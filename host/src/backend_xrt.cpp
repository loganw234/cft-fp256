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
/* The second capability word, since 0x800 (docs/SEQUENCER.md revision
 * 3, R4/R5): [3:0] log2 of the scratch depth, [4] scratch present, [5]
 * scratch I/O present, [7:6] reserved, [31:8] reserved for what comes
 * next. Read-only, and the one register the map grew that this code
 * reads rather than XRT writing it. */
constexpr uint32_t CSR_CAPS2   = 0x6C;
constexpr uint32_t TILE_MAGIC  = 0x43465430u;   /* "CFT0" */
/* The sequencer's pointer registers are NOT in this list, and that is
 * deliberate: PROG_PTR (0x54), CNT_PTR (0x5C), BANK_PTR (0x64 low,
 * 0x68 high) since 0x700, and SCRATCH_IN_PTR (0x70/0x74) and
 * SCRATCH_OUT_PTR (0x78/0x7C) since 0x800 are KERNEL ARGUMENTS - 6, 7,
 * 8, 9 and 10 in hw/kernel.xml - and XRT writes each buffer's device
 * address into its own register when the run is submitted. A host that
 * also wrote them would be writing them twice, from two different
 * notions of where the buffer is. They are named here so the map is
 * readable beside the registers this code does touch. */

/* The hardware contracts this library speaks.
 *
 * VERSION guards the REGISTER MAP. A bitstream announcing something not
 * in this list has a register at an address this code does not know,
 * and guessing is how a host reads a result it has misinterpreted.
 *
 * It is a LIST rather than one value, and that is the point. Adding an
 * opcode group does not move a register, so a tile at 0x500 and a tile
 * at 0x410 are read identically; what differs is what they implement,
 * and that is CAPS's job, which every call already consults through
 * cft_supports(). Insisting on a single version would have orphaned the
 * card-day images the moment reductions landed - a host refusing a
 * bitstream whose registers it understands perfectly, over a feature it
 * was not going to use.
 *
 *   0x410  v0.4.1  four rungs, five rounding attributes
 *   0x500  v0.5.0  adds the reduction group (CAPS bit 13)
 *   0x600  v0.6.0  adds PROG_PTR and CNT_PTR, and two kernel arguments
 *   0x700  v0.7.0  adds BANK_PTR at 0x64/0x68 and a ninth kernel
 *                  argument, `bank` on the A master - the sequencer's
 *                  per-run constant bank (docs/SEQUENCER.md revision
 *                  2, R3). CAPS[6] says whether a tile at this
 *                  contract will TAKE one, and the loader asks that
 *                  rather than this
 *   0x800  v0.8.0  adds CAPS2 at 0x6C (read-only), SCRATCH_IN_PTR at
 *                  0x70/0x74 and SCRATCH_OUT_PTR at 0x78/0x7C, with
 *                  two more kernel arguments - `scratch_in` (id 9) on
 *                  the A master beside the image and the bank, and
 *                  `scratch_out` (id 10) on the D master beside the
 *                  deposits and the counts. The per-lane scratch
 *                  memory and its per-run block (docs/SEQUENCER.md
 *                  revision 3, R4 and R5). CAPS2[4] and CAPS2[5] say
 *                  whether a tile at this contract HAS them, and the
 *                  loader asks that rather than this
 *
 * Add a version here only when the map is genuinely unchanged; move the
 * map and this list should shrink to the versions that share it.
 *
 * 0x600 is the first bump that GREW the map rather than only adding a
 * capability, and the old entries stay for exactly the reason the list
 * exists: 0x410 and 0x500 tiles are still read correctly by this code,
 * they simply have nothing at 0x54. What they cannot do is run a
 * program, and SEQ_VERSION below is what says so - a kernel call with
 * eight arguments against a six-argument xclbin does not misbehave
 * subtly, it throws, and a clear refusal beats an XRT exception.
 *
 * 0x700 grows it again the same way and the same reasoning applies
 * twice over: a 0x600 tile is read correctly here and simply has
 * nothing at 0x64, and BANK_VERSION below is what refuses a banked run
 * against it. The card-day images are 0x410 and predate all of it.
 *
 * 0x800 is the third growth and the third time the same three things
 * are true: every older tile is still read correctly, it simply has
 * nothing at 0x6C, and SCRATCH_VERSION below refuses a run that
 * carries a scratch block against it. The ARGUMENT COUNT is what makes
 * that refusal necessary rather than tidy - eleven arguments against a
 * nine-argument xclbin throws from inside XRT with a message about
 * argument counts. */
constexpr uint32_t KNOWN_VERSIONS[] = { 0x00000410u, 0x00000500u,
                                        0x00000600u, 0x00000700u,
                                        0x00000800u };
constexpr uint32_t SEQ_VERSION = 0x00000600u;   /* first map with PROG_PTR */
constexpr uint32_t BANK_VERSION = 0x00000700u;  /* first map with BANK_PTR */
/* first map with CAPS2 and the two scratch pointers */
constexpr uint32_t SCRATCH_VERSION = 0x00000800u;

inline bool version_known(uint32_t v)
{
    for (uint32_t k : KNOWN_VERSIONS)
        if (v == k) return true;
    return false;
}

/* kernel.xml argument ids. `bank` is 8, on m_axi_a - it rides the A
 * master as the program image does, and the two never overlap in time
 * (hw/kernel.xml, docs/SEQUENCER.md revision 2). `scratch_in` is 9 and
 * rides the A master for the same reason and in its own phase;
 * `scratch_out` is 10 and rides the D master beside the deposits and
 * the counts, because it is written rather than read (revision 3, R5). */
constexpr int ARG_A = 2, ARG_B = 3, ARG_C = 4, ARG_D = 5;
constexpr int ARG_PROG = 6, ARG_CNT = 7, ARG_BANK = 8;
constexpr int ARG_SCRATCH_IN = 9, ARG_SCRATCH_OUT = 10;

/* MODE[15]: this run belongs to cft_seq and MODE[7:0] is ignored. */
constexpr uint32_t MODE_SEQ = 1u << 15;

/* STATUS, as rtl/cft_csr.sv lays it out. Bit 4 is also
 * CFT_STATUS_DEPOSIT_OVERFLOW in the public header; the two must not
 * drift, and this file cannot include cft.h. */
constexpr uint32_t ST_BUS_BITS  = 0x7u;
constexpr uint32_t ST_REFUSED   = 0x8u;
constexpr uint32_t ST_DEPOSIT_OVERFLOW = 0x10u;

/* Round `n` up to a whole 256-bit beat's worth of bytes. The masters
 * move whole beats whatever the format, so a buffer that ends mid-beat
 * is a buffer the last transfer runs off the end of. */
inline size_t beat_round(size_t bytes)
{
    return (bytes + 31u) & ~static_cast<size_t>(31u);
}

/* The most compute units this backend will bind on one device.
 *
 * Not a prediction that 64 will ever be built as one bitstream - the
 * area and HBM pseudo-channel budgets cap a monolithic tile at about
 * eight (docs/SCALING.md), and past that the shape is many devices
 * rather than many CUs. It is here because the number is free: CU
 * discovery is a loop over names, tiles are a std::vector, and every
 * partitioning property is already tested to 64 in api_test. A limit
 * that binds before the hardware does is a limit that gets discovered
 * on card day. */
constexpr int MAX_TILES = 64;

std::string g_err;

void set_err(const std::string &s) { g_err = s; }

/* A status word as eight hex digits. STATUS is a bit field and the
 * bits are what the reader needs; decimal would have to be converted
 * by hand at the exact moment nobody wants to. */
