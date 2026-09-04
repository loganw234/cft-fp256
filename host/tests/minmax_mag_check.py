# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""ABI 0.7 package B against the golden model and against 754's text.

    python3 host/tests/minmax_mag_check.py                # standard sweep
    python3 host/tests/minmax_mag_check.py --formats fp64
    python3 host/tests/minmax_mag_check.py --trials 400   # longer randoms

Three things land together in this package and they are checked here
together, because they are one library change:

1. 754-2019 9.6's four magnitude forms - minimumMagnitude,
   minimumMagnitudeNumber, maximumMagnitude, maximumMagnitudeNumber -
   against python/cft_golden, per call (n=1) so that flags compare per
   element, and then as batches so that the loop and the flag OR are
   exercised. Same discipline as clause5_check.py: the model defines
   every bit, this replays the C against it.

2. The sticky status word of 7.1 and the six operations of 5.7.4.
   Nothing in the model corresponds to it - it is state, not
   arithmetic - so it is checked against the standard's own
   sentences, quoted at each check: accumulation across calls, the
   union over a batch's elements, lowering only at the caller's
   request, the save/restore round trip, and a call that raises
   nothing leaving the word exactly as it stood.

3. The three conformance predicates of 5.7.1, which are constants.

The pools are the same shape clause5_check.py uses: every interesting
encoding of the format, both signs, the NaN zoo, and seeded randoms -
plus, for these four operations specifically, every EQUAL-MAGNITUDE
pair, which is the family 9.6 defers to the base operation on and the
one an implementation is most likely to get wrong.
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
    FORMATS, PREC_CODE, MINMAX_MAG_FNS, MINMAX_MAG_IMPL,
    zero_bits, inf_bits, qnan_bits, snan_bits, one_bits,
    min_subnormal_bits, max_subnormal_bits, min_normal_bits,
    max_normal_bits,
)

FLAG_INVALID = 1 << 0
FLAG_DIVBYZERO = 1 << 1
FLAG_OVERFLOW = 1 << 2
FLAG_UNDERFLOW = 1 << 3
FLAG_INEXACT = 1 << 4
FLAGS_ALL = 0x1f

CHECKED = 0


def note(k=1):
    global CHECKED
    CHECKED += k


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
    vp, sz, u32 = ctypes.c_void_p, ctypes.c_size_t, ctypes.c_uint32
    i = ctypes.c_int
    lib.cft_open.argtypes = [ctypes.c_char_p, i, ctypes.POINTER(vp)]
    lib.cft_open.restype = i
    lib.cft_close.argtypes = [vp]
    lib.cft_close.restype = None
    for nm in ("cft_min_mag", "cft_max_mag", "cft_minnum_mag",
               "cft_maxnum_mag"):
        fn = getattr(lib, nm)
        fn.argtypes = [vp, i, vp, vp, vp, sz, u32p]
        fn.restype = i
    # the 5.7.4 six
    lib.cft_lower_flags.argtypes = [vp, u32]
    lib.cft_lower_flags.restype = None
    lib.cft_raise_flags.argtypes = [vp, u32]
    lib.cft_raise_flags.restype = None
    lib.cft_test_flags.argtypes = [vp, u32]
    lib.cft_test_flags.restype = i
    lib.cft_save_all_flags.argtypes = [vp]
    lib.cft_save_all_flags.restype = u32
    lib.cft_restore_flags.argtypes = [vp, u32, u32]
    lib.cft_restore_flags.restype = None
    lib.cft_test_saved_flags.argtypes = [u32, u32]
    lib.cft_test_saved_flags.restype = i
    # 5.7.1
    for nm in ("cft_is754version1985", "cft_is754version2008",
               "cft_is754version2019"):
        fn = getattr(lib, nm)
        fn.argtypes = []
        fn.restype = i
    # producers used by the status-word checks
    lib.cft_run.argtypes = [vp, i, i, i, vp, vp, vp, vp, sz, u32p, u32p]
    lib.cft_run.restype = i
    lib.cft_div.argtypes = [vp, i, i, vp, vp, vp, sz, u32p, u32p]
    lib.cft_div.restype = i
    lib.cft_next_up.argtypes = [vp, i, vp, vp, sz, u32p]
    lib.cft_next_up.restype = i
    lib.cft_class.argtypes = [vp, i, vp, vp, sz]
    lib.cft_class.restype = i


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


