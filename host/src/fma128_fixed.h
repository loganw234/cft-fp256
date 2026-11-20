/* Copyright 2026 Logan W.
 * SPDX-License-Identifier: Apache-2.0
 *
 * The GPU backend's fixed tier at binary128 (round 3's G3A2): the binary128
 * fused multiply-add on fixed-size limbs. A SECOND IMPLEMENTATION of the
 * contract softfloat.c's sf_fma defines - not libcft's arithmetic, and its
 * agreement with it is evidence by test, not a proof. Device-only in the
 * library: backend_hip.cpp includes it after softfloat.c and fma256_fixed.h,
 * and it needs softfloat.h's CFT_HD, CFT_SF_* and cft_fmt_desc before it
 * (it includes nothing), so it is in libcft only under HIP=1;
 * host/tools/hip_fmadiff.cpp includes it the same way, and
 * host/tests/fma128_test.c builds it on a host (make fma128test), the
 * arithmetic's own test against libcft's with no GPU.
 *
 * fma256_fixed.h's method at binary128's size. The lane is the one G3A's
 * scratch prototype of the construction measured (fma128_proto.hip, kept
 * in the parcel's records, not in the tree), token for token once its
 * names take the FX128_ and fx128_ prefixes; its layout and comments are
 * fma256_fixed.h's, so that the two headers differ only in the format's
 * constants, limb counts, window widths and shifters' bounds (G3A2's
 * ledger tables both comparisons). The two are separate texts, NOT one
 * header generalised, and neither is kept in sync with the other. After
 * the lane, fx128_steer and fx128_matches: fma256_fixed.h's two at 16
 * bytes.
 *
 * Every array has a fixed size and every index is a constant once the
 * loops unroll, so the values can stay in registers rather than local
 * memory. It is held bit for bit, results and flags, to cft_sf_compute by
 * hip-fmadiff's differential streams (--format fp128) on each GPU and
 * fma128test's on the CPU, to the golden model by the conformance, stream
 * and edge corpora at fp128 through hip-corpus, and through the API by
 * hip-test's fixed leg.
 *
 * The method (fma256_fixed.h's, at a 256-bit window). Unpacking and the
 * special cases are sf_fma's, in its order. The finite case puts the term
 * whose leading bit is higher with that bit at position 253 of a 256-bit
 * window (eight limbs; the inputs are four, the exact product at most 226
 * bits) and shifts the other into the window, folding what falls below it
 * into a sticky bit. The sum is then (N + eps) * 2^E, eps in [0, 1) and
 * nonzero exactly when sticky: the value sf_fma rounds. The rounding below
 * is sf_round_pack's, step for step, on (N, E, sticky), at p = 113 and
 * with tininess after rounding; the same value and sticky give the same
 * bits and flags.
 *
 * Where a sticky can arise (G3A2's own derivation). Let the lower term
 * lead g binades below the upper one, whose top is at bit 253: a term of L
 * bits then ends at bit 253 - g - (L - 1), and the window drops a bit only
 * if that is below 0. Two 113-bit significands make a product of 225 or
 * 226 bits, ending at 29 - g or 28 - g, so a product below c first loses a
 * bit at g = 30 (225 bits) or g = 29 (226); c, of 113 bits, ends at
 * 141 - g, so c below the product first does at g = 142. Whenever a
 * sticky is set the lower term is below 2^(254 - g), at most 2^225, so a
 * difference keeps bit 252 at least: N has 253 bits or more, far past the
 * p + 2 = 115 of sf_round_pack's precondition (more than p bits whenever
 * sticky), and a sum's carry stays below bit 255.
 */
#ifndef CFT_FMA128_FIXED_H
#define CFT_FMA128_FIXED_H

#define FX128_P     113
#define FX128_MANW  112
#define FX128_BIAS  16383
#define FX128_EMIN  (-16382)
#define FX128_EMAX  16383
#define FX128_EXPF  0x7FFFu

typedef struct {
    int kind, sign, signaling, e;   /* kind: 0 zero 1 sub 2 norm 3 inf 4 nan */
    uint32_t m[4];
} fx128_unp;

