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
 * capacities with all its features (seq_features 0x7ff1f, the software
 * handle's own). Round 1 did not carry the two below and refused them
 * by name; round 2 added them, one item a parcel:
 *
 *   index tables (CFT_SEQ_FEAT_INDEXED): carried since round 2's G2B,
 *   so no longer among them - a program's four tables, and cft_run_ex's
 *   (device.c composes those as a program), run on the device: each
 *   SOURCE whole in device memory, each table cut with its chunk's lanes
 *   (prog_impl, below);
 *
 *   augmentedAddition (CFT_SEQ_FEAT_AUGADD) is no longer one of them
 *   (round 2's G2A): this unit includes augmented.c's lane functions
 *   (CFT_AUG_LANES_ONLY, which leaves its entry points to libcft's
 *   augmented.o), so the executor runs AUGADD and AUGERR, and the API's
 *   cft_augmented_add, _sub and _mul run here too, on a seam entry of
 *   their own (cfth_augmented: k_aug, a thread an element).
 *
 * A program's scratch is its handle's depth: the software executor's 256
 * slots, or the power of two cft_open_ex opened the GPU at, up to
 * CFT_HIP_SCRATCH_MAX, the card's 2,048 (backend.h; deeper is refused by
 * name in device.c). The slots are device memory, `reach` of them a lane
 * in the handle's pool, so a deeper depth costs lanes a launch, not the
 * thread's frame (round 2's G2B).
 *
 * No device image: cft_get_image_id is refused by name. Resident
 * buffers: yes (CFT_HIP_BUFFERS_RESIDENT 1, backend.h; below).
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
 * Resident buffers (cft_alloc), and who owns the bytes
 * ---------------------------------------------------------------
 *
 * A cft_alloc'd buffer gets ONE device allocation the size of its host
 * mirror, made the first time a call binds it and never resized: a GPU
 * has one memory, so where the XRT backend keeps a copy per tile and
 * role, this keeps one, at the mirror's own offsets. Its state is kept
 * a PAGE at a time (256 bytes, eight fp256 elements; CFT_HIP_PAGE in a
 * plant build): STALE, the mirror is the truth and the device's bytes
 * are not; FRESH, the two agree; DIRTY, a run wrote it and the device is
 * the truth. A binding uploads the STALE pages its call reads - an
 * input's whole window, an output's whole window under a lane mask (its
 * masked lanes must stay the caller's), an unmasked output's edge pages
 * alone (the run writes the rest) - and a run of pages is marked FRESH
 * only once its copy has completed. A good run leaves its outputs'
 * pages DIRTY; cft_buffer_from_device brings DIRTY pages home. The
 * rules cft.h states for a device backend - a publish over unread
 * results refused, a failed run's outputs LOST, a host write staling
 * only what it touches - are the XRT backend's, page by page.
 *
 * One copy means two roles of one call can share bytes on the device,
 * which per-role copies never do. So an input that overlaps an output of
 * the same call in the same buffer is STAGED (read from the mirror,
 * which device.c has brought home first), except cft_run's d == a and an
 * augmented call's r or e over a or b, where each element is read before
 * its own is written (cft.h); and two outputs that overlap are both
 * staged and written into the mirror in the staged order. No lane reads
 * what another lane writes, so no answer depends on the order lanes run
 * in.
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
 *   stale-publish  cft_buffer_to_device leaves the pages as they were:
 *                  the next run binds the bytes published before
 *   no-readback    cft_buffer_from_device marks DIRTY pages FRESH and
 *                  copies nothing home
 *   fresh-early    an upload's pages marked FRESH before its copy, the
 *                  order verifier-V8 found in the XRT backend (KL-464);
 *                  only an upload that fails (CFT_HIP_UPLOAD) shows it
 *   (round 2's G2A: its plants here)
 *   aug-flip       bit 0 of r's first element in an augmented call
 *   aug-flags      overflow dropped from an augmented call's flag word
 *   aug-swap       r and e written in each other's place, first element
 *   seq-aug        the executor's AUGERR computed as AUGADD: its lane
 *                  call, wrapped in this unit, delivers r as e
 *   (round 2's G2B: its plants here)
 *   idx-chunk      an index table's window not advanced per chunk: every
 *                  chunk reads the table's first entries (R16's trap)
 *   idx-none       CFT_IDX_NONE read as index 0 (a staged table chunk's
 *                  sentinels rewritten to 0 on their way up)
 *   src-trunc      a staged indexed source uploaded at min(n, its length)
 *                  elements, the rest of its device copy left 0xA5
 *   depth-clamp    the kernel's copy of a program deeper than 256 slots
 *                  at 256 (its scratch_depth and log2)
 *   (round 2's G2C: its plants here)
 *   bank-mode      a whole-operation run's five mode words (the last five
 *                  of the bank of a BANK_EXT program of 42 or more
 *                  constants and two deposits a lane: divsqrt.c's divfull
 *                  and sqrtfull) rotated by one, so the image rounds with
 *                  the next attribute - rne as rtz, ..., rmm as rne
 *   full-flag      after such a run, INEXACT cleared from lane 0's flag
 *                  word (its deposit 1)
 *   full-refuse    a BANK_EXT program of 42 or more constants refused by
 *                  name (CFT_ERR_UNSUPPORTED) before anything is bound or
 *                  run: divsqrt.c's ladder falls through to the program
 *                  route, whose bits are the same, so only a route probe
 *                  can see it
 *
 * CFT_HIP_CHUNK=<n> (a multiple of 8, 8 to 2^30) fixes the chunk: n
 * elements a run, the largest power of two not above n a reduction's
 * chunk, n lanes a program's, so small data crosses every boundary.
 * CFT_HIP_PAGE=<bytes> (a power of two, 32 to 1048576) sets the page.
 * CFT_HIP_UPLOAD=fail-fill, read at each call that binds a resident
 * buffer, fails that call's first upload after its host copy and before
 * the device copy - an instrument, as CFT_XRT_UPLOAD is the XRT
 * backend's.
 */

/* ---- the unit: the tree's own sources, for the host and the device ---- */
#include <hip/hip_runtime.h>   /* first: blockIdx, and AMD's device memset
                                * seq_exec.h calls (G1A's known limit 2) */
#define BLOCK_LANES 1          /* a thread is a block of one lane */
#ifndef CFT_HIP_PLANT_COLLIDE
/* softfloat.c's one datum, renamed in this unit - see the head */
#define cft_sf_formats cft_hip_sf_formats
#endif
#ifndef CFT_HIP_PLANT_AUG_HOST
/* augmented.c's lane functions alone: its entry points are C names that
 * libcft's augmented.o defines, which hip-symcheck holds this unit to
 * (hip-symcheck-plant removes this define and must see them collide) */
#define CFT_AUG_LANES_ONLY 1
#endif
#include "bigint.c"
#include "softfloat.c"
#include "augmented.c"
#ifdef CFT_HIP_PLANT_AUG_HOST
/* hip-symcheck-plant's unit only: augmented.c whole, entry points and all,
 * has no cft_aug_mul_lane (augmented.c defines it under the guard), so the
 * plant's build names the product's lane here, for k_aug to compile and
 * the symbol check, not the compiler, to be what refuses the unit */
CFT_HD int cft_aug_mul_lane(const cft_fmt_desc *f, const cft_bn *xa, const cft_bn *xb,
                            cft_bn *vr, cft_bn *ve, uint32_t *acc)
{
    return aug_mul_lane(f, xa, xb, vr, ve, acc);
}
#endif
#ifdef CFT_HIP_PLANTS
/* The seq-aug plant: the executor's lane call, wrapped here so that
 * seq_exec.h is not edited, delivers r as e when the launch's word says
 * so - AUGERR computed as AUGADD. k_seq sets the word from its plant
 * argument; k_aug calls the lane function itself, never this. Only the
 * device's pass reads the word, hence maybe_unused for the host's. */
[[maybe_unused]] static __device__ unsigned g_plant_seq_aug;
CFT_HD static int plant_aug_add_lane(const cft_fmt_desc *f, const cft_bn *xa,
                                     const cft_bn *xb, cft_bn *vr, cft_bn *ve,
                                     uint32_t *acc)
{
    const int rc = cft_aug_add_lane(f, xa, xb, vr, ve, acc);
#if defined(__CUDA_ARCH__) || defined(__HIP_DEVICE_COMPILE__)
    if (g_plant_seq_aug)
        cft_bn_copy(ve, vr);
#endif
    return rc;
}
#define cft_aug_add_lane plant_aug_add_lane
#endif
#include "seq_exec.h"
#ifdef CFT_HIP_PLANTS
#undef cft_aug_add_lane
#endif
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
    PL_SEQ_MASK = 1u << 5, PL_SEQ_DEPOSIT = 1u << 6, PL_FAIL_LAUNCH = 1u << 7,
    PL_STALE_PUBLISH = 1u << 8, PL_NO_READBACK = 1u << 9, PL_FRESH_EARLY = 1u << 10,
    /* round 2's G2A: its plants here, bits 11 to 15 */
    PL_AUG_FLIP = 1u << 11, PL_AUG_FLAGS = 1u << 12, PL_AUG_SWAP = 1u << 13,
    PL_SEQ_AUG = 1u << 14,
    /* round 2's G2B: its plants here, bits 16 to 20 */
    PL_IDX_CHUNK = 1u << 16, PL_IDX_NONE = 1u << 17, PL_SRC_TRUNC = 1u << 18,
    PL_DEPTH_CLAMP = 1u << 19,
    /* round 2's G2C: its plants here, bits 21 to 25 */
    PL_BANK_MODE = 1u << 21, PL_FULL_FLAG = 1u << 22, PL_FULL_REFUSE = 1u << 23,
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
        g_plant_seq_aug = (plant & PL_SEQ_AUG) ? 1u : 0u;  /* seq-aug's word, every lane */
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

/* The API's augmented calls (cfth_augmented): element i of a chunk through
 * augmented.c's own lane functions, as its host loops run one - loaded and
 * stored by its lane_load and lane_store, both inputs read before either
 * output is written (so r or e may share an input's window), b's sign bit
 * flipped on its integer encoding for a subtraction exactly as
 * cft_augmented_sub flips it (never through a double, which would quiet a
 * signalling NaN), then cft_aug_add_lane or cft_aug_mul_lane. A lane whose
 * function returns 1, a broken invariant, records its index; the flags
 * are an OR, a block's word in shared memory first. */
__global__ __launch_bounds__(256) void k_aug(cft_fmt_desc f, int op, const uint8_t *a,
                                             const uint8_t *b, uint8_t *r, uint8_t *e,
                                             size_t n, size_t first, hacc *acc PLANT_PARAM)
{
    __shared__ unsigned int blk;
    const size_t i = (size_t)blockIdx.x * blockDim.x + threadIdx.x;
    if (threadIdx.x == 0)
        blk = 0;
    __syncthreads();
    if (i < n) {
        cft_bn xa, xb, vr, ve;
        uint32_t fl = 0;
        int bad;
        lane_load(&f, a, i, &xa);
        lane_load(&f, b, i, &xb);
        if (op == CFT_AUG_SUB) {
            if (cft_bn_bit(&xb, f.width - 1))
                cft_bn_clearbit(&xb, f.width - 1);
            else
                cft_bn_setbit(&xb, f.width - 1);
        }
        bad = op == CFT_AUG_MUL ? cft_aug_mul_lane(&f, &xa, &xb, &vr, &ve, &fl)
                                : cft_aug_add_lane(&f, &xa, &xb, &vr, &ve, &fl);
        if (bad) {
            atomicMin(&acc->fail, ((unsigned long long)(first + i) << 8) |
                                      (unsigned long long)CFT_ERR_INTERNAL);
        } else {
#ifdef CFT_HIP_PLANTS
            if ((plant & PL_AUG_SWAP) && first + i == 0) {
                lane_store(&f, r, i, &ve);
                lane_store(&f, e, i, &vr);
            } else
#endif
            {
                lane_store(&f, r, i, &vr);
                lane_store(&f, e, i, &ve);
            }
#ifdef CFT_HIP_PLANTS
            if ((plant & PL_AUG_FLIP) && first + i == 0)
                r[0] ^= 1u;
#endif
            if (fl)
                atomicOr(&blk, (unsigned int)fl);
        }
    }
    __syncthreads();
    if (threadIdx.x == 0 && blk) {
        unsigned int w = blk;
#ifdef CFT_HIP_PLANTS
        if (plant & PL_AUG_FLAGS)
            w &= ~(unsigned int)CFT_SF_OVERFLOW;
#endif
        atomicOr(&acc->flags, w);
    }
}

/* ==== the handle ======================================================== */

constexpr size_t STAGE_MAX = (size_t)64 << 20;    /* bytes, each side */
constexpr size_t POOL_MAX = (size_t)256 << 20;    /* a program's scratch */
constexpr unsigned BLOCK = 256;                   /* threads a block */
constexpr double LAUNCH_SLOW_MS = 250.0;          /* halve the next chunk */
constexpr double LAUNCH_FAST_MS = 62.0;           /* double it */
constexpr size_t PROG_CHUNK_START = 2048;         /* lanes */
constexpr size_t PAGE_BYTES = 256;                /* a resident buffer's page */
constexpr unsigned long long NO_FAIL = ~0ull;

struct HBuf;

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
    uint8_t *src = nullptr;       /* device, `src_bytes`: a program's staged
                                   * indexed sources, whole (prog_impl) */
    size_t src_bytes = 0;
    size_t free_at_open = 0, total = 0;
    size_t prog_chunk = PROG_CHUNK_START;
    hipFuncAttributes fa_run, fa_level, fa_seq, fa_aug;
    bool poisoned = false;
    std::string poison_why;
    size_t page = PAGE_BYTES;     /* CFT_HIP_PAGE in a plant build */
    bool launched = false;        /* this call has had a launch accepted */
#ifdef CFT_HIP_PLANTS
    unsigned plant = 0;
    const char *plant_name = "none";
    size_t chunk = 0;             /* CFT_HIP_CHUNK, or 0 */
    bool fail_fired = false;
    bool fail_fill = false;       /* CFT_HIP_UPLOAD=fail-fill, this call */
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
    if (e == hipSuccess) {
        D.launched = true;        /* from here a resident output may be written */
        return CFT_OK;
    }
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

/* ==== resident buffers (the head says what they keep) ==================== */

enum : uint8_t { PG_STALE = 0, PG_FRESH = 1, PG_DIRTY = 2 };

/* cfth_buffer_create's object: device.c's mirror, and this backend's one
 * device allocation of it with a state a page. */
struct HBuf {
    Dev *D = nullptr;
    uint8_t *host = nullptr;      /* the mirror, device.c's for the buffer's life */
    size_t bytes = 0;
    uint8_t *dmem = nullptr;      /* at the first binding, never resized */
    std::vector<uint8_t> pg;      /* a state a page, made with dmem */
    bool lost = false;
    std::string lost_why;
    std::string why;              /* the last staged binding's reason */
    uint64_t resident_binds = 0, staged_binds = 0;
};

/* The pages [*p0, *p1) that bytes [lo, hi) of B touch, clamped to it. */
void page_span(const HBuf &B, size_t lo, size_t hi, size_t *p0, size_t *p1)
{
    const size_t pg = B.D->page;
    if (hi > B.bytes)
        hi = B.bytes;
    if (lo > hi)
        lo = hi;
    *p0 = lo / pg;
    *p1 = hi > lo ? (hi - 1) / pg + 1 : *p0;
}

size_t page_lo(const HBuf &B, size_t p) { return p * B.D->page; }

size_t page_hi(const HBuf &B, size_t p)
{
    const size_t e = (p + 1) * B.D->page;
    return e < B.bytes ? e : B.bytes;
}

bool any_page(const HBuf &B, size_t p0, size_t p1, uint8_t s)
{
    for (size_t p = p0; p < p1; p++)
        if (B.pg[p] == s)
            return true;
    return false;
}

void set_pages(HBuf &B, size_t p0, size_t p1, uint8_t s) noexcept
{
    if (p1 > p0)
        std::memset(B.pg.data() + p0, s, p1 - p0);
}

/* A LOST buffer's refusal, in the words its loss left. */
int refuse_lost(const HBuf &B)
{
    set_err_or([&] {
        return B.lost_why.empty()
                   ? std::string("a failed run lost this resident buffer's contents; "
                                 "publish them again with cft_buffer_to_device")
                   : B.lost_why;
    }, "buffer lost");
    return CFT_ERR_INTERNAL;
}

/* The STALE pages of [p0, p1) to the device, a run of them at a time
 * through the stage, each run marked FRESH only once its copy has
 * completed: a copy that fails leaves its pages STALE, so the next
 * binding uploads them again (the order verifier-V8 found reversed in
 * the XRT backend, KL-464; fresh-early plants the reversal). Called
 * before any launch of the call, so a failure is the call's, named, and
 * does not poison the handle: nothing of the call ran. */
int up_pages(Dev &D, HBuf &B, const char *who, size_t p0, size_t p1, size_t *moved)
{
    size_t p = p0;
    while (p < p1) {
        if (B.pg[p] != PG_STALE) {
            p++;
            continue;
        }
        size_t q = p + 1;
        while (q < p1 && B.pg[q] == PG_STALE)
            q++;
        const size_t lo = page_lo(B, p), hi = page_hi(B, q - 1);
#ifdef CFT_HIP_PLANTS
        if (D.plant & PL_FRESH_EARLY)
            set_pages(B, p, q, PG_FRESH);
#endif
        for (size_t x = lo; x < hi;) {
            const size_t m = hi - x < D.stage ? hi - x : D.stage;
            std::memcpy(D.host, B.host + x, m);
#ifdef CFT_HIP_PLANTS
            if (D.fail_fill) {
                D.fail_fill = false;
                set_err(fmt_str("%s: the upload of a resident buffer's pages to %s was "
                                "failed on purpose by CFT_HIP_UPLOAD=fail-fill, after the "
                                "host copy and before the device copy - nothing of this "
                                "call ran, and the pages stay stale", who,
                                D.label.c_str()));
                return CFT_ERR_INTERNAL;
            }
#endif
            hipError_t e = hipMemcpyAsync(B.dmem + x, D.host, m, hipMemcpyHostToDevice,
                                          D.stream);
            if (e == hipSuccess)
                e = hipStreamSynchronize(D.stream);
            if (e != hipSuccess) {
                (void)hipGetLastError();
                set_err(fmt_str("%s: uploading a resident buffer's pages to %s failed: "
                                "%s (%s) - before any launch of this call, so nothing ran; "
                                "the pages stay stale and the next binding uploads them "
                                "again", who, D.label.c_str(), hipGetErrorString(e),
                                hipGetErrorName(e)));
                return CFT_ERR_INTERNAL;
            }
            x += m;
        }
        set_pages(B, p, q, PG_FRESH);
        *moved += hi - lo;
        p = q;
    }
    return CFT_OK;
}

/* The DIRTY pages of [p0, p1) home, a run at a time through the stage,
 * each marked FRESH once it is in the mirror. A copy that fails leaves
 * its pages DIRTY and poisons the handle: the device holds the only copy
 * of those results, and a failed copy says its context may be gone. */
int down_pages(Dev &D, HBuf &B, const char *who, size_t p0, size_t p1)
{
    bool copy = true;
#ifdef CFT_HIP_PLANTS
    copy = !(D.plant & PL_NO_READBACK);
#endif
    size_t p = p0;
    while (p < p1) {
        if (B.pg[p] != PG_DIRTY) {
            p++;
            continue;
        }
        size_t q = p + 1;
        while (q < p1 && B.pg[q] == PG_DIRTY)
            q++;
        const size_t lo = page_lo(B, p), hi = page_hi(B, q - 1);
        for (size_t x = lo; copy && x < hi;) {
            const size_t m = hi - x < D.stage ? hi - x : D.stage;
            hipError_t e = hipMemcpyAsync(D.host, B.dmem + x, m, hipMemcpyDeviceToHost,
                                          D.stream);
            if (e == hipSuccess)
                e = hipStreamSynchronize(D.stream);
            if (e != hipSuccess)
                return fail_device(D, who, "reading a resident buffer back (hipMemcpyAsync)",
                                   e);
            std::memcpy(B.host + x, D.host, m);
            x += m;
        }
        set_pages(B, p, q, PG_FRESH);
        p = q;
    }
    return CFT_OK;
}

/* One operand of a call, as device.c resolved it (cft_bindings) and as
 * bind_call then decided. */
struct Role {
    HBuf *B = nullptr;            /* the buffer it is a window of, or nullptr */
    size_t off = 0, len = 0;      /* the window, bytes */
    bool out = false;             /* the call writes it */
    bool keep = false;            /* an output under a lane mask */
    bool alias_ok = false;        /* an output an identical input window may
                                   * share: each lane reads its own input
                                   * before it writes its own output, and no
                                   * other lane touches either */
    bool resident = false;        /* decided: the device window dp */
    uint8_t *dp = nullptr;
    std::string why;              /* decided: staged, and why */
};

void role_from(Role &r, const cft_bindings *bind, int slot, size_t len, bool out,
               bool keep, bool alias_ok)
{
    if (!bind || !bind->buf[slot] || !len)
        return;
    r.B = static_cast<HBuf *>(bind->buf[slot]);
    r.off = bind->off[slot];
    r.len = len;
    r.out = out;
    r.keep = keep;
    r.alias_ok = alias_ok;
}

bool overlap(const Role &x, const Role &y)
{
    return x.B && x.B == y.B && x.off < y.off + y.len && y.off < x.off + x.len;
}

/* Every bound operand of a call, decided before anything of it runs:
 * refused for a LOST buffer; staged where the buffer has no device
 * memory or where two roles would share bytes on the device (the head);
 * resident otherwise, with the STALE pages it reads uploaded. A staged
 * output into a buffer that has device memory first brings home its
 * DIRTY pages and stales them, as a host write does, since the mirror
 * is what it writes. Counted as the XRT backend counts: a binding that
 * moved bytes is staged, with the reason; one that moved none, resident. */
int bind_call(Dev &D, const char *who, Role *R, int nr)
{
    int i, j;
    D.launched = false;
#ifdef CFT_HIP_PLANTS
    D.fail_fill = false;
    {
        const char *u = std::getenv("CFT_HIP_UPLOAD");
        if (u && *u) {
            if (std::strcmp(u, "fail-fill")) {
                set_err(fmt_str("CFT_HIP_UPLOAD=\"%s\": expected fail-fill (a call's "
                                "first resident upload fails after its host copy); unset "
                                "it for none", u));
                return CFT_ERR_INVALID_ARGUMENT;
            }
            D.fail_fill = true;
        }
    }
#endif
    for (i = 0; i < nr; i++) {
        Role &r = R[i];
        if (!r.B)
            continue;
        if (r.B->lost)
            return refuse_lost(*r.B);
        if (r.B->D != &D)
            r.why = "the buffer belongs to another handle";
        else if (r.off > r.B->bytes || r.len > r.B->bytes - r.off)
            r.why = "the window runs past the end of the buffer";
    }
    /* the device memory, at a buffer's first binding */
    for (i = 0; i < nr; i++) {
        Role &r = R[i];
        if (!r.B || !r.why.empty() || r.B->dmem)
            continue;
        HBuf &B = *r.B;
        std::vector<uint8_t> pg;
        std::string why;
        try {
            pg.assign((B.bytes + D.page - 1) / D.page, (uint8_t)PG_STALE);
        } catch (const std::bad_alloc &) {
            why = "no host memory for this buffer's page states - it is staged, as a "
                  "plain host pointer is";
        }
        if (why.empty()) {
            const hipError_t e = hipMalloc((void **)&B.dmem, B.bytes);
            if (e == hipSuccess) {
                B.pg.swap(pg);
                continue;
            }
            B.dmem = nullptr;
            (void)hipGetLastError();
            why = fmt_str("no device memory for this buffer: hipMalloc of %zu bytes on "
                          "%s: %s - it is staged, as a plain host pointer is", B.bytes,
                          D.label.c_str(), hipGetErrorString(e));
        }
        for (j = 0; j < nr; j++)
            if (R[j].B == &B && R[j].why.empty())
                R[j].why = why;
    }
    /* two roles that would share bytes on the device */
    for (i = 0; i < nr; i++)
        for (j = i + 1; j < nr; j++) {
            Role &x = R[i], &y = R[j];
            if (!overlap(x, y) || (!x.out && !y.out))
                continue;
            if (x.out && y.out) {
                static const char both[] =
                    "two outputs of the same call overlap in this buffer, so both are "
                    "staged and written into the mirror in turn, as plain host "
                    "pointers are";
                if (x.why.empty())
                    x.why = both;
                if (y.why.empty())
                    y.why = both;
                continue;
            }
            Role &in = x.out ? y : x;
            const Role &o = x.out ? x : y;
            if (o.alias_ok && in.off == o.off && in.len == o.len)
                continue;
            if (in.why.empty())
                in.why = "an input that overlaps an output of the same call in this "
                         "buffer is staged, so that no lane reads what another writes";
        }
    /* staged outputs into device memory: their pages home and stale */
    for (i = 0; i < nr; i++) {
        Role &r = R[i];
        if (!r.B || !r.out || r.why.empty() || !r.B->dmem)
            continue;
        size_t p0, p1;
        page_span(*r.B, r.off, r.off + r.len, &p0, &p1);
        if (any_page(*r.B, p0, p1, PG_DIRTY)) {
            const int st = down_pages(D, *r.B, who, p0, p1);
            if (st != CFT_OK)
                return st;
        }
        set_pages(*r.B, p0, p1, PG_STALE);
    }
    /* the rest resident, with what each reads uploaded; the staged ones
     * counted last, so that a buffer's `why` names the decline rather
     * than a fill of the same call */
    for (i = 0; i < nr; i++) {
        Role &r = R[i];
        if (!r.B || !r.why.empty())
            continue;
        HBuf &B = *r.B;
        size_t p0, p1, moved = 0;
        int st = CFT_OK;
        page_span(B, r.off, r.off + r.len, &p0, &p1);
        if (!r.out || r.keep) {
            st = up_pages(D, B, who, p0, p1, &moved);
        } else {
            /* an unmasked output: its edge pages, where the window does
             * not cover them, so the bytes beside it stay the caller's */
            if (r.off > page_lo(B, p0) || r.off + r.len < page_hi(B, p0))
                st = up_pages(D, B, who, p0, p0 + 1, &moved);
            if (st == CFT_OK && p1 - 1 > p0 && r.off + r.len < page_hi(B, p1 - 1))
                st = up_pages(D, B, who, p1 - 1, p1, &moved);
        }
        if (st != CFT_OK)
            return st;
        r.resident = true;
        r.dp = B.dmem + r.off;
        if (!moved) {
            B.resident_binds++;
            continue;
        }
        B.staged_binds++;
        B.why = !r.out ? "stale pages of this window (its first use, or published "
                         "since) were uploaded"
              : r.keep ? "an output under a lane mask: its stale pages were uploaded, "
                         "so that its masked lanes stay the caller's"
                       : "an output's stale edge pages were uploaded, so that the bytes "
                         "beside its window stay the caller's";
    }
    for (i = 0; i < nr; i++)
        if (R[i].B && !R[i].why.empty()) {
            R[i].B->staged_binds++;
            R[i].B->why = R[i].why;
        }
    return CFT_OK;
}

/* The end of a call that bound: a good run leaves its resident outputs'
 * pages DIRTY; a failed one that may have written them leaves their
 * buffers LOST (cft.h); a staged output into device memory leaves its
 * pages STALE either way, since the mirror took its bytes. */
void call_end(Dev &D, int st, const Role *R, int nr) noexcept
{
    const bool maybe = st != CFT_OK && (D.launched || D.poisoned);
    for (int i = 0; i < nr; i++) {
        const Role &r = R[i];
        if (!r.B || !r.out || !r.B->dmem)
            continue;
        HBuf &B = *r.B;
        size_t p0, p1;
        page_span(B, r.off, r.off + r.len, &p0, &p1);
        if (!r.resident) {
            set_pages(B, p0, p1, PG_STALE);
        } else if (st == CFT_OK) {
            set_pages(B, p0, p1, PG_DIRTY);
        } else if (maybe && !B.lost) {
            B.lost = true;
            try {
                B.lost_why = fmt_str("a run that wrote this resident buffer failed on "
                                     "the device (%s: %.200s), so what the GPU left in "
                                     "it is not known - publish its contents again with "
                                     "cft_buffer_to_device before reading it back or "
                                     "running on it", cft_strerror((cft_status)st),
                                     g_err.c_str());
            } catch (...) {
            }
        }
    }
    D.launched = false;
}

/* ==== the elementwise run =============================================== */

/* R[0..3] are a, b, c and d as bind_call decided them: a resident one is
 * read or written at its device window, the rest staged as before. The
 * chunk is the staged run's whatever is resident, so no launch is longer
 * than the staged one. */
int run_impl(Dev &D, int op, int fmt, int rnd, const void *a, const void *b,
             const void *c, void *d, size_t n, uint32_t scal, const Role *R,
             uint32_t *flags)
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
             * an earlier one wrote. (The software loop re-reads it.) A
             * resident scalar is read on the device, and is resident
             * only where d's window does not overlap it (bind_call). */
            if (!R[r].resident) {
                std::memcpy(snap[r], opnd[r], esz);
                opnd[r] = snap[r];
            }
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
        const uint8_t *dv[3];
        size_t o = 0, oacc, od;
        int st;
        for (r = 0; r < 3; r++) {
            const bool sc = (scal >> r) & 1u;
            dv[r] = nullptr;
            if (!opnd[r])
                continue;
            if (R[r].resident) {
                dv[r] = R[r].dp + (sc ? 0 : s * esz);
                continue;
            }
            const size_t bytes = sc ? esz : m * esz;
            std::memcpy(D.host + o, sc ? opnd[r] : opnd[r] + s * esz, bytes);
            dv[r] = D.dev + o;
            o = al(o + bytes);
        }
        oacc = o;
        acc_init(D, oacc);
        od = al(oacc + sizeof(hacc));
        if ((st = h2d(D, who, 0, oacc + sizeof(hacc))) != CFT_OK)
            return st;
        k_run<<<grid_for(m), BLOCK, 0, D.stream>>>(
            f, op, rnd, dv[0], dv[1], dv[2], R[3].resident ? R[3].dp + s * esz : D.dev + od,
            m, scal, s, (hacc *)(D.dev + oacc) PLANT_ARG(D));
        if ((st = check_launch(D, who, "the elementwise kernel", D.fa_run)) != CFT_OK)
            return st;
        if ((st = d2h(D, who, oacc, R[3].resident ? sizeof(hacc)
                                                  : od - oacc + m * esz)) != CFT_OK ||
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
        if (!R[3].resident)
            std::memcpy((uint8_t *)d + s * esz, D.host + od, m * esz);
    }
    *flags = fl;
    return CFT_OK;
}

/* ==== the API's augmented calls ========================================= */

/* R[0..3] are a, b, r and e as bind_call decided them: a resident one is
 * read or written at its device window, the rest staged. The chunk is a
 * staged call's whatever is resident, as run_impl's is. Staged outputs
 * come back r first, then e, the order the host's loop writes them. */
int aug_impl(Dev &D, const char *who, int op, int fmt, const void *a, const void *b,
             void *r, void *e, size_t n, const Role *R, uint32_t *flags)
{
    const cft_fmt_desc f = cft_sf_formats[fmt];
    const size_t esz = (size_t)f.width / 8;
    const size_t fixed = 5 * 256 + sizeof(hacc), per = 4 * esz;
    const uint8_t *in[2] = {(const uint8_t *)a, (const uint8_t *)b};
    uint8_t *out[2] = {(uint8_t *)r, (uint8_t *)e};
    uint32_t fl = 0;
    size_t k, s;
    if (D.stage <= fixed + per)
        return fail_alloc(D, who, "the stage", fixed + per, hipErrorOutOfMemory);
    k = (D.stage - fixed) / per;
#ifdef CFT_HIP_PLANTS
    if (D.chunk && D.chunk < k)
        k = D.chunk;
#endif
    for (s = 0; s < n; s += k) {
        const size_t m = n - s < k ? n - s : k;
        const uint8_t *dv[2];
        uint8_t *dq[2];
        size_t o = 0, oacc, oq[2];
        int st, q;
        for (q = 0; q < 2; q++) {               /* a and b */
            if (R[q].resident) {
                dv[q] = R[q].dp + s * esz;
                continue;
            }
            std::memcpy(D.host + o, in[q] + s * esz, m * esz);
            dv[q] = D.dev + o;
            o = al(o + m * esz);
        }
        oacc = o;
        acc_init(D, oacc);
        o = al(oacc + sizeof(hacc));
        for (q = 0; q < 2; q++) {               /* r and e */
            oq[q] = o;
            if (R[2 + q].resident) {
                dq[q] = R[2 + q].dp + s * esz;
                continue;
            }
            dq[q] = D.dev + o;
            o = al(o + m * esz);
        }
        if ((st = h2d(D, who, 0, oacc + sizeof(hacc))) != CFT_OK)
            return st;
        k_aug<<<grid_for(m), BLOCK, 0, D.stream>>>(f, op, dv[0], dv[1], dq[0], dq[1], m, s,
                                                    (hacc *)(D.dev + oacc) PLANT_ARG(D));
        if ((st = check_launch(D, who, "the augmented kernel", D.fa_aug)) != CFT_OK)
            return st;
        if ((st = d2h(D, who, oacc, o - oacc)) != CFT_OK || (st = finish(D, who)) != CFT_OK)
            return st;
        const hacc h = acc_read(D, oacc);
        if (h.fail != NO_FAIL) {
            set_err(fmt_str("%s: element %llu broke an invariant of augmented.c's lane "
                            "functions on %s - a defect in libcft, not in the call", who,
                            (unsigned long long)(h.fail >> 8), D.label.c_str()));
            return CFT_ERR_INTERNAL;
        }
        fl |= h.flags;
        for (q = 0; q < 2; q++)
            if (!R[2 + q].resident)
                std::memcpy(out[q] + s * esz, D.host + oq[q], m * esz);
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

/* nseg segments of m >= 2 elements each, from host `src` - or, when the
 * input is resident, from its device window `dsrc`, which the first
 * level reads in place - to nseg results at host `dst`: levels until one
 * element a segment is left. */
int reduce_on_device(Dev &D, const char *who, const cft_fmt_desc &f, int op, int rnd,
                     const uint8_t *src, const uint8_t *dsrc, size_t m, size_t nseg,
                     uint8_t *dst, uint32_t *fl)
{
    const size_t esz = (size_t)f.width / 8, h1 = (m + 1) / 2;
    /* staged: the input, then the first level's output; resident: the
     * first level's output and the second's, which the levels after
     * them take in turn */
    const size_t x = al(sizeof(hacc)), xb = nseg * (dsrc ? h1 : m) * esz;
    const size_t y = al(x + xb), yb = nseg * (dsrc ? (h1 + 1) / 2 : h1) * esz;
    const uint8_t *in = dsrc ? dsrc : D.dev + x;
    size_t outo = dsrc ? x : y, other = dsrc ? y : x, len = m;
    int st;

    if (y + yb > D.stage)
        return fail_alloc(D, who, "the reduction's stage", y + yb, hipErrorOutOfMemory);
    acc_init(D, 0);
    if (!dsrc)
        std::memcpy(D.host + x, src, xb);
    if ((st = h2d(D, who, 0, dsrc ? sizeof(hacc) : x + xb)) != CFT_OK)
        return st;
    while (len > 1) {
        const size_t h = (len + 1) / 2;
        k_level<<<grid_for(nseg * h), BLOCK, 0, D.stream>>>(
            f, op, rnd, in, D.dev + outo, len, nseg, (hacc *)D.dev PLANT_ARG(D));
        if ((st = check_launch(D, who, "the reduction's level kernel", D.fa_level)) != CFT_OK)
            return st;
        in = D.dev + outo;
        const size_t t = outo;
        outo = other;
        other = t;
        len = h;
    }
    const size_t cur = (size_t)(in - D.dev);
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
 * their partials has the same shape. `dsrc` is the range's device window
 * when the input is resident, or nullptr; a leaf is read from the host
 * mirror either way, which device.c has brought home before the call. */
int reduce_range(Dev &D, const char *who, const cft_fmt_desc &f, int op, int rnd,
                 const uint8_t *src, const uint8_t *dsrc, size_t len, uint8_t *dst,
                 uint32_t *fl)
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
        return reduce_on_device(D, who, f, op, rnd, src, dsrc, len, 1, dst, fl);
    const size_t parts = (len + cap - 1) / cap;
    std::vector<uint8_t> part(parts * esz);
    for (size_t j = 0; j < parts; j++) {
        const size_t lo = j * cap, l = len - lo < cap ? len - lo : cap;
        const int st = reduce_range(D, who, f, op, rnd, src + lo * esz,
                                    dsrc ? dsrc + lo * esz : nullptr, l,
                                    part.data() + j * esz, fl);
        if (st != CFT_OK)
            return st;
    }
    return reduce_range(D, who, f, op, rnd, part.data(), nullptr, parts, dst, fl);
}

/* ==== the sequencer ===================================================== */

#ifdef CFT_HIP_PLANTS
/* A plant build's instrument (no plant needs to be set): the last program
 * run's shape - its lanes, the budget that cut them, and what each launch
 * carried - for cfth_plant_prog_probe, which a bench reads after the run.
 * A default build has none of it. */
struct ProgProbe {
    uint64_t n, esz, reach, lane_pool, pool_cap, stage, head, lane_in, lane_out,
        kmax, chunk0, launches, max_launch, min_launch, src_bytes, free_at_open;
};
ProgProbe g_probe;

/* round 2's G2C's plants act on a whole-operation run: a BANK_EXT program
 * of 42 or more constants (divfull's 42, sqrtfull's 49) - with two
 * deposits a lane, its result and its flag word, for the two that touch
 * its bank or its words */
bool plant_whole(const cft_program &p, bool two_deposits)
{
    return (p.flags & CFT_PROG_FLAG_BANK_EXT) && p.n_consts >= 42 &&
           (!two_deposits || p.max_deposits == 2);
}
#endif

/* One staged indexed source, WHOLE, into the handle's source buffer: a
 * piece the stage's size at a time through the pinned block, each piece
 * finished before the next, so the block is free again when the head goes
 * into it. Before any launch of the call, so a failure is the call's,
 * named, and does not poison the handle (up_pages' rule). `keep` is the
 * bytes to copy: all of them, but for the src-trunc plant. */
int up_source(Dev &D, const char *who, uint8_t *dst, const uint8_t *src, size_t bytes,
              size_t keep)
{
    for (size_t x = 0; x < keep;) {
        const size_t m = keep - x < D.stage ? keep - x : D.stage;
        std::memcpy(D.host, src + x, m);
        hipError_t e = hipMemcpyAsync(dst + x, D.host, m, hipMemcpyHostToDevice, D.stream);
        if (e == hipSuccess)
            e = hipStreamSynchronize(D.stream);
        if (e != hipSuccess) {
            (void)hipGetLastError();
            set_err(fmt_str("%s: uploading an indexed source to %s failed: %s (%s) - "
                            "before any launch of this call, so nothing ran", who,
                            D.label.c_str(), hipGetErrorString(e), hipGetErrorName(e)));
            return CFT_ERR_INTERNAL;
        }
        x += m;
    }
    if (keep < bytes) {                   /* the src-trunc plant's 0xA5 */
        hipError_t e = hipMemsetAsync(dst + keep, 0xA5, bytes - keep, D.stream);
        if (e == hipSuccess)
            e = hipStreamSynchronize(D.stream);
        if (e != hipSuccess)
            return fail_device(D, who, "the src-trunc plant's fill", e);
    }
    return CFT_OK;
}

/* A staged table's window into the stage at `o` (256-aligned, so the
 * entries are aligned); the idx-none plant rewrites its sentinels. */
void put_tab(Dev &D, size_t o, const uint32_t *t, size_t entries)
{
    std::memcpy(D.host + o, t, entries * 4u);
#ifdef CFT_HIP_PLANTS
    if (D.plant & PL_IDX_NONE) {
        uint32_t *w = (uint32_t *)(D.host + o);
        for (size_t e = 0; e < entries; e++)
            if (w[e] == CFT_IDX_NONE)
                w[e] = 0;
    }
#endif
}

/* R[0..5] are a, b, c, the deposits, scratch-in and scratch-out as
 * bind_call decided them, and R[6..9] the four index tables; the mask,
 * the counts, the lane bytes, the bank and the instructions are staged
 * always.
 *
 * An index table (R16, ABI 0.14) makes its stream - or the scratch block
 * - a SOURCE the table indexes: idx_*_src elements (scratch_in_bytes, the
 * pool, for the block), any of which any lane may read. So the lanes are
 * cut into chunks as before and the sources are NOT: a staged source goes
 * up whole, once a call, into the handle's source buffer (D.src, grown
 * on demand as the pool is, and freed at close), and a resident one is
 * read in place at its whole window (bind_call uploaded what was stale).
 * A chunk's kernel gets each source whole and ITS window of each table -
 * entries [first, first + k) of a stream's, [first * nsi, (first + k) *
 * nsi) of the block's - because seq_lanes_in indexes a table by the lane
 * (seq_exec.h), and a table cut any other way is the trap R16 names: a
 * plausible neighbour's element, read with no assertion to catch it. A
 * table rides the stage with its chunk, four bytes an entry, or is read
 * at its bound window. A source the device cannot hold is refused by
 * name, with its bytes, before anything runs; never cut short. */
int prog_impl(Dev &D, int fmt, const cft_seq_run_io *io, uint32_t max_deposits,
              const void *a, const void *b, const void *c, void *deposits,
              uint32_t *counts, size_t n, const Role *R, uint32_t *flags, uint32_t *bus)
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
    /* The tables' shapes were held by program.c before this call
     * (seq_check_round2: a table on a NULL stream, a zero source length, a
     * scratch table with no pool, every index at or past its source - each
     * refused by name), so what reaches here is well formed: a defence,
     * not a check the run relies on. */
    {
        const void *const strm[3] = {a, b, c};
        const uint32_t *const tab[3] = {io->idx_a, io->idx_b, io->idx_c};
        const size_t srcn[3] = {io->idx_a_src, io->idx_b_src, io->idx_c_src};
        bool bad = io->idx_scratch_in && (!io->scratch_in || !io->n_scratch_in ||
                                          !io->idx_scratch_src);
        for (int r = 0; r < 3; r++)
            bad = bad || (tab[r] && (!strm[r] || !srcn[r]));
        if (bad) {
            set_err("cft_program_run_ex: an index table reached the GPU backend with "
                    "no source to read, which program.c refuses by name first - a "
                    "defect in libcft, not in the call");
            return CFT_ERR_INTERNAL;
        }
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
    /* the four tables, or none: a stream with one is its whole source */
    const bool ia = io->idx_a != nullptr, ib = b && io->idx_b, ic = c && io->idx_c;
    const bool isi = nsi && io->idx_scratch_in;
    const size_t ntab = (ia ? 1 : 0) + (ib ? 1 : 0) + (ic ? 1 : 0) + (isi ? 1 : 0);
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
#ifdef CFT_HIP_PLANTS
        /* bank-mode: the last five words, the attribute's slots, rotated
         * by one - slot r's word into slot r + 1, the last into the first */
        if ((D.plant & PL_BANK_MODE) && plant_whole(prog, true)) {
            const cft_bn last = bank[nk - 1];
            for (size_t q = nk - 1; q > nk - 5; q--)
                bank[q] = bank[q - 1];
            bank[nk - 5] = last;
        }
#endif
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
    /* a lane's staged bytes: an element of each dense stream and of its
     * scratch block, four bytes an entry of each table in their place */
    const size_t lane_in = esz * ((ia ? 0 : 1) + (b && !ib ? 1 : 0) + (c && !ic ? 1 : 0) +
                                  (isi ? 0 : nsi)) +
                           4 * ((ia ? 1 : 0) + (ib ? 1 : 0) + (ic ? 1 : 0) +
                                (isi ? nsi : 0)) + (mask ? 1 : 0);
    const size_t lane_out = esz * (md + nso) + (counts ? 4 : 0) + (lflags ? 1 : 0);
    const size_t slack = (10 + ntab) * 256 + sizeof(hacc);
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

    /* The indexed sources, whole, once a call (this section's head says
     * why): a resident one where bind_call left it, a staged one into
     * D.src through the stage - before the head goes into the stage. */
    const uint8_t *srcp[4] = {nullptr, nullptr, nullptr, nullptr};  /* a, b, c, pool */
#ifdef CFT_HIP_PLANTS
    size_t src_up = 0;
#endif
    if (ntab) {
        const bool tab[4] = {ia, ib, ic, isi};
        const void *const hsrc[4] = {a, b, c, io->scratch_in};
        const size_t sb[4] = {io->idx_a_src * esz, io->idx_b_src * esz,
                              io->idx_c_src * esz, io->scratch_in_bytes};
        const int role[4] = {0, 1, 2, 4};
        size_t off[4] = {0, 0, 0, 0}, stg[4] = {0, 0, 0, 0}, total = 0;
        for (int s = 0; s < 4; s++) {
            if (!tab[s] || R[role[s]].resident)
                continue;
            off[s] = total;
            stg[s] = sb[s];
            total = al(total + sb[s]);
        }
        if (total > D.src_bytes) {
            if (D.src) {
                (void)hipFree(D.src);
                D.src = nullptr;
                D.src_bytes = 0;
            }
            const hipError_t e = hipMalloc((void **)&D.src, total);
            if (e != hipSuccess) {
                D.src = nullptr;
                if (e != hipErrorOutOfMemory)
                    return fail_device(D, who, "hipMalloc of the indexed sources", e);
                (void)hipGetLastError();
                set_err(fmt_str("%s: this run's staged indexed sources need %zu bytes of "
                                "device memory on %s - each source whole, since an index "
                                "reaches anywhere in it: a %zu, b %zu, c %zu and the "
                                "scratch pool %zu bytes - and hipMalloc refused them: %s. "
                                "The device had %zu of %zu bytes free at open, beside this "
                                "handle's %zu-byte stage and %zu-byte scratch pool; a "
                                "resident source (cft_alloc) is read in place, and a "
                                "shorter source or a free device would answer", who, total,
                                D.label.c_str(), stg[0], stg[1], stg[2], stg[3],
                                hipGetErrorString(e), D.free_at_open, D.total, D.stage,
                                D.pool_bytes));
                return CFT_ERR_OUT_OF_MEMORY;
            }
            D.src_bytes = total;
        }
        for (int s = 0; s < 4; s++) {
            if (!tab[s])
                continue;
            if (R[role[s]].resident) {
                srcp[s] = R[role[s]].dp;
                continue;
            }
            size_t keep = sb[s];
#ifdef CFT_HIP_PLANTS
            if ((D.plant & PL_SRC_TRUNC) && s < 3 && n * esz < keep)
                keep = n * esz;
#endif
            if ((st = up_source(D, who, D.src + off[s], (const uint8_t *)hsrc[s], sb[s],
                                keep)) != CFT_OK)
                return st;
            srcp[s] = D.src + off[s];
#ifdef CFT_HIP_PLANTS
            src_up += keep;
#endif
        }
    }

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
#ifdef CFT_HIP_PLANTS
    if ((D.plant & PL_DEPTH_CLAMP) && P.scratch_depth > 256u) {
        P.scratch_depth = 256u;    /* the kernel's copy only: the host's */
        P.scratch_log2 = 8;        /* program, and the reach, as they were */
    }
    const size_t chunk0 = chunk;
    uint64_t pr_launches = 0, pr_max = 0, pr_min = 0;
#endif

    /* which of the ten are resident (bind_call): the stage carries the rest */
    const bool ra = R[0].resident, rb = b && R[1].resident, rc = c && R[2].resident;
    const bool rd = md && R[3].resident, rsi = nsi && R[4].resident;
    const bool rso = nso && R[5].resident;
    const bool ria = ia && R[6].resident, rib = ib && R[7].resident;
    const bool ric = ic && R[8].resident, risi = isi && R[9].resident;
    uint32_t fl = 0, rep = 0;
    for (size_t first = 0; first < n;) {
        const size_t k = n - first < chunk ? n - first : chunk;
        /* this chunk's window of each table: entries from lane `first`
         * (idx-chunk plants R16's trap, every chunk the first window) */
        size_t tf = first;
#ifdef CFT_HIP_PLANTS
        if (D.plant & PL_IDX_CHUNK)
            tf = 0;
#endif
        size_t o = head;
        const size_t o_a = o;  if (!ia && !ra) o = al(o + k * esz);
        const size_t o_b = o;  if (b && !ib && !rb) o = al(o + k * esz);
        const size_t o_c = o;  if (c && !ic && !rc) o = al(o + k * esz);
        const size_t o_m = o;  if (mask) o = al(o + (k + 7) / 8);
        const size_t o_si = o; if (nsi && !isi && !rsi) o = al(o + k * nsi * esz);
        const size_t o_ia = o; if (ia && !ria) o = al(o + k * 4);
        const size_t o_ib = o; if (ib && !rib) o = al(o + k * 4);
        const size_t o_ic = o; if (ic && !ric) o = al(o + k * 4);
        const size_t o_isi = o; if (isi && !risi) o = al(o + k * nsi * 4);
        const size_t o_acc = o; o = al(o + sizeof(hacc));
        const size_t o_dep = o; if (md && !rd) o = al(o + k * md * esz);
        const size_t o_cnt = o; if (counts) o = al(o + k * 4);
        const size_t o_lf = o;  if (lflags) o = al(o + k);
        const size_t o_so = o;  if (nso && !rso) o = al(o + k * nso * esz);
        const size_t end = o;
        bool up_out = mask != nullptr;

        if (!ia && !ra)
            std::memcpy(D.host + o_a, (const uint8_t *)a + first * esz, k * esz);
        if (b && !ib && !rb)
            std::memcpy(D.host + o_b, (const uint8_t *)b + first * esz, k * esz);
        if (c && !ic && !rc)
            std::memcpy(D.host + o_c, (const uint8_t *)c + first * esz, k * esz);
        if (mask) std::memcpy(D.host + o_m, mask + first / 8, (k + 7) / 8);
        if (nsi && !isi && !rsi)
            std::memcpy(D.host + o_si, (const uint8_t *)io->scratch_in + first * nsi * esz,
                        k * nsi * esz);
        if (ia && !ria) put_tab(D, o_ia, io->idx_a + tf, k);
        if (ib && !rib) put_tab(D, o_ib, io->idx_b + tf, k);
        if (ic && !ric) put_tab(D, o_ic, io->idx_c + tf, k);
        if (isi && !risi) put_tab(D, o_isi, io->idx_scratch_in + tf * nsi, k * nsi);
        acc_init(D, o_acc);
        if (mask) {
            /* OUTPUTS UNDER A MASK GO UP FIRST: the executor leaves a masked
             * lane's deposits, count, lane byte and scratch-out alone, so
             * the window it leaves must hold the caller's bytes, or the copy
             * back would hand the caller device garbage for them. (A
             * resident one's pages went up at its binding.) */
            if (md && !rd)
                std::memcpy(D.host + o_dep, (uint8_t *)deposits + first * md * esz,
                            k * md * esz);
            if (counts) std::memcpy(D.host + o_cnt, counts + first, k * 4);
            if (lflags) std::memcpy(D.host + o_lf, lflags + first, k);
            if (nso && !rso)
                std::memcpy(D.host + o_so, (uint8_t *)io->scratch_out + first * nso * esz,
                            k * nso * esz);
        }
#ifdef CFT_HIP_PLANTS
        if ((D.plant & PL_SEQ_DEPOSIT) && md && !mask) {
            if (rd) {
                const hipError_t e = hipMemsetAsync(R[3].dp + first * md * esz, 0xA5,
                                                    k * md * esz, D.stream);
                if (e != hipSuccess)
                    return fail_device(D, who, "the seq-deposit plant's fill", e);
            } else {
                std::memset(D.host + o_dep, 0xA5, k * md * esz);
                up_out = true;
            }
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
        /* a stream with a table is its source, WHOLE - never a chunk of it */
        A.a = ia ? srcp[0] : ra ? R[0].dp + first * esz : D.dev + o_a;
        A.b = b ? (ib ? srcp[1] : rb ? R[1].dp + first * esz : D.dev + o_b) : nullptr;
        A.c = c ? (ic ? srcp[2] : rc ? R[2].dp + first * esz : D.dev + o_c) : nullptr;
        A.n = k;
        A.scratch_in = nsi ? (isi ? srcp[3] : rsi ? R[4].dp + first * nsi * esz
                                                  : D.dev + o_si) : nullptr;
        A.scratch_in_bytes = isi ? io->scratch_in_bytes : k * nsi * esz;
        A.idx_a = !ia ? nullptr : ria ? (const uint32_t *)R[6].dp + tf
                                      : (const uint32_t *)(D.dev + o_ia);
        A.idx_b = !ib ? nullptr : rib ? (const uint32_t *)R[7].dp + tf
                                      : (const uint32_t *)(D.dev + o_ib);
        A.idx_c = !ic ? nullptr : ric ? (const uint32_t *)R[8].dp + tf
                                      : (const uint32_t *)(D.dev + o_ic);
        A.idx_scratch_in = !isi ? nullptr : risi ? (const uint32_t *)R[9].dp + tf * nsi
                                                 : (const uint32_t *)(D.dev + o_isi);
        A.idx_a_src = ia ? io->idx_a_src : 0;
        A.idx_b_src = ib ? io->idx_b_src : 0;
        A.idx_c_src = ic ? io->idx_c_src : 0;
        A.idx_scratch_src = isi ? io->idx_scratch_src : 0;
        A.scratch_out = nso ? (rso ? R[5].dp + first * nso * esz : D.dev + o_so) : nullptr;
        A.scratch_out_bytes = k * nso * esz;
        A.deposits = md ? (rd ? R[3].dp + first * md * esz : D.dev + o_dep) : nullptr;
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
#ifdef CFT_HIP_PLANTS
        pr_launches++;
        if (k > pr_max)
            pr_max = k;
        if (!pr_min || k < pr_min)
            pr_min = k;
#endif
        if (md && !rd)
            std::memcpy((uint8_t *)deposits + first * md * esz, D.host + o_dep,
                        k * md * esz);
        if (counts) std::memcpy(counts + first, D.host + o_cnt, k * 4);
        if (lflags) std::memcpy(lflags + first, D.host + o_lf, k);
        if (nso && !rso)
            std::memcpy((uint8_t *)io->scratch_out + first * nso * esz, D.host + o_so,
                        k * nso * esz);
#ifdef CFT_HIP_PLANTS
        /* full-flag: after the run, lane 0's flag word (deposit 1, its low
         * byte) loses INEXACT - in the caller's copy, or on the device */
        if ((D.plant & PL_FULL_FLAG) && first == 0 && md == 2 && plant_whole(prog, true)) {
            if (!rd) {
                ((uint8_t *)deposits)[esz] &= (uint8_t)~CFT_SF_INEXACT;
            } else {
                uint8_t w = 0;
                hipError_t e = hipMemcpyAsync(&w, R[3].dp + esz, 1, hipMemcpyDeviceToHost,
                                              D.stream);
                if (e == hipSuccess)
                    e = hipStreamSynchronize(D.stream);
                w &= (uint8_t)~CFT_SF_INEXACT;
                if (e == hipSuccess)
                    e = hipMemcpyAsync(R[3].dp + esz, &w, 1, hipMemcpyHostToDevice, D.stream);
                if (e == hipSuccess)
                    e = hipStreamSynchronize(D.stream);
                if (e != hipSuccess)
                    return fail_device(D, who, "the full-flag plant's write", e);
            }
        }
#endif
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
#ifdef CFT_HIP_PLANTS
    g_probe = ProgProbe{n, esz, reach, lane_pool, D.pool_cap, D.stage, head, lane_in,
                        lane_out, kmax, chunk0, pr_launches, pr_max, pr_min, src_up,
                        D.free_at_open};
#endif
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
    {"stale-publish", PL_STALE_PUBLISH},
    {"no-readback", PL_NO_READBACK},
    {"fresh-early", PL_FRESH_EARLY},
    /* round 2's G2A: its plants here */
    {"aug-flip", PL_AUG_FLIP},
    {"aug-flags", PL_AUG_FLAGS},
    {"aug-swap", PL_AUG_SWAP},
    {"seq-aug", PL_SEQ_AUG},
    /* round 2's G2B: its plants here */
    {"idx-chunk", PL_IDX_CHUNK},
    {"idx-none", PL_IDX_NONE},
    {"src-trunc", PL_SRC_TRUNC},
    {"depth-clamp", PL_DEPTH_CLAMP},
    /* round 2's G2C: its plants here */
    {"bank-mode", PL_BANK_MODE},
    {"full-flag", PL_FULL_FLAG},
    {"full-refuse", PL_FULL_REFUSE},
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
    const char *pv = std::getenv("CFT_HIP_PAGE");
    if (pv && *pv) {
        bool ok = true;
        unsigned long long x = 0;
        for (const char *p = pv; *p; p++) {
            if (*p < '0' || *p > '9' || x > (1ull << 20)) {
                ok = false;
                break;
            }
            x = x * 10 + (unsigned)(*p - '0');
        }
        if (!ok || x < 32 || x > (1ull << 20) || (x & (x - 1))) {
            set_err(fmt_str("CFT_HIP_PAGE=\"%s\": expected a power of two in decimal "
                            "from 32 to 1048576 (bytes, a resident buffer's page); unset "
                            "it for the default %zu", pv, PAGE_BYTES));
            return CFT_ERR_INVALID_ARGUMENT;
        }
        D.page = (size_t)x;
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
    if (D->src)
        (void)hipFree(D->src);
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
    const hipError_t e4 = hipFuncGetAttributes(&D->fa_aug, (const void *)k_aug);
    if (e1 != hipSuccess || e2 != hipSuccess || e3 != hipSuccess || e4 != hipSuccess) {
        const hipError_t eb = e1 != hipSuccess ? e1 : e2 != hipSuccess ? e2
                            : e3 != hipSuccess ? e3 : e4;
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
                         " stage %zu MiB, page %zu bytes, kernels %d/%d/%d/%d registers "
                         "and %zu/%zu/%zu/%zu bytes local a thread (run/level/seq/aug)%s%s\n",
                         artifact, D->prop.name, arch_of(D->prop).c_str(),
                         D->prop.multiProcessorCount, (unsigned)D->prop.pciDomainID,
                         (unsigned)D->prop.pciBusID, (unsigned)D->prop.pciDeviceID,
                         (size_t)(D->prop.totalGlobalMem >> 20), platform_name(), rtv,
                         drv, count, vis ? ", CUDA_VISIBLE_DEVICES=" : "",
                         vis ? vis : "", hvis ? ", HIP_VISIBLE_DEVICES=" : "",
                         hvis ? hvis : "", CFT_HIP_ARCH, D->stage >> 20, D->page,
                         D->fa_run.numRegs, D->fa_level.numRegs, D->fa_seq.numRegs,
                         D->fa_aug.numRegs, (size_t)D->fa_run.localSizeBytes,
                         (size_t)D->fa_level.localSizeBytes,
                         (size_t)D->fa_seq.localSizeBytes,
                         (size_t)D->fa_aug.localSizeBytes,
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
     * too). Since round 2 that is every feature the software handle
     * publishes: index tables (G2B) and augmentedAddition (G2A) run here
     * as well. */
    cft_sw_seq_caps(seq);
    seq->features |= CFT_SEQ_FEAT_SCALAR | CFT_FEAT_REDUCE_SEG;
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

/* ---- resident buffers (backend.h's seam; the head says what is kept) ---- */

namespace {

/* A DIRTY page's bytes outside [lo, hi), home, for a host write over the
 * rest of it - quietly: cfth_buffer_host_wrote cannot fail and must leave
 * the call's sentence alone. False when it could not be done. */
bool home_outside(HBuf &B, size_t p, size_t lo, size_t hi) noexcept
{
    Dev &D = *B.D;
    const size_t a = page_lo(B, p), z = page_hi(B, p);
    if (D.poisoned || hipSetDevice(D.ordinal) != hipSuccess)
        return false;
    hipError_t e = hipMemcpyAsync(D.host, B.dmem + a, z - a, hipMemcpyDeviceToHost,
                                  D.stream);
    if (e == hipSuccess)
        e = hipStreamSynchronize(D.stream);
    if (e != hipSuccess) {
        try {
            poison(D, fmt_str("a read-back beside a host write (hipMemcpyAsync) "
                              "failed: %s (%s)", hipGetErrorString(e),
                              hipGetErrorName(e)));
        } catch (...) {
            D.poisoned = true;
        }
        return false;
    }
    if (lo > a)                   /* before the write */
        std::memcpy(B.host + a, D.host, (lo < z ? lo : z) - a);
    if (hi < z) {                 /* after it */
        const size_t s = hi > a ? hi : a;
        std::memcpy(B.host + s, D.host + (s - a), z - s);
    }
    return true;
}

/* [off, off + len) of B, clamped to it. */
void clamp(const HBuf &B, size_t off, size_t len, size_t *lo, size_t *hi)
{
    *lo = off < B.bytes ? off : B.bytes;
    *hi = len < B.bytes - *lo ? *lo + len : B.bytes;
}

}  // namespace

extern "C" int cfth_buffer_create(void *hw, void *host, size_t bytes, void **out)
{
    if (out)
        *out = nullptr;
    if (!hw || !host || !bytes || !out)
        return CFT_ERR_INVALID_ARGUMENT;
    HBuf *B = new (std::nothrow) HBuf();
    if (!B)
        return CFT_ERR_OUT_OF_MEMORY;
    B->D = static_cast<Dev *>(hw);
    B->host = static_cast<uint8_t *>(host);
    B->bytes = bytes;
    *out = B;                     /* no device memory until a call binds it */
    return CFT_OK;
}

extern "C" void cfth_buffer_destroy(void *buf)
{
    /* Whatever a run wrote and nobody read back goes with it, which is
     * what cft_buffer_free means and what cft.h says. */
    HBuf *B = static_cast<HBuf *>(buf);
    if (!B)
        return;
    if (B->dmem) {
        (void)hipSetDevice(B->D->ordinal);
        (void)hipFree(B->dmem);
        (void)hipGetLastError();
    }
    delete B;
}

extern "C" int cfth_buffer_to_device(void *buf)
{
    g_err.clear();
    if (!buf)
        return CFT_ERR_INVALID_ARGUMENT;
    HBuf &B = *static_cast<HBuf *>(buf);
    return at_boundary("publishing a resident buffer", [&]() -> int {
        if (!B.dmem)
            return CFT_OK;        /* no device memory: nothing to stale */
        /* A buffer a failed run LOST: the caller is supplying its
         * contents, so what the device holds is dropped and the loss is
         * cleared. Nothing moves. */
        if (B.lost) {
            set_pages(B, 0, B.pg.size(), PG_STALE);
            B.lost = false;
            B.lost_why.clear();
            return CFT_OK;
        }
        /* A run's results on the device and never read back: REFUSED,
         * nothing changed (Logan's rule, 2026-09-26; backend_xrt.cpp says
         * why neither guess is safe). */
        if (any_page(B, 0, B.pg.size(), PG_DIRTY)) {
            set_err("cft_buffer_to_device: a run's results in this buffer are still "
                    "on the device and were never read back, so whether the host copy "
                    "was written since cannot be known and publishing could keep the "
                    "wrong bytes - read it back first (cft_buffer_from_device keeps "
                    "the run's results), then write and publish; nothing was changed "
                    "(docs/HOSTAPI.md)");
            return CFT_ERR_INVALID_ARGUMENT;
        }
#ifdef CFT_HIP_PLANTS
        if (B.D->plant & PL_STALE_PUBLISH)
            return CFT_OK;        /* the plant: the pages left as they were */
#endif
        /* The mirror is the truth from here: every page is stale and
         * goes up at its next binding. Nothing moves. */
        set_pages(B, 0, B.pg.size(), PG_STALE);
        return CFT_OK;
    });
}

extern "C" int cfth_buffer_from_device(void *buf)
{
    g_err.clear();
    if (!buf)
        return CFT_ERR_INVALID_ARGUMENT;
    HBuf &B = *static_cast<HBuf *>(buf);
    return at_boundary("reading a resident buffer back", [&]() -> int {
        static const char who[] = "cft_buffer_from_device";
        if (B.lost)
            return refuse_lost(B);
        /* nothing a run wrote: nothing moves, so a caller who reads back
         * after every run - the right thing to do - pays for none */
        if (!B.dmem || !any_page(B, 0, B.pg.size(), PG_DIRTY))
            return CFT_OK;
        const int st = enter(*B.D, who);
        return st != CFT_OK ? st : down_pages(*B.D, B, who, 0, B.pg.size());
    });
}

extern "C" int cfth_buffer_will_write(void *buf, size_t off, size_t len)
{
    g_err.clear();
    if (!buf)
        return CFT_ERR_INVALID_ARGUMENT;
    HBuf &B = *static_cast<HBuf *>(buf);
    return at_boundary("preparing a resident buffer for a host write", [&]() -> int {
        static const char who[] = "a host write into a resident buffer";
        /* refused like a read: its bytes outside the write would still be
         * nobody's */
        if (B.lost)
            return refuse_lost(B);
        if (!B.dmem)
            return CFT_OK;
        size_t lo, hi, p0, p1;
        clamp(B, off, len, &lo, &hi);
        page_span(B, lo, hi, &p0, &p1);
        /* A run's pages over the range come home first, WHOLE: the write
         * may not cover all of them, and what it does not cover has to be
         * the run's. Then the range's pages are stale. */
        if (any_page(B, p0, p1, PG_DIRTY)) {
            int st = enter(*B.D, who);
            if (st == CFT_OK)
                st = down_pages(*B.D, B, who, p0, p1);
            if (st != CFT_OK)
                return st;
        }
        set_pages(B, p0, p1, PG_STALE);
        return CFT_OK;
    });
}

extern "C" int cfth_buffer_host_wrote(void *buf, size_t off, size_t len)
{
    /* No sentence and no failure: device.c calls this after a call's body,
     * whose own sentence must stand. */
    if (!buf)
        return CFT_ERR_INVALID_ARGUMENT;
    HBuf &B = *static_cast<HBuf *>(buf);
    if (!B.dmem)
        return CFT_OK;
    size_t lo, hi, p0, p1;
    clamp(B, off, len, &lo, &hi);
    page_span(B, lo, hi, &p0, &p1);
    for (size_t p = p0; p < p1; p++) {
        /* A page a run left DIRTY under the write: inside the range it is
         * superseded; reaching past it, the rest of the page is the run's
         * and comes home around the write (a page is shared by neighbours,
         * which a window-exact copy never is). If that cannot be done, the
         * buffer is LOST - outputs that alias, or a failed device. */
        if (B.pg[p] == PG_DIRTY && !B.lost &&
            !(lo <= page_lo(B, p) && page_hi(B, p) <= hi) &&
            !home_outside(B, p, lo, hi)) {
            B.lost = true;
            try {
                B.lost_why = "a run's output still on the device overlapped bytes the "
                             "library wrote on the host, and the rest of it could not "
                             "be brought home, so this buffer's contents cannot be "
                             "vouched for; publish them again with cft_buffer_to_device";
            } catch (...) {
            }
        }
        B.pg[p] = PG_STALE;
    }
    return CFT_OK;
}

extern "C" void cfth_buffer_stat(void *buf, int *resident, int *device_authority,
                                 uint64_t *resident_binds, uint64_t *staged_binds,
                                 char *why, size_t why_bytes)
{
    if (!buf)
        return;
    const HBuf &B = *static_cast<const HBuf *>(buf);
    const bool dirty = B.dmem && any_page(B, 0, B.pg.size(), PG_DIRTY);
    if (resident) *resident = B.dmem != nullptr;
    /* a LOST buffer has no authority anywhere; its `why` says so, first */
    if (device_authority) *device_authority = !B.lost && dirty;
    if (resident_binds) *resident_binds = B.resident_binds;
    if (staged_binds) *staged_binds = B.staged_binds;
    if (why && why_bytes) {
        if (B.lost)
            std::snprintf(why, why_bytes, "LOST: %s", B.lost_why.c_str());
        else
            std::snprintf(why, why_bytes, "%s", B.why.c_str());
    }
}

/* ---- the compute seams ---------------------------------------------------- */

extern "C" int cfth_run(void *hw, int op, int fmt, int rnd, const void *a,
                        const void *b, const void *c, void *d, size_t n,
                        uint32_t scalar_mask, const cft_bindings *bind,
                        uint32_t *flags, uint32_t *bus)
{
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
        const size_t esz = (size_t)cft_sf_formats[fmt].width / 8;
        Role R[4];
        const void *in[3] = {a, b, c};
        for (int r = 0; r < 3; r++)
            role_from(R[r], bind, CFT_ROLE_A + r,
                      in[r] ? (((scalar_mask >> r) & 1u) ? esz : n * esz) : 0, false,
                      false, false);
        /* d == a is cft_run's in-place rule: an element is read before
         * its own is written, by its own thread alone */
        role_from(R[3], bind, CFT_ROLE_D, n * esz, true, false, true);
        if ((st = bind_call(D, "cft_run", R, 4)) != CFT_OK)
            return st;
        st = run_impl(D, op, fmt, rnd, a, b, c, d, n, scalar_mask, R, &fl);
        call_end(D, st, R, 4);
        if (st == CFT_OK)
            *flags = fl;
        return st;
    });
}

/* backend.h's cfth_augmented: cft_augmented_add, _sub and _mul (op
 * CFT_AUG_ADD, _SUB, _MUL) on this device, called by device.c's
 * cft_device_augmented once augmented.c has validated the call. The roles
 * are cft_run's four slots: a in CFT_ROLE_A, b in CFT_ROLE_B, r in
 * CFT_ROLE_D, and e in CFT_ROLE_C's - the call has no third input, and a
 * fifth role would move CFT_ROLE_COUNT, the stride of the XRT backend's
 * per-role arrays (backend.h). Both outputs may share an input's window
 * exactly (alias_ok): every lane reads both inputs before it writes
 * either output, and no lane touches another's element. */
extern "C" int cfth_augmented(void *hw, int op, int fmt, const void *a, const void *b,
                              void *r, void *e, size_t n, const cft_bindings *bind,
                              uint32_t *flags)
{
    static const char *const names[3] = {"cft_augmented_add", "cft_augmented_sub",
                                         "cft_augmented_mul"};
    g_err.clear();
    return at_boundary("an augmented call", [&]() -> int {
        const char *who = op >= CFT_AUG_ADD && op <= CFT_AUG_MUL ? names[op]
                                                                : "cft_augmented";
        Dev &D = *static_cast<Dev *>(hw);
        uint32_t fl = 0;
        int st = enter(D, who);
        if (st != CFT_OK)
            return st;
        if (op < CFT_AUG_ADD || op > CFT_AUG_MUL || fmt < 0 || fmt > CFT_MAX_FORMAT || !a ||
            !b || !r || !e || r == e || !flags) {
            set_err(fmt_str("%s: the GPU backend was handed an operation, a format or a "
                            "pointer augmented.c refuses first - a defect in libcft, not "
                            "in the call", who));
            return CFT_ERR_INTERNAL;
        }
        const size_t esz = (size_t)cft_sf_formats[fmt].width / 8;
        if (n == 0) {
            *flags = 0;
            return CFT_OK;
        }
        if (n > ((size_t)-1) / esz) {
            set_err(fmt_str("%s: %zu elements of %zu bytes overflow a size_t, which "
                            "augmented.c refuses first - a defect in libcft, not in the "
                            "call", who, n, esz));
            return CFT_ERR_INTERNAL;
        }
        Role R[4];
        role_from(R[0], bind, CFT_ROLE_A, n * esz, false, false, false);
        role_from(R[1], bind, CFT_ROLE_B, n * esz, false, false, false);
        role_from(R[2], bind, CFT_ROLE_D, n * esz, true, false, true);
        role_from(R[3], bind, CFT_ROLE_C, n * esz, true, false, true);
        if ((st = bind_call(D, who, R, 4)) != CFT_OK)
            return st;
        st = aug_impl(D, who, op, fmt, a, b, r, e, n, R, &fl);
        call_end(D, st, R, 4);
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
        size_t top = 0;
        for (size_t r = 0; r < nranges; r++) {
            if (hi[r] < lo[r]) {
                set_err("cft_reduce: a range whose end is before its start reached "
                        "the GPU backend - a defect in libcft, not in the call");
                return CFT_ERR_INTERNAL;
            }
            if (hi[r] > top)
                top = hi[r];
        }
        /* the input's window: as far as the furthest range reads */
        Role R[1];
        role_from(R[0], bind, CFT_ROLE_A, top * esz, false, false, false);
        if ((st = bind_call(D, who, R, 1)) != CFT_OK)
            return st;
        for (size_t r = 0; r < nranges && st == CFT_OK; r++)
            st = reduce_range(D, who, f, op, rnd, (const uint8_t *)a + lo[r] * esz,
                              R[0].resident ? R[0].dp + lo[r] * esz : nullptr,
                              hi[r] - lo[r], (uint8_t *)partials + r * esz, &fl);
        call_end(D, st, R, 1);
        if (st == CFT_OK)
            *flags = fl;
        return st;
    });
}

extern "C" int cfth_reduce_seg(void *hw, int op, int fmt, int rnd, const void *a,
                               size_t n, size_t seg, void *d, const cft_bindings *bind,
                               uint32_t *flags, uint32_t *bus)
{
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
            /* every segment one leaf: verbatim, no flags - from the host
             * mirror, which device.c has brought home */
            std::memmove(dst, src, n * esz);
            *flags = 0;
            return CFT_OK;
        }
        Role R[1];
        role_from(R[0], bind, CFT_ROLE_A, n * esz, false, false, false);
        if ((st = bind_call(D, who, R, 1)) != CFT_OK)
            return st;
        const uint8_t *dsrc = R[0].resident ? R[0].dp : nullptr;
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
            for (size_t s0 = 0; s0 < nres && st == CFT_OK; s0 += g) {
                const size_t gs = nres - s0 < g ? nres - s0 : g;
                st = reduce_on_device(D, who, f, op, rnd, src + s0 * seg * esz,
                                      dsrc ? dsrc + s0 * seg * esz : nullptr, seg, gs,
                                      dst + s0 * esz, &fl);
            }
        } else {
            for (size_t s = 0; s < nres && st == CFT_OK; s++)
                st = reduce_range(D, who, f, op, rnd, src + s * seg * esz,
                                  dsrc ? dsrc + s * seg * esz : nullptr, seg,
                                  dst + s * esz, &fl);
        }
        call_end(D, st, R, 1);
        if (st == CFT_OK)
            *flags = fl;
        return st;
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
#ifdef CFT_HIP_PLANTS
        /* full-refuse: before anything is bound, staged or run */
        if ((D.plant & PL_FULL_REFUSE) && io && io->prog && plant_whole(*io->prog, false)) {
            set_err(fmt_str("cft_program_run_ex: %s refuses a BANK_EXT program of %u "
                            "constants, before anything is bound or run "
                            "(CFT_HIP_PLANT=full-refuse)", D.label.c_str(),
                            (unsigned)io->prog->n_consts));
            return (int)CFT_ERR_UNSUPPORTED;
        }
#endif
        const size_t esz = (size_t)cft_sf_formats[fmt].width / 8;
        const size_t md = deposits ? (size_t)max_deposits : 0;
        const size_t nsi = io && io->scratch_in ? io->n_scratch_in : 0;
        const size_t nso = io && io->scratch_out ? io->n_scratch_out : 0;
        const bool masked = io && io->lane_mask;
        /* R16: a stream with an index table is the SOURCE the table reads,
         * idx_*_src elements whole - the window device.c registers and
         * brings home - and the scratch-in block with one is the pool,
         * scratch_in_bytes; each table is n entries (n * nsi for the
         * block's) of four bytes, read by every lane: an input */
        const bool ta = io && io->idx_a, tb = io && io->idx_b, tc = io && io->idx_c;
        const bool tsi = nsi && io->idx_scratch_in;
        {
            const size_t src[4] = {ta ? io->idx_a_src : 0, tb ? io->idx_b_src : 0,
                                   tc ? io->idx_c_src : 0, tsi ? io->idx_scratch_src : 0};
            for (int s = 0; s < 4; s++)
                if (src[s] > ((size_t)-1) / esz) {
                    set_err(fmt_str("cft_program_run_ex: an indexed source of %zu "
                                    "elements of %zu bytes is more than this process "
                                    "can address", src[s], esz));
                    return (int)CFT_ERR_INVALID_ARGUMENT;
                }
        }
        Role R[10];
        role_from(R[0], bind, CFT_ROLE_A, a ? (ta ? io->idx_a_src : n) * esz : 0, false,
                  false, false);
        role_from(R[1], bind, CFT_ROLE_B, b ? (tb ? io->idx_b_src : n) * esz : 0, false,
                  false, false);
        role_from(R[2], bind, CFT_ROLE_C, c ? (tc ? io->idx_c_src : n) * esz : 0, false,
                  false, false);
        /* the deposits are zero-filled before a lane reads its inputs, so
         * no input may share them; scratch-out is written after a lane's
         * last deposit, from its own slots, so an identical input window
         * may (an integrator's state carried in place) - but not a pool a
         * table gathers from, whose slots any lane may read: that one is
         * staged, the mirror's bytes before the run */
        role_from(R[3], bind, CFT_ROLE_D, n * md * esz, true, masked, false);
        role_from(R[4], bind, CFT_ROLE_SI, tsi ? io->scratch_in_bytes : n * nsi * esz,
                  false, false, false);
        role_from(R[5], bind, CFT_ROLE_SO, n * nso * esz, true, masked, !tsi);
        role_from(R[6], bind, CFT_ROLE_IA, ta ? n * 4 : 0, false, false, false);
        role_from(R[7], bind, CFT_ROLE_IB, tb ? n * 4 : 0, false, false, false);
        role_from(R[8], bind, CFT_ROLE_IC, tc ? n * 4 : 0, false, false, false);
        role_from(R[9], bind, CFT_ROLE_ISI, tsi ? n * nsi * 4 : 0, false, false, false);
        if ((st = bind_call(D, "cft_program_run_ex", R, 10)) != CFT_OK)
            return st;
        st = prog_impl(D, fmt, io, max_deposits, a, b, c, deposits, counts, n, R, &fl,
                       &rep);
        call_end(D, st, R, 10);
        if (st == CFT_OK) {
            if (flags) *flags = fl;
            if (bus) *bus = rep;
        }
        return st;
    });
}

#ifdef CFT_HIP_PLANTS
/* A plant build's instrument, read by a bench after a program run (no
 * plant needs to be set): the last run's n, element bytes, reach, a lane's
 * pool bytes, the pool's cap, the stage, the head, a lane's staged bytes
 * in and out, kmax, the first chunk, the launches, the largest and the
 * smallest launch in lanes, the staged source bytes uploaded, and the
 * device's free bytes at open - up to `nout` of them, in that order.
 * Returns how many it wrote. Not in backend.h: nothing in libcft calls
 * it, and a default build defines no such symbol. */
extern "C" int cfth_plant_prog_probe(uint64_t *out, int nout)
{
    const uint64_t v[] = {g_probe.n, g_probe.esz, g_probe.reach, g_probe.lane_pool,
                          g_probe.pool_cap, g_probe.stage, g_probe.head, g_probe.lane_in,
                          g_probe.lane_out, g_probe.kmax, g_probe.chunk0,
                          g_probe.launches, g_probe.max_launch, g_probe.min_launch,
                          g_probe.src_bytes, g_probe.free_at_open};
    const int m = (int)(sizeof v / sizeof v[0]);
    int i;
    for (i = 0; i < m && i < nout && out; i++)
        out[i] = v[i];
    return i;
}
#endif