LIBFN = {"min_mag": "cft_min_mag", "max_mag": "cft_max_mag",
         "minnum_mag": "cft_minnum_mag", "maxnum_mag": "cft_maxnum_mag"}


# ---- pools -----------------------------------------------------------

def magnitudes(fmt):
    """The magnitude ladder, sign bit clear."""
    one = one_bits(fmt)
    return [
        zero_bits(fmt, 0),
        min_subnormal_bits(fmt),
        max_subnormal_bits(fmt),
        min_normal_bits(fmt),
        one,
        one | 1,
        one + (1 << fmt.man_w),          # 2.0
        max_normal_bits(fmt),
        inf_bits(fmt, 0),
    ]


def pool_for(fmt, extra, seed=1234):
    """Every interesting encoding in both signs, the NaN zoo, and
    seeded randoms."""
    out = []
    for m in magnitudes(fmt):
        out.append(m)
        out.append(m | fmt.sign_mask)
    out += [qnan_bits(fmt), qnan_bits(fmt) | 7,
            qnan_bits(fmt) | fmt.sign_mask,
            snan_bits(fmt), snan_bits(fmt) | 3,
            snan_bits(fmt) | fmt.sign_mask]
    rng = random.Random(seed + fmt.width)
    for _ in range(extra):
        out.append(rng.getrandbits(fmt.width))
    return out


# ---- 1. the four magnitude forms ------------------------------------

def check_scalar(lib, dev, fmt, trials):
    """One call per pair, so the flag word is exactly that pair's."""
    fi = PREC_CODE[fmt.name]
    esz = fmt.width // 8
    pool = pool_for(fmt, trials)
    d = ctypes.create_string_buffer(esz)
    fl = ctypes.c_uint32(0)
    for name in MINMAX_MAG_FNS:
        fn = getattr(lib, LIBFN[name])
        impl = MINMAX_MAG_IMPL[name]
        for xa in pool:
            for xb in pool:
                a = enc(fmt, [xa])
                b = enc(fmt, [xb])
                fl.value = 0xdeadbeef
                st = fn(dev, fi, a, b, d, 1, ctypes.byref(fl))
                assert st == 0, (name, fmt.name, st)
                got = dec(fmt, d.raw, 1)[0]
                wb, wf = impl(fmt, xa, xb)
                assert got == wb, (
                    f"{name} {fmt.name} a=0x{xa:x} b=0x{xb:x}: "
                    f"C 0x{got:x}, model 0x{wb:x}")
                assert fl.value == wf, (
                    f"{name} {fmt.name} a=0x{xa:x} b=0x{xb:x}: "
                    f"C flags 0x{fl.value:x}, model 0x{wf:x}")
                note()


def check_equal_magnitude_family(lib, dev, fmt):
    """The family 9.6 hands to the base operation: |x| == |y|. Every
    magnitude in the ladder, against itself in both sign
    combinations - which is where an implementation that prefers x or
    y instead of deferring to minimum/maximum diverges."""
    fi = PREC_CODE[fmt.name]
    esz = fmt.width // 8
    d = ctypes.create_string_buffer(esz)
    fl = ctypes.c_uint32(0)
    for m in magnitudes(fmt):
        for sa in (0, fmt.sign_mask):
            for sb in (0, fmt.sign_mask):
                xa, xb = m | sa, m | sb
                for name in MINMAX_MAG_FNS:
                    fn = getattr(lib, LIBFN[name])
                    st = fn(dev, fi, enc(fmt, [xa]), enc(fmt, [xb]), d, 1,
                            ctypes.byref(fl))
                    assert st == 0
                    got = dec(fmt, d.raw, 1)[0]
                    wb, wf = MINMAX_MAG_IMPL[name](fmt, xa, xb)
                    assert got == wb and fl.value == wf, (
                        f"{name} {fmt.name} equal magnitudes "
                        f"0x{xa:x} 0x{xb:x}: C 0x{got:x}/0x{fl.value:x}, "
                        f"model 0x{wb:x}/0x{wf:x}")
                    note()


