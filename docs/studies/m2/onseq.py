# M2 model: the fragments as programs on seq.py (scratch; the study's 8,
# item 1). Each fragment through routines.program (its inputs in r0, its
# values given registers by first free, its words a BANK_EXT bank, two
# deposits a lane) and routines.run, lane for lane against the model's
# evaluator and against transcend.py: bits and flag word, or marked.
#
#   python onseq.py FMT [FNS] [ATTRS] [limit]

import sys
import time

from m2core import FORMATS, sf, evaluate, ATTRS   # puts python/ on the path
from cft_golden import routines
from m2harness import pools, tr
from m2trig import build


def main():
    name = sys.argv[1]
    fns = sys.argv[2].split(",") if len(sys.argv) > 2 else ["sin", "cos", "tan"]
    rnds = ([int(c) for c in sys.argv[3].split(",")] if len(sys.argv) > 3
            else list(ATTRS))
    limit = int(sys.argv[4]) if len(sys.argv) > 4 else 0
    fmt = FORMATS[name]
    xs = pools(fmt)
    if limit:
        xs = xs[::max(1, len(xs) // limit)]
    t0 = time.perf_counter()
    for fn in fns:
        for rnd in rnds:
            f = build(fmt, rnd, fn)
            frag = f.to_fragment()
            outs, words = routines.run(frag, xs)
            diff_model = mism = marked = 0
            for xa, ob, ow in zip(xs, outs, words):
                mb, mw, _ = evaluate(f, xa)
                if (ob, ow) != (mb, mw):
                    diff_model += 1
                gb, gf = tr.compute(fmt, fn, xa, 0, rnd)
                if ow & 0x80:
                    marked += 1
                elif (ob, ow) != (gb, gf):
                    mism += 1
            print(f"{name} {fn} {sf.RND_NAMES[rnd]}: {len(xs)} lanes on seq.py, "
                  f"{len(f.body)} instructions, live {f.live_max()}: differ "
                  f"from the model {diff_model}, from transcend.py (unmarked) "
                  f"{mism}, marked {marked}; {time.perf_counter() - t0:.0f}s",
                  flush=True)


if __name__ == "__main__":
    main()
