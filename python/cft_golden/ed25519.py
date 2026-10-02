# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""Ed25519, for the certificates' detached signature: RFC 8032, section 5.1.

docs/CERTIFICATES.md (version 2, "The detached signature") signs a
certificate's body hash with Ed25519, and Python's standard library has
none. This module is written from the RFC's specification - the curve,
the encodings, and the key generation, signing and verification steps of
section 5.1 - in the RFC's own terms and nothing else's, and
python/tests/test_ed25519.py holds it to section 7.1's test vectors.

    public_key(secret)              the 32-byte public key of a 32-byte
                                    secret (5.1.5)
    sign(secret, message)           the 64-byte signature (5.1.6)
    verify(public, message, sig)    True or False (5.1.7)

The curve is the twisted Edwards curve -x^2 + y^2 = 1 + d x^2 y^2 over
GF(p), p = 2^255 - 19, d = -121665/121666, with the base point B whose y
is 4/5 and whose x is even, of prime order L (5.1, table 1). Points are
held in extended homogeneous coordinates (X, Y, Z, T): x = X/Z, y = Y/Z
and x y = T/Z (5.1.4).

What it is not:
  * constant-time. Python's integers take time that depends on their
    values, and the scalar multiplication branches on the scalar's bits,
    so signing with a secret key on a machine an adversary can time
    leaks it. The project signs its own certificates on its own
    machines; a key that must survive such an adversary belongs in a
    constant-time implementation (docs/CERTIFICATES.md says so);
  * fast: a signature or a verification is a few milliseconds of big
    integer arithmetic, which is all a certificate needs;
  * a key store. The secret is handed in as bytes and nothing here keeps,
    zeroes or protects it (python/cft_sign.py writes a key file).

