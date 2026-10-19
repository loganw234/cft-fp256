# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""tile_counts.py - what the tile items cost in passes and in program instructions, and what an
instruction-issue bound would give against the stress run's measured rates (section 6.2 of the study).

python/cft_golden is imported read-only and nothing here touches a device. The counts are of the GOLDEN
model's sequences (the routes python/cft_golden/sequences.py and divfull.py specify and that
host/src/clause5.c and divsqrt.c issue), so they are the routes' own step counts, not a measurement of
the card.

  T1  the whole-divide and whole-square-root PROGRAMS: len(Program.insns) at fp32 and fp64
  T2  the ELEMENTWISE routes, in passes (one compute() call is one cft_run pass): div, sqrt, rint (a mean over random
      operands of the general path, for both variants the soak runs) and scaleb (one count per exponent of the
      soak tool's own directed list, parsed from host/tools/clause5_soak.c)
  T3  the issue-bound model of 6.2: one instruction a beat, 8 fp32 or 4 fp64 lanes a beat, 108 M beats a second a tile;
      a tile then does lanes x beats / instructions cases a second. The measured per-job quad rates are held to it:
      no measured rate may exceed the bound (a model the data exceeds is wrong), and the fractions are printed.

CHECKS have controls: the funnel count must equal the count through the module's own step function, the bound
must be above every measured rate, a bound with the wrong lane count must be caught, and the documents the two
constants are READ from must still say them.
usage: python tile_counts.py      (reads stress-final-item-rates.txt beside it)
"""
import os
import random
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "python"))

from cft_golden import FP32, FP64  # noqa: E402
from cft_golden import divfull, sequences as S  # noqa: E402
from cft_golden import softfloat as sf  # noqa: E402

LANES = {"fp32": 8, "fp64": 4}      # READ: docs/ARCHITECTURE.md, cft_lanes: "eight fp32 / four fp64 / two fp128 lanes"
BEATS = 108e6                       # READ: docs/VALIDATION.md, 2026-09-08 card day: "108 M beats/s at 135 MHz and 1.25 cycles a beat"
RATES = os.path.join(HERE, "stress-final-item-rates.txt")
SOAK = os.path.join(ROOT, "host", "tools", "clause5_soak.c")
fails = 0


def check(label, ok, detail=""):
    global fails
    print("CHECK %-96s %s %s" % (label, "ok" if ok else "FAILED", detail))
    if not ok:
        fails += 1


def squash(path):
    with open(path, encoding="utf-8") as fh:
        return re.sub(r"\s+", " ", fh.read())


class Counter:
    """Counts every compute() call (the one exit of the module's step function) and every call of the step function."""

    def __init__(self):
        self.n_compute = 0
        self.n_op = 0
        self._compute, self._op = S.compute, S._op

        def compute(*a, **k):
            self.n_compute += 1
            return self._compute(*a, **k)

        def op(*a, **k):
            self.n_op += 1
            return self._op(*a, **k)
        S.compute, S._op = compute, op

    def reset(self):
        self.n_compute = self.n_op = 0

    def close(self):
        S.compute, S._op = self._compute, self._op


def directed_list(name):
    """The soak tool's own list of directed scalbn exponents, parsed from its source."""
    with open(SOAK, encoding="utf-8") as fh:
        text = fh.read()
    m = re.search(r"static const int64_t %s\[\] = \{(.*?)\};" % name, text, re.S)
    return [int(x) for x in re.findall(r"-?\d+", m.group(1))]


def read_rates():
    out = {}
    with open(RATES, encoding="utf-8") as fh:
        hdr = fh.readline().split()
        for line in fh:
            f = line.split()
            if len(f) == len(hdr):
                d = dict(zip(hdr, f))
                out[(d["item"], d["image"])] = d
    return out


def main():
    try:
        sys.stdout.reconfigure(newline="\n")
    except (AttributeError, ValueError):
        pass
    print("tile_counts.py: passes and program instructions of the tile items, and the issue-bound model of 6.2")
    print()
    # the two READ constants must still be what the documents say
    arch = squash(os.path.join(ROOT, "docs", "ARCHITECTURE.md"))
    val = squash(os.path.join(ROOT, "docs", "VALIDATION.md"))
    check("docs/ARCHITECTURE.md still says the tile's lanes are eight fp32 / four fp64 / two fp128",
          "eight fp32 / four fp64 / two fp128 lanes" in arch)
    check("docs/VALIDATION.md still says the tile's own rate is 108 M beats/s at 135 MHz and 1.25 cycles a beat",
          "108 M beats/s at 135 MHz and 1.25 cycles a beat" in val)
    print()

    print("== T1. the whole-divide and whole-square-root programs (len(Program.insns))")
    insns = {}
    for fname, fmt in (("fp32", FP32), ("fp64", FP64)):
        d = len(divfull.div_full_program_for(fmt).insns)
        s = len(divfull.sqrt_full_program_for(fmt).insns)
        insns[fname] = (d, s)
        print("   %s: div_full %d instructions, sqrt_full %d" % (fname, d, s))
    print()

    print("== T2. the elementwise routes, in passes (compute() calls) - what a composed item issues a call")
    cnt = Counter()
    try:
        rng = random.Random(3)
        passes = {}
        for fname, fmt in (("fp32", FP32), ("fp64", FP64)):
            one = (fmt.bias << fmt.man_w)
            cnt.reset()
            S.div_seq(fmt, one | 12345, one | 54321, sf.RND_RNE)
            passes[(fname, "div")] = cnt.n_compute
            same_div = cnt.n_compute == cnt.n_op
            cnt.reset()
            S.sqrt_seq(fmt, one | 12345, sf.RND_RNE)
            passes[(fname, "sqrt")] = cnt.n_compute
            same_sqrt = cnt.n_compute == cnt.n_op
            print("   %s div_seq %d passes, sqrt_seq %d passes (one operand pair)" % (fname, passes[(fname, "div")], passes[(fname, "sqrt")]))
            for exact in (False, True):
                tot = k = 0
                lo = hi = None
                for _ in range(200):
                    x = ((fmt.bias + rng.randrange(-3, fmt.man_w - 2)) << fmt.man_w) | rng.getrandbits(fmt.man_w)
                    cnt.reset()
                    S.rint_seq(fmt, x, sf.RND_RNE, exact)
                    tot += cnt.n_compute
                    k += 1
                    lo = cnt.n_compute if lo is None else min(lo, cnt.n_compute)
                    hi = cnt.n_compute if hi is None else max(hi, cnt.n_compute)
                    same_div = same_div and cnt.n_compute == cnt.n_op
                passes[(fname, "rint", exact)] = tot / k
                print("   %s rint_seq exact=%-5s: %.2f passes a call on average (min %d, max %d, over 200 operands with a fraction)"
                      % (fname, exact, tot / k, lo, hi))
            lst = directed_list("SCALEB_N32" if fname == "fp32" else "SCALEB_N64")
            per = []
            for n in lst:
                cnt.reset()
                S.scaleb_seq(fmt, one | 5, n, sf.RND_RNE)
                per.append(cnt.n_compute)
                same_div = same_div and cnt.n_compute == cnt.n_op
            passes[(fname, "scaleb")] = per
            print("   %s scaleb_seq over the tool's %d directed exponents: %d passes in all; passes by exponent: %s"
                  % (fname, len(lst), sum(per), " ".join("%d:%d" % (n, p) for n, p in zip(lst, per))))
            check("%s: every pass is counted once whether counted at the step function or at compute()" % fname,
                  same_div and same_sqrt)
    finally:
        cnt.close()
    print()

    print("== T3. the issue-bound model against the measured per-job quad rates (M cases a second a tile)")
    print("   bound = lanes x %.0f M beats / instructions, one instruction a beat; the measured rate is the card run's median per job" % (BEATS / 1e6))
    rates = read_rates()
    rows = []
    for fam, fname, key, col in (("div32", "fp32", 0, "median_count_rate"), ("div64", "fp64", 0, "median_count_rate"),
                                 ("sqrt32", "fp32", 1, "median_cases_rate"), ("sqrt64", "fp64", 1, "median_count_rate")):
        bound = LANES[fname] * BEATS / insns[fname][key]
        meas = {m: float(rates[("%s-%s" % (fam, m), "quad")][col]) for m in ("rne", "rtz", "rdn", "rup")}
        best = max(meas.values())
        rows.append((fam, bound, meas["rne"], best))
        print("   %-7s bound %5.2f   measured rne %5.3f (%.0f%% of the bound), best of four attributes %5.3f (%.0f%%)"
              % (fam, bound / 1e6, meas["rne"] / 1e6, 100.0 * meas["rne"] / bound, best / 1e6, 100.0 * best / bound))
    check("no measured rate exceeds the issue bound (a model the data exceeds is wrong)", all(r[3] < r[1] for r in rows))
    # the same predicate on a model with a quarter of the documented beat rate: it must fail, or the check above cannot
    check("CONTROL: a bound at a quarter of the documented beat rate lies below the measured rates (the check above can fail)",
          not all(r[3] < r[1] / 4.0 for r in rows))
    print()

    print("== T4. does a tile slow down when four run at once? the quad's per-job median against the single image's, same item")
    print("   (rows with at least 3 slices on both images; the single ran one job at a time, the quad four; M/s a tile)")
    print("   %-14s %8s %8s %8s %8s" % ("item", "slices", "quad", "single", "quad/single"))
    ratios = []
    for fam in ("div32", "div64", "sqrt32", "sqrt64", "rint32", "rint64", "scaleb32", "scaleb64"):
        col = "median_cases_rate" if fam in ("sqrt32", "rint32") else "median_count_rate"
        for mode in ("rne", "rtz", "rdn", "rup", "rmm"):
            q, s = rates.get(("%s-%s" % (fam, mode), "quad")), rates.get(("%s-%s" % (fam, mode), "single"))
            if q is None or s is None or int(q["slices"]) < 3 or int(s["slices"]) < 3:
                continue
            r = float(q[col]) / float(s[col])
            ratios.append((r, "%s-%s" % (fam, mode)))
            print("   %-14s %3s/%-3s %8.3f %8.3f %8.3f" % ("%s-%s" % (fam, mode), q["slices"], s["slices"], float(q[col]) / 1e6, float(s[col]) / 1e6, r))
    lo, hi = min(ratios), max(ratios)
    print("   quad/single over %d items: %.2f (%s) to %.2f (%s)" % (len(ratios), lo[0], lo[1], hi[0], hi[1]))
    check("T4 saw rows to compare (the filter does not leave an empty table)", len(ratios) >= 8, "(%d rows)" % len(ratios))
    print()

    print("== T5. the composed items (rint, scaleb): the tile's share of a job, a pass's cost, and the staged traffic (quad, rne)")
    print("   a job is a batch of 4,096 operands; passes an operand: rint 2 calls x 4 (T2), scaleb the passes over the directed list (T2);")
    print("   tile time = beats / 108 M a second at lanes a beat; traffic of the four tiles = passes x words an element x element bytes, with 3 words (two read, one")
    print("   written: the lower figure, BELIEVED) or 4 (READ in cftx_run_impl, host/src/backend_xrt.cpp: it stages a, b and c for every run, a null operand zero-filled and uploaded, and a pass")
    print("   writes d. docs/VALIDATION.md 2026-09-18, 'the reductions' missing rate', quotes the engine's reason, 'one read enable feeds all three FIFOs', in an entry about the REDUCTIONS: for rint")
    print("   and scaleb the four words rest on the reading of cftx_run_impl), against the 2.3 to 3.3 GB/s of staged traffic that docs/VALIDATION.md 2026-09-08 measured whatever the format and the tile count")
    print("   %-9s %9s %9s %8s %10s %10s %9s %10s %10s %14s" % ("item", "M op/s", "passes/op", "job ms", "us/pass", "tile us", "tile %", "GB/s (3)", "GB/s (4)", "of the wall (4)"))
    composed = []
    for fam, fname, word in (("rint32", "fp32", 4), ("rint64", "fp64", 8), ("scaleb32", "fp32", 4), ("scaleb64", "fp64", 8)):
        if fam.startswith("rint"):
            col = "median_cases_rate" if fam == "rint32" else "median_count_rate"
            ops = float(rates[("%s-rne" % fam, "quad")][col])
            ppo = 2 * passes[(fname, "rint", False)]
        else:
            lst = directed_list("SCALEB_N32" if fam == "scaleb32" else "SCALEB_N64")
            ops = float(rates[("%s-rne" % fam, "quad")]["median_count_rate"]) / len(lst)      # count is checks
            ppo = float(sum(passes[(fname, "scaleb")]))
        job = 4096.0 / ops
        tile = ppo * (4096.0 / LANES[fname]) / BEATS
        bound = LANES[fname] * BEATS / ppo
        gbs3 = 4 * ops * ppo * 3 * word / 1e9
        gbs4 = 4 * ops * ppo * 4 * word / 1e9
        composed.append((fam, ops, bound))
        print("   %-9s %9.3f %9.1f %8.3f %10.1f %10.1f %8.1f%% %10.2f %10.2f %9.0f%% to %.0f%%" % (
            fam, ops / 1e6, ppo, job * 1e3, job / ppo * 1e6, tile / ppo * 1e6, 100.0 * tile / job, gbs3, gbs4, 100.0 * gbs4 / 3.3, 100.0 * gbs4 / 2.3))
    # the four words: the source must still stage a, b and c on every run, unless resident (a tie of the claim to the text it was READ in)
    with open(os.path.join(ROOT, "host", "src", "backend_xrt.cpp"), encoding="utf-8") as fh:
        be = fh.read()
    body = be[be.index("static int cftx_run_impl("):]
    body = body[:body.index("t.start = ")]
    pat = r"for \(int r = 0; r < %s; r\+\+\) \{\s*if \(sb\[i\]\.bo\[r\]\)\s*continue;.*?stage\(\*tb\[r\],"
    check("cftx_run_impl stages every operand role below D (a, b, c) on every run unless it is resident: the four words an element",
          re.search(pat % "CFT_ROLE_D", body, re.S) is not None)
    check("CONTROL: the same search for a staging loop over TWO roles finds nothing in the source (the check above can fail)",
          re.search(pat % "2", body, re.S) is None)
    check("no measured composed rate exceeds its beat bound (lanes x beats / passes an operand)", all(o < b for _f, o, b in composed))
    # these items run at 2 to 4% of the bound, so only a much smaller beat rate can put the bound under them
    check("CONTROL: with a hundredth of the documented beat rate the bound falls below a measured rate (the check above can fail)",
          not all(o < b / 100.0 for _f, o, b in composed))
    print()
    print("tile_counts: %s" % ("every CHECK held" if fails == 0 else "%d CHECK(s) FAILED" % fails))
    return 0 if fails == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
