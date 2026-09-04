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

/* ---- the phase-3 radian trigonometry and the hyperbolics (ABI 0.5) --- *
 *
 * Added 2026-09-03 with the library's own step to 0.5, so this module
 * never carried the nine without exporting them - the half-step each
 * of the 0.3 and 0.4 rebuilds took once. One wrapper per declaration
 * in cft.h, same order, same arguments: unary, host operations, no bus
 * word. sin, cos and tan take RADIANS; the library reduces them against
 * its own 2/pi at any magnitude the format holds, and a wrapper knows
 * nothing about that, which is the point of a wrapper.
 */

WASM_EXPORT int cftw_sin(cft_device *dev, int fmt, int rnd,
                         const void *a, void *d, uint32_t n,
                         uint32_t *flags_out)
{
    return (int)cft_sin(dev, (cft_format)fmt, (cft_round)rnd, a, d,
                        (size_t)n, flags_out);
}

WASM_EXPORT int cftw_cos(cft_device *dev, int fmt, int rnd,
                         const void *a, void *d, uint32_t n,
                         uint32_t *flags_out)
{
    return (int)cft_cos(dev, (cft_format)fmt, (cft_round)rnd, a, d,
                        (size_t)n, flags_out);
}

WASM_EXPORT int cftw_tan(cft_device *dev, int fmt, int rnd,
                         const void *a, void *d, uint32_t n,
                         uint32_t *flags_out)
{
    return (int)cft_tan(dev, (cft_format)fmt, (cft_round)rnd, a, d,
                        (size_t)n, flags_out);
}

WASM_EXPORT int cftw_sinh(cft_device *dev, int fmt, int rnd,
                          const void *a, void *d, uint32_t n,
                          uint32_t *flags_out)
{
    return (int)cft_sinh(dev, (cft_format)fmt, (cft_round)rnd, a, d,
                         (size_t)n, flags_out);
}

WASM_EXPORT int cftw_cosh(cft_device *dev, int fmt, int rnd,
                          const void *a, void *d, uint32_t n,
                          uint32_t *flags_out)
{
    return (int)cft_cosh(dev, (cft_format)fmt, (cft_round)rnd, a, d,
                         (size_t)n, flags_out);
}

WASM_EXPORT int cftw_tanh(cft_device *dev, int fmt, int rnd,
                          const void *a, void *d, uint32_t n,
                          uint32_t *flags_out)
{
    return (int)cft_tanh(dev, (cft_format)fmt, (cft_round)rnd, a, d,
                         (size_t)n, flags_out);
}

WASM_EXPORT int cftw_asinh(cft_device *dev, int fmt, int rnd,
                           const void *a, void *d, uint32_t n,
                           uint32_t *flags_out)
{
    return (int)cft_asinh(dev, (cft_format)fmt, (cft_round)rnd, a, d,
                          (size_t)n, flags_out);
}

WASM_EXPORT int cftw_acosh(cft_device *dev, int fmt, int rnd,
                           const void *a, void *d, uint32_t n,
                           uint32_t *flags_out)
{
    return (int)cft_acosh(dev, (cft_format)fmt, (cft_round)rnd, a, d,
                          (size_t)n, flags_out);
}

WASM_EXPORT int cftw_atanh(cft_device *dev, int fmt, int rnd,
                           const void *a, void *d, uint32_t n,
                           uint32_t *flags_out)
{
    return (int)cft_atanh(dev, (cft_format)fmt, (cft_round)rnd, a, d,
                          (size_t)n, flags_out);
}

