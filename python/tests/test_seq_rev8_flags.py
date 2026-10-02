# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""Revision 8's flag control and per-lane flags (the step-6 round's R8F and
R8L, 2026-10-02): the golden side.

docs/SEQUENCER.md, R23 and R24, is the contract these hold `seq.py` to:

* R24, flag control. `quiet` (control code 12) opens a region and
  `endquiet` (13) closes the innermost; inside one, the five IEEE flags of
  every instruction - ALU, augadd/augerr, and a raise's own - reach neither
  FLAGS nor a lane's byte (754-2019 5.7.4's saveAllFlags at the open and
  restoreFlags at the close). Nothing else is silenced. `raise rA` (14), in
  every active lane, ORs rA[4:0] into FLAGS and the lane's byte outside a
  region and marks the lane on rA[7] anywhere (STATUS[6]).
* R23, a byte a lane: [4:0] the IEEE flags raised outside every region,
  [5] deposit overflow, [6] a strict access past the depth, [7] the mark.
  Over the lanes a run owns, the OR of [4:0] is FLAGS and the OR of [7:5]
  is STATUS[6:4] one place up.
* the refusals: every field the three codes do not read, and the bracket
  rules - a region closed out of turn with a loop, nested past four, open
  at a HALT or at the end, or closed with none open.

Each test says what it would catch. The last sections hold divfull and
sqrtfull, wrapped in a region with their flag word raised, to softfloat's
flags lane by lane - the routine R24 exists for - and the text form.
"""

import random
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from cft_golden import FORMATS, divfull  # noqa: E402
from cft_golden import softfloat as sf  # noqa: E402
from cft_golden import asm, seq  # noqa: E402

from test_divfull import specials  # noqa: E402

FP32 = FORMATS["fp32"]
FP64 = FORMATS["fp64"]
FP128 = FORMATS["fp128"]
FP256 = FORMATS["fp256"]
ALL = tuple(FORMATS.values())
R24 = (seq.QUIET, seq.ENDQUIET, seq.RAISE)


def _prog(fmt, insns, **kw):
    kw.setdefault("max_deposits", 0)
    return seq.Program(fmt, list(insns) + [seq.halt()], **kw)


def _inexact(fmt):
    """An FMA that is inexact and nothing else: 1 + tiny, where tiny is
    far below half an ulp of one. Its operands ride in r0, r1, r2."""
    one = sf.one_bits(fmt)
    tiny = sf.round_pack(fmt, 0, 1, -fmt.prec - 4)[0]
    return one, one, tiny


def _owned(n, n_active=None, mask=None):
    n_active = n if n_active is None else n_active
    return [i for i in range(n)
            if i < n_active and (mask is None or mask[i])]


def _identities(res, owned):
    """R23's three identities over the lanes the run owns."""
    o = 0
    for i in owned:
        o |= res.lane_flags[i]
    assert o & seq.LANE_FLAGS_IEEE == res.flags, (hex(o), hex(res.flags))
    assert (o >> 1) & 0x70 == res.status & 0x70, (hex(o), hex(res.status))


# ---- 1. the encoding --------------------------------------------------------

def test_the_three_codes_are_twelve_to_fourteen_and_read_what_they_say():
    assert (seq.QUIET, seq.ENDQUIET, seq.RAISE) == (12, 13, 14)
    assert [seq.CTRL_NAMES[c] for c in R24] == ["quiet", "endquiet", "raise"]
    assert seq.quiet() == seq.encode(seq.QUIET, ctrl=True) == (1 << 31) | 12
    assert seq.endquiet() == (1 << 31) | 13
    for r in (0, 7, 15, 16, 31):
        d = seq.decode(seq.raise_(r))
        assert (d["op"], d["ctrl"], d["ra"]) == (14, True, r)
        # ra's fifth bit is imm[25], and nothing else of the word is set
        assert d["imm"] == ((r >> 4) << 25)
        assert (d["rd"], d["rb"], d["rc"], d["rnd"]) == (0, 0, 0, 0)


