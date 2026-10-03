/* Copyright 2026 Logan W.
 * SPDX-License-Identifier: Apache-2.0
 *
 * ed25519.h - Ed25519 VERIFICATION (RFC 8032, section 5.1), for cft-audit's
 * check of a certificate's detached signature and of every key a version-2
 * certificate, a keyring or a signature file names (docs/CERTIFICATES.md,
 * version 2, "The detached signature"). Written for this tree from the
 * RFC's mathematics (parcel CV2CA, 2026-10-02): the curve and its
 * constants (5.1), the encoding (5.1.2), the decoding (5.1.3), the group
 * law in extended coordinates (5.1.4) and the verification (5.1.7). No
 * code was copied from the RFC, whose section 6 is a Python sketch, or
 * from anywhere else. python/cft_golden/ed25519.py is the authority it is
 * held to, and host/tests/audit_check.py (section 7) holds it to every
 * vector python/tests/test_ed25519.py carries.
 *
 * There is no signing here: python/cft_sign.py signs. Verification takes
 * public data only (a key, a message, a signature), so nothing here is
 * secret and nothing needs to be constant-time; it is not.
 *
 *   ed25519_decodes(k)        do the 32 bytes encode a point (5.1.3)?
 *   ed25519_small_order(k)    do they encode a point A with [8]A the
 *                             identity - one of the eight keys of the
 *                             curve's torsion? (0 where they encode none)
 *   ed25519_key_check(k)      both at once, as a key is read anywhere:
 *                             ED25519_KEY_OK (0), ED25519_KEY_NO_POINT (1)
 *                             or ED25519_KEY_SMALL_ORDER (2) - the one
 *                             decoding cft-audit and cft-segrun share
 *   ed25519_verify(A, M, sig) 5.1.7 with the cofactored equation, and one
 *                             refusal the RFC leaves to its user: a key of
 *                             small order (verifier-VCV2B; the lead's
 *                             decision, 2026-10-02)
 *
 * What verification decides, in the golden model's terms (ed25519.verify):
 *   - A and R each decode: y below p, a square root of x^2 that exists,
 *     and no x of zero with its sign bit set;
 *   - A is not of small order: under such a key [8][k]A vanishes, and any
 *     R = [S]B satisfies the equation for every message;
 *   - S is below L, so one signature has one spelling;
 *   - [8][S]B = [8]R + [8][k]A, with k = SHA-512(R || A || M) mod L. The
 *     cofactorless [S]B = R + [k]A is a sufficient special case, and the
 *     two part on a key with a small-order component beside a prime-order
 *     part, which is accepted: signing under it needs that part's secret.
 *     A point R of small order is not refused.
 *
 * The constants are derived, never typed: p = 2^255 - 19 is built from its
 * definition; d = -121665/121666 and B's y = 4/5 are field divisions; B's
 * x is the decoding's root with its sign bit clear; sqrt(-1) is
 * 2^((p-1)/4); L is 2^252 plus the decimal the RFC writes, read from that
 * decimal (the base it was specified in). The vectors catch any of them
 * wrong.
 *
 * The field: an element is eight 32-bit limbs, least significant first,
 * holding a value below 2^256 that is congruent to it modulo p; since
 * 2^256 = 2p + 38, a carry out of the top limb is folded back as 38, and
 * an element is reduced below p (canonical) only to compare or to read
 * its parity. Portable C99: 32 x 32 -> 64-bit products and nothing wider.
 *
 * HEADER-ONLY, every definition ED_FN: static with GCC's `unused`
 * attribute, as tools/cert_exact.h's are.
 */
#ifndef CFT_TOOLS_ED25519_H
#define CFT_TOOLS_ED25519_H

#include <stddef.h>
#include <stdint.h>
#include <string.h>

#include "sha512.h"

#if defined(__GNUC__)
#  define ED_FN static __attribute__((unused))
#else
#  define ED_FN static
#endif

