# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""The orbit sequencer, in software. This file is the definition of
correct for programs, as softfloat.py is for arithmetic.

docs/SEQUENCER.md is the design and the argument; this is the
executable form of it. The RTL will be verified against this, and a
program's output on hardware must match what `run()` produces here,
bit for bit.

Two things about the execution model are worth reading before the
code, because they are the whole determinism argument:

* **Lanes run in lockstep, not independently.** Modelling each lane to
  completion in turn would be simpler and would give the same answers,
  but it could not express the early exit - a cross-lane condition -
  and so could not be used to test that the early exit is invisible.
  This runs the machine the way the hardware will.

* **The active mask gates flags, not just writes.** An inactive lane
  contributes nothing: no register write, no deposit, and no exception
  flag. Masking only the writes would let a dead lane's stale
  registers raise `invalid` into the run's sticky word, and then the
  flags would depend on how many lanes were still running - which is
  exactly the kind of result-depends-on-convergence behaviour the
  contract exists to forbid.
"""

import struct

from .formats import FORMATS, PREC_CODE, FpFormat
from . import softfloat as sf

MAGIC = 0x50544643        # "CFTP" little-endian
VERSION = 1
HEADER_WORDS = 8
INSN_BYTES = 8
# Registers a lane owns. Thirty-two since revision 2 (2026-09-08): a
# register field is FIVE bits, the low four in the operand field where
# they have always been and the fifth in `imm[27:24]` - `imm[24]` is
# `rd[4]`, `[25]` `ra[4]`, `[26]` `rb[4]`, `[27]` `rc[4]`. `imm[31:28]`
# stays reserved-must-be-zero, which is the version guard: a loader
# older than this refuses any set bit in imm[31:24] and so refuses
# every program that names a register above 15, rather than reading
# the low four bits and silently addressing the wrong one.
NREG = 32
# What a revision-1 program could name. Kept as a constant because the
# fuzz generator's default arm draws from it: a corpus that reshuffled
# the moment NREG moved would compare two different sets of programs
# and call the result a regression.
NREG_REV1 = 16
MAX_LOOP_DEPTH = 4

# The fifth bit of each register field, by position in `imm`. Written
# as a table rather than four shifts because the RTL decode, the
# assembler and three refusal rules all read the same four bits, and
# four is exactly enough copies of a magic number to get one wrong.
REG_HI_SHIFT = {"rd": 24, "ra": 25, "rb": 26, "rc": 27}
REG_HI_MASK = 0x0F00_0000

# How many constants an instruction can ADDRESS. Without `kx` an
# operand's constant index is its own 4-bit field, so sixteen; with
# `kx` it is a byte of `imm`, so 256 - which is `KMEM_D`, the capacity
# rtl/cft_seq.sv's header check already permits. `n_consts` above this
# is not refused (it never was above sixteen either): the constants
# past it are simply unaddressable, and every index is checked against
# `n_consts` anyway.
KADDR_PLAIN = 16
KADDR_KX = 256

# A program's worst-case instruction count must be finite AND small
# enough to be a bound rather than a formality. Four nested
# `repeat 0xffffffff` fit in 104 bytes and describe 3.4e38 iterations,
# which is "terminating" only in the sense that the heat death of the
# universe is.
MAX_INSTRUCTIONS = 1 << 40

# The output buffer is n * max_deposits elements, so this is a bound on
# how much memory a 104-byte program can ask a host to allocate.
MAX_DEPOSITS = 1 << 20

# The header's `flags` word, which was `reserved[0]` until revision 2.
#
# BANK_EXT: the image carries no constant section, so it is exactly
# header + n_insns instructions, and every run supplies `n_consts`
# format-width values in a separate bank buffer. Everything above bit 0
# is reserved and must be zero, and so is the header's remaining
# reserved word - the revision-2 tile checks BOTH, which the 0x600 tile
# did not, and that omission is why the feature needs a CAPS bit at all
# rather than only a header flag.
FLAG_BANK_EXT = 1 << 0
FLAGS_KNOWN = FLAG_BANK_EXT

# control codes (instruction bit 31 set)
HALT, REPEAT, ENDREP, DEPOSIT, SETACT, ACTALL = 0, 1, 2, 3, 4, 5
CTRL_NAMES = {HALT: "halt", REPEAT: "repeat", ENDREP: "endrep",
              DEPOSIT: "deposit", SETACT: "setact", ACTALL: "actall"}

# The bits of `imm` each control code READS, and so the only bits it
# may set. Since revision 2 imm[27:24] carry the fifth bits of rd, ra,
# rb and rc, which is what this table is mostly about:
#
#   HALT, ENDREP, ACTALL   read no register and no immediate: zero.
#   DEPOSIT, SETACT        read `ra` alone, so ra's high bit imm[25]
#                          and nothing else - not rd's, not rb's, not
#                          rc's, and no part of the immediate.
#   REPEAT                 reads no register but owns the whole word
#                          as its trip count. imm[27:24] there are
#                          trip-count bits like any other, because
#                          there is no register field for them to be
#                          the high bit OF - which is also why a
#                          revision-1 tile runs such a REPEAT
#                          identically, and why narrowing this would
#                          newly refuse programs that are legal and
#                          correct on every existing bitstream.
IMM_ALLOWED = {
    HALT: 0,
    REPEAT: 0xFFFF_FFFF,
    ENDREP: 0,
    DEPOSIT: 1 << REG_HI_SHIFT["ra"],
    SETACT: 1 << REG_HI_SHIFT["ra"],
    ACTALL: 0,
}

# STATUS bits. 0..2 are the engine's bus faults and 3 is the
# precision refusal (rtl/cft_csr.sv); the sequencer adds bit 4. It
# held bit 3 until 2026-09-01, when the trimmed-build refusal took
# that position in silicon-bound RTL - moved while this word had
# never crossed a device boundary, which is the last moment moving it
# was free. It is deliberately not an IEEE flag: the five in FLAGS
# mean what 754 says they mean, and "your buffer was too small" is
# not one of them.
STATUS_DEPOSIT_OVERFLOW = 1 << 4


class ProgramError(ValueError):
    """A program the loader must refuse. Raised at validate() time, so
    a bad program never reaches a device."""


# ---- encoding --------------------------------------------------------

def encode(op, rd=0, ra=0, rb=0, rc=0, rnd=sf.RND_RNE,
           ka=False, kb=False, kc=False, ctrl=False, imm=0, kx=False):
    """One 64-bit instruction word.

    Register numbers are 0..31. The low four bits of each go in the
    operand field the encoding has always kept them in and the fifth is
    OR-ed into `imm` at REG_HI_SHIFT - so a caller writes `rd=20` and
    the split is this function's business, exactly as `alu()` already
    hides where a `kx` constant index lands.

    OR-ing rather than assigning is safe because the only instruction
    whose `imm` this function is also given is `REPEAT`, and REPEAT
    names no register at all: its four fields are zero, so nothing is
    OR-ed in and its trip count reaches the word intact.
    """
    for name, v in (("rd", rd), ("ra", ra), ("rb", rb), ("rc", rc)):
        if not 0 <= v < NREG:
            raise ProgramError(f"{name}={v} outside 0..{NREG - 1}")
    if not 0 <= op < 256:
        raise ProgramError(f"op={op} does not fit the opcode byte")
    if not 0 <= rnd <= 4:
        raise ProgramError(f"rnd={rnd}; the contract defines 0..4")
    if not 0 <= imm < (1 << 32):
        raise ProgramError(f"imm={imm} does not fit 32 bits")
    imm |= (((rd >> 4) & 1) << REG_HI_SHIFT["rd"]
            | ((ra >> 4) & 1) << REG_HI_SHIFT["ra"]
            | ((rb >> 4) & 1) << REG_HI_SHIFT["rb"]
            | ((rc >> 4) & 1) << REG_HI_SHIFT["rc"])
    return (op | ((rd & 0xF) << 8) | ((ra & 0xF) << 12)
            | ((rb & 0xF) << 16) | ((rc & 0xF) << 20)
            | (rnd << 24) | (int(bool(ka)) << 27) | (int(bool(kb)) << 28)
            | (int(bool(kc)) << 29) | (int(bool(kx)) << 30)
            | (int(bool(ctrl)) << 31)
            | (imm << 32))


def decode(word):
    """-> dict. Field names match docs/SEQUENCER.md.

    `rd`, `ra`, `rb` and `rc` come back as whole five-bit register
    numbers, low four bits from the operand field and the fifth from
    `imm`. That is the right view for an ALU instruction, which is
    what reads registers; a CONTROL instruction reads at most `ra`,
    and `REPEAT` reads none at all and owns the whole of `imm` as its
    trip count - so the canonicity rules in `validate()` are written
    against the raw encoding rather than against this merged view,
    which is the one place the distinction matters.
    """
    imm = (word >> 32) & 0xFFFFFFFF
    return {
        "op": word & 0xFF,
        "rd": ((word >> 8) & 0xF) | ((imm >> REG_HI_SHIFT["rd"] & 1) << 4),
        "ra": ((word >> 12) & 0xF) | ((imm >> REG_HI_SHIFT["ra"] & 1) << 4),
        "rb": ((word >> 16) & 0xF) | ((imm >> REG_HI_SHIFT["rb"] & 1) << 4),
        "rc": ((word >> 20) & 0xF) | ((imm >> REG_HI_SHIFT["rc"] & 1) << 4),
        "rnd": (word >> 24) & 0x7,
        "ka": bool((word >> 27) & 1),
        "kb": bool((word >> 28) & 1),
        "kc": bool((word >> 29) & 1),
        "kx": bool((word >> 30) & 1),
        "ctrl": bool((word >> 31) & 1),
        "imm": imm,
    }


def decode_raw(word):
    """The four operand fields as the ENCODING holds them - four bits
    each, with no fifth bit merged in from `imm`.

    `validate()` needs this for control instructions. `REPEAT`'s `imm`
    is wholly a trip count, so a trip count of 0xffffffff sets all four
    of the register high bits without naming a single register, and a
    canonicity check written against `decode()`'s merged view would
    refuse the very program docs/SEQUENCER.md uses to explain why the
    worst-case instruction bound exists.
    """
    return {"rd": (word >> 8) & 0xF, "ra": (word >> 12) & 0xF,
            "rb": (word >> 16) & 0xF, "rc": (word >> 20) & 0xF}


# Which byte of `imm` carries each operand's constant index under `kx`,
# in a, b, c order: imm[7:0], imm[15:8], imm[23:16].
#
# The reserved window above them was imm[31:24] until revision 2 took
# imm[27:24] for the register high bits, so it is now imm[31:28] - four
# bits that nothing reads, still there for the counter-indexed form
# docs/ATLAS.md keeps asking about. Narrowing it does NOT weaken the
# version guard: an older loader refuses all eight, so it refuses every
# revision-2 program that names a register above 15 or an index through
# `kx`, which is the behaviour a compatibility rule is for.
KX_SHIFT = (0, 8, 16)
KX_RESERVED = 0xF000_0000


def sources(d):
    """The three operand sources of a decoded ALU instruction, as
    (index, is_const) triples in a, b, c order.

    Without `kx` an operand's 4-bit field is a register number, or a
    constant index when its `k` bit is set - so a program addresses
    sixteen constants whatever `n_consts` says, which is the wall
    docs/ENCLOSE.md hit. With `kx` the constant indices come from
    `imm[7:0]`, `imm[15:8]` and `imm[23:16]` instead and reach 255;
    an operand whose `k` bit is clear still names a register through
    its own field, exactly as before.
    """
    out = []
    for field, flag, shift in (("ra", "ka", KX_SHIFT[0]),
                               ("rb", "kb", KX_SHIFT[1]),
                               ("rc", "kc", KX_SHIFT[2])):
        if d[flag]:
            out.append((((d["imm"] >> shift) & 0xFF) if d["kx"]
                        else d[field], True))
        else:
            out.append((d[field], False))
    return out


# ---- a small assembler, for tests and for writing programs by hand ---

def alu(op, rd, ra=0, rb=0, rc=0, rnd=sf.RND_RNE, ka=False, kb=False,
        kc=False, kx=False):
    """One ALU instruction.

    `ra`/`rb`/`rc` are register numbers, or CONSTANT INDICES where the
    matching `k` flag is set - the same calling convention either way.
    With `kx` an index may reach 255 and this packs it into its byte of
    `imm`, zeroing the 4-bit field it came from, which is what the
    loader's canonicity rule demands.

    A register reaches 31 since revision 2; a constant index in the
    PLAIN form still reaches only 15, because there its index lives in
    the four-bit operand field and the fifth bit is a register's, not
    an index's. Refused here by name rather than left to `validate()`
    to discover as a stray high bit.
    """
    for v, flag, name in ((ra, ka, "ra"), (rb, kb, "rb"), (rc, kc, "rc")):
        if flag and not kx and not 0 <= v < KADDR_PLAIN:
            raise ProgramError(
                f"{name} names constant {v} without kx, and the plain form "
                f"addresses 0..{KADDR_PLAIN - 1} - the fifth bit of an "
                f"operand field is a register's high bit, not an index's")
    if not kx:
        return encode(op, rd, ra, rb, rc, rnd, ka, kb, kc, ctrl=False)
    imm = 0
    fields = []
    for v, flag, shift in ((ra, ka, KX_SHIFT[0]), (rb, kb, KX_SHIFT[1]),
                           (rc, kc, KX_SHIFT[2])):
        if flag:
            if not 0 <= v < KADDR_KX:
                raise ProgramError(
                    f"constant index {v} outside 0..{KADDR_KX - 1}")
            imm |= v << shift
            fields.append(0)
        else:
            fields.append(v)
    return encode(op, rd, fields[0], fields[1], fields[2], rnd,
                  ka, kb, kc, ctrl=False, imm=imm, kx=True)


def halt():
    return encode(HALT, ctrl=True)


def repeat(trip):
    if trip < 1:
        raise ProgramError("repeat trip count must be at least 1")
    return encode(REPEAT, ctrl=True, imm=trip)


def endrep():
    return encode(ENDREP, ctrl=True)


def deposit(ra):
    return encode(DEPOSIT, ra=ra, ctrl=True)


def setact(ra):
    return encode(SETACT, ra=ra, ctrl=True)


def actall():
    return encode(ACTALL, ctrl=True)


# ---- the program object ---------------------------------------------

class Program:
    """Header, constant bank, instruction stream - the bytes the host
    DMAs to the tile and can read back to attest what ran.

    Since revision 2 the header's first reserved word is `flags`, and
    bit 0 - `BANK_EXT` - says the image carries NO constant section:
    `n_consts` still says how many constants the program addresses and
    every run supplies exactly that many values through `bank`. One
    image per positive, loaded once, with the levers riding as data.
    """

    def __init__(self, fmt: FpFormat, insns, consts=(), max_deposits=1,
                 flags=0, n_consts=None):
        self.fmt = fmt
        self.insns = list(insns)
        self.consts = list(consts)
        self.max_deposits = max_deposits
        self.flags = flags
        if flags & FLAG_BANK_EXT:
            if self.consts:
                raise ProgramError(
                    "a BANK_EXT program carries no constant section, so "
                    "consts must be empty - the values arrive per run")
            self._n_consts = 0 if n_consts is None else n_consts
        else:
            if n_consts is not None and n_consts != len(self.consts):
                raise ProgramError(
                    f"n_consts={n_consts} but the image carries "
                    f"{len(self.consts)} constants")
            self._n_consts = len(self.consts)
        self.validate()

    @property
    def n_consts(self):
        """How many constants the program ADDRESSES - the header field.

        The same number whether the values ride in the image or arrive
        per run, which is the point: `BANK_EXT` moves where the
        constants live and changes nothing about what the instruction
        stream may name."""
        return self._n_consts

    @property
    def bank_ext(self):
        return bool(self.flags & FLAG_BANK_EXT)

    # -- validation ----------------------------------------------------

    def _check_operands(self, pc, d):
        """The operand half of an ALU instruction's refusals: the
        constant indices are inside the bank, and the encoding of those
        indices is the only one that spells this operation.

        The canonicity rule is the one docs/SEQUENCER.md already
        states - *any field an instruction does not read being non-zero
        is refused* - applied to the fields `kx` brings into play. An
        ALU instruction has no immediate, so without `kx` all 32 bits
        of `imm` must be zero. With `kx` set:

        * an operand whose `k` bit is set takes its index from `imm`,
          so its 4-bit register field is not read and must be zero;
        * an operand whose `k` bit is clear names a register, so its
          byte of `imm` is not read and must be zero;
        * `imm[31:28]` is read by nothing and must be zero, which is
          what keeps it available for a later form;
        * and `kx` itself selects nothing when no `k` bit is set, so
          that combination is refused too - it would otherwise be a
          second spelling of an ordinary three-register instruction.

        Revision 2 adds one application of the SAME rule, not a new
        one. `imm[27:24]` are the fifth bits of `rd`, `ra`, `rb` and
        `rc`; an operand whose `k` bit is set names a CONSTANT, so its
        register high bit is read by nothing and must be zero - under
        `kx` too, where the index is a byte of `imm` and the high bit
        is not part of it. `rd` is always a register, so `imm[24]` is
        free on every ALU instruction.

        What is deliberately NOT refused: a `kx` instruction whose
        indices all happen to be below sixteen. That is a second
        spelling of a plain `k` instruction, and the model tolerates it
        for the same reason it tolerates a non-zero `rb` on a unary
        ABS - the rule is about fields the ENCODING does not read, not
        about which of two legal encodings a compiler chose.
        """
        if d["kx"] and not (d["ka"] or d["kb"] or d["kc"]):
            raise ProgramError(
                f"[{pc}] kx is set and no operand names a constant, so "
                f"the bit selects nothing and the instruction has a "
                f"second encoding with kx clear")
        if d["imm"] & KX_RESERVED:
            raise ProgramError(
                f"[{pc}] imm[31:28] is reserved and must be zero")
        if not d["kx"] and (d["imm"] & ~REG_HI_MASK & 0xFFFFFFFF):
            raise ProgramError(
                f"[{pc}] an ALU instruction without kx has no immediate, "
                f"so bits 63:32 must be zero apart from the register high "
                f"bits imm[27:24] - otherwise the same operation has many "
                f"encodings and a readback hash stops being a hash of the "
                f"program")

        for key, flag in (("ra", "ka"), ("rb", "kb"), ("rc", "kc")):
            if d[flag] and (d["imm"] >> REG_HI_SHIFT[key]) & 1:
                raise ProgramError(
                    f"[{pc}] {key} names a constant, so its register high "
                    f"bit imm[{REG_HI_SHIFT[key]}] is read by nothing and "
                    f"must be zero")

        for key, flag, shift in (("ra", "ka", KX_SHIFT[0]),
                                 ("rb", "kb", KX_SHIFT[1]),
                                 ("rc", "kc", KX_SHIFT[2])):
            byte = (d["imm"] >> shift) & 0xFF
            if d["kx"] and d[flag]:
                if d[key]:
                    raise ProgramError(
                        f"[{pc}] {key} names constant {byte} through imm "
                        f"under kx, so the {key} field must be zero and "
                        f"it is {d[key]}")
                idx = byte
            elif d["kx"]:
                if byte:
                    raise ProgramError(
                        f"[{pc}] {key} names a register, so its byte of "
                        f"imm is not read and must be zero")
                continue
            elif d[flag]:
                idx = d[key]
            else:
                continue
            if idx >= self.n_consts:
                raise ProgramError(
                    f"[{pc}] {key} names constant {idx} but the bank "
                    f"holds {self.n_consts}")

    def validate(self):
        if not 0 <= self.max_deposits <= MAX_DEPOSITS:
            raise ProgramError(
                f"max_deposits={self.max_deposits}, cap {MAX_DEPOSITS}")
        for k in self.consts:
            if not 0 <= k < (1 << self.fmt.width):
                raise ProgramError("constant does not fit the format")

        depth = 0
        # `mult` tracks how many times the instruction at the current
        # nesting level can execute, so the worst-case instruction
        # count is known before the program runs rather than
        # discovered by waiting.
        mult = [1]
        worst = 0

        for pc, word in enumerate(self.insns):
            d = decode(word)
            worst += mult[-1]

            if not d["ctrl"]:
                self._check_operands(pc, d)
                if d["rnd"] > 4:
                    raise ProgramError(f"[{pc}] rnd={d['rnd']} is reserved")
                continue

            code = d["op"]
            if code not in CTRL_NAMES:
                raise ProgramError(f"[{pc}] unknown control code {code}")

            # Every field a control instruction does not read must be
            # zero. Two reasons: attestation, as above; and the natural
            # RTL shares one operand-fetch mux across control and ALU
            # instructions, so a stray ka on a DEPOSIT would index a
            # constant bank that may be empty.
            #
            # Written against the RAW operand fields, not decode()'s
            # merged five-bit view. Since revision 2 the fifth bit of
            # each register lives in imm[27:24], and `REPEAT` owns the
            # whole of `imm` as its trip count - so `repeat 0xffffffff`
            # sets all four of those bits while naming no register at
            # all, and checking the merged view would refuse the one
            # program docs/SEQUENCER.md uses to explain why the
            # worst-case instruction bound has to exist. The register
            # high bits are checked instead through IMM_ALLOWED below,
            # which says per code exactly which bits of `imm` are read.
            used = {HALT: (), REPEAT: ("imm",), ENDREP: (),
                    DEPOSIT: ("ra",), SETACT: ("ra",), ACTALL: ()}[code]
            raw = decode_raw(word)
            for field in ("rd", "ra", "rb", "rc"):
                if field not in used and raw[field]:
                    raise ProgramError(
                        f"[{pc}] {CTRL_NAMES[code]} does not read {field}, "
                        f"so it must be zero")
            for field in ("rnd", "ka", "kb", "kc", "kx"):
                if d[field]:
                    raise ProgramError(
                        f"[{pc}] {CTRL_NAMES[code]} does not read {field}, "
                        f"so it must be zero")
            if d["imm"] & ~IMM_ALLOWED[code] & 0xFFFFFFFF:
                raise ProgramError(
                    f"[{pc}] {CTRL_NAMES[code]} reads only "
                    f"imm & {IMM_ALLOWED[code]:#010x}, so imm="
                    f"{d['imm']:#010x} sets a bit it does not read")

            if code == REPEAT:
                if d["imm"] == 0:
                    raise ProgramError(
                        f"[{pc}] repeat 0 is not a loop; omit it")
                depth += 1
                if depth > MAX_LOOP_DEPTH:
                    raise ProgramError(
                        f"[{pc}] loops nest deeper than {MAX_LOOP_DEPTH}")
                mult.append(mult[-1] * d["imm"])
            elif code == ENDREP:
                depth -= 1
                if depth < 0:
                    raise ProgramError(f"[{pc}] endrep without repeat")
                mult.pop()
            elif code == ACTALL and depth > 0:
                # P3 holds only if nothing inside a loop can reactivate
                # a lane. Refusing the program is the cheapest way to
                # keep that true.
                raise ProgramError(
                    f"[{pc}] actall inside a loop would make the "
                    f"all-lanes-done early exit observable")
            elif code == HALT and depth > 0:
                # The subtle one, and the reason P3 needs a second
                # rule rather than one.
                #
                # HALT is the only instruction whose effect is not
                # per-lane, so the active mask cannot gate it. With
                # every lane inactive, a loop body containing a HALT is
                # NOT a no-op: skipping the loop continues the program,
                # entering it stops the program. Those differ in
                # deposits, in flags, and in the final register file.
                #
                # It breaks P2 with it, because the deposit count of
                # lane i then depends on whether some OTHER lane was
                # still active - which makes the answer depend on how
                # the library split lanes across compute units.
                #
                # A fuzz over 40,000 valid programs found divergence
                # only ever through this instruction, and none at all
                # once it is refused here.
                raise ProgramError(
                    f"[{pc}] halt inside a loop: the active mask cannot "
                    f"gate it, so the all-lanes-done early exit would "
                    f"be observable")

            if worst > MAX_INSTRUCTIONS:
                raise ProgramError(
                    f"[{pc}] worst-case instruction count exceeds "
                    f"{MAX_INSTRUCTIONS}; the loop bounds are finite but "
                    f"not a bound")

        if depth != 0:
            raise ProgramError(f"{depth} loop(s) left open at the end")
        if worst > MAX_INSTRUCTIONS:
            raise ProgramError(
                f"worst-case instruction count {worst} exceeds "
                f"{MAX_INSTRUCTIONS}")

    def digest(self, bank=None):
        """sha256 of the exact bytes a device would be given.

        The program is loaded through the AXI master and can be read
        back, so what executed can be attested rather than assumed -
        but only if the encoding is canonical, which is what the
        must-be-zero checks above are for.

        `bank` extends that to a BANK_EXT program, whose image is only
        half of what ran: the hash covers the image bytes followed by
        the bank bytes, so what ran is ONE hash of program and data
        together. It is the model's side of `cft_program_digest`."""
        import hashlib
        h = hashlib.sha256(self.to_bytes())
        if bank is not None:
            h.update(self.bank_bytes(bank))
        return h.hexdigest()

    # -- serialisation -------------------------------------------------

    def bank_bytes(self, bank):
        """A run's constant bank as the device receives it: dense,
        format-width, little-endian - the same layout the image's
        constant section has, which is what lets FETCH read one the way
        it reads the other."""
        self._check_bank(bank)
        ebytes = self.fmt.width // 8
        return b"".join(k.to_bytes(ebytes, "little") for k in bank)

    def _check_bank(self, bank):
        """The refusals a bank has to carry. A BANK_EXT program cannot
        run without one and a self-contained program cannot run with
        one: either way the run would compute on constants nobody
        agreed on, which is the failure the whole feature exists to
        make impossible."""
        if not self.bank_ext:
            if bank is not None:
                raise ProgramError(
                    "this program carries its own constants, so a bank "
                    "would be a second, contradictory source for them")
            return
        if bank is None:
            raise ProgramError(
                f"a BANK_EXT program carries no constants; supply the "
                f"{self.n_consts} the header declares")
        if len(bank) != self.n_consts:
            raise ProgramError(
                f"bank holds {len(bank)} constants, the header declares "
                f"{self.n_consts}")
        for k in bank:
            if not 0 <= k < (1 << self.fmt.width):
                raise ProgramError("bank constant does not fit the format")

    def to_bytes(self):
        ebytes = self.fmt.width // 8
        out = struct.pack("<8I", MAGIC, VERSION, len(self.insns),
                          self.n_consts, self.max_deposits,
                          PREC_CODE[self.fmt.name], self.flags, 0)
        # A BANK_EXT image is header then instructions, with no constant
        # section at all - so it is exactly 32 + 8 * n_insns bytes
        # whatever n_consts says, and `self.consts` is empty.
        for k in self.consts:
            out += k.to_bytes(ebytes, "little")
        for w in self.insns:
            out += struct.pack("<Q", w)
        return out

    @classmethod
    def from_bytes(cls, data):
        if len(data) < HEADER_WORDS * 4:
            raise ProgramError("shorter than a header")
        magic, ver, n_insns, n_consts, maxdep, prec, flags, rsv1 = \
            struct.unpack("<8I", data[:HEADER_WORDS * 4])
        if magic != MAGIC:
            raise ProgramError(f"bad magic {magic:#010x}, expected "
                               f"{MAGIC:#010x}")
        if ver != VERSION:
            raise ProgramError(f"program version {ver}, this loader "
                               f"speaks {VERSION}")
        # The header's first reserved word became `flags` at revision 2;
        # everything above bit 0 of it, and the whole of the remaining
        # reserved word, stay must-be-zero. Instruction bit 30 is
        # refused for being reserved; header words cannot be laxer than
        # instruction bits.
        if flags & ~FLAGS_KNOWN & 0xFFFFFFFF:
            raise ProgramError(
                f"header flags {flags:#010x} set a bit this loader does "
                f"not know; flags[31:1] are reserved and must be zero")
        if rsv1:
            raise ProgramError("reserved header words must be zero")
        name = next((k for k, v in PREC_CODE.items() if v == prec), None)
        if name is None:
            raise ProgramError(f"precision code {prec} is not on the ladder")
        fmt = FORMATS[name]
        ebytes = fmt.width // 8
        off = HEADER_WORDS * 4
        n_stored = 0 if flags & FLAG_BANK_EXT else n_consts
        want = off + n_stored * ebytes + n_insns * INSN_BYTES
        if len(data) != want:
            raise ProgramError(
                f"{len(data)} bytes, header describes {want} - a program "
                f"is exactly its header, constants and instructions, so "
                f"anything else is a different program")
        consts = [int.from_bytes(data[off + i * ebytes:
                                      off + (i + 1) * ebytes], "little")
                  for i in range(n_stored)]
        off += n_stored * ebytes
        insns = [struct.unpack("<Q", data[off + i * INSN_BYTES:
                                          off + (i + 1) * INSN_BYTES])[0]
                 for i in range(n_insns)]
        return cls(fmt, insns, consts, maxdep, flags=flags,
                   n_consts=n_consts)


