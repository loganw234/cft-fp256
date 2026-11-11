/* Copyright 2026 Logan W.
 * SPDX-License-Identifier: Apache-2.0
 *
 * GPU-D: libcft's fused multiply-add through OpenCL 1.2, one work-item a
 * lane: GPU-A's cft_fma.hip harness (check, bench, info) over the OpenCL
 * host API, one C source for Linux and macOS (the header's name is the one
 * platform line). The arithmetic is not here: it is the text oclcopy.py
 * writes (libcft's host/src through devcopy.py, plus GPU-A's lane and
 * fma_kernel.cl), read at run time and built by clCreateProgramWithSource.
 *
 *   cft_fma_ocl check CORPUS OUT|-   compare with the golden model, hash, time
 *   cft_fma_ocl bench CORPUS         one warm-up, then --reps timed runs
 *   cft_fma_ocl info                 the device and the built kernel
 *   options: --platform N --device N --reps R --lanes N --cl FILE --opts S,
 *            and --wg N, a work-group smaller than the kernel's (experiments)
 *
 * Build options are "-cl-std=CL1.2" and --opts after it; GPU-A's plants
 * are its macros as options (--opts -DCFT_GPUA_PLANT_RMM_AS_RNE, or
 * -DCFT_GPUA_PLANT_DROP_FLAG=8). Every run prints, before its last line,
 * the text's sha256 (libcft's sha256.c), the options, the build's time and
 * log, the work-group size, which is the kernel's own
 * CL_KERNEL_WORK_GROUP_SIZE on that device, and the time of a first launch
 * of one lane (a compile at first launch lands there). Kernel time is the profiling
 * event's start to end; end to end is the host clock over the writes, the
 * kernel and the reads, as GPU-A's. check's last line has GPU-A's form,
 * and its output file GPU-A's layout (d || flags), so GPU-A's expected
 * hashes and gen_corpus.py verify apply unchanged. A lane whose
 * cft_sf_compute refuses writes d = 0 and flags 0x80, a difference.
 */
#ifndef __APPLE__
#  define _POSIX_C_SOURCE 200809L          /* clock_gettime */
#endif
#define CL_TARGET_OPENCL_VERSION 120
#ifdef __APPLE__
#  define CL_SILENCE_DEPRECATION
#  include <OpenCL/opencl.h>
#else
#  include <CL/cl.h>
#endif
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include "sha256.h"                    /* host/src as it is; sha256.o */

#define CK(x) do { cl_int e_ = (x); if (e_ != CL_SUCCESS) { \
    fprintf(stderr, "%s:%d: %s: OpenCL error %d\n", __FILE__, __LINE__, #x, \
            (int)e_); exit(2); } } while (0)

static const struct { const char *name; int esz; } FMT[4] = {
    {"fp32", 4}, {"fp64", 8}, {"fp128", 16}, {"fp256", 32}};

static int plat_index = 0, dev_index = 0, reps = 10;
static long long lanes = 0, wg_req = 0;   /* --wg N: a smaller work-group than the kernel's */
static const char *cl_path = "cft_fma.cl";
static char opts[1024] = "-cl-std=CL1.2";
static char device_name[640];
static cl_device_id dev;
static cl_context ctx;
static cl_command_queue q;
static cl_program prog;
static cl_kernel kern;
static size_t wg;

static double now_ms(void)
{
    struct timespec t;
    clock_gettime(CLOCK_MONOTONIC, &t);
    return t.tv_sec * 1e3 + t.tv_nsec * 1e-6;
}

static uint8_t *read_file(const char *path, size_t *n)
{
    FILE *fp = fopen(path, "rb");
    uint8_t *p = NULL;
    long len;
    if (!fp || fseek(fp, 0, SEEK_END) || (len = ftell(fp)) < 0 || fseek(fp, 0, SEEK_SET) ||
        !(p = malloc((size_t)len + 1)) || fread(p, 1, (size_t)len, fp) != (size_t)len) {
        fprintf(stderr, "cannot read %s\n", path);
        exit(2);
    }
    fclose(fp);
    p[len] = 0;
    *n = (size_t)len;
    return p;
}

static void sha_hex(const uint8_t *p, size_t n, char hex[65])
{
    cft_sha256_ctx s;
    uint8_t h[32];
    cft_sha256_init(&s);
    cft_sha256_update(&s, p, n);
    cft_sha256_final(&s, h);
    cft_sha256_hex(h, hex);
}

