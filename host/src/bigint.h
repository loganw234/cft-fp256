/* Copyright 2026 Logan W.
 * SPDX-License-Identifier: Apache-2.0
 *
 * Fixed-width unsigned integers, internal to libcft.
 *
 * The golden model computes in Python's unbounded integers, which is
 * the right choice for a definition of correct and the wrong one for a
 * library: a faithful transliteration of the fp256 fused
 * multiply-add would align operands across the whole exponent range
 * and want roughly 790,000 bits - a hundred kilobytes of shifting per
 * element in the worst case.
 *
 * softfloat.c avoids that by bounding the alignment (see the FAR
 * analysis there); what remains needs about 1200 bits. This file
 * provides exactly that and nothing more. No allocation, no
 * dependency, no arbitrary precision - a bignum library would be a
 * larger surface than the thing it supports.
 *
 * Limbs are 32 bits with 64-bit intermediates, so this is plain C99
 * that behaves identically on 32-bit and 64-bit hosts. Bit-exactness
 * across machines is the product; using a type whose width varies
 * would be a strange place to start.
 *
 * Every value carries `n`, the number of significant limbs, and no
 * function reads v[i] for i >= n. That keeps fp32 (two limbs) fast
 * even though the container is sized for fp256.
 *
 * Functions returning int return 0 on success and 1 if the result
 * would not fit. Nothing here truncates silently: softfloat.c turns an
 * overflow into CFT_ERR_INTERNAL rather than into a wrong answer.
 */

#ifndef CFT_BIGINT_H
#define CFT_BIGINT_H

#include <stdint.h>

/* 2048 bits. The widest intermediate any operation here can produce is
 * the near-case fp256 addend alignment at about 5*prec + 3 = 1188
 * bits; the rest is margin, and margin costs stack rather than time
 * because operations run over `n` limbs, not over the container. */
#define CFT_BN_LIMBS 64
#define CFT_BN_BITS  (CFT_BN_LIMBS * 32)

typedef struct {
    int      n;                     /* significant limbs; v[n-1] != 0 */
    uint32_t v[CFT_BN_LIMBS];       /* little-endian */
} cft_bn;

void     cft_bn_zero(cft_bn *r);
void     cft_bn_copy(cft_bn *r, const cft_bn *a);
int      cft_bn_is_zero(const cft_bn *a);
void     cft_bn_set_u32(cft_bn *r, uint32_t x);

int      cft_bn_bitlen(const cft_bn *a);
int      cft_bn_bit(const cft_bn *a, int i);
void     cft_bn_setbit(cft_bn *r, int i);
void     cft_bn_clearbit(cft_bn *r, int i);
uint32_t cft_bn_extract(const cft_bn *a, int lo, int nbits); /* nbits <= 32 */
void     cft_bn_mask(cft_bn *r, int nbits);                  /* keep low bits */

int      cft_bn_cmp(const cft_bn *a, const cft_bn *b);
int      cft_bn_low_nonzero(const cft_bn *a, int k);   /* any of bits [0,k) */

int      cft_bn_shl(cft_bn *r, const cft_bn *a, int k);
void     cft_bn_shr(cft_bn *r, const cft_bn *a, int k);
int      cft_bn_add(cft_bn *r, const cft_bn *a, const cft_bn *b);
void     cft_bn_sub(cft_bn *r, const cft_bn *a, const cft_bn *b); /* a >= b */
int      cft_bn_mul(cft_bn *r, const cft_bn *a, const cft_bn *b);
int      cft_bn_inc(cft_bn *r);
void     cft_bn_dec(cft_bn *r);                        /* r > 0 */

void     cft_bn_and(cft_bn *r, const cft_bn *a, const cft_bn *b);
void     cft_bn_or(cft_bn *r, const cft_bn *a, const cft_bn *b);
void     cft_bn_xor(cft_bn *r, const cft_bn *a, const cft_bn *b);

/* Interchange encodings are dense little-endian byte strings, which is
 * what the buffers a caller hands cft_run() contain and what the tile
 * reads off the bus. Load and store are the only places this file
 * knows about bytes. */
void     cft_bn_load(cft_bn *r, const uint8_t *le, int nbytes);
void     cft_bn_store(const cft_bn *a, uint8_t *le, int nbytes);

#endif /* CFT_BIGINT_H */