# ---- execution -------------------------------------------------------

class Result:
    __slots__ = ("deposits", "flags", "status", "regs", "active",
                 "counts", "insns_executed")

    def __init__(self, deposits, flags, status, regs, active, counts,
                 insns_executed):
        self.deposits = deposits            # n * max_deposits values
        self.flags = flags                  # sticky IEEE flags
        self.status = status                # bus / sequencer faults
        self.regs = regs                    # final register file
        self.active = active                # final active mask
        self.counts = counts                # deposits made, per lane
        self.insns_executed = insns_executed

    def state(self):
        """Everything observable. Used to prove the early exit changes
        nothing but the instruction count."""
        return (self.deposits, self.flags, self.status, self.regs,
                self.active, self.counts)


def run(prog: Program, a, b, c=None, bank=None, early_exit=True,
        insn_budget=None, n_active=None):
    """Execute `prog` over len(a) lanes.

    The three input streams initialise r0, r1 and r2 - the same three
    the elementwise engine already reads, so a sequencer run needs no
    new input path in the hardware. Registers r3..r31 start at +0.

    `bank` is a BANK_EXT program's constants, supplied per run: exactly
    `prog.n_consts` format-width values, dense and in index order, the
    way the device receives them through BANK_PTR. It is refused if it
    is missing, the wrong size, or handed to a program that carries its
    own constant section - the model's side of `cft_program_run_bank`.

    `n_active` is the caller's real element count. Lanes at or beyond
    it start INACTIVE and stay that way unless a program reactivates
    them, which is how beat padding is made harmless.

    That matters more here than it does for an elementwise op. There, a
    zero-filled tail is quiet for every opcode and the padding is
    genuinely free. A sequencer program is arbitrary, so no padding
    VALUE can be relied on to stay quiet through thirty iterations of
    an unknown map: padding lanes would push exceptions into the sticky
    word, deposit into slots past the caller's buffer, and hold
    `any(active)` true so the early exit never fires. The lane index is
    known to the hardware and so is n, so the mask costs one comparator
    and removes the whole problem.

    early_exit=False forces every loop to run its full trip count. The
    results must be identical either way; that is P3 in
    docs/SEQUENCER.md and test_seq.py checks it.
    """
    fmt = prog.fmt
    prog._check_bank(bank)
    consts = list(bank) if prog.bank_ext else prog.consts
    n = len(a)
    if len(b) != n or (c is not None and len(c) != n):
        raise ValueError("input streams differ in length")
    if c is None:
        c = [0] * n
    if n_active is None:
        n_active = n
    if not 0 <= n_active <= n:
        raise ValueError(f"n_active={n_active} outside 0..{n}")

    zero = sf.zero_bits(fmt, 0)
    mask = (1 << fmt.width) - 1
    regs = [[zero] * NREG for _ in range(n)]
    for i in range(n):
        # Registers are format-width; the hardware truncates and so
        # does this, rather than carrying a wider value that could
        # never have been loaded.
        regs[i][0] = a[i] & mask
        regs[i][1] = b[i] & mask
        regs[i][2] = c[i] & mask
    active = [i < n_active for i in range(n)]
    counts = [0] * n
    deposits = [zero] * (n * prog.max_deposits)
    flags = 0
    status = 0
    executed = 0

    def src(lane, spec):
        # `consts` and not `prog.consts`: under BANK_EXT the values came
        # with the RUN, and the whole point of the feature is that the
        # image is the same bytes for every one of them.
        idx, is_const = spec
        return consts[idx] if is_const else regs[lane][idx]

    pc = 0
    stack = []                      # (body_start_pc, iterations_left)
    while pc < len(prog.insns):
        if insn_budget is not None and executed >= insn_budget:
            raise RuntimeError("instruction budget exhausted")
        d = decode(prog.insns[pc])
        executed += 1

        if not d["ctrl"]:
            # The three operand sources are a property of the
            # instruction, not of the lane, so they are resolved once
            # per instruction - which is also what the hardware does,
            # since a constant cannot change during a run.
            sa, sb, sc = sources(d)
            for i in range(n):
                if not active[i]:
                    continue        # no write, no deposit, and no flags
                res, fl = sf.compute(
                    fmt, d["op"],
                    src(i, sa), src(i, sb), src(i, sc),
                    d["rnd"])
                regs[i][d["rd"]] = res
                flags |= fl
            pc += 1
            continue

        code = d["op"]
        if code == HALT:
            break
        if code == REPEAT:
            if d["imm"] == 0 or (early_exit and not any(active)):
                # Skip to the matching endrep. Nothing inside can
                # reactivate a lane or halt the program (validate()
                # guarantees both), so the body is a no-op.
                #
                # A trip count of zero takes the same path. validate()
                # rejects it, so no valid program arrives here - but
                # the obvious RTL tests imm == 0 and skips, and a model
                # that ran the body once instead would disagree with
                # the hardware about a program neither should accept.
                pc = _matching_endrep(prog.insns, pc) + 1
                continue
            stack.append([pc + 1, d["imm"]])
            pc += 1
            continue
        if code == ENDREP:
            frame = stack[-1]
            frame[1] -= 1
            if frame[1] > 0 and not (early_exit and not any(active)):
                pc = frame[0]
            else:
                stack.pop()
                pc += 1
            continue
        if code == DEPOSIT:
            for i in range(n):
                if not active[i]:
                    continue
                if counts[i] >= prog.max_deposits:
                    status |= STATUS_DEPOSIT_OVERFLOW
                    continue
                deposits[i * prog.max_deposits + counts[i]] = \
                    regs[i][d["ra"]]
                counts[i] += 1
            pc += 1
            continue
        if code == SETACT:
            for i in range(n):
                if active[i]:
                    mag = regs[i][d["ra"]] & ~fmt.sign_mask
                    active[i] = mag != 0
            pc += 1
            continue
        if code == ACTALL:
            active = [True] * n
            pc += 1
            continue
        raise ProgramError(f"[{pc}] unknown control code {code}")

    return Result(deposits, flags, status, regs, active, counts, executed)


