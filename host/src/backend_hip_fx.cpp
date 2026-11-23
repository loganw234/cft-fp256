/* Copyright 2026 Logan W.
 * SPDX-License-Identifier: Apache-2.0
 *
 * The GPU backend's fixed tier inside programs (round 3's G3B): its two
 * program kernels, k_seq_fx (binary256) and k_seq_fx128 (binary128), in a
 * device translation unit of their own beside backend_hip.cpp's.
 *
 * WHY A SECOND UNIT (measured; G3B's ledger and docs/VALIDATION.md): with
 * these kernels compiled in backend_hip.cpp's unit, k_seq's code moved on
 * sm_120 though its text did not - ptxas's spills 80/76 bytes to 88/88 at
 * the same 64 registers and 16,864 bytes, 9 of 16 programs 1.6 % to 3.6 %
 * slower on the RTX 5060 Ti beyond the spread (the base against that tip,
 * processes alternating) - with the wrappers out of line too, and with each
 * executor copy on its own bigint and softfloat (k_seq's frame then 17,104
 * bytes and its fp128 programs 3.7 % to 6.8 % slower). With nothing new
 * instantiated in the unit, k_seq's frame and spills were the base's and its
 * programs within the spread. So the generic tier's unit keeps its device
 * code as it was (built so, its six kernels' SASS and gfx1102 code are the
 * base's line for line), and this one holds everything the fixed tier's
 * program kernels reach. Neither unit uses relocatable device code:
 * each is a whole device program, and no device function crosses them; the
 * two entries at the end are host functions backend_hip.cpp calls.
 *
 * What it holds: cft.h, bigint.h, softfloat.h and seq_exec.h read at the
 * file's scope for the TYPES of the interface (cft_program, cft_fmt_desc,
 * cft_bn, cft_run_args) - the functions those headers declare or define
 * there are not used and emit no code - then, inside an ANONYMOUS
 * namespace, the tree's bigint.c and softfloat.c (their two headers read
 * again, so that cft_bn and cft_fmt_desc there are the namespace's own
 * types), fma256_fixed.h and fma128_fixed.h (the fixed tier's second
 * implementations), seq_alu_fixed.h (their wrappers with cft_sf_compute's
 * signature), and seq_exec.h twice - in fxseq with its one ALU call on
 * fxalu_compute, in fxseq128 on fxalu128_compute (a macro hook is fixed per
 * inclusion, so a second width is a second copy of the executor) - the
 * tree's text unedited, both copies on this unit's one copy of the
 * arithmetic; and the kernels. Everything executable has internal linkage,
 * so this object defines no symbol of bigint's, softfloat's or the
 * executor's, and none of backend_hip.o's: hip-symcheck holds it to both,
 * with a plant that must turn the pairwise check red. Besides the two
 * entries it defines, on AMD, the unit's __hip_cuid_ symbol, and with nvcc
 * the namespace's own names, which nvcc emits as global symbols carrying
 * this file's hash (_GLOBAL__N__<hash>_18_backend_hip_fx_cpp_...) - names no
 * other unit has (measured at G3B: 41 symbols with nvcc, 3 with clang).
 *
 * AUGADD and AUGERR: each copy's augmented.c lane calls are mapped to a
 * stub that refuses (returns 1, so the case returns CFT_ERR_INTERNAL), and
 * augmented.c is not in this unit: no program with AUGADD or AUGERR is
 * routed here (backend_hip.cpp's seq_route, and its literal test before
 * anything is staged). The stub leaves the `case` in place: this is not an
 * executor without the case.
 *
 * Plants (HIP_PLANTS=1, the same flags as backend_hip.cpp's): the launch is
 * handed backend_hip.cpp's plant word and, beside it, the masks of the
 * bits this unit acts on, from backend_hip.cpp's own enum - so no bit is
 * written twice - and the kernel gets this unit's small word: seq-mask and
 * seq-deposit, applied as k_seq applies them, and the four wrapper plants
 * of the kernel's format (G3B's seqfx-rmm, -flag, -steer and -mulsign, or
 * their fp128 twins), applied by a wrapper of the wrapper on the fixed
 * ALU's own calls alone - the width, FMA to MUL, attributes 0 to 4 - its
 * word read through a __device__ global the kernel sets for every lane
 * (seq-aug's pattern in backend_hip.cpp): rmm computed as rne; UNDERFLOW
 * dropped from the lane's flags; SUB steered as ADD (c's sign not flipped:
 * the ADD it then is); MUL's zero addend always +0 (the FMA a*b + +0 it
 * then is). No operand is ever held in a double.
 */
