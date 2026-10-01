# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""The internal check, run on every compilation: the image computes the
lowered step, exactly.

It reads the assembled image's own words - not the allocator's notes -
and executes one segment symbolically. A value is a symbol: a state
input, a lane param, a bank slot, or an operation on symbols (with the
attribute, for the four that round). The segment must:

* load nothing in its prologue but its pinned values;
* in the step, compute every lowered node exactly once, each with its
  op, its attribute and its operands in their positions;
* read no register and no slot the step has not defined first - so r0
  to r2 are never read, a spill slot never carries a value from one step
  to the next, and a pinned component's home, stale after the first
  step, is never read inside the loop;
* never write a lane param's slot;
* hold, at ENDREP, each component's next value where its value began
  the step (its pinned register, or its home), and each lane param where
  it began - which, by induction, makes every step the step;
* store the pinned state back to its homes after the loop;
* carry a bank whose every slot is its entry's encoding, or that
  encoding's sign-flip, or the param's value; and a halved bank whose
  h-scaled slots are exactly half and whose others are the same.

A failure is an InternalError - a defect in the compiler, never a
property of the source. seq.py against the interpreter is the other net
(programs/lang_check.py); this one sees every compilation, run or not.
"""

from collections import Counter

from cft_golden import asm
from cft_golden.seqflags import (FLAG_BANK_EXT, FLAG_SCRATCH_IO,
                                 FLAG_SCRATCH_STRICT)

from .ir import ROUNDED
from .lower import exact_value
from .refusals import InternalError

OP_OF = {v: k for k, v in asm.OP_NAMES.items()}


class _Syms:
    def __init__(self):
        self.ids = {}
        self.what = []

    def __call__(self, t):
        i = self.ids.get(t)
        if i is None:
            i = len(self.what)
            self.ids[t] = i
            self.what.append(t)
        return i


def _fail(why):
    raise InternalError(f"the internal check: {why}")


def verify(low, prog, image_bytes, steps, half_values=None):
    g = low.graph
    n, nl, m = g.n_state, len(g.lane), g.m
    img = asm.Image.from_bytes(image_bytes)
    if img.fmt.name != g.fmt_name:
        _fail(f"the image is {img.fmt.name} and the graph {g.fmt_name}")
    want_flags = FLAG_BANK_EXT | FLAG_SCRATCH_IO | FLAG_SCRATCH_STRICT
    if img.flags != want_flags:
        _fail(f"header flags 0x{img.flags:x}, not BANK_EXT, SCRATCH_IO and "
              f"SCRATCH_STRICT")
    if img.max_deposits != 0:
        _fail("a segment deposits nothing, and max_deposits is not 0")
    if (img.n_scratch_in, img.n_scratch_out) != (m, m):
        _fail(f"scratch in/out {img.n_scratch_in}/{img.n_scratch_out}, "
              f"not {m}/{m}")
    if img.n_consts != len(low.slots):
        _fail(f"the image addresses {img.n_consts} constants and the bank "
              f"holds {len(low.slots)}")

    S = _Syms()
    sym_in = [S(("in", i)) for i in range(n)]
    sym_lane = [S(("lane", j)) for j in range(nl)]
    sym_bank = [S(("bank", k)) for k in range(len(low.slots))]

    # what each lowered node is, from the lowering's own refs
    expected = []

    def ref_sym(r):
        kind, i = r
        if kind == "s":
            return sym_in[i]
        if kind == "l":
            return sym_lane[i]
        if kind == "n":
            return expected[i]
        return sym_bank[low.slot_of[r]]
    for nd in low.nodes:
        rnd = g.rnd if nd.op in ROUNDED else None
        expected.append(S((nd.op, rnd, tuple(ref_sym(a) for a in nd.args))))
    want_out = [ref_sym(o) for o in low.outs]

    words = [asm.decode(w) for w in img.insns]
    reps = [k for k, d in enumerate(words) if d["ctrl"] and
            d["op"] == asm.REPEAT]
    ends = [k for k, d in enumerate(words) if d["ctrl"] and
            d["op"] == asm.ENDREP]
    if len(reps) != 1 or len(ends) != 1 or reps[0] > ends[0]:
        _fail("the image is not one REPEAT over the step")
    if words[reps[0]]["imm"] != steps:
        _fail(f"the REPEAT counts {words[reps[0]]['imm']}, not {steps}")
    last = words[-1]
    if not (last["ctrl"] and last["op"] == asm.HALT):
        _fail("the image does not end with halt")
    pro = words[:reps[0]]
    body = words[reps[0] + 1:ends[0]]
    epi = words[ends[0] + 1:-1]

    regs, slots = {}, {}

    def read_reg(r, where):
        if r not in regs:
            _fail(f"{where} reads r{r}, which nothing defined")
        return regs[r]

    def read_slot(s, where):
        if s not in slots:
            _fail(f"{where} reads scratch slot {s}, which holds nothing "
                  f"defined here")
        return slots[s]

    def run(part, name, allow, computed=None):
        for k, d in enumerate(part):
            where = f"{name} instruction {k}"
            if d["ctrl"]:
                code = d["op"]
                if code not in allow:
                    _fail(f"{where} is {asm.CTRL_NAMES.get(code, code)}")
                slot = d["imm"] & asm.SLOT_MASK
                if code == asm.LDL:
                    regs[d["rd"]] = read_slot(slot, where)
                else:
                    if n <= slot < m:
                        _fail(f"{where} writes lane param slot {slot}")
                    slots[slot] = read_reg(d["ra"], where)
                continue
            if computed is None:
                _fail(f"{where} is arithmetic outside the step")
            op = asm.OP_NAMES.get(d["op"])
            if op is None:
                _fail(f"{where} is opcode {d['op']}")
            vals = []
            for (idx, is_const), field in zip(asm.sources(d),
                                              ("ra", "rb", "rc")):
                if field not in asm.OP_FIELDS[d["op"]]:
                    continue
                vals.append(sym_bank[idx] if is_const
                            else read_reg(idx, where))
            if op == "ior":
                if len(set(vals)) != 1 or d["rnd"]:
                    _fail(f"{where} is an ior that is not a copy")
                regs[d["rd"]] = vals[0]
                continue
            if op in ROUNDED:
                if d["rnd"] != g.rnd:
                    _fail(f"{where}: {op} carries attribute {d['rnd']}, "
                          f"not the program's {g.rnd}")
                rnd = g.rnd
            else:
                if d["rnd"]:
                    _fail(f"{where}: quiet {op} carries a rounding field")
                rnd = None
            sym = S((op, rnd, tuple(vals)))
            computed[sym] += 1
            regs[d["rd"]] = sym

    # the segment's start: the scratch block, nothing else
    for i in range(n):
        slots[i] = sym_in[i]
    for j in range(nl):
        slots[n + j] = sym_lane[j]
    run(pro, "prologue", {asm.LDL})
    for key, r in prog.pinned.items():
        want = sym_in[key[1]] if key[0] == "s" else sym_lane[key[1]]
        if regs.get(r) != want:
            _fail(f"the prologue leaves r{r} without {key}")
    # the state every step begins in: no register but the pinned, and no
    # home of a pinned component (stale after the first step)
    regs = {r: regs[r] for r in prog.pinned.values()}
    for key in prog.pinned:
        if key[0] == "s":
            del slots[key[1]]
    computed = Counter()
    run(body, "step", {asm.LDL, asm.STL}, computed)
    want_nodes = Counter(expected)
    if computed != want_nodes:
        missing = want_nodes - computed
        extra = computed - want_nodes
        _fail(f"the step computes {sum(computed.values())} operations for "
              f"{len(expected)} nodes: {len(missing)} missing, "
              f"{len(extra)} not the step's")
    for i in range(n):
        key = ("s", i)
        if key in prog.pinned:
            got = regs.get(prog.pinned[key])
        else:
            got = slots.get(i)
        if got != want_out[i]:
            _fail(f"at ENDREP component {g.components[i]} does not hold its "
                  f"next value")
    for j in range(nl):
        key = ("l", j)
        if slots.get(n + j) != sym_lane[j]:
            _fail(f"at ENDREP lane param {g.lane[j][0]}'s slot changed")
        if key in prog.pinned and regs.get(prog.pinned[key]) != sym_lane[j]:
            _fail(f"at ENDREP lane param {g.lane[j][0]} is not in its "
                  f"register")
    run(epi, "epilogue", {asm.STL})
    for i in range(n):
        if slots.get(i) != want_out[i]:
            _fail(f"after the loop component {g.components[i]}'s home does "
                  f"not hold its last value")
    _verify_bank(low, half_values)


def _verify_bank(low, half_values):
    g = low.graph
    fmt = g.fmt
    for k, s in enumerate(low.slots):
        if s.kind == "param":
            if s.default and s.bits != g.param[s.index][2]:
                _fail(f"bank slot {k} is not param {g.param[s.index][0]}'s "
                      f"default")
            continue
        bits = g.const[s.index][2]
        if s.kind == "flip":
            bits ^= fmt.sign_mask
        if s.bits != bits:
            _fail(f"bank slot {k} is not its {s.kind}'s encoding")
    hs = [k for k, s in enumerate(low.slots)
          if s.factor is not None and s.factor != 0]
    if hs != low.h_slots:
        _fail("the h-scaled slots are not the ones whose factor says so")
    if half_values is None:
        if hs:
            _fail("no halved bank for a bank with h-scaled slots")
        return
    for k, s in enumerate(low.slots):
        if k in hs:
            if exact_value(fmt, half_values[k]) * 2 != \
                    exact_value(fmt, s.bits):
                _fail(f"halved bank slot {k} is not exactly half")
        elif half_values[k] != s.bits:
            _fail(f"halved bank slot {k} is not the bank's")
