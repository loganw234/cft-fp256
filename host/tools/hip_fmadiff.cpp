/* Copyright 2026 Logan W.
 * SPDX-License-Identifier: Apache-2.0
 *
 * hip-fmadiff - the GPU backend's fixed tier held to its generic tier on a
 * GPU, lane by lane (round 3's G3A; study GPU-A's `cft_fma diff`, moved
 * into the tree):
 *
 *   hip-fmadiff diff N SEED [--op add|sub|mul] [--stream study|edge]
 *                           [--base B] [--device D] [--block K]
 *
 * runs lanes B to B + N - 1 of a counter-based stream (tools/fx256_stream.h:
 * `study`, GPU-A's nine families, the default; `edge`, the five classes
 * GPU-A's generator does not aim at) through two kernels on the same
 * inputs - the generic lane, libcft's cft_sf_compute(op), and the fixed
 * lane, fx256_steer then fx256_fma_lane (src/fma256_fixed.h), the very
 * functions the backend's k_run and k_run256 call - and compares d and the
 * flag byte of every lane on the device, in chunks of at most 2^21 lanes.
 * For ADD and SUB, a becomes a*b rounded to nearest (and for SUB c becomes
 * -c), so a + c meets the alignments a*b + c did. The first chunk's inputs
 * and both outputs are hashed with libcft's sha256, so devices, builds and
 * GPU-A's records compare: seed 20261110 from lane 0 reproduces GPU-A's
 * first-chunk sums. The last line says the stream, the op, the cases, the
 * seed, the device, how many lanes differ, the three sums, the kernels'
 * milliseconds and rates, the wall time and GREEN or RED; exit 0 when no
 * lane differs, 1 when one does, 2 when the run could not be made.
 *
 * What this holds is the ARITHMETIC: the two lanes the backend's kernels
 * call. The backend's plumbing around them - operands, scalars, NULLs, the
 * flag OR, chunks, resident windows, the branch - is hip-test's fixed
 * leg's to hold; neither holds the other's.
 *
 * It compiles the tree's bigint.c, softfloat.c (cft_sf_formats renamed, as
 * backend_hip.cpp renames it), src/fma256_fixed.h and tools/fx256_stream.h
 * in backend_hip.cpp's order and under its flags (host/Makefile's
 * hip-fmadiff, HIP=1 only), with the tree's sha256.c beside it. Built with
 * HIP_PLANTS=1 it carries the four plants that act on the fixed lane, by
 * the library's names - CFT_HIP_PLANT=fixed-rmm, fixed-flag, fixed-steer or
 * fixed-mulsign - and refuses any other value by name; a default build has
 * no plant code and refuses a set CFT_HIP_PLANT, so that a plant run on
 * the wrong build is never a silent green. The mismatch count is an
 * atomic integer sum, whose order cannot change it; no value is summed.
 * No operand is held in a double.
 */
#include <hip/hip_runtime.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <chrono>
#include <string>
#include <vector>

#define cft_sf_formats cft_hip_sf_formats   /* backend_hip.cpp's rename */
#include "../src/bigint.c"
#include "../src/softfloat.c"
/* as in backend_hip.cpp: nvcc's host pass hands the header's `#pragma
 * unroll` to gcc, which does not know it */
#if defined(__GNUC__) && !defined(__clang__)
#pragma GCC diagnostic push
#pragma GCC diagnostic ignored "-Wunknown-pragmas"
#endif
#include "../src/fma256_fixed.h"
#include "fx256_stream.h"
#if defined(__GNUC__) && !defined(__clang__)
#pragma GCC diagnostic pop
#endif
#include "../src/sha256.h"

/* host/Makefile compiles the tree's sha256.c beside this unit, as C, in
 * place of libcft.a (whose backend_hip.o would bring the unit's own C++
 * copies of bigint and softfloat a second time). sha256.c's public
 * one-shot cft_sha256, which this tool does not call, clears libcft's
 * error slot first: device.c's cft_clear_error is not linked, so this
 * stands in for it. */
