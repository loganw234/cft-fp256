# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""The phase-1 transcendental set, correctly rounded: the definition.

exp, expm1, exp2, log, log1p, log2, log10, pow and hypot, at all four
rungs of the interchange ladder, under all five rounding-direction
attributes, with the IEEE 754-2019 clause 9.2 special-value tables and
the contract's exact flags. Every bit this module returns is what
host/src/transcend.c must return; the vector sets are generated from
here and host/tests/transcend_check.py replays the C against it.

WHY THIS FILE IS NOT softfloat.py. That module states, and keeps, a
rule: integers only, no floats, no mpmath - because every result it
defines is a rational number and Python evaluates rationals exactly.
A transcendental function's value is NOT a rational number, so no
amount of integer arithmetic writes it down. Two things follow, and
they are the whole design:

  * The EXACT cases are decided by exact integer arithmetic, never by
    a tolerance. exp is exact only at 0; log only at 1; exp2 only at
    an integer argument; log2 only at a power of two; log10 only at a
    representable power of ten; pow exactly when the true value is a
    dyadic rational (integer exponents by integer powers, dyadic
    exponents by exact integer root extraction); hypot exactly when
    x^2 + y^2 is a perfect square in the dyadic rationals. Those
    decisions are proofs, and they are what makes the inexact flag
    trustworthy - an "exact" decided by comparing against a rounded
    reconstruction is a tolerance wearing a proof's clothes.

  * Everything else is decided by a RIGOROUS ENCLOSURE. mpmath's
    interval context (mpmath.iv) evaluates with outward-directed
    rounding, so the true value provably lies between the two
    endpoints. The rounding is accepted only when BOTH endpoints round
    to the same bits and the same flags under the requested attribute;
    otherwise the working precision is raised and the enclosure is
    recomputed. That is Ziv's strategy with the guesswork removed:
    the answer is never "mpmath said so", it is "no real number in an
    interval that contains the true value rounds any other way".

    Rounding under every attribute is monotone in the value, and so are
    tininess and the overflow test, so agreement at the endpoints IS
    agreement everywhere between them.

WHY THE LOOP TERMINATES. A Ziv loop hangs exactly when the true value
sits ON a rounding boundary - a grid point or a midpoint of the
format. Every such boundary is a dyadic rational, so the loop can only
hang where the true value is one. For exp/expm1/log/log1p that never
happens away from the exact cases (Lindemann-Weierstrass: the
exponential of a nonzero algebraic number, and the logarithm of a
positive rational other than 1, are transcendental); for exp2/log2/
log10 the rational values are exactly the ones the exact-case tests
already catch; and for pow and hypot the dyadic values are enumerated
and computed exactly BEFORE the loop is entered. The bound that makes
that enumeration finite is the same one for both: a dyadic value whose
odd part needs more than p+1 bits cannot be a grid point or a midpoint
of a p-bit format, so it cannot be a boundary, so the loop decides it.

Three families of input are decided WITHOUT an enclosure for a
different reason - not because the value is exact, but because it is
provably nearer to a representable neighbour than any working
precision could ever separate it from: exp of a tiny argument, expm1
and log1p of one, pow with a base near one, and hypot with a dominant
operand. _round_neighbour is where that lives, and it is the reason
this module terminates on inputs a naive Ziv loop runs forever on.

