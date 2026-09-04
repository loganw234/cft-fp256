# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""The formatOf arithmetic entry points against the golden model.

    python3 host/tests/formatof_check.py                    # standard sweep
    python3 host/tests/formatof_check.py --pairs fp64:fp32
    python3 host/tests/formatof_check.py --trials 400       # longer randoms

Same discipline as augmented_check.py and clause5_check.py:
python/cft_golden/formatof.py defines every bit and flag, and this
replays host/src/formatof.c against it - per call (n=1) so the flag word
compares per element, plus batch calls so the element loop and the flag
OR are exercised.

What the pools are FOR, since a random sweep would score almost nothing
here:

* THE DESTINATION'S BOUNDARIES. Every exception belongs to dfmt, so the
  pools carry source values sitting exactly on the destination's
  overflow threshold, its least normal, its least subnormal and half of
  each - values that are utterly unremarkable in the source and decide
  the answer in the destination.
* THE DESTINATION'S MIDPOINTS. A narrowing rounds at a position the
  source grid straddles, so the pools carry source values one, half and
  a quarter ulp of the DESTINATION above and below a destination grid
  point, which is where a rounding written against the wrong descriptor
  goes wrong and nowhere else.
* THE DOUBLE-ROUNDING WITNESSES. The families of
  formatof.double_rounding_witness() for division, square root and
  fused multiply-add, on every ordered pair - the cases that separate
  this implementation from the plausible one that rounds in the source
  format first. They are checked twice: against the model, and against
  the composed route, which must DISAGREE. A run where the witness
  agreed with the composed route would mean the witness had stopped
  witnessing, and that is worth failing on.
* EXACT CANCELLATIONS AND NEAR-MIDPOINT QUOTIENTS, because those are
  where a sticky bit that is one place out survives everything else.
* SPECIALS AND SUBNORMALS OF BOTH FORMATS, including the source
  subnormals that are ordinary normals in a wider destination.
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
    FORMATS, PREC_CODE, RND_NAMES, RND_MODES,
    one_bits, zero_bits, inf_bits, qnan_bits, snan_bits,
    min_subnormal_bits, max_subnormal_bits, min_normal_bits,
    max_normal_bits,
)
from cft_golden import formatof as fo  # noqa: E402
from cft_golden import softfloat as sf  # noqa: E402

#: (library entry point, internal name, arity). The order is cft.h's.
OPS = (
    ("cft_formatof_add",  fo.FN_FO_ADD,  2),
    ("cft_formatof_sub",  fo.FN_FO_SUB,  2),
    ("cft_formatof_mul",  fo.FN_FO_MUL,  2),
    ("cft_formatof_div",  fo.FN_FO_DIV,  2),
    ("cft_formatof_sqrt", fo.FN_FO_SQRT, 1),
    ("cft_formatof_fma",  fo.FN_FO_FMA,  3),
)

CHECKED = 0
WITNESSES = 0


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
    for nm, _fn, arity in OPS:
        f = getattr(lib, nm)
        ops = [vp] * arity
        f.argtypes = [vp, i, i, i] + ops + [vp, sz, u32p, u32p]
        f.restype = i


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


