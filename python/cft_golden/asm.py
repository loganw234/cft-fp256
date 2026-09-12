# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""The `.cfta` text form: assembler, disassembler, and the revision-3
encoder they are written against.

docs/PROGRAMS.md is the specification of the text form;
docs/SEQUENCER.md and its "Revision 2 (2026-09-08)" and "Revision 3
(2026-09-08, evening)" sections are the encoding. This module is the
reference implementation of both, and `host/tools/cft-asm.c` is held
byte-for-byte to it.

**Why this file carries its own encoder.** `seq.py` is the definition
of correct for the program model, and it moves one revision at a time
on its own lane. Revision 2 widened the register fields to five bits
(the fifth of each in `imm[27:24]`) and turned the header's
`reserved[0]` into `flags`, whose bit 0 is `BANK_EXT`; revision 3 adds
a per-lane scratch memory with four control codes, turns
`reserved[1]` into `scratch_io` behind `flags` bit 1, and gives each
constant index a ninth bit in `imm[30:28]` under `kx`. This file was
written to the revision-3 contract from the start, before the model
carried it; `seq.py` has since landed revision 3 as well (`NREG = 32`,
`SCRATCH_D = 256`, the four control codes, `FLAG_SCRATCH_IO` and
`KX9_SHIFT`), so the two now overlap on everything. And
`python/tests/test_asm.py` pins the two together where they overlap -
a program that stays inside what `seq.py` can express must encode to
`seq.encode`'s exact words and run identically in `seq.run`.

So: where this file and `seq.py` disagree about a program `seq.py` can
express, THIS FILE IS WRONG. The rule was written for a period when a
program might be outside what the model could express; the model has
caught up, so today there is no such program and the rule has no
second clause - which is where it should stay until the next
revision opens one.

