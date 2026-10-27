# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""The hard-case generator (python/hardcases.py) and the golden model's answers on what it builds.

Three things, none of which is the soak tool's (hw/test_divsqrt_hard.py holds that against the C tool):

  1. The generator's own claims hold in exact integers: the space's table, the keyed mixer against the published
     splitmix64 outputs, `verify` over every small segment and a sample of every large one, the F0 skip rate against
     the number theory (a divisor skips with probability 1 - ln 2 over both quotient binades), and `verify`'s
     refusals, by planting one wrong builder at a time in process.
  2. The golden model's division and square root equal an exact arbiter written here from the definitions of
     IEEE 754-2019 5.4.1 and 7 (Fractions and isqrt: a quotient's position on the grid, the five rounding
     attributes, tininess after rounding, the overflow landings), on a sample of every family of both formats, all
     four sign slots and all five attributes, bits and flags. The arbiter shares no code with softfloat.py, nor
     with the generator's builders.
  3. A second, independent arbiter for fp64 round-to-nearest: CPython's own float division and math.sqrt, which are
     the host FPU's - the oracle the soak uses.

The cases are the ones a sampler never reaches at fp64 (docs/studies/SWP-A-coverage.md section 4.2).
"""

import math
import struct
import sys
from fractions import Fraction
from math import isqrt
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import hardcases as H  # noqa: E402
from cft_golden import softfloat as sf  # noqa: E402
from cft_golden.formats import FP32, FP64, FP128, FP256  # noqa: E402

FMT = {"div32-hard": FP32, "div64-hard": FP64, "sqrt64-hard": FP64, "div128-hard": FP128, "div256-hard": FP256,
       "sqrt128-hard": FP128, "sqrt256-hard": FP256}
WIDE = ("div128-hard", "div256-hard", "sqrt128-hard", "sqrt256-hard")
RND = (sf.RND_RNE, sf.RND_RTZ, sf.RND_RDN, sf.RND_RUP, sf.RND_RMM)


# ----------------------------------------------------------------------------------------------------------
# an exact arbiter, from the definitions
# ----------------------------------------------------------------------------------------------------------

def _val(fmt, bits):
    """|x| as a Fraction, exactly, for a finite number."""
    p, bias = fmt.prec, fmt.bias
    e = (bits >> (p - 1)) & fmt.exp_mask
    f = bits & ((1 << (p - 1)) - 1)
    if e == 0:
        return Fraction(f, 1 << (bias - 1 + p - 1))
    sig = (1 << (p - 1)) | f
    t = e - bias - (p - 1)
    return Fraction(sig << t) if t >= 0 else Fraction(sig, 1 << -t)


def _floor_log2(q):
    n, d = q.numerator, q.denominator
    e = n.bit_length() - d.bit_length()
    if (n << max(-e, 0)) < (d << max(e, 0)):
        e -= 1
    return e


def _round_up(rem, j, sign, inexact, rnd):
    """Whether a result in [j, j + 1) grid units with fraction rem goes up, by the attribute's definition."""
    half = Fraction(1, 2)
    if rnd == sf.RND_RNE:
        return rem > half or (rem == half and j & 1 == 1)
    if rnd == sf.RND_RMM:
        return rem >= half
    if rnd == sf.RND_RTZ:
        return False
    if rnd == sf.RND_RDN:
        return bool(sign) and inexact
    return (not sign) and inexact                       # RND_RUP


