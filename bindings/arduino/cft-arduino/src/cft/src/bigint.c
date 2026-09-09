/* Copyright 2026 Logan W.
 * SPDX-License-Identifier: Apache-2.0
 *
 * Fixed-width unsigned integers. See bigint.h for why this exists
 * rather than a dependency.
 *
 * Shift and add/sub are written so that r may alias a or b: shl walks
 * from the high limb down and everything else from the low limb up, so
 * a limb is always read before it is overwritten. mul cannot be
 * aliased safely and uses a local, which is why it is the one function
 * here that copies.
 */

#include "bigint.h"

static void bn_norm(cft_bn *r)
{
    while (r->n > 0 && r->v[r->n - 1] == 0)
        r->n--;
}

static int u32_bitlen(uint32_t x)
{
    int n = 0;
    while (x) { n++; x >>= 1; }
    return n;
}

void cft_bn_zero(cft_bn *r)
{
    r->n = 0;
}

void cft_bn_copy(cft_bn *r, const cft_bn *a)
{
    int i;
    if (r == a)
        return;
    for (i = 0; i < a->n; i++)
        r->v[i] = a->v[i];
    r->n = a->n;
}

int cft_bn_is_zero(const cft_bn *a)
{
    return a->n == 0;
}

void cft_bn_set_u32(cft_bn *r, uint32_t x)
{
    r->v[0] = x;
    r->n = x ? 1 : 0;
}

int cft_bn_bitlen(const cft_bn *a)
{
    if (a->n == 0)
        return 0;
    return (a->n - 1) * 32 + u32_bitlen(a->v[a->n - 1]);
}

int cft_bn_bit(const cft_bn *a, int i)
{
    int limb = i >> 5;
    if (i < 0 || limb >= a->n)
        return 0;
    return (int)((a->v[limb] >> (i & 31)) & 1u);
}

void cft_bn_setbit(cft_bn *r, int i)
{
    int limb = i >> 5, j;
    if (i < 0 || limb >= CFT_BN_LIMBS)
        return;
    for (j = r->n; j <= limb; j++)
        r->v[j] = 0;
    if (limb >= r->n)
        r->n = limb + 1;
    r->v[limb] |= 1u << (i & 31);
}

void cft_bn_clearbit(cft_bn *r, int i)
{
    int limb = i >> 5;
    if (i < 0 || limb >= r->n)
        return;
    r->v[limb] &= ~(1u << (i & 31));
    bn_norm(r);
}

uint32_t cft_bn_extract(const cft_bn *a, int lo, int nbits)
{
    int limb, off;
    uint32_t l0, l1;
    uint64_t acc;
    if (lo < 0 || nbits <= 0)
        return 0;
    limb = lo >> 5;
    off = lo & 31;
    l0 = (limb < a->n) ? a->v[limb] : 0u;
    l1 = (limb + 1 < a->n) ? a->v[limb + 1] : 0u;
    acc = ((uint64_t)l1 << 32) | (uint64_t)l0;
    acc >>= off;
    if (nbits < 32)
        acc &= ((uint32_t)1u << nbits) - 1u;
    return (uint32_t)acc;
}

void cft_bn_mask(cft_bn *r, int nbits)
{
    int limb = nbits >> 5, bits = nbits & 31;
    if (nbits <= 0) { r->n = 0; return; }
    if (limb >= r->n)
        return;
    if (bits)
        r->v[limb] &= ((uint32_t)1u << bits) - 1u;
    r->n = bits ? limb + 1 : limb;
    bn_norm(r);
}

int cft_bn_cmp(const cft_bn *a, const cft_bn *b)
{
    int i;
    if (a->n != b->n)
        return a->n < b->n ? -1 : 1;
    for (i = a->n - 1; i >= 0; i--)
        if (a->v[i] != b->v[i])
            return a->v[i] < b->v[i] ? -1 : 1;
    return 0;
}

int cft_bn_low_nonzero(const cft_bn *a, int k)
{
    int full = k >> 5, bits = k & 31, i;
    if (k <= 0)
        return 0;
    for (i = 0; i < full && i < a->n; i++)
        if (a->v[i])
            return 1;
    if (bits && full < a->n && (a->v[full] & (((uint32_t)1u << bits) - 1u)))
        return 1;
    return 0;
}

int cft_bn_shl(cft_bn *r, const cft_bn *a, int k)
{
    int limbs, bits, an, rn, i;
    if (k < 0)
        return 1;
    if (a->n == 0) { r->n = 0; return 0; }
    limbs = k >> 5;
    bits = k & 31;
    an = a->n;
    rn = an + limbs + 1;
    if (rn > CFT_BN_LIMBS)
        return 1;
    for (i = rn - 1; i >= 0; i--) {
        int ih = i - limbs, il = i - limbs - 1;
        uint32_t hi = (ih >= 0 && ih < an) ? a->v[ih] : 0u;
        uint32_t lo = (il >= 0 && il < an) ? a->v[il] : 0u;
        r->v[i] = bits ? ((hi << bits) | (lo >> (32 - bits))) : hi;
    }
    r->n = rn;
    bn_norm(r);
    return 0;
}