def test_the_bits_and_the_byte():
    """The numbers the C side, cftc and the protocol carry: CAPS2[13] and
    [14] on seq_features bits 17 and 18, STATUS[6], and the byte."""
    assert (seq.FEAT_LANE_FLAGS, seq.FEAT_FLAG_CONTROL) == (0x20000, 0x40000)
    assert seq.STATUS_MARKED == 0x40
    assert (seq.LANE_FLAGS_IEEE, seq.LANE_DEPOSIT_OVERFLOW,
            seq.LANE_SCRATCH_RANGE, seq.LANE_MARKED) == (0x1F, 0x20, 0x40,
                                                         0x80)
    # [7:5] are STATUS[6:4] one place up
    assert seq.LANE_DEPOSIT_OVERFLOW == seq.STATUS_DEPOSIT_OVERFLOW << 1
    assert seq.LANE_SCRATCH_RANGE == seq.STATUS_SCRATCH_RANGE << 1
    assert seq.LANE_MARKED == seq.STATUS_MARKED << 1


def test_features_rev8_names_flag_control_and_never_lane_flags():
    for w in (seq.quiet(), seq.endquiet(), seq.raise_(3)):
        assert seq.features_rev8([w]) == seq.FEAT_FLAG_CONTROL
    both = [seq.quiet(), seq.augadd(1, 2, 3), seq.endquiet(), seq.raise_(1)]
    assert seq.features_rev8(both) == (seq.FEAT_FLAG_CONTROL
                                      | seq.FEAT_AUGADD)
    # the per-lane block is asked of a run, never of an image
    assert not seq.features_rev8(both) & seq.FEAT_LANE_FLAGS


def test_the_new_forms_survive_the_image_round_trip():
    insns = [seq.quiet(), seq.alu(sf.OP_FMA, 3, 0, 1, 2), seq.quiet(),
             seq.endquiet(), seq.endquiet(), seq.raise_(3), seq.raise_(30),
             seq.halt()]
    p = seq.Program(FP64, insns, max_deposits=1)
    q = seq.Program.from_bytes(p.to_bytes())
    assert q.insns == insns and q.to_bytes() == p.to_bytes()


# ---- 2. the refusals ----------------------------------------------------------

@pytest.mark.parametrize("code", R24, ids=lambda c: seq.CTRL_NAMES[c])
def test_every_field_the_three_do_not_read_is_refused(code):
    """QUIET and ENDQUIET read nothing; RAISE reads ra alone (imm[25] its
    fifth bit). Every other field is a second spelling of one
    instruction, which a readback hash cannot tolerate."""
    reads_ra = code == seq.RAISE
    good = dict(ra=17 if reads_ra else 0, ctrl=True)
    brackets = {seq.QUIET: ([], [seq.endquiet()]),
                seq.ENDQUIET: ([seq.quiet()], []),
                seq.RAISE: ([], [])}[code]

    def prog(**extra):
        return _prog(FP64, brackets[0] + [seq.encode(code, **{**good,
                                                               **extra})]
                     + brackets[1])

    prog()
    bad = [dict(rd=1), dict(rb=2), dict(rc=3), dict(rnd=1), dict(rnd=4),
           dict(ka=True), dict(kb=True), dict(kc=True), dict(kx=True)]
    if not reads_ra:
        bad.append(dict(ra=1))
    bad += [dict(imm=1 << k) for k in range(32)
            if not (reads_ra and k == 25)]
    for extra in bad:
        with pytest.raises(seq.ProgramError):
            prog(**extra)


def test_a_raise_names_every_register():
    for r in range(32):
        _prog(FP32, [seq.raise_(r)])


@pytest.mark.parametrize("insns,fragment", [
    ([seq.endquiet()], "no quiet region open"),
    ([seq.quiet(), seq.endquiet(), seq.endquiet()], "no quiet region open"),
    # a region opened outside a loop, closed inside it
    ([seq.quiet(), seq.repeat(2), seq.endquiet(), seq.endrep()],
     "closes outside it"),
    # a region opened in a loop body, the loop closed around it
    ([seq.repeat(2), seq.quiet(), seq.endrep(), seq.endquiet()],
     "closes in that body"),
    ([seq.quiet()] * 5 + [seq.endquiet()] * 5, "deeper than 4"),
    ([seq.quiet(), seq.halt(), seq.endquiet()], "halt inside the quiet"),
    ([seq.quiet()], "left open at the end"),
    ([seq.quiet(), seq.quiet(), seq.endquiet()], "left open at the end"),
], ids=["close-none", "close-twice", "close-in-loop", "loop-around",
        "five-deep", "halt-inside", "open-at-end", "one-left-open"])
def test_the_bracket_rules(insns, fragment):
    with pytest.raises(seq.ProgramError, match=fragment):
        seq.Program(FP32, list(insns), max_deposits=0)


