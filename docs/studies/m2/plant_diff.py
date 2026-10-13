# M2 model: which fragments a plant changes (scratch; the study's section
# 8). For each plant, sin's, cos's and tan's fragments under rne at FMT
# against the unplanted ones: the body's length, and whether the body,
# words, result or flag word differ.
#
#   python plant_diff.py [FMT]

import sys

from m2core import FORMATS, RNE
from m2trig import build, PLANTS


def main():
    fmt = FORMATS[sys.argv[1] if len(sys.argv) > 1 else "fp64"]
    for fn in ("sin", "cos", "tan"):
        base = build(fmt, RNE, fn)
        key0 = repr((base.body, sorted(base.words.items()), base.result,
                     base.flags))
        for pl in PLANTS:
            f = build(fmt, RNE, fn, plant=pl)
            key = repr((f.body, sorted(f.words.items()), f.result, f.flags))
            print(fn, pl, len(f.body),
                  "same as the control" if key == key0 else "differs",
                  flush=True)


if __name__ == "__main__":
    main()
