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
 * block must be at least the ALU's 15-stage latency for the pipeline
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
 * caps it enforces. They are NOT the tile's - a tile holds 64 deposit
 * slots a lane, 1024 instructions - and they are deliberately not
 * narrowed to match one, because the software backend is the
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
 * max_consts is the number of constants an instruction can ADDRESS,
 * which is the four-bit ka/kb/kc operand field's reach and is the
 * same 16 in the tile (rtl/cft_seq.sv's KREG). It is not the header's
 * n_consts, which may legally be larger and simply leaves the excess
 * unreachable. */
#define SEQ_MAX_DEPOSITS (1uL << 20)
#define SEQ_IMAGE_INSNS  0xFFFFFFFFu
#define SEQ_ADDR_CONSTS  512u  /* with kx (2026-09-07) an instruction's
                                * 8-bit indices reach 256 of the bank,
                                * and with the ninth bits of revision 3
                                * (kx9, imm[30:28]) the whole 512; the
                                * 4-bit fields still reach 16 */

/* The scratch memory's depth, a lane's own (docs/SEQUENCER.md revision
 * 3, R4). ONE define: it is the executor's array bound, the modulus
 * STX and LDX reduce by, the ceiling a static STL or LDL slot is held
 * to, and the number cft_sw_seq_caps publishes as max_scratch - and a
 * second copy of it is how those four start to disagree. */
#define SEQ_SCRATCH_D    256u
#define SEQ_SCRATCH_LOG2 8     /* log2(SEQ_SCRATCH_D), the width of the
                                * index STX and LDX read out of rb */

#define BLOCK_LANES      64

/* control codes */
enum { SEQ_HALT = 0, SEQ_REPEAT, SEQ_ENDREP, SEQ_DEPOSIT, SEQ_SETACT,
       SEQ_ACTALL, SEQ_STL, SEQ_LDL, SEQ_STX, SEQ_LDX };

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
 * cft.h publishes CFT_PROG_FLAG_BANK_EXT and, since revision 3,
 * CFT_PROG_FLAG_SCRATCH_IO; this is the mask of every bit this library
 * knows, and a set bit outside it is CFT_ERR_ARTIFACT. */
#define SEQ_FLAGS_KNOWN  ((uint32_t)CFT_PROG_FLAG_BANK_EXT | \
                          (uint32_t)CFT_PROG_FLAG_SCRATCH_IO)

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
     * SEQ_SCRATCH_D slots a lane and a program that never touches one
     * should not pay four megabytes a run for the possibility. */
    int                 scratch_active;
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
 * as the version guard for whatever comes next. */
static cft_status seq_check_operands(const cft_program *p,
                                     const seq_insn *d)
{
    static const int shift[3] = { SEQ_KX_SHIFT_A, SEQ_KX_SHIFT_B,
                                  SEQ_KX_SHIFT_C };
    const int reg[3] = { d->ra, d->rb, d->rc };
    const int hi[3]  = { d->ha, d->hb, d->hc };
    const int k9[3]  = { d->k9a, d->k9b, d->k9c };
    const int kf[3]  = { d->ka, d->kb, d->kc };
    int which;

    if (d->imm & SEQ_IMM_RESERVED)
        return CFT_ERR_INVALID_ARGUMENT;
    if (d->kx) {
        if (!(d->ka || d->kb || d->kc))
            return CFT_ERR_INVALID_ARGUMENT;
    } else if (d->imm & SEQ_KX_INDICES) {
        return CFT_ERR_INVALID_ARGUMENT;
    }
    if (!d->kx && (d->imm & SEQ_KX9_MASK))
        return CFT_ERR_INVALID_ARGUMENT;

    for (which = 0; which < 3; which++) {
        uint32_t byte = (d->imm >> shift[which]) & 0xFFu;
        uint32_t idx;
        if (kf[which] && hi[which])
            return CFT_ERR_INVALID_ARGUMENT;
        /* The ninth bit is read under `kx` for a constant operand and
         * nowhere else, so everywhere else it must be zero. */
        if (!(d->kx && kf[which]) && k9[which])
            return CFT_ERR_INVALID_ARGUMENT;
        if (d->kx && kf[which]) {
            if (reg[which])
                return CFT_ERR_INVALID_ARGUMENT;
            idx = byte | ((uint32_t)k9[which] << 8);
        } else if (d->kx) {
            if (byte)
                return CFT_ERR_INVALID_ARGUMENT;
            continue;
        } else if (kf[which]) {
            idx = (uint32_t)reg[which];
        } else {
            continue;
        }
        if (idx >= p->n_consts)
            return CFT_ERR_INVALID_ARGUMENT;
    }
    return CFT_OK;
}

