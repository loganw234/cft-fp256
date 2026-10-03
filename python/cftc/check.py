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
  encoding's sign-flip, or the param's value, or a word of the step's
  routines; and a halved bank whose h-scaled slots are exactly half and
  whose others are the same.

A step that divides or takes a root (C4) holds each routine to its
FRAGMENT, which the check takes from the golden model itself
(cft_golden/routines.py) - not from the compiler's inlining - and
instantiates over the node's operand symbols: each instruction a symbol
(its opcode, its own attribute where it rounds, its operands; a word the
slot holding its bits), simplified by the fragment's own rules
(routines.simplify) and interned, so that instances which share an
instruction share its symbol, as the image computes it once. Then:
* every expected symbol, a language node's or a routine's instruction's,
  is computed exactly once;
* a routine's instructions stand inside a quiet region and the
  language's outside every one (the two can never be one symbol: every
  instruction of a routine reads one of its words or its values, which
  routines.invariants proves of every fragment) - so a scaffolding flag
  cannot reach FLAGS and a language node's flags cannot be lost;
* each routine node's flag word is RAISEd exactly once, outside every
  region, and nothing else is raised;
* regions are balanced within the step, and none stands outside it.

A step with CALL LOOPS (callloop.py) is executed as the tile runs it: an
inner REPEAT's body once a call, symbolically, its index arithmetic -
the iadd and the copy of a word outside a region - evaluated concretely,
since every word's bits are known, so that each LDX and STX names the
slot the tile would: within the slots the image names statically, an
STX never below m. A call's routine is then the fragment UNBOUND, so in
a region each instruction's operands are first put through
routines.simplify, as binding them puts the inlined fragment's; and a
loop computes its routine afresh each call, so a routine instruction may
be computed more than once there - quietly, and pure - while outside the
loops it is still computed exactly once, and every language node exactly
once, outside them. The bank's words may then also be those the index
arithmetic reads, each once.