/* ---- the four packages of ABI 0.6 --------------------------------- *
 *
 * Added 2026-09-03 with the library's own step to 0.6, so this module
 * never carried the four packages without exporting them - the
 * half-step the 0.3 and 0.4 rebuilds each took once and 0.5 stopped
 * taking. One wrapper per declaration in cft.h, in cft.h's order:
 * clause 5.12's character conversions with 9.7's payload operations,
 * then the rest of table 9.1, then the scaled product reductions, then
 * clause 9.5's augmented arithmetic. CFT_SUMSQ and CFT_SUMABS need no
 * wrapper of their own: they are opcodes 28 and 29 through the
 * cftw_reduce that has been here since 0.1, which is the whole point
 * of an opcode.
 *
 * FOUR ADAPTATIONS ARE NEW HERE, and each one is the contract's shape
 * carried across wasm32 rather than a JavaScript convenience:
 *
 *   STRINGS IN. cft_from_decimal_char and cft_from_hex_char take
 *   `const char *const *` - an array of pointers to NUL-terminated
 *   sequences. On wasm32 that is an array of 4-byte heap offsets, so a
 *   JS caller writes each sequence into the heap, writes the offsets
 *   into a second buffer, and hands over that buffer's pointer. The
 *   wrapper passes it straight through; there is no marshalling here,
 *   because a wrapper that copied strings would be a second definition
 *   of what a sequence is.
 *
 *   STRINGS OUT keep the C's two-call sizing protocol EXACTLY, and
 *   this is the one place the temptation to invent a JavaScript
 *   contract was real. cft.h: *len is always set, on success and on
 *   refusal alike, to the bytes required INCLUDING the NUL; cap = 0
 *   with out = NULL asks; a buffer too small is
 *   CFT_ERR_INVALID_ARGUMENT with *len set and NOTHING written. A
 *   wrapper that allocated the answer itself and returned a pointer
 *   would have to own the free, would hide the refusal, and would mean
 *   the browser and the C disagree about what a short buffer does -
 *   so it does none of that. `out` of 0 IS the NULL the protocol asks
 *   for: wasm address 0 is not a valid allocation.
 *
 *   THE INT64 ARRAY. pown, compound and rootn read one int64_t per
 *   element beside the encoding array. It crosses as a plain heap
 *   pointer, the way cft_cvt_from_i64's does - JS fills it with a
 *   BigInt64Array view - rather than as a parameter, because without
 *   -sWASM_BIGINT a wasm i64 cannot cross the JS boundary at all.
 *   cft.h's name for the element count there is `count`, not `n`, and
 *   this file keeps that spelling so the two arguments cannot be
 *   confused when they are read side by side.
 *
 *   THE PAIRS. The three scaled products deliver a significand and an
 *   int64 scale, and the three augmented operations deliver r and e.
 *   Both pairs travel as out-pointers into the heap - scale_out an
 *   int64 the caller reads with a BigInt64Array, r and e two element
 *   buffers - which is what the C does, and is why neither needed a
 *   return-value convention invented for it here.
 *
 * The augmented three take NO ROUNDING ARGUMENT, and the omission is
 * normative rather than an oversight in this file: 9.5 fixes the
 * direction to roundTiesTowardZero, which is not one of clause 4.3's
 * five, so there is nothing to pass. A wrapper that accepted a
 * cft_round to look like its neighbours would be describing a choice
 * the caller does not have.
 *
 * Host operations throughout: no cft_run pass is issued, so there is
 * no bus word and no bus_out parameter, and `dev` is context. Correct
 * rounding, 9.2.1's special values, 5.12's syntax and its refusals,
 * 9.4's infinity-before-NaN row and 9.5's roundTiesTowardZero all live
 * in the library; nothing here decides or second-guesses any of them.
 */

/* ---- clause 5.12's character conversions, 9.7's payloads ---------- */

/* Pmin(fmt): 9, 17, 36, 73. size_t in the contract, uint32 here like
 * every other size_t on wasm32. */
WASM_EXPORT uint32_t cftw_format_decimal_digits(int fmt)
{
    return (uint32_t)cft_format_decimal_digits((cft_format)fmt);
}

/* `in` is an array of n heap offsets, each a NUL-terminated sequence.
 * bad_index reports which element of the batch was refused, and is
 * written only when the library writes it - a caller that passes 0
 * gets the contract's NULL and no report, exactly as in C. */
WASM_EXPORT int cftw_from_decimal_char(cft_device *dev, int fmt, int rnd,
                                       const char *const *in, void *d,
                                       uint32_t n, uint32_t *bad_index,
                                       uint32_t *flags_out)
{
    size_t bad = 0;
    int st = (int)cft_from_decimal_char(dev, (cft_format)fmt, (cft_round)rnd,
                                        in, d, (size_t)n,
                                        bad_index ? &bad : NULL, flags_out);
    if (bad_index)
        *bad_index = (uint32_t)bad;
    return st;
}

