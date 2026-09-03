/* Copyright 2026 Logan W.
 * SPDX-License-Identifier: Apache-2.0
 *
 * libcft - the Coordinated Fusion Tile host API.
 *
 * STATUS: the software backend is implemented and is checked against
 * the golden model over the whole interesting input space (see
 * host/tests/). The XRT device backend is implemented behind the same
 * calls (build with CFT_ENABLE_XRT); a build without it reports
 * CFT_ERR_NO_DEVICE from cft_open() with an artifact path.
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
#define CFT_ABI_VERSION_MINOR 5   /* 0.5: the phase-3 radian trig and hyperbolics */

/* Returns (major << 16) | minor of the library actually loaded.
 *
 * The minor version is a floor on what is present, and each step of it
 * is additive: 0.1 was the elementwise opcodes, the reductions and the
 * composed div/sqrt; 0.2 added the clause-5 completion set; 0.3 added
 * the nine correctly-rounded transcendentals below; 0.4 added the
 * eleven trigonometric functions whose argument reduction is exact -
 * sinPi, cosPi, tanPi, asin, acos, atan, atan2 and the four Pi-forms
 * of the inverses. A caller that needs one of those checks the number
 * rather than the header it compiled against. */
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
    CFT_ICMPLT   = 23,  /* unsigned; yields 1.0 or +0.0 */

    /* Reductions: n inputs, ONE output. They take the same opcode
     * space so the device's opcode field stays one field, but they do
     * not share the elementwise calling convention, so they are issued
     * through cft_reduce() and cft_run() refuses them.
     *
     * The tree shape is fixed by element index and is part of the
     * contract, not an implementation detail - see docs/DETERMINISM.md
     * and python/cft_golden/reduce.py, which is the definition. */
    CFT_SUM      = 24,  /* d = sum a[i] */
    CFT_DOT      = 25,  /* d = sum round(a[i] * b[i]) */

    /* Divide/sqrt seeds: quiet table lookups, relative error < 2^-8.5,
     * from which cft_div and cft_sqrt Newton-refine to full precision.
     * Elementwise and unary (b and c ignored), they run through
     * cft_run like any other opcode, raise no flags ever, and ignore
     * the rounding attribute. Exposed rather than hidden inside
     * cft_div because a caller building its own iteration deserves the
     * same starting point the library uses.
     *
     * Special classes give the limit values: seed(NaN) is the
     * canonical quiet NaN, recip_seed of +/-inf is +/-0, rsqrt_seed of
     * a negative is NaN - and ZERO AND EVERY SUBNORMAL give the
     * correspondingly-signed infinity. That last one is deliberate
     * (flush-at-input): a value-based seed on a subnormal would cost
     * hardware that nothing uses, because cft_div and cft_sqrt
     * pre-normalise before seeding. */
    CFT_RECIP_SEED = 26,   /* ~ 1/a   */
    CFT_RSQRT_SEED = 27    /* ~ 1/sqrt(a) */
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
    CFT_FLAG_DIVBYZERO = 1u << 1,   /* raised by cft_div for x/0 */
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
 * An opcode the contract leaves unassigned (15, and 28 upward) is not
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
 * Reductions
 *
 *     d[0] = sum over i in [0, n) of a[i]              CFT_SUM
 *     d[0] = sum over i in [0, n) of round(a[i]*b[i])  CFT_DOT
 *
 * d receives exactly ONE element - cft_format_size(fmt) bytes - not n.
 * That is the whole reason this is a separate entry point: cft_run's
 * promise is that element i of the output depends on element i of the
 * inputs, and a reduction cannot keep it. Issuing CFT_SUM or CFT_DOT
 * through cft_run() is CFT_ERR_INVALID_ARGUMENT rather than a
 * plausible-looking array.
 *
 * b is unused by CFT_SUM and may be NULL.
 *
 * THE TREE SHAPE IS PART OF THE CONTRACT. Results are the fixed
 * binary tree over the index range, evaluated with the given rounding
 * attribute at every node - never a sequential accumulation, never
 * reassociated, never padded to a power of two.
 *
 * A node splits so that its LEFT child is the largest power of two
 * strictly smaller than the range: T(0,5) is add(T(0,4), a[4]). Not
 * the floor midpoint, which is the tidier-looking balanced tree and
 * was the first version of this. The two agree only when n is a power
 * of two, and this one is the shape a streaming binary-counter
 * accumulator produces - which is what the hardware is. Depth is
 * ceil(log2 n) either way, so the accuracy argument for pairwise
 * summation is the same for both.
 *
 * Two conforming implementations therefore return the same bits, and
 * a reduction split across four tiles returns what one tile returns.
 * python/cft_golden/reduce.py is the definition; that shape is why a
 * float reduction can be part of a determinism contract at all.
 *
 * Consequences worth knowing before they surprise you:
 *   n == 0 gives +0.0 and raises nothing.
 *   n == 1 gives a[0] verbatim and raises nothing - one leaf means
 *          zero additions, so not even a signalling NaN is quieted.
 *
 * A device that does not implement the reduction opcode group returns
 * CFT_ERR_UNSUPPORTED; ask cft_supports() to know in advance.
 * --------------------------------------------------------------- */
CFT_API cft_status cft_reduce(cft_device *dev,
                              cft_op      op,
                              cft_format  fmt,
                              cft_round   rnd,
                              const void *a,
                              const void *b,
                              void       *d,
                              size_t      n,
                              uint32_t   *flags_out,
                              uint32_t   *bus_out);