A failure is an InternalError - a defect in the compiler, never a
property of the source. seq.py against the interpreter is the other net
(programs/lang_check.py); this one sees every compilation, run or not.
"""

from collections import Counter

from cft_golden import asm, seq
from cft_golden import routines as R
from cft_golden import softfloat as sf
from cft_golden.seqflags import (FLAG_BANK_EXT, FLAG_SCRATCH_IO,
                                 FLAG_SCRATCH_STRICT)

from .ir import ROUNDED, ROUTINES
from .lower import exact_value
from .refusals import InternalError

OP_OF = {v: k for k, v in asm.OP_NAMES.items()}
QUIET, ENDQUIET, RAISE = seq.QUIET, seq.ENDQUIET, seq.RAISE   # R24
# what a call loop's body may hold (callloop.py)
LOOP_ALLOW = frozenset({asm.LDX, asm.STX, QUIET, ENDQUIET, RAISE})


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
    # a routine's word is the slot holding its bits (lower.py)
    word_slot = {s.bits: k for k, s in enumerate(low.slots)
                 if s.kind == "word"}
    bits_of_sym = {sym_bank[k]: b for b, k in word_slot.items()}

    # what each lowered node is, from the lowering's own refs; a routine
    # node's, its fragment from the golden model (module docstring)
    expected, lang_syms, flag_syms = [], [], []
    quiet_syms = set()

    def ref_sym(r):
        kind, i = r
        if kind == "s":
            return sym_in[i]
        if kind == "l":
            return sym_lane[i]
        if kind == "n":
            return expected[i]
        return sym_bank[low.slot_of[r]]
    for j, nd in enumerate(low.nodes):
        args = tuple(ref_sym(a) for a in nd.args)
        if nd.op not in ROUTINES:
            rnd = g.rnd if nd.op in ROUNDED else None
            sym = S((nd.op, rnd, args))
            expected.append(sym)
            lang_syms.append(sym)
            continue
        f = R.fragment(nd.op, g.fmt, g.rnd)
        inputs = dict(zip(f.inputs, args))
        vals = {}
        for i, (opc, r, srcs) in enumerate(f.body):
            ss = []
            for s in srcs:
                if s[0] == "in":
                    ss.append(inputs[s[1]])
                elif s[0] == "v":
                    ss.append(vals[s])
                else:
                    k = word_slot.get(f.words[s[1]])
                    if k is None:
                        _fail(f"{nd.op} node {j}'s word {s[1]} is in no bank "
                              f"slot")
                    ss.append(sym_bank[k])
            ss = tuple(ss)
            same = R.simplify(opc, ss, bits_of_sym.get, g.fmt.sign_mask)
            if same is not None:
                vals[("v", i)] = same
                continue
            sym = S((asm.OP_NAMES[opc], r, ss))
            vals[("v", i)] = sym
            quiet_syms.add(sym)
        expected.append(vals[f.result])
        flag_syms.append(vals[f.flags])
    if quiet_syms & set(lang_syms):
        _fail("a routine's instruction is a language node's: the two "
              "classes must not meet")
    want_out = [ref_sym(o) for o in low.outs]

    words = [asm.decode(w) for w in img.insns]
    reps = [k for k, d in enumerate(words) if d["ctrl"] and
            d["op"] == asm.REPEAT]
    ends = [k for k, d in enumerate(words) if d["ctrl"] and
            d["op"] == asm.ENDREP]
    if not reps or len(reps) != len(ends) or reps[0] > ends[-1] or \
            reps[-1] > ends[-1] or ends[0] < reps[0]:
        _fail("the image is not one REPEAT over the step")
    if words[reps[0]]["imm"] != steps:
        _fail(f"the REPEAT counts {words[reps[0]]['imm']}, not {steps}")
    last = words[-1]
    if not (last["ctrl"] and last["op"] == asm.HALT):
        _fail("the image does not end with halt")
    pro = words[:reps[0]]
    body = words[reps[0] + 1:ends[-1]]
    epi = words[ends[-1] + 1:-1]
    # every other REPEAT and ENDREP is a call loop's (callloop.py): one
    # deep, inside the step
    nest = 0
    for k, d in enumerate(body):
        if d["ctrl"] and d["op"] == asm.REPEAT:
            nest += 1
            if nest > 1:
                _fail(f"step instruction {k} opens a loop inside a call loop")
        elif d["ctrl"] and d["op"] == asm.ENDREP:
            nest -= 1
            if nest < 0:
                _fail(f"step instruction {k} closes no call loop")
    if nest:
        _fail("a call loop is not closed within the step")
    # an indexed access stays within the slots the image names statically
    reach = 0
    for d in words:
        if d["ctrl"] and d["op"] in (asm.STL, asm.LDL):
            reach = max(reach, (d["imm"] & asm.SLOT_MASK) + 1)

    regs, slots = {}, {}
    qdepth = [0]
    raised = Counter()
    # a value whose bits are known: the words, and what a call loop's index
    # arithmetic makes of them, evaluated concretely
    concrete = dict(bits_of_sym)
    loop_words = set()
    computed_in = Counter()         # in a call loop's body

    def read_reg(r, where):
        if r not in regs:
            _fail(f"{where} reads r{r}, which nothing defined")
        return regs[r]

    def read_slot(s, where):
        if s not in slots:
            _fail(f"{where} reads scratch slot {s}, which holds nothing "
                  f"defined here")
        return slots[s]

    def index(d, where):
        idx = concrete.get(read_reg(d["rb"], where))
        if idx is None:
            _fail(f"{where}: its index r{d['rb']} is not a slot the image "
                  f"computes from its words")
        if idx >= reach:
            _fail(f"{where}: its index, slot {idx}, is past every slot the "
                  f"image names ({reach})")
        if seq.index_step(d):
            _fail(f"{where} steps its index, which no compiled image does")
        return idx

    def run(part, name, allow, computed=None, in_loop=False):
        k = 0
        while k < len(part):
            d = part[k]
            where = f"{name} instruction {k}"
            k += 1
            if d["ctrl"]:
                code = d["op"]
                if code not in allow:
                    _fail(f"{where} is {asm.CTRL_NAMES.get(code, code)}")
                if code == asm.REPEAT:
                    # a call loop: its body, once a call, symbolically
                    e = k
                    while not (part[e]["ctrl"] and
                               part[e]["op"] == asm.ENDREP):
                        e += 1
                    if d["imm"] < 1:
                        _fail(f"{where} is a call loop of no calls")
                    depth0 = qdepth[0]
                    for call in range(d["imm"]):
                        run(part[k:e], f"{name} loop at {k - 1}, call {call},",
                            LOOP_ALLOW, computed, in_loop=True)
                        if qdepth[0] != depth0:
                            _fail(f"{where}: a call loop's body leaves its "
                                  f"quiet regions unbalanced")
                    k = e + 1
                    continue
                if code == QUIET:
                    qdepth[0] += 1
                    continue
                if code == ENDQUIET:
                    if not qdepth[0]:
                        _fail(f"{where} closes no quiet region")
                    qdepth[0] -= 1
                    continue
                if code == RAISE:
                    if qdepth[0]:
                        _fail(f"{where} raises inside a quiet region, where "
                              f"its flags would be silenced")
                    raised[read_reg(d["ra"], where)] += 1
                    continue
                if code == asm.LDX:
                    regs[d["rd"]] = read_slot(index(d, where), where)
                    continue
                if code == asm.STX:
                    s = index(d, where)
                    if s < m:
                        _fail(f"{where} writes slot {s}, a state home or a "
                              f"lane param's, through an index")
                    slots[s] = read_reg(d["ra"], where)
                    continue
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
            if op == "ior" and len(set(vals)) == 1:
                if d["rnd"]:
                    _fail(f"{where} is an ior that is not a copy")
                if not qdepth[0] and vals[0] in bits_of_sym:
                    loop_words.add(bits_of_sym[vals[0]])
                regs[d["rd"]] = vals[0]
                continue
            if not qdepth[0] and op == "iadd" and \
                    all(v in concrete for v in vals):
                # a call loop's index arithmetic, on known bits
                if d["rnd"]:
                    _fail(f"{where}: iadd carries a rounding field")
                bits, _fl = sf.iadd(g.fmt, concrete[vals[0]],
                                    concrete[vals[1]])
                for v in vals:
                    if v in bits_of_sym:
                        loop_words.add(bits_of_sym[v])
                sym = S(("bits", bits))
                concrete[sym] = bits
                regs[d["rd"]] = sym
                continue
            if qdepth[0]:
                # a routine's instruction as the fragment's rules have it
                # once its operands are bound (routines.simplify): a call
                # loop's body is the fragment unbound
                same = R.simplify(d["op"], tuple(vals), bits_of_sym.get,
                                  g.fmt.sign_mask)
                if same is not None:
                    regs[d["rd"]] = same
                    continue
            if op in ROUNDED:
                if not qdepth[0] and d["rnd"] != g.rnd:
                    _fail(f"{where}: {op} carries attribute {d['rnd']}, "
                          f"not the program's {g.rnd}")
                rnd = d["rnd"]
            else:
                if d["rnd"]:
                    _fail(f"{where}: quiet {op} carries a rounding field")
                rnd = None
            sym = S((op, rnd, tuple(vals)))
            if qdepth[0] and sym not in quiet_syms:
                _fail(f"{where}: {op} stands in a quiet region, and is no "
                      f"routine's instruction: its flags would be lost")
            if not qdepth[0] and sym in quiet_syms:
                _fail(f"{where}: a routine's {op} stands outside its quiet "
                      f"region, where its scaffolding flags would stand")
            if not qdepth[0] and op == "ior":
                _fail(f"{where} is an ior that is not a copy")
            (computed_in if in_loop else computed)[sym] += 1
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
    run(body, "step", {asm.LDL, asm.STL, QUIET, ENDQUIET, RAISE, asm.REPEAT},
        computed)
    if qdepth[0]:
        _fail("the step ends inside a quiet region")
    # each language node once, outside every call loop; each routine
    # instruction at least once and, outside the call loops, at most once
    # (a call loop computes its routine afresh each call, quiet)
    want_lang = Counter(lang_syms)
    missing = [s for s in want_lang if computed[s] != want_lang[s] or
               computed_in[s]]
    missing += [s for s in quiet_syms if computed[s] > 1 or
                computed[s] + computed_in[s] < 1]
    extra = [s for s in set(computed) | set(computed_in)
             if s not in want_lang and s not in quiet_syms]
    if missing or extra:
        n_in = sum(computed_in.values())
        _fail(f"the step computes {sum(computed.values())} operations"
              + (f" and {n_in} in call loops" if n_in else "")
              + f" for {len(expected)} nodes ({len(quiet_syms)} routine "
              f"instructions among them): {len(missing)} missing or "
              f"repeated, {len(extra)} not the step's")
    if raised != Counter(flag_syms):
        _fail(f"the step raises {sum(raised.values())} flag words for "
              f"{len(flag_syms)} routines: each routine's once, and no "
              f"other, is due")
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
    _verify_bank(low, half_values, loop_words)


def _verify_bank(low, half_values, loop_words=frozenset()):
    g = low.graph
    fmt = g.fmt
    # the words: exactly the bit patterns the step's routines' fragments
    # read, from the golden model (cft_golden/routines.py), and those a
    # call loop's index arithmetic read - each once
    want = set(loop_words)
    for op in sorted({nd.op for nd in low.nodes if nd.op in ROUTINES}):
        want |= set(R.fragment(op, fmt, g.rnd).words.values())
    have = [s.bits for s in low.slots if s.kind == "word"]
    if len(set(have)) != len(have) or set(have) != want:
        _fail(f"the bank's {len(have)} word slots are not the "
              f"{len(want)} words the step's routines and call loops read, "
              f"each once")
    for k, s in enumerate(low.slots):
        if s.kind == "word":
            if s.factor is not None:
                _fail(f"bank slot {k}, a word, is h-scaled")
            continue
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
