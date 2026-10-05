import sys, time, math
import mpmath
from m1core import sf, evaluate, dec
from m1exp32 import build_exp32
from m1harness import domain_sample, FORMATS, tr, pools
from m1measure import true_scaled, in_main
fmt = FORMATS["fp32"]; p = 24
mpmath.mp.prec = 400
t0 = time.perf_counter()
xs = domain_sample(fmt, "exp", int(sys.argv[2]) if len(sys.argv) > 2 else 600, 3)
for G in [int(g) for g in sys.argv[1].split(",")]:
    f = build_exp32(fmt, sf.RND_RNE, G=G)
    worst, wrong, marked, main = -1e9, 0, 0, 0
    for xa in xs:
        bits, fw, pr = evaluate(f, xa, want=["V0", "V1", "V2", "Bv", "t"], full=True)
        gb, gf = tr.compute(fmt, "exp", xa, 0, sf.RND_RNE)
        if fw & 0x80: marked += 1
        elif (bits, fw) != (gb, gf): wrong += 1
        if not in_main(fmt, "exp", xa): continue
        n = dec(fmt, pr["t"]) - dec(fmt, sf.round_pack(fmt, 0, 3, p - 2, 0)[0])
        k = math.floor(n / 8)
        V = sum(mpmath.mpf(dec(fmt, pr[k_]).numerator) / dec(fmt, pr[k_]).denominator for k_ in ("V0", "V1", "V2"))
        tv = true_scaled(fmt, "exp", xa, k)
        bv = dec(fmt, pr["Bv"])
        if bv == 0: continue
        err = abs(V - tv)
        if err: worst = max(worst, float(mpmath.log(err / (mpmath.mpf(bv.numerator) / bv.denominator), 2)))
        main += 1
    print(f"fp32 exp G{G} K3 {f.meta['K3']} K2 {f.meta['K2']} D {f.meta['D']}: {len(f.body)} insns, live {f.live_max()}, words {len(f.words)}; {len(xs)} random ({main} main path): wrong {wrong}, marked {marked}, worst log2(err/bound) {worst:.2f}  {time.perf_counter()-t0:.0f}s", flush=True)
