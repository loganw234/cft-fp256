# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""The clause-5 completion entry points against the golden model.

    python3 host/tests/clause5_check.py                # standard sweep
    python3 host/tests/clause5_check.py --formats fp64
    python3 host/tests/clause5_check.py --trials 400   # longer randoms

Same discipline as divsqrt_check.py: python/cft_golden defines every
bit and flag; this replays host/src/clause5.c against it - per call
(n=1) so flags compare per element, plus batch cases that cross the
composed operations' internal chunk boundary. The pools lean on the
operand families where these operations actually differ: the Sterbenz
edge at 2^(p-1) for rint, every n regime for scaleB, the NaN zoo for
the signaling compares and totalOrder, exponent-gap extremes for
remainder, and the RISC-V invalid table for the integer conversions.
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
    FORMATS, PREC_CODE, RND_MODES, vectors,
    one_bits, zero_bits, inf_bits, qnan_bits, snan_bits,
    min_subnormal_bits, max_subnormal_bits, min_normal_bits,
    max_normal_bits,
)
from cft_golden import softfloat as sf  # noqa: E402

OPC = {"cmplt": 12, "cmple": 13, "cmpeq": 14}


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
    vp, sz = ctypes.c_void_p, ctypes.c_size_t
    i = ctypes.c_int
    lib.cft_open.argtypes = [ctypes.c_char_p, i, ctypes.POINTER(vp)]
    lib.cft_open.restype = i
    lib.cft_close.argtypes = [vp]
    lib.cft_close.restype = None
    lib.cft_rint.argtypes = [vp, i, i, i, vp, vp, sz, u32p, u32p]
    lib.cft_scaleb.argtypes = [vp, i, i, vp, ctypes.c_int64, vp, sz,
                               u32p, u32p]
    lib.cft_cmp_sig.argtypes = [vp, i, i, vp, vp, vp, sz, u32p, u32p]
    lib.cft_convert.argtypes = [vp, i, i, i, vp, vp, sz, u32p]
    for nm in ("cft_cvt_from_i32", "cft_cvt_from_u32",
               "cft_cvt_from_i64", "cft_cvt_from_u64"):
        getattr(lib, nm).argtypes = [vp, i, i, vp, vp, sz, u32p]
    for nm in ("cft_cvt_to_i32", "cft_cvt_to_u32",
               "cft_cvt_to_i64", "cft_cvt_to_u64"):
        getattr(lib, nm).argtypes = [vp, i, i, i, vp, vp, sz, u32p]
    lib.cft_logb.argtypes = [vp, i, vp, vp, sz, u32p]
    lib.cft_next_up.argtypes = [vp, i, vp, vp, sz, u32p]
    lib.cft_next_down.argtypes = [vp, i, vp, vp, sz, u32p]
    lib.cft_class.argtypes = [vp, i, vp, vp, sz]
    lib.cft_total_order.argtypes = [vp, i, vp, vp, vp, sz]
    lib.cft_total_order_mag.argtypes = [vp, i, vp, vp, vp, sz]
    lib.cft_rem.argtypes = [vp, i, vp, vp, vp, sz, u32p]
    for nm in ("cft_rint", "cft_scaleb", "cft_cmp_sig", "cft_convert",
               "cft_cvt_from_i32", "cft_cvt_from_u32", "cft_cvt_from_i64",
               "cft_cvt_from_u64", "cft_cvt_to_i32", "cft_cvt_to_u32",
               "cft_cvt_to_i64", "cft_cvt_to_u64", "cft_logb",
               "cft_next_up", "cft_next_down", "cft_class",
               "cft_total_order", "cft_total_order_mag", "cft_rem"):
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


def pool_for(fmt, extra):
    rng = random.Random(0xC1A5)
    pool = list(vectors.interesting_operands(fmt))
    c = (fmt.man_w + fmt.bias) << fmt.man_w          # 2^(p-1)
    pool += [c, c - 1, c + 1, c | fmt.sign_mask, (c - 1) | fmt.sign_mask]
    for k in (1, 3, 5):
        pool.append(sf.round_pack(fmt, 0, k, -1, sf.RND_RNE)[0])
        pool.append(sf.round_pack(fmt, 1, k, -1, sf.RND_RNE)[0])
    pool += [rng.getrandbits(fmt.width) for _ in range(extra)]
    return pool