/* Everything docs/SEQUENCER.md says the loader refuses. A program that
 * a device could execute ambiguously is stopped here, so the hardware
 * never has to decide what an ambiguous one means. */
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

    mult[0] = 1;
    for (pc = 0; pc < p->n_insns; pc++) {
        seq_insn d;
        cft_status ost;
        seq_decode(p->insns[pc], &d);

        worst += mult[top];
        if (worst > SEQ_MAX_INSNS)
            return CFT_ERR_INVALID_ARGUMENT;

        if (!d.ctrl) {
            ost = seq_check_operands(p, &d);
            if (ost != CFT_OK)
                return ost;
            if (d.rnd > 4)
                return CFT_ERR_INVALID_ARGUMENT;
            continue;
        }

        /* Fields a control instruction does not read must be zero, so
         * one operation has one encoding - otherwise a readback hash
         * is not a hash of the program.
         *
         * A control instruction reads at most `ra` (DEPOSIT, SETACT),
         * so of the four register high bits in imm[27:24] only those
         * two read one - imm[25], ra's - and that is the single
         * relaxation revision 2 makes here: their `imm` was required
         * to be zero whole and is now required to be zero but for that
         * bit. HALT, ENDREP and ACTALL read no field of `imm` at all
         * and it stays zero whole.
         *
         * REPEAT is the exception and reads its `imm` ENTIRELY, as the
         * trip count - it always has. The canonicity rule is about
         * fields an instruction does not read, so it reaches nothing
         * here: constraining imm[27:24] on a REPEAT would refuse every
         * trip count at or above 2^24, including the `repeat
         * 0xffffffff` docs/SEQUENCER.md's own worst-case paragraph
         * relies on being loadable and refused by the 2^40 bound
         * instead. docs/HOSTAPI.md records the reading. */
        switch (d.op) {
        case SEQ_HALT:
        case SEQ_ENDREP:
        case SEQ_ACTALL:
            if (d.rd || d.ra || d.rb || d.rc || d.rnd || d.ka || d.kb ||
                d.kc || d.kx || d.imm)
                return CFT_ERR_INVALID_ARGUMENT;
            break;
        case SEQ_REPEAT:
            if (d.rd || d.ra || d.rb || d.rc || d.rnd || d.ka || d.kb ||
                d.kc || d.kx)
                return CFT_ERR_INVALID_ARGUMENT;
            break;
        case SEQ_DEPOSIT:
        case SEQ_SETACT:
            if (d.rd || d.rb || d.rc || d.rnd || d.ka || d.kb || d.kc ||
                d.kx ||
                (d.imm & ~(uint32_t)(1u << (SEQ_REGHI_SHIFT + 1))))
                return CFT_ERR_INVALID_ARGUMENT;
            break;
        /* The four scratch codes of revision 3, R4. The reserved-field
         * rule settles each of them and adds nothing new: STL reads
         * `ra` and imm[23:0]; LDL writes `rd` and reads imm[23:0]; STX
         * reads `ra` and `rb`; LDX writes `rd` and reads `rb`, and for
         * those last two imm[23:0] is a field nothing reads. Every
         * other field - the remaining register fields, `rnd`, the `k`
         * flags, `kx`, and the parts of imm[31:24] that are not the
         * high bit of a register this instruction names - must be
         * zero.
         *
         * The slot of a static form is checked against the DEVICE's
         * depth rather than here, exactly as a constant index is: what
         * bounds it is a capacity a tile publishes, not a property of
         * the encoding. */
        case SEQ_STL:
            if (d.rd || d.rb || d.rc || d.rnd || d.ka || d.kb || d.kc ||
                d.kx ||
                (d.imm & ~(SEQ_KX_INDICES |
                           (uint32_t)(1u << (SEQ_REGHI_SHIFT + 1)))))
                return CFT_ERR_INVALID_ARGUMENT;
            break;
        case SEQ_LDL:
            if (d.ra || d.rb || d.rc || d.rnd || d.ka || d.kb || d.kc ||
                d.kx ||
                (d.imm & ~(SEQ_KX_INDICES |
                           (uint32_t)(1u << (SEQ_REGHI_SHIFT + 0)))))
                return CFT_ERR_INVALID_ARGUMENT;
            break;
        case SEQ_STX:
            if (d.rd || d.rc || d.rnd || d.ka || d.kb || d.kc || d.kx ||
                (d.imm & ~(uint32_t)((1u << (SEQ_REGHI_SHIFT + 1)) |
                                     (1u << (SEQ_REGHI_SHIFT + 2)))))
                return CFT_ERR_INVALID_ARGUMENT;
            break;
        case SEQ_LDX:
            if (d.ra || d.rc || d.rnd || d.ka || d.kb || d.kc || d.kx ||
                (d.imm & ~(uint32_t)((1u << (SEQ_REGHI_SHIFT + 0)) |
                                     (1u << (SEQ_REGHI_SHIFT + 2)))))
                return CFT_ERR_INVALID_ARGUMENT;
            break;
        default:
            return CFT_ERR_INVALID_ARGUMENT;
        }

        if (d.op == SEQ_REPEAT) {
            if (d.imm == 0 || depth >= SEQ_MAX_DEPTH)
                return CFT_ERR_INVALID_ARGUMENT;
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
             * mult * imm > MAX. */
            if (d.imm > SEQ_MAX_INSNS / mult[top - 1])
                return CFT_ERR_INVALID_ARGUMENT;
            mult[top] = mult[top - 1] * d.imm;
        } else if (d.op == SEQ_ENDREP) {
            if (depth == 0)
                return CFT_ERR_INVALID_ARGUMENT;
            depth--;
            top--;
        } else if ((d.op == SEQ_ACTALL || d.op == SEQ_HALT) && depth > 0) {
            /* Both would make the all-lanes-done early exit
             * observable - ACTALL because it can reactivate a lane,
             * HALT because its effect is not per-lane and so the
             * active mask cannot gate it. */
            return CFT_ERR_INVALID_ARGUMENT;
        }
    }
    return depth == 0 ? CFT_OK : CFT_ERR_INVALID_ARGUMENT;
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
                        CFT_SEQ_FEAT_SCRATCH_IO;
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
 * declare more constants than it can reach (they are simply
 * unreachable), and what a device refuses to execute is a reference
 * past its bank. Structurally impossible on a device that addresses
 * all sixteen a four-bit field reaches, which is every device shipped
 * so far; it becomes real for a trimmed tile that publishes fewer, and
 * for the wide constant index CAPS[4] publishes.
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
                d.op == SEQ_STL     || d.op == SEQ_STX)
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
 * four megabytes a run. */
