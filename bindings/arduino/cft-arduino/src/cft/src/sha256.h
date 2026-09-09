/* Copyright 2026 Logan W.
 * SPDX-License-Identifier: Apache-2.0
 *
 * SHA-256, once. Internal, beside the public one-shot cft_sha256().
 *
 * There were five copies of this in the tree on 2026-09-08: one each in
 * host/tools/collatz.c, enclose.c, mersenne.c and orbits.c, all
 * byte-identical, and the fifth wanted by cft_program_digest (ABI 0.9,
 * docs/SEQUENCER.md revision 2). Five copies of a hash is five chances
 * for the attestation of one run to disagree with the attestation of
 * another, so there is one, here, and the four tools include this
 * header. Their printed chains are unchanged by construction - the
 * bytes moved, the arithmetic did not - and host/tests' collatz_check,
 * enclose_check, mersenne_check and orbits_check recompute every chain
 * with Python's hashlib, which is what proves it.
 *
 * The streaming form is what the tools need (each chains a hash over
 * its own output lines); cft_program_digest needs it too, since a
 * digest is the image followed by the bank. The one-shot cft_sha256()
 * in the public header is this, wrapped.
 */

#ifndef CFT_SHA256_H
#define CFT_SHA256_H

#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

typedef struct cft_sha256_ctx {
    uint32_t h[8];
    uint64_t bits;
    uint8_t  buf[64];
    size_t   have;
} cft_sha256_ctx;

void cft_sha256_init(cft_sha256_ctx *s);
void cft_sha256_update(cft_sha256_ctx *s, const void *data, size_t n);
void cft_sha256_final(cft_sha256_ctx *s, uint8_t out[32]);

/* 32 bytes as 64 lowercase hex digits plus a NUL. Here rather than in
 * each caller because every one of them wants exactly this and a
 * second spelling of a hex digit is a second thing to get wrong. */
void cft_sha256_hex(const uint8_t in[32], char out[65]);

#ifdef __cplusplus
}
#endif

#endif /* CFT_SHA256_H */