The text form, in one paragraph. One instruction a line; `;` starts a
comment; names are case-insensitive; numbers are decimal or `0x` hex.
`.format` and `.deposits` are required and `.format` comes first;
`.bank external` declares a program whose constants arrive per run;
`.const NAME = value` appends to the bank; `.reg NAME = rN` names a
register; `.slot NAME = N` names a scratch slot; `.scratch N` declares
the scratch depth the program assumes and `.scratch in N` /
`.scratch out M` the per-run block it wants carried in and out. An ALU
line is a mnemonic (with an optional rounding suffix) followed by the
destination and the operands the opcode reads, in `ra, rb, rc` field
order; the control lines are `repeat N` / `endrep`, `deposit rA`,
`setact rA`, `actall`, `halt`, `stl rA, SLOT`, `ldl rD, SLOT`,
`stx rA, rB` and `ldx rD, rB`.
"""

import hashlib
import re
import struct

from .formats import FORMATS, PREC_CODE, FpFormat
from .seqflags import FLAG_BANK_EXT, FLAG_SCRATCH_IO, names as flag_names
from . import chars
from . import softfloat as sf

# ---- the image, revision 3 -------------------------------------------

MAGIC = 0x50544643        # "CFTP" little-endian
VERSION = 1               # the PROGRAM version; VERSION guards the CSR
                          # register map and steps there, not here
HEADER_WORDS = 8
HEADER_BYTES = HEADER_WORDS * 4
INSN_BYTES = 8

# R1: each lane owns 32 registers. The low four bits of each field stay
# where they were; the fifth bits live in imm[27:24].
NREG = 32
REG_FIELD = 16            # what the four-bit operand field alone reaches

# R3: header word 6 (bytes 24..27) is `flags`; bit 0 is BANK_EXT.
# R5: bit 1 is SCRATCH_IO, and word 7 (bytes 28..31) - `reserved[1]`
# until revision 3 - is `scratch_io`: [15:0] in, [31:16] out, and zero
# unless the flag is set.
# Numbering from .seqflags. The subset is this ASSEMBLER's own and is
# deliberately smaller than the loader's: seq.py implements R8's
# SCRATCH_STRICT and this cannot yet emit it, so an image asking for
# it is refused here rather than assembled into something no tile
# will load.
FLAGS_KNOWN = FLAG_BANK_EXT | FLAG_SCRATCH_IO
FLAGS_RESERVED = ~FLAGS_KNOWN & 0xFFFFFFFF

MAX_LOOP_DEPTH = 4
MAX_INSTRUCTIONS = 1 << 40
MAX_DEPOSITS = 1 << 20

# How many constants an instruction can ADDRESS: sixteen through the
# four-bit operand field, 512 through a byte of `imm` plus the ninth
# bit in imm[30:28] under `kx` (R7).
KADDR_PLAIN = 16
KADDR_KX = 512

# R4: the per-lane scratch. `SCRATCH_D` is a build parameter of the
# tile and not part of the program model, so a SOURCE declares the
# depth it assumes with `.scratch N` and the assembler refuses a static
# slot at or past it; 256 is the depth revision 3 builds. The slot of
# a STL/LDL is imm[23:0], so a static slot cannot exceed that field
# whatever a device publishes.
SCRATCH_D_DEFAULT = 256
SCRATCH_D_MAX = 1 << 24
SLOT_MASK = 0x00FFFFFF
# Each half of `scratch_io` is sixteen bits wide.
SCRATCH_IO_MAX = 0xFFFF

(HALT, REPEAT, ENDREP, DEPOSIT, SETACT, ACTALL,
 STL, LDL, STX, LDX) = range(10)
CTRL_NAMES = {HALT: "halt", REPEAT: "repeat", ENDREP: "endrep",
              DEPOSIT: "deposit", SETACT: "setact", ACTALL: "actall",
              STL: "stl", LDL: "ldl", STX: "stx", LDX: "ldx"}
CTRL_CODES = {v: k for k, v in CTRL_NAMES.items()}
SCRATCH_CODES = (STL, LDL, STX, LDX)

# What each control code READS, which is the whole of its encoding
# rule: the register fields it names, and whether imm[23:0] is a
# scratch slot. Everything not named here must be zero - the register
# fields, their high bits in imm[27:24], `rnd`, `ka`/`kb`/`kc`, `kx`
# and imm[31:24] - which is docs/SEQUENCER.md's reserved-field rule
# applied once per code rather than restated per code.
#
# REPEAT is the exception and is not really one: it names no register,
# so it reads `imm` WHOLE as its trip count and none of imm[27:24] is
# a register's high bit there.
CTRL_USE = {
    HALT:    ((),           False),
    REPEAT:  ((),           False),
    ENDREP:  ((),           False),
    DEPOSIT: (("ra",),      False),
    SETACT:  (("ra",),      False),
    ACTALL:  ((),           False),
    STL:     (("ra",),      True),      # scratch[imm] := ra
    LDL:     (("rd",),      True),      # rd := scratch[imm]
    STX:     (("ra", "rb"), False),     # scratch[rb mod D] := ra
    LDX:     (("rd", "rb"), False),     # rd := scratch[rb mod D]
}

# Which byte of `imm` carries each operand's constant index under `kx`,
# and where that index's ninth bit lives (R7).
KX_SHIFT = (0, 8, 16)
KX9_SHIFT = (28, 29, 30)
# imm[27:24] are the four register high bits, in rd, ra, rb, rc order;
# imm[31] is read by nothing at all and must be zero - it is the cheap
# version guard for whatever comes after revision 3.
RHI_SHIFT = {"rd": 24, "ra": 25, "rb": 26, "rc": 27}
IMM_RESERVED = 0x80000000


class AsmError(ValueError):
    """A source the assembler refuses, or an image the disassembler
    cannot read. Both are ProgramError's job in seq.py; the assembler
    keeps its own type so a test can tell a refusal from a bug."""


# ---- the opcode table ------------------------------------------------
#
# The MNEMONICS are not written here: they come from the model's own
# `sf.OP_NAMES`, exactly as cft-asm.c takes them from `cft_op_name`.
# Two tables of the same strings is one table plus a way to drift, and
# a name typed twice has been wrong here before.
#
# What IS written here is which operand FIELDS each opcode reads, which
# neither table carries. It follows `softfloat.steer` and the arity of
# `SIMPLE_IMPL`'s entries:
#
#   FMA    d = a*b + c      a, b, c
#   ADD    d = a + c        a, c      (b is not read - it is steered
#   SUB    d = a - c        a, c       to 1.0 inside the pipeline)
#   MUL    d = a * b        a, b
#   SELECT d = c ? a : b    a, b, c
#
# and everything else is binary on (a, b) or unary on (a).
A, B, C = "ra", "rb", "rc"
OP_FIELDS = {
    sf.OP_FMA: (A, B, C),
    sf.OP_ADD: (A, C),
    sf.OP_SUB: (A, C),
    sf.OP_MUL: (A, B),
    sf.OP_ABS: (A,),
    sf.OP_NEG: (A,),
    sf.OP_COPYSIGN: (A, B),
    sf.OP_MIN: (A, B),
    sf.OP_MAX: (A, B),
    sf.OP_MINNUM: (A, B),
    sf.OP_MAXNUM: (A, B),
    sf.OP_SELECT: (A, B, C),
    sf.OP_CMPLT: (A, B),
    sf.OP_CMPLE: (A, B),
    sf.OP_CMPEQ: (A, B),
    sf.OP_IAND: (A, B),
    sf.OP_IOR: (A, B),
    sf.OP_IXOR: (A, B),
    sf.OP_IADD: (A, B),
    sf.OP_ISUB: (A, B),
    sf.OP_ISHL: (A, B),
    sf.OP_ISHR: (A, B),
    sf.OP_ICMPLT: (A, B),
    sf.OP_RECIP_SEED: (A,),
    sf.OP_RSQRT_SEED: (A,),
    sf.OP_IMUL: (A, B),
}
# Opcode -> mnemonic, for exactly the opcodes a sequencer program may
# name. 24, 25, 28 and 29 have names in the shared opcode table
# (`sum`, `dot`, `sumsq`, `sumabs`) and are REDUCTIONS: cft_reduce
# issues them, the ALU does not implement them, and `sf.compute`
# answers the canonical quiet NaN with `invalid`. They are reachable
# from the text form only through the numeric `opNN` escape, which is
# what keeps a disassembly of one re-assemblable without making it look
# like an operation this ISA has.
OP_NAMES = {op: sf.OP_NAMES[op] for op in OP_FIELDS}
OP_BY_NAME = {name: op for op, name in OP_NAMES.items()}

RND_BY_NAME = {name: code for code, name in sf.RND_NAMES.items()}
RND_NAMES = dict(sf.RND_NAMES)


# ---- encoding --------------------------------------------------------

def encode(op, rd=0, ra=0, rb=0, rc=0, rnd=sf.RND_RNE,
           ka=False, kb=False, kc=False, ctrl=False, imm=0, kx=False):
    """One 64-bit instruction word, revision 3.

    `rd`/`ra`/`rb`/`rc` are FIVE-BIT register numbers: the low four bits
    go to the field they always went to and the fifth to its bit of
    `imm[27:24]`. Where an operand names a CONSTANT the caller passes
    the index in the same argument and the register high bit is not
    written, because the loader refuses one there - the field is not
    read, so it must be zero.

    `imm` is whatever the instruction reads as an immediate: the trip
    count on REPEAT, the scratch slot on STL/LDL, the packed constant
    indices under `kx`, nothing otherwise. The register high bits are
    OR-ed into it here rather than being the caller's problem.
    """
    fields = {"rd": rd, "ra": ra, "rb": rb, "rc": rc}
    kflag = {"rd": False, "ra": ka, "rb": kb, "rc": kc}
    if not 0 <= op < 256:
        raise AsmError(f"op={op} does not fit the opcode byte")
    if not 0 <= rnd <= 4:
        raise AsmError(f"rnd={rnd}; the contract defines 0..4")
    if not 0 <= imm < (1 << 32):
        raise AsmError(f"imm={imm} does not fit 32 bits")
    word = (op | (rnd << 24) | (int(bool(ka)) << 27) | (int(bool(kb)) << 28)
            | (int(bool(kc)) << 29) | (int(bool(kx)) << 30)
            | (int(bool(ctrl)) << 31))
    shift = {"rd": 8, "ra": 12, "rb": 16, "rc": 20}
    for name, v in fields.items():
        limit = (KADDR_KX if kx else KADDR_PLAIN) if kflag[name] else NREG
        if not 0 <= v < limit:
            raise AsmError(f"{name}={v} outside 0..{limit - 1}")
        if kflag[name] and kx:
            continue          # the index rides in imm; the field is zero
        word |= (v & 0xF) << shift[name]
        if v >> 4:
            if kflag[name]:
                raise AsmError(
                    f"{name} names constant {v}, which needs kx")
            imm |= 1 << RHI_SHIFT[name]
    if imm >> 32:
        raise AsmError("imm does not fit 32 bits")
    return word | (imm << 32)


def decode(word):
    """-> dict. The register fields are the FIVE-BIT values; `ra_lo` and
    friends are kept beside them because the refusals are stated about
    the raw fields ("the field must be zero"), not about the value."""
    imm = (word >> 32) & 0xFFFFFFFF
    d = {
        "op": word & 0xFF,
        "rnd": (word >> 24) & 0x7,
        "ka": bool((word >> 27) & 1),
        "kb": bool((word >> 28) & 1),
        "kc": bool((word >> 29) & 1),
        "kx": bool((word >> 30) & 1),
        "ctrl": bool((word >> 31) & 1),
        "imm": imm,
    }
    for name, shift in (("rd", 8), ("ra", 12), ("rb", 16), ("rc", 20)):
        lo = (word >> shift) & 0xF
        hi = (imm >> RHI_SHIFT[name]) & 1
        d[name + "_lo"] = lo
        d[name + "_hi"] = hi
        d[name] = lo | (hi << 4)
    return d


def sources(d):
    """The three operand sources of a decoded ALU instruction, as
    (index, is_const) triples in a, b, c order. Under `kx` an index is
    nine bits: a byte of `imm` and its ninth bit in imm[30:28] (R7)."""
    out = []
    for k, (field, flag) in enumerate((("ra", "ka"), ("rb", "kb"),
                                       ("rc", "kc"))):
        if d[flag]:
            if d["kx"]:
                idx = ((d["imm"] >> KX_SHIFT[k]) & 0xFF) | \
                      (((d["imm"] >> KX9_SHIFT[k]) & 1) << 8)
            else:
                idx = d[field + "_lo"]
            out.append((idx, True))
        else:
            out.append((d[field], False))
    return out


def alu(op, rd, ra=0, rb=0, rc=0, rnd=sf.RND_RNE, ka=False, kb=False,
        kc=False, kx=None):
    """One ALU instruction. `kx=None` selects the form the assembler
    would: indexed when any constant index is 16 or more, plain
    otherwise, which is the rule docs/PROGRAMS.md states."""
    idx = [(ra, ka), (rb, kb), (rc, kc)]
    if kx is None:
        kx = any(flag and v >= KADDR_PLAIN for v, flag in idx)
    imm = 0
    if kx:
        if not (ka or kb or kc):
            raise AsmError("kx with no constant operand selects nothing")
        for k, (v, flag) in enumerate(idx):
            if flag:
                if not 0 <= v < KADDR_KX:
                    raise AsmError(f"constant index {v} outside "
                                   f"0..{KADDR_KX - 1}")
                imm |= (v & 0xFF) << KX_SHIFT[k]
                imm |= (v >> 8) << KX9_SHIFT[k]
    return encode(op, rd, ra, rb, rc, rnd, ka, kb, kc, ctrl=False,
                  imm=imm, kx=kx)


def halt():
    return encode(HALT, ctrl=True)


def repeat(trip):
    if not 1 <= trip < (1 << 32):
        raise AsmError("repeat trip count must be 1..2^32-1")
    return encode(REPEAT, ctrl=True, imm=trip)


def endrep():
    return encode(ENDREP, ctrl=True)


def deposit(ra):
    return encode(DEPOSIT, ra=ra, ctrl=True)


def setact(ra):
    return encode(SETACT, ra=ra, ctrl=True)


def actall():
    return encode(ACTALL, ctrl=True)


def _slot_imm(slot):
    if not 0 <= slot <= SLOT_MASK:
        raise AsmError(f"scratch slot {slot} does not fit imm[23:0]")
    return slot


def stl(ra, slot):
    """`scratch[slot] := ra`. Reads `ra` and imm[23:0]."""
    return encode(STL, ra=ra, ctrl=True, imm=_slot_imm(slot))


def ldl(rd, slot):
    """`rd := scratch[slot]`. Writes `rd`, reads imm[23:0]."""
    return encode(LDL, rd=rd, ctrl=True, imm=_slot_imm(slot))


def stx(ra, rb):
    """`scratch[rb mod SCRATCH_D] := ra`. imm[23:0] must be zero."""
    return encode(STX, ra=ra, rb=rb, ctrl=True)


def ldx(rd, rb):
    """`rd := scratch[rb mod SCRATCH_D]`. imm[23:0] must be zero."""
    return encode(LDX, rd=rd, rb=rb, ctrl=True)


def infer_scratch_depth(insns, scratch_io=0, flags=0):
    """The depth a READBACK assumes: the smallest power of two, at
    least the default, that covers every static slot and both
    scratch-I/O counts.

    The depth is not in the image - `SCRATCH_D` is a build parameter of
    the tile, published in `CAPS2[3:0]` - so an image is legal against
    whatever depth the device has, and a reader that simply defaulted
    to 256 would refuse a perfectly good program written for a deeper
    tile. Both implementations infer the same number, and the
    disassembler writes it back as `.scratch N`, so the round trip
    holds.
    """
    need = 1
    for word in insns:
        d = decode(word)
        if d["ctrl"] and d["op"] in (STL, LDL):
            need = max(need, (d["imm"] & SLOT_MASK) + 1)
    if flags & FLAG_SCRATCH_IO:
        need = max(need, scratch_io & 0xFFFF, (scratch_io >> 16) & 0xFFFF)
    depth = SCRATCH_D_DEFAULT
    while depth < need:
        depth *= 2
    return depth


# ---- the image -------------------------------------------------------

class Image:
    """A program as bytes, plus the names the text form gave its parts.

    This is deliberately NOT seq.Program: it is the revision-3 image,
    it validates itself against the revision-3 loader's rules, and it
    knows about the bank and the scratch block the model reaches on its
    own schedule. `to_bytes()` is what a `.cftp` file holds and what
    `cft_program_load` is handed.

    `scratch_depth` is the depth the PROGRAM assumes - `.scratch N` in
    the source. It is not in the image (SCRATCH_D is a build parameter
    of the tile, published in CAPS2), so `from_bytes` infers the
    smallest depth that could have produced the image and the
    disassembler writes that same number back. What is in the image is
    `scratch_io`, and only when `flags.SCRATCH_IO` says so.
    """

    def __init__(self, fmt: FpFormat, insns, consts=(), max_deposits=1,
                 flags=0, const_names=None, reg_names=None,
                 scratch_depth=SCRATCH_D_DEFAULT, scratch_io=0,
                 slot_names=None):
        self.fmt = fmt
        self.insns = list(insns)
        self.consts = list(consts)
        self.max_deposits = max_deposits
        self.flags = flags
        self.scratch_depth = scratch_depth
        self.scratch_io = scratch_io
        self.const_names = list(const_names or [])
        self.reg_names = dict(reg_names or {})
        self.slot_names = dict(slot_names or {})
        self.validate()

    # -- properties ----------------------------------------------------

    @property
    def bank_external(self):
        return bool(self.flags & FLAG_BANK_EXT)

    @property
    def scratch_io_declared(self):
        return bool(self.flags & FLAG_SCRATCH_IO)

    @property
    def n_scratch_in(self):
        return self.scratch_io & 0xFFFF

    @property
    def n_scratch_out(self):
        return (self.scratch_io >> 16) & 0xFFFF

    def scratch_use(self):
        """-> (highest static slot or None, does it index?). What
        `cft-asm -i` reports and what `cft_program_info` calls
        `scratch_used`: one past the highest static slot, or the whole
        depth when the program reaches it through STX/LDX."""
        top, indexed = None, False
        for word in self.insns:
            d = decode(word)
            if not d["ctrl"]:
                continue
            if d["op"] in (STL, LDL):
                slot = d["imm"] & SLOT_MASK
                top = slot if top is None else max(top, slot)
            elif d["op"] in (STX, LDX):
                indexed = True
        return top, indexed

    @property
    def n_consts(self):
        """How many constants the program ADDRESSES. With BANK_EXT the
        image carries none of them and every run supplies exactly this
        many; without it, it is the length of the section on disk.

        `self.consts` holds that many entries either way - under
        BANK_EXT they are placeholders that never reach `to_bytes`,
        which keeps every index check written once."""
        return len(self.consts)

    @property
    def esz(self):
        return self.fmt.width // 8

    def features(self):
        """The feature bits this image needs a device to publish, as
        names, in CAPS bit order followed by CAPS2's: `kx` is CAPS[4],
        `REGS32` [5], `BANK_PTR` [6], `KX9` [7], `IMUL` [28], and then
        `SCRATCH` is CAPS2[4] and `SCRATCH_IO` CAPS2[5]. A tool prints
        these; `cft_program_load` refuses the image where CAPS is
        missing one."""
        want = set()
        for word in self.insns:
            d = decode(word)
            if d["ctrl"]:
                # Which control codes have a register to extend is
                # CTRL_USE's business; REPEAT's imm[25] is a bit of the
                # trip count and not a register's fifth bit.
                regs, _slot = CTRL_USE.get(d["op"], ((), False))
                for name in regs:
                    if d[name] >= REG_FIELD:
                        want.add("REGS32")
                if d["op"] in SCRATCH_CODES:
                    want.add("SCRATCH")
                continue
            if d["kx"]:
                want.add("kx")
                for idx, is_const in sources(d):
                    if is_const and idx >= 256:
                        want.add("KX9")
            if d["op"] == sf.OP_IMUL:
                want.add("IMUL")
            for name in ("rd", "ra", "rb", "rc"):
                if d[name + "_hi"]:
                    want.add("REGS32")
        if self.bank_external:
            want.add("BANK_PTR")
        if self.scratch_io_declared:
            want.add("SCRATCH_IO")
        return [f for f in ("kx", "REGS32", "BANK_PTR", "KX9", "IMUL",
                            "SCRATCH", "SCRATCH_IO")
                if f in want]

    # -- validation ----------------------------------------------------
    #
    # Everything the loader refuses, refused here, so a file that
    # assembles is a file that loads. The rules are docs/SEQUENCER.md's
    # "What the loader refuses" plus revision 2's two additions: the
    # register high bits obey the same not-read-so-must-be-zero rule as
    # every other field, and the header's flags word is checked like an
    # instruction's reserved bits.

    def _check_alu(self, pc, d):
        if d["rnd"] > 4:
            raise AsmError(f"[{pc}] rnd={d['rnd']} is reserved")
        if d["imm"] & IMM_RESERVED:
            raise AsmError(f"[{pc}] imm[31] is reserved and must be zero")
        if d["kx"] and not (d["ka"] or d["kb"] or d["kc"]):
            raise AsmError(
                f"[{pc}] kx is set and no operand names a constant, so the "
                f"bit selects nothing and the instruction has a second "
                f"encoding with kx clear")

        for k, (key, flag, shift) in enumerate(
                (("ra", "ka", KX_SHIFT[0]),
                 ("rb", "kb", KX_SHIFT[1]),
                 ("rc", "kc", KX_SHIFT[2]))):
            byte = (d["imm"] >> shift) & 0xFF
            ninth = (d["imm"] >> KX9_SHIFT[k]) & 1
            # R7: imm[30:28] are the ninth bits of ka's, kb's and kc's
            # indices, read only under kx for an operand whose k flag is
            # set. Anywhere else the bit is an unread field.
            if ninth and not (d["kx"] and d[flag]):
                raise AsmError(
                    f"[{pc}] imm[{KX9_SHIFT[k]}] is the ninth bit of "
                    f"{key}'s constant index, which is read only under kx "
                    f"for an operand that names a constant, so it must be "
                    f"zero")
            if d[flag]:
                # A constant operand reads neither the register high
                # bit nor - under kx - the four-bit field.
                if d[key + "_hi"]:
                    raise AsmError(
                        f"[{pc}] {key} names a constant, so its register "
                        f"high bit imm[{RHI_SHIFT[key]}] is not read and "
                        f"must be zero")
                if d["kx"]:
                    if d[key + "_lo"]:
                        raise AsmError(
                            f"[{pc}] {key} names constant "
                            f"{byte | (ninth << 8)} through imm under kx, "
                            f"so the {key} field must be zero and "
                            f"it is {d[key + '_lo']}")
                    idx = byte | (ninth << 8)
                else:
                    idx = d[key + "_lo"]
            else:
                if d["kx"] and byte:
                    raise AsmError(
                        f"[{pc}] {key} names a register, so its byte of imm "
                        f"is not read and must be zero")
                continue
            if idx >= self.n_consts:
                raise AsmError(
                    f"[{pc}] {key} names constant {idx} but the bank "
                    f"holds {self.n_consts}")
        if not d["kx"] and (d["imm"] & 0x00FFFFFF):
            raise AsmError(
                f"[{pc}] an ALU instruction without kx has no immediate "
                f"below imm[24], so those bits must be zero - otherwise "
                f"the same operation has many encodings and a readback "
                f"hash stops being a hash of the program")

    def _check_ctrl(self, pc, d):
        code = d["op"]
        if code not in CTRL_NAMES:
            raise AsmError(f"[{pc}] unknown control code {code}")
        name = CTRL_NAMES[code]
        # Every control code's encoding is CTRL_USE's two entries: the
        # register fields it names, and whether imm[23:0] is a scratch
        # slot. Everything else is a field the instruction does not
        # read, and must be zero. REPEAT is the exception: it names no
        # register, so it reads `imm` whole as its trip count and
        # imm[27:24] are count bits there rather than register high
        # bits.
        regs, slot = CTRL_USE[code]
        for field in ("rd", "ra", "rb", "rc"):
            if field not in regs and d[field + "_lo"]:
                raise AsmError(
                    f"[{pc}] {name} does not read {field}, so "
                    f"it must be zero")
        for field in ("rnd", "ka", "kb", "kc", "kx"):
            if d[field]:
                raise AsmError(
                    f"[{pc}] {name} does not read {field}, so "
                    f"it must be zero")
        if code != REPEAT:
            allowed = SLOT_MASK if slot else 0
            for field in regs:
                allowed |= 1 << RHI_SHIFT[field]
            if d["imm"] & ~allowed & 0xFFFFFFFF:
                raise AsmError(
                    f"[{pc}] {name} does not read imm beyond "
                    f"{'its slot and ' if slot else ''}its register high "
                    f"bit(s), so the rest of imm must be zero and imm is "
                    f"{d['imm']:#010x}")
        if slot:
            v = d["imm"] & SLOT_MASK
            if v >= self.scratch_depth:
                raise AsmError(
                    f"[{pc}] {name} names scratch slot {v} and the program "
                    f"declares a scratch of {self.scratch_depth} slots "
                    f"(.scratch N)")

    def validate(self):
        if self.fmt.name not in PREC_CODE:
            raise AsmError(f"{self.fmt.name} is not on the precision ladder")
        if not 0 <= self.max_deposits <= MAX_DEPOSITS:
            raise AsmError(
                f"max_deposits={self.max_deposits}, cap {MAX_DEPOSITS}")
        if self.flags & FLAGS_RESERVED:
            raise AsmError(
                f"header flags {self.flags:#010x}: only "
                f"{flag_names(FLAGS_KNOWN)} are defined and the rest are "
                f"reserved-must-be-zero")
        if self.n_consts > KADDR_KX:
            raise AsmError(
                f"{self.n_consts} constants; an index is nine bits under "
                f"kx, so the bank addresses at most {KADDR_KX}")
        if (self.scratch_depth & (self.scratch_depth - 1)) or \
                not 1 <= self.scratch_depth <= SCRATCH_D_MAX:
            raise AsmError(
                f"a scratch depth is a power of two in 1..{SCRATCH_D_MAX} "
                f"and this one is {self.scratch_depth}")
        # R5: `scratch_io` is meaningful only behind its flag, and with
        # the flag clear the word must be zero - the same rule the
        # header word carried when it was `reserved[1]`.
        if not self.scratch_io_declared and self.scratch_io:
            raise AsmError(
                f"header word 7 is {self.scratch_io:#010x} with SCRATCH_IO "
                f"clear; with the flag clear it must be zero")
        if not 0 <= self.scratch_io < (1 << 32):
            raise AsmError("scratch_io does not fit 32 bits")
        for what, count in (("in", self.n_scratch_in),
                            ("out", self.n_scratch_out)):
            if count > self.scratch_depth:
                raise AsmError(
                    f".scratch {what} {count} is more than the "
                    f"{self.scratch_depth} slots the program declares")
        for k in self.consts:
            if not 0 <= k < (1 << self.fmt.width):
                raise AsmError("constant does not fit the format")

        depth = 0
        mult = [1]
        worst = 0
        for pc, word in enumerate(self.insns):
            d = decode(word)
            worst += mult[-1]
            if not d["ctrl"]:
                self._check_alu(pc, d)
                continue
            self._check_ctrl(pc, d)
            code = d["op"]
            if code == REPEAT:
                if d["imm"] == 0:
                    raise AsmError(f"[{pc}] repeat 0 is not a loop; omit it")
                depth += 1
                if depth > MAX_LOOP_DEPTH:
                    raise AsmError(
                        f"[{pc}] loops nest deeper than {MAX_LOOP_DEPTH}")
                mult.append(mult[-1] * d["imm"])
            elif code == ENDREP:
                depth -= 1
                if depth < 0:
                    raise AsmError(f"[{pc}] endrep without repeat")
                mult.pop()
            elif code == ACTALL and depth > 0:
                raise AsmError(
                    f"[{pc}] actall inside a loop would make the "
                    f"all-lanes-done early exit observable")
            elif code == HALT and depth > 0:
                raise AsmError(
                    f"[{pc}] halt inside a loop: the active mask cannot "
                    f"gate it, so the all-lanes-done early exit would be "
                    f"observable")
            if worst > MAX_INSTRUCTIONS:
                raise AsmError(
                    f"[{pc}] worst-case instruction count exceeds "
                    f"{MAX_INSTRUCTIONS}; the loop bounds are finite but "
                    f"not a bound")
        if depth != 0:
            raise AsmError(f"{depth} loop(s) left open at the end")
        if worst > MAX_INSTRUCTIONS:
            raise AsmError(
                f"worst-case instruction count {worst} exceeds "
                f"{MAX_INSTRUCTIONS}")

    # -- serialisation -------------------------------------------------

    def to_bytes(self):
        out = struct.pack("<8I", MAGIC, VERSION, len(self.insns),
                          self.n_consts, self.max_deposits,
                          PREC_CODE[self.fmt.name], self.flags,
                          self.scratch_io)
        if not self.bank_external:
            for k in self.consts:
                out += k.to_bytes(self.esz, "little")
        for w in self.insns:
            out += struct.pack("<Q", w)
        return out

    def digest(self, bank=b""):
        """SHA-256 of the image bytes followed by the bank bytes - the
        attestation `cft_program_digest` returns, computed here so the
        library and the tools can be held to one number."""
        h = hashlib.sha256()
        h.update(self.to_bytes())
        h.update(bank)
        return h.hexdigest()

    def bank_bytes(self, values):
        """A bank buffer from a list of format-width values: exactly
        `n_consts` of them, dense, little-endian, laid out the way the
        image's own constant section would be."""
        if len(values) != self.n_consts:
            raise AsmError(f"bank holds {len(values)} values, the program "
                           f"addresses {self.n_consts}")
        out = b""
        for v in values:
            if not 0 <= v < (1 << self.fmt.width):
                raise AsmError("bank value does not fit the format")
            out += v.to_bytes(self.esz, "little")
        return out

    @classmethod
    def from_bytes(cls, data, scratch_depth=None):
        """The image back. `scratch_depth` is what the reader assumes
        the tile has; None INFERS it - the smallest power of two, at
        least the default 256, that covers every static slot and both
        scratch-I/O counts. Inferring rather than defaulting is what
        keeps a legal image for a 512-slot tile readable on a tree
        whose own default is 256, and it is what the disassembler
        writes back as `.scratch N`."""
        if len(data) < HEADER_BYTES:
            raise AsmError("shorter than a header")
        (magic, ver, n_insns, n_consts, maxdep, prec, flags,
         scratch_io) = struct.unpack("<8I", data[:HEADER_BYTES])
        if magic != MAGIC:
            raise AsmError(f"bad magic {magic:#010x}, expected {MAGIC:#010x}")
        if ver != VERSION:
            raise AsmError(f"program version {ver}, this loader speaks "
                           f"{VERSION}")
        if flags & FLAGS_RESERVED:
            raise AsmError(f"header flags {flags:#010x}: only BANK_EXT and "
                           f"SCRATCH_IO are defined and the rest are "
                           f"reserved")
        if not (flags & FLAG_SCRATCH_IO) and scratch_io:
            raise AsmError("reserved header word 7 must be zero unless "
                           "flags.SCRATCH_IO says it is scratch_io")
        name = next((k for k, v in PREC_CODE.items() if v == prec), None)
        if name is None:
            raise AsmError(f"precision code {prec} is not on the ladder")
        fmt = FORMATS[name]
        esz = fmt.width // 8
        off = HEADER_BYTES
        carried = 0 if (flags & FLAG_BANK_EXT) else n_consts
        want = off + carried * esz + n_insns * INSN_BYTES
        if len(data) != want:
            raise AsmError(
                f"{len(data)} bytes, header describes {want} - a program is "
                f"exactly its header, constants and instructions, so "
                f"anything else is a different program")
        consts = [int.from_bytes(data[off + i * esz: off + (i + 1) * esz],
                                 "little")
                  for i in range(carried)]
        off += carried * esz
        insns = [struct.unpack("<Q", data[off + i * INSN_BYTES:
                                          off + (i + 1) * INSN_BYTES])[0]
                 for i in range(n_insns)]
        if flags & FLAG_BANK_EXT:
            # The bank is not in the image, but the program still
            # addresses n_consts of it and every index check needs that
            # number - so the declared bank is carried as placeholders
            # that to_bytes() never writes.
            consts = [0] * n_consts
        if scratch_depth is None:
            scratch_depth = infer_scratch_depth(insns, scratch_io, flags)
        return cls(fmt, insns, consts, maxdep, flags,
                   scratch_depth=scratch_depth, scratch_io=scratch_io)


