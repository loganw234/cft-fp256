# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""The formatOf arithmetic operations, IEEE 754-2019 clause 5.4.1.

The six general-computational arithmetic operations with the operands
in ONE binary format and the destination in ANOTHER, rounded once.
5.4.1 requires them, in as many words:

    "Implementations shall provide the following formatOf general-
     computational operations, for destinations of all supported
     arithmetic formats, and, for each destination format, for operands
     of all supported arithmetic formats with the same radix as the
     destination format:

         formatOf-addition(source1, source2)
         formatOf-subtraction(source1, source2)
         formatOf-multiplication(source1, source2)
         formatOf-division(source1, source2)
         formatOf-squareRoot(source)
         formatOf-fusedMultiplyAdd(source1, source2, source3)"

Everything in softfloat.py already takes one format for the operands
and the same one for the result. This module is the same six operations
with the two separated, and it is written from the DEFINITION rather
than from the single-format code: unpack the operands in `sfmt`, form
the exact rational result, round it ONCE into `dfmt`, and report the
flags clause 7 asks for at the destination.

WHAT IS ACTUALLY DIFFERENT

Only two things, and both of them live at the destination:

1. THE ROUNDING POSITION AND THE EXPONENT RANGE ARE THE DESTINATION'S.
   `round_pack(dfmt, ...)` decides inexact, tininess (after rounding,
   as the contract states everywhere else), underflow and overflow
   against dfmt's p, emin and emax - never against the operands'. So a
   product of two ordinary binary64 values can overflow a binary32
   destination, and a difference of two ordinary binary64 values can
   land on binary32's subnormal grid, and both are the destination's
   exceptions, raised once.

2. A SPECIAL RESULT IS BUILT IN THE DESTINATION. The canonical quiet
   NaN, the infinities and the zeros are dfmt's encodings. A signaling
   NaN operand raises invalid exactly as it does in the same-format
   operations (6.2.1: every general-computational operation signals on
   one), and the result is dfmt's canonical quiet NaN - this contract's
   standing deviation from 6.2.3's payload recommendation, unchanged
   here.

Everything else is the arithmetic that was already exact. Note in
particular what does NOT get a special case: `x + 0` is x exactly, but
x is a value of the SOURCE format and the destination may not hold it,
so it goes through the same single `round_pack` as any other result
instead of being returned verbatim. Returning the operand's bits - which
is right in the same-format case and is what softfloat.add does - would
silently skip the rounding and its flags.

NARROW SOURCE, WIDE DESTINATION: A COMPOSITION, AND WHY

When dfmt is at least as wide as sfmt every source value is exactly a
destination value (the interchange ladder nests: fp32's values are
fp64's, fp64's are fp128's, fp128's are fp256's, in significand bits
and in exponent range both). Widening is therefore exact and signals
nothing except the invalid a signaling NaN earns, so

    formatOf-op(sfmt -> dfmt) == op_dfmt(convert(a), convert(b), ...)

with one rounding either way - the conversion did not round, so the
operation's rounding is still the only one. test_formatof.py asserts
that identity over every pair rather than trusting it, and libcft takes
exactly that route in that direction so that a device backend still
runs the arithmetic on the tile.

WIDE SOURCE, NARROW DESTINATION: NOT A COMPOSITION, AND WHY NOT

The other direction cannot be composed, in EITHER order:

* Operate then convert is a DOUBLE ROUNDING, and it is wrong. Not
  "wrong in principle and right in practice" - wrong on operands this
  library will meet. The classical theorem (Figueroa: double rounding
  through an intermediate of q >= 2p + 2 bits is innocuous for the five
  basic operations) does not apply here, and the difference is exactly
  which format the OPERANDS live in. That theorem takes p-bit operands
  and asks about a q-bit intermediate; here the operands are the WIDE
  format's, and the bound that makes the theorem work - "a quotient of
  p-bit values cannot come within a whisker of a p-bit midpoint" - is
  a statement about p-bit operands and says nothing about wide ones.
  `double_rounding_witness()` below CONSTRUCTS the counterexample for
  any ordered pair, for division, square root and fused multiply-add
  alike, and python/tests/test_formatof.py runs them.