#include <hip/hip_runtime.h>   /* first: blockIdx, and AMD's device memset */
#define BLOCK_LANES 1          /* a thread is a block of one lane */
/* softfloat.c's one datum, renamed in this unit as in backend_hip.cpp (in
 * the anonymous namespace below it is internal in any case) */
#define cft_sf_formats cft_hipfx_sf_formats

#include <cstddef>
#include <cstdint>
#include <cstring>

/* the interface's types at the file's scope; the header's functions are not
 * used here (the anonymous namespace has its own) and emit no code */
#if defined(__GNUC__)
#pragma GCC diagnostic push
#pragma GCC diagnostic ignored "-Wunused-function"
#endif
#include "../include/cft.h"
#include "bigint.h"
#include "softfloat.h"
#include "seq_exec.h"
#if defined(__GNUC__)
#pragma GCC diagnostic pop
#endif

/* the two entries, as backend_hip.cpp declares them (C++ names: a
 * signature that drifts in either file fails the link) */
void cfthfx_seq_attributes(hipFuncAttributes *fa256, hipError_t *e256,
                           hipFuncAttributes *fa128, hipError_t *e128);
void cfthfx_seq_launch(int which, unsigned grid, unsigned block, hipStream_t stream,
                       const ::cft_program &P, const ::cft_fmt_desc &f, const ::cft_bn *konst,
                       const cft_run_args &A, ::cft_bn *pool, uint32_t reach, size_t first,
                       void *acc, uint64_t plant, uint64_t m_mask, uint64_t m_deposit,
                       uint64_t m_rmm, uint64_t m_flag, uint64_t m_steer, uint64_t m_mulsign);

