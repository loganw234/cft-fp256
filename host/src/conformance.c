/* Copyright 2026 Logan W.
 * SPDX-License-Identifier: Apache-2.0
 *
 * Replay the published conformance vector sets through whatever
 * backend is open.
 *
 * This is the acceptance test for a new backend, a new language
 * binding, a new device generation, or somebody else's independent
 * implementation - and it is how a user audits ours. The guarantee at
 * the top of cft.h is not something to take on trust; it is
 * machine-checkable, so this makes checking it a function call.
 *
 * The files are enumerated by name rather than by scanning the
 * directory: the generator's naming is fixed (vectors/gen_vectors.py),
 * and reading a directory is the one piece of this library that would
 * otherwise need a POSIX or Win32 fork. A missing set is skipped, and
 * the report says which ran - so an empty vectors directory reads as
 * "nothing was checked" instead of as a pass.
 */

#include <stdarg.h>
#include <stdio.h>
#include <string.h>
#include <stdlib.h>

#include "../include/cft.h"
#include "softfloat.h"
#include "transcend.h"

#define MAX_ELEM   32       /* fp256 */
#define LINE_MAX   4096
#define TOKEN_MAX  128

/* One parsed case, held so a set can be replayed twice: once an
 * element at a time, and once as arrays.
 *
 * Both passes are needed and they catch different things. Element at a
 * time is the only way to check a case's exception flags exactly,
 * because flags are sticky and a batch reports their OR. But a device
 * backend splits an array across compute units, and a replay that only
 * ever passes n=1 drives one beat on one tile - so every partitioning
 * bug there is, up to and including "tiles 2 to 4 are never used", is
 * invisible to it. A set that is the published acceptance test for a
 * new backend should not be structurally incapable of failing on the
 * backend's hardest code. */
typedef struct {
    int      op;
    uint8_t  a[MAX_ELEM], b[MAX_ELEM], c[MAX_ELEM], d[MAX_ELEM];
    uint32_t flags;
} cft_case;

/* ---- a scanner for this one schema ------------------------------ *
 *
 * Not a JSON parser. The generator emits a flat object with known
 * keys, hex strings and one integer - no nesting, no escapes, no
 * unicode. A real parser would be a larger dependency than the format
 * it reads, and would still have to be told this schema.
 */

static const char *find_field(const char *line, const char *key)
{
    size_t klen = strlen(key);
    const char *p = line;
    while ((p = strchr(p, '"')) != NULL) {
        if (strncmp(p + 1, key, klen) == 0 && p[1 + klen] == '"') {
            const char *q = p + 2 + klen;
            while (*q == ' ' || *q == '\t')
                q++;
            if (*q == ':')
                return q + 1;
        }
        p++;
    }
    return NULL;
}

static int field_string(const char *line, const char *key, char *out,
                        size_t out_size)
{
    const char *p = find_field(line, key);
    size_t i = 0;
    if (!p)
        return -1;
    while (*p == ' ' || *p == '\t')
        p++;
    if (*p != '"')
        return -1;
    p++;
    while (*p && *p != '"') {
        if (i + 1 >= out_size)
            return -1;
        out[i++] = *p++;
    }
    if (*p != '"')
        return -1;
    out[i] = '\0';
    return 0;
}

static int field_u32(const char *line, const char *key, uint32_t *out)
{
    const char *p = find_field(line, key);
    unsigned long v = 0;
    int digits = 0;
    if (!p)
        return -1;
    while (*p == ' ' || *p == '\t')
        p++;
    while (*p >= '0' && *p <= '9') {
        v = v * 10 + (unsigned long)(*p - '0');
        p++;
        digits++;
    }
    if (!digits)
        return -1;
    *out = (uint32_t)v;
    return 0;
}


/* ---- the reduction schema's growing line buffer -------------------
 *
 * The other two schemas hold a case in a fixed number of single
 * elements, so LINE_MAX bounds them. A reduction's operand is a whole
 * VECTOR whose length is part of the case: at fp256 a 129-element pair
 * of vectors is about 17 KB, so this one grows instead of guessing.
 * A line that does not fit is a reason to allocate, never a reason to
 * silently truncate a case and score the fragment.
 */
typedef struct {
    char  *buf;
    size_t cap;
} rline;

/* 1 = a line is in L->buf, 0 = end of file, -1 = out of memory. */
static int rline_get(rline *L, FILE *fp)
{
    size_t used = 0;
    for (;;) {
        if (used + 2 > L->cap) {
            size_t want = L->cap ? L->cap * 2 : 8192;
            char *bigger = (char *)realloc(L->buf, want);
            if (!bigger)
                return -1;
            L->buf = bigger;
            L->cap = want;
        }
        if (!fgets(L->buf + used, (int)(L->cap - used), fp))
            return used ? 1 : 0;
        used += strlen(L->buf + used);
        if (used && L->buf[used - 1] == '\n')
            return 1;
        if (feof(fp))
            return 1;
    }
}

/* A signed decimal field, for the "n" of pown, compound and rootn -
 * the one field in these sets that is an INTEGER rather than an
 * encoding, and the reason it has a key of its own rather than being
 * squeezed into "b". The whole int64 range has to parse: pown of a base
 * one ulp from 1 against an exponent of 2^62 is an ordinary number, not
 * an edge case. */
static int field_i64(const char *line, const char *key, int64_t *out)
{
    const char *p = find_field(line, key);
    uint64_t v = 0;
    int digits = 0, neg = 0;
    if (!p)
        return -1;
    while (*p == ' ' || *p == '\t')
        p++;
    if (*p == '-') {
        neg = 1;
        p++;
    }
    while (*p >= '0' && *p <= '9') {
        v = v * 10u + (uint64_t)(*p - '0');
        p++;
        digits++;
    }
    if (!digits || digits > 19)
        return -1;
    *out = neg ? -(int64_t)v : (int64_t)v;
    return 0;
}

static int hexval(int ch)
{
    if (ch >= '0' && ch <= '9') return ch - '0';
    if (ch >= 'a' && ch <= 'f') return ch - 'a' + 10;
    if (ch >= 'A' && ch <= 'F') return ch - 'A' + 10;
    return -1;
}

/* "0x" + exactly 2*nbytes hex digits, most significant first, into a
 * dense little-endian element. */
static int parse_hex_elem(const char *s, uint8_t *out, int nbytes)
{
    int ndig = 2 * nbytes, i;
    if (s[0] != '0' || (s[1] != 'x' && s[1] != 'X'))
        return -1;
    s += 2;
    if ((int)strlen(s) != ndig)
        return -1;
    for (i = 0; i < nbytes; i++) {
        int hi = hexval(s[ndig - 2 * (i + 1)]);
        int lo = hexval(s[ndig - 2 * i - 1]);
        if (hi < 0 || lo < 0)
            return -1;
        out[i] = (uint8_t)((hi << 4) | lo);
    }
    return 0;
}

static void format_hex_elem(const uint8_t *in, int nbytes, char *out)
{
    static const char digits[] = "0123456789abcdef";
    int i;
    out[0] = '0';
    out[1] = 'x';
    for (i = 0; i < nbytes; i++) {
        uint8_t byte = in[nbytes - 1 - i];
        out[2 + 2 * i]     = digits[byte >> 4];
        out[2 + 2 * i + 1] = digits[byte & 0xf];
    }
    out[2 + 2 * nbytes] = '\0';
}

/* An array of hex elements: ["0x..", "0x..", ...] -> packed
 * little-endian elements. Writes at most `cap` of them and reports how
 * many the line actually held, so a case whose array disagrees with
 * its own "n" is caught rather than replayed short. */
static int field_hex_array(const char *line, const char *key, uint8_t *out,
                           int nbytes, size_t cap, size_t *count)
{
    const char *p = find_field(line, key);
    size_t k = 0;
    if (!p)
        return -1;
    while (*p == ' ' || *p == '\t')
        p++;
    if (*p != '[')
        return -1;
    p++;
    for (;;) {
        char tok[2 * MAX_ELEM + 3];
        size_t i = 0;
        while (*p == ' ' || *p == '\t' || *p == ',')
            p++;
        if (*p == ']') {
            *count = k;
            return 0;
        }
        if (*p != '"')
            return -1;
        p++;
        while (*p && *p != '"') {
            if (i + 1 >= sizeof tok)
                return -1;
            tok[i++] = *p++;
        }
        if (*p != '"')
            return -1;
        p++;
        tok[i] = '\0';
        if (k >= cap)
            return -1;
        if (parse_hex_elem(tok, out + k * (size_t)nbytes, nbytes))
            return -1;
        k++;
    }
}

static int op_from_name(const char *s)
{
    int i;
    if (strncmp(s, "reserved", 8) == 0) {
        const char *p = s + 8;
        int v = 0, digits = 0;
        while (*p >= '0' && *p <= '9') {
            v = v * 10 + (*p - '0');
            p++;
            digits++;
        }
        if (!digits || *p != '\0' || v > 255)
            return -1;
        /* A set generated before an opcode was assigned still names it
         * "reservedNN", and replaying it would now exercise a DIFFERENT
         * operation than the one whose answer was recorded. Caught here
         * and reported as its own thing: this is not a corrupt file, it
         * is a stale one, and the two want different responses from
         * whoever is reading the error. */
        if (strcmp(cft_op_name((cft_op)v), "reserved") != 0)
            return -2;
        return v;
    }
    for (i = 0; i < 30; i++)
        if (i != 15 && strcmp(cft_op_name((cft_op)i), s) == 0)
            return i;
    return -1;
}

static int rnd_from_name(const char *s)
{
    static const char *const names[5] = { "rne", "rtz", "rdn", "rup", "rmm" };
    int i;
    for (i = 0; i < 5; i++)
        if (strcmp(names[i], s) == 0)
            return i;
    return -1;
}

/* ---- report building --------------------------------------------- */

typedef struct {
    char  *buf;
    size_t size;
    size_t used;
} rep;

static void rep_add(rep *r, const char *fmt, ...)
{
    va_list ap;
    int n;
    if (!r->buf || r->used + 1 >= r->size)
        return;
    va_start(ap, fmt);
    n = vsnprintf(r->buf + r->used, r->size - r->used, fmt, ap);
    va_end(ap);
    if (n > 0) {
        r->used += (size_t)n;
        if (r->used >= r->size)
            r->used = r->size - 1;
    }
}

