/* Copyright 2026 Logan W.
 * SPDX-License-Identifier: Apache-2.0
 *
 * cert_exact.h - the exact arithmetic of a version-1 certificate's
 * accuracy entries (docs/CERTIFICATES.md, "Accuracy entries" and "The
 * width rule"), shared by the two C tools that need it:
 *
 *   cft-audit  (tools/audit.c)   re-derives every entry's value, and holds
 *                                it to the value written (step 10)
 *   cft-segrun (tools/segrun.c)  writes the entries: each value computed
 *                                from the boundary states it wrote
 *
 * It was cft-audit's until the certificate plan's step 5 (docs/ROADMAP.md,
 * "Steps 5 and 6"; parcel S1, 2026-09-30), and was moved here whole, so
 * that the writer and the C auditor compute every value with one code.
 * The golden model, python/cft_golden/cert.py, is the authority: each
 * function names the one it follows.
 *
 * NOTHING HERE PRINTS OR EXITS. Every function that can fail returns a
 * status, and a `why` where the caller may print one:
 *   CX_OK
 *   one of the page's refusal names (cx_name): width, accuracy-finite,
 *     accuracy-run, accuracy-scope, accuracy-slot, malformed
 *   CX_INTERNAL   an exact step past the bigint, which the width rule makes
 *                 impossible for in-rule operands; not a verdict
 *   CX_LIBRARY    a library call that failed (the rounding's
 *                 cft_from_hex_char); not a verdict either
 * Each tool keeps its own refusal and exit paths around these calls: the
 * auditor's refuse() with its locations, the writer's with its cleanup.
 *
 * HEADER-ONLY, AND EVERY DEFINITION CX_FN or CX_TABLE: static, with GCC's
 * `unused` attribute (the lead's condition, 2026-09-30). Two tools include
 * it, each in several builds (the tool, the narrow builds, the probe, the
 * plant build), and each calls a different part of it; gcc warns for a
 * static function or table defined and not called (measured: gcc 16.1,
 * -Wall), and the project's builds are warning-free. The attribute is on
 * every definition rather than on a hand-kept list of the ones some build
 * leaves uncalled, since that list changes with the build.
 *
 * Exact values go through libcft's own bigint, cft_bn (src/bigint.h, an
 * internal header: the lead's decision, 2026-09-29), which the width rule
 * was sized for: every in-rule step needs at most 2 x 1,023 + 1 bits. It
 * has no division, no gcd and a left shift that keeps a spare limb; those
 * three are here. A build whose cft_bn is narrower than 2,047 bits gets no
 * exact arithmetic at all (CX_EXACT is 0): the formats, the directions,
 * the method words and an element's decoding stay, and each tool refuses
 * an exact value by its own name, build-width.
 */
#ifndef CFT_CERT_EXACT_H
#define CFT_CERT_EXACT_H

#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

#include "cft.h"
#include "../src/bigint.h"

#if defined(__GNUC__)
#  define CX_FN    static __attribute__((unused))
#  define CX_TABLE static __attribute__((unused))
#else
#  define CX_FN    static
#  define CX_TABLE static
#endif

/* The width rule: 1,023 bits a numerator or a denominator. One exact step
 * on two in-rule values needs 2 x 1,023 + 1 bits, so a cft_bn narrower
 * than that is not a conforming auditor, or writer, of exact values. */
#define CX_WIDTH_BITS  1023
#define CX_EXACT       (CFT_BN_LIMBS * 32 >= 2 * CX_WIDTH_BITS + 1)

/* ---- statuses --------------------------------------------------------- */

enum {
    CX_OK = 0,
    CX_WIDTH,           /* width            */
    CX_FINITE,          /* accuracy-finite  */
    CX_RUN,             /* accuracy-run     */
    CX_SCOPE,           /* accuracy-scope   */
    CX_SLOT,            /* accuracy-slot    */
    CX_MALFORMED,       /* malformed        */
    CX_INTERNAL,        /* not a verdict: an exact step past the bigint */
    CX_LIBRARY          /* not a verdict: a library call that failed    */
};

/* The page's name for a status, or NULL for CX_OK and the two that are no
 * verdict. */
CX_FN const char *cx_name(int st)
{
    static const char *const NAME[] = {
        NULL, "width", "accuracy-finite", "accuracy-run", "accuracy-scope",
        "accuracy-slot", "malformed", NULL, NULL };
    return st >= 0 && st <= CX_LIBRARY ? NAME[st] : NULL;
}

/* ---- the formats, and the rounding directions ------------------------- */

typedef struct {
    const char *name;
    int width, ew, mw;          /* bits: whole, exponent, trailing significand */
} fmt_t;

CX_TABLE const fmt_t FMT[4] = {
    { "fp32", 32, 8, 23 }, { "fp64", 64, 11, 52 },
    { "fp128", 128, 15, 112 }, { "fp256", 256, 19, 236 },
};
#define ESZ(f)   ((size_t)FMT[f].width / 8)
#define PREC(f)  (FMT[f].mw + 1)
#define BIAS(f)  ((1L << (FMT[f].ew - 1)) - 1)
#define EMIN(f)  (1 - BIAS(f))

