/* Copyright 2026 Logan W.
 * SPDX-License-Identifier: Apache-2.0
 *
 * A small multiprecision FLOATING-point evaluator on the bigint core.
 * Internal to libcft; transcend.c is its only caller.
 *
 * ---------------------------------------------------------------
 * Why floating and not fixed point
 * ---------------------------------------------------------------
 *
 * Everything else this library computes fits in fixed point, because
 * every other result is a rounding of an exactly-known dyadic
 * rational: bigint.h's add/sub/mul/shift/compare are enough, and
 * softfloat.c never needs a second exponent. The transcendentals are
 * the first operations where that stops being true, and two input
 * families say so on their own:
 *
 *   pow(1 + 2^-236, 2^262000) at fp256. The logarithm of that base is
 *   about 2^-236 and the product with y is an ordinary number, so the
 *   answer is ordinary - but a fixed-point evaluator carrying W bits
 *   below the point would have to carry 236 + W of them to keep the
 *   base's logarithm to RELATIVE accuracy, and then multiply by an
 *   exponent with 262,000 bits of range above the point. The width is
 *   set by the exponent RANGE rather than by the precision, which is
 *   the definition of the wrong representation.
 *
 *   log1p(2^-262000). The result is about 2^-262000 and must be
 *   correct to p bits OF ITS OWN MAGNITUDE. A fixed-point word deep
 *   enough to hold it is a third of a megabit wide and almost all
 *   zeroes.
 *
 * So: a sign, an integer exponent, a W-bit significand in a cft_bn,
 * and an error bound carried with the value.
 *
 * ---------------------------------------------------------------
 * The error discipline
 * ---------------------------------------------------------------
 *
 * Every operation TRUNCATES toward zero and every operation carries
 * `err`, an upper bound on the RELATIVE distance from the true value
 * in units of 2^-W:
 *
 *     |true - value| <= err * 2^-W * |value|
 *
 * Relative, not in ulps, because relative error is additive through a
 * multiplication where an ulp count is not - mpfloat.c derives every
 * rule. Since the significand is normalised to exactly W bits, err
 * units of 2^-W relative are also at most err units in the
 * significand's last place, which is how cft_mp_round turns the bound
 * back into an enclosure: [m - err, m + err] * 2^exp.
 *
 * The bounds are deliberately loose - upper bounds, not estimates -
 * because of the property that makes the whole scheme sound: the bound
 * is CHECKED at the end. cft_mp_round rounds both ends of that
 * enclosure and accepts the result only if they agree on the bits AND
 * on the flags. A bound that is too generous costs an escalation to a
 * higher working precision; it can never produce a wrong answer. The
 * only bound that could is one that is too SMALL, which is why every
 * rule rounds up and why the saturating arithmetic saturates upward.
 *
 * A saturated error (CFT_MP_ERR_MAX) is therefore not an error
 * condition: it is a value whose enclosure is too wide to decide, and
 * the Ziv loop above will raise the precision and try again.
 */

#ifndef CFT_MPFLOAT_H
#define CFT_MPFLOAT_H

#include <stdint.h>

#include "bigint.h"
#include "softfloat.h"

/* The widest working significand. The binding constraint is the
 * 2048-bit bigint container: cft_mp_mul forms the full 2W-bit product
 * and cft_mp_div shifts the numerator left by W before dividing, so
 * 2W must fit with room to spare. 928 leaves 192 bits of headroom, and
 * is itself 832 (the Ziv cap, python/cft_golden/transcend.py) plus 32
 * bits of guard plus the 19 bits of argument-reduction headroom the
 * fp256 exponent range can demand. */
#define CFT_MP_PREC_MAX 928

/* An error bound this large cannot decide any rounding, so it is the
 * saturation point rather than a failure. Kept far below UINT64_MAX so
 * that the scaling in cft_mp_add cannot wrap. */
#define CFT_MP_ERR_MAX ((uint64_t)1 << 40)

