# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""The drop-in demo: one workload, gmpy2 and cftmpfr, identical bits.

    python demo_mpfr_dropin.py [N]        (default 100000 elements)

The workload is the kind of thing MPFR-at-IEEE-precision is actually
used for: evaluate a degree-8 polynomial by Horner's rule (8 fused
multiply-adds), take the square root, divide - 100k elements at
binary256, every operation correctly rounded with IEEE flags. It runs
twice:

  (a) the way it is written today: a Python loop over gmpy2.mpfr in
      gmpy2.ieee(256) - MPFR's own IEEE emulation recipe;
  (b) cftmpfr.batch - the same arithmetic as whole-array libcft calls.

Then every element of every phase is compared BIT FOR BIT. That
comparison is the demo: not "close", identical - 300,000 encodings
with zero daylight, or a mismatch count and the first offenders.

The timing table reports each phase honestly, because the phases tell
different stories on the software backend: fma crosses the interpreter
once instead of N times and wins; div and sqrt are libcft's fixed
seed/Newton/residual sequence - 25-30 elementwise passes each, the
price of correct rounding built from an FMA - and a portable-C
softfloat pays that price at softfloat speed while MPFR's native
division does not. The tile pays it at hardware speed; the calls in
(b) are already the calls that drive it (Context(..., artifact=
"tile.xclbin")). Where (b) is slower today, the honest number is
printed, not reframed.

