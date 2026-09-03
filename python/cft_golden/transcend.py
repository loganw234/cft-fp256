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

#: Canonical order - the ABI's, the vector sets', the docs'.
TRANSCEND_FNS = (FN_EXP, FN_EXPM1, FN_EXP2, FN_LOG, FN_LOG1P, FN_LOG2,
                 FN_LOG10, FN_POW, FN_HYPOT)

#: How many operands each reads.
TRANSCEND_ARITY = {fn: (2 if fn in (FN_POW, FN_HYPOT) else 1)
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
}


def compute(fmt: FpFormat, fn: str, xa: int, xb: int = 0,
            rnd: int = RND_RNE):
    """One case by function name - the shape the vector generator and
    the conformance replay both speak."""
    if fn not in TRANSCEND_IMPL:
        raise ValueError(f"unknown transcendental {fn!r}")
    if rnd not in RND_MODES:
        raise ValueError(f"bad rounding mode {rnd}; contract defines 0-4")
    impl = TRANSCEND_IMPL[fn]
    if TRANSCEND_ARITY[fn] == 2:
        return impl(fmt, xa, xb, rnd)
    return impl(fmt, xa, rnd)
