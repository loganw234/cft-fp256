# The pools against transcend.py, one format and a list of functions, with
# a deadline: no configuration starts after `deadline` seconds.
import time, sys
from m1core import sf
from m1exp import build_exp
from m1log import build_log
from m1harness import pools, compare, FORMATS
fmtname = sys.argv[1]
fns = sys.argv[2].split(",")
deadline = float(sys.argv[3]) if len(sys.argv) > 3 else 540
rnds = [int(c) for c in sys.argv[4].split(",")] if len(sys.argv) > 4 else list(sf.RND_MODES)
fmt = FORMATS[fmtname]
xs = pools(fmt)
t0 = time.perf_counter()
out, skipped = {}, []
for fn in fns:
    for rnd in rnds:
        if time.perf_counter() - t0 > deadline:
            skipped.append(f"{fn}/{sf.RND_NAMES[rnd]}")
            continue
        f = build_exp(fmt, rnd, fn) if fn.startswith("exp") else build_log(fmt, rnd, fn)
        st = compare(f, fn, xs, rnd)
        out[f"{fmtname}/{fn}/{sf.RND_NAMES[rnd]}"] = dict(n=st["n"], marked=st["marked"], right=st["marked_right"], wrong=len(st["wrong"]), marks=st["marks"], insns=len(f.body), words=len(f.words), live=f.live_max(), K=f.meta["K"], D=f.meta["D"], phases=f.by_phase(), counts=f.counts())
        print(f"{fmtname} {fn:5s} {sf.RND_NAMES[rnd]} K{f.meta['K']} D{f.meta['D']} n {st['n']} marked {st['marked']} (right {st['marked_right']}) wrong {len(st['wrong'])} insns {len(f.body)} words {len(f.words)} live {f.live_max()} {st['marks'][:3]} {st['wrong'][:2]}  {time.perf_counter()-t0:.0f}s", flush=True)
print(f"{time.perf_counter()-t0:.0f}s; skipped (deadline): {skipped if skipped else 'none'}")