/* The sizing protocol, unchanged: out = 0 with cap = 0 asks for the
 * length, *len is set either way, and a short buffer refuses rather
 * than truncating. digits = 0 is the exact conversion. */
WASM_EXPORT int cftw_to_decimal_char(cft_device *dev, int fmt, int rnd,
                                     const void *a, uint32_t digits,
                                     char *out, uint32_t cap, uint32_t *len,
                                     uint32_t *flags_out)
{
    size_t need = 0;
    int st = (int)cft_to_decimal_char(dev, (cft_format)fmt, (cft_round)rnd, a,
                                      (size_t)digits, out, (size_t)cap,
                                      len ? &need : NULL, flags_out);
    if (len)
        *len = (uint32_t)need;
    return st;
}

WASM_EXPORT int cftw_from_hex_char(cft_device *dev, int fmt, int rnd,
                                   const char *const *in, void *d,
                                   uint32_t n, uint32_t *bad_index,
                                   uint32_t *flags_out)
{
    size_t bad = 0;
    int st = (int)cft_from_hex_char(dev, (cft_format)fmt, (cft_round)rnd,
                                    in, d, (size_t)n,
                                    bad_index ? &bad : NULL, flags_out);
    if (bad_index)
        *bad_index = (uint32_t)bad;
    return st;
}

/* Exact always, so there is no rounding attribute and no flag word -
 * cft.h gives this one neither, and neither is invented here. */
WASM_EXPORT int cftw_to_hex_char(cft_device *dev, int fmt, const void *a,
                                 char *out, uint32_t cap, uint32_t *len)
{
    size_t need = 0;
    int st = (int)cft_to_hex_char(dev, (cft_format)fmt, a, out, (size_t)cap,
                                  len ? &need : NULL);
    if (len)
        *len = (uint32_t)need;
    return st;
}

/* The 9.7 payload operations. "These signal no exceptions", so none
 * has a flags argument - the same reason cftw_class has none. */
WASM_EXPORT int cftw_get_payload(cft_device *dev, int fmt, const void *a,
                                 void *d, uint32_t n)
{
    return (int)cft_get_payload(dev, (cft_format)fmt, a, d, (size_t)n);
}

WASM_EXPORT int cftw_set_payload(cft_device *dev, int fmt, const void *a,
                                 void *d, uint32_t n)
{
    return (int)cft_set_payload(dev, (cft_format)fmt, a, d, (size_t)n);
}

WASM_EXPORT int cftw_set_payload_signaling(cft_device *dev, int fmt,
                                           const void *a, void *d,
                                           uint32_t n)
{
    return (int)cft_set_payload_signaling(dev, (cft_format)fmt, a, d,
                                          (size_t)n);
}

/* ---- the rest of IEEE 754-2019 table 9.1 -------------------------- */

WASM_EXPORT int cftw_exp2m1(cft_device *dev, int fmt, int rnd,
                            const void *a, void *d, uint32_t n,
                            uint32_t *flags_out)
{
    return (int)cft_exp2m1(dev, (cft_format)fmt, (cft_round)rnd, a, d,
                           (size_t)n, flags_out);
}

WASM_EXPORT int cftw_exp10(cft_device *dev, int fmt, int rnd,
                           const void *a, void *d, uint32_t n,
                           uint32_t *flags_out)
{
    return (int)cft_exp10(dev, (cft_format)fmt, (cft_round)rnd, a, d,
                          (size_t)n, flags_out);
}

WASM_EXPORT int cftw_exp10m1(cft_device *dev, int fmt, int rnd,
                             const void *a, void *d, uint32_t n,
                             uint32_t *flags_out)
{
    return (int)cft_exp10m1(dev, (cft_format)fmt, (cft_round)rnd, a, d,
                            (size_t)n, flags_out);
}

