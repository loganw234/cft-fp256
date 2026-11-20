/* Copyright 2026 Logan W.
 * SPDX-License-Identifier: Apache-2.0
 *
 * The fixed tier's differential streams at binary128 (round 3's G3A2), one
 * source for hip-fmadiff --format fp128 (host/tools/hip_fmadiff.cpp, on a
 * GPU) and fma128test (host/tests/fma128_test.c, on a host). Included after
 * bigint.c, softfloat.c and src/fma128_fixed.h, whose CFT_HD,
 * cft_sf_compute, cft_bn and fx128_* it uses; it includes nothing and reads
 * no variable of the environment. tools/fx256_stream.h is binary256's and
 * is not this file: the two sit in one unit, every name here FXS128_ or
 * fxs128_.
 *
 * COUNTER-BASED: case i of seed S is a pure function of (S, i), so lane i
 * is the same case on every device, on the CPU, and from any starting lane
 * (hip-fmadiff --base). The generator is G3A's scratch prototype's
 * (fma128_proto.hip, which measured fp128's lever), moved here with its
 * names prefixed and its draws unchanged, so that its first-chunk sha256s
 * at seed 20261110 are the anchor of the move. Two streams:
 *
 *   study  study GPU-A's nine families at binary128's constants: raw bits;
 *          operands at the subnormal edge; products at the underflow and
 *          at the overflow edge; deep and exact cancellation; exact ties;
 *          c swept across +-244 binades; the specials.
 *   edge   the five classes GPU-A's generator does not aim at, scaled to
 *          binary128, each family a number after the nine, every
 *          attribute, random signs:
 *           9  cancellation near EMIN: c = -(a*b rounded), the product a
 *              few binades either side of the subnormal boundary, a few
 *              ulps off;
 *          10  cancellation near EMAX, the same at the top binades;
 *          11  c at the normal boundary - the smallest normal and the
 *              largest subnormal, a few ulps either way - against products
 *              at the same scale and at far ones (within 300 binades);
 *          12  overflow by a rounding carry: a product of all-ones
 *              significands (the fraction's top 80 to 112 bits) in the
 *              largest binade or the one below it, and a c near half its
 *              ulp, below, at and above the threshold;
 *          13  the alignment edges: c above the product's lead by 25 to 33
 *              binades (where the fixed window's sticky first arises), c
 *              below it by 138 to 146 (c's own sticky edge), and either way
 *              by 226 to 234 (softfloat.c's FAR = 2p + 4 = 230 switch).
 *
 * The lanes: fxs128_generic_lane is libcft's cft_sf_compute(op) on cft_bn
 * (the generic tier's arithmetic); fxs128_fixed_lane is fx128_steer then
 * fx128_fma_lane (the fixed tier's, the functions k_run128 calls), with
 * hip-fmadiff's four fp128 lane plants under CFT_HIP_PLANTS alone. A lane
 * that refuses writes d = 0 and flags 0x80, which no IEEE flag is, so a
 * refusal is a difference, never a pass. No operand is held in a double.
 */
#ifndef CFT_FX128_STREAM_H
#define CFT_FX128_STREAM_H

#define FXS128_STUDY 0
#define FXS128_EDGE  1

#ifdef CFT_HIP_PLANTS
/* hip-fmadiff's fp128 plants, on its fixed lane alone (the library's names) */
#define FXS128_PL_RMM     1u
#define FXS128_PL_FLAG    2u
#define FXS128_PL_STEER   4u
#define FXS128_PL_MULSIGN 8u
#endif

/* NOT INLINED on a GPU, from the start: G3A found hip-fmadiff's fp256
 * generic lane, inlined, making an illegal memory access on the RTX 5060 Ti
 * (nvcc's sm_120 code) on --op sub whenever four or more lanes shared a
 * warp, and running out of line (tools/fx256_stream.h's FXS_NOINLINE;
 * BELIEVED the compiler's, not isolated). The fp128 prototype's generic
 * lane was out of line too. */
#if defined(__CUDACC__) || defined(__HIP__)
#define FXS128_NOINLINE __noinline__
#else
#define FXS128_NOINLINE
#endif

/* The generic tier's lane: cft_sf_compute(op) on cft_bn, as k_run runs an
 * element (at FMA, the prototype's generic lane). */
