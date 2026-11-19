# M3 model: the table of plants (scratch; the study's section 8). Each plant
# is one fault of m3pow.PLANTS; each is red in a NAMED case and the control
# (no plant) is green there. A case is one of:
#
#   lane    the lane is wrong and UNMARKED with the plant (bits or flags
#           differ from transcend.py), right without it
#   mark    the design decides the lane in-lane (unmarked and right) and
#           the plant marks it: a test "these lanes are decided" fails
#   budget  the first-order budget of a region is past 1 Bv with the plant,
#           under 1 without it
#
#   python plants.py FMT

import sys
import time
from fractions import Fraction

import mpmath

from m3core import FORMATS, RNE, RTZ, RDN, RUP, RMM, AN, sf, val, dec, enc
from m3core import golden
import m3pow as M
import m3harness as H


def lane_state(fmt, fn, lane, rnd, plant):
    n = lane[1] if fn in ("pown", "rootn", "compound") else None
    if plant is None:
        bld = M.build_any(fn, fmt, rnd, n=n)
    else:
        bld = M.build(fn, fmt, rnd, n=n, plant=plant)
    bits, fl, _ = M.run(bld, fn, lane)
    want = golden(fmt, fn, lane, rnd)
    if fl & M.ml.MARK:
        return "marked", bits, fl, want
    return ("right" if (bits, fl) == want else "WRONG"), bits, fl, want


def screen_lane(fmt):
    """A lane whose ROUTINE's t_h0 is exactly emax + 1 and whose result is
    finite under rne (transcend.py's answer not an infinity): the low
    screen's overflow is wrong there. Searched on the control's probe."""
    p = fmt.prec
    top = fmt.emax + 1
    b = M.build("pow", fmt, RNE)
    for M_ in range(3, 400, 2):
        x = val(fmt, 0, M_, 0)
        with mpmath.workprec(4 * p):
            L = mpmath.log(M_, 2)
            y0 = M.ml._frac(mpmath.mpf(top) / L)
        yb = enc(fmt, y0)
        for d in range(-3, 4):
            y = yb + d
            _bits, _fl, pr = M.run(b, "pow", (x, y), ("th0",))
            if dec(fmt, pr["th0"]) != top:
                continue
            want = golden(fmt, "pow", (x, y), RNE)
            if (want[0] & ~fmt.sign_mask) != sf.inf_bits(fmt):
                return (x, y)
    return None