def random_program(fmt, rng, nconst=3, allow_halt_in_loop=False,
                   extended=False, wide_regs=False):
    """A random program, for fuzzing. Returns (insns, consts).

    It lives here rather than in a test file because two different
    checks need the same generator - the model's own property tests and
    the cross-check against libcft's C implementation - and a fuzz
    corpus that differs between them would compare two things neither
    of which is the thing under test.

    `allow_halt_in_loop` emits the one construction validate() refuses,
    so a test can confirm the rule is load-bearing by watching the fuzz
    break without it.

    `extended` adds the two 2026-09-07 additions - `IMUL` in the opcode
    pool, and `kx` on some of the constant-naming instructions with a
    bank deep enough that indices above fifteen are reachable. It is
    OFF by default and draws nothing from `rng` when off, so the corpus
    every existing bench generates from a given seed is the corpus it
    generated before: `tb/test_seq_core.py`'s fuzz suite compares the
    RTL against the model over the same 62 programs it always did, and
    the new forms arrive as an additional arm rather than as a
    reshuffle of the old one.

    `wide_regs` is revision 2's arm, on the same terms: with it the
    register draws reach r31 instead of r15, and without it they draw
    from exactly the sixteen they always did. A draw from a WIDER range
    consumes the same one value from `rng`, so an existing seed's
    corpus is unchanged bit for bit either way - but only because the
    range is a parameter rather than `NREG`, which moved. That is the
    whole reason this argument exists instead of the constant being
    read directly.
    """
    nreg = NREG if wide_regs else NREG_REV1
    ops = [OP_FMA_, OP_ADD_, OP_SUB_, OP_MUL_, OP_ABS_,
           OP_MIN_, OP_MAXNUM_, OP_CMPLT_, OP_SELECT_, OP_IXOR_]
    if extended:
        ops.append(OP_IMUL_)
        # Deep enough that a kx index of 16 or more is drawn often, and
        # small enough that a program image stays a few kilobytes at
        # fp256.
        nconst = max(nconst, KADDR_PLAIN + 24)
    insns = []
    depth = 0
    for _ in range(rng.randint(4, 22)):
        pick = rng.random()
        if pick < 0.45:
            op = rng.choice(ops)
            # choose the constant flags first, then draw each operand
            # from the range that flag makes legal - otherwise most
            # instructions name a constant the bank does not hold and
            # the fuzz spends its time being rejected
            kb = rng.random() < 0.3
            kc = rng.random() < 0.2
            # kx is only meaningful when some operand names a constant,
            # and the loader refuses it otherwise, so it is drawn only
            # then. The reach is the whole bank, which is the point.
            kx = extended and (kb or kc) and rng.random() < 0.6
            top = nconst if kx else min(nconst, KADDR_PLAIN)
            insns.append(alu(
                op,
                rd=rng.randrange(nreg),
                ra=rng.randrange(nreg),
                rb=rng.randrange(top) if kb else rng.randrange(nreg),
                rc=rng.randrange(top) if kc else rng.randrange(nreg),
                rnd=rng.randrange(5), kb=kb, kc=kc, kx=kx))
        elif pick < 0.6 and depth < MAX_LOOP_DEPTH:
            insns.append(repeat(rng.randint(1, 4)))
            depth += 1
        elif pick < 0.7 and depth > 0:
            insns.append(endrep())
            depth -= 1
        elif pick < 0.8:
            insns.append(deposit(rng.randrange(nreg)))
        elif pick < 0.92:
            insns.append(setact(rng.randrange(nreg)))
        elif depth == 0:
            insns.append(actall())
        elif allow_halt_in_loop:
            insns.append(halt())
    insns += [endrep()] * depth
    insns.append(halt())
    pool = [sf.zero_bits(fmt), sf.one_bits(fmt), sf.max_normal_bits(fmt)]
    if nconst <= len(pool):
        consts = pool[:nconst]
    else:
        # A deep bank has to hold DISTINGUISHABLE values, or an index
        # error reads a constant equal to the one it should have read
        # and the fuzz sees nothing. Every entry past the pool is a
        # different bit pattern, and the low bits carry the index so a
        # mis-indexed IMUL is loud.
        consts = pool + [(i << 4) | 0x9 for i in range(len(pool), nconst)]
    return insns, consts


