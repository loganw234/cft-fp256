/* Copyright 2026 Logan W.
 * SPDX-License-Identifier: Apache-2.0
 *
 * cft-asm - the assembler and disassembler for `.cfta`, the orbit
 * sequencer's text form (docs/PROGRAMS.md).
 *
 *   cft-asm kernel.cfta -o kernel.cftp    assemble
 *   cft-asm -d kernel.cftp                disassemble to stdout
 *   cft-asm -i kernel.cftp                the header, and the SHA-256
 *
 * python/cft_golden/asm.py is the reference; THIS FILE IS HELD TO IT
 * BYTE FOR BYTE, on every source in programs/ and on a disassemble /
 * re-assemble round trip of the images seqprogs.py generates. That
 * equality is a check in `make programs-check`, and it is the reason
 * the two implementations exist: an encoding one program produces and
 * one program consumes is a format nobody has read.
 *
 * ---------------------------------------------------------------
 * What it needs from libcft, and what it deliberately does not
 * ---------------------------------------------------------------
 *
 * It links libcft for three things and no more:
 *
 *   cft_op_name         the mnemonics. NOT retyped here: this file
 *                       carries only which operand FIELDS each opcode
 *                       reads, which no table in either language
 *                       carries, and takes every name from the shared
 *                       one. A name typed twice is a name that drifts.
 *   cft_format_name     the four rungs and their sizes, likewise.
 *   cft_from_decimal_char   a decimal literal correctly rounded into
 *                       the format - the same routine, and the same
 *                       rounding, python/cft_golden/chars.py performs.
 *
 * It does NOT use cft_program_load. An assembler that could only
 * produce images the LOADER IN THIS TREE already accepts could not
 * write a revision-2 program until every backend had caught up, and
 * the whole point of the round is that a program is a file. So the
 * refusals below are the loader's rules, implemented here, and the
 * cross-check against asm.py is what keeps them honest.
 *
 * The encoding is docs/SEQUENCER.md's, INCLUDING its "Revision 2
 * (2026-09-08)" section: five-bit register fields whose high bits live
 * in imm[27:24], and a header whose word 6 is `flags` with BANK_EXT at
 * bit 0.
 */

#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include <ctype.h>

#include "cft.h"

#define MAX_ESZ        32
#define MAX_CONSTS     256
#define MAX_INSNS      65536
#define MAX_NAMES      1024
#define MAX_LINE       1024
#define NREG           32
#define REG_FIELD      16
#define KADDR_PLAIN    16
#define KADDR_KX       256
#define MAX_LOOP_DEPTH 4
#define HEADER_BYTES   32
#define FLAG_BANK_EXT  0x1u
/* 2^40: a program's worst-case instruction count must be a bound and
 * not merely finite. Written as a shift, so nobody has to count the
 * zeros in a literal. */
#define MAX_WORST      ((uint64_t)1 << 40)
#define MAX_DEPOSITS   ((uint32_t)1 << 20)

enum { C_HALT = 0, C_REPEAT, C_ENDREP, C_DEPOSIT, C_SETACT, C_ACTALL };
static const char *const CTRL_NAMES[6] = {
    "halt", "repeat", "endrep", "deposit", "setact", "actall"
};

/* Which operand fields each opcode reads, as a 3-character string over
 * 'a', 'b', 'c'. This follows softfloat.steer and the arity of the
 * simple ops, and it is the ONE thing this file states that libcft's
 * tables do not:
 *
 *   FMA    d = a*b + c     abc      ADD  d = a + c    ac
 *   MUL    d = a * b       ab       SUB  d = a - c    ac
 *   SELECT d = c ? a : b   abc
 *
 * and everything else is binary on (a, b) or unary on (a). cft.h says
 * the same thing in prose beside each enumerator ("b ignored").
 *
 * 24, 25, 28 and 29 are absent on purpose: cft_op_name calls them
 * sum, dot, sumsq and sumabs, they are REDUCTIONS that cft_reduce
 * issues, and the sequencer's ALU does not implement them. They stay
 * reachable through the numeric `opNN` escape so that an image
 * carrying one still disassembles into something that re-assembles.
 */
typedef struct { int op; const char *fields; } opdef;
static const opdef OPS[] = {
    { CFT_FMA,        "abc" },
    { CFT_ADD,        "ac"  },
    { CFT_SUB,        "ac"  },
    { CFT_MUL,        "ab"  },
    { CFT_ABS,        "a"   },
    { CFT_NEG,        "a"   },
    { CFT_COPYSIGN,   "ab"  },
    { CFT_MIN,        "ab"  },
    { CFT_MAX,        "ab"  },
    { CFT_MINNUM,     "ab"  },
    { CFT_MAXNUM,     "ab"  },
    { CFT_SELECT,     "abc" },
    { CFT_CMPLT,      "ab"  },
    { CFT_CMPLE,      "ab"  },
    { CFT_CMPEQ,      "ab"  },
    { CFT_IAND,       "ab"  },
    { CFT_IOR,        "ab"  },
    { CFT_IXOR,       "ab"  },
    { CFT_IADD,       "ab"  },
    { CFT_ISUB,       "ab"  },
    { CFT_ISHL,       "ab"  },
    { CFT_ISHR,       "ab"  },
    { CFT_ICMPLT,     "ab"  },
    { CFT_RECIP_SEED, "a"   },
    { CFT_RSQRT_SEED, "a"   },
    { CFT_IMUL,       "ab"  }
};
#define N_OPS ((int)(sizeof OPS / sizeof OPS[0]))

static const char *const RND_NAMES[5] = { "rne", "rtz", "rdn", "rup", "rmm" };

/* ---- failure ------------------------------------------------------- */

static const char *SRC = "<input>";
static int LINENO = 0;

static void die(const char *what)
{
    fprintf(stderr, "cft-asm: %s\n", what);
    exit(1);
}

static void diel(const char *fmt, ...)
{
    va_list ap;
    if (LINENO)
        fprintf(stderr, "%s:%d: ", SRC, LINENO);
    else
        fprintf(stderr, "%s: ", SRC);
    va_start(ap, fmt);
    vfprintf(stderr, fmt, ap);
    va_end(ap);
    fputc('\n', stderr);
    exit(1);
}

static void *xcalloc(size_t n, size_t sz)
{
    void *p = calloc(n ? n : 1, sz ? sz : 1);
    if (!p)
        die("out of memory");
    return p;
}

/* ---- SHA-256 -------------------------------------------------------
 *
 * The constants are DERIVED, not transcribed: K[i] is the fractional
 * part of the cube root of the i-th prime and H0[i] the square root of
 * the same, exactly as FIPS 180-4 defines them. Sixty-four hand-typed
 * hexadecimal words is sixty-four chances to be wrong in a way no test
 * here would localise, and the workload tools derive them for the same
 * reason. */
