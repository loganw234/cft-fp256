# The cost of the alternatives, by building them and counting (no runs):
#   N, the table's size, read by a SELECT tree (4, 8, 16, 32);
#   G, the guard (36, 40, 46, 52): instructions against the mark rate;
#   the table read from a scratch copy by LDX instead (computed: the
#   SELECT tree's instructions replaced by two IADDs and two LDXs, the
#   copy's 2N slots a lane and its 2N STL a segment).
import sys
from m1core import sf
from m1exp import build_exp, exp_plan
from m1log import build_log, log_plan
from m1harness import FORMATS

rnd = sf.RND_RNE
print("exp, rne: N (SELECT tree) -> K, D, instructions [lookup phase], words")
for fmtname in ("fp64", "fp128", "fp256"):
    fmt = FORMATS[fmtname]
    for N in (4, 8, 16, 32):
        f = build_exp(fmt, rnd, "exp", N=N)
        ph = f.by_phase()
        ldx = len(f.body) - ph.get("lookup", 0) + 4 + 1
        print(f"  {fmtname} N={N:2d}: K {f.meta['K']} D {f.meta['D']:2d}  insns {len(f.body)} [lookup {ph.get('lookup', 0)}]  words {len(f.words)}  | LDX copy: {ldx} insns, {2 * N} slots a lane")
print("exp and log, rne: G -> instructions; the mark rate 2^(0.53-G) a call")
for fmtname in ("fp64", "fp128", "fp256"):
    fmt = FORMATS[fmtname]
    for G in (36, 40, 46, 47, 48, 52, 60):
        try:
            fe = build_exp(fmt, rnd, "exp", G=G)
            fl = build_log(fmt, rnd, "log", G=G)
        except ValueError as e:
            print(f"  {fmtname} G={G}: {e}")
            continue
        print(f"  {fmtname} G={G}: exp K {fe.meta['K']} D {fe.meta['D']} {len(fe.body)} insns; log K {fl.meta['K']} D {fl.meta['D']} {len(fl.body)} insns; rate 2^{0.53 - G:.1f}")
