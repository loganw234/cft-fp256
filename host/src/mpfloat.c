/* Copyright 2026 Logan W.
 * SPDX-License-Identifier: Apache-2.0
 *
 * The multiprecision floating-point evaluator. See mpfloat.h for why
 * it is floating rather than fixed point, and for the error contract.
 *
 * ---------------------------------------------------------------
 * The error bounds, derived
 * ---------------------------------------------------------------
 *
 * `err` counts units of 2^-W of RELATIVE error, W being the value's
 * own width (the bit length of its significand):
 *
 *     |true - value| <= err * 2^-W * |value|
 *
 * Relative rather than absolute-in-ulps for one reason, and it is the
 * difference between a usable evaluator and a useless one: relative
 * error is ADDITIVE through multiplication and division, where an
 * ulp count is not. A significand sitting just above 2^(W-1) has ulps
 * twice as coarse, relatively, as one sitting just below 2^W, so a
 * bound expressed in ulps has to be multiplied by two at every
 * multiply to stay safe - and 2^170 over a series is not a bound, it
 * is a surrender. In relative terms the same step costs an addition.
 *
 * The count (cft_mp_err) is a whole number of units with its own
 * exponent, c * 2^k with k >= 0. Below 2^63 it is the exact integer,
 * k = 0; above, c keeps 63 significant bits. Nothing saturates, and
 * every operation on counts rounds UP: a sum that overflows c halves
 * it rounding up, and a count scaled DOWN rounds up to a whole unit.
 * Scaling UP moves k and is exact, so an amplified count is carried at
 * its size. Past k = 2^24 the count is infinity - a bound, since it is
 * above every true error, and one that cannot decide. Nothing reaches
 * it by growth: one operation scales a count up by at most 2W + 2
 * bits. The rules below produce it in two places only, div and
 * transcend.c's mp_log_of_mp, both where the rule's bound already
 * exceeds a relative error of 1, so it never displaces a bound that
 * could decide.
 *
 * Widths. An operation at W reads each operand's count in units of
 * 2^-W (cft_mp_err_at): scaled up by 2^(W - Wx), exactly, when the
 * operand is narrower, and kept when it is wider, which overstates it
 * by 2^(Wx - W). Every result it computes is W bits wide - an add with
 * an exact zero returns the other operand as it stands, its own width
 * and count with it - and every rule below holds at any operand
 * widths. One operand is read at a width not its own today: the
 * Payne-Hanek reduction's t, made at the deepest attempt's width and
 * multiplied at each attempt's (transcend.c, tr_eval).
 *
 * Below, counts are in units of 2^-W; ea and eb are the operands'
 * counts read at W; ceil() rounds up to a whole unit; up(e, j) is
 * e * 2^j, exact for j >= 0 and ceil'd for j < 0; and
 *
 *     trunc(X) = X + 2 + ceil(X * 2^(1-W))
 *
 * The rules, each an upper bound at every size of count and every W:
 *
 *   truncation   S exact, with |true - S| <= x*S, truncated toward
 *                zero to r of W bits. One unit in r's last place is at
 *                most 2^(1-W) of r, so S = r(1 + t) with
 *                0 <= t < 2^(1-W), and
 *                    |true - r| <= x*S + t*r = r(x + t + x*t).
 *                In units that is trunc(X). The x*t term is one unit
 *                whenever 0 < X <= 2^(W-1), and nothing for an exact
 *                S; until 2026-09-30 it was not charged (X + 2).
 *
 *   mul          (1 + da)(1 + db) - 1 is at most ea + eb + ea*eb
 *                relatively:
 *                    X = ea + eb + max(1, ceil(ea*eb*2^-W)), trunc(X).
 *                The 1 is the old rule's allowance for the cross term,
 *                which covered it while ea*eb < 2^W; past that the
 *                cross term itself is charged.
 *
 *   div          |(1 + da)/(1 + db) - 1| <= (ea + eb)/(1 - eb)
 *                <= (ea + eb)(1 + 2*eb) for eb <= 1/2. So, for eb
 *                below 2^(W-1) in units,
 *                    X = ea + eb + max(1, ceil(2*(ea + eb)*eb*2^-W)),
 *                    trunc(X).
 *                Past that the bound is above eb/(1 - eb) > 1, and at
 *                eb >= 1 no finite bound exists (the divisor may be
 *                zero): infinity. The quotient is floor(a * 2^s / b)
 *                with s = W + 1 + max(0, Wb - Wa), so it has W + 1
 *                bits or more, and floor(floor(x) / 2^j) =
 *                floor(x / 2^j): the floor and the truncation to W
 *                bits are ONE truncation. The old rule's + 1 for the
 *                floor was spare; it is the 1 kept above.
 *
 *   mul_ui,      An exact integer factor or divisor leaves the
 *   div_ui       relative error as it was. div_ui's quotient is
 *                floor(a * 2^s / u) with s = 34 + max(0, W - Wa), so
 *                it has W + 2 bits or more and its floor is part of
 *                its one truncation, as div's is.          trunc(ea)
 *
 *   add, like signs
 *                ea|a| + eb|b| <= (ea + eb)|a + b|.    trunc(ea + eb)
 *
 *   add, unlike signs (cancellation)
 *                The absolute errors survive and the result shrank.
 *                With la and lb the bit lengths of the aligned
 *                significands and lr the difference's,
 *                |a| / |a + b| < 2^(la - lr + 1), so
 *                    X = up(ea, la - lr + 1) + up(eb, lb - lr + 1),
 *                then trunc(X) when the difference is wider than W
 *                bits, and X when it is not (a left shift is exact).
 *                That is where a subtraction that loses k bits costs
 *                k bits of the error budget - carried at its size,
 *                since scaling up is exact. This is the term the
 *                algorithms in transcend.c are shaped to keep small.
 *
 *   add, b wholly below a's last place (a->exp - b->exp > W + 2)
 *                The result is a, and
 *                    |true - a| <= ea|a| + |b|(1 + eb),
 *                with |b| / |a| < 2^(vb - va + 1) for the value
 *                exponents va and vb (exp plus width): below a quarter
 *                unit at equal widths. So
 *                    X = ea + max(2, ceil(2^(vb - va + 1 + W))
 *                                    + up(eb, vb - va + 1)).
 *                The 2 is the old rule's; b's own error is charged
 *                once it could exceed it.
 *
 *   sqrt         1 - sqrt(1 - e) <= e/2 + e^2/2 on [0, 1] (with
 *                s = sqrt(1 - e) that is 0 <= s(1 - s)(2 + s)), and
 *                sqrt(1 + e) - 1 <= e/2. So for ea below 2^W
 *                    X = ceil(ea/2) + ceil(ea^2 * 2^-(W+1)).
 *                At or past 2^W the operand's relative error is 1 or
 *                more. Every square root here is of a value known to
 *                be nonnegative - 1 + u^2, (1 - x)(1 + x), x^2 + y^2 -
 *                so the root lies in [0, sqrt(1 + e)] of the stored
 *                one, and X = ea. The integer root lands on exactly W
 *                bits, so an inexact root is one truncation, trunc(X);
 *                an EXACT root keeps X. (Until 2026-09-30 the square
 *                term was left to the other rules' slack - verifiers
 *                F1 and F4 - and until that day's first fix the
 *                inexact root had no + 2.)
 *
 *   scale by 2^k Exact.                                        +0
 *
 * cft_mp_const truncates the 1088-bit constant with a count of 1 in,
 * so trunc(1) = 4. The stored constant is the true one truncated at
 * 1088 bits, and truncating that at W is truncating the true one at
 * W, so the 1 is spare; it is kept from the old rule.
 *
 * ---------------------------------------------------------------
 * The old count, and why this one decides nothing the old one did not
 * ---------------------------------------------------------------
 *
 * Until 2026-09-30 `err` was a uint64_t that saturated at 2^40, and a
 * saturated count was a CLAMP, not a bound: the true error could be
 * larger, and the count still decided. enclosure() is m +- err in the
 * significand's units, so a count of 2^40 is narrow enough to decide
 * a rounding at any working precision about 41 bits above the
 * format's, which is every ordinary one. It was not rare. The lead
 * measured it that day over host/tests/transcend_check.py at the
 * contract's precision: 1,781,005 saturations, 1,773,722 of them the
 * cancellation rule amplifying an inexact operand's error (1,769,620
 * scaling the first operand's count and 4,102 the second's), and 17,816
 * of 298,133 final roundings decided on a saturated count - every one
 * of the 607,217 results equal to the model's. Nor was a count below
 * the ceiling safe: a square root, a cancellation or transcend.c's
 * mp_log_of_mp could scale a clamp back down into an ordinary-looking
 * count that was not a bound either. verifier-W4 measured one that day
 * at W = 88 through two subtractions: a count of 34 against a worst
 * true error of 2^46.97 units. host/tests/mp_err_check.c carries that
 * case. Refusing to decide on a saturated count was not the repair:
 * it made calls such as expm1 of fp32 0x42b17218 refuse at the Ziv
 * cap, because a cancellation that loses d bits amplifies by 2^(d+1)
 * at every working precision, so a fixed ceiling is met at every one.
 * A count without a ceiling is the repair: at a higher W the same
 * count is a smaller relative error, and it decides.
 *
 * Every rule above is the old one (as it stood at aeb3f5e, where a
 * count scaled down already rounded up) plus terms that are never
 * negative, and every rule is non-decreasing in its operands' counts.
 * No significand depends on a count: the rules only compute counts,
 * and the only other readers are enclosure() and cft_mp_add's
 * exact-cancellation test, which asks only whether both counts are
 * zero. (div's and div_ui's shifts are the old ones whenever the
 * dividend is W bits wide, which it is at every call site.) So, by
 * induction over an evaluation, every count here is at least the one
 * the old rules computed at the same step - the clamp only ever
 * lowered those - and every enclosure contains the old one.
 *
 * Hence a rounding this module decides at a working precision, the
 * old module decided at the same precision with the same bits and
 * flags, with one exception: an end of the OLD enclosure lying
 * exactly on the format's grid, which round_pack reports exact where
 * the wider enclosure's end is not. There the old flags disagreed and
 * the old loop escalated, where this one may decide - correctly, as
 * its enclosure holds the true value. A screen (cft_mp_cmp_int) this
 * module fires, the old one fired; one the old fired and this does not
 * falls through to the Ziv loop, which is always safe. So against the
 * old module a call can only take an extra escalation, and it refuses
 * (CFT_ERR_INTERNAL) only if that escalation reaches the cap - which
 * the gate's transcend and mpfr stages report as a mismatch, naming
 * the operands. Its answer is the old one's wherever the old one was
 * right, which the sweep holds against the model on every result;
 * where a clamp had decided a rounding wrongly, this module escalates
 * past the clamp instead.
 */

