/* Copyright 2026 Logan W.
 * SPDX-License-Identifier: Apache-2.0
 *
 * The device backend: XRT, one or many tiles.
 *
 * This is the only C++ in libcft, and it is C++ because XRT's API is.
 * It exports nothing but the C functions in backend.h, so the shape of
 * the library from outside is unchanged.
 *
 * ---------------------------------------------------------------
 * Why multi-tile lives here rather than in the caller
 * ---------------------------------------------------------------
 *
 * A four-CU bitstream is not four times one CU from the host's side.
 * Each compute unit's AXI master is wired to its own group of HBM
 * pseudo-channels (hw/link_quad.cfg), so a buffer allocated for tile 1
 * is not reachable by tile 2 - there is no "the input array" to share.
 * Each tile needs its own buffers, in its own memory group, holding
 * its own slice.
 *
 * That is genuinely awkward, and it is exactly the kind of awkward a
 * library should absorb once rather than have every caller rediscover.
 * cft_run() still takes one pointer per operand and one element count.
 *
 * ---------------------------------------------------------------
 * Why partitioning cannot disturb the contract
 * ---------------------------------------------------------------
 *
 * Element i of the output depends on element i of the inputs and
 * nothing else, so which tile computed it is unobservable. Each tile
 * writes a disjoint, contiguous, index-ordered range. The output is
 * therefore the same bits for any tile count, including one - and a
 * result computed on the quad image must equal the same call on the
 * single-tile image, on the software backend, and on a laptop. That
 * equality is the product, so it is asserted here and tested in
 * host/tests/.
 *
 * ---------------------------------------------------------------
 * Padding
 * ---------------------------------------------------------------
 *
 * The engine works in whole 256-bit beats: 8 fp32, 4 fp64, 2 fp128 or
 * 1 fp256 element. A caller's n is arbitrary, so tails are padded with
 * zero operands.
 *
 * Zero padding is safe rather than merely conventional. Every opcode
 * this contract assigns returns a flag-free result for all-zero
 * operands: the arithmetic group computes 0*0+0 = +0 exactly, the sign
 * and min/max and predicate groups signal only on a signaling NaN, and
 * the integer group never signals at all. An opcode the contract
 * leaves unassigned raises invalid - but it does so for the real
 * elements too, so the OR is unchanged either way. host/tests
 * checks this over every opcode, format and attribute rather than
 * leaving it as an argument in a comment.
 */

#include <algorithm>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <exception>
#include <string>
#include <vector>

#include <xrt/xrt_bo.h>
#include <xrt/xrt_device.h>
#include <xrt/xrt_kernel.h>

#include "backend.h"

/* mirrors cft_status; see backend.h */
enum {
    ST_OK = 0,
    ST_INVALID_ARGUMENT,
    ST_UNSUPPORTED,
    ST_NO_DEVICE,
    ST_ARTIFACT,
    ST_BUS_FAULT,
    ST_OUT_OF_MEMORY,
    ST_TIMEOUT,
    ST_INTERNAL
};

/* XRT 2.19 deprecates xrt::kernel::read_register and points at
 * xrt::ip instead. That advice does not apply here: xrt::ip is for
 * user-managed IPs, and this kernel is ap_ctrl_hs and deliberately run
 * BY XRT - the two cannot both hold a CU. Reading four read-only
 * status registers after a run has completed is exactly what the call
 * is for, and there is no supported alternative that keeps XRT
 * managing execution.
 *
 * If a future XRT removes it rather than deprecating it, the fallback
 * already exists and is already honest: cftx_open catches the failure,
 * reports flags_readable = 0, and cft_get_caps tells the caller its
 * exception flags cannot be trusted. That is the same hole pyxrt has
 * had all along, and the reason this backend exists. */
#if defined(__GNUC__)
#  pragma GCC diagnostic ignored "-Wdeprecated-declarations"
#endif

