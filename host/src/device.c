/* Copyright 2026 Logan W.
 * SPDX-License-Identifier: Apache-2.0
 *
 * libcft: devices, capabilities, buffers and the one call that does
 * the work. The arithmetic lives in softfloat.c; this file is the
 * boundary between it and the rest of the world, so its job is
 * argument checking and bookkeeping - the two things a caller in
 * another language cannot do for itself.
 */

#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "../include/cft.h"
#include "softfloat.h"
/* Unconditionally: cft_seq_caps and the seams this file owns on both
 * sides of it (cft_device_seq_caps, cft_set_error) exist in every
 * build, including one with no device backend at all. */
#include "backend.h"
#ifdef CFT_ENABLE_XRT

/* Ranges a device reduction may be split into. One per tile, so this
 * is MAX_TILES in the XRT backend - kept as its own name because it
 * sizes two stack arrays here and a wrong value would overflow them
 * quietly. */
#define CFT_MAX_REDUCE_PARTS 64
#endif

#define CFT_BACKEND_SW  0
#define CFT_BACKEND_XRT 1

/* Clears this library's own last-error slot; called at every point
 * where a call is about to reach a device backend, so that a message
 * libcft wrote never goes on explaining a failure that is not its.
 * Defined with the slot, below. */
#if defined(CFT_ENABLE_XRT) || !defined(CFT_NO_REMOTE)
static void backend_call(void);
#endif

/* ==== the remote backend (docs/REMOTE.md) ============================
 * A device behind a socket, opened with "cft://host:port". Compiled in
 * by default: it is C99 plus the operating system's socket API and
 * adds no link-time dependency (backend_remote.c says how). Building
 * with -DCFT_NO_REMOTE leaves it out, and cft_open() of a cft:// URL
 * is then CFT_ERR_NO_DEVICE - the answer a build without XRT gives an
 * xclbin path. */
#ifndef CFT_NO_REMOTE
#include "backend.h"
#include "remote.h"
#endif
#define CFT_BACKEND_REMOTE 2
/* ==== end of the remote block ======================================= */

struct cft_device {
    int         backend;
    int         index;
    uint32_t    format_mask;
    uint32_t    op_groups;      /* CAPS[15:8]; software carries them all */
    uint32_t    tiles;
    uint32_t    device_version;
    int         flags_readable;
    /* What this device will accept in a program header, published
     * through cft_caps and enforced by cft_program_load. Zero in a
     * field is UNKNOWN, and only a remote server whose caps block
     * predates the fields produces one. */
    cft_seq_caps seq;
    const char *backend_name;
    void       *hw;             /* backend handle, NULL for software */
    /* The 754-2019 7.1 status word (ABI 0.7). Every entry point ORs
     * its per-call flags in through cft_flags_emit(); only the six
     * operations of 5.7.4 at the end of this file ever lower it.
     * calloc'd to zero at cft_open, which is 7.1's "A program that
     * does not inherit status flags from another source begins
     * execution with all status flags lowered." */
    uint32_t    sticky_flags;
    /* Nonzero while a composed operation's internal passes are
     * running, so that the scaffolding's flags reach the pass's own
     * flags_out and not the word above. See cft_flags_mute. */
    int         flags_muted;
    /* Every live cft_buffer this device allocated, newest first.
     *
     * The registry that makes cft.h's "the library recognises its own
     * buffers" true. It is a LIST and the lookup is a linear scan,
     * because the thing being counted is how many cft_alloc'd buffers
     * one program holds at once - three or four in every use this API
     * has - and a hash table keyed on address ranges would be more
     * code, more state to keep correct, and no faster at that size.
     * If a caller ever holds hundreds, the scan is the place to look
     * and the fix is local to this file. */
    struct cft_buffer *bufs;
};

/* Which CAPS opcode-group bit covers an opcode. The groups exist
 * because opcodes arrive in groups and a bit per opcode is a register
 * nobody keeps current; see rtl/cft_csr.sv, which is the normative
 * map. Returns -1 for an unassigned opcode, which belongs to no group
 * and is never "supported". */
static int op_group_bit(int op)
{
    if (op >= 0  && op <= 3)  return 0;   /* arithmetic */
    if (op >= 4  && op <= 6)  return 1;   /* sign */
    if (op >= 7  && op <= 10) return 2;   /* min/max */
    if (op >= 11 && op <= 14) return 3;   /* predicate */
    if (op >= 16 && op <= 23) return 4;   /* integer */
    if (op == 30)             return 4;   /* integer: IMUL (2026-09-07),
                                           * and CAPS[28] must ALSO be set
                                           * - checked beside the group */
    if (op >= 24 && op <= 25) return 5;   /* reduction */
    if (op == 31)             return 5;   /* reduction: maxall
                                           * (2026-09-12), composed - see
                                           * reduce_helper_group */
    if (op >= 26 && op <= 27) return 6;   /* divide/sqrt (the seeds) */
    /* sumSquare and sumAbs are the reduction group too, although no
     * accumulator streams them: they are issued as a dot (or an abs
     * pass and a sum), so a device that carries the group carries
     * them. They also need the ARITHMETIC group for the multiply and
     * the SIGN group for the abs, which cft_reduce checks separately -
     * one opcode cannot name two groups in a table shaped like this,
     * and inventing a second group bit for an opcode no bitstream
     * implements would put a lie in the CAPS register. */
    if (op >= 28 && op <= 29) return 5;   /* reduction (composed)      */
    return -1;
}

/* The extra opcode group a composed reduction needs beyond its own:
 * arithmetic for sumSquare's multiply, sign for sumAbs's abs. -1 for
 * everything else. */
static int reduce_helper_group(int op)
{
    if (op == 28) return 0;               /* sumsq  -> mul  */
    if (op == 29) return 1;               /* sumabs -> abs  */
    if (op == 31) return 2;               /* maxall -> min/max */
    return -1;
}

struct cft_buffer {
    cft_device *dev;            /* NULL once the device has been closed */
    size_t      bytes;
    void       *data;           /* the host mirror; this file owns it */
    void       *dbuf;           /* the backend's object, or NULL when the
                                 * backend keeps no device copies */
    struct cft_buffer *next;    /* the device's registry, newest first */
};

/* ---------------------------------------------------------------
 * The buffer registry (cft.h's cft_alloc, docs/HOSTAPI.md)
 *
 * Everything below turns "the caller handed cft_run a pointer" into
 * "that pointer is byte k of this device-resident buffer", which is
 * the whole of what recognition means. It lives here, in C, and not
 * in the device backend, for the reason slice.h lives here: the
 * arithmetic that decides which bytes a run reads is testable without
 * a card, and a backend should only be asked what a memory group is.
 * --------------------------------------------------------------- */

/* Does [p, p + bytes) lie wholly inside a live buffer of this device?
 *
 * WHOLLY, and that is not fussiness. A device copy is exactly as long
 * as the buffer, so a run that reached past the end would be served
 * bytes nobody wrote - which is the one failure mode this whole
 * mechanism must not have. A window that overruns is therefore not
 * recognised at all, and is staged from host memory exactly as any
 * other pointer is: the same answer the caller would have got before
 * buffers existed, including the same out-of-bounds read if that is
 * what they asked for.
 *
 * Compiled only where something recognises a pointer: the one caller
 * is bind_role below, which is the XRT backend's binding path. A
 * software-only build has no device copies for a pointer to be a
 * window into, so this would be an unused function - and it would
 * warn, which is worse than absent. */
#ifdef CFT_ENABLE_XRT
static cft_buffer *buf_find(cft_device *dev, const void *p, size_t bytes,
                            size_t *off)
{
    cft_buffer *b;
    const uint8_t *q = (const uint8_t *)p;

    if (!dev || !p)
        return NULL;
    for (b = dev->bufs; b; b = b->next) {
        const uint8_t *base = (const uint8_t *)b->data;
        if (!b->dbuf || !base)
            continue;
        /* Comparing pointers into different objects is not defined by
         * C, which is why this compares INTEGERS: the arithmetic is
         * the same and the language is not being asked a question it
         * declines to answer. */
        {
            uintptr_t bi = (uintptr_t)base, qi = (uintptr_t)q;
            if (qi < bi || qi - bi > b->bytes)
                continue;
            if (bytes > b->bytes - (qi - bi))
                continue;
            if (off)
                *off = (size_t)(qi - bi);
            return b;
        }
    }
    return NULL;
}
#endif /* CFT_ENABLE_XRT */

/* Bring a buffer's mirror up to date before anything READS it.
 *
 * The authority rule in cft.h says a caller should call
 * cft_buffer_from_device after a run wrote the buffer. This is what
 * happens when the caller does not: the library does it, here, before
 * the bytes could be misread - whether the reader is the tile (the
 * buffer is about to be an input) or this file itself (9.4's infinity
 * scan walks the caller's array on the host). Breaking the rule costs
 * the round trip; it never costs the answer. */
static void buf_sync_in(cft_device *dev, const void *p, size_t bytes)
{
    cft_buffer *b;
    (void)bytes;
    if (!dev || !p)
        return;
    /* Deliberately NOT buf_find. That one demands the whole window fit,
     * because a window that overruns must not be BOUND; this one only
     * has to decide whether the mirror about to be read is stale, and
     * the answer to that is the same whether the caller's length is
     * sensible or not. A buffer whose start this points into gets
     * brought home, and an overrunning run then reads a current mirror
     * and whatever is past it - which is the caller's own bug, not a
     * stale answer this library handed back. */
    for (b = dev->bufs; b; b = b->next) {
        uintptr_t bi, qi;
        if (!b->dbuf || !b->data)
            continue;
        bi = (uintptr_t)b->data;
        qi = (uintptr_t)p;
        if (qi < bi || qi - bi > b->bytes)
            continue;
#ifdef CFT_ENABLE_XRT
        (void)cftx_buffer_from_device(b->dbuf);
#endif
        return;
    }
}

#ifdef CFT_ENABLE_XRT
static void bind_clear(cft_bindings *bd)
{
    int i;
    /* CFT_ROLE_COUNT, never a literal: a role this loop does not reach
     * is a pointer a backend would read as a live binding. */
    for (i = 0; i < CFT_ROLE_COUNT; i++) {
        bd->buf[i] = NULL;
        bd->off[i] = 0;
    }
}

static void bind_role(cft_device *dev, cft_bindings *bd, int role,
                      const void *p, size_t bytes)
{
    size_t off = 0;
    cft_buffer *b;
    if (!p || bytes == 0)
        return;
    b = buf_find(dev, p, bytes, &off);
    if (!b)
        return;
    bd->buf[role] = b->dbuf;
    bd->off[role] = off;
}
#endif

/* ---------------------------------------------------------------
 * Static descriptions
 * --------------------------------------------------------------- */

CFT_API uint32_t cft_abi_version(void)
{
    return ((uint32_t)CFT_ABI_VERSION_MAJOR << 16) |
           (uint32_t)CFT_ABI_VERSION_MINOR;
}

CFT_API const char *cft_strerror(cft_status s)
{
    switch (s) {
    case CFT_OK:                     return "ok";
    case CFT_ERR_INVALID_ARGUMENT:   return "invalid argument";
    case CFT_ERR_UNSUPPORTED:        return "operation or format not "
                                            "available on this device";
    case CFT_ERR_NO_DEVICE:          return "no such device";
    case CFT_ERR_ARTIFACT:           return "artifact missing, unreadable, "
                                            "or not a tile";
    case CFT_ERR_BUS_FAULT:          return "memory system fault: the output "
                                            "is not valid";
    case CFT_ERR_OUT_OF_MEMORY:      return "out of memory";
    case CFT_ERR_TIMEOUT:            return "timed out";
    case CFT_ERR_INTERNAL:           return "internal error";
    }
    return "unknown status";
}

CFT_API size_t cft_format_size(cft_format f)
{
    if (CFT_FMT_OUT_OF_RANGE(f))
        return 0;
    return (size_t)cft_sf_formats[(int)f].width / 8;
}

CFT_API const char *cft_format_name(cft_format f)
{
    if (CFT_FMT_OUT_OF_RANGE(f))
        return "invalid";
    return cft_sf_formats[(int)f].name;
}

CFT_API const char *cft_op_name(cft_op op)
{
    /* UNSIZED on purpose, since 2026-09-12. It was names[31], and
     * appending maxall's string made a 32nd initialiser that the
     * compiler DISCARDED with a warning - so cft_op_name(31) kept
     * answering "reserved" and the opcode-assignment gate below
     * caught it. The bound on the lookup is sizeof names, so an
     * unsized array cannot disagree with itself. */
    static const char *const names[] = {
        "fma", "add", "sub", "mul",
        "abs", "neg", "copysign",
        "min", "max", "minnum", "maxnum",
        "select", "cmplt", "cmple", "cmpeq",
        0,
        "iand", "ior", "ixor", "iadd",
        "isub", "ishl", "ishr", "icmplt",
        "sum", "dot",
        "recip_seed", "rsqrt_seed",
        "sumsq", "sumabs",
        /* 30: the integer group's multiply (2026-09-07). Named here
         * the moment the opcode was defined, and BEFORE any CAPS bit
         * publishes it, because this table is what conformance.c's
         * op_from_name() consults to decide whether a recorded set's
         * "reserved30" case is stale. A set recorded while 30 answered
         * with the canonical quiet NaN must be refused rather than
         * replayed against a multiply, and it is this string that
         * makes the refusal fire. */
        "imul",
        "maxall"
    };
    if ((int)op >= 0 && (int)op < (int)(sizeof names / sizeof names[0]) &&
        names[(int)op])
        return names[(int)op];
    return "reserved";
}

/* ---------------------------------------------------------------
 * Devices
 * --------------------------------------------------------------- */