/* ---------------------------------------------------------------
 * Division and square root
 *
 *     d[i] = a[i] / b[i]          cft_div
 *     d[i] = squareRoot(a[i])     cft_sqrt
 *
 * Correctly rounded per IEEE 754-2019 5.4.1, in the caller's rounding
 * attribute, with the contract flags: invalid (sNaN, 0/0, inf/inf,
 * sqrt of a negative), divideByZero (x/0), and inexact / underflow /
 * overflow from the single final rounding. python/cft_golden's div
 * and sqrt are the definition of these bits.
 *
 * These are NOT single opcodes, and that is a fact about the design
 * rather than a gap in it: the tile's divide hardware is the two seed
 * tables (CFT_RECIP_SEED / CFT_RSQRT_SEED) and its FMA. This call
 * composes them - seed, Newton refinement, an exactly-measured
 * residual, one rounding - as a fixed sequence of cft_run steps, the
 * same on every backend. On the software backend that reproduces the
 * contract functions bit for bit; on a device the floating-point
 * steps run on the tile and this library keeps only the exact
 * integer bookkeeping between them, the same division of labour
 * cft_reduce draws when it folds partial sums.
 * python/cft_golden/sequences.py is the sequence's specification and
 * is held bit-identical to the contract by its own test matrix.
 *
 * Because the sequence issues many elementwise runs, each element
 * costs roughly 25-30 opcode passes; this is the price of correct
 * rounding built from an FMA, and it is the same price on every
 * conforming implementation of this route.
 *
 * On a device that can execute sequencer programs (docs/SEQUENCER.md)
 * the same sequence is issued as ONE on-chip program instead - the
 * identical steps over register-resident lanes, so the pass count
 * stands but the per-pass round trip and its memory traffic do not.
 * The choice is automatic and invisible in the results, which the
 * test matrix holds bit-identical across both routes; setting
 * CFT_DIVSQRT_SEQ=0 (or =1) in the environment forces the elementwise
 * (or program) route when a measurement wants one of them
 * specifically.
 *
 * d may alias a or b. b unused by cft_sqrt. A device whose bitstream
 * lacks the seed opcodes (CAPS group bit 6), the arithmetic group or
 * the sign group cannot run the sequence and answers
 * CFT_ERR_UNSUPPORTED; ask cft_supports(dev, CFT_RECIP_SEED, fmt)
 * to know in advance.
 * --------------------------------------------------------------- */
CFT_API cft_status cft_div(cft_device *dev,
                           cft_format  fmt,
                           cft_round   rnd,
                           const void *a,
                           const void *b,
                           void       *d,
                           size_t      n,
                           uint32_t   *flags_out,
                           uint32_t   *bus_out);

CFT_API cft_status cft_sqrt(cft_device *dev,
                            cft_format  fmt,
                            cft_round   rnd,
                            const void *a,
                            void       *d,
                            size_t      n,
                            uint32_t   *flags_out,
                            uint32_t   *bus_out);

/* ---------------------------------------------------------------
 * The remaining clause-5 operations
 *
 * Everything IEEE 754-2019 clause 5 still asked of this library after
 * division and square root landed. python/cft_golden/softfloat.py
 * defines every bit and flag below; none of it needed new hardware,
 * and the entry points say which of two shapes each operation takes:
 *
 *   COMPOSED (cft_rint, cft_scaleb, cft_cmp_sig): the floating-point
 *   work is cft_run() passes - on a device it runs on the tile - with
 *   the host keeping exact integer bookkeeping, like cft_div.
 *   python/cft_golden/sequences.py specifies the routes.
 *
 *   HOST (everything else): no floating-point arithmetic exists in
 *   the operation at all - it is rounding-position bit surgery - so
 *   there is no pass to issue and nothing to accelerate. The device
 *   argument is context; results are bit-identical on every backend
 *   by construction. These do not gate on the device's format mask
 *   for the same reason.
 *
 * Common rules, from the contract: any NaN in yields the canonical
 * quiet NaN out (payloads canonicalise; the documented deviation), a
 * signaling NaN raises invalid except in the non-computational
 * operations (class, totalOrder), which signal nothing ever. Every
 * same-format entry point keeps cft_run's aliasing rule - d may alias
 * a or b, each element read before it is written; cft_convert is the
 * one exception and says so.
 * --------------------------------------------------------------- */

/* roundToIntegral (5.3.1). exact = 0: the five named operations -
 * direction from `rnd`, inexact NEVER signalled. exact != 0:
 * roundToIntegralExact, which signals inexact when the value changed.
 * The zero result keeps the operand's sign: rint(-0.4) is -0.
 * Composed: needs CFT_ADD and CFT_COPYSIGN on the device. */
CFT_API cft_status cft_rint(cft_device *dev, cft_format fmt, cft_round rnd,
                            int exact, const void *a, void *d, size_t n,
                            uint32_t *flags_out, uint32_t *bus_out);

/* scaleB (5.3.3): d[i] = a[i] * 2^nexp, one rounding, full flags.
 * Composed as multiplies by exact powers of two (needs CFT_MUL);
 * |nexp| beyond the subnormal floor takes an equivalent host path. */
CFT_API cft_status cft_scaleb(cft_device *dev, cft_format fmt, cft_round rnd,
                              const void *a, int64_t nexp, void *d, size_t n,
                              uint32_t *flags_out, uint32_t *bus_out);

/* Signaling comparisons (5.6.1): same 1.0/+0.0 predicate values as
 * the quiet opcodes - unordered is false - but invalid is raised for
 * ANY NaN operand, quiet included. cmp selects CFT_CMPLT, CFT_CMPLE
 * or CFT_CMPEQ; greater/greaterEqual are the usual operand swap. */
