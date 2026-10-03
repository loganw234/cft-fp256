# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""Run-time division and square root as relocatable fragments (step 6,
parcel C4).

The language has `a / b` and `sqrt(a)` as operations, correctly rounded
with exactly the flags softfloat's div and sqrt raise (docs/LANGUAGE.md,
"The operations"). A tile has no divide or square-root instruction; it
has divfull and sqrtfull (divfull.py), whole programs that take their
operands from the streams and deposit the result and its flag word. The
language's compiler needs each as a FRAGMENT it can inline where a node
stands: no fixed registers, no fixed bank indices, no deposits. This
module makes one from divfull's own program, mechanically, so the two
cannot part - divfull.py is not touched, and its images stay what
programs/MANIFEST, host/src/divfull_images.h and programs/check.py hold.

A Fragment, for an operation, a format and the program's attribute:

  inputs    ("a", "b") for div, ("a",) for sqrt: the golden function's
            operands in its order
  body      straight-line SSA - instruction i defines value i - each
            (opcode, rnd, srcs): rnd is the instruction's OWN attribute
            where it rounds (the division's core truncates once, its q2
            fma; every other rounded instruction is rne) and None where
            the opcode does not round; a src is ("in", name), ("v", i)
            or ("w", name), a word
  words     {name: bits}: the raw bank words the body reads, by
            divfull's own names (K_SIGN, K_INF, K_QNAN, ...) - encodings
            at the format, an infinity, -0, NaNs and integers among them,
            which no language constant can be
  result    the value holding the correctly rounded result
  flags     the value holding the flag word: bits [4:0] exactly the
            operation's IEEE flags in FLAGS's order, [7:5] zero. It is
            the word divfull deposits second today, computed by the same
            instructions (the special lane's word selected over
            round_pack's), which libcft ORs into its status word
            (host/src/divsqrt.c); a compiled program RAISEs it (R24)

How one is made (fragment()), in three steps, each exact by construction:

  1. READ: every instruction of div_full_program_for(fmt) (or
     sqrt_full_program_for) but the two deposits and the halt, as SSA. A
     register read before any write is an input (r0 = a, r1 = b; r2 is
     written before it is read), a bank index its divfull name, the two
     deposited registers' last values the result and the flags.
  2. BIND: the words take their bits from divfull.bank(fmt, rnd) (or
     bank_sqrt): the five mode words become constants, 1 in the
     program's attribute's slot and 0 in the others - the attribute is
     the program's one, fixed when it is compiled.
  3. SPECIALISE (simplify(), the one statement of these rules, which the
     compiler's inlining and its internal check apply too):
       * a SELECT whose condition is a word is the operand it picks - a
         if the condition's magnitude is not zero, else b, which is
         SELECT's own rule (softfloat.select): one of its operands, bit
         for bit, and it raises nothing;
       * a SELECT whose two arms are one value is that value;
       * an IOR of a value with itself is that value (the bits ORed with
         themselves; IOR raises nothing);
       * two instructions with one opcode, attribute and operands are one
         value: the same bits, and their flags are scaffolding, silenced
         by the quiet region a fragment always runs in;
       * a value neither the result nor the flags reaches is dropped.
     None of these changes a bit of the result or of the flag word, and
     every flag the body's own instructions raise is silenced anyway.

In a compiled image a fragment is always

    quiet
      <body>          ; its own flags are scaffolding (6/3 raises inexact)
    endquiet
    raise rF          ; rF holds `flags`

so the only flags it raises are the flag word's [4:0]: sf.div's or
sf.sqrt's, divideByZero included (docs/SEQUENCER.md, R24). Its bit 7 is
never set - division and root decide their last bit in-lane, by the
exact residual - so a routine never marks a lane (flag_words() proves
the word's possible values, below).

How it is held (python/tests/test_routines.py, and the lang stage's leg
that runs the full pools): the fragment as a stand-alone program on
seq.py (program(), a naive allocation, depositing the result and the
flag word) against softfloat lane by lane - bits AND each lane's own flag
word - at all four formats and all five attributes, over test_divfull's
pools; the read form against divfull's own program, deposit for deposit;
each specialisation rule planted wrong, red; and the invariants below.

Measured (C4's ledger, 2026-10-02): the read form is 207/209/211/213
instructions (division, fp32 to fp256) and 183 to 192 (root), at most 15
values live at once; specialised, 177 to 191 and 155 to 171, at most 16
live, 36 to 41 words (31 to 34 distinct bit patterns).
"""

from . import asm, divfull, seq
from . import softfloat as sf
from .formats import FpFormat

ROUTINES = {"div": 2, "sqrt": 1}
GOLDEN = {"div": sf.div, "sqrt": sf.sqrt}
INPUTS = {"div": ("a", "b"), "sqrt": ("a",)}
ROUNDED = frozenset((sf.OP_FMA, sf.OP_ADD, sf.OP_SUB, sf.OP_MUL))
# The values a flag word can take, by its select chain (flag_words): no
# flag, invalid, divideByZero, inexact, overflow with inexact, underflow
# with inexact. Never bit 7: a routine here never marks a lane.
FLAG_WORDS = frozenset((0, sf.FLAG_INVALID, sf.FLAG_DIVZERO, sf.FLAG_INEXACT,
                        sf.FLAG_OVERFLOW | sf.FLAG_INEXACT,
                        sf.FLAG_UNDERFLOW | sf.FLAG_INEXACT))
LIVE_MAX = 16           # the most values a fragment keeps live at once


class Fragment:
    """One routine at one format and attribute (the module docstring)."""
    __slots__ = ("op", "fmt", "rnd", "inputs", "body", "result", "flags",
                 "words", "stage")

    def __init__(self, op, fmt, rnd, inputs, body, result, flags, words,
                 stage):
        self.op = op
        self.fmt = fmt
        self.rnd = rnd
        self.inputs = tuple(inputs)
        self.body = tuple(body)
        self.result = result
        self.flags = flags
        self.words = dict(words)
        self.stage = stage          # "read" or "specialised"

    def __len__(self):
        return len(self.body)

    def counts(self):
        out = {}
        for op, _r, _s in self.body:
            name = sf.OP_NAMES[op]
            out[name] = out.get(name, 0) + 1
        return out

    def live_max(self):
        """The most values live at once in body order: an input from the
        start to its last use, a value from its definition to its last
        use, the result and the flags to the end."""
        last = {}
        for i, (_op, _r, srcs) in enumerate(self.body):
            for s in srcs:
                if s[0] in ("v", "in"):
                    last[s] = i
        end = len(self.body)
        last[self.result] = end
        last[self.flags] = end
        live = {("in", n) for n in self.inputs if ("in", n) in last}
        best = len(live)
        for i, (_op, _r, srcs) in enumerate(self.body):
            for s in srcs:
                if s[0] in ("v", "in") and last.get(s) == i:
                    live.discard(s)
            if ("v", i) in last:
                live.add(("v", i))
            best = max(best, len(live))
        return best

    def word_bits(self, src):
        return self.words[src[1]]


# ---- 1 and 2: read divfull's program, the words at the attribute -----

def _program_and_bank(op, fmt, rnd):
    if op == "div":
        return (divfull.div_full_program_for(fmt), divfull._NAMES_DIV,
                divfull.bank(fmt, rnd))
    if op == "sqrt":
        return (divfull.sqrt_full_program_for(fmt), divfull._NAMES_SQRT,
                divfull.bank_sqrt(fmt, rnd))
    raise ValueError(f"{op!r} is not a routine: {', '.join(ROUTINES)}")


def read(op, fmt: FpFormat, rnd: int):
    """Steps 1 and 2: divfull's program as SSA, its words at `rnd`."""
    prog, names, bank = _program_and_bank(op, fmt, rnd)
    inputs = INPUTS[op]
    cur = {k: ("in", name) for k, name in enumerate(inputs)}
    body, deposits = [], []
    for k, word in enumerate(prog.insns):
        d = seq.decode(word)
        if d["ctrl"]:
            if d["op"] == seq.DEPOSIT:
                deposits.append(cur[d["ra"]])
                continue
            if d["op"] == seq.HALT and k == len(prog.insns) - 1:
                break
            raise AssertionError(f"{op} at {fmt.name}: instruction {k} is "
                                 f"control code {d['op']}")
        srcs = []
        for (idx, is_const), field in zip(seq.sources(d), ("ra", "rb", "rc")):
            if field not in asm.OP_FIELDS[d["op"]]:
                continue
            if is_const:
                srcs.append(("w", names[idx]))
            elif idx in cur:
                srcs.append(cur[idx])
            else:
                raise AssertionError(f"{op} at {fmt.name}: r{idx} is read "
                                     f"at instruction {k} before it is "
                                     f"written")
        body.append((d["op"], d["rnd"] if d["op"] in ROUNDED else None,
                     tuple(srcs)))
        cur[d["rd"]] = ("v", len(body) - 1)
    if len(deposits) != 2:
        raise AssertionError(f"{op} at {fmt.name}: {len(deposits)} deposits")
    words = {names[i]: bank[i] for i in range(len(names))}
    return Fragment(op, fmt, rnd, inputs, body, deposits[0], deposits[1],
                    words, "read")


# ---- 3: specialise ------------------------------------------------------

def simplify(op, srcs, bits_of, sign_mask):
    """The ref an instruction IS without being computed, or None. `srcs`
    are its operands as already resolved; `bits_of(src)` a word's bits,
    or None for anything that is not a word. The rules are the module
    docstring's step 3, but merging, which the caller keys."""
    if op == sf.OP_SELECT:
        c = bits_of(srcs[2])
        if c is not None:
            return srcs[0] if c & ~sign_mask else srcs[1]
        if srcs[0] == srcs[1]:
            return srcs[0]
    elif op == sf.OP_IOR and srcs[0] == srcs[1]:
        return srcs[0]
    return None


def specialise(f: Fragment):
    """Step 3 on a read fragment (the module docstring)."""
    words = f.words

    def bits_of(s):
        return words[s[1]] if s[0] == "w" else None
    keyed, body, new_of = {}, [], {}

    def res(s):
        return new_of[s] if s[0] == "v" else s
    for i, (op, r, srcs) in enumerate(f.body):
        srcs = tuple(res(s) for s in srcs)
        same = simplify(op, srcs, bits_of, f.fmt.sign_mask)
        if same is not None:
            new_of[("v", i)] = same
            continue
        key = (op, r, srcs)
        if key in keyed:
            new_of[("v", i)] = keyed[key]
            continue
        body.append(key)
        keyed[key] = new_of[("v", i)] = ("v", len(body) - 1)
    result, flags = res(f.result), res(f.flags)
    need, stack = set(), [s for s in (result, flags) if s[0] == "v"]
    while stack:
        v = stack.pop()
        if v not in need:
            need.add(v)
            stack.extend(s for s in body[v[1]][2] if s[0] == "v")
    keep = [i for i in range(len(body)) if ("v", i) in need]
    renum = {("v", i): ("v", k) for k, i in enumerate(keep)}
    out = []
    for i in keep:
        op, r, srcs = body[i]
        out.append((op, r, tuple(renum.get(s, s) for s in srcs)))
    used = {s[1] for _op, _r, srcs in out for s in srcs if s[0] == "w"}
    return Fragment(f.op, f.fmt, f.rnd, f.inputs, out,
                    renum.get(result, result), renum.get(flags, flags),
                    {k: v for k, v in words.items() if k in used},
                    "specialised")


# ---- what is proved of every fragment -----------------------------------

def flag_words(f: Fragment):
    """The values the flag word can take, by a walk of its definition: a
    word is its bits, a SELECT the union of its arms, an IAND with the
    word 0 is 0; anything else is unknown (None)."""
    sets = {}

    def val(s):
        if s[0] == "w":
            return {f.words[s[1]]}
        if s[0] == "v":
            return sets.get(s[1])
        return None
    for i, (op, _r, srcs) in enumerate(f.body):
        if op == sf.OP_SELECT:
            a, b = val(srcs[0]), val(srcs[1])
            sets[i] = a | b if a is not None and b is not None else None
        elif op == sf.OP_IAND and any(val(s) == {0} for s in srcs):
            sets[i] = {0}
        else:
            sets[i] = None
    return sets.get(f.flags[1]) if f.flags[0] == "v" else val(f.flags)


def invariants(f: Fragment):
    """[str]: what does not hold of the fragment, empty when all does:
    the flag word's values within FLAG_WORDS; at most LIVE_MAX live;
    every instruction reading a word or an internal value (so no
    instruction of a routine can be a language node's, whose operands
    are never a routine's words or values); no SELECT with equal arms or
    a word condition, no IOR of a value with itself, left after
    specialising; the attributes the routine's own."""
    out = []
    fw = flag_words(f)
    if fw is None or not fw <= FLAG_WORDS:
        out.append(f"the flag word's values {fw} are not within "
                   f"{sorted(FLAG_WORDS)}")
    if f.live_max() > LIVE_MAX:
        out.append(f"{f.live_max()} values live at once, past {LIVE_MAX}")
    for i, (op, r, srcs) in enumerate(f.body):
        if not any(s[0] in ("w", "v") for s in srcs):
            out.append(f"instruction {i} reads only the routine's inputs")
        if f.stage == "specialised" and simplify(
                op, srcs, lambda s: f.words[s[1]] if s[0] == "w" else None,
                f.fmt.sign_mask) is not None:
            out.append(f"instruction {i} simplifies further")
        if (op in ROUNDED) != (r is not None) or \
                (r is not None and r not in (sf.RND_RNE, sf.RND_RTZ)):
            out.append(f"instruction {i}'s attribute {r} is not the "
                       f"routine's own")
    return out


_CACHE = {}


def fragment(op, fmt: FpFormat, rnd: int):
    """The specialised fragment of `op` ("div" or "sqrt") at `fmt` under
    the program's attribute `rnd`, held to its invariants."""
    key = (op, fmt.width, rnd)
    if key not in _CACHE:
        f = specialise(read(op, fmt, rnd))
        bad = invariants(f)
        if bad:
            raise AssertionError(f"{op} at {fmt.name}, rnd {rnd}: "
                                 f"{'; '.join(bad)}")
        _CACHE[key] = f
    return _CACHE[key]


# ---- a fragment as a stand-alone program, for the tests ----------------

def program(f: Fragment):
    """(seq.Program, bank values): the fragment with its inputs in r0
    (and r1), its values given registers from r2 up by first free, its
    words a BANK_EXT bank in name order, and two deposits a lane, the
    result and the flag word - divfull's own shape, so a run reads the
    same way. Nothing here is how the compiler allocates: it is the
    smallest honest harness for the fragment's arithmetic."""
    names = sorted(f.words)
    kidx = {n: i for i, n in enumerate(names)}
    last = {}
    for i, (_op, _r, srcs) in enumerate(f.body):
        for s in srcs:
            if s[0] in ("v", "in"):
                last[s] = i
    last[f.result] = last[f.flags] = len(f.body)
    reg = {("in", n): k for k, n in enumerate(f.inputs)}
    free = [r for r in range(len(f.inputs), seq.NREG)]
    insns = []
    for i, (op, rnd, srcs) in enumerate(f.body):
        args = [(kidx[s[1]], True) if s[0] == "w" else (reg[s], False)
                for s in srcs]
        for s in set(srcs):
            if s[0] in ("v", "in") and last.get(s) == i:
                free.append(reg[s])
        free.sort()
        if not free:
            raise AssertionError("no register for the harness")
        reg[("v", i)] = free.pop(0)
        kw = {"ra": 0, "rb": 0, "rc": 0, "ka": False, "kb": False,
              "kc": False}
        for (val, isk), field in zip(args, asm.OP_FIELDS[op]):
            kw[field] = val
            kw["k" + field[1]] = isk
        kx = any(kw["k" + fl[1]] and kw[fl] >= seq.KADDR_PLAIN
                 for fl in ("ra", "rb", "rc"))
        insns.append(seq.alu(op, reg[("v", i)], kw["ra"], kw["rb"], kw["rc"],
                             rnd=sf.RND_RNE if rnd is None else rnd,
                             ka=kw["ka"], kb=kw["kb"], kc=kw["kc"], kx=kx))
    insns += [seq.deposit(reg[f.result]), seq.deposit(reg[f.flags]),
              seq.halt()]
    bank = [f.words[n] for n in names]
    return seq.Program(f.fmt, insns, consts=(), max_deposits=2,
                       flags=seq.FLAG_BANK_EXT, n_consts=len(bank)), bank


def run(f: Fragment, xs_a, xs_b=None):
    """(results, flag words), a lane each: program(f) on seq.py."""
    prog, bank = program(f)
    n = len(xs_a)
    res = seq.run(prog, list(xs_a), list(xs_b if xs_b is not None
                                          else [0] * n), bank=bank)
    outs, words = [], []
    for i in range(n):
        if res.counts[i] != 2:
            raise AssertionError(f"lane {i} deposited {res.counts[i]}")
        outs.append(res.deposits[2 * i])
        words.append(res.deposits[2 * i + 1])
    return outs, words