The cap on the escalation is therefore a backstop against a mistake in
the reasoning above, not a part of the algorithm - and it is loud:
reaching it raises ZivEscalation rather than returning a plausible
number. docs/TRANSCENDENTALS.md carries the arithmetic on how far the
cap sits from anything the input space can reach.
"""

from .formats import FpFormat
from .softfloat import (
    FLAG_DIVZERO, FLAG_INEXACT, FLAG_INVALID, INF, NAN,
    RND_MODES, RND_RNE, ZERO, inf_bits, one_bits, qnan_bits, round_pack,
    unpack, zero_bits,
)

# ---- the operation set ----------------------------------------------

FN_EXP = "exp"
FN_EXPM1 = "expm1"
FN_EXP2 = "exp2"
FN_LOG = "log"
FN_LOG1P = "log1p"
FN_LOG2 = "log2"
FN_LOG10 = "log10"
FN_POW = "pow"
FN_HYPOT = "hypot"

#: Canonical order - the ABI's, the vector sets', the docs'. Phase 1's
#: nine first, then phase 2's eleven, then phase 3's nine, and the order
#: never changes: a vector set names its function, but transcend.h's
#: enum, cft_tr_name and this tuple are one list in three languages.
TRANSCEND_FNS = (FN_EXP, FN_EXPM1, FN_EXP2, FN_LOG, FN_LOG1P, FN_LOG2,
                 FN_LOG10, FN_POW, FN_HYPOT,
                 "sinpi", "cospi", "tanpi", "asin", "acos", "atan",
                 "atan2", "asinpi", "acospi", "atanpi", "atan2pi",
                 "sin", "cos", "tan",
                 "sinh", "cosh", "tanh", "asinh", "acosh", "atanh",
                 "exp2m1", "exp10", "exp10m1", "log2p1", "log10p1",
                 "rsqrt", "pown", "powr", "compound", "rootn")

#: How many FLOATING-POINT operands each reads.
TRANSCEND_ARITY = {fn: (2 if fn in (FN_POW, FN_HYPOT, "atan2", "atan2pi",
                                    "powr")
                        else 1)
                   for fn in TRANSCEND_FNS}

#: Which of them read an INTEGER second operand beside the float one.
#: 754-2019 9.2.1 asks for exactly that - "n is a finite integral value
#: in integralFormat" - so these three take a Python int here and an
#: int64_t array in the C, rather than a floating operand that would
#: have to be asked whether it is integral.
TRANSCEND_INTARG = {fn: fn in ("pown", "compound", "rootn")
                    for fn in TRANSCEND_FNS}


class ZivEscalation(Exception):
    """The enclosure never decided the rounding within the cap.

    Raised, never swallowed: a transcendental that cannot be shown
    correctly rounded is not one this library returns.
    """


#: Instrumentation, so "how deep did it ever go" is a measurement.
STATS = {"ziv_calls": 0, "escalations": 0, "max_prec": 0, "exact": 0,
         "neighbour": 0}


def reset_stats():
    for k in STATS:
        STATS[k] = 0


# ---- working-precision schedule --------------------------------------
#
# The first attempt carries 2p + 40 bits, which decides every input
# that is not adversarially close to a boundary. Each escalation
# doubles, and the last attempt is made AT the cap, so the cap is a
# precision that was actually tried rather than one that was skipped
# past.
#
# The cap is min(8p + 128, 832). 832 is the ceiling the C port's fixed
# 2048-bit integer container imposes once a product of two working
# significands plus the argument-reduction headroom has to fit
# (docs/TRANSCENDENTALS.md does that arithmetic), and the model uses
# the same number so that both implementations give up in the same
# place instead of disagreeing quietly about which inputs are
# answerable.

PREC_CAP_CEILING = 832


#: Lower the FIRST attempt's precision, for tests only. The escalation
#: path decides nothing on its own - a rounding accepted at 2p+40 bits
#: is accepted at any higher precision too, because the enclosure only
#: narrows - so forcing the loop to start below what it needs must not
#: move a single result bit. It is set by python/tests/test_transcend.py
#: (and, on the C side, by CFT_TRANSCEND_MINPREC) because a path never
#: taken is a path never tested, and in ordinary use this loop never
#: escalates at all.
START_PREC_OVERRIDE = 0


def start_prec(fmt: FpFormat) -> int:
    if START_PREC_OVERRIDE:
        return max(64, fmt.prec // 2,
                   min(START_PREC_OVERRIDE, prec_cap(fmt)))
    return 2 * fmt.prec + 40


def prec_cap(fmt: FpFormat) -> int:
    return min(8 * fmt.prec + 128, PREC_CAP_CEILING)


def _prec_schedule(fmt: FpFormat):
    cap = prec_cap(fmt)
    w = start_prec(fmt)
    while w < cap:
        yield w
        w = min(2 * w, cap)
    yield cap


# ---- small exact helpers ---------------------------------------------

def _odd_part(n: int):
    """(odd, shift) with n == odd << shift, for n > 0."""
    shift = (n & -n).bit_length() - 1
    return n >> shift, shift


def _dyadic(u):
    """(M, E) with |value| == M * 2^E and M ODD, for a finite nonzero
    unpacked operand. The canonical form every exactness test below is
    stated in."""
    m, s = _odd_part(u.m)
    return m, u.e + s


def _vexp(u):
    """floor(log2 |value|) for a finite nonzero operand."""
    return u.e + u.m.bit_length() - 1


def _nan_out(fmt, *ops):
    invalid = any(u.kind == NAN and u.signaling for u in ops)
    return qnan_bits(fmt), (FLAG_INVALID if invalid else 0)


def _has_snan(*ops):
    return any(u.kind == NAN and u.signaling for u in ops)


# ---- the roundings that are not a Ziv loop ---------------------------

def _round_exact(fmt, sign, m, e, rnd):
    """Round an exactly-known nonzero dyadic magnitude m * 2^e.

    round_pack is the library's single rounding authority and already
    delivers the whole of clause 7 - the overflow response table per
    attribute, tininess after rounding, underflow only when tiny AND
    inexact. An exact case therefore needs no special flag handling: a
    representable value packs with no flags at all, and one that is not
    representable gets exactly the flags any other inexact result
    would."""
    return round_pack(fmt, sign, m, e, rnd)


def _round_neighbour(fmt, ubits, away, rnd):
    """Round a value lying strictly between the representable u and the
    midpoint on one side of it.

    `away` selects the side: 1 when the true value is farther from zero
    than u, 0 when it is nearer. Every value strictly inside that half
    of the gap rounds identically under all five attributes - to u,
    except in the one directed attribute that points across the gap -
    so a WITNESS placed an eighth of a gap from u answers for all of
    them, and round_pack derives the flags (inexact always; underflow
    when the landing is tiny; the overflow response when u is the
    largest finite and the attribute steps past it).

    This is what makes exp(x) for a tiny x, expm1 and log1p of one, pow
    of a base near one, and hypot with a dominant operand decidable AT
    ALL: their true values are closer to a representable number than
    any working precision could resolve, so an enclosure would never
    separate them. The separation is not needed - the side is known
    exactly, and the side is the whole answer."""
    u = unpack(fmt, ubits)
    STATS["neighbour"] += 1
    if away:
        return round_pack(fmt, u.sign, 8 * u.m + 1, u.e - 3, rnd)
    assert u.m > 0, "no neighbour below zero"
    return round_pack(fmt, u.sign, 8 * u.m - 1, u.e - 3, rnd)


def _round_overflowing(fmt, sign, rnd):
    """A value provably above every finite magnitude: 3 * 2^emax is
    one, and round_pack turns it into this attribute's overflow
    response with overflow and inexact raised."""
    return round_pack(fmt, sign, 3, fmt.emax, rnd)


def _round_underflowing(fmt, sign, rnd):
    """A value provably nonzero and below half the smallest subnormal:
    a quarter of that subnormal is one, and it rounds to zero in four
    attributes and to the subnormal in the fifth, with underflow and
    inexact."""
    return round_pack(fmt, sign, 1, fmt.emin - fmt.man_w - 2, rnd)


# ---- the enclosure ---------------------------------------------------

def _iv():
    try:
        from mpmath import iv
    except ImportError as exc:      # pragma: no cover - environment
        raise ZivEscalation(
            "mpmath is required to evaluate the transcendental "
            "reference (the exact cases and the special values do not "
            "need it; a rigorous enclosure does)") from exc
    return iv


#: Units in the last place of the WORKING precision by which each
#: enclosure endpoint is moved outward before it is trusted.
#:
#: mpmath's interval context is documented as rigorous and is not,
#: quite: measured on 2026-09-02, at 514 bits
#:
#:     iv.power(1 + 2^-236, -(1 + 2^-236))
#:
#: returns the DEGENERATE interval [g, g] at g = 1 - 2^-236, while the
#: true value is g + 2^-709 - so the "enclosure" excludes the value it
#: is supposed to contain, by rather less than one unit in the last
#: place. Both iv.power and iv.exp(y*iv.log(x)) do it, so it is the
#: underlying mpf_exp/mpf_log directed rounding rather than the
#: interval layer. Left alone that costs a wrong last bit of pow under
#: roundTowardPositive, which is exactly the failure this module
#: exists to make impossible.
#:
#: So every endpoint is moved outward by 256 units of the working
#: precision before it is believed. mpmath's own accuracy claim for
#: these functions is a few ulps, so the margin is roughly a hundredfold
#: what it needs to be; it costs eight bits of working precision, which
#: the 40 bits of guard in the schedule absorb, and it cannot cost
#: correctness, because a too-wide enclosure escalates and a too-narrow
#: one lies. The independent checks - GNU MPFR, and libcft's own
#: error-tracked evaluator, which shares none of this code - are what
#: say the margin is enough in practice.
ENCLOSURE_MARGIN_ULPS = 256


def _endpoint(tup, prec, outward):
    """One raw mpmath endpoint as an exact (man, exp), moved outward by
    ENCLOSURE_MARGIN_ULPS units of `prec`. Returns None when the
    endpoint is not a finite positive number, or when the widening
    reaches zero."""
    sign, man, exp, _bc = tup
    man = int(man)
    exp = int(exp)
    if man == 0 or sign:
        return None
    vexp = man.bit_length() + exp - 1              # floor(log2 value)
    e_new = vexp - prec - 8
    shift = exp - e_new
    if shift < 0:                                  # already coarser
        return man, exp
    m = (man << shift) + (outward << 16)
    if m <= 0:
        return None
    return m, e_new


def _ziv(fmt, sign, evaluate, rnd):
    """Correctly round a positive real value given as an enclosure.

    `evaluate(iv)` returns an mpmath interval CONTAINING the true
    magnitude. The rounding is accepted only when both endpoints round
    to the same bits and the same flags; inexact is then forced,
    because the caller has already proved the value is not
    representable - that is what the exact-case tests are for.
    """
    iv = _iv()
    saved = iv.prec
    STATS["ziv_calls"] += 1
    prec = 0
    try:
        for i, prec in enumerate(_prec_schedule(fmt)):
            if i:
                STATS["escalations"] += 1
            STATS["max_prec"] = max(STATS["max_prec"], prec)
            iv.prec = prec
            lo_t, hi_t = evaluate(iv)._mpi_
            lo = _endpoint(lo_t, prec, -1)
            hi = _endpoint(hi_t, prec, +1)
            if lo is None or hi is None:
                continue                        # straddles zero: sharpen
            blo = round_pack(fmt, sign, lo[0], lo[1], rnd)
            bhi = round_pack(fmt, sign, hi[0], hi[1], rnd)
            if blo == bhi:
                bits, flags = blo
                return bits, flags | FLAG_INEXACT
        raise ZivEscalation(
            f"{fmt.name}: the enclosure still did not decide the "
            f"rounding at {prec} bits of working precision. Either an "
            "exact case was missed above, or this input is the hard "
            "case the cap was sized to exclude; either way the correct "
            "answer is a refusal, not a guess.")
    finally:
        iv.prec = saved


# ---- exact-case machinery --------------------------------------------

def _pow_dyadic(fmt, ux, uy):
    """|x| ** y as an exact (m, e) with |x|**y == m * 2^e, or None when
    no such dyadic rational exists with an odd part small enough to be
    a rounding boundary.

    None is a PROOF, not a shrug: |x|**y is then either irrational, or
    a rational that is not dyadic, or a dyadic whose odd part needs
    more than p+1 bits. None of those can be a grid point or a midpoint
    of a p-bit format, so the enclosure decides it in finite time.

    x finite, positive, nonzero and not 1; y finite and nonzero.
    """
    p = fmt.prec
    M, E = _dyadic(ux)                      # |x| = M * 2^E, M odd
    Y, F = _dyadic(uy)                      # |y| = Y * 2^F, Y odd
    yneg = uy.sign

    if F >= 0:
        # y is an integer. Its magnitude may be astronomical, which is
        # fine: a base whose odd part is anything but 1 loses the race
        # after p+1 multiplications, and a base of 1 is a pure shift.
        if M == 1:
            n = Y << F
            return 1, E * (-n if yneg else n)
        if yneg:
            return None                     # 1/(odd > 1): not dyadic
        n = Y << F
        if n > p + 1:
            return None                     # odd part outruns p+1 bits
        m = M ** n
        if m.bit_length() > p + 1:
            return None
        return m, E * n

    # y is not an integer: y = +-Y / 2^k with Y odd, so |x|**y is
    # rational only if |x| is an exact 2^k-th power (Y odd forces every
    # prime exponent of M, and E, to be divisible by 2^k).
    k = -F
    if k > 24:
        # 2^k then exceeds both the widest odd part on this ladder and
        # the widest |E|, so only M == 1 with E == 0 could pass - and
        # that is x == 1, which the caller has already answered.
        return None
    if E % (1 << k):
        return None
    if M == 1:
        root = 1
    else:
        root = _exact_2k_root(M, k)
        if root is None:
            return None
    if root == 1:
        return 1, (E >> k) * (-Y if yneg else Y)
    if yneg:
        return None
    if Y > p + 1:
        return None
    m = root ** Y
    if m.bit_length() > p + 1:
        return None
    return m, (E >> k) * Y


def _exact_2k_root(M, k):
    """The exact 2^k-th root of the odd M > 1, or None. k successive
    integer square roots, each verified - no floating point and no
    tolerance."""
    from math import isqrt
    r = M
    for _ in range(k):
        s = isqrt(r)
        if s * s != r:
            return None
        r = s
    return r


def _hypot_dyadic(fmt, ux, uy):
    """sqrt(x^2 + y^2) exactly as (m, e), or None when it is not a
    dyadic rational with an odd part inside p+1 bits.

    The span screen is the finiteness argument. x^2 and y^2 have odd
    significands, so their sum loses at most one low bit to carries
    (and only when the two square exactly the same power of two): a
    pair whose set bits span more than p+6 places therefore squares to
    a sum whose odd part is wider than 2p+2 bits, whose square root -
    if it has one - has an odd part wider than p+1 bits, which cannot
    be a rounding boundary."""
    from math import isqrt
    p = fmt.prec
    mx, ex = ux.m, ux.e
    my, ey = uy.m, uy.e
    top = max(ex + mx.bit_length(), ey + my.bit_length())
    bot = min(ex + (mx & -mx).bit_length() - 1,
              ey + (my & -my).bit_length() - 1)
    if top - bot > p + 6:
        return None
    e0 = 2 * min(ex, ey)
    s = ((mx * mx) << (2 * ex - e0)) + ((my * my) << (2 * ey - e0))
    odd, sh = _odd_part(s)
    total = e0 + sh
    if total % 2:
        return None
    r = isqrt(odd)
    if r * r != odd:
        return None
    if r.bit_length() > p + 1:
        return None
    return r, total // 2


def _pow_of_ten(fmt, u):
    """k with |x| == 10^k exactly, or None. 10^k is a dyadic rational
    only for k >= 0, and then its odd part is 5^k - so the test is one
    exact comparison, bounded by 5^k < 2^p."""
    M, E = _dyadic(u)
    if E < 0 or E > fmt.prec:
        return None
    if M != 5 ** E:
        return None
    return E


# ---- the range screens -----------------------------------------------
#
# They exist so nothing downstream is ever asked for exp of 2^262143.
# Each is a one-sided enclosure test at low precision: it fires only
# when the enclosure PROVES the result is past the format's thresholds
# and falls through to the ordinary path otherwise. Falling through is
# always safe; firing wrongly would not be, which is why the test is on
# an enclosure and not on a float.

# The screen's precision is p + 32 rather than something small, and
# the reason is worth stating: _exact_value_iv builds the operand by
# handing its integer significand to the interval context, which is
# exact only while the context carries at least p bits. A screen run
# at 96 bits would enclose the function of a ROUNDED operand - a
# correct answer to the wrong question, and one that could fire the
# overflow branch for an input that does not overflow.
def _screen_prec(fmt):
    return fmt.prec + 32


def _bounds(fmt, evaluate):
    """(lo, hi) of a screening enclosure, as mpmath endpoints."""
    iv = _iv()
    saved = iv.prec
    try:
        iv.prec = _screen_prec(fmt)
        enc = evaluate(iv)
        return enc.a, enc.b
    finally:
        iv.prec = saved


def _screen_exponent(fmt, log2_of_result, sign, rnd):
    """The overflow or underflow response when the base-two logarithm
    of the result is provably outside the format, else None.

    The thresholds carry a whole unit of slack past what they need -
    emax + 2 rather than emax + 1, emin - man_w - 2 rather than - 1 -
    so that mpmath's few-ulp accuracy cannot reach them. Underflow
    therefore fires only well below half the smallest subnormal, and
    the tie at that half is never decided here."""
    lo, hi = _bounds(fmt, log2_of_result)
    if lo > fmt.emax + 2:
        return _round_overflowing(fmt, sign, rnd)
    if hi < fmt.emin - fmt.man_w - 2:
        return _round_underflowing(fmt, sign, rnd)
    return None


# =====================================================================
# The nine operations
# =====================================================================

def exp(fmt: FpFormat, xa: int, rnd: int = RND_RNE):
    """exp(x), correctly rounded. 754-2019 9.2: exp(+-0) is 1,
    exp(+inf) is +inf, exp(-inf) is +0, and 0 is the only exact
    argument."""
    return _exp_family(fmt, xa, rnd, base_two=False, minus_one=False)


def exp2(fmt: FpFormat, xa: int, rnd: int = RND_RNE):
    """2**x, correctly rounded. Exact exactly when x is an integer;
    round_pack then decides whether that power is representable, too
    large or too small, with the flags each of those carries."""
    return _exp_family(fmt, xa, rnd, base_two=True, minus_one=False)


def expm1(fmt: FpFormat, xa: int, rnd: int = RND_RNE):
    """exp(x) - 1, correctly rounded. expm1(+-0) is +-0 - the sign is
    the operand's, which is half the reason this function exists -
    expm1(-inf) is -1 exactly, expm1(+inf) is +inf."""
    return _exp_family(fmt, xa, rnd, base_two=False, minus_one=True)


def _exp_family(fmt, xa, rnd, base_two, minus_one):
    u = unpack(fmt, xa)
    p = fmt.prec

    if u.kind == NAN:
        return _nan_out(fmt, u)
    if u.kind == INF:
        if u.sign:
            if minus_one:
                return one_bits(fmt, 1), 0          # expm1(-inf) = -1
            return zero_bits(fmt, 0), 0             # exp(-inf) = +0
        return inf_bits(fmt, 0), 0
    if u.kind == ZERO:
        STATS["exact"] += 1
        if minus_one:
            return xa, 0                            # expm1(+-0) = +-0
        return one_bits(fmt, 0), 0                  # exp(+-0), exp2(+-0)

    # exp2 of an integer is this family's only exact case beyond zero,
    # and it is decided on the encoding: a finite value is an integer
    # exactly when its odd part's exponent is not negative.
    if base_two:
        M, E = _dyadic(u)
        if E >= 0:
            n = M << E
            if u.sign:
                n = -n
            STATS["exact"] += 1
            if n > fmt.emax:
                return _round_overflowing(fmt, 0, rnd)
            if n < fmt.emin - fmt.man_w:
                return _round_underflowing(fmt, 0, rnd)
            return _round_exact(fmt, 0, 1, n, rnd)

    # An argument so small that no working precision separates the
    # result from its neighbour - decided by side. exp2 rides the same
    # threshold because |x ln2| < |x|.
    ex = _vexp(u)
    if minus_one:
        if ex <= -(p + 3):
            # expm1(x) - x = x^2/2 + ... > 0 for every x in (-1, 1),
            # so the true value is always on the +x side of x.
            return _round_neighbour(fmt, xa, away=(u.sign == 0), rnd=rnd)
    elif ex <= -(p + 4):
        # exp(x) - 1 has the sign of x, and |exp(x) - 1| < 1.01|x|.
        return _round_neighbour(fmt, one_bits(fmt, 0), away=(u.sign == 0),
                                rnd=rnd)

    val = _exact_value_iv(fmt, xa)
    sign = 1 if (minus_one and u.sign) else 0

    def log2_of_exp(iv):
        x = val(iv)
        return x if base_two else x / iv.log(2)

    if minus_one:
        lo, hi = _bounds(fmt, log2_of_exp)
        if lo > fmt.emax + 2:
            return _round_overflowing(fmt, 0, rnd)
        if hi < -(p + 3):
            # exp(x) is below 2^-(p+2), so expm1(x) sits that far above
            # -1 and no working precision separates the two.
            return _round_neighbour(fmt, one_bits(fmt, 1), away=0, rnd=rnd)
    else:
        screened = _screen_exponent(fmt, log2_of_exp, sign, rnd)
        if screened is not None:
            return screened

    def evaluate(iv):
        x = val(iv)
        if base_two:
            return iv.power(2, x)
        if minus_one:
            y = iv.expm1(x)
            return -y if u.sign else y
        return iv.exp(x)

    return _ziv(fmt, sign, evaluate, rnd)


def log(fmt: FpFormat, xa: int, rnd: int = RND_RNE):
    """log(x), the natural logarithm. log(1) is +0 and is the only
    exact case; log(+-0) is -inf with divideByZero (754 7.3), a
    negative operand is invalid, log(+inf) is +inf."""
    return _log_family(fmt, xa, rnd, base=None)


def log2(fmt: FpFormat, xa: int, rnd: int = RND_RNE):
    """log2(x). Exact exactly at the powers of two, where the answer is
    an integer every format on this ladder holds exactly."""
    return _log_family(fmt, xa, rnd, base=2)


def log10(fmt: FpFormat, xa: int, rnd: int = RND_RNE):
    """log10(x). Exact exactly at the powers of ten the format
    represents - 10^k for k >= 0 with 5^k inside p bits; a negative
    power of ten is not a dyadic rational, so it is never an
    operand."""
    return _log_family(fmt, xa, rnd, base=10)


def _log_family(fmt, xa, rnd, base):
    u = unpack(fmt, xa)

    if u.kind == NAN:
        return _nan_out(fmt, u)
    if u.kind == ZERO:
        return inf_bits(fmt, 1), FLAG_DIVZERO
    if u.sign:
        return qnan_bits(fmt), FLAG_INVALID
    if u.kind == INF:
        return inf_bits(fmt, 0), 0

    M, E = _dyadic(u)
    if M == 1 and E == 0:                       # x == 1
        STATS["exact"] += 1
        return zero_bits(fmt, 0), 0
    if base == 2 and M == 1:                    # x is a power of two
        STATS["exact"] += 1
        return _round_exact(fmt, 1 if E < 0 else 0, abs(E), 0, rnd)
    if base == 10:
        k = _pow_of_ten(fmt, u)
        if k is not None:
            STATS["exact"] += 1
            return _round_exact(fmt, 0, k, 0, rnd)

    # The result's sign is the side of 1 the operand lies on, exactly.
    sign = 1 if _vexp(u) < 0 else 0
    val = _exact_value_iv(fmt, xa)

    def evaluate(iv):
        y = iv.log(val(iv))
        if base == 2:
            y = y / iv.log(2)
        elif base == 10:
            y = y / iv.log(10)
        return -y if sign else y

    return _ziv(fmt, sign, evaluate, rnd)


def log1p(fmt: FpFormat, xa: int, rnd: int = RND_RNE):
    """log(1 + x), correctly rounded. log1p(+-0) is +-0 (the sign
    survives, which is the other half of why these two functions
    exist), log1p(-1) is -inf with divideByZero, anything below -1 is
    invalid, log1p(+inf) is +inf and log1p(-inf) is invalid."""
    u = unpack(fmt, xa)
    p = fmt.prec

    if u.kind == NAN:
        return _nan_out(fmt, u)
    if u.kind == INF:
        if u.sign:
            return qnan_bits(fmt), FLAG_INVALID       # 1 + (-inf) < 0
        return inf_bits(fmt, 0), 0
    if u.kind == ZERO:
        STATS["exact"] += 1
        return xa, 0                                  # log1p(+-0) = +-0

    M, E = _dyadic(u)
    if u.sign and M == 1 and E == 0:                  # x == -1
        return inf_bits(fmt, 1), FLAG_DIVZERO
    if u.sign and _vexp(u) >= 0:                      # x < -1
        return qnan_bits(fmt), FLAG_INVALID

    if _vexp(u) <= -(p + 3):
        # log1p(x) - x = -x^2/2 + ... < 0 for every x in (-1, 1), so
        # the true value always lies on the -x side of x.
        return _round_neighbour(fmt, xa, away=(u.sign == 1), rnd=rnd)

    sign = u.sign
    val = _exact_value_iv(fmt, xa)

    def evaluate(iv):
        y = iv.log1p(val(iv))
        return -y if sign else y

    return _ziv(fmt, sign, evaluate, rnd)


def pow(fmt: FpFormat, xa: int, xb: int, rnd: int = RND_RNE):
    """x ** y, the 754-2019 `pow` - the one whose special cases follow
    C's: pow(x, +-0) is 1 for every x including a quiet NaN, pow(1, y)
    is 1 for every y including a quiet NaN, pow(-1, +-inf) is 1, a
    negative finite base with a non-integer exponent is invalid, and a
    zero base signals divideByZero for a negative exponent.

    A signaling NaN operand is NOT covered by those table entries - the
    standard's wording is "even a quiet NaN" - so it raises invalid and
    delivers the canonical quiet NaN, as everything else in this
    contract does.
    """
    ux, uy = unpack(fmt, xa), unpack(fmt, xb)

    if _has_snan(ux, uy):
        return qnan_bits(fmt), FLAG_INVALID

    # The two entries that outrank even a quiet NaN operand.
    if uy.kind == ZERO:
        return one_bits(fmt, 0), 0
    if ux.kind != NAN and _is_one(ux):
        return one_bits(fmt, 0), 0
    if ux.kind == NAN or uy.kind == NAN:
        return qnan_bits(fmt), 0

    # An infinite exponent first, so that pow(+-0, -inf) takes the
    # |x| < 1 row - which delivers +inf and, per C's own split of this
    # table, signals NOTHING: divideByZero is the pole at a FINITE
    # negative exponent, not the limit.
    if uy.kind == INF:
        if _is_one_mag(ux):                        # pow(-1, +-inf) = 1
            return one_bits(fmt, 0), 0
        if _mag_gt_one(ux) == (not uy.sign):
            return inf_bits(fmt, 0), 0
        return zero_bits(fmt, 0), 0

    y_int, y_odd = _integrality(uy)

    if ux.kind == ZERO:
        neg = ux.sign and y_odd
        if uy.sign:
            return inf_bits(fmt, 1 if neg else 0), FLAG_DIVZERO
        return zero_bits(fmt, 1 if neg else 0), 0

    if ux.kind == INF:
        neg = ux.sign and y_odd
        if uy.sign:
            return zero_bits(fmt, 1 if neg else 0), 0
        return inf_bits(fmt, 1 if neg else 0), 0

    if ux.sign and not y_int:
        return qnan_bits(fmt), FLAG_INVALID

    sign = 1 if (ux.sign and y_odd) else 0

    exact = _pow_dyadic(fmt, ux, uy)
    if exact is not None:
        m, e = exact
        STATS["exact"] += 1
        vexp = e + m.bit_length() - 1
        if vexp > fmt.emax:
            return _round_overflowing(fmt, sign, rnd)
        if vexp < fmt.emin - fmt.man_w - 1:
            return _round_underflowing(fmt, sign, rnd)
        return _round_exact(fmt, sign, m, e, rnd)

    valx = _exact_value_iv(fmt, xa)
    valy = _exact_value_iv(fmt, xb)

    def log_of_result(iv):
        return valy(iv) * iv.log(abs(valx(iv)))

    screened = _screen_exponent(fmt, lambda iv: log_of_result(iv) / iv.log(2),
                                sign, rnd)
    if screened is not None:
        return screened

    # A result that cannot be separated from 1: |y log x| below
    # 2^-(p+3) puts x**y strictly inside the half gap next to 1, on the
    # side the exact operand signs give.
    lo, hi = _bounds(fmt, lambda iv: abs(log_of_result(iv)))
    if hi < 2.0 ** -(fmt.prec + 3):
        up = (_mag_gt_one(ux) != bool(uy.sign))
        return _round_neighbour(fmt, one_bits(fmt, sign), away=up, rnd=rnd)

    def evaluate(iv):
        return iv.power(abs(valx(iv)), valy(iv))

    return _ziv(fmt, sign, evaluate, rnd)


def hypot(fmt: FpFormat, xa: int, xb: int, rnd: int = RND_RNE):
    """sqrt(x^2 + y^2) computed as if with unbounded range and rounded
    once. An infinite operand gives +inf even when the other is a quiet
    NaN (754-2019 9.2.1); a signaling NaN raises invalid and gives the
    canonical quiet NaN. The result is never negative, and is +0 only
    when both operands are zero."""
    ux, uy = unpack(fmt, xa), unpack(fmt, xb)

    if _has_snan(ux, uy):
        return qnan_bits(fmt), FLAG_INVALID
    if ux.kind == INF or uy.kind == INF:
        return inf_bits(fmt, 0), 0
    if ux.kind == NAN or uy.kind == NAN:
        return qnan_bits(fmt), 0
    if ux.kind == ZERO and uy.kind == ZERO:
        return zero_bits(fmt, 0), 0
    if ux.kind == ZERO:
        return xb & ~fmt.sign_mask, 0                 # |y|, exactly
    if uy.kind == ZERO:
        return xa & ~fmt.sign_mask, 0                 # |x|, exactly

    exact = _hypot_dyadic(fmt, ux, uy)
    if exact is not None:
        m, e = exact
        STATS["exact"] += 1
        vexp = e + m.bit_length() - 1
        if vexp > fmt.emax:
            return _round_overflowing(fmt, 0, rnd)
        return _round_exact(fmt, 0, m, e, rnd)

    # A dominant operand. sqrt(X^2+Y^2) - X < Y^2/(2X), so once
    # 2*esml + p + 2 < 2*ebig the excess is below a quarter of the gap
    # above the larger magnitude and the side (always up) decides it.
    big_is_x = _mag_ge(ux, uy)
    big, small = (ux, uy) if big_is_x else (uy, ux)
    if 2 * _vexp(small) + fmt.prec + 2 < 2 * _vexp(big):
        bits = (xa if big_is_x else xb) & ~fmt.sign_mask
        return _round_neighbour(fmt, bits, away=1, rnd=rnd)

    valx = _exact_value_iv(fmt, xa)
    valy = _exact_value_iv(fmt, xb)

    def evaluate(iv):
        x, y = valx(iv), valy(iv)
        return iv.sqrt(x * x + y * y)

    return _ziv(fmt, 0, evaluate, rnd)


# ---- operand helpers -------------------------------------------------

def _exact_value_iv(fmt, bits):
    """A callable returning the operand's EXACT value as a degenerate
    interval. Exactness matters: an operand rounded on the way in makes
    every result a correctly rounded answer to the wrong question."""
    u = unpack(fmt, bits)
    m, e, sign = u.m, u.e, u.sign

    def build(iv):
        v = iv.mpf(m)
        if e >= 0:
            v = v * iv.mpf(1 << e)
        else:
            v = v / iv.mpf(1 << -e)
        return -v if sign else v

    return build


def _is_one(u):
    return not u.sign and _is_one_mag(u)


def _is_one_mag(u):
    if u.kind in (ZERO, INF, NAN):
        return False
    m, e = _dyadic(u)
    return m == 1 and e == 0


def _mag_gt_one(u):
    if u.kind == INF:
        return True
    if u.kind == ZERO:
        return False
    return _vexp(u) >= 0 and not _is_one_mag(u)


def _mag_ge(ua, ub):
    if ua.kind == ZERO:
        return ub.kind == ZERO
    if ub.kind == ZERO:
        return True
    return (ua.m << max(0, ua.e - ub.e)) >= (ub.m << max(0, ub.e - ua.e))


def _integrality(u):
    """(is_integer, is_odd_integer) for a finite operand, decided on the
    encoding. Zero is an even integer; an infinity is neither and never
    reaches here."""
    if u.kind == ZERO:
        return True, False
    if u.kind in (INF, NAN):
        return False, False
    _m, e = _dyadic(u)
    return e >= 0, e == 0


# =====================================================================
# Phase 2: the trigonometric functions that need NO reduction against pi
#
# sinPi, cosPi, tanPi, asin, acos, atan, atan2, asinPi, acosPi, atanPi
# and atan2Pi. What they have in common is the thing phase 1's closing
# note said was missing: none of them needs pi to hundreds of thousands
# of bits.
#
#   * For the Pi-variants of the forward functions the reduction is
#     x mod 2, and x is a DYADIC RATIONAL, so the reduction is a mask
#     on the encoding and is exact at every magnitude. sinPi(2^262000)
#     is +0 by integer arithmetic, where sin(2^262000) would need the
#     reduction constant to a quarter of a million bits.
#   * The inverse functions take their argument in [-1, 1] (or a ratio),
#     so there is nothing to reduce at all; pi enters only as a factor
#     of the ANSWER, at one multiplication's worth of precision.
#
# Everything else is phase 1's: the same three-way split (exact cases,
# neighbour rules, enclosure), the same working-precision schedule, the
# same cap, the same loud refusal. docs/TRANSCENDENTALS.md carries the
# proofs; what is stated here is what each line rests on.
# =====================================================================

FN_SINPI = "sinpi"
FN_COSPI = "cospi"
FN_TANPI = "tanpi"
FN_ASIN = "asin"
FN_ACOS = "acos"
FN_ATAN = "atan"
FN_ATAN2 = "atan2"
FN_ASINPI = "asinpi"
FN_ACOSPI = "acospi"
FN_ATANPI = "atanpi"
FN_ATAN2PI = "atan2pi"

TRIG_FNS = (FN_SINPI, FN_COSPI, FN_TANPI, FN_ASIN, FN_ACOS, FN_ATAN,
            FN_ATAN2, FN_ASINPI, FN_ACOSPI, FN_ATANPI, FN_ATAN2PI)


# ---- the generalised neighbour witness -------------------------------

def _round_dyadic_side(fmt, sign, m, e, away, rnd):
    """Round a value known to lie strictly between the exact dyadic
    V = m * 2^e and V +- 2^(g-2), where 2^g is the format's grid step
    just above V - a quarter step, and half a step where V is a power
    of two and the true value is below it.

    _round_neighbour above needs V to be a REPRESENTABLE number, because
    it starts from an encoding. That is not enough for atan2: the value
    it must sit beside is the quotient y/x, which is exactly a dyadic
    rational whenever x's odd significand divides y's - and which can
    land on a subnormal MIDPOINT rather than on the grid (atan2(minSub,
    2) does exactly that). A midpoint is a rounding boundary like any
    other, and no working precision separates atan of it from it.

    The witness goes an eighth of a grid step from V on the named side.
    Every value strictly inside that quarter-step rounds identically
    under all five attributes - to V's own rounding when V is a grid
    point, and to the grid point on the witness's side when V is a
    midpoint - so the witness answers for the true value, and round_pack
    derives the flags.

    `away` = 1 when the true value is farther from zero than V.
    """
    assert m > 0
    STATS["neighbour"] += 1
    vexp = e + m.bit_length() - 1
    g = max(vexp - fmt.prec + 1, fmt.emin - fmt.man_w)   # log2 of the step
    assert e >= g - 3, (m, e, g)         # V is on the eighth-step grid
    n = m << (e - g + 3)
    return round_pack(fmt, sign, n + 1 if away else n - 1, g - 3, rnd)


def _dyadic_iv(m, e):
    """A callable giving the exact dyadic m * 2^e as a degenerate
    interval. Exactness matters for the same reason it does for an
    operand: a reduced argument rounded on the way in makes every
    result a correctly rounded answer to the wrong question."""
    def build(iv):
        v = iv.mpf(m)
        return v * iv.mpf(1 << e) if e >= 0 else v / iv.mpf(1 << -e)
    return build


def _exact_quotient(ua, ub):
    """|a| / |b| as an exact (m, e) with m ODD, or None when the
    quotient is not a dyadic rational.

    a and b are finite and nonzero. |a|/|b| = (Ma/Mb) * 2^(Ea-Eb) with
    Ma and Mb odd, so it is dyadic exactly when Mb divides Ma - and the
    quotient's odd part is then Ma/Mb, which is no wider than Ma. That
    is why atan2's neighbour case never has to consider an odd part
    wider than p bits."""
    ma, ea = _dyadic(ua)
    mb, eb = _dyadic(ub)
    if ma % mb:
        return None
    return ma // mb, ea - eb


# ---- the Pi-variant argument reduction, exact ------------------------

def _pi_reduce(u):
    """|x| mod 2 written as k/2 + S*2^e, with k in 0..4 and |S*2^e| <=
    1/4. Exact, and a mask rather than a multiplication.

    S == 0 exactly when |x| is a half-integer, which is where every
    exact case of this family lives.
    """
    if u.e >= 1:                            # every bit is above 2^1
        return 0, 0, 0                      # an even integer
    k2 = -u.e
    tm = u.m & ((1 << (k2 + 1)) - 1)        # |x| mod 2 == tm * 2^-k2
    if k2 == 0:                             # an integer
        return 2 * tm, 0, 0
    d = k2 - 1
    if d == 0:                              # a half-integer
        return tm, 0, 0
    k = (tm + (1 << (d - 1))) >> d          # nearest, ties downward
    return k, tm - (k << d), u.e


def _pi_trig_signs(k, s_int):
    """(sin is negative, cos is negative) for sin(pi t) and cos(pi t)
    at t = k/2 + s. Read off the quadrant, exactly; no evaluation can
    decide the sign of a value it is about to round."""
    km = k & 3
    if km == 0:
        return s_int < 0, False
    if km == 1:
        return False, s_int > 0
    if km == 2:
        return s_int > 0, True
    return True, s_int < 0


def _sinpi_cospi_tanpi(fmt, xa, rnd, which):
    u = unpack(fmt, xa)
    p = fmt.prec

    if u.kind == NAN:
        return _nan_out(fmt, u)
    if u.kind == INF:
        # sin/cos/tan of an infinity has no limit: 9.2.1 makes all three
        # invalid, and MPFR 4.2 agrees.
        return qnan_bits(fmt), FLAG_INVALID
    if u.kind == ZERO:
        STATS["exact"] += 1
        if which == "cos":
            return one_bits(fmt, 0), 0                  # cosPi(+-0) = 1
        return zero_bits(fmt, u.sign), 0                # sinPi/tanPi

    m_odd, e_odd = _dyadic(u)

    # ---- the exact cases, and Niven's theorem says they are all of
    # them. For a rational r, sin(pi r) is rational only when it is 0,
    # +-1/2 or +-1, and tan(pi r) only when it is 0 or +-1. A dyadic r
    # can never give +-1/2 (that needs r = 1/6 + n/1 and friends), so:
    #
    #   sinPi, cosPi   exact exactly at the HALF-integers
    #   tanPi          exact exactly at the QUARTER-integers
    #                  (with the half-integers a pole, not a value)
    #
    # and everything else is irrational, hence not a rounding boundary,
    # hence decided by the enclosure in finite time.
    if e_odd >= 0:                                      # an integer n
        STATS["exact"] += 1
        odd_n = (e_odd == 0)
        if which == "sin":
            return zero_bits(fmt, u.sign), 0            # sign of n
        if which == "cos":
            return one_bits(fmt, 1 if odd_n else 0), 0  # (-1)^n
        return zero_bits(fmt, u.sign ^ (1 if odd_n else 0)), 0
    if e_odd == -1:                                     # n + 1/2
        neg = u.sign ^ ((m_odd >> 1) & 1)
        if which == "sin":
            STATS["exact"] += 1
            return one_bits(fmt, neg), 0                # +-1
        if which == "cos":
            STATS["exact"] += 1
            return zero_bits(fmt, 0), 0                 # +0, both signs
        # tanPi at a pole. 754-2019 7.3 raises divideByZero where an
        # exact infinity comes from finite operands, and the sign is
        # sinPi's, because cosPi there is +0. MPFR 4.2.2 delivers the
        # same rows: tanpi(1/2) = +inf, tanpi(3/2) = -inf, with
        # divide-by-zero raised.
        return inf_bits(fmt, neg), FLAG_DIVZERO
    if e_odd == -2 and which == "tan":                  # n/4, n odd
        STATS["exact"] += 1
        return one_bits(fmt, u.sign ^ ((m_odd >> 1) & 1)), 0

    k, s_int, s_exp = _pi_reduce(u)
    assert s_int != 0, "a half-integer reached the enclosure"
    sin_neg, cos_neg = _pi_trig_signs(k, s_int)
    if which == "sin":
        sign = u.sign ^ (1 if sin_neg else 0)           # odd function
    elif which == "cos":
        sign = 1 if cos_neg else 0                      # even function
    else:
        sign = u.sign ^ (1 if sin_neg else 0) ^ (1 if cos_neg else 0)

    # |sin(pi t)| is sin(pi|s|) when k is even and cos(pi|s|) when it is
    # odd; |cos(pi t)| is the other way round.
    k_even = (k % 2) == 0
    magnitude_is_cos = (k_even and which == "cos") or \
                       (not k_even and which == "sin")

    s_abs = abs(s_int)
    s_vexp = s_exp + s_abs.bit_length() - 1

    # The one neighbour rule this family needs. cos(u) < 1 for u != 0
    # and 1 - cos(u) <= u^2/2, so with u = pi|s| the result sits below 1
    # by less than 4.94 s^2. Half the gap below 1 is 2^-(p+1), and
    # 4.94 * 2^(2v+2) < 2^-(p+1) reduces to 2v + p + 6 <= 0. No working
    # precision separates those from 1; the SIDE does, and it is always
    # downward.
    if magnitude_is_cos and 2 * s_vexp + p + 6 <= 0:
        return _round_neighbour(fmt, one_bits(fmt, sign), away=0, rnd=rnd)

    val = _dyadic_iv(s_abs, s_exp)

    def evaluate(iv):
        v = iv.pi * val(iv)
        if which == "tan":
            t = iv.tan(v)
            return t if k_even else iv.mpf(1) / t
        return iv.cos(v) if magnitude_is_cos else iv.sin(v)

    return _ziv(fmt, sign, evaluate, rnd)


def sinpi(fmt: FpFormat, xa: int, rnd: int = RND_RNE):
    """sin(pi x). Exact at the half-integers and nowhere else: sinPi(n)
    is a zero with the sign of n, sinPi(n + 1/2) is +-1. sinPi(+-inf) is
    invalid."""
    return _sinpi_cospi_tanpi(fmt, xa, rnd, "sin")


def cospi(fmt: FpFormat, xa: int, rnd: int = RND_RNE):
    """cos(pi x). cosPi(+-0) is 1, cosPi(n) is (-1)^n, and
    cosPi(n + 1/2) is +0 for every n and both signs of the argument -
    the function is even, so the zero cannot carry a sign."""
    return _sinpi_cospi_tanpi(fmt, xa, rnd, "cos")


def tanpi(fmt: FpFormat, xa: int, rnd: int = RND_RNE):
    """tan(pi x), which is sinPi/cosPi in every respect including the
    signs: tanPi(1) is -0, because sinPi(1) is +0 and cosPi(1) is -1.
    The half-integers are poles - +-infinity with divideByZero - and
    the quarter-integers are exactly +-1.

    tanPi cannot overflow at any format on this ladder. A representable
    x nearest a pole is at least 2^-p from it (x in [1/2, 1) has that
    ulp, and no binade does better), so |tanPi| <= 1/(pi 2^-p) < 2^p,
    which is far inside emax at all four rungs."""
    return _sinpi_cospi_tanpi(fmt, xa, rnd, "tan")


# ---- the inverse functions -------------------------------------------
#
# EXACTNESS, and why the enumerations below are complete.
#
# For the non-Pi inverses the answer is Hermite-Lindemann. If theta is a
# nonzero algebraic number then e^(i theta) is transcendental; but
# sin theta = x algebraic makes z = e^(i theta) a root of
# z^2 - 2ix z - 1, hence algebraic. So asin of a dyadic rational is
# either 0 or transcendental, and the same argument runs for cos and
# tan. asin, atan and atan2 are therefore exact only where the result
# is a ZERO, and acos only at acos(1) = +0.
#
# For the Pi-variants it is Niven. asinPi(x) = r means x = sin(pi r);
# r dyadic and x rational force sin(pi r) into {0, +-1/2, +-1}, and of
# the r that produce those only 0 and +-1/2 are themselves dyadic. So
# the whole table is
#
#   asinPi(+-0) = +-0        asinPi(+-1) = +-1/2
#   acosPi(1)   = +0         acosPi(+-0) = 1/2      acosPi(-1) = 1
#   atanPi(+-0) = +-0        atanPi(+-1) = +-1/4    atanPi(+-inf) = +-1/2
#   atan2Pi on the axes and the diagonals: 0, +-1/4, +-1/2, +-3/4, +-1
#
# and asinPi(1/2) = 1/6, rational but NOT dyadic, is not an exact case
# and not a rounding boundary either - which is why the loop terminates
# on it rather than hanging.


def _asin_acos_common(fmt, u):
    """(|x| as an exact iv builder, sqrt((1-|x|)(1+|x|)) builder).

    The product form is the whole trick: for |x| near 1 the factor
    1 - |x| is EXACT (Sterbenz), so the cancellation amplifies an error
    of zero, where 1 - x^2 formed directly would lose every bit the
    answer has. Phase 1's log(m') uses the same shape for the same
    reason."""
    ax = _dyadic_iv(u.m, u.e)

    def root(iv):
        x = ax(iv)
        one = iv.mpf(1)
        return iv.sqrt((one - x) * (one + x))

    return ax, root


def _asin_family(fmt, xa, rnd, over_pi):
    u = unpack(fmt, xa)
    p = fmt.prec

    if u.kind == NAN:
        return _nan_out(fmt, u)
    if u.kind == INF:
        return qnan_bits(fmt), FLAG_INVALID
    if u.kind == ZERO:
        STATS["exact"] += 1
        return zero_bits(fmt, u.sign), 0            # asin(+-0) = +-0
    if _mag_gt_one(u):
        return qnan_bits(fmt), FLAG_INVALID         # |x| > 1
    if _is_one_mag(u):
        STATS["exact"] += 1
        if over_pi:
            return _round_exact(fmt, u.sign, 1, -1, rnd)   # +-1/2, exact
        return _ziv(fmt, u.sign, lambda iv: iv.pi / 2, rnd)  # +-pi/2

    ex = _vexp(u)
    if not over_pi and 2 * ex + p + 2 <= 0:
        # asin(x) - x = x^3/6 + 3x^5/40 + ... > 0 for x in (0, 1), so
        # the true value is always on the far side of x from zero, and
        # |asin(x) - x| <= 0.2|x|^3 < 2^(3e+0.68) is inside half the gap
        # there once 2e + p + 2 <= 0. asinPi rides no such rule: its
        # answer is about x/pi, which is not next to anything.
        return _round_dyadic_side(fmt, u.sign, u.m, u.e, away=1, rnd=rnd)

    ax, root = _asin_acos_common(fmt, u)

    def evaluate(iv):
        a = iv.atan2(ax(iv), root(iv))
        return a / iv.pi if over_pi else a

    return _ziv(fmt, u.sign, evaluate, rnd)


def asin(fmt: FpFormat, xa: int, rnd: int = RND_RNE):
    """asin(x) in radians. Exact only at +-0; |x| > 1 is invalid."""
    return _asin_family(fmt, xa, rnd, over_pi=False)


def asinpi(fmt: FpFormat, xa: int, rnd: int = RND_RNE):
    """asin(x)/pi. Exact at +-0 and at +-1, where it is +-1/2."""
    return _asin_family(fmt, xa, rnd, over_pi=True)


def _acos_family(fmt, xa, rnd, over_pi):
    u = unpack(fmt, xa)
    p = fmt.prec

    if u.kind == NAN:
        return _nan_out(fmt, u)
    if u.kind == INF:
        return qnan_bits(fmt), FLAG_INVALID
    if _mag_gt_one(u):
        return qnan_bits(fmt), FLAG_INVALID
    if u.kind == ZERO:
        if over_pi:
            STATS["exact"] += 1
            return _round_exact(fmt, 0, 1, -1, rnd)        # 1/2, exact
        return _ziv(fmt, 0, lambda iv: iv.pi / 2, rnd)     # pi/2
    if _is_one_mag(u):
        STATS["exact"] += 1
        if not u.sign:
            return zero_bits(fmt, 0), 0                    # acos(1) = +0
        if over_pi:
            return one_bits(fmt, 0), 0                     # acosPi(-1) = 1
        return _ziv(fmt, 0, lambda iv: iv.pi, rnd)         # acos(-1) = pi

    ex = _vexp(u)
    if over_pi and ex <= -(p + 2):
        # acosPi(x) = 1/2 - asin(x)/pi, and |asin(x)/pi| <= 0.33|x| is
        # inside half the gap next to 1/2 once |x| <= 2^-(p+2). The side
        # is the operand's: a positive x pulls the answer below 1/2.
        return _round_dyadic_side(fmt, 0, 1, -1,
                                  away=(1 if u.sign else 0), rnd=rnd)

    ax, root = _asin_acos_common(fmt, u)

    def evaluate(iv):
        # atan2(sqrt(1-x^2), x) rather than pi/2 - asin(x): for x just
        # below 1 the difference form cancels away the whole answer,
        # and this one is a small angle computed as a small angle.
        a = iv.atan2(root(iv), _dyadic_iv(u.m if not u.sign else -u.m,
                                          u.e)(iv))
        return a / iv.pi if over_pi else a

    return _ziv(fmt, 0, evaluate, rnd)


def acos(fmt: FpFormat, xa: int, rnd: int = RND_RNE):
    """acos(x) in radians, in [0, pi]. Exact only at acos(1) = +0."""
    return _acos_family(fmt, xa, rnd, over_pi=False)


def acospi(fmt: FpFormat, xa: int, rnd: int = RND_RNE):
    """acos(x)/pi, in [0, 1]. Exact at 1 (+0), at +-0 (1/2) and at
    -1 (1)."""
    return _acos_family(fmt, xa, rnd, over_pi=True)


def _atan_family(fmt, xa, rnd, over_pi):
    u = unpack(fmt, xa)
    p = fmt.prec

    if u.kind == NAN:
        return _nan_out(fmt, u)
    if u.kind == ZERO:
        STATS["exact"] += 1
        return zero_bits(fmt, u.sign), 0
    if u.kind == INF:
        if over_pi:
            STATS["exact"] += 1
            return _round_exact(fmt, u.sign, 1, -1, rnd)      # +-1/2
        return _ziv(fmt, u.sign, lambda iv: iv.pi / 2, rnd)   # +-pi/2
    if over_pi and _is_one_mag(u):
        STATS["exact"] += 1
        return _round_exact(fmt, u.sign, 1, -2, rnd)          # +-1/4

    ex = _vexp(u)
    if not over_pi and 2 * ex + p + 3 <= 0:
        # atan(x) - x = -x^3/3 + x^5/5 - ... is negative for x in (0,1)
        # and no bigger than x^3/3, so the true value lies on the ZERO
        # side of x - the opposite side from asin's, which is what makes
        # a pair of directed roundings tell the two apart at all.
        return _round_dyadic_side(fmt, u.sign, u.m, u.e, away=0, rnd=rnd)
    if over_pi and ex >= p + 1:
        # atanPi(x) = 1/2 - atan(1/x)/pi and atan(1/x) <= 1/|x|, so once
        # |x| >= 2^(p+1) the answer is inside half the gap below 1/2.
        return _round_dyadic_side(fmt, u.sign, 1, -1, away=0, rnd=rnd)

    ax = _dyadic_iv(u.m, u.e)

    def evaluate(iv):
        a = iv.atan2(ax(iv), iv.mpf(1))
        return a / iv.pi if over_pi else a

    return _ziv(fmt, u.sign, evaluate, rnd)


def atan(fmt: FpFormat, xa: int, rnd: int = RND_RNE):
    """atan(x) in radians. Exact only at +-0; atan(+-inf) is +-pi/2."""
    return _atan_family(fmt, xa, rnd, over_pi=False)


def atanpi(fmt: FpFormat, xa: int, rnd: int = RND_RNE):
    """atan(x)/pi. Exact at +-0, at +-1 (+-1/4) and at +-inf (+-1/2)."""
    return _atan_family(fmt, xa, rnd, over_pi=True)


# ---- atan2, and the whole of its 9.2.1 table -------------------------
#
# The rows below are the standard's, and they are the ones an
# implementation is most often wrong about. atan2(+-0, -0) is +-pi -
# NOT +-0 - because the minus zero denominator names the negative real
# axis; atan2Pi(+-0, -0) is +-1 and is EXACT, where its radian twin is
# an inexact rounding of pi. Both were confirmed against MPFR 4.2.2
# before they were written down.


def _atan2_axis(fmt, quarters, sign, rnd, over_pi):
    """Deliver a result that is an exact multiple of pi/4.

    In the Pi-variant every one of them - 0, 1/4, 1/2, 3/4, 1 - is a
    dyadic rational the format holds exactly, so the answer is exact and
    raises nothing. In radians every one but zero is a rounding of an
    irrational number, so the answer is inexact. That asymmetry is not
    an implementation detail; it is the reason atan2Pi exists."""
    if quarters == 0:
        STATS["exact"] += 1
        return zero_bits(fmt, sign), 0
    if over_pi:
        STATS["exact"] += 1
        m, e = _odd_part(quarters)
        return _round_exact(fmt, sign, m, e - 2, rnd)
    return _ziv(fmt, sign, lambda iv: iv.pi * quarters / 4, rnd)


def _atan2_family(fmt, ya, xa, rnd, over_pi):
    uy, ux = unpack(fmt, ya), unpack(fmt, xa)
    p = fmt.prec

    if _has_snan(uy, ux):
        return qnan_bits(fmt), FLAG_INVALID
    if uy.kind == NAN or ux.kind == NAN:
        return qnan_bits(fmt), 0

    sign = uy.sign
    if uy.kind == INF:
        if ux.kind == INF:
            return _atan2_axis(fmt, 1 if not ux.sign else 3, sign, rnd,
                               over_pi)
        return _atan2_axis(fmt, 2, sign, rnd, over_pi)      # +-pi/2
    if ux.kind == INF:
        # a finite y against an infinite x: +-0 or +-pi
        return _atan2_axis(fmt, 4 if ux.sign else 0, sign, rnd, over_pi)
    if uy.kind == ZERO:
        # atan2(+-0, x>0) and atan2(+-0, +0) are +-0; atan2(+-0, x<0)
        # and atan2(+-0, -0) are +-pi. The SIGN of a zero x decides,
        # which is the row the whole table is remembered for.
        return _atan2_axis(fmt, 4 if ux.sign else 0, sign, rnd, over_pi)
    if ux.kind == ZERO:
        return _atan2_axis(fmt, 2, sign, rnd, over_pi)      # +-pi/2

    # Both finite and nonzero. The diagonals |y| == |x| are the last
    # exact rows: atan2Pi is +-1/4 there for a positive x and +-3/4 for
    # a negative one, and Niven says there are no others - a dyadic
    # multiple of pi has a rational tangent only at 0, +-1 and the pole.
    ey, ex = _vexp(uy), _vexp(ux)
    if (uy.m << max(0, uy.e - ux.e)) == (ux.m << max(0, ux.e - uy.e)):
        return _atan2_axis(fmt, 1 if not ux.sign else 3, sign, rnd, over_pi)

    if not ux.sign and not over_pi:
        # atan2(y, x>0) is atan(y/x), so when that quotient is itself a
        # dyadic rational sitting on the format's fine grid - which it
        # is whenever x's odd significand divides y's - the answer is a
        # hair below it and no precision can say how far. atan2(minSub,
        # 2) lands on a subnormal MIDPOINT this way.
        q = _exact_quotient(uy, ux)
        if q is not None:
            qm, qe = q
            qv = qe + qm.bit_length() - 1
            g = max(qv - p + 1, fmt.emin - fmt.man_w)
            if 2 * qv + p + 3 <= 0 and qe >= g - 1:
                return _round_dyadic_side(fmt, sign, qm, qe, away=0, rnd=rnd)

    if over_pi:
        # Near +-1 (a tiny quotient against a negative x) and near +-1/2
        # (a dominant y), the answer is inside half a gap of a value the
        # format holds. In radians the same corners sit next to pi and
        # pi/2, which the format does NOT hold, so no rule is needed
        # there - the ordinary enclosure resolves them.
        if ux.sign and ey - ex <= -(p + 1):
            return _round_dyadic_side(fmt, sign, 1, 0, away=0, rnd=rnd)
        if ex - ey <= -(p + 2):
            return _round_dyadic_side(fmt, sign, 1, -1,
                                      away=(1 if ux.sign else 0), rnd=rnd)

    # |y| > 0 makes atan2(|y|, x) land in (0, pi) whatever x's sign is,
    # so the interval library returns the MAGNITUDE directly and the
    # sign stays where it belongs: decided exactly, above.
    ay = _dyadic_iv(uy.m, uy.e)
    sx = _dyadic_iv(-ux.m if ux.sign else ux.m, ux.e)

    def evaluate(iv):
        t = iv.atan2(ay(iv), sx(iv))
        return t / iv.pi if over_pi else t

    return _ziv(fmt, sign, evaluate, rnd)


def atan2(fmt: FpFormat, ya: int, xa: int, rnd: int = RND_RNE):
    """atan2(y, x) in radians, y first as C has it. The full 9.2.1
    table, including atan2(+-0, -0) = +-pi."""
    return _atan2_family(fmt, ya, xa, rnd, over_pi=False)


def atan2pi(fmt: FpFormat, ya: int, xa: int, rnd: int = RND_RNE):
    """atan2(y, x)/pi. Exact on the axes and the diagonals - 0, +-1/4,
    +-1/2, +-3/4, +-1 - and nowhere else, which is a far larger exact
    table than the radian form has."""
    return _atan2_family(fmt, ya, xa, rnd, over_pi=True)


# =====================================================================
# Phase 3: the radian trigonometry and the hyperbolics
#
# sin, cos, tan of a RADIAN argument, and sinh, cosh, tanh, asinh, acosh
# and atanh. What phase 2 was defined to exclude, plus the half of
# clause 9 that needs nothing new at all.
#
# THE ARGUMENT REDUCTION, AND WHY THIS MODULE DOES NOT WRITE ONE.
# host/src/transcend.c reduces `x mod (pi/2)` itself, Payne-Hanek style,
# out of a 270,336-bit window of 2/pi and integer arithmetic, because a
# C library has no arbitrary-precision floating point to lean on. This
# module has mpmath, whose interval sine and cosine do their own
# reduction internally and rigorously at whatever precision the
# enclosure needs - so the reference does NOT reimplement the reduction,
# and that is the point. Two implementations that share a reduction
# agree about its bugs. Measured on this host, `iv.sin` of the largest
# fp256 magnitudes costs a tenth of a second the first time (it computes
# pi to a quarter of a million bits and caches it) and nothing after.
#
# THE SIGN. Phase 2's forward functions read their sign off an EXACT
# reduction - `x mod 2` is a mask - so no evaluation ever decided the
# sign of a value it was about to round. Here the reduction is not
# exact, and the C reads the sign off the quadrant its integer
# arithmetic produces. This module does the opposite on purpose: it
# takes the sign FROM THE ENCLOSURE, and only when both endpoints agree
# on it. That is sound because sin, cos and tan of a nonzero dyadic
# rational are never zero (a zero would make the argument a rational
# multiple of pi), so the enclosure separates from zero at some finite
# precision - and it is a different derivation from the C's, which is
# what an independent reference is for.
#
# EXACTNESS. Hermite-Lindemann again, and it closes the whole set:
# if x is a nonzero algebraic number then e^x is transcendental, and
# e^(ix) with it. So
#
#   sin(x) = a algebraic  =>  z = e^(ix) is a root of z^2 - 2iaz - 1
#   sinh(x) = a algebraic =>  z = e^x  is a root of z^2 - 2az - 1
#   cosh(x) = a algebraic =>  z = e^x  is a root of z^2 - 2az + 1
#
# and in each case z is algebraic, which forces x = 0. Every operand
# here is a dyadic rational, hence algebraic, so:
#
#   sin, tan, sinh, tanh, asinh, atanh   exact only at +-0
#   cos, cosh                            exact only at 0, where it is 1
#   acosh                                exact only at 1, where it is +0
#
# and `tanh(+-inf) = +-1` is a limit rather than a value, so it is a
# special-value row rather than an exact case - it raises nothing
# either way. docs/TRANSCENDENTALS.md writes each argument out.
# =====================================================================

FN_SIN = "sin"
FN_COS = "cos"
FN_TAN = "tan"
FN_SINH = "sinh"
FN_COSH = "cosh"
FN_TANH = "tanh"
FN_ASINH = "asinh"
FN_ACOSH = "acosh"
FN_ATANH = "atanh"

RADIAN_FNS = (FN_SIN, FN_COS, FN_TAN)
HYPERBOLIC_FNS = (FN_SINH, FN_COSH, FN_TANH, FN_ASINH, FN_ACOSH, FN_ATANH)
PHASE3_FNS = RADIAN_FNS + HYPERBOLIC_FNS


# ---- an enclosure whose SIGN is part of what it decides ---------------

def _signed_parts(enc):
    """(sign, smaller-magnitude endpoint, larger-magnitude endpoint) for
    an mpmath interval that provably excludes zero, else None.

    None means "sharpen": the interval touches or straddles zero, or an
    endpoint is not finite. Returning None rather than guessing is the
    whole difference between deciding a sign and assuming one."""
    lo_t, hi_t = enc._mpi_
    ls, lm, le, _lb = lo_t
    hs, hm, he, _hb = hi_t
    if int(lm) == 0 or int(hm) == 0 or ls != hs:
        return None
    if ls:                              # both negative: |lo| >= |hi|
        return 1, (0, hm, he, 0), (0, lm, le, 0)
    return 0, (0, lm, le, 0), (0, hm, he, 0)


def _mag_cmp(m, e, num, den_bits):
    """sign of (m * 2^e) - (num * 2^-den_bits), exactly."""
    k = e + den_bits
    if k >= 0:
        left, right = m << k, num
    else:
        left, right = m, num << -k
    return (left > right) - (left < right)


def _inside_half_gap_below_one(fmt, lo):
    """Does the enclosure PROVE the magnitude is above the midpoint just
    below 1?

    Only the low end is asked, and the reason is the interesting one:
    the high end can never be got below 1 cheaply - an enclosure of
    cos(x) for an x a hair from a multiple of 2pi is [1-eps-w, 1-eps+w]
    with w set by the working precision, and its top stays above 1 until
    the precision passes -log2(eps), which is exactly the escalation the
    rule exists to avoid. It does not need to: |sin x| and |cos x| are
    STRICTLY below 1 for every nonzero dyadic x, by the same
    Hermite-Lindemann argument that makes them inexact, so the low end
    plus a theorem is the whole proof."""
    return _mag_cmp(lo[0], lo[1], (1 << (fmt.prec + 1)) - 1,
                    fmt.prec + 1) > 0


def _ziv_signed(fmt, evaluate, rnd, beside_one=False):
    """Correctly round a real value whose SIGN the enclosure decides.

    Identical to _ziv except that the sign is read off the interval
    rather than passed in, and that `beside_one` enables the one
    neighbour rule the radian functions need against a value the
    enclosure cannot bracket from above."""
    iv = _iv()
    saved = iv.prec
    STATS["ziv_calls"] += 1
    prec = 0
    try:
        for i, prec in enumerate(_prec_schedule(fmt)):
            if i:
                STATS["escalations"] += 1
            STATS["max_prec"] = max(STATS["max_prec"], prec)
            iv.prec = prec
            parts = _signed_parts(evaluate(iv))
            if parts is None:
                continue                    # straddles zero: sharpen
            sign, lo_t, hi_t = parts
            lo = _endpoint(lo_t, prec, -1)
            hi = _endpoint(hi_t, prec, +1)
            if lo is None or hi is None:
                continue
            if beside_one and _inside_half_gap_below_one(fmt, lo):
                return _round_neighbour(fmt, one_bits(fmt, sign), away=0,
                                        rnd=rnd)
            blo = round_pack(fmt, sign, lo[0], lo[1], rnd)
            bhi = round_pack(fmt, sign, hi[0], hi[1], rnd)
            if blo == bhi:
                bits, flags = blo
                return bits, flags | FLAG_INEXACT
        raise ZivEscalation(
            f"{fmt.name}: the enclosure still did not decide the "
            f"rounding at {prec} bits of working precision. For a radian "
            "argument that means the reduction against pi cancelled "
            "deeper than the cap can see, which is the case the cap was "
            "sized to exclude; the correct answer is a refusal.")
    finally:
        iv.prec = saved


# ---- sin, cos, tan of a radian argument -------------------------------

def _radian_family(fmt, xa, rnd, which):
    u = unpack(fmt, xa)
    p = fmt.prec

    if u.kind == NAN:
        return _nan_out(fmt, u)
    if u.kind == INF:
        # 754-2019 9.2.1: no limit exists, so all three are invalid -
        # the same row sinPi, cosPi and tanPi take.
        return qnan_bits(fmt), FLAG_INVALID
    if u.kind == ZERO:
        STATS["exact"] += 1
        if which == "cos":
            return one_bits(fmt, 0), 0                  # cos(+-0) = 1
        return xa, 0                                    # sin/tan(+-0) = +-0

    ex = _vexp(u)

    # The three tiny-argument rules. Each is the leading term of the
    # series and its SIGN, compared against a quarter of the grid step,
    # exactly as phase 2 derives asin's and atan's:
    #
    #   sin(x) - x = -x^3/6 + ...   below x,  |.| <= |x|^3/6
    #   tan(x) - x = +x^3/3 + ...   above x,  |.| <= 0.357|x|^3 for
    #                               |x| <= 1/4
    #   1 - cos(x) <= x^2/2         below 1
    #
    # and the reduction is the identity here, so these are statements
    # about the operand rather than about a reduced argument.
    if which == "sin" and 2 * ex + p + 2 <= 0:
        return _round_neighbour(fmt, xa, away=0, rnd=rnd)
    if which == "tan" and 2 * ex + p + 3 <= 0:
        return _round_neighbour(fmt, xa, away=1, rnd=rnd)
    if which == "cos" and 2 * ex + p + 3 <= 0:
        return _round_neighbour(fmt, one_bits(fmt, 0), away=0, rnd=rnd)

    val = _exact_value_iv(fmt, xa)
    fn = {"sin": lambda iv_, v: iv_.sin(v),
          "cos": lambda iv_, v: iv_.cos(v),
          "tan": lambda iv_, v: iv_.tan(v)}[which]

    def evaluate(iv):
        return fn(iv, val(iv))

    # sin and cos can land inside the half gap below 1 - that is the
    # argument sitting a hair from a multiple of pi/2, which is the
    # deep-cancellation case - and no working precision separates them
    # from it. tan cannot: |tan| near 1 would need the reduced argument
    # within 2^-(p+2) of pi/4, which is a coincidence of a different and
    # far rarer order, and if one ever occurred the loop would refuse
    # rather than guess.
    return _ziv_signed(fmt, evaluate, rnd,
                       beside_one=(which in ("sin", "cos")))


def sin(fmt: FpFormat, xa: int, rnd: int = RND_RNE):
    """sin(x), x in RADIANS. Exact only at +-0; sin(+-inf) is invalid.

    The argument reduction against pi is what separates this from
    phase 2's sinPi, and it is the whole of phase 3's new machinery."""
    return _radian_family(fmt, xa, rnd, "sin")


def cos(fmt: FpFormat, xa: int, rnd: int = RND_RNE):
    """cos(x) in radians. cos(+-0) is 1 and is the only exact case;
    cos(+-inf) is invalid."""
    return _radian_family(fmt, xa, rnd, "cos")


def tan(fmt: FpFormat, xa: int, rnd: int = RND_RNE):
    """tan(x) in radians. Exact only at +-0; tan(+-inf) is invalid.

    Unlike tanPi there is no pole a representable argument can land on -
    an odd multiple of pi/2 is irrational - so tan never signals
    divideByZero. It CAN overflow, which tanPi provably cannot: how
    close an operand gets to a pole is the measurement in
    docs/TRANSCENDENTALS.md rather than a bound, and the overflow
    response comes through round_pack like every other."""
    return _radian_family(fmt, xa, rnd, "tan")


# ---- the hyperbolics --------------------------------------------------
#
# Every one of these is exp or log in different clothes, and the
# cancellation-free forms are phase 1's. This module writes them
# differently from host/src/transcend.c on purpose - the C uses the
# doubling identity for sinh and expm1(2x) for tanh, and these use the
# odd/even split of expm1 - so that agreement is evidence rather than a
# shared derivation:
#
#   sinh(x)  = (expm1(x) - expm1(-x)) / 2
#   cosh(x)  = (exp(x) + exp(-x)) / 2
#   tanh(x)  = (expm1(x) - expm1(-x)) / (exp(x) + exp(-x))
#   asinh(x) = log1p(x + x^2/(1 + sqrt(1 + x^2)))
#   acosh(x) = log1p(d + sqrt(d*(x+1))),  d = x - 1 EXACTLY
#   atanh(x) = log1p(2x/(1 - x)) / 2,     1 - x EXACTLY
#
# The two `EXACTLY` are the same trick phase 1's log(m') and phase 2's
# asin root use: for x near 1 the difference is exact on the encoding,
# so the cancellation amplifies an error of zero. Written the other way
# - acosh through sqrt(x^2 - 1), atanh through log((1+x)/(1-x)) - both
# lose every bit the answer has as x approaches 1.


def _exact_minus_one(u):
    """|x| - 1 as an exact dyadic (m, e), for a finite |x| > 1."""
    if u.e >= 0:
        return (u.m << u.e) - 1, 0
    return u.m - (1 << -u.e), u.e


def _exact_plus_one(u):
    """|x| + 1 as an exact dyadic (m, e), for a finite |x|."""
    if u.e >= 0:
        return (u.m << u.e) + 1, 0
    return u.m + (1 << -u.e), u.e


def _exact_one_minus(u):
    """1 - |x| as an exact dyadic (m, e), for a finite |x| < 1."""
    assert u.e < 0
    return (1 << -u.e) - u.m, u.e


def _cosh_sinh_overflow(fmt, u, sign, rnd):
    """The overflow response when sinh or cosh provably passes the
    format, else None.

    Both lie between e^|x|/4 and e^|x| for every |x| >= 1, so an
    enclosure of |x|*log2(e) above emax + 3 proves the result is above
    2^(emax+1), which is above every finite value. The screen exists so
    that nothing downstream is ever asked for e^(2^262143); it fires
    only when it PROVES the overflow, and falling through is always
    safe."""
    ax = _dyadic_iv(u.m, u.e)
    lo, _hi = _bounds(fmt, lambda iv: ax(iv) / iv.log(2))
    if lo > fmt.emax + 3:
        return _round_overflowing(fmt, sign, rnd)
    return None


def sinh(fmt: FpFormat, xa: int, rnd: int = RND_RNE):
    """sinh(x). Odd, exact only at +-0, sinh(+-inf) = +-inf, and it
    overflows for a large argument like any other exponential."""
    u = unpack(fmt, xa)
    p = fmt.prec

    if u.kind == NAN:
        return _nan_out(fmt, u)
    if u.kind == INF:
        return inf_bits(fmt, u.sign), 0
    if u.kind == ZERO:
        STATS["exact"] += 1
        return xa, 0                                    # sinh(+-0) = +-0

    ex = _vexp(u)
    if 2 * ex + p + 2 <= 0:
        # sinh(x) - x = x^3/6 + ... has the sign of x, and
        # |sinh(x) - x| <= 0.17|x|^3 sits inside half the gap on the far
        # side of x once 2e + p + 2 <= 0. The same threshold asin gets,
        # and for the same series shape with the opposite sign to sin's.
        return _round_neighbour(fmt, xa, away=1, rnd=rnd)

    screened = _cosh_sinh_overflow(fmt, u, u.sign, rnd)
    if screened is not None:
        return screened

    ax = _dyadic_iv(u.m, u.e)

    def evaluate(iv):
        a = ax(iv)
        return (iv.expm1(a) - iv.expm1(-a)) / 2

    return _ziv(fmt, u.sign, evaluate, rnd)


def cosh(fmt: FpFormat, xa: int, rnd: int = RND_RNE):
    """cosh(x). Even, never below 1, exact only at cosh(+-0) = 1, and
    cosh(+-inf) = +inf."""
    u = unpack(fmt, xa)
    p = fmt.prec

    if u.kind == NAN:
        return _nan_out(fmt, u)
    if u.kind == INF:
        return inf_bits(fmt, 0), 0
    if u.kind == ZERO:
        STATS["exact"] += 1
        return one_bits(fmt, 0), 0                      # cosh(+-0) = 1

    ex = _vexp(u)
    if 2 * ex + p + 2 <= 0:
        # cosh(x) - 1 = x^2/2 + ... > 0, at most 0.51x^2, and half the
        # gap ABOVE 1 is 2^-p - twice the gap below it, which is why
        # this threshold is one better than cos's for the same series.
        return _round_neighbour(fmt, one_bits(fmt, 0), away=1, rnd=rnd)

    screened = _cosh_sinh_overflow(fmt, u, 0, rnd)
    if screened is not None:
        return screened

    ax = _dyadic_iv(u.m, u.e)

    def evaluate(iv):
        a = ax(iv)
        return (iv.exp(a) + iv.exp(-a)) / 2

    return _ziv(fmt, 0, evaluate, rnd)


def tanh(fmt: FpFormat, xa: int, rnd: int = RND_RNE):
    """tanh(x). Odd, exact at +-0, and **tanh(+-inf) = +-1 exactly** -
    a limit that happens to be representable, so it raises nothing."""
    u = unpack(fmt, xa)
    p = fmt.prec

    if u.kind == NAN:
        return _nan_out(fmt, u)
    if u.kind == INF:
        return one_bits(fmt, u.sign), 0                 # +-1, exact
    if u.kind == ZERO:
        STATS["exact"] += 1
        return xa, 0                                    # tanh(+-0) = +-0

    ex = _vexp(u)
    if 2 * ex + p + 3 <= 0:
        # tanh(x) - x = -x^3/3 + ... lies on the ZERO side of x and is
        # no bigger than 0.357|x|^3 for |x| <= 1/4 - atan's rule with
        # atan's threshold, for the series that differs only in sign.
        return _round_neighbour(fmt, xa, away=0, rnd=rnd)
    if ex >= (p + 2).bit_length():
        # 1 - tanh(x) = 2/(e^2x + 1) < 2 e^-2x, which is inside half the
        # gap below 1 once x > 0.347(p+2). 2^ex >= p + 2 implies it with
        # room, and the integer form is the one both implementations
        # can test without evaluating anything.
        return _round_neighbour(fmt, one_bits(fmt, u.sign), away=0, rnd=rnd)

    ax = _dyadic_iv(u.m, u.e)

    def evaluate(iv):
        a = ax(iv)
        return (iv.expm1(a) - iv.expm1(-a)) / (iv.exp(a) + iv.exp(-a))

    return _ziv(fmt, u.sign, evaluate, rnd)


def asinh(fmt: FpFormat, xa: int, rnd: int = RND_RNE):
    """asinh(x). Odd, exact only at +-0, asinh(+-inf) = +-inf, and it
    cannot overflow: |asinh(x)| <= log(2|x| + 1) is about 181,705 at the
    top of fp256."""
    u = unpack(fmt, xa)
    p = fmt.prec

    if u.kind == NAN:
        return _nan_out(fmt, u)
    if u.kind == INF:
        return inf_bits(fmt, u.sign), 0
    if u.kind == ZERO:
        STATS["exact"] += 1
        return xa, 0                                    # asinh(+-0) = +-0

    ex = _vexp(u)
    if 2 * ex + p + 2 <= 0:
        # asinh(x) - x = -x^3/6 + ... lies on the zero side of x, by at
        # most |x|^3/6: sin's rule exactly, for the series that differs
        # only in the sign of every second term.
        return _round_neighbour(fmt, xa, away=0, rnd=rnd)

    ax = _dyadic_iv(u.m, u.e)

    def evaluate(iv):
        a = ax(iv)
        return iv.log1p(a + a * a / (1 + iv.sqrt(1 + a * a)))

    return _ziv(fmt, u.sign, evaluate, rnd)


def acosh(fmt: FpFormat, xa: int, rnd: int = RND_RNE):
    """acosh(x), defined on [1, +inf). acosh(1) is +0 and is the only
    exact case; **every x below 1 is invalid**, zeros, negatives and
    -inf included; acosh(+inf) is +inf.

    No neighbour rule, and that is worth stating: near 1 the answer
    behaves like sqrt(2(x-1)), which is not next to any representable
    number, so the ordinary enclosure resolves it - the same reason
    phase 2's acos has no rule near 1."""
    u = unpack(fmt, xa)

    if u.kind == NAN:
        return _nan_out(fmt, u)
    if u.kind == INF:
        if u.sign:
            return qnan_bits(fmt), FLAG_INVALID
        return inf_bits(fmt, 0), 0
    if u.kind == ZERO or u.sign or _vexp(u) < 0:
        return qnan_bits(fmt), FLAG_INVALID             # x < 1
    if _is_one_mag(u):
        STATS["exact"] += 1
        return zero_bits(fmt, 0), 0                     # acosh(1) = +0

    dm, de = _exact_minus_one(u)
    pm, pe = _exact_plus_one(u)
    d = _dyadic_iv(dm, de)
    s = _dyadic_iv(pm, pe)

    def evaluate(iv):
        dd = d(iv)
        return iv.log1p(dd + iv.sqrt(dd * s(iv)))

    return _ziv(fmt, 0, evaluate, rnd)