extern "C" void cft_clear_error(void)
{
}

__global__ void __launch_bounds__(256)
fxd_gen_kernel(cft_fmt_desc f, int stream, int op, uint64_t seed, int64_t base, int64_t n,
               uint8_t *a, uint8_t *b, uint8_t *c, uint8_t *rnd)
{
    const int64_t i = (int64_t)blockIdx.x * blockDim.x + threadIdx.x;
    if (i < n) {
        fxs_gen_case(&f, stream, seed, base + i, a + i * 32, b + i * 32, c + i * 32, rnd + i);
        fxs_prep_case(&f, op, a + i * 32, b + i * 32, c + i * 32);
    }
}

__global__ void __launch_bounds__(256)
fxd_generic_kernel(cft_fmt_desc f, int op, int64_t n, const uint8_t *a, const uint8_t *b,
                   const uint8_t *c, const uint8_t *rnd, uint8_t *d, uint8_t *fl)
{
    const int64_t i = (int64_t)blockIdx.x * blockDim.x + threadIdx.x;
    if (i < n)
        fxs_generic_lane(&f, op, a + i * 32, b + i * 32, c + i * 32, rnd[i], d + i * 32, fl + i);
}

__global__ void __launch_bounds__(256)
fxd_fixed_kernel(int op, int64_t n, const uint8_t *a, const uint8_t *b, const uint8_t *c,
                 const uint8_t *rnd, uint8_t *d, uint8_t *fl, unsigned plant)
{
    const int64_t i = (int64_t)blockIdx.x * blockDim.x + threadIdx.x;
    if (i < n)
        fxs_fixed_lane(op, a + i * 32, b + i * 32, c + i * 32, rnd[i], d + i * 32, fl + i, plant);
}

/* Lanes where the two kernels differ: counted by an atomic (an integer sum,
 * whose order cannot change it), the first eight indices kept. */
__global__ void fxd_cmp_kernel(int64_t n, const uint8_t *d1, const uint8_t *f1,
                               const uint8_t *d2, const uint8_t *f2, unsigned *count,
                               unsigned long long *first)
{
    const int64_t i = (int64_t)blockIdx.x * blockDim.x + threadIdx.x;
    int k, bad;
    if (i >= n)
        return;
    bad = f1[i] != f2[i];
    for (k = 0; k < 32; k++)
        bad |= d1[i * 32 + k] != d2[i * 32 + k];
    if (bad) {
        const unsigned c = atomicAdd(count, 1u);
        if (c < 8)
            first[c] = (unsigned long long)i;
    }
}

#define CK(x) do { hipError_t e_ = (x); if (e_ != hipSuccess) { \
    fprintf(stderr, "hip-fmadiff: %s:%d: %s: %s\n", __FILE__, __LINE__, #x, \
            hipGetErrorString(e_)); exit(2); } } while (0)

typedef std::chrono::steady_clock clk;
static double ms_since(clk::time_point t0)
{
    return std::chrono::duration<double, std::milli>(clk::now() - t0).count();
}

static int device_index = 0, block = 128, alu_op = CFT_SF_FMA, stream = FXS_STUDY;
static unsigned plant = 0;
#ifdef CFT_HIP_PLANTS
static const char *plant_name = "none";
#endif
static char device_name[320] = "?";

static void hexle(const uint8_t *p, char *out)          /* big-endian text */
{
    int i;
    for (i = 0; i < 32; i++)
        sprintf(out + 2 * i, "%02x", p[31 - i]);
}

