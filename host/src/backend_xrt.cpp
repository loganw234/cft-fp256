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
 * single-tile image, on the software backend, and on a laptop.
 *
 * The total amount of zero padding is `beats_total * epb - n`, which
 * does not depend on the tile count either, so the flag word is the
 * same for any partitioning as well.
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
 * elements too, so the OR is unchanged either way.
 *
 * host/tests/api_test.c checks that claim against the software model
 * over every opcode, format and attribute. It does not exercise this
 * file's padding path, which needs a device; the quad hw_emu image is
 * what covers that.
 *
 * ---------------------------------------------------------------
 * Failure is not recoverable in place
 * ---------------------------------------------------------------
 *
 * If a launch or a wait throws, compute units are still running. XRT's
 * run destructor releases a command slot; it does not stop a CU, and
 * this RTL has no abort. Worse, rtl/cft_csr.sv gates the start pulse
 * on `!busy` and answers every write with BRESP OKAY, so a start
 * issued to a busy CU is dropped *silently* - and the next poll of
 * CTRL sees the PREVIOUS run's done bit and reports success. The
 * caller would then read that previous run's output buffer and flags.
 *
 * Same inputs, different bits, depending on timing. That is precisely
 * the failure this product exists to rule out, so a failed run poisons
 * the device: every later call refuses until the handle is closed and
 * reopened, which is the only way to know the CUs are idle again.
 */

#include <algorithm>
#include <chrono>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <exception>
#include <new>
#include <string>
#include <vector>

#include <xrt/xrt_bo.h>
#include <xrt/xrt_device.h>
#include <xrt/xrt_kernel.h>

#include "backend.h"
#include "slice.h"

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
 * managing execution. */
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

/* The hardware contract this library speaks. A bitstream announcing
 * anything else has a register map or an opcode meaning this code does
 * not know, and guessing is how a host reads a result it has
 * misinterpreted. Bump both together, deliberately. */
constexpr uint32_t KNOWN_VERSION = 0x00000410u;

/* kernel.xml argument ids */
constexpr int ARG_A = 2, ARG_B = 3, ARG_C = 4, ARG_D = 5;

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

/* How long to wait for a run before calling it hung.
 *
 * This is not belt and braces. cft_engine_stream.sv records a short or
 * long read burst in err_acc and then never completes, so a fabric
 * fault presents as a CU that is simply never done - and an
 * indefinite wait turns that into a hung process with no diagnosis,
 * because the fault register can only be read after the wait returns.
 *
 * Emulation runs orders of magnitude slower than silicon, so it wants
 * a long timeout - but not an arbitrarily long one.
 *
 * CAP is 20 minutes because a timeout past about 35 minutes does not
 * work: 2^31 microseconds is 2147 seconds, and a value beyond that
 * overflows somewhere below this API. The symptom is not a spurious
 * timeout, which would be obvious - it is a wait that never returns
 * at all, on a kernel that has already finished. That cost an evening
 * here: the engine's own trace showed the run completing while the
 * host sat in a polling loop, which reads exactly like a hardware or
 * scheduler fault and is neither.
 *
 * So the cap is deliberate and the margin is generous. If a run
 * legitimately needs longer than twenty minutes, something else is
 * wrong and a timeout is the right answer. */
long timeout_ms()
{
    const long CAP = 20L * 60L * 1000L;
    long ms;
    if (const char *e = std::getenv("CFT_TIMEOUT_MS"))
        ms = std::strtol(e, nullptr, 10);
    else if (std::getenv("XCL_EMULATION_MODE"))
        ms = CAP;
    else
        ms = 60L * 1000L;
    if (ms <= 0 || ms > CAP)
        ms = CAP;
    return ms;
}

struct Tile {
    xrt::kernel k;
    xrt::bo     a, b, c, d;
    size_t      cap = 0;         /* bytes per buffer, 0 if unallocated */
};

struct Dev {
    xrt::device       dev;
    xrt::uuid         uuid;
    std::vector<Tile> tiles;
    long              wait_ms = 60000;
    /* Set when a run failed with compute units possibly still active.
     * See the header comment: there is no way to make the device safe
     * again from here, so the handle is finished. */
    bool              poisoned = false;
};

/* Grow a tile's buffers to hold `bytes`.
 *
 * Buffers are cached across calls because allocating and mapping a
 * device buffer costs far more than the transfer at the sizes a first
 * port will use; a caller who does not want the copy at all has
 * cft_alloc().
 *
 * `cap` is cleared first and only restored once all four allocations
 * have succeeded, so it is never larger than the buffers actually are.
 * Each buffer is also released before its replacement is requested:
 * growing four buffers inside one HBM group would otherwise need the
 * old and new sizes simultaneously, and fail at a little over a third
 * of the group rather than at two thirds. */