def atanh(fmt: FpFormat, xa: int, rnd: int = RND_RNE):
    """atanh(x), defined on (-1, 1). Odd, exact only at +-0;
    **atanh(+-1) is +-infinity with divideByZero** - 754-2019 7.3's
    rule, an exact infinity from finite operands, the same row tanPi
    takes at a pole - and |x| > 1, infinities included, is invalid.

    It cannot overflow either: the representable argument closest to 1
    is 2^-p away, so |atanh| <= (p+1)ln2/2, about 82 at fp256."""
    u = unpack(fmt, xa)
    p = fmt.prec

    if u.kind == NAN:
        return _nan_out(fmt, u)
    if u.kind == INF:
        return qnan_bits(fmt), FLAG_INVALID
    if u.kind == ZERO:
        STATS["exact"] += 1
        return xa, 0                                    # atanh(+-0) = +-0
    if _is_one_mag(u):
        return inf_bits(fmt, u.sign), FLAG_DIVZERO      # the pole
    if _mag_gt_one(u):
        return qnan_bits(fmt), FLAG_INVALID

    ex = _vexp(u)
    if 2 * ex + p + 3 <= 0:
        # atanh(x) - x = x^3/3 + ... has the sign of x and is at most
        # 0.357|x|^3 for |x| <= 1/4: tan's rule, for the series that
        # differs only in sign, and the mirror of tanh's.
        return _round_neighbour(fmt, xa, away=1, rnd=rnd)

    ax = _dyadic_iv(u.m, u.e)
    om, oe = _exact_one_minus(u)
    one_minus = _dyadic_iv(om, oe)

    def evaluate(iv):
        return iv.log1p(2 * ax(iv) / one_minus(iv)) / 2

    return _ziv(fmt, u.sign, evaluate, rnd)