CFT_API cft_status cft_open(const char *artifact, int index, cft_device **out)
{
    cft_device *dev;

    if (!out)
        return CFT_ERR_INVALID_ARGUMENT;
    *out = NULL;
    if (index < 0)
        return CFT_ERR_INVALID_ARGUMENT;

    /* ==== the remote backend: "cft://host:port" (docs/REMOTE.md) ====
     * One additive spelling of the artifact argument; every other
     * string still means what it always did. The backend does the
     * connecting and the handshake and reports the server's device as
     * this one's capabilities; the handle it returns is dispatched to
     * exactly as the XRT one is, below. */
    if (artifact && strncmp(artifact, "cft://", 6) == 0) {
#ifndef CFT_NO_REMOTE
        uint32_t fmask = 0, groups = 0, tiles = 0, ver = 0;
        cft_seq_caps seq;
        int readable = 1;
        void *hw = NULL;
        int st;
        memset(&seq, 0, sizeof seq);
        backend_call();
        st = cftr_open(artifact, index, &hw, &fmask, &groups, &tiles,
                       &ver, &readable, &seq);
        if (st != CFT_OK)
            return (cft_status)st;
        dev = (cft_device *)calloc(1, sizeof *dev);
        if (!dev) {
            cftr_close(hw);
            return CFT_ERR_OUT_OF_MEMORY;
        }
        dev->backend        = CFT_BACKEND_REMOTE;
        dev->index          = index;
        dev->format_mask    = fmask;
        dev->op_groups      = groups;
        dev->tiles          = tiles;
        dev->device_version = ver;
        dev->flags_readable = readable;
        /* CFT_SEQ_FEAT_INDEXED among them, as of parcel P2: the mask
         * that used to clear it here went out with the refusal it
         * matched, and a remote handle now publishes the bit its
         * server's HELLO publishes, like every other capability.
         *
         * The bit's meaning is "cft_program_run_ex with index tables
         * SUCCEEDS on this device", and it now does: the client
         * gathers before the frame and sends the dense run
         * (cft_backend_program_run's remote branch). Note which way
         * the remaining inaccuracy points - the CLIENT can gather
         * whatever the server publishes, so a handle to a server
         * WITHOUT the bit under-promises rather than over-promises,
         * and a caller who believes it and gathers for themselves gets
         * the right answer by a longer road. The opposite - a word
         * saying yes to a call that says no - is the one this project
         * refuses, and it cannot arise here. */
        dev->seq            = seq;
        dev->backend_name   = "remote";
        dev->hw             = hw;
        *out = dev;
        return CFT_OK;
#else
        return CFT_ERR_NO_DEVICE;
#endif
    }
    /* ==== end of the remote block =================================== */

    if (artifact) {
#ifdef CFT_ENABLE_XRT
        uint32_t fmask = 0, groups = 0, tiles = 0, ver = 0;
        cft_seq_caps seq;
        int readable = 1;
        void *hw = NULL;
        int st;
        memset(&seq, 0, sizeof seq);
        backend_call();
        st = cftx_open(artifact, index, &hw, &fmask, &groups, &tiles,
                       &ver, &readable, &seq);
        if (st != CFT_OK)
            return (cft_status)st;
        dev = (cft_device *)calloc(1, sizeof *dev);
        if (!dev) {
            cftx_close(hw);
            return CFT_ERR_OUT_OF_MEMORY;
        }
        dev->backend        = CFT_BACKEND_XRT;
        dev->index          = index;
        dev->format_mask    = fmask;
        dev->op_groups      = groups;
        dev->tiles          = tiles;
        dev->device_version = ver;
        dev->flags_readable = readable;
        dev->seq            = seq;
        dev->backend_name   = "xrt";
        dev->hw             = hw;
        *out = dev;
        return CFT_OK;
#else
        /* No device backend is compiled into this build, so there is
         * genuinely no such device here - not a bad artifact, and not
         * an unsupported operation. */
        return CFT_ERR_NO_DEVICE;
#endif
    }

    if (index != 0)
        return CFT_ERR_NO_DEVICE;   /* one software backend, and it is 0 */

    dev = (cft_device *)calloc(1, sizeof *dev);
    if (!dev)
        return CFT_ERR_OUT_OF_MEMORY;
    dev->backend        = CFT_BACKEND_SW;
    dev->index          = index;
    /* Every format this build carries. That is all four unless
     * CFT_MAX_FORMAT lowered the ceiling for a part whose RAM cannot
     * hold the wide ones' intermediates (cft_config.h), and then it is
     * the ones below it - published here so a caller finds out from
     * cft_get_caps rather than from a refusal. */
    dev->format_mask    = CFT_FORMAT_MASK_BUILD;
    /* Every assigned group, reductions (bit 5) and the divide/sqrt
     * seeds (bit 6) included. The software backend is the contract,
     * so it implements all of it; a device advertises what its
     * bitstream actually contains. */
    dev->op_groups      = 0x7Fu;
    dev->tiles          = 1;
    dev->device_version = 0;
    dev->flags_readable = 1;
    /* Its own limits, from the file that enforces them, so that the
     * caps this backend reports and the caps it holds a program to
     * are one declaration (host/src/program.c). Deliberately NOT the
     * tile's - see the note there. A build with no sequencer has no
     * CAPACITIES to report and leaves the zeroes calloc gave: a caller
     * reading max_insns == 0 is being told there is no executor here,
     * which is the same thing cft_program_load's absent symbol says
     * at link time.
     *
     * CFT_ALU_EXT_IMUL is the exception, and it has to be. That bit
     * says the ALU implements opcode 30, which this one does whether
     * or not a sequencer is compiled in - it lives in seq_features
     * only because CAPS[28] is where the hardware puts it. Left out,
     * cft_supports() answers no for IMUL and cft_run() refuses an
     * opcode the library computes correctly; the elementwise vector
     * sets then skip 200 cases on a small build and pass, which is
     * exactly the shape of a hole a conformance run must not have.
     * Found by the loopback replay, 2026-09-09. */
#ifndef CFT_NO_PROGRAM
    cft_sw_seq_caps(&dev->seq);
#else
    dev->seq.features = CFT_ALU_EXT_IMUL;
#endif
    /* CAPS2[7] and CAPS2[8] are not the sequencer's either, and unlike
     * IMUL they are not even the ALU's: they are features of THIS file's
     * dense elementwise path (a scalar operand, element 0 for every i)
     * and of cft_reduce_seg (the definition, slice by slice), which every
     * build carries, the -DCFT_NO_PROGRAM one included. So they are
     * published here, after both branches, rather than from
     * cft_sw_seq_caps - which that build compiles out, and which would
     * have left a tiny-profile handle computing a scalar operand while
     * saying it could not. The two refusals that read them (run_impl's
     * scalar refusal and cft_reduce_seg's) read them on THIS backend as
     * well as on a tile's, so the word and the path are one constant:
     * a software handle that stopped publishing either would refuse the
     * call by name rather than go on doing it behind a clear bit.
     *
     * Until 2026-09-24 neither was published here while both calls were
     * computed, so a caller that asked cft_get_caps first, as cft.h tells
     * it to, was told no by a handle that would have said yes (the
     * default build's seq_features was 0x671f; it is 0x7f1f since, and
     * a -DCFT_NO_PROGRAM build's 0x1810 rather than 0x10). */
    dev->seq.features  |= CFT_SEQ_FEAT_SCALAR | CFT_FEAT_REDUCE_SEG;
    dev->backend_name   = "software";
    dev->hw             = NULL;
    *out = dev;
    return CFT_OK;
}

/* ---- the host-side gather (R16, ABI 0.14, docs/ROUND2.md P2) -------
 *
 * The +0 a CFT_IDX_NONE entry reads as, in THIS format's encoding -
 * derived from the same bignum store both executors write their
 * results through, not assumed to be an all-zero element. (It is one,
 * for every binary format this library carries; deriving it is what
 * keeps that true rather than believed.) */
static void idx_zero_elem(uint8_t *dst, size_t esz)
{
    cft_bn z;
    cft_bn_zero(&z);
    cft_bn_store(&z, dst, (int)esz);
}

/* The contract's gather, in the one place every host-side route
 * reaches it: A[i] = idx[i] == CFT_IDX_NONE ? +0 : src[idx[i]], for i
 * in [0, count).
 *
 * Two callers, deliberately one function. The elementwise run's
 * software and remote routes gather their operands with it, and the
 * REMOTE route of a program run gathers its streams and its scratch
 * block with it - the block is n * n_scratch_in entries of the same
 * shape, lane-major, so "count" is all that differs.
 *
 * Every index has already been held to the source's declared length
 * before the run started - by cft_run_ex for the first caller and by
 * seq_check_round2 for the second - so this function cannot be where a
 * bad index is discovered, and does not look. The same division of
 * labour seq_load_in has on the software program path. */
static void idx_gather(uint8_t *dst, const uint8_t *src,
                       const uint32_t *idx, size_t count, size_t esz)
{
    size_t i;
    for (i = 0; i < count; i++) {
        if (idx[i] == CFT_IDX_NONE)
            idx_zero_elem(dst + i * esz, esz);
        else
            memcpy(dst + i * esz, src + (size_t)idx[i] * esz, esz);
    }
}

#if defined(CFT_ENABLE_XRT) || !defined(CFT_NO_REMOTE)
/* program.c asks this to decide which executor a program run belongs
 * to. It is the only thing outside this file that needs to know a
 * device has a backend at all, and it deliberately returns the opaque
 * handle rather than the struct: the shape of cft_device stays this
 * file's business. A remote device (docs/REMOTE.md) has a backend
 * handle too, and gets the same answer. */
void *cft_device_backend(const struct cft_device *dev)
{
    if (!dev)
        return NULL;
    if (dev->backend != CFT_BACKEND_XRT && dev->backend != CFT_BACKEND_REMOTE)
        return NULL;
    return dev->hw;
}

/* ==== the remote block's dispatcher (backend.h) =======================
 * Which device backend a program run belongs to is decided here, where
 * the backend kind lives, so that program.c names neither of them. */
int cft_backend_program_run(struct cft_device *dev, int fmt,
                            const void *image, size_t image_bytes,
                            const cft_seq_run_io *io,
                            uint32_t max_deposits,
                            const void *a, const void *b, const void *c,
                            void *deposits, uint32_t *counts, size_t n,
                            uint32_t *flags, uint32_t *bus)
{
#ifdef CFT_ENABLE_XRT
    if (dev && dev->backend == CFT_BACKEND_XRT) {
        cft_bindings bd;
        size_t esz = cft_format_size((cft_format)fmt);
        bind_clear(&bd);
        /* The three streams, the deposit window, and the two scratch
         * blocks. `counts` is four bytes an element whatever the format
         * and the image and bank do not grow with n at all, so none of
         * THOSE is worth a device copy - backend.h says so beside the
         * signature.
         *
         * The scratch blocks are not in that category and used to be
         * filed with it. They are n_scratch_in slots for each of n
         * lanes, lane-major and dense (docs/SEQUENCER.md R5) - the same
         * shape as the deposit window's n * max_deposits, and they grow
         * with n for the same reason. An integrator's per-step state
         * lives there and is rewritten every corrector pass, so staging
         * it put a round trip in the innermost loop
         * (cft-rebound/docs/HARDWARE.md, the first ask). */
        /* R16 on a tile that cannot gather is REFUSED BY NAME, which
         * is the whole reason CAPS2[9] exists. The alternative - hand
         * the run over and let the tile refuse MODE[22:19] - comes back
         * as STATUS[3], which reads as "this bitstream lacks the
         * precision" and names nothing; and a tile old enough to ignore
         * the bits instead would answer from the DENSE stream, which is
         * a wrong number with clean flags. The software backend always
         * carries it, and the remote route gathers on the client below
         * (P2) and so needs no bit. */
        if (io && (io->idx_a || io->idx_b || io->idx_c ||
                   io->idx_scratch_in) &&
            !(dev->seq.features & CFT_SEQ_FEAT_INDEXED)) {
            cft_set_error(
                "an indexed input block needs CFT_SEQ_FEAT_INDEXED, which "
                "this device does not publish (CAPS2[9]); ask cft_get_caps "
                "before passing a table, or gather on the host and pass "
                "the dense block");
            return CFT_ERR_UNSUPPORTED;
        }
        /* R17 on a tile that cannot mask, for the same reason and with
         * the same shape: an ignored mask runs every lane and writes
         * over the caller's bytes in the lanes it was told to leave
         * alone - confidently, with clean flags and the right answer
         * in the lanes anyone would check. */
        if (io && io->lane_mask &&
            !(dev->seq.features & CFT_SEQ_FEAT_LANE_MASK)) {
            cft_set_error(
                "a lane mask needs CFT_SEQ_FEAT_LANE_MASK, which this "
                "device does not publish (CAPS2[10]); ask cft_get_caps "
                "before passing one, or run the masked lanes and ignore "
                "their outputs");
            return CFT_ERR_UNSUPPORTED;
        }
        /* R16: a stream with a table is the SOURCE the table indexes,
         * and its length is `idx_*_src` rather than n - shorter than
         * the run in the shape this feature exists for, and allowed to
         * be longer. The window this registers and brings home has to
         * be that one: bound at n * esz, a longer source would be
         * truncated on the device and a shorter one over-read, and the
         * bound the run is held to (seq_check_round2 refuses an index
         * at or past idx_*_src) would be checked against a length
         * nothing had staged. The scratch pool already works this way
         * - scratch_in_bytes IS the pool's length - and this is the
         * same rule for the three streams, which have no such field. */
        {
            const void *strm[3];
            size_t sbytes[3];
            int r;
            strm[0] = a; strm[1] = b; strm[2] = c;
            sbytes[0] = ((io && io->idx_a) ? io->idx_a_src : n) * esz;
            sbytes[1] = ((io && io->idx_b) ? io->idx_b_src : n) * esz;
            sbytes[2] = ((io && io->idx_c) ? io->idx_c_src : n) * esz;
            for (r = 0; r < 3; r++) {
                buf_sync_in(dev, strm[r], sbytes[r]);
                bind_role(dev, &bd, CFT_ROLE_A + r, strm[r], sbytes[r]);
            }
        }
        if (max_deposits)
            bind_role(dev, &bd, CFT_ROLE_D, deposits,
                      n * max_deposits * esz);
        if (io && io->scratch_in_bytes) {
            /* Read by the tile, so it is brought home first, exactly as
             * a, b and c are. scratch_out needs none of this: it is
             * written and not read, which is why `d` needs none. */
            buf_sync_in(dev, io->scratch_in, io->scratch_in_bytes);
            bind_role(dev, &bd, CFT_ROLE_SI, io->scratch_in,
                      io->scratch_in_bytes);
        }
        if (io && io->scratch_out_bytes)
            bind_role(dev, &bd, CFT_ROLE_SO, io->scratch_out,
                      io->scratch_out_bytes);
        /* The four index tables (ABI 0.14), on exactly the scratch
         * block's terms: READ by the tile, so each is brought home
         * first, and bound where it is a resident buffer so a caller
         * who fills a table once and runs many pays no round trip for
         * it - which is the shape the gravity fold has, where the
         * table is rebuilt once a step and read by every call in it.
         *
         * Four bytes an entry at every format, because a table holds
         * INDICES and not elements: n of them for a stream and
         * n * n_scratch_in for the block, lane-major as the block is.
         * Guarded on the pointer alone - a table with no entries is
         * not a table, and n is non-zero here. */
        if (io) {
            const void *itab[3];
            int r;
            itab[0] = io->idx_a; itab[1] = io->idx_b; itab[2] = io->idx_c;
            for (r = 0; r < 3; r++) {
                if (!itab[r])
                    continue;
                buf_sync_in(dev, itab[r], n * 4u);
                bind_role(dev, &bd, CFT_ROLE_IA + r, itab[r], n * 4u);
            }
            if (io->idx_scratch_in && io->n_scratch_in) {
                size_t ib = n * (size_t)io->n_scratch_in * 4u;
                buf_sync_in(dev, io->idx_scratch_in, ib);
                bind_role(dev, &bd, CFT_ROLE_ISI, io->idx_scratch_in, ib);
            }
            /* ...and the lane mask (R17), which is brought home like
             * the tables and then NOT BOUND. A tile's mask is a
             * function of the tile's SLICE and not a window of the
             * caller's buffer: its bit 0 has to be the tile's lane 0,
             * and a slice does not start on a byte boundary at every
             * format (host/src/slice.h cuts in beats and a beat is one
             * lane at fp256). So the backend repacks it into the
             * tile's own buffer on every launch, the way it pads an
             * operand up to a beat, and there is no configuration in
             * which pointing the tile at the caller's bytes is right
             * for more than one tile. The sync still has to happen -
             * the repack READS the host mirror, so a resident buffer's
             * device copy is brought home first, exactly as it is for
             * a table. */
            if (io->lane_mask && io->lane_mask_bytes)
                buf_sync_in(dev, io->lane_mask, io->lane_mask_bytes);
        }
        backend_call();
        return cftx_program_run(dev->hw, fmt, image, image_bytes, io,
                                max_deposits, a, b, c, deposits, counts, n,
                                &bd, flags, bus);
    }
#endif
#ifndef CFT_NO_REMOTE
    if (dev && dev->backend == CFT_BACKEND_REMOTE) {
        /* R16 over the wire is a CLIENT-SIDE GATHER (docs/ROUND2.md,
         * parcel P2). The protocol has no field for a table and gains
         * none: the tables are resolved here, into dense temporaries,
         * and what crosses is the dense program run the server already
         * understands - no new opcode, no new frame, and a server that
         * predates this parcel answers it.
         *
         * The SAVING is not portable and the CALL is, which is the
         * same division cft_run_ex's scalar mask shipped with and is
         * the honest one for a socket: the run's n elements cross
         * either way, so a table on the wire would buy a protocol
         * field and nothing else. What it buys the caller is that one
         * source works on every backend.
         *
         * The deposits land dense as they already do, so nothing is
         * unpacked on the way back.
         *
         * Every index has been held to its source's length by
         * seq_check_round2 before this point, on this same host, so
         * the gathers below cannot read past a source. */
        int need_gather = io && (io->idx_a || io->idx_b || io->idx_c ||
                                 io->idx_scratch_in);
        if (need_gather) {
            const size_t resz = cft_format_size((cft_format)fmt);
            const void *strm[3];
            uint8_t *tmp[4];
            cft_seq_run_io dio = *io;
            int r, rc;

            strm[0] = a; strm[1] = b; strm[2] = c;
            tmp[0] = tmp[1] = tmp[2] = tmp[3] = NULL;
            for (r = 0; r < 3; r++) {
                const uint32_t *t = (r == 0) ? io->idx_a
                                  : (r == 1) ? io->idx_b : io->idx_c;
                if (!t)
                    continue;
                tmp[r] = (uint8_t *)malloc(n * resz);
                if (!tmp[r]) {
                    while (r-- > 0) free(tmp[r]);
                    return CFT_ERR_OUT_OF_MEMORY;
                }
                idx_gather(tmp[r], (const uint8_t *)strm[r], t, n, resz);
                strm[r] = tmp[r];
            }
            if (io->idx_scratch_in && io->n_scratch_in) {
                /* The block, lane-major, n * n_scratch_in entries out
                 * of a pool of idx_scratch_src elements - and the
                 * dense block's byte count is the BLOCK's, not the
                 * pool's, which is the one field that changes meaning
                 * when the table goes. */
                size_t entries = n * (size_t)io->n_scratch_in;
                tmp[3] = (uint8_t *)malloc(entries * resz);
                if (!tmp[3]) {
                    free(tmp[2]); free(tmp[1]); free(tmp[0]);
                    return CFT_ERR_OUT_OF_MEMORY;
                }
                idx_gather(tmp[3], (const uint8_t *)io->scratch_in,
                           io->idx_scratch_in, entries, resz);
                dio.scratch_in       = tmp[3];
                dio.scratch_in_bytes = entries * resz;
            }
            dio.idx_a = dio.idx_b = dio.idx_c = NULL;
            dio.idx_scratch_in = NULL;
            dio.idx_a_src = dio.idx_b_src = dio.idx_c_src = 0;
            dio.idx_scratch_src = 0;
            backend_call();
            rc = cftr_program_run(dev->hw, fmt, image, image_bytes, &dio,
                                  max_deposits, strm[0], strm[1], strm[2],
                                  deposits, counts, n, flags, bus);
            free(tmp[3]); free(tmp[2]); free(tmp[1]); free(tmp[0]);
            return rc;
        }
        backend_call();
        return cftr_program_run(dev->hw, fmt, image, image_bytes, io,
                                max_deposits, a, b, c, deposits, counts, n,
                                flags, bus);
    }
#endif
    (void)fmt; (void)image; (void)image_bytes; (void)max_deposits;
    (void)io;
    (void)a; (void)b; (void)c; (void)deposits; (void)counts; (void)n;
    (void)flags; (void)bus;
    return CFT_ERR_INTERNAL;
}
/* ==== end of the remote block ======================================= */
#endif

