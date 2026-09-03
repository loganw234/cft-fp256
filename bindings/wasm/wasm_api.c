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