static void str_info(int dev_query, cl_platform_id p, cl_uint what, char *buf, size_t n)
{
    buf[0] = 0;
    if (dev_query)
        clGetDeviceInfo(dev, what, n, buf, NULL);
    else
        clGetPlatformInfo(p, what, n, buf, NULL);
    buf[n - 1] = 0;
    for (size_t k = strlen(buf); k > 0 && buf[k - 1] == ' '; k--)
        buf[k - 1] = 0;
}

/* The platform and device, the program text, its build and the kernel. */
static void setup(void)
{
    cl_platform_id ps[16];
    cl_device_id ds[16];
    cl_uint np = 0, nd = 0, cus = 0;
    cl_int e;
    cl_ulong pm = 0, lm = 0;
    size_t srclen, loglen = 0, mult = 0, k;
    char pname[256], pver[256], dname[256], dver[256], drv[256], hex[65], *log;
    const char *s;
    uint8_t *src;
    double t0, tb;
    CK(clGetPlatformIDs(16, ps, &np));
    if (plat_index < 0 || (cl_uint)plat_index >= np) {
        fprintf(stderr, "refused: --platform %d, and there are %u platforms\n", plat_index, np);
        exit(2);
    }
    CK(clGetDeviceIDs(ps[plat_index], CL_DEVICE_TYPE_ALL, 16, ds, &nd));
    if (dev_index < 0 || (cl_uint)dev_index >= nd) {
        fprintf(stderr, "refused: --device %d, and platform %d has %u devices\n", dev_index,
                plat_index, nd);
        exit(2);
    }
    dev = ds[dev_index];
    str_info(0, ps[plat_index], CL_PLATFORM_NAME, pname, sizeof pname);
    str_info(0, ps[plat_index], CL_PLATFORM_VERSION, pver, sizeof pver);
    str_info(1, NULL, CL_DEVICE_NAME, dname, sizeof dname);
    str_info(1, NULL, CL_DEVICE_VERSION, dver, sizeof dver);
    str_info(1, NULL, CL_DRIVER_VERSION, drv, sizeof drv);
    CK(clGetDeviceInfo(dev, CL_DEVICE_MAX_COMPUTE_UNITS, sizeof cus, &cus, NULL));
    snprintf(device_name, sizeof device_name, "%.200s (%.120s, %.120s, driver %.120s)", dname,
             pname, dver, drv);
    printf("device: platform %d of %u, %s, %s; device %d of %u, %s; %u compute units\n",
           plat_index, np, pname, pver, dev_index, nd, device_name, cus);
    src = read_file(cl_path, &srclen);
    sha_hex(src, srclen, hex);
    printf("program: %s, %zu bytes, sha256 %s; build options \"%s\"\n", cl_path, srclen, hex,
           opts);
    ctx = clCreateContext(NULL, 1, &dev, NULL, NULL, &e);
    CK(e);
    q = clCreateCommandQueue(ctx, dev, CL_QUEUE_PROFILING_ENABLE, &e);
    CK(e);
    s = (const char *)src;
    prog = clCreateProgramWithSource(ctx, 1, &s, &srclen, &e);
    CK(e);
    t0 = now_ms();
    e = clBuildProgram(prog, 1, &dev, opts, NULL, NULL);
    tb = now_ms() - t0;
    clGetProgramBuildInfo(prog, dev, CL_PROGRAM_BUILD_LOG, 0, NULL, &loglen);
    log = calloc(loglen + 1, 1);
    clGetProgramBuildInfo(prog, dev, CL_PROGRAM_BUILD_LOG, loglen, log, NULL);
    for (k = strlen(log); k > 0 && (log[k - 1] == '\n' || log[k - 1] == ' ' || log[k - 1] == '\r'); k--)
        log[k - 1] = 0;
    printf("build: %s, clBuildProgram %.1f ms (this process's first build; a runtime may cache); "
           "log %s\n", e == CL_SUCCESS ? "built" : "FAILED", tb, log[0] ? "below" : "empty");
    if (log[0])
        printf("---- build log ----\n%s\n---- end of build log ----\n", log);
    if (e != CL_SUCCESS) {
        fprintf(stderr, "clBuildProgram: OpenCL error %d\n", (int)e);
        exit(3);
    }
    kern = clCreateKernel(prog, "cft_fma_ocl", &e);
    CK(e);
    CK(clGetKernelWorkGroupInfo(kern, dev, CL_KERNEL_WORK_GROUP_SIZE, sizeof wg, &wg, NULL));
    clGetKernelWorkGroupInfo(kern, dev, CL_KERNEL_PREFERRED_WORK_GROUP_SIZE_MULTIPLE,
                             sizeof mult, &mult, NULL);
    clGetKernelWorkGroupInfo(kern, dev, CL_KERNEL_PRIVATE_MEM_SIZE, sizeof pm, &pm, NULL);
    clGetKernelWorkGroupInfo(kern, dev, CL_KERNEL_LOCAL_MEM_SIZE, sizeof lm, &lm, NULL);
    printf("kernel: work-group size %zu (CL_KERNEL_WORK_GROUP_SIZE), preferred multiple %zu; "
           "private memory %llu bytes a work-item, local %llu (as the runtime reports them)\n",
           wg, mult, (unsigned long long)pm, (unsigned long long)lm);
    if (wg_req > 0) {
        if ((size_t)wg_req > wg) {
            fprintf(stderr, "refused: --wg %lld is over the kernel's %zu\n", wg_req, wg);
            exit(2);
        }
        wg = (size_t)wg_req;
        printf("kernel: work-group size %zu by --wg\n", wg);
    }
    free(log);
    free(src);
}

