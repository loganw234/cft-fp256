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
NREG = 16
MAX_LOOP_DEPTH = 4

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

# control codes (instruction bit 31 set)
HALT, REPEAT, ENDREP, DEPOSIT, SETACT, ACTALL = 0, 1, 2, 3, 4, 5
CTRL_NAMES = {HALT: "halt", REPEAT: "repeat", ENDREP: "endrep",
              DEPOSIT: "deposit", SETACT: "setact", ACTALL: "actall"}

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
    for name, v in (("rd", rd), ("ra", ra), ("rb", rb), ("rc", rc)):
        if not 0 <= v < NREG:
            raise ProgramError(f"{name}={v} outside 0..{NREG - 1}")
    if not 0 <= op < 256:
        raise ProgramError(f"op={op} does not fit the opcode byte")
    if not 0 <= rnd <= 4:
        raise ProgramError(f"rnd={rnd}; the contract defines 0..4")
    if not 0 <= imm < (1 << 32):
        raise ProgramError(f"imm={imm} does not fit 32 bits")
    return (op | (rd << 8) | (ra << 12) | (rb << 16) | (rc << 20)
            | (rnd << 24) | (int(bool(ka)) << 27) | (int(bool(kb)) << 28)
            | (int(bool(kc)) << 29) | (int(bool(kx)) << 30)
            | (int(bool(ctrl)) << 31)
            | (imm << 32))


def decode(word):
    """-> dict. Field names match docs/SEQUENCER.md."""
    return {
        "op": word & 0xFF,
        "rd": (word >> 8) & 0xF,
        "ra": (word >> 12) & 0xF,
        "rb": (word >> 16) & 0xF,
        "rc": (word >> 20) & 0xF,
        "rnd": (word >> 24) & 0x7,
        "ka": bool((word >> 27) & 1),
        "kb": bool((word >> 28) & 1),
        "kc": bool((word >> 29) & 1),
        "kx": bool((word >> 30) & 1),
        "ctrl": bool((word >> 31) & 1),
        "imm": (word >> 32) & 0xFFFFFFFF,
    }


