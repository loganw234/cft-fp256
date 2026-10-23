# M4 model: fp32's triple word at G = 40, measured (scratch; the study's
# 2.7). One script, five modes:
#
#   python twrun.py pools            every function and attribute over the
#                                    pools against transcend.py
#   python twrun.py costs            instructions, words, values live in the
#                                    design's order and SCHEDULED (mathlib's
#                                    depth-first order, as MB1 fitted fp32's
#                                    exp), the invariants, the flag words
#   python twrun.py onseq            the scheduled fragments as programs on
#                                    seq.py, against the model and
#                                    transcend.py
#   python twrun.py measure N MODE   |V - f| / Bv over m4measure's regions,
#                                    mpmath at 4p + 200 bits, rne; every lane
#                                    against transcend.py too
#   python twrun.py plants           each m4tw plant red in pools or bound

import sys
import time

import mpmath

from m4core import FORMATS, sf, dec, evaluate2, ATTRS, RNE, RTZ
from m4harness import pool, compare, golden
from m4measure import sample, in_main, true_value
import m4tw
from cft_golden import mathlib, routines

FMT = FORMATS["fp32"]
FNS = ("atan", "asin", "acos", "atan2")


def scheduled(f):
    frag = f.to_fragment()
    return mathlib.permuted(frag, mathlib._dfs_order(frag))


def pools():
    t0 = time.perf_counter()
    for fn in FNS:
        xs = pool(FMT, fn)
        for rnd in ATTRS:
            f = m4tw.build(FMT, rnd, fn)
            st = compare(f, fn, xs, rnd)
            print(f"fp32-tw {fn} {sf.RND_NAMES[rnd]}: {len(f.body)} instructions, "
                  f"{st['n']} lanes, marked {st['marked']} (guess right "
                  f"{st['marked_right']}), wrong {len(st['wrong'])}, flag words "
                  f"{sorted(hex(v) for v in st['words'])}; "
                  f"{time.perf_counter() - t0:.0f}s", flush=True)
            for wr in st["wrong"][:4]:
                print("     WRONG", wr, flush=True)


def costs():
    words = set()
    for fn in FNS:
        for rnd in ATTRS:
            f = m4tw.build(FMT, rnd, fn)
            s = scheduled(f)
            inv = mathlib.invariants(s, live_cap=None)
            fw = routines.flag_words(s)
            words |= set(f.words.values())
            print(f"fp32-tw {fn} {sf.RND_NAMES[rnd]}: {len(f.body)} instructions, "
                  f"{len(f.words)} words, live {f.live_max()} in the design's "
                  f"order, {s.live_max()} scheduled; TwoSum {f.meta['two_sum']}, "
                  f"Fast2Sum {f.meta['fast_two_sum']}; invariants (scheduled) "
                  f"{inv if inv else 'hold'}; flag words "
                  f"{sorted(hex(v) for v in fw) if fw is not None else None}",
                  flush=True)
            if rnd == RNE:
                print(f"   by phase {f.by_phase()}", flush=True)
                print(f"   plan: K3 {f.meta['K3']} K2 {f.meta['K2']} D "
                      f"{f.meta['D']} rho {f.meta['rho']:.6f}", flush=True)
    print(f"fp32-tw bank words, all four functions and five attributes: "
          f"{len(words)}", flush=True)


def onseq():
    t0 = time.perf_counter()
    for fn in FNS:
        xs = pool(FMT, fn)
        for rnd in ATTRS:
            f = m4tw.build(FMT, rnd, fn)
            s = scheduled(f)
            try:
                if fn == "atan2":
                    outs, wds = routines.run(s, [a for a, _ in xs], [b for _, b in xs])
                else:
                    outs, wds = routines.run(s, xs)
            except AssertionError as exc:
                print(f"fp32-tw {fn} {sf.RND_NAMES[rnd]}: routines.program "
                      f"refused: {exc}", flush=True)
                continue
            dm = mism = mk = 0
            for xa, ob, ow in zip(xs, outs, wds):
                mb, mw, _ = evaluate2(f, xa)
                if (ob, ow) != (mb, mw):
                    dm += 1
                gb, gf = golden(FMT, fn, xa, rnd)
                if ow & 0x80:
                    mk += 1
                elif (ob, ow) != (gb, gf):
                    mism += 1
            print(f"fp32-tw {fn} {sf.RND_NAMES[rnd]}: {len(xs)} lanes on seq.py, "
                  f"live {s.live_max()} scheduled: differ from the model {dm}, "
                  f"from transcend.py (unmarked) {mism}, marked {mk}; "
                  f"{time.perf_counter() - t0:.0f}s", flush=True)


