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
 * in units of 2^-W, W being the value's own width, the bit length of
 * its significand:
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
 * The count has no ceiling. It is a cft_mp_err, a whole number of
 * units carried with its own exponent: exact below 2^63, and past that
 * rounded UP to 63 significant bits. So a bound of any size is carried
 * exactly or rounded up, and never replaced by a smaller one. The one
 * value above every finite count is infinity, which is a bound too -
 * it is above every true error - and which never decides.
 *
 * The bounds are deliberately loose - upper bounds, not estimates -
 * because of the property that makes the whole scheme sound: the bound
 * is CHECKED at the end. cft_mp_round rounds both ends of that
 * enclosure and accepts the result only if they agree on the bits AND
 * on the flags. A bound that is too generous costs an escalation to a
 * higher working precision; it can never produce a wrong answer. The
 * only bound that could is one that is too SMALL. That is why every
 * rule in mpfloat.c is an upper bound at every size of count and every
 * working precision, rounds up, and carries its derivation, and why
 * host/tests/mp_err_check.c holds every one of those rules to it
 * exactly, in GMP, over counts from zero past 2^W to infinity - and,
 * against MPFR, the count cft_mp_const gives each constant and
 * transcend.c's conversion of an argument's error into its
 * logarithm's (mp_log_of_mp). transcend.c's own allowances, such as a
 * truncated series' tail, are its algorithms' analysis and are not
 * held there.
 *
 * Until 2026-09-30 the count was a uint64_t saturating at 2^40. A
 * saturated count was a clamp, not a bound, and it decided roundings:
 * 17,816 of the 298,133 final roundings in
 * host/tests/transcend_check.py's sweep, every result equal to the
 * model's. Nor was every count below the ceiling a bound: a clamp that
 * a later operation scaled back down looked ordinary and was not one
 * (verifier-W4 measured a count of 34 against a worst true error of
 * 2^46.97 units). mpfloat.c's header has that history, and why the
 * count that replaced it decides no rounding the old one did not, but
 * for the one exception it names: an end of the old enclosure on the
 * format's grid, where the old loop escalated and this one may decide.
 */

#ifndef CFT_MPFLOAT_H
#define CFT_MPFLOAT_H

#include <stdint.h>

#include "bigint.h"
#include "softfloat.h"

/* The widest working significand. The binding constraint is the
 * 2048-bit bigint container: cft_mp_mul forms the full 2W-bit product
 * and cft_mp_div shifts the numerator left by W + 1 or more before
 * dividing, so 2W must fit with room to spare. 928 leaves 192 bits of
 * headroom, and is itself 832 (the Ziv cap,
 * python/cft_golden/transcend.py) plus 32 bits of guard plus the 19
 * bits of argument-reduction headroom the fp256 exponent range can
 * demand. */
#define CFT_MP_PREC_MAX 928

/* An error count: c * 2^k whole units of 2^-W. Canonical: c below
 * 2^63, k >= 0, and c at or above 2^62 whenever k > 0, so a count
 * below 2^63 is the exact integer with k = 0 and a larger one keeps 63
 * significant bits. A zero count is {0, 0}. k at CFT_MP_ERR_K_INF or
 * past it is infinity: a bound that is above every true error and
 * cannot decide. mpfloat.c's header says where infinity can arise, and
 * why it never displaces a bound that could decide. */
typedef struct {
    uint64_t c;
    int32_t  k;
} cft_mp_err;

#define CFT_MP_ERR_K_INF ((int32_t)1 << 24)

typedef struct {
    int        sign;  /* 1 when negative */
    int        zero;  /* the value is exactly zero; m and exp unused */
    long       exp;   /* value = (-1)^sign * m * 2^exp */
    cft_mp_err err;   /* |true - value| <= err * 2^-W * |value| */
    cft_bn     m;     /* exactly W bits when !zero: bit W-1 set */
} cft_mp;

/* The count's arithmetic: every result is the exact one or above it,
 * never below. These are the only ways this module and transcend.c
 * make or rescale a bound. */
cft_mp_err cft_mp_err_u64(uint64_t n);                 /* n units */
cft_mp_err cft_mp_err_add(cft_mp_err a, cft_mp_err b);
/* a * 2^j: for j >= 0 only the exponent moves, which is exact while it
 * stays below CFT_MP_ERR_K_INF; for j < 0 rounded up to a whole unit.
 * A known limit (verifier-W5, 2026-09-30): near a count of 2^(2^24)
 * infinity comes early. Any j of 2^24 or more gives infinity even from
 * a count of 1, which canonical form could hold as {2^62, 2^24 - 62},
 * and the private err_mul in mpfloat.c can do the same for a product
 * between 2^(2^24) and 2^(2^24 + 63), the top of canonical form. So
 * "exact for j >= 0" is not exact there - a bound still, above the
 * true value, at a size that decides nothing. */
cft_mp_err cft_mp_err_up(cft_mp_err a, long j);
cft_mp_err cft_mp_err_inf(void);
int        cft_mp_err_is_inf(cft_mp_err a);
/* 1 when a < 2^j is certain from a's bit length; 0 otherwise. */
int        cft_mp_err_lt_pow2(cft_mp_err a, long j);
/* v's count read in units of 2^-W: scaled up exactly by 2^(W - Wv)
 * when v is narrower than W bits, and kept - an overstatement - when
 * it is wider. */
cft_mp_err cft_mp_err_at(const cft_mp *v, int W);

/* The generated constants (host/src/mp_consts.h), by index. */
typedef enum {
    CFT_MP_C_LN2 = 0,
    CFT_MP_C_LOG2E,
    CFT_MP_C_LN10,
    CFT_MP_C_LOG10E,
    CFT_MP_C_PI,        /* phase 2: sinPi/cosPi/tanPi multiply by it */
    CFT_MP_C_INVPI      /* phase 2: asinPi/acosPi/atanPi divide by it */
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

/* Multiply ln2 by log2e, ln10 by log10e and pi by 1/pi, and require
 * all three products to be 1 to within a few units in the last place.
 * Returns 0 when the generated header is intact. A constant that was
 * truncated, byte swapped or edited fails here rather than in the low
 * bit of somebody's exponential.
 *
 * A reciprocal relation only says the two halves of a pair agree with
 * each other, so pi additionally gets an INDEPENDENT derivation: the
 * first call re-sums Machin's pi/4 = 4 atan(1/5) - atan(1/239) at 256
 * bits out of small-integer arithmetic and compares. That derivation
 * is cached - it is a property of compile-time data, and re-deriving
 * it on every call would cost more than the transcendental it guards -
 * while the three cheap products are re-checked every time, as they
 * always were. */
int cft_mp_consts_selfcheck(void);

#endif /* CFT_MPFLOAT_H */
