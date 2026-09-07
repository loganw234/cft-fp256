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
#define SEQ_NREG         16
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
#define SEQ_MAX_DEPOSITS (1u << 20)
#define SEQ_IMAGE_INSNS  0xFFFFFFFFu
#define SEQ_ADDR_CONSTS  256u  /* with kx (2026-09-07) an instruction's
                                * 8-bit indices reach the whole bank;
                                * the 4-bit fields still reach 16 */

#define BLOCK_LANES      64

/* control codes */
enum { SEQ_HALT = 0, SEQ_REPEAT, SEQ_ENDREP, SEQ_DEPOSIT, SEQ_SETACT,
       SEQ_ACTALL };

/* Indexed constants (`kx`, instruction bit 30). Which byte of `imm`
 * carries each operand's constant index, and the byte above them that
 * stays reserved so a later form can have it. */
#define SEQ_KX_SHIFT_A   0
#define SEQ_KX_SHIFT_B   8
#define SEQ_KX_SHIFT_C  16
#define SEQ_KX_RESERVED  0xFF000000u

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
}

/* The index operand `which` (0 = a, 1 = b, 2 = c) names, and whether
 * it is a constant. A port of seq.py's sources().
 *
 * Without `kx` an operand's 4-bit field is a register number, or a
 * constant index when its `k` bit is set - sixteen addressable
 * constants whatever the header says, which is the wall docs/ENCLOSE.md
 * hit. With `kx` the constant indices come from imm[7:0], imm[15:8]
 * and imm[23:16] instead and reach 255; an operand whose `k` bit is
 * clear still names a register through its own field. */