def measure(n, mode):
    t0 = time.perf_counter()
    mpmath.mp.prec = 4 * FMT.prec + 200
    fns = FNS if mode != "diag" else ("asin", "acos", "atan2")
    for fn in fns:
        f = m4tw.build(FMT, RNE, fn)
        xs = sample(FMT, fn, mode, n, 1)
        worst, at, main, wrong, marked = -1e9, None, 0, 0, 0
        for xa in xs:
            b, fw, pr = evaluate2(f, xa, want=["Vh", "Vl", "V2", "Bv"], full=True)
            gb, gf = golden(FMT, fn, xa, RNE)
            if fw & 0x80:
                marked += 1
            elif (b, fw) != (gb, gf):
                wrong += 1
            if not in_main(FMT, fn, xa):
                continue
            Vv = dec(FMT, pr["Vh"]) + dec(FMT, pr["Vl"]) + dec(FMT, pr["V2"])
            Bv = abs(dec(FMT, pr["Bv"]))
            T = true_value(fn, xa, FMT)
            r = abs(mpmath.mpf(Vv.numerator) / Vv.denominator - T) / (
                mpmath.mpf(Bv.numerator) / Bv.denominator)
            main += 1
            if r > 0:
                lr = float(mpmath.log(r, 2))
                if lr > worst:
                    worst, at = lr, xa
        print(f"fp32-tw {fn} rne {mode}: {main} main of {len(xs)}, wrong {wrong}, "
              f"marked {marked}; largest |V - f|/Bv 2^{worst:.2f} at {at}; "
              f"{time.perf_counter() - t0:.0f}s", flush=True)


def plants():
    for plant in (None,) + m4tw.PLANTS_TW:
        red = []
        for fn in FNS:
            f = m4tw.build(FMT, RNE, fn, plant=plant)
            st = compare(f, fn, pool(FMT, fn), RNE)
            if st["wrong"]:
                red.append(f"pools: {fn} {st['wrong'][0][0]} wrong")
                break
        mpmath.mp.prec = 4 * FMT.prec + 200
        worst = 0.0
        for fn in FNS:
            f = m4tw.build(FMT, RNE, fn, plant=plant)
            for xa in sample(FMT, fn, "edge", 200, 5):
                if not in_main(FMT, fn, xa):
                    continue
                b, fw, pr = evaluate2(f, xa, want=["Vh", "Vl", "V2", "Bv"], full=True)
                Vv = dec(FMT, pr["Vh"]) + dec(FMT, pr["Vl"]) + dec(FMT, pr["V2"])
                Bv = abs(dec(FMT, pr["Bv"]))
                r = float(abs(mpmath.mpf(Vv.numerator) / Vv.denominator
                              - true_value(fn, xa, FMT)) /
                          (mpmath.mpf(Bv.numerator) / Bv.denominator))
                worst = max(worst, r)
        if worst > 1:
            red.append(f"bound: 2^{float(mpmath.log(worst, 2)):.1f} Bv over the edge region")
        # send-back 1's corner (m4measure "tinyn", 100 lanes, rne and rtz):
        # a wrong unmarked lane, or under rne a bound past 1 or underflowed
        cw = cb = cz = 0
        for rnd in (RNE, RTZ):
            f = m4tw.build(FMT, rnd, "atan2", plant=plant)
            for xa in sample(FMT, "atan2", "tinyn", 100, 17):
                b, fw, pr = evaluate2(f, xa, want=["Vh", "Vl", "V2", "Bv"], full=True)
                if fw & 0x80:
                    continue
                if (b, fw) != tuple(golden(FMT, "atan2", xa, rnd)):
                    cw += 1
                    continue
                if rnd != RNE or fw != 0x10 or not (xa[0] & ~FMT.sign_mask):
                    continue
                Bv = abs(dec(FMT, pr["Bv"]))
                if Bv == 0:
                    cz += 1
                    continue
                Vv = dec(FMT, pr["Vh"]) + dec(FMT, pr["Vl"]) + dec(FMT, pr["V2"])
                if abs(mpmath.mpf(Vv.numerator) / Vv.denominator
                       - true_value("atan2", xa, FMT)) > mpmath.mpf(Bv.numerator) / Bv.denominator:
                    cb += 1
        if cw or cb or cz:
            red.append(f"corner: {cw} wrong unmarked, {cb} past the bound, "
                       f"{cz} with Bv underflowed")
        print(f"fp32-tw plant {plant or 'none'}: red in "
              f"{'; '.join(red) if red else 'NOTHING'} (largest edge error "
              f"2^{float(mpmath.log(worst, 2)) if worst else -999:.2f} Bv)", flush=True)


def main():
    mode = sys.argv[1]
    if mode == "measure":
        measure(int(sys.argv[2]), sys.argv[3])
    else:
        {"pools": pools, "costs": costs, "onseq": onseq, "plants": plants}[mode]()


if __name__ == "__main__":
    main()