CFT_API cft_status cft_cmp_sig(cft_device *dev, cft_op cmp, cft_format fmt,
                               const void *a, const void *b, void *d,
                               size_t n, uint32_t *flags_out,
                               uint32_t *bus_out);

/* formatOf-convertFormat (5.4.2), any of the four formats to any
 * other. Widening is exact and silent; narrowing rounds once with
 * full overflow/underflow/inexact; NaNs canonicalise into the
 * destination. d MUST NOT overlap a - elements change size, so
 * in-place conversion is not well defined here. */
CFT_API cft_status cft_convert(cft_device *dev, cft_format sfmt,
                               cft_format dfmt, cft_round rnd,
                               const void *a, void *d, size_t n,
                               uint32_t *flags_out);

/* convertFromInt (5.4.1). Zero converts to +0; inexact where the
 * integer outruns the significand; nothing else can signal. */
CFT_API cft_status cft_cvt_from_i32(cft_device *dev, cft_format fmt,
                                    cft_round rnd, const int32_t *src,
                                    void *d, size_t n, uint32_t *flags_out);
CFT_API cft_status cft_cvt_from_u32(cft_device *dev, cft_format fmt,
                                    cft_round rnd, const uint32_t *src,
                                    void *d, size_t n, uint32_t *flags_out);
CFT_API cft_status cft_cvt_from_i64(cft_device *dev, cft_format fmt,
                                    cft_round rnd, const int64_t *src,
                                    void *d, size_t n, uint32_t *flags_out);
CFT_API cft_status cft_cvt_from_u64(cft_device *dev, cft_format fmt,
                                    cft_round rnd, const uint64_t *src,
                                    void *d, size_t n, uint32_t *flags_out);

/* convertToInteger (5.4.1), direction from `rnd`; exact != 0 selects
 * the ...Exact family, which alone reports inexact. 754 leaves the
 * delivered value of the invalid cases open; determinism cannot, so
 * this contract fixes them to RISC-V's FCVT table: NaN and +inf to
 * the type's maximum, -inf and negative overflow to its minimum, a
 * negative rounded BELOW zero to unsigned 0 - always with invalid,
 * which pre-empts inexact. A negative that rounds TO zero is simply
 * zero. */
CFT_API cft_status cft_cvt_to_i32(cft_device *dev, cft_format fmt,
                                  cft_round rnd, int exact, const void *a,
                                  int32_t *dst, size_t n,
                                  uint32_t *flags_out);
CFT_API cft_status cft_cvt_to_u32(cft_device *dev, cft_format fmt,
                                  cft_round rnd, int exact, const void *a,
                                  uint32_t *dst, size_t n,
                                  uint32_t *flags_out);
CFT_API cft_status cft_cvt_to_i64(cft_device *dev, cft_format fmt,
                                  cft_round rnd, int exact, const void *a,
                                  int64_t *dst, size_t n,
                                  uint32_t *flags_out);
CFT_API cft_status cft_cvt_to_u64(cft_device *dev, cft_format fmt,
                                  cft_round rnd, int exact, const void *a,
                                  uint64_t *dst, size_t n,
                                  uint32_t *flags_out);

/* logB (5.3.3), delivered in the operand's own format. Value-based:
 * a subnormal reports its true exponent. Always exact. logB(0) is
 * -inf and signals divideByZero; logB(+-inf) is +inf, silently. */
CFT_API cft_status cft_logb(cft_device *dev, cft_format fmt, const void *a,
                            void *d, size_t n, uint32_t *flags_out);

/* nextUp / nextDown (5.3.1). One step on the encoding. The edges are
 * the standard's own: nextUp(+-0) is the smallest positive subnormal,
 * nextUp of the most negative subnormal is -0, the largest finite
 * steps to infinity WITHOUT overflow - invalid on sNaN is the only
 * signal these can raise. */
CFT_API cft_status cft_next_up(cft_device *dev, cft_format fmt,
                               const void *a, void *d, size_t n,
                               uint32_t *flags_out);
CFT_API cft_status cft_next_down(cft_device *dev, cft_format fmt,
                                 const void *a, void *d, size_t n,
                                 uint32_t *flags_out);

/* class (5.7.2), one byte per element. The values are RISC-V fclass
 * bit INDICES - one table for anyone porting between the two, the
 * same reasoning that chose frm for the rounding encoding. Every is*
 * predicate of 5.7.2 is a subset test on this byte; isCanonical is
 * constantly true here and radix constantly 2. Non-computational:
 * signals nothing, so there is no flags argument to mislead. */
typedef enum cft_class_value {
    CFT_CLASS_NEG_INF  = 0,
    CFT_CLASS_NEG_NORM = 1,
    CFT_CLASS_NEG_SUB  = 2,
    CFT_CLASS_NEG_ZERO = 3,
    CFT_CLASS_POS_ZERO = 4,
    CFT_CLASS_POS_SUB  = 5,
    CFT_CLASS_POS_NORM = 6,
    CFT_CLASS_POS_INF  = 7,
    CFT_CLASS_SNAN     = 8,
    CFT_CLASS_QNAN     = 9
} cft_class_value;

CFT_API cft_status cft_class(cft_device *dev, cft_format fmt, const void *a,
                             uint8_t *cls, size_t n);

/* totalOrder / totalOrderMag (5.10), as 1.0/+0.0 predicates a SELECT
 * consumes. Defined on the entire encoding space - NaNs ordered by
 * sign, then quiet bit, then payload - and signals nothing on
 * anything, which is what makes it the sort key compareQuiet* cannot
 * be. */
CFT_API cft_status cft_total_order(cft_device *dev, cft_format fmt,
                                   const void *a, const void *b, void *d,
                                   size_t n);
