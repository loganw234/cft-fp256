/* Copyright 2026 Logan W.
 * SPDX-License-Identifier: Apache-2.0
 *
 * cft-tf-subject: libcft as the system under test in a Berkeley TestFloat
 * pipe (docs/EXTERNAL-GENERATORS.md).
 *
 *   testfloat_gen -rnear_even f32_add \
 *     | cft-tf-subject f32_add near_even \
 *     | testfloat_ver -rnear_even -tininessafter f32_add
 *
 * testfloat_gen writes a case a line: the operands, then the result and
 * flags its own SoftFloat computes. This tool reads the operands only,
 * computes each case ONCE with libcft (n = 1, because libcft's flags are
 * per call and TestFloat judges flags per case), and writes
 * "operands result flags" as testfloat_ver reads it: upper-case hex, fixed
 * width, single spaces, the flags one byte. testfloat_ver then judges
 * libcft against SoftFloat. No TestFloat or SoftFloat source or object is
 * compiled or linked into this tool; the only contact is the text.
 *
 *   cft-tf-subject <function> [<round>] [exact|notexact]
 *
 * <function> is TestFloat's name for it, for binary32, binary64 and
 * binary128 (f32, f64, f128): f32_/f64_/f128_ add, sub, mul, mulAdd, div,
 * sqrt, rem, roundToInt, eq, le, lt, eq_signaling, le_quiet, lt_quiet; the
 * conversions among the three formats (f32_to_f64, f128_to_f32, ...); the
 * integer-to-float names (ui32_to_f32, i64_to_f128, ...) and the
 * float-to-integer names (f32_to_i32, f128_to_ui64, ...), each of the
 * latter also as <name>_r_minMag. Any other name (f16, extF80) is refused by
 * name. <round> is near_even (the default), near_maxMag, minMag, min or max,
 * TestFloat's own words. exact is the -exact of roundToInt and the
 * float-to-integer conversions.
 *
 * Things this tool settles, each a place TestFloat and libcft differ in
 * spelling and not in meaning:
 *
 *   * The flag bits run the other way. TestFloat: inexact 1, underflow 2,
 *     overflow 4, infinite (divide by zero) 8, invalid 16. libcft: invalid
 *     1, divide by zero 2, overflow 4, underflow 8, inexact 16.
 *   * libcft's ADD and SUB read their operands from a and c (b ignored),
 *     so TestFloat's x + y is cft_run(ADD, x, NULL, y).
 *   * TestFloat's f32_le and f32_lt are the SIGNALING comparisons (invalid
 *     on any NaN) and f32_eq the quiet one; libcft's quiet predicates are
 *     the opcodes CMPEQ/CMPLE/CMPLT and cft_cmp_sig is the signaling form.
 *     A Boolean result is the predicate's 1.0 or +0.0 read as true or false.
 *   * The _r_minMag conversions are toward zero by their name; the rounding
 *     argument is ignored for them, as TestFloat ignores it.
 *   * Tininess is not a setting here. libcft detects it after rounding and
 *     says so (python/cft_golden/softfloat.py, round_pack); run
 *     testfloat_ver with -tininessafter, its own default.
 *
 * CFT_SOAK_ARTIFACT names an .xclbin to run on instead of the software
 * backend, exactly as the soak tools read it; the banner on stderr names
 * the backend, so a card run and a software run are not alike in a log.
 * CFT_SOAK_SABOTAGE=1 flips the low bit of every 1,024th result and =2
 * toggles the inexact flag of every 1,024th case: a negative control, since
 * a pipe that cannot fail proves nothing. CFT_SOAK_SABOTAGE_EVERY=N changes
 * the 1,024 (a caller that sends the subject short streams, as the vector
 * runners do, needs a smaller period for the control to fire at all).
 *
 * Exit status: 0 at the end of input, 2 for any usage, input or library
 * failure, named on stderr. It never writes a line it did not compute.
 *
 * Build: make -C host cft-tf-subject
 */

#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "../include/cft.h"

typedef enum { K_ADD, K_SUB, K_MUL, K_FMA, K_DIV, K_SQRT, K_REM, K_RINT,
               K_F2F, K_I2F, K_F2I, K_CMP } kind;

