# M2 model: what sin, cos and tan of one argument share in a compiled step
# (scratch; the study's 2.1 and 7). cftc's inliner (python/cftc/inline.py,
# expand) keys each routine instruction by (opcode name, attribute,
# resolved operands) across every instance in the step, after
# routines.simplify; this replays that keying over a list of instances
# bound to one input and counts the instructions that remain.
#
#   python share.py FMT

import sys

from m2core import FORMATS, sf, ATTRS, RNE
from m2trig import build
from cft_golden import routines


def expand(frags):
    keyed, total = {}, 0
    for f in frags:
        vals = {}
        for i, (opc, r, srcs) in enumerate(f.body):
            ss = tuple(("x",) if s[0] == "in" else vals[s] if s[0] == "v"
                       else ("w", f.words[s[1]]) for s in srcs)
            same = routines.simplify(opc, ss, lambda t: t[1] if t[0] == "w" else None,
                                     f.fmt.sign_mask)
            if same is not None:
                vals[("v", i)] = same
                continue
            key = (sf.OP_NAMES[opc], r, ss)
            if key not in keyed:
                keyed[key] = ("n", len(keyed))
            vals[("v", i)] = keyed[key]
        total += len(f.body)
    return len(keyed), total


def main():
    name = sys.argv[1]
    fmt = FORMATS[name]
    for rnd in (RNE,) + tuple(a for a in ATTRS if a != RNE):
        s = build(fmt, rnd, "sin")
        c = build(fmt, rnd, "cos")
        t = build(fmt, rnd, "tan")
        for label, frs in (("sin + cos", [s, c]), ("sin + cos + tan", [s, c, t]),
                           ("sin + tan", [s, t])):
            n, tot = expand(frs)
            extra = n - len(frs[0].body)
            print(f"{name} {sf.RND_NAMES[rnd]} {label}: {n} instructions "
                  f"together, against {tot} apart; {extra} beyond "
                  f"{frs[0].name.split('-')[0]}'s {len(frs[0].body)}", flush=True)


if __name__ == "__main__":
    main()