typedef struct {
    uint32_t h[8];
    uint64_t bits;
    uint8_t  buf[64];
    size_t   have;
} sha256;

static uint32_t SHA_K[64];
static uint32_t SHA_H0[8];
static int      sha_ready = 0;

static void first_primes(uint32_t *out, int n)
{
    int found = 0;
    uint32_t v;
    for (v = 2; found < n; v++) {
        uint32_t d;
        int prime = 1;
        for (d = 2; d * d <= v; d++)
            if (v % d == 0) { prime = 0; break; }
        if (prime)
            out[found++] = v;
    }
}

/* An exact 128-bit unsigned, so that the roots below are integer work
 * with no floating point anywhere near them - the same shape
 * host/tools/collatz.c uses for the same constants. */
typedef struct { uint64_t hi, lo; } u128;

static u128 u128_mk(uint64_t hi, uint64_t lo)
{
    u128 r;
    r.hi = hi;
    r.lo = lo;
    return r;
}

static int u128_cmp(u128 a, u128 b)
{
    if (a.hi != b.hi)
        return a.hi < b.hi ? -1 : 1;
    if (a.lo != b.lo)
        return a.lo < b.lo ? -1 : 1;
    return 0;
}

static u128 u128_shl(u128 a, int s)          /* 0 <= s < 128 */
{
    u128 r;
    if (s == 0)
        return a;
    if (s >= 64) {
        r.hi = a.lo << (s - 64);
        r.lo = 0;
    } else {
        r.hi = (a.hi << s) | (a.lo >> (64 - s));
        r.lo = a.lo << s;
    }
    return r;
}

static u128 u128_mul64(uint64_t a, uint64_t b)     /* exact 64x64 -> 128 */
{
    uint64_t al = a & 0xffffffffu, ah = a >> 32;
    uint64_t bl = b & 0xffffffffu, bh = b >> 32;
    uint64_t ll = al * bl, lh = al * bh, hl = ah * bl, hh = ah * bh;
    uint64_t mid = (ll >> 32) + (lh & 0xffffffffu) + (hl & 0xffffffffu);
    u128 r;
    r.lo = (ll & 0xffffffffu) | (mid << 32);
    r.hi = hh + (lh >> 32) + (hl >> 32) + (mid >> 32);
    return r;
}

static int u128_mul_small(u128 a, uint64_t b, u128 *out)
{
    u128 lo = u128_mul64(a.lo, b);
    u128 hi = u128_mul64(a.hi, b);
    if (hi.hi != 0)
        return 1;
    lo.hi += hi.lo;
    if (lo.hi < hi.lo)
        return 1;
    *out = lo;
    return 0;
}

static int u128_pow(uint64_t v, int root, u128 *out)   /* 1 on overflow */
{
    u128 acc = u128_mk(0, v);
    int k;
    for (k = 1; k < root; k++)
        if (u128_mul_small(acc, v, &acc))
            return 1;
    *out = acc;
    return 0;
}

/* floor(frac(p^(1/root)) * 2^32), root 2 or 3: the low 32 bits of
 * floor((p << (32*root))^(1/root)), by binary search over an exact
 * 128-bit power. */
static uint32_t root_frac32(uint32_t p, int root)
{
    u128 target = u128_shl(u128_mk(0, p), 32 * root);
    uint64_t lo = 0, hi = 1;
    for (;;) {
        u128 acc;
        if (u128_pow(hi, root, &acc) || u128_cmp(acc, target) > 0)
            break;
        hi <<= 1;
    }
    while (hi - lo > 1) {
        uint64_t mid = lo + (hi - lo) / 2;
        u128 acc;
        if (u128_pow(mid, root, &acc) || u128_cmp(acc, target) > 0)
            hi = mid;
        else
            lo = mid;
    }
    return (uint32_t)(lo & 0xffffffffu);
}

static void sha_init_constants(void)
{
    uint32_t primes[64];
    int i;
    if (sha_ready)
        return;
    first_primes(primes, 64);
    for (i = 0; i < 64; i++)
        SHA_K[i] = root_frac32(primes[i], 3);
    for (i = 0; i < 8; i++)
        SHA_H0[i] = root_frac32(primes[i], 2);
    sha_ready = 1;
}

static uint32_t rotr32(uint32_t x, int n)
{
    return (x >> n) | (x << (32 - n));
}

static void sha256_block(sha256 *s, const uint8_t *p)
{
    uint32_t w[64], a, b, c, d, e, f, g, h;
    int i;
    for (i = 0; i < 16; i++)
        w[i] = ((uint32_t)p[4 * i] << 24) | ((uint32_t)p[4 * i + 1] << 16) |
               ((uint32_t)p[4 * i + 2] << 8) | (uint32_t)p[4 * i + 3];
    for (i = 16; i < 64; i++) {
        uint32_t s0 = rotr32(w[i - 15], 7) ^ rotr32(w[i - 15], 18) ^
                      (w[i - 15] >> 3);
        uint32_t s1 = rotr32(w[i - 2], 17) ^ rotr32(w[i - 2], 19) ^
                      (w[i - 2] >> 10);
        w[i] = w[i - 16] + s0 + w[i - 7] + s1;
    }
    a = s->h[0]; b = s->h[1]; c = s->h[2]; d = s->h[3];
    e = s->h[4]; f = s->h[5]; g = s->h[6]; h = s->h[7];
    for (i = 0; i < 64; i++) {
        uint32_t S1 = rotr32(e, 6) ^ rotr32(e, 11) ^ rotr32(e, 25);
        uint32_t ch = (e & f) ^ (~e & g);
        uint32_t t1 = h + S1 + ch + SHA_K[i] + w[i];
        uint32_t S0 = rotr32(a, 2) ^ rotr32(a, 13) ^ rotr32(a, 22);
        uint32_t maj = (a & b) ^ (a & c) ^ (b & c);
        uint32_t t2 = S0 + maj;
        h = g; g = f; f = e; e = d + t1;
        d = c; c = b; b = a; a = t1 + t2;
    }
    s->h[0] += a; s->h[1] += b; s->h[2] += c; s->h[3] += d;
    s->h[4] += e; s->h[5] += f; s->h[6] += g; s->h[7] += h;
}

static void sha256_start(sha256 *s)
{
    sha_init_constants();
    memcpy(s->h, SHA_H0, sizeof s->h);
    s->bits = 0;
    s->have = 0;
}

static void sha256_push(sha256 *s, const void *data, size_t n)
{
    const uint8_t *p = (const uint8_t *)data;
    s->bits += (uint64_t)n * 8u;
    while (n) {
        size_t take = 64 - s->have;
        if (take > n)
            take = n;
        memcpy(s->buf + s->have, p, take);
        s->have += take;
        p += take;
        n -= take;
        if (s->have == 64) {
            sha256_block(s, s->buf);
            s->have = 0;
        }
    }
}

