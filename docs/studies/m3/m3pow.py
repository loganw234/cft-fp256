# M3 model: the pow family's ONE core and its five front ends (scratch; the
# study's section 2).
#
#   result = sign 2^t,  t = Y log2|X|
#
#   X  x for pow, powr, pown and rootn; 1 + x for compound, the exact double
#      word TwoSum(1, x), its low word entering the logarithm as M1's log1p's
#      does (r_l = u_l 2^-k c / (1 + r))
#   Y  y (an input) for pow and powr; n for pown and compound, one word at
#      fp128 and fp256 and two at fp64 (n_h + n_l = n exactly); 1/n in two
#      words for rootn
#
# The logarithm is M1's log2 at fp64 to fp256 (mathlib's _log_reduce, its
# table, its polynomial, F (1/ln 2) in two words, k + F) planned at a larger
# guard GL; t = Y L is TwoProd(Y_h, L_h) and two FMAs; 2^t is M1's exp2 with
# a double-word argument: n = round(8 t_h), r' = (t_h - n/8) + t_l by
# Fast2Sum, r = r' ln 2 in two words, the same table, polynomial, scale,
# reconstruction, fixed grid and in-lane test, and V signed before the final
# rounding so that every attribute rounds the signed value.
#
# Built on the tree's mathlib.Build and M1's helpers, imported and never
# edited. Every name, constant and order here is PROPOSED.

import math
import types
from fractions import Fraction

from m3core import ml, sf, routines, RNE, RTZ, RDN, RUP, RMM, AN

N = ml.N
GUARD = dict(ml.GUARD)

# the plants (section 8): name -> what it breaks
PLANTS = {
    "exact_unmarked": "the RNE/RMM 'may be exact' test removed: an exact "
                      "representable result is left to the enclosure",
    "exact_rule_off": "the in-lane power-of-two rule removed: 2^n and "
                      "x = 2^E lanes are left to the test",
    "exact_rule_no_tl": "the power-of-two rule without t_l = 0, as rootn's: "
                        "pow wrongly calls 2^(k + f) exact",
    "midpoint_unmarked": "the fixed grid's midpoint test dropped",
    "pow_zero_nan": "pow(qNaN, +-0) answered NaN, not 1",
    "pow_one_nan": "pow(1, qNaN) answered NaN, not 1",
    "sign_even": "the parity of y read from the wrong bit: an even y "
                 "taken as odd",
    "integrality_wide": "the first design: MAGIC's band for y's "
                        "integrality taken up to 2^(p-1), not 2^(p-2)",
    "sign_odd_lost": "an odd y's sign dropped (the result's sign forced +)",
    "powr_neg_ok": "powr's x < 0 row removed (negative x goes to the core)",
    "powr_zero_zero": "powr(0, 0) answered 1, not invalid",
    "rootn_m0_neg": "rootn(-0, 2) answered -0 (squareRoot's row)",
    "compound_onep_rounded": "1 + x formed in the format (rounded) before "
                             "the logarithm, its low word dropped",
    "near_one_gate_off": "the inseparable-from-1 gate removed: lanes with "
                         "|t| below 2^-(p+3) left to the test",
    "side_rule_off": "the first design: beside 1 the mark is cleared and "
                     "V's own rounding answers, t_h having underflowed for "
                     "a subnormal y",
    "screen_low": "the overflow screen at emax + 1, not emax + 2",
    "mark_silenced": "the mark never set",
    "bound_loose": "the in-lane bound 2^40 times too small (M1's plant): "
                   "a midpoint is decided by V's side",
    "zero_sign_lost": "the first design: a negative result rounding to "
                      "zero on the subnormal grid answered +0",
    "log_short": "the logarithm planned at G, not GL",
    "bound_tight": "Bv's |t| term dropped at fp64",
}


def t_reach(fmt):
    """T_f: the largest |t| the main path sees. The screens answer
    t_h >= emax + 2 and t_h <= emin - p - 2, so the main path has
    |t| < max(emax + 2, p - emin + 2)."""
    return max(fmt.emax + 2, fmt.prec - fmt.emin + 2)


def extra_bits(fmt):
    """The bits the logarithm needs past p + G: log2 T_f, rounded up."""
    return math.ceil(math.log2(t_reach(fmt)))


def plan(fmt, G=None):
    """(G, GL, GE, B1): the in-lane guard; the logarithm's planned guard,
    G + extra + 2 where the double word holds it, else the most M1's
    plan_log accepts (its floor 12 u^2); the exponential's, G + 2; and B1,
    the bound's coefficient of |t_h| (0 where GL reached its target)."""
    G = GUARD[fmt.name] if G is None else G
    want = G + extra_bits(fmt) + 2
    GL = want
    while GL > G:
        try:
            ml.plan_log(fmt, GL)
            break
        except ValueError:
            GL -= 1
    GE = G + 2
    # B1 = 2^-(2p-6): the double word's roundings in the logarithm's sum,
    # relative to L where k = -1 and log2 m' near 0.91 cancel (x just below
    # 1, 3.4 bits), and the product: the budget (3.2). The first value,
    # 2^-(2p-3), left 0.48 bits in the region negint; the second, 2^-(2p-4),
    # was past 1 Bv for pown(x, 1000) (the study's 3.6, item 6)
    B1 = Fraction(0) if GL == want else Fraction(1, 2 ** (2 * fmt.prec - 6))
    return G, GL, GE, B1


