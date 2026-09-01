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
    FORMATS, PREC_CODE, RND_MODES, vectors, is_nan,
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


def check_bad_rnd(lib, dev):
    """Every rnd-consuming entry point must refuse an attribute outside
    0..4 outright - the F1 regression: a (cft_round)-1 once sailed
    through the shared validator and computed under a rounding no legal
    attribute produces."""
    fmt = FORMATS["fp32"]
    fi = PREC_CODE["fp32"]
    a = enc(fmt, [one_bits(fmt)])
    d = ctypes.create_string_buffer(4)
    i32 = ctypes.c_int32(1)
    fl = ctypes.c_uint32()
    INVAL = 1                                    # CFT_ERR_INVALID_ARGUMENT
    for bad in (-1, 5, 7, 255):
        assert lib.cft_rint(dev, fi, bad, 0, a, d, 1,
                            ctypes.byref(fl), None) == INVAL, bad
        assert lib.cft_scaleb(dev, fi, bad, a, 0, d, 1,
                              ctypes.byref(fl), None) == INVAL, bad
        assert lib.cft_scaleb(dev, fi, bad, a, -(10 ** 9), d, 1,
                              ctypes.byref(fl), None) == INVAL, bad
        assert lib.cft_convert(dev, fi, fi, bad, a, d, 1,
                               ctypes.byref(fl)) == INVAL, bad
        assert lib.cft_cvt_from_i32(dev, fi, bad, ctypes.byref(i32), d, 1,
                                    ctypes.byref(fl)) == INVAL, bad
        assert lib.cft_cvt_to_i32(dev, fi, bad, 0, a, ctypes.byref(i32), 1,
                                  ctypes.byref(fl)) == INVAL, bad
        note(6)


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


def _int_boundary_pool(fmt):
    """Values whose magnitudes sit in the 2^28..2^70 window - the
    integer-conversion range edges. interesting_operands() never lands
    there for the wide formats (the adversarial review counted zero),
    so the 66-bit cutoff, the kept>64 check, INT64_MIN and the
    unsigned-high boundary were structurally unreached at fp128/fp256
    until these were added."""
    pool = []
    for e in (28, 30, 31, 32, 33, 52, 62, 63, 64, 65, 66, 67, 70):
        if e - 1 > fmt.emax:
            continue
        for m, de in ((1, 0), (3, -1), ((1 << fmt.prec) - 1,
                                        -(fmt.prec - 1))):
            bits, _ = sf.round_pack(fmt, 0, m, e + de, sf.RND_RNE)
            pool += [bits, bits | fmt.sign_mask]
    return pool


def check_cvt_int(lib, dev, fmt, trials):
    fi = PREC_CODE[fmt.name]
    pool = pool_for(fmt, trials) + _int_boundary_pool(fmt)
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
    fr = [("cft_cvt_from_i32", 32, True, ctypes.c_int32),
          ("cft_cvt_from_u32", 32, False, ctypes.c_uint32),
          ("cft_cvt_from_i64", 64, True, ctypes.c_int64),
          ("cft_cvt_from_u64", 64, False, ctypes.c_uint64)]
    for nm, width, signed, ctype in fr:
        fn = getattr(lib, nm)
        lo = -(1 << (width - 1)) if signed else 0
        hi = (1 << (width - 1)) - 1 if signed else (1 << width) - 1
        # per-width values: the type's own edges, high-bit patterns
        # (the review found 32-bit randoms drawn from a 64-bit range
        # were vacuous), and in-range randoms for THIS width
        ivals = [0, 1, lo, lo + 1, hi, hi - 1, hi // 3,
                 (hi >> 1) + 1, (hi >> 1) + 3]
        if not signed:
            ivals += [hi - 1023, (1 << (width - 1)) | 1,
                      0xAAAAAAAB & hi, (0xAAAAAAAAAAAAAAAB & hi)]
        ivals += [rng.randint(lo, hi) for _ in range(max(trials, 20))]
        for rnd in RND_MODES:
            for v in ivals:
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


def _fbits(fmt, num, den=1):
    """Encoding of the exactly-representable num/den, den a power of 2."""
    bits, fl = sf.round_pack(fmt, 0, num, -(den.bit_length() - 1),
                             sf.RND_RNE)
    assert fl == 0
    return bits