/* This module is optional: the multiprecision evaluator the
 * transcendentals use, removed entirely by -DCFT_NO_TRANSCEND. Removed
 * rather than left for the linker to garbage-collect, because what
 * does not fit on a part with 32 KB of flash is as often a constant
 * table as it is code, and a table reachable from one live function is
 * not collected. */
#include "../include/cft_config.h"
#ifndef CFT_NO_TRANSCEND

#include <string.h>

#include "mpfloat.h"
#include "mp_consts.h"

/* ---- the error count ---------------------------------------------- *
 *
 * c * 2^k whole units, canonical as mpfloat.h describes. Every function
 * here returns the exact result or one above it, never below it: that,
 * and nothing else, is what keeps a count a bound. No 128-bit type and
 * no compiler builtin, so it is the same arithmetic on every host.
 */

#define ERR_C_TOP  ((uint64_t)1 << 63)   /* c stays below this */
#define ERR_C_HIGH ((uint64_t)1 << 62)   /* and at or above it when k > 0 */

static const cft_mp_err ERR_ZERO = { 0, 0 };

static int u64_bitlen(uint64_t x)
{
    int n = 0;
    if (x >> 32) { n += 32; x >>= 32; }
    if (x >> 16) { n += 16; x >>= 16; }
    if (x >> 8)  { n += 8;  x >>= 8; }
    if (x >> 4)  { n += 4;  x >>= 4; }
    if (x >> 2)  { n += 2;  x >>= 2; }
    if (x >> 1)  { n += 1;  x >>= 1; }
    return n + (int)x;
}

