/* Copyright 2026 Logan W.
 * SPDX-License-Identifier: Apache-2.0
 *
 * The orbit sequencer, executed in software.
 *
 * A port of python/cft_golden/seq.py, which is the definition of
 * correct, in the same way device.c's element loop is a port of
 * softfloat.py. The control flow and the names follow it deliberately,
 * so the two can be read side by side.
 *
 * ---------------------------------------------------------------
 * Lanes are processed in blocks, and that is not an optimisation
 * ---------------------------------------------------------------
 *
 * A lane's state is 32 registers of format width (16 before revision 2
 * of docs/SEQUENCER.md, 2026-09-08). Holding all of them for a large n
 * would be absurd - a million fp256 elements would want a gigabyte of
 * register file - so lanes are processed BLOCK_LANES at a time.
 *
 * That is a partitioning, and partitioning is exactly what P2 and P3
 * in docs/SEQUENCER.md promise is invisible: deposits are addressed by
 * element index, and the early exit cannot change a result. So the
 * block size is free to be whatever suits the machine, and the answer
 * is the same as a single enormous block - which host/tests checks
 * against the golden model running the whole array at once, because a
 * promise that is only argued is a promise that is only probably kept.
 *
 * The hardware has the same structure for a different reason: its
 * block must be at least the ALU's 16-stage latency for the pipeline
 * to stay full. Here the number is chosen for cache, not for
 * latency, and neither choice is observable.
 */

/* This module is optional: the sequencer and its image loader, removed
 * entirely by -DCFT_NO_PROGRAM. Removed rather than left for the
 * linker to garbage-collect, because what does not fit on a part with
 * 32 KB of flash is as often a constant table as it is code, and a
 * table reachable from one live function is not collected. */
#include "../include/cft_config.h"
#ifndef CFT_NO_PROGRAM

#include <stdlib.h>
#include <string.h>

#include "../include/cft.h"
#include "softfloat.h"
#include "sha256.h"
/* Unconditionally, for cft_seq_caps and the two seams device.c owns:
 * which caps a handle publishes, and which executor a program run
 * belongs to. The second is only reachable when a device backend was
 * compiled in - XRT, or the remote one of docs/REMOTE.md, which is
 * there unless CFT_NO_REMOTE says otherwise - but a declaration costs
 * nothing in a build that has neither, and a header included in two
 * places under two conditions is how a signature drifts. */
#include "backend.h"
/* The header flags by name, rendered from a mask, for the refusal of a
 * flag bit this loader does not know - the generated table the comment
 * above SEQ_FLAGS_KNOWN points at, rather than a list written here. */
#include "../include/cft_seq_flags.h"

#define SEQ_MAGIC        0x50544643u   /* "CFTP" */
#define SEQ_VERSION      1u
#define SEQ_HEADER_BYTES 32
#define SEQ_INSN_BYTES   8
/* Revision 2's thirty-two registers a lane. The low four bits of each
 * field stay where they were and the fifth lives in imm[27:24], so a
 * program that names only r0..r15 encodes exactly as it always did -
 * which is what lets an image built before this run unchanged. */
#define SEQ_NREG         32
#define SEQ_NREG_NARROW  16            /* what a device without
                                        * CFT_SEQ_FEAT_REGS32 has */
#define SEQ_MAX_DEPTH    4
/* The worst-case number of instruction ISSUES a program may perform,
 * loops multiplied out - a run-length bound, not a capacity, and not
 * published anywhere. */
#define SEQ_MAX_INSNS    (1ull << 40)

/* ---- what THIS backend accepts in a program header ------------------
 *
 * cft_get_caps publishes these three for a software device and
 * cft_program_load holds it to exactly them, which is the invariant
 * host/tests/device_test.c checks: the caps a backend reports are the
 * caps it enforces. They are NOT a tile's - a tile publishes its own
 * in CAPS, 1,024 deposit slots a lane and 32,768 instructions on the
 * U50's revision-7 images, 64 and 16,384 on the round-2 images and
 * the open-core builds - and they are deliberately not narrowed to
 * match one, because the software backend is the
 * CONTRACT rather than an implementation of it, and every recorded
 * workload chain (docs/REMOTE.md, bindings/wasm/demos_chains.json)
 * was produced through this accepted set. What used to be missing was
 * not a narrower software backend but a way to ASK, which is what
 * cft_caps.max_deposits now is: cft-zoom and cft-orbits size
 * themselves from the answer instead of from a literal 64.
 *
 * max_insns is the header field's own ceiling. This backend imposes
 * nothing of its own on the instruction count - the image is checked
 * for being exactly header + constants + instructions, so a program
 * of n instructions is 8n bytes the caller had to have - and a cap of
 * 2^32-1 is therefore the honest report: it is the largest n_insns a
 * 32-bit header field can express.
 *
 * max_consts is the number of constants an instruction can ADDRESS:
 * sixteen through the four-bit ka/kb/kc fields, and under kx, with
 * revision 3's ninth index bits, 512 - the same 512 a tile of
 * revision 3 or later publishes (rtl/cft_seq.sv's KREG, which is its
 * KMEM_D). That is also the deepest bank a header can declare, and
 * since 2026-10-01 cft_program_load refuses an n_consts above it on
 * every device, by name, as the golden model's loader does: no
 * instruction addresses a constant past it, and a tile refuses such
 * an image at its header check only after the image has crossed. At
 * or below 512 a header may still declare more constants than its
 * instructions name; the rest are simply unaddressed. The 512 is the
 * loader's and every tile's since revision 3: a tile built before had a
 * 256-entry bank, and a header of 257 to 512 still crosses to it and is
 * refused there - a known limit, since no such tile is in use. */
#define SEQ_MAX_DEPOSITS (1uL << 20)
#define SEQ_IMAGE_INSNS  0xFFFFFFFFu
#define SEQ_ADDR_CONSTS  512u  /* with kx (2026-09-07) an instruction's
                                * 8-bit indices reach 256 of the bank,
                                * and with the ninth bits of revision 3
                                * (kx9, imm[30:28]) the whole 512; the
                                * 4-bit fields still reach 16 */

/* The scratch memory's depth, a lane's own (docs/SEQUENCER.md revision
 * 3, R4). It is the executor's array bound, the modulus STX and LDX
 * reduce by, the ceiling a static STL or LDL slot is held to, and the
 * number a software handle publishes as max_scratch - and since
 * revision 7 (2026-09-29) all four are read from ONE place, the handle:
 * cft_sw_seq_caps publishes this default, a software handle opened at
 * another depth publishes that one instead (device.c), and a program
 * loaded on it takes the handle's number once, at load
 * (seq_scratch_footprint), for every use after. A second copy of the
 * depth is how those four would start to disagree. */
#define SEQ_SCRATCH_D    256u

#define BLOCK_LANES      64

/* control codes */
enum { SEQ_HALT = 0, SEQ_REPEAT, SEQ_ENDREP, SEQ_DEPOSIT, SEQ_SETACT,
       SEQ_ACTALL, SEQ_STL, SEQ_LDL, SEQ_STX, SEQ_LDX,
       /* revision 8 (proposed 2026-09-29): augmentedAddition's two
        * halves - see the block above seq_validate */
       SEQ_AUGADD, SEQ_AUGERR,
       /* revision 8's R24 (the step-6 round): flag control, a quiet
        * region and a raise - see the block above seq_validate */
       SEQ_QUIET, SEQ_ENDQUIET, SEQ_RAISE };

/* R24: quiet regions nest four deep, as loops do, in a field of their
 * own; a raise reads rA[4:0] as the five flags and rA[7] as the mark. */
#define SEQ_MAX_QUIET    4
#define SEQ_RAISE_FLAGS  0x1Fu
#define SEQ_RAISE_MARK   7

/* Revision 8's post-step: imm[11:0] of an STX or LDX, twelve-bit two's
 * complement. imm[23:12] stays a field nothing reads. */
#define SEQ_STEP_MASK    0x00000FFFu

/* Indexed constants (`kx`, instruction bit 30). Which byte of `imm`
 * carries each operand's constant index. */
#define SEQ_KX_SHIFT_A   0
#define SEQ_KX_SHIFT_B   8
#define SEQ_KX_SHIFT_C  16
#define SEQ_KX_INDICES   0x00FFFFFFu   /* imm[23:0]: the three indices */

/* Five-bit register fields (revision 2). imm[24] is rd's fifth bit,
 * imm[25] ra's, imm[26] rb's, imm[27] rc's - the destination first,
 * then the operands in their own order. imm[31:28] is what is left of
 * the byte `kx` reserved, and stays reserved-must-be-zero so a
 * counter-indexed form can still have it. */
#define SEQ_REGHI_SHIFT  24
#define SEQ_REGHI_MASK   0x0F000000u

/* The ninth constant-index bits (revision 3, R7). Under `kx`, imm[28],
 * imm[29] and imm[30] are the high bits of ka's, kb's and kc's indices
 * - the same construction as the fifth register bits in imm[27:24],
 * one nibble up - and the bank becomes 512. imm[31] STAYS
 * reserved-must-be-zero: it is the cheap version guard for whatever
 * comes after this, and the largest index the corpus needs is 464. */
#define SEQ_KX9_SHIFT    28
#define SEQ_KX9_MASK     0x70000000u
#define SEQ_IMM_RESERVED 0x80000000u

/* The header's flags word, which was reserved[0] until 2026-09-08.
 * This is the mask of every bit this library IMPLEMENTS - not every bit
 * cft.h defines, which is a different and larger thing whenever a flag
 * has been assigned a number before the code to honour it exists. A set
 * bit outside this mask is CFT_ERR_ARTIFACT.
 *
 * Do not list the members in prose here. The comment that did say them
 * named two of three by 2026-09-11, which is how the flag list came to
 * be written out by hand in nine places at three different revisions;
 * host/include/cft_seq_flags.h renders the names from whatever mask you
 * hand it. */
#define SEQ_FLAGS_KNOWN  ((uint32_t)CFT_PROG_FLAG_BANK_EXT | \
                          (uint32_t)CFT_PROG_FLAG_SCRATCH_IO | \
                          (uint32_t)CFT_PROG_FLAG_SCRATCH_STRICT)

struct cft_program {
    cft_device         *dev;
    const cft_fmt_desc *f;
    int                 fmt_code;
    uint32_t            max_deposits;
    uint32_t            n_insns;
    uint32_t            n_consts;
    uint32_t            flags;
    /* The header's second word, which was reserved[1] until revision
     * 3: the per-run scratch block's two halves, zero unless
     * CFT_PROG_FLAG_SCRATCH_IO is set. */
    uint32_t            n_scratch_in;
    uint32_t            n_scratch_out;
    /* What the INSTRUCTIONS touch: one past the highest static STL or
     * LDL slot, or the whole depth when STX/LDX is used, whose slot is
     * not known until the run. A different question from the two
     * above, which is why it is a third field and not a maximum of
     * them. */
    uint32_t            scratch_used;
    /* Whether this run needs a scratch memory at all - any of the four
     * codes, or a declared block. Kept because the executor allocates
     * scratch_depth slots a lane and a program that never touches one
     * should not pay four megabytes a run for the possibility. */
    int                 scratch_active;
    /* The depth this program is held to and, on a software handle, runs
     * at (revision 7): the one the handle published when it was loaded -
     * 256 unless the handle was opened at another - or this library's
     * own default where a device published none. The modulus a
     * non-strict STX/LDX reduces by is scratch_depth and the range a
     * strict one is reported past is 2^scratch_log2, the same number. */
    uint32_t            scratch_depth;
    int                 scratch_log2;
    uint64_t           *insns;
    /* The program's own constants, or NULL under BANK_EXT - where
     * n_consts still says how many the program ADDRESSES and every run
     * supplies them. The bounds check on an index is the same either
     * way, which is the point of keeping n_consts meaningful. */
    cft_bn             *consts;
    /* The exact bytes that were loaded, kept whole.
     *
     * A device is given the IMAGE, not this parsed form - "the same
     * bytes on disk, in this call, and in the device's instruction
     * memory" is what makes a readback able to attest what ran, and
     * re-serialising from the fields above would be a second encoder
     * to keep in step with the first. A program is a hundred bytes or
     * so, so the copy costs nothing worth counting. */
    uint8_t            *image;
    size_t              image_bytes;
};

/* The four-bit fields stay four-bit fields here, and the fifth bits
 * are kept beside them rather than folded in.
 *
 * That is not tidiness. A field is read TWICE and means different
 * things: as a register number it is five bits wide, and as a constant
 * index (its `k` bit set, no `kx`) it is the four-bit field alone and
 * the fifth bit is a reserved bit that must be zero. Folding them
 * would make the reserved-bit check and the index check reach for the
 * same variable and one of them would be wrong. seq_reg() below is the
 * only place the two halves are joined. */
typedef struct {
    int      op, rd, ra, rb, rc, rnd;
    int      hd, ha, hb, hc;    /* imm[27:24], the fields' fifth bits */
    int      k9a, k9b, k9c;     /* imm[30:28], the indices' ninth bits */
    int      ka, kb, kc, kx, ctrl;
    uint32_t imm;
} seq_insn;

static void seq_decode(uint64_t w, seq_insn *d)
{
    d->op   = (int)(w & 0xFF);
    d->rd   = (int)((w >> 8) & 0xF);
    d->ra   = (int)((w >> 12) & 0xF);
    d->rb   = (int)((w >> 16) & 0xF);
    d->rc   = (int)((w >> 20) & 0xF);
    d->rnd  = (int)((w >> 24) & 0x7);
    d->ka   = (int)((w >> 27) & 1);
    d->kb   = (int)((w >> 28) & 1);
    d->kc   = (int)((w >> 29) & 1);
    d->kx   = (int)((w >> 30) & 1);
    d->ctrl = (int)((w >> 31) & 1);
    d->imm  = (uint32_t)((w >> 32) & 0xFFFFFFFFu);
    d->hd   = (int)((d->imm >> (SEQ_REGHI_SHIFT + 0)) & 1);
    d->ha   = (int)((d->imm >> (SEQ_REGHI_SHIFT + 1)) & 1);
    d->hb   = (int)((d->imm >> (SEQ_REGHI_SHIFT + 2)) & 1);
    d->hc   = (int)((d->imm >> (SEQ_REGHI_SHIFT + 3)) & 1);
    d->k9a  = (int)((d->imm >> (SEQ_KX9_SHIFT + 0)) & 1);
    d->k9b  = (int)((d->imm >> (SEQ_KX9_SHIFT + 1)) & 1);
    d->k9c  = (int)((d->imm >> (SEQ_KX9_SHIFT + 2)) & 1);
}

/* A five-bit register number from its two halves. */
static int seq_reg(int lo, int hi)
{
    return lo | (hi << 4);
}

/* The index operand `which` (0 = a, 1 = b, 2 = c) names, and whether
 * it is a constant. A port of seq.py's sources().
 *
 * Without `kx` an operand's 4-bit field is a register number, or a
 * constant index when its `k` bit is set - sixteen addressable
 * constants whatever the header says, which is the wall docs/ENCLOSE.md
 * hit. With `kx` the constant indices come from imm[7:0], imm[15:8]
 * and imm[23:16] instead, with imm[28], imm[29] and imm[30] as their
 * ninth bits since revision 3, so they reach 511; an operand whose `k`
 * bit is clear still names a register through its own field.
 *
 * A REGISTER operand is five bits wide since revision 2 and a CONSTANT
 * index is nine since revision 3: the fifth register bit belongs to
 * the register form only, and on a constant operand it is a reserved
 * bit seq_check_operands refuses; the ninth index bit belongs to the
 * `kx` constant form only, and anywhere else it is a reserved bit the
 * same function refuses. So the two returns differ in width on
 * purpose, and each width has exactly one place it is legal. */
static int seq_source(const seq_insn *d, int which, int *is_const)
{
    static const int shift[3] = { SEQ_KX_SHIFT_A, SEQ_KX_SHIFT_B,
                                  SEQ_KX_SHIFT_C };
    const int reg[3] = { d->ra, d->rb, d->rc };
    const int hi[3]  = { d->ha, d->hb, d->hc };
    const int k9[3]  = { d->k9a, d->k9b, d->k9c };
    const int kf[3]  = { d->ka, d->kb, d->kc };

    *is_const = kf[which];
    if (!kf[which])
        return seq_reg(reg[which], hi[which]);
    if (d->kx)
        return (int)((d->imm >> shift[which]) & 0xFFu) | (k9[which] << 8);
    return reg[which];
}

static uint32_t rd_le32(const uint8_t *p)
{
    return (uint32_t)p[0] | ((uint32_t)p[1] << 8) |
           ((uint32_t)p[2] << 16) | ((uint32_t)p[3] << 24);
}

static uint64_t rd_le64(const uint8_t *p)
{
    return (uint64_t)rd_le32(p) | ((uint64_t)rd_le32(p + 4) << 32);
}