static void pick_device(void)
{
    hipDeviceProp_t p;
    char bus[32] = {0};
    /* zeroed first: HIP 7.2.4 on NVIDIA leaves gcnArchName unwritten (GPU-A) */
    memset(&p, 0, sizeof p);
    CK(hipSetDevice(device_index));
    CK(hipGetDeviceProperties(&p, device_index));
    CK(hipDeviceGetPCIBusId(bus, (int)sizeof bus, device_index));
    if (!strncmp(p.gcnArchName, "gfx", 3))
        snprintf(device_name, sizeof device_name, "%.200s (%.60s, bus %s)", p.name,
                 p.gcnArchName, bus);
    else
        snprintf(device_name, sizeof device_name, "%.200s (sm_%d%d, bus %s)", p.name,
                 p.major, p.minor, bus);
}

static void diff_show(const cft_fmt_desc *f, uint64_t seed, int64_t i)
{
    uint8_t a[32], b[32], c[32], r, d1[32], d2[32], f1, f2;
    char ha[65], hb[65], hc[65], h1[65], h2[65];
    fxs_gen_case(f, stream, seed, i, a, b, c, &r);       /* recomputed on the host */
    fxs_prep_case(f, alu_op, a, b, c);
    fxs_generic_lane(f, alu_op, a, b, c, r, d1, &f1);
    fxs_fixed_lane(alu_op, a, b, c, r, d2, &f2, plant);
    hexle(a, ha); hexle(b, hb); hexle(c, hc); hexle(d1, h1); hexle(d2, h2);
    printf("  DIFF lane %lld rnd %d: a %s b %s c %s\n     generic d %s flags 0x%02x\n"
           "       fixed d %s flags 0x%02x\n", (long long)i, r, ha, hb, hc, h1, f1, h2, f2);
}

