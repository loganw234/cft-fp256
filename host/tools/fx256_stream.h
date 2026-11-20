/* Copyright 2026 Logan W.
 * SPDX-License-Identifier: Apache-2.0
 *
 * The fixed tier's differential streams (round 3's G3A), one source for
 * hip-fmadiff (host/tools/hip_fmadiff.cpp, on a GPU) and fma256test
 * (host/tests/fma256_test.c, on a host). Included after bigint.c,
 * softfloat.c and src/fma256_fixed.h, whose CFT_HD, cft_sf_compute,
 * cft_bn and fx256_* it uses; it includes nothing and reads no variable of
 * the environment.
 *
 * COUNTER-BASED: case i of seed S is a pure function of (S, i), so lane i
 * is the same case on every device, on the CPU, and from any starting lane
 * (hip-fmadiff --base). Two streams:
 *
 *   study  study GPU-A's nine families exactly (docs/studies/gpu-a/
 *          cft_fma.hip's gpua_gen_case, its names prefixed), so that its
 *          first-chunk sha256s reproduce GPU-A's - the anchor of the move:
 *          raw bits; operands at the subnormal edge; products at the
 *          underflow and at the overflow edge; deep and exact cancellation;
 *          exact ties; c swept across +-514 binades; the specials.
 *   edge   the five classes the study's generator does not aim at, each
 *          family a number after the nine, every attribute, random signs:
 *           9  cancellation near EMIN: c = -(a*b rounded), the product a
 *              few binades either side of the subnormal boundary, a few
 *              ulps off;
 *          10  cancellation near EMAX, the same at the top binades;
 *          11  c at the normal boundary - the smallest normal and the
 *              largest subnormal, a few ulps either way - against products
 *              at the same scale and at far ones;
 *          12  overflow by a rounding carry: a product of all-ones
 *              significands in the largest binade (or the one below it)
 *              and a c near half its ulp, below, at and above the threshold;
 *          13  the alignment edges: c above the product's lead by 33 to 41
 *              binades (where the window's sticky first arises: 37 for a
 *              474-bit product, 38 for a 473-bit one), c below it by 270 to
 *              278 (c's own sticky edge, 274 for 237 bits), and either way
 *              by 474 to 482 (softfloat.c's FAR = 2p + 4 = 478 switch).
 *
 * The lanes: fxs_generic_lane is libcft's cft_sf_compute(op) on cft_bn
 * (the generic tier's arithmetic); fxs_fixed_lane is fx256_steer then
 * fx256_fma_lane (the fixed tier's, the functions k_run256 calls), with
 * hip-fmadiff's four lane plants under CFT_HIP_PLANTS alone. A lane that
 * refuses writes d = 0 and flags 0x80, which no IEEE flag is, so a
 * refusal is a difference, never a pass.
 */
#ifndef CFT_FX256_STREAM_H
#define CFT_FX256_STREAM_H

#define FXS_STUDY 0
#define FXS_EDGE  1

#ifdef CFT_HIP_PLANTS
/* hip-fmadiff's plants, on its fixed lane alone (the library's names) */
#define FXS_PL_RMM     1u
#define FXS_PL_FLAG    2u
#define FXS_PL_STEER   4u
#define FXS_PL_MULSIGN 8u
#endif

/* NOT INLINED on a GPU (G3A, MEASURED 2026-11-20): with this lane inlined
 * into hip-fmadiff's generic kernel - and with k_run's own lane text written
 * into that kernel's body - nvcc's sm_120 code (CUDA 12.9 through HIP
 * 7.2.4) made an illegal memory access on --op sub whenever four or more
 * lanes shared a warp; out of line it runs, and so does every op on the
 * RX 7600. The backend's k_run on the same cases is right under both tiers
 * (a scratch probe, 65,536 cases, 0 differing), so it is this unit's
 * code, not libcft's arithmetic; the lane is the same function either way. */
#if defined(__CUDACC__) || defined(__HIP__)
#define FXS_NOINLINE __noinline__
#else
#define FXS_NOINLINE
#endif

/* The generic tier's lane: cft_sf_compute(op) on cft_bn, as k_run runs an
 * element (the study's gpua_op_lane; at FMA, its gpua_fma_lane at 32). */
