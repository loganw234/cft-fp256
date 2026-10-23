# M4 model: what the functions of one argument share in a compiled step
# (scratch; the study's 2.1, 5 and 7). cftc's inliner (python/cftc/
# inline.py, expand) keys each routine instruction by (opcode name,
# attribute, resolved operands) across every instance in the step, after
# routines.simplify; this replays that keying (M2's share.py, with inputs
# keyed by name) over instances bound to one input and counts what remains.
#
#   python share.py FMT

import sys

from m4core import FORMATS, sf, ATTRS, RNE
from m4inv import build
from cft_golden import routines


def expand(frags):
    keyed, total = {}, 0
    for f in frags:
        vals = {}
        for i, (opc, r, srcs) in enumerate(f.body):
            ss = tuple(("x", s[1]) if s[0] == "in" else vals[s] if s[0] == "v"
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
    for rnd in ATTRS:
        s = build(fmt, rnd, "asin")
        c = build(fmt, rnd, "acos")
        for label, frs in (("asin + acos", [s, c]),):
            n, tot = expand(frs)
            extra = n - len(frs[0].body)
            print(f"{name} {sf.RND_NAMES[rnd]} {label}: {n} instructions "
                  f"together, against {tot} apart; {extra} beyond "
                  f"asin's {len(frs[0].body)}", flush=True)


if __name__ == "__main__":
    main()
