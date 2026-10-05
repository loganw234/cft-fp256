# The model's fragments run as stand-alone programs on seq.py (C4's own
# harness, routines.program / routines.run: a naive allocation, two
# deposits a lane), against the model's evaluator and transcend.py.
import time
from m1core import sf, evaluate
from m1exp import build_exp
from m1log import build_log
from m1harness import pools, FORMATS, tr
from cft_golden import routines, seq
t0 = time.perf_counter()
tot = 0
for fmtname in ("fp64", "fp256"):
    fmt = FORMATS[fmtname]
    xs = pools(fmt)
    for fn in ("exp", "exp2", "expm1", "log", "log2", "log1p"):
        for rnd in (sf.RND_RNE, sf.RND_RTZ, sf.RND_RUP):
            f = build_exp(fmt, rnd, fn) if fn.startswith("exp") else build_log(fmt, rnd, fn)
            frag = f.to_fragment()
            prog, bank = routines.program(frag)
            outs, words = routines.run(frag, xs)
            bad = 0
            for xa, o, wd in zip(xs, outs, words):
                b, fw, _ = evaluate(f, xa)
                if (o, wd) != (b, fw):
                    bad += 1
                gb, gf = tr.compute(fmt, fn, xa, 0, rnd)
                if not (wd & 0x80) and (o, wd) != (gb, gf):
                    bad += 1000
            tot += len(xs)
            print(f"{fmtname} {fn:5s} {sf.RND_NAMES[rnd]}: seq.py program {len(prog.insns)} insns (incl. 2 deposits + halt), bank {len(bank)}, lanes {len(xs)}, mismatches {bad}", flush=True)
print(f"{tot} lanes, {time.perf_counter()-t0:.0f}s")