cft_mp_err cft_mp_err_inf(void)
{
    cft_mp_err r;
    r.c = ERR_C_HIGH;
    r.k = CFT_MP_ERR_K_INF;
    return r;
}

int cft_mp_err_is_inf(cft_mp_err a)
{
    return a.k >= CFT_MP_ERR_K_INF;
}

/* c * 2^k for any c and any k >= 0, made canonical. A c too wide is
 * halved with the dropped bit rounded UP; a c too narrow for its k
 * takes bits from k, which is exact. */
static cft_mp_err err_make(uint64_t c, long k)
{
    cft_mp_err r;
    if (c == 0)
        return ERR_ZERO;
    while (c >= ERR_C_TOP) {
        c = (c >> 1) + (c & 1);
        k++;
    }
    if (k > 0 && c < ERR_C_HIGH) {
        long s = 63 - u64_bitlen(c);     /* the top bit to bit 62 */
        if (s > k)
            s = k;
        c <<= s;
        k -= s;
    }
    if (k >= CFT_MP_ERR_K_INF)
        return cft_mp_err_inf();
    r.c = c;
    r.k = (int32_t)k;
    return r;
}

cft_mp_err cft_mp_err_u64(uint64_t n)
{
    return err_make(n, 0);
}

cft_mp_err cft_mp_err_add(cft_mp_err a, cft_mp_err b)
{
    uint64_t bc;
    long d;
    if (cft_mp_err_is_inf(a) || cft_mp_err_is_inf(b))
        return cft_mp_err_inf();
    if (b.c == 0)
        return a;
    if (a.c == 0)
        return b;
    if (a.k < b.k) {
        cft_mp_err t = a;
        a = b;
        b = t;
    }
    /* b in a's units of 2^a.k, rounded up. When a.k > 0, a.c is at
     * least 2^62, so that costs at most 2^-62 of the sum. */
    d = (long)a.k - (long)b.k;
    if (d == 0)
        bc = b.c;
    else if (d >= 64)
        bc = 1;
    else
        bc = (b.c >> d) + ((b.c & (((uint64_t)1 << d) - 1)) != 0);
    return err_make(a.c + bc, a.k);    /* each below 2^63: no wrap */
}

cft_mp_err cft_mp_err_up(cft_mp_err a, long j)
{
    uint64_t q;
    long s;
    if (a.c == 0 || cft_mp_err_is_inf(a))
        return a;
    if (j >= 0) {
        if (j >= CFT_MP_ERR_K_INF)
            return cft_mp_err_inf();
        return err_make(a.c, (long)a.k + j);
    }
    if (j >= -(long)a.k)
        return err_make(a.c, (long)a.k + j);      /* exact: k absorbs it */
    if (j < -(long)a.k - 63)
        return err_make(1, 0);                    /* below one unit: 1 */
    s = -((long)a.k + j);                         /* 1 to 63 bits of c */
    q = (a.c >> s) + ((a.c & (((uint64_t)1 << s) - 1)) != 0);
    return err_make(q, 0);
}

int cft_mp_err_lt_pow2(cft_mp_err a, long j)
{
    if (a.c == 0)
        return 1;
    if (cft_mp_err_is_inf(a))
        return 0;
    return (long)u64_bitlen(a.c) + (long)a.k <= j;   /* a < 2^(len+k) */
}

cft_mp_err cft_mp_err_at(const cft_mp *v, int W)
{
    int wv;
    if (v->zero)
        return ERR_ZERO;
    wv = cft_bn_bitlen(&v->m);
    return wv < W ? cft_mp_err_up(v->err, (long)W - wv) : v->err;
}

/* A count bounded above by its top 31 bits: a <= h * 2^s. */
static void err_top31(cft_mp_err a, uint64_t *h, long *s)
{
    int L = u64_bitlen(a.c);
    int sh = L > 31 ? L - 31 : 0;
    uint64_t t = a.c >> sh;
    if (sh && (a.c & (((uint64_t)1 << sh) - 1)))
        t++;                                      /* at most 2^31 */
    *h = t;
    *s = (long)a.k + sh;
}

/* a * b * 2^j, rounded up to a whole unit: the second-order terms. The
 * top-31-bit bounds make the product fit 62 bits, so no 128-bit
 * multiply is needed, at a cost of at most 2^-29 of the term. */
static cft_mp_err err_mul(cft_mp_err a, cft_mp_err b, long j)
{
    uint64_t ha, hb;
    long sa, sb;
    if (a.c == 0 || b.c == 0)
        return ERR_ZERO;
    if (cft_mp_err_is_inf(a) || cft_mp_err_is_inf(b))
        return cft_mp_err_inf();
    err_top31(a, &ha, &sa);
    err_top31(b, &hb, &sb);
    return cft_mp_err_up(err_make(ha * hb, 0), sa + sb + j);
}

/* max(n, x) for a small n: the old rules' allowances, kept as floors. */
static cft_mp_err err_at_least(cft_mp_err x, uint64_t n)
{
    if (x.k == 0 && x.c <= n)
        return err_make(n, 0);
    return x;
}

/* The truncation lemma of the header: a value carrying x, truncated
 * toward zero to W bits, carries x + 2 + x * 2^(1-W). */
static cft_mp_err err_trunc(cft_mp_err x, int W)
{
    return cft_mp_err_add(cft_mp_err_add(x, cft_mp_err_u64(2)),
                          cft_mp_err_up(x, 1 - (long)W));
}

/* ---- normalisation ------------------------------------------------ *
 *
 * Bring (sign, m, e) to exactly W significand bits. `err_in` is the
 * incoming relative error in units of 2^-W; a right shift truncates
 * and costs trunc() (the header's truncation lemma), a left shift is
 * exact.
 */