def test_regions_and_loops_nest_properly_four_deep_each():
    q, e = seq.quiet(), seq.endquiet()
    r, x = seq.repeat(2), seq.endrep()
    for insns in (
            [q] * 4 + [e] * 4,                          # four regions
            [q, r, q, r, q, r, q, r, x, e, x, e, x, e, x, e],
            [r, q, e, x],                               # region in a body
            [q, r, x, e],                               # loop in a region
            [q, seq.actall(), e]):                      # actall in one
        seq.Program(FP32, insns + [seq.halt()], max_deposits=0)


# ---- 3. the quiet region -----------------------------------------------------

@pytest.mark.parametrize("fmt", ALL, ids=lambda f: f.name)
def test_a_region_silences_an_alu_instruction_and_nothing_before_it(fmt):
    """Inside a region the FMA's inexact reaches neither FLAGS nor the
    byte; a flag raised before the region stands (5.7.4 restores, it does
    not clear - and 7.1 lowers a flag only at the user's request)."""
    a, b, c = _inexact(fmt)
    fma = seq.alu(sf.OP_FMA, 3, 0, 1, 2)
    loud = seq.run(_prog(fmt, [fma]), [a], [b], [c])
    assert loud.flags == sf.FLAG_INEXACT == loud.lane_flags[0]
    quiet = seq.run(_prog(fmt, [seq.quiet(), fma, seq.endquiet()]),
                    [a], [b], [c])
    assert quiet.flags == 0 and quiet.lane_flags == [0]
    assert quiet.regs[0][3] == loud.regs[0][3], "the value is not silenced"
    before = seq.run(_prog(fmt, [fma, seq.quiet(), fma, seq.endquiet()]),
                     [a], [b], [c])
    assert before.flags == sf.FLAG_INEXACT == before.lane_flags[0]
    after = seq.run(_prog(fmt, [seq.quiet(), fma, seq.endquiet(), fma]),
                    [a], [b], [c])
    assert after.flags == sf.FLAG_INEXACT


def test_a_region_silences_augadd_and_augerr():
    """R21's codes raise flags, and a region silences them as it does an
    ALU's: invalid from a signaling NaN, overflow with inexact at the
    top of the range."""
    fmt = FP64
    snan, one = sf.snan_bits(fmt, 1), sf.one_bits(fmt)
    big = sf.max_normal_bits(fmt)
    pair = [seq.augerr(5, 0, 1), seq.augadd(6, 0, 1)]
    loud = seq.run(_prog(fmt, pair), [snan, big], [one, big])
    assert loud.flags == (sf.FLAG_INVALID | sf.FLAG_OVERFLOW
                          | sf.FLAG_INEXACT)
    assert loud.lane_flags == [sf.FLAG_INVALID,
                               sf.FLAG_OVERFLOW | sf.FLAG_INEXACT]
    quiet = seq.run(_prog(fmt, [seq.quiet()] + pair + [seq.endquiet()]),
                    [snan, big], [one, big])
    assert quiet.flags == 0 and quiet.lane_flags == [0, 0]
    assert quiet.regs[0][5:7] == loud.regs[0][5:7]
    assert quiet.regs[1][5:7] == loud.regs[1][5:7]


def test_nested_regions_compose():
    """5.7.4's save/restore pairs compose: closing the inner region does
    not end the outer one, and a raise inside the outer is silenced."""
    fmt = FP32
    a, b, c = _inexact(fmt)
    fma = seq.alu(sf.OP_FMA, 3, 0, 1, 2)
    q, e = seq.quiet(), seq.endquiet()
    for body in ([q, q, e, fma, e],
                 [q, q, fma, e, e],
                 [q, q, q, q, fma, e, e, e, e],
                 [q, seq.raise_(4), e]):
        res = seq.run(_prog(fmt, body), [a], [b], [c])
        assert res.flags == 0 and res.lane_flags == [0], body