/* IEEE 754-2019's attributes, in the page's order */
enum { R_RNE, R_RTZ, R_RDN, R_RUP, R_RMM };
CX_TABLE const char *const RND_NAME[5] = { "rne", "rtz", "rdn", "rup", "rmm" };
CX_TABLE const cft_round RND_CODE[5] = { CFT_RNE, CFT_RTZ, CFT_RDN, CFT_RUP,
                                         CFT_RMM };

/* ---- the certificate's words ------------------------------------------ */

enum { K_MAIN, K_HALF, K_WIDER, K_WSRC };       /* a run's kind */
CX_TABLE const char *const KIND_NAME[4] = { "main", "half-step", "wider",
                                            "wider-source" };
enum { M_DRIFT, M_HALVING, M_WIDER, M_WSRC };   /* an entry's method */
CX_TABLE const char *const METHOD_NAME[4] = { "drift", "step-halving",
                                              "wider", "wider-source" };
CX_TABLE const char *const KINDS[3] = { "bound", "estimate", "measurement" };
CX_TABLE const int METHOD_KIND[4] = { 2, 1, 1, 1 }; /* measurement, estimate */
enum { V_EXACT, V_ROUNDED, V_ENCLOSED };        /* a value's form */

#define MAX_TERMS    64
#define MAX_FACTORS  8
#define MAX_SLOT     0xFFFFu   /* a term's slot: the scratch counts are 16-bit */

/* ---- hex --------------------------------------------------------------- */

CX_FN int is_hexl(char c)
{
    return (c >= '0' && c <= '9') || (c >= 'a' && c <= 'f');
}

CX_FN int hexval(char c)
{
    return c <= '9' ? c - '0' : c - 'a' + 10;
}

/* ---- cft_bn: the library's bigint, and what it lacks ------------------- */

CX_FN void bn_norm(cft_bn *r)
{
    while (r->n > 0 && r->v[r->n - 1] == 0)
        r->n--;
}

CX_FN int bn_is_one(const cft_bn *a)
{
    return a->n == 1 && a->v[0] == 1;
}

CX_FN int bn_tz(const cft_bn *a)                /* a nonzero */
{
    int i, b;
    for (i = 0; i < a->n; i++) {
        uint32_t w = a->v[i];
        if (w) {
            b = 0;
            while (!(w & 1u)) {
                w >>= 1;
                b++;
            }
            return i * 32 + b;
        }
    }
    return 0;
}

/* r = a << k, exactly: 1 only if the result has more than CFT_BN_BITS
 * bits. (cft_bn_shl keeps a spare limb and refuses any shift of a value
 * that fills the container, a shift by 0 included.) r may alias a. */
CX_FN int bn_shl(cft_bn *r, const cft_bn *a, int k)
{
    int limbs = k >> 5, bits = k & 31, an = a->n, len, rn, i;
    if (a->n == 0) {
        r->n = 0;
        return 0;
    }
    len = cft_bn_bitlen(a);
    if (k < 0 || len > CFT_BN_BITS - k)
        return 1;
    rn = (len + k + 31) >> 5;
    for (i = rn - 1; i >= 0; i--) {
        int ih = i - limbs, il = i - limbs - 1;
        uint32_t hi = (ih >= 0 && ih < an) ? a->v[ih] : 0u;
        uint32_t lo = (il >= 0 && il < an) ? a->v[il] : 0u;
        r->v[i] = bits ? ((hi << bits) | (lo >> (32 - bits))) : hi;
    }
    r->n = rn;
    return 0;
}

/* q = a / b and rem = a % b (b nonzero), by shift and subtract; q or rem
 * may be NULL, and either may alias a or b. CX_INTERNAL only if the
 * aligned divisor did not fit, which it always does (its bits are a's). */
CX_FN int bn_divmod(cft_bn *q, cft_bn *rem, const cft_bn *a, const cft_bn *b)
{
    cft_bn r, d, quo;
    int la = cft_bn_bitlen(a), lb = cft_bn_bitlen(b), s, i;
    cft_bn_copy(&r, a);
    cft_bn_zero(&quo);
    if (la >= lb) {
        s = la - lb;
        if (bn_shl(&d, b, s))
            return CX_INTERNAL;
        for (i = s; i >= 0; i--) {
            if (cft_bn_cmp(&r, &d) >= 0) {
                cft_bn_sub(&r, &r, &d);
                cft_bn_setbit(&quo, i);
            }
            cft_bn_shr(&d, &d, 1);
        }
    }
    if (q)
        cft_bn_copy(q, &quo);
    if (rem)
        cft_bn_copy(rem, &r);
    return CX_OK;
}

/* a / d for one limb d, into q (which may alias a); the remainder back */
CX_FN uint32_t bn_div_u32(cft_bn *q, const cft_bn *a, uint32_t d)
{
    uint64_t r = 0;
    int i;
    for (i = a->n - 1; i >= 0; i--) {
        uint64_t cur = (r << 32) | a->v[i];
        q->v[i] = (uint32_t)(cur / d);
        r = cur % d;
    }
    q->n = a->n;
    bn_norm(q);
    return (uint32_t)r;
}

CX_FN uint32_t gcd_u32(uint32_t a, uint32_t b)
{
    while (b) {
        uint32_t t = a % b;
        a = b;
        b = t;
    }
    return a;
}

/* g = gcd(a, b): the common power of two, then Stein on the odd parts,
 * with a single-limb Euclid once either part fits one limb. CX_INTERNAL
 * only if the common power of two did not fit back, which it always does
 * (g is at most the smaller of the two). */