/* ---- the array pass ----------------------------------------------- *
 *
 * Replay a whole set again as arrays, one cft_run per opcode. On the
 * software backend this proves the element loop; on a device backend
 * it is the only thing here that splits work across compute units, and
 * so the only thing that can catch a slice boundary that is off by
 * one, a tile that is never given work, or a result written to the
 * wrong offset.
 *
 * Flags are checked as the OR over the batch, which is what a sticky
 * word means for an array. The per-element pass has already pinned
 * each case's flags exactly, so between them nothing is unchecked. */
static cft_status array_pass(cft_device *dev, int fi, int rnd, int esz,
                             const cft_case *cases, size_t ncases,
                             const char *path, rep *r,
                             const char *const *rnames)
{
    const cft_fmt_desc *f = &cft_sf_formats[fi];
    uint8_t *a = NULL, *b = NULL, *c = NULL, *got = NULL;
    cft_status ret = CFT_OK;
    int op;

    if (ncases == 0)
        return CFT_OK;
    a   = (uint8_t *)malloc(ncases * (size_t)esz);
    b   = (uint8_t *)malloc(ncases * (size_t)esz);
    c   = (uint8_t *)malloc(ncases * (size_t)esz);
    got = (uint8_t *)malloc(ncases * (size_t)esz);
    if (!a || !b || !c || !got) {
        free(a); free(b); free(c); free(got);
        return CFT_ERR_OUT_OF_MEMORY;
    }

    for (op = 0; op < 256 && ret == CFT_OK; op++) {
        size_t k = 0, i, batch;
        uint32_t want_flags = 0, got_flags = 0;
        cft_status st;

        for (i = 0; i < ncases; i++) {
            if (cases[i].op != op)
                continue;
            memcpy(a + k * (size_t)esz, cases[i].a, (size_t)esz);
            memcpy(b + k * (size_t)esz, cases[i].b, (size_t)esz);
            memcpy(c + k * (size_t)esz, cases[i].c, (size_t)esz);
            want_flags |= cases[i].flags;
            k++;
        }
        if (k == 0)
            continue;
        batch = k;

        memset(got, 0, k * (size_t)esz);
        st = cft_run(dev, (cft_op)op, (cft_format)fi, (cft_round)rnd,
                     a, b, c, got, k, &got_flags, NULL);
        if (st != CFT_OK) {
            rep_add(r, "%s: array pass, %s x%lu: cft_run failed: %s\n",
                    path, cft_op_name((cft_op)op), (unsigned long)k,
                    cft_strerror(st));
            ret = st;
            break;
        }

        k = 0;
        for (i = 0; i < ncases && ret == CFT_OK; i++) {
            if (cases[i].op != op)
                continue;
            if (memcmp(got + k * (size_t)esz, cases[i].d, (size_t)esz) != 0) {
                char hw[2 * MAX_ELEM + 3], hg[2 * MAX_ELEM + 3];
                format_hex_elem(cases[i].d, esz, hw);
                format_hex_elem(got + k * (size_t)esz, esz, hg);
                r->used = 0;
                if (r->buf && r->size)
                    r->buf[0] = '\0';
                rep_add(r, "%s: ARRAY PASS element %lu of %lu (%s %s %s)\n"
                           "  expected %s\n  got      %s\n"
                           "  the same case passes one element at a time, "
                           "so this is the array path - partitioning, "
                           "padding, or a slice offset\n",
                        path, (unsigned long)k, (unsigned long)batch,
                        f->name, cft_op_name((cft_op)op), rnames[rnd],
                        hw, hg);
                ret = CFT_ERR_INTERNAL;
            }
            k++;
        }
        if (ret == CFT_OK && got_flags != want_flags) {
            r->used = 0;
            if (r->buf && r->size)
                r->buf[0] = '\0';
            rep_add(r, "%s: ARRAY PASS flags for %s %s over %lu elements: "
                       "got 0x%02x, expected the OR of the cases 0x%02x\n",
                    path, cft_op_name((cft_op)op), rnames[rnd],
                    (unsigned long)batch, (unsigned)got_flags,
                    (unsigned)want_flags);
            ret = CFT_ERR_INTERNAL;
        }
    }

    free(a); free(b); free(c); free(got);
    return ret;
}

/* ---- the transcendental sets -------------------------------------- *
 *
 * A different schema and a different dispatch, in their own files: the
 * transcendentals are library entry points rather than opcodes, so a
 * case names a FUNCTION and there is no opcode field to put it in.
 * Keeping them separate also means a consumer that predates ABI 0.3
 * reads exactly the files it always read, and one that skips these
 * skips a file rather than failing a line.
 *
 * The dispatch is by NAME through cft_tr_from_name and cft_tr_arity,
 * so ABI 0.4's eleven and 0.5's nine needed nothing here beyond the
 * enum they were added to - and a replayer built against 0.3 and handed
 * a 0.4 or 0.5 set
 * refuses on the name of a function it does not know, which is the
 * refusal it should give.
 *
 * Replayed the same two ways as the opcode sets, for the same two
 * reasons: one element at a time pins each case's flags exactly, and
 * whole arrays exercise the batch loop and the flag OR.
 */

typedef struct {
    int      fn;
    int64_t  nn;             /* the "n" of pown, compound and rootn */
    uint8_t  a[MAX_ELEM], b[MAX_ELEM], d[MAX_ELEM];
    uint32_t flags;
} cft_tr_case;

static cft_status transcend_array_pass(cft_device *dev, int fi, int rnd,
                                       int esz, const cft_tr_case *cases,
                                       size_t ncases, const char *path,
                                       rep *r, const char *const *rnames)
{
    const cft_fmt_desc *f = &cft_sf_formats[fi];
    uint8_t *a = NULL, *b = NULL, *got = NULL;
    int64_t *nn = NULL;
    cft_status ret = CFT_OK;
    int fn;

    if (ncases == 0)
        return CFT_OK;
    a   = (uint8_t *)malloc(ncases * (size_t)esz);
    b   = (uint8_t *)malloc(ncases * (size_t)esz);
    got = (uint8_t *)malloc(ncases * (size_t)esz);
    nn  = (int64_t *)malloc(ncases * sizeof *nn);
    if (!a || !b || !got || !nn) {
        free(a); free(b); free(got); free(nn);
        return CFT_ERR_OUT_OF_MEMORY;
    }

    for (fn = 0; fn < CFT_TR_COUNT && ret == CFT_OK; fn++) {
        size_t k = 0, i, batch;
        uint32_t want_flags = 0, got_flags = 0;
        cft_status st;

        for (i = 0; i < ncases; i++) {
            if (cases[i].fn != fn)
                continue;
            memcpy(a + k * (size_t)esz, cases[i].a, (size_t)esz);
            memcpy(b + k * (size_t)esz, cases[i].b, (size_t)esz);
            nn[k] = cases[i].nn;
            want_flags |= cases[i].flags;
            k++;
        }
        if (k == 0)
            continue;
        batch = k;

        memset(got, 0, k * (size_t)esz);
        st = cft_tr_apply(dev, fn, (cft_format)fi, (cft_round)rnd, a,
                          cft_tr_arity(fn) == 2 ? b : NULL,
                          cft_tr_has_int(fn) ? nn : NULL, got, k,
                          &got_flags);
        if (st != CFT_OK) {
            rep_add(r, "%s: array pass, %s x%lu: failed: %s\n",
                    path, cft_tr_name(fn), (unsigned long)k,
                    cft_strerror(st));
            ret = st;
            break;
        }

        k = 0;
        for (i = 0; i < ncases && ret == CFT_OK; i++) {
            if (cases[i].fn != fn)
                continue;
            if (memcmp(got + k * (size_t)esz, cases[i].d, (size_t)esz) != 0) {
                char hw[2 * MAX_ELEM + 3], hg[2 * MAX_ELEM + 3];
                format_hex_elem(cases[i].d, esz, hw);
                format_hex_elem(got + k * (size_t)esz, esz, hg);
                r->used = 0;
                if (r->buf && r->size)
                    r->buf[0] = '\0';
                rep_add(r, "%s: ARRAY PASS element %lu of %lu (%s %s %s)\n"
                           "  expected %s\n  got      %s\n"
                           "  the same case passes one element at a time, "
                           "so this is the batch loop\n",
                        path, (unsigned long)k, (unsigned long)batch,
                        f->name, cft_tr_name(fn), rnames[rnd], hw, hg);
                ret = CFT_ERR_INTERNAL;
            }
            k++;
        }
        if (ret == CFT_OK && got_flags != want_flags) {
            r->used = 0;
            if (r->buf && r->size)
                r->buf[0] = '\0';
            rep_add(r, "%s: ARRAY PASS flags for %s %s over %lu elements: "
                       "got 0x%02x, expected the OR of the cases 0x%02x\n",
                    path, cft_tr_name(fn), rnames[rnd],
                    (unsigned long)batch, (unsigned)got_flags,
                    (unsigned)want_flags);
            ret = CFT_ERR_INTERNAL;
        }
    }

    free(a); free(b); free(got); free(nn);
    return ret;
}

