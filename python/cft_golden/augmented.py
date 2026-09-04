# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""The augmented arithmetic operations, IEEE 754-2019 clause 9.5.

augmentedAddition, augmentedSubtraction and augmentedMultiplication:
three operations that each return a PAIR (r, e) - the operation
rounded, and the error that rounding made - so that the pair together
carries the exact result the format alone cannot hold.

This module is the definition of correct for those bits, on the same
terms softfloat.py is for everything else: exact Python integers, no
floats, no mpmath. Everything below quotes the standard where the
choice is load-bearing, because 9.5 is the subclause implementations
most often approximate.

WHAT IS DIFFERENT ABOUT THESE THREE

1. They take NO rounding-direction attribute. 9.5 fixes the rounding
   itself: "This standard specifies a single rounding direction to be
   used in the operations in this subclause, defined as
   roundTiesTowardZero: the floating-point number nearest to the
   infinitely precise result shall be delivered; if the two nearest
   floating-point numbers bracketing an unrepresentable infinitely
   precise result are equally near, the one with smaller magnitude
   shall be delivered."

   That rule is not one of 4.3's five attributes and this contract does
   not add a sixth attribute for it: softfloat.round_pack learns it as
   an internal rounding DIRECTION (RND_RTTZ), reachable from here and
   from nowhere a caller can steer.

2. Overflow still goes to infinity. "However, an infinitely precise
   result with magnitude greater than b^emax x (b - 1/2 b^(1-p)) shall
   round to infinity with no change in sign ... Thus,
   roundTiesTowardZero carries all overflows (see 7.4) to infinity with
   the sign of the intermediate result. An infinitely precise result
   with magnitude equal to b^emax x (b - 1/2 b^(1-p)) shall round to
   b^emax x (b - b^(1-p)) with no change in sign."

   For radix 2 that threshold is 2^(emax+1) - 2^(emax-p), the midpoint
   between the largest finite and 2^(emax+1); AT the midpoint the tie
   rule applies and delivers the largest finite, ABOVE it the result
   overflows to an infinity. Both halves are exercised by the vector
   pools, and the first raises NOTHING - see the flags below.

3. The flags are not the flags of an ordinary operation. Under default
   exception handling 9.5 says, for each of the three, that "the
   operation signals inexact ONLY when roundTiesTowardZero(x + y)
   overflows; the operation's subnormal and zero results are exact",
   and separately that "if x + y - roundTiesTowardZero(x + y) is
   non-zero and lies strictly between +-b^emin, the underflow exception
   shall be signaled".

   So underflow here is a statement about the ERROR TERM being
   subnormal, and it is raised even though that error term is EXACT -
   which is the one place in this contract where underflow appears
   without inexact. The tininess convention of 7.5 (after rounding,
   docs/DETERMINISM.md) is untouched and simply does not decide this
   case: round_pack's own underflow bit is not what these operations
   report, because 9.5 names the condition itself.

   The one exception is augmentedMultiplication's non-representable
   residual, below, which raises underflow AND inexact.

WHY THE ERROR TERM IS REPRESENTABLE

For addition and subtraction, always (when r is finite). Both operands
are integer multiples of the format's smallest quantum 2^(emin-p+1), so
the exact sum is one too, and so is e = s - r. Its magnitude is at most
half an ulp of r, so it needs at most p significant bits: for a normal
r, |e| <= 2^(er-p) whose quantum-count is bounded by 2^p at the coarser
of the two operands' quanta; for a subnormal r the grid is the fixed
minimum quantum and e is a multiple of it by the same argument. 9.5
states the result rather than the proof - it gives augmentedAddition no
non-representable case at all, where augmentedMultiplication gets one -
and this module ASSERTS it (`_pack_exact` raises when round_pack calls
the pack inexact) rather than trusting it.

For multiplication it can fail, and 9.5 says exactly when and what to
deliver: "If x x y - roundTiesTowardZero(x x y) is finite and non-zero
and cannot be represented exactly in sourceFormat (because some
non-zero digits lie strictly between +-b^(emin-p+1)), the results are
roundTiesTowardZero(x x y) and the infinitely precise result of
x x y - roundTiesTowardZero(x x y) rounded to sourceFormat using
roundTiesTowardZero. Default exception handling raises the underflow
flag and signals the inexact exception in this case."

That is the ONLY case in which r + e is not exactly x op y, and it is
the case the identity test in python/tests/test_augmented.py excludes by
name rather than by tolerance.

SIGNS OF ZERO

Two different rules, and confusing them is the usual bug:

* An error term that is EXACTLY zero "is returned with the sign of
  roundTiesTowardZero(x + y)" - the sign of r, not of the arithmetic.
  So augmentedAddition(-3, 3) delivers (+0, +0) and
  augmentedAddition(-3, 0) delivers (-3, -0).
* An error term that is non-zero and ROUNDS to zero (multiplication
  only) keeps the sign of the exact residual, by 6.3's rule that a
  result "that is zero because of rounding takes the sign of the exact
  result". It is a rounded value, not a zero result.

