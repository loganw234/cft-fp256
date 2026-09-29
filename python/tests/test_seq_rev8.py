# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""Revision 8 of the program model (proposed, 2026-09-29): the golden side.

docs/SEQUENCER.md, "Revision 8 (proposed, 2026-09-29)", is the contract
these hold `seq.py` to:

* `augadd rD, rA, rB` / `augerr rD, rA, rB` (control codes 10 and 11):
  the two halves of IEEE 754-2019 clause 9.5's augmentedAddition, each
  computed by `augmented.augmented_add` and each raising that
  operation's flags. Bit for bit against augmented.py in every format.
* STX / LDX with a signed twelve-bit post-step in imm[11:0]: the access
  at the index as it stood, then rb := rb + step modulo 2^W, whatever
  SCRATCH_STRICT decides about the access, and never for an inactive
  lane. A zero step is the old instruction, bit for bit.
* the refusals: every field the two new codes do not read, imm[23:12]
  on a stepped access, and an LDX that loads into its own stepped index.

Each test says what it would catch, and the fuzz at the end checks that
it reached what it claims to, because a property test that never meets
the interesting case passes for the wrong reason.
"""

import random
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cft_golden import FORMATS, augmented, vectors  # noqa: E402
from cft_golden import softfloat as sf  # noqa: E402
from cft_golden import asm, seq  # noqa: E402

FP32 = FORMATS["fp32"]
FP64 = FORMATS["fp64"]
ALL = tuple(FORMATS.values())

AUG_PAIR = [seq.augerr(5, 0, 1), seq.augadd(6, 0, 1),
            seq.deposit(6), seq.deposit(5), seq.halt()]


def _prog(fmt, insns, **kw):
    kw.setdefault("max_deposits", 0)
    return seq.Program(fmt, list(insns) + [seq.halt()], **kw)


# ---- 1. the encoding ---------------------------------------------------

def test_a_zero_step_is_the_old_encoding_bit_for_bit():
    """Every STX/LDX a loader accepted before revision 8 has imm[23:0]
    zero, and a zero step must encode to exactly that word - otherwise an
    existing image would change meaning or bytes."""
    for r1 in range(32):
        for r2 in range(32):
            old_ldx = seq.encode(seq.LDX, rd=r1, rb=r2, ctrl=True)
            old_stx = seq.encode(seq.STX, ra=r1, rb=r2, ctrl=True)
            assert seq.ldx(r1, r2) == seq.ldx(r1, r2, 0) == old_ldx
            assert seq.stx(r1, r2) == seq.stx(r1, r2, 0) == old_stx
            assert seq.index_step(seq.decode(old_ldx)) == 0


def test_the_step_is_imm_11_0_in_twos_complement():
    for step in list(range(-40, 41)) + [seq.STEP_MIN, seq.STEP_MAX,
                                        -1024, 1023, -2047, 2046]:
        for make in (lambda s: seq.ldx(7, 20, s), lambda s: seq.stx(20, 7, s)):
            w = make(step)
            d = seq.decode(w)
            assert seq.index_step(d) == step
            assert d["imm"] & seq.STEP_MASK == step & 0xFFF
            assert d["imm"] & 0x00FFF000 == 0, "imm[23:12] must stay zero"
            # the register fields are untouched by the step
            assert d["rb"] in (7, 20) and d["op"] in (seq.STX, seq.LDX)


def test_a_step_outside_twelve_bits_is_refused_by_name():
    for bad in (seq.STEP_MAX + 1, seq.STEP_MIN - 1, 4096, -100000):
        with pytest.raises(seq.ProgramError, match="signed 12-bit"):
            seq.ldx(1, 2, bad)
        with pytest.raises(seq.ProgramError, match="signed 12-bit"):
            seq.stx(1, 2, bad)


def test_stl_and_ldl_carry_a_slot_not_a_step():
    """imm[11:0] of a STATIC access is part of its slot; index_step must
    never read one there, or LDL 5 would step a register it never names."""
    for slot in (1, 5, 255, 0x7FF, 0x800):
        if slot >= seq.SCRATCH_D:
            continue
        assert seq.index_step(seq.decode(seq.ldl(3, slot))) == 0
        assert seq.index_step(seq.decode(seq.stl(3, slot))) == 0
    assert seq.index_step(seq.decode(seq.alu(sf.OP_FMA, 1, 2, 3, 4))) == 0


def test_the_two_new_codes_are_ten_and_eleven_with_five_bit_fields():
    w = seq.augadd(17, 30, 9)
    d = seq.decode(w)
    assert (w & 0xFF, d["ctrl"]) == (10, True)
    assert (d["rd"], d["ra"], d["rb"]) == (17, 30, 9)
    assert d["imm"] == (1 << 24) | (1 << 25), "rd[4] and ra[4], rb < 16"
    d = seq.decode(seq.augerr(0, 16, 31))
    assert (d["op"], d["rd"], d["ra"], d["rb"]) == (11, 0, 16, 31)
    assert seq.CTRL_NAMES[10] == "augadd" and seq.CTRL_NAMES[11] == "augerr"


# ---- 2. the refusals ---------------------------------------------------

@pytest.mark.parametrize("code", [seq.AUGADD, seq.AUGERR])
def test_the_pair_refuses_every_field_it_does_not_read(code):
    """rc and its high bit, rnd (9.5 fixes the rounding, so an attribute
    cannot be spelled), the three k flags and kx (no control code reads
    the bank), every bit of imm[23:0] and imm[31:28]. Each is a second
    spelling of one operation, which a readback hash cannot tolerate."""
    good = dict(rd=1, ra=2, rb=3, ctrl=True)
    _prog(FP64, [seq.encode(code, **good)])
    bad = [dict(rc=4), dict(rnd=1), dict(rnd=4), dict(ka=True),
           dict(kb=True), dict(kc=True), dict(kx=True)]
    bad += [dict(imm=1 << k) for k in list(range(24)) + [27, 28, 29, 30, 31]]
    for extra in bad:
        with pytest.raises(seq.ProgramError):
            _prog(FP64, [seq.encode(code, **{**good, **extra})])


@pytest.mark.parametrize("code", [seq.STX, seq.LDX])
def test_imm_23_12_stays_reserved_on_a_stepped_access(code):
    regs = dict(ra=2, rb=3) if code == seq.STX else dict(rd=2, rb=3)
    _prog(FP32, [seq.encode(code, ctrl=True, imm=0xFFF, **regs)])
    for k in range(12, 24):
        with pytest.raises(seq.ProgramError, match="does not read"):
            _prog(FP32, [seq.encode(code, ctrl=True, imm=1 << k, **regs)])


def test_an_ldx_into_its_own_stepped_index_is_refused_and_nothing_else():
    """CORE-V's rule gives the register to the loaded value, so the step
    would select nothing: refused. A zero step is the old LDX and loads;
    STX with ra == rb has one register write, the step's, and loads."""
    for r in (0, 5, 16, 31):
        with pytest.raises(seq.ProgramError, match="own index register"):
            _prog(FP32, [seq.ldx(r, r, 1)])
        with pytest.raises(seq.ProgramError, match="own index register"):
            _prog(FP32, [seq.ldx(r, r, seq.STEP_MIN)])
        _prog(FP32, [seq.ldx(r, r, 0)])
        _prog(FP32, [seq.stx(r, r, -3)])
        _prog(FP32, [seq.ldx((r + 1) % 32, r, 7)])


