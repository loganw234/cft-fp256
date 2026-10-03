# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""The routines the compiler inlines (cft_golden/routines.py, C4),
against the contract and against divfull.

* the read form IS divfull's program: instruction for instruction (each
  opcode, each attribute, each word by its bank index's name), and run as
  a program it deposits what divfull deposits, lane for lane, the flag
  word included;
* each specialised fragment, at every format and every attribute, run on
  seq.py against softfloat's div and sqrt lane by lane: the bits AND each
  lane's own flag word, over test_divfull's pools (the light cut here;
  the lang stage runs the full pools);
* what is proved of every fragment (routines.invariants): the flag word's
  values within the six a division or root can raise, never bit 7; at
  most sixteen values live; every instruction reading a word or an
  internal value; nothing left to simplify; the attributes the
  routine's own - one truncating fma in the division, none in the root;
* each specialisation rule planted wrong - a SELECT fold picking the
  other arm, an IOR taken for its first operand - red on the pools.
"""

import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from cft_golden import FP32, FP64, FP128, FP256, asm, divfull, seq  # noqa: E402
from cft_golden import routines as R  # noqa: E402
from cft_golden import softfloat as sf  # noqa: E402
from cft_golden.softfloat import RND_MODES  # noqa: E402

from routine_pools import div_pairs, sqrt_xs  # noqa: E402

FORMATS = (FP32, FP64, FP128, FP256)


def lanes(op, fmt, light=True):
    return div_pairs(fmt, light) if op == "div" else sqrt_xs(fmt, light)


def wrong_lanes(f, ls):
    """[(lane, got, want)] where the fragment is not softfloat's."""
    if f.op == "div":
        outs, words = R.run(f, [p[0] for p in ls], [p[1] for p in ls])
    else:
        outs, words = R.run(f, ls)
    bad = []
    for i, x in enumerate(ls):
        args = x if f.op == "div" else (x,)
        want = R.GOLDEN[f.op](f.fmt, *args, f.rnd)
        if (outs[i], words[i]) != want:
            bad.append((x, (outs[i], words[i]), want))
    return bad


@pytest.mark.parametrize("op", ["div", "sqrt"])
@pytest.mark.parametrize("fmt", FORMATS, ids=lambda f: f.name)
def test_the_read_form_is_divfull_instruction_for_instruction(op, fmt):
    prog = (divfull.div_full_program_for(fmt) if op == "div"
            else divfull.sqrt_full_program_for(fmt))
    names = divfull._NAMES_DIV if op == "div" else divfull._NAMES_SQRT
    f = R.read(op, fmt, sf.RND_RNE)
    alu = [seq.decode(w) for w in prog.insns if not seq.decode(w)["ctrl"]]
    assert len(f) == len(alu) == len(prog.insns) - 3
    for (opc, rnd, srcs), d in zip(f.body, alu):
        assert opc == d["op"]
        assert rnd == (d["rnd"] if opc in R.ROUNDED else None)
        consts = [names[idx] for (idx, k), field in
                  zip(seq.sources(d), ("ra", "rb", "rc"))
                  if k and field in asm.OP_FIELDS[d["op"]]]
        assert [s[1] for s in srcs if s[0] == "w"] == consts
    # run as a program it deposits what divfull deposits, lane for lane
    ls = lanes(op, fmt)[:300]
    a = [x[0] for x in ls] if op == "div" else ls
    b = [x[1] for x in ls] if op == "div" else [0] * len(ls)
    for rnd in (sf.RND_RNE, sf.RND_RDN):
        bank = divfull.bank(fmt, rnd) if op == "div" else \
            divfull.bank_sqrt(fmt, rnd)
        ref = seq.run(prog, a, b, bank=bank)
        outs, words = R.run(R.read(op, fmt, rnd), a, b)
        assert outs == ref.deposits[0::2] and words == ref.deposits[1::2]


@pytest.mark.parametrize("rnd", RND_MODES)
@pytest.mark.parametrize("op", ["div", "sqrt"])
@pytest.mark.parametrize("fmt", FORMATS, ids=lambda f: f.name)
def test_each_fragment_is_softfloats_bits_and_flags_lane_by_lane(fmt, op,
                                                                  rnd):
    f = R.fragment(op, fmt, rnd)
    bad = wrong_lanes(f, lanes(op, fmt))
    assert not bad, (f"{op} {fmt.name} rnd={rnd}: {len(bad)} lanes, first "
                     f"{bad[0]}")


@pytest.mark.parametrize("op", ["div", "sqrt"])
@pytest.mark.parametrize("fmt", FORMATS, ids=lambda f: f.name)
def test_what_is_proved_of_every_fragment(fmt, op):
    for rnd in RND_MODES:
        f = R.fragment(op, fmt, rnd)
        assert R.invariants(f) == []
        assert R.flag_words(f) <= R.FLAG_WORDS
        assert all(not w & 0x80 for w in R.FLAG_WORDS)
        assert f.live_max() <= R.LIVE_MAX
        assert f.result[0] == f.flags[0] == "v"
        rtz = [i for i, (_o, r, _s) in enumerate(f.body) if r == sf.RND_RTZ]
        assert len(rtz) == (1 if op == "div" else 0)
        if op == "div":
            assert f.body[rtz[0]][0] == sf.OP_FMA        # q2, truncated
        assert len(f) < len(R.read(op, fmt, rnd))
        # the words are divfull's, at this attribute, by name
        bank = divfull.bank(fmt, rnd) if op == "div" else \
            divfull.bank_sqrt(fmt, rnd)
        names = divfull._NAMES_DIV if op == "div" else divfull._NAMES_SQRT
        for name, bits in f.words.items():
            assert bits == bank[names.index(name)]
    assert R.fragment(op, fmt, sf.RND_RNE) is R.fragment(op, fmt, sf.RND_RNE)


def test_a_routine_is_refused_for_an_unknown_op():
    with pytest.raises(ValueError):
        R.read("exp", FP64, sf.RND_RNE)


@pytest.mark.parametrize("plant", ["select picks the other arm",
                                   "ior taken for its first operand"])
def test_each_specialisation_rule_planted_wrong_is_red(plant, monkeypatch):
    """Each rule of step 3 changed to a wrong one - a SELECT fold that
    picks the arm the condition does not, an IOR with distinct operands
    taken for its first - makes some lane wrong on the light pools at
    fp64 under rne: the tests above see the rules, not just the code."""
    good = R.simplify

    def wrong(op, srcs, bits_of, sign_mask):
        if plant.startswith("select") and op == sf.OP_SELECT:
            c = bits_of(srcs[2])
            if c is not None:
                return srcs[1] if c & ~sign_mask else srcs[0]
        if plant.startswith("ior") and op == sf.OP_IOR:
            return srcs[0]
        return good(op, srcs, bits_of, sign_mask)
    monkeypatch.setattr(R, "simplify", wrong)
    red = 0
    for op in ("div", "sqrt"):
        f = R.specialise(R.read(op, FP64, sf.RND_RNE))
        try:
            red += len(wrong_lanes(f, lanes(op, FP64)))
        except AssertionError:
            red += 1                            # it did not even run
    assert red, f"{plant}: green on the pools"
