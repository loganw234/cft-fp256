/* Copyright 2026 Logan W.
 * SPDX-License-Identifier: Apache-2.0
 *
 * cft.hpp against cft.h: the same inputs down both paths, compared for
 * bit-identical encodings and identical flags.
 *
 * This is the only test the C++ layer needs and the only one it can
 * honestly have. The wrapper computes nothing, so there is no
 * arithmetic here to check against IEEE 754 - api_test.c already does
 * that, against a reading of the standard rather than against either
 * implementation, and cft-selftest replays the published vectors. What
 * CAN go wrong in a wrapper is everything around the arithmetic:
 * operands in the wrong slot (cft.h's ADD reads a and c, MUL reads a
 * and b), a length in elements where the library wants elements, a
 * rounding attribute that did not travel, a flag word dropped on the
 * floor, a NULL where an empty span was meant. So every entry point is
 * issued twice - once through cft.hpp, once through cft.h with the
 * same bytes - and the two must agree exactly.
 *
 * Two independently opened devices, not one, so that a wrapper bug
 * that corrupted device state would show up as a disagreement rather
 * than being shared by both sides.
 *
 * Built at BOTH -std=c++17 and -std=c++20 by `make -C host cpptest`:
 * the span type is std::span under one and this header's own view
 * under the other, and the point of a feature check is that the answer
 * does not depend on which.
 *
 *     ./cpp-api-test [vectors-dir]     default ../vectors/out
 */

#include <cstdio>
#include <cstdint>
#include <cstring>
#include <string>
#include <vector>

#include "cft.hpp"

