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
 * A lane's state is 16 registers of format width. Holding all of them
 * for a large n would be absurd - a million fp256 elements would want
 * half a gigabyte of register file - so lanes are processed
 * BLOCK_LANES at a time.
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

#include <stdlib.h>
#include <string.h>

#include "../include/cft.h"
#include "softfloat.h"
#ifdef CFT_ENABLE_XRT
#include "backend.h"
#endif

#define SEQ_MAGIC        0x50544643u   /* "CFTP" */
#define SEQ_VERSION      1u
#define SEQ_HEADER_BYTES 32
#define SEQ_INSN_BYTES   8
#define SEQ_NREG         16
#define SEQ_MAX_DEPTH    4
#define SEQ_MAX_INSNS    (1ull << 40)
#define SEQ_MAX_DEPOSITS (1u << 20)

#define BLOCK_LANES      64

/* control codes */
enum { SEQ_HALT = 0, SEQ_REPEAT, SEQ_ENDREP, SEQ_DEPOSIT, SEQ_SETACT,
       SEQ_ACTALL };

struct cft_program {
    cft_device         *dev;
    const cft_fmt_desc *f;
    int                 fmt_code;
    uint32_t            max_deposits;
    uint32_t            n_insns;
    uint32_t            n_consts;
    uint64_t           *insns;
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

typedef struct {
    int      op, rd, ra, rb, rc, rnd;
    int      ka, kb, kc, rsv, ctrl;
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
    d->rsv  = (int)((w >> 30) & 1);
    d->ctrl = (int)((w >> 31) & 1);
    d->imm  = (uint32_t)((w >> 32) & 0xFFFFFFFFu);
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
        seq_decode(p->insns[pc], &d);
        if (d.rsv)
            return CFT_ERR_INVALID_ARGUMENT;

        worst += mult[top];
        if (worst > SEQ_MAX_INSNS)
            return CFT_ERR_INVALID_ARGUMENT;

        if (!d.ctrl) {
            if ((d.ka && (uint32_t)d.ra >= p->n_consts) ||
                (d.kb && (uint32_t)d.rb >= p->n_consts) ||
                (d.kc && (uint32_t)d.rc >= p->n_consts))
                return CFT_ERR_INVALID_ARGUMENT;
            if (d.rnd > 4 || d.imm != 0)
                return CFT_ERR_INVALID_ARGUMENT;
            continue;
        }

        /* Fields a control instruction does not read must be zero, so
         * one operation has one encoding - otherwise a readback hash
         * is not a hash of the program. */
        switch (d.op) {
        case SEQ_HALT:
        case SEQ_ENDREP:
        case SEQ_ACTALL:
            if (d.rd || d.ra || d.rb || d.rc || d.rnd || d.ka || d.kb ||
                d.kc || d.imm)
                return CFT_ERR_INVALID_ARGUMENT;
            break;
        case SEQ_REPEAT:
            if (d.rd || d.ra || d.rb || d.rc || d.rnd || d.ka || d.kb ||
                d.kc)
                return CFT_ERR_INVALID_ARGUMENT;
            break;
        case SEQ_DEPOSIT:
        case SEQ_SETACT:
            if (d.rd || d.rb || d.rc || d.rnd || d.ka || d.kb || d.kc ||
                d.imm)
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
            mult[top] = mult[top - 1] * d.imm;
            if (mult[top] > SEQ_MAX_INSNS)
                return CFT_ERR_INVALID_ARGUMENT;
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

CFT_API cft_status cft_program_load(cft_device *dev, const void *image,
                                    size_t bytes, cft_program **out)
{
    const uint8_t *p = (const uint8_t *)image;
    cft_program *prog;
    uint32_t magic, ver, n_insns, n_consts, maxdep, prec, rsv0, rsv1;
    size_t esz, want, i;
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
    rsv0     = rd_le32(p + 24);
    rsv1     = rd_le32(p + 28);

    if (magic != SEQ_MAGIC || ver != SEQ_VERSION || rsv0 || rsv1)
        return CFT_ERR_ARTIFACT;
    if (prec > 3)
        return CFT_ERR_ARTIFACT;
    if (maxdep > SEQ_MAX_DEPOSITS)
        return CFT_ERR_INVALID_ARGUMENT;
    /* A program is compiled for one format, because its constants are
     * format-width values. Refuse it here rather than at the first
     * instruction that would issue a precision this device does not
     * carry. */
    if (!cft_supports(dev, CFT_FMA, (cft_format)prec))
        return CFT_ERR_UNSUPPORTED;

    esz  = (size_t)cft_sf_formats[prec].width / 8;
    want = (size_t)SEQ_HEADER_BYTES + (size_t)n_consts * esz +
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
    if (n_insns) {
        prog->insns = (uint64_t *)calloc(n_insns, sizeof(uint64_t));
        if (!prog->insns) { cft_program_free(prog); return CFT_ERR_OUT_OF_MEMORY; }
    }
    if (n_consts) {
        prog->consts = (cft_bn *)calloc(n_consts, sizeof(cft_bn));
        if (!prog->consts) { cft_program_free(prog); return CFT_ERR_OUT_OF_MEMORY; }
    }
    prog->image = (uint8_t *)malloc(bytes);
    if (!prog->image) { cft_program_free(prog); return CFT_ERR_OUT_OF_MEMORY; }
    memcpy(prog->image, p, bytes);
    prog->image_bytes = bytes;

    for (i = 0; i < n_consts; i++)
        cft_bn_load(&prog->consts[i], p + SEQ_HEADER_BYTES + i * esz,
                    (int)esz);
    for (i = 0; i < n_insns; i++)
        prog->insns[i] = rd_le64(p + SEQ_HEADER_BYTES + n_consts * esz +
                                 i * SEQ_INSN_BYTES);

    st = seq_validate(prog);
    if (st != CFT_OK) {
        cft_program_free(prog);
        return st;
    }
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
} seq_block;

static const cft_bn *seq_src(const cft_program *p, seq_block *B, int lane,
                             int idx, int is_const)
{
    return is_const ? &p->consts[idx] : &B->regs[lane][idx];
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

static cft_status seq_run_block(const cft_program *p, seq_block *B,
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
            for (i = 0; i < nlane; i++) {
                cft_bn outv;
                uint32_t fl = 0;
                if (!B->active[i])
                    continue;   /* no write, no deposit, and no flags */
                if (cft_sf_compute(p->f, d.op, d.rnd,
                                   seq_src(p, B, i, d.ra, d.ka),
                                   seq_src(p, B, i, d.rb, d.kb),
                                   seq_src(p, B, i, d.rc, d.kc),
                                   &outv, &fl))
                    return CFT_ERR_INTERNAL;
                cft_bn_copy(&B->regs[i][d.rd], &outv);
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
                cft_bn_store(&B->regs[i][d.ra], deposits + slot * esz,
                             (int)esz);
                B->counts[i]++;
            }
            pc++;
            break;

        case SEQ_SETACT:
            for (i = 0; i < nlane; i++) {
                cft_bn mag;
                if (!B->active[i])
                    continue;       /* narrows only, never widens */
                cft_bn_copy(&mag, &B->regs[i][d.ra]);
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

        default:
            return CFT_ERR_INTERNAL;
        }
    }
    return CFT_OK;
}

CFT_API cft_status cft_program_run(cft_program *prog,
                                   const void *a, const void *b,
                                   const void *c,
                                   void *deposits, uint32_t *counts,
                                   size_t n,
                                   uint32_t *flags, uint32_t *bus)
{
    const uint8_t *pa = (const uint8_t *)a;
    const uint8_t *pb = (const uint8_t *)b;
    const uint8_t *pc_ = (const uint8_t *)c;
    uint8_t *pd = (uint8_t *)deposits;
    size_t esz, off;
    uint32_t acc_flags = 0, acc_status = 0;
    seq_block *B;

    if (bus)
        *bus = 0;
    if (!prog)
        return CFT_ERR_INVALID_ARGUMENT;
    if (n == 0) {
        if (flags)
            *flags = 0;
        return CFT_OK;
    }
    if (!a || (!deposits && prog->max_deposits))
        return CFT_ERR_INVALID_ARGUMENT;

    esz = (size_t)prog->f->width / 8;
    if (prog->max_deposits &&
        n > ((size_t)-1) / prog->max_deposits / esz)
        return CFT_ERR_INVALID_ARGUMENT;

#ifdef CFT_ENABLE_XRT
    /* The device runs the program if the device is where it was
     * loaded. Everything above this line is argument checking that
     * both executors need; everything below is the software one.
     *
     * The two must agree bit for bit, and that is not an aspiration:
     * the tile's ALU is the same pipeline softfloat.c models
     * (docs/SEQUENCER.md P1), the deposit address is a function of the
     * element index alone (P2), and the early exit changes only how
     * long the run takes (P3). So this is a dispatch and not a second
     * implementation - which is why it hands over the IMAGE and the
     * caller's own pointers and does nothing else.
     *
     * One divergence is known and deliberately not papered over here:
     * a program with max_deposits == 0 loads and runs in software
     * (every deposit overflows, nothing is written) and is REFUSED by
     * the tile, whose header check requires at least one slot. The
     * refusal surfaces as CFT_ERR_UNSUPPORTED with the reason in
     * cft_last_error rather than being pre-empted, because inventing a
     * host-side rule the contract does not state is how the two
     * executors start drifting for real. */
    {
        void *hw = cft_device_backend(prog->dev);
        if (hw) {
            uint32_t fl = 0, bs = 0;
            cft_status st = (cft_status)cftx_program_run(
                hw, prog->fmt_code, prog->image, prog->image_bytes,
                prog->max_deposits, a, b, c, deposits, counts, n, &fl, &bs);
            if (st == CFT_OK) {
                if (flags)
                    *flags = fl;
                if (bus)
                    *bus = bs;
            }
            return st;
        }
    }
#endif

    /* Every slot is written, including ones no lane deposits into: an
     * untouched slot reads as +0 by definition, and a run that left
     * the caller's previous contents there would not be reproducible.
     */
    if (pd && prog->max_deposits)
        memset(pd, 0, n * prog->max_deposits * esz);

    B = (seq_block *)calloc(1, sizeof *B);
    if (!B)
        return CFT_ERR_OUT_OF_MEMORY;

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
        }

        st = seq_run_block(prog, B, (int)k, pd, off, esz,
                           &acc_flags, &acc_status);
        if (st != CFT_OK) {
            free(B);
            return st;
        }
        if (counts)
            for (i = 0; i < k; i++)
                counts[off + i] = B->counts[i];
    }

    free(B);
    if (flags)
        *flags = acc_flags;
    /* A deposit overflow is reported, not an error. The deposits that
     * fit are correct and the run is reproducible; what the caller
     * lost is the tail, and it needs to know that without being told
     * its results are invalid - which is what CFT_ERR_BUS_FAULT
     * means and this is not. */
    if (bus)
        *bus = acc_status;
    return CFT_OK;
}
