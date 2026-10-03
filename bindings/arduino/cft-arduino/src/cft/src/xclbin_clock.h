/* Copyright 2026 Logan W.
 * SPDX-License-Identifier: Apache-2.0
 *
 * xclbin_clock.h - the kernel clock an xclbin's own record of its link
 * states, for cft_get_image_id's clock_hz at ABI 0.18 (cft.h; certificate
 * format version 2's `device-clock` line, docs/CERTIFICATES.md).
 *
 * WHY HERE AND NOT FROM XRT. XRT does not report the clock this design's
 * compute units run at. On the U50's shell the kernel clock is a clocking
 * wizard configured statically inside the bitstream (the ULP's
 * clk_out1_ulp_clk_wiz_0), and the image's CLOCK_FREQ_TOPOLOGY section -
 * which is what XRT programs and reports - lists the SHELL's scalable
 * clocks (hbm_aclk 450, KERNEL_CLK 500, DATA_CLK 300 MHz on every image
 * measured), never the constraint the link was given. That constraint
 * lives only in the bitstream and in the v++ command line the image's
 * BUILD_METADATA section records: `--clock.freqHz <Hz>:<cu>.ap_clk,...`.
 * hw/verify-image.sh reads the kernel clock from there too (its check
 * 5b), and says why it does not read it from the topology (check 6).
 *
 * THE RULE. The clock is named only when it is the clock of every compute
 * unit the handle opened: the image has exactly one BUILD_METADATA
 * section, its text names `--clock.freqHz` exactly once, the value is a
 * decimal of 1 to 19 digits without a leading zero, and the list after
 * the colon names `<instance>.ap_clk` for every instance opened. Anything
 * else - an hw_emu image, linked without the constraint; an image whose
 * constraint leaves a unit at the platform default; two constraints; a
 * section that is not there or runs past the file - is 0, "not known",
 * with the reason in `why`. Never a guess.
 *
 * THE LAYOUT, as XRT's xclbin.h fixes it with static asserts (struct axlf
 * is 496 bytes, axlf_header 152, axlf_section_header 40): the magic
 * "xclbin2" and a NUL at 0; the header at 304, whose m_numSections is at
 * its byte 144 (file byte 448); the section headers from 456, each 40
 * bytes - m_sectionKind (u32) at 0, m_sectionName at 4, m_sectionOffset
 * (u64) at 24 and m_sectionSize (u64) at 32, little-endian. BUILD_METADATA
 * is kind 14. Measured in the cft2204 distro, read only, which holds
 * fifteen images (four hw, eleven hw_emu): on 2026-10-02 the constraints
 * of eleven were counted - the hw images of /root/cft-fp256/build-r8-hw
 * and build-r8-quad name one each, 10000000:cft_krnl_1.ap_clk and the same
 * over cft_krnl_1 to _4, and nine hw_emu images none - and this reader
 * read those two hw images and build/cft_hw_emu.xclbin (not known). On
 * 2026-10-03 verifier-VCV2CW read the two 135 MHz hw images of
 * /root/cft-quad-tip/ (build-single-tip-135, build-quad-tip-135) with it:
 * 135000000 each. The two hw_emu images of /root/cft-red/ were not read.
 *
 * Header-only and static inline, in C99 and C++, so that the XRT backend
 * (C++) and host/tests/api_test.c (C, which holds this file to synthetic
 * images on every host, with or without XRT) include the one copy. */
#ifndef CFT_XCLBIN_CLOCK_H
#define CFT_XCLBIN_CLOCK_H

#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

#define CFT_AXLF_MAGIC_BYTES    8u
#define CFT_AXLF_NUM_SECTIONS   448u     /* 304 + 144 */
#define CFT_AXLF_SECTIONS       456u     /* 304 + 152 */
#define CFT_AXLF_SECTION_BYTES  40u
#define CFT_AXLF_BUILD_METADATA 14u

static inline uint64_t cft_axlf_le(const unsigned char *p, int n)
{
    uint64_t v = 0;
    int i;
    for (i = n - 1; i >= 0; i--)
        v = (v << 8) | p[i];
    return v;
}

/* Does `list` (the constraint's text after its colon, `len` bytes, its
 * items separated by commas) name `<inst>.ap_clk`? */
