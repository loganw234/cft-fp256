# M4 model: the fragments as programs on seq.py (scratch; the study's 8,
# item 1). Each fragment through routines.program (its inputs in r0 and,
# for atan2, r1 - y then x; its values given registers by first free; its
# words a BANK_EXT bank; two deposits a lane) and routines.run, lane for
# lane against the model's evaluator and against transcend.py: bits and
# flag word, or marked.
#
#   python onseq.py FMT [FNS] [ATTRS]

import sys
import time

from m4core import FORMATS, sf, evaluate2, ATTRS      # puts python/ on the path
from cft_golden import routines
from m4harness import pool, golden
from m4inv import build, FNS


def main():
    name = sys.argv[1]
    fns = sys.argv[2].split(",") if len(sys.argv) > 2 else list(FNS)
    rnds = ([int(c) for c in sys.argv[3].split(",")] if len(sys.argv) > 3
            else list(ATTRS))
    fmt = FORMATS[name]
    t0 = time.perf_counter()
    for fn in fns:
        xs = pool(fmt, fn)
        for rnd in rnds:
            f = build(fmt, rnd, fn)
            frag = f.to_fragment()
            if fn == "atan2":
                outs, words = routines.run(frag, [a for a, _b in xs],
                                           [b for _a, b in xs])
            else:
                outs, words = routines.run(frag, xs)
            diff_model = mism = marked = 0
            for xa, ob, ow in zip(xs, outs, words):
                mb, mw, _ = evaluate2(f, xa)
                if (ob, ow) != (mb, mw):
                    diff_model += 1
                gb, gf = golden(fmt, fn, xa, rnd)
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