# =====================================================================
# The rest of table 9.1: exp2m1, exp10, exp10m1, log2p1, log10p1,
# rSqrt, pown, powr, compound and rootn
#
# What is new here is NOT a reduction, a constant or an evaluator - it
# is exactness. Every one of these ten has a LARGER exact-case table
# than the function it is built from, and each table has to be proved
# closed before the Ziv loop below it is allowed to run, because a true
# value that sits on a rounding boundary is exactly where the loop does
# not terminate.
#
#   exp2m1   2^n - 1 is a dyadic rational for EVERY integer n, positive
#            or negative. exp2's own exact case is the whole line of
#            integers, and subtracting 1 keeps it there.
#   exp10    10^n = 2^n 5^n is dyadic for n >= 0 and is a rounding
#            boundary exactly while 5^n fits in p+1 bits; a negative
#            power of ten is not dyadic at all.
#   exp10m1  10^n - 1 is an ODD integer, so its odd part is itself and
#            the boundary condition is that it fit in p+1 bits.
#   log2p1   log2(1+x) is rational only where 1+x is a power of two -
#            unique factorisation, the same argument log2 uses - and 1+x
#            is formed EXACTLY on the encoding, never as a rounded sum.
#   log10p1  likewise for the powers of ten, which for a dyadic 1+x
#            means the non-negative ones.
#   rSqrt    1/sqrt(M 2^E) is dyadic only when M = 1 and E is even: any
#            other odd M would need sqrt(M) to be a power of two.
#   pown     phase 1's pow with an integer exponent, which is the branch
#            its dyadic analysis already decides exactly.
#   powr     phase 1's pow restricted to a non-negative base, so the
#            same analysis with the sign question deleted.
#   compound (1+x)^n: 1+x exactly, then pown's procedure on it.
#   rootn    x^(1/n) is rational only when the odd significand is a
#            perfect |n|-th power AND |n| divides the exponent, which
#            one verified integer root decides.
#
# The neighbour rules are the other half, and the interesting half is
# which functions get NONE. A tiny x gives 2^x - 1 ~ x ln2,
# 10^x - 1 ~ x ln10, log2(1+x) ~ x/ln2 and log10(1+x) ~ x/ln10 - none
# of which is beside x, because none of those constants is 1. So the
# four "m1/p1" functions of a base other than e get no tiny-argument
# rule at all, where expm1 and log1p have one; what they get instead is
# a rule beside -1 for a large negative argument, where 2^x and 10^x
# have vanished below half a gap. docs/TRANSCENDENTALS.md derives every
# threshold.
# =====================================================================