Without gmpy2 the demo still runs (b) - after offering to pip install
gmpy2 - and says exactly what it could not verify.
"""

import random
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from cftmpfr import Context, batch

N_DEFAULT = 100_000
COEFFS = (3, 1, 4, 1, 5, 9, 2, 6, 5)   # c0..c8, all positive: P(x) > 0
SEED = 0x5EEDF00D


def ensure_gmpy2():
    """Import gmpy2, offering one pip install into this interpreter if
    it is missing. Failure degrades rather than aborts: the batch side
    and its timings still mean something without the oracle."""
    try:
        import gmpy2
        return gmpy2
    except ImportError:
        pass
    print("gmpy2 not installed; trying: "
          f"{sys.executable} -m pip install gmpy2")
    r = subprocess.run([sys.executable, "-m", "pip", "install", "gmpy2"],
                       capture_output=True, text=True)
    if r.returncode != 0:
        tail = (r.stderr or r.stdout).strip().splitlines()[-1:]
        print(f"pip install failed ({' '.join(tail) or 'no output'})")
        return None
    try:
        import gmpy2
        print(f"installed gmpy2 {gmpy2.version()}")
        return gmpy2
    except ImportError:
        print("pip reported success but gmpy2 still does not import")
        return None


def make_inputs(ctx, n):
    """n deterministic binary256 values in [0.5, 2): full 236-bit
    random significands, so nothing about the comparison is easy."""
    rng = random.Random(SEED)
    xs = []
    for _ in range(n):
        man = rng.getrandbits(236)
        e = 262143 - 1 + rng.getrandbits(1)          # exponent of 0.5 or 1.x
        xs.append((e << 236) | man)
    return [ctx.from_bits(b) for b in xs]


def fnv1a(data):
    h = 0xCBF29CE484222325
    for byte in data:
        h = ((h ^ byte) * 0x100000001B3) & 0xFFFFFFFFFFFFFFFF
    return h


def run_gmpy2(gmpy2, mx, coeffs):
    """The workload as it is idiomatically written today: gmpy2 ops in
    an ieee(256) context, one Python iteration per element."""
    save = gmpy2.get_context()
    gmpy2.set_context(gmpy2.ieee(256))
    try:
        fma, gsqrt, gdiv = gmpy2.fma, gmpy2.sqrt, gmpy2.div
        cs = [gmpy2.mpfr(c) for c in coeffs]

        t0 = time.perf_counter()
        ps = []
        top = cs[-1]
        rest = cs[-2::-1]
        for x in mx:
            p = top
            for c in rest:
                p = fma(p, x, c)
            ps.append(p)
        t1 = time.perf_counter()
        ys = [gsqrt(p) for p in ps]
        t2 = time.perf_counter()
        rs = [gdiv(x, y) for x, y in zip(mx, ys)]
        t3 = time.perf_counter()
    finally:
        gmpy2.set_context(save)
    return (ps, ys, rs), (t1 - t0, t2 - t1, t3 - t2)


def run_cftmpfr(ctx, xs_packed, n, coeffs):
    """The same workload as whole-array calls: 8 fma passes, one sqrt,
    one div - ten interpreter crossings for 100k elements."""
    esz = 32
    cs = [ctx.from_int(c) for c in coeffs]

    t0 = time.perf_counter()
    p = cs[-1].to_bytes() * n                        # Horner seed, broadcast
    for c in cs[-2::-1]:
        p, _ = batch.fma(ctx, p, xs_packed, c)
    flags = ctx.flags
    t1 = time.perf_counter()
    y, fl_sqrt = batch.sqrt(ctx, p)
    t2 = time.perf_counter()
    r, fl_div = batch.div(ctx, xs_packed, y)
    t3 = time.perf_counter()
    assert len(p) == len(y) == len(r) == n * esz
    return (p, y, r), (t1 - t0, t2 - t1, t3 - t2), flags | fl_sqrt | fl_div


def verify(ctx, gmpy_phases, cft_phases, n):
    """Element-by-element bit identity, every phase. The gmpy2 result
    is converted to its interchange encoding through the package's
    exact from_mpfr (integer significand, never a decimal), and the
    bytes are compared. Returns (elements compared, mismatches)."""
    esz = 32
    names = ("horner", "sqrt", "div")
    compared = bad = 0
    for name, want_list, got_bytes in zip(names, gmpy_phases, cft_phases):
        for i, want in enumerate(want_list):
            wenc = ctx.from_mpfr(want).to_bytes()
            genc = got_bytes[i * esz:(i + 1) * esz]
            compared += 1
            if wenc != genc:
                bad += 1
                if bad <= 5:
                    print(f"  MISMATCH {name}[{i}]:")
                    print(f"    gmpy2  0x{wenc[::-1].hex()}")
                    print(f"    cftmpfr 0x{genc[::-1].hex()}")
    return compared, bad


def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else N_DEFAULT
    gmpy2 = ensure_gmpy2()

    ctx = Context(237)   # binary256, roundTiesToEven
    print(f"cftmpfr drop-in demo: binary256, n={n}, backend={ctx.backend}")
    print(f"workload: degree-8 Horner (8 fma) + sqrt + div per element\n")

    xs = make_inputs(ctx, n)
    xs_packed = b"".join(f.to_bytes() for f in xs)

    cft_phases, cft_times, cft_flags = run_cftmpfr(ctx, xs_packed, n, COEFFS)
    print(f"cftmpfr flags across the run: 0x{cft_flags:02x} "
          f"{ctx.flag_names(cft_flags)}")

    if gmpy2 is None:
        total = sum(cft_times)
        print("\nphase      cftmpfr")
        for name, t in zip(("horner", "sqrt", "div"), cft_times):
            print(f"{name:<9} {t:8.3f} s   {t / n * 1e9:9.0f} ns/elem")
        print(f"{'total':<9} {total:8.3f} s")
        print(f"\nresult checksum (fnv1a of div phase): "
              f"0x{fnv1a(cft_phases[2]):016x}")
        print("\nNOT VERIFIED: gmpy2 is unavailable, so bit-identity "
              "against MPFR's IEEE emulation could not be checked here. "
              "The claim itself rests on host/tools/mpfr_check.c "
              "(999,000 cases, zero disagreements); install gmpy2 and "
              "rerun to see it hold on this workload.")
        return 0

    mx = [f.to_mpfr() for f in xs]
    gmpy_phases, gmpy_times = run_gmpy2(gmpy2, mx, COEFFS)

    print("\nverifying bit identity, element by element, every phase...")
    t0 = time.perf_counter()
    compared, bad = verify(ctx, gmpy_phases, cft_phases, n)
    tv = time.perf_counter() - t0
    if bad:
        print(f"PARITY FAILED: {bad} of {compared} encodings differ")
    else:
        print(f"parity: {compared} of {compared} encodings identical, "
              f"bit for bit ({tv:.1f} s to check)")

    print(f"\nphase        gmpy2 loop        cftmpfr batch      speedup")
    for name, tg, tc in zip(("horner", "sqrt", "div"), gmpy_times,
                            cft_times):
        print(f"{name:<9} {tg:8.3f} s {tg / n * 1e9:7.0f} ns"
              f" | {tc:8.3f} s {tc / n * 1e9:7.0f} ns"
              f" | {tg / tc:5.2f}x")
    tg, tc = sum(gmpy_times), sum(cft_times)
    print(f"{'total':<9} {tg:8.3f} s {tg / n * 1e9:7.0f} ns"
          f" | {tc:8.3f} s {tc / n * 1e9:7.0f} ns"
          f" | {tg / tc:5.2f}x")

    print(
        "\nReading the table honestly: the fma phase is the batch story -\n"
        "one interpreter crossing instead of n, same bits. div and sqrt\n"
        "are libcft's fixed seed/Newton/residual sequence (25-30\n"
        "elementwise passes each; the price of correct rounding built\n"
        "from an FMA), and on the software backend those passes run at\n"
        "portable-softfloat speed, so MPFR's native divide wins there\n"
        "today. The identical calls drive the FPGA tile - pass an\n"
        "artifact path to Context - where the passes run at hardware\n"
        "speed and the bits, by contract and by construction, do not\n"
        "change.")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