CFT_HD FXS128_NOINLINE static void fxs128_generic_lane(const cft_fmt_desc *f, int op,
                                                       const uint8_t *pa, const uint8_t *pb,
                                                       const uint8_t *pc, int rnd,
                                                       uint8_t *pd, uint8_t *pflags)
{
    cft_bn ba, bb, bc, bo;
    uint32_t fl = 0;
    int k;
    cft_bn_zero(&ba); cft_bn_zero(&bb); cft_bn_zero(&bc);
    cft_bn_load(&ba, pa, 16); cft_bn_load(&bb, pb, 16); cft_bn_load(&bc, pc, 16);
    if (cft_sf_compute(f, op, rnd, &ba, &bb, &bc, &bo, &fl)) {
        for (k = 0; k < 16; k++) pd[k] = 0;
        *pflags = 0x80;
        return;
    }
    cft_bn_store(&bo, pd, 16);
    *pflags = (uint8_t)fl;
}

/* The fixed tier's lane: the operands copied, steered by fx128_steer and
 * run by fx128_fma_lane, as k_run128 runs an element. `plant` is 0 but in
 * hip-fmadiff's plant build. */
CFT_HD static void fxs128_fixed_lane(int op, const uint8_t *pa, const uint8_t *pb,
                                     const uint8_t *pc, int rnd, uint8_t *pd, uint8_t *pflags,
                                     unsigned plant)
{
    uint8_t qa[16], qb[16], qc[16], fl8 = 0;
    int k;
    (void)plant;
#pragma unroll
    for (k = 0; k < 16; k++) {
        qa[k] = pa[k];
        qb[k] = pb[k];
        qc[k] = pc[k];
    }
#ifdef CFT_HIP_PLANTS
    if ((plant & FXS128_PL_RMM) && rnd == CFT_SF_RMM)
        rnd = CFT_SF_RNE;
#endif
    if (fx128_steer(op, qa, qb, qc)) {
        for (k = 0; k < 16; k++) pd[k] = 0;
        *pflags = 0x80;
        return;
    }
#ifdef CFT_HIP_PLANTS
    if ((plant & FXS128_PL_STEER) && op == CFT_SF_SUB)
        qc[15] ^= 0x80u;
    if ((plant & FXS128_PL_MULSIGN) && op == CFT_SF_MUL)
        qc[15] = 0;
#endif
    fx128_fma_lane(qa, qb, qc, rnd, pd, &fl8);
#ifdef CFT_HIP_PLANTS
    if ((plant & FXS128_PL_FLAG) && !(fl8 & 0x80u))
        fl8 &= (uint8_t)~(unsigned)CFT_SF_UNDERFLOW;
#endif
    *pflags = fl8;
}

/* ---- the generator: the fp128 prototype's, its names prefixed ---------- */

CFT_HD static inline uint64_t fxs128_next(uint64_t *s)       /* splitmix64 */
{
    uint64_t z = (*s += 0x9E3779B97F4A7C15ull);
    z = (z ^ (z >> 30)) * 0xBF58476D1CE4E5B9ull;
    z = (z ^ (z >> 27)) * 0x94D049BB133111EBull;
    return z ^ (z >> 31);
}

/* w = an fp128 encoding: sign, biased exponent field, a random fraction */
CFT_HD static inline void fxs128_val(uint64_t *s, uint32_t *w, uint32_t sign, uint32_t ef)
{
    const uint64_t r0 = fxs128_next(s), r1 = fxs128_next(s);
    w[0] = (uint32_t)r0; w[1] = (uint32_t)(r0 >> 32); w[2] = (uint32_t)r1;
    w[3] = ((uint32_t)(r1 >> 32) & 0xFFFFu) | (ef & FX128_EXPF) << 16 | sign << 31;
}

CFT_HD static inline void fxs128_put(const uint32_t *w, uint8_t *p)
{
    int i;
    for (i = 0; i < 16; i++) p[i] = (uint8_t)(w[i >> 2] >> (8 * (i & 3)));
}

CFT_HD static inline void fxs128_get(const uint8_t *p, uint32_t *w)
{
    int k;
    for (k = 0; k < 4; k++)
        w[k] = (uint32_t)p[4 * k] | (uint32_t)p[4 * k + 1] << 8 |
               (uint32_t)p[4 * k + 2] << 16 | (uint32_t)p[4 * k + 3] << 24;
}

CFT_HD static inline uint32_t fxs128_clampef(int64_t ef)
{
    return ef < 0 ? 0u : ef > 0x7FFE ? 0x7FFEu : (uint32_t)ef;
}