std::string hex32(uint32_t v)
{
    char b[9];
    std::snprintf(b, sizeof b, "%08x", static_cast<unsigned>(v));
    return std::string(b);
}

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
    /* The sequencer's two extra buffers. They are separate rather than
     * folded into `cap` because they are not operand-shaped: the
     * program image is tens of bytes and never grows with n, and the
     * counts are four bytes per element whatever the format. Growing
     * them with the operands would allocate a megabyte of HBM to hold
     * a hundred-byte program. */
    xrt::bo     pg, cn;
    size_t      pg_cap = 0, cn_cap = 0;
    /* And the third, since 0x700: the per-run constant bank, argument
     * 8 on the A master. Sized like the image and for the same reason -
     * a bank is n_consts format-width values, tens or hundreds of
     * bytes, and never grows with n. It is allocated on a 0x700 tile
     * even for a program that carries its own constants, because the
     * kernel has the argument either way and XRT will not submit a run
     * with one unbound; the tile never reads it in that case. */
    xrt::bo     bk;
    size_t      bk_cap = 0;
    /* And the two of 0x800: the per-run scratch block in and out,
     * arguments 9 and 10. These DO grow with n - the block is
     * n_scratch_in slots a lane - so they are sized per run like the
     * counts buffer rather than like the image, and for the same
     * reason they are not folded into `cap`: their shape is the
     * program's slot count, not the operand width. A program that
     * declares no scratch I/O still gets one beat of each bound,
     * because the kernel has the arguments either way and XRT will not
     * submit a run with one unbound; the tile never reads or writes
     * them in that case. */
    xrt::bo     si, so;
    size_t      si_cap = 0, so_cap = 0;
};

struct Dev {
    xrt::device       dev;
    xrt::uuid         uuid;
    std::vector<Tile> tiles;
    uint32_t          version = 0;
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

/* Grow one buffer, for the two that are not operand-shaped. Same
 * release-before-request discipline as ensure_capacity, and the same
 * reason: an HBM group is finite, and asking for the new size while
 * still holding the old one fails at half the group. */
void ensure_one(Dev &D, Tile &t, xrt::bo &bo, size_t &cap, int arg,
                size_t bytes)
{
    if (cap >= bytes)
        return;
    cap = 0;
    bo = xrt::bo();
    bo = xrt::bo(D.dev, bytes, xrt::bo::flags::normal, t.k.group_id(arg));
    cap = bytes;
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

/* ====================================================================
 * Device-resident buffers (cft.h's cft_alloc; backend.h's seam)
 *
 * WHAT A DEVICE COPY IS. Not "the buffer, on the card". Each compute
 * unit's four AXI masters own one HBM pseudo-channel each (hw/link.cfg,
 * hw/link_quad.cfg), so memory reachable by tile 1's `a` port is
 * reachable by nothing else - not by tile 2's `a` port and not by tile
 * 1's `b` port. A copy is therefore per (TILE, ROLE), and one host
 * buffer feeding a four-tile run as `a` has four of them.
 *
 * WHAT A COPY HOLDS: exactly the WINDOW that tile was last asked for -
 * its slice of the run, padded up to a whole 256-bit beat with zeros,
 * which is precisely what stage() puts in a staging buffer today. Two
 * consequences, and they are the design:
 *
 *   - the kernel argument is the copy ITSELF, at its own base address,
 *     so nothing here needs an XRT SUB-BUFFER. That matters: a
 *     sub-buffer's offset must satisfy the device's base-address
 *     alignment, measured at 4096 bytes on the XRT this project builds
 *     against (xrt_core::bo::alignment(), XRT 2.14.354), while
 *     slice.h cuts at 32-byte beats. Binding a window at an offset the
 *     runtime is entitled to round would be the one failure this
 *     mechanism must not have, and holding the cuts to 4096 would mean
 *     a different partition for resident runs than for staged ones -
 *     two answers where the contract promises one. Per-tile slice
 *     copies avoid the question entirely, and cost less HBM as well:
 *     each tile holds its own quarter rather than the whole array.
 *
 *   - a copy is REUSED only when the window is the same one again.
 *     That is the common case by construction - the same call in a
 *     loop asks for the same n, the same format and the same tile
 *     count, so every tile wants the window it already has - and when
 *     it is not, the copy refills, which costs exactly what staging
 *     costs and never more. There is no case in which residency is
 *     slower than the staged path it replaces.
 *
 * WHO IS AUTHORITATIVE is cft.h's rule and this is its machinery:
 * `gen` is bumped whenever the host mirror becomes the truth, a copy
 * remembers the `gen` it was filled at, and a copy a run WROTE is
 * `dirty` until cftx_buffer_from_device carries it home. device.c
 * calls that itself before the buffer can be read, so a caller who
 * skips it pays the transfer rather than reading the run before last.
 * ==================================================================== */

/* Role index (backend.h's CFT_ROLE_*) to kernel argument id. */
constexpr int ROLE_ARG[4] = {ARG_A, ARG_B, ARG_C, ARG_D};

struct BufCopy {
    xrt::bo  bo;
    size_t   off    = 0;      /* first byte of the buffer this holds */
    size_t   real   = 0;      /* bytes of the caller's data in it */
    size_t   padded = 0;      /* bytes allocated: whole beats */
    uint64_t gen    = 0;      /* the buffer generation it was filled at */
    bool     live   = false;  /* the bo exists and the window means
                               * something */
    bool     dirty  = false;  /* a run wrote this window and the mirror
                               * has not been told */
};

struct Buf {
    Dev                 *D = nullptr;
    uint8_t             *host = nullptr;   /* device.c owns this */
    size_t               bytes = 0;
    /* Bumped every time the mirror becomes the truth. Starts at 1 so
     * that a copy's zero-initialised `gen` can never be mistaken for
     * current. */
    uint64_t             gen = 1;
    std::vector<BufCopy> copies;           /* tiles * 4, [t * 4 + role] */
    uint64_t             resident_binds = 0, staged_binds = 0;
    std::string          why;
};

/* Carry one copy's window home. The whole copy is synced and only the
 * real bytes are written into the mirror: the pad is beat padding this
 * file put there and is nobody's data. */
void buf_flush(Buf &B, BufCopy &c)
{
    if (!c.dirty)
        return;
    c.bo.sync(XCL_BO_SYNC_BO_FROM_DEVICE, c.padded, 0);
    std::memcpy(B.host + c.off, c.bo.map<uint8_t *>(), c.real);
    c.dirty = false;
}

/* Bind one operand of one slice, or decline.
 *
 * Returns the buffer object to hand the kernel, or nullptr to say
 * "stage this one from host memory as before" - which is never wrong,
 * only slower, and is what every failure here degrades to.
 *
 * `output` is the D role: its contents before the run are nobody's
 * business, so a window that matches binds whatever generation it was
 * filled at, and a fresh one is not filled at all. */
xrt::bo *buf_bind(Buf &B, size_t tile, int role, size_t off,
                  size_t real, size_t padded, bool output)
{
    if (!B.D || tile >= B.D->tiles.size() || role < 0 || role > 3)
        return nullptr;

    BufCopy &c = B.copies[tile * 4 + static_cast<size_t>(role)];
    const bool same_window =
        c.live && c.off == off && c.real == real && c.padded == padded;

    if (same_window && (output || c.gen == B.gen)) {
        B.resident_binds++;
        return &c.bo;
    }

    /* Whatever a previous run wrote into this copy has to reach the
     * mirror before the window is repurposed OR the binding is given
     * up on, or the bytes are simply lost - the one place in this file
     * where a performance path could silently drop a result. It
     * happens BEFORE the decision to decline for exactly that reason:
     * a declined output is staged instead, and the staged path writes
     * the mirror itself when the run finishes, so this copy's older
     * window must land first or it would overwrite the newer bytes on
     * the next cft_buffer_from_device. */
    if (c.dirty)
        buf_flush(B, c);

    if (off > B.bytes || real > B.bytes - off) {
        /* device.c's registry already refuses a window that overruns,
         * so reaching this means the slice arithmetic and the lookup
         * disagree. Stage, and say so rather than serve short bytes. */
        B.why = "the window runs past the end of the buffer";
        B.staged_binds++;
        return nullptr;
    }

    if (!c.live || c.padded != padded) {
        try {
            c.live = false;
            c.bo = xrt::bo();          /* release before requesting */
            c.bo = xrt::bo(B.D->dev, padded, xrt::bo::flags::normal,
                           B.D->tiles[tile].k.group_id(ROLE_ARG[role]));
        } catch (const std::exception &e) {
            /* An HBM channel is 256 MB a tile. A buffer that does not
             * fit one is staged in slices, exactly as a plain host
             * pointer is, and the run still gives the right answer. */
            c.live = false;
            B.why = std::string("no device memory for this window (each "
                                "tile's channel is 256 MB): ") + e.what();
            if (B.why.size() > 200)
                B.why.resize(200);
            B.staged_binds++;
            return nullptr;
        }
    }
    c.off = off; c.real = real; c.padded = padded; c.live = true;
    c.dirty = false;
    c.gen = B.gen;

    if (!output) {
        auto *p = c.bo.map<uint8_t *>();
        std::memcpy(p, B.host + off, real);
        if (padded > real)
            std::memset(p + real, 0, padded - real);
        c.bo.sync(XCL_BO_SYNC_BO_TO_DEVICE, padded, 0);
        B.staged_binds++;
        B.why = same_window
                    ? "the mirror was republished, so this copy refilled"
                    : "first use of this window on this tile and role";
    } else {
        /* Nothing crossed the bus: an output copy is written by the
         * tile, and allocating one is not a transfer. */
        B.resident_binds++;
    }
    return &c.bo;
}

/* After a successful run, the copies the tiles wrote hold bytes the
 * mirror does not. Only ever called on ST_OK: a failed run's output is
 * not valid, and marking it authoritative would let a later
 * cftx_buffer_from_device carry a bus fault's leavings into the
 * caller's array. */
void buf_mark_written(Buf &B, size_t tile, int role)
{
    BufCopy &c = B.copies[tile * 4 + static_cast<size_t>(role)];
    if (c.live)
        c.dirty = true;
}

}  // namespace

extern "C" const char *cftx_last_error(void)
{
    return g_err.c_str();
}

extern "C" int cftx_open(const char *artifact, int index, void **out,
                         uint32_t *format_mask, uint32_t *op_groups,
                         uint32_t *tiles, uint32_t *version,
                         int *flags_readable, cft_seq_caps *seq)
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
    uint32_t magic = 0, caps = 0, ver = 0, caps2 = 0;
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
    if (!version_known(ver)) {
        char buf[256];
        std::snprintf(buf, sizeof buf,
                      "hardware contract 0x%08x is not one this library "
                      "knows (0x%08x, 0x%08x, 0x%08x, 0x%08x, 0x%08x) - the "
                      "register map may differ, and guessing is how a host "
                      "misreads a result. What a tile IMPLEMENTS is CAPS, "
                      "not this.",
                      ver, KNOWN_VERSIONS[0], KNOWN_VERSIONS[1],
                      KNOWN_VERSIONS[2], KNOWN_VERSIONS[3],
                      KNOWN_VERSIONS[4]);
        delete D;
        set_err(buf);
        return ST_UNSUPPORTED;
    }

