# M4 model: values live once scheduled (scratch; the study's 5.3). Each
# fragment's body in mathlib's depth-first topological order (the order
# M1's build gives its fragments when it keeps fewer live: mathlib.
# schedule_order's second candidate), the live count before and after,
# and the invariants of the scheduled fragment with no cap.
#
#   python sched.py

from m4core import FORMATS, sf, ATTRS, RNE
from m4inv import build, FNS
from cft_golden import mathlib


def main():
    for name in ("fp32", "fp64", "fp128", "fp256"):
        fmt = FORMATS[name]
        for fn in FNS:
            lives = []
            for rnd in ATTRS:
                f = build(fmt, rnd, fn)
                frag = f.to_fragment()
                s = mathlib.permuted(frag, mathlib._dfs_order(frag))
                inv = mathlib.invariants(s, live_cap=None)
                lives.append((f.live_max(), s.live_max(), "hold" if not inv else inv))
            d = sorted({a for a, _b, _c in lives})
            sc = sorted({b for _a, b, _c in lives})
            iv = sorted({str(c) for _a, _b, c in lives})
            print(f"{name}{'-dw18' if name == 'fp32' else ''} {fn}: live {d} in the "
                  f"design's order, {sc} scheduled, over the five attributes; "
                  f"invariants (scheduled) {iv}", flush=True)


if __name__ == "__main__":
    main()