static void sha256_end(sha256 *s, uint8_t out[32])
{
    uint64_t bits = s->bits;
    int i;
    s->buf[s->have++] = 0x80;
    if (s->have > 56) {
        while (s->have < 64)
            s->buf[s->have++] = 0;
        sha256_block(s, s->buf);
        s->have = 0;
    }
    while (s->have < 56)
        s->buf[s->have++] = 0;
    for (i = 7; i >= 0; i--)
        s->buf[s->have++] = (uint8_t)(bits >> (8 * i));
    sha256_block(s, s->buf);
    for (i = 0; i < 8; i++) {
        out[4 * i]     = (uint8_t)(s->h[i] >> 24);
        out[4 * i + 1] = (uint8_t)(s->h[i] >> 16);
        out[4 * i + 2] = (uint8_t)(s->h[i] >> 8);
        out[4 * i + 3] = (uint8_t)s->h[i];
    }
}

static void hex32(const uint8_t in[32], char out[65])
{
    static const char D[] = "0123456789abcdef";
    int i;
    for (i = 0; i < 32; i++) {
        out[2 * i]     = D[in[i] >> 4];
        out[2 * i + 1] = D[in[i] & 15];
    }
    out[64] = 0;
}

/* ---- little-endian helpers ----------------------------------------- */

static void put_le32(uint8_t *p, uint32_t v)
{
    p[0] = (uint8_t)v; p[1] = (uint8_t)(v >> 8);
    p[2] = (uint8_t)(v >> 16); p[3] = (uint8_t)(v >> 24);
}

static uint32_t get_le32(const uint8_t *p)
{
    return (uint32_t)p[0] | ((uint32_t)p[1] << 8) |
           ((uint32_t)p[2] << 16) | ((uint32_t)p[3] << 24);
}

static void put_le64(uint8_t *p, uint64_t v)
{
    put_le32(p, (uint32_t)v);
    put_le32(p + 4, (uint32_t)(v >> 32));
}

static uint64_t get_le64(const uint8_t *p)
{
    return (uint64_t)get_le32(p) | ((uint64_t)get_le32(p + 4) << 32);
}

/* ---- the instruction encoding, revision 2 --------------------------- */

/* imm[24..27] carry the fifth bit of rd, ra, rb and rc, in that order. */
static int rhi_shift(int field)      /* 0=rd 1=ra 2=rb 3=rc */
{
    return 24 + field;
}

static const int FIELD_SHIFT[4] = { 8, 12, 16, 20 };
static const int KX_SHIFT[3]    = { 0, 8, 16 };

/* One ALU or control word. `reg[4]` is rd, ra, rb, rc as FIVE-BIT
 * values - or, where the matching k flag is set, a constant index.
 * `kflag[3]` is ka, kb, kc. */
static uint64_t encode(int op, const int reg[4], const int kflag[3],
                       int rnd, int kx, int ctrl, uint32_t imm)
{
    uint64_t word;
    int i;
    if (op < 0 || op > 255)
        diel("op %d does not fit the opcode byte", op);
    if (rnd < 0 || rnd > 4)
        diel("rnd %d; the contract defines 0..4", rnd);
    word = (uint64_t)(uint32_t)op | ((uint64_t)(uint32_t)rnd << 24) |
           ((uint64_t)(kflag[0] ? 1u : 0u) << 27) |
           ((uint64_t)(kflag[1] ? 1u : 0u) << 28) |
           ((uint64_t)(kflag[2] ? 1u : 0u) << 29) |
           ((uint64_t)(kx ? 1u : 0u) << 30) |
           ((uint64_t)(ctrl ? 1u : 0u) << 31);
    for (i = 0; i < 4; i++) {
        int is_k = (i > 0) && kflag[i - 1];
        int v = reg[i];
        int limit = is_k ? (kx ? KADDR_KX : KADDR_PLAIN) : NREG;
        if (v < 0 || v >= limit)
            diel("operand %d outside 0..%d", v, limit - 1);
        if (is_k && kx)
            continue;                       /* the index rides in imm */
        word |= (uint64_t)(uint32_t)(v & 0xF) << FIELD_SHIFT[i];
        if (v >> 4) {
            if (is_k)
                diel("constant index %d needs the indexed form", v);
            imm |= 1u << rhi_shift(i);
        }
    }
    return word | ((uint64_t)imm << 32);
}

typedef struct {
    int      op, rnd, ctrl, kx;
    int      reg[4];        /* five-bit values */
    int      lo[4];         /* the raw four-bit fields */
    int      hi[4];         /* the imm high bits */
    int      kflag[3];
    uint32_t imm;
} insn;

static void decode(uint64_t word, insn *d)
{
    int i;
    d->op   = (int)(word & 0xFF);
    d->rnd  = (int)((word >> 24) & 0x7);
    d->kflag[0] = (int)((word >> 27) & 1);
    d->kflag[1] = (int)((word >> 28) & 1);
    d->kflag[2] = (int)((word >> 29) & 1);
    d->kx   = (int)((word >> 30) & 1);
    d->ctrl = (int)((word >> 31) & 1);
    d->imm  = (uint32_t)(word >> 32);
    for (i = 0; i < 4; i++) {
        d->lo[i] = (int)((word >> FIELD_SHIFT[i]) & 0xF);
        d->hi[i] = (int)((d->imm >> rhi_shift(i)) & 1);
        d->reg[i] = d->lo[i] | (d->hi[i] << 4);
    }
}

/* The source index of operand `k` (0=a,1=b,2=c), or -1 when it names a
 * register. */
static int const_index(const insn *d, int k)
{
    if (!d->kflag[k])
        return -1;
    return d->kx ? (int)((d->imm >> KX_SHIFT[k]) & 0xFF) : d->lo[k + 1];
}

/* ---- the program under construction --------------------------------- */

typedef struct {
    cft_format fmt;
    int        have_fmt;
    uint32_t   max_deposits;
    int        have_deposits;
    uint32_t   flags;
    size_t     esz;

    int      n_consts;
    uint8_t  consts[MAX_CONSTS][MAX_ESZ];
    char     const_name[MAX_CONSTS][64];

    int      n_regs;
    char     reg_name[MAX_NAMES][64];
    int      reg_value[MAX_NAMES];

    uint32_t n_insns;
    uint64_t insns[MAX_INSNS];
} program;

static cft_device *DEV = NULL;

static void lower(char *s)
{
    for (; *s; s++)
        *s = (char)tolower((unsigned char)*s);
}

static int streq_ci(const char *a, const char *b)
{
    for (; *a && *b; a++, b++)
        if (tolower((unsigned char)*a) != tolower((unsigned char)*b))
            return 0;
    return *a == *b;
}

static int is_ident(const char *s)
{
    if (!(isalpha((unsigned char)s[0]) || s[0] == '_'))
        return 0;
    for (s++; *s; s++)
        if (!(isalnum((unsigned char)*s) || *s == '_'))
            return 0;
    return 1;
}