/* The operand half of an ALU instruction's refusals: every constant
 * index is inside the bank, and the encoding of those indices is the
 * only one that spells this operation. A port of seq.py's
 * _check_operands(), which carries the argument at length.
 *
 * The canonicity rule is the one docs/SEQUENCER.md already states -
 * any field an instruction does not read being non-zero is refused -
 * applied to the fields `kx` and the five-bit register fields bring
 * into play. Without `kx` an ALU instruction reads nothing of `imm`
 * but the four register high bits. With it: an operand whose `k` bit
 * is set takes its index from `imm`, so its 4-bit field must be zero;
 * an operand whose `k` bit is clear names a register, so its byte of
 * `imm` must be zero; and `kx` itself selects nothing when no operand
 * names a constant, which would leave the instruction with a second
 * encoding.
 *
 * Revision 2 adds two applications of the same rule and no new rule.
 * imm[31:28] is read by nothing and must be zero - it is what is left
 * of the byte `kx` reserved whole. And an operand whose `k` bit is set
 * names a CONSTANT, whose index is four bits or a byte of `imm` and
 * never five bits, so that operand's register high bit is not read and
 * must be zero - under `kx` as well, where the index is the immediate
 * byte and the high bit is still not read. rd is always a register, so
 * imm[24] is always read and never constrained.
 *
 * Revision 3 takes three of those four remaining bits and applies the
 * rule to them too. imm[28], imm[29] and imm[30] are the ninth bits of
 * ka's, kb's and kc's constant indices, and each is read ONLY under
 * `kx` and only for an operand whose `k` flag is set - so on an
 * instruction without `kx`, or for an operand that names a register,
 * or in the four-bit constant form, it is a field nothing reads and
 * must be zero. imm[31] alone is left, and stays reserved-must-be-zero
 * as the version guard for whatever comes next.
 *
 * Each refusal says which rule, naming the instruction, its opcode, the
 * operand and the field, in the meaning of the ProgramError seq.py
 * raises for it. Until 2026-09-30 all nine returned
 * CFT_ERR_INVALID_ARGUMENT with no sentence at all. */
static cft_status seq_check_operands(const cft_program *p,
                                     const seq_insn *d, uint32_t pc)
{
    static const int shift[3] = { SEQ_KX_SHIFT_A, SEQ_KX_SHIFT_B,
                                  SEQ_KX_SHIFT_C };
    static const char *const opnd[3] = { "ra", "rb", "rc" };
    const int reg[3] = { d->ra, d->rb, d->rc };
    const int hi[3]  = { d->ha, d->hb, d->hc };
    const int k9[3]  = { d->k9a, d->k9b, d->k9c };
    const int kf[3]  = { d->ka, d->kb, d->kc };
    const unsigned long at = (unsigned long)pc;
    const char *name = cft_op_name((cft_op)d->op);
    int which;

    if (d->imm & SEQ_IMM_RESERVED) {
        cft_set_error("instruction %lu (%s, opcode %d): imm[31] is "
                      "reserved and must be zero, and it is set",
                      at, name, d->op);
        return CFT_ERR_INVALID_ARGUMENT;
    }
    if (d->kx) {
        if (!(d->ka || d->kb || d->kc)) {
            cft_set_error("instruction %lu (%s, opcode %d) sets kx and no "
                          "operand names a constant, so the bit selects "
                          "nothing and the instruction has a second "
                          "encoding with kx clear", at, name, d->op);
            return CFT_ERR_INVALID_ARGUMENT;
        }
    } else if (d->imm & SEQ_KX_INDICES) {
        cft_set_error("instruction %lu (%s, opcode %d) has no kx, so it "
                      "reads no immediate: imm[23:0] must be zero, and it "
                      "is 0x%06lx", at, name, d->op,
                      (unsigned long)(d->imm & SEQ_KX_INDICES));
        return CFT_ERR_INVALID_ARGUMENT;
    }
    if (!d->kx && (d->imm & SEQ_KX9_MASK)) {
        cft_set_error("instruction %lu (%s, opcode %d) has no kx, so the "
                      "ninth constant-index bits imm[30:28] are read by "
                      "nothing and must be zero, and they are 0x%lx",
                      at, name, d->op,
                      (unsigned long)((d->imm & SEQ_KX9_MASK) >>
                                      SEQ_KX9_SHIFT));
        return CFT_ERR_INVALID_ARGUMENT;
    }

    for (which = 0; which < 3; which++) {
        uint32_t byte = (d->imm >> shift[which]) & 0xFFu;
        uint32_t idx;
        if (kf[which] && hi[which]) {
            cft_set_error("instruction %lu (%s, opcode %d): %s names a "
                          "constant, so its register high bit imm[%d] is "
                          "read by nothing and must be zero", at, name,
                          d->op, opnd[which], SEQ_REGHI_SHIFT + 1 + which);
            return CFT_ERR_INVALID_ARGUMENT;
        }
        /* The ninth bit is read under `kx` for a constant operand and
         * nowhere else, so everywhere else it must be zero. Without
         * `kx` the test above has already refused it, so what reaches
         * here is an operand under `kx` that names a register. */
        if (!(d->kx && kf[which]) && k9[which]) {
            cft_set_error("instruction %lu (%s, opcode %d): %s names a "
                          "register, so its ninth constant-index bit "
                          "imm[%d] is read by nothing and must be zero",
                          at, name, d->op, opnd[which],
                          SEQ_KX9_SHIFT + which);
            return CFT_ERR_INVALID_ARGUMENT;
        }
        if (d->kx && kf[which]) {
            idx = byte | ((uint32_t)k9[which] << 8);
            if (reg[which]) {
                cft_set_error("instruction %lu (%s, opcode %d): %s names "
                              "constant %lu through imm under kx, so the %s "
                              "field must be zero, and it is %d", at, name,
                              d->op, opnd[which], (unsigned long)idx,
                              opnd[which], reg[which]);
                return CFT_ERR_INVALID_ARGUMENT;
            }
        } else if (d->kx) {
            if (byte) {
                cft_set_error("instruction %lu (%s, opcode %d): %s names a "
                              "register under kx, so its byte of imm, "
                              "imm[%d:%d], is read by nothing and must be "
                              "zero, and it is 0x%02lx", at, name, d->op,
                              opnd[which], shift[which] + 7, shift[which],
                              (unsigned long)byte);
                return CFT_ERR_INVALID_ARGUMENT;
            }
            continue;
        } else if (kf[which]) {
            idx = (uint32_t)reg[which];
        } else {
            continue;
        }
        if (idx >= p->n_consts) {
            cft_set_error("instruction %lu (%s, opcode %d): %s names "
                          "constant %lu, and the program's header declares "
                          "%lu (n_consts), indexed from 0", at, name, d->op,
                          opnd[which], (unsigned long)idx,
                          (unsigned long)p->n_consts);
            return CFT_ERR_INVALID_ARGUMENT;
        }
    }
    return CFT_OK;
}

/* ---- revision 8 (proposed 2026-09-29), docs/SEQUENCER.md -----------
 *
 * Defined golden-first in python/cft_golden/seq.py; ported here, and held
 * to it by host/tests/seq_check.py's sixth corpus. Kept in functions of
 * their own, so that what the rest of this file does is unchanged for
 * every program that uses neither:
 *
 *   augadd rD, rA, rB  (code 10)  rD := r of 754-2019 9.5's
 *   augerr rD, rA, rB  (code 11)  augmentedAddition(rA, rB), or e -
 *                                 computed by augmented.c's own lane
 *                                 function, raising that operation's
 *                                 flags;
 *   stx/ldx ..., step              after the access, rb := rb + step
 *                                 modulo 2^width, the step a signed
 *                                 twelve-bit imm[11:0], except an LDX
 *                                 into rb itself, which keeps what it
 *                                 loaded (CORE-V XCVmem). Zero is the
 *                                 instruction as it always was.
 *
 * And the step-6 round's R23 and R24 (2026-10-02, ABI 0.17), held to the
 * model by seq_check.py's flag-control corpus:
 *
 *   quiet       (code 12)  open a quiet region; endquiet (13) closes the
 *                          innermost. Inside one, the five IEEE flags of
 *                          every instruction - ALU, augadd/augerr, and a
 *                          raise's own - reach neither the run's flags nor
 *                          a lane's byte (754-2019 5.7.4's saveAllFlags
 *                          and restoreFlags). Regions nest four deep and
 *                          properly with loops, so the depth at an
 *                          instruction is a function of where it stands;
 *   raise rA    (code 14)  for every active lane, rA[4:0] ORed into the
 *                          flags and the lane's byte outside a region,
 *                          and rA[7] MARKS the lane - CFT_STATUS_MARKED,
 *                          CFT_LANE_MARKED - anywhere. Nothing else of
 *                          rA is read;
 *   the byte    R23's, one a lane: [4:0] its flags outside every region,
 *               [5] its deposit overflow, [6] its strict fault, [7] its
 *               mark - written to cft_run_args.lane_flags, for the lanes
 *               the caller has, where the caller asks for it. */

/* The signed post-step an STX or LDX carries, or 0 - and 0 for STL and
 * LDL, whose imm[23:0] is a slot and not a step. */
static int seq_step(const seq_insn *d)
{
    int s;
    if (!d->ctrl || (d->op != SEQ_STX && d->op != SEQ_LDX))
        return 0;
    s = (int)(d->imm & SEQ_STEP_MASK);
    return (s & 0x800) ? s - 0x1000 : s;
}

/* An LDX that loads into its own stepped index: both writes would land in
 * one register, and RISC-V's post-increment loads say which wins (CORE-V
 * XCVmem: "When same register is used as address and destination (rD ==
 * rs1) for post-incremented loads, loaded data has highest priority over
 * incremented address when writing to this same register"). So the
 * loaded value is kept and the step discarded - rung 2 of Logan's rule.
 * STX with ra == rb has one register write, the step's, and keeps it. */
static int seq_step_discarded(const seq_insn *d)
{
    return d->op == SEQ_LDX &&
           seq_reg(d->rd, d->hd) == seq_reg(d->rb, d->hb);
}

/* The highest register augadd or augerr names, for the REGS32 check. */
static int seq_augadd_highest(const seq_insn *d)
{
    int r = seq_reg(d->rd, d->hd);
    if (seq_reg(d->ra, d->ha) > r) r = seq_reg(d->ra, d->ha);
    if (seq_reg(d->rb, d->hb) > r) r = seq_reg(d->rb, d->hb);
    return r;
}

/* Revision 8 against the device, BY NAME. Every tile built so far reads
 * CAPS2[11], [12] and [14] as zero: it decodes codes 10 to 14 as HALT,
 * and it never reads imm on STX/LDX, so it would access without stepping
 * - none of them a fault it could raise. So each is refused here, before
 * the register map is touched, naming the instruction and the bit. */
static cft_status seq_rev8_against_device(const cft_seq_caps *c,
                                          const seq_insn *d, uint32_t pc)
{
    int step = seq_step(d);
    if ((d->op == SEQ_AUGADD || d->op == SEQ_AUGERR) &&
        !(c->features & CFT_SEQ_FEAT_AUGADD)) {
        cft_set_error("instruction %lu is %s - 754-2019 9.5's "
                      "augmentedAddition, revision 8 - and this device does "
                      "not publish it (CAPS2[11] clear, cft_caps."
                      "seq_features bit 15 - CFT_SEQ_FEAT_AUGADD); a tile "
                      "without it decodes the code as HALT",
                      (unsigned long)pc,
                      d->op == SEQ_AUGADD ? "AUGADD" : "AUGERR");
        return CFT_ERR_UNSUPPORTED;
    }
    if (step && !(c->features & CFT_SEQ_FEAT_SCRATCH_STEP)) {
        cft_set_error("instruction %lu is %s with a post-step of %+d "
                      "(revision 8) and this device does not publish it "
                      "(CAPS2[12] clear, cft_caps.seq_features bit 16 - "
                      "CFT_SEQ_FEAT_SCRATCH_STEP); a tile without it would "
                      "access the slot and never step the index",
                      (unsigned long)pc,
                      d->op == SEQ_STX ? "STX" : "LDX", step);
        return CFT_ERR_UNSUPPORTED;
    }
    if ((d->op == SEQ_QUIET || d->op == SEQ_ENDQUIET ||
         d->op == SEQ_RAISE) &&
        !(c->features & CFT_SEQ_FEAT_FLAG_CONTROL)) {
        cft_set_error("instruction %lu is %s - revision 8's flag control, "
                      "R24 - and this device does not publish it (CAPS2[14] "
                      "clear, cft_caps.seq_features bit 18 - "
                      "CFT_SEQ_FEAT_FLAG_CONTROL); a tile without it "
                      "decodes the code as HALT", (unsigned long)pc,
                      d->op == SEQ_QUIET    ? "QUIET"
                      : d->op == SEQ_ENDQUIET ? "ENDQUIET" : "RAISE");
        return CFT_ERR_UNSUPPORTED;
    }
    return CFT_OK;
}

/* What each control code READS, and so the only fields it may set: the
 * canonicity rule docs/SEQUENCER.md states - any field an instruction
 * does not read being non-zero is refused - as seq.py writes it, in
 * `used` and IMM_ALLOWED. Fields a control instruction does not read
 * must be zero so that one operation has one encoding; otherwise a
 * readback hash is not a hash of the program.
 *
 * One table decides the refusal AND names it, so the two cannot
 * disagree about which field it was. Until 2026-09-30 a condition per
 * code decided, the same fields exactly, and none said which. A code
 * with no row here is unknown and refused as unknown, so a code added to
 * the enum above without a row stays refused rather than accepted.
 *
 * `regs` is the operand fields a code reads as the ENCODING holds them,
 * four bits each (SEQ_F_RD for rd, and so on); their fifth bits live in
 * imm[27:24] and are held through `imm`. That is what REPEAT needs: it
 * reads its `imm` entirely, as the trip count - it always has - so
 * `repeat 0xffffffff` sets all four high bits and names no register, and
 * the canonicity rule, which is about fields an instruction does not
 * read, reaches nothing there. Constraining imm[27:24] on a REPEAT would
 * refuse every trip count at or above 2^24, including the
 * `repeat 0xffffffff` docs/SEQUENCER.md's own worst-case paragraph relies
 * on being loadable and refused by the 2^40 bound instead.
 * docs/HOSTAPI.md records the reading.
 *
 * DEPOSIT and SETACT read `ra`, so of the four high bits only imm[25],
 * ra's - the single relaxation revision 2 made here: their `imm` was
 * required to be zero whole and is now zero but for that bit. HALT,
 * ENDREP and ACTALL read no field of `imm` at all.
 *
 * The four scratch codes of revision 3, R4, add no rule: STL reads `ra`
 * and imm[23:0], its slot; LDL writes `rd` and reads imm[23:0]; STX reads
 * `ra` and `rb`; LDX writes `rd` and reads `rb`. For those last two
 * imm[23:0] was a field nothing read until revision 8 (proposed
 * 2026-09-29) made imm[11:0] their post-step (SEQ_STEP_MASK), so now
 * imm[23:12] is the part nothing reads. The slot of a static form is
 * checked against the DEVICE's depth rather than here, exactly as a
 * constant index is: what bounds it is a capacity a tile publishes, not
 * a property of the encoding.
 *
 * augadd and augerr (revision 8) read ra and rb and write rd, five bits
 * each. Every other field is unread and must be zero: rc and its high
 * bit, rnd (9.5 fixes the rounding, so no attribute can be spelled),
 * imm[23:0] and imm[31:28].
 *
 * R24's quiet and endquiet read nothing, as HALT does; its raise reads
 * `ra` alone, as SETACT does, so imm[25] and nothing else of imm.
 *
 * No control code reads rnd, a `k` flag or `kx`: none reads a rounding
 * attribute (augadd and augerr round, at the one rounding 9.5 fixes),
 * and none reads the constant bank. */
#define SEQ_F_RD   1u
#define SEQ_F_RA   2u
#define SEQ_F_RB   4u
#define SEQ_F_RC   8u
#define SEQ_HI_RD  ((uint32_t)1u << (SEQ_REGHI_SHIFT + 0))
#define SEQ_HI_RA  ((uint32_t)1u << (SEQ_REGHI_SHIFT + 1))
#define SEQ_HI_RB  ((uint32_t)1u << (SEQ_REGHI_SHIFT + 2))

static const struct {
    const char *name;
    unsigned    regs;       /* SEQ_F_: the operand fields it reads */
    uint32_t    imm;        /* the bits of imm it reads */
} seq_ctrl[] = {
    [SEQ_HALT]    = { "HALT",    0,        0 },
    [SEQ_REPEAT]  = { "REPEAT",  0,        0xFFFFFFFFu },
    [SEQ_ENDREP]  = { "ENDREP",  0,        0 },
    [SEQ_DEPOSIT] = { "DEPOSIT", SEQ_F_RA, SEQ_HI_RA },
    [SEQ_SETACT]  = { "SETACT",  SEQ_F_RA, SEQ_HI_RA },
    [SEQ_ACTALL]  = { "ACTALL",  0,        0 },
    [SEQ_STL]     = { "STL",     SEQ_F_RA, SEQ_KX_INDICES | SEQ_HI_RA },
    [SEQ_LDL]     = { "LDL",     SEQ_F_RD, SEQ_KX_INDICES | SEQ_HI_RD },
    [SEQ_STX]     = { "STX",     SEQ_F_RA | SEQ_F_RB,
                      SEQ_HI_RA | SEQ_HI_RB | SEQ_STEP_MASK },
    [SEQ_LDX]     = { "LDX",     SEQ_F_RD | SEQ_F_RB,
                      SEQ_HI_RD | SEQ_HI_RB | SEQ_STEP_MASK },
    [SEQ_AUGADD]  = { "AUGADD",  SEQ_F_RD | SEQ_F_RA | SEQ_F_RB,
                      SEQ_HI_RD | SEQ_HI_RA | SEQ_HI_RB },
    [SEQ_AUGERR]  = { "AUGERR",  SEQ_F_RD | SEQ_F_RA | SEQ_F_RB,
                      SEQ_HI_RD | SEQ_HI_RA | SEQ_HI_RB },
    [SEQ_QUIET]    = { "QUIET",    0,        0 },
    [SEQ_ENDQUIET] = { "ENDQUIET", 0,        0 },
    [SEQ_RAISE]    = { "RAISE",    SEQ_F_RA, SEQ_HI_RA }
};
#define SEQ_NCTRL  ((int)(sizeof seq_ctrl / sizeof seq_ctrl[0]))