typedef uint32_t ed_fe[8];                   /* a field element */
typedef struct { ed_fe X, Y, Z, T; } ed_ge;  /* x = X/Z, y = Y/Z, xy = T/Z */

/* ---- 256-bit naturals: the pieces both the field and the scalars use --- */

/* a += x (x < 2^32); the carry out of the top limb */
ED_FN uint32_t ed_add_small(uint32_t a[8], uint32_t x)
{
    uint64_t c = x;
    int i;
    for (i = 0; i < 8 && c; i++) {
        uint64_t m = (uint64_t)a[i] + c;
        a[i] = (uint32_t)m;
        c = m >> 32;
    }
    return (uint32_t)c;
}

/* a -= x (x < 2^32); the borrow out of the top limb */
ED_FN uint32_t ed_sub_small(uint32_t a[8], uint32_t x)
{
    uint32_t b = x;
    int i;
    for (i = 0; i < 8 && b; i++) {
        uint32_t old = a[i];
        a[i] = old - b;
        b = old < b ? 1u : 0u;
    }
    return b;
}

ED_FN int ed_cmp(const uint32_t a[8], const uint32_t b[8])
{
    int i;
    for (i = 7; i >= 0; i--)
        if (a[i] != b[i])
            return a[i] < b[i] ? -1 : 1;
    return 0;
}

/* a -= b, a >= b */
ED_FN void ed_sub_n(uint32_t a[8], const uint32_t b[8])
{
    uint32_t bw = 0;
    int i;
    for (i = 0; i < 8; i++) {
        uint64_t m = (uint64_t)a[i] - b[i] - bw;
        a[i] = (uint32_t)m;
        bw = (uint32_t)(m >> 32) & 1u;
    }
}

/* 32 little-endian bytes -> eight limbs */
ED_FN void ed_load(uint32_t a[8], const uint8_t s[32])
{
    int i;
    for (i = 0; i < 8; i++)
        a[i] = (uint32_t)s[4 * i] | ((uint32_t)s[4 * i + 1] << 8) |
               ((uint32_t)s[4 * i + 2] << 16) | ((uint32_t)s[4 * i + 3] << 24);
}

/* ---- the constants (5.1, table 1), derived once ------------------------- */

static ed_fe ED_P;          /* p = 2^255 - 19 */
static ed_fe ED_PM2;        /* p - 2, the inverse's exponent (Fermat) */
static ed_fe ED_PM5_8;      /* (p - 5) / 8, the decoding's root exponent */
static ed_fe ED_PM1_4;      /* (p - 1) / 4: 2 to it is sqrt(-1) */
static ed_fe ED_D2;         /* 2d, d = -121665/121666 */
static ed_fe ED_D;
static ed_fe ED_SQRTM1;
static uint32_t ED_L[8];    /* L = 2^252 + 27742317777372353535851937790883648493 */
static ed_ge ED_B;          /* the base point: y = 4/5, x even */
static int ED_READY = 0;

/* ---- the field --------------------------------------------------------- */

ED_FN void fe_copy(ed_fe r, const ed_fe a)
{
    memcpy(r, a, sizeof(ed_fe));
}

ED_FN void fe_set(ed_fe r, uint32_t x)
{
    memset(r, 0, sizeof(ed_fe));
    r[0] = x;
}

/* a carry c out of the top limb is c * 2^256 = 38 c (mod p): fold it back,
 * again while folding carries (at most twice) */
ED_FN void fe_fold(ed_fe r, uint32_t c)
{
    while (c)
        c = ed_add_small(r, 38u * c);
}

ED_FN void fe_add(ed_fe r, const ed_fe a, const ed_fe b)
{
    uint64_t c = 0;
    int i;
    for (i = 0; i < 8; i++) {
        uint64_t m = (uint64_t)a[i] + b[i] + c;
        r[i] = (uint32_t)m;
        c = m >> 32;
    }
    fe_fold(r, (uint32_t)c);
}

/* r = a - b: a borrow out of the top is a + 2^256 - b = a - b + 38 (mod p),
 * so 38 is taken away again, as often as that borrows (at most twice) */