static int do_diff(int64_t total, uint64_t seed, int64_t base0)
{
    const cft_fmt_desc f = cft_sf_formats[3];
    const int64_t chunk = total < ((int64_t)1 << 21) ? total : ((int64_t)1 << 21);
    int64_t base, i, bad = 0, nshow = 0, firsts[8];
    double tgen = 0, tg = 0, tf = 0;
    char hx[3][65];
    const clk::time_point w0 = clk::now();
    std::vector<uint8_t> in((size_t)chunk * 97), o1((size_t)chunk * 33), o2((size_t)chunk * 33);
    uint8_t *a = &in[0], *b = a + chunk * 32, *c = b + chunk * 32, *r = c + chunk * 32;
    uint8_t *da, *db, *dc, *dr, *d1, *f1, *d2, *f2;
    unsigned *dcount, hcount;
    unsigned long long *dfirst, hfirst[8];
    hipEvent_t e[4];
    float ms;
    if (!fx256_matches(&f)) {
        fprintf(stderr, "hip-fmadiff: fma256_fixed.h's binary256 constants are not this "
                        "tree's format table's (fx256_matches)\n");
        return 2;
    }
    pick_device();
    CK(hipMalloc((void **)&da, chunk * 32)); CK(hipMalloc((void **)&db, chunk * 32));
    CK(hipMalloc((void **)&dc, chunk * 32)); CK(hipMalloc((void **)&dr, chunk));
    CK(hipMalloc((void **)&d1, chunk * 33)); CK(hipMalloc((void **)&d2, chunk * 33));
    CK(hipMalloc((void **)&dcount, sizeof(unsigned)));
    CK(hipMalloc((void **)&dfirst, 8 * sizeof(unsigned long long)));
    f1 = d1 + chunk * 32; f2 = d2 + chunk * 32;
    for (i = 0; i < 4; i++) CK(hipEventCreate(&e[i]));
    for (base = base0; base < base0 + total; base += chunk) {
        const int64_t m = base0 + total - base < chunk ? base0 + total - base : chunk;
        const unsigned g = (unsigned)((m + block - 1) / block);
        CK(hipMemset(dcount, 0, sizeof(unsigned)));
        CK(hipEventRecord(e[0], 0));
        fxd_gen_kernel<<<g, block>>>(f, stream, alu_op, seed, base, m, da, db, dc, dr);
        CK(hipEventRecord(e[1], 0));
        fxd_generic_kernel<<<g, block>>>(f, alu_op, m, da, db, dc, dr, d1, f1);
        CK(hipEventRecord(e[2], 0));
        fxd_fixed_kernel<<<g, block>>>(alu_op, m, da, db, dc, dr, d2, f2, plant);
        CK(hipEventRecord(e[3], 0));
        fxd_cmp_kernel<<<g, block>>>(m, d1, f1, d2, f2, dcount, dfirst);
        CK(hipGetLastError());
        CK(hipMemcpy(&hcount, dcount, sizeof hcount, hipMemcpyDeviceToHost));
        CK(hipEventElapsedTime(&ms, e[0], e[1])); tgen += ms;
        CK(hipEventElapsedTime(&ms, e[1], e[2])); tg += ms;
        CK(hipEventElapsedTime(&ms, e[2], e[3])); tf += ms;
        if (hcount) {
            CK(hipMemcpy(hfirst, dfirst, sizeof hfirst, hipMemcpyDeviceToHost));
            for (i = 0; i < 8 && i < (int64_t)hcount && bad + i < 8; i++)
                firsts[bad + i] = base + (int64_t)hfirst[i];
            bad += hcount;
        }
        if (base == base0) {             /* the first chunk's inputs and outputs, hashed */
            int h;
            CK(hipMemcpy(a, da, m * 32, hipMemcpyDeviceToHost));
            CK(hipMemcpy(b, db, m * 32, hipMemcpyDeviceToHost));
            CK(hipMemcpy(c, dc, m * 32, hipMemcpyDeviceToHost));
            CK(hipMemcpy(r, dr, m, hipMemcpyDeviceToHost));
            CK(hipMemcpy(&o1[0], d1, m * 32, hipMemcpyDeviceToHost));
            CK(hipMemcpy(&o1[chunk * 32], f1, m, hipMemcpyDeviceToHost));
            CK(hipMemcpy(&o2[0], d2, m * 32, hipMemcpyDeviceToHost));
            CK(hipMemcpy(&o2[chunk * 32], f2, m, hipMemcpyDeviceToHost));
            for (h = 0; h < 3; h++) {
                cft_sha256_ctx s;
                uint8_t dg[32];
                cft_sha256_init(&s);
                if (h == 0) {
                    cft_sha256_update(&s, a, m * 32); cft_sha256_update(&s, b, m * 32);
                    cft_sha256_update(&s, c, m * 32); cft_sha256_update(&s, r, m);
                } else {
                    const std::vector<uint8_t> &o = h == 1 ? o1 : o2;
                    cft_sha256_update(&s, &o[0], m * 32);
                    cft_sha256_update(&s, &o[chunk * 32], m);
                }
                cft_sha256_final(&s, dg);
                cft_sha256_hex(dg, hx[h]);
            }
        }
    }
    for (i = 0; i < bad && i < 8 && nshow < 3; i++, nshow++)
        diff_show(&f, seed, firsts[i]);
    printf("diff%s --stream %s: %lld cases from lane %lld, seed %llu, on %s: generic and "
           "fixed differ on %lld; first chunk (%lld cases) sha256 inputs %s, generic %s, "
           "fixed %s; kernel ms: generator %.1f, generic %.1f (%.4g a second), fixed %.1f "
           "(%.4g a second); wall %.1f s; plants %s: %s\n",
           alu_op == CFT_SF_FMA ? "" : alu_op == CFT_SF_ADD ? " --op add (steered)" :
           alu_op == CFT_SF_SUB ? " --op sub (steered)" : " --op mul (steered)",
           stream == FXS_EDGE ? "edge" : "study", (long long)total, (long long)base0,
           (unsigned long long)seed, device_name, (long long)bad, (long long)chunk, hx[0],
           hx[1], hx[2], tgen, tg, total / (tg * 1e-3), tf, total / (tf * 1e-3),
           ms_since(w0) / 1e3,
#ifdef CFT_HIP_PLANTS
           (std::string("PLANTS COMPILED IN, CFT_HIP_PLANT=") + plant_name).c_str(),
#else
           "none compiled in",
#endif
           bad ? "RED" : "GREEN");
    CK(hipFree(da)); CK(hipFree(db)); CK(hipFree(dc)); CK(hipFree(dr));
    CK(hipFree(d1)); CK(hipFree(d2)); CK(hipFree(dcount)); CK(hipFree(dfirst));
    return bad ? 1 : 0;
}