WASM_EXPORT int cftw_log2p1(cft_device *dev, int fmt, int rnd,
                            const void *a, void *d, uint32_t n,
                            uint32_t *flags_out)
{
    return (int)cft_log2p1(dev, (cft_format)fmt, (cft_round)rnd, a, d,
                           (size_t)n, flags_out);
}

WASM_EXPORT int cftw_log10p1(cft_device *dev, int fmt, int rnd,
                             const void *a, void *d, uint32_t n,
                             uint32_t *flags_out)
{
    return (int)cft_log10p1(dev, (cft_format)fmt, (cft_round)rnd, a, d,
                            (size_t)n, flags_out);
}

WASM_EXPORT int cftw_rsqrt(cft_device *dev, int fmt, int rnd,
                           const void *a, void *d, uint32_t n,
                           uint32_t *flags_out)
{
    return (int)cft_rsqrt(dev, (cft_format)fmt, (cft_round)rnd, a, d,
                          (size_t)n, flags_out);
}

/* powr is NOT pow, and the difference is in the library rather than
 * here: x < 0 is invalid for EVERY y including a NaN, powr(+-0, +-0)
 * and powr(+1, +-inf) are invalid, and powr(qNaN, y) is a quiet NaN
 * where pow(qNaN, 0) is 1. a is the base and b the exponent, in that
 * order - the asymmetry verify.mjs step 5 exists to notice. */
WASM_EXPORT int cftw_powr(cft_device *dev, int fmt, int rnd,
                          const void *a, const void *b, void *d, uint32_t n,
                          uint32_t *flags_out)
{
    return (int)cft_powr(dev, (cft_format)fmt, (cft_round)rnd, a, b, d,
                         (size_t)n, flags_out);
}

/* The three with an INTEGER exponent (9.2.1: "n is a finite integral
 * value in integralFormat"). `nn` is a heap pointer to `count`
 * int64_t values - one per element, never NULL - and `count` is the
 * element count, which is cft.h's own naming for the one place those
 * two arguments are not the same number. */
WASM_EXPORT int cftw_pown(cft_device *dev, int fmt, int rnd, const void *a,
                          const int64_t *nn, void *d, uint32_t count,
                          uint32_t *flags_out)
{
    return (int)cft_pown(dev, (cft_format)fmt, (cft_round)rnd, a, nn, d,
                         (size_t)count, flags_out);
}

WASM_EXPORT int cftw_compound(cft_device *dev, int fmt, int rnd,
                              const void *a, const int64_t *nn, void *d,
                              uint32_t count, uint32_t *flags_out)
{
    return (int)cft_compound(dev, (cft_format)fmt, (cft_round)rnd, a, nn, d,
                             (size_t)count, flags_out);
}

WASM_EXPORT int cftw_rootn(cft_device *dev, int fmt, int rnd, const void *a,
                           const int64_t *nn, void *d, uint32_t count,
                           uint32_t *flags_out)
{
    return (int)cft_rootn(dev, (cft_format)fmt, (cft_round)rnd, a, nn, d,
                          (size_t)count, flags_out);
}

/* ---- the scaled product reductions (clause 9.4) ------------------- *
 *
 * A pair out: `pr` receives ONE element and `scale_out` one int64,
 * both heap pointers, neither NULL. n == 0 is the multiplicative
 * identity - pr = 1, sf = 0, no exception - so a zero-length call is
 * an answer rather than an error, and this wrapper passes the count
 * through without a length check of its own.
 */

WASM_EXPORT int cftw_scaled_prod(cft_device *dev, int fmt, int rnd,
                                 const void *a, void *pr, int64_t *scale_out,
                                 uint32_t n, uint32_t *flags_out)
{
    return (int)cft_scaled_prod(dev, (cft_format)fmt, (cft_round)rnd, a, pr,
                                scale_out, (size_t)n, flags_out);
}

WASM_EXPORT int cftw_scaled_prod_sum(cft_device *dev, int fmt, int rnd,
                                     const void *a, const void *b, void *pr,
                                     int64_t *scale_out, uint32_t n,
                                     uint32_t *flags_out)
{
    return (int)cft_scaled_prod_sum(dev, (cft_format)fmt, (cft_round)rnd, a,
                                    b, pr, scale_out, (size_t)n, flags_out);
}