namespace {

/* rtl/cft_csr.sv is the normative map; these must move together. */
constexpr uint32_t CSR_FLAGS   = 0x40;
constexpr uint32_t CSR_MAGIC   = 0x44;
constexpr uint32_t CSR_VERSION = 0x48;
constexpr uint32_t CSR_CAPS    = 0x4C;
constexpr uint32_t CSR_STATUS  = 0x50;
constexpr uint32_t TILE_MAGIC  = 0x43465430u;   /* "CFT0" */

/* kernel.xml argument ids */
constexpr int ARG_MODE = 0, ARG_N = 1, ARG_A = 2, ARG_B = 3,
              ARG_C = 4, ARG_D = 5;

constexpr int MAX_TILES = 16;

std::string g_err;

void set_err(const std::string &s) { g_err = s; }

int elem_bytes(int fmt)
{
    switch (fmt) {
    case 0: return 4;
    case 1: return 8;
    case 2: return 16;
    case 3: return 32;
    default: return 0;
    }
}

struct Tile {
    xrt::kernel k;
    xrt::bo     a, b, c, d;
    size_t      cap = 0;         /* bytes currently allocated per buffer */
};

struct Dev {
    xrt::device       dev;
    xrt::uuid         uuid;
    std::vector<Tile> tiles;
    int               flags_readable = 1;
};

/* Grow a tile's buffers to hold `bytes`. Buffers are cached across
 * calls because allocating and mapping a device buffer costs far more
 * than the transfer for the sizes a first port will use, and a caller
 * that does not want the copy at all has cft_alloc(). */
void ensure_capacity(Dev &D, Tile &t, size_t bytes)
{
    if (t.cap >= bytes)
        return;
    t.a = xrt::bo(D.dev, bytes, xrt::bo::flags::normal, t.k.group_id(ARG_A));
    t.b = xrt::bo(D.dev, bytes, xrt::bo::flags::normal, t.k.group_id(ARG_B));
    t.c = xrt::bo(D.dev, bytes, xrt::bo::flags::normal, t.k.group_id(ARG_C));
    t.d = xrt::bo(D.dev, bytes, xrt::bo::flags::normal, t.k.group_id(ARG_D));
    t.cap = bytes;
}

/* Copy one operand slice in, zero-filling the beat padding. A null
 * source is an operand this opcode does not read; the buffer still has
 * to exist and be addressable, so it is zeroed rather than skipped. */
void stage(xrt::bo &bo, const uint8_t *src, size_t real_bytes,
           size_t padded_bytes)
{
    auto *p = bo.map<uint8_t *>();
    if (src)
        std::memcpy(p, src, real_bytes);
    else
        std::memset(p, 0, real_bytes);
    if (padded_bytes > real_bytes)
        std::memset(p + real_bytes, 0, padded_bytes - real_bytes);
    bo.sync(XCL_BO_SYNC_BO_TO_DEVICE, padded_bytes, 0);
}

}  // namespace

extern "C" const char *cftx_last_error(void)
{
    return g_err.c_str();
}

extern "C" int cftx_open(const char *artifact, int index, void **out,
                         uint32_t *format_mask, uint32_t *op_groups,
                         uint32_t *tiles, uint32_t *version,
                         int *flags_readable)
{
    if (!artifact || !out)
        return ST_INVALID_ARGUMENT;
    *out = nullptr;
    g_err.clear();

    /* Opening the card and loading the bitstream fail for completely
     * different reasons and want completely different responses - "no
     * card visible" is a driver or a slot, "bad xclbin" is a build.
     * Reporting both as one status is the sort of small dishonesty
     * that costs an hour at a bench. */
    Dev *D = new Dev();
    try {
        D->dev = xrt::device(static_cast<unsigned int>(index));
    } catch (const std::exception &e) {
        delete D;
        set_err(std::string("opening device ") + std::to_string(index) +
                ": " + e.what());
        return ST_NO_DEVICE;
    }
    try {
        D->uuid = D->dev.load_xclbin(artifact);
    } catch (const std::exception &e) {
        delete D;
        set_err(std::string("loading ") + artifact + ": " + e.what());
        return ST_ARTIFACT;
    }

    /* Enumerate the compute units by probing their names. The
     * alternative is parsing IP_LAYOUT, which is a different API in
     * every XRT generation; a name that fails to open is the same
     * answer in all of them. Exclusive access is required for the
     * status registers to be readable at all. */
    for (int i = 1; i <= MAX_TILES; i++) {
        std::string nm = "cft_krnl:{cft_krnl_" + std::to_string(i) + "}";
        try {
            /* Construct first, append second: if the kernel does not
             * exist this throws before the vector grows, so the tile
             * count is always the number that actually opened. */
            xrt::kernel k(D->dev, D->uuid, nm,
                          xrt::kernel::cu_access_mode::exclusive);
            D->tiles.emplace_back();
            D->tiles.back().k = std::move(k);
        } catch (const std::exception &) {
            break;
        }
    }
    if (D->tiles.empty()) {
        delete D;
        set_err(std::string(artifact) +
                " contains no cft_krnl compute unit - is it a tile?");
        return ST_ARTIFACT;
    }

    /* Ask the hardware what it is before believing the filename. A
     * bitstream that is not a tile, or is a tile from an incompatible
     * contract, should be refused here rather than produce confident
     * nonsense later. */
    uint32_t magic = 0, caps = 0, ver = 0;
    try {
        magic = D->tiles[0].k.read_register(CSR_MAGIC);
        ver   = D->tiles[0].k.read_register(CSR_VERSION);
        caps  = D->tiles[0].k.read_register(CSR_CAPS);
    } catch (const std::exception &e) {
        /* The one honest fallback: assume nothing about capability and
         * tell the caller its flags are untrustworthy. cft_caps has a
         * field for exactly this, because a check that silently skips
         * itself is worse than no check. */
        D->flags_readable = 0;
        set_err(std::string("status registers unreadable: ") + e.what());
    }

    if (D->flags_readable && magic != TILE_MAGIC) {
        char buf[128];
        std::snprintf(buf, sizeof buf,
                      "not a cft tile: MAGIC reads 0x%08x, expected 0x%08x",
                      magic, TILE_MAGIC);
        delete D;
        set_err(buf);
        return ST_ARTIFACT;
    }

    *format_mask    = D->flags_readable ? (caps & 0xFu) : 0xFu;
    *op_groups      = D->flags_readable ? ((caps >> 8) & 0xFFu) : 0x1Fu;
    *tiles          = static_cast<uint32_t>(D->tiles.size());
    *version        = ver;
    *flags_readable = D->flags_readable;
    *out            = D;
    return ST_OK;
}