/* A known control instruction's fields against its row: CFT_OK, or the
 * first field it sets and does not read, by name - seq.py's order, the
 * operand fields, then rnd, the `k` flags and `kx`, then imm. */
static cft_status seq_ctrl_fields(const seq_insn *d, uint32_t pc)
{
    static const char *const regname[4]  = { "rd", "ra", "rb", "rc" };
    static const char *const flagname[4] = { "ka", "kb", "kc", "kx" };
    const int regs[4]  = { d->rd, d->ra, d->rb, d->rc };
    const int flags[4] = { d->ka, d->kb, d->kc, d->kx };
    const unsigned long at = (unsigned long)pc;
    const char *name = seq_ctrl[d->op].name;
    const uint32_t reads = seq_ctrl[d->op].imm;
    int f;

    for (f = 0; f < 4; f++)
        if (regs[f] && !(seq_ctrl[d->op].regs & (1u << f))) {
            cft_set_error("instruction %lu is %s, which does not read %s, "
                          "so it must be zero, and it is %d", at, name,
                          regname[f], regs[f]);
            return CFT_ERR_INVALID_ARGUMENT;
        }
    if (d->rnd) {
        cft_set_error("instruction %lu is %s, which does not read rnd - no "
                      "control code reads a rounding attribute - so it must "
                      "be zero, and it is "
                      "%d", at, name, d->rnd);
        return CFT_ERR_INVALID_ARGUMENT;
    }
    for (f = 0; f < 4; f++)
        if (flags[f]) {
            cft_set_error("instruction %lu is %s, which does not read %s - "
                          "no control code reads the constant bank - so it "
                          "must be clear, and it is set", at, name,
                          flagname[f]);
            return CFT_ERR_INVALID_ARGUMENT;
        }
    if (d->imm & ~reads) {
        cft_set_error("instruction %lu is %s, which reads only imm & "
                      "0x%08lx, so imm = 0x%08lx sets a bit it does not "
                      "read", at, name, (unsigned long)reads,
                      (unsigned long)d->imm);
        return CFT_ERR_INVALID_ARGUMENT;
    }
    return CFT_OK;
}

/* Everything docs/SEQUENCER.md says the loader refuses. A program that
 * a device could execute ambiguously is stopped here, so the hardware
 * never has to decide what an ambiguous one means.
 *
 * Every refusal names the instruction and the rule it broke, in the
 * meaning of the ProgramError seq.py's validate() raises for it (the
 * words differ); until 2026-09-30 none did. */
static cft_status seq_validate(const cft_program *p)
{
    uint32_t pc;
    int depth = 0;
    /* how many times an instruction at the current nesting level can
     * execute, so the worst case is known before the run rather than
     * discovered by waiting for it */
    uint64_t mult[SEQ_MAX_DEPTH + 1];
    uint64_t worst = 0;
    int top = 0;
    /* R24: every bracket open, loops and quiet regions together,
     * innermost last, with the instruction each opened at - so that the
     * two kinds nest properly within each other (a region opened in a
     * loop body closes in that body; one opened outside a loop closes
     * outside it), which makes whether an instruction is quiet a property
     * of where it stands. The depth checks below bound the stack. */
    int bkind[SEQ_MAX_DEPTH + SEQ_MAX_QUIET];
    uint32_t bpc[SEQ_MAX_DEPTH + SEQ_MAX_QUIET];
    int nb = 0, qdepth = 0;

    mult[0] = 1;
    for (pc = 0; pc < p->n_insns; pc++) {
        seq_insn d;
        cft_status ost;
        seq_decode(p->insns[pc], &d);

        worst += mult[top];
        if (worst > SEQ_MAX_INSNS) {
            cft_set_error("instruction %lu takes the program's worst-case "
                          "instruction count to %llu, past the bound of "
                          "%llu (2^40): its loops are finite but not a "
                          "bound", (unsigned long)pc,
                          (unsigned long long)worst,
                          (unsigned long long)SEQ_MAX_INSNS);
            return CFT_ERR_INVALID_ARGUMENT;
        }

        if (!d.ctrl) {
            ost = seq_check_operands(p, &d, pc);
            if (ost != CFT_OK)
                return ost;
            if (d.rnd > 4) {
                cft_set_error("instruction %lu (%s, opcode %d): its "
                              "rounding attribute rnd is %d, and the "
                              "contract defines 0 to 4 - the rest are "
                              "reserved", (unsigned long)pc,
                              cft_op_name((cft_op)d.op), d.op, d.rnd);
                return CFT_ERR_INVALID_ARGUMENT;
            }
            continue;
        }

        /* A control code, held to its row of seq_ctrl above - which
         * says, per code, which fields it reads and why. */
        if (d.op >= SEQ_NCTRL) {
            cft_set_error("instruction %lu is control code %d, and the "
                          "control codes are 0 to %d (HALT to %s): an "
                          "unknown one is refused, not guessed at",
                          (unsigned long)pc, d.op, SEQ_NCTRL - 1,
                          seq_ctrl[SEQ_NCTRL - 1].name);
            return CFT_ERR_INVALID_ARGUMENT;
        }
        ost = seq_ctrl_fields(&d, pc);
        if (ost != CFT_OK)
            return ost;

        if (d.op == SEQ_REPEAT) {
            if (d.imm == 0) {
                cft_set_error("instruction %lu is REPEAT 0, which is not a "
                              "loop; omit it", (unsigned long)pc);
                return CFT_ERR_INVALID_ARGUMENT;
            }
            if (depth >= SEQ_MAX_DEPTH) {
                cft_set_error("instruction %lu is a REPEAT inside %d open "
                              "loops, and loops nest at most %d deep",
                              (unsigned long)pc, depth, SEQ_MAX_DEPTH);
                return CFT_ERR_INVALID_ARGUMENT;
            }
            depth++;
            top++;
            /* Checked BEFORE the product is taken, not after: mult and
             * imm are both 64 bits, and a product past 2^64 wraps to a
             * small number that passes an "> SEQ_MAX_INSNS" test. That
             * let `repeat 2^16 / repeat 2^17 / repeat 2^31` - 2^64
             * iterations - through this loader while seq.py, whose
             * integers do not wrap, refused it (host/fuzz,
             * 2026-09-07). mult[top - 1] is at least 1, so the
             * division is safe, and imm > MAX / mult is exactly
             * mult * imm > MAX - which is why the sentence names the
             * two factors and not their product. */
            if (d.imm > SEQ_MAX_INSNS / mult[top - 1]) {
                cft_set_error("instruction %lu is REPEAT %lu inside loops "
                              "that already run their body %llu times: the "
                              "product is past %llu (2^40), the bound on a "
                              "program's worst-case instruction count, so "
                              "its loops are finite but not a bound",
                              (unsigned long)pc, (unsigned long)d.imm,
                              (unsigned long long)mult[top - 1],
                              (unsigned long long)SEQ_MAX_INSNS);
                return CFT_ERR_INVALID_ARGUMENT;
            }
            mult[top] = mult[top - 1] * d.imm;
            bkind[nb] = SEQ_REPEAT;
            bpc[nb++] = pc;
        } else if (d.op == SEQ_ENDREP) {
            if (depth == 0) {
                cft_set_error("instruction %lu is an ENDREP with no REPEAT "
                              "open", (unsigned long)pc);
                return CFT_ERR_INVALID_ARGUMENT;
            }
            if (bkind[nb - 1] != SEQ_REPEAT) {
                cft_set_error("instruction %lu is an ENDREP that closes its "
                              "loop while the quiet region opened at "
                              "instruction %lu is open: a region opened in a "
                              "loop body closes in that body",
                              (unsigned long)pc, (unsigned long)bpc[nb - 1]);
                return CFT_ERR_INVALID_ARGUMENT;
            }
            nb--;
            depth--;
            top--;
        } else if (d.op == SEQ_QUIET) {
            if (qdepth >= SEQ_MAX_QUIET) {
                cft_set_error("instruction %lu is a QUIET inside %d open "
                              "quiet regions, and regions nest at most %d "
                              "deep", (unsigned long)pc, qdepth,
                              SEQ_MAX_QUIET);
                return CFT_ERR_INVALID_ARGUMENT;
            }
            qdepth++;
            bkind[nb] = SEQ_QUIET;
            bpc[nb++] = pc;
        } else if (d.op == SEQ_ENDQUIET) {
            if (qdepth == 0) {
                cft_set_error("instruction %lu is an ENDQUIET with no quiet "
                              "region open", (unsigned long)pc);
                return CFT_ERR_INVALID_ARGUMENT;
            }
            if (bkind[nb - 1] != SEQ_QUIET) {
                cft_set_error("instruction %lu is an ENDQUIET inside the loop "
                              "opened at instruction %lu, around a region "
                              "opened outside it: a region opened outside a "
                              "loop closes outside it", (unsigned long)pc,
                              (unsigned long)bpc[nb - 1]);
                return CFT_ERR_INVALID_ARGUMENT;
            }
            nb--;
            qdepth--;
        } else if ((d.op == SEQ_ACTALL || d.op == SEQ_HALT) && depth > 0) {
            /* Both would make the all-lanes-done early exit
             * observable - ACTALL because it can reactivate a lane,
             * HALT because its effect is not per-lane and so the
             * active mask cannot gate it. */
            if (d.op == SEQ_ACTALL)
                cft_set_error("instruction %lu is ACTALL inside a loop, "
                              "where it could reactivate a lane and make "
                              "the all-lanes-done early exit observable",
                              (unsigned long)pc);
            else
                cft_set_error("instruction %lu is HALT inside a loop: the "
                              "active mask cannot gate it, so the "
                              "all-lanes-done early exit would be "
                              "observable", (unsigned long)pc);
            return CFT_ERR_INVALID_ARGUMENT;
        }
        /* R24. A region is 754-2019 5.7.4's save and its restore, and a
         * program that stops between them has two faithful readings - the
         * flags since the save stand, nothing having restored them, or
         * they never reached the flags - so it is refused rather than one
         * of them chosen. Every bracket open here is a region: a HALT in a
         * loop was refused above. */
        if (d.op == SEQ_HALT && qdepth > 0) {
            cft_set_error("instruction %lu is HALT inside the quiet region "
                          "opened at instruction %lu: a region is a save and "
                          "its restore, and a program cannot stop between "
                          "them", (unsigned long)pc,
                          (unsigned long)bpc[nb - 1]);
            return CFT_ERR_INVALID_ARGUMENT;
        }
    }
    if (depth != 0) {
        /* depth > 0 needs a REPEAT, so there is a last instruction */
        cft_set_error("the program ends, after instruction %lu, inside %d "
                      "open loop%s: every REPEAT needs its ENDREP",
                      (unsigned long)(p->n_insns - 1u), depth,
                      depth == 1 ? "" : "s");
        return CFT_ERR_INVALID_ARGUMENT;
    }
    if (qdepth != 0) {
        /* R24, for the reason a HALT inside a region is refused */
        cft_set_error("the program ends, after instruction %lu, inside %d "
                      "open quiet region%s, the innermost opened at "
                      "instruction %lu: every QUIET needs its ENDQUIET",
                      (unsigned long)(p->n_insns - 1u), qdepth,
                      qdepth == 1 ? "" : "s", (unsigned long)bpc[nb - 1]);
        return CFT_ERR_INVALID_ARGUMENT;
    }
    return CFT_OK;
}

/* The software backend's own sequencer capacities, for device.c to
 * publish. Defined here, where they are enforced, so that the number
 * a host is told and the number a program is held to are one
 * declaration. */
void cft_sw_seq_caps(cft_seq_caps *out)
{
    if (!out)
        return;
    out->max_deposits = SEQ_MAX_DEPOSITS;
    out->max_insns    = SEQ_IMAGE_INSNS;
    out->max_consts   = SEQ_ADDR_CONSTS;
    out->max_scratch  = SEQ_SCRATCH_D;
    /* This executor decodes kx (bit 30: 8-bit constant indices in the
     * immediate) with revision 3's ninth bits above them, gives every
     * lane the thirty-two registers of revision 2 and the private
     * scratch memory of revision 3, takes a constant bank and a
     * scratch block per run, and implements IMUL (opcode 30). The bit
     * assignments are rtl/cft_csr.sv's, surfaced by cft.h. Publishing
     * them here is what makes cft_program_load accept a program that
     * uses them on a software handle - the software backend is the
     * CONTRACT, so it carries every feature the contract defines. */
    out->features     = CFT_SEQ_FEAT_WIDE_CONST | CFT_SEQ_FEAT_REGS32 |
                        CFT_SEQ_FEAT_BANK_PTR   | CFT_SEQ_FEAT_KX9 |
                        CFT_ALU_EXT_IMUL        | CFT_SEQ_FEAT_SCRATCH |
                        CFT_SEQ_FEAT_SCRATCH_IO | CFT_SEQ_FEAT_SCRATCH_STRICT |
                        /* R16, ABI 0.14: this executor gathers an input
                         * block through its table, so it publishes the
                         * bit - the software backend is the contract and
                         * carries every feature the contract defines. A
                         * tile publishes it from CAPS2[9] and a tile
                         * without it is refused BY NAME (device.c). */
                        CFT_SEQ_FEAT_INDEXED |
                        /* R17, ABI 0.14, on exactly those terms: this
                         * executor honours a lane mask, so it publishes
                         * the bit, and a tile that does not carry
                         * CAPS2[10] is refused by name rather than
                         * handed a run it would compute over every
                         * lane. */
                        CFT_SEQ_FEAT_LANE_MASK;
    /* Revision 8 (proposed 2026-09-29), on the same terms: this executor
     * steps an STX/LDX index, and computes augadd/augerr wherever
     * augmented.c is compiled in - a -DCFT_NO_AUGMENTED build has no
     * augmentedAddition, so it leaves the bit clear and the loader refuses
     * the two codes by name there, as a tile without CAPS2[11] is. */
    out->features |= CFT_SEQ_FEAT_SCRATCH_STEP;
#ifndef CFT_NO_AUGMENTED
    out->features |= CFT_SEQ_FEAT_AUGADD;
#endif
    /* The step-6 round's R23 and R24 (ABI 0.17), on the same terms: this
     * executor keeps a byte a lane and writes it where a run asks, and it
     * runs quiet regions and raises - so a software handle's seq_features
     * is 0x7ff1f in a default build. */
    out->features |= CFT_SEQ_FEAT_LANE_FLAGS | CFT_SEQ_FEAT_FLAG_CONTROL;
    /* Not here, and not missing: CFT_SEQ_FEAT_SCALAR and
     * CFT_FEAT_REDUCE_SEG. The software backend publishes both (since
     * 2026-09-24), but they are features of device.c's elementwise path
     * and of cft_reduce_seg, which a -DCFT_NO_PROGRAM build keeps and
     * this file does not - so device.c's software open ORs them in after
     * this, in every build, from the constants its refusals read. */
}

/* A program image against the capacities the device it was loaded for
 * publishes. Zero is UNKNOWN in every field - only a remote server
 * whose caps block predates them produces one - and an unknown cap
 * enforces nothing, because refusing against a number nobody stated
 * would turn an old server into a broken one.
 *
 * The message names the cap, the program's value and the device's, in
 * that order, because the thing a caller has to change is the first
 * of the three. Before this existed the tile answered a program past
 * its cap with STATUS[3] and no explanation, and the library
 * answered with nothing at all: it accepted every one of them
 * (docs/studies/OPT-D-contract.md 0.1). */
static cft_status seq_check_caps(cft_device *dev, uint32_t n_insns,
                                 uint32_t maxdep)
{
    cft_seq_caps c;
    cft_device_seq_caps(dev, &c);
    if (c.max_deposits && maxdep > c.max_deposits)
        return (cft_status)cft_seq_cap_refusal(
            "max_deposits", maxdep, c.max_deposits,
            "deposit slots a lane", "max_deposits");
    if (c.max_insns && n_insns > c.max_insns)
        return (cft_status)cft_seq_cap_refusal(
            "instruction count", n_insns, c.max_insns,
            "instructions it can hold", "max_insns");
    return CFT_OK;
}

/* The instruction stream against the DEVICE: the features it uses and
 * the constant indices it carries.
 *
 * Separate from the header check above because these are properties of
 * the instruction stream rather than of the header: a program may
 * declare more constants than a device reaches - the rest are simply
 * unreachable - up to the 512 any instruction can, past which
 * cft_program_load refuses the header itself (on a tile built before
 * revision 3, whose bank is 256, a header of 257 to 512 still crosses
 * and is refused at the tile: a known limit, no such tile in use); and
 * what a device refuses to execute is a reference past its bank. That
 * refusal cannot fire on a device built so far: each publishes the
 * whole reach of the encoding it decodes - sixteen without kx, 256 with
 * it, and 512 with KX9, which is the software backend and every tile
 * since revision 3 - and an index past that reach is refused first, as
 * the feature it needs. It is real for a trimmed tile that publishes
 * fewer.
 *
 * A feature the device does not publish is ABSENT, not unknown, and
 * every one of these refusals exists because the DEVICE cannot make
 * it. An old bitstream's operand mux would read a kx instruction's
 * four-bit fields and compute on the wrong constants without a fault;
 * it would read a five-bit register's low four bits and address the
 * wrong register the same way; an integer group without IMUL answers
 * opcode 30 with the unassigned-opcode result. None of those is a
 * fault the tile can raise, so each is raised here, by name. */