def int_words(fmt, n):
    """n as format words whose sum is n exactly: one word where n fits p
    bits, else two (fp64 holds every int64 in two; at fp32 two hold every
    |n| < 2^48, and past 2^31 every lane but |x| = 1 is screened, so the
    second word is rounded there and n's parity is the build's)."""
    hi = ml._enc(fmt, Fraction(n))
    rest = Fraction(n) - ml._dec(fmt, hi)
    if rest == 0:
        return hi, None
    return hi, ml._enc(fmt, rest)


def recip_words(fmt, n):
    """1/n in two words, RN and RN of the rest."""
    return tuple(ml._words(fmt, Fraction(1, n), 2))


class PBuild(ml.Build):
    """mathlib.Build that also records a LABEL per instruction (the
    study's cost by part), beside the phase the scheduler ranks by."""

    def __init__(self, fmt, rnd, name):
        super().__init__(fmt, rnd, name)
        self.label = "classify"
        self.label_of = []

    def ins(self, op, srcs, rnd=None):
        n0 = len(self.body)
        ref = super().ins(op, srcs, rnd)
        if len(self.body) > n0:
            self.label_of.append(self.label)
        return ref


def _at(b, label, phase):
    b.label, b.phase = label, phase


_CACHE = {}


def _consts(fmt, fn, GL, KL, DL, GE, KE, DE, plant):
    key = (fmt.name, fn, GL, KL, DL, GE, KE, DE, plant)
    if key not in _CACHE:
        logfn = "log1p" if fn == "compound" else "log2"
        cl = ml._log_constants(logfn, fmt, GL, KL, DL, 0, None)
        ce = ml._dw_constants("exp2", fmt, GE, KE, DE, 0, None)
        _CACHE[key] = (cl, ce)
    return _CACHE[key]


def _classify(b, k_, name):
    """NaN, signalling NaN, infinity, zero, the sign bit, |v|: for input
    `name` (x is mathlib's _classify_common; y the same code)."""
    fmt = b.fmt
    ib, ZERO, INF = k_["ib"], k_["ZERO"], k_["INF"]
    v = ("in", name)
    c = types.SimpleNamespace(x=v)
    c.ax = b.iand(v, k_["ABSM"])
    c.isnan = b.icmplt(INF, c.ax)
    c.issnan = b.sel(ZERO, c.isnan, b.iand(v, k_["QBIT"]))
    c.isinf = b.cmpeq(c.ax, INF)
    c.iszero = b.icmplt(c.ax, k_["INT1"])
    c.neg = b.ishr(v, ib(fmt.width - 1, "SIGN_SHIFT"))
    return c


def _integrality(b, k_, yc, plant):
    """(isint, odd) of y, in-lane: below 2^(p-2) by MAGIC (y + MAGIC rounds
    y to an integer, exactly when y is one, and its encoding's low bit is the
    integer's parity, MAGIC's value 3 2^(p-2) being even); from 2^(p-2) to
    2^(p-1) the encoding's bit 0 is the halves and bit 1 the units; from
    2^(p-1) to 2^p every y is an integer and bit 0 is its parity; from 2^p
    up every y is an even integer, up to 2^262143 at fp256."""
    fmt = b.fmt
    p = fmt.prec
    ib, ZERO, ONE, INT1 = k_["ib"], k_["ZERO"], k_["ONE"], k_["INT1"]
    MAGIC = b.word(ml._enc_exact(fmt, Fraction(3, 2) * 2 ** (p - 1)), "MAGIC")
    if plant == "integrality_wide":
        # the first design: MAGIC's band taken up to 2^(p-1), where y + MAGIC
        # passes 2^p and its rounding loses the units bit (the study's 3.6)
        small = b.icmplt(yc.ax, b.word(ml._pow2(fmt, p - 1), "P2PM1"))
        yi = b.add(yc.ax, MAGIC)
        isint_s = b.cmpeq(b.sub(yi, MAGIC), yc.ax)
        par_s = b.iand(yi, INT1)
        below_p = b.icmplt(yc.ax, b.word(ml._pow2(fmt, p), "P2P_Y"))
        odd_b = b.sel(b.iand(yc.ax, INT1), ZERO, below_p)
        return (b.sel(isint_s, ONE, small),
                b.sel(b.sel(par_s, ZERO, isint_s), odd_b, small))
    # |y| < 2^(p-2): y + MAGIC stays below 2^p, so its ulp is 1
    small = b.icmplt(yc.ax, b.word(ml._pow2(fmt, p - 2), "P2PM2"))
    yi = b.add(yc.ax, MAGIC)
    isint_s = b.cmpeq(b.sub(yi, MAGIC), yc.ax)
    par_s = b.iand(yi, INT1)
    if plant == "sign_even":
        par_s = b.iand(yi, ib(2, "I2"))
    # 2^(p-2) <= |y| < 2^(p-1): the ulp is 1/2, the encoding's bit 0 the
    # halves (an integer iff it is clear) and bit 1 the units (the parity)
    mid = b.icmplt(yc.ax, b.word(ml._pow2(fmt, p - 1), "P2PM1"))
    b0 = b.iand(yc.ax, INT1)
    isint_m = b.sel(ZERO, ONE, b0)
    odd_m = b.sel(ZERO, b.iand(yc.ax, ib(2, "I2")), b0)
    # 2^(p-1) <= |y| < 2^p: every y an integer, bit 0 its parity; past 2^p
    # every y an even integer
    below_p = b.icmplt(yc.ax, b.word(ml._pow2(fmt, p), "P2P_Y"))
    odd_b = b.sel(b0, ZERO, below_p)
    isint = b.sel(isint_s, b.sel(isint_m, ONE, mid), small)
    odd = b.sel(b.sel(par_s, ZERO, isint_s), b.sel(odd_m, odd_b, mid), small)
    return isint, odd