/* `rN` -> N, or -1. */
static int reg_literal(const char *s)
{
    long v;
    char *end;
    if (!(s[0] == 'r' || s[0] == 'R') || !isdigit((unsigned char)s[1]))
        return -1;
    v = strtol(s + 1, &end, 10);
    if (*end || v < 0 || v > 100000)
        return -1;
    return (int)v;
}

static int find_const(const program *P, const char *name)
{
    int i;
    for (i = 0; i < P->n_consts; i++)
        if (streq_ci(P->const_name[i], name))
            return i;
    return -1;
}

static int find_reg_name(const program *P, const char *name)
{
    int i;
    for (i = 0; i < P->n_regs; i++)
        if (streq_ci(P->reg_name[i], name))
            return i;
    return -1;
}

static int parse_reg(const program *P, const char *tok)
{
    int i = find_reg_name(P, tok);
    int n;
    if (i >= 0)
        return P->reg_value[i];
    n = reg_literal(tok);
    if (n < 0) {
        if (find_const(P, tok) >= 0)
            diel("%s is a constant, and this operand must be a register",
                 tok);
        diel("'%s' is not a register", tok);
    }
    if (n >= NREG)
        diel("r%d is outside r0..r%d", n, NREG - 1);
    return n;
}

static uint64_t parse_uint(const char *tok, const char *what)
{
    char *end;
    unsigned long long v;
    if (tok[0] == '0' && (tok[1] == 'x' || tok[1] == 'X'))
        v = strtoull(tok + 2, &end, 16);
    else
        v = strtoull(tok, &end, 10);
    if (*end || end == tok)
        diel("%s: '%s' is not a number", what, tok);
    return (uint64_t)v;
}

/* A `.const` literal into `out`, format-width, little-endian. */
static void parse_literal(program *P, const char *text, uint8_t *out)
{
    size_t esz = P->esz;
    memset(out, 0, MAX_ESZ);
    if (text[0] == '-' && (text[1] == '0') &&
        (text[2] == 'x' || text[2] == 'X'))
        diel("a raw 0x encoding carries its own sign bit; write the "
             "whole word");
    if (text[0] == '0' && (text[1] == 'x' || text[1] == 'X')) {
        const char *p = text + 2;
        size_t nd = strlen(p), i;
        if (!nd)
            diel("'%s' is not a hexadecimal encoding", text);
        if (nd > esz * 2) {
            /* leading zeros are fine; anything else is too wide */
            for (i = 0; i + esz * 2 < nd; i++)
                if (p[i] != '0')
                    diel("%s is wider than %s", text,
                         cft_format_name(P->fmt));
            p += nd - esz * 2;
            nd = esz * 2;
        }
        for (i = 0; i < nd; i++) {
            int c = (unsigned char)p[nd - 1 - i];
            int v;
            if (c >= '0' && c <= '9') v = c - '0';
            else if (c >= 'a' && c <= 'f') v = c - 'a' + 10;
            else if (c >= 'A' && c <= 'F') v = c - 'A' + 10;
            else diel("'%s' is not a hexadecimal encoding", text);
            out[i / 2] |= (uint8_t)(v << (4 * (i & 1)));
        }
        return;
    }
    {
        const char *in[1];
        uint32_t fl = 0;
        cft_status st;
        in[0] = text;
        st = cft_from_decimal_char(DEV, P->fmt, CFT_RNE, in, out, 1,
                                   NULL, &fl);
        if (st != CFT_OK)
            diel("'%s' is not a number %s can read", text,
                 cft_format_name(P->fmt));
    }
}

/* ---- the assembler --------------------------------------------------- */

static void emit(program *P, uint64_t word)
{
    if (P->n_insns >= MAX_INSNS)
        diel("more than %d instructions", MAX_INSNS);
    P->insns[P->n_insns++] = word;
}

static void need_fmt(const program *P)
{
    if (!P->have_fmt)
        diel(".format must come first");
}

static void do_ctrl(program *P, int code, char **tok, int ntok)
{
    int reg[4] = { 0, 0, 0, 0 };
    int kflag[3] = { 0, 0, 0 };
    uint32_t imm = 0;
    if (code == C_REPEAT) {
        uint64_t trip;
        if (ntok != 1)
            diel("repeat takes a trip count");
        trip = parse_uint(tok[0], "repeat");
        if (trip == 0)
            diel("repeat 0 is not a loop; omit it");
        if (trip >= ((uint64_t)1 << 32))
            diel("a trip count is a 32-bit immediate");
        imm = (uint32_t)trip;
    } else if (code == C_DEPOSIT || code == C_SETACT) {
        if (ntok != 1)
            diel("%s takes one register", CTRL_NAMES[code]);
        reg[1] = parse_reg(P, tok[0]);
    } else if (ntok) {
        diel("%s takes no operands", CTRL_NAMES[code]);
    }
    emit(P, encode(code, reg, kflag, 0, 0, 1, imm));
}