# ---- the assembler ---------------------------------------------------

_COMMENT = re.compile(r";.*$")
_REGNAME = re.compile(r"^r(\d+)$", re.IGNORECASE)
_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_OPNUM = re.compile(r"^op(\d+)$", re.IGNORECASE)


def _split(line):
    return [t for t in re.split(r"[\s,]+", line.strip()) if t]


def _parse_uint(tok, what):
    t = tok.lower()
    try:
        return int(t, 16) if t.startswith("0x") else int(t, 10)
    except ValueError:
        raise AsmError(f"{what}: {tok!r} is not a number")


class _Asm:
    def __init__(self, text, source="<text>"):
        self.text = text
        self.source = source
        self.fmt = None
        self.max_deposits = None
        self.flags = 0
        self.consts = []
        self.const_names = []
        self.const_index = {}
        self.reg_names = {}
        self.slot_names = {}
        self.scratch_depth = SCRATCH_D_DEFAULT
        self.have_depth = False
        self.n_scratch_in = 0
        self.n_scratch_out = 0
        self.have_scratch_in = False
        self.have_scratch_out = False
        self.insns = []
        self.lineno = 0

    def fail(self, msg):
        raise AsmError(f"{self.source}:{self.lineno}: {msg}")

    # -- operands ------------------------------------------------------

    def reg(self, tok):
        """A register operand -> number. Refuses a constant name, so a
        `deposit K_ONE` is a message rather than a silent register 0."""
        low = tok.lower()
        if low in self.reg_names:
            return self.reg_names[low]
        m = _REGNAME.match(tok)
        if not m:
            if low in self.const_index:
                self.fail(f"{tok} is a constant, and this operand must be "
                          f"a register")
            if low in self.slot_names:
                self.fail(f"{tok} is a scratch slot, and this operand must "
                          f"be a register")
            self.fail(f"{tok!r} is not a register")
        n = int(m.group(1))
        if not 0 <= n < NREG:
            self.fail(f"r{n} is outside r0..r{NREG - 1}")
        return n

    def slot(self, tok):
        """A scratch slot operand -> number: a `.slot` name, or a
        decimal or 0x literal. Refuses a register or a constant name,
        so `stl r3, r4` is a message rather than slot 4."""
        low = tok.lower()
        if low in self.slot_names:
            return self.slot_names[low]
        if _IDENT.match(tok):
            what = ("a register" if (low in self.reg_names
                                     or _REGNAME.match(tok))
                    else "a constant" if low in self.const_index
                    else None)
            if what:
                self.fail(f"{tok} is {what}, and a static slot is a number "
                          f"or a `.slot` name - the indexed form is `stx` "
                          f"and `ldx`")
            self.fail(f"{tok!r} is not a slot")
        v = _parse_uint(tok, "a scratch slot")
        return v

    def operand(self, tok):
        """-> (value, is_const). A constant NAME sets that operand's k
        bit; anything else is a register."""
        low = tok.lower()
        if low in self.const_index:
            return self.const_index[low], True
        return self.reg(tok), False

    # -- directives ----------------------------------------------------

    def do_format(self, args):
        if self.fmt is not None:
            self.fail(".format appears twice")
        if self.insns or self.consts or self.max_deposits is not None:
            self.fail(".format must come first")
        if len(args) != 1:
            self.fail(".format takes one name")
        name = args[0].lower()
        if name not in FORMATS:
            self.fail(f"{args[0]!r} is not fp32, fp64, fp128 or fp256")
        self.fmt = FORMATS[name]

    def do_deposits(self, args):
        if len(args) != 1:
            self.fail(".deposits takes one number")
        self.max_deposits = _parse_uint(args[0], ".deposits")

    def do_bank(self, args):
        if len(args) != 1 or args[0].lower() != "external":
            self.fail(".bank takes the word `external`")
        if self.consts:
            self.fail(".bank external must precede the .const lines it "
                      "turns into declarations")
        self.flags |= FLAG_BANK_EXT

    def do_scratch(self, args):
        """`.scratch N` - the depth the program assumes; `.scratch in N`
        and `.scratch out M` - the per-run block, which is the header's
        `scratch_io` and `flags.SCRATCH_IO`.

        All three must precede the instructions: a depth that changed
        halfway through would make the slot bound depend on where a
        line sits, and a scratch-I/O count is a header word, not
        something a program acquires as it goes."""
        if self.insns:
            self.fail(".scratch must come before the instructions")
        if len(args) == 1:
            if self.have_depth:
                self.fail(".scratch N appears twice")
            v = _parse_uint(args[0], ".scratch")
            if v < 1 or v > SCRATCH_D_MAX or (v & (v - 1)):
                self.fail(f".scratch takes a power of two in "
                          f"1..{SCRATCH_D_MAX}")
            self.scratch_depth = v
            self.have_depth = True
            return
        if len(args) != 2 or args[0].lower() not in ("in", "out"):
            self.fail(".scratch takes a depth, or `in N`, or `out M`")
        which = args[0].lower()
        v = _parse_uint(args[1], f".scratch {which}")
        if v > SCRATCH_IO_MAX:
            self.fail(f".scratch {which} is a sixteen-bit count, at most "
                      f"{SCRATCH_IO_MAX}")
        if which == "in":
            if self.have_scratch_in:
                self.fail(".scratch in appears twice")
            self.n_scratch_in = v
            self.have_scratch_in = True
        else:
            if self.have_scratch_out:
                self.fail(".scratch out appears twice")
            self.n_scratch_out = v
            self.have_scratch_out = True
        # Either half declares the block, so the flag is set even by a
        # count of zero: the flag says the word is MEANINGFUL, and a
        # program that carries nothing in and something out is a
        # program that says so.
        self.flags |= FLAG_SCRATCH_IO

    def do_slot(self, args):
        if len(args) != 3 or args[1] != "=":
            self.fail(".slot takes NAME = N")
        name = args[0]
        if not _IDENT.match(name):
            self.fail(f"{name!r} is not a name")
        low = name.lower()
        if (low in self.const_index or low in self.reg_names
                or low in self.slot_names):
            self.fail(f"{name} is already defined")
        if _REGNAME.match(name):
            self.fail(f"{name} would shadow a register")
        v = _parse_uint(args[2], ".slot")
        if v > SLOT_MASK:
            self.fail(f"a static slot is imm[23:0], so at most {SLOT_MASK}")
        self.slot_names[low] = v

    def do_const(self, args):
        # Under `.bank external` a `.const` line declares a NAME and its
        # place in the order, and the run supplies the value - so the
        # `= value` half is optional there and ignored when written.
        bare = len(args) == 1 and (self.flags & FLAG_BANK_EXT)
        if not bare and (len(args) < 3 or args[1] != "="):
            self.fail(".const takes NAME = value"
                      + (", or NAME alone under .bank external"
                         if self.flags & FLAG_BANK_EXT else ""))
        name = args[0]
        if not _IDENT.match(name):
            self.fail(f"{name!r} is not a name")
        low = name.lower()
        if (low in self.const_index or low in self.reg_names
                or low in self.slot_names):
            self.fail(f"{name} is already defined")
        if _REGNAME.match(name):
            self.fail(f"{name} would shadow a register")
        if bare:
            bits = 0
        else:
            bits = self.literal(" ".join(args[2:]))
            if self.flags & FLAG_BANK_EXT:
                bits = 0        # declared, not carried
        if len(self.consts) >= KADDR_KX:
            self.fail(f"the bank addresses at most {KADDR_KX} constants")
        self.const_index[low] = len(self.consts)
        self.const_names.append(name)
        self.consts.append(bits)

    def do_reg(self, args):
        if len(args) != 3 or args[1] != "=":
            self.fail(".reg takes NAME = rN")
        name = args[0]
        if not _IDENT.match(name):
            self.fail(f"{name!r} is not a name")
        low = name.lower()
        if (low in self.const_index or low in self.reg_names
                or low in self.slot_names):
            self.fail(f"{name} is already defined")
        if _REGNAME.match(name):
            self.fail(f"{name} would shadow a register")
        m = _REGNAME.match(args[2])
        if not m:
            self.fail(f"{args[2]!r} is not r0..r{NREG - 1}")
        n = int(m.group(1))
        if not 0 <= n < NREG:
            self.fail(f"r{n} is outside r0..r{NREG - 1}")
        self.reg_names[low] = n

    def literal(self, text):
        """A constant literal -> the format's bits.

        Three forms, and the one that decides between them is a `p`:

        * `0x...` with no `p` is the RAW ENCODING, at the format's
          width, zero-extended from however many digits are written.
        * `0x1p237`, `-0x1.8p-3` - a `p` makes it 754-2019 5.12.3's
          hexadecimal-significand character sequence, exact when it
          fits and correctly rounded when it does not. This is not
          decoration: at fp128 and fp256 a power of two is a 64-digit
          raw word or a 70-digit decimal, and both are transcription
          hazards where `0x1p237` is a derivation.
        * anything else is 5.12.2's decimal sequence, round-to-
          nearest-even into the format - `chars.from_decimal` here and
          `cft_from_decimal_char` in the tool, which are the same
          routine in two languages.

        The two forms cannot collide: `p` is not a hexadecimal digit.
        """
        if self.fmt is None:
            self.fail(".format must come before any constant")
        t = text.strip()
        body = t[1:] if t[:1] in "+-" else t
        if body[:2].lower() == "0x":
            if "p" in body.lower():
                try:
                    bits, _flags = chars.from_hex(self.fmt, t, sf.RND_RNE)
                except Exception as exc:               # noqa: BLE001
                    self.fail(f"{text!r} is not a hexadecimal-significand "
                              f"sequence this format can read ({exc})")
                return bits
            if t is not body:
                self.fail("a raw 0x encoding carries its own sign bit; "
                          "write the whole word, or use the 5.12.3 form "
                          "with a binary exponent")
            try:
                v = int(body[2:], 16)
            except ValueError:
                self.fail(f"{text!r} is not a hexadecimal encoding")
            if v >= (1 << self.fmt.width):
                self.fail(f"{text} is wider than {self.fmt.name}")
            return v
        try:
            bits, _flags = chars.from_decimal(self.fmt, t, sf.RND_RNE)
        except Exception as exc:                       # noqa: BLE001
            self.fail(f"{text!r} is not a number this format can read "
                      f"({exc})")
        return bits

    # -- instructions --------------------------------------------------

    def do_ctrl(self, code, args):
        if code == REPEAT:
            if len(args) != 1:
                self.fail("repeat takes a trip count")
            trip = _parse_uint(args[0], "repeat")
            if trip == 0:
                self.fail("repeat 0 is not a loop; omit it")
            if trip >= (1 << 32):
                self.fail("a trip count is a 32-bit immediate")
            self.insns.append(repeat(trip))
        elif code in (DEPOSIT, SETACT):
            if len(args) != 1:
                self.fail(f"{CTRL_NAMES[code]} takes one register")
            r = self.reg(args[0])
            self.insns.append(deposit(r) if code == DEPOSIT else setact(r))
        elif code in (STL, LDL):
            if len(args) != 2:
                self.fail(f"{CTRL_NAMES[code]} takes a register and a slot")
            r = self.reg(args[0])
            s = self.slot(args[1])
            if s > SLOT_MASK:
                self.fail(f"a static slot is imm[23:0], so at most "
                          f"{SLOT_MASK}")
            self.insns.append(stl(r, s) if code == STL else ldl(r, s))
        elif code in (STX, LDX):
            if len(args) != 2:
                self.fail(f"{CTRL_NAMES[code]} takes two registers - the "
                          f"value and the index")
            r0 = self.reg(args[0])
            r1 = self.reg(args[1])
            self.insns.append(stx(r0, r1) if code == STX else ldx(r0, r1))
        else:
            if args:
                self.fail(f"{CTRL_NAMES[code]} takes no operands")
            self.insns.append(encode(code, ctrl=True))

    def do_alu(self, mnemonic, args):
        name, *suffixes = mnemonic.split(".")
        rnd = sf.RND_RNE
        force_kx = False
        for suffix in suffixes:
            if suffix == "kx":
                # The indexed form is chosen automatically when an index
                # needs it. `.kx` asks for it anyway, which is the one
                # redundancy docs/SEQUENCER.md deliberately does not
                # refuse - a kx instruction whose indices all happen to
                # be below sixteen - and therefore the one thing the
                # disassembler must be able to say.
                force_kx = True
            elif suffix in RND_BY_NAME:
                rnd = RND_BY_NAME[suffix]
            else:
                self.fail(f"{suffix!r} is not rne, rtz, rdn, rup, rmm or kx")
        m = _OPNUM.match(name)
        if m:
            op = int(m.group(1))
            if op > 255:
                self.fail(f"op{op} does not fit the opcode byte")
            fields = (A, B, C)          # an opcode we cannot name has
            explicit_only = True        # no arity we can know
        else:
            if name not in OP_BY_NAME:
                self.fail(f"{name!r} is not an opcode this ISA has")
            op = OP_BY_NAME[name]
            fields = OP_FIELDS[op]
            explicit_only = False
        if not args:
            self.fail(f"{name} takes a destination")
        rd = self.reg(args[0])
        rest = args[1:]
        if len(rest) == 3:
            order = (A, B, C)           # every field, written out
        elif not explicit_only and len(rest) == len(fields):
            order = fields              # the operands the opcode reads
        else:
            self.fail(
                f"{name} reads {len(fields)} operand(s) "
                f"({', '.join(fields)}); write that many, or all three "
                f"in ra, rb, rc order - {len(rest)} given")
        vals = {A: 0, B: 0, C: 0}
        flags = {A: False, B: False, C: False}
        for field, tok in zip(order, rest):
            v, is_const = self.operand(tok)
            vals[field] = v
            flags[field] = is_const
        if force_kx and not any(flags.values()):
            self.fail("`.kx` on an instruction whose operands are all "
                      "registers selects nothing, and the loader refuses "
                      "it - it is a second spelling of the plain form")
        try:
            word = alu(op, rd, vals[A], vals[B], vals[C], rnd,
                       ka=flags[A], kb=flags[B], kc=flags[C],
                       kx=True if force_kx else None)
        except AsmError as exc:
            self.fail(str(exc))
        self.insns.append(word)

    # -- the pass ------------------------------------------------------

    def run(self):
        for raw in self.text.splitlines():
            self.lineno += 1
            line = _COMMENT.sub("", raw)
            toks = _split(line)
            if not toks:
                continue
            head = toks[0]
            if head.startswith("."):
                directive = head.lower()
                handler = {".format": self.do_format,
                           ".deposits": self.do_deposits,
                           ".bank": self.do_bank,
                           ".const": self.do_const,
                           ".reg": self.do_reg,
                           ".slot": self.do_slot,
                           ".scratch": self.do_scratch}.get(directive)
                if handler is None:
                    self.fail(f"{head!r} is not a directive")
                handler(toks[1:])
                continue
            if self.fmt is None:
                self.fail(".format must come first")
            low = head.lower()
            if low in CTRL_CODES:
                self.do_ctrl(CTRL_CODES[low], toks[1:])
                continue
            self.do_alu(low, toks[1:])

        self.lineno = 0
        if self.fmt is None:
            self.fail(".format is required")
        if self.max_deposits is None:
            self.fail(".deposits is required")
        scratch_io = (self.n_scratch_in & 0xFFFF) | \
                     ((self.n_scratch_out & 0xFFFF) << 16)
        try:
            return Image(self.fmt, self.insns, self.consts,
                         self.max_deposits, self.flags,
                         const_names=self.const_names,
                         reg_names=self.reg_names,
                         scratch_depth=self.scratch_depth,
                         scratch_io=scratch_io,
                         slot_names=self.slot_names)
        except AsmError as exc:
            raise AsmError(f"{self.source}: {exc}") from None