static cft_status transcend_set(cft_device *dev, int fi, int ri, int esz,
                                const char *path, rep *r,
                                const char *const *rnames, uint64_t *total)
{
    const cft_fmt_desc *f = &cft_sf_formats[fi];
    char line[LINE_MAX];
    unsigned long lineno = 0;
    cft_tr_case *cases = NULL;
    size_t ncases = 0, ccap = 0;
    cft_status arr;
    FILE *fp = fopen(path, "r");

    if (!fp)
        return CFT_OK;                    /* absent is not a failure */

    while (fgets(line, (int)sizeof line, fp)) {
        char tok[TOKEN_MAX];
        uint8_t ea[MAX_ELEM], eb[MAX_ELEM];
        uint8_t want_d[MAX_ELEM], got_d[MAX_ELEM];
        uint32_t want_flags = 0, got_flags = 0;
        int64_t enn = 0;
        int fn = -1, rnd = -1, binary, has_n;
        cft_status st;

        lineno++;
        if (line[0] == '\n' || line[0] == '\r' || line[0] == '\0')
            continue;
        {
            const char *why = NULL;
            if (field_string(line, "fn", tok, sizeof tok))
                why = "no \"fn\" field - this is not a transcendental set";
            else if ((fn = cft_tr_from_name(tok)) < 0)
                why = "unknown transcendental name";
            else if (field_string(line, "rnd", tok, sizeof tok))
                why = "no \"rnd\" field";
            else if ((rnd = rnd_from_name(tok)) < 0)
                why = "unknown rounding attribute";
            else if (field_u32(line, "flags", &want_flags))
                why = "no \"flags\" field";
            if (why) {
                fclose(fp);
                free(cases);
                rep_add(r, "%s:%lu: %s\n", path, lineno, why);
                return CFT_ERR_ARTIFACT;
            }
        }
        binary = cft_tr_arity(fn) == 2;
        has_n = cft_tr_has_int(fn);
        memset(eb, 0, sizeof eb);

#define TGET(key, dst)                                                   \
        if (field_string(line, key, tok, sizeof tok) ||                  \
            parse_hex_elem(tok, dst, esz)) {                             \
            fclose(fp);                                                  \
            free(cases);                                                 \
            rep_add(r, "%s:%lu: bad \"%s\" field\n", path, lineno, key); \
            return CFT_ERR_ARTIFACT;                                     \
        }
        TGET("a", ea)
        if (binary)
            TGET("b", eb)
        TGET("d", want_d)
#undef TGET
        if (has_n && field_i64(line, "n", &enn)) {
            fclose(fp);
            free(cases);
            rep_add(r, "%s:%lu: no \"n\" field - %s takes an integer "
                       "exponent\n", path, lineno, cft_tr_name(fn));
            return CFT_ERR_ARTIFACT;
        }

        memset(got_d, 0, (size_t)esz);
        st = cft_tr_apply(dev, fn, (cft_format)fi, (cft_round)rnd, ea,
                          binary ? eb : NULL, has_n ? &enn : NULL,
                          got_d, 1, &got_flags);
        if (st != CFT_OK) {
            fclose(fp);
            free(cases);
            rep_add(r, "%s:%lu: %s failed: %s\n", path, lineno,
                    cft_tr_name(fn), cft_strerror(st));
            return st;
        }
        (*total)++;

        if (memcmp(got_d, want_d, (size_t)esz) != 0 ||
            got_flags != want_flags) {
            char ha[2 * MAX_ELEM + 3], hb[2 * MAX_ELEM + 3];
            char hw[2 * MAX_ELEM + 3], hg[2 * MAX_ELEM + 3];
            fclose(fp);
            free(cases);
            format_hex_elem(ea, esz, ha);
            format_hex_elem(eb, esz, hb);
            format_hex_elem(want_d, esz, hw);
            format_hex_elem(got_d, esz, hg);
            r->used = 0;
            if (r->buf && r->size)
                r->buf[0] = '\0';
            rep_add(r, "%s:%lu: %s %s %s\n"
                        "  a        %s\n"
                        "  b        %s\n"
                        "  n        %lld\n"
                        "  expected %s flags 0x%02x\n"
                        "  got      %s flags 0x%02x\n",
                    path, lineno, f->name, cft_tr_name(fn), rnames[rnd],
                    ha, binary ? hb : "-", (long long)(has_n ? enn : 0),
                    hw, (unsigned)want_flags,
                    hg, (unsigned)got_flags);
            return CFT_ERR_INTERNAL;
        }

        if (ncases == ccap) {
            size_t want = ccap ? ccap * 2 : 4096;
            cft_tr_case *bigger = (cft_tr_case *)realloc(
                cases, want * sizeof *cases);
            if (!bigger) {
                fclose(fp);
                free(cases);
                rep_add(r, "out of memory holding %s\n", path);
                return CFT_ERR_OUT_OF_MEMORY;
            }
            cases = bigger;
            ccap = want;
        }
        cases[ncases].fn = fn;
        cases[ncases].nn = enn;
        cases[ncases].flags = want_flags;
        memcpy(cases[ncases].a, ea, (size_t)esz);
        memcpy(cases[ncases].b, eb, (size_t)esz);
        memcpy(cases[ncases].d, want_d, (size_t)esz);
        ncases++;
    }
    fclose(fp);

    arr = transcend_array_pass(dev, fi, ri, esz, cases, ncases, path, r,
                               rnames);
    free(cases);
    return arr;
}

/* ---- the augmented arithmetic sets (754-2019 9.5) ------------------ *
 *
 * A third schema, and the first with TWO outputs per case: an augmented
 * operation returns the rounded result AND the error that rounding
 * made, so a line carries "r" and "e" where every other set carries
 * "d". There is also no "rnd" field, and its absence is normative
 * rather than an omission - 9.5 fixes the rounding to
 * roundTiesTowardZero, which is not one of the five attributes, so
 * there is nothing to record and there is one file per format instead
 * of one per attribute.
 *
 * Replayed the same two ways as everything else: one element at a time,
 * where a sticky flag word means exactly one case, and then as whole
 * arrays, which is the only thing here that exercises the batch loop
 * and the flag OR.
 */

typedef struct {
    int      fn;                /* index into AUG_NAMES */
    uint8_t  a[MAX_ELEM], b[MAX_ELEM], r[MAX_ELEM], e[MAX_ELEM];
    uint32_t flags;
} cft_aug_case;

#define AUG_COUNT 3
static const char *const AUG_NAMES[AUG_COUNT] = {
    "augmentedAddition", "augmentedSubtraction", "augmentedMultiplication"
};

static int aug_from_name(const char *s)
{
    int i;
    for (i = 0; i < AUG_COUNT; i++)
        if (strcmp(AUG_NAMES[i], s) == 0)
            return i;
    return -1;
}

static cft_status aug_apply(cft_device *dev, int fn, cft_format fmt,
                            const void *a, const void *b, void *r, void *e,
                            size_t n, uint32_t *flags)
{
    switch (fn) {
    case 0:  return cft_augmented_add(dev, fmt, a, b, r, e, n, flags);
    case 1:  return cft_augmented_sub(dev, fmt, a, b, r, e, n, flags);
    default: return cft_augmented_mul(dev, fmt, a, b, r, e, n, flags);
    }
}

static cft_status augmented_array_pass(cft_device *dev, int fi, int esz,
                                       const cft_aug_case *cases,
                                       size_t ncases, const char *path,
                                       rep *rp)
{
    const cft_fmt_desc *f = &cft_sf_formats[fi];
    uint8_t *a = NULL, *b = NULL, *gr = NULL, *ge = NULL;
    cft_status ret = CFT_OK;
    int fn;

    if (ncases == 0)
        return CFT_OK;
    a  = (uint8_t *)malloc(ncases * (size_t)esz);
    b  = (uint8_t *)malloc(ncases * (size_t)esz);
    gr = (uint8_t *)malloc(ncases * (size_t)esz);
    ge = (uint8_t *)malloc(ncases * (size_t)esz);
    if (!a || !b || !gr || !ge) {
        free(a); free(b); free(gr); free(ge);
        return CFT_ERR_OUT_OF_MEMORY;
    }

    for (fn = 0; fn < AUG_COUNT && ret == CFT_OK; fn++) {
        size_t k = 0, i, batch;
        uint32_t want_flags = 0, got_flags = 0;
        cft_status st;

        for (i = 0; i < ncases; i++) {
            if (cases[i].fn != fn)
                continue;
            memcpy(a + k * (size_t)esz, cases[i].a, (size_t)esz);
            memcpy(b + k * (size_t)esz, cases[i].b, (size_t)esz);
            want_flags |= cases[i].flags;
            k++;
        }
        if (k == 0)
            continue;
        batch = k;

        memset(gr, 0, k * (size_t)esz);
        memset(ge, 0, k * (size_t)esz);
        st = aug_apply(dev, fn, (cft_format)fi, a, b, gr, ge, k, &got_flags);
        if (st != CFT_OK) {
            rep_add(rp, "%s: array pass, %s x%lu: failed: %s\n",
                    path, AUG_NAMES[fn], (unsigned long)k, cft_strerror(st));
            ret = st;
            break;
        }

        k = 0;
        for (i = 0; i < ncases && ret == CFT_OK; i++) {
            if (cases[i].fn != fn)
                continue;
            if (memcmp(gr + k * (size_t)esz, cases[i].r, (size_t)esz) != 0 ||
                memcmp(ge + k * (size_t)esz, cases[i].e, (size_t)esz) != 0) {
                char hw[2 * MAX_ELEM + 3], hg[2 * MAX_ELEM + 3];
                char hw2[2 * MAX_ELEM + 3], hg2[2 * MAX_ELEM + 3];
                format_hex_elem(cases[i].r, esz, hw);
                format_hex_elem(gr + k * (size_t)esz, esz, hg);
                format_hex_elem(cases[i].e, esz, hw2);
                format_hex_elem(ge + k * (size_t)esz, esz, hg2);
                rp->used = 0;
                if (rp->buf && rp->size)
                    rp->buf[0] = '\0';
                rep_add(rp, "%s: ARRAY PASS element %lu of %lu (%s %s)\n"
                            "  expected r %s e %s\n"
                            "  got      r %s e %s\n"
                            "  the same case passes one element at a time, "
                            "so this is the batch loop\n",
                        path, (unsigned long)k, (unsigned long)batch,
                        f->name, AUG_NAMES[fn], hw, hw2, hg, hg2);
                ret = CFT_ERR_INTERNAL;
            }
            k++;
        }
        if (ret == CFT_OK && got_flags != want_flags) {
            rp->used = 0;
            if (rp->buf && rp->size)
                rp->buf[0] = '\0';
            rep_add(rp, "%s: ARRAY PASS flags for %s over %lu elements: "
                        "got 0x%02x, expected the OR of the cases 0x%02x\n",
                    path, AUG_NAMES[fn], (unsigned long)batch,
                    (unsigned)got_flags, (unsigned)want_flags);
            ret = CFT_ERR_INTERNAL;
        }
    }

    free(a); free(b); free(gr); free(ge);
    return ret;
}