def build(fn, fmt, rnd, n=None, plant=None, G=None, GL=None, shift=0):
    """The instrumented Build of fn at fmt under rnd (n the integer operand
    of pown, rootn and compound: a constant of the build)."""
    if plant is not None and plant not in PLANTS:
        raise ValueError(f"unknown plant {plant!r}")
    p, mw = fmt.prec, fmt.man_w
    G, GL0, GE, B1 = plan(fmt, G)
    if GL is None:
        GL = GL0
    if plant == "log_short":
        GL = G
    if plant == "bound_tight":
        B1 = Fraction(0)
    KL, DL = ml.plan_log(fmt, GL)
    KE, DE = ml.plan_exp(fmt, GE)
    cl_, ce = _consts(fmt, fn, GL, KL, DL, GE, KE, DE, plant)
    b = PBuild(fmt, rnd, f"{fn}-{fmt.name}-{AN[rnd]}")
    b.inputs = ("a", "b") if fn in ("pow", "powr") else ("a",)
    b.meta.update(fn=fn, G=G, GL=GL, GE=GE, KL=KL, DL=DL, KE=KE, DE=DE,
                  B1=B1, n=n, plant=plant, family="double word", N=N,
                  shift=shift)
    k_ = ml._words_common(b)
    ib, ZERO, ONE, INT1 = k_["ib"], k_["ZERO"], k_["ONE"], k_["INT1"]
    INF, QNAN = k_["INF"], k_["QNAN"]
    INX, INXUNF, OVFINX = k_["INX"], k_["INXUNF"], k_["OVFINX"]
    INVALID, MARKW = k_["INVALID"], k_["MARKW"]
    DIVZ = ib(sf.FLAG_DIVZERO, "FL_DIVZERO")
    SIGN = ib(fmt.sign_mask, "SIGN_BIT")
    MANW = ib(mw, "MANTISSA_WIDTH")

    def W(name, bits):
        return b.word(bits, name)

    # ---- classify ----------------------------------------------------------
    _at(b, "classify", "classify")
    cl = ml._classify_common(b, k_)          # x: ax, NaN, sNaN, inf, 0, sign
    x = cl.x
    yc = None
    if fn in ("pow", "powr"):
        yc = _classify(b, k_, "b")

    # ---- the integer operand, and the sign ---------------------------------
    _at(b, "front", "front")
    isint = odd = None
    negres = None                            # the result is negative
    if fn == "pow":
        isint, odd = _integrality(b, k_, yc, plant)
        negres = b.sel(odd, ZERO, cl.neg)
        if plant == "sign_odd_lost":
            negres = None
    elif fn in ("pown", "rootn") and n % 2:
        negres = cl.neg
    sgnw = None
    if negres is not None:
        sgnw = (b.iand(x, SIGN) if negres is cl.neg
                else b.sel(SIGN, ZERO, negres))
    if fn in ("pow", "powr"):
        Yh, Yl = ("in", "b"), None
    elif fn in ("pown", "compound"):
        hi, lo = int_words(fmt, n)
        Yh = W("NH", hi)
        Yl = None if lo is None else W("NL", lo)
    else:
        hi, lo = recip_words(fmt, n)
        Yh = W("RNH", hi)
        Yl = None if lo == 0 else W("RNL", lo)

    # ---- the logarithm: L = log2 |X| as a double word (M1's log2) ----------
    _at(b, "log-reduce", "reduce")
    if fn == "compound":
        red = ml._log_reduce(b, "log1p", cl_, k_, cl, None)
        if plant == "compound_onep_rounded":
            red.ul = ZERO
    else:
        clx = types.SimpleNamespace(x=cl.ax, ax=cl.ax)
        red = ml._log_reduce(b, "log2", cl_, k_, clx, None)
    r, kf = red.r, red.kf
    _at(b, "log-table", "table")
    Lh, Ll = ml._table(b, cl_, red.tc, k_,
                       (lambda j: f"LH{j}", lambda j: f"LL{j}"))
    corr = None
    if fn == "compound":
        _at(b, "log-lowword", "lowword")
        p2mk = b.ishl(b.isub(ib(fmt.bias + cl_["MAGIC"], "K_BIAS_MAGIC"),
                             red.kb), MANW)
        p2mk = b.sel(ZERO, p2mk, b.icmplt(
            ib(cl_["MAGIC"] + p + GL + 2, "K_CLAMP"), red.kb))
        rl = b.mul(b.mul(red.ul, p2mk), red.cc)
        nr0 = b.neg(r)
        yv = b.sub(ONE, r)
        for _ in range(3 if p < 100 else 4):
            e = b.fma(nr0, yv, b.sub(ONE, yv))
            yv = b.fma(yv, e, yv)
        corr = b.mul(rl, yv)
        sm = b.icmplt(cl.ax, W("SMALL", cl_["SMALL"]))
        r = b.sel(x, r, sm)
        kf = b.sel(ZERO, kf, sm)
        Lh, Ll = b.sel(ZERO, Lh, sm), b.sel(ZERO, Ll, sm)
        corr = b.sel(ZERO, corr, sm)
    _at(b, "log-poly", "tail")
    nr = b.neg(r)
    yv = W(f"LY{DL}", cl_[f"Y{DL}"])
    for i in range(DL - 1, KL - 1, -1):
        yv = b.fma(yv, r, W(f"LY{i}", cl_[f"Y{i}"]))
    b.phase = "head"
    yh, yl = yv, None
    for i in range(KL - 1, -1, -1):
        CH, CLw = W(f"LCH{i}", cl_[f"CH{i}"]), W(f"LCL{i}", cl_[f"CL{i}"])
        pp = b.mul(yh, r)
        ne = b.fma(yh, nr, pp)
        nl = b.fma(yl, nr, ne) if yl is not None else ne
        s, e = b.fast_two_sum(CH, pp)
        tt = b.sub(e, nl)
        yl = b.add(tt, CLw) if cl_[f"CL{i}"] else tt
        yh = s
    b.phase = "Z"
    lph = b.mul(yh, r)
    nlpe = b.fma(yh, nr, lph)
    nlpl = b.fma(yl, nr, nlpe)
    if corr is not None:
        nlpl = b.sub(nlpl, corr)
    _at(b, "log-sum", "recon")
    il2h, il2l = ml._words(fmt, ml._inv_ln2(), 2)
    F, fe = b.fast_two_sum(Lh, lph)
    Fl = b.sub(b.add(fe, Ll), nlpl)
    gh = b.mul(F, W("IL2H", il2h))
    nge = b.fma(F, W("NIL2H", sf.negate(fmt, il2h)), gh)
    ngl = b.fma(F, W("NIL2L", sf.negate(fmt, il2l)), nge)
    ngl = b.fma(Fl, W("NIL2H", sf.negate(fmt, il2h)), ngl)
    S, e = b.fast_two_sum(kf, gh)
    lo = b.sub(e, ngl)
    Lh2, Ll2 = b.fast_two_sum(S, lo)
    b.probes.update(r=r, Lh=Lh2, Ll=Ll2)

    # ---- t = Y L as a double word ------------------------------------------
    _at(b, "product", "head2")
    NLh = b.neg(Lh2)
    th0 = b.mul(Yh, Lh2)
    ne = b.fma(Yh, NLh, th0)                  # th0 - Y_h L_h: exact
    ne = b.fma(Yh, b.neg(Ll2), ne)
    if Yl is not None:
        ne = b.fma(Yl, NLh, ne)
    th, tl = b.fast_two_sum(th0, b.neg(ne))   # |th0| >= |tl| or th0 = 0
    b.probes.update(th0=th0, th=th, tl=tl)
    # the screens, on the rounded product (an overflowed product is +-inf)
    hi_t = fmt.emax + (1 if plant == "screen_low" else 2)
    ovs = b.cmple(W("TOVF", ml._enc_exact(fmt, hi_t)), th0)
    uns = b.cmple(th0, W("TUNF", ml._enc_exact(fmt, fmt.emin - p - 2)))

    # ---- 2^t: M1's exp2 with a double-word argument -------------------------
    _at(b, "exp-reduce", "reduce")
    MAGIC = W("MAGIC", ce["MAGIC"])
    tq = b.fma(th, W("EIGHT", ce["EIGHT"]), MAGIC)
    nf = b.sub(tq, MAGIC)
    rp = b.fma(nf, W("NINV8", ce["NINV8"]), th)          # th - n/8: exact
    rh1, rl1 = b.fast_two_sum(rp, tl)
    LN2H, NLN2H = W("LN2H", ce["LN2H"]), W("NLN2H", ce["NLN2H"])
    rh = b.mul(rh1, LN2H)
    nre = b.fma(rh1, NLN2H, rh)
    nrl = b.fma(rh1, W("NLN2L", ce["NLN2L"]), nre)
    nrl = b.fma(rl1, NLN2H, nrl)
    nrE = b.neg(rh)
    b.probes.update(tq=tq, rp=rp, rh=rh, nrl=nrl)
    _at(b, "exp-table", "lookup")
    Th, Tl = ml._table(b, ce, tq, k_, (lambda j: f"TH{j}", lambda j: f"TL{j}"))
    _at(b, "exp-scale", "scale")
    sc = ml._scale(b, "exp2", rnd, tq, ce, GE, None, k_)
    _at(b, "exp-poly", "tail")
    yv = W(f"EY{DE}", ce[f"Y{DE}"])
    for i in range(DE - 1, KE - 1, -1):
        yv = b.fma(yv, rh, W(f"EY{i}", ce[f"Y{i}"]))
    b.phase = "head"
    yh, yl = yv, None
    for i in range(KE - 1, -1, -1):
        CH, CLw = W(f"ECH{i}", ce[f"CH{i}"]), W(f"ECL{i}", ce[f"CL{i}"])
        pp = b.mul(yh, rh)
        ne2 = b.fma(yh, nrE, pp)
        nl = b.fma(yl, nrE, ne2) if yl is not None else ne2
        s, e = b.fast_two_sum(CH, pp)
        tt = b.sub(e, nl)
        yl = b.add(tt, CLw) if ce[f"CL{i}"] else tt
        yh = s
    b.phase = "Z"
    zp = b.mul(yh, rh)
    nze = b.fma(yh, nrE, zp)
    nzl = b.fma(yl, nrE, nze)
    eh = b.add(ONE, zp)
    nZl = b.fma(eh, nrl, nzl)
    _at(b, "exp-recon", "recon")
    P = b.mul(Th, zp)
    nPe = b.fma(Th, b.neg(zp), P)
    Sx, e2 = b.fast_two_sum(Th, P)
    a1 = b.fma(Th, nZl, nPe)
    a2 = b.fma(Tl, zp, Tl)
    lo = b.add(b.sub(e2, a1), a2)
    Vh, Vl = b.fast_two_sum(Sx, lo)

    # ---- the exact power of two, in-lane ------------------------------------
    _at(b, "exact", "final")
    jz = b.icmplt(b.iand(tq, ib(N - 1)), INT1)
    ex = b.sel(b.cmpeq(rp, ZERO), ZERO, jz)
    if fn != "rootn" or plant == "exact_rule_no_tl":
        if plant != "exact_rule_no_tl":
            ex = b.sel(b.cmpeq(tl, ZERO), ZERO, ex)
    ex = b.sel(b.cmpeq(r, ZERO), ZERO, ex)
    if fn == "compound":
        ex = b.sel(b.cmpeq(red.ul, ZERO), ZERO, ex)
    if plant == "exact_rule_off":
        ex = ZERO
    if fn == "rootn":
        Vh, Vl = b.sel(ONE, Vh, ex), b.sel(ZERO, Vl, ex)
    if sgnw is not None:
        Vh, Vl = b.ixor(Vh, sgnw), b.ixor(Vl, sgnw)
    b.probes.update(Vh=Vh, Vl=Vl, ex=ex)

    # ---- the final rounding and the in-lane test ----------------------------
    _at(b, "test", "final")
    R = b.add(Vh, Vl, rnd)
    aVh = b.fabs(Vh)
    ath = b.fabs(th)
    # `shift` inflates the bound 2^shift times, for the mark-rate law
    if plant == "bound_loose":
        shift -= 40
    if B1:
        w = b.fma(ath, W("B1", ml._enc(fmt, B1 * 2 ** shift)),
                  W("BREL", ml._pow2(fmt, -(p + G) + shift)), RUP)
        Bv = b.mul(aVh, w, RUP)
    else:
        Bv = b.mul(aVh, W("BREL", ml._pow2(fmt, -(p + G) + shift)))
    lo_dn = b.sub(Vl, Bv, RDN)
    lo_up = b.add(Vl, Bv, RUP)
    R1 = b.add(Vh, lo_dn, rnd)
    R2 = b.add(Vh, lo_up, rnd)
    mk = b.ixor(R1, R2)
    if rnd in (RNE, RMM) and plant != "exact_unmarked":
        # a grid point inside V's interval: the value may be exact, and the
        # inexact flag cannot be decided (the directed attributes' test marks
        # it already, a grid point being their boundary)
        g1 = b.add(Vh, lo_dn, RUP)
        g2 = b.add(Vh, lo_up, RDN)
        mk = b.sel(ONE, mk, b.cmple(g1, g2))
    b.probes.update(R=R, R1=R1, R2=R2, Bv=Bv)

    # ---- the fixed grid: a result that may be subnormal ---------------------
    _at(b, "fixed-grid", "fixed-grid")
    Cu = sc.Cu if sgnw is None else b.ixor(sc.Cu, sgnw)
    Z0 = b.add(Cu, Vh)
    W0 = b.sub(Z0, Cu)
    zr = b.sub(Vh, W0)
    s_ = b.add(zr, Vl, RTZ)
    eqv = b.cmpeq(b.sub(s_, zr), Vl)
    ro = b.sel(s_, b.ior(s_, INT1), eqv)
    Ws = b.sub(b.add(Z0, ro, rnd), Cu)
    if sgnw is not None and plant != "zero_sign_lost":
        # a negative result that rounds to zero on the subnormal grid: the
        # offset's subtraction gives +0 (x - x is +0 but under rdn), and the
        # answer is -0 (the first design lost it: the study's 3.6, item 7)
        Ws = b.ior(Ws, sgnw)
    if sc.hu is not None:
        c1 = b.cmpeq(b.fabs(zr), sc.hu)
        if plant == "midpoint_unmarked":
            c1 = ZERO
        if plant != "exact_unmarked":
            c1 = b.sel(ONE, c1, b.cmpeq(zr, ZERO))
    else:
        c1 = b.cmpeq(zr, ZERO)
    smallo = b.cmple(b.fabs(Vl), Bv)
    msub = b.sel(smallo, ZERO, c1)
    Wsel = b.sel(Ws, R, sc.sub_p)
    mk = b.sel(ONE, mk, b.sel(msub, ZERO, sc.sub_p))
    tn = b.sel(ONE, b.cmplt(b.fabs(R), ONE), sc.klt)
    tinyu = b.sel(tn, ZERO, sc.sub_p)

    # ---- the scaling, the flag word, the mark -------------------------------
    _at(b, "final", "final")
    Y1 = b.mul(Wsel, sc.S1)
    FIN = b.mul(Y1, sc.S2, rnd)
    ovf = b.cmpeq(b.mul(b.fabs(Y1), sc.S2, RUP), INF)
    fl = b.sel(OVFINX, b.sel(INXUNF, INX, tinyu), ovf)
    tinyt = b.icmplt(ath, W("TINYT", ml._pow2(fmt, -(p + 3))))
    if plant != "near_one_gate_off":
        mk = b.sel(ZERO, mk, tinyt)
    mk = b.sel(ZERO, mk, ex)
    if plant != "mark_silenced":
        fl = b.ior(fl, b.sel(MARKW, ZERO, mk))
    OFF = b.meta["OFF"]
    lowk = b.icmplt(sc.Ek, ib(fmt.emin - p + 1 + fmt.bias + OFF, "K_SUBMIN"))
    exrep = b.sel(b.sel(ZERO, b.sel(ZERO, ONE, lowk), ovf), ZERO, ex)
    fl = b.sel(ZERO, fl, exrep)
    bits = FIN

    # ---- the rule beside 1, transcend.py's own -------------------------------
    # |t_h| below 2^-(p+3) puts the value strictly inside the half gap next to
    # 1, on the side the operands' signs give, whatever t_h's own value: it
    # may have underflowed to 0 (y down to the least subnormal). The first
    # design only cleared the mark there and let V's rounding answer, which
    # gave 1 under rup for pow(1.2, minSub) (the study's 3.6; the plant
    # side_rule_off). An exact lane (x = -1 with an integer y: t = 0) is not
    # beside 1 but on it, and keeps its exact answer.
    if plant not in ("side_rule_off", "near_one_gate_off"):
        _at(b, "beside-1", "final")
        gt1 = b.icmplt(ONE, cl.ax)                    # |x| > 1
        if fn in ("pow", "powr"):
            up = b.sel(b.sel(ZERO, ONE, yc.neg), yc.neg, gt1)
        elif fn == "compound":                        # 1 + x > 1 iff x > 0
            up = cl.neg if n < 0 else b.sel(ZERO, ONE, cl.neg)
        else:                                         # pown, rootn
            up = b.sel(ZERO, ONE, gt1) if n < 0 else gt1
        one_m = 1 << (p - 1)

        def nbr(sign, away):
            return W(f"NB{sign}{int(away)}", sf.round_pack(
                fmt, sign, 8 * one_m + (1 if away else -1), -(p - 1) - 3,
                rnd)[0])
        nb = b.sel(nbr(0, True), nbr(0, False), up)
        if negres is not None:
            nb = b.sel(b.sel(nbr(1, True), nbr(1, False), up), nb, negres)
        side = b.sel(ZERO, tinyt, ex)
        bits = b.sel(nb, bits, side)
        fl = b.sel(INX, fl, side)
    b.probes.update(FIN=FIN, mk=mk, tinyt=tinyt)

    # ---- the screens and the specials ---------------------------------------
    _at(b, "special", "special")

    def signed_pair(pos, neg):
        if negres is None:
            return W(f"W{pos:x}", pos)
        return b.sel(W(f"W{neg:x}", neg), W(f"W{pos:x}", pos), negres)
    ovfb = signed_pair(sf.round_pack(fmt, 0, 3, fmt.emax, rnd)[0],
                       sf.round_pack(fmt, 1, 3, fmt.emax, rnd)[0])
    unfb = signed_pair(sf.round_pack(fmt, 0, 1, fmt.emin - mw - 2, rnd)[0],
                       sf.round_pack(fmt, 1, 1, fmt.emin - mw - 2, rnd)[0])
    bits = b.sel(ovfb, bits, ovs)
    fl = b.sel(OVFINX, fl, ovs)
    bits = b.sel(unfb, bits, uns)
    fl = b.sel(INXUNF, fl, uns)

    def sgn(v):
        return v if sgnw is None else b.ixor(v, sgnw)
    if fn == "pow":
        bits, fl = _pow_specials(b, k_, cl, yc, isint, sgnw, bits, fl, plant)
    elif fn == "powr":
        bits, fl = _powr_specials(b, k_, cl, yc, bits, fl, plant)
    elif fn == "pown":
        bits = b.sel(sgn(ZERO if n > 0 else INF), bits, cl.iszero)
        fl = b.sel(DIVZ if n < 0 else ZERO, fl, cl.iszero)
        bits = b.sel(sgn(INF if n > 0 else ZERO), bits, cl.isinf)
        fl = b.sel(ZERO, fl, cl.isinf)
        bits = b.sel(QNAN, bits, cl.isnan)
        fl = b.sel(b.sel(INVALID, ZERO, cl.issnan), fl, cl.isnan)
    elif fn == "rootn":
        bits = b.sel(sgn(INF if n > 0 else ZERO), bits, cl.isinf)
        fl = b.sel(ZERO, fl, cl.isinf)
        zsign = sgnw if plant != "rootn_m0_neg" else b.iand(x, SIGN)
        zb = ZERO if n > 0 else INF
        bits = b.sel(zb if zsign is None else b.ixor(zb, zsign), bits,
                     cl.iszero)
        fl = b.sel(DIVZ if n < 0 else ZERO, fl, cl.iszero)
        if n % 2 == 0:
            negnz = b.sel(ZERO, b.sel(ZERO, cl.neg, cl.iszero), cl.isnan)
            bits = b.sel(QNAN, bits, negnz)
            fl = b.sel(INVALID, fl, negnz)
        bits = b.sel(QNAN, bits, cl.isnan)
        fl = b.sel(b.sel(INVALID, ZERO, cl.issnan), fl, cl.isnan)
    else:                                         # compound
        NEGONE = W("NEGONE", sf.one_bits(fmt, 1))
        bits = b.sel(INF if n > 0 else ZERO, bits, cl.isinf)
        fl = b.sel(ZERO, fl, cl.isinf)
        bits = b.sel(ONE, bits, cl.iszero)
        fl = b.sel(ZERO, fl, cl.iszero)
        m1 = b.cmpeq(x, NEGONE)
        bits = b.sel(ZERO if n > 0 else INF, bits, m1)
        fl = b.sel(DIVZ if n < 0 else ZERO, fl, m1)
        below = b.cmplt(x, NEGONE)
        bits = b.sel(QNAN, bits, below)
        fl = b.sel(INVALID, fl, below)
        bits = b.sel(QNAN, bits, cl.isnan)
        fl = b.sel(b.sel(INVALID, ZERO, cl.issnan), fl, cl.isnan)
    b.label_of = b.label_of[:len(b.body)]
    return b.finish(bits, fl)