FN_EXP2M1 = "exp2m1"
FN_EXP10 = "exp10"
FN_EXP10M1 = "exp10m1"
FN_LOG2P1 = "log2p1"
FN_LOG10P1 = "log10p1"
FN_RSQRT = "rsqrt"
FN_POWN = "pown"
FN_POWR = "powr"
FN_COMPOUND = "compound"
FN_ROOTN = "rootn"

TABLE91_FNS = (FN_EXP2M1, FN_EXP10, FN_EXP10M1, FN_LOG2P1, FN_LOG10P1,
               FN_RSQRT, FN_POWN, FN_POWR, FN_COMPOUND, FN_ROOTN)


# ---- exact helpers for this set --------------------------------------

def _exact_one_plus(u):
    """1 + x as an exact dyadic (m, e) with m >= 0, for a finite x.

    Never a rounded sum: the two exponents are aligned on the lower of
    them and the integers are added, which is the same discipline phase
    3's acosh and atanh use for x - 1 and 1 - x. For x = -2^-1074 at
    binary64 the result is the 1075-bit integer 2^1074 - 1 times
    2^-1074, exactly, where `1 + x` evaluated in the format would be 1
    and would take the answer with it."""
    e0 = min(0, u.e)
    base = 1 << (-e0)
    term = u.m << (u.e - e0)
    return (base - term if u.sign else base + term), e0