extern "C" void cftx_close(void *hw)
{
    delete static_cast<Dev *>(hw);
}

extern "C" int cftx_run(void *hw, int op, int fmt, int rnd,
                        const void *a, const void *b, const void *c,
                        void *d, size_t n, uint32_t *flags, uint32_t *bus)
{
    Dev &D = *static_cast<Dev *>(hw);
    const size_t esz = static_cast<size_t>(elem_bytes(fmt));
    if (esz == 0)
        return ST_INVALID_ARGUMENT;

    /* Elements per 256-bit beat: the engine's indivisible unit. */
    const size_t epb = 32 / esz;
    const size_t beats_total = (n + epb - 1) / epb;
    const size_t ntiles = D.tiles.size();
    const size_t beats_per_tile = (beats_total + ntiles - 1) / ntiles;

    const uint32_t mode = static_cast<uint32_t>(op & 0xFF) |
                          (static_cast<uint32_t>(fmt & 0xF) << 8) |
                          (static_cast<uint32_t>(rnd & 0x7) << 12);

    const auto *pa = static_cast<const uint8_t *>(a);
    const auto *pb = static_cast<const uint8_t *>(b);
    const auto *pc = static_cast<const uint8_t *>(c);
    auto *pd = static_cast<uint8_t *>(d);

    struct Slice { size_t tile, first_elem, real, padded; };
    std::vector<Slice> slices;
    std::vector<xrt::run> runs;

    try {
        for (size_t t = 0; t < ntiles; t++) {
            const size_t first_beat = t * beats_per_tile;
            if (first_beat >= beats_total)
                break;                       /* fewer beats than tiles */
            const size_t nbeats =
                std::min(beats_per_tile, beats_total - first_beat);
            const size_t first_elem = first_beat * epb;
            const size_t padded = nbeats * epb;
            const size_t real = std::min(padded, n - first_elem);

            Tile &tile = D.tiles[t];
            ensure_capacity(D, tile, padded * esz);
            stage(tile.a, pa ? pa + first_elem * esz : nullptr,
                  real * esz, padded * esz);
            stage(tile.b, pb ? pb + first_elem * esz : nullptr,
                  real * esz, padded * esz);
            stage(tile.c, pc ? pc + first_elem * esz : nullptr,
                  real * esz, padded * esz);

            slices.push_back({t, first_elem, real, padded});
        }

        /* Start every tile before waiting on any of them; the wait
         * loop below is what makes four tiles four times the work in
         * one wall clock, rather than four times in sequence. */
        for (const auto &s : slices) {
            Tile &tile = D.tiles[s.tile];
            runs.push_back(tile.k(mode, static_cast<uint64_t>(s.padded),
                                  tile.a, tile.b, tile.c, tile.d));
        }
        for (auto &r : runs)
            r.wait();
    } catch (const std::exception &e) {
        set_err(std::string("submitting work: ") + e.what());
        return ST_INTERNAL;
    }

    /* Faults before results. If the memory system did not vouch for
     * the data then comparing the output against anything is
     * meaningless, because the bits under test were never delivered. */
    uint32_t status_acc = 0, flag_acc = 0;
    if (D.flags_readable) {
        try {
            for (const auto &s : slices) {
                status_acc |= D.tiles[s.tile].k.read_register(CSR_STATUS);
                flag_acc   |= D.tiles[s.tile].k.read_register(CSR_FLAGS);
            }
        } catch (const std::exception &e) {
            set_err(std::string("reading status: ") + e.what());
            return ST_INTERNAL;
        }
    }
    if (status_acc) {
        if (bus)
            *bus = status_acc;
        set_err("kernel reported bus faults; the output is not valid");
        return ST_BUS_FAULT;
    }

    try {
        for (const auto &s : slices) {
            Tile &tile = D.tiles[s.tile];
            tile.d.sync(XCL_BO_SYNC_BO_FROM_DEVICE, s.padded * esz, 0);
            std::memcpy(pd + s.first_elem * esz, tile.d.map<uint8_t *>(),
                        s.real * esz);
        }
    } catch (const std::exception &e) {
        set_err(std::string("reading results: ") + e.what());
        return ST_INTERNAL;
    }

    if (flags)
        *flags = flag_acc;
    return ST_OK;
}