namespace {

int checks;
int failures;

#define CHECK(cond, ...)                                                 \
    do {                                                                 \
        checks++;                                                        \
        if (!(cond)) {                                                   \
            std::printf("FAIL %s:%d: ", __FILE__, __LINE__);             \
            std::printf(__VA_ARGS__);                                    \
            std::printf("\n");                                           \
            failures++;                                                  \
        }                                                                \
    } while (0)

/* ---- the operand stream ------------------------------------------ *
 * The example's xorshift, for the same reason: reproducible without a
 * data file. Exponents stay within 32 of 1.0 so that products stay in
 * range and cft_rem's exponent-gap walk stays short. */
std::uint32_t rng_state = 1;

std::uint8_t rng_byte()
{
    rng_state ^= rng_state << 13;
    rng_state ^= rng_state >> 17;
    rng_state ^= rng_state << 5;
    return static_cast<std::uint8_t>(rng_state & 0xffu);
}

template <cft_format F>
cft::encoding<F> random_normal()
{
    using t = cft::format_traits<F>;
    cft::encoding<F> e{};
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
    return e;
}

/* The specials, in a fixed order, so that a pair of arrays offset from
 * each other produces (nan, inf), (inf, 0), (0, 0) and the rest of the
 * interesting corners without anyone enumerating them. */
template <cft_format F>
std::vector<cft::encoding<F>> specials()
{
    std::vector<cft::encoding<F>> v;
    v.push_back(cft::quiet_nan_enc<F>());
    v.push_back(cft::signaling_nan_enc<F>());
    v.push_back(cft::inf_enc<F>(0));
    v.push_back(cft::inf_enc<F>(1));
    v.push_back(cft::zero_enc<F>(0));
    v.push_back(cft::zero_enc<F>(1));
    v.push_back(cft::min_subnormal_enc<F>());
    v.push_back(cft::one_enc<F>());
    cft::encoding<F> neg_one = cft::one_enc<F>();
    neg_one[cft::format_traits<F>::size - 1] |= 0x80u;
    v.push_back(neg_one);
    return v;
}

/* n elements: the specials rotated by `shift`, then random normals. */
template <cft_format F>
std::vector<cft::encoding<F>> operands(std::size_t n, std::size_t shift)
{
    const std::vector<cft::encoding<F>> sp = specials<F>();
    std::vector<cft::encoding<F>> v;
    v.reserve(n);
    for (std::size_t i = 0; i < n; i++) {
        if (i < sp.size())
            v.push_back(sp[(i + shift) % sp.size()]);
        else
            v.push_back(random_normal<F>());
    }
    return v;
}

template <cft_format F>
bool same_bytes(const std::vector<cft::encoding<F>> &x,
                const std::vector<cft::encoding<F>> &y, std::size_t *where)
{
    if (x.size() != y.size())
        return false;
    for (std::size_t i = 0; i < x.size(); i++)
        if (x[i] != y[i]) {
            *where = i;
            return false;
        }
    return true;
}

/* The comparison every case funnels through: same encodings, same
 * flags, and the first disagreement named in the format's own hex. */
template <cft_format F>
void expect(const char *what, cft_round rnd,
            const std::vector<cft::encoding<F>> &got, std::uint32_t got_flags,
            const std::vector<cft::encoding<F>> &want, std::uint32_t want_flags)
{
    std::size_t at = 0;
    checks++;
    if (!same_bytes<F>(got, want, &at)) {
        std::printf("FAIL %s %s %s: element %u wrapper %s, C %s\n",
                    cft_format_name(F), cft::round_name(rnd), what,
                    static_cast<unsigned>(at), cft::to_hex<F>(got[at]).c_str(),
                    cft::to_hex<F>(want[at]).c_str());
        failures++;
        return;
    }
    if (got_flags != want_flags) {
        std::printf("FAIL %s %s %s: flags wrapper 0x%02x (%s), C 0x%02x (%s)\n",
                    cft_format_name(F), cft::round_name(rnd), what,
                    static_cast<unsigned>(got_flags),
                    cft::flag_names(got_flags).c_str(),
                    static_cast<unsigned>(want_flags),
                    cft::flag_names(want_flags).c_str());
        failures++;
    }
}

/* Run a wrapper call and report the status it would have thrown. */
template <class Fn>
cft_status status_of(Fn &&fn)
{
    try {
        fn();
        return CFT_OK;
    } catch (const cft::error &e) {
        return e.status();
    }
}

/* Was a wrapper-side misuse refused as such? */
template <class Fn>
bool refused_as_misuse(Fn &&fn)
{
    try {
        fn();
    } catch (const std::invalid_argument &) {
        return true;
    } catch (...) {
        return false;
    }
    return false;
}

bool predicate_set(const void *p, std::size_t bytes)
{
    const std::uint8_t *b = static_cast<const std::uint8_t *>(p);
    for (std::size_t i = 0; i < bytes; i++)
        if (b[i])
            return true;
    return false;
}

/* =================================================================
 * One format, both paths
 * ================================================================= */
template <cft_format F>
void check_format(cft::device &dev, cft_device *ref)
{
    using enc = cft::encoding<F>;
    using t = cft::format_traits<F>;
    const std::size_t esz = t::size;
    const std::size_t n = 257;          /* crosses the library's chunking */

    static const cft_round rounds[5] = { CFT_RNE, CFT_RTZ, CFT_RDN,
                                         CFT_RUP, CFT_RMM };

    /* -- the traits, checked against the library rather than trusted -
     * cvt_from_i32(1) pins bias, significand width and exponent width
     * of one_enc() in one comparison; format_size pins the byte width;
     * cft_class pins the specials. */
    CHECK(cft_format_size(F) == esz, "%s: cft_format_size says %u, traits say %u",
          cft_format_name(F), static_cast<unsigned>(cft_format_size(F)),
          static_cast<unsigned>(esz));
    {
        const std::int32_t one_i = 1;
        enc from_lib{};
        std::uint32_t fl = 0;
        const cft_status st = cft_cvt_from_i32(ref, F, CFT_RNE, &one_i,
                                               from_lib.data(), 1, &fl);
        CHECK(st == CFT_OK && from_lib == cft::one_enc<F>(),
              "%s: one_enc() is %s, the library's 1 is %s",
              cft_format_name(F), cft::to_hex<F>(cft::one_enc<F>()).c_str(),
              cft::to_hex<F>(from_lib).c_str());

        std::uint8_t cls[6];
        const std::vector<enc> sp = { cft::quiet_nan_enc<F>(),
                                      cft::signaling_nan_enc<F>(),
                                      cft::inf_enc<F>(0), cft::inf_enc<F>(1),
                                      cft::zero_enc<F>(1),
                                      cft::min_subnormal_enc<F>() };
        const cft_status cst = cft_class(ref, F, sp.data(), cls, sp.size());
        CHECK(cst == CFT_OK && cls[0] == CFT_CLASS_QNAN &&
                  cls[1] == CFT_CLASS_SNAN && cls[2] == CFT_CLASS_POS_INF &&
                  cls[3] == CFT_CLASS_NEG_INF && cls[4] == CFT_CLASS_NEG_ZERO &&
                  cls[5] == CFT_CLASS_POS_SUB,
              "%s: the header's specials do not classify as themselves",
              cft_format_name(F));
    }

    /* -- hex round trip ------------------------------------------- */
    {
        const std::vector<enc> sp = specials<F>();
        bool ok = true;
        for (std::size_t i = 0; i < sp.size(); i++)
            if (cft::from_hex<F>(cft::to_hex<F>(sp[i])) != sp[i])
                ok = false;
        CHECK(ok, "%s: to_hex/from_hex round trip", cft_format_name(F));
        CHECK(refused_as_misuse([] { cft::from_hex<F>("00"); }),
              "%s: from_hex must refuse a string of the wrong width",
              cft_format_name(F));
    }

    const std::vector<enc> a = operands<F>(n, 0);
    const std::vector<enc> b = operands<F>(n, 3);
    const std::vector<enc> c = operands<F>(n, 6);
    std::vector<enc> dw(n), dc(n);

    /* -- the elementwise opcode space, every attribute -------------- */
    static const cft_op ops[] = {
        CFT_FMA, CFT_ADD, CFT_SUB, CFT_MUL, CFT_ABS, CFT_NEG, CFT_COPYSIGN,
        CFT_MIN, CFT_MAX, CFT_MINNUM, CFT_MAXNUM, CFT_SELECT, CFT_CMPLT,
        CFT_CMPLE, CFT_CMPEQ, CFT_IAND, CFT_IOR, CFT_IXOR, CFT_IADD,
        CFT_ISUB, CFT_ISHL, CFT_ISHR, CFT_ICMPLT, CFT_RECIP_SEED,
        CFT_RSQRT_SEED
    };

    for (std::size_t ri = 0; ri < 5; ri++) {
        const cft_round rnd = rounds[ri];
        cft::basic_context<F> ctx(dev, rnd);

        for (std::size_t oi = 0; oi < sizeof ops / sizeof ops[0]; oi++) {
            const cft_op op = ops[oi];
            std::uint32_t fw = 0, fc = 0;
            fw = ctx.map(op, a, b, c, dw);
            const cft_status st = cft_run(ref, op, F, rnd, a.data(), b.data(),
                                          c.data(), dc.data(), n, &fc, nullptr);
            CHECK(st == CFT_OK, "%s: cft_run: %s", cft_op_name(op),
                  cft_strerror(st));
            expect<F>(cft_op_name(op), rnd, dw, fw, dc, fc);
        }

        /* The named helpers, which is where an operand slot can be
         * wrong without the arithmetic looking wrong. */
        {
            std::uint32_t fw = ctx.add(a, c, dw), fc = 0;
            cft_run(ref, CFT_ADD, F, rnd, a.data(), nullptr, c.data(),
                    dc.data(), n, &fc, nullptr);
            expect<F>("add(x,y) slots", rnd, dw, fw, dc, fc);

            fw = ctx.sub(a, c, dw);
            cft_run(ref, CFT_SUB, F, rnd, a.data(), nullptr, c.data(),
                    dc.data(), n, &fc, nullptr);
            expect<F>("sub(x,y) slots", rnd, dw, fw, dc, fc);

            fw = ctx.mul(a, b, dw);
            cft_run(ref, CFT_MUL, F, rnd, a.data(), b.data(), nullptr,
                    dc.data(), n, &fc, nullptr);
            expect<F>("mul(x,y) slots", rnd, dw, fw, dc, fc);

            fw = ctx.fma(a, b, c, dw);
            cft_run(ref, CFT_FMA, F, rnd, a.data(), b.data(), c.data(),
                    dc.data(), n, &fc, nullptr);
            expect<F>("fma slots", rnd, dw, fw, dc, fc);

            fw = ctx.copysign(a, b, dw);
            cft_run(ref, CFT_COPYSIGN, F, rnd, a.data(), b.data(), nullptr,
                    dc.data(), n, &fc, nullptr);
            expect<F>("copysign slots", rnd, dw, fw, dc, fc);

            fw = ctx.select(a, b, c, dw);
            cft_run(ref, CFT_SELECT, F, rnd, a.data(), b.data(), c.data(),
                    dc.data(), n, &fc, nullptr);
            expect<F>("select slots", rnd, dw, fw, dc, fc);

            fw = ctx.ishl(a, b, dw);
            cft_run(ref, CFT_ISHL, F, rnd, a.data(), b.data(), nullptr,
                    dc.data(), n, &fc, nullptr);
            expect<F>("ishl slots", rnd, dw, fw, dc, fc);

            fw = ctx.recip_seed(a, dw);
            cft_run(ref, CFT_RECIP_SEED, F, rnd, a.data(), nullptr, nullptr,
                    dc.data(), n, &fc, nullptr);
            expect<F>("recip_seed", rnd, dw, fw, dc, fc);

            fw = ctx.rsqrt_seed(a, dw);
            cft_run(ref, CFT_RSQRT_SEED, F, rnd, a.data(), nullptr, nullptr,
                    dc.data(), n, &fc, nullptr);
            expect<F>("rsqrt_seed", rnd, dw, fw, dc, fc);
        }

        /* Division and square root: the composed sequence, both ways. */
        {
            std::uint32_t fw = ctx.div(a, b, dw), fc = 0;
            cft_status st = cft_div(ref, F, rnd, a.data(), b.data(),
                                    dc.data(), n, &fc, nullptr);
            CHECK(st == CFT_OK, "cft_div: %s", cft_strerror(st));
            expect<F>("div", rnd, dw, fw, dc, fc);

            fw = ctx.sqrt(a, dw);
            st = cft_sqrt(ref, F, rnd, a.data(), dc.data(), n, &fc, nullptr);
            CHECK(st == CFT_OK, "cft_sqrt: %s", cft_strerror(st));
            expect<F>("sqrt", rnd, dw, fw, dc, fc);
        }

        /* Reductions, at three lengths: a power of two, a length whose
         * tree shape is only right if the left child is the largest
         * power of two below it, and the whole array. */
        {
            static const std::size_t lens[] = { 1, 5, 64, 257 };
            for (std::size_t li = 0; li < sizeof lens / sizeof lens[0]; li++) {
                const std::size_t m = lens[li];
                cft::cspan<enc> av(a.data(), m);
                cft::cspan<enc> bv(b.data(), m);

                const cft::value<F> sw = ctx.sum(av);
                enc sc{};
                std::uint32_t fc = 0;
                cft_status st = cft_reduce(ref, CFT_SUM, F, rnd, a.data(),
                                           nullptr, sc.data(), m, &fc, nullptr);
                CHECK(st == CFT_OK, "cft_reduce sum: %s", cft_strerror(st));
                CHECK(sw.bytes() == sc && ctx.last_flags() == fc,
                      "%s %s sum n=%u: wrapper %s/0x%02x, C %s/0x%02x",
                      cft_format_name(F), cft::round_name(rnd),
                      static_cast<unsigned>(m), sw.hex().c_str(),
                      static_cast<unsigned>(ctx.last_flags()),
                      cft::to_hex<F>(sc).c_str(), static_cast<unsigned>(fc));

                const cft::value<F> dwv = ctx.dot(av, bv);
                enc dcv{};
                st = cft_reduce(ref, CFT_DOT, F, rnd, a.data(), b.data(),
                                dcv.data(), m, &fc, nullptr);
                CHECK(st == CFT_OK, "cft_reduce dot: %s", cft_strerror(st));
                CHECK(dwv.bytes() == dcv && ctx.last_flags() == fc,
                      "%s %s dot n=%u: wrapper %s/0x%02x, C %s/0x%02x",
                      cft_format_name(F), cft::round_name(rnd),
                      static_cast<unsigned>(m), dwv.hex().c_str(),
                      static_cast<unsigned>(ctx.last_flags()),
                      cft::to_hex<F>(dcv).c_str(), static_cast<unsigned>(fc));
            }

            /* n == 0 is +0 and raises nothing - documented, and the
             * wrapper reaches it with a NULL operand pointer exactly as
             * a C caller would. */
            const cft::value<F> z = ctx.sum(cft::cspan<enc>());
            enc zc{};
            std::uint32_t fz = 0xdead;
            const cft_status st = cft_reduce(ref, CFT_SUM, F, rnd, nullptr,
                                             nullptr, zc.data(), 0, &fz, nullptr);
            CHECK(st == CFT_OK && z.bytes() == zc && zc == cft::zero_enc<F>(0) &&
                      fz == 0,
                  "%s: an empty sum is +0 and raises nothing (%s)",
                  cft_format_name(F), z.hex().c_str());
        }

        /* -- the rest of clause 9.4 (the 0.6 step) ---------------- *
         *
         * The same three lengths, plus the two claims that are about
         * this WRAPPER rather than about the library: that sumsq and
         * sumabs reach the right opcodes, and that a scaled product's
         * SCALE survives the round trip - a pair whose second member
         * the wrapper dropped would still pass a pr-only comparison.
         */
        {
            static const std::size_t lens[] = { 0, 1, 5, 64, 257 };
            for (std::size_t li = 0; li < sizeof lens / sizeof lens[0]; li++) {
                const std::size_t m = lens[li];
                cft::cspan<enc> av(m ? a.data() : nullptr, m);
                cft::cspan<enc> bv(m ? b.data() : nullptr, m);
                enc c1{};
                std::uint32_t fc = 0;
                cft_status st;

                const cft::value<F> sq = ctx.sumsq(av);
                st = cft_reduce(ref, CFT_SUMSQ, F, rnd, m ? a.data() : nullptr,
                                nullptr, c1.data(), m, &fc, nullptr);
                CHECK(st == CFT_OK && sq.bytes() == c1 &&
                          ctx.last_flags() == fc,
                      "%s %s sumsq n=%u: wrapper %s/0x%02x, C %s/0x%02x",
                      cft_format_name(F), cft::round_name(rnd),
                      static_cast<unsigned>(m), sq.hex().c_str(),
                      static_cast<unsigned>(ctx.last_flags()),
                      cft::to_hex<F>(c1).c_str(), static_cast<unsigned>(fc));

                const cft::value<F> ab = ctx.sumabs(av);
                st = cft_reduce(ref, CFT_SUMABS, F, rnd, m ? a.data() : nullptr,
                                nullptr, c1.data(), m, &fc, nullptr);
                CHECK(st == CFT_OK && ab.bytes() == c1 &&
                          ctx.last_flags() == fc,
                      "%s %s sumabs n=%u: wrapper %s/0x%02x, C %s/0x%02x",
                      cft_format_name(F), cft::round_name(rnd),
                      static_cast<unsigned>(m), ab.hex().c_str(),
                      static_cast<unsigned>(ctx.last_flags()),
                      cft::to_hex<F>(c1).c_str(), static_cast<unsigned>(fc));

                /* The identity, through the wrapper's own two entry
                 * points - and its documented exception, which this
                 * operand array reaches: it carries infinities and
                 * NaNs, so 9.4's infinity-over-NaN row applies at every
                 * length but n <= 1 and the answer is +inf where the
                 * plain dot gives the quiet NaN. Both branches are
                 * asserted, because "they differ" is only evidence if
                 * the difference is the one the standard names. */
                if (m) {
                    std::vector<std::uint8_t> kls(m);
                    bool has_inf = false, has_nan = false;
                    CHECK(cft_class(ref, F, a.data(), kls.data(), m) == CFT_OK,
                          "cft_class over the reduction operands");
                    for (std::size_t k = 0; k < m; k++) {
                        has_inf |= kls[k] == CFT_CLASS_POS_INF ||
                                   kls[k] == CFT_CLASS_NEG_INF;
                        has_nan |= kls[k] == CFT_CLASS_QNAN ||
                                   kls[k] == CFT_CLASS_SNAN;
                    }
                    const cft::value<F> dsq = ctx.dot(av, av);
                    if (has_inf && has_nan) {
                        CHECK(sq.bytes() == cft::inf_enc<F>(0),
                              "%s %s n=%u: an infinity beside a NaN must "
                              "make sumsq +inf, got %s",
                              cft_format_name(F), cft::round_name(rnd),
                              static_cast<unsigned>(m), sq.hex().c_str());
                        CHECK(!(dsq.bytes() == sq.bytes()),
                              "%s %s n=%u: the plain dot agreed there, so "
                              "the override cannot be shown to do anything",
                              cft_format_name(F), cft::round_name(rnd),
                              static_cast<unsigned>(m));
                    } else {
                        CHECK(sq.bytes() == dsq.bytes(),
                              "%s %s n=%u: sumsq %s != dot(a,a) %s through "
                              "the wrapper", cft_format_name(F),
                              cft::round_name(rnd), static_cast<unsigned>(m),
                              sq.hex().c_str(), dsq.hex().c_str());
                    }
                }

                std::int64_t sc64 = 0;
                const auto sp = ctx.scaled_prod(av);
                st = cft_scaled_prod(ref, F, rnd, m ? a.data() : nullptr,
                                     c1.data(), &sc64, m, &fc);
                CHECK(st == CFT_OK && sp.pr.bytes() == c1 &&
                          sp.scale == sc64 && ctx.last_flags() == fc,
                      "%s %s scaled_prod n=%u: wrapper %s/%lld/0x%02x, "
                      "C %s/%lld/0x%02x",
                      cft_format_name(F), cft::round_name(rnd),
                      static_cast<unsigned>(m), sp.pr.hex().c_str(),
                      static_cast<long long>(sp.scale),
                      static_cast<unsigned>(ctx.last_flags()),
                      cft::to_hex<F>(c1).c_str(),
                      static_cast<long long>(sc64),
                      static_cast<unsigned>(fc));

                const auto sps = ctx.scaled_prod_sum(av, bv);
                st = cft_scaled_prod_sum(ref, F, rnd, m ? a.data() : nullptr,
                                         m ? b.data() : nullptr, c1.data(),
                                         &sc64, m, &fc);
                CHECK(st == CFT_OK && sps.pr.bytes() == c1 &&
                          sps.scale == sc64 && ctx.last_flags() == fc,
                      "%s %s scaled_prod_sum n=%u: wrapper %s/%lld, "
                      "C %s/%lld",
                      cft_format_name(F), cft::round_name(rnd),
                      static_cast<unsigned>(m), sps.pr.hex().c_str(),
                      static_cast<long long>(sps.scale),
                      cft::to_hex<F>(c1).c_str(),
                      static_cast<long long>(sc64));

                const auto spd = ctx.scaled_prod_diff(av, bv);
                st = cft_scaled_prod_diff(ref, F, rnd, m ? a.data() : nullptr,
                                          m ? b.data() : nullptr, c1.data(),
                                          &sc64, m, &fc);
                CHECK(st == CFT_OK && spd.pr.bytes() == c1 &&
                          spd.scale == sc64 && ctx.last_flags() == fc,
                      "%s %s scaled_prod_diff n=%u: wrapper %s/%lld, "
                      "C %s/%lld",
                      cft_format_name(F), cft::round_name(rnd),
                      static_cast<unsigned>(m), spd.pr.hex().c_str(),
                      static_cast<long long>(spd.scale),
                      cft::to_hex<F>(c1).c_str(),
                      static_cast<long long>(sc64));
            }

            /* An empty scaled product is 9.4's multiplicative identity,
             * and it is the one answer here that is not a function of
             * any input - worth a literal rather than a comparison. */
            const auto e = ctx.scaled_prod(cft::cspan<enc>());
            CHECK(e.pr.bytes() == cft::one_enc<F>() && e.scale == 0 &&
                      ctx.last_flags() == 0,
                  "%s: an empty scaled product is (1, 0), silently (%s/%lld)",
                  cft_format_name(F), e.pr.hex().c_str(),
                  static_cast<long long>(e.scale));

            /* Length disagreement is the wrapper's own refusal, and it
             * must be an exception rather than a read past the end of
             * the caller's array. */
            CHECK(refused_as_misuse([&] {
                      ctx.scaled_prod_sum(cft::cspan<enc>(a.data(), 4),
                                          cft::cspan<enc>(b.data(), 3));
                  }),
                  "%s: scaled_prod_sum refuses mismatched lengths",
                  cft_format_name(F));
            CHECK(refused_as_misuse([&] {
                      ctx.scaled_prod_diff(cft::cspan<enc>(a.data(), 4),
                                           cft::cspan<enc>(b.data(), 3));
                  }),
                  "%s: scaled_prod_diff refuses mismatched lengths",
                  cft_format_name(F));
        }

        /* -- clause 5 --------------------------------------------- */
        {
            std::uint32_t fw = 0, fc = 0;
            cft_status st;

            for (int exact = 0; exact < 2; exact++) {
                fw = ctx.rint(a, dw, exact != 0);
                st = cft_rint(ref, F, rnd, exact, a.data(), dc.data(), n, &fc,
                              nullptr);
                CHECK(st == CFT_OK, "cft_rint: %s", cft_strerror(st));
                expect<F>(exact ? "rint exact" : "rint", rnd, dw, fw, dc, fc);
            }

            static const std::int64_t exps[] = { 1, -1, 40, -40, 100000 };
            for (std::size_t ei = 0; ei < sizeof exps / sizeof exps[0]; ei++) {
                fw = ctx.scaleb(a, exps[ei], dw);
                st = cft_scaleb(ref, F, rnd, a.data(), exps[ei], dc.data(), n,
                                &fc, nullptr);
                CHECK(st == CFT_OK, "cft_scaleb: %s", cft_strerror(st));
                expect<F>("scaleb", rnd, dw, fw, dc, fc);
            }

            static const cft_op cmps[] = { CFT_CMPLT, CFT_CMPLE, CFT_CMPEQ };
            for (std::size_t ci = 0; ci < 3; ci++) {
                fw = ctx.cmp_sig(cmps[ci], a, b, dw);
                st = cft_cmp_sig(ref, cmps[ci], F, a.data(), b.data(),
                                 dc.data(), n, &fc, nullptr);
                CHECK(st == CFT_OK, "cft_cmp_sig: %s", cft_strerror(st));
                expect<F>("cmp_sig", rnd, dw, fw, dc, fc);
            }

            fw = ctx.logb(a, dw);
            st = cft_logb(ref, F, a.data(), dc.data(), n, &fc);
            CHECK(st == CFT_OK, "cft_logb: %s", cft_strerror(st));
            expect<F>("logb", rnd, dw, fw, dc, fc);

            fw = ctx.next_up(a, dw);
            st = cft_next_up(ref, F, a.data(), dc.data(), n, &fc);
            CHECK(st == CFT_OK, "cft_next_up: %s", cft_strerror(st));
            expect<F>("next_up", rnd, dw, fw, dc, fc);

            fw = ctx.next_down(a, dw);
            st = cft_next_down(ref, F, a.data(), dc.data(), n, &fc);
            CHECK(st == CFT_OK, "cft_next_down: %s", cft_strerror(st));
            expect<F>("next_down", rnd, dw, fw, dc, fc);

            fw = ctx.rem(a, b, dw);
            st = cft_rem(ref, F, a.data(), b.data(), dc.data(), n, &fc);
            CHECK(st == CFT_OK, "cft_rem: %s", cft_strerror(st));
            expect<F>("rem", rnd, dw, fw, dc, fc);

            /* The phase-1 transcendentals (ABI 0.3). Correctly
             * rounded, so the wrapper has to marshal them exactly:
             * one wrong pointer and the bits move. */
            fw = ctx.exp(a, dw);
            st = cft_exp(ref, F, rnd, a.data(), dc.data(), n, &fc);
            CHECK(st == CFT_OK, "cft_exp: %s", cft_strerror(st));
            expect<F>("exp", rnd, dw, fw, dc, fc);

            fw = ctx.expm1(a, dw);
            st = cft_expm1(ref, F, rnd, a.data(), dc.data(), n, &fc);
            CHECK(st == CFT_OK, "cft_expm1: %s", cft_strerror(st));
            expect<F>("expm1", rnd, dw, fw, dc, fc);

            fw = ctx.exp2(a, dw);
            st = cft_exp2(ref, F, rnd, a.data(), dc.data(), n, &fc);
            CHECK(st == CFT_OK, "cft_exp2: %s", cft_strerror(st));
            expect<F>("exp2", rnd, dw, fw, dc, fc);

            fw = ctx.log(a, dw);
            st = cft_log(ref, F, rnd, a.data(), dc.data(), n, &fc);
            CHECK(st == CFT_OK, "cft_log: %s", cft_strerror(st));
            expect<F>("log", rnd, dw, fw, dc, fc);

            fw = ctx.log1p(a, dw);
            st = cft_log1p(ref, F, rnd, a.data(), dc.data(), n, &fc);
            CHECK(st == CFT_OK, "cft_log1p: %s", cft_strerror(st));
            expect<F>("log1p", rnd, dw, fw, dc, fc);

            fw = ctx.log2(a, dw);
            st = cft_log2(ref, F, rnd, a.data(), dc.data(), n, &fc);
            CHECK(st == CFT_OK, "cft_log2: %s", cft_strerror(st));
            expect<F>("log2", rnd, dw, fw, dc, fc);

            fw = ctx.log10(a, dw);
            st = cft_log10(ref, F, rnd, a.data(), dc.data(), n, &fc);
            CHECK(st == CFT_OK, "cft_log10: %s", cft_strerror(st));
            expect<F>("log10", rnd, dw, fw, dc, fc);

            fw = ctx.pow(a, b, dw);
            st = cft_pow(ref, F, rnd, a.data(), b.data(), dc.data(), n, &fc);
            CHECK(st == CFT_OK, "cft_pow: %s", cft_strerror(st));
            expect<F>("pow", rnd, dw, fw, dc, fc);

            fw = ctx.hypot(a, b, dw);
            st = cft_hypot(ref, F, rnd, a.data(), b.data(), dc.data(), n, &fc);
            CHECK(st == CFT_OK, "cft_hypot: %s", cft_strerror(st));
            expect<F>("hypot", rnd, dw, fw, dc, fc);

            /* The phase-2 trigonometrics (ABI 0.4). Same reasoning:
             * the wrapper computes nothing, so what is being checked
             * is that it hands the same bytes to the same call - and
             * for atan2 in particular that it does not swap y and x,
             * which is the one marshalling error that would still
             * look plausible. */
#define TRIG1(name)                                                        \
            fw = ctx.name(a, dw);                                          \
            st = cft_##name(ref, F, rnd, a.data(), dc.data(), n, &fc);     \
            CHECK(st == CFT_OK, "cft_" #name ": %s", cft_strerror(st));    \
            expect<F>(#name, rnd, dw, fw, dc, fc)
            TRIG1(sinpi);
            TRIG1(cospi);
            TRIG1(tanpi);
            TRIG1(asin);
            TRIG1(acos);
            TRIG1(atan);
            TRIG1(asinpi);
            TRIG1(acospi);
            TRIG1(atanpi);
            /* The phase-3 nine (ABI 0.5): the same marshalling check,
             * and for sin, cos and tan the pool's huge operands drive
             * the reduction against pi through both routes. */
            TRIG1(sin);
            TRIG1(cos);
            TRIG1(tan);
            TRIG1(sinh);
            TRIG1(cosh);
            TRIG1(tanh);
            TRIG1(asinh);
            TRIG1(acosh);
            TRIG1(atanh);
            /* Table 9.1's remainder (part of the 0.6 step). The six
             * unary ones marshal like everything above. */
            TRIG1(exp2m1);
            TRIG1(exp10);
            TRIG1(exp10m1);
            TRIG1(log2p1);
            TRIG1(log10p1);
            TRIG1(rsqrt);
#undef TRIG1

            /* pown, compound and rootn carry a second array of a
             * DIFFERENT type, which is the marshalling this file exists
             * to check: a wrapper that passed the element count where
             * the exponent array belongs would compile and would be
             * wrong in every lane. The exponents vary per element for
             * the same reason. */
            {
                std::vector<std::int64_t> nv(n);
                for (std::size_t k = 0; k < n; k++)
                    nv[k] = (std::int64_t)(k % 7) - 3;
#define INT1(name)                                                         \
                fw = ctx.name(a, nv, dw);                                  \
                st = cft_##name(ref, F, rnd, a.data(), nv.data(),          \
                                dc.data(), n, &fc);                        \
                CHECK(st == CFT_OK, "cft_" #name ": %s",                   \
                      cft_strerror(st));                                   \
                expect<F>(#name, rnd, dw, fw, dc, fc)
                INT1(pown);
                INT1(compound);
                INT1(rootn);
#undef INT1
            }

            fw = ctx.powr(a, b, dw);
            st = cft_powr(ref, F, rnd, a.data(), b.data(), dc.data(), n, &fc);
            CHECK(st == CFT_OK, "cft_powr: %s", cft_strerror(st));
            expect<F>("powr", rnd, dw, fw, dc, fc);

            fw = ctx.atan2(a, b, dw);
            st = cft_atan2(ref, F, rnd, a.data(), b.data(), dc.data(), n, &fc);
            CHECK(st == CFT_OK, "cft_atan2: %s", cft_strerror(st));
            expect<F>("atan2", rnd, dw, fw, dc, fc);

            fw = ctx.atan2pi(a, b, dw);
            st = cft_atan2pi(ref, F, rnd, a.data(), b.data(), dc.data(), n,
                             &fc);
            CHECK(st == CFT_OK, "cft_atan2pi: %s", cft_strerror(st));
            expect<F>("atan2pi", rnd, dw, fw, dc, fc);

            /* The augmented arithmetic operations (754-2019 9.5): two
             * outputs each, and no attribute - the context's rounding
             * is deliberately NOT consulted, so the same pair must come
             * back under every `rnd` this loop is running. */
            {
                std::vector<enc> ew(n), ec(n);
#define AUG(name)                                                         \
                fw = ctx.augmented_##name(a, b, dw, ew);                  \
                st = cft_augmented_##name(ref, F, a.data(), b.data(),     \
                                          dc.data(), ec.data(), n, &fc);  \
                CHECK(st == CFT_OK, "cft_augmented_" #name ": %s",        \
                      cft_strerror(st));                                  \
                expect<F>("augmented_" #name " (r)", rnd, dw, fw, dc, fc); \
                expect<F>("augmented_" #name " (e)", rnd, ew, fw, ec, fc)
                AUG(add);
                AUG(sub);
                AUG(mul);
#undef AUG
                /* r and e as one span is refused by the library and the
                 * wrapper turns that into an exception, like every
                 * other refusal on this class. */
                bool threw = false;
                try {
                    ctx.augmented_add(a, b, dw, dw);
                } catch (const cft::error &) {
                    threw = true;
                }
                CHECK(threw, "%s: augmented_add(r, r) must be refused",
                      cft_format_name(F));
            }

            ctx.total_order(a, b, dw);
            st = cft_total_order(ref, F, a.data(), b.data(), dc.data(), n);
            CHECK(st == CFT_OK, "cft_total_order: %s", cft_strerror(st));
            expect<F>("total_order", rnd, dw, 0, dc, 0);

            ctx.total_order_mag(a, b, dw);
            st = cft_total_order_mag(ref, F, a.data(), b.data(), dc.data(), n);
            CHECK(st == CFT_OK, "cft_total_order_mag: %s", cft_strerror(st));
            expect<F>("total_order_mag", rnd, dw, 0, dc, 0);

            std::vector<std::uint8_t> clsw(n), clsc(n);
            ctx.classify(a, clsw);
            st = cft_class(ref, F, a.data(), clsc.data(), n);
            CHECK(st == CFT_OK && clsw == clsc,
                  "%s: classify disagrees with cft_class", cft_format_name(F));
        }

        /* -- character sequences (5.12) and payloads (9.7) --------- *
         *
         * Part of the 0.6 step, and the same charter as everything
         * above: the wrapper's answer must be the C call's answer,
         * bit for bit and flag for flag. The shapes differ here, so
         * the comparison does too - the from_ direction is a batch and
         * is compared as one, and the to_ direction is per element, so
         * the whole pool is walked and every sequence compared as a
         * string. What the wrapper adds beyond marshalling is the
         * sizing protocol, and the strings would differ the moment it
         * got that wrong.
         */
        {
            std::uint32_t fw = 0, fc = 0;
            cft_status st;
            const std::size_t h = ctx.decimal_digits();

            CHECK(h == cft_format_decimal_digits(F),
                  "%s: decimal_digits disagrees with the C entry point",
                  cft_format_name(F));

            for (int rj = 0; rj < 5; rj++) {
                const cft_round rj_rnd = rounds[rj];
                auto rctx = ctx.with_rounding(rj_rnd);
                std::vector<std::string> seq(n);
                std::vector<const char *> raw(n);
                std::size_t i;

                /* Write the pool out through the wrapper and through
                 * the C entry point, in both radices and both digit
                 * modes, and compare the characters. */
                for (i = 0; i < n; i++) {
                    std::string wdec = rctx.to_decimal_char(a[i]);
                    std::string wrnd = rctx.to_decimal_char(a[i], h);
                    std::string whex = rctx.to_hex_char(a[i]);
                    std::vector<char> cbuf;
                    std::size_t need = 0;
                    std::uint32_t f1 = 0;

                    st = cft_to_decimal_char(ref, F, rj_rnd, a[i].data(), 0,
                                             nullptr, 0, &need, &f1);
                    CHECK(st == CFT_ERR_INVALID_ARGUMENT && need > 1,
                          "the sizing call must报 refuse and report a size");
                    cbuf.assign(need, '\0');
                    st = cft_to_decimal_char(ref, F, rj_rnd, a[i].data(), 0,
                                             cbuf.data(), need, &need, &f1);
                    CHECK(st == CFT_OK && wdec == cbuf.data() && f1 == 0,
                          "%s: to_decimal_char(exact) wrapper %s vs C %s",
                          cft_format_name(F), wdec.c_str(), cbuf.data());

                    st = cft_to_decimal_char(ref, F, rj_rnd, a[i].data(), h,
                                             nullptr, 0, &need, &f1);
                    cbuf.assign(need, '\0');
                    st = cft_to_decimal_char(ref, F, rj_rnd, a[i].data(), h,
                                             cbuf.data(), need, &need, &f1);
                    CHECK(st == CFT_OK && wrnd == cbuf.data(),
                          "%s: to_decimal_char(%u) wrapper %s vs C %s",
                          cft_format_name(F), static_cast<unsigned>(h),
                          wrnd.c_str(), cbuf.data());
                    CHECK(rctx.last_flags() == f1,
                          "%s: to_decimal_char flags disagree",
                          cft_format_name(F));

                    st = cft_to_hex_char(ref, F, a[i].data(), nullptr, 0,
                                         &need);
                    cbuf.assign(need, '\0');
                    st = cft_to_hex_char(ref, F, a[i].data(), cbuf.data(),
                                         need, &need);
                    CHECK(st == CFT_OK && whex == cbuf.data(),
                          "%s: to_hex_char wrapper %s vs C %s",
                          cft_format_name(F), whex.c_str(), cbuf.data());

                    seq[i] = wdec;
                    checks += 3;
                }

                /* ... and read the whole batch back, both ways. */
                for (i = 0; i < n; i++)
                    raw[i] = seq[i].c_str();
                fw = rctx.from_decimal_char(seq.data(), n, dw);
                st = cft_from_decimal_char(ref, F, rj_rnd, raw.data(),
                                           dc.data(), n, nullptr, &fc);
                CHECK(st == CFT_OK, "cft_from_decimal_char: %s",
                      cft_strerror(st));
                expect<F>("from_decimal_char", rj_rnd, dw, fw, dc, fc);

                for (i = 0; i < n; i++)
                    seq[i] = rctx.to_hex_char(a[i]);
                for (i = 0; i < n; i++)
                    raw[i] = seq[i].c_str();
                fw = rctx.from_hex_char(seq.data(), n, dw);
                st = cft_from_hex_char(ref, F, rj_rnd, raw.data(), dc.data(),
                                       n, nullptr, &fc);
                CHECK(st == CFT_OK, "cft_from_hex_char: %s",
                      cft_strerror(st));
                expect<F>("from_hex_char", rj_rnd, dw, fw, dc, fc);
                /* The hex form is exact, so reading it back reproduces
                 * the pool - through the wrapper, and with no flag. */
                CHECK(same_bytes<F>(dw, a, nullptr) && fw == 0,
                      "%s %s: the exact hex form did not round trip",
                      cft_format_name(F), cft::round_name(rj_rnd));
                checks++;
            }

            /* The 9.7 three, wrapper against C. */
            ctx.get_payload(a, dw);
            st = cft_get_payload(ref, F, a.data(), dc.data(), n);
            CHECK(st == CFT_OK, "cft_get_payload: %s", cft_strerror(st));
            expect<F>("get_payload", CFT_RNE, dw, 0, dc, 0);

            ctx.set_payload(a, dw);
            st = cft_set_payload(ref, F, a.data(), dc.data(), n);
            CHECK(st == CFT_OK, "cft_set_payload: %s", cft_strerror(st));
            expect<F>("set_payload", CFT_RNE, dw, 0, dc, 0);

            ctx.set_payload_signaling(a, dw);
            st = cft_set_payload_signaling(ref, F, a.data(), dc.data(), n);
            CHECK(st == CFT_OK, "cft_set_payload_signaling: %s",
                  cft_strerror(st));
            expect<F>("set_payload_signaling", CFT_RNE, dw, 0, dc, 0);

            /* A sequence outside the syntax reaches the caller as
             * cft::error carrying the C status, not as a number. */
            CHECK(status_of([&] { ctx.from_decimal_char("1.5.5"); })
                  == CFT_ERR_INVALID_ARGUMENT,
                  "%s: a malformed sequence must throw cft::error",
                  cft_format_name(F));
            CHECK(status_of([&] { ctx.from_hex_char("0x1.8"); })
                  == CFT_ERR_INVALID_ARGUMENT,
                  "%s: 5.12.3 requires the binary exponent",
                  cft_format_name(F));
            /* And a length mismatch is the wrapper's own misuse
             * exception, as everywhere else here. */
            {
                std::vector<std::string> two(2, std::string("1"));
                CHECK(refused_as_misuse(
                          [&] { ctx.from_decimal_char(two.data(), 2, dw); }),
                      "%s: a short sequence array must be std::invalid_argument",
                      cft_format_name(F));
            }
        }

        /* -- conversions ------------------------------------------ */
        {
            std::uint32_t fw = 0, fc = 0;
            cft_status st;

            /* Every destination format, including this one. */
            std::vector<cft::fp32_enc>  d32w(n),  d32c(n);
            std::vector<cft::fp64_enc>  d64w(n),  d64c(n);
            std::vector<cft::fp128_enc> d128w(n), d128c(n);
            std::vector<cft::fp256_enc> d256w(n), d256c(n);

            fw = ctx.template convert<CFT_FP32>(a, d32w);
            st = cft_convert(ref, F, CFT_FP32, rnd, a.data(), d32c.data(), n,
                             &fc);
            CHECK(st == CFT_OK && d32w == d32c && fw == fc,
                  "%s->fp32 convert (flags 0x%02x vs 0x%02x)",
                  cft_format_name(F), static_cast<unsigned>(fw),
                  static_cast<unsigned>(fc));

            fw = ctx.template convert<CFT_FP64>(a, d64w);
            st = cft_convert(ref, F, CFT_FP64, rnd, a.data(), d64c.data(), n,
                             &fc);
            CHECK(st == CFT_OK && d64w == d64c && fw == fc,
                  "%s->fp64 convert", cft_format_name(F));

            fw = ctx.template convert<CFT_FP128>(a, d128w);
            st = cft_convert(ref, F, CFT_FP128, rnd, a.data(), d128c.data(), n,
                             &fc);
            CHECK(st == CFT_OK && d128w == d128c && fw == fc,
                  "%s->fp128 convert", cft_format_name(F));

            fw = ctx.template convert<CFT_FP256>(a, d256w);
            st = cft_convert(ref, F, CFT_FP256, rnd, a.data(), d256c.data(), n,
                             &fc);
            CHECK(st == CFT_OK && d256w == d256c && fw == fc,
                  "%s->fp256 convert", cft_format_name(F));

            /* convertFromInt, all four widths. */
            std::vector<std::int32_t>  si32(n);
            std::vector<std::uint32_t> su32(n);
            std::vector<std::int64_t>  si64(n);
            std::vector<std::uint64_t> su64(n);
            for (std::size_t i = 0; i < n; i++) {
                const std::uint64_t r =
                    (static_cast<std::uint64_t>(rng_byte()) << 56) |
                    (static_cast<std::uint64_t>(rng_byte()) << 40) |
                    (static_cast<std::uint64_t>(rng_byte()) << 24) |
                    (static_cast<std::uint64_t>(rng_byte()) << 8) |
                    static_cast<std::uint64_t>(rng_byte());
                su64[i] = r;
                si64[i] = static_cast<std::int64_t>(r);
                su32[i] = static_cast<std::uint32_t>(r >> 32);
                si32[i] = static_cast<std::int32_t>(su32[i]);
            }

            fw = ctx.from_int(cft::cspan<std::int32_t>(si32), dw);
            st = cft_cvt_from_i32(ref, F, rnd, si32.data(), dc.data(), n, &fc);
            CHECK(st == CFT_OK, "cft_cvt_from_i32: %s", cft_strerror(st));
            expect<F>("cvt_from_i32", rnd, dw, fw, dc, fc);

            fw = ctx.from_int(cft::cspan<std::uint32_t>(su32), dw);
            st = cft_cvt_from_u32(ref, F, rnd, su32.data(), dc.data(), n, &fc);
            CHECK(st == CFT_OK, "cft_cvt_from_u32: %s", cft_strerror(st));
            expect<F>("cvt_from_u32", rnd, dw, fw, dc, fc);

            fw = ctx.from_int(cft::cspan<std::int64_t>(si64), dw);
            st = cft_cvt_from_i64(ref, F, rnd, si64.data(), dc.data(), n, &fc);
            CHECK(st == CFT_OK, "cft_cvt_from_i64: %s", cft_strerror(st));
            expect<F>("cvt_from_i64", rnd, dw, fw, dc, fc);

            fw = ctx.from_int(cft::cspan<std::uint64_t>(su64), dw);
            st = cft_cvt_from_u64(ref, F, rnd, su64.data(), dc.data(), n, &fc);
            CHECK(st == CFT_OK, "cft_cvt_from_u64: %s", cft_strerror(st));
            expect<F>("cvt_from_u64", rnd, dw, fw, dc, fc);

            /* convertToInteger, both families. The operands are the
             * specials plus scaled normals, so the invalid corners
             * (NaN, infinity, overflow) are all present. */
            for (int exact = 0; exact < 2; exact++) {
                std::vector<std::int32_t> oi32w(n), oi32c(n);
                fw = ctx.to_int(cft::cspan<enc>(a), cft::span<std::int32_t>(oi32w),
                                exact != 0);
                st = cft_cvt_to_i32(ref, F, rnd, exact, a.data(), oi32c.data(),
                                    n, &fc);
                CHECK(st == CFT_OK && oi32w == oi32c && fw == fc,
                      "%s cvt_to_i32 exact=%d", cft_format_name(F), exact);

                std::vector<std::uint32_t> ou32w(n), ou32c(n);
                fw = ctx.to_int(cft::cspan<enc>(a),
                                cft::span<std::uint32_t>(ou32w), exact != 0);
                st = cft_cvt_to_u32(ref, F, rnd, exact, a.data(), ou32c.data(),
                                    n, &fc);
                CHECK(st == CFT_OK && ou32w == ou32c && fw == fc,
                      "%s cvt_to_u32 exact=%d", cft_format_name(F), exact);

                std::vector<std::int64_t> oi64w(n), oi64c(n);
                fw = ctx.to_int(cft::cspan<enc>(a),
                                cft::span<std::int64_t>(oi64w), exact != 0);
                st = cft_cvt_to_i64(ref, F, rnd, exact, a.data(), oi64c.data(),
                                    n, &fc);
                CHECK(st == CFT_OK && oi64w == oi64c && fw == fc,
                      "%s cvt_to_i64 exact=%d", cft_format_name(F), exact);

                std::vector<std::uint64_t> ou64w(n), ou64c(n);
                fw = ctx.to_int(cft::cspan<enc>(a),
                                cft::span<std::uint64_t>(ou64w), exact != 0);
                st = cft_cvt_to_u64(ref, F, rnd, exact, a.data(), ou64c.data(),
                                    n, &fc);
                CHECK(st == CFT_OK && ou64w == ou64c && fw == fc,
                      "%s cvt_to_u64 exact=%d", cft_format_name(F), exact);
            }
        }
    }

    /* -- scalar == the batch of one, and the operators ------------- */
    {
        cft::basic_context<F> ctx(dev, CFT_RUP);   /* a directed attribute */
        const cft::value<F> x = ctx.make(a[9]);
        const cft::value<F> y = ctx.make(b[9]);
        const cft::value<F> z = ctx.make(c[9]);

        enc one_c{};
        std::uint32_t fc = 0;

        cft::value<F> got = ctx.fma(x, y, z);
        cft_run(ref, CFT_FMA, F, CFT_RUP, a.data() + 9, b.data() + 9,
                c.data() + 9, one_c.data(), 1, &fc, nullptr);
        CHECK(got.bytes() == one_c && ctx.last_flags() == fc,
              "%s scalar fma", cft_format_name(F));

        got = x + z;
        cft_run(ref, CFT_ADD, F, CFT_RUP, a.data() + 9, nullptr, c.data() + 9,
                one_c.data(), 1, &fc, nullptr);
        CHECK(got.bytes() == one_c && ctx.last_flags() == fc,
              "%s operator+ is one cft_run in the context's attribute",
              cft_format_name(F));

        got = x - z;
        cft_run(ref, CFT_SUB, F, CFT_RUP, a.data() + 9, nullptr, c.data() + 9,
                one_c.data(), 1, &fc, nullptr);
        CHECK(got.bytes() == one_c, "%s operator-", cft_format_name(F));

        got = x * y;
        cft_run(ref, CFT_MUL, F, CFT_RUP, a.data() + 9, b.data() + 9, nullptr,
                one_c.data(), 1, &fc, nullptr);
        CHECK(got.bytes() == one_c, "%s operator*", cft_format_name(F));

        got = x / y;
        cft_div(ref, F, CFT_RUP, a.data() + 9, b.data() + 9, one_c.data(), 1,
                &fc, nullptr);
        CHECK(got.bytes() == one_c && ctx.last_flags() == fc,
              "%s operator/ is cft_div", cft_format_name(F));

        got = -x;
        cft_run(ref, CFT_NEG, F, CFT_RUP, a.data() + 9, nullptr, nullptr,
                one_c.data(), 1, &fc, nullptr);
        CHECK(got.bytes() == one_c, "%s unary minus is CFT_NEG (5.5.1), not "
              "0 - x", cft_format_name(F));

        /* The predicates, including the swapped-operand ones. */
        const struct { const char *name; bool got_val; cft_op op; bool swap; }
        preds[] = {
            { "<",  x < y,  CFT_CMPLT, false },
            { "<=", x <= y, CFT_CMPLE, false },
            { "==", x == y, CFT_CMPEQ, false },
            { ">",  x > y,  CFT_CMPLT, true  },
            { ">=", x >= y, CFT_CMPLE, true  }
        };
        for (std::size_t pi = 0; pi < sizeof preds / sizeof preds[0]; pi++) {
            const void *pa = preds[pi].swap ? b.data() + 9 : a.data() + 9;
            const void *pb = preds[pi].swap ? a.data() + 9 : b.data() + 9;
            cft_run(ref, preds[pi].op, F, CFT_RUP, pa, pb, nullptr,
                    one_c.data(), 1, &fc, nullptr);
            CHECK(preds[pi].got_val == predicate_set(one_c.data(), esz),
                  "%s operator%s", cft_format_name(F), preds[pi].name);
        }
        CHECK((x != y) == !(x == y), "%s operator!=", cft_format_name(F));

        /* same_bits is encoding identity, not 754 equality: the two
         * zeros compare equal and are not the same bits. */
        const cft::value<F> pz = ctx.zero(0), nz = ctx.zero(1);
        CHECK(pz == nz && !pz.same_bits(nz),
              "%s: +0 == -0 but not same_bits", cft_format_name(F));

        /* Scalar clause-5, against the C call. */
        got = ctx.rint(x, true);
        cft_rint(ref, F, CFT_RUP, 1, a.data() + 9, one_c.data(), 1, &fc, nullptr);
        CHECK(got.bytes() == one_c, "%s scalar rint", cft_format_name(F));

        got = ctx.scaleb(x, 7);
        cft_scaleb(ref, F, CFT_RUP, a.data() + 9, 7, one_c.data(), 1, &fc,
                   nullptr);
        CHECK(got.bytes() == one_c, "%s scalar scaleb", cft_format_name(F));

        got = ctx.logb(x);
        cft_logb(ref, F, a.data() + 9, one_c.data(), 1, &fc);
        CHECK(got.bytes() == one_c, "%s scalar logb", cft_format_name(F));

        got = ctx.next_up(x);
        cft_next_up(ref, F, a.data() + 9, one_c.data(), 1, &fc);
        CHECK(got.bytes() == one_c, "%s scalar next_up", cft_format_name(F));

        got = ctx.next_down(x);
        cft_next_down(ref, F, a.data() + 9, one_c.data(), 1, &fc);
        CHECK(got.bytes() == one_c, "%s scalar next_down", cft_format_name(F));

        got = ctx.rem(x, y);
        cft_rem(ref, F, a.data() + 9, b.data() + 9, one_c.data(), 1, &fc);
        CHECK(got.bytes() == one_c, "%s scalar rem", cft_format_name(F));

        got = ctx.exp(x);
        cft_exp(ref, F, CFT_RUP, a.data() + 9, one_c.data(), 1, &fc);
        CHECK(got.bytes() == one_c, "%s scalar exp", cft_format_name(F));

        got = ctx.expm1(x);
        cft_expm1(ref, F, CFT_RUP, a.data() + 9, one_c.data(), 1, &fc);
        CHECK(got.bytes() == one_c, "%s scalar expm1", cft_format_name(F));

        got = ctx.exp2(x);
        cft_exp2(ref, F, CFT_RUP, a.data() + 9, one_c.data(), 1, &fc);
        CHECK(got.bytes() == one_c, "%s scalar exp2", cft_format_name(F));

        got = ctx.log(x);
        cft_log(ref, F, CFT_RUP, a.data() + 9, one_c.data(), 1, &fc);
        CHECK(got.bytes() == one_c, "%s scalar log", cft_format_name(F));

        got = ctx.log1p(x);
        cft_log1p(ref, F, CFT_RUP, a.data() + 9, one_c.data(), 1, &fc);
        CHECK(got.bytes() == one_c, "%s scalar log1p", cft_format_name(F));

        got = ctx.log2(x);
        cft_log2(ref, F, CFT_RUP, a.data() + 9, one_c.data(), 1, &fc);
        CHECK(got.bytes() == one_c, "%s scalar log2", cft_format_name(F));

        got = ctx.log10(x);
        cft_log10(ref, F, CFT_RUP, a.data() + 9, one_c.data(), 1, &fc);
        CHECK(got.bytes() == one_c, "%s scalar log10", cft_format_name(F));

        got = ctx.pow(x, y);
        cft_pow(ref, F, CFT_RUP, a.data() + 9, b.data() + 9, one_c.data(), 1,
                &fc);
        CHECK(got.bytes() == one_c, "%s scalar pow", cft_format_name(F));

        got = ctx.hypot(x, y);
        cft_hypot(ref, F, CFT_RUP, a.data() + 9, b.data() + 9, one_c.data(), 1,
                  &fc);
        CHECK(got.bytes() == one_c, "%s scalar hypot", cft_format_name(F));

#define STRIG1(name)                                                       \
        got = ctx.name(x);                                                 \
        cft_##name(ref, F, CFT_RUP, a.data() + 9, one_c.data(), 1, &fc);   \
        CHECK(got.bytes() == one_c, "%s scalar " #name, cft_format_name(F))
        STRIG1(sinpi);
        STRIG1(cospi);
        STRIG1(tanpi);
        STRIG1(asin);
        STRIG1(acos);
        STRIG1(atan);
        STRIG1(asinpi);
        STRIG1(acospi);
        STRIG1(atanpi);
        STRIG1(exp2m1);
        STRIG1(exp10);
        STRIG1(exp10m1);
        STRIG1(log2p1);
        STRIG1(log10p1);
        STRIG1(rsqrt);
#undef STRIG1

#define SINT1(name)                                                        \
        {                                                                  \
            const std::int64_t nn = 3;                                     \
            got = ctx.name(x, nn);                                         \
            cft_##name(ref, F, CFT_RUP, a.data() + 9, &nn, one_c.data(),   \
                       1, &fc);                                            \
            CHECK(got.bytes() == one_c, "%s scalar " #name,                \
                  cft_format_name(F));                                     \
        }
        SINT1(pown);
        SINT1(compound);
        SINT1(rootn);
#undef SINT1

        got = ctx.powr(x, y);
        cft_powr(ref, F, CFT_RUP, a.data() + 9, b.data() + 9, one_c.data(), 1,
                 &fc);
        CHECK(got.bytes() == one_c, "%s scalar powr", cft_format_name(F));

        got = ctx.atan2(x, y);
        cft_atan2(ref, F, CFT_RUP, a.data() + 9, b.data() + 9, one_c.data(), 1,
                  &fc);
        CHECK(got.bytes() == one_c, "%s scalar atan2", cft_format_name(F));

        got = ctx.atan2pi(x, y);
        cft_atan2pi(ref, F, CFT_RUP, a.data() + 9, b.data() + 9, one_c.data(),
                    1, &fc);
        CHECK(got.bytes() == one_c, "%s scalar atan2pi", cft_format_name(F));

        got = ctx.sqrt(x);
        cft_sqrt(ref, F, CFT_RUP, a.data() + 9, one_c.data(), 1, &fc, nullptr);
        CHECK(got.bytes() == one_c, "%s scalar sqrt", cft_format_name(F));

        got = ctx.min(x, y);
        cft_run(ref, CFT_MIN, F, CFT_RUP, a.data() + 9, b.data() + 9, nullptr,
                one_c.data(), 1, &fc, nullptr);
        CHECK(got.bytes() == one_c, "%s scalar min", cft_format_name(F));

        got = ctx.maxnum(x, y);
        cft_run(ref, CFT_MAXNUM, F, CFT_RUP, a.data() + 9, b.data() + 9, nullptr,
                one_c.data(), 1, &fc, nullptr);
        CHECK(got.bytes() == one_c, "%s scalar maxnum", cft_format_name(F));

        got = ctx.abs(x);
        cft_run(ref, CFT_ABS, F, CFT_RUP, a.data() + 9, nullptr, nullptr,
                one_c.data(), 1, &fc, nullptr);
        CHECK(got.bytes() == one_c, "%s scalar abs", cft_format_name(F));

        got = ctx.copysign(x, y);
        cft_run(ref, CFT_COPYSIGN, F, CFT_RUP, a.data() + 9, b.data() + 9,
                nullptr, one_c.data(), 1, &fc, nullptr);
        CHECK(got.bytes() == one_c, "%s scalar copysign", cft_format_name(F));

        got = ctx.select(x, y, z);
        cft_run(ref, CFT_SELECT, F, CFT_RUP, a.data() + 9, b.data() + 9,
                c.data() + 9, one_c.data(), 1, &fc, nullptr);
        CHECK(got.bytes() == one_c, "%s scalar select", cft_format_name(F));

        {
            std::uint8_t cls_c = 0;
            cft_class(ref, F, a.data() + 9, &cls_c, 1);
            CHECK(static_cast<std::uint8_t>(ctx.classify(x)) == cls_c,
                  "%s scalar classify", cft_format_name(F));

            cft_total_order(ref, F, a.data() + 9, b.data() + 9, one_c.data(), 1);
            CHECK(ctx.total_order(x, y) == predicate_set(one_c.data(), esz),
                  "%s scalar total_order", cft_format_name(F));
            cft_total_order_mag(ref, F, a.data() + 9, b.data() + 9,
                                one_c.data(), 1);
            CHECK(ctx.total_order_mag(x, y) == predicate_set(one_c.data(), esz),
                  "%s scalar total_order_mag", cft_format_name(F));
        }

        /* The integer and double doorways. */
        {
            const std::int64_t iv = -1234567890123ll;
            const cft::value<F> fv = ctx.from_int(iv);
            enc ic{};
            cft_cvt_from_i64(ref, F, CFT_RUP, &iv, ic.data(), 1, &fc);
            CHECK(fv.bytes() == ic && ctx.last_flags() == fc,
                  "%s from_int(int64)", cft_format_name(F));

            std::int64_t back_c = 0;
            cft_cvt_to_i64(ref, F, CFT_RUP, 1, ic.data(), &back_c, 1, &fc);
            CHECK(ctx.template to_int<std::int64_t>(fv, true) == back_c,
                  "%s to_int(int64)", cft_format_name(F));

            const double dv = 0.1;
            cft::fp64_enc src{};
            std::memcpy(src.data(), &dv, sizeof dv);
            enc via_c{};
            cft_convert(ref, CFT_FP64, F, CFT_RUP, src.data(), via_c.data(), 1,
                        &fc);
            const cft::value<F> from_d = ctx.from_double(dv);
            CHECK(from_d.bytes() == via_c && ctx.last_flags() == fc,
                  "%s from_double goes through cft_convert",
                  cft_format_name(F));

            cft::fp64_enc back64{};
            cft_convert(ref, F, CFT_FP64, CFT_RUP, via_c.data(), back64.data(),
                        1, &fc);
            double want = 0.0;
            std::memcpy(&want, back64.data(), sizeof want);
            const double got_d = ctx.to_double(from_d);
            CHECK(std::memcmp(&got_d, &want, sizeof want) == 0,
                  "%s to_double goes through cft_convert", cft_format_name(F));
        }

        /* Flag bookkeeping: sticky is the OR of the calls, last is the
         * most recent, and clearing clears only the sticky word. */
        {
            cft::basic_context<F> fctx(dev, CFT_RNE);
            CHECK(fctx.flags() == 0 && fctx.last_flags() == 0,
                  "%s: a fresh context has no flags", cft_format_name(F));
            std::vector<enc> out(n);
            const std::uint32_t f1 = fctx.mul(a, b, out);
            const std::uint32_t f2 = fctx.abs(a, out);
            CHECK(fctx.last_flags() == f2 && fctx.flags() == (f1 | f2),
                  "%s: sticky flags are the OR (0x%02x vs 0x%02x)",
                  cft_format_name(F), static_cast<unsigned>(fctx.flags()),
                  static_cast<unsigned>(f1 | f2));
            fctx.clear_flags();
            CHECK(fctx.flags() == 0 && fctx.last_flags() == f2,
                  "%s: clear_flags clears only the sticky word",
                  cft_format_name(F));
        }

        /* Refusals: the library's, and the wrapper's own. */
        {
            std::vector<enc> out(n);
            CHECK(status_of([&] { ctx.map(CFT_SUM, a, b, c, out); }) ==
                      CFT_ERR_INVALID_ARGUMENT,
                  "%s: a reduction through map() is refused, as cft_run "
                  "refuses it", cft_format_name(F));

            std::vector<enc> shorter(n - 1);
            CHECK(refused_as_misuse([&] {
                      ctx.add(cft::cspan<enc>(shorter), c, out);
                  }),
                  "%s: an operand shorter than the output is refused",
                  cft_format_name(F));

            cft::basic_context<F> other(dev, CFT_RDN);
            const cft::value<F> foreign = other.make(a[0]);
            CHECK(refused_as_misuse([&] { const cft::value<F> r = x + foreign;
                                          (void)r; }),
                  "%s: values from two contexts do not mix",
                  cft_format_name(F));
        }
    }
}

/* =================================================================
 * The sequencer program, both ways
 * ================================================================= */
std::uint64_t seq_alu(unsigned op, unsigned rd, unsigned ra, unsigned rb,
                      unsigned rc, unsigned rnd)
{
    return static_cast<std::uint64_t>(op) |
           (static_cast<std::uint64_t>(rd) << 8) |
           (static_cast<std::uint64_t>(ra) << 12) |
           (static_cast<std::uint64_t>(rb) << 16) |
           (static_cast<std::uint64_t>(rc) << 20) |
           (static_cast<std::uint64_t>(rnd) << 24);
}

std::uint64_t seq_ctrl(unsigned code, unsigned ra)
{
    return static_cast<std::uint64_t>(code) |
           (static_cast<std::uint64_t>(ra) << 12) |
           (static_cast<std::uint64_t>(1) << 31);
}

void put_le32(std::uint8_t *p, std::uint32_t v)
{
    p[0] = static_cast<std::uint8_t>(v);
    p[1] = static_cast<std::uint8_t>(v >> 8);
    p[2] = static_cast<std::uint8_t>(v >> 16);
    p[3] = static_cast<std::uint8_t>(v >> 24);
}

/* Header + no constants + instructions; the image format of
 * docs/SEQUENCER.md, packed here the way host/tests/device_test.c
 * packs it. */
std::vector<std::uint8_t> seq_image(cft_format fmt,
                                    const std::vector<std::uint64_t> &insns,
                                    std::uint32_t max_deposits)
{
    std::vector<std::uint8_t> img(32 + insns.size() * 8, 0);
    put_le32(&img[0], 0x50544643u);          /* "CFTP" */
    put_le32(&img[4], 1);
    put_le32(&img[8], static_cast<std::uint32_t>(insns.size()));
    put_le32(&img[12], 0);                   /* no constants */
    put_le32(&img[16], max_deposits);
    put_le32(&img[20], static_cast<std::uint32_t>(fmt));
    for (std::size_t i = 0; i < insns.size(); i++)
        for (int b = 0; b < 8; b++)
            img[32 + i * 8 + static_cast<std::size_t>(b)] =
                static_cast<std::uint8_t>(insns[i] >> (8 * b));
    return img;
}

void check_program(cft::device &dev, cft_device *ref)
{
    using enc = cft::fp32_enc;
    const std::size_t n = 16;

    /* r4 = r0*r1 + r2; deposit r4; halt. */
    std::vector<std::uint64_t> insns;
    insns.push_back(seq_alu(0, 4, 0, 1, 2, 0));
    insns.push_back(seq_ctrl(3, 4));
    insns.push_back(seq_ctrl(0, 0));
    const std::vector<std::uint8_t> img = seq_image(CFT_FP32, insns, 1);

    std::vector<enc> a(n), b(n), c(n);
    for (std::size_t i = 0; i < n; i++) {
        a[i] = random_normal<CFT_FP32>();
        b[i] = random_normal<CFT_FP32>();
        c[i] = random_normal<CFT_FP32>();
    }

    std::vector<enc> depw(n), depc(n);
    std::vector<std::uint32_t> cntw(n), cntc(n);

    cft::program prog = dev.load_program(img.data(), img.size());
    cft_program_info info;
    const cft_status ist = prog.info(info);
    CHECK(ist == CFT_OK && info.format == CFT_FP32 && info.max_deposits == 1 &&
              info.n_insns == 3 && info.n_consts == 0 && prog.get() != nullptr,
          "program info: %s", cft_strerror(ist));

    const cft::call_result rw = prog.run(a.data(), b.data(), c.data(),
                                         depw.data(), cntw.data(), n);

    cft_program *pref = nullptr;
    cft_status st = cft_program_load(ref, img.data(), img.size(), &pref);
    CHECK(st == CFT_OK, "cft_program_load: %s", cft_strerror(st));
    std::uint32_t fc = 0, busc = 0;
    st = cft_program_run(pref, a.data(), b.data(), c.data(), depc.data(),
                         cntc.data(), n, &fc, &busc);
    cft_program_free(pref);

    CHECK(rw.status == st && rw.flags == fc && rw.bus == busc &&
              depw == depc && cntw == cntc,
          "program run: wrapper %s/0x%02x, C %s/0x%02x",
          cft_strerror(rw.status), static_cast<unsigned>(rw.flags),
          cft_strerror(st), static_cast<unsigned>(fc));

    /* Move semantics: the moved-from program is empty and safe, the
     * moved-to one still runs. */
    cft::program moved = std::move(prog);
    CHECK(!prog && moved, "program move leaves the source empty");
    const cft::call_result again = moved.run(a.data(), b.data(), c.data(),
                                             depw.data(), cntw.data(), n);
    CHECK(again.status == CFT_OK && depw == depc,
          "a moved program still runs");
    CHECK(cft::program().run(nullptr, nullptr, nullptr, nullptr, nullptr, 0)
                  .status == CFT_ERR_INVALID_ARGUMENT,
          "an empty program refuses rather than dereferencing null");
}

/* =================================================================
 * Device-level checks that are not per-format
 * ================================================================= */
void check_device(cft::device &dev, cft_device *ref)
{
    CHECK(cft::runtime_abi_version() == cft_abi_version(),
          "runtime_abi_version passes cft_abi_version through");
    CHECK(cft::abi_compatible(),
          "this header (%u.%u) is compatible with the library it linked "
          "(%u.%u)",
          static_cast<unsigned>(cft::header_abi_version >> 16),
          static_cast<unsigned>(cft::header_abi_version & 0xffffu),
          static_cast<unsigned>(cft_abi_version() >> 16),
          static_cast<unsigned>(cft_abi_version() & 0xffffu));

    cft_caps craw;
    std::memset(&craw, 0, sizeof craw);
    craw.struct_size = sizeof craw;
    const cft_status st = cft_get_caps(ref, &craw);
    CHECK(st == CFT_OK, "cft_get_caps: %s", cft_strerror(st));

    const cft::capabilities caps = dev.caps();
    CHECK(caps.format_mask == craw.format_mask && caps.tiles == craw.tiles &&
              caps.abi_version == craw.abi_version &&
              caps.device_version == craw.device_version &&
              caps.flags_readable == (craw.flags_readable != 0) &&
              caps.backend == std::string(craw.backend),
          "caps() reproduces cft_get_caps (backend '%s' vs '%s')",
          caps.backend.c_str(), craw.backend);

    static const cft_format fmts[4] = { CFT_FP32, CFT_FP64, CFT_FP128,
                                        CFT_FP256 };
    bool supports_agrees = true;
    bool mask_agrees = true;
    for (std::size_t fi = 0; fi < 4; fi++) {
        if (dev.supports(CFT_FMA, fmts[fi]) !=
            (cft_supports(ref, CFT_FMA, fmts[fi]) != 0))
            supports_agrees = false;
        if (caps.has_format(fmts[fi]) !=
            ((craw.format_mask & (1u << static_cast<unsigned>(fmts[fi]))) != 0))
            mask_agrees = false;
    }
    CHECK(supports_agrees, "supports() reproduces cft_supports");
    CHECK(mask_agrees, "has_format() reads the format mask the same way");

    /* Names come from the library, not from a table here. */
    CHECK(std::string(cft::format_name(CFT_FP128)) == "fp128" &&
              std::string(cft::op_name(CFT_MINNUM)) ==
                  std::string(cft_op_name(CFT_MINNUM)) &&
              cft::format_size(CFT_FP256) == cft_format_size(CFT_FP256),
          "the name and size helpers pass through to the library");
    CHECK(std::string(cft::round_name(CFT_RMM)) == "rmm" &&
              std::string(cft::round_name(CFT_RDN)) == "rdn",
          "round_name spells the attributes cft.h's way");

    CHECK(cft::flag_names(0) == "none" &&
              cft::flag_names(CFT_FLAG_INEXACT) == "inexact" &&
              cft::flag_names(CFT_FLAG_INVALID | CFT_FLAG_INEXACT) ==
                  "invalid|inexact" &&
              cft::flag_names(1u << 9) == "unknown(0x200)",
          "flag_names names what it can and reports what it cannot (%s)",
          cft::flag_names(1u << 9).c_str());

    /* to_bits / from_bits at the two widths that fit an integer. */
    CHECK(cft::to_bits(cft::from_bits32(0x3f800000u)) == 0x3f800000u &&
              cft::to_bits(cft::from_bits64(0x3ff0000000000000ull)) ==
                  0x3ff0000000000000ull &&
              cft::from_bits32(0x3f800000u) == cft::one_enc<CFT_FP32>() &&
              cft::from_bits64(0x3ff0000000000000ull) ==
                  cft::one_enc<CFT_FP64>(),
          "the 32- and 64-bit integer views agree with one_enc()");

    /* The accessors and the small helpers, so that "every entry point
     * is exercised" is a claim about all of them and not most. */
    {
        cft::check_abi();               /* must not throw against this library */
        CHECK(dev.get() != nullptr, "device::get() hands back the raw handle");

        cft::context128 ctx(dev, CFT_RDN);
        CHECK(&ctx.get_device() == &dev && ctx.rounding() == CFT_RDN &&
                  std::string(ctx.rounding_name()) == "rdn" &&
                  std::string(ctx.format_name()) == "fp128" &&
                  ctx.supports(CFT_FMA) == dev.supports(CFT_FMA, CFT_FP128),
              "the context's accessors");
        const cft::context128 up = ctx.with_rounding(CFT_RUP);
        CHECK(up.rounding() == CFT_RUP && ctx.rounding() == CFT_RDN,
              "with_rounding makes a new context and leaves this one alone");
        CHECK(ctx.flag_names() == "none", "a fresh context names no flags");

        const cft::fp128_value one = ctx.one();
        CHECK(one.context() == &ctx && one.same_bits(ctx.from_hex(one.hex())),
              "value::context(), and hex out and back through the context");
        CHECK(ctx.inf(1).bytes() == cft::inf_enc<CFT_FP128>(1) &&
                  ctx.quiet_nan().bytes() == cft::quiet_nan_enc<CFT_FP128>() &&
                  ctx.signaling_nan().bytes() ==
                      cft::signaling_nan_enc<CFT_FP128>(),
              "the context's special constructors");

        /* nextUp(1) is 1 with the low significand bit set, which holds
         * only if the traits' significand width is the library's. */
        cft::fp128_enc want = cft::one_enc<CFT_FP128>();
        want[0] = static_cast<std::uint8_t>(want[0] | 1u);
        CHECK(ctx.next_up(one).bytes() == want,
              "nextUp(1) pins the significand width against the library");

        /* The span view, whichever one this build got. */
        std::vector<cft::fp32_enc> sv3(3);
        const cft::span<cft::fp32_enc> sv(sv3);
        std::size_t counted = 0;
        for (const cft::fp32_enc &e : sv) {
            (void)e;
            counted++;
        }
        CHECK(!sv.empty() && sv.size() == 3 && counted == 3 &&
                  sv.size_bytes() == 12 && sv.data() == sv3.data() &&
                  cft::span<cft::fp32_enc>().empty(),
              "the span view's shape");
    }

    /* Device buffers: RAII, and the pointer feeds cft_run directly. */
    {
        cft::buffer buf = dev.alloc(4096);
        CHECK(static_cast<bool>(buf) && buf.data() != nullptr &&
                  buf.size() == 4096 && buf.get() != nullptr,
              "cft_alloc through the wrapper");
        std::uint8_t *p = static_cast<std::uint8_t *>(buf.data());
        const cft::fp32_enc one = cft::one_enc<CFT_FP32>();
        std::memcpy(p, one.data(), 4);
        std::memcpy(p + 8, one.data(), 4);
        CHECK(buf.to_device() == CFT_OK && buf.from_device() == CFT_OK,
              "buffer sync calls");
        cft::context32 ctx(dev, CFT_RNE);
        cft::cspan<cft::fp32_enc> av(
            reinterpret_cast<const cft::fp32_enc *>(p), 1);
        cft::cspan<cft::fp32_enc> cv(
            reinterpret_cast<const cft::fp32_enc *>(p + 8), 1);
        cft::span<cft::fp32_enc> dv(
            reinterpret_cast<cft::fp32_enc *>(p + 16), 1);
        ctx.add(av, cv, dv);
        cft::fp32_enc want{};
        std::uint32_t fc = 0;
        cft_run(ref, CFT_ADD, CFT_FP32, CFT_RNE, one.data(), nullptr,
                one.data(), want.data(), 1, &fc, nullptr);
        CHECK(std::memcmp(p + 16, want.data(), 4) == 0,
              "a run over a device buffer matches the C call");

        cft::buffer moved = std::move(buf);
        CHECK(!buf && moved && moved.data() != nullptr,
              "buffer move leaves the source empty");
    }

    /* The handle itself: move, close, and calls on an empty device. */
    {
        cft::device d2;
        CHECK(!d2, "a default device holds no handle");
        CHECK(d2.run(CFT_ADD, CFT_FP32, CFT_RNE, nullptr, nullptr, nullptr,
                     nullptr, 0).status == CFT_ERR_INVALID_ARGUMENT,
              "an empty device refuses rather than dereferencing null");
        CHECK(d2.try_open(nullptr, 0) == CFT_OK && d2,
              "try_open reports rather than throws");
        cft::device d3 = std::move(d2);
        CHECK(!d2 && d3, "device move leaves the source empty");
        cft::fp32_enc out{};
        const cft::fp32_enc one = cft::one_enc<CFT_FP32>();
        CHECK(d3.run(CFT_ADD, CFT_FP32, CFT_RNE, one.data(), nullptr,
                     one.data(), out.data(), 1).ok(),
              "a moved device still runs");
        d3.close();
        CHECK(!d3, "close() empties the handle");
    }

    /* Opening a nonexistent artifact is a status, not a crash - and
     * the exception carries it. */
    {
        cft_status caught = CFT_OK;
        try {
            cft::device bad("no-such-artifact.xclbin", 0);
        } catch (const cft::error &e) {
            caught = e.status();
            CHECK(std::string(e.what()).find(cft_strerror(e.status())) !=
                      std::string::npos,
                  "cft::error::what() carries cft_strerror's text: %s",
                  e.what());
            CHECK(e.detail().empty() ||
                      std::string(e.what()).find(e.detail()) !=
                          std::string::npos,
                  "cft::error::detail() is a copy of what cft_last_error "
                  "said, and what() carries it: '%s'", e.detail().c_str());
        }
        CHECK(caught != CFT_OK, "a bad artifact throws cft::error");
    }
}


/* ---- the formatOf arithmetic (754-2019 5.4.1) --------------------- *
 *
 * Two formats, so this cannot live inside check_format<F>: the source
 * and the destination are separate template parameters and every
 * ordered pair gets its own instantiation, which is the point - handing
 * binary64 encodings to a call that reads them as binary32 is a compile
 * error in this layer and a silent wrong answer in C.
 *
 * Three paths compared, not two: the typed free function, the raw
 * method on cft::device, and cft.h itself. The middle one exists
 * because it is what a caller with its own buffers uses, and a wrapper
 * whose typed path was right and whose raw path had the operands
 * swapped would pass a two-path test.
 */
template <cft_format SF, cft_format DF>
void check_formatof(cft::device &dev, cft_device *ref)
{
    using senc = cft::encoding<SF>;
    using denc = cft::encoding<DF>;
    const std::size_t n = 129;          /* crosses the widening chunking */
    static const cft_round rounds[5] = { CFT_RNE, CFT_RTZ, CFT_RDN,
                                         CFT_RUP, CFT_RMM };

    const std::vector<senc> a = operands<SF>(n, 0);
    const std::vector<senc> b = operands<SF>(n, 3);
    const std::vector<senc> c = operands<SF>(n, 5);

    for (std::size_t ri = 0; ri < 5; ri++) {
        const cft_round rnd = rounds[ri];
        std::vector<denc> dw(n), dc(n), dr(n);
        std::uint32_t fw = 0, fc = 0, fr = 0;
        cft_status st;

#define FO2(name)                                                         \
        fw = cft::formatof_##name<SF, DF>(dev, rnd, a, b, dw);            \
        st = cft_formatof_##name(ref, SF, DF, rnd, a.data(), b.data(),    \
                                 dc.data(), n, &fc, nullptr);             \
        CHECK(st == CFT_OK, "cft_formatof_" #name ": %s",                 \
              cft_strerror(st));                                          \
        expect<DF>("formatof_" #name, rnd, dw, fw, dc, fc);               \
        {                                                                 \
            const cft::call_result r =                                    \
                dev.formatof_##name(SF, DF, rnd, a.data(), b.data(),      \
                                    dr.data(), n);                        \
            fr = r.flags;                                                 \
            CHECK(r.status == CFT_OK, "device::formatof_" #name);         \
            expect<DF>("formatof_" #name " (raw)", rnd, dr, fr, dc, fc);  \
        }
        FO2(add)
        FO2(sub)
        FO2(mul)
        FO2(div)
#undef FO2

        fw = cft::formatof_sqrt<SF, DF>(dev, rnd, a, dw);
        st = cft_formatof_sqrt(ref, SF, DF, rnd, a.data(), dc.data(), n,
                               &fc, nullptr);
        CHECK(st == CFT_OK, "cft_formatof_sqrt: %s", cft_strerror(st));
        expect<DF>("formatof_sqrt", rnd, dw, fw, dc, fc);

        fw = cft::formatof_fma<SF, DF>(dev, rnd, a, b, c, dw);
        st = cft_formatof_fma(ref, SF, DF, rnd, a.data(), b.data(),
                              c.data(), dc.data(), n, &fc, nullptr);
        CHECK(st == CFT_OK, "cft_formatof_fma: %s", cft_strerror(st));
        expect<DF>("formatof_fma", rnd, dw, fw, dc, fc);
    }

    /* A short destination span is refused before any call is issued -
     * the one thing this layer can check that C cannot, since C has
     * only pointers and a count. */
    {
        std::vector<denc> shortd(2);
        bool threw = false;
        try {
            std::vector<senc> two(2);
            cft::formatof_add<SF, DF>(dev, CFT_RNE,
                                      cft::cspan<senc>(two.data(), 1),
                                      cft::cspan<senc>(two.data(), 2),
                                      cft::span<denc>(shortd.data(), 2));
        } catch (const std::invalid_argument &) {
            threw = true;
        }
        CHECK(threw, "%s->%s: an operand span shorter than the destination "
                     "is refused", cft_format_name(SF), cft_format_name(DF));
    }

    /* The same-format instantiation is the operation that was already
     * there. Checked HERE rather than only in C, because the wrapper is
     * where a format could get swapped for its neighbour. */
    if (SF == DF) {
        std::vector<denc> dw(n), dc(n);
        const std::uint32_t fw2 =
            cft::formatof_add<SF, DF>(dev, CFT_RNE, a, b, dw);
        std::uint32_t fc2 = 0;
        const cft_status st2 =
            cft_run(ref, CFT_ADD, SF, CFT_RNE, a.data(), nullptr, b.data(),
                    dc.data(), n, &fc2, nullptr);
        CHECK(st2 == CFT_OK, "cft_run: %s", cft_strerror(st2));
        expect<DF>("formatof_add == run(ADD)", CFT_RNE, dw, fw2, dc, fc2);
    }

    /* 5.11's cross-format comparison, as the COMPOSITION cft.h says it
     * is: widen both sides into the wider of the two formats and use the
     * comparison that already exists. Exercised rather than asserted,
     * and the assertion that matters is that the widening rounds
     * NOTHING - the clause asks for a comparison "as if the data were
     * converted to a common format with unbounded exponent range and
     * precision", and this composition only computes that because the
     * ladder nests. */
    {
        const cft_format wide =
            (cft::format_traits<SF>::significand_bits >=
             cft::format_traits<DF>::significand_bits) ? SF : DF;
        const std::size_t wsz = cft_format_size(wide);
        std::vector<denc> dvals(n);
        std::vector<std::uint8_t> wa(n * wsz), wb(n * wsz), pred(n * wsz);
        std::uint32_t f0 = 0, f1 = 0, f2 = 0, f3 = 0;

        /* the second side is a real destination-format value, so the
         * comparison has two formats to reconcile rather than one */
        const cft_status s0 = cft_formatof_add(ref, SF, DF, CFT_RNE,
                                               a.data(), b.data(),
                                               dvals.data(), n, &f0,
                                               nullptr);
        const cft_status s1 = cft_convert(ref, SF, wide, CFT_RNE, a.data(),
                                          wa.data(), n, &f1);
        const cft_status s2 = cft_convert(ref, DF, wide, CFT_RNE,
                                          dvals.data(), wb.data(), n, &f2);
        const cft_status s3 = cft_run(ref, CFT_CMPLT, wide, CFT_RNE,
                                      wa.data(), wb.data(), nullptr,
                                      pred.data(), n, &f3, nullptr);
        CHECK(s0 == CFT_OK && s1 == CFT_OK && s2 == CFT_OK && s3 == CFT_OK,
              "%s vs %s: the 5.11 composition runs",
              cft_format_name(SF), cft_format_name(DF));
        CHECK((f1 & ~static_cast<std::uint32_t>(CFT_FLAG_INVALID)) == 0 &&
              (f2 & ~static_cast<std::uint32_t>(CFT_FLAG_INVALID)) == 0,
              "%s/%s: 5.11's widening into the common format must be exact, "
              "got 0x%02x and 0x%02x", cft_format_name(SF),
              cft_format_name(DF), static_cast<unsigned>(f1),
              static_cast<unsigned>(f2));
        /* and the quiet comparison signals nothing at all, even where
         * the widening met a signaling NaN on the way in */
        CHECK(f3 == 0, "%s/%s: the quiet comparison signals nothing",
              cft_format_name(SF), cft_format_name(DF));
    }
}

}  // namespace

int main(int argc, char **argv)
{
    const char *vdir = (argc > 1) ? argv[1] : "../vectors/out";

    cft::device dev;
    cft_device *ref = nullptr;

    try {
        dev = cft::device(nullptr, 0);
    } catch (const cft::error &e) {
        std::printf("cpp-api-test: cannot open the software backend: %s\n",
                    e.what());
        return 1;
    }
    const cft_status st = cft_open(nullptr, 0, &ref);
    if (st != CFT_OK) {
        std::printf("cpp-api-test: cft_open: %s\n", cft_strerror(st));
        return 1;
    }

    std::printf("cpp-api-test: cft.hpp against cft.h, __cplusplus %ld, "
                "span is %s\n", static_cast<long>(__cplusplus),
                CFT_HPP_STD_SPAN ? "std::span" : "the header's own view");

    check_device(dev, ref);
    check_format<CFT_FP32>(dev, ref);
    check_format<CFT_FP64>(dev, ref);
    check_format<CFT_FP128>(dev, ref);
    check_format<CFT_FP256>(dev, ref);
    check_program(dev, ref);

    /* Every ordered pair of formats through the formatOf layer. The
     * loop is written out because SF and DF are template parameters -
     * which is the whole point of the typed layer, and the reason a
     * mismatched pair is a compile error rather than a wrong answer. */
#define FOPAIR(S, D) check_formatof<S, D>(dev, ref)
    FOPAIR(CFT_FP32, CFT_FP32);  FOPAIR(CFT_FP32, CFT_FP64);
    FOPAIR(CFT_FP32, CFT_FP128); FOPAIR(CFT_FP32, CFT_FP256);
    FOPAIR(CFT_FP64, CFT_FP32);  FOPAIR(CFT_FP64, CFT_FP64);
    FOPAIR(CFT_FP64, CFT_FP128); FOPAIR(CFT_FP64, CFT_FP256);
    FOPAIR(CFT_FP128, CFT_FP32); FOPAIR(CFT_FP128, CFT_FP64);
    FOPAIR(CFT_FP128, CFT_FP128);FOPAIR(CFT_FP128, CFT_FP256);
    FOPAIR(CFT_FP256, CFT_FP32); FOPAIR(CFT_FP256, CFT_FP64);
    FOPAIR(CFT_FP256, CFT_FP128);FOPAIR(CFT_FP256, CFT_FP256);
#undef FOPAIR

    /* Conformance through the wrapper: the published vector sets,
     * replayed by cft_conformance itself rather than by a restatement
     * of it here. A missing set directory is reported by name - a
     * replay that quietly checked nothing must not read as a pass. */
    {
        const cft::device::conformance_result r = dev.conformance(vdir);
        if (r.status == CFT_ERR_ARTIFACT) {
            std::printf("cpp-api-test: SKIP conformance: no vector sets in "
                        "%s (run `make vectors` from the repo root)\n", vdir);
        } else {
            CHECK(r.ok(), "conformance replay: %s", cft_strerror(r.status));
            CHECK(r.cases > 0 && !r.report.empty(),
                  "conformance reports its summary even on success");
            std::printf("cpp-api-test: conformance replayed %llu cases from "
                        "%s\n", static_cast<unsigned long long>(r.cases), vdir);
        }
    }

    cft_close(ref);

    if (failures == 0)
        std::printf("cpp-api-test: all %d checks passed\n", checks);
    else
        std::printf("cpp-api-test: %d of %d checks FAILED\n", failures, checks);
    return failures ? 1 : 0;
}