CX_FN int bn_gcd(cft_bn *g, const cft_bn *a0, const cft_bn *b0)
{
    cft_bn a, b;
    int za, zb, k;
    if (cft_bn_is_zero(a0)) {
        cft_bn_copy(g, b0);
        return CX_OK;
    }
    if (cft_bn_is_zero(b0)) {
        cft_bn_copy(g, a0);
        return CX_OK;
    }
    za = bn_tz(a0);
    zb = bn_tz(b0);
    k = za < zb ? za : zb;
    cft_bn_shr(&a, a0, za);
    cft_bn_shr(&b, b0, zb);
    for (;;) {
        int c;
        if (bn_is_one(&a) || bn_is_one(&b)) {
            cft_bn_set_u32(g, 1);
            break;
        }
        if (b.n == 1 || a.n == 1) {
            const cft_bn *big = b.n == 1 ? &a : &b;
            uint32_t small = b.n == 1 ? b.v[0] : a.v[0];
            cft_bn t;
            uint32_t r = bn_div_u32(&t, big, small);
            cft_bn_set_u32(g, gcd_u32(small, r));
            break;
        }
        c = cft_bn_cmp(&a, &b);
        if (c == 0) {
            cft_bn_copy(g, &a);
            break;
        }
        if (c > 0) {
            cft_bn_sub(&a, &a, &b);
            cft_bn_shr(&a, &a, bn_tz(&a));
        } else {
            cft_bn_sub(&b, &b, &a);
            cft_bn_shr(&b, &b, bn_tz(&b));
        }
    }
    if (k && bn_shl(g, g, k))
        return CX_INTERNAL;
    return CX_OK;
}

/* h[0..len): lowercase hex, no sign. CX_INTERNAL past the bigint. */
CX_FN int bn_from_hex(cft_bn *r, const char *h, size_t len)
{
    size_t i;
    int limbs = (int)((4 * len + 31) / 32);
    if (limbs > CFT_BN_LIMBS)
        return CX_INTERNAL;
    for (i = 0; i < (size_t)limbs; i++)
        r->v[i] = 0;
    for (i = 0; i < len; i++) {
        size_t bit = 4 * (len - 1 - i);
        r->v[bit / 32] |= (uint32_t)hexval(h[i]) << (bit % 32);
    }
    r->n = limbs;
    bn_norm(r);
    return CX_OK;
}

/* lowercase hex, no leading zeros; "0" for zero. `out` holds at least
 * CFT_BN_BITS / 4 + 1 bytes. */
CX_FN void bn_hex(const cft_bn *a, char *out)
{
    static const char D[] = "0123456789abcdef";
    int nib = (cft_bn_bitlen(a) + 3) / 4, i;
    if (nib == 0) {
        strcpy(out, "0");
        return;
    }
    for (i = 0; i < nib; i++)
        out[i] = D[cft_bn_extract(a, 4 * (nib - 1 - i), 4)];
    out[nib] = 0;
}

/* ---- elements ---------------------------------------------------------- */

enum { EL_ZERO, EL_FINITE, EL_INF, EL_NAN };

typedef struct {
    int kind, sign;
    cft_bn m;       /* EL_FINITE: the significand, odd */
    long e;         /* EL_FINITE: the value is (-1)^sign m 2^e, m odd */
} elem_t;

/* An encoding's value (cert.element_fraction), reduced: m odd. */
CX_FN void decode(int f, const uint8_t *le, elem_t *x)
{
    cft_bn b;
    uint32_t biased, emask = (1u << FMT[f].ew) - 1u;
    int z;
    cft_bn_load(&b, le, (int)ESZ(f));
    x->sign = cft_bn_bit(&b, FMT[f].width - 1);
    biased = cft_bn_extract(&b, FMT[f].mw, FMT[f].ew);
    cft_bn_copy(&x->m, &b);
    cft_bn_mask(&x->m, FMT[f].mw);
    if (biased == emask) {
        x->kind = cft_bn_is_zero(&x->m) ? EL_INF : EL_NAN;
        return;
    }
    if (biased == 0) {
        if (cft_bn_is_zero(&x->m)) {
            x->kind = EL_ZERO;
            return;
        }
        x->e = EMIN(f) - FMT[f].mw;
    } else {
        cft_bn_setbit(&x->m, FMT[f].mw);
        x->e = (long)biased - BIAS(f) - FMT[f].mw;
    }
    x->kind = EL_FINITE;
    z = bn_tz(&x->m);
    cft_bn_shr(&x->m, &x->m, z);
    x->e += z;
}

/* The bits of a finite element's exact value, reduced: numerator and
 * denominator. Zero is 0/1. */
CX_FN void elem_bits(const elem_t *x, long *nb, long *db)
{
    if (x->kind == EL_ZERO) {
        *nb = 0;
        *db = 1;
        return;
    }
    *nb = cft_bn_bitlen(&x->m) + (x->e > 0 ? x->e : 0);
    *db = x->e < 0 ? -x->e + 1 : 1;
}

/* an element's order key: -inf 0, finite 1, +inf 2 (NaNs never reach) */
CX_FN int order_kind(int f, const uint8_t *le)
{
    elem_t x;
    decode(f, le, &x);
    if (x.kind == EL_INF)
        return x.sign ? 0 : 2;
    return 1;
}