/* The leaf is a[i] - b[i], in that order. An asymmetric operand pair
 * again, and the one this build's negative control swaps. */
WASM_EXPORT int cftw_scaled_prod_diff(cft_device *dev, int fmt, int rnd,
                                      const void *a, const void *b, void *pr,
                                      int64_t *scale_out, uint32_t n,
                                      uint32_t *flags_out)
{
    return (int)cft_scaled_prod_diff(dev, (cft_format)fmt, (cft_round)rnd, a,
                                     b, pr, scale_out, (size_t)n, flags_out);
}

/* ---- the augmented arithmetic (clause 9.5) ------------------------ *
 *
 * Two outputs per element and no rounding argument. r and e must not
 * overlap each other - the same pointer for both is
 * CFT_ERR_INVALID_ARGUMENT in the library, which is where that check
 * belongs - while either may alias a or b.
 */

WASM_EXPORT int cftw_augmented_add(cft_device *dev, int fmt, const void *a,
                                   const void *b, void *r, void *e,
                                   uint32_t n, uint32_t *flags_out)
{
    return (int)cft_augmented_add(dev, (cft_format)fmt, a, b, r, e,
                                  (size_t)n, flags_out);
}

WASM_EXPORT int cftw_augmented_sub(cft_device *dev, int fmt, const void *a,
                                   const void *b, void *r, void *e,
                                   uint32_t n, uint32_t *flags_out)
{
    return (int)cft_augmented_sub(dev, (cft_format)fmt, a, b, r, e,
                                  (size_t)n, flags_out);
}

WASM_EXPORT int cftw_augmented_mul(cft_device *dev, int fmt, const void *a,
                                   const void *b, void *r, void *e,
                                   uint32_t n, uint32_t *flags_out)
{
    return (int)cft_augmented_mul(dev, (cft_format)fmt, a, b, r, e,
                                  (size_t)n, flags_out);
}

/* ---- the two packages of ABI 0.7 ---------------------------------- *
 *
 * Added 2026-09-04 with the library's own step to 0.7, so this module
 * never carried the two packages without exporting them - the
 * half-step the 0.3 and 0.4 rebuilds each took once and every step
 * since has refused to take. One wrapper per declaration in cft.h, in
 * cft.h's order: the status word of 7.1 with 5.7.4's six operations
 * over it, the three conformance predicates of 5.7.1, the four
 * magnitude forms of 9.6, and then clause 5.4.1's formatOf
 * arithmetic.
 *
 * THREE THINGS HERE ARE NOT PLAIN PASSTHROUGHS, and each is the
 * contract's shape carried across wasm32 rather than a JavaScript
 * convenience:
 *
 *   THE MASK IS A MACRO, and a macro is the one part of a header a
 *   caller on the other side of a wasm boundary cannot reach at all.
 *   CFT_FLAGS_ALL is DERIVED in cft.h from the cft_exception bits
 *   rather than written out, so a JavaScript copy of it would be a
 *   transcription of a derivation - which is how a sixth flag would
 *   silently stop being covered by "all". cftw_flags_all() projects
 *   the macro instead, and bindings/node's audit asks the module for
 *   it rather than trusting its own OR.
 *
 *   A NULL DEVICE IS PASSED THROUGH, not defended against. cft.h says
 *   the six flag calls accept one and behave as a handle whose word is
 *   permanently zero; a wrapper that refused it here would be a
 *   different contract in the browser than in C, and 0 is exactly the
 *   pointer a JS caller holds before cftw_open_software() has
 *   succeeded.
 *
 *   TWO FORMATS, IN THE C's ORDER. The formatOf six take sfmt for a,
 *   b and c and dfmt for d, so d holds n elements of
 *   cftw_format_size(dfmt) bytes while the operands hold n of
 *   cftw_format_size(sfmt) - the two are different widths in the same
 *   call, which no other entry point in this file does except
 *   cftw_convert. d MUST NOT overlap a, b or c (cft.h); this wrapper
 *   does not restate the rule and does not break it.
 *
 * The four magnitude forms take NO ROUNDING ARGUMENT and the omission
 * is normative rather than an oversight: 9.6 defines each by a
 * comparison of magnitudes and then a SELECTION of one operand, so
 * there is no rounding for an attribute to direct. They issue no
 * device pass either, so there is no bus word - like nextUp, and for
 * the same reason. The three predicates take neither a device nor a
 * format: 5.7.1 asks about the programming environment, not about a
 * number, and they are safe to call before cftw_open_software().
 *
 * Everything the operations mean - which direction narrows exactly,
 * why the composed route may not be used, whose exceptions the
 * formatOf six raise, what "otherwise" means for a NaN in 9.6 - lives
 * in cft.h and in python/cft_golden/formatof.py. Nothing here decides
 * or second-guesses any of it.
 */