def test_a_region_hides_no_report():
    """STATUS[4], STATUS[5] and their lane bits are not IEEE flags, and
    5.7.4 restores the five exceptions' flags only: a deposit that
    overflows and a strict access past the depth inside a region are
    reported as outside one."""
    fmt = FP64
    one = sf.one_bits(fmt)
    over = seq.Program(fmt, [seq.quiet(), seq.deposit(0), seq.deposit(0),
                             seq.endquiet(), seq.halt()], max_deposits=1)
    res = seq.run(over, [one, one], [one, one])
    assert res.status == seq.STATUS_DEPOSIT_OVERFLOW
    assert res.lane_flags == [seq.LANE_DEPOSIT_OVERFLOW] * 2
    strict = seq.Program(fmt, [seq.quiet(), seq.ldx(3, 0), seq.endquiet(),
                               seq.halt()], max_deposits=0,
                         flags=seq.FLAG_SCRATCH_STRICT)
    res = seq.run(strict, [300, 3], [0, 0])
    assert res.status == seq.STATUS_SCRATCH_RANGE
    assert res.lane_flags == [seq.LANE_SCRATCH_RANGE, 0]
    _identities(res, [0, 1])


def test_a_region_in_a_loop_body_and_a_loop_in_a_region():
    """Whether an instruction is quiet depends on where it stands: three
    trips of a body whose region holds the FMA raise nothing, and a raise
    after the region in the same body raises each trip."""
    fmt = FP32
    a, b, c = _inexact(fmt)
    fma = seq.alu(sf.OP_FMA, 3, 0, 1, 2)
    flagword = sf.FLAG_DIVZERO
    res = seq.run(_prog(fmt, [seq.repeat(3), seq.quiet(), fma,
                              seq.endquiet(), seq.raise_(4), seq.endrep()]),
                  [a], [b], [c])
    assert res.flags == 0 and res.lane_flags == [0]
    # r4 holds the divide-by-zero bit through r0's stream on lane 1
    res = seq.run(_prog(fmt, [seq.repeat(3), seq.quiet(), fma,
                              seq.endquiet(), seq.raise_(0), seq.endrep()]),
                  [a, flagword], [b, b], [c, c])
    assert res.lane_flags == [a & 0x1F, flagword]
    assert res.flags == (a & 0x1F) | flagword
    res = seq.run(_prog(fmt, [seq.quiet(), seq.repeat(4), fma,
                              seq.endrep(), seq.endquiet()]), [a], [b], [c])
    assert res.flags == 0


# ---- 4. the raise and the mark -------------------------------------------------

@pytest.mark.parametrize("fmt", ALL, ids=lambda f: f.name)
def test_a_raise_ors_exactly_the_low_five_bits(fmt):
    """Every one of the 32 subsets - underflow without inexact included,
    since 5.7.4's group is any subset - and nothing from bits [6:5] or
    from bit 8 up."""
    W = fmt.width
    for v in range(32):
        for noise in (0, 0x60, 0x100, ((1 << W) - 1) & ~0xFF):
            res = seq.run(_prog(fmt, [seq.raise_(0)]), [v | noise], [0])
            assert res.flags == v and res.lane_flags == [v], (v, noise)
            assert res.status == 0


def test_the_mark_is_bit_seven_and_no_region_silences_it():
    fmt = FP64
    for inside in (False, True):
        body = [seq.raise_(0)]
        if inside:
            body = [seq.quiet()] + body + [seq.endquiet()]
        res = seq.run(_prog(fmt, body), [0x80 | 0x12, 0x80, 0x7F, 0],
                      [0, 0, 0, 0])
        assert res.status == seq.STATUS_MARKED
        flags = [0x12, 0, 0x1F & 0x7F, 0] if not inside else [0] * 4
        marks = [seq.LANE_MARKED, seq.LANE_MARKED, 0, 0]
        assert res.lane_flags == [f | m for f, m in zip(flags, marks)]
        assert res.flags == (0 if inside else 0x1F)
        _identities(res, range(4))


def test_a_raise_does_not_change_a_register_or_a_deposit():
    fmt = FP32
    v = 0xFFFF_FF9F
    res = seq.run(seq.Program(fmt, [seq.raise_(0), seq.deposit(0),
                                    seq.halt()], max_deposits=1), [v], [0])
    assert res.regs[0][0] == v and res.deposits == [v] and res.counts == [1]


def test_inactive_lanes_raise_and_mark_nothing():
    """P3 and R17: a masked lane, a padding lane and a lane SETACT dropped
    hold a flag word with every bit set, and none of them raises or
    marks; the one active lane does."""
    fmt = FP64
    one = sf.one_bits(fmt)
    allbits = (1 << fmt.width) - 1
    a = [allbits, allbits, allbits, allbits]
    c = [one, one, 0, one]                    # lane 2 dropped by SETACT r2
    res = seq.run(_prog(fmt, [seq.setact(2), seq.raise_(0)]), a, [0] * 4, c,
                  n_active=3, lane_mask=[True, False, True, True])
    assert res.flags == 0x1F and res.status == seq.STATUS_MARKED
    assert res.lane_flags == [0x9F, 0, 0, 0]
    _identities(res, _owned(4, 3, [True, False, True, True]))