Verification is the RFC's: R and A must decode (5.1.3: y below p, a
square root that exists, no "negative zero"), S must be below L, and the
cofactored group equation [8][S]B = [8]R + [8][k]A must hold - the
equation 5.1.7 states, of which the cofactorless [S]B = R + [k]A is a
sufficient special case.
"""

import hashlib

# ---- the field and the curve (RFC 8032 5.1, table 1) ----------------------

P = (1 << 255) - 19
L = (1 << 252) + 27742317777372353535851937790883648493
D = (-121665 * pow(121666, P - 2, P)) % P
# a square root of -1 mod p: 2^((p-1)/4)
SQRT_M1 = pow(2, (P - 1) // 4, P)

SECRET_BYTES = 32
PUBLIC_BYTES = 32
SIGNATURE_BYTES = 64


def _inv(a):
    """a^-1 mod p, by Fermat (p is prime)."""
    return pow(a, P - 2, P)


def _recover_x(y, sign):
    """The x with -x^2 + y^2 = 1 + d x^2 y^2 and x's low bit `sign`, or
    None (5.1.3, steps 2 to 4). x^2 = u/v with u = y^2 - 1 and
    v = d y^2 + 1; the candidate root of u/v is u v^3 (u v^7)^((p-5)/8)."""
    if y >= P:
        return None
    u = (y * y - 1) % P
    v = (D * y * y + 1) % P
    x = (u * pow(v, 3, P) * pow(u * pow(v, 7, P), (P - 5) // 8, P)) % P
    vx2 = (v * x * x) % P
    if vx2 == u:
        pass
    elif vx2 == (-u) % P:
        x = (x * SQRT_M1) % P
    else:
        return None                     # u/v is not a square
    if x == 0 and sign == 1:
        return None                     # "negative zero" is not a point
    if x & 1 != sign:
        x = P - x
    return x


_BY = (4 * _inv(5)) % P
_BX = _recover_x(_BY, 0)
B = (_BX, _BY, 1, (_BX * _BY) % P)
IDENTITY = (0, 1, 1, 0)


# ---- the group law in extended coordinates (5.1.4) ----------------------

def _add(p1, p2):
    """P1 + P2. The formulas for a = -1 are complete on this curve (d is
    not a square mod p), so they hold for P1 = P2 and for the identity
    too."""
    x1, y1, z1, t1 = p1
    x2, y2, z2, t2 = p2
    a = ((y1 - x1) * (y2 - x2)) % P
    b = ((y1 + x1) * (y2 + x2)) % P
    c = (2 * D * t1 * t2) % P
    d = (2 * z1 * z2) % P
    e, f, g, h = b - a, d - c, d + c, b + a
    return ((e * f) % P, (g * h) % P, (f * g) % P, (e * h) % P)


def _double(p1):
    """2 P1, by the doubling formulas for a = -1."""
    x1, y1, z1, _t1 = p1
    a = (x1 * x1) % P
    b = (y1 * y1) % P
    c = (2 * z1 * z1) % P
    h = a + b
    e = (h - (x1 + y1) * (x1 + y1)) % P
    g = (a - b) % P
    f = (c + g) % P
    return ((e * f) % P, (g * h) % P, (f * g) % P, (e * h) % P)


def _mul(k, point):
    """[k] point, for an integer k >= 0: double and add, from k's top
    bit down."""
    acc = IDENTITY
    for i in range(k.bit_length() - 1, -1, -1):
        acc = _double(acc)
        if (k >> i) & 1:
            acc = _add(acc, point)
    return acc


def _same(p1, p2):
    """P1 = P2 as points: X1/Z1 = X2/Z2 and Y1/Z1 = Y2/Z2."""
    x1, y1, z1, _ = p1
    x2, y2, z2, _ = p2
    return (x1 * z2 - x2 * z1) % P == 0 and (y1 * z2 - y2 * z1) % P == 0


# ---- the encodings (5.1.2, 5.1.3) ---------------------------------------

def encode_point(point):
    """32 bytes: y little-endian, with x's low bit in the top bit of the
    last byte."""
    x, y, z, _ = point
    zi = _inv(z)
    x, y = (x * zi) % P, (y * zi) % P
    return (y | ((x & 1) << 255)).to_bytes(32, "little")


def decode_point(data):
    """The point 32 bytes encode, or None where they encode none: y not
    below p, no square root, or an x of zero with its sign bit set."""
    if len(data) != 32:
        return None
    n = int.from_bytes(data, "little")
    sign, y = n >> 255, n & ((1 << 255) - 1)
    x = _recover_x(y, sign)
    if x is None:
        return None
    return (x, y, 1, (x * y) % P)


def _sha512_int(*parts):
    """SHA-512 of the parts, read as a little-endian integer."""
    return int.from_bytes(hashlib.sha512(b"".join(parts)).digest(),
                          "little")


# ---- keys, signatures, verification (5.1.5 to 5.1.7) --------------------

def _expand(secret):
    """(s, prefix): the secret key's hash, its first half pruned into the
    scalar s and its second half the prefix the nonce is drawn from."""
    if not isinstance(secret, (bytes, bytearray)) or \
            len(secret) != SECRET_BYTES:
        raise ValueError(f"an Ed25519 secret key is {SECRET_BYTES} bytes")
    h = hashlib.sha512(bytes(secret)).digest()
    a = bytearray(h[:32])
    a[0] &= 0xF8            # the lowest three bits cleared
    a[31] &= 0x7F           # the highest bit cleared
    a[31] |= 0x40           # the second highest set
    return int.from_bytes(a, "little"), h[32:]


def public_key(secret):
    """The 32-byte public key of a 32-byte secret key: [s]B, encoded."""
    s, _ = _expand(secret)
    return encode_point(_mul(s, B))


def sign(secret, message):
    """The 64-byte signature R || S of `message` under `secret`. It is
    deterministic: the nonce r is SHA-512(prefix || M) mod L, so one key
    and one message give one signature (RFC 8032, section 1)."""
    s, prefix = _expand(secret)
    message = bytes(message)
    a_enc = encode_point(_mul(s, B))
    r = _sha512_int(prefix, message) % L
    r_enc = encode_point(_mul(r, B))
    k = _sha512_int(r_enc, a_enc, message) % L
    big_s = (r + k * s) % L
    return r_enc + big_s.to_bytes(32, "little")


def verify(public, message, signature):
    """Does `signature` verify for `message` under the 32-byte `public`
    key? False for any key or signature that does not decode, any S at
    or above L, and any that fails the group equation."""
    if not isinstance(public, (bytes, bytearray)) or \
            len(public) != PUBLIC_BYTES:
        return False
    if not isinstance(signature, (bytes, bytearray)) or \
            len(signature) != SIGNATURE_BYTES:
        return False
    public, signature = bytes(public), bytes(signature)
    a_pt = decode_point(public)
    r_pt = decode_point(signature[:32])
    if a_pt is None or r_pt is None:
        return False
    big_s = int.from_bytes(signature[32:], "little")
    if big_s >= L:
        return False
    k = _sha512_int(signature[:32], public, bytes(message)) % L
    left = _mul(8, _mul(big_s, B))
    right = _mul(8, _add(r_pt, _mul(k, a_pt)))
    return _same(left, right)
