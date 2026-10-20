# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""Tests of python/c5_class_enum.py, the reference for the clause-5 soak's class-level (L2) modes.

What is shown here is that the ENUMERATION reaches every class, at the class level and no further:

  * the decision rule this file's module uses is the study's `decide` (docs/studies/swp-a/symmetry_check.py),
    loaded from the study's own source and compared on every (sign, attribute, class, lsb);
  * the five index spaces have the sizes their formulas give, and the sizes the C tool prints;
  * at e4m3 and e5m6 (the formats where the study's exhaustion works) every key (sign, position, class, kept lsb,
    kept all ones) that ANY encoding exhibits is reached by at least one enumerated case, for all five operations;
  * a plant that drops one class fails that check by name (the keys of the dropped class, listed), for every class
    and every operation; so does a wrong class selector, except where a class is reached a second way;
  * at p = 24 and p = 53 the built operand's key equals the key its index names, for every non-degenerate index;
  * a planted rounding defect (a sticky tree without the lowest dropped bit) is caught by the class set and missed
    by an equal number of the soak's own random draws.

A pass is a claim about the enumeration. That the rounding unit has the structure the enumeration assumes is the
second level's assumption (docs/studies/SWP-A-coverage.md 4.3), and nothing here tests it.
"""
import ast
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "python"))

import c5_class_enum as C  # noqa: E402
from cft_golden import softfloat as sf  # noqa: E402

SMALL = C.small_enums()
WIDE = C.wide_enums()
ENUMS64 = C.enums64()


def test_decide_is_the_studys():
    """The decision rule used for classification is the study's `decide`, taken from the study's source."""
    src = (ROOT / "docs" / "studies" / "swp-a" / "symmetry_check.py").read_text(encoding="utf-8")
    fn = next(n for n in ast.parse(src).body if isinstance(n, ast.FunctionDef) and n.name == "decide")
    ns = {"sf": sf}
    exec(compile(ast.Module([fn], []), "symmetry_check.decide", "exec"), ns)
    n = 0
    for sign in (0, 1):
        for mode in (sf.RND_RNE, sf.RND_RTZ, sf.RND_RDN, sf.RND_RUP, sf.RND_RMM):
            for cls in range(4):
                for lsb in (0, 1):
                    assert C.decide(sign, mode, cls, lsb) == ns["decide"](sign, mode, cls, lsb)
                    n += 1
    assert n == 80


def test_sizes_are_their_formulas():
    """The counts, derived: positions x 2 signs x 4 classes x (4 + W) patterns, and the other three."""
    want = {"conv64to32-class": 136192, "rint64-class": 35840, "cvtto64-class": 40768, "cvtfrom64-class": 50923,
            "scaleb64-class": 72648}
    assert {k: v.N for k, v in ENUMS64.items()} == want
    assert 304 * 2 * 4 * 56 == 136192 and (281 + 23) == 304            # conv: the study's 281 + the 23 witnesses
    assert 80 * 448 == 35840 and (57 + 23) == 80                      # rint: [-3, 53] + 23
    assert 91 * 448 == 40768 and (68 + 23) == 91                      # cvtto: [-3, 64] + 23
    assert 190 * 4 * 67 + 3 == 50923 and (63 + 63 + 64) == 190        # cvtfrom
    assert 3 * 54 * 448 + 2 * 36 == 72648                             # scaleb: 3 routes x 54 strips, + 2 blocks of 36
    # the study's conv64to32 figure counts three magnitude functions: 281 x 4 x 56 x 2 x 3
    assert 281 * 4 * 56 * 2 * 3 == 377664 == 3 * (281 * 448)
    # k, the checks an index makes: a case a target for cvtto, a case a lane for the two tile modes, else 1
    assert {n: e.k for n, e in ENUMS64.items()} == {"conv64to32-class": 1, "rint64-class": 4, "cvtto64-class": 4,
                                                     "cvtfrom64-class": 1, "scaleb64-class": 4}
    assert ENUMS64["rint64-class"].attrs == ENUMS64["cvtto64-class"].attrs == ("rne", "rtz", "rdn", "rup", "rmm")
    assert ENUMS64["conv64to32-class"].attrs == ("rne", "rtz", "rdn", "rup")


def test_the_witnesses_are_finite_exponent_fields():
    for E in (4, 5, 11):
        w = C.exp_witnesses(E)
        assert len(w) == 2 * E + 1 and 0 in w and all(0 <= b <= (1 << E) - 2 for b in w), E


def test_the_builder_makes_each_class_and_pattern():
    """sig(): the dropped bits have the class asked for and the kept bits the lsb and all-ones asked for, where the
    cell is non-degenerate; the walking one lands on the bit asked for."""
    P = 53
    for d in (2, 5, 29, 30, 48):
        k = P - d
        for c in range(4):
            for t in range(4):
                m = C.sig(P, d, c, t)
                cls, lsb, ones = C.cls_lsb_ones(m, 0, d)
                assert (cls, lsb, ones) == (c, t & 1, t == 3), (d, c, t)
                assert m.bit_length() == P
        for w in range(52):
            m = C.sig(P, d, 0, 4 + w)
            assert m & (1 << w) and m.bit_length() == P
    assert C.sig(53, 29, 2, 0) & ((1 << 29) - 1) == 1 << 28           # class 2: the guard bit alone
    assert C.sig(53, 29, 3, 0) & ((1 << 29) - 1) == (1 << 28) | 1     # class 3: guard and the lowest bit
    assert C.sig(53, 29, 1, 0) & ((1 << 29) - 1) == 1                  # class 1: the lowest bit alone


@pytest.mark.parametrize("label", list(SMALL))
def test_every_key_of_the_small_format_is_reached(label):
    """The coverage check: every key any encoding (or source integer, or encoding-exponent pair) exhibits is reached."""
    e = SMALL[label]
    n_uni, n_reached, missing, extra = C.coverage(e)
    assert n_uni > 30
    assert missing == [], f"{label}: {len(missing)} of {n_uni} keys not reached, first {missing[:3]}"
    assert n_reached == n_uni and extra == 0


@pytest.mark.parametrize("cls", range(4))
@pytest.mark.parametrize("label", list(SMALL))
def test_a_plant_that_drops_a_class_fails_the_check_by_name(label, cls):
    """An enumerator that never produces one class leaves that class's keys unreached, and the check names them."""
    e = SMALL[label]
    _, _, missing, _ = C.coverage(e, drop_class=cls)
    assert missing, f"{label}: dropping the {C.CLS_NAMES[cls]} class went unnoticed"
    named = [k for k in missing if k[1] != "ovf"]
    assert named and all(k[2] == cls for k in named), (label, cls, missing[:3])


