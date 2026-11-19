# M3 model: what cftc's inliner can share (scratch; the study's 5.4). The
# inliner hash-conses instructions on (opcode, attribute, operands), so two
# calls share every instruction whose operands are the same values. Each
# fragment's instructions are given a canonical key by their dataflow (the
# opcode, the attribute and the operands' keys; a word by its bits; an input
# by the name of the program value bound to it), and two calls share the
# instructions whose keys they have in common: COMPUTED on the fragments
# (MEASURED counts), not by running cftc.
#
#   python share.py FMT

import sys

from m3core import FORMATS, RNE, ml
import m3pow as M


_IDS = {}            # canonical key -> a small id, shared across fragments


def keys(f, bind):
    """{id} of a fragment's instructions' canonical keys, inputs bound to
    program names. Each key holds its operands' ids, not their keys: a key
    of nested keys rehashes the whole dataflow below it at every use, which
    is exponential on a DAG (the first version of this file ran for minutes
    at fp64 and was stopped)."""
    k = []
    out = set()
    for op, r, srcs in f.body:
        parts = []
        for s in srcs:
            if s[0] == "v":
                parts.append(("v", k[s[1]]))
            elif s[0] == "w":
                parts.append(("w", f.words[s[1]]))
            else:
                parts.append(("in", bind[s[1]]))
        key = (op, r, tuple(parts))
        kid = _IDS.setdefault(key, len(_IDS))
        k.append(kid)
        out.add(kid)
    return out


def main():
    fmt = FORMATS[sys.argv[1]]
    pw = M.build("pow", fmt, RNE).fragment()
    a = keys(pw, {"a": "x", "b": "y"})
    b = keys(pw, {"a": "x", "b": "z"})
    c = keys(pw, {"a": "w", "b": "y"})
    pr = keys(M.build("powr", fmt, RNE).fragment(), {"a": "x", "b": "y"})
    pn3 = keys(M.build("pown", fmt, RNE, n=3).fragment(), {"a": "x"})
    pn5 = keys(M.build("pown", fmt, RNE, n=5).fragment(), {"a": "x"})
    rt3 = keys(M.build("rootn", fmt, RNE, n=3).fragment(), {"a": "x"})
    l2 = keys(ml.fragment("log2", fmt, RNE), {"a": "x"})
    e2 = keys(ml.fragment("exp2", fmt, RNE), {"a": "x"})
    lg = keys(ml.fragment("log", fmt, RNE), {"a": "x"})
    print(f"{fmt.name}, rne: pow(x, y) is {len(a)} instructions")
    for name, other in (("pow(x, z), the same x", b),
                        ("pow(w, y), the same y", c),
                        ("powr(x, y)", pr),
                        ("pown(x, 3)", pn3),
                        ("pown(x, 5) against pown(x, 3)", None),
                        ("rootn(x, 3)", rt3),
                        ("log2(x), M1's", l2),
                        ("log(x), M1's", lg),
                        ("exp2(x), M1's", e2)):
        if other is None:
            sh = len(pn3 & pn5)
            print(f"  {name}: {sh} shared of {len(pn5)}; together "
                  f"{len(pn3 | pn5)} against {len(pn3) + len(pn5)} apart")
            continue
        sh = len(a & other)
        print(f"  with {name}: {sh} shared; together {len(a | other)} "
              f"against {len(a) + len(other)} apart")


if __name__ == "__main__":
    main()
