# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""Division and square root as SEQUENCER PROGRAMS.

sequences.div_seq / sqrt_seq state the composed route as a list of
elementwise engine passes with host bookkeeping between them - and the
library's elementwise port pays for that shape on a device: ~25-30
kernel round trips per call, each staging its operands again. This
module restates the SAME route as one on-chip program: the operands
are loaded into lane registers once, every floating-point and integer
step of the core executes from the instruction memory, and three
values per lane come back through the deposit stream. One round trip.

The partition follows from what each side owns:

  HOST, BEFORE (div_prep / sqrt_prep): operand classification -
  specials are answered from operand class, never computed, exactly as
  the sequences do - and the exact prenormalise/centre surgery, which
  is integer work on encodings the host is already holding. The host
  also derives D (the true scale) from the same fields. Nothing here
  needs device data.

  PROGRAM (div_program / sqrt_program): the entire core - seed,
  Newton, the truncating Markstein finish, the two restore passes, the
  exact residual and the midpoint probe. The restore's per-lane
  conditionals become branchless CMPLT/SELECT with IADD/ISUB ulp steps
  on the encoding, which is exactly what those opcodes exist for. The
  early break of the model's restore loop needs no bookkeeping at all:
  a lane that would have broken re-evaluates to the same decisions and
  steps zero times, so two unconditional passes are bit-identical to
  the model's loop.

  HOST, AFTER (div_finish / sqrt_finish): guard and sticky read from
  the deposited residual and midpoint probe by the same zero/sign
  tests the sequences apply, then round_pack - the contract's single
  rounding authority - at the true scale, under the caller's
  attribute. Program FLAGS are scaffolding and are discarded, exactly
  as the sequences discard per-step flags; the caller's flags come
  from operand classes and round_pack alone.

Equivalence rests on one fact checked case-by-case in review and
enforced wholesale by test_seqprogs.py: on every value the core can
reach, the program's FP comparisons decide exactly what the model's
sign-bit tests decide. The two places they could differ are -0
residuals, and the RNE exact-cancellation FMAs that produce those
residuals cannot produce -0.

