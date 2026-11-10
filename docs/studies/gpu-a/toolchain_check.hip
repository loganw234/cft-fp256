/* Copyright 2026 Logan W.
 * SPDX-License-Identifier: Apache-2.0
 *
 * GPU-A's toolchain check: the smallest HIP program that proves one source
 * builds and runs on a device. Every device the runtime sees runs one
 * integer kernel and is named with its architecture and PCI bus. Run it
 * first on a new machine (run_rx7600.sh, run_mi300x.sh, run_wsl_nvidia.sh).
 *
 *   hipcc -O2 --offload-arch=<arch> toolchain_check.hip -o toolchain_check
 */
#include <hip/hip_runtime.h>
#include <stdio.h>
#include <stdlib.h>

#define CK(x) do { hipError_t e_ = (x); if (e_ != hipSuccess) { \
    fprintf(stderr, "%s:%d: %s: %s\n", __FILE__, __LINE__, #x, \
            hipGetErrorString(e_)); exit(2); } } while (0)

__global__ void tc_kernel(unsigned *out, int n)
{
    int i = blockIdx.x * blockDim.x + threadIdx.x;
    if (i < n)
        out[i] = (unsigned)i * 2654435761u + 12345u;   /* integer only */
}

int main(void)
{
    int ndev = 0, d, bad_all = 0;
    const int n = 1 << 20;
    unsigned *h = (unsigned *)malloc(n * sizeof(unsigned));
    CK(hipGetDeviceCount(&ndev));
    printf("toolchain_check: HIP_VERSION %d, %d device(s)\n", HIP_VERSION, ndev);
    for (d = 0; d < ndev; d++) {
        hipDeviceProp_t p;
        char bus[32] = {0};
        unsigned *dv = NULL;
        int i, bad = 0;
        CK(hipSetDevice(d));
        CK(hipGetDeviceProperties(&p, d));
        CK(hipDeviceGetPCIBusId(bus, (int)sizeof bus, d));
        CK(hipMalloc((void **)&dv, n * sizeof(unsigned)));
        tc_kernel<<<(n + 255) / 256, 256>>>(dv, n);
        CK(hipGetLastError());
        CK(hipMemcpy(h, dv, n * sizeof(unsigned), hipMemcpyDeviceToHost));
        CK(hipFree(dv));
        for (i = 0; i < n; i++)
            bad += h[i] != (unsigned)i * 2654435761u + 12345u;
        printf("device %d: %s, cc %d.%d, arch '%s', bus %s, %d CUs/SMs, "
               "warp %d: %d of %d lanes wrong\n", d, p.name, p.major, p.minor,
               p.gcnArchName, bus, p.multiProcessorCount, p.warpSize, bad, n);
        bad_all += bad;
    }
    free(h);
    printf("toolchain_check: %s\n", bad_all || !ndev ? "FAIL" : "PASS");
    return bad_all || !ndev;
}
