/* Copyright 2026 Logan W.
 * SPDX-License-Identifier: Apache-2.0
 *
 * GPU-A: libcft's fused multiply-add on GPUs through HIP, one thread a
 * lane, from this one source for three targets (build.sh makes each):
 *
 *   cpu      g++ -x c++ -DCFT_GPUA_CPU       no HIP; CFT_HD is empty
 *   nvidia   hipcc -x cu (HIP_PLATFORM=nvidia) HIP over CUDA
 *   amd      hipcc --offload-arch=gfxNNN       HIP over ROCm
 *
 * The arithmetic is not here. It is libcft's: host/src/bigint.c and
 * softfloat.c as devcopy.py copies them (edit E1 alone), included below as
 * one translation unit, and each lane runs what device.c's software
 * backend runs for one element: load a, b, c, cft_sf_compute(CFT_SF_FMA,
 * rnd), store d. -DCFT_GPUA_LIBCFT_C (CPU only) links libcft's own C
 * instead, compiled by gcc from host/src as it is.
 *
 *   cft_fma check CORPUS OUT|- [--device N] [--block B] [--kernel generic|fixed]
 *   cft_fma bench CORPUS [--device N] [--block B] [--reps R] [--lanes N] [--case K]
 *                 [--kernel generic|fixed]
 *   cft_fma diff N SEED [--device N] [--block B]
 *   cft_fma info [--device N]
 *
 * --kernel fixed runs the second kernel (fma256_fixed.h, binary256 only, a
 * second implementation); diff runs both kernels on N cases of the
 * counter-based stream and compares them lane by lane.
 *
 * check writes d || flags (gen_corpus.py's layout), compares it with the
 * golden model's, hashes it with libcft's sha256.c and times it. A lane
 * whose cft_sf_compute refuses writes d = 0 and flags 0x80, so a refusal
 * is a difference, never a silent pass.
 *
 * Preprocessor switches, each the study's to name: CFT_GPUA_CPU (the CPU
 * build: no HIP header, no kernel), CFT_GPUA_LIBCFT_C (libcft's own C
 * linked), and two plants that exist to make the comparison go red:
 * CFT_GPUA_PLANT_RMM_AS_RNE and CFT_GPUA_PLANT_DROP_FLAG=<flag bit>, in
 * both kernels; CFT_GPUA_PLANT_FIXED_RMM_AS_RNE plants the second alone, so
 * that `diff` goes red (fma256_fixed.h).
 * Nothing in this file tests which GPU vendor it is compiled for.
 */
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <algorithm>
#include <chrono>
#include <vector>

#ifdef CFT_GPUA_CPU
#  define CFT_HD
#else
#  include <hip/hip_runtime.h>
#  define CFT_HD __host__ __device__
#endif

#ifdef CFT_GPUA_LIBCFT_C
extern "C" {
#  include "softfloat.h"          /* host/src as it is; bigint.o, softfloat.o */
}
#else
#  include "src/bigint.c"         /* devcopy.py's copy: E1 alone */
#  include "src/softfloat.c"
#endif
#include "sha256.h"               /* host/src as it is; sha256.o */
#include "fma256_fixed.h"         /* the second kernel: NOT libcft's code */

/* One lane: device.c's software loop body for one element. */
CFT_HD static void gpua_fma_lane(const cft_fmt_desc *f, int esz,
                                 const uint8_t *pa, const uint8_t *pb,
                                 const uint8_t *pc, int rnd,
                                 uint8_t *pd, uint8_t *pflags)
{
    cft_bn ba, bb, bc, bo;
    uint32_t fl = 0;
    int k;
    cft_bn_zero(&ba);
    cft_bn_zero(&bb);
    cft_bn_zero(&bc);
    cft_bn_load(&ba, pa, esz);
    cft_bn_load(&bb, pb, esz);
    cft_bn_load(&bc, pc, esz);
#ifdef CFT_GPUA_PLANT_RMM_AS_RNE
    if (rnd == CFT_SF_RMM)
        rnd = CFT_SF_RNE;
#endif
    if (cft_sf_compute(f, CFT_SF_FMA, rnd, &ba, &bb, &bc, &bo, &fl)) {
        for (k = 0; k < esz; k++)
            pd[k] = 0;
        *pflags = 0x80;
        return;
    }
#ifdef CFT_GPUA_PLANT_DROP_FLAG
    fl &= ~(uint32_t)(CFT_GPUA_PLANT_DROP_FLAG);
#endif
    cft_bn_store(&bo, pd, esz);
    *pflags = (uint8_t)fl;
}

#ifndef CFT_GPUA_CPU
__global__ void __launch_bounds__(256)
gpua_fma_kernel(cft_fmt_desc f, int esz, int64_t n,
                const uint8_t *a, const uint8_t *b, const uint8_t *c,
                const uint8_t *rnd, uint8_t *d, uint8_t *flags)
{
    int64_t i = (int64_t)blockIdx.x * blockDim.x + threadIdx.x;
    if (i < n)
        gpua_fma_lane(&f, esz, a + i * esz, b + i * esz, c + i * esz,
                      rnd[i], d + i * esz, flags + i);
}