static cft_status augmented_set(cft_device *dev, int fi, int esz,
                                const char *path, rep *rp, uint64_t *total)
{
    const cft_fmt_desc *f = &cft_sf_formats[fi];
    char line[LINE_MAX];
    unsigned long lineno = 0;
    cft_aug_case *cases = NULL;
    size_t ncases = 0, ccap = 0;
    cft_status arr;
    FILE *fp = fopen(path, "r");

    if (!fp)
        return CFT_OK;                    /* absent is not a failure */

    while (fgets(line, (int)sizeof line, fp)) {
        char tok[TOKEN_MAX];
        uint8_t ea[MAX_ELEM], eb[MAX_ELEM];
        uint8_t want_r[MAX_ELEM], want_e[MAX_ELEM];
        uint8_t got_r[MAX_ELEM], got_e[MAX_ELEM];
        uint32_t want_flags = 0, got_flags = 0;
        int fn = -1;
        cft_status st;

        lineno++;
        if (line[0] == '\n' || line[0] == '\r' || line[0] == '\0')
            continue;
        {
            const char *why = NULL;
            if (field_string(line, "fn", tok, sizeof tok))
                why = "no \"fn\" field - this is not an augmented set";
            else if ((fn = aug_from_name(tok)) < 0)
                why = "unknown augmented operation name";
            else if (field_u32(line, "flags", &want_flags))
                why = "no \"flags\" field";
            if (why) {
                fclose(fp);
                free(cases);
                rep_add(rp, "%s:%lu: %s\n", path, lineno, why);
                return CFT_ERR_ARTIFACT;
            }
        }

#define AGET(key, dst)                                                   \
        if (field_string(line, key, tok, sizeof tok) ||                  \
            parse_hex_elem(tok, dst, esz)) {                             \
            fclose(fp);                                                  \
            free(cases);                                                 \
            rep_add(rp, "%s:%lu: bad \"%s\" field\n", path, lineno, key); \
            return CFT_ERR_ARTIFACT;                                     \
        }
        AGET("a", ea)
        AGET("b", eb)
        AGET("r", want_r)
        AGET("e", want_e)
#undef AGET

        memset(got_r, 0, (size_t)esz);
        memset(got_e, 0, (size_t)esz);
        st = aug_apply(dev, fn, (cft_format)fi, ea, eb, got_r, got_e, 1,
                       &got_flags);
        if (st != CFT_OK) {
            fclose(fp);
            free(cases);
            rep_add(rp, "%s:%lu: %s failed: %s\n", path, lineno,
                    AUG_NAMES[fn], cft_strerror(st));
            return st;
        }
        (*total)++;

        if (memcmp(got_r, want_r, (size_t)esz) != 0 ||
            memcmp(got_e, want_e, (size_t)esz) != 0 ||
            got_flags != want_flags) {
            char ha[2 * MAX_ELEM + 3], hb[2 * MAX_ELEM + 3];
            char hwr[2 * MAX_ELEM + 3], hwe[2 * MAX_ELEM + 3];
            char hgr[2 * MAX_ELEM + 3], hge[2 * MAX_ELEM + 3];
            fclose(fp);
            free(cases);
            format_hex_elem(ea, esz, ha);
            format_hex_elem(eb, esz, hb);
            format_hex_elem(want_r, esz, hwr);
            format_hex_elem(want_e, esz, hwe);
            format_hex_elem(got_r, esz, hgr);
            format_hex_elem(got_e, esz, hge);
            rp->used = 0;
            if (rp->buf && rp->size)
                rp->buf[0] = '\0';
            rep_add(rp, "%s:%lu: %s %s\n"
                        "  a        %s\n"
                        "  b        %s\n"
                        "  expected r %s e %s flags 0x%02x\n"
                        "  got      r %s e %s flags 0x%02x\n",
                    path, lineno, f->name, AUG_NAMES[fn], ha, hb,
                    hwr, hwe, (unsigned)want_flags,
                    hgr, hge, (unsigned)got_flags);
            return CFT_ERR_INTERNAL;
        }

        if (ncases == ccap) {
            size_t want = ccap ? ccap * 2 : 4096;
            cft_aug_case *bigger = (cft_aug_case *)realloc(
                cases, want * sizeof *cases);
            if (!bigger) {
                fclose(fp);
                free(cases);
                rep_add(rp, "out of memory holding %s\n", path);
                return CFT_ERR_OUT_OF_MEMORY;
            }
            cases = bigger;
            ccap = want;
        }
        cases[ncases].fn = fn;
        cases[ncases].flags = want_flags;
        memcpy(cases[ncases].a, ea, (size_t)esz);
        memcpy(cases[ncases].b, eb, (size_t)esz);
        memcpy(cases[ncases].r, want_r, (size_t)esz);
        memcpy(cases[ncases].e, want_e, (size_t)esz);
        ncases++;
    }
    fclose(fp);

    arr = augmented_array_pass(dev, fi, esz, cases, ncases, path, rp);
    free(cases);
    return arr;
}

/* ---- the reduction sets ------------------------------------------- *
 *
 * The seven reductions of 754-2019 9.4, in their own schema and their
 * own files. A case is a whole VECTOR and one answer - two answers for
 * the three scaled products, which return a (significand, scale) pair -
 * so it fits neither of the schemas above.
 *
 * There is no second array pass here, and none is needed: a reduction
 * case IS an array call, so the device backend's partitioning - which
 * is what the array pass exists to reach - is exercised by the first
 * pass. The flags stay exact per case for the same reason, since one
 * case is one call rather than a batch whose flags are an OR.
 */

#define RD_SUM        0
#define RD_DOT        1
#define RD_SUMSQ      2
#define RD_SUMABS     3
#define RD_PROD       4
#define RD_PROD_SUM   5
#define RD_PROD_DIFF  6

static int reduce_fn_from_name(const char *s)
{
    static const char *const names[7] = {
        "sum", "dot", "sumsq", "sumabs",
        "scaled_prod", "scaled_prod_sum", "scaled_prod_diff"
    };
    int i;
    for (i = 0; i < 7; i++)
        if (strcmp(names[i], s) == 0)
            return i;
    return -1;
}

static const char *reduce_fn_name(int fn)
{
    switch (fn) {
    case RD_SUM:       return "sum";
    case RD_DOT:       return "dot";
    case RD_SUMSQ:     return "sumsq";
    case RD_SUMABS:    return "sumabs";
    case RD_PROD:      return "scaled_prod";
    case RD_PROD_SUM:  return "scaled_prod_sum";
    case RD_PROD_DIFF: return "scaled_prod_diff";
    }
    return "?";
}

static int reduce_fn_binary(int fn)
{
    return fn == RD_DOT || fn == RD_PROD_SUM || fn == RD_PROD_DIFF;
}

static int reduce_fn_scaled(int fn)
{
    return fn >= RD_PROD;
}

static cft_status reduce_set(cft_device *dev, int fi, int esz,
                             const char *path, rep *r,
                             const char *const *rnames, uint64_t *total)
{
    const cft_fmt_desc *f = &cft_sf_formats[fi];
    rline L;
    unsigned long lineno = 0;
    uint8_t *va = NULL, *vb = NULL;
    size_t vcap = 0;
    cft_status ret = CFT_OK;
    FILE *fp = fopen(path, "r");
    int got;

    if (!fp)
        return CFT_OK;                    /* absent is not a failure */

    L.buf = NULL;
    L.cap = 0;

    while ((got = rline_get(&L, fp)) == 1) {
        char tok[TOKEN_MAX];
        const char *line = L.buf;
        uint8_t want_d[MAX_ELEM], got_d[MAX_ELEM];
        uint32_t want_flags = 0, got_flags = 0, nfield = 0;
        int64_t want_sf = 0, got_sf = 0;
        size_t n, na = 0, nb = 0;
        int fn = -1, rnd = -1;
        cft_status st;

        lineno++;
        if (line[0] == '\n' || line[0] == '\r' || line[0] == '\0')
            continue;

        {
            const char *why = NULL;
            if (field_string(line, "fn", tok, sizeof tok))
                why = "no \"fn\" field - this is not a reduction set";
            else if ((fn = reduce_fn_from_name(tok)) < 0)
                why = "unknown reduction name";
            else if (field_string(line, "rnd", tok, sizeof tok))
                why = "no \"rnd\" field";
            else if ((rnd = rnd_from_name(tok)) < 0)
                why = "unknown rounding attribute";
            else if (field_u32(line, "n", &nfield))
                why = "no \"n\" field - a reduction case is a vector and "
                      "its length is part of the case";
            else if (field_u32(line, "flags", &want_flags))
                why = "no \"flags\" field";
            if (why) {
                rep_add(r, "%s:%lu: %s\n", path, lineno, why);
                ret = CFT_ERR_ARTIFACT;
                break;
            }
        }
        n = (size_t)nfield;

        if (n > vcap) {
            size_t want = n ? n : 1;
            uint8_t *ga = (uint8_t *)realloc(va, want * (size_t)esz);
            uint8_t *gb = (uint8_t *)realloc(vb, want * (size_t)esz);
            if (ga)
                va = ga;
            if (gb)
                vb = gb;
            if (!ga || !gb) {
                rep_add(r, "out of memory holding a %lu-element case "
                           "from %s\n", (unsigned long)n, path);
                ret = CFT_ERR_OUT_OF_MEMORY;
                break;
            }
            vcap = want;
        }

        if (field_hex_array(line, "a", va, esz, vcap, &na) || na != n) {
            rep_add(r, "%s:%lu: bad \"a\" field, or its length disagrees "
                       "with \"n\"\n", path, lineno);
            ret = CFT_ERR_ARTIFACT;
            break;
        }
        if (reduce_fn_binary(fn) &&
            (field_hex_array(line, "b", vb, esz, vcap, &nb) || nb != n)) {
            rep_add(r, "%s:%lu: bad \"b\" field, or its length disagrees "
                       "with \"n\"\n", path, lineno);
            ret = CFT_ERR_ARTIFACT;
            break;
        }

        if (reduce_fn_scaled(fn)) {
            if (field_string(line, "pr", tok, sizeof tok) ||
                parse_hex_elem(tok, want_d, esz) ||
                field_i64(line, "sf", &want_sf)) {
                rep_add(r, "%s:%lu: a scaled product's case needs both "
                           "\"pr\" and \"sf\" - it returns a pair\n",
                        path, lineno);
                ret = CFT_ERR_ARTIFACT;
                break;
            }
        } else if (field_string(line, "d", tok, sizeof tok) ||
                   parse_hex_elem(tok, want_d, esz)) {
            rep_add(r, "%s:%lu: bad \"d\" field\n", path, lineno);
            ret = CFT_ERR_ARTIFACT;
            break;
        }

        memset(got_d, 0, (size_t)esz);
        switch (fn) {
        case RD_SUM:
            st = cft_reduce(dev, CFT_SUM, (cft_format)fi, (cft_round)rnd,
                            va, NULL, got_d, n, &got_flags, NULL);
            break;
        case RD_DOT:
            st = cft_reduce(dev, CFT_DOT, (cft_format)fi, (cft_round)rnd,
                            va, vb, got_d, n, &got_flags, NULL);
            break;
        case RD_SUMSQ:
            st = cft_reduce(dev, CFT_SUMSQ, (cft_format)fi, (cft_round)rnd,
                            va, NULL, got_d, n, &got_flags, NULL);
            break;
        case RD_SUMABS:
            st = cft_reduce(dev, CFT_SUMABS, (cft_format)fi, (cft_round)rnd,
                            va, NULL, got_d, n, &got_flags, NULL);
            break;
        case RD_PROD:
            st = cft_scaled_prod(dev, (cft_format)fi, (cft_round)rnd,
                                 n ? va : NULL, got_d, &got_sf, n,
                                 &got_flags);
            break;
        case RD_PROD_SUM:
            st = cft_scaled_prod_sum(dev, (cft_format)fi, (cft_round)rnd,
                                     n ? va : NULL, n ? vb : NULL, got_d,
                                     &got_sf, n, &got_flags);
            break;
        default:
            st = cft_scaled_prod_diff(dev, (cft_format)fi, (cft_round)rnd,
                                      n ? va : NULL, n ? vb : NULL, got_d,
                                      &got_sf, n, &got_flags);
            break;
        }
        if (st != CFT_OK) {
            rep_add(r, "%s:%lu: %s failed: %s\n", path, lineno,
                    reduce_fn_name(fn), cft_strerror(st));
            ret = st;
            break;
        }
        (*total)++;

        if (memcmp(got_d, want_d, (size_t)esz) != 0 ||
            got_flags != want_flags || got_sf != want_sf) {
            char hw[2 * MAX_ELEM + 3], hg[2 * MAX_ELEM + 3];
            format_hex_elem(want_d, esz, hw);
            format_hex_elem(got_d, esz, hg);
            r->used = 0;
            if (r->buf && r->size)
                r->buf[0] = '\0';
            rep_add(r, "%s:%lu: %s %s %s over %lu elements\n"
                        "  expected %s scale %lld flags 0x%02x\n"
                        "  got      %s scale %lld flags 0x%02x\n",
                    path, lineno, f->name, reduce_fn_name(fn), rnames[rnd],
                    (unsigned long)n,
                    hw, (long long)want_sf, (unsigned)want_flags,
                    hg, (long long)got_sf, (unsigned)got_flags);
            ret = CFT_ERR_INTERNAL;
            break;
        }
    }
    if (got < 0 && ret == CFT_OK) {
        rep_add(r, "out of memory reading %s\n", path);
        ret = CFT_ERR_OUT_OF_MEMORY;
    }

    free(L.buf);
    free(va);
    free(vb);
    fclose(fp);
    return ret;
}