/* (hi:lo) >> s and the high word of (hi:lo) << s, s in 0..31 */
CFT_HD static inline uint32_t fx128_fr(uint32_t hi, uint32_t lo, int s)
{
    return (uint32_t)((((uint64_t)hi << 32) | lo) >> s);
}
CFT_HD static inline uint32_t fx128_fl(uint32_t hi, uint32_t lo, int s)
{
    return (uint32_t)(((((uint64_t)hi << 32) | lo) << s) >> 32);
}

CFT_HD static inline int fx128_clz32(uint32_t x)          /* x != 0 */
{
    int n = 0;
    if (!(x & 0xFFFF0000u)) { n += 16; x <<= 16; }
    if (!(x & 0xFF000000u)) { n += 8;  x <<= 8; }
    if (!(x & 0xF0000000u)) { n += 4;  x <<= 4; }
    if (!(x & 0xC0000000u)) { n += 2;  x <<= 2; }
    if (!(x & 0x80000000u)) n += 1;
    return n;
}

CFT_HD static inline int fx128_bitlen(const uint32_t *w, int nl)  /* 0 for zero */
{
    int i, top = -1;
    uint32_t v = 0;
#pragma unroll
    for (i = 0; i < 8; i++)
        if (i < nl && w[i]) { top = i; v = w[i]; }
    return top < 0 ? 0 : 32 * top + 32 - fx128_clz32(v);
}

/* w >>= s over 8 limbs, ORing what falls off into *sticky; any s >= 0. */
CFT_HD static inline void fx128_shr8(uint32_t *w, int s, uint32_t *sticky)
{
    int i, k, b;
    uint32_t any = 0;
    if (s >= 256) {
#pragma unroll
        for (i = 0; i < 8; i++) { any |= w[i]; w[i] = 0; }
        *sticky |= any;
        return;
    }
#pragma unroll
    for (k = 4; k >= 1; k >>= 1) {
        const int on = (s >> 5) & k;
        uint32_t drop = 0;
#pragma unroll
        for (i = 0; i < k; i++) drop |= w[i];
        *sticky |= on ? drop : 0u;
#pragma unroll
        for (i = 0; i < 8; i++) w[i] = on ? (i + k < 8 ? w[i + k] : 0u) : w[i];
    }
    b = s & 31;
    *sticky |= w[0] & (uint32_t)((1ull << b) - 1u);
#pragma unroll
    for (i = 0; i < 7; i++) w[i] = fx128_fr(w[i + 1], w[i], b);
    w[7] >>= b;
}

/* w <<= s over 8 limbs, s in 0..255; returns nonzero if a set bit fell off
 * the top, which the construction never allows (a refusal, not a result). */
CFT_HD static inline uint32_t fx128_shl8(uint32_t *w, int s)
{
    int i, k, b;
    uint32_t lost = 0;
#pragma unroll
    for (k = 4; k >= 1; k >>= 1) {
        const int on = (s >> 5) & k;
        uint32_t drop = 0;
#pragma unroll
        for (i = 8 - k; i < 8; i++) drop |= w[i];
        lost |= on ? drop : 0u;
#pragma unroll
        for (i = 7; i >= 0; i--) w[i] = on ? (i - k >= 0 ? w[i - k] : 0u) : w[i];
    }
    b = s & 31;
    lost |= fx128_fl(0u, w[7], b);                        /* the bits pushed out of the top */
#pragma unroll
    for (i = 7; i > 0; i--) w[i] = fx128_fl(w[i], w[i - 1], b);
    w[0] = fx128_fl(w[0], 0u, b);
    return lost;
}

CFT_HD static inline void fx128_shr1_4(uint32_t *w)
{
    int i;
#pragma unroll
    for (i = 0; i < 3; i++) w[i] = (w[i] >> 1) | (w[i + 1] << 31);
    w[3] >>= 1;
}

CFT_HD static inline void fx128_unpack(const uint8_t *p, fx128_unp *u)
{
    uint32_t w[4], ef, any;
    int i;
#pragma unroll
    for (i = 0; i < 4; i++)
        w[i] = (uint32_t)p[4 * i] | (uint32_t)p[4 * i + 1] << 8 |
               (uint32_t)p[4 * i + 2] << 16 | (uint32_t)p[4 * i + 3] << 24;
    u->sign = (int)(w[3] >> 31);
    ef = (w[3] >> 16) & FX128_EXPF;
    any = w[3] & 0xFFFFu;
#pragma unroll
    for (i = 0; i < 3; i++) any |= w[i];
#pragma unroll
    for (i = 0; i < 3; i++) u->m[i] = w[i];
    u->m[3] = w[3] & 0xFFFFu;
    u->signaling = 0;
    u->e = 0;
    if (ef == FX128_EXPF) {
        u->kind = any ? 4 : 3;
        u->signaling = any && !((w[3] >> 15) & 1u);
    } else if (ef == 0) {
        u->kind = any ? 1 : 0;
        u->e = FX128_EMIN - FX128_MANW;
    } else {
        u->kind = 2;
        u->m[3] |= 1u << 16;
        u->e = (int)ef - FX128_BIAS - FX128_MANW;
    }
}

