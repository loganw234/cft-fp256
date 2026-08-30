/* Copyright 2026 Logan W.
 * SPDX-License-Identifier: Apache-2.0
 *
 * libcft - the Coordinated Fusion Tile host API.
 *
 * STATUS: design artifact. This header is the contract; the
 * implementation follows. It is published first, deliberately, so the
 * shape can be argued with before anything depends on it.
 *
 * ---------------------------------------------------------------
 * What this library promises
 * ---------------------------------------------------------------
 *
 * The same call, with the same inputs, returns the same bits. On every
 * backend, on every machine, on every day. That is the entire product;
 * speed and precision are what you get on top of it.
 *
 * Concretely: cft_run() with a software backend on a laptop and
 * cft_run() with the FPGA tile produce byte-identical output buffers
 * and identical exception flags. Not "within an ulp" - identical. A
 * result that differs is a bug in this library, not a tolerance to
 * document.
 *
 * ---------------------------------------------------------------
 * Why C
 * ---------------------------------------------------------------
 *
 * Because the fields that need reproducible arithmetic do not write
 * their numerics in one language. A C ABI is directly callable from
 * Fortran (iso_c_binding), Julia (ccall), Python (ctypes/cffi), Rust,
 * Go, MATLAB, R, C# and Java without a binding generator or a build
 * step. Porting this library to a language means writing a shim, never
 * reimplementing semantics - and semantics reimplemented is exactly how
 * "identical bits" quietly stops being true.
 *
 * ---------------------------------------------------------------
 * The device is a backend, not a requirement
 * ---------------------------------------------------------------
 *
 * Open with a NULL artifact and you get the software backend, which
 * needs no card, no driver and no Linux. Open with an xclbin and you
 * get the tile. The call sites do not change. Adopt the library first,
 * add hardware later, and nothing above the API notices except the
 * clock on the wall.
 *
 * ---------------------------------------------------------------
 * How you check we are telling the truth
 * ---------------------------------------------------------------
 *
 * cft_conformance() replays the project's published vector sets
 * (vectors/*.jsonl) through whatever backend you opened and reports
 * the first disagreement. A backend, a binding, a port, or somebody
 * else's independent implementation is correct if and only if it
 * replays those files exactly. Do not take the guarantee above on
 * trust; it is machine-checkable, so check it.
 */

#ifndef CFT_H
#define CFT_H

#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/* ---------------------------------------------------------------
 * ABI version
 *
 * Major changes break source or binary compatibility; minor additions
 * do not. Check at runtime rather than trusting the header you
 * compiled against - a binding loaded against a different shared
 * library is the normal case, not the exceptional one.
 * --------------------------------------------------------------- */
#define CFT_ABI_VERSION_MAJOR 0
#define CFT_ABI_VERSION_MINOR 1

/* Returns (major << 16) | minor of the library actually loaded. */
uint32_t cft_abi_version(void);

/* ---------------------------------------------------------------
 * Status
 * --------------------------------------------------------------- */
typedef enum cft_status {
    CFT_OK = 0,
    CFT_ERR_INVALID_ARGUMENT,
    CFT_ERR_UNSUPPORTED,   /* op or format not available on this device;
                            * ask cft_supports() first */
    CFT_ERR_NO_DEVICE,
    CFT_ERR_ARTIFACT,      /* xclbin missing, unreadable, or not a tile */
    CFT_ERR_BUS_FAULT,     /* the memory system did not vouch for the
                            * data. The output buffer is NOT valid: a
                            * bad pointer or a fabric error means the
                            * kernel computed on bits that were never
                            * delivered. Distinct from a wrong answer,
                            * and worth distinguishing. */
    CFT_ERR_OUT_OF_MEMORY,
    CFT_ERR_TIMEOUT,
    CFT_ERR_INTERNAL
} cft_status;

/* Static, human-readable; never NULL, never needs freeing. */
const char *cft_strerror(cft_status s);

/* ---------------------------------------------------------------
 * Formats, operations, rounding
 *
 * These values are normative for callers. They happen to match the
 * hardware's MODE encoding, which keeps the mapping auditable, but a
 * caller depends on the names here and never on the register layout.
 * --------------------------------------------------------------- */
