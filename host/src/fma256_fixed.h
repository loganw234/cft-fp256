/* Copyright 2026 Logan W.
 * SPDX-License-Identifier: Apache-2.0
 *
 * The GPU backend's fixed tier (round 3's G3A): the binary256 fused
 * multiply-add on fixed-size limbs. A SECOND IMPLEMENTATION of the contract
 * softfloat.c's sf_fma defines - not libcft's arithmetic, and its agreement
 * with it is evidence by test, not a proof. Device-only in the library:
 * backend_hip.cpp includes it after softfloat.c, whose CFT_HD, CFT_SF_*
 * and cft_fmt_desc it needs (it includes nothing), so it is in libcft only
 * under HIP=1; host/tools/hip_fmadiff.cpp includes it the same way, and
 * host/tests/fma256_test.c builds it on a host (make fma256test), the
 * arithmetic's own test against libcft's with no GPU.
 *
 * Moved from study GPU-A's docs/studies/gpu-a/fma256_fixed.h, which stays
 * as it was: the record that study's captured results refer to. The two
 * are NOT kept in sync. This file is the study's text with the edit table
 * of G3A's ledger applied and nothing else: this comment; an include
 * guard; every name prefixed FX256_ or fx256_; the study's two
 * compile-time plants removed (the tree's plants are its callers', chosen
 * at run time); and two functions added after the lane, fx256_steer (ADD,
 * SUB and MUL as the FMA with steered operands, on the encodings) and
 * fx256_matches (the constants below, typed in, held to the library's
 * descriptor of binary256).
 *
 * Every array has a fixed size and every index is a constant once the
 * loops unroll, so the values can stay in registers rather than local
 * memory. It is held bit for bit, results and flags, to cft_sf_compute by
 * hip-fmadiff's differential streams on each GPU and fma256test's on the
 * CPU, to the golden model by the conformance and edge corpora through
 * hip-corpus, and through the API by hip-test's fixed leg.
 *
 * The method (the study's words). Unpacking and the special cases are
 * sf_fma's, in its order. The finite case does not align both terms at the
 * lower exponent, as sf_fma's near case does (up to 1,188 bits). It puts
 * the term whose leading bit is higher with that bit at position 509 of a
 * 512-bit window and shifts the other into the window, folding what falls
 * below it into a sticky bit. The sum is then (N + eps) * 2^E, eps in
 * [0, 1) and nonzero exactly when sticky: the value sf_fma rounds. A
 * sticky arises only when the lower term ends below the window, which
 * needs its leading bit 36 or more below the upper one's, so a difference
 * is at least half the upper term, N keeps 509 bits or more, and
 * sf_round_pack's precondition (more than p bits whenever sticky) holds.
 * The rounding below is sf_round_pack's, step for step, on (N, E, sticky);
 * the same value and sticky give the same bits and flags. (G3A's count:
 * the product's 473 or 474 bits put its lowest bit at 37 - g or 36 - g
 * when its lead is g below c's, so a sticky first arises at g = 37 for a
 * 474-bit product and 38 for a 473-bit one, and at 274 for c below the
 * product: "36 or more" is the safe side of it.)
 */
#ifndef CFT_FMA256_FIXED_H
#define CFT_FMA256_FIXED_H

#define FX256_P     237
#define FX256_MANW  236
#define FX256_BIAS  262143
#define FX256_EMIN  (-262142)
#define FX256_EMAX  262143
#define FX256_EXPF  0x7FFFFu

typedef struct {
    int kind, sign, signaling, e;   /* kind: 0 zero 1 sub 2 norm 3 inf 4 nan */
    uint32_t m[8];
} fx256_unp;

/* (hi:lo) >> s and the high word of (hi:lo) << s, s in 0..31 */
CFT_HD static inline uint32_t fx256_fr(uint32_t hi, uint32_t lo, int s)
{
    return (uint32_t)((((uint64_t)hi << 32) | lo) >> s);
}
CFT_HD static inline uint32_t fx256_fl(uint32_t hi, uint32_t lo, int s)
{
    return (uint32_t)(((((uint64_t)hi << 32) | lo) << s) >> 32);
}