/* ---- the character sets -------------------------------------------- *
 *
 * A third schema in a third family of files, for the third time the
 * same reason: a clause-5.12 case names a SEQUENCE, and neither the
 * opcode sets nor the transcendental ones have a field to put one in.
 * A consumer that predates the 0.6 step skips these files rather than
 * failing a line.
 *
 * Two things here are unlike every other set. The lines are UNBOUNDED -
 * the exact decimal of the smallest binary256 subnormal is a
 * 183,000-character sequence, so the reader grows its buffer instead
 * of refusing at LINE_MAX. And some cases assert a REFUSAL rather than
 * a value: a sequence outside the syntax must be rejected, which is as
 * much a part of the contract as any encoding and the one part a set
 * of encodings cannot express.
 *
 * Replayed twice like the others, and for the same reason: one case at
 * a time pins each case's flags exactly, then the from_ conversions -
 * which are the batch-shaped half of this API - run again as arrays so
 * the batch loop and the flag OR are exercised. The to_ conversions
 * are per-element by design (cft.h says why), so their second pass is
 * the one the first pass already is.
 */

typedef enum {
    CH_FROM_DEC, CH_FROM_HEX, CH_TO_DEC, CH_TO_HEX,
    CH_GET_PAYLOAD, CH_SET_PAYLOAD, CH_SET_PAYLOAD_SIG, CH_COUNT
} ch_kind;

static const char *const CH_NAME[CH_COUNT] = {
    "from_decimal", "from_hex", "to_decimal", "to_hex",
    "get_payload", "set_payload", "set_payload_signaling"
};

typedef struct {
    int      kind;
    char    *s;                      /* owned; the sequence to read in */
    uint8_t  d[MAX_ELEM];
    uint32_t flags;
} ch_case;

/* A line of any length. Returns 1 on a line, 0 at end of file. */
static int read_line(FILE *fp, char **buf, size_t *cap, size_t *len)
{
    size_t used = 0;
    int c;
    if (*cap == 0) {
        *cap = 4096;
        *buf = (char *)malloc(*cap);
        if (!*buf)
            return 0;
    }
    while ((c = fgetc(fp)) != EOF) {
        if (used + 2 > *cap) {
            size_t want = *cap * 2;
            char *bigger = (char *)realloc(*buf, want);
            if (!bigger)
                return 0;
            *buf = bigger;
            *cap = want;
        }
        if (c == '\n')
            break;
        (*buf)[used++] = (char)c;
    }
    (*buf)[used] = '\0';
    *len = used;
    return used > 0 || c != EOF;
}

/* A string field, allocated. The generator asserts that no sequence it
 * writes needs a JSON escape, so reading to the closing quote is the
 * whole of the parse. */
static char *field_string_alloc(const char *line, const char *key)
{
    const char *p = find_field(line, key), *q;
    char *out;
    size_t n;
    if (!p)
        return NULL;
    while (*p == ' ' || *p == '\t')
        p++;
    if (*p != '"')
        return NULL;
    p++;
    q = p;
    while (*q && *q != '"')
        q++;
    if (*q != '"')
        return NULL;
    n = (size_t)(q - p);
    out = (char *)malloc(n + 1);
    if (!out)
        return NULL;
    memcpy(out, p, n);
    out[n] = '\0';
    return out;
}

static int ch_from_name(const char *s)
{
    int i;
    for (i = 0; i < CH_COUNT; i++)
        if (strcmp(CH_NAME[i], s) == 0)
            return i;
    return -1;
}

/* One to_ conversion through the two-call sizing protocol, into a
 * freshly allocated buffer. */
static cft_status ch_write(cft_device *dev, int fi, int rnd, int kind,
                           const uint8_t *a, size_t digits, char **out,
                           uint32_t *flags)
{
    size_t need = 0;
    cft_status st;
    char *buf;

    *out = NULL;
    *flags = 0;
    if (kind == CH_TO_DEC)
        st = cft_to_decimal_char(dev, (cft_format)fi, (cft_round)rnd, a,
                                 digits, NULL, 0, &need, flags);
    else
        st = cft_to_hex_char(dev, (cft_format)fi, a, NULL, 0, &need);
    if (st != CFT_ERR_INVALID_ARGUMENT || need < 2)
        return st == CFT_OK ? CFT_ERR_INTERNAL : st;
    buf = (char *)malloc(need);
    if (!buf)
        return CFT_ERR_OUT_OF_MEMORY;
    if (kind == CH_TO_DEC)
        st = cft_to_decimal_char(dev, (cft_format)fi, (cft_round)rnd, a,
                                 digits, buf, need, &need, flags);
    else
        st = cft_to_hex_char(dev, (cft_format)fi, a, buf, need, &need);
    if (st != CFT_OK) {
        free(buf);
        return st;
    }
    *out = buf;
    return CFT_OK;
}

/* The array pass over the from_ conversions: the same sequences again,
 * a whole file at a time, so the batch loop and the flag OR run. */
static cft_status character_array_pass(cft_device *dev, int fi, int rnd,
                                       int esz, const ch_case *cases,
                                       size_t ncases, const char *path,
                                       rep *r, const char *const *rnames)
{
    const cft_fmt_desc *f = &cft_sf_formats[fi];
    cft_status ret = CFT_OK;
    int kind;

    for (kind = CH_FROM_DEC; kind <= CH_FROM_HEX && ret == CFT_OK; kind++) {
        const char **in = NULL;
        uint8_t *got = NULL;
        uint32_t want_flags = 0, got_flags = 0;
        size_t k = 0, i, bad = 0;
        cft_status st;

        for (i = 0; i < ncases; i++)
            if (cases[i].kind == kind)
                k++;
        if (k == 0)
            continue;
        in = (const char **)malloc(k * sizeof *in);
        got = (uint8_t *)malloc(k * (size_t)esz);
        if (!in || !got) {
            free((void *)in);
            free(got);
            return CFT_ERR_OUT_OF_MEMORY;
        }
        k = 0;
        for (i = 0; i < ncases; i++) {
            if (cases[i].kind != kind)
                continue;
            in[k] = cases[i].s;
            want_flags |= cases[i].flags;
            k++;
        }
        memset(got, 0, k * (size_t)esz);
        st = kind == CH_FROM_DEC
             ? cft_from_decimal_char(dev, (cft_format)fi, (cft_round)rnd,
                                     in, got, k, &bad, &got_flags)
             : cft_from_hex_char(dev, (cft_format)fi, (cft_round)rnd,
                                 in, got, k, &bad, &got_flags);
        if (st != CFT_OK) {
            rep_add(r, "%s: array pass, %s x%lu: failed at element %lu "
                       "(%.80s): %s\n", path, CH_NAME[kind],
                    (unsigned long)k, (unsigned long)bad,
                    bad < k ? in[bad] : "?", cft_strerror(st));
            ret = st;
        }
        k = 0;
        for (i = 0; i < ncases && ret == CFT_OK; i++) {
            if (cases[i].kind != kind)
                continue;
            if (memcmp(got + k * (size_t)esz, cases[i].d, (size_t)esz) != 0) {
                char hw[2 * MAX_ELEM + 3], hg[2 * MAX_ELEM + 3];
                format_hex_elem(cases[i].d, esz, hw);
                format_hex_elem(got + k * (size_t)esz, esz, hg);
                r->used = 0;
                if (r->buf && r->size)
                    r->buf[0] = '\0';
                rep_add(r, "%s: ARRAY PASS element %lu (%s %s %s) %.80s\n"
                           "  expected %s\n  got      %s\n"
                           "  the same case passes one at a time, so this "
                           "is the batch loop\n",
                        path, (unsigned long)k, f->name, CH_NAME[kind],
                        rnames[rnd], cases[i].s, hw, hg);
                ret = CFT_ERR_INTERNAL;
            }
            k++;
        }
        if (ret == CFT_OK && got_flags != want_flags) {
            r->used = 0;
            if (r->buf && r->size)
                r->buf[0] = '\0';
            rep_add(r, "%s: ARRAY PASS flags for %s %s over %lu sequences: "
                       "got 0x%02x, expected the OR of the cases 0x%02x\n",
                    path, CH_NAME[kind], rnames[rnd], (unsigned long)k,
                    (unsigned)got_flags, (unsigned)want_flags);
            ret = CFT_ERR_INTERNAL;
        }
        free((void *)in);
        free(got);
    }
    return ret;
}