/* A finite end of an enclosure held to the width rule (the reader's
 * check, cert._Reader.value, and so the writer's): CX_WIDTH when its exact
 * value is past it. An infinite end compares by its sign alone. `which` is
 * "lower" or "upper". */
CX_FN int cx_end_in_rule(int f, const uint8_t *le, const char *which,
                         char *why, size_t cap)
{
    elem_t x;
    long nb, db;
    decode(f, le, &x);
    if (x.kind != EL_ZERO && x.kind != EL_FINITE)
        return CX_OK;
    elem_bits(&x, &nb, &db);
    if (nb > CX_WIDTH_BITS || db > CX_WIDTH_BITS) {
        snprintf(why, cap, "the %s end's exact value needs a %ld-bit "
                 "numerator and a %ld-bit denominator; version 1 allows %d "
                 "bits each", which, nb, db, CX_WIDTH_BITS);
        return CX_WIDTH;
    }
    return CX_OK;
}

#if CX_EXACT
/* ---- rationals, exact, under the width rule ---------------------------- */

typedef struct { int neg; cft_bn n, d; } rat;   /* reduced, d > 0; 0 is 0/1 */

/* rat_text's buffer: a sign, two parts of at most CFT_BN_BITS / 4 hex
 * digits, a slash and the NUL */
#define CX_RAT_TEXT (2 * (CFT_BN_BITS / 4) + 8)

CX_FN void rat_zero(rat *r)
{
    r->neg = 0;
    cft_bn_zero(&r->n);
    cft_bn_set_u32(&r->d, 1);
}

CX_FN int rat_reduce(rat *r)
{
    cft_bn g, odd;
    int z;
    if (cft_bn_is_zero(&r->n)) {
        rat_zero(r);
        return CX_OK;
    }
    if (bn_gcd(&g, &r->n, &r->d))
        return CX_INTERNAL;
    if (bn_is_one(&g))
        return CX_OK;
    z = bn_tz(&g);
    cft_bn_shr(&odd, &g, z);
    cft_bn_shr(&r->n, &r->n, z);
    cft_bn_shr(&r->d, &r->d, z);
    if (bn_is_one(&odd))
        return CX_OK;
    if (odd.n == 1) {
        bn_div_u32(&r->n, &r->n, odd.v[0]);
        bn_div_u32(&r->d, &r->d, odd.v[0]);
    } else if (bn_divmod(&r->n, NULL, &r->n, &odd) ||
               bn_divmod(&r->d, NULL, &r->d, &odd)) {
        return CX_INTERNAL;
    }
    return CX_OK;
}

CX_FN int rat_in_rule(const rat *r)
{
    return cft_bn_bitlen(&r->n) <= CX_WIDTH_BITS &&
           cft_bn_bitlen(&r->d) <= CX_WIDTH_BITS;
}

/* The width rule, on a value just computed (cert._checked). */
CX_FN int cx_rule(const rat *r, const char *what, char *why, size_t cap)
{
    if (rat_in_rule(r))
        return CX_OK;
    snprintf(why, cap, "%s needs a %d-bit numerator and a %d-bit "
             "denominator; version 1 allows %d bits each", what,
             cft_bn_bitlen(&r->n), cft_bn_bitlen(&r->d), CX_WIDTH_BITS);
    return CX_WIDTH;
}

/* r = a b, a + b, a - b; r may alias either. CX_INTERNAL past the bigint,
 * which two in-rule operands never reach (2,046 and 2,047 bits). */
CX_FN int rat_mul(rat *r, const rat *a, const rat *b)
{
    rat t;
    t.neg = a->neg ^ b->neg;
    if (cft_bn_mul(&t.n, &a->n, &b->n) || cft_bn_mul(&t.d, &a->d, &b->d))
        return CX_INTERNAL;
    if (rat_reduce(&t))
        return CX_INTERNAL;
    *r = t;
    return CX_OK;
}

CX_FN int rat_add(rat *r, const rat *a, const rat *b)
{
    cft_bn x, y;
    rat t;
    if (cft_bn_mul(&x, &a->n, &b->d) || cft_bn_mul(&y, &b->n, &a->d) ||
        cft_bn_mul(&t.d, &a->d, &b->d))
        return CX_INTERNAL;
    if (a->neg == b->neg) {
        if (cft_bn_add(&t.n, &x, &y))
            return CX_INTERNAL;
        t.neg = a->neg;
    } else if (cft_bn_cmp(&x, &y) >= 0) {
        cft_bn_sub(&t.n, &x, &y);
        t.neg = a->neg;
    } else {
        cft_bn_sub(&t.n, &y, &x);
        t.neg = b->neg;
    }
    if (rat_reduce(&t))
        return CX_INTERNAL;
    *r = t;
    return CX_OK;
}

CX_FN int rat_sub(rat *r, const rat *a, const rat *b)
{
    rat nb = *b;
    if (!cft_bn_is_zero(&nb.n))
        nb.neg = !nb.neg;
    return rat_add(r, a, &nb);
}

/* *c = -1, 0 or 1 as a is below, at or above b. CX_INTERNAL past the
 * bigint, which two in-rule operands never reach. */