Deposits, per lane, in order: div (q2, r2, d2); sqrt (s1, r, d2).
Registers: r0/r1 are the a/b input streams (centred operands); the
program touches r3..r12 and never r2, so a c stream is unused.
"""

from .formats import FpFormat
from . import softfloat as sf
from . import seq
from .softfloat import (
    RND_RNE, RND_RTZ,
    OP_RECIP_SEED, OP_RSQRT_SEED,
    OP_FMA, OP_MUL, OP_NEG, OP_SUB,
    OP_SELECT, OP_CMPLT, OP_CMPLE,
    OP_IAND, OP_ISUB, OP_IADD, OP_ISHL,
    unpack, NAN, INF, ZERO,
    zero_bits, one_bits, inf_bits, qnan_bits,
    FLAG_INVALID, FLAG_DIVZERO,
)
from .sequences import _NEWTON, _v, _pow2_bits, _centre

# ---- constant banks --------------------------------------------------
# Indexed by the K* names below; every constant is derived from the
# format's own fields, never transcribed.

K_ZERO, K_ONE, K_INT1, K_EXP, K_MW, K_MW1 = range(6)     # div bank
K_HALF, K_3H, K_SQ = 6, 7, 8                             # sqrt extends it


def _consts_div(fmt: FpFormat):
    return [
        zero_bits(fmt),                          # +0.0
        one_bits(fmt),                           # 1.0
        1,                                       # integer 1: the ulp step
        fmt.exp_mask << fmt.man_w,               # exponent-field mask
        fmt.man_w << fmt.man_w,                  # E -> E - man_w   (2^e)
        (fmt.man_w + 1) << fmt.man_w,            # E -> E - man_w - 1
    ]


def _consts_sqrt(fmt: FpFormat):
    return _consts_div(fmt) + [
        _pow2_bits(fmt, -1),                                     # 0.5
        (fmt.bias << fmt.man_w) | (1 << (fmt.man_w - 1)),        # 1.5
        (fmt.bias + 2 * fmt.man_w + 2) << fmt.man_w,             # see below
    ]
    # K_SQ turns pwm<<1 into 2^(2e-2): the encoding of 2^(2e-2) has
    # exponent field 2E - bias - 2*man_w - 2, and (pwm << 1) has 2E in
    # the field, so one ISUB of this constant finishes it. E is within
    # one of the bias here, so the field stays normal and the transient
    # top bit of the shift cannot wrap.


# ---- the programs ----------------------------------------------------
# Register map (both programs): r0=a-stream r1=b-stream r3=y r4=nbc/neg
# r5,r6=temporaries r7=result-in-progress r8=power r9=down r10=room/up
# r11=scratch r12=sp (sqrt only).

_A, _B = 0, 1
_Y, _NB, _T1, _T2, _Q, _PW, _DN, _UP, _TMP, _SP = 3, 4, 5, 6, 7, 8, 9, 10, 11, 12


def _restore_pass_div(p):
    a = seq.alu
    p += [
        a(OP_FMA, _T2, _NB, _Q, _A),                       # exact residual
        a(OP_CMPLT, _DN, _T2, K_ZERO, kb=True),            # r2 < 0 (not -0)
        a(OP_ISUB, _TMP, _Q, K_INT1, kb=True),
        a(OP_SELECT, _Q, _TMP, _Q, _DN),                   # ulp down if so
        a(OP_IAND, _PW, _Q, K_EXP, kb=True),
        a(OP_ISUB, _PW, _PW, K_MW, kb=True),               # 2^e of q2
        a(OP_FMA, _UP, _NB, _PW, _T2),                     # room = r2 - b*ulp
        a(OP_CMPLT, _UP, K_ZERO, _UP, ka=True),            # room > 0
        a(OP_SUB, _TMP, K_ONE, 0, _DN, ka=True),           # 1 - down
        a(OP_MUL, _UP, _UP, _TMP),                         # up & !down
        a(OP_IADD, _TMP, _Q, K_INT1, kb=True),
        a(OP_SELECT, _Q, _TMP, _Q, _UP),                   # ulp up if so
    ]
    return p


def div_program(fmt: FpFormat) -> seq.Program:
    """The div core as a program: r0 = centred dividend, r1 = centred
    divisor, both in [1, 2). Deposits q2, r2, d2."""
    a = seq.alu
    N = _NEWTON[fmt.man_w + 1]
    p = [
        a(OP_RECIP_SEED, _Y, _B),
        a(OP_NEG, _NB, _B),
    ]
    for _ in range(N):                                     # y -> 1/bc
        p += [
            a(OP_FMA, _T1, _NB, _Y, K_ONE, kc=True),       # e = 1 - b*y
            a(OP_FMA, _Y, _Y, _T1, _Y),                    # y += y*e
        ]
    p += [
        a(OP_MUL, _T1, _A, _Y),                            # q02
        a(OP_FMA, _T2, _NB, _T1, _A),                      # r0, exact
        a(OP_FMA, _Q, _T2, _Y, _T1),                       # q1, RNE tighten
        a(OP_FMA, _T2, _NB, _Q, _A),                       # r1, exact
        a(OP_FMA, _Q, _T2, _Y, _Q, rnd=RND_RTZ),           # q2: no ties
    ]
    _restore_pass_div(p)
    _restore_pass_div(p)
    p += [
        a(OP_FMA, _T2, _NB, _Q, _A),                       # exact remainder
        a(OP_IAND, _PW, _Q, K_EXP, kb=True),
        a(OP_ISUB, _PW, _PW, K_MW1, kb=True),              # 2^(e-1)
        a(OP_FMA, _UP, _NB, _PW, _T2),                     # d: midpoint probe
        seq.deposit(_Q),
        seq.deposit(_T2),
        seq.deposit(_UP),
        seq.halt(),
    ]
    return seq.Program(fmt, p, consts=_consts_div(fmt), max_deposits=3)


def _restore_pass_sqrt(p):
    a = seq.alu
    p += [
        a(OP_NEG, _NB, _Q),
        a(OP_FMA, _T2, _NB, _Q, _A),                       # exact residual
        a(OP_CMPLT, _DN, _T2, K_ZERO, kb=True),            # r < 0 (not -0)
        a(OP_ISUB, _TMP, _Q, K_INT1, kb=True),
        a(OP_SELECT, _Q, _TMP, _Q, _DN),                   # ulp down if so
        a(OP_IADD, _SP, _Q, K_INT1, kb=True),              # candidate s+1
        a(OP_NEG, _NB, _SP),
        a(OP_FMA, _UP, _NB, _SP, _A),                      # rp = a - sp^2
        a(OP_CMPLE, _UP, K_ZERO, _UP, ka=True),            # rp >= 0
        a(OP_SUB, _TMP, K_ONE, 0, _DN, ka=True),           # 1 - down
        a(OP_MUL, _UP, _UP, _TMP),                         # up & !down
        a(OP_SELECT, _Q, _SP, _Q, _UP),                    # take sp if so
    ]
    return p


def sqrt_program(fmt: FpFormat) -> seq.Program:
    """The sqrt core as a program: r0 = centred operand in [1, 4).
    Deposits s1, r, d2."""
    a = seq.alu
    N = _NEWTON[fmt.man_w + 1]
    p = [
        a(OP_RSQRT_SEED, _Y, _A),
        a(OP_NEG, _NB, _A),
        a(OP_MUL, _NB, _NB, K_HALF, kb=True),              # -(a/2), exact
    ]
    for _ in range(N):                                     # y -> 1/sqrt(a)
        p += [
            a(OP_MUL, _T1, _Y, _Y),
            a(OP_FMA, _T1, _NB, _T1, K_3H, kc=True),
            a(OP_MUL, _Y, _Y, _T1),
        ]
    p += [
        a(OP_MUL, _T1, _A, _Y),                            # s0
        a(OP_MUL, _UP, _Y, K_HALF, kb=True),               # h0
        a(OP_NEG, _NB, _T1),
        a(OP_FMA, _T2, _NB, _T1, _A),                      # r0, exact
        a(OP_FMA, _Q, _T2, _UP, _T1),                      # s1: within 1/2 ulp
    ]
    _restore_pass_sqrt(p)
    _restore_pass_sqrt(p)
    p += [
        a(OP_NEG, _NB, _Q),
        a(OP_FMA, _T2, _NB, _Q, _A),                       # exact, >= 0
        a(OP_IAND, _PW, _Q, K_EXP, kb=True),               # pwm
        a(OP_ISUB, _UP, _PW, K_MW, kb=True),               # 2^e
        a(OP_MUL, _UP, _Q, _UP),                           # s*u, exact
        a(OP_SUB, _TMP, _T2, 0, _UP),                      # r - s*u, exact
        a(OP_ISHL, _PW, _PW, K_INT1, kb=True),             # field 2E
        a(OP_ISUB, _PW, _PW, K_SQ, kb=True),               # 2^(2e-2)
        a(OP_SUB, _TMP, _TMP, 0, _PW),                     # d2, exact
        seq.deposit(_Q),
        seq.deposit(_T2),
        seq.deposit(_TMP),
        seq.halt(),
    ]
    return seq.Program(fmt, p, consts=_consts_sqrt(fmt), max_deposits=3)


_DIV_CACHE = {}
_SQRT_CACHE = {}


def div_program_for(fmt: FpFormat) -> seq.Program:
    if fmt.width not in _DIV_CACHE:
        _DIV_CACHE[fmt.width] = div_program(fmt)
    return _DIV_CACHE[fmt.width]


def sqrt_program_for(fmt: FpFormat) -> seq.Program:
    if fmt.width not in _SQRT_CACHE:
        _SQRT_CACHE[fmt.width] = sqrt_program(fmt)
    return _SQRT_CACHE[fmt.width]


# ---- host halves -----------------------------------------------------

def div_prep(fmt: FpFormat, xa: int, xb: int):
    """-> (bits, flags) for a special lane, or None plus the core lane
    state (ac, bc, D, sq) - exactly sequences.div_seq's head."""
    ua, ub = unpack(fmt, xa), unpack(fmt, xb)
    if NAN in (ua.kind, ub.kind):
        return sf.div(fmt, xa, xb, RND_RNE), None
    sq = ua.sign ^ ub.sign
    if ua.kind == INF:
        if ub.kind == INF:
            return (qnan_bits(fmt), FLAG_INVALID), None
        return (inf_bits(fmt, sq), 0), None
    if ub.kind == INF:
        return (zero_bits(fmt, sq), 0), None
    if ub.kind == ZERO:
        if ua.kind == ZERO:
            return (qnan_bits(fmt), FLAG_INVALID), None
        return (inf_bits(fmt, sq), FLAG_DIVZERO), None
    if ua.kind == ZERO:
        return (zero_bits(fmt, sq), 0), None

    p = fmt.prec
    d_adj = 0
    a_eff, b_eff = xa, xb
    if ((xa >> fmt.man_w) & fmt.exp_mask) == 0:
        a_eff = _v(fmt, OP_MUL, xa, _pow2_bits(fmt, p))
        d_adj -= p
    if ((xb >> fmt.man_w) & fmt.exp_mask) == 0:
        b_eff = _v(fmt, OP_MUL, xb, _pow2_bits(fmt, p))
        d_adj += p
    ac, ea = _centre(fmt, a_eff)
    bc, eb = _centre(fmt, b_eff)
    return None, (ac, bc, ea - eb + d_adj, sq)


