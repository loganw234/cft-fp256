# M4 model: what mathlib.schedule_order would give these fragments once M4's
# phase names are in PHASE_ORDER (scratch; the study's question 9, after
# send-back 1's note). mathlib ranks by PHASE_ORDER, which holds M1's
# names and none of this model's (front, sqrt, index, num, den, quotient,
# z, atan_s, table), so its ranked candidate cannot run on them as they
# stand and its depth-first one decides. This script runs mathlib's own
# ranked order (_ranked_order) with PHASE_ORDER extended by the model's
# names in the design's order, beside the depth-first order and the
# design's own, and prints each live count and schedule_order's choice.
#
#   python phaseorder.py

from m4core import FORMATS, ATTRS
from m4inv import build, FNS
from cft_golden import mathlib

M4_PHASES = ("front", "sqrt", "index", "num", "den", "quotient", "z", "tail",
             "head", "atan_s", "table", "recon", "final", "classify", "special")


def main():
    saved = mathlib.PHASE_ORDER
    try:
        mathlib.PHASE_ORDER = M4_PHASES + tuple(p for p in saved if p not in M4_PHASES)
        for name in ("fp32", "fp64", "fp128", "fp256"):
            fmt = FORMATS[name]
            for fn in FNS:
                rows = set()
                for rnd in ATTRS:
                    f = build(fmt, rnd, fn)
                    frag = f.to_fragment()
                    ranked = mathlib.permuted(frag, mathlib._ranked_order(frag, f.phase_of))
                    dfs = mathlib.permuted(frag, mathlib._dfs_order(frag))
                    chosen = mathlib.permuted(frag, mathlib.schedule_order(frag, f.phase_of))
                    rows.add((f.live_max(), ranked.live_max(), dfs.live_max(),
                              chosen.live_max()))
                for d, r, s, c in sorted(rows):
                    print(f"{name}{'-dw18' if name == 'fp32' else ''} {fn}: live "
                          f"{d} in the design's order, {r} by mathlib's ranked "
                          f"order with M4's phases added, {s} depth-first; "
                          f"schedule_order then takes {c}", flush=True)
    finally:
        mathlib.PHASE_ORDER = saved


if __name__ == "__main__":
    main()
