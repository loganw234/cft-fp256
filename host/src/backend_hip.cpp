/* Copyright 2026 Logan W.
 * SPDX-License-Identifier: Apache-2.0
 *
 * The GPU backend: a HIP device as a libcft device, opened as "hip:N"
 * (the GPU backend's round 1; docs/HOSTAPI.md, "The GPU backend").
 *
 * It implements backend.h's device seam under the prefix cfth_, which
 * backend.h's HIP block maps the cftx_ names to - so device.c's device
 * branches (the registry, the compositions, the segmented reduction)
 * drive a GPU as they drive a card. host/Makefile builds it with HIP=1,
 * on ROCm or on HIP's NVIDIA layer, and never beside the XRT backend.
 *
 * ---------------------------------------------------------------
 * One translation unit, and whose code runs
 * ---------------------------------------------------------------
 *
 * This file is also the device code's only unit (no relocatable device
 * code): it includes the tree's own bigint.c, softfloat.c and seq_exec.h
 * below, which carry CFT_HD (cft_config.h), so every kernel here runs
 * this library's arithmetic and its sequencer's executor as they are -
 * cft_sf_compute for an element, cft_sf_compute's ADD and MAX for a node
 * of the reduction tree, seq_exec.h's four per-lane functions and
 * seq_run_block for a program lane. Nothing of a run is re-expressed.
 * The pattern is host/tools/hip_unit.py's unit, which compiles the same
 * three files the same way as a check (make HIP=1 hip-unit).
 *
 * Including them makes C++ DEFINITIONS of their functions in this unit,
 * beside the C ones libcft.a's bigint.o and softfloat.o hold. The
 * functions do not collide - their headers have no extern "C", so these
 * are C++ (mangled) names. A datum is not mangled, and softfloat.c
 * defines one: the format table. This unit's copy is renamed below, and
 * host/Makefile's hip-symcheck holds the objects to it - no symbol is
 * defined both here and in a host object - with a plant
 * (CFT_HIP_PLANT_COLLIDE) that removes the rename and must turn it red.
 *
 * The descriptor of a format reaches a kernel BY VALUE, never through
 * the table: NVIDIA's compiler refuses a host global in device code
 * (docs/VALIDATION.md, G1A's augmented.c finding).
 *
 * CFT_BN_LIMBS is the host's (bigint.h's 64 by default) and must be:
 * the host decodes a program's constants into cft_bn arrays (program.c,
 * at load, or here, from a bank) and the device reads that memory with
 * this unit's layout. The static_assert below holds the two to one
 * definition of cft_bn.
 *
 * ---------------------------------------------------------------
 * What it publishes, and what it refuses
 * ---------------------------------------------------------------
 *
 * Every format and opcode group the software backend carries (the same
 * code runs), tiles 1, flags readable, and the software executor's four
 * capacities with its features less two, which round 1 does not carry
 * and refuses by name through the loader and device.c: index tables
 * (CFT_SEQ_FEAT_INDEXED) and augmentedAddition (CFT_SEQ_FEAT_AUGADD -
 * augmented.c does not compile for an NVIDIA device as it is, so this
 * unit is CFT_NO_AUGMENTED). A program's scratch is the software
 * handle's 256 slots; cft_open_ex refuses another depth for any device
 * by name (device.c). No device image: cft_get_image_id is refused by
 * name. Resident buffers: none yet (CFT_HIP_BUFFERS_RESIDENT 0,
 * backend.h): cfth_buffer_create declines and device.c keeps the
 * buffer as host memory, so every operand is staged.
 *
 * ---------------------------------------------------------------
 * Staging, chunks, and the time a launch may take
 * ---------------------------------------------------------------
 *
 * Each handle owns one pinned host block and one device block of the
 * same size, its STAGE (min(free / 8, 64 MiB) at open), a scratch pool
 * for programs (up to min(free / 8, 256 MiB), made at the first program
 * that needs one) and a stream. A call copies its operands into the
 * stage, uploads them with one copy, launches, and copies the results
 * back with one more; a run longer than the stage holds is cut into
 * chunks. An element and a lane depend on their own index alone, so a
 * cut cannot reach an answer, and the reduction is cut only at nodes of
 * its own tree (below). A program's chunk is adaptive: it doubles after
 * a launch under 62 ms and halves after one over 250 ms, so that no
 * launch runs for seconds on a GPU whose driver resets one that does.
 *
 * ---------------------------------------------------------------
 * Failure
 * ---------------------------------------------------------------
 *
 * Every entry runs inside a noexcept boundary that turns a C++
 * exception into a status and a sentence. An allocation the device
 * refuses before anything ran is CFT_ERR_OUT_OF_MEMORY, named, and the
 * handle stays usable. Any other HIP failure once a launch may have
 * started POISONS the handle: a sticky device error leaves the context
 * unusable, and whether a kernel wrote part of an output is not known,
 * so every later call is CFT_ERR_INTERNAL with "close it and open it
 * again" - the discipline cft.h gives the XRT and remote backends.
 *
 * ---------------------------------------------------------------
 * Plants (HIP_PLANTS=1 only)
 * ---------------------------------------------------------------
 *
 * Compiled in only under -DCFT_HIP_PLANTS, chosen at open by
 * CFT_HIP_PLANT=<name>; an unknown or malformed value is refused by
 * name at open. A default build has no plant code and never reads the
 * variable. Each breaks one thing a check must see:
 *
 *   flip           bit 0 of the first element of every elementwise run
 *   rmm-as-rne     attribute 4 (rmm) computed as 0 (rne) in a run
 *   drop-flag      underflow dropped from a run's flag word
 *   reduce-carry   at an odd level, the FIRST element carried and the
 *                  rest paired from the right - another tree
 *   reduce-flags   the reduction's adds' flags dropped
 *   seq-mask       a program's lane mask ignored
 *   seq-deposit    a program's deposit slots not zero-filled (over a
 *                  device window the plant fills with 0xA5)
 *   fail-launch    the handle's first launch reported failed after it
 *                  ran: the call fails and the handle is poisoned
 *
 * CFT_HIP_CHUNK=<n> (a multiple of 8, 8 to 2^30) fixes the chunk: n
 * elements a run, the largest power of two not above n a reduction's
 * chunk, n lanes a program's, so small data crosses every boundary.
 */

