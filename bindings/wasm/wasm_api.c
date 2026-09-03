/* Copyright 2026 Logan W.
 * SPDX-License-Identifier: Apache-2.0
 *
 * libcft's C ABI, re-exported for WebAssembly.
 *
 * This file invents nothing. Every export is a projection of one
 * declaration in host/include/cft.h, and cft.h remains the contract:
 * the comments there govern, the wrappers here only adapt calling
 * conventions a JavaScript caller cannot reach directly - out-params
 * that want a pointer-to-pointer, a sized struct, a uint64_t. Where
 * no adaptation is needed the wrapper is a plain passthrough, kept
 * anyway so the page calls exactly one namespace (cftw_*) and this
 * file is the complete list of what the wasm module exposes.
 *
 * Why the software backend is the only device here: wasm32 has no
 * XRT, no PCIe and no tile - and does not need one for the claim this
 * build exists to make. The backend's arithmetic is integer-only
 * (uint32 limbs, uint64 intermediates; see host/src/bigint.c), and
 * WebAssembly's integer semantics are fully specified, so the bits
 * this module returns are the library's bits by construction. No
 * float-determinism caveat applies, because no host float is ever
 * consulted.
 */

#include <stdint.h>
#include <string.h>

#include <emscripten/emscripten.h>

#include "cft.h"

#define WASM_EXPORT EMSCRIPTEN_KEEPALIVE

/* ---- identity ---------------------------------------------------- */

WASM_EXPORT uint32_t cftw_abi_version(void)
{
    return cft_abi_version();
}

WASM_EXPORT const char *cftw_strerror(int s)
{
    return cft_strerror((cft_status)s);
}

WASM_EXPORT const char *cftw_last_error(void)
{
    return cft_last_error();
}

WASM_EXPORT uint32_t cftw_format_size(int f)
{
    return (uint32_t)cft_format_size((cft_format)f);
}

WASM_EXPORT const char *cftw_format_name(int f)
{
    return cft_format_name((cft_format)f);
}

WASM_EXPORT const char *cftw_op_name(int op)
{
    return cft_op_name((cft_op)op);
}

/* ---- devices ----------------------------------------------------- */

/* cft_open with the NULL artifact: the software backend, the only one
 * a browser can be. The device pointer lands in *out (4 bytes on
 * wasm32); the return value is the cft_status. */
WASM_EXPORT int cftw_open_software(cft_device **out)
{
    return (int)cft_open(NULL, 0, out);
}

WASM_EXPORT void cftw_close(cft_device *dev)
{
    cft_close(dev);
}

WASM_EXPORT int cftw_supports(cft_device *dev, int op, int fmt)
{
    return cft_supports(dev, (cft_op)op, (cft_format)fmt);
}

/* cft_get_caps, one field per call rather than one struct per call.
 * A JS caller reading struct offsets out of the heap is exactly the
 * silent ABI coupling the size handshake in cft.h exists to prevent;
 * these accessors keep the layout private to C. Each performs the
 * full handshake and projects one field. */

static int caps_of(cft_device *dev, cft_caps *c)
{
    memset(c, 0, sizeof *c);
    c->struct_size = sizeof *c;
    return (int)cft_get_caps(dev, c);
}

WASM_EXPORT uint32_t cftw_caps_format_mask(cft_device *dev)
{
    cft_caps c;
    return caps_of(dev, &c) == CFT_OK ? c.format_mask : 0u;
}

WASM_EXPORT uint32_t cftw_caps_tiles(cft_device *dev)
{
    cft_caps c;
    return caps_of(dev, &c) == CFT_OK ? c.tiles : 0u;
}

WASM_EXPORT uint32_t cftw_caps_abi_version(cft_device *dev)
{
    cft_caps c;
    return caps_of(dev, &c) == CFT_OK ? c.abi_version : 0u;
}

WASM_EXPORT int cftw_caps_flags_readable(cft_device *dev)
{
    cft_caps c;
    return caps_of(dev, &c) == CFT_OK ? c.flags_readable : 0;
}

WASM_EXPORT const char *cftw_caps_backend(cft_device *dev)
{
    static char backend[32];
    cft_caps c;
    if (caps_of(dev, &c) != CFT_OK)
        return "";
    memcpy(backend, c.backend, sizeof backend);
    backend[sizeof backend - 1] = '\0';
    return backend;
}

