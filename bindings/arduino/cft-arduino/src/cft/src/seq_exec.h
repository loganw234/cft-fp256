/* Copyright 2026 Logan W.
 * SPDX-License-Identifier: Apache-2.0
 *
 * The orbit sequencer's executor: a block of lanes through a program
 * (seq_run_block), everything it reaches, and the work a run does for
 * each lane around it. program.c's own text, taken out of it on
 * 2026-11-11 (the GPU backend's round 1) so that two executors compile
 * one source:
 *
 *   - program.c, the software backend, includes this with BLOCK_LANES
 *     at 64 and seq_run_block's ALU call going to cft_sf_compute, which
 *     is what it compiled before the split;
 *   - a GPU's kernel, one thread a lane, includes it with BLOCK_LANES at
 *     1 (docs/studies/GPU-A-hip.md, P2.4, says why a block of one lane
 *     gives a block of 64's bits), and may route the ALU call elsewhere
 *     through CFT_SEQ_ALU.
 *
 * Every function here is static, as it was in program.c, so this is a
 * header of definitions in the idiom of mask_bits.h and lane_cut.h: a
 * translation unit that runs programs includes it once. The text is
 * MOVED, not rewritten. From SEQ_NREG to seq_load_in it is program.c's,
 * line for line, but for CFT_HD at the head of each function line
 * (cft_config.h), a comment above BLOCK_LANES and two macros:
 * BLOCK_LANES's definition now yields to one made before this header,
 * and seq_run_block's one ALU call goes through CFT_SEQ_ALU, whose
 * default is the cft_sf_compute it called.
 * The four functions after seq_load_in are seq_program_run's per-lane
 * work (their comment says what moved and what did not).
 */
#ifndef CFT_SEQ_EXEC_H
#define CFT_SEQ_EXEC_H

#include <string.h>

#include "../include/cft_config.h"
#include "../include/cft.h"
#include "softfloat.h"

/* seq_run_block's one ALU call, for every lane of every arithmetic
 * instruction. cft_sf_compute unless the including file names another
 * function of the same signature and the same bits - a device's
 * specialised arithmetic, held to this one by its gates. */
#ifndef CFT_SEQ_ALU
#define CFT_SEQ_ALU cft_sf_compute
#endif

/* Revision 2's thirty-two registers a lane. The low four bits of each
 * field stay where they were and the fifth lives in imm[27:24], so a
 * program that names only r0..r15 encodes exactly as it always did -
 * which is what lets an image built before this run unchanged. */
#define SEQ_NREG         32

#define SEQ_MAX_DEPTH    4

/* Lanes a block runs at once: 64 here, 1 on a GPU, whose thread is
 * a block of one lane (program.c's head says why the number cannot
 * change an answer). */
#ifndef BLOCK_LANES
#define BLOCK_LANES      64
#endif

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

CFT_HD static void seq_decode(uint64_t w, seq_insn *d)
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
CFT_HD static int seq_reg(int lo, int hi)
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
CFT_HD static int seq_source(const seq_insn *d, int which, int *is_const)
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

/* The signed post-step an STX or LDX carries, or 0 - and 0 for STL and
 * LDL, whose imm[23:0] is a slot and not a step. */
