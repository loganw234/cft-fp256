/* Copyright 2026 Logan W.
 * SPDX-License-Identifier: Apache-2.0
 *
 * libcft - the Coordinated Fusion Tile host API.
 *
 * STATUS: the software backend is implemented and is checked against
 * the golden model over the whole interesting input space (see
 * host/tests/). The device backend is not built yet, so cft_open()
 * with an artifact path reports CFT_ERR_UNSUPPORTED; nothing above
 * this API will change when it lands, which is the point.
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
 * cft_conformance() replays the project's published vector sets - the
 * .jsonl files under vectors/ - through whatever backend you opened
 * and reports the first disagreement. A backend, a binding, a port, or somebody
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

/* Everything not marked CFT_API is internal and not exported, so the
 * shared library's surface is exactly this header. Define
 * CFT_BUILD_SHARED when building the DLL and CFT_USE_SHARED when
 * linking against it; static builds need neither. */
#if defined(_WIN32) || defined(__CYGWIN__)
#  if defined(CFT_BUILD_SHARED)
#    define CFT_API __declspec(dllexport)
#  elif defined(CFT_USE_SHARED)
#    define CFT_API __declspec(dllimport)
#  else
#    define CFT_API
#  endif
#elif defined(__GNUC__) && __GNUC__ >= 4
#  define CFT_API __attribute__((visibility("default")))
#else
#  define CFT_API
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
CFT_API uint32_t cft_abi_version(void);

/* ---------------------------------------------------------------
 * Status
 * --------------------------------------------------------------- */
