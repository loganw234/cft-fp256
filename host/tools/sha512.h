/* Copyright 2026 Logan W.
 * SPDX-License-Identifier: Apache-2.0
 *
 * sha512.h - SHA-512 (FIPS 180-4, sections 4.1.3, 4.2.3, 5.1.2, 5.2.2,
 * 5.3.5 and 6.4), for Ed25519's verification (ed25519.h, RFC 8032 section
 * 5.1), which is all that needs it: cft-audit's check of a certificate's
 * detached signature (docs/CERTIFICATES.md, version 2, "The detached
 * signature"). Written for this tree from the standard's text (parcel
 * CV2CA, 2026-10-02); no code was copied from anywhere.
 *
 * The constants are DERIVED, as host/src/sha256.c derives SHA-256's: the
 * standing rule here is that a constant is derived, or copied in the base
 * it was specified in, and never retyped from memory. FIPS 180-4 specifies
 * SHA-512's eight initial words as the first 64 bits of the fractional
 * parts of the square roots of the first eight primes (5.3.5), and its
 * eighty round constants as those of the cube roots of the first eighty
 * primes (4.2.3). So they are computed so, once, by integer roots: the
 * first 64 bits of frac(sqrt(p)) are floor(sqrt(p * 2^128)) mod 2^64, and
 * those of frac(cbrt(p)) are floor(cbrt(p * 2^192)) mod 2^64, each root
 * built bit by bit in a 256-bit integer of 32-bit limbs. No floating point,
 * nothing to mistype. host/tests/audit_check.py (section 7) holds the whole
 * hash to FIPS 180-4's published examples - "abc", the 448-bit and 896-bit
 * messages, a million 'a's - to the empty message, and to Python's hashlib
 * on every length that crosses a block's padding edge.
 *
 * HEADER-ONLY, every definition SHA512_FN: static, with GCC's `unused`
 * attribute, as tools/cert_exact.h's are, so that a build that calls part
 * of it stays warning-free (-Wall -Wextra -Wpedantic -Wshadow). Portable
 * C99: 32-bit and 64-bit unsigned arithmetic only, no 128-bit type. It is
 * not constant-time, which a hash of public data does not need.
 */
#ifndef CFT_TOOLS_SHA512_H
#define CFT_TOOLS_SHA512_H

#include <stddef.h>
#include <stdint.h>
#include <string.h>

#if defined(__GNUC__)
#  define SHA512_FN static __attribute__((unused))
#else
#  define SHA512_FN static
#endif

typedef struct {
    uint64_t h[8];
    uint64_t len_hi, len_lo;        /* the message's length in BITS, 128 */
    uint8_t buf[128];
    size_t have;
} sha512_ctx;

/* ---- the constants, derived (4.2.3, 5.3.5) ---------------------------- */

/* A 256-bit unsigned of eight 32-bit limbs, least significant first: room
 * for p * 2^192 (p <= 409 < 2^9) and for a root's cube. */
typedef struct { uint32_t v[8]; } sha512_u256;

/* r = a * b, truncated to 256 bits (the callers' products fit) */
SHA512_FN void sha512_u256_mul(sha512_u256 *r, const sha512_u256 *a,
                               const sha512_u256 *b)
{
    uint32_t t[8];
    int i, j;
    memset(t, 0, sizeof t);
    for (i = 0; i < 8; i++) {
        uint64_t c = 0;
        for (j = 0; i + j < 8; j++) {
            uint64_t m = (uint64_t)a->v[i] * b->v[j] + t[i + j] + c;
            t[i + j] = (uint32_t)m;
            c = m >> 32;
        }
    }
    memcpy(r->v, t, sizeof t);
}

SHA512_FN int sha512_u256_cmp(const sha512_u256 *a, const sha512_u256 *b)
{
    int i;
    for (i = 7; i >= 0; i--)
        if (a->v[i] != b->v[i])
            return a->v[i] < b->v[i] ? -1 : 1;
    return 0;
}

/* floor(cbrt(p * 2^192)) mod 2^64 when cube, else floor(sqrt(p * 2^128))
 * mod 2^64: the root is below 2^67, built from bit 66 down, each bit kept
 * where the power of the candidate does not pass the target */
SHA512_FN uint64_t sha512_root_bits(uint32_t p, int cube)
{
    sha512_u256 n, r, t, sq, pw;
    int bit;
    memset(&n, 0, sizeof n);
    n.v[cube ? 6 : 4] = p;          /* p * 2^192, or p * 2^128 */
    memset(&r, 0, sizeof r);
    for (bit = 66; bit >= 0; bit--) {
        t = r;
        t.v[bit / 32] |= (uint32_t)1 << (bit % 32);
        sha512_u256_mul(&sq, &t, &t);
        if (cube)
            sha512_u256_mul(&pw, &sq, &t);
        else
            pw = sq;
        if (sha512_u256_cmp(&pw, &n) <= 0)
            r = t;
    }
    return (uint64_t)r.v[0] | ((uint64_t)r.v[1] << 32);
}

static uint64_t SHA512_H0[8], SHA512_K[80];
static int SHA512_READY = 0;