# Which byte of `imm` carries each operand's constant index under `kx`,
# in a, b, c order: imm[7:0], imm[15:8], imm[23:16]. imm[31:24] is
# reserved and must be zero, which is what leaves room for a
# counter-indexed form later without disturbing this one.
KX_SHIFT = (0, 8, 16)
KX_RESERVED = 0xFF000000


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
    """
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
    DMAs to the tile and can read back to attest what ran."""

    def __init__(self, fmt: FpFormat, insns, consts=(), max_deposits=1):
        self.fmt = fmt
        self.insns = list(insns)
        self.consts = list(consts)
        self.max_deposits = max_deposits
        self.validate()

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
        * `imm[31:24]` is read by nothing and must be zero, which is
          what keeps it available for a later form;
        * and `kx` itself selects nothing when no `k` bit is set, so
          that combination is refused too - it would otherwise be a
          second spelling of an ordinary three-register instruction.

        What is deliberately NOT refused: a `kx` instruction whose
        indices all happen to be below sixteen. That is a second
        spelling of a plain `k` instruction, and the model tolerates it
        for the same reason it tolerates a non-zero `rb` on a unary
        ABS - the rule is about fields the ENCODING does not read, not
        about which of two legal encodings a compiler chose.
        """
        if d["kx"]:
            if not (d["ka"] or d["kb"] or d["kc"]):
                raise ProgramError(
                    f"[{pc}] kx is set and no operand names a constant, so "
                    f"the bit selects nothing and the instruction has a "
                    f"second encoding with kx clear")
            if d["imm"] & KX_RESERVED:
                raise ProgramError(
                    f"[{pc}] imm[31:24] is reserved and must be zero")
        elif d["imm"]:
            raise ProgramError(
                f"[{pc}] an ALU instruction without kx has no immediate, "
                f"so bits 63:32 must be zero - otherwise the same "
                f"operation has many encodings and a readback hash stops "
                f"being a hash of the program")

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
            if idx >= len(self.consts):
                raise ProgramError(
                    f"[{pc}] {key} names constant {idx} but the bank "
                    f"holds {len(self.consts)}")

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
            used = {HALT: (), REPEAT: ("imm",), ENDREP: (),
                    DEPOSIT: ("ra",), SETACT: ("ra",), ACTALL: ()}[code]
            for field in ("rd", "ra", "rb", "rc", "rnd", "ka", "kb", "kc",
                          "kx", "imm"):
                if field not in used and d[field]:
                    raise ProgramError(
                        f"[{pc}] {CTRL_NAMES[code]} does not read {field}, "
                        f"so it must be zero")

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

    def digest(self):
        """sha256 of the exact bytes a device would be given.

        The program is loaded through the AXI master and can be read
        back, so what executed can be attested rather than assumed -
        but only if the encoding is canonical, which is what the
        must-be-zero checks above are for."""
        import hashlib
        return hashlib.sha256(self.to_bytes()).hexdigest()

    # -- serialisation -------------------------------------------------

    def to_bytes(self):
        ebytes = self.fmt.width // 8
        out = struct.pack("<8I", MAGIC, VERSION, len(self.insns),
                          len(self.consts), self.max_deposits,
                          PREC_CODE[self.fmt.name], 0, 0)
        for k in self.consts:
            out += k.to_bytes(ebytes, "little")
        for w in self.insns:
            out += struct.pack("<Q", w)
        return out

    @classmethod
    def from_bytes(cls, data):
        if len(data) < HEADER_WORDS * 4:
            raise ProgramError("shorter than a header")
        magic, ver, n_insns, n_consts, maxdep, prec, rsv0, rsv1 = \
            struct.unpack("<8I", data[:HEADER_WORDS * 4])
        if magic != MAGIC:
            raise ProgramError(f"bad magic {magic:#010x}, expected "
                               f"{MAGIC:#010x}")
        if ver != VERSION:
            raise ProgramError(f"program version {ver}, this loader "
                               f"speaks {VERSION}")
        if rsv0 or rsv1:
            # Instruction bit 30 is refused for being reserved; header
            # words cannot be laxer than instruction bits.
            raise ProgramError("reserved header words must be zero")
        name = next((k for k, v in PREC_CODE.items() if v == prec), None)
        if name is None:
            raise ProgramError(f"precision code {prec} is not on the ladder")
        fmt = FORMATS[name]
        ebytes = fmt.width // 8
        off = HEADER_WORDS * 4
        want = off + n_consts * ebytes + n_insns * INSN_BYTES
        if len(data) != want:
            raise ProgramError(
                f"{len(data)} bytes, header describes {want} - a program "
                f"is exactly its header, constants and instructions, so "
                f"anything else is a different program")
        consts = [int.from_bytes(data[off + i * ebytes:
                                      off + (i + 1) * ebytes], "little")
                  for i in range(n_consts)]
        off += n_consts * ebytes
        insns = [struct.unpack("<Q", data[off + i * INSN_BYTES:
                                          off + (i + 1) * INSN_BYTES])[0]
                 for i in range(n_insns)]
        return cls(fmt, insns, consts, maxdep)


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


def run(prog: Program, a, b, c=None, early_exit=True, insn_budget=None,
        n_active=None):
    """Execute `prog` over len(a) lanes.

    The three input streams initialise r0, r1 and r2 - the same three
    the elementwise engine already reads, so a sequencer run needs no
    new input path in the hardware. Registers r3..r15 start at +0.

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
        idx, is_const = spec
        return prog.consts[idx] if is_const else regs[lane][idx]

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
                   extended=False):
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
    """
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
                rd=rng.randrange(NREG),
                ra=rng.randrange(NREG),
                rb=rng.randrange(top) if kb else rng.randrange(NREG),
                rc=rng.randrange(top) if kc else rng.randrange(NREG),
                rnd=rng.randrange(5), kb=kb, kc=kc, kx=kx))
        elif pick < 0.6 and depth < MAX_LOOP_DEPTH:
            insns.append(repeat(rng.randint(1, 4)))
            depth += 1
        elif pick < 0.7 and depth > 0:
            insns.append(endrep())
            depth -= 1
        elif pick < 0.8:
            insns.append(deposit(rng.randrange(NREG)))
        elif pick < 0.92:
            insns.append(setact(rng.randrange(NREG)))
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