* Convert then operate rounds the operands, which is a different
  operation entirely.

So the wide-to-narrow direction is what the work is: form the exact
result and round it once against the destination's descriptor. That is
what this module does for all six, in every direction, uniformly - the
composition above is an identity it satisfies, not a route it takes.

python/tests/test_formatof.py is the checking layer; host/src/formatof.c
is the C port; host/tests/formatof_check.py drives the two against each
other; and the <sfmt>-to-<dfmt>-formatof[-<rnd>].jsonl sets publish the
result.
"""

import math

from .formats import FpFormat, FORMATS
from . import softfloat as sf

#: The six operations, in the order the ABI, the vector sets and the
#: MPFR harness use. Names are the standard's own, minus the
#: "formatOf-" prefix that every one of them shares.
FORMATOF_FNS = ("addition", "subtraction", "multiplication",
                "division", "squareRoot", "fusedMultiplyAdd")

(FN_FO_ADD, FN_FO_SUB, FN_FO_MUL,
 FN_FO_DIV, FN_FO_SQRT, FN_FO_FMA) = FORMATOF_FNS

#: How many operands each reads, so a generator and a replayer agree
#: without either of them holding a second copy of the table.
FORMATOF_ARITY = {
    FN_FO_ADD: 2, FN_FO_SUB: 2, FN_FO_MUL: 2,
    FN_FO_DIV: 2, FN_FO_SQRT: 1, FN_FO_FMA: 3,
}

#: The short name each set file and each C entry point carries.
FORMATOF_SHORT = {
    FN_FO_ADD: "add", FN_FO_SUB: "sub", FN_FO_MUL: "mul",
    FN_FO_DIV: "div", FN_FO_SQRT: "sqrt", FN_FO_FMA: "fma",
}


def _nan_out(dfmt, *ops):
    """The canonical quiet NaN of the DESTINATION, and invalid when any
    operand the operation reads was signaling (6.2.1)."""
    invalid = any(u.kind == sf.NAN and u.signaling for u in ops)
    return sf.qnan_bits(dfmt), (sf.FLAG_INVALID if invalid else 0)


def _pack_operand(dfmt, u, rnd):
    """The destination's rounding of one finite operand's exact value -
    the tail of every 'the answer is one of the operands, exactly' case.

    In the same-format operations those cases return the operand's own
    encoding; here the value is exact but the destination may not hold
    it, so the single rounding still has to happen and still has to
    report its flags."""
    if u.kind == sf.ZERO:
        return sf.zero_bits(dfmt, u.sign), 0
    return sf.round_pack(dfmt, u.sign, u.m, u.e, rnd)


def fo_fma(sfmt: FpFormat, dfmt: FpFormat, xa: int, xb: int, xc: int,
           rnd: int = sf.RND_RNE):
    """(bits in dfmt, flags) of formatOf-fusedMultiplyAdd(a, b, c).

    a*b + c with ONE rounding, the operands in sfmt and the result in
    dfmt. The product is exact (2p bits of source significand); the
    addend joins it exactly; the single round_pack is the destination's.
    """
    sf._check_mode(rnd)
    ua, ub, uc = (sf.unpack(sfmt, xa), sf.unpack(sfmt, xb),
                  sf.unpack(sfmt, xc))
    if sf.NAN in (ua.kind, ub.kind, uc.kind):
        return _nan_out(dfmt, ua, ub, uc)
    sp = ua.sign ^ ub.sign

    if sf.INF in (ua.kind, ub.kind):
        if sf.ZERO in (ua.kind, ub.kind):
            return sf.qnan_bits(dfmt), sf.FLAG_INVALID       # inf * 0
        if uc.kind == sf.INF and uc.sign != sp:
            return sf.qnan_bits(dfmt), sf.FLAG_INVALID       # inf - inf
        return sf.inf_bits(dfmt, sp), 0
    if uc.kind == sf.INF:
        return sf.inf_bits(dfmt, uc.sign), 0

    if sf.ZERO in (ua.kind, ub.kind):
        if uc.kind == sf.ZERO:
            rs = uc.sign if uc.sign == sp else \
                sf.zero_sign_for_exact_cancellation(rnd)
            return sf.zero_bits(dfmt, rs), 0
        return _pack_operand(dfmt, uc, rnd)   # 0*b + c is c, exactly

    mp, ep = ua.m * ub.m, ua.e + ub.e         # exact product
    if uc.kind == sf.ZERO:
        return sf.round_pack(dfmt, sp, mp, ep, rnd)

    e0 = min(ep, uc.e)
    t = (mp << (ep - e0)) * (-1 if sp else 1) \
        + (uc.m << (uc.e - e0)) * (-1 if uc.sign else 1)
    if t == 0:
        return (sf.zero_bits(dfmt,
                             sf.zero_sign_for_exact_cancellation(rnd)), 0)
    return sf.round_pack(dfmt, 1 if t < 0 else 0, abs(t), e0, rnd)


def fo_add(sfmt: FpFormat, dfmt: FpFormat, xa: int, xb: int,
           rnd: int = sf.RND_RNE):
    """(bits in dfmt, flags) of formatOf-addition(a, b)."""
    sf._check_mode(rnd)
    ua, ub = sf.unpack(sfmt, xa), sf.unpack(sfmt, xb)
    if sf.NAN in (ua.kind, ub.kind):
        return _nan_out(dfmt, ua, ub)
    if ua.kind == sf.INF:
        if ub.kind == sf.INF and ub.sign != ua.sign:
            return sf.qnan_bits(dfmt), sf.FLAG_INVALID
        return sf.inf_bits(dfmt, ua.sign), 0
    if ub.kind == sf.INF:
        return sf.inf_bits(dfmt, ub.sign), 0
    if ua.kind == sf.ZERO and ub.kind == sf.ZERO:
        rs = ua.sign if ua.sign == ub.sign else \
            sf.zero_sign_for_exact_cancellation(rnd)
        return sf.zero_bits(dfmt, rs), 0
    if ua.kind == sf.ZERO:
        return _pack_operand(dfmt, ub, rnd)
    if ub.kind == sf.ZERO:
        return _pack_operand(dfmt, ua, rnd)
    e0 = min(ua.e, ub.e)
    t = (ua.m << (ua.e - e0)) * (-1 if ua.sign else 1) \
        + (ub.m << (ub.e - e0)) * (-1 if ub.sign else 1)
    if t == 0:
        return (sf.zero_bits(dfmt,
                             sf.zero_sign_for_exact_cancellation(rnd)), 0)
    return sf.round_pack(dfmt, 1 if t < 0 else 0, abs(t), e0, rnd)


def fo_sub(sfmt: FpFormat, dfmt: FpFormat, xa: int, xb: int,
           rnd: int = sf.RND_RNE):
    """(bits in dfmt, flags) of formatOf-subtraction(a, b).

    a - b is a + (-b) with every rule of formatOf-addition, the signed
    zeros included; the negation happens in the SOURCE format, where b
    lives."""
    return fo_add(sfmt, dfmt, xa, sf.negate(sfmt, xb), rnd)


def fo_mul(sfmt: FpFormat, dfmt: FpFormat, xa: int, xb: int,
           rnd: int = sf.RND_RNE):
    """(bits in dfmt, flags) of formatOf-multiplication(a, b)."""
    sf._check_mode(rnd)
    ua, ub = sf.unpack(sfmt, xa), sf.unpack(sfmt, xb)
    if sf.NAN in (ua.kind, ub.kind):
        return _nan_out(dfmt, ua, ub)
    sp = ua.sign ^ ub.sign
    if sf.INF in (ua.kind, ub.kind):
        if sf.ZERO in (ua.kind, ub.kind):
            return sf.qnan_bits(dfmt), sf.FLAG_INVALID
        return sf.inf_bits(dfmt, sp), 0
    if sf.ZERO in (ua.kind, ub.kind):
        return sf.zero_bits(dfmt, sp), 0
    return sf.round_pack(dfmt, sp, ua.m * ub.m, ua.e + ub.e, rnd)


def fo_div(sfmt: FpFormat, dfmt: FpFormat, xa: int, xb: int,
           rnd: int = sf.RND_RNE):
    """(bits in dfmt, flags) of formatOf-division(a, b), correctly
    rounded.

    Exact long division carried to at least p+3 quotient bits of the
    DESTINATION's precision, with everything below the last computed bit
    folded into one sticky - softfloat.div's construction with dfmt's p
    in place of the single format's. There is no second rounding
    anywhere in it, which is the whole point: see this module's banner
    and `double_rounding_witness` for what happens to the version that
    rounds in sfmt first.
    """
    sf._check_mode(rnd)
    ua, ub = sf.unpack(sfmt, xa), sf.unpack(sfmt, xb)
    if sf.NAN in (ua.kind, ub.kind):
        return _nan_out(dfmt, ua, ub)
    sq = ua.sign ^ ub.sign

    if ua.kind == sf.INF:
        if ub.kind == sf.INF:
            return sf.qnan_bits(dfmt), sf.FLAG_INVALID       # inf / inf
        return sf.inf_bits(dfmt, sq), 0
    if ub.kind == sf.INF:
        return sf.zero_bits(dfmt, sq), 0
    if ub.kind == sf.ZERO:
        if ua.kind == sf.ZERO:
            return sf.qnan_bits(dfmt), sf.FLAG_INVALID       # 0 / 0
        return sf.inf_bits(dfmt, sq), sf.FLAG_DIVZERO        # x / 0
    if ua.kind == sf.ZERO:
        return sf.zero_bits(dfmt, sq), 0

    p = dfmt.prec
    k = (p + 3) + ub.m.bit_length() - ua.m.bit_length() + 1
    if k < 0:
        k = 0
    q, rem = divmod(ua.m << k, ub.m)
    assert q.bit_length() >= p + 3
    m = sf._fold_sticky(q, rem != 0)
    e = (ua.e - ub.e) - k - 1
    return sf.round_pack(dfmt, sq, m, e, rnd)


def fo_sqrt(sfmt: FpFormat, dfmt: FpFormat, xa: int,
            rnd: int = sf.RND_RNE):
    """(bits in dfmt, flags) of formatOf-squareRoot(a), correctly
    rounded. softfloat.sqrt's construction with dfmt's p, and the same
    single rounding."""
    sf._check_mode(rnd)
    ua = sf.unpack(sfmt, xa)
    if ua.kind == sf.NAN:
        return _nan_out(dfmt, ua)
    if ua.kind == sf.ZERO:
        return sf.zero_bits(dfmt, ua.sign), 0     # sqrt(+/-0) is +/-0
    if ua.sign:
        return sf.qnan_bits(dfmt), sf.FLAG_INVALID   # negative, -inf too
    if ua.kind == sf.INF:
        return sf.inf_bits(dfmt, 0), 0

    p = dfmt.prec
    m, e = ua.m, ua.e
    t = 2 * (p + 3) - m.bit_length()
    if t < 0:
        t = 0
    t += (t ^ e) & 1                        # keep e - t even
    m <<= t
    e -= t
    assert (e & 1) == 0
    r = math.isqrt(m)
    assert r.bit_length() >= p + 3
    mres = sf._fold_sticky(r, r * r != m)
    eres = e // 2 - 1
    # In the SAME-format case the root of a positive finite value sits
    # at about half the operand's exponent and so cannot leave the
    # range - which is why softfloat.sqrt says round_pack cannot
    # overflow or underflow there. Across formats that stops being
    # true, and it is worth naming: the root of the largest binary256
    # is about 2^131071, far above binary32's emax, and the root of the
    # smallest binary256 subnormal is about 2^-131189, far below
    # binary32's subnormal floor. Both of the destination's exceptions
    # are reachable here, and round_pack raises them.
    return sf.round_pack(dfmt, 0, mres, eres, rnd)


FORMATOF_IMPL = {
    FN_FO_ADD:  lambda s, d, a, b, c, r: fo_add(s, d, a, b, r),
    FN_FO_SUB:  lambda s, d, a, b, c, r: fo_sub(s, d, a, b, r),
    FN_FO_MUL:  lambda s, d, a, b, c, r: fo_mul(s, d, a, b, r),
    FN_FO_DIV:  lambda s, d, a, b, c, r: fo_div(s, d, a, b, r),
    FN_FO_SQRT: lambda s, d, a, b, c, r: fo_sqrt(s, d, a, r),
    FN_FO_FMA:  fo_fma,
}


def compute(sfmt: FpFormat, dfmt: FpFormat, fn: str, xa: int, xb: int = 0,
            xc: int = 0, rnd: int = sf.RND_RNE):
    """(bits in dfmt, flags) of one formatOf operation by name - the
    dispatch the vector generator and the conformance sets use."""
    try:
        impl = FORMATOF_IMPL[fn]
    except KeyError:
        raise ValueError(f"unknown formatOf operation {fn!r}") from None
    return impl(sfmt, dfmt, xa, xb, xc, rnd)


# ---- cross-format comparison (754-2019 5.11) -------------------------
#
# 5.11 asks for comparison across formats and does NOT make it a
# formatOf operation, because a comparison has no destination format to
# round into:
#
#   "Comparisons shall be exact and never overflow nor underflow.
#    ... Infinite operands of the same sign shall compare equal.
#    ... Comparisons of two data of different binary formats shall be
#    exact, as if the data were converted to a common format with
#    unbounded exponent range and precision."
#
# On this ladder that common format is simply the wider of the two, and
# converting into it is exact - which is why this is a composition and
# not an entry point. libcft's callers write cft_convert then the
# comparison they already have; a signaling NaN raises invalid on the
# way through the conversion exactly as it would have in the comparison
# (6.2.1 for the conversion, 5.11 for cmp_sig), so the signal is neither
# lost nor doubled - the flag word is sticky and an OR of one raised bit
# with another raised bit is one raised bit.


def compare(afmt: FpFormat, bfmt: FpFormat, xa: int, xb: int,
            signaling: bool = False):
    """(predicate triple, flags) for 5.11 comparison ACROSS two binary
    formats, as the composition it is.

    Returns ((lt, eq, gt), flags) with the three quiet predicates of
    5.6.1 - all three False means unordered - and the flag word the
    composition raises. `signaling` selects the signaling forms, which
    signal invalid on ANY NaN rather than only on a signaling one.

    This exists to be TESTED, not to be a route: the identity it asserts
    is that widening the narrower operand into the wider format and then
    comparing there is the exact comparison 5.11 defines. No entry point
    is added to libcft for it, and docs/DETERMINISM.md says so.
    """
    wide = afmt if afmt.prec >= bfmt.prec else bfmt
    fl = 0
    va, fa = sf.convert(afmt, wide, xa, sf.RND_RNE)
    vb, fb = sf.convert(bfmt, wide, xb, sf.RND_RNE)
    # The conversions are exact in both directions here (the wider
    # format holds every value of the narrower, and the wider-to-itself
    # conversion is the identity), so the only bit either can raise is
    # the invalid a signaling NaN earns.
    assert (fa | fb) & ~sf.FLAG_INVALID == 0, "5.11 widening must be exact"
    fl |= fa | fb
    ua, ub = sf.unpack(wide, va), sf.unpack(wide, vb)
    if sf.NAN in (ua.kind, ub.kind):
        if signaling:
            fl |= sf.FLAG_INVALID
        return (False, False, False), fl
    lt, _ = sf.cmplt(wide, va, vb)
    eq, _ = sf.cmpeq(wide, va, vb)
    gt, _ = sf.cmplt(wide, vb, va)
    return (bool(lt), bool(eq), bool(gt)), fl


# ---- the double-rounding witnesses -----------------------------------
#
# Constructed, never transcribed. Each function below returns operands
# in `sfmt` for which
#
#     round_dfmt(exact result)  !=  round_dfmt(round_wfmt(exact result))
#
# for a chosen intermediate format `wfmt` - so that a test can show the
# composed route failing rather than assert that it would.


def _wide_format(prec: int, exp_w: int = 24) -> FpFormat:
    """A synthetic binary format of `prec` significand bits and a very
    wide exponent field, for standing in as the intermediate of a
    double-rounding scheme. Not an interchange format and not supported
    by anything here - it exists so that "at any width" can be tested
    at several widths instead of argued."""
    return FpFormat(f"w{prec}", exp_w, prec - 1)


def double_rounding_witness(sfmt: FpFormat, dfmt: FpFormat, fn: str,
                            wprec: int = None):
    """Operands in `sfmt` that break the composed route for `fn`.

    Returns (xa, xb, xc, wfmt) where wfmt is the intermediate format the
    witness defeats: rounding the exact result to wfmt and then to dfmt
    gives a different answer from rounding it once to dfmt, under
    roundTiesToEven. `wprec` defaults to sfmt's own precision, which is
    the route COMPLIANCE.md considered and this module rejects.

    THE CONSTRUCTION, for all three of division, square root and fused
    multiply-add, is one idea:

        put the exact result a hair ABOVE a midpoint of the DESTINATION
        grid, closer to it than half an ulp of the intermediate.

    The first rounding then lands exactly ON the midpoint, which is
    representable in any intermediate with at least p_d + 1 bits; the
    second rounding sees a tie and breaks it to even, downward; and the
    single correct rounding goes up, because the exact value was above
    the midpoint. The hair is what each operation has to supply:

    * FUSED MULTIPLY-ADD is the easy one and the one no width can fix:
      the product IS the midpoint exactly (m x 1), and the addend is a
      free choice of any positive source value, so it can be made
      smaller than the intermediate's half-ulp for ANY intermediate
      precision the source's exponent range can undercut - down to
      2^(emin_s - p_s + 1). At binary64 that is 1074 binades of headroom
      below the midpoint, so no finite intermediate under about a
      thousand bits escapes.
    * DIVISION supplies the hair from the remainder: choose the divisor
      so that m * y misses the source grid by exactly one unit in the
      last place of the exact product, and take the dividend to be the
      nearest source value ABOVE it. Then x/y - m is that one unit
      divided by y - about 2^-(p_s + p_d) of the value, far under the
      intermediate's 2^-p_s half-ulp.
    * SQUARE ROOT supplies it from the next value above m^2: m^2 is
      exactly representable when 2 p_d + 1 <= p_s, and sqrt of the
      source value one ulp above it exceeds m by about a quarter of the
      intermediate's ulp.

    Every constant below is derived from the format descriptors.
    """
    ps, pd = sfmt.prec, dfmt.prec
    if pd >= ps:
        raise ValueError("a witness needs a destination narrower than "
                         "the source")
    wfmt = _wide_format(ps if wprec is None else wprec)

    # The destination midpoint, at the bottom of the binade where the
    # even neighbour is the power of two itself: m = 1 + 2^-pd, whose
    # neighbours in dfmt are 1 (last bit 0, so RNE's tie goes here) and
    # 1 + 2^(1-pd). M is m's integer significand at weight 2^-pd.
    M = (1 << pd) + 1                      # odd, pd + 1 bits

    if fn == FN_FO_FMA:
        # a * b = m exactly, with b = 1; c = the smallest positive
        # source value, which is below every intermediate's half-ulp at
        # magnitude 1 for any intermediate under emin_s - ps + 1 bits.
        xa = sf.round_pack(sfmt, 0, M, -pd, sf.RND_RNE)[0]
        xb = sf.one_bits(sfmt)
        xc = sf.min_subnormal_bits(sfmt)
        return xa, xb, xc, wfmt

    if fn == FN_FO_DIV:
        # y = 1 + (2^(ps - pd) - 1) * 2^(1 - ps): a source value whose
        # significand Y satisfies M*Y = 1 (mod 2^pd) with the residue
        # just BELOW a multiple of the source grid, so the nearest
        # source value above m*y is one unit of the exact product's last
        # place away and x/y sits that far above m.
        #
        # Y is ps bits: 2^(ps-1) + (2^(ps-pd) - 1). Then
        #   M * Y  =  (2^pd + 1) * Y  =  2^pd * Y + Y,
        # and Y mod 2^pd = 2^pd - 1 by construction, i.e. -1, so the
        # exact product m*y falls exactly one unit of 2^(-pd-ps+1) short
        # of a multiple of the source ulp.
        Y = (1 << (ps - 1)) + ((1 << (ps - pd)) - 1)
        assert Y % (1 << pd) == (1 << pd) - 1
        xb, fb = sf.round_pack(sfmt, 0, Y, 1 - ps, sf.RND_RNE)
        assert fb == 0, "the divisor must be a source value"
        # The exact product M*Y sits at weight 2^(1 - pd - ps) and is
        # one unit SHORT of a multiple of 2^pd there - which is the
        # source grid - because M*Y == -1 (mod 2^pd). Adding that one
        # unit therefore lands exactly on a source value, and it is the
        # dividend: x / y is then m plus one unit of 2^(1-pd-ps) over y.
        prod = M * Y
        xa, fa = sf.round_pack(sfmt, 0, prod + 1, 1 - pd - ps, sf.RND_RNE)
        assert fa == 0, "the dividend must be exact in the source"
        return xa, xb, 0, wfmt

    if fn == FN_FO_SQRT:
        # m^2 needs 2*pd + 1 bits; the ladder gives 2*pd + 2 <= ps for
        # every ordered pair here, so it is a source value, and the
        # source value one ulp above it has a root a quarter of an
        # intermediate ulp above m.
        if 2 * pd + 1 > ps:
            raise ValueError("no square-root witness: the destination "
                             "midpoint's square does not fit the source")
        sq = M * M                                  # weight 2^(-2*pd)
        xa, fa = sf.round_pack(sfmt, 0, sq, -2 * pd, sf.RND_RNE)
        assert fa == 0, "m^2 must be exact in the source"
        # The next source value up. m^2 is in [1, 2) with a significand
        # far from all-ones, so incrementing the encoding IS nextUp.
        xa += 1
        return xa, 0, 0, wfmt

    raise ValueError(f"no double-rounding witness for {fn!r}: addition, "
                     f"subtraction and multiplication have exact results "
                     f"that the intermediate holds or does not, and the "
                     f"library never composes them")


def composed_route(sfmt: FpFormat, dfmt: FpFormat, wfmt: FpFormat, fn: str,
                   xa: int, xb: int = 0, xc: int = 0,
                   rnd: int = sf.RND_RNE):
    """The route this module does NOT take: compute the correctly
    rounded result in `wfmt`, then convert it to `dfmt`. Two roundings.

    Here so that a test can EXHIBIT the difference rather than describe
    it, and so that host/src/formatof.c's negative control has a name in
    the model for what it is doing wrong. Flags follow the rule the
    composed route would have to use - the wide step's inexact kept, the
    destination's overflow and underflow decided by the second rounding.
    """
    if wfmt is sfmt or (wfmt.prec == sfmt.prec and wfmt.exp_w == sfmt.exp_w):
        wide, fw = compute(sfmt, sfmt, fn, xa, xb, xc, rnd)
        uw = sfmt
    else:
        wide, fw = compute(sfmt, wfmt, fn, xa, xb, xc, rnd)
        uw = wfmt
    narrow, fn_ = sf.convert(uw, dfmt, wide, rnd)
    return narrow, (fw | fn_)


__all__ = [
    "FORMATOF_FNS", "FORMATOF_ARITY", "FORMATOF_SHORT", "FORMATOF_IMPL",
    "FN_FO_ADD", "FN_FO_SUB", "FN_FO_MUL", "FN_FO_DIV", "FN_FO_SQRT",
    "FN_FO_FMA",
    "fo_add", "fo_sub", "fo_mul", "fo_div", "fo_sqrt", "fo_fma",
    "compute", "compare", "double_rounding_witness", "composed_route",
    "FORMATS",
]