    /* CAPS2 only where the map has it. A tile below 0x800 has nothing
     * at 0x6C, and reading a register that is not there is not a
     * question with a defined answer - so it is not asked, and the
     * word stays zero, which the decode below reads as no scratch and
     * an unknown depth. Read AFTER the version check for exactly that
     * reason: the version is what says the register exists. */
    if (ver >= SCRATCH_VERSION) {
        try {
            caps2 = D->tiles[0].k.read_register(CSR_CAPS2);
        } catch (const std::exception &e) {
            delete D;
            set_err(std::string("this bitstream's contract is 0x800, whose "
                                "map has CAPS2 at 0x6C, and reading it "
                                "failed: ") + e.what());
            return ST_UNSUPPORTED;
        }
    }

    D->version      = ver;
    *format_mask    = caps & 0xFu;
    *op_groups      = (caps >> 8) & 0xFFu;
    *tiles          = static_cast<uint32_t>(D->tiles.size());
    *version        = ver;
    *flags_readable = 1;      /* proven above, or we did not get here */
    if (seq) {
        /* CAPS[27:16] carries the EXPONENT of each capacity - four bits
         * each, which only fits because every one of them is a power of
         * two by construction (two memory depths and a field width;
         * rtl/cft_krnl.sv names them once and hands them to cft_seq as
         * parameters). Shift, do not transcribe: a literal 64 here is
         * how a host would go on believing a trimmed tile was a full
         * one.
         *
         * A tile whose VERSION predates these fields reads zeros, and
         * cft_caps documents zero as UNKNOWN - so the caps check in
         * cft_program_load simply does not fire against it, which is
         * the behaviour that tile had before the fields existed. The
         * card-day images are 0x410 and are exactly that case. */
        const uint32_t sizes = (caps >> 16) & 0xFFFu;
        /* The feature nibble, and above it the ALU extensions of
         * CAPS[31:28] - IMUL is bit 28, cft.h's CFT_ALU_EXT_IMUL.
         *
         * The nibble shift already carries revision 2's two new bits
         * and needed no change for them: CAPS[5] lands in
         * seq_features bit 1 (CFT_SEQ_FEAT_REGS32) and CAPS[6] in bit
         * 2 (CFT_SEQ_FEAT_BANK_PTR), which is what the field was
         * shaped for. Shift, do not enumerate. */
        seq->features = ((caps >> 4) & 0xFu) | (((caps >> 28) & 0xFu) << 4);
        /* CAPS2[7:4] is the second sequencer feature nibble and lands
         * in seq_features bits 11:8, which is CFT_SEQ_FEAT_SCRATCH at
         * [4] and CFT_SEQ_FEAT_SCRATCH_IO at [5]. Shift, do not
         * enumerate, exactly as the first nibble does - the two bits
         * revision 3 assigns and the two it reserves travel together. */
        seq->features |= ((caps2 >> 4) & 0xFu) << 8;
        /* And the depth: CAPS2[3:0] is log2 of it, meaningful only
         * where CAPS2[4] says the memory is there. A tile below 0x800
         * reads a zero word here, which is no scratch and a depth of
         * zero - UNKNOWN, and enforced against nothing, which is the
         * behaviour such a tile had before the register existed. */
        seq->max_scratch = (caps2 & 0x10u) ? (1u << (caps2 & 0xFu)) : 0u;
        if (sizes == 0) {
            seq->max_deposits = 0;
            seq->max_insns    = 0;
            seq->max_consts   = 0;
        } else {
            seq->max_deposits = 1u << ((caps >> 16) & 0xFu);
            seq->max_insns    = 1u << ((caps >> 20) & 0xFu);
            seq->max_consts   = 1u << ((caps >> 24) & 0xFu);
        }
    }
    *out            = D;
    return ST_OK;
}

extern "C" void cftx_close(void *hw)
{
    delete static_cast<Dev *>(hw);
}