/* ---- the work ---------------------------------------------------- *
 *
 * Buffers are plain heap pointers (Module._malloc from JS), dense
 * little-endian elements of cftw_format_size(fmt) bytes, exactly as
 * cft.h specifies. n is uint32_t because wasm32's size_t is. Every
 * argument passes straight through, bus_out included - the software
 * backend never raises a bus fault, but trimming the parameter would
 * make this a different signature than the one the contract
 * documents. */

WASM_EXPORT int cftw_run(cft_device *dev, int op, int fmt, int rnd,
                         const void *a, const void *b, const void *c,
                         void *d, uint32_t n,
                         uint32_t *flags_out, uint32_t *bus_out)
{
    return (int)cft_run(dev, (cft_op)op, (cft_format)fmt, (cft_round)rnd,
                        a, b, c, d, (size_t)n, flags_out, bus_out);
}

WASM_EXPORT int cftw_reduce(cft_device *dev, int op, int fmt, int rnd,
                            const void *a, const void *b,
                            void *d, uint32_t n,
                            uint32_t *flags_out, uint32_t *bus_out)
{
    return (int)cft_reduce(dev, (cft_op)op, (cft_format)fmt, (cft_round)rnd,
                           a, b, d, (size_t)n, flags_out, bus_out);
}

WASM_EXPORT int cftw_div(cft_device *dev, int fmt, int rnd,
                         const void *a, const void *b, void *d, uint32_t n,
                         uint32_t *flags_out, uint32_t *bus_out)
{
    return (int)cft_div(dev, (cft_format)fmt, (cft_round)rnd,
                        a, b, d, (size_t)n, flags_out, bus_out);
}

WASM_EXPORT int cftw_sqrt(cft_device *dev, int fmt, int rnd,
                          const void *a, void *d, uint32_t n,
                          uint32_t *flags_out, uint32_t *bus_out)
{
    return (int)cft_sqrt(dev, (cft_format)fmt, (cft_round)rnd,
                         a, d, (size_t)n, flags_out, bus_out);
}

/* ---- conformance ------------------------------------------------- *
 *
 * The page writes .jsonl sets into MEMFS under the generator's fixed
 * names and hands the directory here, so the replay in the browser is
 * the library's own cft_conformance() - the same parser, the same
 * per-element pass, the same array pass, the same refusal to let an
 * empty directory read as a pass - not a JavaScript reimplementation
 * of it. cases_checked is a uint64_t in the contract; JS reads the
 * heap in 32-bit words, so it comes back split. */

WASM_EXPORT int cftw_conformance(cft_device *dev, const char *dir,
                                 char *report, uint32_t report_size,
                                 uint32_t *cases_lo, uint32_t *cases_hi)
{
    uint64_t cases = 0;
    int st = (int)cft_conformance(dev, dir, report, (size_t)report_size,
                                  &cases);
    if (cases_lo)
        *cases_lo = (uint32_t)(cases & 0xffffffffu);
    if (cases_hi)
        *cases_hi = (uint32_t)(cases >> 32);
    return st;
}

/* ---- the rest of clause 5 (ABI 0.2) ------------------------------ *
 *
 * Added 2026-09-02, with the source-list fix that made clause5.c part
 * of this build at all. The module reports its ABI version from the
 * library it was compiled from, so a wasm build that answered
 * cftw_abi_version() with 0.2 while exporting none of the operations
 * 0.2 IS would have been telling a true sentence in a misleading way.
 * These wrappers close that: every clause-5 entry point in cft.h has
 * one here, same order, same arguments, adapting only size_t (uint32
 * on wasm32) and the one int64_t that has to cross as two halves.
 *
 * The conformance page calls none of them - it replays vectors, which
 * cover cft_run's opcode space - so nothing on the page changes. They
 * are here for callers of the module: bindings/node, and anyone who
 * loads it directly.
 */

WASM_EXPORT int cftw_rint(cft_device *dev, int fmt, int rnd, int exact,
                          const void *a, void *d, uint32_t n,
                          uint32_t *flags_out, uint32_t *bus_out)
{
    return (int)cft_rint(dev, (cft_format)fmt, (cft_round)rnd, exact,
                         a, d, (size_t)n, flags_out, bus_out);
}

