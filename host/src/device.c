/* Copyright 2026 Logan W.
 * SPDX-License-Identifier: Apache-2.0
 *
 * libcft: devices, capabilities, buffers and the one call that does
 * the work. The arithmetic lives in softfloat.c; this file is the
 * boundary between it and the rest of the world, so its job is
 * argument checking and bookkeeping - the two things a caller in
 * another language cannot do for itself.
 */

#include <stdlib.h>
#include <string.h>

#include "../include/cft.h"
#include "softfloat.h"
#ifdef CFT_ENABLE_XRT
#include "backend.h"
#endif

#define CFT_BACKEND_SW  0
#define CFT_BACKEND_XRT 1

struct cft_device {
    int         backend;
    int         index;
    uint32_t    format_mask;
    uint32_t    op_groups;      /* CAPS[15:8]; software carries them all */
    uint32_t    tiles;
    uint32_t    device_version;
    int         flags_readable;
    const char *backend_name;
    void       *hw;             /* backend handle, NULL for software */
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
    return -1;
}

struct cft_buffer {
    cft_device *dev;
    size_t      bytes;
    void       *data;
};

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
    static const char *const names[24] = {
        "fma", "add", "sub", "mul",
        "abs", "neg", "copysign",
        "min", "max", "minnum", "maxnum",
        "select", "cmplt", "cmple", "cmpeq",
        0,
        "iand", "ior", "ixor", "iadd",
        "isub", "ishl", "ishr", "icmplt"
    };
    if ((int)op >= 0 && (int)op < 24 && names[(int)op])
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

    if (artifact) {
#ifdef CFT_ENABLE_XRT
        uint32_t fmask = 0, groups = 0, tiles = 0, ver = 0;
        int readable = 1;
        void *hw = NULL;
        int st = cftx_open(artifact, index, &hw, &fmask, &groups, &tiles,
                           &ver, &readable);
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
    dev->op_groups      = 0x1Fu;    /* every assigned group */
    dev->tiles          = 1;
    dev->device_version = 0;
    dev->flags_readable = 1;
    dev->backend_name   = "software";
    dev->hw             = NULL;
    *out = dev;
    return CFT_OK;
}

CFT_API void cft_close(cft_device *dev)
{
    if (!dev)
        return;
#ifdef CFT_ENABLE_XRT
    if (dev->hw)
        cftx_close(dev->hw);
#endif
    free(dev);
}

CFT_API const char *cft_last_error(void)
{
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
    return (dev->op_groups & (1u << group)) ? 1 : 0;
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
    }

    if (n == 0) {
        if (flags_out)
            *flags_out = 0;
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
        cft_status st = (cft_status)cftx_run(dev->hw, (int)op, (int)fmt,
                                             (int)rnd, a, b, c, d, n,
                                             &fl, bus_out);
        if (st == CFT_OK && flags_out)
            *flags_out = fl;
        return st;
    }
#endif

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

    if (flags_out)
        *flags_out = acc;
    return CFT_OK;
}

/* ---------------------------------------------------------------
 * Buffers
 *
 * On the software backend these are ordinary allocations and the sync
 * calls do nothing, which is the whole point: code written against
 * this API stays portable to the device backend without a second path.
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
    *out = buf;
    return CFT_OK;
}

CFT_API void *cft_buffer_data(cft_buffer *buf)
{
    return buf ? buf->data : NULL;
}

CFT_API cft_status cft_buffer_to_device(cft_buffer *buf)
{
    return buf ? CFT_OK : CFT_ERR_INVALID_ARGUMENT;
}

CFT_API cft_status cft_buffer_from_device(cft_buffer *buf)
{
    return buf ? CFT_OK : CFT_ERR_INVALID_ARGUMENT;
}

CFT_API void cft_buffer_free(cft_buffer *buf)
{
    if (!buf)
        return;
    free(buf->data);
    free(buf);
}