def check_batch(lib, dev, fmt, trials):
    """A whole array in one call: every element right, and the flag
    word the OR of the elements' - cft.h's batch contract."""
    fi = PREC_CODE[fmt.name]
    esz = fmt.width // 8
    pool = pool_for(fmt, trials, seed=99)
    rng = random.Random(7 + fmt.width)
    n = len(pool)
    xs = list(pool)
    ys = [pool[rng.randrange(n)] for _ in range(n)]
    a, b = enc(fmt, xs), enc(fmt, ys)
    d = ctypes.create_string_buffer(n * esz)
    fl = ctypes.c_uint32(0)
    for name in MINMAX_MAG_FNS:
        fn = getattr(lib, LIBFN[name])
        assert fn(dev, fi, a, b, d, n, ctypes.byref(fl)) == 0
        want_or = 0
        for x, y, g in zip(xs, ys, dec(fmt, d.raw, n)):
            wb, wf = MINMAX_MAG_IMPL[name](fmt, x, y)
            assert g == wb, (name, fmt.name, hex(x), hex(y))
            want_or |= wf
        assert fl.value == want_or, (name, fmt.name, hex(fl.value),
                                     hex(want_or))
        note(n)


def check_aliasing_and_arguments(lib, dev, fmt):
    """cft.h's promises: d may alias a or b, n == 0 is a no-op that
    raises nothing, a NULL operand or a bad format is refused."""
    fi = PREC_CODE[fmt.name]
    esz = fmt.width // 8
    xs = [min_normal_bits(fmt), inf_bits(fmt, 1), zero_bits(fmt, 1),
          snan_bits(fmt)]
    ys = [inf_bits(fmt, 0), min_subnormal_bits(fmt), zero_bits(fmt, 0),
          one_bits(fmt)]
    n = len(xs)
    fl = ctypes.c_uint32(0)
    for name in MINMAX_MAG_FNS:
        fn = getattr(lib, LIBFN[name])
        want = [MINMAX_MAG_IMPL[name](fmt, x, y)[0] for x, y in zip(xs, ys)]
        # d aliases a
        buf = ctypes.create_string_buffer(enc(fmt, xs), n * esz)
        other = enc(fmt, ys)
        assert fn(dev, fi, buf, other, buf, n, ctypes.byref(fl)) == 0
        assert dec(fmt, buf.raw, n) == want, ("alias a", name, fmt.name)
        # d aliases b
        buf = ctypes.create_string_buffer(enc(fmt, ys), n * esz)
        other = enc(fmt, xs)
        assert fn(dev, fi, other, buf, buf, n, ctypes.byref(fl)) == 0
        assert dec(fmt, buf.raw, n) == want, ("alias b", name, fmt.name)
        note(2 * n)

        # n == 0: OK, and no flag
        fl.value = 0xdeadbeef
        assert fn(dev, fi, None, None, None, 0, ctypes.byref(fl)) == 0
        assert fl.value == 0
        # refusals
        d = ctypes.create_string_buffer(n * esz)
        assert fn(dev, fi, enc(fmt, xs), None, d, n,
                  ctypes.byref(fl)) == 1        # CFT_ERR_INVALID_ARGUMENT
        assert fn(dev, 9, enc(fmt, xs), enc(fmt, ys), d, n,
                  ctypes.byref(fl)) == 1
        assert fn(None, fi, enc(fmt, xs), enc(fmt, ys), d, n,
                  ctypes.byref(fl)) == 1
        note(4)


# ---- 2. the status word (7.1, 5.7.4) --------------------------------

def fresh(lib, dev):
    lib.cft_lower_flags(dev, FLAGS_ALL)
    assert lib.cft_save_all_flags(dev) == 0


