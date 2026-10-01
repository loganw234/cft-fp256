# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""Registers and the scratch: pinning, the allocator, its spills, and the
copies that close a step.

The image is a segment (docs/ORBITS.md): its state enters and leaves
through the scratch block, and one REPEAT runs the step S times. A state
component or a lane param is PINNED - one register for the whole
segment, loaded before the loop and the state stored after it - or
HOMED: it lives in its own scratch slot and is loaded where the step
needs it. Slots 0..n-1 are the state in the step graph's flat order,
n..m-1 the lane params, and from m the spill slots.

The step is allocated as straight-line code on a fixed order of its
nodes (schedule.py), over r3..r31: r0..r2 are where the streams start a
run, and the compiled image never reads them. Spills follow Belady's
rule - the value whose next use is furthest goes first, and at equal
distance a CLEAN one (a homed state value or lane param, or a value
already spilled), which needs no store. The lowest free register and the
lowest free spill slot are taken; on this machine a register written
after a read costs nothing (R12), so the choice changes no cycle.

A homed component's next value is stored to its slot once its old value
has no use left in the step. A pinned component's next value is written
into its register where the old value dies there - RK4's and Verlet's
updates are each their old value's last use - and otherwise moved there
at the step's end. What a step's end owes - the pinned registers' next
values, the homed stores that had to wait (an output that is another
component's input, a swap, a rotation), a pinned lane param evicted on
the way - is one parallel copy, sequenced through free registers: `ior
rd, rs, rs` (softfloat.ior: the bits, no flag; the tile's own load path,
docs/SEQUENCER.md R18), `ldl` and `stl`.

Nothing but the homes and the pinned registers carries a value from one
step to the next: a spill slot is written before it is read within a
step, a lane param's slot is never written, and every other register is
dead at ENDREP. check.py proves that of every image this writes.
"""

import heapq
from bisect import bisect_right

from . import schedule
from .ir import ROUNDED
from .refusals import InternalError

REGS = tuple(range(3, 32))
PIN_MARGIN = 4          # registers a pinning leaves to the step at least
FAR = 1 << 40


class Ins:
    """One instruction of a compiled image, before it is text.

    kind  alu   an operation of the step: op, rnd, rd, srcs, node
          copy  ior rd, src, src - a value moved, bit for bit
          ldl   rd := scratch[slot]
          stl   scratch[slot] := srcs[0]
    A source is ("r", register) or ("b", bank slot). `node` is the lowered
    node an alu computes; `key` the value a copy, load or store moves."""
    __slots__ = ("kind", "op", "rnd", "rd", "srcs", "slot", "node", "key")

    def __init__(self, kind, rd=None, srcs=(), slot=None, op=None, rnd=0,
                 node=None, key=None):
        self.kind = kind
        self.op = op
        self.rnd = rnd
        self.rd = rd
        self.srcs = tuple(srcs)
        self.slot = slot
        self.node = node
        self.key = key

    def reads(self):
        return [s[1] for s in self.srcs if s[0] == "r"]


class Program:
    """An allocated segment: prologue, step body, epilogue."""

    def __init__(self, prologue, body, epilogue, pinned, m, slots_used,
                 order, pinning):
        self.prologue = prologue
        self.body = body
        self.epilogue = epilogue
        self.pinned = pinned            # key -> register
        self.m = m
        self.slots_used = slots_used
        self.order = order
        self.pinning = pinning
        self.candidate = None

    @property
    def spill_slots(self):
        return self.slots_used - self.m

    def step_counts(self):
        c = {"alu": 0, "copies": 0, "loads": 0, "stores": 0}
        for ins in self.body:
            c[{"alu": "alu", "copy": "copies", "ldl": "loads",
               "stl": "stores"}[ins.kind]] += 1
        return c

    def registers(self):
        regs = set()
        for part in (self.prologue, self.body, self.epilogue):
            for ins in part:
                if ins.rd is not None:
                    regs.add(ins.rd)
                regs.update(ins.reads())
        return sorted(regs)


class _Alloc:
    def __init__(self, low, order, pinning):
        self.low = low
        g = low.graph
        self.n = g.n_state
        self.nl = len(g.lane)
        self.m = self.n + self.nl
        self.order = list(order)
        self.N = len(self.order)
        self.END = 2 * self.N
        self.rnd = g.rnd
        self.pinning = pinning
        self.pinned = {}
        regs = iter(REGS)
        if pinning in ("all", "state"):
            for i in range(self.n):
                self.pinned[("s", i)] = next(regs)
        if pinning == "all":
            for j in range(self.nl):
                self.pinned[("l", j)] = next(regs)
        self.pinned_regs = set(self.pinned.values())
        self.pos_of = {j: p for p, j in enumerate(self.order)}
        self.holds = {r: None for r in REGS}
        self.where = {}
        self.slot_val = {}
        self.key_slots = {}
        self.spill_heap = []
        self.next_spill = self.m
        self.out = None
        self.computed = set()
        self.closing_regs = set()
        self._uses()

    # -- where each value is used ---------------------------------------
    #
    # Positions are doubled: node p reads its operands at 2p, a store
    # that follows it happens at 2p + 1, a store before the first node at
    # -1, and the step's closing copies at 2N.

    def _uses(self):
        uses = {}

        def add(k, q):
            uses.setdefault(k, []).append(q)
        for p, j in enumerate(self.order):
            for r in self.low.nodes[j].args:
                if r[0] in "sln":
                    add(r, 2 * p)
        outs = self.low.outs
        out_state = {o for o in outs if o[0] == "s"}
        self.pending = {}
        self.deferred = set()
        self.pinned_out = {}
        self.home_out = {}
        for i, o in enumerate(outs):
            sk = ("s", i)
            if sk in self.pinned:
                if o[0] in "sln":
                    add(o, self.END)
                if o[0] == "n":
                    self.pinned_out.setdefault(o, []).append(i)
                continue
            if o == sk:
                continue                    # its home holds it already
            self.pending[i] = True
            if o[0] in "sl" or sk in out_state:
                self.deferred.add(i)        # to the closing copies
                if o[0] in "sln":
                    add(o, self.END)
            elif o[0] == "n":
                self.home_out.setdefault(o, []).append(i)
        for j in range(self.nl):
            lk = ("l", j)
            if lk in self.pinned:
                add(lk, self.END)
        # Where each homed store falls due: once its value exists and its
        # old value has no use left. stores(q) reads this index rather than
        # every pending component at every position, which was quadratic
        # (52 of the 166 s a 16,796-node step took to compile).
        self.due_at = {}
        for i in self.pending:
            o = outs[i]
            if i in self.deferred:
                continue
            last = max(uses.get(("s", i), [-2]))
            if o[0] == "n":
                q = max(2 * self.pos_of[o[1]], last) + 1
                add(o, q)
            else:
                q = last + 1
            self.due_at.setdefault(q, []).append(i)
        for k in uses:
            uses[k].sort()
        self.uses = uses

    def next_use(self, key, q):
        u = self.uses.get(key)
        if not u:
            return None
        k = bisect_right(u, q)
        return u[k] if k < len(u) else None

    # -- registers and slots ----------------------------------------------

    def place(self, key, r):
        old = self.holds[r]
        if old is not None and self.where.get(old) == r:
            del self.where[old]
        self.holds[r] = key
        self.where[key] = r

    def unplace(self, key):
        r = self.where.pop(key, None)
        if r is not None:
            self.holds[r] = None

    def slot_put(self, s, key):
        old = self.slot_val.get(s)
        if old is not None and old in self.key_slots:
            self.key_slots[old].discard(s)
        self.slot_val[s] = key
        self.key_slots.setdefault(key, set()).add(s)

    def copy_slot(self, key):
        ss = self.key_slots.get(key)
        return min(ss) if ss else None

    def new_spill_slot(self):
        if self.spill_heap:
            return heapq.heappop(self.spill_heap)
        s = self.next_spill
        self.next_spill += 1
        return s

    def release(self, key):
        """A value with no use left: its register and spill slots go."""
        self.unplace(key)
        for s in sorted(self.key_slots.pop(key, ())):
            if s >= self.m:
                del self.slot_val[s]
                heapq.heappush(self.spill_heap, s)

    # -- emission -----------------------------------------------------------

    def emit(self, ins):
        self.out.append(ins)

    def ldl(self, r, s, key):
        self.emit(Ins("ldl", rd=r, slot=s, key=key))

    def stl(self, r, s, key):
        self.emit(Ins("stl", srcs=(("r", r),), slot=s, key=key))

    def copy(self, rd, src, key):
        self.emit(Ins("copy", op="ior", rd=rd, srcs=(src, src), key=key))

    # -- choosing registers ---------------------------------------------------

    def victim(self, q, protect):
        best = None
        for r in REGS:
            k = self.holds[r]
            if k is None or k in protect:
                continue
            nu = self.next_use(k, q)
            dist = FAR if nu is None else nu - q
            clean = 1 if self.copy_slot(k) is not None else 0
            score = (dist, clean, -r)
            if best is None or score > best[0]:
                best = (score, r)
        if best is None:
            raise InternalError("no register to evict: each holds an operand "
                                "of the instruction being placed")
        return best[1]

    def spill_target(self, key, q):
        """Where an evicted value goes: its own output home when its store
        is owed and allowed now (which is the store, done early), else a
        spill slot."""
        for i in self.home_out.get(key, ()):
            if self.pending.get(i) and self.next_use(("s", i), q) is None:
                self.pending[i] = False
                return i
        return self.new_spill_slot()

    def evict(self, r, q):
        k = self.holds[r]
        if self.next_use(k, q) is not None and self.copy_slot(k) is None:
            s = self.spill_target(k, q)
            self.stl(r, s, k)
            self.slot_put(s, k)
        self.unplace(k)

    def take_reg(self, q, protect=()):
        for r in REGS:
            if self.holds[r] is None and r not in self.pinned_regs:
                return r
        for r in REGS:
            if self.holds[r] is None:
                return r
        r = self.victim(q, set(protect))
        self.evict(r, q)
        return r

    # -- one node -----------------------------------------------------------

    def node(self, p, j):
        q = 2 * p
        nd = self.low.nodes[j]
        keys = []
        for r in nd.args:
            if r[0] in "sln" and r not in keys:
                keys.append(r)
        protect = set(keys)
        for k in keys:
            if k not in self.where:
                s = self.copy_slot(k)
                if s is None:
                    raise InternalError(f"value {k} is needed by node {j} "
                                        f"and is in no register or slot")
                r = self.take_reg(q, protect)
                self.ldl(r, s, k)
                self.place(k, r)
        srcs = tuple(("r", self.where[a]) if a[0] in "sln"
                     else ("b", self.low.slot_of[a]) for a in nd.args)
        dying = [k for k in keys if self.next_use(k, q) is None]
        key = ("n", j)
        dest = None
        for i in self.pinned_out.get(key, ()):
            P = self.pinned[("s", i)]
            if self.holds[P] is None or self.holds[P] in dying:
                dest = P
                break
        if dest is None:
            pool = sorted({self.where[k] for k in dying} |
                          {r for r in REGS if self.holds[r] is None})
            unreserved = [r for r in pool if r not in self.pinned_regs]
            if unreserved:
                dest = unreserved[0]
            elif pool:
                dest = pool[0]
            else:
                dest = self.victim(q, set())
                self.evict(dest, q)
        self.emit(Ins("alu", op=nd.op,
                      rnd=self.rnd if nd.op in ROUNDED else 0,
                      rd=dest, srcs=srcs, node=j))
        for k in dying:
            self.release(k)
        self.place(key, dest)
        self.computed.add(key)

    def stores(self, q):
        """The homed stores whose turn has come after position q.

        Every value still due here is protected from eviction until its
        last store here is made: a value whose only later use is a store
        at this very position has no use AFTER q, so the eviction rule
        would drop it as dead - reloading one output for its store once
        evicted another due beside it, "output N's value is nowhere"
        (verifier-VL2's let-heavy maps). The values already in registers
        are stored first, so that the reloads after them find registers
        those stores have freed; and a value is let go after its last store
        here, since one node can be several components' next value
        (sharing merges a[1..3] = s * s into one)."""
        outs = self.low.outs
        due = []
        for i in self.due_at.get(q, ()):
            if not self.pending[i]:
                continue
            o = outs[i]
            if self.next_use(("s", i), q) is not None:
                continue
            if o[0] == "n" and o not in self.computed:
                continue
            due.append(i)
        if not due:
            return
        left = {}
        for i in due:
            left[outs[i]] = left.get(outs[i], 0) + 1
        protect = {o for o in left if o[0] in "sln"}
        due.sort(key=lambda i: (outs[i] not in self.where, i))
        for i in due:
            o = outs[i]
            if o[0] in "pcf":
                r = self.take_reg(q, protect)
                self.copy(r, ("b", self.low.slot_of[o]), o)
                self.stl(r, i, o)
                self.slot_put(i, o)
            else:
                if o not in self.where:
                    s = self.copy_slot(o)
                    if s is None:
                        raise InternalError(f"output {i}'s value is nowhere")
                    r = self.take_reg(q, protect)
                    self.ldl(r, s, o)
                    self.place(o, r)
                self.stl(self.where[o], i, o)
                self.slot_put(i, o)
            self.pending[i] = False
            left[o] -= 1
            if not left[o]:
                protect.discard(o)
                if o[0] in "sln" and self.next_use(o, q) is None:
                    self.release(o)

    # -- the step's closing copies -------------------------------------------
    #
    # From here on a value may sit in several places at once, so the
    # copies track contents (holds, slot_val) and not where/key_slots.

    def content(self, loc):
        return self.holds[loc[1]] if loc[0] == "r" else \
            self.slot_val.get(loc[1])

    def locations(self, v):
        if v[0] in "pcf":
            return [("b", self.low.slot_of[v])]
        locs = [("r", r) for r in REGS if self.holds[r] == v]
        locs += [("m", s) for s in sorted(self.slot_val)
                 if self.slot_val[s] == v]
        return locs

    def temp(self, pending, overwriting=None):
        """A register to hold a value on its way: one whose content is
        not needed, or is also somewhere that is neither this register
        nor `overwriting`, the location the move in hand is about to
        write. (Counting that location as a copy lost a value once: a
        slot-to-slot move of a swap took as its temporary the register
        holding the slot's old value, then overwrote the slot.)"""
        # Every register the closing copies write is out, those already
        # written too: a rotation once took a pinned register that had
        # just received its next value as the temporary for its cycle.
        dst = {d[1] for d, _v in pending if d[0] == "r"} | self.closing_regs
        needed = {v for _d, v in pending}
        for r in REGS:
            if r in dst:
                continue
            c = self.holds[r]
            if c is None or c not in needed:
                return r
            if any(loc not in (("r", r), overwriting)
                   for loc in self.locations(c)):
                return r
        for r in REGS:
            if r in dst:
                continue
            c = self.holds[r]
            s = self.new_spill_slot()
            self.stl(r, s, c)
            self.slot_val[s] = c
            return r
        raise InternalError("no register is free for the step's closing "
                            "copies")

    def move(self, d, v, pending):
        locs = self.locations(v)
        if not locs:
            raise InternalError(f"{v} is owed at the step's end and is "
                                f"nowhere")
        regs = [loc for loc in locs if loc[0] == "r"]
        src = regs[0] if regs else locs[0]
        if d[0] == "r":
            if src[0] == "m":
                self.ldl(d[1], src[1], v)
            else:
                self.copy(d[1], src, v)
            self.holds[d[1]] = v
            return
        if src[0] == "r":
            self.stl(src[1], d[1], v)
        else:
            t = self.temp(pending, overwriting=d)
            if src[0] == "m":
                self.ldl(t, src[1], v)
            else:
                self.copy(t, src, v)
            self.holds[t] = v
            self.stl(t, d[1], v)
        self.slot_val[d[1]] = v

    def closing(self):
        outs = self.low.outs
        moves = []
        for i in range(self.n):
            sk = ("s", i)
            if sk in self.pinned:
                moves.append((("r", self.pinned[sk]), outs[i]))
            elif self.pending.get(i):
                moves.append((("m", i), outs[i]))
        for j in range(self.nl):
            lk = ("l", j)
            if lk in self.pinned:
                moves.append((("r", self.pinned[lk]), lk))
        self.closing_regs = {d[1] for d, _v in moves if d[0] == "r"}
        pending = [(d, v) for d, v in moves if self.content(d) != v]
        rounds = 0
        while pending:
            rounds += 1
            if rounds > 8 * (len(moves) + len(REGS) + 8):
                raise InternalError("the step's closing copies do not end")
            for idx, (d, v) in enumerate(pending):
                cur = self.content(d)
                blocked = (cur is not None and cur != v
                           and any(v2 == cur for k2, (_d2, v2)
                                   in enumerate(pending) if k2 != idx)
                           and len(self.locations(cur)) <= 1)
                if not blocked:
                    self.move(d, v, pending)
                    break
            else:
                d, _v = pending[0]
                cur = self.content(d)
                t = self.temp(pending)
                self.move(("r", t), cur, pending)
            pending = [(d, v) for d, v in pending if self.content(d) != v]

    # -- the segment ---------------------------------------------------------

    def run(self):
        prologue, body, epilogue = [], [], []
        self.out = prologue
        for key, r in self.pinned.items():
            self.ldl(r, key[1] if key[0] == "s" else self.n + key[1], key)
        # the state the loop keeps at every ENDREP: pinned values in their
        # registers, homed state in its homes, lane params in their slots
        for key, r in self.pinned.items():
            self.place(key, r)
        for i in range(self.n):
            if ("s", i) not in self.pinned:
                self.slot_put(i, ("s", i))
        for j in range(self.nl):
            self.slot_put(self.n + j, ("l", j))
        self.out = body
        self.stores(-1)
        for p, j in enumerate(self.order):
            self.node(p, j)
            self.stores(2 * p + 1)
        self.closing()
        self.out = epilogue
        for i in range(self.n):
            sk = ("s", i)
            if sk in self.pinned:
                self.stl(self.pinned[sk], i, sk)
        return Program(prologue, body, epilogue, dict(self.pinned), self.m,
                       max(self.m, self.next_spill), self.order, self.pinning)


def allocate(low, order, pinning="none"):
    return _Alloc(low, order, pinning).run()


def pinnings(low):
    """The pinnings worth costing for this step, in a fixed order."""
    g = low.graph
    n, nl = g.n_state, len(g.lane)
    room = len(REGS) - PIN_MARGIN
    out = []
    if n + nl <= room:
        out.append("all")
    if nl and n <= room:
        out.append("state")
    out.append("none")
    return out


def pinned_keys(low, pinning):
    g = low.graph
    keys = []
    if pinning in ("all", "state"):
        keys += [("s", i) for i in range(g.n_state)]
    if pinning == "all":
        keys += [("l", j) for j in range(len(g.lane))]
    return keys


def best_program(low, candidates=None):
    """The cheapest allocation among the candidate orders and pinnings:
    fewest instructions a step, then the model's cycles a step at one
    beat, then the fewest outside the loop, then the fixed order."""
    best = None
    tried = []
    for pi, pin in enumerate(pinnings(low)):
        keys = pinned_keys(low, pin)
        for ci, (name, margin) in enumerate(candidates or
                                            schedule.CANDIDATES):
            order = schedule.order(low, name, margin, keys, len(REGS))
            prog = allocate(low, order, pin)
            prog.candidate = (name, margin)
            cost = (len(prog.body) + 1, schedule.cycles(prog.body, 1),
                    len(prog.prologue) + len(prog.epilogue), pi, ci)
            tried.append((pin, name, margin, cost[0], cost[1]))
            if best is None or cost < best[0]:
                best = (cost, prog)
    prog = best[1]
    prog.tried = tried
    return prog