def arbiter_div(fmt, a, b, rnd):
    """(bits, flags) of a / b for finite nonzero operands: the correctly rounded result and the flags of 754."""
    p, bias, w = fmt.prec, fmt.bias, fmt.width
    emin, emax = fmt.emin, fmt.emax
    sign = (a >> (w - 1)) ^ (b >> (w - 1))
    q = _val(fmt, a & ~(1 << (w - 1))) / _val(fmt, b & ~(1 << (w - 1)))
    e = _floor_log2(q)
    g = max(e, emin) - (p - 1)
    u = q / (Fraction(1 << g) if g >= 0 else Fraction(1, 1 << -g))
    j = u.numerator // u.denominator
    rem = u - j
    inexact = rem != 0
    big = j + (1 if _round_up(rem, j, sign, inexact, rnd) else 0)
    flags = sf.FLAG_INEXACT if inexact else 0
    if big == 1 << p:                                   # a carry into the next binade
        big, g = 1 << (p - 1), g + 1
    sbit = sign << (w - 1)
    # overflow: the rounded value reaches 2^(emax + 1)
    if big >= 1 << (p - 1) and g + p - 1 > emax:
        inf = ((2 * bias + 1) << (p - 1)) | sbit
        maxf = ((2 * bias) << (p - 1)) | ((1 << (p - 1)) - 1) | sbit
        if rnd in (sf.RND_RNE, sf.RND_RMM) or (rnd == sf.RND_RDN and sign) or (rnd == sf.RND_RUP and not sign):
            return inf, sf.FLAG_OVERFLOW | sf.FLAG_INEXACT
        return maxf, sf.FLAG_OVERFLOW | sf.FLAG_INEXACT
    # tininess after rounding: q rounded to p bits with an unbounded exponent is below the smallest normal
    if e < emin and inexact:
        u2 = q / (Fraction(1 << (e - p + 1)) if e - p + 1 >= 0 else Fraction(1, 1 << -(e - p + 1)))
        j2 = u2.numerator // u2.denominator
        rem2 = u2 - j2
        j2 += 1 if _round_up(rem2, j2, sign, rem2 != 0, rnd) else 0
        reaches_normal = j2 == 1 << p and e + 1 == emin
        if not reaches_normal:
            flags |= sf.FLAG_UNDERFLOW
    if big == 0:
        return sbit, flags
    if big < 1 << (p - 1):                              # subnormal: g is the subnormal grid
        return sbit | big, flags
    return sbit | ((g + p - 1 + bias) << (p - 1)) | (big - (1 << (p - 1))), flags


def arbiter_sqrt(fmt, x, rnd):
    """(bits, flags) of sqrt(x) for a positive normal x: integer arithmetic, no ties possible."""
    p, bias = fmt.prec, fmt.bias
    e = (x >> (p - 1)) & fmt.exp_mask
    sig = (1 << (p - 1)) | (x & ((1 << (p - 1)) - 1))
    t = e - bias - (p - 1)
    er = (sig.bit_length() - 1 + t) // 2
    c = er - (p - 1)
    y = sig << (t - 2 * c)                              # x / 4^c, an integer for these inputs
    assert t - 2 * c >= 0
    jj = isqrt(y)
    exact = jj * jj == y
    above = 4 * y > (2 * jj + 1) ** 2
    if rnd in (sf.RND_RNE, sf.RND_RMM):
        up = above
    elif rnd == sf.RND_RUP:
        up = not exact
    else:
        up = False
    big = jj + (1 if up else 0)
    if big == 1 << p:
        big, er = 1 << (p - 1), er + 1
    return ((er + bias) << (p - 1)) | (big - (1 << (p - 1))), (0 if exact else sf.FLAG_INEXACT)