/* The second kernel (fma256_fixed.h): binary256 only. */
__global__ void __launch_bounds__(256)
gpua_f256_kernel(int64_t n, const uint8_t *a, const uint8_t *b, const uint8_t *c,
                 const uint8_t *rnd, uint8_t *d, uint8_t *flags)
{
    int64_t i = (int64_t)blockIdx.x * blockDim.x + threadIdx.x;
    if (i < n)
        f256_fma_lane(a + i * 32, b + i * 32, c + i * 32, rnd[i], d + i * 32, flags + i);
}
#endif

/* ---- the differential stream (cft_fma diff): counter-based, so lane i of
 * seed S is the same case on every device and on the CPU; weighted to the
 * hard cases. The generic lane makes the cancellation cases' addends. ---- */
CFT_HD static inline uint64_t g_next(uint64_t *s)          /* splitmix64 */
{
    uint64_t z = (*s += 0x9E3779B97F4A7C15ull);
    z = (z ^ (z >> 30)) * 0xBF58476D1CE4E5B9ull;
    z = (z ^ (z >> 27)) * 0x94D049BB133111EBull;
    return z ^ (z >> 31);
}

/* w = an fp256 encoding: sign, biased exponent field, a random fraction */
CFT_HD static inline void g_val(uint64_t *s, uint32_t *w, uint32_t sign, uint32_t ef)
{
    int i;
    for (i = 0; i < 8; i += 2) {
        const uint64_t r = g_next(s);
        w[i] = (uint32_t)r;
        w[i + 1] = (uint32_t)(r >> 32);
    }
    w[7] = (w[7] & 0xFFFu) | (ef & F_EXPF) << 12 | sign << 31;
}

CFT_HD static inline void g_put(const uint32_t *w, uint8_t *p)
{
    int i;
    for (i = 0; i < 32; i++)
        p[i] = (uint8_t)(w[i >> 2] >> (8 * (i & 3)));
}

CFT_HD static inline uint32_t g_clampef(int64_t ef)
{
    return ef < 0 ? 0u : ef > 0x7FFFE ? 0x7FFFEu : (uint32_t)ef;
}

/* One special of sixteen: zeros, infinities, NaNs (quiet, signalling, with a
 * payload), ones, the largest normal, the smallest normal and subnormals. */
CFT_HD static inline void g_special(uint64_t *s, uint32_t *w)
{
    const uint32_t k = (uint32_t)(g_next(s) % 16u), sg = k & 1u;
    int i;
    for (i = 0; i < 8; i++) w[i] = 0;
    switch (k >> 1) {
    case 0: break;                                                  /* zero */
    case 1: w[7] = 0x7FFFF000u; break;                              /* inf */
    case 2: w[7] = sg ? 0x7FFFF000u : 0x7FFFF800u; w[0] = 1; break; /* sNaN, qNaN+1 */
    case 3: w[7] = (uint32_t)F_BIAS << 12; break;                   /* one */
    case 4: for (i = 0; i < 7; i++) w[i] = 0xFFFFFFFFu;
            w[7] = 0x7FFFE000u | 0xFFFu; break;                     /* max normal */
    case 5: w[7] = 1u << 12; break;                                 /* min normal */
    case 6: w[0] = 1; break;                                        /* min subnormal */
    default: for (i = 0; i < 7; i++) w[i] = 0xFFFFFFFFu;
             w[7] = 0xFFFu; break;                                  /* max subnormal */
    }
    if (k >> 1 != 2) w[7] |= sg << 31;
}

/* Case i of the stream under seed: nine families, a rounding attribute each.
 * f is binary256's descriptor (cft_sf_formats[3], passed by value to a GPU). */