typedef struct {
    uint8_t *raw;
    int fmt, esz;
    long long n;
    const uint8_t *a, *b, *c, *rnd, *d, *fl;
} corpus;

static double run_lanes(const corpus *cp, long long n, uint8_t *out, double *kernel_ms,
                        double *host_ms);

/* One fp256 lane of zeros, once, right after the build: a runtime that
 * compiles at the first launch (or per work-group size) does it here, so
 * that cost is printed on its own and stays out of the timed runs. */
static void first_launch(void)
{
    static uint8_t zero[3 * 32 + 1], out[33];
    corpus z = {NULL, 3, 32, 1, zero, zero + 32, zero + 64, zero + 96, NULL, NULL};
    double kms, hms, e2e = run_lanes(&z, 1, out, &kms, &hms);
    printf("launch: the first launch, one fp256 lane: %.1f ms end to end, kernel %.3f ms "
           "(any compile a runtime makes at the first launch is in it)\n", e2e, kms);
}

static void load_corpus(const char *path, corpus *cp)
{
    size_t size;
    uint32_t h32[2];
    cp->raw = read_file(path, &size);
    if (size < 24 || memcmp(cp->raw, "CFTGPUA1", 8)) {
        fprintf(stderr, "%s: not a GPU-A corpus\n", path);
        exit(2);
    }
    memcpy(h32, cp->raw + 8, 8);
    memcpy(&cp->n, cp->raw + 16, 8);
    cp->fmt = (int)h32[0];
    cp->esz = (int)h32[1];
    if (cp->fmt < 0 || cp->fmt > 3 || cp->esz != FMT[cp->fmt].esz || cp->n < 1 ||
        (uint64_t)size != 24 + (uint64_t)cp->n * (4 * (uint64_t)cp->esz + 2)) {
        fprintf(stderr, "%s: header does not match its size\n", path);
        exit(2);
    }
    cp->a = cp->raw + 24;
    cp->b = cp->a + cp->n * cp->esz;
    cp->c = cp->b + cp->n * cp->esz;
    cp->rnd = cp->c + cp->n * cp->esz;
    cp->d = cp->rnd + cp->n;
    cp->fl = cp->d + cp->n * cp->esz;
}

/* n lanes of the corpus's inputs (lane i reads case i mod n) into out
 * (d || flags). kernel_ms gets the event's time and host_ms the host
 * clock's, from the enqueue to clFinish with the inputs already written;
 * the return value is the end-to-end time: the writes, the kernel and the
 * reads. */