CFT_HD static inline int fx256_clz32(uint32_t x)          /* x != 0 */
{
    int n = 0;
    if (!(x & 0xFFFF0000u)) { n += 16; x <<= 16; }
    if (!(x & 0xFF000000u)) { n += 8;  x <<= 8; }
    if (!(x & 0xF0000000u)) { n += 4;  x <<= 4; }
    if (!(x & 0xC0000000u)) { n += 2;  x <<= 2; }
    if (!(x & 0x80000000u)) n += 1;
    return n;
}

CFT_HD static inline int fx256_bitlen(const uint32_t *w, int nl)  /* 0 for zero */
{
    int i, top = -1;
    uint32_t v = 0;
#pragma unroll
    for (i = 0; i < 16; i++)
        if (i < nl && w[i]) { top = i; v = w[i]; }
    return top < 0 ? 0 : 32 * top + 32 - fx256_clz32(v);
}

/* w >>= s over 16 limbs, ORing what falls off into *sticky; any s >= 0. */
CFT_HD static inline void fx256_shr16(uint32_t *w, int s, uint32_t *sticky)
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
    for (i = 0; i < 15; i++) w[i] = fx256_fr(w[i + 1], w[i], b);
    w[15] >>= b;
}

/* w <<= s over 16 limbs, s in 0..511; returns nonzero if a set bit fell off
 * the top, which the construction never allows (a refusal, not a result). */
CFT_HD static inline uint32_t fx256_shl16(uint32_t *w, int s)
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
    lost |= fx256_fl(0u, w[15], b);                       /* the bits pushed out of the top */
#pragma unroll
    for (i = 15; i > 0; i--) w[i] = fx256_fl(w[i], w[i - 1], b);
    w[0] = fx256_fl(w[0], 0u, b);
    return lost;
}

CFT_HD static inline void fx256_shr1_8(uint32_t *w)
{
    int i;
#pragma unroll
    for (i = 0; i < 7; i++) w[i] = (w[i] >> 1) | (w[i + 1] << 31);
    w[7] >>= 1;
}

CFT_HD static inline void fx256_unpack(const uint8_t *p, fx256_unp *u)
{
    uint32_t w[8], ef, any;
    int i;
#pragma unroll
    for (i = 0; i < 8; i++)
        w[i] = (uint32_t)p[4 * i] | (uint32_t)p[4 * i + 1] << 8 |
               (uint32_t)p[4 * i + 2] << 16 | (uint32_t)p[4 * i + 3] << 24;
    u->sign = (int)(w[7] >> 31);
    ef = (w[7] >> 12) & FX256_EXPF;
    any = w[7] & 0xFFFu;
#pragma unroll
    for (i = 0; i < 7; i++) any |= w[i];
#pragma unroll
    for (i = 0; i < 7; i++) u->m[i] = w[i];
    u->m[7] = w[7] & 0xFFFu;
    u->signaling = 0;
    u->e = 0;
    if (ef == FX256_EXPF) {
        u->kind = any ? 4 : 3;
        u->signaling = any && !((w[7] >> 11) & 1u);
    } else if (ef == 0) {
        u->kind = any ? 1 : 0;
        u->e = FX256_EMIN - FX256_MANW;
    } else {
        u->kind = 2;
        u->m[7] |= 1u << 12;
        u->e = (int)ef - FX256_BIAS - FX256_MANW;
    }
}

