# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""Division and square root as sequences of contract operations.

`softfloat.div` and `softfloat.sqrt` are the CONTRACT - what a caller
gets. This module is the IMPLEMENTATION ROUTE: the same results built
from a fixed sequence of the tile's own opcodes, which is what libcft
will issue to hardware. Every step below is a `compute()` call - if it
is not an opcode the engine has, it cannot appear here. The model-level
sequence and the device-level program are meant to be the same object
read at two speeds, exactly as CFT_DOT is MUL-then-SUM at both levels.

The construction is Markstein's: hardware supplies what FMA cannot -
the seed - and everything else is composition.

  sqrt:    y ~ 1/sqrt(a) from the seed, refined by Newton under RNE
           (y' = y*(1.5 - (a/2)*y*y); each step squares the error, so
           the count comes from the proven seed bound 2^-8.5: 2/3/4/5
           steps for fp32/64/128/256). Then s0 = a*y, h = y/2, the
           residual r = a - s0*s0 taken EXACTLY by one fma, and the
           final s = fma(r, h, s0) rounded once in the caller's
           attribute. Roots of finite positives can neither overflow
           nor land subnormal, which removes the range machinery.

  divide:  y ~ 1/b refined the same way (y' = y + y*(1 - b*y)), then
           q0 = a*y, the exact residual r = a - b*q0, and the final
           q = fma(r, y, q0) in the caller's attribute.

WHAT KEEPS THE SEQUENCES TOTAL:

  * specials never enter the core. Lanes whose operands are
    NaN/inf/zero take their contract results directly (the library
    decides by a classify pass and SELECT; the model, running
    elementwise, decides by the same predicate). The core therefore
    never computes inf*0, and dummy lanes are not needed at model
    level at all.
  * subnormal operands are pre-normalised by an exact power-of-two
    multiply before the core, and the result is rescaled by an exact
    power-of-two multiply after it. For sqrt the adjustment is kept
    even so the rescale is a single representable power and the
    rounding position is unchanged (the root of any subnormal is deep
    inside the normal range).
  * for division the operands are exponent-CENTRED (significand kept,
    exponent field replaced by the bias, via the integer ops on the
    encoding), the core computes the centred quotient qs in (1/2, 2),
    and the true result is qs * 2^D. D is assembled per lane into
    power-of-two floats by integer shifts on the encoding - never
    converted, never transcribed. The final fma runs at TRUE scale, so
    overflow and its flags fall out of the final rounding itself.
  * lanes whose true quotient lands SUBNORMAL cannot take that
    shortcut - rescaling q0 into the subnormal range would round
    before the final step. Those lanes finish by explicit bit surgery:
    the quotient correctly rounded RTZ at a normal scale, the sticky
    refreshed from an exact residual, then guard/sticky/attribute
    resolved with the integer ops at the target's reduced precision.

Flags: each library step is its own hardware run and FLAGS is per-run,
so the library keeps only the final step's flags and derives
invalid/divideByZero from operand classes. The model returns the same
(bits, flags) the contract functions do, and test_sequences.py holds
the two bit-identical across the full matrix.
"""

from .formats import FpFormat
from . import softfloat as sf
from .softfloat import (
    RND_RNE, RND_RTZ, RND_RDN, RND_RUP, RND_RMM,
    FLAG_INVALID, FLAG_DIVZERO, FLAG_INEXACT, FLAG_UNDERFLOW,
    OP_RECIP_SEED, OP_RSQRT_SEED,
    OP_FMA, OP_MUL, OP_NEG, OP_SUB, OP_ADD, OP_COPYSIGN,
    compute, unpack, NAN, INF, ZERO,
    zero_bits, one_bits, inf_bits, qnan_bits,
)

# Newton iteration counts, derived from the proven seed bound 2^-8.5.
_NEWTON = {24: 2, 53: 3, 113: 4, 237: 5}


def _op(fmt, op, a, b=None, c=None, rnd=RND_RNE):
    """One sequence step. Everything funnels through here so the step
    list is auditable and any step's flags can be kept or dropped."""
    z = zero_bits(fmt)
    return compute(fmt, op, a, z if b is None else b,
                   z if c is None else c, rnd)


def _v(fmt, op, a, b=None, c=None, rnd=RND_RNE):
    """A scaffolding step: value kept, flags discarded."""
    bits, _ = _op(fmt, op, a, b, c, rnd)
    return bits


def _pow2_bits(fmt, e: int) -> int:
    """The float 2^e as bits; e must be in the normal range."""
    assert fmt.emin <= e <= fmt.emax, e
    return (e + fmt.bias) << fmt.man_w


# ---- square root -----------------------------------------------------

def _sqrt_core(fmt: FpFormat, acen: int, D2: int, rnd: int):
    """Floor-and-measured-guard square root of a CENTRED operand in
    [1, 4), delivered at true scale 2^D2 by round_pack. Symmetric with
    the division finish, and for the same reason: every construction
    that finished with a rounded correction eventually landed on a
    fabricated midpoint in some family (the matrix found one per
    attempt), and the cure both times is to MEASURE the rounding
    information instead of synthesising it.

      * s is driven to floor(sqrt(acen)) at p bits: Newton plus one RNE
        correction lands within half an ulp (which is what makes the
        residual exactly representable - Markstein's lemma, valid here
        BECAUSE the operand is centred; the matrix caught it failing at
        raw scale near the bottom of the range), and a restore step
        against the exact residual's sign settles floor by
        construction.
      * guard is the sign of the exact midpoint discriminant
        d = acen - (s + u/2)^2, computed as r - s*u - u^2/4 in three
        exact steps (each value lies on the centred 2^(2-2p) grid with
        a coefficient of at most 2^p, so each subtraction is a single
        rounding of a representable value - i.e. exact). d = 0 is
        unreachable: a true root on a p+1-bit midpoint would need its
        square, a 2p+1-bit number, to equal a p-bit operand.
      * sticky: guard high forces sticky (the root is never ON the
        midpoint); guard low, sticky is just r != 0.

    round_pack then rounds once, at the true position, under the
    caller's attribute. Roots of finite positives are always normal,
    so no clamping ever engages - but the flags come from the same
    authority as everything else."""
    half = _pow2_bits(fmt, -1)
    three_half = (fmt.bias << fmt.man_w) | (1 << (fmt.man_w - 1))  # 1.5

    assert ((acen >> fmt.man_w) & fmt.exp_mask) != 0  # see recip note
    y = _v(fmt, OP_RSQRT_SEED, acen)
    nah = _v(fmt, OP_MUL, _v(fmt, OP_NEG, acen), half)   # -(a/2), exact
    for _ in range(_NEWTON[fmt.man_w + 1]):
        yy = _v(fmt, OP_MUL, y, y)
        t = _v(fmt, OP_FMA, nah, yy, three_half)
        y = _v(fmt, OP_MUL, y, t)
    s0 = _v(fmt, OP_MUL, acen, y)
    h0 = _v(fmt, OP_MUL, y, half)
    r0 = _v(fmt, OP_FMA, _v(fmt, OP_NEG, s0), s0, acen)  # exact
    s1 = _v(fmt, OP_FMA, r0, h0, s0)                     # within 1/2 ulp

    # Restore to floor: at most one ulp step either way, decided by
    # exact residual signs. (IADD/ISUB on the encoding in the library;
    # the encoding is monotone, so the step crosses binades correctly.)
    for _ in range(2):
        r = _v(fmt, OP_FMA, _v(fmt, OP_NEG, s1), s1, acen)
        if ((r >> (fmt.width - 1)) & 1) and r != zero_bits(fmt, 1):
            s1 -= 1
            continue
        sp = s1 + 1
        rp = _v(fmt, OP_FMA, _v(fmt, OP_NEG, sp), sp, acen)
        if not ((rp >> (fmt.width - 1)) & 1):
            s1 = sp
            continue
        break

    r = _v(fmt, OP_FMA, _v(fmt, OP_NEG, s1), s1, acen)   # exact, >= 0
    us = unpack(fmt, s1)
    if r in (zero_bits(fmt, 0), zero_bits(fmt, 1)):
        guard, sticky = 0, 0
    else:
        su = _v(fmt, OP_MUL, s1, _pow2_bits(fmt, us.e))          # exact
        d1 = _v(fmt, OP_SUB, r, c=su)                            # exact
        d2 = _v(fmt, OP_SUB, d1, c=_pow2_bits(fmt, 2 * us.e - 2))
        guard = 0 if ((d2 >> (fmt.width - 1)) & 1) else 1
        # r != 0 here, and an inexact root is never ON a representable
        # or a midpoint, so something nonzero always lies below the
        # guard: sticky is 1 unconditionally in this branch.
        sticky = 1

    m = (us.m << 2) | (guard << 1) | sticky
    e = us.e - 2 + D2
    return sf.round_pack(fmt, 0, m, e, rnd)


def sqrt_seq(fmt: FpFormat, xa: int, rnd: int = RND_RNE):
    """squareRoot(a) as the op sequence. Bit-identical to sf.sqrt.

    The core runs CENTRED, on a value in [1, 4) with the true
    exponent's parity folded in, for the same reason division centres:
    Markstein's residual-exactness lemma (a - s^2 representable in p
    bits) holds when a and s live in adjacent fixed binades, and the
    matrix caught it failing at raw scale - near the bottom of the
    range the exact residual needs bits below the representable floor,
    sqrt(max_subnormal) claimed exactness, and RTZ came back a ulp
    high. Centring makes the lemma's grid argument true by
    construction, and the rescale by 2^((E - odd)/2) is a single exact
    representable power because a root's exponent is half its
    operand's."""
    ua = unpack(fmt, xa)
    if ua.kind == NAN:
        return sf.sqrt(fmt, xa, rnd)          # contract NaN handling
    if ua.kind == ZERO:
        return xa, 0
    if ua.sign:
        return qnan_bits(fmt), FLAG_INVALID
    if ua.kind == INF:
        return xa, 0

    p = fmt.prec
    k2 = p + (p & 1)                          # even prenorm shift
    adj = 0
    a_eff = xa
    if ((xa >> fmt.man_w) & fmt.exp_mask) == 0:
        a_eff = _v(fmt, OP_MUL, xa, _pow2_bits(fmt, k2))   # exact
        adj = -(k2 // 2)

    biased = (a_eff >> fmt.man_w) & fmt.exp_mask
    E = biased - fmt.bias
    odd = E & 1
    acen = (a_eff & fmt.man_mask) | (fmt.bias << fmt.man_w)
    if odd:
        acen = _v(fmt, OP_MUL, acen, _pow2_bits(fmt, 1))   # exact, [2,4)

    return _sqrt_core(fmt, acen, (E - odd) // 2 + adj, rnd)


# ---- division --------------------------------------------------------

def _refine_recip(fmt: FpFormat, b_eff: int):
    """Newton-refined reciprocal of a normal operand, under RNE."""
    one = one_bits(fmt)
    # The seed spec flushes subnormal INPUTS (hardware economics; see
    # recip_seed). The sequences must therefore never seed one - and
    # never do, because operands are prenormalised and centred first.
    # Asserted, not assumed.
    assert ((b_eff >> fmt.man_w) & fmt.exp_mask) != 0
    y = _v(fmt, OP_RECIP_SEED, b_eff)
    nb = _v(fmt, OP_NEG, b_eff)
    for _ in range(_NEWTON[fmt.man_w + 1]):
        e = _v(fmt, OP_FMA, nb, y, one)                    # 1 - b*y
        y = _v(fmt, OP_FMA, y, e, y)                       # y + y*e
    return y


def _centre(fmt: FpFormat, x: int):
    """(centred bits, true unbiased exponent) - significand kept, the
    exponent field replaced by the bias. Callers guarantee x is finite,
    nonzero and NORMAL. In the library this is IAND/IOR with constant
    masks; the model does the same arithmetic on the same fields."""
    biased = (x >> fmt.man_w) & fmt.exp_mask
    assert biased not in (0, fmt.exp_mask)
    # The sign is STRIPPED: the whole finish reasons about positive
    # magnitudes (residual signs, floor, guard), and the quotient's
    # sign is applied exactly once, by round_pack at the end. Keeping
    # the sign here ran the positive-geometry restore on negative
    # values, and every negative-divisor lane came back one ulp large.
    centred = (x & fmt.man_mask) | (fmt.bias << fmt.man_w)
    return centred, biased - fmt.bias


def div_seq(fmt: FpFormat, xa: int, xb: int, rnd: int = RND_RNE):
    """division(a, b) as the op sequence. Bit-identical to sf.div."""
    ua, ub = unpack(fmt, xa), unpack(fmt, xb)

    # Contract specials, decided by operand class - never computed.
    if NAN in (ua.kind, ub.kind):
        return sf.div(fmt, xa, xb, rnd)
    sq = ua.sign ^ ub.sign
    if ua.kind == INF:
        if ub.kind == INF:
            return qnan_bits(fmt), FLAG_INVALID
        return inf_bits(fmt, sq), 0
    if ub.kind == INF:
        return zero_bits(fmt, sq), 0
    if ub.kind == ZERO:
        if ua.kind == ZERO:
            return qnan_bits(fmt), FLAG_INVALID
        return inf_bits(fmt, sq), FLAG_DIVZERO
    if ua.kind == ZERO:
        return zero_bits(fmt, sq), 0

    p = fmt.prec

    # Pre-normalise subnormal operands (exact), tracking the shift in D.
    d_adj = 0
    a_eff, b_eff = xa, xb
    if ((xa >> fmt.man_w) & fmt.exp_mask) == 0:
        a_eff = _v(fmt, OP_MUL, xa, _pow2_bits(fmt, p))
        d_adj -= p
    if ((xb >> fmt.man_w) & fmt.exp_mask) == 0:
        b_eff = _v(fmt, OP_MUL, xb, _pow2_bits(fmt, p))
        d_adj += p

    # Centre both operands: the true quotient is (ac/bc) * 2^D with
    # ac/bc in (1/2, 2), so the result exponent is D or D-1.
    ac, ea = _centre(fmt, a_eff)
    bc, eb = _centre(fmt, b_eff)
    D = ea - eb + d_adj

    y = _refine_recip(fmt, bc)

    # ONE path for every lane, chosen for provability over speed.
    #
    # Two earlier constructions each failed a family the matrix found.
    # A mode-rounded Markstein finish fails the exact-tie family (a=1,
    # b=1-ulp: the correction lands exactly on the RNE tie while the
    # true quotient sits 2^-2p above it). A doubled-dividend truncation
    # was meant to carry one bit below the target position, but when
    # the doubled quotient crosses into the next binade its ulp doubles
    # too and the extra bit evaporates - the fold then fabricates a tie
    # at exactly the normal/subnormal boundary. Both failures share a
    # root: manufacturing rounding information that was never computed.
    #
    # This construction computes it:
    #
    #   * q2 = floor(ac/bc) to p bits, by a truncating Markstein finish
    #     (RTZ has no ties) plus a RESTORE step - the exact residual's
    #     sign says whether the truncation missed floor by one ulp, and
    #     one conditional ulp step on the encoding fixes it. Floor is
    #     then exact BY CONSTRUCTION, not by margin argument.
    #   * the GUARD bit is measured, not folded: with r2 the exact
    #     remainder in [0, bc*ulp), one exact fma against bc*(ulp/2)
    #     gives d = r2 - bc*ulp/2, whose sign is the guard and whose
    #     zeroness separates an exact tie from above-tie. The sticky is
    #     the remaining nonzeroness. Both are real quantities.
    #   * round_pack - the contract's own authority - then performs the
    #     single rounding at the true position under the caller's
    #     attribute, fed a mantissa carrying the true guard and sticky:
    #     subnormal clamping, tininess and per-attribute overflow
    #     delivery included.
    #
    # In the library every piece is contract ops: the restore and the
    # guard test are fma-sign checks (ICMPLT on the result), the ulp
    # steps are IADD on the encoding (monotone across binades), and the
    # finish is the integer surgery the module docstring describes. The
    # model states the same arithmetic directly.
    nbc = _v(fmt, OP_NEG, bc)
    q02 = _v(fmt, OP_MUL, ac, y)
    r0 = _v(fmt, OP_FMA, nbc, q02, ac)               # exact
    q1 = _v(fmt, OP_FMA, r0, y, q02)                 # RNE tighten
    r1 = _v(fmt, OP_FMA, nbc, q1, ac)                # exact
    q2 = _v(fmt, OP_FMA, r1, y, q1, rnd=RND_RTZ)     # truncate, no ties

    for _ in range(2):
        r2 = _v(fmt, OP_FMA, nbc, q2, ac)            # exact
        neg = (r2 >> (fmt.width - 1)) & 1
        if neg and r2 != zero_bits(fmt, 1):
            q2 -= 1                                  # one ulp down
            continue
        u2 = unpack(fmt, q2)
        room = _v(fmt, OP_FMA, nbc, _pow2_bits(fmt, u2.e), r2)
        if not ((room >> (fmt.width - 1)) & 1) and                 room != zero_bits(fmt, 0):
            q2 += 1                                  # one ulp up
            continue
        break

    r2 = _v(fmt, OP_FMA, nbc, q2, ac)                # exact remainder
    u2 = unpack(fmt, q2)
    if r2 in (zero_bits(fmt, 0), zero_bits(fmt, 1)):
        guard, sticky = 0, 0
    else:
        d = _v(fmt, OP_FMA, nbc, _pow2_bits(fmt, u2.e - 1), r2)
        dneg = (d >> (fmt.width - 1)) & 1
        if d in (zero_bits(fmt, 0), zero_bits(fmt, 1)):
            guard, sticky = 1, 0                     # exact tie
        elif dneg:
            guard, sticky = 0, 1                     # below the midpoint
        else:
            guard, sticky = 1, 1                     # above the midpoint

    m = (u2.m << 2) | (guard << 1) | sticky
    e = u2.e + D - 2
    return sf.round_pack(fmt, sq, m, e, rnd)


# ---- roundToIntegral as a sequence -----------------------------------

def rint_seq(fmt: FpFormat, xa: int, rnd: int = RND_RNE,
             exact: bool = False):
    """roundToIntegral as backend passes. Bit-identical to sf.round_int.

    The construction is the classic magic-constant addition, made
    total: with C = 2^(p-1) carrying the operand's sign,

        t = (x + copysign(C, x)) - copysign(C, x)

    rounds x at integer weight under the caller's own attribute - the
    sum lands in [C, 2C), where the format's ulp is exactly 1, and the
    subtraction is exact by Sterbenz's bound. A final copySign restores
    the operand's sign so the zero of roundToIntegral(-0.4) comes back
    -0, which the trick alone loses.

    What the passes cannot do, the library does per element in integer
    bookkeeping, exactly as cft_div does:

      * lanes with biased exponent >= bias + (p-1) are already integral
        (their ulp is >= 1) AND would break the trick's Sterbenz
        argument, so their original bits are substituted - a test that
        also catches the infinities;
      * NaN lanes take the contract result directly (the final copySign
        pass would otherwise stamp the operand's sign onto the
        canonical quiet NaN);
      * flags are synthesised, not accumulated: the adds raise inexact
        as scaffolding, but the named roundToIntegral operations signal
        nothing except invalid for sNaN, and the Exact variant's
        inexact is precisely "did the bits change on a finite lane".
    """
    ua = unpack(fmt, xa)
    if ua.kind == NAN:
        return sf.round_int(fmt, xa, rnd, exact)
    ef = (xa >> fmt.man_w) & fmt.exp_mask
    if ua.kind == INF or ef >= fmt.bias + fmt.man_w:
        return xa, 0
    cbits = _pow2_bits(fmt, fmt.man_w)               # 2^(p-1)
    m = _v(fmt, OP_COPYSIGN, cbits, xa)
    t = _v(fmt, OP_ADD, xa, c=m, rnd=rnd)
    u = _v(fmt, OP_SUB, t, c=m, rnd=rnd)
    r = _v(fmt, OP_COPYSIGN, u, xa)
    flags = FLAG_INEXACT if (exact and r != xa) else 0
    return r, flags


# ---- scaleB as a sequence --------------------------------------------

def _scale_factor_bits(fmt: FpFormat, e: int) -> int:
    """The float 2^e as bits, subnormal encodings included - every one
    of them exact, which is what makes a multiply by it a SINGLE
    rounding of the true scaled value."""
    if e >= fmt.emin:
        return _pow2_bits(fmt, e)
    lo = fmt.emin - fmt.man_w
    assert e >= lo, e
    return 1 << (e - lo)


def scaleb_seq(fmt: FpFormat, xa: int, n: int, rnd: int = RND_RNE):
    """scaleB as backend passes. Bit-identical to sf.scaleb.

    One multiply by the exact float 2^n whenever that float exists
    (n down to emin - (p-1), the smallest subnormal): the factor is
    exact, so the multiply IS scaleB - one rounding, and the mul's own
    flags are the contract flags, invalid-on-sNaN included. Above emax
    the factor is staged in chunks of 2^emax; every chunk but the last
    is exact for every lane (any finite value times 2^emax is normal or
    overflows, and an overflow there means the true result overflows
    too, with the per-attribute saturation delivering the same bits at
    every subsequent stage). Flags are the OR of the stages: pre-final
    stages contribute either nothing or the true overflow.

    BELOW the smallest subnormal power there is no exact factor and no
    safe uniform staging - a lane driven inexactly subnormal mid-chain
    would round twice, and the matrix that killed the div shortcuts
    would kill this one. Those calls (|n| beyond ~emax + p, far outside
    any real use) take the contract path on the host instead, exactly
    as special lanes do everywhere else in this module.
    """
    ua = unpack(fmt, xa)
    if ua.kind == NAN:
        return sf.scaleb(fmt, xa, n, rnd)
    if ua.kind in (INF, ZERO):
        return xa, 0
    if n < fmt.emin - fmt.man_w:
        return sf.scaleb(fmt, xa, n, rnd)            # the host path
    # Beyond 3*emax every nonzero finite lane saturates identically
    # (the full exponent span is 2*emax + p - 1 and emax >= p on every
    # rung of the ladder), so the chunk walk is bounded at three.
    remaining = min(n, 3 * fmt.emax)
    x, flags = xa, 0
    while True:
        step = min(remaining, fmt.emax)
        x, fl = _op(fmt, OP_MUL, x, _scale_factor_bits(fmt, step), rnd=rnd)
        flags |= fl
        remaining -= step
        if remaining == 0:
            return x, flags