static int mp_norm(cft_mp *r, int W, int sign, const cft_bn *m, long e,
                   cft_mp_err err_in)
{
    int L = cft_bn_bitlen(m);
    if (L == 0) {
        cft_mp_set_zero(r);
        return 0;
    }
    r->sign = sign ? 1 : 0;
    r->zero = 0;
    if (L > W) {
        cft_bn_shr(&r->m, m, L - W);
        r->exp = e + (L - W);
        r->err = err_trunc(err_in, W);
    } else {
        if (cft_bn_shl(&r->m, m, W - L))
            return 1;
        r->exp = e - (W - L);
        r->err = err_in;
    }
    return 0;
}

void cft_mp_set_zero(cft_mp *r)
{
    r->sign = 0;
    r->zero = 1;
    r->exp = 0;
    r->err = ERR_ZERO;
    cft_bn_zero(&r->m);
}

int cft_mp_set_bn(cft_mp *r, int W, int sign, const cft_bn *m, long e)
{
    return mp_norm(r, W, sign, m, e, ERR_ZERO);
}

int cft_mp_set_ui(cft_mp *r, int W, int sign, uint32_t v, long e)
{
    cft_bn t;
    cft_bn_zero(&t);
    cft_bn_set_u32(&t, v);
    return mp_norm(r, W, sign, &t, e, ERR_ZERO);
}

void cft_mp_copy(cft_mp *r, const cft_mp *a)
{
    if (r == a)
        return;
    r->sign = a->sign;
    r->zero = a->zero;
    r->exp = a->exp;
    r->err = a->err;
    cft_bn_copy(&r->m, &a->m);
}

void cft_mp_neg(cft_mp *r)
{
    if (!r->zero)
        r->sign ^= 1;
}

void cft_mp_shift(cft_mp *r, long k)
{
    if (!r->zero)
        r->exp += k;
}

long cft_mp_exp2_of(const cft_mp *a)
{
    return a->exp + cft_bn_bitlen(&a->m) - 1;
}

/* ---- multiply ----------------------------------------------------- */

/* X = ea + eb + max(1, ceil(ea*eb*2^-W)), then the truncation. */
int cft_mp_mul(cft_mp *r, const cft_mp *a, const cft_mp *b, int W)
{
    cft_bn p;
    cft_mp_err ea, eb, x;
    if (a->zero || b->zero) {
        cft_mp_set_zero(r);
        return 0;
    }
    if (cft_bn_mul(&p, &a->m, &b->m))
        return 1;
    ea = cft_mp_err_at(a, W);
    eb = cft_mp_err_at(b, W);
    x = cft_mp_err_add(cft_mp_err_add(ea, eb),
                       err_at_least(err_mul(ea, eb, -(long)W), 1));
    return mp_norm(r, W, a->sign ^ b->sign, &p, a->exp + b->exp, x);
}

int cft_mp_mul_ui(cft_mp *r, const cft_mp *a, uint32_t u, int W)
{
    cft_bn f, p;
    if (a->zero || u == 0) {
        cft_mp_set_zero(r);
        return 0;
    }
    cft_bn_zero(&f);
    cft_bn_set_u32(&f, u);
    if (cft_bn_mul(&p, &a->m, &f))
        return 1;
    return mp_norm(r, W, a->sign, &p, a->exp, cft_mp_err_at(a, W));
}

/* ---- add and subtract --------------------------------------------- */

/* b lies wholly below a's last place: the result is a, carrying a's
 * count and b's whole contribution relative to a - its magnitude,
 * below a quarter unit at equal widths, and its own error - with the
 * old rule's 2 as the floor (the header's "add, b wholly below"). The
 * counts are read before r is written, and a's significand is copied,
 * so r may be a or b. */
static int add_skip(cft_mp *r, const cft_mp *a, cft_mp_err erra,
                    const cft_mp *b, cft_mp_err errb, int W)
{
    long va = a->exp + cft_bn_bitlen(&a->m);
    long vb = b->exp + cft_bn_bitlen(&b->m);
    cft_mp_err mag = cft_mp_err_up(cft_mp_err_u64(1), vb - va + 1 + W);
    cft_mp_err own = cft_mp_err_up(errb, vb - va + 1);
    cft_mp_err x = cft_mp_err_add(erra,
                                  err_at_least(cft_mp_err_add(mag, own), 2));
    cft_bn t;
    cft_bn_copy(&t, &a->m);
    return mp_norm(r, W, a->sign, &t, a->exp, x);
}

/* The alignment is bounded exactly as sf_fma bounds it: past W + 2
 * places the smaller term lies entirely below the larger's last bit,
 * and add_skip charges what it can still contribute. */