def pick(mode, per_seg=24):
    """A deterministic sample of indices: a segment of at most per_seg indices whole; else per_seg indices at an odd
    stride (so that every variant of an index is reached) and its last two."""
    sp = H.SPACES[mode]
    out = []
    for name, start, count in sp.segs:
        if count <= per_seg:
            out += list(range(start, start + count))
            continue
        stride = (count // per_seg) | 1
        out += [start + i for i in range(0, count, stride)][:per_seg]
        out += [start + count - 1, start + count - 2]
    return out


# ----------------------------------------------------------------------------------------------------------
# 1. the generator
# ----------------------------------------------------------------------------------------------------------

def test_space_tables_and_totals():
    assert [H.SPACES[m].total for m in ("div32-hard", "div64-hard", "sqrt64-hard")] == [21235788, 289685696, 4456448]
    assert [H.SPACES[m].k for m in ("div32-hard", "div64-hard", "sqrt64-hard")] == [4, 4, 1]
    # the wide spaces (parcel HXa) are docs/studies/HX-wide-sweeps.md 3.4's table: the fp64 modes' segment sizes at
    # p = 113 and 237, F3a and F3b growing with p and the exponent range
    assert [H.SPACES[m].total for m in WIDE] == [289931696, 293864352, 4456448, 4456448]
    assert [(H.SPACES[m].k, H.SPACES[m].p, H.SPACES[m].w) for m in WIDE] == [(4, 113, 128), (4, 237, 256),
                                                                             (1, 113, 128), (1, 237, 256)]
    assert [c for n, s, c in H.SPACES["div256-hard"].segs][:2] == [948, 4194284]
    for sp in H.SPACES.values():
        pos = 0
        for name, start, count in sp.segs:
            assert start == pos and count > 0 and count % 4 == 0
            pos += count
        assert pos == sp.total
        assert [s[0] for s in sp.segs][:2] in (["F3a", "F3b"], ["S1", "S0"])     # the structural families come first


def test_mix64_equals_the_published_splitmix64_outputs():
    # splitmix64 with seed 0 outputs mix64(0), mix64(golden), mix64(2 golden), ... (the increment is added first)
    golden = 0x9E3779B97F4A7C15
    got = [H.mix64((n * golden) & H.M64) for n in range(3)]
    assert got == [0xE220A8397B1DCDAF, 0x6E789E6AA1B965F4, 0x06C45D188009454F]


@pytest.mark.parametrize("mode", ["div32-hard", "div64-hard", "sqrt64-hard"] + list(WIDE))
def test_verify_every_small_segment_and_a_sample_of_every_large_one(mode):
    sp = H.SPACES[mode]
    cases = 0
    for idx in H.sample_indices(sp, 120 if mode not in WIDE else 40, 7):
        cases += H.verify(mode, idx)
    assert cases > 0


def test_the_widened_draws_are_the_one_word_draws_where_one_word_held():
    # Parcel HXa drew F1's odd parts and F0K's keyed low bits from as many 64-bit words as p needs (splitmix64's stream
    # from the old seed). Where one word held - F1 to p = 132, F0K to p = 77 - the draw is the old one, and F3a's
    # alternating pattern, carried past 64 bits, is the old mask below 65: so div32-hard, div64-hard and sqrt64-hard are
    # unchanged operand for operand (hw/test_divsqrt_hard.py's `unchanged` group holds the C tool's dumps to the same).
    seeds = [0, 1, H.SALT_F1, H.SALT_F0K, (1 << 63) + 5, H.M64] + [H.mix64(i) for i in range(300)]
    for seed in seeds:
        word = H.mix64(seed)
        for nbits in range(0, 65):
            assert H.draw_top(seed, nbits) == word >> (64 - nbits)
            assert H.draw_low(seed, nbits) == word & ((1 << nbits) - 1)
    for length in range(1, 65):
        assert H.even_bits(length) == 0x5555555555555555 & ((1 << length) - 1)
    # past one word the stream's next words follow, the first word on top (draw_top) or at the bottom (draw_low)
    s = 12345
    w0, w1 = H.mix64(s), H.mix64((s + H.GOLDEN) & H.M64)
    assert H.draw_top(s, 100) == ((w0 << 64) | w1) >> 28
    assert H.draw_low(s, 100) == (w0 | (w1 << 64)) & ((1 << 100) - 1)


def test_the_wide_draws_reach_every_bit():
    # F1 at p = 237 builds (one word failed there, on a negative shift: the study's 3.4) and its odd parts take their
    # whole width, h = 118 bits; F0K's keyed divisors at p = 113 and 237 carry keyed bits above bit 63, where one word
    # left bits 64 to p - 14 zero in every divisor
    sp = H.SPACES["div256-hard"]
    f1 = [s for n, s, c in sp.segs if n == "F1"][0]
    lens = set()
    for i in range(f1, f1 + 800, 4):
        a, b = H.base_case(sp, i)
        _sb, sig_b, _tb = H.decode(sp, b)
        lens.add((sig_b >> ((sig_b & -sig_b).bit_length() - 1)).bit_length())      # the divisor's odd part
    assert max(lens) == (237 - 1) // 2
    for mode in ("div128-hard", "div256-hard"):
        sp = H.SPACES[mode]
        high = 0
        for jj in range(256):
            high |= H.f0_divisor(sp, "K", jj) >> 64
        want = (1 << (sp.p - 1 - 64)) - 1                # every bit from 64 to p - 2 (the cells' too) is reached
        assert high & ((1 << (sp.p - 13 - 64)) - 1) == (1 << (sp.p - 13 - 64)) - 1, mode
        assert high >> (sp.p - 1 - 64) == 1 and high & want == want, mode


def test_an_unsupported_p_is_refused_by_name():
    # the family's construction is not defined there: refused by name, never left to fail on a shift
    with pytest.raises(ValueError, match=r"family F1 is not defined at p = 4, bias = 127 \(it needs p >= 5"):
        H.Space("tiny", 4, 12, 127, 4, [("F1", 4)])
    with pytest.raises(ValueError, match=r"family F0K is not defined at p = 13"):
        H.Space("tiny", 13, 21, 127, 4, [("F0K", 4)])
    with pytest.raises(ValueError, match=r"family S1 is not defined at p = 53, bias = 127 \(it needs p >= 2 and "
                                         r"bias >= 510"):
        H.Space("narrow-range", 53, 61, 127, 1, [("S1", 4)])
    assert H.Space("ok", 5, 13, 127, 4, [("F1", 4)]).total == 4 and H.Space("ok", 14, 22, 127, 4, [("F0K", 4)]).total == 4


def test_the_plain_widening_keeps_every_value():
    # the fp32 slice's widening (plain_lines, the reference the tool's slice dump is held to): the same value at fp64,
    # fp128 and fp256 for every class - zeros, subnormals, normals, infinities - and a NaN's quiet bit and payload at the
    # top of the wider fraction; at fp64 it is the host FPU's own widening (CPython's float of an fp32) for every
    # non-NaN value
    fmts = {32: FP32, 64: FP64, 128: FP128, 256: FP256}
    specials = [0, 1, 2, 0x7FFFFF, 0x800000, 0x3F800000, 0x3F800001, 0x7F7FFFFF, 0x7F800000, 0x7F800001,
                0x7FBFFFFF, 0x7FC00000, 0x7FFFFFFF]
    pool = specials + [s | 0x80000000 for s in specials] + [H.mix64(i) & 0xFFFFFFFF for i in range(600)]
    for bits in pool:
        e = (bits >> 23) & 0xFF
        f = bits & 0x7FFFFF
        for w in (64, 128, 256):
            fw = fmts[w]
            wb = H.widen_bits(bits, 32, w)
            assert wb >> (w - 1) == bits >> 31
            we = (wb >> fw.man_w) & fw.exp_mask
            if e == 0xFF:
                assert we == fw.exp_mask and (wb & ((1 << fw.man_w) - 1)) == f << (fw.man_w - 23), hex(bits)
            else:
                assert _val(fw, wb & ~(1 << (w - 1))) == _val(FP32, bits & 0x7FFFFFFF), (hex(bits), w)
                assert e == 0 and f == 0 or we != 0, (hex(bits), w)       # a nonzero fp32 value is a wide normal
        if e != 0xFF:
            want64 = struct.unpack("<Q", struct.pack("<d", struct.unpack("<f", struct.pack("<I", bits))[0]))[0]
            assert H.widen_bits(bits, 32, 64) == want64, hex(bits)
    # the windows: x = 1.H L with H's top bit at the first fraction place, L the index
    for w in (128, 256):
        hb = fmts[w].man_w - 32
        assert H.window_x(w, "ones", 0) >> 32 == (fmts[w].bias << hb) | ((1 << hb) - 1)
        assert H.window_x(w, "zeros", 7) == (fmts[w].bias << fmts[w].man_w) | 7
        alt = H.window_x(w, "alt", 0) >> 32
        assert (alt >> (hb - 1)) & 1 == 0 and (alt >> (hb - 2)) & 1 == 1            # 1.0101...
        assert H.window_x(w, "key", 5) & ((1 << 32) - 1) == 5


def test_f0_skip_rate_is_the_number_theory():
    # a divisor has no |N| = 1 dividend, for one target and sign, with probability 1 - ln 2 = 30.7% over both quotient
    # binades (the prototype's single binade, mx >= my, skips 61.4%); near 1.0 almost none skip, near 2.0 half do
    sp = H.SPACES["div64-hard"]
    start = [s for n, s, c in sp.segs if n == "F0K"][0]
    n = 6000
    skips = sum(1 for i in range(start, start + n) if H.base_case(sp, i) is None)
    assert abs(skips / n - (1 - math.log(2))) < 0.03
    a = [s for n_, s, c in sp.segs if n_ == "F0A"][0]
    d = [s for n_, s, c in sp.segs if n_ == "F0D"][0]
    assert sum(1 for i in range(a, a + 2000) if H.base_case(sp, i) is None) < 40
    assert 0.4 < sum(1 for i in range(d, d + 2000) if H.base_case(sp, i) is None) / 2000 < 0.6
    # the keyed stream is stratified: the top 12 fraction bits of the divisor take every value once in any 4,096
    # consecutive divisors (the cell order is scrambled, so a short slice is spread, but a full period is whole)
    for first in (0, 123456, (1 << 26) - 4096):
        cells = {(H.f0_divisor(sp, "K", jj) >> 40) & 4095 for jj in range(first, first + 4096)}
        assert cells == set(range(4096)), first
    assert len({(H.f0_divisor(sp, "K", jj) >> 40) & 4095 for jj in range(64)}) > 40   # and 64 divisors already spread


def _tiny_space(p):
    """A space at a small precision with an 8-bit exponent: the builders and the classification are written for any p."""
    return H.Space("tiny%d" % p, p, p + 8, 127, 4, [("F0A", 4 << (p - 3)), ("F0D", 4 << (p - 3))])


@pytest.mark.parametrize("p", [9, 10])
def test_f0_finds_every_closest_approach_and_only_those_at_small_precision(p):
    # Exhaustive at p = 9 and 10: for every odd divisor (the A and D streams together are all of them) and every
    # dividend, the classification (Fractions) lists the dividends at |N| = 1 from a midpoint and from a representable
    # number, above and below; the builder returns exactly that dividend when it exists - there is at most one per target
    # and sign - and a skip exactly when there is none. This is the construction's soundness AND completeness, and the
    # reason a skip means "no such dividend", checked over the whole space at a size the brute force reaches.
    sp = _tiny_space(p)
    n_div = built = 0
    seen = set()
    for stream in ("A", "D"):
        for jj in range(1 << (p - 3)):
            my = H.f0_divisor(sp, stream, jj)
            assert my % 2 == 1 and sp.P1 < my < sp.P and my not in seen, (stream, jj, my)
            seen.add(my)
            b = H._enc(sp, sp.bias, my)
            sols = {(t, s): [] for t in (0, 1) for s in (0, 1)}
            for mx in range(sp.P1, sp.P):
                cl = H.div_class(sp, H._enc(sp, sp.bias, mx), b)
                if cl["d"] != my:
                    continue
                for t in (0, 1):
                    nn = cl["n_mid"] if t == 0 else cl["n_rep"]
                    if abs(nn) == 1:
                        sols[(t, 0 if nn == 1 else 1)].append(mx)
            n_div += 1
            for v in range(4):
                want = sols[(v >> 1, v & 1)]
                got = H.build_f0(sp, stream, jj, v)
                assert len(want) <= 1
                if got is None:
                    assert want == [], (stream, jj, v)
                else:
                    assert want == [(got[0] & (sp.P1 - 1)) | sp.P1], (stream, jj, v)
                    built += 1
    assert n_div == len(seen) == 1 << (p - 2)           # every odd divisor of the binade, each once
    assert 0.55 < built / (4 * n_div) < 0.85            # about 1 - (1 - ln 2) = 69% of constructions exist


@pytest.mark.parametrize("p", [10, 12, 14])
def test_s0_lists_every_input_at_a_given_distance_at_small_precision(p):
    # The sqrt construction's two argued claims, by exhaustion over every input of [1, 4) at p = 10, 12, 14: (1) the
    # inputs whose nearest midpoint square is at distance |D| form the set the builder lists for rho = -D (all four
    # roots of u^2 = rho mod 2^s), for every rho = 8m + 1 with |rho| below the grid's half-width; (2) the least distance
    # is 1, reached by exactly two inputs (sqrt(1 + ulp) and the predecessor of 4), and the distances that follow are the
    # study's 7, 9, 15, 17, 23 - all of them congruent to 1 mod 8 up to sign.
    sp = H.Space("tiny%d" % p, p, p + 8, 127, 1, [("S0", 4 << 10)])
    by_d = {}
    for par in (0, 1):
        for k in range(sp.P1, sp.P):
            x = H._enc(sp, sp.bias + par, k)
            by_d.setdefault(H.sqrt_class(sp, x)["D"], set()).add(x)
    assert all((-d) % 8 == 1 for d in by_d)
    assert sorted({abs(d) for d in by_d})[:6] == [1, 7, 9, 15, 17, 23]
    assert by_d[-1] == {H._enc(sp, sp.bias, sp.P1 + 1), H._enc(sp, sp.bias + 1, sp.P - 1)}
    for n in range(64):                                 # rho = 1, -7, 9, ..., |rho| <= 249 < 2^(p-1)
        m = n // 2 if n % 2 == 0 else -((n + 1) // 2)
        rho = 8 * m + 1
        built = {c[0] for v in range(4) for c in [H.build_s0(sp, n, v)] if c is not None}
        assert built == by_d.get(-rho, set()), (p, n, rho)


def test_verify_refuses_wrong_builders_by_name(monkeypatch):
    sp = H.SPACES["div32-hard"]
    f0 = [s for n, s, c in sp.segs if n == "F0A"][0]
    good = H.build_f0

    def off_by_two(sp_, stream, j, v):                  # the dividend two too high: |N| no longer 1
        c = good(sp_, stream, j, v)
        return None if c is None else (c[0] + 2, c[1])

    monkeypatch.setattr(H, "build_f0", off_by_two)
    with pytest.raises(AssertionError, match="F0 closest approach"):
        for i in range(f0, f0 + 40):
            H.verify("div32-hard", i)
    monkeypatch.setattr(H, "build_f0", good)
    for i in range(f0, f0 + 40):                        # the same indices pass with the real builder
        H.verify("div32-hard", i)
    good_s0 = H.build_s0
    s0 = [s for n, s, c in H.SPACES["sqrt64-hard"].segs if n == "S0"][0]

    def one_ulp_up(sp_, n, v):
        c = good_s0(sp_, n, v)
        return None if c is None else (c[0] + 1, None)

    monkeypatch.setattr(H, "build_s0", one_ulp_up)
    with pytest.raises(AssertionError, match="S0 odd-square input"):
        for i in range(s0, s0 + 40):
            H.verify("sqrt64-hard", i)


def test_dump_lines_have_one_line_a_slot():
    for mode in H.SPACES:
        lines = H.dump_lines(mode, 100, 110)
        assert len(lines) == 10 * H.SPACES[mode].k
        assert all(ln.split()[0].isdigit() for ln in lines)


# ----------------------------------------------------------------------------------------------------------
# 2. the golden model against the exact arbiter
# ----------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("mode", ["div32-hard", "div64-hard"])
def test_golden_division_equals_the_exact_arbiter_on_every_family(mode):
    fmt = FMT[mode]
    seen_inexact = seen_exact = seen_uf = seen_of = 0
    n = 0
    for idx in pick(mode, 400 if mode == "div32-hard" else 80):
        for slot in H.gen(mode, idx):
            if slot is None:
                continue
            a, b = slot
            for rnd in RND:
                want = arbiter_div(fmt, a, b, rnd)
                got = sf.div(fmt, a, b, rnd)
                assert got == want, (mode, idx, hex(a), hex(b), rnd, got, want)
                n += 1
            if want[1] & sf.FLAG_INEXACT:
                seen_inexact += 1
            else:
                seen_exact += 1
            seen_uf += bool(want[1] & sf.FLAG_UNDERFLOW)
            seen_of += bool(want[1] & sf.FLAG_OVERFLOW)
    # the families reach what they say they reach: exact quotients, inexact ones, the underflow and overflow strips
    assert n > 1000 and seen_exact > 0 and seen_inexact > 0 and seen_uf > 0 and seen_of > 0


@pytest.mark.parametrize("mode", ["div32-hard", "div64-hard"])
def test_strip_ties_separate_rne_from_rmm(mode):
    # F3a's exact quotients are ties of the subnormal grid: RNE and RMM differ exactly where the kept bit is even (RNE
    # rounds down, RMM up), which three of the four patterns arrange; they agree where it is odd - the only place
    # division has a tie (no midpoint is reachable among normal results)
    fmt = FMT[mode]
    sp = H.SPACES[mode]
    diff = tot = 0
    for idx in range(sp.segs[0][2]):
        a, b = H.gen(mode, idx)[0]
        tot += 1
        diff += sf.div(fmt, a, b, sf.RND_RNE)[0] != sf.div(fmt, a, b, sf.RND_RMM)[0]
    assert 0.5 * tot < diff < 0.95 * tot


def test_golden_sqrt_equals_the_exact_arbiter_on_every_family():
    fmt = FP64
    n = 0
    for idx in pick("sqrt64-hard", 200):
        slot = H.gen("sqrt64-hard", idx)[0]
        if slot is None:
            continue
        for rnd in RND:
            want = arbiter_sqrt(fmt, slot[0], rnd)
            got = sf.sqrt(fmt, slot[0], rnd)
            assert got == want, (idx, hex(slot[0]), rnd, got, want)
            n += 1
    assert n > 500


@pytest.mark.parametrize("mode", ["div128-hard", "div256-hard"])
def test_golden_wide_division_equals_the_exact_arbiter_on_every_family(mode):
    # the wide spaces through the golden model at fp128 and fp256 (the arbiter of any disagreement on the card): every
    # family, every slot, every attribute, against the arbiter written from the definitions
    fmt = FMT[mode]
    n = seen_uf = seen_of = seen_exact = 0
    for idx in pick(mode, 12):
        for slot in H.gen(mode, idx):
            if slot is None:
                continue
            for rnd in RND:
                want = arbiter_div(fmt, slot[0], slot[1], rnd)
                got = sf.div(fmt, slot[0], slot[1], rnd)
                assert got == want, (mode, idx, hex(slot[0]), hex(slot[1]), rnd, got, want)
                n += 1
            seen_uf += bool(want[1] & sf.FLAG_UNDERFLOW)
            seen_of += bool(want[1] & sf.FLAG_OVERFLOW)
            seen_exact += not want[1] & sf.FLAG_INEXACT
    assert n > 1000 and seen_uf > 0 and seen_of > 0 and seen_exact > 0


@pytest.mark.parametrize("mode", ["sqrt128-hard", "sqrt256-hard"])
def test_golden_wide_sqrt_equals_the_exact_arbiter_on_every_family(mode):
    fmt = FMT[mode]
    n = 0
    for idx in pick(mode, 60):
        slot = H.gen(mode, idx)[0]
        if slot is None:
            continue
        for rnd in RND:
            want = arbiter_sqrt(fmt, slot[0], rnd)
            got = sf.sqrt(fmt, slot[0], rnd)
            assert got == want, (mode, idx, hex(slot[0]), rnd, got, want)
            n += 1
    assert n > 200


# ----------------------------------------------------------------------------------------------------------
# 3. the host FPU, through CPython
# ----------------------------------------------------------------------------------------------------------

def _f(bits):
    return struct.unpack("<d", struct.pack("<Q", bits))[0]


def _bits(x):
    return struct.unpack("<Q", struct.pack("<d", x))[0]


def test_golden_rne_equals_the_host_fpu_through_cpython():
    n = 0
    for idx in pick("div64-hard", 60):
        for slot in H.gen("div64-hard", idx):
            if slot is None:
                continue
            a, b = slot
            want = _bits(_f(a) / _f(b))
            assert sf.div(FP64, a, b, sf.RND_RNE)[0] == want, (idx, hex(a), hex(b))
            n += 1
    for idx in pick("sqrt64-hard", 120):
        slot = H.gen("sqrt64-hard", idx)[0]
        if slot is None:
            continue
        assert sf.sqrt(FP64, slot[0], sf.RND_RNE)[0] == _bits(math.sqrt(_f(slot[0]))), (idx, hex(slot[0]))
        n += 1
    assert n > 600