CFT_API cft_status cft_total_order_mag(cft_device *dev, cft_format fmt,
                                       const void *a, const void *b, void *d,
                                       size_t n);

/* remainder (5.3.1): d[i] = a[i] - b[i]*n, n the integer nearest
 * a[i]/b[i], ties to even. EXACT always - no rounding attribute is
 * consumed because none is used, and inexact/overflow/underflow
 * cannot occur. A zero result takes a's sign. remainder(inf, y) and
 * remainder(x, 0) are invalid; remainder(x, inf) is x. The host walks
 * the exponent gap a quotient bit at a time - a handful of steps
 * normally, up to ~524.5k (about ten milliseconds) PER LANE for an
 * adversarial fp256 pair, paid per element over an array - where the
 * model does one unbounded division. */
CFT_API cft_status cft_rem(cft_device *dev, cft_format fmt, const void *a,
                           const void *b, void *d, size_t n,
                           uint32_t *flags_out);

/* ---------------------------------------------------------------
 * The phase-1 transcendental set (ABI 0.3)
 *
 *   d[i] = exp(a[i])        cft_exp        d[i] = log(a[i])    cft_log
 *   d[i] = exp(a[i]) - 1    cft_expm1      d[i] = log(1+a[i])  cft_log1p
 *   d[i] = 2 ** a[i]        cft_exp2       d[i] = log2(a[i])   cft_log2
 *                                          d[i] = log10(a[i])  cft_log10
 *   d[i] = a[i] ** b[i]     cft_pow
 *   d[i] = sqrt(a[i]^2 + b[i]^2)           cft_hypot
 *
 * CORRECTLY ROUNDED, in the caller's attribute, at every format, with
 * exact flags - not "accurate to an ulp", not "faithful", not
 * "algorithm-defined". A result here is defined by the mathematics
 * alone, so every correct implementation agrees bit for bit and this
 * library's answer is checkable against any of them. That is the whole
 * reason these are in a determinism contract at all: an "accurate"
 * transcendental is precisely the thing this project exists to
 * replace, because two of them never agree and neither can be scored.
 * python/cft_golden/transcend.py is the definition;
 * docs/TRANSCENDENTALS.md is the design and its proofs.
 *
 * HOST operations, like most of the clause-5 set: they issue no device
 * pass, so there is no bus word and no bus_out argument, and the
 * device argument is context. That is a design choice with a reason -
 * see docs/TRANSCENDENTALS.md - and not a gap: division composes from
 * the tile's opcodes because it has an exactly measurable residual,
 * and an exponential has none. A tile-assisted fast path for the
 * narrow formats would have to reproduce these bits exactly, and is a
 * later optimisation rather than a different answer.
 *
 * INEXACT is raised for every result except the ones that are exactly
 * representable, and those are decided by exact arithmetic rather than
 * by a tolerance: exp and expm1 are exact only at zero; log and log1p
 * only at 1 and 0; exp2 exactly when the argument is an integer whose
 * power the format holds; log2 exactly at the powers of two; log10
 * exactly at the powers of ten the format represents; pow exactly when
 * the true value is a representable dyadic rational; hypot exactly
 * when x^2 + y^2 is a perfect square. Overflow, underflow and the
 * signed zero follow clause 7 through the same round_pack every
 * arithmetic result uses.
 *
 * The 754-2019 clause 9.2.1 special values apply in full. The ones
 * implementations most often differ on, stated here so a porter does
 * not have to infer them:
 *
 *   exp(-inf) = +0            expm1(-inf) = -1      exp2(-inf) = +0
 *   log(+-0)  = -inf, divideByZero      log(x < 0) = qNaN, invalid
 *   log1p(-1) = -inf, divideByZero      log1p(x < -1) = qNaN, invalid
 *   expm1(+-0) = +-0 and log1p(+-0) = +-0 - the operand's sign, which
 *     is half of why those two functions exist
 *   pow(x, +-0) = 1 for ANY x, including a quiet NaN or an infinity
 *   pow(+1, y)  = 1 for ANY y, including a quiet NaN
 *   pow(-1, +-inf) = 1
 *   pow(x, y) with x finite negative and y a non-integer is invalid
 *   pow(+-0, y) for finite y < 0 signals divideByZero; pow(+-0, -inf)
 *     is +inf and signals NOTHING - that is the |x| < 1 row, and the
 *     divideByZero is the pole at a finite exponent, not the limit
 *   hypot(+-inf, y) = +inf for any y, INCLUDING a quiet NaN
 *
 * A SIGNALING NaN operand is not covered by those rows - 9.2.1's
 * wording is "even a quiet NaN" - so it raises invalid and delivers
 * the canonical quiet NaN, exactly as every other operation in this
 * contract does. That differs from C's pow(sNaN, 0), and the
 * difference is deliberate and documented rather than accidental.
 *
 * If an input cannot be shown correctly rounded within the library's
 * working-precision cap, the call returns CFT_ERR_INTERNAL and writes
 * nothing useful to d. It does not return a plausible number. The cap
 * is sized so that no input the formats can express should reach it
 * (docs/TRANSCENDENTALS.md does that arithmetic); if one ever does,
 * that is a bug worth a report, and a status is how you would find
 * out.
 *
 * d may alias a or b: each element is read before it is written.
 * --------------------------------------------------------------- */
CFT_API cft_status cft_exp(cft_device *dev, cft_format fmt, cft_round rnd,
                           const void *a, void *d, size_t n,
                           uint32_t *flags_out);
CFT_API cft_status cft_expm1(cft_device *dev, cft_format fmt, cft_round rnd,
                             const void *a, void *d, size_t n,
                             uint32_t *flags_out);