CFT_API void cft_close(cft_device *dev)
{
    if (!dev)
        return;
    /* Release every live buffer's DEVICE side before the device goes,
     * and unlink it from the handle that is about to stop existing.
     *
     * The buffer itself survives as plain host memory: its mirror is
     * this file's allocation and cft_buffer_data still answers,
     * cft_buffer_free is still the way to release it, and the two
     * sync calls become the no-ops they are on a backend without
     * device memory. That keeps the promise cft_close() and
     * cft_buffer_free() have always made about order and NULLs -
     * closing first is allowed and is not a use-after-free - and it is
     * the only ordering a language binding with a garbage collector
     * can actually guarantee. */
    {
        cft_buffer *b = dev->bufs;
        while (b) {
            cft_buffer *next = b->next;
#ifdef CFT_ENABLE_XRT
            if (b->dbuf)
                cftx_buffer_destroy(b->dbuf);
#endif
            b->dbuf = NULL;
            b->dev  = NULL;
            b->next = NULL;
            b = next;
        }
        dev->bufs = NULL;
    }
#ifdef CFT_ENABLE_XRT
    if (dev->hw && dev->backend == CFT_BACKEND_XRT)
        cftx_close(dev->hw);
#endif
#ifndef CFT_NO_REMOTE
    if (dev->hw && dev->backend == CFT_BACKEND_REMOTE)
        cftr_close(dev->hw);
#endif
    free(dev);
}

/* ---- the library's own last-error slot ------------------------------
 *
 * The two device backends keep a message each and clear it at the
 * start of every call they make, so each is non-empty only while its
 * own most recent call is the one that failed. This is the third
 * source and it follows the same discipline from the other side:
 * anything in libcft that refuses without reaching a backend writes
 * here, and every call that DOES reach a backend clears it first -
 * backend_call() below, immediately before each cftx_/cftr_ call, and
 * this file holds all of them. Without that, a program refused at
 * load would go on explaining a run that failed for another reason
 * ten calls later.
 *
 * Its producers are the library's refusals by name - this file's,
 * program.c's, and the other modules' through the helpers backend.h
 * declares; cft_program_load's capacity refusal was the first
 * (2026-09-07).
 *
 * Its size is a build choice (cft_config.h): on a part with two
 * kilobytes of RAM a 320-byte buffer is sixteen percent of it. At
 * CFT_ERRMSG_MAX == 1 the slot is the empty string cft_last_error()
 * must still return, and the vsnprintf that would have filled it goes
 * with it - though not every formatted write does: render_format_mask,
 * below, still builds its argument and the slot drops the sentence.
 * So a refusal in such a build keeps its status and loses its
 * sentence, and most of this file's refusals are compiled into every
 * profile, sequencer or not. */
static char g_msg[CFT_ERRMSG_MAX];

void cft_set_error(const char *fmt, ...)
{
#if CFT_ERRMSG_MAX > 1
    va_list ap;
    va_start(ap, fmt);
    vsnprintf(g_msg, sizeof g_msg, fmt, ap);
    va_end(ap);
#else
    (void)fmt;
#endif
}

#if defined(CFT_ENABLE_XRT) || !defined(CFT_NO_REMOTE)
/* Called immediately before handing anything to a device backend. A
 * build with no device backend hands nothing to one. */
static void backend_call(void)
{
    g_msg[0] = '\0';
}
#endif

int cft_seq_cap_refusal(const char *field, unsigned long asked,
                        unsigned long cap, const char *units,
                        const char *caps_field)
{
    /* The program's number first, the device's second, and the name of
     * the field that would have answered in advance third: what a
     * caller has to change is the first of the three, and what it
     * should have asked is the last. */
    cft_set_error("this program's %s is %lu; this device's is %lu (%s). "
                  "Ask cft_get_caps - cft_caps.%s - before building one: a "
                  "device refuses an image past its capacities itself, with "
                  "a status bit and no explanation",
                  field, asked, cap, units, caps_field);
    return CFT_ERR_UNSUPPORTED;
}

/* The CAPS[15:8] opcode groups by name, in op_group_bit's numbering. */
static const char *const group_names[8] = {
    "arithmetic", "sign", "min/max", "predicate/select",
    "integer", "reduction", "divide/sqrt seeds", "sequencer"
};

/* "fp32 fp64 fp128": the formats a mask names, space-separated, in
 * the library's own vocabulary. A mask with nothing set is said so,
 * because an empty list reads as a formatting accident. */
static const char *render_format_mask(uint32_t mask, char *buf, size_t len)
{
    int f;
    size_t used = 0;
    buf[0] = '\0';
    for (f = 0; f < 4; f++) {
        int k;
        if (!(mask & (1u << f)))
            continue;
        k = snprintf(buf + used, len - used, "%s%s", used ? " " : "",
                     cft_format_name((cft_format)f));
        if (k < 0 || (size_t)k >= len - used)
            break;
        used += (size_t)k;
    }
    if (!buf[0])
        snprintf(buf, len, "no format at all");
    return buf;
}

int cft_absent_format_refusal(int fmt)
{
    char have[64];
    /* The same shape as the device refusal below - what IS carried,
     * then what was asked for - because a caller reads both the same
     * way, and device-test holds both to naming every carried format. */
    cft_set_error("this libcft build carries %s; %s is above its format "
                  "ceiling (CFT_MAX_FORMAT is %d in cft_config.h), so no "
                  "backend of this build can carry it - cft_get_caps - "
                  "cft_caps.format_mask - says so before a run",
                  render_format_mask(CFT_FORMAT_MASK_BUILD, have, sizeof have),
                  cft_format_name((cft_format)fmt), (int)CFT_MAX_FORMAT);
    return CFT_ERR_UNSUPPORTED;
}

int cft_device_format_refusal(uint32_t mask, int fmt, const char *entry)
{
    char have[64];
    cft_set_error("%s: this device carries %s; %s is not among them. "
                  "cft_supports(dev, op, fmt), or cft_get_caps - "
                  "cft_caps.format_mask - says so before a run; a device "
                  "refuses a precision it lacks itself, with STATUS[3] "
                  "and no explanation",
                  entry, render_format_mask(mask, have, sizeof have),
                  cft_format_name((cft_format)fmt));
    return CFT_ERR_UNSUPPORTED;
}

int cft_op_group_refusal(int op, const char *entry)
{
    int g = op_group_bit(op);
    cft_set_error("%s: opcode %d (%s) is in CAPS group %d (%s, CAPS[%d]), "
                  "which this device does not implement - "
                  "cft_supports(dev, op, fmt) says so before a run",
                  entry, op, cft_op_name((cft_op)op), g,
                  (g >= 0 && g < 8) ? group_names[g] : "unassigned", 8 + g);
    return CFT_ERR_UNSUPPORTED;
}

int cft_composed_refusal(const char *entry, const char *needs, int fmt)
{
    cft_set_error("%s is composed from %s, which this device does not "
                  "support at %s - cft_supports(dev, %s, fmt) says so "
                  "before a call",
                  entry, needs, cft_format_name((cft_format)fmt), needs);
    return CFT_ERR_UNSUPPORTED;
}

void cft_device_seq_caps(const struct cft_device *dev, cft_seq_caps *out)
{
    if (!out)
        return;
    if (!dev) {
        memset(out, 0, sizeof *out);
        return;
    }
    *out = dev->seq;
}

CFT_API const char *cft_last_error(void)
{
    /* This library's own message first: it is cleared the moment
     * anything reaches a backend, so it is non-empty only while the
     * most recent failure was one libcft made on its own. */
    if (*g_msg)
        return g_msg;
    /* Two device backends keep a message each. The remote one clears
     * its own at the start of every call it makes, so its message is
     * non-empty only while its most recent call is the one that
     * failed - which is exactly when it is the message to show. */
#ifndef CFT_NO_REMOTE
    if (*cftr_last_error())
        return cftr_last_error();
#endif
#ifdef CFT_ENABLE_XRT
    return cftx_last_error();
#else
    return "";
#endif
}

CFT_API cft_status cft_get_caps(cft_device *dev, cft_caps *out)
{
    cft_caps c;
    size_t want;

    if (!dev || !out)
        return CFT_ERR_INVALID_ARGUMENT;
    want = out->struct_size;
    if (want < sizeof(size_t))
        return CFT_ERR_INVALID_ARGUMENT;

    memset(&c, 0, sizeof c);
    c.format_mask    = dev->format_mask;
    c.tiles          = dev->tiles;
    c.abi_version    = cft_abi_version();
    /* The hardware contract version. A software backend does not have
     * one: it models a contract, but reporting a version it is not
     * would let a host believe it had talked to a device. */
    c.device_version = dev->device_version;
    c.flags_readable = dev->flags_readable;
    strncpy(c.backend, dev->backend_name, sizeof c.backend - 1);
    /* Appended in ABI 0.8; a caller with the older struct passes the
     * older struct_size and the memcpy below stops before them. */
    c.max_deposits   = dev->seq.max_deposits;
    c.max_insns      = dev->seq.max_insns;
    c.max_consts     = dev->seq.max_consts;
    c.seq_features   = dev->seq.features;
    /* Appended in ABI 0.10, on the same terms again. */
    c.max_scratch    = dev->seq.max_scratch;
    /* And in ABI 0.11. Answered from which BACKEND this is, not from
     * anything a device told us: the software backend's cft_alloc is
     * a host allocation, a remote handle's buffers stay on the client
     * (docs/REMOTE.md), and only the XRT backend keeps device copies.
     * A build without XRT has no such backend at all and answers 0
     * everywhere, which is exactly true of it. */
#ifdef CFT_ENABLE_XRT
    c.buffers_resident = (dev->backend == CFT_BACKEND_XRT) ? 1 : 0;
#else
    c.buffers_resident = 0;
#endif

    if (want > sizeof c)
        want = sizeof c;
    /* struct_size comes back as the number of bytes actually filled,
     * so a caller built against a newer header can tell what it got
     * rather than reading its own zeroes as answers. */
    c.struct_size = want;
    memcpy(out, &c, want);
    return CFT_OK;
}

CFT_API int cft_supports(cft_device *dev, cft_op op, cft_format fmt)
{
    int group;
    if (!dev)
        return 0;
    if (CFT_FMT_OUT_OF_RANGE(fmt))
        return 0;
    if (!(dev->format_mask & (1u << (int)fmt)))
        return 0;
    if (!cft_sf_op_assigned((int)op))
        return 0;
    /* A device may carry fewer opcode groups than the contract
     * assigns - that is what CAPS[15:8] is for, and asking is the
     * whole point of a portable binary running against several
     * generations of hardware. */
    group = op_group_bit((int)op);
    if (group < 0)
        return 0;
    if (!(dev->op_groups & (1u << group)))
        return 0;
    /* IMUL joined the integer group after bitstreams shipped with that
     * group's bit set, so the group cannot vouch for it: CAPS[28] does
     * (cft_caps.seq_features, CFT_ALU_EXT_IMUL). Live since 2026-09-24:
     * until then cft_sf_op_assigned left 30 off, the return above fired
     * first, and this answered no for IMUL on every device - a software
     * handle and a CAPS[28] tile included (softfloat.c says the rest). */
    if ((int)op == (int)CFT_IMUL && !(dev->seq.features & CFT_ALU_EXT_IMUL))
        return 0;
    /* A composed reduction is supported only if what it composes from
     * is: sumSquare needs the arithmetic group for its multiply and
     * sumAbs the sign group for its abs. Answering yes and then
     * refusing the call would make cft_supports() the wrong question
     * to ask. */
    group = reduce_helper_group((int)op);
    if (group >= 0 && !(dev->op_groups & (1u << group)))
        return 0;
    return 1;
}

/* ---------------------------------------------------------------
 * The core call
 * --------------------------------------------------------------- */

/* ---- R16 for an ELEMENTWISE run (ABI 0.14, docs/ROUND2.md P2) ------
 *
 * The three tables and their sources' lengths, as one argument rather
 * than six: cft_run carries none of them and passes NULL, cft_run_ex
 * fills one in. A NULL `tab`, and a `tab` whose three pointers are all
 * NULL, are the same dense run - which is what makes every existing
 * call site of run_impl unchanged in behaviour as well as in shape. */
typedef struct {
    const uint32_t *idx[3];
    size_t          src[3];
} run_tables;

static int tables_present(const run_tables *tab)
{
    return tab && (tab->idx[0] || tab->idx[1] || tab->idx[2]);
}

/* Do two byte windows share a byte? Used for the aliasing rule below.
 * Comparing pointers into separate objects is what buf_find in this
 * file already does to decide whether a caller's operand lies inside a
 * registered buffer, and for the same reason: there is no portable
 * answer and every backend this library targets is flat-addressed. */
static int windows_overlap(const void *p, size_t pbytes,
                           const void *q, size_t qbytes)
{
    const uint8_t *x = (const uint8_t *)p;
    const uint8_t *y = (const uint8_t *)q;
    if (!x || !y || !pbytes || !qbytes)
        return 0;
    return (x < y + qbytes) && (y < x + pbytes);
}

