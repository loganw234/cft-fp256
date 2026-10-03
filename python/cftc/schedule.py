# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""The order of a step's operations, and what an order costs.

Every order here respects the step's dependences, so every order
computes the same bits and the same FLAGS; what an order changes is the
time a tile takes. The cost model is docs/SEQUENCER.md R12 to R19
(revision 7, the single-pass tile), and the card has measured it: on
revision 7's quad on the U50, ten compiled programs ran 2.2% to 5.8%
slower than it (docs/VALIDATION.md, 2026-10-02):

* an ALU instruction or a static scratch access issues one beat a cycle;
* a dependent ALU link costs LATENCY + 1 = 17 cycles from the producer's
  issue to its user's (R15's forwarding);
* an LDL behind an array writer still in flight rides the array and its
  value lands 17 cycles on; otherwise it is fast, a few cycles;
* an LDL straight after an STL waits two cycles (R18);
* REPEAT and ENDREP wait for nothing; a register written after it was
  read, or written twice, costs nothing (R12's in-order retire);
* a routine's instructions (C4) are ALU instructions and cost what they
  do; its QUIET and ENDQUIET cost a cycle each and wait for nothing, and
  its RAISE waits for its register to have LANDED - R18's rule for
  SETACT, three cycles past a forwarded link - then walks the beats one
  a cycle. Those three are revision 8's R24, which no tile has, so their
  prices are believed, from R18's for the control codes it built.

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
  interleaved  for a step with tangent vectors only: the post-order walk
               from the outputs, each component's tangent outputs beside
               its own (x0, v.x0, w.x0, x1, ...), operands in order. A
               tangent reads each stage's primal values, and the other
               orders compute the whole primal step first, so those
               values wait in scratch: Lorenz-96 at N = 40 with one
               vector spilled 309 values under the six above and 59 here,
               and 59 at every N measured (L3, 2026-10-01). It is offered
               beside the six, never in their place: for Lorenz-63 the
               latency order stays cheaper, and for two, three or four
               vectors at N = 40 the six's fewer instructions win under
               the objective, at more scratch (450 slots at T = 2; 490
               against 300 at T = 3) - the objective does not read the
               target's
               capacity, which would make the image depend on the target
               (a known limit, docs/LANGUAGE.md).
"""

LAT = 17            # LATENCY 16 + 1: a dependent link, issue to issue
FAST_LOAD = 3       # a fast LDL's value, issue to readable (R18), believed
LANDED = 3          # a landed read's cycles past a forwarded one (R18)

CANDIDATES = (("graph", 0), ("pressure", 0), ("latency", 0),
              ("integrated", 2), ("integrated", 4), ("integrated", 8))
TANGENT_CANDIDATES = (("interleaved", 0),)


def candidates(low):
    """The candidate orders for this step: the six, and for a step with
    tangent vectors the interleaved walk after them, so that a tie keeps
    the six's choice and a step without tangents compiles as before."""
    return CANDIDATES + (TANGENT_CANDIDATES if low.graph.T else ())


def interleaved(low):
    """The post-order walk from the outputs taken as x0, v.x0, w.x0, x1,
    ... - the graph's own walk with each tangent output beside its
    component's - walked in a loop."""
    g = low.graph
    n, T = g.n_primal, g.T
    roots = []
    for i in range(n):
        roots.append(low.outs[i])
        roots.extend(low.outs[n * (k + 1) + i] for k in range(T))
    nodes = low.nodes
    seen, out = set(), []
    for root in roots:
        if root[0] != "n" or root[1] in seen:
            continue
        stack = [[root[1], 0]]
        while stack:
            frame = stack[-1]
            j, a = frame
            args = nodes[j].args
            if a < len(args):
                frame[1] = a + 1
                r = args[a]
                if r[0] == "n" and r[1] not in seen:
                    stack.append([r[1], 0])
                continue
            stack.pop()
            if j not in seen:
                seen.add(j)
                out.append(j)
    # a node no output reads - none in a canonical step - is placed last,
    # in the graph's order, so the order is total
    out += [j for j in range(len(nodes)) if j not in seen]
    return out


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
    if name == "interleaved":
        return interleaved(low)
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


def unrolled(body):
    """A step body as it executes: a call loop's body once a call, its
    ENDREP each time, its REPEAT once (callloop.py)."""
    out, k = [], 0
    while k < len(body):
        ins = body[k]
        if ins.kind != "repeat":
            out.append(ins)
            k += 1
            continue
        e = k + 1
        while body[e].kind != "endrep":
            e += 1
        out.append(ins)
        for _ in range(ins.slot):
            out.extend(body[k + 1:e + 1])
        k = e + 1
    return out


def cycles(body, beats):
    """The model's cycles a step, steady state, for a step body (a list of
    regalloc.Ins) on a block of `beats` beats.

    A call loop (C4) runs as unrolled() says, its REPEAT and each ENDREP a
    cycle; its LDX waits for its index to have LANDED, fires its value two
    steps later than an LDL's, and holds the next instruction that is not
    an LDX two cycles; its STX waits for its data forwarded and its index
    landed; its index arithmetic is ALU arithmetic (R18's rules for the
    indexed codes, which no compiled program has run on a card: believed,
    as the routines' own prices are)."""
    ready = {}
    land = 0
    t = 0
    prev_store = prev_ldx = False
    marks = []
    steps = unrolled(body)
    for _ in range(3):
        for ins in steps:
            if ins.kind in ("quiet", "endquiet", "repeat", "endrep"):
                t += 1
                prev_store = prev_ldx = False
                continue
            start = t
            reads = ins.reads()
            for k, r in enumerate(reads):
                landed = ins.kind == "raise" or \
                    (ins.kind == "ldx") or (ins.kind == "stx" and k == 1)
                start = max(start, ready.get(r, 0) +
                            (LANDED if landed else 0))
            if ins.kind == "ldl" and prev_store:
                start = max(start, t + 2)
            if ins.kind != "ldx" and prev_ldx:
                start = max(start, t + 2)
            if ins.kind in ("alu", "copy", "index"):
                ready[ins.rd] = start + LAT
                land = max(land, start + LAT)
            elif ins.kind in ("ldl", "ldx"):
                ready[ins.rd] = start + (LAT if start < land else FAST_LOAD) \
                    + (2 if ins.kind == "ldx" else 0)
            t = start + beats
            prev_store = ins.kind in ("stl", "stx")
            prev_ldx = ins.kind == "ldx"
        t += 1                      # ENDREP
        marks.append(t)
    return marks[-1] - marks[-2]