@pytest.mark.parametrize("label", ["conv e5m6->e4m3", "rint e5m6", "cvtto e5m6 (B=8)", "cvtfrom i8 -> e4m3"])
def test_a_wrong_class_selector_fails_the_check(label):
    """A class selector that gives the cases of one class the next class's operand leaves keys unreached too (scaleb
    e4m3's half class is the exception, reached a second way: a walking one on the class-0 representative at the
    guard bit, and is left out here)."""
    for cls in range(4):
        _, _, missing, _ = C.coverage(SMALL[label], drop_class=cls, drop_by="slot")
        assert missing, f"{label}: a wrong selector for the {C.CLS_NAMES[cls]} class went unnoticed"


def test_the_check_can_fail_a_real_gap():
    """The universe is not read from the enumerator: take away every case at one structural exponent (e = 2, which no
    witness repeats) and the check must report exactly the keys at that position, by name."""
    e = SMALL["rint e5m6"]
    uni, reached = C.universe_and_reached(e)
    assert uni <= reached
    pi_gap = 2 - e.lo_e
    kept = set()
    for i in range(e.N):
        if e.split(i)[0] == pi_gap:
            continue
        k = C.key_round(e, e.operand(i))
        if k:
            kept.add(k)
    still = sorted(k for k in uni if k not in kept)
    assert still and all(k[1] == 2 for k in still), still[:3]
    assert {k for k in uni if k[1] == 2} == set(still)


