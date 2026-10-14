# M2 model: the cost (scratch; the study's section 5 and 6).
#
#   python costs.py FMT
#
# For each function and attribute: instructions (the fragment's body; a
# compiled call adds QUIET, ENDQUIET and RAISE), words, values live at
# once, by phase and by opcode, the error-free transformations; the bank
# words' union over the three functions and the five attributes; the
# invariants of mathlib.py (the widened form of C4's, the tree's) with no
# live cap, and C4's own flag-word walk (routines.flag_words); and the
# counted alternatives: the window by LDX from a scratch copy in place of
# the SELECT shifter, and design B's reduction.

import sys

from m2core import FORMATS, sf, ATTRS, RNE
from m2trig import build
from cft_golden import mathlib, routines


def main():
    name = sys.argv[1]
    fmt = FORMATS[name]
    union = {}
    for fn in ("sin", "cos", "tan"):
        words_fn = set()
        for rnd in ATTRS:
            f = build(fmt, rnd, fn)
            frag = f.to_fragment()
            inv = mathlib.invariants(frag, live_cap=None)
            fw = routines.flag_words(frag)
            words_fn |= set(f.words.values())
            union.setdefault("all", set()).update(f.words.values())
            ops = f.counts()
            ph = f.by_phase()
            win = ph.get("red-window", 0)
            ldx = len(f.body) - win + f.meta["L"]
            fb = build(fmt, rnd, fn, variant="B")
            print(f"{name} {fn} {sf.RND_NAMES[rnd]}: {len(f.body)} instructions, "
                  f"{len(f.words)} words, live {f.live_max()}; window "
                  f"{win} (SELECT shifter and its bit tests), by LDX "
                  f"{ldx} instructions ({f.meta['L']} stepped LDX); design B "
                  f"{len(fb.body)} instructions, live {fb.live_max()}; "
                  f"TwoSum {f.meta['two_sum']}, Fast2Sum {f.meta['fast_two_sum']}, "
                  f"TwoProd {f.meta['two_prod']}; invariants "
                  f"{inv if inv else 'hold'}; flag words (C4's walk) "
                  f"{sorted(hex(w) for w in fw) if fw is not None else None}",
                  flush=True)
            if rnd == RNE:
                print(f"   by phase {ph}", flush=True)
                print(f"   by opcode {dict(sorted(ops.items(), key=lambda kv: -kv[1]))}",
                      flush=True)
                print(f"   plan: b {f.meta['b']} L {f.meta['L']} words of 2/pi "
                      f"{f.meta['K_words']}; S K {f.meta['KS']} D {f.meta['DS']}, "
                      f"C K {f.meta['KC']} D {f.meta['DC']}; G {f.meta['G']}; "
                      f"range 2^{f.meta['R']}", flush=True)
        union[fn] = words_fn
    print(f"{name} bank words, union over the five attributes: sin "
          f"{len(union['sin'])}, cos {len(union['cos'])}, tan {len(union['tan'])}; "
          f"all three {len(union['all'])}", flush=True)


if __name__ == "__main__":
    main()