/* a value of up to 128 bits, as its little-endian bytes - the layout cft_run
 * takes on the hosts main() insists on */
typedef struct { unsigned char b[16]; } val;

typedef struct {
    kind       k;
    cft_format fmt;     /* the float side; for K_F2F the source */
    cft_format dfmt;    /* K_F2F: the destination */
    int        isize;   /* K_I2F, K_F2I: bytes in the integer, 4 or 8 */
    int        isigned;
    int        cmp;     /* K_CMP: CFT_CMPEQ, CFT_CMPLE or CFT_CMPLT */
    int        sig;     /* K_CMP: invalid on any NaN, quiet ones included */
    int        minmag;  /* K_F2I: the _r_minMag form */
    int        nops;
    int        idig[3]; /* hex digits of each operand */
    int        odig;    /* hex digits of the result; 1 for a Boolean */
} fn_t;

static const struct { const char *nm; kind k; int nops; } FOPS[] = {
    { "add", K_ADD, 2 }, { "sub", K_SUB, 2 }, { "mul", K_MUL, 2 },
    { "mulAdd", K_FMA, 3 }, { "div", K_DIV, 2 }, { "sqrt", K_SQRT, 1 },
    { "rem", K_REM, 2 }, { "roundToInt", K_RINT, 1 },
};
static const struct { const char *nm; int cmp, sig; } CMPS[] = {
    { "eq", CFT_CMPEQ, 0 }, { "le", CFT_CMPLE, 1 }, { "lt", CFT_CMPLT, 1 },
    { "eq_signaling", CFT_CMPEQ, 1 }, { "le_quiet", CFT_CMPLE, 0 },
    { "lt_quiet", CFT_CMPLT, 0 },
};
static const struct { const char *nm; int size, sgn; } INTS[] = {
    { "ui32", 4, 0 }, { "ui64", 8, 0 }, { "i32", 4, 1 }, { "i64", 8, 1 },
};
static const struct { const char *nm; cft_round cr; } ROUNDS[] = {
    { "near_even", CFT_RNE }, { "near_maxMag", CFT_RMM }, { "minMag", CFT_RTZ },
    { "min", CFT_RDN }, { "max", CFT_RUP },
};
static const struct { const char *nm; cft_format f; int digits; } FLOATS[] = {
    { "f32", CFT_FP32, 8 }, { "f64", CFT_FP64, 16 }, { "f128", CFT_FP128, 32 },
};

#define COUNT(a) (sizeof(a) / sizeof((a)[0]))

static int fdig(cft_format f)
{
    size_t i;
    for (i = 0; i < COUNT(FLOATS); i++)
        if (FLOATS[i].f == f)
            return FLOATS[i].digits;
    return 0;
}

/* the float format a whole word names (s of length n), 1 if it names one */
static int float_name(const char *s, size_t n, cft_format *f)
{
    size_t i;
    for (i = 0; i < COUNT(FLOATS); i++)
        if (n == strlen(FLOATS[i].nm) && !strncmp(s, FLOATS[i].nm, n)) {
            *f = FLOATS[i].f;
            return 1;
        }
    return 0;
}

static int int_name(const char *s, size_t n, int *size, int *sgn)
{
    size_t i;
    for (i = 0; i < COUNT(INTS); i++)
        if (n == strlen(INTS[i].nm) && !strncmp(s, INTS[i].nm, n)) {
            *size = INTS[i].size;
            *sgn = INTS[i].sgn;
            return 1;
        }
    return 0;
}

