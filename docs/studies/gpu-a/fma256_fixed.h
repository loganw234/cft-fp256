/* Copyright 2026 Logan W.
 * SPDX-License-Identifier: Apache-2.0
 *
 * GPU-A's second kernel: the binary256 fused multiply-add on fixed-size
 * limbs, included by cft_fma.hip after libcft's arithmetic.
 *
 * NOT libcft's code. The first kernel runs host/src/softfloat.c as it is;
 * this is a second implementation of the same contract, written for a GPU:
 * every array has a fixed size and every index is a constant once the loops
 * unroll, so the values can stay in registers rather than local memory. A
 * second implementation needs its own proof, and it gets the first one's:
 * held bit for bit, results and flags, to the golden corpora and to the
 * first kernel (`cft_fma diff`), on every device it runs on.
 *
 * The method. Unpacking and the special cases are sf_fma's, in its order.
 * The finite case does not align both terms at the lower exponent, as
 * sf_fma's near case does (up to 1,188 bits). It puts the term whose leading
 * bit is higher with that bit at position 509 of a 512-bit window and shifts
 * the other into the window, folding what falls below it into a sticky bit.
 * The sum is then (N + eps) * 2^E, eps in [0, 1) and nonzero exactly when
 * sticky: the value sf_fma rounds. A sticky arises only when the lower term
 * ends below the window, which needs its leading bit 36 or more below the
 * upper one's, so a difference is at least half the upper term, N keeps 509
 * bits or more, and sf_round_pack's precondition (more than p bits whenever
 * sticky) holds. The rounding below is sf_round_pack's, step for step, on
 * (N, E, sticky); the same value and sticky give the same bits and flags.
 */
#define F_P     237
#define F_MANW  236
#define F_BIAS  262143
#define F_EMIN  (-262142)
#define F_EMAX  262143
#define F_EXPF  0x7FFFFu

typedef struct {
    int kind, sign, signaling, e;   /* kind: 0 zero 1 sub 2 norm 3 inf 4 nan */
    uint32_t m[8];
} f_unp;

/* (hi:lo) >> s and the high word of (hi:lo) << s, s in 0..31 */
CFT_HD static inline uint32_t f_fr(uint32_t hi, uint32_t lo, int s)
{
    return (uint32_t)((((uint64_t)hi << 32) | lo) >> s);
}
CFT_HD static inline uint32_t f_fl(uint32_t hi, uint32_t lo, int s)
{
    return (uint32_t)(((((uint64_t)hi << 32) | lo) << s) >> 32);
}

CFT_HD static inline int f_clz32(uint32_t x)          /* x != 0 */
{
    int n = 0;
    if (!(x & 0xFFFF0000u)) { n += 16; x <<= 16; }
    if (!(x & 0xFF000000u)) { n += 8;  x <<= 8; }
    if (!(x & 0xF0000000u)) { n += 4;  x <<= 4; }
    if (!(x & 0xC0000000u)) { n += 2;  x <<= 2; }
    if (!(x & 0x80000000u)) n += 1;
    return n;
}

CFT_HD static inline int f_bitlen(const uint32_t *w, int nl)  /* 0 for zero */
{
    int i, top = -1;
    uint32_t v = 0;
#pragma unroll
    for (i = 0; i < 16; i++)
        if (i < nl && w[i]) { top = i; v = w[i]; }
    return top < 0 ? 0 : 32 * top + 32 - f_clz32(v);
}

/* w >>= s over 16 limbs, ORing what falls off into *sticky; any s >= 0. */
CFT_HD static inline void f_shr16(uint32_t *w, int s, uint32_t *sticky)
{
    int i, k, b;
    uint32_t any = 0;
    if (s >= 512) {
#pragma unroll
        for (i = 0; i < 16; i++) { any |= w[i]; w[i] = 0; }
        *sticky |= any;
        return;
    }
#pragma unroll
    for (k = 8; k >= 1; k >>= 1) {
        const int on = (s >> 5) & k;
        uint32_t drop = 0;
#pragma unroll
        for (i = 0; i < k; i++) drop |= w[i];
        *sticky |= on ? drop : 0u;
#pragma unroll
        for (i = 0; i < 16; i++) w[i] = on ? (i + k < 16 ? w[i + k] : 0u) : w[i];
    }
    b = s & 31;
    *sticky |= w[0] & (uint32_t)((1ull << b) - 1u);
#pragma unroll
    for (i = 0; i < 15; i++) w[i] = f_fr(w[i + 1], w[i], b);
    w[15] >>= b;
}