CFT_HD static void gpua_gen_case(const cft_fmt_desc *f, uint64_t seed, int64_t i,
                                 uint8_t *pa, uint8_t *pb, uint8_t *pc, uint8_t *prnd)
{
    uint64_t s = seed ^ ((uint64_t)i * 0xD1B54A32D192ED03ull);
    uint32_t wa[8], wb[8], wc[8], sa, sb, sc;
    const uint32_t fam = (uint32_t)(g_next(&s) % 9u);
    const int rnd = (int)(g_next(&s) % 5u);
    const int64_t B = F_BIAS;
    int k;
    sa = (uint32_t)g_next(&s) & 1u; sb = (uint32_t)g_next(&s) & 1u; sc = (uint32_t)g_next(&s) & 1u;
    switch (fam) {
    case 0:                                         /* raw bits */
        g_val(&s, wa, sa, (uint32_t)g_next(&s)); g_val(&s, wb, sb, (uint32_t)g_next(&s));
        g_val(&s, wc, sc, (uint32_t)g_next(&s));
        break;
    case 1:                                         /* operands at the subnormal edge */
        g_val(&s, wa, sa, (uint32_t)(g_next(&s) % 3)); g_val(&s, wb, sb, (uint32_t)(g_next(&s) % 3));
        g_val(&s, wc, sc, (uint32_t)(g_next(&s) % 3));
        break;
    case 2: case 3: {                               /* products at the underflow / overflow edge */
        const int64_t t = fam == 2 ? F_EMIN - 240 + (int64_t)(g_next(&s) % 243)
                                   : F_EMAX - 2 + (int64_t)(g_next(&s) % 4);
        const int64_t ea = fam == 2 ? 1 + (int64_t)(g_next(&s) % 262000)
                                    : B + 1 + (int64_t)(g_next(&s) % 262000);
        g_val(&s, wa, sa, (uint32_t)ea);
        g_val(&s, wb, sb, g_clampef(t + 2 * B - ea));
        g_val(&s, wc, sc, fam == 2 ? 0u : 0x7FFFC + (uint32_t)(g_next(&s) % 3));
        if (g_next(&s) & 1u)
            for (k = 0; k < 8; k++) wc[k] = k == 7 ? sc << 31 : 0u;      /* c = +-0 */
        break;
    }
    case 4: case 7: {                               /* deep and exact cancellation */
        uint8_t ta[32], tb[32], tz[32] = {0}, tp[32], tf;
        g_val(&s, wa, sa, (uint32_t)(B - 32 + (int64_t)(g_next(&s) % 64)));
        g_val(&s, wb, sb, (uint32_t)(B - 32 + (int64_t)(g_next(&s) % 64)));
        if (fam == 7)                               /* short significands: a*b exact */
            for (k = 0; k < 4; k++) { wa[k] = 0; wb[k] = 0; }
        g_put(wa, ta); g_put(wb, tb);
        gpua_fma_lane(f, 32, ta, tb, tz, rnd, tp, &tf);
        for (k = 0; k < 8; k++)
            wc[k] = (uint32_t)tp[4 * k] | (uint32_t)tp[4 * k + 1] << 8 |
                    (uint32_t)tp[4 * k + 2] << 16 | (uint32_t)tp[4 * k + 3] << 24;
        wc[7] ^= 1u << 31;                          /* c = -(a*b rounded) */
        if (fam == 4 && (g_next(&s) & 1u))
            wc[0] += (uint32_t)(g_next(&s) % 5) - 2u;          /* a few ulps off */
        break;
    }
    case 5: {                                       /* exact ties, normal and subnormal */
        const int sub = (int)(g_next(&s) & 1u);
        const int t = sub ? 1 + (int)(g_next(&s) % 200) : 0;
        const int kk = 1 + (int)(g_next(&s) % (uint64_t)(236 - t)), jj = 237 - t - kk;
        const int64_t pe = sub ? F_EMIN - t : (int64_t)(g_next(&s) % 4000) - 2000;
        const int64_t ea = (pe / 2) + B, eb = pe - pe / 2 + B;
        for (k = 0; k < 8; k++) { wa[k] = 0; wb[k] = 0; wc[k] = 0; }
        wa[(236 - kk) >> 5] |= 1u << ((236 - kk) & 31);
        wb[(236 - jj) >> 5] |= 1u << ((236 - jj) & 31);
        wa[7] |= (uint32_t)ea << 12 | sa << 31;
        wb[7] |= (uint32_t)eb << 12 | sb << 31;
        wc[7] = sc << 31;                           /* c = +-0 */
        break;
    }
    case 6: {                                       /* c swept across the alignment window */
        const int64_t ea = B - 131072 + (int64_t)(g_next(&s) % 262144);
        const int64_t eb = B - 131072 + (int64_t)(g_next(&s) % 262144);
        const int64_t d = (int64_t)(g_next(&s) % (2 * 514 + 1)) - 514;
        g_val(&s, wa, sa, (uint32_t)ea); g_val(&s, wb, sb, (uint32_t)eb);
        g_val(&s, wc, sc, g_clampef(ea + eb - B + d));
        break;
    }
    default:                                        /* specials in every slot */
        g_special(&s, wa); g_special(&s, wb); g_special(&s, wc);
        break;
    }
    g_put(wa, pa); g_put(wb, pb); g_put(wc, pc);
    *prnd = (uint8_t)rnd;
}

#ifndef CFT_GPUA_CPU
__global__ void __launch_bounds__(256)
gpua_gen_kernel(cft_fmt_desc f, uint64_t seed, int64_t base, int64_t n, uint8_t *a,
                uint8_t *b, uint8_t *c, uint8_t *rnd)
{
    int64_t i = (int64_t)blockIdx.x * blockDim.x + threadIdx.x;
    if (i < n)
        gpua_gen_case(&f, seed, base + i, a + i * 32, b + i * 32, c + i * 32, rnd + i);
}

/* Lanes where the two kernels differ: counted by an atomic (an integer sum,
 * whose order cannot change it), the first eight indices kept. */
__global__ void gpua_cmp_kernel(int64_t n, const uint8_t *d1, const uint8_t *f1,
                                const uint8_t *d2, const uint8_t *f2, unsigned *count,
                                unsigned long long *first)
{
    int64_t i = (int64_t)blockIdx.x * blockDim.x + threadIdx.x;
    int k, bad;
    if (i >= n)
        return;
    bad = f1[i] != f2[i];
    for (k = 0; k < 32; k++)
        bad |= d1[i * 32 + k] != d2[i * 32 + k];
    if (bad) {
        unsigned c = atomicAdd(count, 1u);
        if (c < 8)
            first[c] = (unsigned long long)i;
    }
}