static cft_status seq_check_against_device(cft_device *dev,
                                           const cft_program *p)
{
    cft_seq_caps c;
    uint32_t pc;
    cft_device_seq_caps(dev, &c);
    for (pc = 0; pc < p->n_insns; pc++) {
        seq_insn d;
        int idx = -1, reg = -1;
        seq_decode(p->insns[pc], &d);

        /* Control first, because six of the ten name a register too.
         * DEPOSIT, SETACT, STL and STX read `ra`, five bits wide since
         * revision 2; LDL and LDX write `rd`; STX and LDX also read
         * `rb`. HALT, REPEAT, ENDREP and ACTALL name no register at
         * all. */
        if (d.ctrl) {
            if (d.op == SEQ_DEPOSIT || d.op == SEQ_SETACT ||
                d.op == SEQ_STL     || d.op == SEQ_STX ||
                d.op == SEQ_RAISE)
                reg = seq_reg(d.ra, d.ha);
            if (d.op == SEQ_LDL || d.op == SEQ_LDX)
                reg = seq_reg(d.rd, d.hd);
            if ((d.op == SEQ_STX || d.op == SEQ_LDX) &&
                seq_reg(d.rb, d.hb) > reg)
                reg = seq_reg(d.rb, d.hb);
            /* The scratch memory itself, before the slot: a device
             * without it has no memory for any of the four codes to
             * reach, and no fault to raise when one does. */
            if (d.op == SEQ_STL || d.op == SEQ_LDL ||
                d.op == SEQ_STX || d.op == SEQ_LDX) {
                static const char *const nm[4] = { "STL", "LDL",
                                                   "STX", "LDX" };
                if (!(c.features & CFT_SEQ_FEAT_SCRATCH)) {
                    cft_set_error("instruction %lu is %s and this device "
                                  "has no per-lane scratch memory "
                                  "(CAPS2[4] clear, cft_caps.seq_features "
                                  "bit 8 - CFT_SEQ_FEAT_SCRATCH)",
                                  (unsigned long)pc, nm[d.op - SEQ_STL]);
                    return CFT_ERR_UNSUPPORTED;
                }
                /* A STATIC slot is held to the device's depth, by name,
                 * as a constant index past the bank is. An INDEXED one
                 * is not: docs/SEQUENCER.md makes the reduction modulo
                 * the depth part of the contract, so there is nothing
                 * out of range for it to be. */
                if ((d.op == SEQ_STL || d.op == SEQ_LDL) && c.max_scratch &&
                    (d.imm & SEQ_KX_INDICES) >= c.max_scratch)
                    return (cft_status)cft_seq_cap_refusal(
                        "scratch slot",
                        (unsigned long)(d.imm & SEQ_KX_INDICES),
                        (unsigned long)c.max_scratch - 1u,
                        "scratch slots a lane, indexed from 0",
                        "max_scratch");
            }
            /* Revision 8: the pair names three registers, and either
             * form needs its own bit - after the scratch, so a device
             * with no scratch at all is told that first. */
            if (d.op == SEQ_AUGADD || d.op == SEQ_AUGERR)
                reg = seq_augadd_highest(&d);
            {
                const cft_status r8 = seq_rev8_against_device(&c, &d, pc);
                if (r8 != CFT_OK)
                    return r8;
            }
        } else {
            if (d.kx && !(c.features & CFT_SEQ_FEAT_WIDE_CONST)) {
                cft_set_error("instruction %lu uses indexed constants (kx, "
                              "bit 30) and this device does not publish the "
                              "feature (CAPS[4] clear, cft_caps.seq_features "
                              "bit 0); build the program without kx",
                              (unsigned long)pc);
                return CFT_ERR_UNSUPPORTED;
            }
            /* The ninth index bits, and the reach they buy. A
             * revision-2 tile's operand mux reads EIGHT bits under kx
             * and would address the wrong constant in silence, so what
             * is refused is not the bit but the index: an index at or
             * past 256 on a device whose CAPS[7] is clear, by name.
             * The bit itself cannot be set without changing the index,
             * so the two refusals are the same refusal. */
            if (d.kx && !(c.features & CFT_SEQ_FEAT_KX9)) {
                int nine = -1;
                if (d.ka && d.k9a) nine = (int)((d.imm >> SEQ_KX_SHIFT_A)
                                                & 0xFFu) | 0x100;
                if (d.kb && d.k9b) nine = (int)((d.imm >> SEQ_KX_SHIFT_B)
                                                & 0xFFu) | 0x100;
                if (d.kc && d.k9c) nine = (int)((d.imm >> SEQ_KX_SHIFT_C)
                                                & 0xFFu) | 0x100;
                if (nine >= 0) {
                    cft_set_error("instruction %lu addresses constant %d and "
                                  "this device reads eight index bits under "
                                  "kx (CAPS[7] clear, cft_caps.seq_features "
                                  "bit 3 - CFT_SEQ_FEAT_KX9); its operand "
                                  "mux would address constant %d instead",
                                  (unsigned long)pc, nine, nine & 0xFF);
                    return CFT_ERR_UNSUPPORTED;
                }
            }
            if (d.op == 30 && !(c.features & CFT_ALU_EXT_IMUL)) {
                cft_set_error("instruction %lu is IMUL (opcode 30) and this "
                              "device does not implement it (CAPS[28] clear, "
                              "cft_caps.seq_features bit 4)",
                              (unsigned long)pc);
                return CFT_ERR_UNSUPPORTED;
            }
            /* The destination always names a register; a source does
             * unless its `k` bit redirects it at the constant bank. */
            reg = seq_reg(d.rd, d.hd);
            if (!d.ka && seq_reg(d.ra, d.ha) > reg) reg = seq_reg(d.ra, d.ha);
            if (!d.kb && seq_reg(d.rb, d.hb) > reg) reg = seq_reg(d.rb, d.hb);
            if (!d.kc && seq_reg(d.rc, d.hc) > reg) reg = seq_reg(d.rc, d.hc);
        }
        if (reg >= SEQ_NREG_NARROW &&
            !(c.features & CFT_SEQ_FEAT_REGS32)) {
            cft_set_error("instruction %lu names r%d and this device has "
                          "%d registers a lane (CAPS[5] clear, "
                          "cft_caps.seq_features bit 1 - "
                          "CFT_SEQ_FEAT_REGS32); its operand mux would read "
                          "the low four bits and address r%d instead",
                          (unsigned long)pc, reg, SEQ_NREG_NARROW,
                          reg & (SEQ_NREG_NARROW - 1));
            return CFT_ERR_UNSUPPORTED;
        }
        if (d.ctrl)
            continue;
        if (!c.max_consts)      /* unknown: nothing enforced */
            continue;
        /* The index is the four-bit field, or a byte of `imm` under
         * kx - and BOTH are held to the device's reach. The kx half
         * had no check until 2026-09-08 and could not fire while it
         * was missing (every device that publishes kx publishes the
         * whole 256-entry bank, and a byte cannot name more), but it
         * is the half a trimmed tile would need, and a rule that is
         * only unreachable is not a rule that is right. */
        if (d.kx) {
            uint32_t ia = (d.imm & 0xFFu)         | ((uint32_t)d.k9a << 8);
            uint32_t ib = ((d.imm >> 8) & 0xFFu)  | ((uint32_t)d.k9b << 8);
            uint32_t ic = ((d.imm >> 16) & 0xFFu) | ((uint32_t)d.k9c << 8);
            if (d.ka && ia >= c.max_consts) idx = (int)ia;
            if (d.kb && ib >= c.max_consts) idx = (int)ib;
            if (d.kc && ic >= c.max_consts) idx = (int)ic;
        } else {
            if (d.ka && (uint32_t)d.ra >= c.max_consts) idx = d.ra;
            if (d.kb && (uint32_t)d.rb >= c.max_consts) idx = d.rb;
            if (d.kc && (uint32_t)d.rc >= c.max_consts) idx = d.rc;
        }
        if (idx >= 0)
            return (cft_status)cft_seq_cap_refusal(
                "highest constant index", (unsigned long)idx,
                (unsigned long)c.max_consts - 1u,
                "constants an instruction can address, indexed from 0",
                "max_consts");
    }
    return CFT_OK;
}

/* What of the scratch memory this program touches, for
 * cft_program_get_info and for the executor's allocator.
 *
 * `scratch_used` is docs/SEQUENCER.md's: one past the highest slot any
 * static STL or LDL names, or the whole depth when an indexed form is
 * present, because an STX's slot comes out of a register and is not
 * known until the run. The depth is the DEVICE's when it published
 * one and this library's own executor depth otherwise, which is the
 * same 256 for a software handle and the honest answer for a device
 * that never said.
 *
 * `scratch_active` is the different question the executor asks: does
 * this run need a scratch memory at all. A declared block needs one
 * even if no instruction touches it - the block is still preloaded and
 * still read back - and a program with neither should not pay for the
 * possibility, which at SEQ_SCRATCH_D slots across a lane block is
 * four megabytes a run (and eight times that at 2,048). */
static void seq_scratch_footprint(cft_device *dev, cft_program *p)
{
    cft_seq_caps c;
    uint32_t depth, used = 0, pc;
    int indexed = 0, touched = 0;

    cft_device_seq_caps(dev, &c);
    depth = c.max_scratch ? c.max_scratch : SEQ_SCRATCH_D;
    /* Kept for the executor (revision 7). Every depth a handle can
     * publish is a power of two - CAPS2[3:0] is a log2, and a software
     * handle refuses any other at open - so the log2 is exact. */
    p->scratch_depth = depth;
    p->scratch_log2  = 0;
    while ((1u << p->scratch_log2) < depth)
        p->scratch_log2++;

    for (pc = 0; pc < p->n_insns; pc++) {
        seq_insn d;
        seq_decode(p->insns[pc], &d);
        if (!d.ctrl)
            continue;
        if (d.op == SEQ_STL || d.op == SEQ_LDL) {
            uint32_t slot = d.imm & SEQ_KX_INDICES;
            touched = 1;
            if (slot + 1u > used)
                used = slot + 1u;
        } else if (d.op == SEQ_STX || d.op == SEQ_LDX) {
            touched = 1;
            indexed = 1;
        }
    }
    p->scratch_used   = indexed ? depth : used;
    p->scratch_active = touched ||
                        (p->flags & CFT_PROG_FLAG_SCRATCH_IO) != 0;
}