r's own zero sign is the ordinary one: 6.3's cancellation rule for a
sum (+0 in every attribute except roundTowardNegative, and
roundTiesTowardZero is not that one), the operands' sign for like-signed
zeros, and the XOR of the signs for a product.
"""

from .formats import FpFormat
from . import softfloat as sf

#: The three operations, in the order the vector sets and the ABI use.
AUG_FNS = ("augmentedAddition", "augmentedSubtraction",
           "augmentedMultiplication")

FN_AUG_ADD, FN_AUG_SUB, FN_AUG_MUL = AUG_FNS


def _pack_exact(fmt: FpFormat, sign: int, m: int, e: int):
    """round_pack of a value the caller has PROVEN representable.

    Returns the bits. Raises if the pack was not exact, because at every
    call site here that would mean the representability argument in this
    module's docstring is wrong - which is a fact worth crashing over
    rather than absorbing into a flag.
    """
    bits, flags = sf.round_pack(fmt, sign, m, e, sf.RND_RTTZ)
    if flags:
        raise AssertionError(
            f"9.5 residual not representable: {fmt.name} sign={sign} "
            f"m={m:#x} e={e} packed with flags {flags:#x}")
    return bits


def _exact_pair(fmt: FpFormat, sign_t: int, t: int, e0: int, is_mul: bool):
    """The common tail: the exact non-zero result (-1)^sign_t * t * 2^e0
    of x op y, rounded to (r, e) with 9.5's flags.

    `t` is a positive integer and `e0` its binary weight, so the value
    is a dyadic rational held with no rounding anywhere above this line.
    `is_mul` selects the one behaviour that differs between the
    operations: whether a non-representable residual is a defined
    delivery (multiplication) or an impossibility (addition).
    """
    r_bits, r_flags = sf.round_pack(fmt, sign_t, t, e0, sf.RND_RTTZ)

    if r_flags & sf.FLAG_OVERFLOW:
        # "If roundTiesTowardZero(x + y) is infinite, both produced
        # results are the result of roundTiesTowardZero(x + y) and the
        # operation signals like addition(x, y) using
        # roundTiesTowardZero." Overflow to an infinity, per 7.4, with
        # inexact alongside it - and this is the only route by which
        # either of these operations raises inexact for the SUM.
        inf = sf.inf_bits(fmt, sign_t)
        return inf, inf, sf.FLAG_OVERFLOW | sf.FLAG_INEXACT

    # e = (x op y) - r, exactly. Both terms are dyadic rationals; put
    # them on the finer of the two grids and subtract as integers.
    ur = sf.unpack(fmt, r_bits)
    if ur.kind == sf.ZERO:
        rm, re = 0, e0
    else:
        rm, re = ur.m, ur.e
    q = min(e0, re)
    diff = (t << (e0 - q)) * (-1 if sign_t else 1) \
        - (rm << (re - q)) * (-1 if ur.sign else 1)

    if diff == 0:
        # "where if x + y - roundTiesTowardZero(x + y) equals zero, it
        # is returned with the sign of roundTiesTowardZero(x + y)"
        return r_bits, sf.zero_bits(fmt, ur.sign), 0

    sign_e = 1 if diff < 0 else 0
    mag = abs(diff)
    tiny = (q + mag.bit_length() - 1) < fmt.emin

    if not is_mul:
        # Addition and subtraction have no non-representable case: the
        # pack must be exact, and _pack_exact says so out loud.
        e_bits = _pack_exact(fmt, sign_e, mag, q)
        return r_bits, e_bits, (sf.FLAG_UNDERFLOW if tiny else 0)

    e_bits, e_flags = sf.round_pack(fmt, sign_e, mag, q, sf.RND_RTTZ)
    if e_flags & sf.FLAG_INEXACT:
        # The residual carried non-zero digits below the format's
        # smallest quantum: deliver it rounded, and raise both.
        # (Non-representable implies tiny - a value of p significant
        # bits at or above 2^emin sits on a grid the format has - so
        # this branch never contradicts the underflow test above.)
        assert tiny, "a non-representable product residual must be tiny"
        return r_bits, e_bits, sf.FLAG_UNDERFLOW | sf.FLAG_INEXACT
    return r_bits, e_bits, (sf.FLAG_UNDERFLOW if tiny else 0)


def _specials(fmt: FpFormat, ua, ub, invalid: bool):
    """The pair for a case decided by operand class, or None.

    9.5: "The operation propagates a NaN as both results if any input is
    a NaN (see 6.2.3)" - propagation here meaning this contract's
    canonical quiet NaN, the standing deviation documented in
    docs/DETERMINISM.md - and "If the operation signals the invalid
    operation exception, it produces the same quiet NaN for both
    outputs".
    """
    if sf.NAN in (ua.kind, ub.kind):
        q = sf.qnan_bits(fmt)
        signaling = any(u.kind == sf.NAN and u.signaling for u in (ua, ub))
        return q, q, (sf.FLAG_INVALID if signaling else 0)
    if invalid:
        q = sf.qnan_bits(fmt)
        return q, q, sf.FLAG_INVALID
    return None


def augmented_add(fmt: FpFormat, xa: int, xb: int):
    """(r_bits, e_bits, flags) of augmentedAddition(x, y), 754-2019 9.5.

    r is x + y rounded with roundTiesTowardZero and e is the exact
    residual x + y - r, which is always representable when r is finite.
    No rounding attribute is taken because the standard fixes the
    rounding.
    """
    ua, ub = sf.unpack(fmt, xa), sf.unpack(fmt, xb)

    invalid = (ua.kind == sf.INF and ub.kind == sf.INF and
               ua.sign != ub.sign)                       # inf + (-inf)
    special = _specials(fmt, ua, ub, invalid)
    if special is not None:
        return special

    if ua.kind == sf.INF or ub.kind == sf.INF:
        # An infinite r that is not an overflow: 9.5 gives both results
        # the same infinity, and addition of an infinity signals nothing.
        inf = sf.inf_bits(fmt, ua.sign if ua.kind == sf.INF else ub.sign)
        return inf, inf, 0

    if ua.kind == sf.ZERO and ub.kind == sf.ZERO:
        # 6.3: like-signed zeros keep their sign; an exact cancellation
        # is +0 in every attribute except roundTowardNegative, and
        # roundTiesTowardZero is not that one.
        rs = ua.sign if ua.sign == ub.sign else 0
        z = sf.zero_bits(fmt, rs)
        return z, z, 0
    if ua.kind == sf.ZERO or ub.kind == sf.ZERO:
        r_bits = xb if ua.kind == sf.ZERO else xa
        # x + 0 is x exactly, so the residual is a zero with r's sign.
        return r_bits, sf.zero_bits(fmt, r_bits >> (fmt.width - 1)), 0

    e0 = min(ua.e, ub.e)
    t = (ua.m << (ua.e - e0)) * (-1 if ua.sign else 1) \
        + (ub.m << (ub.e - e0)) * (-1 if ub.sign else 1)
    if t == 0:
        z = sf.zero_bits(fmt, 0)              # 6.3 exact cancellation
        return z, z, 0
    return _exact_pair(fmt, 1 if t < 0 else 0, abs(t), e0, is_mul=False)


def augmented_sub(fmt: FpFormat, xa: int, xb: int):
    """(r_bits, e_bits, flags) of augmentedSubtraction(x, y), 9.5.

    x - y is x + (-y) with every rule of augmentedAddition, the signed
    zeros included: augmentedSubtraction(+0, +0) is (+0, +0) because the
    negation makes it +0 + -0, an exact cancellation.
    """
    return augmented_add(fmt, xa, sf.negate(fmt, xb))


def augmented_mul(fmt: FpFormat, xa: int, xb: int):
    """(r_bits, e_bits, flags) of augmentedMultiplication(x, y), 9.5.

    r is x * y rounded with roundTiesTowardZero; e is the exact residual
    when the format can hold it, and otherwise that residual rounded the
    same way, with underflow and inexact raised. The exact product of
    two p-bit significands is 2p bits, so nothing above the final pack
    rounds.
    """
    ua, ub = sf.unpack(fmt, xa), sf.unpack(fmt, xb)

    invalid = ((ua.kind == sf.INF and ub.kind == sf.ZERO) or
               (ua.kind == sf.ZERO and ub.kind == sf.INF))   # inf * 0
    special = _specials(fmt, ua, ub, invalid)
    if special is not None:
        return special

    sp = ua.sign ^ ub.sign
    if sf.INF in (ua.kind, ub.kind):
        inf = sf.inf_bits(fmt, sp)
        return inf, inf, 0
    if sf.ZERO in (ua.kind, ub.kind):
        z = sf.zero_bits(fmt, sp)             # 6.3: the XOR sign
        return z, z, 0

    return _exact_pair(fmt, sp, ua.m * ub.m, ua.e + ub.e, is_mul=True)


AUG_IMPL = {
    FN_AUG_ADD: augmented_add,
    FN_AUG_SUB: augmented_sub,
    FN_AUG_MUL: augmented_mul,
}


def compute(fmt: FpFormat, fn: str, xa: int, xb: int):
    """(r_bits, e_bits, flags) of one augmented operation by name - the
    dispatch the vector generator and the conformance sets use."""
    try:
        impl = AUG_IMPL[fn]
    except KeyError:
        raise ValueError(f"unknown augmented operation {fn!r}") from None
    return impl(fmt, xa, xb)


def exact_value(fmt: FpFormat, bits: int):
    """The exact value of a finite encoding as a Fraction-free pair
    (numerator, exponent) - (m, e) with value m * 2^e, m signed.

    Used by the identity checks: r + e == x + y and r + e == x * y are
    statements about exact dyadic rationals, and this keeps them in
    integers rather than routing them through anything that rounds.
    """
    u = sf.unpack(fmt, bits)
    if u.kind in (sf.INF, sf.NAN):
        raise ValueError("not finite")
    if u.kind == sf.ZERO:
        return 0, 0
    return (-u.m if u.sign else u.m), u.e