ED_FN void fe_sub(ed_fe r, const ed_fe a, const ed_fe b)
{
    uint32_t bw = 0, t[8];
    int i;
    for (i = 0; i < 8; i++) {
        uint64_t m = (uint64_t)a[i] - b[i] - bw;
        t[i] = (uint32_t)m;
        bw = (uint32_t)(m >> 32) & 1u;
    }
    while (bw)
        bw = ed_sub_small(t, 38u * bw);
    memcpy(r, t, sizeof t);
}

/* r = a * b: the 512-bit product hi * 2^256 + lo is lo + 38 hi (mod p) */
ED_FN void fe_mul(ed_fe r, const ed_fe a, const ed_fe b)
{
    uint32_t t[16], u[8];
    uint64_t c;
    int i, j;
    memset(t, 0, sizeof t);
    for (i = 0; i < 8; i++) {
        c = 0;
        for (j = 0; j < 8; j++) {
            uint64_t m = (uint64_t)a[i] * b[j] + t[i + j] + c;
            t[i + j] = (uint32_t)m;
            c = m >> 32;
        }
        t[i + 8] = (uint32_t)c;
    }
    c = 0;
    for (i = 0; i < 8; i++) {
        uint64_t m = (uint64_t)t[i + 8] * 38u + t[i] + c;
        u[i] = (uint32_t)m;
        c = m >> 32;
    }
    fe_fold(u, (uint32_t)c);
    memcpy(r, u, sizeof u);
}

ED_FN void fe_sq(ed_fe r, const ed_fe a)
{
    fe_mul(r, a, a);
}

/* below p: 2^256 = 2p + 38, so at most two subtractions */
ED_FN void fe_canon(ed_fe r, const ed_fe a)
{
    int k;
    fe_copy(r, a);
    for (k = 0; k < 2; k++)
        if (ed_cmp(r, ED_P) >= 0)
            ed_sub_n(r, ED_P);
}

ED_FN int fe_eq(const ed_fe a, const ed_fe b)
{
    ed_fe x, y;
    fe_canon(x, a);
    fe_canon(y, b);
    return memcmp(x, y, sizeof x) == 0;
}

ED_FN int fe_is_zero(const ed_fe a)
{
    ed_fe z;
    fe_set(z, 0);
    return fe_eq(a, z);
}

ED_FN void fe_neg(ed_fe r, const ed_fe a)
{
    ed_fe z;
    fe_set(z, 0);
    fe_sub(r, z, a);
}

/* r = a^e, e a 256-bit natural, by squaring and multiplying from e's top
 * bit down */
ED_FN void fe_pow(ed_fe r, const ed_fe a, const ed_fe e)
{
    ed_fe acc, base;
    int bit;
    fe_copy(base, a);
    fe_set(acc, 1);
    for (bit = 255; bit >= 0; bit--) {
        fe_sq(acc, acc);
        if ((e[bit / 32] >> (bit % 32)) & 1u)
            fe_mul(acc, acc, base);
    }
    fe_copy(r, acc);
}

ED_FN void fe_inv(ed_fe r, const ed_fe a)
{
    fe_pow(r, a, ED_PM2);
}

/* ---- the constants -------------------------------------------------- */

/* x with -x^2 + y^2 = 1 + d x^2 y^2 and x's low bit `sign`, 5.1.3's steps
 * 2 to 4 (y already below p): x^2 = u/v with u = y^2 - 1 and v = d y^2 + 1;
 * the candidate root of u/v is u v^3 (u v^7)^((p-5)/8). 0 where there is
 * none: u/v not a square, or x = 0 with the sign bit set. */