CFT_HD static inline int fx128_round_up(int rnd, int sign, uint32_t g, uint32_t s, uint32_t lsb)
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
CFT_HD static void fx128_round_pack(int sign, uint32_t *N, int E, uint32_t sticky, int rnd,
                                uint32_t *out, uint32_t *flags, int *bad)
{
    const int L = fx128_bitlen(N, 8);
    const int e_norm = E + L - 1;
    const int q = (e_norm > FX128_EMIN ? e_norm : FX128_EMIN) - (FX128_P - 1);
    const int shift = q - E;
    uint32_t kept[4], g = 0, s = 0, g1 = 0, s1 = 0, fl = 0, st = sticky ? 1u : 0u, d = 0;
    int i, inexact = 0, tiny, carry_u = 0, kl, e_res;
    if (L == 0 || (sticky && L <= FX128_P)) { *bad = 1; return; }
    if (shift <= 0) {                     /* exact: no bit below the ulp */
        if (sticky || fx128_shl8(N, -shift)) { *bad = 1; return; }
#pragma unroll
        for (i = 4; i < 8; i++) if (N[i]) *bad = 1;
#pragma unroll
        for (i = 0; i < 4; i++) kept[i] = N[i];
        tiny = e_norm < FX128_EMIN;
    } else {
        if (shift >= 2) {                 /* two bits more than the ulp: */
            fx128_shr8(N, shift - 2, &st);   /* the guard at q-1 for tininess */
            g1 = N[0] & 1u; s1 = st;
            fx128_shr8(N, 1, &d);
            g = N[0] & 1u; s = g1 | s1;
        } else {
            g = N[0] & 1u; s = st;
        }
#pragma unroll
        for (i = 4; i < 8; i++) if (N[i]) *bad = 1;
        if (e_norm == FX128_EMIN - 1 && shift >= 2) {
            /* rounded at q - 1 with the exponent unbounded: does it carry? */
            uint32_t all = 1u;
#pragma unroll
            for (i = 0; i < 3; i++) all &= N[i] == 0xFFFFFFFFu;
            all &= (N[3] & 0x1FFFFu) == 0x1FFFFu && (N[3] >> 17) == 0;
            carry_u = fx128_round_up(rnd, sign, g1, s1, N[0] & 1u) && all;
        }
        tiny = e_norm < FX128_EMIN - 1 || (e_norm == FX128_EMIN - 1 && !carry_u);
#pragma unroll
        for (i = 0; i < 4; i++) kept[i] = N[i];
        fx128_shr1_4(kept);
        if (g | s) {
            inexact = 1;
            if (fx128_round_up(rnd, sign, g, s, kept[0] & 1u)) {
                uint32_t c = 1;
#pragma unroll
                for (i = 0; i < 4; i++) { kept[i] += c; c = c && kept[i] == 0; }
            }
        }
    }
    if (inexact) fl |= CFT_SF_INEXACT;
#pragma unroll
    for (i = 0; i < 4; i++) out[i] = 0;
    kl = fx128_bitlen(kept, 4);
    if (kl == 0) {                        /* rounded past the smallest subnormal */
        out[3] = (uint32_t)sign << 31;
        *flags = fl | CFT_SF_UNDERFLOW;
        return;
    }
    e_res = q + kl - 1;
    if (e_res > FX128_EMAX) {
        const int inf = rnd == CFT_SF_RTZ ? 0 : rnd == CFT_SF_RDN ? sign :
                        rnd == CFT_SF_RUP ? !sign : 1;
        if (inf) {
            out[3] = 0x7FFF0000u;
        } else {
#pragma unroll
            for (i = 0; i < 3; i++) out[i] = 0xFFFFFFFFu;
            out[3] = (0x7FFEu << 16) | 0xFFFFu;
        }
        out[3] |= (uint32_t)sign << 31;
        *flags = fl | CFT_SF_OVERFLOW | CFT_SF_INEXACT;
        return;
    }
    if (tiny && inexact) fl |= CFT_SF_UNDERFLOW;
    if (e_res >= FX128_EMIN) {
        if (kl == FX128_P + 1) fx128_shr1_4(kept);           /* rounding carried out */
        kept[3] = (kept[3] & 0xFFFFu) | ((uint32_t)(e_res + FX128_BIAS) << 16);
    }
#pragma unroll
    for (i = 0; i < 4; i++) out[i] = kept[i];
    out[3] |= (uint32_t)sign << 31;
    *flags = fl;
}

