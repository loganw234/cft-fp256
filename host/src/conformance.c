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
    for (i = 0; i < 28; i++)
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
 * so ABI 0.4's eleven needed nothing here beyond the enum they were
 * added to - and a replayer built against 0.3 and handed a 0.4 set
 * refuses on the name of a function it does not know, which is the
 * refusal it should give.
 *
 * Replayed the same two ways as the opcode sets, for the same two
 * reasons: one element at a time pins each case's flags exactly, and
 * whole arrays exercise the batch loop and the flag OR.
 */

typedef struct {
    int      fn;
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
    cft_status ret = CFT_OK;
    int fn;

    if (ncases == 0)
        return CFT_OK;
    a   = (uint8_t *)malloc(ncases * (size_t)esz);
    b   = (uint8_t *)malloc(ncases * (size_t)esz);
    got = (uint8_t *)malloc(ncases * (size_t)esz);
    if (!a || !b || !got) {
        free(a); free(b); free(got);
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
            want_flags |= cases[i].flags;
            k++;
        }
        if (k == 0)
            continue;
        batch = k;

        memset(got, 0, k * (size_t)esz);
        st = cft_tr_apply(dev, fn, (cft_format)fi, (cft_round)rnd, a,
                          cft_tr_arity(fn) == 2 ? b : NULL, got, k,
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

    free(a); free(b); free(got);
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
        int fn = -1, rnd = -1, binary;
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

        memset(got_d, 0, (size_t)esz);
        st = cft_tr_apply(dev, fn, (cft_format)fi, (cft_round)rnd, ea,
                          binary ? eb : NULL, got_d, 1, &got_flags);
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
                        "  expected %s flags 0x%02x\n"
                        "  got      %s flags 0x%02x\n",
                    path, lineno, f->name, cft_tr_name(fn), rnames[rnd],
                    ha, binary ? hb : "-", hw, (unsigned)want_flags,
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

/* ---- the replay --------------------------------------------------- */

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
    }

    if (cases_checked)
        *cases_checked = total;
    if (sets == 0) {
        rep_add(&r, "no vector sets found under %s - nothing was checked\n",
                dir);
        return CFT_ERR_ARTIFACT;
    }
    rep_add(&r, "%d set%s, %lu cases, all matching "
                "(each replayed twice: one element at a time for exact "
                "flags, then as arrays so a device backend's "
                "partitioning is exercised)\n",
            sets, sets == 1 ? "" : "s", (unsigned long)total);
    return CFT_OK;
}
