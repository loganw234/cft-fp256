# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""The orbit sequencer's golden model.

These tests are mostly about the three properties docs/SEQUENCER.md
claims, because those are what the whole design rests on:

  P1  the ALU is the existing, already-verified pipeline
  P2  deposition is addressed by index, so splitting lanes across
      tiles cannot change the answer
  P3  the all-lanes-done early exit changes the instruction count and
      nothing else

P2 and P3 are the ones that could be quietly false, so they get the
most attention - and each test checks that it actually exercised what
it claims to, because a property test that never reaches the
interesting case passes for the wrong reason.
"""

import random
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cft_golden import FORMATS  # noqa: E402
from cft_golden import softfloat as sf  # noqa: E402
from cft_golden import seq  # noqa: E402

FP32 = FORMATS["fp32"]
FP64 = FORMATS["fp64"]


# ---- encoding --------------------------------------------------------

def test_encode_decode_roundtrip():
    """Every field survives encode -> decode, with registers reaching 31.

    `imm` is drawn from the bits revision 2 leaves to it - imm[23:0] and
    imm[31:28] - because imm[27:24] ARE the register high bits and a
    caller does not write them twice. What comes back out of `imm` is
    therefore the drawn value with those four bits filled in, which is
    the second assertion below and the whole of the R1 encoding.
    """
    rng = random.Random(4)
    for _ in range(2000):
        fields = dict(
            op=rng.randrange(256), rd=rng.randrange(32),
            ra=rng.randrange(32), rb=rng.randrange(32),
            rc=rng.randrange(32), rnd=rng.randrange(5),
            ka=bool(rng.getrandbits(1)), kb=bool(rng.getrandbits(1)),
            kc=bool(rng.getrandbits(1)), kx=bool(rng.getrandbits(1)),
            ctrl=bool(rng.getrandbits(1)),
            imm=(rng.randrange(1 << 24)
                 | (rng.randrange(1 << 4) << 28)))
        d = seq.decode(seq.encode(**fields))
        for k, v in fields.items():
            if k == "imm":
                continue
            assert d[k] == v, f"{k} did not survive the round trip"
        want_hi = sum(((fields[k] >> 4) & 1) << seq.REG_HI_SHIFT[k]
                      for k in ("rd", "ra", "rb", "rc"))
        assert d["imm"] == fields["imm"] | want_hi, (
            "imm[27:24] must come back carrying exactly the four "
            "register high bits the fields asked for")


def test_five_bit_register_fields_land_where_the_contract_says():
    """R1's table, checked one bit at a time rather than in aggregate:
    imm[24] is rd[4], imm[25] ra[4], imm[26] rb[4], imm[27] rc[4]."""
    for name, shift in (("rd", 24), ("ra", 25), ("rb", 26), ("rc", 27)):
        word = seq.encode(sf.OP_FMA, **{name: 16})
        assert (word >> 32) == (1 << shift), (
            f"{name}[4] must be imm[{shift}] and nothing else; the word's "
            f"immediate is {(word >> 32):#010x}")
        assert seq.decode(word)[name] == 16
        # ...and the low four bits stay where they have always been.
        word = seq.encode(sf.OP_FMA, **{name: 16 + 9})
        assert seq.decode(word)[name] == 25


def test_registers_above_fifteen_run():
    """r16..r31 exist, start at +0 like r3..r15, and hold a value."""
    fmt = FP32
    one = sf.one_bits(fmt)
    # ADD reads ra and rc (rb is steered to 1.0), so the operands are
    # named in those two positions.
    prog = seq.Program(fmt, [
        seq.alu(sf.OP_ADD, 31, ra=0, rc=2),    # r31 = a + c, and c is +0
        seq.alu(sf.OP_ADD, 16, ra=31, rc=20),  # r16 = r31 + r20, r20 is +0
        seq.deposit(16),
        seq.deposit(20),                       # the untouched high register
        seq.halt()], max_deposits=2)
    a = [one, sf.zero_bits(fmt), sf.max_normal_bits(fmt)]
    res = seq.run(prog, a, [0] * 3, [0] * 3)
    for i, v in enumerate(a):
        assert res.deposits[i * 2] == v, "r16 did not carry a through r31"
        assert res.deposits[i * 2 + 1] == sf.zero_bits(fmt), \
            "r20 must start at +0 exactly as r3..r15 do"
    assert len(res.regs[0]) == seq.NREG == 32


def test_program_serialisation_roundtrip():
    prog = seq.Program(
        FP64,
        [seq.alu(sf.OP_FMA, 0, 0, 0, 1), seq.deposit(0), seq.halt()],
        consts=[sf.one_bits(FP64), sf.zero_bits(FP64, 1)],
        max_deposits=3)
    back = seq.Program.from_bytes(prog.to_bytes())
    assert back.insns == prog.insns
    assert back.consts == prog.consts
    assert back.max_deposits == prog.max_deposits
    assert back.fmt is prog.fmt


def test_serialisation_rejects_damage():
    prog = seq.Program(FP32, [seq.halt()])
    raw = bytearray(prog.to_bytes())
    with pytest.raises(seq.ProgramError):
        seq.Program.from_bytes(bytes(raw[:4]))          # truncated
    bad = bytearray(raw)
    bad[0] ^= 0xFF
    with pytest.raises(seq.ProgramError):
        seq.Program.from_bytes(bytes(bad))              # bad magic
    bad = bytearray(raw)
    bad[4] = 99
    with pytest.raises(seq.ProgramError):
        seq.Program.from_bytes(bytes(bad))              # future version


# ---- validation ------------------------------------------------------

def test_actall_inside_a_loop_is_refused():
    """P3 depends on it: if a lane can be reactivated inside a loop,
    skipping the rest of that loop stops being invisible."""
    with pytest.raises(seq.ProgramError, match="early exit"):
        seq.Program(FP32, [seq.repeat(4), seq.actall(), seq.endrep(),
                           seq.halt()])
    # and is fine outside one
    seq.Program(FP32, [seq.actall(), seq.repeat(4), seq.endrep(),
                       seq.halt()])


def test_validation_rejects_malformed_programs():
    with pytest.raises(seq.ProgramError):
        seq.Program(FP32, [seq.repeat(2), seq.halt()])          # unclosed
    with pytest.raises(seq.ProgramError):
        seq.Program(FP32, [seq.endrep(), seq.halt()])           # unopened
    with pytest.raises(seq.ProgramError):
        seq.Program(FP32, [seq.repeat(2)] * 5 + [seq.endrep()] * 5)
    with pytest.raises(seq.ProgramError):
        seq.Program(FP32, [seq.alu(sf.OP_FMA, 0, 1, 0, 0, ka=True)])
    with pytest.raises(seq.ProgramError):
        seq.encode(sf.OP_FMA, rd=32)          # a register past the file
    with pytest.raises(seq.ProgramError):
        # A CONSTANT operand's register high bit is read by nothing, so
        # it must be zero - the same reserved-field rule, applied to the
        # four bits R1 brought into play. Written raw, because `alu()`
        # would never build it.
        seq.Program(FP32, [seq.encode(sf.OP_FMA, 0, ka=True,
                                      imm=1 << seq.REG_HI_SHIFT["ra"]),
                           seq.halt()], consts=[sf.one_bits(FP32)])
    with pytest.raises(seq.ProgramError, match="high bit"):
        # ...under kx too: there the index is a byte of imm and the
        # register high bit is not part of it.
        seq.Program(FP32, [seq.encode(sf.OP_FMA, 0, kb=True, kx=True,
                                      imm=(2 << 8)
                                          | (1 << seq.REG_HI_SHIFT["rb"])),
                           seq.halt()],
                    consts=[sf.one_bits(FP32)] * 4)
    with pytest.raises(seq.ProgramError, match="imm"):
        # A control code that reads no register may set none of the
        # four high bits. DEPOSIT reads `ra`, so ra's is legal and
        # rb's is not.
        seq.Program(FP32, [seq.encode(seq.DEPOSIT, ra=1, ctrl=True,
                                      imm=1 << seq.REG_HI_SHIFT["rb"]),
                           seq.halt()])
    with pytest.raises(seq.ProgramError, match="imm"):
        seq.Program(FP32, [seq.encode(seq.ACTALL, ctrl=True,
                                      imm=1 << seq.REG_HI_SHIFT["ra"]),
                           seq.halt()])
    with pytest.raises(seq.ProgramError):
        seq.encode(sf.OP_FMA, rnd=5)                            # reserved
    with pytest.raises(seq.ProgramError):
        # bit 30 is kx since 2026-09-07; set with no operand naming a
        # constant it selects nothing, which is refused for the reason
        # it was refused as a reserved bit - the instruction would have
        # a second encoding.
        seq.Program(FP32, [seq.encode(sf.OP_FMA, 0, kx=True)])


# ---- a real program --------------------------------------------------

def escape_program(fmt, iterations, limit_bits):
    """z <- z*z + c, deposited each step, lanes dropping out when |z|
    reaches the limit. The atlas inner loop in miniature: an fma
    chain, a magnitude test, a predicate, and a deposition."""
    return seq.Program(
        fmt,
        [
            seq.repeat(iterations),
            seq.alu(sf.OP_FMA, 0, 0, 0, 1),     # r0 = r0*r0 + r1
            seq.deposit(0),
            seq.alu(sf.OP_ABS, 2, 0),           # r2 = |r0|
            seq.alu(sf.OP_CMPLT, 3, 2, 0, kb=True),   # r3 = r2 < limit
            seq.setact(3),
            seq.endrep(),
            seq.halt(),
        ],
        consts=[limit_bits],
        max_deposits=iterations)


def reference_escape(fmt, a, b, iterations, limit_bits):
    """The same computation written directly, so the sequencer is
    checked against something that is not the sequencer."""
    n = len(a)
    zero = sf.zero_bits(fmt, 0)
    deposits = [zero] * (n * iterations)
    flags = 0
    for i in range(n):
        z, c = a[i], b[i]
        live, made = True, 0
        for _ in range(iterations):
            if not live:
                break
            z, fl = sf.compute(fmt, sf.OP_FMA, z, z, c)
            flags |= fl
            deposits[i * iterations + made] = z
            made += 1
            mag, fl = sf.compute(fmt, sf.OP_ABS, z, 0, 0)
            flags |= fl
            pred, fl = sf.compute(fmt, sf.OP_CMPLT, mag, limit_bits, 0)
            flags |= fl
            live = (pred & ~fmt.sign_mask) != 0
    return deposits, flags


def _seeds(fmt, n, seed):
    """Starting points spread either side of the escape radius, so
    some lanes converge and some run away - which is what makes the
    early exit fire at different times per lane."""
    rng = random.Random(seed)
    out = []
    for _ in range(n):
        e = fmt.bias + rng.randint(-3, 1)
        frac = rng.getrandbits(fmt.man_w)
        out.append((rng.getrandbits(1) << (fmt.width - 1))
                   | (e << fmt.man_w) | frac)
    return out


@pytest.mark.parametrize("name", ["fp32", "fp64"])
def test_escape_matches_a_direct_computation(name):
    fmt = FORMATS[name]
    limit = sf.one_bits(fmt)                     # |z| < 1.0
    n, iters = 24, 8
    a, b = _seeds(fmt, n, 1), _seeds(fmt, n, 2)
    prog = escape_program(fmt, iters, limit)

    got = seq.run(prog, a, b)
    want_dep, want_flags = reference_escape(fmt, a, b, iters, limit)

    assert got.deposits == want_dep
    assert got.flags == want_flags
    assert got.status == 0
    # the test is only meaningful if lanes actually dropped out
    assert 0 < sum(got.active) < n, "no spread in convergence; retune seeds"


# ---- P3: the early exit is invisible ---------------------------------

def _pow2(fmt, e):
    return (e + fmt.bias) << fmt.man_w


def _escaping_seeds(fmt, n):
    """Seeds that all escape, at visibly different rates.

    The general-purpose seeds converge as often as they diverge, and a
    single lane that never goes inactive keeps every loop running to
    its trip count - which makes the early exit skip nothing and the
    test below prove nothing. z <- z*z with z = 2^k doubles the
    exponent every step, so a lane starting at 2^1 takes six steps to
    pass 2^60 and one starting at 2^30 takes one.
    """
    return [_pow2(fmt, 1 + (i % 8) * 4) for i in range(n)]


@pytest.mark.parametrize("name", ["fp32", "fp64"])
def test_early_exit_changes_nothing_but_the_instruction_count(name):
    fmt = FORMATS[name]
    limit = _pow2(fmt, 60)
    n, iters = 32, 20
    a = _escaping_seeds(fmt, n)
    b = [sf.zero_bits(fmt)] * n
    prog = escape_program(fmt, iters, limit)

    fast = seq.run(prog, a, b, early_exit=True)
    slow = seq.run(prog, a, b, early_exit=False)

    assert fast.state() == slow.state(), (
        "the early exit changed an observable")
    # ...and it has to have actually saved work, or this proves nothing
    assert fast.insns_executed < slow.insns_executed, (
        "no instructions were skipped; the test never reached the "
        "case it exists to check")


def test_early_exit_with_every_lane_escaping_immediately():
    """The extreme: all lanes go inactive on the first iteration, so
    the whole remainder of the loop is skipped."""
    fmt = FP32
    limit = sf.zero_bits(fmt)             # |z| < 0 is false for every z
    n, iters = 8, 50
    a = [sf.one_bits(fmt)] * n
    b = [sf.zero_bits(fmt)] * n
    prog = escape_program(fmt, iters, limit)
    fast = seq.run(prog, a, b, early_exit=True)
    slow = seq.run(prog, a, b, early_exit=False)
    assert fast.state() == slow.state()
    assert not any(fast.active)
    assert fast.insns_executed < slow.insns_executed / 5


# ---- P2: splitting lanes across tiles cannot change the answer -------

@pytest.mark.parametrize("chunks", [[24], [12, 12], [6, 6, 6, 6],
                                    [1, 23], [5, 5, 5, 5, 4]])
def test_partitioning_is_invisible(chunks):
    """This is the multi-tile determinism argument, executed. A run
    split into chunks - which is exactly what cft_run does across
    compute units - must produce the same deposits, in the same
    places, with the same flags."""
    fmt = FP32
    limit = sf.one_bits(fmt)
    n, iters = 24, 6
    assert sum(chunks) == n
    a, b = _seeds(fmt, n, 21), _seeds(fmt, n, 22)
    prog = escape_program(fmt, iters, limit)

    whole = seq.run(prog, a, b)

    deposits, flags, status = [], 0, 0
    off = 0
    for size in chunks:
        part = seq.run(prog, a[off:off + size], b[off:off + size])
        deposits += part.deposits
        flags |= part.flags
        status |= part.status
        off += size

    assert deposits == whole.deposits
    assert flags == whole.flags
    assert status == whole.status


# ---- masking ---------------------------------------------------------

def test_inactive_lanes_contribute_no_flags():
    """An inactive lane must raise nothing. If the mask covered only
    register writes, a dead lane's stale registers would still push
    invalid into the sticky word and the flags would depend on how
    many lanes were still running."""
    fmt = FP32
    snan = sf.snan_bits(fmt, 1)
    prog = seq.Program(
        fmt,
        [
            seq.alu(sf.OP_CMPLT, 3, 0, 0, kb=True),   # r3 = r0 < 0.0
            seq.setact(3),                            # everyone drops out
            seq.repeat(4),
            seq.alu(sf.OP_ADD, 4, 1, 0, 1),           # would raise invalid
            seq.deposit(4),
            seq.endrep(),
            seq.halt(),
        ],
        consts=[sf.zero_bits(fmt)],
        max_deposits=4)

    n = 6
    a = [sf.one_bits(fmt)] * n            # 1.0 < 0.0 is false -> inactive
    b = [snan] * n                        # a signaling NaN, never touched
    res = seq.run(prog, a, b)

    assert not any(res.active)
    assert res.flags == 0, "an inactive lane raised a flag"
    assert res.counts == [0] * n
    # the comparison itself is quiet on a non-NaN pair, so nothing but
    # the masked adds could have raised invalid - confirm the program
    # really would have, if the lanes had stayed live
    live = seq.run(seq.Program(fmt, [seq.alu(sf.OP_ADD, 4, 1, 0, 1),
                                     seq.halt()],
                               consts=[sf.zero_bits(fmt)]), a, b)
    assert live.flags & sf.FLAG_INVALID


# ---- deposition ------------------------------------------------------

def test_deposit_overflow_truncates_and_reports():
    fmt = FP32
    prog = seq.Program(
        fmt,
        [seq.repeat(5), seq.alu(sf.OP_ADD, 0, 0, 0, 1), seq.deposit(0),
         seq.endrep(), seq.halt()],
        consts=[sf.one_bits(fmt)],
        max_deposits=2)
    n = 3
    a = [sf.zero_bits(fmt)] * n
    b = [sf.one_bits(fmt)] * n
    res = seq.run(prog, a, b)
    assert res.status & seq.STATUS_DEPOSIT_OVERFLOW
    assert res.counts == [2] * n, "a lane deposited past the cap"
    assert len(res.deposits) == n * 2


def test_deposits_land_at_index_derived_addresses():
    """P2 in its simplest form: lane i owns exactly the slots
    [i*max_deposits, (i+1)*max_deposits) and touches nothing else."""
    fmt = FP32
    maxdep = 3
    prog = seq.Program(
        fmt,
        [seq.repeat(maxdep), seq.alu(sf.OP_ADD, 0, 0, 0, 1),
         seq.deposit(0), seq.endrep(), seq.halt()],
        consts=[sf.one_bits(fmt)],
        max_deposits=maxdep)
    n = 4
    marker = sf.zero_bits(fmt)
    a = [marker] * n
    b = [sf.one_bits(fmt)] * n
    res = seq.run(prog, a, b)
    # every lane ran the same program from the same start, so every
    # lane's window must hold the same sequence
    win = [res.deposits[i * maxdep:(i + 1) * maxdep] for i in range(n)]
    assert all(w == win[0] for w in win)
    assert len(res.deposits) == n * maxdep


# ---- the defects a review found, each with the case that shows it ----

def test_halt_inside_a_loop_is_refused():
    """The one instruction the active mask cannot gate.

    HALT's effect is not per-lane, so with every lane inactive a loop
    body containing one is NOT a no-op: skipping the loop continues the
    program, entering it stops the program. The two differ in deposits,
    in flags and in the final registers - and in deposit COUNTS, which
    is how it breaks P2 as well, since lane i's count then depends on
    whether some other lane was still active.
    """
    with pytest.raises(seq.ProgramError, match="halt inside a loop"):
        seq.Program(FP32, [
            seq.alu(sf.OP_CMPLT, 3, 0, 0, kb=True),
            seq.setact(3),
            seq.repeat(4),
            seq.halt(),
            seq.endrep(),
            seq.actall(),
            seq.deposit(0),
            seq.halt(),
        ], consts=[sf.zero_bits(FP32)], max_deposits=1)
    # outside a loop it is ordinary
    seq.Program(FP32, [seq.repeat(2), seq.endrep(), seq.halt()])


def test_repeat_zero_is_refused_and_would_skip():
    with pytest.raises(seq.ProgramError, match="not a loop"):
        seq.Program(FP32, [seq.encode(seq.REPEAT, ctrl=True, imm=0),
                           seq.endrep(), seq.halt()])


def test_unbounded_trip_counts_are_refused():
    """`validate` claims a program terminates. Four nested repeats of
    2^32-1 fit in 104 bytes and describe 3.4e38 iterations, which is
    finite and not a bound."""
    huge = 0xFFFFFFFF
    insns = [seq.repeat(huge) for _ in range(4)] + \
            [seq.alu(sf.OP_ADD, 0, 0, 0, 0)] + \
            [seq.endrep() for _ in range(4)] + [seq.halt()]
    with pytest.raises(seq.ProgramError, match="worst-case"):
        seq.Program(FP32, insns)
    # a genuinely bounded nest is fine
    ok = [seq.repeat(4), seq.repeat(4), seq.alu(sf.OP_ADD, 0, 0, 0, 0),
          seq.endrep(), seq.endrep(), seq.halt()]
    seq.Program(FP32, ok)


def test_encoding_is_canonical():
    """Fields an instruction does not read must be zero, or the same
    operation has many encodings and the readback hash the design
    relies on for attestation stops being a hash of the program."""
    with pytest.raises(seq.ProgramError, match="does not read"):
        seq.Program(FP32, [seq.encode(seq.DEPOSIT, ra=0, ka=True,
                                      ctrl=True), seq.halt()])
    with pytest.raises(seq.ProgramError, match="does not read"):
        seq.Program(FP32, [seq.encode(seq.SETACT, ra=1, rd=3, ctrl=True),
                           seq.halt()])
    with pytest.raises(seq.ProgramError, match="no immediate"):
        seq.Program(FP32, [seq.encode(sf.OP_FMA, 0, imm=1), seq.halt()])
    # and the digest is stable across a round trip
    p = seq.Program(FP32, [seq.alu(sf.OP_ADD, 0, 0, 0, 1), seq.halt()],
                    consts=[sf.one_bits(FP32)])
    assert p.digest() == seq.Program.from_bytes(p.to_bytes()).digest()


def test_padding_lanes_contribute_nothing():
    """A sequencer cannot rely on a quiet padding VALUE the way an
    elementwise op can: no operand stays quiet through an arbitrary
    program. Lanes at or beyond n start inactive instead."""
    fmt = FP32
    prog = seq.Program(
        fmt,
        [seq.repeat(3), seq.alu(sf.OP_ADD, rd=4, ra=1, rc=1),
         seq.deposit(4), seq.endrep(), seq.halt()],
        max_deposits=3)
    n, real = 8, 5
    a = [sf.one_bits(fmt)] * n
    # only the PADDING lanes carry the signaling NaN, so any flag in
    # the result came from a lane that should never have run
    b = [sf.one_bits(fmt)] * real + [sf.snan_bits(fmt, 1)] * (n - real)
    res = seq.run(prog, a, b, n_active=real)
    assert res.flags == 0, "a padding lane raised a flag"
    assert res.counts[real:] == [0] * (n - real)
    assert all(c == 3 for c in res.counts[:real])
    assert not any(res.active[real:])


def test_inputs_are_masked_to_the_format():
    fmt = FP32
    prog = seq.Program(fmt, [seq.deposit(0), seq.halt()], max_deposits=1)
    res = seq.run(prog, [0xdeadbeefcafe1234], [0], [0])
    assert res.deposits[0] == 0xcafe1234


def test_loader_rejects_a_padded_or_reserved_program():
    p = seq.Program(FP32, [seq.halt()])
    raw = bytearray(p.to_bytes())
    with pytest.raises(seq.ProgramError):
        seq.Program.from_bytes(bytes(raw) + b"\x00")      # trailing bytes
    # Header bytes 24..27 became `flags` at revision 2 and 28..31
    # became `scratch_io` at revision 3. Bits 0 (BANK_EXT) and 1
    # (SCRATCH_IO) are known; everything above them is reserved, and so
    # is the whole of `scratch_io` while its flag is clear. The tile
    # checks both words, which the 0x600 tile did not.
    bad = bytearray(raw)
    bad[24] = 1 << 2                                    # flags[2], unknown
    with pytest.raises(seq.ProgramError, match="reserved"):
        seq.Program.from_bytes(bytes(bad))
    bad = bytearray(raw)
    bad[27] = 0x80                                      # flags[31]
    with pytest.raises(seq.ProgramError, match="reserved"):
        seq.Program.from_bytes(bytes(bad))
    bad = bytearray(raw)
    bad[28] = 1                            # scratch_io without the flag
    with pytest.raises(seq.ProgramError, match="reserved"):
        seq.Program.from_bytes(bytes(bad))
    # ...and a count past the depth, with the flag set. Both halves of
    # the word, because one of the two would be a rule that only half
    # exists.
    for byte, half in ((28, "n_scratch_in"), (30, "n_scratch_out")):
        bad = bytearray(raw)
        bad[24] = seq.FLAG_SCRATCH_IO
        bad[byte] = (seq.SCRATCH_D + 1) & 0xFF
        bad[byte + 1] = (seq.SCRATCH_D + 1) >> 8
        with pytest.raises(seq.ProgramError, match=half):
            seq.Program.from_bytes(bytes(bad))
    with pytest.raises(seq.ProgramError, match="max_deposits"):
        seq.Program(FP32, [seq.halt()], max_deposits=1 << 30)


def test_nested_loops_execute():
    """The suite proved nesting was REJECTED past depth 4 and never
    once ran a nested loop."""
    fmt = FP32
    prog = seq.Program(
        fmt,
        [seq.repeat(3), seq.repeat(4),
         seq.alu(sf.OP_ADD, rd=0, ra=0, rc=0, kc=True),   # r0 += 1.0
         seq.endrep(), seq.endrep(), seq.halt()],
        consts=[sf.one_bits(fmt)])
    res = seq.run(prog, [sf.zero_bits(fmt)], [0], [0])
    acc = sf.zero_bits(fmt)
    for _ in range(12):
        acc, _ = sf.compute(fmt, sf.OP_ADD, acc, 0, sf.one_bits(fmt))
    assert res.regs[0][0] == acc, "3 x 4 iterations did not happen"


# ---- the property, fuzzed -------------------------------------------

def test_p3_fuzz_early_exit_is_invisible():
    """The real gate on P3: random valid programs, run with the
    optimisation forced on and off, whole machine state compared."""
    rng = random.Random(2026)
    fmt = FP32
    checked = 0
    saved = 0
    for _ in range(400):
        insns, consts = seq.random_program(fmt, rng)
        try:
            prog = seq.Program(fmt, insns, consts, max_deposits=3)
        except seq.ProgramError:
            continue
        n = rng.randint(1, 6)
        a, b, c = (seq.random_inputs(fmt, rng, n) for _ in range(3))
        fast = seq.run(prog, a, b, c, early_exit=True)
        slow = seq.run(prog, a, b, c, early_exit=False)
        assert fast.state() == slow.state(), (
            f"early exit changed an observable\n{[hex(i) for i in insns]}")
        checked += 1
        if fast.insns_executed < slow.insns_executed:
            saved += 1
    assert checked > 200, f"only {checked} programs were valid"
    assert saved > 0, ("the early exit never fired in the whole fuzz, so "
                       "it proved nothing")


def test_p3_fuzz_finds_the_halt_hole_when_the_rule_is_removed():
    """The rule banning HALT in a loop is load-bearing, and this shows
    it: the same fuzz, with that one construction allowed past the
    validator, diverges."""
    rng = random.Random(7)
    fmt = FP32
    diverged = 0
    for _ in range(600):
        insns, consts = seq.random_program(fmt, rng, allow_halt_in_loop=True)
        # bypass the validator deliberately - this is the program shape
        # validate() exists to refuse
        prog = seq.Program.__new__(seq.Program)
        prog.fmt, prog.insns, prog.consts, prog.max_deposits = \
            fmt, insns, consts, 3
        # __init__ is skipped on purpose, so the fields it would have
        # set are set here by hand. Without them `run` raises on every
        # program, every iteration lands in the `except` below, and this
        # control passes by never testing anything - which is precisely
        # the way a negative control dies quietly, and why the assertion
        # at the end of this test counts divergences rather than
        # trusting the loop ran.
        prog.flags, prog._n_consts = 0, len(consts)
        # Revision 3 adds two more that `run()` reads on entry, for the
        # same reason and with the same failure mode if they are
        # missing: the control stops diverging because it stops
        # running.
        prog.n_scratch_in, prog.n_scratch_out = 0, 0
        n = rng.randint(2, 6)
        a, b, c = (seq.random_inputs(fmt, rng, n) for _ in range(3))
        try:
            fast = seq.run(prog, a, b, c, early_exit=True)
            slow = seq.run(prog, a, b, c, early_exit=False)
        except Exception:
            continue
        if fast.state() != slow.state():
            diverged += 1
    assert diverged > 0, (
        "the fuzz could not break P3 even with HALT allowed in loops, "
        "so this test is not watching what it claims to")


def test_p2_fuzz_partitioning_is_invisible():
    """P2, fuzzed. It is a corollary of P3 rather than an independent
    property - lane i's deposit COUNT depends on the shared program
    counter, hence on the cohort - so it is worth fuzzing the two
    together."""
    rng = random.Random(99)
    fmt = FP32
    for _ in range(250):
        insns, consts = seq.random_program(fmt, rng)
        try:
            prog = seq.Program(fmt, insns, consts, max_deposits=3)
        except seq.ProgramError:
            continue
        n = 8
        a, b, c = (seq.random_inputs(fmt, rng, n) for _ in range(3))
        whole = seq.run(prog, a, b, c)
        for cuts in ([8], [4, 4], [1, 3, 4], [2, 2, 2, 2], [1] * 8):
            dep, fl, stt, off = [], 0, 0, 0
            for k in cuts:
                part = seq.run(prog, a[off:off + k], b[off:off + k],
                               c[off:off + k])
                dep += part.deposits
                fl |= part.flags
                stt |= part.status
                off += k
            assert dep == whole.deposits, f"partition {cuts} changed the answer"
            assert fl == whole.flags
            assert stt == whole.status


def test_run_is_repeatable():
    fmt = FP64
    prog = escape_program(fmt, 10, sf.one_bits(fmt))
    a, b = _seeds(fmt, 16, 31), _seeds(fmt, 16, 32)
    first = seq.run(prog, a, b)
    for _ in range(3):
        assert seq.run(prog, a, b).state() == first.state()


# ---- indexed constants (kx) and IMUL, 2026-09-07 ---------------------
#
# Two additions the atlas port asked for (docs/ATLAS.md, "What the
# program model lacks", items 1 and 2). They are tested here rather
# than in test_softfloat.py because only one of them is arithmetic:
# `kx` is an addressing mode and lives entirely in this file's decode
# and validator.

def _bank(fmt, n):
    """A bank of n distinguishable constants. Distinguishable matters:
    if two entries were equal an off-by-one index would read the right
    answer from the wrong place and the test would pass."""
    return [(i * 0x0101_0101 + 0x11) & ((1 << fmt.width) - 1)
            for i in range(n)]


def test_kx_reaches_the_whole_bank():
    """The point of the feature: a constant index above fifteen, which
    no encoding could name before."""
    fmt = FP32
    consts = _bank(fmt, 200)
    for idx in (0, 15, 16, 17, 99, 199):
        prog = seq.Program(
            fmt,
            [seq.alu(sf.OP_IOR, 3, ra=5, rb=idx, kb=True, kx=True),
             seq.deposit(3), seq.halt()],
            consts=consts, max_deposits=1)
        res = seq.run(prog, [0], [0])
        assert res.deposits[0] == consts[idx], (
            f"constant {idx} did not reach the operand")


def test_kx_and_plain_agree_where_both_can_encode():
    """Below sixteen the two forms are two spellings of one operation,
    so they must compute the same thing - which is what makes the new
    bit a widening rather than a change."""
    fmt = FP64
    consts = _bank(fmt, 16)
    rng = random.Random(1234)
    for _ in range(200):
        idx = rng.randrange(16)
        op = rng.choice([sf.OP_FMA, sf.OP_ADD, sf.OP_MUL, sf.OP_SELECT,
                         sf.OP_IXOR, sf.OP_IMUL])
        body = dict(rd=4, ra=0, rb=idx, rc=1, kb=True)
        a = seq.random_inputs(fmt, rng, 4)
        b = seq.random_inputs(fmt, rng, 4)
        plain = seq.Program(fmt, [seq.alu(op, **body), seq.deposit(4),
                                  seq.halt()], consts, 1)
        wide = seq.Program(fmt, [seq.alu(op, kx=True, **body),
                                 seq.deposit(4), seq.halt()], consts, 1)
        assert plain.insns != wide.insns, "the two forms encode the same"
        assert seq.run(plain, a, b).state() == seq.run(wide, a, b).state()


def test_kx_refusals():
    fmt = FP32
    consts = _bank(fmt, 40)

    def prog(word):
        return seq.Program(fmt, [word, seq.halt()], consts, 1)

    # an index past the bank, reachable only through kx
    with pytest.raises(seq.ProgramError, match="constant 40"):
        prog(seq.alu(sf.OP_ADD, 0, rb=40, kb=True, kx=True))
    # a non-zero operand field on an operand whose index came from imm
    with pytest.raises(seq.ProgramError, match="must be zero"):
        prog(seq.encode(sf.OP_ADD, 0, rb=3, kb=True, kx=True, imm=5 << 8))
    # a non-zero imm byte for an operand that names a register
    with pytest.raises(seq.ProgramError, match="not read and must be zero"):
        prog(seq.encode(sf.OP_ADD, 0, ra=3, rb=0, kb=True, kx=True,
                        imm=(2 << 0) | (5 << 8)))
    # imm[31], which stays reserved so a later form can use it. The
    # window was imm[31:24] until revision 2 took the low four of those
    # for the register high bits and revision 3 took imm[30:28] for the
    # ninth constant-index bits, so bit 31 is all that is left of it -
    # and is deliberately left, because the largest positive in the
    # corpus needs 464 of the 512 the ninth bit reaches.
    with pytest.raises(seq.ProgramError, match=r"imm\[31\]"):
        prog(seq.encode(sf.OP_ADD, 0, rb=0, kb=True, kx=True,
                        imm=(5 << 8) | (1 << 31)))
    # ...and imm[28] is now ra's ninth index bit, so it is refused for
    # a DIFFERENT reason - ra names a register here, and a ninth bit on
    # an operand that is not a kx constant is an unread field.
    with pytest.raises(seq.ProgramError,
                       match=r"ninth constant-index bit imm\[28\]"):
        prog(seq.encode(sf.OP_ADD, 0, rb=0, kb=True, kx=True,
                        imm=(5 << 8) | (1 << 28)))
    # ...and imm[24] is NOT reserved any more: it is rd[4], and rd is
    # always a register, so a kx instruction may name r16..r31 as its
    # destination. This is the positive control for the line above.
    prog(seq.alu(sf.OP_ADD, 30, rb=20, kb=True, kx=True))
    # kx with nothing to select
    with pytest.raises(seq.ProgramError, match="selects nothing"):
        prog(seq.encode(sf.OP_ADD, 0, kx=True))
    # kx on a control instruction: a field it does not read
    with pytest.raises(seq.ProgramError, match="does not read kx"):
        seq.Program(fmt, [seq.encode(seq.REPEAT, ctrl=True, imm=2,
                                     kx=True), seq.endrep(), seq.halt()],
                    consts, 1)
    with pytest.raises(seq.ProgramError, match="does not read kx"):
        seq.Program(fmt, [seq.encode(seq.DEPOSIT, ra=1, ctrl=True,
                                     kx=True), seq.halt()], consts, 1)


def test_kx_is_the_version_guard():
    """An old loader refuses a kx program by the reserved-bit rule it
    already has, which is why the feature needs no header version bump.
    The old rule is reconstructed here rather than cited: bit 30
    non-zero was the whole of it."""
    fmt = FP32
    word = seq.alu(sf.OP_ADD, 0, rb=200, kb=True, kx=True)
    assert (word >> 30) & 1, "a kx instruction must set bit 30"

    def old_loader_accepts(w):
        return not ((w >> 30) & 1)

    assert not old_loader_accepts(word)
    assert old_loader_accepts(seq.alu(sf.OP_ADD, 0, rb=2, kb=True))


def test_imul_matches_integer_arithmetic():
    """IMUL against Python's own integers, over the directed corpus
    docs/studies/OPT-D-contract.md names - zeros, ones, powers of two,
    2^k-1, the two lowbias32 constants, the wraparound boundary - plus
    randoms, at every format. The zero-extension rule is what the wide
    formats are here for."""
    rng = random.Random(20260907)
    m32 = 0xFFFFFFFF
    directed = [0, 1, 2, 3, 0xFFFF, 0x10000, 0x7FFFFFFF, 0x80000000,
                0xFFFFFFFF, 0x7FEB352D, 0x846CA68B]
    directed += [1 << k for k in range(32)]
    directed += [(1 << k) - 1 for k in range(1, 33)]
    for name in ("fp32", "fp64", "fp128", "fp256"):
        fmt = FORMATS[name]
        top = (1 << fmt.width) - 1
        pairs = [(x, y) for x in directed for y in directed]
        pairs += [(rng.getrandbits(fmt.width), rng.getrandbits(fmt.width))
                  for _ in range(2000)]
        for xa, xb in pairs:
            got, fl = sf.compute(fmt, sf.OP_IMUL, xa & top, xb & top, 0)
            want = ((xa & m32) * (xb & m32)) & m32
            assert got == want, f"{name} imul {xa:x} {xb:x}"
            assert fl == 0, "IMUL is quiet, always"
            assert got >> 32 == 0, "the result is zero-extended, not merged"


def test_imul_ignores_the_bits_above_thirty_two():
    """The 32-bit definition, stated as a property: no bit of either
    operand above 31 can change the answer. This is the half of the
    contract a W-bit implementation would silently break at fp64 and
    above."""
    rng = random.Random(7)
    for name in ("fp64", "fp128", "fp256"):
        fmt = FORMATS[name]
        for _ in range(500):
            lo_a, lo_b = rng.getrandbits(32), rng.getrandbits(32)
            hi_a = rng.getrandbits(fmt.width - 32) << 32
            hi_b = rng.getrandbits(fmt.width - 32) << 32
            base, _ = sf.compute(fmt, sf.OP_IMUL, lo_a, lo_b, 0)
            wide, _ = sf.compute(fmt, sf.OP_IMUL, lo_a | hi_a,
                                 lo_b | hi_b, 0)
            assert base == wide, f"{name}: a high bit reached the product"


def test_imul_builds_lowbias32():
    """The operation exists for one caller. This is that caller, run as
    a program: atlas-engine's draw hash, whose two multiplies are what
    docs/ATLAS.md's census could not map onto the ISA.

        x ^= x >> 16;  x *= 0x7feb352d;
        x ^= x >> 15;  x *= 0x846ca68b;
        x ^= x >> 16

    The constants are the hash's, so they are the one place here where
    a literal is the specification rather than a transcription."""
    fmt = FP32
    K1, K2 = 0x7FEB352D, 0x846CA68B
    consts = [16, 15, K1, K2]
    prog = seq.Program(
        fmt,
        [
            seq.alu(sf.OP_ISHR, 1, 0, 0, kb=True),         # r1 = x >> 16
            seq.alu(sf.OP_IXOR, 0, 0, 1),
            seq.alu(sf.OP_IMUL, 0, 0, 2, kb=True),         # x *= K1
            seq.alu(sf.OP_ISHR, 1, 0, 1, kb=True),         # r1 = x >> 15
            seq.alu(sf.OP_IXOR, 0, 0, 1),
            seq.alu(sf.OP_IMUL, 0, 0, 3, kb=True),         # x *= K2
            seq.alu(sf.OP_ISHR, 1, 0, 0, kb=True),         # r1 = x >> 16
            seq.alu(sf.OP_IXOR, 0, 0, 1),
            seq.deposit(0), seq.halt(),
        ],
        consts=consts, max_deposits=1)

    def lowbias32(x):
        x ^= x >> 16
        x = (x * K1) & 0xFFFFFFFF
        x ^= x >> 15
        x = (x * K2) & 0xFFFFFFFF
        x ^= x >> 16
        return x

    seeds = list(range(64)) + [0xFFFFFFFF, 0x80000000, 0xDEADBEEF]
    res = seq.run(prog, seeds, [0] * len(seeds))
    assert res.flags == 0, "the draw stream must not signal"
    for i, s in enumerate(seeds):
        assert res.deposits[i] == lowbias32(s), f"seed {s:#x}"


def test_extended_fuzz_generates_both_features():
    """The corpus arm the runner's seq stage uses. If it stopped
    producing kx instructions or IMULs the differential would still
    pass, and would be checking nothing new - so the generator is
    checked for what it generates."""
    rng = random.Random(11)
    saw_kx = saw_imul = saw_wide_index = 0
    for _ in range(200):
        insns, consts = seq.random_program(FP32, rng, extended=True)
        for w in insns:
            d = seq.decode(w)
            if d["ctrl"]:
                continue
            if d["op"] == sf.OP_IMUL:
                saw_imul += 1
            if d["kx"]:
                saw_kx += 1
                for idx, is_const in seq.sources(d):
                    if is_const and idx >= seq.KADDR_PLAIN:
                        saw_wide_index += 1
        assert len(consts) > seq.KADDR_PLAIN
    assert saw_imul > 0 and saw_kx > 0 and saw_wide_index > 0, (
        f"imul={saw_imul} kx={saw_kx} wide={saw_wide_index}")


def test_default_fuzz_is_unchanged_by_the_extension():
    """The existing corpus is byte-identical. `tb/test_seq_core.py`
    generates its fuzz suite from a fixed seed, and a generator that
    reshuffled its draws would silently retire the 62 programs the RTL
    has been held to. The default path must draw nothing new."""
    known = seq.random_program(FP32, random.Random(5))
    again = seq.random_program(FP32, random.Random(5))
    assert known == again
    # and the extended arm is a different corpus, not the same one
    ext = seq.random_program(FP32, random.Random(5), extended=True)
    assert ext != known


# ---- revision 2: the per-run constant bank ---------------------------

def _bank_program(fmt, n_consts=4, max_deposits=2):
    """A BANK_EXT program: the image names constants it does not carry.

    `kx` where an index above fifteen is reachable, and a register above
    fifteen either way, so the two revision-2 features are exercised in
    one image rather than in two that never meet.
    """
    return seq.Program(
        fmt,
        [seq.alu(sf.OP_ADD, 20, ra=0, rc=n_consts - 1, kc=True,
                 kx=n_consts > seq.KADDR_PLAIN),
         seq.deposit(20),
         seq.alu(sf.OP_MUL, 21, ra=20, rb=0),
         seq.deposit(21),
         seq.halt()],
        flags=seq.FLAG_BANK_EXT, n_consts=n_consts,
        max_deposits=max_deposits)


def test_bank_ext_image_carries_no_constant_section():
    """`bytes == 32 + 8 * n_insns`, whatever n_consts says - that IS the
    feature: one image per positive, with the levers riding as data."""
    fmt = FP64
    p = _bank_program(fmt, n_consts=6)
    img = p.to_bytes()
    assert len(img) == 32 + 8 * len(p.insns), (
        "a BANK_EXT image is header then instructions, with no constant "
        "section - so its length cannot depend on n_consts")
    assert p.n_consts == 6 and p.consts == []
    back = seq.Program.from_bytes(img)
    assert back.flags == seq.FLAG_BANK_EXT
    assert back.n_consts == 6 and back.consts == []
    assert back.to_bytes() == img
    # n_consts still bounds the instruction stream's constant indices
    with pytest.raises(seq.ProgramError, match="bank holds 2"):
        seq.Program(fmt, [seq.alu(sf.OP_ADD, 0, rc=5, kc=True), seq.halt()],
                    flags=seq.FLAG_BANK_EXT, n_consts=2)


def test_bank_ext_runs_on_the_bank_it_is_given():
    """The same image, two banks, two answers - each identical to the
    self-contained program built with those constants inside it."""
    fmt = FP32
    n = 4
    a = [sf.one_bits(fmt), sf.zero_bits(fmt), sf.max_normal_bits(fmt),
         sf.min_subnormal_bits(fmt)]
    for values in ([sf.one_bits(fmt), sf.zero_bits(fmt),
                    sf.max_normal_bits(fmt), sf.one_bits(fmt)],
                   [sf.zero_bits(fmt, 1), sf.min_subnormal_bits(fmt),
                    sf.inf_bits(fmt), sf.qnan_bits(fmt)]):
        ext = _bank_program(fmt, n_consts=4)
        got = seq.run(ext, a, [0] * n, [0] * n, bank=values)
        # the same program with the constants baked into the image
        inline = seq.Program(
            fmt,
            [seq.alu(sf.OP_ADD, 20, ra=0, rc=3, kc=True),
             seq.deposit(20),
             seq.alu(sf.OP_MUL, 21, ra=20, rb=0),
             seq.deposit(21),
             seq.halt()],
            consts=values, max_deposits=2)
        want = seq.run(inline, a, [0] * n, [0] * n)
        assert got.state() == want.state(), (
            "where the constants LIVE must not change a single bit of "
            "what the program computes")


def test_bank_refusals():
    fmt = FP32
    n = 2
    a = [sf.one_bits(fmt)] * n
    ext = _bank_program(fmt, n_consts=3)
    with pytest.raises(seq.ProgramError, match="carries no constants"):
        seq.run(ext, a, [0] * n, [0] * n)                    # missing
    with pytest.raises(seq.ProgramError, match="header declares 3"):
        seq.run(ext, a, [0] * n, [0] * n, bank=[0, 0])       # too few
    with pytest.raises(seq.ProgramError, match="header declares 3"):
        seq.run(ext, a, [0] * n, [0] * n, bank=[0] * 4)      # too many
    with pytest.raises(seq.ProgramError, match="does not fit the format"):
        seq.run(ext, a, [0] * n, [0] * n, bank=[0, 0, 1 << 40])
    # ...and a self-contained program refuses a bank, because two
    # sources for one constant is one source too many
    inline = seq.Program(fmt, [seq.alu(sf.OP_ADD, 0, rc=0, kc=True),
                               seq.halt()], consts=[sf.one_bits(fmt)])
    with pytest.raises(seq.ProgramError, match="carries its own constants"):
        seq.run(inline, a, [0] * n, [0] * n, bank=[sf.one_bits(fmt)])
    # a BANK_EXT program cannot also carry a constant section
    with pytest.raises(seq.ProgramError, match="carries no constant section"):
        seq.Program(fmt, [seq.halt()], consts=[sf.one_bits(fmt)],
                    flags=seq.FLAG_BANK_EXT, n_consts=1)


def test_digest_covers_the_bank():
    """What ran is ONE hash of image and data together: the image alone
    cannot distinguish two runs of a BANK_EXT program."""
    import hashlib
    fmt = FP32
    p = _bank_program(fmt, n_consts=3)
    b1 = [sf.one_bits(fmt), sf.zero_bits(fmt), sf.one_bits(fmt)]
    b2 = [sf.one_bits(fmt), sf.zero_bits(fmt), sf.zero_bits(fmt)]
    assert p.digest(b1) != p.digest(b2), \
        "two banks under one image must not attest identically"
    assert p.digest(b1) == p.digest(list(b1))
    # and the image-only digest is still the image's
    assert p.digest() == hashlib.sha256(p.to_bytes()).hexdigest()


# ---- revision 3: the per-lane scratch ---------------------------------
#
# R4 is four control codes and one memory; R5 is the block that fills
# it before a run and empties it after. Both are about STATE THAT
# SURVIVES, which is why every case below checks the scratch itself as
# well as what the program deposited: a load that quietly read +0 would
# pass a deposit-only check on half of these programs.

def test_scratch_static_round_trip_including_the_highest_slot():
    fmt = FP32
    top = seq.SCRATCH_D - 1
    prog = seq.Program(fmt, [
        seq.stl(0, 0), seq.stl(1, top),
        seq.ldl(9, top), seq.ldl(10, 0),
        seq.deposit(9), seq.deposit(10), seq.halt()],
        max_deposits=2)
    a = [sf.one_bits(fmt), sf.max_normal_bits(fmt)]
    b = [sf.min_subnormal_bits(fmt), sf.inf_bits(fmt)]
    res = seq.run(prog, a, b)
    for i in range(2):
        assert res.deposits[i * 2] == b[i], "the top slot did not survive"
        assert res.deposits[i * 2 + 1] == a[i]
        assert res.scratch[i][top] == b[i]
        assert res.scratch[i][0] == a[i]
    # no flags: a load and a store are not arithmetic, so an infinity
    # and a subnormal pass through them silently
    assert res.flags == 0


def test_scratch_indexed_reduces_past_the_depth():
    """STX/LDX are NOT refused for an index past the depth - the slot
    is data, so the contract reduces it modulo the depth. Lanes whose
    indices differ by whole multiples of the depth must land on one
    slot."""
    fmt = FP32
    prog = seq.Program(fmt, [
        seq.stx(0, 1), seq.ldx(4, 2), seq.deposit(4), seq.halt()],
        max_deposits=1)
    val = [0x11111111, 0x22222222, 0x33333333]
    idx = [5, 5 + seq.SCRATCH_D, 5 + 3 * seq.SCRATCH_D]
    rd = [5 + 7 * seq.SCRATCH_D, 5, 5 + seq.SCRATCH_D]
    res = seq.run(prog, val, idx, rd)
    assert res.deposits == val, [hex(v) for v in res.deposits]
    for i in range(3):
        assert res.scratch[i][5] == val[i]
    # the reduction really was exercised: only lane 0 wrote a slot its
    # raw index already named
    assert max(idx) >= seq.SCRATCH_D and max(rd) >= seq.SCRATCH_D


def test_a_store_in_an_all_inactive_loop_body_does_nothing():
    """P3 for the scratch. A store is a register write for the active
    mask's purposes, so a loop body every lane has dropped out of must
    leave the scratch exactly as it was - and the early exit, which
    only makes the body run FEWER times, must not change the answer."""
    fmt = FP32
    zero, one = sf.zero_bits(fmt), sf.one_bits(fmt)
    prog = seq.Program(fmt, [
        seq.stl(0, 4),            # slot 4 := r0, while every lane is live
        seq.setact(1),            # r1 is +0, so every lane drops out
        seq.repeat(9),
        seq.stl(2, 4),            # ...and this must not reach slot 4
        seq.stx(2, 2),
        seq.endrep(),
        seq.ldl(5, 4), seq.deposit(5), seq.halt()],
        max_deposits=1)
    n = 4
    a = [one] * n
    res = seq.run(prog, a, [zero] * n, [0xdeadbeef] * n)
    slow = seq.run(prog, a, [zero] * n, [0xdeadbeef] * n, early_exit=False)
    assert res.state() == slow.state(), \
        "the early exit changed the scratch, so a store escaped the mask"
    for i in range(n):
        assert res.scratch[i][4] == one, "an inactive lane stored"
        assert res.scratch[i][0xdeadbeef & seq.SCRATCH_MASK] == zero, \
            "an inactive lane's indexed store landed"
    # the deposit is masked by the same bit, so nothing was recorded
    assert res.counts == [0] * n


def test_scratch_io_block_in_and_out():
    fmt = FP32
    prog = seq.Program(fmt, [
        seq.ldl(3, 0), seq.ldl(4, 1),
        seq.alu(sf.OP_ADD, rd=5, ra=3, rc=4),
        seq.stl(5, 2), seq.deposit(5), seq.halt()],
        max_deposits=1, flags=seq.FLAG_SCRATCH_IO,
        n_scratch_in=2, n_scratch_out=3)
    one, two = sf.one_bits(fmt), 0x40000000
    n = 3
    block = [one, one, one, two, two, two]
    res = seq.run(prog, [0] * n, [0] * n, scratch_in=block)
    assert len(res.scratch_out) == n * 3
    for i in range(n):
        want, _ = sf.compute(fmt, sf.OP_ADD, block[2 * i], 0,
                             block[2 * i + 1])
        assert res.scratch_out[i * 3:i * 3 + 3] == \
            [block[2 * i], block[2 * i + 1], want]
        assert res.deposits[i] == want
    # the header word is the two counts, packed, and survives the bytes
    assert prog.scratch_io_word == 2 | (3 << 16)
    again = seq.Program.from_bytes(prog.to_bytes())
    assert again.to_bytes() == prog.to_bytes()
    assert (again.n_scratch_in, again.n_scratch_out) == (2, 3)


def test_scratch_io_resumes_a_run():
    """The ask R5 answers: a program whose state leaves through
    `scratch out` and comes back through `scratch in` computes the same
    thing in two calls as in one. Three iterations, then three more,
    against six in a single run."""
    fmt = FP32
    one = sf.one_bits(fmt)
    body = [seq.ldl(3, 0),
            seq.alu(sf.OP_ADD, rd=3, ra=3, rc=0, kc=True),
            seq.stl(3, 0), seq.deposit(3)]

    def prog(trips, maxdep):
        return seq.Program(fmt, [seq.repeat(trips)] + body
                           + [seq.endrep(), seq.halt()],
                           consts=[one], max_deposits=maxdep,
                           flags=seq.FLAG_SCRATCH_IO,
                           n_scratch_in=1, n_scratch_out=1)
    n = 2
    zeros = [sf.zero_bits(fmt)] * n
    whole = seq.run(prog(6, 6), [0] * n, [0] * n, scratch_in=zeros)
    first = seq.run(prog(3, 3), [0] * n, [0] * n, scratch_in=zeros)
    second = seq.run(prog(3, 3), [0] * n, [0] * n,
                     scratch_in=first.scratch_out)
    for i in range(n):
        assert first.deposits[i * 3:(i + 1) * 3] == \
            whole.deposits[i * 6:i * 6 + 3]
        assert second.deposits[i * 3:(i + 1) * 3] == \
            whole.deposits[i * 6 + 3:(i + 1) * 6], \
            "the resumed half does not equal the second half of one run"


def test_scratch_io_padding_lanes_read_and_write_nothing():
    """A lane at or past the caller's element count is not the
    caller's: it receives no scratch input and contributes no scratch
    output, exactly as it receives no deposit slot."""
    fmt = FP32
    prog = seq.Program(fmt, [seq.ldl(3, 0), seq.stl(3, 1), seq.halt()],
                       max_deposits=1, flags=seq.FLAG_SCRATCH_IO,
                       n_scratch_in=1, n_scratch_out=2)
    n, real = 5, 3
    block = [0x1000 + i for i in range(n)]
    res = seq.run(prog, [0] * n, [0] * n, scratch_in=block,
                  n_active=real)
    for i in range(real):
        assert res.scratch_out[i * 2:i * 2 + 2] == [block[i], block[i]]
    for i in range(real, n):
        assert res.scratch_out[i * 2:i * 2 + 2] == [0, 0], \
            "a padding lane wrote its scratch out"
        assert res.scratch[i] == [0] * seq.SCRATCH_D, \
            "a padding lane was preloaded"


def test_scratch_refusals():
    fmt = FP32
    # a STATIC slot past the depth, refused by name - at the assembler
    # helper, and again in validate() for a hand-built word
    with pytest.raises(seq.ProgramError, match="scratch slot"):
        seq.stl(0, seq.SCRATCH_D)
    for code in (seq.STL, seq.LDL):
        word = seq.encode(code, ctrl=True, imm=seq.SCRATCH_D)
        with pytest.raises(seq.ProgramError, match="a lane owns"):
            seq.Program(fmt, [word, seq.halt()])
    # ...and the highest legal one is not refused
    seq.Program(fmt, [seq.stl(0, seq.SCRATCH_D - 1), seq.halt()])
    # imm[23:0] is read by nothing on the indexed forms
    with pytest.raises(seq.ProgramError,
                       match="sets a bit it does not read"):
        seq.Program(fmt, [seq.encode(seq.STX, ra=1, rb=2, ctrl=True,
                                     imm=1), seq.halt()])
    # fields no scratch code reads
    with pytest.raises(seq.ProgramError, match="does not read rc"):
        seq.Program(fmt, [seq.encode(seq.STL, ra=1, rc=2, ctrl=True),
                          seq.halt()])
    with pytest.raises(seq.ProgramError, match="does not read rnd"):
        seq.Program(fmt, [seq.encode(seq.LDX, rd=1, rb=2, ctrl=True,
                                     rnd=sf.RND_RTZ), seq.halt()])
    with pytest.raises(seq.ProgramError, match="does not read ka"):
        seq.Program(fmt, [seq.encode(seq.LDL, rd=1, ctrl=True, ka=True),
                          seq.halt()])
    # LDL writes rd, so rd's high bit is legal there and ra's is not
    seq.Program(fmt, [seq.ldl(20, 3), seq.halt()])
    with pytest.raises(seq.ProgramError,
                       match="sets a bit it does not read"):
        seq.Program(fmt, [seq.encode(seq.LDL, rd=1, ctrl=True,
                                     imm=1 << seq.REG_HI_SHIFT["ra"]),
                          seq.halt()])
    # the header's own three
    with pytest.raises(seq.ProgramError, match="without flags.SCRATCH_IO"):
        seq.Program(fmt, [seq.halt()], n_scratch_in=1)
    with pytest.raises(seq.ProgramError, match="past the"):
        seq.Program(fmt, [seq.halt()], flags=seq.FLAG_SCRATCH_IO,
                    n_scratch_out=seq.SCRATCH_D + 1)
    with pytest.raises(seq.ProgramError, match="does not know"):
        seq.Program(fmt, [seq.halt()], flags=1 << 2)
    # and the block's, which are the bank's refusals in the same shape
    p = seq.Program(fmt, [seq.halt()], flags=seq.FLAG_SCRATCH_IO,
                    n_scratch_in=2)
    with pytest.raises(seq.ProgramError, match="supply 4 values"):
        seq.run(p, [0, 0], [0, 0])
    with pytest.raises(seq.ProgramError, match="holds 3 values"):
        seq.run(p, [0, 0], [0, 0], scratch_in=[0, 0, 0])
    plain = seq.Program(fmt, [seq.halt()])
    with pytest.raises(seq.ProgramError,
                       match="declares no scratch input"):
        seq.run(plain, [0], [0], scratch_in=[0])


def test_scratch_fuzz_arm_leaves_the_old_corpus_alone():
    """The `scratch` arm follows `extended` and `wide_regs`: off, it
    draws nothing from rng, so every corpus an existing seed generates
    is the corpus it generated before. Checked rather than asserted,
    because this is exactly the kind of claim that quietly stops being
    true."""
    for seed in range(120):
        rng_a = random.Random(seed)
        rng_b = random.Random(seed)
        assert (seq.random_program(FP32, rng_a)
                == seq.random_program(FP32, rng_b, scratch=False))
    # ...and on, it really does emit all four codes, in loadable programs
    seen = set()
    rng = random.Random(7)
    for _ in range(80):
        insns, consts = seq.random_program(FP32, rng, scratch=True,
                                           wide_regs=True)
        for w in insns:
            d = seq.decode(w)
            if d["ctrl"] and d["op"] in (seq.STL, seq.LDL, seq.STX,
                                         seq.LDX):
                seen.add(d["op"])
        seq.Program(FP32, insns, consts, 2)
    assert seen == {seq.STL, seq.LDL, seq.STX, seq.LDX}, seen


# ---- revision 3: the ninth constant-index bit -------------------------

def test_kx9_reaches_five_hundred_and_twelve():
    fmt = FP32
    consts = _bank(fmt, 512)
    for idx in (0, 255, 256, 511):
        p = seq.Program(fmt, [
            seq.alu(sf.OP_ADD, 0, ra=0, rc=idx, kc=True, kx=True),
            seq.deposit(0), seq.halt()], consts, 1)
        res = seq.run(p, [sf.zero_bits(fmt)], [0], [0])
        want, _ = sf.compute(fmt, sf.OP_ADD, sf.zero_bits(fmt), 0,
                             consts[idx])
        assert res.deposits[0] == want, \
            f"index {idx} read the wrong constant"
    # the ninth bit lands where the contract says it does
    d = seq.decode(seq.alu(sf.OP_ADD, 0, rc=300, kc=True, kx=True))
    assert (d["imm"] >> seq.KX9_SHIFT["rc"]) & 1 == 1
    assert (d["imm"] >> seq.KX_SHIFT[2]) & 0xFF == 300 & 0xFF
    assert seq.sources(d)[2] == (300, True)


def test_kx9_refusals():
    fmt = FP32
    consts = _bank(fmt, 512)
    with pytest.raises(seq.ProgramError, match="outside 0..511"):
        seq.alu(sf.OP_ADD, 0, rb=512, kb=True, kx=True)
    # a ninth bit set on an operand that names a REGISTER
    for key, shift in seq.KX9_SHIFT.items():
        word = seq.encode(sf.OP_ADD, 0, rb=0, kb=True, kx=True,
                          imm=(5 << 8) | (1 << shift))
        if key == "rb":
            # rb IS the constant here, so its ninth bit is read: the
            # index is 261, which a 512-entry bank holds
            seq.Program(fmt, [word, seq.halt()], consts, 1)
            continue
        with pytest.raises(
                seq.ProgramError,
                match=rf"ninth constant-index bit imm\[{shift}\]"):
            seq.Program(fmt, [word, seq.halt()], consts, 1)
    # imm[31] is what is left of the reserved window
    with pytest.raises(seq.ProgramError, match=r"imm\[31\]"):
        seq.Program(fmt, [seq.encode(sf.OP_ADD, 0, rb=0, kb=True,
                                     kx=True, imm=(5 << 8) | (1 << 31)),
                          seq.halt()], consts, 1)
    # without kx the whole of imm[30:28] is an unread field
    with pytest.raises(seq.ProgramError, match="63:32 must be zero"):
        seq.Program(fmt, [seq.encode(sf.OP_ADD, 0, ra=1, imm=1 << 29),
                          seq.halt()], consts, 1)