ED_FN int ed_recover_x(ed_fe x, const ed_fe y, int sign)
{
    ed_fe y2, u, v, v3, v7, t, cand, vx2, one, negu;
    fe_set(one, 1);
    fe_sq(y2, y);
    fe_sub(u, y2, one);
    fe_mul(v, ED_D, y2);
    fe_add(v, v, one);
    fe_sq(v3, v);
    fe_mul(v3, v3, v);                   /* v^3 */
    fe_sq(v7, v3);
    fe_mul(v7, v7, v);                   /* v^7 */
    fe_mul(t, u, v7);
    fe_pow(t, t, ED_PM5_8);              /* (u v^7)^((p-5)/8) */
    fe_mul(cand, u, v3);
    fe_mul(cand, cand, t);
    fe_sq(vx2, cand);
    fe_mul(vx2, vx2, v);
    fe_neg(negu, u);
    if (fe_eq(vx2, u)) {
        /* cand is a root */
    } else if (fe_eq(vx2, negu)) {
        fe_mul(cand, cand, ED_SQRTM1);
    } else {
        return 0;                        /* u/v is not a square */
    }
    fe_canon(cand, cand);
    if (fe_is_zero(cand) && sign)
        return 0;                        /* "negative zero" is no point */
    if ((int)(cand[0] & 1u) != sign)
        fe_neg(cand, cand);
    fe_copy(x, cand);
    return 1;
}

ED_FN void ed_constants(void)
{
    static const char L_DECIMAL[] = "27742317777372353535851937790883648493";
    ed_fe a, b, five, four;
    const char *s;
    int i;
    if (ED_READY)
        return;
    /* p = 2^255 - 19: 255 one bits, less 18 */
    for (i = 0; i < 8; i++)
        ED_P[i] = 0xFFFFFFFFu;
    ED_P[7] = 0x7FFFFFFFu;
    ed_sub_small(ED_P, 18u);
    fe_copy(ED_PM2, ED_P);
    ed_sub_small(ED_PM2, 2u);
    /* (p - 5) / 8 and (p - 1) / 4, shifted down */
    fe_copy(a, ED_P);
    ed_sub_small(a, 5u);
    for (i = 0; i < 8; i++)
        ED_PM5_8[i] = (a[i] >> 3) | (i < 7 ? a[i + 1] << 29 : 0u);
    fe_copy(a, ED_P);
    ed_sub_small(a, 1u);
    for (i = 0; i < 8; i++)
        ED_PM1_4[i] = (a[i] >> 2) | (i < 7 ? a[i + 1] << 30 : 0u);
    /* d = -121665 / 121666, and 2d */
    fe_set(a, 121666u);
    fe_inv(b, a);
    fe_set(a, 121665u);
    fe_mul(ED_D, a, b);
    fe_neg(ED_D, ED_D);
    fe_add(ED_D2, ED_D, ED_D);
    /* sqrt(-1) = 2^((p-1)/4) */
    fe_set(a, 2u);
    fe_pow(ED_SQRTM1, a, ED_PM1_4);
    /* L = 2^252 + the decimal, which is below 2^125 */
    memset(ED_L, 0, sizeof ED_L);
    for (s = L_DECIMAL; *s; s++) {
        uint64_t c = (uint64_t)(*s - '0');
        for (i = 0; i < 8; i++) {
            uint64_t m = (uint64_t)ED_L[i] * 10u + c;
            ED_L[i] = (uint32_t)m;
            c = m >> 32;
        }
    }
    ED_L[7] |= 1u << 28;                 /* bit 252 */
    /* B: y = 4/5, x recovered with its sign bit clear (x even) */
    fe_set(five, 5u);
    fe_set(four, 4u);
    fe_inv(a, five);
    fe_mul(ED_B.Y, four, a);
    fe_canon(ED_B.Y, ED_B.Y);
    ED_READY = 1;                        /* ed_recover_x reads the rest */
    if (!ed_recover_x(ED_B.X, ED_B.Y, 0)) {
        ED_READY = 0;                    /* cannot happen: B is a point */
        return;
    }
    fe_set(ED_B.Z, 1u);
    fe_mul(ED_B.T, ED_B.X, ED_B.Y);
}

/* ---- the group law (5.1.4), complete for a = -1 ----------------------- */