# ---- 5. the per-lane byte (R23) -------------------------------------------------

def test_each_lane_keeps_its_own_flags():
    """Four lanes raise four different things - inexact, invalid, a deposit
    overflow and a mark - and each byte holds its own lane's, while FLAGS
    and STATUS hold their OR."""
    fmt = FP64
    one, snan = sf.one_bits(fmt), sf.snan_bits(fmt, 1)
    _, _, tiny = _inexact(fmt)
    # one FMA, r0 * r1 + r2: inexact in lane 0 (1 + tiny), invalid in
    # lane 1 (a signaling NaN), exact in lanes 2 and 3 (1 * 1 + 0)
    prog = _prog(fmt, [seq.alu(sf.OP_FMA, 3, 0, 1, 2)])
    res = seq.run(prog, [one, snan, one, one], [one, one, one, one],
                  [tiny, one, 0, 0])
    assert res.lane_flags == [sf.FLAG_INEXACT, sf.FLAG_INVALID, 0, 0]
    assert res.flags == sf.FLAG_INEXACT | sf.FLAG_INVALID
    _identities(res, range(4))
    # two deposits into one slot overflow in every lane; a raise of r1
    # marks lanes 2 and 3, and raises overflow in lane 3
    over = seq.Program(fmt, [seq.deposit(0), seq.deposit(0), seq.raise_(1),
                             seq.halt()], max_deposits=1)
    res = seq.run(over, [one] * 4, [0, 0, 0x80, 0x84])
    assert res.lane_flags == [seq.LANE_DEPOSIT_OVERFLOW] * 2 + [
        seq.LANE_DEPOSIT_OVERFLOW | seq.LANE_MARKED,
        seq.LANE_DEPOSIT_OVERFLOW | seq.LANE_MARKED | sf.FLAG_OVERFLOW]
    assert res.flags == sf.FLAG_OVERFLOW
    assert res.status == seq.STATUS_DEPOSIT_OVERFLOW | seq.STATUS_MARKED
    _identities(res, range(4))


def test_a_masked_and_a_padding_lane_read_zero_and_a_dropped_lane_keeps_its_byte():
    """R17's rule for every output: a masked lane's byte is not this run's
    (the model's fresh array reads 0), a padding lane has none, and a lane
    SETACT dropped keeps what it raised while it was active - and, revived
    by ACTALL, what it raises after."""
    fmt = FP32
    one, _, tiny = _inexact(fmt)
    snan = sf.snan_bits(fmt, 1)
    # r0 * r0 + r2 is inexact in every lane that runs it; SETACT r1 then
    # drops the lanes whose r1 is +0; then r0 + k[0], a signaling NaN,
    # raises invalid in the lanes still active. Lane 0 runs throughout,
    # lane 1 is dropped, lane 2 masked, lane 3 runs, lane 4 is padding.
    body = [seq.alu(sf.OP_FMA, 3, 0, 0, 2), seq.setact(1),
            seq.alu(sf.OP_ADD, 6, 0, 0, 0, kc=True)]
    prog = seq.Program(fmt, body + [seq.halt()], [snan], max_deposits=0)
    mask = [True, True, False, True, True]
    res = seq.run(prog, [one] * 5, [one, 0, one, one, one], [tiny] * 5,
                  n_active=4, lane_mask=mask)
    both = sf.FLAG_INEXACT | sf.FLAG_INVALID
    assert res.lane_flags == [both, sf.FLAG_INEXACT, 0, both, 0]
    _identities(res, _owned(5, 4, mask))
    # revived by ACTALL, the dropped lane raises again
    revive = [seq.alu(sf.OP_FMA, 3, 0, 0, 2), seq.setact(1), seq.actall(),
              seq.alu(sf.OP_ADD, 6, 0, 0, 0, kc=True)]
    prog = seq.Program(fmt, revive + [seq.halt()], [snan], max_deposits=0)
    res = seq.run(prog, [one] * 2, [one, 0], [tiny] * 2)
    assert res.lane_flags == [both, both]