CFT_HD static void fx128_fma_lane(const uint8_t *pa, const uint8_t *pb, const uint8_t *pc,
                                 int rnd, uint8_t *pd, uint8_t *pflags)
{
    fx128_unp ua, ub, uc;
    uint32_t out[4], fl = 0;
    int i, bad = 0, done = 1;
    fx128_unpack(pa, &ua); fx128_unpack(pb, &ub); fx128_unpack(pc, &uc);
#pragma unroll
    for (i = 0; i < 4; i++) out[i] = 0;
    const int sp = ua.sign ^ ub.sign;
    if (ua.kind == 4 || ub.kind == 4 || uc.kind == 4) {
        out[3] = 0x7FFF8000u;                               /* the canonical qNaN */
        fl = (ua.signaling || ub.signaling || uc.signaling) ? CFT_SF_INVALID : 0u;
    } else if (ua.kind == 3 || ub.kind == 3) {
        if (ua.kind == 0 || ub.kind == 0 || (uc.kind == 3 && uc.sign != sp)) {
            out[3] = 0x7FFF8000u;
            fl = CFT_SF_INVALID;
        } else {
            out[3] = 0x7FFF0000u | (uint32_t)sp << 31;
        }
    } else if (uc.kind == 3) {
        out[3] = 0x7FFF0000u | (uint32_t)uc.sign << 31;
    } else if (ua.kind == 0 || ub.kind == 0) {
        if (uc.kind == 0) {
            out[3] = (uint32_t)(uc.sign == sp ? uc.sign : rnd == CFT_SF_RDN) << 31;
        } else {                                            /* 0*b + c is c, exactly */
#pragma unroll
            for (i = 0; i < 4; i++)
                out[i] = (uint32_t)pc[4 * i] | (uint32_t)pc[4 * i + 1] << 8 |
                         (uint32_t)pc[4 * i + 2] << 16 | (uint32_t)pc[4 * i + 3] << 24;
        }
    } else {
        done = 0;
    }
    if (!done) {
        uint32_t P[8], X[8], Y[8], N[8], ys = 0;
        int j, ep = ua.e + ub.e;
#pragma unroll
        for (i = 0; i < 8; i++) P[i] = 0;
#pragma unroll
        for (i = 0; i < 4; i++) {                           /* the exact product */
            uint64_t carry = 0;
#pragma unroll
            for (j = 0; j < 4; j++) {
                uint64_t t = (uint64_t)ua.m[i] * ub.m[j] + P[i + j] + carry;
                P[i + j] = (uint32_t)t;
                carry = t >> 32;
            }
            P[i + 4] = (uint32_t)carry;
        }
        if (uc.kind == 0) {
            fx128_round_pack(sp, P, ep, 0u, rnd, out, &fl, &bad);
        } else {
            uint32_t C[8];
#pragma unroll
            for (i = 0; i < 8; i++) C[i] = i < 4 ? uc.m[i] : 0u;
            const int Lp = fx128_bitlen(P, 8), Lc = fx128_bitlen(C, 4);
            const int pbig = ep + Lp - 1 >= uc.e + Lc - 1;
            const int Lx = pbig ? Lp : Lc, ex = pbig ? ep : uc.e, ey = pbig ? uc.e : ep;
            const int sx = pbig ? sp : uc.sign, sy = pbig ? uc.sign : sp;
#pragma unroll
            for (i = 0; i < 8; i++) { X[i] = pbig ? P[i] : C[i]; Y[i] = pbig ? C[i] : P[i]; }
            const int shx = 254 - Lx, E = ex - shx, off = ey - E;
            if (fx128_shl8(X, shx)) bad = 1;                    /* X's top bit at 253 */
            if (off >= 0) { if (fx128_shl8(Y, off)) bad = 1; }
            else fx128_shr8(Y, -off, &ys);
            int sign = sx, cmp = 0;
            uint64_t br = 0;
            if (sx == sy) {
                uint64_t c = 0;
#pragma unroll
                for (i = 0; i < 8; i++) { c += (uint64_t)X[i] + Y[i]; N[i] = (uint32_t)c; c >>= 32; }
            } else {
                if (!ys) {
#pragma unroll
                    for (i = 0; i < 8; i++)
                        if (X[i] != Y[i]) cmp = X[i] > Y[i] ? 1 : -1;  /* highest differing wins */
                }
                if (!ys && cmp == 0) {
                    out[3] = (uint32_t)(rnd == CFT_SF_RDN) << 31;   /* exact cancellation */
                    done = 1;
                } else {
                    const int swap = cmp < 0;
                    sign = swap ? sy : sx;
#pragma unroll
                    for (i = 0; i < 8; i++) {
                        const uint64_t a = swap ? Y[i] : X[i], b = swap ? X[i] : Y[i];
                        const uint64_t t = a - b - br - (i == 0 && ys ? 1u : 0u);
                        N[i] = (uint32_t)t;
                        br = (t >> 63) & 1u;
                    }
                }
            }
            if (!done)
                fx128_round_pack(sign, N, E, ys, rnd, out, &fl, &bad);
        }
    }
#pragma unroll
    for (i = 0; i < 16; i++)
        pd[i] = bad ? 0 : (uint8_t)(out[i >> 2] >> (8 * (i & 3)));
    *pflags = bad ? 0x80 : (uint8_t)fl;
}

