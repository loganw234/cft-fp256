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

# Slots of per-lane SCRATCH memory, revision 3's R4. A power of two, so
# the indexed forms can reduce modulo it with a mask rather than a
# division - which is what the hardware does and therefore what the
# contract says. It is the lane's: lane i's slot s is reachable by lane
# i alone, which is what keeps P2's "no slot is reachable from two
# indices" true of the scratch as it is of the deposit buffer.
#
# 256 is the tile's build parameter, published in CAPS2[3:0] as log2.
# The model is not one tile - but unlike max_deposits, whose model cap
# is deliberately larger than any tile's, this depth is part of the
# INSTRUCTION's meaning: STX/LDX reduce modulo it, so a model with a
# different depth would compute different answers rather than merely
# accept larger programs.
SCRATCH_D = 256
SCRATCH_MASK = SCRATCH_D - 1

# The fifth bit of each register field, by position in `imm`. Written
# as a table rather than four shifts because the RTL decode, the
# assembler and three refusal rules all read the same four bits, and
# four is exactly enough copies of a magic number to get one wrong.
REG_HI_SHIFT = {"rd": 24, "ra": 25, "rb": 26, "rc": 27}
REG_HI_MASK = 0x0F00_0000

# How many constants an instruction can ADDRESS. Without `kx` an
# operand's constant index is its own 4-bit field, so sixteen; with
# `kx` it is a byte of `imm` plus a ninth bit (revision 3's R7), so
# 512 - which is `KMEM_D`, the capacity rtl/cft_seq.sv's header check
# permits. `n_consts` above this is not refused (it never was above
# sixteen either): the constants past it are simply unaddressable, and
# every index is checked against `n_consts` anyway.
#
# It was 256 between 2026-09-07 and revision 3, which is the number
# `KADDR_KX8` keeps: a device whose CAPS[7] is clear addresses eight
# bits, and the loader refuses an index at or past this on one, by
# name, because that tile's operand mux would read the low eight and
# silently address the wrong constant.
KADDR_PLAIN = 16
KADDR_KX8 = 256
KADDR_KX = 512

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
#
# SCRATCH_IO (revision 3, R5) says the header's second reserved word is
# `scratch_io` rather than a reserved zero: [15:0] slots read into every
# lane before the first instruction, [31:16] slots written out after the
# last deposit. With the bit CLEAR that word must still be zero, which
# is what a revision-2 tile enforces and therefore the guard - a tile
# that predates the flag throws the image back at the header rather
# than running it with the scratch uninitialised.
#
# SCRATCH_STRICT (revision 4, R8) says an indexed scratch access at or
# past SCRATCH_D is to be REPORTED rather than reduced modulo it. With
# the bit clear the modulo stands, so every program built before this
# revision runs unchanged and this file still defines what it computes.
# The bit is the program asking for the stricter contract, and a tile
# that cannot honour it refuses the image rather than running it with
# the old meaning - which is the same guard SCRATCH_IO needed and for
# the same reason.
FLAG_BANK_EXT = 1 << 0
FLAG_SCRATCH_IO = 1 << 1
FLAG_SCRATCH_STRICT = 1 << 2
FLAGS_KNOWN = FLAG_BANK_EXT | FLAG_SCRATCH_IO | FLAG_SCRATCH_STRICT

