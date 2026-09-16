/* Copyright 2026 Logan W.
 * SPDX-License-Identifier: Apache-2.0
 *
 * How a lane mask is cut for one compute unit. Internal.
 *
 * ABI 0.14's lane mask (docs/SEQUENCER.md R17) is one bit a lane over
 * the whole run, and a tile is given a SLICE of the run - so the bits
 * a tile needs start at bit `first`, which is not a byte boundary at
 * every format. `slice.h` cuts at 256-bit beats, and a beat is ONE
 * lane at fp256, so a slice can begin at any lane and therefore at any
 * bit: tile 1 of an fp256 run of 24 lanes begins at lane 12, which is
 * bit 4 of byte 1. A backend cannot hand the tile a pointer into the
 * caller's bytes and call it the tile's mask - the tile reads bit 0 of
 * what it is given as lane 0 of what it is running - so the slice's
 * bits are REPACKED to start at bit 0.
 *
 * This lives here, beside slice.h and for exactly its reason: it is
 * arithmetic whose failure is a wrong answer in the wrong lanes, it is
 * reached only from the XRT backend, and reaching it there needs a
 * card. As a pure function of (source, first, lanes) it is a dozen
 * lines that host/tests/api_test.c exercises at every bit offset on
 * any machine.
 *
 * The properties, which api_test.c asserts rather than assumes:
 *
 *   - bit j of the result is bit (first + j) of the source, for every
 *     j in [0, lanes);
 *   - every bit above `lanes - 1` in the last byte is ZERO, so a tile
 *     that reads a whole beat sees no lane it does not have (the tile
 *     ignores them - its own blk_n does - but a mask buffer that
 *     carried another tile's lanes in its padding would make the two
 *     answers depend on the split, which is the property slice.h
 *     exists to keep);
 *   - `first = 0` is a copy, which is the only case a run on one tile
 *     can produce and the only one reachable today.
 */

#ifndef CFT_MASK_BITS_H
#define CFT_MASK_BITS_H

#include <stddef.h>
#include <stdint.h>

/* Bytes a mask of `lanes` lanes occupies: the ABI's (n + 7) / 8. */
static size_t cft_mask_bytes(size_t lanes)
{
    return (lanes + 7u) / 8u;
}

/* Copy `lanes` bits starting at bit `first` of `src` into `dst`,
 * starting at bit 0, and zero the rest of the last byte. `dst` must
 * hold cft_mask_bytes(lanes) bytes. A NULL `src` means every lane, so
 * the result is all ones - the caller of a run with no mask does not
 * reach this, but a backend that binds the register unconditionally
 * does, and "no mask" must never read as "no lanes". */
static void cft_mask_repack(uint8_t *dst, const uint8_t *src,
                            size_t first, size_t lanes)
{
    size_t nb = cft_mask_bytes(lanes), i;

    if (!dst)
        return;
    if (!src) {
        for (i = 0; i < nb; i++)
            dst[i] = 0xFFu;
    } else {
        for (i = 0; i < nb; i++)
            dst[i] = 0;
        for (i = 0; i < lanes; i++) {
            size_t b = first + i;
            if (src[b >> 3] & (uint8_t)(1u << (b & 7u)))
                dst[i >> 3] |= (uint8_t)(1u << (i & 7u));
        }
    }
    /* The tail of the last byte. Bits at or past `lanes` are not the
     * tile's lanes; they are zeroed whether they came from a
     * neighbouring tile's slice or from the all-ones fill above. */
    if (nb && (lanes & 7u))
        dst[nb - 1] &= (uint8_t)((1u << (lanes & 7u)) - 1u);
}

#endif /* CFT_MASK_BITS_H */