/* ADD, SUB and MUL as the one FMA with its operands steered: libcft's own
 * identities (softfloat.c's sf_steer, which rtl/cft_opmux.sv realises) on
 * the 16-byte encodings, in place on the lane's own copies of b and c.
 * ADD = FMA(a, 1, c); SUB = FMA(a, 1, -c), c's sign bit toggled whatever c
 * is; MUL = FMA(a, b, +-0), the zero's sign the XOR of a's and b's sign
 * bits; FMA as it is. Any other opcode returns 1 with nothing changed, as
 * sf_steer refuses it. A second implementation of the steering, held to
 * sf_steer by hip-fmadiff's diff --op streams and by fma128test. */
CFT_HD static inline int fx128_steer(int op, const uint8_t *pa, uint8_t *pb, uint8_t *pc)
{
    int i;
    if (op == CFT_SF_FMA)
        return 0;
    if (op == CFT_SF_ADD || op == CFT_SF_SUB) {
#pragma unroll
        for (i = 0; i < 16; i++)
            pb[i] = 0;
        pb[14] = 0xFFu;                     /* +1: the biased exponent 16383 at bits */
        pb[15] = 0x3Fu;                     /* 112 to 126, the sign and the trailing
                                             * significand clear */
        if (op == CFT_SF_SUB)
            pc[15] ^= 0x80u;
        return 0;
    }
    if (op == CFT_SF_MUL) {
        const uint8_t s = (uint8_t)((pa[15] ^ pb[15]) & 0x80u);
#pragma unroll
        for (i = 0; i < 16; i++)
            pc[i] = 0;
        pc[15] = s;
        return 0;
    }
    return 1;
}

/* The constants above are binary128's, typed in. This holds them to the
 * library's own descriptor (softfloat.c's table), so that a change there
 * cannot leave this header computing another format's numbers: 1 only if
 * every field they state is the descriptor's - the precision, the trailing
 * width, the exponent field's width (FX128_EXPF's 15 bits) and mask, the
 * bias, emax, emin and the 128-bit element the lane reads. The GPU
 * backend's open refuses its fixed tier by name where it is 0, and
 * fma128test checks it against cft_sf_formats[2]. */
CFT_HD static inline int fx128_matches(const cft_fmt_desc *f)
{
    return f->prec == FX128_P && f->man_w == FX128_MANW && f->exp_w == 15 &&
           f->width == 128 && f->bias == FX128_BIAS && f->emax == FX128_EMAX &&
           f->emin == FX128_EMIN && f->exp_mask == FX128_EXPF;
}

#endif /* CFT_FMA128_FIXED_H */