/* ---- the buffer seam (backend.h) ---------------------------------- */

extern "C" int cftx_buffer_create(void *hw, void *host, size_t bytes,
                                  void **out)
{
    if (!hw || !host || bytes == 0 || !out)
        return ST_INVALID_ARGUMENT;
    *out = nullptr;
    Dev &D = *static_cast<Dev *>(hw);
    Buf *B = new (std::nothrow) Buf();
    if (!B)
        return ST_OUT_OF_MEMORY;
    B->D = &D;
    B->host = static_cast<uint8_t *>(host);
    B->bytes = bytes;
    try {
        /* Sized once and never resized, because buf_bind hands out a
         * pointer INTO this vector and a reallocation would leave the
         * kernel holding a dangling one. The tile count cannot change
         * during a device's life. */
        B->copies.resize(D.tiles.size() * 4);
    } catch (const std::exception &) {
        delete B;
        return ST_OUT_OF_MEMORY;
    }
    *out = B;
    return ST_OK;
}

extern "C" void cftx_buffer_destroy(void *buf)
{
    /* Whatever a run wrote and nobody read back goes with it, which is
     * what cft_buffer_free means and what cft.h says. */
    delete static_cast<Buf *>(buf);
}

extern "C" int cftx_buffer_to_device(void *buf)
{
    if (!buf)
        return ST_INVALID_ARGUMENT;
    Buf &B = *static_cast<Buf *>(buf);
    /* The mirror is the truth: every copy is stale and every claim a
     * run had on the contents is dropped. Nothing moves - each copy
     * refills at its next binding, for the window that binding needs,
     * rather than for a window nobody may ask for again. */
    B.gen++;
    for (auto &c : B.copies)
        c.dirty = false;
    return ST_OK;
}

extern "C" int cftx_buffer_from_device(void *buf)
{
    if (!buf)
        return ST_INVALID_ARGUMENT;
    Buf &B = *static_cast<Buf *>(buf);
    bool moved = false;
    try {
        for (auto &c : B.copies) {
            if (!c.dirty)
                continue;
            buf_flush(B, c);
            moved = true;
        }
    } catch (const std::exception &e) {
        set_err(std::string("reading a resident buffer back: ") + e.what());
        return ST_INTERNAL;
    }
    /* Only when something actually came back. A no-op read must not
     * invalidate the input copies, or a caller who calls this after
     * every run - which is the correct thing to do - would refill them
     * every time and never see the rate this exists for. */
    if (moved)
        B.gen++;
    return ST_OK;
}

extern "C" void cftx_buffer_stat(void *buf, int *resident,
                                 int *device_authority,
                                 uint64_t *resident_binds,
                                 uint64_t *staged_binds,
                                 char *why, size_t why_bytes)
{
    if (!buf)
        return;
    Buf &B = *static_cast<Buf *>(buf);
    int live = 0, dirty = 0;
    for (const auto &c : B.copies) {
        if (c.live)   live = 1;
        if (c.dirty)  dirty = 1;
    }
    if (resident)         *resident = live;
    if (device_authority) *device_authority = dirty;
    if (resident_binds)   *resident_binds = B.resident_binds;
    if (staged_binds)     *staged_binds = B.staged_binds;
    if (why && why_bytes) {
        std::snprintf(why, why_bytes, "%s", B.why.c_str());
    }
}

