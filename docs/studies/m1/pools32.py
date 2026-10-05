# The triple-word fp32 exp against transcend.py over the fp32 pools.
#   python pools32.py G [rnd,rnd,...]
import time, sys
from m1core import sf, evaluate
from m1exp32 import build_exp32
from m1harness import pools, compare, FORMATS
fmt = FORMATS["fp32"]
xs = pools(fmt)
t0 = time.perf_counter()
G = int(sys.argv[1]) if len(sys.argv) > 1 else 46
rnds = [int(c) for c in sys.argv[2].split(",")] if len(sys.argv) > 2 else list(sf.RND_MODES)
for rnd in rnds:
    f = build_exp32(fmt, rnd, G=G)
    st = compare(f, "exp", xs, rnd)
    print(f"fp32 exp {sf.RND_NAMES[rnd]} G{G} K3 {f.meta['K3']} K2 {f.meta['K2']} D {f.meta['D']}: insns {len(f.body)} words {len(f.words)} live {f.live_max()}  pool {st['n']} marked {st['marked']} (right {st['marked_right']}) wrong {len(st['wrong'])} {st['marks'][:4]} {st['wrong'][:3]}  {time.perf_counter()-t0:.0f}s", flush=True)
print(f.by_phase())