CX_FN int rat_cmp(const rat *a, const rat *b, int *c)
{
    cft_bn x, y;
    if (a->neg != b->neg) {
        *c = a->neg ? -1 : 1;
        return CX_OK;
    }
    if (cft_bn_mul(&x, &a->n, &b->d) || cft_bn_mul(&y, &b->n, &a->d))
        return CX_INTERNAL;
    *c = cft_bn_cmp(&x, &y);
    if (a->neg)
        *c = -*c;
    return CX_OK;
}

CX_FN int rat_eq(const rat *a, const rat *b)
{
    return a->neg == b->neg && cft_bn_cmp(&a->n, &b->n) == 0 &&
           cft_bn_cmp(&a->d, &b->d) == 0;
}

/* the page's one spelling: hex numerator (signed), '/', hex denominator;
 * `out` holds CX_RAT_TEXT bytes */
CX_FN void rat_text(const rat *r, char *out)
{
    if (r->neg)
        *out++ = '-';
    bn_hex(&r->n, out);
    out += strlen(out);
    *out++ = '/';
    bn_hex(&r->d, out);
}

/* A finite element's exact value: CX_OK, CX_FINITE if it is not finite,
 * CX_WIDTH if it is past the rule (nothing is computed past it), or
 * CX_INTERNAL. */
CX_FN int rat_of_elem(rat *r, const elem_t *x)
{
    long nb, db;
    if (x->kind == EL_INF || x->kind == EL_NAN)
        return CX_FINITE;
    elem_bits(x, &nb, &db);
    if (nb > CX_WIDTH_BITS || db > CX_WIDTH_BITS)
        return CX_WIDTH;
    rat_zero(r);
    if (x->kind == EL_ZERO)
        return CX_OK;
    r->neg = x->sign;
    if (x->e >= 0) {
        if (bn_shl(&r->n, &x->m, (int)x->e))
            return CX_INTERNAL;
    } else {
        cft_bn one;
        cft_bn_copy(&r->n, &x->m);
        cft_bn_set_u32(&one, 1);
        if (bn_shl(&r->d, &one, (int)-x->e))
            return CX_INTERNAL;
    }
    return CX_OK;
}

/* cert._exact: an element's exact value under the width rule; a
 * non-finite one has none, refused by name. */
CX_FN int cx_exact(rat *r, int f, const uint8_t *le, const char *what,
                   char *why, size_t cap)
{
    static const char *const WORD[4] = { "finite", "finite", "inf", "nan" };
    elem_t x;
    long nb, db;
    int st;
    decode(f, le, &x);
    st = rat_of_elem(r, &x);
    if (st == CX_FINITE)
        snprintf(why, cap, "%s is %s%s; an exact value needs a finite "
                 "element", what, x.kind == EL_INF && x.sign ? "-" : "",
                 WORD[x.kind]);
    else if (st == CX_WIDTH) {
        elem_bits(&x, &nb, &db);
        snprintf(why, cap, "%s needs a %ld-bit numerator and a %ld-bit "
                 "denominator; version 1 allows %d bits each", what, nb, db,
                 CX_WIDTH_BITS);
    } else if (st)
        snprintf(why, cap, "%s: its exact value past the bigint", what);
    return st;
}

/* q correctly rounded into format f under rnd (cert.round_rational): one
 * division leaves m and a sticky, as _round_rational's does, and
 * cft_from_hex_char on `host` rounds the dyadic value (2m + 1) 2^(q - 1) -
 * or m 2^q, exact - which is round_pack's answer for it. Zero is +0.
 * CX_INTERNAL past the bigint; CX_LIBRARY if the library refuses. */
CX_FN int cx_round(cft_device *host, const rat *q, int f, int rnd,
                   uint8_t *out)
{
    cft_bn m, rem, t;
    long w = PREC(f) + 3, qe;
    char hex[CFT_BN_BITS / 4 + 8], buf[CFT_BN_BITS / 4 + 64];
    const char *in[1];
    size_t bad = 0;
    uint32_t fl = 0;
    if (cft_bn_is_zero(&q->n)) {
        memset(out, 0, ESZ(f));
        return CX_OK;
    }
    qe = (long)(cft_bn_bitlen(&q->n) - cft_bn_bitlen(&q->d)) - w;
    if (qe >= 0) {
        if (bn_shl(&t, &q->d, (int)qe) || bn_divmod(&m, &rem, &q->n, &t))
            return CX_INTERNAL;
    } else {
        if (bn_shl(&t, &q->n, (int)-qe) || bn_divmod(&m, &rem, &t, &q->d))
            return CX_INTERNAL;
    }
    if (!cft_bn_is_zero(&rem)) {
        if (bn_shl(&m, &m, 1) || cft_bn_inc(&m))
            return CX_INTERNAL;
        qe -= 1;
    }
    bn_hex(&m, hex);
    snprintf(buf, sizeof buf, "%s0x%sp%ld", q->neg ? "-" : "", hex, qe);
    in[0] = buf;
    if (cft_from_hex_char(host, (cft_format)f, RND_CODE[rnd], in, out, 1,
                          &bad, &fl) != CFT_OK)
        return CX_LIBRARY;
    return CX_OK;
}

/* A rational's token in its one spelling, in lowest terms, under the
 * width rule (cert._Reader.rational), in the page's order: its spelling
 * (CX_MALFORMED); each part's DIGITS against the rule, before anything is
 * converted or reduced (CX_WIDTH), so that no token past 1,023 bits is
 * ever held; zero's one spelling, 0/1; last, lowest terms (CX_MALFORMED).
 * `what` names it in `why`. */