def check_status_word(lib, dev):
    """7.1: "Status flags shall be lowered only at the user's request."
    Everything below is that sentence and 5.7.4's six operations."""
    fmt = FORMATS["fp32"]
    fi = PREC_CODE["fp32"]
    esz = 4
    d = ctypes.create_string_buffer(4 * esz)

    def run(op, xs, ys=None, zs=None):
        n = len(xs)
        a = enc(fmt, xs)
        b = enc(fmt, ys) if ys else None
        c = enc(fmt, zs) if zs else None
        fl = ctypes.c_uint32(0)
        assert lib.cft_run(dev, op, fi, 0, a, b, c, d, n,
                           ctypes.byref(fl), None) == 0
        return fl.value

    OP_ADD, OP_MUL, OP_MIN = 1, 3, 7
    big = max_normal_bits(fmt)
    tiny = min_subnormal_bits(fmt)
    one = one_bits(fmt)
    third = 0x3eaaaaab                       # 1/3 rounded: inexact source

    # a fresh device begins with every flag lowered (7.1)
    fresh(lib, dev)
    assert lib.cft_test_flags(dev, FLAGS_ALL) == 0
    note()

    # one call's flags land in the word
    f1 = run(OP_ADD, [big], zs=[big])        # overflow + inexact
    assert f1 & FLAG_OVERFLOW and f1 & FLAG_INEXACT
    assert lib.cft_save_all_flags(dev) == f1
    assert lib.cft_test_flags(dev, FLAG_OVERFLOW) == 1
    assert lib.cft_test_flags(dev, FLAG_INVALID) == 0
    note(4)

    # ACCUMULATION: a second call ORs in and nothing is lost
    f2 = run(OP_MUL, [tiny], ys=[third])     # underflow + inexact
    assert f2 & FLAG_UNDERFLOW
    assert lib.cft_save_all_flags(dev) == (f1 | f2)
    note(2)

    # a call that raises nothing leaves the word EXACTLY as it stood
    before = lib.cft_save_all_flags(dev)
    f3 = run(OP_ADD, [one], zs=[one])        # 1 + 1 = 2, exact
    assert f3 == 0
    assert lib.cft_save_all_flags(dev) == before
    # and so does a non-computational one, which has no flag word at all
    cls = (ctypes.c_uint8 * 1)()
    assert lib.cft_class(dev, fi, enc(fmt, [snan_bits(fmt)]), cls, 1) == 0
    assert lib.cft_save_all_flags(dev) == before
    note(3)

    # PER-ELEMENT UNION: one batch call whose elements each raise a
    # different thing puts all of them in the word at once
    fresh(lib, dev)
    xs = [big, tiny, one, snan_bits(fmt)]
    ys = [big, third, one, one]
    fl = ctypes.c_uint32(0)
    assert lib.cft_run(dev, OP_MUL, fi, 0, enc(fmt, xs), enc(fmt, ys),
                       None, d, 4, ctypes.byref(fl), None) == 0
    assert fl.value & FLAG_OVERFLOW and fl.value & FLAG_UNDERFLOW \
        and fl.value & FLAG_INVALID and fl.value & FLAG_INEXACT
    assert lib.cft_save_all_flags(dev) == fl.value
    note(2)

    # the composed and host entry points feed the same word
    fresh(lib, dev)
    fl.value = 0
    assert lib.cft_div(dev, fi, 0, enc(fmt, [one]), enc(fmt, [zero_bits(fmt)]),
                       d, 1, ctypes.byref(fl), None) == 0
    assert fl.value == FLAG_DIVBYZERO
    assert lib.cft_save_all_flags(dev) == FLAG_DIVBYZERO
    fl.value = 0
    assert lib.cft_next_up(dev, fi, enc(fmt, [snan_bits(fmt)]), d, 1,
                           ctypes.byref(fl)) == 0
    assert fl.value == FLAG_INVALID
    assert lib.cft_save_all_flags(dev) == (FLAG_DIVBYZERO | FLAG_INVALID)
    note(4)

    # ... and so do the four new ones, which is the check the negative
    # control for the hook breaks
    fresh(lib, dev)
    fl.value = 0
    assert lib.cft_min_mag(dev, fi, enc(fmt, [snan_bits(fmt)]),
                           enc(fmt, [one]), d, 1, ctypes.byref(fl)) == 0
    assert fl.value == FLAG_INVALID
    assert lib.cft_save_all_flags(dev) == FLAG_INVALID, (
        "cft_min_mag did not OR its flags into the status word")
    note(2)

    # lowerFlags BY MASK: only the named flags go down
    fresh(lib, dev)
    lib.cft_raise_flags(dev, FLAGS_ALL)
    assert lib.cft_save_all_flags(dev) == FLAGS_ALL
    lib.cft_lower_flags(dev, FLAG_INEXACT | FLAG_UNDERFLOW)
    assert lib.cft_save_all_flags(dev) == (
        FLAGS_ALL & ~(FLAG_INEXACT | FLAG_UNDERFLOW))
    assert lib.cft_test_flags(dev, FLAG_INEXACT) == 0
    assert lib.cft_test_flags(dev, FLAG_INVALID) == 1
    # testFlags is ANY of the mask, not all of it
    assert lib.cft_test_flags(dev, FLAG_INEXACT | FLAG_INVALID) == 1
    assert lib.cft_test_flags(dev, 0) == 0
    note(6)

    # raiseFlags by mask, one bit at a time
    fresh(lib, dev)
    for bit in (FLAG_INVALID, FLAG_DIVBYZERO, FLAG_OVERFLOW,
                FLAG_UNDERFLOW, FLAG_INEXACT):
        lib.cft_raise_flags(dev, bit)
        assert lib.cft_test_flags(dev, bit) == 1
        note()
    assert lib.cft_save_all_flags(dev) == FLAGS_ALL
    note()

    # SAVE / RESTORE round trip
    fresh(lib, dev)
    lib.cft_raise_flags(dev, FLAG_INVALID | FLAG_OVERFLOW)
    saved = lib.cft_save_all_flags(dev)
    lib.cft_lower_flags(dev, FLAGS_ALL)
    lib.cft_raise_flags(dev, FLAG_INEXACT)
    lib.cft_restore_flags(dev, saved, FLAGS_ALL)
    assert lib.cft_save_all_flags(dev) == saved, (
        "restoreFlags over the whole set must be a round trip")
    note()

    # restoreFlags LOWERS as well as raises inside the mask, and leaves
    # everything outside it alone
    fresh(lib, dev)
    lib.cft_raise_flags(dev, FLAGS_ALL)
    lib.cft_restore_flags(dev, 0, FLAG_INEXACT)
    assert lib.cft_save_all_flags(dev) == (FLAGS_ALL & ~FLAG_INEXACT)
    lib.cft_restore_flags(dev, FLAG_INEXACT | FLAG_INVALID, FLAG_INEXACT)
    assert lib.cft_save_all_flags(dev) == FLAGS_ALL
    lib.cft_lower_flags(dev, FLAGS_ALL)
    lib.cft_restore_flags(dev, FLAGS_ALL, FLAG_DIVBYZERO)
    assert lib.cft_save_all_flags(dev) == FLAG_DIVBYZERO
    note(3)

    # testSavedFlags asks the same question of a value the caller holds
    assert lib.cft_test_saved_flags(FLAG_INVALID | FLAG_INEXACT,
                                    FLAG_INEXACT) == 1
    assert lib.cft_test_saved_flags(FLAG_INVALID, FLAG_INEXACT) == 0
    assert lib.cft_test_saved_flags(0, FLAGS_ALL) == 0
    assert lib.cft_test_saved_flags(FLAGS_ALL, FLAGS_ALL) == 1
    note(4)

    # a NULL device is a word that is permanently zero
    assert lib.cft_save_all_flags(None) == 0
    assert lib.cft_test_flags(None, FLAGS_ALL) == 0
    lib.cft_raise_flags(None, FLAGS_ALL)      # must not crash
    lib.cft_lower_flags(None, FLAGS_ALL)
    lib.cft_restore_flags(None, FLAGS_ALL, FLAGS_ALL)
    assert lib.cft_save_all_flags(None) == 0
    note(4)

    fresh(lib, dev)


