# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""Ed25519 (python/cft_golden/ed25519.py) held to RFC 8032.

The five test vectors of RFC 8032 section 7.1 ("Test Vectors for
Ed25519"), each by its secret key, public key, message and signature,
read from rfc-editor.org's text of the RFC on 2026-10-02. TEST 1024's
message is 1,023 bytes; it was rebuilt from three readings of the page
and is the one string the RFC's signature verifies over, by an
implementation independent of this one (the CV2B parcel's ledger), and
its SHA-256 is held below so that an edit to it is seen.

Then what 5.1.3 and 5.1.7 make a verifier refuse: a key or an R that
does not decode (y at or above p, no square root, an x of zero with its
sign bit set), an S at or above L, the wrong lengths, and a signature
that verifies for another message or another key. And one refusal the
RFC leaves to its user: the eight keys of small order (verifier-VCV2B,
2026-10-02).

The vectors below the RFC's - SMALL_ORDER, UNDECODABLE and S_EDGES - are
for an implementation in another language to be held to as well (the C
half's Ed25519, docs/CERTIFICATES.md): each is refused, by `verify`, and
a key of small order by name wherever a certificate's key is read.
"""

import hashlib
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cft_golden import ed25519 as E  # noqa: E402

TEST_1024_MESSAGE = (
    "08b8b2b733424243760fe426a4b54908632110a66c2f6591eabd3345e3e4eb98"
    "fa6e264bf09efe12ee50f8f54e9f77b1e355f6c50544e23fb1433ddf73be84d8"
    "79de7c0046dc4996d9e773f4bc9efe5738829adb26c81b37c93a1b270b20329d"
    "658675fc6ea534e0810a4432826bf58c941efb65d57a338bbd2e26640f89ffbc"
    "1a858efcb8550ee3a5e1998bd177e93a7363c344fe6b199ee5d02e82d522c4fe"
    "ba15452f80288a821a579116ec6dad2b3b310da903401aa62100ab5d1a36553e"
    "06203b33890cc9b832f79ef80560ccb9a39ce767967ed628c6ad573cb116dbef"
    "efd75499da96bd68a8a97b928a8bbc103b6621fcde2beca1231d206be6cd9ec7"
    "aff6f6c94fcd7204ed3455c68c83f4a41da4af2b74ef5c53f1d8ac70bdcb7ed1"
    "85ce81bd84359d44254d95629e9855a94a7c1958d1f8ada5d0532ed8a5aa3fb2"
    "d17ba70eb6248e594e1a2297acbbb39d502f1a8c6eb6f1ce22b3de1a1f40cc24"
    "554119a831a9aad6079cad88425de6bde1a9187ebb6092cf67bf2b13fd65f270"
    "88d78b7e883c8759d2c4f5c65adb7553878ad575f9fad878e80a0c9ba63bcbcc"
    "2732e69485bbc9c90bfbd62481d9089beccf80cfe2df16a2cf65bd92dd597b07"
    "07e0917af48bbb75fed413d238f5555a7a569d80c3414a8d0859dc65a46128ba"
    "b27af87a71314f318c782b23ebfe808b82b0ce26401d2e22f04d83d1255dc51a"
    "ddd3b75a2b1ae0784504df543af8969be3ea7082ff7fc9888c144da2af58429e"
    "c96031dbcad3dad9af0dcbaaaf268cb8fcffead94f3c7ca495e056a9b47acdb7"
    "51fb73e666c6c655ade8297297d07ad1ba5e43f1bca32301651339e22904cc8c"
    "42f58c30c04aafdb038dda0847dd988dcda6f3bfd15c4b4c4525004aa06eeff8"
    "ca61783aacec57fb3d1f92b0fe2fd1a85f6724517b65e614ad6808d6f6ee34df"
    "f7310fdc82aebfd904b01e1dc54b2927094b2db68d6f903b68401adebf5a7e08"
    "d78ff4ef5d63653a65040cf9bfd4aca7984a74d37145986780fc0b16ac451649"
    "de6188a7dbdf191f64b5fc5e2ab47b57f7f7276cd419c17a3ca8e1b939ae49e4"
    "88acba6b965610b5480109c8b17b80e1b7b750dfc7598d5d5011fd2dcc5600a3"
    "2ef5b52a1ecc820e308aa342721aac0943bf6686b64b2579376504ccc493d97e"
    "6aed3fb0f9cd71a43dd497f01f17c0e2cb3797aa2a2f256656168e6c496afc5f"
    "b93246f6b1116398a346f1a641f3b041e989f7914f90cc2c7fff357876e506b5"
    "0d334ba77c225bc307ba537152f3f1610e4eafe595f6d9d90d11faa933a15ef1"
    "369546868a7f3a45a96768d40fd9d03412c091c6315cf4fde7cb68606937380d"
    "b2eaaa707b4c4185c32eddcdd306705e4dc1ffc872eeee475a64dfac86aba41c"
    "0618983f8741c5ef68d3a101e8a3b8cac60c905c15fc910840b94c00a0b9d0")
TEST_1024_SHA256 = ("358c67baee6b3e0265787951d1840a84"
                    "68b9e9044852f1c67229a892b2cc0d22")

# (name, secret key, public key, message, signature), RFC 8032 7.1
VECTORS = [
    ("TEST 1",
     "9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60",
     "d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a",
     "",
     "e5564300c360ac729086e2cc806e828a84877f1eb8e5d974d873e06522490155"
     "5fb8821590a33bacc61e39701cf9b46bd25bf5f0595bbe24655141438e7a100b"),
    ("TEST 2",
     "4ccd089b28ff96da9db6c346ec114e0f5b8a319f35aba624da8cf6ed4fb8a6fb",
     "3d4017c3e843895a92b70aa74d1b7ebc9c982ccf2ec4968cc0cd55f12af4660c",
     "72",
     "92a009a9f0d4cab8720e820b5f642540a2b27b5416503f8fb3762223ebdb69da"
     "085ac1e43e15996e458f3613d0f11d8c387b2eaeb4302aeeb00d291612bb0c00"),
    ("TEST 3",
     "c5aa8df43f9f837bedb7442f31dcb7b166d38535076f094b85ce3a2e0b4458f7",
     "fc51cd8e6218a1a38da47ed00230f0580816ed13ba3303ac5deb911548908025",
     "af82",
     "6291d657deec24024827e69c3abe01a30ce548a284743a445e3680d7db5ac3ac"
     "18ff9b538d16f290ae67f760984dc6594a7c15e9716ed28dc027beceea1ec40a"),
    ("TEST 1024",
     "f5e5767cf153319517630f226876b86c8160cc583bc013744c6bf255f5cc0ee5",
     "278117fc144c72340f67d0f2316e8386ceffbf2b2428c9c51fef7c597f1d426e",
     TEST_1024_MESSAGE,
     "0aab4c900501b3e24d7cdf4663326a3a87df5e4843b2cbdb67cbf6e460fec350"
     "aa5371b1508f9f4528ecea23c436d94b5e8fcd4f681e30a6ac00a9704a188a03"),
    ("TEST SHA(abc)",
     "833fe62409237b9d62ec77587520911e9a759cec1d19755b7da901b96dca3d42",
     "ec172b93ad5e563bf4932c70e1245034c35467ef2efd4d64ebf819683467e2bf",
     "ddaf35a193617abacc417349ae20413112e6fa4e89a97ea20a9eeee64b55d39a"
     "2192992a274fc1a836ba3c23a3feebbd454d4423643ce80e2a9ac94fa54ca49f",
     "dc2a4459e7369633a52b1bf277839a00201009a3efbf3ecb69bea2186c26b589"
     "09351fc9ac90b3ecfdfbc7c66431e0303dca179c138ac17ad9bef1177331a704"),
]


# The eight keys of small order - every point of the curve's torsion,
# [8]A the identity - each in its one encoding, computed here (below) as
# the multiples of [L]P for the point P whose y is 3 and x even. Under such
# a key [8][k]A vanishes, so any R = [S]B satisfies the cofactored
# equation for every message: verifier-VCV2B's forgery, R = [1234567]B
# and S = 1234567. verify refuses them all.
SMALL_ORDER = (
    ("order 1, the identity",
     "0100000000000000000000000000000000000000000000000000000000000000"),
    ("order 2",
     "ecffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff7f"),
    ("order 4, x even",
     "0000000000000000000000000000000000000000000000000000000000000000"),
    ("order 4, x odd",
     "0000000000000000000000000000000000000000000000000000000000000080"),
    ("order 8",
     "26e8958fc2b227b045c3f489f2ef98f0d5dfac05d3c63339b13802886d53fc05"),
    ("order 8",
     "26e8958fc2b227b045c3f489f2ef98f0d5dfac05d3c63339b13802886d53fc85"),
    ("order 8",
     "c7176a703d4dd84fba3c0b760d10670f2a2053fa2c39ccc64ec7fd7792ac037a"),
    ("order 8",
     "c7176a703d4dd84fba3c0b760d10670f2a2053fa2c39ccc64ec7fd7792ac03fa"),
)
# 5.1.3's refusals as encodings: (what, the integer they spell, 32 bytes).
UNDECODABLE = (
    ("y = p", (1 << 255) - 19,
     "edffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff7f"),
    ("y = p + 1, the identity's y unreduced", (1 << 255) - 18,
     "eeffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff7f"),
    ("y = 2^255 - 1", (1 << 255) - 1,
     "ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff7f"),
    ("y = 2, whose x^2 has no square root", 2,
     "0200000000000000000000000000000000000000000000000000000000000000"),
    ("y = 1 with the sign bit set: x = 0, negative", 1 | (1 << 255),
     "0100000000000000000000000000000000000000000000000000000000000080"),
    ("y = p - 1 with the sign bit set: x = 0, negative",
     ((1 << 255) - 20) | (1 << 255),
     "ecffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff"),
)
# 5.1.7's S at or above L, on TEST 1's key and empty message: (what, the
# signature). S + L is TEST 1's S plus L, the same scalar mod L.
S_EDGES = (
    ("S + L",
     "e5564300c360ac729086e2cc806e828a84877f1eb8e5d974d873e06522490155"
     "4c8c7872aa064e049dbb3013fbf29380d25bf5f0595bbe24655141438e7a101b"),
    ("S = L",
     "e5564300c360ac729086e2cc806e828a84877f1eb8e5d974d873e06522490155"
     "edd3f55c1a631258d69cf7a2def9de1400000000000000000000000000000010"),
    ("S = 2^256 - 1",
     "e5564300c360ac729086e2cc806e828a84877f1eb8e5d974d873e06522490155"
     "ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff"),
)


def _v(name):
    for v in VECTORS:
        if v[0] == name:
            return tuple(bytes.fromhex(x) for x in v[1:])
    raise KeyError(name)


def test_the_vectors_are_the_rfcs():
    """The 1,023-byte message is held to its digest, and the SHA(abc)
    message is SHA-512 of "abc", as the RFC says it is."""
    msg = bytes.fromhex(TEST_1024_MESSAGE)
    assert len(msg) == 1023
    assert hashlib.sha256(msg).hexdigest() == TEST_1024_SHA256
    assert _v("TEST SHA(abc)")[2] == hashlib.sha512(b"abc").digest()


@pytest.mark.parametrize("name", [v[0] for v in VECTORS])
def test_rfc_8032_section_7_1(name):
    sk, pk, msg, sig = _v(name)
    assert E.public_key(sk) == pk
    assert E.sign(sk, msg) == sig
    assert E.verify(pk, msg, sig)


@pytest.mark.parametrize("name", [v[0] for v in VECTORS])
def test_a_bit_changed_anywhere_is_refused(name):
    """Every bit of the signature, and the message's and the key's first
    and last bytes: each change, alone, fails verification."""
    sk, pk, msg, sig = _v(name)
    for i in range(8 * len(sig)):
        bad = bytearray(sig)
        bad[i // 8] ^= 1 << (i % 8)
        assert not E.verify(pk, msg, bytes(bad)), f"signature bit {i}"
    if msg:
        for i in (0, len(msg) - 1):
            bad = bytearray(msg)
            bad[i] ^= 1
            assert not E.verify(pk, bytes(bad), sig)
    assert not E.verify(pk, msg + b"\x00", sig)
    for i in (0, 31):
        bad = bytearray(pk)
        bad[i] ^= 1
        assert not E.verify(bytes(bad), msg, sig)


def test_another_keys_signature_is_refused():
    sk1, pk1, msg, sig1 = _v("TEST 2")
    sk2, pk2, _m, _s = _v("TEST 3")
    assert not E.verify(pk2, msg, sig1)
    assert E.verify(pk2, msg, E.sign(sk2, msg))


def test_signing_is_deterministic():
    """RFC 8032 section 1: no random number a signature. One key and one
    message give one signature, byte for byte, which is why a gate can
    hold a signature to committed bytes."""
    sk = bytes(range(32, 64))
    a = E.sign(sk, b"cft-signature 1\x00" + bytes(32))
    assert a == E.sign(sk, b"cft-signature 1\x00" + bytes(32))
    assert a != E.sign(sk, b"cft-signature 1\x00" + bytes(31) + b"\x01")


def test_an_s_at_or_above_l_is_refused():
    """5.1.7: S must be below L. S + L is the same scalar mod L, so a
    verifier that reduced it would accept a second spelling of one
    signature."""
    sk, pk, msg, sig = _v("TEST 1")
    s = int.from_bytes(sig[32:], "little")
    for t in (s + E.L, E.L, (1 << 256) - 1):
        if t >= 1 << 256:
            continue
        assert not E.verify(pk, msg, sig[:32] + t.to_bytes(32, "little"))


def _no_root_y():
    """A y below p whose x^2 has no square root mod p."""
    for y in range(2, 100):
        if E._recover_x(y, 0) is None:
            return y
    raise AssertionError("no y without a root below 100")


def test_what_does_not_decode_is_refused():
    """5.1.3: y at or above p; no square root; x = 0 with its sign bit
    set. Each as the key, and each as R."""
    sk, pk, msg, sig = _v("TEST 1")
    p_enc = E.P.to_bytes(32, "little")                  # y = p
    big = ((1 << 255) - 1).to_bytes(32, "little")       # y = 2^255 - 1
    no_root = _no_root_y().to_bytes(32, "little")
    neg_zero = (1 | (1 << 255)).to_bytes(32, "little")  # y = 1, x = -0
    for bad in (p_enc, big, no_root, neg_zero):
        assert E.decode_point(bad) is None
        assert not E.verify(bad, msg, sig)
        assert not E.verify(pk, msg, bad + sig[32:])
    # y = 1 with the sign bit clear is the identity, which decodes
    ident = (1).to_bytes(32, "little")
    assert E.decode_point(ident) is not None


def test_the_wrong_lengths_are_refused():
    sk, pk, msg, sig = _v("TEST 1")
    assert not E.verify(pk[:31], msg, sig)
    assert not E.verify(pk + b"\x00", msg, sig)
    assert not E.verify(pk, msg, sig[:63])
    assert not E.verify(pk, msg, sig + b"\x00")
    assert not E.verify("not bytes", msg, sig)
    for bad in (sk[:31], sk + b"\x00", "x" * 32):
        with pytest.raises(ValueError):
            E.public_key(bad)
        with pytest.raises(ValueError):
            E.sign(bad, msg)


def test_verification_is_the_cofactored_equation():
    """5.1.7 checks [8][S]B = [8]R + [8][k]A; [S]B = R + [k]A is a
    sufficient special case, and the two part on a key with a small-order
    component. A' = A + T, with T = (0, -1) of order 2, signed by A's
    secret with k drawn over A': the cofactored equation holds, and the
    cofactorless one fails wherever k is odd. So this verifier accepts
    such a signature, and an auditor written in another language must too
    (docs/CERTIFICATES.md, "The detached signature")."""
    t2 = (0, E.P - 1, 1, 0)                     # (0, -1): order 2
    assert E._same(E._double(t2), E.IDENTITY)
    secret = bytes(range(32, 64))
    s, prefix = E._expand(secret)
    a2 = E._add(E._mul(s, E.B), t2)
    pub2 = E.encode_point(a2)
    found = 0
    for i in range(64):
        msg = b"cofactor " + bytes([i])
        r = E._sha512_int(prefix, msg) % E.L
        r_enc = E.encode_point(E._mul(r, E.B))
        k = E._sha512_int(r_enc, pub2, msg) % E.L
        sig = r_enc + ((r + k * s) % E.L).to_bytes(32, "little")
        assert E.verify(pub2, msg, sig)
        lhs = E._mul(int.from_bytes(sig[32:], "little"), E.B)
        rhs = E._add(E.decode_point(r_enc), E._mul(k, E.decode_point(pub2)))
        assert E._same(lhs, rhs) == (k % 2 == 0)
        found += k % 2
    assert found, "no odd k among 64 messages"


def test_the_small_order_keys_are_the_curves_torsion():
    """SMALL_ORDER is every point T with [8]T the identity, each once
    and each at its order: the multiples [k]Q, k = 0..7, of Q = [L]P for
    the point P whose y is 3 and x even, which has order 8."""
    x = E._recover_x(3, 0)
    q = E._mul(E.L, (x, 3, 1, (x * 3) % E.P))
    assert not E._same(E._mul(4, q), E.IDENTITY)
    assert {E.encode_point(E._mul(k, q)).hex() for k in range(8)} == \
        {h for _w, h in SMALL_ORDER}
    for what, h in SMALL_ORDER:
        a = E.decode_point(bytes.fromhex(h))
        assert a is not None and E.encode_point(a).hex() == h, what
        order = next(n for n in (1, 2, 4, 8)
                     if E._same(E._mul(n, a), E.IDENTITY))
        assert what.startswith(f"order {order}"), what


@pytest.mark.parametrize("what,key", SMALL_ORDER)
def test_a_key_of_small_order_is_refused(what, key):
    """verifier-VCV2B's forgery: under a key of small order, R = [r]B
    and S = r satisfy the cofactored equation for every message, since
    [8][k]A is the identity - so verify refuses the key itself, and
    small_order names it."""
    pub = bytes.fromhex(key)
    assert E.small_order(pub), what
    r = 1234567
    sig = E.encode_point(E._mul(r, E.B)) + r.to_bytes(32, "little")
    a = E.decode_point(pub)
    for msg in (b"", b"any message", b"cft-signature 1\x00" + bytes(32)):
        k = E._sha512_int(sig[:32], pub, msg) % E.L
        lhs = E._mul(8, E._mul(r, E.B))
        rhs = E._mul(8, E._add(E.decode_point(sig[:32]), E._mul(k, a)))
        assert E._same(lhs, rhs), "the equation alone accepts it"
        assert not E.verify(pub, msg, sig), what


def test_a_key_with_a_small_order_part_is_accepted():
    """A key A + T, with A of prime order and T of small order, is not of
    small order: signing under it needs A's secret, and the cofactored
    equation lets T pass (test_verification_is_the_cofactored_equation
    signs under one). small_order is False for it, for the RFC's keys,
    and for what is not a key."""
    s, _ = E._expand(bytes(range(32, 64)))
    a = E._mul(s, E.B)
    for _w, h in SMALL_ORDER:
        mixed = E.encode_point(E._add(a, E.decode_point(bytes.fromhex(h))))
        assert not E.small_order(mixed)
    for v in VECTORS:
        assert not E.small_order(bytes.fromhex(v[2]))
    for bad in (b"", bytes(31), bytes(33), "x" * 32):
        assert not E.small_order(bad)
    for _w, _n, h in UNDECODABLE:
        assert not E.small_order(bytes.fromhex(h))


@pytest.mark.parametrize("what,n,enc", UNDECODABLE)
def test_the_undecodable_vectors(what, n, enc):
    """Each spells its integer, decodes to no point, and is refused as
    the key and as R."""
    data = bytes.fromhex(enc)
    assert data == n.to_bytes(32, "little"), what
    assert E.decode_point(data) is None, what
    sk, pk, msg, sig = _v("TEST 1")
    assert not E.verify(data, msg, sig)
    assert not E.verify(pk, msg, data + sig[32:])


@pytest.mark.parametrize("what,sig", S_EDGES)
def test_the_s_edge_vectors(what, sig):
    """Each is TEST 1's R with an S at or above L: refused, though S + L
    is TEST 1's scalar mod L."""
    sk, pk, msg, good = _v("TEST 1")
    bad = bytes.fromhex(sig)
    assert bad[:32] == good[:32]
    assert int.from_bytes(bad[32:], "little") >= E.L
    assert not E.verify(pk, msg, bad), what
    if what == "S + L":
        assert int.from_bytes(bad[32:], "little") - E.L == \
            int.from_bytes(good[32:], "little")


def test_the_curve_and_its_base_point():
    """B lies on -x^2 + y^2 = 1 + d x^2 y^2, its y is 4/5 and its x is
    even, and its order is L: [L]B is the identity and B is not."""
    x, y, z, t = E.B
    assert z == 1 and t == (x * y) % E.P
    assert (-x * x + y * y - 1 - E.D * x * x * y * y) % E.P == 0
    assert (5 * y) % E.P == 4 and x % 2 == 0
    assert E._same(E._mul(E.L, E.B), E.IDENTITY)
    assert not E._same(E.B, E.IDENTITY)
    # the doubling and the addition agree
    for k in (1, 2, 3, 7, 1000):
        p = E._mul(k, E.B)
        assert E._same(E._double(p), E._add(p, p))
    # an encoding reads back as its point
    for k in (1, 2, 5, 12345):
        p = E._mul(k, E.B)
        assert E._same(E.decode_point(E.encode_point(p)), p)