#define CK(x) do { hipError_t e_ = (x); if (e_ != hipSuccess) { \
    fprintf(stderr, "%s:%d: %s: %s\n", __FILE__, __LINE__, #x, \
            hipGetErrorString(e_)); exit(2); } } while (0)
#endif

typedef std::chrono::steady_clock clk;
static double ms_since(clk::time_point t0)
{
    return std::chrono::duration<double, std::milli>(clk::now() - t0).count();
}

struct corpus {
    std::vector<uint8_t> raw;
    int fmt, esz;
    int64_t n;
    const uint8_t *a, *b, *c, *rnd, *d, *fl;
};

static void load_corpus(const char *path, corpus *cp)
{
    FILE *fp = fopen(path, "rb");
    uint8_t buf[1 << 16];
    size_t got;
    uint32_t h32[2];
    if (!fp) { fprintf(stderr, "cannot open %s\n", path); exit(2); }
    while ((got = fread(buf, 1, sizeof buf, fp)) > 0)
        cp->raw.insert(cp->raw.end(), buf, buf + got);
    fclose(fp);
    if (cp->raw.size() < 24 || memcmp(cp->raw.data(), "CFTGPUA1", 8)) {
        fprintf(stderr, "%s: not a GPU-A corpus\n", path); exit(2);
    }
    memcpy(h32, cp->raw.data() + 8, 8);
    memcpy(&cp->n, cp->raw.data() + 16, 8);
    cp->fmt = (int)h32[0];
    cp->esz = (int)h32[1];
    if (cp->fmt < 0 || cp->fmt > 3 || cp->esz != cft_sf_formats[cp->fmt].width / 8 ||
        (uint64_t)cp->raw.size() != 24 + (uint64_t)cp->n * (4 * cp->esz + 2)) {
        fprintf(stderr, "%s: header does not match its size\n", path); exit(2);
    }
    cp->a = cp->raw.data() + 24;
    cp->b = cp->a + cp->n * cp->esz;
    cp->c = cp->b + cp->n * cp->esz;
    cp->rnd = cp->c + cp->n * cp->esz;
    cp->d = cp->rnd + cp->n;
    cp->fl = cp->d + cp->n * cp->esz;
}

static void hexle(const uint8_t *p, int esz, char *out)    /* big-endian text */
{
    int i;
    for (i = 0; i < esz; i++)
        sprintf(out + 2 * i, "%02x", p[esz - 1 - i]);
}

static int device_index = 0, block = 128, reps = 10;
static int kernel_fixed = 0;              /* --kernel fixed: fma256_fixed.h's */
static int64_t lanes = 0, one_case = -1;   /* --case K: every lane runs case K */
static char device_name[320] = "cpu, one thread";

/* Run n lanes of the corpus's inputs (lane i reads case i mod cp->n, or
 * case K for every lane under --case K, which takes divergence away) into
 * out (d || flags). kernel_ms gets the kernel's time (events on a GPU, the
 * loop on the CPU); the return value is the end-to-end time, transfers in. */
static double run_lanes(const corpus *cp, int64_t n, uint8_t *out, double *kernel_ms)
{
    const cft_fmt_desc f = cft_sf_formats[cp->fmt];
    const int esz = cp->esz;
    std::vector<uint8_t> in;
    const uint8_t *a = cp->a, *b = cp->b, *c = cp->c, *r = cp->rnd;
    if (n != cp->n || one_case >= 0) {    /* replicate the inputs to n lanes */
        int64_t i;
        in.resize((size_t)n * (3 * esz + 1));
        for (i = 0; i < n; i++) {
            int64_t s = one_case >= 0 ? one_case % cp->n : i % cp->n;
            memcpy(&in[(size_t)(i * esz)], cp->a + s * esz, esz);
            memcpy(&in[(size_t)((n + i) * esz)], cp->b + s * esz, esz);
            memcpy(&in[(size_t)((2 * n + i) * esz)], cp->c + s * esz, esz);
            in[(size_t)(3 * n * esz + i)] = cp->rnd[s];
        }
        a = &in[0]; b = a + n * esz; c = b + n * esz; r = c + n * esz;
    }
#ifdef CFT_GPUA_CPU
    clk::time_point t0 = clk::now();
    for (int64_t i = 0; i < n; i++) {
        if (kernel_fixed)
            f256_fma_lane(a + i * esz, b + i * esz, c + i * esz, r[i], out + i * esz,
                          out + n * esz + i);
        else
            gpua_fma_lane(&f, esz, a + i * esz, b + i * esz, c + i * esz, r[i],
                          out + i * esz, out + n * esz + i);
    }
    *kernel_ms = ms_since(t0);
    return *kernel_ms;
#else
    uint8_t *da, *db, *dc, *dr, *dd, *dfl;
    hipEvent_t e0, e1;
    float kms = 0;
    const size_t vb = (size_t)n * esz;
    CK(hipMalloc((void **)&da, vb)); CK(hipMalloc((void **)&db, vb));
    CK(hipMalloc((void **)&dc, vb)); CK(hipMalloc((void **)&dr, (size_t)n));
    CK(hipMalloc((void **)&dd, vb)); CK(hipMalloc((void **)&dfl, (size_t)n));
    CK(hipEventCreate(&e0)); CK(hipEventCreate(&e1));
    CK(hipDeviceSynchronize());
    clk::time_point t0 = clk::now();
    CK(hipMemcpy(da, a, vb, hipMemcpyHostToDevice));
    CK(hipMemcpy(db, b, vb, hipMemcpyHostToDevice));
    CK(hipMemcpy(dc, c, vb, hipMemcpyHostToDevice));
    CK(hipMemcpy(dr, r, (size_t)n, hipMemcpyHostToDevice));
    CK(hipEventRecord(e0, 0));
    if (kernel_fixed)
        gpua_f256_kernel<<<(unsigned)((n + block - 1) / block), block>>>(n, da, db, dc, dr,
                                                                        dd, dfl);
    else
        gpua_fma_kernel<<<(unsigned)((n + block - 1) / block), block>>>(f, esz, n, da, db,
                                                                       dc, dr, dd, dfl);
    CK(hipGetLastError());
    CK(hipEventRecord(e1, 0));
    CK(hipMemcpy(out, dd, vb, hipMemcpyDeviceToHost));
    CK(hipMemcpy(out + vb, dfl, (size_t)n, hipMemcpyDeviceToHost));
    double e2e = ms_since(t0);
    CK(hipEventElapsedTime(&kms, e0, e1));
    *kernel_ms = kms;
    CK(hipFree(da)); CK(hipFree(db)); CK(hipFree(dc)); CK(hipFree(dr));
    CK(hipFree(dd)); CK(hipFree(dfl));
    CK(hipEventDestroy(e0)); CK(hipEventDestroy(e1));
    return e2e;
#endif
}