@pytest.mark.parametrize("label", list(WIDE))
def test_the_built_key_is_the_named_key_at_p24_and_p53(label):
    e = WIDE[label]
    checked, bad, firsts = C.constructive(e)
    assert checked > 400, (label, checked)
    assert bad == 0, (label, bad, firsts)


def test_constructive_can_fail():
    """Control: a builder with the class-3 representative wrong (the lowest bit forgotten, so 'above half' is 'half')
    must fail the constructive check."""
    real = C.sig

    def broken(P, d, c, t):
        return real(P, d, 2 if c == 3 else c, t)

    C.sig = broken
    try:
        checked, bad, firsts = C.constructive(WIDE["rint fp64 (p 53)"])
    finally:
        C.sig = real
    assert bad > 0 and firsts


def test_the_distinct_operands():
    """Each space's operands that differ (the rest are repeats where a class or pattern does not exist at a position,
    or a witness repeats a structural cell)."""
    got = {k: C.distinct(v) for k, v in ENUMS64.items()}
    assert got == {"conv64to32-class": 124984, "rint64-class": 26032, "cvtto64-class": 27242, "cvtfrom64-class": 11557,
                   "scaleb64-class": 65992}


def test_scaleb_strips_are_where_they_say():
    """Every strip index's (operand, exponent) lands in the strip it names; the blocks overflow or fall below the last
    strip; nothing in the space is an in-range (exact) result."""
    e = ENUMS64["scaleb64-class"]
    seen = set()
    for i in range(e.N):
        a, n = e.operands(i)
        k = C.key_scaleb(e, a, n)
        assert k is not None, i                                       # never an in-range result
        if i < e.nstripidx:
            pi, sign, c, t = e.split(i)
            route, s = divmod(pi, e.nstrip)
            assert k[1] == s + 1 and k[0] == sign, (i, k)
        else:
            assert k[1] in ("ovf", "deep"), (i, k)
        seen.add(k[1])
    assert seen == set(range(1, 55)) | {"ovf", "deep"}


def test_cvtto_skips_are_counted_by_the_rule():
    """expected_skipped_cvtto: the pairs a slice must skip, from the rule alone, on cases worked by hand."""
    e = ENUMS64["cvtto64-class"]
    one = 0x3FF0000000000000                                         # 1.0: rounds to 1 in every target
    assert C.rounded_integer(C.FP64, one, "rne") == 1
    assert C.rounded_integer(C.FP64, one | (1 << 63), "rne") == -1    # -1: out of both unsigned targets
    big = (1023 + 63) << 52                                           # 2^63: only u64 holds it
    assert C.rounded_integer(C.FP64, big, "rtz") == 1 << 63
    nan = 0x7FF8000000000000
    assert C.rounded_integer(C.FP64, nan, "rne") is None
    # the whole space for one attribute: the skips are strictly between none and all
    s = C.expected_skipped_cvtto(e, 0, e.N, "rne")
    assert 0 < s < 4 * e.N
    # the targets compared, by name, on a few operands: 1.0 is held by all four, -1.0 by the two signed, 2^63 by u64 alone,
    # 2^31 (rne) by every target but i32, a NaN by none
    class _One:                                               # an enumerator stand-in that returns one fixed operand
        src = C.FP64
        def __init__(self, x): self.x = x
        def operand(self, i): return self.x
    assert C.compared_targets(_One(one), 0, "rne") == ("i32", "u32", "i64", "u64")
    assert C.compared_targets(_One(one | (1 << 63)), 0, "rne") == ("i32", "i64")
    assert C.compared_targets(_One(big), 0, "rtz") == ("u64",)
    assert C.compared_targets(_One((1023 + 31) << 52), 0, "rne") == ("u32", "i64", "u64")
    assert C.compared_targets(_One(nan), 0, "rne") == ()