void cft_bn_shr(cft_bn *r, const cft_bn *a, int k)
{
    int limbs = k >> 5, bits = k & 31, an = a->n, rn, i;
    if (k < 0 || limbs >= an) { r->n = 0; return; }
    rn = an - limbs;
    for (i = 0; i < rn; i++) {
        uint32_t lo = a->v[i + limbs];
        uint32_t hi = (i + limbs + 1 < an) ? a->v[i + limbs + 1] : 0u;
        r->v[i] = bits ? ((lo >> bits) | (hi << (32 - bits))) : lo;
    }
    r->n = rn;
    bn_norm(r);
}

int cft_bn_add(cft_bn *r, const cft_bn *a, const cft_bn *b)
{
    int n = a->n > b->n ? a->n : b->n, i;
    uint64_t carry = 0;
    for (i = 0; i < n; i++) {
        uint64_t s = carry;
        if (i < a->n) s += a->v[i];
        if (i < b->n) s += b->v[i];
        r->v[i] = (uint32_t)s;
        carry = s >> 32;
    }
    if (carry) {
        if (n >= CFT_BN_LIMBS)
            return 1;
        r->v[n++] = (uint32_t)carry;
    }
    r->n = n;
    bn_norm(r);
    return 0;
}

void cft_bn_sub(cft_bn *r, const cft_bn *a, const cft_bn *b)
{
    int i, n = a->n;
    uint64_t borrow = 0;
    for (i = 0; i < n; i++) {
        uint64_t x = a->v[i];
        uint64_t y = (i < b->n ? b->v[i] : 0u) + borrow;
        borrow = (x < y) ? 1u : 0u;
        r->v[i] = (uint32_t)(x - y + (borrow ? ((uint64_t)1 << 32) : 0));
    }
    r->n = n;
    bn_norm(r);
}

int cft_bn_mul(cft_bn *r, const cft_bn *a, const cft_bn *b)
{
    cft_bn t;
    int i, j;
    if (a->n == 0 || b->n == 0) { r->n = 0; return 0; }
    if (a->n + b->n > CFT_BN_LIMBS)
        return 1;
    t.n = a->n + b->n;
    for (i = 0; i < t.n; i++)
        t.v[i] = 0;
    for (i = 0; i < a->n; i++) {
        uint64_t carry = 0, ai = a->v[i];
        for (j = 0; j < b->n; j++) {
            uint64_t cur = (uint64_t)t.v[i + j] + ai * (uint64_t)b->v[j] + carry;
            t.v[i + j] = (uint32_t)cur;
            carry = cur >> 32;
        }
        t.v[i + b->n] = (uint32_t)carry;   /* exact: schoolbook never
                                            * carries past a->n+b->n */
    }
    bn_norm(&t);
    cft_bn_copy(r, &t);
    return 0;
}

int cft_bn_inc(cft_bn *r)
{
    int i;
    for (i = 0; i < r->n; i++) {
        if (++r->v[i] != 0)
            return 0;
    }
    if (r->n >= CFT_BN_LIMBS)
        return 1;
    r->v[r->n++] = 1;
    return 0;
}

void cft_bn_dec(cft_bn *r)
{
    int i;
    for (i = 0; i < r->n; i++) {
        if (r->v[i]-- != 0)
            break;
    }
    bn_norm(r);
}

void cft_bn_and(cft_bn *r, const cft_bn *a, const cft_bn *b)
{
    int n = a->n < b->n ? a->n : b->n, i;
    for (i = 0; i < n; i++)
        r->v[i] = a->v[i] & b->v[i];
    r->n = n;
    bn_norm(r);
}

void cft_bn_or(cft_bn *r, const cft_bn *a, const cft_bn *b)
{
    int n = a->n > b->n ? a->n : b->n, i;
    for (i = 0; i < n; i++)
        r->v[i] = (i < a->n ? a->v[i] : 0u) | (i < b->n ? b->v[i] : 0u);
    r->n = n;
    bn_norm(r);
}

void cft_bn_xor(cft_bn *r, const cft_bn *a, const cft_bn *b)
{
    int n = a->n > b->n ? a->n : b->n, i;
    for (i = 0; i < n; i++)
        r->v[i] = (i < a->n ? a->v[i] : 0u) ^ (i < b->n ? b->v[i] : 0u);
    r->n = n;
    bn_norm(r);
}

void cft_bn_load(cft_bn *r, const uint8_t *le, int nbytes)
{
    int limbs = (nbytes + 3) / 4, i;
    if (limbs > CFT_BN_LIMBS)
        limbs = CFT_BN_LIMBS;
    for (i = 0; i < limbs; i++) {
        uint32_t w = 0;
        int j;
        for (j = 0; j < 4; j++) {
            int k = i * 4 + j;
            if (k < nbytes)
                w |= (uint32_t)le[k] << (8 * j);
        }
        r->v[i] = w;
    }
    r->n = limbs;
    bn_norm(r);
}

void cft_bn_store(const cft_bn *a, uint8_t *le, int nbytes)
{
    int i;
    for (i = 0; i < nbytes; i++) {
        int limb = i >> 2;
        uint32_t w = (limb < a->n) ? a->v[limb] : 0u;
        le[i] = (uint8_t)(w >> (8 * (i & 3)));
    }
}