ED_FN void ge_identity(ed_ge *r)
{
    fe_set(r->X, 0);
    fe_set(r->Y, 1);
    fe_set(r->Z, 1);
    fe_set(r->T, 0);
}

ED_FN void ge_add(ed_ge *r, const ed_ge *p, const ed_ge *q)
{
    ed_fe A, B, C, D, E, F, G, H, s, t;
    fe_sub(s, p->Y, p->X);
    fe_sub(t, q->Y, q->X);
    fe_mul(A, s, t);
    fe_add(s, p->Y, p->X);
    fe_add(t, q->Y, q->X);
    fe_mul(B, s, t);
    fe_mul(C, p->T, ED_D2);
    fe_mul(C, C, q->T);
    fe_mul(D, p->Z, q->Z);
    fe_add(D, D, D);
    fe_sub(E, B, A);
    fe_sub(F, D, C);
    fe_add(G, D, C);
    fe_add(H, B, A);
    fe_mul(r->X, E, F);
    fe_mul(r->Y, G, H);
    fe_mul(r->T, E, H);
    fe_mul(r->Z, F, G);
}

ED_FN void ge_double(ed_ge *r, const ed_ge *p)
{
    ed_fe A, B, C, E, F, G, H, s;
    fe_sq(A, p->X);
    fe_sq(B, p->Y);
    fe_sq(C, p->Z);
    fe_add(C, C, C);
    fe_add(H, A, B);
    fe_add(s, p->X, p->Y);
    fe_sq(s, s);
    fe_sub(E, H, s);
    fe_sub(G, A, B);
    fe_add(F, C, G);
    fe_mul(r->X, E, F);
    fe_mul(r->Y, G, H);
    fe_mul(r->T, E, H);
    fe_mul(r->Z, F, G);
}

/* [k] P for a 256-bit natural k (eight limbs), double and add from k's top
 * bit down; not constant-time, which public data does not need */
ED_FN void ge_scalar(ed_ge *r, const uint32_t k[8], const ed_ge *p)
{
    ed_ge acc;
    int bit;
    ge_identity(&acc);
    for (bit = 255; bit >= 0; bit--) {
        ge_double(&acc, &acc);
        if ((k[bit / 32] >> (bit % 32)) & 1u)
            ge_add(&acc, &acc, p);
    }
    *r = acc;
}

ED_FN void ge_times8(ed_ge *r, const ed_ge *p)
{
    ge_double(r, p);
    ge_double(r, r);
    ge_double(r, r);
}

/* P = Q as points: X1/Z1 = X2/Z2 and Y1/Z1 = Y2/Z2 */
ED_FN int ge_same(const ed_ge *p, const ed_ge *q)
{
    ed_fe a, b;
    fe_mul(a, p->X, q->Z);
    fe_mul(b, q->X, p->Z);
    if (!fe_eq(a, b))
        return 0;
    fe_mul(a, p->Y, q->Z);
    fe_mul(b, q->Y, p->Z);
    return fe_eq(a, b);
}

ED_FN int ge_is_identity(const ed_ge *p)
{
    ed_ge id;
    ge_identity(&id);
    return ge_same(p, &id);
}

/* ---- the encodings (5.1.2, 5.1.3) ------------------------------------- */

/* The point 32 bytes encode: y little-endian in the low 255 bits, x's low
 * bit in the top bit. 0 where they encode none: y not below p, no square
 * root, or x = 0 with the sign bit set. */
ED_FN int ge_decode(ed_ge *r, const uint8_t s[32])
{
    ed_fe y;
    int sign = s[31] >> 7;
    ed_constants();
    if (!ED_READY)
        return 0;
    ed_load(y, s);
    y[7] &= 0x7FFFFFFFu;
    if (ed_cmp(y, ED_P) >= 0)
        return 0;                        /* y not below p */
    if (!ed_recover_x(r->X, y, sign))
        return 0;
    fe_copy(r->Y, y);
    fe_set(r->Z, 1u);
    fe_mul(r->T, r->X, r->Y);
    return 1;
}

