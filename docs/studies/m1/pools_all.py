import time, sys
from m1core import sf
from m1exp import build_exp
from m1log import build_log
from m1harness import pools, compare, FORMATS
fmts = sys.argv[1].split(",")
out = {}
t0 = time.perf_counter()
for fmtname in fmts:
    fmt = FORMATS[fmtname]
    xs = pools(fmt)
    for fn in ("exp", "exp2", "expm1", "log", "log2", "log1p"):
        for rnd in sf.RND_MODES:
            f = build_exp(fmt, rnd, fn) if fn.startswith("exp") else build_log(fmt, rnd, fn)
            st = compare(f, fn, xs, rnd)
            row = dict(fmt=fmtname, fn=fn, rnd=sf.RND_NAMES[rnd], n=st["n"], marked=st["marked"], right=st["marked_right"], wrong=len(st["wrong"]), marks=st["marks"], insns=len(f.body), words=len(f.words), live=f.live_max(), K=f.meta["K"], D=f.meta["D"], phases=f.by_phase(), counts=f.counts())
            out[f"{fmtname}/{fn}/{sf.RND_NAMES[rnd]}"] = row
            print(f"{fmtname} {fn:5s} {sf.RND_NAMES[rnd]} n {st['n']} marked {st['marked']} (right {st['marked_right']}) wrong {len(st['wrong'])} insns {len(f.body)} words {len(f.words)} live {f.live_max()} {st['marks'][:3]} {st['wrong'][:2]}", flush=True)
print(f"{time.perf_counter()-t0:.0f}s")