# control codes (instruction bit 31 set)
HALT, REPEAT, ENDREP, DEPOSIT, SETACT, ACTALL = 0, 1, 2, 3, 4, 5
# Revision 3's R4: the per-lane scratch, by static slot and by index.
# Neither is arithmetic - no rounding attribute, no flags - and both
# are masked by the lane's active bit, a store because it is a write
# and a load because it writes `rd`. That is what keeps an
# all-inactive loop body a no-op and P3 true.
STL, LDL, STX, LDX = 6, 7, 8, 9
CTRL_NAMES = {HALT: "halt", REPEAT: "repeat", ENDREP: "endrep",
              DEPOSIT: "deposit", SETACT: "setact", ACTALL: "actall",
              STL: "stl", LDL: "ldl", STX: "stx", LDX: "ldx"}

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
#   STL, LDL               read imm[23:0] as the SLOT, plus the high
#                          bit of the one register they name - ra's
#                          for the store, rd's for the load.
#   STX, LDX               take the slot from a register instead, so
#                          imm[23:0] is read by nothing and must be
#                          zero; the high bits they may set are the
#                          two registers they name.
SCRATCH_SLOT_MASK = 0x00FF_FFFF
IMM_ALLOWED = {
    HALT: 0,
    REPEAT: 0xFFFF_FFFF,
    ENDREP: 0,
    DEPOSIT: 1 << REG_HI_SHIFT["ra"],
    SETACT: 1 << REG_HI_SHIFT["ra"],
    ACTALL: 0,
    STL: SCRATCH_SLOT_MASK | (1 << REG_HI_SHIFT["ra"]),
    LDL: SCRATCH_SLOT_MASK | (1 << REG_HI_SHIFT["rd"]),
    STX: (1 << REG_HI_SHIFT["ra"]) | (1 << REG_HI_SHIFT["rb"]),
    LDX: (1 << REG_HI_SHIFT["rd"]) | (1 << REG_HI_SHIFT["rb"]),
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
# Revision 4's R8, and deliberately the bit after the deposit's: the two
# mean the same kind of thing, a lane asking for a slot that is not
# there, and they are reported the same way. Not an IEEE flag, for the
# reason given above the deposit bit.
STATUS_SCRATCH_RANGE = 1 << 5


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
# imm[27:24] for the register high bits, and revision 3 takes
# imm[30:28] for the NINTH bit of each index - ka's, kb's and kc's, the
# same construction as the register high bits one nibble down. What is
# left is `imm[31]` alone, and it stays reserved-must-be-zero on
# purpose: it is the cheap version guard for whatever comes after this,
# and the largest positive in atlas-engine's corpus needs 464 of the
# 512.
#
# Narrowing the window does NOT weaken the guard for what is already
# shipped: an older loader refuses all of imm[31:24], so it refuses
# every revision-2 program that names a register above 15 and every
# revision-3 program that names a constant above 255.
KX_SHIFT = (0, 8, 16)
KX9_SHIFT = {"ra": 28, "rb": 29, "rc": 30}
KX9_MASK = 0x7000_0000
KX_RESERVED = 0x8000_0000


def sources(d):
    """The three operand sources of a decoded ALU instruction, as
    (index, is_const) triples in a, b, c order.

    Without `kx` an operand's 4-bit field is a register number, or a
    constant index when its `k` bit is set - so a program addresses
    sixteen constants whatever `n_consts` says, which is the wall
    docs/ENCLOSE.md hit. With `kx` the constant indices come from
    `imm[7:0]`, `imm[15:8]` and `imm[23:16]` instead, each with a
    NINTH bit at `imm[28]`, `imm[29]` and `imm[30]` since revision 3,
    so they reach 511; an operand whose `k` bit is clear still names a
    register through its own field, exactly as before.
    """
    out = []
    for field, flag, shift in (("ra", "ka", KX_SHIFT[0]),
                               ("rb", "kb", KX_SHIFT[1]),
                               ("rc", "kc", KX_SHIFT[2])):
        if d[flag]:
            if d["kx"]:
                idx = ((d["imm"] >> shift) & 0xFF) | (
                    ((d["imm"] >> KX9_SHIFT[field]) & 1) << 8)
            else:
                idx = d[field]
            out.append((idx, True))
        else:
            out.append((d[field], False))
    return out


# ---- a small assembler, for tests and for writing programs by hand ---

def alu(op, rd, ra=0, rb=0, rc=0, rnd=sf.RND_RNE, ka=False, kb=False,
        kc=False, kx=False):
    """One ALU instruction.

    `ra`/`rb`/`rc` are register numbers, or CONSTANT INDICES where the
    matching `k` flag is set - the same calling convention either way.
    With `kx` an index may reach 511 and this packs it into its byte of
    `imm` plus the ninth bit at `KX9_SHIFT`, zeroing the 4-bit field it
    came from, which is what the loader's canonicity rule demands.

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
    for v, flag, shift, name in ((ra, ka, KX_SHIFT[0], "ra"),
                                 (rb, kb, KX_SHIFT[1], "rb"),
                                 (rc, kc, KX_SHIFT[2], "rc")):
        if flag:
            if not 0 <= v < KADDR_KX:
                raise ProgramError(
                    f"constant index {v} outside 0..{KADDR_KX - 1}")
            imm |= (v & 0xFF) << shift
            imm |= ((v >> 8) & 1) << KX9_SHIFT[name]
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


def stl(ra, slot):
    """scratch[slot] := ra, for the lane, masked by its active bit."""
    _check_slot(slot)
    return encode(STL, ra=ra, ctrl=True, imm=slot)


def ldl(rd, slot):
    """rd := scratch[slot], a masked register write."""
    _check_slot(slot)
    return encode(LDL, rd=rd, ctrl=True, imm=slot)


def stx(ra, rb):
    """scratch[rb mod SCRATCH_D] := ra. The slot comes from the low
    log2(SCRATCH_D) bits of rb's BIT PATTERN read as an unsigned
    integer, which is where the atlas emitter keeps its loop
    counters."""
    return encode(STX, ra=ra, rb=rb, ctrl=True)


def ldx(rd, rb):
    """rd := scratch[rb mod SCRATCH_D]."""
    return encode(LDX, rd=rd, rb=rb, ctrl=True)


def _check_slot(slot):
    """A STATIC slot past the depth is refused, by name, exactly as a
    constant index past the bank is - the instruction says which slot
    and the answer is knowable before the run. An INDEXED slot is not
    refused, it is reduced: `rb` is data, so refusing it would mean
    refusing a program for a value it might compute."""
    if not 0 <= slot < SCRATCH_D:
        raise ProgramError(
            f"scratch slot {slot} outside 0..{SCRATCH_D - 1}")
    return slot


# ---- the program object ---------------------------------------------

class Program:
    """Header, constant bank, instruction stream - the bytes the host
    DMAs to the tile and can read back to attest what ran.

    Since revision 2 the header's first reserved word is `flags`, and
    bit 0 - `BANK_EXT` - says the image carries NO constant section:
    `n_consts` still says how many constants the program addresses and
    every run supplies exactly that many values through `bank`. One
    image per positive, loaded once, with the levers riding as data.

    Revision 3 spends the header's remaining reserved word the same
    way. Under `flags` bit 1 - `SCRATCH_IO` - it is `scratch_io`:
    `[15:0]` slots preloaded into every lane's scratch before the first
    instruction and `[31:16]` slots read back out of it after the last
    deposit. With the bit clear the word must be zero, which is exactly
    what a revision-2 tile enforces and therefore the version guard.
    """

    def __init__(self, fmt: FpFormat, insns, consts=(), max_deposits=1,
                 flags=0, n_consts=None, n_scratch_in=0, n_scratch_out=0):
        self.fmt = fmt
        self.insns = list(insns)
        self.consts = list(consts)
        self.max_deposits = max_deposits
        self.flags = flags
        self.n_scratch_in = n_scratch_in
        self.n_scratch_out = n_scratch_out
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

    @property
    def scratch_io(self):
        return bool(self.flags & FLAG_SCRATCH_IO)

    @property
    def scratch_io_word(self):
        """The header's second word as the device reads it."""
        return (self.n_scratch_in & 0xFFFF) | (
            (self.n_scratch_out & 0xFFFF) << 16)

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
                f"[{pc}] imm[31] is reserved and must be zero")
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
            hi9 = (d["imm"] >> KX9_SHIFT[key]) & 1
            if d["kx"] and d[flag]:
                if d[key]:
                    raise ProgramError(
                        f"[{pc}] {key} names constant {byte} through imm "
                        f"under kx, so the {key} field must be zero and "
                        f"it is {d[key]}")
                idx = byte | (hi9 << 8)
            elif d["kx"]:
                if byte:
                    raise ProgramError(
                        f"[{pc}] {key} names a register, so its byte of "
                        f"imm is not read and must be zero")
                # Revision 3's ninth index bit is read only under `kx`
                # for an operand whose `k` flag is set. On an operand
                # that names a REGISTER it is an unread field, the same
                # rule the byte below it obeys.
                if hi9:
                    raise ProgramError(
                        f"[{pc}] {key} names a register, so its ninth "
                        f"constant-index bit imm[{KX9_SHIFT[key]}] is "
                        f"read by nothing and must be zero")
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

        # The header's second word, checked exactly as the tile checks
        # it: an unknown flag bit, a count past the depth, or a
        # non-zero `scratch_io` without the flag. The last of the three
        # is what makes a revision-2 tile the guard for R5 - it refuses
        # a non-zero reserved[1] at the header, so an image built for
        # this revision is thrown back rather than run with the scratch
        # never loaded.
        if self.flags & ~FLAGS_KNOWN & 0xFFFFFFFF:
            raise ProgramError(
                f"header flags {self.flags:#010x} set a bit this loader "
                f"does not know; the known ones are BANK_EXT and "
                f"SCRATCH_IO")
        for name, v in (("n_scratch_in", self.n_scratch_in),
                        ("n_scratch_out", self.n_scratch_out)):
            if not 0 <= v <= 0xFFFF:
                raise ProgramError(
                    f"{name}={v} does not fit its half of scratch_io")
            if not self.scratch_io:
                if v:
                    raise ProgramError(
                        f"{name}={v} without flags.SCRATCH_IO: with the "
                        f"bit clear the header's second word is reserved "
                        f"and must be zero")
            elif v > SCRATCH_D:
                raise ProgramError(
                    f"{name}={v} past the {SCRATCH_D} slots a lane owns")

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
                    DEPOSIT: ("ra",), SETACT: ("ra",), ACTALL: (),
                    # R4's four. STL reads ra and the slot; LDL writes
                    # rd and reads the slot; the indexed pair take the
                    # slot from rb instead, so imm[23:0] is read by
                    # nothing there and IMM_ALLOWED refuses it.
                    STL: ("ra",), LDL: ("rd",),
                    STX: ("ra", "rb"), LDX: ("rd", "rb")}[code]
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

            if code in (STL, LDL):
                # A STATIC slot past the depth is refused by name, as a
                # constant index past the bank is: the instruction says
                # which slot, so the answer is knowable here rather
                # than at the tile's header check. STX/LDX are NOT
                # refused - their slot is data, and the reduction
                # modulo the depth is part of the contract.
                slot = d["imm"] & SCRATCH_SLOT_MASK
                if slot >= SCRATCH_D:
                    raise ProgramError(
                        f"[{pc}] {CTRL_NAMES[code]} names scratch slot "
                        f"{slot} but a lane owns {SCRATCH_D}")

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

    def scratch_bytes(self, values):
        """A run's scratch block as the device receives it: dense,
        format-width, little-endian, lane-major - the same layout the
        bank and the image's constant section have, for the same
        reason (one parser reads them all)."""
        ebytes = self.fmt.width // 8
        return b"".join(v.to_bytes(ebytes, "little") for v in values)

    def _check_scratch_in(self, scratch_in, n):
        """The refusals the scratch-in block carries, which are the
        bank's refusals in the same shape: a program that declares one
        cannot run without it, and a program that declares none cannot
        run with it. Byte counts match exactly or the run is refused -
        a buffer whose length nobody agreed on is a run whose lanes
        started somewhere nobody agreed on."""
        want = (self.n_scratch_in if self.scratch_io else 0) * n
        if not want:
            if scratch_in is not None:
                raise ProgramError(
                    "this program declares no scratch input, so a "
                    "scratch_in block would be values no instruction "
                    "can have been compiled to read")
            return
        if scratch_in is None:
            raise ProgramError(
                f"this program declares n_scratch_in="
                f"{self.n_scratch_in}; supply {want} values for {n} lanes")
        if len(scratch_in) != want:
            raise ProgramError(
                f"scratch_in holds {len(scratch_in)} values, the header "
                f"declares {self.n_scratch_in} a lane over {n} lanes = "
                f"{want}")
        for v in scratch_in:
            if not 0 <= v < (1 << self.fmt.width):
                raise ProgramError(
                    "scratch_in value does not fit the format")

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
                          PREC_CODE[self.fmt.name], self.flags,
                          self.scratch_io_word)
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
        magic, ver, n_insns, n_consts, maxdep, prec, flags, word7 = \
            struct.unpack("<8I", data[:HEADER_WORDS * 4])
        if magic != MAGIC:
            raise ProgramError(f"bad magic {magic:#010x}, expected "
                               f"{MAGIC:#010x}")
        if ver != VERSION:
            raise ProgramError(f"program version {ver}, this loader "
                               f"speaks {VERSION}")
        # The header's first reserved word became `flags` at revision 2
        # and its second became `scratch_io` at revision 3. Everything
        # above the known flag bits is still must-be-zero, and so is the
        # whole of `scratch_io` while `SCRATCH_IO` is clear. Instruction
        # bit 31 is refused for being reserved; header words cannot be
        # laxer than instruction bits.
        if flags & ~FLAGS_KNOWN & 0xFFFFFFFF:
            raise ProgramError(
                f"header flags {flags:#010x} set a bit this loader does "
                f"not know; flags[31:2] are reserved and must be zero")
        if not (flags & FLAG_SCRATCH_IO) and word7:
            raise ProgramError(
                f"header word 7 is {word7:#010x} without flags.SCRATCH_IO; "
                f"with the bit clear it is reserved and must be zero")
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
                   n_consts=n_consts,
                   n_scratch_in=word7 & 0xFFFF,
                   n_scratch_out=(word7 >> 16) & 0xFFFF)