void ensure_capacity(Dev &D, Tile &t, size_t bytes)
{
    if (t.cap >= bytes)
        return;
    t.cap = 0;
    xrt::bo *bufs[4] = {&t.a, &t.b, &t.c, &t.d};
    const int args[4] = {ARG_A, ARG_B, ARG_C, ARG_D};
    for (int i = 0; i < 4; i++) {
        *bufs[i] = xrt::bo();                       /* release first */
        *bufs[i] = xrt::bo(D.dev, bytes, xrt::bo::flags::normal,
                           t.k.group_id(args[i]));
    }
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
    Dev *D = new (std::nothrow) Dev();
    if (!D)
        return ST_OUT_OF_MEMORY;
    D->wait_ms = timeout_ms();

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
     * status registers to be readable at all.
     *
     * The FIRST failure's message is kept, because the commonest
     * reason cft_krnl_1 will not open is that another process holds
     * it - and reporting live contention as "this is not a tile" sends
     * the reader to entirely the wrong place. */
    std::string first_failure;
    for (int i = 1; i <= MAX_TILES; i++) {
        std::string nm = "cft_krnl:{cft_krnl_" + std::to_string(i) + "}";
        try {
            xrt::kernel k(D->dev, D->uuid, nm,
                          xrt::kernel::cu_access_mode::exclusive);
            D->tiles.emplace_back();
            D->tiles.back().k = std::move(k);
        } catch (const std::exception &e) {
            if (i == 1)
                first_failure = e.what();
            break;
        }
    }
    if (D->tiles.empty()) {
        delete D;
        set_err(std::string("no cft_krnl compute unit could be opened in ") +
                artifact + ": " + first_failure +
                " (a compute unit already held by another process reports"
                " the same way as one that is not there)");
        return ST_ARTIFACT;
    }

    /* Ask the hardware what it is before believing the filename. */
    uint32_t magic = 0, caps = 0, ver = 0;
    try {
        magic = D->tiles[0].k.read_register(CSR_MAGIC);
        ver   = D->tiles[0].k.read_register(CSR_VERSION);
        caps  = D->tiles[0].k.read_register(CSR_CAPS);
    } catch (const std::exception &e) {
        /* Refuse, rather than carry on with the flags disabled.
         *
         * The status registers are not a nicety here. FLAGS carries
         * the IEEE exceptions, which are half of what this library
         * promises to reproduce; STATUS carries the bus faults, which
         * are how a caller learns its results were computed on bits
         * the memory system never delivered. Without them every run
         * would return CFT_OK with unverifiable data and no way to
         * tell the difference - and CAPS would have to be guessed,
         * which on a trimmed bitstream means issuing a precision the
         * bitstream does not carry and receiving a buffer of zeros
         * with clean flags. A library whose product is exception-exact
         * reproducibility cannot run in that mode. */
        delete D;
        set_err(std::string("status registers are unreadable on this "
                            "runtime, so exception flags and bus faults "
                            "cannot be reported and capabilities cannot "
                            "be read: ") + e.what());
        return ST_UNSUPPORTED;
    }

    if (magic != TILE_MAGIC) {
        char buf[160];
        std::snprintf(buf, sizeof buf,
                      "not a cft tile: MAGIC reads 0x%08x, expected 0x%08x",
                      magic, TILE_MAGIC);
        delete D;
        set_err(buf);
        return ST_ARTIFACT;
    }
    if (ver != KNOWN_VERSION) {
        char buf[200];
        std::snprintf(buf, sizeof buf,
                      "hardware contract 0x%08x, this library speaks "
                      "0x%08x - the register map or an opcode meaning may "
                      "differ, and guessing is how a host misreads a result",
                      ver, KNOWN_VERSION);
        delete D;
        set_err(buf);
        return ST_UNSUPPORTED;
    }

    *format_mask    = caps & 0xFu;
    *op_groups      = (caps >> 8) & 0xFFu;
    *tiles          = static_cast<uint32_t>(D->tiles.size());
    *version        = ver;
    *flags_readable = 1;      /* proven above, or we did not get here */
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
    g_err.clear();

    if (D.poisoned) {
        set_err("this device handle was left in an unknown state by an "
                "earlier failure; close it and open it again");
        return ST_INTERNAL;
    }

    const size_t esz = static_cast<size_t>(elem_bytes(fmt));
    if (esz == 0)
        return ST_INVALID_ARGUMENT;

    const size_t ntiles = D.tiles.size();
    const uint32_t mode = static_cast<uint32_t>(op & 0xFF) |
                          (static_cast<uint32_t>(fmt & 0xF) << 8) |
                          (static_cast<uint32_t>(rnd & 0x7) << 12);

    const auto *pa = static_cast<const uint8_t *>(a);
    const auto *pb = static_cast<const uint8_t *>(b);
    const auto *pc = static_cast<const uint8_t *>(c);
    auto *pd = static_cast<uint8_t *>(d);

    /* The split itself is in slice.h, as a pure function, so that
     * host/tests can exercise it over every interesting n and tile
     * count without a card - which is where the arithmetic that
     * decides whether every element is computed exactly once belongs.
     */
    std::vector<cft_slice> slices(ntiles);
    slices.resize(cft_plan_slices(n, esz, ntiles, slices.data()));

    /* Staging touches only host-visible buffers and starts nothing, so
     * a failure here leaves every compute unit idle and the device
     * perfectly reusable. */
    try {
        for (const auto &s : slices) {
            Tile &tile = D.tiles[s.tile];
            ensure_capacity(D, tile, s.padded * esz);
            stage(tile.a, pa ? pa + s.first_elem * esz : nullptr,
                  s.real * esz, s.padded * esz);
            stage(tile.b, pb ? pb + s.first_elem * esz : nullptr,
                  s.real * esz, s.padded * esz);
            stage(tile.c, pc ? pc + s.first_elem * esz : nullptr,
                  s.real * esz, s.padded * esz);
        }
    } catch (const std::bad_alloc &) {
        set_err("out of memory staging operands");
        return ST_OUT_OF_MEMORY;
    } catch (const std::exception &e) {
        /* An HBM group is finite - under hw/link_quad.cfg each tile
         * owns four pseudo-channels - so "could not allocate" is a
         * routine capacity limit and should not read as a library
         * bug. */
        const std::string what = e.what();
        if (what.find("alloc") != std::string::npos ||
            what.find("memory") != std::string::npos ||
            what.find("Memory") != std::string::npos) {
            set_err("device buffer allocation failed (each tile's HBM "
                    "group is finite; try a smaller n or cft_alloc): " +
                    what);
            return ST_OUT_OF_MEMORY;
        }
        set_err("staging operands: " + what);
        return ST_INTERNAL;
    }

    /* From here a compute unit may be running, so every failure
     * poisons the handle rather than returning to a caller who would
     * reasonably retry. */
    std::vector<xrt::run> runs;
    runs.reserve(slices.size());
    int status = ST_OK;
    std::string err;

    for (const auto &s : slices) {
        try {
            Tile &tile = D.tiles[s.tile];
            runs.push_back(tile.k(mode, static_cast<uint64_t>(s.padded),
                                  tile.a, tile.b, tile.c, tile.d));
        } catch (const std::exception &e) {
            err = std::string("starting tile ") + std::to_string(s.tile) +
                  ": " + e.what();
            status = ST_INTERNAL;
            break;      /* stop launching, but still wait on the started */
        }
    }

    /* Wait on EVERY run that was started, including after a failure -
     * abandoning one leaves a compute unit writing into a buffer this
     * process still owns. */
    for (auto &r : runs) {
        try {
            ert_cmd_state st = r.wait(std::chrono::milliseconds(D.wait_ms));
            if (st != ERT_CMD_STATE_COMPLETED && status == ST_OK) {
                status = (st == ERT_CMD_STATE_TIMEOUT) ? ST_TIMEOUT
                                                       : ST_INTERNAL;
                err = "a compute unit did not complete (state " +
                      std::to_string(static_cast<int>(st)) + ")";
            }
        } catch (const std::exception &e) {
            if (status == ST_OK) {
                status = ST_INTERNAL;
                err = std::string("waiting for a compute unit: ") + e.what();
            }
        }
    }

    if (status != ST_OK) {
        D.poisoned = true;
        set_err(err + " - compute units may still be active, so this "
                      "handle is finished; close and reopen it");
        return status;
    }

    /* Faults before results. If the memory system did not vouch for
     * the data then comparing the output against anything is
     * meaningless, because the bits under test were never delivered.
     *
     * Only the tiles that actually ran are read. A tile left idle
     * still holds its previous run's sticky words - the engine clears
     * them at start, not at completion - so OR-ing over all tiles
     * would make this run's flags depend on the call history. */
    uint32_t status_acc = 0, flag_acc = 0;
    try {
        for (const auto &s : slices) {
            status_acc |= D.tiles[s.tile].k.read_register(CSR_STATUS);
            flag_acc   |= D.tiles[s.tile].k.read_register(CSR_FLAGS);
        }
    } catch (const std::exception &e) {
        D.poisoned = true;
        set_err(std::string("reading status after a run: ") + e.what());
        return ST_INTERNAL;
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
