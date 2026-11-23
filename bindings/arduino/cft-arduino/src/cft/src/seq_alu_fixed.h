/* Copyright 2026 Logan W.
 * SPDX-License-Identifier: Apache-2.0
 *
 * The GPU backend's fixed tier inside programs (round 3's G3B): the
 * sequencer executor's lane ALU on the fixed tier's second implementations
 * of the FMA. NOT libcft's arithmetic: an ADAPTER with cft_sf_compute's
 * signature, for seq_exec.h's hook (CFT_SEQ_ALU), so that an executor
 * compiled with it runs FMA, ADD, SUB and MUL at binary256 through
 * fma256_fixed.h (fxalu_compute) or at binary128 through fma128_fixed.h
 * (fxalu128_compute), and every other opcode, format and attribute through
 * cft_sf_compute itself, unchanged. Its agreement with cft_sf_compute is
 * evidence by test, not a proof.
 *
 * Device-only in the library: backend_hip.cpp includes it after
 * fma256_fixed.h and fma128_fixed.h (it includes nothing, and needs their
 * fx256_* and fx128_*, softfloat.c's cft_sf_compute and CFT_SF_*, and
 * bigint's cft_bn), so it is in libcft only under HIP=1. On a host,
 * host/tests/fma256_test.c and fma128_test.c build it (make fma256test,
 * fma128test) and hold each wrapper to cft_sf_compute on cft_bn operands.
 *
 * Each wrapper, inside its condition - the width (256, or 128), the opcode
 * FMA, ADD, SUB or MUL (0 to 3) and the attribute 0 to 4 (the loader
 * refuses a program with any other, so an executor never passes one):
 *   - a, b and c stored to the format's bytes by cft_bn_store: a register
 *     of a program at that format holds nothing above its width (no opcode
 *     leaves a bit there: the integer group masks to the width or cannot
 *     reach past it, and every float result is packed at the width), so the
 *     store drops nothing;
 *   - steered on the bytes by fx256_steer or fx128_steer, libcft's own
 *     identities (ADD = FMA(a, 1, c), SUB = FMA(a, 1, -c), MUL = FMA(a, b,
 *     +-0)), so ADD and SUB read a and c, and MUL a and b, as
 *     cft_sf_compute's sf_steer does;
 *   - the lane, fx256_fma_lane or fx128_fma_lane, in k_run256's and
 *     k_run128's order (store, steer, lane);
 *   - the result loaded by cft_bn_zero then cft_bn_load, and the flags the
 *     lane's byte & 0x1F.
 * A lane that flags 0x80 (a construction invariant failed) returns 1 with
 * *flags 0 and out untouched, and so does an opcode the steering refuses
 * (none inside the condition): the executor then returns CFT_ERR_INTERNAL,
 * as for any ALU refusal. Outside the condition the call IS cft_sf_compute.
 *
 * The width is the lane's whole test of the format; fx256_matches and
 * fx128_matches are not called here. They are the open's: a handle opened
 * on the fixed tier holds each header's typed-in constants to the
 * library's own descriptor first, and the backend sends a kernel of these
 * programs of its one format only (backend_hip.cpp's seq_route, and its
 * literal test at the launch), so a descriptor of width 256 (128) here is
 * that library's binary256 (binary128). No operand is ever held in a
 * double: bytes, then the headers' uint32_t limbs.
 */
#ifndef CFT_SEQ_ALU_FIXED_H
#define CFT_SEQ_ALU_FIXED_H

/* binary256: FMA, ADD, SUB and MUL through fma256_fixed.h */
CFT_HD static inline int fxalu_compute(const cft_fmt_desc *f, int op, int rnd,
                                       const cft_bn *a, const cft_bn *b, const cft_bn *c,
                                       cft_bn *out, uint32_t *flags)
{
    uint8_t qa[32], qb[32], qc[32], qd[32], fl8 = 0;
    if (f->width != 256 || op < CFT_SF_FMA || op > CFT_SF_MUL || rnd < CFT_SF_RNE ||
        rnd > CFT_SF_RMM)
        return cft_sf_compute(f, op, rnd, a, b, c, out, flags);
    *flags = 0;
    cft_bn_store(a, qa, 32);
    cft_bn_store(b, qb, 32);
    cft_bn_store(c, qc, 32);
    if (fx256_steer(op, qa, qb, qc))
        return 1;
    fx256_fma_lane(qa, qb, qc, rnd, qd, &fl8);
    if (fl8 & 0x80u)
        return 1;
    cft_bn_zero(out);
    cft_bn_load(out, qd, 32);
    *flags = (uint32_t)(fl8 & 0x1Fu);
    return 0;
}

/* binary128: the same through fma128_fixed.h, at 16 bytes */
CFT_HD static inline int fxalu128_compute(const cft_fmt_desc *f, int op, int rnd,
                                          const cft_bn *a, const cft_bn *b, const cft_bn *c,
                                          cft_bn *out, uint32_t *flags)
{
    uint8_t qa[16], qb[16], qc[16], qd[16], fl8 = 0;
    if (f->width != 128 || op < CFT_SF_FMA || op > CFT_SF_MUL || rnd < CFT_SF_RNE ||
        rnd > CFT_SF_RMM)
        return cft_sf_compute(f, op, rnd, a, b, c, out, flags);
    *flags = 0;
    cft_bn_store(a, qa, 16);
    cft_bn_store(b, qb, 16);
    cft_bn_store(c, qc, 16);
    if (fx128_steer(op, qa, qb, qc))
        return 1;
    fx128_fma_lane(qa, qb, qc, rnd, qd, &fl8);
    if (fl8 & 0x80u)
        return 1;
    cft_bn_zero(out);
    cft_bn_load(out, qd, 16);
    *flags = (uint32_t)(fl8 & 0x1Fu);
    return 0;
}

#endif /* CFT_SEQ_ALU_FIXED_H */