def test_the_next_control_code_is_still_unknown():
    for code in (12, 13, 127, 255):
        with pytest.raises(seq.ProgramError, match="unknown control code"):
            _prog(FP32, [seq.encode(code, ctrl=True)])


def test_the_new_forms_survive_the_image_round_trip():
    insns = [seq.augerr(5, 0, 1), seq.augadd(0, 0, 1), seq.ldx(3, 4, -7),
             seq.stx(4, 4, 2047), seq.ldx(9, 10, seq.STEP_MIN), seq.halt()]
    p = seq.Program(FP64, insns, max_deposits=1)
    q = seq.Program.from_bytes(p.to_bytes())
    assert q.insns == insns and q.to_bytes() == p.to_bytes()


def test_features_rev8_names_exactly_what_a_program_needs():
    assert seq.features_rev8([seq.halt()]) == 0
    assert seq.features_rev8([seq.ldx(1, 2), seq.stx(1, 2, 0)]) == 0
    assert seq.features_rev8([seq.augadd(1, 2, 3)]) == seq.FEAT_AUGADD
    assert seq.features_rev8([seq.augerr(1, 2, 3)]) == seq.FEAT_AUGADD
    assert seq.features_rev8([seq.stx(1, 2, 1)]) == seq.FEAT_SCRATCH_STEP
    assert seq.features_rev8([seq.ldx(1, 2, -1), seq.augerr(1, 2, 3)]) == (
        seq.FEAT_AUGADD | seq.FEAT_SCRATCH_STEP)
    # a slot of 1 on a static access is not a step
    assert seq.features_rev8([seq.ldl(1, 1), seq.stl(1, 3)]) == 0
    assert (seq.FEAT_AUGADD, seq.FEAT_SCRATCH_STEP) == (0x8000, 0x10000)


# ---- 3. augadd / augerr against augmented.py ------------------------------