namespace {

/* the launch's answer, backend_hip.cpp's hacc (whose layout is held to the
 * same four numbers there) */
struct fx_hacc {
    unsigned int flags;
    unsigned int status;
    unsigned long long fail;
};
static_assert(sizeof(fx_hacc) == 16 && offsetof(fx_hacc, flags) == 0 &&
              offsetof(fx_hacc, status) == 4 && offsetof(fx_hacc, fail) == 8,
              "fx_hacc is not backend_hip.cpp's hacc");

/* this unit's plant word, made at the launch from backend_hip.cpp's */
enum : unsigned {
    FXP_SEQ_MASK = 1u << 0, FXP_SEQ_DEPOSIT = 1u << 1, FXP_RMM = 1u << 2,
    FXP_FLAG = 1u << 3, FXP_STEER = 1u << 4, FXP_MULSIGN = 1u << 5,
};
#ifdef CFT_HIP_PLANTS
[[maybe_unused]] __device__ unsigned g_plant_seqfx;   /* the wrapper plants', every lane */
#define FX_PLANT_PARAM , unsigned plant
#else
#define FX_PLANT_PARAM
#endif

/* The tree's arithmetic, inside this namespace: internal, so the functions
 * of bigint.c, softfloat.c and softfloat.h that the program kernels do not
 * reach are unused functions of this unit, which the compilers would name
 * (ROCm's clang: 13 of them, each pass) - silenced for these files alone,
 * as the fixed headers' `#pragma unroll` is for gcc. */
#if defined(__GNUC__)
#pragma GCC diagnostic push
#pragma GCC diagnostic ignored "-Wunused-function"
#endif
#if defined(__clang__)
#pragma clang diagnostic ignored "-Wunneeded-internal-declaration"
#endif
#if defined(__GNUC__) && !defined(__clang__)
#pragma GCC diagnostic ignored "-Wunknown-pragmas"   /* the headers' #pragma unroll */
#endif
#undef CFT_BIGINT_H
#undef CFT_SOFTFLOAT_H
#define cft_aug_add_lane fxseq_no_aug
#define cft_aug_mul_lane fxseq_no_aug
#include "bigint.c"
#include "softfloat.c"
/* softfloat.h declared the two augmented lanes under the stub's name */
CFT_HD int fxseq_no_aug(const cft_fmt_desc *, const cft_bn *, const cft_bn *, cft_bn *, cft_bn *,
                        uint32_t *)
{
    return 1;               /* augmentedAddition is k_seq's (seq_route), never here */
}
#include "fma256_fixed.h"
#include "fma128_fixed.h"
#include "seq_alu_fixed.h"

#ifdef CFT_HIP_PLANTS
/* the wrapper plants, one wrapper a width */
CFT_HD static int plant_fxalu(const cft_fmt_desc *f, int op, int rnd, const cft_bn *a,
                              const cft_bn *b, const cft_bn *c, cft_bn *out, uint32_t *flags,
                              int width)
{
#if defined(__CUDA_ARCH__) || defined(__HIP_DEVICE_COMPILE__)
    const unsigned w = g_plant_seqfx;
    if (f->width == width && op >= CFT_SF_FMA && op <= CFT_SF_MUL && rnd >= CFT_SF_RNE &&
        rnd <= CFT_SF_RMM) {
        cft_bn z;
        int rc;
        if ((w & FXP_RMM) && rnd == CFT_SF_RMM)
            rnd = CFT_SF_RNE;
        if ((w & FXP_STEER) && op == CFT_SF_SUB)
            op = CFT_SF_ADD;
        if ((w & FXP_MULSIGN) && op == CFT_SF_MUL) {
            cft_bn_zero(&z);
            op = CFT_SF_FMA;
            c = &z;
        }
        rc = width == 256 ? fxalu_compute(f, op, rnd, a, b, c, out, flags)
                          : fxalu128_compute(f, op, rnd, a, b, c, out, flags);
        if (!rc && (w & FXP_FLAG))
            *flags &= ~(uint32_t)CFT_SF_UNDERFLOW;
        return rc;
    }
#endif
    return width == 256 ? fxalu_compute(f, op, rnd, a, b, c, out, flags)
                        : fxalu128_compute(f, op, rnd, a, b, c, out, flags);
}
CFT_HD static int plant_fxalu_compute(const cft_fmt_desc *f, int op, int rnd, const cft_bn *a,
                                      const cft_bn *b, const cft_bn *c, cft_bn *out,
                                      uint32_t *flags)
{
    return plant_fxalu(f, op, rnd, a, b, c, out, flags, 256);
}
CFT_HD static int plant_fxalu128_compute(const cft_fmt_desc *f, int op, int rnd,
                                         const cft_bn *a, const cft_bn *b, const cft_bn *c,
                                         cft_bn *out, uint32_t *flags)
{
    return plant_fxalu(f, op, rnd, a, b, c, out, flags, 128);
}
#endif

#undef CFT_SEQ_EXEC_H
#undef CFT_SEQ_ALU
#ifdef CFT_HIP_PLANTS
#define CFT_SEQ_ALU plant_fxalu_compute
#else
#define CFT_SEQ_ALU fxalu_compute
#endif
namespace fxseq {
#include "seq_exec.h"
}
#undef CFT_SEQ_EXEC_H
#undef CFT_SEQ_ALU
#ifdef CFT_HIP_PLANTS
#define CFT_SEQ_ALU plant_fxalu128_compute
#else
#define CFT_SEQ_ALU fxalu128_compute
#endif
namespace fxseq128 {
#include "seq_exec.h"
}
#undef cft_aug_add_lane
#undef cft_aug_mul_lane
#if defined(__GNUC__)
#pragma GCC diagnostic pop
#endif

/* The type bridge. This namespace's cft_bn and cft_fmt_desc, and each copy's
 * cft_program, are SECOND TYPES of the same text, so the kernels take them
 * and the launch fills them from the interface's: each held to the
 * interface's type here - the whole's size and alignment, and every field's
 * offset and size (the program's seventeen fields: the executor reads
 * n_insns, insns, f, max_deposits, flags, scratch_active, scratch_used,
 * scratch_depth, scratch_log2, n_scratch_in and n_scratch_out; the
 * descriptor's nine, the bignum's two) - then copied whole, byte for byte,
 * or for the constants and the pool (device memory the host wrote, or no
 * one has) read through a pointer of this namespace's bignum. */
#define FX_SAME(Q, G, m) (offsetof(Q, m) == offsetof(G, m) && \
                          sizeof(((Q *)0)->m) == sizeof(((G *)0)->m))
template <class Q>
constexpr bool fx_same_program()
{
    return sizeof(Q) == sizeof(::cft_program) && alignof(Q) == alignof(::cft_program) &&
           FX_SAME(Q, ::cft_program, dev) && FX_SAME(Q, ::cft_program, f) &&
           FX_SAME(Q, ::cft_program, fmt_code) && FX_SAME(Q, ::cft_program, max_deposits) &&
           FX_SAME(Q, ::cft_program, n_insns) && FX_SAME(Q, ::cft_program, n_consts) &&
           FX_SAME(Q, ::cft_program, flags) && FX_SAME(Q, ::cft_program, n_scratch_in) &&
           FX_SAME(Q, ::cft_program, n_scratch_out) && FX_SAME(Q, ::cft_program, scratch_used) &&
           FX_SAME(Q, ::cft_program, scratch_active) &&
           FX_SAME(Q, ::cft_program, scratch_depth) &&
           FX_SAME(Q, ::cft_program, scratch_log2) && FX_SAME(Q, ::cft_program, insns) &&
           FX_SAME(Q, ::cft_program, consts) && FX_SAME(Q, ::cft_program, image) &&
           FX_SAME(Q, ::cft_program, image_bytes);
}
static_assert(fx_same_program<fxseq::cft_program>() && fx_same_program<fxseq128::cft_program>(),
              "a namespaced cft_program is not the interface's layout");
