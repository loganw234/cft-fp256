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
#include <cerrno>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <exception>
#include <functional>
#include <memory>
#include <new>
#include <stdexcept>
#include <string>
#include <thread>
#include <vector>

#include <xrt/xrt_bo.h>
#include <xrt/xrt_device.h>
#include <xrt/xrt_kernel.h>
/* The xclbin listing API, where this XRT has it. The discriminator is
 * the NEWER header path: XRT 2.19 (amd-arc-box) ships it at
 * xrt/experimental/xrt_xclbin.h; XRT 2.14 (the cft2204 WSL distro) has
 * no xrt/experimental/ at all, so a 2.14 build takes the probe below.
 * That is the detection's choice, not a missing API: 2.14's
 * experimental/xrt_xclbin.h is 21,405 bytes and declares get_kernels()
 * and get_cus() (measured 2026-09-25; this comment called it an EMPTY
 * file until then, which verifier-V2 found false), and the backend
 * compiles with CFT_XRT_XCLBIN_API forced on against it - but whether
 * 2.14's listing works at run time has never been seen on a card.
 * Without the API, compute units are found the way they always were,
 * by probing cft_krnl_1.. by name. */
#if defined(__has_include)
#  if __has_include(<xrt/experimental/xrt_xclbin.h>)
#    include <xrt/experimental/xrt_xclbin.h>
#    define CFT_XRT_XCLBIN_API 1
#  endif
#endif
#ifndef CFT_XRT_XCLBIN_API
#  define CFT_XRT_XCLBIN_API 0
#endif

#include "backend.h"
#include "caps_decode.h"   /* VERSION, CAPS, CAPS2 -> cft_seq_caps */
#include "slice.h"
#include "mask_bits.h"
#include "tile_select.h"
#include "lane_cut.h"
/* The image digest cft_get_image_id reports is sha256.c's, which
 * CFT_NO_PROGRAM compiles out (cft_config.h, where CFT_TINY implies it).
 * The combination is refused here, by name, rather than at the link by
 * an undefined symbol. */
#include "sha256.h"
#include "../include/cft_config.h"
#ifdef CFT_NO_PROGRAM
#  error "the XRT backend hashes the image it loads with sha256.c, which CFT_NO_PROGRAM (or CFT_TINY) removes - build XRT=1 without it"
#endif
/* ABI 0.18's device lines (cft.h, cft_image_id): the kernel clock the
 * image's own BUILD_METADATA states, read by the one copy api-test holds
 * to synthetic images on every host. */
#include "xclbin_clock.h"
/* And the XRT version the library is built against: its version header,
 * at the path a newer XRT ships it, else the older one (XRT 2.14, the
 * cft2204 distro, has include/version.h). Its XRT_DRIVER_VERSION macro is
 * the version, a comma, and the commit; where neither header or the macro
 * is there, the version is "" - not known - and the build is unchanged. */
#if defined(__has_include)
#  if __has_include(<xrt/detail/version.h>)
#    include <xrt/detail/version.h>
#  elif __has_include(<version.h>)
#    include <version.h>
#  endif
#endif

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
/* CTRL, read only as the completion witness in run_job: [0] ap_start,
 * [1] ap_done - which CLEARS ON READ, and which XRT's scheduler polls -
 * [2] ap_idle, [3] ap_ready. The witness reads it at the two moments
 * no command of this process is outstanding on the tile: before a start
 * and after XRT has reported the run complete. */
constexpr uint32_t CSR_CTRL    = 0x00;
constexpr uint32_t CTRL_START  = 0x1u;
constexpr uint32_t CTRL_IDLE   = 0x4u;
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
                                        0x00000800u, 0x00000900u,
                                        0x00000A00u, 0x00000B00u };
constexpr uint32_t SEQ_VERSION = 0x00000600u;   /* first map with PROG_PTR */
constexpr uint32_t BANK_VERSION = 0x00000700u;  /* first map with BANK_PTR */
/* first map with CAPS2 and the two scratch pointers */
constexpr uint32_t SCRATCH_VERSION = 0x00000800u;
/* 0x900 (2026-09-14): SEG and NRES at 0x80/0x84, kernel argument 11 - a
 * reduction's segment length and result count, zero for the whole
 * array - passed as the TWELFTH ARGUMENT of every reduction launched on
 * such a tile, with the map's other buffers bound as the program launch
 * binds them. Not written through the handle: the first version did,
 * and the card returned one result where a thousand were due, because
 * XRT's start sends the whole argument register image and a declared
 * argument the launch did not set goes out as zero, erasing the pair.
 * The pair travels with the launch or not at all; zero for a
 * whole-array reduction, so one after a segmented one inherits nothing. */
constexpr uint32_t SEG_VERSION = 0x00000900u;
/* 0xA00 (2026-09-15, docs/ROUND2.md P0): five pointer registers at
 * 0x88..0xA8 as kernel arguments 12..16 - the index tables of a program
 * run's three streams and its scratch block, and its lane mask. Every
 * program launch on such a tile passes all seventeen arguments - each
 * table the caller's resident buffer or one staged at the run's size,
 * one beat when the run has no table, and the mask a bit for every
 * lane whether or not the run has one (the lesson SEG_VERSION records:
 * a declared argument travels with the launch or not at all).
 * Reductions and elementwise runs pass what they passed; the five they
 * leave unset go out as zero, and the tile reads none of them without
 * MODE[23:19]. */
constexpr uint32_t IDX_VERSION = 0x00000A00u;
/* 0xB00 (2026-10-02, revision 8's seam, docs/ROADMAP.md "Revision 8"):
 * LFLAGS_PTR at 0xB0/0xB4 as kernel argument 17 - R23's per-lane flag
 * block, written by the tile after the counts when MODE[24] asks for it,
 * so on the D master beside the deposits, the counts and scratch-out.
 * Every program launch on such a tile passes all EIGHTEEN arguments
 * (0x900's lesson, below). A run that asks for the block - on a tile
 * publishing CAPS2[13], which device.c holds it to by name first - gets
 * a buffer of its slice's lanes bound there and MODE[24] set, and each
 * tile's block is copied to its slice's first lane in the caller's
 * buffer as the counts are (revision 8's lane-flags item, 2026-10-05). A
 * run that does not ask binds a one-beat stand-in the tile never writes,
 * with MODE[24] clear. The same map carries CAPS2[14:11], revision 8's
 * four program-model bits, and CAPS2[20:16], a streamed instruction
 * capacity; the decode is host/src/caps_decode.h's, and believes neither
 * below this version. Reductions and elementwise runs pass what they
 * passed, and argument 17 goes out as zero there, which the tile never
 * reads without MODE[24]. */
constexpr uint32_t LFLAGS_VERSION = 0x00000B00u;
/* The decode's own names for the same maps (host/src/caps_decode.h),
 * which this file does not use in its place: held equal here, so the two
 * cannot drift apart without the build saying so. */
static_assert(SCRATCH_VERSION == CFT_MAP_CAPS2, "caps_decode.h: CAPS2's map");
static_assert(SEG_VERSION == CFT_MAP_SEG, "caps_decode.h: SEG/NRES's map");
static_assert(IDX_VERSION == CFT_MAP_IDX, "caps_decode.h: the five pointers' map");
static_assert(LFLAGS_VERSION == CFT_MAP_LFLAGS, "caps_decode.h: LFLAGS_PTR's map");

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
/* 11 is the SEG/NRES pair (a scalar). 12..16 (ABI 0.14, docs/ROUND2.md):
 * the four index tables and the lane mask, all read by the sequencer
 * through the A master as the image, the bank and the preload are. */
constexpr int ARG_IDX_A = 12, ARG_IDX_B = 13, ARG_IDX_C = 14;
constexpr int ARG_IDX_SI = 15, ARG_MASK = 16;
/* 17 (VERSION 0xB00, revision 8's R23): LFLAGS_PTR at 0xB0, WRITTEN by
 * the tile, so on the D master as the deposits, the counts and
 * scratch-out are (hw/kernel.xml). */
constexpr int ARG_LFLAGS = 17;

/* MODE[15]: this run belongs to cft_seq and MODE[7:0] is ignored. */
constexpr uint32_t MODE_SEQ = 1u << 15;
/* MODE[24] (revision 8's R23, docs/SEQUENCER.md): write the per-lane
 * flags block at LFLAGS_PTR after the counts. Set only on a run that
 * asked for the block. It is the lowest bit of the range a tile since
 * the scalar guard refuses at start with STATUS[3] unless it builds the
 * feature, so a tile without CAPS2[13] asked for a block refuses the run
 * rather than ignoring the ask - and device.c refuses first, by name. */
constexpr uint32_t MODE_LFLAGS = 1u << 24;

/* STATUS, as rtl/cft_csr.sv lays it out. Bits 4 and 5 are also
 * CFT_STATUS_DEPOSIT_OVERFLOW and CFT_STATUS_SCRATCH_RANGE in the
 * public header; they must not drift, and this file cannot include
 * cft.h.
 *
 * ST_REPORTS is every bit a SUCCESSFUL program run hands back: reports
 * and not errors, because what fit is correct and what was in range is
 * correct. It is one mask because it was the same literal written at
 * two return sites until 2026-09-18, and both had stopped at bit 4:
 * the tile raised STATUS[5] for a strict image's index past the depth
 * (revision 4's R8, on silicon since the rev4 pair) and this backend
 * handed the caller 0, where the software backend and the golden
 * model hand it 0x20. Found by atlas-engine's first card day
 * (2026-09-17) with CFT_XRT_TRACE, which read 0x20 off the tile's own
 * register; no test had ever run an index past the depth on a device
 * and read the status back (device-test's scratch leg does now). */
constexpr uint32_t ST_BUS_BITS  = 0x7u;
constexpr uint32_t ST_REFUSED   = 0x8u;
constexpr uint32_t ST_DEPOSIT_OVERFLOW = 0x10u;
constexpr uint32_t ST_SCRATCH_RANGE    = 0x20u;
/* Revision 8's R24 (ABI 0.17): STATUS[6], CFT_STATUS_MARKED - a raise
 * marked a lane whose last bit a routine could not decide. In the mask
 * since BEFORE any tile could set it (a revision-7 tile reads STATUS as six
 * bits padded with zeros, so there it changes nothing), because a
 * mask that stopped at bit 5 would hand back an undecided bit as though
 * it were decided - and the run's certificates with it - which is the
 * trap bit 5 fell into until 2026-09-18. */
constexpr uint32_t ST_MARKED           = 0x40u;
constexpr uint32_t ST_REPORTS = ST_DEPOSIT_OVERFLOW | ST_SCRATCH_RANGE |
                                ST_MARKED;

/* Round `n` up to a whole 256-bit beat's worth of bytes. The masters
 * move whole beats whatever the format, so a buffer that ends mid-beat
 * is a buffer the last transfer runs off the end of. */
inline size_t beat_round(size_t bytes)
{
    return (bytes + 31u) & ~static_cast<size_t>(31u);
}

/* The CAPACITY of a buffer object, as distinct from the bytes a
 * transfer moves: a whole number of 4 KiB pages. Found on the card on
 * 2026-09-15: a buffer object of 1,344 bytes (336 fp32 lanes, beat-
 * rounded) ended in heap corruption on the first elementwise runs -
 * "corrupted size vs. prev_size" - while 64 lanes never did, and
 * AddressSanitizer showed XRT sizing a 4 KiB-aligned host allocation
 * to exactly our byte count. What the runtime and the driver move
 * behind that allocation is page-granular; a capacity that is too is
 * memory nobody runs off the end of. The byte counts handed to sync
 * and memcpy are unchanged. */
inline size_t page_round(size_t bytes)
{
    return (bytes + 4095u) & ~static_cast<size_t>(4095u);
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

/* The number a compute-unit name ends in - "cft_krnl:{cft_krnl_12}" is
 * 12 - or -1 if it ends in none. Used to put tiles in a stable order
 * and to find the one CFT_XRT_TILES names. Where the image's units are
 * listed, or a selection names them, MAGIC decides what each one IS
 * once it is open; the probe fallback's default open reads MAGIC from
 * the first tile only and keeps cft_krnl_2 and on by name, as it always
 * has. */
static long cu_ordinal(const std::string &nm)
{
    size_t end = nm.size();
    if (end && nm[end - 1] == '}')
        --end;
    size_t beg = end;
    while (beg && nm[beg - 1] >= '0' && nm[beg - 1] <= '9')
        --beg;
    if (beg == end)
        return -1;
    return std::strtol(nm.c_str() + beg, nullptr, 10);
}

std::string g_err;

void set_err(const std::string &s) { g_err = s; }
/* The same, for a message built before something it depended on was
 * freed: moved in, so nothing is allocated after the free. */
void set_err(std::string &&s) { g_err = std::move(s); }

/* A status word as eight hex digits. STATUS is a bit field and the
 * bits are what the reader needs; decimal would have to be converted
 * by hand at the exact moment nobody wants to. */
std::string hex32(uint32_t v)
{
    char b[9];
    std::snprintf(b, sizeof b, "%08x", static_cast<unsigned>(v));
    return std::string(b);
}

/* ---- ABI 0.18's device lines (cft.h, cft_image_id) ------------------ */

/* The XRT this library is built against: XRT_DRIVER_VERSION (the
 * version, a comma, the commit) up to its comma, or "" where the version
 * header is not there or has no such macro. */
std::string xrt_built_version()
{
#if defined(XRT_DRIVER_VERSION)
    std::string v(XRT_DRIVER_VERSION);
    const size_t comma = v.find(',');
    if (comma != std::string::npos)
        v.resize(comma);
    return v;
#else
    return std::string();
#endif
}

/* The first non-empty string a JSON text gives `key` (a quoted key, a
 * colon, a quoted string), or "": for the serial in XRT's platform report
 * (xrt::info::device::platform), which nests it under the card's
 * management controller. A value with an escape, which no serial has, is
 * not read; "N/A", XRT's word for a field it could not read, is not a
 * serial. */
std::string json_string_of(const std::string &js, const std::string &key)
{
    const std::string q = "\"" + key + "\"";
    size_t at = 0;
    while ((at = js.find(q, at)) != std::string::npos) {
        size_t p = at + q.size();
        while (p < js.size() && (js[p] == ' ' || js[p] == '\n' ||
                                 js[p] == '\t' || js[p] == '\r'))
            p++;
        at = p;
        if (p >= js.size() || js[p] != ':')
            continue;
        p++;
        while (p < js.size() && (js[p] == ' ' || js[p] == '\n' ||
                                 js[p] == '\t' || js[p] == '\r'))
            p++;
        if (p >= js.size() || js[p] != '"')
            continue;
        const size_t end = js.find('"', p + 1);
        if (end == std::string::npos)
            break;
        std::string v = js.substr(p + 1, end - p - 1);
        if (v.find('\\') != std::string::npos || v.empty() || v == "N/A" ||
            v == "n/a")
            continue;
        return v;
    }
    return std::string();
}

/* A text into a fixed field of cft_image_raw, NUL-terminated, or "" where
 * it would not fit: a value is never cut short (cft.h). */
void put_text(char *field, size_t cap, const std::string &v)
{
    if (v.size() < cap && v.find('\0') == std::string::npos)
        std::memcpy(field, v.c_str(), v.size() + 1);
    else
        field[0] = 0;
}

/* An artifact's bytes, whole, for cftx_open to hash and then hand to
 * XRT. ONE read: the digest cft_get_image_id reports is of the bytes
 * that were loaded, and not of the file read again later, which could
 * have been replaced in between. A file that cannot be opened or read
 * is refused with the operating system's reason. The handle is owned,
 * so a bad_alloc while the buffer grows cannot leak it on its way to the
 * C boundary, which reports it as out of memory. */
struct FileCloser {
    void operator()(std::FILE *f) const noexcept
    {
        if (f)
            std::fclose(f);
    }
};

bool read_image(const char *path, std::vector<char> &out, std::string &why)
{
    std::unique_ptr<std::FILE, FileCloser> f(std::fopen(path, "rb"));
    if (!f) {
        why = std::string("opening ") + path + " to hash and load it: " +
              std::strerror(errno);
        return false;
    }
    const size_t chunk = size_t(1) << 20;
    std::vector<char> v;
    size_t have = 0;
    for (;;) {
        v.resize(have + chunk);
        const size_t k = std::fread(v.data() + have, 1, chunk, f.get());
        have += k;
        if (k == chunk)
            continue;
        if (std::ferror(f.get())) {
            const int err = errno;
            why = std::string("reading ") + path + " to hash and load it: " +
                  std::strerror(err);
            return false;
        }
        break;                               /* end of file */
    }
    v.resize(have);
    out.swap(v);
    return true;
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
    /* And the five of 0xA00 (docs/ROUND2.md): the four index tables
     * and the lane mask, arguments 12..16. Sized per run and cached by
     * ensure_one like the counts buffer - a table one beat when the run
     * has none, the mask a bit a lane with or without one - because
     * the kernel has the arguments and a program launch on such a tile
     * passes every one of them. */
    xrt::bo     ia, ib, ic, isi, mk;
    size_t      ia_cap = 0, ib_cap = 0, ic_cap = 0, isi_cap = 0, mk_cap = 0;
    /* And 0xB00's one (revision 8's R23): the per-lane flag block,
     * argument 17 on the D master. Sized per run and cached by ensure_one
     * like the counts buffer, and for the counts' reason never the
     * caller's own memory: a byte a lane is never worth a device copy.
     * Bound on every program launch on such a tile - a run that asks for
     * the block gets its slice's lanes, beat-rounded, and one that does
     * not a one-beat stand-in the tile never writes (MODE[24] clear). */
    xrt::bo     lf;
    size_t      lf_cap = 0;
    /* The compute unit's name as XRT knows it ("cft_krnl:{cft_krnl_2}"),
     * so a refusal names the unit an operator can find in xbutil and in
     * CFT_XRT_TILES, not only this handle's index for it. */
    std::string cu;
};

struct Buf;

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
    /* The resident buffers the job in progress has bound as OUTPUTS,
     * filled by buf_bind and cleared by run_job. A job that fails once
     * a unit may have run marks each of them lost (Buf::lost): the tile
     * may have written part of a window whose earlier contents had not
     * come home yet, so no copy of it can be vouched for. */
    std::vector<Buf *> job_outs;
    /* CFT_XRT_BIND=decline-outputs, read by run_job at the start of each
     * job: a resident OUTPUT bind that would allocate, fill or re-window
     * a copy declines, as one too large for its channel does, so the
     * staged collects that write a resident buffer's mirror can be
     * reached on a card (verifier-V8: no leg could, and removing their
     * marks passed the gate). An output copy already live at the same
     * window, and current, is reused before the check is reached
     * (verifier-V9); device-test's pass runs each sequence into a fresh
     * buffer, where there is none. */
    bool              decline_outputs = false;
    /* The image's identity, for cftx_image_id (cft.h, cft_get_image_id):
     * the SHA-256 of the bytes cftx_open read and then loaded, how many
     * there were, and the raw capability words - n_caps of them, CAPS2
     * only from SCRATCH_VERSION. caps_refusal is empty unless the
     * identity cannot be answered, and then it is the whole sentence the
     * refusal gives: a tile whose words differ from tile 0's, or a tile
     * whose words could not be read at open - two different things, said
     * as two different sentences (verifier-C3 found the second reported
     * as the first). */
    uint8_t           image_sha256[32] = {};
    uint64_t          image_bytes = 0;
    uint32_t          n_caps = 0;
    uint32_t          caps_words[4] = {};
    std::string       caps_refusal;
    /* ABI 0.18's device lines, recorded at open with the rest (cft.h,
     * cft_image_id): the platform's name as XRT reports it, the kernel
     * clock the image's BUILD_METADATA states (0 where it names none for
     * every unit opened), and the card's serial from XRT's platform
     * report; "" and 0 where not known. */
    std::string       platform_name;
    uint64_t          clock_hz = 0;
    std::string       serial;
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
        *bufs[i] = xrt::bo(D.dev, page_round(bytes), xrt::bo::flags::normal,
                           t.k.group_id(args[i]));
    }
    t.cap = page_round(bytes);
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
    bo = xrt::bo(D.dev, page_round(bytes), xrt::bo::flags::normal,
                 t.k.group_id(arg));
    cap = page_round(bytes);
}

