# M4 model: the cost (scratch; the study's sections 2 and 5).
#
#   python costs.py FMT
#
# For each function and attribute: instructions (the fragment's body; a
# compiled call adds QUIET, ENDQUIET and RAISE), words, values live at
# once in the body's order, the error-free transformations; by phase and by
# opcode under rne; the invariants of mathlib.py (the tree's widened form
# of C4's, the six's statement) with no live cap, and C4's own flag-word
# walk (routines.flag_words); the bank words' union over the five
# attributes, by function and for all four; and the table's size N = 2, 4,
# 8 and 16, each built: rho, K, D and the instructions.

import sys

from m4core import FORMATS, sf, ATTRS, RNE
from m4inv import build, FNS, rho_of, plan_poly, GUARD
from cft_golden import mathlib, routines


def main():
    name = sys.argv[1]
    fmt = FORMATS[name]
    union = {}
    for fn in FNS:
        words_fn = set()
        for rnd in ATTRS:
            f = build(fmt, rnd, fn)
            frag = f.to_fragment()
            inv = mathlib.invariants(frag, live_cap=None)
            fw = routines.flag_words(frag)
            words_fn |= set(f.words.values())
            union.setdefault("all", set()).update(f.words.values())
            print(f"{name} {fn} {sf.RND_NAMES[rnd]}: {len(f.body)} instructions, "
                  f"{len(f.words)} words, live {f.live_max()}; TwoSum "
                  f"{f.meta['two_sum']}, Fast2Sum {f.meta['fast_two_sum']}, "
                  f"TwoProd {f.meta['two_prod']}; invariants "
                  f"{inv if inv else 'hold'}; flag words (C4's walk) "
                  f"{sorted(hex(w) for w in fw) if fw is not None else None}",
                  flush=True)
            if rnd == RNE:
                print(f"   by phase {f.by_phase()}", flush=True)
                print(f"   by opcode {dict(sorted(f.counts().items(), key=lambda kv: -kv[1]))}",
                      flush=True)
                print(f"   plan: G {f.meta['G']} N {f.meta['N']} rho "
                      f"{f.meta['rho']:.6f} K {f.meta['K']} D {f.meta['D']}",
                      flush=True)
        union[fn] = words_fn
    print(f"{name} bank words, union over the five attributes: "
          + ", ".join(f"{fn} {len(union[fn])}" for fn in FNS)
          + f"; all four {len(union['all'])}", flush=True)
    G = GUARD[name]
    for N in (2, 4, 8, 16):
        rho, lr, hr = rho_of(N)
        K, D = plan_poly(fmt, G, rho)
        counts = {fn: len(build(fmt, RNE, fn, N=N).body) for fn in FNS}
        print(f"{name} table N = {N}: rho {float(rho):.6f}, t/c in "
              f"[{float(lr):.4f}, {float(hr):.4f}], head K {K}, degree D {D}; "
              + ", ".join(f"{fn} {counts[fn]}" for fn in FNS), flush=True)


if __name__ == "__main__":
    main()