def test_a_split_run_places_each_lane_byte_without_a_merge():
    """P2: a lane's byte is a function of its own inputs and the program
    alone, so a run cut anywhere is its two halves side by side - the
    bytes concatenated, FLAGS and STATUS ORed - which is how a tile split,
    a remote chunk and a software block each place them."""
    rng = random.Random(24)
    fmt = FP64
    for trial in range(60):
        insns, consts = seq.random_program(fmt, rng, scratch=True,
                                           wide_regs=True, rev8=True,
                                           flags=True)
        prog = seq.Program(fmt, insns, consts, max_deposits=2,
                           flags=seq.FLAG_SCRATCH_IO, n_scratch_out=2)
        n = rng.randint(2, 9)
        a, b, c = (seq.random_inputs(fmt, rng, n) for _ in range(3))
        whole = seq.run(prog, a, b, c)
        k = rng.randint(1, n - 1)
        lo = seq.run(prog, a[:k], b[:k], c[:k])
        hi = seq.run(prog, a[k:], b[k:], c[k:])
        assert whole.lane_flags == lo.lane_flags + hi.lane_flags, trial
        assert whole.flags == lo.flags | hi.flags
        assert whole.status == lo.status | hi.status
        _identities(whole, range(n))


def test_the_padding_seam_is_the_one_place_the_identities_part():
    """The recorded limit, stated where R23 says the identities depend on
    it: seq.py's ACTALL wakes a lane past n_active, which can then raise
    into FLAGS and owns no byte. With every lane the caller's - every run a
    caller makes - the identities hold."""
    fmt = FP32
    a, b, c = _inexact(fmt)
    snan = sf.snan_bits(fmt, 1)
    prog = _prog(fmt, [seq.actall(), seq.alu(sf.OP_ADD, 3, 0, 0, 0)])
    res = seq.run(prog, [a, snan], [b, b], [c, c], n_active=1)
    assert res.flags & sf.FLAG_INVALID, "the woken padding lane raised"
    assert res.lane_flags == [0, 0], "and owns no byte"
    full = seq.run(prog, [a, snan], [b, b], [c, c])
    _identities(full, range(2))


# ---- 6. fuzzed ---------------------------------------------------------------

def test_p3_and_the_identities_fuzzed_with_flag_control_on():
    """P3 over regions and raises: random programs run with the early exit
    forced on and off, the whole machine state compared - lane bytes
    included - and R23's identities checked on every run, masked or not.
    And the arm must reach what it exists for, or this proved nothing."""
    rng = random.Random(20261002)
    fmt = FP32
    checked = saved = 0
    seen = dict(quiet=0, nested=0, raise_quiet=0, raise_loud=0, marked=0,
                masked=0, in_loop=0)
    for _ in range(400):
        insns, consts = seq.random_program(fmt, rng, scratch=True,
                                           wide_regs=True, rev8=True,
                                           flags=True)
        strict = rng.random() < 0.3
        prog = seq.Program(fmt, insns, consts, max_deposits=2,
                           flags=seq.FLAG_SCRATCH_IO
                           | (seq.FLAG_SCRATCH_STRICT if strict else 0),
                           n_scratch_out=4)
        qd = ld = 0
        for w in insns:
            d = seq.decode(w)
            if not d["ctrl"]:
                continue
            if d["op"] == seq.QUIET:
                qd += 1
                seen["quiet"] += 1
                seen["nested"] += qd > 1
                seen["in_loop"] += ld > 0
            elif d["op"] == seq.ENDQUIET:
                qd -= 1
            elif d["op"] == seq.REPEAT:
                ld += 1
            elif d["op"] == seq.ENDREP:
                ld -= 1
            elif d["op"] == seq.RAISE:
                seen["raise_quiet" if qd else "raise_loud"] += 1
        n = rng.randint(1, 6)
        a, b, c = (seq.random_inputs(fmt, rng, n) for _ in range(3))
        mask = None
        if rng.random() < 0.3:
            mask = [rng.random() < 0.7 for _ in range(n)]
            seen["masked"] += 1
        fast = seq.run(prog, a, b, c, early_exit=True, lane_mask=mask)
        slow = seq.run(prog, a, b, c, early_exit=False, lane_mask=mask)
        assert fast.state() == slow.state(), [hex(i) for i in insns]
        _identities(fast, _owned(n, None, mask))
        seen["marked"] += bool(fast.status & seq.STATUS_MARKED)
        checked += 1
        saved += fast.insns_executed < slow.insns_executed
    assert checked == 400, "the arm drew a program validate refused"
    assert saved > 0
    assert all(seen.values()), seen