def _int_kth_root(M, k):
    """The exact k-th root of the positive integer M, or None. Binary
    search verified by raising the candidate back - no floating point
    and no tolerance, which is the same rule _exact_2k_root keeps."""
    if M == 1:
        return 1
    if k >= M.bit_length():
        return None                     # any root >= 2 would need 2^k <= M
    hi = 1 << ((M.bit_length() + k - 1) // k)
    lo = 1
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if mid ** k <= M:
            lo = mid
        else:
            hi = mid - 1
    return lo if lo ** k == M else None


def _pown_dyadic(fmt, m, e, n):
    """(M 2^E)^n as an exact (m, e), or None when no such dyadic
    rational exists with an odd part small enough to be a rounding
    boundary. m > 0; n != 0.

    None is a proof, not a shrug, and it is phase 1's: the value is
    then a rational that is not dyadic (a negative power of an odd
    significand) or a dyadic whose odd part needs more than p+1 bits,
    and neither can be a grid point or a midpoint of a p-bit format."""
    p = fmt.prec
    M, E = _odd_part(m)
    E += e
    if M == 1:
        return 1, E * n
    if n < 0:
        return None                     # 1/(odd > 1) is not dyadic
    if n > p + 1:
        return None                     # the odd part outruns p+1 bits
    v = M ** n
    if v.bit_length() > p + 1:
        return None
    return v, E * n


def _rootn_dyadic(fmt, u, n):
    """|x|^(1/n) as an exact (m, e), or None.

    (M 2^E)^(1/n) is rational exactly when M is a perfect |n|-th power
    and |n| divides E; for a negative n the reciprocal of that is dyadic
    only when the root is 1, because 1/(odd > 1) is not a dyadic
    rational. Both halves are decided by exact integer arithmetic."""
    M, E = _dyadic(u)
    k = -n if n < 0 else n
    if E % k:
        return None
    if M == 1:
        root = 1
    else:
        if n < 0:
            return None
        root = _int_kth_root(M, k)
        if root is None:
            return None
    F = E // k
    if n < 0:
        return 1, -F                    # root == 1 here, so 1/2^F
    return root, F


def _int_bits(fmt, n, e):
    """The encoding of n * 2^e when the format holds it exactly, else
    None - so a neighbour witness can be anchored on a power of two
    without assuming the format reaches it."""
    bits, flags = round_pack(fmt, 0, n, e, RND_RNE)
    return None if flags else bits


# =====================================================================
# exp2m1, exp10, exp10m1
# =====================================================================

def exp2m1(fmt: FpFormat, xa: int, rnd: int = RND_RNE):
    """2**x - 1, correctly rounded. 754-2019 9.2.1: f(+-0) is +-0,
    f(+inf) is +inf, f(-inf) is -1, all with no exception.

    EXACT at every integer argument, which is a wider table than exp2's
    is narrow: 2^n - 1 is a dyadic rational for every n, and it is a
    rounding boundary of a p-bit format exactly while |n| <= p+1. Past
    that the value is still exactly known but is decided by a SIDE
    rather than by a rounding of it - 2^n - 1 sits in the top quarter of
    the gap below 2^n for n >= p+2, and -(1 - 2^n) in the half gap above
    -1 for n <= -(p+2) - because the exact integer 2^n - 1 is up to
    262,143 bits wide at fp256 and the C's container is 2048."""
    u = unpack(fmt, xa)
    p = fmt.prec

    if u.kind == NAN:
        return _nan_out(fmt, u)
    if u.kind == INF:
        if u.sign:
            return one_bits(fmt, 1), 0                  # exp2m1(-inf) = -1
        return inf_bits(fmt, 0), 0
    if u.kind == ZERO:
        STATS["exact"] += 1
        return xa, 0                                    # exp2m1(+-0) = +-0

    M, E = _dyadic(u)
    if E >= 0:                                          # an integer argument
        n = M << E
        if u.sign:
            n = -n
        if -(p + 1) <= n <= p + 1:
            STATS["exact"] += 1
            if n >= 0:
                return _round_exact(fmt, 0, (1 << n) - 1, 0, rnd)
            return _round_exact(fmt, 1, (1 << -n) - 1, n, rnd)
        if n > 0:
            if n > fmt.emax:
                return _round_overflowing(fmt, 0, rnd)
            # 2^n - 1 is inside the top quarter of the gap below 2^n:
            # the gap there is 2^(n-p) and 1 < 2^(n-p-1) for n >= p+2.
            return _round_neighbour(fmt, _int_bits(fmt, 1, n), away=0,
                                    rnd=rnd)
        # n <= -(p+2): 2^n - 1 is inside the half gap above -1, whose
        # nearest boundary is at -(1 - 2^-(p+1)).
        return _round_neighbour(fmt, one_bits(fmt, 1), away=0, rnd=rnd)

    # A non-integer argument. No tiny-argument rule: 2^x - 1 is about
    # x ln2, which is not beside x.
    val = _exact_value_iv(fmt, xa)
    sign = 1 if u.sign else 0

    lo, hi = _bounds(fmt, val)                          # log2(2^x) is x
    if lo > fmt.emax + 2:
        return _round_overflowing(fmt, 0, rnd)
    if hi < -(p + 3):
        # 2^x is below 2^-(p+2), so the value sits that far above -1.
        return _round_neighbour(fmt, one_bits(fmt, 1), away=0, rnd=rnd)

    def evaluate(iv):
        y = iv.expm1(val(iv) * iv.log(2))
        return -y if sign else y

    return _ziv(fmt, sign, evaluate, rnd)


def exp10(fmt: FpFormat, xa: int, rnd: int = RND_RNE):
    """10**x, correctly rounded. 9.2.1: f(+-0) is 1, f(+inf) is +inf,
    f(-inf) is +0.

    EXACT exactly at the non-negative integers whose 5^n fits in p+1
    bits. 10^n = 2^n 5^n has odd part 5^n, so it is a rounding boundary
    only while that fits; a negative power of ten is not a dyadic
    rational at all, and a non-integer dyadic exponent gives an
    algebraic irrational."""
    u = unpack(fmt, xa)
    p = fmt.prec

    if u.kind == NAN:
        return _nan_out(fmt, u)
    if u.kind == INF:
        return (zero_bits(fmt, 0), 0) if u.sign else (inf_bits(fmt, 0), 0)
    if u.kind == ZERO:
        STATS["exact"] += 1
        return one_bits(fmt, 0), 0

    M, E = _dyadic(u)
    if E >= 0 and not u.sign:
        n = M << E
        if n <= p + 1:                  # 5^n needs at least n bits
            v = 5 ** n
            if v.bit_length() <= p + 1:
                STATS["exact"] += 1
                return _round_exact(fmt, 0, v, n, rnd)

    ex = _vexp(u)
    if ex <= -(p + 4):
        # |10^x - 1| <= 2.64|x| < 2^-(p+1) there, which is the nearer
        # boundary next to 1, and the side is the sign of x.
        return _round_neighbour(fmt, one_bits(fmt, 0), away=(u.sign == 0),
                                rnd=rnd)

    val = _exact_value_iv(fmt, xa)

    def log2_of_result(iv):
        return val(iv) * iv.log(10) / iv.log(2)

    screened = _screen_exponent(fmt, log2_of_result, 0, rnd)
    if screened is not None:
        return screened

    return _ziv(fmt, 0, lambda iv: iv.exp(val(iv) * iv.log(10)), rnd)


def exp10m1(fmt: FpFormat, xa: int, rnd: int = RND_RNE):
    """10**x - 1, correctly rounded. 9.2.1: f(+-0) is +-0, f(+inf) is
    +inf, f(-inf) is -1.

    EXACT exactly at the non-negative integers whose 10^n - 1 fits in
    p+1 bits. 10^n - 1 is an odd integer, so its odd part is itself; for
    a larger n the value is not a boundary and the enclosure decides it,
    and for (p+1)/log2(10) < n <= p/log2(5) it decides it at a
    measurable depth - 10^n - 1 is then exactly ONE below a multiple of
    the half-ulp, so the enclosure needs about log2(10)*n bits, which is
    at most 1.44(p+1) and is inside the FIRST attempt at every format.
    docs/TRANSCENDENTALS.md does that arithmetic."""
    u = unpack(fmt, xa)
    p = fmt.prec

    if u.kind == NAN:
        return _nan_out(fmt, u)
    if u.kind == INF:
        if u.sign:
            return one_bits(fmt, 1), 0                  # exp10m1(-inf) = -1
        return inf_bits(fmt, 0), 0
    if u.kind == ZERO:
        STATS["exact"] += 1
        return xa, 0                                    # exp10m1(+-0) = +-0

    M, E = _dyadic(u)
    if E >= 0 and not u.sign:
        n = M << E
        if n <= p + 1:
            v = 10 ** n - 1
            if v.bit_length() <= p + 1:
                STATS["exact"] += 1
                return _round_exact(fmt, 0, v, 0, rnd)

    val = _exact_value_iv(fmt, xa)
    sign = 1 if u.sign else 0

    def log2_of_exp(iv):
        return val(iv) * iv.log(10) / iv.log(2)

    lo, hi = _bounds(fmt, log2_of_exp)
    if lo > fmt.emax + 2:
        return _round_overflowing(fmt, 0, rnd)
    if hi < -(p + 3):
        # 10^x is below 2^-(p+2): the value sits that far above -1.
        return _round_neighbour(fmt, one_bits(fmt, 1), away=0, rnd=rnd)

    def evaluate(iv):
        y = iv.expm1(val(iv) * iv.log(10))
        return -y if sign else y

    return _ziv(fmt, sign, evaluate, rnd)


# =====================================================================
# log2p1, log10p1
# =====================================================================

def log2p1(fmt: FpFormat, xa: int, rnd: int = RND_RNE):
    """log2(1 + x). 9.2.1: f(+-0) is +-0, f(-1) is -inf with
    divideByZero, x < -1 is invalid, f(+inf) is +inf.

    EXACT exactly where 1 + x is a power of two, and 1 + x is formed
    EXACTLY on the encoding rather than in the format."""
    return _logp1_family(fmt, xa, rnd, base=2)


def log10p1(fmt: FpFormat, xa: int, rnd: int = RND_RNE):
    """log10(1 + x). The same rows, and EXACT exactly where 1 + x is a
    power of ten the format can hold - which means a NON-NEGATIVE power,
    since 10^-k is not a dyadic rational and 1 + x always is."""
    return _logp1_family(fmt, xa, rnd, base=10)


def _logp1_family(fmt, xa, rnd, base):
    u = unpack(fmt, xa)

    if u.kind == NAN:
        return _nan_out(fmt, u)
    if u.kind == INF:
        if u.sign:
            return qnan_bits(fmt), FLAG_INVALID         # 1 + (-inf) < 0
        return inf_bits(fmt, 0), 0
    if u.kind == ZERO:
        STATS["exact"] += 1
        return xa, 0                                    # f(+-0) = +-0

    M, E = _dyadic(u)
    if u.sign and M == 1 and E == 0:                    # x == -1
        return inf_bits(fmt, 1), FLAG_DIVZERO
    if u.sign and _vexp(u) >= 0:                        # x < -1
        return qnan_bits(fmt), FLAG_INVALID

    sm, se = _exact_one_plus(u)
    om, oe = _odd_part(sm)
    oe += se
    if base == 2 and om == 1:                           # 1 + x = 2^oe
        STATS["exact"] += 1
        if oe == 0:
            return zero_bits(fmt, 0), 0
        return _round_exact(fmt, 1 if oe < 0 else 0, abs(oe), 0, rnd)
    if base == 10 and 0 <= oe <= fmt.prec and om == 5 ** oe:
        STATS["exact"] += 1                             # 1 + x = 10^oe
        if oe == 0:
            return zero_bits(fmt, 0), 0
        return _round_exact(fmt, 0, oe, 0, rnd)

    # The one family no working precision can decide, and the only
    # neighbour rule these two get.
    #
    # For x = 2^k the value is k + log2(1 + 2^-k): an exponentially small
    # step ABOVE the integer k, and k is a grid point of every format on
    # this ladder. The enclosure would have to separate the two and
    # cannot; the SIDE is the whole answer, and it is a theorem
    # (log2(1+u) > 0 for u > 0) rather than a measurement.
    #
    # The threshold is derived. The excess is at most 2^(-k+0.529) and
    # the nearest boundary above k is at 2^(g-p) with g = floor(log2 k),
    # so it is inside once k >= p - g + 1; at k = p - g the excess is at
    # least 1.26 half-gaps and the enclosure decides that one with two
    # bits to spare, so there is no band between them. For x = 10^k the
    # same shape in another base, compared in exact integers against
    # 23025/10000 - a rational below ln 10, and the closest that
    # comparison comes to an equality over every k any format holds is a
    # factor of 2^0.495 (fp128, k = 32).
    if not u.sign and E >= 1:
        g = E.bit_length() - 1
        if base == 2 and M == 1 and E >= fmt.prec - g + 1:
            return _round_dyadic_side(fmt, 0, E, 0, away=1, rnd=rnd)
        if (base == 10 and E <= fmt.prec and M == 5 ** E and
                10000 * (1 << (fmt.prec - g)) < 23025 * 10 ** E):
            return _round_dyadic_side(fmt, 0, E, 0, away=1, rnd=rnd)

    # Nothing else needs one, and that is the derivation rather than an
    # omission: for a tiny x the value is x/ln2 or x/ln10, which is not
    # beside x - only a base of e puts it there. The enclosure resolves
    # those to full relative precision, and round_pack carries the
    # underflow.
    sign = u.sign
    val = _exact_value_iv(fmt, xa)

    def evaluate(iv):
        y = iv.log1p(val(iv)) / (iv.log(2) if base == 2 else iv.log(10))
        return -y if sign else y

    return _ziv(fmt, sign, evaluate, rnd)


# =====================================================================
# rSqrt
# =====================================================================

def rsqrt(fmt: FpFormat, xa: int, rnd: int = RND_RNE):
    """1/sqrt(x) on [0, +inf]. 9.2.1: rSqrt(+-0) is +-INFINITY with
    divideByZero - the sign survives, which GNU MPFR's mpfr_rec_sqrt
    does not do (it delivers +inf for both, measured 2026-09-03) -
    rSqrt(+inf) is +0, and x < 0 is invalid.

    EXACT exactly at the even powers of two. 1/sqrt(M 2^E) is rational
    only if sqrt(M) is, and dyadic only if sqrt(M) is a power of two;
    M is odd, so that forces M = 1, and then E must be even for
    2^(-E/2) to be a dyadic rational at all.

    It can neither overflow nor underflow on this ladder: the largest
    result is 1/sqrt(minSubnormal) = 2^((p-1+emax)/2), and (emax+p-1)/2
    is below emax at every rung."""
    u = unpack(fmt, xa)

    if u.kind == NAN:
        return _nan_out(fmt, u)
    if u.kind == ZERO:
        return inf_bits(fmt, u.sign), FLAG_DIVZERO
    if u.sign:
        return qnan_bits(fmt), FLAG_INVALID
    if u.kind == INF:
        return zero_bits(fmt, 0), 0

    M, E = _dyadic(u)
    if M == 1 and E % 2 == 0:
        STATS["exact"] += 1
        return _round_exact(fmt, 0, 1, -(E // 2), rnd)

    val = _exact_value_iv(fmt, xa)
    return _ziv(fmt, 0, lambda iv: iv.mpf(1) / iv.sqrt(val(iv)), rnd)


# =====================================================================
# pown, powr, compound, rootn - the integer-exponent family
#
# n is an INTEGER, not a floating-point operand, exactly as 9.2.1 asks:
# "n is a finite integral value in integralFormat". This module takes a
# Python int and the C takes an int64_t array beside the operand array;
# neither ever has to ask what a non-integral second operand would mean.
# =====================================================================

def pown(fmt: FpFormat, xa: int, n: int, rnd: int = RND_RNE):
    """x**n for an integer n. 9.2.1's own rows, which are pow's with
    the non-integer exponent deleted: pown(x, 0) is 1 for any x that is
    not a signaling NaN - a quiet NaN and an infinity included -
    pown(+-0, n) is +-inf with divideByZero for an odd n < 0 and +inf
    for an even one, and the sign of the result is the operand's when n
    is odd and positive otherwise.

    The exact cases are the ones pow's dyadic analysis already decides:
    a power-of-two magnitude is an exponent shift at any n, and any
    other odd significand loses the race after p+1 multiplications."""
    u = unpack(fmt, xa)

    if _has_snan(u):
        return qnan_bits(fmt), FLAG_INVALID
    if n == 0:
        return one_bits(fmt, 0), 0
    if u.kind == NAN:
        return qnan_bits(fmt), 0

    odd = bool(n & 1)
    if u.kind == ZERO:
        neg = u.sign and odd
        if n < 0:
            return inf_bits(fmt, 1 if neg else 0), FLAG_DIVZERO
        return zero_bits(fmt, 1 if neg else 0), 0
    if u.kind == INF:
        neg = u.sign and odd
        if n < 0:
            return zero_bits(fmt, 1 if neg else 0), 0
        return inf_bits(fmt, 1 if neg else 0), 0

    sign = 1 if (u.sign and odd) else 0
    exact = _pown_dyadic(fmt, u.m, u.e, n)
    if exact is not None:
        m, e = exact
        STATS["exact"] += 1
        vexp = e + m.bit_length() - 1
        if vexp > fmt.emax:
            return _round_overflowing(fmt, sign, rnd)
        if vexp < fmt.emin - fmt.man_w - 1:
            return _round_underflowing(fmt, sign, rnd)
        return _round_exact(fmt, sign, m, e, rnd)

    val = _exact_value_iv(fmt, xa)

    def log_of_result(iv):
        return n * iv.log(abs(val(iv)))

    screened = _screen_exponent(fmt, lambda iv: log_of_result(iv) / iv.log(2),
                                sign, rnd)
    if screened is not None:
        return screened

    lo, hi = _bounds(fmt, lambda iv: abs(log_of_result(iv)))
    if hi < 2.0 ** -(fmt.prec + 3):
        up = (_mag_gt_one(u) != (n < 0))
        return _round_neighbour(fmt, one_bits(fmt, sign), away=up, rnd=rnd)

    return _ziv(fmt, sign, lambda iv: iv.power(abs(val(iv)), n), rnd)


def powr(fmt: FpFormat, xa: int, xb: int, rnd: int = RND_RNE):
    """x**y defined as exp(y log x), so the domain excludes a negative
    base and the table is NOT pow's:

        powr(x, y) for x < 0            invalid  (every y, NaN included)
        powr(+-0, +-0)                  invalid
        powr(+inf, +-0)                 invalid
        powr(+1, +-inf)                 invalid
        powr(+-0, y) for finite y < 0   +inf with divideByZero
        powr(+-0, -inf)                 +inf, silent
        powr(+-0, y) for y > 0          +0
        powr(x, +-0) for finite x > 0   1
        powr(+1, y) for finite y        1
        powr(qNaN, y), powr(x, qNaN)    qNaN, silent

    Two of those differ from what MPFR 4.2.2 delivers, and both are the
    standard's: powr(1, qNaN) is a quiet NaN here where mpfr_powr
    returns 1 - the standard's row is "powr(+1, y) is 1 for FINITE y",
    and it lists powr(x, qNaN) for x >= 0 separately - and powr(qNaN, 0)
    is a quiet NaN where pow(qNaN, 0) is 1. The second is the whole
    point of having both functions.

    The result is never negative, so the exact cases are pow's dyadic
    analysis with the sign question deleted."""
    ux, uy = unpack(fmt, xa), unpack(fmt, xb)

    if _has_snan(ux, uy):
        return qnan_bits(fmt), FLAG_INVALID
    # x < 0 outranks even a quiet NaN exponent: it is a domain error,
    # and 9.2.1's NaN row is written "for x >= 0".
    if ux.kind != NAN and ux.sign and ux.kind != ZERO:
        return qnan_bits(fmt), FLAG_INVALID
    if ux.kind == NAN or uy.kind == NAN:
        return qnan_bits(fmt), 0

    if ux.kind == ZERO:
        if uy.kind == ZERO:
            return qnan_bits(fmt), FLAG_INVALID         # powr(+-0, +-0)
        if uy.sign:
            if uy.kind == INF:
                return inf_bits(fmt, 0), 0              # powr(+-0, -inf)
            return inf_bits(fmt, 0), FLAG_DIVZERO
        return zero_bits(fmt, 0), 0
    if ux.kind == INF:                                  # +inf only
        if uy.kind == ZERO:
            return qnan_bits(fmt), FLAG_INVALID         # powr(+inf, +-0)
        return (zero_bits(fmt, 0), 0) if uy.sign else (inf_bits(fmt, 0), 0)
    if _is_one(ux):
        if uy.kind == INF:
            return qnan_bits(fmt), FLAG_INVALID         # powr(+1, +-inf)
        return one_bits(fmt, 0), 0                      # every finite y
    if uy.kind == ZERO:
        return one_bits(fmt, 0), 0                      # finite x > 0
    if uy.kind == INF:
        if _mag_gt_one(ux) == (not uy.sign):
            return inf_bits(fmt, 0), 0
        return zero_bits(fmt, 0), 0

    exact = _pow_dyadic(fmt, ux, uy)
    if exact is not None:
        m, e = exact
        STATS["exact"] += 1
        vexp = e + m.bit_length() - 1
        if vexp > fmt.emax:
            return _round_overflowing(fmt, 0, rnd)
        if vexp < fmt.emin - fmt.man_w - 1:
            return _round_underflowing(fmt, 0, rnd)
        return _round_exact(fmt, 0, m, e, rnd)

    valx = _exact_value_iv(fmt, xa)
    valy = _exact_value_iv(fmt, xb)

    def log_of_result(iv):
        return valy(iv) * iv.log(valx(iv))

    screened = _screen_exponent(fmt, lambda iv: log_of_result(iv) / iv.log(2),
                                0, rnd)
    if screened is not None:
        return screened

    lo, hi = _bounds(fmt, lambda iv: abs(log_of_result(iv)))
    if hi < 2.0 ** -(fmt.prec + 3):
        up = (_mag_gt_one(ux) != bool(uy.sign))
        return _round_neighbour(fmt, one_bits(fmt, 0), away=up, rnd=rnd)

    return _ziv(fmt, 0, lambda iv: iv.power(valx(iv), valy(iv)), rnd)


def compound(fmt: FpFormat, xa: int, n: int, rnd: int = RND_RNE):
    """(1 + x)**n for an integer n, on [-1, +inf]. 9.2.1:

        compound(x, 0)      1 for x >= -1 or a quiet NaN - and INVALID
                            for x < -1, which is the row the phrase "for
                            x >= -1 or quiet NaN" makes rather than
                            states, and which MPFR 4.2.2 confirms
        compound(-1, n)     +inf with divideByZero for n < 0, +0 for n > 0
        compound(+-0, n)    1
        compound(+inf, n)   +inf for n > 0, +0 for n < 0
        compound(x, n)      invalid for x < -1, -inf included
        compound(qNaN, n)   qNaN for n != 0

    1 + x is formed EXACTLY and then raised by pown's own procedure, so
    compound(x, 1) is the exact 1 + x correctly rounded - which for
    x = 2^-1074 at binary64 is 1 with inexact, and is NOT what
    evaluating (1 + x)^1 in the format would give."""
    u = unpack(fmt, xa)

    if _has_snan(u):
        return qnan_bits(fmt), FLAG_INVALID
    below = (u.kind != NAN and u.sign and _mag_gt_one(u))       # x < -1
    if n == 0:
        if u.kind == NAN:
            return one_bits(fmt, 0), 0                  # even a quiet NaN
        if below:
            return qnan_bits(fmt), FLAG_INVALID
        return one_bits(fmt, 0), 0
    if u.kind == NAN:
        return qnan_bits(fmt), 0
    if below:
        return qnan_bits(fmt), FLAG_INVALID
    if u.sign and _is_one_mag(u):                       # x == -1
        if n < 0:
            return inf_bits(fmt, 0), FLAG_DIVZERO
        return zero_bits(fmt, 0), 0
    if u.kind == ZERO:
        return one_bits(fmt, 0), 0
    if u.kind == INF:                                   # +inf
        return (inf_bits(fmt, 0), 0) if n > 0 else (zero_bits(fmt, 0), 0)

    sm, se = _exact_one_plus(u)
    exact = _pown_dyadic(fmt, sm, se, n)
    if exact is not None:
        m, e = exact
        STATS["exact"] += 1
        vexp = e + m.bit_length() - 1
        if vexp > fmt.emax:
            return _round_overflowing(fmt, 0, rnd)
        if vexp < fmt.emin - fmt.man_w - 1:
            return _round_underflowing(fmt, 0, rnd)
        return _round_exact(fmt, 0, m, e, rnd)

    val = _exact_value_iv(fmt, xa)
    onep = _dyadic_iv(sm, se)

    def log_of_result(iv):
        # log1p on the operand for a small x, so 1 + x is never formed
        # in the interval context and cannot round to 1; the exact
        # dyadic otherwise, which costs nothing and is tighter.
        if _vexp(u) < -2:
            return n * iv.log1p(val(iv))
        return n * iv.log(onep(iv))

    screened = _screen_exponent(fmt, lambda iv: log_of_result(iv) / iv.log(2),
                                0, rnd)
    if screened is not None:
        return screened

    lo, hi = _bounds(fmt, lambda iv: abs(log_of_result(iv)))
    if hi < 2.0 ** -(fmt.prec + 3):
        up = (not u.sign) != (n < 0)     # 1 + x is above 1 iff x is
        return _round_neighbour(fmt, one_bits(fmt, 0), away=up, rnd=rnd)

    # A DOMINANT operand, and the second family here that no working
    # precision reaches. For a large x the value is x^n times
    # (1 + 1/x)^n, and when x^n is itself an exact dyadic the correction
    # is below a quarter of the grid step there, so the side settles it -
    # exactly as hypot's dominant operand is settled. Without it,
    # compound(2^1022, 1) at binary64 is 2^1022 + 1: one unit above a
    # grid point whose ulp is 2^970.
    #
    # vexp(x) >= p + 2 + bits(|n|) makes |n/x| < 2^-(p+2), the binomial
    # tail is below 2(n/x)^2 and so below it again, and a quarter of the
    # relative grid step is 2^-(p+1). The correction's sign is n's,
    # because 1 + 1/x is above 1 for a positive x.
    if not u.sign and _vexp(u) >= fmt.prec + 2 + abs(n).bit_length():
        dom = _pown_dyadic(fmt, u.m, u.e, n)
        if dom is not None:
            dm, de = dom
            return _round_dyadic_side(fmt, 0, dm, de, away=(n > 0), rnd=rnd)

    def evaluate(iv):
        if _vexp(u) < -2:
            return iv.exp(n * iv.log1p(val(iv)))
        return iv.power(onep(iv), n)

    return _ziv(fmt, 0, evaluate, rnd)


def rootn(fmt: FpFormat, xa: int, n: int, rnd: int = RND_RNE):
    """x**(1/n) for a nonzero integer n. 9.2.1:

        rootn(x, 0)              invalid - 0 is outside the domain
        rootn(+-0, n) n < 0 odd  +-inf with divideByZero
        rootn(+-0, n) n < 0 even +inf with divideByZero
        rootn(+-0, n) n > 0 odd  +-0
        rootn(+-0, n) n > 0 even +0
        rootn(+-inf, n)          +-inf / +-0 for odd n, invalid for an
                                 even n and a negative operand
        x < 0 with an even n     invalid

    rootn(x, 1) is x, exactly and with no exception. rootn(x, 2) is
    squareRoot(x) on every input EXCEPT x = -0, where the standard's own
    NOTE says they differ: rootn(-0, 2) is +0 by the even-n row, where
    squareRoot(-0) is -0. host/tests/transcend_check.py tests both
    halves of that.

    EXACT exactly when the odd significand is a perfect |n|-th power and
    |n| divides the exponent - one verified integer root - with a
    negative n turning it into a reciprocal, which is dyadic only when
    that root is 1."""
    u = unpack(fmt, xa)

    if _has_snan(u):
        return qnan_bits(fmt), FLAG_INVALID
    if n == 0:
        # Table 9.1: "n = 0: invalid operation". 0 is outside the
        # domain for EVERY x, a quiet NaN included, and 9.2's general
        # rule for an operand outside the domain is invalid.
        return qnan_bits(fmt), FLAG_INVALID
    if u.kind == NAN:
        return qnan_bits(fmt), 0

    odd = bool(n & 1)
    if u.kind == ZERO:
        if n < 0:
            return inf_bits(fmt, 1 if (odd and u.sign) else 0), FLAG_DIVZERO
        return zero_bits(fmt, 1 if (odd and u.sign) else 0), 0
    if u.kind == INF:
        if u.sign and not odd:
            return qnan_bits(fmt), FLAG_INVALID
        if n > 0:
            return inf_bits(fmt, 1 if u.sign else 0), 0
        return zero_bits(fmt, 1 if u.sign else 0), 0
    if u.sign and not odd:
        return qnan_bits(fmt), FLAG_INVALID             # x < 0, n even

    if n == 1:
        STATS["exact"] += 1
        return xa, 0                                    # rootn(x, 1) = x

    sign = 1 if u.sign else 0
    exact = _rootn_dyadic(fmt, u, n)
    if exact is not None:
        m, e = exact
        STATS["exact"] += 1
        vexp = e + m.bit_length() - 1
        if vexp > fmt.emax:
            return _round_overflowing(fmt, sign, rnd)
        if vexp < fmt.emin - fmt.man_w - 1:
            return _round_underflowing(fmt, sign, rnd)
        return _round_exact(fmt, sign, m, e, rnd)

    val = _exact_value_iv(fmt, xa)

    def mag(iv):
        return abs(val(iv))

    def log_of_result(iv):
        return iv.log(mag(iv)) / n

    screened = _screen_exponent(fmt, lambda iv: log_of_result(iv) / iv.log(2),
                                sign, rnd)
    if screened is not None:
        return screened

    lo, hi = _bounds(fmt, lambda iv: abs(log_of_result(iv)))
    if hi < 2.0 ** -(fmt.prec + 3):
        # A large |n| drives every operand to 1; the side is the side of
        # 1 the operand is on, flipped by the sign of n.
        up = (_mag_gt_one(u) != (n < 0))
        return _round_neighbour(fmt, one_bits(fmt, sign), away=up, rnd=rnd)

    def evaluate(iv):
        if n == 2:
            return iv.sqrt(mag(iv))
        if n == -2:
            return iv.mpf(1) / iv.sqrt(mag(iv))
        if n == -1:
            return iv.mpf(1) / mag(iv)
        return iv.exp(iv.log(mag(iv)) / n)

    return _ziv(fmt, sign, evaluate, rnd)


# ---- dispatch --------------------------------------------------------

TRANSCEND_IMPL = {
    FN_EXP: exp,
    FN_EXPM1: expm1,
    FN_EXP2: exp2,
    FN_LOG: log,
    FN_LOG1P: log1p,
    FN_LOG2: log2,
    FN_LOG10: log10,
    FN_POW: pow,
    FN_HYPOT: hypot,
    FN_SINPI: sinpi,
    FN_COSPI: cospi,
    FN_TANPI: tanpi,
    FN_ASIN: asin,
    FN_ACOS: acos,
    FN_ATAN: atan,
    FN_ATAN2: atan2,
    FN_ASINPI: asinpi,
    FN_ACOSPI: acospi,
    FN_ATANPI: atanpi,
    FN_ATAN2PI: atan2pi,
    FN_SIN: sin,
    FN_COS: cos,
    FN_TAN: tan,
    FN_SINH: sinh,
    FN_COSH: cosh,
    FN_TANH: tanh,
    FN_ASINH: asinh,
    FN_ACOSH: acosh,
    FN_ATANH: atanh,
    FN_EXP2M1: exp2m1,
    FN_EXP10: exp10,
    FN_EXP10M1: exp10m1,
    FN_LOG2P1: log2p1,
    FN_LOG10P1: log10p1,
    FN_RSQRT: rsqrt,
    FN_POWN: pown,
    FN_POWR: powr,
    FN_COMPOUND: compound,
    FN_ROOTN: rootn,
}


def compute(fmt: FpFormat, fn: str, xa: int, xb: int = 0,
            rnd: int = RND_RNE, n: int = 0):
    """One case by function name - the shape the vector generator and
    the conformance replay both speak.

    `n` is the INTEGER operand of pown, compound and rootn, and is
    ignored by every other function. It is a separate parameter rather
    than a reuse of xb because it is a different kind of thing: xb is an
    encoding, n is an integer, and a vector set writes them under
    different keys for the same reason."""
    if fn not in TRANSCEND_IMPL:
        raise ValueError(f"unknown transcendental {fn!r}")
    if rnd not in RND_MODES:
        raise ValueError(f"bad rounding mode {rnd}; contract defines 0-4")
    impl = TRANSCEND_IMPL[fn]
    if TRANSCEND_INTARG[fn]:
        return impl(fmt, xa, int(n), rnd)
    if TRANSCEND_ARITY[fn] == 2:
        return impl(fmt, xa, xb, rnd)
    return impl(fmt, xa, rnd)