def assemble_image(text, source="<text>") -> Image:
    return _Asm(text, source).run()


def assemble(text, source="<text>") -> bytes:
    """`.cfta` source -> the exact bytes a `.cftp` file holds."""
    return assemble_image(text, source).to_bytes()


# ---- the disassembler ------------------------------------------------

def _const_name(i):
    return f"k{i}"


def disassemble(image) -> str:
    """Any valid image -> `.cfta` text that assembles back to the same
    bytes. Constants get generated names (`k0`, `k1`, ...) because the
    image has none, and registers are written as `rN` for the same
    reason.

    The round trip is a test, not a convenience: a readback that
    cannot be re-assembled is not an attestation.
    """
    if isinstance(image, (bytes, bytearray)):
        img = Image.from_bytes(bytes(image))
    else:
        img = image
    out = []
    out.append(f".format   {img.fmt.name}")
    out.append(f".deposits {img.max_deposits}")
    # The depth is not in the image, so what is written back is what
    # `from_bytes` inferred - and only when it is not the default, so
    # that an image which needs no scratch reads exactly as it did
    # before revision 3.
    if img.scratch_depth != SCRATCH_D_DEFAULT:
        out.append(f".scratch  {img.scratch_depth}")
    if img.scratch_io_declared:
        out.append(f".scratch  in {img.n_scratch_in}")
        out.append(f".scratch  out {img.n_scratch_out}")
    if img.bank_external:
        out.append(".bank     external")
    for i in range(img.n_consts):
        if img.bank_external:
            # No values to print: the source declares names and order.
            out.append(f".const    {_const_name(i)}")
        else:
            width = img.esz * 2
            out.append(f".const    {_const_name(i)} = "
                       f"0x{img.consts[i]:0{width}x}")
    if img.n_consts or img.bank_external:
        out.append("")

    def operand(idx, is_const):
        return _const_name(idx) if is_const else f"r{idx}"

    indent = 0
    for word in img.insns:
        d = decode(word)
        if d["ctrl"]:
            code = d["op"]
            name = CTRL_NAMES[code]
            if code == ENDREP:
                indent -= 1
            pad = "  " * max(indent, 0)
            if code == REPEAT:
                out.append(f"{pad}{name} {d['imm']}")
                indent += 1
            elif code in (DEPOSIT, SETACT):
                out.append(f"{pad}{name} r{d['ra']}")
            elif code == STL:
                out.append(f"{pad}{name} r{d['ra']}, {d['imm'] & SLOT_MASK}")
            elif code == LDL:
                out.append(f"{pad}{name} r{d['rd']}, {d['imm'] & SLOT_MASK}")
            elif code == STX:
                out.append(f"{pad}{name} r{d['ra']}, r{d['rb']}")
            elif code == LDX:
                out.append(f"{pad}{name} r{d['rd']}, r{d['rb']}")
            else:
                out.append(f"{pad}{name}")
            continue
        pad = "  " * max(indent, 0)
        op = d["op"]
        name = OP_NAMES.get(op, f"op{op}")
        if d["rnd"] != sf.RND_RNE:
            name += "." + RND_NAMES[d["rnd"]]
        srcs = sources(d)
        if d["kx"] and not any(idx >= KADDR_PLAIN
                               for idx, is_const in srcs if is_const):
            # An indexed instruction the assembler's own rule would have
            # written plain. Legal, and it has to be sayable.
            name += ".kx"
        fields = OP_FIELDS.get(op)
        by_field = dict(zip((A, B, C), srcs))
        short = None
        if fields is not None:
            unread = [f for f in (A, B, C) if f not in fields]
            # The short form can only be used when every field the
            # opcode does not read is a plain zero register - otherwise
            # the bits would not survive the round trip.
            if all(by_field[f] == (0, False) for f in unread):
                short = [operand(*by_field[f]) for f in fields]
        args = short if short is not None else [operand(*by_field[f])
                                                for f in (A, B, C)]
        out.append(f"{pad}{name} r{d['rd']}, " + ", ".join(args))
    return "\n".join(out) + "\n"