int cft_mp_add(cft_mp *r, const cft_mp *a, const cft_mp *b, int W)
{
    cft_bn ma, mb, s;
    long ea, eb, e0;
    cft_mp_err erra, errb, err_out;
    int sa, sb, cmp, sign;

    if (a->zero) { cft_mp_copy(r, b); return 0; }
    if (b->zero) { cft_mp_copy(r, a); return 0; }

    ea = a->exp; eb = b->exp;
    sa = a->sign; sb = b->sign;
    erra = cft_mp_err_at(a, W);
    errb = cft_mp_err_at(b, W);

    if (ea - eb > W + 2)
        return add_skip(r, a, erra, b, errb, W);
    if (eb - ea > W + 2)
        return add_skip(r, b, errb, a, erra, W);

    e0 = ea < eb ? ea : eb;
    if (cft_bn_shl(&ma, &a->m, (int)(ea - e0)))
        return 1;
    if (cft_bn_shl(&mb, &b->m, (int)(eb - e0)))
        return 1;

    if (sa == sb) {
        if (cft_bn_add(&s, &ma, &mb))
            return 1;
        sign = sa;
        err_out = cft_mp_err_add(erra, errb);
    } else {
        cmp = cft_bn_cmp(&ma, &mb);
        if (cmp == 0) {
            if (erra.c == 0 && errb.c == 0) {
                cft_mp_set_zero(r);      /* exactly zero, and provably */
                return 0;
            }
            /* The two APPROXIMATIONS cancelled exactly, but neither
             * was exact, so the true difference is not provably zero.
             * It is not provably ANYTHING this type can hold: the
             * bound `err` is RELATIVE, and the true difference lies
             * somewhere in a window set by the operands' ABSOLUTE
             * errors, which no relative bound around any value covers.
             * So this is a failure and not a value - the caller's Ziv
             * loop raises the working precision, which is exactly what
             * a cancellation this complete calls for.
             *
             * Found by running the evaluator below its design
             * precision (CFT_TRANSCEND_MINPREC): log(1 + 2^-112) at
             * fp128 cancels to zero at 64 bits, and pow then returned
             * exactly 1 from a degenerate enclosure the loop believed.
             * The first repair returned the larger operand with a
             * SATURATED bound, on the reasoning that the enclosure
             * would then reach zero. It did not: err then saturated at
             * 2^40 while the significand is 2^(W-1), so at any W above
             * 41 the enclosure was narrow, decidable and wrong - which
             * showed up on 2026-09-03 as pow(2 + ulp, ~10^4) at fp128
             * overflowing where the true value is about 2^9888.
             *
             * At the contract's own working precisions the operands of
             * the subtraction that can do this are exact, so this
             * cannot fire; the whole discussion is about the forced
             * low-precision runs, which is what they are for. */
            return 1;
        }
        if (cmp > 0) {
            cft_bn_sub(&s, &ma, &mb);
            sign = sa;
        } else {
            cft_bn_sub(&s, &mb, &ma);
            sign = sb;
        }
        /* Cancellation: the amplification is the drop from each
         * operand's value exponent to the result's, and it is applied
         * before the result is renormalised, in units of 2^-W. Scaling
         * up is exact however far it goes; scaling down rounds up. */
        {
            int lr = cft_bn_bitlen(&s);
            int la = cft_bn_bitlen(&ma);
            int lb = cft_bn_bitlen(&mb);
            err_out = cft_mp_err_add(cft_mp_err_up(erra, la - lr + 1),
                                     cft_mp_err_up(errb, lb - lr + 1));
        }
    }
    return mp_norm(r, W, sign, &s, e0, err_out);
}

int cft_mp_sub(cft_mp *r, const cft_mp *a, const cft_mp *b, int W)
{
    cft_mp nb;
    cft_mp_copy(&nb, b);
    cft_mp_neg(&nb);
    return cft_mp_add(r, a, &nb, W);
}

/* ---- divide -------------------------------------------------------- *
 *
 * Schoolbook binary long division, not a Newton reciprocal, and the
 * reason is the error contract: a floor division with a remainder is
 * exact to within one unit in the last place BY CONSTRUCTION, where a
 * Newton iteration's accuracy has to be argued or measured. bigint.h
 * deliberately carries no division; this is the one place the library
 * needs one, it needs it once per logarithm, and W iterations of
 * shift-compare-subtract cost about the same as sixty multiplies.
 */
static int bn_divmod(cft_bn *q, const cft_bn *num, const cft_bn *den)
{
    cft_bn rem;
    int i, nb = cft_bn_bitlen(num);
    if (cft_bn_is_zero(den))
        return 1;
    cft_bn_zero(q);
    cft_bn_zero(&rem);
    for (i = nb - 1; i >= 0; i--) {
        if (cft_bn_shl(&rem, &rem, 1))
            return 1;
        if (cft_bn_bit(num, i))
            cft_bn_setbit(&rem, 0);
        if (cft_bn_shl(q, q, 1))
            return 1;
        if (cft_bn_cmp(&rem, den) >= 0) {
            cft_bn_sub(&rem, &rem, den);
            cft_bn_setbit(q, 0);
        }
    }
    return 0;
}

/* The numerator is shifted by W + 1, and by the divisor's excess width
 * over the dividend's when there is one, so that the quotient always
 * has W + 1 bits or more: then floor and truncation are one truncation
 * (the header's div). With the operands W bits wide, as they are at
 * every call site, the shift is W + 1 exactly, as it always was. For
 * eb below 2^(W-1): X = ea + eb + max(1, ceil(2(ea + eb) eb 2^-W));
 * past it, infinity. */
int cft_mp_div(cft_mp *r, const cft_mp *a, const cft_mp *b, int W)
{
    cft_bn num, q;
    cft_mp_err ea, eb, s, x;
    int la, lb, sh;
    if (b->zero)
        return 1;
    if (a->zero) {
        cft_mp_set_zero(r);
        return 0;
    }
    la = cft_bn_bitlen(&a->m);
    lb = cft_bn_bitlen(&b->m);
    sh = W + 1 + (lb > la ? lb - la : 0);
    if (cft_bn_shl(&num, &a->m, sh))
        return 1;
    if (bn_divmod(&q, &num, &b->m))
        return 1;
    ea = cft_mp_err_at(a, W);
    eb = cft_mp_err_at(b, W);
    if (!cft_mp_err_lt_pow2(eb, (long)W - 1)) {
        x = cft_mp_err_inf();
    } else {
        s = cft_mp_err_add(ea, eb);
        x = cft_mp_err_add(s, err_at_least(err_mul(s, eb, 1 - (long)W), 1));
    }
    return mp_norm(r, W, a->sign ^ b->sign, &q, a->exp - b->exp - sh, x);
}

/* The numerator is shifted by 34, and by W less the dividend's width
 * when it is narrower, so the quotient has W + 2 bits or more and its
 * floor is part of the one truncation. A W-bit dividend - every call
 * site's - is shifted by 34, as it always was. The divisor is an exact
 * integer, so the count is the dividend's: trunc(ea). */