ED_FN int ed25519_decodes(const uint8_t key[32])
{
    ed_ge a;
    return ge_decode(&a, key);
}

/* A key of small order: 32 bytes that decode to a point A with [8]A the
 * identity - the eight points of the curve's torsion. 0 for bytes that
 * decode to no point, as the golden model's small_order says. */
ED_FN int ed25519_small_order(const uint8_t key[32])
{
    ed_ge a, a8;
    if (!ge_decode(&a, key))
        return 0;
    ge_times8(&a8, &a);
    return ge_is_identity(&a8);
}

/* What 32 bytes are as a key that a holder signs with (cert2.key_problem,
 * read wherever a certificate names a key: its issuer-key line, a
 * keyring's line, a signature file's key):
 *   ED25519_KEY_OK           0  a point with a prime-order part
 *   ED25519_KEY_NO_POINT     1  an encoding of no point (5.1.3): `malformed`
 *                               on an issuer-key line, `signer` in a keyring
 *   ED25519_KEY_SMALL_ORDER  2  a point of small order, [8]A the identity:
 *                               `signer` wherever it is read, since under it
 *                               a signature nobody made verifies for every
 *                               message
 * (A signature file's key that encodes no point is not refused here by the
 * golden auditor: its signature then fails to verify, `signature`.) The
 * one decoding both C tools share (the lead's decision, 2026-10-02). */
enum { ED25519_KEY_OK = 0, ED25519_KEY_NO_POINT = 1,
       ED25519_KEY_SMALL_ORDER = 2 };

ED_FN int ed25519_key_check(const unsigned char key[32])
{
    ed_ge a, a8;
    if (!ge_decode(&a, key))
        return ED25519_KEY_NO_POINT;
    ge_times8(&a8, &a);
    return ge_is_identity(&a8) ? ED25519_KEY_SMALL_ORDER : ED25519_KEY_OK;
}

/* ---- the scalars ------------------------------------------------------ */

/* the 512-bit little-endian h reduced mod L, by binary long division:
 * the remainder stays below 2L < 2^254, so eight limbs hold it doubled */
ED_FN void ed_mod_l(uint32_t r[8], const uint8_t h[64])
{
    int bit, i;
    memset(r, 0, 8 * sizeof r[0]);
    for (bit = 511; bit >= 0; bit--) {
        uint32_t in = (h[bit / 8] >> (bit % 8)) & 1u;
        for (i = 7; i > 0; i--)
            r[i] = (r[i] << 1) | (r[i - 1] >> 31);
        r[0] = (r[0] << 1) | in;
        if (ed_cmp(r, ED_L) >= 0)
            ed_sub_n(r, ED_L);
    }
}

/* ---- verification (5.1.7) --------------------------------------------- */

ED_FN int ed25519_verify(const uint8_t pub[32], const uint8_t *msg,
                         size_t n, const uint8_t sig[64])
{
    ed_ge A, R, sB, kA, rhs, l8, r8;
    uint32_t S[8], k[8];
    uint8_t h[64];
    sha512_ctx hs;
    if (!ge_decode(&A, pub) || !ge_decode(&R, sig))
        return 0;
    ge_times8(&l8, &A);
    if (ge_is_identity(&l8))
        return 0;                        /* a key of small order */
    ed_load(S, sig + 32);
    if (ed_cmp(S, ED_L) >= 0)
        return 0;                        /* S at or above L */
    sha512_init(&hs);
    sha512_update(&hs, sig, 32);         /* R as encoded */
    sha512_update(&hs, pub, 32);         /* A as encoded */
    sha512_update(&hs, msg, n);
    sha512_final(&hs, h);
    ed_mod_l(k, h);
    ge_scalar(&sB, S, &ED_B);
    ge_scalar(&kA, k, &A);
    ge_add(&rhs, &R, &kA);
    ge_times8(&l8, &sB);
    ge_times8(&r8, &rhs);
    return ge_same(&l8, &r8);
}

#endif /* CFT_TOOLS_ED25519_H */