static void pick_device(void)
{
#ifndef CFT_GPUA_CPU
    hipDeviceProp_t p;
    char bus[32] = {0};
    /* Zeroed first: HIP 7.2.4 on NVIDIA leaves gcnArchName unwritten, so
     * without this the name carries whatever the stack held. An AMD
     * device is told by its "gfx" name, not by a platform test. */
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
#endif
}

/* The fixed kernel is binary256's alone; any other corpus is refused by name. */
static int fixed_fits(const corpus *cp, const char *cpath)
{
    if (kernel_fixed && cp->fmt != 3) {
        fprintf(stderr, "refused: the fixed kernel is binary256 only, and %s is %s\n", cpath,
                cft_sf_formats[cp->fmt].name);
        return 0;
    }
    return 1;
}

static int do_check(const char *cpath, const char *opath)
{
    corpus cp;
    int64_t i, dbad = 0, fbad = 0, refused = 0, per[5] = {0}, perbad[5] = {0}, shown = 0;
    double kms, e2e;
    uint8_t hash[32];
    char hex[65];
    cft_sha256_ctx s;
    load_corpus(cpath, &cp);
    if (!fixed_fits(&cp, cpath))
        return 2;
    std::vector<uint8_t> out((size_t)cp.n * (cp.esz + 1));
    pick_device();
    e2e = run_lanes(&cp, cp.n, out.data(), &kms);
    for (i = 0; i < cp.n; i++) {
        const uint8_t *gd = &out[(size_t)(i * cp.esz)];
        uint8_t gf = out[(size_t)(cp.n * cp.esz + i)];
        int rd = cp.rnd[i] < 5 ? cp.rnd[i] : 0;
        int bad_d = memcmp(gd, cp.d + i * cp.esz, cp.esz) != 0;
        int bad_f = gf != cp.fl[i];
        per[rd]++;
        dbad += bad_d; fbad += bad_f; refused += (gf & 0x80) != 0;
        perbad[rd] += bad_d || bad_f;
        if ((bad_d || bad_f) && shown++ < 5) {
            char ha[65], hb[65], hc[65], hg[65], hw[65];
            hexle(cp.a + i * cp.esz, cp.esz, ha); hexle(cp.b + i * cp.esz, cp.esz, hb);
            hexle(cp.c + i * cp.esz, cp.esz, hc); hexle(gd, cp.esz, hg);
            hexle(cp.d + i * cp.esz, cp.esz, hw);
            printf("  DIFF case %lld rnd %d: a %s b %s c %s\n       got d %s flags 0x%02x\n"
                   "      want d %s flags 0x%02x\n", (long long)i, cp.rnd[i], ha, hb, hc,
                   hg, gf, hw, cp.fl[i]);
        }
    }
    cft_sha256_init(&s);
    cft_sha256_update(&s, out.data(), out.size());
    cft_sha256_final(&s, hash);
    cft_sha256_hex(hash, hex);
    if (opath) {
        FILE *fp = fopen(opath, "wb");
        if (!fp || fwrite(out.data(), 1, out.size(), fp) != out.size()) {
            fprintf(stderr, "cannot write %s\n", opath); exit(2);
        }
        fclose(fp);
    }
    printf("check: %s%s on %s: %s, %lld cases (rne %lld rtz %lld rdn %lld rup %lld rmm %lld);"
           " %lld results and %lld flags differ, %lld refused; differing by attribute "
           "%lld/%lld/%lld/%lld/%lld; sha256 %s; kernel %.3f ms, end to end %.3f ms: %s\n",
           cpath, kernel_fixed ? " [fixed kernel]" : "", device_name,
           cft_sf_formats[cp.fmt].name, (long long)cp.n,
           (long long)per[0], (long long)per[1], (long long)per[2], (long long)per[3],
           (long long)per[4], (long long)dbad, (long long)fbad, (long long)refused,
           (long long)perbad[0], (long long)perbad[1], (long long)perbad[2],
           (long long)perbad[3], (long long)perbad[4], hex, kms, e2e,
           dbad || fbad ? "RED" : "GREEN");
    return dbad || fbad ? 1 : 0;
}