CFT_HD static inline int fx256_round_up(int rnd, int sign, uint32_t g, uint32_t s, uint32_t lsb)
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
CFT_HD static void fx256_round_pack(int sign, uint32_t *N, int E, uint32_t sticky, int rnd,
                                uint32_t *out, uint32_t *flags, int *bad)
{
    const int L = fx256_bitlen(N, 16);
    const int e_norm = E + L - 1;
    const int q = (e_norm > FX256_EMIN ? e_norm : FX256_EMIN) - (FX256_P - 1);
    const int shift = q - E;
    uint32_t kept[8], g = 0, s = 0, g1 = 0, s1 = 0, fl = 0, st = sticky ? 1u : 0u, d = 0;
    int i, inexact = 0, tiny, carry_u = 0, kl, e_res;
    if (L == 0 || (sticky && L <= FX256_P)) { *bad = 1; return; }
    if (shift <= 0) {                     /* exact: no bit below the ulp */
        if (sticky || fx256_shl16(N, -shift)) { *bad = 1; return; }
#pragma unroll
        for (i = 8; i < 16; i++) if (N[i]) *bad = 1;
#pragma unroll
        for (i = 0; i < 8; i++) kept[i] = N[i];
        tiny = e_norm < FX256_EMIN;
    } else {
        if (shift >= 2) {                 /* two bits more than the ulp: */
            fx256_shr16(N, shift - 2, &st);   /* the guard at q-1 for tininess */
            g1 = N[0] & 1u; s1 = st;
            fx256_shr16(N, 1, &d);
            g = N[0] & 1u; s = g1 | s1;
        } else {
            g = N[0] & 1u; s = st;
        }
#pragma unroll
        for (i = 8; i < 16; i++) if (N[i]) *bad = 1;
        if (e_norm == FX256_EMIN - 1 && shift >= 2) {
            /* rounded at q - 1 with the exponent unbounded: does it carry? */
            uint32_t all = 1u;
#pragma unroll
            for (i = 0; i < 7; i++) all &= N[i] == 0xFFFFFFFFu;
            all &= (N[7] & 0x1FFFu) == 0x1FFFu && (N[7] >> 13) == 0;
            carry_u = fx256_round_up(rnd, sign, g1, s1, N[0] & 1u) && all;
        }
        tiny = e_norm < FX256_EMIN - 1 || (e_norm == FX256_EMIN - 1 && !carry_u);
#pragma unroll
        for (i = 0; i < 8; i++) kept[i] = N[i];
        fx256_shr1_8(kept);
        if (g | s) {
            inexact = 1;
            if (fx256_round_up(rnd, sign, g, s, kept[0] & 1u)) {
                uint32_t c = 1;
#pragma unroll
                for (i = 0; i < 8; i++) { kept[i] += c; c = c && kept[i] == 0; }
            }
        }
    }
    if (inexact) fl |= CFT_SF_INEXACT;
#pragma unroll
    for (i = 0; i < 8; i++) out[i] = 0;
    kl = fx256_bitlen(kept, 8);
    if (kl == 0) {                        /* rounded past the smallest subnormal */
        out[7] = (uint32_t)sign << 31;
        *flags = fl | CFT_SF_UNDERFLOW;
        return;
    }
    e_res = q + kl - 1;
    if (e_res > FX256_EMAX) {
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
    if (e_res >= FX256_EMIN) {
        if (kl == FX256_P + 1) fx256_shr1_8(kept);           /* rounding carried out */
        kept[7] = (kept[7] & 0xFFFu) | ((uint32_t)(e_res + FX256_BIAS) << 12);
    }
#pragma unroll
    for (i = 0; i < 8; i++) out[i] = kept[i];
    out[7] |= (uint32_t)sign << 31;
    *flags = fl;
}

CFT_HD static void fx256_fma_lane(const uint8_t *pa, const uint8_t *pb, const uint8_t *pc,
                                 int rnd, uint8_t *pd, uint8_t *pflags)
{
    fx256_unp ua, ub, uc;
    uint32_t out[8], fl = 0;
    int i, bad = 0, done = 1;
    fx256_unpack(pa, &ua); fx256_unpack(pb, &ub); fx256_unpack(pc, &uc);
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
            fx256_round_pack(sp, P, ep, 0u, rnd, out, &fl, &bad);
        } else {
            uint32_t C[16];
#pragma unroll
            for (i = 0; i < 16; i++) C[i] = i < 8 ? uc.m[i] : 0u;
            const int Lp = fx256_bitlen(P, 16), Lc = fx256_bitlen(C, 8);
            const int pbig = ep + Lp - 1 >= uc.e + Lc - 1;
            const int Lx = pbig ? Lp : Lc, ex = pbig ? ep : uc.e, ey = pbig ? uc.e : ep;
            const int sx = pbig ? sp : uc.sign, sy = pbig ? uc.sign : sp;
#pragma unroll
            for (i = 0; i < 16; i++) { X[i] = pbig ? P[i] : C[i]; Y[i] = pbig ? C[i] : P[i]; }
            const int shx = 510 - Lx, E = ex - shx, off = ey - E;
            if (fx256_shl16(X, shx)) bad = 1;                   /* X's top bit at 509 */
            if (off >= 0) { if (fx256_shl16(Y, off)) bad = 1; }
            else fx256_shr16(Y, -off, &ys);
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
                fx256_round_pack(sign, N, E, ys, rnd, out, &fl, &bad);
        }
    }