CFT_API cft_status cft_program_load(cft_device *dev, const void *image,
                                    size_t bytes, cft_program **out)
{
    const uint8_t *p = (const uint8_t *)image;
    cft_program *prog;
    uint32_t magic, ver, n_insns, n_consts, maxdep, prec, flags, scr_io;
    uint32_t n_sin = 0, n_sout = 0, n_stored;
    size_t esz, kbytes, i;
    uint64_t want;
    cft_status st;

    /* Before anything can refuse. This entry point reaches no device
     * backend, so nothing else clears the library's slot for it, and
     * until 2026-09-30 a refusal here that wrote no sentence left
     * cft_last_error() explaining an earlier call - P2 of the revision-7
     * round measured one printing a cft_run_ex index refusal. Every
     * refusal below now writes its own sentence, the NULL argument's
     * included: the clear alone would not do for a refusal left without
     * one, since cft_last_error() then falls through to a device
     * backend's message, which may be older still. So the clear is for
     * the exits that are not refusals: a load that succeeds, and the
     * allocation failures, which carry no sentence here (nor do ten of
     * the remote and XRT backends' fourteen out-of-memory returns). */
    cft_clear_error();
    if (!dev || !image || !out) {
        cft_set_error("cft_program_load was given a NULL %s; it needs the "
                      "device, the image and somewhere to put the program",
                      !dev ? "device" : !image ? "image" : "out");
        return CFT_ERR_INVALID_ARGUMENT;
    }
    *out = NULL;
    /* The image is read here, on the host: a resident buffer's device
     * bytes come home first (softfloat.h). Until 2026-09-26 nothing in
     * this file brought anything home (verifier-V8, N2). */
    st = (cft_status)cft_host_in(dev, image, bytes);
    if (st != CFT_OK)
        return st;          /* the backend's own sentence (softfloat.h) */
    if (bytes < SEQ_HEADER_BYTES) {
        cft_set_error("this image is %lu bytes, shorter than the %d-byte "
                      "header every program image begins with",
                      (unsigned long)bytes, SEQ_HEADER_BYTES);
        return CFT_ERR_ARTIFACT;
    }

    magic    = rd_le32(p +  0);
    ver      = rd_le32(p +  4);
    n_insns  = rd_le32(p +  8);
    n_consts = rd_le32(p + 12);
    maxdep   = rd_le32(p + 16);
    prec     = rd_le32(p + 20);
    /* reserved[0] became `flags` on 2026-09-08. An image built before
     * that wrote zero there, which is flags with no bit set, so every
     * older image reads exactly as it did - which is the whole reason
     * the word was reserved rather than absent. reserved[1] became
     * `scratch_io` the same evening, on the same terms and with one
     * more: it is meaningful only under CFT_PROG_FLAG_SCRATCH_IO, and
     * with that bit clear it must still be zero, exactly as the
     * reserved word it was. */
    flags    = rd_le32(p + 24);
    scr_io   = rd_le32(p + 28);

    /* The header's own refusals, each CFT_ERR_ARTIFACT as it always was
     * and each with the sentence seq.py's from_bytes gives the same
     * image (the words differ; the meaning is the model's). */
    if (magic != SEQ_MAGIC) {
        cft_set_error("this image's magic is 0x%08lx, not 0x%08lx "
                      "(\"CFTP\"), so it is not a program image",
                      (unsigned long)magic, (unsigned long)SEQ_MAGIC);
        return CFT_ERR_ARTIFACT;
    }
    if (ver != SEQ_VERSION) {
        cft_set_error("this image is program-image version %lu, and this "
                      "library reads version %lu", (unsigned long)ver,
                      (unsigned long)SEQ_VERSION);
        return CFT_ERR_ARTIFACT;
    }
    if (!(flags & CFT_PROG_FLAG_SCRATCH_IO) && scr_io) {
        cft_set_error("this image's header word 7, scratch_io, is 0x%08lx "
                      "and its flags do not carry SCRATCH_IO; with that bit "
                      "clear the word is reserved and must be zero",
                      (unsigned long)scr_io);
        return CFT_ERR_ARTIFACT;
    }
    /* A flag bit this library does not know is an image it cannot
     * read: the bit says something about the layout or the run, and
     * the honest answer to a sentence you cannot parse is not to
     * guess. This is the version guard for everything flags will ever
     * carry, which is why the round needed no VERSION step. */
    if (flags & ~SEQ_FLAGS_KNOWN) {
        char known[CFT_SEQ_FLAG_NAMES_MAX];
        cft_set_error("this image's header flags are 0x%08lx, and 0x%08lx "
                      "of that is bits this library does not know: it knows "
                      "%s (mask 0x%08lx), and every other bit is reserved "
                      "and must be zero", (unsigned long)flags,
                      (unsigned long)(flags & ~SEQ_FLAGS_KNOWN),
                      cft_seq_flag_names(SEQ_FLAGS_KNOWN, known,
                                         sizeof known),
                      (unsigned long)SEQ_FLAGS_KNOWN);
        return CFT_ERR_ARTIFACT;
    }
    if (prec > 3) {
        cft_set_error("this image's precision code is %lu, which is not on "
                      "the ladder: 0 %s, 1 %s, 2 %s, 3 %s",
                      (unsigned long)prec, cft_format_name(CFT_FP32),
                      cft_format_name(CFT_FP64), cft_format_name(CFT_FP128),
                      cft_format_name(CFT_FP256));
        return CFT_ERR_ARTIFACT;
    }
    /* A program is compiled for one format, because its constants are
     * format-width values. Refuse it here rather than at the first
     * instruction that would issue a precision this device does not
     * carry. */
    if (!cft_supports(dev, CFT_FMA, (cft_format)prec)) {
        /* Name what the device DOES carry, which is the sentence a
         * caller holding an image for the wrong rung actually needs. */
        cft_caps pc;
        memset(&pc, 0, sizeof pc);
        pc.struct_size = sizeof pc;
        if (cft_get_caps(dev, &pc) == CFT_OK)
            return (cft_status)cft_device_format_refusal(
                pc.format_mask, (int)prec,
                "cft_program_load: a program is compiled for one format");
        return (cft_status)cft_composed_refusal("cft_program_load",
                                                "CFT_FMA", (int)prec);
    }
    /* And against the capacities THIS device publishes, in the same
     * breath and for the same reason: the alternative is a program
     * that loads, runs on a laptop, and is refused by the tile at its
     * header check with a status bit and no explanation.
     *
     * At LOAD rather than at run, because a program is built once and
     * run many times - a tool that will not fit wants to know before
     * it has staged operands - and because a handle that loaded and
     * cannot run is a worse contract than a load that failed.
     *
     * BEFORE the absolute ceiling below, not after, so that every
     * device gets the same explained refusal at its own cap. For a
     * software handle the two boundaries are the same number, and
     * whichever came first would be the one a caller ever saw; the
     * one that names the cap is the better answer. */
    st = seq_check_caps(dev, n_insns, maxdep);
    if (st != CFT_OK)
        return st;
    /* The bank's depth, on every device, before any backend sees the
     * image (2026-10-01; golden-first, seq.py's validate refuses it
     * too). 512 is what nine index bits under kx address, so no
     * instruction can read a constant past it and no tile holds one:
     * KMEM_D is fixed by the encoding, not by a build. A tile REFUSES
     * an image that declares more, at its header check - with STATUS[3]
     * and no explanation, after the image has crossed. Until this date
     * the library loaded such an image, ran it on the software backend
     * and handed it to that refusal on a card.
     *
     * CFT_ERR_UNSUPPORTED, the status of the capacity refusals beside
     * it - an instruction count or a deposit budget past the device's -
     * and of the tile's own STATUS[3] for this image (backend_xrt.cpp).
     * Not CFT_ERR_ARTIFACT: the image is well formed, its bytes exactly
     * what its header describes, and what it asks for is a bank no
     * device has. Not cft_seq_cap_refusal either, whose sentence says
     * "this device's is": 512 is every device's ceiling, whatever one
     * publishes as max_consts, so the sentence names the reach. */
    if (n_consts > SEQ_ADDR_CONSTS) {
        cft_set_error("this image's header declares %lu constants "
                      "(n_consts), and an instruction addresses at most "
                      "%lu - nine index bits under kx - so no device holds "
                      "a bank that deep: a tile refuses the image at its "
                      "header check, after it has crossed, with STATUS[3] "
                      "and no explanation",
                      (unsigned long)n_consts,
                      (unsigned long)SEQ_ADDR_CONSTS);
        return CFT_ERR_UNSUPPORTED;
    }
    /* The library's own absolute ceiling on a deposit budget, which is
     * about what this process can represent rather than about any
     * device. Only reachable when the device published no cap of its
     * own - cft_caps documents zero as unknown, and a remote server
     * older than those fields is the one thing that produces it - or
     * one above this ceiling, which no device does. The sentence says
     * which (2026-09-30; until then it said nothing). */
    if (maxdep > SEQ_MAX_DEPOSITS) {
        cft_seq_caps mc;
        cft_device_seq_caps(dev, &mc);
        cft_set_error("this image's max_deposits is %lu, past %lu, this "
                      "library's own ceiling on deposit slots a lane - a "
                      "run's output is n times that many elements, so the "
                      "ceiling bounds what one image can make a host "
                      "allocate; this device's own cap, "
                      "cft_caps.max_deposits, is %lu%s",
                      (unsigned long)maxdep, (unsigned long)SEQ_MAX_DEPOSITS,
                      (unsigned long)mc.max_deposits,
                      mc.max_deposits ? "" : " (unknown)");
        return CFT_ERR_INVALID_ARGUMENT;
    }

    /* A BANK_EXT image on a device that cannot take a bank, refused
     * BEFORE the map is ever touched.
     *
     * This is the one guard that protects an old bitstream, and it has
     * to be here rather than in the tile: a 0x600 tile's FETCH reads
     * n_consts constants from the image whatever the header's flags
     * say, so it would read the first instructions as constants and
     * then run whatever followed. There is no status bit for that,
     * because the tile never notices. */
    if (flags & CFT_PROG_FLAG_BANK_EXT) {
        cft_seq_caps sc;
        cft_device_seq_caps(dev, &sc);
        if (!(sc.features & CFT_SEQ_FEAT_BANK_PTR)) {
            cft_set_error("this image's header flags carry BANK_EXT, so its "
                          "constants arrive per run, and this device does "
                          "not publish the feature (CAPS[6] clear, "
                          "cft_caps.seq_features bit 2 - "
                          "CFT_SEQ_FEAT_BANK_PTR); its fetch would read "
                          "%lu constants from an image that has none. Build "
                          "the program with its constants in the image",
                          (unsigned long)n_consts);
            return CFT_ERR_UNSUPPORTED;
        }
    }

    /* And the scratch block, on the same terms and for a sharper
     * reason. A revision-2 tile refuses a non-zero reserved[1] at its
     * header check, so this one WOULD be caught there - but with
     * STATUS[3] and no explanation, after the image has crossed, and
     * only on a tile new enough to check the word at all. The loader
     * says it first, by name, and says which feature. */
    if (flags & CFT_PROG_FLAG_SCRATCH_IO) {
        cft_seq_caps sc;
        cft_device_seq_caps(dev, &sc);
        n_sin  = scr_io & 0xFFFFu;
        n_sout = (scr_io >> 16) & 0xFFFFu;
        if (!(sc.features & CFT_SEQ_FEAT_SCRATCH_IO)) {
            cft_set_error("this image's header flags carry SCRATCH_IO, so "
                          "every run preloads %lu scratch slots a lane and "
                          "reads %lu back, and this device does not publish "
                          "the feature (CAPS2[5] clear, "
                          "cft_caps.seq_features bit 9 - "
                          "CFT_SEQ_FEAT_SCRATCH_IO)",
                          (unsigned long)n_sin, (unsigned long)n_sout);
            return CFT_ERR_UNSUPPORTED;
        }
        /* Each half is at most the device's depth - a block deeper than
         * the memory it is loaded into names slots that do not exist.
         * Zero is unknown, and an unknown depth is enforced against
         * nothing, as everywhere else. */
        if (sc.max_scratch && n_sin > sc.max_scratch)
            return (cft_status)cft_seq_cap_refusal(
                "n_scratch_in", n_sin, sc.max_scratch,
                "scratch slots a lane", "max_scratch");
        if (sc.max_scratch && n_sout > sc.max_scratch)
            return (cft_status)cft_seq_cap_refusal(
                "n_scratch_out", n_sout, sc.max_scratch,
                "scratch slots a lane", "max_scratch");
        /* And where the device published NO depth, this library's own
         * ceiling: its executor's default depth, the depth
         * seq_scratch_footprint gives such a program too. Only there - a
         * device that published a depth is held to its own number above
         * and to nothing else. Zero is unknown; past the feature test
         * above it takes a device that publishes the block without a
         * depth, a tile whose CAPS2 sets bit 5 and not bit 4.
         *
         * Until 2026-09-29 this test ran whatever the device published,
         * which held every handle's block to 256: invisible while no
         * device published more, and a refusal with no sentence of every
         * block from 257 to 2,048 slots once a 2,048-slot handle
         * existed (verifier-R5; device-test's deep-block leg holds it
         * now). */
        if (!sc.max_scratch &&
            (n_sin > SEQ_SCRATCH_D || n_sout > SEQ_SCRATCH_D)) {
            cft_set_error("this image's scratch block preloads %lu slots a "
                          "lane and reads %lu back, and this device "
                          "published no scratch depth (cft_caps.max_scratch "
                          "is 0, unknown), so the block is held to this "
                          "library's own executor depth, %lu slots a lane",
                          (unsigned long)n_sin, (unsigned long)n_sout,
                          (unsigned long)SEQ_SCRATCH_D);
            return CFT_ERR_INVALID_ARGUMENT;
        }
    }

    /* And revision 4's strict scratch range, on exactly the same terms.
     * A tile that does not publish the feature refuses this image at its
     * own header check - flags[2] sits inside the reserved range every
     * revision before 4 enforces - but with STATUS[3] and no
     * explanation, after the image has crossed. The loader says it
     * first, by name, and says which feature.
     *
     * Clearing the flag would let the same program run, which is why
     * this is a refusal and not a fallback: under the modulo it is a
     * DIFFERENT contract, and answering a different question quietly is
     * the one thing this library must not do. */
    if (flags & CFT_PROG_FLAG_SCRATCH_STRICT) {
        cft_seq_caps strict_caps;
        cft_device_seq_caps(dev, &strict_caps);
        if (!(strict_caps.features & CFT_SEQ_FEAT_SCRATCH_STRICT)) {
            cft_set_error("this image's header flags carry SCRATCH_STRICT, "
                          "so an indexed scratch access at or past the "
                          "device's depth is reported rather than reduced "
                          "modulo it, and this device does not publish the "
                          "feature (CAPS2[6] clear, cft_caps.seq_features "
                          "bit 10 - CFT_SEQ_FEAT_SCRATCH_STRICT)");
            return CFT_ERR_UNSUPPORTED;
        }
    }

    esz  = (size_t)cft_sf_formats[prec].width / 8;
    /* A BANK_EXT image is a header and an instruction stream, full
     * stop: n_consts says how many constants the program ADDRESSES,
     * and none of them is in the file. */
    n_stored = (flags & CFT_PROG_FLAG_BANK_EXT) ? 0u : n_consts;
    /* In 64 bits, not in size_t. Two 32-bit header fields describe up
     * to about 2^38 bytes, which a 32-bit size_t wraps: 8 * 0x20000001
     * instructions came to 8, so a 40-byte image passed this check on
     * such a host and failed later, at the allocation, as
     * CFT_ERR_OUT_OF_MEMORY, where a 64-bit host answered
     * CFT_ERR_ARTIFACT (measured on an i686 build, 2026-09-30; wasm32
     * and the 32-bit boards are such hosts). The same image now gets the
     * same answer on every host. Once the check has passed, every part
     * of `want` is part of `bytes`, so kbytes below fits a size_t. */
    want = (uint64_t)SEQ_HEADER_BYTES + (uint64_t)n_stored * esz +
           (uint64_t)n_insns * SEQ_INSN_BYTES;
    /* Exactly, not at least: a program is its header, its constants
     * and its instructions, so anything else is a different program
     * and should not load as this one. */
    if ((uint64_t)bytes != want) {
        cft_set_error("this image is %llu bytes and its header describes "
                      "%llu: %d of header, %lu x %lu of constants%s and "
                      "%lu x %d of instructions. A program image is exactly "
                      "those, so this one is a different program",
                      (unsigned long long)bytes, (unsigned long long)want,
                      SEQ_HEADER_BYTES, (unsigned long)n_stored,
                      (unsigned long)esz,
                      (flags & CFT_PROG_FLAG_BANK_EXT)
                          ? " (none in the image, under BANK_EXT)" : "",
                      (unsigned long)n_insns, SEQ_INSN_BYTES);
        return CFT_ERR_ARTIFACT;
    }
    kbytes = (size_t)n_stored * esz;

    prog = (cft_program *)calloc(1, sizeof *prog);
    if (!prog)
        return CFT_ERR_OUT_OF_MEMORY;
    prog->dev          = dev;
    prog->fmt_code     = (int)prec;
    prog->f            = &cft_sf_formats[prec];
    prog->max_deposits = maxdep;
    prog->n_insns      = n_insns;
    prog->n_consts     = n_consts;
    prog->flags        = flags;
    prog->n_scratch_in  = n_sin;
    prog->n_scratch_out = n_sout;
    if (n_insns) {
        prog->insns = (uint64_t *)calloc(n_insns, sizeof(uint64_t));
        if (!prog->insns) { cft_program_free(prog); return CFT_ERR_OUT_OF_MEMORY; }
    }
    if (n_consts && !(flags & CFT_PROG_FLAG_BANK_EXT)) {
        prog->consts = (cft_bn *)calloc(n_consts, sizeof(cft_bn));
        if (!prog->consts) { cft_program_free(prog); return CFT_ERR_OUT_OF_MEMORY; }
    }
    prog->image = (uint8_t *)malloc(bytes);
    if (!prog->image) { cft_program_free(prog); return CFT_ERR_OUT_OF_MEMORY; }
    memcpy(prog->image, p, bytes);
    prog->image_bytes = bytes;

    if (prog->consts)
        for (i = 0; i < n_consts; i++)
            cft_bn_load(&prog->consts[i], p + SEQ_HEADER_BYTES + i * esz,
                        (int)esz);
    for (i = 0; i < n_insns; i++)
        prog->insns[i] = rd_le64(p + SEQ_HEADER_BYTES + kbytes +
                                 i * SEQ_INSN_BYTES);

    st = seq_validate(prog);
    if (st != CFT_OK) {
        cft_program_free(prog);
        return st;
    }
    /* After seq_validate, so that a malformed instruction is reported
     * as malformed rather than as a capacity the device lacks. */
    st = seq_check_against_device(dev, prog);
    if (st != CFT_OK) {
        cft_program_free(prog);
        return st;
    }
    seq_scratch_footprint(dev, prog);
    *out = prog;
    return CFT_OK;
}

CFT_API void cft_program_free(cft_program *prog)
{
    if (!prog)
        return;
    free(prog->insns);
    free(prog->consts);
    free(prog->image);
    free(prog);
}

CFT_API cft_status cft_program_get_info(cft_program *prog,
                                        cft_program_info *out)
{
    cft_program_info info;
    size_t want;

    if (!prog || !out)
        return CFT_ERR_INVALID_ARGUMENT;
    want = out->struct_size;
    if (want < sizeof(size_t))
        return CFT_ERR_INVALID_ARGUMENT;

    memset(&info, 0, sizeof info);
    info.format       = (cft_format)prog->fmt_code;
    info.max_deposits = prog->max_deposits;
    info.n_insns      = prog->n_insns;
    info.n_consts     = prog->n_consts;
    /* Appended in ABI 0.9; a caller with the older struct passes the
     * older struct_size and the memcpy below stops before it. */
    info.flags         = prog->flags;
    /* And in 0.10, on the same terms. */
    info.n_scratch_in  = prog->n_scratch_in;
    info.n_scratch_out = prog->n_scratch_out;
    info.scratch_used  = prog->scratch_used;
    if (want > sizeof info)
        want = sizeof info;
    info.struct_size = want;
    memcpy(out, &info, want);
    return CFT_OK;
}

/* ---- execution ---------------------------------------------------- */

typedef struct {
    cft_bn regs[BLOCK_LANES][SEQ_NREG];
    int    active[BLOCK_LANES];
    /* The lanes THE CALLER HAS in this block (R17): every lane without
     * a mask, the mask's bits with one. It is the floor under `active`
     * - what ACTALL restores, and what the three output writes test -
     * and it is a second array rather than a re-read of the mask
     * because ACTALL is inside the instruction loop, where the block's
     * global offset is not in scope. The hardware makes the same
     * choice for the same reason: its `blk_act` is the block's lanes
     * ANDed with the mask, computed once and read by both. */
    int    keep[BLOCK_LANES];
    uint32_t counts[BLOCK_LANES];
    /* R23's byte a lane (ABI 0.17): [4:0] the IEEE flags the lane raised
     * outside every quiet region, CFT_LANE_DEPOSIT_OVERFLOW,
     * CFT_LANE_SCRATCH_RANGE and CFT_LANE_MARKED. Kept for every run -
     * an OR beside the one into the run's word - and written out only
     * where the caller asks, for the lanes it has. */
    uint8_t lflags[BLOCK_LANES];
    /* The program's scratch_depth slots a lane, or NULL for a program
     * that touches no scratch and declares no block. Out of line rather
     * than inside this struct because it is four megabytes at 256 slots
     * to the register file's half - 34 at 2,048 - and a program that
     * never issues an STL should not allocate and zero it once a run.
     * Lane i's slot s is scratch[i * depth + s], and it is the lane's
     * alone - there is no cross-lane addressing in the contract and
     * none here. */
    cft_bn *scratch;
    uint32_t depth;
} seq_block;

/* Lane `lane`'s slot `slot`, or NULL when this program has no scratch.
 * The two callers below have both already refused to reach it in that
 * case, so the NULL is a defence and not a path. */
static cft_bn *seq_scratch_at(seq_block *B, int lane, uint32_t slot)
{
    if (!B->scratch || slot >= B->depth)
        return NULL;
    return &B->scratch[(size_t)lane * B->depth + slot];
}

/* The constants a run computes on: the image's own, or the bank the
 * caller handed cft_program_run_bank. The executor is given the array
 * rather than reading it off the program, so that a BANK_EXT program
 * is the SAME executor with a different pointer and not a second
 * implementation - which is what makes "the image is the schedule and
 * the bank is the data" true of this code and not only of the tile. */
static const cft_bn *seq_src(const cft_bn *konst, seq_block *B, int lane,
                             int idx, int is_const)
{
    return is_const ? &konst[idx] : &B->regs[lane][idx];
}

/* Skip forward to the ENDREP matching the REPEAT at `pc`. Validation
 * has already proved the nesting is balanced, so the depth scan is
 * exact. */
static uint32_t seq_matching_endrep(const cft_program *p, uint32_t pc)
{
    int depth = 0;
    uint32_t j;
    for (j = pc; j < p->n_insns; j++) {
        seq_insn d;
        seq_decode(p->insns[j], &d);
        if (!d.ctrl)
            continue;
        if (d.op == SEQ_REPEAT)
            depth++;
        else if (d.op == SEQ_ENDREP && --depth == 0)
            return j;
    }
    return p->n_insns;      /* unreachable for a validated program */
}

/* Revision 8's augadd / augerr over a lane block: for every ACTIVE lane,
 * augmentedAddition(ra, rb) through augmented.c's own lane function,
 * keeping r (augadd) or e (augerr) in rd, and OR-ing the flags that
 * operation raises. Both operands are read before rd is written, so rd
 * may name ra or rb. An inactive lane neither writes nor raises. In a
 * -DCFT_NO_AUGMENTED build there is no such function, the software
 * backend does not publish CFT_SEQ_FEAT_AUGADD, and the loader has
 * already refused any program that needs it - so the branch below it is
 * unreachable and says so. */
static cft_status seq_exec_augmented(const cft_program *p, seq_block *B,
                                     int nlane, const seq_insn *d,
                                     uint32_t *flags, int loud)
{
#ifndef CFT_NO_AUGMENTED
    const int rd = seq_reg(d->rd, d->hd);
    const int ra = seq_reg(d->ra, d->ha);
    const int rb = seq_reg(d->rb, d->hb);
    int i;
    for (i = 0; i < nlane; i++) {
        cft_bn r, e;
        uint32_t fl = 0;
        if (!B->active[i])
            continue;       /* no write and no flags, as for the ALU */
        if (cft_aug_add_lane(p->f, &B->regs[i][ra], &B->regs[i][rb],
                             &r, &e, &fl))
            return CFT_ERR_INTERNAL;
        cft_bn_copy(&B->regs[i][rd], d->op == SEQ_AUGERR ? &e : &r);
        /* R24: a quiet region silences them, here as for an ALU
         * instruction; otherwise they reach the run's word and the
         * lane's byte alike (R23). */
        if (loud) {
            *flags |= fl;
            B->lflags[i] |= (uint8_t)fl;
        }
    }
    return CFT_OK;
#else
    (void)p; (void)B; (void)nlane; (void)d; (void)flags; (void)loud;
    return CFT_ERR_INTERNAL;
#endif
}