int cft_mp_div_ui(cft_mp *r, const cft_mp *a, uint32_t u, int W)
{
    cft_bn num, den, q;
    int la, sh;
    if (u == 0)
        return 1;
    if (a->zero) {
        cft_mp_set_zero(r);
        return 0;
    }
    cft_bn_zero(&den);
    cft_bn_set_u32(&den, u);
    la = cft_bn_bitlen(&a->m);
    sh = 34 + (W > la ? W - la : 0);
    if (cft_bn_shl(&num, &a->m, sh))
        return 1;
    if (bn_divmod(&q, &num, &den))
        return 1;
    return mp_norm(r, W, a->sign, &q, a->exp - sh, cft_mp_err_at(a, W));
}

/* ---- square root --------------------------------------------------- *
 *
 * Digit-by-digit integer square root, for the same reason division is
 * schoolbook: floor(sqrt(N)) with a remainder is exact to within one
 * unit in the last place without an argument. The remainder it ends
 * with is N - root^2, so `exact` (when asked for) is whether it is 0. */
static int bn_isqrt(cft_bn *root, int *exact, const cft_bn *n)
{
    cft_bn rem, trial;
    int i, nb = cft_bn_bitlen(n);
    if (nb & 1)
        nb++;
    cft_bn_zero(root);
    cft_bn_zero(&rem);
    for (i = nb - 2; i >= 0; i -= 2) {
        if (cft_bn_shl(&rem, &rem, 2))
            return 1;
        if (cft_bn_bit(n, i + 1))
            cft_bn_setbit(&rem, 1);
        if (cft_bn_bit(n, i))
            cft_bn_setbit(&rem, 0);
        /* The trial subtrahend is 4R + 1, not 2R + 1: appending a
         * digit d takes the root from R to 2R+d, and (2R+1)^2 -
         * (2R)^2 is 4R + 1. */
        if (cft_bn_shl(&trial, root, 2))
            return 1;
        cft_bn_setbit(&trial, 0);
        if (cft_bn_shl(root, root, 1))
            return 1;
        if (cft_bn_cmp(&rem, &trial) >= 0) {
            cft_bn_sub(&rem, &rem, &trial);
            cft_bn_setbit(root, 0);
        }
    }
    if (exact)
        *exact = cft_bn_bitlen(&rem) == 0;
    return 0;
}

int cft_mp_isqrt(cft_bn *root, int *exact, const cft_bn *n)
{
    cft_bn sq;
    if (bn_isqrt(root, NULL, n))
        return 1;
    if (cft_bn_mul(&sq, root, root))
        return 1;
    *exact = (cft_bn_cmp(&sq, n) == 0);
    return 0;
}

/* The root's error is the input's, halved, plus the square term, plus
 * the truncation (the header's sqrt). bn_isqrt returns floor(sqrt(n)),
 * and root lands on exactly W bits, so an inexact root lies below the
 * true one by less than a unit in its last place: one truncation. Until
 * 2026-09-30 that term was missing, so an exact operand came back with
 * err 0 on an inexact root. No gate saw it decide a rounding wrongly at
 * the contract's starting precision, but forced to start at 64 bits
 * (CFT_TRANSCEND_MINPREC) the loop decided fp128 rootn(0x2, 2) one ulp
 * low of squareRoot (verify/run.sh transcend, the escalation run). An
 * exact root, and only an exact root, keeps no truncation. */
int cft_mp_sqrt(cft_mp *r, const cft_mp *a, int W)
{
    cft_bn n, root;
    cft_mp_err ea, x;
    long e;
    int L, k, exact;
    if (a->zero) {
        cft_mp_set_zero(r);
        return 0;
    }
    if (a->sign)
        return 1;
    L = cft_bn_bitlen(&a->m);
    k = 2 * W - L;                 /* land the significand on 2W bits */
    e = a->exp - k;
    if (e & 1) {                   /* the exponent must be even to halve */
        k--;
        e++;
    }
    if (k < 0 || cft_bn_shl(&n, &a->m, k))
        return 1;
    if (bn_isqrt(&root, &exact, &n))
        return 1;
    ea = cft_mp_err_at(a, W);
    if (cft_mp_err_lt_pow2(ea, W))
        x = cft_mp_err_add(cft_mp_err_up(ea, -1),
                           err_mul(ea, ea, -(long)W - 1));
    else
        x = ea;
    if (!exact)
        x = err_trunc(x, W);
    return mp_norm(r, W, 0, &root, e / 2, x);
}

/* The integer part of the value, truncated toward zero and saturated.
 * Only the exponential's argument reduction uses it, and there an
 * off-by-one merely widens the reduced argument from ln2/2 to ln2 -
 * which the series still carries - so truncation is enough and no
 * rounding rule is needed. */
int64_t cft_mp_trunc_to_int(const cft_mp *a)
{
    const int64_t CAP = (int64_t)1 << 40;
    cft_bn t;
    int64_t v = 0;
    long sh;
    int i;

    if (a->zero)
        return 0;
    if (cft_mp_exp2_of(a) > 40)
        return a->sign ? -CAP : CAP;
    if (cft_mp_exp2_of(a) < 0)
        return 0;
    sh = -a->exp;
    if (sh < 0)
        return a->sign ? -CAP : CAP;
    cft_bn_shr(&t, &a->m, (int)sh);
    for (i = t.n - 1; i >= 0; i--)
        v = (v << 32) | (int64_t)t.v[i];
    if (v > CAP)
        v = CAP;
    return a->sign ? -v : v;
}

/* ---- generated constants ------------------------------------------- */

