/* Copyright 2026 Logan W.
 * SPDX-License-Identifier: Apache-2.0
 *
 * Parity with GNU MPFR: the third oracle, and the first independent
 * one that reaches every rung.
 *
 * The golden model is the definition of correct, and the CPU soak
 * checks fp32/fp64 against silicon nobody here designed - but silicon
 * stops at binary64. MPFR is the arbitrary-precision library the rest
 * of the world already treats as the reference for correctly-rounded
 * arithmetic, it computes at ANY precision, and it was written by
 * people who have never seen this project. Agreement at fp128 and
 * fp256 is therefore the strongest external evidence available this
 * side of silicon - and disagreement at fp32/fp64, where the CPU
 * campaign has already proven 23.9 billion cases, would indict this
 * HARNESS rather than the library, which is exactly the
 * self-calibration a new oracle needs.
 *
 * IEEE emulation follows the MPFR manual's own recipe: precision p,
 * mpfr_set_emin(emin - p + 2), mpfr_set_emax(emax + 1), compute, then
 * mpfr_check_range + mpfr_subnormalize with the ternary. Results are
 * compared in the MPFR domain (both sides converted exactly), NaN as
 * a CLASS (MPFR keeps no payloads; the model's canonicalisation is
 * pinned by its own tests), zeros by sign.
 *
 * Flags are NOT taken from MPFR's sticky flags, deliberately. The
 * contract defines underflow as tininess AFTER rounding AND inexact
 * (round_pack's q_unb test); MPFR's underflow flag has its own
 * definition, and reconciling definitions is how subtle disagreements
 * get explained away instead of found. Instead every case is computed
 * twice - once with the format's exponent range, once unbounded at
 * the same precision - and overflow/underflow fall out of comparing
 * the unbounded result against the format's thresholds: the same
 * derivation round_pack uses, computed by the oracle's arithmetic.
 * Inexact is the final ternary; invalid and divideByZero come from
 * operand classes (sNaN inputs classified from the bits, since MPFR
 * has no signaling NaNs - documented one-sided help to the oracle).
 *
 * Rounding modes: RNE/RTZ/RDN/RUP map directly onto MPFR. RMM
 * (ties-to-away) has NO MPFR equivalent - MPFR_RNDA rounds every
 * inexact value away, not just ties - so RMM is built from pure-MPFR
 * intermediates by the standard construction: truncate to p+1 bits
 * (RNDZ, ternary kept), where the extra bit is the guard and the
 * ternary is the sticky; a tie is exactly "ternary zero and guard
 * set", which rounds away, and everything else follows the RNE
 * decision. Subnormal landings redo the decision on the format's
 * fixed subnormal grid. The construction is a dozen lines and each
 * intermediate is MPFR's own arithmetic; it is labelled where it
 * runs, because an oracle with a footnote should say so.
 *
 * The phase-1 transcendentals (ABI 0.3) are checked here too, and for
 * them this is not the third oracle but the ONLY one: libm is neither
 * correctly rounded nor reproducible, so unlike div and sqrt there is
 * no CPU campaign at fp32/fp64 to calibrate against. See the banner
 * above check_transcend for how MPFR's own exponent range is handled
 * (exp of the largest fp256 overflows MPFR too) and which expectations
 * are the contract's rather than MPFR's.
 *
 * The clause-5 completion set (ABI 0.2) is checked here too - rint,
 * scaleB, convertFormat, the eight integer conversions, logB,
 * nextUp/nextDown and remainder - by the same machinery: see the
 * banner comment above c5_round_into() for what maps onto what, which
 * expectations are MPFR-derived and which are the contract's own
 * (cvt_to's invalid-case delivery table), and why class, totalOrder
 * and the signaling comparisons are left to the other oracles.
 *
 * The augmented arithmetic operations of clause 9.5 are checked here
 * with one difference worth stating up front: MPFR has no
 * roundTiesTowardZero, so this harness cannot ask it for the answer.
 * It asks MPFR for the EXACT value at a precision that provably holds
 * it - and proves it by requiring a zero ternary - then applies 9.5's
 * tie rule itself and derives the error term by exact subtraction. See
 * the banner above check_augmented for why that is still an oracle and
 * exactly which part of it is not.
 *
 * The seven REDUCTIONS of clause 9.4 are checked here too, and what
 * this oracle can and cannot say about them is worth stating exactly,
 * because the honest answer is "half of it".
 *
 * MPFR CAN ARBITRATE EVERY NODE. Each node of a reduction is one add
 * or one multiply of two format values, correctly rounded in the
 * caller's attribute, and that is precisely what oracle() above
 * already decides - so the campaign REPLAYS the tree here with MPFR
 * doing every node's arithmetic and compares the root against the
 * library's, bits and flags. A node that rounded the wrong way, or
 * raised the wrong flag, or lost a subnormal, fails here.
 *
 * MPFR CANNOT ARBITRATE THE TREE. Which values are paired, and at
 * which level, is this CONTRACT's choice - 754-2019 9.4 explicitly
 * allows an implementation to "associate in any order or evaluate in
 * any wider format", so there is no external authority to appeal to
 * and MPFR has no opinion. The harness therefore reproduces the split
 * rather than judging it, and a reduction whose shape was wrong in
 * BOTH the library and this file would pass. What guards the shape is
 * a different thing entirely: two independent implementations of it
 * (python/cft_golden/reduce.py and libcft) compared against each other
 * by host/tests/reduce_check.py, the streaming accumulator's agreement
 * with the recursive definition, and the published vector sets.
 *
 * The same division applies to the three scaled products: MPFR decides
 * every node's multiply, and the binade extraction that follows it is
 * exact bit surgery on the encoding, with nothing to round and so
 * nothing to arbitrate. 9.4's special-value precedence is likewise the
 * contract's table, replayed rather than judged.
 *
 * Usage:  mpfr-check [randoms-per-format] [seed]
 *         (directed specials always run; randoms are exponent-banded)
 *         CFT_MPFR_PHASES and CFT_MPFR_FORMATS (environment, comma
 *         lists) run a subset; CFT_MPFR_DUMP_CASES prints the
 *         transcendental cases instead of checking them. Unset (or
 *         empty), the run is the whole of it. See the block above
 *         build_tpool. `mpfr-check 24 7` also compares the cases the
 *         extras ask with the pinned counts and exits 1 on a
 *         difference: see the block above main.
 */

#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include <gmp.h>
#include <mpfr.h>

/* The Pi-variants - sinpi, cospi, tanpi, asinpi, acospi, atanpi and
 * atan2pi - arrived in MPFR 4.2.0. Composing them out of sin(pi*x)
 * would compare against a ROUNDED product and would decide nothing
 * about the last bit, so an older MPFR must fail HERE rather than
 * quietly check something weaker. */