/* One tile's LANE MASK (R17), repacked into its buffer.
 *
 * Not a copy and not a window: bit 0 of what the tile reads is the
 * TILE's lane 0, so the caller's bits are shifted down from `first`,
 * which is a bit offset and not a byte one (slice.h cuts in beats and
 * a beat is one lane at fp256). The arithmetic is cft_mask_repack in
 * host/src/mask_bits.h, a pure function api_test.c exercises at every
 * offset; what is here is the buffer and the sync.
 *
 * A null mask writes all ones - every lane - so that an 0xA00 tile's
 * argument 16 is a real buffer on every launch, the way the four table
 * arguments are, and so that a MODE[23] the host did not set could
 * only ever read as "every lane" if something did. */
void stage_mask(xrt::bo &bo, const uint8_t *src, size_t first,
                size_t lanes, size_t padded_bytes)
{
    const size_t real = cft_mask_bytes(lanes);
    /* The repack below writes `real` bytes whatever the buffer holds,
     * so the buffer's size is checked HERE and not trusted to the
     * caller. It was trusted until 2026-09-18, and a run with no mask
     * sized the buffer at one beat while this wrote a bit for every
     * lane: past 32,768 lanes - one page's worth of bits - the all-ones
     * fill ran off the end of the mapping, the deposits came back right
     * and the host heap did not (atlas-engine's card day, 2026-09-17).
     * A sizing mistake is now a named failure of this one run. */
    if (real > padded_bytes)
        throw std::length_error("stage_mask: the lane-mask buffer holds " +
                                std::to_string(padded_bytes) + " bytes and " +
                                std::to_string(lanes) + " lanes need " +
                                std::to_string(real) + " - a sizing defect "
                                "in this backend, not the caller's");
    auto *p = bo.map<uint8_t *>();
    cft_mask_repack(p, src, first, lanes);
    if (padded_bytes > real)
        std::memset(p + real, src ? 0 : 0xFF, padded_bytes - real);
    bo.sync(XCL_BO_SYNC_BO_TO_DEVICE, padded_bytes, 0);
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

/* A reduction's b and c: buffers the engine READS and nothing USES.
 *
 * The engine streams all three operands - one read enable feeds all
 * three FIFOs - so for a reduction, which takes only `a`, b and c must
 * still be real, readable memory of the run's length. ensure_capacity
 * makes them that. Until 2026-09-18 both reduction paths ALSO zero-
 * filled them and uploaded them, for every tile on every call: twice
 * the operand's bytes over PCIe, one tile after another, to deliver
 * zeros no reduction looks at. It was the whole of the signature the
 * saturation runs of 2026-09-16 could not explain - a tile reducing at
 * a third of the engine's rate, and four tiles together no faster than
 * one - and none of it was the tiles: with the upload gone a
 * whole-array sum runs at the engine's 100 M beats a second on one
 * tile and at 3.8 times that on four (docs/VALIDATION.md, 2026-09-18).
 *
 * What makes skipping it safe is a property of the TILE, so it is held
 * by a test and not by this comment: with b and c filled with 0xFF - a
 * NaN at every format - every reduction still matches the software
 * backend, bits and flags. device-test re-runs its reductions that way
 * on an XRT device, which is what CFT_XRT_REDUCE_BC=poison is for:
 *
 *   unset    b and c are allocated and never written (the default)
 *   poison   they are filled with 0xFF and uploaded - adversarial
 *            contents at the old cost; a reduction that ever comes to
 *            depend on them goes red under it
 *   zero     the behaviour before 2026-09-18, for an A/B timing
 *
 * Read per call, so a test can switch it between two runs. A future
 * reduction that really reads b in the tile (a fused dot) must not
 * come through here with a null b. */
void reduce_unread(xrt::bo &b, xrt::bo &c, size_t real_bytes,
                   size_t padded_bytes)
{
    const char *const m = std::getenv("CFT_XRT_REDUCE_BC");
    if (std::getenv("CFT_XRT_TRACE"))
        std::fprintf(stderr, "[xrt trace] reduction b and c, %zu bytes: %s\n",
                     padded_bytes,
                     (!m || !*m) ? "unwritten"
                     : !std::strcmp(m, "poison") ? "poison (0xFF), uploaded"
                     : !std::strcmp(m, "zero") ? "zeros, uploaded"
                     : "unwritten (unknown mode ignored)");
    if (!m || !*m)
        return;
    if (!std::strcmp(m, "poison")) {
        std::memset(b.map<uint8_t *>(), 0xFF, padded_bytes);
        std::memset(c.map<uint8_t *>(), 0xFF, padded_bytes);
        b.sync(XCL_BO_SYNC_BO_TO_DEVICE, padded_bytes, 0);
        c.sync(XCL_BO_SYNC_BO_TO_DEVICE, padded_bytes, 0);
    } else if (!std::strcmp(m, "zero")) {
        stage(b, nullptr, real_bytes, padded_bytes);
        stage(c, nullptr, real_bytes, padded_bytes);
    }
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

/* Role index (backend.h's CFT_ROLE_*) to kernel argument id.
 *
 * One entry per role, sized by CFT_ROLE_COUNT rather than by a literal.
 * The scratch roles were added to the enum on 2026-09-12 and NOT to this
 * table, and the failure was not a compile error: ROLE_ARG[CFT_ROLE_SI]
 * read past a constexpr array and passed whatever followed it to
 * group_id(), which XRT range-checked and threw - "__n (which is 1040)".
 * The gate caught it on the card. */
constexpr int ROLE_ARG[CFT_ROLE_COUNT] = {ARG_A, ARG_B, ARG_C, ARG_D,
                                          ARG_SCRATCH_IN, ARG_SCRATCH_OUT,
                                          ARG_IDX_A, ARG_IDX_B, ARG_IDX_C,
                                          ARG_IDX_SI, ARG_MASK};
/* A role added without an argument id leaves the tail of that list
 * zero-initialised, which is not a compile error and IS a valid-looking
 * argument index - it would bind the wrong buffer silently. ARG_A is 2,
 * so no real argument id is zero. */
static_assert(ROLE_ARG[CFT_ROLE_COUNT - 1] != 0,
              "every CFT_ROLE_* needs a kernel argument id in ROLE_ARG");

struct BufCopy {
    xrt::bo  bo;
    size_t   off    = 0;      /* first byte of the buffer this holds */
    size_t   real   = 0;      /* bytes of the caller's data in it */
    size_t   padded = 0;      /* bytes allocated: whole beats */
    uint64_t gen    = 0;      /* CURRENT when it equals Buf::gen: its
                               * bytes are the mirror's over its window -
                               * filled from it, or flushed into it - and
                               * nothing has changed the mirror under the
                               * window since (buf_touched sets 0, which
                               * is never current). One exception: an
                               * OUTPUT copy bound without a fill is
                               * given the generation too, and holds
                               * bytes nobody wrote until the tile writes
                               * the window whole. It is never read as an
                               * input: D and SO are output roles, and a
                               * preserving bind also asks `filled`
                               * (verifier-V9, 2026-09-27) */
    bool     live   = false;  /* the bo exists and the window means
                               * something */
    bool     dirty  = false;  /* a run wrote this window and the mirror
                               * has not been told */
    bool     filled = false;  /* its bytes were copied FROM the mirror at
                               * `gen` - true for every input, and for an
                               * output bound under a lane mask; an output
                               * a run will overwrite whole is allocated
                               * and never filled */
};

struct Buf {
    Dev                 *D = nullptr;
    uint8_t             *host = nullptr;   /* device.c owns this */
    size_t               bytes = 0;
    /* Moved only when the CALLER publishes the mirror
     * (cftx_buffer_to_device), who may have written any of it. The
     * library's own changes to the mirror - a flush, a host write - stale
     * only the copies over the bytes they changed (buf_touched). Starts at
     * 1 so that a copy's zero-initialised `gen` can never be mistaken for
     * current. */
    uint64_t             gen = 1;
    std::vector<BufCopy> copies;  /* tiles * CFT_ROLE_COUNT,
                                   * [t * CFT_ROLE_COUNT + role] */
    uint64_t             resident_binds = 0, staged_binds = 0;
    std::string          why;
    /* Set when a run that bound this buffer as an output failed once a
     * unit may have run (run_job's lose_outputs), with the sentence
     * saying so. Its contents are then nobody's - the failed run may have
     * written part of a window, over bytes an earlier run left on the
     * device that never came home - so reading it back or binding it
     * again is refused by name until the caller publishes the mirror as
     * the truth (cft_buffer_to_device). Found by verifier-V4
     * (2026-09-25): before this, the copy kept the earlier run's dirty
     * flag, and cft_buffer_from_device handed the failed run's bytes to
     * the caller with CFT_OK. The flag is separate from the sentence so
     * that setting it cannot fail. */
    bool                 lost = false;
    std::string          lost_why;
};

/* The mirror's bytes [lo, hi) no longer match what a device copy over
 * them holds: a flush has just written one copy's bytes over them, or the
 * host is about to write them or has just written them. Every copy whose
 * window overlaps the range, other than `now`, stops being current (gen 0
 * is never current: Buf::gen starts at 1). Copies elsewhere in the buffer
 * keep their standing, because the bytes under their windows did not move
 * - which is what lets one resident buffer carved into windows (streams,
 * a deposit window, the counts beside them) keep its input copies across
 * a run whose counts land on the host.
 *
 * Until 2026-09-25 three paths changed the mirror and told no copy -
 * buf_bind's flush of a copy it was about to re-window, a collect writing
 * a staged output into a resident buffer's mirror, and every entry point
 * computed on the host - and a copy filled before was served as current:
 * wrong answers with CFT_OK (verifier-V7). */
void buf_touched(Buf &B, size_t lo, size_t hi, const BufCopy *now) noexcept
{
    for (auto &o : B.copies)
        if (&o != now && o.off < hi && lo < o.off + o.real)
            o.gen = 0;
}

/* Carry one copy's window home. The whole copy is synced and only the
 * real bytes are written into the mirror: the pad is beat padding this
 * file put there and is nobody's data. Afterwards the mirror under the
 * window holds exactly this copy's bytes, so this copy is current - a
 * masked run into the same window next needs no refill - and every other
 * copy over those bytes is not. One step: a sync that throws leaves the
 * copy dirty and nothing else changed. */
bool buf_flush(Buf &B, BufCopy &c)
{
    if (!c.dirty)
        return false;
    c.bo.sync(XCL_BO_SYNC_BO_FROM_DEVICE, c.padded, 0);
    std::memcpy(B.host + c.off, c.bo.map<uint8_t *>(), c.real);
    c.dirty = false;
    buf_touched(B, c.off, c.off + c.real, &c);
    c.gen = B.gen;
    c.filled = true;
    return true;
}

/* The library has written [lo, hi) of the mirror ON THE HOST: a staged
 * output collected into a resident buffer (a bind this file declined), a
 * program's counts, a reduction's result, an entry point computed on the
 * host. Every copy over those bytes is stale.
 *
 * A copy still DIRTY over them held bytes the write superseded. Wholly
 * inside the range, nothing of it is left to keep, and its claim is
 * dropped. Reaching past the range, the rest of it would have to come
 * home through a sync that can fail - which this cannot, being called
 * from inside run_job's collects - so it is not attempted: the claim is
 * dropped and the buffer is LOST, refused by name until it is published
 * again. That needs outputs that alias one another or a host result,
 * because every path that writes the mirror first brings home the copies
 * over it (buf_bind before it declines, cftx_buffer_will_write before the
 * host writes); it is a refusal, never a wrong answer. */
void buf_host_wrote(Buf &B, size_t lo, size_t hi) noexcept
{
    if (lo > B.bytes)
        lo = B.bytes;
    if (hi > B.bytes)
        hi = B.bytes;
    if (hi < lo)
        hi = lo;
    for (auto &c : B.copies) {
        if (!c.dirty || !(c.off < hi && lo < c.off + c.real))
            continue;
        c.dirty = false;
        if (lo <= c.off && c.off + c.real <= hi)
            continue;
        if (!B.lost) {
            B.lost = true;
            try {
                B.lost_why = "a run's output still on the device overlapped "
                             "bytes the library wrote on the host, and "
                             "reached past them (outputs that alias), so "
                             "this buffer's contents cannot be vouched for; "
                             "publish them again with cft_buffer_to_device";
            } catch (...) {
                /* the flag stands without its sentence */
            }
        }
    }
    buf_touched(B, lo, hi, nullptr);
}

/* Bind one operand of one slice, or decline.
 *
 * Returns the buffer object to hand the kernel, or nullptr to say
 * "stage this one from host memory as before" - which is never wrong,
 * only slower, and is what every failure here degrades to. Throws, and
 * so refuses the job before anything starts, for a buffer a failed run
 * left lost (Buf::lost): staging it from the mirror would be the one
 * wrong thing.
 *
 * `output` is a role the tile WRITES. Unmasked, it writes every lane of
 * the window, so the copy's contents before the run are nobody's
 * business: a window that matches binds whatever generation it was
 * filled at, and a fresh one is not filled at all. `preserve` is an
 * output under a lane mask (R17): the tile's strobes leave a masked
 * lane's bytes exactly as they were, and those bytes must be what the
 * caller's buffer holds - so the copy must be current before the run,
 * like an input: it is kept only if it holds the newest bytes (a dirty
 * copy of this window, which nothing is newer than, or one filled from
 * the mirror at this generation), and otherwise filled from the mirror.
 * Until 2026-09-25 a masked run's resident deposit window and scratch-
 * out block kept whatever the device copy held in their masked lanes -
 * another run's deposits after a republish (verifier-V4). */
xrt::bo *buf_bind(Buf &B, size_t tile, int role, size_t off,
                  size_t real, size_t padded, bool output,
                  bool preserve = false)
{
    if (!B.D || tile >= B.D->tiles.size() ||
        role < 0 || role >= CFT_ROLE_COUNT)
        return nullptr;
    if (B.lost)
        throw std::runtime_error(
            B.lost_why.empty() ? std::string("a failed run lost this "
                                             "buffer's contents; publish "
                                             "them again with "
                                             "cft_buffer_to_device")
                               : B.lost_why);

    BufCopy &c =
        B.copies[tile * CFT_ROLE_COUNT + static_cast<size_t>(role)];

    /* Before a run is handed an OUTPUT window, every OTHER copy of this
     * buffer holding unflushed bytes that overlap it goes home first.
     * Two copies can overlap when a window moved to another tile - a
     * different cut, a different placement, or a window reached through
     * an offset into the buffer - and cftx_buffer_from_device flushes
     * copies in table order, not write order, so the older bytes could
     * otherwise land last and silently replace the newer run's. The
     * mirror changed under them, so buf_flush stales every copy over
     * those bytes: an input copy filled before must not be reused as
     * current. (Found reading
     * this file for the scheduler, 2026-09-25. It was reachable under
     * fixed placement too: verifier-V4's random-window property test
     * found 32 of 300 trials wrong at 617b753 on four tiles and 16 of 300
     * on three, with no placement instrument; 0 of 1,200 since.) */
    if (output)
        for (auto &o : B.copies)
            if (&o != &c && o.dirty && o.off < off + real &&
                off < o.off + o.real)
                (void)buf_flush(B, o);
    const bool same_window =
        c.live && c.off == off && c.real == real && c.padded == padded;

    const bool current = preserve
                             ? (c.dirty || (c.filled && c.gen == B.gen))
                             : (output || c.gen == B.gen);
    if (same_window && current) {
        if (output)
            B.D->job_outs.push_back(&B);
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
    (void)buf_flush(B, c);   /* stales the copies over its old window */

    if (output && B.D->decline_outputs) {
        B.why = "declined by CFT_XRT_BIND=decline-outputs";
        B.staged_binds++;
        return nullptr;
    }

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
            c.bo = xrt::bo(B.D->dev, page_round(padded),
                           xrt::bo::flags::normal,
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
    /* Current only once its bytes ARE the mirror's. Marked before the
     * fill until 2026-09-26, so a fill whose upload threw left the copy
     * "current" with the bytes it held before, and the retry that a
     * staging failure allows bound it resident - 64 of 64 wrong with
     * CFT_OK, pre-existing (verifier-V8, N1). */
    c.gen = 0;
    c.filled = false;

    if (!output || preserve) {
        auto *p = c.bo.map<uint8_t *>();
        std::memcpy(p, B.host + off, real);
        if (padded > real)
            std::memset(p + real, 0, padded - real);
        c.bo.sync(XCL_BO_SYNC_BO_TO_DEVICE, padded, 0);
        c.gen = B.gen;
        c.filled = true;
        B.staged_binds++;
        B.why = preserve
                    ? "an output under a lane mask, filled so its masked "
                      "lanes are the caller's"
                : same_window
                    ? "the mirror was republished, so this copy refilled"
                    : "first use of this window on this tile and role";
    } else {
        /* Nothing crossed the bus: an output copy is written by the
         * tile whole, and allocating one is not a transfer. */
        c.gen = B.gen;
        B.resident_binds++;
    }
    /* An output bound to a device copy is this job's to lose if it
     * fails; one declined above is staged, and a failed run never
     * writes a staged output back. */
    if (output)
        B.D->job_outs.push_back(&B);
    return &c.bo;
}

/* After a successful run, the copies the tiles wrote hold bytes the
 * mirror does not. Only ever called on ST_OK: a failed run's output is
 * not valid, and marking it authoritative would let a later
 * cftx_buffer_from_device carry a bus fault's leavings into the
 * caller's array. */
void buf_mark_written(Buf &B, size_t tile, int role)
{
    BufCopy &c =
        B.copies[tile * CFT_ROLE_COUNT + static_cast<size_t>(role)];
    if (c.live)
        c.dirty = true;
}

/* ====================================================================
 * The scheduler (docs/ROADMAP.md, "Programs across tiles: a partitioner
 * and a scheduler" - Logan's plan of record of 2026-09-18, its step 2)
 *
 * Every kind of run - elementwise, reduction, segmented reduction,
 * program - reaches the tiles through this one piece of code. A call
 * builds a JOB: its TASKS, each one tile's share of the run (a slice of
 * elements, a range of a reduction's tree, a run of segments, a range of
 * lanes), with the steps only that kind knows - stage, start, collect -
 * each taking the tile the scheduler places it on. The scheduler owns
 * everything the kinds used to do four times over, each its own way:
 *
 *   - PLACEMENT. Tasks go out in waves of at most one a tile, because
 *     the RTL silently drops a start issued to a busy compute unit, and
 *     each wave is staged just before it starts: staging every task up
 *     front once let a reduction's fifth range overwrite its first
 *     range's operands before the first had been launched. Within a
 *     wave the tiles are taken in order, or in the order
 *     CFT_XRT_TILE_ORDER=seed:<N> draws (lane_cut.h's cft_tile_order):
 *     a job's bits may not depend on which tile ran which task, and the
 *     card gate holds that by moving the tasks around.
 *   - THE LAUNCH DISCIPLINE. Every task of a wave is staged before any
 *     starts, so a staging failure leaves every unit idle and the handle
 *     reusable. Every started run is waited on, even after a failure -
 *     abandoning one leaves a unit writing into this process's buffers -
 *     and any failure once a unit may be running poisons the handle,
 *     after a best-effort STATUS read, because the timeout is how a
 *     fabric fault becomes readable at all.
 *   - THE STICKY WORDS. STATUS and FLAGS are ORed over the tiles that
 *     RAN, never an idle one, whose words are its previous run's - OR is
 *     associative, which is why placement cannot reach them - and the
 *     job's own test of STATUS decides, wave by wave, whether results
 *     are collected at all: faults before results.
 *
 * What the scheduler does not decide is the CUT, which is each kind's
 * strategy (slice.h's beats for elementwise work, the caller's
 * canonical tree nodes for a reduction, whole segments for a segmented
 * one, lane_cut.h's lanes for a program), nor what STATUS means, which
 * differs by kind - a program's carries reports beside its faults. The
 * plan's later steps - asynchronous submit and wait, per-tile failure,
 * cuts through a program - build on this and are not here.
 * ==================================================================== */

struct Task {
    std::function<void(size_t)> stage;      /* may throw; nothing started */
    std::function<xrt::run(size_t)> start;  /* launch on this tile */
    std::function<void(size_t)> collect;    /* after a clean wave */
    std::function<void(size_t)> after;      /* optional: every task, before
                                             * the fault test (traces) */
};

struct Job {
    std::string what;        /* "a run", "a program", "a reduction", ... */
    std::string oom_words;   /* why this kind's staging runs out */
    std::vector<Task> tasks;
    bool (*faulty)(uint32_t);
    /* Filled by run_job when the job's test stops it: which tiles, with
     * their STATUS - for the caller's sentence, so a fault names the
     * tile it happened on. */
    std::string where;
};

/* CFT_XRT_TILE_ORDER and CFT_XRT_PROGRAM_CUTS take "seed:<N>", and the
 * second also "skew:<N>"; N decimal, nothing else. Read per call, so a
 * test can switch it between two runs. Unset or empty is the default
 * (seed 0). A malformed value is refused by name - an instrument that
 * quietly read a typo as "off" would be a gate that could not fail. */
int instrument_seed(const char *name, bool allow_skew, uint64_t *seed,
                    bool *skew)
{
    *seed = 0;
    if (skew)
        *skew = false;
    const char *const v = std::getenv(name);
    if (!v || !*v)
        return ST_OK;
    const bool is_seed = !std::strncmp(v, "seed:", 5);
    const bool is_skew = allow_skew && !std::strncmp(v, "skew:", 5);
    char *end = nullptr;
    unsigned long long n = 0;
    bool ok = (is_seed || is_skew) && v[5] >= '0' && v[5] <= '9';
    if (ok) {
        errno = 0;
        n = std::strtoull(v + 5, &end, 10);
        ok = end && !*end && !errno && n != 0;
    }
    if (!ok) {
        set_err(std::string(name) + "=\"" + v + "\": expected seed:<N>" +
                (allow_skew ? " or skew:<N>" : "") + ", N a decimal seed "
                "above zero; unset it for the default");
        return ST_INVALID_ARGUMENT;
    }
    *seed = n;
    if (skew)
        *skew = is_skew;
    return ST_OK;
}

/* "tile N (cft_krnl:{cft_krnl_M})": this handle's index for a tile and
 * the compute unit an operator finds in xbutil and names in
 * CFT_XRT_TILES - which, after a timeout, is the tile to reload. */
std::string tile_name(const Dev &D, size_t t)
{
    return "tile " + std::to_string(t) + " (" + D.tiles[t].cu + ")";
}

/* g_err from a sentence built by `build`, or - if building it runs out
 * of memory - from a fallback short enough to need no allocation. Used
 * on every path where a unit may have run, which must go on to wait,
 * poison and mark outputs whatever the message costs (verifier-V4,
 * 2026-09-25: a bad_alloc while run_job built its message escaped with
 * started runs unwaited and the handle not poisoned). */
template <class F>
void set_err_or(F build, const char *fallback) noexcept
{
    try {
        set_err(build());
    } catch (...) {
        try {
            g_err.assign(fallback);
        } catch (...) {
        }
    }
}

/* The C boundary's handlers, shared by every extern "C" entry point that
 * does real work: run `body` and turn an escaping bad_alloc into
 * ST_OUT_OF_MEMORY and anything else into ST_INTERNAL, each with a
 * sentence - no C++ exception may cross into C. */
template <class F>
int at_boundary(const char *what, F body) noexcept
{
    try {
        return body();
    } catch (const std::bad_alloc &) {
        set_err_or([&] { return std::string("out of memory in ") + what; },
                   "out of memory");
        return ST_OUT_OF_MEMORY;
    } catch (const std::exception &e) {
        set_err_or([&] { return std::string(what) + ": " + e.what(); },
                   "internal error");
        return ST_INTERNAL;
    } catch (...) {
        set_err_or([&] { return std::string(what) + " failed"; },
                   "internal error");
        return ST_INTERNAL;
    }
}

/* A job that failed once a unit may have run loses its resident outputs
 * (Buf::lost). Never throws: the flag needs no allocation and the
 * sentence is best-effort. */
void lose_outputs(Dev &D, const char *how) noexcept
{
    for (Buf *B : D.job_outs) {
        if (!B || B->lost)
            continue;
        B->lost = true;
        try {
            B->lost_why = std::string("a run that wrote this resident "
                                      "buffer failed on the device (") +
                          how + "), so what the tile left in it is not "
                          "known - publish its contents again with "
                          "cft_buffer_to_device before reading it back or "
                          "running on it";
        } catch (...) {
        }
    }
    D.job_outs.clear();
}

/* " (tile 2 (cft_krnl:{cft_krnl_3}) STATUS 0x1)", or nothing: the tiles
 * a job's test stopped it on, for the caller's sentence. */
std::string at_where(const Job &J)
{
    return J.where.empty() ? std::string() : " (" + J.where + ")";
}

/* Run a job. ST_OK means every wave ran: *status and *flags are the
 * words ORed over the tiles that ran, and *faulted says whether the
 * job's test stopped it before a wave's results were collected (the
 * caller then names the fault, with J.where; nothing it collected is to
 * be trusted). Anything else is a failure with g_err set; *fail_status
 * is then a best-effort STATUS read, for the caller's message, and the
 * handle is poisoned when a unit may still be running. Once a unit may
 * have run, every path out - including one that runs out of memory
 * building its sentence - waits on every started run, and a failure
 * loses the job's resident outputs (Buf::lost). */
int run_job(Dev &D, Job &J, uint32_t *status, uint32_t *flags,
            bool *faulted, uint32_t *fail_status)
{
    *status = 0;
    *flags = 0;
    *faulted = false;
    *fail_status = 0;
    D.job_outs.clear();
    J.where.clear();

    uint64_t seed = 0;
    const int ist = instrument_seed("CFT_XRT_TILE_ORDER", false, &seed,
                                    nullptr);
    if (ist != ST_OK)
        return ist;

    /* CFT_XRT_WITNESS, a card instrument read per call: the completion
     * witness's planted fault. "busy-before" makes the first task's
     * tile read as busy before its start; "busy-after" makes its reads
     * after the wait busy for 50 ms and then real, so that a witness
     * which refused without waiting for the tile to go idle is seen not
     * to have waited (device-test times it: verifier-V7 found a one-read
     * plant let that mutant pass, 2026-09-25). Either must be
     * refused by name and leave the handle usable - device-test holds
     * that on every XRT device. What it cannot plant is the defect the
     * witness exists for, an abandoned run; that is a card-day leg
     * (docs/CARDDAY.md). Anything else set is refused by name. */
    int plant = 0;
    if (const char *w = std::getenv("CFT_XRT_WITNESS")) {
        if (!std::strcmp(w, "busy-before"))
            plant = 1;
        else if (!std::strcmp(w, "busy-after"))
            plant = 2;
        else if (!std::strcmp(w, "busy-open"))
            plant = 0;           /* cftx_open's plant; nothing for a run */
        else if (*w) {
            set_err(std::string("CFT_XRT_WITNESS=\"") + w + "\": expected "
                    "busy-before, busy-after or busy-open; unset it for "
                    "none");
            return ST_INVALID_ARGUMENT;
        }
    }
    D.decline_outputs = false;
    if (const char *b = std::getenv("CFT_XRT_BIND")) {
        if (!std::strcmp(b, "decline-outputs"))
            D.decline_outputs = true;
        else if (*b) {
            set_err(std::string("CFT_XRT_BIND=\"") + b + "\": expected "
                    "decline-outputs; unset it for none");
            return ST_INVALID_ARGUMENT;
        }
    }

    const size_t ntiles = D.tiles.size();
    std::vector<size_t> order(ntiles);
    for (size_t base = 0, wave = 0; base < J.tasks.size();
         base += ntiles, wave++) {
        const size_t count = std::min(ntiles, J.tasks.size() - base);
        cft_tile_order(ntiles, seed, wave, order.data());

        /* The completion witness, before (2026-09-25) - and before the
         * wave is STAGED (2026-09-26): staging fills this wave's copies on
         * the tile, and a busy tile's memory may be written by the run
         * that is going there, so a refusal after staging left copies
         * "current" that the abandoned run could have written over
         * (verifier-V8). A tile this wave will start must be IDLE: a busy one is running work this
         * process did not start - a run abandoned on it by a timeout or
         * by a process that ended mid-run - and the tile drops a start
         * while busy (rtl/cft_csr.sv), so XRT would report this task
         * complete when THAT run ends and hand back bytes this job never
         * wrote. Nothing of the wave has started, so a refusal leaves
         * every unit as it was. CFT_ERR_BUSY takes this over with
         * per-tile failure (docs/ROADMAP.md, plan step 3). */
        for (size_t j = 0; j < count; j++) {
            const Tile &t = D.tiles[order[j]];
            uint32_t c = 0;
            try {
                c = t.k.read_register(CSR_CTRL);
            } catch (const std::exception &e) {
                set_err("reading " + tile_name(D, order[j]) + "'s CTRL "
                        "before " + J.what + ": " + e.what());
                return ST_INTERNAL;
            }
            if (plant == 1 && base == 0 && j == 0)
                c = CTRL_START;                  /* CFT_XRT_WITNESS */
            if ((c & CTRL_IDLE) && !(c & CTRL_START))
                continue;
            set_err(tile_name(D, order[j]) + " is running work this "
                    "process did not start (CTRL 0x" + hex32(c) + ", not "
                    "idle): a run abandoned on it - by a timeout, or by a "
                    "process that ended mid-run - is still going. The tile "
                    "would drop this start and XRT would report " + J.what +
                    " complete when that run ends, so it is refused and "
                    "nothing was started or staged. Reload the image - load "
                    "another xclbin, then this one - before trusting this "
                    "tile: until then XRT may complete later runs on it "
                    "early, and the abandoned run may write into memory "
                    "this handle's buffers use");
            return ST_INTERNAL;
        }

        /* Stage the wave. Nothing of it has started, so a failure
         * leaves its units idle; an earlier wave's results are the
         * caller's to discard with the error. */
        /* Every failure sentence below names its tile (verifier-V7,
         * 2026-09-25: staging, STATUS/FLAGS and collect failures named
         * none). */
        size_t at = 0;
        try {
            for (size_t j = 0; j < count; j++) {
                at = order[j];
                J.tasks[base + j].stage(order[j]);
            }
        } catch (const std::bad_alloc &) {
            set_err_or([&] {
                return "out of memory staging " + J.what + " for " +
                       tile_name(D, at);
            }, "out of memory");
            return ST_OUT_OF_MEMORY;
        } catch (const std::exception &e) {
            const std::string w = e.what();
            if (w.find("alloc") != std::string::npos ||
                w.find("memory") != std::string::npos ||
                w.find("Memory") != std::string::npos) {
                set_err("device buffer allocation failed (" + J.oom_words +
                        ") on " + tile_name(D, at) + ": " + w);
                return ST_OUT_OF_MEMORY;
            }
            set_err("staging " + J.what + " for " + tile_name(D, at) + ": " +
                    w);
            return ST_INTERNAL;
        }

        /* From here a compute unit may be running. Nothing below may
         * leave without waiting on every run in `runs`: the handlers
         * record what failed in fixed storage and the sentence is built
         * after the waits, by set_err_or. */
        std::vector<xrt::run> runs;
        runs.reserve(count);      /* before any start: never grows below */
        int st = ST_OK;
        int kind = 0;       /* 1 a start, 2 a wait's state, 3 a wait threw */
        size_t bad = 0;
        int bad_state = 0;
        char what[240] = "";
        for (size_t j = 0; j < count; j++) {
            try {
                runs.push_back(J.tasks[base + j].start(order[j]));
            } catch (const std::exception &e) {
                st = ST_INTERNAL;
                kind = 1;
                bad = order[j];
                std::snprintf(what, sizeof what, "%s", e.what());
                break;      /* stop launching, but wait on the started */
            } catch (...) {
                st = ST_INTERNAL;
                kind = 1;
                bad = order[j];
                break;
            }
        }
        for (size_t j = 0; j < runs.size(); j++) {
            try {
                const ert_cmd_state s =
                    runs[j].wait(std::chrono::milliseconds(D.wait_ms));
                if (s != ERT_CMD_STATE_COMPLETED && st == ST_OK) {
                    st = (s == ERT_CMD_STATE_TIMEOUT) ? ST_TIMEOUT
                                                      : ST_INTERNAL;
                    kind = 2;
                    bad = order[j];
                    bad_state = static_cast<int>(s);
                }
            } catch (const std::exception &e) {
                if (st == ST_OK) {
                    st = ST_INTERNAL;
                    kind = 3;
                    bad = order[j];
                    std::snprintf(what, sizeof what, "%s", e.what());
                }
            } catch (...) {
                if (st == ST_OK) {
                    st = ST_INTERNAL;
                    kind = 3;
                    bad = order[j];
                }
            }
        }
        if (st != ST_OK) {
            D.poisoned = true;
            lose_outputs(D, st == ST_TIMEOUT ? "a timeout" : "a failure");
            uint32_t acc = 0;
            try {
                for (size_t j = 0; j < runs.size(); j++)
                    acc |= D.tiles[order[j]].k.read_register(CSR_STATUS);
            } catch (...) {
                acc = 0;          /* the handle is going away regardless */
            }
            *fail_status = acc;
            const bool ran = !runs.empty();
            set_err_or([&] {
                std::string m;
                if (kind == 1)
                    m = "starting " + J.what + " on " + tile_name(D, bad) +
                        ": " + what + " - a unit may have begun before the "
                        "failure, so this handle is finished; close and "
                        "reopen it";
                else if (st == ST_TIMEOUT)
                    m = tile_name(D, bad) + " did not complete " + J.what +
                        " within CFT_TIMEOUT_MS (" +
                        std::to_string(D.wait_ms) + " ms) and may still be "
                        "running it, so this handle is finished; close and "
                        "reopen it";
                else if (kind == 2)
                    m = tile_name(D, bad) + " did not complete " + J.what +
                        " (state " + std::to_string(bad_state) + ") - "
                        "compute units may still be active, so this handle "
                        "is finished; close and reopen it";
                else
                    m = "waiting on " + J.what + " on " + tile_name(D, bad) +
                        ": " + what + " - compute units may still be "
                        "active, so this handle is finished; close and "
                        "reopen it";
                /* Every one of these can leave a unit running, and what
                 * the timeout's sentence alone said is true of all four
                 * (verifier-V7, 2026-09-25). */
                m += ". A run left running on a tile can make XRT complete "
                     "later runs there early, in any process, until the "
                     "image is reloaded: reload it before trusting " +
                     tile_name(D, bad) + " (docs/HOSTAPI.md)";
                if (ran) {
                    /* Only what STATUS shows: until 2026-09-25 this said
                     * the units "never started this work, so this is a
                     * hang", which a latched refusal does not establish
                     * (verifier-V7). */
                    if (acc == 0x8u)
                        m += " (STATUS 0x8 - only the REFUSAL bit is latched: "
                             "a unit refused a request, and no memory fault "
                             "is recorded, so this is not a bus fault)";
                    else if (acc)
                        m += " (STATUS 0x" + hex32(acc) + " - the memory "
                             "system or the tile reported something, so "
                             "this is more than a slow run)";
                    else if (st == ST_TIMEOUT)
                        m += " (STATUS clean on every unit that ran, so "
                             "this is a hang or a genuinely slow run rather "
                             "than a bus fault)";
                    else
                        /* a thrown wait, an ERROR state, a start that
                         * threw: none is shown to be a hang or slow
                         * (verifier-V8) */
                        m += " (STATUS clean on every unit that ran)";
                }
                return m;
            }, "run failed");
            return st;
        }

        /* The completion witness, after. XRT reported every run of the
         * wave complete; each tile must now BE idle. On the card on
         * 2026-09-25, after a run was abandoned on a tile, XRT's
         * scheduler (ERT) completed later runs on it early - in any
         * process, until the image was reloaded - and a slice slower
         * than the others came back with its last block unwritten and
         * rc 0 (docs/VALIDATION.md). An output check cannot see that
         * when an identical earlier run left the same bytes at the same
         * addresses; this can: the tile is still busy. STATUS and FLAGS
         * are read below this, never from a run still going. A busy tile
         * is waited on until idle (as long as a run may take), so no
         * write of this job lands after the call returns, and then the
         * job is refused - nothing of the wave is collected. */
        {
            bool early = false, still = false;
            size_t first_early = 0;
            for (size_t j = 0; j < count; j++) {
                const Tile &t = D.tiles[order[j]];
                uint32_t c = 0;
                try {
                    const bool planted = plant == 2 && base == 0 && j == 0;
                    c = t.k.read_register(CSR_CTRL);
                    if (planted)
                        c = CTRL_START;              /* CFT_XRT_WITNESS */
                    if (c & CTRL_IDLE)
                        continue;
                    const auto t0 = std::chrono::steady_clock::now();
                    while (!(c & CTRL_IDLE) &&
                           std::chrono::steady_clock::now() - t0 <
                               std::chrono::milliseconds(D.wait_ms)) {
                        std::this_thread::sleep_for(
                            std::chrono::milliseconds(1));
                        c = t.k.read_register(CSR_CTRL);
                        if (planted && std::chrono::steady_clock::now() - t0 <
                                           std::chrono::milliseconds(50))
                            c = CTRL_START;      /* the plant holds 50 ms */
                    }
                } catch (...) {
                    D.poisoned = true;
                    lose_outputs(D, "an unreadable CTRL");
                    set_err_or([&] {
                        return "reading " + tile_name(D, order[j]) +
                               "'s CTRL after " + J.what + " failed, so "
                               "whether it finished is not known; this "
                               "handle is finished. A run left running on a "
                               "tile can make XRT complete later runs there "
                               "early, in any process, until the image is "
                               "reloaded: reload it before trusting " +
                               tile_name(D, order[j]) + " (docs/HOSTAPI.md)";
                    }, "run failed");
                    return ST_INTERNAL;
                }
                if (!(c & CTRL_IDLE))
                    still = true;
                if (!early)
                    first_early = order[j];
                early = true;
            }
            if (early) {
                if (still)
                    D.poisoned = true;
                lose_outputs(D, "an early completion");
                set_err_or([&] {
                    return "XRT reported " + J.what + " complete while " +
                           tile_name(D, first_early) + " was still running "
                           "it, so it is refused and nothing of this wave "
                           "was collected: XRT's scheduler completes runs "
                           "early on a tile after a run there was abandoned "
                           "(a timeout, or a process that ended mid-run, in "
                           "this process or any other) until the image is "
                           "reloaded" +
                           (still ? std::string("; a tile was still running "
                                                "after the run's whole wait, "
                                                "so this handle is finished")
                                  : std::string("; each such tile has since "
                                                "finished it")) +
                           ". Reload the image - load another xclbin and "
                           "then this one - before trusting this tile "
                           "again";
                }, "run refused");
                return ST_INTERNAL;
            }
        }

        uint32_t ws = 0, wf = 0;
        uint32_t per[64] = {0};   /* a device has at most 64 tiles */
        bool flags_reg = false;   /* which read failed, for the sentence */
        try {
            for (size_t j = 0; j < count; j++) {
                at = order[j];
                flags_reg = false;
                const uint32_t sj =
                    D.tiles[order[j]].k.read_register(CSR_STATUS);
                if (j < 64)
                    per[j] = sj;
                ws |= sj;
                flags_reg = true;
                wf |= D.tiles[order[j]].k.read_register(CSR_FLAGS);
            }
        } catch (...) {
            D.poisoned = true;
            lose_outputs(D, flags_reg ? "an unreadable FLAGS register"
                                      : "an unreadable STATUS register");
            set_err_or([&] {
                return "reading " + tile_name(D, at) + "'s " +
                       (flags_reg ? "FLAGS" : "STATUS") + " after " +
                       J.what + " failed, so whether its results are "
                       "valid is not known; this handle is finished";
            }, "run failed");
            return ST_INTERNAL;
        }
        *status |= ws;
        *flags |= wf;
        for (size_t j = 0; j < count; j++)
            if (J.tasks[base + j].after)
                J.tasks[base + j].after(order[j]);
        if (J.faulty(*status)) {
            *faulted = true;
            lose_outputs(D, "a fault the tile reported");
            try {
                for (size_t j = 0; j < count && j < 64; j++)
                    if (J.faulty(per[j]))
                        J.where += (J.where.empty() ? "" : ", ") +
                                   tile_name(D, order[j]) + " STATUS 0x" +
                                   hex32(per[j]);
            } catch (...) {
            }
            return ST_OK;
        }
        try {
            for (size_t j = 0; j < count; j++) {
                at = order[j];
                J.tasks[base + j].collect(order[j]);
            }
        } catch (const std::exception &e) {
            lose_outputs(D, "a result that could not be read back");
            set_err_or([&] {
                return "reading the results of " + J.what + " from " +
                       tile_name(D, at) + ": " + std::string(e.what());
            }, "run failed");
            return ST_INTERNAL;
        }
    }
    D.job_outs.clear();
    return ST_OK;
}

}  // namespace

extern "C" const char *cftx_last_error(void)
{
    return g_err.c_str();
}

static int cftx_open_impl(const char *artifact, int index, void **out,
                          uint32_t *format_mask, uint32_t *op_groups,
                          uint32_t *tiles, uint32_t *version,
                          int *flags_readable, cft_seq_caps *seq)
{
    if (!artifact || !out)
        return ST_INVALID_ARGUMENT;
    *out = nullptr;
    g_err.clear();

    /* CFT_XRT_CAPS, device-test's instrument for cft_get_image_id's two
     * refusals, planted where the tiles' words are recorded (below). It
     * is read HERE, before anything is opened or loaded, so that a
     * malformed value is refused by name and at once, as the other
     * instruments docs/CARDDAY.md lists refuse theirs. An instrument that
     * read a typo as "no plant" would be a gate that could not fail, and
     * until 2026-09-28 this one did: plant-diff, PLANT-DIFFER, a trailing
     * space, 1 and yes were each quietly ignored (verifier-C3). Unset or
     * empty is no plant. */
    bool plant_differ = false, plant_unread = false;
    if (const char *cp = std::getenv("CFT_XRT_CAPS")) {
        if (!std::strcmp(cp, "plant-differ"))
            plant_differ = true;
        else if (!std::strcmp(cp, "plant-unreadable"))
            plant_unread = true;
        else if (*cp) {
            set_err(std::string("CFT_XRT_CAPS=\"") + cp + "\": expected "
                    "plant-differ or plant-unreadable; unset it for none");
            return ST_INVALID_ARGUMENT;
        }
    }

    /* Opening the card and loading the bitstream fail for completely
     * different reasons and want completely different responses - "no
     * card visible" is a driver or a slot, "bad xclbin" is a build.
     * Reporting both as one status is the sort of small dishonesty
     * that costs an hour at a bench. */
    /* Owned here until the open succeeds, so no path out - a refusal, or
     * an exception reaching the wrapper - can leak it or delete it
     * twice. */
    std::unique_ptr<Dev> own(new (std::nothrow) Dev());
    if (!own)
        return ST_OUT_OF_MEMORY;
    Dev *D = own.get();
    D->wait_ms = timeout_ms();

    try {
        D->dev = xrt::device(static_cast<unsigned int>(index));
    } catch (const std::exception &e) {
        set_err(std::string("opening device ") + std::to_string(index) +
                ": " + e.what());
        return ST_NO_DEVICE;
    }
    /* The image is read ONCE, hashed, and those same bytes are loaded
     * (cft_get_image_id): the digest is then of what was loaded by
     * construction, and never of the file read a second time. Until
     * 2026-09-28 XRT read the file itself, by path, and nothing hashed
     * it; load_xclbin(path) is xrt::xclbin(path) and a load of that
     * object, and xrt::xclbin(path) reads the file into exactly the
     * vector handed over here (believed from XRT's API and its 2.14
     * headers, which declare both). Measured since: it opened the 0907
     * quad image in hw_emu on XRT 2.14, and both round-2 images on the
     * U50 on XRT 2.19 (hw/card-identity.sh, 16 of 16, and the quick
     * matrix 2,456 of 2,456 after it; 2026-09-28). That the file is read
     * ONCE is held by reading this code: no gate can fail for a second
     * read that returns other bytes (verifier-C3, on a mock). The same
     * object also answers the compute-unit listing below, which read the
     * file a second time before. */
    std::vector<char> image;
    {
        std::string why;
        if (!read_image(artifact, image, why)) {
            set_err(std::move(why));
            return ST_ARTIFACT;
        }
    }
    {
        cft_sha256_ctx h;
        cft_sha256_init(&h);
        cft_sha256_update(&h, image.data(), image.size());
        cft_sha256_final(&h, D->image_sha256);
        D->image_bytes = image.size();
    }
    std::unique_ptr<xrt::xclbin> xb;
    try {
        xb.reset(new xrt::xclbin(image));
        D->uuid = D->dev.load_xclbin(*xb);
    } catch (const std::bad_alloc &) {
        throw;                          /* the boundary's out-of-memory */
    } catch (const std::exception &e) {
        set_err(std::string("loading ") + artifact + ": " + e.what());
        return ST_ARTIFACT;
    }

    /* Which compute units to open, and in what order.
     *
     * Preferred: the names the image itself declares, read out of it
     * with xrt::xclbin, and then what each one IS decided by MAGIC read
     * from it before it is kept - a compute unit that opens but does
     * not answer "CFT0" is dropped, not trusted. So a kernel packaged
     * under a variant name (hw/layouts' cft_krnl_f128_N) opens exactly
     * as cft_krnl_N does, and a foreign kernel sharing the image is
     * left alone. Until 2026-09-14 this loop probed the literal name
     * cft_krnl:{cft_krnl_N} and nothing else; cft-rebound's binary128
     * image had to keep the name cft_krnl to open at all (its
     * docs/BITSTREAM.md, ask 2), and docs/LAYOUTS.md's variant names
     * would have opened zero tiles.
     *
     * Fallback: an XRT without the listing API (see the include block)
     * probes cft_krnl_1..MAX_TILES by name as before, stopping at the
     * first gap.
     *
     * Exclusive access either way, because the status registers are
     * not readable otherwise. The FIRST failure's message is kept,
     * because the commonest reason a compute unit will not open is
     * that another process holds it - and reporting live contention as
     * "this is not a tile" sends the reader to entirely the wrong
     * place. */
    std::vector<std::string> names;
    std::string declared;          /* what the image lists, for the message */
#if CFT_XRT_XCLBIN_API
    try {
        /* The object built above from the bytes that were hashed and
         * loaded. (It was built here from the PATH until 2026-09-28, as
         * a std::string and not a const char*: XRT 2.19 also has
         * xclbin(const std::string_view&), which takes the xclbin's
         * BYTES, and a const char* converts to both. A std::vector<char>
         * converts to neither, so the byte constructor above is the one
         * picked.) */
        for (const auto &k : xb->get_kernels())
            for (const auto &cu : k.get_cus()) {
                /* XRT 2.19 answers the QUALIFIED name here -
                 * "cft_krnl:cft_krnl_1" - and the open string wants
                 * kernel:{instance}. Composed naively this read
                 * cft_krnl:{cft_krnl:cft_krnl_1} and opened no tile on
                 * the card (2026-09-14, the first run of this branch on
                 * silicon; both header generations had only been
                 * COMPILED before). The instance is what follows the
                 * last ':', or the whole name from an XRT that answers
                 * bare. */
                std::string inst = cu.get_name();
                const size_t colon = inst.rfind(':');
                if (colon != std::string::npos)
                    inst = inst.substr(colon + 1);
                names.push_back(k.get_name() + ":{" + inst + "}");
                declared += (declared.empty() ? "" : " ") + inst;
            }
    } catch (const std::exception &) {
        names.clear();             /* the probe below takes over */
    }
    /* Tile 0 is _1 whatever order the image lists them in, and _10 does
     * not sort before _2: order by the number a name ends in. */
    std::sort(names.begin(), names.end(),
              [](const std::string &a, const std::string &b) {
                  long x = cu_ordinal(a), y = cu_ordinal(b);
                  return x != y ? x < y : a < b;
              });
#endif
    const bool probing = names.empty();
    if (probing)
        for (int i = 1; i <= MAX_TILES; i++)
            names.push_back("cft_krnl:{cft_krnl_" + std::to_string(i) + "}");

    /* CFT_XRT_TILES (host/src/tile_select.h): open only the tiles it
     * names, in the order it names them - one process per tile is how
     * independent jobs share a card - and REFUSE, never shrink, when a
     * named tile is not in the image, will not open, or is not a cft
     * tile. Absent, every tile the image declares is opened, as before.
     * The ordinal is the number a compute unit's name ends in, which is
     * also the order tiles are opened in by default. */
    const char *const sel_env = std::getenv("CFT_XRT_TILES");
    const bool selecting = sel_env != nullptr;
    if (selecting) {
        int order[CFT_TILE_SELECT_MAX];
        char why[320];
        const int k = cft_tile_select_parse(sel_env, order, why, sizeof why);
        if (k < 0) {
            std::string msg(why);
            set_err(std::move(msg));
            return ST_INVALID_ARGUMENT;
        }
        std::vector<std::string> picked;
        for (int i = 0; i < k; i++) {
            std::string hit, also;
            for (const std::string &nm : names)
                if (cu_ordinal(nm) == order[i]) {
                    if (hit.empty())
                        hit = nm;
                    else
                        also += " " + nm;
                }
            if (hit.empty()) {
                /* The caller's selection names a tile the image does not
                 * have: the argument is wrong, not the artifact, so the
                 * status is the one a malformed list gets (Logan's word,
                 * 2026-09-25, after verifier-V2 found ARTIFACT's "missing,
                 * unreadable, or not a tile" misdescribing a valid quad). */
                std::string msg = std::string("CFT_XRT_TILES names tile ") +
                                  std::to_string(order[i]) + ", and " +
                                  artifact +
                                  (declared.empty()
                                       ? std::string(" declares no such "
                                                     "compute unit")
                                       : " declares " + declared);
                set_err(std::move(msg));
                return ST_INVALID_ARGUMENT;
            }
            if (!also.empty()) {
                /* A foreign kernel numbered like a tile: which one is
                 * the tile is MAGIC's call after an open, and a
                 * selection must not open the wrong one to find out. */
                std::string msg = std::string("CFT_XRT_TILES names tile ") +
                                  std::to_string(order[i]) + ", and more "
                                  "than one compute unit in " + artifact +
                                  " ends in that number: " + hit + also;
                set_err(std::move(msg));
                return ST_ARTIFACT;
            }
            picked.push_back(hit);
        }
        names.swap(picked);
    }

    std::string first_failure, not_tiles;
    /* A selection's refusal is decided inside the loop and carried out
     * after it. Deleting D inside the try and then building the message
     * once let a bad_alloc reach the catch below and delete it a second
     * time (verifier-V2, 2026-09-25, under ASan); D is now owned by a
     * unique_ptr for the whole open, so no path deletes it by hand. */
    int refused = ST_OK;
    std::string refusal;
    for (const std::string &nm : names) {
        try {
            xrt::kernel k(D->dev, D->uuid, nm,
                          xrt::kernel::cu_access_mode::exclusive);
            if (!probing || selecting) {
                uint32_t m = 0;
                try {
                    m = k.read_register(CSR_MAGIC);
                } catch (const std::exception &) {
                    m = 0;
                }
                if (m != TILE_MAGIC) {
                    if (selecting) {
                        refusal = "CFT_XRT_TILES names " + nm + ", which "
                                  "opened but did not answer MAGIC as a cft "
                                  "tile";
                        refused = ST_ARTIFACT;
                        break;
                    }
                    not_tiles += (not_tiles.empty() ? "" : " ") + nm;
                    continue;      /* opened, answered, not ours; released */
                }
            }
            D->tiles.emplace_back();
            D->tiles.back().k = std::move(k);
            D->tiles.back().cu = nm;
        } catch (const std::exception &e) {
            if (selecting) {
                /* Say which tile, and what XRT said. With the listing
                 * API the unit is one the image declares, and the
                 * commonest reason it will not open is that another
                 * process holds it - XRT 2.19 says "failed to open cu
                 * context: Invalid argument" (the card, 2026-09-25).
                 * Without it every ordinal is a guessed name, and one the
                 * image lacks fails too ("No compute units matching",
                 * the card on 2026-09-14), so the sentence does not
                 * guess which. */
                refusal = "CFT_XRT_TILES names " + nm + ", which could not "
                          "be opened: " + e.what() +
                          (probing ? " (this XRT cannot list an image's "
                                     "compute units, so one the image does "
                                     "not have and one another process "
                                     "holds are not told apart here)"
                                   : " (the image declares it, and a compute "
                                     "unit another process holds fails "
                                     "exactly this way)");
                refused = ST_ARTIFACT;
                break;
            }
            if (first_failure.empty())
                first_failure = e.what();
            if (probing)
                break;             /* the probe stops at the first gap */
        }
    }
    if (refused != ST_OK) {
        set_err(std::move(refusal));
        return refused;
    }
    if (D->tiles.empty()) {
        std::string msg = "no cft tile could be opened in " + std::string(artifact);
        if (!probing)
            msg += ": the image declares compute unit(s) " + declared +
                   (not_tiles.empty() ? "" : "; opened but not a cft tile by MAGIC: " + not_tiles);
        if (!first_failure.empty())
            msg += "; first failure: " + first_failure +
                   " (XRT says \"failed to open cu context\" for a compute "
                   "unit another process holds and \"No compute units "
                   "matching\" for one the image lacks - the card, 2026-09-14 "
                   "and 2026-09-25)";
        set_err(msg);
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
        set_err(buf);
        return ST_ARTIFACT;
    }
    if (!version_known(ver)) {
        /* The list is derived from KNOWN_VERSIONS, not typed: the
         * first version of this message named five of six. */
        std::string known;
        for (uint32_t k : KNOWN_VERSIONS) {
            char one[16];
            std::snprintf(one, sizeof one, "%s0x%x", known.empty() ? "" : ", ", k);
            known += one;
        }
        std::string msg = "hardware contract 0x";
        char hexv[16];
        std::snprintf(hexv, sizeof hexv, "%08x", ver);
        msg += hexv;
        msg += " is not one this library knows (" + known + ") - the "
               "register map may differ, and guessing is how a host "
               "misreads a result. What a tile IMPLEMENTS is CAPS, not this.";
        set_err(msg);
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
            set_err(std::string("this bitstream's contract is 0x800, whose "
                                "map has CAPS2 at 0x6C, and reading it "
                                "failed: ") + e.what());
            return ST_UNSUPPORTED;
        }
    }

    /* The completion witness at OPEN (2026-09-26, verifier-V8). Access
     * to a compute unit is exclusive, so no OPEN handle can be running
     * work on a tile this one has just opened: one that is not idle is
     * running a run abandoned there by a handle that is gone - one a
     * process that ended held, or one closed after a run failed in a
     * way that can leave the tile running (a timeout, a thrown wait, an
     * ERROR state, a completion refused because the tile was still busy
     * after the whole wait, an unreadable CTRL), in this process or
     * another (verifier-V9: the sentence blamed an ended process for
     * this process's own closed handle, then named only a timeout). Its
     * writes may land in the device memory this handle's buffers are
     * about to be given - probe 4 saw an abandoned run's output land in
     * a later process's buffers at the same addresses - and once it
     * ends no later reading of CTRL can see that it happened. So the
     * open is refused by name. CFT_XRT_WITNESS=busy-open plants a busy
     * reading on the first tile, so that device-test can hold the
     * refusal. */
    {
        const char *w = std::getenv("CFT_XRT_WITNESS");
        const bool plant_open = w && !std::strcmp(w, "busy-open");
        for (size_t tt = 0; tt < D->tiles.size(); tt++) {
            uint32_t c = 0;
            try {
                c = D->tiles[tt].k.read_register(CSR_CTRL);
            } catch (const std::exception &e) {
                set_err("reading " + tile_name(*D, tt) + "'s CTRL at open: " +
                        e.what());
                return ST_INTERNAL;
            }
            if (plant_open && tt == 0)
                c = CTRL_START;                  /* CFT_XRT_WITNESS */
            if ((c & CTRL_IDLE) && !(c & CTRL_START))
                continue;
            set_err(tile_name(*D, tt) + " is already running when this "
                    "handle opens it (CTRL 0x" + hex32(c) + ", not idle): a "
                    "run abandoned there - by a process that ended, or a "
                    "handle closed after a run failed - is still going, "
                    "and its writes may land in the memory this "
                    "handle's buffers would be given. Reload the image - "
                    "load another xclbin, then this one - before opening "
                    "this tile, or leave it out with CFT_XRT_TILES");
            return ST_INTERNAL;
        }
    }

    /* The raw capability words, for cft_get_image_id: tile 0's, which
     * the decode below reads, and every other opened tile's held equal
     * to them. This library has always decoded tile 0's CAPS and applied
     * it to every tile; a single pair of words called the IMAGE's is true
     * only if every tile publishes it, and a mixed layout's would not
     * (docs/LAYOUTS.md: CAPS is per compute unit). A tile that differs,
     * or whose words cannot be read, leaves the open exactly as it was -
     * refusing a mixed image here is not this record's call - and makes
     * cftx_image_id refuse, with a sentence that says which of the two
     * happened and names the tile.
     *
     * CFT_XRT_CAPS plants either one for device-test -i, in the manner of
     * CFT_XRT_WITNESS, so that both refusals have a gate that can fail on
     * an image with more than one tile: "plant-differ" takes tile 1's
     * CAPS with bit 0 flipped, and "plant-unreadable" makes its read
     * throw (the value was checked at the top of this function). Only
     * this record sees the planted word - everything the library DOES is
     * decoded from tile 0's, above and below - so a planted handle
     * computes exactly as an unplanted one, and only cft_get_image_id
     * changes, from an answer to a refusal; device-test holds a planted
     * handle's decoded caps equal to an unplanted one's. The plant acts on
     * the comparison's input, not on its verdict, so the comparison
     * itself is what the gate holds. Each refusal's sentence names the
     * plant when it made the difference, so one set by accident cannot
     * tell anyone their image is mixed or their tile unreadable. */
    D->n_caps        = ver >= SCRATCH_VERSION ? 2u : 1u;
    D->caps_words[0] = caps;
    D->caps_words[1] = D->n_caps > 1 ? caps2 : 0u;
    for (size_t tt = 1; tt < D->tiles.size(); tt++) {
        uint32_t c = 0, c2 = 0;
        try {
            if (plant_unread && tt == 1)
                throw std::runtime_error("planted by CFT_XRT_CAPS="
                                         "plant-unreadable");
            c = D->tiles[tt].k.read_register(CSR_CAPS);
            if (D->n_caps > 1)
                c2 = D->tiles[tt].k.read_register(CSR_CAPS2);
        } catch (const std::exception &e) {
            D->caps_refusal = "cft_get_image_id: " + tile_name(*D, tt) +
                              "'s CAPS could not be read at open (" +
                              e.what() + "), so nothing says this image's "
                              "tiles publish one set of words, and tile "
                              "0's are not reported as the image's";
            break;
        }
        const bool planted = plant_differ && tt == 1;
        if (planted)
            c ^= 0x1u;
        if (c != D->caps_words[0] || c2 != D->caps_words[1]) {
            const auto words = [&](uint32_t w, uint32_t w2) {
                return "CAPS 0x" + hex32(w) +
                       (D->n_caps > 1 ? " CAPS2 0x" + hex32(w2)
                                      : std::string());
            };
            D->caps_refusal = "cft_get_image_id: the tiles of this image "
                              "publish different CAPS words, so no one set "
                              "of them names it - " + tile_name(*D, tt) +
                              " publishes " + words(c, c2) +
                              (planted ? std::string(" (planted by "
                                         "CFT_XRT_CAPS=plant-differ: its "
                                         "real word with bit 0 flipped)")
                                       : std::string()) +
                              " and " + tile_name(*D, 0) + " " +
                              words(D->caps_words[0], D->caps_words[1]) +
                              ". A mixed layout (docs/LAYOUTS.md) needs a "
                              "word pair per tile, which this call does not "
                              "carry, and this library opens it as if every "
                              "tile were tile 0";
            break;
        }
    }

    /* ABI 0.18's device lines (cft.h, cft_image_id), recorded here with
     * the image's digest and words so that cftx_image_id still reaches no
     * device. The platform and the serial are XRT's answers, each "" where
     * XRT gives none or throws: neither can fail an open, and neither is
     * ever guessed. The kernel clock is the image's own record of its link
     * (xclbin_clock.h), for the compute units opened - the instance of
     * each kernel:{instance} name - and 0 where it names none for all. */
    try {
        D->platform_name = D->dev.get_info<xrt::info::device::name>();
    } catch (const std::bad_alloc &) {
        throw;                          /* the boundary's out-of-memory */
    } catch (const std::exception &) {
        D->platform_name.clear();
    }
    try {
        D->serial = json_string_of(
            D->dev.get_info<xrt::info::device::platform>(), "serial_number");
    } catch (const std::bad_alloc &) {
        throw;
    } catch (const std::exception &) {
        D->serial.clear();
    }
    {
        std::vector<std::string> inst;
        std::vector<const char *> ptr;
        for (const auto &t : D->tiles) {
            const size_t b = t.cu.find('{'), e = t.cu.rfind('}');
            inst.push_back(b != std::string::npos && e != std::string::npos
                           && e > b ? t.cu.substr(b + 1, e - b - 1) : t.cu);
        }
        for (const auto &s : inst)
            ptr.push_back(s.c_str());
        char why[320];
        uint64_t hz = 0;
        if (cft_xclbin_kernel_clock(
                reinterpret_cast<const unsigned char *>(image.data()),
                image.size(), ptr.data(), ptr.size(), &hz, why, sizeof why))
            D->clock_hz = hz;
        else
            D->clock_hz = 0;
    }

    D->version      = ver;
    *format_mask    = caps & 0xFu;
    *op_groups      = (caps >> 8) & 0xFFu;
    *tiles          = static_cast<uint32_t>(D->tiles.size());
    *version        = ver;
    *flags_readable = 1;      /* proven above, or we did not get here */
    if (seq) {
        /* What the three words MEAN is host/src/caps_decode.h's - every
         * feature nibble and bit, every capacity, and the map each is
         * believed on, revision 8's CAPS2[14:11] (seq_features bits 15 to
         * 18) and CAPS2[20:16] (max_insns) behind 0xB00 among them - so
         * that api_test holds the decode on machines that cannot build
         * this file. It moved there unchanged for every map below 0xB00
         * (2026-10-02, revision 8's seam). */
        cft_caps_decode(ver, caps, caps2, seq);
    }
    *out            = own.release();
    return ST_OK;
}

/* The C boundary. No C++ exception may cross it: every entry point
 * below is a thin wrapper that runs its implementation and turns an
 * escaping bad_alloc into CFT_ERR_OUT_OF_MEMORY and anything else into
 * CFT_ERR_INTERNAL, with a sentence. Once a unit may have run, run_job
 * itself lets nothing escape (it waits, poisons and marks outputs
 * first), so what reaches these handlers happened before any start or
 * after every run finished. Before 2026-09-25 most allocation failures
 * in cftx_open escaped as bad_alloc and leaked the device object
 * (verifier-V2, then verifier-V4). */
extern "C" int cftx_open(const char *artifact, int index, void **out,
                         uint32_t *format_mask, uint32_t *op_groups,
                         uint32_t *tiles, uint32_t *version,
                         int *flags_readable, cft_seq_caps *seq)
{
    return at_boundary("opening the device", [&] {
        return cftx_open_impl(artifact, index, out, format_mask, op_groups,
                              tiles, version, flags_readable, seq);
    });
}

extern "C" void cftx_close(void *hw)
{
    delete static_cast<Dev *>(hw);
}

/* The image's identity, as cftx_open recorded it (backend.h). Touches no
 * device, so it answers on a poisoned handle: what was loaded is still
 * what was loaded. */
extern "C" int cftx_image_id(void *hw, cft_image_raw *out)
{
    return at_boundary("reading the device image's identity", [&]() -> int {
        g_err.clear();
        const Dev *D = static_cast<const Dev *>(hw);
        if (!D || !out)
            return ST_INVALID_ARGUMENT;
        if (!D->caps_refusal.empty()) {
            set_err(D->caps_refusal);
            return ST_UNSUPPORTED;
        }
        std::memcpy(out->sha256, D->image_sha256, sizeof out->sha256);
        out->bytes   = D->image_bytes;
        out->version = D->version;
        out->n_caps  = D->n_caps;
        for (int i = 0; i < 4; i++)
            out->caps[i] = D->caps_words[i];
        /* ABI 0.18: the device lines, as cftx_open recorded them */
        put_text(out->platform, sizeof out->platform, D->platform_name);
        put_text(out->xrt_version, sizeof out->xrt_version,
                 xrt_built_version());
        out->clock_hz = D->clock_hz;
        put_text(out->serial, sizeof out->serial, D->serial);
        return ST_OK;
    });
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
        B->copies.resize(D.tiles.size() * CFT_ROLE_COUNT);
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

/* A LOST buffer's refusal, in the words its loss left (Buf::lost). */
int buf_refuse_lost(const Buf &B) noexcept
{
    set_err_or([&] {
        return B.lost_why.empty()
                   ? std::string("a failed run lost this resident buffer's "
                                 "contents; publish them again with "
                                 "cft_buffer_to_device")
                   : B.lost_why;
    }, "buffer lost");
    return ST_INTERNAL;
}

/* [off, off + len) of a buffer, clamped to it. */
void buf_range(const Buf &B, size_t off, size_t len, size_t *lo, size_t *hi)
{
    *lo = off < B.bytes ? off : B.bytes;
    *hi = len < B.bytes - *lo ? *lo + len : B.bytes;
}

extern "C" int cftx_buffer_to_device(void *buf)
{
    if (!buf)
        return ST_INVALID_ARGUMENT;
    Buf &B = *static_cast<Buf *>(buf);
    return at_boundary("publishing a resident buffer", [&]() -> int {
        /* A buffer a failed run LOST: the caller is supplying its
         * contents, so what the device holds is dropped and the loss is
         * cleared. */
        if (B.lost) {
            for (auto &c : B.copies)
                c.dirty = false;
            B.lost = false;
            B.lost_why.clear();
            B.gen++;
            return ST_OK;
        }
        /* A run's results still on the device and never read back:
         * REFUSED (Logan's rule, 2026-09-26). The library cannot tell
         * whether the host copy was written since the run - a store of
         * the same bytes looks like none, so no test of the contents can
         * tell - and each way of guessing returns wrong bytes with CFT_OK
         * for one of the two ways of calling this: dropping the device's
         * bytes loses the run's results from a publish nobody wrote
         * before (verifier-V7), bringing them home first puts them over a
         * caller's rewrite (verifier-V8, N6). Nothing is changed; the
         * caller reads the buffer back first, which keeps the run's
         * results, then writes and publishes. */
        for (const auto &c : B.copies)
            if (c.dirty) {
                set_err_or([] {
                    return std::string(
                        "cft_buffer_to_device: a run's results in this "
                        "buffer are still on the device and were never read "
                        "back, so whether the host copy was written since "
                        "cannot be known and publishing could keep the "
                        "wrong bytes - read it back first "
                        "(cft_buffer_from_device keeps the run's results), "
                        "then write and publish; nothing was changed "
                        "(docs/HOSTAPI.md)");
                }, "publish refused: read the buffer back first");
                return ST_INVALID_ARGUMENT;
            }
        /* The mirror is the truth from here: every copy is stale and
         * refills at its next binding. Nothing moves. */
        B.gen++;
        return ST_OK;
    });
}

extern "C" int cftx_buffer_from_device(void *buf)
{
    if (!buf)
        return ST_INVALID_ARGUMENT;
    Buf &B = *static_cast<Buf *>(buf);
    /* Behind the boundary like every other entry point: its error path
     * builds a sentence, and a bad_alloc there reached C (verifier-V7,
     * 2026-09-25). */
    return at_boundary("reading a resident buffer back", [&]() -> int {
        /* A failed run may have written part of a window over bytes that
         * never came home: nothing on the device, and nothing in the
         * mirror, is this buffer's contents any more (Buf::lost). */
        if (B.lost)
            return buf_refuse_lost(B);
        /* Each flush stales the copies over the bytes it moved and marks
         * its own copy current; a read-back with nothing dirty changes
         * nothing at all, so a caller who calls this after every run -
         * the correct thing to do - pays no refills for it. */
        for (auto &c : B.copies)
            (void)buf_flush(B, c);
        return ST_OK;
    });
}

extern "C" int cftx_buffer_will_write(void *buf, size_t off, size_t len)
{
    if (!buf)
        return ST_INVALID_ARGUMENT;
    Buf &B = *static_cast<Buf *>(buf);
    return at_boundary("preparing a resident buffer for a host write",
                       [&]() -> int {
        /* Writing into a lost buffer is refused like reading it: its
         * bytes outside the write would still be nobody's. */
        if (B.lost)
            return buf_refuse_lost(B);
        size_t lo, hi;
        buf_range(B, off, len, &lo, &hi);
        /* A run's bytes over the range come home first, WHOLE: the write
         * may not cover all of them - an entry point that fails part way,
         * a copy whose window reaches past the range - and what it does
         * not cover has to be the run's. */
        for (auto &c : B.copies)
            if (c.dirty && c.off < hi && lo < c.off + c.real)
                (void)buf_flush(B, c);
        buf_touched(B, lo, hi, nullptr);
        return ST_OK;
    });
}

extern "C" int cftx_buffer_host_wrote(void *buf, size_t off, size_t len)
{
    if (!buf)
        return ST_INVALID_ARGUMENT;
    Buf &B = *static_cast<Buf *>(buf);
    size_t lo, hi;
    buf_range(B, off, len, &lo, &hi);
    buf_host_wrote(B, lo, hi);
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
    /* A LOST buffer has no authority anywhere (docs/HOSTAPI.md's table);
     * its `why` says so, first. */
    if (device_authority) *device_authority = B.lost ? 0 : dirty;
    if (resident_binds)   *resident_binds = B.resident_binds;
    if (staged_binds)     *staged_binds = B.staged_binds;
    if (why && why_bytes) {
        if (B.lost)
            std::snprintf(why, why_bytes, "LOST: %s", B.lost_why.c_str());
        else
            std::snprintf(why, why_bytes, "%s", B.why.c_str());
    }
}

/* MODE[18:16], the stride-0 operands. Named rather than written as a
 * shift at the use site, because MODE's layout lives in docs/HOSTAPI.md
 * and one place here. */
constexpr uint32_t MODE_SCALAR_SH = 16;

static int cftx_run_impl(void *hw, int op, int fmt, int rnd,
                         const void *a, const void *b, const void *c,
                         void *d, size_t n, uint32_t scalar_mask,
                         const cft_bindings *bind,
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
                          (static_cast<uint32_t>(rnd & 0x7) << 12) |
                          ((scalar_mask & 7u) << MODE_SCALAR_SH);

    const auto *pa = static_cast<const uint8_t *>(a);
    const auto *pb = static_cast<const uint8_t *>(b);
    const auto *pc = static_cast<const uint8_t *>(c);
    auto *pd = static_cast<uint8_t *>(d);

    /* The split itself is in slice.h, as a pure function, so that
     * host/tests can exercise it over every interesting n and tile
     * count without a card - which is where the arithmetic that
     * decides whether every element is computed exactly once belongs.
     *
     * Each slice is one task, and the scheduler (run_job, above)
     * places it: CFT_XRT_TILE_ORDER moves them between the tiles. A
     * SEQUENCER run's lanes are cut by the same planner, with every
     * per-lane block to match (lane_cut.h). An elementwise element
     * depends on its own index and nothing else, which is what makes
     * this partitioning unobservable; a sequencer lane depends on its
     * own index too, but the early exit is a CROSS-LANE condition, so
     * "four tiles give the same bits as one" is a claim about P3
     * (docs/SEQUENCER.md) rather than a corollary of the dataflow -
     * which is why that path carries CFT_XRT_PROGRAM_CUTS, to fuzz the
     * cut on a card. Until 2026-09-25 a program ran on tile 0 alone.
     */
    std::vector<cft_slice> slices(ntiles);
    slices.resize(cft_plan_slices(n, esz, ntiles, slices.data()));

    /* Which buffer object each of a slice's four operands is bound to,
     * on the tile the scheduler put it on. A null entry means "the
     * tile's own staging buffer", which is what every operand was
     * before resident buffers existed - so a run with no bindings at
     * all walks exactly the old path. */
    struct SliceBind { xrt::bo *bo[4]; };
    std::vector<SliceBind> sb(slices.size());
    for (auto &e : sb) { e.bo[0] = e.bo[1] = e.bo[2] = e.bo[3] = nullptr; }

    Job J;
    J.what = "a run";
    J.oom_words = "each tile's HBM group is finite; try a smaller n or "
                  "cft_alloc";
    J.faulty = [](uint32_t s) { return s != 0; };
    for (size_t i = 0; i < slices.size(); i++) {
        Task t;
        /* Staging touches only host-visible buffers and starts nothing,
         * so a failure here leaves every compute unit idle and the
         * device perfectly reusable. Binding a resident buffer
         * allocates and may fill, which is the same kind of work and
         * the same guarantee. */
        t.stage = [&, i](size_t tl) {
            const cft_slice &s = slices[i];
            Tile &tile = D.tiles[tl];
            const uint8_t *src[4] = {pa, pb, pc, nullptr};
            size_t staged_need = 0;

            /* A SCALAR operand is not partitioned. Every tile reads
             * element 0 of the same one-element buffer, so its offset
             * is not advanced by first_elem and its length is one
             * element rather than the slice's - get this wrong and tile
             * 2 reads element first_elem, which is a plausible number
             * and therefore the worst kind of wrong. CFT_ROLE_D is never
             * scalar: a run writes every element it was asked for. */
            for (int r = 0; r < 4; r++) {
                sb[i].bo[r] = nullptr;
                if (!bind || !bind->buf[r])
                    continue;
                const bool scal = (r < 3) &&
                                  (((scalar_mask >> r) & 1u) != 0);
                Buf &B = *static_cast<Buf *>(bind->buf[r]);
                sb[i].bo[r] = buf_bind(B, tl, r,
                                       bind->off[r] +
                                           (scal ? 0u : s.first_elem * esz),
                                       scal ? esz : s.real * esz,
                                       scal ? esz : s.padded * esz,
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
                const bool scal = ((scalar_mask >> r) & 1u) != 0;
                stage(*tb[r],
                      src[r] ? src[r] + (scal ? 0u : s.first_elem * esz)
                             : nullptr,
                      scal ? esz : s.real * esz,
                      scal ? esz : s.padded * esz);
            }
            for (int r = 0; r < 4; r++)
                if (!sb[i].bo[r])
                    sb[i].bo[r] = tb[r];
        };
        t.start = [&, i](size_t tl) {
            return D.tiles[tl].k(mode, static_cast<uint64_t>(slices[i].padded),
                                 *sb[i].bo[0], *sb[i].bo[1], *sb[i].bo[2],
                                 *sb[i].bo[3]);
        };
        t.collect = [&, i](size_t tl) {
            const cft_slice &s = slices[i];
            Tile &tile = D.tiles[tl];
            /* A RESIDENT output does not come back. The bytes are on the
             * device, that copy is now the authority, and the caller
             * collects them with cft_buffer_from_device when it wants
             * them - which is the whole saving on this side of the call,
             * and the reason the rule in cft.h exists. */
            if (bind && bind->buf[CFT_ROLE_D] && sb[i].bo[3] != &tile.d) {
                buf_mark_written(*static_cast<Buf *>(bind->buf[CFT_ROLE_D]),
                                 tl, CFT_ROLE_D);
                return;
            }
            tile.d.sync(XCL_BO_SYNC_BO_FROM_DEVICE, s.padded * esz, 0);
            std::memcpy(pd + s.first_elem * esz, tile.d.map<uint8_t *>(),
                        s.real * esz);
            /* A resident output whose bind was DECLINED was staged, and
             * its bytes just landed in the buffer's mirror on the host. */
            if (bind && bind->buf[CFT_ROLE_D]) {
                const size_t lo =
                    bind->off[CFT_ROLE_D] + s.first_elem * esz;
                buf_host_wrote(*static_cast<Buf *>(bind->buf[CFT_ROLE_D]),
                               lo, lo + s.real * esz);
            }
        };
        J.tasks.push_back(std::move(t));
    }

    uint32_t status_acc = 0, flag_acc = 0, fail = 0;
    bool faulted = false;
    const int st = run_job(D, J, &status_acc, &flag_acc, &faulted, &fail);
    if (st != ST_OK) {
        /* After a start, *bus carries the best-effort STATUS read that
         * the message already names, as this path always has. */
        if (D.poisoned && bus)
            *bus = fail;
        return st;
    }

    /* Faults before results. If the memory system did not vouch for the
     * data then comparing the output against anything is meaningless,
     * because the bits under test were never delivered - and the
     * scheduler collected nothing once STATUS said so. */
    if (faulted) {
        /* STATUS[3] is the precision refusal, not a bus fault: the run
         * never started and no memory moved. Reaching it through libcft
         * means the device's CAPS and its refusal logic disagree with
         * each other - the library checks CAPS before issuing - so name
         * that loudly rather than folding it into "the memory system
         * misbehaved". A single tile can never report both (the kernel
         * masks the engine's stale sticky while its last start was
         * refused - the adversarial review caught the ORed-truths
         * version); bits 2:0 beside bit 3 can only mean DIFFERENT tiles
         * refused and faulted, and the faulting tile's invalid data is
         * the worse fact. */
        if ((status_acc & 0x8u) && !(status_acc & 0x7u)) {
            /* the contract scopes *bus to CFT_ERR_BUS_FAULT, so the
             * refusal keeps its detail in the message alone */
            set_err("kernel REFUSED the run: MODE selected a precision "
                    "this bitstream does not implement (STATUS 0x" +
                    hex32(status_acc) + "). CAPS advertised otherwise, "
                    "which is a device/library disagreement worth "
                    "reporting" + at_where(J));
            return ST_UNSUPPORTED;
        }
        if (bus)
            *bus = status_acc;
        set_err("kernel reported bus faults; the output is not valid" +
                at_where(J));
        return ST_BUS_FAULT;
    }

    if (flags)
        *flags = flag_acc;
    return ST_OK;
}

extern "C" int cftx_run(void *hw, int op, int fmt, int rnd,
                        const void *a, const void *b, const void *c,
                        void *d, size_t n, uint32_t scalar_mask,
                        const cft_bindings *bind,
                        uint32_t *flags, uint32_t *bus)
{
    return at_boundary("a run", [&] {
        return cftx_run_impl(hw, op, fmt, rnd, a, b, c, d, n, scalar_mask,
                             bind, flags, bus);
    });
}

/* ---- sequencer programs -------------------------------------------
 *
 * Every tile the device has, since 2026-09-25: the run's lanes are
 * cut the way an elementwise run's elements are, every per-lane block
 * with them (lane_cut.h), and each slice is a task the scheduler
 * places (run_job) - the plan of record's step 2, docs/ROADMAP.md
 * "Programs across tiles". The comment beside cftx_run's partitioning
 * says why that is a claim about P3 rather than a corollary of the
 * dataflow - the early exit is a cross-lane condition - so the cut is
 * fuzzed on a card (CFT_XRT_PROGRAM_CUTS, below) rather than assumed.
 * Until then a program ran on tile 0.
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
static int cftx_program_run_impl(void *hw, int fmt, const void *image,
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
    /* R23's per-lane flags block (ABI 0.17): n bytes, lane i's at byte i,
     * or NULL. program.c held its count to n by name; held again here,
     * as the scratch blocks are held to their shapes below, because a
     * count this file cut by and the caller did not mean would hand a
     * tile's bytes to another lane. */
    uint8_t *const lane_flags = io->lane_flags;
    if (bank_bytes && !bank)
        return ST_INVALID_ARGUMENT;
    if ((sin_bytes && !scratch_in) || (sout_bytes && !scratch_out))
        return ST_INVALID_ARGUMENT;
    if ((io->lane_flags_bytes && !lane_flags) ||
        (lane_flags && io->lane_flags_bytes != n))
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

    /* And a fourth time, for the index tables: a tile below 0xA00 has
     * no IDX_A_PTR..IDX_SI_PTR and no twelfth through fifteenth kernel
     * argument, so there is nowhere to put a table and no MODE bit that
     * would select it. device.c has already refused a table against a
     * device whose CAPS2[9] is clear, which is the refusal a caller
     * should see; this is the second line of the same defence, for a
     * device whose CAPS2 and whose VERSION disagree. */
    if (io && (io->idx_a || io->idx_b || io->idx_c || io->idx_scratch_in) &&
        D.version < IDX_VERSION) {
        char buf[256];
        std::snprintf(buf, sizeof buf,
                      "this bitstream's contract is 0x%08x, which has no "
                      "index-table registers - an indexed input block "
                      "arrived at 0x%08x. CAPS2 bit 9 says in advance which "
                      "it is.",
                      D.version, IDX_VERSION);
        set_err(buf);
        return ST_UNSUPPORTED;
    }

    /* And a fifth time, for the lane mask: MASK_PTR and argument 16
     * arrived in the same contract the tables did, so a tile below
     * 0xA00 has nowhere to put one. device.c has already refused a
     * mask against a device whose CAPS2[10] is clear, which is the
     * refusal a caller should see; this is the second line of the same
     * defence, for a device whose CAPS2 and whose VERSION disagree. */
    if (io && io->lane_mask && D.version < IDX_VERSION) {
        char buf[256];
        std::snprintf(buf, sizeof buf,
                      "this bitstream's contract is 0x%08x, which has no "
                      "MASK_PTR - the per-run lane mask arrived at 0x%08x. "
                      "CAPS2 bit 10 says in advance which it is.",
                      D.version, IDX_VERSION);
        set_err(buf);
        return ST_UNSUPPORTED;
    }

    /* And a sixth time, for R23's per-lane flags block: LFLAGS_PTR and
     * argument 17 arrived at 0xB00, so a tile below it has nowhere to
     * write one. device.c has already refused the block against a device
     * that does not publish CAPS2[13] - the refusal a caller should see,
     * naming CFT_SEQ_FEAT_LANE_FLAGS; caps_decode.h believes that bit only
     * from 0xB00, so this is the second line of the same defence, for a
     * device whose CAPS2 and whose VERSION disagree. */
    if (lane_flags && D.version < LFLAGS_VERSION) {
        char buf[256];
        std::snprintf(buf, sizeof buf,
                      "this bitstream's contract is 0x%08x, which has no "
                      "LFLAGS_PTR - the per-lane flags block arrived at "
                      "0x%08x. CAPS2 bit 13 says in advance which it is.",
                      D.version, LFLAGS_VERSION);
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

    /* ---- the lane cut: the scheduler's first strategy for programs ----
     *
     * (docs/ROADMAP.md, "Programs across tiles", the plan of record's
     * step 2.) A program's lanes are cut the way an elementwise run's
     * elements are - cft_plan_slices' beat boundaries - and every
     * per-lane block goes with its lanes, by lane_cut.h's windows: the
     * dense streams' elements, and [first * w, (first + lanes) * w) of
     * the deposit window, the counts, the two scratch blocks and the
     * index tables. An indexed stream's SOURCE, and an indexed
     * scratch-in's, go to every tile whole, because a lane's index can
     * reach anywhere in them; so do the image and the bank. The mask is
     * repacked per tile from its slice's first lane. Each slice is one
     * task, and the scheduler places it; each tile is told its slice's
     * lane count as N, so its early exit is its own lanes' - SEQUENCER.md's
     * P3 says that exit is invisible, which is what makes the cut
     * unobservable, and the card gate fuzzes it rather than assuming it.
     *
     * CFT_XRT_PROGRAM_CUTS, a card instrument read per call:
     *   unset       cft_plan_slices, the default
     *   seed:<N>    cuts anywhere - one lane, an odd offset, a slice left
     *               out - from lane_cut.h's seeded planner
     *   skew:<N>    the same cuts, and every slice after the first stages
     *               a dense `a` from one lane EARLY: a planted fault, the
     *               placement tests' negative control (device-test's
     *               program legs must go red under it). Early, never
     *               late, so it cannot read past the caller's buffer.
     * CFT_XRT_TILE_ORDER, the scheduler's, moves the slices between the
     * tiles. Until 2026-09-25 a program ran on tile 0 alone. */
    std::vector<cft_slice> slices(D.tiles.size());
    bool skew = false;
    {
        uint64_t seed = 0;
        const int ist = instrument_seed("CFT_XRT_PROGRAM_CUTS", true, &seed,
                                        &skew);
        if (ist != ST_OK)
            return ist;
        slices.resize(seed ? cft_plan_lane_cuts(n, D.tiles.size(), seed,
                                                slices.data())
                           : cft_plan_slices(n, esz, D.tiles.size(),
                                             slices.data()));
    }

    /* The run's shape, which lane_cut.h cuts by. program.c held every
     * byte count to the program's header; what is checked here is that
     * each count agrees with the shape it is about to be cut by, so a
     * disagreement is named rather than read as slices of the wrong
     * width. An INDEXED scratch-in's count is its pool's, a dense one's
     * the block's - device.c's remark that this is the one field whose
     * meaning changes with the table. */
    cft_lane_shape shape;
    std::memset(&shape, 0, sizeof shape);
    shape.n = n;
    shape.esz = esz;
    shape.max_deposits = max_deposits;
    shape.n_sin = io->n_scratch_in;
    shape.n_sout = io->n_scratch_out;
    shape.has_sin = sin_bytes != 0;
    shape.has_sout = sout_bytes != 0;
    shape.src_elems[0] = io->idx_a ? io->idx_a_src : 0;
    shape.src_elems[1] = io->idx_b ? io->idx_b_src : 0;
    shape.src_elems[2] = io->idx_c ? io->idx_c_src : 0;
    shape.src_elems[3] = io->idx_scratch_in ? io->idx_scratch_src : 0;
    shape.has_lf = lane_flags != nullptr;
    {
        const size_t sin_want = shape.src_elems[3]
                                    ? shape.src_elems[3] * esz
                                    : n * shape.n_sin * esz;
        const size_t sout_want = n * shape.n_sout * esz;
        if ((sin_bytes && sin_bytes != sin_want) ||
            (sout_bytes && sout_bytes != sout_want)) {
            set_err("a program run's scratch blocks disagree with their "
                    "shapes (in " + std::to_string(sin_bytes) + " bytes, "
                    "shape " + std::to_string(sin_want) + "; out " +
                    std::to_string(sout_bytes) + ", shape " +
                    std::to_string(sout_want) + ") - cut by lane, a tile "
                    "would be handed another lane's slots");
            return ST_INTERNAL;
        }
    }

    /* MODE[22:19] and MODE[23], set from the same pointers the tables'
     * and the mask's bytes come from, so a table cannot be staged
     * without its bit or a bit set without its table. The same on every
     * tile: what a tile gathers is decided by the run, not the cut. */
    const uint32_t *const itab[4] = {io->idx_a, io->idx_b, io->idx_c,
                                     io->idx_scratch_in};
    uint32_t idx_mode = 0;
    for (int r = 0; r < 3; r++)
        if (itab[r])
            idx_mode |= 1u << (19 + r);
    if (itab[3] && io->n_scratch_in)
        idx_mode |= 1u << 22;
    const uint8_t *const lane_mask = io->lane_mask;
    if (lane_mask)
        idx_mode |= 1u << 23;
    /* MODE[24] from the same pointer the block's bytes go to, for the
     * same reason: a buffer bound without its bit, or the bit without its
     * buffer, cannot happen. The same on every tile. */
    if (lane_flags)
        idx_mode |= MODE_LFLAGS;

    /* MODE[7:0] is not written because it is ignored: the program says
     * what to compute. So is the rounding field - every instruction
     * carries its own attribute. N is the SLICE's lane count and NOT a
     * padded one: lanes at or beyond it start inactive, which is how
     * beat padding is made harmless for a program whose map nobody has
     * read. */
    const uint32_t mode = MODE_SEQ | idx_mode |
                          (static_cast<uint32_t>(fmt & 0xF) << 8);

    const size_t img_bytes = beat_round(image_bytes);
    /* One beat when there is no bank, so a 0x700 tile's ninth argument
     * is always a real, addressable buffer. beat_round(0) is 0 and a
     * zero-length xrt::bo is not something to rely on. */
    const size_t bnk_bytes = bank_bytes ? beat_round(bank_bytes) : 32u;

    /* One slice's windows, the buffer sizes a tile needs for it, and -
     * once the scheduler has placed and staged it - the buffer object
     * each role is bound to on that tile. The streams' pads are what
     * beat_round has always made of them - a dense slice's lanes * esz,
     * an indexed stream's whole source - and a block the run does not
     * have is one beat, because the kernel has the argument either way
     * and XRT will not submit a run with one unbound. */
    struct PSlice {
        size_t first, lanes;
        cft_lane_win w[CFT_LANE_ROLES];
        size_t spad[3], dep_pad, cnt_pad, sin_pad, sout_pad, itab_pad[4];
        size_t mask_pad, lf_pad;
        xrt::bo *ob[CFT_ROLE_COUNT];
    };
    std::vector<PSlice> ps(slices.size());
    for (size_t i = 0; i < slices.size(); i++) {
        PSlice &p = ps[i];
        p.first = slices[i].first_elem;
        p.lanes = slices[i].real;
        cft_lane_windows(&shape, p.first, p.lanes, p.w);
        for (int r = 0; r < 3; r++)
            p.spad[r] = beat_round(p.w[r].len);
        p.dep_pad = beat_round(p.w[CFT_LANE_DEP].len);
        p.cnt_pad = beat_round(p.w[CFT_LANE_CNT].len);
        p.sin_pad = sin_bytes ? beat_round(p.w[CFT_LANE_SIN].len) : 32u;
        p.sout_pad = sout_bytes ? beat_round(p.w[CFT_LANE_SOUT].len) : 32u;
        for (int r = 0; r < 4; r++) {
            const size_t len = p.w[CFT_LANE_IA + r].len;
            p.itab_pad[r] = len ? beat_round(len) : 32u;
        }
        /* ONE BIT A LANE at every format, with or without a mask: with
         * none, stage_mask writes a one for every lane, so a MODE[23]
         * the host did not set could only ever read as "every lane". */
        p.mask_pad = std::max(beat_round(cft_mask_bytes(p.lanes)),
                              static_cast<size_t>(32));
        /* R23's block: the slice's lanes, a byte each, beat-rounded. The
         * tile drains it 32 lanes a beat from its own lane 0 - lane j at
         * byte j, so a block of 16 fp256 lanes starts on a 16-byte
         * boundary and goes as half a beat with byte strobes - and
         * strobes off every lane at or past its N. A drain that sent its
         * last block's beats whole would still land inside the buffer:
         * ensure_one's capacity is whole 4 KiB pages, and a block (128,
         * 64, 32 or 16 bytes, on its own boundary) never crosses one. One
         * beat, the stand-in, when the run does not ask. */
        p.lf_pad = lane_flags ? std::max(beat_round(p.w[CFT_LANE_LF].len),
                                         static_cast<size_t>(32))
                              : 32u;
        for (int r = 0; r < CFT_ROLE_COUNT; r++)
            p.ob[r] = nullptr;
    }

    const auto *pa = static_cast<const uint8_t *>(a);
    const auto *pb = static_cast<const uint8_t *>(b);
    const auto *pc = static_cast<const uint8_t *>(c);
    auto *pdep = static_cast<uint8_t *>(deposits);
    auto *pcnt = reinterpret_cast<uint8_t *>(counts);
    const auto *psin = static_cast<const uint8_t *>(scratch_in);
    auto *psout = static_cast<uint8_t *>(scratch_out);
    uint8_t *const plf = lane_flags;
    const bool trace = std::getenv("CFT_XRT_TRACE") != nullptr;
    const char *const mask_ov = std::getenv("CFT_XRT_MASK_ADDR_OVERRIDE");

    Job J;
    J.what = "a program";
    J.oom_words = "a program's deposit window is n * max_deposits "
                  "elements, so it outgrows an HBM group sooner than an "
                  "elementwise run does";
    /* A program's STATUS carries REPORTS as well as faults - the deposit
     * overflow and the range report are the lanes' news, not the
     * memory's - so only the refusal and the bus bits stop a job. */
    J.faulty = [](uint32_t s) {
        return (s & (ST_REFUSED | ST_BUS_BITS)) != 0;
    };
    for (size_t i = 0; i < ps.size(); i++) {
        Task t;
        /* Which of the operand-shaped buffers came from cft_alloc: the
         * three streams, the deposit window, the two scratch blocks and
         * the four tables, each bound at its slice's window of the
         * caller's buffer on the tile the scheduler chose. The image,
         * the bank, the counts and R23's per-lane flags are staged
         * always: the image and the bank do not grow with n at all, the
         * counts are four bytes a lane whatever the format, and the flags
         * one. */
        t.stage = [&, i](size_t tl) {
            PSlice &p = ps[i];
            Tile &tile = D.tiles[tl];
            xrt::bo **const ob = p.ob;
            const cft_lane_win *const w = p.w;
            for (int r = 0; r < CFT_ROLE_COUNT; r++)
                ob[r] = nullptr;

            if (bind) {
                const void *src[3] = {a, b, c};
                for (int r = 0; r < 3; r++)
                    if (bind->buf[r] && src[r])
                        ob[r] = buf_bind(*static_cast<Buf *>(bind->buf[r]),
                                         tl, r, bind->off[r] + w[r].off,
                                         w[r].len, p.spad[r], false);
                /* Under a lane mask the tile leaves a masked lane's
                 * deposit slots and scratch-out slots as they were, so a
                 * resident window is bound PRESERVING: its copy made
                 * current first, like an input (buf_bind). */
                const bool keep = lane_mask != nullptr;
                if (bind->buf[CFT_ROLE_D] && deposits && max_deposits)
                    ob[3] = buf_bind(
                        *static_cast<Buf *>(bind->buf[CFT_ROLE_D]), tl,
                        CFT_ROLE_D,
                        bind->off[CFT_ROLE_D] + w[CFT_LANE_DEP].off,
                        w[CFT_LANE_DEP].len, p.dep_pad, true, keep);
                /* The scratch blocks, on the deposit window's terms.
                 * Guarded on the BYTE COUNT and not only the pointer: a
                 * program that declares no scratch I/O gets a one-beat
                 * staging buffer the tile never reads, and binding a
                 * caller's buffer for a block of zero length would be a
                 * window no run has. */
                if (bind->buf[CFT_ROLE_SI] && scratch_in && sin_bytes)
                    ob[CFT_ROLE_SI] = buf_bind(
                        *static_cast<Buf *>(bind->buf[CFT_ROLE_SI]), tl,
                        CFT_ROLE_SI,
                        bind->off[CFT_ROLE_SI] + w[CFT_LANE_SIN].off,
                        w[CFT_LANE_SIN].len, p.sin_pad, false);
                if (bind->buf[CFT_ROLE_SO] && scratch_out && sout_bytes)
                    ob[CFT_ROLE_SO] = buf_bind(
                        *static_cast<Buf *>(bind->buf[CFT_ROLE_SO]), tl,
                        CFT_ROLE_SO,
                        bind->off[CFT_ROLE_SO] + w[CFT_LANE_SOUT].off,
                        w[CFT_LANE_SOUT].len, p.sout_pad, true, keep);
                /* The four tables on the same terms. A table is read and
                 * never written, so `false`. */
                for (int r = 0; r < 4; r++) {
                    const int role = CFT_ROLE_IA + r;
                    const cft_lane_win &tw = w[CFT_LANE_IA + r];
                    if (bind->buf[role] && itab[r] && tw.len)
                        ob[role] = buf_bind(
                            *static_cast<Buf *>(bind->buf[role]), tl, role,
                            bind->off[role] + tw.off, tw.len, p.itab_pad[r],
                            false);
                }
            }

            /* One cap covers a, b, c and d together, so the operand
             * buffers come out as large as the deposit window - the
             * price of leaving the elementwise path's allocator alone;
             * the fix when it bites is a cap per buffer. A run whose
             * operands are all resident asks for the deposit window
             * alone, and d gets a beat whatever happens, because a
             * program with max_deposits of zero is legal and XRT will
             * not submit a run with an argument unbound. */
            size_t need = 0;
            for (int r = 0; r < 3; r++)
                if (!ob[r] && p.spad[r] > need)
                    need = p.spad[r];
            if (!ob[3])
                need = std::max(need, std::max(p.dep_pad,
                                               static_cast<size_t>(32)));
            ensure_capacity(D, tile, need);
            ensure_one(D, tile, tile.pg, tile.pg_cap, ARG_PROG, img_bytes);
            ensure_one(D, tile, tile.cn, tile.cn_cap, ARG_CNT, p.cnt_pad);
            if (D.version >= BANK_VERSION)
                ensure_one(D, tile, tile.bk, tile.bk_cap, ARG_BANK,
                           bnk_bytes);
            if (D.version >= SCRATCH_VERSION) {
                if (!ob[CFT_ROLE_SI])
                    ensure_one(D, tile, tile.si, tile.si_cap,
                               ARG_SCRATCH_IN, p.sin_pad);
                if (!ob[CFT_ROLE_SO])
                    ensure_one(D, tile, tile.so, tile.so_cap,
                               ARG_SCRATCH_OUT, p.sout_pad);
            }
            if (D.version >= IDX_VERSION) {
                xrt::bo *const ib[4] = {&tile.ia, &tile.ib, &tile.ic,
                                        &tile.isi};
                size_t *const ic[4] = {&tile.ia_cap, &tile.ib_cap,
                                       &tile.ic_cap, &tile.isi_cap};
                const int iarg[4] = {ARG_IDX_A, ARG_IDX_B, ARG_IDX_C,
                                     ARG_IDX_SI};
                for (int r = 0; r < 4; r++)
                    if (!ob[CFT_ROLE_IA + r])
                        ensure_one(D, tile, *ib[r], *ic[r], iarg[r],
                                   p.itab_pad[r]);
                /* The mask's buffer, sized per run and never bound: see
                 * its staging below. */
                ensure_one(D, tile, tile.mk, tile.mk_cap, ARG_MASK,
                           p.mask_pad);
            }
            /* Argument 17 on a 0xB00 map: this slice's block where the
             * run asks for one (MODE[24]), else the one-beat stand-in the
             * tile never writes. Never a caller's buffer: the block lands
             * in the caller's memory ON THE HOST, as the counts do. */
            if (D.version >= LFLAGS_VERSION)
                ensure_one(D, tile, tile.lf, tile.lf_cap, ARG_LFLAGS,
                           p.lf_pad);

            if (!ob[0]) {
                size_t off = w[0].off;
                if (skew && i > 0 && !w[0].whole)
                    off -= esz;          /* CFT_XRT_PROGRAM_CUTS=skew */
                stage(tile.a, pa ? pa + off : nullptr, w[0].len, p.spad[0]);
            }
            if (!ob[1])
                stage(tile.b, pb ? pb + w[1].off : nullptr, w[1].len,
                      p.spad[1]);
            if (!ob[2])
                stage(tile.c, pc ? pc + w[2].off : nullptr, w[2].len,
                      p.spad[2]);
            /* R17 on a STAGED deposit window (the card day of
             * 2026-09-15). The tile does not write a masked lane's slots
             * or its count - the drains strobe them off - so what the
             * caller's buffer "keeps" is whatever the DEVICE copy held
             * when the run began, because the readback brings the device
             * copy home whole. For a resident window that is the
             * contract. For a staged one the device copy was the
             * previous run's output, so under a mask the caller's
             * deposit window, counts and scratch-out go to the device
             * first - this slice's windows of them - and the tile writes
             * the kept lanes over them. An unmasked run uploads none. */
            if (lane_mask) {
                if (!ob[3] && deposits && max_deposits)
                    stage(tile.d, pdep + w[CFT_LANE_DEP].off,
                          w[CFT_LANE_DEP].len, p.dep_pad);
                if (counts)
                    stage(tile.cn, pcnt + w[CFT_LANE_CNT].off,
                          w[CFT_LANE_CNT].len, p.cnt_pad);
                if (D.version >= SCRATCH_VERSION && !ob[CFT_ROLE_SO] &&
                    scratch_out && sout_bytes)
                    stage(tile.so, psout + w[CFT_LANE_SOUT].off,
                          w[CFT_LANE_SOUT].len, p.sout_pad);
                /* R23's block on the same terms: a masked lane's byte is
                 * the caller's (docs/SEQUENCER.md R23), and the tile
                 * strobes it off, so the caller's bytes go first and the
                 * tile writes the kept lanes' over them. Unmasked, every
                 * lane below N is written and nothing goes up. */
                if (lane_flags)
                    stage(tile.lf, plf + w[CFT_LANE_LF].off,
                          w[CFT_LANE_LF].len, p.lf_pad);
            }
            if (trace && p.cnt_pad > p.lanes * 4) {
                /* The count window's staging pad - the last beat's lanes
                 * past this tile's N, which the tile strobes off - filled
                 * with a pattern and read back after the run: a WSTRB
                 * test that owes nothing to the lane mask (card day,
                 * 2026-09-15). */
                std::memset(tile.cn.map<uint8_t *>() + p.lanes * 4, 0xCC,
                            p.cnt_pad - p.lanes * 4);
                tile.cn.sync(XCL_BO_SYNC_BO_TO_DEVICE, p.cnt_pad, 0);
            }
            if (trace && lane_flags && p.lf_pad > p.lanes) {
                /* ...and the same WSTRB test for R23's block, whose last
                 * beat is part lanes past this tile's N at every format:
                 * the pad patterned before the run, read back after it
                 * (the trace below). */
                std::memset(tile.lf.map<uint8_t *>() + p.lanes, 0xCC,
                            p.lf_pad - p.lanes);
                tile.lf.sync(XCL_BO_SYNC_BO_TO_DEVICE, p.lf_pad, 0);
            }
            {
                /* tile.si and tile.so are only created on an 0x800
                 * device, and the launch only passes them there, so an
                 * older contract never dereferences them. */
                xrt::bo *tb[CFT_ROLE_COUNT] = {&tile.a, &tile.b, &tile.c,
                                               &tile.d, &tile.si, &tile.so,
                                               &tile.ia, &tile.ib, &tile.ic,
                                               &tile.isi, &tile.mk};
                for (int r = 0; r < CFT_ROLE_COUNT; r++)
                    if (!ob[r])
                        ob[r] = tb[r];
            }
            /* The image WHOLE, whatever it holds, on every tile - what
             * executes is what was loaded - and the bank beside it: a
             * NULL bank zeroes the buffer, which is what a program that
             * carries its own constants leaves at argument 8. */
            stage(tile.pg, static_cast<const uint8_t *>(image), image_bytes,
                  img_bytes);
            if (D.version >= BANK_VERSION)
                stage(tile.bk, static_cast<const uint8_t *>(bank),
                      bank_bytes, bnk_bytes);
            /* The scratch-IN block, this slice's lanes of a dense one or
             * the whole pool of an indexed one. Pointer identity, NOT
             * `!ob[CFT_ROLE_SI]`: the tb[] fallback has run, so an
             * UNBOUND role is &tile.si rather than null, and a null test
             * would skip exactly the staging that is needed - a bug this
             * file had once. The scratch-OUT buffer is not staged: it is
             * the tile's to write, every element of it. */
            if (D.version >= SCRATCH_VERSION && ob[CFT_ROLE_SI] == &tile.si)
                stage(tile.si, psin ? psin + w[CFT_LANE_SIN].off : nullptr,
                      w[CFT_LANE_SIN].len, p.sin_pad);
            if (D.version >= IDX_VERSION) {
                /* The tables with the same pointer-identity test; a
                 * table whose MODE bit is clear gets its one beat
                 * zeroed, which the tile never reads. */
                xrt::bo *const ib[4] = {&tile.ia, &tile.ib, &tile.ic,
                                        &tile.isi};
                for (int r = 0; r < 4; r++) {
                    const cft_lane_win &tw = w[CFT_LANE_IA + r];
                    if (ob[CFT_ROLE_IA + r] == ib[r])
                        stage(*ib[r],
                              itab[r] ? reinterpret_cast<const uint8_t *>(
                                            itab[r]) + tw.off
                                      : nullptr,
                              tw.len, p.itab_pad[r]);
                }
                /* The mask, unconditionally and never from a bound
                 * buffer: this tile's bit 0 is this slice's first lane,
                 * which is a bit offset and not a byte one. */
                stage_mask(tile.mk, lane_mask, p.first, p.lanes, p.mask_pad);
            }
        };

        /* Three shapes, because the ARGUMENT COUNT is what the contract
         * version guards, and XRT throws rather than adapts. Every buffer
         * the map has is bound on every run of that contract whether or
         * not this program uses it; an 0xA00 launch passes all
         * seventeen, and an 0xB00 launch all eighteen, because XRT's
         * start sends the whole argument register image (2026-09-14). */
        t.start = [&, i](size_t tl) -> xrt::run {
            PSlice &p = ps[i];
            Tile &tile = D.tiles[tl];
            xrt::bo **const ob = p.ob;
            const uint64_t lanes = static_cast<uint64_t>(p.lanes);
            /* Set empty, the instrument is unset, as the list's other
             * instruments are but CFT_XRT_TRACE, which an empty value turns
             * on (docs/CERTIFICATES.md). Before 2026-10-05 it took address
             * 0, while a certificate records the empty variable as unset
             * (verifier-VI5). */
            if (mask_ov && *mask_ov && D.version >= IDX_VERSION) {
                /* A card-day instrument (2026-09-15): argument 16
                 * replaced by a raw address, so that a read of it faults
                 * if the tile issues one. On a 0xB00 map argument 17
                 * travels too - the run's block or the stand-in, as on
                 * every launch - so the instrument changes the one
                 * argument it names and no other. */
                const uint64_t addr = std::strtoull(mask_ov, nullptr, 16);
                xrt::run rr(tile.k);
                rr.set_arg(0, mode);
                rr.set_arg(1, lanes);
                rr.set_arg(2, *ob[0]);  rr.set_arg(3, *ob[1]);
                rr.set_arg(4, *ob[2]);  rr.set_arg(5, *ob[3]);
                rr.set_arg(6, tile.pg); rr.set_arg(7, tile.cn);
                rr.set_arg(8, tile.bk);
                rr.set_arg(9, *ob[CFT_ROLE_SI]);
                rr.set_arg(10, *ob[CFT_ROLE_SO]);
                rr.set_arg(11, static_cast<uint64_t>(0));
                rr.set_arg(12, *ob[CFT_ROLE_IA]);
                rr.set_arg(13, *ob[CFT_ROLE_IB]);
                rr.set_arg(14, *ob[CFT_ROLE_IC]);
                rr.set_arg(15, *ob[CFT_ROLE_ISI]);
                rr.set_arg(16, addr);
                if (D.version >= LFLAGS_VERSION)
                    rr.set_arg(ARG_LFLAGS, tile.lf);
                std::fprintf(stderr, "[xrt trace] tile %zu: argument 16 "
                             "overridden with 0x%016llx\n", tl,
                             static_cast<unsigned long long>(addr));
                rr.start();
                return rr;
            }
            if (D.version >= LFLAGS_VERSION)
                return tile.k(mode, lanes, *ob[0], *ob[1], *ob[2], *ob[3],
                              tile.pg, tile.cn, tile.bk, *ob[CFT_ROLE_SI],
                              *ob[CFT_ROLE_SO], static_cast<uint64_t>(0),
                              *ob[CFT_ROLE_IA], *ob[CFT_ROLE_IB],
                              *ob[CFT_ROLE_IC], *ob[CFT_ROLE_ISI], tile.mk,
                              tile.lf);
            if (D.version >= IDX_VERSION)
                return tile.k(mode, lanes, *ob[0], *ob[1], *ob[2], *ob[3],
                              tile.pg, tile.cn, tile.bk, *ob[CFT_ROLE_SI],
                              *ob[CFT_ROLE_SO], static_cast<uint64_t>(0),
                              *ob[CFT_ROLE_IA], *ob[CFT_ROLE_IB],
                              *ob[CFT_ROLE_IC], *ob[CFT_ROLE_ISI], tile.mk);
            if (D.version >= SCRATCH_VERSION)
                return tile.k(mode, lanes, *ob[0], *ob[1], *ob[2], *ob[3],
                              tile.pg, tile.cn, tile.bk, *ob[CFT_ROLE_SI],
                              *ob[CFT_ROLE_SO]);
            if (D.version >= BANK_VERSION)
                return tile.k(mode, lanes, *ob[0], *ob[1], *ob[2], *ob[3],
                              tile.pg, tile.cn, tile.bk);
            return tile.k(mode, lanes, *ob[0], *ob[1], *ob[2], *ob[3],
                          tile.pg, tile.cn);
        };

        /* CFT_XRT_TRACE: what each tile received against what the host
         * sent, read back through the same register path CAPS uses. A
         * card-day instrument (2026-09-15: the tile wrote every masked
         * lane while every host-side value looked right on paper). Run
         * for every task before the fault test, which is when it helps. */
        if (trace)
            t.after = [&, i](size_t tl) {
                PSlice &p = ps[i];
                Tile &tile = D.tiles[tl];
                try {
                    const uint32_t r_mode = tile.k.read_register(0x10);
                    const uint32_t r_n_lo = tile.k.read_register(0x18);
                    const uint32_t r_n_hi = tile.k.read_register(0x1C);
                    std::fprintf(stderr, "[xrt trace] tile %zu lanes [%zu, "
                                 "%zu): host mode=0x%08x n=%zu | tile "
                                 "MODE=0x%08x N=0x%08x%08x STATUS=0x%08x "
                                 "FLAGS=0x%08x\n", tl, p.first,
                                 p.first + p.lanes, mode, p.lanes, r_mode,
                                 r_n_hi, r_n_lo,
                                 tile.k.read_register(CSR_STATUS),
                                 tile.k.read_register(CSR_FLAGS));
                    static const char *const pname[5] = {"IDX_A", "IDX_B",
                                                         "IDX_C", "IDX_SI",
                                                         "MASK"};
                    for (int k = 0; k < 5; k++) {
                        const uint32_t lo =
                            tile.k.read_register(0x88u + 8u * k);
                        const uint32_t hi =
                            tile.k.read_register(0x8Cu + 8u * k);
                        std::fprintf(stderr, "[xrt trace]   %-6s = "
                                     "0x%08x%08x\n", pname[k], hi, lo);
                    }
                    if (D.version >= LFLAGS_VERSION) {
                        /* Argument 17 as the tile holds it, beside the
                         * address the host bound (0xB00): the run's block
                         * under MODE[24], else the stand-in. */
                        const uint32_t lo = tile.k.read_register(0xB0u);
                        const uint32_t hi = tile.k.read_register(0xB4u);
                        std::fprintf(stderr, "[xrt trace]   %-6s = "
                                     "0x%08x%08x (bound 0x%016llx, %s)\n",
                                     "LFLAGS", hi, lo,
                                     static_cast<unsigned long long>(
                                         tile.lf.address()),
                                     lane_flags ? "the run's block, MODE[24]"
                                                : "the stand-in");
                    }
                    if (D.version >= IDX_VERSION) {
                        std::fprintf(stderr, "[xrt trace]   mask bo address "
                                     "0x%016llx, %zu bytes staged (real "
                                     "%zu); device bytes:",
                                     static_cast<unsigned long long>(
                                         tile.mk.address()),
                                     p.mask_pad, cft_mask_bytes(p.lanes));
                        tile.mk.sync(XCL_BO_SYNC_BO_FROM_DEVICE, p.mask_pad,
                                     0);
                        auto *mp = tile.mk.map<const uint8_t *>();
                        for (size_t k = 0; k < p.mask_pad && k < 32; k++)
                            std::fprintf(stderr, " %02x", mp[k]);
                        std::fprintf(stderr, "\n");
                    }
                    if (p.cnt_pad > p.lanes * 4) {
                        tile.cn.sync(XCL_BO_SYNC_BO_FROM_DEVICE, p.cnt_pad,
                                     0);
                        const uint8_t *cp = tile.cn.map<const uint8_t *>();
                        std::fprintf(stderr, "[xrt trace] tile %zu count pad "
                                     "bytes [%zu, %zu) after the run:", tl,
                                     p.lanes * 4, p.cnt_pad);
                        for (size_t k = p.lanes * 4; k < p.cnt_pad; k++)
                            std::fprintf(stderr, " %02x", cp[k]);
                        std::fprintf(stderr, "\n[xrt trace]   (cc = "
                                     "untouched, the strobes held; anything "
                                     "else the tile wrote through a strobe "
                                     "that was off)\n");
                    }
                    if (lane_flags && p.lf_pad > p.lanes) {
                        tile.lf.sync(XCL_BO_SYNC_BO_FROM_DEVICE, p.lf_pad,
                                     0);
                        const uint8_t *lp = tile.lf.map<const uint8_t *>();
                        std::fprintf(stderr, "[xrt trace] tile %zu lane-flags "
                                     "pad bytes [%zu, %zu) after the run:",
                                     tl, p.lanes, p.lf_pad);
                        for (size_t k = p.lanes; k < p.lf_pad; k++)
                            std::fprintf(stderr, " %02x", lp[k]);
                        std::fprintf(stderr, "\n[xrt trace]   (cc = "
                                     "untouched, the strobes held)\n");
                    }
                } catch (const std::exception &e) {
                    std::fprintf(stderr, "[xrt trace] tile %zu register read "
                                 "failed: %s\n", tl, e.what());
                }
            };

        t.collect = [&, i](size_t tl) {
            PSlice &p = ps[i];
            Tile &tile = D.tiles[tl];
            const cft_lane_win *const w = p.w;
            /* A RESIDENT deposit window does not come back: the tile
             * wrote it, that copy is the authority now, and the caller
             * collects it with cft_buffer_from_device. Every slot is
             * still written - the untouched ones as +0, which
             * SEQUENCER.md makes normative. A deposit window of zero
             * bytes (max_deposits of zero is a legal program) is skipped
             * rather than transferred for nothing. */
            if (p.ob[3] != &tile.d) {
                buf_mark_written(*static_cast<Buf *>(bind->buf[CFT_ROLE_D]),
                                 tl, CFT_ROLE_D);
            } else {
                if (p.dep_pad)
                    tile.d.sync(XCL_BO_SYNC_BO_FROM_DEVICE, p.dep_pad, 0);
                if (deposits && max_deposits)
                    std::memcpy(pdep + w[CFT_LANE_DEP].off,
                                tile.d.map<uint8_t *>(), w[CFT_LANE_DEP].len);
                /* a resident window whose bind was declined: its mirror
                 * was just written on the host */
                if (bind && bind->buf[CFT_ROLE_D] && deposits &&
                    max_deposits) {
                    const size_t lo =
                        bind->off[CFT_ROLE_D] + w[CFT_LANE_DEP].off;
                    buf_host_wrote(
                        *static_cast<Buf *>(bind->buf[CFT_ROLE_D]), lo,
                        lo + w[CFT_LANE_DEP].len);
                }
            }
            tile.cn.sync(XCL_BO_SYNC_BO_FROM_DEVICE, p.cnt_pad, 0);
            if (counts)
                std::memcpy(pcnt + w[CFT_LANE_CNT].off,
                            tile.cn.map<uint8_t *>(), w[CFT_LANE_CNT].len);
            /* R23's block, on the counts' terms: this tile wrote its
             * lanes' bytes from its own lane 0, and they go to the
             * slice's first lane in the caller's buffer - lane_cut.h's
             * window, which api-test holds over every cut. Nothing is
             * merged: each byte is the one tile's that ran its lane (P2),
             * and FLAGS and STATUS stay the OR over tiles. */
            if (lane_flags) {
                tile.lf.sync(XCL_BO_SYNC_BO_FROM_DEVICE, p.lf_pad, 0);
                std::memcpy(plf + w[CFT_LANE_LF].off,
                            tile.lf.map<uint8_t *>(), w[CFT_LANE_LF].len);
            }
            /* The scratch-out block, on the deposit window's terms:
             * skipped when the program declares none, and a RESIDENT one
             * does not come back - an integrator's state can stay on the
             * device across a whole corrector pass. */
            if (sout_bytes) {
                if (p.ob[CFT_ROLE_SO] != &tile.so) {
                    buf_mark_written(
                        *static_cast<Buf *>(bind->buf[CFT_ROLE_SO]), tl,
                        CFT_ROLE_SO);
                } else {
                    tile.so.sync(XCL_BO_SYNC_BO_FROM_DEVICE, p.sout_pad, 0);
                    std::memcpy(psout + w[CFT_LANE_SOUT].off,
                                tile.so.map<uint8_t *>(),
                                w[CFT_LANE_SOUT].len);
                    if (bind && bind->buf[CFT_ROLE_SO]) {
                        const size_t lo =
                            bind->off[CFT_ROLE_SO] + w[CFT_LANE_SOUT].off;
                        buf_host_wrote(
                            *static_cast<Buf *>(bind->buf[CFT_ROLE_SO]), lo,
                            lo + w[CFT_LANE_SOUT].len);
                    }
                }
            }
        };
        J.tasks.push_back(std::move(t));
    }

    uint32_t status_acc = 0, flag_acc = 0, fail = 0;
    bool faulted = false;
    const int st = run_job(D, J, &status_acc, &flag_acc, &faulted, &fail);
    if (st != ST_OK) {
        /* After a start, *bus carries the report bits of the best-effort
         * STATUS read, as this path always has. */
        if (D.poisoned && bus)
            *bus = fail & ST_REPORTS;
        return st;
    }

    /* Faults before results, as everywhere in this file. Three outcomes
     * rather than the elementwise path's two, because a sequencer adds a
     * bit that is a REPORT and not a failure. */
    if (faulted && !(status_acc & ST_BUS_BITS)) {
        /* Two things reach the refusal bit: a precision the bitstream
         * does not carry, and a program image the tile threw back. The
         * library checked CAPS before loading the program, and
         * cft_program_load validated the image, so either one means the
         * device and this code disagree about something both thought was
         * settled. The run did not happen. */
        /* A run that asked for R23's block set MODE[24], which a tile
         * without CAPS2[13] refuses at start the same way: device.c held
         * the run to the bit first, so a tile that publishes the bit and
         * refuses the MODE disagrees with its own CAPS2, and the sentence
         * names that possibility rather than leaving it to be guessed. */
        set_err("kernel REFUSED the program (STATUS 0x" + hex32(status_acc) +
                "): either MODE selected a precision this bitstream does "
                "not implement, or the tile rejected the program image - "
                "too many instructions, constants or deposit slots for its "
                "on-chip memories, or a header it did not recognise" +
                std::string(lane_flags
                                ? ", or it refused MODE[24], the per-lane "
                                  "flags block this run asked for, which "
                                  "its CAPS2[13] publishes"
                                : "") +
                ". Nothing was computed and nothing was written." +
                at_where(J));
        return ST_UNSUPPORTED;
    }
    if (faulted) {
        if (bus)
            *bus = status_acc;
        set_err("kernel reported bus faults during a program; the deposits "
                "are not valid" + at_where(J));
        return ST_BUS_FAULT;
    }

    if (flags)
        *flags = flag_acc;
    /* The deposit overflow travels in *bus on a SUCCESSFUL run, which is
     * the one place this library puts something there without returning
     * CFT_ERR_BUS_FAULT. It is not a fault: the deposits that fit are
     * correct and reproducible, and what the caller lost is the tail.
     * ORed over the tiles, as the overflow is a lane's. */
    if (bus)
        *bus = status_acc & ST_REPORTS;
    return ST_OK;
}

extern "C" int cftx_program_run(void *hw, int fmt, const void *image,
                                size_t image_bytes,
                                const cft_seq_run_io *io,
                                uint32_t max_deposits,
                                const void *a, const void *b, const void *c,
                                void *deposits, uint32_t *counts, size_t n,
                                const cft_bindings *bind,
                                uint32_t *flags, uint32_t *bus)
{
    return at_boundary("a program", [&] {
        return cftx_program_run_impl(hw, fmt, image, image_bytes, io,
                                     max_deposits, a, b, c, deposits,
                                     counts, n, bind, flags, bus);
    });
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
static int cftx_reduce_impl(void *hw, int op, int fmt, int rnd,
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

    const uint32_t mode = static_cast<uint32_t>(op & 0xFF) |
                          (static_cast<uint32_t>(fmt & 0xF) << 8) |
                          (static_cast<uint32_t>(rnd & 0x7) << 12);

    const auto *pa = static_cast<const uint8_t *>(a);
    auto *pp = static_cast<uint8_t *>(partials);

    /* One task per range, and the scheduler's waves of at most one task
     * a tile do what this path once did by hand - the RTL silently
     * drops a start issued to a busy compute unit, which would return
     * the previous range's answer.
     *
     * THERE ARE ROUTINELY MORE RANGES THAN TILES. It is not an edge case
     * and it is not only about huge n: the tree's canonical cut of
     * [0, n) into at most `parts` NODES needs one extra range whenever n
     * is a power of two plus a remainder, so four tiles get five ranges
     * at n = 5, 9, 17, 33, 65, ... and eight tiles get more than eight
     * for 49 of the first thousand n.
     *
     * Which is why staging happens per WAVE, just before it starts, and
     * not once up front for every range. Staging all of them first wrote
     * range k into tile k % ntiles, so with five ranges and four tiles
     * range 4 overwrote range 0's operands before range 0 had ever been
     * launched - and wave 0 then reduced the wrong data with the right
     * length, giving a wrong sum with clean STATUS and plausible flags.
     * Nothing reported an error. The scheduler stages each wave on its
     * own for exactly that reason.
     *
     * The cost is that a staging failure in a later wave happens after
     * earlier waves have already run. That is harmless: a reduction
     * leaves nothing behind on the device but the tiles' own buffers,
     * and the host discards every partial on any error.
     *
     * Which object carries a range's `a`: the resident buffer's own
     * copy of that range on the task's tile, or the tile's staging
     * buffer. b, c and d are the tile's either way - b and c are
     * buffers nothing reads, and one element of d is the answer - so `a`
     * is the only operand a reduction can save, which is also the only
     * one that carries the whole vector. */
    std::vector<xrt::bo *> wa(nranges, nullptr);
    Job J;
    J.what = "a reduction";
    J.oom_words = "each tile's HBM group is finite; try a smaller n or "
                  "cft_alloc";
    J.faulty = [](uint32_t s) { return s != 0; };
    for (size_t k = 0; k < nranges; k++) {
        Task t;
        t.stage = [&, k](size_t tl) {
            const size_t m = hi[k] - lo[k];
            const size_t padded = ((m + epb - 1) / epb) * epb;
            Tile &tile = D.tiles[tl];
            wa[k] = nullptr;
            if (bind && bind->buf[CFT_ROLE_A])
                wa[k] = buf_bind(*static_cast<Buf *>(bind->buf[CFT_ROLE_A]),
                                 tl, CFT_ROLE_A,
                                 bind->off[CFT_ROLE_A] + lo[k] * esz,
                                 m * esz, padded * esz, false);
            ensure_capacity(D, tile, padded * esz);
            if (!wa[k]) {
                stage(tile.a, pa + lo[k] * esz, m * esz, padded * esz);
                wa[k] = &tile.a;
            }
            /* b and c are unread by a sum, but the engine streams all
             * three - one read enable feeds all three FIFOs - so they
             * must be real, readable memory of the same length.
             * ensure_capacity above made them that; their CONTENTS are
             * nothing's business (reduce_unread). */
            reduce_unread(tile.b, tile.c, m * esz, padded * esz);
            /* every buffer the twelve-argument launch binds must exist,
             * one beat at least; the program path creates them on first
             * use and a device that only ever reduces would never have */
            if (D.version >= SEG_VERSION) {
                ensure_one(D, tile, tile.pg, tile.pg_cap, ARG_PROG, 32);
                ensure_one(D, tile, tile.cn, tile.cn_cap, ARG_CNT, 32);
                ensure_one(D, tile, tile.bk, tile.bk_cap, ARG_BANK, 32);
                ensure_one(D, tile, tile.si, tile.si_cap, ARG_SCRATCH_IN, 32);
                ensure_one(D, tile, tile.so, tile.so_cap, ARG_SCRATCH_OUT,
                           32);
            }
        };
        t.start = [&, k](size_t tl) -> xrt::run {
            const uint64_t m = static_cast<uint64_t>(hi[k] - lo[k]);
            Tile &tile = D.tiles[tl];
            /* the whole range, one result: SEG 0, as the twelfth
             * argument on a map that has it (see SEG_VERSION) */
            if (D.version >= SEG_VERSION)
                return tile.k(mode, m, *wa[k], tile.b, tile.c, tile.d,
                              tile.pg, tile.cn, tile.bk, tile.si, tile.so,
                              static_cast<uint64_t>(0));
            return tile.k(mode, m, *wa[k], tile.b, tile.c, tile.d);
        };
        /* One beat comes back; one element of it is the answer, and the
         * engine zeroed the rest. */
        t.collect = [&, k](size_t tl) {
            Tile &tile = D.tiles[tl];
            tile.d.sync(XCL_BO_SYNC_BO_FROM_DEVICE, 32, 0);
            std::memcpy(pp + k * esz, tile.d.map<uint8_t *>(), esz);
        };
        J.tasks.push_back(std::move(t));
    }

    uint32_t bs = 0, fl = 0, fail = 0;
    bool faulted = false;
    /* The run's own failure is reported BEFORE the status word, which is
     * the opposite order to the success path and deliberate: a STATUS
     * read taken from a unit that may still be running must not turn a
     * ST_TIMEOUT into a ST_BUS_FAULT. The scheduler's message names the
     * word, which is the part that helps. */
    const int st = run_job(D, J, &bs, &fl, &faulted, &fail);
    if (st != ST_OK)
        return st;
    if (faulted) {
        /* Same split as the elementwise path: STATUS[3] alone is the
         * precision refusal - no run, no data - and a device refusing
         * what its CAPS advertised is its own report, not a bus story. */
        if ((bs & 0x8u) && !(bs & 0x7u)) {
            /* *bus stays scoped to CFT_ERR_BUS_FAULT, as backend.h and
             * cft.h promise */
            set_err("kernel REFUSED the reduction: MODE selected a "
                    "precision this bitstream does not implement "
                    "(STATUS 0x" + hex32(bs) + ")" + at_where(J));
            return ST_UNSUPPORTED;
        }
        if (bus) *bus = bs;
        set_err("the memory system reported a fault during a reduction; "
                "the result is not to be trusted" + at_where(J));
        return ST_BUS_FAULT;
    }
    if (flags) *flags = fl;
    return ST_OK;
}

extern "C" int cftx_reduce(void *hw, int op, int fmt, int rnd,
                           const void *a,
                           const size_t *lo, const size_t *hi,
                           size_t nranges, void *partials,
                           const cft_bindings *bind,
                           uint32_t *flags, uint32_t *bus)
{
    return at_boundary("a reduction", [&] {
        return cftx_reduce_impl(hw, op, fmt, rnd, a, lo, hi, nranges,
                                partials, bind, flags, bus);
    });
}

/* ---- cftx_reduce_seg: segments across tiles (ABI 0.13) --------------
 *
 * d[s] over slice s, n / seg results. Tile t takes segments [s0, s1),
 * a contiguous run of elements, one launch with SEG = seg and NRES =
 * s1 - s0, and its results are final - there is nothing to combine, so
 * the partition is by whole segments, as even as the tile count allows,
 * one wave. op is 24 (sum) or 31 (maxall), the two the tile streams;
 * the caller took the composed opcodes apart. */
static int cftx_reduce_seg_impl(void *hw, int op, int fmt, int rnd,
                                const void *a, size_t n, size_t seg,
                                void *d, const cft_bindings *bind,
                                uint32_t *flags, uint32_t *bus)
{
    if (!hw || !a || !d || seg == 0 || n == 0 || (n % seg) != 0)
        return ST_INVALID_ARGUMENT;

    Dev &D = *static_cast<Dev *>(hw);
    if (D.poisoned) {
        set_err("device handle is poisoned by an earlier failure");
        return ST_INTERNAL;
    }
    /* the caller refused a device without CFT_FEAT_REDUCE_SEG; the map
     * is checked again here because the register write below would
     * otherwise land in a decode default */
    if (D.version < SEG_VERSION) {
        set_err("this bitstream's map (before 0x900) has no SEG register: "
                "cft_reduce_seg cannot run on it");
        return ST_UNSUPPORTED;
    }
    const size_t esz = static_cast<size_t>(elem_bytes(fmt));
    if (esz == 0)
        return ST_INVALID_ARGUMENT;
    const size_t epb = 32u / esz;
    const size_t nres = n / seg;
    const size_t ntiles = D.tiles.size();
    const size_t use = std::min(ntiles, nres);
    const uint32_t mode = static_cast<uint32_t>(op & 0xFF) |
                          (static_cast<uint32_t>(fmt & 0xF) << 8) |
                          (static_cast<uint32_t>(rnd & 0x7) << 12);
    const auto *pa = static_cast<const uint8_t *>(a);
    auto *pd = static_cast<uint8_t *>(d);

    /* segments s0..s1 per task: nres / use each, the remainder to the
     * first ones, so the slices are contiguous and every task has work.
     * One wave: there are no more tasks than tiles. */
    std::vector<size_t> s0(use + 1, 0);
    for (size_t j = 0; j < use; j++)
        s0[j + 1] = s0[j] + nres / use + (j < nres % use ? 1u : 0u);

    std::vector<xrt::bo *> wa(use, nullptr);
    Job J;
    J.what = "a segmented reduction";
    J.oom_words = "each tile's HBM group is finite; try a smaller n or "
                  "cft_alloc";
    J.faulty = [](uint32_t s) { return s != 0; };
    for (size_t j = 0; j < use; j++) {
        Task t;
        t.stage = [&, j](size_t tl) {
            const size_t lo = s0[j] * seg, m = (s0[j + 1] - s0[j]) * seg;
            const size_t padded = ((m + epb - 1) / epb) * epb;
            const size_t rpad = (((s0[j + 1] - s0[j]) + epb - 1) / epb) * epb;
            Tile &tile = D.tiles[tl];
            wa[j] = nullptr;
            if (bind && bind->buf[CFT_ROLE_A])
                wa[j] = buf_bind(*static_cast<Buf *>(bind->buf[CFT_ROLE_A]),
                                 tl, CFT_ROLE_A,
                                 bind->off[CFT_ROLE_A] + lo * esz,
                                 m * esz, padded * esz, false);
            ensure_capacity(D, tile, std::max(padded, rpad) * esz);
            if (!wa[j]) {
                stage(tile.a, pa + lo * esz, m * esz, padded * esz);
                wa[j] = &tile.a;
            }
            reduce_unread(tile.b, tile.c, m * esz, padded * esz);
            /* every buffer the twelve-argument launch binds must exist,
             * one beat at least; the program path creates them on first
             * use and a device that only ever reduces would never have */
            ensure_one(D, tile, tile.pg, tile.pg_cap, ARG_PROG, 32);
            ensure_one(D, tile, tile.cn, tile.cn_cap, ARG_CNT, 32);
            ensure_one(D, tile, tile.bk, tile.bk_cap, ARG_BANK, 32);
            ensure_one(D, tile, tile.si, tile.si_cap, ARG_SCRATCH_IN, 32);
            ensure_one(D, tile, tile.so, tile.so_cap, ARG_SCRATCH_OUT, 32);
        };
        t.start = [&, j](size_t tl) -> xrt::run {
            const size_t m = (s0[j + 1] - s0[j]) * seg;
            Tile &tile = D.tiles[tl];
            const uint64_t seg_word =
                (static_cast<uint64_t>(s0[j + 1] - s0[j]) << 32) |
                static_cast<uint64_t>(seg);
            return tile.k(mode, static_cast<uint64_t>(m), *wa[j], tile.b,
                          tile.c, tile.d, tile.pg, tile.cn, tile.bk, tile.si,
                          tile.so, seg_word);
        };
        t.collect = [&, j](size_t tl) {
            const size_t r0 = s0[j], rn = s0[j + 1] - s0[j];
            Tile &tile = D.tiles[tl];
            const size_t rbytes = ((rn * esz + 31u) / 32u) * 32u;
            tile.d.sync(XCL_BO_SYNC_BO_FROM_DEVICE, rbytes, 0);
            std::memcpy(pd + r0 * esz, tile.d.map<uint8_t *>(), rn * esz);
        };
        J.tasks.push_back(std::move(t));
    }

    uint32_t bs = 0, fl = 0, fail = 0;
    bool faulted = false;
    const int st = run_job(D, J, &bs, &fl, &faulted, &fail);
    if (st != ST_OK)
        return st;
    if (faulted) {
        if ((bs & 0x8u) && !(bs & 0x7u)) {
            set_err("kernel REFUSED the reduction: MODE selected a "
                    "precision this bitstream does not implement "
                    "(STATUS 0x" + hex32(bs) + ")" + at_where(J));
            return ST_UNSUPPORTED;
        }
        if (bus) *bus = bs;
        set_err("the memory system reported a fault during a segmented "
                "reduction; the results are not to be trusted" +
                at_where(J));
        return ST_BUS_FAULT;
    }
    if (flags) *flags = fl;
    return ST_OK;
}

extern "C" int cftx_reduce_seg(void *hw, int op, int fmt, int rnd,
                               const void *a, size_t n, size_t seg,
                               void *d, const cft_bindings *bind,
                               uint32_t *flags, uint32_t *bus)
{
    return at_boundary("a segmented reduction", [&] {
        return cftx_reduce_seg_impl(hw, op, fmt, rnd, a, n, seg, d, bind,
                                    flags, bus);
    });
}