# ---- execution -------------------------------------------------------

class Result:
    __slots__ = ("deposits", "flags", "status", "regs", "active",
                 "counts", "insns_executed", "scratch", "scratch_out")

    def __init__(self, deposits, flags, status, regs, active, counts,
                 insns_executed, scratch=None, scratch_out=None):
        self.deposits = deposits            # n * max_deposits values
        self.flags = flags                  # sticky IEEE flags
        self.status = status                # bus / sequencer faults
        self.regs = regs                    # final register file
        self.active = active                # final active mask
        self.counts = counts                # deposits made, per lane
        self.insns_executed = insns_executed
        # The per-lane scratch at the end of the run (revision 3, R4),
        # and the block a SCRATCH_IO program hands back through
        # SCRATCH_OUT_PTR: lane i's slot s at i * n_scratch_out + s,
        # lane-major and dense, the same shape the deposit buffer has.
        # `scratch_out` is [] for a program that declares none, which is
        # what the device writes to that pointer: nothing.
        self.scratch = scratch if scratch is not None else []
        self.scratch_out = scratch_out if scratch_out is not None else []

    def state(self):
        """Everything observable. Used to prove the early exit changes
        nothing but the instruction count.

        The scratch joins it at revision 3 for the same reason the
        register file is here: an all-inactive loop body that stored
        into a slot would be observable through the scratch-out block
        even where it moved no deposit, so P3's fuzz has to see it."""
        return (self.deposits, self.flags, self.status, self.regs,
                self.active, self.counts, self.scratch, self.scratch_out)