static int seq_source(const seq_insn *d, int which, int *is_const)
{
    static const int shift[3] = { SEQ_KX_SHIFT_A, SEQ_KX_SHIFT_B,
                                  SEQ_KX_SHIFT_C };
    const int reg[3] = { d->ra, d->rb, d->rc };
    const int kf[3]  = { d->ka, d->kb, d->kc };

    *is_const = kf[which];
    if (!kf[which])
        return reg[which];
    if (d->kx)
        return (int)((d->imm >> shift[which]) & 0xFFu);
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
 * applied to the fields `kx` brings into play. Without `kx` an ALU
 * instruction has no immediate at all. With it: an operand whose `k`
 * bit is set takes its index from `imm`, so its 4-bit field must be
 * zero; an operand whose `k` bit is clear names a register, so its
 * byte of `imm` must be zero; imm[31:24] is read by nothing; and `kx`
 * itself selects nothing when no operand names a constant, which
 * would leave the instruction with a second encoding. */
static cft_status seq_check_operands(const cft_program *p,
                                     const seq_insn *d)
{
    static const int shift[3] = { SEQ_KX_SHIFT_A, SEQ_KX_SHIFT_B,
                                  SEQ_KX_SHIFT_C };
    const int reg[3] = { d->ra, d->rb, d->rc };
    const int kf[3]  = { d->ka, d->kb, d->kc };
    int which;

    if (d->kx) {
        if (!(d->ka || d->kb || d->kc))
            return CFT_ERR_INVALID_ARGUMENT;
        if (d->imm & SEQ_KX_RESERVED)
            return CFT_ERR_INVALID_ARGUMENT;
    } else if (d->imm != 0) {
        return CFT_ERR_INVALID_ARGUMENT;
    }

    for (which = 0; which < 3; which++) {
        uint32_t byte = (d->imm >> shift[which]) & 0xFFu;
        uint32_t idx;
        if (d->kx && kf[which]) {
            if (reg[which])
                return CFT_ERR_INVALID_ARGUMENT;
            idx = byte;
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
         * is not a hash of the program. */
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
                d.kx || d.imm)
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
    /* This executor decodes kx (bit 30: 8-bit constant indices in the
     * immediate) and implements IMUL (opcode 30). The bit assignments
     * are rtl/cft_csr.sv's, surfaced by cft.h. */
    out->features     = CFT_SEQ_FEAT_WIDE_CONST | CFT_ALU_EXT_IMUL;
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

/* The constant INDEX an instruction carries, against the number of
 * constants the device can address. Separate from the header check
 * above because it is a property of the instruction stream rather
 * than of the header: a program may declare more constants than it
 * can reach (they are simply unreachable), and what a device refuses
 * to execute is a reference past its bank. Structurally impossible on
 * a device that addresses all sixteen a four-bit field reaches, which
 * is every device shipped so far; it becomes real for a trimmed tile
 * that publishes fewer, and for the wide constant index that
 * CAPS[4] is reserved for. */
static cft_status seq_check_const_index(cft_device *dev,
                                        const cft_program *p)
{
    cft_seq_caps c;
    uint32_t pc;
    cft_device_seq_caps(dev, &c);
    for (pc = 0; pc < p->n_insns; pc++) {
        seq_insn d;
        int idx = -1;
        seq_decode(p->insns[pc], &d);
        if (d.ctrl)
            continue;
        /* A feature the device does not publish is ABSENT, not
         * unknown: an old bitstream's operand mux would read a kx
         * instruction's four-bit fields and compute on the wrong
         * constants without a fault, and an integer group without
         * IMUL answers opcode 30 with the unassigned-opcode result.
         * Neither is a refusal the tile can make, so it is made here. */
        if (d.kx && !(c.features & CFT_SEQ_FEAT_WIDE_CONST)) {
            cft_set_error("instruction %lu uses indexed constants (kx, bit "
                          "30) and this device does not publish the "
                          "feature (CAPS[4] clear, cft_caps.seq_features "
                          "bit 0); build the program without kx",
                          (unsigned long)pc);
            return CFT_ERR_UNSUPPORTED;
        }
        if (d.op == 30 && !(c.features & CFT_ALU_EXT_IMUL)) {
            cft_set_error("instruction %lu is IMUL (opcode 30) and this "
                          "device does not implement it (CAPS[28] clear, "
                          "cft_caps.seq_features bit 4)",
                          (unsigned long)pc);
            return CFT_ERR_UNSUPPORTED;
        }
        if (!c.max_consts)      /* unknown: nothing enforced */
            continue;
        if (d.ka && (uint32_t)d.ra >= c.max_consts) idx = d.ra;
        if (d.kb && (uint32_t)d.rb >= c.max_consts) idx = d.rb;
        if (d.kc && (uint32_t)d.rc >= c.max_consts) idx = d.rc;
        if (idx >= 0)
            return (cft_status)cft_seq_cap_refusal(
                "highest constant index", (unsigned long)idx,
                (unsigned long)c.max_consts - 1u,
                "constants an instruction can address, indexed from 0",
                "max_consts");
    }
    return CFT_OK;
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
    /* After seq_validate, so that a malformed instruction is reported
     * as malformed rather than as a capacity the device lacks. */
    st = seq_check_const_index(dev, prog);
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
            /* The three operand sources are a property of the
             * instruction, not of the lane, so they are resolved once
             * per instruction - which is what the hardware does too,
             * a constant being unable to change during a run. */
            int ia, ib, ic, ka, kb, kc;
            ia = seq_source(&d, 0, &ka);
            ib = seq_source(&d, 1, &kb);
            ic = seq_source(&d, 2, &kc);
            for (i = 0; i < nlane; i++) {
                cft_bn outv;
                uint32_t fl = 0;
                if (!B->active[i])
                    continue;   /* no write, no deposit, and no flags */
                if (cft_sf_compute(p->f, d.op, d.rnd,
                                   seq_src(p, B, i, ia, ka),
                                   seq_src(p, B, i, ib, kb),
                                   seq_src(p, B, i, ic, kc),
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
        cft_flags_emit(prog->dev, 0, flags);
        return CFT_OK;
    }
    if (!a || (!deposits && prog->max_deposits))
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
     * implementation - which is why it hands over the IMAGE and the
     * caller's own pointers and does nothing else.
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
            /* Which device backend is device.c's business: the
             * dispatcher in backend.h hands the run to the XRT one or
             * the remote one (docs/REMOTE.md) and this file names
             * neither. */
            cft_status st = (cft_status)cft_backend_program_run(
                prog->dev, prog->fmt_code, prog->image, prog->image_bytes,
                prog->max_deposits, a, b, c, deposits, counts, n, &fl, &bs);
            if (st == CFT_OK) {
                cft_flags_emit(prog->dev, fl, flags);
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