def test_the_flag_control_arm_draws_nothing_when_off():
    """A seed's corpus - the rev8 arm's included - must not move because
    the arm exists."""
    for seed in range(50):
        for rev8 in (False, True):
            r1, r2 = random.Random(seed), random.Random(seed)
            p1 = seq.random_program(FP64, r1, scratch=True, wide_regs=True,
                                    rev8=rev8)
            p2 = seq.random_program(FP64, r2, scratch=True, wide_regs=True,
                                    rev8=rev8, flags=False)
            assert p1 == p2 and r1.random() == r2.random()


# ---- 7. what R24 is for: divfull and sqrtfull, flag-exact ------------------------

def _wrapped(prog):
    """A divfull or sqrtfull image with its body in a quiet region and its
    flag word raised: `quiet` first, then `endquiet; raise r8` before the
    two deposits (bits from r3, the flag word from r8). The image has no
    loop, so the region nests trivially."""
    insns = list(prog.insns)
    tail = [seq.deposit(3), seq.deposit(8), seq.halt()]
    assert insns[-3:] == tail, "the routine's answer moved"
    body = [seq.quiet()] + insns[:-3] + [seq.endquiet(), seq.raise_(8)]
    return seq.Program(prog.fmt, body + tail, consts=(),
                       max_deposits=prog.max_deposits, flags=prog.flags,
                       n_consts=prog.n_consts)


@pytest.mark.parametrize("fmt,modes", [
    (FP32, sf.RND_MODES), (FP64, sf.RND_MODES),
    (FP128, (sf.RND_RNE, sf.RND_RDN)), (FP256, (sf.RND_RNE,)),
], ids=lambda v: getattr(v, "name", "modes"))
def test_divfull_in_a_region_raises_exactly_the_divisions_flags(fmt, modes):
    """Every special against every special, one lane a pairing. Unwrapped,
    the run's FLAGS are scaffolding - 6/3 raises inexact, 1/0 cannot raise
    divide-by-zero (the step-6 surveys measured both). Wrapped, each lane's
    byte is softfloat's flags for its own division, divide-by-zero
    included, the quotient's bits are unchanged, and FLAGS is their OR."""
    S = specials(fmt)
    a = [x for x in S for _ in S]
    b = [y for _ in S for y in S]
    plain = divfull.div_full_program_for(fmt)
    wrapped = _wrapped(plain)
    six, three = (sf.round_pack(fmt, 0, 6, 0)[0],
                  sf.round_pack(fmt, 0, 3, 0)[0])
    for rnd in modes:
        bank = divfull.bank(fmt, rnd)
        res = seq.run(wrapped, a, b, bank=bank)
        want_flags = 0
        for i in range(len(a)):
            bits, fl = sf.div(fmt, a[i], b[i], rnd)
            assert res.deposits[2 * i] == bits, (rnd, hex(a[i]), hex(b[i]))
            assert res.lane_flags[i] == fl, (rnd, hex(a[i]), hex(b[i]))
            want_flags |= fl
        assert res.flags == want_flags and res.status == 0
        # the control: unwrapped, an exact quotient raises inexact
        cut = seq.run(plain, [six], [three], bank=bank)
        assert cut.flags & sf.FLAG_INEXACT and sf.div(fmt, six, three,
                                                       rnd)[1] == 0
        ok = seq.run(wrapped, [six, sf.one_bits(fmt)], [three, 0], bank=bank)
        assert ok.lane_flags == [0, sf.FLAG_DIVZERO]


@pytest.mark.parametrize("fmt,modes", [
    (FP32, sf.RND_MODES), (FP64, (sf.RND_RNE, sf.RND_RUP)),
    (FP256, (sf.RND_RNE,)),
], ids=lambda v: getattr(v, "name", "modes"))
def test_sqrtfull_in_a_region_raises_exactly_the_roots_flags(fmt, modes):
    S = specials(fmt)
    plain = divfull.sqrt_full_program_for(fmt)
    wrapped = _wrapped(plain)
    for rnd in modes:
        res = seq.run(wrapped, S, [0] * len(S),
                      bank=divfull.bank_sqrt(fmt, rnd))
        for i, x in enumerate(S):
            bits, fl = sf.sqrt(fmt, x, rnd)
            assert res.deposits[2 * i] == bits, (rnd, hex(x))
            assert res.lane_flags[i] == fl, (rnd, hex(x))


