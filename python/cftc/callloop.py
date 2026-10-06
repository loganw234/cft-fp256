# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""The call loop (C4): a step too large to inline every routine runs some
of them in a loop instead - one copy of the routine, called once a record.

The compiler inlines every division and root (inline.py) unless the step
would then pass CALL_LOOP_ABOVE instructions. Logan's rule (2026-10-02,
"Build it now, last in C4"): the constant is the compiler's own - 32,768,
the instruction memory of the U50's revision-7 tile - and is
never read from a target, so one image still serves every target that
accepts it; it is part of the output version. Past it, BATCHES are
looped, the largest first, until the step fits or none is left.

A BATCH is the routine nodes of one operation at one routine depth - the
most routine nodes on a path from the step's inputs to the node, itself
included - so no call of a batch reads another's result, and every value
a call reads exists before the first of them runs. Planar N bodies under
rk4 give four: the first two stages' roots (their positions need no
acceleration), their divisions, the last two stages' roots, their
divisions. The largest is the one whose calls, inlined, are the most
instructions (calls times the fragment's size); ties go to the shallower,
then to div before sqrt. A batch of one call is never looped: its loop
would be its inlined copy and the loop's own instructions besides.

A looped batch of K calls has its own RECORDS, K of them, contiguous in
the scratch: a division's record is two slots, a and b, and a root's
one, a. The allocator places them where the loop stands, in the lowest
run of slots free there - the spill pool's, which may be slots dead
values used before - so a loop costs the scratch only what is live
across it; a record's slots join the pool again once the loop has run
(an a at once, a result when its value dies). The first record's slot is
then a word of the bank, LOOP_BASE, added once the allocation is chosen
(finish()). Each looped batch is

      stl  ...                      ; every call's operands into its record
      ior  rI, bBASE, bBASE         ; BASE: a word, the first record's slot
      repeat K
        ldx  ra, rI                 ; this call's a
        iadd rI, rI, bSTEP          ; STEP: the word 1
        ldx  rb, rI                 ; and its b (a division)
        quiet
          <the fragment>            ; the routine, its registers its own
        endquiet
        raise rF                    ; this call's flags
        stx  rR, rI                 ; its result, over b (a root's over a)
        iadd rI, rI, bSTEP          ; the next record
      endrep

and its results are read back from their records where the step needs
them, as spilled values are. Only revision 7's LDX, STX, IADD and REPEAT
are new here - and R24's three, which every routine needs anyway. The
loop's registers are any the allocator frees for it (plan() says how
many); nothing else is live in them across the loop.

What a looped call computes is the inlined call's, bit for bit, and its
flags are raised once: the internal check executes the loop iteration by
iteration, the index arithmetic concretely (its words' bits are known),
and holds each iteration's routine to the fragment as it holds an
inlined one (check.py).
"""

from cft_golden import routines as R

from .ir import ROUTINES
from .refusals import InternalError, refuse

CALL_LOOP_ABOVE = 32768     # instructions a step; never a target's number
STEP_BITS = 1               # the word the record index steps by
WORDS = (("LOOP_STEP", STEP_BITS),)     # a looped step's, before its bases


class Batch:
    """The routine nodes of one operation at one routine depth."""
    __slots__ = ("op", "depth", "calls")

    def __init__(self, op, depth, calls):
        self.op = op
        self.depth = depth
        self.calls = list(calls)        # lowered node indices, ascending

    @property
    def arity(self):
        return R.ROUTINES[self.op]

    def record_slots(self):
        return self.arity * len(self.calls)

    def key(self):
        return (self.op, self.depth)


def depths(low):
    """{routine node: its routine depth} (the module docstring)."""
    depth = [0] * len(low.nodes)
    out = {}
    for j, nd in enumerate(low.nodes):
        d = max((depth[a[1]] for a in nd.args if a[0] == "n"), default=0)
        if nd.op in ROUTINES:
            d += 1
            out[j] = d
        depth[j] = d
    return out


def batches(low):
    """[Batch]: every routine node in its batch, the batches by depth,
    then div before sqrt."""
    groups = {}
    for j, d in depths(low).items():
        groups.setdefault((d, low.nodes[j].op), []).append(j)
    return [Batch(op, d, sorted(calls))
            for (d, op), calls in sorted(groups.items())]


def by_size(low):
    """The batches a loop can shorten, largest first (the module
    docstring): a batch of one call is never looped, since its loop would
    be its one inlined copy and the loop's own instructions besides."""
    g = low.graph
    size = {op: len(R.fragment(op, g.fmt, g.rnd)) for op in R.ROUTINES}
    return sorted((b for b in batches(low) if len(b.calls) > 1),
                  key=lambda b: (-len(b.calls) * size[b.op], b.depth,
                                 b.op != "div"))


def select(low, keys, sizes):
    """The batches of `low` named by `keys`, in that order, each the size
    `sizes` gave it - which the words were made for."""
    by = {b.key(): b for b in batches(low)}
    out = []
    for key in keys:
        b = by.get(key)
        if b is None or len(b.calls) != len(sizes[key].calls):
            raise InternalError(f"call loop batch {key} is not the one its "
                                f"words were made for")
        out.append(b)
    return out


def finish(low, prog, source=None):
    """After the allocation is chosen: each loop's record base as a word of
    the bank (named LOOP_BASE and its loop; one slot a bit pattern, as
    every word), its index instruction pointed at it, and `bank-capacity`
    where the bank would pass 512. The allocator chose each base where it
    found the records' room (regalloc's records()), so the words are known
    only now; no decision of the allocation reads a bank slot's number."""
    from .lower import BANK_MAX, Slot
    x = prog.x
    for li in x.loops:
        nd = x.nodes[li]
        key = ("w", nd.base)
        name = ("loop", f"LOOP_BASE {nd.op} loop {nd.block + 1}")
        k = low.slot_of.get(key)
        if k is None:
            low.slot_of[key] = len(low.slots)
            low.slots.append(Slot("word", None, None, None, nd.base, 0,
                                  names=[name]))
        else:
            low.slots[k].names.append(name)
    if len(low.slots) > BANK_MAX:
        refuse("bank-capacity",
               f"{len(low.slots)} bank slots with the words of the routines "
               f"the compiler inlines and of the call loops it runs some of "
               f"them in ({len(x.loops)} record bases): the bank holds "
               f"{BANK_MAX} on every device", source=source)
    for ins in prog.body:
        if ins.kind == "index" and ins.srcs[0][0] == "base":
            b = ("b", low.slot_of[("w", ins.srcs[0][1])])
            ins.srcs = (b, b)


def contracted(low, order, looped):
    """`order` with each looped batch one item: [("n", j) or ("b", i)],
    by Kahn's rule over the batches' contraction, each item's priority its
    place in `order` - a batch's the place of its last call - so every
    other node keeps the candidate's relative order. Acyclic: a path from
    one call of a batch to another would make their depths differ."""
    import heapq
    pos = {j: p for p, j in enumerate(order)}
    of = {}
    for i, b in enumerate(looped):
        for j in b.calls:
            of[j] = i

    def item(j):
        return ("b", of[j]) if j in of else ("n", j)
    prio = {}
    for j in order:
        it = item(j)
        prio[it] = max(prio.get(it, -1), pos[j])
    preds = {it: set() for it in prio}
    succs = {it: set() for it in prio}
    for j, nd in enumerate(low.nodes):
        it = item(j)
        for a in nd.args:
            if a[0] == "n":
                p = item(a[1])
                if p == it:
                    raise InternalError(f"batch {it}: one call reads another")
                if p not in preds[it]:
                    preds[it].add(p)
                    succs[p].add(it)
    left = {it: len(ps) for it, ps in preds.items()}
    heap = [(prio[it], it) for it, k in left.items() if k == 0]
    heapq.heapify(heap)
    out = []
    while heap:
        _p, it = heapq.heappop(heap)
        out.append(it)
        for s in succs[it]:
            left[s] -= 1
            if left[s] == 0:
                heapq.heappush(heap, (prio[s], s))
    if len(out) != len(prio):
        raise InternalError("the call loop's contracted order lost an item")
    return out


_PLANS = {}


def plan(op, fmt, rnd, fixed=()):
    """The loop body of a routine, on virtual registers: (code, n) where n
    is the registers it needs, register 0 the record index, live
    throughout. `fixed` names the inputs every call of the loop takes
    from one bank slot (a division of 1, or by a constant): those are no
    part of a record, and the body reads the slot itself. Each item of
    code:
      ("ldx", d)                    d := the slot the index names
      ("step",)                     the index += the word 1
      ("quiet",) / ("endquiet",)
      ("alu", i, opcode, rnd, d, srcs)   the fragment's instruction i;
                                    a src ("r", v), ("w", bits), or
                                    ("k", input) a fixed input's slot
      ("raise", v)
      ("stx", v)                    the slot the index names := v
    A record is the inputs not fixed, in the fragment's order; the result
    goes over its last. Registers are given in a linear scan: lowest free
    first, and a value's register free after its last use, so an
    instruction may write the register of an operand it reads last."""
    import heapq
    fixed = tuple(sorted(fixed))
    key = (op, fmt.name, rnd, fixed)
    if key in _PLANS:
        return _PLANS[key]
    f = R.fragment(op, fmt, rnd)
    if all(name in fixed for name in f.inputs):
        raise InternalError(f"a {op} loop with every input fixed")
    end = len(f.body)
    last = {}
    for i, (_o, _r, srcs) in enumerate(f.body):
        for s in srcs:
            if s[0] in ("in", "v"):
                last[s] = i
    last[f.result] = end + 1        # stored after the raise
    last[f.flags] = end
    free = []                       # a min-heap of free virtual registers
    top = [1]                       # 0 is the index

    def take():
        if free:
            return heapq.heappop(free)
        r = top[0]
        top[0] += 1
        return r
    reg = {}
    code = []
    for name in f.inputs:
        if name in fixed:
            continue
        if any(c[0] == "ldx" for c in code):
            code.append(("step",))
        r = take()
        reg[("in", name)] = r
        code.append(("ldx", r))
        if ("in", name) not in last:
            heapq.heappush(free, r)     # read by nothing (none is so)
    code.append(("quiet",))
    for i, (opc, r, srcs) in enumerate(f.body):
        ss = []
        dying = []
        for s in srcs:
            if s[0] == "w":
                ss.append(("w", f.words[s[1]]))
            elif s[0] == "in" and s[1] in fixed:
                ss.append(("k", s[1]))
            else:
                ss.append(("r", reg[s]))
                if last.get(s) == i and s not in dying:
                    dying.append(s)
        for s in dying:
            heapq.heappush(free, reg.pop(s))
        if ("v", i) not in last:
            raise InternalError(f"{op}: fragment value {i} is never read")
        d = take()
        reg[("v", i)] = d
        code.append(("alu", i, opc, r, d, tuple(ss)))
    code.append(("endquiet",))
    code.append(("raise", reg[f.flags]))
    code.append(("stx", reg[f.result]))
    code.append(("step",))
    out = (code, top[0])
    _PLANS[key] = out
    return out
