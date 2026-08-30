/* Copyright 2026 Logan W.
 * SPDX-License-Identifier: Apache-2.0
 *
 * cft-selftest - report what a libcft device is, and replay the
 * published conformance vectors through it.
 *
 *     cft-selftest [vector-directory] [artifact.xclbin]
 *
 * With no artifact it exercises the software backend. With one it
 * opens that device and replays every case through the hardware,
 * which is the run docs/CARDDAY.md keeps: 228,000 published cases,
 * the claim this project exists to make, checked on silicon.
 *
 * Exit status is 0 only if every case in every set matched. This is
 * the thing to run after building the library, after porting it, and
 * on the machine you are about to trust a result from - the claim is
 * that the bits are the same everywhere, and this is how you find out
 * whether they are on yours.
 */

#include <inttypes.h>
#include <stdio.h>
#include <string.h>

#include "cft.h"

int main(int argc, char **argv)
{
    const char *dir = (argc > 1) ? argv[1] : "vectors/out";
    const char *artifact = (argc > 2) ? argv[2] : NULL;
    cft_device *dev = NULL;
    cft_caps caps;
    char report[8192];
    uint64_t cases = 0;
    uint32_t abi;
    cft_status st;
    int i;

    abi = cft_abi_version();
    printf("libcft ABI %u.%u\n", (unsigned)(abi >> 16),
           (unsigned)(abi & 0xffffu));

    st = cft_open(artifact, 0, &dev);
    if (st != CFT_OK) {
        fprintf(stderr, "cft_open(%s): %s\n",
                artifact ? artifact : "software", cft_strerror(st));
        if (*cft_last_error())
            fprintf(stderr, "  %s\n", cft_last_error());
        return 2;
    }

    memset(&caps, 0, sizeof caps);
    caps.struct_size = sizeof caps;
    st = cft_get_caps(dev, &caps);
    if (st != CFT_OK) {
        fprintf(stderr, "cft_get_caps: %s\n", cft_strerror(st));
        cft_close(dev);
        return 2;
    }

    printf("backend        %s\n", caps.backend);
    printf("tiles          %u\n", (unsigned)caps.tiles);
    printf("flags readable %s\n", caps.flags_readable ? "yes" :
           "NO - flags cannot be trusted on this backend");
    printf("formats        ");
    for (i = 0; i < 4; i++)
        if (caps.format_mask & (1u << i))
            printf("%s ", cft_format_name((cft_format)i));
    printf("\n");
    if (caps.device_version)
        printf("device version 0x%08x\n", (unsigned)caps.device_version);

    printf("\nreplaying %s\n", dir);
    st = cft_conformance(dev, dir, report, sizeof report, &cases);
    fputs(report, stdout);
    printf("%" PRIu64 " cases checked\n", cases);
    if (st != CFT_OK)
        printf("CONFORMANCE FAILED: %s\n", cft_strerror(st));

    cft_close(dev);
    return st == CFT_OK ? 0 : 1;
}