/* the first 8 and 80 primes, by trial division, and their roots' bits */
SHA512_FN void sha512_constants(void)
{
    uint32_t p = 1;
    int n = 0;
    if (SHA512_READY)
        return;
    while (n < 80) {
        uint32_t d;
        int prime = 1;
        p++;
        for (d = 2; d * d <= p; d++)
            if (p % d == 0) {
                prime = 0;
                break;
            }
        if (!prime)
            continue;
        if (n < 8)
            SHA512_H0[n] = sha512_root_bits(p, 0);
        SHA512_K[n] = sha512_root_bits(p, 1);
        n++;
    }
    SHA512_READY = 1;
}

/* ---- the functions (4.1.3) and the compression (6.4.2) ---------------- */

#define SHA512_ROTR(x, n) (((x) >> (n)) | ((x) << (64 - (n))))

SHA512_FN void sha512_block(uint64_t h[8], const uint8_t blk[128])
{
    uint64_t w[80], a, b, c, d, e, f, g, hh;
    int t, i;
    for (t = 0; t < 16; t++) {
        uint64_t x = 0;
        for (i = 0; i < 8; i++)
            x = (x << 8) | blk[8 * t + i];     /* big-endian words */
        w[t] = x;
    }
    for (t = 16; t < 80; t++) {
        uint64_t s0 = SHA512_ROTR(w[t - 15], 1) ^ SHA512_ROTR(w[t - 15], 8) ^
                      (w[t - 15] >> 7);
        uint64_t s1 = SHA512_ROTR(w[t - 2], 19) ^ SHA512_ROTR(w[t - 2], 61) ^
                      (w[t - 2] >> 6);
        w[t] = s1 + w[t - 7] + s0 + w[t - 16];
    }
    a = h[0]; b = h[1]; c = h[2]; d = h[3];
    e = h[4]; f = h[5]; g = h[6]; hh = h[7];
    for (t = 0; t < 80; t++) {
        uint64_t S1 = SHA512_ROTR(e, 14) ^ SHA512_ROTR(e, 18) ^
                      SHA512_ROTR(e, 41);
        uint64_t ch = (e & f) ^ (~e & g);
        uint64_t T1 = hh + S1 + ch + SHA512_K[t] + w[t];
        uint64_t S0 = SHA512_ROTR(a, 28) ^ SHA512_ROTR(a, 34) ^
                      SHA512_ROTR(a, 39);
        uint64_t maj = (a & b) ^ (a & c) ^ (b & c);
        uint64_t T2 = S0 + maj;
        hh = g; g = f; f = e; e = d + T1;
        d = c; c = b; b = a; a = T1 + T2;
    }
    h[0] += a; h[1] += b; h[2] += c; h[3] += d;
    h[4] += e; h[5] += f; h[6] += g; h[7] += hh;
}

/* ---- the streaming hash ------------------------------------------------ */

SHA512_FN void sha512_init(sha512_ctx *s)
{
    sha512_constants();
    memcpy(s->h, SHA512_H0, sizeof s->h);
    s->len_hi = s->len_lo = 0;
    s->have = 0;
}

SHA512_FN void sha512_update(sha512_ctx *s, const void *data, size_t n)
{
    const uint8_t *p = (const uint8_t *)data;
    while (n) {
        size_t k = 128 - s->have;
        uint64_t bits;
        if (k > n)
            k = n;
        memcpy(s->buf + s->have, p, k);
        s->have += k;
        p += k;
        n -= k;
        bits = (uint64_t)k << 3;            /* k <= 128: no overflow */
        s->len_lo += bits;
        if (s->len_lo < bits)
            s->len_hi++;
        if (s->have == 128) {
            sha512_block(s->h, s->buf);
            s->have = 0;
        }
    }
}

/* 5.1.2's padding: a 1 bit, zeros to 896 mod 1024, the length in 128 bits
 * big-endian; then the eight words big-endian */
SHA512_FN void sha512_final(sha512_ctx *s, uint8_t out[64])
{
    int i;
    s->buf[s->have++] = 0x80;
    if (s->have > 112) {
        memset(s->buf + s->have, 0, 128 - s->have);
        sha512_block(s->h, s->buf);
        s->have = 0;
    }
    memset(s->buf + s->have, 0, 112 - s->have);
    for (i = 0; i < 8; i++) {
        s->buf[112 + i] = (uint8_t)(s->len_hi >> (56 - 8 * i));
        s->buf[120 + i] = (uint8_t)(s->len_lo >> (56 - 8 * i));
    }
    sha512_block(s->h, s->buf);
    for (i = 0; i < 64; i++)
        out[i] = (uint8_t)(s->h[i / 8] >> (56 - 8 * (i % 8)));
    memset(s, 0, sizeof *s);
}

SHA512_FN void sha512(const void *data, size_t n, uint8_t out[64])
{
    sha512_ctx s;
    sha512_init(&s);
    sha512_update(&s, data, n);
    sha512_final(&s, out);
}

#endif /* CFT_TOOLS_SHA512_H */
