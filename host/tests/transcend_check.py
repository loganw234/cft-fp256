# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""The transcendental entry points against the golden model.

    python3 host/tests/transcend_check.py                 # standard sweep
    python3 host/tests/transcend_check.py --formats fp64
    python3 host/tests/transcend_check.py --trials 200    # longer randoms

Same discipline as clause5_check.py and divsqrt_check.py:
python/cft_golden/transcend.py defines every bit and flag, and this
replays host/src/transcend.c against it - per call (n=1) so flags
compare per element, plus batch calls so the array loop is exercised
and the flag OR is checked.

The pools are built where these operations actually differ from each
other and from a merely-accurate implementation:

  * the exact cases and their immediate neighbours - integer arguments
    to exp2, powers of two to log2, powers of ten to log10, integer and
    dyadic exponents to pow, Pythagorean triples to hypot, each with
    one ulp added and subtracted so the exactness test has to be right
    rather than merely optimistic;
  * the overflow and underflow thresholds, computed per attribute -
    n*ln2 for every interesting n, rounded both ways;
  * arguments below 2^-(p+3), where the answer is decided by the side
    of a neighbour rather than by any working precision;
  * pow with a base one ulp from 1 and exponents up to 2^emax, which is
    the family a fixed-point evaluator cannot survive;
  * hypot with operands whose exponents differ by more than half the
    precision, and with sums that are near-perfect squares;
  * subnormal inputs and subnormal results.

Phase 2 (ABI 0.4) adds eleven more, with pools of their own, because
the families that catch a trigonometric function are not the families
that catch an exponential:

  * the half-integers and quarter-integers, each with one ulp added and
    subtracted, so sinPi's and tanPi's exactness tests have to be right
    rather than merely optimistic - and the integers, where sinPi's
    zero takes the sign of the ARGUMENT and tanPi's takes the parity
    too;
  * arguments just below and just above 1 for asin, acos and their Pi
    forms, where the domain ends and where (1-x)(1+x) is the only form
    that survives;
  * tiny arguments straddling every neighbour threshold this set has -
    asin above its argument, atan below it, cosPi below 1, acosPi and
    atan2Pi beside 1/2 and 1, atanPi below 1/2 for a huge argument;
  * atan2 ON the axes and the diagonals, and one ulp off them, in every
    combination of signs and both zeros;
  * atan2 with an exactly dyadic quotient - including minSubnormal over
    two, whose quotient is a subnormal MIDPOINT;
  * subnormal inputs and subnormal results.