/* Revision 8's post-step of a stepped STX/LDX: rb := rb + step modulo
 * 2^width for every ACTIVE lane, after every lane's access - through this
 * library's own IADD, or ISUB by the step's magnitude, which is the same
 * residue. NOT gated by SCRATCH_STRICT: R8 suppresses an access, and the
 * step is a register write, so a strict and a non-strict run leave rb
 * the same. A zero step writes nothing: the old instruction. Nor does an
 * LDX into its own index, which keeps what it loaded - the slot's value,
 * or R8's +0 - and discards the step (seq_step_discarded). */
static cft_status seq_post_step(const cft_program *p, seq_block *B,
                                int nlane, const seq_insn *d)
{
    const int step = seq_step(d);
    const int rb = seq_reg(d->rb, d->hb);
    cft_bn mag, zero;
    int i;
    if (!step || seq_step_discarded(d))
        return CFT_OK;
    cft_bn_set_u32(&mag, (uint32_t)(step < 0 ? -step : step));
    cft_bn_zero(&zero);
    for (i = 0; i < nlane; i++) {
        cft_bn out;
        uint32_t fl = 0;
        if (!B->active[i])
            continue;
        if (cft_sf_compute(p->f, step > 0 ? CFT_SF_IADD : CFT_SF_ISUB, 0,
                           &B->regs[i][rb], &mag, &zero, &out, &fl))
            return CFT_ERR_INTERNAL;
        cft_bn_copy(&B->regs[i][rb], &out);
    }
    return CFT_OK;
}

static cft_status seq_run_block(const cft_program *p, const cft_bn *konst,
                                seq_block *B,
                                int nlane, uint8_t *deposits,
                                size_t first_elem, size_t esz,
                                uint32_t *flags, uint32_t *status)
{
    struct { uint32_t body; uint32_t left; } stack[SEQ_MAX_DEPTH];
    int sp = 0;
    uint32_t pc = 0;
    /* R24's quiet depth, counted in program order. seq_validate nests
     * regions properly with loops, so a loop body the early exit skips
     * has balanced brackets and the count after it is the count before
     * it: the depth at an instruction is a function of where it stands. */
    int qdepth = 0;

    while (pc < p->n_insns) {
        seq_insn d;
        int i, any;
        seq_decode(p->insns[pc], &d);

        if (!d.ctrl) {
            /* The three operand sources are a property of the
             * instruction, not of the lane, so they are resolved once
             * per instruction - which is what the hardware does too,
             * a constant being unable to change during a run. */
            int ia, ib, ic, ka, kb, kc;
            int rd = seq_reg(d.rd, d.hd);
            ia = seq_source(&d, 0, &ka);
            ib = seq_source(&d, 1, &kb);
            ic = seq_source(&d, 2, &kc);
            for (i = 0; i < nlane; i++) {
                cft_bn outv;
                uint32_t fl = 0;
                if (!B->active[i])
                    continue;   /* no write, no deposit, and no flags */
                if (cft_sf_compute(p->f, d.op, d.rnd,
                                   seq_src(konst, B, i, ia, ka),
                                   seq_src(konst, B, i, ib, kb),
                                   seq_src(konst, B, i, ic, kc),
                                   &outv, &fl))
                    return CFT_ERR_INTERNAL;
                cft_bn_copy(&B->regs[i][rd], &outv);
                if (!qdepth) {          /* R24: a region silences them */
                    *flags |= fl;
                    B->lflags[i] |= (uint8_t)fl;
                }
            }
            pc++;
            continue;
        }

        switch (d.op) {
        case SEQ_HALT:
            return CFT_OK;

        case SEQ_REPEAT:
            any = 0;
            for (i = 0; i < nlane; i++)
                if (B->active[i]) { any = 1; break; }
            if (d.imm == 0 || !any) {
                pc = seq_matching_endrep(p, pc) + 1;
                break;
            }
            stack[sp].body = pc + 1;
            stack[sp].left = d.imm;
            sp++;
            pc++;
            break;

        case SEQ_ENDREP:
            any = 0;
            for (i = 0; i < nlane; i++)
                if (B->active[i]) { any = 1; break; }
            stack[sp - 1].left--;
            if (stack[sp - 1].left > 0 && any) {
                pc = stack[sp - 1].body;
            } else {
                sp--;
                pc++;
            }
            break;

        case SEQ_DEPOSIT:
            for (i = 0; i < nlane; i++) {
                size_t slot;
                if (!B->active[i])
                    continue;
                if (B->counts[i] >= p->max_deposits) {
                    /* a report, which no quiet region hides (R24) */
                    *status |= CFT_STATUS_DEPOSIT_OVERFLOW;
                    B->lflags[i] |= (uint8_t)CFT_LANE_DEPOSIT_OVERFLOW;
                    continue;
                }
                slot = (first_elem + (size_t)i) * p->max_deposits +
                       B->counts[i];
                cft_bn_store(&B->regs[i][seq_reg(d.ra, d.ha)],
                             deposits + slot * esz, (int)esz);
                B->counts[i]++;
            }
            pc++;
            break;

        case SEQ_SETACT:
            for (i = 0; i < nlane; i++) {
                cft_bn mag;
                if (!B->active[i])
                    continue;       /* narrows only, never widens */
                cft_bn_copy(&mag, &B->regs[i][seq_reg(d.ra, d.ha)]);
                cft_bn_clearbit(&mag, p->f->width - 1);
                B->active[i] = !cft_bn_is_zero(&mag);
            }
            pc++;
            break;

        case SEQ_ACTALL:
            /* Every lane the caller has, which under R17 is not every
             * lane of the block. `keep` is all ones without a mask, so
             * this is `= 1` for every program written before it. */
            for (i = 0; i < nlane; i++)
                B->active[i] = B->keep[i];
            pc++;
            break;

        /* The scratch, revision 3 R4. A store is a REGISTER WRITE for
         * P3's purposes and is masked by the active bit, so an
         * all-inactive loop body stays a no-op and the early exit
         * stays free; a load writes `rd` and is masked the same way.
         * Neither is arithmetic: no rounding attribute is read and no
         * flag is raised, exactly as P1 holds for IMUL. */
        case SEQ_STL:
        case SEQ_LDL: {
            uint32_t slot = d.imm & SEQ_KX_INDICES;
            for (i = 0; i < nlane; i++) {
                cft_bn *cell;
                if (!B->active[i])
                    continue;
                cell = seq_scratch_at(B, i, slot);
                if (!cell)
                    return CFT_ERR_INTERNAL;
                if (d.op == SEQ_STL)
                    cft_bn_copy(cell, &B->regs[i][seq_reg(d.ra, d.ha)]);
                else
                    cft_bn_copy(&B->regs[i][seq_reg(d.rd, d.hd)], cell);
            }
            pc++;
            break;
        }

        /* The indexed forms take the slot from `rb`'s BIT PATTERN read as
         * an unsigned integer - where the atlas emitter keeps its loop
         * counters.
         *
         * WITHOUT CFT_PROG_FLAG_SCRATCH_STRICT the index is reduced
         * modulo the depth. That reduction is part of the contract
         * rather than an accident: it is what every image built before
         * revision 4 means, so it is done here and in the model alike.
         *
         * WITH the flag (revision 4, R8) an index at or past the depth
         * is REPORTED instead - the access is suppressed, LDX reads +0,
         * and the run continues, exactly as a deposit past max_deposits
         * does. That is what makes the depth portable: a program inside
         * its declared scratch_used computes the same answer at every
         * depth, and one outside it is told rather than quietly handed
         * a different slot.
         *
         * The range test is a BIT LENGTH, not a wider extract, and that
         * is the substance of R8 on this side. The line below reads
         * only the low scratch_log2 bits, so before this flag existed
         * the executor could not SEE an out-of-range index - every
         * index was in range by construction. The depth is published as
         * a log2 and is therefore a power of two, which makes
         * `idx >= scratch_depth` exactly
         * `cft_bn_bitlen(idx) > scratch_log2` at any register width,
         * with no truncation anywhere.
         *
         * Both are the PROGRAM's depth, which is its handle's (revision
         * 7): 256 on a handle opened plainly, another power of two on
         * one opened at another depth - and the modulus and the range
         * are what a tile of that depth computes. */
        case SEQ_STX:
        case SEQ_LDX: {
            int rb = seq_reg(d.rb, d.hb);
            int strict_range = (p->flags & CFT_PROG_FLAG_SCRATCH_STRICT) != 0;
            for (i = 0; i < nlane; i++) {
                cft_bn *cell;
                uint32_t slot;
                if (!B->active[i])
                    continue;
                if (strict_range &&
                    cft_bn_bitlen(&B->regs[i][rb]) > p->scratch_log2) {
                    *status |= CFT_STATUS_SCRATCH_RANGE;
                    B->lflags[i] |= (uint8_t)CFT_LANE_SCRATCH_RANGE;
                    /* +0, which is what an untouched slot reads back as.
                     * Never a stale register: that would make the result
                     * depend on whatever the lane happened to hold. */
                    if (d.op == SEQ_LDX)
                        cft_bn_zero(&B->regs[i][seq_reg(d.rd, d.hd)]);
                    continue;
                }
                slot = cft_bn_extract(&B->regs[i][rb], 0, p->scratch_log2)
                       & (p->scratch_depth - 1u);
                cell = seq_scratch_at(B, i, slot);
                if (!cell)
                    return CFT_ERR_INTERNAL;
                if (d.op == SEQ_STX)
                    cft_bn_copy(cell, &B->regs[i][seq_reg(d.ra, d.ha)]);
                else
                    cft_bn_copy(&B->regs[i][seq_reg(d.rd, d.hd)], cell);
            }
            /* revision 8: the post-step, after every lane's access */
            {
                const cft_status sst = seq_post_step(p, B, nlane, &d);
                if (sst != CFT_OK)
                    return sst;
            }
            pc++;
            break;
        }

        /* Revision 8: augmentedAddition's two halves. */
        case SEQ_AUGADD:
        case SEQ_AUGERR: {
            const cft_status ast = seq_exec_augmented(p, B, nlane, &d,
                                                      flags, !qdepth);
            if (ast != CFT_OK)
                return ast;
            pc++;
            break;
        }

        /* R24: a quiet region's two ends. Not per lane - a region is a
         * property of an instruction's place in the program. */
        case SEQ_QUIET:
            qdepth++;
            pc++;
            break;

        case SEQ_ENDQUIET:
            qdepth--;
            pc++;
            break;

        /* R24's raise, for every ACTIVE lane: rA[4:0] ORed into the flags
         * and the lane's byte outside a region (754-2019 5.7.4's
         * raiseFlags - any subset, never a clear), and rA[7] marking the
         * lane anywhere: the mark is not an IEEE flag, and a lost one
         * would make an undecided last bit look decided. Nothing else of
         * rA is read. An inactive lane raises and marks nothing (P3). */
        case SEQ_RAISE: {
            const int ra = seq_reg(d.ra, d.ha);
            for (i = 0; i < nlane; i++) {
                uint32_t low;
                if (!B->active[i])
                    continue;
                low = (uint32_t)cft_bn_extract(&B->regs[i][ra], 0, 8);
                if (!qdepth) {
                    *flags |= low & SEQ_RAISE_FLAGS;
                    B->lflags[i] |= (uint8_t)(low & SEQ_RAISE_FLAGS);
                }
                if ((low >> SEQ_RAISE_MARK) & 1u) {
                    *status |= CFT_STATUS_MARKED;
                    B->lflags[i] |= (uint8_t)CFT_LANE_MARKED;
                }
            }
            pc++;
            break;
        }

        default:
            return CFT_ERR_INTERNAL;
        }
    }
    return CFT_OK;
}

/* ---- the run: one entry point, and the wrappers over it ------------ */

/* How many bytes a run of this program's constant bank is, or 0 when
 * the program carries its own. Separate from the check below because
 * the message wants the number and so does the loader. */
static size_t seq_bank_bytes(const cft_program *p)
{
    size_t esz = (size_t)p->f->width / 8;
    if (!(p->flags & CFT_PROG_FLAG_BANK_EXT) || !p->n_consts)
        return 0;
    if ((size_t)p->n_consts > ((size_t)-1) / esz)
        return (size_t)-1;      /* not representable here; refused below */
    return (size_t)p->n_consts * esz;
}

/* The bank a run or a digest was handed, against the program it names.
 *
 * Two refusals, and both are about a program having exactly one source
 * of constants. A program that carries its own refuses a bank, because
 * a bank that was quietly ignored is two machines computing on
 * different numbers while agreeing about the image; and a BANK_EXT
 * program refuses a bank that is not the size its n_consts says,
 * because the alternative is reading past the caller's buffer or
 * running on constants it never supplied.
 *
 * `who` is the entry point's own name: a caller that reached the wrong
 * one should be told which one it wanted. */
static cft_status seq_check_bank(const cft_program *p, const void *bank,
                                 size_t bank_bytes, const char *who)
{
    size_t want;

    if (!(p->flags & CFT_PROG_FLAG_BANK_EXT)) {
        if (bank || bank_bytes) {
            cft_set_error("%s was given a %lu-byte constant bank and this "
                          "program carries its own %lu constants in its "
                          "image (its header flags do not set BANK_EXT). "
                          "A program has one source of constants; pass no "
                          "bank, or call cft_program_run",
                          who, (unsigned long)bank_bytes,
                          (unsigned long)p->n_consts);
            return CFT_ERR_INVALID_ARGUMENT;
        }
        return CFT_OK;
    }
    want = seq_bank_bytes(p);
    if (want == (size_t)-1) {
        cft_set_error("%s: this program addresses %lu constants, which is "
                      "more bank than this process can address",
                      who, (unsigned long)p->n_consts);
        return CFT_ERR_INVALID_ARGUMENT;
    }
    if (bank_bytes != want) {
        cft_set_error("%s was given a %lu-byte constant bank and this "
                      "program's bank is %lu bytes - %lu %s constants, "
                      "densely packed, exactly as an image's constant "
                      "section is laid out",
                      who, (unsigned long)bank_bytes, (unsigned long)want,
                      (unsigned long)p->n_consts,
                      cft_format_name((cft_format)p->fmt_code));
        return CFT_ERR_INVALID_ARGUMENT;
    }
    if (want && !bank) {
        cft_set_error("%s: this program's constants arrive with the run "
                      "(BANK_EXT) and the bank pointer is NULL", who);
        return CFT_ERR_INVALID_ARGUMENT;
    }
    return CFT_OK;
}

/* How many bytes a run's scratch-in and scratch-out blocks are, over
 * `n` lanes, or 0 when this program declares no I/O. Lane-major and
 * dense: lane i's slot s is element i * n_scratch_in + s, so the whole
 * block is n * n_scratch_in elements. (size_t)-1 is "not
 * representable here", refused by the check below the way the bank's
 * overflow is. */
static size_t seq_scratch_bytes(const cft_program *p, size_t n, int out)
{
    size_t esz   = (size_t)p->f->width / 8;
    size_t slots = out ? p->n_scratch_out : p->n_scratch_in;
    if (!(p->flags & CFT_PROG_FLAG_SCRATCH_IO) || !slots || !n)
        return 0;
    if (n > ((size_t)-1) / slots / esz)
        return (size_t)-1;
    return n * slots * esz;
}

/* The scratch blocks a run was handed, against the program it names.
 *
 * The same two refusals the bank has, and the same reason for each. A
 * program that declares no scratch I/O refuses a buffer, because a
 * block that was quietly ignored is a caller and a library disagreeing
 * about what a run carried; and a program that declares one refuses a
 * block that is not the size its header says, because the layout is
 * lane-major - a wrong n_scratch_in overruns nothing and silently
 * gives every lane somebody else's slots, which is the failure mode a
 * length check is worth having for.
 *
 * `who` is the entry point's own name, so a caller that reached the
 * wrong one is told which one it wanted. */