extern "C" int cftx_run(void *hw, int op, int fmt, int rnd,
                        const void *a, const void *b, const void *c,
                        void *d, size_t n, const cft_bindings *bind,
                        uint32_t *flags, uint32_t *bus)
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
     *
     * A SEQUENCER run does not come through here and is NOT split:
     * cftx_program_run below uses tile 0 and only tile 0. An
     * elementwise element depends on its own index and nothing else,
     * which is what makes this partitioning unobservable; a sequencer
     * lane depends on its own index too, but the early exit is a
     * CROSS-LANE condition, so "four tiles give the same bits as one"
     * is a claim about P3 (docs/SEQUENCER.md) rather than a corollary
     * of the dataflow. It is very probably true and it is not yet
     * fuzzed, so v1 does not assume it.
     */
    std::vector<cft_slice> slices(ntiles);
    slices.resize(cft_plan_slices(n, esz, ntiles, slices.data()));

    /* Which buffer object each of this slice's four operands is bound
     * to. A null entry means "the tile's own staging buffer", which is
     * what every operand was before resident buffers existed - so a
     * run with no bindings at all walks exactly the old path. */
    struct SliceBind { xrt::bo *bo[4]; };
    std::vector<SliceBind> sb(slices.size());
    for (auto &e : sb) { e.bo[0] = e.bo[1] = e.bo[2] = e.bo[3] = nullptr; }

    /* Staging touches only host-visible buffers and starts nothing, so
     * a failure here leaves every compute unit idle and the device
     * perfectly reusable. Binding a resident buffer allocates and may
     * fill, which is the same kind of work and the same guarantee. */
    try {
        const uint8_t *src[4] = {pa, pb, pc, nullptr};
        for (size_t i = 0; i < slices.size(); i++) {
            const cft_slice &s = slices[i];
            Tile &tile = D.tiles[s.tile];
            size_t staged_need = 0;

            for (int r = 0; r < 4; r++) {
                if (!bind || !bind->buf[r])
                    continue;
                Buf &B = *static_cast<Buf *>(bind->buf[r]);
                sb[i].bo[r] = buf_bind(B, s.tile, r,
                                       bind->off[r] + s.first_elem * esz,
                                       s.real * esz, s.padded * esz,
                                       r == CFT_ROLE_D);
            }
            /* The tile's own buffers are grown only for what is left,
             * and not at all when every operand is resident: one cap
             * still covers all four, so asking for the run's size when
             * nothing needs it would take HBM from the copies. */
            for (int r = 0; r < 4; r++)
                if (!sb[i].bo[r])
                    staged_need = s.padded * esz;
            ensure_capacity(D, tile, staged_need);

            xrt::bo *tb[4] = {&tile.a, &tile.b, &tile.c, &tile.d};
            for (int r = 0; r < CFT_ROLE_D; r++) {
                if (sb[i].bo[r])
                    continue;                     /* already on the device */
                stage(*tb[r], src[r] ? src[r] + s.first_elem * esz : nullptr,
                      s.real * esz, s.padded * esz);
            }
            for (int r = 0; r < 4; r++)
                if (!sb[i].bo[r])
                    sb[i].bo[r] = tb[r];
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

    for (size_t i = 0; i < slices.size(); i++) {
        const cft_slice &s = slices[i];
        try {
            Tile &tile = D.tiles[s.tile];
            runs.push_back(tile.k(mode, static_cast<uint64_t>(s.padded),
                                  *sb[i].bo[0], *sb[i].bo[1],
                                  *sb[i].bo[2], *sb[i].bo[3]));
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
        /* Read STATUS anyway, best effort.
         *
         * This is the whole reason the timeout exists rather than an
         * indefinite wait: the engine records a short or long read
         * burst in err_acc and then never completes, and err_acc can
         * only be read once the wait has returned. Returning here
         * without reading it throws away the one diagnosis the timeout
         * was introduced to obtain, and leaves "a compute unit did not
         * complete" as the entire explanation of a bus fault.
         *
         * Reading a status register of a CU that may still be running
         * is safe - it is an AXI-Lite read of a sticky word, and the
         * value is what it is. The DATA buffers stay untouched. */
        uint32_t st_acc = 0;
        try {
            for (const auto &s : slices)
                st_acc |= D.tiles[s.tile].k.read_register(CSR_STATUS);
        } catch (const std::exception &) {
            st_acc = 0;           /* the handle is going away regardless */
        }
        if (bus)
            *bus = st_acc;
        set_err(err + " - compute units may still be active, so this "
                      "handle is finished; close and reopen it" +
                (st_acc == 0x8u
                     ? " (STATUS 0x8 - only a REFUSAL is latched; the "
                       "units never started this run's work, so this is "
                       "a hang or a slow run, not a memory fault)"
                 : st_acc ? " (STATUS 0x" + hex32(st_acc) +
                          " - the memory system reported a fault, so this "
                          "is a bus problem rather than a slow run)"
                        : " (STATUS clean on every unit that ran, so this "
                          "is a hang or a genuinely slow run rather than "
                          "a bus fault)"));
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
        /* STATUS[3] is the precision refusal, not a bus fault: the run
         * never started and no memory moved. Reaching it through
         * libcft means the device's CAPS and its refusal logic
         * disagree with each other - the library checks CAPS before
         * issuing - so name that loudly rather than folding it into
         * "the memory system misbehaved". A single tile can never
         * report both (the kernel masks the engine's stale sticky
         * while its last start was refused - the adversarial review
         * caught the ORed-truths version); bits 2:0 beside bit 3 can
         * only mean DIFFERENT tiles refused and faulted, and the
         * faulting tile's invalid data is the worse fact. */
        if ((status_acc & 0x8u) && !(status_acc & 0x7u)) {
            /* the contract scopes *bus to CFT_ERR_BUS_FAULT, so the
             * refusal keeps its detail in the message alone */
            set_err("kernel REFUSED the run: MODE selected a precision "
                    "this bitstream does not implement (STATUS 0x" +
                    hex32(status_acc) + "). CAPS advertised otherwise, "
                    "which is a device/library disagreement worth "
                    "reporting");
            return ST_UNSUPPORTED;
        }
        if (bus)
            *bus = status_acc;
        set_err("kernel reported bus faults; the output is not valid");
        return ST_BUS_FAULT;
    }

    try {
        for (size_t i = 0; i < slices.size(); i++) {
            const cft_slice &s = slices[i];
            Tile &tile = D.tiles[s.tile];
            /* A RESIDENT output does not come back. The bytes are on
             * the device, that copy is now the authority, and the
             * caller collects them with cft_buffer_from_device when it
             * wants them - which is the whole saving on this side of
             * the call, and the reason the rule in cft.h exists. */
            if (bind && bind->buf[CFT_ROLE_D] && sb[i].bo[3] != &tile.d) {
                buf_mark_written(*static_cast<Buf *>(bind->buf[CFT_ROLE_D]),
                                 s.tile, CFT_ROLE_D);
                continue;
            }
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

/* ---- sequencer programs -------------------------------------------
 *
 * ONE compute unit, and the comment beside cftx_run's partitioning
 * says why: the early exit is a cross-lane condition, so splitting
 * lanes across tiles is a claim about P3 rather than a corollary of
 * the dataflow, and v1 does not make claims it has not fuzzed.
 *
 * Six buffers rather than four. The program image rides the A master
 * (the sequencer borrows it for the image AND the three input
 * streams, which never overlap in time) and the deposit counts ride
 * the D master beside the deposits - which is what puts each in the
 * HBM group its master can reach, per hw/kernel.xml and hw/link.cfg.
 *
 * The deposit buffer is NOT pre-zeroed here. Every slot in the window
 * is the tile's to write, including the ones no lane deposited into -
 * SEQUENCER.md calls the +0 normative for exactly that reason - so
 * zeroing first would make a tile that skipped a slot indistinguishable
 * from one that wrote the zero it promised.
 */
extern "C" int cftx_program_run(void *hw, int fmt, const void *image,
                                size_t image_bytes,
                                const cft_seq_run_io *io,
                                uint32_t max_deposits,
                                const void *a, const void *b, const void *c,
                                void *deposits, uint32_t *counts, size_t n,
                                const cft_bindings *bind,
                                uint32_t *flags, uint32_t *bus)
{
    if (!hw || !image || image_bytes == 0 || !io)
        return ST_INVALID_ARGUMENT;
    const void *bank         = io->bank;
    const size_t bank_bytes  = io->bank_bytes;
    const void *scratch_in   = io->scratch_in;
    const size_t sin_bytes   = io->scratch_in_bytes;
    void *scratch_out        = io->scratch_out;
    const size_t sout_bytes  = io->scratch_out_bytes;
    if (bank_bytes && !bank)
        return ST_INVALID_ARGUMENT;
    if ((sin_bytes && !scratch_in) || (sout_bytes && !scratch_out))
        return ST_INVALID_ARGUMENT;

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

    /* A tile whose map predates PROG_PTR has no register to write it
     * to and no seventh argument to bind. Refuse here rather than let
     * an eight-argument kernel call throw from inside XRT, where the
     * message is about argument counts and not about what is actually
     * wrong: this bitstream cannot run programs. */
    if (D.version < SEQ_VERSION) {
        char buf[224];
        std::snprintf(buf, sizeof buf,
                      "this bitstream's contract is 0x%08x, which has no "
                      "PROG_PTR - the sequencer arrived at 0x%08x. Run the "
                      "program on the software backend, or load a newer "
                      "image; CAPS bit 15 says in advance which it is.",
                      D.version, SEQ_VERSION);
        set_err(buf);
        return ST_UNSUPPORTED;
    }
    /* And a tile whose map predates BANK_PTR has no register for a
     * bank and no ninth argument to bind it to. cft_program_load has
     * already refused a BANK_EXT image against a tile whose CAPS[6] is
     * clear, which is the refusal a caller should see; this is the
     * second line of the same defence, for a device whose CAPS and
     * whose VERSION disagree. Same reasoning as the check above: a
     * nine-argument kernel call against an eight-argument xclbin
     * throws from inside XRT with a message about argument counts. */
    if (bank_bytes && D.version < BANK_VERSION) {
        char buf[224];
        std::snprintf(buf, sizeof buf,
                      "this bitstream's contract is 0x%08x, which has no "
                      "BANK_PTR - the per-run constant bank arrived at "
                      "0x%08x. CAPS bit 6 says in advance which it is.",
                      D.version, BANK_VERSION);
        set_err(buf);
        return ST_UNSUPPORTED;
    }
    /* And the same again for the scratch block, a third time and for
     * the third identical reason: a tile below 0x800 has no
     * SCRATCH_IN_PTR, no SCRATCH_OUT_PTR and no tenth or eleventh
     * kernel argument. cft_program_load has already refused a
     * SCRATCH_IO image against a tile whose CAPS2[5] is clear, which
     * is the refusal a caller should see; this is the second line of
     * the same defence, for a device whose CAPS2 and whose VERSION
     * disagree. */
    if ((sin_bytes || sout_bytes) && D.version < SCRATCH_VERSION) {
        char buf[256];
        std::snprintf(buf, sizeof buf,
                      "this bitstream's contract is 0x%08x, which has no "
                      "SCRATCH_IN_PTR or SCRATCH_OUT_PTR - the per-run "
                      "scratch block arrived at 0x%08x. CAPS2 bit 5 says in "
                      "advance which it is.",
                      D.version, SCRATCH_VERSION);
        set_err(buf);
        return ST_UNSUPPORTED;
    }

    if (n == 0) {
        if (flags) *flags = 0;
        if (bus)   *bus   = 0;
        return ST_OK;
    }
    if (max_deposits && !deposits)
        return ST_INVALID_ARGUMENT;
    if (max_deposits && n > (static_cast<size_t>(-1) / max_deposits / esz))
        return ST_INVALID_ARGUMENT;

    const size_t epb        = 32u / esz;         /* elements per beat */
    const size_t real_bytes = n * esz;
    const size_t opnd_bytes = ((n + epb - 1) / epb) * epb * esz;
    const size_t dep_bytes  = beat_round(n * max_deposits * esz);
    const size_t cnt_bytes  = beat_round(n * 4);
    const size_t img_bytes  = beat_round(image_bytes);
    /* One beat when there is no bank, so a 0x700 tile's ninth argument
     * is always a real, addressable buffer. beat_round(0) is 0 and a
     * zero-length xrt::bo is not something to rely on. */
    const size_t bnk_bytes  = bank_bytes ? beat_round(bank_bytes) : 32u;
    /* The two scratch blocks, on exactly the same terms: bound on
     * every 0x800 run whether or not the program declares one, with a
     * minimum of one beat when it does not. Unlike the bank they grow
     * with n - the block is n_scratch_in slots for each of n lanes -
     * so they are sized per run and cached by ensure_one like the
     * counts buffer. */
    const size_t sin_pad    = sin_bytes  ? beat_round(sin_bytes)  : 32u;
    const size_t sout_pad   = sout_bytes ? beat_round(sout_bytes) : 32u;

    Tile &tile = D.tiles[0];

    /* Which of the four operand-shaped buffers came from cft_alloc.
     * The image, the bank, the counts and the two scratch blocks are
     * staged always: none of them is operand-shaped, the image and the
     * bank do not grow with n at all, and the counts are four bytes an
     * element whatever the format. */
    xrt::bo *ob[4] = {nullptr, nullptr, nullptr, nullptr};

    /* Staging touches only host-visible buffers and starts nothing, so
     * a failure here leaves the compute unit idle and reusable. */
    try {
        if (bind) {
            const void *src[3] = {a, b, c};
            for (int r = 0; r < 3; r++)
                if (bind->buf[r] && src[r])
                    ob[r] = buf_bind(*static_cast<Buf *>(bind->buf[r]),
                                     0, r, bind->off[r], real_bytes,
                                     opnd_bytes, false);
            if (bind->buf[CFT_ROLE_D] && deposits && max_deposits)
                ob[3] = buf_bind(*static_cast<Buf *>(bind->buf[CFT_ROLE_D]),
                                 0, CFT_ROLE_D, bind->off[CFT_ROLE_D],
                                 n * max_deposits * esz, dep_bytes, true);
        }

        /* One cap covers a, b, c and d together, so the operand
         * buffers come out as large as the deposit window -
         * max_deposits times bigger than they need to be. That is the
         * price of leaving the elementwise path's allocator alone for
         * v1; the fix when it bites is a cap per buffer rather than
         * one for four, not a second allocator.
         *
         * What residency changes is only which of the four still need
         * it: a run whose operands are all resident asks for the
         * deposit window alone. The d buffer gets a beat whatever
         * happens, because a program with max_deposits of zero is
         * legal and XRT will not submit a run with an argument
         * unbound. */
        size_t need = 0;
        if (!ob[0] || !ob[1] || !ob[2])
            need = opnd_bytes;
        if (!ob[3])
            need = std::max(need, std::max(dep_bytes, static_cast<size_t>(32)));
        ensure_capacity(D, tile, need);
        ensure_one(D, tile, tile.pg, tile.pg_cap, ARG_PROG, img_bytes);
        ensure_one(D, tile, tile.cn, tile.cn_cap, ARG_CNT, cnt_bytes);
        if (D.version >= BANK_VERSION)
            ensure_one(D, tile, tile.bk, tile.bk_cap, ARG_BANK, bnk_bytes);
        if (D.version >= SCRATCH_VERSION) {
            ensure_one(D, tile, tile.si, tile.si_cap, ARG_SCRATCH_IN,
                       sin_pad);
            ensure_one(D, tile, tile.so, tile.so_cap, ARG_SCRATCH_OUT,
                       sout_pad);
        }
        if (!ob[0])
            stage(tile.a, static_cast<const uint8_t *>(a), real_bytes,
                  opnd_bytes);
        if (!ob[1])
            stage(tile.b, static_cast<const uint8_t *>(b), real_bytes,
                  opnd_bytes);
        if (!ob[2])
            stage(tile.c, static_cast<const uint8_t *>(c), real_bytes,
                  opnd_bytes);
        {
            xrt::bo *tb[4] = {&tile.a, &tile.b, &tile.c, &tile.d};
            for (int r = 0; r < 4; r++)
                if (!ob[r])
                    ob[r] = tb[r];
        }
        /* The image WHOLE, whatever it holds. A BANK_EXT image is a
         * header and an instruction stream and has no constant section
         * to send - cft_program_load sized it that way and kept the
         * exact bytes - so nothing here has to strip one out, which is
         * the same reason the image was kept whole in the first place:
         * what executes is what was loaded. */
        stage(tile.pg, static_cast<const uint8_t *>(image), image_bytes,
              img_bytes);
        /* The bank, staged exactly as the image is: a NULL source
         * zeroes the buffer, which is what a program that carries its
         * own constants leaves at argument 8 and the tile never
         * reads. */
        if (D.version >= BANK_VERSION)
            stage(tile.bk, static_cast<const uint8_t *>(bank), bank_bytes,
                  bnk_bytes);
        /* The scratch-IN block, staged exactly as the bank is: a NULL
         * source zeroes the buffer, which is what a program declaring
         * no scratch I/O leaves at argument 9 and the tile never
         * reads. The scratch-OUT buffer is not staged at all - it is
         * the tile's to write, the same reason the deposit window is
         * not pre-zeroed here, and every element of it is written by a
         * run that declares one. */
        if (D.version >= SCRATCH_VERSION)
            stage(tile.si, static_cast<const uint8_t *>(scratch_in),
                  sin_bytes, sin_pad);
    } catch (const std::bad_alloc &) {
        set_err("out of memory staging a program");
        return ST_OUT_OF_MEMORY;
    } catch (const std::exception &e) {
        const std::string what = e.what();
        if (what.find("alloc") != std::string::npos ||
            what.find("memory") != std::string::npos ||
            what.find("Memory") != std::string::npos) {
            set_err("device buffer allocation failed (a program's deposit "
                    "window is n * max_deposits elements, so it outgrows an "
                    "HBM group sooner than an elementwise run does): " + what);
            return ST_OUT_OF_MEMORY;
        }
        set_err("staging a program: " + what);
        return ST_INTERNAL;
    }

    /* MODE[7:0] is not written because it is ignored: the program says
     * what to compute. So is the rounding field - every instruction
     * carries its own attribute, which is the whole reason one pass
     * can produce both interval bounds. N is the caller's element
     * count and NOT the padded one: lanes at or beyond it start
     * inactive, which is how beat padding is made harmless for a
     * program whose map nobody has read. */
    const uint32_t mode = MODE_SEQ |
                          (static_cast<uint32_t>(fmt & 0xF) << 8);

    int status = ST_OK;
    std::string err;
    try {
        /* Three shapes, because the ARGUMENT COUNT is what the contract
         * version guards: a 0x600 xclbin's kernel takes eight, a
         * 0x700's takes nine and an 0x800's takes eleven, and XRT
         * throws rather than adapts. Every buffer the map has is bound
         * on every run of that contract whether or not this program
         * uses it - the bank on a 0x700, the two scratch blocks on an
         * 0x800; the tile reads or writes each only when the image's
         * flags say BANK_EXT or SCRATCH_IO. */
        xrt::run r = (D.version >= SCRATCH_VERSION)
                   ? tile.k(mode, static_cast<uint64_t>(n),
                            *ob[0], *ob[1], *ob[2], *ob[3],
                            tile.pg, tile.cn, tile.bk, tile.si, tile.so)
                   : (D.version >= BANK_VERSION)
                   ? tile.k(mode, static_cast<uint64_t>(n),
                            *ob[0], *ob[1], *ob[2], *ob[3],
                            tile.pg, tile.cn, tile.bk)
                   : tile.k(mode, static_cast<uint64_t>(n),
                            *ob[0], *ob[1], *ob[2], *ob[3],
                            tile.pg, tile.cn);
        ert_cmd_state st = r.wait(std::chrono::milliseconds(D.wait_ms));
        if (st != ERT_CMD_STATE_COMPLETED) {
            status = (st == ERT_CMD_STATE_TIMEOUT) ? ST_TIMEOUT : ST_INTERNAL;
            err = "the compute unit did not complete a program (state " +
                  std::to_string(static_cast<int>(st)) + ")";
        }
    } catch (const std::exception &e) {
        status = ST_INTERNAL;
        err = std::string("running a program: ") + e.what();
    }

    if (status != ST_OK) {
        D.poisoned = true;
        /* Same best-effort read as cftx_run, and the same reason: the
         * fault register can only be read once the wait has returned,
         * so breaking out before reading it throws away the diagnosis
         * the timeout exists to obtain. */
        uint32_t st_acc = 0;
        try {
            st_acc = tile.k.read_register(CSR_STATUS);
        } catch (const std::exception &) {
            st_acc = 0;
        }
        if (bus)
            *bus = st_acc & ST_DEPOSIT_OVERFLOW;
        set_err(err + " - the compute unit may still be active, so this "
                      "handle is finished; close and reopen it" +
                (st_acc ? " (STATUS 0x" + hex32(st_acc) + ")"
                        : " (STATUS clean, so this is a hang or a genuinely "
                          "long program rather than a bus fault)"));
        return status;
    }

    uint32_t status_acc = 0, flag_acc = 0;
    try {
        status_acc = tile.k.read_register(CSR_STATUS);
        flag_acc   = tile.k.read_register(CSR_FLAGS);
    } catch (const std::exception &e) {
        D.poisoned = true;
        set_err(std::string("reading status after a program: ") + e.what());
        return ST_INTERNAL;
    }

    /* Faults before results, as everywhere in this file. Three
     * outcomes rather than the elementwise path's two, because a
     * sequencer adds a bit that is a REPORT and not a failure. */
    if ((status_acc & ST_REFUSED) && !(status_acc & ST_BUS_BITS)) {
        /* Two things reach this bit: a precision the bitstream does
         * not carry, and a program image the tile threw back. The
         * library checked CAPS before loading the program, and
         * cft_program_load validated the image, so either one means
         * the device and this code disagree about something both
         * thought was settled - which is worth naming rather than
         * folding into a bus story. The run did not happen: the
         * deposit buffer holds whatever it held, and the image may
         * have been READ but nothing was written. */
        set_err("kernel REFUSED the program (STATUS 0x" + hex32(status_acc) +
                "): either MODE selected a precision this bitstream does "
                "not implement, or the tile rejected the program image - "
                "too many instructions, constants or deposit slots for its "
                "on-chip memories, or a header it did not recognise. "
                "Nothing was computed and nothing was written.");
        return ST_UNSUPPORTED;
    }
    if (status_acc & ST_BUS_BITS) {
        if (bus)
            *bus = status_acc;
        set_err("kernel reported bus faults during a program; the deposits "
                "are not valid");
        return ST_BUS_FAULT;
    }

    try {
        /* dep_bytes is zero when max_deposits is, and max_deposits of
         * zero is a legal program rather than a rejected one: the
         * model validates it, the tile accepts it, and every DEPOSIT
         * overflows into STATUS[4]. There is nothing to bring back, so
         * the transfer is skipped rather than issued for no bytes -
         * the memcpy below is already guarded and a zero-length DMA is
         * at best a no-op that XRT is under no obligation to define. */
        /* A RESIDENT deposit window does not come back: the tile wrote
         * it, that copy is the authority now, and the caller collects
         * it with cft_buffer_from_device. Every slot is still written
         * - the untouched ones as +0, which SEQUENCER.md makes
         * normative - so what comes home later is the whole window and
         * not a partial one. */
        if (ob[3] != &tile.d) {
            buf_mark_written(*static_cast<Buf *>(bind->buf[CFT_ROLE_D]), 0,
                             CFT_ROLE_D);
        } else {
            if (dep_bytes)
                tile.d.sync(XCL_BO_SYNC_BO_FROM_DEVICE, dep_bytes, 0);
            if (deposits && max_deposits)
                std::memcpy(deposits, tile.d.map<uint8_t *>(),
                            n * max_deposits * esz);
        }
        tile.cn.sync(XCL_BO_SYNC_BO_FROM_DEVICE, cnt_bytes, 0);
        if (counts)
            std::memcpy(counts, tile.cn.map<uint8_t *>(), n * 4);
        /* And the scratch-out block, on exactly the same terms as the
         * deposits: skipped entirely when the program declares none,
         * so a run that touches neither pointer costs neither
         * transfer. */
        if (sout_bytes) {
            tile.so.sync(XCL_BO_SYNC_BO_FROM_DEVICE, sout_pad, 0);
            std::memcpy(scratch_out, tile.so.map<uint8_t *>(), sout_bytes);
        }
    } catch (const std::exception &e) {
        set_err(std::string("reading program results: ") + e.what());
        return ST_INTERNAL;
    }

    if (flags)
        *flags = flag_acc;
    /* The deposit overflow travels in *bus on a SUCCESSFUL run, which
     * is the one place this library puts something there without
     * returning CFT_ERR_BUS_FAULT. It is not a fault: the deposits
     * that fit are correct and reproducible, and what the caller lost
     * is the tail. Telling it the results are invalid would be a
     * worse lie than saying nothing. */
    if (bus)
        *bus = status_acc & ST_DEPOSIT_OVERFLOW;
    return ST_OK;
}

/* ---- reductions ---------------------------------------------------
 *
 * One range per tile, round-robin when there are more ranges than
 * tiles. Each tile is handed the TRUE element count for its range,
 * not a padded one: the engine takes ceil(n / elements-per-beat) beats
 * for a reduction and consumes only the real elements from the last,
 * because padding a sum with +0.0 is not the identity. The buffer
 * still has to hold whole beats, so the staging pads the memory - the
 * arithmetic simply never reaches it.
 */
extern "C" int cftx_reduce(void *hw, int op, int fmt, int rnd,
                           const void *a,
                           const size_t *lo, const size_t *hi,
                           size_t nranges, void *partials,
                           const cft_bindings *bind,
                           uint32_t *flags, uint32_t *bus)
{
    if (!hw || !a || !lo || !hi || !partials || nranges == 0)
        return ST_INVALID_ARGUMENT;

    Dev &D = *static_cast<Dev *>(hw);
    if (D.poisoned) {
        set_err("device handle is poisoned by an earlier failure");
        return ST_INTERNAL;
    }

    const size_t esz = static_cast<size_t>(elem_bytes(fmt));
    if (esz == 0)
        return ST_INVALID_ARGUMENT;
    const size_t epb = 32u / esz;              /* elements per 256-bit beat */

    const size_t ntiles = D.tiles.size();
    const uint32_t mode = static_cast<uint32_t>(op & 0xFF) |
                          (static_cast<uint32_t>(fmt & 0xF) << 8) |
                          (static_cast<uint32_t>(rnd & 0x7) << 12);

    const auto *pa = static_cast<const uint8_t *>(a);
    auto *pp = static_cast<uint8_t *>(partials);

    /* Ranges beyond the tile count reuse a tile, so they cannot all be
     * in flight at once. Launch a wave per tile-sized group and wait
     * before reusing a unit - the RTL silently drops a start issued to
     * a busy CU, which would return the previous range's answer.
     *
     * THERE ARE ROUTINELY MORE RANGES THAN TILES. It is not an edge
     * case and it is not only about huge n: the tree's canonical cut
     * of [0, n) into at most `parts` NODES needs one extra range
     * whenever n is a power of two plus a remainder, so four tiles get
     * five ranges at n = 5, 9, 17, 33, 65, ... and eight tiles get
     * more than eight for 49 of the first thousand n.
     *
     * Which is why staging happens HERE, per wave, and not once up
     * front for every range. Staging all of them first wrote range k
     * into tile k % ntiles, so with five ranges and four tiles range 4
     * overwrote range 0's operands before range 0 had ever been
     * launched - and wave 0 then reduced the wrong data with the right
     * length, giving a wrong sum with clean STATUS and plausible
     * flags. Nothing reported an error.
     *
     * The cost is that a staging failure in a later wave happens after
     * earlier waves have already run. That is harmless: a reduction
     * leaves nothing behind on the device but the tiles' own buffers,
     * and the host discards every partial on any error. */
    int status = ST_OK;
    std::string err;
    uint32_t fl = 0, bs = 0;

    for (size_t base = 0; base < nranges && status == ST_OK; base += ntiles) {
        const size_t wave = std::min(ntiles, nranges - base);
        std::vector<xrt::run> runs;
        runs.reserve(wave);

        /* Which object carries this wave's `a` for each tile: the
         * resident buffer's own copy of that range, or the tile's
         * staging buffer. b, c and d are the tile's either way - b and
         * c are zeros this file makes up, and one element of d is the
         * answer - so `a` is the only operand a reduction can save,
         * which is also the only one that carries the whole vector. */
        std::vector<xrt::bo *> wa(wave, nullptr);

        try {
            for (size_t j = 0; j < wave; j++) {
                const size_t k = base + j;
                const size_t m = hi[k] - lo[k];
                const size_t padded = ((m + epb - 1) / epb) * epb;
                Tile &tile = D.tiles[j];
                if (bind && bind->buf[CFT_ROLE_A])
                    wa[j] = buf_bind(*static_cast<Buf *>(bind->buf[CFT_ROLE_A]),
                                     j, CFT_ROLE_A,
                                     bind->off[CFT_ROLE_A] + lo[k] * esz,
                                     m * esz, padded * esz, false);
                ensure_capacity(D, tile, padded * esz);
                if (!wa[j]) {
                    stage(tile.a, pa + lo[k] * esz, m * esz, padded * esz);
                    wa[j] = &tile.a;
                }
                /* b and c are unread by a sum, but the engine streams
                 * all three - one read enable feeds all three FIFOs -
                 * so they must be real, readable memory of the same
                 * length. */
                stage(tile.b, nullptr, m * esz, padded * esz);
                stage(tile.c, nullptr, m * esz, padded * esz);
            }
        } catch (const std::bad_alloc &) {
            set_err("out of memory staging a reduction");
            return ST_OUT_OF_MEMORY;
        } catch (const std::exception &e) {
            set_err(std::string("staging a reduction: ") + e.what());
            return ST_INTERNAL;
        }

        for (size_t j = 0; j < wave; j++) {
            const size_t k = base + j;
            const size_t m = hi[k] - lo[k];
            try {
                Tile &tile = D.tiles[j];
                runs.push_back(tile.k(mode, static_cast<uint64_t>(m),
                                      *wa[j], tile.b, tile.c, tile.d));
            } catch (const std::exception &e) {
                err = std::string("starting tile ") + std::to_string(j) +
                      " for a reduction: " + e.what();
                status = ST_INTERNAL;
                break;
            }
        }

        for (auto &r : runs) {
            try {
                ert_cmd_state st = r.wait(std::chrono::milliseconds(D.wait_ms));
                if (st != ERT_CMD_STATE_COMPLETED && status == ST_OK) {
                    status = (st == ERT_CMD_STATE_TIMEOUT) ? ST_TIMEOUT
                                                           : ST_INTERNAL;
                    err = "a compute unit did not complete a reduction "
                          "(state " + std::to_string(static_cast<int>(st)) +
                          ")";
                }
            } catch (const std::exception &e) {
                if (status == ST_OK) {
                    status = ST_INTERNAL;
                    err = std::string("waiting on a reduction: ") + e.what();
                }
            }
        }
        if (status != ST_OK) {
            D.poisoned = true;
            /* Same best-effort STATUS read as cftx_run: the timeout is
             * how a fabric fault becomes readable at all, so breaking
             * out before reading it discards the diagnosis. */
            try {
                for (size_t j = 0; j < wave; j++)
                    bs |= D.tiles[j].k.read_register(CSR_STATUS);
            } catch (const std::exception &) {
                /* handle is finished either way */
            }
            err += bs ? " (STATUS 0x" + hex32(bs) + " - a memory fault, "
                        "not merely a slow run)"
                      : " (STATUS clean on every unit in this wave)";
            break;
        }

        /* Collect this wave before the next one reuses the tiles.
         * Faults before results, for the reason cftx_run gives: if the
         * memory system did not vouch for the data then the partial is
         * meaningless, and only the tiles that ran are read, because an
         * idle tile still holds its previous run's sticky words. */
        for (size_t j = 0; j < wave; j++) {
            const size_t k = base + j;
            try {
                Tile &tile = D.tiles[j];
                bs |= tile.k.read_register(CSR_STATUS);
                fl |= tile.k.read_register(CSR_FLAGS);
                /* One beat comes back; one element of it is the answer,
                 * and the engine zeroed the rest. */
                tile.d.sync(XCL_BO_SYNC_BO_FROM_DEVICE, 32, 0);
                std::memcpy(pp + k * esz, tile.d.map<uint8_t *>(), esz);
            } catch (const std::exception &e) {
                D.poisoned = true;
                set_err(std::string("reading a reduction result: ") + e.what());
                return ST_INTERNAL;
            }
        }
    }


    /* The run's own failure is reported BEFORE the status word, which
     * is the opposite order to the success path and deliberate. A
     * reduction that timed out has a STATUS read taken from a unit
     * that may still be running, so letting a non-zero bs turn a
     * ST_TIMEOUT into a ST_BUS_FAULT would relabel the failure on the
     * strength of a register sampled mid-flight. The status word is
     * still delivered through *bus and named in the message, which is
     * the part that helps. */
    if (status != ST_OK) {
        set_err(err);
        return status;
    }
    if (bs != 0) {
        /* Same split as the elementwise path: STATUS[3] alone is the
         * precision refusal - no run, no data - and a device refusing
         * what its CAPS advertised is its own report, not a bus story. */
        if ((bs & 0x8u) && !(bs & 0x7u)) {
            /* *bus stays scoped to CFT_ERR_BUS_FAULT, as backend.h and
             * cft.h promise */
            set_err("kernel REFUSED the reduction: MODE selected a "
                    "precision this bitstream does not implement "
                    "(STATUS 0x" + hex32(bs) + ")");
            return ST_UNSUPPORTED;
        }
        if (bus) *bus = bs;
        set_err("the memory system reported a fault during a reduction; "
                "the result is not to be trusted");
        return ST_BUS_FAULT;
    }
    if (flags) *flags = fl;
    return ST_OK;
}