static int do_bench(const char *cpath)
{
    corpus cp;
    int k;
    load_corpus(cpath, &cp);
    if (!fixed_fits(&cp, cpath))
        return 2;
    const int64_t n = lanes ? lanes : cp.n;
    std::vector<uint8_t> out((size_t)n * (cp.esz + 1));
    std::vector<double> km, ee;
    double kms;
    pick_device();
    run_lanes(&cp, n, out.data(), &kms);              /* warm-up, not counted */
    for (k = 0; k < reps; k++) {
        ee.push_back(run_lanes(&cp, n, out.data(), &kms));
        km.push_back(kms);
    }
    std::sort(km.begin(), km.end());
    std::sort(ee.begin(), ee.end());
    double km_med = km[km.size() / 2], ee_med = ee[ee.size() / 2];
    printf("bench: %s%s%s on %s: %s, %lld lanes, block %d, %d reps; kernel ms min %.3f median "
           "%.3f max %.3f; end to end ms min %.3f median %.3f max %.3f; %.4g FMA/s kernel, "
           "%.4g FMA/s end to end (medians); %.1f ns a lane\n", cpath,
           kernel_fixed ? " [fixed kernel]" : "",
           one_case >= 0 ? " (every lane one case)" : "", device_name,
           cft_sf_formats[cp.fmt].name, (long long)n, block, reps, km.front(), km_med,
           km.back(), ee.front(), ee_med, ee.back(), n / (km_med * 1e-3),
           n / (ee_med * 1e-3), km_med * 1e6 / n);
    return 0;
}

static int do_info(void)
{
#ifdef CFT_GPUA_CPU
    printf("info: the CPU build has no device; sizeof(cft_bn) %d, CFT_BN_LIMBS %d\n",
           (int)sizeof(cft_bn), (int)CFT_BN_LIMBS);
#else
    hipDeviceProp_t p;
    hipFuncAttributes fa;
    size_t stack0 = 0, stack1 = 0;
    int bs;
    pick_device();
    CK(hipGetDeviceProperties(&p, device_index));
    CK(hipFuncGetAttributes(&fa, (const void *)gpua_fma_kernel));
    CK(hipDeviceGetLimit(&stack0, hipLimitStackSize));
    printf("info: %s: %d CUs/SMs, warp %d, max threads/CU %d, regs/block %d, "
           "clock %d kHz (not controlled)\n", device_name, p.multiProcessorCount,
           p.warpSize, p.maxThreadsPerMultiProcessor, p.regsPerBlock, p.clockRate);
    printf("info: kernel: %d registers a thread, %d bytes local (private) a thread, "
           "%d bytes shared, max %d threads a block; sizeof(cft_bn) %d, CFT_BN_LIMBS %d\n",
           fa.numRegs, (int)fa.localSizeBytes, (int)fa.sharedSizeBytes,
           fa.maxThreadsPerBlock, (int)sizeof(cft_bn), (int)CFT_BN_LIMBS);
    for (bs = 32; bs <= 256; bs *= 2) {
        int nb = 0;
        CK(hipOccupancyMaxActiveBlocksPerMultiprocessor(&nb, gpua_fma_kernel, bs, 0));
        printf("info: block %d: %d blocks a CU/SM resident, %d threads, occupancy %.1f %%\n",
               bs, nb, nb * bs, 100.0 * nb * bs / p.maxThreadsPerMultiProcessor);
    }
    CK(hipFuncGetAttributes(&fa, (const void *)gpua_f256_kernel));
    printf("info: fixed kernel: %d registers a thread, %d bytes local (private) a thread\n",
           fa.numRegs, (int)fa.localSizeBytes);
    for (bs = 32; bs <= 256; bs *= 2) {
        int nb = 0;
        CK(hipOccupancyMaxActiveBlocksPerMultiprocessor(&nb, gpua_f256_kernel, bs, 0));
        printf("info: fixed kernel, block %d: %d blocks a CU/SM resident, occupancy %.1f %%\n",
               bs, nb, 100.0 * nb * bs / p.maxThreadsPerMultiProcessor);
    }
    /* One launch of no lanes, then the limit again: does the runtime raise
     * a thread's stack to the kernel's frame by itself? */
    gpua_fma_kernel<<<1, 1>>>(cft_sf_formats[3], 32, 0, NULL, NULL, NULL, NULL, NULL, NULL);
    CK(hipGetLastError());
    CK(hipDeviceSynchronize());
    CK(hipDeviceGetLimit(&stack1, hipLimitStackSize));
    printf("info: stack limit a thread: %zu bytes before any launch, %zu after one\n",
           stack0, stack1);
#endif
    return 0;
}