CFT_HD FXS_NOINLINE static void fxs_generic_lane(const cft_fmt_desc *f, int op, const uint8_t *pa,
                                    const uint8_t *pb, const uint8_t *pc, int rnd,
                                    uint8_t *pd, uint8_t *pflags)
{
    cft_bn ba, bb, bc, bo;
    uint32_t fl = 0;
    int k;
    cft_bn_zero(&ba); cft_bn_zero(&bb); cft_bn_zero(&bc);
    cft_bn_load(&ba, pa, 32); cft_bn_load(&bb, pb, 32); cft_bn_load(&bc, pc, 32);
    if (cft_sf_compute(f, op, rnd, &ba, &bb, &bc, &bo, &fl)) {
        for (k = 0; k < 32; k++) pd[k] = 0;
        *pflags = 0x80;
        return;
    }
    cft_bn_store(&bo, pd, 32);
    *pflags = (uint8_t)fl;
}

/* The fixed tier's lane: the operands copied, steered by fx256_steer and
 * run by fx256_fma_lane, as k_run256 runs an element. `plant` is 0 but in
 * hip-fmadiff's plant build. */
CFT_HD static void fxs_fixed_lane(int op, const uint8_t *pa, const uint8_t *pb,
                                  const uint8_t *pc, int rnd, uint8_t *pd, uint8_t *pflags,
                                  unsigned plant)
{
    uint8_t qa[32], qb[32], qc[32], fl8 = 0;
    int k;
    (void)plant;
#pragma unroll
    for (k = 0; k < 32; k++) {
        qa[k] = pa[k];
        qb[k] = pb[k];
        qc[k] = pc[k];
    }
#ifdef CFT_HIP_PLANTS
    if ((plant & FXS_PL_RMM) && rnd == CFT_SF_RMM)
        rnd = CFT_SF_RNE;
#endif
    if (fx256_steer(op, qa, qb, qc)) {
        for (k = 0; k < 32; k++) pd[k] = 0;
        *pflags = 0x80;
        return;
    }
#ifdef CFT_HIP_PLANTS
    if ((plant & FXS_PL_STEER) && op == CFT_SF_SUB)
        qc[31] ^= 0x80u;
    if ((plant & FXS_PL_MULSIGN) && op == CFT_SF_MUL)
        qc[31] = 0;
#endif
    fx256_fma_lane(qa, qb, qc, rnd, pd, &fl8);
#ifdef CFT_HIP_PLANTS
    if ((plant & FXS_PL_FLAG) && !(fl8 & 0x80u))
        fl8 &= (uint8_t)~(unsigned)CFT_SF_UNDERFLOW;
#endif
    *pflags = fl8;
}

/* ---- the generator: study GPU-A's, its names prefixed ------------------ */

CFT_HD static inline uint64_t fxs_next(uint64_t *s)          /* splitmix64 */
{
    uint64_t z = (*s += 0x9E3779B97F4A7C15ull);
    z = (z ^ (z >> 30)) * 0xBF58476D1CE4E5B9ull;
    z = (z ^ (z >> 27)) * 0x94D049BB133111EBull;
    return z ^ (z >> 31);
}

/* w = an fp256 encoding: sign, biased exponent field, a random fraction */
CFT_HD static inline void fxs_val(uint64_t *s, uint32_t *w, uint32_t sign, uint32_t ef)
{
    int i;
    for (i = 0; i < 8; i += 2) {
        const uint64_t r = fxs_next(s);
        w[i] = (uint32_t)r;
        w[i + 1] = (uint32_t)(r >> 32);
    }
    w[7] = (w[7] & 0xFFFu) | (ef & FX256_EXPF) << 12 | sign << 31;
}

CFT_HD static inline void fxs_put(const uint32_t *w, uint8_t *p)
{
    int i;
    for (i = 0; i < 32; i++)
        p[i] = (uint8_t)(w[i >> 2] >> (8 * (i & 3)));
}

CFT_HD static inline void fxs_get(const uint8_t *p, uint32_t *w)
{
    int k;
    for (k = 0; k < 8; k++)
        w[k] = (uint32_t)p[4 * k] | (uint32_t)p[4 * k + 1] << 8 |
               (uint32_t)p[4 * k + 2] << 16 | (uint32_t)p[4 * k + 3] << 24;
}

CFT_HD static inline uint32_t fxs_clampef(int64_t ef)
{
    return ef < 0 ? 0u : ef > 0x7FFFE ? 0x7FFFEu : (uint32_t)ef;
}