/* A little-endian word into the composed image below. The image format
 * is docs/SEQUENCER.md's and it is little-endian on the wire whatever
 * this host is, which is why this exists rather than a cast. Only the
 * composition builds an image, so it lives under the same guard. */
#ifndef CFT_NO_PROGRAM
static void put_le32_img(uint8_t *p, uint32_t v)
{
    p[0] = (uint8_t)v;
    p[1] = (uint8_t)(v >> 8);
    p[2] = (uint8_t)(v >> 16);
    p[3] = (uint8_t)(v >> 24);
}
#endif

/* The elementwise run, with the scalar mask. cft_run and cft_run_ex are
 * both one line over this; the body stayed where it was rather than being
 * moved into a new entry point, because the diff of a move is unreadable
 * and this is the function every backend dispatch lives in.
 *
 * scalar_mask: bit 0 a, bit 1 b, bit 2 c. A set bit makes that operand
 * one element that applies to the whole run. */
static cft_status run_impl(cft_device *dev,
                           cft_op      op,
                           cft_format  fmt,
                           cft_round   rnd,
                           const void *a,
                           const void *b,
                           const void *c,
                           void       *d,
                           size_t      n,
                           uint32_t    scalar_mask,
                           const run_tables *tab,
                           uint32_t   *flags_out,
                           uint32_t   *bus_out);

/* The two R16 routes, defined after run_impl because each of them ends
 * in a dense run through it. Which one a call takes is decided in one
 * place, inside run_impl and after every check it already makes, so
 * that an indexed run is refused for a bad format, a bad attribute, a
 * reduction opcode or an opcode group this device lacks in exactly the
 * words and exactly the order a dense one is. */
static cft_status run_gathered(cft_device *dev, cft_op op, cft_format fmt,
                               cft_round rnd, const void *a, const void *b,
                               const void *c, void *d, size_t n,
                               uint32_t scalar_mask, const run_tables *tab,
                               size_t esz, uint32_t *flags_out,
                               uint32_t *bus_out);
/* The composition is a PROGRAM, so it exists only where the sequencer
 * and its loader do. A profile built with -DCFT_NO_PROGRAM (which is
 * what -DCFT_TINY selects, bindings/arduino/loopback) has neither
 * cft_program_load nor cft_program_run_ex to call, and no device in
 * such a build can publish CFT_SEQ_FEAT_INDEXED either - so the host
 * gather is not a lesser route there, it is the only one there is. */
#ifndef CFT_NO_PROGRAM
static cft_status run_composed(cft_device *dev, cft_op op, cft_format fmt,
                               cft_round rnd, const void *a, const void *b,
                               const void *c, void *d, size_t n,
                               uint32_t scalar_mask, const run_tables *tab,
                               size_t esz, uint32_t *flags_out,
                               uint32_t *bus_out);
#endif

static cft_status run_impl(cft_device *dev,
                           cft_op      op,
                           cft_format  fmt,
                           cft_round   rnd,
                           const void *a,
                           const void *b,
                           const void *c,
                           void       *d,
                           size_t      n,
                           uint32_t    scalar_mask,
                           const run_tables *tab,
                           uint32_t   *flags_out,
                           uint32_t   *bus_out)
{
    const cft_fmt_desc *f;
    const uint8_t *pa, *pb, *pc;
    uint8_t *pd;
    size_t esz, i;
    unsigned need;
    uint32_t acc = 0;
    cft_bn ba, bb, bc, bo;

    if (bus_out)
        *bus_out = 0;
    if (!dev)
        return CFT_ERR_INVALID_ARGUMENT;
    if (CFT_FMT_ABSENT(fmt))
        return (cft_status)cft_absent_format_refusal((int)fmt);
    if (CFT_FMT_OUT_OF_RANGE(fmt))
        return CFT_ERR_INVALID_ARGUMENT;
    if ((int)rnd < 0 || (int)rnd > 4)
        return CFT_ERR_INVALID_ARGUMENT;
    /* The device carries the opcode in a byte. Anything wider is a
     * caller mistake; anything inside it that is unassigned is not -
     * it has a defined answer, produced below. */
    if ((int)op < 0 || (int)op > 255)
        return CFT_ERR_INVALID_ARGUMENT;
    if (!(dev->format_mask & (1u << (int)fmt)))
        return (cft_status)cft_device_format_refusal(dev->format_mask,
                                                     (int)fmt, "cft_run");
    /* A reduction cannot be evaluated elementwise, so this is not the
     * call for it. Refused BEFORE the backend dispatch below, so the
     * software and device paths give the same answer - the alternative
     * is software returning an error while a device that has never
     * heard of opcode 24 returns the unassigned-opcode result, and two
     * backends disagreeing is the one outcome this project cannot
     * ship. */
    if (cft_sf_is_reduction((int)op))
        return CFT_ERR_INVALID_ARGUMENT;
    /* An assigned opcode whose group this device lacks is refused
     * here, not issued and hoped for. A trimmed bitstream does not
     * fault on an opcode it does not implement - it returns whatever
     * the absent bank drives, which is zeros with clean flags, and
     * that is the worst possible shape for a wrong answer. An
     * UNASSIGNED opcode is a different case and still runs: the
     * contract gives it a defined result, the canonical quiet NaN
     * with invalid raised, and the device produces it. */
    {
        int group = op_group_bit((int)op);
        if (group >= 0 && !(dev->op_groups & (1u << group)))
            return (cft_status)cft_op_group_refusal((int)op, "cft_run");
        if ((int)op == (int)CFT_IMUL &&
            !(dev->seq.features & CFT_ALU_EXT_IMUL)) {
            cft_set_error("opcode 30 (imul) is not implemented by this "
                          "device: CAPS[28] is clear, the image predates "
                          "2026-09-07 - cft_supports says so first");
            return CFT_ERR_UNSUPPORTED;
        }
    }

    if (n == 0) {
        cft_flags_emit(dev, 0, flags_out);
        return CFT_OK;
    }
    if (!d)
        return CFT_ERR_INVALID_ARGUMENT;

    need = cft_sf_op_operands((int)op);
    if (((need & 1u) && !a) || ((need & 2u) && !b) || ((need & 4u) && !c))
        return CFT_ERR_INVALID_ARGUMENT;

    f   = &cft_sf_formats[(int)fmt];
    esz = (size_t)f->width / 8;
    if (n > ((size_t)-1) / esz)
        return CFT_ERR_INVALID_ARGUMENT;

    /* ==== R16's two MEMORY-TOUCHING argument rules ===================
     *
     * They live HERE, and not beside the shape rules in cft_run_ex,
     * because they are the first things in this call that read a
     * caller's index table or compute a byte count from `n` - and
     * everything above this line is every check the DENSE path makes
     * before it touches a byte: the format, the attribute, the opcode
     * and its group, the early return for n == 0, the NULL output,
     * the NULL operand an opcode requires, and `n > SIZE_MAX / esz`.
     *
     * Putting them before those was a regression of the elementwise
     * entry point and not only of the new feature (V2, 2026-09-15): an
     * `n` the dense path refuses as an argument error without touching
     * a byte walked the caller's table for n entries first, and
     * n = 2**61 with an 8-entry table segmentation-faulted where the
     * same n with no table returned CFT_ERR_INVALID_ARGUMENT. The
     * ordering rule is unchanged and is now true of memory as well as
     * of messages: argument errors before capability refusals, and no
     * byte of a caller's buffer read until every dense-path check has
     * passed.
     *
     * Behind run_impl's checks rather than duplicating the two named
     * ones, so that a check added to the dense path later is inherited
     * here instead of being forgotten here. */
    if (tables_present(tab)) {
            const void *opnd[3];
            int r;
            opnd[0] = a; opnd[1] = b; opnd[2] = c;
        /* ALIASING. `d` may alias a, b or c in a DENSE run and still
         * may: the element loop loads before it stores and element i
         * of the output is element i of the input, so the two never
         * disagree. WITH A TABLE the run is a different machine and
         * `d` may overlap nothing.
         *
         * For the indexed operand itself the reason is immediate: lane
         * i reads source[idx[i]], which is ANY element of the source
         * rather than element i, so a source the run is also writing is
         * read after write and the answer depends on the order the
         * lanes happen to run in.
         *
         * For the DENSE operands beside it the reason is the route. A
         * table makes this run a program on a device, and a program's
         * deposit window is a separate buffer ROLE with its own write
         * discipline - the software executor zeroes the whole window
         * before its first block, the XRT path binds it as an output
         * and never syncs it in - so `d` overlapping any operand means
         * something different on each backend. Refusing all three is
         * the only rule that gives one answer everywhere, which is
         * worth more than the in-place update it costs: a caller who
         * wants one can run into their own buffer and copy, and will
         * know they did.
         *
         * Refused on every backend and not only where it bites - the
         * software route gathers into temporaries first and would
         * survive it, and a rule that held on two backends out of three
         * is not a rule.
         *
         * Windows, not pointers: an indexed source is idx_*_src
         * elements, a dense one is n, the output is n, and none of them
         * need start at the same place to collide. */
        const size_t fsz = cft_format_size(fmt);
        const size_t dbytes = n * fsz;
        for (r = 0; r < 3; r++) {
            size_t obytes;
            if (!opnd[r])
                continue;
            obytes = (tab->idx[r] ? tab->src[r]
                             : ((scalar_mask >> r) & 1u)
                                 ? 1u : n) * fsz;
            if (windows_overlap(d, dbytes, opnd[r], obytes)) {
                cft_set_error(
                    "cft_run_ex: d overlaps operand %c, and a run with "
                    "an index table may not write over any of its "
                    "operands (%lu elements at %c, %lu written at d); "
                    "a gathered lane reads any element of its source, "
                    "and the deposit window of the program this "
                    "composes into is a separate buffer - give the "
                    "gather its own output",
                    'a' + r, (unsigned long)(obytes / fsz), 'a' + r,
                    (unsigned long)n);
                return CFT_ERR_INVALID_ARGUMENT;
            }
        }
        /* The bound, checked BEFORE the run and on every backend, by
         * name and by value: an index at or past the source's declared
         * length is refused, because a device must never read past a
         * buffer for a caller. Word for word the rule seq_check_round2
         * holds a program run to, so the composed route and the program
         * it composes into refuse the same table with the same
         * sentence. CFT_IDX_NONE is not an index and is never out of
         * range. */
        for (r = 0; r < 3; r++) {
            size_t e;
            if (!tab->idx[r])
                continue;
            for (e = 0; e < n; e++) {
                if (tab->idx[r][e] == CFT_IDX_NONE)
                    continue;
                if ((size_t)tab->idx[r][e] >= tab->src[r]) {
                    cft_set_error(
                        "cft_run_ex: idx_%c[%lu] = %lu is at or past the "
                        "%lu elements idx_%c_src says operand %c holds",
                        'a' + r, (unsigned long)e,
                        (unsigned long)tab->idx[r][e], (unsigned long)tab->src[r],
                        'a' + r, 'a' + r);
                    return CFT_ERR_INVALID_ARGUMENT;
                }
            }
        }
    }
    /* ==== R16: an indexed elementwise run (ABI 0.14) =================
     *
     * The fork, and the only one. Everything above is what a dense run
     * checks and it is checked identically; everything below is the
     * dense run itself, which both routes end in.
     *
     * On a DEVICE the run is composed as a three-instruction program
     * over P1's mechanism, so the tile does the gather and the bytes
     * the caller did not ask for never cross the bus - which is the
     * whole of the ask (docs/ROUND2.md, asks 1 and 4).
     *
     * On the software and the remote backends it is gathered HERE and
     * the dense path runs over the gathered block. That is not a
     * fallback to apologise for on either one: the software backend is
     * the CONTRACT, and the contract's sentence is "the run proceeds
     * exactly as a dense run over the gathered block", so gathering
     * and running dense is the definition rather than an
     * approximation of it. On the remote backend the SAVING was never
     * portable and the CALL is - the same division cft_run_ex's scalar
     * mask already ships with, and for the same reason: the whole
     * array crosses the socket either way, so a table on the wire
     * would buy a protocol field and nothing else. */
    if (tables_present(tab)) {
#ifndef CFT_NO_PROGRAM
        if (dev->backend == CFT_BACKEND_XRT && a)
            return run_composed(dev, op, fmt, rnd, a, b, c, d, n,
                                scalar_mask, tab, esz, flags_out, bus_out);
#endif
        /* `a` NULL on a device is the one shape the composition cannot
         * express - a program run's stream a is required - and it is
         * unreachable rather than merely unlikely: the only opcodes
         * that do not require `a` are the unassigned ones, whose
         * cft_sf_op_operands is zero, and cft_run_ex refuses a table
         * on an operand the opcode does not read. The host gather is
         * here so that "unreachable" does not have to be load
         * bearing. */
        return run_gathered(dev, op, fmt, rnd, a, b, c, d, n,
                            scalar_mask, tab, esz, flags_out, bus_out);
    }
    /* ==== end of R16 ================================================= */

    /* A scalar operand on a device that cannot do it is refused BY NAME,
     * which is the whole reason CAPS2[7] exists. The alternative - run it
     * anyway and let the tile ignore MODE[18:16] - reads n elements from
     * a one-element buffer, and that is an out-of-bounds read rather than
     * a wrong number.
     *
     * The test is the BIT, on every backend that computes here, and not
     * "is this a tile": the software backend publishes CFT_SEQ_FEAT_SCALAR
     * (cft_open, above) and indexes element 0, and reading the same word
     * on it is what makes that publication load-bearing - drop the bit
     * and this refuses, rather than a caller who asked first being told
     * no by a handle that goes on computing the call (the state of this
     * library until 2026-09-24, when the test was `backend == XRT`).
     * The REMOTE backend is the one exception and is excluded by name: it
     * never sets MODE[18:16] anywhere - its block below expands the
     * operand before a frame exists - so the server's CAPS2[7], which is
     * all its word can carry, gates nothing on that route. A remote
     * handle therefore takes a scalar operand whatever its word says: it
     * can say no to a call that works (a server fronting a tile without
     * the bit), never yes to one that is refused.
     *
     * AFTER the R16 fork, deliberately (V2, 2026-09-15). The refusal is
     * about MODE[18:16], and MODE[18:16] is what the DENSE device route
     * uses; the composed route does not touch it at all - a scalar
     * operand becomes one of the program's own CONSTANTS, which is the
     * whole point of that design. Refusing a composed run for a
     * capability it does not use would have made a tile publishing the
     * sequencer and CAPS2[9] but not CAPS2[7] reject exactly the call
     * this parcel exists to serve.
     *
     * The gathered route still reaches this line, because run_gathered
     * re-enters run_impl with no tables and the dense device path then
     * really does set MODE[18:16] - so a build with -DCFT_NO_PROGRAM,
     * where nothing can compose, is refused here as it always was. Which
     * is the test of whether this is in the right place: it is reached
     * by exactly the runs that use the bit. */
    if (scalar_mask && dev->backend != CFT_BACKEND_REMOTE &&
        !(dev->seq.features & CFT_SEQ_FEAT_SCALAR)) {
        cft_set_error(
            "a scalar operand needs CFT_SEQ_FEAT_SCALAR, which this device "
            "does not publish (CAPS2[7]); ask cft_get_caps before issuing "
            "one, or pass the value as an array of copies - which is what "
            "this run would otherwise have read past the end of");
        return CFT_ERR_UNSUPPORTED;
    }

#ifdef CFT_ENABLE_XRT
    if (dev->backend == CFT_BACKEND_XRT) {
        uint32_t fl = 0;
        cft_status st;
        cft_bindings bd;
        bind_clear(&bd);
        /* Inputs first: a buffer a previous run wrote and nobody has
         * read back is brought home before it is fed in, so the rule
         * in cft.h costs a caller who ignores it time and not bits.
         * `d` needs none of this - it is written, not read, and the
         * backend flushes a device copy it is about to repurpose. */
        /* A scalar operand's buffer is ONE element everywhere it is
         * measured: buf_sync_in brings home exactly what the caller
         * owns, and bind_role asks buf_find for an EXACT byte count, so
         * n * esz would fail to match a resident one-element buffer and
         * the run would quietly stage it instead - correct, slower, and
         * invisible because nothing fails. */
        /* a_bytes, not ab: `bb` shadowed the cft_bn temporaries this
         * function already declares, and -Wshadow said so - on the
         * LINUX box, because this whole block is behind
         * #ifdef CFT_ENABLE_XRT and XRT is off by default, so no build
         * on the Windows host compiles it at all. */
        const size_t a_bytes = (scalar_mask & 1u) ? esz : n * esz;
        const size_t b_bytes = (scalar_mask & 2u) ? esz : n * esz;
        const size_t c_bytes = (scalar_mask & 4u) ? esz : n * esz;

        buf_sync_in(dev, a, a_bytes);
        buf_sync_in(dev, b, b_bytes);
        buf_sync_in(dev, c, c_bytes);
        bind_role(dev, &bd, CFT_ROLE_A, a, a_bytes);
        bind_role(dev, &bd, CFT_ROLE_B, b, b_bytes);
        bind_role(dev, &bd, CFT_ROLE_C, c, c_bytes);
        bind_role(dev, &bd, CFT_ROLE_D, d, n * esz);
        backend_call();
        st = (cft_status)cftx_run(dev->hw, (int)op, (int)fmt,
                                             (int)rnd, a, b, c, d, n,
                                             scalar_mask,
                                             &bd, &fl, bus_out);
        if (st == CFT_OK)
            cft_flags_emit(dev, fl, flags_out);
        return st;
    }
#endif
    /* ==== the remote backend (docs/REMOTE.md) ========================
     * The same shape as the XRT dispatch above: the backend moves the
     * bytes and returns the run's flag word, and this file ORs it into
     * the status word through the one seam every backend uses. */
#ifndef CFT_NO_REMOTE
    if (dev->backend == CFT_BACKEND_REMOTE) {
        uint32_t fl = 0;
        cft_status st;
        /* A scalar operand is EXPANDED here rather than carried on the
         * wire. The RUN request chunks - k elements a frame - so element
         * 0 would have to ride every chunk, and docs/REMOTE.md would grow
         * a field for a saving a socket does not have: the whole array
         * crosses either way. Expanding keeps the protocol exactly as it
         * is and the answer exactly what the contract says, which are the
         * two things that have to be true.
         *
         * Not a fallback to be ashamed of: the SAVING was never portable,
         * only the CALL is. Which is also why this route takes the
         * operand whatever the handle's CFT_SEQ_FEAT_SCALAR says - that
         * word is the server device's, from HELLO, and nothing here asks
         * the server's device to read a scalar operand at all. */
        void *exp[3] = {NULL, NULL, NULL};
        const void *opnd[3] = {a, b, c};
        if (scalar_mask) {
            int r;
            for (r = 0; r < 3; r++) {
                size_t k;
                if (!((scalar_mask >> r) & 1u) || !opnd[r])
                    continue;
                exp[r] = malloc(n * esz);
                if (!exp[r]) {
                    while (r-- > 0) free(exp[r]);
                    return CFT_ERR_OUT_OF_MEMORY;
                }
                for (k = 0; k < n; k++)
                    memcpy((uint8_t *)exp[r] + k * esz, opnd[r], esz);
                opnd[r] = exp[r];
            }
        }
        backend_call();
        st = (cft_status)cftr_run(dev->hw, (int)op, (int)fmt,
                                             (int)rnd, opnd[0], opnd[1],
                                             opnd[2], d, n,
                                             &fl, bus_out);
        free(exp[2]); free(exp[1]); free(exp[0]);
        if (st == CFT_OK)
            cft_flags_emit(dev, fl, flags_out);
        return st;
    }
#endif
    /* ==== end of the remote block =================================== */

    pa = (const uint8_t *)a;
    pb = (const uint8_t *)b;
    pc = (const uint8_t *)c;
    pd = (uint8_t *)d;

    cft_bn_zero(&ba);
    cft_bn_zero(&bb);
    cft_bn_zero(&bc);

    /* A scalar operand is element 0 for every element, which on this
     * backend is an index and nothing more - so the software answer is
     * the contract's by construction rather than by testing: it is the
     * same op() on the same values a caller would have got from an array
     * of copies. */
    {
        const size_t sa = (scalar_mask & 1u) ? 0u : 1u;
        const size_t sb = (scalar_mask & 2u) ? 0u : 1u;
        const size_t sc = (scalar_mask & 4u) ? 0u : 1u;

    for (i = 0; i < n; i++) {
        uint32_t fl = 0;
        /* Load before storing, so d may alias a, b or c. */
        if (pa) cft_bn_load(&ba, pa + sa * i * esz, (int)esz);
        if (pb) cft_bn_load(&bb, pb + sb * i * esz, (int)esz);
        if (pc) cft_bn_load(&bc, pc + sc * i * esz, (int)esz);
        if (cft_sf_compute(f, (int)op, (int)rnd, &ba, &bb, &bc, &bo, &fl))
            return CFT_ERR_INTERNAL;
        acc |= fl;
        cft_bn_store(&bo, pd + i * esz, (int)esz);
    }
    }

    cft_flags_emit(dev, acc, flags_out);
    return CFT_OK;
}