static int parse_fn(const char *name, fn_t *f)
{
    const char *us = strchr(name, '_');
    cft_format a, b;
    int sz, sg;
    size_t i;
    int j;

    memset(f, 0, sizeof *f);
    if (!us)
        return 0;
    if (float_name(name, (size_t)(us - name), &a)) {
        const char *r = us + 1;
        f->fmt = a;
        f->odig = fdig(a);
        for (i = 0; i < COUNT(FOPS); i++)
            if (!strcmp(r, FOPS[i].nm)) {
                f->k = FOPS[i].k;
                f->nops = FOPS[i].nops;
                for (j = 0; j < 3; j++)
                    f->idig[j] = fdig(a);
                return 1;
            }
        for (i = 0; i < COUNT(CMPS); i++)
            if (!strcmp(r, CMPS[i].nm)) {
                f->k = K_CMP;
                f->cmp = CMPS[i].cmp;
                f->sig = CMPS[i].sig;
                f->nops = 2;
                f->idig[0] = f->idig[1] = fdig(a);
                f->odig = 1;
                return 1;
            }
        if (!strncmp(r, "to_", 3)) {
            const char *t = r + 3;
            const char *us2 = strchr(t, '_');
            f->nops = 1;
            f->idig[0] = fdig(a);
            if (float_name(t, strlen(t), &b)) {
                if (b == a)
                    return 0;
                f->k = K_F2F;
                f->dfmt = b;
                f->odig = fdig(b);
                return 1;
            }
            if (int_name(t, us2 ? (size_t)(us2 - t) : strlen(t), &sz, &sg)) {
                if (us2 && strcmp(us2, "_r_minMag"))
                    return 0;
                f->k = K_F2I;
                f->isize = sz;
                f->isigned = sg;
                f->minmag = us2 != NULL;
                f->odig = 2 * sz;
                return 1;
            }
        }
        return 0;
    }
    if (int_name(name, (size_t)(us - name), &sz, &sg) &&
        !strncmp(us + 1, "to_", 3) &&
        float_name(us + 4, strlen(us + 4), &a)) {
        f->k = K_I2F;
        f->fmt = a;
        f->isize = sz;
        f->isigned = sg;
        f->nops = 1;
        f->idig[0] = 2 * sz;
        f->odig = fdig(a);
        return 1;
    }
    return 0;
}

/* ---- the library -------------------------------------------------- */

static cft_device *dev;

static unsigned tf_flags(uint32_t f)
{
    return ((f & CFT_FLAG_INEXACT)   ? 1u  : 0u) |
           ((f & CFT_FLAG_UNDERFLOW) ? 2u  : 0u) |
           ((f & CFT_FLAG_OVERFLOW)  ? 4u  : 0u) |
           ((f & CFT_FLAG_DIVBYZERO) ? 8u  : 0u) |
           ((f & CFT_FLAG_INVALID)   ? 16u : 0u);
}

static void die(const char *what, cft_status st)
{
    const char *d = cft_last_error();
    fprintf(stderr, "cft-tf-subject: %s: %s%s%s\n", what, cft_strerror(st),
            (d && *d) ? " - " : "", (d && *d) ? d : "");
    exit(2);
}