def _pow_specials(b, k_, cl, yc, isint, sgnw, bits, fl, plant):
    """pow's 9.2.1 rows, lowest priority first (transcend.pow's order
    reversed): y = 1 (x itself, exact), x < 0 with y not an integer,
    x = +-inf, x = +-0, y = +-inf, a NaN, y = +-0 or x = +1, a sNaN."""
    ZERO, ONE, INF, QNAN = k_["ZERO"], k_["ONE"], k_["INF"], k_["QNAN"]
    INVALID = k_["INVALID"]
    DIVZ = k_["ib"](sf.FLAG_DIVZERO, "FL_DIVZERO")
    x, y = cl.x, yc.x

    def sgn(v):
        return v if sgnw is None else b.ixor(v, sgnw)
    y1 = b.cmpeq(y, ONE)
    bits = b.sel(x, bits, y1)
    fl = b.sel(ZERO, fl, y1)
    bad = b.sel(b.sel(ZERO, ONE, isint), ZERO, cl.neg)   # x < 0, y not int
    bits = b.sel(QNAN, bits, bad)
    fl = b.sel(INVALID, fl, bad)
    bits = b.sel(sgn(b.sel(ZERO, INF, yc.neg)), bits, cl.isinf)
    fl = b.sel(ZERO, fl, cl.isinf)
    bits = b.sel(sgn(b.sel(INF, ZERO, yc.neg)), bits, cl.iszero)
    fl = b.sel(b.sel(DIVZ, ZERO, yc.neg), fl, cl.iszero)
    gt1 = b.icmplt(ONE, cl.ax)                           # |x| > 1
    big = b.sel(b.sel(ZERO, INF, yc.neg), b.sel(INF, ZERO, yc.neg), gt1)
    yinf = b.sel(ONE, big, b.cmpeq(cl.ax, ONE))          # pow(-1, +-inf) = 1
    bits = b.sel(yinf, bits, yc.isinf)
    fl = b.sel(ZERO, fl, yc.isinf)
    anynan = b.sel(ONE, cl.isnan, yc.isnan)
    bits = b.sel(QNAN, bits, anynan)
    fl = b.sel(ZERO, fl, anynan)
    one_ = ZERO
    if plant != "pow_zero_nan":
        one_ = yc.iszero
    if plant != "pow_one_nan":
        one_ = b.sel(ONE, one_, b.cmpeq(x, ONE))
    bits = b.sel(ONE, bits, one_)
    fl = b.sel(ZERO, fl, one_)
    snan = b.sel(ONE, cl.issnan, yc.issnan)
    bits = b.sel(QNAN, bits, snan)
    fl = b.sel(INVALID, fl, snan)
    return bits, fl