def check_predicates(lib):
    """5.7.1: "true if and only if this programming environment
    conforms to" the named version. See cft.h for what each answer
    rests on."""
    assert lib.cft_is754version1985() == 0
    assert lib.cft_is754version2008() == 0
    assert lib.cft_is754version2019() == 1
    note(3)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--formats", default="fp32,fp64,fp128,fp256")
    ap.add_argument("--trials", type=int, default=48)
    args = ap.parse_args()
    formats = [s.strip() for s in args.formats.split(",") if s.strip()]

    lib = load_library()
    bind(lib)
    dev = open_dev(lib)
    try:
        check_predicates(lib)
        print("  5.7.1: is754version1985/2008/2019 = 0/0/1")
        check_status_word(lib, dev)
        print(f"  7.1 + 5.7.4: the status word accumulates, lowers only "
              f"on request, and round-trips ({CHECKED} checks so far)")
        for name in formats:
            fmt = FORMATS[name]
            t = args.trials if fmt.width <= 64 else max(4, args.trials // 4)
            # the status word is device-wide; keep it out of the way of
            # the per-call flag comparisons below
            lib.cft_lower_flags(dev, FLAGS_ALL)
            check_scalar(lib, dev, fmt, t)
            check_equal_magnitude_family(lib, dev, fmt)
            check_batch(lib, dev, fmt, t)
            check_aliasing_and_arguments(lib, dev, fmt)
            print(f"  {name}: 9.6's four magnitude forms agree with the "
                  f"model ({CHECKED} comparisons so far)")
    finally:
        lib.cft_close(dev)
    print(f"minmax_mag_check: {CHECKED} comparisons, C == model on every "
          f"one")


if __name__ == "__main__":
    main()
