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
static void backend_call(void);

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
 * what they asked for. */
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
    for (i = 0; i < 4; i++) {
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
    if ((int)f < 0 || (int)f > 3)
        return 0;
    return (size_t)cft_sf_formats[(int)f].width / 8;
}

CFT_API const char *cft_format_name(cft_format f)
{
    if ((int)f < 0 || (int)f > 3)
        return "invalid";
    return cft_sf_formats[(int)f].name;
}

CFT_API const char *cft_op_name(cft_op op)
{
    static const char *const names[31] = {
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
        "imul"
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
    dev->format_mask    = (1u << CFT_FP32) | (1u << CFT_FP64) |
                          (1u << CFT_FP128) | (1u << CFT_FP256);
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
     * tile's - see the note there. */
    cft_sw_seq_caps(&dev->seq);
    dev->backend_name   = "software";
    dev->hw             = NULL;
    *out = dev;
    return CFT_OK;
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
        /* The three streams and the deposit window. `counts` is four
         * bytes an element whatever the format and the image and bank
         * do not grow with n at all, so none of them is worth a
         * device copy - backend.h says so beside the signature. */
        buf_sync_in(dev, a, n * esz);
        buf_sync_in(dev, b, n * esz);
        buf_sync_in(dev, c, n * esz);
        bind_role(dev, &bd, CFT_ROLE_A, a, n * esz);
        bind_role(dev, &bd, CFT_ROLE_B, b, n * esz);
        bind_role(dev, &bd, CFT_ROLE_C, c, n * esz);
        if (max_deposits)
            bind_role(dev, &bd, CFT_ROLE_D, deposits,
                      n * max_deposits * esz);
        backend_call();
        return cftx_program_run(dev->hw, fmt, image, image_bytes, io,
                                max_deposits, a, b, c, deposits, counts, n,
                                &bd, flags, bus);
    }
#endif
#ifndef CFT_NO_REMOTE
    if (dev && dev->backend == CFT_BACKEND_REMOTE) {
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
 * The one producer today is cft_program_load's capacity refusal. */
static char g_msg[320];

void cft_set_error(const char *fmt, ...)
{
    va_list ap;
    va_start(ap, fmt);
    vsnprintf(g_msg, sizeof g_msg, fmt, ap);
    va_end(ap);
}

/* Called immediately before handing anything to a device backend. */
static void backend_call(void)
{
    g_msg[0] = '\0';
}

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
    if ((int)fmt < 0 || (int)fmt > 3)
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
     * (cft_caps.seq_features, CFT_ALU_EXT_IMUL). */
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
    if ((int)fmt < 0 || (int)fmt > 3)
        return CFT_ERR_INVALID_ARGUMENT;
    if ((int)rnd < 0 || (int)rnd > 4)
        return CFT_ERR_INVALID_ARGUMENT;
    /* The device carries the opcode in a byte. Anything wider is a
     * caller mistake; anything inside it that is unassigned is not -
     * it has a defined answer, produced below. */
    if ((int)op < 0 || (int)op > 255)
        return CFT_ERR_INVALID_ARGUMENT;
    if (!(dev->format_mask & (1u << (int)fmt)))
        return CFT_ERR_UNSUPPORTED;
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
            return CFT_ERR_UNSUPPORTED;
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
        buf_sync_in(dev, a, n * esz);
        buf_sync_in(dev, b, n * esz);
        buf_sync_in(dev, c, n * esz);
        bind_role(dev, &bd, CFT_ROLE_A, a, n * esz);
        bind_role(dev, &bd, CFT_ROLE_B, b, n * esz);
        bind_role(dev, &bd, CFT_ROLE_C, c, n * esz);
        bind_role(dev, &bd, CFT_ROLE_D, d, n * esz);
        backend_call();
        st = (cft_status)cftx_run(dev->hw, (int)op, (int)fmt,
                                             (int)rnd, a, b, c, d, n,
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
        backend_call();
        st = (cft_status)cftr_run(dev->hw, (int)op, (int)fmt,
                                             (int)rnd, a, b, c, d, n,
                                             &fl, bus_out);
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

    for (i = 0; i < n; i++) {
        uint32_t fl = 0;
        /* Load before storing, so d may alias a, b or c. */
        if (pa) cft_bn_load(&ba, pa + i * esz, (int)esz);
        if (pb) cft_bn_load(&bb, pb + i * esz, (int)esz);
        if (pc) cft_bn_load(&bc, pc + i * esz, (int)esz);
        if (cft_sf_compute(f, (int)op, (int)rnd, &ba, &bb, &bc, &bo, &fl))
            return CFT_ERR_INTERNAL;
        acc |= fl;
        cft_bn_store(&bo, pd + i * esz, (int)esz);
    }

    cft_flags_emit(dev, acc, flags_out);
    return CFT_OK;
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
    if ((int)fmt < 0 || (int)fmt > 3)
        return CFT_ERR_INVALID_ARGUMENT;
    if ((int)rnd < 0 || (int)rnd > 4)
        return CFT_ERR_INVALID_ARGUMENT;
    /* The mirror of cft_run's refusal: this entry point is for
     * reductions, and handing it an elementwise opcode would otherwise
     * quietly compute something nobody asked for. */
    if (!cft_sf_is_reduction((int)op))
        return CFT_ERR_INVALID_ARGUMENT;
    if (!(dev->format_mask & (1u << (int)fmt)))
        return CFT_ERR_UNSUPPORTED;
    {
        int group = op_group_bit((int)op);
        if (group < 0 || !(dev->op_groups & (1u << group)))
            return CFT_ERR_UNSUPPORTED;
        /* A composed reduction also needs the group its composition
         * runs through - the multiply for sumSquare, the abs for
         * sumAbs - and a device missing one must say so here rather
         * than fail partway through the sequence. */
        group = reduce_helper_group((int)op);
        if (group >= 0 && !(dev->op_groups & (1u << group)))
            return CFT_ERR_UNSUPPORTED;
    }
    if (!d)
        return CFT_ERR_INVALID_ARGUMENT;

    f   = &cft_sf_formats[(int)fmt];
    esz = (size_t)f->width / 8;

    /* n == 0 is +0.0 and raises nothing: the additive identity, and
     * the only result here that is not a function of any input. It is
     * handled before the operand check because a sum of nothing does
     * not need anything to sum. */
    if (n == 0) {
        cft_bn z;
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