static void do_alu(program *P, const char *mnemonic, char **tok, int ntok)
{
    char name[64];
    const char *dot;
    int rnd = 0, force_kx = 0, op = -1, kx;
    const char *fields = "abc";
    int explicit_only = 0;
    int reg[4] = { 0, 0, 0, 0 };
    int kflag[3] = { 0, 0, 0 };
    uint32_t imm = 0;
    int i, nops, any_k = 0, need_kx = 0;
    char order[4];

    /* mnemonic, then dot-separated modifiers: a rounding name, or kx */
    dot = strchr(mnemonic, '.');
    if (dot) {
        size_t n = (size_t)(dot - mnemonic);
        if (n >= sizeof name)
            diel("'%s' is not an opcode this ISA has", mnemonic);
        memcpy(name, mnemonic, n);
        name[n] = 0;
        while (dot) {
            char mod[16];
            const char *next = strchr(dot + 1, '.');
            size_t mn = next ? (size_t)(next - dot - 1) : strlen(dot + 1);
            int matched = 0, r;
            if (mn >= sizeof mod)
                diel("'%s' is not rne, rtz, rdn, rup, rmm or kx", dot + 1);
            memcpy(mod, dot + 1, mn);
            mod[mn] = 0;
            if (!strcmp(mod, "kx")) {
                force_kx = 1;
                matched = 1;
            }
            for (r = 0; r < 5 && !matched; r++)
                if (!strcmp(mod, RND_NAMES[r])) { rnd = r; matched = 1; }
            if (!matched)
                diel("'%s' is not rne, rtz, rdn, rup, rmm or kx", mod);
            dot = next;
        }
    } else {
        if (strlen(mnemonic) >= sizeof name)
            diel("'%s' is not an opcode this ISA has", mnemonic);
        strcpy(name, mnemonic);
    }

    if ((name[0] == 'o' || name[0] == 'O') &&
        (name[1] == 'p' || name[1] == 'P') &&
        isdigit((unsigned char)name[2])) {
        uint64_t v = parse_uint(name + 2, "opcode");
        if (v > 255)
            diel("op%llu does not fit the opcode byte",
                 (unsigned long long)v);
        op = (int)v;
        explicit_only = 1;
        fields = "abc";
    } else {
        for (i = 0; i < N_OPS; i++)
            if (!strcmp(cft_op_name((cft_op)OPS[i].op), name)) {
                op = OPS[i].op;
                fields = OPS[i].fields;
                break;
            }
        if (op < 0)
            diel("'%s' is not an opcode this ISA has", name);
    }

    if (ntok < 1)
        diel("%s takes a destination", name);
    reg[0] = parse_reg(P, tok[0]);
    nops = ntok - 1;
    if (nops == 3) {
        strcpy(order, "abc");
    } else if (!explicit_only && nops == (int)strlen(fields)) {
        strcpy(order, fields);
    } else {
        diel("%s reads %d operand(s) (%s); write that many, or all three "
             "in ra, rb, rc order - %d given",
             name, (int)strlen(fields), fields, nops);
        return;
    }

    for (i = 0; i < nops; i++) {
        int slot = order[i] - 'a';          /* 0=a 1=b 2=c */
        const char *t = tok[1 + i];
        int k = find_const(P, t);
        if (k >= 0) {
            kflag[slot] = 1;
            reg[slot + 1] = k;
            any_k = 1;
            if (k >= KADDR_PLAIN)
                need_kx = 1;
        } else {
            reg[slot + 1] = parse_reg(P, t);
        }
    }
    kx = need_kx || force_kx;
    if (kx && !any_k)
        diel("`.kx` on an instruction whose operands are all registers "
             "selects nothing, and the loader refuses it - it is a second "
             "spelling of the plain form");
    if (kx) {
        for (i = 0; i < 3; i++)
            if (kflag[i])
                imm |= (uint32_t)reg[i + 1] << KX_SHIFT[i];
    }
    emit(P, encode(op, reg, kflag, rnd, kx, 0, imm));
}

static void assemble_line(program *P, char *line)
{
    char *tok[16];
    int ntok = 0;
    char *p = line, *semi = strchr(line, ';');
    if (semi)
        *semi = 0;
    while (*p && ntok < 16) {
        while (*p && (isspace((unsigned char)*p) || *p == ','))
            p++;
        if (!*p)
            break;
        tok[ntok++] = p;
        while (*p && !isspace((unsigned char)*p) && *p != ',')
            p++;
        if (*p)
            *p++ = 0;
    }
    if (!ntok)
        return;

    if (tok[0][0] == '.') {
        char d[32];
        size_t n = strlen(tok[0]);
        if (n >= sizeof d)
            diel("'%s' is not a directive", tok[0]);
        strcpy(d, tok[0]);
        lower(d);
        if (!strcmp(d, ".format")) {
            int f;
            if (P->have_fmt)
                diel(".format appears twice");
            if (P->n_insns || P->n_consts || P->have_deposits)
                diel(".format must come first");
            if (ntok != 2)
                diel(".format takes one name");
            for (f = 0; f < 4; f++)
                if (streq_ci(cft_format_name((cft_format)f), tok[1])) {
                    P->fmt = (cft_format)f;
                    P->have_fmt = 1;
                    P->esz = cft_format_size((cft_format)f);
                    break;
                }
            if (!P->have_fmt)
                diel("'%s' is not fp32, fp64, fp128 or fp256", tok[1]);
        } else if (!strcmp(d, ".deposits")) {
            if (ntok != 2)
                diel(".deposits takes one number");
            P->max_deposits = (uint32_t)parse_uint(tok[1], ".deposits");
            P->have_deposits = 1;
        } else if (!strcmp(d, ".bank")) {
            if (ntok != 2 || !streq_ci(tok[1], "external"))
                diel(".bank takes the word `external`");
            if (P->n_consts)
                diel(".bank external must precede the .const lines it "
                     "turns into declarations");
            P->flags |= FLAG_BANK_EXT;
        } else if (!strcmp(d, ".const")) {
            int bare = (ntok == 2) && (P->flags & FLAG_BANK_EXT);
            char joined[MAX_LINE];
            need_fmt(P);
            if (!bare && (ntok < 4 || strcmp(tok[2], "=")))
                diel(".const takes NAME = value%s",
                     (P->flags & FLAG_BANK_EXT)
                     ? ", or NAME alone under .bank external" : "");
            if (!is_ident(tok[1]))
                diel("'%s' is not a name", tok[1]);
            if (find_const(P, tok[1]) >= 0 || find_reg_name(P, tok[1]) >= 0)
                diel("%s is already defined", tok[1]);
            if (reg_literal(tok[1]) >= 0)
                diel("%s would shadow a register", tok[1]);
            if (P->n_consts >= MAX_CONSTS)
                diel("the bank addresses at most %d constants", MAX_CONSTS);
            if (strlen(tok[1]) >= sizeof P->const_name[0])
                diel("that name is too long");
            if (bare || (P->flags & FLAG_BANK_EXT)) {
                memset(P->consts[P->n_consts], 0, MAX_ESZ);
            } else {
                int i;
                size_t len = 0;
                joined[0] = 0;
                for (i = 3; i < ntok; i++) {
                    size_t l = strlen(tok[i]);
                    if (len + l + 2 >= sizeof joined)
                        diel("that literal is too long");
                    if (len)
                        joined[len++] = ' ';
                    memcpy(joined + len, tok[i], l);
                    len += l;
                    joined[len] = 0;
                }
                parse_literal(P, joined, P->consts[P->n_consts]);
            }
            strcpy(P->const_name[P->n_consts], tok[1]);
            P->n_consts++;
        } else if (!strcmp(d, ".reg")) {
            int rnum;
            if (ntok != 4 || strcmp(tok[2], "="))
                diel(".reg takes NAME = rN");
            if (!is_ident(tok[1]))
                diel("'%s' is not a name", tok[1]);
            if (find_const(P, tok[1]) >= 0 || find_reg_name(P, tok[1]) >= 0)
                diel("%s is already defined", tok[1]);
            if (reg_literal(tok[1]) >= 0)
                diel("%s would shadow a register", tok[1]);
            rnum = reg_literal(tok[3]);
            if (rnum < 0)
                diel("'%s' is not r0..r%d", tok[3], NREG - 1);
            if (rnum >= NREG)
                diel("r%d is outside r0..r%d", rnum, NREG - 1);
            if (P->n_regs >= MAX_NAMES)
                diel("too many register names");
            if (strlen(tok[1]) >= sizeof P->reg_name[0])
                diel("that name is too long");
            strcpy(P->reg_name[P->n_regs], tok[1]);
            P->reg_value[P->n_regs] = rnum;
            P->n_regs++;
        } else {
            diel("'%s' is not a directive", tok[0]);
        }
        return;
    }

    {
        int c;
        for (c = 0; c < 6; c++)
            if (streq_ci(tok[0], CTRL_NAMES[c])) {
                need_fmt(P);
                do_ctrl(P, c, tok + 1, ntok - 1);
                return;
            }
    }
    need_fmt(P);
    {
        char m[64];
        if (strlen(tok[0]) >= sizeof m)
            diel("'%s' is not an opcode this ISA has", tok[0]);
        strcpy(m, tok[0]);
        lower(m);
        do_alu(P, m, tok + 1, ntok - 1);
    }
}

