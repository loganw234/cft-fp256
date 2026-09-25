/* Copyright 2026 Logan W.
 * SPDX-License-Identifier: Apache-2.0
 *
 * How a sequencer program run's operands are cut when its LANES are
 * split across compute units. Internal.
 *
 * slice.h's reason, again: the arithmetic that decides whether every
 * lane's every operand reaches exactly one tile, at the right offset,
 * is arithmetic no test could reach while it lived inside the XRT
 * backend, because reaching it needs a card. backend.h's cft_seq_run_io
 * already states the rule - a chunk of k lanes from `off` carries
 * [off * w, (off + k) * w) of every per-lane block, and the WHOLE of an
 * indexed source, since an index reaches anywhere in it - and this is
 * that rule as one function the backend calls and host/tests/api_test.c
 * holds, over every cut it can make, on any machine.
 *
 * Two planners. The backend's own is slice.h's cft_plan_slices, so a
 * program's lanes are cut at the beat boundaries an elementwise run's
 * elements are. The other, cft_plan_lane_cuts, puts the cuts anywhere -
 * one lane, an odd offset, a tile left with nothing - from a seed; it is
 * what CFT_XRT_PROGRAM_CUTS asks the backend for, so that "where the
 * lanes are cut cannot reach a result" (docs/SEQUENCER.md, P3: the
 * all-lanes-done exit is invisible) is fuzzed on a card, not argued.
 */

#ifndef CFT_LANE_CUT_H
#define CFT_LANE_CUT_H

#include <stddef.h>
#include <stdint.h>

#include "slice.h"

/* The caller's per-run blocks, in the order the windows come back. */
enum {
    CFT_LANE_A, CFT_LANE_B, CFT_LANE_C,     /* the three streams */
    CFT_LANE_DEP, CFT_LANE_CNT,             /* deposit window, counts */
    CFT_LANE_SIN, CFT_LANE_SOUT,            /* the scratch blocks */
    CFT_LANE_IA, CFT_LANE_IB, CFT_LANE_IC,  /* the streams' index tables */
    CFT_LANE_ISI,                           /* the scratch block's */
    CFT_LANE_ROLES
};

/* What a run's blocks are shaped by. `src_elems[r]` is non-zero exactly
 * when block r (a, b, c or scratch-in) is INDEXED, and is then the
 * length of its source in elements; a dense block has none. */
typedef struct {
    size_t n;               /* lanes in the run */
    size_t esz;             /* bytes an element */
    size_t max_deposits;    /* deposit slots a lane */
    size_t n_sin, n_sout;   /* scratch slots a lane, in and out */
    int    has_sin, has_sout;
    size_t src_elems[4];    /* a, b, c, scratch-in: 0 = dense */
} cft_lane_shape;

/* One block's window for one slice: bytes into the caller's buffer.
 * `whole` marks a block every tile receives entire - an indexed source,
 * which a lane's index can reach anywhere in. A block the run does not
 * have is { 0, 0, 0 }. */
typedef struct {
    size_t off, len;
    int    whole;
} cft_lane_win;

/* The windows of the slice [first, first + lanes). */
static void cft_lane_windows(const cft_lane_shape *S, size_t first,
                             size_t lanes, cft_lane_win w[CFT_LANE_ROLES])
{
    const size_t esz = S->esz;
    int r;

    for (r = 0; r < CFT_LANE_ROLES; r++) {
        w[r].off = 0;
        w[r].len = 0;
        w[r].whole = 0;
    }
    for (r = 0; r < 3; r++) {
        if (S->src_elems[r]) {
            w[r].len = S->src_elems[r] * esz;
            w[r].whole = 1;
            w[CFT_LANE_IA + r].off = first * 4;
            w[CFT_LANE_IA + r].len = lanes * 4;
        } else {
            w[r].off = first * esz;
            w[r].len = lanes * esz;
        }
    }
    w[CFT_LANE_DEP].off = first * S->max_deposits * esz;
    w[CFT_LANE_DEP].len = lanes * S->max_deposits * esz;
    w[CFT_LANE_CNT].off = first * 4;
    w[CFT_LANE_CNT].len = lanes * 4;
    if (S->has_sin) {
        if (S->src_elems[3]) {
            w[CFT_LANE_SIN].len = S->src_elems[3] * esz;
            w[CFT_LANE_SIN].whole = 1;
            w[CFT_LANE_ISI].off = first * S->n_sin * 4;
            w[CFT_LANE_ISI].len = lanes * S->n_sin * 4;
        } else {
            w[CFT_LANE_SIN].off = first * S->n_sin * esz;
            w[CFT_LANE_SIN].len = lanes * S->n_sin * esz;
        }
    }
    if (S->has_sout) {
        w[CFT_LANE_SOUT].off = first * S->n_sout * esz;
        w[CFT_LANE_SOUT].len = lanes * S->n_sout * esz;
    }
}