def run(prog: Program, a, b, c=None, bank=None, scratch_in=None,
        early_exit=True, insn_budget=None, n_active=None):
    """Execute `prog` over len(a) lanes.

    The three input streams initialise r0, r1 and r2 - the same three
    the elementwise engine already reads, so a sequencer run needs no
    new input path in the hardware. Registers r3..r31 start at +0, and
    so does every one of the lane's SCRATCH_D scratch slots - except
    the first `prog.n_scratch_in` of them, which a SCRATCH_IO program
    takes from `scratch_in`.

    `scratch_in` is lane-major and dense: lane i's slot s is element
    `i * prog.n_scratch_in + s`, `len(a) * n_scratch_in` values in all,
    the way the device receives them through SCRATCH_IN_PTR. It is
    refused if it is missing, the wrong size, or handed to a program
    that declares no scratch input. The matching block on the way out
    is `Result.scratch_out`.

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

    prog._check_scratch_in(scratch_in, n)

    zero = sf.zero_bits(fmt, 0)
    mask = (1 << fmt.width) - 1
    # Revision 4's R8. Read once: the flag is the image's, so it cannot
    # change under a running program, and reading it per access would
    # invite someone to make it per lane - which would be a contract that
    # depends on data rather than on the image.
    strict = bool(prog.flags & FLAG_SCRATCH_STRICT)
    regs = [[zero] * NREG for _ in range(n)]
    for i in range(n):
        # Registers are format-width; the hardware truncates and so
        # does this, rather than carrying a wider value that could
        # never have been loaded.
        regs[i][0] = a[i] & mask
        regs[i][1] = b[i] & mask
        regs[i][2] = c[i] & mask
    # The scratch, one array of SCRATCH_D slots per lane, +0 everywhere
    # a run begins. Slots start at +0 for the same reason a deposit
    # slot no lane wrote reads +0: a run whose untouched storage kept
    # whatever was there before would not be bit-exact between two
    # machines.
    scratch = [[zero] * SCRATCH_D for _ in range(n)]
    nsin = prog.n_scratch_in if prog.scratch_io else 0
    if nsin:
        # Lane-major and dense, and PADDING LANES RECEIVE NOTHING: a
        # lane at or past the caller's element count is not the
        # caller's, so the tail of the buffer is not read into it.
        for i in range(min(n, n_active)):
            for s in range(nsin):
                scratch[i][s] = scratch_in[i * nsin + s] & mask
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
        if code in (STL, LDL, STX, LDX):
            # R4. A store is a register write for P3's purposes and a
            # load writes rd, so both are masked by the active bit and
            # an all-inactive loop body stays a no-op. Neither is
            # arithmetic: no rounding attribute is read and no flag is
            # raised, which is why they cost the verification surface
            # of a control code rather than of an opcode.
            static = code in (STL, LDL)
            slot = (d["imm"] & SCRATCH_SLOT_MASK) if static else None
            for i in range(n):
                if not active[i]:
                    continue
                if not static:
                    # The indexed slot is rb's BIT PATTERN read as an
                    # unsigned integer. Without FLAG_SCRATCH_STRICT it is
                    # reduced modulo the depth, which is what every
                    # program written before revision 4 means and so what
                    # this file must keep computing for them.
                    #
                    # With the flag, an index at or past the depth is
                    # REPORTED instead: the access is suppressed and the
                    # run continues, exactly as a deposit past
                    # max_deposits is. That is what makes the depth
                    # portable - a program inside its declared
                    # scratch_used computes the same answer at every
                    # depth, and one outside it is told rather than
                    # quietly given a different number.
                    idx = regs[i][d["rb"]]
                    if strict and idx >= SCRATCH_D:
                        status |= STATUS_SCRATCH_RANGE
                        if code == LDX:
                            # +0, the same thing an untouched slot reads
                            # back as; never a stale register, which
                            # would make the result depend on what the
                            # lane happened to hold.
                            regs[i][d["rd"]] = zero
                        continue
                    slot = idx & SCRATCH_MASK
                if code in (STL, STX):
                    scratch[i][slot] = regs[i][d["ra"]]
                else:
                    regs[i][d["rd"]] = scratch[i][slot]
            pc += 1
            continue
        raise ProgramError(f"[{pc}] unknown control code {code}")

    # The scratch-out block, written after the last deposit of a lane
    # block and laid out exactly as the scratch-in block is. It is not
    # masked by the active bit - it is a drain, like the deposit
    # drain, and a lane that converged early still has state worth
    # carrying to the next call. Padding lanes write nothing, so their
    # slots stay +0.
    nsout = prog.n_scratch_out if prog.scratch_io else 0
    scratch_out = [zero] * (n * nsout)
    for i in range(min(n, n_active)):
        for s in range(nsout):
            scratch_out[i * nsout + s] = scratch[i][s]

    return Result(deposits, flags, status, regs, active, counts, executed,
                  scratch, scratch_out)


def random_program(fmt, rng, nconst=3, allow_halt_in_loop=False,
                   extended=False, wide_regs=False, scratch=False):
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

    `scratch` is revision 3's arm, and it is the strictest form of the
    same discipline: rather than take a slice of the `pick` chain -
    which would move every existing threshold and reshuffle the corpus
    outright - it is an EXTRA instruction appended after the chain, so
    the sequence of draws that produces a revision-1 or revision-2
    corpus is untouched to the value. Off, `scratch and ...`
    short-circuits and nothing is drawn at all.
    """
    nreg = NREG if wide_regs else NREG_REV1
    # Slots the fuzz uses. A handful of low ones so stores and loads
    # actually COLLIDE - a corpus that scattered its slots over 256
    # would spend its time reading +0 out of untouched storage - plus
    # the highest slot, which is the one an off-by-one in the address
    # decode reaches past.
    slots = [0, 1, 2, 3, 7, SCRATCH_D - 1]
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
        # R4's four, appended BESIDE the chain above rather than
        # inside it. All four are legal at any loop depth: a store is
        # masked by the active bit exactly as a register write is, so
        # neither of P3's two rules (ACTALL, HALT) has an analogue
        # here.
        if scratch and rng.random() < 0.4:
            kind = rng.randrange(4)
            if kind == 0:
                insns.append(stl(rng.randrange(nreg), rng.choice(slots)))
            elif kind == 1:
                insns.append(ldl(rng.randrange(nreg), rng.choice(slots)))
            elif kind == 2:
                insns.append(stx(rng.randrange(nreg), rng.randrange(nreg)))
            else:
                insns.append(ldx(rng.randrange(nreg), rng.randrange(nreg)))
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