int cft_mp_const(cft_mp *r, cft_mp_constant which, int W)
{
    const uint32_t *limbs;
    long e;
    cft_bn v;
    int i;

    switch (which) {
    case CFT_MP_C_LN2:    limbs = cft_mp_ln2_limbs;    e = CFT_MP_LN2_EXP; break;
    case CFT_MP_C_LOG2E:  limbs = cft_mp_log2e_limbs;  e = CFT_MP_LOG2E_EXP; break;
    case CFT_MP_C_LN10:   limbs = cft_mp_ln10_limbs;   e = CFT_MP_LN10_EXP; break;
    case CFT_MP_C_LOG10E: limbs = cft_mp_log10e_limbs; e = CFT_MP_LOG10E_EXP; break;
    case CFT_MP_C_PI:     limbs = cft_mp_pi_limbs;     e = CFT_MP_PI_EXP; break;
    case CFT_MP_C_INVPI:  limbs = cft_mp_invpi_limbs;  e = CFT_MP_INVPI_EXP; break;
    default: return 1;
    }
    if (W > CFT_MP_CONST_BITS)
        return 1;
    cft_bn_zero(&v);
    for (i = 0; i < CFT_MP_CONST_LIMBS; i++)
        v.v[i] = limbs[i];
    v.n = CFT_MP_CONST_LIMBS;
    while (v.n > 0 && v.v[v.n - 1] == 0)
        v.n--;
    if (cft_bn_bitlen(&v) != CFT_MP_CONST_BITS)
        return 1;                 /* a truncated or corrupted header */
    /* The stored value is the true one truncated toward zero at 1088
     * bits, so it is already low by up to one unit there; truncating
     * further to W is the truncation mp_norm charges. The count of 1
     * going in is spare - a truncation of a truncation is one - and is
     * kept from the old rule (the header): trunc(1), 4 units. */
    return mp_norm(r, W, 0, &v, e, cft_mp_err_u64(1));
}

/* atan(1/n) at W bits, for a small integer n >= 2, by its alternating
 * series: sum (-1)^k / ((2k+1) n^(2k+1)). Every operand is a small
 * integer or a previous term divided by one, so this shares nothing at
 * all with mp_consts.h - which is the point: it is a DERIVATION of pi,
 * not a consistency check on one.
 *
 * The positive and negative terms are accumulated separately and
 * subtracted once at the end, so the error bound never pays the factor
 * of two an alternating sum charges per step. */
static int mp_atan_recip(cft_mp *r, uint32_t n, int W)
{
    cft_mp pos, neg, pw, t, q, n2;
    uint32_t k;

    if (n < 2)
        return 1;
    if (cft_mp_set_ui(&pw, W, 0, 1, 0))          /* (1/n)^(2k+1), k=0 */
        return 1;
    if (cft_mp_div_ui(&pw, &pw, n, W))
        return 1;
    if (cft_mp_set_ui(&n2, W, 0, n, 0))
        return 1;
    if (cft_mp_mul(&n2, &n2, &n2, W))            /* n^2 */
        return 1;
    cft_mp_copy(&pos, &pw);
    cft_mp_set_zero(&neg);
    for (k = 1; k < 4096; k++) {
        if (cft_mp_div(&pw, &pw, &n2, W))
            return 1;
        if (cft_mp_div_ui(&q, &pw, 2 * k + 1, W))
            return 1;
        if (q.zero || cft_mp_exp2_of(&q) < cft_mp_exp2_of(&pos) - (long)(W + 8))
            break;
        if (k & 1) {
            if (cft_mp_add(&neg, &neg, &q, W))
                return 1;
        } else {
            if (cft_mp_add(&pos, &pos, &q, W))
                return 1;
        }
    }
    if (cft_mp_sub(&t, &pos, &neg, W))
        return 1;
    cft_mp_copy(r, &t);
    return 0;
}

/* Machin: pi = 16 atan(1/5) - 4 atan(1/239). */
static int mp_pi_machin(cft_mp *r, int W)
{
    cft_mp a5, a239, t;
    if (mp_atan_recip(&a5, 5, W))
        return 1;
    if (mp_atan_recip(&a239, 239, W))
        return 1;
    cft_mp_shift(&a5, 4);                        /* 16 atan(1/5) */
    cft_mp_shift(&a239, 2);                      /*  4 atan(1/239) */
    if (cft_mp_sub(&t, &a5, &a239, W))
        return 1;
    cft_mp_copy(r, &t);
    return 0;
}

/* The stored pi against Machin's, once. See mpfloat.h for why this is
 * cached where the reciprocal products are not: it is a derivation of
 * compile-time data, and it costs about as much as one transcendental.
 * The tri-state keeps a FAILURE sticky - a bad header must not become
 * good on the second call. */
static int pi_derivation_ok(void)
{
    static int state;            /* 0 not run, 1 ok, 2 failed */
    const int W = 256;
    cft_mp got, want, d;

    if (state)
        return state == 1 ? 0 : 1;
    state = 2;
    if (mp_pi_machin(&got, W))
        return 1;
    if (cft_mp_const(&want, CFT_MP_C_PI, W))
        return 1;
    if (cft_mp_sub(&d, &got, &want, W))
        return 1;
    /* Two W-bit truncations of the same number, one of them summed
     * over ~150 series terms: a few thousand units in the last place
     * apart at worst, where a WRONG constant is apart by 2^-1 of
     * itself. 2^-(W-32) sits far outside the former and far inside the
     * latter. */
    if (!d.zero && cft_mp_exp2_of(&d) > -(long)(W - 32))
        return 1;
    state = 1;
    return 0;
}

int cft_mp_consts_selfcheck(void)
{
    static const struct { cft_mp_constant a, b; } pairs[3] = {
        { CFT_MP_C_LN2, CFT_MP_C_LOG2E },
        { CFT_MP_C_LN10, CFT_MP_C_LOG10E },
        { CFT_MP_C_PI, CFT_MP_C_INVPI },
    };
    const int W = 256;
    int i;
    if (pi_derivation_ok())
        return 1;
    for (i = 0; i < 3; i++) {
        cft_mp x, y, p, one, d;
        if (cft_mp_const(&x, pairs[i].a, W) ||
            cft_mp_const(&y, pairs[i].b, W))
            return 1;
        if (cft_mp_mul(&p, &x, &y, W))
            return 1;
        if (cft_mp_set_ui(&one, W, 0, 1, 0))
            return 1;
        if (cft_mp_sub(&d, &p, &one, W))
            return 1;
        /* The product of two W-bit truncations differs from 1 by at
         * most a handful of units in the last place; a wrong constant
         * differs by vastly more. 2^-(W-8) is far outside the former
         * and far inside the latter. */
        if (!d.zero && cft_mp_exp2_of(&d) > -(W - 8))
            return 1;
    }
    return 0;
}