static double run_lanes(const corpus *cp, long long n, uint8_t *out, double *kernel_ms,
                        double *host_ms)
{
    const int esz = cp->esz;
    const size_t vb = (size_t)n * esz;
    const uint8_t *a = cp->a, *b = cp->b, *c = cp->c, *r = cp->rnd;
    uint8_t *in = NULL;
    cl_mem da, db, dc, dr, dd, dfl;
    cl_event ev;
    cl_ulong t_start = 0, t_end = 0;
    cl_int e, fmt = cp->fmt, ce = esz;
    cl_long cn = n;
    size_t g = ((size_t)n + wg - 1) / wg * wg, l = wg;
    double t0, tk, e2e;
    if (n != cp->n) {                       /* replicate the inputs to n lanes */
        long long i;
        in = malloc((size_t)n * (3 * esz + 1));
        for (i = 0; i < n; i++) {
            long long sidx = i % cp->n;
            memcpy(in + (size_t)i * esz, cp->a + sidx * esz, esz);
            memcpy(in + (size_t)(n + i) * esz, cp->b + sidx * esz, esz);
            memcpy(in + (size_t)(2 * n + i) * esz, cp->c + sidx * esz, esz);
            in[(size_t)3 * n * esz + i] = cp->rnd[sidx];
        }
        a = in; b = a + vb; c = b + vb; r = c + vb;
    }
    da = clCreateBuffer(ctx, CL_MEM_READ_ONLY, vb, NULL, &e); CK(e);
    db = clCreateBuffer(ctx, CL_MEM_READ_ONLY, vb, NULL, &e); CK(e);
    dc = clCreateBuffer(ctx, CL_MEM_READ_ONLY, vb, NULL, &e); CK(e);
    dr = clCreateBuffer(ctx, CL_MEM_READ_ONLY, (size_t)n, NULL, &e); CK(e);
    dd = clCreateBuffer(ctx, CL_MEM_WRITE_ONLY, vb, NULL, &e); CK(e);
    dfl = clCreateBuffer(ctx, CL_MEM_WRITE_ONLY, (size_t)n, NULL, &e); CK(e);
    CK(clSetKernelArg(kern, 0, sizeof fmt, &fmt));
    CK(clSetKernelArg(kern, 1, sizeof ce, &ce));
    CK(clSetKernelArg(kern, 2, sizeof cn, &cn));
    CK(clSetKernelArg(kern, 3, sizeof da, &da));
    CK(clSetKernelArg(kern, 4, sizeof db, &db));
    CK(clSetKernelArg(kern, 5, sizeof dc, &dc));
    CK(clSetKernelArg(kern, 6, sizeof dr, &dr));
    CK(clSetKernelArg(kern, 7, sizeof dd, &dd));
    CK(clSetKernelArg(kern, 8, sizeof dfl, &dfl));
    CK(clFinish(q));
    t0 = now_ms();
    CK(clEnqueueWriteBuffer(q, da, CL_FALSE, 0, vb, a, 0, NULL, NULL));
    CK(clEnqueueWriteBuffer(q, db, CL_FALSE, 0, vb, b, 0, NULL, NULL));
    CK(clEnqueueWriteBuffer(q, dc, CL_FALSE, 0, vb, c, 0, NULL, NULL));
    CK(clEnqueueWriteBuffer(q, dr, CL_FALSE, 0, (size_t)n, r, 0, NULL, NULL));
    CK(clFinish(q));
    tk = now_ms();
    CK(clEnqueueNDRangeKernel(q, kern, 1, NULL, &g, &l, 0, NULL, &ev));
    CK(clFinish(q));
    *host_ms = now_ms() - tk;
    CK(clEnqueueReadBuffer(q, dd, CL_FALSE, 0, vb, out, 0, NULL, NULL));
    CK(clEnqueueReadBuffer(q, dfl, CL_TRUE, 0, (size_t)n, out + vb, 0, NULL, NULL));
    e2e = now_ms() - t0;
    CK(clWaitForEvents(1, &ev));
    CK(clGetEventProfilingInfo(ev, CL_PROFILING_COMMAND_START, sizeof t_start, &t_start, NULL));
    CK(clGetEventProfilingInfo(ev, CL_PROFILING_COMMAND_END, sizeof t_end, &t_end, NULL));
    *kernel_ms = (double)(t_end - t_start) * 1e-6;
    CK(clReleaseEvent(ev));
    CK(clReleaseMemObject(da)); CK(clReleaseMemObject(db)); CK(clReleaseMemObject(dc));
    CK(clReleaseMemObject(dr)); CK(clReleaseMemObject(dd)); CK(clReleaseMemObject(dfl));
    free(in);
    return e2e;
}

static void hexle(const uint8_t *p, int esz, char *out)    /* big-endian text */
{
    int i;
    for (i = 0; i < esz; i++)
        sprintf(out + 2 * i, "%02x", p[esz - 1 - i]);
}