/* ---- the status word (7.1) and 5.7.4's six operations ------------- */

/* CFT_FLAGS_ALL, which is a macro and therefore invisible to a caller
 * that only has the module. Derived in cft.h from the cft_exception
 * bits; projected here so that nothing on the JavaScript side has to
 * hold a second copy of the derivation. */
WASM_EXPORT uint32_t cftw_flags_all(void)
{
    return (uint32_t)CFT_FLAGS_ALL;
}

WASM_EXPORT void cftw_lower_flags(cft_device *dev, uint32_t mask)
{
    cft_lower_flags(dev, mask);
}

WASM_EXPORT void cftw_raise_flags(cft_device *dev, uint32_t mask)
{
    cft_raise_flags(dev, mask);
}

/* 1 or 0, never a flag word - cft.h makes that a property of the
 * value so it cannot be mistaken for an intersection. */
WASM_EXPORT int cftw_test_flags(cft_device *dev, uint32_t mask)
{
    return cft_test_flags(dev, mask);
}

WASM_EXPORT uint32_t cftw_save_all_flags(cft_device *dev)
{
    return cft_save_all_flags(dev);
}

/* RESTORES rather than ORs: a flag inside the mask that is low in
 * `saved` comes back low. That is what makes save/restore a round
 * trip rather than an accumulation. */
WASM_EXPORT void cftw_restore_flags(cft_device *dev, uint32_t saved,
                                    uint32_t mask)
{
    cft_restore_flags(dev, saved, mask);
}

/* No device argument, because no device is involved: 5.7.4 puts the
 * saved flags in the first operand precisely so this is pure. */
WASM_EXPORT int cftw_test_saved_flags(uint32_t saved, uint32_t mask)
{
    return cft_test_saved_flags(saved, mask);
}

/* ---- 5.7.1's three conformance predicates ------------------------- */

WASM_EXPORT int cftw_is754version1985(void)
{
    return cft_is754version1985();
}

WASM_EXPORT int cftw_is754version2008(void)
{
    return cft_is754version2008();
}

WASM_EXPORT int cftw_is754version2019(void)
{
    return cft_is754version2019();
}

/* ---- 9.6's magnitude forms of minimum and maximum ----------------- *
 *
 * Host operations of the nextUp kind: a comparison of two sign-cleared
 * encodings and a selection, no rounding and no opcode - so no `rnd`
 * argument and no bus word, and the result is one of the two operand
 * encodings bit for bit except where the base operation delivers a
 * NaN. d may alias a or b. */

WASM_EXPORT int cftw_min_mag(cft_device *dev, int fmt, const void *a,
                             const void *b, void *d, uint32_t n,
                             uint32_t *flags_out)
{
    return (int)cft_min_mag(dev, (cft_format)fmt, a, b, d, (size_t)n,
                            flags_out);
}

WASM_EXPORT int cftw_max_mag(cft_device *dev, int fmt, const void *a,
                             const void *b, void *d, uint32_t n,
                             uint32_t *flags_out)
{
    return (int)cft_max_mag(dev, (cft_format)fmt, a, b, d, (size_t)n,
                            flags_out);
}

WASM_EXPORT int cftw_minnum_mag(cft_device *dev, int fmt, const void *a,
                                const void *b, void *d, uint32_t n,
                                uint32_t *flags_out)
{
    return (int)cft_minnum_mag(dev, (cft_format)fmt, a, b, d, (size_t)n,
                               flags_out);
}