/* nexp is int64_t in the contract. Without -sWASM_BIGINT a wasm i64
 * cannot cross into JS at all, so it crosses as two 32-bit halves and
 * is reassembled here - the same split cftw_conformance uses for
 * cases_checked, in the other direction. */
WASM_EXPORT int cftw_scaleb(cft_device *dev, int fmt, int rnd,
                            const void *a, uint32_t nexp_lo, int32_t nexp_hi,
                            void *d, uint32_t n,
                            uint32_t *flags_out, uint32_t *bus_out)
{
    int64_t nexp = (int64_t)(((uint64_t)(uint32_t)nexp_hi << 32) |
                             (uint64_t)nexp_lo);
    return (int)cft_scaleb(dev, (cft_format)fmt, (cft_round)rnd, a, nexp,
                           d, (size_t)n, flags_out, bus_out);
}

WASM_EXPORT int cftw_cmp_sig(cft_device *dev, int cmp, int fmt,
                             const void *a, const void *b, void *d,
                             uint32_t n, uint32_t *flags_out,
                             uint32_t *bus_out)
{
    return (int)cft_cmp_sig(dev, (cft_op)cmp, (cft_format)fmt, a, b, d,
                            (size_t)n, flags_out, bus_out);
}

/* d must not overlap a here - elements change size. cft.h says so;
 * this wrapper does not restate the rule, it just does not break it. */
WASM_EXPORT int cftw_convert(cft_device *dev, int sfmt, int dfmt, int rnd,
                             const void *a, void *d, uint32_t n,
                             uint32_t *flags_out)
{
    return (int)cft_convert(dev, (cft_format)sfmt, (cft_format)dfmt,
                            (cft_round)rnd, a, d, (size_t)n, flags_out);
}

/* convertFromInt / convertToInteger. The integer arrays are plain
 * heap pointers of the named element type: JS builds them with
 * Int32Array / BigInt64Array views over the module's memory, which is
 * where the 64-bit families stay callable without WASM_BIGINT - the
 * i64s live in memory, never in a parameter. */

WASM_EXPORT int cftw_cvt_from_i32(cft_device *dev, int fmt, int rnd,
                                  const int32_t *src, void *d, uint32_t n,
                                  uint32_t *flags_out)
{
    return (int)cft_cvt_from_i32(dev, (cft_format)fmt, (cft_round)rnd,
                                 src, d, (size_t)n, flags_out);
}

WASM_EXPORT int cftw_cvt_from_u32(cft_device *dev, int fmt, int rnd,
                                  const uint32_t *src, void *d, uint32_t n,
                                  uint32_t *flags_out)
{
    return (int)cft_cvt_from_u32(dev, (cft_format)fmt, (cft_round)rnd,
                                 src, d, (size_t)n, flags_out);
}

WASM_EXPORT int cftw_cvt_from_i64(cft_device *dev, int fmt, int rnd,
                                  const int64_t *src, void *d, uint32_t n,
                                  uint32_t *flags_out)
{
    return (int)cft_cvt_from_i64(dev, (cft_format)fmt, (cft_round)rnd,
                                 src, d, (size_t)n, flags_out);
}

WASM_EXPORT int cftw_cvt_from_u64(cft_device *dev, int fmt, int rnd,
                                  const uint64_t *src, void *d, uint32_t n,
                                  uint32_t *flags_out)
{
    return (int)cft_cvt_from_u64(dev, (cft_format)fmt, (cft_round)rnd,
                                 src, d, (size_t)n, flags_out);
}

WASM_EXPORT int cftw_cvt_to_i32(cft_device *dev, int fmt, int rnd, int exact,
                                const void *a, int32_t *dst, uint32_t n,
                                uint32_t *flags_out)
{
    return (int)cft_cvt_to_i32(dev, (cft_format)fmt, (cft_round)rnd, exact,
                               a, dst, (size_t)n, flags_out);
}

WASM_EXPORT int cftw_cvt_to_u32(cft_device *dev, int fmt, int rnd, int exact,
                                const void *a, uint32_t *dst, uint32_t n,
                                uint32_t *flags_out)
{
    return (int)cft_cvt_to_u32(dev, (cft_format)fmt, (cft_round)rnd, exact,
                               a, dst, (size_t)n, flags_out);
}