/* w <<= s over 16 limbs, s in 0..511; returns nonzero if a set bit fell off
 * the top, which the construction never allows (a refusal, not a result). */
CFT_HD static inline uint32_t f_shl16(uint32_t *w, int s)
{
    int i, k, b;
    uint32_t lost = 0;
#pragma unroll
    for (k = 8; k >= 1; k >>= 1) {
        const int on = (s >> 5) & k;
        uint32_t drop = 0;
#pragma unroll
        for (i = 16 - k; i < 16; i++) drop |= w[i];
        lost |= on ? drop : 0u;
#pragma unroll
        for (i = 15; i >= 0; i--) w[i] = on ? (i - k >= 0 ? w[i - k] : 0u) : w[i];
    }
    b = s & 31;
    lost |= f_fl(0u, w[15], b);                       /* the bits pushed out of the top */
#pragma unroll
    for (i = 15; i > 0; i--) w[i] = f_fl(w[i], w[i - 1], b);
    w[0] = f_fl(w[0], 0u, b);
    return lost;
}

CFT_HD static inline void f_shr1_8(uint32_t *w)
{
    int i;
#pragma unroll
    for (i = 0; i < 7; i++) w[i] = (w[i] >> 1) | (w[i + 1] << 31);
    w[7] >>= 1;
}

CFT_HD static inline void f_unpack(const uint8_t *p, f_unp *u)
{
    uint32_t w[8], ef, any;
    int i;
#pragma unroll
    for (i = 0; i < 8; i++)
        w[i] = (uint32_t)p[4 * i] | (uint32_t)p[4 * i + 1] << 8 |
               (uint32_t)p[4 * i + 2] << 16 | (uint32_t)p[4 * i + 3] << 24;
    u->sign = (int)(w[7] >> 31);
    ef = (w[7] >> 12) & F_EXPF;
    any = w[7] & 0xFFFu;
#pragma unroll
    for (i = 0; i < 7; i++) any |= w[i];
#pragma unroll
    for (i = 0; i < 7; i++) u->m[i] = w[i];
    u->m[7] = w[7] & 0xFFFu;
    u->signaling = 0;
    u->e = 0;
    if (ef == F_EXPF) {
        u->kind = any ? 4 : 3;
        u->signaling = any && !((w[7] >> 11) & 1u);
    } else if (ef == 0) {
        u->kind = any ? 1 : 0;
        u->e = F_EMIN - F_MANW;
    } else {
        u->kind = 2;
        u->m[7] |= 1u << 12;
        u->e = (int)ef - F_BIAS - F_MANW;
    }
}

CFT_HD static inline int f_round_up(int rnd, int sign, uint32_t g, uint32_t s, uint32_t lsb)
{
    switch (rnd) {
    case CFT_SF_RNE: return g && (s || lsb);
    case CFT_SF_RMM: return g != 0;
    case CFT_SF_RTZ: return 0;
    case CFT_SF_RDN: return sign && (g || s);
    default:         return !sign && (g || s);           /* RUP */
    }
}

