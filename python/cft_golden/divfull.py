# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""The WHOLE divide, and the whole square root, as one sequencer program
each: prep, core and finish on the chip, the contract's bits and flags
deposited per lane.

seqprogs.py splits the composed divide three ways - host prep on the
operand bits, one program run over the core, host finish from three
deposits - and a device pays for the split per element: a staged pass,
a 3-deposit read-back and two host loops of encoding surgery. Measured
by cft-rebound at 1.6 us an element at binary128 against 4.3 ns for an
FMA on the same tile, with "fix the divide" second on their list for
the card (docs/ROADMAP.md, workload ask 8). This module moves both
host halves into the instruction stream, so a program takes the RAW
operands in r0 (and r1) and deposits two words a lane: the correctly
rounded result and its five IEEE flags. The host copies one and ORs
the other; nothing per element is computed off the chip.

What the prep does on the chip, branchlessly. Class is read off the
encoding with IAND and unsigned ICMPLT (the comparison opcodes answer
1.0 or +0.0, which SELECT consumes as a predicate and which compose as
AND/OR/NOT through SELECT alone). The specials are answered from class
in softfloat's priority order - for the divide NaN, then inf/x, x/inf,
x/0, 0/x; for the root NaN, zero, negative, +inf - by a chain of SELECTs
that leaves the special lane's bits and flags in two registers, and
the same lane's core operand is forced to 1.0 so the core computes
1/1 or sqrt(1) and raises nothing. A subnormal operand is scaled by a
power of two through the FMA path (exact) and the scale is folded into
D, the true exponent; centring is IAND/IOR with the mask and the bias,
as sequences._centre says the library does it, and the root's odd
exponent is a MUL by 2.0 into [2, 4).

What the finish does is softfloat.round_pack, restated for the one
shape it meets here: a p+2-bit magnitude m4 = (the core result's
significand << 2 | guard << 1 | sticky) at exponent e, so the rounding
position is max(2, emin - p + 1 - e) bits up. Everything round_pack
derives with bit_length() is derived here from that one shift instead:
the normal path packs with the carry-out riding into the exponent field
(IADD, not a case), the subnormal path's kept IS the fraction field,
and tininess-after-rounding is the one configuration where the
unbounded rounding carries a value at emin - 1 up to emin. The rounding
mode is DATA - five 0/1 words at the end of a per-run constant bank
(BANK_EXT) - because an instruction's rounding attribute is static and
the caller's is not; one image a format, the mode rides with the run.