static cft_status seq_check_scratch(const cft_program *p,
                                    const cft_run_args *A, const char *who)
{
    const struct { const void *buf; size_t bytes; uint32_t slots;
                   const char *name; } side[2] = {
        { A->scratch_in,  A->scratch_in_bytes,  p->n_scratch_in,  "in" },
        { A->scratch_out, A->scratch_out_bytes, p->n_scratch_out, "out" }
    };
    int which;

    if (!(p->flags & CFT_PROG_FLAG_SCRATCH_IO)) {
        for (which = 0; which < 2; which++) {
            if (side[which].buf || side[which].bytes) {
                cft_set_error("%s was given a %lu-byte scratch-%s block and "
                              "this program declares no scratch I/O (its "
                              "header flags do not set SCRATCH_IO). Pass no "
                              "scratch block",
                              who, (unsigned long)side[which].bytes,
                              side[which].name);
                return CFT_ERR_INVALID_ARGUMENT;
            }
        }
        return CFT_OK;
    }
    for (which = 0; which < 2; which++) {
        size_t want = seq_scratch_bytes(p, A->n, which);
        /* R16 (ABI 0.14): with a table, `scratch_in` is the POOL the
         * table indexes and not the block - the block's shape is the
         * table's, n * n_scratch_in entries - so the buffer's length is
         * the pool's, which `idx_scratch_src` states as a count. The
         * two statements of one number must agree, for the reason the
         * dense check exists at all: a buffer whose length nobody
         * agreed on is a run reading somewhere nobody agreed on. Only
         * the IN side; the block on the way out is dense either way.
         *
         * `want != (size_t)-1` guards the substitution rather than the
         * comparison: the table is n * n_scratch_in entries whatever
         * the pool's length, so a block that is not representable here
         * is still not representable, and the refusal below must not
         * be lost by replacing the number that says so. */
        if (which == 0 && A->idx_scratch_in && want != (size_t)-1 &&
            (p->flags & CFT_PROG_FLAG_SCRATCH_IO)) {
            size_t esz = (size_t)p->f->width / 8;
            want = (A->idx_scratch_src > ((size_t)-1) / esz)
                 ? (size_t)-1 : A->idx_scratch_src * esz;
            if (want != (size_t)-1 && side[0].bytes != want) {
                cft_set_error("%s was given a %lu-byte scratch-in pool and "
                              "idx_scratch_src names %lu elements, which is "
                              "%lu bytes - with idx_scratch_in the block is "
                              "gathered THROUGH the table and scratch_in is "
                              "the pool it reads from",
                              who, (unsigned long)side[0].bytes,
                              (unsigned long)A->idx_scratch_src,
                              (unsigned long)want);
                return CFT_ERR_INVALID_ARGUMENT;
            }
        }
        if (want == (size_t)-1) {
            cft_set_error("%s: this program's scratch-%s block is %lu slots "
                          "a lane over %lu lanes, which is more than this "
                          "process can address",
                          who, side[which].name,
                          (unsigned long)side[which].slots,
                          (unsigned long)A->n);
            return CFT_ERR_INVALID_ARGUMENT;
        }
        if (side[which].bytes != want) {
            cft_set_error("%s was given a %lu-byte scratch-%s block and this "
                          "program's is %lu bytes - %lu lanes x %lu %s "
                          "values, lane-major and dense, lane i's slot s at "
                          "element i * %lu + s",
                          who, (unsigned long)side[which].bytes,
                          side[which].name, (unsigned long)want,
                          (unsigned long)A->n,
                          (unsigned long)side[which].slots,
                          cft_format_name((cft_format)p->fmt_code),
                          (unsigned long)side[which].slots);
            return CFT_ERR_INVALID_ARGUMENT;
        }
        if (want && !side[which].buf) {
            cft_set_error("%s: this program declares %lu scratch-%s slots a "
                          "lane and the pointer is NULL",
                          who, (unsigned long)side[which].slots,
                          side[which].name);
            return CFT_ERR_INVALID_ARGUMENT;
        }
    }
    return CFT_OK;
}

/* The executor and the dispatch, behind every entry point.
 *
 * `A` has been held to the program by seq_check_bank and
 * seq_check_scratch: its bank is NULL for a program that carries its
 * own constants and the caller's buffer for a BANK_EXT one, and its
 * scratch blocks are exactly the shape the header declares or both
 * absent. Everything from here is what cft_program_run always did,
 * with the constants and the scratch coming from wherever they come
 * from. */
/* One input element, dense or gathered - the whole of R16 on this
 * executor, in the one place both the streams and the scratch block
 * reach it.
 *
 * `idx` NULL is the dense case and the call is what it always was.
 * With a table, element e is `src[idx[e]]` and CFT_IDX_NONE is +0,
 * which is `cft_bn_zero` and not a load of anything: there is no
 * element to read and no address to compute, so a sentinel entry
 * issues no read here exactly as it issues none on the tile. Every
 * index has already been held to the source's declared length by
 * seq_check_round2, before the run started - so this function cannot
 * be the place a bad index is discovered, and does not look. */
static void seq_load_in(cft_bn *dst, const uint8_t *src,
                        const uint32_t *idx, size_t e, size_t esz)
{
    if (!idx) {
        cft_bn_load(dst, src + e * esz, (int)esz);
        return;
    }
    if (idx[e] == CFT_IDX_NONE) {
        cft_bn_zero(dst);
        return;
    }
    cft_bn_load(dst, src + (size_t)idx[e] * esz, (int)esz);
}

static cft_status seq_program_run(cft_program *prog, const cft_run_args *A)
{
    const void *bank   = A->bank;
    size_t bank_bytes  = A->bank_bytes;
    void *deposits     = A->deposits;
    uint32_t *counts   = A->counts;
    size_t n           = A->n;
    uint32_t *flags    = A->flags_out;
    uint32_t *bus      = A->bus_out;
    const uint8_t *pa = (const uint8_t *)A->a;
    const uint8_t *pb = (const uint8_t *)A->b;
    const uint8_t *pc_ = (const uint8_t *)A->c;
    const uint8_t *psi = (const uint8_t *)A->scratch_in;
    /* The four tables, or NULL each for a dense block (ABI 0.14). With
     * a table, `pa` and `psi` are the SOURCE and the POOL rather than
     * the run's elements, and the only thing that knows the difference
     * is seq_load_in below. */
    const uint32_t *ia = A->idx_a, *ib = A->idx_b, *ic = A->idx_c;
    const uint32_t *isi = A->idx_scratch_in;
    /* R17's lane mask, or NULL for every lane. Bit i of the buffer is
     * lane i of the RUN - global, so a block of this loop reads bits
     * off + i and not bits 0..k, the same rule the index tables have
     * one field along. */
    const uint8_t *msk = A->lane_mask;
    uint8_t *pso = (uint8_t *)A->scratch_out;
    uint8_t *pd = (uint8_t *)deposits;
    size_t esz, off;
    uint32_t acc_flags = 0, acc_status = 0;
    uint32_t scr_reach = 0;
    seq_block *B;
    cft_bn *loaded = NULL;
    const cft_bn *konst;

    if (n == 0) {
        cft_flags_emit(prog->dev, 0, flags);
        return CFT_OK;
    }
    if (!A->a || (!deposits && prog->max_deposits)) {
        cft_set_error("cft_program_run_ex: %s", !A->a
                      ? "stream a is NULL"
                      : "deposits is NULL for a program that deposits");
        return CFT_ERR_INVALID_ARGUMENT;
    }

    esz = (size_t)prog->f->width / 8;
    if (prog->max_deposits &&
        n > ((size_t)-1) / prog->max_deposits / esz) {
        cft_set_error("cft_program_run_ex: n = %lu elements is more than "
                      "this library can size", (unsigned long)n);
        return CFT_ERR_INVALID_ARGUMENT;
    }

    /* The bank is read on the host - staged to the tile below, or
     * decoded by the software executor - so a resident buffer's device
     * bytes come home first (softfloat.h). Until 2026-09-26 a bank a run
     * had computed on the device was staged from the stale mirror, with
     * CFT_OK (verifier-V8, N2). The streams, the scratch block, the
     * tables and the mask are the backend's to bind or bring home. */
    {
        const cft_status hs =
            (cft_status)cft_host_in(prog->dev, bank, bank_bytes);
        if (hs != CFT_OK)
            return hs;
    }

#if defined(CFT_ENABLE_XRT) || !defined(CFT_NO_REMOTE)
    /* The device runs the program if the device is where it was
     * loaded. Everything above this line is argument checking that
     * both executors need; everything below is the software one.
     *
     * The two must agree bit for bit, and that is not an aspiration:
     * the tile's ALU is the same pipeline softfloat.c models
     * (docs/SEQUENCER.md P1), the deposit address is a function of the
     * element index alone (P2), and the early exit changes only how
     * long the run takes (P3). So this is a dispatch and not a second
     * implementation - which is why it hands over the IMAGE, the BANK
     * and the caller's own pointers and does nothing else.
     *
     * max_deposits == 0 was once listed here as a known divergence -
     * legal in software, refused by the tile. It is not one. The
     * model's validator accepts a zero budget, cft_seq refuses only
     * max_deposits > MAXD, and SEQUENCER.md's list of what the loader
     * throws back never mentioned zero; a header check that demanded
     * one slot would have been the hardware inventing a rule the
     * contract does not state. Both executors now run such a program,
     * overflow every deposit into the status bit, and write nothing -
     * which is the agreement this comment used to apologise for
     * lacking. Nothing here pre-empts it either way, for the reason
     * that has not changed: a host-side rule neither the model nor the
     * tile states is how two executors start drifting for real. */
    {
        void *hw = cft_device_backend(prog->dev);
        if (hw) {
            uint32_t fl = 0, bs = 0;
            cft_seq_run_io io;
            cft_status st;
            io.bank              = bank;
            io.bank_bytes        = bank_bytes;
            io.scratch_in        = A->scratch_in;
            io.scratch_in_bytes  = A->scratch_in_bytes;
            io.scratch_out       = A->scratch_out;
            io.scratch_out_bytes = A->scratch_out_bytes;
            io.n_scratch_in      = prog->n_scratch_in;
            io.n_scratch_out     = prog->n_scratch_out;
            /* ABI 0.14's tables, handed across unchanged: the backend
             * binds or stages them and the TILE does the gather, which
             * is the whole point of the feature - a host-side gather is
             * the round trip per element the ask exists to remove.
             * Every field is set, including the mask's, because `io` is
             * an automatic and a field nobody assigns is whatever was
             * on the stack. */
            io.idx_a             = A->idx_a;
            io.idx_b             = A->idx_b;
            io.idx_c             = A->idx_c;
            io.idx_scratch_in    = A->idx_scratch_in;
            io.idx_a_src         = A->idx_a_src;
            io.idx_b_src         = A->idx_b_src;
            io.idx_c_src         = A->idx_c_src;
            io.idx_scratch_src   = A->idx_scratch_src;
            io.lane_mask         = A->lane_mask;
            io.lane_mask_bytes   = A->lane_mask_bytes;
            /* ABI 0.17's block, handed across as the mask is: device.c
             * refuses it by name where the device does not publish
             * CFT_SEQ_FEAT_LANE_FLAGS, and a backend that does writes a
             * byte a lane the caller has. */
            io.lane_flags        = A->lane_flags;
            io.lane_flags_bytes  = A->lane_flags_bytes;
            /* Which device backend is device.c's business: the
             * dispatcher in backend.h hands the run to the XRT one or
             * the remote one (docs/REMOTE.md) and this file names
             * neither. */
            st = (cft_status)cft_backend_program_run(
                prog->dev, prog->fmt_code, prog->image, prog->image_bytes,
                &io,
                prog->max_deposits, A->a, A->b, A->c, deposits, counts, n,
                &fl, &bs);
            if (st == CFT_OK) {
                cft_flags_emit(prog->dev, fl, flags);
                if (bus)
                    *bus = bs;
            }
            return st;
        }
    }
#endif

    /* The bank, decoded once for the whole run. A constant cannot
     * change during a run - that is what makes it a constant - so it
     * is decoded here and not per block, exactly as the image's own
     * constants are decoded once at load. */
    if (bank_bytes) {
        size_t i;
        loaded = (cft_bn *)calloc(prog->n_consts, sizeof(cft_bn));
        if (!loaded)
            return CFT_ERR_OUT_OF_MEMORY;
        for (i = 0; i < prog->n_consts; i++)
            cft_bn_load(&loaded[i], (const uint8_t *)bank + i * esz,
                        (int)esz);
    }
    konst = loaded ? loaded : prog->consts;

    /* Every slot is written, including ones no lane deposits into: an
     * untouched slot reads as +0 by definition, and a run that left
     * the caller's previous contents there would not be reproducible.
     *
     * Except a MASKED lane's slots (R17), which are the one thing in
     * this buffer that is NOT this run's to write: the caller keeps
     * its bytes. So the zero-fill is per lane when there is a mask and
     * one memset when there is not - the same bytes in the same order
     * either way, and no run written before the mask existed pays for
     * the loop. */
    if (pd && prog->max_deposits) {
        if (!msk) {
            memset(pd, 0, n * prog->max_deposits * esz);
        } else {
            size_t i;
            for (i = 0; i < n; i++)
                if (msk[i >> 3] & (uint8_t)(1u << (i & 7u)))
                    memset(pd + i * prog->max_deposits * esz, 0,
                           prog->max_deposits * esz);
        }
    }

    B = (seq_block *)calloc(1, sizeof *B);
    if (!B) {
        free(loaded);
        return CFT_ERR_OUT_OF_MEMORY;
    }
    /* The scratch, only for a program that has one. Out of line and
     * conditional because it is four megabytes across a lane block at
     * 256 slots (34 at 2,048), and every program written before
     * revision 3 touches none of it. At the program's depth, which is
     * its handle's (revision 7). */
    B->depth = prog->scratch_depth;
    if (prog->scratch_active) {
        B->scratch = (cft_bn *)calloc((size_t)BLOCK_LANES * B->depth,
                                      sizeof(cft_bn));
        if (!B->scratch) {
            free(B);
            free(loaded);
            return CFT_ERR_OUT_OF_MEMORY;
        }
    }
    /* What of a lane's scratch a block has to clear: every slot the
     * program can observe - the whole depth when it indexes
     * (scratch_used says so), else its highest static slot and the
     * slots its block reads in and out. Nothing above that is ever read
     * or written, so its contents are not a value any program can
     * distinguish; the tile's per-block wipe is bounded by the same rule
     * (and since revision 7 stops sooner, where nothing has written).
     * calloc zeroed all of it for the first block. */
    if (prog->scratch_active) {
        scr_reach = prog->scratch_used;
        if (prog->n_scratch_in > scr_reach)
            scr_reach = prog->n_scratch_in;
        if (prog->n_scratch_out > scr_reach)
            scr_reach = prog->n_scratch_out;
        if (scr_reach > B->depth)
            scr_reach = B->depth;
    }

    for (off = 0; off < n; off += BLOCK_LANES) {
        size_t k = n - off < BLOCK_LANES ? n - off : BLOCK_LANES;
        size_t i;
        cft_status st;

        for (i = 0; i < k; i++) {
            int r;
            for (r = 0; r < SEQ_NREG; r++)
                cft_bn_zero(&B->regs[i][r]);
            /* The GLOBAL lane index, off + i, indexes the table as it
             * indexes the dense stream: the table is the caller's, over
             * the whole run, and this loop is a block of it. Slicing it
             * per block is the trap R16 names - a table sliced by beat
             * rather than by lane reads a plausible neighbour's element
             * and no assertion catches it. */
            seq_load_in(&B->regs[i][0], pa, ia, off + i, esz);
            if (pb)
                seq_load_in(&B->regs[i][1], pb, ib, off + i, esz);
            if (pc_)
                seq_load_in(&B->regs[i][2], pc_, ic, off + i, esz);
            /* R17: a lane the mask clears starts inactive and stays
             * that way - ACTALL reactivates the lanes the CALLER has
             * and this is not one, which seq_run_block reads out of
             * the same array. The bit is the GLOBAL lane's. */
            B->keep[i] = (!msk ||
                (msk[(off + i) >> 3] & (uint8_t)(1u << ((off + i) & 7u))))
                    ? 1 : 0;
            B->active[i] = B->keep[i];
            B->counts[i] = 0;
            B->lflags[i] = 0;       /* R23: every run starts at zero */
            /* "Slots start at +0 for every lane at the start of a run,
             * except where R5 preloads them" - so every slot is zeroed
             * for every block, and then the block's first n_scratch_in
             * are overwritten from the caller's buffer. Lane-major:
             * lane i's slot s is element i * n_scratch_in + s of a
             * block n * n_scratch_in elements long, and the lane index
             * is the GLOBAL one, which is what makes a run split into
             * lane blocks read the same bytes as a run in one. */
            if (B->scratch) {
                uint32_t s;
                memset(&B->scratch[i * B->depth], 0,
                       (size_t)scr_reach * sizeof(cft_bn));
                for (s = 0; psi && s < prog->n_scratch_in; s++)
                    seq_load_in(&B->scratch[i * B->depth + s], psi,
                                isi,
                                (off + i) * prog->n_scratch_in + s, esz);
            }
        }

        st = seq_run_block(prog, konst, B, (int)k, pd, off, esz,
                           &acc_flags, &acc_status);
        if (st != CFT_OK) {
            free(B->scratch);
            free(B);
            free(loaded);
            return st;
        }
        /* ...and a masked lane's count is not written either (R17): the
         * caller's array keeps what it held, which is what the tile
         * does by leaving that lane's four bytes unstrobed. */
        if (counts)
            for (i = 0; i < k; i++)
                if (B->keep[i])
                    counts[off + i] = B->counts[i];
        /* R23's block (ABI 0.17), on the counts' terms: lane i's byte at
         * byte i, for the lanes the caller has - a masked lane's is the
         * caller's and is not written. */
        if (A->lane_flags)
            for (i = 0; i < k; i++)
                if (B->keep[i])
                    A->lane_flags[off + i] = B->lflags[i];
        /* And the block's scratch-out, after its last deposit. Every
         * element is written, including a slot no instruction ever
         * stored to: it reads as +0, which is the same normative rule
         * the deposit buffer has and for the same reason. */
        if (pso && prog->n_scratch_out) {
            uint32_t s;
            for (i = 0; i < k; i++)
                /* Not masked by the ACTIVE bit - a lane that converged
                 * early still has state worth carrying - and masked by
                 * the CALLER'S bit, because a lane the caller did not
                 * give this run has no state of this run's at all.
                 * R17's one place where the two questions differ. */
                if (B->keep[i]) {
                    for (s = 0; s < prog->n_scratch_out; s++)
                        cft_bn_store(&B->scratch[i * B->depth + s],
                                     pso + ((off + i) * prog->n_scratch_out
                                            + s) * esz,
                                     (int)esz);
                }
        }
    }

    free(B->scratch);
    free(B);
    free(loaded);
    cft_flags_emit(prog->dev, acc_flags, flags);
    /* A deposit overflow is reported, not an error. The deposits that
     * fit are correct and the run is reproducible; what the caller
     * lost is the tail, and it needs to know that without being told
     * its results are invalid - which is what CFT_ERR_BUS_FAULT
     * means and this is not. */
    if (bus)
        *bus = acc_status;
    return CFT_OK;
}