#if MPFR_VERSION < MPFR_VERSION_NUM(4, 2, 0)
#  error "mpfr-check needs MPFR 4.2.0 or newer for sinpi/cospi/tanpi \
and the Pi-variants of the inverse trigonometrics (ABI 0.4), and for \
exp2m1/exp10m1/log2p1/log10p1/powr/compound_si/rootn_si (table 9.1's \
remainder). Every one of those is called DIRECTLY."
#endif

#include "../include/cft.h"
/* Not API: the transcendental instrumentation, which this tool
 * links statically and which is where docs/TRANSCENDENTALS.md's
 * escalation numbers are measured rather than asserted. */
#include "../src/transcend.h"

/* The IEEE emulation itself - fdesc, mop, classify, enc_to_mpfr, raw_op,
 * rmm_round, the oracle, agree, hexdump and the rounding of an exact
 * value - lives in mpfr_ieee.h since parcel HXa (2026-10-26), so that
 * divsqrt-soak's fp128 and fp256 modes take the same emulation rather
 * than a second one. oracle() and c5_round_into() below are its two
 * entry points with the attribute read from MODES, as before. */
#include "mpfr_ieee.h"
/* The clause-5 rules - what each of rint, scaleB, convert, cvt_from and
 * cvt_to expects of one case - live in mpfr_c5.h since parcel HXb
 * (2026-10-27), so that clause5-soak's fp128 and fp256 class modes take
 * these rules rather than a second set. The check_* functions below call
 * them where their bodies stood, with the attribute MODES[mi].cr. */
#include "mpfr_c5.h"
/* The transcendental oracle - tfn, raw_tfn, tfn_class_flags and the case
 * itself - and get_field live in mpfr_tfn.h since parcel M4X (2026-11-09), so
 * that routine-sweep takes this oracle rather than a second one. t_oracle()
 * below is its entry point with the attribute read from MODES, as before. */
#include "mpfr_tfn.h"

static const fdesc FMTS[4] = {
    { "fp32",  CFT_FP32,   8,  23,  24,    127,    -126,  4 },
    { "fp64",  CFT_FP64,  11,  52,  53,   1023,   -1022,  8 },
    { "fp128", CFT_FP128, 15, 112, 113,  16383,  -16382, 16 },
    { "fp256", CFT_FP256, 19, 236, 237, 262143, -262142, 32 },
};

static const struct { const char *name; cft_round cr; mpfr_rnd_t mr; }
MODES[5] = {
    { "rne", CFT_RNE, MPFR_RNDN },
    { "rtz", CFT_RTZ, MPFR_RNDZ },
    { "rdn", CFT_RDN, MPFR_RNDD },
    { "rup", CFT_RUP, MPFR_RNDU },
    { "rmm", CFT_RMM, MPFR_RNDN },   /* via the p+1 construction */
};

static const char *const OPN[NOPS] =
    { "add", "sub", "mul", "fma", "div", "sqrt" };
static const int OP_NARGS[NOPS] = { 2, 2, 2, 3, 2, 1 };

static uint64_t mismatches, flag_mismatches, cases;
static int shown;
static cft_device *dev;

/* Per-op, per-format case ledger, printed at the end - the campaign's
 * receipt. The first six rows are the arithmetic this file always
 * checked; the rest are the clause-5 completion set. convert is
 * tallied by SOURCE format; rint and rint_x are the named attributes
 * and the Exact variant respectively. */
enum {
    T_ADD, T_SUB, T_MUL, T_FMA, T_DIV, T_SQRT,
    T_RINT, T_RINTX, T_SCALEB, T_CONVERT,
    T_FROM_I32, T_FROM_U32, T_FROM_I64, T_FROM_U64,
    T_TO_I32, T_TO_U32, T_TO_I64, T_TO_U64,
    T_LOGB, T_NEXTUP, T_NEXTDOWN, T_REM,
    /* the transcendentals, in the ABI's order - check_transcend
     * indexes this block as T_EXP + fn, so the two orders are one */
    T_EXP, T_EXPM1, T_EXP2, T_LOG, T_LOG1P, T_LOG2, T_LOG10, T_POW,
    T_HYPOT,
    T_SINPI, T_COSPI, T_TANPI, T_ASIN, T_ACOS, T_ATAN, T_ATAN2,
    T_ASINPI, T_ACOSPI, T_ATANPI, T_ATAN2PI,
    T_SIN, T_COS, T_TAN, T_SINH, T_COSH, T_TANH, T_ASINH, T_ACOSH,
    T_ATANH,
    T_EXP2M1, T_EXP10, T_EXP10M1, T_LOG2P1, T_LOG10P1, T_RSQRT,
    T_POWN, T_POWR, T_COMPOUND, T_ROOTN,
    /* clause 5.12, appended AFTER the transcendental block so
     * check_transcend's T_EXP + fn indexing is untouched */
    T_FROM_DEC, T_TO_DEC, T_FROM_HEX, T_TO_HEX,
    /* the augmented arithmetic operations of 754-2019 9.5 */
    T_AUG_ADD, T_AUG_SUB, T_AUG_MUL,
    /* the seven reductions of clause 9.4. A "case" here is a whole
     * VECTOR, not an element - the element count is reported
     * separately, because 400 cases over 20-element vectors is 8,000
     * arbitrated nodes and reporting only the smaller number would
     * undersell the campaign while reporting only the larger would
     * oversell its independence. */
    T_RSUM, T_RDOT, T_RSUMSQ, T_RSUMABS,
    T_SPROD, T_SPROD_SUM, T_SPROD_DIFF,
    /* 754-2019 9.6's four magnitude forms (ABI 0.7) */
    T_MINMAG, T_MINNUM_MAG, T_MAXMAG, T_MAXNUM_MAG,
    /* the formatOf arithmetic of 5.4.1, tallied by SOURCE format like
     * convert - the destination is named in the run's per-pair line */
    T_FO_ADD, T_FO_SUB, T_FO_MUL, T_FO_DIV, T_FO_SQRT, T_FO_FMA,
    NTALLY
};
static const char *const TALLY_NAME[NTALLY] = {
    "add", "sub", "mul", "fma", "div", "sqrt",
    "rint", "rint_x", "scaleb", "convert",
    "from_i32", "from_u32", "from_i64", "from_u64",
    "to_i32", "to_u32", "to_i64", "to_u64",
    "logb", "next_up", "next_down", "rem",
    "exp", "expm1", "exp2", "log", "log1p", "log2", "log10", "pow",
    "hypot",
    "sinpi", "cospi", "tanpi", "asin", "acos", "atan", "atan2",
    "asinpi", "acospi", "atanpi", "atan2pi",
    "sin", "cos", "tan", "sinh", "cosh", "tanh", "asinh", "acosh",
    "atanh",
    "exp2m1", "exp10", "exp10m1", "log2p1", "log10p1", "rsqrt",
    "pown", "powr", "compound", "rootn",
    "from_dec", "to_dec", "from_hex", "to_hex",
    "aug_add", "aug_sub", "aug_mul",
    "sum", "dot", "sumsq", "sumabs",
    "sprod", "sprod_sum", "sprod_diff",
    "min_mag", "minnum_mag", "max_mag", "maxnum_mag",
    "fo_add", "fo_sub", "fo_mul", "fo_div", "fo_sqrt", "fo_fma"
};
static uint64_t tally[NTALLY][4];

/* Arbitrated NODES, separately from the vector count above. */
static uint64_t reduce_nodes;

/* ---- the oracle ---------------------------------------------------- */

/* One case through MPFR (mpfr_ieee.h's ieee_oracle), under MODES[mi]. */
static void oracle(const fdesc *f, mop op, int mi,
                   const uint8_t *ba, const uint8_t *bb, const uint8_t *bc,
                   mpfr_t out, uint32_t *flags)
{
    ieee_oracle(f, op, MODES[mi].mr, MODES[mi].cr == CFT_RMM,
                ba, bb, bc, out, flags);
}

/* ---- the library side --------------------------------------------- */

static uint32_t lib_flags(const fdesc *f, mop op, cft_round rnd,
                          const uint8_t *a, const uint8_t *b,
                          const uint8_t *c, uint8_t *d)
{
    uint32_t fl = 0;
    switch (op) {
    case OP_ADD: cft_run(dev, CFT_ADD, f->fmt, rnd, a, NULL, c, d, 1,
                         &fl, NULL); break;
    case OP_SUB: cft_run(dev, CFT_SUB, f->fmt, rnd, a, NULL, c, d, 1,
                         &fl, NULL); break;
    case OP_MUL: cft_run(dev, CFT_MUL, f->fmt, rnd, a, b, NULL, d, 1,
                         &fl, NULL); break;
    case OP_FMA: cft_run(dev, CFT_FMA, f->fmt, rnd, a, b, c, d, 1,
                         &fl, NULL); break;
    case OP_DIV: cft_div(dev, f->fmt, rnd, a, b, d, 1, &fl, NULL); break;
    default:     cft_sqrt(dev, f->fmt, rnd, a, d, 1, &fl, NULL); break;
    }
    return fl;
}

/* ---- comparison: agree() and hexdump() are mpfr_ieee.h's ----------- */

/* ---- operand pools ------------------------------------------------- */

static uint64_t rs;
static uint64_t rng(void)
{
    uint64_t x = rs;
    x ^= x << 13; x ^= x >> 7; x ^= x << 17;
    return rs = x;
}

static void set_field(uint8_t *b, int lo, int n, uint64_t v)
{
    int i;
    for (i = 0; i < n; i++) {
        int bit = lo + i;
        if ((v >> i) & 1) b[bit >> 3] |= (uint8_t)(1u << (bit & 7));
        else              b[bit >> 3] &= (uint8_t)~(1u << (bit & 7));
    }
}

static void rand_enc(const fdesc *f, uint8_t *b)
{
    size_t i;
    for (i = 0; i < f->esz; i++)
        b[i] = (uint8_t)rng();
    if ((rng() & 3) == 0) {
        /* band the exponent toward the edges, as the CPU soak does */
        unsigned long span = (2ul << (f->exp_w - 1)) - 1;
        unsigned long base[7] = {0, 1, 2, span / 2, span - 3, span - 2,
                                 span - 1};
        /* Two statements, so the two draws come in one order on every
         * compiler (C leaves the order of a sum's operands open): the
         * band first, as every gcc build measured on 2026-10-20 did. */
        unsigned long e = base[rng() % 7];
        e += (unsigned long)(rng() % 3);
        if (e > span) e = span;
        set_field(b, f->man_w, f->exp_w, e);
    }
}

#define MAXPOOL 64

static int build_pool(const fdesc *f, uint8_t pool[][32], int randoms)
{
    int n = 0, w = 1 + f->exp_w + f->man_w;
    memset(pool, 0, sizeof(uint8_t) * MAXPOOL * 32);

    /* +0 */                                                     n++;
    /* -0 */  set_field(pool[n], w - 1, 1, 1);                   n++;
    /* +inf */ set_field(pool[n], f->man_w, f->exp_w, ~0ul);     n++;
    /* -inf */ set_field(pool[n], f->man_w, f->exp_w, ~0ul);
               set_field(pool[n], w - 1, 1, 1);                  n++;
    /* qNaN */ set_field(pool[n], f->man_w, f->exp_w, ~0ul);
               set_field(pool[n], f->man_w - 1, 1, 1);           n++;
    /* sNaN */ set_field(pool[n], f->man_w, f->exp_w, ~0ul);
               set_field(pool[n], 0, 1, 1);                      n++;
    /* min sub */ set_field(pool[n], 0, 1, 1);                   n++;
    /* max sub */ set_field(pool[n], 0, 1, 0);
               { int i; for (i = 0; i < f->man_w; i++)
                     set_field(pool[n], i, 1, 1); }              n++;
    /* min normal */ set_field(pool[n], f->man_w, f->exp_w, 1);  n++;
    /* max normal */ set_field(pool[n], f->man_w, f->exp_w,
                               (1ul << f->exp_w) - 2);
               { int i; for (i = 0; i < f->man_w; i++)
                     set_field(pool[n], i, 1, 1); }              n++;
    /* 1.0 */  set_field(pool[n], f->man_w, f->exp_w,
                         (unsigned long)f->emax);                n++;
    /* 1.0 - ulp (largest < 1) */
               set_field(pool[n], f->man_w, f->exp_w,
                         (unsigned long)f->emax - 1);
               { int i; for (i = 0; i < f->man_w; i++)
                     set_field(pool[n], i, 1, 1); }              n++;
    /* 1.0 + ulp */
               set_field(pool[n], f->man_w, f->exp_w,
                         (unsigned long)f->emax);
               set_field(pool[n], 0, 1, 1);                      n++;
    /* 2.0 */  set_field(pool[n], f->man_w, f->exp_w,
                         (unsigned long)f->emax + 1);            n++;
    /* 3.0 */  set_field(pool[n], f->man_w, f->exp_w,
                         (unsigned long)f->emax + 1);
               set_field(pool[n], f->man_w - 1, 1, 1);           n++;
    /* 0.5 */  set_field(pool[n], f->man_w, f->exp_w,
                         (unsigned long)f->emax - 1);            n++;
    /* -1.0 */ set_field(pool[n], f->man_w, f->exp_w,
                         (unsigned long)f->emax);
               set_field(pool[n], w - 1, 1, 1);                  n++;
    /* -3.0 */ set_field(pool[n], f->man_w, f->exp_w,
                         (unsigned long)f->emax + 1);
               set_field(pool[n], f->man_w - 1, 1, 1);
               set_field(pool[n], w - 1, 1, 1);                  n++;

    while (n < MAXPOOL && randoms-- > 0)
        rand_enc(f, pool[n++]);
    return n;
}

/* =================================================================
 * The clause-5 completion set (ABI 0.2), against the same oracle.
 *
 * Everything below reuses the machinery above rather than restating
 * it: enc_to_mpfr for exact operands, agree() for the verdict, and
 * c5_round_into() - the one new piece - which is oracle()'s delivery
 * logic (unbounded p-bit rounding as the over/underflow authority,
 * tininess after rounding by construction, fixed-grid subnormal
 * landings, the p+1 RMM build) applied to a value that is already
 * EXACT in an mpfr variable. That is the shape of every rounding
 * clause-5 operation: convert, scaleB and the integer conversions
 * are each ONE rounding of an exactly-representable value, which is
 * why they share a router where add/mul/div needed a recompute.
 *
 * What maps onto what:
 *   rint      mpfr_rint under RNDN (ties-to-even) / trunc / floor /
 *             ceil / round (ties-to-away). The named variants signal
 *             nothing but sNaN invalid; the Exact variant adds
 *             inexact iff the value moved; a zero result's sign is
 *             the operand's - pinned by the contract and derived
 *             here rather than trusted to MPFR's rint family.
 *   scaleb    mpfr_mul_2si in unbounded range (exact), then
 *             c5_round_into. n is clamped in the ORACLE only, at
 *             +-(4*emax + 2p + 64): past that, every nonzero finite
 *             operand overflows (resp. lands below half a subnormal
 *             grid step) whatever its exponent, so delivery and
 *             flags are constant in n - the library is called with
 *             the raw n, INT64_MIN/MAX included.
 *   convert   c5_round_into at the destination grid; NaN as class.
 *   cvt_from  the integer exactly via mpz, then c5_round_into.
 *   cvt_to    mpfr_rint at p+2 bits (always exact: the integer part
 *             of a p-bit value carries at most p+1 bits), the range
 *             test in mpz. The DELIVERED value of the invalid cases
 *             is the contract's own RISC-V FCVT table - cft.h
 *             documents the choice, 754 leaves it open - so those
 *             expectations are hardcoded from the doc, not derived
 *             from MPFR. Invalid pre-empts inexact, and only the
 *             Exact variants report inexact at all.
 *   logb      mpfr_get_exp minus one (MPFR holds the mantissa in
 *             [1/2,1), IEEE's logB in [1,2)); value-based, so a
 *             subnormal reports its true exponent; delivery is
 *             asserted exact since |logB| <= emax + man_w fits every
 *             format's significand with room to spare.
 *   next_up   mpfr_nextabove at p bits in UNBOUNDED range, then
 *             c5_round_into toward +inf. On the format's grid the
 *             step is at most one p-bit ulp, so the directed
 *             re-round lands exactly one grid position up - and the
 *             standard's edges fall out instead of being restated:
 *             nextabove(-min_sub) is a sub-grid negative that RUP
 *             delivers as -0, nextabove(max_normal) trips the
 *             overflow branch whose RUP delivery is +inf, and
 *             nextabove(-inf) is a huge negative whose RUP overflow
 *             delivery is -max_normal. Quantisation flags are
 *             discarded - the contract signal is sNaN invalid and
 *             nothing else, asserted separately. next_down is the
 *             mirror through nextbelow/RDN.
 *   rem       mpfr_remainder, exact by the standard theorem (a
 *             nonzero ternary is surfaced as a mismatch, never
 *             absorbed). MPFR documents a zero result's sign as x's,
 *             which is also the contract's rule; the sign is still
 *             forced from the operand here so the expectation is the
 *             contract's own. The flag comparison doubles as the
 *             exactness assertion: the expected mask never contains
 *             inexact/overflow/underflow, so the library raising any
 *             of them fails the case.
 *
 * cft_class and cft_total_order* are not checked here: MPFR has no
 * independent notion of either (an oracle would just restate the
 * encoding walk), and cmp_sig's value is the quiet predicate the
 * golden model already pins while its flag rule is one classify()
 * away from the harness testing itself. next_up/next_down DID make
 * the cut because the construction above is honest MPFR arithmetic
 * end to end.
 * ================================================================= */


/* +-1 on the little-endian encoding: one grid step on a finite
 * magnitude, which is how the directed generators reach "the
 * neighbour of" a boundary value without restating nextUp. */
static void enc_step(const fdesc *f, uint8_t *b, int up)
{
    size_t i;
    for (i = 0; i < f->esz; i++) {
        if (up) { if (++b[i] != 0) break; }
        else    { if (b[i]-- != 0) break; }
    }
}

static void enc_neg(const fdesc *f, uint8_t *b)
{
    int w = 1 + f->exp_w + f->man_w;
    b[(w - 1) >> 3] ^= (uint8_t)(1u << ((w - 1) & 7));
}

/* Encode (-1)^sign * m * 2^e2 exactly, if the format can. Returns 1
 * and fills b on success, 0 when the value is not representable -
 * directed generators simply skip those. Every success is verified
 * against enc_to_mpfr before it is used, because a generator bug
 * here would silently test the wrong value. */
static int enc_from_val(const fdesc *f, int sign, uint64_t m, long e2,
                        uint8_t *b)
{
    int msb = 63, w = 1 + f->exp_w + f->man_w;
    long E;

    if (m == 0)
        return 0;
    while (!((m >> msb) & 1))
        msb--;
    E = e2 + msb;
    memset(b, 0, 32);
    if (E > f->emax)
        return 0;
    if (E >= f->emin) {
        int shift = f->man_w - msb;
        if (shift >= 0) {
            set_field(b, shift, msb + 1, m);
        } else {
            if (-shift > 63 || (m & ((1ull << -shift) - 1)))
                return 0;                    /* low bits would be lost */
            set_field(b, 0, msb + 1 + shift, m >> -shift);
        }
        set_field(b, f->man_w, f->exp_w, (uint64_t)(E + f->emax));
    } else {
        long pos = e2 - (f->emin - f->man_w);
        if (pos >= 0) {
            if (msb + pos >= f->man_w)
                return 0;                    /* cannot happen: E < emin */
            set_field(b, (int)pos, msb + 1, m);
        } else {
            if (-pos > 63 || (m & ((1ull << -pos) - 1)))
                return 0;                    /* below the subnormal grid */
            set_field(b, 0, msb + 1 + (int)pos, m >> -pos);
        }
    }
    if (sign)
        set_field(b, w - 1, 1, 1);
    {
        mpfr_t chk, ref;
        mpfr_init2(chk, f->p);
        mpfr_init2(ref, 70);
        enc_to_mpfr(f, b, chk);
        mpfr_set_ui(ref, (unsigned long)(m >> 32), MPFR_RNDN);
        mpfr_mul_2ui(ref, ref, 32, MPFR_RNDN);
        mpfr_add_ui(ref, ref, (unsigned long)(m & 0xffffffffu),
                    MPFR_RNDN);              /* both steps exact at 70b */
        mpfr_mul_2si(ref, ref, e2, MPFR_RNDN);
        if (sign)
            mpfr_neg(ref, ref, MPFR_RNDN);
        if (!mpfr_equal_p(chk, ref)) {
            fprintf(stderr,
                    "enc_from_val self-check failed: %s sign=%d "
                    "m=0x%llx e2=%ld\n", f->name, sign,
                    (unsigned long long)m, e2);
            exit(3);
        }
        mpfr_clear(chk);
        mpfr_clear(ref);
    }
    return 1;
}

/* Round the EXACT finite value x into format f under MODES[mi], with
 * oracle()'s own delivery derivation: the unbounded p-bit rounding is
 * the overflow/underflow authority (tininess after rounding by
 * construction), subnormal landings re-round the true value on the
 * fixed grid, RMM goes through the p+1 guard/sticky build. Where
 * oracle() recomputes the operation, this rounds a known value -
 * every clause-5 rounding is one rounding of an exactly-held value,
 * so mpfr_set IS the operation here. */
static void c5_round_into(const fdesc *f, const mpfr_t x, int mi,
                          mpfr_t out, uint32_t *flags)
{
    ieee_round_into(f, x, MODES[mi].mr, MODES[mi].cr == CFT_RMM, out,
                    flags);
}

/* roundToIntegral by attribute (rint_by_mode here until parcel HXb) is
 * mpfr_c5.h's c5_rint_value(). */

/* An expected value, printed WITHOUT mpfr_out_str.
 *
 * mpfr_out_str with n = 0 segfaults on a zero in MPFR 4.2.1 as built
 * here, and dies on an extreme exponent as well - measured 2026-09-02,
 * both from this file. Either one turns the first reported mismatch
 * into a dead process and takes the report with it, which is the worst
 * possible failure mode for an oracle: it can only crash when it has
 * something to say. So the mantissa and the exponent are printed
 * directly, which is bounded work for any value MPFR can hold. */
static void print_mpfr(mpfr_srcptr v)
{
    mpz_t m;
    mpfr_exp_t e;
    /* A caller-supplied buffer, not mpz_get_str(NULL, ...): GMP
     * allocates with its own allocator and free() is not necessarily
     * its deallocator, which corrupts the heap on this toolchain. The
     * mantissa is at most p bits, so 128 bytes is generous. */
    char buf[128];
    if (mpfr_nan_p(v)) { printf("nan"); return; }
    if (mpfr_inf_p(v)) { printf("%sinf", mpfr_signbit(v) ? "-" : ""); return; }
    if (mpfr_zero_p(v)) { printf("%s0", mpfr_signbit(v) ? "-" : ""); return; }
    mpz_init(m);
    e = mpfr_get_z_2exp(m, v);
    if (mpz_sizeinbase(m, 16) + 3 <= sizeof buf) {
        mpz_get_str(buf, 16, m);
        printf("0x%s p2^%ld", buf, (long)e);
    } else {
        printf("<%lu hex digits> p2^%ld",
               (unsigned long)mpz_sizeinbase(m, 16), (long)e);
    }
    mpz_clear(m);
}

static void report_c5(const char *opn, const char *mode, const fdesc *fa,
                      const uint8_t *a, const uint8_t *b, const fdesc *fg,
                      const uint8_t *got, mpfr_srcptr want, uint32_t gf,
                      uint32_t wf, int value_bad, const char *extra)
{
    char ha[65], hb[65], hg[65];
    if (shown >= 16)
        return;
    shown++;
    if (a) hexdump(a, fa->esz, ha); else strcpy(ha, "-");
    if (b) hexdump(b, fa->esz, hb); else strcpy(hb, "-");
    hexdump(got, fg->esz, hg);
    printf("  %s %s %s %s a=0x%s b=0x%s %s\n",
           value_bad ? "MISMATCH" : "FLAGS", fa->name, opn, mode, ha, hb,
           extra ? extra : "");
    printf("    lib=0x%s flags=0x%02x  mpfr=", hg, (unsigned)gf);
    print_mpfr(want);
    printf(" flags=0x%02x\n", (unsigned)wf);
}

/* One case's verdict: value plus flags, ledger, first-16 reporting. */
static void c5_judge(int ti, int fj, const char *opn, const char *mode,
                     const fdesc *fa, const uint8_t *a, const uint8_t *b,
                     const fdesc *fg, const uint8_t *got, mpfr_srcptr want,
                     uint32_t gf, uint32_t wf, cft_status st,
                     const char *extra)
{
    int vbad = (st != CFT_OK) || !agree(fg, got, want);
    int fbad = (gf != wf);
    if (vbad)
        mismatches++;
    if (fbad)
        flag_mismatches++;
    if (vbad || fbad)
        report_c5(opn, mode, fa, a, b, fg, got, want, gf, wf, vbad,
                  st != CFT_OK ? "(status!=OK)" : extra);
    cases++;
    tally[ti][fj]++;
}

/* ---- roundToIntegral ---------------------------------------------- */

static void check_rint(int fj, uint8_t pool[][32], int pn)
{
    const fdesc *f = &FMTS[fj];
    uint8_t extra[64][32];
    uint8_t d[32];
    int ne = 0, i, mi, exact, s;

    /* the tie families: n + 1/2 both signs, quarters, and the
     * integral threshold 2^(p-1) with its neighbours - enc-1 of the
     * threshold is 2^(p-1) - 1/2, the last value with a fraction */
    for (s = 0; s <= 1; s++) {
        uint64_t k;
        for (k = 0; k <= 7; k++)
            if (enc_from_val(f, s, 2 * k + 1, -1, extra[ne]))
                ne++;
        if (enc_from_val(f, s, 45, -1, extra[ne])) ne++;      /* 22.5 */
        if (enc_from_val(f, s, 1, -2, extra[ne])) ne++;
        if (enc_from_val(f, s, 3, -2, extra[ne])) ne++;
        if (enc_from_val(f, s, 5, -2, extra[ne])) ne++;
        if (enc_from_val(f, s, 7, -2, extra[ne])) ne++;
        if (enc_from_val(f, 0, 1, f->p - 1, extra[ne])) {
            if (s)
                enc_neg(f, extra[ne]);
            memcpy(extra[ne + 1], extra[ne], 32);
            enc_step(f, extra[ne + 1], 0);
            memcpy(extra[ne + 2], extra[ne], 32);
            enc_step(f, extra[ne + 2], 1);
            ne += 3;
        }
    }

    for (mi = 0; mi < 5; mi++)
        for (exact = 0; exact <= 1; exact++)
            for (i = 0; i < pn + ne; i++) {
                const uint8_t *a = i < pn ? pool[i] : extra[i - pn];
                uint32_t gf = 0, wf = 0;
                mpfr_t want;
                cft_status st;
                char note[24];

                mpfr_init2(want, f->p);
                c5_rint_expect(f, a, MODES[mi].cr, exact, want, &wf);
                memset(d, 0, sizeof d);
                st = cft_rint(dev, f->fmt, MODES[mi].cr, exact, a, d, 1,
                              &gf, NULL);
                snprintf(note, sizeof note, "exact=%d", exact);
                c5_judge(exact ? T_RINTX : T_RINT, fj, "rint",
                         MODES[mi].name, f, a, NULL, f, d, want, gf, wf,
                         st, note);
                mpfr_clear(want);
            }
}

/* ---- scaleB ------------------------------------------------------- */

static void check_scaleb(int fj, uint8_t pool[][32], int pn)
{
    const fdesc *f = &FMTS[fj];
    int64_t ns[24];
    uint8_t d[32];
    int nn = 0, i, mi, k;
    int64_t emax = f->emax, p = f->p;

    /* every n regime: zero, small, the precision, the range edges,
     * the staging chunks above emax, past every saturation clamp,
     * the composed/host boundary at emin - p + 1, and the raw int64
     * extremes */
    ns[nn++] = 0;  ns[nn++] = 1;  ns[nn++] = -1;
    ns[nn++] = 2;  ns[nn++] = -2;
    ns[nn++] = p;  ns[nn++] = -p; ns[nn++] = f->man_w;
    ns[nn++] = emax;      ns[nn++] = emax + 1;
    ns[nn++] = -emax;     ns[nn++] = 2 * emax + p;
    ns[nn++] = 3 * emax;  ns[nn++] = 3 * emax + 1;
    ns[nn++] = 3 * emax + 1234567;
    ns[nn++] = f->emin - f->man_w;          /* deepest composed n */
    ns[nn++] = f->emin - p;                 /* first host-path n */
    ns[nn++] = -2 * emax;
    ns[nn++] = -(4 * emax + 2 * p) + 1;     /* the host clamp, straddled */
    ns[nn++] = -(4 * emax + 2 * p);
    ns[nn++] = -(4 * emax + 2 * p) - 1;
    ns[nn++] = INT64_MAX;
    ns[nn++] = INT64_MIN;

    for (k = 0; k < nn; k++)
        for (mi = 0; mi < 5; mi++)
            for (i = 0; i < pn; i++) {
                const uint8_t *a = pool[i];
                uint32_t gf = 0, wf = 0;
                mpfr_t want;
                cft_status st;
                char note[40];

                mpfr_init2(want, f->p);
                c5_scaleb_expect(f, a, ns[k], MODES[mi].cr, want, &wf);
                memset(d, 0, sizeof d);
                st = cft_scaleb(dev, f->fmt, MODES[mi].cr, a, ns[k], d, 1,
                                &gf, NULL);
                snprintf(note, sizeof note, "n=%lld", (long long)ns[k]);
                c5_judge(T_SCALEB, fj, "scaleb", MODES[mi].name, f, a,
                         NULL, f, d, want, gf, wf, st, note);
                mpfr_clear(want);
            }
}

/* ---- convertFormat ------------------------------------------------ */

static void check_convert(int sfi, int dfi, uint8_t pool[][32], int pn)
{
    const fdesc *fs = &FMTS[sfi], *fd = &FMTS[dfi];
    uint8_t extra[24][32];
    uint8_t d[32];
    int ne = 0, i, mi;
    char note[16];

    if (fs->man_w > fd->man_w) {
        /* narrowing stress: destination-grid ties built in the wider
         * source - a one at the destination's rounding position
         * (exact tie), and the same with the sticky bit lit (just
         * above the tie) - at a plain exponent, at the destination's
         * emax, and down on its subnormal grid */
        long Es[5];
        int nE = 0, t, s, v;
        Es[nE++] = 0;
        Es[nE++] = fd->emax;
        Es[nE++] = fd->emin;
        Es[nE++] = fd->emin - 3;
        Es[nE++] = fd->emin - fd->man_w + 1;
        for (t = 0; t < nE; t++)
            for (s = 0; s <= 1; s++)
                for (v = 0; v <= 1; v++) {
                    uint8_t *b = extra[ne];
                    memset(b, 0, 32);
                    set_field(b, fs->man_w, fs->exp_w,
                              (uint64_t)(Es[t] + fs->emax));
                    set_field(b, fs->man_w - (fd->man_w + 1), 1, 1);
                    if (v)
                        set_field(b, 0, 1, 1);
                    if (s)
                        enc_neg(fs, b);
                    ne++;
                }
    }
    snprintf(note, sizeof note, "->%s", fd->name);

    for (mi = 0; mi < 5; mi++)
        for (i = 0; i < pn + ne; i++) {
            const uint8_t *a = i < pn ? pool[i] : extra[i - pn];
            uint32_t gf = 0, wf = 0;
            mpfr_t want;
            cft_status st;

            mpfr_init2(want, fd->p);
            c5_convert_expect(fs, fd, a, MODES[mi].cr, want, &wf);
            memset(d, 0, sizeof d);
            st = cft_convert(dev, fs->fmt, fd->fmt, MODES[mi].cr, a, d, 1,
                             &gf);
            c5_judge(T_CONVERT, sfi, "convert", MODES[mi].name, fs, a,
                     NULL, fd, d, want, gf, wf, st, note);
            mpfr_clear(want);
        }
}

/* ---- convertFromInt ----------------------------------------------- */

static void check_cvt_from(int fj, int nrand)
{
    const fdesc *f = &FMTS[fj];
    static const uint64_t DI[] = {
        0, 1, 2, 3, 5, 7, 0xff,
        (1ull << 23) - 1, 1ull << 23, (1ull << 23) + 1,
        (1ull << 24) - 1, 1ull << 24, (1ull << 24) + 1,
        (1ull << 24) + 2, (1ull << 25) + 2,
        (1ull << 31) - 1, 1ull << 31, (1ull << 31) + 1,
        (1ull << 32) - 1, 1ull << 32, (1ull << 32) + 1,
        (1ull << 52) - 1, 1ull << 52, (1ull << 52) + 1,
        (1ull << 53) - 1, 1ull << 53, (1ull << 53) + 1, (1ull << 53) + 2,
        1ull << 62, (1ull << 63) - 1, 1ull << 63, (1ull << 63) + 1,
        ~0ull, ~0ull - 1,
        0xaaaaaaaaaaaaaaaaull, 0x5555555555555555ull,
        0x7fffffffull, 0x80000000ull, 0x80000001ull,
        0x7fffffffffffffffull,
    };
    enum { NDI = (int)(sizeof DI / sizeof DI[0]) };
    uint64_t vals[NDI + 96];
    uint8_t d[32];
    int nv = 0, ty, mi, i;

    for (i = 0; i < (int)NDI; i++)
        vals[nv++] = DI[i];
    for (i = 0; i < nrand && nv < (int)NDI + 96; i++) {
        uint64_t v = rng();        /* the value, then its shift: two */
        vals[nv++] = v >> (rng() & 63);   /* statements, as above */
    }

    for (ty = 0; ty < 4; ty++)
        for (mi = 0; mi < 5; mi++)
            for (i = 0; i < nv; i++) {
                uint64_t raw = vals[i];
                int ti = 0;
                const char *opn = "?";
                uint32_t gf = 0, wf = 0;
                mpfr_t want;
                cft_status st = CFT_ERR_INTERNAL;
                char note[32];

                switch (ty) {
                case 0:  ti = T_FROM_I32; opn = "from_i32"; break;
                case 1:  ti = T_FROM_U32; opn = "from_u32"; break;
                case 2:  ti = T_FROM_I64; opn = "from_i64"; break;
                default: ti = T_FROM_U64; opn = "from_u64"; break;
                }

                mpfr_init2(want, f->p);
                c5_cvtfrom_expect(f, ty, raw, MODES[mi].cr, want, &wf);

                memset(d, 0, sizeof d);
                switch (ty) {
                case 0: {
                    int32_t x = (int32_t)(uint32_t)raw;
                    st = cft_cvt_from_i32(dev, f->fmt, MODES[mi].cr, &x,
                                          d, 1, &gf);
                    break;
                }
                case 1: {
                    uint32_t x = (uint32_t)raw;
                    st = cft_cvt_from_u32(dev, f->fmt, MODES[mi].cr, &x,
                                          d, 1, &gf);
                    break;
                }
                case 2: {
                    int64_t x = (int64_t)raw;
                    st = cft_cvt_from_i64(dev, f->fmt, MODES[mi].cr, &x,
                                          d, 1, &gf);
                    break;
                }
                default: {
                    uint64_t x = raw;
                    st = cft_cvt_from_u64(dev, f->fmt, MODES[mi].cr, &x,
                                          d, 1, &gf);
                    break;
                }
                }
                snprintf(note, sizeof note, "v=0x%llx",
                         (unsigned long long)raw);
                c5_judge(ti, fj, opn, MODES[mi].name, f, NULL, NULL, f, d,
                         want, gf, wf, st, note);
                mpfr_clear(want);
            }
}

/* ---- convertToInteger --------------------------------------------- */

static void check_cvt_to(int fj, uint8_t pool[][32], int pn, int nrand)
{
    const fdesc *f = &FMTS[fj];
    /* The delivered values of the invalid cases are the CONTRACT's
     * RISC-V FCVT table, hardcoded from cft.h's doc: mpfr_c5.h's C5_TO,
     * the targets in the order i32, u32, i64, u64 (the tally's T_TO_I32
     * onward, in the same order). */
    uint8_t extra[112][32];
    int ne = 0, ty, mi, exact, i, s;

    /* halves and quarters both signs, plus the representable
     * boundary ties (2^31 +- 1/2, 2^32 + 1/2, 2^63 - 1/2, 2^63 + 1) */
    for (s = 0; s <= 1; s++) {
        static const struct { uint64_t m; long e; } HV[6] = {
            {1, -1}, {3, -1}, {5, -1}, {7, -1}, {1, -2}, {3, -2},
        };
        for (i = 0; i < 6; i++)
            if (enc_from_val(f, s, HV[i].m, HV[i].e, extra[ne]))
                ne++;
        if (enc_from_val(f, s, (1ull << 32) + 1, -1, extra[ne])) ne++;
        if (enc_from_val(f, s, (1ull << 32) - 1, -1, extra[ne])) ne++;
        if (enc_from_val(f, s, (1ull << 33) + 1, -1, extra[ne])) ne++;
        if (enc_from_val(f, s, ~0ull, -1, extra[ne])) ne++;
        if (enc_from_val(f, s, (1ull << 63) + 1, 0, extra[ne])) ne++;
    }
    /* the powers at the type edges with their nearest neighbours,
     * both signs - 66 is past the implementation's early-out and past
     * every 64-bit range whatever the rounding */
    {
        static const long BE[5] = { 31, 32, 63, 64, 66 };
        for (i = 0; i < 5; i++) {
            if (!enc_from_val(f, 0, 1, BE[i], extra[ne]))
                continue;
            memcpy(extra[ne + 1], extra[ne], 32);
            enc_step(f, extra[ne + 1], 0);
            memcpy(extra[ne + 2], extra[ne], 32);
            enc_step(f, extra[ne + 2], 1);
            memcpy(extra[ne + 3], extra[ne], 32);
            enc_neg(f, extra[ne + 3]);
            memcpy(extra[ne + 4], extra[ne + 1], 32);
            enc_neg(f, extra[ne + 4]);
            memcpy(extra[ne + 5], extra[ne + 2], 32);
            enc_neg(f, extra[ne + 5]);
            ne += 6;
        }
    }
    /* integer-range randoms: exponents banded into [-6, 71], where
     * the rounding is interesting - the shared pool's own randoms
     * already cover the far-out-of-range mass */
    for (i = 0; i < nrand && ne < 112; i++) {
        long E = (long)(rng() % 78) - 6;
        rand_enc(f, extra[ne]);
        set_field(extra[ne], f->man_w, f->exp_w, (uint64_t)(E + f->emax));
        ne++;
    }

    for (ty = 0; ty < 4; ty++) {
        for (mi = 0; mi < 5; mi++)
            for (exact = 0; exact <= 1; exact++)
                for (i = 0; i < pn + ne; i++) {
                    const uint8_t *a = i < pn ? pool[i] : extra[i - pn];
                    uint32_t gf = 0, wf = 0;
                    uint64_t want64 = 0, got64 = 0, mask;
                    cft_status st = CFT_ERR_INTERNAL;

                    mask = C5_TO[ty].width == 32 ? 0xffffffffull : ~0ull;
                    c5_cvtto_expect(f, a, ty, MODES[mi].cr, exact, &want64,
                                    &wf);

                    switch (ty) {
                    case 0: {
                        int32_t o = 0;
                        st = cft_cvt_to_i32(dev, f->fmt, MODES[mi].cr,
                                            exact, a, &o, 1, &gf);
                        got64 = (uint64_t)(uint32_t)o;
                        break;
                    }
                    case 1: {
                        uint32_t o = 0;
                        st = cft_cvt_to_u32(dev, f->fmt, MODES[mi].cr,
                                            exact, a, &o, 1, &gf);
                        got64 = o;
                        break;
                    }
                    case 2: {
                        int64_t o = 0;
                        st = cft_cvt_to_i64(dev, f->fmt, MODES[mi].cr,
                                            exact, a, &o, 1, &gf);
                        got64 = (uint64_t)o;
                        break;
                    }
                    default: {
                        uint64_t o = 0;
                        st = cft_cvt_to_u64(dev, f->fmt, MODES[mi].cr,
                                            exact, a, &o, 1, &gf);
                        got64 = o;
                        break;
                    }
                    }

                    {
                        int vbad = (st != CFT_OK) ||
                                   (got64 & mask) != (want64 & mask);
                        int fbad = (gf != wf);
                        if (vbad)
                            mismatches++;
                        if (fbad)
                            flag_mismatches++;
                        if ((vbad || fbad) && shown < 16) {
                            char ha[65];
                            shown++;
                            hexdump(a, f->esz, ha);
                            printf("  %s %s %s %s exact=%d a=0x%s\n",
                                   vbad ? "MISMATCH" : "FLAGS", f->name,
                                   C5_TO[ty].name, MODES[mi].name, exact,
                                   ha);
                            printf("    lib=0x%llx flags=0x%02x  "
                                   "want=0x%llx flags=0x%02x\n",
                                   (unsigned long long)(got64 & mask),
                                   (unsigned)gf,
                                   (unsigned long long)(want64 & mask),
                                   (unsigned)wf);
                        }
                        cases++;
                        tally[T_TO_I32 + ty][fj]++;
                    }
                }
    }
}

/* ---- logB --------------------------------------------------------- */

static void check_logb(int fj, uint8_t pool[][32], int pn, int nrand)
{
    const fdesc *f = &FMTS[fj];
    uint8_t extra[80][32];
    uint8_t d[32];
    int ne = 0, i, s;

    for (s = 0; s <= 1; s++) {
        if (enc_from_val(f, s, 1, f->emin - f->man_w, extra[ne])) ne++;
        if (enc_from_val(f, s, 3, f->emin - f->man_w, extra[ne])) ne++;
        if (enc_from_val(f, s, 1, f->emin - 1, extra[ne])) ne++;
        if (enc_from_val(f, s, 1, f->emin, extra[ne])) ne++;
        if (enc_from_val(f, s, 1, f->emax, extra[ne])) ne++;
        if (enc_from_val(f, s, 3, -1, extra[ne])) ne++;       /* 1.5 */
    }
    for (i = 0; i < nrand && ne < 80; i++) {
        rand_enc(f, extra[ne]);
        set_field(extra[ne], f->man_w, f->exp_w, 0);  /* subnormal band */
        ne++;
    }

    for (i = 0; i < pn + ne; i++) {
        const uint8_t *a = i < pn ? pool[i] : extra[i - pn];
        uint32_t gf = 0, wf = 0;
        mpfr_t av, want;
        cls ca;
        cft_status st;

        classify(f, a, &ca);
        mpfr_init2(av, f->p);
        mpfr_init2(want, f->p);
        enc_to_mpfr(f, a, av);
        if (ca.is_nan) {
            mpfr_set_nan(want);
            if (ca.is_snan)
                wf |= CFT_FLAG_INVALID;
        } else if (ca.is_zero) {
            mpfr_set_inf(want, -1);
            wf |= CFT_FLAG_DIVBYZERO;
        } else if (ca.is_inf) {
            mpfr_set_inf(want, 1);            /* both signs, silently */
        } else {
            /* mpfr_get_exp sees the mantissa in [1/2, 1); IEEE's logB
             * sees [1, 2), one binade lower. Value-based, so
             * subnormals report their true exponent. |logB| <= emax +
             * man_w < 2^19 even at fp256, so the delivery is exact in
             * every format - asserted, not hoped. */
            long E = (long)mpfr_get_exp(av) - 1;
            if (mpfr_set_si(want, E, MPFR_RNDN) != 0) {
                fprintf(stderr, "logb oracle: E=%ld inexact in %s?!\n",
                        E, f->name);
                exit(3);
            }
        }
        memset(d, 0, sizeof d);
        st = cft_logb(dev, f->fmt, a, d, 1, &gf);
        c5_judge(T_LOGB, fj, "logb", "-", f, a, NULL, f, d, want, gf, wf,
                 st, NULL);
        mpfr_clear(av);
        mpfr_clear(want);
    }
}

/* ---- nextUp / nextDown -------------------------------------------- */

static void check_next(int fj, uint8_t pool[][32], int pn)
{
    const fdesc *f = &FMTS[fj];
    uint8_t d[32], aflip[32];
    int i, dirn, s;

    for (dirn = 0; dirn < 2; dirn++)          /* 0 up, 1 down */
        for (s = 0; s <= 1; s++)
            for (i = 0; i < pn; i++) {
                const uint8_t *a;
                uint32_t gf = 0, wf = 0, discard = 0;
                mpfr_t av, want;
                cls ca;
                cft_status st;

                if (s) {
                    memcpy(aflip, pool[i], 32);
                    enc_neg(f, aflip);
                    a = aflip;
                } else {
                    a = pool[i];
                }
                classify(f, a, &ca);
                mpfr_init2(av, f->p);
                mpfr_init2(want, f->p);
                enc_to_mpfr(f, a, av);
                if (ca.is_nan) {
                    mpfr_set_nan(want);
                    if (ca.is_snan)
                        wf |= CFT_FLAG_INVALID;
                } else {
                    /* one representable step in unbounded range, then
                     * a directed re-round onto the format's grid;
                     * MODES[3] is rup, MODES[2] is rdn. The
                     * quantisation's flags are discarded: nextUp's
                     * only signal is the sNaN invalid above. */
                    if (dirn == 0)
                        mpfr_nextabove(av);
                    else
                        mpfr_nextbelow(av);
                    if (mpfr_inf_p(av))
                        mpfr_set(want, av, MPFR_RNDN); /* the fixed point */
                    else
                        c5_round_into(f, av, dirn == 0 ? 3 : 2, want,
                                      &discard);
                }
                memset(d, 0, sizeof d);
                st = dirn == 0
                    ? cft_next_up(dev, f->fmt, a, d, 1, &gf)
                    : cft_next_down(dev, f->fmt, a, d, 1, &gf);
                c5_judge(dirn == 0 ? T_NEXTUP : T_NEXTDOWN, fj,
                         dirn == 0 ? "next_up" : "next_down", "-", f, a,
                         NULL, f, d, want, gf, wf, st, NULL);
                mpfr_clear(av);
                mpfr_clear(want);
            }
}

/* ---- remainder ---------------------------------------------------- */

static void check_rem(int fj, uint8_t pool[][32], int pn, int nrand)
{
    const fdesc *f = &FMTS[fj];
    static uint8_t xa[160][32], xb[160][32];
    uint8_t d[32];
    int np = 0, i, j, s;

    /* exact ties: (2k+1)/2 rem 1 - the quotient sits exactly on a
     * half and ties-to-even decides; both signs of x */
    for (s = 0; s <= 1; s++)
        for (i = 0; i <= 7 && np < 160; i++)
            if (enc_from_val(f, s, 2 * (uint64_t)i + 1, -1, xa[np]) &&
                enc_from_val(f, 0, 1, 0, xb[np]))
                np++;
    /* the same against an odd divisor: 3(2m+1)/2 rem 3 */
    for (s = 0; s <= 1; s++)
        for (i = 0; i <= 3 && np < 160; i++)
            if (enc_from_val(f, s, 6 * (uint64_t)i + 3, -1, xa[np]) &&
                enc_from_val(f, 0, 3, 0, xb[np]))
                np++;
    /* one encoding step either side of a tie: near-half quotients */
    for (s = 0; s <= 1; s++)
        for (i = 0; i < 2 && np < 157; i++) {
            uint64_t m = i ? 33 : 9;
            if (!enc_from_val(f, s, m, -1, xa[np]))
                continue;
            (void)enc_from_val(f, 0, 3, 0, xb[np]);
            memcpy(xa[np + 1], xa[np], 32);
            enc_step(f, xa[np + 1], 0);
            memcpy(xb[np + 1], xb[np], 32);
            memcpy(xa[np + 2], xa[np], 32);
            enc_step(f, xa[np + 2], 1);
            memcpy(xb[np + 2], xb[np], 32);
            np += 3;
        }
    /* the adversarial exponent gap, once per divisor: max_normal
     * against the smallest subnormals - at fp256 this is the
     * documented ~786k-step quotient-bit walk */
    if (np < 159) {
        memset(xa[np], 0, 32);
        set_field(xa[np], f->man_w, f->exp_w, (1ull << f->exp_w) - 2);
        for (i = 0; i < f->man_w; i++)
            set_field(xa[np], i, 1, 1);
        memset(xb[np], 0, 32);
        set_field(xb[np], 0, 1, 1);
        memcpy(xa[np + 1], xa[np], 32);
        memset(xb[np + 1], 0, 32);
        set_field(xb[np + 1], 0, 2, 3);
        np += 2;
    }
    /* gap-banded random pairs: y's exponent pulled within +-600 of
     * x's, so the walk is exercised without owning the clock */
    for (i = 0; i < nrand && np < 160; i++) {
        long ea, eb;
        long delta = (long)(rng() % 1201) - 600;
        rand_enc(f, xa[np]);
        rand_enc(f, xb[np]);
        ea = (long)get_field(xa[np], f->man_w, f->exp_w);
        eb = ea + delta;
        if (eb < 0)
            eb = 0;
        if (eb > (long)((1ull << f->exp_w) - 2))
            eb = (long)((1ull << f->exp_w) - 2);
        set_field(xb[np], f->man_w, f->exp_w, (uint64_t)eb);
        np++;
    }

    for (i = 0; i < pn + np; i++) {
        int jmax = i < pn ? pn : 1;
        for (j = 0; j < jmax; j++) {
            const uint8_t *pa = i < pn ? pool[i] : xa[i - pn];
            const uint8_t *pb = i < pn ? pool[j] : xb[i - pn];
            uint32_t gf = 0, wf = 0;
            mpfr_t av, bv, want;
            cls ca, cb;
            cft_status st;
            int tern = 0;

            classify(f, pa, &ca);
            classify(f, pb, &cb);
            mpfr_init2(av, f->p);
            mpfr_init2(bv, f->p);
            mpfr_init2(want, f->p);
            enc_to_mpfr(f, pa, av);
            enc_to_mpfr(f, pb, bv);
            if (ca.is_nan || cb.is_nan) {
                mpfr_set_nan(want);
                if (ca.is_snan || cb.is_snan)
                    wf |= CFT_FLAG_INVALID;
            } else if (ca.is_inf || cb.is_zero) {
                mpfr_set_nan(want);
                wf |= CFT_FLAG_INVALID;
            } else if (cb.is_inf || ca.is_zero) {
                mpfr_set(want, av, MPFR_RNDN);   /* x, sign included */
            } else {
                tern = mpfr_remainder(want, av, bv, MPFR_RNDN);
                if (mpfr_zero_p(want))
                    mpfr_setsign(want, want, ca.sign, MPFR_RNDN);
            }
            if (tern != 0) {
                /* the remainder of two p-bit values is representable
                 * in p bits (the standard theorem); a nonzero ternary
                 * is a harness-assumption failure, surfaced rather
                 * than absorbed */
                mismatches++;
                if (shown < 16) {
                    shown++;
                    printf("  REM-TERNARY %s: mpfr_remainder claims "
                           "inexact\n", f->name);
                }
            }
            memset(d, 0, sizeof d);
            st = cft_rem(dev, f->fmt, pa, pb, d, 1, &gf);
            /* the flag equality below IS the exactness assertion: wf
             * never contains inexact/overflow/underflow, so the
             * library raising any of them fails the case */
            c5_judge(T_REM, fj, "rem", "-", f, pa, pb, f, d, want, gf,
                     wf, st, NULL);
            mpfr_clear(av);
            mpfr_clear(bv);
            mpfr_clear(want);
        }
    }
}

/* ---- the augmented arithmetic operations (754-2019 9.5) ------------ *
 *
 * WHY THIS IS AN ORACLE, AND WHAT IT IS AN ORACLE FOR.
 *
 * MPFR has no roundTiesTowardZero. It has no mode that breaks a tie
 * toward the smaller magnitude, and MPFR_RNDZ is not it - RNDZ
 * truncates every inexact value, not only the ties. So this harness
 * cannot ask MPFR for the answer; it asks MPFR for the EXACT VALUE and
 * applies 9.5's rule itself:
 *
 *   1. compute x op y at a precision that holds the exact result with
 *      no rounding at all, and PROVE it did by requiring MPFR's ternary
 *      to be zero. That precision is not 2p: the exact sum of two
 *      p-bit values whose exponents span the whole format is
 *      emax - emin + p bits wide (524,522 at binary256), and the
 *      product's residual against a subnormal result is nearly as wide.
 *      AUG_PREC below covers both with margin, and the ternary check is
 *      what makes "exact" a measurement rather than an assumption.
 *   2. round that exact value to the format by 9.5's own definition -
 *      scale to the format's grid, split into an integer and a
 *      fraction with exact MPFR arithmetic, and compare the fraction
 *      with one half: strictly above rounds away, equal keeps the
 *      smaller magnitude ("the one with smaller magnitude shall be
 *      delivered"), below truncates. Overflow is the rounded value's
 *      exponent exceeding emax, and 9.5 sends it to an infinity.
 *   3. subtract exactly for the error term, and decide representability
 *      by rounding it the same way and asking whether the rounding
 *      changed it - which is 9.5's "can be represented exactly as a
 *      finite number in sourceFormat" tested rather than reasoned.
 *
 * Every arithmetic step above is MPFR's, every step is exact by
 * construction and checked to be, and the only thing this file
 * contributes is the tie rule and the flag policy - which are the two
 * things 9.5 states in words and the library must be scored against.
 * That makes this a genuine independent oracle for the VALUES and a
 * restatement for the FLAGS, and saying which is which is the point of
 * this paragraph.
 *
 * The flags are 9.5's, not clause 7's defaults: inexact "only when
 * roundTiesTowardZero(x + y) overflows", underflow when the error term
 * is "non-zero and lies strictly between +-b^emin" even though that
 * error term is exact, and both together for the one case 9.5 gives
 * augmentedMultiplication where the residual falls below the subnormal
 * grid.
 */

#define AUG_COUNT 3
static const char *const AUGN[AUG_COUNT] = { "aug_add", "aug_sub",
                                             "aug_mul" };

/* Wide enough to hold every exact intermediate: the widest is a SUM
 * spanning the whole exponent range, emax - emin + p bits. */
static long aug_prec(const fdesc *f)
{
    return (long)f->emax - f->emin + 2 * f->p + 16;
}

/* Round the exact non-zero finite value v into f's grid under 9.5's
 * roundTiesTowardZero, into `out`. Returns 1 if it overflowed. */
static int aug_rttz(const fdesc *f, mpfr_srcptr v, mpfr_ptr out)
{
    mpz_t n;
    mpfr_t scaled, frac, half;
    long E, q, er;
    int sign = mpfr_signbit(v) ? 1 : 0, cmp, ovf = 0;

    E = (long)mpfr_get_exp(v) - 1;               /* floor(log2 |v|) */
    q = (E > f->emin ? E : f->emin) - (f->p - 1);
    mpz_init(n);
    mpfr_init2(scaled, aug_prec(f));
    mpfr_init2(frac, aug_prec(f));
    mpfr_init2(half, 8);
    mpfr_abs(scaled, v, MPFR_RNDN);
    mpfr_mul_2si(scaled, scaled, -q, MPFR_RNDN); /* exact: an exponent */
    mpfr_get_z(n, scaled, MPFR_RNDZ);            /* floor */
    mpfr_sub_z(frac, scaled, n, MPFR_RNDN);      /* exact */
    mpfr_set_ui_2exp(half, 1, -1, MPFR_RNDN);
    cmp = mpfr_cmp(frac, half);
    if (cmp > 0)
        mpz_add_ui(n, n, 1);                     /* strictly above half */
    /* cmp == 0 is the TIE, and 9.5 keeps the smaller magnitude: nothing
     * happens here, and that one line is the whole difference from
     * roundTiesToEven. */
    if (mpz_sgn(n) == 0) {
        mpfr_set_zero(out, sign ? -1 : 1);       /* 6.3: the exact sign */
    } else {
        er = q + (long)mpz_sizeinbase(n, 2) - 1;
        if (er > f->emax) {
            ovf = 1;
            mpfr_set_inf(out, sign ? -1 : 1);
        } else {
            mpfr_set_z_2exp(out, n, q, MPFR_RNDN);       /* exact */
            if (sign)
                mpfr_neg(out, out, MPFR_RNDN);
        }
    }
    mpz_clear(n);
    mpfr_clear(scaled);
    mpfr_clear(frac);
    mpfr_clear(half);
    return ovf;
}

/* The pair and the flags for one case. fn: 0 add, 1 sub, 2 mul. */
static void aug_oracle(const fdesc *f, int fn, const uint8_t *ba,
                       const uint8_t *bb, mpfr_ptr want_r, mpfr_ptr want_e,
                       uint32_t *flags)
{
    mpfr_t a, b, exact, rv, err, emin_mag;
    cls ca, cb;
    uint32_t fl = 0;
    int tern = 0, nan_in;
    long P = aug_prec(f);

    classify(f, ba, &ca);
    classify(f, bb, &cb);
    nan_in = ca.is_nan || cb.is_nan;
    if (ca.is_snan || cb.is_snan)
        fl |= CFT_FLAG_INVALID;

    mpfr_init2(a, f->p);
    mpfr_init2(b, f->p);
    mpfr_init2(exact, P);
    mpfr_init2(rv, P);
    mpfr_init2(err, P);
    mpfr_init2(emin_mag, 8);
    enc_to_mpfr(f, ba, a);
    enc_to_mpfr(f, bb, b);

    if (fn == 2)
        tern = mpfr_mul(exact, a, b, MPFR_RNDN);
    else if (fn == 1)
        tern = mpfr_sub(exact, a, b, MPFR_RNDN);
    else
        tern = mpfr_add(exact, a, b, MPFR_RNDN);
    if (tern != 0) {
        /* The working precision was supposed to make this impossible.
         * A non-zero ternary means the harness, not the library, is
         * wrong - surfaced rather than absorbed. */
        mismatches++;
        if (shown < 16) {
            shown++;
            printf("  AUG-TERNARY %s %s: the exact %s was rounded at %ld "
                   "bits\n", f->name, AUGN[fn],
                   fn == 2 ? "product" : "sum", P);
        }
    }

    if (mpfr_nan_p(exact)) {
        mpfr_set_nan(want_r);
        mpfr_set_nan(want_e);
        if (!nan_in)
            fl |= CFT_FLAG_INVALID;      /* inf + (-inf), inf * 0 */
        goto done;
    }
    if (!mpfr_number_p(exact) || mpfr_zero_p(exact)) {
        /* An infinity at unbounded range can only come from an infinite
         * OPERAND, so it signals nothing; a zero carries its own sign
         * (6.3), and 9.5 gives both outputs the same value either way. */
        mpfr_set(want_r, exact, MPFR_RNDN);
        mpfr_set(want_e, exact, MPFR_RNDN);
        goto done;
    }

    if (aug_rttz(f, exact, rv)) {
        mpfr_set(want_r, rv, MPFR_RNDN);
        mpfr_set(want_e, rv, MPFR_RNDN);
        fl |= CFT_FLAG_OVERFLOW | CFT_FLAG_INEXACT;
        goto done;
    }
    mpfr_set(want_r, rv, MPFR_RNDN);

    tern = mpfr_sub(err, exact, rv, MPFR_RNDN);
    if (tern != 0) {
        mismatches++;
        if (shown < 16) {
            shown++;
            printf("  AUG-TERNARY %s %s: the residual was rounded\n",
                   f->name, AUGN[fn]);
        }
    }
    if (mpfr_zero_p(err)) {
        /* 9.5: an error term equal to zero "is returned with the sign of
         * roundTiesTowardZero(x + y)". */
        mpfr_set_zero(want_e, mpfr_signbit(rv) ? -1 : 1);
        goto done;
    }
    {
        mpfr_t rounded;
        int tiny;
        mpfr_set_ui_2exp(emin_mag, 1, f->emin, MPFR_RNDN);
        tiny = mpfr_cmpabs(err, emin_mag) < 0;
        mpfr_init2(rounded, P);
        (void)aug_rttz(f, err, rounded);         /* cannot overflow */
        if (mpfr_equal_p(rounded, err)) {
            mpfr_set(want_e, err, MPFR_RNDN);    /* exactly representable */
            if (tiny)
                fl |= CFT_FLAG_UNDERFLOW;
        } else {
            /* 9.5's one non-representable delivery, augmentedMulti-
             * plication only: the residual rounded the same way, with
             * the underflow flag raised and inexact signalled. */
            mpfr_set(want_e, rounded, MPFR_RNDN);
            fl |= CFT_FLAG_UNDERFLOW | CFT_FLAG_INEXACT;
        }
        mpfr_clear(rounded);
    }

done:
    *flags = fl;
    mpfr_clear(a); mpfr_clear(b); mpfr_clear(exact);
    mpfr_clear(rv); mpfr_clear(err); mpfr_clear(emin_mag);
}

/* Both values and the flag word, as ONE case in the ledger. */
static void aug_judge(int ti, int fj, int fn, const fdesc *f,
                      const uint8_t *a, const uint8_t *b,
                      const uint8_t *gr, const uint8_t *ge,
                      mpfr_srcptr wr, mpfr_srcptr we,
                      uint32_t gf, uint32_t wf, cft_status st)
{
    int rbad = (st != CFT_OK) || !agree(f, gr, wr);
    int ebad = (st != CFT_OK) || !agree(f, ge, we);
    int fbad = (gf != wf);
    if (rbad || ebad)
        mismatches++;
    if (fbad)
        flag_mismatches++;
    if (rbad || fbad)
        report_c5(AUGN[fn], "9.5", f, a, b, f, gr, wr, gf, wf, rbad,
                  st != CFT_OK ? "(status!=OK)" : "(r)");
    if (ebad && !rbad)
        report_c5(AUGN[fn], "9.5", f, a, b, f, ge, we, gf, wf, ebad,
                  "(e, the error term)");
    cases++;
    tally[ti][fj]++;
}

static cft_status aug_lib(const fdesc *f, int fn, const uint8_t *a,
                          const uint8_t *b, uint8_t *r, uint8_t *e,
                          uint32_t *fl)
{
    switch (fn) {
    case 0:  return cft_augmented_add(dev, f->fmt, a, b, r, e, 1, fl);
    case 1:  return cft_augmented_sub(dev, f->fmt, a, b, r, e, 1, fl);
    default: return cft_augmented_mul(dev, f->fmt, a, b, r, e, 1, fl);
    }
}

/* 2^E as a normal encoding (E must be >= emin). */
static void aug_pow2(const fdesc *f, long E, int sign, uint8_t *b)
{
    memset(b, 0, 32);
    set_field(b, f->man_w, f->exp_w, (uint64_t)(E + f->emax));
    if (sign)
        set_field(b, 1 + f->exp_w + f->man_w - 1, 1, 1);
}

static void check_augmented(int fj, uint8_t pool[][32], int pn)
{
    const fdesc *f = &FMTS[fj];
    static uint8_t xa[96][32], xb[96][32];
    int np = 0, fn, i, j, s;
    uint8_t gr[32], ge[32];

    /* THE TIE, at binade edges: x is 2^k + 1 ulp (an ODD significand,
     * which is the only place roundTiesTowardZero and roundTiesToEven
     * can differ) and y is exactly half an ulp of that binade. */
    {
        long ks[6];
        int nk = 0;
        ks[nk++] = 0;
        ks[nk++] = 1;
        ks[nk++] = f->emin;
        ks[nk++] = f->emin + f->p;
        ks[nk++] = f->emax - 1;
        ks[nk++] = f->emax / 2;
        for (i = 0; i < nk; i++) {
            long k = ks[i];
            if (k - f->p < f->emin || np > 88)
                continue;
            for (s = 0; s <= 1; s++) {
                aug_pow2(f, k, s, xa[np]);
                set_field(xa[np], 0, 1, 1);            /* + 1 ulp: odd */
                aug_pow2(f, k - f->p, 0, xb[np]);      /* half an ulp */
                np++;
                aug_pow2(f, k, s, xa[np]);
                set_field(xa[np], 0, 1, 1);
                aug_pow2(f, k - f->p, 1, xb[np]);      /* and below it */
                np++;
            }
        }
    }
    /* THE OVERFLOW THRESHOLD: the largest finite plus exactly half an
     * ulp is the midpoint 9.5 rounds DOWN, silently; one ulp is past
     * it and goes to an infinity with overflow and inexact. */
    for (s = 0; s <= 1 && np < 92; s++) {
        int k;
        for (k = 0; k < 2; k++) {
            memset(xa[np], 0, 32);
            set_field(xa[np], f->man_w, f->exp_w,
                      (uint64_t)((1ull << f->exp_w) - 2));
            for (i = 0; i < f->man_w; i++)
                set_field(xa[np], i, 1, 1);            /* max normal */
            if (s)
                set_field(xa[np], 1 + f->exp_w + f->man_w - 1, 1, 1);
            aug_pow2(f, f->emax - f->p + k, s, xb[np]);
            np++;
        }
    }
    /* A SUBNORMAL RESIDUAL: 1 against the bottom of the grid, which is
     * underflow with no inexact - the combination 9.5 alone produces. */
    for (i = 0; i < 3 && np < 95; i++) {
        aug_pow2(f, i == 0 ? 0 : (i == 1 ? f->p : f->emax - 1), 0, xa[np]);
        memset(xb[np], 0, 32);
        set_field(xb[np], i, 1, 1);                    /* a tiny subnormal */
        np++;
    }

    for (fn = 0; fn < AUG_COUNT; fn++) {
        for (i = 0; i < pn + np; i++) {
            int jmax = i < pn ? pn : 1;
            for (j = 0; j < jmax; j++) {
                const uint8_t *pa = i < pn ? pool[i] : xa[i - pn];
                const uint8_t *pb = i < pn ? pool[j] : xb[i - pn];
                uint32_t gf = 0, wf = 0;
                mpfr_t wr, we;
                cft_status st;

                mpfr_init2(wr, f->p);
                mpfr_init2(we, f->p);
                aug_oracle(f, fn, pa, pb, wr, we, &wf);
                memset(gr, 0, sizeof gr);
                memset(ge, 0, sizeof ge);
                st = aug_lib(f, fn, pa, pb, gr, ge, &gf);
                aug_judge(T_AUG_ADD + fn, fj, fn, f, pa, pb, gr, ge, wr, we,
                          gf, wf, st);
                mpfr_clear(wr);
                mpfr_clear(we);
            }
        }
    }
}

/* ---- clause 5.12: conversions to and from character sequences ------ *
 *
 * MPFR is the right arbiter for these and is used as one in both
 * directions: mpfr_strtofr and mpfr_get_str are correctly rounded in
 * every rounding mode, at any precision, and neither has ever seen
 * this project. So the parse is scored against MPFR's parse and the
 * write against MPFR's digits, values AND flags, in all five
 * attributes at all four rungs.
 *
 * Four things about this block are worth stating rather than leaving
 * to be discovered.
 *
 * 1. There is no mpfr_t that holds the exact value of a decimal
 *    sequence - "0.1" is not dyadic - so c5_round_into cannot be
 *    reused here and chars_round_str below is its derivation with the
 *    source changed from mpfr_set to mpfr_strtofr. Same unbounded
 *    p-bit rounding as the overflow/underflow authority, same
 *    subnormal re-rounding on the format's fixed grid, same p+1
 *    guard/sticky build for RMM - only the thing being rounded
 *    differs. base 0 reads both radices: "0x..." is hexadecimal with a
 *    p exponent, anything else is decimal.
 *
 * 2. RMM is built rather than compared, in both directions, because
 *    MPFR has no ties-to-away. Reading in, it is the same p+1
 *    construction the rest of this file uses. Writing out it is
 *    simpler than that and exactly right: ties-to-away on a DECIMAL
 *    grid rounds up exactly when digit H+1 is 5 or more, and no sticky
 *    is needed for that decision - so the oracle asks mpfr_get_str for
 *    H+1 digits truncated and rounds the last one half-up.
 *
 * 3. The EXACT conversion cannot be asked of mpfr_get_str, which
 *    produces shortest-or-N digits and not the full expansion. It is
 *    scored a different way that is just as strong: the sequence the
 *    library wrote is handed back to mpfr_strtofr at the format's own
 *    precision, and MPFR must report a ternary of ZERO - the parse was
 *    exact - and the same value. A sequence that denotes exactly x is
 *    what "exact" means, and MPFR decides it. Same check for the
 *    hexadecimal form.
 *
 * 4. What is deliberately NOT scored here. The absurd exponents
 *    ("1e999999999999") are outside MPFR's own exponent range, so
 *    feeding them to the oracle would score MPFR's overflow rather
 *    than the format's - the pools stay inside MPFR's range and well
 *    outside every format's, and the bands are scored by the golden
 *    model and the vectors instead. NaN PAYLOADS are not scored here
 *    either: MPFR keeps no payload, so it cannot arbitrate the one
 *    thing 5.12.1's suffix exists for. The 9.7 payload operations are
 *    pure bit surgery with no arithmetic in them at all and belong to
 *    the model, which is where character_check.py scores them.
 */

/* c5_round_into's derivation, on a character sequence. */
static void chars_round_str(const fdesc *f, const char *s, int mi,
                            mpfr_t out, uint32_t *flags)
{
    mpfr_t runb, y;
    int inexact, is_rmm = (MODES[mi].cr == CFT_RMM);
    mpfr_rnd_t rnd = MODES[mi].mr;
    uint32_t fl = 0;
    char *end = NULL;
    int t1;

    mpfr_init2(runb, f->p);
    mpfr_init2(y, f->p + 1);
    if (is_rmm) {
        t1 = mpfr_strtofr(y, s, &end, 0, MPFR_RNDZ);
        rmm_round(runb, y, t1 != 0, f->p);
        inexact = (t1 != 0) || !mpfr_equal_p(y, runb);
    } else {
        t1 = mpfr_strtofr(runb, s, &end, 0, rnd);
        inexact = (t1 != 0);
    }

    if (mpfr_zero_p(runb) && !inexact) {
        mpfr_set_prec(out, f->p);
        mpfr_set(out, runb, MPFR_RNDN);          /* signed zero rides along */
        *flags = 0;
        mpfr_clear(runb);
        mpfr_clear(y);
        return;
    }

    {
        long e_res;
        if (mpfr_zero_p(runb)) {
            /* rounded away below the smallest representable: the
             * subnormal branch decides it */
            e_res = (long)f->emin - 1;
        } else {
            e_res = (long)mpfr_get_exp(runb) - 1;
        }

        if (e_res > f->emax) {
            int away = (rnd == MPFR_RNDU && mpfr_sgn(runb) > 0) ||
                       (rnd == MPFR_RNDD && mpfr_sgn(runb) < 0) ||
                       rnd == MPFR_RNDN || is_rmm;
            if (rnd == MPFR_RNDZ)
                away = 0;
            mpfr_set_prec(out, f->p);
            if (away)
                mpfr_set_inf(out, mpfr_sgn(runb));
            else {
                mpfr_set_ui_2exp(out, 1, f->emax + 1, MPFR_RNDN);
                mpfr_nextbelow(out);
                if (mpfr_sgn(runb) < 0)
                    mpfr_neg(out, out, MPFR_RNDN);
            }
            *flags = fl | CFT_FLAG_OVERFLOW | CFT_FLAG_INEXACT;
        } else if (e_res >= f->emin) {
            mpfr_set_prec(out, f->p);
            mpfr_set(out, runb, MPFR_RNDN);
            *flags = inexact ? (fl | CFT_FLAG_INEXACT) : fl;
        } else if (!is_rmm) {
            mpfr_exp_t save_emin = mpfr_get_emin();
            mpfr_exp_t save_emax = mpfr_get_emax();
            mpfr_t r;
            int t2;
            mpfr_init2(r, f->p);
            mpfr_set_emin(f->emin - f->p + 2);
            mpfr_set_emax(f->emax + 1);
            t2 = mpfr_strtofr(r, s, &end, 0, rnd);
            t2 = mpfr_check_range(r, t2, rnd);
            t2 = mpfr_subnormalize(r, t2, rnd);
            mpfr_set_emin(save_emin);
            mpfr_set_emax(save_emax);
            mpfr_set_prec(out, f->p);
            mpfr_set(out, r, MPFR_RNDN);
            if (t2 != 0 || inexact)
                fl |= CFT_FLAG_INEXACT | CFT_FLAG_UNDERFLOW;
            *flags = fl;
            mpfr_clear(r);
        } else {
            /* RMM on the fixed subnormal grid, from the p+1 truncation
             * - c5_round_into's block, and its granularity argument
             * holds unchanged because y is a truncation here too. */
            int t1b, up, sgn;
            long grid = f->emin - f->man_w;
            mpz_t nn;
            mpfr_t scaled, frac, half;
            t1b = mpfr_strtofr(y, s, &end, 0, MPFR_RNDZ);
            sgn = mpfr_signbit(y) ? 1 : 0;
            mpz_init(nn);
            mpfr_init2(scaled, f->p + 4);
            mpfr_init2(frac, f->p + 4);
            mpfr_init2(half, 8);
            mpfr_abs(scaled, y, MPFR_RNDN);
            mpfr_mul_2si(scaled, scaled, -grid, MPFR_RNDN);
            mpfr_get_z(nn, scaled, MPFR_RNDZ);
            mpfr_sub_z(frac, scaled, nn, MPFR_RNDN);
            mpfr_set_ui_2exp(half, 1, -1, MPFR_RNDN);
            up = (mpfr_cmp(frac, half) >= 0);
            if (up)
                mpz_add_ui(nn, nn, 1);
            mpfr_set_prec(out, f->p);
            mpfr_set_z_2exp(out, nn, grid, MPFR_RNDN);
            if (sgn)
                mpfr_neg(out, out, MPFR_RNDN);
            if (!mpfr_zero_p(frac) || t1b)
                fl |= CFT_FLAG_INEXACT | CFT_FLAG_UNDERFLOW;
            mpz_clear(nn);
            mpfr_clear(scaled);
            mpfr_clear(frac);
            mpfr_clear(half);
            *flags = fl;
        }
    }
    mpfr_clear(runb);
    mpfr_clear(y);
}

/* Read one sequence through the library, both ways compared. */
static void chars_check_parse(int fj, const char *s, int hexform)
{
    const fdesc *f = &FMTS[fj];
    int mi;
    for (mi = 0; mi < 5; mi++) {
        uint8_t d[32];
        uint32_t gf = 0, wf = 0;
        mpfr_t want;
        cft_status st;
        const char *one = s;
        size_t bad = 0;

        mpfr_init2(want, f->p);
        chars_round_str(f, s, mi, want, &wf);
        memset(d, 0, sizeof d);
        st = hexform
             ? cft_from_hex_char(dev, f->fmt, MODES[mi].cr, &one, d, 1, &bad,
                                 &gf)
             : cft_from_decimal_char(dev, f->fmt, MODES[mi].cr, &one, d, 1,
                                     &bad, &gf);
        /* A refusal is its own thing and gets its own line: "the
         * library would not read a sequence MPFR read" and "it read a
         * different number" want different responses from whoever is
         * looking at the report. */
        if (st != CFT_OK && shown < 16) {
            shown++;
            printf("  REFUSED %s %s %s: %.160s\n", f->name,
                   hexform ? "from_hex" : "from_dec", MODES[mi].name, s);
        }
        c5_judge(hexform ? T_FROM_HEX : T_FROM_DEC, fj,
                 hexform ? "from_hex" : "from_dec", MODES[mi].name, f, NULL,
                 NULL, f, d, want, gf, wf, st, s);
        mpfr_clear(want);
    }
}

/* The library's answer, written into a fresh buffer. */
static char *chars_write(int fj, int mi, const uint8_t *a, size_t digits,
                         int hexform, uint32_t *flags, cft_status *st)
{
    const fdesc *f = &FMTS[fj];
    size_t need = 0;
    char *buf;

    *flags = 0;
    *st = hexform ? cft_to_hex_char(dev, f->fmt, a, NULL, 0, &need)
                  : cft_to_decimal_char(dev, f->fmt, MODES[mi].cr, a, digits,
                                        NULL, 0, &need, flags);
    if (need < 2) {
        *st = *st == CFT_OK ? CFT_ERR_INTERNAL : *st;
        return NULL;
    }
    buf = (char *)malloc(need);
    if (!buf) {
        *st = CFT_ERR_OUT_OF_MEMORY;
        return NULL;
    }
    *st = hexform ? cft_to_hex_char(dev, f->fmt, a, buf, need, &need)
                  : cft_to_decimal_char(dev, f->fmt, MODES[mi].cr, a, digits,
                                        buf, need, &need, flags);
    if (*st != CFT_OK) {
        free(buf);
        return NULL;
    }
    return buf;
}

/* "the sequence denotes exactly this value" - MPFR's verdict, which is
 * the whole content of an exact conversion. */
static void chars_check_exact(int fj, const uint8_t *a, const char *s,
                              const char *what, int ti)
{
    const fdesc *f = &FMTS[fj];
    mpfr_t x, back;
    char *end = NULL;
    int t;

    mpfr_init2(x, f->p);
    mpfr_init2(back, f->p);
    enc_to_mpfr(f, a, x);
    t = mpfr_strtofr(back, s, &end, 0, MPFR_RNDN);
    cases++;
    tally[ti][fj]++;
    if (t != 0 || !mpfr_equal_p(back, x) ||
        (end && *end) || mpfr_signbit(back) != mpfr_signbit(x)) {
        mismatches++;
        if (shown < 16) {
            char ha[65];
            shown++;
            hexdump(a, f->esz, ha);
            printf("  MISMATCH %s %s a=0x%s\n", f->name, what, ha);
            printf("    the library wrote %.*s%s\n", 120, s,
                   strlen(s) > 120 ? "..." : "");
            printf("    mpfr_strtofr reads it back ternary %d, equal %d, "
                   "trailing %d\n", t, mpfr_equal_p(back, x),
                   end && *end ? 1 : 0);
        }
    }
    mpfr_clear(x);
    mpfr_clear(back);
}

/* The library's H-digit sequence against mpfr_get_str's. */
static void chars_check_digits(int fj, int mi, const uint8_t *a, size_t h)
{
    const fdesc *f = &FMTS[fj];
    char *got;
    uint32_t gf = 0;
    cft_status st;
    mpfr_t x;
    mpfr_exp_t e10 = 0;
    char *want;
    char buf[512];
    int is_rmm = (MODES[mi].cr == CFT_RMM);
    size_t n = h + (is_rmm ? 1 : 0);
    int bad = 0;

    if (h < 2 || n + 4 > sizeof buf)
        return;                            /* mpfr_get_str wants n >= 2 */

    got = chars_write(fj, mi, a, h, 0, &gf, &st);
    cases++;
    tally[T_TO_DEC][fj]++;
    if (!got) {
        mismatches++;
        if (shown < 16) {
            shown++;
            printf("  MISMATCH %s to_dec %s: status %s\n", f->name,
                   MODES[mi].name, cft_strerror(st));
        }
        return;
    }

    mpfr_init2(x, f->p);
    enc_to_mpfr(f, a, x);
    want = mpfr_get_str(buf, &e10, 10, n,
                        x, is_rmm ? MPFR_RNDZ : MODES[mi].mr);
    if (!want) {
        free(got);
        mpfr_clear(x);
        return;
    }
    {
        /* mpfr_get_str writes 0.d1..dn * 10^e10 with the sign as a
         * leading '-'; the library writes d1.d2..dn e (e10 - 1). */
        char digits[520];
        int neg = want[0] == '-';
        long exp10;
        size_t i, len;
        char expect[560];

        snprintf(digits, sizeof digits, "%s", want + (neg ? 1 : 0));
        len = strlen(digits);
        exp10 = (long)e10 - 1;
        if (is_rmm && len == n) {
            /* ties-to-away on a decimal grid: up exactly when the
             * dropped digit is 5 or more, no sticky needed */
            int up = digits[n - 1] >= '5';
            digits[n - 1] = '\0';
            len = n - 1;
            if (up) {
                size_t k = len;
                while (k-- > 0) {
                    if (digits[k] != '9') {
                        digits[k]++;
                        break;
                    }
                    digits[k] = '0';
                    if (k == 0) {
                        digits[0] = '1';
                        exp10++;
                    }
                }
            }
        }
        /* Assemble what the library should have written. */
        {
            char body[540];
            size_t w = 0;
            body[w++] = digits[0];
            if (len > 1) {
                body[w++] = '.';
                for (i = 1; i < len && w + 2 < sizeof body; i++)
                    body[w++] = digits[i];
            }
            body[w] = '\0';
            snprintf(expect, sizeof expect, "%s%se%s%ld", neg ? "-" : "",
                     body, exp10 >= 0 ? "+" : "-",
                     exp10 >= 0 ? exp10 : -exp10);
        }
        if (strcmp(expect, got) != 0)
            bad = 1;
        if (bad) {
            char ha[65];
            mismatches++;
            if (shown < 16) {
                shown++;
                hexdump(a, f->esz, ha);
                printf("  MISMATCH %s to_dec %s a=0x%s h=%lu\n", f->name,
                       MODES[mi].name, ha, (unsigned long)h);
                printf("    lib  %s\n    mpfr %s\n", got, expect);
            }
        }
    }
    free(got);
    mpfr_clear(x);
}

/* The exact decimal of the midpoint between an encoding and its
 * successor, built with GMP - the tie only the attribute can decide,
 * and generated by the ORACLE side so it owes the library nothing.
 * Returns 0 when the expansion does not fit the caller's buffer, which
 * is how the extremes of the wide formats are left out. */
static int chars_midpoint(const fdesc *f, const uint8_t *a, char *buf,
                          size_t cap)
{
    uint8_t up[32];
    mpz_t m1, m2, mid, five;
    mpfr_t v1, v2;
    long e1, e2, e, p10;
    int ok = 0;
    cls ca;

    classify(f, a, &ca);
    if (ca.is_nan || ca.is_inf)
        return 0;
    memcpy(up, a, f->esz);
    enc_step(f, up, 1);
    classify(f, up, &ca);
    if (ca.is_nan || ca.is_inf)
        return 0;

    mpfr_init2(v1, f->p);
    mpfr_init2(v2, f->p);
    enc_to_mpfr(f, a, v1);
    enc_to_mpfr(f, up, v2);
    if (mpfr_zero_p(v1) || mpfr_zero_p(v2) || mpfr_sgn(v1) != mpfr_sgn(v2)) {
        mpfr_clear(v1);
        mpfr_clear(v2);
        return 0;
    }
    mpz_init(m1);
    mpz_init(m2);
    mpz_init(mid);
    mpz_init(five);
    e1 = (long)mpfr_get_z_2exp(m1, v1);
    e2 = (long)mpfr_get_z_2exp(m2, v2);
    e = (e1 < e2 ? e1 : e2) - 1;
    mpz_mul_2exp(m1, m1, (unsigned long)(e1 - e));
    mpz_mul_2exp(m2, m2, (unsigned long)(e2 - e));
    mpz_add(mid, m1, m2);
    mpz_tdiv_q_2exp(mid, mid, 1);              /* (m1 + m2) / 2, exact */
    /* The sign is carried separately below - mpfr_get_z_2exp hands
     * back a NEGATIVE significand for a negative value, and letting
     * mpz_get_str write its own '-' as well produced "--..." */
    mpz_abs(mid, mid);

    /* mid * 2^e is mid * 5^-e * 10^e for e < 0, and mid << e for e >= 0 */
    if (e >= 0) {
        mpz_mul_2exp(mid, mid, (unsigned long)e);
        p10 = 0;
    } else {
        mpz_ui_pow_ui(five, 5, (unsigned long)(-e));
        mpz_mul(mid, mid, five);
        p10 = e;
    }
    if (mpz_sizeinbase(mid, 10) + 24 < cap) {
        char *digits = (char *)malloc(mpz_sizeinbase(mid, 10) + 4);
        if (digits) {
            size_t len, keep;
            long exp10;
            mpz_get_str(digits, 10, mid);
            len = strlen(digits);
            exp10 = (long)len - 1 + p10;
            keep = len;
            while (keep > 1 && digits[keep - 1] == '0')
                keep--;
            digits[keep] = '\0';
            if (keep == 1)
                snprintf(buf, cap, "%s%se%s%ld", mpfr_signbit(v1) ? "-" : "",
                         digits, exp10 >= 0 ? "+" : "-",
                         exp10 >= 0 ? exp10 : -exp10);
            else
                snprintf(buf, cap, "%s%c.%se%s%ld",
                         mpfr_signbit(v1) ? "-" : "", digits[0], digits + 1,
                         exp10 >= 0 ? "+" : "-", exp10 >= 0 ? exp10 : -exp10);
            ok = 1;
            free(digits);
        }
    }
    mpz_clear(m1);
    mpz_clear(m2);
    mpz_clear(mid);
    mpz_clear(five);
    mpfr_clear(v1);
    mpfr_clear(v2);
    return ok;
}

static void check_chars(int fj, uint8_t pool[][32], int pn, int nrand)
{
    const fdesc *f = &FMTS[fj];
    size_t h = cft_format_decimal_digits(f->fmt);
    int i, mi, k;

    /* -- writing out ------------------------------------------------ */
    for (i = 0; i < pn; i++) {
        cls ca;
        classify(f, pool[i], &ca);
        if (ca.is_nan || ca.is_inf || ca.is_zero)
            continue;                     /* MPFR keeps no payload; the
                                           * words are the model's */
        for (mi = 0; mi < 5; mi++) {
            chars_check_digits(fj, mi, pool[i], h);
            chars_check_digits(fj, mi, pool[i], h - 1);
            chars_check_digits(fj, mi, pool[i], h + 3);
            chars_check_digits(fj, mi, pool[i], 5);
            chars_check_digits(fj, mi, pool[i], 2);
        }
        /* The exact forms, in both radices, verified by reading them
         * back through MPFR - which is what "exact" means. */
        {
            uint32_t gf = 0;
            cft_status st;
            char *s = chars_write(fj, 0, pool[i], 0, 0, &gf, &st);
            if (s) {
                if (gf == 0)
                    chars_check_exact(fj, pool[i], s, "to_dec exact",
                                      T_TO_DEC);
                else {
                    mismatches++;
                    if (shown++ < 16)
                        printf("  FLAGS %s to_dec exact raised 0x%02x\n",
                               f->name, (unsigned)gf);
                }
                chars_check_parse(fj, s, 0);
                free(s);
            }
            s = chars_write(fj, 0, pool[i], 0, 1, &gf, &st);
            if (s) {
                chars_check_exact(fj, pool[i], s, "to_hex", T_TO_HEX);
                chars_check_parse(fj, s, 1);
                free(s);
            }
        }
    }

    /* -- reading in: sequences this file builds itself --------------- */
    {
        static const char *const fixed[] = {
            "0", "-0", "1", "-1", "0.1", "0.5", "2.5", "1.25",
            "3.14159265358979323846264338327950288419716939937510",
            "2.71828182845904523536028747135266249775724709369995",
            "1e10", "1e-10", "1e100", "1e-100", "9.99999999999999999e2",
            "123456789012345678901234567890e-15",
            "0.000000000000000000000000000000000000001",
            "99999999999999999999999999999999999999", NULL
        };
        for (k = 0; fixed[k]; k++)
            chars_check_parse(fj, fixed[k], 0);
    }
    {
        static const char *const fixedhex[] = {
            "0x0p+0", "-0x0p+0", "0x1p+0", "-0x1p+0", "0X1P+0",
            "0x1.8p+1", "0x.8p+1", "0x8.p-3", "0x1.fffffffffffffp+1023",
            "0xfffffffffffffffffffffffffffffffffp-4",
            "0x1.23456789abcdefp-100", "-0x1.fedcba9876543p+100", NULL
        };
        for (k = 0; fixedhex[k]; k++)
            chars_check_parse(fj, fixedhex[k], 1);
    }

    /* Exponents inside MPFR's own range and well outside every
     * format's, so overflow and underflow are scored by the oracle
     * rather than assumed. */
    for (k = 0; k < 8 * nrand; k++) {
        char s[128];
        int nd = 1 + (int)(rng() % 34), j, pos = 0;
        long ex = (long)(rng() % 200001) - 100000;
        if (rng() & 1)
            s[pos++] = '-';
        for (j = 0; j < nd; j++)
            s[pos++] = (char)('0' + (int)(rng() % 10));
        snprintf(s + pos, sizeof s - (size_t)pos, "e%ld", ex);
        chars_check_parse(fj, s, 0);
    }

    /* Random hexadecimal significands, mostly WIDER than the format
     * holds - which is the only way a hex sequence can need rounding
     * at all, and so the only part of 5.12.3 an oracle can arbitrate
     * beyond "did it read the bits back". */
    for (k = 0; k < 4 * nrand; k++) {
        char s[256];
        int nd = 1 + (int)(rng() % (unsigned)(f->p / 4 + 6)), j, pos = 0;
        long ex = (long)(rng() % (2u * (unsigned)f->emax + 61)) - f->emax - 30;
        if (rng() & 1)
            s[pos++] = '-';
        s[pos++] = '0';
        s[pos++] = 'x';
        for (j = 0; j < nd; j++) {
            s[pos++] = "0123456789abcdef"[rng() % 16];
            if (j == 0 && (rng() & 1))
                s[pos++] = '.';
        }
        snprintf(s + pos, sizeof s - (size_t)pos, "p%+ld", ex);
        chars_check_parse(fj, s, 1);
    }

    /* The exact halfway sequences: the tie the attribute alone
     * decides, built here from GMP and owing the library nothing. */
    for (i = 0; i < pn; i++) {
        char mid[4096];
        if (chars_midpoint(f, pool[i], mid, sizeof mid))
            chars_check_parse(fj, mid, 0);
    }
}

/* ---- 9.6's magnitude forms of minimum and maximum ------------------ *
 *
 * WHICH HALF IS AN ORACLE AND WHICH IS A RESTATEMENT. This matters
 * more here than anywhere else in this file, because the operation is
 * a selection and a careless oracle would be this library's own logic
 * written twice.
 *
 * The ORACLE half is MPFR's, and it is the whole numeric content of
 * 9.6's first two clauses:
 *
 *   * mpfr_cmpabs(av, bv) decides |x| against |y|. MPFR converts the
 *     encodings exactly (enc_to_mpfr) and compares magnitudes in its
 *     own arbitrary-precision arithmetic; nothing in libcft or in the
 *     golden model contributes to that answer, and at fp128/fp256 it
 *     is the only implementation on this machine that can give one.
 *   * mpfr_min / mpfr_max decide the "otherwise" when the magnitudes
 *     are equal. The MPFR manual defines those exactly as 754 defines
 *     minimum and maximum on numbers, signed zeros included: "If op1
 *     and op2 are zeros of different signs, then rop is set to -0
 *     (resp. +0)". So the -0/+0 rule, and the choice between +3 and
 *     -3, come from MPFR rather than from a rule restated here.
 *
 * The RESTATEMENT half is the NaN handling, and it has to be, because
 * MPFR cannot supply it:
 *
 *   * MPFR has no signaling NaN, so "an invalid operation exception is
 *     signaled" (9.6) has no counterpart to compare against.
 *   * mpfr_min implements only the ...Number NaN rule ("if op1 or op2
 *     is NaN, then rop is set to the other value"), which is
 *     minimumNumber's. The plain minimum's rule - "a quiet NaN if
 *     either operand is a NaN" - is the opposite, and MPFR has no
 *     function that does it.
 *   * A NaN has no magnitude, so mpfr_cmpabs on one is meaningless
 *     (MPFR sets erange and returns 0); the NaN cases must be taken
 *     out before the oracle is consulted, which is a decision about
 *     the standard's text and not a measurement.
 *
 * So: every NaN row below is this file reading 9.6 and 6.2, scored
 * against libcft reading the same clauses - two readings, not two
 * oracles - and every numeric row is MPFR's answer. The golden model
 * is the third opinion on both halves and host/tests/
 * minmax_mag_check.py is where that comparison lives.
 *
 * The comparison is a memcmp of ENCODINGS rather than agree()'s value
 * comparison, because 9.6 selects an operand: an implementation that
 * returned a numerically equal but differently encoded result - the
 * wrong one of two NaNs, or +0 where -0 was asked for - would pass a
 * value test and be wrong.
 */

/* Which operand 9.6 selects, and with which flags, for one pair.
 * Writes the expected encoding into `want`. */
static void mm_oracle(const fdesc *f, int fn, const uint8_t *a,
                      const uint8_t *b, uint8_t *want, uint32_t *wf)
{
    const int is_max = (fn == 2 || fn == 3);
    const int is_num = (fn == 1 || fn == 3);
    cls ca, cb;
    mpfr_t av, bv, pick;
    int c;

    classify(f, a, &ca);
    classify(f, b, &cb);
    *wf = (ca.is_snan || cb.is_snan) ? CFT_FLAG_INVALID : 0u;

    /* --- the restatement: 9.6's "otherwise" for a NaN operand --- */
    if (ca.is_nan || cb.is_nan) {
        if (!is_num || (ca.is_nan && cb.is_nan)) {
            /* The canonical quiet NaN this contract delivers: sign
             * clear, every exponent bit set, the quiet bit set, the
             * payload zero. Built from the format's own widths rather
             * than transcribed per format. */
            int k;
            memset(want, 0, f->esz);
            for (k = f->man_w; k < f->man_w + f->exp_w; k++)
                want[k >> 3] |= (uint8_t)(1u << (k & 7));
            want[(f->man_w - 1) >> 3] |=
                (uint8_t)(1u << ((f->man_w - 1) & 7));
        } else {
            memcpy(want, ca.is_nan ? b : a, f->esz);
        }
        return;
    }

    /* --- the oracle: MPFR decides both magnitude and tie --- */
    mpfr_init2(av, f->p);
    mpfr_init2(bv, f->p);
    enc_to_mpfr(f, a, av);
    enc_to_mpfr(f, b, bv);
    c = mpfr_cmpabs(av, bv);
    if (c != 0) {
        memcpy(want, (is_max ? (c > 0) : (c < 0)) ? a : b, f->esz);
    } else {
        /* Equal magnitudes. mpfr_min/mpfr_max ARE 754's minimum and
         * maximum on numbers, so let them choose the value and map it
         * back to the operand that carries it. With equal magnitudes
         * the two operands differ at most in their sign bit, so the
         * sign of MPFR's answer names one of them. */
        mpfr_init2(pick, f->p);
        if (is_max)
            mpfr_max(pick, av, bv, MPFR_RNDN);
        else
            mpfr_min(pick, av, bv, MPFR_RNDN);
        {
            const int neg = mpfr_signbit(pick) != 0;
            if (ca.sign == cb.sign)
                memcpy(want, a, f->esz);   /* identical encodings */
            else
                memcpy(want, (ca.sign == neg) ? a : b, f->esz);
        }
        mpfr_clear(pick);
    }
    mpfr_clear(av);
    mpfr_clear(bv);
}

static cft_status mm_lib(const fdesc *f, int fn, const uint8_t *a,
                         const uint8_t *b, uint8_t *d, uint32_t *fl)
{
    switch (fn) {
    case 0:  return cft_min_mag(dev, f->fmt, a, b, d, 1, fl);
    case 1:  return cft_minnum_mag(dev, f->fmt, a, b, d, 1, fl);
    case 2:  return cft_max_mag(dev, f->fmt, a, b, d, 1, fl);
    default: return cft_maxnum_mag(dev, f->fmt, a, b, d, 1, fl);
    }
}

static const char *const MMN[4] = { "min_mag", "minnum_mag",
                                    "max_mag", "maxnum_mag" };
static const int MM_TALLY[4] = { T_MINMAG, T_MINNUM_MAG,
                                 T_MAXMAG, T_MAXNUM_MAG };

/* One case's verdict. Like c5_judge, but the value test is a memcmp of
 * encodings: 9.6 names an operand, so "numerically equal" is not the
 * question. The mpfr value is built only for the report. */
static void mm_judge(int fj, int fn, const fdesc *f, const uint8_t *a,
                     const uint8_t *b, const uint8_t *got,
                     const uint8_t *want, uint32_t gf, uint32_t wf,
                     cft_status st)
{
    const int vbad = (st != CFT_OK) || memcmp(got, want, f->esz) != 0;
    const int fbad = (gf != wf);
    if (vbad)
        mismatches++;
    if (fbad)
        flag_mismatches++;
    if (vbad || fbad) {
        mpfr_t w;
        mpfr_init2(w, f->p);
        enc_to_mpfr(f, want, w);
        report_c5(MMN[fn], "-", f, a, b, f, got, w, gf, wf, vbad,
                  st != CFT_OK ? "(status!=OK)" : NULL);
        mpfr_clear(w);
    }
    cases++;
    tally[MM_TALLY[fn]][fj]++;
}

static void check_minmax_mag(int fj, uint8_t pool[][32], int pn)
{
    const fdesc *f = &FMTS[fj];
    uint8_t want[32], got[32], aflip[32], bflip[32];
    int fn, i, j, sa, sb;

    for (fn = 0; fn < 4; fn++)
        for (i = 0; i < pn; i++)
            for (j = 0; j < pn; j++)
                /* Both sign combinations of every pair, because the
                 * sign has no vote in 9.6's magnitude clauses and
                 * exactly the deciding vote in its "otherwise" - an
                 * implementation that lets it in early fails only on
                 * the mixed pairs, and only those. */
                for (sa = 0; sa <= 1; sa++)
                    for (sb = 0; sb <= 1; sb++) {
                        const uint8_t *a, *b;
                        uint32_t gf = 0, wf = 0;
                        cft_status st;

                        if (sa) {
                            memcpy(aflip, pool[i], 32);
                            enc_neg(f, aflip);
                            a = aflip;
                        } else {
                            a = pool[i];
                        }
                        if (sb) {
                            memcpy(bflip, pool[j], 32);
                            enc_neg(f, bflip);
                            b = bflip;
                        } else {
                            b = pool[j];
                        }
                        mm_oracle(f, fn, a, b, want, &wf);
                        memset(got, 0, sizeof got);
                        st = mm_lib(f, fn, a, b, got, &gf);
                        mm_judge(fj, fn, f, a, b, got, want, gf, wf, st);
                    }
}

/* Equal magnitudes are where the four differ from a plain magnitude
 * compare, and a random pool reaches them almost never. This aims at
 * them directly: every pool entry against ITSELF and against its own
 * negation, which is every equal-magnitude pair there is. */
static void check_minmax_mag_ties(int fj, uint8_t pool[][32], int pn)
{
    const fdesc *f = &FMTS[fj];
    uint8_t want[32], got[32], neg[32];
    int fn, i, k;

    for (fn = 0; fn < 4; fn++)
        for (i = 0; i < pn; i++) {
            memcpy(neg, pool[i], 32);
            enc_neg(f, neg);
            for (k = 0; k < 4; k++) {
                const uint8_t *a = (k & 1) ? neg : pool[i];
                const uint8_t *b = (k & 2) ? neg : pool[i];
                uint32_t gf = 0, wf = 0;
                cft_status st;
                mm_oracle(f, fn, a, b, want, &wf);
                memset(got, 0, sizeof got);
                st = mm_lib(f, fn, a, b, got, &gf);
                mm_judge(fj, fn, f, a, b, got, want, gf, wf, st);
            }
        }
}

/* ---- the transcendentals ------------------------------------------- *
 *
 * The nine functions of ABI 0.3 and the eleven of ABI 0.4 against
 * MPFR's own, which is the only external oracle that reaches fp128 and
 * fp256 - and, for these operations, the only external oracle at all:
 * the CPU's libm is neither correctly rounded nor reproducible, so
 * there is nothing at fp32/fp64 to calibrate against either. Agreement
 * here is therefore the whole external case for the transcendental
 * set.
 *
 * For phase 2 the version matters and is asserted at the top of this
 * file: mpfr_sinpi, mpfr_cospi, mpfr_tanpi, mpfr_asinpi, mpfr_acospi,
 * mpfr_atanpi and mpfr_atan2pi are MPFR 4.2.0 functions, and this host
 * carries 4.2.2. They are called DIRECTLY. Composing sinPi out of
 * mpfr_sin(pi * x) would be a comparison against a rounded product -
 * it would agree to a few ulps and decide nothing about the bit this
 * library exists to get right - and for a large x it would not even
 * agree to that. mpfr_asin, mpfr_acos, mpfr_atan and mpfr_atan2 exist
 * in every MPFR and need no guard.
 *
 * Phase 3's nine - mpfr_sin, mpfr_cos, mpfr_tan and the six
 * hyperbolics - exist in every MPFR too. What matters for the first
 * three is that MPFR reduces a HUGE argument correctly, against a pi
 * of its own computed to however many bits the exponent demands, so
 * agreement on sin(2^262143) at fp256 is agreement between two
 * independent reductions. It is slow there - a fraction of a second
 * per call - which is why the phase-3 pool samples the exponent
 * range rather than sweeping it.
 *
 * The machinery is oracle()'s, with three differences worth stating:
 *
 *   * MPFR's OWN exponent range can overflow where the format's would
 *     too. exp of the largest fp256 is e^(1.6e78913), which no
 *     exponent field holds. So the unbounded evaluation runs with
 *     MPFR's widest range and its overflow/underflow flags are read:
 *     either one means the true value is past anything this format can
 *     express, and the delivery is the attribute's overflow or
 *     underflow response.
 *
 *   * Signaling NaNs are the documented one-sided help this harness
 *     already gives MPFR elsewhere - MPFR has none - so an sNaN
 *     operand's expectation is the contract's (invalid, canonical
 *     quiet NaN) rather than MPFR's.
 *
 *   * divideByZero is derived from operand classes, as everywhere else
 *     here: log and its friends at zero, log1p at -1, pow of a zero
 *     base to a FINITE negative exponent. pow(+-0, -inf) is the
 *     |x| < 1 row and signals nothing, which is the one row of that
 *     table implementations most often get wrong.
 */

/* One transcendental case through MPFR (mpfr_tfn.h's ieee_tfn_oracle), under
 * MODES[mi]. */
static void t_oracle(const fdesc *f, int fn, int mi, const uint8_t *ba,
                     const uint8_t *bb, long nn, mpfr_t out,
                     uint32_t *flags)
{
    ieee_tfn_oracle(f, fn, MODES[mi].mr, MODES[mi].cr == CFT_RMM, ba, bb,
                    nn, out, flags);
}

static uint32_t tfn_lib(const fdesc *f, int fn, cft_round rnd,
                        const uint8_t *a, const uint8_t *b, long nn,
                        uint8_t *d, cft_status *st)
{
    uint32_t fl = 0;
    int64_t n64 = (int64_t)nn;
    switch (fn) {
    case TF_EXP:   *st = cft_exp(dev, f->fmt, rnd, a, d, 1, &fl); break;
    case TF_EXPM1: *st = cft_expm1(dev, f->fmt, rnd, a, d, 1, &fl); break;
    case TF_EXP2:  *st = cft_exp2(dev, f->fmt, rnd, a, d, 1, &fl); break;
    case TF_LOG:   *st = cft_log(dev, f->fmt, rnd, a, d, 1, &fl); break;
    case TF_LOG1P: *st = cft_log1p(dev, f->fmt, rnd, a, d, 1, &fl); break;
    case TF_LOG2:  *st = cft_log2(dev, f->fmt, rnd, a, d, 1, &fl); break;
    case TF_LOG10: *st = cft_log10(dev, f->fmt, rnd, a, d, 1, &fl); break;
    case TF_POW:   *st = cft_pow(dev, f->fmt, rnd, a, b, d, 1, &fl); break;
    case TF_HYPOT: *st = cft_hypot(dev, f->fmt, rnd, a, b, d, 1, &fl); break;
    case TF_SINPI:  *st = cft_sinpi(dev, f->fmt, rnd, a, d, 1, &fl); break;
    case TF_COSPI:  *st = cft_cospi(dev, f->fmt, rnd, a, d, 1, &fl); break;
    case TF_TANPI:  *st = cft_tanpi(dev, f->fmt, rnd, a, d, 1, &fl); break;
    case TF_ASIN:   *st = cft_asin(dev, f->fmt, rnd, a, d, 1, &fl); break;
    case TF_ACOS:   *st = cft_acos(dev, f->fmt, rnd, a, d, 1, &fl); break;
    case TF_ATAN:   *st = cft_atan(dev, f->fmt, rnd, a, d, 1, &fl); break;
    case TF_ATAN2:  *st = cft_atan2(dev, f->fmt, rnd, a, b, d, 1, &fl);
                    break;
    case TF_ASINPI: *st = cft_asinpi(dev, f->fmt, rnd, a, d, 1, &fl); break;
    case TF_ACOSPI: *st = cft_acospi(dev, f->fmt, rnd, a, d, 1, &fl); break;
    case TF_ATANPI: *st = cft_atanpi(dev, f->fmt, rnd, a, d, 1, &fl); break;
    case TF_ATAN2PI: *st = cft_atan2pi(dev, f->fmt, rnd, a, b, d, 1, &fl);
                    break;
    case TF_SIN:    *st = cft_sin(dev, f->fmt, rnd, a, d, 1, &fl); break;
    case TF_COS:    *st = cft_cos(dev, f->fmt, rnd, a, d, 1, &fl); break;
    case TF_TAN:    *st = cft_tan(dev, f->fmt, rnd, a, d, 1, &fl); break;
    case TF_SINH:   *st = cft_sinh(dev, f->fmt, rnd, a, d, 1, &fl); break;
    case TF_COSH:   *st = cft_cosh(dev, f->fmt, rnd, a, d, 1, &fl); break;
    case TF_TANH:   *st = cft_tanh(dev, f->fmt, rnd, a, d, 1, &fl); break;
    case TF_ASINH:  *st = cft_asinh(dev, f->fmt, rnd, a, d, 1, &fl); break;
    case TF_ACOSH:  *st = cft_acosh(dev, f->fmt, rnd, a, d, 1, &fl); break;
    case TF_ATANH:  *st = cft_atanh(dev, f->fmt, rnd, a, d, 1, &fl); break;
    case TF_EXP2M1: *st = cft_exp2m1(dev, f->fmt, rnd, a, d, 1, &fl); break;
    case TF_EXP10:  *st = cft_exp10(dev, f->fmt, rnd, a, d, 1, &fl); break;
    case TF_EXP10M1:
        *st = cft_exp10m1(dev, f->fmt, rnd, a, d, 1, &fl);
        break;
    case TF_LOG2P1: *st = cft_log2p1(dev, f->fmt, rnd, a, d, 1, &fl); break;
    case TF_LOG10P1:
        *st = cft_log10p1(dev, f->fmt, rnd, a, d, 1, &fl);
        break;
    case TF_RSQRT:  *st = cft_rsqrt(dev, f->fmt, rnd, a, d, 1, &fl); break;
    case TF_POWN:
        *st = cft_pown(dev, f->fmt, rnd, a, &n64, d, 1, &fl);
        break;
    case TF_POWR:
        *st = cft_powr(dev, f->fmt, rnd, a, b, d, 1, &fl);
        break;
    case TF_COMPOUND:
        *st = cft_compound(dev, f->fmt, rnd, a, &n64, d, 1, &fl);
        break;
    default:
        *st = cft_rootn(dev, f->fmt, rnd, a, &n64, d, 1, &fl);
        break;
    }
    return fl;
}

/* ---- subsets and the case dump (audit of 2026-11-02) --------------- *
 *
 * Three environment variables, none of which touches a default run:
 *
 *   CFT_MPFR_PHASES   a comma list of phase names - arith, clause5,
 *                     transcend, trig, radian, table91, extras, reduce,
 *                     convert, formatof - to run those and no others;
 *   CFT_MPFR_FORMATS  a comma list of fp32, fp64, fp128, fp256;
 *   CFT_MPFR_DUMP_CASES  any non-empty value: print every case the
 *                     transcendental phases would ask (under the first
 *                     attribute only - the other four ask the same
 *                     operands), check nothing, and run no other phase.
 *
 * Unset - or empty, for all three - env_lists answers yes to everything
 * and the run is the one it always was. A subset skips the phases
 * before it, so the random operands it draws are not the ones a full
 * run draws; the directed ones are, and are the whole point of a
 * subset.
 *
 * The dump is how the pools are audited rather than read: tools of the
 * audit compare it, case by case, with the operands the vector generator
 * and the golden model's thresholds direct at each function. A dump line is
 *
 *   C <format> <function> <pass> <i> <j> <d> <a> <b> <n> [<family>]
 *
 * with the pool pass (x the exponential pool, t the trigonometric, h
 * the third, e the extras below), the indices of the two operands in it
 * (in the extras, i is the entry's place in its list and j is 0), d = 1
 * when both are directed operands rather than random ones (the randoms
 * of a dump are not a full run's), the operands in hex, and - for the
 * three that read one - the integer; "-" where an operand is not read.
 * The extras' lines end with the family the entry belongs to. */
static int dump_cases;

static int env_lists(const char *var, const char *name)
{
    const char *v = getenv(var);
    size_t n = strlen(name);

    if (!v || !*v)
        return 1;
    while (*v) {
        const char *e = strchr(v, ',');
        size_t len = e ? (size_t)(e - v) : strlen(v);
        if (len == n && !strncmp(v, name, n))
            return 1;
        if (!e)
            break;
        v = e + 1;
    }
    return 0;
}

static int phase_on(const char *name)
{
    if (dump_cases)
        return !strcmp(name, "transcend") || !strcmp(name, "trig") ||
               !strcmp(name, "radian") || !strcmp(name, "table91") ||
               !strcmp(name, "extras");
    return env_lists("CFT_MPFR_PHASES", name);
}

static int format_on(const fdesc *f)
{
    return env_lists("CFT_MPFR_FORMATS", f->name);
}

/* Operands aimed at the transcendentals specifically, in their own
 * larger pool: the families that matter here - the exact cases, the
 * overflow and underflow thresholds, a base one ulp from 1 - are not
 * the families that matter for an FMA, and the arithmetic phase's
 * 64-operand pool is sized for a cross product this phase does not
 * take. */
/* enc_from_val returns 1 on SUCCESS. build_tpool tested it against 0
 * from the day it was written, so every directed operand it meant to
 * add - the exp2 integers, the log2 powers of two, the log10 powers of
 * ten, the neighbours of 1, the arguments below 2^-(p+3) - was
 * discarded and a zeroed encoding kept in its place. The transcendental
 * phase of this campaign therefore ran on build_pool's specials plus
 * randoms until 2026-09-03. Found while adding the trigonometric pool,
 * whose entries came out at 42 where 192 were asked for. */
#define TPOOL_MAX 208
#define TRIGPOOL_MAX 192
#define P3POOL_MAX 224

/* Which entries of each pool are random draws - the case dump marks the
 * rest as directed. The builders set them; nothing else reads them. */
static uint8_t isrand_x[TPOOL_MAX], isrand_t[TRIGPOOL_MAX],
               isrand_h[P3POOL_MAX];

static int build_tpool(const fdesc *f, uint8_t pool[][32], int randoms)
{
    int n = build_pool(f, pool, randoms);
    long ks[12];
    int nk = 0, k;

    memset(isrand_x, 0, sizeof isrand_x);
    for (k = 18; k < n; k++)
        isrand_x[k] = 1;                /* build_pool's own randoms */
    ks[nk++] = 1; ks[nk++] = 2; ks[nk++] = 3; ks[nk++] = 10;
    ks[nk++] = 17; ks[nk++] = f->p; ks[nk++] = f->emax;
    ks[nk++] = f->emax + 1; ks[nk++] = f->emin; ks[nk++] = -1;
    ks[nk++] = -3; ks[nk++] = f->emin - f->man_w;
    for (k = 0; k < nk && n < TPOOL_MAX - 8; k++) {
        uint64_t mag = (uint64_t)(ks[k] < 0 ? -ks[k] : ks[k]);
        /* the integer itself: an exp2 exact case, and a pow exponent */
        if (enc_from_val(f, 0, mag, 0, pool[n])) {
            if (ks[k] < 0)
                enc_neg(f, pool[n]);
            n++;
        }
        /* 2^k: log2's exact cases, with a neighbour above and below */
        if (enc_from_val(f, 0, 1, ks[k], pool[n])) {
            n++;
            memcpy(pool[n], pool[n - 1], 32); enc_step(f, pool[n], 1); n++;
            memcpy(pool[n], pool[n - 2], 32); enc_step(f, pool[n], 0); n++;
        }
    }
    /* powers of ten: log10's exact cases, until the odd part 5^k
     * outruns the significand */
    {
        uint64_t five = 1;
        long e = 0;
        while (n < TPOOL_MAX - 4 && five <= ((uint64_t)1 << 60)) {
            if (!enc_from_val(f, 0, five, e, pool[n]))
                break;
            n++;
            memcpy(pool[n], pool[n - 1], 32); enc_step(f, pool[n], 1); n++;
            five *= 5;
            e++;
        }
    }
    /* one ulp either side of 1 and of -1, and arguments below
     * 2^-(p+3), where the answer is decided by a SIDE and not by any
     * working precision */
    if (n < TPOOL_MAX - 10 && enc_from_val(f, 0, 1, 0, pool[n])) {
        n++;
        memcpy(pool[n], pool[n - 1], 32); enc_step(f, pool[n], 1); n++;
        memcpy(pool[n], pool[n - 2], 32); enc_step(f, pool[n], 0); n++;
        memcpy(pool[n], pool[n - 3], 32); enc_neg(f, pool[n]); n++;
        memcpy(pool[n], pool[n - 1], 32); enc_step(f, pool[n], 1); n++;
    }
    for (k = 2; k < 12 && n < TPOOL_MAX - 4; k++) {
        if (enc_from_val(f, 0, 1, -(long)f->p - k, pool[n])) {
            n++;
            memcpy(pool[n], pool[n - 1], 32); enc_neg(f, pool[n]); n++;
        }
    }
    /* top up with randoms, which cost nothing and occasionally find
     * something the directed families did not think of */
    while (n < TPOOL_MAX) {
        rand_enc(f, pool[n]);
        isrand_x[n] = 1;
        n++;
    }
    return n;
}

/* The trigonometric pool. The families that catch sinPi are not the
 * families that catch exp: half-integers and quarter-integers (where
 * sinPi and tanPi are exact), integers (where sinPi's zero takes the
 * sign of the ARGUMENT), the top of the range (where every value is an
 * even integer), the two sides of 1 (where asin's domain ends), and
 * every neighbour threshold this set has. */
static int build_trigpool(const fdesc *f, uint8_t pool[][32],
                          uint8_t const base[][32], int nbase, int randoms)
{
    int n = 0, k;
    static const long HALVES[] = { 1, 3, 5, 7, 9, 17, 33 };
    static const long QUARTS[] = { 1, 3, 5, 7, 9, 11, 13 };
    static const long INTS[]   = { 1, 2, 3, 4, 5, 8, 17 };

    memset(pool, 0, sizeof(uint8_t) * TRIGPOOL_MAX * 32);
    /* every special build_pool already constructs - both zeros, both
     * infinities, both NaNs, the subnormal and normal extremes - and
     * then the families this set needs and that one does not */
    for (k = 0; k < nbase && k < 18 && n < TRIGPOOL_MAX; k++)
        memcpy(pool[n++], base[k], 32);

    for (k = 0; k < (int)(sizeof HALVES / sizeof HALVES[0]) &&
                n < TRIGPOOL_MAX - 12; k++) {
        if (enc_from_val(f, 0, (uint64_t)HALVES[k], -1, pool[n])) {
            n++;
            memcpy(pool[n], pool[n - 1], 32); enc_step(f, pool[n], 1); n++;
            memcpy(pool[n], pool[n - 2], 32); enc_step(f, pool[n], 0); n++;
            memcpy(pool[n], pool[n - 3], 32); enc_neg(f, pool[n]); n++;
        }
    }
    for (k = 0; k < (int)(sizeof QUARTS / sizeof QUARTS[0]) &&
                n < TRIGPOOL_MAX - 12; k++) {
        if (enc_from_val(f, 0, (uint64_t)QUARTS[k], -2, pool[n])) {
            n++;
            memcpy(pool[n], pool[n - 1], 32); enc_step(f, pool[n], 1); n++;
            memcpy(pool[n], pool[n - 2], 32); enc_neg(f, pool[n]); n++;
        }
    }
    for (k = 0; k < (int)(sizeof INTS / sizeof INTS[0]) &&
                n < TRIGPOOL_MAX - 12; k++) {
        if (enc_from_val(f, 0, (uint64_t)INTS[k], 0, pool[n])) {
            n++;
            memcpy(pool[n], pool[n - 1], 32); enc_step(f, pool[n], 1); n++;
            memcpy(pool[n], pool[n - 2], 32); enc_step(f, pool[n], 0); n++;
            memcpy(pool[n], pool[n - 3], 32); enc_neg(f, pool[n]); n++;
        }
    }
    /* the top of the range: every value there is an even integer */
    {
        long tops[4];
        tops[0] = f->p; tops[1] = f->p + 1; tops[2] = 2 * f->p;
        tops[3] = f->emax;
        for (k = 0; k < 4 && n < TRIGPOOL_MAX - 4; k++)
            if (enc_from_val(f, 0, 1, tops[k], pool[n])) {
                n++;
                memcpy(pool[n], pool[n - 1], 32); enc_step(f, pool[n], 0);
                n++;
            }
    }
    /* every neighbour threshold, one step either side */
    {
        long ks[9];
        ks[0] = f->p / 2; ks[1] = f->p / 2 + 1; ks[2] = f->p / 2 + 2;
        ks[3] = f->p; ks[4] = f->p + 1; ks[5] = f->p + 2;
        ks[6] = f->p + 3; ks[7] = 2 * f->p; ks[8] = 4 * f->p;
        for (k = 0; k < 9 && n < TRIGPOOL_MAX - 6; k++) {
            if (enc_from_val(f, 0, 1, -ks[k], pool[n])) {
                n++;
                memcpy(pool[n], pool[n - 1], 32); enc_neg(f, pool[n]); n++;
            }
            if (enc_from_val(f, 0, 3, -ks[k] - 1, pool[n]))
                n++;
        }
    }
    /* one ulp either side of +-1, where asin's domain ends */
    if (n < TRIGPOOL_MAX - 6 && enc_from_val(f, 0, 1, 0, pool[n])) {
        n++;
        memcpy(pool[n], pool[n - 1], 32); enc_step(f, pool[n], 1); n++;
        memcpy(pool[n], pool[n - 2], 32); enc_step(f, pool[n], 0); n++;
        memcpy(pool[n], pool[n - 3], 32); enc_neg(f, pool[n]); n++;
        memcpy(pool[n], pool[n - 1], 32); enc_step(f, pool[n], 1); n++;
        memcpy(pool[n], pool[n - 2], 32); enc_step(f, pool[n], 0); n++;
    }
    memset(isrand_t, 0, sizeof isrand_t);
    while (n < TRIGPOOL_MAX && randoms-- > 0) {
        rand_enc(f, pool[n]);
        isrand_t[n] = 1;
        n++;
    }
    return n;
}

/* An mpfr value already rounded into the format, as an encoding.
 * Normal values only, which is all the phase-3 pool asks of it: the
 * significand is exactly p bits, the exponent is in the normal range,
 * and the fields are assembled with mpz so the wide formats need no
 * 64-bit detour. */
static int mpfr_to_enc(const fdesc *f, const mpfr_t v, uint8_t *b)
{
    mpz_t z, enc;
    mpfr_exp_t e2;
    long E;
    int sign = mpfr_signbit(v) ? 1 : 0;

    if (!mpfr_regular_p(v))
        return 0;
    mpz_init(z);
    mpz_init(enc);
    e2 = mpfr_get_z_2exp(z, v);                 /* v = z * 2^e2 */
    mpz_abs(z, z);
    if (mpz_sizeinbase(z, 2) != (size_t)f->p) {
        mpz_clear(z); mpz_clear(enc);
        return 0;
    }
    E = (long)e2 + f->p - 1;                    /* the unbiased exponent */
    if (E < f->emin || E > f->emax) {
        mpz_clear(z); mpz_clear(enc);
        return 0;
    }
    mpz_clrbit(z, (mp_bitcnt_t)f->man_w);       /* the hidden bit */
    mpz_set_si(enc, E + f->emax);
    mpz_mul_2exp(enc, enc, (mp_bitcnt_t)f->man_w);
    mpz_add(enc, enc, z);
    if (sign)
        mpz_setbit(enc, (mp_bitcnt_t)(f->exp_w + f->man_w));
    memset(b, 0, 32);
    mpz_export(b, NULL, -1, 1, 0, 0, enc);
    mpz_clear(z);
    mpz_clear(enc);
    return 1;
}

/* The phase-3 pool: what the reduction against pi and the hyperbolics'
 * domain edges need, which neither pool above has. Nothing in it is a
 * typed "known hard case". The arguments nearest a multiple of pi/2 are
 * built here from MPFR's own pi, rounded into the format, with a grid
 * neighbour either side; the sinh/cosh overflow edge from MPFR's ln 2
 * the same way. So the pool is derived at run time from the oracle
 * that judges it, and a wrong constant anywhere would show up as a
 * disagreement rather than as a pool that quietly tested nothing. */
static int build_p3pool(const fdesc *f, uint8_t pool[][32],
                        uint8_t const base[][32], int nbase, int randoms)
{
    int n = 0, k;
    static const long KS[] = { 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13,
                               100, 355, 1000, 12345, 1000000 };
    mpfr_t pi, l2, v, t;

    memset(pool, 0, sizeof(uint8_t) * P3POOL_MAX * 32);
    for (k = 0; k < nbase && k < 18 && n < P3POOL_MAX; k++)
        memcpy(pool[n++], base[k], 32);

    /* powers of two across the exponent range, both signs: the
     * window's START is the argument's exponent, and a power of two is
     * its cleanest probe. The wide formats are sampled - MPFR's own
     * reduction of 2^262143 is the slow half of this campaign. */
    {
        long es[20];
        int ne = 0;
        es[ne++] = f->emin - f->man_w; es[ne++] = f->emin;
        es[ne++] = -f->p; es[ne++] = -f->p / 2; es[ne++] = -2;
        es[ne++] = -1; es[ne++] = 0; es[ne++] = 1; es[ne++] = 2;
        es[ne++] = 3; es[ne++] = 5; es[ne++] = 10; es[ne++] = 20;
        es[ne++] = f->p; es[ne++] = 2 * f->p; es[ne++] = 100;
        es[ne++] = f->emax / 4; es[ne++] = f->emax / 2;
        es[ne++] = f->emax - 1; es[ne++] = f->emax;
        for (k = 0; k < ne && n < P3POOL_MAX - 4; k++)
            if (enc_from_val(f, 0, 1, es[k], pool[n])) {
                n++;
                memcpy(pool[n], pool[n - 1], 32); enc_neg(f, pool[n]); n++;
            }
    }

    mpfr_init2(pi, (mpfr_prec_t)f->p + 64);
    mpfr_init2(l2, (mpfr_prec_t)f->p + 64);
    mpfr_init2(t, (mpfr_prec_t)f->p + 64);
    mpfr_init2(v, f->p);
    mpfr_const_pi(pi, MPFR_RNDN);
    mpfr_const_log2(l2, MPFR_RNDN);

    /* the representable numbers nearest k*pi/2, from MPFR's pi rounded
     * into the format, each with a grid neighbour either side and its
     * negative: where the reduction cancels and its window widens */
    for (k = 0; k < (int)(sizeof KS / sizeof KS[0]) &&
                n < P3POOL_MAX - 8; k++) {
        mpfr_mul_si(t, pi, KS[k], MPFR_RNDN);
        mpfr_div_2ui(t, t, 1, MPFR_RNDN);
        mpfr_set(v, t, MPFR_RNDN);
        if (mpfr_to_enc(f, v, pool[n])) {
            n++;
            memcpy(pool[n], pool[n - 1], 32); enc_step(f, pool[n], 1); n++;
            memcpy(pool[n], pool[n - 2], 32); enc_step(f, pool[n], 0); n++;
            memcpy(pool[n], pool[n - 3], 32); enc_neg(f, pool[n]); n++;
        }
    }

    /* the sinh/cosh overflow edge: n*ln2 for n = emax, emax+1, emax+2,
     * walked two ulps either way, so the screen fires in exactly the
     * right place and the enclosure decides the rest */
    {
        long ns[3];
        ns[0] = f->emax; ns[1] = f->emax + 1; ns[2] = f->emax + 2;
        for (k = 0; k < 3 && n < P3POOL_MAX - 12; k++) {
            mpfr_mul_si(t, l2, ns[k], MPFR_RNDN);
            mpfr_set(v, t, MPFR_RNDN);
            if (mpfr_to_enc(f, v, pool[n])) {
                uint8_t c[32];
                memcpy(c, pool[n], 32);
                n++;
                memcpy(pool[n], c, 32); enc_step(f, pool[n], 1); n++;
                memcpy(pool[n], pool[n - 1], 32); enc_step(f, pool[n], 1); n++;
                memcpy(pool[n], c, 32); enc_step(f, pool[n], 0); n++;
                memcpy(pool[n], pool[n - 1], 32); enc_step(f, pool[n], 0); n++;
                memcpy(pool[n], c, 32); enc_neg(f, pool[n]); n++;
            }
        }
    }
    mpfr_clear(pi); mpfr_clear(l2); mpfr_clear(t); mpfr_clear(v);

    /* where tanh stops being separable from 1: 2^bitlen(p+2), straddled */
    {
        int bl = 0, vv = f->p + 2;
        while (vv) { bl++; vv >>= 1; }
        for (k = bl - 1; k <= bl + 1 && n < P3POOL_MAX - 6; k++)
            if (enc_from_val(f, 0, 1, k, pool[n])) {
                n++;
                memcpy(pool[n], pool[n - 1], 32); enc_step(f, pool[n], 1); n++;
                memcpy(pool[n], pool[n - 2], 32); enc_step(f, pool[n], 0); n++;
            }
    }
    /* one ulp either side of +-1: acosh's domain edge and atanh's pole */
    if (n < P3POOL_MAX - 6 && enc_from_val(f, 0, 1, 0, pool[n])) {
        n++;
        memcpy(pool[n], pool[n - 1], 32); enc_step(f, pool[n], 1); n++;
        memcpy(pool[n], pool[n - 2], 32); enc_step(f, pool[n], 0); n++;
        memcpy(pool[n], pool[n - 3], 32); enc_neg(f, pool[n]); n++;
        memcpy(pool[n], pool[n - 1], 32); enc_step(f, pool[n], 1); n++;
        memcpy(pool[n], pool[n - 2], 32); enc_step(f, pool[n], 0); n++;
    }
    /* every tiny threshold in the family, straddled */
    {
        long ks[8];
        ks[0] = f->p / 2 - 1; ks[1] = f->p / 2; ks[2] = f->p / 2 + 1;
        ks[3] = f->p / 2 + 2; ks[4] = f->p; ks[5] = f->p + 2;
        ks[6] = 2 * f->p; ks[7] = 4 * f->p;
        for (k = 0; k < 8 && n < P3POOL_MAX - 4; k++) {
            if (enc_from_val(f, 0, 1, -ks[k], pool[n])) {
                n++;
                memcpy(pool[n], pool[n - 1], 32); enc_neg(f, pool[n]); n++;
            }
            if (enc_from_val(f, 0, 3, -ks[k] - 1, pool[n]))
                n++;
        }
    }
    memset(isrand_h, 0, sizeof isrand_h);
    while (n < P3POOL_MAX && randoms-- > 0) {
        rand_enc(f, pool[n]);
        isrand_h[n] = 1;
        n++;
    }
    return n;
}

/* The integer exponents pown, compound and rootn are tried against.
 * Both signs, both parities, a value past p+1 (where the exact-case
 * test gives up), and the ends of the LONG range - which is 32 bits on
 * this host, and is MPFR's own type for these operands. The whole int64
 * range is covered against the model in host/tests/transcend_check.py;
 * what is checked here is agreement with MPFR over what MPFR can be
 * asked. */
static const long TFN_NS[] = {
    0, 1, -1, 2, -2, 3, -3, 5, -5, 17, -17, 120, -120,
    2147483647L, -2147483647L
};
#define TFN_NS_COUNT ((int)(sizeof TFN_NS / sizeof TFN_NS[0]))

/* One line of the case dump (see the block above build_tpool). */
static void dump_case(const fdesc *f, int fn, char pass,
                      const uint8_t *isrand, int i, int j, int nargs,
                      int hasn, const uint8_t *a, const uint8_t *b, long nn)
{
    char ha[70], hb[70];
    int directed = !isrand[i] && (nargs == 2 ? !isrand[j] : 1);

    hexdump(a, f->esz, ha);
    if (nargs == 2)
        hexdump(b, f->esz, hb);
    else
        strcpy(hb, "-");
    printf("C %s %s %c %d %d %d %s %s ", f->name, TFN_NAME[fn], pass, i,
           nargs == 2 ? j : 0, directed, ha, hb);
    if (hasn)
        printf("%ld\n", nn);
    else
        printf("-\n");
}

static void check_transcend(int fj, uint8_t pool[][32], int pn,
                            uint8_t tpool[][32], int tn,
                            uint8_t hpool[][32], int hn, int first,
                            int last)
{
    const fdesc *f = &FMTS[fj];
    int fn, mi, i, j;

    for (fn = first; fn < last; fn++) {
        int nargs = TFN_NARGS[fn];
        uint64_t esc_before = cft_tr_escalations;
        /* Unary: every operand. Binary: every operand against a strided
         * eighth of the pool, so the pair count stays linear - the full
         * cross product of two hundred operands times five attributes
         * times two functions is not a sharper test, only a longer
         * one. */
        uint8_t (*P)[32] = fn >= TF_EXP2M1 ? tpool
                         : fn >= TF_SIN ? hpool
                         : fn >= TF_SINPI ? tpool : pool;
        int np = fn >= TF_EXP2M1 ? tn
               : fn >= TF_SIN ? hn : fn >= TF_SINPI ? tn : pn;
        int hasn = TFN_HASINT[fn];
        int jstep = nargs == 2 ? (np / 8 > 0 ? np / 8 : 1) : 1;
        int nstep = hasn ? 3 : 1;
        for (mi = 0; mi < 5; mi++) {
            for (i = 0; i < np; i++) {
                int jmax = nargs == 2 ? np : 1;
                int k;
                /* The integer operand is strided the same way a second
                 * encoding is: every n against every operand times five
                 * attributes would be a longer campaign rather than a
                 * sharper one, and the rows that turn on n's sign and
                 * parity are all inside the first few. */
                for (k = hasn ? i % nstep : 0;
                     k < (hasn ? TFN_NS_COUNT : 1); k += nstep) {
                    long nn = hasn ? TFN_NS[k] : 0;
                    for (j = (nargs == 2 ? i % jstep : 0); j < jmax;
                         j += jstep) {
                        const uint8_t *a = P[i];
                        const uint8_t *b = P[j];
                        uint8_t d[32];
                        uint32_t gf, wf = 0;
                        cft_status st = CFT_OK;
                        char extra[48];
                        mpfr_t want;

                        if (dump_cases) {
                            if (mi == 0)
                                dump_case(f, fn,
                                          P == pool ? 'x' : P == hpool ? 'h'
                                                                       : 't',
                                          P == pool ? isrand_x
                                          : P == hpool ? isrand_h : isrand_t,
                                          i, j, nargs, hasn, a, b, nn);
                            continue;
                        }
                        mpfr_init2(want, f->p);
                        t_oracle(f, fn, mi, a, b, nn, want, &wf);
                        memset(d, 0, sizeof d);
                        gf = tfn_lib(f, fn, MODES[mi].cr, a, b, nn, d, &st);
                        if (hasn)
                            snprintf(extra, sizeof extra, "n=%ld", nn);
                        c5_judge(T_EXP + fn, fj, TFN_NAME[fn],
                                 MODES[mi].name, f, a,
                                 nargs == 2 ? b : NULL, f, d, want, gf, wf,
                                 st, hasn ? extra : NULL);
                        mpfr_clear(want);
                    }
                }
            }
        }
        /* Which function escalated, and how often - a total at the
         * end would say that something did without saying what. */
        if (cft_tr_escalations != esc_before)
            printf("  %s %s: %llu Ziv escalation(s), deepest working "
                   "precision so far %llu bits\n", f->name, TFN_NAME[fn],
                   (unsigned long long)(cft_tr_escalations - esc_before),
                   (unsigned long long)cft_tr_max_prec);
    }
}

/* ---- the extras: what the audit of 2026-11-02 found missing -------- *
 *
 * Issue 1 found that the ten of table 9.1 had never been asked their own
 * exact cases, because they ran on the wrong pool. The audit that
 * followed asked the same question of all thirty-nine functions: for
 * each, does the pool it runs on hold the operands its hard cases live
 * in? It compared the pools (the dump above) with the operands
 * python/cft_golden/vectors.py directs at each function, line by line
 * of the generator; with the branches of python/cft_golden/transcend.py
 * that a case reaches (sys.monitoring, first hit per line); with the
 * thresholds written into those branches, each straddled; and with
 * IEEE 754-2019 9.2's special rows. docs/TRANSCENDENTALS.md carries the
 * table and VALIDATION.md the entry. This block is what it found.
 *
 * It ADDS. The three pools above are unchanged, down to the random
 * draws and their sizes, but for the first eighteen entries of the
 * trigonometric and third pools at fp32, fp64 and fp128 (see the loop in
 * main), so every other case the oracle asked before it asks now; these
 * are the cases it asks besides, in a phase of their own that draws no
 * random number. A candidate the function's pool already holds is
 * skipped, and so is a pair that the pool's strided pairing already
 * asks, so the counts are of what is new. Every entry belongs to a
 * family, named where it is added, and the end of the run counts each
 * family's members and cases per format.
 *
 * Eight things the pools lacked, in the order they matter:
 *
 *   * the specials of the FORMAT. build_trigpool and build_p3pool were
 *     handed fp256's eighteen for every format (main's loop hands them
 *     the format's own now), so at fp32, fp64 and fp128 the twenty
 *     functions of those two pools were never asked -0, an infinity, a
 *     NaN of the usual pattern, the largest subnormal or the largest
 *     normal - and the exp and log pool lacked the negative extremes
 *     and the payload NaNs, which the extras still ask;
 *   * the pairs of specials of every binary function, which a strided
 *     pairing reaches only on its diagonal, and 9.2.1's rows live
 *     off it;
 *   * the overflow and underflow edges of the exponentials, hyperbolics
 *     and powers: n ln 2 and n log10 2 walked two ulps either way, the
 *     integer edges of exp2 (its tie at emin - p included), and for
 *     pow and its kin the exponent that takes a base to 2^emax;
 *   * every threshold of the golden model's neighbour rules, straddled:
 *     the last operand on each side and the first;
 *   * the exact cases the pools never reached: hypot's Pythagorean
 *     pairs (and the ones whose exact result overflows), pow's perfect
 *     powers under a dyadic exponent, log10p1 at 10^k - 1, log10 and
 *     log10p1 at the powers of ten past 10^25, rootn at its perfect
 *     powers, and the powers of two and ten where log2p1 and log10p1
 *     change rule;
 *   * the integer exponents the model's exact tables end on: p - 1 to
 *     p + 2, and the n at which M^n leaves p + 1 bits;
 *   * the families the vector generator directs at a function and its
 *     pool does not hold: integers, halves, quarters and eighths with
 *     their neighbours, 2^k - 1, the top of the range, every power of
 *     two at the narrow formats and a sampled sweep at the wide ones,
 *     and the reduction's hardest operands for sin, cos and tan (the
 *     representable numbers nearest a multiple of pi/2, found here from
 *     MPFR's own pi);
 *   * the pairs of the vector generator: pow's integer, dyadic,
 *     near-1 and cancelling exponents, hypot's triples, atan2's axes
 *     and diagonals and near-axis pairs, and the (operand, n) pairs of
 *     pown, compound and rootn.
 *
 * What it does NOT add is listed in docs/TRANSCENDENTALS.md: an n beyond
 * the host's long (MPFR's operand type), the arguments hardest to round
 * for exp, log and pow (in no pool and in no vector), and the pairs that
 * the strided pairing skips and no family names.
 */

#define XCAP 8192

typedef struct {
    uint8_t a[XCAP][32];
    uint8_t b[XCAP][32];
    long n[XCAP];
    uint8_t fam[XCAP];
    uint8_t ran[XCAP];
    uint8_t fmask[XCAP];             /* which of pown, compound, rootn: 1, 2, 4 */
    int cnt;
} xlist;

static xlist XL;
static uint8_t xmask = 7;            /* the mask xadd gives the entries it adds */
static const fdesc *xf;                  /* the format being built for */

#define XFMAX 112
static const char *xfam_name[XFMAX];
static int xfam_n;
static uint64_t xfam_cases[XFMAX][4], xfam_mem[XFMAX][4];
static uint64_t xfam_intended[XFMAX][4], xfam_held[XFMAX][4];
static int xcur_fj;                  /* the format being built, as an index */

static int xfam(const char *name)
{
    int i;
    for (i = 0; i < xfam_n; i++)
        if (!strcmp(xfam_name[i], name))
            return i;
    if (xfam_n >= XFMAX) {
        fprintf(stderr, "extras: too many families\n");
        exit(3);
    }
    xfam_name[xfam_n] = name;
    return xfam_n++;
}

/* Add a candidate once. a is read as a floating encoding, b likewise
 * when given, n as the integer operand. */
static void xadd(const char *fam, const uint8_t *a, const uint8_t *b,
                 long n)
{
    int i;
    for (i = 0; i < XL.cnt; i++)
        if (XL.n[i] == n && !memcmp(XL.a[i], a, xf->esz) &&
            (!b || !memcmp(XL.b[i], b, xf->esz)))
            return;
    if (XL.cnt >= XCAP) {
        fprintf(stderr, "extras: list full\n");
        exit(3);
    }
    memset(XL.a[XL.cnt], 0, 32);
    memcpy(XL.a[XL.cnt], a, xf->esz);
    memset(XL.b[XL.cnt], 0, 32);
    if (b)
        memcpy(XL.b[XL.cnt], b, xf->esz);
    XL.n[XL.cnt] = n;
    XL.fam[XL.cnt] = (uint8_t)xfam(fam);
    XL.ran[XL.cnt] = 0;
    XL.fmask[XL.cnt] = xmask;
    xfam_intended[XL.fam[XL.cnt]][xcur_fj]++;
    XL.cnt++;
}

/* (-1)^sg m 2^e2 - sg 2 for both signs - with nb encoding steps either
 * side of it. A value the format cannot hold exactly is skipped. */
static void xval(const char *fam, int sg, uint64_t m, long e2, int nb)
{
    uint8_t t[32], u[32];
    int s, k, q;

    for (s = 0; s < 2; s++) {
        if (sg != 2 && sg != s)
            continue;
        if (!enc_from_val(xf, s, m, e2, t))
            return;
        xadd(fam, t, NULL, 0);
        for (k = 1; k <= nb; k++) {
            memcpy(u, t, 32);
            for (q = 0; q < k; q++)
                enc_step(xf, u, 1);
            xadd(fam, u, NULL, 0);
            memcpy(u, t, 32);
            for (q = 0; q < k; q++)
                enc_step(xf, u, 0);
            xadd(fam, u, NULL, 0);
        }
    }
}

/* The same for a significand wider than 64 bits. */
static int enc_from_mpz(const fdesc *f, int sg, const mpz_t m, long e2,
                        uint8_t *b)
{
    mpfr_t v, r;
    int ok = 0;
    size_t bits = mpz_sizeinbase(m, 2);

    mpfr_init2(v, (mpfr_prec_t)(bits > (size_t)f->p ? bits : (size_t)f->p));
    mpfr_init2(r, f->p);
    mpfr_set_z_2exp(v, m, e2, MPFR_RNDN);        /* v holds every bit */
    if (sg)
        mpfr_neg(v, v, MPFR_RNDN);
    if (mpfr_set(r, v, MPFR_RNDN) == 0)          /* exactly p bits? */
        ok = mpfr_to_enc(f, r, b);
    mpfr_clear(v);
    mpfr_clear(r);
    return ok;
}

static void xvalz(const char *fam, int sg, const mpz_t m, long e2, int nb)
{
    uint8_t t[32], u[32];
    int s, k, q;

    for (s = 0; s < 2; s++) {
        if (sg != 2 && sg != s)
            continue;
        if (!enc_from_mpz(xf, s, m, e2, t))
            return;
        xadd(fam, t, NULL, 0);
        for (k = 1; k <= nb; k++) {
            memcpy(u, t, 32);
            for (q = 0; q < k; q++)
                enc_step(xf, u, 1);
            xadd(fam, u, NULL, 0);
            memcpy(u, t, 32);
            for (q = 0; q < k; q++)
                enc_step(xf, u, 0);
            xadd(fam, u, NULL, 0);
        }
    }
}

/* The representable numbers around n * c, c an mpfr constant (ln 2,
 * log10 2): the value rounded to nearest, nb ulps either way, both signs. */
static void xedge(const char *fam, const mpfr_t c, long n, int nb)
{
    mpfr_t t, v;
    uint8_t b[32], u[32], w[32];
    int s, k, q;

    mpfr_init2(t, (mpfr_prec_t)xf->p + 64);
    mpfr_init2(v, xf->p);
    mpfr_mul_si(t, c, n, MPFR_RNDN);
    mpfr_abs(t, t, MPFR_RNDN);
    mpfr_set(v, t, MPFR_RNDN);
    if (mpfr_to_enc(xf, v, b)) {
        for (s = 0; s < 2; s++) {
            memcpy(u, b, 32);
            if (s)
                enc_neg(xf, u);
            xadd(fam, u, NULL, 0);
            for (k = 1; k <= nb; k++) {
                memcpy(w, u, 32);
                for (q = 0; q < k; q++)
                    enc_step(xf, w, 1);
                xadd(fam, w, NULL, 0);
                memcpy(w, u, 32);
                for (q = 0; q < k; q++)
                    enc_step(xf, w, 0);
                xadd(fam, w, NULL, 0);
            }
        }
    }
    mpfr_clear(t);
    mpfr_clear(v);
}

/* enc +- d, for a count too wide for a long (the near-1 bases). */
static void enc_addz(const fdesc *f, uint8_t *o, const mpz_t d, int sub)
{
    mpz_t v;

    mpz_init(v);
    mpz_import(v, f->esz, -1, 1, 0, 0, o);
    if (sub)
        mpz_sub(v, v, d);
    else
        mpz_add(v, v, d);
    memset(o, 0, 32);
    mpz_export(o, NULL, -1, 1, 0, 0, v);
    mpz_clear(v);
}

static void enc_add_si(const fdesc *f, uint8_t *o, long d)
{
    mpz_t z;

    mpz_init_set_ui(z, (unsigned long)(d < 0 ? -d : d));
    enc_addz(f, o, z, d < 0);
    mpz_clear(z);
}

/* The 754 specials and extremes of THIS format, both signs, and the
 * encodings interesting_operands() of the vector generator lists. */
static void x_io(const char *fam)
{
    static uint8_t sp[MAXPOOL][32];
    uint8_t t[32];
    int s;

    build_pool(xf, sp, 0);       /* 0: +0  2: +inf  4: qNaN  5: sNaN
                                  * 6: minsub  7: maxsub  8: minnormal
                                  * 9: maxnormal  10: 1  11: 1-ulp
                                  * 12: 1+ulp  13: 2  14: 3 */
    for (s = 0; s < 2; s++) {
        int idx[] = { 0, 6, 7, 8, 10, 11, 12, 13, 14, 9, 2 };
        size_t i;
        for (i = 0; i < sizeof idx / sizeof idx[0]; i++) {
            memcpy(t, sp[idx[i]], 32);
            if (s)
                enc_neg(xf, t);
            xadd(fam, t, NULL, 0);
        }
        memcpy(t, sp[8], 32);                    /* minnormal + 1 ulp */
        if (s) enc_neg(xf, t);
        enc_step(xf, t, 1);
        xadd(fam, t, NULL, 0);
        memcpy(t, sp[13], 32);                   /* 2 - ulp: 1.11..1 */
        if (s) enc_neg(xf, t);
        enc_step(xf, t, 0);
        xadd(fam, t, NULL, 0);
        memcpy(t, sp[9], 32);                    /* maxnormal - 1 ulp */
        if (s) enc_neg(xf, t);
        enc_step(xf, t, 0);
        xadd(fam, t, NULL, 0);
    }
    xadd(fam, sp[4], NULL, 0);                   /* qNaN, sNaN */
    xadd(fam, sp[5], NULL, 0);
    memcpy(t, sp[4], 32);                        /* qNaN with a payload */
    t[0] |= 5;
    xadd(fam, t, NULL, 0);
    memcpy(t, sp[4], 32);                        /* the other sign */
    enc_neg(xf, t);
    xadd(fam, t, NULL, 0);
    memcpy(t, sp[5], 32);                        /* sNaN, other sign */
    enc_neg(xf, t);
    xadd(fam, t, NULL, 0);
}

/* The golden model's neighbour thresholds, each straddled: the largest
 * operand on the rule's side, the smallest off it, and one more. The
 * forms in transcend.py are ex <= -(p+c), 2ex + p + c <= 0 and
 * ex >= p + 1 (vexp is floor(log2 |x|)), so each is a binade boundary. */
static void x_tiny_edges(const char *fam)
{
    long p = xf->p, c;

    for (c = 2; c <= 6; c++) {
        xval(fam, 2, 1, -(p + c) + 1, 1);                /* ex <= -(p+c) */
        xval(fam, 2, 1, -((p + c + 1) / 2) + 1, 1);      /* 2ex+p+c <= 0 */
    }
    xval(fam, 2, 1, p + 1, 1);                           /* ex >= p + 1 */
}

/* (1, -k) and (3, -k-1) for each k, both signs: the neighbour rules'
 * operands, one on the first power and one between two. */
static void x_tiny(const char *fam, const long *ks, int nk)
{
    int i;

    for (i = 0; i < nk; i++) {
        xval(fam, 2, 1, -ks[i], 0);
        xval(fam, 2, 3, -ks[i] - 1, 0);
    }
}

/* ---- the unary classes --------------------------------------------- */

/* exp, expm1, exp2, log, log1p, log2, log10 */
static void gen_x(void)
{
    const long p = xf->p, E = xf->emax, M = xf->emin, W = xf->man_w;
    long ints[48], k, tk[6];
    int ni = 0, i;
    mpfr_t ln2;
    mpz_t five;

    x_io("x:io");
    xval("x:units", 2, 1, 0, 1);
    for (k = 1; k <= 24; k++)
        ints[ni++] = k;
    ints[ni++] = p; ints[ni++] = 2 * p; ints[ni++] = E - 1; ints[ni++] = E;
    ints[ni++] = E + 1; ints[ni++] = -M; ints[ni++] = -(M - 1);
    ints[ni++] = W - M; ints[ni++] = W - M + 1;
    for (i = 0; i < ni; i++)
        xval("x:ints", 2, (uint64_t)ints[i], 0, 0);
    /* exp2's integer edges, with the operand's own neighbours: the
     * overflow (n > emax), the tie at emin - man_w - 1 and the quarter
     * below it, and the subnormal and normal edges */
    {
        long ed[] = { E, E + 1, E + 2, -M - 1, -M, -M + 1, W - M - 1,
                      W - M, W - M + 1, W - M + 2, W - M + 3 };
        for (i = 0; i < (int)(sizeof ed / sizeof ed[0]); i++)
            xval("x:int-edge", 2, (uint64_t)ed[i], 0, 1);
    }
    {
        long pw[] = { -3, -1, 1, 2, 10, E, M, M - W + 1 };
        for (i = 0; i < (int)(sizeof pw / sizeof pw[0]); i++)
            xval("x:pow2", 0, 1, pw[i], 1);
    }
    {
        /* log2's exact cases at the subnormal powers of two, where the
         * exponent is read off the significand rather than the field */
        long ps[] = { M - W, M - W + 2, M - W / 2, M - 2, M - 1, M + 1 };
        for (i = 0; i < (int)(sizeof ps / sizeof ps[0]); i++)
            xval("x:pow2-sub", 0, 1, ps[i], 1);
    }
    mpz_init_set_ui(five, 1);
    for (k = 0; mpz_sizeinbase(five, 2) <= (size_t)p; k++) {
        xvalz("x:pow10", 0, five, k, 1);
        mpz_mul_ui(five, five, 5);
    }
    mpz_clear(five);
    mpfr_init2(ln2, (mpfr_prec_t)p + 64);
    mpfr_const_log2(ln2, MPFR_RNDN);
    {
        long ns[] = { E, E + 1, E + 2, M, M - W, M - W - 1, M - W - 2,
                      -(p + 2), -(p + 3), p + 1 };
        for (i = 0; i < (int)(sizeof ns / sizeof ns[0]); i++)
            xedge("x:ln2-edge", ln2, ns[i], 2);
    }
    mpfr_clear(ln2);
    tk[0] = p + 2; tk[1] = p + 3; tk[2] = p + 4; tk[3] = p + 5;
    tk[4] = p + 10; tk[5] = 2 * p;
    x_tiny("x:tiny", tk, 6);
    x_tiny_edges("x:tiny-edge");
}

/* sinPi, cosPi, tanPi, asin, acos, atan and the three Pi-inverses */
static void gen_trig(void)
{
    const long p = xf->p, E = xf->emax;
    long k, tk[9];
    int i;
    static const long HALVES[] = { 1, 3, 5, 7, 9, 17, 33 };
    static const long QUARTS[] = { 1, 3, 5, 7, 9, 11, 13 };
    static const long INTS[]   = { 1, 2, 3, 4, 5, 8, 17 };
    static const long EIGHTHS[] = { 1, 3, 5, 7, 11, 13 };

    x_io("t:io");
    xval("t:units", 2, 1, 0, 2);
    for (i = 0; i < 7; i++) xval("t:halves", 2, (uint64_t)HALVES[i], -1, 1);
    for (i = 0; i < 7; i++) xval("t:quarters", 2, (uint64_t)QUARTS[i], -2, 1);
    for (i = 0; i < 7; i++) xval("t:ints", 2, (uint64_t)INTS[i], 0, 1);
    for (i = 0; i < 6; i++) xval("t:eighths", 2, (uint64_t)EIGHTHS[i], -3, 1);
    {
        long tops[] = { p - 1, p, p + 1, 2 * p, E - 1, E };
        for (i = 0; i < 6; i++)
            xval("t:top", 2, 1, tops[i], 1);
    }
    tk[0] = p / 2; tk[1] = p / 2 + 1; tk[2] = p / 2 + 2; tk[3] = p;
    tk[4] = p + 1; tk[5] = p + 2; tk[6] = p + 3; tk[7] = 2 * p;
    tk[8] = 4 * p;
    x_tiny("t:tiny", tk, 9);
    x_tiny_edges("t:tiny-edge");
    /* sinPi and cosPi beside a half-integer or an integer: the
     * reduced distance s from it is what the rule 2 vexp(s) + p + 6 <= 0
     * reads, so the operands h +- 2^-j around j = (p + 6) / 2 */
    {
        long j0 = (p + 6 + 1) / 2;
        static const long HS[] = { 1, 2, 3, 4, 5, 6 };      /* h = HS / 2 */
        for (i = 0; i < 6; i++)
            for (k = j0 - 1; k <= j0 + 1; k++) {
                uint8_t h[32], s2[32], t[32];
                int sg;
                if (!enc_from_val(xf, 0, (uint64_t)HS[i], -1, h) ||
                    !enc_from_val(xf, 0, 1, -k, s2))
                    continue;
                for (sg = 0; sg < 2; sg++) {
                    mpfr_t a, b2;
                    mpfr_init2(a, xf->p + 4);
                    mpfr_init2(b2, xf->p + 4);
                    enc_to_mpfr(xf, h, a);
                    enc_to_mpfr(xf, s2, b2);
                    if (sg)
                        mpfr_sub(a, a, b2, MPFR_RNDN);
                    else
                        mpfr_add(a, a, b2, MPFR_RNDN);
                    {
                        mpfr_t r;
                        mpfr_init2(r, xf->p);
                        if (mpfr_set(r, a, MPFR_RNDN) == 0 &&
                            mpfr_to_enc(xf, r, t)) {
                            xadd("t:beside-half", t, NULL, 0);
                            enc_neg(xf, t);
                            xadd("t:beside-half", t, NULL, 0);
                        }
                        mpfr_clear(r);
                    }
                    mpfr_clear(a);
                    mpfr_clear(b2);
                }
            }
    }
}

/* The reduction's worst cases, from MPFR's own pi.
 *
 * In the binade [2^v, 2^(v+1)) the arguments x = m 2^(v-p+1) lie at
 * distances |x - n pi/2| = pi/2 |m a - n| from the multiples of pi/2,
 * with a = 2^(v-p+2) / pi, and the hardest is the m in [2^(p-1), 2^p)
 * that minimises the distance of m a to the nearest integer: the one
 * whose reduced argument has the most leading zeros, which is what
 * widens the library's window and what an independent reduction has to
 * get right. The vector generator takes them from host/tools/
 * pi_worstcase.py, which reads the library's own table of 2/pi; these
 * are found from MPFR's pi, by the continued fraction of frac(a): the
 * best m in the window is the multiple of a convergent denominator or an
 * intermediate fraction between two, and each candidate is judged by an
 * exact integer residual. Measured against pi_worstcase.py's descent
 * over every binade of fp32 (128) and fp64 (1024) and the sampled ones
 * of fp128 and fp256 (8 and 8), on 2026-11-02, the two name the same m
 * every time. Nothing here depends on it being so: a candidate that was
 * not the worst would still be an argument near a multiple of pi/2, and
 * MPFR judges it like any other. */
static void worst_in_binade(const fdesc *f, long v, mpz_t m_out,
                            long *lost_out)
{
    const long p = f->p, Fb = 2 * p + 128;
    mpfr_prec_t P = (mpfr_prec_t)((v - p + 2 > 0 ? v - p + 2 : 0) +
                                  2 * p + 192);
    mpfr_t pi, al;
    mpz_t num, den, r0, r1, q0, qm1, q, a, n0, n1, m, s, tmp, best_d, best_m;
    int have = 0, k;

    mpfr_init2(pi, P);
    mpfr_init2(al, P);
    mpz_init(num); mpz_init(den); mpz_init(r0); mpz_init(r1);
    mpz_init(q0); mpz_init(qm1); mpz_init(q); mpz_init(a); mpz_init(n0);
    mpz_init(n1); mpz_init(m); mpz_init(s); mpz_init(tmp);
    mpz_init(best_d); mpz_init(best_m);

    mpfr_const_pi(pi, MPFR_RNDN);
    mpfr_ui_div(al, 1, pi, MPFR_RNDN);
    mpfr_mul_2si(al, al, v - p + 2, MPFR_RNDN);        /* 2^(v-p+2) / pi */
    mpfr_frac(al, al, MPFR_RNDN);
    mpfr_mul_2ui(al, al, (unsigned long)Fb, MPFR_RNDN);
    mpfr_get_z(num, al, MPFR_RNDZ);                    /* frac * 2^Fb */
    mpz_set_ui(den, 1);
    mpz_mul_2exp(den, den, (mp_bitcnt_t)Fb);
    mpz_set_ui(n0, 1);
    mpz_mul_2exp(n0, n0, (mp_bitcnt_t)(p - 1));
    mpz_mul_2exp(n1, n0, 1);                           /* 2^p */
    mpz_set(r0, den);
    mpz_set(r1, num);
    mpz_set_ui(qm1, 0);
    mpz_set_ui(q0, 1);

    while (mpz_sgn(r1)) {
        mpz_t cand[6];
        mpz_fdiv_q(a, r0, r1);
        for (k = 0; k < 6; k++)
            mpz_init(cand[k]);
        /* the multiple of the last convergent just inside the window */
        mpz_cdiv_q(tmp, n0, q0);
        mpz_mul(cand[0], tmp, q0);
        /* the intermediate fractions qm1 + s q0, s in 1..a: the first
         * and the last inside the window, and one more beside each */
        mpz_sub(tmp, n0, qm1);
        mpz_cdiv_q(s, tmp, q0);
        if (mpz_cmp_ui(s, 1) < 0)
            mpz_set_ui(s, 1);
        mpz_mul(cand[1], s, q0); mpz_add(cand[1], cand[1], qm1);
        mpz_add_ui(tmp, s, 1);
        mpz_mul(cand[2], tmp, q0); mpz_add(cand[2], cand[2], qm1);
        mpz_sub_ui(tmp, n1, 1);
        mpz_sub(tmp, tmp, qm1);
        mpz_fdiv_q(s, tmp, q0);
        if (mpz_cmp(s, a) > 0)
            mpz_set(s, a);
        mpz_mul(cand[3], s, q0); mpz_add(cand[3], cand[3], qm1);
        mpz_sub_ui(tmp, s, 1);
        mpz_mul(cand[4], tmp, q0); mpz_add(cand[4], cand[4], qm1);
        mpz_set_ui(cand[5], 0);
        for (k = 0; k < 5; k++) {
            if (mpz_cmp(cand[k], n0) < 0 || mpz_cmp(cand[k], n1) >= 0)
                continue;
            mpz_mul(tmp, cand[k], num);
            mpz_fdiv_r(tmp, tmp, den);                 /* m a mod 1 */
            mpz_sub(s, den, tmp);
            if (mpz_cmp(s, tmp) < 0)
                mpz_set(tmp, s);                       /* the distance */
            if (!have || mpz_cmp(tmp, best_d) < 0) {
                mpz_set(best_d, tmp);
                mpz_set(best_m, cand[k]);
                have = 1;
            }
        }
        for (k = 0; k < 6; k++)
            mpz_clear(cand[k]);
        mpz_mul(q, a, q0);
        mpz_add(q, q, qm1);
        mpz_mul(tmp, a, r1);
        mpz_sub(tmp, r0, tmp);
        mpz_set(r0, r1);
        mpz_set(r1, tmp);
        mpz_set(qm1, q0);
        mpz_set(q0, q);
        if (mpz_cmp(qm1, n1) >= 0)
            break;
    }
    mpz_set(m_out, best_m);
    *lost_out = have ? Fb - (long)mpz_sizeinbase(best_d, 2) : 0;
    mpfr_clear(pi); mpfr_clear(al);
    mpz_clear(num); mpz_clear(den); mpz_clear(r0); mpz_clear(r1);
    mpz_clear(q0); mpz_clear(qm1); mpz_clear(q); mpz_clear(a);
    mpz_clear(n0); mpz_clear(n1); mpz_clear(m); mpz_clear(s);
    mpz_clear(tmp); mpz_clear(best_d); mpz_clear(best_m);
}

/* The deepest few of a sweep of binades with |x| >= 1, as the vector
 * generator takes them (stride and count by format), each with a grid
 * neighbour either side and both signs. */
static void gen_rad_worst(void)
{
    static const long STRIDE[4] = { 8, 64, 2048, 32768 };
    static const int TOP[4] = { 4, 4, 3, 3 };
    const int fi = (int)(xf - FMTS);
    const long p = xf->p, E = xf->emax;
    long vs[24], lost[24], v;
    mpz_t ms[24], t;
    int nr = 0, i, j, dm;

    mpz_init(t);
    for (v = 0; v <= E && nr < 24; v += STRIDE[fi]) {
        mpz_init(ms[nr]);
        worst_in_binade(xf, v, ms[nr], &lost[nr]);
        vs[nr] = v;
        nr++;
    }
    for (i = 0; i < nr; i++)                   /* deepest first, then v */
        for (j = i + 1; j < nr; j++)
            if (lost[j] > lost[i] || (lost[j] == lost[i] && vs[j] > vs[i])) {
                long tl = lost[i], tv = vs[i];
                lost[i] = lost[j]; vs[i] = vs[j];
                lost[j] = tl; vs[j] = tv;
                mpz_swap(ms[i], ms[j]);
            }
    for (i = 0; i < TOP[fi] && i < nr; i++)
        for (dm = -1; dm <= 1; dm++) {
            if (dm < 0)
                mpz_sub_ui(t, ms[i], 1);
            else
                mpz_add_ui(t, ms[i], (unsigned long)dm);
            if (mpz_sizeinbase(t, 2) == (size_t)p)
                xvalz("r:worst", 2, t, vs[i] - p + 1, 0);
        }
    for (i = 0; i < nr; i++)
        mpz_clear(ms[i]);
    mpz_clear(t);
}

/* sin, cos, tan of a radian argument */
static void gen_rad(void)
{
    const long p = xf->p, E = xf->emax, M = xf->emin, W = xf->man_w;
    long k, tk[7], step = xf->esz <= 8 ? 1 : (E + 1) / 48;
    int i;

    if (step < 1)
        step = 1;
    x_io("r:io");
    for (k = M - W; k <= E; k += step)
        xval("r:pow2-sweep", 2, 1, k, 0);
    {
        long pw[] = { E, E - 1, 0, 1, 2, p, 2 * p, M, M - W };
        for (i = 0; i < 9; i++)
            xval("r:pow2-near", 2, 1, pw[i], 1);
    }
    tk[0] = p / 2 - 1; tk[1] = p / 2; tk[2] = p / 2 + 1; tk[3] = p / 2 + 2;
    tk[4] = p; tk[5] = p + 2; tk[6] = 2 * p;
    x_tiny("r:tiny", tk, 7);
    x_tiny_edges("r:tiny-edge");
    gen_rad_worst();
}

/* sinh, cosh, tanh, asinh, acosh, atanh */
static void gen_hyp(void)
{
    const long p = xf->p, E = xf->emax, M = xf->emin, W = xf->man_w;
    long tk[8], bl = 0, vv = p + 2, k;
    int i;
    mpfr_t ln2;
    static const long K0[] = { 1, 2, 3, 4, 5, 8, 17, 100 };
    static const long K1[] = { 1, 3, 5, 7, 9 };
    static const long K2[] = { 1, 3, 5, 7 };

    x_io("h:io");
    xval("h:units", 2, 1, 0, 1);
    for (i = 0; i < 8; i++) xval("h:small", 2, (uint64_t)K0[i], 0, 1);
    for (i = 0; i < 5; i++) xval("h:small", 2, (uint64_t)K1[i], -1, 1);
    for (i = 0; i < 4; i++) xval("h:small", 2, (uint64_t)K2[i], -2, 1);
    mpfr_init2(ln2, (mpfr_prec_t)p + 64);
    mpfr_const_log2(ln2, MPFR_RNDN);
    {
        long ns[] = { E, E + 1, E + 2, E + 3, M, M - W };
        for (i = 0; i < 6; i++)
            xedge("h:ln2-edge", ln2, ns[i], 2);
    }
    mpfr_clear(ln2);
    while (vv) { bl++; vv >>= 1; }
    for (k = bl - 1; k <= bl + 1; k++)
        xval("h:tanh-edge", 2, 1, k, 1);
    tk[0] = p / 2 - 1; tk[1] = p / 2; tk[2] = p / 2 + 1; tk[3] = p / 2 + 2;
    tk[4] = p; tk[5] = p + 2; tk[6] = 2 * p; tk[7] = 4 * p;
    x_tiny("h:tiny", tk, 8);
    x_tiny_edges("h:tiny-edge");
}

/* exp2m1, exp10, exp10m1, log2p1, log10p1, rSqrt */
static void gen_t91(void)
{
    const long p = xf->p, E = xf->emax, M = xf->emin, W = xf->man_w;
    long k, tk[5], ks[48];
    int i, nk = 0;
    mpz_t five, ten, t;
    mpfr_t l10;

    x_io("m:io");
    xval("m:units", 2, 1, 0, 1);
    for (k = 1; k <= 11; k++)
        ks[nk++] = k;
    ks[nk++] = p - 1; ks[nk++] = p; ks[nk++] = p + 1; ks[nk++] = p + 2;
    ks[nk++] = p + 3; ks[nk++] = 2 * p; ks[nk++] = E - 1; ks[nk++] = E;
    ks[nk++] = E + 1; ks[nk++] = -M; ks[nk++] = W - M;
    for (i = 0; i < nk; i++)
        xval("m:ints", 2, (uint64_t)ks[i], 0, 1);
    {
        long ed[] = { E + 2, -M - 1, -M + 1, W - M - 1, W - M + 1 };
        for (i = 0; i < 5; i++)
            xval("m:int-edge", 2, (uint64_t)ed[i], 0, 1);
    }
    mpz_init_set_ui(five, 1);
    mpz_init(ten);
    mpz_init(t);
    mpz_set_ui(ten, 1);
    for (k = 0; mpz_sizeinbase(five, 2) <= (size_t)p; k++) {
        xvalz("m:pow10", 0, five, k, 1);               /* 5^k 2^k = 10^k */
        if (k) {
            mpz_sub_ui(t, ten, 1);                     /* 10^k - 1 */
            xvalz("m:10^k-1", 0, t, 0, 1);
        }
        mpz_mul_ui(five, five, 5);
        mpz_mul_ui(ten, ten, 10);
    }
    mpz_clear(five);
    mpz_clear(ten);
    mpz_clear(t);
    for (k = 1; k <= (p < 40 ? p : 40); k++) {
        xval("m:2^k-1", 2, (((uint64_t)1) << k) - 1, 0, 1);
        xval("m:2^k-1", 2, (((uint64_t)1) << k) - 1, -k, 1);
    }
    {
        long pw[40];
        int np = 0;
        for (k = -6; k <= 6; k++)
            pw[np++] = k;
        pw[np++] = p; pw[np++] = -p; pw[np++] = E; pw[np++] = E - 1;
        pw[np++] = M; pw[np++] = M - W; pw[np++] = M - W + 1;
        for (i = 0; i < np; i++)
            xval("m:pow2", 2, 1, pw[i], 1);
    }
    tk[0] = p + 2; tk[1] = p + 3; tk[2] = p + 4; tk[3] = p + 5;
    tk[4] = 2 * p;
    x_tiny("m:tiny", tk, 5);
    x_tiny_edges("m:tiny-edge");
    /* log2p1 changes rule at x = 2^k once k >= p - floor(log2 k) + 1 */
    {
        long g, kmin = 0, t2;
        for (k = 1; k <= 4 * p && !kmin; k++) {
            g = 0;
            for (t2 = k; t2 > 1; t2 >>= 1)
                g++;
            if (k >= p - g + 1)
                kmin = k;
        }
        for (k = kmin - 2; k <= kmin + 2; k++)
            if (k >= 1)
                xval("m:log2p1-edge", 0, 1, k, 1);
    }
    /* exp10's and exp10m1's overflow, underflow and beside -1 edges: the
     * x with x log2(10) = n, that is x = n log10(2) */
    mpfr_init2(l10, (mpfr_prec_t)p + 64);
    {
        mpfr_t two;
        mpfr_init2(two, 8);
        mpfr_set_ui(two, 2, MPFR_RNDN);
        mpfr_log10(l10, two, MPFR_RNDN);
        mpfr_clear(two);
    }
    {
        long ns[] = { E, E + 1, E + 2, M, M - W, M - W - 1, M - W - 2,
                      -(p + 2), -(p + 3) };
        for (i = 0; i < 9; i++)
            xedge("m:log10-edge", l10, ns[i], 2);
    }
    mpfr_clear(l10);
}

/* ---- the pair and integer-exponent classes ------------------------- */

static int xz(int sg, uint64_t m, long e2, uint8_t *o)
{
    return enc_from_val(xf, sg, m, e2, o);
}

static int xbits(uint64_t m)
{
    int b = 0;
    while (m) { b++; m >>= 1; }
    return b;
}

/* The pow pairs of vectors.py, and for powr the table it adds. */
static void gen_pow(int powr)
{
    const long p = xf->p, E = xf->emax, W = xf->man_w;
    static uint8_t SP[MAXPOOL][32];
    uint8_t S[20][32], one[32], a[32], b[32], c[32], d[32];
    int ns = 0, i, j, k, sg;
    mpz_t dz;

    build_pool(xf, SP, 0);
    memcpy(one, SP[10], 32);
#define SPUSH(src) do { memcpy(S[ns], (src), 32); ns++; } while (0)
#define SVAL(sgn, m, e2) do { if (xz((sgn), (m), (e2), c)) SPUSH(c); } while (0)
    SPUSH(SP[0]); SPUSH(SP[1]); SPUSH(SP[2]); SPUSH(SP[3]); SPUSH(SP[4]);
    SPUSH(SP[5]); SPUSH(SP[10]); SPUSH(SP[16]);
    SVAL(0, 3, -1); SVAL(1, 3, -1); SVAL(0, 1, 1); SVAL(1, 1, 1);
    SVAL(0, 3, 0); SVAL(1, 3, 0);
    SPUSH(SP[9]); SPUSH(SP[6]);
    for (i = 0; i < ns; i++)
        for (j = 0; j < ns; j++)
            xadd(powr ? "powr:specials" : "pow:specials", S[i], S[j], 0);
    if (powr) {
        /* powr's own table: negative bases against every kind of
         * exponent, both zeros against both zeros, an infinite base
         * against a zero exponent, 1 against an infinity, a NaN in
         * either operand */
        ns = 0;
        SPUSH(SP[0]); SPUSH(SP[1]); SPUSH(SP[2]); SPUSH(SP[3]);
        SPUSH(SP[4]); SPUSH(SP[5]); SPUSH(SP[10]); SPUSH(SP[16]);
        SVAL(0, 1, 1); SVAL(1, 1, 1); SVAL(0, 3, -1);
        SPUSH(SP[9]);
        memcpy(c, SP[9], 32); enc_neg(xf, c); SPUSH(c);
        SPUSH(SP[6]);
        for (i = 0; i < ns; i++)
            for (j = 0; j < ns; j++)
                xadd("powr:specials", S[i], S[j], 0);
    }
    {
        static const unsigned BASES[] = { 2, 3, 5, 7, 10, 4097 };
        long nl[] = { 1, 2, 3, 4, 5, 8, 17, p - 1, p, p + 1, p + 2, -1, -2,
                      -3, 1000 };
        for (i = 0; i < 6; i++) {
            if (xbits(BASES[i]) > p)
                continue;
            for (k = 0; k < 15; k++) {
                if (!xz(nl[k] < 0, (uint64_t)(nl[k] < 0 ? -nl[k] : nl[k]),
                        0, b))
                    continue;
                for (sg = 0; sg < 2; sg++)
                    if (xz(sg, BASES[i], 0, a))
                        xadd(powr ? "powr:int-exp" : "pow:int-exp", a, b, 0);
            }
        }
    }
    {
        static const unsigned MS[] = { 4, 9, 16, 25, 81, 256, 625, 1024 };
        for (i = 0; i < 8; i++) {
            uint8_t mb[32], mp1[32];
            if (xbits(MS[i]) > p || !xz(0, MS[i], 0, mb))
                continue;
            memcpy(mp1, mb, 32);
            enc_step(xf, mp1, 1);
            for (k = 1; k <= 3; k++) {
                long ey = -k;
                if (xz(0, 1, ey, b)) {
                    xadd("pow:dyadic-exp", mb, b, 0);
                    xadd("pow:dyadic-exp", mp1, b, 0);
                }
                if (xz(0, 3, ey - 1, b))
                    xadd("pow:dyadic-exp", mb, b, 0);
                if (xz(1, 1, ey, b))
                    xadd("pow:dyadic-exp", mb, b, 0);
            }
        }
    }
    {
        /* a perfect square, or fourth power, to a dyadic exponent Y / 2^k
         * with Y odd: the exact root is found, and its Y-th power is too
         * wide to be a boundary either because Y > p + 1 or because the
         * power itself needs more than p + 1 bits (_pow_dyadic, the two
         * returns of None after the root). Y runs across both edges. */
        static const unsigned PW[] = { 9, 25, 49, 81, 625 };
        for (i = 0; i < 5; i++) {
            uint8_t mb[32];
            int kk;
            if (xbits(PW[i]) > p || !xz(0, PW[i], 0, mb))
                continue;
            for (kk = 1; kk <= 2; kk++) {
                unsigned long r = PW[i];
                long Ystar = 0, Y, Yl[12];
                int ny = 0, q2;
                mpz_t v;
                for (q2 = 0; q2 < kk; q2++) {         /* the exact 2^kk-th root */
                    unsigned long s2 = 0;
                    while ((s2 + 1) * (s2 + 1) <= r)
                        s2++;
                    r = s2;
                }
                {
                    unsigned long chk = r;
                    for (q2 = 0; q2 < kk; q2++)
                        chk *= chk;
                    if (r < 2 || chk != PW[i])
                        continue;
                }
                mpz_init_set_ui(v, 1);
                for (Y = 1; Y <= 4 * p; Y++) {         /* r^Y inside p + 1 bits */
                    mpz_mul_ui(v, v, r);
                    if (mpz_sizeinbase(v, 2) > (size_t)p + 1)
                        break;
                    Ystar = Y;
                }
                mpz_clear(v);
                for (Y = Ystar - 2; Y <= Ystar + 3; Y++)
                    if (Y >= 1 && ny < 12)
                        Yl[ny++] = Y;
                for (k = 0; k < ny; k++) {
                    long Yo = Yl[k] | 1;               /* odd */
                    if (xz(0, (uint64_t)Yo, -kk, b))
                        xadd(powr ? "powr:dyadic-wide" : "pow:dyadic-wide",
                             mb, b, 0);
                }
                {
                    long Ye[] = { p + 2, p + 3, p + 4, p + 5, 2 * p + 1 };
                    for (k = 0; k < 5; k++)
                        if (xz(0, (uint64_t)(Ye[k] | 1), -kk, b))
                            xadd(powr ? "powr:dyadic-wide" :
                                        "pow:dyadic-wide", mb, b, 0);
                }
            }
        }
    }
    mpz_init(dz);
    {
        long eys[] = { 0, 10, p, 2 * p, E / 2, E - 1, E, -(p + 20), -(p + 3) };
        for (i = 0; i < 4; i++) {
            if (i == 0) mpz_set_ui(dz, 1);
            if (i == 1) mpz_set_ui(dz, 3);
            if (i == 2) { mpz_set_ui(dz, 0); mpz_setbit(dz, (mp_bitcnt_t)(p / 2)); }
            if (i == 3) { mpz_set_ui(dz, 0); mpz_setbit(dz, (mp_bitcnt_t)W); mpz_sub_ui(dz, dz, 1); }
            for (k = 0; k < 9; k++) {
                if (!xz(0, 1, eys[k], b))
                    continue;
                for (sg = 0; sg < 2; sg++) {
                    memcpy(a, one, 32);
                    enc_addz(xf, a, dz, sg);              /* 1 +- dy ulps */
                    memcpy(d, b, 32);
                    xadd("pow:near1", a, d, 0);
                    enc_neg(xf, d);
                    xadd("pow:near1", a, d, 0);
                }
            }
        }
    }
    mpz_clear(dz);
    {
        static const long DU[] = { 1, 2, 3, 5 }, DV[] = { 0, 1, 2, 3, 5 };
        for (i = 0; i < 4; i++)
            for (j = 0; j < 5; j++) {
                uint8_t base[32], base2[32], expo[32], expp[32];
                memcpy(base, one, 32);  enc_add_si(xf, base, DU[i]);
                memcpy(base2, one, 32); enc_add_si(xf, base2, -DU[i]);
                memcpy(expp, one, 32);  enc_add_si(xf, expp, DV[j]);
                memcpy(expo, expp, 32); enc_neg(xf, expo);
                xadd("pow:cancel", base, expo, 0);
                xadd("pow:cancel", base2, expo, 0);
                xadd("pow:cancel", base, expp, 0);
            }
    }
#undef SPUSH
#undef SVAL
}

/* The exponent that takes a base to 2^n: the overflow and underflow
 * edges of the powers. pairs (x, y), y near n / log2 |x|. */
static void xedge_pair(const char *fam, const uint8_t *x, long n, int nb)
{
    mpfr_t xv, t, v;
    uint8_t y[32], w[32];
    int s, k, q;

    mpfr_init2(xv, xf->p);
    mpfr_init2(t, (mpfr_prec_t)xf->p + 64);
    mpfr_init2(v, xf->p);
    enc_to_mpfr(xf, x, xv);
    mpfr_abs(xv, xv, MPFR_RNDN);
    mpfr_log2(t, xv, MPFR_RNDN);
    if (!mpfr_zero_p(t)) {
        mpfr_si_div(t, n, t, MPFR_RNDN);
        mpfr_abs(t, t, MPFR_RNDN);
        if (mpfr_fits_slong_p(t, MPFR_RNDZ)) {      /* the integers either side */
            long y0 = mpfr_get_si(t, MPFR_RNDZ), d0;
            for (d0 = -1; d0 <= 2; d0++)
                for (s = 0; s < 2; s++) {
                    uint8_t u[32];
                    if (y0 + d0 >= 1 &&
                        enc_from_val(xf, s, (uint64_t)(y0 + d0), 0, u))
                        xadd(fam, x, u, 0);
                }
        }
        mpfr_set(v, t, MPFR_RNDN);
        if (mpfr_to_enc(xf, v, y)) {
            for (s = 0; s < 2; s++) {
                uint8_t u[32];
                memcpy(u, y, 32);
                if (s)
                    enc_neg(xf, u);
                xadd(fam, x, u, 0);
                for (k = 1; k <= nb; k++) {
                    memcpy(w, u, 32);
                    for (q = 0; q < k; q++)
                        enc_step(xf, w, 1);
                    xadd(fam, x, w, 0);
                    memcpy(w, u, 32);
                    for (q = 0; q < k; q++)
                        enc_step(xf, w, 0);
                    xadd(fam, x, w, 0);
                }
            }
        }
    }
    mpfr_clear(xv);
    mpfr_clear(t);
    mpfr_clear(v);
}

static void gen_pow_edges(const char *fam)
{
    const long E = xf->emax, M = xf->emin, W = xf->man_w;
    static const unsigned long NUM[] = { 3, 5, 10, 3, 5 };
    static const long EXP2[] = { 0, 0, 0, -1, -2 };   /* 3, 5, 10, 3/2, 5/4 */
    int i, s;
    uint8_t x[32];

    for (i = 0; i < 5; i++)
        for (s = 0; s < 2; s++) {
            if (!xz(s, NUM[i], EXP2[i], x))
                continue;
            if (s == 1 && i >= 3)
                continue;
            xedge_pair(fam, x, E + 1, 2);
            xedge_pair(fam, x, M - W - 1, 2);
        }
    {
        uint8_t half[32];                      /* 3/4: below 1 */
        if (xz(0, 3, -2, half)) {
            xedge_pair(fam, half, E + 1, 2);
            xedge_pair(fam, half, M - W - 1, 2);
        }
    }
}

/* hypot */
static void gen_hypot(void)
{
    const long p = xf->p, E = xf->emax, M = xf->emin, W = xf->man_w;
    static uint8_t SP[MAXPOOL][32];
    uint8_t a[32], b[32], a1[32], b1[32], one[32];
    int i, sx, sy, k;
    static const unsigned TR[][2] = { {3, 4}, {5, 12}, {8, 15}, {7, 24},
                                      {20, 21}, {9, 40}, {1, 1}, {2, 2},
                                      {6, 8}, {12, 16} };
    long es[4];
    long ks[9];

    build_pool(xf, SP, 0);
    memcpy(one, SP[10], 32);
    es[0] = E - 8; es[1] = M + 2; es[2] = -p; es[3] = M - W;
    for (i = 0; i < 10; i++) {
        unsigned x = TR[i][0], y = TR[i][1];
        if (xbits(x > y ? x : y) > p)
            continue;
        for (sx = 0; sx < 2; sx++)
            for (sy = 0; sy < 2; sy++)
                if (xz(sx, x, 0, a) && xz(sy, y, 0, b))
                    xadd("hypot:triples", a, b, 0);
        if (xz(0, x, 0, a) && xz(0, y, 0, b)) {
            memcpy(b1, b, 32); enc_step(xf, b1, 1);
            xadd("hypot:triples", a, b1, 0);
            memcpy(a1, a, 32); enc_step(xf, a1, 0);
            xadd("hypot:triples", a1, b, 0);
        }
        for (k = 0; k < 4; k++)
            if (xz(0, x, es[k], a) && xz(0, y, es[k], b))
                xadd("hypot:triples", a, b, 0);
    }
    ks[0] = 1; ks[1] = 2; ks[2] = p / 2 - 1; ks[3] = p / 2;
    ks[4] = p / 2 + 1; ks[5] = p; ks[6] = 2 * p; ks[7] = E / 2; ks[8] = E;
    for (i = 0; i < 9; i++) {
        uint8_t sm[32], big[32];
        if (xz(0, 1, -ks[i], sm)) {
            xadd("hypot:dominance", one, sm, 0);
            xadd("hypot:dominance", sm, one, 0);
        }
        if (xz(0, 1, E - ks[i], big)) {
            memcpy(a, SP[9], 32);
            xadd("hypot:dominance", a, big, 0);
        }
    }
    xadd("hypot:extremes", SP[9], SP[9], 0);
    xadd("hypot:extremes", SP[9], SP[6], 0);
    xadd("hypot:extremes", SP[6], SP[6], 0);
    xadd("hypot:extremes", SP[7], SP[7], 0);
    xadd("hypot:extremes", SP[8], SP[6], 0);
    xadd("hypot:extremes", SP[1], SP[1], 0);
    memcpy(b, SP[9], 32); enc_neg(xf, b);
    xadd("hypot:extremes", SP[0], b, 0);
    xadd("hypot:extremes", SP[2], SP[4], 0);
    xadd("hypot:extremes", SP[4], SP[3], 0);
    xadd("hypot:extremes", SP[5], SP[2], 0);
    xadd("hypot:extremes", SP[4], SP[4], 0);
    /* Pythagorean pairs whose hypot is an exact integer wider than p + 1
     * bits, so _hypot_dyadic finds the square root and refuses it: the
     * pair (m^2 - n^2, 2mn) for m = 2^j, n = m - 1 is (2^(j+1) - 1,
     * (2^j - 1) 2^(j+1)) with the hypot 2^(2j+1) - 2^(j+1) + 1, which
     * passes the span screen while 2j + 1 <= p + 6 and is wider than the
     * format while 2j + 2 > p + 1 */
    for (i = (int)((p - 1) / 2); i <= (int)((p + 5) / 2) + 1; i++) {
        mpz_t u, w;
        if (i < 2)
            continue;
        mpz_init_set_ui(u, 1);
        mpz_mul_2exp(u, u, (mp_bitcnt_t)(i + 1));
        mpz_sub_ui(u, u, 1);                          /* 2^(j+1) - 1 */
        mpz_init_set_ui(w, 1);
        mpz_mul_2exp(w, w, (mp_bitcnt_t)i);
        mpz_sub_ui(w, w, 1);                          /* 2^j - 1 */
        if (enc_from_mpz(xf, 0, u, 0, a) &&
            enc_from_mpz(xf, 0, w, i + 1, b)) {
            xadd("hypot:wide-triples", a, b, 0);
            xadd("hypot:wide-triples", b, a, 0);
            memcpy(a1, a, 32); enc_step(xf, a1, 1);
            xadd("hypot:wide-triples", a1, b, 0);
        }
        mpz_clear(u);
        mpz_clear(w);
    }
    /* the exact results the golden model's branch hypot:898 sends to
     * round_pack with a value past the largest finite: Pythagorean pairs
     * scaled to the top of the range, hypot(3t, 4t) = 5t >= 2^(emax+1)
     * with t = 7 * 2^(emax-4), and the same for (5,12) and (8,15) */
    {
        static const struct { unsigned x, y; unsigned long t; long te; } OV[] = {
            { 3, 4, 7, -4 }, { 5, 12, 5, -5 }, { 8, 15, 1, -3 },
            { 3, 4, 3, -4 }, { 5, 12, 3, -5 }, { 8, 15, 1, -4 } };
        for (i = 0; i < 6; i++) {
            long e2 = E + OV[i].te;
            if (xz(0, OV[i].x * OV[i].t, e2, a) &&
                xz(0, OV[i].y * OV[i].t, e2, b)) {
                xadd("hypot:exact-top", a, b, 0);
                xadd("hypot:exact-top", b, a, 0);
                memcpy(b1, b, 32); enc_step(xf, b1, 0);
                xadd("hypot:exact-top", a, b1, 0);
                memcpy(a1, a, 32); enc_step(xf, a1, 1);
                xadd("hypot:exact-top", a1, b, 0);
            }
        }
    }
}

/* atan2 and atan2Pi */
static void gen_atan2(void)
{
    const long p = xf->p, E = xf->emax, M = xf->emin, W = xf->man_w;
    static uint8_t SP[MAXPOOL][32];
    uint8_t ax[16][32], y[32], x[32], two[32], one[32], sub[32], t[32];
    uint8_t c1[32], c2[32];
    int na = 0, i, j, sy, sx, k;
    long es[8];
    long kk[10];

    build_pool(xf, SP, 0);
    memcpy(one, SP[10], 32);
    memcpy(sub, SP[6], 32);
#define APUSH(src) do { memcpy(ax[na], (src), 32); na++; } while (0)
#define AVAL(sgn, m, e2) do { if (xz((sgn), (m), (e2), t)) APUSH(t); } while (0)
    APUSH(SP[0]); APUSH(SP[1]); APUSH(SP[10]); APUSH(SP[16]); APUSH(SP[2]);
    APUSH(SP[3]); APUSH(SP[4]); APUSH(SP[5]);
    AVAL(0, 1, 1); AVAL(1, 1, 1); AVAL(0, 3, 0); AVAL(1, 3, 0);
    APUSH(SP[9]); APUSH(sub);
    memcpy(c1, sub, 32); enc_neg(xf, c1); APUSH(c1);
    for (i = 0; i < na; i++)
        for (j = 0; j < na; j++)
            xadd("atan2:axes", ax[i], ax[j], 0);
    es[0] = 0; es[1] = 1; es[2] = -1; es[3] = p; es[4] = -p; es[5] = E - 1;
    es[6] = M; es[7] = M - W;
    for (k = 0; k < 8; k++) {
        uint8_t bb[32];
        if (!xz(0, 1, es[k], bb))
            continue;
        for (sy = 0; sy < 2; sy++)
            for (sx = 0; sx < 2; sx++) {
                memcpy(y, bb, 32);
                if (sy) enc_neg(xf, y);
                memcpy(x, bb, 32);
                if (sx) enc_neg(xf, x);
                xadd("atan2:diagonals", y, x, 0);
                memcpy(c1, y, 32); enc_step(xf, c1, 1);
                xadd("atan2:diagonals", c1, x, 0);
                memcpy(c2, x, 32); enc_step(xf, c2, 1);
                xadd("atan2:diagonals", y, c2, 0);
                memcpy(c1, y, 32); enc_step(xf, c1, 0);
                xadd("atan2:diagonals", c1, x, 0);
            }
    }
    xz(0, 1, 1, two);
    {
        uint8_t four[32], nsub[32], mtwo[32];
        xz(0, 1, 2, four);
        memcpy(nsub, sub, 32); enc_neg(xf, nsub);
        xz(1, 1, 1, mtwo);
        xadd("atan2:sub-quotient", sub, two, 0);
        xadd("atan2:sub-quotient", sub, four, 0);
        xadd("atan2:sub-quotient", sub, one, 0);
        xadd("atan2:sub-quotient", nsub, two, 0);
        xadd("atan2:sub-quotient", sub, mtwo, 0);
    }
    kk[0] = p; kk[1] = p + 4; kk[2] = 2 * p; kk[3] = 4 * p;
    kk[4] = p - 1; kk[5] = p + 1; kk[6] = p + 2;
    kk[7] = (p + 4) / 2 - 1; kk[8] = (p + 4) / 2; kk[9] = (p + 4) / 2 + 1;
    for (i = 0; i < 10; i++) {
        uint8_t yy[32], none[32], three[32], ny[32];
        if (!xz(0, 1, -kk[i], yy))
            continue;
        memcpy(none, SP[16], 32);
        xz(0, 3, 0, three);
        memcpy(ny, yy, 32); enc_neg(xf, ny);
        xadd("atan2:tiny-over-unit", yy, one, 0);
        xadd("atan2:tiny-over-unit", yy, none, 0);
        xadd("atan2:tiny-over-unit", yy, two, 0);
        xadd("atan2:tiny-over-unit", ny, one, 0);
        xadd("atan2:tiny-over-unit", yy, three, 0);
    }
    kk[0] = p; kk[1] = p + 1; kk[2] = p + 2; kk[3] = p + 3; kk[4] = 2 * p;
    for (i = 0; i < 5; i++) {
        uint8_t big[32], small[32];
        if (!xz(0, 1, kk[i], big) || !xz(0, 1, -kk[i], small))
            continue;
        xadd("atan2:big-small", big, one, 0);
        xadd("atan2:big-small", one, big, 0);
        xadd("atan2:big-small", small, one, 0);
        xadd("atan2:big-small", one, small, 0);
        xadd("atan2:big-small", big, SP[16], 0);
        xadd("atan2:big-small", small, SP[16], 0);
    }
#undef APUSH
#undef AVAL
}

static int cmp_enc_desc(const void *pa, const void *pb)
{
    const uint8_t *a = pa, *b = pb;
    int i;
    for (i = 31; i >= 0; i--)
        if (a[i] != b[i])
            return a[i] < b[i] ? -1 : 1;
    return 0;
}

static int cmp_n(const void *pa, const void *pb)
{
    int64_t a = *(const int64_t *)pa, b = *(const int64_t *)pb;
    uint64_t aa = a < 0 ? 0 - (uint64_t)a : (uint64_t)a;
    uint64_t ab = b < 0 ? 0 - (uint64_t)b : (uint64_t)b;
    if (aa != ab)
        return aa < ab ? -1 : 1;
    return a < b ? -1 : a > b;
}

/* pown, compound, rootn */
static void gen_int(void)
{
    const long p = xf->p, E = xf->emax, M = xf->emin, W = xf->man_w;
    static uint8_t SP[MAXPOOL][32];
    static uint8_t ops[1024][32];
    uint8_t t[32], b2[32];
    int no = 0, i, j, k, sg, q;
    int64_t ns[40];
    int nn = 0;
    static const unsigned MM[] = { 2, 3, 4, 8, 9, 16, 25, 27, 32, 64, 81, 125,
                                   243, 256, 1024, 15625 };
    static const long E5[] = { 0, 2, 6, -4, -6 };
    static const long EE[] = { -3, -2, -1, 1, 2, 3, 6 };

    build_pool(xf, SP, 0);
#define OPUSH(src) do { memcpy(ops[no], (src), 32); no++; } while (0)
    OPUSH(SP[0]); OPUSH(SP[1]); OPUSH(SP[2]); OPUSH(SP[3]); OPUSH(SP[4]);
    OPUSH(SP[5]); OPUSH(SP[10]); OPUSH(SP[16]);
    memcpy(t, SP[10], 32); enc_step(xf, t, 1); OPUSH(t);
    memcpy(t, SP[10], 32); enc_step(xf, t, 0); OPUSH(t);
    memcpy(t, SP[10], 32); enc_neg(xf, t); enc_step(xf, t, 1); OPUSH(t);
    memcpy(t, SP[10], 32); enc_neg(xf, t); enc_step(xf, t, 0); OPUSH(t);
    OPUSH(SP[6]);
    memcpy(t, SP[6], 32); enc_neg(xf, t); OPUSH(t);
    OPUSH(SP[9]);
    memcpy(t, SP[9], 32); enc_neg(xf, t); OPUSH(t);
    OPUSH(SP[8]);
    for (i = 0; i < 16; i++) {
        if (xbits(MM[i]) > p)
            continue;
        for (sg = 0; sg < 2; sg++)
            for (k = 0; k < 5; k++)
                if (xz(sg, MM[i], E5[k], t))
                    OPUSH(t);
        if (xz(0, MM[i], 0, t)) {
            uint8_t u[32];
            memcpy(u, t, 32); enc_step(xf, u, 1); OPUSH(u);
            memcpy(u, t, 32); enc_step(xf, u, 0); OPUSH(u);
        }
    }
    for (i = 0; i < 7; i++)
        for (sg = 0; sg < 2; sg++)
            if (xz(sg, 1, EE[i], t))
                OPUSH(t);
    {
        long el[] = { p, -p, E, M, M - W };
        for (i = 0; i < 5; i++)
            for (sg = 0; sg < 2; sg++)
                if (xz(sg, 1, el[i], t))
                    OPUSH(t);
    }
    {
        long kl[] = { 1, 2, p / 2, p, p + 2, 2 * p };
        for (i = 0; i < 6; i++)
            for (sg = 0; sg < 2; sg++)
                if (xz(sg, 1, -kl[i], t))
                    OPUSH(t);
    }
    qsort(ops, (size_t)no, 32, cmp_enc_desc);
    {
        int w = 0;
        for (i = 0; i < no; i++)               /* unique, in value order */
            if (w == 0 || memcmp(ops[w - 1], ops[i], 32)) {
                memcpy(ops[w], ops[i], 32);
                w++;
            }
        no = w;
    }
    {
        /* the vector generator's n, all 31 of them, so that the stride
         * below pairs what it pairs; the five past the host's long (MPFR
         * takes a long) are dropped when a pair is added, not before */
        int64_t base[] = { 0, 1, -1, 2, -2, 3, -3, 4, -4, 5, -5, 8, -8, 17,
                           -17, p - 1, p, p + 1, p + 2, -(p + 1), -(p + 2),
                           1000, -1000, (int64_t)1 << 20, -((int64_t)1 << 20),
                           ((int64_t)1 << 31) - 1, -((int64_t)1 << 31),
                           (int64_t)1 << 62, -((int64_t)1 << 62),
                           INT64_MAX, INT64_MIN };
        for (i = 0; i < (int)(sizeof base / sizeof base[0]); i++) {
            int dup = 0;
            for (j = 0; j < nn; j++)
                if (ns[j] == base[i])
                    dup = 1;
            if (!dup)
                ns[nn++] = base[i];
        }
    }
    qsort(ns, (size_t)nn, sizeof ns[0], cmp_n);
    for (i = 0; i < no; i++) {
        for (j = i % 3; j < nn; j += 3)
            if (ns[j] >= -2147483647LL && ns[j] <= 2147483647LL)
                xadd("int:vector-pairs", ops[i], NULL, (long)ns[j]);
        for (k = 0; k < 5; k++) {
            static const long SK[] = { 0, 1, 2, -1, -2 };
            xadd("int:vector-pairs", ops[i], NULL, SK[k]);
        }
    }
    /* the specials against every n the oracle itself uses */
    for (i = 0; i < 18; i++)
        for (j = 0; j < TFN_NS_COUNT; j++)
            xadd("int:specials", SP[i], NULL, TFN_NS[j]);
    /* where M^n leaves p + 1 bits - the exact table's edge - for the odd
     * bases: n* is the largest n with M^n inside p+1 bits, and n* - 1,
     * n*, n* + 1 and n* + 2 straddle it */
    {
        static const unsigned OB[] = { 3, 5, 7, 9, 11, 13, 15, 17, 25, 125 };
        for (i = 0; i < 10; i++) {
            mpz_t v;
            long nstar = 0;
            if (xbits(OB[i]) > p)
                continue;
            mpz_init_set_ui(v, 1);
            for (;;) {
                mpz_mul_ui(v, v, OB[i]);
                if (mpz_sizeinbase(v, 2) > (size_t)p + 1)
                    break;
                nstar++;
                if (nstar > 400)
                    break;
            }
            mpz_clear(v);
            if (!xz(0, OB[i], 0, t))
                continue;
            for (k = -1; k <= 2; k++)
                if (nstar + k >= 1) {
                    uint8_t m1[32];
                    xmask = 1;                           /* pown(M, n) */
                    xadd("int:exact-edge", t, NULL, nstar + k);
                    memcpy(b2, t, 32); enc_neg(xf, b2);
                    xadd("int:exact-edge", b2, NULL, nstar + k);
                    xadd("int:exact-edge", t, NULL, -(nstar + k));
                    xmask = 2;                           /* compound: 1 + x = M */
                    if (xz(0, OB[i] - 1, 0, m1))
                        xadd("int:exact-edge", m1, NULL, nstar + k);
                    xmask = 7;
                }
        }
    }
    /* rootn at its perfect powers: r^n exactly, with a neighbour each
     * side, for the n whose root fits. Added for rootn alone: what pown
     * and compound make of these operands is the vector pairs' business. */
    xmask = 4;
    {
        static const unsigned RR[] = { 2, 3, 5, 7, 9, 10, 11, 13 };
        for (i = 0; i < 8; i++) {
            mpz_t v;
            for (k = 2; k <= 12; k++) {
                uint8_t u[32];
                mpz_init_set_ui(v, RR[i]);
                mpz_pow_ui(v, v, (unsigned long)k);
                if (mpz_sizeinbase(v, 2) <= (size_t)p &&
                    enc_from_mpz(xf, 0, v, 0, t)) {
                    xadd("int:perfect-power", t, NULL, k);
                    memcpy(u, t, 32); enc_step(xf, u, 1);
                    xadd("int:perfect-power", u, NULL, k);
                    memcpy(u, t, 32); enc_step(xf, u, 0);
                    xadd("int:perfect-power", u, NULL, k);
                    if (k % 2) {
                        memcpy(u, t, 32); enc_neg(xf, u);
                        xadd("int:perfect-power", u, NULL, k);
                    }
                }
                mpz_clear(v);
            }
        }
    }
    /* rootn(x, -1) of a subnormal that is not a power of two: 1/x passes
     * the format's top, which is the model's screen branch rootn:2862 */
    {
        static const unsigned OM[] = { 3, 5, 7 };   /* (still rootn's) */
        for (i = 0; i < 3; i++)
            for (k = -2; k <= 3; k++) {
                long e2 = -(E + 1 + k + xbits(OM[i]));
                if (xz(0, OM[i], e2, t)) {
                    xadd("int:subnormal-recip", t, NULL, -1);
                    xadd("int:subnormal-recip", t, NULL, -2);
                    xadd("int:subnormal-recip", t, NULL, 1);
                }
            }
    }
    /* the exponent that takes a base to 2^n, as integers: pown's edge */
    xmask = 1;
    {
        static const unsigned BB[] = { 3, 5, 10 };
        for (i = 0; i < 3; i++) {
            mpfr_t bl, ed;
            long nsides[2];
            nsides[0] = E + 1;
            nsides[1] = M - W - 1;
            if (!xz(0, BB[i], 0, t))
                continue;
            mpfr_init2(bl, p + 64);
            mpfr_init2(ed, p + 64);
            {
                mpfr_t bv;
                mpfr_init2(bv, p);
                enc_to_mpfr(xf, t, bv);
                mpfr_log2(bl, bv, MPFR_RNDN);
                mpfr_clear(bv);
            }
            for (q = 0; q < 2; q++) {
                long y0;
                mpfr_si_div(ed, nsides[q], bl, MPFR_RNDN);
                mpfr_abs(ed, ed, MPFR_RNDN);
                y0 = mpfr_get_si(ed, MPFR_RNDZ);
                for (k = -1; k <= 2; k++)
                    if (y0 + k >= 1 && y0 + k <= 2147483647L) {
                        xadd("int:power-edge", t, NULL, y0 + k);
                        xadd("int:power-edge", t, NULL, -(y0 + k));
                        memcpy(b2, t, 32); enc_neg(xf, b2);
                        xadd("int:power-edge", b2, NULL, y0 + k);
                    }
            }
            mpfr_clear(bl);
            mpfr_clear(ed);
        }
    }
    xmask = 7;
#undef OPUSH
}

/* ---- running the lists --------------------------------------------- */

static const int XC_EXP[] = { TF_EXP, TF_EXPM1, TF_EXP2, TF_LOG, TF_LOG1P,
                              TF_LOG2, TF_LOG10, -1 };
static const int XC_TRIG[] = { TF_SINPI, TF_COSPI, TF_TANPI, TF_ASIN,
                               TF_ACOS, TF_ATAN, TF_ASINPI, TF_ACOSPI,
                               TF_ATANPI, -1 };
static const int XC_RAD[] = { TF_SIN, TF_COS, TF_TAN, -1 };
static const int XC_HYP[] = { TF_SINH, TF_COSH, TF_TANH, TF_ASINH,
                              TF_ACOSH, TF_ATANH, -1 };
static const int XC_T91[] = { TF_EXP2M1, TF_EXP10, TF_EXP10M1, TF_LOG2P1,
                              TF_LOG10P1, TF_RSQRT, -1 };

static int in_pool(const uint8_t (*P)[32], int np, const uint8_t *a,
                   size_t esz)
{
    int i;
    for (i = 0; i < np; i++)
        if (!memcmp(P[i], a, esz))
            return 1;
    return 0;
}

/* Is the pair (a, b) one the strided pairing of check_transcend asks of
 * this pool? It asks (P[i], P[j]) for j = i % jstep, + jstep, ... */
static int pair_asked(const uint8_t (*P)[32], int np, const uint8_t *a,
                      const uint8_t *b, size_t esz)
{
    int jstep = np / 8 > 0 ? np / 8 : 1, i, j;

    for (i = 0; i < np; i++) {
        if (memcmp(P[i], a, esz))
            continue;
        for (j = i % jstep; j < np; j += jstep)
            if (!memcmp(P[j], b, esz))
                return 1;
    }
    return 0;
}

/* Is (a, n) one the integer-exponent loop asks of this pool? */
static int int_asked(const uint8_t (*P)[32], int np, const uint8_t *a,
                     long n, size_t esz)
{
    int i, k;

    for (i = 0; i < np; i++) {
        if (memcmp(P[i], a, esz))
            continue;
        for (k = i % 3; k < TFN_NS_COUNT; k += 3)
            if (TFN_NS[k] == n)
                return 1;
    }
    return 0;
}

/* How many of the list's entries the pools already ask - counted once
 * per list, for the table at the end: intended - held = added. kind 0 is
 * unary, 1 a pair, 2 an operand and an n. */
static void xcount_held(int fj, int kind, const uint8_t (*P1)[32], int n1,
                        const uint8_t (*P2)[32], int n2)
{
    const fdesc *f = &FMTS[fj];
    int ix;

    for (ix = 0; ix < XL.cnt; ix++) {
        int held;
        if (kind == 0)
            held = in_pool(P1, n1, XL.a[ix], f->esz) ||
                   (P2 && in_pool(P2, n2, XL.a[ix], f->esz));
        else if (kind == 1)
            held = pair_asked(P1, n1, XL.a[ix], XL.b[ix], f->esz) ||
                   (P2 && pair_asked(P2, n2, XL.a[ix], XL.b[ix], f->esz));
        else
            held = int_asked(P1, n1, XL.a[ix], XL.n[ix], f->esz) ||
                   (P2 && int_asked(P2, n2, XL.a[ix], XL.n[ix], f->esz));
        if (held)
            xfam_held[XL.fam[ix]][fj]++;
    }
}

static void xrun_case(int fj, int fn, int mi, int idx, const uint8_t *a,
                      const uint8_t *b, long nn, int fam)
{
    static const uint8_t zero_op[32];
    const fdesc *f = &FMTS[fj];
    int nargs = TFN_NARGS[fn], hasn = TFN_HASINT[fn];
    uint8_t d[32];
    uint32_t gf, wf = 0;
    cft_status st = CFT_OK;
    char extra[96];
    mpfr_t want;

    if (!b)
        b = zero_op;                  /* t_oracle reads it, unary or not */
    if (dump_cases) {
        if (mi == 0) {
            char ha[70], hb[70];
            hexdump(a, f->esz, ha);
            if (nargs == 2)
                hexdump(b, f->esz, hb);
            else
                strcpy(hb, "-");
            printf("C %s %s e %d 0 1 %s %s ", f->name, TFN_NAME[fn], idx,
                   ha, hb);
            if (hasn)
                printf("%ld %s\n", nn, xfam_name[fam]);
            else
                printf("- %s\n", xfam_name[fam]);
        }
        return;
    }
    mpfr_init2(want, f->p);
    t_oracle(f, fn, mi, a, b, nn, want, &wf);
    memset(d, 0, sizeof d);
    gf = tfn_lib(f, fn, MODES[mi].cr, a, b, nn, d, &st);
    if (hasn)
        snprintf(extra, sizeof extra, "n=%ld [%s]", nn, xfam_name[fam]);
    else
        snprintf(extra, sizeof extra, "[%s]", xfam_name[fam]);
    c5_judge(T_EXP + fn, fj, TFN_NAME[fn], MODES[mi].name, f, a,
             nargs == 2 ? b : NULL, f, d, want, gf, wf, st, extra);
    mpfr_clear(want);
    xfam_cases[fam][fj]++;
}

static void xrun_unary(int fj, const int *fns, const uint8_t (*P1)[32],
                       int n1, const uint8_t (*P2)[32], int n2)
{
    const fdesc *f = &FMTS[fj];
    int ix, mi;

    for (; *fns >= 0; fns++) {
        int fn = *fns;
        for (ix = 0; ix < XL.cnt; ix++) {
            if (in_pool(P1, n1, XL.a[ix], f->esz) ||
                (P2 && in_pool(P2, n2, XL.a[ix], f->esz)))
                continue;
            if (!XL.ran[ix]) {
                XL.ran[ix] = 1;
                xfam_mem[XL.fam[ix]][fj]++;
            }
            for (mi = 0; mi < 5; mi++)
                xrun_case(fj, fn, mi, ix, XL.a[ix], NULL, 0, XL.fam[ix]);
        }
    }
}

/* fn on the entries of XL not already asked of the pools in P (one or two) */
static void xrun_pairs(int fj, int fn, const uint8_t (*P1)[32], int n1,
                       const uint8_t (*P2)[32], int n2)
{
    const fdesc *f = &FMTS[fj];
    int ix, mi, hasn = TFN_HASINT[fn];

    for (ix = 0; ix < XL.cnt; ix++) {
        if (hasn) {
            int bit = fn == TF_POWN ? 1 : fn == TF_COMPOUND ? 2 : 4;
            if (!(XL.fmask[ix] & bit))
                continue;                 /* added for another of the three */
            if (int_asked(P1, n1, XL.a[ix], XL.n[ix], f->esz) ||
                (P2 && int_asked(P2, n2, XL.a[ix], XL.n[ix], f->esz)))
                continue;
        } else {
            if (pair_asked(P1, n1, XL.a[ix], XL.b[ix], f->esz) ||
                (P2 && pair_asked(P2, n2, XL.a[ix], XL.b[ix], f->esz)))
                continue;
        }
        if (!XL.ran[ix]) {
            XL.ran[ix] = 1;
            xfam_mem[XL.fam[ix]][fj]++;
        }
        for (mi = 0; mi < 5; mi++)
            xrun_case(fj, fn, mi, ix, XL.a[ix], XL.b[ix], XL.n[ix],
                      XL.fam[ix]);
    }
}

static void check_extras(int fj, uint8_t xpool[][32], int xn,
                         uint8_t gpool_[][32], int gn,
                         uint8_t hpool_[][32], int hn)
{
    const uint8_t (*XP)[32] = (const uint8_t (*)[32])xpool;
    const uint8_t (*GP)[32] = (const uint8_t (*)[32])gpool_;
    const uint8_t (*HP)[32] = (const uint8_t (*)[32])hpool_;

    xf = &FMTS[fj];
    xcur_fj = fj;

    /* exp, expm1, exp2, log, log1p, log2, log10: the exponential pool */
    XL.cnt = 0; gen_x();
    xcount_held(fj, 0, XP, xn, NULL, 0);
    xrun_unary(fj, XC_EXP, XP, xn, NULL, 0);
    /* the nine trigonometric: the trigonometric pool */
    XL.cnt = 0; gen_trig();
    xcount_held(fj, 0, GP, gn, NULL, 0);
    xrun_unary(fj, XC_TRIG, GP, gn, NULL, 0);
    /* sin, cos, tan and the six hyperbolics: the third pool */
    XL.cnt = 0; gen_rad();
    xcount_held(fj, 0, HP, hn, NULL, 0);
    xrun_unary(fj, XC_RAD, HP, hn, NULL, 0);
    XL.cnt = 0; gen_hyp();
    xcount_held(fj, 0, HP, hn, NULL, 0);
    xrun_unary(fj, XC_HYP, HP, hn, NULL, 0);
    /* table 9.1's six unary: both of their pools */
    XL.cnt = 0; gen_t91();
    xcount_held(fj, 0, GP, gn, XP, xn);
    xrun_unary(fj, XC_T91, GP, gn, XP, xn);
    /* the binary five and the integer-exponent three */
    XL.cnt = 0; gen_pow(0); gen_pow_edges("pow:edge");
    xcount_held(fj, 1, XP, xn, NULL, 0);
    xrun_pairs(fj, TF_POW, XP, xn, NULL, 0);
    XL.cnt = 0; gen_pow(1); gen_pow_edges("powr:edge");
    xcount_held(fj, 1, GP, gn, XP, xn);
    xrun_pairs(fj, TF_POWR, GP, gn, XP, xn);
    XL.cnt = 0; gen_hypot();
    xcount_held(fj, 1, XP, xn, NULL, 0);
    xrun_pairs(fj, TF_HYPOT, XP, xn, NULL, 0);
    XL.cnt = 0; gen_atan2();
    xcount_held(fj, 1, GP, gn, NULL, 0);
    xrun_pairs(fj, TF_ATAN2, GP, gn, NULL, 0);
    xrun_pairs(fj, TF_ATAN2PI, GP, gn, NULL, 0);
    XL.cnt = 0; gen_int();
    xcount_held(fj, 2, GP, gn, XP, xn);
    xrun_pairs(fj, TF_POWN, GP, gn, XP, xn);
    xrun_pairs(fj, TF_COMPOUND, GP, gn, XP, xn);
    xrun_pairs(fj, TF_ROOTN, GP, gn, XP, xn);
}

/* ---- the reductions of clause 9.4 ---------------------------------- *
 *
 * See the banner at the top of this file for what this can and cannot
 * settle. In one line: MPFR decides every NODE, and the TREE is
 * reproduced here rather than judged, because 9.4 leaves the
 * association to the implementation and there is nothing to appeal to.
 */

/* An MPFR value already ON the format's grid -> its encoding. The
 * nodes feed each other - oracle() consumes encodings and produces an
 * mpfr value - so the replay needs the inverse of enc_to_mpfr.
 *
 * Not mpfr_to_enc() above, which takes normal values only and refuses
 * everything else: a reduction's nodes produce infinities, signed
 * zeros, subnormals and NaNs as a matter of course, and those classes
 * are most of what its edges are about.
 *
 * It checks its own work, because a value this function could not
 * represent exactly would silently corrupt every node above it and
 * the campaign would report a library bug. */
static void rd_to_enc(const fdesc *f, mpfr_srcptr x, uint8_t *out)
{
    memset(out, 0, f->esz);
    if (mpfr_nan_p(x)) {
        /* the canonical quiet NaN, which is the only NaN this contract
         * emits and the only one MPFR can be said to have returned */
        set_field(out, f->man_w, f->exp_w, (1ul << f->exp_w) - 1);
        out[(f->man_w - 1) / 8] |= (uint8_t)(1u << ((f->man_w - 1) % 8));
        return;
    }
    if (mpfr_signbit(x))
        out[f->esz - 1] |= 0x80;
    if (mpfr_inf_p(x)) {
        set_field(out, f->man_w, f->exp_w, (1ul << f->exp_w) - 1);
        return;
    }
    if (mpfr_zero_p(x))
        return;                          /* the sign is already in */
    {
        mpz_t z;
        mpfr_exp_t e;
        long ee, ebiased;
        size_t bits, i;
        uint8_t tmp[32];

        mpz_init(z);
        e = mpfr_get_z_2exp(z, x);       /* x = z * 2^e, exactly */
        mpz_abs(z, z);
        bits = mpz_sizeinbase(z, 2);
        ee = (long)e + (long)bits - 1;   /* IEEE-style exponent */
        if (ee >= f->emin) {
            long sh = (long)f->p - (long)bits;
            if (sh > 0)
                mpz_mul_2exp(z, z, (unsigned long)sh);
            else if (sh < 0)
                mpz_fdiv_q_2exp(z, z, (unsigned long)(-sh));
            mpz_clrbit(z, f->man_w);     /* the hidden bit */
            ebiased = ee + f->emax;
        } else {
            long sh = (long)e - (f->emin - f->man_w);
            if (sh > 0)
                mpz_mul_2exp(z, z, (unsigned long)sh);
            else if (sh < 0)
                mpz_fdiv_q_2exp(z, z, (unsigned long)(-sh));
            ebiased = 0;
        }
        memset(tmp, 0, sizeof tmp);
        mpz_export(tmp, NULL, -1, 1, 0, 0, z);
        for (i = 0; i < f->esz; i++)
            out[i] |= tmp[i];
        if (ebiased)
            set_field(out, f->man_w, f->exp_w, (unsigned long)ebiased);
        mpz_clear(z);
    }
    if (!agree(f, out, x)) {
        char h[70];
        hexdump(out, f->esz, h);
        printf("HARNESS BUG: rd_to_enc lost a value at %s -> 0x%s\n",
               f->name, h);
        mismatches++;
    }
}

/* The contract's split: the largest power of two strictly inside the
 * range, so the LEFT child is a perfect subtree. REPRODUCED, not
 * arbitrated. */
static size_t rd_split(size_t lo, size_t hi)
{
    size_t m = hi - lo, k = 1;
    while (k < m)
        k <<= 1;
    return lo + (k >> 1);
}

/* enc (finite, non-zero) -> a significand in +-[1, 2) and the exact
 * scale, the scaled products' leaf and node rule. Exact bit surgery:
 * there is nothing here to round, so there is nothing here for MPFR
 * to arbitrate, and saying so is the point. */
static void rd_norm_split(const fdesc *f, const uint8_t *x, uint8_t *sig,
                          long long *k)
{
    mpz_t enc, man;
    unsigned long biased;
    long e;
    size_t bits, i;
    uint8_t tmp[32];
    int sign = (x[f->esz - 1] >> 7) & 1;

    mpz_init(enc);
    mpz_init(man);
    mpz_import(enc, f->esz, -1, 1, 0, 0, x);
    mpz_fdiv_r_2exp(man, enc, f->man_w);
    mpz_fdiv_q_2exp(enc, enc, f->man_w);
    biased = mpz_get_ui(enc) & ((1ul << f->exp_w) - 1);
    if (biased) {
        mpz_setbit(man, f->man_w);
        e = (long)biased - f->emax - f->man_w;
    } else {
        e = f->emin - f->man_w;
    }
    bits = mpz_sizeinbase(man, 2);
    *k = (long long)e + (long long)bits - 1;
    mpz_mul_2exp(man, man, (unsigned long)(f->man_w - (bits - 1)));
    mpz_clrbit(man, f->man_w);
    memset(sig, 0, f->esz);
    memset(tmp, 0, sizeof tmp);
    mpz_export(tmp, NULL, -1, 1, 0, 0, man);
    for (i = 0; i < f->esz; i++)
        sig[i] |= tmp[i];
    set_field(sig, f->man_w, f->exp_w, (unsigned long)f->emax);
    if (sign)
        sig[f->esz - 1] |= 0x80;
    mpz_clear(enc);
    mpz_clear(man);
}

/* The sum tree over already-transformed leaves, MPFR at every node. */
static void rd_tree(const fdesc *f, int mi, const uint8_t (*leaf)[32],
                    size_t lo, size_t hi, uint8_t *out, uint32_t *flags)
{
    uint8_t l[32], r[32], dummy[32];
    uint32_t lf = 0, rf = 0, nf = 0;
    mpfr_t v;
    size_t mid;

    *flags = 0;
    if (hi - lo == 1) {
        memcpy(out, leaf[lo], f->esz);
        return;
    }
    mid = rd_split(lo, hi);
    rd_tree(f, mi, leaf, lo, mid, l, &lf);
    rd_tree(f, mi, leaf, mid, hi, r, &rf);
    memset(dummy, 0, sizeof dummy);
    mpfr_init2(v, f->p);
    /* ADD reads a and c - b is steered to 1.0 - which oracle() and
     * raw_op() already honour. */
    oracle(f, OP_ADD, mi, l, dummy, r, v, &nf);
    rd_to_enc(f, v, out);
    mpfr_clear(v);
    reduce_nodes++;
    *flags = lf | rf | nf;
}

/* The scaled product tree: MPFR decides the multiply, the extraction
 * is exact. */
static void rd_sp_tree(const fdesc *f, int mi, const uint8_t (*fac)[32],
                       size_t lo, size_t hi, uint8_t *sig,
                       long long *scale, uint32_t *flags)
{
    uint8_t l[32], r[32], prod[32], dummy[32];
    uint32_t lf = 0, rf = 0, nf = 0;
    long long lk = 0, rk = 0, k = 0;
    mpfr_t v;
    size_t mid;

    *flags = 0;
    if (hi - lo == 1) {
        rd_norm_split(f, fac[lo], sig, scale);
        return;
    }
    mid = rd_split(lo, hi);
    rd_sp_tree(f, mi, fac, lo, mid, l, &lk, &lf);
    rd_sp_tree(f, mi, fac, mid, hi, r, &rk, &rf);
    memset(dummy, 0, sizeof dummy);
    mpfr_init2(v, f->p);
    oracle(f, OP_MUL, mi, l, r, dummy, v, &nf);
    rd_to_enc(f, v, prod);
    mpfr_clear(v);
    rd_norm_split(f, prod, sig, &k);
    *scale = lk + rk + k;
    reduce_nodes++;
    *flags = lf | rf | nf;
}

/* The seven, by the order they are tallied in. */
enum { RF_SUM, RF_DOT, RF_SUMSQ, RF_SUMABS,
       RF_PROD, RF_PROD_SUM, RF_PROD_DIFF, RF_COUNT };
static const char *const RFN_NAME[RF_COUNT] = {
    "sum", "dot", "sumsq", "sumabs",
    "scaled_prod", "scaled_prod_sum", "scaled_prod_diff"
};
static const int RFN_BINARY[RF_COUNT] = { 0, 1, 0, 0, 0, 1, 1 };

/* 9.4's special-value tables, replayed. These are the CONTRACT's rows
 * and MPFR has no opinion on them; what MPFR settles is the
 * arithmetic underneath. */
static void rd_classes(const fdesc *f, const uint8_t (*v)[32], size_t n,
                       int *inf, int *zero, int *nan, int *snan, int *sign)
{
    size_t i;
    *inf = *zero = *nan = *snan = *sign = 0;
    for (i = 0; i < n; i++) {
        cls c;
        classify(f, v[i], &c);
        *sign ^= c.sign;
        if (c.is_nan) {
            *nan = 1;
            *snan |= c.is_snan;
        } else if (c.is_inf) {
            *inf = 1;
        } else if (c.is_zero) {
            *zero = 1;
        }
    }
}

#define RD_MAXN 65

static void rd_oracle(const fdesc *f, int fn, int mi,
                      const uint8_t (*a)[32], const uint8_t (*b)[32],
                      size_t n, mpfr_t want, long long *want_sf,
                      uint32_t *wf)
{
    uint8_t leaf[RD_MAXN][32], out[32], dummy[32];
    uint32_t fl = 0, lf = 0;
    int inf = 0, zero = 0, nan = 0, snan = 0, sign = 0;
    size_t i;

    *want_sf = 0;
    memset(dummy, 0, sizeof dummy);

    if (n == 0) {
        if (fn >= RF_PROD) {
            mpfr_set_ui(want, 1, MPFR_RNDN);      /* 9.4: pr = 1, sf = +0 */
        } else {
            mpfr_set_zero(want, 1);               /* 9.4: +0 */
        }
        *wf = 0;
        return;
    }

    /* the leaves */
    for (i = 0; i < n; i++) {
        mpfr_t v;
        switch (fn) {
        case RF_SUM:
            memcpy(leaf[i], a[i], f->esz);
            break;
        case RF_SUMABS:
            /* abs: 5.5.1 says it touches the sign bit and signals
             * nothing, so there is no arithmetic here to arbitrate */
            memcpy(leaf[i], a[i], f->esz);
            leaf[i][f->esz - 1] &= 0x7f;
            break;
        case RF_DOT:
        case RF_SUMSQ:
            mpfr_init2(v, f->p);
            oracle(f, OP_MUL, mi, a[i], fn == RF_DOT ? b[i] : a[i], dummy,
                   v, &lf);
            rd_to_enc(f, v, leaf[i]);
            mpfr_clear(v);
            fl |= lf;
            reduce_nodes++;
            break;
        case RF_PROD:
            memcpy(leaf[i], a[i], f->esz);
            break;
        default:
            mpfr_init2(v, f->p);
            oracle(f, fn == RF_PROD_SUM ? OP_ADD : OP_SUB, mi, a[i], dummy,
                   b[i], v, &lf);
            rd_to_enc(f, v, leaf[i]);
            mpfr_clear(v);
            fl |= lf;
            reduce_nodes++;
            break;
        }
    }

    if (fn < RF_PROD) {
        uint32_t tf = 0;
        /* 9.4 puts an infinity ahead of a NaN for sumSquare and sumAbs,
         * and only for those two. The rows are stated over the OPERAND
         * ELEMENTS, not over the leaves: an element whose square
         * overflows to an infinity is not "an operand element that is
         * an infinity", and squaring a signalling NaN produces a quiet
         * one, so classifying the leaves gets this wrong in both
         * directions. It did, until the campaign said so. */
        rd_classes(f, a, n, &inf, &zero, &nan, &snan, &sign);
        if ((fn == RF_SUMSQ || fn == RF_SUMABS) && inf && nan) {
            mpfr_set_inf(want, 1);
            *wf = snan ? CFT_FLAG_INVALID : 0u;
            return;
        }
        rd_tree(f, mi, (const uint8_t (*)[32])leaf, 0, n, out, &tf);
        enc_to_mpfr(f, out, want);
        *wf = fl | tf;
        return;
    }

    /* The scaled products' rows, in 9.4's order, over the FACTORS -
     * which for scaledProdSum and scaledProdDiff are the rounded sums
     * and differences, and for scaledProd are the elements. */
    rd_classes(f, (const uint8_t (*)[32])leaf, n, &inf, &zero, &nan, &snan,
               &sign);
    if (nan) {
        mpfr_set_nan(want);
        *wf = fl | (snan ? CFT_FLAG_INVALID : 0u);
        return;
    }
    if (inf && zero) {
        mpfr_set_nan(want);
        *wf = fl | CFT_FLAG_INVALID;
        return;
    }
    if (inf) {
        mpfr_set_inf(want, sign ? -1 : 1);
        *wf = fl;
        return;
    }
    if (zero) {
        mpfr_set_zero(want, sign ? -1 : 1);
        *wf = fl;
        return;
    }
    {
        uint32_t tf = 0;
        rd_sp_tree(f, mi, (const uint8_t (*)[32])leaf, 0, n, out, want_sf,
                   &tf);
        enc_to_mpfr(f, out, want);
        *wf = fl | tf;
    }
}

static cft_status rd_lib(const fdesc *f, int fn, cft_round rnd,
                         const uint8_t *a, const uint8_t *b, size_t n,
                         uint8_t *d, long long *sf, uint32_t *flags)
{
    int64_t scale = 0;
    cft_status st;
    *flags = 0;
    switch (fn) {
    case RF_SUM:
        st = cft_reduce(dev, CFT_SUM, f->fmt, rnd, a, NULL, d, n, flags,
                        NULL);
        break;
    case RF_DOT:
        st = cft_reduce(dev, CFT_DOT, f->fmt, rnd, a, b, d, n, flags, NULL);
        break;
    case RF_SUMSQ:
        st = cft_reduce(dev, CFT_SUMSQ, f->fmt, rnd, a, NULL, d, n, flags,
                        NULL);
        break;
    case RF_SUMABS:
        st = cft_reduce(dev, CFT_SUMABS, f->fmt, rnd, a, NULL, d, n, flags,
                        NULL);
        break;
    case RF_PROD:
        st = cft_scaled_prod(dev, f->fmt, rnd, n ? a : NULL, d, &scale, n,
                             flags);
        break;
    case RF_PROD_SUM:
        st = cft_scaled_prod_sum(dev, f->fmt, rnd, n ? a : NULL,
                                 n ? b : NULL, d, &scale, n, flags);
        break;
    default:
        st = cft_scaled_prod_diff(dev, f->fmt, rnd, n ? a : NULL,
                                  n ? b : NULL, d, &scale, n, flags);
        break;
    }
    *sf = (long long)scale;
    return st;
}

static void check_reduce(int fj, uint8_t pool[][32], int pn, int nvec)
{
    static const size_t LENS[] = { 0, 1, 2, 3, 5, 7, 8, 9, 15, 16, 17,
                                   31, 32, 33, 63, 64, 65 };
    const fdesc *f = &FMTS[fj];
    uint8_t va[RD_MAXN][32], vb[RD_MAXN][32];
    uint8_t flat_a[RD_MAXN * 32], flat_b[RD_MAXN * 32];
    uint8_t d[32], big[32], tiny[32];
    int fn, mi, li, v, i;
    int nl = (int)(sizeof LENS / sizeof LENS[0]);

    /* The two ends of the format, built here rather than taken from
     * the pool by index. build_pool's ORDER is its own business -
     * pool[0] is +0 and the tail is random - so a draw that claimed to
     * alternate the extremes while taking pool[0] and pool[pn-1] would
     * be describing something it does not do. It did, until this. */
    memset(big, 0, sizeof big);
    set_field(big, f->man_w, f->exp_w, (1ul << f->exp_w) - 2);
    for (i = 0; i < f->man_w; i++)
        set_field(big, i, 1, 1);                  /* max normal */
    memset(tiny, 0, sizeof tiny);
    set_field(tiny, 0, 1, 1);                     /* min subnormal */

    for (fn = 0; fn < RF_COUNT; fn++) {
        for (mi = 0; mi < 5; mi++) {
            for (li = 0; li < nl; li++) {
                size_t n = LENS[li];
                for (v = 0; v < nvec; v++) {
                    mpfr_t want;
                    long long want_sf = 0, got_sf = 0;
                    uint32_t gf = 0, wf = 0;
                    cft_status st;
                    char extra[96];

                    /* Vectors are drawn from the pool by a stride that
                     * changes with the draw, so a run covers the
                     * specials-heavy pool in different combinations
                     * rather than the same prefix every time. The
                     * fourth draw of every length is the format's two
                     * EXTREMES alternating - the largest finite value
                     * and the smallest subnormal - which is the vector
                     * a scaled product exists for: its true product
                     * leaves the format by hundreds of binades in both
                     * directions and the answer must not. */
                    for (i = 0; i < (int)n; i++) {
                        if (v % 4 == 3) {
                            memcpy(va[i], (i & 1) ? tiny : big, f->esz);
                            memcpy(vb[i], (i & 1) ? big : tiny, f->esz);
                        } else {
                            memcpy(va[i], pool[(i * (v + 1) + li) % pn],
                                   f->esz);
                            memcpy(vb[i], pool[(i * (v + 2) + fn + 1) % pn],
                                   f->esz);
                        }
                        memcpy(flat_a + (size_t)i * f->esz, va[i], f->esz);
                        memcpy(flat_b + (size_t)i * f->esz, vb[i], f->esz);
                    }

                    mpfr_init2(want, f->p);
                    rd_oracle(f, fn, mi, (const uint8_t (*)[32])va,
                              (const uint8_t (*)[32])vb, n, want, &want_sf,
                              &wf);
                    memset(d, 0, sizeof d);
                    st = rd_lib(f, fn, MODES[mi].cr, flat_a,
                                RFN_BINARY[fn] ? flat_b : NULL, n, d,
                                &got_sf, &gf);
                    snprintf(extra, sizeof extra,
                             "n=%lu scale got %lld want %lld",
                             (unsigned long)n, got_sf, want_sf);
                    /* The scale is a second result, so a case that
                     * agrees on pr and disagrees on sf must fail. */
                    if (fn >= RF_PROD && got_sf != want_sf && st == CFT_OK)
                        st = CFT_ERR_INTERNAL;
                    c5_judge(T_RSUM + fn, fj, RFN_NAME[fn], MODES[mi].name,
                             f, n ? va[0] : NULL, NULL, f, d, want, gf, wf,
                             st, extra);
                    mpfr_clear(want);
                }
            }
        }
    }
}

/* ---- the formatOf arithmetic of clause 5.4.1 ----------------------- *
 *
 * MPFR IS A FULL ORACLE HERE, with no footnote, and it is worth saying
 * why: 5.4.1's cross-format operations are DEFINED as "the operands
 * read at their own precision, the infinitely precise result rounded
 * once to the destination", and that sentence is a literal description
 * of mpfr_add / mpfr_mul / mpfr_fma / mpfr_div / mpfr_sqrt with the
 * operand variables at the source precision and the result variable at
 * the destination's. Nothing here restates a rule the way the augmented
 * harness has to restate 9.5's tie, and nothing here reproduces a shape
 * the way the reduction harness reproduces the tree. The library and
 * MPFR are told the same thing and their answers are compared.
 *
 * The exponent range is the DESTINATION's, and it is handled exactly as
 * oracle() handles the same-format case: the unbounded-range result at
 * the destination's precision decides overflow and tininess (the same
 * after-rounding test round_pack applies), and a subnormal landing is
 * re-rounded through the MPFR manual's recipe - emin/emax set to the
 * destination's, mpfr_check_range, mpfr_subnormalize with the ternary.
 * RMM is the p+1 construction the rest of this file uses, at the
 * destination's p.
 *
 * The three DOUBLE-ROUNDING WITNESSES are built here too, from the two
 * descriptors with GMP integers - the cases where computing in the
 * source format and converting down gives a different answer from the
 * single rounding 5.4.1 asks for. They are the only cases in this file
 * whose expected answer would be reached by a plausible wrong
 * implementation, so they are constructed rather than hoped for.
 */

/* Add one to a little-endian encoding: nextUp for a positive finite
 * value that is not the largest, nextDown for a negative one. */
static void enc_inc(uint8_t *b, size_t n)
{
    size_t i;
    for (i = 0; i < n; i++) {
        if (++b[i] != 0)
            return;
    }
}

static void enc_dec(uint8_t *b, size_t n)
{
    size_t i;
    for (i = 0; i < n; i++) {
        if (b[i]-- != 0)
            return;
    }
}

/* One case through MPFR, with the operands at fs's precision and the
 * result at fd's - oracle()'s body with the one format split in two.
 * The duplication is deliberate: oracle() is the same-format campaign's
 * and is left exactly as it was, so a change here cannot silently
 * re-verdict 24 million same-format cases. */
static void fo_oracle(const fdesc *fs, const fdesc *fd, mop op, int mi,
                      const uint8_t *ba, const uint8_t *bb,
                      const uint8_t *bc, mpfr_t out, uint32_t *flags)
{
    mpfr_t a, b, c, runb, r, y;
    cls ca, cb, cc;
    int tunb = 0, inexact, nan_in = 0,
        is_rmm = (MODES[mi].cr == CFT_RMM);
    mpfr_rnd_t rnd = MODES[mi].mr;
    uint32_t fl = 0;

    classify(fs, ba, &ca);
    classify(fs, bb, &cb);
    classify(fs, bc, &cc);

    mpfr_init2(a, fs->p); mpfr_init2(b, fs->p); mpfr_init2(c, fs->p);
    mpfr_init2(runb, fd->p); mpfr_init2(r, fd->p);
    mpfr_init2(y, fd->p + 1);
    enc_to_mpfr(fs, ba, a);
    enc_to_mpfr(fs, bb, b);
    enc_to_mpfr(fs, bc, c);

    {
        int use_b = (op == OP_MUL || op == OP_FMA || op == OP_DIV);
        int use_c = (op == OP_ADD || op == OP_SUB || op == OP_FMA);
        if (ca.is_snan || (use_b && cb.is_snan) || (use_c && cc.is_snan))
            fl |= CFT_FLAG_INVALID;
        nan_in = ca.is_nan || (use_b && cb.is_nan) || (use_c && cc.is_nan);
    }
    if (op == OP_DIV && cb.is_zero && !ca.is_zero && !ca.is_nan &&
        !ca.is_inf)
        fl |= CFT_FLAG_DIVBYZERO;

    if (is_rmm) {
        int t1;
        raw_op(y, op, a, b, c, MPFR_RNDZ, &t1);
        if (!mpfr_number_p(y) || mpfr_zero_p(y)) {
            mpfr_set(runb, y, MPFR_RNDN);
            tunb = 0;
        } else {
            rmm_round(runb, y, t1 != 0, fd->p);
            tunb = !mpfr_equal_p(runb, y) || t1;
        }
    } else {
        raw_op(runb, op, a, b, c, rnd, &tunb);
    }

    if (mpfr_nan_p(runb) && !nan_in)
        fl |= CFT_FLAG_INVALID;

    inexact = (tunb != 0);

    if (mpfr_nan_p(runb) || mpfr_inf_p(runb) || mpfr_zero_p(runb)) {
        mpfr_set(out, runb, MPFR_RNDN);
        if (inexact) fl |= CFT_FLAG_INEXACT;
        *flags = fl;
        goto fo_done;
    }

    {
        mpfr_exp_t e_unb = mpfr_get_exp(runb);
        long e_res = (long)e_unb - 1;

        if (e_res > fd->emax) {
            int away = (rnd == MPFR_RNDU && mpfr_sgn(runb) > 0) ||
                       (rnd == MPFR_RNDD && mpfr_sgn(runb) < 0) ||
                       rnd == MPFR_RNDN || is_rmm;
            if (rnd == MPFR_RNDZ) away = 0;
            if (away)
                mpfr_set_inf(out, mpfr_sgn(runb));
            else {
                mpfr_set_ui_2exp(out, 1, fd->emax + 1, MPFR_RNDN);
                mpfr_nextbelow(out);
                if (mpfr_sgn(runb) < 0) mpfr_neg(out, out, MPFR_RNDN);
            }
            *flags = fl | CFT_FLAG_OVERFLOW | CFT_FLAG_INEXACT;
            goto fo_done;
        }

        if (e_res >= fd->emin) {
            mpfr_set(out, runb, MPFR_RNDN);
            if (inexact) fl |= CFT_FLAG_INEXACT;
            *flags = fl;
            goto fo_done;
        }

        /* SUBNORMAL LANDING, and this is the one place fo_oracle does
         * NOT follow oracle()'s body - it cannot, and finding out why
         * cost a gate.
         *
         * oracle() uses the MPFR manual's IEEE recipe here: set emin to
         * emin - p + 2, redo the operation at the format's precision,
         * then mpfr_check_range + mpfr_subnormalize with the ternary.
         * That recipe assumes the operation's own result lands at or
         * above the least subnormal's exponent, so that the ternary it
         * hands subnormalize still describes the rounding. In a
         * SAME-format addition it always does: both operands are
         * multiples of the format's smallest quantum, so a non-zero
         * exact sum is at least that quantum, which is twice the
         * half-way point below the least subnormal. Across formats it
         * does not. binary64's 2^-968 added to -2^-150 is a hair over
         * half of binary32's least subnormal; the recipe's mpfr_add
         * underflows against the very emin that was set for it, flushes,
         * and the ternary stops carrying the hair. The result comes back
         * -0 where round-to-nearest says -2^-149, on eight cases in this
         * campaign, and the harness blamed the library.
         *
         * So the destination's subnormal grid is rounded onto EXPLICITLY,
         * for all five attributes, by the construction the RMM branch of
         * this file already used and c5_round_into documents: truncate
         * the exact result to p + 2 bits toward zero with the exponent
         * range left alone (the ternary is then a faithful sticky),
         * scale onto the grid, split into an integer and a fraction with
         * exact arithmetic, and compare that fraction with one half.
         *
         * The truncation cannot move the decision: the fraction is a
         * multiple of a granule no larger than 2^-2 of a grid unit and
         * the truncation error is below one granule, so a fraction under
         * one half stays under it, and a fraction exactly at one half
         * with a non-zero sticky is strictly above it. Every step is
         * MPFR's or GMP's; the only thing this file contributes is
         * clause 4.3's decision table, which is what an oracle for a
         * rounding has to contribute.
         *
         * Tininess is already settled: this branch was reached because
         * the UNBOUNDED p-bit rounding fell below emin, which is 7.5's
         * after-rounding test, so underflow rides with inexact even when
         * the grid rounding carries up to the least normal. */
        {
            int t1, up, sign, at_half, above_half, lost;
            long grid = fd->emin - fd->man_w;
            mpz_t n;
            mpfr_t scaled, frac, half;

            raw_op(y, op, a, b, c, MPFR_RNDZ, &t1);
            sign = mpfr_signbit(y) ? 1 : 0;
            mpz_init(n);
            mpfr_init2(scaled, fd->p + 8);
            mpfr_init2(frac, fd->p + 8);
            mpfr_init2(half, 8);
            mpfr_abs(scaled, y, MPFR_RNDN);
            mpfr_mul_2si(scaled, scaled, -grid, MPFR_RNDN);   /* exact */
            mpfr_get_z(n, scaled, MPFR_RNDZ);                 /* floor */
            mpfr_sub_z(frac, scaled, n, MPFR_RNDN);           /* exact */
            mpfr_set_ui_2exp(half, 1, -1, MPFR_RNDN);
            at_half = (mpfr_cmp(frac, half) == 0);
            above_half = (mpfr_cmp(frac, half) > 0);
            lost = (!mpfr_zero_p(frac) || t1 != 0);

            switch (MODES[mi].cr) {
            case CFT_RTZ:
                up = 0;
                break;
            case CFT_RDN:
                up = sign && lost;
                break;
            case CFT_RUP:
                up = !sign && lost;
                break;
            case CFT_RMM:
                up = above_half || at_half;
                break;
            default:            /* CFT_RNE */
                up = above_half ||
                     (at_half && (t1 != 0 || mpz_odd_p(n)));
                break;
            }
            if (up)
                mpz_add_ui(n, n, 1);
            mpfr_set_prec(out, fd->p);
            mpfr_set_z_2exp(out, n, grid, MPFR_RNDN);         /* exact */
            if (sign)
                mpfr_neg(out, out, MPFR_RNDN);
            if (lost || inexact)
                fl |= CFT_FLAG_INEXACT | CFT_FLAG_UNDERFLOW;
            mpz_clear(n);
            mpfr_clear(scaled); mpfr_clear(frac); mpfr_clear(half);
            *flags = fl;
        }
        goto fo_done;
    }

fo_done:
    mpfr_clear(a); mpfr_clear(b); mpfr_clear(c);
    mpfr_clear(runb); mpfr_clear(r); mpfr_clear(y);
}

/* The library side. `op` is the same mop the oracle took. */
static cft_status fo_lib(const fdesc *fs, const fdesc *fd, mop op,
                         cft_round rnd, const uint8_t *a, const uint8_t *b,
                         const uint8_t *c, uint8_t *d, uint32_t *fl)
{
    switch (op) {
    case OP_ADD:  return cft_formatof_add(dev, fs->fmt, fd->fmt, rnd,
                                          a, c, d, 1, fl, NULL);
    case OP_SUB:  return cft_formatof_sub(dev, fs->fmt, fd->fmt, rnd,
                                          a, c, d, 1, fl, NULL);
    case OP_MUL:  return cft_formatof_mul(dev, fs->fmt, fd->fmt, rnd,
                                          a, b, d, 1, fl, NULL);
    case OP_FMA:  return cft_formatof_fma(dev, fs->fmt, fd->fmt, rnd,
                                          a, b, c, d, 1, fl, NULL);
    case OP_DIV:  return cft_formatof_div(dev, fs->fmt, fd->fmt, rnd,
                                          a, b, d, 1, fl, NULL);
    default:      return cft_formatof_sqrt(dev, fs->fmt, fd->fmt, rnd,
                                           a, d, 1, fl, NULL);
    }
}

/* An exact value into a source encoding, or 0 if the source cannot hold
 * it. mpfr_to_enc wants a value already at the format's precision, so
 * the caller's variable is set at that precision and the ternary says
 * whether anything was lost. */
static int fo_exact_enc(const fdesc *fs, mpfr_srcptr v, uint8_t *b)
{
    mpfr_t t;
    int tern, ok;
    mpfr_init2(t, fs->p);
    tern = mpfr_set(t, v, MPFR_RNDN);
    ok = (tern == 0) && mpfr_to_enc(fs, t, b);
    mpfr_clear(t);
    return ok;
}

/* The three double-rounding witnesses for (fs -> fd), built from the
 * descriptors. `which`: 0 fma, 1 div, 2 sqrt. Returns 1 when the pair
 * has one - which is exactly when fd is strictly narrower.
 *
 * Each puts the exact result a hair ABOVE a midpoint of the DESTINATION
 * grid and closer to it than half an ulp of the SOURCE, so a first
 * rounding into the source lands on the midpoint and the second ties to
 * even, downward, while the single correct rounding goes up. */
static int fo_witness(const fdesc *fs, const fdesc *fd, int which,
                      uint8_t *ba, uint8_t *bb, uint8_t *bc)
{
    long ps = fs->p, pd = fd->p;
    mpz_t M, Y, T;
    mpfr_t v;
    int ok = 0;

    if (pd >= ps)
        return 0;
    memset(ba, 0, 32); memset(bb, 0, 32); memset(bc, 0, 32);
    mpz_init(M); mpz_init(Y); mpz_init(T);
    mpfr_init2(v, (mpfr_prec_t)(2 * ps + 8));

    mpz_ui_pow_ui(M, 2, (unsigned long)pd);
    mpz_add_ui(M, M, 1);                       /* M = 2^pd + 1, odd */

    if (which == 0) {
        /* a = M * 2^-pd is the destination midpoint just above 1 and a
         * source value; b = 1; c = the source's least subnormal, which
         * is positive and far below the source's own half-ulp at 1. */
        mpfr_set_z_2exp(v, M, -pd, MPFR_RNDN);
        if (!fo_exact_enc(fs, v, ba))
            goto done;
        mpfr_set_ui(v, 1, MPFR_RNDN);
        if (!fo_exact_enc(fs, v, bb))
            goto done;
        bc[0] = 1;                             /* 2^(emin - man_w) */
        ok = 1;
        goto done;
    }

    if (which == 1) {
        /* Y = 2^(ps-1) + 2^(ps-pd) - 1 satisfies Y == -1 (mod 2^pd), so
         * M*Y is one unit short of a multiple of the source grid at
         * weight 2^(1-pd-ps); the dividend is that product plus one
         * unit, and x/y is the midpoint plus one unit over y. */
        mpz_ui_pow_ui(Y, 2, (unsigned long)(ps - 1));
        mpz_ui_pow_ui(T, 2, (unsigned long)(ps - pd));
        mpz_add(Y, Y, T);
        mpz_sub_ui(Y, Y, 1);
        mpfr_set_z_2exp(v, Y, 1 - ps, MPFR_RNDN);
        if (!fo_exact_enc(fs, v, bb))
            goto done;
        mpz_mul(T, M, Y);
        mpz_add_ui(T, T, 1);
        mpfr_set_z_2exp(v, T, 1 - pd - ps, MPFR_RNDN);
        if (!fo_exact_enc(fs, v, ba))
            goto done;
        ok = 1;
        goto done;
    }

    /* which == 2: the square of the midpoint needs 2*pd + 1 bits, which
     * every ordered pair of this ladder holds; the source value one ulp
     * above it has a root a quarter of a source ulp above the midpoint. */
    if (2 * pd + 1 > ps)
        goto done;
    mpz_mul(T, M, M);
    mpfr_set_z_2exp(v, T, -2 * pd, MPFR_RNDN);
    if (!fo_exact_enc(fs, v, ba))
        goto done;
    enc_inc(ba, fs->esz);
    ok = 1;

done:
    mpz_clear(M); mpz_clear(Y); mpz_clear(T);
    mpfr_clear(v);
    return ok;
}

/* The second operand an operation actually reads, for the report. The
 * steering behind cft.h's opcodes makes add and sub read a and c while
 * mul and div read a and b, so a report that always printed b would
 * name a value the failing case never looked at. */
static const uint8_t *fo_second(mop op, const uint8_t *b, const uint8_t *c)
{
    if (op == OP_SQRT)
        return 0;
    if (op == OP_ADD || op == OP_SUB)
        return c;
    return b;
}

static const mop FO_OPS[6] = { OP_ADD, OP_SUB, OP_MUL, OP_DIV, OP_SQRT,
                               OP_FMA };
static const int FO_TALLY[6] = { T_FO_ADD, T_FO_SUB, T_FO_MUL, T_FO_DIV,
                                 T_FO_SQRT, T_FO_FMA };

static void check_formatof(int sfi, int dfi, uint8_t pool[][32], int pn)
{
    const fdesc *fs = &FMTS[sfi], *fd = &FMTS[dfi];
    uint8_t extra[64][32];
    uint8_t d[32];
    int ne = 0, i, oi, mi;
    char note[24];
    mpfr_t v;

    snprintf(note, sizeof note, "->%s", fd->name);
    mpfr_init2(v, (mpfr_prec_t)(fd->p + 4));

    /* The DESTINATION's landmarks, expressed in the source. Every one
     * of them is an unremarkable source value and a decision in the
     * destination, which is the class of case a same-format pool
     * cannot contain. */
    {
        long marks[4];
        int k, nm = 0;
        marks[nm++] = fd->emin - fd->man_w;         /* least subnormal */
        marks[nm++] = fd->emin - fd->man_w - 1;     /* half of it: a tie */
        marks[nm++] = fd->emin;                     /* least normal */
        marks[nm++] = fd->emin - fd->man_w / 2;     /* mid-subnormal */
        for (k = 0; k < nm && ne < 60; k++) {
            mpfr_set_ui_2exp(v, 1, marks[k], MPFR_RNDN);
            if (!fo_exact_enc(fs, v, extra[ne]))
                continue;
            memcpy(extra[ne + 1], extra[ne], 32);
            enc_neg(fs, extra[ne + 1]);
            ne += 2;
        }
    }
    if (ne < 58) {
        /* the largest finite of the destination, and the overflow
         * midpoint above it - 7.4's threshold, invisible from here */
        mpfr_set_ui_2exp(v, 1, fd->emax + 1, MPFR_RNDN);
        mpfr_nextbelow(v);                          /* maxfinite(fd) */
        if (fo_exact_enc(fs, v, extra[ne])) {
            memcpy(extra[ne + 1], extra[ne], 32);
            enc_neg(fs, extra[ne + 1]);
            ne += 2;
        }
        {
            mpfr_t w;
            mpfr_init2(w, (mpfr_prec_t)(fd->p + 1));
            mpfr_set_ui_2exp(w, 1, fd->emax + 1, MPFR_RNDN);
            mpfr_nextbelow(w);                      /* the midpoint */
            if (ne < 58 && fo_exact_enc(fs, w, extra[ne])) {
                memcpy(extra[ne + 1], extra[ne], 32);
                enc_neg(fs, extra[ne + 1]);
                ne += 2;
            }
            mpfr_clear(w);
        }
    }
    if (fs->p > fd->p) {
        /* destination midpoints, with a source-grid neighbour either
         * side - the only place a rounding written against the wrong
         * descriptor can be caught */
        long Es[3];
        int k, nE = 0;
        Es[nE++] = 0;
        Es[nE++] = fd->emax;
        Es[nE++] = fd->emin;
        for (k = 0; k < nE && ne < 58; k++) {
            mpfr_t w;
            mpfr_init2(w, (mpfr_prec_t)(fd->p + 1));
            mpfr_set_ui_2exp(w, 1, Es[k] + 1, MPFR_RNDN);
            mpfr_nextbelow(w);          /* 2^(E+1) - ulp_d/2: a midpoint */
            if (fo_exact_enc(fs, w, extra[ne])) {
                memcpy(extra[ne + 1], extra[ne], 32);
                enc_inc(extra[ne + 1], fs->esz);
                memcpy(extra[ne + 2], extra[ne], 32);
                enc_dec(extra[ne + 2], fs->esz);
                ne += 3;
            }
            mpfr_clear(w);
        }
    }
    mpfr_clear(v);

    for (oi = 0; oi < 6; oi++) {
        mop op = FO_OPS[oi];
        for (mi = 0; mi < 5; mi++)
            for (i = 0; i < pn + ne; i++) {
                const uint8_t *a = i < pn ? pool[i] : extra[i - pn];
                int jb = (i * 7 + 1) % (pn + ne);
                int jc = (i * 13 + 5) % (pn + ne);
                const uint8_t *b = jb < pn ? pool[jb] : extra[jb - pn];
                const uint8_t *c = jc < pn ? pool[jc] : extra[jc - pn];
                uint32_t gf = 0, wf = 0;
                mpfr_t want;
                cft_status st;

                mpfr_init2(want, fd->p);
                fo_oracle(fs, fd, op, mi, a, b, c, want, &wf);
                memset(d, 0, sizeof d);
                st = fo_lib(fs, fd, op, MODES[mi].cr, a, b, c, d, &gf);
                /* Report the operands the OPERATION READ, not the pool
                 * slots: the steering makes add and sub read a and c,
                 * so printing b there names a value the case never
                 * touched - which cost an hour once. */
                c5_judge(FO_TALLY[oi], sfi, OPN[op], MODES[mi].name,
                         fs, a, fo_second(op, b, c), fd, d, want,
                         gf, wf, st, note);
                mpfr_clear(want);
            }
    }

    /* The witnesses, in every attribute: the cases a source-format
     * rounding would get wrong. */
    if (fd->p < fs->p) {
        int w;
        for (w = 0; w < 3; w++) {
            uint8_t wa[32], wb[32], wc[32];
            mop op = (w == 0) ? OP_FMA : (w == 1) ? OP_DIV : OP_SQRT;
            int ti = (w == 0) ? T_FO_FMA : (w == 1) ? T_FO_DIV : T_FO_SQRT;
            if (!fo_witness(fs, fd, w, wa, wb, wc))
                continue;
            for (mi = 0; mi < 5; mi++) {
                uint32_t gf = 0, wf = 0;
                mpfr_t want;
                cft_status st;
                mpfr_init2(want, fd->p);
                fo_oracle(fs, fd, op, mi, wa, wb, wc, want, &wf);
                memset(d, 0, sizeof d);
                st = fo_lib(fs, fd, op, MODES[mi].cr, wa, wb, wc, d, &gf);
                c5_judge(ti, sfi, OPN[op], MODES[mi].name, fs, wa,
                         fo_second(op, wb, wc), fd, d, want, gf, wf,
                         st, "double-rounding witness");
                mpfr_clear(want);
            }
        }
    }
}

/* ---- driver -------------------------------------------------------- */

static void report(const fdesc *f, mop op, int mi, const uint8_t *a,
                   const uint8_t *b, const uint8_t *c,
                   const uint8_t *got, const mpfr_t want,
                   uint32_t gf, uint32_t wf, int value_bad)
{
    char ha[65], hb[65], hc[65], hg[65];
    if (shown >= 16) return;
    shown++;
    hexdump(a, f->esz, ha); hexdump(b, f->esz, hb);
    hexdump(c, f->esz, hc); hexdump(got, f->esz, hg);
    printf("  %s %s %s %s a=0x%s b=0x%s c=0x%s\n", value_bad ?
           "MISMATCH" : "FLAGS", f->name, OPN[op], MODES[mi].name,
           ha, hb, hc);
    printf("    lib=0x%s flags=0x%02x  mpfr=", hg, (unsigned)gf);
    mpfr_out_str(stdout, 16, 0, want, MPFR_RNDN);
    printf(" flags=0x%02x\n", (unsigned)wf);
}

/* ---- the coverage, pinned (OPS send-back 1, 2026-11-02) ------------- *
 *
 * The mismatch counters fail a run. Nothing failed it when a phase asked
 * FEWER cases than it should - a family dropped, a format skipped, a pool
 * shortened - and a count line that cannot fail is a check that cannot
 * fail: with the extras of fp256 skipped, a run once printed TOTAL
 * 380,370 and exited 0, 126,720 cases short. That silent not-asking is
 * what issue 1 was. So the cases the extras ask are pinned:
 *
 *   XPIN         per family and format;
 *   XPIN_FORMAT  per format (the sum of the family column);
 *   PIN_TOTAL    the whole run's TOTAL, for a run with no subset.
 *
 * All three are the counts of `mpfr-check 24 7`, the verification stage's
 * arguments, because the pools hold the randoms those arguments draw and
 * the extras skip what the pools hold. With other arguments nothing is
 * checked and the run says so. A pin is checked wherever the run chose
 * what it counts: a format's extras when that format's extras ran (a
 * CFT_MPFR_FORMATS or CFT_MPFR_PHASES subset checks what it ran), the
 * total only when neither variable is set. A difference prints a line
 * that names the phase, the format (and the family), the count found and
 * the count wanted, and the run exits 1.
 *
 * WHOEVER CHANGES A POOL, A FAMILY OR THE EXTRAS' DEDUPE UPDATES THESE
 * PINS IN THE SAME COMMIT. The new numbers are the cases column of the
 * table this tool prints at the end of a run; host/tools/audit-pools/
 * pins.py reads them off a run and prints the rows below, and with
 * --check says which of them a run disagrees with. A pin that has to move
 * is a change in what the oracle asks: say why in the commit.
 *
 * The counts do not depend on the width of the host's long as far as it
 * has been measured: the two places that read a long wider than 32 bits
 * (xedge_pair's integer neighbours and the power-edge family) were
 * counted at fp32, fp64, fp128 and fp256 on the desktop, whose long is
 * 32 bits, and neither met a value past 2^31 in this run. */

typedef struct {
    const char *name;
    uint64_t cases[4];                   /* fp32, fp64, fp128, fp256 */
} xpin_t;

static const xpin_t XPIN[] = {
    { "x:io",                    { 455, 455, 455, 455 } },
    { "x:ints",                  { 1575, 1645, 1645, 1645 } },
    { "x:int-edge",              { 1750, 1680, 1750, 1750 } },
    { "x:pow2",                  { 35, 35, 35, 35 } },
    { "x:pow2-sub",              { 490, 490, 490, 490 } },
    { "x:pow10",                 { 350, 770, 3290, 8960 } },
    { "x:ln2-edge",              { 3500, 3500, 3500, 3500 } },
    { "x:tiny",                  { 490, 490, 490, 490 } },
    { "x:tiny-edge",             { 1610, 1610, 1610, 1610 } },
    { "t:io",                    { 540, 540, 540, 540 } },
    { "t:units",                 { 180, 180, 180, 180 } },
    { "t:halves",                { 630, 630, 630, 630 } },
    { "t:quarters",              { 945, 945, 945, 945 } },
    { "t:ints",                  { 495, 495, 495, 495 } },
    { "t:eighths",               { 1620, 1620, 1620, 1620 } },
    { "t:top",                   { 1260, 1260, 1260, 1260 } },
    { "t:tiny",                  { 405, 405, 405, 405 } },
    { "t:tiny-edge",             { 1620, 1710, 1710, 1710 } },
    { "t:beside-half",           { 3240, 3240, 3240, 3240 } },
    { "r:io",                    { 165, 165, 165, 165 } },
    { "r:pow2-sweep",            { 7500, 62130, 2880, 2880 } },
    { "r:pow2-near",             { 330, 330, 360, 360 } },
    { "r:tiny",                  { 105, 105, 105, 105 } },
    { "r:tiny-edge",             { 540, 540, 720, 720 } },
    { "r:worst",                 { 360, 360, 210, 270 } },
    { "h:io",                    { 330, 330, 330, 330 } },
    { "h:small",                 { 2460, 2460, 2460, 2460 } },
    { "h:ln2-edge",              { 1260, 1260, 1260, 1260 } },
    { "h:tanh-edge",             { 240, 240, 270, 270 } },
    { "h:tiny",                  { 240, 240, 240, 240 } },
    { "h:tiny-edge",             { 1380, 1440, 1440, 1440 } },
    { "m:io",                    { 330, 330, 330, 330 } },
    { "m:ints",                  { 2760, 2700, 2760, 2760 } },
    { "m:int-edge",              { 720, 720, 720, 720 } },
    { "m:pow10",                 { 270, 630, 2790, 7650 } },
    { "m:10^k-1",                { 480, 1260, 2910, 6270 } },
    { "m:2^k-1",                 { 7350, 13470, 13470, 13470 } },
    { "m:pow2",                  { 1770, 1830, 1830, 1830 } },
    { "m:tiny",                  { 210, 210, 210, 210 } },
    { "m:tiny-edge",             { 1080, 1140, 1140, 1140 } },
    { "m:log2p1-edge",           { 420, 450, 450, 450 } },
    { "m:log10-edge",            { 2700, 2700, 2700, 2700 } },
    { "pow:specials",            { 1155, 1155, 1175, 1175 } },
    { "pow:int-exp",             { 780, 780, 780, 780 } },
    { "pow:dyadic-exp",          { 960, 960, 960, 960 } },
    { "pow:dyadic-wide",         { 230, 270, 270, 255 } },
    { "pow:near1",               { 1400, 1390, 1400, 1400 } },
    { "pow:cancel",              { 530, 530, 530, 530 } },
    { "pow:edge",                { 1620, 1620, 1620, 1620 } },
    { "powr:specials",           { 1235, 1235, 1255, 1255 } },
    { "powr:int-exp",            { 770, 770, 770, 770 } },
    { "powr:dyadic-wide",        { 230, 270, 270, 255 } },
    { "powr:edge",               { 1620, 1620, 1620, 1620 } },
    { "hypot:triples",           { 460, 460, 460, 460 } },
    { "hypot:dominance",         { 130, 130, 130, 130 } },
    { "hypot:extremes",          { 30, 30, 30, 30 } },
    { "hypot:wide-triples",      { 75, 75, 75, 75 } },
    { "hypot:exact-top",         { 120, 120, 120, 120 } },
    { "atan2:axes",              { 2050, 2050, 2050, 2050 } },
    { "atan2:diagonals",         { 1050, 1050, 1050, 1050 } },
    { "atan2:sub-quotient",      { 10, 10, 10, 10 } },
    { "atan2:tiny-over-unit",    { 460, 460, 460, 460 } },
    { "atan2:big-small",         { 220, 220, 220, 220 } },
    { "int:vector-pairs",        { 29685, 29715, 29640, 29715 } },
    { "int:specials",            { 975, 975, 975, 975 } },
    { "int:exact-edge",          { 710, 785, 795, 800 } },
    { "int:perfect-power",       { 890, 1385, 1385, 1385 } },
    { "int:subnormal-recip",     { 270, 270, 270, 270 } },
    { "int:power-edge",          { 360, 360, 360, 360 } },
};
static const uint64_t XPIN_FORMAT[4] = { 102215, 165435, 112720, 126720 };
#define PIN_TOTAL 1366964ull

static int pin_fail;
static uint64_t pin_seed;               /* rs as main was given it: rs
                                         itself is the generator's state */

static void pin_say(const char *phase, const char *format,
                    const char *family, uint64_t found, uint64_t wanted)
{
    pin_fail = 1;
    printf("PIN FAILED %s %s%s%s: %llu cases found, %llu wanted\n", phase,
           format, family ? " " : "", family ? family : "",
           (unsigned long long)found, (unsigned long long)wanted);
}

static int env_set(const char *var)
{
    const char *v = getenv(var);
    return v && *v;
}

/* Compare the run with the pins. Called once, after the last phase and
 * before the TOTAL line; sets pin_fail, which main folds into its exit
 * status. */
static void pins_check(int randoms)
{
    const int nfam = (int)(sizeof XPIN / sizeof XPIN[0]);
    int fi, k, t, checked = 0, listed;

    if (randoms != 24 || pin_seed != 7) {
        printf("pins: not checked (the pinned counts are those of "
               "mpfr-check 24 7)\n");
        return;
    }
    for (fi = 0; fi < 4; fi++) {
        const fdesc *f = &FMTS[fi];
        uint64_t found = 0;

        if (!format_on(f) || !phase_on("extras"))
            continue;
        checked++;
        listed = 0;
        for (t = 0; t < xfam_n; t++)
            found += xfam_cases[t][fi];
        if (found != XPIN_FORMAT[fi])
            pin_say("extras", f->name, NULL, found, XPIN_FORMAT[fi]);
        for (k = 0; k < nfam; k++) {
            uint64_t have = 0;
            for (t = 0; t < xfam_n; t++)
                if (!strcmp(xfam_name[t], XPIN[k].name))
                    have = xfam_cases[t][fi];
            if (have != XPIN[k].cases[fi] && listed++ < 12)
                pin_say("extras", f->name, XPIN[k].name, have,
                        XPIN[k].cases[fi]);
        }
        for (t = 0; t < xfam_n; t++) {   /* a family the pins do not know */
            int known = 0;
            for (k = 0; k < nfam; k++)
                if (!strcmp(xfam_name[t], XPIN[k].name))
                    known = 1;
            if (!known && xfam_cases[t][fi] && listed++ < 12)
                pin_say("extras", f->name, xfam_name[t],
                        xfam_cases[t][fi], 0);
        }
        if (listed > 12)
            printf("PIN FAILED extras %s: and %d more families\n", f->name,
                   listed - 12);
    }
    if (!env_set("CFT_MPFR_PHASES") && !env_set("CFT_MPFR_FORMATS")) {
        if (cases != PIN_TOTAL)
            pin_say("total", "(all phases and formats)", NULL, cases,
                    PIN_TOTAL);
        else if (!pin_fail)
            printf("pins held: extras at every format (%d families), "
                   "total %llu\n", nfam, (unsigned long long)PIN_TOTAL);
    } else if (checked) {
        if (!pin_fail)
            printf("pins held: extras at %d format%s (%d families); "
                   "total not checked, a subset ran\n", checked,
                   checked == 1 ? "" : "s", nfam);
    } else {
        printf("pins: the extras did not run, nothing to check\n");
    }
}

int main(int argc, char **argv)
{
    int randoms = argc > 1 ? atoi(argv[1]) : 24;
    rs = argc > 2 ? strtoull(argv[2], NULL, 0) | 1 : 0x5EEDF00Dull;
    pin_seed = rs;
    static uint8_t pool[MAXPOOL][32];
    static uint8_t base[MAXPOOL][32];    /* a format's own specials */
    static uint8_t tpool[TPOOL_MAX][32];
    static uint8_t gpool[TRIGPOOL_MAX][32];
    static uint8_t hpool[P3POOL_MAX][32];
    int fi, oi, mi, i, j;

    if (cft_open(NULL, 0, &dev) != CFT_OK) {
        fprintf(stderr, "cft_open failed\n");
        return 2;
    }
    printf("MPFR %s as oracle\n", mpfr_get_version());
    dump_cases = env_set("CFT_MPFR_DUMP_CASES");

    for (fi = 0; fi < 4; fi++) {
        const fdesc *f = &FMTS[fi];
        int pn;
        uint64_t fmt_cases = 0;

        if (!phase_on("arith") || !format_on(f))
            continue;
        pn = build_pool(f, pool, randoms);

        for (oi = 0; oi < NOPS; oi++) {
            int nargs = OP_NARGS[oi];
            for (mi = 0; mi < 5; mi++) {
                for (i = 0; i < pn; i++) {
                    int jmax = nargs >= 2 ? pn : 1;
                    for (j = 0; j < jmax; j++) {
                        const uint8_t *a = pool[i];
                        const uint8_t *b = pool[j];
                        const uint8_t *c = pool[(i + j) % pn];
                        uint8_t d[32];
                        uint32_t gf, wf;
                        mpfr_t want;
                        int vbad, fbad;

                        mpfr_init2(want, f->p);
                        oracle(f, (mop)oi, mi, a, b, c, want, &wf);
                        gf = lib_flags(f, (mop)oi, MODES[mi].cr,
                                       a, b, c, d);
                        vbad = !agree(f, d, want);
                        fbad = (gf != wf);
                        if (vbad) mismatches++;
                        if (fbad) flag_mismatches++;
                        if (vbad || fbad)
                            report(f, (mop)oi, mi, a, b, c, d, want,
                                   gf, wf, vbad);
                        mpfr_clear(want);
                        cases++; fmt_cases++;
                        tally[oi][fi]++;
                    }
                }
            }
        }
        printf("%s: %llu cases done (running mismatches: %llu value, "
               "%llu flag)\n", f->name,
               (unsigned long long)fmt_cases,
               (unsigned long long)mismatches,
               (unsigned long long)flag_mismatches);
        fflush(stdout);
    }

    /* The clause-5 completion set. Fresh pools (the rng has moved on,
     * so these randoms differ from the arithmetic phase's), and the
     * wide rungs get double the random weight: fp128/fp256 are the
     * formats only MPFR can arbitrate. */
    for (fi = 0; fi < 4; fi++) {
        const fdesc *f = &FMTS[fi];
        int pn, mult = fi >= 2 ? 2 : 1;
        uint64_t before = cases;

        if (!phase_on("clause5") || !format_on(f))
            continue;
        pn = build_pool(f, pool, randoms);
        check_rint(fi, pool, pn);
        check_scaleb(fi, pool, pn);
        check_cvt_from(fi, 24 * mult);
        check_cvt_to(fi, pool, pn, 24 * mult);
        check_logb(fi, pool, pn, 24 * mult);
        check_next(fi, pool, pn);
        check_rem(fi, pool, pn, 48 * mult);
        check_chars(fi, pool, pn, 48 * mult);
        check_augmented(fi, pool, pn);
        check_minmax_mag(fi, pool, pn);
        check_minmax_mag_ties(fi, pool, pn);
        printf("%s clause5+9.5+9.6: %llu cases done (running mismatches: "
               "%llu value, %llu flag)\n", f->name,
               (unsigned long long)(cases - before),
               (unsigned long long)mismatches,
               (unsigned long long)flag_mismatches);
        fflush(stdout);
    }
    /* The phase-1 transcendentals. Their own pools, because the
     * families that matter here - exact cases, thresholds, a base one
     * ulp from 1 - are not the families that matter for an FMA. */
    /* build_trigpool and build_p3pool take the first eighteen entries of
     * their pools from the array they are handed: the format's specials.
     * Until 2026-11-02 what they were handed was `pool` as the clause-5
     * loop had left it - fp256's eighteen, for every format - and tpool's
     * count (208) where the array's own is eighteen. At fp256 that was
     * right. At fp32, fp64 and fp128 the "specials" were fp256 encodings
     * read through a narrower format - at fp32 +0 twelve times,
     * 0x00000001 three times and 0xffffffff three times - and the twenty
     * functions of those two pools never met -0, an infinity, the
     * canonical quiet NaN or a signaling one, the largest subnormal or
     * the largest normal (the trigonometric pool also lacked the
     * smallest normal, the third 3 and -3). The audit of that day found
     * it (issue 1's kind of defect: the wrong array handed to a check),
     * and each format now builds its own eighteen, without a random draw
     * - so every draw of the run is where it was and the pools keep
     * their sizes - and hands them with their own count. A subset run,
     * or the case dump, which skips the clause-5 loop, gets the same
     * pools a full run does. `pool` is not read in this loop any more:
     * the loops below each rebuild it before they use it. */
    for (fi = 0; fi < 4; fi++) {
        const fdesc *f = &FMTS[fi];
        int pn, gn, hn, bn;
        uint64_t before;

        if (!format_on(f) ||
            !(phase_on("transcend") || phase_on("trig") ||
              phase_on("radian") || phase_on("table91") ||
              phase_on("extras")))
            continue;
        bn = build_pool(f, base, 0);
        pn = build_tpool(f, tpool, randoms);
        gn = build_trigpool(f, gpool, (const uint8_t (*)[32])base,
                            bn, randoms);
        hn = build_p3pool(f, hpool, (const uint8_t (*)[32])base,
                          bn, randoms);
        before = cases;
        if (phase_on("transcend")) {
            check_transcend(fi, tpool, pn, gpool, gn, hpool, hn, 0,
                            TF_SINPI);
            if (!dump_cases)
                printf("%s transcend: %llu cases done (running "
                       "mismatches: %llu value, %llu flag)\n", f->name,
                       (unsigned long long)(cases - before),
                       (unsigned long long)mismatches,
                       (unsigned long long)flag_mismatches);
        }
        before = cases;
        if (phase_on("trig")) {
            check_transcend(fi, tpool, pn, gpool, gn, hpool, hn,
                            TF_SINPI, TF_SIN);
            if (!dump_cases)
                printf("%s trig: %llu cases done (running mismatches: "
                       "%llu value, %llu flag)\n", f->name,
                       (unsigned long long)(cases - before),
                       (unsigned long long)mismatches,
                       (unsigned long long)flag_mismatches);
            fflush(stdout);
        }
        before = cases;
        if (phase_on("radian")) {
            check_transcend(fi, tpool, pn, gpool, gn, hpool, hn, TF_SIN,
                            TF_EXP2M1);
            if (!dump_cases)
                printf("%s radian+hyperbolic: %llu cases done (running "
                       "mismatches: %llu value, %llu flag)\n", f->name,
                       (unsigned long long)(cases - before),
                       (unsigned long long)mismatches,
                       (unsigned long long)flag_mismatches);
            fflush(stdout);
        }
        before = cases;
        if (phase_on("table91")) {
            check_transcend(fi, tpool, pn, gpool, gn, hpool, hn,
                            TF_EXP2M1, TF_COUNT);
            /* And again on the exponential pool, the one these ten were
             * written for. check_transcend calls its fourth argument
             * tpool, and here that is the trigonometric pool, so from
             * 2026-09-03 to 2026-10-30 the ten ran on it alone and never
             * saw an exp2 integer at the top of the range - where
             * exp2m1(emax + 1) raised overflow toward zero (issue 1).
             * The trigonometric pass above stays: it is coverage they
             * have had since. */
            check_transcend(fi, tpool, pn, tpool, pn, hpool, hn,
                            TF_EXP2M1, TF_COUNT);
            if (!dump_cases)
                printf("%s table91: %llu cases done (running mismatches: "
                       "%llu value, %llu flag)\n", f->name,
                       (unsigned long long)(cases - before),
                       (unsigned long long)mismatches,
                       (unsigned long long)flag_mismatches);
            fflush(stdout);
        }
        /* What the audit of 2026-11-02 found the pools above lacked. A
         * phase of its own, after the four, that draws no random number:
         * everything above runs exactly as it did, and these are the
         * cases it runs besides. */
        before = cases;
        if (phase_on("extras")) {
            check_extras(fi, tpool, pn, gpool, gn, hpool, hn);
            if (!dump_cases)
                printf("%s extras: %llu cases done (running mismatches: "
                       "%llu value, %llu flag)\n", f->name,
                       (unsigned long long)(cases - before),
                       (unsigned long long)mismatches,
                       (unsigned long long)flag_mismatches);
            fflush(stdout);
        }
    }

    /* The seven reductions. Their pools are the arithmetic phase's -
     * the specials are exactly what a reduction's edges turn on - and
     * the campaign reports NODES as well as cases, because a case here
     * is a whole vector and the node count is what MPFR actually
     * arbitrated. */
    if (dump_cases) {                    /* the dump ends with the table */
        cft_close(dev);
        return 0;
    }
    for (fi = 0; fi < 4; fi++) {
        const fdesc *f = &FMTS[fi];
        int pn;
        uint64_t before = cases, nodes_before = reduce_nodes;

        if (!phase_on("reduce") || !format_on(f))
            continue;
        pn = build_pool(f, pool, randoms);
        check_reduce(fi, pool, pn, 4);
        printf("%s reduce: %llu vectors done, %llu nodes arbitrated "
               "(running mismatches: %llu value, %llu flag)\n", f->name,
               (unsigned long long)(cases - before),
               (unsigned long long)(reduce_nodes - nodes_before),
               (unsigned long long)mismatches,
               (unsigned long long)flag_mismatches);
        fflush(stdout);
    }

    for (fi = 0; fi < 4; fi++) {
        int pn, dfi;
        uint64_t before = cases;

        if (!phase_on("convert") || !format_on(&FMTS[fi]))
            continue;
        pn = build_pool(&FMTS[fi], pool, randoms);
        for (dfi = 0; dfi < 4; dfi++)
            check_convert(fi, dfi, pool, pn);
        printf("%s convert: %llu cases done (running mismatches: "
               "%llu value, %llu flag)\n", FMTS[fi].name,
               (unsigned long long)(cases - before),
               (unsigned long long)mismatches,
               (unsigned long long)flag_mismatches);
        fflush(stdout);
    }

    /* The formatOf arithmetic of 5.4.1: every ordered pair of formats,
     * all six operations, all five attributes. MPFR is a FULL oracle
     * here - the clause's definition IS "the operands at the source
     * precision, the infinitely precise result rounded once to the
     * destination", which is exactly what mpfr_add and friends do when
     * the variables are declared that way - so nothing in this phase is
     * a restatement of a rule or a reproduction of a shape. */
    for (fi = 0; fi < 4; fi++) {
        int pn, dfi;

        if (!phase_on("formatof") || !format_on(&FMTS[fi]))
            continue;
        pn = build_pool(&FMTS[fi], pool, randoms);
        for (dfi = 0; dfi < 4; dfi++) {
            uint64_t before = cases;
            check_formatof(fi, dfi, pool, pn);
            printf("%s->%s formatOf: %llu cases done (running "
                   "mismatches: %llu value, %llu flag)\n",
                   FMTS[fi].name, FMTS[dfi].name,
                   (unsigned long long)(cases - before),
                   (unsigned long long)mismatches,
                   (unsigned long long)flag_mismatches);
            fflush(stdout);
        }
    }

    if (xfam_n) {
        int t, k;
        uint64_t tot = 0;
        printf("\nextras (audit of 2026-11-02), per family and format: "
               "intended - held by the pools = added / cases:\n");
        printf("  %-24s %18s %18s %18s %18s\n", "family", "fp32", "fp64",
               "fp128", "fp256");
        for (t = 0; t < xfam_n; t++) {
            int any = 0;
            for (k = 0; k < 4; k++)
                if (xfam_cases[t][k])
                    any = 1;
            if (!any)
                continue;
            printf("  %-24s", xfam_name[t]);
            for (k = 0; k < 4; k++) {
                printf(" %3llu-%3llu=%3llu/%-6llu",
                       (unsigned long long)xfam_intended[t][k],
                       (unsigned long long)xfam_held[t][k],
                       (unsigned long long)xfam_mem[t][k],
                       (unsigned long long)xfam_cases[t][k]);
                tot += xfam_cases[t][k];
            }
            printf("\n");
        }
        printf("  extras total: %llu cases\n", (unsigned long long)tot);
    }

    {
        int t, k;
        printf("\nper-op case counts (convert and formatOf by source "
               "format):\n");
        printf("  %-10s %12s %12s %12s %12s\n", "op", "fp32", "fp64",
               "fp128", "fp256");
        for (t = 0; t < NTALLY; t++) {
            printf("  %-10s", TALLY_NAME[t]);
            for (k = 0; k < 4; k++)
                printf(" %12llu", (unsigned long long)tally[t][k]);
            printf("\n");
        }
    }

    printf("\ntranscendental evaluator: %llu elements, %llu reached the "
           "Ziv loop,\n  %llu escalations, deepest working precision %llu "
           "bits, %llu decided exactly,\n  %llu decided by a neighbour's "
           "side\n",
           (unsigned long long)cft_tr_calls,
           (unsigned long long)cft_tr_ziv_calls,
           (unsigned long long)cft_tr_escalations,
           (unsigned long long)cft_tr_max_prec,
           (unsigned long long)cft_tr_exact,
           (unsigned long long)cft_tr_neighbour);

    printf("reduction against pi: %llu arguments reduced, %llu window "
           "widenings,\n  widest window %llu bits, deepest cancellation "
           "seen %llu bits (allowance %d)\n",
           (unsigned long long)cft_tr_reduce_calls,
           (unsigned long long)cft_tr_reduce_widen,
           (unsigned long long)cft_tr_max_window,
           (unsigned long long)cft_tr_max_cancel,
           CFT_TR_PH_WINDOW_MAX);

    printf("reductions: %llu tree nodes arbitrated by MPFR (the SHAPE of "
           "the tree\n  is this contract's choice and is reproduced by the "
           "harness, not judged\n  by it - 9.4 lets an implementation "
           "associate in any order)\n",
           (unsigned long long)reduce_nodes);

    pins_check(randoms);
    printf("TOTAL %llu cases, %llu value mismatches, %llu flag "
           "mismatches\n", (unsigned long long)cases,
           (unsigned long long)mismatches,
           (unsigned long long)flag_mismatches);
    cft_close(dev);
    mpfr_free_cache();
    return (mismatches || flag_mismatches || pin_fail) ? 1 : 0;
}