/* ---- the rounding decision ----------------------------------------- */

/* Compare the whole enclosure [value - err*ulp, value + err*ulp]
 * against an integer, exactly. The screens in transcend.c ask only
 * "is this provably past the threshold", so an inconclusive answer is
 * always safe: it falls through to the ordinary path.
 *
 * cmp_mag compares m * 2^e against the non-negative integer t without
 * materialising either side at full width - a value exponent above 63
 * settles it, and so does one below zero. */
static int cmp_mag(const cft_bn *m, long e, uint64_t t)
{
    cft_bn tb, x;
    int i;
    if (cft_bn_is_zero(m))
        return t == 0 ? 0 : -1;
    if (t == 0)
        return 1;
    if (e + cft_bn_bitlen(m) > 80)
        return 1;                      /* > 2^79, far above any t */
    cft_bn_zero(&tb);
    for (i = 0; i < 2; i++)
        tb.v[i] = (uint32_t)(t >> (32 * i));
    tb.n = tb.v[1] ? 2 : (tb.v[0] ? 1 : 0);
    if (e >= 0) {
        if (cft_bn_shl(&x, m, (int)e))
            return 1;
        return cft_bn_cmp(&x, &tb);
    }
    if (-e > CFT_BN_BITS - 96)
        return -1;                     /* below 1, and t >= 1 */
    if (cft_bn_shl(&x, &tb, (int)(-e)))
        return -1;
    return cft_bn_cmp(m, &x);
}

/* The enclosure's two ends, as (significand, exponent) pairs.
 *
 * The half-width is the whole count, c * 2^k, as a bigint: the true
 * bound, whatever its size. A count of 2^L or more, L the
 * significand's width, is past the significand itself, so the
 * enclosure reaches zero before any conversion, and so does infinity;
 * below that the count is at most L + 1 bits. (A 32-bit half-width
 * once turned a decidable pow into CFT_ERR_INTERNAL, and until
 * 2026-09-30 a half-width that saturated at 2^40 decided on a clamp -
 * the header's history.) */
static void enclosure(const cft_mp *a, cft_bn *lo, cft_bn *hi, int *ok)
{
    cft_bn e;
    long L = cft_bn_bitlen(&a->m);
    *ok = 0;
    if (cft_mp_err_is_inf(a->err))
        return;
    if (a->err.c && (long)u64_bitlen(a->err.c) - 1 + a->err.k >= L)
        return;                        /* at least 2^L: reaches zero */
    cft_bn_zero(&e);
    e.v[0] = (uint32_t)a->err.c;
    e.v[1] = (uint32_t)(a->err.c >> 32);
    e.n = e.v[1] ? 2 : (e.v[0] ? 1 : 0);
    if (cft_bn_shl(&e, &e, a->err.k))
        return;
    if (cft_bn_cmp(&a->m, &e) <= 0)
        return;                        /* the enclosure reaches zero */
    cft_bn_sub(lo, &a->m, &e);
    if (cft_bn_add(hi, &a->m, &e))
        return;
    *ok = 1;
}

/* The comparison of one signed (m, exp) endpoint against t. */
static int cmp_signed(int sign, const cft_bn *m, long e, int64_t t)
{
    uint64_t mag;
    int c;
    if (cft_bn_is_zero(m))
        return t == 0 ? 0 : (t < 0 ? 1 : -1);
    if (!sign) {
        if (t < 0)
            return 1;
        return cmp_mag(m, e, (uint64_t)t);
    }
    if (t >= 0)
        return -1;
    mag = (uint64_t)(-(t + 1)) + 1u;
    c = cmp_mag(m, e, mag);
    return -c;
}

int cft_mp_cmp_int(const cft_mp *a, int64_t t)
{
    cft_bn lo, hi;
    int ok;
    if (a->zero)
        return t == 0 ? 0 : (t < 0 ? 1 : -1);
    enclosure(a, &lo, &hi, &ok);
    if (!ok)
        return 0;                      /* too wide to decide: fall through */
    if (a->sign) {
        /* the enclosure of the VALUE runs from -(hi) up to -(lo) */
        if (cmp_signed(1, &hi, a->exp, t) > 0)
            return 1;
        if (cmp_signed(1, &lo, a->exp, t) < 0)
            return -1;
        return 0;
    }
    if (cmp_signed(0, &lo, a->exp, t) > 0)
        return 1;
    if (cmp_signed(0, &hi, a->exp, t) < 0)
        return -1;
    return 0;
}

int cft_mp_round(const cft_mp *a, int sign, const cft_fmt_desc *f, int rnd,
                 cft_bn *out, uint32_t *flags, int *decided)
{
    cft_bn lo, hi;
    cft_bn blo, bhi;
    uint32_t flo = 0, fhi = 0;
    int ok;

    *decided = 0;
    if (a->zero)
        return 1;                 /* the callers never round an exact 0 */
    if (a->exp > (1L << 24) || a->exp < -(1L << 24))
        return 1;                 /* the screens keep this unreachable */

    enclosure(a, &lo, &hi, &ok);
    if (!ok)
        return 0;                 /* too wide to decide: escalate */

    if (cft_sf_round_pack(f, sign, &lo, (int)a->exp, 0, rnd, &blo, &flo))
        return 1;
    if (cft_sf_round_pack(f, sign, &hi, (int)a->exp, 0, rnd, &bhi, &fhi))
        return 1;
    if (cft_bn_cmp(&blo, &bhi) != 0 || flo != fhi)
        return 0;

    cft_bn_copy(out, &blo);
    *flags = flo | CFT_SF_INEXACT;
    *decided = 1;
    return 0;
}

#else  /* CFT_NO_TRANSCEND */

/* An empty translation unit is not strictly conforming C99 and
 * -Wpedantic says so, so leave one declaration behind. */
typedef int cft_mpfloat_module_omitted;

#endif /* CFT_NO_TRANSCEND */