static void seq_scratch_footprint(cft_device *dev, cft_program *p)
{
    cft_seq_caps c;
    uint32_t depth, used = 0, pc;
    int indexed = 0, touched = 0;

    cft_device_seq_caps(dev, &c);
    depth = c.max_scratch ? c.max_scratch : SEQ_SCRATCH_D;

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
    uint32_t n_sin = 0, n_sout = 0;
    size_t esz, want, kbytes, i;
    cft_status st;

    if (!dev || !image || !out)
        return CFT_ERR_INVALID_ARGUMENT;
    *out = NULL;
    if (bytes < SEQ_HEADER_BYTES)
        return CFT_ERR_ARTIFACT;

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

    if (magic != SEQ_MAGIC || ver != SEQ_VERSION)
        return CFT_ERR_ARTIFACT;
    if (!(flags & CFT_PROG_FLAG_SCRATCH_IO) && scr_io)
        return CFT_ERR_ARTIFACT;
    /* A flag bit this library does not know is an image it cannot
     * read: the bit says something about the layout or the run, and
     * the honest answer to a sentence you cannot parse is not to
     * guess. This is the version guard for everything flags will ever
     * carry, which is why the round needed no VERSION step. */
    if (flags & ~SEQ_FLAGS_KNOWN)
        return CFT_ERR_ARTIFACT;
    if (prec > 3)
        return CFT_ERR_ARTIFACT;
    /* A program is compiled for one format, because its constants are
     * format-width values. Refuse it here rather than at the first
     * instruction that would issue a precision this device does not
     * carry. */
    if (!cft_supports(dev, CFT_FMA, (cft_format)prec))
        return CFT_ERR_UNSUPPORTED;
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
    /* The library's own absolute ceiling on a deposit budget, which is
     * about what this process can represent rather than about any
     * device. Only reachable when the device published no cap of its
     * own - cft_caps documents zero as unknown, and a remote server
     * older than those fields is the one thing that produces it. */
    if (maxdep > SEQ_MAX_DEPOSITS)
        return CFT_ERR_INVALID_ARGUMENT;

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
        /* And this library's own ceiling, which is its executor's
         * depth. Only reachable when the device published none. */
        if (n_sin > SEQ_SCRATCH_D || n_sout > SEQ_SCRATCH_D)
            return CFT_ERR_INVALID_ARGUMENT;
    }

    esz  = (size_t)cft_sf_formats[prec].width / 8;
    /* A BANK_EXT image is a header and an instruction stream, full
     * stop: n_consts says how many constants the program ADDRESSES,
     * and none of them is in the file. */
    kbytes = (flags & CFT_PROG_FLAG_BANK_EXT)
             ? 0 : (size_t)n_consts * esz;
    want = (size_t)SEQ_HEADER_BYTES + kbytes +
           (size_t)n_insns * SEQ_INSN_BYTES;
    /* Exactly, not at least: a program is its header, its constants
     * and its instructions, so anything else is a different program
     * and should not load as this one. */
    if (bytes != want)
        return CFT_ERR_ARTIFACT;

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
    uint32_t counts[BLOCK_LANES];
    /* SEQ_SCRATCH_D slots a lane, or NULL for a program that touches
     * no scratch and declares no block. Out of line rather than inside
     * this struct because at fp256 it is four megabytes to the
     * register file's half, and a program that never issues an STL
     * should not allocate and zero it once a run. Lane i's slot s is
     * scratch[i * SEQ_SCRATCH_D + s], and it is the lane's alone -
     * there is no cross-lane addressing in the contract and none
     * here. */
    cft_bn *scratch;
} seq_block;