static void ch_free(ch_case *cases, size_t n)
{
    size_t i;
    for (i = 0; i < n; i++)
        free(cases[i].s);
    free(cases);
}

static cft_status character_set(cft_device *dev, int fi, int ri, int esz,
                                const char *path, rep *r,
                                const char *const *rnames, uint64_t *total)
{
    const cft_fmt_desc *f = &cft_sf_formats[fi];
    char *line = NULL;
    size_t cap = 0, len = 0;
    unsigned long lineno = 0;
    ch_case *cases = NULL;
    size_t ncases = 0, ccases = 0;
    cft_status arr, ret = CFT_OK;
    FILE *fp = fopen(path, "r");

    if (!fp)
        return CFT_OK;                    /* absent is not a failure */

    while (ret == CFT_OK && read_line(fp, &line, &cap, &len)) {
        char tok[TOKEN_MAX];
        char *seq = NULL, *want_s = NULL, *got_s = NULL;
        uint8_t ea[MAX_ELEM], want_d[MAX_ELEM], got_d[MAX_ELEM];
        uint32_t want_flags = 0, got_flags = 0, digits = 0;
        int kind = -1, rnd = -1, refuse;
        const char *why = NULL;
        cft_status st;

        lineno++;
        if (len == 0)
            continue;
        refuse = find_field(line, "refuse") != NULL;
        if (field_string(line, "fn", tok, sizeof tok))
            why = "no \"fn\" field - this is not a character set";
        else if ((kind = ch_from_name(tok)) < 0)
            why = "unknown character-conversion name";
        else if (field_string(line, "rnd", tok, sizeof tok))
            why = "no \"rnd\" field";
        else if ((rnd = rnd_from_name(tok)) < 0)
            why = "unknown rounding attribute";
        else if (!refuse && field_u32(line, "flags", &want_flags))
            why = "no \"flags\" field";
        if (why) {
            rep_add(r, "%s:%lu: %s\n", path, lineno, why);
            ret = CFT_ERR_ARTIFACT;
            break;
        }

        if (kind == CH_FROM_DEC || kind == CH_FROM_HEX) {
            seq = field_string_alloc(line, "s");
            if (!seq || (!refuse &&
                         (field_string(line, "d", tok, sizeof tok) ||
                          parse_hex_elem(tok, want_d, esz)))) {
                free(seq);
                rep_add(r, "%s:%lu: bad \"s\" or \"d\" field\n", path,
                        lineno);
                ret = CFT_ERR_ARTIFACT;
                break;
            }
            memset(got_d, 0, (size_t)esz);
            got_flags = 0;
            {
                const char *one = seq;
                size_t bad = 0;
                st = kind == CH_FROM_DEC
                     ? cft_from_decimal_char(dev, (cft_format)fi,
                                             (cft_round)rnd, &one, got_d, 1,
                                             &bad, &got_flags)
                     : cft_from_hex_char(dev, (cft_format)fi, (cft_round)rnd,
                                         &one, got_d, 1, &bad, &got_flags);
            }
            (*total)++;
            if (refuse) {
                /* The contract's refusal: a sequence outside 5.12's
                 * syntax must be rejected rather than guessed at. */
                if (st == CFT_OK) {
                    r->used = 0;
                    if (r->buf && r->size)
                        r->buf[0] = '\0';
                    rep_add(r, "%s:%lu: %s %s ACCEPTED a sequence that is "
                               "not in the syntax: %.120s\n",
                            path, lineno, f->name, CH_NAME[kind], seq);
                    ret = CFT_ERR_INTERNAL;
                }
                free(seq);
                if (ret != CFT_OK)
                    break;
                continue;
            }
            if (st != CFT_OK) {
                rep_add(r, "%s:%lu: %s failed on %.120s: %s\n", path, lineno,
                        CH_NAME[kind], seq, cft_strerror(st));
                free(seq);
                ret = st;
                break;
            }
            if (memcmp(got_d, want_d, (size_t)esz) != 0 ||
                got_flags != want_flags) {
                char hw[2 * MAX_ELEM + 3], hg[2 * MAX_ELEM + 3];
                format_hex_elem(want_d, esz, hw);
                format_hex_elem(got_d, esz, hg);
                r->used = 0;
                if (r->buf && r->size)
                    r->buf[0] = '\0';
                rep_add(r, "%s:%lu: %s %s %s\n  s        %.200s\n"
                           "  expected %s flags 0x%02x\n"
                           "  got      %s flags 0x%02x\n",
                        path, lineno, f->name, CH_NAME[kind], rnames[rnd],
                        seq, hw, (unsigned)want_flags, hg,
                        (unsigned)got_flags);
                free(seq);
                ret = CFT_ERR_INTERNAL;
                break;
            }
            if (ncases == ccases) {
                size_t want = ccases ? ccases * 2 : 512;
                ch_case *bigger = (ch_case *)realloc(cases,
                                                     want * sizeof *cases);
                if (!bigger) {
                    free(seq);
                    ret = CFT_ERR_OUT_OF_MEMORY;
                    break;
                }
                cases = bigger;
                ccases = want;
            }
            cases[ncases].kind = kind;
            cases[ncases].s = seq;
            cases[ncases].flags = want_flags;
            memcpy(cases[ncases].d, want_d, (size_t)esz);
            ncases++;
            continue;
        }

        /* Everything else reads an encoding. */
        if (field_string(line, "a", tok, sizeof tok) ||
            parse_hex_elem(tok, ea, esz)) {
            rep_add(r, "%s:%lu: bad \"a\" field\n", path, lineno);
            ret = CFT_ERR_ARTIFACT;
            break;
        }

        if (kind == CH_TO_DEC || kind == CH_TO_HEX) {
            if (kind == CH_TO_DEC && field_u32(line, "digits", &digits)) {
                rep_add(r, "%s:%lu: no \"digits\" field\n", path, lineno);
                ret = CFT_ERR_ARTIFACT;
                break;
            }
            want_s = field_string_alloc(line, "s");
            if (!want_s) {
                rep_add(r, "%s:%lu: bad \"s\" field\n", path, lineno);
                ret = CFT_ERR_ARTIFACT;
                break;
            }
            st = ch_write(dev, fi, rnd, kind, ea, (size_t)digits, &got_s,
                          &got_flags);
            (*total)++;
            if (st != CFT_OK) {
                rep_add(r, "%s:%lu: %s failed: %s\n", path, lineno,
                        CH_NAME[kind], cft_strerror(st));
                free(want_s);
                ret = st;
                break;
            }
            if (strcmp(got_s, want_s) != 0 || got_flags != want_flags) {
                char ha[2 * MAX_ELEM + 3];
                format_hex_elem(ea, esz, ha);
                r->used = 0;
                if (r->buf && r->size)
                    r->buf[0] = '\0';
                rep_add(r, "%s:%lu: %s %s %s a=%s digits=%lu\n"
                           "  expected %.200s flags 0x%02x\n"
                           "  got      %.200s flags 0x%02x\n",
                        path, lineno, f->name, CH_NAME[kind], rnames[rnd],
                        ha, (unsigned long)digits, want_s,
                        (unsigned)want_flags, got_s, (unsigned)got_flags);
                ret = CFT_ERR_INTERNAL;
            }
            free(want_s);
            free(got_s);
            if (ret != CFT_OK)
                break;
            continue;
        }

        /* The three 9.7 payload operations: no attribute, no flags. */
        if (field_string(line, "d", tok, sizeof tok) ||
            parse_hex_elem(tok, want_d, esz)) {
            rep_add(r, "%s:%lu: bad \"d\" field\n", path, lineno);
            ret = CFT_ERR_ARTIFACT;
            break;
        }
        memset(got_d, 0, (size_t)esz);
        st = kind == CH_GET_PAYLOAD
             ? cft_get_payload(dev, (cft_format)fi, ea, got_d, 1)
             : (kind == CH_SET_PAYLOAD
                ? cft_set_payload(dev, (cft_format)fi, ea, got_d, 1)
                : cft_set_payload_signaling(dev, (cft_format)fi, ea,
                                            got_d, 1));
        (*total)++;
        if (st != CFT_OK) {
            rep_add(r, "%s:%lu: %s failed: %s\n", path, lineno,
                    CH_NAME[kind], cft_strerror(st));
            ret = st;
            break;
        }
        if (memcmp(got_d, want_d, (size_t)esz) != 0) {
            char ha[2 * MAX_ELEM + 3], hw[2 * MAX_ELEM + 3];
            char hg[2 * MAX_ELEM + 3];
            format_hex_elem(ea, esz, ha);
            format_hex_elem(want_d, esz, hw);
            format_hex_elem(got_d, esz, hg);
            r->used = 0;
            if (r->buf && r->size)
                r->buf[0] = '\0';
            rep_add(r, "%s:%lu: %s %s\n  a        %s\n"
                       "  expected %s\n  got      %s\n",
                    path, lineno, f->name, CH_NAME[kind], ha, hw, hg);
            ret = CFT_ERR_INTERNAL;
            break;
        }
    }
    fclose(fp);
    free(line);
    if (ret != CFT_OK) {
        ch_free(cases, ncases);
        return ret;
    }
    arr = character_array_pass(dev, fi, ri, esz, cases, ncases, path, r,
                               rnames);
    ch_free(cases, ncases);
    return arr;
}

/* ---- the replay --------------------------------------------------- */

/* ---- the magnitude min/max sets (754-2019 9.6) --------------------- *
 *
 * A sixth schema, and the simplest of them: two operands, one output,
 * one flag word, and NO "rnd" field. Its absence is normative, as it
 * is for the augmented sets and for a sharper reason - these four
 * operations select one of their operands rather than computing a
 * value, so there is no rounding for an attribute to direct and one
 * file per format is the whole set.
 *
 * "fn" carries 754's own spelling (minimumMagnitude and friends)
 * rather than this library's C names, so the file says what standard
 * it is a set for.
 *
 * Replayed the same two ways as everything else: one element at a
 * time, where the flag word means exactly one case, and then as whole
 * arrays, which is what exercises the batch loop and the flag OR.
 */

typedef struct {
    int      fn;                /* index into MM_NAMES */
    uint8_t  a[MAX_ELEM], b[MAX_ELEM], d[MAX_ELEM];
    uint32_t flags;
} cft_mm_case;

#define MM_COUNT 4
static const char *const MM_NAMES[MM_COUNT] = {
    "minimumMagnitude", "minimumMagnitudeNumber",
    "maximumMagnitude", "maximumMagnitudeNumber"
};