WASM_EXPORT int cftw_cvt_to_i64(cft_device *dev, int fmt, int rnd, int exact,
                                const void *a, int64_t *dst, uint32_t n,
                                uint32_t *flags_out)
{
    return (int)cft_cvt_to_i64(dev, (cft_format)fmt, (cft_round)rnd, exact,
                               a, dst, (size_t)n, flags_out);
}

WASM_EXPORT int cftw_cvt_to_u64(cft_device *dev, int fmt, int rnd, int exact,
                                const void *a, uint64_t *dst, uint32_t n,
                                uint32_t *flags_out)
{
    return (int)cft_cvt_to_u64(dev, (cft_format)fmt, (cft_round)rnd, exact,
                               a, dst, (size_t)n, flags_out);
}

WASM_EXPORT int cftw_logb(cft_device *dev, int fmt, const void *a, void *d,
                          uint32_t n, uint32_t *flags_out)
{
    return (int)cft_logb(dev, (cft_format)fmt, a, d, (size_t)n, flags_out);
}

WASM_EXPORT int cftw_next_up(cft_device *dev, int fmt, const void *a,
                             void *d, uint32_t n, uint32_t *flags_out)
{
    return (int)cft_next_up(dev, (cft_format)fmt, a, d, (size_t)n,
                            flags_out);
}

WASM_EXPORT int cftw_next_down(cft_device *dev, int fmt, const void *a,
                               void *d, uint32_t n, uint32_t *flags_out)
{
    return (int)cft_next_down(dev, (cft_format)fmt, a, d, (size_t)n,
                              flags_out);
}

/* One byte per element, values cft_class_value. Non-computational:
 * there is no flags argument in the contract and none is invented. */
WASM_EXPORT int cftw_class(cft_device *dev, int fmt, const void *a,
                           uint8_t *cls, uint32_t n)
{
    return (int)cft_class(dev, (cft_format)fmt, a, cls, (size_t)n);
}

WASM_EXPORT int cftw_total_order(cft_device *dev, int fmt, const void *a,
                                 const void *b, void *d, uint32_t n)
{
    return (int)cft_total_order(dev, (cft_format)fmt, a, b, d, (size_t)n);
}

WASM_EXPORT int cftw_total_order_mag(cft_device *dev, int fmt, const void *a,
                                     const void *b, void *d, uint32_t n)
{
    return (int)cft_total_order_mag(dev, (cft_format)fmt, a, b, d,
                                    (size_t)n);
}

WASM_EXPORT int cftw_rem(cft_device *dev, int fmt, const void *a,
                         const void *b, void *d, uint32_t n,
                         uint32_t *flags_out)
{
    return (int)cft_rem(dev, (cft_format)fmt, a, b, d, (size_t)n, flags_out);
}

/* ---- the phase-1 transcendentals (ABI 0.3) ----------------------- *
 *
 * Added 2026-09-03, the rebuild after the one that made mpfloat.c and
 * transcend.c part of this build. That rebuild left the module
 * answering cftw_abi_version() with 3 while exporting none of the nine
 * operations 0.3 IS - the same shape of untruth the clause-5 block
 * above exists to have ended, one minor version later, and the reason
 * docs/COMPATIBILITY.md called it a half-step rather than a release.
 * These close it: one wrapper per declaration in cft.h, same order,
 * same arguments.
 *
 * The signature difference from cft_run and from cft_div/cft_sqrt is
 * the contract's, not an omission here. These are HOST operations:
 * they issue no device pass, so there is no bus word and cft.h gives
 * them no bus_out parameter. A wrapper that added one to look like its
 * neighbours would be describing a device round trip that does not
 * happen. The device argument stays because cft.h takes one - it is
 * context, not a destination.
 *
 * Everything else is the usual adaptation and nothing more: cft_format
 * and cft_round as ints, size_t as uint32 (wasm32's), the flag word as
 * a pointer into the heap. Correct rounding, the clause 9.2.1 special
 * values and the exactness rules all live in the library, and nothing
 * here decides or second-guesses any of them.
 */

WASM_EXPORT int cftw_exp(cft_device *dev, int fmt, int rnd,
                         const void *a, void *d, uint32_t n,
                         uint32_t *flags_out)
{
    return (int)cft_exp(dev, (cft_format)fmt, (cft_round)rnd, a, d,
                        (size_t)n, flags_out);
}