Held to the contract by test_divfull.py: bits AND flags against
softfloat.div and softfloat.sqrt, every format, every attribute, the
pool test_sequences uses, the named hard families, every special
pairing, and the subnormal boundary where tininess is decided.
"""

from .formats import FpFormat
from . import seq
from .softfloat import (
    RND_RNE, RND_RTZ, RND_RDN, RND_RUP, RND_RMM,
    OP_MUL, OP_SELECT,
    OP_IAND, OP_IOR, OP_IXOR, OP_ISUB, OP_IADD, OP_ISHL, OP_ISHR,
    OP_ICMPLT,
    qnan_bits, inf_bits, max_normal_bits,
    FLAG_INVALID, FLAG_DIVZERO, FLAG_OVERFLOW, FLAG_UNDERFLOW,
    FLAG_INEXACT,
)
from .sequences import _pow2_bits
from .seqprogs import (
    _consts_div, _consts_sqrt, _div_core, _sqrt_core, _Q, _T2, _UP, _TMP,
    K_ZERO, K_ONE, K_INT1, K_EXP,
)

# ---- the constant banks -----------------------------------------------
# A program's core constants first (indices 0..5 for the divide, 0..8
# for the root, so seqprogs' K_* names hold inside the cores), then the
# words the prep and the finish share, then the root's own, then the
# five mode words LAST - the library appends those. Named in order; the
# numbers are never written by hand.

_TAIL = (
    "K_SIGN", "K_MAN", "K_QBIT", "K_EXPM1", "K_P2P", "K_NEGP",
    "K_POSP", "K_MANW",                                             # prep
    "K_QNAN", "K_INF", "K_INVALID", "K_DIVZERO", "K_INEXACT",
    "K_INXUND", "K_OVFINX",                                         # answers
    "K_HIDDEN", "K_TWO", "K_EOFF", "K_SUBQ", "K_P3", "K_TWO_S",
    "K_P1", "K_BIAS", "K_MAXN", "K_HALFP", "K_TOPU", "K_EMAX_S",
    "K_ABSM", "K_W1", "K_THREE", "K_FOUR",                          # finish
)
_MODES = ("K_RNE", "K_RTZ", "K_RDN", "K_RUP", "K_RMM")
_NAMES_DIV = ("K_ZERO", "K_ONE", "K_INT1", "K_EXP", "K_MW", "K_MW1") + _TAIL + _MODES
_NAMES_SQRT = (("K_ZERO", "K_ONE", "K_INT1", "K_EXP", "K_MW", "K_MW1",
                "K_HALF", "K_3H", "K_SQ") + _TAIL
               + ("K_P2K2", "K_NEGK2H", "K_QUART", "K_TWOF") + _MODES)
KD = {name: i for i, name in enumerate(_NAMES_DIV)}
KS = {name: i for i, name in enumerate(_NAMES_SQRT)}
N_CONSTS = len(_NAMES_DIV)            # the divide's bank
N_CONSTS_SQRT = len(_NAMES_SQRT)
N_MODES = len(_MODES)
for _K in (KD, KS):
    assert _K["K_ZERO"] == K_ZERO and _K["K_ONE"] == K_ONE
    assert _K["K_INT1"] == K_INT1 and _K["K_EXP"] == K_EXP


def _tail(fmt: FpFormat):
    w, p, man_w = fmt.width, fmt.prec, fmt.man_w
    full = (1 << w) - 1

    def s(v):                      # a signed integer in width bits
        return v & full

    return [
        fmt.sign_mask,                             # K_SIGN
        fmt.man_mask,                              # K_MAN
        1 << (man_w - 1),                          # K_QBIT   the quiet bit
        (fmt.exp_mask << man_w) - 1,               # K_EXPM1  field == all ones test
        _pow2_bits(fmt, p),                        # K_P2P    2^p, the subnormal scale
        s(-p),                                     # K_NEGP
        p,                                         # K_POSP
        man_w,                                     # K_MANW   the field shift
        qnan_bits(fmt),                            # K_QNAN
        inf_bits(fmt),                             # K_INF
        FLAG_INVALID,                              # K_INVALID
        FLAG_DIVZERO,                              # K_DIVZERO
        FLAG_INEXACT,                              # K_INEXACT
        FLAG_INEXACT | FLAG_UNDERFLOW,             # K_INXUND
        FLAG_OVERFLOW | FLAG_INEXACT,              # K_OVFINX
        1 << man_w,                                # K_HIDDEN
        2,                                         # K_TWO
        fmt.bias + man_w + 2,                      # K_EOFF   e = ef(q) + D - EOFF
        s(fmt.emin - p + 1),                       # K_SUBQ   the subnormal grid
        p + 3,                                     # K_P3     the shift clamp
        2 | fmt.sign_mask,                         # K_TWO_S  2, in signed-compare order
        p + 1,                                     # K_P1     e_norm = e + p + 1
        fmt.bias,                                  # K_BIAS
        max_normal_bits(fmt),                      # K_MAXN
        1 << (p - 1),                              # K_HALFP  the hidden bit of kept
        1 << p,                                    # K_TOPU   kept's carry-out value
        fmt.emax | fmt.sign_mask,                  # K_EMAX_S emax, in signed-compare order
        full ^ fmt.sign_mask,                      # K_ABSM   magnitude mask
        w - 1,                                     # K_W1     the sign's shift
        3,                                         # K_THREE
        4,                                         # K_FOUR
    ]


def _modes(rnd: int):
    return [int(rnd == RND_RNE), int(rnd == RND_RTZ), int(rnd == RND_RDN),
            int(rnd == RND_RUP), int(rnd == RND_RMM)]


def bank(fmt: FpFormat, rnd: int):
    """The divide's run constants: derived from the format's fields and
    the caller's attribute, never transcribed."""
    vals = list(_consts_div(fmt)) + _tail(fmt) + _modes(rnd)
    assert len(vals) == N_CONSTS
    return vals