/* sf_round_pack on (N, E, sticky): (N + eps) * 2^E, eps nonzero iff sticky. */
CFT_HD static void f_round_pack(int sign, uint32_t *N, int E, uint32_t sticky, int rnd,
                                uint32_t *out, uint32_t *flags, int *bad)
{
    const int L = f_bitlen(N, 16);
    const int e_norm = E + L - 1;
    const int q = (e_norm > F_EMIN ? e_norm : F_EMIN) - (F_P - 1);
    const int shift = q - E;
    uint32_t kept[8], g = 0, s = 0, g1 = 0, s1 = 0, fl = 0, st = sticky ? 1u : 0u, d = 0;
    int i, inexact = 0, tiny, carry_u = 0, kl, e_res;
    if (L == 0 || (sticky && L <= F_P)) { *bad = 1; return; }
    if (shift <= 0) {                     /* exact: no bit below the ulp */
        if (sticky || f_shl16(N, -shift)) { *bad = 1; return; }
#pragma unroll
        for (i = 8; i < 16; i++) if (N[i]) *bad = 1;
#pragma unroll
        for (i = 0; i < 8; i++) kept[i] = N[i];
        tiny = e_norm < F_EMIN;
    } else {
        if (shift >= 2) {                 /* two bits more than the ulp: */
            f_shr16(N, shift - 2, &st);   /* the guard at q-1 for tininess */
            g1 = N[0] & 1u; s1 = st;
            f_shr16(N, 1, &d);
            g = N[0] & 1u; s = g1 | s1;
        } else {
            g = N[0] & 1u; s = st;
        }
#pragma unroll
        for (i = 8; i < 16; i++) if (N[i]) *bad = 1;
        if (e_norm == F_EMIN - 1 && shift >= 2) {
            /* rounded at q - 1 with the exponent unbounded: does it carry? */
            uint32_t all = 1u;
#pragma unroll
            for (i = 0; i < 7; i++) all &= N[i] == 0xFFFFFFFFu;
            all &= (N[7] & 0x1FFFu) == 0x1FFFu && (N[7] >> 13) == 0;
            carry_u = f_round_up(rnd, sign, g1, s1, N[0] & 1u) && all;
        }
        tiny = e_norm < F_EMIN - 1 || (e_norm == F_EMIN - 1 && !carry_u);
#pragma unroll
        for (i = 0; i < 8; i++) kept[i] = N[i];
        f_shr1_8(kept);
        if (g | s) {
            inexact = 1;
            if (f_round_up(rnd, sign, g, s, kept[0] & 1u)) {
                uint32_t c = 1;
#pragma unroll
                for (i = 0; i < 8; i++) { kept[i] += c; c = c && kept[i] == 0; }
            }
        }
    }
    if (inexact) fl |= CFT_SF_INEXACT;
#pragma unroll
    for (i = 0; i < 8; i++) out[i] = 0;
    kl = f_bitlen(kept, 8);
    if (kl == 0) {                        /* rounded past the smallest subnormal */
        out[7] = (uint32_t)sign << 31;
        *flags = fl | CFT_SF_UNDERFLOW;
        return;
    }
    e_res = q + kl - 1;
    if (e_res > F_EMAX) {
        const int inf = rnd == CFT_SF_RTZ ? 0 : rnd == CFT_SF_RDN ? sign :
                        rnd == CFT_SF_RUP ? !sign : 1;
        if (inf) {
            out[7] = 0x7FFFF000u;
        } else {
#pragma unroll
            for (i = 0; i < 7; i++) out[i] = 0xFFFFFFFFu;
            out[7] = (0x7FFFEu << 12) | 0xFFFu;
        }
        out[7] |= (uint32_t)sign << 31;
        *flags = fl | CFT_SF_OVERFLOW | CFT_SF_INEXACT;
        return;
    }
    if (tiny && inexact) fl |= CFT_SF_UNDERFLOW;
    if (e_res >= F_EMIN) {
        if (kl == F_P + 1) f_shr1_8(kept);           /* rounding carried out */
        kept[7] = (kept[7] & 0xFFFu) | ((uint32_t)(e_res + F_BIAS) << 12);
    }
#pragma unroll
    for (i = 0; i < 8; i++) out[i] = kept[i];
    out[7] |= (uint32_t)sign << 31;
    *flags = fl;
}

