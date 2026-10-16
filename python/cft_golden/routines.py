# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""The routines the compiler inlines, as relocatable fragments: run-time
division and square root (step 6, parcel C4), and the math library's
exp, expm1, exp2, log, log1p and log2 (M1's build, item 4).

THE EIGHT. ROUTINES, the arity map, names them in the language's own
order (lang.graph.OPS: div, sqrt, then the six), and that order is the
one order of the eight wherever cftc needs one - the bank's words, the
call loop's batches (python/cftc/lower.py, callloop.py) - so division's
and root's places, and every image without the six, are what they were.
Division's and root's fragments are READ from divfull's programs here,
below. The six's are BUILT by the math library's golden generator,
mathlib.py, and fragment() hands them out by name (Logan's answer to M1's
question 11): mathlib.fragment's own object, unchanged. mathlib.py
derives its constants through mpmath and imports it at its top, so this
module imports mathlib only inside fragment(), for one of the six: a
program without them - and the compiler compiling one - never imports
mpmath. What a fragment of each must be is ONE statement, per routine,
below ("what is proved of every fragment"): division's and root's as C4
measured them, the six's widened as M1's question 12 answers.

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

  inputs    ("a", "b") for div, ("a",) for sqrt and for each of the six:
            the golden function's operands in its order
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
            operation's IEEE flags in FLAGS's order, [6:5] zero, and [7]
            zero for division and root and the mark for the six. A
            division's or a root's is the word divfull deposits second
            today, computed by the same instructions (the special lane's
            word selected over round_pack's), which libcft ORs into its
            status word (host/src/divsqrt.c); a compiled program RAISEs
            it (R24)

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
sf.sqrt's, divideByZero included (docs/SEQUENCER.md, R24). A division's
or a root's bit 7 is never set - division and root decide their last bit
in-lane, by the exact residual - so they never mark a lane; one of the
six's is set where its in-lane test cannot decide the last bit (below).
flag_words() proves each word's possible values against its routine's
own statement, below.

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

The six (mathlib.py's module docstring is their design): one input, `a`;
the same Fragment, built rather than read, specialised by the same
simplify(), and SCHEDULED, a topological order that keeps few values
live; 175 to 433 instructions, 62 to 123 distinct words and 11 to 21
values live, by routine, format and attribute (MEASURED over all 120, M1's
build, item 4; mathlib.py, LIVE_CAP's table). Their flag word's bit 7 is
set where the routine's in-lane test cannot decide the last bit: RAISE
then MARKS the lane (R23's [7], STATUS[6]; seq.RAISE_MARK), and the
lane's value is the routine's best guess, which the definition replays
(docs/LANGUAGE.md, "A marked lane"). The six's golden functions are
transcend.py's, which decide each rounding through mpmath's enclosures.
"""

from . import asm, divfull, seq
from . import softfloat as sf
from .formats import FpFormat

# The eight, in the language's order (the module docstring): the one order
# of the routines wherever an order is needed
ROUTINES = {"div": 2, "sqrt": 1, "exp": 1, "expm1": 1, "exp2": 1, "log": 1,
            "log1p": 1, "log2": 1}
READ = ("div", "sqrt")                  # read from divfull's programs (C4)
BUILT = ("exp", "expm1", "exp2", "log", "log1p", "log2")   # mathlib.py's


def _transcend(name):
    """The golden function of one of the six, in GOLDEN's shape: transcend
    computes it, correctly rounded with its exact flags, through mpmath -
    which transcend.py imports only when it evaluates, so naming it here
    imports nothing."""
    def golden(fmt, a, rnd):
        from . import transcend
        return transcend.compute(fmt, name, a, 0, rnd)
    golden.__name__ = f"transcend_{name}"
    return golden


GOLDEN = {"div": sf.div, "sqrt": sf.sqrt,
          **{name: _transcend(name) for name in BUILT}}
INPUTS = {"div": ("a", "b"), **{op: ("a",) for op in ROUTINES if op != "div"}}
ROUNDED = frozenset((sf.OP_FMA, sf.OP_ADD, sf.OP_SUB, sf.OP_MUL))


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
    if op in BUILT:
        raise ValueError(f"{op!r} is not read from a program: mathlib.py "
                         f"builds its fragment (fragment() hands it out)")
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
#
# ONE statement for the eight (M1's build, item 4; Logan's answer to M1's
# question 12, "as recommended"): what a routine's fragment may be, stated
# PER ROUTINE - CONTRACT, the values its flag word may take and the
# attributes its instructions may carry, and LIVE_CAP, the most values it
# may keep live, by routine AND format - and one set of checks, the same for
# every routine (flag_words, invariants), that hold a fragment to its own.
# cftc's internal check holds every routine of an image to it
# (python/cftc/check.py).
#
# Why per routine. The six's are C4's widened four ways, the study found
# (docs/studies/M1-exp-log.md, section 6): the mark among the flag word's
# values, which takes an IOR rule in the walk to see; RDN, RUP and the
# program's own attribute inside a routine; more values live; and no
# instruction reading only the input (which the six keep, by an
# instruction spent in expm1 and in log1p - parcels MB1 and MB2). One
# statement shared by all eight would loosen division's and root's to the
# six's; so each routine names its own, and division's and root's are C4's
# exactly - a flag word without the mark, RNE and RTZ, 16 live - so a
# division that could mark a lane, round under RDN or keep 17 values live
# still fails. The live cap is by routine and format because that is the
# finest any routine needs: M2's fragments (sin, cos, tan), whose caps
# Logan approved per function and format on 2026-10-14 (22, 26, 17 and 16),
# extend this table. The values are where C4 and parcels MB1 and MB2
# measured and stated them; mathlib.py keeps views of the six's.

MARK = seq.RAISE_MARK
# The values a flag word can take. Division's and root's, by its select
# chain: no flag, invalid, divideByZero, inexact, overflow with inexact,
# underflow with inexact - never bit 7, since division and root decide
# their last bit in-lane by the exact residual and never mark a lane.
FLAG_WORDS = frozenset((0, sf.FLAG_INVALID, sf.FLAG_DIVZERO, sf.FLAG_INEXACT,
                        sf.FLAG_OVERFLOW | sf.FLAG_INEXACT,
                        sf.FLAG_UNDERFLOW | sf.FLAG_INEXACT))
# The six's: those, and inexact, overflow with inexact and underflow with
# inexact each with the mark (bit 7) - never bits [6:5], the mark only
# with inexact (mathlib.py's design, the study's section 4).
MARKED_FLAG_WORDS = FLAG_WORDS | frozenset(
    w | MARK for w in (sf.FLAG_INEXACT, sf.FLAG_OVERFLOW | sf.FLAG_INEXACT,
                       sf.FLAG_UNDERFLOW | sf.FLAG_INEXACT))


class Contract(tuple):
    """What a routine's instructions and flag word may be: `flag_words`,
    the values its flag word may take; `attributes`, the attributes its
    rounded instructions may carry; `program`, whether the program's own
    attribute is admitted besides (a fragment is made at one, f.rnd)."""
    __slots__ = ()

    def __new__(cls, flag_words, attributes, program):
        return tuple.__new__(cls, (frozenset(flag_words),
                                   frozenset(attributes), bool(program)))

    flag_words = property(lambda self: self[0])
    attributes = property(lambda self: self[1])
    program = property(lambda self: self[2])

    def __repr__(self):
        return (f"Contract(flag_words={sorted(self[0])}, attributes="
                f"{sorted(self[1])}, program={self[2]})")


# C4's, division's and root's: their own two attributes, the division's one
# truncating fma among them; the program's attribute is a word (the five
# mode words, step 2), never an instruction's
C4_CONTRACT = Contract(FLAG_WORDS, (sf.RND_RNE, sf.RND_RTZ), False)
# the six's (Logan's answer to M1's question 12): RNE, RTZ, RDN and RUP -
# the in-lane test rounds the two ends of its interval down and up - and
# the program's attribute, the final rounding of V_h + V_l
MATH_CONTRACT = Contract(MARKED_FLAG_WORDS, (sf.RND_RNE, sf.RND_RTZ,
                                             sf.RND_RDN, sf.RND_RUP), True)
CONTRACT = {"div": C4_CONTRACT, "sqrt": C4_CONTRACT,
            **{name: MATH_CONTRACT for name in BUILT}}

# The most values a fragment may keep live at once, by routine and format.
# Division and root: C4's 16 at every format (MEASURED by C4: at most 16
# specialised; division keeps 15 or 16 and root 12 to 15, by format and
# attribute). The six: the most any of them keeps under any attribute,
# scheduled, at that format (MEASURED, parcels MB1 and MB2; mathlib.py's
# LIVE_CAP table gives each routine's), so a growth past it is a change of
# design to look at - stated for each routine, so that one of them can be
# given its own (as M2's will be) without moving the others'.
LIVE_CAP = {
    "div": {"fp32": 16, "fp64": 16, "fp128": 16, "fp256": 16},
    "sqrt": {"fp32": 16, "fp64": 16, "fp128": 16, "fp256": 16},
    "exp": {"fp32": 21, "fp64": 13, "fp128": 13, "fp256": 13},
    "expm1": {"fp32": 21, "fp64": 13, "fp128": 13, "fp256": 13},
    "exp2": {"fp32": 21, "fp64": 13, "fp128": 13, "fp256": 13},
    "log": {"fp32": 21, "fp64": 13, "fp128": 13, "fp256": 13},
    "log1p": {"fp32": 21, "fp64": 13, "fp128": 13, "fp256": 13},
    "log2": {"fp32": 21, "fp64": 13, "fp128": 13, "fp256": 13},
}
LIVE_MAX = 16           # C4's name for division's and root's cap: theirs above
_OWN = object()         # invariants()'s default cap: the routine's own


def flag_words(f: Fragment):
    """The values the flag word can take, by a walk of its definition: a
    word is its bits, a SELECT the union of its arms, an IAND with the word
    0 is 0, an IOR the set of the pairwise ORs of its operands' (the rule
    the six's mark takes: M1's question 12); anything else is unknown
    (None). Each rule's set holds every value the instruction can give, so
    the walk can only fail to prove a word, never prove a wrong one; on
    division's and root's flag words, which no IOR reaches, it gives what
    C4's walk without the IOR rule gave (MEASURED at all 40)."""
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
        elif op == sf.OP_IOR:
            a, b = val(srcs[0]), val(srcs[1])
            sets[i] = ({u | v for u in a for v in b}
                       if a is not None and b is not None else None)
        else:
            sets[i] = None
    return sets.get(f.flags[1]) if f.flags[0] == "v" else val(f.flags)


def invariants(f: Fragment, live_cap=_OWN, contract=None):
    """[str]: what does not hold of the fragment, empty when all does - the
    one statement (the section's head), each clause by name:

      * well formed: values read only after they are defined, the words
        named held and encodings at the format, each opcode with its
        operands, the result and the flag word values of the body;
      * the flag word's values, by flag_words(), within its routine's
        CONTRACT: division's and root's never bit 7, the six's the mark
        only with inexact;
      * at most `live_cap` values live at once: its routine's LIVE_CAP at
        its format by default, None for no cap;
      * every instruction reading a word or an internal value, so that no
        instruction of a routine can be a language node's, whose operands
        are never a routine's words or values (cftc/inline.py's argument);
      * nothing left to simplify (simplify()), once specialised;
      * the attributes its routine's own: CONTRACT's, and the program's
        (f.rnd) where the contract admits it; none where an opcode does not
        round.

    `contract` holds the fragment to another statement than its routine's
    - mathlib.invariants() holds any fragment it is handed to the six's -
    and a fragment of no routine, without one, is refused by name."""
    if contract is None:
        contract = CONTRACT.get(f.op)
        if contract is None:
            return [f"{f.op!r} is not a routine, so no statement holds it: "
                    f"{', '.join(ROUTINES)}"]
    if live_cap is _OWN:
        live_cap = LIVE_CAP.get(f.op, {}).get(f.fmt.name)
    out = []
    fmt = f.fmt
    for name, bits in f.words.items():
        if not 0 <= bits < 1 << fmt.width:
            out.append(f"word {name} is not an encoding at {fmt.name}")
    n = len(f.body)
    for i, (op, r, srcs) in enumerate(f.body):
        fields = asm.OP_FIELDS.get(op)
        if fields is None or len(srcs) != len(fields):
            out.append(f"instruction {i}: opcode {op} with {len(srcs)} "
                       f"operands is not an ALU instruction")
        for s in srcs:
            if s[0] == "v" and not 0 <= s[1] < i:
                out.append(f"instruction {i} reads value {s[1]} before it "
                           f"is defined")
            elif s[0] == "w" and s[1] not in f.words:
                out.append(f"instruction {i} reads the word {s[1]!r}, "
                           f"which the fragment does not hold")
            elif s[0] == "in" and s[1] not in f.inputs:
                out.append(f"instruction {i} reads the input {s[1]!r}")
    for what, ref in (("result", f.result), ("flag word", f.flags)):
        if ref[0] != "v" or not 0 <= ref[1] < n:
            out.append(f"the {what} {ref} is not a value of the body")
    if out:
        return out              # the checks below walk a well-formed body
    fw = flag_words(f)
    if fw is None or not fw <= contract.flag_words:
        out.append(f"the flag word's values {fw} are not within "
                   f"{sorted(contract.flag_words)}")
    live = f.live_max()
    if live_cap is not None and live > live_cap:
        out.append(f"{live} values live at once, past {live_cap}")
    own = contract.attributes | ({f.rnd} if contract.program else set())
    for i, (op, r, srcs) in enumerate(f.body):
        if not any(s[0] in ("w", "v") for s in srcs):
            out.append(f"instruction {i} reads only the routine's inputs")
        if f.stage == "specialised" and simplify(
                op, srcs, lambda s: f.words[s[1]] if s[0] == "w" else None,
                fmt.sign_mask) is not None:
            out.append(f"instruction {i} simplifies further")
        if (op in ROUNDED) != (r is not None) or \
                (r is not None and r not in own):
            out.append(f"instruction {i}'s attribute {r} is not the "
                       f"routine's own")
    return out


_CACHE = {}
_HELD = set()           # the six's fragments held here once each


def fragment(op, fmt: FpFormat, rnd: int):
    """The specialised fragment of `op`, one of ROUTINES, at `fmt` under
    the program's attribute `rnd`, held to its routine's invariants:
    division's and root's read and specialised here; the six's
    mathlib.fragment's own object, built (and cached) there, unchanged.
    Only a request for one of the six imports mathlib.py, and with it
    mpmath, which it derives its constants through: without mpmath that is
    an ImportError, which the compiler never reaches - it refuses such a
    source `routine-unavailable` first (python/cftc/__init__.py)."""
    if op in BUILT:
        from . import mathlib
        f = mathlib.fragment(op, fmt, rnd)
        key = (op, fmt.name, rnd)
        if key not in _HELD:
            bad = invariants(f)
            if bad:
                raise AssertionError(f"{op} at {fmt.name}, rnd {rnd}: "
                                     f"{'; '.join(bad)}")
            _HELD.add(key)
        return f
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
