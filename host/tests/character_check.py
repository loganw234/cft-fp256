# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""The clause-5.12 character conversions and the 9.7 payload
operations, against the golden model.

    python3 host/tests/character_check.py               # standard sweep
    python3 host/tests/character_check.py --formats fp64
    python3 host/tests/character_check.py --trials 200  # longer randoms

Same discipline as clause5_check.py: python/cft_golden/chars.py defines
every string, every encoding and every flag; this replays
host/src/chars.c against it - per call so flags compare per element,
plus batch cases so the batch loop and the flag OR are exercised.

The pools lean on the families where a decimal conversion actually
breaks: halfway cases decided by the last digit, digit strings far
longer than the format's precision, exponents at and past the bands
where the library answers without computing, subnormal landings, every
spelling of every special, and the round trip at Pmin - which is
checked in both directions AND shown to FAIL at Pmin - 1, because a
round-trip guarantee nobody has seen break is a guarantee nobody has
tested.
"""

import argparse
import ctypes
import os
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "python"))

from cft_golden import (  # noqa: E402
    FORMATS, PREC_CODE, RND_MODES, chars, vectors,
    inf_bits, max_normal_bits, max_subnormal_bits, min_normal_bits,
    min_subnormal_bits, one_bits, qnan_bits, snan_bits, zero_bits,
)
from cft_golden import softfloat as sf  # noqa: E402

INVAL = 1                                    # CFT_ERR_INVALID_ARGUMENT


def load_library():
    override = os.environ.get("CFT_LIB")
    if override:
        path = Path(override)
    else:
        name = {"win32": "cft.dll", "cygwin": "cft.dll",
                "darwin": "libcft.dylib"}.get(sys.platform, "libcft.so")
        path = ROOT / "host" / name
    if not path.exists():
        raise SystemExit(
            f"{path} not found - build it first:\n"
            "    make -C host\n"
            "or point CFT_LIB at the shared library.")
    return ctypes.CDLL(str(path))


def bind(lib):
    u32p = ctypes.POINTER(ctypes.c_uint32)
    szp = ctypes.POINTER(ctypes.c_size_t)
    vp, sz = ctypes.c_void_p, ctypes.c_size_t
    i = ctypes.c_int
    cpp = ctypes.POINTER(ctypes.c_char_p)
    lib.cft_open.argtypes = [ctypes.c_char_p, i, ctypes.POINTER(vp)]
    lib.cft_open.restype = i
    lib.cft_close.argtypes = [vp]
    lib.cft_close.restype = None
    lib.cft_format_decimal_digits.argtypes = [i]
    lib.cft_format_decimal_digits.restype = sz
    lib.cft_from_decimal_char.argtypes = [vp, i, i, cpp, vp, sz, szp, u32p]
    lib.cft_from_hex_char.argtypes = [vp, i, i, cpp, vp, sz, szp, u32p]
    lib.cft_to_decimal_char.argtypes = [vp, i, i, vp, sz, ctypes.c_char_p,
                                        sz, szp, u32p]
    lib.cft_to_hex_char.argtypes = [vp, i, vp, ctypes.c_char_p, sz, szp]
    for nm in ("cft_get_payload", "cft_set_payload",
               "cft_set_payload_signaling"):
        getattr(lib, nm).argtypes = [vp, i, vp, vp, sz]
    for nm in ("cft_from_decimal_char", "cft_from_hex_char",
               "cft_to_decimal_char", "cft_to_hex_char", "cft_get_payload",
               "cft_set_payload", "cft_set_payload_signaling"):
        getattr(lib, nm).restype = i


def open_dev(lib):
    dev = ctypes.c_void_p()
    st = lib.cft_open(None, 0, ctypes.byref(dev))
    if st != 0:
        raise SystemExit(f"cft_open failed: {st}")
    return dev


def enc(fmt, bits_list):
    esz = fmt.width // 8
    return b"".join(b.to_bytes(esz, "little") for b in bits_list)


def dec(fmt, raw, n):
    esz = fmt.width // 8
    return [int.from_bytes(raw[i * esz:(i + 1) * esz], "little")
            for i in range(n)]


CHECKED = 0


def note(k=1):
    global CHECKED
    CHECKED += k


# ----------------------------------------------------------------------
# thin wrappers over the two shapes
# ----------------------------------------------------------------------

def lib_from(lib, dev, fmt, texts, rnd, hexmode=False):
    """-> (status, [bits], flags, bad_index)"""
    n = len(texts)
    arr = (ctypes.c_char_p * max(n, 1))(*[t.encode() for t in texts])
    out = ctypes.create_string_buffer(max(n, 1) * (fmt.width // 8))
    fl = ctypes.c_uint32(1 << 31)
    bad = ctypes.c_size_t(0xdead)
    fn = lib.cft_from_hex_char if hexmode else lib.cft_from_decimal_char
    st = fn(dev, PREC_CODE[fmt.name], rnd, arr, out, n,
            ctypes.byref(bad), ctypes.byref(fl))
    return st, dec(fmt, out.raw, n), fl.value, bad.value


def lib_to_decimal(lib, dev, fmt, bits, digits, rnd):
    """-> (status, text, flags), using the two-call sizing protocol so
    that protocol is exercised on every single call rather than in one
    token test."""
    a = enc(fmt, [bits])
    need = ctypes.c_size_t(0)
    fl = ctypes.c_uint32(1 << 31)
    st = lib.cft_to_decimal_char(dev, PREC_CODE[fmt.name], rnd, a, digits,
                                 None, 0, ctypes.byref(need),
                                 ctypes.byref(fl))
    assert st == INVAL and need.value > 1, (st, need.value)
    buf = ctypes.create_string_buffer(need.value)
    got = ctypes.c_size_t(0)
    st = lib.cft_to_decimal_char(dev, PREC_CODE[fmt.name], rnd, a, digits,
                                 buf, need.value, ctypes.byref(got),
                                 ctypes.byref(fl))
    assert got.value == need.value, (got.value, need.value)
    return st, buf.value.decode(), fl.value


def lib_to_hex(lib, dev, fmt, bits):
    a = enc(fmt, [bits])
    need = ctypes.c_size_t(0)
    st = lib.cft_to_hex_char(dev, PREC_CODE[fmt.name], a, None, 0,
                             ctypes.byref(need))
    assert st == INVAL and need.value > 1, (st, need.value)
    buf = ctypes.create_string_buffer(need.value)
    st = lib.cft_to_hex_char(dev, PREC_CODE[fmt.name], a, buf, need.value,
                             ctypes.byref(need))
    return st, buf.value.decode()


# ----------------------------------------------------------------------
# pools
# ----------------------------------------------------------------------

def cheap_to_write(fmt, bits):
    """Is writing this encoding out cheap?

    The exact decimal of a value near either end of fp128's or fp256's
    exponent range runs to tens of thousands of digits, and the library
    derives it in full for every digit count (cft.h carries the cost
    note). Those values ARE covered - deliberately, by extreme_pool
    below, across the digit modes and every attribute - but sweeping
    them densely as well would spend minutes re-deriving the same
    powering and would add no case anyone has not already seen."""
    kind, _, m, e, _, _ = chars._decode(fmt, bits)
    if kind != "finite" or fmt.width <= 64:
        return True
    return abs(e + m.bit_length() - 1) <= 400


def encoding_pool(fmt, extra, seed=0xC1A5):
    """Encodings worth converting OUT, at every digit count."""
    rng = random.Random(seed)
    pool = list(vectors.interesting_operands(fmt))
    pool += [qnan_bits(fmt) | 1, qnan_bits(fmt) | (chars.max_payload(fmt) - 1),
             snan_bits(fmt, 1), snan_bits(fmt, chars.max_payload(fmt) - 1),
             fmt.sign_mask | snan_bits(fmt, 3),
             fmt.sign_mask | qnan_bits(fmt) | 7]
    # a spread of ordinary values, and ties on the decimal grid
    for k in (1, 3, 5, 7, 9, 11):
        for s in (0, 1):
            pool.append(sf.round_pack(fmt, s, k, -3, sf.RND_RNE)[0])
            pool.append(sf.round_pack(fmt, s, k * 5, -1, sf.RND_RNE)[0])
    span = 40 if fmt.width > 64 else fmt.emax
    for _ in range(extra):
        s = rng.getrandbits(1)
        e = rng.randint(-span, span)
        m = rng.getrandbits(fmt.prec) | (1 << (fmt.prec - 1))
        pool.append(sf.round_pack(fmt, s, m, e - fmt.man_w, sf.RND_RNE)[0])
    return [b for b in pool if cheap_to_write(fmt, b)]


def extreme_pool(fmt):
    """The handful where the exact decimal is enormous - the ends of
    the exponent range, where a conversion that only ever saw ordinary
    magnitudes would not exercise the powering path at all."""
    return [min_subnormal_bits(fmt, 0), min_subnormal_bits(fmt, 1),
            max_subnormal_bits(fmt, 0), min_normal_bits(fmt, 0),
            max_normal_bits(fmt, 0), max_normal_bits(fmt, 1)]


def decimal_pool(fmt, extra, seed=0x5EED):
    """Sequences worth converting IN, as plain strings."""
    rng = random.Random(seed)
    out = ["0", "-0", "+0", "0.0", ".0", "0.", "00000", "0e100000",
           "-0e-100000",
           "1", "-1", "+1", "1.", ".5", "1.5", "-1.5", "1e0", "1E0",
           "1e+0", "1e-0", "10e-1", "0.1", "0.5", "2.5", "1.25",
           "inf", "-inf", "INF", "Infinity", "-INFINITY", "+inf",
           "nan", "NaN", "-nan", "SNAN", "snan", "-snan",
           "nan(0x1)", "nan(1)", "NAN(0X10)", "snan(0x3)", "-snan(7)",
           "1e400", "-1e400", "1e-400", "1e999999999999",
           "-1e-999999999999", "1e-99999", "9" * 40,
           "0." + "0" * 30 + "1", "123456789012345678901234567890e-15"]
    # the format's own edges, written out exactly, plus one ulp either
    # side of a tie - the cases the last digit decides
    for bits in (min_subnormal_bits(fmt, 0), min_normal_bits(fmt, 0),
                 one_bits(fmt, 0), max_normal_bits(fmt, 0)):
        text, _ = chars.to_decimal(fmt, bits, 0)
        out.append(text)
        out.append("-" + text if not text.startswith("-") else text[1:])
    # exact halfway strings between neighbouring encodings: the tie the
    # attribute has to decide, and the same tie nudged either way
    for bits in (one_bits(fmt, 0), min_normal_bits(fmt, 0),
                 min_subnormal_bits(fmt, 0),
                 sf.round_pack(fmt, 0, 3, -1, sf.RND_RNE)[0]):
        lo = bits
        hi = bits + 1
        kind, sign, m1, e1, _, _ = chars._decode(fmt, lo)
        kind2, _, m2, e2, _, _ = chars._decode(fmt, hi)
        if kind != "finite" or kind2 != "finite":
            continue
        # the exact midpoint is (m1*2^e1 + m2*2^e2)/2, still dyadic
        e = min(e1, e2) - 1
        mid = (m1 << (e1 - e)) + (m2 << (e2 - e))
        assert mid % 2 == 0
        ds, exp10 = chars.exact_digits(mid // 2, e)
        mids = chars._format_finite(sign, ds, exp10)
        out.append(mids)
        out.append("-" + mids)
        # and just off the tie in both directions
        out.append(chars._format_finite(sign, ds + "1", exp10))
        out.append(chars._format_finite(sign, ds[:-1] +
                                        str(int(ds[-1]) - 1) + "9", exp10)
                   if ds[-1] != "0" else mids)
    for _ in range(extra):
        nd = rng.randint(1, 45)
        d = "".join(rng.choice("0123456789") for _ in range(nd))
        k = rng.randint(-(fmt.emax // 3 + 20), fmt.emax // 3 + 20)
        out.append(("-" if rng.getrandbits(1) else "") + d + "e" + str(k))
    return out


REFUSALS = [
    "", "+", "-", ".", "-.", "e5", "+e5", "1e", "1e+", "1e-", "1 ", " 1",
    "1.5.5", "1,5", "0x1p0", "1p5", "1d5", "--1", "1-", "nan(", "nan()",
    "nan(x)", "nan(0x)", "nan(-1)", "inf inity", "infi", "nanx", "snan()",
    "1.5e5x", "0b101", "\t1", "1\n", "1_000", "Infinity2", "nan(0x1) ",
]

HEX_REFUSALS = [
    "", "0x", "0x1", "0x.p0", "0xp+1", "0x1p", "0x1p+", "0x1.8", "1.8p+3",
    "0x1.8e+3", "0x1.8p3.5", "0x1.8p+3x", "0xg.1p+0", "0x1..8p+0",
    " 0x1p+0", "0x1p+0 ", "1e5", "0x1p+0.5",
]


def hex_pool(fmt, extra, seed=0xBEEF):
    rng = random.Random(seed)
    out = ["0x0p+0", "-0x0p+0", "0x0p-999", "0x1p+0", "-0x1p+0", "0X1P+0",
           "0x1.8p+1", "0x.8p+1", "0x8.p-3", "0x1p-1074", "0x1p+1024",
           "0x1p+999999999999", "0x1p-999999999999",
           "0xfffffffffffffffffffffffffffffffffp-4",
           "inf", "-inf", "nan", "snan", "nan(0x2)", "-snan(0x5)"]
    for bits in (min_subnormal_bits(fmt, 0), min_normal_bits(fmt, 0),
                 one_bits(fmt, 0), max_normal_bits(fmt, 1)):
        out.append(chars.to_hex(fmt, bits))
    # one hex digit past the format's precision, which is where the
    # rounding attribute starts to matter
    for _ in range(extra):
        nd = rng.randint(1, fmt.prec // 4 + 4)
        d = "".join(rng.choice("0123456789abcdefABCDEF") for _ in range(nd))
        e = rng.randint(-(fmt.emax + 30), fmt.emax + 30)
        out.append(("-" if rng.getrandbits(1) else "") + "0x" + d +
                   "p" + ("+" if e >= 0 else "") + str(e))
    return out


# ----------------------------------------------------------------------
# the checks
# ----------------------------------------------------------------------

def check_to_decimal(lib, dev, fmt, pool, digit_counts):
    fi = PREC_CODE[fmt.name]
    for rnd in RND_MODES:
        for bits in pool:
            for h in digit_counts:
                st, got, fl = lib_to_decimal(lib, dev, fmt, bits, h, rnd)
                want, wfl = chars.to_decimal(fmt, bits, h, rnd)
                assert st == 0, (st, fmt.name, hex(bits), h, rnd)
                assert (got, fl) == (want, wfl), \
                    ("to_decimal", fmt.name, hex(bits), h, rnd,
                     got[:80], want[:80], fl, wfl)
                note()
    del fi


def check_from_decimal(lib, dev, fmt, texts):
    for rnd in RND_MODES:
        for s in texts:
            st, got, fl, _ = lib_from(lib, dev, fmt, [s], rnd)
            want, wfl = chars.from_decimal(fmt, s, rnd)
            assert st == 0, (st, fmt.name, s[:60], rnd)
            assert (got[0], fl) == (want, wfl), \
                ("from_decimal", fmt.name, s[:60], rnd,
                 hex(got[0]), hex(want), fl, wfl)
            note()
    # one batch, flags as the OR
    st, got, fl, _ = lib_from(lib, dev, fmt, texts, sf.RND_RNE)
    assert st == 0, st
    acc = 0
    for i, s in enumerate(texts):
        want, wfl = chars.from_decimal(fmt, s, sf.RND_RNE)
        assert got[i] == want, ("batch", fmt.name, s[:60])
        acc |= wfl
    assert fl == acc, (fl, acc)
    note(len(texts))


def check_refusals(lib, dev, fmt):
    for s in REFUSALS:
        st, _, _, bad = lib_from(lib, dev, fmt, [s], sf.RND_RNE)
        assert st == INVAL, (fmt.name, "accepted", repr(s))
        try:
            chars.from_decimal(fmt, s, sf.RND_RNE)
            raise AssertionError(("model accepted", repr(s)))
        except chars.CharacterSyntaxError:
            pass
        note()
    for s in HEX_REFUSALS:
        st, _, _, _ = lib_from(lib, dev, fmt, [s], sf.RND_RNE, hexmode=True)
        assert st == INVAL, (fmt.name, "hex accepted", repr(s))
        try:
            chars.from_hex(fmt, s, sf.RND_RNE)
            raise AssertionError(("model accepted hex", repr(s)))
        except chars.CharacterSyntaxError:
            pass
        note()
    # a payload the format cannot hold is in the syntax and still
    # refused, in both parsers
    too_big = "nan(0x%x)" % chars.max_payload(fmt)
    for hexmode in (False, True):
        st, _, _, _ = lib_from(lib, dev, fmt, [too_big], sf.RND_RNE, hexmode)
        assert st == INVAL, (fmt.name, too_big)
        note()
    # the refusal names WHICH element, which is the whole reason
    # bad_index exists
    good = "1.5"
    st, _, _, bad = lib_from(lib, dev, fmt, [good, good, "1.5.5", good],
                             sf.RND_RNE)
    assert st == INVAL and bad == 2, (st, bad)
    note()
    # decimal is not hex and hex is not decimal
    st, _, _, _ = lib_from(lib, dev, fmt, ["0x1p+0"], sf.RND_RNE)
    assert st == INVAL
    st, _, _, _ = lib_from(lib, dev, fmt, ["1.5"], sf.RND_RNE, hexmode=True)
    assert st == INVAL
    note(2)


def check_hex(lib, dev, fmt, epool, texts):
    for bits in epool:
        st, got = lib_to_hex(lib, dev, fmt, bits)
        want = chars.to_hex(fmt, bits)
        assert st == 0 and got == want, \
            ("to_hex", fmt.name, hex(bits), got, want)
        # the shortest EXACT form: it must read back to the same bits
        # in every attribute, because nothing was rounded
        for rnd in RND_MODES:
            st2, back, fl, _ = lib_from(lib, dev, fmt, [got], rnd,
                                        hexmode=True)
            assert st2 == 0 and back[0] == bits and fl == 0, \
                ("hex round trip", fmt.name, hex(bits), got, hex(back[0]), fl)
        note(1 + len(RND_MODES))
    for rnd in RND_MODES:
        for s in texts:
            st, got, fl, _ = lib_from(lib, dev, fmt, [s], rnd, hexmode=True)
            want, wfl = chars.from_hex(fmt, s, rnd)
            assert st == 0, (st, fmt.name, s[:60], rnd)
            assert (got[0], fl) == (want, wfl), \
                ("from_hex", fmt.name, s[:60], rnd, hex(got[0]), hex(want),
                 fl, wfl)
            note()


def check_round_trip(lib, dev, fmt, pool):
    """5.12.2's guarantee, and its edge.

    At Pmin(bf) digits under a round-to-nearest attribute the round
    trip reproduces the encoding - that is the standard's own claim.
    At Pmin - 1 it does not, and this exhibits a pair of neighbouring
    encodings whose Pmin-1-digit decimals collide rather than merely
    asserting that no such pair exists."""
    h = chars.pmin(fmt)
    assert lib.cft_format_decimal_digits(PREC_CODE[fmt.name]) == h
    for rnd in (sf.RND_RNE, sf.RND_RMM):
        for bits in pool:
            kind, _, _, _, _, _ = chars._decode(fmt, bits)
            if kind == "nan":
                continue                 # a NaN has no digits to count
            st, text, _ = lib_to_decimal(lib, dev, fmt, bits, h, rnd)
            assert st == 0
            st, back, _, _ = lib_from(lib, dev, fmt, [text], rnd)
            assert st == 0 and back[0] == bits, \
                ("round trip at Pmin", fmt.name, h, hex(bits), text[:80],
                 hex(back[0]))
            note()
    # And the failure at Pmin - 1. Two neighbouring encodings collide
    # wherever the (h-1)-digit decimal grid is COARSER than the binary
    # one, which is at the top of a binade whose values still lead with
    # the decimal digit 1 - so the search walks down from the largest
    # value of each binade rather than sampling and hoping.
    collided = None
    for k in range(0, min(fmt.emax, 500)):
        top = sf.round_pack(fmt, 0, (1 << fmt.prec) - 1, k - fmt.man_w,
                            sf.RND_RNE)[0]
        for step in range(0, 64):
            x, y = top - step - 1, top - step
            tx, _ = chars.to_decimal(fmt, x, h - 1, sf.RND_RNE)
            ty, _ = chars.to_decimal(fmt, y, h - 1, sf.RND_RNE)
            if tx == ty:
                collided = (x, y, tx)
                break
        if collided:
            break
    assert collided, f"{fmt.name}: no Pmin-1 collision found"
    x, y, text = collided
    # both encodings print the same h-1 digits THROUGH THE LIBRARY,
    # and reading that back can only recover one of them - which is
    # exactly the round trip failing one digit short of Pmin
    for bits in (x, y):
        st, got, _ = lib_to_decimal(lib, dev, fmt, bits, h - 1, sf.RND_RNE)
        assert st == 0 and got == text, (fmt.name, hex(bits), got, text)
    st, back, _, _ = lib_from(lib, dev, fmt, [text], sf.RND_RNE)
    assert st == 0
    # One sequence cannot name two encodings, so reading it back loses
    # at least one of them - and sometimes both, when the shared
    # decimal rounds to a third encoding between them.
    lost = [bits for bits in (x, y) if back[0] != bits]
    assert lost, (fmt.name, hex(back[0]))
    note(3)
    return h, collided, len(lost)


def check_payload(lib, dev, fmt, pool):
    fi = PREC_CODE[fmt.name]
    esz = fmt.width // 8
    n = len(pool)
    a = enc(fmt, pool)
    for name, model in (("get", chars.get_payload),
                        ("set", chars.set_payload),
                        ("setsig", chars.set_payload_signaling)):
        fn = {"get": lib.cft_get_payload, "set": lib.cft_set_payload,
              "setsig": lib.cft_set_payload_signaling}[name]
        d = ctypes.create_string_buffer(n * esz)
        assert fn(dev, fi, a, d, n) == 0
        got = dec(fmt, d.raw, n)
        for i, bits in enumerate(pool):
            assert got[i] == model(fmt, bits), \
                (name, fmt.name, hex(bits), hex(got[i]),
                 hex(model(fmt, bits)))
            note()
        # d may alias a
        inplace = ctypes.create_string_buffer(a, n * esz)
        assert fn(dev, fi, inplace, inplace, n) == 0
        assert inplace.raw[:n * esz] == d.raw[:n * esz], (name, "aliased")
        note()
    # the 9.7 round trip: setPayload of getPayload of a NaN reproduces
    # the payload (quiet, sign 0), which is the property the two
    # operations exist to have
    for bits in pool:
        if not sf.is_nan(fmt, bits):
            continue
        got = chars.set_payload(fmt, chars.get_payload(fmt, bits))
        want = chars.nan_bits(fmt, 0, chars._decode(fmt, bits)[4], 0)
        assert got == want, (hex(bits), hex(got), hex(want))
        note()


def check_bad_args(lib, dev):
    fmt = FORMATS["fp32"]
    fi = PREC_CODE["fp32"]
    a = enc(fmt, [one_bits(fmt)])
    buf = ctypes.create_string_buffer(64)
    need = ctypes.c_size_t(0)
    fl = ctypes.c_uint32()
    arr = (ctypes.c_char_p * 1)(b"1.5")
    d = ctypes.create_string_buffer(4)
    for bad in (-1, 5, 7, 255):
        assert lib.cft_from_decimal_char(dev, fi, bad, arr, d, 1, None,
                                         ctypes.byref(fl)) == INVAL
        assert lib.cft_from_hex_char(dev, fi, bad, arr, d, 1, None,
                                     ctypes.byref(fl)) == INVAL
        # the attribute is checked even in the exact mode, where it is
        # not consumed
        assert lib.cft_to_decimal_char(dev, fi, bad, a, 0, buf, 64,
                                       ctypes.byref(need),
                                       ctypes.byref(fl)) == INVAL
        note(3)
    for badfmt in (-1, 4, 99):
        assert lib.cft_to_hex_char(dev, badfmt, a, buf, 64,
                                   ctypes.byref(need)) == INVAL
        assert lib.cft_get_payload(dev, badfmt, a, d, 1) == INVAL
        assert lib.cft_format_decimal_digits(badfmt) == 0
        note(3)
    assert lib.cft_from_decimal_char(None, fi, 0, arr, d, 1, None,
                                     ctypes.byref(fl)) == INVAL
    assert lib.cft_to_decimal_char(dev, fi, 0, None, 0, buf, 64,
                                   ctypes.byref(need),
                                   ctypes.byref(fl)) == INVAL
    # n == 0 is a clean no-op with clean flags
    fl.value = 0xdead
    assert lib.cft_from_decimal_char(dev, fi, 0, arr, d, 0, None,
                                     ctypes.byref(fl)) == 0 and fl.value == 0
    assert lib.cft_get_payload(dev, fi, None, None, 0) == 0
    # a buffer one byte short is a refusal with the length, never a
    # truncation
    st = lib.cft_to_decimal_char(dev, fi, 0, a, 0, buf, 1,
                                 ctypes.byref(need), ctypes.byref(fl))
    assert st == INVAL and need.value == 5, (st, need.value)   # "1e+0"
    buf[0] = b"Z"
    st = lib.cft_to_decimal_char(dev, fi, 0, a, 0, buf, 4,
                                 ctypes.byref(need), ctypes.byref(fl))
    assert st == INVAL and buf[0] == b"Z", "a short buffer was written"
    note(6)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--formats", default="fp32,fp64,fp128,fp256")
    ap.add_argument("--trials", type=int, default=40)
    args = ap.parse_args()
    formats = [s.strip() for s in args.formats.split(",") if s.strip()]

    lib = load_library()
    bind(lib)
    dev = open_dev(lib)
    try:
        check_bad_args(lib, dev)
        for name in formats:
            fmt = FORMATS[name]
            t = args.trials if fmt.width <= 64 else max(6, args.trials // 4)
            epool = encoding_pool(fmt, t)
            digit_counts = [0, 1, 2, 3, chars.pmin(fmt) - 1,
                            chars.pmin(fmt), chars.pmin(fmt) + 4, 60]
            check_to_decimal(lib, dev, fmt, epool, digit_counts)
            # the extremes go through the exact mode once each, where
            # the answer runs to tens of thousands of digits
            check_to_decimal(lib, dev, fmt, extreme_pool(fmt),
                             [0, 1, chars.pmin(fmt) - 1, chars.pmin(fmt)])
            check_from_decimal(lib, dev, fmt, decimal_pool(fmt, t))
            check_refusals(lib, dev, fmt)
            check_hex(lib, dev, fmt, epool + extreme_pool(fmt),
                      hex_pool(fmt, t))
            h, collided, lost = check_round_trip(lib, dev, fmt,
                                                 epool + extreme_pool(fmt))
            check_payload(lib, dev, fmt, epool)
            print(f"  {name}: character conversions agree with the model "
                  f"({CHECKED} comparisons so far); round trip holds at "
                  f"H={h} and collides at {h - 1} "
                  f"(0x{collided[0]:x} vs 0x{collided[1]:x} both print "
                  f"{collided[2]}; {lost} of the 2 are lost reading back)")
    finally:
        lib.cft_close(dev)
    print(f"character_check: {CHECKED} comparisons, C == model on every one")


if __name__ == "__main__":
    main()