def call(lib, dev, nm, arity, sfmt, dfmt, rnd, ops, n):
    """One library call over n elements. `ops` is a tuple of bit lists,
    one per operand the entry point reads."""
    args = [enc(sfmt, o) for o in ops]
    out = ctypes.create_string_buffer(n * (dfmt.width // 8))
    flags = ctypes.c_uint32(0)
    bus = ctypes.c_uint32(0xdeadbeef)
    st = getattr(lib, nm)(dev, PREC_CODE[sfmt.name], PREC_CODE[dfmt.name],
                          rnd, *args, out, n, ctypes.byref(flags),
                          ctypes.byref(bus))
    if st != 0:
        raise SystemExit(f"{nm}({sfmt.name}->{dfmt.name}) returned {st}")
    return dec(dfmt, out.raw, n), flags.value, bus.value


# ---- the operand pools ------------------------------------------------

def _val(fmt, sign, m, e):
    """The encoding of (-1)^sign * m * 2^e when it is EXACT in fmt, else
    None. Derived, never typed: every pool entry below is built this
    way from the format descriptors."""
    if m == 0:
        return zero_bits(fmt, sign)
    bits, flags = sf.round_pack(fmt, sign, m, e, sf.RND_RNE)
    return None if flags else bits


def _extend(out, *vals):
    for v in vals:
        if v is not None:
            out.append(v)


def source_pool(sfmt, dfmt, extra, seed):
    """Source-format operands aimed at the DESTINATION's decisions."""
    rng = random.Random(seed ^ (sfmt.width * 1013) ^ (dfmt.width * 71))
    out = []
    _extend(out,
            zero_bits(sfmt), zero_bits(sfmt, 1),
            one_bits(sfmt), one_bits(sfmt, 1),
            inf_bits(sfmt), inf_bits(sfmt, 1),
            qnan_bits(sfmt), snan_bits(sfmt), snan_bits(sfmt, 3),
            min_subnormal_bits(sfmt), min_subnormal_bits(sfmt, 1),
            max_subnormal_bits(sfmt), min_normal_bits(sfmt),
            max_normal_bits(sfmt), max_normal_bits(sfmt, 1))

    ps, pd = sfmt.prec, dfmt.prec
    # The destination's own landmarks, carried into the source (exact,
    # since the source is at least as wide wherever this matters), plus
    # their neighbours on the SOURCE grid - which is the only place a
    # rounding written against the wrong descriptor can be caught.
    marks = [min_subnormal_bits(dfmt), max_subnormal_bits(dfmt),
             min_normal_bits(dfmt), max_normal_bits(dfmt),
             one_bits(dfmt), zero_bits(dfmt)]
    for mb in marks:
        v, fl = sf.convert(dfmt, sfmt, mb, sf.RND_RNE)
        if fl:
            continue
        for sgn in (0, 1):
            b = v | (sfmt.sign_mask if sgn else 0)
            _extend(out, b)
            if b & ~sfmt.sign_mask:
                _extend(out, b - 1, b + 1)

    # Destination midpoints and their quarter/half/three-quarter
    # neighbours, expressed in the source. Only reachable when the
    # source is strictly wider, which is exactly when they matter.
    if ps > pd:
        for E in sorted({0, 1, -1, dfmt.emax, dfmt.emax - 1, dfmt.emin,
                         dfmt.emin + 1, dfmt.emin - 1,
                         dfmt.emin - dfmt.man_w,
                         dfmt.emin - dfmt.man_w + 1, pd, -pd}):
            base = _val(sfmt, 0, (1 << (pd - 1)), E - (pd - 1))
            if base is None:
                continue
            for sgn in (0, 1):
                for dm, de in ((1, E - pd), (1, E - pd - 1),
                               (3, E - pd - 2), (1, E - pd + 1),
                               (1, E - ps + 1)):
                    step = _val(sfmt, 0, dm, de)
                    if step is None:
                        continue
                    hi, fl1 = sf.add(sfmt, base, step, sf.RND_RNE)
                    lo, fl2 = sf.sub(sfmt, base, step, sf.RND_RNE)
                    if not fl1:
                        _extend(out, hi | (sfmt.sign_mask if sgn else 0))
                    if not fl2:
                        _extend(out, lo | (sfmt.sign_mask if sgn else 0))
                _extend(out, base | (sfmt.sign_mask if sgn else 0))

        # Just above and just below the destination's overflow
        # threshold - the midpoint between maxnormal(dfmt) and 2^(emax+1).
        thr = _val(sfmt, 0, (1 << pd) - 1, dfmt.emax - pd + 1)
        if thr is not None:
            for sgn in (0, 1):
                b = thr | (sfmt.sign_mask if sgn else 0)
                _extend(out, b, b - 1, b + 1)
        # And half the destination's least subnormal, which rounds to
        # zero or to that subnormal depending only on the attribute.
        halftiny = _val(sfmt, 0, 1, dfmt.emin - dfmt.man_w - 1)
        if halftiny is not None:
            for sgn in (0, 1):
                b = halftiny | (sfmt.sign_mask if sgn else 0)
                _extend(out, b, b + 1)

    # Exact powers of two across the source's range, so that a product
    # or quotient lands exactly on a binade edge of the destination.
    span = max(1, (sfmt.emax - sfmt.emin) // 12)
    for E in range(sfmt.emin, sfmt.emax + 1, span):
        for sgn in (0, 1):
            _extend(out, _val(sfmt, sgn, 1, E))
    for E in (0, 1, -1, ps, -ps, 2 * ps, -2 * ps):
        for sgn in (0, 1):
            _extend(out, _val(sfmt, sgn, 1, E),
                    _val(sfmt, sgn, 3, E - 1),
                    _val(sfmt, sgn, (1 << ps) - 1, E - ps + 1))

    for _ in range(extra):
        out.append(rng.getrandbits(sfmt.width))
    for _ in range(extra):
        # exponent-banded randoms: a uniform bit pattern is almost
        # always a huge normal, which decides nothing about subnormals
        ef = rng.randrange(0, sfmt.exp_mask + 1)
        out.append((rng.randrange(0, 2) << (sfmt.width - 1)) |
                   (ef << sfmt.man_w) |
                   rng.getrandbits(sfmt.man_w))

    seen, uniq = set(), []
    for b in out:
        b &= (1 << sfmt.width) - 1
        if b not in seen:
            seen.add(b)
            uniq.append(b)
    return uniq


def triples(pool, extra, seed):
    """(a, b, c) triples from a pool: a diagonal sweep plus randoms, and
    the exact cancellations and reciprocal pairs that no diagonal
    reaches."""
    rng = random.Random(seed)
    out = []
    n = len(pool)
    for i, a in enumerate(pool):
        out.append((a, pool[(i * 7 + 1) % n], pool[(i * 13 + 5) % n]))
        out.append((a, a, pool[(i * 3 + 2) % n]))
    for _ in range(extra):
        out.append((pool[rng.randrange(n)], pool[rng.randrange(n)],
                    pool[rng.randrange(n)]))
    return out


# ---- the checks -------------------------------------------------------

def check_pair(lib, dev, sfmt, dfmt, rnds, extra, seed, batch):
    global CHECKED
    pool = source_pool(sfmt, dfmt, extra, seed)
    cases = triples(pool, extra * 2, seed + 1)
    label = f"{sfmt.name}->{dfmt.name}"

    for rnd in rnds:
        for nm, fn, arity in OPS:
            # per element: the flag word is exactly this case's
            wants = []
            for a, b, c in cases:
                want = fo.compute(sfmt, dfmt, fn, a, b, c, rnd)
                ops = [[a], [b], [c]][:arity]
                got, gf, gbus = call(lib, dev, nm, arity, sfmt, dfmt, rnd,
                                     ops, 1)
                CHECKED += 1
                if (got[0], gf) != want:
                    raise SystemExit(
                        f"MISMATCH {label} {fn} {RND_NAMES[rnd]}\n"
                        f"  a 0x{a:0{sfmt.width // 4}x}\n"
                        f"  b 0x{b:0{sfmt.width // 4}x}\n"
                        f"  c 0x{c:0{sfmt.width // 4}x}\n"
                        f"  model 0x{want[0]:0{dfmt.width // 4}x} "
                        f"flags 0x{want[1]:02x}\n"
                        f"  lib   0x{got[0]:0{dfmt.width // 4}x} "
                        f"flags 0x{gf:02x}")
                if dfmt.prec < sfmt.prec and gbus != 0:
                    raise SystemExit(
                        f"{label} {fn}: the narrowing route issues no "
                        f"device pass, so bus_out must read 0, got "
                        f"0x{gbus:08x}")
                wants.append(want)

            # as arrays: the element loop and the flag OR
            if batch:
                cols = [[t[k] for t in cases] for k in range(3)][:arity]
                got, gf, _ = call(lib, dev, nm, arity, sfmt, dfmt, rnd,
                                  cols, len(cases))
                CHECKED += len(cases)
                acc = 0
                for k, (wb, wf) in enumerate(wants):
                    acc |= wf
                    if got[k] != wb:
                        raise SystemExit(
                            f"ARRAY MISMATCH {label} {fn} "
                            f"{RND_NAMES[rnd]} element {k}: "
                            f"model 0x{wb:x} lib 0x{got[k]:x}")
                if gf != acc:
                    raise SystemExit(
                        f"ARRAY FLAGS {label} {fn} {RND_NAMES[rnd]}: "
                        f"got 0x{gf:02x} want 0x{acc:02x}")


def check_witnesses(lib, dev, sfmt, dfmt):
    """The double-rounding witnesses, through the LIBRARY.

    Two assertions per witness, and the second is the one that matters:
    the library agrees with the model, AND the composed route (round in
    the source format, then convert) DISAGREES with both. A witness that
    stopped separating the two would leave this harness checking that
    two identical things are identical.
    """
    global CHECKED, WITNESSES
    for nm, fn, arity in OPS:
        if fn not in (fo.FN_FO_FMA, fo.FN_FO_DIV, fo.FN_FO_SQRT):
            continue
        a, b, c, wfmt = fo.double_rounding_witness(sfmt, dfmt, fn)
        want = fo.compute(sfmt, dfmt, fn, a, b, c, sf.RND_RNE)
        ops = [[a], [b], [c]][:arity]
        got, gf, _ = call(lib, dev, nm, arity, sfmt, dfmt, sf.RND_RNE,
                          ops, 1)
        CHECKED += 1
        WITNESSES += 1
        if (got[0], gf) != want:
            raise SystemExit(
                f"WITNESS MISMATCH {sfmt.name}->{dfmt.name} {fn}: "
                f"model 0x{want[0]:x}/0x{want[1]:02x} "
                f"lib 0x{got[0]:x}/0x{gf:02x}")
        wrong = fo.composed_route(sfmt, dfmt, wfmt, fn, a, b, c,
                                  sf.RND_RNE)
        if wrong[0] == want[0]:
            raise SystemExit(
                f"{sfmt.name}->{dfmt.name} {fn}: the composed route "
                f"agreed with the correct one, so this witness no "
                f"longer witnesses anything - fix the witness before "
                f"trusting this harness")


def check_refusals(lib, dev):
    """The API promises the vectors cannot express."""
    f32 = FORMATS["fp32"]
    a = enc(f32, [one_bits(f32)])
    out = ctypes.create_string_buffer(8)
    fl = ctypes.c_uint32(0)
    bad = 0

    def st(*args):
        return lib.cft_formatof_add(*args)

    if st(dev, 9, 0, 0, a, a, out, 1, ctypes.byref(fl), None) == 0:
        bad += 1
        print("FAIL: a bad source format was accepted")
    if st(dev, 0, 9, 0, a, a, out, 1, ctypes.byref(fl), None) == 0:
        bad += 1
        print("FAIL: a bad destination format was accepted")
    if st(dev, 0, 0, 5, a, a, out, 1, ctypes.byref(fl), None) == 0:
        bad += 1
        print("FAIL: a rounding attribute outside 0..4 was accepted")
    if st(dev, 0, 0, 0, None, a, out, 1, ctypes.byref(fl), None) == 0:
        bad += 1
        print("FAIL: a NULL operand was accepted")
    if st(dev, 0, 0, 0, a, a, None, 1, ctypes.byref(fl), None) == 0:
        bad += 1
        print("FAIL: a NULL destination was accepted")
    if st(None, 0, 0, 0, a, a, out, 1, ctypes.byref(fl), None) == 0:
        bad += 1
        print("FAIL: a NULL device was accepted")
    # n == 0 is not an error and must clear the flag word
    fl.value = 0xdead
    if st(dev, 0, 0, 0, None, None, None, 0, ctypes.byref(fl), None) != 0 \
            or fl.value != 0:
        bad += 1
        print("FAIL: n == 0 must be OK with a cleared flag word")
    # sqrt reads one operand, so a NULL b is not its business to refuse
    if lib.cft_formatof_sqrt(dev, 0, 0, 0, a, out, 1, ctypes.byref(fl),
                             None) != 0:
        bad += 1
        print("FAIL: cft_formatof_sqrt refused a valid call")
    if bad:
        raise SystemExit(f"{bad} refusal check(s) failed")
    return 8


def check_same_format_alias(lib, dev, fmt):
    """sfmt == dfmt must be the existing operation, bit for bit. That is
    the base case of the generalisation and the one a reader will
    assume; it is cheap to check and expensive to have wrong."""
    global CHECKED
    lib.cft_run.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int,
                            ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p,
                            ctypes.c_void_p, ctypes.c_void_p,
                            ctypes.c_size_t,
                            ctypes.POINTER(ctypes.c_uint32),
                            ctypes.POINTER(ctypes.c_uint32)]
    lib.cft_run.restype = ctypes.c_int
    lib.cft_div.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int,
                            ctypes.c_void_p, ctypes.c_void_p,
                            ctypes.c_void_p, ctypes.c_size_t,
                            ctypes.POINTER(ctypes.c_uint32),
                            ctypes.POINTER(ctypes.c_uint32)]
    lib.cft_div.restype = ctypes.c_int
    lib.cft_sqrt.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int,
                             ctypes.c_void_p, ctypes.c_void_p,
                             ctypes.c_size_t,
                             ctypes.POINTER(ctypes.c_uint32),
                             ctypes.POINTER(ctypes.c_uint32)]
    lib.cft_sqrt.restype = ctypes.c_int

    pool = source_pool(fmt, fmt, 8, 99)
    code = PREC_CODE[fmt.name]
    esz = fmt.width // 8
    for rnd in RND_MODES:
        for i, a in enumerate(pool):
            b = pool[(i * 5 + 3) % len(pool)]
            c = pool[(i * 11 + 7) % len(pool)]
            ea, eb, ec = enc(fmt, [a]), enc(fmt, [b]), enc(fmt, [c])
            for nm, fn, arity in OPS:
                ops = [[a], [b], [c]][:arity]
                got, gf, _ = call(lib, dev, nm, arity, fmt, fmt, rnd,
                                  ops, 1)
                ref = ctypes.create_string_buffer(esz)
                rf = ctypes.c_uint32(0)
                if fn == fo.FN_FO_DIV:
                    lib.cft_div(dev, code, rnd, ea, eb, ref, 1,
                                ctypes.byref(rf), None)
                elif fn == fo.FN_FO_SQRT:
                    lib.cft_sqrt(dev, code, rnd, ea, ref, 1,
                                 ctypes.byref(rf), None)
                else:
                    op, aa, bb, cc = {
                        fo.FN_FO_ADD: (1, ea, None, eb),
                        fo.FN_FO_SUB: (2, ea, None, eb),
                        fo.FN_FO_MUL: (3, ea, eb, None),
                        fo.FN_FO_FMA: (0, ea, eb, ec),
                    }[fn]
                    lib.cft_run(dev, op, code, rnd, aa, bb, cc, ref, 1,
                                ctypes.byref(rf), None)
                want = dec(fmt, ref.raw, 1)[0]
                CHECKED += 1
                if got[0] != want or gf != rf.value:
                    raise SystemExit(
                        f"SAME-FORMAT ALIAS {fmt.name} {fn} "
                        f"{RND_NAMES[rnd]}: formatOf 0x{got[0]:x}/"
                        f"0x{gf:02x} vs the plain call 0x{want:x}/"
                        f"0x{rf.value:02x}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pairs", nargs="+",
                    help="ordered pairs as sfmt:dfmt (default: all 16)")
    ap.add_argument("--rounding", nargs="+", default=list(RND_NAMES.values()),
                    choices=list(RND_NAMES.values()))
    ap.add_argument("--trials", type=int, default=24,
                    help="random operands added to each pool")
    ap.add_argument("--no-batch", action="store_true")
    ap.add_argument("--seed", type=int, default=5)
    args = ap.parse_args()

    names = list(FORMATS)
    if args.pairs:
        pairs = []
        for spec in args.pairs:
            s, _, d = spec.partition(":")
            if s not in FORMATS or d not in FORMATS:
                raise SystemExit(f"bad pair {spec!r}")
            pairs.append((FORMATS[s], FORMATS[d]))
    else:
        pairs = [(FORMATS[s], FORMATS[d]) for s in names for d in names]
    by_name = {v: k for k, v in RND_NAMES.items()}
    rnds = [by_name[r] for r in args.rounding]

    lib = load_library()
    bind(lib)
    dev = open_dev(lib)

    nref = check_refusals(lib, dev)
    for sfmt, dfmt in pairs:
        check_pair(lib, dev, sfmt, dfmt, rnds, args.trials, args.seed,
                   not args.no_batch)
        if dfmt.prec < sfmt.prec:
            check_witnesses(lib, dev, sfmt, dfmt)
        print(f"  {sfmt.name}->{dfmt.name}: ok")
    for name in names:
        if (FORMATS[name], FORMATS[name]) in pairs:
            check_same_format_alias(lib, dev, FORMATS[name])
    lib.cft_close(dev)
    print(f"formatof_check: {CHECKED} comparisons over {len(pairs)} format "
          f"pair(s), {WITNESSES} double-rounding witnesses and {nref} "
          f"refusal checks, C == model on every one")


if __name__ == "__main__":
    main()
