# M3 model: values live at once, by order (scratch; the study's 5.2). The
# tree's schedule_order takes the fewest of three orders (by phase; depth
# first from the flag word, then the result; the design's own). pow keeps
# its special rows' conditions live across the main path in all three, so
# a fourth is tried here, depth first from the RESULT, then the flag word
# (mathlib's _dfs_order with its two roots swapped; nothing in the tree is
# changed). MEASURED on the fragments, every attribute.
#
#   python sched.py FMT

import sys

from m3core import FORMATS, ATTRS, ml
import m3pow as M


def dfs(f, roots):
    n = len(f.body)
    anc = [0] * n
    for i, (_op, _r, srcs) in enumerate(f.body):
        m = 1 << i
        for s in srcs:
            if s[0] == "v":
                m |= anc[s[1]]
        anc[i] = m
    size = [bin(m).count("1") for m in anc]

    def deps(i):
        return sorted({s[1] for s in f.body[i][2] if s[0] == "v"},
                      key=lambda j: (-size[j], j))
    order, seen = [], set()
    for root in roots:
        if root in seen:
            continue
        seen.add(root)
        stack = [(root, iter(deps(root)))]
        while stack:
            node, it = stack[-1]
            for j in it:
                if j not in seen:
                    seen.add(j)
                    stack.append((j, iter(deps(j))))
                    break
            else:
                stack.pop()
                order.append(node)
    return order


def main():
    fmt = FORMATS[sys.argv[1]]
    for fn, n in (("pow", None), ("powr", None), ("pown", 3), ("rootn", 3),
                  ("compound", 3)):
        rows = []
        for rnd in ATTRS:
            b = M.build(fn, fmt, rnd, n=n)
            f0 = b.fragment(schedule=False)
            keep = b.live_indices()
            phases = [b.phase_of[i] for i in keep]
            ranked = ml.permuted(f0, ml._ranked_order(f0, phases)).live_max()
            dflags = ml.permuted(f0, ml._dfs_order(f0)).live_max()
            dres = ml.permuted(f0, dfs(f0, (f0.result[1], f0.flags[1]))
                               ).live_max()
            rows.append((ranked, dflags, f0.live_max(), dres,
                         b.fragment().live_max()))
        cols = list(zip(*rows))
        names = ("by phase", "depth first, flags first", "design order",
                 "depth first, result first", "schedule_order's choice")
        tag = fn if n is None else f"{fn}(x, {n})"
        print(f"{fmt.name} {tag}: " + "; ".join(
            f"{nm} {'/'.join(map(str, c))}" for nm, c in zip(names, cols))
            + " (rne/rtz/rdn/rup/rmm)", flush=True)


if __name__ == "__main__":
    main()