CFT_HD static void f256_fma_lane(const uint8_t *pa, const uint8_t *pb, const uint8_t *pc,
                                 int rnd, uint8_t *pd, uint8_t *pflags)
{
    f_unp ua, ub, uc;
    uint32_t out[8], fl = 0;
    int i, bad = 0, done = 1;
    f_unpack(pa, &ua); f_unpack(pb, &ub); f_unpack(pc, &uc);
/* CFT_GPUA_PLANT_FIXED_RMM_AS_RNE is the one-sided plant: this kernel
 * alone, so `cft_fma diff` must go red (send-back 1). */
#if defined(CFT_GPUA_PLANT_RMM_AS_RNE) || defined(CFT_GPUA_PLANT_FIXED_RMM_AS_RNE)
    if (rnd == CFT_SF_RMM)
        rnd = CFT_SF_RNE;
#endif
#pragma unroll
    for (i = 0; i < 8; i++) out[i] = 0;
    const int sp = ua.sign ^ ub.sign;
    if (ua.kind == 4 || ub.kind == 4 || uc.kind == 4) {
        out[7] = 0x7FFFF800u;                               /* the canonical qNaN */
        fl = (ua.signaling || ub.signaling || uc.signaling) ? CFT_SF_INVALID : 0u;
    } else if (ua.kind == 3 || ub.kind == 3) {
        if (ua.kind == 0 || ub.kind == 0 || (uc.kind == 3 && uc.sign != sp)) {
            out[7] = 0x7FFFF800u;
            fl = CFT_SF_INVALID;
        } else {
            out[7] = 0x7FFFF000u | (uint32_t)sp << 31;
        }
    } else if (uc.kind == 3) {
        out[7] = 0x7FFFF000u | (uint32_t)uc.sign << 31;
    } else if (ua.kind == 0 || ub.kind == 0) {
        if (uc.kind == 0) {
            out[7] = (uint32_t)(uc.sign == sp ? uc.sign : rnd == CFT_SF_RDN) << 31;
        } else {                                            /* 0*b + c is c, exactly */
#pragma unroll
            for (i = 0; i < 8; i++)
                out[i] = (uint32_t)pc[4 * i] | (uint32_t)pc[4 * i + 1] << 8 |
                         (uint32_t)pc[4 * i + 2] << 16 | (uint32_t)pc[4 * i + 3] << 24;
        }
    } else {
        done = 0;
    }
    if (!done) {
        uint32_t P[16], X[16], Y[16], N[16], ys = 0;
        int j, ep = ua.e + ub.e;
#pragma unroll
        for (i = 0; i < 16; i++) P[i] = 0;
#pragma unroll
        for (i = 0; i < 8; i++) {                           /* the exact product */
            uint64_t carry = 0;
#pragma unroll
            for (j = 0; j < 8; j++) {
                uint64_t t = (uint64_t)ua.m[i] * ub.m[j] + P[i + j] + carry;
                P[i + j] = (uint32_t)t;
                carry = t >> 32;
            }
            P[i + 8] = (uint32_t)carry;
        }
        if (uc.kind == 0) {
            f_round_pack(sp, P, ep, 0u, rnd, out, &fl, &bad);
        } else {
            uint32_t C[16];
#pragma unroll
            for (i = 0; i < 16; i++) C[i] = i < 8 ? uc.m[i] : 0u;
            const int Lp = f_bitlen(P, 16), Lc = f_bitlen(C, 8);
            const int pbig = ep + Lp - 1 >= uc.e + Lc - 1;
            const int Lx = pbig ? Lp : Lc, ex = pbig ? ep : uc.e, ey = pbig ? uc.e : ep;
            const int sx = pbig ? sp : uc.sign, sy = pbig ? uc.sign : sp;
#pragma unroll
            for (i = 0; i < 16; i++) { X[i] = pbig ? P[i] : C[i]; Y[i] = pbig ? C[i] : P[i]; }
            const int shx = 510 - Lx, E = ex - shx, off = ey - E;
            if (f_shl16(X, shx)) bad = 1;                   /* X's top bit at 509 */
            if (off >= 0) { if (f_shl16(Y, off)) bad = 1; }
            else f_shr16(Y, -off, &ys);
            int sign = sx, cmp = 0;
            uint64_t br = 0;
            if (sx == sy) {
                uint64_t c = 0;
#pragma unroll
                for (i = 0; i < 16; i++) { c += (uint64_t)X[i] + Y[i]; N[i] = (uint32_t)c; c >>= 32; }
            } else {
                if (!ys) {
#pragma unroll
                    for (i = 0; i < 16; i++)
                        if (X[i] != Y[i]) cmp = X[i] > Y[i] ? 1 : -1;  /* highest differing wins */
                }
                if (!ys && cmp == 0) {
                    out[7] = (uint32_t)(rnd == CFT_SF_RDN) << 31;   /* exact cancellation */
                    done = 1;
                } else {
                    const int swap = cmp < 0;
                    sign = swap ? sy : sx;
#pragma unroll
                    for (i = 0; i < 16; i++) {
                        const uint64_t a = swap ? Y[i] : X[i], b = swap ? X[i] : Y[i];
                        const uint64_t t = a - b - br - (i == 0 && ys ? 1u : 0u);
                        N[i] = (uint32_t)t;
                        br = (t >> 63) & 1u;
                    }
                }
            }
            if (!done)
                f_round_pack(sign, N, E, ys, rnd, out, &fl, &bad);
        }
    }
#ifdef CFT_GPUA_PLANT_DROP_FLAG
    fl &= ~(uint32_t)(CFT_GPUA_PLANT_DROP_FLAG);
#endif
#pragma unroll
    for (i = 0; i < 32; i++)
        pd[i] = bad ? 0 : (uint8_t)(out[i >> 2] >> (8 * (i & 3)));
    *pflags = bad ? 0x80 : (uint8_t)fl;
}
