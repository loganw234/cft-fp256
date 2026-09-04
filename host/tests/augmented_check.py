# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""The augmented arithmetic entry points against the golden model.

    python3 host/tests/augmented_check.py                # standard sweep
    python3 host/tests/augmented_check.py --formats fp64
    python3 host/tests/augmented_check.py --trials 400   # longer randoms

Same discipline as clause5_check.py: python/cft_golden/augmented.py
defines every bit and flag, and this replays host/src/augmented.c
against it - per call (n=1), so BOTH outputs and the flag word compare
per element, plus batch cases so the element loop and the flag OR are
exercised too.

Two things this harness checks that a value comparison alone would not:

* The PAIR identity. r + e == x op y as exact integers, over every pool
  case, with the one exclusion 9.5 names: augmentedMultiplication's
  residual when the format cannot hold it (underflow AND inexact). The
  identity is what the operations are FOR, so it is scored rather than
  assumed, and it is scored on the library's own output rather than on
  the model's.
* Aliasing and refusals. r may alias a or b; r and e may not be the same
  buffer, and a call that says they are must be refused rather than
  computed.
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
    FORMATS, PREC_CODE, vectors,
    FLAG_INEXACT, FLAG_OVERFLOW,
    one_bits, zero_bits, min_subnormal_bits, max_normal_bits,
)
from cft_golden import augmented as aug  # noqa: E402
from cft_golden import softfloat as sf  # noqa: E402

#: (library entry point, model function, the vector sets' name)
OPS = (("cft_augmented_add", aug.augmented_add, "augmentedAddition"),
       ("cft_augmented_sub", aug.augmented_sub, "augmentedSubtraction"),
       ("cft_augmented_mul", aug.augmented_mul, "augmentedMultiplication"))

CHECKED = 0
IDENTITIES = 0
LOST = 0


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
    vp, sz, i = ctypes.c_void_p, ctypes.c_size_t, ctypes.c_int
    lib.cft_open.argtypes = [ctypes.c_char_p, i, ctypes.POINTER(vp)]
    lib.cft_open.restype = i
    lib.cft_close.argtypes = [vp]
    lib.cft_close.restype = None
    for nm, _model, _label in OPS:
        fn = getattr(lib, nm)
        fn.argtypes = [vp, i, vp, vp, vp, vp, sz, u32p]
        fn.restype = i


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


def note(k=1):
    global CHECKED
    CHECKED += k


# ---- the pair identity, in exact integers ---------------------------

def dnorm(m, e):
    if m == 0:
        return (0, 0)
    t = (m & -m).bit_length() - 1
    return (m >> t, e + t)


def dyadic(fmt, bits):
    """(m, e) with value m * 2^e, m signed - or None if not finite."""
    u = sf.unpack(fmt, bits)
    if u.kind in (sf.INF, sf.NAN):
        return None
    if u.kind == sf.ZERO:
        return (0, 0)
    return dnorm(-u.m if u.sign else u.m, u.e)


def dadd(x, y):
    e0 = min(x[1], y[1])
    return dnorm((x[0] << (x[1] - e0)) + (y[0] << (y[1] - e0)), e0)


def dmul(x, y):
    return dnorm(x[0] * y[0], x[1] + y[1])


def check_identity(fmt, label, a, b, r, e, flags):
    """r + e == x op y exactly, on the LIBRARY's output.

    The exclusions are the two 9.5 names, not a tolerance: an overflowed
    result (both outputs are an infinity) and augmentedMultiplication's
    residual when the format cannot hold it, which arrives rounded and
    marked underflow AND inexact.
    """
    global IDENTITIES, LOST
    xa, xb = dyadic(fmt, a), dyadic(fmt, b)
    if xa is None or xb is None:
        return
    if flags & FLAG_OVERFLOW:
        return
    if label == "augmentedMultiplication" and (flags & FLAG_INEXACT):
        LOST += 1
        return
    dr, de = dyadic(fmt, r), dyadic(fmt, e)
    assert dr is not None and de is not None, (label, hex(a), hex(b))
    if label == "augmentedMultiplication":
        want = dmul(xa, xb)
    elif label == "augmentedSubtraction":
        want = dadd(xa, (-xb[0], xb[1]))
    else:
        want = dadd(xa, xb)
    got = dadd(dr, de)
    assert got == want, (label, fmt.name, hex(a), hex(b), hex(r), hex(e),
                         got, want)
    IDENTITIES += 1


# ---- the sweeps ------------------------------------------------------