static void diff_show(const cft_fmt_desc *f, uint64_t seed, int64_t i)
{
    uint8_t a[32], b[32], c[32], r, d1[32], d2[32], f1, f2;
    char ha[65], hb[65], hc[65], h1[65], h2[65];
    gpua_gen_case(f, seed, i, a, b, c, &r);           /* recomputed on the host */
    gpua_fma_lane(f, 32, a, b, c, r, d1, &f1);
    f256_fma_lane(a, b, c, r, d2, &f2);
    hexle(a, 32, ha); hexle(b, 32, hb); hexle(c, 32, hc); hexle(d1, 32, h1); hexle(d2, 32, h2);
    printf("  DIFF lane %lld rnd %d: a %s b %s c %s\n     generic d %s flags 0x%02x\n"
           "       fixed d %s flags 0x%02x\n", (long long)i, r, ha, hb, hc, h1, f1, h2, f2);
}

/* The differential stream: `total` cases from the counter-based generator
 * (lanes 0..total-1 of `seed`), both kernels on each, compared lane by lane,
 * in chunks of at most 2^21 lanes (326 MB of device memory). The first
 * chunk's inputs and both outputs are hashed, so devices can be compared. */
static int do_diff(int64_t total, uint64_t seed)
{
    const cft_fmt_desc f = cft_sf_formats[3];
    const int64_t chunk = total < ((int64_t)1 << 21) ? total : ((int64_t)1 << 21);
    int64_t base, i, bad = 0, nshow = 0, firsts[8];
    double tgen = 0, tg = 0, tf = 0;
    char hx[3][65];
    std::vector<uint8_t> in((size_t)chunk * 97), o1((size_t)chunk * 33), o2((size_t)chunk * 33);
    uint8_t *a = &in[0], *b = a + chunk * 32, *c = b + chunk * 32, *r = c + chunk * 32;
    pick_device();
#ifndef CFT_GPUA_CPU
    uint8_t *da, *db, *dc, *dr, *d1, *f1, *d2, *f2;
    unsigned *dcount, hcount;
    unsigned long long *dfirst, hfirst[8];
    hipEvent_t e[4];
    float ms;
    CK(hipMalloc((void **)&da, chunk * 32)); CK(hipMalloc((void **)&db, chunk * 32));
    CK(hipMalloc((void **)&dc, chunk * 32)); CK(hipMalloc((void **)&dr, chunk));
    CK(hipMalloc((void **)&d1, chunk * 33)); CK(hipMalloc((void **)&d2, chunk * 33));
    CK(hipMalloc((void **)&dcount, sizeof(unsigned)));
    CK(hipMalloc((void **)&dfirst, 8 * sizeof(unsigned long long)));
    f1 = d1 + chunk * 32; f2 = d2 + chunk * 32;
    for (i = 0; i < 4; i++) CK(hipEventCreate(&e[i]));
#endif
    for (base = 0; base < total; base += chunk) {
        const int64_t m = total - base < chunk ? total - base : chunk;
#ifdef CFT_GPUA_CPU
        clk::time_point t0 = clk::now();
        for (i = 0; i < m; i++)
            gpua_gen_case(&f, seed, base + i, a + i * 32, b + i * 32, c + i * 32, r + i);
        tgen += ms_since(t0); t0 = clk::now();
        for (i = 0; i < m; i++)
            gpua_fma_lane(&f, 32, a + i * 32, b + i * 32, c + i * 32, r[i], &o1[i * 32],
                          &o1[chunk * 32 + i]);
        tg += ms_since(t0); t0 = clk::now();
        for (i = 0; i < m; i++)
            f256_fma_lane(a + i * 32, b + i * 32, c + i * 32, r[i], &o2[i * 32],
                          &o2[chunk * 32 + i]);
        tf += ms_since(t0);
        for (i = 0; i < m; i++)
            if (memcmp(&o1[i * 32], &o2[i * 32], 32) || o1[chunk * 32 + i] != o2[chunk * 32 + i]) {
                if (bad < 8) firsts[bad] = base + i;
                bad++;
            }
#else
        const unsigned g = (unsigned)((m + block - 1) / block);
        CK(hipMemset(dcount, 0, sizeof(unsigned)));
        CK(hipEventRecord(e[0], 0));
        gpua_gen_kernel<<<g, block>>>(f, seed, base, m, da, db, dc, dr);
        CK(hipEventRecord(e[1], 0));
        gpua_fma_kernel<<<g, block>>>(f, 32, m, da, db, dc, dr, d1, f1);
        CK(hipEventRecord(e[2], 0));
        gpua_f256_kernel<<<g, block>>>(m, da, db, dc, dr, d2, f2);
        CK(hipEventRecord(e[3], 0));
        gpua_cmp_kernel<<<g, block>>>(m, d1, f1, d2, f2, dcount, dfirst);
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
        if (base == 0) {
            CK(hipMemcpy(a, da, m * 32, hipMemcpyDeviceToHost));
            CK(hipMemcpy(b, db, m * 32, hipMemcpyDeviceToHost));
            CK(hipMemcpy(c, dc, m * 32, hipMemcpyDeviceToHost));
            CK(hipMemcpy(r, dr, m, hipMemcpyDeviceToHost));
            CK(hipMemcpy(&o1[0], d1, m * 32, hipMemcpyDeviceToHost));
            CK(hipMemcpy(&o1[chunk * 32], f1, m, hipMemcpyDeviceToHost));
            CK(hipMemcpy(&o2[0], d2, m * 32, hipMemcpyDeviceToHost));
            CK(hipMemcpy(&o2[chunk * 32], f2, m, hipMemcpyDeviceToHost));
        }
#endif
        if (base == 0) {                 /* the first chunk's inputs and outputs, hashed */
            const uint8_t *parts[3][2] = {{a, NULL}, {&o1[0], &o1[chunk * 32]},
                                          {&o2[0], &o2[chunk * 32]}};
            int h;
            for (h = 0; h < 3; h++) {
                cft_sha256_ctx s;
                uint8_t dg[32];
                cft_sha256_init(&s);
                if (h == 0) {
                    cft_sha256_update(&s, a, m * 32); cft_sha256_update(&s, b, m * 32);
                    cft_sha256_update(&s, c, m * 32); cft_sha256_update(&s, r, m);
                } else {
                    cft_sha256_update(&s, parts[h][0], m * 32);
                    cft_sha256_update(&s, parts[h][1], m);
                }
                cft_sha256_final(&s, dg);
                cft_sha256_hex(dg, hx[h]);
            }
        }
    }
    for (i = 0; i < bad && i < 8 && nshow < 3; i++, nshow++)
        diff_show(&f, seed, firsts[i]);
    printf("diff: %lld cases, seed %llu, on %s: generic and fixed differ on %lld; first chunk "
           "(%lld cases) sha256 inputs %s, generic %s, fixed %s; kernel ms: generator %.1f, "
           "generic %.1f (%.4g FMA/s), fixed %.1f (%.4g FMA/s): %s\n", (long long)total,
           (unsigned long long)seed, device_name, (long long)bad, (long long)chunk, hx[0], hx[1],
           hx[2], tgen, tg, total / (tg * 1e-3), tf, total / (tf * 1e-3), bad ? "RED" : "GREEN");
#ifndef CFT_GPUA_CPU
    CK(hipFree(da)); CK(hipFree(db)); CK(hipFree(dc)); CK(hipFree(dr));
    CK(hipFree(d1)); CK(hipFree(d2)); CK(hipFree(dcount)); CK(hipFree(dfirst));
#endif
    return bad ? 1 : 0;
}