def _rem_families(fmt):
    """The adversarial review's remainder torture set, kept as standing
    coverage: explicit x = (2k+1)*y/2 tie families (both quotient
    parities), the half-boundary neighbours of the ea<eb wide branch,
    raw subnormal pairs for the normalisation shifts, forced small
    exponent gaps with random significands, and a sign grid."""
    p = fmt.prec
    ints = [1, 2, 3, 4, 5, 6, 7, 9, 11, 15, 21, 2 ** 20 + 1, 2 ** 23 - 1]
    vals = [(_fbits(fmt, x), _fbits(fmt, y)) for x in ints for y in ints]
    for y in (2, 3, 5, 7):
        for k in (0, 1, 2, 3, 8):
            vals.append((_fbits(fmt, (2 * k + 1) * y, 2), _fbits(fmt, y)))
    half, one = _fbits(fmt, 1, 2), _fbits(fmt, 1)
    vals += [(half, one), (half + 1, one), (half - 1, one)]
    for xm in (1, 3, 5, 0x55):
        for ym in (1, 2, 3, 7):
            vals.append((xm, ym))            # raw subnormal encodings
    rng = random.Random(0xBEEF ^ fmt.width)
    for gap in (0, 1, 2, 3):
        for _ in range(40):
            mb = (1 << (p - 1)) | rng.getrandbits(p - 1)
            ma = (1 << (p - 1)) | rng.getrandbits(p - 1)
            eb = rng.randint(fmt.emin + p, fmt.emax - p) - (p - 1)
            vals.append((sf.round_pack(fmt, 0, ma, eb + gap,
                                       sf.RND_RNE)[0],
                         sf.round_pack(fmt, 0, mb, eb, sf.RND_RNE)[0]))
    for xa, xb in list(vals[:40]):
        for sa in (0, fmt.sign_mask):
            for sb in (0, fmt.sign_mask):
                vals.append((xa | sa, xb | sb))
    return vals


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
    # remainder: pairs plus the exponent-gap extremes. The min_subnormal
    # divisor is a power of two, so its walk EXITS EARLY when the
    # residue hits zero after <= p steps - a real case, but not the
    # full walk this comment once claimed it was (the adversarial
    # review's F2). The genuine full-gap walk needs an ODD divisor
    # significand: bits value 3 is the 3-ulp... no - the 2-bit
    # subnormal 0b11, whose walk runs the whole emax-emin+p-2 gap
    # (~524.5k steps at fp256), once per format, on purpose.
    directed = [(max_normal_bits(fmt, 0), min_subnormal_bits(fmt, 0)),
                (max_normal_bits(fmt, 0), 3),
                (max_normal_bits(fmt, 1), one_bits(fmt) | 1),
                (min_subnormal_bits(fmt, 0), max_normal_bits(fmt, 0))]
    directed += _rem_families(fmt)
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


def check_host_batches(lib, dev, fmt):
    """Host-side entry points at n > 1: the per-element loops, the flag
    OR, and a NaN parked in the LAST lane so late-lane classification
    is what sets the batch's flags."""
    fi = PREC_CODE[fmt.name]
    rng = random.Random(23 ^ fmt.width)
    pool = pool_for(fmt, 30)
    finite = [x for x in pool if not is_nan(fmt, x)]
    n = 1000
    xs = [rng.choice(finite) for _ in range(n - 1)] + [snan_bits(fmt)]
    ys = [rng.choice(finite) for _ in range(n)]
    a, b = enc(fmt, xs), enc(fmt, ys)

    d = ctypes.create_string_buffer(len(a))
    fl = ctypes.c_uint32()
    assert lib.cft_next_up(dev, fi, a, d, n, ctypes.byref(fl)) == 0
    want_or = 0
    for x, g in zip(xs, dec(fmt, d.raw, n)):
        wb, wf = sf.next_up(fmt, x)
        assert g == wb, (fmt.name, hex(x))
        want_or |= wf
    assert fl.value == want_or and want_or  # the last-lane sNaN showed up
    note(n)

    assert lib.cft_cmp_sig(dev, OPC["cmplt"], fi, a, b, d, n,
                           ctypes.byref(fl), None) == 0
    for x, y, g in zip(xs, ys, dec(fmt, d.raw, n)):
        assert g == sf.cmplt_sig(fmt, x, y)[0], (fmt.name, hex(x), hex(y))
    assert fl.value == 1  # FLAG_INVALID from the last lane alone
    note(n)

    assert lib.cft_rem(dev, fi, a, b, d, n, ctypes.byref(fl)) == 0
    want_or = 0
    for x, y, g in zip(xs, ys, dec(fmt, d.raw, n)):
        wb, wf = sf.remainder(fmt, x, y)
        assert g == wb, (fmt.name, hex(x), hex(y))
        want_or |= wf
    assert fl.value == want_or
    note(n)

    cls = (ctypes.c_uint8 * n)()
    assert lib.cft_class(dev, fi, a, cls, n) == 0
    for x, g in zip(xs, cls):
        assert g == sf.classify(fmt, x), (fmt.name, hex(x))
    note(n)


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
        check_bad_rnd(lib, dev)
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
            check_host_batches(lib, dev, fmt)
            print(f"  {name}: clause-5 entry points agree with the model "
                  f"({CHECKED} comparisons so far)")
    finally:
        lib.cft_close(dev)
    print(f"clause5_check: {CHECKED} comparisons, C == model on every one")


if __name__ == "__main__":
    main()