def _powr_specials(b, k_, cl, yc, bits, fl, plant):
    """powr's rows (transcend.powr's docstring table), lowest priority
    first: y = 1, y = +-inf, y = +-0, x = +1, x = +inf, x = +-0, a NaN,
    x < 0 (before a quiet NaN exponent), a sNaN."""
    ZERO, ONE, INF, QNAN = k_["ZERO"], k_["ONE"], k_["INF"], k_["QNAN"]
    INVALID = k_["INVALID"]
    DIVZ = k_["ib"](sf.FLAG_DIVZERO, "FL_DIVZERO")
    x, y = cl.x, yc.x
    y1 = b.cmpeq(y, ONE)
    bits = b.sel(x, bits, y1)
    fl = b.sel(ZERO, fl, y1)
    gt1 = b.icmplt(ONE, cl.ax)
    big = b.sel(b.sel(ZERO, INF, yc.neg), b.sel(INF, ZERO, yc.neg), gt1)
    bits = b.sel(big, bits, yc.isinf)
    fl = b.sel(ZERO, fl, yc.isinf)
    bits = b.sel(ONE, bits, yc.iszero)
    fl = b.sel(ZERO, fl, yc.iszero)
    xone = b.cmpeq(x, ONE)
    bits = b.sel(b.sel(QNAN, ONE, yc.isinf), bits, xone)
    fl = b.sel(b.sel(INVALID, ZERO, yc.isinf), fl, xone)
    zz = ZERO if plant == "powr_zero_zero" else yc.iszero
    infr = b.sel(QNAN, b.sel(ZERO, INF, yc.neg), yc.iszero)
    bits = b.sel(infr, bits, cl.isinf)
    fl = b.sel(b.sel(INVALID, ZERO, yc.iszero), fl, cl.isinf)
    zres = b.sel(QNAN, b.sel(INF, ZERO, yc.neg), zz)
    zfl = b.sel(INVALID, b.sel(b.sel(ZERO, DIVZ, yc.isinf), ZERO, yc.neg),
                zz)
    if plant == "powr_zero_zero":
        zres = b.sel(ONE, zres, yc.iszero)
        zfl = b.sel(ZERO, zfl, yc.iszero)
    bits = b.sel(zres, bits, cl.iszero)
    fl = b.sel(zfl, fl, cl.iszero)
    anynan = b.sel(ONE, cl.isnan, yc.isnan)
    bits = b.sel(QNAN, bits, anynan)
    fl = b.sel(ZERO, fl, anynan)
    if plant != "powr_neg_ok":
        negx = b.sel(ZERO, b.sel(ZERO, cl.neg, cl.iszero), cl.isnan)
        bits = b.sel(QNAN, bits, negx)
        fl = b.sel(INVALID, fl, negx)
    snan = b.sel(ONE, cl.issnan, yc.issnan)
    bits = b.sel(QNAN, bits, snan)
    fl = b.sel(INVALID, fl, snan)
    return bits, fl