/* ---- R16 route one: gather here, then the dense run ----------------
 *
 * One allocation per INDEXED operand and none for the others: a dense
 * operand is passed through as it stands, and so is a scalar one -
 * its stride of zero and a table are two answers to one question, and
 * cft_run_ex refuses an operand that carries both, so the two cases
 * cannot meet on one pointer.
 *
 * The recursion into run_impl with a NULL `tab` is deliberate and is
 * one level deep: the dense run over the gathered block is not LIKE
 * the answer, it IS the answer, so the honest way to write it is to
 * call the dense path rather than to copy it. */
static cft_status run_gathered(cft_device *dev, cft_op op, cft_format fmt,
                               cft_round rnd, const void *a, const void *b,
                               const void *c, void *d, size_t n,
                               uint32_t scalar_mask, const run_tables *tab,
                               size_t esz, uint32_t *flags_out,
                               uint32_t *bus_out)
{
    const void *opnd[3];
    uint8_t *tmp[3];
    cft_status st;
    int r;

    opnd[0] = a; opnd[1] = b; opnd[2] = c;
    tmp[0] = tmp[1] = tmp[2] = NULL;

    for (r = 0; r < 3; r++) {
        if (!tab->idx[r])
            continue;
        tmp[r] = (uint8_t *)malloc(n * esz);
        if (!tmp[r]) {
            while (r-- > 0)
                free(tmp[r]);
            return CFT_ERR_OUT_OF_MEMORY;
        }
        idx_gather(tmp[r], (const uint8_t *)opnd[r], tab->idx[r], n, esz);
        opnd[r] = tmp[r];
    }
    st = run_impl(dev, op, fmt, rnd, opnd[0], opnd[1], opnd[2], d, n,
                  scalar_mask, NULL, flags_out, bus_out);
    free(tmp[2]); free(tmp[1]); free(tmp[0]);
    return st;
}

/* ---- R16 route two: the composition, on a device -------------------
 *
 * An indexed elementwise run as a THREE-INSTRUCTION PROGRAM over the
 * mechanism P1 built, with no new RTL and no new register:
 *
 *     op r3, r0, r1, r2  ;  DEPOSIT r3  ;  HALT
 *
 * and `max_deposits` 1, so lane i deposits exactly once, its slot is
 * element i * 1 + 0, and the deposit window IS the dense `d` the
 * caller passed - nothing is unpacked afterwards.
 *
 * a, b and c map onto r0, r1 and r2 with NO remapping, because they
 * are the same three streams in the same order (docs/SEQUENCER.md R9)
 * and an elementwise opcode and an ALU opcode are the same byte. That
 * is what makes the bits the dense run's BY CONSTRUCTION rather than
 * by agreement: one pipeline, one rounding attribute, one opcode. The
 * gate beside this file checks it anyway.
 *
 * r3 is the destination because r0, r1 and r2 ARE the streams: writing
 * the result into one of them would overwrite an operand the same
 * instruction reads, and it would also name a stream in a field R10
 * reads (P1's op_reads follows the OPCODE now, so it would cost
 * nothing today - but a program that does not depend on the decode
 * being right is the one to write, which is P1's own advice to this
 * parcel). r3 is the first register that starts at +0 and names no
 * stream.
 *
 * A SCALAR operand becomes one of the image's own CONSTANTS. The
 * sequencer has no stride-0 stream, so the alternative was an
 * n-element expansion on the host - which is precisely the thing
 * CAPS2[7] exists to avoid, and it would turn a one-element buffer
 * into n * esz bytes across the bus in the call whose whole purpose is
 * to move fewer of them. A constant costs zero bytes a lane, rides in
 * the image beside the instruction that reads it, needs no bank
 * pointer and no CFT_SEQ_FEAT_BANK_PTR (the image carries its own),
 * and the four-bit operand field addresses it directly with the `k`
 * bit set - so at most three constants, indices 0, 1 and 2, well
 * inside the sixteen a field without `kx` can name. */
#ifndef CFT_NO_PROGRAM
static cft_status run_composed(cft_device *dev, cft_op op, cft_format fmt,
                               cft_round rnd, const void *a, const void *b,
                               const void *c, void *d, size_t n,
                               uint32_t scalar_mask, const run_tables *tab,
                               size_t esz, uint32_t *flags_out,
                               uint32_t *bus_out)
{
    /* Header, three constants at the widest format THIS BUILD carries,
     * three instructions - every term derived from the shape above and
     * from cft_config.h's own ceiling, so a profile that narrows
     * CFT_MAX_FORMAT narrows this with it and a format added above
     * fp256 grows it without anyone remembering to. (fp32 is 4 bytes
     * and each rung doubles, which is what the shift is.) */
    uint8_t img[32 + 3 * (4 << CFT_MAX_FORMAT) + 3 * 8];
    const void *opnd[3];
    const void *strm[3];
    const uint32_t *stab[3];
    size_t ssrc[3];
    uint32_t fld[3], kbit[3];
    uint64_t w[3];
    cft_seq_caps sc;
    cft_program *prog = NULL;
    cft_run_args A;
    size_t off = 32;
    unsigned n_consts = 0, need;
    int n_strm = 0;
    cft_status st;
    int r, i;

    strm[0] = strm[1] = strm[2] = NULL;
    stab[0] = stab[1] = stab[2] = NULL;
    ssrc[0] = ssrc[1] = ssrc[2] = 0;
    /* The image cannot outgrow its buffer - the array above is sized
     * from the same ceiling `esz` comes from - but the run that would
     * find out is one that wrote past a stack array, so it is checked
     * rather than argued. */
    if (32u + 3u * esz + 3u * 8u > sizeof img)
        return CFT_ERR_INTERNAL;

    /* The two capability refusals, BY NAME and in this order.
     *
     * The sequencer's capacities first. A tile that publishes none has
     * no sequencer at all, and on such a tile "compose the run as a
     * program" is not a slower route, it is not a route - so the
     * sentence a caller needs is that this image has no sequencer.
     * CAPS2[9] on a tile with no sequencer is a bit inside a word that
     * means nothing, and naming it would send the caller to check
     * something whose zero says nothing about what is missing.
     *
     * Then CAPS2[9], which is the refusal for the tile that HAS a
     * sequencer and lacks the gather - the one CFT_SEQ_FEAT_INDEXED
     * exists to make askable in advance. Neither refusal gathers, runs
     * or allocates anything; both come before the image is built. */
    cft_device_seq_caps(dev, &sc);
    if (sc.max_insns == 0) {
        cft_set_error(
            "cft_run_ex: an indexed operand is run on a device as a "
            "three-instruction sequencer program, and this device "
            "publishes no sequencer capacities at all (cft_caps.max_insns "
            "is zero) - ask cft_get_caps before passing a table, or "
            "gather on the host and call cft_run");
        return CFT_ERR_UNSUPPORTED;
    }
    if (!(dev->seq.features & CFT_SEQ_FEAT_INDEXED)) {
        cft_set_error(
            "cft_run_ex: an indexed operand needs CFT_SEQ_FEAT_INDEXED, "
            "which this device does not publish (CAPS2[9]); ask "
            "cft_get_caps before passing a table, or gather on the host "
            "and call cft_run");
        return CFT_ERR_UNSUPPORTED;
    }

    opnd[0] = a; opnd[1] = b; opnd[2] = c;
    need = cft_sf_op_operands((int)op);
    for (r = 0; r < 3; r++) {
        if (!((need >> r) & 1u)) {
            /* An operand this OPCODE does not read. It still has a
             * field in the instruction, and what goes in the field is
             * r4: a register at or above three, which R10 never turns
             * into a stream load whatever the decode does, and which
             * holds +0 because nothing has written it (R9). Naming r0,
             * r1 or r2 here would work today - P1's op_reads follows
             * the opcode - and would make this program's cost depend
             * on the decode being right, which is exactly the
             * dependency P1 told this parcel not to take. The dense
             * path ignores such an operand in the same way and for the
             * same reason. */
            fld[r]  = 4u;
            kbit[r] = 0u;
            continue;
        }
        if ((scalar_mask >> r) & 1u) {
            /* One element, into the image's own constant section, in
             * operand order - so the index is the count of scalars
             * before it and nothing has to be looked up later. */
            memcpy(img + off, opnd[r], esz);
            off += esz;
            fld[r]  = n_consts++;
            kbit[r] = 1u;
            continue;
        }
        /* A real stream, and it takes the NEXT free stream slot rather
         * than the one its own letter names.
         *
         * The three streams are three pointer registers that
         * initialise r0, r1 and r2, and which OPERAND a register
         * carries is the instruction's business - the ALU steers by
         * FIELD (ra, rb, rc), not by register number. So packing the
         * streams down keeps two promises at once. A program run
         * requires stream a to be non-NULL, and a scalar `a` beside an
         * indexed `b` would otherwise have to pass the caller's
         * ONE-ELEMENT buffer as an n-element stream - which is the
         * over-read CAPS2[7] exists to prevent, arriving through the
         * back door. And an operand the opcode does not read now
         * carries no stream pointer at all, so nothing is bound,
         * synced or staged for it.
         *
         * Stream a is always used: the composed route is only taken
         * when a table is present, a table's operand is non-NULL and
         * not scalar (the shape rules) and is read by the opcode
         * (refused above if not), so at least one operand reaches
         * here and the first to do so is slot 0. */
        strm[n_strm]  = opnd[r];
        stab[n_strm]  = tab->idx[r];
        ssrc[n_strm]  = tab->idx[r] ? tab->src[r] : 0u;
        fld[r]  = (uint32_t)n_strm;     /* r0, r1, r2 in turn */
        kbit[r] = 0u;
        n_strm++;
    }

    /* The instruction words. No `kx`, so every constant index is the
     * operand's own four-bit field; no fifth register bit and no ninth
     * constant bit, so imm is zero throughout - which is what makes
     * this encoding legal on a device that publishes neither
     * CFT_SEQ_FEAT_REGS32 nor CFT_SEQ_FEAT_KX9. */
    w[0] = (uint64_t)(uint32_t)op
         | ((uint64_t)3u << 8)                          /* rd = r3 */
         | ((uint64_t)fld[0] << 12)
         | ((uint64_t)fld[1] << 16)
         | ((uint64_t)fld[2] << 20)
         | ((uint64_t)((uint32_t)rnd & 7u) << 24)
         | ((uint64_t)kbit[0] << 27)
         | ((uint64_t)kbit[1] << 28)
         | ((uint64_t)kbit[2] << 29);
    w[1] = (uint64_t)3u                                 /* DEPOSIT */
         | ((uint64_t)3u << 12)                         /* of r3 */
         | ((uint64_t)1u << 31);                        /* control */
    w[2] = (uint64_t)1u << 31;                          /* HALT */

    put_le32_img(img +  0, 0x50544643u);                /* "CFTP" */
    put_le32_img(img +  4, 1u);                         /* image version */
    put_le32_img(img +  8, 3u);                         /* n_insns */
    put_le32_img(img + 12, n_consts);
    put_le32_img(img + 16, 1u);                         /* max_deposits */
    put_le32_img(img + 20, (uint32_t)fmt);
    put_le32_img(img + 24, 0u);                         /* header flags */
    put_le32_img(img + 28, 0u);                         /* scratch_io */
    for (i = 0; i < 3; i++) {
        int byte;
        for (byte = 0; byte < 8; byte++)
            img[off + (size_t)byte] = (uint8_t)(w[i] >> (8 * byte));
        off += 8;
    }

    /* Loaded rather than hand-dispatched, so the composed run is a
     * PROGRAM RUN in every sense the rest of the library means it: the
     * device's own capacity and format refusals, the image bytes the
     * tile executes, and the one dispatcher in cft_backend_program_run
     * that P1's tables already ride. The seam test the lead runs after
     * this parcel compares this route against cft_program_run_ex with
     * the same tables, and it is comparing two paths through the same
     * executor by construction. */
    st = cft_program_load(dev, img, off, &prog);
    if (st != CFT_OK)
        return st;

    memset(&A, 0, sizeof A);
    A.struct_size = sizeof A;
    A.a = strm[0]; A.b = strm[1]; A.c = strm[2];
    A.n = n;
    A.deposits  = d;            /* n * max_deposits(1) elements: dense */
    A.counts    = NULL;
    A.flags_out = flags_out;
    A.bus_out   = bus_out;
    A.idx_a     = stab[0];
    A.idx_b     = stab[1];
    A.idx_c     = stab[2];
    A.idx_a_src = ssrc[0];
    A.idx_b_src = ssrc[1];
    A.idx_c_src = ssrc[2];
    st = cft_program_run_ex(prog, &A);
    cft_program_free(prog);
    return st;
}