CFT_API cft_status cft_exp2(cft_device *dev, cft_format fmt, cft_round rnd,
                            const void *a, void *d, size_t n,
                            uint32_t *flags_out);
CFT_API cft_status cft_log(cft_device *dev, cft_format fmt, cft_round rnd,
                           const void *a, void *d, size_t n,
                           uint32_t *flags_out);
CFT_API cft_status cft_log1p(cft_device *dev, cft_format fmt, cft_round rnd,
                             const void *a, void *d, size_t n,
                             uint32_t *flags_out);
CFT_API cft_status cft_log2(cft_device *dev, cft_format fmt, cft_round rnd,
                            const void *a, void *d, size_t n,
                            uint32_t *flags_out);
CFT_API cft_status cft_log10(cft_device *dev, cft_format fmt, cft_round rnd,
                             const void *a, void *d, size_t n,
                             uint32_t *flags_out);

/* b[i] is the exponent for cft_pow and the second leg for cft_hypot;
 * neither may be NULL. */
CFT_API cft_status cft_pow(cft_device *dev, cft_format fmt, cft_round rnd,
                           const void *a, const void *b, void *d, size_t n,
                           uint32_t *flags_out);
CFT_API cft_status cft_hypot(cft_device *dev, cft_format fmt, cft_round rnd,
                             const void *a, const void *b, void *d, size_t n,
                             uint32_t *flags_out);

/* ---------------------------------------------------------------
 * The phase-2 trigonometric set (ABI 0.4)
 *
 *   d[i] = sin(pi*a[i])     cft_sinpi      d[i] = asin(a[i])   cft_asin
 *   d[i] = cos(pi*a[i])     cft_cospi      d[i] = acos(a[i])   cft_acos
 *   d[i] = tan(pi*a[i])     cft_tanpi      d[i] = atan(a[i])   cft_atan
 *   d[i] = asin(a[i])/pi    cft_asinpi     d[i] = atan2(a[i], b[i])
 *   d[i] = acos(a[i])/pi    cft_acospi                         cft_atan2
 *   d[i] = atan(a[i])/pi    cft_atanpi     d[i] = atan2(a,b)/pi
 *                                                            cft_atan2pi
 *
 * CORRECTLY ROUNDED, in the caller's attribute, at every format, with
 * exact flags, on the same terms as the nine above: the mathematics
 * defines the bits, so every correct implementation agrees.
 *
 * WHAT THESE ELEVEN HAVE IN COMMON is what they do NOT need: an
 * argument reduction against pi. sinPi's reduction is x mod 2, and
 * every operand is a dyadic rational, so that reduction is a mask on
 * the encoding and is exact at every magnitude - sinPi of the largest
 * finite binary256 is a zero decided by integer arithmetic. The
 * inverse functions take an argument in [-1, 1] or a ratio and meet pi
 * only as a factor of the answer. `sin`, `cos` and `tan` of a RADIAN
 * argument are a different problem and are not here.
 *
 * HOST operations, like the nine: no device pass, no bus word, the
 * device argument is context, `d` may alias `a` or `b`.
 *
 * INEXACT is raised for every result except the exact ones, and the
 * exact ones are an enumeration with a proof behind it rather than a
 * tolerance. Niven's theorem bounds the forward set: sin(pi r) is
 * rational for a rational r only at 0, +-1/2 and +-1, and a dyadic r
 * cannot reach +-1/2 - so sinPi and cosPi are exact exactly at the
 * half-integers and tanPi exactly at the quarter-integers.
 * Hermite-Lindemann bounds the inverse set: asin, atan and atan2 of a
 * nonzero dyadic rational are transcendental, so those are exact only
 * where the answer is a zero, and acos only at acos(1) = +0. The
 * Pi-forms get a much larger table for Niven's reason:
 *
 *   asinPi(+-0) = +-0      asinPi(+-1) = +-1/2
 *   acosPi(1)   = +0       acosPi(+-0) = 1/2       acosPi(-1) = 1
 *   atanPi(+-0) = +-0      atanPi(+-1) = +-1/4     atanPi(+-inf) = +-1/2
 *   atan2Pi on every axis and diagonal: 0, +-1/4, +-1/2, +-3/4, +-1
 *
 * while asinPi(1/2) is exactly 1/6 - rational, but NOT a dyadic
 * rational, so it is inexact and still decidable.
 *
 * The 754-2019 clause 9.2.1 special values apply in full. The rows a
 * porter should not have to infer, each confirmed against MPFR 4.2.2:
 *
 *   sinPi(+-0) = +-0, and sinPi of an integer n is a zero with the
 *     sign of the ARGUMENT: sinPi(1) = +0, sinPi(-1) = -0
 *   cosPi(+-0) = 1, cosPi(n) = (-1)^n, cosPi(n + 1/2) = +0 for every n
 *     and both signs - cosPi is even, so that zero has no sign to carry
 *   tanPi is sinPi/cosPi in every respect: tanPi(1) = -0, and tanPi at
 *     a half-integer is +-infinity with divideByZero (7.3's rule for an
 *     exact infinity from finite operands)
 *   tanPi cannot overflow at any format here: a representable argument
 *     is at least 2^-p from a pole, so |tanPi| stays below 2^p
 *   sinPi/cosPi/tanPi of an infinity is invalid - there is no limit
 *   asin, acos, asinPi and acosPi of an operand with |x| > 1 are
 *     invalid, infinities included
 *   atan2(+-0, -0) = +-pi and atan2Pi(+-0, -0) = +-1: a MINUS zero
 *     denominator names the negative real axis, so the answer is pi
 *     and not zero. That is the row implementations most often miss
 *   atan2(+-0, +0) = +-0; atan2(y, +-0) = +-pi/2; atan2(+-inf, +inf)
 *     = +-pi/4 and (+-inf, -inf) = +-3pi/4
 *   a quiet NaN operand does NOT outrank this table the way it does
 *     pow's: atan2 of a NaN is a NaN
 *
 * Overflow cannot occur anywhere in this set. Underflow can, and comes
 * through the same round_pack as everything else: sinPi of a tiny x is
 * about pi*x and atanPi of one is about x/pi, and both land subnormal.
 *
 * A SIGNALING NaN raises invalid and delivers the canonical quiet NaN,
 * as everywhere else in this contract.
 *
 * If an input cannot be shown correctly rounded within the working
 * precision cap the call returns CFT_ERR_INTERNAL, never a plausible
 * number. docs/TRANSCENDENTALS.md is the design and its proofs.
 * --------------------------------------------------------------- */