WASM_EXPORT int cftw_maxnum_mag(cft_device *dev, int fmt, const void *a,
                                const void *b, void *d, uint32_t n,
                                uint32_t *flags_out)
{
    return (int)cft_maxnum_mag(dev, (cft_format)fmt, a, b, d, (size_t)n,
                               flags_out);
}

/* ---- clause 5.4.1's formatOf arithmetic --------------------------- *
 *
 * SIX ENTRY POINTS RATHER THAN ONE DISPATCHER, and the reason is the
 * C's rather than this file's: division and square root have no opcode
 * and never will (they are compositions here), so a dispatcher keyed
 * on cft_op could not express half of the clause. The arities differ
 * too. cft.h argues it at length.
 *
 * `sfmt` is the format of a, b and c; `dfmt` is d's. The rounding
 * attribute directs the ONE rounding, and every exception is the
 * DESTINATION's. The signatures below carry exactly the operands
 * cft.h gives each operation, so there is no unused slot here to pass
 * the wrong thing into. bus_out is real for the widening direction (a
 * device pass is issued underneath) and reads back 0 for the narrowing
 * one, which is the contract's own statement and not a wrapper's
 * simplification. */

WASM_EXPORT int cftw_formatof_add(cft_device *dev, int sfmt, int dfmt,
                                  int rnd, const void *a, const void *b,
                                  void *d, uint32_t n, uint32_t *flags_out,
                                  uint32_t *bus_out)
{
    return (int)cft_formatof_add(dev, (cft_format)sfmt, (cft_format)dfmt,
                                 (cft_round)rnd, a, b, d, (size_t)n,
                                 flags_out, bus_out);
}

WASM_EXPORT int cftw_formatof_sub(cft_device *dev, int sfmt, int dfmt,
                                  int rnd, const void *a, const void *b,
                                  void *d, uint32_t n, uint32_t *flags_out,
                                  uint32_t *bus_out)
{
    return (int)cft_formatof_sub(dev, (cft_format)sfmt, (cft_format)dfmt,
                                 (cft_round)rnd, a, b, d, (size_t)n,
                                 flags_out, bus_out);
}

WASM_EXPORT int cftw_formatof_mul(cft_device *dev, int sfmt, int dfmt,
                                  int rnd, const void *a, const void *b,
                                  void *d, uint32_t n, uint32_t *flags_out,
                                  uint32_t *bus_out)
{
    return (int)cft_formatof_mul(dev, (cft_format)sfmt, (cft_format)dfmt,
                                 (cft_round)rnd, a, b, d, (size_t)n,
                                 flags_out, bus_out);
}

WASM_EXPORT int cftw_formatof_div(cft_device *dev, int sfmt, int dfmt,
                                  int rnd, const void *a, const void *b,
                                  void *d, uint32_t n, uint32_t *flags_out,
                                  uint32_t *bus_out)
{
    return (int)cft_formatof_div(dev, (cft_format)sfmt, (cft_format)dfmt,
                                 (cft_round)rnd, a, b, d, (size_t)n,
                                 flags_out, bus_out);
}

WASM_EXPORT int cftw_formatof_sqrt(cft_device *dev, int sfmt, int dfmt,
                                   int rnd, const void *a, void *d,
                                   uint32_t n, uint32_t *flags_out,
                                   uint32_t *bus_out)
{
    return (int)cft_formatof_sqrt(dev, (cft_format)sfmt, (cft_format)dfmt,
                                  (cft_round)rnd, a, d, (size_t)n,
                                  flags_out, bus_out);
}

WASM_EXPORT int cftw_formatof_fma(cft_device *dev, int sfmt, int dfmt,
                                  int rnd, const void *a, const void *b,
                                  const void *c, void *d, uint32_t n,
                                  uint32_t *flags_out, uint32_t *bus_out)
{
    return (int)cft_formatof_fma(dev, (cft_format)sfmt, (cft_format)dfmt,
                                 (cft_round)rnd, a, b, c, d, (size_t)n,
                                 flags_out, bus_out);
}