#endif  /* CFT_NO_PROGRAM */

CFT_API cft_status cft_run(cft_device *dev,
                           cft_op      op,
                           cft_format  fmt,
                           cft_round   rnd,
                           const void *a,
                           const void *b,
                           const void *c,
                           void       *d,
                           size_t      n,
                           uint32_t   *flags_out,
                           uint32_t   *bus_out)
{
    return run_impl(dev, op, fmt, rnd, a, b, c, d, n, 0u, NULL,
                    flags_out, bus_out);
}

CFT_API cft_status cft_run_ex(cft_device *dev,
                              cft_op      op,
                              cft_format  fmt,
                              cft_round   rnd,
                              const cft_elem_args *args)
{
    if (!dev || !args)
        return CFT_ERR_INVALID_ARGUMENT;
    /* An INPUT struct, so an unrecognised size is REFUSED rather than
     * truncated - the same reversal cft_run_args documents. A newer
     * caller's scalar_mask silently ignored is exactly the run that
     * would return an array's worth of the wrong answer. */
    if (args->struct_size != sizeof(cft_elem_args))
        return CFT_ERR_INVALID_ARGUMENT;
    /* Bits above the three operands are reserved, and refused rather
     * than masked off: a caller setting bit 3 means something this
     * library does not implement. */
    if (args->scalar_mask & ~7u)
        return CFT_ERR_INVALID_ARGUMENT;
    /* An operand that is not supplied cannot be scalar. Caught here
     * because a NULL pointer with its bit set would otherwise read
     * element 0 of nothing. */
    if (((args->scalar_mask & 1u) && !args->a) ||
        ((args->scalar_mask & 2u) && !args->b) ||
        ((args->scalar_mask & 4u) && !args->c))
        return CFT_ERR_INVALID_ARGUMENT;
    /* ABI 0.14's index tables (docs/ROUND2.md, P2). The SHAPE rules are
     * the seam's and final: a table on an operand that is NULL, or that
     * is also scalar, or with a source length of zero, and a source
     * length beside no table, are each an argument error. Then three
     * more rules this parcel adds, and then the run.
     *
     * ARGUMENT ERRORS COME FIRST AND CAPABILITY REFUSALS AFTER, which
     * is the order cft_program_run_ex already has (seq_check_round2
     * runs before cft_backend_program_run's CAPS2[9] refusal) and is
     * therefore the order the composed run has to have: the same
     * mistake must be told in the same words by both calls, or a
     * caller who moves from one to the other is debugging the library
     * instead of their program. It also means the bound is checked on
     * EVERY backend, which is what the contract says - a device must
     * never read past a buffer for a caller, and a check the feature
     * bit could skip would not be that. */
    {
        const uint32_t *idx[3];
        size_t src[3];
        const void *opnd[3];
        int r;
        idx[0] = args->idx_a; idx[1] = args->idx_b; idx[2] = args->idx_c;
        src[0] = args->idx_a_src; src[1] = args->idx_b_src;
        src[2] = args->idx_c_src;
        opnd[0] = args->a; opnd[1] = args->b; opnd[2] = args->c;
        for (r = 0; r < 3; r++) {
            if (!idx[r]) {
                if (src[r]) {
                    cft_set_error("cft_run_ex: idx_%c_src = %lu names a "
                                  "source length for operand %c, which has "
                                  "no index table", 'a' + r,
                                  (unsigned long)src[r], 'a' + r);
                    return CFT_ERR_INVALID_ARGUMENT;
                }
                continue;
            }
            if (!opnd[r]) {
                cft_set_error("cft_run_ex: idx_%c indexes operand %c, "
                              "which is NULL", 'a' + r, 'a' + r);
                return CFT_ERR_INVALID_ARGUMENT;
            }
            if (args->scalar_mask & (1u << r)) {
                cft_set_error("cft_run_ex: operand %c is both scalar "
                              "(scalar_mask bit %d) and indexed (idx_%c); "
                              "a stride of zero and a table are two answers "
                              "to one question", 'a' + r, r, 'a' + r);
                return CFT_ERR_INVALID_ARGUMENT;
            }
            if (src[r] == 0) {
                cft_set_error("cft_run_ex: idx_%c is set and idx_%c_src is "
                              "zero, so no index could be in range - the "
                              "source's length in elements is what bounds "
                              "the table", 'a' + r, 'a' + r);
                return CFT_ERR_INVALID_ARGUMENT;
            }
        }
        /* A table on an operand THIS OPCODE DOES NOT READ is refused by
         * name, and is not quietly ignored the way the dense path
         * ignores the operand itself.
         *
         * The two look alike and are not. Ignoring a pointer costs
         * nothing and reads nothing - cft.h has said "unused operands
         * (b for ADD, c for MUL) may be NULL" since the beginning, and
         * a caller who passes one anyway has simply passed a pointer.
         * A TABLE is a buffer the caller built at a cost, for a fetch
         * they are asking this call to make; running and returning
         * success would tell them the gather happened. It also would
         * not mean one thing on three backends - the gather here, a
         * MODE bit and a bound table there - so "ignore" would be
         * three behaviours wearing one word.
         *
         * An UNASSIGNED opcode reads nothing at all
         * (cft_sf_op_operands is zero for one), so every table on one
         * is refused here, which is the same rule and not a special
         * case: the result is the canonical quiet NaN whatever any
         * operand holds.
         *
         * Skipped for an opcode run_impl is about to refuse anyway - a
         * reduction, or a byte outside 0..255 - so that the refusal a
         * caller gets names the call they got wrong rather than a
         * table they merely also passed. */
        if ((int)op >= 0 && (int)op <= 255 && !cft_sf_is_reduction((int)op)) {
            unsigned need = cft_sf_op_operands((int)op);
            for (r = 0; r < 3; r++) {
                if (idx[r] && !((need >> r) & 1u)) {
                    cft_set_error(
                        "cft_run_ex: idx_%c gathers operand %c and opcode "
                        "%d (%s) does not read it, so the table would be "
                        "built and never used; drop idx_%c, or pass the "
                        "opcode whose operand %c is",
                        'a' + r, 'a' + r, (int)op, cft_op_name(op),
                        'a' + r, 'a' + r);
                    return CFT_ERR_INVALID_ARGUMENT;
                }
            }
        }
    }
    /* The two rules that READ a table's entries, or do arithmetic on
     * `n`, are NOT here. They are in run_impl, behind every check the
     * dense path makes before it touches memory - see the block there.
     * Everything above this line reads a pointer's value and nothing
     * it points at, which is what lets it run first. */
    {
        run_tables tab;
        tab.idx[0] = args->idx_a; tab.idx[1] = args->idx_b;
        tab.idx[2] = args->idx_c;
        tab.src[0] = args->idx_a_src; tab.src[1] = args->idx_b_src;
        tab.src[2] = args->idx_c_src;
        return run_impl(dev, op, fmt, rnd, args->a, args->b, args->c,
                        args->d, args->n, args->scalar_mask, &tab,
                        args->flags_out, args->bus_out);
    }
}

/* ---------------------------------------------------------------
 * Reductions
 * --------------------------------------------------------------- */

/* 754-2019 9.4 orders the special values differently for sumSquare and
 * sumAbs than for sum and dot:
 *
 *   "For sumSquare and sumAbs, if any operand element is an infinity,
 *    +inf is returned. Otherwise, if any operand element is a NaN a
 *    quiet NaN is returned."
 *
 * where sum and dot put NaN first. The tree cannot produce that - a
 * NaN reaching an add propagates - so this overrides it, and ONLY on
 * the one input where the two differ.
 *
 * Checked lazily, after the tree, because the check is equivalent to
 * the model's pre-pass and much cheaper: every term of either
 * operation is a square or a magnitude, so no term is negative, no
 * inf - inf and no 0 x inf can arise, and therefore the tree's result
 * is a NaN if and only if some ELEMENT was a NaN. The scan for an
 * infinity then only happens on a vector that produced one, instead of
 * on every call - which matters on a device backend, where it is the
 * host reading the whole input array.
 *
 * The flags are 9.4's blanket signalling-NaN rule and nothing else:
 * the result is decided by a table rather than computed, and 9.4 says
 * "exceptions are not signaled for each exceptional intermediate
 * operand or result".
 *
 * Returns 1 when it applied. */
static int sumsq_abs_inf_override(const cft_fmt_desc *f, const void *a,
                                  size_t esz, size_t n,
                                  cft_bn *out, uint32_t *flags)
{
    size_t i;
    int saw_inf = 0, saw_snan = 0;
    cft_bn v, frac;

    for (i = 0; i < n; i++) {
        cft_bn_load(&v, (const uint8_t *)a + i * esz, (int)esz);
        if (cft_bn_extract(&v, f->man_w, f->exp_w) != f->exp_mask)
            continue;
        cft_bn_copy(&frac, &v);
        cft_bn_mask(&frac, f->man_w);
        if (cft_bn_is_zero(&frac))
            saw_inf = 1;
        else if (!cft_bn_bit(&v, f->man_w - 1))
            saw_snan = 1;
    }
    if (!saw_inf)
        return 0;
    cft_sf_inf(f, 0, out);
    *flags = saw_snan ? CFT_FLAG_INVALID : 0u;
    return 1;
}

/* Is the reduction's result a NaN? The trigger for the scan above. */
static int result_is_nan(const cft_fmt_desc *f, const void *d)
{
    cft_bn v, frac;
    cft_bn_load(&v, (const uint8_t *)d, f->width / 8);
    if (cft_bn_extract(&v, f->man_w, f->exp_w) != f->exp_mask)
        return 0;
    cft_bn_copy(&frac, &v);
    cft_bn_mask(&frac, f->man_w);
    return !cft_bn_is_zero(&frac);
}