static int mm_from_name(const char *s)
{
    int i;
    for (i = 0; i < MM_COUNT; i++)
        if (strcmp(MM_NAMES[i], s) == 0)
            return i;
    return -1;
}

static cft_status mm_apply(cft_device *dev, int fn, cft_format fmt,
                           const void *a, const void *b, void *d,
                           size_t n, uint32_t *flags)
{
    switch (fn) {
    case 0:  return cft_min_mag(dev, fmt, a, b, d, n, flags);
    case 1:  return cft_minnum_mag(dev, fmt, a, b, d, n, flags);
    case 2:  return cft_max_mag(dev, fmt, a, b, d, n, flags);
    default: return cft_maxnum_mag(dev, fmt, a, b, d, n, flags);
    }
}

static cft_status minmaxmag_array_pass(cft_device *dev, int fi, int esz,
                                       const cft_mm_case *cases,
                                       size_t ncases, const char *path,
                                       rep *rp)
{
    const cft_fmt_desc *f = &cft_sf_formats[fi];
    uint8_t *a = NULL, *b = NULL, *gd = NULL;
    cft_status ret = CFT_OK;
    int fn;

    if (ncases == 0)
        return CFT_OK;
    a  = (uint8_t *)malloc(ncases * (size_t)esz);
    b  = (uint8_t *)malloc(ncases * (size_t)esz);
    gd = (uint8_t *)malloc(ncases * (size_t)esz);
    if (!a || !b || !gd) {
        free(a); free(b); free(gd);
        return CFT_ERR_OUT_OF_MEMORY;
    }

    for (fn = 0; fn < MM_COUNT && ret == CFT_OK; fn++) {
        size_t k = 0, i, batch;
        uint32_t want_flags = 0, got_flags = 0;
        cft_status st;

        for (i = 0; i < ncases; i++) {
            if (cases[i].fn != fn)
                continue;
            memcpy(a + k * (size_t)esz, cases[i].a, (size_t)esz);
            memcpy(b + k * (size_t)esz, cases[i].b, (size_t)esz);
            want_flags |= cases[i].flags;
            k++;
        }
        if (k == 0)
            continue;
        batch = k;

        memset(gd, 0, k * (size_t)esz);
        st = mm_apply(dev, fn, (cft_format)fi, a, b, gd, k, &got_flags);
        if (st != CFT_OK) {
            rep_add(rp, "%s: array pass, %s x%lu: failed: %s\n",
                    path, MM_NAMES[fn], (unsigned long)k, cft_strerror(st));
            ret = st;
            break;
        }

        k = 0;
        for (i = 0; i < ncases && ret == CFT_OK; i++) {
            if (cases[i].fn != fn)
                continue;
            if (memcmp(gd + k * (size_t)esz, cases[i].d, (size_t)esz) != 0) {
                char hw[2 * MAX_ELEM + 3], hg[2 * MAX_ELEM + 3];
                format_hex_elem(cases[i].d, esz, hw);
                format_hex_elem(gd + k * (size_t)esz, esz, hg);
                rp->used = 0;
                if (rp->buf && rp->size)
                    rp->buf[0] = '\0';
                rep_add(rp, "%s: ARRAY PASS element %lu of %lu (%s %s)\n"
                            "  expected %s\n"
                            "  got      %s\n"
                            "  the same case passes one element at a time, "
                            "so this is the batch loop\n",
                        path, (unsigned long)k, (unsigned long)batch,
                        f->name, MM_NAMES[fn], hw, hg);
                ret = CFT_ERR_INTERNAL;
            }
            k++;
        }
        if (ret == CFT_OK && got_flags != want_flags) {
            rp->used = 0;
            if (rp->buf && rp->size)
                rp->buf[0] = '\0';
            rep_add(rp, "%s: ARRAY PASS flags for %s over %lu elements: "
                        "got 0x%02x, expected the OR of the cases 0x%02x\n",
                    path, MM_NAMES[fn], (unsigned long)batch,
                    (unsigned)got_flags, (unsigned)want_flags);
            ret = CFT_ERR_INTERNAL;
        }
    }

    free(a); free(b); free(gd);
    return ret;
}

static cft_status minmaxmag_set(cft_device *dev, int fi, int esz,
                                const char *path, rep *rp, uint64_t *total)
{
    const cft_fmt_desc *f = &cft_sf_formats[fi];
    char line[LINE_MAX];
    unsigned long lineno = 0;
    cft_mm_case *cases = NULL;
    size_t ncases = 0, ccap = 0;
    cft_status arr;
    FILE *fp = fopen(path, "r");

    if (!fp)
        return CFT_OK;                    /* absent is not a failure */

    while (fgets(line, (int)sizeof line, fp)) {
        char tok[TOKEN_MAX];
        uint8_t ea[MAX_ELEM], eb[MAX_ELEM];
        uint8_t want_d[MAX_ELEM], got_d[MAX_ELEM];
        uint32_t want_flags = 0, got_flags = 0;
        int fn = -1;
        cft_status st;

        lineno++;
        if (line[0] == '\n' || line[0] == '\r' || line[0] == '\0')
            continue;
        {
            const char *why = NULL;
            if (field_string(line, "fn", tok, sizeof tok))
                why = "no \"fn\" field - this is not a magnitude min/max set";
            else if ((fn = mm_from_name(tok)) < 0)
                why = "unknown 9.6 magnitude operation name";
            else if (field_u32(line, "flags", &want_flags))
                why = "no \"flags\" field";
            if (why) {
                fclose(fp);
                free(cases);
                rep_add(rp, "%s:%lu: %s\n", path, lineno, why);
                return CFT_ERR_ARTIFACT;
            }
        }

#define MGET(key, dst)                                                   \
        if (field_string(line, key, tok, sizeof tok) ||                  \
            parse_hex_elem(tok, dst, esz)) {                             \
            fclose(fp);                                                  \
            free(cases);                                                 \
            rep_add(rp, "%s:%lu: bad \"%s\" field\n", path, lineno, key); \
            return CFT_ERR_ARTIFACT;                                     \
        }
        MGET("a", ea)
        MGET("b", eb)
        MGET("d", want_d)
#undef MGET

        memset(got_d, 0, (size_t)esz);
        st = mm_apply(dev, fn, (cft_format)fi, ea, eb, got_d, 1, &got_flags);
        if (st != CFT_OK) {
            fclose(fp);
            free(cases);
            rep_add(rp, "%s:%lu: %s failed: %s\n", path, lineno,
                    MM_NAMES[fn], cft_strerror(st));
            return st;
        }
        (*total)++;

        if (memcmp(got_d, want_d, (size_t)esz) != 0 ||
            got_flags != want_flags) {
            char ha[2 * MAX_ELEM + 3], hb[2 * MAX_ELEM + 3];
            char hw[2 * MAX_ELEM + 3], hg[2 * MAX_ELEM + 3];
            fclose(fp);
            free(cases);
            format_hex_elem(ea, esz, ha);
            format_hex_elem(eb, esz, hb);
            format_hex_elem(want_d, esz, hw);
            format_hex_elem(got_d, esz, hg);
            rp->used = 0;
            if (rp->buf && rp->size)
                rp->buf[0] = '\0';
            rep_add(rp, "%s:%lu: %s %s\n"
                        "  a        %s\n"
                        "  b        %s\n"
                        "  expected %s flags 0x%02x\n"
                        "  got      %s flags 0x%02x\n",
                    path, lineno, f->name, MM_NAMES[fn], ha, hb,
                    hw, (unsigned)want_flags, hg, (unsigned)got_flags);
            return CFT_ERR_INTERNAL;
        }

        if (ncases == ccap) {
            size_t want = ccap ? ccap * 2 : 4096;
            cft_mm_case *bigger = (cft_mm_case *)realloc(
                cases, want * sizeof *cases);
            if (!bigger) {
                fclose(fp);
                free(cases);
                rep_add(rp, "out of memory holding %s\n", path);
                return CFT_ERR_OUT_OF_MEMORY;
            }
            cases = bigger;
            ccap = want;
        }
        cases[ncases].fn = fn;
        cases[ncases].flags = want_flags;
        memcpy(cases[ncases].a, ea, (size_t)esz);
        memcpy(cases[ncases].b, eb, (size_t)esz);
        memcpy(cases[ncases].d, want_d, (size_t)esz);
        ncases++;
    }
    fclose(fp);

    arr = minmaxmag_array_pass(dev, fi, esz, cases, ncases, path, rp);
    free(cases);
    return arr;
}

