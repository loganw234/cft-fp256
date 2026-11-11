/* Copyright 2026 Logan W.
 * SPDX-License-Identifier: Apache-2.0
 *
 * GPU-D, DIAGNOSIS ONLY, never the route: a reduced case for Apple's default
 * build. cft_sf_round_pack alone, the call the refusing path makes, in a probe
 * kernel added to the OpenCL C text as a second source string, on N fp256 lanes
 * shaped like sf_fma's far path (a 239-bit significand, a sticky bit on two
 * lanes of three, every attribute), against libcft's own softfloat.c and
 * bigint.c on this CPU. Platform 0, device 0. macOS:
 *   cc -O2 -std=c99 -I ROOT/host/src rp_probe.c ROOT/host/src/softfloat.c \
 *      ROOT/host/src/bigint.c -framework OpenCL -o rp_probe
 *   rp_probe TEXT.cl [--plant-host-rup-as-rtz] [build options...]
 * The plant computes the host's rup lanes as rtz: it must DIFFER. */
#define CL_SILENCE_DEPRECATION
#include <OpenCL/opencl.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "softfloat.h"

#define N 4096
static const char *KSRC =
    "__kernel void probe_rp(__global const uint *in, __global uint *out, int n) {\n"
    "  int i = get_global_id(0), k, rc; cft_fmt_desc f = cft_sf_formats[3];\n"
    "  cft_bn m, o; uint32_t fl = 0; __global const uint *p = in + i * 16; __global uint *q;\n"
    "  if (i >= n) return;\n"
    "  cft_bn_zero(&m); cft_bn_zero(&o); m.n = (int)p[8]; for (k = 0; k < 8; k++) m.v[k] = p[k];\n"
    "  rc = cft_sf_round_pack(&f, (int)p[12], &m, (int)p[9], (int)p[10], (int)p[11], &o, &fl);\n"
    "  q = out + i * 12; q[0] = (uint)rc; q[1] = fl; q[2] = (uint)o.n;\n"
    "  for (k = 0; k < 9; k++) q[3 + k] = k < o.n ? o.v[k] : 0u;\n"
    "}\n";
static uint64_t s = 0x243F6A8885A308D3ull;
static uint32_t rnd32(void) { s = s * 6364136223846793005ull + 1442695040888963407ull; return (uint32_t)(s >> 32); }

int main(int argc, char **argv)
{
    static uint32_t in[N * 16], got[N * 12], want[N * 12];
    char opts[512] = "-cl-std=CL1.2";
    const char *srcs[2] = {NULL, KSRC};
    size_t lens[2], g = N;
    int i, k, a = 2, plant = 0, bad = 0, byr[5] = {0};
    cl_int e, nl = N;
    cl_platform_id pf; cl_device_id dev;
    FILE *fp = argc > 1 ? fopen(argv[1], "rb") : NULL;
    if (!fp) { fprintf(stderr, "usage: rp_probe TEXT.cl [--plant-host-rup-as-rtz] [options]\n"); return 2; }
    if (argc > 2 && !strcmp(argv[2], "--plant-host-rup-as-rtz")) { plant = 1; a = 3; }
    for (; a < argc; a++) { strcat(opts, " "); strcat(opts, argv[a]); }
    fseek(fp, 0, SEEK_END); lens[0] = (size_t)ftell(fp); fseek(fp, 0, SEEK_SET);
    srcs[0] = malloc(lens[0]); fread((char *)srcs[0], 1, lens[0], fp); fclose(fp); lens[1] = strlen(KSRC);
    for (i = 0; i < N; i++) {                      /* the inputs, and libcft's answer on this CPU */
        uint32_t *p = in + i * 16, fl = 0, *w = want + i * 12;
        cft_bn m, o;
        int en = (i % 4 == 3) ? 262142 + (int)(rnd32() % 2) : (int)(rnd32() % 4001) - 2000;
        for (k = 0; k < 7; k++) p[k] = rnd32();
        p[7] = (rnd32() & 0x3FFFu) | 0x4000u;      /* 239 bits: p + 2 */
        p[8] = 8; p[9] = (uint32_t)(en - 238); p[10] = (i % 3) != 0; p[11] = i % 5; p[12] = (i / 5) & 1;
        cft_bn_zero(&m); cft_bn_zero(&o); m.n = 8;
        for (k = 0; k < 8; k++) m.v[k] = p[k];
        w[0] = (uint32_t)cft_sf_round_pack(&cft_sf_formats[3], (int)p[12], &m, (int)p[9], (int)p[10],
                                           plant && p[11] == CFT_SF_RUP ? CFT_SF_RTZ : (int)p[11], &o, &fl);
        w[1] = fl; w[2] = (uint32_t)o.n;
        for (k = 0; k < 9; k++) w[3 + k] = k < o.n ? o.v[k] : 0u;
    }
    clGetPlatformIDs(1, &pf, NULL); clGetDeviceIDs(pf, CL_DEVICE_TYPE_ALL, 1, &dev, NULL);
    cl_context ctx = clCreateContext(NULL, 1, &dev, NULL, NULL, &e);
    cl_command_queue q = clCreateCommandQueue(ctx, dev, 0, &e);
    cl_program pr = clCreateProgramWithSource(ctx, 2, srcs, lens, &e);
    if (clBuildProgram(pr, 1, &dev, opts, NULL, NULL)) { printf("rp_probe: \"%s\": build FAILED\n", opts); return 2; }
    cl_kernel kr = clCreateKernel(pr, "probe_rp", &e);
    cl_mem bi = clCreateBuffer(ctx, CL_MEM_READ_ONLY | CL_MEM_COPY_HOST_PTR, sizeof in, in, &e);
    cl_mem bo = clCreateBuffer(ctx, CL_MEM_WRITE_ONLY, sizeof got, NULL, &e);
    clSetKernelArg(kr, 0, sizeof bi, &bi); clSetKernelArg(kr, 1, sizeof bo, &bo); clSetKernelArg(kr, 2, sizeof nl, &nl);
    e = clEnqueueNDRangeKernel(q, kr, 1, NULL, &g, NULL, 0, NULL, NULL);
    e |= clEnqueueReadBuffer(q, bo, CL_TRUE, 0, sizeof got, got, 0, NULL, NULL);
    if (e) { printf("rp_probe: launch or read: OpenCL error %d\n", e); return 2; }
    for (i = 0; i < N; i++)
        if (memcmp(got + i * 12, want + i * 12, 48)) { bad++; byr[i % 5]++; }
    printf("rp_probe: build options \"%s\"%s: %d lanes of cft_sf_round_pack alone, %d differ from "
           "libcft on this CPU (by rnd %d/%d/%d/%d/%d): %s\n", opts, plant ? ", host plant rup-as-rtz" : "",
           N, bad, byr[0], byr[1], byr[2], byr[3], byr[4], bad ? "DIFFERS" : "AGREES");
    return bad != 0;
}