/* The one entry point. Everything a run can carry, in one struct
 * (ABI 0.10, docs/SEQUENCER.md revision 3).
 *
 * The struct is an INPUT, which reverses the size handshake cft_caps
 * and cft_program_info use: an output struct is TRUNCATED to what the
 * caller can hold, and truncating an input would mean silently
 * ignoring fields a newer caller set. A run that quietly dropped a
 * scratch block is precisely the failure every byte-count rule here
 * exists to prevent, so a size this library does not recognise is
 * refused, in both directions and with a different message for each. */
/* ABI 0.14's fields (docs/ROUND2.md): the index tables of the three
 * streams and the scratch block, and the lane mask. The SHAPE rules are
 * the seam's and final, and R16's bound on every index is checked here
 * too, before the run, on every backend. A well-formed table or mask is
 * then CARRIED - by seq_program_run on the software backend, by the
 * device backend otherwise, which refuses it BY NAME on a tile that
 * does not publish the feature (device.c) - and never ignored: a run
 * that quietly read the dense stream, or ran every lane, would return
 * the wrong answer with clean flags. Until P1 (the tables) and P3 (the
 * mask) landed on 2026-09-15 this refused every one by name. */
static cft_status seq_check_round2(const cft_program *p,
                                   const cft_run_args *A, const char *who)
{
    const uint32_t *idx[3];
    size_t src[3];
    const void *strm[3];
    int r;

    idx[0] = A->idx_a; idx[1] = A->idx_b; idx[2] = A->idx_c;
    src[0] = A->idx_a_src; src[1] = A->idx_b_src; src[2] = A->idx_c_src;
    strm[0] = A->a; strm[1] = A->b; strm[2] = A->c;
    for (r = 0; r < 3; r++) {
        if (!idx[r]) {
            if (src[r]) {
                cft_set_error("%s: idx_%c_src = %lu names a source length "
                              "for stream %c, which has no index table",
                              who, 'a' + r, (unsigned long)src[r], 'a' + r);
                return CFT_ERR_INVALID_ARGUMENT;
            }
            continue;
        }
        if (!strm[r]) {
            cft_set_error("%s: idx_%c indexes stream %c, which is NULL",
                          who, 'a' + r, 'a' + r);
            return CFT_ERR_INVALID_ARGUMENT;
        }
        if (src[r] == 0) {
            cft_set_error("%s: idx_%c is set and idx_%c_src is zero, so no "
                          "index could be in range - the source's length "
                          "in elements is what bounds the table",
                          who, 'a' + r, 'a' + r);
            return CFT_ERR_INVALID_ARGUMENT;
        }
    }
    if (!A->idx_scratch_in && A->idx_scratch_src) {
        cft_set_error("%s: idx_scratch_src = %lu names a pool length with "
                      "no idx_scratch_in table", who,
                      (unsigned long)A->idx_scratch_src);
        return CFT_ERR_INVALID_ARGUMENT;
    }
    if (A->idx_scratch_in) {
        if (p->n_scratch_in == 0) {
            cft_set_error("%s: idx_scratch_in is set and this program "
                          "declares no scratch input - there is no block "
                          "to gather into", who);
            return CFT_ERR_INVALID_ARGUMENT;
        }
        if (!A->scratch_in) {
            cft_set_error("%s: idx_scratch_in indexes scratch_in, which is "
                          "NULL", who);
            return CFT_ERR_INVALID_ARGUMENT;
        }
        if (A->idx_scratch_src == 0) {
            cft_set_error("%s: idx_scratch_in is set and idx_scratch_src "
                          "is zero, so no index could be in range", who);
            return CFT_ERR_INVALID_ARGUMENT;
        }
    }
    if (!A->lane_mask && A->lane_mask_bytes) {
        cft_set_error("%s: lane_mask_bytes = %lu with no lane_mask", who,
                      (unsigned long)A->lane_mask_bytes);
        return CFT_ERR_INVALID_ARGUMENT;
    }
    if (A->lane_mask && A->lane_mask_bytes != (A->n + 7u) / 8u) {
        cft_set_error("%s: lane_mask_bytes is %lu and a mask over %lu lanes "
                      "is exactly %lu bytes - a mask of the wrong length "
                      "would give lanes somebody else's bit", who,
                      (unsigned long)A->lane_mask_bytes, (unsigned long)A->n,
                      (unsigned long)((A->n + 7u) / 8u));
        return CFT_ERR_INVALID_ARGUMENT;
    }
    /* ABI 0.17 (docs/SEQUENCER.md R23): the per-lane flags block, on the
     * mask's rule and for the mask's reason. The two are byte arrays a
     * run's lanes size, (n + 7) / 8 of bits and n of flags, and a caller
     * that sized one by the other is told rather than overrun. */
    if (!A->lane_flags && A->lane_flags_bytes) {
        cft_set_error("%s: lane_flags_bytes = %lu with no lane_flags", who,
                      (unsigned long)A->lane_flags_bytes);
        return CFT_ERR_INVALID_ARGUMENT;
    }
    if (A->lane_flags && A->lane_flags_bytes != A->n) {
        cft_set_error("%s: lane_flags_bytes is %lu and the per-lane flags "
                      "of %lu lanes are exactly %lu bytes, a byte a lane - "
                      "not a mask's (n + 7) / 8", who,
                      (unsigned long)A->lane_flags_bytes, (unsigned long)A->n,
                      (unsigned long)A->n);
        return CFT_ERR_INVALID_ARGUMENT;
    }
    /* The bound, checked BEFORE the run on every backend (R16): an
     * index at or past the source's declared length is refused by name
     * and by value, because a device must never read past a buffer for
     * a caller - and a check made here is one the tile, the software
     * executor and the model all inherit without any of them having to
     * agree on what a bad index would have computed.
     *
     * Every entry is examined, including a padding lane's: the run's
     * last block is padded up to the tile's lane block and the check
     * has to be the same on both executors, so "the lanes the caller
     * has" is n and nothing else. CFT_IDX_NONE is not an index and is
     * never out of range.
     *
     * The check READS each table on the host, so each is brought home
     * first (softfloat.h's cft_host_in), the scratch-in table too. Until
     * 2026-09-27 a table a device run had written into a resident buffer
     * was checked on the stale mirror: an out-of-range index the device
     * held ran with CFT_OK, and a valid one over a bad mirror was refused
     * (verifier-V9). A table in a LOST buffer is refused by that
     * sentence. */
    if (A->n) {
        for (r = 0; r < 3; r++) {
            cft_status hs;
            if (!idx[r])
                continue;
            hs = (cft_status)cft_host_in(p->dev, idx[r], A->n * 4u);
            if (hs != CFT_OK)
                return hs;
        }
        if (A->idx_scratch_in) {
            const cft_status hs = (cft_status)cft_host_in(
                p->dev, A->idx_scratch_in,
                A->n * (size_t)p->n_scratch_in * 4u);
            if (hs != CFT_OK)
                return hs;
        }
    }
    for (r = 0; r < 3; r++) {
        size_t i;
        if (!idx[r])
            continue;
        for (i = 0; i < A->n; i++) {
            if (idx[r][i] == CFT_IDX_NONE)
                continue;
            if ((size_t)idx[r][i] >= src[r]) {
                cft_set_error("%s: idx_%c[%lu] = %lu is at or past the %lu "
                              "elements idx_%c_src says stream %c holds",
                              who, 'a' + r, (unsigned long)i,
                              (unsigned long)idx[r][i],
                              (unsigned long)src[r], 'a' + r, 'a' + r);
                return CFT_ERR_INVALID_ARGUMENT;
            }
        }
    }
    if (A->idx_scratch_in) {
        size_t e, entries;
        /* n * n_scratch_in entries, lane-major as the block is. The
         * product cannot overflow: seq_check_scratch has already held
         * the block to a byte count this process can address. */
        entries = A->n * (size_t)p->n_scratch_in;
        for (e = 0; e < entries; e++) {
            if (A->idx_scratch_in[e] == CFT_IDX_NONE)
                continue;
            if ((size_t)A->idx_scratch_in[e] >= A->idx_scratch_src) {
                cft_set_error("%s: idx_scratch_in[%lu] = %lu (lane %lu slot "
                              "%lu) is at or past the %lu elements "
                              "idx_scratch_src says the pool holds",
                              who, (unsigned long)e,
                              (unsigned long)A->idx_scratch_in[e],
                              (unsigned long)(e / p->n_scratch_in),
                              (unsigned long)(e % p->n_scratch_in),
                              (unsigned long)A->idx_scratch_src);
                return CFT_ERR_INVALID_ARGUMENT;
            }
        }
    }
    /* R17 needs no check of its own beyond the two shapes above. A
     * mask BIT cannot be out of range the way an index can - it names
     * a lane of this run and nothing else - so the byte count is the
     * whole of it, and the executor below reads the bits. */
    return CFT_OK;
}

CFT_API cft_status cft_program_run_ex(cft_program *prog,
                                      const cft_run_args *args)
{
    cft_run_args A;
    cft_status st;

    if (!prog || !args)
        return CFT_ERR_INVALID_ARGUMENT;
    if (args->struct_size != sizeof(cft_run_args)) {
        cft_set_error("cft_program_run_ex was given a %lu-byte "
                      "cft_run_args and this library's is %lu bytes: %s. "
                      "Zero the struct and set struct_size to "
                      "sizeof(cft_run_args)",
                      (unsigned long)args->struct_size,
                      (unsigned long)sizeof(cft_run_args),
                      args->struct_size < sizeof(cft_run_args)
                        ? "a struct this short is missing a field this "
                          "call reads"
                        : "the fields past the end of this library's "
                          "struct would be ignored, and a run that "
                          "silently dropped one of them is what the byte "
                          "counts exist to prevent");
        return CFT_ERR_INVALID_ARGUMENT;
    }
    A = *args;
    if (A.bus_out)
        *A.bus_out = 0;
    /* The arguments that bound every byte this run will READ are checked
     * before any rule that reads a caller's buffer: seq_check_scratch
     * sizes the block from n, and seq_check_round2 walks the index tables
     * for n entries. A rule that dereferences a caller's buffer belongs
     * behind every rule that does not (V2's finding in P2's cft_run_ex,
     * and V3's reading of its twin here, 2026-09-15). The same three
     * tests stand in seq_program_run as the last line, where they were
     * alone until now and said nothing; n == 0 is the no-op run and is
     * not refused for a NULL stream, as it never was. */
    if (A.n != 0) {
        const size_t esz = (size_t)prog->f->width / 8;
        if (!A.a) {
            cft_set_error("cft_program_run_ex: stream a is NULL - a program "
                          "run requires its first stream, which initialises "
                          "r0 in every lane");
            return CFT_ERR_INVALID_ARGUMENT;
        }
        if (!A.deposits && prog->max_deposits) {
            cft_set_error("cft_program_run_ex: deposits is NULL for a "
                          "program with max_deposits = %u",
                          (unsigned)prog->max_deposits);
            return CFT_ERR_INVALID_ARGUMENT;
        }
        {
            /* the bytes one lane reads and writes: its element in each
             * stream and its deposit slots; a program with no deposit
             * slot still reads n elements a stream */
            const size_t per = esz * (prog->max_deposits ? prog->max_deposits
                                                          : 1u);
            if (A.n > ((size_t)-1) / per) {
                cft_set_error("cft_program_run_ex: n = %llu elements is more "
                              "than this library can size (max_deposits "
                              "%u, %llu bytes an element) - refused before "
                              "any table or mask is read",
                              (unsigned long long)A.n,
                              (unsigned)prog->max_deposits,
                              (unsigned long long)esz);
                return CFT_ERR_INVALID_ARGUMENT;
            }
        }
    }
    st = seq_check_bank(prog, A.bank, A.bank_bytes, "cft_program_run_ex");
    if (st != CFT_OK)
        return st;
    st = seq_check_scratch(prog, &A, "cft_program_run_ex");
    if (st != CFT_OK)
        return st;
    st = seq_check_round2(prog, &A, "cft_program_run_ex");
    if (st != CFT_OK)
        return st;
    if (!A.bank_bytes)
        A.bank = NULL;
    return seq_program_run(prog, &A);
}

/* The two older calls, as wrappers that fill the struct.
 *
 * Wrappers and not second implementations: every check, every buffer
 * shape and every answer is the one above, so the three cannot drift.
 * What each adds is the refusal that names the call the caller wanted
 * instead. */
static void seq_args_init(cft_run_args *A, const void *a, const void *b,
                          const void *c, void *deposits, uint32_t *counts,
                          size_t n, uint32_t *flags, uint32_t *bus)
{
    memset(A, 0, sizeof *A);
    A->struct_size = sizeof *A;
    A->a = a; A->b = b; A->c = c;
    A->n = n;
    A->deposits = deposits;
    A->counts   = counts;
    A->flags_out = flags;
    A->bus_out   = bus;
}

/* A program that declares scratch I/O takes run_ex and nothing else.
 * Neither of the two calls below has a place to put the blocks, and
 * running such a program without them would preload every lane with
 * +0 the caller never chose and drop the block it was going to read
 * back - the same argument BANK_EXT made about constants, about a
 * different kind of data. */
static cft_status seq_refuse_scratch_io(const cft_program *p,
                                        const char *who)
{
    if (!(p->flags & CFT_PROG_FLAG_SCRATCH_IO))
        return CFT_OK;
    cft_set_error("this program's header flags carry SCRATCH_IO, so every "
                  "run preloads %lu scratch slots a lane and reads %lu "
                  "back, and %s has nowhere to put them; call "
                  "cft_program_run_ex",
                  (unsigned long)p->n_scratch_in,
                  (unsigned long)p->n_scratch_out, who);
    return CFT_ERR_INVALID_ARGUMENT;
}

CFT_API cft_status cft_program_run(cft_program *prog,
                                   const void *a, const void *b,
                                   const void *c,
                                   void *deposits, uint32_t *counts,
                                   size_t n,
                                   uint32_t *flags, uint32_t *bus)
{
    cft_run_args A;
    cft_status st;

    if (bus)
        *bus = 0;
    if (!prog)
        return CFT_ERR_INVALID_ARGUMENT;
    /* A BANK_EXT program has no constants of its own, and running it
     * with none at all would compute on a bank of +0 that the caller
     * never chose. Refused by name rather than defaulted: the whole
     * point of the flag is that the numbers ride as data. */
    if (prog->flags & CFT_PROG_FLAG_BANK_EXT) {
        cft_set_error("this program's header flags carry BANK_EXT, so its "
                      "%lu constants arrive with each run; call "
                      "cft_program_run_bank",
                      (unsigned long)prog->n_consts);
        return CFT_ERR_INVALID_ARGUMENT;
    }
    st = seq_refuse_scratch_io(prog, "cft_program_run");
    if (st != CFT_OK)
        return st;
    seq_args_init(&A, a, b, c, deposits, counts, n, flags, bus);
    return cft_program_run_ex(prog, &A);
}

CFT_API cft_status cft_program_run_bank(cft_program *prog,
                                        const void *bank, size_t bank_bytes,
                                        const void *a, const void *b,
                                        const void *c,
                                        void *deposits, uint32_t *counts,
                                        size_t n,
                                        uint32_t *flags_out,
                                        uint32_t *bus_out)
{
    cft_run_args A;
    cft_status st;

    if (bus_out)
        *bus_out = 0;
    if (!prog)
        return CFT_ERR_INVALID_ARGUMENT;
    st = seq_check_bank(prog, bank, bank_bytes, "cft_program_run_bank");
    if (st != CFT_OK)
        return st;
    st = seq_refuse_scratch_io(prog, "cft_program_run_bank");
    if (st != CFT_OK)
        return st;
    seq_args_init(&A, a, b, c, deposits, counts, n, flags_out, bus_out);
    A.bank       = bank;
    A.bank_bytes = bank_bytes;
    return cft_program_run_ex(prog, &A);
}

/* ---- attestation --------------------------------------------------- */

CFT_API cft_status cft_program_digest(cft_program *prog,
                                      const void *bank, size_t bank_bytes,
                                      uint8_t out[32])
{
    cft_sha256_ctx s;
    cft_status st;

    if (!prog || !out)
        return CFT_ERR_INVALID_ARGUMENT;
    /* The same bank rule as the run, deliberately: a digest over a
     * bank the program could not have run is a name for nothing, and a
     * program that has two ways to be digested has no name at all. */
    st = seq_check_bank(prog, bank, bank_bytes, "cft_program_digest");
    if (st != CFT_OK)
        return st;
    /* read on the host, as the run's is (seq_program_run) */
    st = (cft_status)cft_host_in(prog->dev, bank, bank_bytes);
    if (st != CFT_OK)
        return st;
    /* ...and the digest WRITTEN on the host: this call's result,
     * announced as every entry point's is (softfloat.h's cft_host_out),
     * so a device copy over it is not served afterwards and a LOST
     * buffer refuses it. Until 2026-09-27 it was neither announced nor
     * among the out-parameters cft.h lists, and a run after it read
     * the bytes from before (verifier-V9). */
    st = (cft_status)cft_host_out(prog->dev, out, 32);
    if (st != CFT_OK)
        return st;
    /* The IMAGE bytes, not the parsed form - the same reason the image
     * is kept whole and handed to a device whole. Then the bank, so
     * that what ran is one hash of program and data together. */
    cft_sha256_init(&s);
    cft_sha256_update(&s, prog->image, prog->image_bytes);
    if (bank_bytes)
        cft_sha256_update(&s, bank, bank_bytes);
    cft_sha256_final(&s, out);
    return CFT_OK;
}

#else  /* CFT_NO_PROGRAM */

/* An empty translation unit is not strictly conforming C99 and
 * -Wpedantic says so, so leave one declaration behind. */
typedef int cft_program_module_omitted;

#endif /* CFT_NO_PROGRAM */