/* One case. */
static void run_case(const fn_t *f, cft_round rnd, int exact,
                     const val in[3], val *out, uint32_t *fl)
{
    const unsigned char *A = in[0].b, *B = in[1].b, *C = in[2].b;
    unsigned char Z[16];
    cft_status st = CFT_OK;
    size_t zb, i;

    memset(Z, 0, sizeof Z);
    *fl = 0;
    switch (f->k) {
    case K_ADD: st = cft_run(dev, CFT_ADD, f->fmt, rnd, A, NULL, B, Z, 1, fl, NULL); break;
    case K_SUB: st = cft_run(dev, CFT_SUB, f->fmt, rnd, A, NULL, B, Z, 1, fl, NULL); break;
    case K_MUL: st = cft_run(dev, CFT_MUL, f->fmt, rnd, A, B, NULL, Z, 1, fl, NULL); break;
    case K_FMA: st = cft_run(dev, CFT_FMA, f->fmt, rnd, A, B, C, Z, 1, fl, NULL); break;
    case K_DIV: st = cft_div(dev, f->fmt, rnd, A, B, Z, 1, fl, NULL); break;
    case K_SQRT: st = cft_sqrt(dev, f->fmt, rnd, A, Z, 1, fl, NULL); break;
    case K_REM: st = cft_rem(dev, f->fmt, A, B, Z, 1, fl); break;
    case K_RINT: st = cft_rint(dev, f->fmt, rnd, exact, A, Z, 1, fl, NULL); break;
    case K_F2F: st = cft_convert(dev, f->fmt, f->dfmt, rnd, A, Z, 1, fl); break;
    case K_CMP:
        if (f->sig)
            st = cft_cmp_sig(dev, (cft_op)f->cmp, f->fmt, A, B, Z, 1, fl, NULL);
        else
            st = cft_run(dev, (cft_op)f->cmp, f->fmt, rnd, A, B, NULL, Z, 1, fl, NULL);
        break;
    case K_I2F: {
        union { int32_t i32; uint32_t u32; int64_t i64; uint64_t u64; } v;
        memset(&v, 0, sizeof v);
        memcpy(&v, A, (size_t)f->isize);
        if (f->isize == 4 && f->isigned)
            st = cft_cvt_from_i32(dev, f->fmt, rnd, &v.i32, Z, 1, fl);
        else if (f->isize == 4)
            st = cft_cvt_from_u32(dev, f->fmt, rnd, &v.u32, Z, 1, fl);
        else if (f->isigned)
            st = cft_cvt_from_i64(dev, f->fmt, rnd, &v.i64, Z, 1, fl);
        else
            st = cft_cvt_from_u64(dev, f->fmt, rnd, &v.u64, Z, 1, fl);
        break;
    }
    case K_F2I: {
        union { int32_t i32; uint32_t u32; int64_t i64; uint64_t u64; } v;
        cft_round r = f->minmag ? CFT_RTZ : rnd;
        memset(&v, 0, sizeof v);
        if (f->isize == 4 && f->isigned)
            st = cft_cvt_to_i32(dev, f->fmt, r, exact, A, &v.i32, 1, fl);
        else if (f->isize == 4)
            st = cft_cvt_to_u32(dev, f->fmt, r, exact, A, &v.u32, 1, fl);
        else if (f->isigned)
            st = cft_cvt_to_i64(dev, f->fmt, r, exact, A, &v.i64, 1, fl);
        else
            st = cft_cvt_to_u64(dev, f->fmt, r, exact, A, &v.u64, 1, fl);
        memcpy(Z, &v, 8);
        break;
    }
    }
    if (st != CFT_OK)
        die("a libcft call failed", st);

    switch (f->k) {
    case K_F2F: zb = cft_format_size(f->dfmt); break;
    case K_F2I: zb = (size_t)f->isize; break;
    default:    zb = cft_format_size(f->fmt); break;
    }
    memset(out, 0, sizeof *out);
    if (f->k == K_CMP) {            /* the predicate's 1.0 or +0.0 as 1 or 0 */
        for (i = 0; i < zb; i++)
            if (Z[i])
                out->b[0] = 1;
    } else {
        memcpy(out->b, Z, zb);
    }
    *fl = tf_flags(*fl);
}

/* ---- the text ----------------------------------------------------- */

static int hexval(int c)
{
    if (c >= '0' && c <= '9') return c - '0';
    if (c >= 'A' && c <= 'F') return c - 'A' + 10;
    if (c >= 'a' && c <= 'f') return c - 'a' + 10;
    return -1;
}

/* One field of exactly `digits` hex digits, as testfloat_ver insists on. */
static int field(const char **p, int digits, val *v)
{
    int i;
    memset(v, 0, sizeof *v);
    while (**p == ' ')
        (*p)++;
    for (i = 0; i < digits; i++) {
        int h = hexval((unsigned char)(*p)[i]);
        int pos = digits - 1 - i;           /* nibble number from the least */
        if (h < 0)
            return 0;
        v->b[pos / 2] = (unsigned char)(v->b[pos / 2] | (h << (4 * (pos % 2))));
    }
    *p += digits;
    return **p == ' ' || **p == '\n' || **p == '\r' || **p == '\0';
}

static char obuf[1 << 16];
static size_t olen;

static void flush_out(void)
{
    if (olen && fwrite(obuf, 1, olen, stdout) != olen) {
        fprintf(stderr, "cft-tf-subject: write failed\n");
        exit(2);
    }
    olen = 0;
}

static void put_val(const val *v, int digits)
{
    static const char HX[] = "0123456789ABCDEF";
    int pos;
    for (pos = digits - 1; pos >= 0; pos--)
        obuf[olen++] = HX[(v->b[pos / 2] >> (4 * (pos % 2))) & 15];
}