CX_FN int cx_rat_parse(const char *tok, rat *q, const char *what, char *why,
                       size_t cap)
{
    const char *p = tok, *num, *slash, *den = NULL;
    size_t nl = 0, dl = 0, i;
    int neg = 0, ok = 1;
    long nbits, dbits;
    cft_bn g;
    if (*p == '-') {
        neg = 1;
        p++;
    }
    num = p;
    slash = strchr(p, '/');
    if (!slash) {
        ok = 0;
    } else {
        nl = (size_t)(slash - num);
        den = slash + 1;
        dl = strlen(den);
        if (nl == 0 || dl == 0)
            ok = 0;
        for (i = 0; ok && i < nl; i++)
            ok = is_hexl(num[i]);
        for (i = 0; ok && i < dl; i++)
            ok = is_hexl(den[i]);
        if (ok && num[0] == '0' && (nl > 1 || neg))
            ok = 0;             /* 0 alone, unsigned; else no leading zero */
        if (ok && den[0] == '0')
            ok = 0;
    }
    if (!ok) {
        /* the golden's two reasons: a zero denominator, or the spelling */
        const char *s = tok;
        int zero_den = 0;
        if (*s == '-')
            s++;
        if (*s && *s != '/') {
            const char *t = s;
            while (*t && is_hexl(*t))
                t++;
            if (*t == '/' && t[1]) {
                const char *u = t + 1;
                while (*u == '0')
                    u++;
                zero_den = *u == 0;
            }
        }
        snprintf(why, cap, "%s '%.80s': %s", what, tok, zero_den ?
                 "a zero denominator" : "not hex numerator/denominator in "
                 "their one spelling (lowercase, no leading zeros, the sign "
                 "on the numerator, no '+')");
        return CX_MALFORMED;
    }
    /* the width rule by the digits alone, FIRST - before zero's spelling
     * and before any gcd (P3's design, approved 2026-09-29) */
    nbits = num[0] == '0' ? 0 : (long)(4 * (nl - 1)) +
            (hexval(num[0]) >= 8 ? 4 : hexval(num[0]) >= 4 ? 3 :
             hexval(num[0]) >= 2 ? 2 : 1);
    dbits = (long)(4 * (dl - 1)) + (hexval(den[0]) >= 8 ? 4 :
             hexval(den[0]) >= 4 ? 3 : hexval(den[0]) >= 2 ? 2 : 1);
    if (nbits > CX_WIDTH_BITS || dbits > CX_WIDTH_BITS) {
        snprintf(why, cap, "%s needs a %ld-bit numerator and a %ld-bit "
                 "denominator; version 1 allows %d bits each", what, nbits,
                 dbits, CX_WIDTH_BITS);
        return CX_WIDTH;
    }
    if (num[0] == '0' && !(dl == 1 && den[0] == '1')) {
        snprintf(why, cap, "%s '%.80s': zero is spelled 0/1", what, tok);
        return CX_MALFORMED;
    }
    q->neg = neg;
    if (bn_from_hex(&q->n, num, nl) || bn_from_hex(&q->d, den, dl) ||
        bn_gcd(&g, &q->n, &q->d)) {
        snprintf(why, cap, "%s '%.80s': past the bigint", what, tok);
        return CX_INTERNAL;
    }
    if (!bn_is_one(&g)) {
        snprintf(why, cap, "%s '%.80s' is not in lowest terms", what, tok);
        return CX_MALFORMED;
    }
    return CX_OK;
}

/* ---- an entry: its definition, its value ------------------------------- */

typedef struct {
    rat coef;
    unsigned n;                     /* its factors; past MAX_FACTORS is refused */
    uint64_t slot[MAX_FACTORS];     /* uint64: a writer checks any slot it is
                                       handed against the state (accuracy-slot) */
} term_t;

typedef struct {
    int form, fmt, rnd;
    rat exact;
    uint8_t bits[32], lo[32], hi[32];
} value_t;

typedef struct {
    int method;
    uint64_t uses;
    int has_lane;
    uint64_t lane;
    unsigned n_terms;
    term_t *terms;
    value_t value;
} entry_t;

/* A run as an entry reads it: its kind, its program's format and slots a
 * lane, its lanes and its segments S (boundary S is its final state). */
typedef struct {
    int kind, fmt;
    uint64_t lanes, S;
    uint32_t nslots;
} cx_run;

/* cert.derive's checks of an entry against the runs, in its order: the
 * run it uses exists (`used` NULL when it does not); an estimate's run is
 * an auxiliary run of the method's kind, with run 0's lanes and slots a
 * lane; the lane is the run's; a drift's slots are its state's. */