/* One special of sixteen: zeros, infinities, NaNs (quiet, signalling, with a
 * payload), ones, the largest normal, the smallest normal and subnormals. */
CFT_HD static inline void fxs_special(uint64_t *s, uint32_t *w)
{
    const uint32_t k = (uint32_t)(fxs_next(s) % 16u), sg = k & 1u;
    int i;
    for (i = 0; i < 8; i++) w[i] = 0;
    switch (k >> 1) {
    case 0: break;                                                  /* zero */
    case 1: w[7] = 0x7FFFF000u; break;                              /* inf */
    case 2: w[7] = sg ? 0x7FFFF000u : 0x7FFFF800u; w[0] = 1; break; /* sNaN, qNaN+1 */
    case 3: w[7] = (uint32_t)FX256_BIAS << 12; break;               /* one */
    case 4: for (i = 0; i < 7; i++) w[i] = 0xFFFFFFFFu;
            w[7] = 0x7FFFE000u | 0xFFFu; break;                     /* max normal */
    case 5: w[7] = 1u << 12; break;                                 /* min normal */
    case 6: w[0] = 1; break;                                        /* min subnormal */
    default: for (i = 0; i < 7; i++) w[i] = 0xFFFFFFFFu;
             w[7] = 0xFFFu; break;                                  /* max subnormal */
    }
    if (k >> 1 != 2) w[7] |= sg << 31;
}

/* c = -(a*b rounded by the generic lane), a few ulps off when `off` */
CFT_HD static void fxs_cancel(const cft_fmt_desc *f, uint64_t *s, const uint32_t *wa,
                              const uint32_t *wb, uint32_t *wc, int rnd, int off)
{
    uint8_t ta[32], tb[32], tz[32] = {0}, tp[32], tf;
    fxs_put(wa, ta); fxs_put(wb, tb);
    fxs_generic_lane(f, CFT_SF_FMA, ta, tb, tz, rnd, tp, &tf);
    fxs_get(tp, wc);
    wc[7] ^= 1u << 31;                          /* c = -(a*b rounded) */
    if (off && (fxs_next(s) & 1u))
        wc[0] += (uint32_t)(fxs_next(s) % 5) - 2u;           /* a few ulps off */
}

/* Case i of a stream under seed: a family and a rounding attribute each.
 * f is binary256's descriptor (cft_sf_formats[3], passed by value to a
 * GPU). The study stream's arms are gpua_gen_case's, unchanged. */