typedef enum cft_format {
    CFT_FP32  = 0,   /* IEEE binary32  - 4 bytes per element */
    CFT_FP64  = 1,   /* IEEE binary64  - 8 bytes */
    CFT_FP128 = 2,   /* IEEE binary128 - 16 bytes */
    CFT_FP256 = 3    /* IEEE binary256 - 32 bytes, 237-bit significand */
} cft_format;

size_t cft_format_size(cft_format f);   /* bytes per element; 0 if invalid */

typedef enum cft_op {
    /* Arithmetic. These round, and consult the rounding attribute. */
    CFT_FMA      = 0,   /* d = a*b + c, one rounding, exact product */
    CFT_ADD      = 1,   /* d = a + c   (b ignored) */
    CFT_SUB      = 2,   /* d = a - c   (b ignored) */
    CFT_MUL      = 3,   /* d = a * b   (c ignored) */

    /* Sign operations (754-2019 5.5.1). Quiet: they signal nothing at
     * all, not even for a signaling NaN, and preserve NaN payloads. */
    CFT_ABS      = 4,
    CFT_NEG      = 5,
    CFT_COPYSIGN = 6,   /* magnitude of a, sign of b */

    /* Minimum and maximum (754-2019 9.6). min(+0,-0) is -0 and
     * max(+0,-0) is +0: signed zeros compare equal but are not
     * interchangeable. The NUM forms return the number when one
     * operand is NaN; the plain forms propagate the NaN. */
    CFT_MIN      = 7,
    CFT_MAX      = 8,
    CFT_MINNUM   = 9,
    CFT_MAXNUM   = 10,

    /* Data movement and predicates. The predicates yield 1.0 or +0.0
     * rather than a boolean so that CFT_SELECT consumes them directly
     * and the result lives in the same arrays as everything else -
     * which is what makes branchless conditional code expressible.
     *
     * There is no "greater" or "greater or equal", and none is needed:
     * a > b is CFT_CMPLT with the a and b arguments swapped. */
    CFT_SELECT   = 11,  /* d = (c != 0) ? a : b; moves NaNs intact */
    CFT_CMPLT    = 12,
    CFT_CMPLE    = 13,
    CFT_CMPEQ    = 14,

    /* The encoding as an unsigned integer of the format's width. Not
     * floating point: no rounding, no signalling, no NaN handling. The
     * bits are just bits. These exist because reproducible algebraic
     * kernels start from integer seeds - a reciprocal-square-root
     * estimate is a constant minus a shifted exponent field. */
    CFT_IAND     = 16,
    CFT_IOR      = 17,
    CFT_IXOR     = 18,
    CFT_IADD     = 19,  /* wraps modulo 2^width */
    CFT_ISUB     = 20,
    CFT_ISHL     = 21,  /* count from b, modulo the format width */
    CFT_ISHR     = 22,  /* logical, never arithmetic */
    CFT_ICMPLT   = 23   /* unsigned; yields 1.0 or +0.0 */
} cft_op;

/* Rounding-direction attributes, IEEE 754-2019 clause 4.3. Ignored by
 * every operation from CFT_ABS onward - those do not round. */
typedef enum cft_round {
    CFT_RNE = 0,   /* roundTiesToEven - the default, and what the
                    * contract means unless a call says otherwise */
    CFT_RTZ = 1,   /* roundTowardZero */
    CFT_RDN = 2,   /* roundTowardNegative */
    CFT_RUP = 3,   /* roundTowardPositive */
    CFT_RMM = 4    /* roundTiesToAway */
} cft_round;

/* Sticky exception flags, OR-accumulated across a whole call. */
typedef enum cft_exception {
    CFT_FLAG_INVALID   = 1u << 0,
    CFT_FLAG_DIVBYZERO = 1u << 1,   /* reserved: no divide yet */
    CFT_FLAG_OVERFLOW  = 1u << 2,
    CFT_FLAG_UNDERFLOW = 1u << 3,   /* tiny AND inexact */
    CFT_FLAG_INEXACT   = 1u << 4
} cft_exception;

/* ---------------------------------------------------------------
 * Devices
 * --------------------------------------------------------------- */
typedef struct cft_device cft_device;

/* Open a device.
 *
 *   artifact == NULL   the software backend. Always available, needs
 *                      no card, no driver, no Linux. Same bits.
 *   artifact != NULL   path to an .xclbin; the tile.
 *
 * index selects among identical devices when more than one is present;
 * pass 0 unless you know otherwise.
 *
 * A cft_device is NOT thread-safe. Open one per thread, or serialise
 * calls yourself. Opening several handles to the same physical device
 * is allowed.
 */