def bank_sqrt(fmt: FpFormat, rnd: int):
    """The root's: the same tail, plus the even scale 2^k2 for a
    subnormal operand, half of it as the exponent adjustment, the
    quarter-range offset that makes a signed halving a logical shift,
    and 2.0 for an odd exponent."""
    p = fmt.prec
    k2 = p + (p & 1)
    full = (1 << fmt.width) - 1
    vals = (list(_consts_sqrt(fmt)) + _tail(fmt) + [
        _pow2_bits(fmt, k2),                       # K_P2K2
        (-(k2 // 2)) & full,                       # K_NEGK2H
        1 << (fmt.width - 2),                      # K_QUART
        _pow2_bits(fmt, 1),                        # K_TWOF   2.0
    ] + _modes(rnd))
    assert len(vals) == N_CONSTS_SQRT
    return vals


# ---- register map -----------------------------------------------------
# r0/r1 are the raw operand streams (r2, the c stream, is free and holds
# the sign predicate); the cores own r3..r12 and run on r12/r13 (the
# divide) or r13 (the root); r14..r18 carry the prep's results across
# the core; r19..r31 are scratch for the prep and, after the core, for
# the finish along with r3..r5, r8, r9, r11..r13.

_RA, _RB = 0, 1
_AC, _BC, _D, _SQ, _SPEC, _SBITS, _SFL = 12, 13, 14, 15, 16, 17, 18
# The sign as a PREDICATE: SELECT tests its condition's magnitude, so
# the sign bit alone reads as false; the directed modes and 7.4's
# overflow rule take this 0/1 word instead. r2 is the unused c stream.
_SGN = 2


def _k(op, rd, ra=0, rb=0, rc=0, ka=False, kb=False, kc=False, rnd=RND_RNE):
    """seq.alu with kx chosen for it: a constant index past 15 needs
    the kx form, and nothing here should have to remember which."""
    kx = any(f and v >= seq.KADDR_PLAIN
             for v, f in ((ra, ka), (rb, kb), (rc, kc)))
    return seq.alu(op, rd, ra, rb, rc, rnd=rnd, ka=ka, kb=kb, kc=kc, kx=kx)


def _classify(p, K, src, nan, inf, zero, sub, snan):
    """The operand in `src` by class, into five 1.0/0.0 predicates;
    r19..r21 scratch."""
    k = _k
    Z, I1 = K["K_ZERO"], K["K_INT1"]
    p += [
        k(OP_IAND, 19, src, K["K_EXP"], kb=True),            # exponent field
        k(OP_IAND, 20, src, K["K_MAN"], kb=True),            # fraction field
        k(OP_ICMPLT, 21, 20, I1, kb=True),                   # fraction == 0
        k(OP_ICMPLT, 20, K["K_EXPM1"], 19, ka=True),         # field == all ones
        k(OP_ICMPLT, 19, 19, I1, kb=True),                   # field == 0
        k(OP_SELECT, nan, Z, 20, 21, ka=True),               # ones & frac != 0
        k(OP_SELECT, inf, 20, Z, 21, kb=True),               # ones & frac == 0
        k(OP_SELECT, zero, 19, Z, 21, kb=True),              # zero & frac == 0
        k(OP_SELECT, sub, Z, 19, 21, ka=True),               # zero & frac != 0
        k(OP_IAND, 19, src, K["K_QBIT"], kb=True),
        k(OP_ICMPLT, 19, 19, I1, kb=True),                   # quiet bit clear
        k(OP_SELECT, snan, nan, Z, 19, kb=True),             # nan & not quiet
    ]
    return p


def _prep_div(p, K):
    """Class, specials, scaling, centring: raw r0/r1 -> _AC/_BC (1.0 on
    a special lane), _D, _SQ, _SGN, _SPEC, _SBITS, _SFL."""
    k = _k
    Z, ONE, I1 = K["K_ZERO"], K["K_ONE"], K["K_INT1"]
    p += [
        k(OP_IAND, 19, _RA, K["K_SIGN"], kb=True),
        k(OP_IAND, 20, _RB, K["K_SIGN"], kb=True),
        k(OP_IXOR, _SQ, 19, 20),                            # the quotient's sign, in place
        k(OP_ISHR, _SGN, _SQ, K["K_W1"], kb=True),          # and as 0/1
    ]
    # class of a -> a_nan 22, a_inf 23, a_zero 24, a_sub 25, a_snan 26
    # class of b -> b_nan 27, b_inf 28, b_zero 29, b_sub 30, b_snan 31
    _classify(p, K, _RA, 22, 23, 24, 25, 26)
    _classify(p, K, _RB, 27, 28, 29, 30, 31)
    p += [
        k(OP_SELECT, 22, ONE, 27, 22, ka=True),              # any_nan  -> 22
        k(OP_SELECT, 26, ONE, 31, 26, ka=True),              # any snan -> 26
        # the special lane's answer, built in reverse priority so the
        # last SELECT that fires is softfloat.div's first test
        k(OP_IOR, _SBITS, _SQ, Z, kb=True),                  # 0/x: zero(sq)
        k(OP_IAND, _SFL, _RA, Z, kb=True),                   # no flags
        # x/0: 0/0 is NaN invalid, else inf(sq) divzero
        k(OP_IOR, 27, _SQ, K["K_INF"], kb=True),
        k(OP_SELECT, 27, K["K_QNAN"], 27, 24, ka=True),
        k(OP_SELECT, _SBITS, 27, _SBITS, 29),
        k(OP_SELECT, 31, K["K_INVALID"], K["K_DIVZERO"], 24, ka=True, kb=True),
        k(OP_SELECT, _SFL, 31, _SFL, 29),
        # x/inf: zero(sq), no flag
        k(OP_SELECT, _SBITS, _SQ, _SBITS, 28),
        k(OP_SELECT, _SFL, Z, _SFL, 28, ka=True),
        # inf/x: inf/inf is NaN invalid, else inf(sq)
        k(OP_IOR, 27, _SQ, K["K_INF"], kb=True),
        k(OP_SELECT, 27, K["K_QNAN"], 27, 28, ka=True),
        k(OP_SELECT, _SBITS, 27, _SBITS, 23),
        k(OP_SELECT, 31, K["K_INVALID"], Z, 28, ka=True, kb=True),
        k(OP_SELECT, _SFL, 31, _SFL, 23),
        # a NaN anywhere: the canonical quiet NaN, invalid iff signaling
        k(OP_SELECT, _SBITS, K["K_QNAN"], _SBITS, 22, ka=True),
        k(OP_SELECT, 31, K["K_INVALID"], Z, 26, ka=True, kb=True),
        k(OP_SELECT, _SFL, 31, _SFL, 22),
        # is the lane special at all
        k(OP_SELECT, _SPEC, ONE, 24, 29, ka=True),
        k(OP_SELECT, _SPEC, ONE, _SPEC, 28, ka=True),
        k(OP_SELECT, _SPEC, ONE, _SPEC, 23, ka=True),
        k(OP_SELECT, _SPEC, ONE, _SPEC, 22, ka=True),
        # subnormal operands scaled by 2^p, exactly, the scale into D
        k(OP_MUL, 19, _RA, K["K_P2P"], kb=True),
        k(OP_SELECT, 19, 19, _RA, 25),                       # a_eff
        k(OP_MUL, 20, _RB, K["K_P2P"], kb=True),
        k(OP_SELECT, 20, 20, _RB, 30),                       # b_eff
        k(OP_SELECT, 21, K["K_NEGP"], Z, 25, ka=True, kb=True),
        k(OP_SELECT, 22, K["K_POSP"], Z, 30, ka=True, kb=True),
        k(OP_IADD, _D, 21, 22),                              # d_adj
        k(OP_IAND, 21, 19, K["K_EXP"], kb=True),
        k(OP_ISHR, 21, 21, K["K_MANW"], kb=True),            # biased exponent of a_eff
        k(OP_IAND, 22, 20, K["K_EXP"], kb=True),
        k(OP_ISHR, 22, 22, K["K_MANW"], kb=True),            # of b_eff
        k(OP_ISUB, 21, 21, 22),
        k(OP_IADD, _D, _D, 21),                              # D = ea - eb + d_adj
        # centre: significand kept, the field replaced by the bias
        k(OP_IAND, _AC, 19, K["K_MAN"], kb=True),
        k(OP_IOR, _AC, _AC, ONE, kb=True),
        k(OP_IAND, _BC, 20, K["K_MAN"], kb=True),
        k(OP_IOR, _BC, _BC, ONE, kb=True),
        # a special lane divides 1 by 1 and raises nothing
        k(OP_SELECT, _AC, ONE, _AC, _SPEC, ka=True),
        k(OP_SELECT, _BC, ONE, _BC, _SPEC, ka=True),
    ]
    return p


def _prep_sqrt(p, K):
    """The root's prep: raw r0 -> _BC (the centred operand in [1, 4),
    1.0 on a special lane), _D (half the true exponent), _SPEC, _SBITS,
    _SFL; the sign words are zero, a root is never negative."""
    k = _k
    Z, ONE, I1 = K["K_ZERO"], K["K_ONE"], K["K_INT1"]
    p += [
        k(OP_IAND, _SQ, _RA, Z, kb=True),                    # the result's sign: +
        k(OP_ISHR, _SGN, _RA, K["K_W1"], kb=True),           # the OPERAND's, as 0/1
    ]
    _classify(p, K, _RA, 22, 23, 24, 25, 26)                 # nan inf zero sub snan
    p += [
        # softfloat.sqrt's order: NaN, then +-0 as itself, then any
        # other negative (-inf included) is invalid, then +inf as itself
        k(OP_IOR, _SBITS, _RA, Z, kb=True),                  # +-0 and +inf: a itself
        k(OP_IAND, _SFL, _RA, Z, kb=True),                   # no flags
        k(OP_SELECT, 27, Z, _SGN, 24, ka=True),              # negative and not zero
        k(OP_SELECT, _SBITS, K["K_QNAN"], _SBITS, 27, ka=True),
        k(OP_SELECT, _SFL, K["K_INVALID"], _SFL, 27, ka=True),
        k(OP_SELECT, _SBITS, K["K_QNAN"], _SBITS, 22, ka=True),
        k(OP_SELECT, 31, K["K_INVALID"], Z, 26, ka=True, kb=True),
        k(OP_SELECT, _SFL, 31, _SFL, 22),
        k(OP_SELECT, _SPEC, ONE, 23, 24, ka=True),           # zero | inf
        k(OP_SELECT, _SPEC, ONE, _SPEC, 27, ka=True),        # | negative
        k(OP_SELECT, _SPEC, ONE, _SPEC, 22, ka=True),        # | nan
        # a subnormal operand scaled by 2^k2 (k2 even), half of it off D
        k(OP_MUL, 19, _RA, K["K_P2K2"], kb=True),
        k(OP_SELECT, 19, 19, _RA, 25),                       # a_eff
        k(OP_SELECT, _D, K["K_NEGK2H"], Z, 25, ka=True, kb=True),
        # E, its parity, the centred operand doubled when E is odd
        k(OP_IAND, 21, 19, K["K_EXP"], kb=True),
        k(OP_ISHR, 21, 21, K["K_MANW"], kb=True),
        k(OP_ISUB, 21, 21, K["K_BIAS"], kb=True),            # E, signed
        k(OP_IAND, 22, 21, I1, kb=True),                     # odd
        k(OP_IAND, _BC, 19, K["K_MAN"], kb=True),
        k(OP_IOR, _BC, _BC, ONE, kb=True),                   # in [1, 2)
        k(OP_MUL, 20, _BC, K["K_TWOF"], kb=True),
        k(OP_SELECT, _BC, 20, _BC, 22),                      # in [2, 4) when odd
        # D2 = (E - odd) / 2: even, signed - offset into the positive
        # range, shift, offset back
        k(OP_ISUB, 21, 21, 22),
        k(OP_IADD, 21, 21, K["K_SIGN"], kb=True),
        k(OP_ISHR, 21, 21, I1, kb=True),
        k(OP_ISUB, 21, 21, K["K_QUART"], kb=True),
        k(OP_IADD, _D, _D, 21),
        # a special lane takes the root of 1 and raises nothing
        k(OP_SELECT, _BC, ONE, _BC, _SPEC, ka=True),
    ]
    return p


def _inc(p, K, rd, guard, sticky, lsb, t1, t2, t3):
    """The increment softfloat._round_up decides, from integer 0/1
    guard, sticky and lsb registers and the bank's mode words, into
    rd; t1..t3 scratch. RTZ is the fall-through: no mode word set."""
    k = _k
    Z, I1 = K["K_ZERO"], K["K_INT1"]
    p += [
        k(OP_SELECT, t1, I1, lsb, sticky, ka=True),           # sticky | lsb
        k(OP_SELECT, t1, t1, Z, guard, kb=True),              # RNE: guard & that
        k(OP_SELECT, t2, I1, sticky, guard, ka=True),         # guard | sticky
        k(OP_SELECT, t3, t2, Z, _SGN, kb=True),               # RDN: sign & that
        k(OP_SELECT, t2, Z, t2, _SGN, ka=True),               # RUP: !sign & that
        k(OP_SELECT, rd, guard, Z, K["K_RMM"], kb=True, kc=True),
        k(OP_SELECT, rd, t2, rd, K["K_RUP"], kc=True),
        k(OP_SELECT, rd, t3, rd, K["K_RDN"], kc=True),
        k(OP_SELECT, rd, t1, rd, K["K_RNE"], kc=True),
    ]
    return p


def _guard_sticky_div(p, K):
    """seqprogs.div_finish's four cases from the residual (_T2) and the
    midpoint probe (_UP): guard -> r22, sticky -> r23, as 0/1."""
    k = _k
    Z, I1 = K["K_ZERO"], K["K_INT1"]
    p += [
        k(OP_IAND, 19, _T2, K["K_ABSM"], kb=True),
        k(OP_ICMPLT, 19, 19, I1, kb=True),                    # r2 == +-0
        k(OP_IAND, 20, _UP, K["K_ABSM"], kb=True),
        k(OP_ICMPLT, 20, 20, I1, kb=True),                    # d2 == +-0
        k(OP_ISHR, 21, _UP, K["K_W1"], kb=True),              # d2 < 0
        k(OP_SELECT, 22, Z, I1, 21, ka=True, kb=True),        # below midpoint: guard 0
        k(OP_SELECT, 22, I1, 22, 20, ka=True),                # exact tie: guard 1
        k(OP_SELECT, 22, Z, 22, 19, ka=True),                 # exact: guard 0
        k(OP_SELECT, 23, Z, I1, 20, ka=True, kb=True),        # tie: sticky 0, else 1
        k(OP_SELECT, 23, Z, 23, 19, ka=True),                 # exact: sticky 0
    ]
    return p


def _guard_sticky_sqrt(p, K):
    """seqprogs.sqrt_finish's two cases from the residual (_T2) and d2
    (_TMP): exact is (0, 0); otherwise guard is d2's sign inverted and
    sticky is 1."""
    k = _k
    Z, I1 = K["K_ZERO"], K["K_INT1"]
    p += [
        k(OP_IAND, 19, _T2, K["K_ABSM"], kb=True),
        k(OP_ICMPLT, 19, 19, I1, kb=True),                    # r == +-0
        k(OP_ISHR, 21, _TMP, K["K_W1"], kb=True),             # d2 < 0
        k(OP_SELECT, 22, Z, I1, 21, ka=True, kb=True),        # guard = !(d2 < 0)
        k(OP_SELECT, 22, Z, 22, 19, ka=True),                 # exact: guard 0
        k(OP_SELECT, 23, Z, I1, 19, ka=True, kb=True),        # exact: sticky 0, else 1
    ]
    return p


def _round_pack(p, K):
    """softfloat.round_pack on the core's result in _Q with guard r22,
    sticky r23, the true exponent in _D and the sign in _SQ/_SGN:
    bits -> r3, flags -> r8."""
    k = _k
    Z, I1 = K["K_ZERO"], K["K_INT1"]
    p += [
        # m4 = (the p-bit significand << 2) | guard << 1 | sticky
        k(OP_IAND, 24, _Q, K["K_MAN"], kb=True),
        k(OP_IOR, 24, 24, K["K_HIDDEN"], kb=True),
        k(OP_ISHL, 24, 24, K["K_TWO"], kb=True),
        k(OP_ISHL, 25, 22, I1, kb=True),
        k(OP_IOR, 24, 24, 25),
        k(OP_IOR, 24, 24, 23),
        # e = ef(q) + D - (bias + man_w + 2), signed
        k(OP_IAND, 25, _Q, K["K_EXP"], kb=True),
        k(OP_ISHR, 25, 25, K["K_MANW"], kb=True),
        k(OP_IADD, 25, 25, _D),
        k(OP_ISUB, 25, 25, K["K_EOFF"], kb=True),
        # the rounding position: shift = clamp(SUBQ - e, 2, p + 3)
        k(OP_ISUB, 26, K["K_SUBQ"], 25, ka=True),             # t
        k(OP_IXOR, 27, 26, K["K_SIGN"], kb=True),
        k(OP_ICMPLT, 28, K["K_TWO_S"], 27, ka=True),          # 2 < t, signed: subnormal
        k(OP_SELECT, 29, 26, K["K_TWO"], 28, kb=True),
        k(OP_ICMPLT, 30, K["K_P3"], 29, ka=True),
        k(OP_SELECT, 29, K["K_P3"], 29, 30, ka=True),         # shift
        # kept0, rem, half -> guard', sticky', inexact, lsb
        k(OP_ISHR, 30, 24, 29),                               # kept0
        k(OP_ISHL, 31, I1, 29, ka=True),
        k(OP_ISUB, 31, 31, I1, kb=True),                      # 2^shift - 1
        k(OP_IAND, 3, 24, 31),                                # rem
        k(OP_ISUB, 4, 29, I1, kb=True),
        k(OP_ISHL, 4, I1, 4, ka=True),                        # half
        k(OP_ICMPLT, 5, 3, 4),
        k(OP_SELECT, 5, Z, I1, 5, ka=True, kb=True),          # guard' = rem >= half
        k(OP_ISUB, 8, 4, I1, kb=True),
        k(OP_IAND, 8, 3, 8),
        k(OP_ICMPLT, 8, Z, 8, ka=True),
        k(OP_SELECT, 8, I1, Z, 8, ka=True, kb=True),          # sticky' = rem & (half-1) != 0
        k(OP_SELECT, 9, I1, 8, 5, ka=True),                   # inexact = guard' | sticky'
        k(OP_IAND, 11, 30, I1, kb=True),                      # lsb
    ]
    _inc(p, K, 20, 5, 8, 11, 12, 13, 19)                      # inc -> 20
    p += [
        k(OP_IADD, 21, 30, 20),                               # kept
        # the normal path: (e_norm + bias) << man_w, plus kept minus the
        # hidden bit - a carry-out rides into the field by itself
        k(OP_IADD, 22, 25, K["K_P1"], kb=True),               # e_norm
        k(OP_IADD, 23, 22, K["K_BIAS"], kb=True),
        k(OP_ISHL, 23, 23, K["K_MANW"], kb=True),
        k(OP_IADD, 23, 23, 21),
        k(OP_ISUB, 23, 23, K["K_HALFP"], kb=True),
        k(OP_IOR, 23, 23, _SQ),                               # bits_n
        k(OP_ICMPLT, 27, 21, K["K_TOPU"], kb=True),
        k(OP_SELECT, 27, Z, I1, 27, ka=True, kb=True),        # carry-out
        k(OP_IADD, 27, 22, 27),                               # e_res
        k(OP_IXOR, 27, 27, K["K_SIGN"], kb=True),
        k(OP_ICMPLT, 27, K["K_EMAX_S"], 27, ka=True),         # emax < e_res: overflow
        k(OP_SELECT, 29, K["K_RDN"], K["K_RUP"], _SGN, ka=True, kb=True),
        k(OP_SELECT, 29, I1, 29, K["K_RNE"], ka=True, kc=True),
        k(OP_SELECT, 29, I1, 29, K["K_RMM"], ka=True, kc=True),   # 7.4: inf or max
        k(OP_IOR, 30, _SQ, K["K_INF"], kb=True),
        k(OP_IOR, 31, _SQ, K["K_MAXN"], kb=True),
        k(OP_SELECT, 30, 30, 31, 29),
        k(OP_SELECT, 23, 30, 23, 27),                         # bits_n, overflow applied
        k(OP_SELECT, 31, K["K_INEXACT"], Z, 9, ka=True, kb=True),
        k(OP_SELECT, 31, K["K_OVFINX"], 31, 27, ka=True),     # flags_n
        # the subnormal path: kept is the fraction field (or the minimum
        # normal, whose pattern is the same); tininess after rounding
        k(OP_IOR, 3, _SQ, 21),                                # bits_s
        k(OP_ISHR, 4, 24, K["K_TWO"], kb=True),               # the unbounded rounding's kept0
        k(OP_IAND, 5, 24, I1, kb=True),                       # its sticky
        k(OP_ISHR, 8, 24, I1, kb=True),
        k(OP_IAND, 8, 8, I1, kb=True),                        # its guard
        k(OP_IAND, 11, 4, I1, kb=True),                       # its lsb
    ]
    _inc(p, K, 29, 8, 5, 11, 12, 13, 19)                      # inc_u -> 29
    p += [
        k(OP_IADD, 4, 4, 29),
        k(OP_ICMPLT, 4, 4, K["K_TOPU"], kb=True),
        k(OP_SELECT, 4, Z, I1, 4, ka=True, kb=True),          # carry_u: it reached 2^p
        k(OP_ICMPLT, 5, 26, K["K_THREE"], kb=True),
        k(OP_ICMPLT, 8, 26, K["K_FOUR"], kb=True),
        k(OP_SELECT, 5, Z, 8, 5, ka=True),                    # t == 3: e_norm is emin - 1
        k(OP_SELECT, 5, 4, Z, 5, kb=True),                    # not tiny: that, and the carry
        k(OP_SELECT, 8, K["K_INEXACT"], K["K_INXUND"], 5, ka=True, kb=True),
        k(OP_SELECT, 8, 8, Z, 9, kb=True),                    # flags_s
        # merge the two paths
        k(OP_SELECT, 3, 3, 23, 28),
        k(OP_SELECT, 8, 8, 31, 28),
    ]
    return p


def _answer(p):
    """The special lane's answer over the rounded one, then the two
    deposits: bits, flags."""
    p += [
        _k(OP_SELECT, 3, _SBITS, 3, _SPEC),
        _k(OP_SELECT, 8, _SFL, 8, _SPEC),
        seq.deposit(3),
        seq.deposit(8),
        seq.halt(),
    ]
    return p


def div_full_program(fmt: FpFormat) -> seq.Program:
    """r0 = a, r1 = b, raw. Deposits (quotient bits, flag word) a lane.
    BANK_EXT: the run supplies bank(fmt, rnd)."""
    p = _prep_div([], KD)
    _div_core(p, fmt, _AC, _BC)
    _guard_sticky_div(p, KD)
    _round_pack(p, KD)
    _answer(p)
    return seq.Program(fmt, p, consts=(), max_deposits=2,
                       flags=seq.FLAG_BANK_EXT, n_consts=N_CONSTS)


def sqrt_full_program(fmt: FpFormat) -> seq.Program:
    """r0 = a, raw. Deposits (root bits, flag word) a lane. BANK_EXT:
    the run supplies bank_sqrt(fmt, rnd)."""
    p = _prep_sqrt([], KS)
    _sqrt_core(p, fmt, _BC)
    _guard_sticky_sqrt(p, KS)
    _round_pack(p, KS)
    _answer(p)
    return seq.Program(fmt, p, consts=(), max_deposits=2,
                       flags=seq.FLAG_BANK_EXT, n_consts=N_CONSTS_SQRT)


_CACHE = {}
_CACHE_SQRT = {}


def div_full_program_for(fmt: FpFormat) -> seq.Program:
    if fmt.width not in _CACHE:
        _CACHE[fmt.width] = div_full_program(fmt)
    return _CACHE[fmt.width]


def sqrt_full_program_for(fmt: FpFormat) -> seq.Program:
    if fmt.width not in _CACHE_SQRT:
        _CACHE_SQRT[fmt.width] = sqrt_full_program(fmt)
    return _CACHE_SQRT[fmt.width]


def _collect(res, n):
    outs, flags = [], 0
    for i in range(n):
        assert res.counts[i] == 2
        outs.append(res.deposits[2 * i])
        flags |= res.deposits[2 * i + 1]
    return outs, flags


def run_div_full(fmt: FpFormat, xs_a, xs_b, rnd: int = RND_RNE):
    """One program run over every lane, specials included; the host
    copies one deposit and ORs the other. -> (list of bits, flags)."""
    res = seq.run(div_full_program_for(fmt), list(xs_a), list(xs_b),
                  bank=bank(fmt, rnd))
    return _collect(res, len(xs_a))


def run_sqrt_full(fmt: FpFormat, xs_a, rnd: int = RND_RNE):
    res = seq.run(sqrt_full_program_for(fmt), list(xs_a), [0] * len(xs_a),
                  bank=bank_sqrt(fmt, rnd))
    return _collect(res, len(xs_a))
