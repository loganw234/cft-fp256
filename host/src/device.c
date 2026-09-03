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

/* Ranges a device reduction may be split into. One per tile, so this
 * is MAX_TILES in the XRT backend - kept as its own name because it
 * sizes two stack arrays here and a wrong value would overflow them
 * quietly. */
#define CFT_MAX_REDUCE_PARTS 64
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
    static const char *const names[30] = {
        "fma", "add", "sub", "mul",
        "abs", "neg", "copysign",
        "min", "max", "minnum", "maxnum",
        "select", "cmplt", "cmple", "cmpeq",
        0,
        "iand", "ior", "ixor", "iadd",
        "isub", "ishl", "ishr", "icmplt",
        "sum", "dot",
        "recip_seed", "rsqrt_seed",
        "sumsq", "sumabs"
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
    /* Every assigned group, reductions (bit 5) and the divide/sqrt
     * seeds (bit 6) included. The software backend is the contract,
     * so it implements all of it; a device advertises what its
     * bitstream actually contains. */
    dev->op_groups      = 0x7Fu;
    dev->tiles          = 1;
    dev->device_version = 0;
    dev->flags_readable = 1;
    dev->backend_name   = "software";
    dev->hw             = NULL;
    *out = dev;
    return CFT_OK;
}

#ifdef CFT_ENABLE_XRT
/* program.c asks this to decide which executor a program run belongs
 * to. It is the only thing outside this file that needs to know a
 * device has a backend at all, and it deliberately returns the opaque
 * handle rather than the struct: the shape of cft_device stays this
 * file's business. */
void *cft_device_backend(const struct cft_device *dev)
{
    if (!dev || dev->backend != CFT_BACKEND_XRT)
        return NULL;
    return dev->hw;
}
#endif

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
    if (!(dev->op_groups & (1u << group)))
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
        if (flags_out)
            *flags_out = 0;
        return CFT_OK;
    }

    need = cft_sf_op_operands((int)op);
    if (((need & 1u) && !a) || ((need & 2u) && !b))
        return CFT_ERR_INVALID_ARGUMENT;
    if (n > ((size_t)-1) / esz)
        return CFT_ERR_INVALID_ARGUMENT;

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
        if (flags_out)
            *flags_out = cf;
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
            if (!tmp)
                return CFT_ERR_OUT_OF_MEMORY;
            st = cft_run(dev, CFT_MUL, fmt, rnd, a, b, NULL, tmp, n,
                         &mf, bus_out);
            if (st == CFT_OK)
                st = cft_reduce(dev, CFT_SUM, fmt, rnd, tmp, NULL, d, n,
                                &sf, bus_out);
            free(tmp);
            if (st == CFT_OK && flags_out)
                *flags_out = mf | sf;
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

            st = (cft_status)cftx_reduce(dev->hw, (int)op, (int)fmt,
                                         (int)rnd, a, lo, hi, nr,
                                         partials, &fl, bus_out);
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
            if (flags_out)
                *flags_out = fl;
            return CFT_OK;
        }
    }
#endif

    if (cft_sf_reduce(f, (int)op, (int)rnd, a, b, esz, 0, n, &bo, &fl))
        return CFT_ERR_INTERNAL;
    cft_bn_store(&bo, (uint8_t *)d, (int)esz);
    if (flags_out)
        *flags_out = fl;
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