typedef enum cft_status {
    CFT_OK = 0,
    CFT_ERR_INVALID_ARGUMENT,
    CFT_ERR_UNSUPPORTED,   /* op or format not available on this device;
                            * ask cft_supports() first */
    CFT_ERR_NO_DEVICE,
    CFT_ERR_ARTIFACT,      /* a file this library was told to load is
                            * missing, unreadable, or not what it claims:
                            * an xclbin that is not a tile, a vector set
                            * that is not a vector set */
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
CFT_API const char *cft_strerror(cft_status s);

/* Detail on the most recent failure, or "" if there is none to add.
 * cft_strerror() says what kind of thing went wrong; this says what
 * the device runtime said about it, which on a bad night at the bench
 * is the only explanation anybody is going to get. Static storage,
 * overwritten by the next failure, and not thread-safe - consistent
 * with cft_device, which is not either. Never NULL. */
CFT_API const char *cft_last_error(void);

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

CFT_API size_t cft_format_size(cft_format f); /* bytes per element; 0 if bad */

/* Canonical names, so a binding, a log line and a conformance report
 * all say "fp128" rather than 2. Static storage, never NULL. */
CFT_API const char *cft_format_name(cft_format f);

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

/* The canonical name, so a binding, a log line and a conformance
 * report all say "minnum" rather than 9. Static storage, never NULL;
 * anything unassigned reads back as "reserved". */
CFT_API const char *cft_op_name(cft_op op);

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
CFT_API cft_status cft_open(const char *artifact, int index,
                            cft_device **out);
CFT_API void       cft_close(cft_device *dev);

/* What this device actually implements.
 *
 * A trimmed build may carry fewer formats than the full tile, and a
 * future one will carry more operations. Ask rather than assume: the
 * whole point of a portable contract is that the same binary runs
 * against several generations of device.
 *
 * Zero the struct, set struct_size to sizeof(cft_caps), then call. On
 * return struct_size is how many bytes were actually filled, so a
 * caller built against a newer header can tell what it got instead of
 * reading its own zeroes as answers.
 *
 * Fields are only ever appended to this struct, never reordered or
 * resized. That is what makes the size handshake safe in both
 * directions: an older caller's struct always ends on a field
 * boundary of the newer one. */
typedef struct cft_caps {
    size_t   struct_size;      /* in: sizeof(cft_caps); out: bytes filled */
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

CFT_API cft_status cft_get_caps(cft_device *dev, cft_caps *out);

/* Is this (op, format) pair implemented here? Returns 1, or 0.
 *
 * An unassigned opcode answers 0 while still being runnable - see
 * cft_run below. The two are not in conflict: this reports what the
 * device implements, cft_run reports what it does when you ask
 * anyway. */
CFT_API int cft_supports(cft_device *dev, cft_op op, cft_format fmt);

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
 * d may alias a, b or c. Each element is read before it is written and
 * elements are independent, so computing in place is well defined -
 * which matters for the long chains of elementwise steps that
 * branchless code turns into.
 *
 * An opcode the contract leaves unassigned (15, and 24 upward) is not
 * an error: it returns CFT_OK having written the canonical quiet NaN
 * and raised invalid, because that is exactly what the device does,
 * and "the same call returns the same bits" has to hold for the
 * uninteresting inputs too. Ask cft_supports() if you want to know
 * before issuing one. Values outside 0..255 do not fit the device's
 * opcode field and are CFT_ERR_INVALID_ARGUMENT.
 *
 * flags_out and bus_out may be NULL if you do not want them. If
 * bus_out is non-NULL and the call returns CFT_ERR_BUS_FAULT, it
 * carries the raw fault bits for diagnosis.
 *
 * On any error the contents of d are unspecified. Do not read them.
 */
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

CFT_API cft_status cft_alloc(cft_device *dev, size_t bytes,
                             cft_buffer **out);
CFT_API void      *cft_buffer_data(cft_buffer *buf); /* host-visible ptr */
CFT_API cft_status cft_buffer_to_device(cft_buffer *buf);
CFT_API cft_status cft_buffer_from_device(cft_buffer *buf);
CFT_API void       cft_buffer_free(cft_buffer *buf);

/* ---------------------------------------------------------------
 * Programs - the orbit sequencer
 *
 * cft_run applies one operation to every element. A program applies a
 * SEQUENCE to every element, on-chip, without the operands making a
 * round trip to memory between steps - which is the difference
 * between 0.125 flops per byte and something worth putting four
 * compute units behind.
 *
 * This sits beside cft_run rather than replacing it, exactly as
 * docs/HOSTAPI.md said it would. docs/SEQUENCER.md is the design and
 * the instruction encoding; python/cft_golden/seq.py is the
 * definition of correct.
 *
 * A program is a flat byte image - header, constant bank, instruction
 * stream - so it is the same bytes on disk, in this call, and in the
 * device's instruction memory. cft_program_load validates it: a
 * program a device could execute ambiguously is refused here rather
 * than interpreted there.
 * --------------------------------------------------------------- */
typedef struct cft_program cft_program;

/* Sticky status bits, reported through cft_program_run's bus_out.
 * Bits 0..2 are the engine's bus faults and mean the output is not
 * valid; this one does not. A lane that deposits more than the
 * program's max_deposits drops the excess and sets it: what fit is
 * correct and reproducible, and what was lost is the tail. */
#define CFT_STATUS_DEPOSIT_OVERFLOW (1u << 3)

CFT_API cft_status cft_program_load(cft_device *dev, const void *image,
                                    size_t bytes, cft_program **out);
CFT_API void       cft_program_free(cft_program *prog);

/* What the loaded program is, so a caller can size its buffers
 * without parsing the image itself. */
typedef struct cft_program_info {
    size_t     struct_size;    /* in: sizeof; out: bytes filled */
    cft_format format;
    uint32_t   max_deposits;   /* deposit slots per element */
    uint32_t   n_insns;
    uint32_t   n_consts;
} cft_program_info;

CFT_API cft_status cft_program_get_info(cft_program *prog,
                                        cft_program_info *out);

/* Run a program over n elements.
 *
 *   a, b, c    initialise each lane's r0, r1 and r2 - the same three
 *              streams cft_run reads. b and c may be NULL, in which
 *              case those registers start at +0.
 *   deposits   n * max_deposits elements. Every slot is written: one
 *              a lane never deposited into reads as +0, and that is
 *              normative, because a run whose untouched slots kept
 *              whatever the buffer held would not be reproducible.
 *   counts     n deposit counts, or NULL. Needed to tell a deposited
 *              +0 from an untouched slot, which the buffer alone
 *              cannot express.
 *
 * Deposit i,d lands at index i * max_deposits + d, which depends on
 * the element's own index and nothing else - so a run split across
 * four tiles writes the same bytes to the same places as a run on one.
 */
CFT_API cft_status cft_program_run(cft_program *prog,
                                   const void *a, const void *b,
                                   const void *c,
                                   void *deposits, uint32_t *counts,
                                   size_t n,
                                   uint32_t *flags, uint32_t *bus);

/* ---------------------------------------------------------------
 * Conformance
 *
 * Replay the published vector sets through this device and report the
 * first disagreement. This is how a port, a backend, or an independent
 * implementation proves itself - and how you audit ours.
 *
 * dir is the directory holding the .jsonl sets (vectors/out when
 * NULL). Returns CFT_OK when every case matched, CFT_ERR_INTERNAL on a
 * disagreement - which is a bug in this library, since the vectors are
 * the definition - and CFT_ERR_ARTIFACT if no set could be read.
 *
 * report (if non-NULL) is filled in every case, not only on failure:
 * on success it names the sets that ran and the ones skipped because
 * this device lacks the format. A conformance pass that quietly
 * checked nothing would be worse than a failing one, so the summary is
 * not optional.
 * --------------------------------------------------------------- */
CFT_API cft_status cft_conformance(cft_device *dev, const char *dir,
                                   char *report, size_t report_size,
                                   uint64_t *cases_checked);

#ifdef __cplusplus
}  /* extern "C" */
#endif

#endif /* CFT_H */