/* splitmix64: the fuzzing planner's only source of numbers, so a seed
 * names one set of cuts on every machine. */
static uint64_t cft_lane_mix(uint64_t *s)
{
    uint64_t z = (*s += 0x9E3779B97F4A7C15ull);
    z = (z ^ (z >> 30)) * 0xBF58476D1CE4E5B9ull;
    z = (z ^ (z >> 27)) * 0x94D049BB133111EBull;
    return z ^ (z >> 31);
}

/* Cut [0, n) at ntiles - 1 lane boundaries drawn from `seed` - any
 * lane, including 0 and n, so a tile can get one lane or none - and
 * write the non-empty slices in lane order, tile t holding the t-th
 * region. Returns how many; zero when n or ntiles is. Deterministic in
 * (seed, n, ntiles). `real` and `padded` are both the slice's lane
 * count: a program tile starts lanes past its N inactive, so a program
 * slice needs no beat padding of its lanes. */
static size_t cft_plan_lane_cuts(size_t n, size_t ntiles, uint64_t seed,
                                 cft_slice *out)
{
    size_t cut[64], t, i, j, k = 0, prev = 0;
    uint64_t s = seed ^ ((uint64_t)n * 0xD1B54A32D192ED03ull);

    if (n == 0 || ntiles == 0)
        return 0;
    if (ntiles > 64)
        ntiles = 64;
    for (t = 0; t + 1 < ntiles; t++)
        cut[t] = (size_t)(cft_lane_mix(&s) % ((uint64_t)n + 1));
    for (i = 1; i + 1 < ntiles; i++)            /* insertion sort */
        for (j = i; j > 0 && cut[j - 1] > cut[j]; j--) {
            size_t x = cut[j];
            cut[j] = cut[j - 1];
            cut[j - 1] = x;
        }
    cut[ntiles - 1] = n;
    for (t = 0; t < ntiles; t++) {
        if (cut[t] > prev) {
            out[k].tile = t;
            out[k].first_elem = prev;
            out[k].real = cut[t] - prev;
            out[k].padded = cut[t] - prev;
            k++;
        }
        prev = cut[t];
    }
    return k;
}

/* Which tile runs which task of one wave: out[j] is the tile for the
 * wave's j-th task. The identity when `seed` is zero - the scheduler's
 * default - and otherwise a permutation of [0, ntiles) drawn from
 * (seed, wave), which is what CFT_XRT_TILE_ORDER asks for: a job's bits
 * may not depend on which tile ran which of its tasks, and the card gate
 * holds that by moving the tasks around. Every kind of run is placed
 * through this, so it lives beside the cut rather than inside one
 * kind's path. */
static void cft_tile_order(size_t ntiles, uint64_t seed, size_t wave,
                           size_t *out)
{
    uint64_t s = seed ^ ((uint64_t)(wave + 1) * 0xA0761D6478BD642Full);
    size_t i;

    for (i = 0; i < ntiles; i++)
        out[i] = i;
    if (!seed)
        return;
    for (i = ntiles; i > 1; i--) {               /* Fisher-Yates */
        size_t j = (size_t)(cft_lane_mix(&s) % (uint64_t)i), x = out[i - 1];
        out[i - 1] = out[j];
        out[j] = x;
    }
}

#endif /* CFT_LANE_CUT_H */
