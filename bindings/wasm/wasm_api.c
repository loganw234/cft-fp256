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
