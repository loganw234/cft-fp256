# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""The order of a step's operations, and what an order costs.

Every order here respects the step's dependences, so every order
computes the same bits and the same FLAGS; what an order changes is the
time a tile takes. The cost model is believed, from docs/SEQUENCER.md
R12 to R19 (revision 7, the single-pass tile), and the card's
measurement is the lead's:

* an ALU instruction or a static scratch access issues one beat a cycle;
* a dependent ALU link costs LATENCY + 1 = 17 cycles from the producer's
  issue to its user's (R15's forwarding);
* an LDL behind an array writer still in flight rides the array and its
  value lands 17 cycles on; otherwise it is fast, a few cycles;
* an LDL straight after an STL waits two cycles (R18);
* REPEAT and ENDREP wait for nothing; a register written after it was
  read, or written twice, costs nothing (R12's in-order retire).

So at a full block (sixteen beats) every order costs the same, to within
a cycle a dependent pair, and only below one block does the order
matter - which is why the objective (regalloc.best_program) is the
instruction count first and the one-beat cycles second. No price here
depends on the format, so no decision does.

The candidate orders:
  graph        the step graph's own order: L1's post-order from the
               outputs, state by state
  pressure     that order, except that a ready node which is the last
               use of an operand, and needs no state or lane value not
               yet in use, goes first
  latency      a list schedule at one beat by critical-path height, ties
               by the graph's order
  integrated   latency while fewer than (registers - margin) values are
               live, pressure above (Goodman and Hsu's integrated
               prepass), at margins 2, 4 and 8
"""

LAT = 17            # LATENCY 16 + 1: a dependent link, issue to issue
FAST_LOAD = 3       # a fast LDL's value, issue to readable (R18), believed

CANDIDATES = (("graph", 0), ("pressure", 0), ("latency", 0),
              ("integrated", 2), ("integrated", 4), ("integrated", 8))


def _dag(nodes):
    n = len(nodes)
    succ = [[] for _ in range(n)]
    for j, nd in enumerate(nodes):
        for r in nd.args:
            if r[0] == "n":
                succ[r[1]].append(j)
    height = [0] * n
    for j in range(n - 1, -1, -1):
        height[j] = LAT + max((height[s] for s in succ[j]), default=0)
    return succ, height


def order(low, name, margin=0, pinned=(), budget=29):
    """The node order a candidate makes (indices into low.nodes)."""
    nodes = low.nodes
    n = len(nodes)
    if name == "graph":
        return list(range(n))
    succ, height = _dag(nodes)
    indeg = [sum(1 for r in nd.args if r[0] == "n") for nd in nodes]
    remaining = {}
    for nd in nodes:
        for r in nd.args:
            if r[0] in "sln":
                remaining[r] = remaining.get(r, 0) + 1
    # Only operand uses are counted: an output is stored, or moved into its
    # register, as soon as it is made, so it is not live past that.
    pinned = set(pinned)
    live = set(pinned)
    ready = [j for j in range(n) if indeg[j] == 0]
    issued = {}
    t = 0
    out = []

    def landed_at(j):
        return max((issued[r[1]] + LAT for r in nodes[j].args
                    if r[0] == "n"), default=0)

    def pick_latency():
        cands = [j for j in ready if landed_at(j) <= t]
        if cands:
            return min(cands, key=lambda j: (-height[j], j)), t
        j = min(ready, key=lambda j: (landed_at(j), -height[j], j))
        return j, landed_at(j)

    def pick_pressure():
        best = None
        for j in ready:
            counts = {}
            for r in nodes[j].args:
                if r[0] in "sln":
                    counts[r] = counts.get(r, 0) + 1
            kills = new = 0
            for r, c in counts.items():
                if r in live and remaining.get(r, 0) == c and r not in pinned:
                    kills += 1
                if r[0] in "sl" and r not in live:
                    new += 1
            if kills and not new and (best is None or j < best):
                best = j
        return (min(ready) if best is None else best), t

    while ready:
        if name == "latency":
            j, t = pick_latency()
        elif name == "pressure":
            j, t = pick_pressure()
        else:
            if len(live) < budget - margin:
                j, t = pick_latency()
            else:
                j, t = pick_pressure()
        ready.remove(j)
        out.append(j)
        issued[j] = t
        t += 1
        for r in nodes[j].args:
            if r[0] in "sln":
                remaining[r] -= 1
                if r[0] in "sl":
                    live.add(r)
        for r in set(nodes[j].args):
            if r[0] in "sln" and remaining[r] == 0 and r not in pinned:
                live.discard(r)
        key = ("n", j)
        if remaining.get(key, 0):
            live.add(key)
        for s in succ[j]:
            indeg[s] -= 1
            if indeg[s] == 0:
                ready.append(s)
    if len(out) != n:
        raise AssertionError("the schedule lost a node")
    return out


def cycles(body, beats):
    """The model's cycles a step, steady state, for a step body (a list of
    regalloc.Ins) on a block of `beats` beats."""
    ready = {}
    land = 0
    t = 0
    prev_store = False
    marks = []
    for _ in range(3):
        for ins in body:
            start = t
            for r in ins.reads():
                start = max(start, ready.get(r, 0))
            if ins.kind == "ldl" and prev_store:
                start = max(start, t + 2)
            if ins.kind in ("alu", "copy"):
                ready[ins.rd] = start + LAT
                land = max(land, start + LAT)
            elif ins.kind == "ldl":
                ready[ins.rd] = start + (LAT if start < land else FAST_LOAD)
            t = start + beats
            prev_store = ins.kind == "stl"
        t += 1                      # ENDREP
        marks.append(t)
    return marks[-1] - marks[-2]