CFT_API cft_status cft_sinpi(cft_device *dev, cft_format fmt, cft_round rnd,
                             const void *a, void *d, size_t n,
                             uint32_t *flags_out);
CFT_API cft_status cft_cospi(cft_device *dev, cft_format fmt, cft_round rnd,
                             const void *a, void *d, size_t n,
                             uint32_t *flags_out);
CFT_API cft_status cft_tanpi(cft_device *dev, cft_format fmt, cft_round rnd,
                             const void *a, void *d, size_t n,
                             uint32_t *flags_out);
CFT_API cft_status cft_asin(cft_device *dev, cft_format fmt, cft_round rnd,
                            const void *a, void *d, size_t n,
                            uint32_t *flags_out);
CFT_API cft_status cft_acos(cft_device *dev, cft_format fmt, cft_round rnd,
                            const void *a, void *d, size_t n,
                            uint32_t *flags_out);
CFT_API cft_status cft_atan(cft_device *dev, cft_format fmt, cft_round rnd,
                            const void *a, void *d, size_t n,
                            uint32_t *flags_out);
CFT_API cft_status cft_asinpi(cft_device *dev, cft_format fmt, cft_round rnd,
                              const void *a, void *d, size_t n,
                              uint32_t *flags_out);
CFT_API cft_status cft_acospi(cft_device *dev, cft_format fmt, cft_round rnd,
                              const void *a, void *d, size_t n,
                              uint32_t *flags_out);
CFT_API cft_status cft_atanpi(cft_device *dev, cft_format fmt, cft_round rnd,
                              const void *a, void *d, size_t n,
                              uint32_t *flags_out);

/* a[i] is y and b[i] is x - the C order, y first, because that is what
 * every caller of atan2 expects; neither may be NULL. */
CFT_API cft_status cft_atan2(cft_device *dev, cft_format fmt, cft_round rnd,
                             const void *a, const void *b, void *d, size_t n,
                             uint32_t *flags_out);
CFT_API cft_status cft_atan2pi(cft_device *dev, cft_format fmt,
                               cft_round rnd, const void *a, const void *b,
                               void *d, size_t n, uint32_t *flags_out);

/* ---------------------------------------------------------------
 * The phase-3 radian trigonometry and the hyperbolics (ABI 0.5)
 *
 *   d[i] = sin  a[i]      d[i] = sinh  a[i]      d[i] = asinh a[i]
 *   d[i] = cos  a[i]      d[i] = cosh  a[i]      d[i] = acosh a[i]
 *   d[i] = tan  a[i]      d[i] = tanh  a[i]      d[i] = atanh a[i]
 *
 * CORRECTLY ROUNDED at every format under every attribute, with clause
 * 9.2.1's special values and exact flags, on exactly the terms the
 * twenty above are. **The argument of sin, cos and tan is in RADIANS**;
 * cft_sinpi and friends are the same functions of a half-turn and are
 * a different, cheaper problem.
 *
 * WHAT THESE NINE NEEDED THAT THE TWENTY DID NOT. One thing, and only
 * the first three need it: `x mod (pi/2)` for an argument as large as
 * 2^262143. That is a Payne-Hanek reduction against a stored 2/pi of
 * 270,336 bits (host/src/mp_2opi.h, generated, never transcribed), and
 * the cancellation it has to survive is a MEASUREMENT rather than a
 * theorem - the irrationality measure of pi is far too weak to bound it
 * usefully at this exponent range. The reduction measures the
 * cancellation from the bits it has and widens its window until the
 * working precision is covered; past what the stored constant covers it
 * REFUSES with CFT_ERR_INTERNAL, as everything else in this contract
 * does rather than return a plausible number.
 *
 * The six hyperbolics need no reduction and no new constant: they are
 * exp and log in different clothes, in the cancellation-free forms
 * phase 1 already justifies.
 *
 * HOST operations, like the twenty: no cft_run pass is issued, no bus
 * word is produced, `dev` is context, `d` may alias `a`, `n` is
 * arbitrary and the flag word is the OR across the batch.
 *
 * THE EXACT CASES ARE THE ZEROS, AND THAT IS A THEOREM. By
 * Hermite-Lindemann, e^z is transcendental for every nonzero algebraic
 * z; sin(x) = a algebraic makes e^(ix) a root of z^2 - 2iaz - 1, and
 * sinh(x) = a makes e^x a root of z^2 - 2az - 1, so both force x = 0.
 * Every operand here is a dyadic rational, hence algebraic. So:
 *
 *   sin, tan, sinh, tanh, asinh, atanh   exact only at +-0, giving +-0
 *   cos, cosh                            exact only at 0, giving 1
 *   acosh                                exact only at 1, giving +0
 *
 * and EVERY other result is inexact. There is no half-integer table
 * here the way there is for sinPi: an odd multiple of pi/2 is
 * irrational, so no representable argument is ever a zero of cos or a
 * pole of tan.
 *
 * Rows a porter should not have to infer:
 *
 *   - sin, cos and tan of an INFINITY are invalid: no limit exists.
 *   - `tanh(+-inf) = +-1`, EXACTLY, raising nothing. It is a limit that
 *     happens to be representable.
 *   - `atanh(+-1) = +-infinity` with **divideByZero** - 754-2019 7.3's
 *     rule for an exact infinity from finite operands, the same row
 *     tanPi takes at a pole - and `|x| > 1` is invalid, infinities
 *     included.
 *   - `acosh(x)` for any x below 1 is invalid: zeros, every negative
 *     value, and -infinity. `acosh(+inf)` is +infinity.
 *   - sinh and cosh OVERFLOW for a large argument, through round_pack
 *     like any other overflow, so roundTowardZero delivers maxfinite.
 *     tan can overflow too, near a pole; sin, cos, tanh, asinh, acosh
 *     and atanh cannot.
 *   - UNDERFLOW happens for sin, tan, sinh, asinh, atanh and tanh of a
 *     tiny argument and follows clause 7 through the same round_pack.
 *   - A signaling NaN raises invalid and delivers the canonical quiet
 *     NaN, as everywhere else in this contract.
 *
 * docs/TRANSCENDENTALS.md's phase-3 section is the design, the
 * reduction's error bound, and the measured cancellation per format.
 * --------------------------------------------------------------- */