static inline int cft_axlf_names(const char *list, size_t len,
                                 const char *inst)
{
    size_t at = 0, n = strlen(inst);
    while (at < len) {
        size_t end = at;
        while (end < len && list[end] != ',')
            end++;
        if (end - at == n + 7 && memcmp(list + at, inst, n) == 0 &&
            memcmp(list + at + n, ".ap_clk", 7) == 0)
            return 1;
        at = end + 1;
    }
    return 0;
}

/* The kernel clock of `img` (n bytes, an xclbin) in Hz, for the compute
 * units whose instance names are `inst[0 .. n_inst-1]` (cft_krnl_1 and so
 * on): 1 and *hz set, or 0 and *hz 0 with the reason in `why`. */
static inline int cft_xclbin_kernel_clock(const unsigned char *img, size_t n,
                                          const char *const *inst,
                                          size_t n_inst, uint64_t *hz,
                                          char *why, size_t cap)
{
    static const char opt[] = "--clock.freqHz";
    const size_t olen = sizeof opt - 1;
    uint64_t nsec, k, off = 0, size = 0, v = 0;
    const char *text, *p, *list;
    size_t tlen, i, digits = 0, found = 0, llen;
    int meta = 0;

    *hz = 0;
    if (n_inst == 0) {
        snprintf(why, cap, "no compute unit was opened");
        return 0;
    }
    if (n < CFT_AXLF_SECTIONS ||
        memcmp(img, "xclbin2\0", CFT_AXLF_MAGIC_BYTES) != 0) {
        snprintf(why, cap, "the image is not an axlf (xclbin2) file");
        return 0;
    }
    nsec = cft_axlf_le(img + CFT_AXLF_NUM_SECTIONS, 4);
    if (nsec > (n - CFT_AXLF_SECTIONS) / CFT_AXLF_SECTION_BYTES) {
        snprintf(why, cap, "its section table runs past the file");
        return 0;
    }
    for (k = 0; k < nsec; k++) {
        const unsigned char *s = img + CFT_AXLF_SECTIONS +
                                 (size_t)k * CFT_AXLF_SECTION_BYTES;
        if (cft_axlf_le(s, 4) != CFT_AXLF_BUILD_METADATA)
            continue;
        meta++;
        off = cft_axlf_le(s + 24, 8);
        size = cft_axlf_le(s + 32, 8);
    }
    if (meta != 1) {
        snprintf(why, cap, "it has %d BUILD_METADATA sections, and the "
                 "clock is read from exactly one", meta);
        return 0;
    }
    if (off > n || size > n - off) {
        snprintf(why, cap, "its BUILD_METADATA section runs past the file");
        return 0;
    }
    text = (const char *)img + off;
    tlen = (size_t)size;
    p = NULL;
    for (i = 0; i + olen <= tlen; i++)
        if (memcmp(text + i, opt, olen) == 0) {
            if (!found)
                p = text + i + olen;
            found++;
        }
    if (found != 1) {
        snprintf(why, cap, "its link's recorded v++ line names "
                 "--clock.freqHz %lu times, and a kernel clock is read from "
                 "exactly one (an image linked without it, as hw_emu "
                 "images are, runs at the platform's default, which it "
                 "does not record)", (unsigned long)found);
        return 0;
    }
    while (p < text + tlen && *p == ' ')
        p++;
    while (p + digits < text + tlen && p[digits] >= '0' && p[digits] <= '9')
        digits++;
    if (digits == 0 || digits > 19 || (p[0] == '0') ||
        p + digits >= text + tlen || p[digits] != ':') {
        snprintf(why, cap, "its --clock.freqHz value is not a decimal "
                 "number of hertz followed by a colon and its units");
        return 0;
    }
    for (i = 0; i < digits; i++)
        v = v * 10u + (uint64_t)(p[i] - '0');
    if (v > (uint64_t)INT64_MAX) {
        snprintf(why, cap, "its --clock.freqHz value is past 2^63 - 1");
        return 0;
    }
    list = p + digits + 1;
    llen = 0;
    while (list + llen < text + tlen && list[llen] != ' ' &&
           list[llen] != '"' && list[llen] != '\\' && list[llen] != '\n')
        llen++;
    for (i = 0; i < n_inst; i++)
        if (!cft_axlf_names(list, llen, inst[i])) {
            snprintf(why, cap, "its --clock.freqHz constraint does not name "
                     "%.64s.ap_clk, which was opened and so runs at the "
                     "platform's default", inst[i]);
            return 0;
        }
    *hz = v;
    return 1;
}

#endif /* CFT_XCLBIN_CLOCK_H */