/* ---- validation: every rule the loader applies ---------------------- */

static void check_alu(const program *P, uint32_t pc, const insn *d)
{
    int k;
    if (d->rnd > 4)
        diel("[%u] rnd=%d is reserved", pc, d->rnd);
    if (d->imm & 0xF0000000u)
        diel("[%u] imm[31:28] is reserved and must be zero", pc);
    if (d->kx && !(d->kflag[0] || d->kflag[1] || d->kflag[2]))
        diel("[%u] kx is set and no operand names a constant, so the bit "
             "selects nothing and the instruction has a second encoding "
             "with kx clear", pc);
    for (k = 0; k < 3; k++) {
        static const char *const KN[3] = { "ra", "rb", "rc" };
        uint32_t byte = (d->imm >> KX_SHIFT[k]) & 0xFFu;
        int idx;
        if (d->kflag[k]) {
            if (d->hi[k + 1])
                diel("[%u] %s names a constant, so its register high bit "
                     "imm[%d] is not read and must be zero",
                     pc, KN[k], rhi_shift(k + 1));
            if (d->kx) {
                if (d->lo[k + 1])
                    diel("[%u] %s names constant %u through imm under kx, "
                         "so the %s field must be zero and it is %d",
                         pc, KN[k], (unsigned)byte, KN[k], d->lo[k + 1]);
                idx = (int)byte;
            } else {
                idx = d->lo[k + 1];
            }
        } else {
            if (d->kx && byte)
                diel("[%u] %s names a register, so its byte of imm is not "
                     "read and must be zero", pc, KN[k]);
            continue;
        }
        if (idx >= P->n_consts)
            diel("[%u] %s names constant %d but the bank holds %d",
                 pc, KN[k], idx, P->n_consts);
    }
    if (!d->kx && (d->imm & 0x00FFFFFFu))
        diel("[%u] an ALU instruction without kx has no immediate below "
             "imm[24], so those bits must be zero - otherwise the same "
             "operation has many encodings and a readback hash stops "
             "being a hash of the program", pc);
}

static void check_ctrl(uint32_t pc, const insn *d)
{
    static const char *const FN[4] = { "rd", "ra", "rb", "rc" };
    int code = d->op, i;
    int reads_ra = (code == C_DEPOSIT || code == C_SETACT);
    uint32_t allowed_imm;
    if (code > C_ACTALL)
        diel("[%u] unknown control code %d", pc, code);
    /* the raw four-bit fields: imm[27:24] are register HIGH bits only
     * on an instruction that has a register to extend, and REPEAT's
     * immediate is a trip count that may set any bit it likes */
    for (i = 0; i < 4; i++) {
        if (i == 1 && reads_ra)
            continue;
        if (d->lo[i])
            diel("[%u] %s does not read %s, so it must be zero",
                 pc, CTRL_NAMES[code], FN[i]);
    }
    if (d->rnd)
        diel("[%u] %s does not read rnd, so it must be zero",
             pc, CTRL_NAMES[code]);
    for (i = 0; i < 3; i++)
        if (d->kflag[i])
            diel("[%u] %s does not read k%c, so it must be zero",
                 pc, CTRL_NAMES[code], 'a' + i);
    if (d->kx)
        diel("[%u] %s does not read kx, so it must be zero",
             pc, CTRL_NAMES[code]);
    allowed_imm = reads_ra ? (1u << rhi_shift(1)) : 0u;
    if (code != C_REPEAT && (d->imm & ~allowed_imm))
        diel("[%u] %s does not read imm beyond its register high bit, so "
             "imm[31:0] must be zero there and it is 0x%08x",
             pc, CTRL_NAMES[code], (unsigned)d->imm);
}

static void validate(const program *P)
{
    uint64_t mult[MAX_LOOP_DEPTH + 1], worst = 0;
    int depth = 0;
    uint32_t pc;
    if (!P->have_fmt)
        diel(".format is required");
    if (!P->have_deposits)
        diel(".deposits is required");
    if (P->max_deposits > MAX_DEPOSITS)
        diel("max_deposits=%u, cap %u", (unsigned)P->max_deposits,
             (unsigned)MAX_DEPOSITS);
    if (P->flags & ~FLAG_BANK_EXT)
        diel("header flags 0x%08x: only BANK_EXT is defined and the rest "
             "are reserved-must-be-zero", (unsigned)P->flags);
    mult[0] = 1;
    for (pc = 0; pc < P->n_insns; pc++) {
        insn d;
        decode(P->insns[pc], &d);
        worst += mult[depth];
        if (!d.ctrl) {
            check_alu(P, pc, &d);
        } else {
            check_ctrl(pc, &d);
            if (d.op == C_REPEAT) {
                if (d.imm == 0)
                    diel("[%u] repeat 0 is not a loop; omit it", pc);
                depth++;
                if (depth > MAX_LOOP_DEPTH)
                    diel("[%u] loops nest deeper than %d", pc,
                         MAX_LOOP_DEPTH);
                if (mult[depth - 1] > MAX_WORST / d.imm)
                    mult[depth] = MAX_WORST + 1;
                else
                    mult[depth] = mult[depth - 1] * d.imm;
            } else if (d.op == C_ENDREP) {
                depth--;
                if (depth < 0)
                    diel("[%u] endrep without repeat", pc);
            } else if (d.op == C_ACTALL && depth > 0) {
                diel("[%u] actall inside a loop would make the "
                     "all-lanes-done early exit observable", pc);
            } else if (d.op == C_HALT && depth > 0) {
                diel("[%u] halt inside a loop: the active mask cannot gate "
                     "it, so the all-lanes-done early exit would be "
                     "observable", pc);
            }
        }
        if (worst > MAX_WORST)
            diel("[%u] worst-case instruction count exceeds %llu; the loop "
                 "bounds are finite but not a bound", pc,
                 (unsigned long long)MAX_WORST);
    }
    if (depth != 0)
        diel("%d loop(s) left open at the end", depth);
}

/* ---- image out ------------------------------------------------------ */