int main(int argc, char **argv)
{
    int i, npos = 0;
    const char *pos[2] = {NULL, NULL};
    long long base = 0;
    const char *pv = getenv("CFT_HIP_PLANT");
#ifdef CFT_HIP_PLANTS
    static const struct { const char *name; unsigned bit; } k_plants[] = {
        {"fixed-rmm", FXS_PL_RMM}, {"fixed-flag", FXS_PL_FLAG},
        {"fixed-steer", FXS_PL_STEER}, {"fixed-mulsign", FXS_PL_MULSIGN}};
    if (pv && *pv) {
        for (const auto &p : k_plants)
            if (!strcmp(pv, p.name)) {
                plant = p.bit;
                plant_name = p.name;
            }
        if (!plant) {
            fprintf(stderr, "hip-fmadiff: CFT_HIP_PLANT=\"%s\": this tool's plants are "
                            "fixed-rmm, fixed-flag, fixed-steer and fixed-mulsign, the four "
                            "of the library's that act on the fixed lane; unset it for none\n",
                    pv);
            return 2;
        }
    }
#else
    if (pv && *pv) {
        fprintf(stderr, "hip-fmadiff: CFT_HIP_PLANT=\"%s\" is set, and this hip-fmadiff is a "
                        "default build, which has no plants: build it with HIP_PLANTS=1, or "
                        "unset the variable\n", pv);
        return 2;
    }
#endif
    if (argc < 2 || strcmp(argv[1], "diff")) {
        fprintf(stderr, "usage: %s diff N SEED [--op add|sub|mul] [--stream study|edge] "
                "[--base B] [--device D] [--block K]\n", argv[0]);
        return 2;
    }
    /* an option this build does not know is refused, never ignored */
    for (i = 2; i < argc; i++) {
        if (!strcmp(argv[i], "--device") && i + 1 < argc) device_index = atoi(argv[++i]);
        else if (!strcmp(argv[i], "--block") && i + 1 < argc) block = atoi(argv[++i]);
        else if (!strcmp(argv[i], "--base") && i + 1 < argc) base = atoll(argv[++i]);
        else if (!strcmp(argv[i], "--op") && i + 1 < argc &&
                 (!strcmp(argv[i + 1], "add") || !strcmp(argv[i + 1], "sub") ||
                  !strcmp(argv[i + 1], "mul"))) {
            i++;
            alu_op = !strcmp(argv[i], "add") ? CFT_SF_ADD : !strcmp(argv[i], "sub")
                     ? CFT_SF_SUB : CFT_SF_MUL;
        } else if (!strcmp(argv[i], "--stream") && i + 1 < argc &&
                   (!strcmp(argv[i + 1], "study") || !strcmp(argv[i + 1], "edge"))) {
            stream = !strcmp(argv[++i], "edge") ? FXS_EDGE : FXS_STUDY;
        } else if (!strncmp(argv[i], "--", 2) || npos == 2) {
            fprintf(stderr, "hip-fmadiff: refused: argument '%s' is not one this build "
                            "knows\n", argv[i]);
            return 2;
        } else {
            pos[npos++] = argv[i];
        }
    }
    if (npos != 2 || atoll(pos[0]) <= 0 || block < 1 || block > 256 || base < 0) {
        fprintf(stderr, "hip-fmadiff: refused: diff needs N > 0 and SEED; --block is 1..256 "
                        "and --base at least 0\n");
        return 2;
    }
    return do_diff(atoll(pos[0]), strtoull(pos[1], NULL, 10), (int64_t)base);
}