@pytest.mark.parametrize("fmt", ALL, ids=lambda f: f.name)
def test_bit_for_bit_against_augmented_py_over_its_stress_families(fmt):
    """The pool augmented.py's own vector sets are built from - ties from
    odd significands at every binade edge, exact cancellation in every
    sign, residuals that land subnormal, both sides of the overflow
    threshold - run as LANES through the recommended pair, each lane
    held to augmented_add's r and e, and the run's FLAGS to the OR of
    the per-pair flags."""
    pairs = vectors.augmented_pairs(fmt, 0)
    a = [x for x, _ in pairs]
    b = [y for _, y in pairs]
    res = seq.run(seq.Program(fmt, AUG_PAIR, max_deposits=2), a, b)
    want_flags = 0
    for i, (x, y) in enumerate(pairs):
        r, e, fl = augmented.augmented_add(fmt, x, y)
        want_flags |= fl
        got = (res.deposits[2 * i], res.deposits[2 * i + 1])
        assert got == (r, e), (
            f"{fmt.name} lane {i}: augadd/augerr({x:#x}, {y:#x}) gave "
            f"({got[0]:#x}, {got[1]:#x}), augmented.py ({r:#x}, {e:#x})")
    assert res.flags == want_flags
    # ...and the pool is the one that reaches every flag class, or this
    # passed without meeting one
    assert want_flags == (sf.FLAG_INVALID | sf.FLAG_OVERFLOW
                          | sf.FLAG_INEXACT | sf.FLAG_UNDERFLOW)


@pytest.mark.parametrize("fmt", ALL, ids=lambda f: f.name)
def test_each_lane_raises_exactly_augmented_additions_flags(fmt):
    """Per lane, not only OR-ed over a run: every pair whose flags are not
    zero, and a sample of the rest, each run alone. The pair raises what
    ONE augmentedAddition raises, since FLAGS is a sticky OR."""
    rng = random.Random(fmt.width * 17)
    pairs = vectors.augmented_pairs(fmt, 0)
    flagged = [(x, y) for x, y in pairs
               if augmented.augmented_add(fmt, x, y)[2]]
    quiet = [(x, y) for x, y in pairs
             if not augmented.augmented_add(fmt, x, y)[2]]
    chosen = rng.sample(flagged, min(len(flagged), 150)) + \
        rng.sample(quiet, min(len(quiet), 150))
    prog = seq.Program(fmt, AUG_PAIR, max_deposits=2)
    seen = set()
    for x, y in chosen:
        want = augmented.augmented_add(fmt, x, y)[2]
        got = seq.run(prog, [x], [y]).flags
        assert got == want, f"{fmt.name} ({x:#x}, {y:#x}): {got:#x} != {want:#x}"
        seen.add(want)
    # 9.5's combinations: none, invalid, overflow+inexact, underflow
    assert {0, sf.FLAG_INVALID, sf.FLAG_OVERFLOW | sf.FLAG_INEXACT,
            sf.FLAG_UNDERFLOW} <= seen


def test_ties_go_to_the_smaller_magnitude_not_to_even():
    """The one place augadd is not ADD. With u = 2^-(p-1) the ulp of 1,
    1 + 1.5u = 1 + 3 x 2^-p is the midpoint between 1 + u, whose last
    bit is ODD, and 1 + 2u. roundTiesToEven goes up to 1 + 2u,
    roundTiesTowardZero down to 1 + u, and e = 0.5u = 2^-p exactly."""
    for fmt in ALL:
        one = sf.one_bits(fmt)
        x = sf.round_pack(fmt, 0, 3, -fmt.prec)[0]
        prog = _prog(fmt, [seq.augadd(2, 0, 1), seq.augerr(3, 0, 1),
                           seq.alu(sf.OP_ADD, 4, 0, rc=1)])
        res = seq.run(prog, [one], [x])
        r, e, rne = res.regs[0][2], res.regs[0][3], res.regs[0][4]
        assert r == one + 1, f"{fmt.name}: r is not 1 + u (toward zero)"
        assert rne == one + 2, f"{fmt.name}: ADD should round to even (up)"
        assert e == sf.round_pack(fmt, 0, 1, -fmt.prec)[0], fmt.name
        assert res.flags & ~sf.FLAG_INEXACT == 0
        # ADD raised inexact for its rounding; the pair raised nothing
        pair = seq.run(_prog(fmt, [seq.augerr(3, 0, 1),
                                   seq.augadd(2, 0, 1)]), [one], [x])
        assert pair.flags == 0, "a rounded r raises no inexact under 9.5"