WASM_EXPORT int cftw_expm1(cft_device *dev, int fmt, int rnd,
                           const void *a, void *d, uint32_t n,
                           uint32_t *flags_out)
{
    return (int)cft_expm1(dev, (cft_format)fmt, (cft_round)rnd, a, d,
                          (size_t)n, flags_out);
}

WASM_EXPORT int cftw_exp2(cft_device *dev, int fmt, int rnd,
                          const void *a, void *d, uint32_t n,
                          uint32_t *flags_out)
{
    return (int)cft_exp2(dev, (cft_format)fmt, (cft_round)rnd, a, d,
                         (size_t)n, flags_out);
}

WASM_EXPORT int cftw_log(cft_device *dev, int fmt, int rnd,
                         const void *a, void *d, uint32_t n,
                         uint32_t *flags_out)
{
    return (int)cft_log(dev, (cft_format)fmt, (cft_round)rnd, a, d,
                        (size_t)n, flags_out);
}

WASM_EXPORT int cftw_log1p(cft_device *dev, int fmt, int rnd,
                           const void *a, void *d, uint32_t n,
                           uint32_t *flags_out)
{
    return (int)cft_log1p(dev, (cft_format)fmt, (cft_round)rnd, a, d,
                          (size_t)n, flags_out);
}

WASM_EXPORT int cftw_log2(cft_device *dev, int fmt, int rnd,
                          const void *a, void *d, uint32_t n,
                          uint32_t *flags_out)
{
    return (int)cft_log2(dev, (cft_format)fmt, (cft_round)rnd, a, d,
                         (size_t)n, flags_out);
}

WASM_EXPORT int cftw_log10(cft_device *dev, int fmt, int rnd,
                           const void *a, void *d, uint32_t n,
                           uint32_t *flags_out)
{
    return (int)cft_log10(dev, (cft_format)fmt, (cft_round)rnd, a, d,
                          (size_t)n, flags_out);
}

/* b is the exponent for pow and the second leg for hypot. cft.h says
 * neither may be NULL; this wrapper passes what it is given rather
 * than substituting a default for a caller who forgot one. */
WASM_EXPORT int cftw_pow(cft_device *dev, int fmt, int rnd,
                         const void *a, const void *b, void *d, uint32_t n,
                         uint32_t *flags_out)
{
    return (int)cft_pow(dev, (cft_format)fmt, (cft_round)rnd, a, b, d,
                        (size_t)n, flags_out);
}

WASM_EXPORT int cftw_hypot(cft_device *dev, int fmt, int rnd,
                           const void *a, const void *b, void *d, uint32_t n,
                           uint32_t *flags_out)
{
    return (int)cft_hypot(dev, (cft_format)fmt, (cft_round)rnd, a, b, d,
                          (size_t)n, flags_out);
}

/* ---- the phase-2 trigonometrics (ABI 0.4) ------------------------ *
 *
 * Added 2026-09-03, hours after the block above closed 0.3's
 * half-step, and for the same reason one notch further along: the
 * library reached ABI 0.4 while this module was still built from the
 * 0.3 sources, so a rebuild on its own would have answered
 * cftw_abi_version() with 4 while exporting none of the eleven
 * operations 0.4 IS. That is the shape of untruth the clause-5 block
 * ended once and the phase-1 block ended again; ending it a third
 * time in the same commit as the rebuild is cheaper than recording a
 * third half-step.
 *
 * One wrapper per declaration in cft.h, in cft.h's order: the nine
 * unary entry points - sinpi, cospi, tanpi, asin, acos, atan and the
 * three Pi-forms of the inverses - then atan2 and atan2pi, which read
 * two operands.
 *
 * OPERAND ORDER, because it is the one thing a passthrough can get
 * wrong while still returning a plausible number: a[i] is y and b[i]
 * is x, the C order, y first, exactly as cft.h says. atan2(1, 0) is
 * +pi/2 and atan2(0, 1) is +0, so a swap disagrees with the vectors
 * almost everywhere and with the reader nowhere - which is what
 * bindings/wasm/verify.mjs step 5 exists to notice, and what it was
 * shown noticing before this file was believed.
 *
 * HOST operations again: no device pass, so no bus word and no
 * bus_out parameter. The device argument is context. Everything else
 * is the usual adaptation and nothing more - cft_format and cft_round
 * as ints, size_t as wasm32's uint32, the flag word as a pointer into
 * the heap. Correct rounding, the clause 9.2.1 rows and the exactness
 * enumeration (Niven for the forward set, Hermite-Lindemann for the
 * inverses) all live in the library; docs/TRANSCENDENTALS.md carries
 * the proofs, and nothing here decides or second-guesses any of them.
 */