# ---- header report ---------------------------------------------------

def info(image) -> str:
    """What `cft-asm -i` prints: what the image declares, what it
    needs, and its SHA-256."""
    if isinstance(image, (bytes, bytearray)):
        data = bytes(image)
        img = Image.from_bytes(data)
    else:
        img = image
        data = img.to_bytes()
    feats = img.features()
    names = [n for bit, n in ((FLAG_BANK_EXT, "BANK_EXT"),
                              (FLAG_SCRATCH_IO, "SCRATCH_IO"))
             if img.flags & bit]
    top, indexed = img.scratch_use()
    if top is None and not indexed:
        scratch = "-"
    else:
        parts = []
        if top is not None:
            parts.append(f"highest static slot {top}")
        parts.append("indexed" if indexed else "not indexed")
        scratch = ", ".join(parts)
    lines = [
        f"format        {img.fmt.name}",
        f"instructions  {len(img.insns)}",
        f"constants     {img.n_consts}"
        + ("  (external: supplied per run)" if img.bank_external else ""),
        f"deposits      {img.max_deposits}",
        f"scratch       {scratch}",
        f"scratch-io    "
        + (f"in {img.n_scratch_in}, out {img.n_scratch_out}"
           if img.scratch_io_declared else "-"),
        f"flags         0x{img.flags:08x}"
        + ("  " + " ".join(names) if names else ""),
        f"bytes         {len(data)}",
        f"features      {' '.join(feats) if feats else '-'}",
        f"sha256        {hashlib.sha256(data).hexdigest()}",
    ]
    return "\n".join(lines) + "\n"
