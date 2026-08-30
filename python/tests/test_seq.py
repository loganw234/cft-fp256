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
    rng = random.Random(4)
    for _ in range(2000):
        fields = dict(
            op=rng.randrange(256), rd=rng.randrange(16),
            ra=rng.randrange(16), rb=rng.randrange(16),
            rc=rng.randrange(16), rnd=rng.randrange(5),
            ka=bool(rng.getrandbits(1)), kb=bool(rng.getrandbits(1)),
            kc=bool(rng.getrandbits(1)), ctrl=bool(rng.getrandbits(1)),
            imm=rng.randrange(1 << 32))
        d = seq.decode(seq.encode(**fields))
        for k, v in fields.items():
            assert d[k] == v, f"{k} did not survive the round trip"
        assert d["rsv"] == 0


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
        seq.encode(sf.OP_FMA, rd=16)                            # register
    with pytest.raises(seq.ProgramError):
        seq.encode(sf.OP_FMA, rnd=5)                            # reserved
    with pytest.raises(seq.ProgramError):
        seq.Program(FP32, [seq.encode(sf.OP_FMA, 0) | (1 << 30)])  # rsv


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
    bad = bytearray(raw)
    bad[24] = 1                                            # reserved word
    with pytest.raises(seq.ProgramError, match="reserved"):
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

def _random_program(fmt, rng, allow_halt_in_loop=False):
    """A random program that validate() accepts (unless the caller asks
    for the one construction that breaks P3, which is how the fuzz
    demonstrates the rule is load-bearing rather than decorative)."""
    insns = []
    depth = 0
    nconst = 3
    for _ in range(rng.randint(4, 22)):
        pick = rng.random()
        if pick < 0.45:
            op = rng.choice([sf.OP_FMA, sf.OP_ADD, sf.OP_SUB, sf.OP_MUL,
                             sf.OP_ABS, sf.OP_MIN, sf.OP_MAXNUM,
                             sf.OP_CMPLT, sf.OP_SELECT, sf.OP_IXOR])
            # pick the constant flag FIRST, then draw the operand from
            # the range that flag makes legal - otherwise most
            # instructions name a constant the bank does not have and
            # the fuzz spends its time being rejected
            kb = rng.random() < 0.3
            kc = rng.random() < 0.2
            insns.append(seq.alu(
                op,
                rd=rng.randrange(seq.NREG),
                ra=rng.randrange(seq.NREG),
                rb=rng.randrange(nconst) if kb else rng.randrange(seq.NREG),
                rc=rng.randrange(nconst) if kc else rng.randrange(seq.NREG),
                rnd=rng.randrange(5), kb=kb, kc=kc))
        elif pick < 0.6 and depth < seq.MAX_LOOP_DEPTH:
            insns.append(seq.repeat(rng.randint(1, 4)))
            depth += 1
        elif pick < 0.7 and depth > 0:
            insns.append(seq.endrep())
            depth -= 1
        elif pick < 0.8:
            insns.append(seq.deposit(rng.randrange(seq.NREG)))
        elif pick < 0.92:
            insns.append(seq.setact(rng.randrange(seq.NREG)))
        elif depth == 0:
            insns.append(seq.actall())
        elif allow_halt_in_loop:
            insns.append(seq.halt())
    insns += [seq.endrep()] * depth
    insns.append(seq.halt())
    consts = [sf.zero_bits(fmt), sf.one_bits(fmt),
              sf.max_normal_bits(fmt)][:nconst]
    return insns, consts


def _fuzz_inputs(fmt, rng, n):
    pool = [sf.zero_bits(fmt), sf.zero_bits(fmt, 1), sf.one_bits(fmt),
            sf.inf_bits(fmt), sf.inf_bits(fmt, 1), sf.qnan_bits(fmt),
            sf.snan_bits(fmt, 1), sf.min_subnormal_bits(fmt),
            sf.max_normal_bits(fmt)]
    return [rng.choice(pool) if rng.random() < 0.5
            else rng.getrandbits(fmt.width) for _ in range(n)]


def test_p3_fuzz_early_exit_is_invisible():
    """The real gate on P3: random valid programs, run with the
    optimisation forced on and off, whole machine state compared."""
    rng = random.Random(2026)
    fmt = FP32
    checked = 0
    saved = 0
    for _ in range(400):
        insns, consts = _random_program(fmt, rng)
        try:
            prog = seq.Program(fmt, insns, consts, max_deposits=3)
        except seq.ProgramError:
            continue
        n = rng.randint(1, 6)
        a, b, c = (_fuzz_inputs(fmt, rng, n) for _ in range(3))
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
        insns, consts = _random_program(fmt, rng, allow_halt_in_loop=True)
        # bypass the validator deliberately - this is the program shape
        # validate() exists to refuse
        prog = seq.Program.__new__(seq.Program)
        prog.fmt, prog.insns, prog.consts, prog.max_deposits = \
            fmt, insns, consts, 3
        n = rng.randint(2, 6)
        a, b, c = (_fuzz_inputs(fmt, rng, n) for _ in range(3))
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
        insns, consts = _random_program(fmt, rng)
        try:
            prog = seq.Program(fmt, insns, consts, max_deposits=3)
        except seq.ProgramError:
            continue
        n = 8
        a, b, c = (_fuzz_inputs(fmt, rng, n) for _ in range(3))
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