# ---- 8. the text form (asm.py) ---------------------------------------------------

FLAGS_SRC = """.format fp64
.deposits 1
quiet
  fma r3, r0, r1, r2
  quiet
  endquiet
endquiet
repeat 2
  quiet
    ior r4, r0, r0
  endquiet
  raise r4
endrep
raise r31
deposit r3
halt
"""


def test_the_text_form_assembles_to_the_models_words():
    img = asm.Image.from_bytes(asm.assemble(FLAGS_SRC, "flags.cfta"))
    want = [seq.quiet(), seq.alu(sf.OP_FMA, 3, 0, 1, 2), seq.quiet(),
            seq.endquiet(), seq.endquiet(), seq.repeat(2), seq.quiet(),
            seq.alu(sf.OP_IOR, 4, 0, 0), seq.endquiet(), seq.raise_(4),
            seq.endrep(), seq.raise_(31), seq.deposit(3), seq.halt()]
    assert img.insns == want
    seq.Program(FP64, img.insns, max_deposits=1)
    assert img.features() == ["REGS32", "FLAG_CONTROL"]


def test_the_text_form_round_trips_with_regions_indented():
    raw = asm.assemble(FLAGS_SRC, "flags.cfta")
    text = asm.disassemble(raw)
    assert asm.assemble(text, "again.cfta") == raw
    lines = [l for l in text.splitlines() if l.strip() and not l.startswith(".")]
    assert lines[0] == "quiet" and lines[1].startswith("  fma")
    assert "    ior r4, r0, r0" in lines and "  raise r4" in lines


@pytest.mark.parametrize("line,fragment", [
    ("raise", "takes one register"),
    ("raise r1, r2", "takes one register"),
    ("quiet r1", "takes no operands"),
    ("endquiet r1", "takes no operands"),
    ("raise.rtz r1", "takes no suffix"),
    ("quiet.kx", "takes no suffix"),
])
def test_the_text_form_refuses_by_name(line, fragment):
    src = ".format fp32\n.deposits 0\nquiet\nendquiet\n" + line + "\nhalt\n"
    if line.startswith("endquiet"):
        src = ".format fp32\n.deposits 0\nquiet\n" + line + "\nhalt\n"
    with pytest.raises(asm.AsmError, match=fragment):
        asm.assemble(src, "bad.cfta")


@pytest.mark.parametrize("body,fragment", [
    ("endquiet", "no quiet region open"),
    ("quiet\nrepeat 2\nendquiet\nendrep", "closes outside it"),
    ("repeat 2\nquiet\nendrep\nendquiet", "closes in that body"),
    ("quiet\nquiet\nquiet\nquiet\nquiet\nendquiet\nendquiet\nendquiet\n"
     "endquiet\nendquiet", "deeper than 4"),
    ("quiet\nhalt\nendquiet", "halt inside the quiet"),
    ("quiet", "left open at the end"),
])
def test_the_assembler_refuses_what_the_loader_refuses(body, fragment):
    src = ".format fp32\n.deposits 0\n" + body + "\nhalt\n"
    if body == "quiet":
        src = ".format fp32\n.deposits 0\nquiet\n"
    with pytest.raises(asm.AsmError, match=fragment):
        asm.assemble(src, "bad.cfta")


def test_the_two_validators_agree_over_the_new_codes_field_space():
    """asm.py's validator and seq.py's over every single-bit perturbation
    of each R24 word, inside a region where the code needs one: accept
    together and refuse together."""
    for code in R24:
        base = seq.encode(code, ra=5 if code == seq.RAISE else 0, ctrl=True)
        pre = [seq.quiet()] if code == seq.ENDQUIET else []
        post = [seq.endquiet()] if code == seq.QUIET else []
        for bit in list(range(64)):
            w = base ^ (1 << bit)
            insns = pre + [w] + post + [seq.halt()]
            try:
                seq.Program(FP64, insns, max_deposits=0)
                m = True
            except seq.ProgramError:
                m = False
            try:
                asm.Image(FP64, insns, max_deposits=0).validate()
                a_ok = True
            except asm.AsmError:
                a_ok = False
            assert m == a_ok, (seq.CTRL_NAMES[code], bit)