def random_inputs(fmt, rng, n):
    """Operands weighted toward the values that make opcodes differ:
    signed zeros, infinities, both NaN kinds, the subnormal edge."""
    pool = [sf.zero_bits(fmt), sf.zero_bits(fmt, 1), sf.one_bits(fmt),
            sf.inf_bits(fmt), sf.inf_bits(fmt, 1), sf.qnan_bits(fmt),
            sf.snan_bits(fmt, 1), sf.min_subnormal_bits(fmt),
            sf.max_normal_bits(fmt)]
    return [rng.choice(pool) if rng.random() < 0.5
            else rng.getrandbits(fmt.width) for _ in range(n)]


# Opcode aliases, so the generator above reads as a list of operations
# rather than a list of attribute lookups.
OP_FMA_, OP_ADD_, OP_SUB_, OP_MUL_ = sf.OP_FMA, sf.OP_ADD, sf.OP_SUB, sf.OP_MUL
OP_ABS_, OP_MIN_, OP_MAXNUM_ = sf.OP_ABS, sf.OP_MIN, sf.OP_MAXNUM
OP_CMPLT_, OP_SELECT_, OP_IXOR_ = sf.OP_CMPLT, sf.OP_SELECT, sf.OP_IXOR
OP_IMUL_ = sf.OP_IMUL


def _matching_endrep(insns, pc):
    depth = 0
    for j in range(pc, len(insns)):
        d = decode(insns[j])
        if not d["ctrl"]:
            continue
        if d["op"] == REPEAT:
            depth += 1
        elif d["op"] == ENDREP:
            depth -= 1
            if depth == 0:
                return j
    raise ProgramError("unbalanced loop reached execution")