CFT_API cft_status cft_reduce(cft_device *dev,
                              cft_op      op,
                              cft_format  fmt,
                              cft_round   rnd,
                              const void *a,
                              const void *b,
                              void       *d,
                              size_t      n,
                              uint32_t   *flags_out,
                              uint32_t   *bus_out)
{
    const cft_fmt_desc *f;
    size_t esz;
    unsigned need;
    uint32_t fl = 0;
    cft_bn bo;

    if (bus_out)
        *bus_out = 0;
    if (!dev)
        return CFT_ERR_INVALID_ARGUMENT;
    if (CFT_FMT_ABSENT(fmt))
        return (cft_status)cft_absent_format_refusal((int)fmt);
    if (CFT_FMT_OUT_OF_RANGE(fmt))
        return CFT_ERR_INVALID_ARGUMENT;
    if ((int)rnd < 0 || (int)rnd > 4)
        return CFT_ERR_INVALID_ARGUMENT;
    /* The mirror of cft_run's refusal: this entry point is for
     * reductions, and handing it an elementwise opcode would otherwise
     * quietly compute something nobody asked for. */
    if (!cft_sf_is_reduction((int)op))
        return CFT_ERR_INVALID_ARGUMENT;
    if (!(dev->format_mask & (1u << (int)fmt)))
        return (cft_status)cft_device_format_refusal(dev->format_mask,
                                                     (int)fmt, "cft_reduce");
    {
        int group = op_group_bit((int)op);
        if (group < 0 || !(dev->op_groups & (1u << group)))
            return (cft_status)cft_op_group_refusal((int)op, "cft_reduce");
        /* A composed reduction also needs the group its composition
         * runs through - the multiply for sumSquare, the abs for
         * sumAbs - and a device missing one must say so here rather
         * than fail partway through the sequence. */
        group = reduce_helper_group((int)op);
        if (group >= 0 && !(dev->op_groups & (1u << group))) {
            cft_set_error("cft_reduce: %s is composed, and its %s step "
                          "needs CAPS group %d (%s, CAPS[%d]), which this "
                          "device does not implement - cft_supports says "
                          "so before a run",
                          cft_op_name(op), group_names[group], group,
                          group_names[group], 8 + group);
            return CFT_ERR_UNSUPPORTED;
        }
    }
    if (!d)
        return CFT_ERR_INVALID_ARGUMENT;

    f   = &cft_sf_formats[(int)fmt];
    esz = (size_t)f->width / 8;

    /* n == 0 raises nothing and is the op's IDENTITY - the only result
     * here that is not a function of any input. It is handled before the
     * operand check because a reduction of nothing needs nothing to
     * reduce.
     *
     * +0 for the four sum reductions, the additive identity. -infinity
     * for maxall, the value that loses to every other: 754 says nothing
     * about an empty reduction, so this is chosen, and chosen so that
     * folding an empty range into a non-empty one is a no-op. A +0 here
     * would WIN against every negative element, which is the failure
     * this branch exists to prevent. */
    if (n == 0) {
        cft_bn z;
        if (op == CFT_MAXALL)
            cft_sf_inf(f, 1, &z);
        else
            cft_bn_zero(&z);
        cft_bn_store(&z, (uint8_t *)d, (int)esz);
        cft_flags_emit(dev, 0, flags_out);
        return CFT_OK;
    }

    need = cft_sf_op_operands((int)op);
    if (((need & 1u) && !a) || ((need & 2u) && !b))
        return CFT_ERR_INVALID_ARGUMENT;
    if (n > ((size_t)-1) / esz)
        return CFT_ERR_INVALID_ARGUMENT;

    /* Before ANY path below, because two of them read the caller's
     * array on the host: the composed sumSquare and sumAbs walk it
     * for 9.4's infinity override, and the software backend reads all
     * of it. A buffer whose last writer was a run has a stale mirror
     * until this brings it home. */
    buf_sync_in(dev, a, n * esz);
    buf_sync_in(dev, b, n * esz);

    /* sumSquare and sumAbs are COMPOSITIONS of what is already here,
     * and are implemented as such rather than as a second tree walker.
     * 754-2019 9.4 defines them as sums of squares and of magnitudes;
     * this contract adds the part 9.4 leaves open - which tree - by
     * making it the same tree, node for node:
     *
     *     sumSquare(a) == cft_reduce(CFT_DOT, a, a)
     *     sumAbs(a)    == cft_run(CFT_ABS, a) then CFT_SUM
     *
     * Issuing exactly those calls is what makes the two backends
     * agree: there is no separate code path to keep in step, and on a
     * device the dot and the sum run on the tile like any other
     * reduction. The cost is one scratch buffer for sumAbs, which is
     * the same trade CFT_DOT already makes for its multiply pass.
     *
     * Recursion is one level deep and cannot be more: the calls below
     * name CFT_DOT and CFT_SUM, which take the tree path directly. */
    /* maxall: halving with the elementwise maximum.
     *
     * The fifth composed reduction, and the first whose composition is
     * not one pass plus the sum tree. A tile publishing CAPS2[8] streams
     * a maximum in one pass (the XRT block below, ABI 0.13), and no
     * other handle needs to for the bits - but unlike sumSquare and
     * sumAbs, opcode 31 must NEVER be handed as a reduction to a tile
     * WITHOUT that bit: its `cfg_is_reduce` is `(cfg_op == 8'd24)`, so
     * it would decode 31 as elementwise and write n elements where a
     * reduction's caller sized `d` for one (rtl/cft_engine_stream.sv
     * has added 8'd31 since the RTL that publishes CAPS2[8]). That is
     * memory corruption, not a wrong answer, and it is why this block
     * sits above the device dispatch rather than beside it.
     *
     * Halving is allowed to BE the shape because 754-2019 maximum is
     * exactly associative and commutative, flags included: any NaN gives
     * a canonical quiet NaN rather than a propagated payload, invalid is
     * raised exactly when some operand is signalling and every element is
     * an operand of one comparison whatever the shape, and max(+0, -0) is
     * +0 which is also the maximum among zeros. So these bits are the
     * software tree's bits, and the hardware maxall added behind CAPS2[8]
     * at 0.13 returns them too (the XRT block below) - which is what
     * makes this a complete answer rather than a staging post.
     *
     * ceil(log2 n) device passes against the ~2n width-one calls the
     * first caller issues today (cft-rebound/docs/HARDWARE.md).
     */
    if (op == CFT_MAXALL) {
        uint32_t cf = 0;
        cft_status st = CFT_OK;
        const int muted = cft_flags_mute(dev, 1);
        uint8_t *buf[2] = {NULL, NULL};
        const void *src = a;
        size_t m = n, which = 0;

#ifdef CFT_ENABLE_XRT
        /* The tile streams it where CAPS2[8] says so (ABI 0.13): one
         * run, the accumulator folding with the elementwise maximum,
         * against ceil(log2 n) halvings. The bits are the halving's,
         * because 754 maximum is exactly associative and commutative,
         * flags included - the block above the opcode has the whole
         * argument, and tb/test_krnl_reduce.py holds the tile to the
         * left fold python/cft_golden/reduce.py defines. A tile without
         * the bit decodes 31 as ELEMENTWISE and must never see it.
         *
         * The backend test is not redundant with the bit: the software
         * backend publishes CAPS2[8] too (2026-09-24, for cft_reduce_seg,
         * which it computes) and has no tile to stream on, so it halves
         * below like every handle that is not a tile with the bit. So
         * does a remote handle, whatever its server publishes: its
         * halving passes are cft_run calls, and so RUN frames. */
        if (dev->backend == CFT_BACKEND_XRT &&
            (dev->seq.features & CFT_FEAT_REDUCE_SEG)) {
            cft_bindings bd;
            uint32_t tf = 0;
            (void)cft_flags_mute(dev, muted);
            bind_clear(&bd);
            bind_role(dev, &bd, CFT_ROLE_A, a, n * esz);
            backend_call();
            st = (cft_status)cftx_reduce_seg(dev->hw, (int)op, (int)fmt,
                                             (int)rnd, a, n, n, d, &bd,
                                             &tf, bus_out);
            if (st == CFT_OK)
                cft_flags_emit(dev, tf, flags_out);
            return st;
        }
#endif

        /* n == 0 never arrives: the identity is handled at the one
         * n == 0 site above, beside every other reduction's. */
        if (n > 1) {
            /* ceil(n/2) + 1 covers every pass: the odd element is
             * carried rather than dropped. */
            size_t cap = (n / 2 + 2) * esz;
            buf[0] = (uint8_t *)malloc(cap);
            buf[1] = (uint8_t *)malloc(cap);
            if (!buf[0] || !buf[1]) {
                free(buf[1]); free(buf[0]);
                (void)cft_flags_mute(dev, muted);
                return CFT_ERR_OUT_OF_MEMORY;
            }
        }
        while (m > 1 && st == CFT_OK) {
            const size_t h   = m / 2;          /* pairs this pass */
            const int    odd = (m & 1u) != 0;  /* one element carried */
            uint8_t     *dst = buf[which];
            uint32_t     pf  = 0;

            st = cft_run(dev, CFT_MAX, fmt, rnd,
                         src, (const uint8_t *)src + h * esz, NULL,
                         dst, h, &pf, bus_out);
            cf |= pf;
            if (st != CFT_OK)
                break;
            if (odd)
                memcpy(dst + h * esz,
                       (const uint8_t *)src + 2 * h * esz, esz);
            src   = dst;
            m     = h + (size_t)odd;
            which ^= 1u;
        }
        (void)cft_flags_mute(dev, muted);
        if (st == CFT_OK)
            memcpy(d, src, esz);
        free(buf[1]);
        free(buf[0]);
        if (st != CFT_OK)
            return st;
        cft_flags_emit(dev, cf, flags_out);
        return CFT_OK;
    }

    if (op == CFT_SUMSQ || op == CFT_SUMABS) {
        uint32_t cf = 0;
        cft_status st;
        /* The composition's own calls are internal passes, so they do
         * not reach the status word: the emit at the end of this block
         * does, and it is the one that carries 9.4's infinity override
         * when that fires. Muting is what keeps a sumAbs over a vector
         * holding both an infinity and a signalling NaN from leaving
         * the tree's flags standing beside the override's. */
        const int muted = cft_flags_mute(dev, 1);

        if (op == CFT_SUMSQ) {
            st = cft_reduce(dev, CFT_DOT, fmt, rnd, a, a, d, n, &cf,
                            bus_out);
        } else {
            void *tmp = malloc(n * esz);
            uint32_t af = 0;
            if (!tmp)
                return CFT_ERR_OUT_OF_MEMORY;
            st = cft_run(dev, CFT_ABS, fmt, rnd, a, NULL, NULL, tmp, n,
                         &af, bus_out);
            if (st == CFT_OK)
                st = cft_reduce(dev, CFT_SUM, fmt, rnd, tmp, NULL, d, n,
                                &cf, bus_out);
            free(tmp);
            cf |= af;          /* abs signals nothing (5.5.1); OR anyway */
        }
        (void)cft_flags_mute(dev, muted);
        if (st != CFT_OK)
            return st;

        if (result_is_nan(f, d)) {
            cft_bn ov;
            uint32_t of = 0;
            if (sumsq_abs_inf_override(f, a, esz, n, &ov, &of)) {
                cft_bn_store(&ov, (uint8_t *)d, (int)esz);
                cf = of;
            }
        }
        cft_flags_emit(dev, cf, flags_out);
        return CFT_OK;
    }

#ifdef CFT_ENABLE_XRT
    if (dev->backend == CFT_BACKEND_XRT) {
        /* CFT_DOT is not device hardware, and does not need to be: the
         * contract makes dot(a,b) == sum(mul(a,b)) exact, flags
         * included. So an elementwise MUL on the device, then a SUM on
         * the device, and the bits are the contract's. The scratch
         * buffer is the only cost. */
        if (op == CFT_DOT) {
            void *tmp = malloc(n * esz);
            uint32_t mf = 0, sf = 0;
            cft_status st;
            int muted;
            if (!tmp)
                return CFT_ERR_OUT_OF_MEMORY;
            muted = cft_flags_mute(dev, 1);   /* internal passes */
            st = cft_run(dev, CFT_MUL, fmt, rnd, a, b, NULL, tmp, n,
                         &mf, bus_out);
            if (st == CFT_OK)
                st = cft_reduce(dev, CFT_SUM, fmt, rnd, tmp, NULL, d, n,
                                &sf, bus_out);
            free(tmp);
            (void)cft_flags_mute(dev, muted);
            if (st == CFT_OK)
                cft_flags_emit(dev, mf | sf, flags_out);
            return st;
        }

        /* A reduction cannot be split evenly the way an elementwise run
         * can: a partial is only reusable if its range is a NODE of the
         * tree. Cut the top levels to get nodes, run one per tile, and
         * fold the partials here with the same tree - which reproduces
         * the levels that were cut.
         *
         * Only a power-of-two part count corresponds to a clean cut, so
         * a device with a non-power-of-two tile count uses the largest
         * power of two of them. Fewer tiles, never a wrong answer. */
        {
            size_t lo[CFT_MAX_REDUCE_PARTS], hi[CFT_MAX_REDUCE_PARTS];
            size_t parts = 1, nr;
            uint8_t *partials;
            cft_status st;

            while (parts * 2 <= dev->tiles && parts * 2 <= CFT_MAX_REDUCE_PARTS)
                parts *= 2;

            nr = cft_sf_canonical_ranges(n, parts, lo, hi,
                                         CFT_MAX_REDUCE_PARTS);
            if (nr == 0)
                return CFT_ERR_INTERNAL;

            partials = (uint8_t *)malloc(nr * esz);
            if (!partials)
                return CFT_ERR_OUT_OF_MEMORY;

            /* One operand and one role: a reduction reads `a` and
             * writes one element per range into `partials`, which is
             * this file's own allocation and never resident. */
            {
                cft_bindings bd;
                bind_clear(&bd);
                bind_role(dev, &bd, CFT_ROLE_A, a, n * esz);
                backend_call();
                st = (cft_status)cftx_reduce(dev->hw, (int)op, (int)fmt,
                                             (int)rnd, a, lo, hi, nr,
                                             partials, &bd, &fl, bus_out);
            }
            if (st != CFT_OK) {
                free(partials);
                return st;
            }

            /* Fold the partials with the same tree. nr is small - one
             * per tile - so this is a handful of adds, and it has to
             * happen here rather than on a tile because no tile has all
             * the partials. */
            {
                uint32_t cf = 0;
                int bad = cft_sf_reduce(f, CFT_SF_SUM, (int)rnd, partials,
                                        NULL, esz, 0, nr, &bo, &cf);
                free(partials);
                if (bad)
                    return CFT_ERR_INTERNAL;
                fl |= cf;
            }
            cft_bn_store(&bo, (uint8_t *)d, (int)esz);
            cft_flags_emit(dev, fl, flags_out);
            return CFT_OK;
        }
    }
#endif
    /* ==== the remote backend (docs/REMOTE.md) ========================
     * The whole vector crosses in one frame and the server's own
     * cft_reduce walks the tree - on its software backend directly, on
     * a tile through its own partitioning - so CFT_DOT needs no MUL
     * pass here: the server's library composes it, bit for bit the
     * same. The composed CFT_SUMSQ and CFT_SUMABS were already taken
     * apart above and arrive here as a DOT or an ABS pass and a SUM. */
#ifndef CFT_NO_REMOTE
    if (dev->backend == CFT_BACKEND_REMOTE) {
        cft_status st;
        backend_call();
        st = (cft_status)cftr_reduce(dev->hw, (int)op, (int)fmt,
                                                (int)rnd, a, b, d, n,
                                                &fl, bus_out);
        if (st == CFT_OK)
            cft_flags_emit(dev, fl, flags_out);
        return st;
    }
#endif
    /* ==== end of the remote block =================================== */

    if (cft_sf_reduce(f, (int)op, (int)rnd, a, b, esz, 0, n, &bo, &fl))
        return CFT_ERR_INTERNAL;
    cft_bn_store(&bo, (uint8_t *)d, (int)esz);
    cft_flags_emit(dev, fl, flags_out);
    return CFT_OK;
}

/* The segmented form: d[s] = cft_reduce(op, a + s*seg, b + s*seg, seg).
 *
 * The software backend is that line, call by call, because it is the
 * definition and there is nothing to add: the composed opcodes, 9.4's
 * infinity rule and maxall's halving all happen inside cft_reduce per
 * slice, and the flags OR up as they do across one call's tree. The
 * device backends are where the entry point earns its existence - one
 * run or one frame for the whole array - and where a device that cannot
 * do that is told so by name rather than handed a loop. */
