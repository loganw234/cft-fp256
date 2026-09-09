/* Copyright 2026 Logan W.
 * SPDX-License-Identifier: Apache-2.0
 *
 * How an element count is split across compute units. Internal.
 *
 * This is three lines of arithmetic that decide whether a four-tile
 * run computes every element exactly once, at the right offset, with
 * the right amount of padding - and it is arithmetic no test could
 * reach while it lived inside the XRT backend, because reaching it
 * needed a card.
 *
 * So it lives here instead, as a pure function of (n, element size,
 * tile count), and host/tests/api_test.c exercises it over every
 * interesting n and tile count on any machine. The device backend
 * calls the same function; there is no second copy to drift.
 *
 * The properties it must have, which the test asserts rather than
 * assumes:
 *
 *   - every element of [0, n) lands in exactly one slice, and slices
 *     are contiguous and in increasing index order
 *   - each slice covers a whole number of 256-bit beats, because the
 *     engine's beat count is `n >> (LANE_SH - prec)` and a partial
 *     beat would be truncated away rather than rounded up
 *   - the TOTAL padding is the same for any tile count. That is what
 *     makes the exception flags independent of how the work was
 *     split: padding is flag-free, but only a constant amount of it
 *     keeps the sticky word constant.
 */

#ifndef CFT_SLICE_H
#define CFT_SLICE_H

#include <stddef.h>

typedef struct {
    size_t tile;        /* which compute unit */
    size_t first_elem;  /* index of this slice's first element */
    size_t real;        /* elements the caller asked for */
    size_t padded;      /* elements the engine will process */
} cft_slice;

/* Fill `out` (at least `ntiles` entries) and return how many slices
 * were produced - fewer than ntiles when there are fewer beats than
 * tiles, and zero when n is zero. */
static size_t cft_plan_slices(size_t n, size_t elem_bytes, size_t ntiles,
                              cft_slice *out)
{
    size_t epb, beats_total, per_tile, t, k = 0;

    if (n == 0 || ntiles == 0 || elem_bytes == 0)
        return 0;
    epb = 32 / elem_bytes;              /* elements per 256-bit beat */
    if (epb == 0)
        epb = 1;
    beats_total = (n + epb - 1) / epb;
    per_tile = (beats_total + ntiles - 1) / ntiles;

    for (t = 0; t < ntiles; t++) {
        size_t first_beat = t * per_tile;
        size_t nbeats, first_elem, padded, real;
        if (first_beat >= beats_total)
            break;                      /* fewer beats than tiles */
        nbeats = beats_total - first_beat;
        if (nbeats > per_tile)
            nbeats = per_tile;
        first_elem = first_beat * epb;
        padded = nbeats * epb;
        real = n - first_elem;
        if (real > padded)
            real = padded;
        out[k].tile = t;
        out[k].first_elem = first_elem;
        out[k].real = real;
        out[k].padded = padded;
        k++;
    }
    return k;
}

#endif /* CFT_SLICE_H */