def check_elementwise(lib, dev, fmt, pairs):
    """n = 1, so both outputs and the exact flag word are compared per
    case - the only shape in which a sticky flag word means one case."""
    fi = PREC_CODE[fmt.name]
    esz = fmt.width // 8
    for nm, model, label in OPS:
        fn = getattr(lib, nm)
        for xa, xb in pairs:
            a, b = enc(fmt, [xa]), enc(fmt, [xb])
            r = ctypes.create_string_buffer(esz)
            e = ctypes.create_string_buffer(esz)
            fl = ctypes.c_uint32(1 << 31)
            st = fn(dev, fi, a, b, r, e, 1, ctypes.byref(fl))
            assert st == 0, (nm, st)
            gr = dec(fmt, r.raw, 1)[0]
            ge = dec(fmt, e.raw, 1)[0]
            want = model(fmt, xa, xb)
            assert (gr, ge, fl.value) == want, \
                (label, fmt.name, hex(xa), hex(xb),
                 (hex(gr), hex(ge), fl.value),
                 (hex(want[0]), hex(want[1]), want[2]))
            check_identity(fmt, label, xa, xb, gr, ge, fl.value)
            note()


def check_batches(lib, dev, fmt, pairs):
    """n > 1: the element loop, the flag OR, and a case whose flags come
    from the LAST lane alone - a loop that stopped early would pass a
    value comparison and fail this."""
    fi = PREC_CODE[fmt.name]
    rng = random.Random(0xA46 ^ fmt.width)
    n = 4000
    chosen = [pairs[rng.randrange(len(pairs))] for _ in range(n - 1)]
    # a signaling NaN parked last, so late-lane classification decides
    chosen.append((sf.snan_bits(fmt), one_bits(fmt)))
    xs = enc(fmt, [p[0] for p in chosen])
    ys = enc(fmt, [p[1] for p in chosen])
    for nm, model, label in OPS:
        fn = getattr(lib, nm)
        r = ctypes.create_string_buffer(len(xs))
        e = ctypes.create_string_buffer(len(xs))
        fl = ctypes.c_uint32()
        st = fn(dev, fi, xs, ys, r, e, n, ctypes.byref(fl))
        assert st == 0, (nm, st)
        grs = dec(fmt, r.raw, n)
        ges = dec(fmt, e.raw, n)
        want_or = 0
        for (xa, xb), gr, ge in zip(chosen, grs, ges):
            wr, we, wf = model(fmt, xa, xb)
            assert (gr, ge) == (wr, we), \
                (label + " batch", fmt.name, hex(xa), hex(xb),
                 hex(gr), hex(ge), hex(wr), hex(we))
            want_or |= wf
        assert fl.value == want_or, (label, fmt.name, fl.value, want_or)
        assert want_or & 1, "the last-lane signaling NaN never showed up"
        note(n)


def check_aliasing(lib, dev, fmt, pairs):
    """cft.h promises r or e may alias a or b - each element is read
    before either output is written - and that r and e may not be the
    same buffer, because no ordering of two writes to one buffer is
    well defined."""
    fi = PREC_CODE[fmt.name]
    esz = fmt.width // 8
    n = 64
    chosen = pairs[:n]
    xs = enc(fmt, [p[0] for p in chosen])
    ys = enc(fmt, [p[1] for p in chosen])
    for nm, _model, label in OPS:
        fn = getattr(lib, nm)
        r0 = ctypes.create_string_buffer(len(xs))
        e0 = ctypes.create_string_buffer(len(xs))
        assert fn(dev, fi, xs, ys, r0, e0, n, None) == 0
        # r aliasing a
        ra = ctypes.create_string_buffer(xs, len(xs))
        eb = ctypes.create_string_buffer(len(xs))
        assert fn(dev, fi, ra, ys, ra, eb, n, None) == 0
        assert ra.raw[:len(xs)] == r0.raw[:len(xs)], (label, "r aliases a")
        assert eb.raw[:len(xs)] == e0.raw[:len(xs)], (label, "e beside it")
        # e aliasing b
        rb = ctypes.create_string_buffer(len(xs))
        yb = ctypes.create_string_buffer(ys, len(ys))
        assert fn(dev, fi, xs, yb, rb, yb, n, None) == 0
        assert rb.raw[:len(xs)] == r0.raw[:len(xs)], (label, "r beside it")
        assert yb.raw[:len(ys)] == e0.raw[:len(xs)], (label, "e aliases b")
        note(3 * n)
        # refusals
        one = ctypes.create_string_buffer(esz)
        buf = ctypes.create_string_buffer(esz)
        a1, b1 = enc(fmt, [one_bits(fmt)]), enc(fmt, [one_bits(fmt)])
        assert fn(dev, fi, a1, b1, buf, buf, 1, None) == 1, \
            (label, "r == e must be refused")
        assert fn(dev, fi, None, b1, one, buf, 1, None) == 1, (label, "a")
        assert fn(dev, fi, a1, None, one, buf, 1, None) == 1, (label, "b")
        assert fn(dev, fi, a1, b1, None, buf, 1, None) == 1, (label, "r")
        assert fn(dev, fi, a1, b1, one, None, 1, None) == 1, (label, "e")
        assert fn(dev, fi, a1, b1, one, buf, 0, None) == 0, (label, "n=0")
        fl = ctypes.c_uint32(0xDEAD)
        assert fn(dev, fi, a1, b1, one, buf, 0, ctypes.byref(fl)) == 0
        assert fl.value == 0, (label, "n=0 must clear the flag word")
        for bad in (-1, 4, 99):
            assert fn(dev, bad, a1, b1, one, buf, 1, None) == 1, \
                (label, "format", bad)
        note(12)