CFT_API cft_status cft_reduce_seg(cft_device *dev,
                                  cft_op      op,
                                  cft_format  fmt,
                                  cft_round   rnd,
                                  const void *a,
                                  const void *b,
                                  void       *d,
                                  size_t      n,
                                  size_t      seg,
                                  uint32_t   *flags_out,
                                  uint32_t   *bus_out)
{
    const cft_fmt_desc *f;
    size_t esz, nres;
    unsigned need;
    uint32_t fl = 0;

    if (bus_out)
        *bus_out = 0;
    if (!dev)
        return CFT_ERR_INVALID_ARGUMENT;
    if (CFT_FMT_ABSENT(fmt))
        return (cft_status)cft_absent_format_refusal((int)fmt);
    if (CFT_FMT_OUT_OF_RANGE(fmt))
        return CFT_ERR_INVALID_ARGUMENT;
    if ((int)rnd < 0 || (int)rnd > 4)
        return CFT_ERR_INVALID_ARGUMENT;
    if (!cft_sf_is_reduction((int)op))
        return CFT_ERR_INVALID_ARGUMENT;
    if (!(dev->format_mask & (1u << (int)fmt)))
        return (cft_status)cft_device_format_refusal(dev->format_mask,
                                                     (int)fmt,
                                                     "cft_reduce_seg");
    {
        int group = op_group_bit((int)op);
        if (group < 0 || !(dev->op_groups & (1u << group)))
            return (cft_status)cft_op_group_refusal((int)op,
                                                    "cft_reduce_seg");
        group = reduce_helper_group((int)op);
        if (group >= 0 && !(dev->op_groups & (1u << group))) {
            cft_set_error("cft_reduce_seg: %s is composed, and its %s step "
                          "needs CAPS group %d (%s, CAPS[%d]), which this "
                          "device does not implement",
                          cft_op_name(op), group_names[group], group,
                          group_names[group], 8 + group);
            return CFT_ERR_UNSUPPORTED;
        }
    }
    if (!d)
        return CFT_ERR_INVALID_ARGUMENT;
    if (seg == 0) {
        cft_set_error("cft_reduce_seg: a segment is at least one element");
        return CFT_ERR_INVALID_ARGUMENT;
    }
    if (n % seg) {
        cft_set_error("cft_reduce_seg: n = %lu is not a whole number of "
                      "segments of %lu - the last %lu elements would "
                      "belong to no result",
                      (unsigned long)n, (unsigned long)seg,
                      (unsigned long)(n % seg));
        return CFT_ERR_INVALID_ARGUMENT;
    }
    f    = &cft_sf_formats[(int)fmt];
    esz  = (size_t)f->width / 8;
    nres = n / seg;
    if (n == 0) {
        cft_flags_emit(dev, 0, flags_out);
        return CFT_OK;
    }
    need = cft_sf_op_operands((int)op);
    if (((need & 1u) && !a) || ((need & 2u) && !b))
        return CFT_ERR_INVALID_ARGUMENT;
    if (n > ((size_t)-1) / esz)
        return CFT_ERR_INVALID_ARGUMENT;
    if (seg == n)
        return cft_reduce(dev, op, fmt, rnd, a, b, d, n, flags_out, bus_out);

    buf_sync_in(dev, a, n * esz);
    buf_sync_in(dev, b, n * esz);

#ifdef CFT_ENABLE_XRT
    if (dev->backend == CFT_BACKEND_XRT) {
        cft_status st;
        if (!(dev->seq.features & CFT_FEAT_REDUCE_SEG)) {
            cft_set_error("cft_reduce_seg: this device does not publish "
                          "CFT_FEAT_REDUCE_SEG (CAPS2[8]) - its tile has no "
                          "SEG register and would return one result where "
                          "%lu are due. Not looped over %lu calls for you: "
                          "that is %lu round trips, and a caller who wants "
                          "them can write them",
                          (unsigned long)nres, (unsigned long)nres,
                          (unsigned long)nres);
            return CFT_ERR_UNSUPPORTED;
        }
        /* The compositions, taken apart exactly as cft_reduce takes
         * them apart, then the segmented tree on the tile. */
        if (op == CFT_DOT || op == CFT_SUMSQ || op == CFT_SUMABS) {
            void *tmp = malloc(n * esz);
            uint32_t pf = 0, sf = 0;
            const int muted = cft_flags_mute(dev, 1);
            if (!tmp) {
                (void)cft_flags_mute(dev, muted);
                return CFT_ERR_OUT_OF_MEMORY;
            }
            if (op == CFT_SUMABS)
                st = cft_run(dev, CFT_ABS, fmt, rnd, a, NULL, NULL, tmp, n,
                             &pf, bus_out);
            else
                st = cft_run(dev, CFT_MUL, fmt, rnd, a,
                             op == CFT_DOT ? b : a, NULL, tmp, n, &pf,
                             bus_out);
            if (st == CFT_OK)
                st = cft_reduce_seg(dev, CFT_SUM, fmt, rnd, tmp, NULL, d, n,
                                    seg, &sf, bus_out);
            free(tmp);
            (void)cft_flags_mute(dev, muted);
            if (st != CFT_OK)
                return st;
            fl = pf | sf;
            /* 9.4's infinity rule, per slice as it is per call: a slice
             * whose sum came out NaN while holding an infinity and no
             * NaN of its own is the infinity. */
            if (op == CFT_SUMSQ || op == CFT_SUMABS) {
                size_t s;
                for (s = 0; s < nres; s++) {
                    uint8_t *ds = (uint8_t *)d + s * esz;
                    if (result_is_nan(f, ds)) {
                        cft_bn ov;
                        uint32_t of = 0;
                        if (sumsq_abs_inf_override(
                                f, (const uint8_t *)a + s * seg * esz, esz,
                                seg, &ov, &of)) {
                            cft_bn_store(&ov, ds, (int)esz);
                            fl = (fl & ~(uint32_t)0) | of;
                        }
                    }
                }
            }
            cft_flags_emit(dev, fl, flags_out);
            return CFT_OK;
        }
        {
            cft_bindings bd;
            bind_clear(&bd);
            bind_role(dev, &bd, CFT_ROLE_A, a, n * esz);
            backend_call();
            st = (cft_status)cftx_reduce_seg(dev->hw, (int)op, (int)fmt,
                                             (int)rnd, a, n, seg, d, &bd,
                                             &fl, bus_out);
            if (st == CFT_OK)
                cft_flags_emit(dev, fl, flags_out);
            return st;
        }
    }
#endif
#ifndef CFT_NO_REMOTE
    /* One REDUCE_SEG frame, whatever the handle's word says: the word is
     * the server device's CAPS2[8], and it is the server's own
     * cft_reduce_seg that reads it - a server fronting a tile without the
     * bit answers with this function's refusal above, by name. So on a
     * remote handle the word and the call agree without the client
     * testing anything. */
    if (dev->backend == CFT_BACKEND_REMOTE) {
        cft_status st;
        backend_call();
        st = (cft_status)cftr_reduce_seg(dev->hw, (int)op, (int)fmt,
                                         (int)rnd, a, b, d, n, seg,
                                         &fl, bus_out);
        if (st == CFT_OK)
            cft_flags_emit(dev, fl, flags_out);
        return st;
    }
#endif
    /* the software backend: the definition, slice by slice - behind the
     * bit this backend publishes (cft_open), read here for the reason
     * run_impl reads CFT_SEQ_FEAT_SCALAR on it: so that the word and the
     * path are one constant, and a software handle that stopped
     * publishing CAPS2[8] would refuse the call by name rather than go on
     * computing it behind a clear bit. Unreachable while cft_open
     * publishes it, which is every build. */
    if (!(dev->seq.features & CFT_FEAT_REDUCE_SEG)) {
        cft_set_error("cft_reduce_seg: this handle does not publish "
                      "CFT_FEAT_REDUCE_SEG (CAPS2[8]), so it does not take "
                      "a segmented reduction - %lu calls of cft_reduce, "
                      "one a segment, are the same bits",
                      (unsigned long)nres);
        return CFT_ERR_UNSUPPORTED;
    }
    {
        const int muted = cft_flags_mute(dev, 1);
        cft_status st = CFT_OK;
        size_t s;
        for (s = 0; s < nres && st == CFT_OK; s++) {
            uint32_t sf = 0;
            st = cft_reduce(dev, op, fmt, rnd,
                            (const uint8_t *)a + s * seg * esz,
                            b ? (const uint8_t *)b + s * seg * esz : NULL,
                            (uint8_t *)d + s * esz, seg, &sf, bus_out);
            fl |= sf;
        }
        (void)cft_flags_mute(dev, muted);
        if (st != CFT_OK)
            return st;
        cft_flags_emit(dev, fl, flags_out);
        return CFT_OK;
    }
}

/* ---------------------------------------------------------------
 * Buffers
 *
 * On a backend with no device memory these are ordinary allocations
 * and the sync calls do nothing, which is the whole point: code
 * written against this API stays portable to the device backend
 * without a second path.
 *
 * On the XRT backend the mirror allocated here is still the caller's
 * pointer and still what cft_buffer_data returns - the device copies
 * live behind buf->dbuf and are the backend's business - so nothing a
 * caller can observe about cft_buffer_data changed when they arrived.
 * cft.h states the authority rule between the two; this file's part
 * of it is buf_sync_in() above, which enforces it on the caller's
 * behalf at every point where the mirror is about to be read.
 * --------------------------------------------------------------- */

CFT_API cft_status cft_alloc(cft_device *dev, size_t bytes, cft_buffer **out)
{
    cft_buffer *buf;

    if (!dev || !out)
        return CFT_ERR_INVALID_ARGUMENT;
    *out = NULL;
    if (bytes == 0)
        return CFT_ERR_INVALID_ARGUMENT;

    buf = (cft_buffer *)calloc(1, sizeof *buf);
    if (!buf)
        return CFT_ERR_OUT_OF_MEMORY;
    buf->data = calloc(1, bytes);
    if (!buf->data) {
        free(buf);
        return CFT_ERR_OUT_OF_MEMORY;
    }
    buf->dev   = dev;
    buf->bytes = bytes;
#ifdef CFT_ENABLE_XRT
    /* The backend's side, if this device has one. NO device memory is
     * taken here: a copy is per (tile, role) and is made on first use
     * as that role, when the window it has to hold is finally known.
     * A failure to create the object is not a failure to allocate -
     * the buffer works, it simply stages like any other pointer - so
     * it is not reported as one. */
    if (dev->backend == CFT_BACKEND_XRT && dev->hw)
        (void)cftx_buffer_create(dev->hw, buf->data, bytes, &buf->dbuf);
#endif
    buf->next = dev->bufs;
    dev->bufs = buf;
    *out = buf;
    return CFT_OK;
}

CFT_API void *cft_buffer_data(cft_buffer *buf)
{
    return buf ? buf->data : NULL;
}

/* The mirror is the truth from here.
 *
 * On a device backend this MOVES NOTHING: it marks every device copy
 * stale, and each refills from the mirror the next time it is bound,
 * for the window that binding actually needs. Pushing eagerly would
 * mean pushing a whole buffer into every tile's channel - a tile
 * cannot read another tile's memory, so "publish" would be four
 * transfers of everything - and then pushing the right windows again
 * at the first run. So the transfer happens once, at the first use,
 * and this call is free and always safe to make. */
CFT_API cft_status cft_buffer_to_device(cft_buffer *buf)
{
    if (!buf)
        return CFT_ERR_INVALID_ARGUMENT;
#ifdef CFT_ENABLE_XRT
    if (buf->dbuf)
        return (cft_status)cftx_buffer_to_device(buf->dbuf);
#endif
    return CFT_OK;
}

/* And the other direction: everything a run wrote into this buffer
 * and has not yet returned, copied back into the mirror. A no-op when
 * no run has written it, so it is safe to call unconditionally. */
CFT_API cft_status cft_buffer_from_device(cft_buffer *buf)
{
    if (!buf)
        return CFT_ERR_INVALID_ARGUMENT;
#ifdef CFT_ENABLE_XRT
    if (buf->dbuf)
        return (cft_status)cftx_buffer_from_device(buf->dbuf);
#endif
    return CFT_OK;
}

/* What happened to this buffer                            (ABI 0.11)
 *
 * The counters come from the backend, because it is the backend that
 * decides each binding; the rest is this file's. A buffer on a
 * backend with no device memory answers zeroes and says why, which is
 * a real answer and not a missing one - the calls are portable, and a
 * caller comparing two machines wants to be told which kind it has
 * rather than left to infer it from a rate. */
CFT_API cft_status cft_buffer_get_info(cft_buffer *buf,
                                       cft_buffer_info *out)
{
    cft_buffer_info info;
    size_t want;

    if (!buf || !out)
        return CFT_ERR_INVALID_ARGUMENT;
    want = out->struct_size;
    if (want < sizeof(size_t))
        return CFT_ERR_INVALID_ARGUMENT;

    memset(&info, 0, sizeof info);
    info.bytes = buf->bytes;
#ifdef CFT_ENABLE_XRT
    if (buf->dbuf) {
        cftx_buffer_stat(buf->dbuf, &info.resident, &info.device_authority,
                         &info.resident_binds, &info.staged_binds,
                         info.staged_why, sizeof info.staged_why);
    } else
#endif
    {
        strncpy(info.staged_why,
                buf->dev ? "this backend keeps no device copies: the "
                           "buffer is host memory and the sync calls "
                           "are no-ops"
                         : "the device this buffer was allocated on has "
                           "been closed; it is host memory now",
                sizeof info.staged_why - 1);
    }

    if (want > sizeof info)
        want = sizeof info;
    info.struct_size = want;
    memcpy(out, &info, want);
    return CFT_OK;
}

CFT_API void cft_buffer_free(cft_buffer *buf)
{
    if (!buf)
        return;
    /* Unlink from the device's registry first, so that nothing can
     * resolve a pointer into a buffer that is going away. A buffer
     * whose device was closed first was already unlinked there. */
    if (buf->dev) {
        cft_buffer **pp = &buf->dev->bufs;
        while (*pp) {
            if (*pp == buf) {
                *pp = buf->next;
                break;
            }
            pp = &(*pp)->next;
        }
    }
#ifdef CFT_ENABLE_XRT
    if (buf->dbuf)
        cftx_buffer_destroy(buf->dbuf);
#endif
    /* Whatever a run wrote and nobody read back goes with it. That is
     * what free means, and cft.h says to call cft_buffer_from_device
     * first if the bytes were wanted. */
    free(buf->data);
    free(buf);
}

/* ---------------------------------------------------------------
 * The status word (754-2019 7.1) and the six operations of 5.7.4,
 * plus the three conformance predicates of 5.7.1.       (ABI 0.7)
 *
 * 7.1: "For each kind of exception the implementation shall provide a
 * corresponding status flag ... Status flags shall be lowered only at
 * the user's request. The user shall be able to test and to alter the
 * status flags individually or collectively, and shall further be
 * able to save and restore all at one time (see 5.7.4)."
 *
 * The word is one uint32_t on the device handle, in the same
 * cft_exception bits every entry point already returns. It is the
 * ONLY mutable state libcft keeps, and it is inert: nothing here or
 * anywhere else in the library reads it back to decide a result, so
 * two runs of the same calls on the same inputs produce the same bits
 * whatever the word happens to hold. The determinism contract is
 * untouched by its existence.
 *
 * Every producer reaches it through cft_flags_emit() below and only
 * through that, which is why a new entry point costs one line.
 * --------------------------------------------------------------- */

/* The one seam. See softfloat.h for the contract; the whole of it is
 * "OR in, then write out". */
void cft_flags_emit(struct cft_device *dev, uint32_t acc,
                    uint32_t *flags_out)
{
    if (dev && !dev->flags_muted)
        dev->sticky_flags |= acc;
    if (flags_out)
        *flags_out = acc;
}

/* The composition discipline's half. See softfloat.h for why an
 * internal pass must not reach the word. */
int cft_flags_mute(struct cft_device *dev, int on)
{
    int prev;
    if (!dev)
        return 0;
    prev = dev->flags_muted;
    dev->flags_muted = on;
    return prev;
}

/* 5.7.4 lowerFlags(exceptionGroup). A NULL device has no word to
 * lower, so this does nothing rather than crashing - the same
 * tolerance cft_close() and cft_buffer_free() already promise. */
CFT_API void cft_lower_flags(cft_device *dev, uint32_t mask)
{
    if (dev)
        dev->sticky_flags &= ~mask;
}

/* 5.7.4 raiseFlags(exceptionGroup). The one operation besides an
 * arithmetic call that can raise a flag, and 7.1 says so: "status
 * flags are raised without an exception being signaled only at the
 * user's request". */
CFT_API void cft_raise_flags(cft_device *dev, uint32_t mask)
{
    if (dev)
        dev->sticky_flags |= mask;
}

/* 5.7.4 testFlags(exceptionGroup): "Queries whether ANY of the flags
 * ... are raised" - so this is a disjunction over the mask and not an
 * equality, and it returns 1 or 0 rather than the intersection, which
 * a caller could mistake for a flag word. A NULL device tests an
 * empty word: 0. */
CFT_API int cft_test_flags(cft_device *dev, uint32_t mask)
{
    return dev && (dev->sticky_flags & mask) ? 1 : 0;
}

/* 5.7.4 saveAllFlags(void): "Returns a representation of the state of
 * all status flags." The representation here is the flag word itself,
 * in cft_exception bits - which is what makes it comparable with the
 * flags_out of any call. 0 for a NULL device. */
CFT_API uint32_t cft_save_all_flags(cft_device *dev)
{
    return dev ? dev->sticky_flags : 0u;
}

/* 5.7.4 restoreFlags(flags, exceptionGroup): "Restores the flags
 * corresponding to the exceptions specified in the exceptionGroup
 * operand ... to their state represented in the flags operand."
 *
 * Restores, not ORs: a flag inside the mask that is LOW in `saved`
 * comes back low, which is the only reading under which
 * restoreFlags(saveAllFlags(), all) is the identity it is meant to
 * be. Flags outside the mask are left exactly as they stand. */
CFT_API void cft_restore_flags(cft_device *dev, uint32_t saved,
                               uint32_t mask)
{
    if (dev)
        dev->sticky_flags = (dev->sticky_flags & ~mask) | (saved & mask);
}

/* 5.7.4 testSavedFlags(flags, exceptionGroup). No device: the whole
 * operation is a question about a value the caller already holds, and
 * giving it a device argument would suggest otherwise. */
CFT_API int cft_test_saved_flags(uint32_t saved, uint32_t mask)
{
    return (saved & mask) ? 1 : 0;
}

/* ---- 5.7.1, the conformance predicates ---------------------------- *
 *
 * "Implementations shall provide the following non-computational
 * operations, true if and only if the indicated conditions are true:
 * boolean is754version1985(void) ... boolean is754version2008(void)
 * ... boolean is754version2019(void)" (5.7.1)
 *
 * The answers are constants, and each rests on something stated
 * elsewhere rather than on this file's opinion. See cft.h for the
 * three arguments in full; in one line each:
 *
 *   1985 - false: never evaluated against the 1985 text.
 *   2008 - false: 754-2008 required minNum/maxNum/minNumMag/maxNumMag
 *          in its 5.3.1, and this library implements 2019's 9.6
 *          semantics instead, which are not the same operations.
 *   2019 - true from ABI 0.7, when clause 5 is complete;
 *          docs/COMPLIANCE.md is the clause-by-clause statement.
 */
CFT_API int cft_is754version1985(void) { return 0; }
CFT_API int cft_is754version2008(void) { return 0; }
CFT_API int cft_is754version2019(void) { return 1; }