class Refused(Exception):
    """A constant integer operand the compiler refuses by name (section
    6): rootn(x, 0) is invalid for every x."""


def build_small(fn, fmt, rnd, n):
    """The integer-operand functions at the n that need no core (section
    2.1): n = 0 (pown 1, compound 1 or invalid below -1; rootn refused),
    n = 1 (pown and rootn x itself; compound 1 + x rounded once, its
    inexact flag from TwoSum's exact error, its overflow from the sum).
    None where the core is used."""
    if n not in (0, 1):
        return None
    if fn == "rootn" and n == 0:
        raise Refused("rootn(x, 0) is invalid for every x, a quiet NaN "
                      "included: a constant the compiler refuses")
    b = PBuild(fmt, rnd, f"{fn}-{fmt.name}-{AN[rnd]}-n{n}")
    b.inputs = ("a",)
    b.meta.update(fn=fn, n=n, family="small", G=GUARD[fmt.name])
    k_ = ml._words_common(b)
    ZERO, ONE, INF, QNAN = k_["ZERO"], k_["ONE"], k_["INF"], k_["QNAN"]
    INVALID, INX, OVFINX = k_["INVALID"], k_["INX"], k_["OVFINX"]
    _at(b, "classify", "classify")
    cl = ml._classify_common(b, k_)
    x = cl.x
    _at(b, "special", "special")
    NEGONE = b.word(sf.one_bits(fmt, 1), "NEGONE")
    if n == 0:
        bits = b.sel(QNAN, ONE, cl.issnan)
        fl = b.sel(INVALID, ZERO, cl.issnan)
        if fn == "compound":
            below = b.cmplt(x, NEGONE)
            bits = b.sel(QNAN, bits, below)
            fl = b.sel(INVALID, fl, below)
        return b.finish(bits, fl)
    if fn in ("pown", "rootn"):
        bits = b.sel(QNAN, x, cl.isnan)
        fl = b.sel(INVALID, ZERO, cl.issnan)
        return b.finish(bits, fl)
    # compound(x, 1): (1 + x) rounded once under rnd; inexact exactly when
    # TwoSum's error is not zero; overflow only where the sum is infinite
    # (rup at x = max), 1 + x being exact by Sterbenz near -1
    s = b.add(ONE, x, rnd)
    _sn, err = b.two_sum(ONE, x)
    fl = b.sel(ZERO, INX, b.cmpeq(err, ZERO))
    fl = b.sel(OVFINX, fl, b.cmpeq(s, INF))
    bits = s
    bits = b.sel(INF, bits, cl.isinf)
    fl = b.sel(ZERO, fl, cl.isinf)
    # compound(-1, n > 0) is +0 under every attribute; 1 + (-1) is -0 under
    # rdn (the model's first version answered -0 there: the study's 3.6)
    bits = b.sel(ZERO, bits, b.cmpeq(x, NEGONE))
    below = b.cmplt(x, NEGONE)
    bits = b.sel(QNAN, bits, below)
    fl = b.sel(INVALID, fl, below)
    bits = b.sel(QNAN, bits, cl.isnan)
    fl = b.sel(b.sel(INVALID, ZERO, cl.issnan), fl, cl.isnan)
    return b.finish(bits, fl)


def build_any(fn, fmt, rnd, n=None, plant=None, **kw):
    """build_small where it applies, else the core."""
    if fn in ("pown", "rootn", "compound"):
        sb = build_small(fn, fmt, rnd, n)
        if sb is not None and plant is None:
            return sb
    return build(fn, fmt, rnd, n=n, plant=plant, **kw)


def lane_of(fn, lane):
    """The Build.run argument of a lane (x, y) or (x, n)."""
    x, b2 = lane
    return (x, b2) if fn in ("pow", "powr") else x


def run(bld, fn, lane, want=()):
    return bld.run(lane_of(fn, lane), want)
