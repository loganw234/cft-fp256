/* Copyright 2026 Logan W.
 * SPDX-License-Identifier: Apache-2.0
 *
 * Which compute units a device opens: CFT_XRT_TILES. Internal.
 *
 * By default an XRT device opens every tile an image declares, each
 * with exclusive access, and is one device of that many tiles. A
 * service that runs independent jobs wants the other shape: one
 * process per tile, each owning its own compute unit, so that four
 * jobs run on a quad at once and a timeout finishes one tile rather
 * than the card (docs/VALIDATION.md, 2026-09-25). The variable names
 * the tiles a process opens, as the 1-based ordinals their compute
 * units carry (cft_krnl_1 is 1):
 *
 *     CFT_XRT_TILES=2        tile 2 alone
 *     CFT_XRT_TILES=1,3      tiles 1 and 3, in that order
 *
 * The parse is a pure function of the text, here rather than inside
 * the XRT backend, so host/tests/api_test.c holds it on any machine -
 * the reason slice.h exists. Its rules are strict because a selection
 * is a claim about hardware: decimal digits only, no sign, no spaces,
 * no empty item, no ordinal outside 1..64, no ordinal named twice. A
 * list that breaks one is refused with a sentence, never read as the
 * nearest thing it resembles.
 */

#ifndef CFT_TILE_SELECT_H
#define CFT_TILE_SELECT_H

#include <stddef.h>
#include <stdint.h>
#include <stdio.h>

#define CFT_TILE_SELECT_MAX 64

/* Parse `s` into `order` (the ordinals in the order written, at most
 * CFT_TILE_SELECT_MAX) and return how many; or return -1 and write why
 * into why[whylen]. An empty string is not a selection and is refused:
 * the caller treats an ABSENT variable as "every tile", and an empty
 * one set by mistake must not read as that. */
static int cft_tile_select_parse(const char *s, int *order, char *why,
                                 size_t whylen)
{
    uint64_t seen = 0;
    int n = 0;
    const char *p = s;

    if (!s || !*s) {
        snprintf(why, whylen, "CFT_XRT_TILES is empty; unset it to open "
                 "every tile, or name tiles as 1-based ordinals (\"2\", "
                 "\"1,3\")");
        return -1;
    }
    for (;;) {
        long v = 0;
        int digits = 0;
        while (*p >= '0' && *p <= '9') {
            if (v <= CFT_TILE_SELECT_MAX)
                v = v * 10 + (*p - '0');
            digits++;
            p++;
        }
        if (!digits) {
            snprintf(why, whylen, "CFT_XRT_TILES=\"%s\": expected a 1-based "
                     "tile ordinal at offset %d", s, (int)(p - s));
            return -1;
        }
        if (v < 1 || v > CFT_TILE_SELECT_MAX) {
            snprintf(why, whylen, "CFT_XRT_TILES=\"%s\": tile %ld is outside "
                     "1..%d", s, v, CFT_TILE_SELECT_MAX);
            return -1;
        }
        if (seen & ((uint64_t)1 << (v - 1))) {
            snprintf(why, whylen, "CFT_XRT_TILES=\"%s\": tile %ld is named "
                     "twice", s, v);
            return -1;
        }
        seen |= (uint64_t)1 << (v - 1);
        order[n++] = (int)v;
        if (*p == 0)
            return n;
        if (*p != ',') {
            snprintf(why, whylen, "CFT_XRT_TILES=\"%s\": unexpected '%c' at "
                     "offset %d (ordinals are separated by commas, nothing "
                     "else)", s, *p, (int)(p - s));
            return -1;
        }
        p++;
    }
}

#endif