def check_named_edges(lib, dev, fmt):
    """The rows 9.5 states in words, through the library rather than
    through the model - the tie toward the smaller magnitude, the
    overflow midpoint that raises nothing, and underflow without
    inexact."""
    fi = PREC_CODE[fmt.name]
    esz = fmt.width // 8
    fn = lib.cft_augmented_add

    def call(xa, xb, f=None):
        a, b = enc(fmt, [xa]), enc(fmt, [xb])
        r = ctypes.create_string_buffer(esz)
        e = ctypes.create_string_buffer(esz)
        fl = ctypes.c_uint32()
        st = (f or fn)(dev, fi, a, b, r, e, 1, ctypes.byref(fl))
        assert st == 0, st
        return dec(fmt, r.raw, 1)[0], dec(fmt, e.raw, 1)[0], fl.value

    # the tie: (1 + u) + u/2 keeps the SMALLER magnitude, where every
    # round-to-nearest attribute this library has would step up
    x = one_bits(fmt) | 1
    y = sf.round_pack(fmt, 0, 1, -(fmt.prec), sf.RND_RNE)[0]
    r, e, fl = call(x, y)
    assert (r, e, fl) == (x, y, 0), (fmt.name, hex(r), hex(e), fl)
    assert sf.add(fmt, x, y, sf.RND_RNE)[0] != r, "the tie is not a tie"
    note()

    # exactly on the overflow threshold: the largest finite, silently
    mx = max_normal_bits(fmt)
    half = sf.round_pack(fmt, 0, 1, fmt.emax - fmt.prec, sf.RND_RNE)[0]
    r, e, fl = call(mx, half)
    assert (r, e, fl) == (mx, half, 0), (fmt.name, hex(r), hex(e), fl)
    note()

    # one ulp past it: an infinity in BOTH outputs, overflow and inexact
    ulp = sf.round_pack(fmt, 0, 1, fmt.emax - fmt.prec + 1, sf.RND_RNE)[0]
    r, e, fl = call(mx, ulp)
    assert r == sf.inf_bits(fmt, 0) and e == r and fl == 0x14, \
        (fmt.name, hex(r), hex(e), fl)
    note()

    # underflow with NO inexact: an exact subnormal residual
    r, e, fl = call(one_bits(fmt), min_subnormal_bits(fmt))
    assert (r, e, fl) == (one_bits(fmt), min_subnormal_bits(fmt), 8), \
        (fmt.name, hex(r), hex(e), fl)
    note()

    # underflow WITH inexact: a product residual the format cannot hold
    s = min_subnormal_bits(fmt)
    r, e, fl = call(s, s, lib.cft_augmented_mul)
    assert (r, e, fl) == (zero_bits(fmt, 0), zero_bits(fmt, 0), 0x18), \
        (fmt.name, hex(r), hex(e), fl)
    note()

    # the zero error term takes r's sign, not the arithmetic's
    neg_one = sf.one_bits(fmt, 1)
    r, e, fl = call(neg_one, zero_bits(fmt, 0))
    assert (r, e, fl) == (neg_one, zero_bits(fmt, 1), 0), (fmt.name, hex(e))
    note()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--formats", default="fp32,fp64,fp128,fp256")
    ap.add_argument("--trials", type=int, default=24,
                    help="random pairs added to each format's pool")
    args = ap.parse_args()
    formats = [s.strip() for s in args.formats.split(",") if s.strip()]

    lib = load_library()
    bind(lib)
    dev = open_dev(lib)
    try:
        for name in formats:
            fmt = FORMATS[name]
            pairs = vectors.augmented_pairs(fmt, args.trials)
            check_elementwise(lib, dev, fmt, pairs)
            check_batches(lib, dev, fmt, pairs)
            check_aliasing(lib, dev, fmt, pairs)
            check_named_edges(lib, dev, fmt)
            print(f"  {name}: {len(pairs)} pairs x 3 operations agree with "
                  f"the model ({CHECKED} comparisons so far)")
    finally:
        lib.cft_close(dev)
    assert LOST > 0, "the non-representable product residual was never hit"
    print(f"augmented_check: {CHECKED} comparisons, C == model on every "
          f"one;\n  {IDENTITIES} pairs verified exact (r + e == x op y in "
          f"integers),\n  {LOST} residuals delivered rounded per 9.5's "
          f"non-representable case")


if __name__ == "__main__":
    main()