def test_cvtto_cases_by_the_rule_are_the_tools_counts():
    """The cases cvtto64-class makes over its whole space, counted in Python from the rounding rule alone, equal the numbers the
    C tool printed on the software backend (MEASURED, 2026-10-20: hw/test_c5_class.py holds the tool to its own count on every
    run; these are the figures a driver can hold the whole item to)."""
    e = ENUMS64["cvtto64-class"]
    want = {"rne": 91005, "rtz": 91484, "rdn": 85141, "rup": 91478, "rmm": 90986}
    got = {a: C.expected_compared_cvtto(e, 0, e.N, a) for a in e.attrs}
    assert got == want
    assert all(got[a] + C.expected_skipped_cvtto(e, 0, e.N, a) == 4 * e.N for a in e.attrs)


def test_the_planted_rounding_defect_is_caught_by_the_class_set_and_missed_by_random_draws():
    """A stand-in for the conversion's unit, written as the structure the second level assumes. Correct it equals the
    golden model; with a sticky tree that leaves out the lowest dropped bit it is wrong exactly where the only dropped bit
    set below the guard is the lowest one. The class set reaches that case (a walking one at bit 0 on the class-0 and
    class-2 representatives); the soak's own random draws, as many of them, do not."""
    r = C.defect_experiment(attrs=("rne", "rup"), seeds=(1, 77))
    for name, v in r["attrs"].items():
        assert v["stand_in_vs_golden"] == 0, (name, v)               # the stand-in is the rounding it stands in for
        assert v["class_set_hits"] > 0, (name, v)                    # the class set catches the planted defect
        assert all(h == 0 for h in v["random_hits"].values()), (name, v)   # the same number of random draws do not
    # COMPUTED bound: the defect needs the 28 bits below the guard to be exactly 000...01, so a core draw hits with
    # probability at most 2^-28, and a draw that rounds into a strip (more dropped bits) with less
    assert r["N"] * 2.0 ** -28 < 1e-3


def test_the_ported_generator_makes_the_values_the_tool_makes():
    """SoakRng is the tool's xorshift64 and banded64() (the band draw first). The values are the operands the real
    software backend printed for the first lane of each 4,096-lane batch of `CFT_SOAK_SABOTAGE=1 clause5-soak conv64to32
    100000 1 rne` (READ, 2026-10-20); hw/test_c5_class.py holds the port to the real tool again, 16 batches a run."""
    g = C.SoakRng(1)
    got = []
    for _ in range(5):
        got.append(g.banded64())
        for _ in range(4095):
            g.banded64()
    assert got == [0x40822041, 0xBFF70BD15785503C, 0x18DBD7E6D74019D9, 0x6C6AA5D1FCF742CE, 0x62942860C1B70170]
    assert C.SoakRng(2).s == 3 and C.SoakRng(3).s == 3               # state = seed | 1


MODES = (sf.RND_RNE, sf.RND_RTZ, sf.RND_RDN, sf.RND_RUP, sf.RND_RMM)