static int do_check(const char *cpath, const char *opath)
{
    corpus cp;
    long long i, dbad = 0, fbad = 0, refused = 0, per[5] = {0}, perbad[5] = {0}, shown = 0;
    double kms, hms, e2e;
    char hex[65];
    uint8_t *out;
    load_corpus(cpath, &cp);
    setup();
    first_launch();
    out = malloc((size_t)cp.n * (cp.esz + 1));
    e2e = run_lanes(&cp, cp.n, out, &kms, &hms);
    printf("timing: kernel %.3f ms by the profiling events, %.3f ms by the host clock (enqueue "
           "to clFinish, inputs written); end to end %.3f ms\n", kms, hms, e2e);
    for (i = 0; i < cp.n; i++) {
        const uint8_t *gd = out + i * cp.esz;
        uint8_t gf = out[cp.n * cp.esz + i];
        int rd = cp.rnd[i] < 5 ? cp.rnd[i] : 0;
        int bad_d = memcmp(gd, cp.d + i * cp.esz, cp.esz) != 0, bad_f = gf != cp.fl[i];
        per[rd]++;
        dbad += bad_d; fbad += bad_f; refused += (gf & 0x80) != 0;
        perbad[rd] += bad_d || bad_f;
        if ((bad_d || bad_f) && shown++ < 5) {
            char ha[65], hb[65], hc[65], hg[65], hw[65];
            hexle(cp.a + i * cp.esz, cp.esz, ha); hexle(cp.b + i * cp.esz, cp.esz, hb);
            hexle(cp.c + i * cp.esz, cp.esz, hc); hexle(gd, cp.esz, hg);
            hexle(cp.d + i * cp.esz, cp.esz, hw);
            printf("  DIFF case %lld rnd %d: a %s b %s c %s\n       got d %s flags 0x%02x\n"
                   "      want d %s flags 0x%02x\n", i, cp.rnd[i], ha, hb, hc, hg, gf, hw,
                   cp.fl[i]);
        }
    }
    sha_hex(out, (size_t)cp.n * (cp.esz + 1), hex);
    if (opath) {
        FILE *fp = fopen(opath, "wb");
        if (!fp || fwrite(out, 1, (size_t)cp.n * (cp.esz + 1), fp) != (size_t)cp.n * (cp.esz + 1)) {
            fprintf(stderr, "cannot write %s\n", opath);
            exit(2);
        }
        fclose(fp);
    }
    printf("check: %s on %s: %s, %lld cases (rne %lld rtz %lld rdn %lld rup %lld rmm %lld);"
           " %lld results and %lld flags differ, %lld refused; differing by attribute "
           "%lld/%lld/%lld/%lld/%lld; sha256 %s; kernel %.3f ms, end to end %.3f ms: %s\n",
           cpath, device_name, FMT[cp.fmt].name, cp.n, per[0], per[1], per[2], per[3], per[4],
           dbad, fbad, refused, perbad[0], perbad[1], perbad[2], perbad[3], perbad[4], hex,
           kms, e2e, dbad || fbad ? "RED" : "GREEN");
    return dbad || fbad ? 1 : 0;
}

static int cmp_d(const void *x, const void *y)
{
    double a = *(const double *)x, b = *(const double *)y;
    return a < b ? -1 : a > b;
}

static int do_bench(const char *cpath)
{
    corpus cp;
    long long n;
    int k;
    double kms, hms, km_med, ee_med, hk_med;
    double *km = malloc(reps * sizeof *km), *ee = malloc(reps * sizeof *ee),
           *hk = malloc(reps * sizeof *hk);
    uint8_t *out;
    load_corpus(cpath, &cp);
    n = lanes ? lanes : cp.n;
    setup();
    first_launch();
    out = malloc((size_t)n * (cp.esz + 1));
    run_lanes(&cp, n, out, &kms, &hms);               /* warm-up, not counted */
    for (k = 0; k < reps; k++) {
        ee[k] = run_lanes(&cp, n, out, &kms, &hms);
        km[k] = kms;
        hk[k] = hms;
    }
    qsort(km, reps, sizeof *km, cmp_d);
    qsort(ee, reps, sizeof *ee, cmp_d);
    qsort(hk, reps, sizeof *hk, cmp_d);
    km_med = km[reps / 2];
    ee_med = ee[reps / 2];
    hk_med = hk[reps / 2];
    printf("bench: %s on %s: %s, %lld lanes, work-group %zu, %d reps; kernel ms min %.3f median "
           "%.3f max %.3f; end to end ms min %.3f median %.3f max %.3f; %.4g FMA/s kernel, "
           "%.4g FMA/s end to end (medians); %.1f ns a lane; kernel by the host clock ms min "
           "%.3f median %.3f max %.3f, %.4g FMA/s\n", cpath, device_name,
           FMT[cp.fmt].name, n, wg, reps, km[0], km_med, km[reps - 1], ee[0], ee_med,
           ee[reps - 1], n / (km_med * 1e-3), n / (ee_med * 1e-3), km_med * 1e6 / n,
           hk[0], hk_med, hk[reps - 1], n / (hk_med * 1e-3));
    return 0;
}