static uint8_t *to_bytes(const program *P, size_t *bytes_out)
{
    size_t carried = (P->flags & FLAG_BANK_EXT) ? 0 : (size_t)P->n_consts;
    size_t bytes = HEADER_BYTES + carried * P->esz +
                   (size_t)P->n_insns * 8;
    uint8_t *img = (uint8_t *)xcalloc(bytes, 1);
    size_t off, i;
    img[0] = 'C'; img[1] = 'F'; img[2] = 'T'; img[3] = 'P';
    put_le32(img + 4, 1);                          /* program version */
    put_le32(img + 8, P->n_insns);
    put_le32(img + 12, (uint32_t)P->n_consts);
    put_le32(img + 16, P->max_deposits);
    put_le32(img + 20, (uint32_t)P->fmt);
    put_le32(img + 24, P->flags);
    put_le32(img + 28, 0);
    off = HEADER_BYTES;
    for (i = 0; i < carried; i++) {
        memcpy(img + off, P->consts[i], P->esz);
        off += P->esz;
    }
    for (i = 0; i < P->n_insns; i++) {
        put_le64(img + off, P->insns[i]);
        off += 8;
    }
    *bytes_out = bytes;
    return img;
}

/* ---- image in -------------------------------------------------------- */

static uint8_t *read_file(const char *path, size_t *n_out)
{
    FILE *f = fopen(path, "rb");
    uint8_t *buf;
    size_t cap = 1 << 16, have = 0;
    if (!f) {
        fprintf(stderr, "cft-asm: cannot open %s\n", path);
        exit(1);
    }
    buf = (uint8_t *)xcalloc(cap, 1);
    for (;;) {
        size_t got;
        if (have == cap) {
            uint8_t *bigger = (uint8_t *)xcalloc(cap * 2, 1);
            memcpy(bigger, buf, have);
            free(buf);
            buf = bigger;
            cap *= 2;
        }
        got = fread(buf + have, 1, cap - have, f);
        have += got;
        if (got == 0)
            break;
    }
    fclose(f);
    *n_out = have;
    return buf;
}

static void load_image(const uint8_t *data, size_t n, program *P)
{
    uint32_t magic, ver, n_insns, n_consts, maxdep, prec, flags, rsv1;
    size_t off, want, carried, i;
    memset(P, 0, sizeof *P);
    if (n < HEADER_BYTES)
        diel("shorter than a header");
    magic   = get_le32(data);
    ver     = get_le32(data + 4);
    n_insns = get_le32(data + 8);
    n_consts= get_le32(data + 12);
    maxdep  = get_le32(data + 16);
    prec    = get_le32(data + 20);
    flags   = get_le32(data + 24);
    rsv1    = get_le32(data + 28);
    if (magic != 0x50544643u)
        diel("bad magic 0x%08x, expected 0x50544643", (unsigned)magic);
    if (ver != 1)
        diel("program version %u, this loader speaks 1", (unsigned)ver);
    if (rsv1)
        diel("reserved header word 7 must be zero");
    if (flags & ~FLAG_BANK_EXT)
        diel("header flags 0x%08x: only BANK_EXT is defined and the rest "
             "are reserved", (unsigned)flags);
    if (prec > 3)
        diel("precision code %u is not on the ladder", (unsigned)prec);
    if (n_consts > MAX_CONSTS)
        diel("%u constants; the bank addresses at most %d",
             (unsigned)n_consts, MAX_CONSTS);
    if (n_insns > MAX_INSNS)
        diel("%u instructions; this tool holds %d", (unsigned)n_insns,
             MAX_INSNS);
    P->fmt = (cft_format)prec;
    P->have_fmt = 1;
    P->esz = cft_format_size(P->fmt);
    P->max_deposits = maxdep;
    P->have_deposits = 1;
    P->flags = flags;
    P->n_consts = (int)n_consts;
    P->n_insns = n_insns;
    carried = (flags & FLAG_BANK_EXT) ? 0 : n_consts;
    want = HEADER_BYTES + carried * P->esz + (size_t)n_insns * 8;
    if (n != want)
        diel("%lu bytes, header describes %lu - a program is exactly its "
             "header, constants and instructions, so anything else is a "
             "different program",
             (unsigned long)n, (unsigned long)want);
    off = HEADER_BYTES;
    for (i = 0; i < carried; i++) {
        memcpy(P->consts[i], data + off, P->esz);
        off += P->esz;
    }
    for (i = 0; i < n_insns; i++) {
        P->insns[i] = get_le64(data + off);
        off += 8;
    }
}

/* ---- the disassembler ------------------------------------------------ */

static void print_operand(const insn *d, int k, char *out, size_t cap)
{
    int idx = const_index(d, k);
    if (idx >= 0)
        snprintf(out, cap, "k%d", idx);
    else
        snprintf(out, cap, "r%d", d->reg[k + 1]);
}

static void disassemble(const program *P, FILE *out)
{
    uint32_t pc;
    int indent = 0, i;
    fprintf(out, ".format   %s\n", cft_format_name(P->fmt));
    fprintf(out, ".deposits %u\n", (unsigned)P->max_deposits);
    if (P->flags & FLAG_BANK_EXT)
        fprintf(out, ".bank     external\n");
    for (i = 0; i < P->n_consts; i++) {
        if (P->flags & FLAG_BANK_EXT) {
            fprintf(out, ".const    k%d\n", i);
        } else {
            size_t j;
            fprintf(out, ".const    k%d = 0x", i);
            for (j = 0; j < P->esz; j++)
                fprintf(out, "%02x", P->consts[i][P->esz - 1 - j]);
            fputc('\n', out);
        }
    }
    if (P->n_consts || (P->flags & FLAG_BANK_EXT))
        fputc('\n', out);

    for (pc = 0; pc < P->n_insns; pc++) {
        insn d;
        char pad[32];
        int n;
        decode(P->insns[pc], &d);
        if (d.ctrl && d.op == C_ENDREP)
            indent--;
        n = indent > 0 ? indent : 0;
        if (n > 15)
            n = 15;
        memset(pad, ' ', (size_t)(2 * n));
        pad[2 * n] = 0;
        if (d.ctrl) {
            if (d.op == C_REPEAT) {
                fprintf(out, "%s%s %u\n", pad, CTRL_NAMES[d.op],
                        (unsigned)d.imm);
                indent++;
            } else if (d.op == C_DEPOSIT || d.op == C_SETACT) {
                fprintf(out, "%s%s r%d\n", pad, CTRL_NAMES[d.op], d.reg[1]);
            } else {
                fprintf(out, "%s%s\n", pad, CTRL_NAMES[d.op]);
            }
            continue;
        }
        {
            const char *name = NULL;
            const char *fields = NULL;
            char mnemonic[64];
            char a0[32], a1[32], a2[32];
            int wide = 0, short_ok = 1;
            for (i = 0; i < N_OPS; i++)
                if (OPS[i].op == d.op) {
                    name = cft_op_name((cft_op)d.op);
                    fields = OPS[i].fields;
                    break;
                }
            if (!name) {
                snprintf(mnemonic, sizeof mnemonic, "op%d", d.op);
            } else {
                snprintf(mnemonic, sizeof mnemonic, "%s", name);
            }
            if (d.rnd) {
                size_t l = strlen(mnemonic);
                snprintf(mnemonic + l, sizeof mnemonic - l, ".%s",
                         RND_NAMES[d.rnd]);
            }
            for (i = 0; i < 3; i++)
                if (const_index(&d, i) >= KADDR_PLAIN)
                    wide = 1;
            if (d.kx && !wide) {
                size_t l = strlen(mnemonic);
                snprintf(mnemonic + l, sizeof mnemonic - l, ".kx");
            }
            print_operand(&d, 0, a0, sizeof a0);
            print_operand(&d, 1, a1, sizeof a1);
            print_operand(&d, 2, a2, sizeof a2);
            if (fields) {
                for (i = 0; i < 3; i++) {
                    if (strchr(fields, 'a' + i))
                        continue;
                    /* a field the opcode does not read must be a plain
                     * zero register, or the short form would lose it */
                    if (d.kflag[i] || d.reg[i + 1])
                        short_ok = 0;
                }
            } else {
                short_ok = 0;
            }
            fprintf(out, "%s%s r%d, ", pad, mnemonic, d.reg[0]);
            if (short_ok) {
                const char *sep = "";
                for (i = 0; fields[i]; i++) {
                    const char *v = (fields[i] == 'a') ? a0 :
                                    (fields[i] == 'b') ? a1 : a2;
                    fprintf(out, "%s%s", sep, v);
                    sep = ", ";
                }
            } else {
                fprintf(out, "%s, %s, %s", a0, a1, a2);
            }
            fputc('\n', out);
        }
    }
}