def test_the_keys_predict_the_golden_model_on_every_enumerated_case():
    """What ties the keys to the authority: at the small formats, the decision rule applied to the class and lsb the key
    reads off the definitions gives the result python/cft_golden gives, for every enumerated case of conv, rint, cvtfrom
    and scaleb, under every attribute (scaleb under the four it takes), and the integer rounded_integer gives for cvtto.
    Cases whose result overflows the destination are not compared (the rule says nothing about them)."""
    n = {"conv": 0, "rint": 0, "cvtto": 0, "cvtfrom": 0, "scaleb": 0}
    e = SMALL["conv e5m6->e4m3"]
    for i in range(e.N):
        x = e.operand(i)
        u = sf.unpack(e.src, x)
        if u.kind not in (sf.NORM, sf.SUB):
            continue
        top = u.m.bit_length() - 1 + u.e
        ulp = max(top - e.dst.man_w, e.dst.emin - e.dst.man_w)
        for mode in MODES:
            p = C.predict_round(e.dst, u.sign, u.m, u.e, ulp, mode)
            if p is not None:
                n["conv"] += 1
                assert p == sf.convert(e.src, e.dst, x, mode)[0], (i, mode)
    for label in ("rint e5m6", "rint e4m3"):
        e = SMALL[label]
        for i in range(e.N):
            x = e.operand(i)
            u = sf.unpack(e.src, x)
            if u.kind not in (sf.NORM, sf.SUB):
                continue
            for mode in MODES:
                p = C.predict_round(e.src, u.sign, u.m, u.e, 0, mode)
                if p is not None:
                    n["rint"] += 1
                    assert p == sf.round_int(e.src, x, mode)[0], (label, i, mode)
    for label in ("cvtto e5m6 (B=8)", "cvtto e4m3 (B=6)"):
        e = SMALL[label]
        for i in range(e.N):
            x = e.operand(i)
            if sf.unpack(e.src, x).kind not in (sf.NORM, sf.SUB):
                continue
            for mode in MODES:
                names = {v: k for k, v in C.MODE_OF.items()}
                got = C.rounded_integer(e.src, x, names[mode])
                assert got == sf.to_int(e.src, x, 64, True, mode)[0], (label, i, mode)
                n["cvtto"] += 1
    for label in ("cvtfrom i8 -> e4m3", "cvtfrom i10 -> e5m6"):
        e = SMALL[label]
        for i in range(e.N):
            v, unsigned = e.operands(i)
            sv = v if unsigned or not v >> (e.Wi - 1) else v - (1 << e.Wi)
            if sv == 0:
                continue
            mag = abs(sv)
            for mode in MODES[:4]:
                p = C.predict_round(e.dst, int(sv < 0), mag, 0, max(mag.bit_length() - e.dst.prec, 0), mode)
                if p is not None:
                    n["cvtfrom"] += 1
                    assert p == sf.from_int(e.dst, sv, mode)[0], (label, i, mode)
    e = SMALL["scaleb e4m3"]
    f = e.fmt
    for i in range(e.N):
        a, nx = e.operands(i)
        u = sf.unpack(f, a)
        if u.kind not in (sf.NORM, sf.SUB):
            continue
        r = u.m.bit_length() - 1 + u.e + nx
        if r > f.emax:
            continue
        for mode in MODES[:4]:
            p = C.predict_round(f, u.sign, u.m, u.e + nx, f.emin - f.man_w, mode)
            if p is not None:
                n["scaleb"] += 1
                assert p == sf.scaleb(f, a, nx, mode)[0], (i, nx, mode)
    assert all(v > 3000 for v in n.values()), n


@pytest.mark.parametrize("label", list(SMALL))
def test_every_carry_out_of_the_kept_bits_is_reached(label):
    """The carry, which the brief names as a key of its own: every (key, attribute) pair whose kept bits are all ones and
    whose attribute rounds the magnitude up - the increment that runs the whole chain and moves the exponent - that any
    encoding exhibits, an enumerated case exhibits."""
    cu, cr = C.carry_coverage(SMALL[label])
    assert len(cu) >= 6, (label, len(cu))
    assert cu <= cr, sorted(cu - cr, key=str)[:3]


def test_a_plant_that_drops_a_class_loses_carries_too():
    """Removing the above-half class (the class every attribute rounds up by) removes carries, by name."""
    e = SMALL["conv e5m6->e4m3"]
    uni, reached = C.universe_and_reached(e, drop_class=3)
    lost = C.carry_pairs(uni, e.attrs) - C.carry_pairs(reached, e.attrs)
    assert lost and all(k[2] == 3 for k, a in lost)