CX_FN int cx_entry_check(const entry_t *E, uint64_t n_runs,
                         const cx_run *main_run, const cx_run *used,
                         char *why, size_t cap)
{
    unsigned t, s;
    if (E->uses >= n_runs || !used) {
        snprintf(why, cap, "entry uses run %llu, and the certificate has "
                 "%llu", (unsigned long long)E->uses,
                 (unsigned long long)n_runs);
        return CX_RUN;
    }
    if (E->method != M_DRIFT) {
        int want = E->method == M_HALVING ? K_HALF :
                   E->method == M_WSRC ? K_WSRC : K_WIDER;
        if (E->uses == 0 || used->kind != want) {
            snprintf(why, cap, "a %s estimate compares run 0 with a %s run; "
                     "run %llu is %s", METHOD_NAME[E->method],
                     KIND_NAME[want], (unsigned long long)E->uses,
                     E->uses == 0 ? "the main run" : KIND_NAME[used->kind]);
            return CX_RUN;
        }
        /* the lead's decision, 2026-09-30, golden-first (cert.derive) */
        if (used->lanes != main_run->lanes ||
            used->nslots != main_run->nslots) {
            snprintf(why, cap, "a %s estimate compares run 0's final state "
                     "with run %llu's, lane by lane and slot by slot; run "
                     "%llu is %llu lanes of %lu slots and run 0 is %llu "
                     "lanes of %lu", METHOD_NAME[E->method],
                     (unsigned long long)E->uses, (unsigned long long)E->uses,
                     (unsigned long long)used->lanes,
                     (unsigned long)used->nslots,
                     (unsigned long long)main_run->lanes,
                     (unsigned long)main_run->nslots);
            return CX_RUN;
        }
    }
    if (E->has_lane && E->lane >= used->lanes) {
        snprintf(why, cap, "lane %llu of a run of %llu lanes",
                 (unsigned long long)E->lane,
                 (unsigned long long)used->lanes);
        return CX_SCOPE;
    }
    if (E->method == M_DRIFT)
        for (t = 0; t < E->n_terms; t++)
            for (s = 0; s < E->terms[t].n && s < MAX_FACTORS; s++)
                if (E->terms[t].slot[s] >= used->nslots) {
                    snprintf(why, cap, "a term names slot %llu; run %llu's "
                             "state has %lu slots a lane",
                             (unsigned long long)E->terms[t].slot[s],
                             (unsigned long long)E->uses,
                             (unsigned long)used->nslots);
                    return CX_SLOT;
                }
    return CX_OK;
}

/* The two states an entry reads, as (run, boundary) in cert.derive's
 * order: a drift's run r at boundary 0 and then at S; an estimate's run 0
 * at its S and then run r at its own. */
CX_FN void cx_entry_needs(const entry_t *E, const cx_run *main_run,
                          const cx_run *used, uint64_t need[2][2])
{
    if (E->method == M_DRIFT) {
        need[0][0] = E->uses;
        need[0][1] = 0;
    } else {
        need[0][0] = 0;
        need[0][1] = main_run->S;
    }
    need[1][0] = E->uses;
    need[1][1] = used->S;
}

/* One lane's quantity, Q(state) = ((T_1 + T_2) + T_3) + ..., each term
 * ((c x v_1) x v_2) x ..., every value held to the rule as it is reached. */
CX_FN int cx_quantity(rat *q, const entry_t *E, int f, const uint8_t *state,
                      uint64_t i, uint32_t nslots, const char *which,
                      char *why, size_t cap)
{
    unsigned t, s;
    char what[160];
    int st;
    rat_zero(q);
    for (t = 0; t < E->n_terms; t++) {
        const term_t *T = &E->terms[t];
        rat p = T->coef;
        for (s = 0; s < T->n; s++) {
            rat v;
            snprintf(what, sizeof what, "lane %llu slot %llu of the %s state",
                     (unsigned long long)i, (unsigned long long)T->slot[s],
                     which);
            st = cx_exact(&v, f, state + ((size_t)i * nslots +
                                          (size_t)T->slot[s]) * ESZ(f),
                          what, why, cap);
            if (st)
                return st;
            if (rat_mul(&p, &p, &v)) {
                snprintf(why, cap, "term %u's product, lane %llu, past the "
                         "bigint", t, (unsigned long long)i);
                return CX_INTERNAL;
            }
            snprintf(what, sizeof what, "term %u's product, lane %llu", t,
                     (unsigned long long)i);
            if ((st = cx_rule(&p, what, why, cap)))
                return st;
        }
        if (rat_add(q, q, &p)) {
            snprintf(why, cap, "the quantity's sum at term %u, lane %llu, "
                     "past the bigint", t, (unsigned long long)i);
            return CX_INTERNAL;
        }
        snprintf(what, sizeof what, "the quantity's sum at term %u, lane %llu",
                 t, (unsigned long long)i);
        if ((st = cx_rule(q, what, why, cap)))
            return st;
    }
    return CX_OK;
}

/* The entry's value, "The functions, exactly" (cert.derive's arithmetic),
 * from the two states cx_entry_needs names, in its order: `a` is a drift's
 * initial state or an estimate's F0, `b` a drift's final state or its Fr.
 * The entry has passed cx_entry_check. */