CFT_HD static void fxs_gen_case(const cft_fmt_desc *f, int stream, uint64_t seed, int64_t i,
                                uint8_t *pa, uint8_t *pb, uint8_t *pc, uint8_t *prnd)
{
    uint64_t s = seed ^ ((uint64_t)i * 0xD1B54A32D192ED03ull);
    uint32_t wa[8], wb[8], wc[8], sa, sb, sc;
    const uint32_t fam = stream == FXS_EDGE ? 9u + (uint32_t)(fxs_next(&s) % 5u)
                                            : (uint32_t)(fxs_next(&s) % 9u);
    const int rnd = (int)(fxs_next(&s) % 5u);
    const int64_t B = FX256_BIAS;
    int k;
    sa = (uint32_t)fxs_next(&s) & 1u; sb = (uint32_t)fxs_next(&s) & 1u;
    sc = (uint32_t)fxs_next(&s) & 1u;
    switch (fam) {
    case 0:                                         /* raw bits */
        fxs_val(&s, wa, sa, (uint32_t)fxs_next(&s)); fxs_val(&s, wb, sb, (uint32_t)fxs_next(&s));
        fxs_val(&s, wc, sc, (uint32_t)fxs_next(&s));
        break;
    case 1:                                         /* operands at the subnormal edge */
        fxs_val(&s, wa, sa, (uint32_t)(fxs_next(&s) % 3)); fxs_val(&s, wb, sb, (uint32_t)(fxs_next(&s) % 3));
        fxs_val(&s, wc, sc, (uint32_t)(fxs_next(&s) % 3));
        break;
    case 2: case 3: {                               /* products at the underflow / overflow edge */
        const int64_t t = fam == 2 ? FX256_EMIN - 240 + (int64_t)(fxs_next(&s) % 243)
                                   : FX256_EMAX - 2 + (int64_t)(fxs_next(&s) % 4);
        const int64_t ea = fam == 2 ? 1 + (int64_t)(fxs_next(&s) % 262000)
                                    : B + 1 + (int64_t)(fxs_next(&s) % 262000);
        fxs_val(&s, wa, sa, (uint32_t)ea);
        fxs_val(&s, wb, sb, fxs_clampef(t + 2 * B - ea));
        fxs_val(&s, wc, sc, fam == 2 ? 0u : 0x7FFFC + (uint32_t)(fxs_next(&s) % 3));
        if (fxs_next(&s) & 1u)
            for (k = 0; k < 8; k++) wc[k] = k == 7 ? sc << 31 : 0u;      /* c = +-0 */
        break;
    }
    case 4: case 7: {                               /* deep and exact cancellation */
        fxs_val(&s, wa, sa, (uint32_t)(B - 32 + (int64_t)(fxs_next(&s) % 64)));
        fxs_val(&s, wb, sb, (uint32_t)(B - 32 + (int64_t)(fxs_next(&s) % 64)));
        if (fam == 7)                               /* short significands: a*b exact */
            for (k = 0; k < 4; k++) { wa[k] = 0; wb[k] = 0; }
        fxs_cancel(f, &s, wa, wb, wc, rnd, fam == 4);
        break;
    }
    case 5: {                                       /* exact ties, normal and subnormal */
        const int sub = (int)(fxs_next(&s) & 1u);
        const int t = sub ? 1 + (int)(fxs_next(&s) % 200) : 0;
        const int kk = 1 + (int)(fxs_next(&s) % (uint64_t)(236 - t)), jj = 237 - t - kk;
        const int64_t pe = sub ? FX256_EMIN - t : (int64_t)(fxs_next(&s) % 4000) - 2000;
        const int64_t ea = (pe / 2) + B, eb = pe - pe / 2 + B;
        for (k = 0; k < 8; k++) { wa[k] = 0; wb[k] = 0; wc[k] = 0; }
        wa[(236 - kk) >> 5] |= 1u << ((236 - kk) & 31);
        wb[(236 - jj) >> 5] |= 1u << ((236 - jj) & 31);
        wa[7] |= (uint32_t)ea << 12 | sa << 31;
        wb[7] |= (uint32_t)eb << 12 | sb << 31;
        wc[7] = sc << 31;                           /* c = +-0 */
        break;
    }
    case 6: {                                       /* c swept across the alignment window */
        const int64_t ea = B - 131072 + (int64_t)(fxs_next(&s) % 262144);
        const int64_t eb = B - 131072 + (int64_t)(fxs_next(&s) % 262144);
        const int64_t d = (int64_t)(fxs_next(&s) % (2 * 514 + 1)) - 514;
        fxs_val(&s, wa, sa, (uint32_t)ea); fxs_val(&s, wb, sb, (uint32_t)eb);
        fxs_val(&s, wc, sc, fxs_clampef(ea + eb - B + d));
        break;
    }
    case 8:                                         /* specials in every slot */
        fxs_special(&s, wa); fxs_special(&s, wb); fxs_special(&s, wc);
        break;
    /* ---- the edge stream (G3A) ---- */
    case 9: case 10: {                              /* cancellation near EMIN / EMAX */
        const int64_t t = fam == 9 ? FX256_EMIN - 12 + (int64_t)(fxs_next(&s) % 25)
                                   : FX256_EMAX - 10 + (int64_t)(fxs_next(&s) % 12);
        const int64_t ea = fam == 9 ? 1 + (int64_t)(fxs_next(&s) % 262000)
                                    : B + 1 + (int64_t)(fxs_next(&s) % 262000);
        fxs_val(&s, wa, sa, fxs_clampef(ea));
        fxs_val(&s, wb, sb, fxs_clampef(t + 2 * B - ea));
        if (fxs_next(&s) % 4 == 0)                  /* short significands: a*b exact */
            for (k = 0; k < 4; k++) { wa[k] = 0; wb[k] = 0; }
        fxs_cancel(f, &s, wa, wb, wc, rnd, 1);
        break;
    }
    case 11: {                                      /* c at the normal boundary */
        const uint32_t ulps = (uint32_t)(fxs_next(&s) % 4);
        const int64_t t = (fxs_next(&s) & 1u) ? FX256_EMIN - 4 + (int64_t)(fxs_next(&s) % 9)
                                              : (int64_t)(fxs_next(&s) % 1200) - 600 + FX256_EMIN / 2;
        const int64_t ea = B + t / 2;
        for (k = 0; k < 8; k++) wc[k] = 0;
        if (fxs_next(&s) & 1u) {                    /* the smallest normal, a few ulps up */
            wc[0] = ulps;
            wc[7] = 1u << 12;
        } else {                                    /* the largest subnormal, a few ulps down */
            for (k = 0; k < 7; k++) wc[k] = 0xFFFFFFFFu;
            wc[7] = 0xFFFu;
            wc[0] -= ulps;
        }
        wc[7] |= sc << 31;
        fxs_val(&s, wa, sa, fxs_clampef(ea));
        fxs_val(&s, wb, sb, fxs_clampef(t + 2 * B - ea));
        break;
    }
    case 12: {                                      /* overflow by a rounding carry */
        const int64_t top = FX256_EMAX - (int64_t)(fxs_next(&s) % 2);
        const int64_t x = (int64_t)(fxs_next(&s) % 200000) - 100000;
        const int ones = 200 + (int)(fxs_next(&s) % 37);        /* the top 200 to 236 bits */
        fxs_val(&s, wa, sa, fxs_clampef(B + x));
        for (k = 0; k < 236; k++)                   /* the fraction's top `ones` bits set */
            if (k >= 236 - ones)
                wa[k >> 5] |= 1u << (k & 31);
        for (k = 0; k < 8; k++) wb[k] = 0;
        if (fxs_next(&s) & 1u)                      /* b = 2^y, or 2^y (1 + a little) */
            wb[0] = (uint32_t)fxs_next(&s) & 0xFFFFu;
        wb[7] |= fxs_clampef(B + top - x) << 12 | sb << 31;
        fxs_val(&s, wc, sc, fxs_clampef(B + top - 239 + (int64_t)(fxs_next(&s) % 5)));
        if (fxs_next(&s) % 3 == 0)                  /* c a power of two: the exact ties */
            for (k = 0; k < 7; k++) wc[k] = 0;
        if (fxs_next(&s) % 3 == 0)
            wc[7] &= ~0xFFFu;
        break;
    }
    default: {                                      /* 13: the alignment edges */
        const uint32_t kind = (uint32_t)(fxs_next(&s) % 4);
        const int64_t g = kind == 0 ? 33 + (int64_t)(fxs_next(&s) % 9)
                        : kind == 1 ? -(270 + (int64_t)(fxs_next(&s) % 9))
                        : kind == 2 ? 474 + (int64_t)(fxs_next(&s) % 9)
                                    : -(474 + (int64_t)(fxs_next(&s) % 9));
        const int64_t ea = B - 100000 + (int64_t)(fxs_next(&s) % 200000);
        const int64_t eb = B - 100000 + (int64_t)(fxs_next(&s) % 200000);
        fxs_val(&s, wa, sa, (uint32_t)ea); fxs_val(&s, wb, sb, (uint32_t)eb);
        fxs_val(&s, wc, sc, fxs_clampef(ea + eb - B + g));
        break;
    }
    }
    fxs_put(wa, pa); fxs_put(wb, pb); fxs_put(wc, pc);
    *prnd = (uint8_t)rnd;
}

/* The stream for ADD and SUB: the generator aims at a*b + c, so a becomes
 * a*b rounded to nearest (and for SUB c becomes -c), and a + c, a - (-c)
 * meet the same alignments a*b + c did; MUL takes a and b as they are (the
 * study's gpua_prep_case). */
CFT_HD static void fxs_prep_case(const cft_fmt_desc *f, int op, uint8_t *pa, const uint8_t *pb,
                                 uint8_t *pc)
{
    uint8_t z[32] = {0}, p[32], fl;
    int k;
    if (op != CFT_SF_ADD && op != CFT_SF_SUB)
        return;
    fxs_generic_lane(f, CFT_SF_FMA, pa, pb, z, CFT_SF_RNE, p, &fl);
    for (k = 0; k < 32; k++)
        pa[k] = p[k];
    if (op == CFT_SF_SUB)
        pc[31] ^= 0x80;
}

#endif /* CFT_FX256_STREAM_H */