def div_finish(fmt: FpFormat, q2: int, r2: int, d2: int, D: int, sq: int,
               rnd: int):
    """Guard, sticky and the one rounding - sequences.div_seq's tail,
    fed from the deposits."""
    u2 = unpack(fmt, q2)
    if r2 in (zero_bits(fmt, 0), zero_bits(fmt, 1)):
        guard, sticky = 0, 0
    elif d2 in (zero_bits(fmt, 0), zero_bits(fmt, 1)):
        guard, sticky = 1, 0                     # exact tie
    elif (d2 >> (fmt.width - 1)) & 1:
        guard, sticky = 0, 1                     # below the midpoint
    else:
        guard, sticky = 1, 1                     # above the midpoint
    m = (u2.m << 2) | (guard << 1) | sticky
    return sf.round_pack(fmt, sq, m, u2.e + D - 2, rnd)


def sqrt_prep(fmt: FpFormat, xa: int):
    """-> (bits, flags) for a special lane, or None plus (acen, D2)."""
    ua = unpack(fmt, xa)
    if ua.kind == NAN:
        return sf.sqrt(fmt, xa, RND_RNE), None
    if ua.kind == ZERO:
        return (xa, 0), None
    if ua.sign:
        return (qnan_bits(fmt), FLAG_INVALID), None
    if ua.kind == INF:
        return (xa, 0), None

    p = fmt.prec
    k2 = p + (p & 1)
    adj = 0
    a_eff = xa
    if ((xa >> fmt.man_w) & fmt.exp_mask) == 0:
        a_eff = _v(fmt, OP_MUL, xa, _pow2_bits(fmt, k2))
        adj = -(k2 // 2)
    biased = (a_eff >> fmt.man_w) & fmt.exp_mask
    E = biased - fmt.bias
    odd = E & 1
    acen = (a_eff & fmt.man_mask) | (fmt.bias << fmt.man_w)
    if odd:
        acen = _v(fmt, OP_MUL, acen, _pow2_bits(fmt, 1))
    return None, (acen, (E - odd) // 2 + adj)


def sqrt_finish(fmt: FpFormat, s1: int, r: int, d2: int, D2: int, rnd: int):
    us = unpack(fmt, s1)
    if r in (zero_bits(fmt, 0), zero_bits(fmt, 1)):
        guard, sticky = 0, 0
    else:
        guard = 0 if ((d2 >> (fmt.width - 1)) & 1) else 1
        sticky = 1
    m = (us.m << 2) | (guard << 1) | sticky
    return sf.round_pack(fmt, 0, m, us.e - 2 + D2, rnd)


# ---- batch runners (the shape the library reproduces in C) -----------

def run_div(fmt: FpFormat, xs_a, xs_b, rnd: int = RND_RNE):
    """One program run over every core lane; specials answered by
    class. -> (list of bits, accumulated flags)."""
    n = len(xs_a)
    outs = [None] * n
    flags = 0
    idx, ac_l, bc_l, D_l, sq_l = [], [], [], [], []
    for i in range(n):
        special, core = div_prep(fmt, xs_a[i], xs_b[i])
        if special is not None:
            outs[i], fl = special
            flags |= fl
        else:
            ac, bc, D, sq = core
            idx.append(i)
            ac_l.append(ac)
            bc_l.append(bc)
            D_l.append(D)
            sq_l.append(sq)
    if idx:
        res = seq.run(div_program_for(fmt), ac_l, bc_l)
        for j, i in enumerate(idx):
            q2, r2, d2 = res.deposits[j * 3: j * 3 + 3]
            assert res.counts[j] == 3
            outs[i], fl = div_finish(fmt, q2, r2, d2, D_l[j], sq_l[j], rnd)
            flags |= fl
    return outs, flags


def run_sqrt(fmt: FpFormat, xs_a, rnd: int = RND_RNE):
    n = len(xs_a)
    outs = [None] * n
    flags = 0
    idx, a_l, D_l = [], [], []
    for i in range(n):
        special, core = sqrt_prep(fmt, xs_a[i])
        if special is not None:
            outs[i], fl = special
            flags |= fl
        else:
            acen, D2 = core
            idx.append(i)
            a_l.append(acen)
            D_l.append(D2)
    if idx:
        res = seq.run(sqrt_program_for(fmt), a_l, [0] * len(a_l))
        for j, i in enumerate(idx):
            s1, r, d2 = res.deposits[j * 3: j * 3 + 3]
            assert res.counts[j] == 3
            outs[i], fl = sqrt_finish(fmt, s1, r, d2, D_l[j], rnd)
            flags |= fl
    return outs, flags