CX_FN int cx_entry_value(const entry_t *E, const cx_run *main_run,
                         const cx_run *used, const uint8_t *a,
                         const uint8_t *b, rat *out, char *why, size_t cap)
{
    uint64_t i, first = E->has_lane ? E->lane : 0;
    uint64_t last = E->has_lane ? E->lane + 1 : used->lanes;
    uint32_t nslots = used->nslots;
    int f = used->fmt, have = 0, st, c = 0;
    rat best;
    char what[160];
    rat_zero(&best);
    if (E->method == M_DRIFT) {
        for (i = first; i < last; i++) {
            rat qf, qi, d;
            if ((st = cx_quantity(&qf, E, f, b, i, nslots, "final", why,
                                  cap)) ||
                (st = cx_quantity(&qi, E, f, a, i, nslots, "initial", why,
                                  cap)))
                return st;
            if (rat_sub(&d, &qf, &qi)) {
                snprintf(why, cap, "the drift of lane %llu, past the bigint",
                         (unsigned long long)i);
                return CX_INTERNAL;
            }
            snprintf(what, sizeof what, "the drift of lane %llu",
                     (unsigned long long)i);
            if ((st = cx_rule(&d, what, why, cap)))
                return st;
            if (E->has_lane) {
                *out = d;
                return CX_OK;
            }
            d.neg = 0;
            if (have && rat_cmp(&d, &best, &c))
                return CX_INTERNAL;
            if (!have || c > 0)
                best = d;
            have = 1;
        }
    } else {
        int f0 = main_run->fmt;
        for (i = first; i < last; i++) {
            rat e;
            uint32_t s;
            rat_zero(&e);
            for (s = 0; s < nslots; s++) {
                rat x, y, d;
                size_t k = (size_t)i * nslots + s;
                snprintf(what, sizeof what, "run 0 lane %llu slot %lu",
                         (unsigned long long)i, (unsigned long)s);
                if ((st = cx_exact(&x, f0, a + k * ESZ(f0), what, why, cap)))
                    return st;
                snprintf(what, sizeof what, "run %llu lane %llu slot %lu",
                         (unsigned long long)E->uses, (unsigned long long)i,
                         (unsigned long)s);
                if ((st = cx_exact(&y, f, b + k * ESZ(f), what, why, cap)))
                    return st;
                if (rat_sub(&d, &x, &y)) {
                    snprintf(why, cap, "the difference at lane %llu slot %lu, "
                             "past the bigint", (unsigned long long)i,
                             (unsigned long)s);
                    return CX_INTERNAL;
                }
                d.neg = 0;
                snprintf(what, sizeof what, "the difference at lane %llu slot "
                         "%lu", (unsigned long long)i, (unsigned long)s);
                if ((st = cx_rule(&d, what, why, cap)))
                    return st;
                if (rat_cmp(&d, &e, &c))
                    return CX_INTERNAL;
                if (c > 0)
                    e = d;
            }
            if (E->has_lane) {
                *out = e;
                return CX_OK;
            }
            if (have && rat_cmp(&e, &best, &c))
                return CX_INTERNAL;
            if (!have || c > 0)
                best = e;
            have = 1;
        }
    }
    *out = best;
    return CX_OK;
}

/* cert.value_holds: does the value written state q? *holds 1 or 0. */
CX_FN int cx_value_holds(cft_device *host, const value_t *v, const rat *q,
                         int *holds)
{
    int st, c;
    *holds = 0;
    if (v->form == V_EXACT) {
        *holds = rat_eq(&v->exact, q);
        return CX_OK;
    }
    if (v->form == V_ROUNDED) {
        uint8_t b[32];
        if ((st = cx_round(host, q, v->fmt, v->rnd, b)))
            return st;
        *holds = memcmp(b, v->bits, ESZ(v->fmt)) == 0;
        return CX_OK;
    }
    {
        int kl = order_kind(v->fmt, v->lo), kh = order_kind(v->fmt, v->hi);
        elem_t x;
        rat e;
        if (kl == 2 || kh == 0)
            return CX_OK;
        /* each finite end was held to the rule by the reader */
        if (kl == 1) {
            decode(v->fmt, v->lo, &x);
            if (rat_of_elem(&e, &x) || rat_cmp(&e, q, &c))
                return CX_INTERNAL;
            if (c > 0)
                return CX_OK;
        }
        if (kh == 1) {
            decode(v->fmt, v->hi, &x);
            if (rat_of_elem(&e, &x) || rat_cmp(q, &e, &c))
                return CX_INTERNAL;
            if (c > 0)
                return CX_OK;
        }
        *holds = 1;
        return CX_OK;
    }
}

/* cert.make_value, the writer's: the value q in its form - exact; rounded
 * in fmt under rnd; or enclosed in fmt by its two directed roundings, the
 * tightest pair the format holds, never widened - with encode's check that
 * each finite end is within the width rule, the lower end first (the
 * reader's, cx_end_in_rule). q itself is held to the rule whatever the
 * form: nothing past it is approximated. */
CX_FN int cx_value_make(cft_device *host, const rat *q, int form, int fmt,
                        int rnd, value_t *v, char *why, size_t cap)
{
    int st;
    memset(v, 0, sizeof *v);
    v->form = form;
    v->fmt = fmt;
    v->rnd = rnd;
    if ((st = cx_rule(q, "the value", why, cap)))
        return st;
    if (form == V_EXACT) {
        v->exact = *q;
        return CX_OK;
    }
    if (form == V_ROUNDED)
        return cx_round(host, q, fmt, rnd, v->bits);
    if ((st = cx_round(host, q, fmt, R_RDN, v->lo)) ||
        (st = cx_round(host, q, fmt, R_RUP, v->hi)))
        return st;
    if ((st = cx_end_in_rule(fmt, v->lo, "lower", why, cap)))
        return st;
    return cx_end_in_rule(fmt, v->hi, "upper", why, cap);
}
#endif /* CX_EXACT */

#endif /* CFT_CERT_EXACT_H */