def zero_lane(fmt):
    """pow(-2^E, d), d odd, d E = emin - p - 1: an exact -2^(emin-p-1),
    below half the least subnormal, which rounds to -0 with underflow under
    rne (the fixed grid's signed zero)."""
    t0 = fmt.emin - fmt.prec - 1
    for d in range(3, 1 << 20, 2):
        if t0 % d == 0:
            return (val(fmt, 1, 1, t0 // d), val(fmt, 0, d, 0))
    return None


_LOOSE = {}


def midpoint_lane(fmt):
    """pow(x, 2) exactly a midpoint, x = (3 2^(h-2) + k) 2^-(h-1) near 1.5
    (h = (p + 2)/2, k odd: the square's odd part p + 1 bits), where the loose
    bound's answer is wrong under rne. Not near 1: there V's own error is
    below the ulp of V_l, which is the test's resolution, so no bound below
    it can leave a midpoint unmarked (the first search, near 1, found none:
    the study's 8)."""
    p = fmt.prec
    h = (p + 2) // 2
    two = val(fmt, 0, 2, 0)
    if fmt.name not in _LOOSE:
        _LOOSE[fmt.name] = M.build("pow", fmt, RNE, plant="bound_loose")
    b = _LOOSE[fmt.name]
    for k in range(1, 4000, 2):
        Mx = 3 * (1 << (h - 2)) + k
        if (Mx * Mx).bit_length() != p + 1:
            continue
        x = val(fmt, 0, Mx, -(h - 1))
        if x is None:
            continue
        bits, fl, _ = M.run(b, "pow", (x, two))
        if fl & M.ml.MARK:
            continue
        if (bits, fl) != golden(fmt, "pow", (x, two), RNE):
            return (x, two)
    return None


def notl_lane(fmt):
    """x = 2^E, y = RN(k/E): t = k + f with t_h = k and t_l = f != 0."""
    for E in (1000, 999, 997, 991, 701, 333, 120, 100, 77):
        if E > fmt.emax:
            continue
        for k in (3, 5, 7, 2, 1):
            y = enc(fmt, Fraction(k, E))
            q = dec(fmt, y) * E
            if q != k and abs(q - k) < Fraction(1, 2 ** (fmt.prec - 1)):
                return (val(fmt, 0, 1, E), y)
    return None


def cases(fmt):
    p = fmt.prec
    v = lambda s, m, e: val(fmt, s, m, e)                  # noqa: E731
    one = sf.one_bits(fmt)
    out = [
        ("exact_unmarked", "pow", RNE, "lane", (v(0, 3, 0), v(0, 2, 0))),
        ("exact_unmarked", "pow", RNE, "lane", (v(0, 10, 0), v(0, 3, 0))),
        ("exact_rule_off", "pow", RTZ, "mark", (v(0, 1, 1), v(0, 10, 0))),
        ("exact_rule_off", "pow", RNE, "mark", (v(0, 1, -1), v(0, 3, 0))),
        ("exact_rule_no_tl", "pow", RNE, "lane", notl_lane(fmt)),
        ("midpoint_unmarked", "pow", RNE, "redundant",
         (v(0, 3, -((fmt.man_w - fmt.emin + 1) // 5)), v(0, 5, 0))
         if (fmt.man_w - fmt.emin + 1) % 5 == 0 else None),
        ("bound_loose", "pow", RNE, "lane", midpoint_lane(fmt)),
        ("pow_zero_nan", "pow", RNE, "lane", (sf.qnan_bits(fmt), 0)),
        ("pow_one_nan", "pow", RNE, "lane", (one, sf.qnan_bits(fmt))),
        ("sign_even", "pow", RNE, "lane",
         (enc(fmt, Fraction(-11, 10)), v(0, 2, 0))),
        ("sign_odd_lost", "pow", RNE, "lane",
         (enc(fmt, Fraction(-11, 10)), v(0, 3, 0))),
        ("zero_sign_lost", "pow", RNE, "lane", zero_lane(fmt)),
        ("integrality_wide", "pow", RNE, "lane",
         ((one + 1) | fmt.sign_mask, v(0, (1 << (p - 2)) + 1, 0))),
        ("powr_neg_ok", "powr", RNE, "lane", (v(1, 1, 1), v(0, 1, -1))),
        ("powr_zero_zero", "powr", RNE, "lane", (0, 0)),
        ("rootn_m0_neg", "rootn", RNE, "lane", (fmt.sign_mask, 2)),
        ("compound_onep_rounded", "compound", RNE, "lane",
         (enc(fmt, Fraction(1, 10)), 3)),
        ("near_one_gate_off", "pow", RTZ, "mark",
         (one + 1, v(0, 1, -60))),
        ("side_rule_off", "pow", RUP, "lane",
         (enc(fmt, Fraction(6, 5)), sf.min_subnormal_bits(fmt))),
        ("side_rule_off", "pow", RTZ, "lane",
         (enc(fmt, Fraction(5, 6)), sf.min_subnormal_bits(fmt))),
        ("screen_low", "pow", RNE, "lane", screen_lane(fmt)),
        ("mark_silenced", "pow", RTZ, "lane", (v(0, 3, 0), v(0, 2, 0))),
    ]
    return out


def main():
    fmt = FORMATS[sys.argv[1]]
    t0 = time.time()
    red = 0
    rows = cases(fmt)
    for plant, fn, rnd, kind, lane in rows:
        if lane is None:
            print(f"{fmt.name} {plant:22s} {fn:8s} {AN[rnd]}: no lane at this "
                  f"format (not run)")
            continue
        ctl = lane_state(fmt, fn, lane, rnd, None)
        got = lane_state(fmt, fn, lane, rnd, plant)
        if kind == "lane":
            ok = got[0] == "WRONG" and ctl[0] in ("right", "marked")
        elif kind == "mark":
            ok = got[0] == "marked" and ctl[0] == "right"
        else:
            # "redundant": a plant the design's argument says cannot fail
            # (the study's 8): it is shown equal to the control, not red
            ok = None
            same = got[:3] == ctl[:3]
            print(f"{fmt.name} {plant:22s} {fn:8s} {AN[rnd]} {kind:9s} "
                  f"{H.show(fmt, lane, fn)}: plant {got[0]} ({got[1]:#x}, "
                  f"{got[2]:#x}), control {ctl[0]} ({ctl[1]:#x}, "
                  f"{ctl[2]:#x}) -> {'EQUAL TO THE CONTROL' if same else 'DIFFERS'}"
                  f" (not counted)", flush=True)
            continue
        red += ok
        print(f"{fmt.name} {plant:22s} {fn:8s} {AN[rnd]} {kind:6s} "
              f"{H.show(fmt, lane, fn)}: plant {got[0]} ({got[1]:#x}, "
              f"{got[2]:#x}), control {ctl[0]} ({ctl[1]:#x}, {ctl[2]:#x}), "
              f"transcend ({got[3][0]:#x}, {got[3][1]:#x}) -> "
              f"{'RED' if ok else 'not red'}", flush=True)
    counted = sum(1 for r in rows if r[4] is not None and r[3] != "redundant")
    print(f"{fmt.name}: {red} of {counted} lane and mark cases red; "
          f"{time.time() - t0:.0f} s (the budget plants: budget.py with a "
          f"plant)")


if __name__ == "__main__":
    main()