cft_status cft_open(const char *artifact, int index, cft_device **out);
void       cft_close(cft_device *dev);

/* What this device actually implements.
 *
 * A trimmed build may carry fewer formats than the full tile, and a
 * future one will carry more operations. Ask rather than assume: the
 * whole point of a portable contract is that the same binary runs
 * against several generations of device. */
typedef struct cft_caps {
    size_t   struct_size;      /* set by caller to sizeof(cft_caps) */
    uint32_t format_mask;      /* bit (1u << cft_format) per format */
    uint32_t tiles;            /* compute units; partitioning is
                                * internal and invisible to callers */
    uint32_t abi_version;
    uint32_t device_version;   /* hardware contract version, or 0 */
    int      flags_readable;   /* some runtimes cannot read the status
                                * registers; when 0, the flags_out
                                * argument of cft_run is left untouched
                                * and you must not treat it as clean */
    char     backend[32];      /* "software", "xrt", ... */
} cft_caps;

cft_status cft_get_caps(cft_device *dev, cft_caps *out);

/* Is this (op, format) pair implemented here? Returns 1, or 0. */
int cft_supports(cft_device *dev, cft_op op, cft_format fmt);

/* ---------------------------------------------------------------
 * The core call
 *
 * Elementwise over three input arrays into one output array:
 *
 *     d[i] = op(a[i], b[i], c[i])   for i in [0, n)
 *
 * Element i of the output depends on element i of the inputs and
 * nothing else, so there is no ordering question to get wrong and no
 * reduction to make non-deterministic.
 *
 * Buffers are dense, little-endian, and cft_format_size(fmt) bytes per
 * element. Unused operands (b for ADD, c for MUL) may be NULL.
 *
 * n is ARBITRARY. The hardware works in whole 256-bit beats, but that
 * is the library's problem, not yours: a partial tail is padded and
 * masked internally, and padding never contributes to the flags.
 *
 * flags_out and bus_out may be NULL if you do not want them. If
 * bus_out is non-NULL and the call returns CFT_ERR_BUS_FAULT, it
 * carries the raw fault bits for diagnosis.
 *
 * On any error the contents of d are unspecified. Do not read them.
 */
cft_status cft_run(cft_device *dev,
                   cft_op      op,
                   cft_format  fmt,
                   cft_round   rnd,
                   const void *a,
                   const void *b,
                   const void *c,
                   void       *d,
                   size_t      n,
                   uint32_t   *flags_out,
                   uint32_t   *bus_out);

/* ---------------------------------------------------------------
 * Device-resident buffers (optional, for throughput)
 *
 * cft_run copies host memory in and out. That is the right default -
 * it always works and it is what a first port should use - but it
 * costs a round trip per call. When the same operands feed several
 * calls, allocate here instead and hand the mapped pointers to
 * cft_run: the library recognises its own buffers and skips staging.
 *
 * On the software backend these are ordinary allocations and the sync
 * calls are no-ops, so code written this way stays portable.
 * --------------------------------------------------------------- */
typedef struct cft_buffer cft_buffer;

cft_status cft_alloc(cft_device *dev, size_t bytes, cft_buffer **out);
void      *cft_buffer_data(cft_buffer *buf);   /* host-visible pointer */
cft_status cft_buffer_to_device(cft_buffer *buf);
cft_status cft_buffer_from_device(cft_buffer *buf);
void       cft_buffer_free(cft_buffer *buf);

/* ---------------------------------------------------------------
 * Conformance
 *
 * Replay the published vector sets through this device and report the
 * first disagreement. This is how a port, a backend, or an independent
 * implementation proves itself - and how you audit ours.
 *
 * dir is the directory holding the .jsonl sets (vectors/out by
 * default). Returns CFT_OK when every case matched; on a mismatch,
 * fills report (if non-NULL) with a human-readable description of the
 * first failing case, truncated to report_size.
 * --------------------------------------------------------------- */
cft_status cft_conformance(cft_device *dev, const char *dir,
                           char *report, size_t report_size,
                           uint64_t *cases_checked);

#ifdef __cplusplus
}  /* extern "C" */
#endif

#endif /* CFT_H */
