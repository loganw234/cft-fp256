/* Copyright 2026 Logan W.
 * SPDX-License-Identifier: Apache-2.0
 *
 * GPU-D's kernel: one work-item is one lane, as GPU-A's gpua_fma_kernel.
 * oclcopy.py appends this file, unedited, after libcft's arithmetic and
 * GPU-A's gpua_fma_lane (taken from cft_fma.hip byte for byte), so the
 * lane runs what device.c's software loop runs for one element.
 *
 * libcft's functions take private pointers (OpenCL C's default address
 * space), so the lane's operands are copied from global memory into
 * private bytes and back, and the format descriptor out of the __constant
 * table into a private copy: GPU-A passed it by value for the same reason.
 * Nothing here computes: the copies move bytes. The plants are GPU-A's
 * macros, given to clBuildProgram as -D options. */
__kernel void cft_fma_ocl(int fmt, int esz, long n,
                          __global const uchar *a, __global const uchar *b,
                          __global const uchar *c, __global const uchar *rnd,
                          __global uchar *d, __global uchar *flags)
{
    const long i = (long)get_global_id(0);
    cft_fmt_desc f;
    uint8_t pa[32], pb[32], pc[32], pd[32], fl = 0;
    int k;
    if (i >= n || fmt < 0 || fmt > 3 || esz != cft_sf_formats[fmt].width / 8)
        return;
    f = cft_sf_formats[fmt];
    for (k = 0; k < esz; k++) {
        pa[k] = a[i * esz + k];
        pb[k] = b[i * esz + k];
        pc[k] = c[i * esz + k];
    }
    gpua_fma_lane(&f, esz, pa, pb, pc, rnd[i], pd, &fl);
    for (k = 0; k < esz; k++)
        d[i * esz + k] = pd[k];
    flags[i] = fl;
}