CFT_API cft_status cft_sin(cft_device *dev, cft_format fmt, cft_round rnd,
                           const void *a, void *d, size_t n,
                           uint32_t *flags_out);
CFT_API cft_status cft_cos(cft_device *dev, cft_format fmt, cft_round rnd,
                           const void *a, void *d, size_t n,
                           uint32_t *flags_out);
CFT_API cft_status cft_tan(cft_device *dev, cft_format fmt, cft_round rnd,
                           const void *a, void *d, size_t n,
                           uint32_t *flags_out);
CFT_API cft_status cft_sinh(cft_device *dev, cft_format fmt, cft_round rnd,
                            const void *a, void *d, size_t n,
                            uint32_t *flags_out);
CFT_API cft_status cft_cosh(cft_device *dev, cft_format fmt, cft_round rnd,
                            const void *a, void *d, size_t n,
                            uint32_t *flags_out);
CFT_API cft_status cft_tanh(cft_device *dev, cft_format fmt, cft_round rnd,
                            const void *a, void *d, size_t n,
                            uint32_t *flags_out);
CFT_API cft_status cft_asinh(cft_device *dev, cft_format fmt, cft_round rnd,
                             const void *a, void *d, size_t n,
                             uint32_t *flags_out);
CFT_API cft_status cft_acosh(cft_device *dev, cft_format fmt, cft_round rnd,
                             const void *a, void *d, size_t n,
                             uint32_t *flags_out);
CFT_API cft_status cft_atanh(cft_device *dev, cft_format fmt, cft_round rnd,
                             const void *a, void *d, size_t n,
                             uint32_t *flags_out);