int main(int argc, char **argv)
{
    fn_t f;
    cft_round rnd = CFT_RNE;
    int exact = 0, i, sabotage = 0;
    unsigned long long n = 0, every = 1024;
    const char *art, *e, *rname = "near_even";
    char line[512];
    cft_status ost;
    uint16_t one = 1;

    if (*(unsigned char *)&one != 1) {
        fprintf(stderr, "cft-tf-subject: refused: a little-endian host is assumed\n");
        return 2;
    }
    if (argc < 2 || argc > 4 || !parse_fn(argv[1], &f)) {
        fprintf(stderr,
            "usage: %s <function> [near_even|near_maxMag|minMag|min|max] [exact|notexact]\n"
            "  <function> is a TestFloat name over f32, f64 and f128 (add sub mul mulAdd div\n"
            "  sqrt rem roundToInt eq le lt eq_signaling le_quiet lt_quiet, the conversions\n"
            "  among the three, the integer conversions, each _r_minMag); refused: %s\n",
            argv[0], argc >= 2 ? argv[1] : "(none)");
        return 2;
    }
    for (i = 2; i < argc; i++) {
        size_t r;
        if (!strcmp(argv[i], "exact")) { exact = 1; continue; }
        if (!strcmp(argv[i], "notexact")) { exact = 0; continue; }
        for (r = 0; r < COUNT(ROUNDS); r++)
            if (!strcmp(argv[i], ROUNDS[r].nm)) {
                rnd = ROUNDS[r].cr;
                rname = ROUNDS[r].nm;
                break;
            }
        if (r == COUNT(ROUNDS)) {
            fprintf(stderr, "cft-tf-subject: unknown argument %s\n", argv[i]);
            return 2;
        }
    }

    art = getenv("CFT_SOAK_ARTIFACT");
    if (art && !*art)
        art = NULL;
    ost = cft_open(art, 0, &dev);
    if (ost != CFT_OK)
        die(art ? "cft_open of the artifact failed" : "cft_open failed", ost);
    fprintf(stderr, "cft-tf-subject: %s %s%s on the %s backend%s%s\n", argv[1],
            rname, exact ? " exact" : "", art ? "DEVICE" : "software",
            art ? ": " : "", art ? art : "");
    e = getenv("CFT_SOAK_SABOTAGE");
    if (e && (*e == '1' || *e == '2'))
        sabotage = *e - '0';
    e = getenv("CFT_SOAK_SABOTAGE_EVERY");
    if (e && atoi(e) > 0)
        every = (unsigned long long)atoi(e);

    setvbuf(stdin, NULL, _IOFBF, 1 << 16);
    while (fgets(line, sizeof line, stdin)) {
        const char *p = line;
        val in[3], z;
        uint32_t fl;
        int j;

        if (!strchr(line, '\n') && !feof(stdin)) {
            fprintf(stderr, "cft-tf-subject: line %llu is longer than %d bytes\n", n + 1, (int)sizeof line - 1);
            return 2;
        }
        memset(in, 0, sizeof in);
        for (j = 0; j < f.nops; j++)
            if (!field(&p, f.idig[j], &in[j])) {
                fprintf(stderr, "cft-tf-subject: line %llu: operand %d is not %d hex digits: %s",
                        n + 1, j + 1, f.idig[j], line);
                return 2;
            }
        run_case(&f, rnd, exact, in, &z, &fl);
        n++;
        if (sabotage && n % every == 0) {
            if (sabotage == 1) z.b[0] ^= 1u;
            else fl ^= 1u;
        }
        if (olen > sizeof obuf - 160)
            flush_out();
        for (j = 0; j < f.nops; j++) {
            put_val(&in[j], f.idig[j]);
            obuf[olen++] = ' ';
        }
        put_val(&z, f.odig);
        obuf[olen++] = ' ';
        {
            val fv;
            memset(&fv, 0, sizeof fv);
            fv.b[0] = (unsigned char)fl;
            put_val(&fv, 2);
        }
        obuf[olen++] = '\n';
    }
    flush_out();
    fflush(stdout);
    fprintf(stderr, "cft-tf-subject: %s %s%s: %llu cases\n", argv[1], rname, exact ? " exact" : "", n);
    cft_close(dev);
    return 0;
}