/* ---- the unit: the tree's own sources, for the host and the device ---- */
#include <hip/hip_runtime.h>   /* first: blockIdx, and AMD's device memset
                                * seq_exec.h calls (G1A's known limit 2) */
#define CFT_NO_AUGMENTED 1
#define BLOCK_LANES 1          /* a thread is a block of one lane */
#ifndef CFT_HIP_PLANT_COLLIDE
/* softfloat.c's one datum, renamed in this unit - see the head */
#define cft_sf_formats cft_hip_sf_formats
#endif
#include "bigint.c"
#include "softfloat.c"
#include "seq_exec.h"
#include "backend.h"

#include <chrono>
#include <cinttypes>
#include <climits>
#include <cstdarg>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <exception>
#include <new>
#include <string>
#include <vector>

#ifndef CFT_ENABLE_HIP
#error "backend_hip.cpp is the GPU backend: build it with host/Makefile's HIP=1, which defines CFT_ENABLE_HIP (and CFT_ENABLE_XRT, whose seam it implements)"
#endif
/* The architectures this build's device code is for, as host/Makefile
 * passes them (HIP_ARCH, joined by "_"), for the sentences that say why
 * a device cannot run it and for CFT_HIP_INFO's line. Tokens, not a
 * string, so that no shell between make and the compiler can unquote it. */
#define CFT_HIP_STR2(x) #x
#define CFT_HIP_STR(x) CFT_HIP_STR2(x)
#ifdef CFT_HIP_ARCH_TOKENS
#define CFT_HIP_ARCH CFT_HIP_STR(CFT_HIP_ARCH_TOKENS)
#else
#define CFT_HIP_ARCH "unstated"
#endif

/* The host decodes into cft_bn and the device reads it: one layout. */
static_assert(sizeof(cft_bn) == sizeof(int) + CFT_BN_LIMBS * sizeof(uint32_t),
              "cft_bn is not the host's int and CFT_BN_LIMBS limbs");

#ifdef CFT_HIP_PLANTS
#define PLANT_PARAM , unsigned plant
#define PLANT_ARG(D) , (D).plant
#else
#define PLANT_PARAM
#define PLANT_ARG(D)
#endif

namespace {

/* ==== the kernels ======================================================= */

/* One launch's answer, in device memory: the OR of every lane's flags
 * (a block ORs its lanes into shared memory first, then one thread ORs
 * the block's word in here), the OR of a program's STATUS reports, and
 * the lowest failing index with its status, (index << 8) | status, by
 * atomicMin - all ~0 when nothing failed. OR and minimum are
 * associative and commutative, so the order lanes finish in cannot
 * reach any of the three. */
struct hacc {
    unsigned int flags;
    unsigned int status;
    unsigned long long fail;
};

#ifdef CFT_HIP_PLANTS
enum : unsigned {
    PL_FLIP = 1u << 0, PL_RMM_AS_RNE = 1u << 1, PL_DROP_FLAG = 1u << 2,
    PL_REDUCE_CARRY = 1u << 3, PL_REDUCE_FLAGS = 1u << 4,
    PL_SEQ_MASK = 1u << 5, PL_SEQ_DEPOSIT = 1u << 6, PL_FAIL_LAUNCH = 1u << 7
};
#endif

/* The elementwise run: element i of a chunk through cft_sf_compute, as
 * device.c's software loop runs one (operands loaded before the result
 * is stored; a NULL operand is a zero element; a scalar one is element
 * 0 for every i). `first` is the chunk's first element in the run. */
__global__ __launch_bounds__(256) void k_run(cft_fmt_desc f, int op, int rnd,
                                             const uint8_t *a, const uint8_t *b,
                                             const uint8_t *c, uint8_t *d,
                                             size_t n, unsigned scal, size_t first,
                                             hacc *acc PLANT_PARAM)
{
    __shared__ unsigned int blk;
    const size_t i = (size_t)blockIdx.x * blockDim.x + threadIdx.x;
    const size_t esz = (size_t)f.width / 8;
    if (threadIdx.x == 0)
        blk = 0;
    __syncthreads();
    if (i < n) {
        cft_bn ba, bb, bc, bo;
        uint32_t fl = 0;
        int r = rnd;
        cft_bn_zero(&ba);
        cft_bn_zero(&bb);
        cft_bn_zero(&bc);
        if (a) cft_bn_load(&ba, a + ((scal & 1u) ? 0 : i) * esz, (int)esz);
        if (b) cft_bn_load(&bb, b + ((scal & 2u) ? 0 : i) * esz, (int)esz);
        if (c) cft_bn_load(&bc, c + ((scal & 4u) ? 0 : i) * esz, (int)esz);
#ifdef CFT_HIP_PLANTS
        if ((plant & PL_RMM_AS_RNE) && r == CFT_SF_RMM)
            r = CFT_SF_RNE;
#endif
        if (cft_sf_compute(&f, op, r, &ba, &bb, &bc, &bo, &fl)) {
            atomicMin(&acc->fail, ((unsigned long long)(first + i) << 8) |
                                      (unsigned long long)CFT_ERR_INTERNAL);
        } else {
            cft_bn_store(&bo, d + i * esz, (int)esz);
#ifdef CFT_HIP_PLANTS
            if ((plant & PL_FLIP) && first + i == 0)
                d[0] ^= 1u;
#endif
            if (fl)
                atomicOr(&blk, (unsigned int)fl);
        }
    }
    __syncthreads();
    if (threadIdx.x == 0 && blk) {
        unsigned int w = blk;
#ifdef CFT_HIP_PLANTS
        if (plant & PL_DROP_FLAG)
            w &= ~(unsigned int)CFT_SF_UNDERFLOW;
#endif
        atomicOr(&acc->flags, w);
    }
}

/* One level of the reduction tree, over nseg segments of m elements each
 * (one segment for a range of cft_reduce): output j of a segment is
 * combine(in[2j], in[2j + 1]) for j < m / 2, and when m is odd its last
 * element is CARRIED up unchanged, with no flags. Levels until one
 * element is left give exactly softfloat.c's tree - the left child the
 * largest power of two strictly inside the range, the remainder right,
 * a lone leaf verbatim - because that tree's every left child is a
 * perfect, aligned subtree (hip_test.c holds the two to each other).
 * The combine is cft_reduce's: ADD with the two subtrees in the a and c
 * slots (b is steered), or MAX in a and b for maxall. */
__global__ __launch_bounds__(256) void k_level(cft_fmt_desc f, int op, int rnd,
                                               const uint8_t *in, uint8_t *out,
                                               size_t m, size_t nseg,
                                               hacc *acc PLANT_PARAM)
{
    __shared__ unsigned int blk;
    const size_t t = (size_t)blockIdx.x * blockDim.x + threadIdx.x;
    const size_t h = (m + 1) / 2;
    const size_t esz = (size_t)f.width / 8;
    if (threadIdx.x == 0)
        blk = 0;
    __syncthreads();
    if (t < nseg * h) {
        const size_t s = t / h, j = t % h;
        const uint8_t *src = in + s * m * esz;
        uint8_t *dst = out + (s * h + j) * esz;
        size_t left = 2 * j, lone = (size_t)-1;
        if ((m & 1u) && j == h - 1)
            lone = m - 1;
#ifdef CFT_HIP_PLANTS
        if ((plant & PL_REDUCE_CARRY) && (m & 1u)) {
            lone = (j == 0) ? 0 : (size_t)-1;
            left = 2 * j - 1;
        }
#endif
        if (lone != (size_t)-1) {
            size_t k;
            for (k = 0; k < esz; k++)
                dst[k] = src[lone * esz + k];
        } else {
            cft_bn l, r, z, o;
            uint32_t fl = 0;
            int bad;
            cft_bn_zero(&l);
            cft_bn_zero(&r);
            cft_bn_zero(&z);
            cft_bn_load(&l, src + left * esz, (int)esz);
            cft_bn_load(&r, src + (left + 1) * esz, (int)esz);
            bad = (op == CFT_SF_MAXALL)
                      ? cft_sf_compute(&f, CFT_SF_MAX, rnd, &l, &r, &z, &o, &fl)
                      : cft_sf_compute(&f, CFT_SF_ADD, rnd, &l, &z, &r, &o, &fl);
            if (bad) {
                atomicMin(&acc->fail, ((unsigned long long)t << 8) |
                                          (unsigned long long)CFT_ERR_INTERNAL);
            } else {
                cft_bn_store(&o, dst, (int)esz);
#ifdef CFT_HIP_PLANTS
                if (plant & PL_REDUCE_FLAGS)
                    fl = 0;
#endif
                if (fl)
                    atomicOr(&blk, (unsigned int)fl);
            }
        }
    }
    __syncthreads();
    if (threadIdx.x == 0 && blk)
        atomicOr(&acc->flags, blk);
}

/* A program lane: G1A's blueprint (host/tools/hip_unit.py's
 * cft_hip_unit_seq), which is seq_program_run's order for one lane -
 * the lane's deposit slots, the lane in, seq_run_block on a block of
 * one, the lane out. Every pointer in A is a window of this chunk, so
 * the lane index the four functions use is the chunk's own: the chunk
 * starts at a multiple of 8 lanes and the mask window at its byte.
 * `first` is the chunk's first lane in the run, for the failure word. */
__global__ __launch_bounds__(256) void k_seq(cft_program P, cft_fmt_desc f,
                                             const cft_bn *konst, cft_run_args A,
                                             cft_bn *pool, uint32_t reach,
                                             size_t first, hacc *acc PLANT_PARAM)
{
    __shared__ unsigned int bfl, bst;
    const size_t i = (size_t)blockIdx.x * blockDim.x + threadIdx.x;
    const size_t esz = (size_t)f.width / 8;
    if (threadIdx.x == 0) {
        bfl = 0;
        bst = 0;
    }
    __syncthreads();
    if (i < A.n) {
        uint32_t fl = 0, st = 0;
        cft_status rc;
        seq_block B;
#ifdef CFT_HIP_PLANTS
        if (plant & PL_SEQ_MASK)
            A.lane_mask = NULL;
#endif
        P.f = &f;
        B.depth = P.scratch_depth;
        B.scratch = pool ? pool + i * reach : NULL;
#ifdef CFT_HIP_PLANTS
        if (!(plant & PL_SEQ_DEPOSIT))
#endif
        seq_lanes_deposits(&P, &A, i, 1, esz);
        seq_lanes_in(&P, &A, &B, i, 1, esz, reach);
        rc = seq_run_block(&P, konst, &B, 1, (uint8_t *)A.deposits, i, esz,
                           &fl, &st);
        if (rc == CFT_OK) {
            seq_lanes_out(&P, &A, &B, i, 1, esz);
            if (fl)
                atomicOr(&bfl, (unsigned int)fl);
            if (st)
                atomicOr(&bst, (unsigned int)st);
        } else {
            atomicMin(&acc->fail, ((unsigned long long)(first + i) << 8) |
                                      (unsigned long long)(unsigned)rc);
        }
    }
    __syncthreads();
    if (threadIdx.x == 0) {
        if (bfl)
            atomicOr(&acc->flags, bfl);
        if (bst)
            atomicOr(&acc->status, bst);
    }
}

/* ==== the handle ======================================================== */

constexpr size_t STAGE_MAX = (size_t)64 << 20;    /* bytes, each side */
constexpr size_t POOL_MAX = (size_t)256 << 20;    /* a program's scratch */
constexpr unsigned BLOCK = 256;                   /* threads a block */
constexpr double LAUNCH_SLOW_MS = 250.0;          /* halve the next chunk */
constexpr double LAUNCH_FAST_MS = 62.0;           /* double it */
constexpr size_t PROG_CHUNK_START = 2048;         /* lanes */
constexpr unsigned long long NO_FAIL = ~0ull;

struct Dev {
    int ordinal = 0;
    std::string label;            /* "hip:1 (NVIDIA GeForce RTX 5060 Ti)" */
    hipDeviceProp_t prop;
    hipStream_t stream = nullptr;
    uint8_t *host = nullptr;      /* pinned, `stage` bytes */
    uint8_t *dev = nullptr;       /* device, `stage` bytes */
    size_t stage = 0;
    cft_bn *pool = nullptr;       /* device, `pool_bytes` */
    size_t pool_bytes = 0, pool_cap = 0;
    size_t free_at_open = 0, total = 0;
    size_t prog_chunk = PROG_CHUNK_START;
    hipFuncAttributes fa_run, fa_level, fa_seq;
    bool poisoned = false;
    std::string poison_why;
#ifdef CFT_HIP_PLANTS
    unsigned plant = 0;
    const char *plant_name = "none";
    size_t chunk = 0;             /* CFT_HIP_CHUNK, or 0 */
    bool fail_fired = false;
#endif
};

std::string g_err;

void set_err(const std::string &s) { g_err = s; }

/* g_err from a sentence built by `build`, or a short fallback if
 * building it runs out of memory: used where a launch may have run,
 * which must go on to poison the handle whatever the message costs. */
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

/* The C boundary (backend_xrt.cpp's at_boundary, the model): no C++
 * exception crosses into C. */
template <class F>
int at_boundary(const char *what, F body) noexcept
{
    try {
        return body();
    } catch (const std::bad_alloc &) {
        set_err_or([&] { return std::string("out of host memory in ") + what +
                                " on the GPU backend"; }, "out of memory");
        return CFT_ERR_OUT_OF_MEMORY;
    } catch (const std::exception &e) {
        set_err_or([&] { return std::string(what) + " on the GPU backend: " +
                                e.what(); }, "internal error");
        return CFT_ERR_INTERNAL;
    } catch (...) {
        set_err_or([&] { return std::string(what) + " on the GPU backend failed"; },
                   "internal error");
        return CFT_ERR_INTERNAL;
    }
}

std::string fmt_str(const char *f, ...)
#if defined(__GNUC__)
    __attribute__((format(printf, 1, 2)))
#endif
    ;
std::string fmt_str(const char *f, ...)
{
    char buf[1024];
    va_list ap;
    va_start(ap, f);
    std::vsnprintf(buf, sizeof buf, f, ap);
    va_end(ap);
    return std::string(buf);
}

size_t al(size_t x) { return (x + 255u) & ~(size_t)255u; }

std::string arch_of(const hipDeviceProp_t &p)
{
#ifdef __HIP_PLATFORM_AMD__
    return std::string(p.gcnArchName);
#else
    return fmt_str("sm_%d%d", p.major, p.minor);
#endif
}

const char *platform_name()
{
#ifdef __HIP_PLATFORM_AMD__
    return "amd";
#else
    return "nvidia";
#endif
}

/* The handle can no longer be trusted: every later call refuses. */
void poison(Dev &D, const std::string &why) noexcept
{
    D.poisoned = true;
    try {
        D.poison_why = why;
    } catch (...) {
    }
}

int refuse_poisoned(const Dev &D, const char *who)
{
    set_err_or([&] {
        return fmt_str("%s: this GPU handle, %s, was left in an unknown state by "
                       "an earlier failure (%s); close it and open it again",
                       who, D.label.c_str(), D.poison_why.c_str());
    }, "this GPU handle was left in an unknown state by an earlier failure; "
       "close it and open it again");
    return CFT_ERR_INTERNAL;
}

/* A HIP call that failed once a launch may have started (or a stream
 * that may hold one): the call fails, and the handle is poisoned. */
int fail_device(Dev &D, const char *who, const char *what, hipError_t e)
{
    const std::string why = fmt_str("%s failed: %s (%s)", what, hipGetErrorString(e),
                                    hipGetErrorName(e));
    poison(D, why);
    set_err_or([&] {
        return fmt_str("%s on %s: %s - a launch may have started, so this handle "
                       "is finished: close it and open it again",
                       who, D.label.c_str(), why.c_str());
    }, "a GPU launch failed; close the handle and open it again");
    return CFT_ERR_INTERNAL;
}

/* Make this handle's device current: the current device is per thread,
 * and two handles may be open in one process. */
int enter(Dev &D, const char *who)
{
    if (D.poisoned)
        return refuse_poisoned(D, who);
    const hipError_t e = hipSetDevice(D.ordinal);
    if (e != hipSuccess)
        return fail_device(D, who, "hipSetDevice", e);
    return CFT_OK;
}

/* A device allocation the runtime refused, before anything ran: named,
 * and the handle stays usable. */
int fail_alloc(Dev &D, const char *who, const char *what, size_t bytes, hipError_t e)
{
    if (e != hipErrorOutOfMemory)
        return fail_device(D, who, what, e);
    (void)hipGetLastError();                      /* not sticky: clear it */
    set_err(fmt_str("%s: %s of %zu bytes on %s: %s - the device has %zu of %zu "
                    "bytes free at open; a smaller run, or a free device, would answer",
                    who, what, bytes, D.label.c_str(), hipGetErrorString(e),
                    D.free_at_open, D.total));
    return CFT_ERR_OUT_OF_MEMORY;
}

/* A launch the runtime refused at the launch itself - out of memory for
 * its local memory, or out of resources - is named with the numbers,
 * before anything ran. Anything else at the launch poisons. */
int check_launch(Dev &D, const char *who, const char *kernel,
                 const hipFuncAttributes &fa)
{
    const hipError_t e = hipGetLastError();
    if (e == hipSuccess)
        return CFT_OK;
    if (e == hipErrorOutOfMemory || e == hipErrorLaunchOutOfResources) {
        const unsigned long long threads =
            (unsigned long long)D.prop.multiProcessorCount *
            (unsigned long long)D.prop.maxThreadsPerMultiProcessor;
        set_err(fmt_str("%s: %s on %s was refused at launch: %s - it needs %zu "
                        "bytes of local memory and %d registers a thread; %d "
                        "multiprocessors x %d threads is %llu threads, %llu bytes "
                        "of local memory at full occupancy, with %zu of %zu bytes "
                        "free at open",
                        who, kernel, D.label.c_str(), hipGetErrorString(e),
                        (size_t)fa.localSizeBytes, fa.numRegs,
                        D.prop.multiProcessorCount, D.prop.maxThreadsPerMultiProcessor,
                        threads, threads * (unsigned long long)fa.localSizeBytes,
                        D.free_at_open, D.total));
        return CFT_ERR_OUT_OF_MEMORY;
    }
    return fail_device(D, who, (std::string("launching ") + kernel).c_str(), e);
}

/* Wait for the stream, and the fail-launch plant. */
int finish(Dev &D, const char *who)
{
    const hipError_t e = hipStreamSynchronize(D.stream);
    if (e != hipSuccess)
        return fail_device(D, who, "hipStreamSynchronize after a launch", e);
#ifdef CFT_HIP_PLANTS
    if ((D.plant & PL_FAIL_LAUNCH) && !D.fail_fired) {
        D.fail_fired = true;
        const std::string why = "the launch was reported failed after it ran "
                                "(CFT_HIP_PLANT=fail-launch)";
        poison(D, why);
        set_err(fmt_str("%s on %s: %s - a launch may have started, so this handle "
                        "is finished: close it and open it again",
                        who, D.label.c_str(), why.c_str()));
        return CFT_ERR_INTERNAL;
    }
#endif
    return CFT_OK;
}

int h2d(Dev &D, const char *who, size_t off, size_t bytes)
{
    if (!bytes)
        return CFT_OK;
    const hipError_t e = hipMemcpyAsync(D.dev + off, D.host + off, bytes,
                                        hipMemcpyHostToDevice, D.stream);
    return e == hipSuccess ? CFT_OK : fail_device(D, who, "an upload (hipMemcpyAsync)", e);
}

int d2h(Dev &D, const char *who, size_t off, size_t bytes)
{
    if (!bytes)
        return CFT_OK;
    const hipError_t e = hipMemcpyAsync(D.host + off, D.dev + off, bytes,
                                        hipMemcpyDeviceToHost, D.stream);
    return e == hipSuccess ? CFT_OK : fail_device(D, who, "a read-back (hipMemcpyAsync)", e);
}

void acc_init(Dev &D, size_t off)
{
    hacc h;
    h.flags = 0;
    h.status = 0;
    h.fail = NO_FAIL;
    std::memcpy(D.host + off, &h, sizeof h);
}

hacc acc_read(const Dev &D, size_t off)
{
    hacc h;
    std::memcpy(&h, D.host + off, sizeof h);
    return h;
}

unsigned grid_for(size_t threads)
{
    return (unsigned)((threads + BLOCK - 1) / BLOCK);
}

/* ==== the elementwise run =============================================== */

int run_impl(Dev &D, int op, int fmt, int rnd, const void *a, const void *b,
             const void *c, void *d, size_t n, uint32_t scal, uint32_t *flags)
{
    static const char who[] = "cft_run";
    const cft_fmt_desc f = cft_sf_formats[fmt];
    const size_t esz = (size_t)f.width / 8;
    const uint8_t *opnd[3] = {(const uint8_t *)a, (const uint8_t *)b,
                              (const uint8_t *)c};
    uint8_t snap[3][32];        /* a scalar operand, read once */
    size_t per = esz, fixed = 5 * 256 + sizeof(hacc), k, s;
    uint32_t fl = 0;
    int r;

    for (r = 0; r < 3; r++) {
        if (!opnd[r])
            continue;
        if ((scal >> r) & 1u) {
            /* A SNAPSHOT for the whole run, as on a tile: a d that
             * aliases the scalar does not feed a later chunk the value
             * an earlier one wrote. (The software loop re-reads it.) */
            std::memcpy(snap[r], opnd[r], esz);
            opnd[r] = snap[r];
            fixed += esz;
        } else {
            per += esz;
        }
    }
    if (D.stage <= fixed + per)
        return fail_alloc(D, who, "the stage", fixed + per, hipErrorOutOfMemory);
    k = (D.stage - fixed) / per;
#ifdef CFT_HIP_PLANTS
    if (D.chunk && D.chunk < k)
        k = D.chunk;
#endif
    for (s = 0; s < n; s += k) {
        const size_t m = n - s < k ? n - s : k;
        size_t off[3], o = 0, oacc, od;
        int st;
        for (r = 0; r < 3; r++) {
            off[r] = o;
            if (!opnd[r])
                continue;
            const size_t bytes = ((scal >> r) & 1u) ? esz : m * esz;
            std::memcpy(D.host + o, ((scal >> r) & 1u) ? opnd[r] : opnd[r] + s * esz,
                        bytes);
            o = al(o + bytes);
        }
        oacc = o;
        acc_init(D, oacc);
        od = al(oacc + sizeof(hacc));
        if ((st = h2d(D, who, 0, oacc + sizeof(hacc))) != CFT_OK)
            return st;
        k_run<<<grid_for(m), BLOCK, 0, D.stream>>>(
            f, op, rnd, opnd[0] ? D.dev + off[0] : nullptr,
            opnd[1] ? D.dev + off[1] : nullptr, opnd[2] ? D.dev + off[2] : nullptr,
            D.dev + od, m, scal, s, (hacc *)(D.dev + oacc) PLANT_ARG(D));
        if ((st = check_launch(D, who, "the elementwise kernel", D.fa_run)) != CFT_OK)
            return st;
        if ((st = d2h(D, who, oacc, od - oacc + m * esz)) != CFT_OK ||
            (st = finish(D, who)) != CFT_OK)
            return st;
        const hacc h = acc_read(D, oacc);
        if (h.fail != NO_FAIL) {
            set_err(fmt_str("%s: the GPU backend's compute step refused opcode %d "
                            "(%s) at element %llu on %s - a defect in libcft, not "
                            "in the call", who, op, cft_op_name((cft_op)op),
                            (unsigned long long)(h.fail >> 8), D.label.c_str()));
            return CFT_ERR_INTERNAL;
        }
        fl |= h.flags;
        std::memcpy((uint8_t *)d + s * esz, D.host + od, m * esz);
    }
    *flags = fl;
    return CFT_OK;
}

/* ==== the reductions ==================================================== */

/* The reduction's chunk: the largest power of two whose elements and the
 * first level's ceil(len / 2) fit the stage. A range longer than it is
 * cut into aligned chunks of it - each a node of the range's tree. */
size_t reduce_cap(const Dev &D, size_t esz)
{
    const size_t room = D.stage - 3 * 256 - sizeof(hacc);
    size_t cap = 2;
    while (cap * 2 * esz + cap * esz <= room && cap < ((size_t)1 << 40))
        cap *= 2;
#ifdef CFT_HIP_PLANTS
    if (D.chunk) {
        size_t p = 2;
        while (p * 2 <= D.chunk)
            p *= 2;
        if (p < cap)
            cap = p;
    }
#endif
    return cap;
}

/* nseg segments of m >= 2 elements each, from host `src`, to nseg
 * results at host `dst`: levels until one element a segment is left. */
int reduce_on_device(Dev &D, const char *who, const cft_fmt_desc &f, int op, int rnd,
                     const uint8_t *src, size_t m, size_t nseg, uint8_t *dst,
                     uint32_t *fl)
{
    const size_t esz = (size_t)f.width / 8;
    const size_t x = al(sizeof(hacc)), xb = nseg * m * esz;
    const size_t y = al(x + xb), yb = nseg * ((m + 1) / 2) * esz;
    size_t cur = x, nxt = y, len = m;
    int st;

    if (y + yb > D.stage)
        return fail_alloc(D, who, "the reduction's stage", y + yb, hipErrorOutOfMemory);
    acc_init(D, 0);
    std::memcpy(D.host + x, src, xb);
    if ((st = h2d(D, who, 0, x + xb)) != CFT_OK)
        return st;
    while (len > 1) {
        const size_t h = (len + 1) / 2;
        k_level<<<grid_for(nseg * h), BLOCK, 0, D.stream>>>(
            f, op, rnd, D.dev + cur, D.dev + nxt, len, nseg,
            (hacc *)D.dev PLANT_ARG(D));
        if ((st = check_launch(D, who, "the reduction's level kernel", D.fa_level)) != CFT_OK)
            return st;
        const size_t t = cur;
        cur = nxt;
        nxt = t;
        len = h;
    }
    if ((st = d2h(D, who, 0, sizeof(hacc))) != CFT_OK ||
        (st = d2h(D, who, cur, nseg * esz)) != CFT_OK || (st = finish(D, who)) != CFT_OK)
        return st;
    const hacc h = acc_read(D, 0);
    if (h.fail != NO_FAIL) {
        set_err(fmt_str("%s: the GPU backend's reduction step refused a combine on "
                        "%s - a defect in libcft, not in the call", who,
                        D.label.c_str()));
        return CFT_ERR_INTERNAL;
    }
    *fl |= h.flags;
    std::memcpy(dst, D.host + cur, nseg * esz);
    return CFT_OK;
}

/* A range of L elements to one, by the tree; a range past the chunk is
 * cut at lo + j * 2^p, nodes of the range's own tree, and the tree over
 * their partials has the same shape. */
int reduce_range(Dev &D, const char *who, const cft_fmt_desc &f, int op, int rnd,
                 const uint8_t *src, size_t len, uint8_t *dst, uint32_t *fl)
{
    const size_t esz = (size_t)f.width / 8;
    if (len == 0) {                       /* softfloat.c's empty range: +0 */
        cft_bn z;
        cft_sf_zero(&f, 0, &z);
        cft_bn_store(&z, dst, (int)esz);
        return CFT_OK;
    }
    if (len == 1) {                       /* a leaf: verbatim, no flags */
        std::memcpy(dst, src, esz);
        return CFT_OK;
    }
    const size_t cap = reduce_cap(D, esz);
    if (len <= cap)
        return reduce_on_device(D, who, f, op, rnd, src, len, 1, dst, fl);
    const size_t parts = (len + cap - 1) / cap;
    std::vector<uint8_t> part(parts * esz);
    for (size_t j = 0; j < parts; j++) {
        const size_t lo = j * cap, l = len - lo < cap ? len - lo : cap;
        const int st = reduce_range(D, who, f, op, rnd, src + lo * esz, l,
                                    part.data() + j * esz, fl);
        if (st != CFT_OK)
            return st;
    }
    return reduce_range(D, who, f, op, rnd, part.data(), parts, dst, fl);
}

/* ==== the sequencer ===================================================== */

int prog_impl(Dev &D, int fmt, const cft_seq_run_io *io, uint32_t max_deposits,
              const void *a, const void *b, const void *c, void *deposits,
              uint32_t *counts, size_t n, uint32_t *flags, uint32_t *bus)
{
    static const char who[] = "cft_program_run_ex";
    if (!io || !io->prog) {
        set_err("cft_program_run_ex: a program run needs the loaded program "
                "(cft_seq_run_io.prog), and this call carries none - the GPU "
                "backend runs the form cft_program_load validated and does not "
                "parse the image a second time");
        return CFT_ERR_INVALID_ARGUMENT;
    }
    const cft_program &prog = *io->prog;
    if (prog.fmt_code != fmt || prog.max_deposits != max_deposits) {
        set_err(fmt_str("cft_program_run_ex: the loaded program is format %d with "
                        "%u deposits a lane, and the run says %d and %u - a defect "
                        "in libcft, not in the call", prog.fmt_code,
                        (unsigned)prog.max_deposits, fmt, (unsigned)max_deposits));
        return CFT_ERR_INTERNAL;
    }
    if (io->idx_a || io->idx_b || io->idx_c || io->idx_scratch_in) {
        set_err("cft_program_run_ex: an index table reached the GPU backend, which "
                "does not publish CFT_SEQ_FEAT_INDEXED and is refused one by name "
                "in device.c first - a defect in libcft, not in the call");
        return CFT_ERR_INTERNAL;
    }
    if (!a) {
        set_err("cft_program_run_ex: stream a is NULL");
        return CFT_ERR_INVALID_ARGUMENT;
    }
    *flags = 0;
    *bus = 0;
    if (n == 0)
        return CFT_OK;

    const cft_fmt_desc f = cft_sf_formats[fmt];
    const size_t esz = (size_t)f.width / 8;
    const size_t md = deposits ? (size_t)max_deposits : 0;
    const size_t nsi = io->scratch_in ? io->n_scratch_in : 0;
    const size_t nso = io->scratch_out ? io->n_scratch_out : 0;
    const uint8_t *mask = io->lane_mask;
    uint8_t *lflags = io->lane_flags;
    const size_t nk = prog.n_consts;
    std::vector<cft_bn> bank;
    const cft_bn *kon = prog.consts;
    int st;

    /* the constants: the image's own, decoded at load, or a bank decoded
     * here as program.c decodes it - cft_bn_load per constant */
    if (io->bank && io->bank_bytes) {
        if (io->bank_bytes < nk * esz) {
            set_err(fmt_str("cft_program_run_ex: a %zu-byte bank for %zu constants "
                            "of %zu bytes - a defect in libcft, not in the call",
                            io->bank_bytes, nk, esz));
            return CFT_ERR_INTERNAL;
        }
        bank.resize(nk);
        for (size_t q = 0; q < nk; q++) {
            cft_bn_zero(&bank[q]);
            cft_bn_load(&bank[q], (const uint8_t *)io->bank + q * esz, (int)esz);
        }
        kon = bank.data();
    }
    if (nk && !kon) {
        set_err("cft_program_run_ex: a program that addresses constants reached the "
                "GPU backend with neither its own nor a bank - a defect in libcft, "
                "not in the call");
        return CFT_ERR_INTERNAL;
    }

    /* The head, once a call: the instructions and the constants. */
    const size_t o_ins = 0, o_kon = al((size_t)prog.n_insns * 8u);
    const size_t head = al(o_kon + nk * sizeof(cft_bn));
    const uint32_t reach = prog.scratch_active
                               ? seq_scratch_reach(&prog, prog.scratch_depth) : 0;
    const size_t lane_pool = (size_t)reach * sizeof(cft_bn);
    const size_t lane_in = esz * (1 + (b ? 1 : 0) + (c ? 1 : 0) + nsi) + (mask ? 1 : 0);
    const size_t lane_out = esz * (md + nso) + (counts ? 4 : 0) + (lflags ? 1 : 0);
    const size_t slack = 10 * 256 + sizeof(hacc);
    if (D.stage <= head + slack + 8 * (lane_in + lane_out) ||
        (lane_pool && D.pool_cap / lane_pool < 8)) {
        set_err(fmt_str("%s: eight lanes of this program need %zu bytes of staging "
                        "and %zu of scratch (%u slots of %zu bytes a lane) beside its "
                        "%zu-byte head, and this handle's budget on %s is %zu and %zu",
                        who, 8 * (lane_in + lane_out), 8 * lane_pool, (unsigned)reach,
                        sizeof(cft_bn), head, D.label.c_str(), D.stage, D.pool_cap));
        return CFT_ERR_OUT_OF_MEMORY;
    }
    size_t kmax = (D.stage - head - slack) / (lane_in + lane_out);
    if (lane_pool && D.pool_cap / lane_pool < kmax)
        kmax = D.pool_cap / lane_pool;
    kmax &= ~(size_t)7;
    size_t chunk = D.prog_chunk;
#ifdef CFT_HIP_PLANTS
    if (D.chunk)
        chunk = D.chunk;
#endif
    if (chunk > kmax)
        chunk = kmax;

    std::memcpy(D.host + o_ins, prog.insns, (size_t)prog.n_insns * 8u);
    if (nk)
        std::memcpy(D.host + o_kon, kon, nk * sizeof(cft_bn));
    if ((st = h2d(D, who, 0, head)) != CFT_OK)
        return st;

    cft_program P = prog;          /* by value; the device's own pointers */
    P.dev = nullptr;
    P.f = nullptr;                 /* the kernel points it at its own copy */
    P.insns = (uint64_t *)(D.dev + o_ins);
    P.consts = nullptr;            /* the executor reads konst, not this */
    P.image = nullptr;
    P.image_bytes = 0;

    uint32_t fl = 0, rep = 0;
    for (size_t first = 0; first < n;) {
        const size_t k = n - first < chunk ? n - first : chunk;
        size_t o = head;
        const size_t o_a = o;  o = al(o + k * esz);
        const size_t o_b = o;  if (b) o = al(o + k * esz);
        const size_t o_c = o;  if (c) o = al(o + k * esz);
        const size_t o_m = o;  if (mask) o = al(o + (k + 7) / 8);
        const size_t o_si = o; if (nsi) o = al(o + k * nsi * esz);
        const size_t o_acc = o; o = al(o + sizeof(hacc));
        const size_t o_dep = o; if (md) o = al(o + k * md * esz);
        const size_t o_cnt = o; if (counts) o = al(o + k * 4);
        const size_t o_lf = o;  if (lflags) o = al(o + k);
        const size_t o_so = o;  if (nso) o = al(o + k * nso * esz);
        const size_t end = o;
        bool up_out = mask != nullptr;

        std::memcpy(D.host + o_a, (const uint8_t *)a + first * esz, k * esz);
        if (b) std::memcpy(D.host + o_b, (const uint8_t *)b + first * esz, k * esz);
        if (c) std::memcpy(D.host + o_c, (const uint8_t *)c + first * esz, k * esz);
        if (mask) std::memcpy(D.host + o_m, mask + first / 8, (k + 7) / 8);
        if (nsi)
            std::memcpy(D.host + o_si, (const uint8_t *)io->scratch_in + first * nsi * esz,
                        k * nsi * esz);
        acc_init(D, o_acc);
        if (mask) {
            /* OUTPUTS UNDER A MASK GO UP FIRST: the executor leaves a masked
             * lane's deposits, count, lane byte and scratch-out alone, so
             * the window it leaves must hold the caller's bytes, or the copy
             * back would hand the caller device garbage for them. */
            if (md) std::memcpy(D.host + o_dep, (uint8_t *)deposits + first * md * esz,
                                k * md * esz);
            if (counts) std::memcpy(D.host + o_cnt, counts + first, k * 4);
            if (lflags) std::memcpy(D.host + o_lf, lflags + first, k);
            if (nso) std::memcpy(D.host + o_so,
                                 (uint8_t *)io->scratch_out + first * nso * esz,
                                 k * nso * esz);
        }
#ifdef CFT_HIP_PLANTS
        if ((D.plant & PL_SEQ_DEPOSIT) && md && !mask) {
            std::memset(D.host + o_dep, 0xA5, k * md * esz);
            up_out = true;
        }
#endif
        if ((st = h2d(D, who, head, (up_out ? end : o_acc + sizeof(hacc)) - head)) != CFT_OK)
            return st;
        if (lane_pool && D.pool_bytes < k * lane_pool) {
            if (D.pool) {
                (void)hipFree(D.pool);
                D.pool = nullptr;
                D.pool_bytes = 0;
            }
            const hipError_t e = hipMalloc((void **)&D.pool, k * lane_pool);
            if (e != hipSuccess) {
                D.pool = nullptr;
                return fail_alloc(D, who, "the program's scratch pool", k * lane_pool, e);
            }
            D.pool_bytes = k * lane_pool;
        }

        cft_run_args A;
        std::memset(&A, 0, sizeof A);
        A.struct_size = sizeof A;
        A.a = D.dev + o_a;
        A.b = b ? D.dev + o_b : nullptr;
        A.c = c ? D.dev + o_c : nullptr;
        A.n = k;
        A.scratch_in = nsi ? D.dev + o_si : nullptr;
        A.scratch_in_bytes = k * nsi * esz;
        A.scratch_out = nso ? D.dev + o_so : nullptr;
        A.scratch_out_bytes = k * nso * esz;
        A.deposits = md ? D.dev + o_dep : nullptr;
        A.counts = counts ? (uint32_t *)(D.dev + o_cnt) : nullptr;
        A.lane_mask = mask ? D.dev + o_m : nullptr;
        A.lane_mask_bytes = mask ? (k + 7) / 8 : 0;
        A.lane_flags = lflags ? D.dev + o_lf : nullptr;
        A.lane_flags_bytes = lflags ? k : 0;

        const auto t0 = std::chrono::steady_clock::now();
        k_seq<<<grid_for(k), BLOCK, 0, D.stream>>>(
            P, f, nk ? (const cft_bn *)(D.dev + o_kon) : nullptr, A,
            lane_pool ? D.pool : nullptr, reach, first, (hacc *)(D.dev + o_acc)
            PLANT_ARG(D));
        if ((st = check_launch(D, who, "the sequencer's kernel", D.fa_seq)) != CFT_OK)
            return st;
        if ((st = d2h(D, who, o_acc, end - o_acc)) != CFT_OK || (st = finish(D, who)) != CFT_OK)
            return st;
        const double ms = std::chrono::duration<double, std::milli>(
                              std::chrono::steady_clock::now() - t0).count();
        const hacc h = acc_read(D, o_acc);
        if (h.fail != NO_FAIL) {
            const int code = (int)(h.fail & 0xFFu);
            set_err(fmt_str("%s: lane %llu of the run failed on %s with %s - the "
                            "loader validated this program, so this is a defect in "
                            "libcft, not in the call", who,
                            (unsigned long long)(h.fail >> 8), D.label.c_str(),
                            cft_strerror((cft_status)code)));
            return code ? code : CFT_ERR_INTERNAL;
        }
        fl |= h.flags;
        rep |= h.status;
        if (md) std::memcpy((uint8_t *)deposits + first * md * esz, D.host + o_dep,
                            k * md * esz);
        if (counts) std::memcpy(counts + first, D.host + o_cnt, k * 4);
        if (lflags) std::memcpy(lflags + first, D.host + o_lf, k);
        if (nso) std::memcpy((uint8_t *)io->scratch_out + first * nso * esz,
                             D.host + o_so, k * nso * esz);
        first += k;
        /* the next chunk's size, from this one's time (the head says why) */
#ifdef CFT_HIP_PLANTS
        if (!D.chunk)
#endif
        {
            if (ms > LAUNCH_SLOW_MS && chunk > 8)
                chunk = (chunk / 2) & ~(size_t)7;
            else if (ms < LAUNCH_FAST_MS && k == chunk && chunk * 2 <= kmax)
                chunk *= 2;
            if (chunk < 8)
                chunk = 8;
            D.prog_chunk = chunk;
        }
    }
    *flags = fl;
    /* STATUS's three reports, all of them (backend.h) */
    *bus = rep & (CFT_STATUS_DEPOSIT_OVERFLOW | CFT_STATUS_SCRATCH_RANGE |
                  CFT_STATUS_MARKED);
    return CFT_OK;
}

/* ==== opening a device =================================================== */

#ifdef CFT_HIP_PLANTS
const struct {
    const char *name;
    unsigned bit;
} k_plants[] = {
    {"flip", PL_FLIP},
    {"rmm-as-rne", PL_RMM_AS_RNE},
    {"drop-flag", PL_DROP_FLAG},
    {"reduce-carry", PL_REDUCE_CARRY},
    {"reduce-flags", PL_REDUCE_FLAGS},
    {"seq-mask", PL_SEQ_MASK},
    {"seq-deposit", PL_SEQ_DEPOSIT},
    {"fail-launch", PL_FAIL_LAUNCH},
};

/* CFT_HIP_PLANT and CFT_HIP_CHUNK, read at open; a value that is not
 * exactly one of the names, or not a decimal multiple of 8 in range, is
 * refused by name - an instrument that read a typo as "no plant" would
 * be a check that could not fail. Unset or empty is none. */
int read_plants(Dev &D)
{
    std::string names;
    const char *v = std::getenv("CFT_HIP_PLANT");
    if (v && *v) {
        for (const auto &p : k_plants) {
            if (!std::strcmp(v, p.name)) {
                D.plant = p.bit;
                D.plant_name = p.name;
            }
            names += names.empty() ? p.name : std::string(", ") + p.name;
        }
        if (!D.plant) {
            set_err(fmt_str("CFT_HIP_PLANT=\"%s\": expected one of %s; unset it for "
                            "none", v, names.c_str()));
            return CFT_ERR_INVALID_ARGUMENT;
        }
    }
    const char *cv = std::getenv("CFT_HIP_CHUNK");
    if (cv && *cv) {
        bool ok = true;
        unsigned long long x = 0;
        for (const char *p = cv; *p; p++) {
            if (*p < '0' || *p > '9' || x > (1ull << 30)) {
                ok = false;
                break;
            }
            x = x * 10 + (unsigned)(*p - '0');
        }
        if (!ok || x < 8 || x > (1ull << 30) || (x & 7u)) {
            set_err(fmt_str("CFT_HIP_CHUNK=\"%s\": expected a decimal multiple of 8 "
                            "from 8 to 1073741824 (elements, or lanes); unset it for "
                            "the default", cv));
            return CFT_ERR_INVALID_ARGUMENT;
        }
        D.chunk = (size_t)x;
    }
    return CFT_OK;
}
#endif

void close_dev(Dev *D) noexcept
{
    if (!D)
        return;
    (void)hipSetDevice(D->ordinal);
    if (D->stream)
        (void)hipStreamSynchronize(D->stream);
    if (D->pool)
        (void)hipFree(D->pool);
    if (D->dev)
        (void)hipFree(D->dev);
    if (D->host)
        (void)hipHostFree(D->host);
    if (D->stream)
        (void)hipStreamDestroy(D->stream);
    delete D;
}

int open_impl(const char *artifact, int index, void **out, uint32_t *format_mask,
              uint32_t *op_groups, uint32_t *tiles, uint32_t *version,
              int *flags_readable, cft_seq_caps *seq)
{
    static const char grammar[] =
        "the artifact is \"hip:\" followed by the device's number in decimal and "
        "nothing else - hip:0 is the first GPU the HIP runtime sees";
    if (!artifact || !out) {
        set_err("cft_open: the GPU backend was handed no artifact or no out - a "
                "defect in libcft, not in the call");
        return CFT_ERR_INTERNAL;
    }
    *out = nullptr;
    /* "hip" itself, and anything from "hip:", is an attempt at the
     * grammar and is told it; any other string is not a GPU */
    if (std::strcmp(artifact, "hip") != 0 && std::strncmp(artifact, "hip:", 4) != 0) {
        set_err(fmt_str("cft_open: %s is not a GPU, and this libcft build's device "
                        "backend is the GPU backend (HIP=1), which opens hip:N only; "
                        "an xclbin needs a build with XRT=1, and the software "
                        "backend is cft_open(NULL, 0, ...)", artifact));
        return CFT_ERR_NO_DEVICE;
    }
    /* "hip:" and then decimal digits, and nothing else */
    const char *p = artifact + 3;
    unsigned long long num = 0;
    bool ok = *p == ':' && p[1] != '\0', big = false;
    if (ok) {
        for (p++; *p; p++) {
            if (*p < '0' || *p > '9') {
                ok = false;
                break;
            }
            if (num > (unsigned long long)INT_MAX)
                big = true;
            else
                num = num * 10 + (unsigned)(*p - '0');
        }
    }
    if (!ok) {
        set_err(fmt_str("cft_open: \"%s\" is not a GPU artifact: %s", artifact, grammar));
        return CFT_ERR_INVALID_ARGUMENT;
    }
    if (index != 0) {
        set_err(fmt_str("cft_open: %s with index %d - hip:N names the device; pass "
                        "index 0", artifact, index));
        return CFT_ERR_INVALID_ARGUMENT;
    }
    int count = 0;
    hipError_t e = hipGetDeviceCount(&count);
    if (e != hipSuccess) {
        set_err(fmt_str("cft_open: %s: the HIP runtime found no usable GPU: %s (%s)",
                        artifact, hipGetErrorString(e), hipGetErrorName(e)));
        (void)hipGetLastError();
        return CFT_ERR_NO_DEVICE;
    }
    if (big || num >= (unsigned long long)count) {
        set_err(fmt_str("cft_open: %s names GPU %s, and the HIP runtime sees %d (hip:0 "
                        "to hip:%d)%s", artifact, big ? "past INT_MAX" :
                        std::to_string(num).c_str(), count, count - 1,
                        count ? "" : " - none at all"));
        return CFT_ERR_NO_DEVICE;
    }

    Dev *D = new Dev();
    D->ordinal = (int)num;
    if ((e = hipSetDevice(D->ordinal)) != hipSuccess ||
        (e = hipGetDeviceProperties(&D->prop, D->ordinal)) != hipSuccess) {
        set_err(fmt_str("cft_open: %s: selecting the device failed: %s (%s)", artifact,
                        hipGetErrorString(e), hipGetErrorName(e)));
        (void)hipGetLastError();
        delete D;
        return CFT_ERR_NO_DEVICE;
    }
    D->label = fmt_str("%s (%s)", artifact, D->prop.name);
    /* The device must run THIS build's kernels: a code object for its
     * architecture is in the library, or every kernel's attributes fail. */
    const hipError_t e1 = hipFuncGetAttributes(&D->fa_run, (const void *)k_run);
    const hipError_t e2 = hipFuncGetAttributes(&D->fa_level, (const void *)k_level);
    const hipError_t e3 = hipFuncGetAttributes(&D->fa_seq, (const void *)k_seq);
    if (e1 != hipSuccess || e2 != hipSuccess || e3 != hipSuccess) {
        const hipError_t eb = e1 != hipSuccess ? e1 : e2 != hipSuccess ? e2 : e3;
        set_err(fmt_str("cft_open: %s is %s, and this libcft's GPU code was built for "
                        "HIP_ARCH %s (%s platform): its kernels do not load there - %s "
                        "(%s). Rebuild with HIP_ARCH naming %s",
                        artifact, arch_of(D->prop).c_str(), CFT_HIP_ARCH,
                        platform_name(), hipGetErrorString(eb), hipGetErrorName(eb),
                        arch_of(D->prop).c_str()));
        (void)hipGetLastError();
        delete D;
        return CFT_ERR_NO_DEVICE;
    }
#ifdef CFT_HIP_PLANTS
    {
        const int pst = read_plants(*D);
        if (pst != CFT_OK) {
            delete D;
            return pst;
        }
    }
#endif
    {
        /* CFT_HIP_INFO=1: the device, named, on stderr; 0 or unset: nothing */
        const char *iv = std::getenv("CFT_HIP_INFO");
        if (iv && *iv && std::strcmp(iv, "0") && std::strcmp(iv, "1")) {
            set_err(fmt_str("CFT_HIP_INFO=\"%s\": expected 1 (name the device on "
                            "stderr at open) or 0; unset it for none", iv));
            delete D;
            return CFT_ERR_INVALID_ARGUMENT;
        }
        D->prog_chunk = PROG_CHUNK_START;
        if ((e = hipMemGetInfo(&D->free_at_open, &D->total)) != hipSuccess) {
            set_err(fmt_str("cft_open: %s: reading its free memory failed: %s",
                            D->label.c_str(), hipGetErrorString(e)));
            (void)hipGetLastError();
            delete D;
            return CFT_ERR_NO_DEVICE;
        }
        D->stage = D->free_at_open / 8 < STAGE_MAX ? D->free_at_open / 8 : STAGE_MAX;
        D->pool_cap = D->free_at_open / 8 < POOL_MAX ? D->free_at_open / 8 : POOL_MAX;
        if (D->stage < ((size_t)1 << 20)) {
            set_err(fmt_str("cft_open: %s has %zu of %zu bytes free, and the GPU "
                            "backend stages through an eighth of it, at least 1 MiB",
                            D->label.c_str(), D->free_at_open, D->total));
            delete D;
            return CFT_ERR_OUT_OF_MEMORY;
        }
        if ((e = hipStreamCreateWithFlags(&D->stream, hipStreamNonBlocking)) != hipSuccess ||
            (e = hipHostMalloc((void **)&D->host, D->stage, hipHostMallocDefault)) != hipSuccess ||
            (e = hipMalloc((void **)&D->dev, D->stage)) != hipSuccess) {
            const bool oom = e == hipErrorOutOfMemory;
            set_err(fmt_str("cft_open: %s: allocating its %zu-byte stage failed: %s (%s)",
                            D->label.c_str(), D->stage, hipGetErrorString(e),
                            hipGetErrorName(e)));
            (void)hipGetLastError();
            close_dev(D);
            return oom ? CFT_ERR_OUT_OF_MEMORY : CFT_ERR_NO_DEVICE;
        }
        if (iv && !std::strcmp(iv, "1")) {
            int rtv = 0, drv = 0;
            (void)hipRuntimeGetVersion(&rtv);
            (void)hipDriverGetVersion(&drv);
            const char *vis = std::getenv("CUDA_VISIBLE_DEVICES");
            const char *hvis = std::getenv("HIP_VISIBLE_DEVICES");
            std::fprintf(stderr,
                         "cft hip: %s = %s (%s, %d multiprocessors, bus "
                         "%04x:%02x:%02x.0, %zu MiB), HIP platform %s, runtime %d, "
                         "driver %d; of %d visible%s%s%s%s; this libcft: HIP_ARCH %s,"
                         " stage %zu MiB, kernels %d/%d/%d registers and "
                         "%zu/%zu/%zu bytes local a thread (run/level/seq)%s%s\n",
                         artifact, D->prop.name, arch_of(D->prop).c_str(),
                         D->prop.multiProcessorCount, (unsigned)D->prop.pciDomainID,
                         (unsigned)D->prop.pciBusID, (unsigned)D->prop.pciDeviceID,
                         (size_t)(D->prop.totalGlobalMem >> 20), platform_name(), rtv,
                         drv, count, vis ? ", CUDA_VISIBLE_DEVICES=" : "",
                         vis ? vis : "", hvis ? ", HIP_VISIBLE_DEVICES=" : "",
                         hvis ? hvis : "", CFT_HIP_ARCH, D->stage >> 20,
                         D->fa_run.numRegs, D->fa_level.numRegs, D->fa_seq.numRegs,
                         (size_t)D->fa_run.localSizeBytes,
                         (size_t)D->fa_level.localSizeBytes,
                         (size_t)D->fa_seq.localSizeBytes,
#ifdef CFT_HIP_PLANTS
                         ", PLANTS COMPILED IN, CFT_HIP_PLANT=", D->plant_name
#else
                         "", ""
#endif
                         );
#ifdef CFT_HIP_PLANTS
            if (D->chunk)
                std::fprintf(stderr, "cft hip: CFT_HIP_CHUNK=%zu\n", D->chunk);
#endif
        }
    }

    *format_mask = CFT_FORMAT_MASK_BUILD;
    *op_groups = 0x7Fu;
    *tiles = 1;
    *version = 0;
    *flags_readable = 1;
    /* The software executor's capacities, because it is the software
     * executor that runs; with the two bits device.c's software handle
     * adds (a scalar operand, the segmented reduction - both run here
     * too), and without the two this backend does not carry. */
    cft_sw_seq_caps(seq);
    seq->features |= CFT_SEQ_FEAT_SCALAR | CFT_FEAT_REDUCE_SEG;
    seq->features &= ~(uint32_t)(CFT_SEQ_FEAT_INDEXED | CFT_SEQ_FEAT_AUGADD);
    *out = D;
    return CFT_OK;
}

}  // namespace

/* ==== the seam (backend.h, cftx_ renamed cfth_) ========================== */

extern "C" const char *cfth_last_error(void)
{
    return g_err.c_str();
}

extern "C" void cfth_clear_error(void)
{
    g_err.clear();
}

extern "C" int cfth_open(const char *artifact, int index, void **out,
                         uint32_t *format_mask, uint32_t *op_groups, uint32_t *tiles,
                         uint32_t *version, int *flags_readable, cft_seq_caps *seq)
{
    g_err.clear();
    return at_boundary("opening a GPU", [&] {
        return open_impl(artifact, index, out, format_mask, op_groups, tiles,
                         version, flags_readable, seq);
    });
}

extern "C" void cfth_close(void *hw)
{
    close_dev(static_cast<Dev *>(hw));
}

extern "C" int cfth_image_id(void *hw, cft_image_raw *out)
{
    (void)hw;
    (void)out;
    g_err.clear();
    return at_boundary("reading the device image's identity", [&] {
        set_err("cft_get_image_id: the GPU backend loads no device image - there is "
                "no xclbin to hash and no CAPS register to read; what determines its "
                "bits is this library (cft_build_id()) and the device's compiler");
        return (int)CFT_ERR_UNSUPPORTED;
    });
}

/* Resident buffers: not in this build (CFT_HIP_BUFFERS_RESIDENT 0). The
 * create declines, writing no sentence (the seam's create writes none),
 * and device.c keeps the buffer as host memory; the others are then
 * unreachable, and answer as a defect if reached. */
extern "C" int cfth_buffer_create(void *hw, void *host, size_t bytes, void **out)
{
    (void)hw;
    (void)host;
    (void)bytes;
    if (out)
        *out = nullptr;
    return CFT_ERR_UNSUPPORTED;
}

extern "C" void cfth_buffer_destroy(void *buf)
{
    (void)buf;
}

static int no_buffers(const char *who)
{
    set_err(std::string(who) + ": the GPU backend keeps no device buffers in this "
            "build (CFT_HIP_BUFFERS_RESIDENT is 0) and made none - a defect in "
            "libcft, not in the call");
    return CFT_ERR_INTERNAL;
}

extern "C" int cfth_buffer_to_device(void *buf)
{
    (void)buf;
    g_err.clear();
    return at_boundary("publishing a buffer", [] { return no_buffers("cft_buffer_to_device"); });
}

extern "C" int cfth_buffer_from_device(void *buf)
{
    (void)buf;
    g_err.clear();
    return at_boundary("reading a buffer back", [] { return no_buffers("cft_buffer_from_device"); });
}

extern "C" int cfth_buffer_will_write(void *buf, size_t off, size_t len)
{
    (void)buf;
    (void)off;
    (void)len;
    g_err.clear();
    return at_boundary("preparing a buffer for a host write",
                       [] { return no_buffers("a host write into a buffer"); });
}

extern "C" int cfth_buffer_host_wrote(void *buf, size_t off, size_t len)
{
    (void)buf;
    (void)off;
    (void)len;
    return CFT_OK;
}

extern "C" void cfth_buffer_stat(void *buf, int *resident, int *device_authority,
                                 uint64_t *resident_binds, uint64_t *staged_binds,
                                 char *why, size_t why_bytes)
{
    (void)buf;
    if (resident) *resident = 0;
    if (device_authority) *device_authority = 0;
    if (resident_binds) *resident_binds = 0;
    if (staged_binds) *staged_binds = 0;
    if (why && why_bytes) {
        std::snprintf(why, why_bytes, "the GPU backend keeps no device buffers in "
                      "this build: every operand is staged");
    }
}

extern "C" int cfth_run(void *hw, int op, int fmt, int rnd, const void *a,
                        const void *b, const void *c, void *d, size_t n,
                        uint32_t scalar_mask, const cft_bindings *bind,
                        uint32_t *flags, uint32_t *bus)
{
    (void)bind;                   /* none bound: CFT_HIP_BUFFERS_RESIDENT 0 */
    g_err.clear();
    if (bus)
        *bus = 0;
    return at_boundary("a run", [&]() -> int {
        Dev &D = *static_cast<Dev *>(hw);
        uint32_t fl = 0;
        int st = enter(D, "cft_run");
        if (st != CFT_OK)
            return st;
        if (fmt < 0 || fmt > CFT_MAX_FORMAT || !d || !flags) {
            set_err("cft_run: the GPU backend was handed a format, an output or a "
                    "flag word device.c refuses first - a defect in libcft, not in "
                    "the call");
            return CFT_ERR_INTERNAL;
        }
        if (n == 0) {
            *flags = 0;
            return CFT_OK;
        }
        st = run_impl(D, op, fmt, rnd, a, b, c, d, n, scalar_mask, &fl);
        if (st == CFT_OK)
            *flags = fl;
        return st;
    });
}

extern "C" int cfth_reduce(void *hw, int op, int fmt, int rnd, const void *a,
                           const size_t *lo, const size_t *hi, size_t nranges,
                           void *partials, const cft_bindings *bind, uint32_t *flags,
                           uint32_t *bus)
{
    (void)bind;
    g_err.clear();
    if (bus)
        *bus = 0;
    return at_boundary("a reduction", [&]() -> int {
        static const char who[] = "cft_reduce";
        Dev &D = *static_cast<Dev *>(hw);
        uint32_t fl = 0;
        int st = enter(D, who);
        if (st != CFT_OK)
            return st;
        if (op != CFT_SF_SUM) {
            set_err(fmt_str("cft_reduce: the GPU backend was handed opcode %d (%s) as a "
                            "whole-array reduction, and device.c sends it sum alone - "
                            "dot, sumSquare and sumAbs are composed above it and maxall "
                            "goes to the segmented form - a defect in libcft, not in "
                            "the call", op, cft_op_name((cft_op)op)));
            return CFT_ERR_INTERNAL;
        }
        if (fmt < 0 || fmt > CFT_MAX_FORMAT || !a || !partials || !flags) {
            set_err("cft_reduce: the GPU backend was handed a format or a pointer "
                    "device.c refuses first - a defect in libcft, not in the call");
            return CFT_ERR_INTERNAL;
        }
        const cft_fmt_desc f = cft_sf_formats[fmt];
        const size_t esz = (size_t)f.width / 8;
        for (size_t r = 0; r < nranges; r++) {
            if (hi[r] < lo[r]) {
                set_err("cft_reduce: a range whose end is before its start reached "
                        "the GPU backend - a defect in libcft, not in the call");
                return CFT_ERR_INTERNAL;
            }
            st = reduce_range(D, who, f, op, rnd, (const uint8_t *)a + lo[r] * esz,
                              hi[r] - lo[r], (uint8_t *)partials + r * esz, &fl);
            if (st != CFT_OK)
                return st;
        }
        *flags = fl;
        return CFT_OK;
    });
}

extern "C" int cfth_reduce_seg(void *hw, int op, int fmt, int rnd, const void *a,
                               size_t n, size_t seg, void *d, const cft_bindings *bind,
                               uint32_t *flags, uint32_t *bus)
{
    (void)bind;
    g_err.clear();
    if (bus)
        *bus = 0;
    return at_boundary("a segmented reduction", [&]() -> int {
        static const char who[] = "cft_reduce_seg";
        Dev &D = *static_cast<Dev *>(hw);
        uint32_t fl = 0;
        int st = enter(D, who);
        if (st != CFT_OK)
            return st;
        if (op != CFT_SF_SUM && op != CFT_SF_MAXALL) {
            set_err(fmt_str("cft_reduce_seg: the GPU backend was handed opcode %d (%s), "
                            "and device.c sends it sum and maxall alone - the others "
                            "are composed above it - a defect in libcft, not in the "
                            "call", op, cft_op_name((cft_op)op)));
            return CFT_ERR_INTERNAL;
        }
        if (fmt < 0 || fmt > CFT_MAX_FORMAT || !a || !d || !flags || !seg || n % seg) {
            set_err("cft_reduce_seg: the GPU backend was handed a format, a pointer or "
                    "a segment device.c refuses first - a defect in libcft, not in "
                    "the call");
            return CFT_ERR_INTERNAL;
        }
        const cft_fmt_desc f = cft_sf_formats[fmt];
        const size_t esz = (size_t)f.width / 8, nres = n / seg;
        const uint8_t *src = (const uint8_t *)a;
        uint8_t *dst = (uint8_t *)d;
        if (seg == 1) {
            /* every segment one leaf: verbatim, no flags */
            std::memmove(dst, src, n * esz);
            *flags = 0;
            return CFT_OK;
        }
        const size_t room = D.stage - 3 * 256 - sizeof(hacc);
        const size_t per_seg = (seg + (seg + 1) / 2) * esz;
        size_t g = per_seg <= room ? room / per_seg : 0;
        if (g && seg > reduce_cap(D, esz))
            g = 0;                        /* a chunk smaller than a segment */
#ifdef CFT_HIP_PLANTS
        if (g && D.chunk) {
            const size_t gc = D.chunk / seg;
            g = gc ? (gc < g ? gc : g) : 0;
        }
#endif
        if (g) {
            for (size_t s0 = 0; s0 < nres; s0 += g) {
                const size_t gs = nres - s0 < g ? nres - s0 : g;
                st = reduce_on_device(D, who, f, op, rnd, src + s0 * seg * esz, seg, gs,
                                      dst + s0 * esz, &fl);
                if (st != CFT_OK)
                    return st;
            }
        } else {
            for (size_t s = 0; s < nres; s++) {
                st = reduce_range(D, who, f, op, rnd, src + s * seg * esz, seg,
                                  dst + s * esz, &fl);
                if (st != CFT_OK)
                    return st;
            }
        }
        *flags = fl;
        return CFT_OK;
    });
}

extern "C" int cfth_program_run(void *hw, int fmt, const void *image, size_t image_bytes,
                                const cft_seq_run_io *io, uint32_t max_deposits,
                                const void *a, const void *b, const void *c,
                                void *deposits, uint32_t *counts, size_t n,
                                const cft_bindings *bind, uint32_t *flags, uint32_t *bus)
{
    (void)image;                  /* the parsed form runs: io->prog */
    (void)image_bytes;
    (void)bind;
    g_err.clear();
    return at_boundary("a program run", [&]() -> int {
        Dev &D = *static_cast<Dev *>(hw);
        uint32_t fl = 0, rep = 0;
        int st = enter(D, "cft_program_run_ex");
        if (st != CFT_OK)
            return st;
        if (fmt < 0 || fmt > CFT_MAX_FORMAT) {
            set_err("cft_program_run_ex: the GPU backend was handed a format the "
                    "loader refuses first - a defect in libcft, not in the call");
            return CFT_ERR_INTERNAL;
        }
        st = prog_impl(D, fmt, io, max_deposits, a, b, c, deposits, counts, n, &fl, &rep);
        if (st == CFT_OK) {
            if (flags) *flags = fl;
            if (bus) *bus = rep;
        }
        return st;
    });
}
