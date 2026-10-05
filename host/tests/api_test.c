/* Copyright 2026 Logan W.
 * SPDX-License-Identifier: Apache-2.0
 *
 * Contract tests for libcft: the promises the conformance vectors
 * cannot express.
 *
 * The vectors check arithmetic, exhaustively and against the golden
 * model. They say nothing about whether a NULL operand an opcode does
 * not read is accepted, whether the output may alias an input, or
 * whether a bad argument is refused rather than computed on. Those are
 * API promises, so they are tested here.
 *
 * The arithmetic that IS here was chosen for one reason: the expected
 * values are derived from IEEE 754-2019 by hand, not from either
 * implementation. A test that agreed with both would only prove they
 * agree with each other, and they are supposed to - so these are the
 * cases where an independent reading of the standard says what the
 * answer must be. They concentrate on the far-alignment path, which is
 * the one place softfloat.c is not a transliteration of the model.
 */

#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "cft.h"
#include "../src/slice.h"
#include "../src/tile_select.h"
#include "../src/lane_cut.h"
#include "../src/mask_bits.h"
#include "../src/backend.h"      /* cftx_last_error */
#include "../src/caps_decode.h"  /* VERSION, CAPS, CAPS2 -> cft_seq_caps */
#include "../src/remote.h"       /* cftr_last_error */
#include "../src/xclbin_clock.h" /* ABI 0.18's clock_hz, for the XRT backend */

static int failures;

#define CHECK(cond, ...)                                                 \
    do {                                                                 \
        if (!(cond)) {                                                   \
            printf("FAIL %s:%d: ", __FILE__, __LINE__);                  \
            printf(__VA_ARGS__);                                         \
            printf("\n");                                                \
            failures++;                                                  \
        }                                                                \
    } while (0)

static void put32(uint8_t *p, uint32_t v)
{
    p[0] = (uint8_t)v;
    p[1] = (uint8_t)(v >> 8);
    p[2] = (uint8_t)(v >> 16);
    p[3] = (uint8_t)(v >> 24);
}

static void put64(uint8_t *p, uint64_t v)
{
    int i;
    for (i = 0; i < 8; i++)
        p[i] = (uint8_t)(v >> (8 * i));
}

static uint64_t get64(const uint8_t *p)
{
    uint64_t v = 0;
    int i;
    for (i = 0; i < 8; i++)
        v |= (uint64_t)p[i] << (8 * i);
    return v;
}

static uint32_t get32(const uint8_t *p)
{
    return (uint32_t)p[0] | ((uint32_t)p[1] << 8) |
           ((uint32_t)p[2] << 16) | ((uint32_t)p[3] << 24);
}

static void hex_elem(const uint8_t *p, int n, char *out)
{
    static const char d[] = "0123456789abcdef";
    int i;
    for (i = 0; i < n; i++) {
        out[2 * i]     = d[p[n - 1 - i] >> 4];
        out[2 * i + 1] = d[p[n - 1 - i] & 0xf];
    }
    out[2 * n] = '\0';
}

/* ---- fp32 one-element helper ------------------------------------- */

static uint32_t run32(cft_device *dev, cft_op op, cft_round rnd,
                      uint32_t a, uint32_t b, uint32_t c, uint32_t *flags)
{
    uint8_t ea[4], eb[4], ec[4], ed[4];
    cft_status st;
    put32(ea, a); put32(eb, b); put32(ec, c); put32(ed, 0);
    st = cft_run(dev, op, CFT_FP32, rnd, ea, eb, ec, ed, 1, flags, NULL);
    CHECK(st == CFT_OK, "cft_run: %s", cft_strerror(st));
    return get32(ed);
}

#define EXPECT32(op, rnd, a, b, c, want_d, want_f)                        \
    do {                                                                  \
        uint32_t f_ = 0xdead, d_ = run32(dev, op, rnd, a, b, c, &f_);     \
        CHECK(d_ == (want_d) && f_ == (uint32_t)(want_f),                 \
              "%s fp32 %s: got 0x%08x/0x%02x want 0x%08x/0x%02x",         \
              cft_op_name(op), #rnd, (unsigned)d_, (unsigned)f_,          \
              (unsigned)(want_d), (unsigned)(want_f));                    \
    } while (0)

/* ---- fp256 constants, built from the field layout ----------------- *
 * exponent field is bits 236..254, bias 262143 = 0x3ffff. */

static void fp256_zero(uint8_t *p)     { memset(p, 0, 32); }
static void fp256_one(uint8_t *p)      { memset(p, 0, 32);
                                         p[29] = 0xf0; p[30] = 0xff;
                                         p[31] = 0x3f; }
static void fp256_min_sub(uint8_t *p)  { memset(p, 0, 32); p[0] = 1; }
static void fp256_next_up_1(uint8_t *p){ fp256_one(p); p[0] = 1; }
static void fp256_prev_1(uint8_t *p)   { memset(p, 0xff, 29);
                                         p[29] = 0xef; p[30] = 0xff;
                                         p[31] = 0x3f; }

static void expect256(cft_device *dev, const char *what, cft_op op,
                      cft_round rnd, const uint8_t *a, const uint8_t *c,
                      const uint8_t *want_d, uint32_t want_f)
{
    uint8_t b[32], d[32];
    uint32_t flags = 0xdead;
    cft_status st;
    char hg[65], hw[65];

    fp256_zero(b);
    memset(d, 0, sizeof d);
    st = cft_run(dev, op, CFT_FP256, rnd, a, b, c, d, 1, &flags, NULL);
    CHECK(st == CFT_OK, "%s: cft_run: %s", what, cft_strerror(st));
    hex_elem(d, 32, hg);
    hex_elem(want_d, 32, hw);
    CHECK(memcmp(d, want_d, 32) == 0 && flags == want_f,
          "%s: got %s/0x%02x want %s/0x%02x",
          what, hg, (unsigned)flags, hw, (unsigned)want_f);
}

/* ---- CFT_XRT_TILES: the lists, and the parse that must fail them -- */

static const struct { const char *s; int n; int o[3]; } tile_good[] = {
    {"1", 1, {1}}, {"2", 1, {2}}, {"64", 1, {64}},
    {"1,3", 2, {1, 3}}, {"3,1", 2, {3, 1}}, {"4,2,1", 3, {4, 2, 1}},
    {"007", 1, {7}}, {"010", 1, {10}}, {"064", 1, {64}},
};
static const char *const tile_bad[] = {
    "", "0", "65", "99999999999999999999", "-1", "+1", " 1", "1 ",
    "1,", ",1", "1,,2", "1;2", "1.5", "a", "1,1", "2,1,2", "1 ,3",
    /* verifier-V2's five loose parses, each read by a mutant that passed
     * the list above: a cap off by one or at 9, no cap (a 32- or 64-bit
     * wrap), strtol's octal and hex, and a tolerated line ending */
    "640", "100", "4294967297", "18446744073709551617", "0x3", "1\n",
    "1\r",
};

typedef int (*tile_parse_fn)(const char *, int *, char *, size_t);

/* How many of the lists above `parse` misreads: a good list read as
 * anything but its ordinals in order, a bad one accepted or refused
 * without a sentence, or the sixty-four at once cut short. With
 * `report`, each misread is a FAIL line. One function judges both the
 * real parse and the control below, so the control is evidence that
 * THESE checks fail, not that some other check would. */
static int tile_select_misreads(tile_parse_fn parse, int report)
{
    int order[CFT_TILE_SELECT_MAX], k, i, j, wrong, misread = 0;
    char why[320], all[CFT_TILE_SELECT_MAX * 3 + 1];
    size_t used = 0;

    for (i = 0; i < (int)(sizeof tile_good / sizeof tile_good[0]); i++) {
        k = parse(tile_good[i].s, order, why, sizeof why);
        wrong = k != tile_good[i].n;
        for (j = 0; !wrong && j < k; j++)
            wrong = order[j] != tile_good[i].o[j];
        if (wrong) {
            misread++;
            if (report)
                CHECK(0, "CFT_XRT_TILES=\"%s\" read as %d ordinals, or "
                      "out of order; want %d as written",
                      tile_good[i].s, k, tile_good[i].n);
        }
    }
    for (i = 0; i < (int)(sizeof tile_bad / sizeof tile_bad[0]); i++) {
        why[0] = 0;
        k = parse(tile_bad[i], order, why, sizeof why);
        if (k != -1 || !why[0]) {
            misread++;
            if (report)
                CHECK(0, "CFT_XRT_TILES=\"%s\" was accepted (%d), or "
                      "refused without a sentence", tile_bad[i], k);
        }
    }
    for (i = 1; i <= CFT_TILE_SELECT_MAX; i++)
        used += (size_t)snprintf(all + used, sizeof all - used,
                                 i > 1 ? ",%d" : "%d", i);
    k = parse(all, order, why, sizeof why);
    if (k != CFT_TILE_SELECT_MAX || order[0] != 1 ||
        order[CFT_TILE_SELECT_MAX - 1] != CFT_TILE_SELECT_MAX) {
        misread++;
        if (report)
            CHECK(0, "all 64 ordinals at once: parsed %d", k);
    }
    return misread;
}

/* THE NEGATIVE CONTROL for the checks above: a parse that reads a list
 * the way atoi would - skip a space or a sign, take the leading digits,
 * move on to the next comma - so " 1" is tile 1, "1;2" is tile 1 and
 * "1 ,3" is tiles 1 and 3. That is "the nearest thing it resembles",
 * which tile_select.h promises never to do. It refuses, with a
 * sentence, only a list naming no tile in range, so what catches it is
 * the strictness and nothing else. */
static int tile_select_loose(const char *s, int *order, char *why,
                             size_t whylen)
{
    int n = 0, v;

    while (*s && n < CFT_TILE_SELECT_MAX) {
        while (*s == ' ' || *s == '+')
            s++;
        for (v = 0; *s >= '0' && *s <= '9'; s++)
            if (v <= CFT_TILE_SELECT_MAX)
                v = v * 10 + (*s - '0');
        if (v >= 1 && v <= CFT_TILE_SELECT_MAX)
            order[n++] = v;
        s = strchr(s, ',');
        if (!s)
            break;
        s++;
    }
    if (!n) {
        snprintf(why, whylen, "no tile in 1..%d named", CFT_TILE_SELECT_MAX);
        return -1;
    }
    return n;
}

/* ---- a program run's lanes across tiles: lane_cut.h ---------------- */

typedef void (*lane_windows_fn)(const cft_lane_shape *, size_t, size_t,
                                cft_lane_win *);

/* The shipped function with one plausible slip: the scratch-in block
 * cut by the scratch-OUT width. Right whenever the two widths agree -
 * which is every program that reads and writes the same state - so a
 * check that only ever tried such programs would pass it. THE NEGATIVE
 * CONTROL for lane_cut_misreads below. */
static void lane_windows_slipped(const cft_lane_shape *S, size_t first,
                                 size_t lanes, cft_lane_win *w)
{
    cft_lane_windows(S, first, lanes, w);
    if (S->has_sin && !S->src_elems[3]) {
        w[CFT_LANE_SIN].off = first * S->n_sout * S->esz;
        w[CFT_LANE_SIN].len = lanes * S->n_sout * S->esz;
    }
}

/* ...and the slip the per-lane flags block invites (revision 8, R23):
 * every tile's block copied to the caller's lane 0, as though the tile's
 * own lane 0 were the run's. Right whenever one tile runs the whole run -
 * every single-tile image, and every run the planner hands one slice - so
 * a check that never cut a run across tiles would pass it. A second
 * NEGATIVE CONTROL for lane_cut_misreads. */
static void lane_windows_lf_at_zero(const cft_lane_shape *S, size_t first,
                                    size_t lanes, cft_lane_win *w)
{
    cft_lane_windows(S, first, lanes, w);
    if (S->has_lf)
        w[CFT_LANE_LF].off = 0;
}

/* Whether o[0..nt) names every tile of [0, nt) exactly once. */
static int tile_order_is_perm(const size_t *o, size_t nt)
{
    uint64_t seen = 0;
    size_t j;
    for (j = 0; j < nt; j++) {
        if (o[j] >= nt || ((seen >> o[j]) & 1u))
            return 0;
        seen |= (uint64_t)1 << o[j];
    }
    return 1;
}

/* The three placement orders verifier-V7 found passing this file's
 * tile-order check at 2ecc382 (2026-09-25), kept as negative controls:
 * each is a permutation, repeatable, and wrong. */
typedef void (*tile_order_fn)(size_t, uint64_t, size_t, size_t *);

static void order_low32(size_t nt, uint64_t seed, size_t wave, size_t *o)
{
    /* a seed read through its low 32 bits: 2^63 is then the identity */
    cft_tile_order(nt, seed & 0xFFFFFFFFull, wave, o);
}

static void order_one_wave(size_t nt, uint64_t seed, size_t wave, size_t *o)
{
    /* every wave of a job the same order */
    (void)wave;
    cft_tile_order(nt, seed, 0, o);
}

/* ...and the four verifier-V8 found passing the judge that caught those
 * three (2026-09-26): it never compared two seeds, and it let two orders
 * alternate. */
static void order_all_seed1(size_t nt, uint64_t seed, size_t wave, size_t *o)
{
    /* every non-zero seed one placement */
    cft_tile_order(nt, seed ? 1u : 0u, wave, o);
}

static void order_first_wave(size_t nt, uint64_t seed, size_t wave, size_t *o)
{
    /* only a job's first wave shuffled */
    cft_tile_order(nt, wave ? 0u : seed, wave, o);
}

static void order_two_waves(size_t nt, uint64_t seed, size_t wave, size_t *o)
{
    /* two orders, alternating */
    cft_tile_order(nt, seed, wave & 1u, o);
}

static void order_low16(size_t nt, uint64_t seed, size_t wave, size_t *o)
{
    /* a seed read through its low 16 bits */
    cft_tile_order(nt, seed & 0xFFFFull, wave, o);
}

static void order_last_stays(size_t nt, uint64_t seed, size_t wave, size_t *o)
{
    /* a shuffle that never moves the last tile - the Fisher-Yates loop
     * that stops one short */
    size_t j;
    cft_tile_order(nt, seed, wave, o);
    for (j = 0; j + 1 < nt; j++)
        if (o[j] == nt - 1) {
            o[j] = o[nt - 1];
            o[nt - 1] = nt - 1;
            break;
        }
}

/* What a placement order must do beyond being a permutation. Under EVERY
 * seed, at every tile count from 4 up, some wave must move a task and
 * the eight waves must not all be one order - and from 5 up they must
 * hold at least three different orders; no two seeds may give the same
 * eight waves at any count from 4 up; and across the seeds every
 * position must move off its tile at every count from 2 up. A bit of the
 * result for each that failed: 1 a seed that moved nothing, 2 a seed
 * whose waves were one order, 4 a position that never moved, 8 two
 * seeds one placement, 16 a seed's waves fewer than three orders. The
 * bounds are where a correct shuffle cannot fail by chance: eight
 * identity waves, or eight identical ones, at 4 tiles have probability
 * 24^-7 or less; two seeds' eight waves equal at 4 tiles, 24^-8; eight
 * waves within two orders at 5 tiles, under C(120,2) x (2/120)^8 = 5e-11;
 * a position fixed through every draw at 2 tiles, 2^-56. */
static unsigned judge_tile_order(tile_order_fn f, const uint64_t *seeds,
                                 size_t nseeds)
{
    static size_t waves[8][8][64];     /* [seed][wave][position] */
    size_t ord[64], nt, w, j, s, s2;
    unsigned bad = 0;
    if (nseeds > 8)
        return 0x80u;                  /* the judge's own limit, refused */
    for (nt = 2; nt <= 64; nt++) {
        uint64_t ever = 0;
        const uint64_t all =
            nt == 64 ? ~(uint64_t)0 : (((uint64_t)1 << nt) - 1);
        for (s = 0; s < nseeds; s++) {
            int moved = 0, differs = 0, distinct = 0;
            for (w = 0; w < 8; w++) {
                size_t v;
                int seen = 0;
                f(nt, seeds[s], w, ord);
                memcpy(waves[s][w], ord, nt * sizeof ord[0]);
                for (j = 0; j < nt; j++)
                    if (ord[j] != j) {
                        moved = 1;
                        ever |= (uint64_t)1 << j;
                    }
                if (w && memcmp(waves[s][0], ord, nt * sizeof ord[0]))
                    differs = 1;
                for (v = 0; v < w; v++)
                    if (!memcmp(waves[s][v], ord, nt * sizeof ord[0]))
                        seen = 1;
                distinct += !seen;
            }
            if (nt >= 4 && !moved)
                bad |= 1u;
            if (nt >= 4 && !differs)
                bad |= 2u;
            if (nt >= 5 && distinct < 3)
                bad |= 16u;
            /* the first nt entries of each wave only: the rest hold an
             * earlier count's or an earlier call's orders */
            for (s2 = 0; nt >= 4 && s2 < s; s2++) {
                int same = 1;
                for (w = 0; same && w < 8; w++)
                    same = !memcmp(waves[s][w], waves[s2][w],
                                   nt * sizeof ord[0]);
                if (same)
                    bad |= 8u;
            }
        }
        if (ever != all)
            bad |= 4u;
    }
    return bad;
}

static uint64_t lane_rng(uint64_t *s)
{
    return cft_lane_mix(s);
}

/* Over `trials` random shapes and cuts (both planners), count the
 * windows `fn` gets wrong: a per-lane block must be covered exactly
 * once, in lane order, by its slices' windows - each the slice's lanes
 * times the block's width a lane - and an indexed source must reach
 * every slice whole. With `report`, each first misread of a kind is a
 * FAIL line. */
static int lane_cut_misreads(lane_windows_fn fn, int trials, int report,
                             int *unaligned, int *empty_tiles)
{
    uint64_t s = 20260925;
    int t, misread = 0, said = 0;

    for (t = 0; t < trials; t++) {
        static const size_t eszs[4] = {4, 8, 16, 32};
        cft_lane_shape S;
        cft_slice sl[64];
        cft_lane_win w[CFT_LANE_ROLES];
        size_t full[CFT_LANE_ROLES], next[CFT_LANE_ROLES];
        size_t ntiles = 1 + (size_t)(lane_rng(&s) % 8), k, i;
        int r, bad = 0, seeded = (int)(lane_rng(&s) & 1);

        memset(&S, 0, sizeof S);
        S.n = 1 + (size_t)(lane_rng(&s) % 300);
        S.esz = eszs[lane_rng(&s) % 4];
        S.max_deposits = (size_t)(lane_rng(&s) % 4);
        S.has_sin = (int)(lane_rng(&s) & 1);
        S.has_sout = (int)(lane_rng(&s) & 1);
        S.n_sin = S.has_sin ? 1 + (size_t)(lane_rng(&s) % 6) : 0;
        S.n_sout = S.has_sout ? 1 + (size_t)(lane_rng(&s) % 6) : 0;
        for (r = 0; r < 4; r++)
            if ((lane_rng(&s) % 3) == 0 && (r < 3 || S.has_sin))
                S.src_elems[r] = 1 + (size_t)(lane_rng(&s) % 500);
        /* R23's per-lane flags block (revision 8: the XRT backend copies
         * each tile's block to its slice's first lane), in half the
         * shapes: a byte a lane at every format */
        S.has_lf = (int)(lane_rng(&s) & 1);

        k = seeded ? cft_plan_lane_cuts(S.n, ntiles, lane_rng(&s), sl)
                   : cft_plan_slices(S.n, S.esz, ntiles, sl);
        if (seeded) {
            for (i = 0; i < k; i++)
                if (sl[i].first_elem % (32 / S.esz))
                    (*unaligned)++;
            if (k < ntiles && k < S.n)
                (*empty_tiles)++;
        }

        full[CFT_LANE_A] = S.n * S.esz;
        full[CFT_LANE_B] = S.n * S.esz;
        full[CFT_LANE_C] = S.n * S.esz;
        full[CFT_LANE_DEP] = S.n * S.max_deposits * S.esz;
        full[CFT_LANE_CNT] = S.n * 4;
        full[CFT_LANE_SIN] = S.has_sin ? S.n * S.n_sin * S.esz : 0;
        full[CFT_LANE_SOUT] = S.has_sout ? S.n * S.n_sout * S.esz : 0;
        full[CFT_LANE_IA] = S.src_elems[0] ? S.n * 4 : 0;
        full[CFT_LANE_IB] = S.src_elems[1] ? S.n * 4 : 0;
        full[CFT_LANE_IC] = S.src_elems[2] ? S.n * 4 : 0;
        full[CFT_LANE_ISI] = (S.has_sin && S.src_elems[3])
                                 ? S.n * S.n_sin * 4 : 0;
        full[CFT_LANE_LF] = S.has_lf ? S.n : 0;
        for (r = 0; r < 4; r++)
            if (S.src_elems[r] && (r < 3 || S.has_sin))
                full[r == 3 ? CFT_LANE_SIN : r] = S.src_elems[r] * S.esz;
        for (r = 0; r < CFT_LANE_ROLES; r++)
            next[r] = 0;

        /* the planner: contiguous, in order, all n lanes, none empty */
        {
            size_t at = 0, last_tile = 0;
            for (i = 0; i < k; i++) {
                if (sl[i].first_elem != at || sl[i].real == 0 ||
                    (i && sl[i].tile <= last_tile) || sl[i].tile >= ntiles)
                    bad = 1;
                at = sl[i].first_elem + sl[i].real;
                last_tile = sl[i].tile;
            }
            if (at != S.n)
                bad = 1;
        }
        for (i = 0; i < k && !bad; i++) {
            fn(&S, sl[i].first_elem, sl[i].real, w);
            for (r = 0; r < CFT_LANE_ROLES; r++) {
                const int whole_src =
                    (r < 3 && S.src_elems[r]) ||
                    (r == CFT_LANE_SIN && S.has_sin && S.src_elems[3]);
                if (whole_src) {
                    if (!w[r].whole || w[r].off != 0 || w[r].len != full[r])
                        bad = 1;
                } else {
                    if (w[r].whole || w[r].off != next[r])
                        bad = 1;
                    next[r] = w[r].off + w[r].len;
                }
            }
        }
        for (r = 0; r < CFT_LANE_ROLES && !bad; r++) {
            const int whole_src = (r < 3 && S.src_elems[r]) ||
                (r == CFT_LANE_SIN && S.has_sin && S.src_elems[3]);
            if (!whole_src && next[r] != full[r])
                bad = 1;
        }
        if (bad) {
            misread++;
            if (report && said++ < 4)
                CHECK(0, "lane cut: n=%lu esz=%lu tiles=%lu %s planner - a "
                      "block's windows do not cover it exactly once",
                      (unsigned long)S.n, (unsigned long)S.esz,
                      (unsigned long)ntiles, seeded ? "seeded" : "beat");
            else if (report)
                failures++;
        }
    }
    return misread;
}

/* cft_build_id()'s grammar, exactly as cft.h gives it: "unknown", or
 * "commit=" and 40 or 64 lowercase hex digits, " tracked=clean" or
 * " tracked=modified", " untracked=none" or " untracked=present", and
 * nothing after. Returns 1, or 0 with the first thing wrong in `why`. A
 * certificate carries these words and a reader parses them, so a
 * near-miss - a short commit, "dirty", a trailing space - is a failure
 * here and not a style point. */
static int build_id_form(const char *s, char *why, size_t n)
{
    size_t h = 0;
    const char *p;
    if (!strcmp(s, "unknown"))
        return 1;
    if (strncmp(s, "commit=", 7)) {
        snprintf(why, n, "it is neither \"unknown\" nor \"commit=...\"");
        return 0;
    }
    p = s + 7;
    while ((p[h] >= '0' && p[h] <= '9') || (p[h] >= 'a' && p[h] <= 'f'))
        h++;
    if (h != 40 && h != 64) {
        snprintf(why, n, "its commit has %lu lowercase hex digits, not 40 "
                 "or 64", (unsigned long)h);
        return 0;
    }
    p += h;
    if (!strncmp(p, " tracked=clean", 14)) {
        p += 14;
    } else if (!strncmp(p, " tracked=modified", 17)) {
        p += 17;
    } else {
        snprintf(why, n, "\" tracked=clean\" or \" tracked=modified\" does "
                 "not follow the commit");
        return 0;
    }
    if (!strcmp(p, " untracked=none") || !strcmp(p, " untracked=present"))
        return 1;
    snprintf(why, n, "it ends \"%s\", not \" untracked=none\" or "
             "\" untracked=present\"", p);
    return 0;
}

/* ---- the program-load refusals (the fixes round's Q5, 2026-09-30) ---
 *
 * One instruction word, as a constant expression so the case table in
 * main can hold it: op[7:0], rd[11:8], ra[15:12], rb[19:16], rc[23:20],
 * rnd[26:24], the flags ka kb kc kx at 27..30 (`k`: LD_KA and friends),
 * ctrl 31, imm[63:32] - docs/SEQUENCER.md's layout. */
#define LD_KA 1u
#define LD_KB 2u
#define LD_KX 8u
#define LDW(c, op, rd, ra, rb, rc, rnd, k, imm)                            \
    ((uint64_t)(op) | ((uint64_t)(rd) << 8) | ((uint64_t)(ra) << 12) |    \
     ((uint64_t)(rb) << 16) | ((uint64_t)(rc) << 20) |                    \
     ((uint64_t)(rnd) << 24) | ((uint64_t)(k) << 27) |                    \
     ((uint64_t)(c) << 31) | ((uint64_t)(uint32_t)(imm) << 32))
#define LD_ALU(op, rd, ra, rb, rc, rnd, k, imm)                            \
    LDW(0, op, rd, ra, rb, rc, rnd, k, imm)
#define LD_CTL(op, rd, ra, rb, rc, rnd, k, imm)                            \
    LDW(1, op, rd, ra, rb, rc, rnd, k, imm)
#define LD_HALT       LD_CTL(0, 0, 0, 0, 0, 0, 0, 0)
#define LD_REPEAT(t)  LD_CTL(1, 0, 0, 0, 0, 0, 0, (t))
#define LD_ENDREP     LD_CTL(2, 0, 0, 0, 0, 0, 0, 0)
#define LD_ADD        LD_ALU(1, 0, 0, 0, 0, 0, 0, 0)

/* An image: the header, `n_consts` zero constants of `esz` bytes (none
 * under BANK_EXT), then `n` instructions. Returns its length. `img`
 * must hold 32 + n_consts * esz + 8 * n bytes. */
static size_t ld_image(uint8_t *img, uint32_t magic, uint32_t ver,
                       uint32_t prec, size_t esz, uint32_t flags,
                       uint32_t scratch_io, uint32_t maxdep,
                       uint32_t n_consts, const uint64_t *ins, size_t n)
{
    size_t off = 32, k;
    put32(img + 0, magic);
    put32(img + 4, ver);
    put32(img + 8, (uint32_t)n);
    put32(img + 12, n_consts);
    put32(img + 16, maxdep);
    put32(img + 20, prec);
    put32(img + 24, flags);
    put32(img + 28, scratch_io);
    if (!(flags & CFT_PROG_FLAG_BANK_EXT)) {
        memset(img + off, 0, (size_t)n_consts * esz);
        off += (size_t)n_consts * esz;
    }
    for (k = 0; k < n; k++, off += 8)
        put64(img + off, ins[k]);
    return off;
}

/* A failing call that leaves a sentence of its own in cft_last_error():
 * P2's, the one measured explaining a load refusal in the revision-7
 * round - cft_run_ex, an index at its source's length. Returns whether
 * it did. */
static int ld_plant(cft_device *dev)
{
    uint8_t a8[4 * 8], d8[4 * 8];
    uint32_t ix[4] = { 0u, 1u, 4u, 3u };     /* 4 is past the source */
    cft_elem_args E;
    memset(a8, 0, sizeof a8);
    memset(&E, 0, sizeof E);
    E.struct_size = sizeof E;
    E.a = a8; E.b = a8; E.c = a8; E.d = d8; E.n = 4;
    E.idx_a = ix; E.idx_a_src = 4;
    return cft_run_ex(dev, CFT_ADD, CFT_FP64, CFT_RNE, &E) ==
               CFT_ERR_INVALID_ARGUMENT &&
           strstr(cft_last_error(), "cft_run_ex") != NULL;
}

/* What cft_last_error() shows while the library's own slot is empty:
 * a device backend's older message, in device.c's order (the remote
 * backend's, then XRT's), or nothing. So cft_last_error() equals this
 * exactly when the library's slot is empty, in every build: an XRT
 * build shows its backend's words for the cft_open of no-such.xclbin
 * below through an empty slot, and a build without one shows "". This
 * file is compiled with the library's own XRT define for that. */
static const char *backend_words(void)
{
#ifndef CFT_NO_REMOTE
    if (*cftr_last_error())
        return cftr_last_error();
#endif
#ifdef CFT_ENABLE_XRT
    return cftx_last_error();
#else
    return "";
#endif
}

/* A load that must be refused: a sentence planted first on `live`, then
 * the load on `dev`, held to its status - the one each always had on a
 * 64-bit host, and since 2026-09-30 on a 32-bit one too - and to a
 * sentence of its own, non-empty, not the planted one, and saying each
 * of `say0`..`say2` (NULL ends the list early). `dev` and `img` may be
 * NULL, and `give_out` 0 passes a NULL `out`: three of the refusals. */
static void ld_expect(cft_device *live, cft_device *dev, const char *what,
                      const void *img, size_t bytes, int give_out,
                      cft_status want, const char *say0, const char *say1,
                      const char *say2)
{
    const char *says[3];
    cft_program *prog = NULL;
    cft_status st;
    const char *msg;
    size_t k;

    says[0] = say0; says[1] = say1; says[2] = say2;
    CHECK(ld_plant(live), "%s: the call meant to plant a sentence first "
          "left none", what);
    st = cft_program_load(dev, img, bytes, give_out ? &prog : NULL);
    msg = cft_last_error();
    CHECK(st == want, "%s: %s, and the status must be %s (%s)", what,
          cft_strerror(st), cft_strerror(want), msg);
    CHECK(strcmp(msg, backend_words()) != 0,
          "%s: refused with no sentence of the library's own ('%s')",
          what, msg);
    CHECK(strstr(msg, "cft_run_ex") == NULL,
          "%s: the sentence is an earlier call's: '%s'", what, msg);
    for (k = 0; k < 3 && says[k]; k++)
        CHECK(strstr(msg, says[k]) != NULL,
              "%s: the sentence does not say \"%s\": '%s'", what, says[k],
              msg);
    if (st == CFT_OK)
        cft_program_free(prog);
}

/* ------------------------------------------------------------------ */

int main(void)
{
    cft_device *dev = NULL;
    cft_buffer *buf = NULL;
    cft_caps caps;
    cft_status st;
    uint32_t flags;
    int i;

    /* --- static description ------------------------------------- */
    CHECK(cft_abi_version() ==
          (((uint32_t)CFT_ABI_VERSION_MAJOR << 16) | CFT_ABI_VERSION_MINOR),
          "abi version disagrees with the header");
    CHECK(cft_format_size(CFT_FP32) == 4 && cft_format_size(CFT_FP64) == 8 &&
          cft_format_size(CFT_FP128) == 16 &&
          cft_format_size(CFT_FP256) == 32, "format sizes");
    CHECK(cft_format_size((cft_format)7) == 0, "bad format size is 0");
    CHECK(strcmp(cft_op_name(CFT_MINNUM), "minnum") == 0, "op name");
    CHECK(strcmp(cft_op_name((cft_op)15), "reserved") == 0,
          "unassigned op name");
    CHECK(cft_strerror(CFT_ERR_BUS_FAULT) != NULL, "strerror");

    /* --- the build id (cft.h, cft_build_id) ----------------------- *
     *
     * Printed first, so every log of this binary says which library it
     * tested - this binary links libcft.a statically and carries the id
     * of the archive it was linked against. Its form is held exactly.
     * `make test` hands it the tree's id as of now in
     * CFT_EXPECT_BUILD_ID, and a binary that differs is a stale one: it
     * is testing a library the tree no longer builds (CLAUDE.md). */
    {
        static const char *const good[] = {
            "unknown",
            "commit=0123456789abcdef0123456789abcdef01234567 tracked=clean "
            "untracked=none",
            "commit=0123456789abcdef0123456789abcdef01234567 "
            "tracked=modified untracked=present",
            "commit=0123456789abcdef0123456789abcdef0123456789abcdef"
            "0123456789abcdef tracked=clean untracked=present",
        };
        static const char *const bad[] = {
            "", "Unknown", "unknown ", "d18d3c2",
            "commit=d18d3c2 tracked=clean untracked=none",
            "commit=0123456789ABCDEF0123456789abcdef01234567 tracked=clean "
            "untracked=none",
            "commit=0123456789abcdef0123456789abcdef01234567 tracked=dirty "
            "untracked=none",
            "commit=0123456789abcdef0123456789abcdef01234567 tracked=clean "
            "untracked=none ",
            "commit=0123456789abcdef0123456789abcdef01234567 tracked=clean",
            "commit=0123456789abcdef0123456789abcdef01234567  tracked=clean "
            "untracked=none",
        };
        const char *id = cft_build_id();
        const char *want = getenv("CFT_EXPECT_BUILD_ID");
        char why[200];
        size_t k;
        int misread = 0;

        /* The form check's own controls, before it is trusted with the
         * library's answer: a check that accepted everything would pass
         * every id there is. */
        for (k = 0; k < sizeof good / sizeof good[0]; k++)
            if (!build_id_form(good[k], why, sizeof why)) {
                printf("  the build-id form check refused \"%s\": %s\n",
                       good[k], why);
                misread++;
            }
        for (k = 0; k < sizeof bad / sizeof bad[0]; k++)
            if (build_id_form(bad[k], why, sizeof why)) {
                printf("  the build-id form check accepted \"%s\"\n", bad[k]);
                misread++;
            }
        CHECK(misread == 0, "the build-id form check misread %d of its %lu "
              "controls", misread,
              (unsigned long)(sizeof good / sizeof good[0] +
                              sizeof bad / sizeof bad[0]));

        CHECK(id != NULL, "cft_build_id() returned NULL");
        if (id) {
            printf("api-test: libcft build %s\n", id);
            CHECK(build_id_form(id, why, sizeof why),
                  "cft_build_id() is \"%s\", which is neither form cft.h "
                  "gives: %s", id, why);
            CHECK(strcmp(cft_build_id(), id) == 0,
                  "cft_build_id() changed between two calls");
            if (want) {
                CHECK(strcmp(id, want) == 0,
                      "this api-test carries libcft build \"%s\" and the "
                      "tree is \"%s\" now - it is stale: it links libcft.a "
                      "statically and was not relinked since the library "
                      "was rebuilt (make -C host api-test)", id, want);
            } else {
                printf("api-test: the build id was not held to the tree's "
                       "(CFT_EXPECT_BUILD_ID is unset; make -C host test "
                       "sets it)\n");
            }
        }
    }

    /* --- open, caps ---------------------------------------------- */
    st = cft_open(NULL, 0, &dev);
    CHECK(st == CFT_OK && dev != NULL, "cft_open(NULL): %s",
          cft_strerror(st));
    if (!dev)
        return 1;

    {
        /* An artifact path that does not exist - and, in a build
         * without XRT, any artifact path at all (a cft:// URL works
         * either way, cft.h) - has to fail loudly rather than quietly
         * hand back the software backend under another name. */
        cft_device *hw = (cft_device *)(void *)0x1;
        CHECK(cft_open("no-such.xclbin", 0, &hw) != CFT_OK && hw == NULL,
              "an artifact open must fail, and must not leave a handle");
    }

    memset(&caps, 0, sizeof caps);
    caps.struct_size = sizeof caps;
    st = cft_get_caps(dev, &caps);
    CHECK(st == CFT_OK, "cft_get_caps: %s", cft_strerror(st));
    CHECK(caps.format_mask == 0xfu, "software backend carries every format");
    CHECK(caps.tiles == 1, "tiles");
    CHECK(caps.flags_readable == 1, "flags readable");
    CHECK(strcmp(caps.backend, "software") == 0, "backend name");
    CHECK(caps.struct_size == sizeof caps, "struct_size echoes bytes filled");

    /* A caller that forgets struct_size gets an error, not a stack
     * smash - the field exists precisely so that the library never
     * writes further than the caller's struct. */
    {
        cft_caps small;
        memset(&small, 0, sizeof small);
        small.struct_size = 0;
        CHECK(cft_get_caps(dev, &small) == CFT_ERR_INVALID_ARGUMENT,
              "struct_size 0 must be refused");
    }

    /* The device image's identity (cft.h, cft_get_image_id). The
     * software backend has no image, so the answer is a refusal BY NAME
     * - never a digest of zeros that reads as one: CFT_ERR_UNSUPPORTED,
     * a sentence that names the backend and where its identity is
     * instead, struct_size set to 0, and not one other byte written
     * (the struct is filled with 0xA5 first, so a write shows). The
     * argument refusals come first, as on every backend. The remote
     * handle's refusal is held by device-test through a loopback server
     * (verify/run.sh's remote stage), and the XRT digest on a card
     * (hw/card-identity.sh). */
    {
        cft_image_id im;
        const unsigned char *b = (const unsigned char *)&im;
        size_t k, wrote = 0;
        const char *msg;

        memset(&im, 0xA5, sizeof im);
        im.struct_size = sizeof im;
        st = cft_get_image_id(dev, &im);
        msg = cft_last_error();
        CHECK(st == CFT_ERR_UNSUPPORTED, "cft_get_image_id on the software "
              "backend: %s, not CFT_ERR_UNSUPPORTED", cft_strerror(st));
        CHECK(strstr(msg, "software backend") && strstr(msg, "cft_build_id"),
              "the software backend's image refusal names neither itself "
              "nor where its identity is: \"%s\"", msg);
        CHECK(im.struct_size == 0, "a refused cft_get_image_id reports %lu "
              "bytes filled, not 0", (unsigned long)im.struct_size);
        for (k = offsetof(cft_image_id, sha256); k < sizeof im; k++)
            wrote += b[k] != 0xA5;
        CHECK(wrote == 0, "a refused cft_get_image_id wrote %lu bytes of "
              "the struct past struct_size", (unsigned long)wrote);

        memset(&im, 0, sizeof im);
        im.struct_size = sizeof im;
        CHECK(cft_get_image_id(NULL, &im) == CFT_ERR_INVALID_ARGUMENT,
              "cft_get_image_id(NULL, ...) must be an argument error");
        CHECK(cft_get_image_id(dev, NULL) == CFT_ERR_INVALID_ARGUMENT,
              "cft_get_image_id(dev, NULL) must be an argument error");
        im.struct_size = sizeof(size_t) - 1;
        CHECK(cft_get_image_id(dev, &im) == CFT_ERR_INVALID_ARGUMENT &&
              im.struct_size == sizeof(size_t) - 1,
              "a struct_size below sizeof(size_t) must be an argument error, "
              "with the struct untouched");

        /* ABI 0.18 appended the device lines (platform, xrt_version,
         * clock_hz, serial) after the 0.17 struct, whose size is where
         * they begin: a caller built against 0.17 passes that size, and
         * its call is the one it always made - here the same refusal,
         * nothing written. */
        CHECK(offsetof(cft_image_id, platform) == 72 &&
              offsetof(cft_image_id, xrt_version) == 72 + 256 &&
              offsetof(cft_image_id, clock_hz) == 72 + 256 + 64 &&
              offsetof(cft_image_id, serial) == 72 + 256 + 64 + 8 &&
              sizeof im == 72 + 256 + 64 + 8 + 256,
              "cft_image_id's 0.18 fields are not appended after the 0.17 "
              "struct's 72 bytes in their order: platform at %lu, "
              "xrt_version at %lu, clock_hz at %lu, serial at %lu, %lu in "
              "all", (unsigned long)offsetof(cft_image_id, platform),
              (unsigned long)offsetof(cft_image_id, xrt_version),
              (unsigned long)offsetof(cft_image_id, clock_hz),
              (unsigned long)offsetof(cft_image_id, serial),
              (unsigned long)sizeof im);
        memset(&im, 0xA5, sizeof im);
        im.struct_size = offsetof(cft_image_id, platform);
        st = cft_get_image_id(dev, &im);
        wrote = 0;
        for (k = offsetof(cft_image_id, sha256); k < sizeof im; k++)
            wrote += b[k] != 0xA5;
        CHECK(st == CFT_ERR_UNSUPPORTED && im.struct_size == 0 &&
              wrote == 0, "a 0.17 caller's cft_get_image_id on the software "
              "backend: %s, struct_size %lu, %lu bytes written; it must be "
              "refused as before, nothing filled", cft_strerror(st),
              (unsigned long)im.struct_size, (unsigned long)wrote);
    }

    /* xclbin_clock.h: the kernel clock an image's BUILD_METADATA states,
     * which the XRT backend reports as cft_image_id's clock_hz (ABI 0.18).
     * It needs no XRT, so it is held here, on every host, to synthetic
     * axlf images: a constraint that names every unit opened gives its
     * clock, and every other shape gives 0 with a reason - never a
     * guess. The real images in the cft2204 distro were read by it too
     * (CV2CW's ledger, 2026-10-02): the hw single and quad, 10 MHz on
     * their own units, and the hw_emu images none. */
    {
        static unsigned char img[4096];
        const char *one[] = { "cft_krnl_1" };
        const char *quad[] = { "cft_krnl_1", "cft_krnl_2", "cft_krnl_3",
                               "cft_krnl_4" };
        struct { const char *what, *meta; int n_meta; size_t at;
                 const char *const *inst; size_t n_inst; uint64_t want; }
        C[] = {
            { "one unit named", "{\"options\": \"--clock.freqHz 135000000:"
              "cft_krnl_1.ap_clk --config hw/link.cfg\"}", 1, 0, one, 1,
              135000000u },
            { "four units, all named", "{\"options\": \"--clock.freqHz "
              "135000000:cft_krnl_1.ap_clk,cft_krnl_2.ap_clk,"
              "cft_krnl_3.ap_clk,cft_krnl_4.ap_clk --link\"}", 1, 0, quad, 4,
              135000000u },
            { "four units, one at the default", "{\"options\": "
              "\"--clock.freqHz 135000000:cft_krnl_1.ap_clk,cft_krnl_2.ap_clk,"
              "cft_krnl_4.ap_clk\"}", 1, 0, quad, 4, 0 },
            { "a longer name is not its prefix", "{\"options\": "
              "\"--clock.freqHz 135000000:cft_krnl_10.ap_clk\"}", 1, 0, one,
              1, 0 },
            { "another port is not ap_clk", "{\"options\": "
              "\"--clock.freqHz 135000000:cft_krnl_1.ap_clk_2\"}", 1, 0, one,
              1, 0 },
            { "two constraints", "{\"options\": \"--clock.freqHz 135000000:"
              "cft_krnl_1.ap_clk --clock.freqHz 100000000:cft_krnl_1.ap_clk"
              "\"}", 1, 0, one, 1, 0 },
            { "no constraint (an hw_emu link)", "{\"options\": \"--link "
              "--target hw_emu\"}", 1, 0, one, 1, 0 },
            { "a leading zero", "{\"options\": \"--clock.freqHz 0135000000:"
              "cft_krnl_1.ap_clk\"}", 1, 0, one, 1, 0 },
            { "zero hertz", "{\"options\": \"--clock.freqHz 0:cft_krnl_1."
              "ap_clk\"}", 1, 0, one, 1, 0 },
            { "twenty digits", "{\"options\": \"--clock.freqHz "
              "10000000000000000000:cft_krnl_1.ap_clk\"}", 1, 0, one, 1, 0 },
            { "no colon", "{\"options\": \"--clock.freqHz 135000000 "
              "cft_krnl_1.ap_clk\"}", 1, 0, one, 1, 0 },
            { "no BUILD_METADATA section", "{\"options\": \"--clock.freqHz "
              "135000000:cft_krnl_1.ap_clk\"}", 0, 0, one, 1, 0 },
            { "two BUILD_METADATA sections", "{\"options\": "
              "\"--clock.freqHz 135000000:cft_krnl_1.ap_clk\"}", 2, 0, one,
              1, 0 },
            { "a section past the file", "{\"options\": \"--clock.freqHz "
              "135000000:cft_krnl_1.ap_clk\"}", 1, 3000, one, 1, 0 },
            { "no unit opened", "{\"options\": \"--clock.freqHz 135000000:"
              "cft_krnl_1.ap_clk\"}", 1, 0, one, 0, 0 },
        };
        size_t c;
        for (c = 0; c < sizeof C / sizeof C[0]; c++) {
            size_t len = strlen(C[c].meta), off = 1024, j;
            uint64_t hz = 12345, size = len;
            char why[400];
            int got;
            memset(img, 0, sizeof img);
            memcpy(img, "xclbin2\0", 8);
            img[448] = (unsigned char)(C[c].n_meta ? C[c].n_meta + 1 : 1);
            /* section 0 is a BITSTREAM of no bytes; then the metadata */
            for (j = 0; j < (size_t)C[c].n_meta; j++) {
                unsigned char *s = img + 456 + 40 * (j + 1);
                uint64_t o = C[c].at ? C[c].at : off, z = size;
                int bb;
                s[0] = 14;
                for (bb = 0; bb < 8; bb++) {
                    s[24 + bb] = (unsigned char)(o >> (8 * bb));
                    s[32 + bb] = (unsigned char)(z >> (8 * bb));
                }
            }
            memcpy(img + off, C[c].meta, len);
            got = cft_xclbin_kernel_clock(img, off + len + (C[c].at ? 0 : 16),
                                          C[c].inst, C[c].n_inst, &hz, why,
                                          sizeof why);
            CHECK(C[c].want ? (got == 1 && hz == C[c].want)
                            : (got == 0 && hz == 0 && why[0] != 0),
                  "xclbin_clock: %s: it answered %d, %llu Hz (%s)",
                  C[c].what, got, (unsigned long long)hz,
                  got ? "" : why);
        }
        memset(img, 0, sizeof img);
        {
            uint64_t hz = 1;
            char why[400];
            CHECK(cft_xclbin_kernel_clock(img, sizeof img, one, 1, &hz, why,
                                          sizeof why) == 0 && hz == 0,
                  "xclbin_clock: bytes that are no axlf name a clock");
            memcpy(img, "xclbin2\0", 8);
            img[448] = 200;         /* 200 sections run past 4,096 bytes */
            CHECK(cft_xclbin_kernel_clock(img, sizeof img, one, 1, &hz, why,
                                          sizeof why) == 0 && hz == 0,
                  "xclbin_clock: a section table past the file names a "
                  "clock");
        }
    }

    /* max_scratch, appended at ABI 0.10, and the same sentinel proof
     * cft_program_info's flags field gets: a caller built against the
     * 0.9 header passes the 0.9 struct_size and nothing past it is
     * written. A clear FEATURE bit is absent and a zero CAPACITY is
     * unknown, so the two are asked separately. */
    CHECK(caps.max_scratch == 256u &&
          (caps.seq_features & CFT_SEQ_FEAT_SCRATCH) != 0 &&
          (caps.seq_features & CFT_SEQ_FEAT_SCRATCH_IO) != 0 &&
          (caps.seq_features & CFT_SEQ_FEAT_KX9) != 0 &&
          caps.max_consts == 512u,
          "the software backend publishes 256 scratch slots, 512 "
          "constants and revision 3's three features (0x%lx, %lu, %lu)",
          (unsigned long)caps.seq_features, (unsigned long)caps.max_scratch,
          (unsigned long)caps.max_consts);
    {
        /* An ABI 0.9 caller's struct ends before `max_scratch`. It
         * must come back with the bytes it asked for and not one
         * more, and the sentinel has to be a byte the field could not
         * have been written as - which 0xa5 is and 0x00 is not, since
         * 256 has a zero low byte. */
        union { cft_caps caps; uint8_t raw[256]; } u;
        const size_t old_size = offsetof(cft_caps, max_scratch);
        size_t w;
        memset(&u, 0xa5, sizeof u);
        memset(&u.caps, 0, old_size);
        u.caps.struct_size = old_size;
        st = cft_get_caps(dev, &u.caps);
        CHECK(st == CFT_OK && u.caps.struct_size == old_size,
              "an ABI 0.9 cft_caps struct_size comes back as itself");
        for (w = old_size; w < sizeof u; w++)
            if (u.raw[w] != 0xa5)
                break;
        CHECK(w == sizeof u,
              "nothing past an older caller's cft_caps struct_size is "
              "written (byte %lu changed)", (unsigned long)w);
    }

    /* --- capability discovery ------------------------------------ */
    CHECK(cft_supports(dev, CFT_FMA, CFT_FP256) == 1, "fma/fp256 supported");
    CHECK(cft_supports(dev, CFT_ICMPLT, CFT_FP32) == 1, "icmplt supported");
    CHECK(cft_supports(dev, (cft_op)15, CFT_FP32) == 0, "op 15 unassigned");
    CHECK(cft_supports(dev, (cft_op)200, CFT_FP32) == 0, "op 200 unassigned");
    CHECK(cft_supports(dev, CFT_FMA, (cft_format)9) == 0, "bad format");

    /* --- the software handle's CAPS2[7] and CAPS2[8] (2026-09-24) ----
     *
     * cft.h defines CFT_SEQ_FEAT_SCALAR and CFT_FEAT_REDUCE_SEG as "does
     * THIS HANDLE take the call", and the software backend computes both
     * calls by their definitions - so it must publish both, or a caller
     * that asks cft_get_caps first, as the header tells it to, is told
     * no by a handle that would have said yes. That was this library's
     * state until 2026-09-24 (seq_features 0x671f; 0x7f1f from then,
     * 0x1ff1f with ABI 0.16's revision-8 bits, and 0x7ff1f since ABI
     * 0.17's R23 and R24).
     *
     * Each claim is held two ways: the bit is in the word, AND the call
     * it names returns the definition's bits and flags - the scalar run
     * against the same run over an array of copies, the segmented
     * reduction against cft_reduce slice by slice. Removing either bit
     * from the software open fails the first half by name and, because
     * libcft reads the same bit before computing, the second half too.
     *
     * The scalar operand's buffer holds n elements: element 0 is the
     * scalar and the rest are POISON, so a path that ignored scalar_mask
     * and streamed the buffer would compute from the poison. `poisoned`
     * counts the cases where the poison would have shown - if it is
     * zero, the comparison could not have failed and says so. */
    {
        enum { SN = 9, NSEG = 12 };
        /* every subset of a, b, c that is not empty */
        static const uint32_t masks[] = { 1u, 2u, 4u, 3u, 5u, 6u, 7u };
        static const cft_op rops[] = { CFT_SUM, CFT_DOT, CFT_SUMSQ,
                                       CFT_SUMABS, CFT_MAXALL };
        static const size_t segs[] = { 1, 3, 4, 6 };
        uint8_t sbuf[3][SN * 32], rep[3][SN * 32];
        uint8_t d_sc[SN * 32], d_rep[SN * 32], d_dense[SN * 32];
        uint8_t ra[NSEG * 32], rb[NSEG * 32], d_seg[NSEG * 32],
                d_one[32];
        uint64_t lcg = 0x243F6A8885A308D3ull;   /* pi's fraction */
        unsigned long cases = 0, poisoned = 0, rcases = 0;
        const int failures0 = failures;
        int fmt, r, rnd;
        size_t k, q, mi, oi, si;

        CHECK((caps.seq_features & CFT_SEQ_FEAT_SCALAR) != 0,
              "the software backend publishes CFT_SEQ_FEAT_SCALAR "
              "(CAPS2[7]) - it computes a scalar operand exactly, so a "
              "caller gating on the bit must be told yes "
              "(seq_features 0x%lx)", (unsigned long)caps.seq_features);
        CHECK((caps.seq_features & CFT_FEAT_REDUCE_SEG) != 0,
              "the software backend publishes CFT_FEAT_REDUCE_SEG "
              "(CAPS2[8]) - it computes cft_reduce_seg by its definition, "
              "so a caller gating on the bit must be told yes "
              "(seq_features 0x%lx)", (unsigned long)caps.seq_features);

        for (fmt = 0; fmt < 4; fmt++) {
            const size_t esz = cft_format_size((cft_format)fmt);
            if (!(caps.format_mask & (1u << fmt)))
                continue;
            for (mi = 0; mi < sizeof masks / sizeof masks[0]; mi++) {
                for (rnd = 0; rnd < 5; rnd++) {
                    const uint32_t m = masks[mi];
                    const void *op3[3];
                    uint32_t f_sc = 0, f_rep = 0, f_dense = 0;
                    cft_elem_args E;
                    /* fresh operands every case, and the repeated
                     * form of each scalar one */
                    for (r = 0; r < 3; r++) {
                        for (k = 0; k < SN * esz; k++) {
                            lcg = lcg * 6364136223846793005ull +
                                  1442695040888963407ull;
                            sbuf[r][k] = (uint8_t)(lcg >> 56);
                        }
                        for (k = 0; k < SN; k++)
                            memcpy(rep[r] + k * esz,
                                   sbuf[r] + (((m >> r) & 1u) ? 0 : k * esz),
                                   esz);
                        op3[r] = rep[r];
                    }
                    memset(d_rep, 0x5a, sizeof d_rep);
                    st = cft_run(dev, CFT_FMA, (cft_format)fmt,
                                 (cft_round)rnd, op3[0], op3[1], op3[2],
                                 d_rep, SN, &f_rep, NULL);
                    CHECK(st == CFT_OK, "scalar: the array-of-copies "
                          "reference run was refused: %s",
                          cft_strerror(st));

                    memset(&E, 0, sizeof E);
                    E.struct_size = sizeof E;
                    E.a = sbuf[0]; E.b = sbuf[1]; E.c = sbuf[2];
                    E.d = d_sc; E.n = SN; E.scalar_mask = m;
                    E.flags_out = &f_sc;
                    memset(d_sc, 0xa5, sizeof d_sc);
                    st = cft_run_ex(dev, CFT_FMA, (cft_format)fmt,
                                    (cft_round)rnd, &E);
                    CHECK(st == CFT_OK,
                          "a scalar operand (mask %lu) on the software "
                          "backend, which publishes CFT_SEQ_FEAT_SCALAR, "
                          "was refused: %s (%s)", (unsigned long)m,
                          cft_strerror(st), cft_last_error());
                    CHECK(memcmp(d_sc, d_rep, SN * esz) == 0 &&
                          f_sc == f_rep,
                          "%s fma rnd %d scalar mask %lu: the scalar run "
                          "is not the run over an array of copies (flags "
                          "0x%lx, want 0x%lx)",
                          cft_format_name((cft_format)fmt), rnd,
                          (unsigned long)m, (unsigned long)f_sc,
                          (unsigned long)f_rep);
                    cases++;

                    /* would a path that ignored the mask have shown? */
                    memset(d_dense, 0x5a, sizeof d_dense);
                    if (cft_run(dev, CFT_FMA, (cft_format)fmt,
                                (cft_round)rnd, sbuf[0], sbuf[1], sbuf[2],
                                d_dense, SN, &f_dense, NULL) == CFT_OK &&
                        (memcmp(d_dense, d_rep, SN * esz) != 0 ||
                         f_dense != f_rep))
                        poisoned++;
                }
            }

            /* cft_reduce_seg against cft_reduce, slice by slice: the
             * bits of every result and the OR of the flags */
            for (oi = 0; oi < sizeof rops / sizeof rops[0]; oi++) {
                for (si = 0; si < sizeof segs / sizeof segs[0]; si++) {
                    const size_t seg = segs[si], nres = NSEG / seg;
                    uint32_t f_seg = 0, f_want = 0;
                    for (k = 0; k < NSEG * esz; k++) {
                        lcg = lcg * 6364136223846793005ull +
                              1442695040888963407ull;
                        ra[k] = (uint8_t)(lcg >> 56);
                        rb[k] = (uint8_t)(lcg >> 48);
                    }
                    memset(d_seg, 0x5a, sizeof d_seg);
                    st = cft_reduce_seg(dev, rops[oi], (cft_format)fmt,
                                        CFT_RNE, ra,
                                        rops[oi] == CFT_DOT ? rb : NULL,
                                        d_seg, NSEG, seg, &f_seg, NULL);
                    CHECK(st == CFT_OK,
                          "cft_reduce_seg %s seg %lu on the software "
                          "backend, which publishes CFT_FEAT_REDUCE_SEG, "
                          "was refused: %s (%s)", cft_op_name(rops[oi]),
                          (unsigned long)seg, cft_strerror(st),
                          cft_last_error());
                    for (q = 0; q < nres; q++) {
                        uint32_t fq = 0;
                        memset(d_one, 0xa5, sizeof d_one);
                        st = cft_reduce(dev, rops[oi], (cft_format)fmt,
                                        CFT_RNE, ra + q * seg * esz,
                                        rops[oi] == CFT_DOT
                                            ? rb + q * seg * esz : NULL,
                                        d_one, seg, &fq, NULL);
                        CHECK(st == CFT_OK &&
                              memcmp(d_one, d_seg + q * esz, esz) == 0,
                              "%s %s seg %lu: result %lu is not "
                              "cft_reduce over its slice",
                              cft_format_name((cft_format)fmt),
                              cft_op_name(rops[oi]), (unsigned long)seg,
                              (unsigned long)q);
                        f_want |= fq;
                    }
                    CHECK(f_seg == f_want,
                          "%s %s seg %lu: flags 0x%lx, the slices' OR "
                          "0x%lx", cft_format_name((cft_format)fmt),
                          cft_op_name(rops[oi]), (unsigned long)seg,
                          (unsigned long)f_seg, (unsigned long)f_want);
                    rcases++;
                }
            }
        }
        CHECK(cases == 4u * 7u * 5u && rcases == 4u * 5u * 4u,
              "the CAPS2[7]/[8] sweep ran %lu scalar and %lu segmented "
              "cases, want 140 and 80", cases, rcases);
        CHECK(poisoned > 0,
              "no scalar case would have caught a path that ignored "
              "scalar_mask - the poison did not differ, so the "
              "comparison above could not fail");
        if (failures == failures0)
            printf("  the software handle publishes CAPS2[7] and CAPS2[8] "
                   "(seq_features 0x%lx), and both calls are the "
                   "definition: %lu scalar-operand runs, %lu of them where "
                   "an ignored mask would have shown; %lu segmented "
                   "reductions\n", (unsigned long)caps.seq_features,
                   cases, poisoned, rcases);
    }

    /* --- argument checking --------------------------------------- */
    {
        uint8_t a[4], b[4], c[4], d[4];
        put32(a, 0x3f800000); put32(b, 0); put32(c, 0x3f800000);
        CHECK(cft_run(NULL, CFT_ADD, CFT_FP32, CFT_RNE, a, b, c, d, 1,
                      NULL, NULL) == CFT_ERR_INVALID_ARGUMENT, "NULL device");
        CHECK(cft_run(dev, CFT_ADD, (cft_format)4, CFT_RNE, a, b, c, d, 1,
                      NULL, NULL) == CFT_ERR_INVALID_ARGUMENT, "bad format");
        CHECK(cft_run(dev, CFT_ADD, CFT_FP32, (cft_round)5, a, b, c, d, 1,
                      NULL, NULL) == CFT_ERR_INVALID_ARGUMENT, "bad rounding");
        CHECK(cft_run(dev, (cft_op)256, CFT_FP32, CFT_RNE, a, b, c, d, 1,
                      NULL, NULL) == CFT_ERR_INVALID_ARGUMENT,
              "opcode wider than the device's field");
        CHECK(cft_run(dev, CFT_ADD, CFT_FP32, CFT_RNE, a, b, c, NULL, 1,
                      NULL, NULL) == CFT_ERR_INVALID_ARGUMENT, "NULL output");
        CHECK(cft_run(dev, CFT_FMA, CFT_FP32, CFT_RNE, a, NULL, c, d, 1,
                      NULL, NULL) == CFT_ERR_INVALID_ARGUMENT,
              "fma reads b, so a NULL b is an error");

        /* n == 0 is a no-op that still reports clean flags, so a loop
         * with an empty tail does not have to special-case itself. */
        flags = 0xdead;
        CHECK(cft_run(dev, CFT_ADD, CFT_FP32, CFT_RNE, NULL, NULL, NULL,
                      NULL, 0, &flags, NULL) == CFT_OK && flags == 0,
              "n == 0");
    }

    /* --- operands an opcode does not read may be NULL ------------- */
    {
        uint8_t a[4], c[4], d[4];
        put32(a, 0x3f800000);            /* 1.0 */
        put32(c, 0x40000000);            /* 2.0 */
        put32(d, 0);
        flags = 0xdead;
        st = cft_run(dev, CFT_ADD, CFT_FP32, CFT_RNE, a, NULL, c, d, 1,
                     &flags, NULL);
        CHECK(st == CFT_OK && get32(d) == 0x40400000u && flags == 0,
              "add with b NULL: 1+2 = 3, got 0x%08x/0x%02x",
              (unsigned)get32(d), (unsigned)flags);

        put32(a, 0x40000000);            /* 2.0 */
        put32(d, 0);
        flags = 0xdead;
        st = cft_run(dev, CFT_MUL, CFT_FP32, CFT_RNE, a, c, NULL, d, 1,
                     &flags, NULL);
        CHECK(st == CFT_OK && get32(d) == 0x40800000u && flags == 0,
              "mul with c NULL: 2*2 = 4, got 0x%08x/0x%02x",
              (unsigned)get32(d), (unsigned)flags);
    }

    /* --- the output may alias an input ---------------------------- */
    {
        uint8_t a[12], c[12];
        static const uint32_t in[3]   = { 0x3f800000u, 0x40000000u,
                                          0x40400000u };            /* 1 2 3 */
        static const uint32_t want[3] = { 0x40000000u, 0x40400000u,
                                          0x40800000u };            /* 2 3 4 */
        for (i = 0; i < 3; i++) {
            put32(a + 4 * i, in[i]);
            put32(c + 4 * i, 0x3f800000u);
        }
        st = cft_run(dev, CFT_ADD, CFT_FP32, CFT_RNE, a, NULL, c, a, 3,
                     NULL, NULL);
        CHECK(st == CFT_OK, "in-place run: %s", cft_strerror(st));
        for (i = 0; i < 3; i++)
            CHECK(get32(a + 4 * i) == want[i],
                  "in-place element %d: got 0x%08x want 0x%08x",
                  i, (unsigned)get32(a + 4 * i), (unsigned)want[i]);
    }

    /* --- unassigned opcodes compute a defined answer -------------- */
    EXPECT32((cft_op)15,  CFT_RNE, 0x3f800000u, 0, 0x3f800000u,
             0x7fc00000u, CFT_FLAG_INVALID);
    EXPECT32((cft_op)200, CFT_RNE, 0x3f800000u, 0, 0x3f800000u,
             0x7fc00000u, CFT_FLAG_INVALID);

    /* --- rounding, from 754-2019 rather than from either model ----
     *
     * 1.0 +/- 2^-149 is the far-alignment path in miniature: the
     * addend lies far below the product's last bit, so it can only be
     * a sticky bit, and every attribute has to notice it anyway. */
    EXPECT32(CFT_ADD, CFT_RNE, 0x3f800000u, 0, 0x00000001u,
             0x3f800000u, CFT_FLAG_INEXACT);
    EXPECT32(CFT_ADD, CFT_RUP, 0x3f800000u, 0, 0x00000001u,
             0x3f800001u, CFT_FLAG_INEXACT);
    EXPECT32(CFT_ADD, CFT_RDN, 0x3f800000u, 0, 0x00000001u,
             0x3f800000u, CFT_FLAG_INEXACT);
    EXPECT32(CFT_SUB, CFT_RNE, 0x3f800000u, 0, 0x00000001u,
             0x3f800000u, CFT_FLAG_INEXACT);
    EXPECT32(CFT_SUB, CFT_RDN, 0x3f800000u, 0, 0x00000001u,
             0x3f7fffffu, CFT_FLAG_INEXACT);
    EXPECT32(CFT_SUB, CFT_RUP, 0x3f800000u, 0, 0x00000001u,
             0x3f800000u, CFT_FLAG_INEXACT);

    /* 754-2019 7.4: overflow is signalled in every attribute, but only
     * some deliver an infinity. */
    EXPECT32(CFT_MUL, CFT_RNE, 0x7f7fffffu, 0x40000000u, 0,
             0x7f800000u, CFT_FLAG_OVERFLOW | CFT_FLAG_INEXACT);
    EXPECT32(CFT_MUL, CFT_RTZ, 0x7f7fffffu, 0x40000000u, 0,
             0x7f7fffffu, CFT_FLAG_OVERFLOW | CFT_FLAG_INEXACT);
    EXPECT32(CFT_MUL, CFT_RDN, 0x7f7fffffu, 0x40000000u, 0,
             0x7f7fffffu, CFT_FLAG_OVERFLOW | CFT_FLAG_INEXACT);
    EXPECT32(CFT_MUL, CFT_RUP, 0xff7fffffu, 0x40000000u, 0,
             0xff7fffffu, CFT_FLAG_OVERFLOW | CFT_FLAG_INEXACT);

    /* Signed zero, 754-2019 6.3: an exact cancellation is +0 in every
     * attribute except roundTowardNegative. */
    EXPECT32(CFT_SUB, CFT_RNE, 0x3f800000u, 0, 0x3f800000u, 0x00000000u, 0);
    EXPECT32(CFT_SUB, CFT_RDN, 0x3f800000u, 0, 0x3f800000u, 0x80000000u, 0);

    /* Signed zero, 754-2019 9.6: min(+0,-0) is -0, max(+0,-0) is +0. */
    EXPECT32(CFT_MIN, CFT_RNE, 0x00000000u, 0x80000000u, 0, 0x80000000u, 0);
    EXPECT32(CFT_MAX, CFT_RNE, 0x00000000u, 0x80000000u, 0, 0x00000000u, 0);

    /* A signaling NaN raises invalid; abs and negate do not, ever, and
     * they keep the payload (754-2019 5.5.1). */
    EXPECT32(CFT_ADD, CFT_RNE, 0x7f800001u, 0, 0x3f800000u,
             0x7fc00000u, CFT_FLAG_INVALID);
    EXPECT32(CFT_ABS, CFT_RNE, 0xff800001u, 0, 0, 0x7f800001u, 0);
    EXPECT32(CFT_NEG, CFT_RNE, 0x7f800001u, 0, 0, 0xff800001u, 0);
    EXPECT32(CFT_MIN, CFT_RNE, 0x7f800001u, 0x3f800000u, 0,
             0x7fc00000u, CFT_FLAG_INVALID);
    EXPECT32(CFT_MINNUM, CFT_RNE, 0x7f800001u, 0x3f800000u, 0,
             0x3f800000u, CFT_FLAG_INVALID);

    /* --- the same three cases at fp256 ----------------------------
     *
     * Same shape, 237 significand bits and a 2^-262378 perturbation.
     * This is where softfloat.c's bounded alignment earns its keep:
     * the exact difference of these two operands is about 262,000 bits
     * wide, and the answer must still be right to the last bit. */
    {
        uint8_t one[32], minsub[32], up[32], down[32];
        fp256_one(one);
        fp256_min_sub(minsub);
        fp256_next_up_1(up);
        fp256_prev_1(down);

        expect256(dev, "fp256 1 + minsub rne", CFT_ADD, CFT_RNE, one, minsub,
                  one, CFT_FLAG_INEXACT);
        expect256(dev, "fp256 1 + minsub rup", CFT_ADD, CFT_RUP, one, minsub,
                  up, CFT_FLAG_INEXACT);
        expect256(dev, "fp256 1 - minsub rne", CFT_SUB, CFT_RNE, one, minsub,
                  one, CFT_FLAG_INEXACT);
        expect256(dev, "fp256 1 - minsub rdn", CFT_SUB, CFT_RDN, one, minsub,
                  down, CFT_FLAG_INEXACT);
        expect256(dev, "fp256 1 - minsub rup", CFT_SUB, CFT_RUP, one, minsub,
                  one, CFT_FLAG_INEXACT);
    }

    /* --- the argument beat padding rests on ----------------------
     *
     * The tile computes in whole 256-bit beats, so the device backend
     * pads a partial tail with zero operands. That is only sound if a
     * zero operand raises nothing - otherwise a caller's exception
     * flags would depend on the length of their array, which is
     * precisely the kind of silent, length-dependent result this
     * project exists to remove.
     *
     * So check it rather than assert it, across every opcode the byte
     * can hold, every format and every attribute. An unassigned opcode
     * raises invalid, and that is fine: it raises invalid for the real
     * elements too, so the OR the backend reports is unchanged. */
    {
        int f_i, op_i, r_i, bad = 0;
        uint8_t zero[32], out[32];
        memset(zero, 0, sizeof zero);
        for (f_i = 0; f_i < 4 && bad < 4; f_i++) {
            size_t esz = cft_format_size((cft_format)f_i);
            for (op_i = 0; op_i < 256 && bad < 4; op_i++) {
                uint32_t want;
                /* Reductions are not elementwise and cft_run refuses
                 * them, so there is no padded tail to reason about.
                 * Skipping them here rather than deleting the opcode
                 * from the sweep, because the refusal itself is worth
                 * asserting - checked immediately below. */
                if (op_i == CFT_SUM || op_i == CFT_DOT ||
                    op_i == CFT_SUMSQ || op_i == CFT_SUMABS ||
                    op_i == CFT_MAXALL) {
                    st = cft_run(dev, (cft_op)op_i, (cft_format)f_i,
                                 CFT_RNE, zero, zero, zero, out, 1,
                                 NULL, NULL);
                    if (st != CFT_ERR_INVALID_ARGUMENT) {
                        bad++;
                        CHECK(0, "cft_run(%s) must refuse the reduction "
                                 "opcode %d, got %s",
                              cft_format_name((cft_format)f_i), op_i,
                              cft_strerror(st));
                    }
                    continue;
                }
                /* IMUL was special-cased here - computed, flag-free, and
                 * answered no by cft_supports - until 2026-09-24, when
                 * cft_sf_op_assigned took 30 and cft_supports began
                 * answering from CAPS[28] as it was written to. The
                 * special case collapsed into this line, as it said it
                 * would: the low 32 bits of zero times zero are zero and
                 * nothing is raised, and cft_supports now says yes. */
                want = cft_supports(dev, (cft_op)op_i, (cft_format)f_i)
                       ? 0u : CFT_FLAG_INVALID;
                for (r_i = 0; r_i < 5; r_i++) {
                    uint32_t fl = 0xdead;
                    memset(out, 0xa5, sizeof out);
                    st = cft_run(dev, (cft_op)op_i, (cft_format)f_i,
                                 (cft_round)r_i, zero, zero, zero, out, 1,
                                 &fl, NULL);
                    if (st != CFT_OK || fl != want) {
                        bad++;
                        CHECK(0, "zero padding raises flags: %s op %d "
                                 "rnd %d -> status %s flags 0x%02x, "
                                 "want 0x%02x",
                              cft_format_name((cft_format)f_i), op_i, r_i,
                              cft_strerror(st), (unsigned)fl,
                              (unsigned)want);
                        break;
                    }
                    (void)esz;
                }
            }
        }
        if (!bad)
            printf("  zero operands are flag-free for all 256 opcodes "
                   "x 4 formats x 5 attributes\n");
    }

    /* --- how work is split across compute units -------------------
     *
     * This is the arithmetic that decides whether a four-tile run
     * computes every element exactly once and writes it to the right
     * offset. Until it was factored out of the XRT backend, reaching
     * it needed a card - which is a poor place to discover an
     * off-by-one. It needs nothing here, so it is checked over every
     * interesting size and tile count.
     */
    {
        static const size_t sizes[] = {
            1, 2, 3, 4, 5, 7, 8, 9, 15, 16, 17, 31, 32, 33, 63, 64, 65,
            127, 128, 129, 255, 256, 257, 1000, 4096, 4097, 100000
        };
        static const size_t esizes[] = {4, 8, 16, 32};
        /* Sized for the largest tile count the contract is checked at,
         * not the largest one any device has. The property being tested
         * - that the answer and the padding total do not depend on how
         * the work was split - has to hold at counts no bitstream can
         * reach yet, because it is impossible to retrofit once the
         * abstraction has leaked and there is no way to bisect a
         * 64-tile disagreement after the fact. Testing it is free; the
         * hardware existing is not a prerequisite. */
#define SLICE_MAX_TILES 64
        cft_slice sl[SLICE_MAX_TILES + 1];
        size_t si, ei, tiles;
        int bad = 0;

        for (ei = 0; ei < 4 && !bad; ei++) {
            size_t esz = esizes[ei], epb = 32 / esz;
            for (si = 0; si < sizeof sizes / sizeof sizes[0] && !bad; si++) {
                size_t n = sizes[si];
                size_t beats = (n + epb - 1) / epb;
                size_t reference_padded = 0;
                for (tiles = 1; tiles <= SLICE_MAX_TILES && !bad; tiles++) {
                    size_t k = cft_plan_slices(n, esz, tiles, sl);
                    size_t covered = 0, total_padded = 0, j;

                    if (k == 0 || k > tiles) {
                        CHECK(0, "esz %lu n %lu tiles %lu: %lu slices",
                              (unsigned long)esz, (unsigned long)n,
                              (unsigned long)tiles, (unsigned long)k);
                        bad = 1;
                        break;
                    }
                    for (j = 0; j < k; j++) {
                        /* contiguous, in order, starting at zero */
                        if (sl[j].first_elem != covered) {
                            CHECK(0, "esz %lu n %lu tiles %lu slice %lu "
                                     "starts at %lu, expected %lu",
                                  (unsigned long)esz, (unsigned long)n,
                                  (unsigned long)tiles, (unsigned long)j,
                                  (unsigned long)sl[j].first_elem,
                                  (unsigned long)covered);
                            bad = 1;
                            break;
                        }
                        /* a whole number of beats, or the engine's
                         * beat count truncates the tail away */
                        if (sl[j].padded % epb) {
                            CHECK(0, "esz %lu n %lu tiles %lu slice %lu "
                                     "is %lu elements, not whole beats",
                                  (unsigned long)esz, (unsigned long)n,
                                  (unsigned long)tiles, (unsigned long)j,
                                  (unsigned long)sl[j].padded);
                            bad = 1;
                            break;
                        }
                        if (sl[j].real == 0 || sl[j].real > sl[j].padded) {
                            CHECK(0, "esz %lu n %lu tiles %lu slice %lu "
                                     "real %lu padded %lu",
                                  (unsigned long)esz, (unsigned long)n,
                                  (unsigned long)tiles, (unsigned long)j,
                                  (unsigned long)sl[j].real,
                                  (unsigned long)sl[j].padded);
                            bad = 1;
                            break;
                        }
                        covered += sl[j].real;
                        total_padded += sl[j].padded;
                    }
                    if (bad)
                        break;
                    if (covered != n) {
                        CHECK(0, "esz %lu n %lu tiles %lu covers %lu",
                              (unsigned long)esz, (unsigned long)n,
                              (unsigned long)tiles, (unsigned long)covered);
                        bad = 1;
                        break;
                    }
                    /* The property the flags depend on: the total
                     * amount of padding does not vary with the tile
                     * count, so neither does the sticky word. */
                    if (tiles == 1)
                        reference_padded = total_padded;
                    else if (total_padded != reference_padded) {
                        CHECK(0, "esz %lu n %lu: %lu tiles pad %lu "
                                 "elements, 1 tile pads %lu - the flags "
                                 "would depend on the tile count",
                              (unsigned long)esz, (unsigned long)n,
                              (unsigned long)tiles,
                              (unsigned long)total_padded,
                              (unsigned long)reference_padded);
                        bad = 1;
                        break;
                    }
                    if (total_padded != beats * epb) {
                        CHECK(0, "esz %lu n %lu tiles %lu: padded total "
                                 "%lu, expected %lu",
                              (unsigned long)esz, (unsigned long)n,
                              (unsigned long)tiles,
                              (unsigned long)total_padded,
                              (unsigned long)(beats * epb));
                        bad = 1;
                        break;
                    }
                }
            }
        }
        CHECK(cft_plan_slices(0, 4, 4, sl) == 0, "n = 0 makes no slices");
        if (!bad)
            printf("  work splits correctly for 27 sizes x 4 formats x "
                   "64 tile counts, and the padding total never depends "
                   "on the tile count\n");
    }

    /* --- which tiles a device opens: CFT_XRT_TILES (2026-09-25) -----
     *
     * host/src/tile_select.h, here for slice.h's reason: the XRT
     * backend's open path reads it, and reaching that needs a card. A
     * selection is a claim about hardware, so the parse is strict and
     * every way a list can be malformed is a refusal with a sentence.
     * tile_select_misreads() holds the accepted forms AND each refusal,
     * and tile_select_loose() - which reads "1 ,3" as tiles 1 and 3 -
     * must be counted wrong by those same checks, or they prove
     * nothing about strictness. */
    {
        int misread = tile_select_misreads(cft_tile_select_parse, 1);
        int caught = tile_select_misreads(tile_select_loose, 0);

        CHECK(caught > 0, "NEGATIVE CONTROL: an atoi-style parse of "
              "CFT_XRT_TILES passed every check, so they cannot tell a "
              "strict parse from a loose one");
        /* The sentence quotes what was written: "650" is refused as tile
         * 650, not as the 65 the capped accumulator stopped at. */
        {
            int o[CFT_TILE_SELECT_MAX];
            char w[320];
            w[0] = 0;
            CHECK(cft_tile_select_parse("650", o, w, sizeof w) == -1 &&
                  strstr(w, "tile 650 is outside") != NULL,
                  "CFT_XRT_TILES=\"650\" refused as: %s", w);
        }
        if (!misread && caught > 0)
            printf("  CFT_XRT_TILES: %d selections read as written, %d "
                   "malformed ones refused with a sentence, and all 64 "
                   "at once; an atoi-style parse is caught on %d\n",
                   (int)(sizeof tile_good / sizeof tile_good[0]),
                   (int)(sizeof tile_bad / sizeof tile_bad[0]), caught);
    }

    /* --- a program run's lanes across tiles: lane_cut.h (2026-09-25) --
     *
     * slice.h's reason once more: the XRT backend cuts a program run's
     * lanes with these two functions, and reaching them there needs a
     * card. Every block a run has must reach exactly one tile lane for
     * lane - windows that tile the caller's buffer, in order, once - and
     * an indexed source must reach every tile whole. The seeded planner
     * is what CFT_XRT_PROGRAM_CUTS fuzzes the card with, so it is also
     * held to actually producing the cuts it exists for: some off a beat
     * boundary, some leaving a tile with nothing. */
    {
        int unaligned = 0, empty = 0, u2 = 0, e2 = 0;
        const int misread = lane_cut_misreads(cft_lane_windows, 4000, 1,
                                              &unaligned, &empty);
        const int caught = lane_cut_misreads(lane_windows_slipped, 4000, 0,
                                             &u2, &e2);
        const int caught_lf = lane_cut_misreads(lane_windows_lf_at_zero,
                                                4000, 0, &u2, &e2);
        cft_slice x[8], y[8], z[8];
        const size_t kx = cft_plan_lane_cuts(1000, 4, 77, x);
        const size_t ky = cft_plan_lane_cuts(1000, 4, 77, y);
        const size_t kz = cft_plan_lane_cuts(1000, 4, 78, z);

        CHECK(unaligned > 0 && empty > 0,
              "lane cut: the seeded planner cut off a beat boundary %d times "
              "and left a tile empty %d times - it must do both, or it is not "
              "fuzzing what it exists for", unaligned, empty);
        CHECK(kx == ky && !memcmp(x, y, kx * sizeof x[0]),
              "lane cut: one seed gave two different sets of cuts");
        CHECK(kz != kx || memcmp(x, z, kx * sizeof x[0]),
              "lane cut: seeds 77 and 78 gave the same cuts");
        CHECK(caught > 0,
              "NEGATIVE CONTROL: a lane cut that sizes the scratch-in block "
              "by the scratch-out width passed every check");
        CHECK(caught_lf > 0,
              "NEGATIVE CONTROL: a lane cut that copies every tile's "
              "per-lane flags block to the caller's lane 0 passed every "
              "check");
        /* cft_tile_order, the scheduler's placement: seed 0 is the
         * identity, any seed is a permutation of the tiles, one (seed,
         * wave) is one order, and the fuzz does move tasks - over many
         * waves some order must differ from the identity, or
         * CFT_XRT_TILE_ORDER tests nothing. The permutation test is held
         * to an order with a repeated tile, which it must reject. */
        {
            static const size_t dup[4] = {0, 2, 2, 3};
            /* Five seeds, the extremes included: until verifier-V4 read
             * it (2026-09-25) this drew every order from 12345 alone and
             * printed "every seeded order". */
            static const uint64_t seeds[5] = {1u, 7u, 12345u,
                                              0x8000000000000000ull,
                                              0xFFFFFFFFFFFFFFFFull};
            /* ...and two that share low bits with them, so a seed read
             * through too few of its bits gives two seeds one placement */
            static const uint64_t seeds7[7] = {1u, 7u, 12345u,
                                               0x8000000000000000ull,
                                               0xFFFFFFFFFFFFFFFFull,
                                               0x10001u, 0x700000007ull};
            size_t ord[64], ord2[64], nt, w, j, s, moved = 0, bad = 0;
            for (nt = 1; nt <= 64; nt++)
                for (w = 0; w < 8; w++) {
                    cft_tile_order(nt, 0, w, ord);
                    for (j = 0; j < nt; j++)
                        if (ord[j] != j)
                            bad++;
                    for (s = 0; s < 5; s++) {
                        cft_tile_order(nt, seeds[s], w, ord);
                        cft_tile_order(nt, seeds[s], w, ord2);
                        if (!tile_order_is_perm(ord, nt) ||
                            memcmp(ord, ord2, nt * sizeof ord[0]))
                            bad++;
                        for (j = 0; j < nt; j++)
                            if (ord[j] != j)
                                moved++;
                    }
                }
            CHECK(!bad, "cft_tile_order: %lu orders not a permutation, not "
                  "the identity at seed 0, or not repeatable",
                  (unsigned long)bad);
            CHECK(moved > 0, "cft_tile_order: a seed never moved a task "
                  "off its tile - the placement fuzz would test nothing");
            CHECK(!tile_order_is_perm(dup, 4),
                  "NEGATIVE CONTROL: an order naming tile 2 twice passed the "
                  "permutation test");
            /* ...and each seed on its own, the waves, every position
             * (verifier-V7: a total over all seeds let a seed that moved
             * nothing, one order for every wave, and a last tile never
             * moved all pass). */
            {
                const unsigned judged = judge_tile_order(cft_tile_order,
                                                         seeds7, 7);
                CHECK(!judged, "cft_tile_order under the seven seeds:%s%s%s%s%s",
                      (judged & 1u) ? " a seed moved no task at some tile "
                                      "count;" : "",
                      (judged & 2u) ? " a seed gave all eight waves one "
                                      "order;" : "",
                      (judged & 4u) ? " a position never moved off its "
                                      "tile;" : "",
                      (judged & 8u) ? " two seeds gave one placement;" : "",
                      (judged & 16u) ? " a seed's waves held fewer than "
                                       "three orders" : "");
                CHECK(judge_tile_order(order_low32, seeds7, 7) & 1u,
                      "NEGATIVE CONTROL: a seed read through its low 32 bits "
                      "(2^63 the identity) passed");
                CHECK(judge_tile_order(order_one_wave, seeds7, 7) & 2u,
                      "NEGATIVE CONTROL: every wave one order passed");
                CHECK(judge_tile_order(order_last_stays, seeds7, 7) & 4u,
                      "NEGATIVE CONTROL: a shuffle that never moves the last "
                      "tile passed");
                CHECK(judge_tile_order(order_all_seed1, seeds7, 7) & 8u,
                      "NEGATIVE CONTROL: every non-zero seed one placement "
                      "passed");
                CHECK(judge_tile_order(order_first_wave, seeds7, 7) & 16u,
                      "NEGATIVE CONTROL: only the first wave shuffled "
                      "passed");
                CHECK(judge_tile_order(order_two_waves, seeds7, 7) & 16u,
                      "NEGATIVE CONTROL: two orders alternating passed");
                CHECK(judge_tile_order(order_low16, seeds7, 7) & 8u,
                      "NEGATIVE CONTROL: a seed read through its low 16 bits "
                      "passed");
                if (!bad && moved && !judged)
                    printf("  tile order: 64 tile counts x 8 waves, seed 0 "
                           "the identity, five seeds' orders each a "
                           "permutation and repeatable, %lu tasks moved; "
                           "under seven seeds every seed moves tasks and "
                           "varies its waves over three orders or more, no "
                           "two seeds share a placement, every position "
                           "moves; an order naming a tile twice and seven "
                           "wrong shuffles are refused\n",
                           (unsigned long)moved);
            }
        }
        if (!misread && caught > 0 && caught_lf > 0 && unaligned > 0 &&
            empty > 0)
            printf("  lane cut: 4,000 random runs over both planners, every "
                   "block covered exactly once - the per-lane flags block "
                   "among them - and every indexed source whole; %d cuts off "
                   "a beat boundary, %d runs leaving a tile empty; a cut that "
                   "slips scratch-in's width is caught in %d, one that copies "
                   "every tile's flags to lane 0 in %d\n", unaligned, empty,
                   caught, caught_lf);
    }

    /* --- a lane mask cut for one tile (ABI 0.14, R17) -------------
     *
     * host/src/mask_bits.h, here for slice.h's reason and beside it:
     * the XRT backend repacks a tile's mask from the slice's first
     * LANE, which is a bit offset and not a byte one - slice.h cuts in
     * beats and a beat is one lane at fp256, so tile 1 of an fp256 run
     * can begin at bit 4 of byte 1. Reaching that code needs a card;
     * reaching this function needs nothing. A run on one tile starts
     * at lane 0, so that is the only offset today's launches use, and
     * it is the offsets they do NOT use that this exists for. */
    {
        static const size_t lens[] = {1, 2, 7, 8, 9, 15, 16, 17, 31, 32,
                                      33, 63, 64, 65, 127, 128, 129, 255};
        uint8_t msrc[64], mdst[64];
        size_t li, fi, mi;
        int bad = 0;
        for (mi = 0; mi < sizeof msrc; mi++)      /* a pattern, not a fill */
            msrc[mi] = (uint8_t)(mi * 37u + 11u);
        for (li = 0; li < sizeof lens / sizeof lens[0] && !bad; li++) {
            size_t lanes = lens[li];
            for (fi = 0; fi < 64 && !bad; fi++) {
                size_t first = fi;
                size_t nb;
                if ((first + lanes + 7u) / 8u > sizeof msrc)
                    continue;             /* would read past the pattern */
                nb = cft_mask_bytes(lanes);
                memset(mdst, 0x5A, sizeof mdst);
                cft_mask_repack(mdst, msrc, first, lanes);
                for (mi = 0; mi < lanes; mi++) {
                    size_t b = first + mi;
                    int want = (msrc[b >> 3] >> (b & 7u)) & 1;
                    int got = (mdst[mi >> 3] >> (mi & 7u)) & 1;
                    if (want != got) {
                        CHECK(0, "mask repack lanes %lu first %lu: bit %lu "
                              "is %d, source bit %lu is %d",
                              (unsigned long)lanes, (unsigned long)first,
                              (unsigned long)mi, got, (unsigned long)b, want);
                        bad = 1;
                        break;
                    }
                }
                if (!bad && (lanes & 7u) &&
                    (mdst[nb - 1] >> (lanes & 7u)) != 0) {
                    CHECK(0, "mask repack lanes %lu first %lu: the last "
                          "byte carries a lane this tile does not have",
                          (unsigned long)lanes, (unsigned long)first);
                    bad = 1;
                }
                if (!bad && mdst[nb] != 0x5Au) {
                    CHECK(0, "mask repack lanes %lu first %lu: it wrote "
                          "past (lanes + 7) / 8 bytes",
                          (unsigned long)lanes, (unsigned long)first);
                    bad = 1;
                }
            }
        }
        /* first = 0 is a copy, which is the only case a run on one
         * tile produces - stated as its own check so a change that
         * broke exactly it could not hide in the sweep. */
        memset(mdst, 0x5A, sizeof mdst);
        cft_mask_repack(mdst, msrc, 0, 64);
        CHECK(memcmp(mdst, msrc, 8) == 0,
              "a mask cut at lane 0 is a copy of the caller's bytes");
        /* ...and no mask at all is every lane, never no lanes. */
        memset(mdst, 0x00, sizeof mdst);
        cft_mask_repack(mdst, NULL, 0, 20);
        CHECK(mdst[0] == 0xFFu && mdst[1] == 0xFFu && mdst[2] == 0x0Fu &&
              mdst[3] == 0x00u,
              "no mask is every lane, with the last byte's spare bits "
              "clear: %02x %02x %02x", mdst[0], mdst[1], mdst[2]);
        if (!bad)
            printf("  a lane mask repacks correctly for 18 lane counts x "
                   "64 bit offsets, writing no byte past the tile's own "
                   "lanes\n");
    }

    /* --- a tile's capability words, decoded (revision 8's seam) ----
     *
     * host/src/caps_decode.h, here for slice.h's reason: the XRT backend
     * turns VERSION, CAPS and CAPS2 into cft_seq_caps, and that file
     * builds only with XRT, so without this no machine that can build
     * the decode could run it. Held to the words docs/ROADMAP.md's plan
     * computed from rtl/cft_krnl.sv's assembly ("What a revision-8 U50
     * tile reads"), to a seam tile's and revision 7's, and to the rule
     * that a field is believed only on a map that has it. */
    {
        static const struct {
            const char *what;
            uint32_t ver, caps, caps2;
            uint32_t features, insns, deposits, consts, scratch;
        } cw[] = {
            /* revision 8's seam: every new bit zero, revision 7's words */
            { "a seam tile at the U50's capacities", 0xB00u, 0x19FAFFFFu,
              0x000007FBu, 0x7F1Fu, 32768u, 1024u, 512u, 2048u },
            { "a seam tile at the open-core capacities", 0xB00u,
              0x19E6FFFFu, 0x000007F8u, 0x7F1Fu, 16384u, 64u, 512u, 256u },
            { "revision 7's U50 tile", 0xA00u, 0x19FAFFFFu, 0x000007FBu,
              0x7F1Fu, 32768u, 1024u, 512u, 2048u },
            /* the plan's revision-8 U50 words (streaming at 2^24) */
            { "revision 8 at 2,048 slots", 0xB00u, 0x19FAFFFFu,
              0x00187FFBu, 0x7FF1Fu, 1u << 24, 1024u, 512u, 2048u },
            { "revision 8 at 4,096 slots", 0xB00u, 0x19FAFFFFu,
              0x00187FFCu, 0x7FF1Fu, 1u << 24, 1024u, 512u, 4096u },
            { "revision 8 without R21", 0xB00u, 0x19FAFFFFu, 0x001877FBu,
              0x77F1Fu, 1u << 24, 1024u, 512u, 2048u },
            /* behind 0xB00 only: an 0xA00 map cannot have these fields,
             * and a word that claims them is not believed */
            { "revision 8's fields on an 0xA00 map", 0xA00u, 0x19FAFFFFu,
              0x00187FFBu, 0x7F1Fu, 32768u, 1024u, 512u, 2048u },
            /* a five-bit log2, 31 its top */
            { "CAPS2[20:16] at its top", 0xB00u, 0x19FAFFFFu, 0x001F07FBu,
              0x7F1Fu, 1u << 31, 1024u, 512u, 2048u },
            /* no CAPS2 below 0x800: revision 2's words, one handed in */
            { "a 0x700 tile, whose map has no CAPS2", 0x700u, 0x18C6FF7Fu,
              0x00187FFBu, 0x17u, 4096u, 64u, 256u, 0u },
            /* card day: no capacity fields, every one UNKNOWN */
            { "a 0x410 tile, before the capacity fields", 0x410u,
              0x00001F0Fu, 0u, 0x0u, 0u, 0u, 0u, 0u }
        };
        size_t k;
        int bad = 0;
        for (k = 0; k < sizeof cw / sizeof cw[0]; k++) {
            cft_seq_caps sc;
            memset(&sc, 0xA5, sizeof sc);
            cft_caps_decode(cw[k].ver, cw[k].caps, cw[k].caps2, &sc);
            if (sc.features != cw[k].features || sc.max_insns != cw[k].insns ||
                sc.max_deposits != cw[k].deposits ||
                sc.max_consts != cw[k].consts ||
                sc.max_scratch != cw[k].scratch) {
                CHECK(0, "caps decode, %s (VERSION 0x%x, CAPS 0x%08lx, CAPS2 "
                      "0x%08lx): features 0x%lx insns %lu deposits %lu consts "
                      "%lu scratch %lu, want 0x%lx %lu %lu %lu %lu",
                      cw[k].what, (unsigned)cw[k].ver,
                      (unsigned long)cw[k].caps, (unsigned long)cw[k].caps2,
                      (unsigned long)sc.features, (unsigned long)sc.max_insns,
                      (unsigned long)sc.max_deposits,
                      (unsigned long)sc.max_consts,
                      (unsigned long)sc.max_scratch,
                      (unsigned long)cw[k].features, (unsigned long)cw[k].insns,
                      (unsigned long)cw[k].deposits,
                      (unsigned long)cw[k].consts,
                      (unsigned long)cw[k].scratch);
                bad = 1;
            }
        }
        /* The plan's other claim: a revision-8 U50 tile's seq_features is
         * the software handle's word at ABI 0.17. One word, two sources -
         * cft_sw_seq_caps and device.c's publishing, against the decode of
         * the words rtl/cft_krnl.sv will assemble. */
        {
            cft_caps swc;
            cft_seq_caps sc;
            memset(&swc, 0, sizeof swc);
            swc.struct_size = sizeof swc;
            cft_caps_decode(0xB00u, 0x19FAFFFFu, 0x00187FFBu, &sc);
            CHECK(cft_get_caps(dev, &swc) == CFT_OK &&
                  swc.seq_features == sc.features,
                  "the software handle publishes seq_features 0x%lx and a "
                  "revision-8 U50 tile's words decode to 0x%lx; the plan "
                  "says they are one word",
                  (unsigned long)swc.seq_features, (unsigned long)sc.features);
            if (swc.seq_features != sc.features)
                bad = 1;
        }
        if (!bad)
            printf("  capability words: %lu decodes as the plan computed "
                   "them - a seam tile seq_features 0x7f1f and 32,768 "
                   "instructions, revision 8 0x7ff1f (0x77f1f without "
                   "R21) and 2^24, nothing of revision 8 believed below "
                   "0xB00 - and the software handle's word is revision "
                   "8's\n", (unsigned long)(sizeof cw / sizeof cw[0]));
    }

    /* --- divide and square root ----------------------------------
     *
     * The arithmetic proof lives in tests/divsqrt_check.py (the whole
     * operand matrix against the model); what belongs here is the API
     * contract and the answers an independent reading of 754 pins
     * down: special classes, the two divide flags, exactness where
     * the result is representable, and the aliasing promise. 1/3 and
     * sqrt(2) are the two inexact literals, derived by hand from the
     * standard the way this file's other constants are. */
    CHECK(cft_supports(dev, CFT_RECIP_SEED, CFT_FP32) == 1,
          "recip_seed supported");
    CHECK(cft_supports(dev, CFT_RSQRT_SEED, CFT_FP256) == 1,
          "rsqrt_seed supported");
    CHECK(strcmp(cft_op_name(CFT_RECIP_SEED), "recip_seed") == 0 &&
          strcmp(cft_op_name(CFT_RSQRT_SEED), "rsqrt_seed") == 0,
          "seed op names");

    {
        uint8_t a[8], b[8], d[8];
        uint32_t f2;

        /* the seed opcodes are QUIET, and their special classes are
         * the limit values - both facts cft_div depends on */
        f2 = 0xdead;
        put32(a, 0x7f800000u);                       /* +inf */
        st = cft_run(dev, CFT_RECIP_SEED, CFT_FP32, CFT_RNE, a, NULL, NULL,
                     d, 1, &f2, NULL);
        CHECK(st == CFT_OK && get32(d) == 0 && f2 == 0,
              "recip_seed(+inf) = +0, quietly");
        put32(a, 0x80000000u);                       /* -0 */
        st = cft_run(dev, CFT_RECIP_SEED, CFT_FP32, CFT_RNE, a, NULL, NULL,
                     d, 1, &f2, NULL);
        CHECK(st == CFT_OK && get32(d) == 0xff800000u && f2 == 0,
              "recip_seed(-0) = -inf, quietly");
        put32(a, 0xbf800000u);                       /* -1 */
        st = cft_run(dev, CFT_RSQRT_SEED, CFT_FP32, CFT_RNE, a, NULL, NULL,
                     d, 1, &f2, NULL);
        CHECK(st == CFT_OK && get32(d) == 0x7fc00000u && f2 == 0,
              "rsqrt_seed(-1) = qNaN, quietly");

        /* divide: specials and both divide flags */
        put32(a, 0x3f800000u); put32(b, 0x40000000u);
        f2 = 0xdead;
        st = cft_div(dev, CFT_FP32, CFT_RNE, a, b, d, 1, &f2, NULL);
        CHECK(st == CFT_OK && get32(d) == 0x3f000000u && f2 == 0,
              "1/2 = 0.5 exactly, no flags");
        put32(a, 0x3f800000u); put32(b, 0);
        st = cft_div(dev, CFT_FP32, CFT_RNE, a, b, d, 1, &f2, NULL);
        CHECK(st == CFT_OK && get32(d) == 0x7f800000u &&
              f2 == CFT_FLAG_DIVBYZERO, "1/0 = +inf, divideByZero");
        put32(a, 0); put32(b, 0);
        st = cft_div(dev, CFT_FP32, CFT_RNE, a, b, d, 1, &f2, NULL);
        CHECK(st == CFT_OK && get32(d) == 0x7fc00000u &&
              f2 == CFT_FLAG_INVALID, "0/0 = qNaN, invalid");
        put32(a, 0x3f800000u); put32(b, 0x40400000u);
        st = cft_div(dev, CFT_FP32, CFT_RNE, a, b, d, 1, &f2, NULL);
        CHECK(st == CFT_OK && get32(d) == 0x3eaaaaabu &&
              f2 == CFT_FLAG_INEXACT,
              "1/3 rounds to 0x3eaaaaab, inexact");

        /* d may alias a - each chunk reads its slice before writing */
        put32(a, 0x40400000u); put32(b, 0x40000000u);
        st = cft_div(dev, CFT_FP32, CFT_RNE, a, b, a, 1, &f2, NULL);
        CHECK(st == CFT_OK && get32(a) == 0x3fc00000u,
              "3/2 in place = 1.5");

        /* square root */
        put32(a, 0x40800000u);
        st = cft_sqrt(dev, CFT_FP32, CFT_RNE, a, d, 1, &f2, NULL);
        CHECK(st == CFT_OK && get32(d) == 0x40000000u && f2 == 0,
              "sqrt(4) = 2 exactly, no flags");
        put32(a, 0x80000000u);
        st = cft_sqrt(dev, CFT_FP32, CFT_RNE, a, d, 1, &f2, NULL);
        CHECK(st == CFT_OK && get32(d) == 0x80000000u && f2 == 0,
              "sqrt(-0) = -0, no flags");
        put32(a, 0xbf800000u);
        st = cft_sqrt(dev, CFT_FP32, CFT_RNE, a, d, 1, &f2, NULL);
        CHECK(st == CFT_OK && get32(d) == 0x7fc00000u &&
              f2 == CFT_FLAG_INVALID, "sqrt(-1) = qNaN, invalid");
        put32(a, 0x40000000u);
        st = cft_sqrt(dev, CFT_FP32, CFT_RNE, a, d, 1, &f2, NULL);
        CHECK(st == CFT_OK && get32(d) == 0x3fb504f3u &&
              f2 == CFT_FLAG_INEXACT,
              "sqrt(2) rounds to 0x3fb504f3, inexact");

        /* argument contract, mirroring cft_run's shape */
        CHECK(cft_div(dev, CFT_FP32, CFT_RNE, a, b, d, 0, &f2, NULL)
              == CFT_OK && f2 == 0, "n = 0 succeeds with clean flags");
        CHECK(cft_div(dev, CFT_FP32, CFT_RNE, a, NULL, d, 1, NULL, NULL)
              == CFT_ERR_INVALID_ARGUMENT, "divide needs b");
        CHECK(cft_div(dev, CFT_FP32, CFT_RNE, NULL, b, d, 1, NULL, NULL)
              == CFT_ERR_INVALID_ARGUMENT, "divide needs a");
        CHECK(cft_sqrt(dev, (cft_format)6, CFT_RNE, a, d, 1, NULL, NULL)
              == CFT_ERR_INVALID_ARGUMENT, "bad format refused");
    }

    {
        /* fp256, the format no host hardware anchors: 1/1 and sqrt(1)
         * are exact identities the field layout pins by hand. */
        uint8_t a[32], b[32], d[32];
        uint32_t f2 = 0xdead;
        fp256_one(a);
        fp256_one(b);
        st = cft_div(dev, CFT_FP256, CFT_RNE, a, b, d, 1, &f2, NULL);
        CHECK(st == CFT_OK && memcmp(d, a, 32) == 0 && f2 == 0,
              "fp256 1/1 = 1 exactly");
        memset(d, 0xAA, sizeof d);
        st = cft_sqrt(dev, CFT_FP256, CFT_RNE, a, d, 1, &f2, NULL);
        CHECK(st == CFT_OK && memcmp(d, a, 32) == 0 && f2 == 0,
              "fp256 sqrt(1) = 1 exactly");
    }

    /* --- the phase-1 transcendentals (ABI 0.3) ---------------------
     *
     * Same charter as the block below: host/tests/transcend_check.py
     * and the MPFR oracle prove these at scale, so what belongs HERE
     * is the refusals, the aliasing promise, and the handful of edges
     * whose expected bits come from reading clause 9.2.1 by hand -
     * including the two rows implementations most often get wrong. */
    {
        uint8_t a[8], b[8], d[8];
        uint32_t f3 = 0xdead;

        put32(a, 0x3f800000u);                        /* 1.0 */
        put32(b, 0x40000000u);                        /* 2.0 */
        CHECK(cft_exp(dev, CFT_FP32, (cft_round)-1, a, d, 1, &f3)
              == CFT_ERR_INVALID_ARGUMENT, "exp refuses rnd = -1");
        CHECK(cft_pow(dev, CFT_FP32, (cft_round)5, a, b, d, 1, &f3)
              == CFT_ERR_INVALID_ARGUMENT, "pow refuses rnd = 5");
        CHECK(cft_log(dev, (cft_format)9, CFT_RNE, a, d, 1, &f3)
              == CFT_ERR_INVALID_ARGUMENT, "log refuses a bad format");
        CHECK(cft_pow(dev, CFT_FP32, CFT_RNE, a, NULL, d, 1, &f3)
              == CFT_ERR_INVALID_ARGUMENT, "pow needs b");
        CHECK(cft_hypot(dev, CFT_FP32, CFT_RNE, a, NULL, d, 1, &f3)
              == CFT_ERR_INVALID_ARGUMENT, "hypot needs b");
        f3 = 0xdead;
        CHECK(cft_exp(dev, CFT_FP32, CFT_RNE, NULL, NULL, 0, &f3)
              == CFT_OK && f3 == 0, "exp n = 0 succeeds, clean flags");

        /* Hand-derived clause 9.2.1 rows. exp(-inf) is +0 and silent;
         * expm1(-0) keeps the sign, which is half of why expm1 exists;
         * log(+0) is -inf with divideByZero; pow(qNaN, +0) is 1 for
         * ANY x; and pow(+0, -inf) is the |x| < 1 row - +inf, and it
         * signals NOTHING, because the divideByZero is the pole at a
         * finite negative exponent rather than the limit. */
        put32(a, 0xff800000u);
        st = cft_exp(dev, CFT_FP32, CFT_RNE, a, d, 1, &f3);
        CHECK(st == CFT_OK && get32(d) == 0x00000000u && f3 == 0,
              "exp(-inf) = +0, silent");
        put32(a, 0x80000000u);
        st = cft_expm1(dev, CFT_FP32, CFT_RNE, a, d, 1, &f3);
        CHECK(st == CFT_OK && get32(d) == 0x80000000u && f3 == 0,
              "expm1(-0) = -0, silent");
        st = cft_log1p(dev, CFT_FP32, CFT_RNE, a, d, 1, &f3);
        CHECK(st == CFT_OK && get32(d) == 0x80000000u && f3 == 0,
              "log1p(-0) = -0, silent");
        put32(a, 0x00000000u);
        st = cft_log(dev, CFT_FP32, CFT_RNE, a, d, 1, &f3);
        CHECK(st == CFT_OK && get32(d) == 0xff800000u &&
              f3 == CFT_FLAG_DIVBYZERO, "log(+0) = -inf, divideByZero");
        put32(a, 0xbf800000u);
        st = cft_log1p(dev, CFT_FP32, CFT_RNE, a, d, 1, &f3);
        CHECK(st == CFT_OK && get32(d) == 0xff800000u &&
              f3 == CFT_FLAG_DIVBYZERO, "log1p(-1) = -inf, divideByZero");
        put32(a, 0x7fc00000u);
        put32(b, 0x00000000u);
        st = cft_pow(dev, CFT_FP32, CFT_RNE, a, b, d, 1, &f3);
        CHECK(st == CFT_OK && get32(d) == 0x3f800000u && f3 == 0,
              "pow(qNaN, +0) = 1, silent");
        put32(a, 0x00000000u);
        put32(b, 0xff800000u);
        st = cft_pow(dev, CFT_FP32, CFT_RNE, a, b, d, 1, &f3);
        CHECK(st == CFT_OK && get32(d) == 0x7f800000u && f3 == 0,
              "pow(+0, -inf) = +inf and signals NOTHING");
        put32(a, 0x00000000u);
        put32(b, 0xbf800000u);
        st = cft_pow(dev, CFT_FP32, CFT_RNE, a, b, d, 1, &f3);
        CHECK(st == CFT_OK && get32(d) == 0x7f800000u &&
              f3 == CFT_FLAG_DIVBYZERO,
              "pow(+0, -1) = +inf with divideByZero");
        put32(a, 0x7f800000u);
        put32(b, 0x7fc00000u);
        st = cft_hypot(dev, CFT_FP32, CFT_RNE, a, b, d, 1, &f3);
        CHECK(st == CFT_OK && get32(d) == 0x7f800000u && f3 == 0,
              "hypot(+inf, qNaN) = +inf, silent");
        put32(a, 0x40400000u);                        /* 3 */
        put32(b, 0x40800000u);                        /* 4 */
        st = cft_hypot(dev, CFT_FP32, CFT_RNE, a, b, d, 1, &f3);
        CHECK(st == CFT_OK && get32(d) == 0x40a00000u && f3 == 0,
              "hypot(3, 4) = 5 EXACTLY - no inexact");
        put32(a, 0x41200000u);                        /* 10 */
        st = cft_log10(dev, CFT_FP32, CFT_RNE, a, d, 1, &f3);
        CHECK(st == CFT_OK && get32(d) == 0x3f800000u && f3 == 0,
              "log10(10) = 1 EXACTLY");
        put32(a, 0x41000000u);                        /* 8 */
        st = cft_log2(dev, CFT_FP32, CFT_RNE, a, d, 1, &f3);
        CHECK(st == CFT_OK && get32(d) == 0x40400000u && f3 == 0,
              "log2(8) = 3 EXACTLY");
        st = cft_exp2(dev, CFT_FP32, CFT_RNE, d, d, 1, &f3);   /* aliased */
        CHECK(st == CFT_OK && get32(d) == 0x41000000u && f3 == 0,
              "exp2(3) = 8 EXACTLY, and d may alias a");

        /* The neighbour rule, which the sabotage run of 2026-09-02
         * showed this file could not catch: exp of an argument below
         * 2^-(p+3) is one half-gap above 1, so it rounds to 1 in four
         * attributes and to nextUp(1) in the fifth, and no working
         * precision decides that - only the SIDE does. expm1 and log1p
         * of the same argument go opposite ways for the same reason,
         * and both land subnormal, so both are tiny AND inexact. */
        put32(a, 0x00000001u);                        /* min subnormal */
        st = cft_exp(dev, CFT_FP32, CFT_RNE, a, d, 1, &f3);
        CHECK(st == CFT_OK && get32(d) == 0x3f800000u &&
              f3 == CFT_FLAG_INEXACT,
              "exp(min subnormal) = 1, inexact");
        st = cft_exp(dev, CFT_FP32, CFT_RUP, a, d, 1, &f3);
        CHECK(st == CFT_OK && get32(d) == 0x3f800001u &&
              f3 == CFT_FLAG_INEXACT,
              "exp(min subnormal) upward = nextUp(1)");
        st = cft_expm1(dev, CFT_FP32, CFT_RTZ, a, d, 1, &f3);
        CHECK(st == CFT_OK && get32(d) == 0x00000001u &&
              f3 == (CFT_FLAG_INEXACT | CFT_FLAG_UNDERFLOW),
              "expm1(min subnormal) toward zero stays there, tiny+inexact");
        st = cft_log1p(dev, CFT_FP32, CFT_RDN, a, d, 1, &f3);
        CHECK(st == CFT_OK && get32(d) == 0x00000000u &&
              f3 == (CFT_FLAG_INEXACT | CFT_FLAG_UNDERFLOW),
              "log1p(min subnormal) downward is +0, tiny+inexact");
        st = cft_log1p(dev, CFT_FP32, CFT_RNE, a, d, 1, &f3);
        CHECK(st == CFT_OK && get32(d) == 0x00000001u &&
              f3 == (CFT_FLAG_INEXACT | CFT_FLAG_UNDERFLOW),
              "log1p(min subnormal) to nearest stays put, tiny+inexact");
    }

    /* --- the phase-2 trigonometrics (ABI 0.4) ----------------------
     *
     * Same charter again: the refusals, the aliasing rule, the exact
     * cases whose bits come from reading the standard rather than from
     * running the library, and - because the 2026-09-02 sabotage run
     * showed this file could not catch a flipped neighbour SIDE - one
     * case from every neighbour family this set has.
     */
    {
        uint8_t a[4], b[4], d[4];
        uint32_t f3 = 0xdead;

        put32(a, 0x3f800000u);                       /* 1.0f */
        CHECK(cft_sinpi(dev, CFT_FP32, (cft_round)-1, a, d, 1, &f3)
                  == CFT_ERR_INVALID_ARGUMENT,
              "cft_sinpi refuses an out-of-range rounding attribute");
        CHECK(cft_atan2(dev, CFT_FP32, (cft_round)7, a, a, d, 1, &f3)
                  == CFT_ERR_INVALID_ARGUMENT,
              "cft_atan2 refuses an out-of-range rounding attribute");
        CHECK(cft_atan(dev, (cft_format)9, CFT_RNE, a, d, 1, &f3)
                  == CFT_ERR_INVALID_ARGUMENT,
              "cft_atan refuses an unknown format");
        CHECK(cft_atan2pi(dev, CFT_FP32, CFT_RNE, a, NULL, d, 1, &f3)
                  == CFT_ERR_INVALID_ARGUMENT,
              "cft_atan2pi refuses a NULL second operand");
        f3 = 0xdead;
        CHECK(cft_tanpi(dev, CFT_FP32, CFT_RNE, NULL, NULL, 0, &f3)
                  == CFT_OK && f3 == 0,
              "cft_tanpi with n == 0 touches nothing and clears the flags");

        /* The exact cases, and they raise NOTHING - which is the whole
         * observable difference between this and an accurate
         * implementation. Niven's theorem is what makes the list
         * finite. */
        put32(a, 0x3f000000u);                       /* 0.5f */
        st = cft_sinpi(dev, CFT_FP32, CFT_RNE, a, d, 1, &f3);
        CHECK(st == CFT_OK && get32(d) == 0x3f800000u && f3 == 0,
              "sinPi(1/2) = 1 EXACTLY");
        st = cft_cospi(dev, CFT_FP32, CFT_RNE, a, d, 1, &f3);
        CHECK(st == CFT_OK && get32(d) == 0x00000000u && f3 == 0,
              "cosPi(1/2) = +0 EXACTLY");
        st = cft_tanpi(dev, CFT_FP32, CFT_RNE, a, d, 1, &f3);
        CHECK(st == CFT_OK && get32(d) == 0x7f800000u &&
              f3 == CFT_FLAG_DIVBYZERO,
              "tanPi(1/2) = +inf with divideByZero");
        put32(a, 0xbf000000u);                       /* -0.5f */
        st = cft_tanpi(dev, CFT_FP32, CFT_RNE, a, d, 1, &f3);
        CHECK(st == CFT_OK && get32(d) == 0xff800000u &&
              f3 == CFT_FLAG_DIVBYZERO,
              "tanPi(-1/2) = -inf with divideByZero");
        put32(a, 0x3f800000u);                       /* 1.0f */
        st = cft_sinpi(dev, CFT_FP32, CFT_RNE, a, d, 1, &f3);
        CHECK(st == CFT_OK && get32(d) == 0x00000000u && f3 == 0,
              "sinPi(1) = +0: the sign of the ARGUMENT, not of (-1)^n");
        st = cft_tanpi(dev, CFT_FP32, CFT_RNE, a, d, 1, &f3);
        CHECK(st == CFT_OK && get32(d) == 0x80000000u && f3 == 0,
              "tanPi(1) = -0, because it is sinPi over cosPi");
        put32(a, 0xbf800000u);                       /* -1.0f */
        st = cft_sinpi(dev, CFT_FP32, CFT_RNE, a, d, 1, &f3);
        CHECK(st == CFT_OK && get32(d) == 0x80000000u && f3 == 0,
              "sinPi(-1) = -0");
        st = cft_acospi(dev, CFT_FP32, CFT_RNE, a, d, 1, &f3);
        CHECK(st == CFT_OK && get32(d) == 0x3f800000u && f3 == 0,
              "acosPi(-1) = 1 EXACTLY");
        st = cft_atanpi(dev, CFT_FP32, CFT_RNE, a, d, 1, &f3);
        CHECK(st == CFT_OK && get32(d) == 0xbe800000u && f3 == 0,
              "atanPi(-1) = -1/4 EXACTLY");
        put32(a, 0x3e800000u);                       /* 0.25f */
        st = cft_tanpi(dev, CFT_FP32, CFT_RNE, a, d, 1, &f3);
        CHECK(st == CFT_OK && get32(d) == 0x3f800000u && f3 == 0,
              "tanPi(1/4) = 1 EXACTLY");
        st = cft_asinpi(dev, CFT_FP32, CFT_RNE, d, d, 1, &f3);  /* aliased */
        CHECK(st == CFT_OK && get32(d) == 0x3f000000u && f3 == 0,
              "asinPi(1) = 1/2 EXACTLY, and d may alias a");
        put32(a, 0x00000000u);
        put32(b, 0x80000000u);                       /* (+0, -0) */
        st = cft_atan2pi(dev, CFT_FP32, CFT_RNE, a, b, d, 1, &f3);
        CHECK(st == CFT_OK && get32(d) == 0x3f800000u && f3 == 0,
              "atan2Pi(+0, -0) = 1 EXACTLY - the row most often missed");
        put32(a, 0x7f800000u);
        st = cft_sinpi(dev, CFT_FP32, CFT_RNE, a, d, 1, &f3);
        CHECK(st == CFT_OK && (get32(d) & 0x7fc00000u) == 0x7fc00000u &&
              f3 == CFT_FLAG_INVALID,
              "sinPi(+inf) is invalid: there is no limit there");
        put32(a, 0x40000000u);                       /* 2.0f */
        st = cft_asin(dev, CFT_FP32, CFT_RNE, a, d, 1, &f3);
        CHECK(st == CFT_OK && (get32(d) & 0x7fc00000u) == 0x7fc00000u &&
              f3 == CFT_FLAG_INVALID,
              "asin(2) is invalid");

        /* One case from every neighbour family, each of which is a
         * SIDE and not a value: no working precision separates these
         * from the number beside them, so a flipped side is invisible
         * to everything except a directed rounding. */
        put32(a, 0x00000001u);                       /* min subnormal */
        st = cft_asin(dev, CFT_FP32, CFT_RNE, a, d, 1, &f3);
        CHECK(st == CFT_OK && get32(d) == 0x00000001u &&
              f3 == (CFT_FLAG_INEXACT | CFT_FLAG_UNDERFLOW),
              "asin(min subnormal) stays put: asin is ABOVE its argument");
        st = cft_asin(dev, CFT_FP32, CFT_RUP, a, d, 1, &f3);
        CHECK(st == CFT_OK && get32(d) == 0x00000002u &&
              f3 == (CFT_FLAG_INEXACT | CFT_FLAG_UNDERFLOW),
              "asin(min subnormal) upward steps off it");
        st = cft_atan(dev, CFT_FP32, CFT_RTZ, a, d, 1, &f3);
        CHECK(st == CFT_OK && get32(d) == 0x00000000u &&
              f3 == (CFT_FLAG_INEXACT | CFT_FLAG_UNDERFLOW),
              "atan(min subnormal) toward zero is +0: atan is BELOW it");
        st = cft_atan(dev, CFT_FP32, CFT_RNE, a, d, 1, &f3);
        CHECK(st == CFT_OK && get32(d) == 0x00000001u &&
              f3 == (CFT_FLAG_INEXACT | CFT_FLAG_UNDERFLOW),
              "atan(min subnormal) to nearest stays put");
        st = cft_cospi(dev, CFT_FP32, CFT_RDN, a, d, 1, &f3);
        CHECK(st == CFT_OK && get32(d) == 0x3f7fffffu &&
              f3 == CFT_FLAG_INEXACT,
              "cosPi(min subnormal) downward is nextDown(1)");
        st = cft_acospi(dev, CFT_FP32, CFT_RDN, a, d, 1, &f3);
        CHECK(st == CFT_OK && get32(d) == 0x3effffffu &&
              f3 == CFT_FLAG_INEXACT,
              "acosPi(min subnormal) downward is nextDown(1/2)");
        put32(a, 0x7f7fffffu);                       /* max finite */
        st = cft_atanpi(dev, CFT_FP32, CFT_RDN, a, d, 1, &f3);
        CHECK(st == CFT_OK && get32(d) == 0x3effffffu &&
              f3 == CFT_FLAG_INEXACT,
              "atanPi(max finite) downward is nextDown(1/2)");
        /* and atan2 beside an exactly dyadic quotient - here the
         * quotient is the subnormal MIDPOINT minSub/2, which is not a
         * representable number at all */
        put32(a, 0x00000001u);
        put32(b, 0x40000000u);                       /* 2.0f */
        st = cft_atan2(dev, CFT_FP32, CFT_RUP, a, b, d, 1, &f3);
        CHECK(st == CFT_OK && get32(d) == 0x00000001u &&
              f3 == (CFT_FLAG_INEXACT | CFT_FLAG_UNDERFLOW),
              "atan2(minSub, 2) upward reaches the smallest subnormal");
        st = cft_atan2(dev, CFT_FP32, CFT_RNE, a, b, d, 1, &f3);
        CHECK(st == CFT_OK && get32(d) == 0x00000000u &&
              f3 == (CFT_FLAG_INEXACT | CFT_FLAG_UNDERFLOW),
              "atan2(minSub, 2) to nearest is +0: just below a midpoint");
    }

    /* --- the phase-3 radian trigonometry and the hyperbolics (ABI 0.5)
     *
     * The same charter: the refusals, the exact cases whose bits come
     * from a theorem rather than from the library, the special rows,
     * one case from every neighbour family - and the reduction's two
     * published worst cases, whose expected bits come from the rule
     * beside 1 and from mpmath at 700 bits, an oracle that shares
     * nothing with the library.
     */
    {
        uint8_t a[8], d[8];
        uint32_t f3 = 0xdead;

        put32(a, 0x3f800000u);                       /* 1.0f */
        CHECK(cft_sin(dev, CFT_FP32, (cft_round)-1, a, d, 1, &f3)
                  == CFT_ERR_INVALID_ARGUMENT,
              "cft_sin refuses an out-of-range rounding attribute");
        CHECK(cft_cosh(dev, (cft_format)9, CFT_RNE, a, d, 1, &f3)
                  == CFT_ERR_INVALID_ARGUMENT,
              "cft_cosh refuses an unknown format");
        f3 = 0xdead;
        CHECK(cft_atanh(dev, CFT_FP32, CFT_RNE, NULL, NULL, 0, &f3)
                  == CFT_OK && f3 == 0,
              "cft_atanh with n == 0 touches nothing and clears the flags");

        /* The exact cases are the zeros - Hermite-Lindemann makes the
         * list a theorem - and every one raises NOTHING. */
        put32(a, 0x80000000u);                       /* -0.0f */
        st = cft_sin(dev, CFT_FP32, CFT_RNE, a, d, 1, &f3);
        CHECK(st == CFT_OK && get32(d) == 0x80000000u && f3 == 0,
              "sin(-0) = -0 EXACTLY");
        st = cft_cos(dev, CFT_FP32, CFT_RNE, a, d, 1, &f3);
        CHECK(st == CFT_OK && get32(d) == 0x3f800000u && f3 == 0,
              "cos(-0) = 1 EXACTLY");
        st = cft_tan(dev, CFT_FP32, CFT_RNE, a, d, 1, &f3);
        CHECK(st == CFT_OK && get32(d) == 0x80000000u && f3 == 0,
              "tan(-0) = -0 EXACTLY");
        st = cft_sinh(dev, CFT_FP32, CFT_RNE, a, d, 1, &f3);
        CHECK(st == CFT_OK && get32(d) == 0x80000000u && f3 == 0,
              "sinh(-0) = -0 EXACTLY");
        st = cft_cosh(dev, CFT_FP32, CFT_RNE, a, d, 1, &f3);
        CHECK(st == CFT_OK && get32(d) == 0x3f800000u && f3 == 0,
              "cosh(-0) = 1 EXACTLY");
        st = cft_tanh(dev, CFT_FP32, CFT_RNE, a, d, 1, &f3);
        CHECK(st == CFT_OK && get32(d) == 0x80000000u && f3 == 0,
              "tanh(-0) = -0 EXACTLY");
        st = cft_asinh(dev, CFT_FP32, CFT_RNE, a, d, 1, &f3);
        CHECK(st == CFT_OK && get32(d) == 0x80000000u && f3 == 0,
              "asinh(-0) = -0 EXACTLY");
        st = cft_atanh(dev, CFT_FP32, CFT_RNE, a, d, 1, &f3);
        CHECK(st == CFT_OK && get32(d) == 0x80000000u && f3 == 0,
              "atanh(-0) = -0 EXACTLY");
        put32(a, 0x3f800000u);                       /* 1.0f */
        st = cft_acosh(dev, CFT_FP32, CFT_RNE, a, d, 1, &f3);
        CHECK(st == CFT_OK && get32(d) == 0x00000000u && f3 == 0,
              "acosh(1) = +0 EXACTLY");
        st = cft_atanh(dev, CFT_FP32, CFT_RNE, a, d, 1, &f3);
        CHECK(st == CFT_OK && get32(d) == 0x7f800000u &&
              f3 == CFT_FLAG_DIVBYZERO,
              "atanh(1) = +inf with divideByZero: the pole");
        put32(a, 0xbf800000u);                       /* -1.0f */
        st = cft_atanh(dev, CFT_FP32, CFT_RNE, a, d, 1, &f3);
        CHECK(st == CFT_OK && get32(d) == 0xff800000u &&
              f3 == CFT_FLAG_DIVBYZERO,
              "atanh(-1) = -inf with divideByZero");
        st = cft_acosh(dev, CFT_FP32, CFT_RNE, a, d, 1, &f3);
        CHECK(st == CFT_OK && (get32(d) & 0x7fc00000u) == 0x7fc00000u &&
              f3 == CFT_FLAG_INVALID,
              "acosh(-1) is invalid: the domain starts at 1");
        put32(a, 0x7f800000u);                       /* +inf */
        st = cft_tanh(dev, CFT_FP32, CFT_RNE, a, d, 1, &f3);
        CHECK(st == CFT_OK && get32(d) == 0x3f800000u && f3 == 0,
              "tanh(+inf) = 1 EXACTLY: a limit that is representable");
        st = cft_sin(dev, CFT_FP32, CFT_RNE, a, d, 1, &f3);
        CHECK(st == CFT_OK && (get32(d) & 0x7fc00000u) == 0x7fc00000u &&
              f3 == CFT_FLAG_INVALID,
              "sin(+inf) is invalid: there is no limit there");
        st = cft_acosh(dev, CFT_FP32, CFT_RNE, a, d, 1, &f3);
        CHECK(st == CFT_OK && get32(d) == 0x7f800000u && f3 == 0,
              "acosh(+inf) = +inf, silent");
        st = cft_atanh(dev, CFT_FP32, CFT_RNE, a, d, 1, &f3);
        CHECK(st == CFT_OK && (get32(d) & 0x7fc00000u) == 0x7fc00000u &&
              f3 == CFT_FLAG_INVALID,
              "atanh(+inf) is invalid");
        put32(a, 0xff800000u);                       /* -inf */
        st = cft_cosh(dev, CFT_FP32, CFT_RNE, a, d, 1, &f3);
        CHECK(st == CFT_OK && get32(d) == 0x7f800000u && f3 == 0,
              "cosh(-inf) = +inf: even");
        st = cft_sinh(dev, CFT_FP32, CFT_RNE, a, d, 1, &f3);
        CHECK(st == CFT_OK && get32(d) == 0xff800000u && f3 == 0,
              "sinh(-inf) = -inf: odd");
        st = cft_acosh(dev, CFT_FP32, CFT_RNE, a, d, 1, &f3);
        CHECK(st == CFT_OK && (get32(d) & 0x7fc00000u) == 0x7fc00000u &&
              f3 == CFT_FLAG_INVALID,
              "acosh(-inf) is invalid");

        /* One case from every neighbour family, each a SIDE and not a
         * value. sin, tanh and asinh lie on the zero side of a tiny
         * argument; tan, sinh and atanh on the far side; cos is below 1
         * and cosh above it. */
        put32(a, 0x00000001u);                       /* min subnormal */
        st = cft_sin(dev, CFT_FP32, CFT_RDN, a, d, 1, &f3);
        CHECK(st == CFT_OK && get32(d) == 0x00000000u &&
              f3 == (CFT_FLAG_INEXACT | CFT_FLAG_UNDERFLOW),
              "sin(min subnormal) downward is +0: sin is BELOW its argument");
        st = cft_sin(dev, CFT_FP32, CFT_RUP, a, d, 1, &f3);
        CHECK(st == CFT_OK && get32(d) == 0x00000001u &&
              f3 == (CFT_FLAG_INEXACT | CFT_FLAG_UNDERFLOW),
              "sin(min subnormal) upward stays put");
        st = cft_tan(dev, CFT_FP32, CFT_RUP, a, d, 1, &f3);
        CHECK(st == CFT_OK && get32(d) == 0x00000002u &&
              f3 == (CFT_FLAG_INEXACT | CFT_FLAG_UNDERFLOW),
              "tan(min subnormal) upward steps off it: tan is ABOVE");
        st = cft_sinh(dev, CFT_FP32, CFT_RUP, a, d, 1, &f3);
        CHECK(st == CFT_OK && get32(d) == 0x00000002u &&
              f3 == (CFT_FLAG_INEXACT | CFT_FLAG_UNDERFLOW),
              "sinh(min subnormal) upward steps off it");
        st = cft_tanh(dev, CFT_FP32, CFT_RTZ, a, d, 1, &f3);
        CHECK(st == CFT_OK && get32(d) == 0x00000000u &&
              f3 == (CFT_FLAG_INEXACT | CFT_FLAG_UNDERFLOW),
              "tanh(min subnormal) toward zero is +0");
        st = cft_asinh(dev, CFT_FP32, CFT_RNE, a, d, 1, &f3);
        CHECK(st == CFT_OK && get32(d) == 0x00000001u &&
              f3 == (CFT_FLAG_INEXACT | CFT_FLAG_UNDERFLOW),
              "asinh(min subnormal) to nearest stays put");
        st = cft_atanh(dev, CFT_FP32, CFT_RDN, a, d, 1, &f3);
        CHECK(st == CFT_OK && get32(d) == 0x00000001u &&
              f3 == (CFT_FLAG_INEXACT | CFT_FLAG_UNDERFLOW),
              "atanh(min subnormal) downward stays put: atanh is ABOVE");
        st = cft_cos(dev, CFT_FP32, CFT_RDN, a, d, 1, &f3);
        CHECK(st == CFT_OK && get32(d) == 0x3f7fffffu &&
              f3 == CFT_FLAG_INEXACT,
              "cos(min subnormal) downward is nextDown(1)");
        st = cft_cosh(dev, CFT_FP32, CFT_RUP, a, d, 1, &f3);
        CHECK(st == CFT_OK && get32(d) == 0x3f800001u &&
              f3 == CFT_FLAG_INEXACT,
              "cosh(min subnormal) upward is nextUp(1)");

        /* The reduction's published worst cases. 16367173 * 2^72 is the
         * binary32 argument nearest a multiple of pi/2 and
         * 0x1.6ac5b262ca1ffp+849 the binary64 one; the search in
         * host/tools/pi_worstcase.py rediscovers both. Both sit beside
         * an ODD multiple, so the sines are 1 minus about 2^-59 and
         * 2^-123 - inside the half gap below 1, where the neighbour
         * rule beside 1 decides: 1 to nearest, nextDown(1) toward
         * zero. The cosines are the reduced arguments themselves (up
         * to sign), and those bits come from mpmath at 700 bits,
         * rounded to the format by hand. */
        put32(a, 0x6f79be45u);
        st = cft_sin(dev, CFT_FP32, CFT_RNE, a, d, 1, &f3);
        CHECK(st == CFT_OK && get32(d) == 0x3f800000u &&
              f3 == CFT_FLAG_INEXACT,
              "sin(binary32 worst case) to nearest is 1");
        st = cft_sin(dev, CFT_FP32, CFT_RTZ, a, d, 1, &f3);
        CHECK(st == CFT_OK && get32(d) == 0x3f7fffffu &&
              f3 == CFT_FLAG_INEXACT,
              "sin(binary32 worst case) toward zero is nextDown(1)");
        st = cft_cos(dev, CFT_FP32, CFT_RNE, a, d, 1, &f3);
        CHECK(st == CFT_OK && get32(d) == 0xb0ddeea9u &&
              f3 == CFT_FLAG_INEXACT,
              "cos(binary32 worst case) is the reduced argument, -1.6148e-9");
        put64(a, UINT64_C(0x7506ac5b262ca1ff));
        st = cft_sin(dev, CFT_FP64, CFT_RNE, a, d, 1, &f3);
        CHECK(st == CFT_OK && get64(d) == UINT64_C(0x3ff0000000000000) &&
              f3 == CFT_FLAG_INEXACT,
              "sin(binary64 worst case) to nearest is 1");
        st = cft_sin(dev, CFT_FP64, CFT_RDN, a, d, 1, &f3);
        CHECK(st == CFT_OK && get64(d) == UINT64_C(0x3fefffffffffffff) &&
              f3 == CFT_FLAG_INEXACT,
              "sin(binary64 worst case) downward is nextDown(1)");
        st = cft_cos(dev, CFT_FP64, CFT_RNE, a, d, 1, &f3);
        CHECK(st == CFT_OK && get64(d) == UINT64_C(0xbc214ae72e6ba22f) &&
              f3 == CFT_FLAG_INEXACT,
              "cos(binary64 worst case) is the reduced argument, -4.687e-19");
    }


    /* --- the rest of table 9.1 (part of the 0.6 step)
     *
     * The same charter as the three phases above: the refusals, the
     * exact cases whose bits come from a theorem rather than from the
     * library, the special rows - including the three where this
     * contract follows 754-2019 and GNU MPFR does not - one case from
     * every neighbour family, and the identity between rootn(x, 2) and
     * squareRoot with the single input where the standard's own NOTE
     * says they differ.
     */
    {
        uint8_t a[8], b[8], d[8];
        uint8_t av[3 * 4], dv[3 * 4];
        int64_t nn[3];
        uint32_t f4 = 0xdead;

        put32(a, 0x40000000u);                       /* 2.0f */
        CHECK(cft_exp2m1(dev, CFT_FP32, (cft_round)-1, a, d, 1, &f4)
                  == CFT_ERR_INVALID_ARGUMENT,
              "cft_exp2m1 refuses an out-of-range rounding attribute");
        CHECK(cft_rsqrt(dev, (cft_format)9, CFT_RNE, a, d, 1, &f4)
                  == CFT_ERR_INVALID_ARGUMENT,
              "cft_rsqrt refuses an unknown format");
        nn[0] = 2;
        CHECK(cft_pown(dev, CFT_FP32, CFT_RNE, a, NULL, d, 1, &f4)
                  == CFT_ERR_INVALID_ARGUMENT,
              "cft_pown refuses a NULL integer-exponent array");
        CHECK(cft_compound(dev, CFT_FP32, CFT_RNE, a, NULL, d, 1, &f4)
                  == CFT_ERR_INVALID_ARGUMENT,
              "cft_compound refuses a NULL integer-exponent array");
        CHECK(cft_rootn(dev, CFT_FP32, CFT_RNE, a, NULL, d, 1, &f4)
                  == CFT_ERR_INVALID_ARGUMENT,
              "cft_rootn refuses a NULL integer-exponent array");
        CHECK(cft_powr(dev, CFT_FP32, CFT_RNE, a, NULL, d, 1, &f4)
                  == CFT_ERR_INVALID_ARGUMENT,
              "cft_powr refuses a NULL second operand");
        f4 = 0xdead;
        CHECK(cft_rootn(dev, CFT_FP32, CFT_RNE, NULL, NULL, NULL, 0, &f4)
                  == CFT_OK && f4 == 0,
              "cft_rootn with n == 0 elements touches nothing");

        /* Exactness, and every one of these is an integer identity
         * rather than a rounding: 2^3 - 1 = 7, 2^-3 - 1 = -7/8,
         * 10^2 = 100, 10^2 - 1 = 99, log2(1 + 3) = 2, log10(1 + 99) = 2,
         * 1/sqrt(4) = 1/2. */
        put32(a, 0x40400000u);                       /* 3.0f */
        st = cft_exp2m1(dev, CFT_FP32, CFT_RNE, a, d, 1, &f4);
        CHECK(st == CFT_OK && get32(d) == 0x40e00000u && f4 == 0,
              "exp2m1(3) = 7 EXACTLY");
        put32(a, 0xc0400000u);                       /* -3.0f */
        st = cft_exp2m1(dev, CFT_FP32, CFT_RNE, a, d, 1, &f4);
        CHECK(st == CFT_OK && get32(d) == 0xbf600000u && f4 == 0,
              "exp2m1(-3) = -7/8 EXACTLY");
        put32(a, 0x80000000u);                       /* -0.0f */
        st = cft_exp2m1(dev, CFT_FP32, CFT_RNE, a, d, 1, &f4);
        CHECK(st == CFT_OK && get32(d) == 0x80000000u && f4 == 0,
              "exp2m1(-0) = -0, silent");
        st = cft_exp10(dev, CFT_FP32, CFT_RNE, a, d, 1, &f4);
        CHECK(st == CFT_OK && get32(d) == 0x3f800000u && f4 == 0,
              "exp10(-0) = 1, silent");
        put32(a, 0x40000000u);                       /* 2.0f */
        st = cft_exp10(dev, CFT_FP32, CFT_RNE, a, d, 1, &f4);
        CHECK(st == CFT_OK && get32(d) == 0x42c80000u && f4 == 0,
              "exp10(2) = 100 EXACTLY");
        st = cft_exp10m1(dev, CFT_FP32, CFT_RNE, a, d, 1, &f4);
        CHECK(st == CFT_OK && get32(d) == 0x42c60000u && f4 == 0,
              "exp10m1(2) = 99 EXACTLY");
        put32(a, 0xbf800000u);                       /* -1.0f */
        st = cft_exp10(dev, CFT_FP32, CFT_RNE, a, d, 1, &f4);
        CHECK(st == CFT_OK && f4 == CFT_FLAG_INEXACT,
              "exp10(-1) is INEXACT: 10^-1 is not a dyadic rational");
        put32(a, 0x40400000u);                       /* 3.0f */
        st = cft_log2p1(dev, CFT_FP32, CFT_RNE, a, d, 1, &f4);
        CHECK(st == CFT_OK && get32(d) == 0x40000000u && f4 == 0,
              "log2p1(3) = 2 EXACTLY: 1 + x is a power of two");
        put32(a, 0xbf000000u);                       /* -0.5f */
        st = cft_log2p1(dev, CFT_FP32, CFT_RNE, a, d, 1, &f4);
        CHECK(st == CFT_OK && get32(d) == 0xbf800000u && f4 == 0,
              "log2p1(-1/2) = -1 EXACTLY: 1 + x is formed on the encoding");
        put32(a, 0x42c60000u);                       /* 99.0f */
        st = cft_log10p1(dev, CFT_FP32, CFT_RNE, a, d, 1, &f4);
        CHECK(st == CFT_OK && get32(d) == 0x40000000u && f4 == 0,
              "log10p1(99) = 2 EXACTLY");
        put32(a, 0x40800000u);                       /* 4.0f */
        st = cft_rsqrt(dev, CFT_FP32, CFT_RNE, a, d, 1, &f4);
        CHECK(st == CFT_OK && get32(d) == 0x3f000000u && f4 == 0,
              "rSqrt(4) = 1/2 EXACTLY: an EVEN power of two");
        put32(a, 0x40000000u);                       /* 2.0f */
        st = cft_rsqrt(dev, CFT_FP32, CFT_RNE, a, d, 1, &f4);
        CHECK(st == CFT_OK && f4 == CFT_FLAG_INEXACT,
              "rSqrt(2) is INEXACT: an odd power of two is not");

        /* exp2m1's exact table runs to |n| = p+1, and p+1 lands on a
         * MIDPOINT - which is exactly why it must be decided by exact
         * arithmetic: no enclosure ever separates a midpoint from
         * either side. Past it the value is still known exactly and is
         * delivered by a SIDE. */
        put32(a, 0x41c00000u);                       /* 24.0f = p */
        st = cft_exp2m1(dev, CFT_FP32, CFT_RNE, a, d, 1, &f4);
        CHECK(st == CFT_OK && get32(d) == 0x4b7fffffu && f4 == 0,
              "exp2m1(24) = 2^24 - 1 EXACTLY at binary32");
        put32(a, 0x41c80000u);                       /* 25.0f = p+1 */
        st = cft_exp2m1(dev, CFT_FP32, CFT_RNE, a, d, 1, &f4);
        CHECK(st == CFT_OK && get32(d) == 0x4c000000u &&
              f4 == CFT_FLAG_INEXACT,
              "exp2m1(25) is the midpoint 2^25 - 1, ties to even");
        put32(a, 0x41d00000u);                       /* 26.0f = p+2 */
        st = cft_exp2m1(dev, CFT_FP32, CFT_RNE, a, d, 1, &f4);
        CHECK(st == CFT_OK && get32(d) == 0x4c800000u &&
              f4 == CFT_FLAG_INEXACT,
              "exp2m1(26) to nearest is 2^26: the side above the midpoint");
        st = cft_exp2m1(dev, CFT_FP32, CFT_RTZ, a, d, 1, &f4);
        CHECK(st == CFT_OK && get32(d) == 0x4c7fffffu &&
              f4 == CFT_FLAG_INEXACT,
              "exp2m1(26) toward zero is nextDown(2^26)");
        put32(a, 0xc1d00000u);                       /* -26.0f */
        st = cft_exp2m1(dev, CFT_FP32, CFT_RNE, a, d, 1, &f4);
        CHECK(st == CFT_OK && get32(d) == 0xbf800000u &&
              f4 == CFT_FLAG_INEXACT,
              "exp2m1(-26) to nearest is -1: inside the half gap above it");
        st = cft_exp2m1(dev, CFT_FP32, CFT_RTZ, a, d, 1, &f4);
        CHECK(st == CFT_OK && get32(d) == 0xbf7fffffu &&
              f4 == CFT_FLAG_INEXACT,
              "exp2m1(-26) toward zero steps off -1");

        /* The three rows where this contract follows the standard and
         * MPFR 4.2.2 does not. Each was measured on this host before it
         * was written down; docs/TRANSCENDENTALS.md quotes the probe. */
        put32(a, 0x00000000u);                       /* +0.0f */
        st = cft_rsqrt(dev, CFT_FP32, CFT_RNE, a, d, 1, &f4);
        CHECK(st == CFT_OK && get32(d) == 0x7f800000u &&
              f4 == CFT_FLAG_DIVBYZERO,
              "rSqrt(+0) = +inf with divideByZero");
        put32(a, 0x80000000u);                       /* -0.0f */
        st = cft_rsqrt(dev, CFT_FP32, CFT_RNE, a, d, 1, &f4);
        CHECK(st == CFT_OK && get32(d) == 0xff800000u &&
              f4 == CFT_FLAG_DIVBYZERO,
              "rSqrt(-0) = MINUS inf: 9.2.1 keeps the sign, mpfr_rec_sqrt "
              "does not");
        put32(a, 0x3f800000u);                       /* 1.0f */
        put32(b, 0x7fc00000u);                       /* qNaN */
        st = cft_powr(dev, CFT_FP32, CFT_RNE, a, b, d, 1, &f4);
        CHECK(st == CFT_OK && (get32(d) & 0x7fc00000u) == 0x7fc00000u &&
              f4 == 0,
              "powr(1, qNaN) is a quiet NaN: the standard's row is "
              "\"for FINITE y\"");
        st = cft_pow(dev, CFT_FP32, CFT_RNE, a, b, d, 1, &f4);
        CHECK(st == CFT_OK && get32(d) == 0x3f800000u && f4 == 0,
              "pow(1, qNaN) is 1 - which is why powr is a second function");
        put32(a, 0xc0000000u);                       /* -2.0f */
        nn[0] = 0;
        st = cft_compound(dev, CFT_FP32, CFT_RNE, a, nn, d, 1, &f4);
        CHECK(st == CFT_OK && (get32(d) & 0x7fc00000u) == 0x7fc00000u &&
              f4 == CFT_FLAG_INVALID,
              "compound(-2, 0) is INVALID: the row is \"1 for x >= -1\"");
        put32(a, 0x7fc00000u);                       /* qNaN */
        st = cft_compound(dev, CFT_FP32, CFT_RNE, a, nn, d, 1, &f4);
        CHECK(st == CFT_OK && get32(d) == 0x3f800000u && f4 == 0,
              "compound(qNaN, 0) is 1: the same row says \"or quiet NaN\"");

        /* The rest of 9.2.1's rows for the four powers. */
        put32(a, 0x7fc00000u);                       /* qNaN */
        nn[0] = 0;
        st = cft_pown(dev, CFT_FP32, CFT_RNE, a, nn, d, 1, &f4);
        CHECK(st == CFT_OK && get32(d) == 0x3f800000u && f4 == 0,
              "pown(qNaN, 0) = 1");
        st = cft_rootn(dev, CFT_FP32, CFT_RNE, a, nn, d, 1, &f4);
        CHECK(st == CFT_OK && (get32(d) & 0x7fc00000u) == 0x7fc00000u &&
              f4 == CFT_FLAG_INVALID,
              "rootn(qNaN, 0) is INVALID: zero is outside the domain for "
              "every x");
        put32(a, 0x80000000u);                       /* -0.0f */
        nn[0] = -3;
        st = cft_pown(dev, CFT_FP32, CFT_RNE, a, nn, d, 1, &f4);
        CHECK(st == CFT_OK && get32(d) == 0xff800000u &&
              f4 == CFT_FLAG_DIVBYZERO,
              "pown(-0, -3) = -inf with divideByZero: n is ODD");
        nn[0] = -2;
        st = cft_pown(dev, CFT_FP32, CFT_RNE, a, nn, d, 1, &f4);
        CHECK(st == CFT_OK && get32(d) == 0x7f800000u &&
              f4 == CFT_FLAG_DIVBYZERO,
              "pown(-0, -2) = PLUS inf: n is even");
        put32(a, 0xc0000000u);                       /* -2.0f */
        nn[0] = 3;
        st = cft_pown(dev, CFT_FP32, CFT_RNE, a, nn, d, 1, &f4);
        CHECK(st == CFT_OK && get32(d) == 0xc1000000u && f4 == 0,
              "pown(-2, 3) = -8 EXACTLY");
        put32(a, 0xbf800000u);                       /* -1.0f */
        nn[0] = -3;
        st = cft_compound(dev, CFT_FP32, CFT_RNE, a, nn, d, 1, &f4);
        CHECK(st == CFT_OK && get32(d) == 0x7f800000u &&
              f4 == CFT_FLAG_DIVBYZERO,
              "compound(-1, -3) = +inf with divideByZero");
        nn[0] = 3;
        st = cft_compound(dev, CFT_FP32, CFT_RNE, a, nn, d, 1, &f4);
        CHECK(st == CFT_OK && get32(d) == 0x00000000u && f4 == 0,
              "compound(-1, 3) = +0, silent");
        put32(a, 0x3f800000u);                       /* 1.0f */
        st = cft_compound(dev, CFT_FP32, CFT_RNE, a, nn, d, 1, &f4);
        CHECK(st == CFT_OK && get32(d) == 0x41000000u && f4 == 0,
              "compound(1, 3) = 8 EXACTLY");
        put32(a, 0x00000000u);                       /* +0.0f */
        put32(b, 0x00000000u);
        st = cft_powr(dev, CFT_FP32, CFT_RNE, a, b, d, 1, &f4);
        CHECK(st == CFT_OK && (get32(d) & 0x7fc00000u) == 0x7fc00000u &&
              f4 == CFT_FLAG_INVALID,
              "powr(+0, +0) is INVALID where pow(+0, +0) is 1");
        put32(a, 0xbf800000u);                       /* -1.0f */
        put32(b, 0x40000000u);                       /* 2.0f */
        st = cft_powr(dev, CFT_FP32, CFT_RNE, a, b, d, 1, &f4);
        CHECK(st == CFT_OK && (get32(d) & 0x7fc00000u) == 0x7fc00000u &&
              f4 == CFT_FLAG_INVALID,
              "powr(-1, 2) is INVALID: powr's domain excludes a negative "
              "base");
        put32(a, 0x40000000u);                       /* 2.0f */
        put32(b, 0x40400000u);                       /* 3.0f */
        st = cft_powr(dev, CFT_FP32, CFT_RNE, a, b, d, 1, &f4);
        CHECK(st == CFT_OK && get32(d) == 0x41000000u && f4 == 0,
              "powr(2, 3) = 8 EXACTLY");

        /* rootn(x, 2) is squareRoot on every input but one, and the
         * exception is the standard's own NOTE. Both are asked here,
         * side by side, so the difference is asserted rather than
         * skipped. */
        put32(a, 0x80000000u);                       /* -0.0f */
        nn[0] = 2;
        st = cft_rootn(dev, CFT_FP32, CFT_RNE, a, nn, d, 1, &f4);
        CHECK(st == CFT_OK && get32(d) == 0x00000000u && f4 == 0,
              "rootn(-0, 2) = PLUS zero (the even-n row)");
        st = cft_sqrt(dev, CFT_FP32, CFT_RNE, a, d, 1, &f4, NULL);
        CHECK(st == CFT_OK && get32(d) == 0x80000000u && f4 == 0,
              "squareRoot(-0) = MINUS zero - the one input where the two "
              "differ, and 9.2.1 says so");
        nn[0] = 3;
        st = cft_rootn(dev, CFT_FP32, CFT_RNE, a, nn, d, 1, &f4);
        CHECK(st == CFT_OK && get32(d) == 0x80000000u && f4 == 0,
              "rootn(-0, 3) = -0: n is odd");
        put32(a, 0x40000000u);                       /* 2.0f */
        nn[0] = 2;
        st = cft_rootn(dev, CFT_FP32, CFT_RTZ, a, nn, d, 1, &f4);
        CHECK(st == CFT_OK && get32(d) == 0x3fb504f3u &&
              f4 == CFT_FLAG_INEXACT,
              "rootn(2, 2) toward zero is sqrt(2) correctly rounded");
        st = cft_sqrt(dev, CFT_FP32, CFT_RTZ, a, d, 1, &f4, NULL);
        CHECK(st == CFT_OK && get32(d) == 0x3fb504f3u &&
              f4 == CFT_FLAG_INEXACT,
              "and cft_sqrt agrees, bits and flags");
        put32(a, 0xc1000000u);                       /* -8.0f */
        nn[0] = 3;
        st = cft_rootn(dev, CFT_FP32, CFT_RNE, a, nn, d, 1, &f4);
        CHECK(st == CFT_OK && get32(d) == 0xc0000000u && f4 == 0,
              "rootn(-8, 3) = -2 EXACTLY: a perfect cube, and n is odd");
        put32(a, 0x00000001u);                       /* min subnormal */
        nn[0] = 1;
        st = cft_rootn(dev, CFT_FP32, CFT_RNE, a, nn, d, 1, &f4);
        CHECK(st == CFT_OK && get32(d) == 0x00000001u && f4 == 0,
              "rootn(x, 1) = x EXACTLY, subnormal and silent");

        /* One case from every neighbour family in this set - and, just
         * as loudly, from the families that have NONE. exp2m1, exp10m1,
         * log2p1 and log10p1 of the smallest subnormal are 0.693x,
         * 2.303x, 1.443x and 0.434x: four different answers, none of
         * them x, which is what "no tiny-argument rule here" means. */
        put32(a, 0x00000001u);                       /* min subnormal */
        st = cft_exp2m1(dev, CFT_FP32, CFT_RNE, a, d, 1, &f4);
        CHECK(st == CFT_OK && get32(d) == 0x00000001u &&
              f4 == (CFT_FLAG_INEXACT | CFT_FLAG_UNDERFLOW),
              "exp2m1(min subnormal) is 0.693x: one subnormal to nearest");
        st = cft_exp2m1(dev, CFT_FP32, CFT_RDN, a, d, 1, &f4);
        CHECK(st == CFT_OK && get32(d) == 0x00000000u &&
              f4 == (CFT_FLAG_INEXACT | CFT_FLAG_UNDERFLOW),
              "and downward it is +0 - so it is NOT beside its argument");
        st = cft_exp10m1(dev, CFT_FP32, CFT_RNE, a, d, 1, &f4);
        CHECK(st == CFT_OK && get32(d) == 0x00000002u &&
              f4 == (CFT_FLAG_INEXACT | CFT_FLAG_UNDERFLOW),
              "exp10m1(min subnormal) is 2.303x: TWO subnormals");
        st = cft_log2p1(dev, CFT_FP32, CFT_RUP, a, d, 1, &f4);
        CHECK(st == CFT_OK && get32(d) == 0x00000002u &&
              f4 == (CFT_FLAG_INEXACT | CFT_FLAG_UNDERFLOW),
              "log2p1(min subnormal) is 1.443x: two subnormals upward");
        st = cft_log10p1(dev, CFT_FP32, CFT_RNE, a, d, 1, &f4);
        CHECK(st == CFT_OK && get32(d) == 0x00000000u &&
              f4 == (CFT_FLAG_INEXACT | CFT_FLAG_UNDERFLOW),
              "log10p1(min subnormal) is 0.434x: +0, below half a subnormal");
        put32(a, 0x30800000u);                       /* 2^-30 */
        st = cft_exp10(dev, CFT_FP32, CFT_RDN, a, d, 1, &f4);
        CHECK(st == CFT_OK && get32(d) == 0x3f800000u &&
              f4 == CFT_FLAG_INEXACT,
              "exp10(2^-30) downward is 1 - the rule beside 1 that DOES "
              "apply");
        st = cft_exp10(dev, CFT_FP32, CFT_RUP, a, d, 1, &f4);
        CHECK(st == CFT_OK && get32(d) == 0x3f800001u &&
              f4 == CFT_FLAG_INEXACT,
              "and upward it is nextUp(1)");
        put32(a, 0x4e800000u);                       /* 2^30 */
        st = cft_log2p1(dev, CFT_FP32, CFT_RNE, a, d, 1, &f4);
        CHECK(st == CFT_OK && get32(d) == 0x41f00000u &&
              f4 == CFT_FLAG_INEXACT,
              "log2p1(2^30) to nearest is 30: an exponentially small step "
              "above a grid point");
        st = cft_log2p1(dev, CFT_FP32, CFT_RUP, a, d, 1, &f4);
        CHECK(st == CFT_OK && get32(d) == 0x41f00001u &&
              f4 == CFT_FLAG_INEXACT,
              "and upward it is nextUp(30) - the side is the whole answer");
        nn[0] = 1;
        st = cft_compound(dev, CFT_FP32, CFT_RNE, a, nn, d, 1, &f4);
        CHECK(st == CFT_OK && get32(d) == 0x4e800000u &&
              f4 == CFT_FLAG_INEXACT,
              "compound(2^30, 1) to nearest is 2^30: 1 is far inside its "
              "gap");
        st = cft_compound(dev, CFT_FP32, CFT_RUP, a, nn, d, 1, &f4);
        CHECK(st == CFT_OK && get32(d) == 0x4e800001u &&
              f4 == CFT_FLAG_INEXACT,
              "and upward it steps off it");

        /* The integer operand is read PER ELEMENT. An implementation
         * that hoisted it out of the batch loop passes every test above
         * and fails this one. */
        put32(av + 0, 0x40000000u);                  /* 2.0f */
        put32(av + 4, 0x40000000u);
        put32(av + 8, 0x40000000u);
        nn[0] = 1; nn[1] = 2; nn[2] = 3;
        st = cft_pown(dev, CFT_FP32, CFT_RNE, av, nn, dv, 3, &f4);
        CHECK(st == CFT_OK && get32(dv + 0) == 0x40000000u &&
              get32(dv + 4) == 0x40800000u &&
              get32(dv + 8) == 0x41000000u && f4 == 0,
              "pown over a batch reads n per element: 2, 4, 8");
    }

    /* --- the clause-5 completion set ------------------------------
     *
     * The check harness proves these against the model at scale; what
     * belongs HERE is this file's charter - refusals, aliasing, and a
     * few edges whose expected bits come from reading 754 by hand.
     * The rnd refusals exist because of a real bug: a (cft_round)-1
     * once slid through a shared validator and computed under a
     * rounding no legal attribute produces. */
    {
        uint8_t a[4 * 8], d[4 * 8];
        int32_t i32out;
        uint32_t f2 = 0xdead;
        int k;

        put32(a, 0x3f000000u);               /* 0.5 */
        CHECK(cft_rint(dev, CFT_FP32, (cft_round)-1, 0, a, d, 1, &f2, NULL)
              == CFT_ERR_INVALID_ARGUMENT, "rint refuses rnd = -1");
        CHECK(cft_rint(dev, CFT_FP32, (cft_round)5, 0, a, d, 1, &f2, NULL)
              == CFT_ERR_INVALID_ARGUMENT, "rint refuses rnd = 5");
        CHECK(cft_scaleb(dev, CFT_FP32, (cft_round)-1, a, -2000000000,
                         d, 1, &f2, NULL)
              == CFT_ERR_INVALID_ARGUMENT,
              "scaleb refuses rnd = -1 on the host path too");
        CHECK(cft_convert(dev, CFT_FP64, CFT_FP32, (cft_round)-1, a, d, 1,
                          &f2) == CFT_ERR_INVALID_ARGUMENT,
              "convert refuses rnd = -1");
        CHECK(cft_cvt_to_i32(dev, CFT_FP32, (cft_round)-1, 0, a, &i32out,
                             1, &f2) == CFT_ERR_INVALID_ARGUMENT,
              "cvt_to refuses rnd = -1");
        CHECK(cft_rem(dev, CFT_FP32, a, NULL, d, 1, &f2)
              == CFT_ERR_INVALID_ARGUMENT, "remainder needs b");
        f2 = 0xdead;
        CHECK(cft_rint(dev, CFT_FP32, CFT_RNE, 0, a, d, 0, &f2, NULL)
              == CFT_OK && f2 == 0, "rint n = 0 succeeds, clean flags");

        /* hand-derived edges: rint(-0.5, RNE) is MINUS zero (5.9's
         * operand-sign rule); nextUp of the least-magnitude negative
         * subnormal is -0 (5.3.1's explicit choice); logB(+0) is -inf
         * with divideByZero; convertToInteger(NaN) delivers INT32_MAX
         * with invalid (the contract's RISC-V table). */
        put32(a, 0xbf000000u);
        st = cft_rint(dev, CFT_FP32, CFT_RNE, 0, a, d, 1, &f2, NULL);
        CHECK(st == CFT_OK && get32(d) == 0x80000000u && f2 == 0,
              "rint(-0.5, rne) = -0, silent");
        put32(a, 0x80000001u);
        st = cft_next_up(dev, CFT_FP32, a, d, 1, &f2);
        CHECK(st == CFT_OK && get32(d) == 0x80000000u && f2 == 0,
              "nextUp(-min_subnormal) = -0");
        put32(a, 0x00000000u);
        st = cft_logb(dev, CFT_FP32, a, d, 1, &f2);
        CHECK(st == CFT_OK && get32(d) == 0xff800000u &&
              f2 == CFT_FLAG_DIVBYZERO, "logB(+0) = -inf, divideByZero");
        put32(a, 0x7fc00000u);
        st = cft_cvt_to_i32(dev, CFT_FP32, CFT_RNE, 0, a, &i32out, 1, &f2);
        CHECK(st == CFT_OK && i32out == 2147483647 &&
              f2 == CFT_FLAG_INVALID, "cvt_to_i32(NaN) = INT32_MAX, invalid");

        /* aliasing: d == a must equal the separate-buffer answer for
         * the same-format entry points, per the header's promise */
        for (k = 0; k < 8; k++)
            put32(a + 4 * k, 0x3f000000u + (uint32_t)k * 0x00100000u);
        st = cft_rint(dev, CFT_FP32, CFT_RUP, 1, a, d, 8, &f2, NULL);
        CHECK(st == CFT_OK, "rint separate buffers");
        st = cft_rint(dev, CFT_FP32, CFT_RUP, 1, a, a, 8, &f2, NULL);
        CHECK(st == CFT_OK && memcmp(a, d, 32) == 0,
              "rint in place matches");
        for (k = 0; k < 8; k++)
            put32(a + 4 * k, 0x3f000000u + (uint32_t)k * 0x00100000u);
        st = cft_scaleb(dev, CFT_FP32, CFT_RNE, a, 130, d, 8, &f2, NULL);
        CHECK(st == CFT_OK, "scaleb separate buffers");
        st = cft_scaleb(dev, CFT_FP32, CFT_RNE, a, 130, a, 8, &f2, NULL);
        CHECK(st == CFT_OK && memcmp(a, d, 32) == 0,
              "scaleb in place matches (staged path)");
    }

    /* --- the augmented arithmetic operations (754-2019 9.5) -------
     *
     * host/tests/augmented_check.py proves these against the model at
     * scale and the published sets replay them; what belongs HERE is
     * this file's charter - refusals, aliasing, and the rows whose
     * expected bits come from reading 9.5 rather than from either
     * implementation.
     *
     * Every anchor below is derivable with the subclause open:
     *
     *  - THE TIE. (1 + 2^-23) + 2^-24 is 1 + 3*2^-24, exactly halfway
     *    between 1 + 2^-23 and 1 + 2^-22. 9.5 delivers "the one with
     *    smaller magnitude", so r is 1 + 2^-23 = 0x3f800001 and the
     *    residual is 2^-24 = 0x33800000. roundTiesToEven would step UP
     *    to 0x3f800002, because the lower neighbour's last bit is odd -
     *    which is why this exact case is the one that separates a
     *    conforming implementation from a plausible one, and why it is
     *    asserted here at binary32 and binary64 both.
     *  - THE OVERFLOW THRESHOLD. 9.5: an infinitely precise result
     *    "with magnitude equal to b^emax x (b - 1/2 b^(1-p)) shall
     *    round to b^emax x (b - b^(1-p))". At binary32 that midpoint is
     *    maxfinite + 2^103, and it lands on maxfinite raising NOTHING,
     *    since inexact is signalled "only when roundTiesTowardZero
     *    overflows". One ulp higher (2^104) is past it, and both
     *    outputs become +infinity with overflow and inexact.
     *  - UNDERFLOW WITHOUT INEXACT. 1 + 2^-149 has an exact residual of
     *    2^-149, which is non-zero and strictly inside +-2^emin, so the
     *    underflow flag rises alone - a combination no other operation
     *    in this library can produce.
     *  - THE ZERO SIGNS. e "is returned with the sign of
     *    roundTiesTowardZero(x + y)" when the residual is zero, so
     *    (-1) + 0 gives (-1, -0); r's own sign is 6.3's, so 1 + (-1)
     *    gives (+0, +0) and -0 - (+0) gives (-0, -0).
     */
    {
        uint8_t a[8 * 8], b[8 * 8], r[8 * 8], e[8 * 8], r2[8 * 8];
        uint32_t fl = 0xdead;
        int k;

        put32(a, 0x3f800001u);               /* 1 + 2^-23 */
        put32(b, 0x33800000u);               /* 2^-24: an exact tie */
        st = cft_augmented_add(dev, CFT_FP32, a, b, r, e, 1, &fl);
        CHECK(st == CFT_OK && get32(r) == 0x3f800001u &&
              get32(e) == 0x33800000u && fl == 0,
              "augmentedAddition breaks the tie toward the SMALLER "
              "magnitude (got r=0x%08x e=0x%08x fl=0x%02x)",
              (unsigned)get32(r), (unsigned)get32(e), (unsigned)fl);
        /* the same operands through ordinary addition step up, which is
         * what makes the line above a test rather than a coincidence */
        st = cft_run(dev, CFT_ADD, CFT_FP32, CFT_RNE, a, NULL, b, r2, 1,
                     NULL, NULL);
        CHECK(st == CFT_OK && get32(r2) == 0x3f800002u,
              "roundTiesToEven steps up from that midpoint");

        put64(a, UINT64_C(0x3ff0000000000001));   /* 1 + 2^-52 */
        put64(b, UINT64_C(0x3ca0000000000000));   /* 2^-53 */
        st = cft_augmented_add(dev, CFT_FP64, a, b, r, e, 1, &fl);
        CHECK(st == CFT_OK && get64(r) == UINT64_C(0x3ff0000000000001) &&
              get64(e) == UINT64_C(0x3ca0000000000000) && fl == 0,
              "the same tie at binary64");

        put32(a, 0x7f7fffffu);               /* the largest finite */
        put32(b, 0x73000000u);               /* 2^103: half an ulp */
        st = cft_augmented_add(dev, CFT_FP32, a, b, r, e, 1, &fl);
        CHECK(st == CFT_OK && get32(r) == 0x7f7fffffu &&
              get32(e) == 0x73000000u && fl == 0,
              "exactly ON the overflow threshold: maxfinite, silently");
        put32(b, 0x73800000u);               /* 2^104: one ulp */
        st = cft_augmented_add(dev, CFT_FP32, a, b, r, e, 1, &fl);
        CHECK(st == CFT_OK && get32(r) == 0x7f800000u &&
              get32(e) == 0x7f800000u &&
              fl == (CFT_FLAG_OVERFLOW | CFT_FLAG_INEXACT),
              "past it: +infinity in BOTH outputs, overflow and inexact");

        put32(a, 0x3f800000u);               /* 1.0 */
        put32(b, 0x00000001u);               /* 2^-149 */
        st = cft_augmented_add(dev, CFT_FP32, a, b, r, e, 1, &fl);
        CHECK(st == CFT_OK && get32(r) == 0x3f800000u &&
              get32(e) == 0x00000001u && fl == CFT_FLAG_UNDERFLOW,
              "a subnormal residual raises underflow and NOT inexact");
        st = cft_augmented_mul(dev, CFT_FP32, b, b, r, e, 1, &fl);
        CHECK(st == CFT_OK && get32(r) == 0 && get32(e) == 0 &&
              fl == (CFT_FLAG_UNDERFLOW | CFT_FLAG_INEXACT),
              "a product residual the format cannot hold: both raised");

        put32(a, 0xbf800000u);               /* -1.0 */
        put32(b, 0x00000000u);
        st = cft_augmented_add(dev, CFT_FP32, a, b, r, e, 1, &fl);
        CHECK(st == CFT_OK && get32(r) == 0xbf800000u &&
              get32(e) == 0x80000000u && fl == 0,
              "a zero error term takes the sign of r, not of the sum");
        put32(b, 0x3f800000u);
        st = cft_augmented_add(dev, CFT_FP32, a, b, r, e, 1, &fl);
        CHECK(st == CFT_OK && get32(r) == 0 && get32(e) == 0 && fl == 0,
              "exact cancellation is +0 in both outputs (6.3)");
        put32(a, 0x80000000u);
        put32(b, 0x00000000u);
        st = cft_augmented_sub(dev, CFT_FP32, a, b, r, e, 1, &fl);
        CHECK(st == CFT_OK && get32(r) == 0x80000000u &&
              get32(e) == 0x80000000u && fl == 0,
              "-0 - (+0) is (-0, -0)");

        put32(a, 0x7f800000u);
        put32(b, 0xff800000u);
        st = cft_augmented_add(dev, CFT_FP32, a, b, r, e, 1, &fl);
        CHECK(st == CFT_OK && get32(r) == 0x7fc00000u &&
              get32(e) == 0x7fc00000u && fl == CFT_FLAG_INVALID,
              "inf + (-inf): the same quiet NaN for both outputs");
        put32(a, 0x7f800001u);               /* a signaling NaN */
        put32(b, 0x3f800000u);
        st = cft_augmented_mul(dev, CFT_FP32, a, b, r, e, 1, &fl);
        CHECK(st == CFT_OK && get32(r) == 0x7fc00000u &&
              get32(e) == 0x7fc00000u && fl == CFT_FLAG_INVALID,
              "a signaling NaN propagates as both results, invalid raised");
        put32(a, 0x7f800000u);
        put32(b, 0x00000000u);
        st = cft_augmented_mul(dev, CFT_FP32, a, b, r, e, 1, &fl);
        CHECK(st == CFT_OK && get32(r) == 0x7fc00000u &&
              get32(e) == 0x7fc00000u && fl == CFT_FLAG_INVALID,
              "inf * 0 likewise");
        put32(a, 0x7f800000u);
        put32(b, 0x3f800000u);
        st = cft_augmented_add(dev, CFT_FP32, a, b, r, e, 1, &fl);
        CHECK(st == CFT_OK && get32(r) == 0x7f800000u &&
              get32(e) == 0x7f800000u && fl == 0,
              "an infinite OPERAND signals nothing - only overflow does");

        /* refusals and aliasing, this file's charter */
        put32(a, 0x3f800000u);
        put32(b, 0x40000000u);
        CHECK(cft_augmented_add(dev, CFT_FP32, a, b, r, r, 1, &fl)
              == CFT_ERR_INVALID_ARGUMENT,
              "r and e must not be the same buffer");
        CHECK(cft_augmented_mul(dev, CFT_FP32, NULL, b, r, e, 1, &fl)
              == CFT_ERR_INVALID_ARGUMENT, "a is not optional");
        CHECK(cft_augmented_sub(dev, CFT_FP32, a, NULL, r, e, 1, &fl)
              == CFT_ERR_INVALID_ARGUMENT, "b is not optional");
        CHECK(cft_augmented_add(dev, CFT_FP32, a, b, NULL, e, 1, &fl)
              == CFT_ERR_INVALID_ARGUMENT, "r is not optional");
        CHECK(cft_augmented_add(dev, CFT_FP32, a, b, r, NULL, 1, &fl)
              == CFT_ERR_INVALID_ARGUMENT, "e is not optional");
        CHECK(cft_augmented_add(dev, (cft_format)9, a, b, r, e, 1, &fl)
              == CFT_ERR_INVALID_ARGUMENT, "a bad format is refused");
        fl = 0xdead;
        CHECK(cft_augmented_add(dev, CFT_FP32, a, b, r, e, 0, &fl)
              == CFT_OK && fl == 0, "n = 0 succeeds with clean flags");

        for (k = 0; k < 8; k++) {
            put32(a + 4 * k, 0x3f800000u + (uint32_t)k);
            put32(b + 4 * k, 0x33800000u + (uint32_t)k);
        }
        st = cft_augmented_add(dev, CFT_FP32, a, b, r, e, 8, &fl);
        CHECK(st == CFT_OK, "augmented batch, separate buffers");
        memcpy(r2, a, 32);
        st = cft_augmented_add(dev, CFT_FP32, r2, b, r2, e, 8, &fl);
        CHECK(st == CFT_OK && memcmp(r2, r, 32) == 0,
              "r may alias a: each element is read before it is written");
    }

    /* --- the rest of clause 9.4 ----------------------------------
     *
     * sumSquare, sumAbs and the three scaled products. Each claim the
     * header makes gets a check, and the two that are worth doubting -
     * "the same tree, so the composition is the answer" and "this
     * cannot overflow" - get a NEGATIVE CONTROL beside them, because a
     * property that holds for boring reasons is not evidence.
     */
    {
        uint8_t v[4 * 4], w[4 * 4], d[4], d2[4];
        uint32_t f2 = 0, f3 = 0;
        int64_t scale = -12345;

        CHECK(strcmp(cft_op_name(CFT_SUMSQ), "sumsq") == 0 &&
              strcmp(cft_op_name(CFT_SUMABS), "sumabs") == 0,
              "the two new reduction opcodes are named");
        /* 30 became CFT_IMUL on 2026-09-07, so 31 is the first
         * unassigned opcode. This line has moved every time the
         * contract took a number, which is what it is for: an opcode
         * that still read as "reserved" after being assigned would
         * let a recorded conformance set naming "reservedNN" replay
         * against a different operation than the one its answer was
         * recorded for. */
        CHECK(strcmp(cft_op_name(CFT_IMUL), "imul") == 0,
              "the integer multiply is named");
        CHECK(strcmp(cft_op_name((cft_op)31), "maxall") == 0,
              "31 names maxall since 2026-09-12");
        CHECK(strcmp(cft_op_name((cft_op)15), "reserved") == 0,
              "15 is an unassigned opcode");
        CHECK(cft_supports(dev, CFT_SUMSQ, CFT_FP256) == 1 &&
              cft_supports(dev, CFT_SUMABS, CFT_FP32) == 1,
              "software backend carries the composed reductions");
        /* maxall IS supported wherever min/max is, because that is what
         * it composes from - reduce_helper_group says so and this is the
         * line that holds it to it. The unassigned-opcode assertion moved
         * to 15 above when 31 was taken. */
        CHECK(cft_supports(dev, CFT_MAXALL, CFT_FP32) == 1,
              "maxall is supported where min/max is");
        CHECK(cft_supports(dev, (cft_op)15, CFT_FP32) == 0,
              "op 15 unassigned");
        /* IMUL is defined and executed - by a sequencer program, and
         * elementwise on the software backend - and CAPS[28]
         * (CFT_ALU_EXT_IMUL) publishes it, since 925efab on 2026-09-07.
         * This line said 0 until 2026-09-24 and was right to, but for
         * the wrong reason: cft_sf_op_assigned left 30 off, so
         * cft_supports returned before the CAPS[28] branch that exists
         * to answer for it, on every device. It is the line the old
         * comment promised would say so when the caps grew; they grew,
         * and nothing moved it. Every format, and the other two things
         * that "unassigned" had got wrong for 30: a NULL operand it
         * reads is refused as its group's siblings' are, and an index
         * table on a or b is taken rather than refused as an operand it
         * does not read. */
        {
            int fi;
            uint8_t ia[4 * 4], ib[4 * 4], id[4 * 4], ig[4 * 4];
            uint32_t tab[4] = { 3, 0, 2, 1 }, fa = 0, fb = 0;
            cft_elem_args IX;
            for (fi = 0; fi < 4; fi++)
                CHECK(cft_supports(dev, CFT_IMUL, (cft_format)fi) == 1,
                      "cft_supports(CFT_IMUL, %s) on the software "
                      "backend, which publishes CFT_ALU_EXT_IMUL "
                      "(seq_features 0x%lx) and computes opcode 30",
                      cft_format_name((cft_format)fi),
                      (unsigned long)caps.seq_features);
            for (fi = 0; fi < 16; fi++) {
                ia[fi] = (uint8_t)(0x9d * fi + 7);
                ib[fi] = (uint8_t)(0x3b * fi + 1);
            }
            CHECK(cft_run(dev, CFT_IMUL, CFT_FP32, CFT_RNE, ia, NULL, NULL,
                          id, 4, NULL, NULL) == CFT_ERR_INVALID_ARGUMENT,
                  "cft_run(CFT_IMUL) with NULL b is refused - imul reads "
                  "b, as iand does");
            memset(&IX, 0, sizeof IX);
            IX.struct_size = sizeof IX;
            IX.a = ia; IX.b = ib; IX.d = id; IX.n = 4;
            IX.idx_a = tab; IX.idx_a_src = 4; IX.flags_out = &fa;
            st = cft_run_ex(dev, CFT_IMUL, CFT_FP32, CFT_RNE, &IX);
            CHECK(st == CFT_OK, "an index table on imul's operand a is "
                  "taken: %s (%s)", cft_strerror(st), cft_last_error());
            for (fi = 0; fi < 4; fi++)
                memcpy(ig + fi * 4, ia + tab[fi] * 4, 4);
            CHECK(cft_run(dev, CFT_IMUL, CFT_FP32, CFT_RNE, ig, ib, NULL,
                          ig, 4, &fb, NULL) == CFT_OK &&
                  memcmp(id, ig, sizeof id) == 0 && fa == fb,
                  "indexed imul is the dense imul over the gathered a");
        }

        /* sumSquare([3, 4]) = 9 + 16 = 25, exactly. */
        put32(v, 0x40400000u);          /* 3.0 */
        put32(v + 4, 0x40800000u);      /* 4.0 */
        st = cft_reduce(dev, CFT_SUMSQ, CFT_FP32, CFT_RNE, v, NULL, d, 2,
                        &f2, NULL);
        CHECK(st == CFT_OK && get32(d) == 0x41c80000u && f2 == 0,
              "sumsq([3,4]) = 25 exactly: %s 0x%08x/0x%02x",
              cft_strerror(st), get32(d), (unsigned)f2);
        /* the identity, on the same bytes: it IS the dot over (a, a) */
        st = cft_reduce(dev, CFT_DOT, CFT_FP32, CFT_RNE, v, v, d2, 2,
                        &f3, NULL);
        CHECK(st == CFT_OK && get32(d2) == get32(d) && f3 == f2,
              "sumsq == dot(a, a)");

        /* sumAbs([-3, 4]) = 7, and the same as an abs pass then a sum */
        put32(v, 0xc0400000u);          /* -3.0 */
        st = cft_reduce(dev, CFT_SUMABS, CFT_FP32, CFT_RNE, v, NULL, d, 2,
                        &f2, NULL);
        CHECK(st == CFT_OK && get32(d) == 0x40e00000u && f2 == 0,
              "sumabs([-3,4]) = 7: %s 0x%08x/0x%02x",
              cft_strerror(st), get32(d), (unsigned)f2);
        st = cft_run(dev, CFT_ABS, CFT_FP32, CFT_RNE, v, NULL, NULL, w, 2,
                     &f3, NULL);
        if (st == CFT_OK)
            st = cft_reduce(dev, CFT_SUM, CFT_FP32, CFT_RNE, w, NULL, d2, 2,
                            &f3, NULL);
        CHECK(st == CFT_OK && get32(d2) == get32(d) && f3 == f2,
              "sumabs == abs pass then sum");

        /* sumAbs whose scratch cannot be had (verifier-V9, 2026-09-27).
         * The composition mutes the handle's flags for its internal
         * passes, and from 613f3f88 until that date its out-of-memory
         * return skipped the unmute: every later call's flags reached
         * flags_out and none reached the status word. n is the largest
         * the call accepts - n * 4 bytes is within 3 of SIZE_MAX - which
         * no allocator can give, and the call returns before it reads a
         * byte of v. (Under ASan, run with allocator_may_return_null=1,
         * as host/fuzz/run.sh does.) */
        cft_lower_flags(dev, CFT_FLAGS_ALL);
        st = cft_reduce(dev, CFT_SUMABS, CFT_FP32, CFT_RNE, v, NULL, d,
                        ((size_t)-1) / 4u, &f2, NULL);
        CHECK(st == CFT_ERR_OUT_OF_MEMORY,
              "sumabs over SIZE_MAX / 4 elements is out of memory before "
              "reading one: %s", cft_strerror(st));
        put32(v, 0x7f7fffffu);          /* the largest finite fp32 */
        put32(v + 4, 0x7f7fffffu);
        f3 = 0;
        st = cft_run(dev, CFT_ADD, CFT_FP32, CFT_RNE, v, NULL, v + 4, w, 1,
                     &f3, NULL);
        CHECK(st == CFT_OK && (f3 & CFT_FLAG_OVERFLOW) &&
              cft_test_flags(dev, CFT_FLAG_OVERFLOW) == 1,
              "after sumabs ran out of memory, an overflow reaches the "
              "status word as well as flags_out (0x%02x, the word says %d) "
              "- the handle's flags were unmuted", (unsigned)f3,
              cft_test_flags(dev, CFT_FLAG_OVERFLOW));
        cft_lower_flags(dev, CFT_FLAGS_ALL);

        /* 9.4 puts an infinity AHEAD of a NaN for these two, which the
         * tree cannot do - and the NEGATIVE CONTROL is the same vector
         * through the plain dot, which returns the quiet NaN. */
        put32(v, 0x7f800000u);          /* +inf */
        put32(v + 4, 0x7fc00000u);      /* quiet NaN */
        st = cft_reduce(dev, CFT_SUMSQ, CFT_FP32, CFT_RNE, v, NULL, d, 2,
                        &f2, NULL);
        CHECK(st == CFT_OK && get32(d) == 0x7f800000u && f2 == 0,
              "sumsq(inf, NaN) is +inf with no flag: 0x%08x/0x%02x",
              get32(d), (unsigned)f2);
        st = cft_reduce(dev, CFT_SUMABS, CFT_FP32, CFT_RNE, v, NULL, d, 2,
                        &f2, NULL);
        CHECK(st == CFT_OK && get32(d) == 0x7f800000u && f2 == 0,
              "sumabs(inf, NaN) is +inf");
        st = cft_reduce(dev, CFT_DOT, CFT_FP32, CFT_RNE, v, v, d2, 2,
                        &f3, NULL);
        CHECK(st == CFT_OK && get32(d2) == 0x7fc00000u,
              "NEGATIVE CONTROL: the plain dot returns the quiet NaN "
              "there, so the override is doing real work (0x%08x)",
              get32(d2));

        /* scaledProd of four copies of 2^100: the true product is
         * 2^400, hundreds of binades outside fp32, and it comes back
         * as (1.0, 400) with no flag at all. */
        put32(v, 0x71800000u);
        put32(v + 4, 0x71800000u);
        put32(v + 8, 0x71800000u);
        put32(v + 12, 0x71800000u);
        f2 = 0xdead;
        st = cft_scaled_prod(dev, CFT_FP32, CFT_RNE, v, d, &scale, 4, &f2);
        CHECK(st == CFT_OK && get32(d) == 0x3f800000u && scale == 400 &&
              f2 == 0,
              "scaledProd(2^100 x 4) = (1.0, 400) silently: %s "
              "0x%08x/%lld/0x%02x", cft_strerror(st), get32(d),
              (long long)scale, (unsigned)f2);
        /* the NEGATIVE CONTROL: the same operands through the multiply
         * this composes from overflow to +inf on the FIRST pair. */
        f3 = 0;
        st = cft_run(dev, CFT_MUL, CFT_FP32, CFT_RNE, v, v, NULL, d2, 1,
                     &f3, NULL);
        CHECK(st == CFT_OK && get32(d2) == 0x7f800000u &&
              (f3 & CFT_FLAG_OVERFLOW),
              "NEGATIVE CONTROL: 2^100 * 2^100 overflows to +inf with "
              "the overflow flag (0x%08x/0x%02x)", get32(d2),
              (unsigned)f3);

        /* the empty vector: 9.4 fixes it at pr = 1, sf = +0, silent */
        scale = -1;
        f2 = 0xdead;
        st = cft_scaled_prod(dev, CFT_FP32, CFT_RNE, NULL, d, &scale, 0,
                             &f2);
        CHECK(st == CFT_OK && get32(d) == 0x3f800000u && scale == 0 &&
              f2 == 0, "scaledProd of nothing is (1.0, 0), silently");

        /* the special-value rows, in 9.4's order */
        put32(v, 0x7f800000u);          /* +inf */
        put32(v + 4, 0x00000000u);      /* +0   */
        st = cft_scaled_prod(dev, CFT_FP32, CFT_RNE, v, d, &scale, 2, &f2);
        CHECK(st == CFT_OK && get32(d) == 0x7fc00000u && scale == 0 &&
              f2 == CFT_FLAG_INVALID,
              "inf x 0 is invalid and the canonical quiet NaN");
        put32(v + 4, 0xc0000000u);      /* -2.0 */
        st = cft_scaled_prod(dev, CFT_FP32, CFT_RNE, v, d, &scale, 2, &f2);
        CHECK(st == CFT_OK && get32(d) == 0xff800000u && f2 == 0,
              "an infinity with no zero takes the product's sign, "
              "silently");
        put32(v, 0x80000000u);          /* -0 */
        st = cft_scaled_prod(dev, CFT_FP32, CFT_RNE, v, d, &scale, 2, &f2);
        CHECK(st == CFT_OK && get32(d) == 0x00000000u && f2 == 0,
              "-0 x -2 is +0, silently");

        /* scaledProdSum / Diff: one rounding for the leaf, then the
         * same tree. (1+1) * (3+1) = 8 -> (1.0, 3). */
        put32(v, 0x3f800000u); put32(v + 4, 0x40400000u);
        put32(w, 0x3f800000u); put32(w + 4, 0x3f800000u);
        st = cft_scaled_prod_sum(dev, CFT_FP32, CFT_RNE, v, w, d, &scale, 2,
                                 &f2);
        CHECK(st == CFT_OK && get32(d) == 0x3f800000u && scale == 3 &&
              f2 == 0, "scaledProdSum = (1.0, 3): 0x%08x/%lld/0x%02x",
              get32(d), (long long)scale, (unsigned)f2);
        /* (1-1) * (3-1): a zero factor, so a zero result */
        st = cft_scaled_prod_diff(dev, CFT_FP32, CFT_RNE, v, w, d, &scale, 2,
                                  &f2);
        CHECK(st == CFT_OK && get32(d) == 0x00000000u && scale == 0 &&
              f2 == 0, "scaledProdDiff with a zero factor is +0");

        /* the refusals: an output the caller cannot receive is an
         * error, not a silent partial answer */
        CHECK(cft_scaled_prod(dev, CFT_FP32, CFT_RNE, v, NULL, &scale, 2,
                              NULL) == CFT_ERR_INVALID_ARGUMENT,
              "NULL pr refused");
        CHECK(cft_scaled_prod(dev, CFT_FP32, CFT_RNE, v, d, NULL, 2,
                              NULL) == CFT_ERR_INVALID_ARGUMENT,
              "NULL scale refused");
        CHECK(cft_scaled_prod(NULL, CFT_FP32, CFT_RNE, v, d, &scale, 2,
                              NULL) == CFT_ERR_INVALID_ARGUMENT,
              "NULL device refused");
        CHECK(cft_scaled_prod(dev, (cft_format)4, CFT_RNE, v, d, &scale, 2,
                              NULL) == CFT_ERR_INVALID_ARGUMENT,
              "bad format refused");
        CHECK(cft_scaled_prod(dev, CFT_FP32, (cft_round)5, v, d, &scale, 2,
                              NULL) == CFT_ERR_INVALID_ARGUMENT,
              "bad rounding attribute refused");
        CHECK(cft_scaled_prod(dev, CFT_FP32, CFT_RNE, NULL, d, &scale, 2,
                              NULL) == CFT_ERR_INVALID_ARGUMENT,
              "a non-empty call with no vector is refused");
        CHECK(cft_scaled_prod_sum(dev, CFT_FP32, CFT_RNE, v, NULL, d,
                                  &scale, 2, NULL) ==
              CFT_ERR_INVALID_ARGUMENT,
              "scaledProdSum needs b");
    }

    /* --- the character conversions and the payload operations ------
     *
     * Part of the 0.6 step. character_check.py proves these against the
     * model at scale and the vectors replay them; what belongs HERE is
     * this file's charter - the refusals, the sizing protocol, the
     * aliasing rule, and a handful of results whose expected bits and
     * characters come from reading 754-2019 clauses 5.12 and 9.7 by
     * hand rather than from running either implementation.
     *
     * Ending with a NEGATIVE CONTROL, because the headline claim here
     * is a round trip, and a round trip is the easiest property in this
     * library to pass for the wrong reason: an implementation that
     * quietly ignored the digit count and always wrote the exact value
     * would satisfy every round-trip check ever written. So the last
     * block asserts that the round trip FAILS one digit below Pmin -
     * which it can only do if the digit count is being honoured.
     */
    {
        uint8_t a[8], d[8];
        char text[64];
        const char *in[4];
        size_t need = 0, bad = 0;
        uint32_t f4 = 0xdead;
        cft_status s2;

        /* Pmin(bf) = 1 + ceiling(p * log10 2). 5.12.2 lists 9, 17 and
         * 36 for the first three rungs; 73 is the same formula at
         * p = 237. */
        CHECK(cft_format_decimal_digits(CFT_FP32) == 9 &&
              cft_format_decimal_digits(CFT_FP64) == 17 &&
              cft_format_decimal_digits(CFT_FP128) == 36 &&
              cft_format_decimal_digits(CFT_FP256) == 73,
              "Pmin per 5.12.2");
        CHECK(cft_format_decimal_digits((cft_format)9) == 0,
              "Pmin of an unknown format is 0");

        /* -- reading a sequence in -- */
        in[0] = "1.5";
        s2 = cft_from_decimal_char(dev, CFT_FP32, CFT_RNE, in, d, 1, &bad,
                                   &f4);
        CHECK(s2 == CFT_OK && get32(d) == 0x3fc00000u && f4 == 0,
              "1.5 is exact in binary32 and raises nothing");
        in[0] = "0.1";
        s2 = cft_from_decimal_char(dev, CFT_FP32, CFT_RNE, in, d, 1, NULL,
                                   &f4);
        CHECK(s2 == CFT_OK && get32(d) == 0x3dcccccdu &&
              f4 == CFT_FLAG_INEXACT, "0.1 to nearest is 0x3dcccccd");
        s2 = cft_from_decimal_char(dev, CFT_FP32, CFT_RTZ, in, d, 1, NULL,
                                   &f4);
        CHECK(s2 == CFT_OK && get32(d) == 0x3dccccccu &&
              f4 == CFT_FLAG_INEXACT, "0.1 toward zero is one ulp below");
        /* 2^24 + 1 is exactly halfway between 2^24 and 2^24 + 2, so
         * the attribute alone decides it - ties-to-even takes the even
         * significand, ties-to-away the other one. */
        in[0] = "16777217";
        s2 = cft_from_decimal_char(dev, CFT_FP32, CFT_RNE, in, d, 1, NULL,
                                   &f4);
        CHECK(s2 == CFT_OK && get32(d) == 0x4b800000u &&
              f4 == CFT_FLAG_INEXACT, "2^24+1 ties to even");
        s2 = cft_from_decimal_char(dev, CFT_FP32, CFT_RMM, in, d, 1, NULL,
                                   &f4);
        CHECK(s2 == CFT_OK && get32(d) == 0x4b800001u &&
              f4 == CFT_FLAG_INEXACT, "2^24+1 ties away");
        /* Below half the smallest subnormal in magnitude, so the
         * result is decided by the attribute's side and both the tiny
         * and the inexact flags rise (7.5). */
        in[0] = "1e-45";
        s2 = cft_from_decimal_char(dev, CFT_FP32, CFT_RNE, in, d, 1, NULL,
                                   &f4);
        CHECK(s2 == CFT_OK && get32(d) == 0x00000001u &&
              f4 == (CFT_FLAG_UNDERFLOW | CFT_FLAG_INEXACT),
              "1e-45 rounds up to the smallest subnormal, tiny+inexact");
        s2 = cft_from_decimal_char(dev, CFT_FP32, CFT_RTZ, in, d, 1, NULL,
                                   &f4);
        CHECK(s2 == CFT_OK && get32(d) == 0u &&
              f4 == (CFT_FLAG_UNDERFLOW | CFT_FLAG_INEXACT),
              "1e-45 toward zero is +0, still tiny+inexact");
        /* Overflow delivers per 7.4's table, exactly as any arithmetic
         * result does - an infinity to nearest, the largest finite
         * magnitude toward zero. */
        in[0] = "3.5e38";
        s2 = cft_from_decimal_char(dev, CFT_FP32, CFT_RNE, in, d, 1, NULL,
                                   &f4);
        CHECK(s2 == CFT_OK && get32(d) == 0x7f800000u &&
              f4 == (CFT_FLAG_OVERFLOW | CFT_FLAG_INEXACT),
              "3.5e38 overflows to +inf");
        s2 = cft_from_decimal_char(dev, CFT_FP32, CFT_RTZ, in, d, 1, NULL,
                                   &f4);
        CHECK(s2 == CFT_OK && get32(d) == 0x7f7fffffu &&
              f4 == (CFT_FLAG_OVERFLOW | CFT_FLAG_INEXACT),
              "3.5e38 toward zero delivers maxfinite");
        /* An exponent no arithmetic could reach still has a defined
         * answer: the library decides the band without computing
         * 10^999999999999. */
        in[0] = "-1e999999999999";
        s2 = cft_from_decimal_char(dev, CFT_FP32, CFT_RNE, in, d, 1, NULL,
                                   &f4);
        CHECK(s2 == CFT_OK && get32(d) == 0xff800000u &&
              f4 == (CFT_FLAG_OVERFLOW | CFT_FLAG_INEXACT),
              "an absurd exponent overflows rather than hanging");
        in[0] = "-1e-999999999999";
        s2 = cft_from_decimal_char(dev, CFT_FP32, CFT_RNE, in, d, 1, NULL,
                                   &f4);
        CHECK(s2 == CFT_OK && get32(d) == 0x80000000u &&
              f4 == (CFT_FLAG_UNDERFLOW | CFT_FLAG_INEXACT),
              "and an absurd negative one underflows to -0");
        /* A zero decimal is a zero and rounding never changes a sign
         * (6.3), so the minus survives in every attribute. */
        in[0] = "-0.000";
        s2 = cft_from_decimal_char(dev, CFT_FP32, CFT_RUP, in, d, 1, NULL,
                                   &f4);
        CHECK(s2 == CFT_OK && get32(d) == 0x80000000u && f4 == 0,
              "-0.000 is -0 even rounding upward");

        /* -- the 5.12.1 words, both directions -- */
        in[0] = "-INFINITY";
        s2 = cft_from_decimal_char(dev, CFT_FP32, CFT_RNE, in, d, 1, NULL,
                                   &f4);
        CHECK(s2 == CFT_OK && get32(d) == 0xff800000u && f4 == 0,
              "-INFINITY, case insensitive, raises nothing");
        in[0] = "snan(0x1)";
        s2 = cft_from_decimal_char(dev, CFT_FP32, CFT_RNE, in, d, 1, NULL,
                                   &f4);
        CHECK(s2 == CFT_OK && get32(d) == 0x7f800001u && f4 == 0,
              "a signaling NaN reads back signaling, and raises NOTHING - "
              "5.12 exempts these conversions from the sNaN rule");
        in[0] = "NaN(0X5)";
        s2 = cft_from_decimal_char(dev, CFT_FP32, CFT_RNE, in, d, 1, NULL,
                                   &f4);
        CHECK(s2 == CFT_OK && get32(d) == 0x7fc00005u && f4 == 0,
              "a payload suffix is read in either case");

        /* -- writing a sequence out -- */
        put32(a, 0x3f800000u);                            /* 1.0f */
        s2 = cft_to_decimal_char(dev, CFT_FP32, CFT_RNE, a, 0, text,
                                 sizeof text, &need, &f4);
        CHECK(s2 == CFT_OK && strcmp(text, "1e+0") == 0 && need == 5 &&
              f4 == 0, "the exact decimal of 1 is 1e+0");
        s2 = cft_to_decimal_char(dev, CFT_FP32, CFT_RNE, a, 9, text,
                                 sizeof text, &need, &f4);
        CHECK(s2 == CFT_OK && strcmp(text, "1.00000000e+0") == 0 && f4 == 0,
              "nine digits of 1 keeps its trailing zeros and stays exact");
        put32(a, 0x3dcccccdu);                            /* the 0.1f above */
        s2 = cft_to_decimal_char(dev, CFT_FP32, CFT_RNE, a, 0, text,
                                 sizeof text, &need, &f4);
        CHECK(s2 == CFT_OK && f4 == 0 &&
              strcmp(text, "1.00000001490116119384765625e-1") == 0,
              "the EXACT decimal of the nearest float to 0.1, all of it");
        s2 = cft_to_decimal_char(dev, CFT_FP32, CFT_RNE, a, 9, text,
                                 sizeof text, &need, &f4);
        CHECK(s2 == CFT_OK && strcmp(text, "1.00000001e-1") == 0 &&
              f4 == CFT_FLAG_INEXACT,
              "nine digits of it drops something, so inexact");
        put32(a, 0x80000000u);
        s2 = cft_to_decimal_char(dev, CFT_FP32, CFT_RNE, a, 17, text,
                                 sizeof text, &need, &f4);
        CHECK(s2 == CFT_OK && strcmp(text, "-0") == 0 && f4 == 0,
              "a zero is -0 at every digit count - it has no digits to pad");
        put32(a, 0x7f800001u);
        s2 = cft_to_decimal_char(dev, CFT_FP32, CFT_RNE, a, 0, text,
                                 sizeof text, &need, &f4);
        CHECK(s2 == CFT_OK && strcmp(text, "snan(0x1)") == 0 && f4 == 0,
              "a signaling NaN writes snan and signals nothing");
        put32(a, 0x7fc00005u);
        s2 = cft_to_decimal_char(dev, CFT_FP32, CFT_RNE, a, 0, text,
                                 sizeof text, &need, &f4);
        CHECK(s2 == CFT_OK && strcmp(text, "nan(0x5)") == 0,
              "a quiet NaN carries its payload out");

        /* -- hexadecimal (5.12.3) -- */
        put32(a, 0x40400000u);                            /* 3.0f */
        CHECK(cft_to_hex_char(dev, CFT_FP32, a, text, sizeof text, &need)
              == CFT_OK && strcmp(text, "0x1.8p+1") == 0,
              "the shortest exact hex of 3 is 0x1.8p+1");
        put32(a, 0x00000001u);
        CHECK(cft_to_hex_char(dev, CFT_FP32, a, text, sizeof text, &need)
              == CFT_OK && strcmp(text, "0x1p-149") == 0,
              "a subnormal prints with its TRUE exponent, not a leading 0");
        put32(a, 0x80000000u);
        CHECK(cft_to_hex_char(dev, CFT_FP32, a, text, sizeof text, &need)
              == CFT_OK && strcmp(text, "-0x0p+0") == 0, "-0 in hex");
        in[0] = "0x1.8p+0";
        s2 = cft_from_hex_char(dev, CFT_FP32, CFT_RNE, in, d, 1, NULL, &f4);
        CHECK(s2 == CFT_OK && get32(d) == 0x3fc00000u && f4 == 0,
              "0x1.8p+0 is 1.5 exactly");
        /* One hex digit more than binary32 holds: 0x1.000001p+0 is
         * 1 + 2^-24, exactly halfway to the next float, so ties-to-even
         * takes 1 and toward-positive takes its successor. */
        in[0] = "0x1.000001p+0";
        s2 = cft_from_hex_char(dev, CFT_FP32, CFT_RNE, in, d, 1, NULL, &f4);
        CHECK(s2 == CFT_OK && get32(d) == 0x3f800000u &&
              f4 == CFT_FLAG_INEXACT, "a hex tie rounds to even");
        s2 = cft_from_hex_char(dev, CFT_FP32, CFT_RUP, in, d, 1, NULL, &f4);
        CHECK(s2 == CFT_OK && get32(d) == 0x3f800001u &&
              f4 == CFT_FLAG_INEXACT, "the same tie upward is nextUp(1)");

        /* -- refusals: a status, never a guess -- */
        {
            static const char *const bad_seq[] = {
                "", "+", ".", "1e", "1 ", " 1", "1.5.5", "1,5", "0x1p+0",
                "nan()", "nan(0x)", "nan(0x400000)", "1_000", NULL
            };
            int k2;
            for (k2 = 0; bad_seq[k2]; k2++) {
                in[0] = bad_seq[k2];
                CHECK(cft_from_decimal_char(dev, CFT_FP32, CFT_RNE, in, d, 1,
                                            NULL, &f4)
                      == CFT_ERR_INVALID_ARGUMENT,
                      "refused: %s", bad_seq[k2]);
            }
        }
        in[0] = "1.5";                     /* decimal is not hexadecimal */
        CHECK(cft_from_hex_char(dev, CFT_FP32, CFT_RNE, in, d, 1, NULL, &f4)
              == CFT_ERR_INVALID_ARGUMENT,
              "the hex parser refuses a decimal sequence");
        in[0] = "0x1.8";                   /* 5.12.3 requires an exponent */
        CHECK(cft_from_hex_char(dev, CFT_FP32, CFT_RNE, in, d, 1, NULL, &f4)
              == CFT_ERR_INVALID_ARGUMENT,
              "5.12.3's grammar requires the binary exponent");
        /* Which element failed, because a caller reading a file of
         * numbers needs the line and not just the verdict. */
        in[0] = "1"; in[1] = "2"; in[2] = "oops"; in[3] = "4";
        bad = 99;
        CHECK(cft_from_decimal_char(dev, CFT_FP32, CFT_RNE, in, d, 4, &bad,
                                    &f4) == CFT_ERR_INVALID_ARGUMENT &&
              bad == 2, "the refusal names the element");

        /* -- the sizing protocol: a short buffer is a status, and the
         * buffer is not touched. A truncated number is a wrong answer
         * that looks like a right one. -- */
        put32(a, 0x3dcccccdu);
        need = 0;
        CHECK(cft_to_decimal_char(dev, CFT_FP32, CFT_RNE, a, 0, NULL, 0,
                                  &need, &f4) == CFT_ERR_INVALID_ARGUMENT &&
              need == 32,
              "cap 0 asks for the size: 31 characters and a NUL");
        memset(text, 'Z', sizeof text);
        CHECK(cft_to_decimal_char(dev, CFT_FP32, CFT_RNE, a, 0, text,
                                  need - 1, &need, &f4)
              == CFT_ERR_INVALID_ARGUMENT && text[0] == 'Z',
              "one byte short refuses and writes NOTHING");

        /* -- the 9.7 payload operations (they signal nothing) -- */
        put32(a, 0x7fc00005u);
        CHECK(cft_get_payload(dev, CFT_FP32, a, d, 1) == CFT_OK &&
              get32(d) == 0x40a00000u,
              "getPayload of a NaN carrying 5 is the float 5");
        put32(a, 0x3f800000u);
        CHECK(cft_get_payload(dev, CFT_FP32, a, d, 1) == CFT_OK &&
              get32(d) == 0xbf800000u,
              "getPayload of a non-NaN is -1, which is 9.7's own answer");
        put32(a, 0x40a00000u);                            /* 5.0f */
        CHECK(cft_set_payload(dev, CFT_FP32, a, d, 1) == CFT_OK &&
              get32(d) == 0x7fc00005u, "setPayload(5) is a quiet NaN");
        CHECK(cft_set_payload_signaling(dev, CFT_FP32, a, d, 1) == CFT_OK &&
              get32(d) == 0x7f800005u,
              "setPayloadSignaling(5) is the signaling form");
        put32(a, 0x4a800000u);                            /* 2^22 */
        CHECK(cft_set_payload(dev, CFT_FP32, a, d, 1) == CFT_OK &&
              get32(d) == 0u,
              "2^22 is one past what binary32's payload field holds: +0");
        put32(a, 0x80000000u);                            /* -0 */
        CHECK(cft_set_payload(dev, CFT_FP32, a, d, 1) == CFT_OK &&
              get32(d) == 0x7fc00000u,
              "-0 is the integer zero by value, so setPayload takes it");
        CHECK(cft_set_payload_signaling(dev, CFT_FP32, a, d, 1) == CFT_OK &&
              get32(d) == 0u,
              "but payload 0 cannot be signaling - that encoding is an "
              "infinity - so setPayloadSignaling(-0) is +0");
        put32(a, 0x3fc00000u);                            /* 1.5, not an int */
        CHECK(cft_set_payload(dev, CFT_FP32, a, d, 1) == CFT_OK &&
              get32(d) == 0u, "a non-integer operand gives +0");
        put32(a, 0xc0a00000u);                            /* -5.0f */
        CHECK(cft_set_payload(dev, CFT_FP32, a, d, 1) == CFT_OK &&
              get32(d) == 0u, "a negative operand gives +0");
        /* d may alias a. */
        put32(a, 0x7fc00003u);
        CHECK(cft_get_payload(dev, CFT_FP32, a, a, 1) == CFT_OK &&
              get32(a) == 0x40400000u, "getPayload in place");
        CHECK(cft_set_payload(dev, CFT_FP32, a, a, 1) == CFT_OK &&
              get32(a) == 0x7fc00003u, "setPayload in place, and back again");

        /* -- THE NEGATIVE CONTROL --
         *
         * 0x417ffff5 and 0x417ffff6 are neighbouring binary32
         * encodings just below 16. At Pmin = 9 digits they write
         * different sequences and each reads back to itself, which is
         * 5.12.2's guarantee. At 8 - one digit short - they write the
         * SAME sequence, so reading it back cannot recover both, and
         * this asserts that it does not. An implementation that
         * ignored the digit count and always wrote the exact value
         * would pass every round-trip check above and fail here, which
         * is the only reason this block exists.
         */
        {
            char nine_a[64], nine_b[64], eight_a[64], eight_b[64];
            uint32_t bits_a = 0x417ffff5u, bits_b = 0x417ffff6u;
            uint32_t back_a, back_b;

            put32(a, bits_a);
            CHECK(cft_to_decimal_char(dev, CFT_FP32, CFT_RNE, a, 9, nine_a,
                                      sizeof nine_a, &need, &f4) == CFT_OK,
                  "nine digits of 0x417ffff5");
            CHECK(cft_to_decimal_char(dev, CFT_FP32, CFT_RNE, a, 8, eight_a,
                                      sizeof eight_a, &need, &f4) == CFT_OK,
                  "eight digits of 0x417ffff5");
            put32(a, bits_b);
            CHECK(cft_to_decimal_char(dev, CFT_FP32, CFT_RNE, a, 9, nine_b,
                                      sizeof nine_b, &need, &f4) == CFT_OK,
                  "nine digits of 0x417ffff6");
            CHECK(cft_to_decimal_char(dev, CFT_FP32, CFT_RNE, a, 8, eight_b,
                                      sizeof eight_b, &need, &f4) == CFT_OK,
                  "eight digits of 0x417ffff6");

            CHECK(strcmp(nine_a, nine_b) != 0,
                  "at Pmin the two neighbours write different sequences");
            in[0] = nine_a;
            CHECK(cft_from_decimal_char(dev, CFT_FP32, CFT_RNE, in, d, 1,
                                        NULL, &f4) == CFT_OK, "read back");
            back_a = get32(d);
            in[0] = nine_b;
            CHECK(cft_from_decimal_char(dev, CFT_FP32, CFT_RNE, in, d, 1,
                                        NULL, &f4) == CFT_OK, "read back");
            back_b = get32(d);
            CHECK(back_a == bits_a && back_b == bits_b,
                  "5.12.2: Pmin digits under a nearest attribute round trip");

            CHECK(strcmp(eight_a, eight_b) == 0,
                  "at Pmin - 1 the two neighbours COLLIDE (%s vs %s)",
                  eight_a, eight_b);
            in[0] = eight_a;
            CHECK(cft_from_decimal_char(dev, CFT_FP32, CFT_RNE, in, d, 1,
                                        NULL, &f4) == CFT_OK, "read back");
            CHECK(get32(d) != bits_a || get32(d) != bits_b,
                  "one sequence cannot name two encodings");
            CHECK((get32(d) == bits_a) != (get32(d) == bits_b),
                  "so at Pmin - 1 the round trip loses one of them - which "
                  "is the control: an implementation ignoring the digit "
                  "count would recover both");
        }
    }

    /* --- the status word (7.1, 5.7.4), the conformance predicates
     *     (5.7.1), and 9.6's magnitude forms          (ABI 0.7)
     *
     * The word is state, so nothing in the vectors can express it and
     * nothing in the golden model corresponds to it. Every check below
     * is against a sentence of the standard, quoted where it bites.
     * ------------------------------------------------------------- */
    {
        uint8_t a[4], b[4], d[4];
        uint32_t f = 0, saved;

        /* 5.7.1. Constants, and what each rests on is in cft.h. */
        CHECK(cft_is754version1985() == 0, "1985 is not asserted");
        CHECK(cft_is754version2008() == 0,
              "2008 is not asserted: its 5.3.1 required minNum/maxNum, "
              "which 2019 replaced with 9.6's");
        CHECK(cft_is754version2019() == 1, "2019 IS asserted from 0.7");

        /* The whole-set mask is the five flags and nothing else. */
        CHECK(CFT_FLAGS_ALL == (uint32_t)(CFT_FLAG_INVALID |
                                          CFT_FLAG_DIVBYZERO |
                                          CFT_FLAG_OVERFLOW |
                                          CFT_FLAG_UNDERFLOW |
                                          CFT_FLAG_INEXACT),
              "CFT_FLAGS_ALL is every exception this library defines");

        /* 7.1: "A program that does not inherit status flags from
         * another source begins execution with all status flags
         * lowered." This device has done a great deal by now, so
         * lower them first and treat that as the starting point. */
        cft_lower_flags(dev, CFT_FLAGS_ALL);
        CHECK(cft_save_all_flags(dev) == 0, "lowered means zero");
        CHECK(cft_test_flags(dev, CFT_FLAGS_ALL) == 0,
              "and testFlags agrees");

        /* ACCUMULATION ACROSS CALLS. Each of these raises something
         * different; nothing between them lowers anything; so the word
         * is the union at every step. The values are 754's, not either
         * implementation's: max + max overflows (and 7.4 makes that
         * inexact too), 1/0 is divideByZero (7.3), and an sNaN into
         * nextUp is invalid (5.3.1: "nextUp(x) is quiet except for
         * signaling NaNs"). */
        put32(a, 0x7f7fffffu);                  /* max normal fp32 */
        put32(b, 0x7f7fffffu);
        CHECK(cft_run(dev, CFT_ADD, CFT_FP32, CFT_RNE, a, NULL, b, d, 1,
                      &f, NULL) == CFT_OK, "add");
        CHECK(f == (uint32_t)(CFT_FLAG_OVERFLOW | CFT_FLAG_INEXACT),
              "max + max overflows inexactly, got 0x%02x", (unsigned)f);
        CHECK(cft_save_all_flags(dev) == f,
              "the first call's flags are the whole word");

        put32(a, 0x3f800000u);                  /* 1.0 */
        put32(b, 0x00000000u);                  /* +0  */
        CHECK(cft_div(dev, CFT_FP32, CFT_RNE, a, b, d, 1, &f, NULL)
              == CFT_OK, "div");
        CHECK(f == (uint32_t)CFT_FLAG_DIVBYZERO,
              "1/0 signals divideByZero and NOTHING else - the Newton "
              "scaffolding's inexact must not leak, got 0x%02x",
              (unsigned)f);
        CHECK(cft_save_all_flags(dev) ==
              (uint32_t)(CFT_FLAG_OVERFLOW | CFT_FLAG_INEXACT |
                         CFT_FLAG_DIVBYZERO),
              "and the word is the union of the two calls: 0x%02x",
              (unsigned)cft_save_all_flags(dev));

        put32(a, 0x7fa00000u);                  /* a signaling NaN */
        CHECK(cft_next_up(dev, CFT_FP32, a, d, 1, &f) == CFT_OK, "nextUp");
        CHECK(f == (uint32_t)CFT_FLAG_INVALID, "nextUp(sNaN) is invalid");
        CHECK(cft_save_all_flags(dev) ==
              (uint32_t)(CFT_FLAG_OVERFLOW | CFT_FLAG_INEXACT |
                         CFT_FLAG_DIVBYZERO | CFT_FLAG_INVALID),
              "four flags standing after three calls");

        /* A CALL THAT RAISES NOTHING LEAVES THE WORD ALONE. Not
         * "leaves it mostly alone": exactly as it stood. 1 + 1 is
         * exact, and cft_class is non-computational (5.7.2) and
         * signals nothing at all, not even on the sNaN below. */
        saved = cft_save_all_flags(dev);
        put32(a, 0x3f800000u);
        put32(b, 0x3f800000u);
        CHECK(cft_run(dev, CFT_ADD, CFT_FP32, CFT_RNE, a, NULL, b, d, 1,
                      &f, NULL) == CFT_OK, "add");
        CHECK(f == 0 && get32(d) == 0x40000000u, "1 + 1 = 2, exactly");
        CHECK(cft_save_all_flags(dev) == saved,
              "an exact call changes no flag");
        {
            uint8_t cls = 0xff;
            put32(a, 0x7fa00000u);
            CHECK(cft_class(dev, CFT_FP32, a, &cls, 1) == CFT_OK, "class");
            CHECK(cls == CFT_CLASS_SNAN, "and it IS a signaling NaN");
            CHECK(cft_save_all_flags(dev) == saved,
                  "which class reports without signalling (5.7.2)");
        }

        /* THE PER-ELEMENT UNION. One batch call whose four elements
         * each raise something different puts all four in the word at
         * once - the same OR the call returns. */
        {
            uint8_t va[16], vb[16], vd[16];
            uint32_t want = (uint32_t)(CFT_FLAG_OVERFLOW |
                                       CFT_FLAG_UNDERFLOW |
                                       CFT_FLAG_INEXACT |
                                       CFT_FLAG_INVALID);
            put32(va + 0,  0x7f7fffffu); put32(vb + 0,  0x7f7fffffu);
            put32(va + 4,  0x00000001u); put32(vb + 4,  0x3eaaaaabu);
            put32(va + 8,  0x3f800000u); put32(vb + 8,  0x3f800000u);
            put32(va + 12, 0x7fa00000u); put32(vb + 12, 0x3f800000u);
            cft_lower_flags(dev, CFT_FLAGS_ALL);
            CHECK(cft_run(dev, CFT_MUL, CFT_FP32, CFT_RNE, va, vb, NULL,
                          vd, 4, &f, NULL) == CFT_OK, "mul x4");
            CHECK(f == want, "the batch's flags are the union of its "
                  "elements': 0x%02x want 0x%02x", (unsigned)f,
                  (unsigned)want);
            CHECK(cft_save_all_flags(dev) == want,
                  "and the word gets that same union in one call");
        }

        /* LOWER BY MASK: only the named flags go down, and testFlags is
         * 5.7.4's "whether ANY of the flags ... are raised". */
        cft_lower_flags(dev, CFT_FLAGS_ALL);
        cft_raise_flags(dev, CFT_FLAGS_ALL);
        CHECK(cft_save_all_flags(dev) == CFT_FLAGS_ALL, "raise all");
        cft_lower_flags(dev, CFT_FLAG_INEXACT | CFT_FLAG_UNDERFLOW);
        CHECK(cft_save_all_flags(dev) ==
              (CFT_FLAGS_ALL & ~(uint32_t)(CFT_FLAG_INEXACT |
                                           CFT_FLAG_UNDERFLOW)),
              "lowering two leaves the other three standing");
        CHECK(cft_test_flags(dev, CFT_FLAG_INEXACT) == 0, "inexact is down");
        CHECK(cft_test_flags(dev, CFT_FLAG_INVALID) == 1, "invalid is up");
        CHECK(cft_test_flags(dev, CFT_FLAG_INEXACT | CFT_FLAG_INVALID) == 1,
              "ANY, not all");
        CHECK(cft_test_flags(dev, 0) == 0, "the empty group tests false");

        /* RAISE BY MASK, one bit at a time. */
        cft_lower_flags(dev, CFT_FLAGS_ALL);
        for (i = 0; i < 5; i++) {
            const uint32_t bit = 1u << i;
            cft_raise_flags(dev, bit);
            CHECK(cft_test_flags(dev, bit) == 1, "raised bit %d", i);
        }
        CHECK(cft_save_all_flags(dev) == CFT_FLAGS_ALL,
              "five raises make the whole set");

        /* SAVE / RESTORE ROUND TRIP, which is what 5.7.4 says the
         * saveAllFlags result is for: "for use as the first operand to
         * a restoreFlags or testSavedFlags operation". */
        cft_lower_flags(dev, CFT_FLAGS_ALL);
        cft_raise_flags(dev, CFT_FLAG_INVALID | CFT_FLAG_OVERFLOW);
        saved = cft_save_all_flags(dev);
        cft_lower_flags(dev, CFT_FLAGS_ALL);
        cft_raise_flags(dev, CFT_FLAG_INEXACT);
        cft_restore_flags(dev, saved, CFT_FLAGS_ALL);
        CHECK(cft_save_all_flags(dev) == saved,
              "restore over the whole set is a round trip: 0x%02x vs "
              "0x%02x", (unsigned)cft_save_all_flags(dev),
              (unsigned)saved);

        /* restoreFlags LOWERS inside the mask as well as raising - a
         * flag that is low in `saved` comes back low - and touches
         * nothing outside it. An OR-only implementation passes the
         * round trip above and fails this. */
        cft_lower_flags(dev, CFT_FLAGS_ALL);
        cft_raise_flags(dev, CFT_FLAGS_ALL);
        cft_restore_flags(dev, 0, CFT_FLAG_INEXACT);
        CHECK(cft_save_all_flags(dev) ==
              (CFT_FLAGS_ALL & ~(uint32_t)CFT_FLAG_INEXACT),
              "restoring a low flag lowers it");
        cft_restore_flags(dev, CFT_FLAG_INEXACT | CFT_FLAG_INVALID,
                          CFT_FLAG_INEXACT);
        CHECK(cft_save_all_flags(dev) == CFT_FLAGS_ALL,
              "and restoring a high one raises it");
        cft_lower_flags(dev, CFT_FLAGS_ALL);
        cft_restore_flags(dev, CFT_FLAGS_ALL, CFT_FLAG_DIVBYZERO);
        CHECK(cft_save_all_flags(dev) == (uint32_t)CFT_FLAG_DIVBYZERO,
              "outside the mask nothing moves");

        /* testSavedFlags: the same question, asked of a value the
         * caller holds. No device, so no state can affect it. */
        CHECK(cft_test_saved_flags(CFT_FLAG_INVALID | CFT_FLAG_INEXACT,
                                   CFT_FLAG_INEXACT) == 1, "saved: any");
        CHECK(cft_test_saved_flags(CFT_FLAG_INVALID,
                                   CFT_FLAG_INEXACT) == 0, "saved: none");
        CHECK(cft_test_saved_flags(0, CFT_FLAGS_ALL) == 0, "saved: empty");
        CHECK(cft_test_saved_flags(CFT_FLAGS_ALL, CFT_FLAGS_ALL) == 1,
              "saved: full");

        /* A NULL device is a word that is permanently zero, and none
         * of the six may dereference it. */
        CHECK(cft_save_all_flags(NULL) == 0, "NULL device saves 0");
        CHECK(cft_test_flags(NULL, CFT_FLAGS_ALL) == 0, "NULL tests 0");
        cft_raise_flags(NULL, CFT_FLAGS_ALL);
        cft_lower_flags(NULL, CFT_FLAGS_ALL);
        cft_restore_flags(NULL, CFT_FLAGS_ALL, CFT_FLAGS_ALL);
        CHECK(cft_save_all_flags(NULL) == 0, "and still 0 afterwards");

        /* ---- 9.6's magnitude forms ------------------------------ *
         *
         * Values derived from the standard's own sentence rather than
         * from either implementation:
         *
         *   "minimumMagnitude(x, y) is x if |x| < |y|, y if |y| < |x|,
         *    otherwise minimum(x, y)."
         */
        cft_lower_flags(dev, CFT_FLAGS_ALL);

        /* The magnitude decides and the sign has no vote:
         * |-1| < |+2|, so minimumMagnitude(-1, +2) is -1 even though
         * -1 is also the smaller number, and maximumMagnitude is +2. */
        put32(a, 0xbf800000u);                  /* -1.0 */
        put32(b, 0x40000000u);                  /* +2.0 */
        f = 0xdead;
        CHECK(cft_min_mag(dev, CFT_FP32, a, b, d, 1, &f) == CFT_OK, "minmag");
        CHECK(get32(d) == 0xbf800000u && f == 0, "minimumMagnitude(-1, 2)");
        CHECK(cft_max_mag(dev, CFT_FP32, a, b, d, 1, &f) == CFT_OK, "maxmag");
        CHECK(get32(d) == 0x40000000u && f == 0, "maximumMagnitude(-1, 2)");

        /* ... and the other way round, where it disagrees with plain
         * minimum: |+2| > |-1| makes -1 the minimum-magnitude, while
         * minimum(-1, +2) would also be -1; so use -3 and +2, where
         * minimum is -3 and minimumMagnitude is +2. */
        put32(a, 0xc0400000u);                  /* -3.0 */
        put32(b, 0x40000000u);                  /* +2.0 */
        CHECK(cft_min_mag(dev, CFT_FP32, a, b, d, 1, &f) == CFT_OK, "minmag");
        CHECK(get32(d) == 0x40000000u,
              "minimumMagnitude(-3, 2) is +2 where minimum(-3, 2) is -3");
        CHECK(cft_max_mag(dev, CFT_FP32, a, b, d, 1, &f) == CFT_OK, "maxmag");
        CHECK(get32(d) == 0xc0400000u,
              "maximumMagnitude(-3, 2) is -3 where maximum(-3, 2) is +2");

        /* EQUAL MAGNITUDES OF OPPOSITE SIGN: 9.6's "otherwise", so the
         * base operation decides, and 9.6 says "-0 compares less than
         * +0" for minimum and "+0 compares greater than -0" for
         * maximum. Both orders of the operands, because preferring x
         * or preferring y is exactly the wrong answer here. */
        put32(a, 0x40400000u);                  /* +3.0 */
        put32(b, 0xc0400000u);                  /* -3.0 */
        CHECK(cft_min_mag(dev, CFT_FP32, a, b, d, 1, &f) == CFT_OK, "minmag");
        CHECK(get32(d) == 0xc0400000u,
              "minimumMagnitude(+3, -3) defers to minimum: -3");
        CHECK(cft_min_mag(dev, CFT_FP32, b, a, d, 1, &f) == CFT_OK, "minmag");
        CHECK(get32(d) == 0xc0400000u, "and -3 whichever way round");
        CHECK(cft_max_mag(dev, CFT_FP32, a, b, d, 1, &f) == CFT_OK, "maxmag");
        CHECK(get32(d) == 0x40400000u,
              "maximumMagnitude(+3, -3) defers to maximum: +3");
        CHECK(cft_max_mag(dev, CFT_FP32, b, a, d, 1, &f) == CFT_OK, "maxmag");
        CHECK(get32(d) == 0x40400000u, "and +3 whichever way round");

        put32(a, 0x00000000u);                  /* +0 */
        put32(b, 0x80000000u);                  /* -0 */
        CHECK(cft_min_mag(dev, CFT_FP32, a, b, d, 1, &f) == CFT_OK, "minmag");
        CHECK(get32(d) == 0x80000000u, "min of the two zeros is -0");
        CHECK(cft_max_mag(dev, CFT_FP32, a, b, d, 1, &f) == CFT_OK, "maxmag");
        CHECK(get32(d) == 0x00000000u, "max of the two zeros is +0");
        CHECK(cft_minnum_mag(dev, CFT_FP32, b, a, d, 1, &f) == CFT_OK,
              "minnummag");
        CHECK(get32(d) == 0x80000000u, "and the Number forms agree");
        CHECK(cft_maxnum_mag(dev, CFT_FP32, b, a, d, 1, &f) == CFT_OK,
              "maxnummag");
        CHECK(get32(d) == 0x00000000u, "and the Number forms agree");

        /* NaNs: |NaN| is unordered, so every NaN case is 9.6's
         * "otherwise" and each form inherits the NaN rule of the
         * operation it names. */
        put32(a, 0x7fc00000u);                  /* quiet NaN */
        put32(b, 0x3f800000u);                  /* 1.0 */
        f = 0xdead;
        CHECK(cft_min_mag(dev, CFT_FP32, a, b, d, 1, &f) == CFT_OK, "minmag");
        CHECK(get32(d) == 0x7fc00000u && f == 0,
              "minimumMagnitude propagates a quiet NaN, quietly");
        CHECK(cft_minnum_mag(dev, CFT_FP32, a, b, d, 1, &f) == CFT_OK,
              "minnummag");
        CHECK(get32(d) == 0x3f800000u && f == 0,
              "minimumMagnitudeNumber returns the number");
        put32(a, 0x7fa00000u);                  /* signaling NaN */
        CHECK(cft_maxnum_mag(dev, CFT_FP32, a, b, d, 1, &f) == CFT_OK,
              "maxnummag");
        CHECK(get32(d) == 0x3f800000u && f == (uint32_t)CFT_FLAG_INVALID,
              "a signaling NaN signals invalid and is 'otherwise "
              "ignored and not converted to a quiet NaN' (9.6)");
        CHECK(cft_max_mag(dev, CFT_FP32, a, b, d, 1, &f) == CFT_OK, "maxmag");
        CHECK(get32(d) == 0x7fc00000u && f == (uint32_t)CFT_FLAG_INVALID,
              "where maximumMagnitude quiets it");
        put32(b, 0x7fc00000u);                  /* sNaN and qNaN */
        CHECK(cft_minnum_mag(dev, CFT_FP32, a, b, d, 1, &f) == CFT_OK,
              "minnummag");
        CHECK(get32(d) == 0x7fc00000u && f == (uint32_t)CFT_FLAG_INVALID,
              "two NaNs give a quiet NaN even in the Number forms");

        /* Infinities and subnormals sit on the same magnitude ladder
         * as everything else. */
        put32(a, 0xff800000u);                  /* -inf */
        put32(b, 0x00000001u);                  /* smallest subnormal */
        CHECK(cft_min_mag(dev, CFT_FP32, a, b, d, 1, &f) == CFT_OK, "minmag");
        CHECK(get32(d) == 0x00000001u && f == 0,
              "the subnormal has the smaller magnitude");
        CHECK(cft_max_mag(dev, CFT_FP32, a, b, d, 1, &f) == CFT_OK, "maxmag");
        CHECK(get32(d) == 0xff800000u && f == 0, "and -inf the larger");

        /* The flags of the four reach the status word like every other
         * entry point's - the check the hook's negative control
         * breaks. */
        cft_lower_flags(dev, CFT_FLAGS_ALL);
        put32(a, 0x7fa00000u);
        put32(b, 0x3f800000u);
        CHECK(cft_min_mag(dev, CFT_FP32, a, b, d, 1, &f) == CFT_OK, "minmag");
        CHECK(cft_save_all_flags(dev) == (uint32_t)CFT_FLAG_INVALID,
              "cft_min_mag ORs its flags into the status word");
        cft_lower_flags(dev, CFT_FLAGS_ALL);

        /* d may alias a or b: each element is read before it is
         * written, as everywhere else in this library. */
        {
            uint8_t va[8], vb[8];
            put32(va + 0, 0xc0400000u); put32(vb + 0, 0x40000000u);
            put32(va + 4, 0x00000001u); put32(vb + 4, 0x80000000u);
            CHECK(cft_max_mag(dev, CFT_FP32, va, vb, va, 2, &f) == CFT_OK,
                  "maxmag aliasing a");
            CHECK(get32(va + 0) == 0xc0400000u &&
                  get32(va + 4) == 0x00000001u, "d aliases a");
            put32(va + 0, 0xc0400000u); put32(vb + 0, 0x40000000u);
            put32(va + 4, 0x00000001u); put32(vb + 4, 0x80000000u);
            CHECK(cft_max_mag(dev, CFT_FP32, va, vb, vb, 2, &f) == CFT_OK,
                  "maxmag aliasing b");
            CHECK(get32(vb + 0) == 0xc0400000u &&
                  get32(vb + 4) == 0x00000001u, "d aliases b");
        }

        /* n == 0 is a no-op that raises nothing; a missing operand, a
         * bad format and a NULL device are refused. */
        f = 0xdead;
        CHECK(cft_min_mag(dev, CFT_FP32, NULL, NULL, NULL, 0, &f) == CFT_OK,
              "n == 0 is OK");
        CHECK(f == 0, "and raises nothing");
        CHECK(cft_max_mag(dev, CFT_FP32, a, NULL, d, 1, &f) ==
              CFT_ERR_INVALID_ARGUMENT, "b is required");
        CHECK(cft_minnum_mag(dev, (cft_format)9, a, b, d, 1, &f) ==
              CFT_ERR_INVALID_ARGUMENT, "bad format is refused");
        CHECK(cft_maxnum_mag(NULL, CFT_FP32, a, b, d, 1, &f) ==
              CFT_ERR_INVALID_ARGUMENT, "NULL device is refused");

        /* Host operations, so they do not gate on the device's opcode
         * groups the way CFT_MIN does - which is exactly why the base
         * operation is restated inside them rather than issued as
         * opcode 7. Nothing to assert about a software device here
         * beyond that they work, but the fp256 leg proves the width
         * is not special-cased at 32 bits. */
        {
            uint8_t wa[32], wb[32], wd[32];
            memset(wa, 0, sizeof wa);
            memset(wb, 0, sizeof wb);
            wa[31] = 0x80;                      /* -0 at fp256 */
            CHECK(cft_min_mag(dev, CFT_FP256, wa, wb, wd, 1, &f) == CFT_OK,
                  "fp256 minmag");
            CHECK(memcmp(wd, wa, 32) == 0, "min of the fp256 zeros is -0");
            CHECK(cft_max_mag(dev, CFT_FP256, wa, wb, wd, 1, &f) == CFT_OK,
                  "fp256 maxmag");
            CHECK(memcmp(wd, wb, 32) == 0, "max of the fp256 zeros is +0");
        }
        cft_lower_flags(dev, CFT_FLAGS_ALL);
    }

    /* --- the formatOf arithmetic operations (754-2019 5.4.1) ------
     *
     * host/tests/formatof_check.py proves these against the model over
     * every ordered pair at scale and the published sets replay them;
     * what belongs HERE is this file's charter - refusals, aliasing,
     * and the rows whose expected bits come from reading 5.4.1 rather
     * than from either implementation.
     *
     * Every anchor below is derivable with the clause open, and every
     * constant is built from the format's own field layout rather than
     * typed:
     *
     *  - THE DOUBLE ROUNDING. binary64 operands, binary32 destination.
     *    a = 1 + 2^-24 is exactly the midpoint between binary32's 1 and
     *    1 + 2^-23, and it is a binary64 value; b = 1, so the product is
     *    that midpoint EXACTLY; c is binary64's smallest subnormal,
     *    2^-1074, which is positive. The infinitely precise a*b + c is
     *    therefore strictly above the midpoint, so 5.4.1's single
     *    rounding to binary32 gives 1 + 2^-23. Round to binary64 first
     *    and the addend disappears under a half-ulp of 2^-53: the
     *    intermediate is the midpoint, the second rounding ties to even,
     *    and the answer comes back 1.0 - one ulp low. Both routes are
     *    issued below, so the difference is exhibited rather than
     *    described.
     *  - THE DESTINATION OWNS THE EXCEPTIONS. 2^100 * 2^100 is an
     *    ordinary binary64 multiply and an overflow in binary32; 2^-150
     *    is an ordinary binary64 normal and half of binary32's least
     *    subnormal, so it is an exact tie between zero and that
     *    subnormal, and 7.5's underflow rises with inexact. The
     *    direction decides which side of both, which is why each is
     *    issued in two attributes.
     *  - THE WIDER DESTINATION HAS THE WIDER RANGE. The square of
     *    binary32's least subnormal underflows to zero IN binary32 and
     *    is an ordinary binary64 normal, 2^-298, exactly. The same two
     *    calls, one opcode apart, are in the test.
     *  - SQUARE ROOT CROSSES RANGES TOO. sqrt of binary128's 2^-2000 is
     *    binary64's 2^-1000, exact; into binary32 the root of 2^-400
     *    lands below the subnormal floor and underflows to zero.
     *  - THE SAME-FORMAT CASE IS THE OPERATION THAT WAS ALREADY HERE,
     *    bit for bit and flag for flag, which is the base case a reader
     *    will assume.
     */
    {
        uint8_t a8[8 * 8], b8[8 * 8], c8[8 * 8], d4[8 * 4], d8[8 * 8];
        uint8_t a16[16];
        uint32_t fl = 0xdead, bus = 0xdead, fl2 = 0;
        const uint32_t FL_OVF = CFT_FLAG_OVERFLOW | CFT_FLAG_INEXACT;
        const uint32_t FL_UNF = CFT_FLAG_UNDERFLOW | CFT_FLAG_INEXACT;
        int k;

        /* --- the double rounding, exhibited --- */
        /* a = 1 + 2^-24 in binary64: exponent field = bias, and the
         * fraction bit whose weight is 2^-24 sits at 52 - 24. */
        put64(a8, ((uint64_t)1023 << 52) | ((uint64_t)1 << (52 - 24)));
        put64(b8, (uint64_t)1023 << 52);                    /* 1.0 */
        put64(c8, (uint64_t)1);                             /* 2^-1074 */
        st = cft_formatof_fma(dev, CFT_FP64, CFT_FP32, CFT_RNE,
                              a8, b8, c8, d4, 1, &fl, &bus);
        CHECK(st == CFT_OK &&
              get32(d4) == (((uint32_t)127 << 23) | 1u) &&
              fl == CFT_FLAG_INEXACT,
              "formatOf-fusedMultiplyAdd rounds ONCE into binary32: "
              "got 0x%08x/0x%02x want 0x%08x/0x%02x",
              (unsigned)get32(d4), (unsigned)fl,
              (unsigned)(((uint32_t)127 << 23) | 1u),
              (unsigned)CFT_FLAG_INEXACT);
        CHECK(bus == 0,
              "the narrowing route issues no device pass, so bus_out is 0");
        /* the control: the same operands rounded in binary64 first and
         * then converted - the route 5.4.1 does NOT describe */
        st = cft_run(dev, CFT_FMA, CFT_FP64, CFT_RNE, a8, b8, c8, d8, 1,
                     &fl, NULL);
        CHECK(st == CFT_OK, "fma in binary64: %s", cft_strerror(st));
        st = cft_convert(dev, CFT_FP64, CFT_FP32, CFT_RNE, d8, d4, 1, &fl2);
        CHECK(st == CFT_OK && get32(d4) == ((uint32_t)127 << 23),
              "rounding in the source format first ties to even and "
              "loses an ulp - got 0x%08x, which is why formatOf is not "
              "a composition in this direction", (unsigned)get32(d4));

        /* --- the destination owns the overflow --- */
        put64(a8, (uint64_t)(1023 + 100) << 52);            /* 2^100 */
        st = cft_formatof_mul(dev, CFT_FP64, CFT_FP32, CFT_RNE,
                              a8, a8, d4, 1, &fl, NULL);
        CHECK(st == CFT_OK && get32(d4) == 0x7f800000u && fl == FL_OVF,
              "2^200 overflows the binary32 destination: 0x%08x/0x%02x",
              (unsigned)get32(d4), (unsigned)fl);
        st = cft_formatof_mul(dev, CFT_FP64, CFT_FP32, CFT_RTZ,
                              a8, a8, d4, 1, &fl, NULL);
        CHECK(st == CFT_OK && get32(d4) == 0x7f7fffffu && fl == FL_OVF,
              "7.4: roundTowardZero delivers the largest finite instead "
              "of an infinity - 0x%08x/0x%02x",
              (unsigned)get32(d4), (unsigned)fl);
        /* the same multiply IN binary64 raises nothing at all */
        st = cft_run(dev, CFT_MUL, CFT_FP64, CFT_RNE, a8, a8, NULL, d8, 1,
                     &fl, NULL);
        CHECK(st == CFT_OK && fl == 0,
              "2^100 * 2^100 is unremarkable in binary64, which is what "
              "makes the row above a statement about the destination");

        /* --- the destination owns the tininess --- */
        put64(a8, (uint64_t)(1023 - 150) << 52);            /* 2^-150 */
        put64(b8, (uint64_t)1023 << 52);                    /* 1.0 */
        st = cft_formatof_mul(dev, CFT_FP64, CFT_FP32, CFT_RNE,
                              a8, b8, d4, 1, &fl, NULL);
        CHECK(st == CFT_OK && get32(d4) == 0 && fl == FL_UNF,
              "half of binary32's least subnormal is an exact tie and "
              "roundTiesToEven takes the even neighbour, zero: "
              "0x%08x/0x%02x", (unsigned)get32(d4), (unsigned)fl);
        st = cft_formatof_mul(dev, CFT_FP64, CFT_FP32, CFT_RUP,
                              a8, b8, d4, 1, &fl, NULL);
        CHECK(st == CFT_OK && get32(d4) == 1u && fl == FL_UNF,
              "roundTowardPositive takes the other side of that tie: "
              "0x%08x/0x%02x", (unsigned)get32(d4), (unsigned)fl);

        /* --- the wider destination has the wider range --- */
        put32(a8, 1u);                                /* 2^-149, binary32 */
        st = cft_formatof_mul(dev, CFT_FP32, CFT_FP64, CFT_RNE,
                              a8, a8, d8, 1, &fl, &bus);
        CHECK(st == CFT_OK &&
              get64(d8) == ((uint64_t)(1023 - 298) << 52) && fl == 0,
              "the square of binary32's least subnormal is an EXACT "
              "binary64 normal, 2^-298: 0x%016llx/0x%02x",
              (unsigned long long)get64(d8), (unsigned)fl);
        CHECK(bus == 0, "a widening pass reports a clean bus word");
        st = cft_run(dev, CFT_MUL, CFT_FP32, CFT_RNE, a8, a8, NULL, d4, 1,
                     &fl, NULL);
        CHECK(st == CFT_OK && get32(d4) == 0 && fl == FL_UNF,
              "and the same multiply in binary32 vanishes, which is the "
              "whole reason 5.4.1 asks for the cross-format form");

        /* --- square root across ranges --- */
        memset(a16, 0, sizeof a16);
        for (k = 0; k < 15; k++)                  /* 2^-2000 in binary128 */
            if ((((long)16383 - 2000) >> k) & 1)
                a16[(112 + k) / 8] |= (uint8_t)(1u << ((112 + k) % 8));
        st = cft_formatof_sqrt(dev, CFT_FP128, CFT_FP64, CFT_RNE,
                               a16, d8, 1, &fl, NULL);
        CHECK(st == CFT_OK &&
              get64(d8) == ((uint64_t)(1023 - 1000) << 52) && fl == 0,
              "sqrt of binary128's 2^-2000 is binary64's 2^-1000, "
              "exactly: 0x%016llx/0x%02x",
              (unsigned long long)get64(d8), (unsigned)fl);
        memset(a16, 0, sizeof a16);
        for (k = 0; k < 15; k++)                   /* 2^-400 in binary128 */
            if ((((long)16383 - 400) >> k) & 1)
                a16[(112 + k) / 8] |= (uint8_t)(1u << ((112 + k) % 8));
        st = cft_formatof_sqrt(dev, CFT_FP128, CFT_FP32, CFT_RNE,
                               a16, d4, 1, &fl, NULL);
        CHECK(st == CFT_OK && get32(d4) == 0 && fl == FL_UNF,
              "its root 2^-200 is below binary32's subnormal floor, so "
              "the cross-format square root CAN underflow where the "
              "same-format one cannot: 0x%08x/0x%02x",
              (unsigned)get32(d4), (unsigned)fl);

        /* --- division, and the exceptions of 7.2/7.3 in the
         *     destination's encoding --- */
        put64(a8, (uint64_t)1023 << 52);                       /* 1.0 */
        put64(b8, ((uint64_t)(1023 + 1) << 52) | ((uint64_t)1 << 51));
        st = cft_formatof_div(dev, CFT_FP64, CFT_FP32, CFT_RNE,
                              a8, b8, d4, 1, &fl, NULL);
        CHECK(st == CFT_OK && get32(d4) == 0x3eaaaaabu &&
              fl == CFT_FLAG_INEXACT,
              "1/3 correctly rounded straight into binary32 is "
              "0x3eaaaaab: got 0x%08x/0x%02x",
              (unsigned)get32(d4), (unsigned)fl);
        put64(c8, 0);                                          /* +0 */
        st = cft_formatof_div(dev, CFT_FP64, CFT_FP32, CFT_RNE,
                              a8, c8, d4, 1, &fl, NULL);
        CHECK(st == CFT_OK && get32(d4) == 0x7f800000u &&
              fl == CFT_FLAG_DIVBYZERO,
              "7.3 divideByZero, delivered in the DESTINATION: "
              "0x%08x/0x%02x", (unsigned)get32(d4), (unsigned)fl);
        st = cft_formatof_div(dev, CFT_FP64, CFT_FP32, CFT_RNE,
                              c8, c8, d4, 1, &fl, NULL);
        CHECK(st == CFT_OK && get32(d4) == 0x7fc00000u &&
              fl == CFT_FLAG_INVALID,
              "0/0 is the destination's canonical quiet NaN with "
              "invalid: 0x%08x/0x%02x", (unsigned)get32(d4), (unsigned)fl);

        /* --- 6.2.1: a signaling NaN operand signals in every one of
         *     the six, and the quiet NaN it delivers is the
         *     DESTINATION's --- */
        put64(a8, ((uint64_t)2047 << 52) | (uint64_t)1);       /* sNaN */
        put64(b8, (uint64_t)1023 << 52);
        st = cft_formatof_add(dev, CFT_FP64, CFT_FP32, CFT_RNE,
                              a8, b8, d4, 1, &fl, NULL);
        CHECK(st == CFT_OK && get32(d4) == 0x7fc00000u &&
              fl == CFT_FLAG_INVALID, "sNaN through formatOf-addition");
        st = cft_formatof_sqrt(dev, CFT_FP64, CFT_FP32, CFT_RNE,
                               a8, d4, 1, &fl, NULL);
        CHECK(st == CFT_OK && get32(d4) == 0x7fc00000u &&
              fl == CFT_FLAG_INVALID, "sNaN through formatOf-squareRoot");
        st = cft_formatof_fma(dev, CFT_FP64, CFT_FP32, CFT_RNE,
                              b8, b8, a8, d4, 1, &fl, NULL);
        CHECK(st == CFT_OK && get32(d4) == 0x7fc00000u &&
              fl == CFT_FLAG_INVALID,
              "sNaN in the addend of formatOf-fusedMultiplyAdd");
        /* and a widening source: the conversion raises it on the way */
        put32(a8, 0x7f800001u);                          /* binary32 sNaN */
        put32(b8, 0x3f800000u);
        st = cft_formatof_add(dev, CFT_FP32, CFT_FP256, CFT_RNE,
                              a8, b8, d8, 1, &fl, NULL);
        CHECK(st == CFT_OK && fl == CFT_FLAG_INVALID,
              "a signaling NaN signals once, not twice, on the widening "
              "route: 0x%02x", (unsigned)fl);

        /* --- the same-format case IS the existing operation --- */
        put32(a8, 0x3f800001u);
        put32(b8, 0x33800000u);
        st = cft_formatof_add(dev, CFT_FP32, CFT_FP32, CFT_RNE,
                              a8, b8, d4, 1, &fl, NULL);
        CHECK(st == CFT_OK, "same-format add: %s", cft_strerror(st));
        st = cft_run(dev, CFT_ADD, CFT_FP32, CFT_RNE, a8, NULL, b8,
                     d4 + 4, 1, &fl2, NULL);
        CHECK(st == CFT_OK && get32(d4) == get32(d4 + 4) && fl == fl2,
              "sfmt == dfmt is cft_run's own answer: 0x%08x/0x%02x vs "
              "0x%08x/0x%02x", (unsigned)get32(d4), (unsigned)fl,
              (unsigned)get32(d4 + 4), (unsigned)fl2);
        st = cft_formatof_sqrt(dev, CFT_FP32, CFT_FP32, CFT_RDN,
                               a8, d4, 1, &fl, NULL);
        CHECK(st == CFT_OK, "same-format sqrt: %s", cft_strerror(st));
        st = cft_sqrt(dev, CFT_FP32, CFT_RDN, a8, d4 + 4, 1, &fl2, NULL);
        CHECK(st == CFT_OK && get32(d4) == get32(d4 + 4) && fl == fl2,
              "and cft_sqrt's, for the operation that has no opcode");

        /* --- batches: the element loop and the flag OR --- */
        for (k = 0; k < 8; k++)
            put64(a8 + 8 * k, (uint64_t)(1023 + 100 * k) << 52);
        for (k = 0; k < 8; k++)
            put64(b8 + 8 * k, (uint64_t)1023 << 52);
        st = cft_formatof_mul(dev, CFT_FP64, CFT_FP32, CFT_RNE,
                              a8, b8, d4, 8, &fl, NULL);
        CHECK(st == CFT_OK && (fl & CFT_FLAG_OVERFLOW),
              "a batch's flag word is the OR across it");
        CHECK(get32(d4) == ((uint32_t)127 << 23),
              "element 0 of that batch is 2^0, untouched by element 7's "
              "overflow: 0x%08x", (unsigned)get32(d4));
        CHECK(get32(d4 + 4 * 7) == 0x7f800000u,
              "and element 7 is the infinity");

        /* --- subtraction, where the cancellation is exact and the
         *     destination still decides the sign of the zero ---
         *
         * (1 + 2^-52) - 1 is 2^-52 EXACTLY - a catastrophic
         * cancellation in binary64 whose whole result is one bit, and
         * 2^-52 is an ordinary binary32 normal (binary32's emin is
         * -126), so nothing is lost on the way down and nothing is
         * signalled. And 6.3's rule is the destination's: an exact
         * cancellation is +0 in every attribute except
         * roundTowardNegative. */
        put64(a8, ((uint64_t)1023 << 52) | (uint64_t)1);   /* 1 + 2^-52 */
        put64(b8, (uint64_t)1023 << 52);                   /* 1.0 */
        st = cft_formatof_sub(dev, CFT_FP64, CFT_FP32, CFT_RNE,
                              a8, b8, d4, 1, &fl, NULL);
        CHECK(st == CFT_OK &&
              get32(d4) == ((uint32_t)(127 - 52) << 23) && fl == 0,
              "formatOf-subtraction of a cancellation: got 0x%08x/0x%02x "
              "want 0x%08x/0x00", (unsigned)get32(d4), (unsigned)fl,
              (unsigned)((uint32_t)(127 - 52) << 23));
        st = cft_formatof_sub(dev, CFT_FP64, CFT_FP32, CFT_RNE,
                              b8, b8, d4, 1, &fl, NULL);
        CHECK(st == CFT_OK && get32(d4) == 0 && fl == 0,
              "an exact cancellation is +0 under roundTiesToEven");
        st = cft_formatof_sub(dev, CFT_FP64, CFT_FP32, CFT_RDN,
                              b8, b8, d4, 1, &fl, NULL);
        CHECK(st == CFT_OK && get32(d4) == 0x80000000u && fl == 0,
              "6.3: and -0 under roundTowardNegative, in the "
              "DESTINATION's encoding: 0x%08x", (unsigned)get32(d4));
        /* the same subtraction into a WIDER destination is the same
         * value, which is what makes the row above about the operation
         * rather than about binary32 */
        st = cft_formatof_sub(dev, CFT_FP64, CFT_FP256, CFT_RNE,
                              a8, b8, d8, 1, &fl, NULL);
        CHECK(st == CFT_OK && fl == 0,
              "and into binary256 it is exact too: 0x%02x", (unsigned)fl);


        /* --- a hair above half the destination's least subnormal ----
         *
         * Half of binary32's least subnormal is 2^-150, an ordinary
         * binary64 normal; binary64's own least subnormal added to it
         * puts the exact sum strictly ABOVE that half-way point, so
         * roundTiesToEven delivers binary32's least subnormal and not
         * zero. Exactly ON the half-way point the tie goes to the even
         * neighbour, which is zero - and having both rows is the
         * difference between testing the boundary and testing near it.
         *
         * This is the family that caught the MPFR harness reaching the
         * destination's subnormal grid through a recipe that flushes:
         * the library was right and the oracle was not. It is pinned in
         * C as well as in the model, because C is where it would be
         * ported wrong. */
        put64(a8, (uint64_t)(1023 - 150) << 52);           /* 2^-150 */
        put64(b8, (uint64_t)1);                            /* 2^-1074 */
        st = cft_formatof_add(dev, CFT_FP64, CFT_FP32, CFT_RNE,
                              a8, b8, d4, 1, &fl, NULL);
        CHECK(st == CFT_OK && get32(d4) == 1u && fl == FL_UNF,
              "a hair above half the least subnormal rounds UP to it: "
              "0x%08x/0x%02x", (unsigned)get32(d4), (unsigned)fl);
        put64(b8, 0);
        st = cft_formatof_add(dev, CFT_FP64, CFT_FP32, CFT_RNE,
                              a8, b8, d4, 1, &fl, NULL);
        CHECK(st == CFT_OK && get32(d4) == 0 && fl == FL_UNF,
              "and exactly ON it the tie goes to the even neighbour, "
              "zero: 0x%08x/0x%02x", (unsigned)get32(d4), (unsigned)fl);
        /* negated: the least subnormal keeps its sign, and so would the
         * zero, which is 6.3's rule for a value that is zero because of
         * rounding */
        put64(a8, ((uint64_t)(1023 - 150) << 52) | ((uint64_t)1 << 63));
        put64(b8, ((uint64_t)1) | ((uint64_t)1 << 63));
        st = cft_formatof_add(dev, CFT_FP64, CFT_FP32, CFT_RNE,
                              a8, b8, d4, 1, &fl, NULL);
        CHECK(st == CFT_OK && get32(d4) == 0x80000001u && fl == FL_UNF,
              "and negated, the least subnormal with its sign: 0x%08x",
              (unsigned)get32(d4));

        /* --- and the 7.1 status word, from formatOf calls ------------
         *
         * Package B's word is only worth having if every entry point
         * feeds it, so these four rows ask it of THIS package's six.
         * The interesting one is the last: a call that signals nothing
         * must leave the word exactly as it found it, which is the
         * difference between OR-ing a group in and assigning one. */
        cft_lower_flags(dev, CFT_FLAGS_ALL);
        CHECK(cft_test_flags(dev, CFT_FLAGS_ALL) == 0,
              "the word starts down");

        /* a narrowing multiply that is inexact and nothing else */
        put64(a8, ((uint64_t)1023 << 52) | (uint64_t)1);   /* 1 + 2^-52 */
        put64(b8, (uint64_t)1023 << 52);                   /* 1.0 */
        st = cft_formatof_mul(dev, CFT_FP64, CFT_FP32, CFT_RNE,
                              a8, b8, d4, 1, NULL, NULL);
        CHECK(st == CFT_OK &&
              cft_test_flags(dev, CFT_FLAG_INEXACT) == 1 &&
              cft_test_flags(dev, (uint32_t)(CFT_FLAGS_ALL &
                                             ~CFT_FLAG_INEXACT)) == 0,
              "a narrowing multiply raises inexact IN THE WORD, and only "
              "that - flags_out was not even asked for");

        /* a call that signals nothing leaves the word alone: the same
         * narrowing multiply by an exact power of two */
        put64(a8, (uint64_t)1023 << 52);                   /* 1.0 */
        st = cft_formatof_mul(dev, CFT_FP64, CFT_FP32, CFT_RNE,
                              a8, b8, d4, 1, &fl, NULL);
        CHECK(st == CFT_OK && fl == 0 &&
              cft_test_flags(dev, CFT_FLAG_INEXACT) == 1,
              "a formatOf call that signals nothing neither adds to the "
              "word nor lowers it");

        cft_lower_flags(dev, CFT_FLAGS_ALL);
        put64(c8, 0);                                      /* +0 */
        st = cft_formatof_div(dev, CFT_FP64, CFT_FP32, CFT_RNE,
                              a8, c8, d4, 1, NULL, NULL);
        CHECK(st == CFT_OK &&
              cft_test_flags(dev, CFT_FLAG_DIVBYZERO) == 1 &&
              cft_test_flags(dev, CFT_FLAG_INEXACT) == 0,
              "formatOf-division by zero leaves divideByZero standing and "
              "NOT the inexact of its own scaffolding - the widening "
              "route's passes are muted, which is what that is for");

        cft_lower_flags(dev, CFT_FLAGS_ALL);
        put64(a8, ((uint64_t)2047 << 52) | (uint64_t)1);   /* sNaN */
        st = cft_formatof_add(dev, CFT_FP64, CFT_FP256, CFT_RNE,
                              a8, b8, d8, 1, NULL, NULL);
        CHECK(st == CFT_OK &&
              cft_test_flags(dev, CFT_FLAG_INVALID) == 1,
              "a signaling NaN through the WIDENING route reaches the "
              "word once, through the operation rather than through its "
              "internal conversion");

        /* the accumulation itself: two calls, two different exceptions,
         * and 7.1's "lowered only at the user's request" */
        cft_lower_flags(dev, CFT_FLAGS_ALL);
        put64(a8, ((uint64_t)1023 << 52) | (uint64_t)1);
        st = cft_formatof_mul(dev, CFT_FP64, CFT_FP32, CFT_RNE,
                              a8, b8, d4, 1, NULL, NULL);
        CHECK(st == CFT_OK, "inexact call");
        put64(a8, (uint64_t)1023 << 52);
        st = cft_formatof_div(dev, CFT_FP64, CFT_FP32, CFT_RNE,
                              a8, c8, d4, 1, NULL, NULL);
        CHECK(st == CFT_OK &&
              cft_test_flags(dev, (uint32_t)(CFT_FLAG_INEXACT |
                                             CFT_FLAG_DIVBYZERO)) == 1,
              "the word accumulates across formatOf calls and is lowered "
              "only when asked");
        cft_lower_flags(dev, CFT_FLAGS_ALL);

        /* --- refusals --- */
        CHECK(cft_formatof_add(dev, (cft_format)9, CFT_FP32, CFT_RNE,
                               a8, b8, d4, 1, &fl, NULL)
              == CFT_ERR_INVALID_ARGUMENT, "bad source format refused");
        CHECK(cft_formatof_add(dev, CFT_FP32, (cft_format)-1, CFT_RNE,
                               a8, b8, d4, 1, &fl, NULL)
              == CFT_ERR_INVALID_ARGUMENT, "bad destination format refused");
        CHECK(cft_formatof_add(dev, CFT_FP32, CFT_FP32, (cft_round)5,
                               a8, b8, d4, 1, &fl, NULL)
              == CFT_ERR_INVALID_ARGUMENT,
              "a rounding direction outside 4.3's five refused - which is "
              "how 9.5's roundTiesTowardZero stays unreachable from here");
        CHECK(cft_formatof_add(dev, CFT_FP32, CFT_FP32, CFT_RNE,
                               NULL, b8, d4, 1, &fl, NULL)
              == CFT_ERR_INVALID_ARGUMENT, "NULL a refused");
        CHECK(cft_formatof_add(dev, CFT_FP32, CFT_FP32, CFT_RNE,
                               a8, NULL, d4, 1, &fl, NULL)
              == CFT_ERR_INVALID_ARGUMENT, "NULL b refused");
        CHECK(cft_formatof_fma(dev, CFT_FP32, CFT_FP32, CFT_RNE,
                               a8, b8, NULL, d4, 1, &fl, NULL)
              == CFT_ERR_INVALID_ARGUMENT, "NULL c refused by fma");
        CHECK(cft_formatof_add(dev, CFT_FP32, CFT_FP32, CFT_RNE,
                               a8, b8, NULL, 1, &fl, NULL)
              == CFT_ERR_INVALID_ARGUMENT, "NULL d refused");
        CHECK(cft_formatof_sqrt(NULL, CFT_FP32, CFT_FP32, CFT_RNE,
                                a8, d4, 1, &fl, NULL)
              == CFT_ERR_INVALID_ARGUMENT, "NULL device refused");
        fl = 0xdead;
        bus = 0xdead;
        CHECK(cft_formatof_add(dev, CFT_FP64, CFT_FP32, CFT_RNE,
                               NULL, NULL, NULL, 0, &fl, &bus) == CFT_OK &&
              fl == 0 && bus == 0,
              "n == 0 is not an error and clears both output words");
        /* sqrt reads one operand, so a NULL second argument is not its
         * business to refuse - the entry point does not have one */
        CHECK(cft_formatof_sqrt(dev, CFT_FP256, CFT_FP32, CFT_RNE,
                                a8, d4, 1, NULL, NULL) == CFT_OK,
              "flags_out and bus_out may both be NULL");
    }

    /* --- programs: the argument contract, ABI 0.9 ------------------
     *
     * What the vectors cannot express, which is this file's whole
     * remit: which arguments are refused, which may be NULL, and how
     * the struct_size handshake behaves for a caller built against the
     * older header. The BITS a program computes are device_test's and
     * seq_check.py's; nothing here runs anything interesting.
     *
     * The image below is "r4 = r0 * k[0] + k[1]; deposit r4; halt" at
     * fp32, in two shapes: with the constants in the image, and as a
     * BANK_EXT program whose constants arrive with the run
     * (docs/SEQUENCER.md revision 2, R3). */
    {
        uint8_t img[64], ext[64], bank[8], a4[4], dep[4], dig[32], dig2[32];
        uint64_t ins[3];
        size_t bytes, ext_bytes, w;
        cft_program *prog = NULL, *pext = NULL;
        cft_program_info info;
        uint32_t bus = 0xdeadbeefu;

        /* fma rd=4 ra=0 rb=k0 rc=k1, with kb and kc set (bits 28, 29) */
        ins[0] = 0u | (4ull << 8) | (0ull << 12) | (0ull << 16) |
                 (1ull << 20) | (1ull << 28) | (1ull << 29);
        ins[1] = 3ull | (4ull << 12) | (1ull << 31);      /* deposit r4 */
        ins[2] = 0ull | (1ull << 31);                     /* halt */

        memset(img, 0, sizeof img);
        put32(img + 0, 0x50544643u);      /* "CFTP" */
        put32(img + 4, 1);                /* version */
        put32(img + 8, 3);                /* n_insns */
        put32(img + 12, 2);               /* n_consts */
        put32(img + 16, 1);               /* max_deposits */
        put32(img + 20, (uint32_t)CFT_FP32);
        put32(img + 24, 0);               /* flags */
        put32(img + 28, 0);               /* reserved[1] */
        put32(img + 32, 0x3fc00000u);     /* k0 = 1.5  */
        put32(img + 36, 0x3fa00000u);     /* k1 = 1.25 */
        for (w = 0; w < 3; w++)
            put64(img + 40 + w * 8, ins[w]);
        bytes = 40 + 3 * 8;

        memcpy(ext, img, 32);
        put32(ext + 24, CFT_PROG_FLAG_BANK_EXT);
        for (w = 0; w < 3; w++)
            put64(ext + 32 + w * 8, ins[w]);
        ext_bytes = 32 + 3 * 8;
        memcpy(bank, img + 32, 8);

        put32(a4, 0x40000000u);           /* a[0] = 2.0 */

        /* -- load -- */
        CHECK(cft_program_load(NULL, img, bytes, &prog) ==
              CFT_ERR_INVALID_ARGUMENT, "program_load refuses a NULL device");
        CHECK(cft_program_load(dev, NULL, bytes, &prog) ==
              CFT_ERR_INVALID_ARGUMENT, "program_load refuses a NULL image");
        CHECK(cft_program_load(dev, img, bytes, NULL) ==
              CFT_ERR_INVALID_ARGUMENT, "program_load refuses a NULL out");
        CHECK(cft_program_load(dev, img, 31, &prog) == CFT_ERR_ARTIFACT,
              "an image shorter than its header is an artifact");
        CHECK(cft_program_load(dev, img, bytes - 1, &prog) ==
              CFT_ERR_ARTIFACT,
              "an image is exactly header + constants + instructions");
        st = cft_program_load(dev, img, bytes, &prog);
        CHECK(st == CFT_OK && prog != NULL, "program_load: %s (%s)",
              cft_strerror(st), cft_last_error());
        st = cft_program_load(dev, ext, ext_bytes, &pext);
        CHECK(st == CFT_OK && pext != NULL, "a BANK_EXT image loads: %s (%s)",
              cft_strerror(st), cft_last_error());

        /* -- info, and the struct_size handshake -- */
        CHECK(cft_program_get_info(NULL, &info) == CFT_ERR_INVALID_ARGUMENT &&
              cft_program_get_info(prog, NULL) == CFT_ERR_INVALID_ARGUMENT,
              "program_get_info refuses NULLs");
        memset(&info, 0, sizeof info);
        info.struct_size = 0;
        CHECK(cft_program_get_info(prog, &info) == CFT_ERR_INVALID_ARGUMENT,
              "a struct_size below one field is refused");
        memset(&info, 0, sizeof info);
        info.struct_size = sizeof info;
        st = cft_program_get_info(pext, &info);
        CHECK(st == CFT_OK && info.struct_size == sizeof info &&
              info.format == CFT_FP32 && info.n_insns == 3 &&
              info.n_consts == 2 && info.max_deposits == 1 &&
              info.flags == CFT_PROG_FLAG_BANK_EXT,
              "program_get_info reports the header, flags included");
        {
            /* An ABI 0.8 caller's struct ends before `flags`. It must
             * come back with the bytes it asked for and not one more:
             * a library writing a field the caller has no room for is
             * the failure the size handshake exists to prevent. */
            union { cft_program_info info; uint8_t raw[64]; } u;
            const size_t old_size = offsetof(cft_program_info, flags);
            memset(&u, 0xa5, sizeof u);
            memset(&u.info, 0, old_size);
            u.info.struct_size = old_size;
            st = cft_program_get_info(pext, &u.info);
            CHECK(st == CFT_OK && u.info.struct_size == old_size,
                  "an ABI 0.8 struct_size comes back as itself");
            for (w = old_size; w < sizeof u; w++)
                if (u.raw[w] != 0xa5)
                    break;
            CHECK(w == sizeof u,
                  "nothing past an older caller's struct_size is written "
                  "(byte %lu changed)", (unsigned long)w);
        }
        {
            /* And the 0.9 boundary, where ABI 0.10 appended its three
             * scratch fields. Each new field wants its own line here
             * or the handshake is only ever proved at the boundary it
             * had when the check was written. */
            union { cft_program_info info; uint8_t raw[64]; } u;
            const size_t old_size = offsetof(cft_program_info, n_scratch_in);
            memset(&u, 0xa5, sizeof u);
            memset(&u.info, 0, old_size);
            u.info.struct_size = old_size;
            st = cft_program_get_info(pext, &u.info);
            CHECK(st == CFT_OK && u.info.struct_size == old_size &&
                  u.info.flags == CFT_PROG_FLAG_BANK_EXT,
                  "an ABI 0.9 struct_size comes back as itself, with flags");
            for (w = old_size; w < sizeof u; w++)
                if (u.raw[w] != 0xa5)
                    break;
            CHECK(w == sizeof u,
                  "nothing past an ABI 0.9 caller's struct_size is written "
                  "(byte %lu changed)", (unsigned long)w);
        }

        /* -- run, and run_bank -- */
        CHECK(cft_program_run(NULL, a4, NULL, NULL, dep, NULL, 1,
                              NULL, &bus) == CFT_ERR_INVALID_ARGUMENT,
              "program_run refuses a NULL program");
        CHECK(bus == 0, "program_run clears bus_out before anything else");
        CHECK(cft_program_run(prog, NULL, NULL, NULL, dep, NULL, 1,
                              NULL, NULL) == CFT_ERR_INVALID_ARGUMENT,
              "the a stream is not optional");
        CHECK(cft_program_run(prog, a4, NULL, NULL, NULL, NULL, 1,
                              NULL, NULL) == CFT_ERR_INVALID_ARGUMENT,
              "a deposit budget above zero needs a deposit buffer");
        bus = 0xdeadbeefu;
        CHECK(cft_program_run(prog, NULL, NULL, NULL, NULL, NULL, 0,
                              NULL, &bus) == CFT_OK && bus == 0,
              "n == 0 is not an error and clears bus_out");
        put32(dep, 0);
        st = cft_program_run(prog, a4, NULL, NULL, dep, NULL, 1, NULL, NULL);
        CHECK(st == CFT_OK && get32(dep) == 0x40880000u,
              "2.0 * 1.5 + 1.25 = 4.25: %s 0x%08x", cft_strerror(st),
              get32(dep));

        CHECK(cft_program_run_bank(NULL, bank, 8, a4, NULL, NULL, dep,
                                   NULL, 1, NULL, NULL) ==
              CFT_ERR_INVALID_ARGUMENT,
              "program_run_bank refuses a NULL program");
        put32(dep, 0);
        st = cft_program_run_bank(pext, bank, 8, a4, NULL, NULL, dep,
                                  NULL, 1, NULL, NULL);
        CHECK(st == CFT_OK && get32(dep) == 0x40880000u,
              "the same program with its constants as data: %s 0x%08x",
              cft_strerror(st), get32(dep));
        CHECK(cft_program_run_bank(pext, bank, 4, a4, NULL, NULL, dep,
                                   NULL, 1, NULL, NULL) ==
              CFT_ERR_INVALID_ARGUMENT,
              "a bank of the wrong size is refused");
        CHECK(cft_program_run_bank(pext, NULL, 8, a4, NULL, NULL, dep,
                                   NULL, 1, NULL, NULL) ==
              CFT_ERR_INVALID_ARGUMENT,
              "a NULL bank of non-zero length is refused");
        CHECK(cft_program_run(pext, a4, NULL, NULL, dep, NULL, 1,
                              NULL, NULL) == CFT_ERR_INVALID_ARGUMENT,
              "a BANK_EXT program refuses cft_program_run");
        CHECK(cft_program_run_bank(prog, bank, 8, a4, NULL, NULL, dep,
                                   NULL, 1, NULL, NULL) ==
              CFT_ERR_INVALID_ARGUMENT,
              "a program carrying its own constants refuses a bank");

        /* -- cft_run_args and cft_program_run_ex (ABI 0.10) --
         *
         * The struct is an INPUT, so its size handshake runs the other
         * way from cft_caps' and cft_program_info's: a size this
         * library does not recognise is REFUSED in both directions
         * rather than truncated, because truncating an input means
         * silently ignoring a field a newer caller set - and a run
         * that dropped a scratch buffer without saying so is exactly
         * what every byte-count rule here exists to prevent. */
        {
            cft_run_args A;
            uint8_t sblk[8];
            memset(sblk, 0, sizeof sblk);

            memset(&A, 0, sizeof A);
            A.struct_size = sizeof A;
            A.a = a4; A.n = 1; A.deposits = dep;
            put32(dep, 0);
            st = cft_program_run_ex(prog, &A);
            CHECK(st == CFT_OK && get32(dep) == 0x40880000u,
                  "run_ex is cft_program_run with a struct: %s 0x%08x",
                  cft_strerror(st), get32(dep));

            CHECK(cft_program_run_ex(NULL, &A) ==
                  CFT_ERR_INVALID_ARGUMENT &&
                  cft_program_run_ex(prog, NULL) ==
                  CFT_ERR_INVALID_ARGUMENT,
                  "run_ex refuses NULLs");

            A.struct_size = 0;
            CHECK(cft_program_run_ex(prog, &A) == CFT_ERR_INVALID_ARGUMENT,
                  "a struct_size of zero is refused");
            A.struct_size = sizeof A - 1u;
            CHECK(cft_program_run_ex(prog, &A) == CFT_ERR_INVALID_ARGUMENT,
                  "a struct_size one byte short is refused");
            A.struct_size = sizeof A + 8u;
            CHECK(cft_program_run_ex(prog, &A) == CFT_ERR_INVALID_ARGUMENT,
                  "a struct_size from a NEWER caller is refused, not "
                  "truncated");

            /* bus_out is cleared before anything else, as the two
             * older calls clear theirs. */
            A.struct_size = sizeof A;
            bus = 0xdeadbeefu;
            A.bus_out = &bus;
            A.a = NULL;
            CHECK(cft_program_run_ex(prog, &A) == CFT_ERR_INVALID_ARGUMENT &&
                  bus == 0,
                  "run_ex refuses a NULL `a` and clears bus_out first");
            A.a = a4;
            A.bus_out = NULL;

            /* The bank and the scratch, each held to the program. */
            A.bank = bank; A.bank_bytes = 8;
            CHECK(cft_program_run_ex(prog, &A) == CFT_ERR_INVALID_ARGUMENT,
                  "run_ex: a program carrying its own constants refuses a "
                  "bank");
            A.bank = NULL; A.bank_bytes = 0;
            A.scratch_in = sblk; A.scratch_in_bytes = 4;
            CHECK(cft_program_run_ex(prog, &A) == CFT_ERR_INVALID_ARGUMENT,
                  "run_ex: a program declaring no scratch I/O refuses a "
                  "scratch-in block");
            A.scratch_in = NULL; A.scratch_in_bytes = 0;
            A.scratch_out = sblk; A.scratch_out_bytes = 4;
            CHECK(cft_program_run_ex(prog, &A) == CFT_ERR_INVALID_ARGUMENT,
                  "run_ex: and a scratch-out block");
            A.scratch_out = NULL; A.scratch_out_bytes = 0;

            /* A BANK_EXT program through run_ex, which is what
             * run_bank now is underneath. */
            memset(&A, 0, sizeof A);
            A.struct_size = sizeof A;
            A.a = a4; A.n = 1; A.deposits = dep;
            A.bank = bank; A.bank_bytes = 8;
            put32(dep, 0);
            st = cft_program_run_ex(pext, &A);
            CHECK(st == CFT_OK && get32(dep) == 0x40880000u,
                  "run_ex takes a BANK_EXT program's bank: %s 0x%08x",
                  cft_strerror(st), get32(dep));
        }

        /* -- the scratch block, and the three fields info gained -- */
        {
            uint8_t sio[64], sin_buf[8], sout_buf[8];
            cft_program *ps = NULL;
            cft_run_args A;
            uint64_t sins[4];
            size_t sbytes, j;

            /* STL r0 -> slot 0; LDL r4 <- slot 1; deposit r4; halt.
             * Two slots in, one out, so every field below is a
             * different number and a transposition shows. */
            sins[0] = 6ull | (0ull << 12) | (1ull << 31) | (0ull << 32);
            sins[1] = 7ull | (4ull << 8)  | (1ull << 31) | (1ull << 32);
            sins[2] = 3ull | (4ull << 12) | (1ull << 31);
            sins[3] = 0ull | (1ull << 31);
            memset(sio, 0, sizeof sio);
            put32(sio + 0, 0x50544643u);
            put32(sio + 4, 1);
            put32(sio + 8, 4);
            put32(sio + 12, 0);
            put32(sio + 16, 1);
            put32(sio + 20, (uint32_t)CFT_FP32);
            put32(sio + 24, CFT_PROG_FLAG_SCRATCH_IO);
            put32(sio + 28, 2u | (1u << 16));      /* 2 in, 1 out */
            for (j = 0; j < 4; j++)
                put64(sio + 32 + j * 8, sins[j]);
            sbytes = 32 + 4 * 8;

            st = cft_program_load(dev, sio, sbytes, &ps);
            CHECK(st == CFT_OK && ps != NULL,
                  "a SCRATCH_IO image loads: %s (%s)", cft_strerror(st),
                  cft_last_error());
            if (ps) {
                memset(&info, 0, sizeof info);
                info.struct_size = sizeof info;
                st = cft_program_get_info(ps, &info);
                CHECK(st == CFT_OK && info.n_scratch_in == 2 &&
                      info.n_scratch_out == 1 && info.scratch_used == 2,
                      "info carries 2/1 scratch slots and 2 used, not "
                      "%lu/%lu and %lu",
                      (unsigned long)info.n_scratch_in,
                      (unsigned long)info.n_scratch_out,
                      (unsigned long)info.scratch_used);

                CHECK(cft_program_run(ps, a4, NULL, NULL, dep, NULL, 1,
                                      NULL, NULL) ==
                      CFT_ERR_INVALID_ARGUMENT,
                      "a SCRATCH_IO program refuses cft_program_run");
                CHECK(cft_program_run_bank(ps, NULL, 0, a4, NULL, NULL, dep,
                                           NULL, 1, NULL, NULL) ==
                      CFT_ERR_INVALID_ARGUMENT,
                      "a SCRATCH_IO program refuses cft_program_run_bank");

                put32(sin_buf + 0, 0x40000000u);   /* slot 0 = 2.0 */
                put32(sin_buf + 4, 0x40400000u);   /* slot 1 = 3.0 */
                put32(sout_buf, 0xdeadbeefu);
                put32(dep, 0);
                memset(&A, 0, sizeof A);
                A.struct_size       = sizeof A;
                A.a                 = a4;
                A.n                 = 1;
                A.deposits          = dep;
                A.scratch_in        = sin_buf;
                A.scratch_in_bytes  = 8;
                A.scratch_out       = sout_buf;
                A.scratch_out_bytes = 4;
                st = cft_program_run_ex(ps, &A);
                CHECK(st == CFT_OK && get32(dep) == 0x40400000u &&
                      get32(sout_buf) == 0x40000000u,
                      "the block goes in and comes back: %s dep 0x%08x "
                      "out 0x%08x", cft_strerror(st), get32(dep),
                      get32(sout_buf));

                A.scratch_in_bytes = 4;
                CHECK(cft_program_run_ex(ps, &A) ==
                      CFT_ERR_INVALID_ARGUMENT,
                      "a scratch-in block of the wrong size is refused");
                A.scratch_in_bytes = 8;
                A.scratch_out_bytes = 8;
                CHECK(cft_program_run_ex(ps, &A) ==
                      CFT_ERR_INVALID_ARGUMENT,
                      "a scratch-out block of the wrong size is refused");
                A.scratch_out_bytes = 4;
                A.scratch_in = NULL;
                CHECK(cft_program_run_ex(ps, &A) ==
                      CFT_ERR_INVALID_ARGUMENT,
                      "a NULL scratch-in block of non-zero length is "
                      "refused");
                cft_program_free(ps);
            }
        }

        /* -- the digest -- */
        CHECK(cft_program_digest(NULL, NULL, 0, dig) ==
              CFT_ERR_INVALID_ARGUMENT &&
              cft_program_digest(prog, NULL, 0, NULL) ==
              CFT_ERR_INVALID_ARGUMENT,
              "program_digest refuses NULLs");
        CHECK(cft_program_digest(prog, bank, 8, dig) ==
              CFT_ERR_INVALID_ARGUMENT,
              "program_digest holds a bank to the same rule the run does");
        CHECK(cft_program_digest(pext, NULL, 0, dig) ==
              CFT_ERR_INVALID_ARGUMENT,
              "a BANK_EXT program has no digest without its bank");
        st = cft_program_digest(prog, NULL, 0, dig);
        CHECK(st == CFT_OK && cft_sha256(img, bytes, dig2) == CFT_OK &&
              memcmp(dig, dig2, 32) == 0,
              "a program with no bank digests to the hash of its image");
        st = cft_program_digest(pext, bank, 8, dig);
        CHECK(st == CFT_OK && cft_sha256(ext, ext_bytes, dig2) == CFT_OK &&
              memcmp(dig, dig2, 32) != 0,
              "image and bank do not digest to the image alone");

        /* -- ABI 0.14's fields on a program run (docs/ROUND2.md) --
         *
         * The SHAPE rules are the lead's and are argument errors with
         * a sentence naming the field; they were true when the fields
         * were only declared and are true now that P1 and P3 have
         * built them. What has changed is the other half: a
         * well-formed table or mask no longer answers
         * CFT_ERR_UNSUPPORTED naming its parcel, it RUNS. The dense
         * run beside them still runs, which is what makes the two
         * features additive rather than a regression. */
        {
            cft_run_args R;
            uint32_t ix[1], fl2 = 0;
            uint8_t mask1[1] = { 0x01u };
            uint8_t dep2[4];
            ix[0] = 0;
            memset(&R, 0, sizeof R);
            R.struct_size = sizeof R;
            R.a = a4; R.n = 1; R.deposits = dep2; R.flags_out = &fl2;
            st = cft_program_run_ex(prog, &R);
            CHECK(st == CFT_OK, "a dense run beside the 0.14 fields: %s (%s)",
                  cft_strerror(st), cft_last_error());
            /* The arguments that bound every byte the run reads are
             * checked BEFORE any table or mask is read: an n this
             * library cannot size, beside a table pointer and then a
             * mask pointer that would fault if dereferenced. V2 found
             * this shape in cft_run_ex and V3 read its twin here
             * (2026-09-15); with the guard behind the table walk, the
             * first case is a read of address 16 for n entries. */
            {
                cft_run_args H;
                memcpy(&H, &R, sizeof H);
                /* above the bound for any format and any deposit count:
                 * n elements of the smallest format would not fit */
                H.n = ((size_t)-1) / 2;
                H.idx_a = (const uint32_t *)16;
                H.idx_a_src = 0xFFFFFFFEu;
                st = cft_program_run_ex(prog, &H);
                CHECK(st == CFT_ERR_INVALID_ARGUMENT,
                      "an n this library cannot size is refused before its "
                      "table is read: %s (%s)",
                      cft_strerror(st), cft_last_error());
                CHECK(strstr(cft_last_error(), "than this library can size") != NULL,
                      "...and the refusal says why: '%s'", cft_last_error());
                H.idx_a = NULL; H.idx_a_src = 0;
                H.lane_mask = (const uint8_t *)16;
                H.lane_mask_bytes = (H.n + 7) / 8;
                st = cft_program_run_ex(prog, &H);
                CHECK(st == CFT_ERR_INVALID_ARGUMENT,
                      "...and before its mask is read: %s (%s)",
                      cft_strerror(st), cft_last_error());
            }
            /* P1 has landed, so a well-formed table RUNS, and the one
             * that reads as +0 runs too. What is refused here is an
             * index at or past the source, by name and by value - the
             * bound being the length the caller declared and not the
             * length of anything this library can see. */
            memcpy(dep2, "\xAA\xAA\xAA\xAA", 4);
            R.idx_a = ix; R.idx_a_src = 1;
            st = cft_program_run_ex(prog, &R);
            CHECK(st == CFT_OK,
                  "an identity table runs: %s (%s)",
                  cft_strerror(st), cft_last_error());
            {
                uint8_t dense_dep[4];
                memcpy(dense_dep, dep2, 4);
                ix[0] = CFT_IDX_NONE;
                st = cft_program_run_ex(prog, &R);
                CHECK(st == CFT_OK, "CFT_IDX_NONE runs: %s (%s)",
                      cft_strerror(st), cft_last_error());
                CHECK(memcmp(dense_dep, dep2, 4) != 0,
                      "the sentinel read +0 where the identity table read "
                      "the caller's element, so these must differ");
                ix[0] = 1;                 /* idx_a_src is 1: 1 is past it */
                st = cft_program_run_ex(prog, &R);
                CHECK(st == CFT_ERR_INVALID_ARGUMENT &&
                      strstr(cft_last_error(), "idx_a[0] = 1") &&
                      strstr(cft_last_error(), "at or past"),
                      "an index at the source's length is refused by name "
                      "and by value: %s (%s)",
                      cft_strerror(st), cft_last_error());
                ix[0] = 0;
            }
            R.idx_a_src = 0;
            st = cft_program_run_ex(prog, &R);
            CHECK(st == CFT_ERR_INVALID_ARGUMENT &&
                  strstr(cft_last_error(), "idx_a_src"),
                  "a table with a source length of zero is a shape error: "
                  "%s (%s)", cft_strerror(st), cft_last_error());
            R.idx_a = NULL; R.idx_a_src = 1;
            st = cft_program_run_ex(prog, &R);
            CHECK(st == CFT_ERR_INVALID_ARGUMENT,
                  "a source length beside no table is a shape error: %s",
                  cft_strerror(st));
            R.idx_a_src = 0; R.idx_b = ix; R.idx_b_src = 1;   /* b is NULL */
            st = cft_program_run_ex(prog, &R);
            CHECK(st == CFT_ERR_INVALID_ARGUMENT &&
                  strstr(cft_last_error(), "NULL"),
                  "a table on a NULL stream is a shape error: %s (%s)",
                  cft_strerror(st), cft_last_error());
            R.idx_b = NULL; R.idx_b_src = 0;
            R.idx_scratch_in = ix; R.idx_scratch_src = 1;
            st = cft_program_run_ex(prog, &R);
            CHECK(st == CFT_ERR_INVALID_ARGUMENT &&
                  strstr(cft_last_error(), "no scratch input"),
                  "an indexed scratch block on a program without one is a "
                  "shape error: %s (%s)", cft_strerror(st), cft_last_error());
            R.idx_scratch_in = NULL; R.idx_scratch_src = 0;
            R.lane_mask = mask1; R.lane_mask_bytes = 2;
            st = cft_program_run_ex(prog, &R);
            CHECK(st == CFT_ERR_INVALID_ARGUMENT &&
                  strstr(cft_last_error(), "lane_mask_bytes"),
                  "a mask of the wrong length is a shape error: %s (%s)",
                  cft_strerror(st), cft_last_error());
            /* P3 has landed too, so a well-formed mask RUNS - and the
             * bytes of a lane it clears are the caller's, which is the
             * one thing about R17 that can be seen from here: the
             * deposit slot keeps the pattern written into it rather
             * than the +0 an untouched slot of a lane the run OWNS
             * would read. */
            R.lane_mask_bytes = 1;
            st = cft_program_run_ex(prog, &R);
            CHECK(st == CFT_OK, "an all-ones lane mask runs: %s (%s)",
                  cft_strerror(st), cft_last_error());
            memcpy(dep2, "\xAA\xAA\xAA\xAA", 4);
            mask1[0] = 0x00u;              /* the run's one lane, masked */
            st = cft_program_run_ex(prog, &R);
            CHECK(st == CFT_OK, "a mask with every lane clear runs: %s (%s)",
                  cft_strerror(st), cft_last_error());
            CHECK(memcmp(dep2, "\xAA\xAA\xAA\xAA", 4) == 0 && fl2 == 0,
                  "a masked lane's deposit slot was written, or its run "
                  "raised a flag");
            mask1[0] = 0x01u;
            R.lane_mask = NULL; R.lane_mask_bytes = 0;
            st = cft_program_run_ex(prog, &R);
            CHECK(st == CFT_OK, "and the dense run still runs after them: %s",
                  cft_strerror(st));
        }

        cft_program_free(prog);
        cft_program_free(pext);
        cft_program_free(NULL);       /* must be safe */
    }

    /* --- revision 8's flag control and per-lane flags (ABI 0.17) -----
     *
     * docs/SEQUENCER.md R23 and R24, on the software handle, which
     * carries both and must say so. Four lanes of one program:
     *
     *   quiet; fma r3, r0, r1, r0; endquiet; raise r2; halt
     *
     * The FMA is inexact in every lane (4/3 squared plus 4/3) and the
     * region silences it. r2 is stream c, the lane's flag word: nothing,
     * divide-by-zero, invalid with the mark (0x81), and bits [6:5] alone
     * (0x60), which a raise does not read. So the flags are 0x03, STATUS
     * is CFT_STATUS_MARKED, and the bytes are 00 02 81 00 - whose OR
     * gives back both words, R23's identities. Without the region every
     * byte gains inexact; under a mask the masked lane's byte is the
     * caller's; and the field's shape and the old struct size are
     * refused by name. */
    {
        static const uint64_t cword[4] = { 0x00u, 0x02u, 0x81u, 0x60u };
        uint64_t ins[5];
        uint8_t img[32 + 5 * 8];
        uint8_t a[4 * 8], c[4 * 8], lf[4];
        uint8_t mask[1];
        uint32_t fl = 0, bus = 0;
        cft_program *pq = NULL;
        cft_caps qc;
        cft_run_args R;
        size_t len;
        int k, or8;

        memset(&qc, 0, sizeof qc);
        qc.struct_size = sizeof qc;
        st = cft_get_caps(dev, &qc);
        CHECK(st == CFT_OK &&
              (qc.seq_features & CFT_SEQ_FEAT_LANE_FLAGS) &&
              (qc.seq_features & CFT_SEQ_FEAT_FLAG_CONTROL),
              "the software handle publishes CFT_SEQ_FEAT_LANE_FLAGS and "
              "CFT_SEQ_FEAT_FLAG_CONTROL (seq_features 0x%lx)",
              (unsigned long)qc.seq_features);
        for (k = 0; k < 4; k++) {
            put64(a + 8 * k, 0x3FF5555555555555ull);       /* 4/3 */
            put64(c + 8 * k, cword[k]);
        }
        ins[0] = LD_CTL(12, 0, 0, 0, 0, 0, 0, 0);               /* quiet */
        ins[1] = LD_ALU(0, 3, 0, 1, 0, 0, 0, 0);       /* fma r3,r0,r1,r0 */
        ins[2] = LD_CTL(13, 0, 0, 0, 0, 0, 0, 0);            /* endquiet */
        ins[3] = LD_CTL(14, 0, 2, 0, 0, 0, 0, 0);            /* raise r2 */
        ins[4] = LD_HALT;
        len = ld_image(img, 0x50544643u, 1u, 1u, 8, 0u, 0u, 0u, 0u, ins, 5);
        st = cft_program_load(dev, img, len, &pq);
        CHECK(st == CFT_OK, "a quiet region and a raise load on the "
              "software handle: %s (%s)", cft_strerror(st),
              cft_last_error());
        if (pq) {
            memset(&R, 0, sizeof R);
            R.struct_size = sizeof R;
            R.a = a; R.b = a; R.c = c; R.n = 4;
            R.flags_out = &fl; R.bus_out = &bus;
            R.lane_flags = lf; R.lane_flags_bytes = 4;
            memset(lf, 0xEE, sizeof lf);
            st = cft_program_run_ex(pq, &R);
            CHECK(st == CFT_OK && fl == 0x03u && bus == CFT_STATUS_MARKED,
                  "the region silences the FMA and the raise raises "
                  "exactly the words: %s flags 0x%02lx STATUS 0x%02lx",
                  cft_strerror(st), (unsigned long)fl, (unsigned long)bus);
            CHECK(lf[0] == 0x00u && lf[1] == 0x02u &&
                  lf[2] == (uint8_t)(0x01u | CFT_LANE_MARKED) &&
                  lf[3] == 0x00u,
                  "each lane's byte is its own: %02x %02x %02x %02x",
                  lf[0], lf[1], lf[2], lf[3]);
            or8 = lf[0] | lf[1] | lf[2] | lf[3];
            CHECK((uint32_t)(or8 & 0x1F) == fl &&
                  (uint32_t)((or8 >> 1) & 0x70) == (bus & 0x70u),
                  "the bytes' OR gives back the flags and STATUS[6:4] "
                  "(R23's identities): OR 0x%02x", or8);

            /* the lane mask: lane 2 masked keeps the caller's byte and
             * raises nothing - so neither its invalid nor its mark */
            mask[0] = 0x0Bu;
            R.lane_mask = mask; R.lane_mask_bytes = 1;
            memset(lf, 0xEE, sizeof lf);
            st = cft_program_run_ex(pq, &R);
            CHECK(st == CFT_OK && lf[2] == 0xEEu && lf[1] == 0x02u &&
                  fl == 0x02u && bus == 0u,
                  "a masked lane's byte is the caller's and it raises and "
                  "marks nothing: %s %02x %02x flags 0x%02lx STATUS 0x%02lx",
                  cft_strerror(st), lf[1], lf[2], (unsigned long)fl,
                  (unsigned long)bus);
            R.lane_mask = NULL; R.lane_mask_bytes = 0;

            /* the field's shape, by name, before the run */
            R.lane_flags = NULL; R.lane_flags_bytes = 4;
            st = cft_program_run_ex(pq, &R);
            CHECK(st == CFT_ERR_INVALID_ARGUMENT &&
                  strstr(cft_last_error(), "with no lane_flags"),
                  "a count with no block is refused by name: %s (%s)",
                  cft_strerror(st), cft_last_error());
            R.lane_flags = lf; R.lane_flags_bytes = 1;   /* a mask's size */
            st = cft_program_run_ex(pq, &R);
            CHECK(st == CFT_ERR_INVALID_ARGUMENT &&
                  strstr(cft_last_error(), "a byte a lane"),
                  "a block sized as a mask is refused by name: %s (%s)",
                  cft_strerror(st), cft_last_error());
            R.lane_flags_bytes = 4;
            /* ABI 0.16's struct ends before the two fields: refused, as an
             * input struct of another size always is */
            R.struct_size = offsetof(cft_run_args, lane_flags);
            st = cft_program_run_ex(pq, &R);
            CHECK(st == CFT_ERR_INVALID_ARGUMENT &&
                  strstr(cft_last_error(), "missing a field"),
                  "a 0.16-sized cft_run_args is refused at 0.17: %s (%s)",
                  cft_strerror(st), cft_last_error());
            R.struct_size = sizeof R;
            cft_program_free(pq);
            pq = NULL;
        }

        /* the control: the same program without its region raises the
         * FMA's inexact in every lane */
        ins[0] = LD_ALU(0, 3, 0, 1, 0, 0, 0, 0);
        ins[1] = LD_CTL(14, 0, 2, 0, 0, 0, 0, 0);
        ins[2] = LD_HALT;
        len = ld_image(img, 0x50544643u, 1u, 1u, 8, 0u, 0u, 0u, 0u, ins, 3);
        st = cft_program_load(dev, img, len, &pq);
        if (st == CFT_OK && pq) {
            memset(&R, 0, sizeof R);
            R.struct_size = sizeof R;
            R.a = a; R.b = a; R.c = c; R.n = 4;
            R.flags_out = &fl; R.bus_out = &bus;
            R.lane_flags = lf; R.lane_flags_bytes = 4;
            st = cft_program_run_ex(pq, &R);
            CHECK(st == CFT_OK && fl == 0x13u &&
                  lf[0] == 0x10u && lf[3] == 0x10u,
                  "without the region the FMA's inexact stands in every "
                  "lane: flags 0x%02lx, bytes %02x .. %02x",
                  (unsigned long)fl, lf[0], lf[3]);
            cft_program_free(pq);
        } else {
            CHECK(0, "the control program loads: %s", cft_strerror(st));
        }
        printf("  revision 8 (ABI 0.17): a quiet region silences an FMA, a "
               "raise ORs its word and marks, each lane's byte is its own, "
               "a masked lane's is the caller's, and the field's shape and "
               "the 0.16 struct are refused by name\n");
    }

    /* --- SHA-256, against the vectors that define it ---------------
     *
     * FIPS 180-4's own two worked examples, copied in the base the
     * standard states them in - which is the rule this repository
     * applies to every constant: derive it, or copy it in its
     * specified base, never retype it from memory. The library's own
     * round constants ARE derived (host/src/sha256.c computes them
     * from the cube roots of the first primes), so these two lines are
     * what proves the derivation landed on SHA-256 and not on
     * something adjacent to it. The second example is 56 bytes, which
     * is the length that forces a second block. */
    {
        static const uint8_t abc[32] = {
            0xba,0x78,0x16,0xbf, 0x8f,0x01,0xcf,0xea,
            0x41,0x41,0x40,0xde, 0x5d,0xae,0x22,0x23,
            0xb0,0x03,0x61,0xa3, 0x96,0x17,0x7a,0x9c,
            0xb4,0x10,0xff,0x61, 0xf2,0x00,0x15,0xad };
        static const uint8_t two_block[32] = {
            0x24,0x8d,0x6a,0x61, 0xd2,0x06,0x38,0xb8,
            0xe5,0xc0,0x26,0x93, 0x0c,0x3e,0x60,0x39,
            0xa3,0x3c,0xe4,0x59, 0x64,0xff,0x21,0x67,
            0xf6,0xec,0xed,0xd4, 0x19,0xdb,0x06,0xc1 };
        static const char *msg2 =
            "abcdbcdecdefdefgefghfghighijhijkijkljklmklmnlmnomnopnopq";
        uint8_t h[32];

        CHECK(cft_sha256("abc", 3, h) == CFT_OK &&
              memcmp(h, abc, 32) == 0, "sha256(\"abc\") is FIPS 180-4's");
        CHECK(cft_sha256(msg2, strlen(msg2), h) == CFT_OK &&
              memcmp(h, two_block, 32) == 0,
              "sha256 of FIPS 180-4's two-block example");
        CHECK(cft_sha256("abc", 3, NULL) == CFT_ERR_INVALID_ARGUMENT &&
              cft_sha256(NULL, 3, h) == CFT_ERR_INVALID_ARGUMENT,
              "cft_sha256 refuses NULLs");
        CHECK(cft_sha256(NULL, 0, h) == CFT_OK,
              "the empty message has a hash");
    }

    /* --- buffers, the contract (ABI 0.11) --------------------------
     *
     * On this backend cft_alloc is a host allocation and the two sync
     * calls do nothing - and that is precisely what has to be checked,
     * because it is the property that keeps code written this way
     * portable. Every check below is a claim about the API's SHAPE,
     * true on every backend; whether a buffer is actually device
     * resident is cft_caps.buffers_resident's answer and is nobody's
     * business here.
     *
     * device-test's -b leg runs the whole elementwise matrix and the
     * reductions through these calls against a device, which is where
     * "the same bits either way" is proven. This is the argument
     * contract only. */
    CHECK(cft_alloc(NULL, 4096, &buf) == CFT_ERR_INVALID_ARGUMENT,
          "cft_alloc refuses a NULL device");
    CHECK(cft_alloc(dev, 4096, NULL) == CFT_ERR_INVALID_ARGUMENT,
          "cft_alloc refuses a NULL out");
    CHECK(cft_alloc(dev, 0, &buf) == CFT_ERR_INVALID_ARGUMENT,
          "a zero-byte buffer is refused");
    CHECK(cft_buffer_to_device(NULL) == CFT_ERR_INVALID_ARGUMENT &&
          cft_buffer_from_device(NULL) == CFT_ERR_INVALID_ARGUMENT,
          "the sync calls refuse a NULL buffer");
    CHECK(cft_buffer_data(NULL) == NULL, "cft_buffer_data(NULL) is NULL");

    st = cft_alloc(dev, 4096, &buf);
    CHECK(st == CFT_OK && buf != NULL, "cft_alloc: %s", cft_strerror(st));
    if (buf) {
        uint8_t *p = (uint8_t *)cft_buffer_data(buf);
        cft_buffer_info bi;

        CHECK(p != NULL, "buffer data pointer");
        CHECK(cft_buffer_data(buf) == p,
              "cft_buffer_data answers the same pointer every time");
        CHECK(cft_buffer_to_device(buf) == CFT_OK, "to_device");
        CHECK(cft_buffer_from_device(buf) == CFT_OK, "from_device");
        /* Both are safe to call again, in either order and any number
         * of times: a caller that syncs defensively must not be
         * punished for it, and one that never had a run to read back
         * must not be told it did. */
        CHECK(cft_buffer_from_device(buf) == CFT_OK &&
              cft_buffer_to_device(buf) == CFT_OK &&
              cft_buffer_to_device(buf) == CFT_OK,
              "the sync calls are idempotent and order-free");

        /* -- cft_buffer_get_info and its struct_size handshake -- */
        CHECK(cft_buffer_get_info(NULL, &bi) == CFT_ERR_INVALID_ARGUMENT &&
              cft_buffer_get_info(buf, NULL) == CFT_ERR_INVALID_ARGUMENT,
              "buffer_get_info refuses NULLs");
        memset(&bi, 0, sizeof bi);
        bi.struct_size = 0;
        CHECK(cft_buffer_get_info(buf, &bi) == CFT_ERR_INVALID_ARGUMENT,
              "a struct_size below one field is refused");
        memset(&bi, 0xa5, sizeof bi);
        bi.struct_size = sizeof bi;
        st = cft_buffer_get_info(buf, &bi);
        CHECK(st == CFT_OK && bi.struct_size == sizeof bi &&
              bi.bytes == 4096,
              "buffer_get_info reports the size it was asked for");
        /* This backend keeps no device copies, so it must not claim to:
         * every counter zero, nothing device-authoritative, and a
         * reason a reader can act on rather than an empty string. */
        CHECK(bi.resident == 0 && bi.device_authority == 0 &&
              bi.resident_binds == 0 && bi.staged_binds == 0 &&
              bi.staged_why[0] != '\0',
              "a backend with no device memory says so and counts nothing");
        CHECK(caps.buffers_resident == 0,
              "the software backend does not report resident buffers");
        /* The older caller: a short struct_size is filled to its own
         * length and nothing past it is touched. */
        {
            uint8_t raw[sizeof(cft_buffer_info)];
            cft_buffer_info *shorty = (cft_buffer_info *)(void *)raw;
            memset(raw, 0x5a, sizeof raw);
            shorty->struct_size = sizeof(size_t) * 2;
            st = cft_buffer_get_info(buf, shorty);
            CHECK(st == CFT_OK &&
                  shorty->struct_size == sizeof(size_t) * 2 &&
                  shorty->bytes == 4096 &&
                  raw[sizeof(size_t) * 2] == 0x5a,
                  "a short struct_size is filled to its own length only");
        }

        if (p) {
            /* Buffer memory is ordinary memory here, so it feeds
             * cft_run directly - which is the property that keeps code
             * written this way portable to the device backend. */
            put32(p, 0x3f800000u);
            put32(p + 8, 0x40000000u);
            st = cft_run(dev, CFT_ADD, CFT_FP32, CFT_RNE, p, NULL, p + 8,
                         p + 16, 1, NULL, NULL);
            CHECK(st == CFT_OK && get32(p + 16) == 0x40400000u,
                  "run over a device buffer");
        }
        cft_buffer_free(buf);
        buf = NULL;
    }
    cft_buffer_free(NULL);          /* must be safe */

    /* --- buffers against host pointers, bit for bit and flag for flag
     *
     * The claim the whole mechanism rests on: the same call over the
     * same bytes gives the same answer whether the operands came from
     * cft_alloc or from malloc. Here that is true by construction -
     * this backend has one kind of memory - so what it proves is the
     * HARNESS: an interior pointer, an aliased output, a reduction and
     * a program run all reach the library the same way through both,
     * and device-test's -b leg runs the identical shape where the two
     * really are different memory. */
    {
        enum { NBUF = 96 };
        cft_buffer *ba = NULL, *bb = NULL, *bc = NULL, *bd = NULL;
        static uint8_t ha[NBUF * 8], hb[NBUF * 8], hc[NBUF * 8];
        static uint8_t hd[NBUF * 8], hd2[NBUF * 8];
        uint32_t fh = 0, fb = 0;
        uint32_t rs2 = 0xb0ffe511u;
        size_t k;

        for (k = 0; k < sizeof ha; k++) {
            rs2 ^= rs2 << 13; rs2 ^= rs2 >> 17; rs2 ^= rs2 << 5;
            ha[k] = (uint8_t)rs2;
            rs2 ^= rs2 << 13; rs2 ^= rs2 >> 17; rs2 ^= rs2 << 5;
            hb[k] = (uint8_t)rs2;
            rs2 ^= rs2 << 13; rs2 ^= rs2 >> 17; rs2 ^= rs2 << 5;
            hc[k] = (uint8_t)rs2;
        }

        if (cft_alloc(dev, sizeof ha, &ba) == CFT_OK &&
            cft_alloc(dev, sizeof hb, &bb) == CFT_OK &&
            cft_alloc(dev, sizeof hc, &bc) == CFT_OK &&
            cft_alloc(dev, sizeof hd, &bd) == CFT_OK) {
            uint8_t *pa = (uint8_t *)cft_buffer_data(ba);
            uint8_t *pb = (uint8_t *)cft_buffer_data(bb);
            uint8_t *pc = (uint8_t *)cft_buffer_data(bc);
            uint8_t *pd = (uint8_t *)cft_buffer_data(bd);

            memcpy(pa, ha, sizeof ha);
            memcpy(pb, hb, sizeof hb);
            memcpy(pc, hc, sizeof hc);
            CHECK(cft_buffer_to_device(ba) == CFT_OK &&
                  cft_buffer_to_device(bb) == CFT_OK &&
                  cft_buffer_to_device(bc) == CFT_OK,
                  "publishing three buffers");

            /* fp64 fma over the whole array, both ways. */
            memset(hd, 0, sizeof hd);
            memset(pd, 0, sizeof hd);
            st = cft_run(dev, CFT_FMA, CFT_FP64, CFT_RNE, ha, hb, hc, hd,
                         NBUF, &fh, NULL);
            CHECK(st == CFT_OK, "host-pointer fma: %s", cft_strerror(st));
            st = cft_run(dev, CFT_FMA, CFT_FP64, CFT_RNE, pa, pb, pc, pd,
                         NBUF, &fb, NULL);
            CHECK(st == CFT_OK, "buffer fma: %s", cft_strerror(st));
            CHECK(cft_buffer_from_device(bd) == CFT_OK, "reading d back");
            CHECK(memcmp(hd, pd, sizeof hd) == 0 && fh == fb,
                  "buffers and host pointers give the same bits and flags");

            /* An INTERIOR pointer: a window at a byte offset inside
             * each buffer, which is the case a registry that only
             * recognised base addresses would silently stage. */
            memset(hd2, 0, sizeof hd2);
            st = cft_run(dev, CFT_MUL, CFT_FP64, CFT_RNE, ha + 64, hb + 64,
                         NULL, hd2 + 64, NBUF / 2, &fh, NULL);
            CHECK(st == CFT_OK, "host-pointer window: %s", cft_strerror(st));
            memset(pd, 0, sizeof hd);
            CHECK(cft_buffer_to_device(bd) == CFT_OK, "republishing d");
            st = cft_run(dev, CFT_MUL, CFT_FP64, CFT_RNE, pa + 64, pb + 64,
                         NULL, pd + 64, NBUF / 2, &fb, NULL);
            CHECK(st == CFT_OK, "buffer window: %s", cft_strerror(st));
            CHECK(cft_buffer_from_device(bd) == CFT_OK, "reading a window");
            CHECK(memcmp(hd2, pd, sizeof hd2) == 0 && fh == fb,
                  "a window inside a buffer computes the same bits");

            /* d aliasing a, which the contract allows because every
             * element is read before it is written. On a device the
             * two are different memory and the answer must still be
             * this one. */
            memcpy(hd, ha, sizeof ha);
            st = cft_run(dev, CFT_ABS, CFT_FP64, CFT_RNE, hd, NULL, NULL,
                         hd, NBUF, &fh, NULL);
            CHECK(st == CFT_OK, "host-pointer aliased abs");
            st = cft_run(dev, CFT_ABS, CFT_FP64, CFT_RNE, pa, NULL, NULL,
                         pa, NBUF, &fb, NULL);
            CHECK(st == CFT_OK, "buffer aliased abs");
            CHECK(cft_buffer_from_device(ba) == CFT_OK, "reading a back");
            CHECK(memcmp(hd, pa, sizeof hd) == 0 && fh == fb,
                  "an output aliasing its own input agrees");
            memcpy(pa, ha, sizeof ha);
            CHECK(cft_buffer_to_device(ba) == CFT_OK, "restoring a");

            /* A reduction reads the whole vector and writes one
             * element; the element goes to a host pointer here, which
             * is what cft_reduce's signature offers. */
            {
                uint8_t r1[8], r2[8];
                st = cft_reduce(dev, CFT_SUM, CFT_FP64, CFT_RNE, hb, NULL,
                                r1, NBUF, &fh, NULL);
                CHECK(st == CFT_OK, "host-pointer sum: %s",
                      cft_strerror(st));
                st = cft_reduce(dev, CFT_SUM, CFT_FP64, CFT_RNE, pb, NULL,
                                r2, NBUF, &fb, NULL);
                CHECK(st == CFT_OK, "buffer sum: %s", cft_strerror(st));
                CHECK(memcmp(r1, r2, 8) == 0 && fh == fb,
                      "a reduction over a buffer is the same sum");
            }

            /* Counting: nothing here is resident on this backend, so
             * every counter must still be zero after all of that. A
             * counter that moved would mean the software path had
             * grown a device concept. */
            {
                cft_buffer_info bi2;
                memset(&bi2, 0, sizeof bi2);
                bi2.struct_size = sizeof bi2;
                CHECK(cft_buffer_get_info(ba, &bi2) == CFT_OK &&
                      bi2.resident_binds == 0 && bi2.staged_binds == 0 &&
                      bi2.resident == 0,
                      "no bindings are counted where there is no device");
            }
        } else {
            CHECK(0, "allocating four buffers");
        }
        cft_buffer_free(ba);
        cft_buffer_free(bb);
        cft_buffer_free(bc);
        cft_buffer_free(bd);
    }

    /* --- a program run over buffers, and the closing order ---------
     *
     * cft_program_run_ex takes a, b, c and the deposit window, and all
     * four are recognised the same way cft_run's are. The image, the
     * bank and the counts are not: they are staged always, which is a
     * decision docs/HOSTAPI.md records and this only has to not
     * contradict.
     *
     * The second claim is the ordering one: closing the device before
     * freeing a buffer is allowed. A device backend releases the
     * buffer's device side there, and the buffer stays valid host
     * memory - which is the only order a garbage-collected binding can
     * promise. It needs its own device, because the check is that this
     * one is gone. */
    {
        cft_device *d2 = NULL;
        cft_buffer *pa = NULL, *pd = NULL;
        uint8_t img[64];
        uint64_t ins[3];
        size_t w, bytes;
        cft_program *prog = NULL;

        ins[0] = 0u | (4ull << 8) | (0ull << 12) | (0ull << 16) |
                 (1ull << 20) | (1ull << 28) | (1ull << 29);
        ins[1] = 3ull | (4ull << 12) | (1ull << 31);
        ins[2] = 0ull | (1ull << 31);
        memset(img, 0, sizeof img);
        put32(img + 0, 0x50544643u);
        put32(img + 4, 1);
        put32(img + 8, 3);
        put32(img + 12, 2);
        put32(img + 16, 1);
        put32(img + 20, (uint32_t)CFT_FP32);
        put32(img + 32, 0x3fc00000u);     /* k0 = 1.5  */
        put32(img + 36, 0x3fa00000u);     /* k1 = 1.25 */
        for (w = 0; w < 3; w++)
            put64(img + 40 + w * 8, ins[w]);
        bytes = 40 + 3 * 8;

        st = cft_open(NULL, 0, &d2);
        CHECK(st == CFT_OK && d2 != NULL, "a second software device");
        if (d2 && cft_program_load(d2, img, bytes, &prog) == CFT_OK &&
            cft_alloc(d2, 4 * 4, &pa) == CFT_OK &&
            cft_alloc(d2, 4 * 4, &pd) == CFT_OK) {
            uint8_t *ap = (uint8_t *)cft_buffer_data(pa);
            uint8_t *dp = (uint8_t *)cft_buffer_data(pd);
            uint8_t ha2[16], hd3[16];
            uint32_t cnt[4], cnt2[4];
            cft_run_args args;

            put32(ha2 + 0,  0x40000000u);        /* 2.0  */
            put32(ha2 + 4,  0x40400000u);        /* 3.0  */
            put32(ha2 + 8,  0x3f800000u);        /* 1.0  */
            put32(ha2 + 12, 0x00000000u);        /* +0   */
            memcpy(ap, ha2, sizeof ha2);
            CHECK(cft_buffer_to_device(pa) == CFT_OK, "publishing a");

            memset(&args, 0, sizeof args);
            args.struct_size = sizeof args;
            args.a = ha2;
            args.n = 4;
            args.deposits = hd3;
            args.counts = cnt;
            st = cft_program_run_ex(prog, &args);
            CHECK(st == CFT_OK, "host-pointer program run: %s",
                  cft_strerror(st));

            args.a = ap;
            args.deposits = dp;
            args.counts = cnt2;
            st = cft_program_run_ex(prog, &args);
            CHECK(st == CFT_OK, "buffer program run: %s", cft_strerror(st));
            CHECK(cft_buffer_from_device(pd) == CFT_OK, "reading deposits");
            CHECK(memcmp(hd3, dp, sizeof hd3) == 0 &&
                  memcmp(cnt, cnt2, sizeof cnt) == 0,
                  "a program over buffers deposits the same bytes");
        } else {
            CHECK(0, "a program and two buffers on the second device");
        }
        cft_program_free(prog);
        cft_close(d2);
        /* AFTER the close, deliberately. */
        CHECK(cft_buffer_data(pa) != NULL,
              "a buffer outlives its device as host memory");
        CHECK(cft_buffer_to_device(pa) == CFT_OK &&
              cft_buffer_from_device(pa) == CFT_OK,
              "the sync calls still answer after the device closed");
        {
            cft_buffer_info bi3;
            memset(&bi3, 0, sizeof bi3);
            bi3.struct_size = sizeof bi3;
            CHECK(cft_buffer_get_info(pa, &bi3) == CFT_OK &&
                  bi3.resident == 0 && bi3.staged_why[0] != '\0',
                  "and say what they are now");
        }
        cft_buffer_free(pa);
        cft_buffer_free(pd);
    }

    /* --- ABI 0.14's fields on an elementwise run (docs/ROUND2.md, P0) --
     *
     * The same discipline as the program run's: shape errors by name,
     * then a refusal naming the parcel, and the dense run beside them
     * unaffected. */
    {
        uint8_t a8[8 * 8], d8[8 * 8];
        uint32_t ix[8], fl = 0;
        cft_elem_args E;
        memset(a8, 0, sizeof a8);
        for (i = 0; i < 8; i++)
            ix[i] = (uint32_t)i;
        memset(&E, 0, sizeof E);
        E.struct_size = sizeof E;
        E.a = a8; E.b = a8; E.c = a8; E.d = d8; E.n = 8; E.flags_out = &fl;
        st = cft_run_ex(dev, CFT_ADD, CFT_FP64, CFT_RNE, &E);
        CHECK(st == CFT_OK, "cft_run_ex beside the 0.14 fields: %s",
              cft_strerror(st));
        /* P2: the refusal that stood here is gone and the run is real.
         * An identity table over a full-length source is the dense run
         * - the numbers are device_test's business and the contract
         * surface is this file's, so what is checked here is that the
         * call succeeds and that the three rules P2 added refuse what
         * they say they refuse. */
        E.idx_a = ix; E.idx_a_src = 8;
        st = cft_run_ex(dev, CFT_ADD, CFT_FP64, CFT_RNE, &E);
        CHECK(st == CFT_OK, "an indexed operand runs (P2): %s (%s)",
              cft_strerror(st), cft_last_error());
        /* A table on an operand the OPCODE does not read. CFT_ADD reads
         * a and c; b is steered to 1.0 and never fetched, so a table
         * for it would be built and never used. */
        E.idx_b = ix; E.idx_b_src = 8;
        st = cft_run_ex(dev, CFT_ADD, CFT_FP64, CFT_RNE, &E);
        CHECK(st == CFT_ERR_INVALID_ARGUMENT &&
              strstr(cft_last_error(), "does not read it"),
              "a table on an operand the opcode does not read: %s (%s)",
              cft_strerror(st), cft_last_error());
        E.idx_b = NULL; E.idx_b_src = 0;
        /* `d` overlapping an INDEXED source: a gathered lane reads any
         * element of its source, so a source the run is also writing is
         * read after write. Dense aliasing is still allowed and the
         * dense run at the end of this block is the proof. */
        E.d = a8;
        st = cft_run_ex(dev, CFT_ADD, CFT_FP64, CFT_RNE, &E);
        CHECK(st == CFT_ERR_INVALID_ARGUMENT &&
              strstr(cft_last_error(), "overlaps"),
              "d overlapping an indexed source: %s (%s)",
              cft_strerror(st), cft_last_error());
        E.d = d8;
        /* The bound, by name and by value, before the run. */
        ix[3] = 8;                          /* one past the last element */
        st = cft_run_ex(dev, CFT_ADD, CFT_FP64, CFT_RNE, &E);
        CHECK(st == CFT_ERR_INVALID_ARGUMENT &&
              strstr(cft_last_error(), "idx_a[3]"),
              "an index at the source's length: %s (%s)",
              cft_strerror(st), cft_last_error());
        ix[3] = CFT_IDX_NONE;               /* ...and the sentinel is not */
        st = cft_run_ex(dev, CFT_ADD, CFT_FP64, CFT_RNE, &E);
        CHECK(st == CFT_OK, "CFT_IDX_NONE is not an out-of-range index: "
              "%s (%s)", cft_strerror(st), cft_last_error());
        ix[3] = 3;
        /* An `n` the DENSE path refuses without touching a byte must be
         * refused before a single table entry is read (V2, 2026-09-15).
         * The table pointer here is a POISONED address that would fault
         * if anything dereferenced it, and the huge n is one
         * `n > SIZE_MAX / esz` rejects - so this case passes only if
         * every dense-path check runs first. Before the fix it walked
         * the table for n entries and segfaulted. */
        {
            const uint32_t *poison = (const uint32_t *)(uintptr_t)0x10;
            cft_elem_args H;
            memset(&H, 0, sizeof H);
            H.struct_size = sizeof H;
            H.a = a8; H.b = a8; H.c = a8; H.d = d8;
            H.n = (size_t)-1 / 4u;          /* n * esz cannot be sized */
            H.idx_a = poison; H.idx_a_src = 8;
            st = cft_run_ex(dev, CFT_ADD, CFT_FP64, CFT_RNE, &H);
            CHECK(st == CFT_ERR_INVALID_ARGUMENT,
                  "an n too large to size, with a table, is refused "
                  "without reading it: %s", cft_strerror(st));
            /* ...and the same for the NULL output, the other check the
             * dense path makes before it touches memory. */
            H.n = 8;
            H.d = NULL;
            st = cft_run_ex(dev, CFT_ADD, CFT_FP64, CFT_RNE, &H);
            CHECK(st == CFT_ERR_INVALID_ARGUMENT,
                  "a NULL d, with a table, is refused without reading "
                  "it: %s", cft_strerror(st));
            /* ...and a reduction opcode, which this call refuses
             * whatever its operands are. */
            H.d = d8;
            st = cft_run_ex(dev, CFT_SUM, CFT_FP64, CFT_RNE, &H);
            CHECK(st == CFT_ERR_INVALID_ARGUMENT,
                  "a reduction opcode, with a table, is refused without "
                  "reading it: %s", cft_strerror(st));
        }
        E.idx_a_src = 0;
        st = cft_run_ex(dev, CFT_ADD, CFT_FP64, CFT_RNE, &E);
        CHECK(st == CFT_ERR_INVALID_ARGUMENT,
              "a table with a source length of zero: %s", cft_strerror(st));
        E.idx_a_src = 8; E.scalar_mask = 1u;
        st = cft_run_ex(dev, CFT_ADD, CFT_FP64, CFT_RNE, &E);
        CHECK(st == CFT_ERR_INVALID_ARGUMENT &&
              strstr(cft_last_error(), "both scalar"),
              "scalar and indexed on one operand: %s (%s)",
              cft_strerror(st), cft_last_error());
        E.scalar_mask = 0; E.idx_a = NULL; E.idx_a_src = 0;
        E.idx_c = ix; E.idx_c_src = 8; E.c = NULL;
        st = cft_run_ex(dev, CFT_ADD, CFT_FP64, CFT_RNE, &E);
        CHECK(st == CFT_ERR_INVALID_ARGUMENT,
              "a table on a NULL operand: %s", cft_strerror(st));
        E.idx_c = NULL;                    /* idx_c_src still 8 */
        st = cft_run_ex(dev, CFT_ADD, CFT_FP64, CFT_RNE, &E);
        CHECK(st == CFT_ERR_INVALID_ARGUMENT,
              "a source length beside no table: %s", cft_strerror(st));
        E.idx_c_src = 0; E.c = a8;
        st = cft_run_ex(dev, CFT_ADD, CFT_FP64, CFT_RNE, &E);
        CHECK(st == CFT_OK, "and the dense run still runs: %s",
              cft_strerror(st));
    }

    /* --- cft_open_ex (ABI 0.16): a software handle at a tile's depth --
     *
     * The depth is one field of the caps the handle publishes, and
     * program.c reads every use of it from there (host/src/device.c), so
     * what is held here is that the field is the one asked for and that
     * every refusal is made before a handle exists, by status and by a
     * word of its sentence. device-test holds the executor at a depth:
     * its whole matrix runs at `--scratch-depth 2048`. */
    {
        static const uint32_t bad_depths[] = { 3u, 6u, 65536u, 0x80000000u };
        cft_open_args oa;
        cft_device *dx = NULL;
        cft_caps cx;
        size_t k;

        memset(&oa, 0, sizeof oa);
        oa.struct_size = sizeof oa;
        oa.scratch_depth = 2048u;
        st = cft_open_ex(&oa, &dx);
        CHECK(st == CFT_OK && dx != NULL, "cft_open_ex at 2,048: %s (%s)",
              cft_strerror(st), cft_last_error());
        if (dx) {
            memset(&cx, 0, sizeof cx);
            cx.struct_size = sizeof cx;
            CHECK(cft_get_caps(dx, &cx) == CFT_OK &&
                  cx.max_scratch == 2048u,
                  "a handle opened at 2,048 publishes 2,048 (%lu)",
                  (unsigned long)cx.max_scratch);
            cft_close(dx);
            dx = NULL;
        }
        oa.scratch_depth = 0;
        st = cft_open_ex(&oa, &dx);
        CHECK(st == CFT_OK && dx != NULL, "cft_open_ex at 0: %s (%s)",
              cft_strerror(st), cft_last_error());
        if (dx) {
            memset(&cx, 0, sizeof cx);
            cx.struct_size = sizeof cx;
            CHECK(cft_get_caps(dx, &cx) == CFT_OK && cx.max_scratch == 256u,
                  "scratch_depth 0 is the backend's own 256 (%lu)",
                  (unsigned long)cx.max_scratch);
            cft_close(dx);
            dx = NULL;
        }
        for (k = 0; k < sizeof bad_depths / sizeof bad_depths[0]; k++) {
            oa.scratch_depth = bad_depths[k];
            dx = (cft_device *)&oa;          /* must come back NULL */
            st = cft_open_ex(&oa, &dx);
            CHECK(st == CFT_ERR_INVALID_ARGUMENT && dx == NULL &&
                  strstr(cft_last_error(), "power of two") != NULL,
                  "scratch_depth %lu is refused as no power of two in "
                  "1..32768: %s (%s)", (unsigned long)bad_depths[k],
                  cft_strerror(st), cft_last_error());
        }
        oa.scratch_depth = 256u;
        oa.struct_size = sizeof oa - 1;
        dx = (cft_device *)&oa;
        st = cft_open_ex(&oa, &dx);
        CHECK(st == CFT_ERR_INVALID_ARGUMENT && dx == NULL &&
              strstr(cft_last_error(), "struct_size") != NULL,
              "a short cft_open_args is refused: %s (%s)",
              cft_strerror(st), cft_last_error());
        oa.struct_size = sizeof oa;
        oa.artifact = "no-such-image.xclbin";
        dx = (cft_device *)&oa;
        st = cft_open_ex(&oa, &dx);
        CHECK(st == CFT_ERR_UNSUPPORTED && dx == NULL &&
              strstr(cft_last_error(), "SOFTWARE") != NULL,
              "a depth with an xclbin is refused before it is opened: "
              "%s (%s)", cft_strerror(st), cft_last_error());
        oa.artifact = "cft://127.0.0.1:1";
        dx = (cft_device *)&oa;
        st = cft_open_ex(&oa, &dx);
        CHECK(st == CFT_ERR_UNSUPPORTED && dx == NULL &&
              strstr(cft_last_error(), "SOFTWARE") != NULL,
              "a depth with a cft:// artifact is refused before any "
              "connection: %s (%s)", cft_strerror(st), cft_last_error());
        oa.artifact = NULL;
        CHECK(cft_open_ex(NULL, &dx) == CFT_ERR_INVALID_ARGUMENT,
              "cft_open_ex with no args is refused");
        CHECK(cft_open_ex(&oa, NULL) == CFT_ERR_INVALID_ARGUMENT,
              "cft_open_ex with nowhere to put the handle is refused");
    }

    /* --- every refusal in the program-load path says why, and never
     *     another call's why (the fixes round's Q5, 2026-09-30) --------
     *
     * CLAUDE.md's discipline: what cannot be done is refused BY NAME, and
     * cft_last_error() carries the sentence behind a refusal
     * (host/src/backend.h). cft_program_load broke that twice, as P2 of
     * the revision-7 round found. Refusals in its own body (eight, the
     * NULL argument's among them), in seq_validate (sixteen) and in
     * seq_check_operands (nine) returned a status and no sentence; and it
     * never cleared the slot, so such a refusal printed an earlier call's
     * sentence - P2 measured a cft_run_ex index refusal explaining a load.
     *
     * Every one fires here, each on its own image, after a failing call
     * has planted a sentence (ld_expect), and each is held to three
     * things: its status, which is what it always was; a sentence that
     * names the cause - the instruction, the code or opcode, the field,
     * the value and its limit - in the meaning of the ProgramError the
     * golden model's seq.py raises for the same image; and not the
     * planted one. One refusal cannot fire on a software handle: the
     * library's own ceiling on max_deposits, which a handle that
     * publishes a cap of its own reaches second, refused by name there
     * (cft_seq_cap_refusal). seq_check.py holds it, through a remote
     * handle to a server that publishes none.
     *
     * Then the entry clear on its own. With every refusal named, a
     * refusal's sentence replaces the planted one whether or not the
     * slot was cleared first. What only the clear does is empty the slot
     * where the load writes nothing, and a load that succeeds is that
     * case: so the last leg plants a sentence, loads a good image and
     * wants the slot empty. */
    {
        static const struct {
            const char *what;
            cft_status  want;
            uint32_t    magic, ver, prec, flags, scr, n_consts;
            size_t      n;
            uint64_t    ins[11];
            const char *say[3];
        } L[] = {
            /* the header's own; 0 in magic and ver is the valid one */
            { .what = "a magic that is not CFTP",
              .want = CFT_ERR_ARTIFACT, .magic = 0x12345678u,
              .n = 1, .ins = { LD_HALT },
              .say = { "magic is 0x12345678", "not 0x50544643" } },
            { .what = "a program-image version this library does not read",
              .want = CFT_ERR_ARTIFACT, .ver = 2u,
              .n = 1, .ins = { LD_HALT },
              .say = { "version 2", "reads version 1" } },
            { .what = "scratch_io non-zero without SCRATCH_IO",
              .want = CFT_ERR_ARTIFACT, .scr = 0x00010002u,
              .n = 1, .ins = { LD_HALT },
              .say = { "scratch_io, is 0x00010002",
                       "do not carry SCRATCH_IO" } },
            { .what = "a flag bit this library does not know",
              .want = CFT_ERR_ARTIFACT, .flags = 0x80u,
              .n = 1, .ins = { LD_HALT },
              .say = { "flags are 0x00000080", "0x00000080 of that",
                       "BANK_EXT" } },
            { .what = "a precision code off the ladder",
              .want = CFT_ERR_ARTIFACT, .prec = 4u,
              .n = 1, .ins = { LD_HALT },
              .say = { "precision code is 4", "3 fp256" } },
            /* seq_validate: the bound, the loops, the codes */
            { .what = "a worst case past 2^40 instructions",
              .want = CFT_ERR_INVALID_ARGUMENT, .n = 6,
              .ins = { LD_REPEAT(1u << 20), LD_REPEAT(1u << 20), LD_ADD,
                       LD_ENDREP, LD_ENDREP, LD_HALT },
              .say = { "instruction 2", "1099512676353",
                       "1099511627776 (2^40)" } },
            { .what = "a trip-count product past 2^40",
              .want = CFT_ERR_INVALID_ARGUMENT, .n = 5,
              .ins = { LD_REPEAT(1u << 20), LD_REPEAT(1u << 21), LD_ENDREP,
                       LD_ENDREP, LD_HALT },
              .say = { "instruction 1 is REPEAT 2097152", "1048576 times",
                       "1099511627776" } },
            { .what = "REPEAT 0",
              .want = CFT_ERR_INVALID_ARGUMENT, .n = 3,
              .ins = { LD_REPEAT(0), LD_ENDREP, LD_HALT },
              .say = { "instruction 0 is REPEAT 0", "not a loop" } },
            { .what = "five nested loops",
              .want = CFT_ERR_INVALID_ARGUMENT, .n = 11,
              .ins = { LD_REPEAT(1), LD_REPEAT(1), LD_REPEAT(1), LD_REPEAT(1),
                       LD_REPEAT(1), LD_ENDREP, LD_ENDREP, LD_ENDREP,
                       LD_ENDREP, LD_ENDREP, LD_HALT },
              .say = { "instruction 4", "inside 4 open loops",
                       "at most 4 deep" } },
            { .what = "an ENDREP with no REPEAT open",
              .want = CFT_ERR_INVALID_ARGUMENT, .n = 2,
              .ins = { LD_ENDREP, LD_HALT },
              .say = { "instruction 0 is an ENDREP", "no REPEAT open" } },
            { .what = "ACTALL inside a loop",
              .want = CFT_ERR_INVALID_ARGUMENT, .n = 4,
              .ins = { LD_REPEAT(2), LD_CTL(5, 0, 0, 0, 0, 0, 0, 0),
                       LD_ENDREP, LD_HALT },
              .say = { "instruction 1 is ACTALL inside a loop",
                       "early exit" } },
            { .what = "HALT inside a loop",
              .want = CFT_ERR_INVALID_ARGUMENT, .n = 4,
              .ins = { LD_REPEAT(2), LD_HALT, LD_ENDREP, LD_HALT },
              .say = { "instruction 1 is HALT inside a loop",
                       "cannot gate it" } },
            { .what = "a loop left open at the end",
              .want = CFT_ERR_INVALID_ARGUMENT, .n = 2,
              .ins = { LD_REPEAT(2), LD_ADD },
              .say = { "after instruction 1", "inside 1 open loop",
                       "ENDREP" } },
            { .what = "an unknown control code",
              .want = CFT_ERR_INVALID_ARGUMENT, .n = 2,
              .ins = { LD_CTL(15, 0, 0, 0, 0, 0, 0, 0), LD_HALT },
              .say = { "instruction 0 is control code 15", "0 to 14" } },
            /* revision 8's R24 (ABI 0.17): the bracket rules and the
             * fields the three codes do not read */
            { .what = "an ENDQUIET with no quiet region open",
              .want = CFT_ERR_INVALID_ARGUMENT, .n = 2,
              .ins = { LD_CTL(13, 0, 0, 0, 0, 0, 0, 0), LD_HALT },
              .say = { "instruction 0 is an ENDQUIET",
                       "no quiet region open" } },
            { .what = "a HALT inside a quiet region",
              .want = CFT_ERR_INVALID_ARGUMENT, .n = 2,
              .ins = { LD_CTL(12, 0, 0, 0, 0, 0, 0, 0), LD_HALT },
              .say = { "instruction 1 is HALT inside the quiet region "
                       "opened at instruction 0", "save and its restore" } },
            { .what = "a quiet region left open at the end",
              .want = CFT_ERR_INVALID_ARGUMENT, .n = 2,
              .ins = { LD_CTL(12, 0, 0, 0, 0, 0, 0, 0), LD_ADD },
              .say = { "after instruction 1", "inside 1 open quiet region",
                       "ENDQUIET" } },
            { .what = "an ENDREP closing its loop around an open region",
              .want = CFT_ERR_INVALID_ARGUMENT, .n = 5,
              .ins = { LD_REPEAT(2), LD_CTL(12, 0, 0, 0, 0, 0, 0, 0),
                       LD_ENDREP, LD_CTL(13, 0, 0, 0, 0, 0, 0, 0), LD_HALT },
              .say = { "instruction 2 is an ENDREP",
                       "quiet region opened at instruction 1",
                       "closes in that body" } },
            { .what = "an ENDQUIET inside a loop opened in its region",
              .want = CFT_ERR_INVALID_ARGUMENT, .n = 5,
              .ins = { LD_CTL(12, 0, 0, 0, 0, 0, 0, 0), LD_REPEAT(2),
                       LD_CTL(13, 0, 0, 0, 0, 0, 0, 0), LD_ENDREP, LD_HALT },
              .say = { "instruction 2 is an ENDQUIET inside the loop opened "
                       "at instruction 1", "closes outside it" } },
            { .what = "a fifth nested quiet region",
              .want = CFT_ERR_INVALID_ARGUMENT, .n = 11,
              .ins = { LD_CTL(12, 0, 0, 0, 0, 0, 0, 0),
                       LD_CTL(12, 0, 0, 0, 0, 0, 0, 0),
                       LD_CTL(12, 0, 0, 0, 0, 0, 0, 0),
                       LD_CTL(12, 0, 0, 0, 0, 0, 0, 0),
                       LD_CTL(12, 0, 0, 0, 0, 0, 0, 0),
                       LD_CTL(13, 0, 0, 0, 0, 0, 0, 0),
                       LD_CTL(13, 0, 0, 0, 0, 0, 0, 0),
                       LD_CTL(13, 0, 0, 0, 0, 0, 0, 0),
                       LD_CTL(13, 0, 0, 0, 0, 0, 0, 0),
                       LD_CTL(13, 0, 0, 0, 0, 0, 0, 0), LD_HALT },
              .say = { "instruction 4 is a QUIET inside 4 open quiet "
                       "regions", "at most 4 deep" } },
            { .what = "a RAISE that names rb",
              .want = CFT_ERR_INVALID_ARGUMENT, .n = 2,
              .ins = { LD_CTL(14, 0, 1, 2, 0, 0, 0, 0), LD_HALT },
              .say = { "instruction 0 is RAISE", "does not read rb" } },
            { .what = "a QUIET with an immediate",
              .want = CFT_ERR_INVALID_ARGUMENT, .n = 3,
              .ins = { LD_CTL(12, 0, 0, 0, 0, 0, 0, 1),
                       LD_CTL(13, 0, 0, 0, 0, 0, 0, 0), LD_HALT },
              .say = { "instruction 0 is QUIET",
                       "reads only imm & 0x00000000" } },
            { .what = "a reserved rounding attribute",
              .want = CFT_ERR_INVALID_ARGUMENT, .n = 2,
              .ins = { LD_ALU(1, 0, 0, 0, 0, 5, 0, 0), LD_HALT },
              .say = { "instruction 0 (add, opcode 1)", "rnd is 5",
                       "0 to 4" } },
            /* a field each control code does not read, one per row of
             * seq_ctrl: an operand field, rnd, a k flag or kx, imm */
            { .what = "HALT naming rb",
              .want = CFT_ERR_INVALID_ARGUMENT, .n = 1,
              .ins = { LD_CTL(0, 0, 0, 3, 0, 0, 0, 0) },
              .say = { "instruction 0 is HALT", "does not read rb",
                       "it is 3" } },
            { .what = "REPEAT with a rounding attribute",
              .want = CFT_ERR_INVALID_ARGUMENT, .n = 3,
              .ins = { LD_CTL(1, 0, 0, 0, 0, 1, 0, 2), LD_ENDREP, LD_HALT },
              .say = { "instruction 0 is REPEAT", "does not read rnd",
                       "it is 1" } },
            { .what = "ENDREP with kx",
              .want = CFT_ERR_INVALID_ARGUMENT, .n = 4,
              .ins = { LD_REPEAT(2), LD_CTL(2, 0, 0, 0, 0, 0, LD_KX, 0),
                       LD_ENDREP, LD_HALT },
              .say = { "instruction 1 is ENDREP", "does not read kx" } },
            { .what = "DEPOSIT with rd's high bit",
              .want = CFT_ERR_INVALID_ARGUMENT, .n = 2,
              .ins = { LD_CTL(3, 0, 4, 0, 0, 0, 0, 1u << 24), LD_HALT },
              .say = { "instruction 0 is DEPOSIT", "imm & 0x02000000",
                       "imm = 0x01000000" } },
            { .what = "SETACT with ka",
              .want = CFT_ERR_INVALID_ARGUMENT, .n = 2,
              .ins = { LD_CTL(4, 0, 1, 0, 0, 0, LD_KA, 0), LD_HALT },
              .say = { "instruction 0 is SETACT", "does not read ka" } },
            { .what = "ACTALL naming rd",
              .want = CFT_ERR_INVALID_ARGUMENT, .n = 2,
              .ins = { LD_CTL(5, 1, 0, 0, 0, 0, 0, 0), LD_HALT },
              .say = { "instruction 0 is ACTALL", "does not read rd",
                       "it is 1" } },
            { .what = "STL naming rb",
              .want = CFT_ERR_INVALID_ARGUMENT, .n = 2,
              .ins = { LD_CTL(6, 0, 0, 1, 0, 0, 0, 0), LD_HALT },
              .say = { "instruction 0 is STL", "does not read rb" } },
            { .what = "LDL naming ra",
              .want = CFT_ERR_INVALID_ARGUMENT, .n = 2,
              .ins = { LD_CTL(7, 4, 2, 0, 0, 0, 0, 0), LD_HALT },
              .say = { "instruction 0 is LDL", "does not read ra",
                       "it is 2" } },
            { .what = "STX with imm[13], read by nothing",
              .want = CFT_ERR_INVALID_ARGUMENT, .n = 2,
              .ins = { LD_CTL(8, 0, 0, 1, 0, 0, 0, 1u << 13), LD_HALT },
              .say = { "instruction 0 is STX", "imm & 0x06000fff",
                       "imm = 0x00002000" } },
            { .what = "LDX naming rc",
              .want = CFT_ERR_INVALID_ARGUMENT, .n = 2,
              .ins = { LD_CTL(9, 4, 0, 1, 1, 0, 0, 0), LD_HALT },
              .say = { "instruction 0 is LDX", "does not read rc" } },
            { .what = "AUGADD with a rounding attribute",
              .want = CFT_ERR_INVALID_ARGUMENT, .n = 2,
              .ins = { LD_CTL(10, 3, 0, 1, 0, 2, 0, 0), LD_HALT },
              .say = { "instruction 0 is AUGADD", "does not read rnd",
                       "it is 2" } },
            { .what = "AUGERR with imm[0]",
              .want = CFT_ERR_INVALID_ARGUMENT, .n = 2,
              .ins = { LD_CTL(11, 3, 0, 1, 0, 0, 0, 1), LD_HALT },
              .say = { "instruction 0 is AUGERR", "imm & 0x07000000",
                       "imm = 0x00000001" } },
            /* seq_check_operands: an ALU instruction's operands */
            { .what = "an ALU instruction with imm[31]",
              .want = CFT_ERR_INVALID_ARGUMENT, .n = 2,
              .ins = { LD_ALU(1, 0, 0, 0, 0, 0, 0, 0x80000000u), LD_HALT },
              .say = { "instruction 0 (add, opcode 1)",
                       "imm[31] is reserved" } },
            { .what = "kx with no operand naming a constant",
              .want = CFT_ERR_INVALID_ARGUMENT, .n = 2,
              .ins = { LD_ALU(1, 0, 0, 0, 0, 0, LD_KX, 0), LD_HALT },
              .say = { "instruction 0 (add, opcode 1) sets kx",
                       "no operand names a constant" } },
            { .what = "imm[23:0] without kx",
              .want = CFT_ERR_INVALID_ARGUMENT, .n = 2,
              .ins = { LD_ALU(1, 0, 0, 0, 0, 0, 0, 5), LD_HALT },
              .say = { "has no kx", "imm[23:0] must be zero",
                       "it is 0x000005" } },
            { .what = "imm[30:28] without kx",
              .want = CFT_ERR_INVALID_ARGUMENT, .n = 2,
              .ins = { LD_ALU(1, 0, 0, 0, 0, 0, 0, 1u << 29), LD_HALT },
              .say = { "has no kx", "imm[30:28]", "they are 0x2" } },
            { .what = "a constant operand with its register high bit",
              .want = CFT_ERR_INVALID_ARGUMENT, .n_consts = 2, .n = 2,
              .ins = { LD_ALU(0, 4, 0, 1, 2, 0, LD_KB, 1u << 26), LD_HALT },
              .say = { "instruction 0 (fma, opcode 0)",
                       "rb names a constant", "imm[26]" } },
            { .what = "a register operand's ninth bit under kx",
              .want = CFT_ERR_INVALID_ARGUMENT, .n_consts = 2, .n = 2,
              .ins = { LD_ALU(0, 4, 0, 0, 0, 0, LD_KB | LD_KX,
                              (1u << 8) | (1u << 28)), LD_HALT },
              .say = { "ra names a register",
                       "ninth constant-index bit imm[28]" } },
            { .what = "a kx constant whose register field is set",
              .want = CFT_ERR_INVALID_ARGUMENT, .n_consts = 2, .n = 2,
              .ins = { LD_ALU(0, 4, 0, 3, 0, 0, LD_KB | LD_KX, 1u << 8),
                       LD_HALT },
              .say = { "rb names constant 1 through imm under kx",
                       "the rb field must be zero", "it is 3" } },
            { .what = "a register operand's byte of imm under kx",
              .want = CFT_ERR_INVALID_ARGUMENT, .n_consts = 2, .n = 2,
              .ins = { LD_ALU(0, 4, 0, 0, 0, 0, LD_KB | LD_KX,
                              5u | (1u << 8)), LD_HALT },
              .say = { "ra names a register under kx", "imm[7:0]",
                       "it is 0x05" } },
            { .what = "a four-bit constant index past the bank",
              .want = CFT_ERR_INVALID_ARGUMENT, .n_consts = 2, .n = 2,
              .ins = { LD_ALU(0, 4, 0, 5, 0, 0, LD_KB, 0), LD_HALT },
              .say = { "rb names constant 5", "declares 2 (n_consts)" } },
            { .what = "a nine-bit kx constant index past the bank",
              .want = CFT_ERR_INVALID_ARGUMENT, .n_consts = 2, .n = 2,
              .ins = { LD_ALU(0, 4, 0, 0, 0, 0, LD_KB | LD_KX,
                              (0x10u << 8) | (1u << 29)), LD_HALT },
              .say = { "rb names constant 272", "declares 2 (n_consts)" } }
        };
        static const uint64_t halt[1] = { LD_HALT };
        uint8_t img[256];
        size_t k, n;
        cft_program *lp = NULL;

        for (k = 0; k < sizeof L / sizeof L[0]; k++) {
            const size_t esz = L[k].prec <= (uint32_t)CFT_FP256
                                   ? cft_format_size((cft_format)L[k].prec)
                                   : 4u;
            n = ld_image(img, L[k].magic ? L[k].magic : 0x50544643u,
                         L[k].ver ? L[k].ver : 1u, L[k].prec, esz,
                         L[k].flags, L[k].scr, 1, L[k].n_consts, L[k].ins,
                         L[k].n);
            ld_expect(dev, dev, L[k].what, img, n, 1, L[k].want,
                      L[k].say[0], L[k].say[1], L[k].say[2]);
        }

        /* The three NULL arguments, and the length: an image shorter than
         * a header, one longer than its header describes, and a BANK_EXT
         * image that still carries the constant section it says it has
         * not. */
        n = ld_image(img, 0x50544643u, 1, CFT_FP32, 4, 0, 0, 1, 0, halt, 1);
        ld_expect(dev, NULL, "a NULL device", img, n, 1,
                  CFT_ERR_INVALID_ARGUMENT, "NULL device", NULL, NULL);
        ld_expect(dev, dev, "a NULL image", NULL, n, 1,
                  CFT_ERR_INVALID_ARGUMENT, "NULL image", NULL, NULL);
        ld_expect(dev, dev, "a NULL out", img, n, 0,
                  CFT_ERR_INVALID_ARGUMENT, "NULL out", NULL, NULL);
        ld_expect(dev, dev, "an image shorter than a header", img, 31, 1,
                  CFT_ERR_ARTIFACT, "31 bytes", "32-byte header", NULL);
        img[n] = 0;
        ld_expect(dev, dev, "an image a byte longer than its header says",
                  img, n + 1, 1, CFT_ERR_ARTIFACT, "is 41 bytes",
                  "describes 40", "1 x 8 of instructions");
        n = ld_image(img, 0x50544643u, 1, CFT_FP32, 4, 0, 0, 1, 2, halt, 1);
        put32(img + 24, CFT_PROG_FLAG_BANK_EXT);
        ld_expect(dev, dev, "a BANK_EXT image carrying constants", img, n, 1,
                  CFT_ERR_ARTIFACT, "is 48 bytes", "describes 40",
                  "under BANK_EXT");

        /* The length a header describes, where a 32-bit size_t wraps it:
         * n_insns 0x20000001 is 8 * 0x20000001 = 2^32 + 8 bytes of
         * instructions, 8 once wrapped, so this 40-byte image passed the
         * check on an i686 build and came back CFT_ERR_OUT_OF_MEMORY from
         * the allocation, where this 64-bit one says CFT_ERR_ARTIFACT
         * (measured 2026-09-30; wasm32 and the 32-bit boards are such
         * hosts). The check is made in 64 bits now. No gate here runs a
         * 32-bit build, so this holds the status and the 64-bit number
         * where it can, and the i686 probe's before and after are in the
         * round's ledger; a 32-bit build of this file holds it there. */
        n = ld_image(img, 0x50544643u, 1, CFT_FP32, 4, 0, 0, 1, 0, halt, 1);
        put32(img + 8, 0x20000001u);
        ld_expect(dev, dev, "a header describing 2^32 + 40 bytes", img, n, 1,
                  CFT_ERR_ARTIFACT, "is 40 bytes", "describes 4294967336",
                  "536870913 x 8 of instructions");

        /* The bank's depth (2026-10-01; golden-first, seq.py's validate
         * refuses it too). An n_consts above 512 - the deepest bank nine
         * index bits under kx reach - is refused at load on every
         * device, CFT_ERR_UNSUPPORTED as the capacity refusals beside it
         * are, naming the count and the reach. Until this date the
         * library loaded such an image, ran it on the software backend
         * and handed it to a tile, which refused it at its header check
         * with STATUS[3] (measured at 575a819: 513, 600 and 70,000 loaded
         * and ran, in the image and under BANK_EXT). Held at 513 and 600
         * in both forms, and at 512 in both: that loads and runs and
         * reads K[511], so the boundary is the bank's and not one below
         * it. A self-contained 600 is 2,456 bytes at fp32, past img[]. */
        {
            static uint8_t deep[32 + 600 * 4 + 3 * 8];
            static uint8_t kbank[512 * 4];
            static const uint64_t rd[3] = {
                /* add r4 = r0 + K[511]: kc and kx, the index's low byte
                 * in imm[23:16] and its ninth bit in imm[30] */
                LD_ALU(1, 4, 0, 0, 0, 0, 4u | LD_KX,
                       (0xFFu << 16) | (1u << 30)),
                LD_CTL(3, 0, 4, 0, 0, 0, 0, 0),         /* deposit r4 */
                LD_HALT };
            static const uint32_t past[2] = { 513u, 600u };
            uint8_t a2[8], d2[8];
            char what[64], says[64];
            int ext;
            size_t j;

            put32(a2, 0x3f800000u);                      /* 1.0 */
            put32(a2 + 4, 0x40000000u);                  /* 2.0 */
            memset(kbank, 0, sizeof kbank);
            put32(kbank + 511 * 4, 0x43ff8000u);         /* K[511] = 511.0 */
            for (ext = 0; ext < 2; ext++) {
                const uint32_t fe = ext ? CFT_PROG_FLAG_BANK_EXT : 0u;
                const char *form = ext ? "under BANK_EXT" : "in the image";

                n = ld_image(deep, 0x50544643u, 1, CFT_FP32, 4, fe, 0, 1,
                             512u, rd, 3);
                if (!ext)
                    memcpy(deep + 32, kbank, sizeof kbank);
                lp = NULL;
                st = cft_program_load(dev, deep, n, &lp);
                CHECK(st == CFT_OK && lp != NULL,
                      "a header of 512 constants %s must load: %s (%s)",
                      form, cft_strerror(st), cft_last_error());
                if (st == CFT_OK) {
                    memset(d2, 0, sizeof d2);
                    st = ext ? cft_program_run_bank(lp, kbank, sizeof kbank,
                                                    a2, NULL, NULL, d2,
                                                    NULL, 2, NULL, NULL)
                             : cft_program_run(lp, a2, NULL, NULL, d2, NULL,
                                               2, NULL, NULL);
                    CHECK(st == CFT_OK && get32(d2) == 0x44000000u &&
                          get32(d2 + 4) == 0x44004000u,
                          "512 constants %s: 1 + K[511] and 2 + K[511] "
                          "must be 512 and 513: %s 0x%08x 0x%08x", form,
                          cft_strerror(st), get32(d2), get32(d2 + 4));
                    cft_program_free(lp);
                }
                for (j = 0; j < 2; j++) {
                    n = ld_image(deep, 0x50544643u, 1, CFT_FP32, 4, fe, 0,
                                 1, past[j], rd, 3);
                    snprintf(what, sizeof what, "a header of %lu constants "
                             "%s", (unsigned long)past[j], form);
                    snprintf(says, sizeof says, "declares %lu constants "
                             "(n_consts)", (unsigned long)past[j]);
                    ld_expect(dev, dev, what, deep, n, 1, CFT_ERR_UNSUPPORTED,
                              says, "addresses at most 512",
                              "no device holds a bank that deep");
                }
            }
        }

        /* The entry clear, which is what nothing above can see. A good
         * load leaves the library's slot empty, so cft_last_error() is
         * then exactly backend_words(): nothing in a build without a
         * device backend's message, and in an XRT build that backend's
         * own words for the cft_open of no-such.xclbin above
         * (docs/HOSTAPI.md). Until 2026-09-30 this required the words to
         * be empty, which an XRT build failed (the card leg of revision
         * 7's quad q135b). */
        n = ld_image(img, 0x50544643u, 1, CFT_FP32, 4, 0, 0, 1, 0, halt, 1);
        CHECK(ld_plant(dev), "the clear's leg: the plant left no sentence");
        CHECK(strcmp(cft_last_error(), backend_words()) != 0,
              "the clear's leg: the plant is not in the library's slot");
        st = cft_program_load(dev, img, n, &lp);
        CHECK(st == CFT_OK && lp != NULL,
              "the clear's leg: a good image loads: %s (%s)",
              cft_strerror(st), cft_last_error());
        CHECK(strcmp(cft_last_error(), backend_words()) == 0,
              "a load that succeeds must leave the library's slot empty - "
              "cft_last_error() shows '%s', where a device backend's "
              "message is '%s'", cft_last_error(), backend_words());
        cft_program_free(lp);
        printf("  program load: %lu refusals, each its status and a "
               "sentence of its own after an earlier call's; a good "
               "load clears the library's slot\n",
               (unsigned long)(sizeof L / sizeof L[0] + 11u));
    }

    cft_close(dev);
    cft_close(NULL);                /* must be safe */

    if (failures == 0)
        printf("api-test: all contract checks passed\n");
    else
        printf("api-test: %d FAILED\n", failures);
    return failures ? 1 : 0;
}