def test_the_flag_classes_one_by_one():
    fmt = FP64
    mx = sf.max_normal_bits(fmt)
    cases = {
        # a signaling NaN: invalid, both halves the canonical qNaN
        "snan": ((sf.snan_bits(fmt, 1), sf.one_bits(fmt)),
                 sf.FLAG_INVALID),
        "inf-inf": ((sf.inf_bits(fmt), sf.inf_bits(fmt, 1)),
                    sf.FLAG_INVALID),
        "qnan": ((sf.qnan_bits(fmt), sf.one_bits(fmt)), 0),
        # max + max: roundTiesTowardZero overflows - both results +inf
        "overflow": ((mx, mx), sf.FLAG_OVERFLOW | sf.FLAG_INEXACT),
        # 1 + the smallest subnormal: r = 1, e subnormal and exact
        "underflow": ((sf.one_bits(fmt), sf.min_subnormal_bits(fmt)),
                      sf.FLAG_UNDERFLOW),
        # a rounded r with a normal e: nothing at all
        "rounded": ((sf.one_bits(fmt), 0x3C30000000000000), 0),
    }
    prog = seq.Program(fmt, AUG_PAIR, max_deposits=2)
    for name, ((x, y), want) in cases.items():
        res = seq.run(prog, [x], [y])
        assert res.flags == want, f"{name}: {res.flags:#x} != {want:#x}"
        r, e, _ = augmented.augmented_add(fmt, x, y)
        assert res.deposits == [r, e], name
    inf = seq.run(prog, [mx], [mx]).deposits
    assert inf == [sf.inf_bits(fmt)] * 2, "an overflow gives both halves inf"


def test_the_recommended_pair_works_in_place_and_aliases_are_read_first():
    """`augerr rE, rA, rB; augadd rA, rA, rB` - the compensated step's
    x := x + y with its error beside it, no temporary. And rd naming a
    source is read-then-written, as for an ALU instruction."""
    fmt = FP64
    rng = random.Random(8)
    xs = seq.random_inputs(fmt, rng, 64)
    ys = seq.random_inputs(fmt, rng, 64)
    prog = _prog(fmt, [seq.augerr(7, 0, 1), seq.augadd(0, 0, 1)])
    res = seq.run(prog, xs, ys)
    for i, (x, y) in enumerate(zip(xs, ys)):
        r, e, _ = augmented.augmented_add(fmt, x, y)
        assert (res.regs[i][0], res.regs[i][7]) == (r, e)
    # rd = rb: augerr r1, r0, r1 reads r1 before overwriting it
    prog = _prog(fmt, [seq.augerr(1, 0, 1)])
    res = seq.run(prog, xs, ys)
    for i, (x, y) in enumerate(zip(xs, ys)):
        assert res.regs[i][1] == augmented.augmented_add(fmt, x, y)[1]


@pytest.mark.parametrize("fmt", ALL, ids=lambda f: f.name)
def test_r_plus_e_is_exactly_x_plus_y_on_the_programs_outputs(fmt):
    """What the operation is FOR, scored on the executor's output rather
    than on augmented.py's: wherever r is finite, r + e == x + y as exact
    dyadic rationals."""
    pairs = vectors.augmented_pairs(fmt, 0)[:3000]
    res = seq.run(seq.Program(fmt, AUG_PAIR, max_deposits=2),
                  [x for x, _ in pairs], [y for _, y in pairs])
    checked = 0
    for i, (x, y) in enumerate(pairs):
        r, e = res.deposits[2 * i], res.deposits[2 * i + 1]
        if any(sf.unpack(fmt, v).kind in (sf.INF, sf.NAN) for v in (x, y, r)):
            continue
        (mr, er), (me, ee) = (augmented.exact_value(fmt, r),
                              augmented.exact_value(fmt, e))
        (mx, ex), (my, ey) = (augmented.exact_value(fmt, x),
                              augmented.exact_value(fmt, y))
        q = min(er, ee, ex, ey)
        assert (mr << (er - q)) + (me << (ee - q)) == \
            (mx << (ex - q)) + (my << (ey - q)), (fmt.name, hex(x), hex(y))
        checked += 1
    assert checked > 1000