CFT_API cft_status cft_conformance(cft_device *dev, const char *dir,
                                   char *report, size_t report_size,
                                   uint64_t *cases_checked)
{
    static const char *const rnames[5] = { "rne", "rtz", "rdn", "rup", "rmm" };
    rep r;
    uint64_t total = 0;
    int sets = 0, fi, ri;

    if (cases_checked)
        *cases_checked = 0;
    r.buf = report;
    r.size = report_size;
    r.used = 0;
    if (report && report_size)
        report[0] = '\0';

    if (!dev)
        return CFT_ERR_INVALID_ARGUMENT;
    if (!dir)
        dir = "vectors/out";

    for (fi = 0; fi < 4; fi++) {
        const cft_fmt_desc *f = &cft_sf_formats[fi];
        int esz = f->width / 8;
        int supported = cft_supports(dev, CFT_FMA, (cft_format)fi);

        for (ri = 0; ri < 5; ri++) {
            char path[512], line[LINE_MAX];
            FILE *fp;
            unsigned long lineno = 0;
            cft_case *cases = NULL;
            size_t ncases = 0, ccap = 0;
            cft_status arr;

            if (ri == 0)
                snprintf(path, sizeof path, "%s/%s.jsonl", dir, f->name);
            else
                snprintf(path, sizeof path, "%s/%s-%s.jsonl", dir, f->name,
                         rnames[ri]);

            fp = fopen(path, "r");
            if (!fp)
                continue;
            if (!supported) {
                fclose(fp);
                rep_add(&r, "%s: skipped, %s not on this device\n",
                        path, f->name);
                continue;
            }
            sets++;

            while (fgets(line, (int)sizeof line, fp)) {
                char tok[TOKEN_MAX];
                uint8_t ea[MAX_ELEM], eb[MAX_ELEM], ec[MAX_ELEM];
                uint8_t want_d[MAX_ELEM], got_d[MAX_ELEM];
                uint32_t want_flags = 0, got_flags = 0;
                int op = -1, rnd = -1;
                cft_status st;

                lineno++;
                if (line[0] == '\n' || line[0] == '\r' || line[0] == '\0')
                    continue;
                if (!strchr(line, '\n') && !feof(fp)) {
                    fclose(fp);
                    rep_add(&r, "%s:%lu: line longer than %d bytes\n",
                            path, lineno, LINE_MAX);
                    return CFT_ERR_ARTIFACT;
                }

                /* Say which field is wrong. The likeliest reason a set
                 * fails to parse is that it was generated before a
                 * field existed - "rnd" was added when the rounding
                 * attributes landed - and "not a conformance case"
                 * sends the reader looking for the wrong problem. */
                {
                    const char *why = NULL;
                    if (field_string(line, "op", tok, sizeof tok))
                        why = "no \"op\" field";
                    else if ((op = op_from_name(tok)) == -2)
                        why = "this set records an opcode as reserved that "
                              "the contract has since assigned - the case "
                              "would now exercise a different operation "
                              "than the one its answer was recorded for. "
                              "Regenerate the set.";
                    else if (op < 0)
                        why = "unknown opcode name";
                    else if (field_string(line, "rnd", tok, sizeof tok))
                        why = "no \"rnd\" field - regenerate this set";
                    else if ((rnd = rnd_from_name(tok)) < 0)
                        why = "unknown rounding attribute";
                    else if (field_u32(line, "flags", &want_flags))
                        why = "no \"flags\" field";
                    if (why) {
                        fclose(fp);
                        rep_add(&r, "%s:%lu: %s\n", path, lineno, why);
                        return CFT_ERR_ARTIFACT;
                    }
                }

#define GET(key, dst)                                                    \
                if (field_string(line, key, tok, sizeof tok) ||          \
                    parse_hex_elem(tok, dst, esz)) {                     \
                    fclose(fp);                                          \
                    rep_add(&r, "%s:%lu: bad \"%s\" field\n",            \
                            path, lineno, key);                          \
                    return CFT_ERR_ARTIFACT;                             \
                }
                GET("a", ea)
                GET("b", eb)
                GET("c", ec)
                GET("d", want_d)
#undef GET

                memset(got_d, 0, (size_t)esz);
                st = cft_run(dev, (cft_op)op, (cft_format)fi, (cft_round)rnd,
                             ea, eb, ec, got_d, 1, &got_flags, NULL);
                if (st != CFT_OK) {
                    fclose(fp);
                    rep_add(&r, "%s:%lu: cft_run failed: %s\n",
                            path, lineno, cft_strerror(st));
                    return st;
                }
                total++;

                if (memcmp(got_d, want_d, (size_t)esz) != 0 ||
                    got_flags != want_flags) {
                    char ha[2 * MAX_ELEM + 3], hb[2 * MAX_ELEM + 3];
                    char hc[2 * MAX_ELEM + 3], hw[2 * MAX_ELEM + 3];
                    char hg[2 * MAX_ELEM + 3];
                    fclose(fp);
                    format_hex_elem(ea, esz, ha);
                    format_hex_elem(eb, esz, hb);
                    format_hex_elem(ec, esz, hc);
                    format_hex_elem(want_d, esz, hw);
                    format_hex_elem(got_d, esz, hg);
                    r.used = 0;              /* the failure is the report */
                    if (r.buf && r.size)
                        r.buf[0] = '\0';
                    rep_add(&r, "%s:%lu: %s %s %s\n"
                                "  a        %s\n"
                                "  b        %s\n"
                                "  c        %s\n"
                                "  expected %s flags 0x%02x\n"
                                "  got      %s flags 0x%02x\n",
                            path, lineno, f->name, cft_op_name((cft_op)op),
                            rnames[rnd], ha, hb, hc,
                            hw, (unsigned)want_flags, hg, (unsigned)got_flags);
                    if (cases_checked)
                        *cases_checked = total;
                    free(cases);
                    return CFT_ERR_INTERNAL;
                }

                if (ncases == ccap) {
                    size_t want = ccap ? ccap * 2 : 4096;
                    cft_case *bigger = (cft_case *)realloc(
                        cases, want * sizeof *cases);
                    if (!bigger) {
                        fclose(fp);
                        free(cases);
                        rep_add(&r, "out of memory holding %s\n", path);
                        return CFT_ERR_OUT_OF_MEMORY;
                    }
                    cases = bigger;
                    ccap = want;
                }
                cases[ncases].op = op;
                cases[ncases].flags = want_flags;
                memcpy(cases[ncases].a, ea, (size_t)esz);
                memcpy(cases[ncases].b, eb, (size_t)esz);
                memcpy(cases[ncases].c, ec, (size_t)esz);
                memcpy(cases[ncases].d, want_d, (size_t)esz);
                ncases++;
            }
            fclose(fp);

            arr = array_pass(dev, fi, ri, esz, cases, ncases, path, &r,
                             rnames);
            free(cases);
            if (arr != CFT_OK) {
                if (cases_checked)
                    *cases_checked = total;
                return arr;
            }
        }

        /* The transcendental sets, in their own files and with their
         * own schema. A device that carries the format carries these
         * too: they are host operations, so there is no capability to
         * ask about. */
        for (ri = 0; ri < 5; ri++) {
            char path[512];
            cft_status st;
            FILE *probe;

            if (ri == 0)
                snprintf(path, sizeof path, "%s/%s-transcend.jsonl", dir,
                         f->name);
            else
                snprintf(path, sizeof path, "%s/%s-transcend-%s.jsonl", dir,
                         f->name, rnames[ri]);
            probe = fopen(path, "r");
            if (!probe)
                continue;
            fclose(probe);
            if (!supported) {
                rep_add(&r, "%s: skipped, %s not on this device\n",
                        path, f->name);
                continue;
            }
            sets++;
            st = transcend_set(dev, fi, ri, esz, path, &r, rnames, &total);
            if (st != CFT_OK) {
                if (cases_checked)
                    *cases_checked = total;
                return st;
            }
        }

        /* The augmented arithmetic set (754-2019 9.5): ONE file per
         * format, because the standard fixes the rounding and there is
         * no attribute to sweep. Two outputs per case. */
        {
            char path[512];
            cft_status st;
            FILE *probe;

            snprintf(path, sizeof path, "%s/%s-augmented.jsonl", dir,
                     f->name);
            probe = fopen(path, "r");
            if (probe) {
                fclose(probe);
                if (!supported) {
                    rep_add(&r, "%s: skipped, %s not on this device\n",
                            path, f->name);
                } else {
                    sets++;
                    st = augmented_set(dev, fi, esz, path, &r, &total);
                    if (st != CFT_OK) {
                        if (cases_checked)
                            *cases_checked = total;
                        return st;
                    }
                }
            }
        }

        /* The reduction sets, in their own files and their own schema.
         * A device that carries the format may still lack the
         * reduction opcode group, so these are skipped by name for
         * that too - a set that could not run must say so rather than
         * count as a pass. */
        for (ri = 0; ri < 5; ri++) {
            char path[512];
            cft_status st;
            FILE *probe;

            if (ri == 0)
                snprintf(path, sizeof path, "%s/%s-reduce.jsonl", dir,
                         f->name);
            else
                snprintf(path, sizeof path, "%s/%s-reduce-%s.jsonl", dir,
                         f->name, rnames[ri]);
            probe = fopen(path, "r");
            if (!probe)
                continue;
            fclose(probe);
            if (!supported) {
                rep_add(&r, "%s: skipped, %s not on this device\n",
                        path, f->name);
                continue;
            }
            if (!cft_supports(dev, CFT_SUM, (cft_format)fi)) {
                rep_add(&r, "%s: skipped, no reduction opcode group on "
                            "this device\n", path);
                continue;
            }
            sets++;
            st = reduce_set(dev, fi, esz, path, &r, rnames, &total);
            if (st != CFT_OK) {
                if (cases_checked)
                    *cases_checked = total;
                return st;
            }
        }

        /* The clause-5.12 character conversions and the clause-9.7
         * payload operations, in their own files and with their own
         * schema - a case here names a SEQUENCE, which neither of the
         * schemas above has a field for. Host operations, so there is
         * no capability to ask about beyond the format itself. */
        for (ri = 0; ri < 5; ri++) {
            char path[512];
            cft_status st;
            FILE *probe;

            if (ri == 0)
                snprintf(path, sizeof path, "%s/%s-character.jsonl", dir,
                         f->name);
            else
                snprintf(path, sizeof path, "%s/%s-character-%s.jsonl", dir,
                         f->name, rnames[ri]);
            probe = fopen(path, "r");
            if (!probe)
                continue;
            fclose(probe);
            if (!supported) {
                rep_add(&r, "%s: skipped, %s not on this device\n",
                        path, f->name);
                continue;
            }
            sets++;
            st = character_set(dev, fi, ri, esz, path, &r, rnames, &total);
            if (st != CFT_OK) {
                if (cases_checked)
                    *cases_checked = total;
                return st;
            }
        }

        /* The four magnitude forms of 754-2019 9.6: ONE file per
         * format, because these operations select an operand rather
         * than computing one and so consume no rounding attribute.
         * Host operations, so the only capability to ask about is the
         * format itself. */
        {
            char path[512];
            cft_status st;
            FILE *probe;

            snprintf(path, sizeof path, "%s/%s-minmaxmag.jsonl", dir,
                     f->name);
            probe = fopen(path, "r");
            if (probe) {
                fclose(probe);
                if (!supported) {
                    rep_add(&r, "%s: skipped, %s not on this device\n",
                            path, f->name);
                } else {
                    sets++;
                    st = minmaxmag_set(dev, fi, esz, path, &r, &total);
                    if (st != CFT_OK) {
                        if (cases_checked)
                            *cases_checked = total;
                        return st;
                    }
                }
            }
        }
    }

    if (cases_checked)
        *cases_checked = total;
    if (sets == 0) {
        rep_add(&r, "no vector sets found under %s - nothing was checked\n",
                dir);
        return CFT_ERR_ARTIFACT;
    }
    rep_add(&r, "%d set%s, %lu cases, all matching "
                "(the elementwise and transcendental sets replayed "
                "twice: one element at a time for exact flags, then as "
                "arrays so a device backend's partitioning is "
                "exercised, and the character sets likewise wherever the "
                "entry point takes an array. A reduction case IS an "
                "array call, so those "
                "sets are replayed once and their flags are exact "
                "already)\n",
            sets, sets == 1 ? "" : "s", (unsigned long)total);
    return CFT_OK;
}