#pragma unroll
    for (i = 0; i < 32; i++)
        pd[i] = bad ? 0 : (uint8_t)(out[i >> 2] >> (8 * (i & 3)));
    *pflags = bad ? 0x80 : (uint8_t)fl;
}

/* ADD, SUB and MUL as the one FMA with its operands steered: libcft's own
 * identities (softfloat.c's sf_steer, which rtl/cft_opmux.sv realises) on
 * the 32-byte encodings, in place on the lane's own copies of b and c.
 * ADD = FMA(a, 1, c); SUB = FMA(a, 1, -c), c's sign bit toggled whatever c
 * is; MUL = FMA(a, b, +-0), the zero's sign the XOR of a's and b's sign
 * bits; FMA as it is. Any other opcode returns 1 with nothing changed, as
 * sf_steer refuses it. A second implementation of the steering, held to
 * sf_steer by hip-fmadiff's diff --op streams and by fma256test. */
CFT_HD static inline int fx256_steer(int op, const uint8_t *pa, uint8_t *pb, uint8_t *pc)
{
    int i;
    if (op == CFT_SF_FMA)
        return 0;
    if (op == CFT_SF_ADD || op == CFT_SF_SUB) {
#pragma unroll
        for (i = 0; i < 32; i++)
            pb[i] = 0;
        pb[29] = 0xF0u;                     /* +1: the biased exponent 262143 at */
        pb[30] = 0xFFu;                     /* bits 236 to 254, the sign and the */
        pb[31] = 0x3Fu;                     /* trailing significand clear */
        if (op == CFT_SF_SUB)
            pc[31] ^= 0x80u;
        return 0;
    }
    if (op == CFT_SF_MUL) {
        const uint8_t s = (uint8_t)((pa[31] ^ pb[31]) & 0x80u);
#pragma unroll
        for (i = 0; i < 32; i++)
            pc[i] = 0;
        pc[31] = s;
        return 0;
    }
    return 1;
}

/* The constants above are binary256's, typed in. This holds them to the
 * library's own descriptor (softfloat.c's table), so that a change there
 * cannot leave this header computing another format's numbers: 1 only if
 * every field they state is the descriptor's - the precision, the trailing
 * width, the exponent field's width (FX256_EXPF's 19 bits) and mask, the
 * bias, emax, emin and the 256-bit element the lane reads. The GPU
 * backend's open refuses its fixed tier by name where it is 0, and
 * fma256test checks it against cft_sf_formats[3]. */
CFT_HD static inline int fx256_matches(const cft_fmt_desc *f)
{
    return f->prec == FX256_P && f->man_w == FX256_MANW && f->exp_w == 19 &&
           f->width == 256 && f->bias == FX256_BIAS && f->emax == FX256_EMAX &&
           f->emin == FX256_EMIN && f->exp_mask == FX256_EXPF;
}

#endif /* CFT_FMA256_FIXED_H */
