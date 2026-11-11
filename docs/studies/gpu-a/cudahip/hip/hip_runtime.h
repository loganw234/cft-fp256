/* Copyright 2026 Logan W.
 * SPDX-License-Identifier: Apache-2.0
 *
 * GPU-A's study header, NOT HIP: the HIP runtime names cft_fma.hip and
 * toolchain_check.hip use, mapped onto CUDA's, so the unchanged source
 * builds with plain nvcc and no HIP (build.sh's `cuda` target puts this
 * directory on the include path). The fallback if HIP 7.2.4, the last
 * release packaging HIP's NVIDIA platform, stops building (the study,
 * section 3). The kernels need nothing here: __global__, __host__
 * __device__, threadIdx, __launch_bounds__ and atomicAdd are CUDA's own.
 */
#ifndef GPUA_CUDAHIP_H
#define GPUA_CUDAHIP_H
#include <cuda_runtime.h>
#include <string.h>

#define HIP_VERSION 0                 /* 0: this header, not a HIP release */
typedef cudaError_t hipError_t;
typedef cudaEvent_t hipEvent_t;
typedef cudaFuncAttributes hipFuncAttributes;
#define hipSuccess                cudaSuccess
#define hipGetErrorString         cudaGetErrorString
#define hipGetLastError           cudaGetLastError
#define hipGetDeviceCount         cudaGetDeviceCount
#define hipSetDevice              cudaSetDevice
#define hipDeviceSynchronize      cudaDeviceSynchronize
#define hipDeviceGetPCIBusId      cudaDeviceGetPCIBusId
#define hipDeviceGetLimit         cudaDeviceGetLimit
#define hipLimitStackSize         cudaLimitStackSize
#define hipMalloc                 cudaMalloc
#define hipFree                   cudaFree
#define hipMemcpy                 cudaMemcpy
#define hipMemset                 cudaMemset
#define hipMemcpyHostToDevice     cudaMemcpyHostToDevice
#define hipMemcpyDeviceToHost     cudaMemcpyDeviceToHost
#define hipEventCreate            cudaEventCreate
#define hipEventRecord            cudaEventRecord
#define hipEventElapsedTime       cudaEventElapsedTime
#define hipEventDestroy           cudaEventDestroy
#define hipFuncGetAttributes      cudaFuncGetAttributes
#define hipOccupancyMaxActiveBlocksPerMultiprocessor \
        cudaOccupancyMaxActiveBlocksPerMultiprocessor

/* HIP's device properties carry gcnArchName and CUDA's do not: empty here,
 * so the harness names the device sm_XY, as on HIP's NVIDIA path. */
struct hipDeviceProp_t : cudaDeviceProp { char gcnArchName[256]; };
static inline hipError_t hipGetDeviceProperties(hipDeviceProp_t *p, int dev)
{
    memset(p->gcnArchName, 0, sizeof p->gcnArchName);
    return cudaGetDeviceProperties(p, dev);
}
#endif