"""

import argparse
import ctypes
import os
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "python"))

from cft_golden import FORMATS, PREC_CODE, RND_MODES, RND_NAMES  # noqa: E402
from cft_golden import softfloat as sf                            # noqa: E402
from cft_golden import transcend as tr                            # noqa: E402

UNARY = ("exp", "expm1", "exp2", "log", "log1p", "log2", "log10")
BINARY = ("pow", "hypot")
TRIG_UNARY = ("sinpi", "cospi", "tanpi", "asin", "acos", "atan",
              "asinpi", "acospi", "atanpi")
TRIG_BINARY = ("atan2", "atan2pi")
CHECKED = 0


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
    vp, sz, i = ctypes.c_void_p, ctypes.c_size_t, ctypes.c_int
    u32p = ctypes.POINTER(ctypes.c_uint32)
    lib.cft_open.argtypes = [ctypes.c_char_p, i, ctypes.POINTER(vp)]
    lib.cft_open.restype = i
    lib.cft_close.argtypes = [vp]
    lib.cft_close.restype = None
    for nm in UNARY + TRIG_UNARY:
        fn = getattr(lib, "cft_" + nm)
        fn.argtypes = [vp, i, i, vp, vp, sz, u32p]
        fn.restype = i
    for nm in BINARY + TRIG_BINARY:
        fn = getattr(lib, "cft_" + nm)
        fn.argtypes = [vp, i, i, vp, vp, vp, sz, u32p]
        fn.restype = i
    lib.cft_abi_version.argtypes = []
    lib.cft_abi_version.restype = ctypes.c_uint32


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


def call(lib, dev, fmt, fn, rnd, xs, ys=None):
    """One batch through the C, returning (bits list, flag word, status)."""
    esz = fmt.width // 8
    n = len(xs)
    a = ctypes.create_string_buffer(enc(fmt, xs), n * esz)
    d = ctypes.create_string_buffer(n * esz)
    fl = ctypes.c_uint32(0xDEAD)
    f = getattr(lib, "cft_" + fn)
    if fn in BINARY or fn in TRIG_BINARY:
        b = ctypes.create_string_buffer(enc(fmt, ys), n * esz)
        st = f(dev, PREC_CODE[fmt.name], rnd, a, b, d, n, ctypes.byref(fl))
    else:
        st = f(dev, PREC_CODE[fmt.name], rnd, a, d, n, ctypes.byref(fl))
    return dec(fmt, d.raw, n), fl.value, st


def note(k=1):
    global CHECKED
    CHECKED += k


def V(fmt, sign, m, e):
    bits, flags = sf.round_pack(fmt, sign, m, e, sf.RND_RNE)
    assert flags == 0, (m, e)
    return bits


def Vopt(fmt, sign, m, e):
    """V, or None when the format cannot hold the value exactly - so a
    family can be written once and thin itself out at fp32."""
    bits, flags = sf.round_pack(fmt, sign, m, e, sf.RND_RNE)
    return None if flags else bits


def unary_pool(fmt, trials, seed):
    """Every family a unary transcendental can get wrong."""
    import mpmath
    p = fmt.prec
    one = sf.one_bits(fmt)
    rng = random.Random(seed ^ fmt.width)
    out = [
        sf.zero_bits(fmt), sf.zero_bits(fmt, 1),
        one, sf.one_bits(fmt, 1), one + 1, one - 1,
        sf.one_bits(fmt, 1) + 1, sf.one_bits(fmt, 1) - 1,
        sf.min_subnormal_bits(fmt), sf.min_subnormal_bits(fmt, 1),
        sf.max_subnormal_bits(fmt), sf.max_subnormal_bits(fmt, 1),
        sf.min_normal_bits(fmt), sf.min_normal_bits(fmt, 1),
        sf.max_normal_bits(fmt), sf.max_normal_bits(fmt, 1),
        sf.inf_bits(fmt), sf.inf_bits(fmt, 1),
        sf.qnan_bits(fmt), sf.snan_bits(fmt),
        sf.qnan_bits(fmt) | 0x5, fmt.sign_mask | sf.qnan_bits(fmt),
    ]
    # small integers, and the ones at the exp2 thresholds
    for k in list(range(1, 25)) + [p, 2 * p, fmt.emax - 1, fmt.emax,
                                   fmt.emax + 1, fmt.emin, fmt.emin - 1,
                                   fmt.emin - fmt.man_w,
                                   fmt.emin - fmt.man_w - 1]:
        for sgn in (0, 1):
            b = Vopt(fmt, sgn, abs(k), 0)
            if b is not None:
                out.append(b)
    # powers of two (log2 exact) and powers of ten (log10 exact), each
    # with a neighbour on both sides
    for k in (-3, -1, 1, 2, 10, fmt.emax, fmt.emin,
              fmt.emin - fmt.man_w + 1):
        b = Vopt(fmt, 0, 1, k)
        if b is not None:
            out += [b, b + 1, b - 1]
    k = 0
    while 5 ** k < (1 << p):
        b = V(fmt, 0, 5 ** k, k)
        out += [b, b + 1, b - 1]
        k += 1
    # the exp overflow and underflow edges: n*ln2 rounded both ways
    mpmath.mp.prec = 4 * p + 64
    for n in (fmt.emax, fmt.emax + 1, fmt.emin, fmt.emin - fmt.man_w,
              fmt.emin - fmt.man_w - 1, -(p + 2), -(p + 3), p + 1):
        t = mpmath.mpf(n) * mpmath.log(2)
        man, ex = mpmath.libmp.to_man_exp(t._mpf_)
        b = sf.round_pack(fmt, 1 if man < 0 else 0, abs(int(man)),
                          int(ex), sf.RND_RNE)[0]
        out += [b, b + 1, b - 1, b + 2, b - 2]
    # below the neighbour thresholds, and just above them
    for k in (p + 2, p + 3, p + 4, p + 5, p + 10, 2 * p):
        for m, e in ((1, -k), (3, -k - 1)):
            for sgn in (0, 1):
                b = Vopt(fmt, sgn, m, e)
                if b is not None:
                    out.append(b)
    out += [rng.getrandbits(fmt.width) for _ in range(trials)]
    return sorted({b & ((1 << fmt.width) - 1) for b in out})


def pow_pairs(fmt, trials, seed):
    p = fmt.prec
    one = sf.one_bits(fmt)
    rng = random.Random(seed ^ (fmt.width * 31))
    pairs = []
    specials = [sf.zero_bits(fmt), sf.zero_bits(fmt, 1), sf.inf_bits(fmt),
                sf.inf_bits(fmt, 1), sf.qnan_bits(fmt), sf.snan_bits(fmt),
                one, sf.one_bits(fmt, 1), V(fmt, 0, 3, -1), V(fmt, 1, 3, -1),
                V(fmt, 0, 1, 1), V(fmt, 1, 1, 1), V(fmt, 0, 3, 0),
                V(fmt, 1, 3, 0), sf.max_normal_bits(fmt),
                sf.min_subnormal_bits(fmt)]
    for a in specials:
        for b in specials:
            pairs.append((a, b))
    # integer exponents against exact and inexact bases
    for base in (2, 3, 5, 7, 10, 4097):
        if base.bit_length() > p:
            continue
        for n in (1, 2, 3, 4, 5, 8, 17, p - 1, p, p + 1, p + 2, -1, -2,
                  -3, 1000):
            b = Vopt(fmt, 1 if n < 0 else 0, abs(n), 0)
            if b is None:
                continue
            for sgn in (0, 1):
                pairs.append((V(fmt, sgn, base, 0), b))
    # dyadic exponents against perfect powers and near-misses
    for m in (4, 9, 16, 25, 81, 256, 625, 1024):
        if m.bit_length() > p:
            continue
        mb = V(fmt, 0, m, 0)
        for ey in (-1, -2, -3):
            pairs.append((mb, V(fmt, 0, 1, ey)))
            pairs.append((mb, V(fmt, 0, 3, ey - 1)))
            pairs.append((mb + 1, V(fmt, 0, 1, ey)))
            pairs.append((mb, V(fmt, 1, 1, ey)))
    # a base one ulp from 1, with exponents right across the range
    for dy in (1, 3, 1 << (p // 2), (1 << fmt.man_w) - 1):
        for ey in (0, 10, p, 2 * p, fmt.emax // 2, fmt.emax - 1, fmt.emax,
                   -(p + 20), -(p + 3)):
            b = Vopt(fmt, 0, 1, ey)
            if b is None:
                continue
            for base in (one + dy, one - dy):
                pairs.append((base, b))
                pairs.append((base, b | fmt.sign_mask))
    # The one family measured to make the Ziv loop escalate at all:
    # pow(1+u, -(1+u)) is 1 - u + u^3/2, so it sits three precisions
    # from the representable 1-u and the first attempt cannot see the
    # gap. The u^2 term cancels only for this exponent, and no
    # representable y can cancel the u^3 one as well, which is the
    # argument that bounds the whole family at 3p bits.
    for du in (1, 2, 3, 5):
        for dv in (0, 1, 2, 3, 5):
            base = one + du
            expo = (one + dv) | fmt.sign_mask
            pairs.append((base, expo))
            pairs.append((one - du, expo))
            pairs.append((base, one + dv))
    for _ in range(trials):
        pairs.append((rng.getrandbits(fmt.width), rng.getrandbits(fmt.width)))
    return pairs


def hypot_pairs(fmt, trials, seed):
    p = fmt.prec
    one = sf.one_bits(fmt)
    rng = random.Random(seed ^ (fmt.width * 61))
    pairs = []
    for (x, y) in ((3, 4), (5, 12), (8, 15), (7, 24), (20, 21), (9, 40),
                   (1, 1), (2, 2), (6, 8), (12, 16)):
        if max(x, y).bit_length() > p:
            continue
        for sx in (0, 1):
            for sy in (0, 1):
                pairs.append((V(fmt, sx, x, 0), V(fmt, sy, y, 0)))
        pairs.append((V(fmt, 0, x, 0), V(fmt, 0, y, 0) + 1))
        pairs.append((V(fmt, 0, x, 0) - 1, V(fmt, 0, y, 0)))
        for e in (fmt.emax - 8, fmt.emin + 2, -p, fmt.emin - fmt.man_w):
            bx, by = Vopt(fmt, 0, x, e), Vopt(fmt, 0, y, e)
            if bx is not None and by is not None:
                pairs.append((bx, by))
    # widely different magnitudes, straddling the dominance threshold
    for k in (1, 2, p // 2 - 1, p // 2, p // 2 + 1, p, 2 * p,
              fmt.emax // 2, fmt.emax):
        pairs.append((one, V(fmt, 0, 1, -k)))
        pairs.append((V(fmt, 0, 1, -k), one))
        b = Vopt(fmt, 0, 1, fmt.emax - k)
        if b is not None:
            pairs.append((sf.max_normal_bits(fmt), b))
    pairs += [
        (sf.max_normal_bits(fmt), sf.max_normal_bits(fmt)),
        (sf.max_normal_bits(fmt), sf.min_subnormal_bits(fmt)),
        (sf.min_subnormal_bits(fmt), sf.min_subnormal_bits(fmt)),
        (sf.max_subnormal_bits(fmt), sf.max_subnormal_bits(fmt)),
        (sf.min_normal_bits(fmt), sf.min_subnormal_bits(fmt)),
        (sf.zero_bits(fmt, 1), sf.zero_bits(fmt, 1)),
        (sf.zero_bits(fmt), sf.max_normal_bits(fmt, 1)),
        (sf.inf_bits(fmt), sf.qnan_bits(fmt)),
        (sf.qnan_bits(fmt), sf.inf_bits(fmt, 1)),
        (sf.snan_bits(fmt), sf.inf_bits(fmt)),
        (sf.qnan_bits(fmt), sf.qnan_bits(fmt)),
    ]
    for _ in range(trials):
        pairs.append((rng.getrandbits(fmt.width), rng.getrandbits(fmt.width)))
    return pairs


def trig_pool(fmt, trials, seed):
    """Operands where a trigonometric function can actually be got
    wrong. Random bit patterns score almost nothing here: they never
    land on a half-integer, never straddle 1, and never sit at a
    neighbour threshold."""
    p = fmt.prec
    one = sf.one_bits(fmt)
    rng = random.Random(seed ^ (fmt.width * 101))
    out = [
        sf.zero_bits(fmt), sf.zero_bits(fmt, 1),
        one, sf.one_bits(fmt, 1), one + 1, one - 1,
        sf.one_bits(fmt, 1) + 1, sf.one_bits(fmt, 1) - 1,
        sf.min_subnormal_bits(fmt), sf.min_subnormal_bits(fmt, 1),
        sf.max_subnormal_bits(fmt), sf.max_subnormal_bits(fmt, 1),
        sf.min_normal_bits(fmt), sf.min_normal_bits(fmt, 1),
        sf.max_normal_bits(fmt), sf.max_normal_bits(fmt, 1),
        sf.inf_bits(fmt), sf.inf_bits(fmt, 1),
        sf.qnan_bits(fmt), sf.snan_bits(fmt), sf.qnan_bits(fmt) | 0x5,
    ]
    # the half-integers, quarter-integers and integers, each with a
    # neighbour on both sides - sinPi and tanPi are exact on two of
    # those three families and irrational on the rest of the line
    for m, e in [(k, -1) for k in (1, 3, 5, 7, 9, 17, 33)] + \
                [(k, -2) for k in (1, 3, 5, 7, 9, 11, 13)] + \
                [(k, 0) for k in (1, 2, 3, 4, 5, 8, 17)] + \
                [(k, -3) for k in (1, 3, 5, 7, 11, 13)]:
        for sgn in (0, 1):
            b = Vopt(fmt, sgn, m, e)
            if b is not None:
                out += [b, b + 1, b - 1]
    # the top of the finite range, where every value is an even integer
    for k in (p - 1, p, p + 1, 2 * p, fmt.emax - 1, fmt.emax):
        for sgn in (0, 1):
            b = Vopt(fmt, sgn, 1, k)
            if b is not None:
                out += [b, b - 1]
    # every neighbour threshold this set has, and one step either side
    for k in (p // 2, p // 2 + 1, p // 2 + 2, p, p + 1, p + 2, p + 3,
              2 * p, 4 * p):
        for m, e in ((1, -k), (3, -k - 1)):
            for sgn in (0, 1):
                b = Vopt(fmt, sgn, m, e)
                if b is not None:
                    out.append(b)
    # just inside and just outside the asin/acos domain
    for sgn in (0, 1):
        out += [sf.one_bits(fmt, sgn), sf.one_bits(fmt, sgn) - 1,
                sf.one_bits(fmt, sgn) + 1]
        b = Vopt(fmt, sgn, (1 << p) - 1, -p)
        if b is not None:
            out += [b, b - 1]
    out += [rng.getrandbits(fmt.width) for _ in range(trials)]
    return sorted({b & ((1 << fmt.width) - 1) for b in out})


def atan2_pairs(fmt, trials, seed):
    """atan2 ON the axes and diagonals and one ulp off them.

    Every axis and diagonal is an EXACT case of atan2Pi and an inexact
    rounding of a multiple of pi for atan2, so the same pair scores both
    halves of the design at once."""
    p = fmt.prec
    one = sf.one_bits(fmt)
    rng = random.Random(seed ^ (fmt.width * 211))
    axes = [sf.zero_bits(fmt), sf.zero_bits(fmt, 1), one,
            sf.one_bits(fmt, 1), sf.inf_bits(fmt), sf.inf_bits(fmt, 1),
            sf.qnan_bits(fmt), sf.snan_bits(fmt), V(fmt, 0, 1, 1),
            V(fmt, 1, 1, 1), V(fmt, 0, 3, 0), V(fmt, 1, 3, 0),
            sf.max_normal_bits(fmt), sf.min_subnormal_bits(fmt),
            sf.min_subnormal_bits(fmt, 1)]
    pairs = [(a, b) for a in axes for b in axes]
    # the diagonals proper, at several magnitudes and all four signs
    for e in (0, 1, -1, p, -p, fmt.emax - 1, fmt.emin, fmt.emin - fmt.man_w):
        b = Vopt(fmt, 0, 1, e)
        if b is None:
            continue
        for sy in (0, 1):
            for sx in (0, 1):
                y = b | (fmt.sign_mask if sy else 0)
                x = b | (fmt.sign_mask if sx else 0)
                pairs += [(y, x), (y + 1, x), (y, x + 1), (y - 1, x)]
    # a quotient that is exactly a dyadic rational, and tiny: the
    # neighbour case round_neighbour could not have handled, because
    # minSubnormal/2 is a MIDPOINT and not a representable number
    two = V(fmt, 0, 1, 1)
    sub = sf.min_subnormal_bits(fmt)
    pairs += [(sub, two), (sub, V(fmt, 0, 1, 2)), (sub, one),
              (sub | fmt.sign_mask, two), (sub, V(fmt, 1, 1, 1))]
    for k in (p, p + 4, 2 * p, 4 * p):
        y = Vopt(fmt, 0, 1, -k)
        if y is None:
            continue
        pairs += [(y, one), (y, V(fmt, 1, 1, 0)), (y, two),
                  (y | fmt.sign_mask, one), (y, V(fmt, 0, 3, 0))]
    # a dominant y and a dominant x, straddling atan2Pi's two corners
    for k in (p, p + 1, p + 2, p + 3, 2 * p):
        big, small = Vopt(fmt, 0, 1, k), Vopt(fmt, 0, 1, -k)
        if big is None or small is None:
            continue
        pairs += [(big, one), (one, big), (small, one), (one, small),
                  (big, V(fmt, 1, 1, 0)), (small, V(fmt, 1, 1, 0))]
    pairs += [(rng.getrandbits(fmt.width), rng.getrandbits(fmt.width))
              for _ in range(trials)]
    return pairs


def check_trig_unary(lib, dev, fmt, pool):
    for fn in TRIG_UNARY:
        for rnd in RND_MODES:
            for xa in pool:
                got, fl, st = call(lib, dev, fmt, fn, rnd, [xa])
                assert st == 0, (fn, fmt.name, RND_NAMES[rnd], hex(xa), st)
                want = tr.compute(fmt, fn, xa, 0, rnd)
                assert (got[0], fl) == want, \
                    (fn, fmt.name, RND_NAMES[rnd], hex(xa),
                     (hex(got[0]), fl), (hex(want[0]), want[1]))
                note()


def check_trig_batches(lib, dev, fmt, pool, pairs):
    """The array path for the eleven, with a signaling NaN parked in the
    last lane so late-lane classification is what sets the flag word."""
    rng = random.Random(131 ^ fmt.width)
    n = 400
    xs = [rng.choice(pool) for _ in range(n - 1)] + [sf.snan_bits(fmt)]
    for fn in ("sinpi", "tanpi", "asin", "atanpi"):
        got, fl, st = call(lib, dev, fmt, fn, sf.RND_RUP, xs)
        assert st == 0, (fn, st)
        want_or = 0
        for x, g in zip(xs, got):
            wb, wf = tr.compute(fmt, fn, x, 0, sf.RND_RUP)
            assert g == wb, ("batch", fn, fmt.name, hex(x), hex(g), hex(wb))
            want_or |= wf
        assert fl == want_or and (want_or & 1), (fn, fl, want_or)
        note(n)
    xs = [a for a, _ in pairs[:300]]
    ys = [b for _, b in pairs[:300]]
    for fn in TRIG_BINARY:
        got, fl, st = call(lib, dev, fmt, fn, sf.RND_RTZ, xs, ys)
        assert st == 0, (fn, st)
        want_or = 0
        for x, y, g in zip(xs, ys, got):
            wb, wf = tr.compute(fmt, fn, x, y, sf.RND_RTZ)
            assert g == wb, ("batch", fn, fmt.name, hex(x), hex(y),
                             hex(g), hex(wb))
            want_or |= wf
        assert fl == want_or
        note(len(xs))


def check_unary(lib, dev, fmt, pool):
    for fn in UNARY:
        for rnd in RND_MODES:
            for xa in pool:
                got, fl, st = call(lib, dev, fmt, fn, rnd, [xa])
                assert st == 0, (fn, fmt.name, RND_NAMES[rnd], hex(xa), st)
                want = tr.compute(fmt, fn, xa, 0, rnd)
                assert (got[0], fl) == want, \
                    (fn, fmt.name, RND_NAMES[rnd], hex(xa),
                     (hex(got[0]), fl), (hex(want[0]), want[1]))
                note()


def check_binary(lib, dev, fmt, fn, pairs):
    for rnd in RND_MODES:
        for xa, xb in pairs:
            got, fl, st = call(lib, dev, fmt, fn, rnd, [xa], [xb])
            assert st == 0, (fn, fmt.name, RND_NAMES[rnd], hex(xa), hex(xb),
                             st)
            want = tr.compute(fmt, fn, xa, xb, rnd)
            assert (got[0], fl) == want, \
                (fn, fmt.name, RND_NAMES[rnd], hex(xa), hex(xb),
                 (hex(got[0]), fl), (hex(want[0]), want[1]))
            note()


def check_batches(lib, dev, fmt, pool, pairs):
    """The array path, and the flag word as the OR over it. A NaN is
    parked in the LAST lane so late-lane classification is what sets
    the batch's flags."""
    rng = random.Random(97 ^ fmt.width)
    n = 600
    xs = [rng.choice(pool) for _ in range(n - 1)] + [sf.snan_bits(fmt)]
    for fn in ("exp", "log", "log1p"):
        got, fl, st = call(lib, dev, fmt, fn, sf.RND_RMM, xs)
        assert st == 0, (fn, st)
        want_or = 0
        for x, g in zip(xs, got):
            wb, wf = tr.compute(fmt, fn, x, 0, sf.RND_RMM)
            assert g == wb, ("batch", fn, fmt.name, hex(x), hex(g), hex(wb))
            want_or |= wf
        assert fl == want_or and (want_or & 1), (fn, fl, want_or)
        note(n)
    xs = [a for a, _ in pairs[:400]]
    ys = [b for _, b in pairs[:400]]
    for fn in BINARY:
        got, fl, st = call(lib, dev, fmt, fn, sf.RND_RDN, xs, ys)
        assert st == 0, (fn, st)
        want_or = 0
        for x, y, g in zip(xs, ys, got):
            wb, wf = tr.compute(fmt, fn, x, y, sf.RND_RDN)
            assert g == wb, ("batch", fn, fmt.name, hex(x), hex(y),
                             hex(g), hex(wb))
            want_or |= wf
        assert fl == want_or
        note(len(xs))