/* Lane `lane`'s slot `slot`, or NULL when this program has no scratch.
 * The two callers below have both already refused to reach it in that
 * case, so the NULL is a defence and not a path. */
static cft_bn *seq_scratch_at(seq_block *B, int lane, uint32_t slot)
{
    if (!B->scratch || slot >= SEQ_SCRATCH_D)
        return NULL;
    return &B->scratch[(size_t)lane * SEQ_SCRATCH_D + slot];
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

static cft_status seq_run_block(const cft_program *p, const cft_bn *konst,
                                seq_block *B,
                                int nlane, uint8_t *deposits,
                                size_t first_elem, size_t esz,
                                uint32_t *flags, uint32_t *status)
{
    struct { uint32_t body; uint32_t left; } stack[SEQ_MAX_DEPTH];
    int sp = 0;
    uint32_t pc = 0;

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
                *flags |= fl;
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
                    *status |= CFT_STATUS_DEPOSIT_OVERFLOW;
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
            for (i = 0; i < nlane; i++)
                B->active[i] = 1;
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

        /* The indexed forms take the slot from the low log2(SCRATCH_D)
         * bits of `rb`'s BIT PATTERN, an unsigned integer where the
         * atlas emitter keeps its loop counters, reduced modulo the
         * depth. The reduction is part of the contract rather than an
         * accident, so it is done here and in the model alike and an
         * out-of-range index is never a refusal. */
        case SEQ_STX:
        case SEQ_LDX: {
            int rb = seq_reg(d.rb, d.hb);
            for (i = 0; i < nlane; i++) {
                cft_bn *cell;
                uint32_t slot;
                if (!B->active[i])
                    continue;
                slot = cft_bn_extract(&B->regs[i][rb], 0, SEQ_SCRATCH_LOG2)
                       & (SEQ_SCRATCH_D - 1u);
                cell = seq_scratch_at(B, i, slot);
                if (!cell)
                    return CFT_ERR_INTERNAL;
                if (d.op == SEQ_STX)
                    cft_bn_copy(cell, &B->regs[i][seq_reg(d.ra, d.ha)]);
                else
                    cft_bn_copy(&B->regs[i][seq_reg(d.rd, d.hd)], cell);
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
    uint8_t *pso = (uint8_t *)A->scratch_out;
    uint8_t *pd = (uint8_t *)deposits;
    size_t esz, off;
    uint32_t acc_flags = 0, acc_status = 0;
    seq_block *B;
    cft_bn *loaded = NULL;
    const cft_bn *konst;

    if (n == 0) {
        cft_flags_emit(prog->dev, 0, flags);
        return CFT_OK;
    }
    if (!A->a || (!deposits && prog->max_deposits))
        return CFT_ERR_INVALID_ARGUMENT;

    esz = (size_t)prog->f->width / 8;
    if (prog->max_deposits &&
        n > ((size_t)-1) / prog->max_deposits / esz)
        return CFT_ERR_INVALID_ARGUMENT;

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
     */
    if (pd && prog->max_deposits)
        memset(pd, 0, n * prog->max_deposits * esz);

    B = (seq_block *)calloc(1, sizeof *B);
    if (!B) {
        free(loaded);
        return CFT_ERR_OUT_OF_MEMORY;
    }
    /* The scratch, only for a program that has one. Out of line and
     * conditional because it is four megabytes at fp256 across a lane
     * block, and every program written before this evening touches
     * none of it. */
    if (prog->scratch_active) {
        B->scratch = (cft_bn *)calloc((size_t)BLOCK_LANES * SEQ_SCRATCH_D,
                                      sizeof(cft_bn));
        if (!B->scratch) {
            free(B);
            free(loaded);
            return CFT_ERR_OUT_OF_MEMORY;
        }
    }

    for (off = 0; off < n; off += BLOCK_LANES) {
        size_t k = n - off < BLOCK_LANES ? n - off : BLOCK_LANES;
        size_t i;
        cft_status st;

        for (i = 0; i < k; i++) {
            int r;
            for (r = 0; r < SEQ_NREG; r++)
                cft_bn_zero(&B->regs[i][r]);
            cft_bn_load(&B->regs[i][0], pa + (off + i) * esz, (int)esz);
            if (pb)
                cft_bn_load(&B->regs[i][1], pb + (off + i) * esz, (int)esz);
            if (pc_)
                cft_bn_load(&B->regs[i][2], pc_ + (off + i) * esz, (int)esz);
            B->active[i] = 1;
            B->counts[i] = 0;
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
                memset(&B->scratch[i * SEQ_SCRATCH_D], 0,
                       (size_t)SEQ_SCRATCH_D * sizeof(cft_bn));
                for (s = 0; psi && s < prog->n_scratch_in; s++)
                    cft_bn_load(&B->scratch[i * SEQ_SCRATCH_D + s],
                                psi + ((off + i) * prog->n_scratch_in + s)
                                      * esz,
                                (int)esz);
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
        if (counts)
            for (i = 0; i < k; i++)
                counts[off + i] = B->counts[i];
        /* And the block's scratch-out, after its last deposit. Every
         * element is written, including a slot no instruction ever
         * stored to: it reads as +0, which is the same normative rule
         * the deposit buffer has and for the same reason. */
        if (pso && prog->n_scratch_out) {
            uint32_t s;
            for (i = 0; i < k; i++)
                for (s = 0; s < prog->n_scratch_out; s++)
                    cft_bn_store(&B->scratch[i * SEQ_SCRATCH_D + s],
                                 pso + ((off + i) * prog->n_scratch_out + s)
                                       * esz,
                                 (int)esz);
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
    st = seq_check_bank(prog, A.bank, A.bank_bytes, "cft_program_run_ex");
    if (st != CFT_OK)
        return st;
    st = seq_check_scratch(prog, &A, "cft_program_run_ex");
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