typedef struct {
    int      sign;    /* 1 when negative */
    int      zero;    /* the value is exactly zero; m and exp unused */
    long     exp;     /* value = (-1)^sign * m * 2^exp */
    uint64_t err;     /* |true - value| <= err * 2^-W * |value| */
    cft_bn   m;       /* exactly W bits when !zero: bit W-1 set */
} cft_mp;

/* The generated constants (host/src/mp_consts.h), by index. */
typedef enum {
    CFT_MP_C_LN2 = 0,
    CFT_MP_C_LOG2E,
    CFT_MP_C_LN10,
    CFT_MP_C_LOG10E
} cft_mp_constant;

/* Every function below returns 0 on success and 1 if a bigint width
 * would have been exceeded - which is an internal invariant failure,
 * turned into CFT_ERR_INTERNAL by the caller rather than into a
 * truncated answer. */

void cft_mp_set_zero(cft_mp *r);
int  cft_mp_set_bn(cft_mp *r, int W, int sign, const cft_bn *m, long e);
int  cft_mp_set_ui(cft_mp *r, int W, int sign, uint32_t v, long e);
void cft_mp_copy(cft_mp *r, const cft_mp *a);
void cft_mp_neg(cft_mp *r);
void cft_mp_shift(cft_mp *r, long k);          /* exact multiply by 2^k */

int  cft_mp_mul(cft_mp *r, const cft_mp *a, const cft_mp *b, int W);
int  cft_mp_add(cft_mp *r, const cft_mp *a, const cft_mp *b, int W);
int  cft_mp_sub(cft_mp *r, const cft_mp *a, const cft_mp *b, int W);
int  cft_mp_div(cft_mp *r, const cft_mp *a, const cft_mp *b, int W);
int  cft_mp_mul_ui(cft_mp *r, const cft_mp *a, uint32_t u, int W);
int  cft_mp_div_ui(cft_mp *r, const cft_mp *a, uint32_t u, int W);
int  cft_mp_sqrt(cft_mp *r, const cft_mp *a, int W);
int  cft_mp_const(cft_mp *r, cft_mp_constant which, int W);

/* floor(sqrt(n)) with an exactness flag, for the exact-case tests in
 * transcend.c: the digit-by-digit integer root, verified by squaring
 * it back. */
int  cft_mp_isqrt(cft_bn *root, int *exact, const cft_bn *n);

/* The value truncated toward zero, saturated at +-2^40. */
int64_t cft_mp_trunc_to_int(const cft_mp *a);

/* floor(log2|value|) of the stored approximation, ignoring err. Only
 * meaningful for a non-zero value. */
long cft_mp_exp2_of(const cft_mp *a);

/* Compare the whole enclosure against an integer:
 *
 *   +1  every value in it is strictly greater than t
 *   -1  every value in it is strictly less than t
 *    0  it straddles t, or the error bound is too wide to tell
 *
 * The screens in transcend.c ask only whether a result is PROVABLY
 * past a format threshold, so a 0 is always safe - it falls through to
 * the ordinary evaluation. */
int cft_mp_cmp_int(const cft_mp *a, int64_t t);

/* Round the magnitude of `a` (with `sign` applied) into the format
 * under `rnd`.
 *
 * Returns 0 and sets *decided when the whole enclosure rounds one way,
 * 0 with *decided == 0 when it does not (the caller raises the working
 * precision), and 1 on an internal width failure. The delivered flags
 * are the ones round_pack derives - this is the library's single
 * rounding authority, so tininess, the overflow response table and the
 * underflow rule all come from the same place they do for add. */
int cft_mp_round(const cft_mp *a, int sign, const cft_fmt_desc *f, int rnd,
                 cft_bn *out, uint32_t *flags, int *decided);

/* Multiply ln2 by log2e and ln10 by log10e and require both products
 * to be 1 to within a few units in the last place. Returns 0 when the
 * generated header is intact. A constant that was truncated, byte
 * swapped or edited fails here rather than in the low bit of somebody's
 * exponential. */
int cft_mp_consts_selfcheck(void);

#endif /* CFT_MPFLOAT_H */