def check_refusals(lib, dev):
    """The arguments that must be refused rather than computed."""
    fmt = FORMATS["fp32"]
    fi = PREC_CODE["fp32"]
    a = ctypes.create_string_buffer(enc(fmt, [sf.one_bits(fmt)]), 4)
    d = ctypes.create_string_buffer(4)
    fl = ctypes.c_uint32()
    INVAL = 1
    for bad in (-1, 5, 7, 255):
        assert lib.cft_exp(dev, fi, bad, a, d, 1,
                           ctypes.byref(fl)) == INVAL, bad
        assert lib.cft_pow(dev, fi, bad, a, a, d, 1,
                           ctypes.byref(fl)) == INVAL, bad
        assert lib.cft_sinpi(dev, fi, bad, a, d, 1,
                             ctypes.byref(fl)) == INVAL, bad
        assert lib.cft_atan2(dev, fi, bad, a, a, d, 1,
                             ctypes.byref(fl)) == INVAL, bad
        note(4)
    for bad_fmt in (-1, 4, 99):
        assert lib.cft_log(dev, bad_fmt, 0, a, d, 1,
                           ctypes.byref(fl)) == INVAL, bad_fmt
        assert lib.cft_atan(dev, bad_fmt, 0, a, d, 1,
                            ctypes.byref(fl)) == INVAL, bad_fmt
        note(2)
    # the second operand is not optional for any binary entry point
    assert lib.cft_pow(dev, fi, 0, a, None, d, 1,
                       ctypes.byref(fl)) == INVAL
    assert lib.cft_hypot(dev, fi, 0, a, None, d, 1,
                         ctypes.byref(fl)) == INVAL
    assert lib.cft_atan2(dev, fi, 0, a, None, d, 1,
                         ctypes.byref(fl)) == INVAL
    assert lib.cft_atan2pi(dev, fi, 0, a, None, d, 1,
                           ctypes.byref(fl)) == INVAL
    note(2)
    # the library actually loaded says 0.4, not the header it was
    # written against
    v = lib.cft_abi_version()
    assert (v >> 16) == 0 and (v & 0xFFFF) >= 4, hex(v)
    note()
    # n == 0 touches nothing and clears the flags
    fl.value = 0xDEAD
    assert lib.cft_exp(dev, fi, 0, None, None, 0, ctypes.byref(fl)) == 0
    assert fl.value == 0
    note(3)