CHECKED = 0


def note(k=1):
    global CHECKED
    CHECKED += k


def run1(lib, fn, dev, fmt, out_esz, *args):
    """Call an n=1 entry point returning (bits_or_raw, flags)."""
    dbuf = ctypes.create_string_buffer(out_esz)
    flags = ctypes.c_uint32(0xdead)
    st = fn(dev, *args, dbuf, 1, ctypes.byref(flags))
    if st != 0:
        raise SystemExit(f"call failed: {st}")
    return dbuf.raw, flags.value


def check_rint(lib, dev, fmt, trials):
    fi = PREC_CODE[fmt.name]
    pool = pool_for(fmt, trials)
    for rnd in RND_MODES:
        for exact in (0, 1):
            for xa in pool:
                a = enc(fmt, [xa])
                d = ctypes.create_string_buffer(fmt.width // 8)
                fl = ctypes.c_uint32(1 << 31)
                st = lib.cft_rint(dev, fi, rnd, exact, a, d, 1,
                                  ctypes.byref(fl), None)
                assert st == 0, st
                want = sf.round_int(fmt, xa, rnd, bool(exact))
                got = (dec(fmt, d.raw, 1)[0], fl.value)
                assert got == want, \
                    ("rint", fmt.name, rnd, exact, hex(xa), got, want)
                note()
    # one batch across the chunk boundary, flags as the OR
    rng = random.Random(7 ^ fmt.width)
    xs = [rng.choice(pool) for _ in range(9000)]
    a = enc(fmt, xs)
    d = ctypes.create_string_buffer(len(a))
    fl = ctypes.c_uint32()
    st = lib.cft_rint(dev, fi, sf.RND_RMM, 1, a, d, len(xs),
                      ctypes.byref(fl), None)
    assert st == 0
    want_or = 0
    got_bits = dec(fmt, d.raw, len(xs))
    for x, g in zip(xs, got_bits):
        wb, wf = sf.round_int(fmt, x, sf.RND_RMM, True)
        assert g == wb, ("rint batch", fmt.name, hex(x), hex(g), hex(wb))
        want_or |= wf
    assert fl.value == want_or
    note(len(xs))


def check_scaleb(lib, dev, fmt, trials):
    fi = PREC_CODE[fmt.name]
    pool = pool_for(fmt, max(8, trials // 4))
    ns = [0, 1, -1, 7, -7, fmt.man_w, -fmt.man_w, fmt.emax, fmt.emax + 1,
          2 * fmt.emax, 2 * fmt.emax + fmt.prec, 3 * fmt.emax + 5,
          fmt.emin, fmt.emin - fmt.man_w, fmt.emin - fmt.man_w - 1,
          -(2 * fmt.emax), -(10 ** 15)]
    for rnd in RND_MODES:
        for xa in pool:
            for n in ns:
                a = enc(fmt, [xa])
                d = ctypes.create_string_buffer(fmt.width // 8)
                fl = ctypes.c_uint32()
                st = lib.cft_scaleb(dev, fi, rnd, a, n, d, 1,
                                    ctypes.byref(fl), None)
                assert st == 0, st
                want = sf.scaleb(fmt, xa, n, rnd)
                got = (dec(fmt, d.raw, 1)[0], fl.value)
                assert got == want, \
                    ("scaleb", fmt.name, rnd, hex(xa), n, got, want)
                note()
    # batch across the chunk boundary, one staged n
    rng = random.Random(11 ^ fmt.width)
    xs = [rng.choice(pool) for _ in range(9000)]
    a = enc(fmt, xs)
    d = ctypes.create_string_buffer(len(a))
    fl = ctypes.c_uint32()
    n_staged = fmt.emax + 3
    st = lib.cft_scaleb(dev, fi, sf.RND_RDN, a, n_staged, d, len(xs),
                        ctypes.byref(fl), None)
    assert st == 0
    want_or = 0
    for x, g in zip(xs, dec(fmt, d.raw, len(xs))):
        wb, wf = sf.scaleb(fmt, x, n_staged, sf.RND_RDN)
        assert g == wb, ("scaleb batch", fmt.name, hex(x), hex(g), hex(wb))
        want_or |= wf
    assert fl.value == want_or
    note(len(xs))


def check_cmp_sig(lib, dev, fmt, trials):
    fi = PREC_CODE[fmt.name]
    pool = pool_for(fmt, trials)
    rng = random.Random(13 ^ fmt.width)
    pairs = [(x, rng.choice(pool)) for x in pool]
    model = {"cmplt": sf.cmplt_sig, "cmple": sf.cmple_sig,
             "cmpeq": sf.cmpeq_sig}
    for name, op in OPC.items():
        for xa, xb in pairs:
            a, b = enc(fmt, [xa]), enc(fmt, [xb])
            d = ctypes.create_string_buffer(fmt.width // 8)
            fl = ctypes.c_uint32()
            st = lib.cft_cmp_sig(dev, op, fi, a, b, d, 1,
                                 ctypes.byref(fl), None)
            assert st == 0, st
            want = model[name](fmt, xa, xb)
            got = (dec(fmt, d.raw, 1)[0], fl.value)
            assert got == want, (name, fmt.name, hex(xa), hex(xb), got, want)
            note()


def check_convert(lib, dev, fmt, trials, formats):
    fi = PREC_CODE[fmt.name]
    pool = pool_for(fmt, trials)
    for dname in formats:
        dfmt = FORMATS[dname]
        di = PREC_CODE[dname]
        for rnd in RND_MODES:
            for xa in pool:
                a = enc(fmt, [xa])
                d = ctypes.create_string_buffer(dfmt.width // 8)
                fl = ctypes.c_uint32()
                st = lib.cft_convert(dev, fi, di, rnd, a, d, 1,
                                     ctypes.byref(fl))
                assert st == 0, st
                want = sf.convert(fmt, dfmt, xa, rnd)
                got = (dec(dfmt, d.raw, 1)[0], fl.value)
                assert got == want, \
                    ("convert", fmt.name, dname, rnd, hex(xa), got, want)
                note()


def check_cvt_int(lib, dev, fmt, trials):
    fi = PREC_CODE[fmt.name]
    pool = pool_for(fmt, trials)
    variants = [("cft_cvt_to_i32", 32, True, ctypes.c_int32),
                ("cft_cvt_to_u32", 32, False, ctypes.c_uint32),
                ("cft_cvt_to_i64", 64, True, ctypes.c_int64),
                ("cft_cvt_to_u64", 64, False, ctypes.c_uint64)]
    for nm, width, signed, ctype in variants:
        fn = getattr(lib, nm)
        for rnd in RND_MODES:
            for exact in (0, 1):
                for xa in pool:
                    a = enc(fmt, [xa])
                    out = ctype(0)
                    fl = ctypes.c_uint32()
                    st = fn(dev, fi, rnd, exact, a, ctypes.byref(out), 1,
                            ctypes.byref(fl))
                    assert st == 0, st
                    want = sf.to_int(fmt, xa, width, signed, rnd,
                                     bool(exact))
                    got = (out.value, fl.value)
                    assert got == want, \
                        (nm, fmt.name, rnd, exact, hex(xa), got, want)
                    note()
    rng = random.Random(17)
    ivals = [0, 1, -1, 2**31 - 1, -(2**31), 2**32 - 1, 2**53 + 1,
             2**63 - 1, -(2**63), 2**64 - 1]
    ivals += [rng.randint(-(2**63), 2**63 - 1) for _ in range(trials)]
    fr = [("cft_cvt_from_i32", 32, True, ctypes.c_int32),
          ("cft_cvt_from_u32", 32, False, ctypes.c_uint32),
          ("cft_cvt_from_i64", 64, True, ctypes.c_int64),
          ("cft_cvt_from_u64", 64, False, ctypes.c_uint64)]
    for nm, width, signed, ctype in fr:
        fn = getattr(lib, nm)
        lo = -(1 << (width - 1)) if signed else 0
        hi = (1 << (width - 1)) - 1 if signed else (1 << width) - 1
        for rnd in RND_MODES:
            for v in ivals:
                if not (lo <= v <= hi):
                    continue
                src = ctype(v)
                d = ctypes.create_string_buffer(fmt.width // 8)
                fl = ctypes.c_uint32()
                st = fn(dev, fi, rnd, ctypes.byref(src), d, 1,
                        ctypes.byref(fl))
                assert st == 0, st
                want = sf.from_int(fmt, v, rnd)
                got = (dec(fmt, d.raw, 1)[0], fl.value)
                assert got == want, (nm, fmt.name, rnd, v, got, want)
                note()


def check_unary(lib, dev, fmt, trials):
    fi = PREC_CODE[fmt.name]
    pool = pool_for(fmt, trials)
    for nm, fn_model in (("cft_logb", sf.logb), ("cft_next_up", sf.next_up),
                         ("cft_next_down", sf.next_down)):
        fn = getattr(lib, nm)
        for xa in pool:
            a = enc(fmt, [xa])
            d = ctypes.create_string_buffer(fmt.width // 8)
            fl = ctypes.c_uint32()
            st = fn(dev, fi, a, d, 1, ctypes.byref(fl))
            assert st == 0, st
            want = fn_model(fmt, xa)
            got = (dec(fmt, d.raw, 1)[0], fl.value)
            assert got == want, (nm, fmt.name, hex(xa), got, want)
            note()
    for xa in pool:
        a = enc(fmt, [xa])
        cls = (ctypes.c_uint8 * 1)()
        st = lib.cft_class(dev, fi, a, cls, 1)
        assert st == 0
        assert cls[0] == sf.classify(fmt, xa), (fmt.name, hex(xa))
        note()


def check_torder_rem(lib, dev, fmt, trials):
    fi = PREC_CODE[fmt.name]
    pool = pool_for(fmt, trials)
    rng = random.Random(19 ^ fmt.width)
    pairs = [(x, rng.choice(pool)) for x in pool]
    for nm, fn_model in (("cft_total_order", sf.total_order),
                         ("cft_total_order_mag", sf.total_order_mag)):
        fn = getattr(lib, nm)
        for xa, xb in pairs:
            a, b = enc(fmt, [xa]), enc(fmt, [xb])
            d = ctypes.create_string_buffer(fmt.width // 8)
            st = fn(dev, fi, a, b, d, 1)
            assert st == 0
            want = fn_model(fmt, xa, xb)[0]
            got = dec(fmt, d.raw, 1)[0]
            assert got == want, (nm, fmt.name, hex(xa), hex(xb))
            note()
    # remainder: pairs plus the exponent-gap extremes; the max/min pair
    # is the full walk - once per format is the point, not the sweep
    directed = [(max_normal_bits(fmt, 0), min_subnormal_bits(fmt, 0)),
                (max_normal_bits(fmt, 1), one_bits(fmt) | 1),
                (min_subnormal_bits(fmt, 0), max_normal_bits(fmt, 0))]
    for xa, xb in pairs + directed:
        a, b = enc(fmt, [xa]), enc(fmt, [xb])
        d = ctypes.create_string_buffer(fmt.width // 8)
        fl = ctypes.c_uint32()
        st = lib.cft_rem(dev, fi, a, b, d, 1, ctypes.byref(fl))
        assert st == 0, st
        want = sf.remainder(fmt, xa, xb)
        got = (dec(fmt, d.raw, 1)[0], fl.value)
        assert got == want, ("rem", fmt.name, hex(xa), hex(xb), got, want)
        note()


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
        for name in formats:
            fmt = FORMATS[name]
            t = args.trials if fmt.width <= 64 else max(6, args.trials // 5)
            check_rint(lib, dev, fmt, t)
            check_scaleb(lib, dev, fmt, t)
            check_cmp_sig(lib, dev, fmt, t)
            check_convert(lib, dev, fmt, t, formats)
            check_cvt_int(lib, dev, fmt, t)
            check_unary(lib, dev, fmt, t)
            check_torder_rem(lib, dev, fmt, t)
            print(f"  {name}: clause-5 entry points agree with the model "
                  f"({CHECKED} comparisons so far)")
    finally:
        lib.cft_close(dev)
    print(f"clause5_check: {CHECKED} comparisons, C == model on every one")


if __name__ == "__main__":
    main()