static_assert(sizeof(cft_fmt_desc) == sizeof(::cft_fmt_desc) &&
                  alignof(cft_fmt_desc) == alignof(::cft_fmt_desc) &&
                  FX_SAME(cft_fmt_desc, ::cft_fmt_desc, name) &&
                  FX_SAME(cft_fmt_desc, ::cft_fmt_desc, exp_w) &&
                  FX_SAME(cft_fmt_desc, ::cft_fmt_desc, man_w) &&
                  FX_SAME(cft_fmt_desc, ::cft_fmt_desc, width) &&
                  FX_SAME(cft_fmt_desc, ::cft_fmt_desc, prec) &&
                  FX_SAME(cft_fmt_desc, ::cft_fmt_desc, bias) &&
                  FX_SAME(cft_fmt_desc, ::cft_fmt_desc, emax) &&
                  FX_SAME(cft_fmt_desc, ::cft_fmt_desc, emin) &&
                  FX_SAME(cft_fmt_desc, ::cft_fmt_desc, exp_mask),
              "this unit's cft_fmt_desc is not the interface's layout");
static_assert(sizeof(cft_bn) == sizeof(::cft_bn) && alignof(cft_bn) == alignof(::cft_bn) &&
                  FX_SAME(cft_bn, ::cft_bn, n) && FX_SAME(cft_bn, ::cft_bn, v),
              "this unit's cft_bn is not the interface's layout");
#undef FX_SAME
template <class Q, class P>
Q fx_copy(const P &p)
{
    static_assert(sizeof(Q) == sizeof(P), "fx_copy between types of different sizes");
    Q q;
    std::memcpy(&q, &p, sizeof q);
    return q;
}

/* is T the type U (k_seq_t's guard; <type_traits> is not included) */
template <class T, class U> struct fx_same_type { static constexpr bool value = false; };
template <class T> struct fx_same_type<T, T> { static constexpr bool value = true; };

/* k_seq_fx and k_seq_fx128: backend_hip.cpp's k_seq's text, token for
 * token, over a namespaced executor - k_seq_t<fxseq::cft_program,
 * fxseq::seq_block> (k_seq_fx, fp256 programs alone) and
 * k_seq_t<fxseq128::cft_program, fxseq128::seq_block> (k_seq_fx128, fp128
 * alone), each its own kernel with its own frame; k_seq is not this text
 * and is not in this unit. The four calls of the executor are found by
 * ARGUMENT-DEPENDENT LOOKUP, each by the namespace of an argument's type:
 *   seq_lanes_deposits(&P, ...)    by &P, a Prog * (fxseq::cft_program *)
 *   seq_lanes_in(&P, &A, &B, ...)  by &P and &B (Prog *, Block *)
 *   seq_run_block(&P, ..., &B, ..) by &P and &B
 *   seq_lanes_out(&P, &A, &B, ...) by &P and &B
 * so for k_seq_fx each is fxseq's (for k_seq_fx128 fxseq128's); the file
 * scope's seq_exec.h functions take ::cft_program and ::seq_block, so they
 * are not viable for these arguments, and the static_assert below refuses
 * an instance over the file scope's types. Which seq_run_block ran is
 * proved at run time by G3B's wrapper plants, which act inside these copies'
 * ALU alone. In a plant build the kernel sets the wrapper plants' word for
 * every lane, as k_seq sets seq-aug's. */
