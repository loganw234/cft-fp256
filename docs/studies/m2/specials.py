# M2 model: the specials and the flags, row by row (scratch; the study's
# section 4). Each row's arguments through the routine and transcend.py,
# at every attribute: equal in bits and flag word, or marked.
#
#   python specials.py FMT

import sys
from fractions import Fraction

from m2core import FORMATS, sf, enc, evaluate, ATTRS
from m2harness import tr
from m2trig import build, gates


def rows(fmt):
    gs, gc = gates(fmt)
    S = fmt.sign_mask
    qn, sn = sf.qnan_bits(fmt), sf.snan_bits(fmt)
    out = [
        ("NaN (quiet, both signs)", [qn, qn | S]),
        ("NaN (signalling, both signs)", [sn, sn | S]),
        ("+inf, -inf", [sf.inf_bits(fmt), sf.inf_bits(fmt, 1)]),
        ("+0, -0", [0, S]),
        ("subnormals: min, max, both signs",
         [sf.min_subnormal_bits(fmt), sf.max_subnormal_bits(fmt),
          sf.min_subnormal_bits(fmt) | S, sf.max_subnormal_bits(fmt) | S]),
        ("min normal, both signs", [sf.min_normal_bits(fmt), sf.min_normal_bits(fmt) | S]),
    ]
    for nm, g in (("sin's gate 2^%d" % gs, gs), ("cos's and tan's gate 2^%d" % gc, gc)):
        b = enc(fmt, Fraction(2) ** g)
        out.append((f"{nm}: the largest tiny and the smallest not, both signs",
                    [b - 1, b, (b - 1) | S, b | S]))
    out.append(("max normal, both signs", [sf.max_normal_bits(fmt), sf.max_normal_bits(fmt) | S]))
    return out


def main():
    name = sys.argv[1]
    fmt = FORMATS[name]
    rs = rows(fmt)
    for fn in ("sin", "cos", "tan"):
        frags = {rnd: build(fmt, rnd, fn) for rnd in ATTRS}
        for label, xs in rs:
            cells = []
            ok = True
            for rnd in ATTRS:
                for xa in xs:
                    b, w, _ = evaluate(frags[rnd], xa)
                    gb, gf = tr.compute(fmt, fn, xa, 0, rnd)
                    if w & 0x80:
                        cells.append(f"{sf.RND_NAMES[rnd]}:{hex(xa)} marked")
                    elif (b, w) != (gb, gf):
                        ok = False
                        cells.append(f"{sf.RND_NAMES[rnd]}:{hex(xa)} WRONG {hex(b)}/{w:#x} vs {hex(gb)}/{gf:#x}")
            words = sorted({evaluate(frags[r], xa)[1] for r in ATTRS for xa in xs})
            res = sorted({hex(evaluate(frags[0], xa)[0]) for xa in xs})
            print(f"{name} {fn} | {label} | rne results {res} | flag words "
                  f"{[hex(w) for w in words]} | {'equal' if ok else 'DIFFER'} "
                  f"{'; '.join(cells) if cells else ''}", flush=True)


if __name__ == "__main__":
    main()