/* One special of sixteen: zeros, infinities, NaNs (quiet, signalling, with a
 * payload), ones, the largest normal, the smallest normal and subnormals. */
CFT_HD static inline void fxs128_special(uint64_t *s, uint32_t *w)
{
    const uint32_t k = (uint32_t)(fxs128_next(s) % 16u), sg = k & 1u;
    int i;
    for (i = 0; i < 4; i++) w[i] = 0;
    switch (k >> 1) {
    case 0: break;                                                  /* zero */
    case 1: w[3] = 0x7FFF0000u; break;                              /* inf */
    case 2: w[3] = sg ? 0x7FFF0000u : 0x7FFF8000u; w[0] = 1; break; /* sNaN, qNaN+1 */
    case 3: w[3] = (uint32_t)FX128_BIAS << 16; break;               /* one */
    case 4: for (i = 0; i < 3; i++) w[i] = 0xFFFFFFFFu;
            w[3] = 0x7FFE0000u | 0xFFFFu; break;                    /* max normal */
    case 5: w[3] = 1u << 16; break;                                 /* min normal */
    case 6: w[0] = 1; break;                                        /* min subnormal */
    default: for (i = 0; i < 3; i++) w[i] = 0xFFFFFFFFu;
             w[3] = 0xFFFFu; break;                                 /* max subnormal */
    }
    if (k >> 1 != 2) w[3] |= sg << 31;
}

/* c = -(a*b rounded by the generic lane), a few ulps off when `off` */
CFT_HD static void fxs128_cancel(const cft_fmt_desc *f, uint64_t *s, const uint32_t *wa,
                                 const uint32_t *wb, uint32_t *wc, int rnd, int off)
{
    uint8_t ta[16], tb[16], tz[16] = {0}, tp[16], tf;
    fxs128_put(wa, ta); fxs128_put(wb, tb);
    fxs128_generic_lane(f, CFT_SF_FMA, ta, tb, tz, rnd, tp, &tf);
    fxs128_get(tp, wc);
    wc[3] ^= 1u << 31;                          /* c = -(a*b rounded) */
    if (off && (fxs128_next(s) & 1u))
        wc[0] += (uint32_t)(fxs128_next(s) % 5) - 2u;        /* a few ulps off */
}

/* Case i of a stream under seed: a family and a rounding attribute each.
 * f is binary128's descriptor (cft_sf_formats[2], passed by value to a
 * GPU). The arms are the prototype's g_case, unchanged. */