CFT_HD static int seq_step(const seq_insn *d)
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
CFT_HD static int seq_step_discarded(const seq_insn *d)
{
    return d->op == SEQ_LDX &&
           seq_reg(d->rd, d->hd) == seq_reg(d->rb, d->hb);
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
CFT_HD static cft_bn *seq_scratch_at(seq_block *B, int lane, uint32_t slot)
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
CFT_HD static const cft_bn *seq_src(const cft_bn *konst, seq_block *B, int lane,
                             int idx, int is_const)
{
    return is_const ? &konst[idx] : &B->regs[lane][idx];
}

/* Skip forward to the ENDREP matching the REPEAT at `pc`. Validation
 * has already proved the nesting is balanced, so the depth scan is
 * exact. */
CFT_HD static uint32_t seq_matching_endrep(const cft_program *p, uint32_t pc)
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
CFT_HD static cft_status seq_exec_augmented(const cft_program *p, seq_block *B,
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
CFT_HD static cft_status seq_post_step(const cft_program *p, seq_block *B,
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

CFT_HD static cft_status seq_run_block(const cft_program *p, const cft_bn *konst,
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
                if (CFT_SEQ_ALU(p->f, d.op, d.rnd,
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
CFT_HD static void seq_load_in(cft_bn *dst, const uint8_t *src,
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

/* ---- a run's lanes, around seq_run_block ---------------------------
 *
 * seq_program_run's work for each lane of a run, besides running it:
 * the lane's deposit slots written +0, its registers and scratch set up
 * before seq_run_block, and its count, its lane byte and its
 * scratch-out read back after. Functions of their own so that a GPU's
 * kernel runs this code for its lane (BLOCK_LANES 1, `first` or `off`
 * the lane's own index) where study GPU-A's runner re-expressed it
 * (docs/studies/GPU-A-hip.md, P2.3). Every buffer is the run's own,
 * reached through A - device pointers, on a device.
 *
 * The bodies are seq_program_run's, moved, and the host calls them
 * where the code stood: the deposits once a run, before its first
 * block; the reach once a run; lanes in and out once a block. Not pure
 * moves: seq_scratch_reach takes the depth as an argument and returns
 * the reach; seq_lanes_deposits takes a range of lanes where it had the
 * whole run (its comment says how); the locals each function reads are
 * re-declared from A as seq_program_run declared them; and the bodies
 * of the two block functions are dedented one level, the block loop
 * being the caller's. They are static inline where the moved text is
 * static: a unit that includes this and calls none of them - study
 * GPU-A's runner, which has its own - is not warned of four unused
 * functions.
 * --------------------------------------------------------------------- */

/* What of a lane's scratch a block has to clear: every slot the
 * program can observe - the whole depth when it indexes
 * (scratch_used says so), else its highest static slot and the
 * slots its block reads in and out. Nothing above that is ever read
 * or written, so its contents are not a value any program can
 * distinguish; the tile's per-block wipe is bounded by the same rule
 * (and since revision 7 stops sooner, where nothing has written).
 * 0 for a program that has no scratch. */
CFT_HD static inline uint32_t seq_scratch_reach(const cft_program *prog,
                                               uint32_t depth)
{
    uint32_t scr_reach = 0;

    if (prog->scratch_active) {
        scr_reach = prog->scratch_used;
        if (prog->n_scratch_in > scr_reach)
            scr_reach = prog->n_scratch_in;
        if (prog->n_scratch_out > scr_reach)
            scr_reach = prog->n_scratch_out;
        if (scr_reach > depth)
            scr_reach = depth;
    }
    return scr_reach;
}

/* Lanes first .. first + count - 1 of the run's deposit slots, as +0.
 *
 * Every slot is written, including ones no lane deposits into: an
 * untouched slot reads as +0 by definition, and a run that left
 * the caller's previous contents there would not be reproducible.
 *
 * Except a MASKED lane's slots (R17), which are the one thing in
 * this buffer that is NOT this run's to write: the caller keeps
 * its bytes. So the zero-fill is per lane when there is a mask and
 * one memset when there is not - the same bytes in the same order
 * either way, and no run written before the mask existed pays for
 * the loop.
 *
 * seq_program_run calls this once, for the whole run (first 0, count
 * n), before its first block, where it always zeroed them - the same
 * one memset, or the same loop. A GPU's lane calls it for itself
 * (first its index, count 1). Not a pure move: `pd` and `n` were the
 * whole run's, and are now `pd + first * max_deposits * esz` and
 * `count`, with the masked loop from `first`. */
CFT_HD static inline void seq_lanes_deposits(const cft_program *prog,
                                             const cft_run_args *A,
                                             size_t first, size_t count,
                                             size_t esz)
{
    uint8_t *pd = (uint8_t *)A->deposits;
    const uint8_t *msk = A->lane_mask;

    if (pd && prog->max_deposits) {
        if (!msk) {
            memset(pd + first * prog->max_deposits * esz, 0,
                   count * prog->max_deposits * esz);
        } else {
            size_t i;
            for (i = first; i < first + count; i++)
                if (msk[i >> 3] & (uint8_t)(1u << (i & 7u)))
                    memset(pd + i * prog->max_deposits * esz, 0,
                           prog->max_deposits * esz);
        }
    }
}

/* Lanes off .. off + k - 1 of the run, into lanes 0 .. k - 1 of block
 * B, ready for seq_run_block: registers zeroed and a, b and c loaded,
 * R17's mask, the counts and lane bytes at zero, and the scratch
 * zeroed to scr_reach (seq_scratch_reach) and preloaded. B->scratch
 * and B->depth are the caller's; lane i's slots start at
 * B->scratch[i * B->depth]. */
CFT_HD static inline void seq_lanes_in(const cft_program *prog,
                                       const cft_run_args *A, seq_block *B,
                                       size_t off, size_t k, size_t esz,
                                       uint32_t scr_reach)
{
    const uint8_t *pa = (const uint8_t *)A->a;
    const uint8_t *pb = (const uint8_t *)A->b;
    const uint8_t *pc_ = (const uint8_t *)A->c;
    const uint8_t *psi = (const uint8_t *)A->scratch_in;
    /* The four tables, or NULL each for a dense block (ABI 0.14). With
     * a table, `pa` and `psi` are the SOURCE and the POOL rather than
     * the run's elements, and the only thing that knows the difference
     * is seq_load_in above. */
    const uint32_t *ia = A->idx_a, *ib = A->idx_b, *ic = A->idx_c;
    const uint32_t *isi = A->idx_scratch_in;
    /* R17's lane mask, or NULL for every lane. Bit i of the buffer is
     * lane i of the RUN - global, so a block of this loop reads bits
     * off + i and not bits 0..k, the same rule the index tables have
     * one field along. */
    const uint8_t *msk = A->lane_mask;
    size_t i;

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
}

/* Lanes 0 .. k - 1 of block B, after seq_run_block, back into lanes
 * off .. off + k - 1 of the run: the counts, R23's lane bytes and the
 * scratch-out, each for the lanes the caller has. */
CFT_HD static inline void seq_lanes_out(const cft_program *prog,
                                        const cft_run_args *A,
                                        const seq_block *B, size_t off,
                                        size_t k, size_t esz)
{
    uint32_t *counts   = A->counts;
    uint8_t *pso = (uint8_t *)A->scratch_out;
    size_t i;

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

#endif /* CFT_SEQ_EXEC_H */