def test_masked_padding_and_dropped_lanes_neither_write_nor_raise():
    """P3's rule and R17's, for the new codes: a lane the caller masked, a
    padding lane past n_active and a lane SETACT dropped all hold a
    signaling NaN, and none of them may write rd or raise invalid."""
    fmt = FP64
    snan, one = sf.snan_bits(fmt, 1), sf.one_bits(fmt)
    zero = sf.zero_bits(fmt)
    # lane 0 runs; lane 1 masked; lane 2 dropped by SETACT on r2 = +0
    # before the pair; lane 3 is padding (n_active = 3)
    a = [one, snan, snan, snan]
    b = [one, one, one, one]
    c = [one, one, zero, one]
    prog = _prog(fmt, [seq.setact(2), seq.augerr(5, 0, 1),
                       seq.augadd(6, 0, 1)])
    res = seq.run(prog, a, b, c, n_active=3,
                  lane_mask=[True, False, True, True])
    assert res.flags == 0, "an inactive lane's sNaN reached FLAGS"
    for i in (1, 2, 3):
        assert res.regs[i][5] == zero and res.regs[i][6] == zero, i
    assert res.regs[0][6] == sf.round_pack(fmt, 0, 1, 1)[0]    # 2.0
    # ...and the same run with every lane active does raise it
    res = seq.run(_prog(fmt, [seq.augadd(6, 0, 1)]), a, b)
    assert res.flags == sf.FLAG_INVALID


# ---- 4. the post-step ----------------------------------------------------

def _walker(fmt, k, step, start_slot, strict=False):
    """A program that loads k consecutive slots through a stepped LDX
    inside a loop and deposits each, with the index in r0."""
    return seq.Program(
        fmt, [seq.repeat(k), seq.ldx(4, 0, step), seq.deposit(4),
              seq.endrep(), seq.halt()],
        max_deposits=k,
        flags=(seq.FLAG_SCRATCH_IO
               | (seq.FLAG_SCRATCH_STRICT if strict else 0)),
        n_scratch_in=seq.SCRATCH_D)


def test_the_access_uses_the_index_as_it_stood_then_it_steps():
    fmt = FP32
    block = [0x1000 + s for s in range(seq.SCRATCH_D)]
    for step in (1, -1, 3, -7):
        res = seq.run(_walker(fmt, 20, step, 100), [100], [0],
                      scratch_in=block)
        want = [block[(100 + step * j) % seq.SCRATCH_D] for j in range(20)]
        assert res.deposits == want, step
        assert res.regs[0][0] == (100 + 20 * step) & 0xFFFFFFFF


def test_a_store_with_ra_equal_rb_stores_the_old_index():
    fmt = FP32
    prog = seq.Program(fmt, [seq.stx(0, 0, 5), seq.stx(0, 0, 5),
                             seq.halt()], max_deposits=0,
                       flags=seq.FLAG_SCRATCH_IO, n_scratch_out=16)
    res = seq.run(prog, [3], [0])
    assert res.scratch_out[3] == 3 and res.scratch_out[8] == 8
    assert res.regs[0][0] == 13


@pytest.mark.parametrize("fmt", ALL, ids=lambda f: f.name)
def test_the_step_wraps_at_the_register_width(fmt):
    """IADD's arithmetic: 0 - 1 is 2^W - 1 in the register at every
    format, and the access after it reduces modulo the depth (slot 255)
    without SCRATCH_STRICT."""
    prog = _prog(fmt, [seq.ldx(3, 0, -1), seq.ldx(4, 0, -1),
                       seq.ldx(5, 0, seq.STEP_MIN)],
                 flags=seq.FLAG_SCRATCH_IO, n_scratch_in=seq.SCRATCH_D)
    block = list(range(1, seq.SCRATCH_D + 1))
    res = seq.run(prog, [0], [0], scratch_in=block)
    W = 1 << fmt.width
    assert res.regs[0][0] == (0 - 2 - 2048) % W
    assert res.regs[0][3] == block[0]           # slot 0, then step
    assert res.regs[0][4] == block[255]         # 2^W - 1 mod 256
    assert res.regs[0][5] == block[254]         # 2^W - 2 mod 256


def test_without_strict_the_walk_is_a_ring_and_the_register_keeps_counting():
    fmt = FP64
    block = [0x77 + s for s in range(seq.SCRATCH_D)]
    res = seq.run(_walker(fmt, 12, 1, 250), [250], [0], scratch_in=block)
    assert res.deposits == [block[(250 + j) % 256] for j in range(12)]
    assert res.regs[0][0] == 262, "the register is not reduced, the slot is"
    assert res.status == 0


def test_strict_suppresses_the_access_past_the_depth_and_still_steps():
    """R8 judges the ACCESS on the index as it stood: slots 250..255 load,
    256 and after are suppressed, read +0 and raise STATUS[5]. The step is
    a register write and happens on every one - so a strict and a
    non-strict run leave the index register identical."""
    fmt = FP64
    block = [0x77 + s for s in range(seq.SCRATCH_D)]
    strict = seq.run(_walker(fmt, 12, 1, 250, strict=True), [250], [0],
                     scratch_in=block)
    loose = seq.run(_walker(fmt, 12, 1, 250), [250], [0], scratch_in=block)
    assert strict.deposits == block[250:256] + [0] * 6
    assert strict.status & seq.STATUS_SCRATCH_RANGE
    assert strict.regs[0][0] == loose.regs[0][0] == 262
    # the step that LEAVES the range reports nothing; only an access does
    one = seq.run(_walker(fmt, 6, 1, 250, strict=True), [250], [0],
                  scratch_in=block)
    assert one.status == 0 and one.regs[0][0] == 256


