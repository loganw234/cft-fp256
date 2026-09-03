/* Copyright 2026 Logan W.
 * SPDX-License-Identifier: Apache-2.0
 *
 * The C example, written against cft.hpp instead of cft.h.
 *
 *     g++ -std=c++17 -Ihost/include host/examples/vector_fma.cpp \
 *         host/libcft.a -o vector-fma-cpp
 *     ./vector-fma-cpp
 *
 * Its stdout must be byte-for-byte what host/examples/vector_fma.c
 * prints, and what the Python, Rust, Julia, Go, C# and R examples
 * print - `make -C host examples-lang` runs the diff. The checksum is
 * FNV-1a over the raw output encodings, so nothing in the line under
 * test passes through a decimal conversion, a locale or an idea of
 * how to spell infinity.
 *
 * What this file is really demonstrating is that the C++ layer is a
 * layer and not a reimplementation: the operand stream is built the
 * same way (a four-line xorshift, short enough to reimplement in any
 * language without error), the arithmetic is ONE cft_run per format
 * issued through cft::basic_context, and the bits that come back are
 * the same bits. The wrapper's contribution is that the buffers are
 * std::vector<cft::encoding<F>> - sized by the format rather than by
 * a multiplication the caller has to get right - and that nothing
 * here frees anything.
 *
 * Nothing needs a card. Pass an xclbin path as argv[1] and the same
 * program runs on the tile instead, with the same output.
 */

#include <cstdint>
#include <cstdio>
#include <new>
#include <vector>

#include "cft.hpp"

namespace {

const int N = 4096;

/* ---- the operand stream ------------------------------------------ *
 *
 * xorshift32, stepped once per byte, so that every language's example
 * can generate byte-identical inputs without sharing a file. It is not
 * a good random number generator and does not need to be.
 */
std::uint32_t rng_state;

void rng_seed(std::uint32_t s)
{
    rng_state = s ? s : 1u;
}

std::uint8_t rng_byte()
{
    rng_state ^= rng_state << 13;
    rng_state ^= rng_state >> 17;
    rng_state ^= rng_state << 5;
    return static_cast<std::uint8_t>(rng_state & 0xffu);
}

/* One element: a normal with a fraction from the stream and an
 * exponent within 32 of 1.0, so that products stay in range and the
 * run exercises rounding rather than overflow.
 *
 * The geometry is cft::format_traits<F>'s, not a table repeated here -
 * which is the one thing this port gets that the C original could not,
 * since a struct of four ints per format is what C had to write. */
template <cft_format F>
void make_element(cft::encoding<F> &e)
{
    using t = cft::format_traits<F>;
    const int nb = static_cast<int>(t::size);
    const int kb = t::significand_bits / 8;
    const int rb = t::significand_bits % 8;
    int j;

    for (j = 0; j < nb; j++)
        e[static_cast<std::size_t>(j)] = rng_byte();
    const std::uint32_t ef = static_cast<std::uint32_t>(
        t::bias - 32 + static_cast<std::int64_t>(rng_byte() & 63u));

    e[static_cast<std::size_t>(kb)] &=
        static_cast<std::uint8_t>((1u << rb) - 1u);
    for (j = kb + 1; j < nb; j++)
        e[static_cast<std::size_t>(j)] = 0;
    for (j = 0; j < t::exponent_bits; j++)
        if ((ef >> j) & 1u)
            e[static_cast<std::size_t>((t::significand_bits + j) / 8)] |=
                static_cast<std::uint8_t>(1u << ((t::significand_bits + j) % 8));
    if (rng_byte() & 1u)
        e[static_cast<std::size_t>(nb - 1)] |= 0x80u;
}

/* FNV-1a, 64-bit. The constants are written in hex because that is how
 * they are specified; transcribing them as decimal is how you get a
 * checksum that is stable, plausible, and not FNV. */
std::uint64_t fnv1a(const std::uint8_t *p, std::size_t n)
{
    std::uint64_t h = 0xcbf29ce484222325ull;
    for (std::size_t i = 0; i < n; i++) {
        h ^= p[i];
        h *= 0x100000001b3ull;
    }
    return h;
}

/* One format's line. Returns false only for a fatal error, which is
 * printed in the C example's words: the missing-artifact and refused-
 * call paths are part of what the languages are diffed on. */
template <cft_format F>
bool one_format(cft::device &dev, int index)
{
    using enc = cft::encoding<F>;

    if (!dev.supports(CFT_FMA, F)) {
        std::printf("%-6s not available on this device\n",
                    cft_format_name(F));
        return true;
    }

    cft::basic_context<F> ctx(dev, CFT_RNE);
    std::vector<enc> a(N), b(N), c(N), d(N);

    /* Seeded per format, so each line is independent of the ones
     * before it and can be reproduced on its own. */
    rng_seed(0x1234567u + static_cast<std::uint32_t>(index));
    for (int i = 0; i < N; i++) {
        make_element<F>(a[static_cast<std::size_t>(i)]);
        make_element<F>(b[static_cast<std::size_t>(i)]);
        make_element<F>(c[static_cast<std::size_t>(i)]);
    }

    std::uint32_t flags = 0;
    try {
        /* ONE call for the whole vector - the shape cft_run is and the
         * shape the tile wants. */
        flags = ctx.fma(a, b, c, d);
    } catch (const cft::error &e) {
        std::fprintf(stderr, "cft_run %s: %s\n", cft_format_name(F),
                     cft_strerror(e.status()));
        return false;
    }

    std::printf("%-6s n=%d rne  checksum 0x%016llx  flags 0x%02x\n",
                cft_format_name(F), N,
                static_cast<unsigned long long>(
                    fnv1a(reinterpret_cast<const std::uint8_t *>(d.data()),
                          static_cast<std::size_t>(N) *
                              cft::format_traits<F>::size)),
                static_cast<unsigned>(flags));
    return true;
}

}  // namespace

int main(int argc, char **argv)
{
    const char *artifact = (argc > 1) ? argv[1] : nullptr;
    cft::device dev;

    const cft_status st = dev.try_open(artifact, 0);
    if (st != CFT_OK) {
        std::fprintf(stderr, "cft_open(%s): %s\n",
                     artifact ? artifact : "software", cft_strerror(st));
        return 1;
    }
    std::printf("cft-fp256 vector fma, %s backend\n",
                artifact ? artifact : "software");

    /* The C original loops over the format enum; here the format is a
     * template argument, so the loop is four instantiations in the
     * same order. Allocation failure is std::bad_alloc rather than a
     * NULL from malloc, and is reported in the same words - the error
     * surface is part of what the ports are diffed on. */
    try {
        if (!one_format<CFT_FP32>(dev, 0))  return 1;
        if (!one_format<CFT_FP64>(dev, 1))  return 1;
        if (!one_format<CFT_FP128>(dev, 2)) return 1;
        if (!one_format<CFT_FP256>(dev, 3)) return 1;
    } catch (const std::bad_alloc &) {
        std::fprintf(stderr, "out of memory\n");
        return 1;
    }

    return 0;
}