/* ---- the header report ----------------------------------------------- */

static void features(const program *P, char *out, size_t cap)
{
    int kx = 0, regs32 = 0, imul = 0, i;
    uint32_t pc;
    for (pc = 0; pc < P->n_insns; pc++) {
        insn d;
        decode(P->insns[pc], &d);
        if (d.ctrl) {
            /* only DEPOSIT and SETACT have a register to extend */
            if ((d.op == C_DEPOSIT || d.op == C_SETACT) &&
                d.reg[1] >= REG_FIELD)
                regs32 = 1;
            continue;
        }
        if (d.kx)
            kx = 1;
        if (d.op == CFT_IMUL)
            imul = 1;
        for (i = 0; i < 4; i++)
            if (d.hi[i])
                regs32 = 1;
    }
    out[0] = 0;
    if (kx)
        strncat(out, "kx ", cap - strlen(out) - 1);
    if (regs32)
        strncat(out, "REGS32 ", cap - strlen(out) - 1);
    if (P->flags & FLAG_BANK_EXT)
        strncat(out, "BANK_PTR ", cap - strlen(out) - 1);
    if (imul)
        strncat(out, "IMUL ", cap - strlen(out) - 1);
    if (!out[0])
        strncat(out, "-", cap - strlen(out) - 1);
    else
        out[strlen(out) - 1] = 0;
}

static void print_info(const program *P, const uint8_t *img, size_t bytes)
{
    sha256 h;
    uint8_t digest[32];
    char hex[65], feat[128];
    sha256_start(&h);
    sha256_push(&h, img, bytes);
    sha256_end(&h, digest);
    hex32(digest, hex);
    features(P, feat, sizeof feat);
    printf("format        %s\n", cft_format_name(P->fmt));
    printf("instructions  %u\n", (unsigned)P->n_insns);
    printf("constants     %d%s\n", P->n_consts,
           (P->flags & FLAG_BANK_EXT) ? "  (external: supplied per run)"
                                      : "");
    printf("deposits      %u\n", (unsigned)P->max_deposits);
    printf("flags         0x%08x%s\n", (unsigned)P->flags,
           (P->flags & FLAG_BANK_EXT) ? "  BANK_EXT" : "");
    printf("bytes         %lu\n", (unsigned long)bytes);
    printf("features      %s\n", feat);
    printf("sha256        %s\n", hex);
}

/* ---- main ------------------------------------------------------------ */

static void usage(void)
{
    printf(
"cft-asm - assemble and disassemble orbit-sequencer programs\n"
"\n"
"  cft-asm in.cfta -o out.cftp      assemble\n"
"  cft-asm in.cfta                  assemble, check, write nothing\n"
"  cft-asm -d image.cftp            disassemble to stdout\n"
"  cft-asm -i image.cftp            header, features and SHA-256\n"
"\n"
"The text form is docs/PROGRAMS.md; python/cft_golden/asm.py is the\n"
"reference this tool is held to byte for byte.\n");
}

int main(int argc, char **argv)
{
    const char *in = NULL, *out = NULL;
    int mode = 'a', i;
    cft_status st;
    program P;

    for (i = 1; i < argc; i++) {
        const char *a = argv[i];
        if (!strcmp(a, "-h") || !strcmp(a, "--help")) { usage(); return 0; }
        else if (!strcmp(a, "-d")) mode = 'd';
        else if (!strcmp(a, "-i")) mode = 'i';
        else if (!strcmp(a, "-o")) {
            if (i + 1 >= argc)
                die("-o needs a path");
            out = argv[++i];
        } else if (a[0] == '-' && a[1]) {
            fprintf(stderr, "cft-asm: unknown option %s\n", a);
            return 1;
        } else {
            if (in)
                die("one input file at a time");
            in = a;
        }
    }
    if (!in) {
        usage();
        return 1;
    }

    /* The software backend, always: this tool computes nothing on a
     * device, it only needs the library's decimal conversion and its
     * name tables. */
    st = cft_open(NULL, 0, &DEV);
    if (st != CFT_OK)
        die("cft_open failed for the software backend");

    if (mode == 'a') {
        char line[MAX_LINE];
        FILE *f = fopen(in, "r");
        uint8_t *img;
        size_t bytes;
        if (!f) {
            fprintf(stderr, "cft-asm: cannot open %s\n", in);
            return 1;
        }
        memset(&P, 0, sizeof P);
        SRC = in;
        LINENO = 0;
        while (fgets(line, sizeof line, f)) {
            LINENO++;
            assemble_line(&P, line);
        }
        fclose(f);
        LINENO = 0;
        validate(&P);
        img = to_bytes(&P, &bytes);
        if (out) {
            FILE *o = fopen(out, "wb");
            if (!o) {
                fprintf(stderr, "cft-asm: cannot write %s\n", out);
                return 1;
            }
            if (fwrite(img, 1, bytes, o) != bytes)
                die("short write");
            fclose(o);
        }
        free(img);
    } else {
        size_t n;
        uint8_t *data = read_file(in, &n);
        SRC = in;
        LINENO = 0;
        load_image(data, n, &P);
        validate(&P);
        if (mode == 'd')
            disassemble(&P, stdout);
        else
            print_info(&P, data, n);
        free(data);
    }
    cft_close(DEV);
    return 0;
}