def test_an_inactive_lane_neither_accesses_nor_steps():
    fmt = FP32
    prog = seq.Program(fmt, [seq.setact(2), seq.stx(1, 0, 1), seq.ldx(3, 0, 1),
                             seq.halt()], max_deposits=0,
                       flags=seq.FLAG_SCRATCH_IO, n_scratch_out=4)
    one = 0x3F800000
    res = seq.run(prog, [0, 0, 0], [one, one, one], [one, 0, one],
                  lane_mask=[True, True, False])
    assert res.regs[0][0] == 2 and res.scratch_out[0:1] == [one]
    assert res.regs[1][0] == 0 and res.scratch_out[4:5] == [0], "dropped"
    assert res.regs[2][0] == 0 and res.scratch_out[8:9] == [0], "masked"


def test_a_cauchy_product_walks_two_indices_in_opposite_directions():
    """The pattern the ask is for: c_n = sum over j of a_j * b_(n-j), two
    stepped loads walking toward each other and one FMA a term - held to
    the same sum computed directly, in the same order, with sf.fma."""
    fmt = FP64
    rng = random.Random(5)
    N = 9
    av = [sf.round_pack(fmt, rng.getrandbits(1), rng.getrandbits(40) | 1,
                        -40)[0] for _ in range(N + 1)]
    bv = [sf.round_pack(fmt, rng.getrandbits(1), rng.getrandbits(40) | 1,
                        -40)[0] for _ in range(N + 1)]
    A, B = 0, 32
    block = [0] * seq.SCRATCH_D
    block[A:A + N + 1] = av
    block[B:B + N + 1] = bv
    consts = [sf.zero_bits(fmt)]
    insns = []
    for n in range(N + 1):
        consts += [A, B + n]
        ka, kb = len(consts) - 2, len(consts) - 1
        insns += [seq.alu(sf.OP_IOR, 10, ka, ka, ka=True, kb=True, kx=True),
                  seq.alu(sf.OP_IOR, 11, kb, kb, ka=True, kb=True, kx=True),
                  seq.alu(sf.OP_IXOR, 12, 12, 12),
                  seq.repeat(n + 1),
                  seq.ldx(13, 10, +1), seq.ldx(14, 11, -1),
                  seq.alu(sf.OP_FMA, 12, 13, 14, 12),
                  seq.endrep(), seq.deposit(12)]
    prog = seq.Program(fmt, insns + [seq.halt()], consts,
                       max_deposits=N + 1, flags=seq.FLAG_SCRATCH_IO,
                       n_scratch_in=seq.SCRATCH_D)
    res = seq.run(prog, [0], [0], scratch_in=block)
    for n in range(N + 1):
        acc = sf.zero_bits(fmt)
        for j in range(n + 1):
            acc, _ = sf.fma(fmt, av[j], bv[n - j], acc)
        assert res.deposits[n] == acc, n


# ---- 5. the properties, fuzzed -------------------------------------------

def test_p3_fuzz_with_revision_8_on():
    """P3 over the new forms: random programs with augadd/augerr, the pair
    and stepped accesses, run with the early exit forced on and off, the
    whole machine state compared - every write and every flag of an
    all-inactive loop body must be a no-op, the step's included. And the
    generator's every form must appear, or this proved nothing."""
    rng = random.Random(20260929)
    fmt = FP32
    checked = saved = 0
    seen = dict(augadd=0, augerr=0, pair=0, ldx_step=0, stx_step=0)
    for _ in range(400):
        insns, consts = seq.random_program(fmt, rng, scratch=True,
                                           wide_regs=True, rev8=True)
        strict = rng.random() < 0.3
        prog = seq.Program(fmt, insns, consts, max_deposits=3,
                           flags=seq.FLAG_SCRATCH_IO
                           | (seq.FLAG_SCRATCH_STRICT if strict else 0),
                           n_scratch_out=4)
        prev = None
        for w in insns:
            d = seq.decode(w)
            if d["ctrl"] and d["op"] == seq.AUGADD:
                seen["augadd"] += 1
                if prev and prev["op"] == seq.AUGERR and \
                        (prev["ra"], prev["rb"]) == (d["ra"], d["rb"]):
                    seen["pair"] += 1
            elif d["ctrl"] and d["op"] == seq.AUGERR:
                seen["augerr"] += 1
            elif seq.index_step(d):
                seen["ldx_step" if d["op"] == seq.LDX else "stx_step"] += 1
            prev = d if d["ctrl"] else None
        n = rng.randint(1, 6)
        a, b, c = (seq.random_inputs(fmt, rng, n) for _ in range(3))
        fast = seq.run(prog, a, b, c, early_exit=True)
        slow = seq.run(prog, a, b, c, early_exit=False)
        assert fast.state() == slow.state(), [hex(i) for i in insns]
        checked += 1
        saved += fast.insns_executed < slow.insns_executed
    assert checked == 400, "the revision-8 arm drew a program validate refused"
    assert saved > 0
    assert all(seen.values()), seen