static int do_info(void)
{
    cl_ulong gm = 0, ma = 0, lm = 0;
    size_t mwg = 0;
    char ocl_c[256], ext[8192];
    setup();
    first_launch();
    clGetDeviceInfo(dev, CL_DEVICE_GLOBAL_MEM_SIZE, sizeof gm, &gm, NULL);
    clGetDeviceInfo(dev, CL_DEVICE_MAX_MEM_ALLOC_SIZE, sizeof ma, &ma, NULL);
    clGetDeviceInfo(dev, CL_DEVICE_LOCAL_MEM_SIZE, sizeof lm, &lm, NULL);
    clGetDeviceInfo(dev, CL_DEVICE_MAX_WORK_GROUP_SIZE, sizeof mwg, &mwg, NULL);
    str_info(1, NULL, CL_DEVICE_OPENCL_C_VERSION, ocl_c, sizeof ocl_c);
    str_info(1, NULL, CL_DEVICE_EXTENSIONS, ext, sizeof ext);
    printf("info: %s; %s; global memory %llu, largest allocation %llu, local memory %llu "
           "bytes; device work-group limit %zu\n", device_name, ocl_c, (unsigned long long)gm,
           (unsigned long long)ma, (unsigned long long)lm, mwg);
    printf("info: extensions: %s\n", ext);
    return 0;
}

int main(int argc, char **argv)
{
    int i, npos = 0;
    const char *pos[2] = {NULL, NULL};
    setvbuf(stdout, NULL, _IOLBF, 0);       /* lines in order with stderr's in a log */
    if (argc < 2) {
        fprintf(stderr, "usage: %s check CORPUS OUT|- | bench CORPUS | info [--platform N] "
                "[--device N] [--reps R] [--lanes N] [--wg N] [--cl FILE] [--opts S]\n", argv[0]);
        return 2;
    }
    /* An option this build does not know is refused, never ignored (GPU-A's rule). */
    for (i = 2; i < argc; i++) {
        if (!strcmp(argv[i], "--platform") && i + 1 < argc) plat_index = atoi(argv[++i]);
        else if (!strcmp(argv[i], "--device") && i + 1 < argc) dev_index = atoi(argv[++i]);
        else if (!strcmp(argv[i], "--reps") && i + 1 < argc) reps = atoi(argv[++i]);
        else if (!strcmp(argv[i], "--lanes") && i + 1 < argc) lanes = atoll(argv[++i]);
        else if (!strcmp(argv[i], "--wg") && i + 1 < argc) wg_req = atoll(argv[++i]);
        else if (!strcmp(argv[i], "--cl") && i + 1 < argc) cl_path = argv[++i];
        else if (!strcmp(argv[i], "--opts") && i + 1 < argc &&
                 strlen(opts) + 1 + strlen(argv[i + 1]) < sizeof opts) {
            strcat(opts, " ");
            strcat(opts, argv[++i]);
        } else if (!strncmp(argv[i], "--", 2) || npos == 2) {
            fprintf(stderr, "refused: argument '%s' is not one this build knows\n", argv[i]);
            return 2;
        } else
            pos[npos++] = argv[i];
    }
    if (reps < 1 || lanes < 0 || wg_req < 0) {
        fprintf(stderr, "refused: --reps is at least 1, --lanes and --wg not negative\n");
        return 2;
    }
    if (!strcmp(argv[1], "check") && npos == 2)
        return do_check(pos[0], strcmp(pos[1], "-") ? pos[1] : NULL);
    if (!strcmp(argv[1], "bench") && npos == 1)
        return do_bench(pos[0]);
    if (!strcmp(argv[1], "info") && npos == 0)
        return do_info();
    fprintf(stderr, "refused: unknown command or wrong number of arguments\n");
    return 2;
}