/* ---------------------------------------------------------------
 * The rest of IEEE 754-2019 table 9.1 (part of the 0.6 step)
 *
 *   d[i] = 2^a[i] - 1        d[i] = log2(1 + a[i])    d[i] = 1/sqrt(a[i])
 *   d[i] = 10^a[i]           d[i] = log10(1 + a[i])
 *   d[i] = 10^a[i] - 1
 *
 *   d[i] = a[i]^n[i]         (pown)      d[i] = a[i]^b[i]   (powr)
 *   d[i] = (1 + a[i])^n[i]   (compound)  d[i] = a[i]^(1/n[i]) (rootn)
 *
 * With these ten the library implements every operation table 9.1
 * lists for the binary formats. CORRECTLY ROUNDED at every format
 * under every attribute, with clause 9.2.1's special values and exact
 * flags, on exactly the terms the twenty-nine above are. HOST
 * operations, like all of them: no cft_run pass, no bus word, `dev` is
 * context, `d` may alias `a`, and the flag word is the OR across the
 * batch.
 *
 * WHAT IS NEW IS EXACTNESS, NOT MACHINERY. There is no new reduction
 * and no constant beyond the ln 10 and log10 e phase 1 already
 * generates. What each of these has is a LARGER exact-case table than
 * the function it is built from, and each table is proved closed in
 * docs/TRANSCENDENTALS.md before the Ziv loop under it is allowed to
 * run - a true value sitting on a rounding boundary is exactly where
 * that loop does not terminate:
 *
 *   exp2m1    EXACT at every integer argument: 2^n - 1 is a dyadic
 *             rational for every n, and a rounding boundary while
 *             |n| <= p+1. Past that the value is still known exactly
 *             and is delivered by a SIDE - 2^n - 1 sits in the top
 *             quarter of the gap below 2^n, and -(1 - 2^n) in the half
 *             gap above -1.
 *   exp10     EXACT at the non-negative integers whose 5^n fits in p+1
 *             bits. A negative power of ten is not dyadic at all.
 *   exp10m1   EXACT at the non-negative integers whose 10^n - 1 (odd,
 *             so its own odd part) fits in p+1 bits.
 *   log2p1    EXACT where 1 + x is a power of two; log10p1 where it is
 *             a power of ten. 1 + x is formed EXACTLY on the encoding
 *             and never as a rounded sum, which is the whole reason
 *             these functions exist.
 *   rSqrt     EXACT exactly at the even powers of two, and it can
 *             neither overflow nor underflow at any rung.
 *   pown      pow's dyadic analysis with an integer exponent.
 *   powr      the same with a non-negative base, so no sign question.
 *   compound  1 + x exactly, then pown's procedure on it.
 *   rootn     EXACT when the odd significand is a perfect |n|-th power
 *             and |n| divides the exponent - one verified integer root.
 *
 * THE INTEGER OPERAND. 9.2.1 says "n is a finite integral value in
 * integralFormat", so pown, compound and rootn take an `int64_t`
 * array beside the encoding array rather than a second encoding that
 * would have to be asked whether it is integral. That moves the
 * element count to `count`; `n` is the exponent array, one per
 * element, and must not be NULL.
 *
 * Rows a porter should not have to infer, every one of them confirmed
 * against MPFR 4.2.2 before it was written down:
 *
 *   - rSqrt(+-0) is +-INFINITY with divideByZero. The sign SURVIVES:
 *     rSqrt(-0) is -infinity. GNU MPFR's mpfr_rec_sqrt returns +inf
 *     for both zeros; the standard's row is +-inf and this contract
 *     follows the standard.
 *   - powr is NOT pow. powr(x, y) for x < 0 is invalid for EVERY y, a
 *     NaN included; powr(+-0, +-0), powr(+inf, +-0) and powr(+1, +-inf)
 *     are invalid; and powr(qNaN, y) is a quiet NaN where pow(qNaN, 0)
 *     is 1. powr(+1, qNaN) is a quiet NaN here - the standard's row is
 *     "powr(+1, y) is 1 for FINITE y" and it lists powr(x, qNaN) for
 *     x >= 0 separately - where mpfr_powr returns 1.
 *   - pown(x, 0) is 1 for any x that is not a signaling NaN, an
 *     infinity and a quiet NaN included.
 *   - compound(x, 0) is 1 "for x >= -1 or quiet NaN", so compound of an
 *     x BELOW -1 with n = 0 is invalid rather than 1. compound(-1, n)
 *     is +infinity with divideByZero for n < 0 and +0 for n > 0;
 *     compound(+-0, n) is 1.
 *   - rootn(x, 0) is invalid: zero is outside the domain for every x.
 *     rootn(x, 1) is x, exactly and silently. rootn(x, 2) is
 *     squareRoot(x) on every input EXCEPT x = -0, where the standard's
 *     own NOTE says they differ: rootn(-0, 2) is +0 by the even-n row
 *     where squareRoot(-0) is -0.
 *   - log2p1(-1) and log10p1(-1) are -infinity with divideByZero, and
 *     an operand below -1 is invalid.
 *   - A signaling NaN raises invalid and delivers the canonical quiet
 *     NaN, as everywhere else in this contract.
 *
 * docs/TRANSCENDENTALS.md's "Table 9.1, completed" section is the
 * design, the exact-case proofs and the neighbour-rule derivations -
 * including which functions get NO neighbour rule and why.
 * --------------------------------------------------------------- */
CFT_API cft_status cft_exp2m1(cft_device *dev, cft_format fmt, cft_round rnd,
                              const void *a, void *d, size_t n,
                              uint32_t *flags_out);
CFT_API cft_status cft_exp10(cft_device *dev, cft_format fmt, cft_round rnd,
                             const void *a, void *d, size_t n,
                             uint32_t *flags_out);
CFT_API cft_status cft_exp10m1(cft_device *dev, cft_format fmt,
                               cft_round rnd, const void *a, void *d,
                               size_t n, uint32_t *flags_out);
CFT_API cft_status cft_log2p1(cft_device *dev, cft_format fmt, cft_round rnd,
                              const void *a, void *d, size_t n,
                              uint32_t *flags_out);
CFT_API cft_status cft_log10p1(cft_device *dev, cft_format fmt,
                               cft_round rnd, const void *a, void *d,
                               size_t n, uint32_t *flags_out);
CFT_API cft_status cft_rsqrt(cft_device *dev, cft_format fmt, cft_round rnd,
                             const void *a, void *d, size_t n,
                             uint32_t *flags_out);

/* x**y on [0, +inf] x [-inf, +inf], two encodings like pow. */
CFT_API cft_status cft_powr(cft_device *dev, cft_format fmt, cft_round rnd,
                            const void *a, const void *b, void *d, size_t n,
                            uint32_t *flags_out);

/* The three with an INTEGER exponent. `n` is the per-element exponent
 * array and `count` the number of elements - the one place in this
 * header where those two names are not the same argument. */
CFT_API cft_status cft_pown(cft_device *dev, cft_format fmt, cft_round rnd,
                            const void *a, const int64_t *n, void *d,
                            size_t count, uint32_t *flags_out);
CFT_API cft_status cft_compound(cft_device *dev, cft_format fmt,
                                cft_round rnd, const void *a,
                                const int64_t *n, void *d, size_t count,
                                uint32_t *flags_out);
CFT_API cft_status cft_rootn(cft_device *dev, cft_format fmt, cft_round rnd,
                             const void *a, const int64_t *n, void *d,
                             size_t count, uint32_t *flags_out);

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
 * valid; bit 3 is the trimmed-build precision refusal - which is why
 * this one moved to bit 4 on 2026-09-01, before any device had ever
 * reported it. It does NOT invalidate the output: a lane that
 * deposits more than the program's max_deposits drops the excess and
 * sets it - what fit is correct and reproducible, and what was lost
 * is the tail. */
#define CFT_STATUS_DEPOSIT_OVERFLOW (1u << 4)

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