def test_the_revision_8_arm_draws_nothing_when_off():
    """A seed's corpus must not move because the arm exists: the same rng
    state after a draw with the arm off as with it absent."""
    for seed in range(50):
        r1, r2 = random.Random(seed), random.Random(seed)
        p1 = seq.random_program(FP64, r1, scratch=True, wide_regs=True)
        p2 = seq.random_program(FP64, r2, scratch=True, wide_regs=True,
                                rev8=False)
        assert p1 == p2 and r1.random() == r2.random()


# ---- 6. the text form (asm.py) --------------------------------------------

REV8_SRC = """.format fp64
.deposits 2
.scratch in 256
augerr r5, r0, r1
augadd r0, r0, r1
stx r0, r4, +1
ldx r6, r4, -1
ldx r7, r8, -2048
stx r9, r9, 2047
ldx r10, r11, 0x10
ldx r12, r13, -0x10
deposit r0
deposit r5
halt
"""


def test_the_text_form_assembles_to_the_models_words():
    img = asm.assemble_image(REV8_SRC, "<rev8>")
    assert img.insns[:8] == [
        seq.augerr(5, 0, 1), seq.augadd(0, 0, 1), seq.stx(0, 4, 1),
        seq.ldx(6, 4, -1), seq.ldx(7, 8, -2048), seq.stx(9, 9, 2047),
        seq.ldx(10, 11, 16), seq.ldx(12, 13, -16)]
    # ...and the model loads the same bytes and runs them
    prog = seq.Program.from_bytes(img.to_bytes())
    assert prog.insns == img.insns


def test_the_text_form_round_trips_and_writes_a_step_only_when_there_is_one():
    image = asm.assemble(REV8_SRC, "<rev8>")
    text = asm.disassemble(image)
    for line in ("augerr r5, r0, r1", "augadd r0, r0, r1",
                 "stx r0, r4, +1", "ldx r6, r4, -1", "ldx r7, r8, -2048",
                 "stx r9, r9, +2047", "ldx r10, r11, +16",
                 "ldx r12, r13, -16"):
        assert line in text, line
    assert asm.assemble(text, "<rt>") == image
    # a zero step is the old instruction: same bytes, same text
    old = asm.assemble(".format fp64\n.deposits 0\nldx r3, r4\nhalt\n")
    zero = asm.assemble(".format fp64\n.deposits 0\nldx r3, r4, 0\nhalt\n")
    assert old == zero
    assert "ldx r3, r4\n" in asm.disassemble(zero)


@pytest.mark.parametrize("line,fragment", [
    ("ldx r3, r4, 2048", "outside -2048..2047"),
    ("stx r3, r4, -2049", "outside -2048..2047"),
    ("ldx r3, r4, r5", "is a register"),
    ("ldx r3, r3, +1", "own index register"),
    ("ldx r3, r4, +1, +2", "optional signed post-step"),
    ("augadd r1, r2", "three registers"),
    ("augerr r1, r2, r3, r4", "three registers"),
    ("augadd r1, r2, K", "is a constant"),
])
def test_the_text_form_refuses_by_name(line, fragment):
    src = ".format fp64\n.deposits 0\n.const K = 1.0\n" + line + "\nhalt\n"
    with pytest.raises(asm.AsmError) as exc:
        asm.assemble(src, "<test>")
    assert fragment in str(exc.value), str(exc.value)


def test_the_text_form_names_the_features():
    def feats(body):
        return asm.assemble_image(".format fp64\n.deposits 0\n" + body
                                  + "halt\n").features()
    assert "AUGADD" in feats("augadd r1, r2, r3\n")
    assert "AUGADD" in feats("augerr r1, r2, r3\n")
    assert "SCRATCH_STEP" in feats("ldx r1, r2, -1\n")
    assert feats("ldx r1, r2\nstx r1, r2, 0\n") == ["SCRATCH"]
    assert feats("augadd r20, r2, r3\n") == ["REGS32", "AUGADD"]
    assert "features      SCRATCH AUGADD SCRATCH_STEP" in asm.info(
        asm.assemble(".format fp64\n.deposits 0\naugadd r1, r2, r3\n"
                     "stx r1, r2, +1\nhalt\n"))