def check_aliasing(lib, dev, fmt, pool):
    """d may alias a: each element is read before it is written."""
    esz = fmt.width // 8
    xs = list(pool[:64])
    n = len(xs)
    buf = ctypes.create_string_buffer(enc(fmt, xs), n * esz)
    fl = ctypes.c_uint32()
    st = lib.cft_exp(dev, PREC_CODE[fmt.name], sf.RND_RNE, buf, buf, n,
                     ctypes.byref(fl))
    assert st == 0
    for x, g in zip(xs, dec(fmt, buf.raw, n)):
        assert g == tr.compute(fmt, "exp", x, 0, sf.RND_RNE)[0], \
            ("alias", fmt.name, hex(x))
    note(n)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--formats", default="fp32,fp64,fp128,fp256")
    ap.add_argument("--trials", type=int, default=64)
    ap.add_argument("--seed", type=int, default=5)
    ap.add_argument("--min-prec", type=int, default=0,
                    help="force the C library to START below the "
                         "precision it needs, so its escalation path is "
                         "exercised against an unescalated model")
    args = ap.parse_args()
    if args.min_prec:
        # The C only. The model keeps its ordinary schedule, so this
        # run compares an ESCALATED C against a non-escalated
        # reference - which is the property worth proving: raising the
        # working precision must land on the same bits, or the loop is
        # deciding something the mathematics does not.
        os.environ["CFT_TRANSCEND_MINPREC"] = str(args.min_prec)
    formats = [s.strip() for s in args.formats.split(",") if s.strip()]

    lib = load_library()
    bind(lib)
    dev = open_dev(lib)
    try:
        check_refusals(lib, dev)
        for name in formats:
            fmt = FORMATS[name]
            t = args.trials if fmt.width <= 64 else max(8, args.trials // 4)
            pool = unary_pool(fmt, t, args.seed)
            ppairs = pow_pairs(fmt, t, args.seed)
            hpairs = hypot_pairs(fmt, t, args.seed)
            tpool = trig_pool(fmt, t, args.seed)
            apairs = atan2_pairs(fmt, t, args.seed)
            check_unary(lib, dev, fmt, pool)
            check_binary(lib, dev, fmt, "pow", ppairs)
            check_binary(lib, dev, fmt, "hypot", hpairs)
            check_trig_unary(lib, dev, fmt, tpool)
            check_binary(lib, dev, fmt, "atan2", apairs)
            check_binary(lib, dev, fmt, "atan2pi", apairs)
            check_batches(lib, dev, fmt, pool, ppairs)
            check_trig_batches(lib, dev, fmt, tpool, apairs)
            check_aliasing(lib, dev, fmt, pool)
            print(f"  {name}: the transcendental entry points agree with "
                  f"the model ({CHECKED} comparisons so far)")
    finally:
        lib.cft_close(dev)
    st = tr.STATS
    print(f"transcend_check: {CHECKED} comparisons over "
          f"{len(UNARY) + len(BINARY) + len(TRIG_UNARY) + len(TRIG_BINARY)} "
          "functions, C == model on every one")
    print(f"  the model's evaluator: {st['ziv_calls']} enclosures, "
          f"{st['escalations']} escalations, deepest working precision "
          f"{st['max_prec']} bits,\n"
          f"  {st['exact']} decided exactly, {st['neighbour']} decided by "
          "a neighbour's side")


if __name__ == "__main__":
    main()