CFT_HD static void fxs128_gen_case(const cft_fmt_desc *f, int stream, uint64_t seed, int64_t i,
                                   uint8_t *pa, uint8_t *pb, uint8_t *pc, uint8_t *prnd)
{
    uint64_t s = seed ^ ((uint64_t)i * 0xD1B54A32D192ED03ull);
    uint32_t wa[4], wb[4], wc[4], sa, sb, sc;
    const uint32_t fam = stream == FXS128_EDGE ? 9u + (uint32_t)(fxs128_next(&s) % 5u)
                                               : (uint32_t)(fxs128_next(&s) % 9u);
    const int rnd = (int)(fxs128_next(&s) % 5u);
    const int64_t B = FX128_BIAS;
    int k;
    sa = (uint32_t)fxs128_next(&s) & 1u; sb = (uint32_t)fxs128_next(&s) & 1u;
    sc = (uint32_t)fxs128_next(&s) & 1u;
    switch (fam) {
    case 0:                                         /* raw bits */
        fxs128_val(&s, wa, sa, (uint32_t)fxs128_next(&s));
        fxs128_val(&s, wb, sb, (uint32_t)fxs128_next(&s));
        fxs128_val(&s, wc, sc, (uint32_t)fxs128_next(&s));
        break;
    case 1:                                         /* operands at the subnormal edge */
        fxs128_val(&s, wa, sa, (uint32_t)(fxs128_next(&s) % 3));
        fxs128_val(&s, wb, sb, (uint32_t)(fxs128_next(&s) % 3));
        fxs128_val(&s, wc, sc, (uint32_t)(fxs128_next(&s) % 3));
        break;
    case 2: case 3: {                               /* products at the underflow / overflow edge */
        const int64_t t = fam == 2 ? FX128_EMIN - 116 + (int64_t)(fxs128_next(&s) % 119)
                                   : FX128_EMAX - 2 + (int64_t)(fxs128_next(&s) % 4);
        const int64_t ea = fam == 2 ? 1 + (int64_t)(fxs128_next(&s) % 16000)
                                    : B + 1 + (int64_t)(fxs128_next(&s) % 16000);
        fxs128_val(&s, wa, sa, (uint32_t)ea);
        fxs128_val(&s, wb, sb, fxs128_clampef(t + 2 * B - ea));
        fxs128_val(&s, wc, sc, fam == 2 ? 0u : 0x7FFC + (uint32_t)(fxs128_next(&s) % 3));
        if (fxs128_next(&s) & 1u)
            for (k = 0; k < 4; k++) wc[k] = k == 3 ? sc << 31 : 0u;     /* c = +-0 */
        break;
    }
    case 4: case 7:                                 /* deep and exact cancellation */
        fxs128_val(&s, wa, sa, (uint32_t)(B - 32 + (int64_t)(fxs128_next(&s) % 64)));
        fxs128_val(&s, wb, sb, (uint32_t)(B - 32 + (int64_t)(fxs128_next(&s) % 64)));
        if (fam == 7)                               /* short significands: a*b exact */
            for (k = 0; k < 2; k++) { wa[k] = 0; wb[k] = 0; }
        fxs128_cancel(f, &s, wa, wb, wc, rnd, fam == 4);
        break;
    case 5: {                                       /* exact ties, normal and subnormal */
        const int sub = (int)(fxs128_next(&s) & 1u);
        const int t = sub ? 1 + (int)(fxs128_next(&s) % 100) : 0;
        const int kk = 1 + (int)(fxs128_next(&s) % (uint64_t)(112 - t)), jj = 113 - t - kk;
        const int64_t pe = sub ? FX128_EMIN - t : (int64_t)(fxs128_next(&s) % 4000) - 2000;
        const int64_t ea = (pe / 2) + B, eb = pe - pe / 2 + B;
        for (k = 0; k < 4; k++) { wa[k] = 0; wb[k] = 0; wc[k] = 0; }
        wa[(112 - kk) >> 5] |= 1u << ((112 - kk) & 31);
        wb[(112 - jj) >> 5] |= 1u << ((112 - jj) & 31);
        wa[3] |= (uint32_t)ea << 16 | sa << 31;
        wb[3] |= (uint32_t)eb << 16 | sb << 31;
        wc[3] = sc << 31;                           /* c = +-0 */
        break;
    }
    case 6: {                                       /* c swept across the alignment window */
        const int64_t ea = B - 8192 + (int64_t)(fxs128_next(&s) % 16384);
        const int64_t eb = B - 8192 + (int64_t)(fxs128_next(&s) % 16384);
        const int64_t d = (int64_t)(fxs128_next(&s) % (2 * 244 + 1)) - 244;
        fxs128_val(&s, wa, sa, (uint32_t)ea); fxs128_val(&s, wb, sb, (uint32_t)eb);
        fxs128_val(&s, wc, sc, fxs128_clampef(ea + eb - B + d));
        break;
    }
    case 8:                                         /* specials in every slot */
        fxs128_special(&s, wa); fxs128_special(&s, wb); fxs128_special(&s, wc);
        break;
    /* ---- the edge stream ---- */
    case 9: case 10: {                              /* cancellation near EMIN / EMAX */
        const int64_t t = fam == 9 ? FX128_EMIN - 12 + (int64_t)(fxs128_next(&s) % 25)
                                   : FX128_EMAX - 10 + (int64_t)(fxs128_next(&s) % 12);
        const int64_t ea = fam == 9 ? 1 + (int64_t)(fxs128_next(&s) % 16000)
                                    : B + 1 + (int64_t)(fxs128_next(&s) % 16000);
        fxs128_val(&s, wa, sa, fxs128_clampef(ea));
        fxs128_val(&s, wb, sb, fxs128_clampef(t + 2 * B - ea));
        if (fxs128_next(&s) % 4 == 0)               /* short significands: a*b exact */
            for (k = 0; k < 2; k++) { wa[k] = 0; wb[k] = 0; }
        fxs128_cancel(f, &s, wa, wb, wc, rnd, 1);
        break;
    }
    case 11: {                                      /* c at the normal boundary */
        const uint32_t ulps = (uint32_t)(fxs128_next(&s) % 4);
        const int64_t t = (fxs128_next(&s) & 1u) ? FX128_EMIN - 4 + (int64_t)(fxs128_next(&s) % 9)
                                                 : FX128_EMIN - 300 + (int64_t)(fxs128_next(&s) % 601);
        const int64_t ea = B + t / 2;
        for (k = 0; k < 4; k++) wc[k] = 0;
        if (fxs128_next(&s) & 1u) {                 /* the smallest normal, a few ulps up */
            wc[0] = ulps;
            wc[3] = 1u << 16;
        } else {                                    /* the largest subnormal, a few ulps down */
            for (k = 0; k < 3; k++) wc[k] = 0xFFFFFFFFu;
            wc[3] = 0xFFFFu;
            wc[0] -= ulps;
        }
        wc[3] |= sc << 31;
        fxs128_val(&s, wa, sa, fxs128_clampef(ea));
        fxs128_val(&s, wb, sb, fxs128_clampef(t + 2 * B - ea));
        break;
    }
    case 12: {                                      /* overflow by a rounding carry */
        const int64_t top = FX128_EMAX - (int64_t)(fxs128_next(&s) % 2);
        const int64_t x = (int64_t)(fxs128_next(&s) % 12000) - 6000;
        const int ones = 80 + (int)(fxs128_next(&s) % 33);      /* the top 80 to 112 bits */
        fxs128_val(&s, wa, sa, fxs128_clampef(B + x));
        for (k = 0; k < 112; k++)                   /* the fraction's top `ones` bits set */
            if (k >= 112 - ones)
                wa[k >> 5] |= 1u << (k & 31);
        for (k = 0; k < 4; k++) wb[k] = 0;
        if (fxs128_next(&s) & 1u)                   /* b = 2^y, or 2^y (1 + a little) */
            wb[0] = (uint32_t)fxs128_next(&s) & 0xFFFFu;
        wb[3] |= fxs128_clampef(B + top - x) << 16 | sb << 31;
        fxs128_val(&s, wc, sc, fxs128_clampef(B + top - 115 + (int64_t)(fxs128_next(&s) % 5)));
        if (fxs128_next(&s) % 3 == 0)               /* c a power of two: the exact ties */
            for (k = 0; k < 3; k++) wc[k] = 0;
        if (fxs128_next(&s) % 3 == 0)
            wc[3] &= ~0xFFFFu;
        break;
    }
    default: {                                      /* 13: the alignment edges */
        const uint32_t kind = (uint32_t)(fxs128_next(&s) % 4);
        const int64_t g = kind == 0 ? 25 + (int64_t)(fxs128_next(&s) % 9)
                        : kind == 1 ? -(138 + (int64_t)(fxs128_next(&s) % 9))
                        : kind == 2 ? 226 + (int64_t)(fxs128_next(&s) % 9)
                                    : -(226 + (int64_t)(fxs128_next(&s) % 9));
        const int64_t ea = B - 6000 + (int64_t)(fxs128_next(&s) % 12000);
        const int64_t eb = B - 6000 + (int64_t)(fxs128_next(&s) % 12000);
        fxs128_val(&s, wa, sa, (uint32_t)ea); fxs128_val(&s, wb, sb, (uint32_t)eb);
        fxs128_val(&s, wc, sc, fxs128_clampef(ea + eb - B + g));
        break;
    }
    }
    fxs128_put(wa, pa); fxs128_put(wb, pb); fxs128_put(wc, pc);
    *prnd = (uint8_t)rnd;
}

/* The stream for ADD and SUB: the generator aims at a*b + c, so a becomes
 * a*b rounded to nearest (and for SUB c becomes -c), and a + c, a - (-c)
 * meet the same alignments a*b + c did; MUL takes a and b as they are (the
 * study's rule, tools/fx256_stream.h's fxs_prep_case at 16 bytes). */
CFT_HD static void fxs128_prep_case(const cft_fmt_desc *f, int op, uint8_t *pa,
                                    const uint8_t *pb, uint8_t *pc)
{
    uint8_t z[16] = {0}, p[16], fl;
    int k;
    if (op != CFT_SF_ADD && op != CFT_SF_SUB)
        return;
    fxs128_generic_lane(f, CFT_SF_FMA, pa, pb, z, CFT_SF_RNE, p, &fl);
    for (k = 0; k < 16; k++)
        pa[k] = p[k];
    if (op == CFT_SF_SUB)
        pc[15] ^= 0x80;
}

#endif /* CFT_FX128_STREAM_H */