def test_the_two_validators_agree_over_the_new_codes_field_space():
    """asm.py keeps its own validator, and the rule is that where it and
    seq.py disagree about a program seq.py can express, asm.py is wrong.
    Random words over every field of codes 8..13 - the stepped pair, the
    new pair, and two codes past them - each judged by both."""
    rng = random.Random(88)
    accepted = refused = 0
    for _ in range(6000):
        code = rng.choice([seq.STX, seq.LDX, seq.AUGADD, seq.AUGERR, 12, 13])
        word = (code | (1 << 31)
                | (rng.randrange(16) << 8 if rng.random() < 0.8 else 0)
                | (rng.randrange(16) << 12 if rng.random() < 0.8 else 0)
                | (rng.randrange(16) << 16 if rng.random() < 0.8 else 0)
                | (rng.randrange(16) << 20 if rng.random() < 0.1 else 0)
                | (rng.randrange(8) << 24 if rng.random() < 0.05 else 0)
                | (rng.randrange(16) << 27 if rng.random() < 0.05 else 0))
        imm = 0
        if rng.random() < 0.6:
            imm |= rng.randrange(1 << 12)
        if rng.random() < 0.05:
            imm |= 1 << rng.randrange(12, 32)
        if rng.random() < 0.5:
            imm |= rng.randrange(8) << 24
        word |= imm << 32
        try:
            seq.Program(FP64, [word, seq.halt()], max_deposits=0)
            model = True
        except seq.ProgramError:
            model = False
        try:
            asm.Image(FP64, [word, asm.halt()], max_deposits=0)
            text = True
        except asm.AsmError:
            text = False
        assert model == text, (hex(word), model, text)
        accepted += model
        refused += not model
    assert accepted > 500 and refused > 500, (accepted, refused)


# ---- 7. what each is worth: the kernels, held ----------------------------

import rev8_worth  # noqa: E402  (python/, on the path above)


@pytest.mark.parametrize("fmt", [FORMATS["fp64"], FORMATS["fp256"]],
                         ids=lambda f: f.name)
def test_the_cauchy_kernels_agree_and_count_as_documented(fmt):
    """The three Cauchy forms compute the same bits as a direct sum in
    the same order (run_cauchy raises otherwise), their counts are held
    to seq.run's own, and the counts are the closed forms docs/SEQUENCER.md
    prices: per term looped 3 ALU + 2 SCR + a loop, stepped 1 + 2 + a
    loop with 2 steps, unrolled 1 + 2; per coefficient 3 ALU of setup and
    a store (1 ALU in the unrolled form)."""
    for N in (0, 1, 7, 12):
        T = (N + 1) * (N + 2) // 2
        res = rev8_worth.run_cauchy(fmt, N, lanes=2)
        lo, st, un = (res[k][0] for k in ("looped", "stepped", "unrolled"))
        assert (lo["alu"], lo["scr"], lo["steps"], lo["endrep"]) == (
            3 * (N + 1) + 3 * T, 2 * T + N + 1, 0, T)
        assert (st["alu"], st["scr"], st["steps"], st["endrep"]) == (
            3 * (N + 1) + T, 2 * T + N + 1, 2 * T, T)
        assert (un["alu"], un["scr"], un["steps"], un["endrep"]) == (
            N + 1 + T, 2 * T + N + 1, 0, 0)
        # the price difference is exactly 2 ALU a term at p = 0, none at 1
        s, e = rev8_worth.CENSUS[fmt.name]["s"], rev8_worth.CENSUS[fmt.name]["e"]
        assert rev8_worth.price(lo, s, e, 0) - rev8_worth.price(st, s, e, 0) \
            == pytest.approx(2 * T)
        assert rev8_worth.price(lo, s, e, 1) == pytest.approx(
            rev8_worth.price(st, s, e, 1))


@pytest.mark.parametrize("fmt", [FORMATS["fp64"], FORMATS["fp256"]],
                         ids=lambda f: f.name)
def test_the_compensated_kernels_hold_and_count_as_documented(fmt):
    """Each form held to its own reference (run_comp raises otherwise);
    per step kahan 5, twosum 8 and the augmented pair 3 instructions."""
    res = rev8_worth.run_comp(fmt, K=16, lanes=4)
    for form, per_step in (("kahan", 5), ("twosum", 8), ("augmented", 3)):
        c = res[form][0]
        assert (c["alu"] + c["aug"]) == 16 * per_step, form
        assert c["endrep"] == 16 and c["scr"] == 0
    assert res["augmented"][0]["aug"] == 32