template <class Prog, class Block>
__global__ __launch_bounds__(256) void k_seq_t(Prog P, cft_fmt_desc f, const cft_bn *konst,
                                               cft_run_args A, cft_bn *pool, uint32_t reach,
                                               size_t first, fx_hacc *acc FX_PLANT_PARAM)
{
    static_assert(!fx_same_type<Prog, ::cft_program>::value &&
                      !fx_same_type<Block, ::seq_block>::value,
                  "k_seq_t over ::cft_program would be the generic executor under a fixed "
                  "kernel's name: k_seq is that kernel");
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
        Block B;
#ifdef CFT_HIP_PLANTS
        if (plant & FXP_SEQ_MASK)
            A.lane_mask = NULL;
        g_plant_seqfx = plant;             /* the wrapper plants' word, every lane */
#endif
        P.f = &f;
        B.depth = P.scratch_depth;
        B.scratch = pool ? pool + i * reach : NULL;
#ifdef CFT_HIP_PLANTS
        if (!(plant & FXP_SEQ_DEPOSIT))
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

/* One launch of k_seq_fx (which 2) or k_seq_fx128 (which 3): the copies of
 * the interface's values into this namespace's types made before the launch,
 * inside the namespace (where every name is this unit's own) */
void fx_launch(int which, unsigned grid, unsigned block, hipStream_t stream,
               const ::cft_program &P, const ::cft_fmt_desc &f, const ::cft_bn *konst,
               const cft_run_args &A, ::cft_bn *pool, uint32_t reach, size_t first, void *acc,
               unsigned w)
{
    const cft_fmt_desc fq = fx_copy<cft_fmt_desc>(f);
    const cft_bn *const kq = (const cft_bn *)(const void *)konst;
    cft_bn *const pq = (cft_bn *)(void *)pool;
    fx_hacc *const aq = (fx_hacc *)acc;
#ifdef CFT_HIP_PLANTS
#define FX_PLANT_ARG , w
#else
    (void)w;
#define FX_PLANT_ARG
#endif
    if (which == 2) {
        const fxseq::cft_program prog = fx_copy<fxseq::cft_program>(P);
        k_seq_t<fxseq::cft_program, fxseq::seq_block><<<grid, block, 0, stream>>>(
            prog, fq, kq, A, pq, reach, first, aq FX_PLANT_ARG);
    } else {
        const fxseq128::cft_program prog = fx_copy<fxseq128::cft_program>(P);
        k_seq_t<fxseq128::cft_program, fxseq128::seq_block><<<grid, block, 0, stream>>>(
            prog, fq, kq, A, pq, reach, first, aq FX_PLANT_ARG);
    }
#undef FX_PLANT_ARG
}

} /* namespace */

/* The fixed tier's program kernels' attributes, read at backend_hip.cpp's
 * open beside its six kernels (the device must run this build's code). */
void cfthfx_seq_attributes(hipFuncAttributes *fa256, hipError_t *e256,
                           hipFuncAttributes *fa128, hipError_t *e128)
{
    *e256 = hipFuncGetAttributes(
        fa256, reinterpret_cast<const void *>(&k_seq_t<fxseq::cft_program, fxseq::seq_block>));
    *e128 = hipFuncGetAttributes(
        fa128,
        reinterpret_cast<const void *>(&k_seq_t<fxseq128::cft_program, fxseq128::seq_block>));
}

/* One launch of k_seq_fx (which 2) or k_seq_fx128 (which 3), from
 * backend_hip.cpp's prog_impl - its route's value and its arguments as
 * k_seq takes them; the launch's errors are read there (check_launch). The
 * plant word is made here from the caller's and its masks; a default build
 * passes zeros and the kernel takes none. */
void cfthfx_seq_launch(int which, unsigned grid, unsigned block, hipStream_t stream,
                       const ::cft_program &P, const ::cft_fmt_desc &f, const ::cft_bn *konst,
                       const cft_run_args &A, ::cft_bn *pool, uint32_t reach, size_t first,
                       void *acc, uint64_t plant, uint64_t m_mask, uint64_t m_deposit,
                       uint64_t m_rmm, uint64_t m_flag, uint64_t m_steer, uint64_t m_mulsign)
{
    const unsigned w = ((plant & m_mask) ? (unsigned)FXP_SEQ_MASK : 0u) |
                       ((plant & m_deposit) ? (unsigned)FXP_SEQ_DEPOSIT : 0u) |
                       ((plant & m_rmm) ? (unsigned)FXP_RMM : 0u) |
                       ((plant & m_flag) ? (unsigned)FXP_FLAG : 0u) |
                       ((plant & m_steer) ? (unsigned)FXP_STEER : 0u) |
                       ((plant & m_mulsign) ? (unsigned)FXP_MULSIGN : 0u);
    fx_launch(which, grid, block, stream, P, f, konst, A, pool, reach, first, acc, w);
}

#ifdef CFT_HIP_PLANT_FX_COLLIDE
/* hip-symcheck-plant's third plant (host/Makefile): the symbol backend_hip.cpp
 * defines under the same macro, which the pairwise check must name */
extern "C" int cfth_plant_fx_collide(void)
{
    return 1;
}
#endif
