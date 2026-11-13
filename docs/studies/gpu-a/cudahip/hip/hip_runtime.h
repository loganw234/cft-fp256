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
 *
 * Extended 2026-11-12 (the GPU backend's round 1, parcel G1C) with the
 * names libcft's GPU backend, host/src/backend_hip.cpp, uses beside them
 * (its streams, asynchronous copies, pinned host memory, error names and
 * versions), so host/Makefile's HIP_PLATFORM=cuda builds it with plain
 * nvcc too; and with clockRate, which CUDA 13's cudaDeviceProp no longer
 * has (cft_fma.hip reads it: the study GPU-B, section 3b).
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

/* The backend's (2026-11-12): HIP's argument order is CUDA's in each */
typedef cudaStream_t hipStream_t;
#define hipStreamCreateWithFlags  cudaStreamCreateWithFlags
#define hipStreamNonBlocking      cudaStreamNonBlocking
#define hipStreamSynchronize      cudaStreamSynchronize
#define hipStreamDestroy          cudaStreamDestroy
#define hipMemcpyAsync            cudaMemcpyAsync
#define hipMemsetAsync            cudaMemsetAsync
#define hipMemGetInfo             cudaMemGetInfo
#define hipHostMalloc             cudaHostAlloc
#define hipHostMallocDefault      cudaHostAllocDefault
#define hipHostFree               cudaFreeHost
#define hipGetErrorName           cudaGetErrorName
#define hipRuntimeGetVersion      cudaRuntimeGetVersion
#define hipDriverGetVersion       cudaDriverGetVersion
#define hipErrorOutOfMemory       cudaErrorMemoryAllocation
#define hipErrorLaunchOutOfResources cudaErrorLaunchOutOfResources

/* HIP's device properties carry gcnArchName and CUDA's do not: empty here,
 * so the harness names the device sm_XY, as on HIP's NVIDIA path. From
 * CUDA 13.0 cudaDeviceProp has no clockRate (kHz), so the field is this
 * struct's own there, read as the device attribute; before 13.0 it is
 * CUDA's member. The guard is CUDART_VERSION, the runtime's own number for
 * the release that removed it; 12.9 and 13.3 were built, 13.0 to 13.2 not. */
struct hipDeviceProp_t : cudaDeviceProp {
    char gcnArchName[256];
#if CUDART_VERSION >= 13000
    int clockRate;
#endif
};
static inline hipError_t hipGetDeviceProperties(hipDeviceProp_t *p, int dev)
{
    hipError_t e;
    memset(p->gcnArchName, 0, sizeof p->gcnArchName);
    e = cudaGetDeviceProperties(p, dev);
#if CUDART_VERSION >= 13000
    p->clockRate = 0;
    if (e == cudaSuccess)
        e = cudaDeviceGetAttribute(&p->clockRate, cudaDevAttrClockRate, dev);
#endif
    return e;
}
#endif