int main(int argc, char **argv)
{
    int i;
    const char *pos[2] = {NULL, NULL};
    int npos = 0;
    if (argc < 2) {
        fprintf(stderr, "usage: %s check CORPUS OUT|- | bench CORPUS | diff N SEED | info "
                "[--device N] [--block B] [--reps R] [--lanes N] [--case K] "
                "[--kernel generic|fixed]\n", argv[0]);
        return 2;
    }
    /* An option this build does not know is refused, never ignored: a
     * timing taken with a flag silently dropped measures something else. */
    for (i = 2; i < argc; i++) {
        if (!strcmp(argv[i], "--device") && i + 1 < argc) device_index = atoi(argv[++i]);
        else if (!strcmp(argv[i], "--block") && i + 1 < argc) block = atoi(argv[++i]);
        else if (!strcmp(argv[i], "--reps") && i + 1 < argc) reps = atoi(argv[++i]);
        else if (!strcmp(argv[i], "--lanes") && i + 1 < argc) lanes = atoll(argv[++i]);
        else if (!strcmp(argv[i], "--case") && i + 1 < argc) one_case = atoll(argv[++i]);
        else if (!strcmp(argv[i], "--kernel") && i + 1 < argc &&
                 (!strcmp(argv[i + 1], "fixed") || !strcmp(argv[i + 1], "generic")))
            kernel_fixed = !strcmp(argv[++i], "fixed");
        else if (!strncmp(argv[i], "--", 2) || npos == 2) {
            fprintf(stderr, "refused: argument '%s' is not one this build knows\n", argv[i]);
            return 2;
        } else
            pos[npos++] = argv[i];
    }
    if (block < 1 || block > 256 || reps < 1) {
        fprintf(stderr, "refused: --block is 1..256 and --reps at least 1\n");
        return 2;
    }
    if (!strcmp(argv[1], "check") && npos == 2)
        return do_check(pos[0], strcmp(pos[1], "-") ? pos[1] : NULL);
    if (!strcmp(argv[1], "bench") && npos == 1)
        return do_bench(pos[0]);
    if (!strcmp(argv[1], "diff") && npos == 2 && atoll(pos[0]) > 0)
        return do_diff(atoll(pos[0]), strtoull(pos[1], NULL, 10));
    if (!strcmp(argv[1], "info") && npos == 0)
        return do_info();
    fprintf(stderr, "refused: unknown command or wrong number of arguments\n");
    return 2;
}
