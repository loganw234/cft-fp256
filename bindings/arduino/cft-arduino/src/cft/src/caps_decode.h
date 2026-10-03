/* Copyright 2026 Logan W.
 * SPDX-License-Identifier: Apache-2.0
 *
 * A tile's capability words, decoded. Internal.
 *
 * What cftx_open makes of three registers - VERSION (0x48), CAPS (0x4C)
 * and CAPS2 (0x6C) - as the sequencer's features and capacities in
 * cft_seq_caps. The XRT backend reads the registers; this says what they
 * mean. A pure function of the three words, here rather than inside the
 * backend, so that host/tests/api_test.c holds it on any machine - the
 * reason slice.h, tile_select.h and mask_bits.h exist - and in
 * particular so that revision 8's map (docs/ROADMAP.md, "Revision 8",
 * the seam) is held to the words the plan computed before any 0xB00 tile
 * is opened: the backend compiles only with XRT, and a decode no machine
 * here can run is a decode nobody has run. rtl/cft_csr.sv is the
 * normative map and rtl/cft_krnl.sv assembles the words.
 *
 * Shift, do not transcribe: every capacity is published as an EXPONENT
 * (each is a power of two by construction - two memory depths and a
 * field width), so a literal 64 here is how a host would go on believing
 * a trimmed tile was a full one. And every field is believed only on a
 * map that has it: a bit set where VERSION says its register cannot
 * exist is a capability register lying about its map, and is not read.
 */

#ifndef CFT_CAPS_DECODE_H
#define CFT_CAPS_DECODE_H

#include <stdint.h>

#include "backend.h"      /* cft_seq_caps */

/* The first VERSION whose map has each field (rtl/cft_csr.sv's VERSION
 * history). backend_xrt.cpp holds its own names for these to the same
 * numbers at compile time. */
#define CFT_MAP_CAPS2   0x00000800u  /* CAPS2 at 0x6C; the scratch pair */
#define CFT_MAP_SEG     0x00000900u  /* SEG/NRES; CAPS2[8] */
#define CFT_MAP_IDX     0x00000A00u  /* 0x88..0xA8; CAPS2[10:9] */
#define CFT_MAP_LFLAGS  0x00000B00u  /* LFLAGS_PTR (0xB0), revision 8's
                                      * seam; CAPS2[14:11] and [20:16] */

static inline void cft_caps_decode(uint32_t ver, uint32_t caps, uint32_t caps2,
                                   cft_seq_caps *seq)
{
    /* CAPS[27:16]: deposit slots a lane, instructions and addressable
     * constants, four bits of log2 each. A tile whose VERSION predates
     * them reads zeros there, and cft_caps documents zero as UNKNOWN -
     * so the caps check in cft_program_load does not fire against it,
     * which is the behaviour that tile had before the fields existed.
     * The card-day 0x410 images are exactly that case. */
    const uint32_t sizes = (caps >> 16) & 0xFFFu;

    /* No CAPS2 below 0x800: the backend does not read 0x6C there, and a
     * word handed in anyway is not believed. */
    if (ver < CFT_MAP_CAPS2)
        caps2 = 0;

    /* CAPS[7:4], the first sequencer feature nibble, in bits 3:0 (kx,
     * REGS32, BANK_PTR, KX9), and CAPS[31:28], the ALU extensions, in
     * bits 7:4 - IMUL is bit 28, cft.h's CFT_ALU_EXT_IMUL. */
    seq->features = ((caps >> 4) & 0xFu) | (((caps >> 28) & 0xFu) << 4);
    /* CAPS2[7:4], the second nibble, in bits 11:8: SCRATCH, SCRATCH_IO,
     * SCRATCH_STRICT and SCALAR, travelling together as the first does. */
    seq->features |= ((caps2 >> 4) & 0xFu) << 8;
    /* CAPS2[8] on bit 12, CFT_FEAT_REDUCE_SEG (2026-09-14), only where the
     * map has the SEG/NRES pair. */
    if (ver >= CFT_MAP_SEG && (caps2 & 0x100u))
        seq->features |= 0x1000u;
    /* CAPS2[9] and [10] on bits 13 and 14 (ABI 0.14): INDEXED and
     * LANE_MASK, only where the map has the five pointers they need. */
    if (ver >= CFT_MAP_IDX) {
        if (caps2 & 0x200u) seq->features |= 0x2000u;
        if (caps2 & 0x400u) seq->features |= 0x4000u;
    }
    /* CAPS2[14:11] on bits 18:15 (revision 8, from its seam): AUGADD
     * (R21), SCRATCH_STEP (R22), LANE_FLAGS (R23) and FLAG_CONTROL (R24)
     * - cft.h's CFT_SEQ_FEAT_AUGADD 0x8000 to CFT_SEQ_FEAT_FLAG_CONTROL
     * 0x40000, in CAPS2's order - only where the map is 0xB00 or later:
     * R23's block needs LFLAGS_PTR, and every tile below 0xB00 read these
     * bits as reserved zeros. Shifted as a nibble, like the two above. */
    if (ver >= CFT_MAP_LFLAGS)
        seq->features |= ((caps2 >> 11) & 0xFu) << 15;

    /* CAPS2[3:0] is log2 of the scratch depth, meaningful only where
     * CAPS2[4] says the memory is there; zero (UNKNOWN, enforced against
     * nothing) otherwise, as below 0x800. */
    seq->max_scratch = (caps2 & 0x10u) ? (1u << (caps2 & 0xFu)) : 0u;

    if (sizes == 0) {
        seq->max_deposits = 0;
        seq->max_insns    = 0;
        seq->max_consts   = 0;
        return;
    }
    seq->max_deposits = 1u << ((caps >> 16) & 0xFu);
    seq->max_insns    = 1u << ((caps >> 20) & 0xFu);
    seq->max_consts   = 1u << ((caps >> 24) & 0xFu);
    /* CAPS2[20:16] (revision 8's R8S, docs/studies/R8S-streaming.md,
     * section 6): log2 of the instructions a program may have on a tile
     * that STREAMS them, five bits because four stop at 2^15, the very
     * ceiling streaming removes. Zero says CAPS[23:20] is the capacity -
     * every tile that holds its program on chip, and every tile below
     * 0xB00, whose CSR padded the word's top half with zeros. A
     * streaming tile publishes CAPS[23:20] as min(15, the log2), so a
     * host that does not read this field sizes to 32,768 and never past
     * what the tile takes. */
    if (ver >= CFT_MAP_LFLAGS) {
        const uint32_t big = (caps2 >> 16) & 0x1Fu;
        if (big)
            seq->max_insns = 1u << big;
    }
}

#endif /* CFT_CAPS_DECODE_H */