WASM_EXPORT int cftw_sinpi(cft_device *dev, int fmt, int rnd,
                           const void *a, void *d, uint32_t n,
                           uint32_t *flags_out)
{
    return (int)cft_sinpi(dev, (cft_format)fmt, (cft_round)rnd, a, d,
                          (size_t)n, flags_out);
}

WASM_EXPORT int cftw_cospi(cft_device *dev, int fmt, int rnd,
                           const void *a, void *d, uint32_t n,
                           uint32_t *flags_out)
{
    return (int)cft_cospi(dev, (cft_format)fmt, (cft_round)rnd, a, d,
                          (size_t)n, flags_out);
}

WASM_EXPORT int cftw_tanpi(cft_device *dev, int fmt, int rnd,
                           const void *a, void *d, uint32_t n,
                           uint32_t *flags_out)
{
    return (int)cft_tanpi(dev, (cft_format)fmt, (cft_round)rnd, a, d,
                          (size_t)n, flags_out);
}

WASM_EXPORT int cftw_asin(cft_device *dev, int fmt, int rnd,
                          const void *a, void *d, uint32_t n,
                          uint32_t *flags_out)
{
    return (int)cft_asin(dev, (cft_format)fmt, (cft_round)rnd, a, d,
                         (size_t)n, flags_out);
}

WASM_EXPORT int cftw_acos(cft_device *dev, int fmt, int rnd,
                          const void *a, void *d, uint32_t n,
                          uint32_t *flags_out)
{
    return (int)cft_acos(dev, (cft_format)fmt, (cft_round)rnd, a, d,
                         (size_t)n, flags_out);
}

WASM_EXPORT int cftw_atan(cft_device *dev, int fmt, int rnd,
                          const void *a, void *d, uint32_t n,
                          uint32_t *flags_out)
{
    return (int)cft_atan(dev, (cft_format)fmt, (cft_round)rnd, a, d,
                         (size_t)n, flags_out);
}

WASM_EXPORT int cftw_asinpi(cft_device *dev, int fmt, int rnd,
                            const void *a, void *d, uint32_t n,
                            uint32_t *flags_out)
{
    return (int)cft_asinpi(dev, (cft_format)fmt, (cft_round)rnd, a, d,
                           (size_t)n, flags_out);
}

WASM_EXPORT int cftw_acospi(cft_device *dev, int fmt, int rnd,
                            const void *a, void *d, uint32_t n,
                            uint32_t *flags_out)
{
    return (int)cft_acospi(dev, (cft_format)fmt, (cft_round)rnd, a, d,
                           (size_t)n, flags_out);
}

WASM_EXPORT int cftw_atanpi(cft_device *dev, int fmt, int rnd,
                            const void *a, void *d, uint32_t n,
                            uint32_t *flags_out)
{
    return (int)cft_atanpi(dev, (cft_format)fmt, (cft_round)rnd, a, d,
                           (size_t)n, flags_out);
}

/* a[i] is y and b[i] is x - the C order, y first, because that is
 * what every caller of atan2 expects (cft.h). Neither may be NULL. */
WASM_EXPORT int cftw_atan2(cft_device *dev, int fmt, int rnd,
                           const void *a, const void *b, void *d, uint32_t n,
                           uint32_t *flags_out)
{
    return (int)cft_atan2(dev, (cft_format)fmt, (cft_round)rnd, a, b, d,
                          (size_t)n, flags_out);
}

WASM_EXPORT int cftw_atan2pi(cft_device *dev, int fmt, int rnd,
                             const void *a, const void *b, void *d,
                             uint32_t n, uint32_t *flags_out)
{
    return (int)cft_atan2pi(dev, (cft_format)fmt, (cft_round)rnd, a, b, d,
                            (size_t)n, flags_out);
}
