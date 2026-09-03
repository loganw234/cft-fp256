/* Copyright 2026 Logan W.
 * SPDX-License-Identifier: Apache-2.0
 *
 * cft.hpp - the C++ layer over libcft's C ABI.
 *
 * Header-only, C++17 minimum, no dependencies beyond the standard
 * library and cft.h. Include it, link libcft, done: there is nothing
 * to build here, because a wrapper that needed a build step would cost
 * more than the twelve extern "C" declarations it saves.
 *
 * ---------------------------------------------------------------
 * What this adds, and what it emphatically does not
 * ---------------------------------------------------------------
 *
 * It adds four things, all of them bookkeeping:
 *
 *   1. RAII for the handles - cft_device, cft_buffer, cft_program.
 *   2. Fixed-width byte types per format, so an fp128 operand cannot
 *      be spelled as a double and a buffer cannot be sized wrong.
 *   3. Spans, so the (pointer, count) pairs cft_run wants are checked
 *      against each other instead of trusted.
 *   4. A Context: a format, a rounding attribute and a device, so
 *      that x + y has somewhere to read the attribute FROM.
 *
 * It adds NOTHING numeric. There is no floating-point arithmetic in
 * this header - no +, -, * or / on a float or a double anywhere in it,
 * and no bit surgery that decides a rounding. Every result comes back
 * from a libcft entry point, because a second implementation of the
 * semantics is exactly how "identical bits" quietly stops being true,
 * and a C++ header is a particularly good place for that to happen
 * quietly: the compiler will happily contract a*b+c into an fma, or
 * not, depending on flags nobody remembers passing.
 *
 * The only arithmetic here is on sizes and indices, in std::size_t.
 *
 * ---------------------------------------------------------------
 * Determinism: what you may rely on
 * ---------------------------------------------------------------
 *
 * Everything docs/DETERMINISM.md promises, unchanged and undiluted:
 * the same call with the same inputs returns the same bits and the
 * same flags, on the software backend and on the tile, on every
 * machine, on every day. Reductions have a fixed tree shape that is
 * part of the contract rather than an artifact of an accumulation
 * order. Any NaN in gives the one canonical quiet NaN out.
 *
 * What this header contributes to that guarantee is nothing at all,
 * and that is the point. It marshals arguments and hands them to the
 * same functions cft.h documents; if a program written against
 * cft.hpp disagrees with the same program written against cft.h, the
 * bug is here and this header's own test (host/tests/cpp_api_test.cpp)
 * is what finds it - every entry point below is checked against the
 * C call on the same inputs for bit-identical encodings and identical
 * flags.
 *
 * Two host-side facts the header depends on and checks at compile
 * time rather than assuming: an encoding type is exactly its format's
 * width in bytes (so an array of them is the dense buffer cft_run
 * wants), and `double` is IEEE binary64 in the byte order the library
 * uses (so the ONE place a host double is reinterpreted - the fp64
 * doorway of to_double/from_double - is a copy and not a conversion).
 * Everything wider than binary64 reaches a double through
 * cft_convert, which rounds it, in the library, once. Nothing in this
 * header ever passes a wider format through a double.
 *
 * ---------------------------------------------------------------
 * Shape
 * ---------------------------------------------------------------
 *
 *   cft::device            RAII cft_device. The C ABI projected one
 *                          to one: void pointers, element counts,
 *                          status returned rather than thrown.
 *   cft::basic_context<F>  a format + a rounding attribute + a device.
 *                          Typed spans, sticky flags, exceptions.
 *   cft::value<F>          one encoding bound to a context, so that
 *                          the operators have an attribute to read.
 *   cft::buffer            RAII cft_buffer.
 *   cft::program           RAII cft_program.
 *
 * Batches first, because cft_run IS a batch call and the tile is a
 * streaming engine: every operation takes spans, and the scalar form
 * is the batch of one, spelled as such in the code below. A loop
 * calling the scalar form N times is N round trips and is exactly the
 * shape the device does not want; it is offered for clarity, not for
 * throughput. (Same rule bindings/node states for the same reason.)
 *
 * ---------------------------------------------------------------
 * No decimal I/O, on purpose
 * ---------------------------------------------------------------
 *
 * bindings/python and bindings/node both carry a decimal contract -
 * exact strings out, one library rounding on the way in. This header
 * carries none: values move as bytes, as hex, or through cft_convert
 * to a double, and that is all.
 *
 * Not an oversight. Those two packages needed decimals because they
 * are how a Python or JavaScript user types a number in the first
 * place; C++ code that reaches for a 237-bit significand did not get
 * there from a string literal. And a decimal contract is real work
 * with real ways to be subtly wrong - the exact decimal of the
 * smallest binary256 subnormal runs to roughly 183,000 digits, and
 * parsing needs either a bignum here or the exact-numerator/exact-
 * denominator dance core.mjs does. Either would be new code in the
 * one place this header refuses to have any: the path a value takes
 * to become bits. If it is ever wanted, bindings/node/core.mjs is the
 * design to port, not a strtod to reach for.
 *
 * ---------------------------------------------------------------
 * Errors: an exception at the top, a status at the bottom
 * ---------------------------------------------------------------
 *
 * Both, deliberately, split by layer rather than duplicated per call:
 *
 *   cft::device's compute calls return cft::call_result - the status,
 *   the flag word, and the bus word - and never throw. That layer is
 *   the ABI, and the ABI reports by return value; a caller who wants
 *   the raw bus bits of a CFT_ERR_BUS_FAULT, or who builds with
 *   exceptions off, has a complete surface here.
 *
 *   cft::basic_context's calls throw cft::error, which carries the
 *   cft_status, cft_strerror's text and a COPY of cft_last_error's
 *   detail (a copy because that buffer is static and the next failure
 *   overwrites it). That layer is the ergonomics, and in C++ the
 *   ergonomic answer to "this cannot be expressed" is an exception.
 *
 * Wrapper-side misuse - spans whose lengths disagree, two values from
 * different contexts - throws std::invalid_argument instead, because
 * it is not a status the library ever produced and dressing it up as
 * one would put a lie in cft_strerror's mouth.
 *
 * ---------------------------------------------------------------
 * Why there is no free operator+ on an encoding type
 * ---------------------------------------------------------------
 *
 * Because fp64_enc is eight bytes and nothing else. Adding two of
 * them needs a device to run the addition on and a rounding attribute
 * to run it under, and a free operator+(fp64_enc, fp64_enc) has
 * neither - so it would have to reach for a default: a process-wide
 * device, and CFT_RNE unless someone changed it. Then the attribute
 * lives in a global, one translation unit sets it and another does
 * not, the two disagree about what `x + y` means while reading
 * identically, and the answer depends on link order. That is not a
 * hypothetical C++ hazard; it is the same failure as a compiler flag
 * that changes a result, which is the failure this whole project
 * exists to remove.
 *
 * There is a second, smaller reason: the flags. Every rounding
 * operation produces an exception flag word, and a free operator has
 * nowhere to put one but a global.
 *
 * So operators live on value<F>, which holds the context that answers
 * both questions, and a context is constructed with its attribute
 * written out at the point of construction:
 *
 *     cft::device dev;                          // software backend
 *     cft::context128 ctx(dev, CFT_RUP);        // the attribute, visible
 *     auto x = ctx.from_double(1.0);
 *     auto y = x + x;                           // one cft_run, RUP
 *
 * Values from two different contexts do not mix: x + y where the two
 * disagree about the attribute has no defensible answer, so it is
 * refused rather than resolved by a rule nobody would remember.
 */

#ifndef CFT_HPP
#define CFT_HPP

#include <array>
#include <cstddef>
#include <cstdint>
#include <cstring>
#include <limits>
#include <stdexcept>
#include <string>
#include <type_traits>
#include <utility>

#include "cft.h"

/* std::span if the toolchain has it, a pointer+size view of the same
 * shape if it does not. C++17 is the floor; C++20 features appear only
 * behind this check, and call sites are identical either way. Define
 * CFT_HPP_STD_SPAN yourself to force one or the other. */
#if !defined(CFT_HPP_STD_SPAN)
#  if defined(__has_include)
#    if __has_include(<version>)
#      include <version>
#    endif
#  endif
#  if defined(__cpp_lib_span) && __cpp_lib_span >= 202002L
#    define CFT_HPP_STD_SPAN 1
#  else
#    define CFT_HPP_STD_SPAN 0
#  endif
#endif
#if CFT_HPP_STD_SPAN
#  include <span>
#endif

namespace cft {

/* ---------------------------------------------------------------
 * ABI version
 *
 * cft.h's advice, in code: check the library that actually loaded
 * rather than the header you compiled against, because a binding
 * against a different shared library is the normal case. Major must
 * match; a newer minor is additive and fine.
 * --------------------------------------------------------------- */
inline constexpr std::uint32_t header_abi_version =
    (static_cast<std::uint32_t>(CFT_ABI_VERSION_MAJOR) << 16) |
    static_cast<std::uint32_t>(CFT_ABI_VERSION_MINOR);

inline std::uint32_t runtime_abi_version() noexcept { return cft_abi_version(); }

inline bool abi_compatible() noexcept
{
    const std::uint32_t v = cft_abi_version();
    return (v >> 16) == (header_abi_version >> 16) &&
           (v & 0xffffu) >= (header_abi_version & 0xffffu);
}

/* ---------------------------------------------------------------
 * Errors
 * --------------------------------------------------------------- */

/* A libcft status that a context-layer call could not deliver on.
 * Carries the status itself (so a caller can branch on
 * CFT_ERR_UNSUPPORTED without parsing English), cft_strerror's text,
 * and a copy of cft_last_error's detail taken at throw time - a copy
 * because that storage is static and the next failure overwrites it,
 * which on a bad night at the bench is the only explanation anybody
 * gets. */
class error : public std::runtime_error {
public:
    error(cft_status st, const char *where)
        : std::runtime_error(build(st, where)), status_(st),
          detail_(cft_last_error()) {}

    cft_status status() const noexcept { return status_; }
    const std::string &detail() const noexcept { return detail_; }

private:
    static std::string build(cft_status st, const char *where)
    {
        std::string s = where ? where : "cft";
        s += ": ";
        s += cft_strerror(st);
        const char *d = cft_last_error();
        if (d && *d) {
            s += " - ";
            s += d;
        }
        return s;
    }

    cft_status status_;
    std::string detail_;
};

/* What a device-layer call answers with: everything the C call had to
 * say. bus is meaningful only alongside CFT_ERR_BUS_FAULT, and flags
 * only alongside CFT_OK - on any error the output buffer is
 * unspecified and so is the flag word. */
struct call_result {
    cft_status    status = CFT_OK;
    std::uint32_t flags  = 0;
    std::uint32_t bus    = 0;

    bool ok() const noexcept { return status == CFT_OK; }
    explicit operator bool() const noexcept { return ok(); }

    /* Turn a status into the exception, or do nothing. This is the
     * one bridge between the two error styles, and it is what every
     * context-layer method is built out of. */
    std::uint32_t check(const char *where) const
    {
        if (status != CFT_OK)
            throw error(status, where);
        return flags;
    }
};

inline void check_abi()
{
    if (!abi_compatible())
        throw std::runtime_error(
            "libcft ABI " + std::to_string(cft_abi_version() >> 16) + "." +
            std::to_string(cft_abi_version() & 0xffffu) +
            " cannot serve a caller compiled against " +
            std::to_string(header_abi_version >> 16) + "." +
            std::to_string(header_abi_version & 0xffffu));
}

/* ---------------------------------------------------------------
 * Names
 *
 * The library owns the spellings it has: cft_format_name and
 * cft_op_name are asked rather than mirrored, so a log line here and
 * a conformance report there cannot drift apart. cft.h has no name
 * function for the rounding attributes, so round_name below is this
 * header's own table - presentational only, never used to select
 * anything, and the enumerators it names are cft.h's.
 * --------------------------------------------------------------- */
inline const char *format_name(cft_format f) { return cft_format_name(f); }
inline const char *op_name(cft_op op) { return cft_op_name(op); }
inline std::size_t format_size(cft_format f) { return cft_format_size(f); }

inline const char *round_name(cft_round r)
{
    switch (r) {
    case CFT_RNE: return "rne";
    case CFT_RTZ: return "rtz";
    case CFT_RDN: return "rdn";
    case CFT_RUP: return "rup";
    case CFT_RMM: return "rmm";
    }
    return "reserved";
}

/* The IEEE exception names set in a flag word, joined by '|', or
 * "none". A bit this header cannot name is reported rather than
 * dropped - an unnameable flag is a disagreement with cft.h, and
 * hiding it would be the one wrong response. */
inline std::string flag_names(std::uint32_t flags)
{
    static const struct { std::uint32_t bit; const char *name; } table[] = {
        { CFT_FLAG_INVALID,   "invalid"   },
        { CFT_FLAG_DIVBYZERO, "divbyzero" },
        { CFT_FLAG_OVERFLOW,  "overflow"  },
        { CFT_FLAG_UNDERFLOW, "underflow" },
        { CFT_FLAG_INEXACT,   "inexact"   }
    };
    std::string s;
    std::uint32_t known = 0;
    for (const auto &e : table) {
        known |= e.bit;
        if (flags & e.bit) {
            if (!s.empty())
                s += "|";
            s += e.name;
        }
    }
    const std::uint32_t extra = flags & ~known;
    if (extra) {
        static const char hex[] = "0123456789abcdef";
        std::string digits;
        for (int shift = 28; shift >= 0; shift -= 4) {
            const unsigned nib = (extra >> shift) & 0xfu;
            if (nib || !digits.empty())
                digits += hex[nib];
        }
        if (!s.empty())
            s += "|";
        s += "unknown(0x" + digits + ")";
    }
    return s.empty() ? std::string("none") : s;
}

/* ---------------------------------------------------------------
 * Spans
 * --------------------------------------------------------------- */
#if CFT_HPP_STD_SPAN
template <class T> using span = std::span<T>;
#else
namespace detail {
template <class T> struct is_span_type : std::false_type {};
}

/* The C++17 stand-in: a pointer and a count, constructible from the
 * same things std::span is constructible from, with the members this
 * header actually uses. Not a general-purpose span, and not trying to
 * be one - when the toolchain has the real thing it is used instead
 * and this code is not compiled at all. */
template <class T>
class span {
public:
    using element_type = T;
    using value_type   = std::remove_cv_t<T>;
    using size_type    = std::size_t;
    using iterator     = T *;

    constexpr span() noexcept : p_(nullptr), n_(0) {}
    constexpr span(T *p, size_type n) noexcept : p_(p), n_(n) {}

    template <std::size_t N>
    constexpr span(T (&a)[N]) noexcept : p_(a), n_(N) {}

    /* Any contiguous container whose data() converts to T*. Takes an
     * lvalue reference on purpose: binding to a temporary would hand
     * back a view of something already destroyed. */
    template <class C,
              class = std::enable_if_t<
                  !detail::is_span_type<std::remove_cv_t<C>>::value &&
                  !std::is_array<C>::value &&
                  std::is_convertible<
                      decltype(std::declval<C &>().data()), T *>::value>>
    constexpr span(C &c) : p_(c.data()), n_(c.size()) {}

    /* span<T> -> span<const T>, the qualification conversion only. */
    template <class U,
              class = std::enable_if_t<
                  !std::is_same<U, T>::value &&
                  std::is_convertible<U (*)[], T (*)[]>::value>>
    constexpr span(const span<U> &o) noexcept : p_(o.data()), n_(o.size()) {}

    constexpr T *data() const noexcept { return p_; }
    constexpr size_type size() const noexcept { return n_; }
    constexpr size_type size_bytes() const noexcept { return n_ * sizeof(T); }
    constexpr bool empty() const noexcept { return n_ == 0; }
    constexpr T &operator[](size_type i) const noexcept { return p_[i]; }
    constexpr iterator begin() const noexcept { return p_; }
    constexpr iterator end() const noexcept { return p_ + n_; }

private:
    T *p_;
    size_type n_;
};

namespace detail {
template <class T> struct is_span_type<span<T>> : std::true_type {};
}
#endif

template <class T> using cspan = span<const T>;

/* ---------------------------------------------------------------
 * Formats and encodings
 *
 * An encoding is bytes. Not a double, not a long double, not a
 * __float128: bytes, dense and little-endian, exactly as cft.h
 * describes a buffer element - so a std::vector<encoding<F>> IS the
 * buffer cft_run wants, with no packing step and no reinterpretation
 * beyond taking its address. The static_asserts below are what make
 * that sentence true rather than hoped for.
 *
 * The geometry constants are the interchange formats' own (754-2019
 * table 3.5, and the same numbers host/examples/vector_fma.c builds
 * its operand stream from). They are not taken on trust either:
 * host/tests/cpp_api_test.cpp asks the library to convert the integer
 * 1 in each format and compares it against one() built from these
 * fields, which pins bias, significand width and exponent width in
 * one comparison per format.
 * --------------------------------------------------------------- */
template <cft_format F> struct format_traits;

template <> struct format_traits<CFT_FP32> {
    static constexpr cft_format  format           = CFT_FP32;
    static constexpr std::size_t size             = 4;
    static constexpr int         exponent_bits    = 8;
    static constexpr int         significand_bits = 23;   /* stored */
    static constexpr int         precision        = 24;
    static constexpr std::int64_t bias            = 127;
};
template <> struct format_traits<CFT_FP64> {
    static constexpr cft_format  format           = CFT_FP64;
    static constexpr std::size_t size             = 8;
    static constexpr int         exponent_bits    = 11;
    static constexpr int         significand_bits = 52;
    static constexpr int         precision        = 53;
    static constexpr std::int64_t bias            = 1023;
};
template <> struct format_traits<CFT_FP128> {
    static constexpr cft_format  format           = CFT_FP128;
    static constexpr std::size_t size             = 16;
    static constexpr int         exponent_bits    = 15;
    static constexpr int         significand_bits = 112;
    static constexpr int         precision        = 113;
    static constexpr std::int64_t bias            = 16383;
};
template <> struct format_traits<CFT_FP256> {
    static constexpr cft_format  format           = CFT_FP256;
    static constexpr std::size_t size             = 32;
    static constexpr int         exponent_bits    = 19;
    static constexpr int         significand_bits = 236;
    static constexpr int         precision        = 237;
    static constexpr std::int64_t bias            = 262143;
};

template <cft_format F>
using encoding = std::array<std::uint8_t, format_traits<F>::size>;

using fp32_enc  = encoding<CFT_FP32>;
using fp64_enc  = encoding<CFT_FP64>;
using fp128_enc = encoding<CFT_FP128>;
using fp256_enc = encoding<CFT_FP256>;

/* The two assumptions a dense buffer of these rests on. If either
 * ever failed, every span this header hands to cft_run would be the
 * wrong length in bytes - so they are checked here rather than
 * discovered in a checksum. */
static_assert(sizeof(fp32_enc) == 4 && sizeof(fp64_enc) == 8 &&
              sizeof(fp128_enc) == 16 && sizeof(fp256_enc) == 32,
              "an encoding must be exactly its format's width in bytes");
static_assert(std::is_trivially_copyable<fp256_enc>::value,
              "an encoding must be trivially copyable");

/* The one host-type dependency in the header, isolated here: the fp64
 * doorway of to_double()/from_double() copies a double's bytes, and
 * that is a copy only if the host's double is the same object the
 * library calls binary64. Everything wider goes through cft_convert,
 * which is arithmetic and belongs to the library. */
static_assert(std::numeric_limits<double>::is_iec559 && sizeof(double) == 8,
              "cft.hpp's double doorway needs an IEEE binary64 double");
#if defined(__BYTE_ORDER__) && defined(__ORDER_LITTLE_ENDIAN__)
static_assert(__BYTE_ORDER__ == __ORDER_LITTLE_ENDIAN__,
              "cft.hpp's double doorway needs a little-endian host");
#endif

/* -- encoding helpers: representation, never arithmetic ------------ *
 *
 * Bit surgery that packs and unpacks fields, in the spirit of
 * bindings/python's codec: it either reproduces a bit pattern exactly
 * or it is not offered. Nothing here rounds, so nothing here can
 * round differently from the library.
 */
namespace detail {
template <cft_format F>
constexpr void set_bit(encoding<F> &e, int i)
{
    e[static_cast<std::size_t>(i) / 8] |=
        static_cast<std::uint8_t>(1u << (static_cast<unsigned>(i) % 8u));
}
}  // namespace detail

/* +0 or -0. */
template <cft_format F>
inline encoding<F> zero_enc(int sign = 0)
{
    encoding<F> e{};
    if (sign)
        detail::set_bit<F>(e, static_cast<int>(format_traits<F>::size) * 8 - 1);
    return e;
}

/* +inf or -inf: exponent all ones, significand zero. */
template <cft_format F>
inline encoding<F> inf_enc(int sign = 0)
{
    encoding<F> e{};
    for (int i = 0; i < format_traits<F>::exponent_bits; i++)
        detail::set_bit<F>(e, format_traits<F>::significand_bits + i);
    if (sign)
        detail::set_bit<F>(e, static_cast<int>(format_traits<F>::size) * 8 - 1);
    return e;
}

/* The contract's canonical quiet NaN: sign 0, exponent all ones,
 * quiet bit set, payload zero - the one NaN libcft arithmetic ever
 * produces (docs/DETERMINISM.md). */
template <cft_format F>
inline encoding<F> quiet_nan_enc()
{
    encoding<F> e = inf_enc<F>(0);
    detail::set_bit<F>(e, format_traits<F>::significand_bits - 1);
    return e;
}

/* A signaling NaN: exponent all ones, quiet bit CLEAR, payload
 * non-zero. Useful mostly for checking that invalid is raised. */
template <cft_format F>
inline encoding<F> signaling_nan_enc()
{
    encoding<F> e = inf_enc<F>(0);
    detail::set_bit<F>(e, 0);
    return e;
}

/* 1.0: biased exponent of zero, significand zero. */
template <cft_format F>
inline encoding<F> one_enc()
{
    encoding<F> e{};
    for (int i = 0; i < format_traits<F>::exponent_bits; i++)
        if ((format_traits<F>::bias >> i) & 1)
            detail::set_bit<F>(e, format_traits<F>::significand_bits + i);
    return e;
}

/* The smallest positive subnormal: the low bit of the encoding. */
template <cft_format F>
inline encoding<F> min_subnormal_enc()
{
    encoding<F> e{};
    detail::set_bit<F>(e, 0);
    return e;
}

/* Big-endian hex, the way an encoding is written down in a vector set
 * and in every error message in this project. Formatting, not
 * conversion: there is no decimal here and no rounding to disagree
 * about. */
template <cft_format F>
inline std::string to_hex(const encoding<F> &e)
{
    static const char d[] = "0123456789abcdef";
    std::string s(format_traits<F>::size * 2, '0');
    for (std::size_t i = 0; i < format_traits<F>::size; i++) {
        const std::uint8_t byte = e[format_traits<F>::size - 1 - i];
        s[2 * i]     = d[byte >> 4];
        s[2 * i + 1] = d[byte & 0xf];
    }
    return s;
}

/* The inverse. Refuses anything that is not exactly the format's
 * width in hex digits, because a short string is a caller who meant a
 * different format. */
template <cft_format F>
inline encoding<F> from_hex(const std::string &s)
{
    if (s.size() != format_traits<F>::size * 2)
        throw std::invalid_argument(
            std::string("from_hex: ") + cft_format_name(F) + " wants " +
            std::to_string(format_traits<F>::size * 2) + " hex digits, got " +
            std::to_string(s.size()));
    encoding<F> e{};
    for (std::size_t i = 0; i < format_traits<F>::size; i++) {
        unsigned v = 0;
        for (int half = 0; half < 2; half++) {
            const char c = s[2 * i + static_cast<std::size_t>(half)];
            unsigned nib;
            if (c >= '0' && c <= '9')      nib = static_cast<unsigned>(c - '0');
            else if (c >= 'a' && c <= 'f') nib = static_cast<unsigned>(c - 'a') + 10u;
            else if (c >= 'A' && c <= 'F') nib = static_cast<unsigned>(c - 'A') + 10u;
            else throw std::invalid_argument("from_hex: not a hex digit");
            v = (v << 4) | nib;
        }
        e[format_traits<F>::size - 1 - i] = static_cast<std::uint8_t>(v);
    }
    return e;
}

/* The encoding as an unsigned integer, for the two formats that fit
 * one. Deliberately not offered at fp128/fp256: a 128-bit integer is
 * not portable C++17 and a truncating one would be a trap. Use
 * to_hex, or the bytes. */
inline std::uint32_t to_bits(const fp32_enc &e)
{
    std::uint32_t v = 0;
    std::memcpy(&v, e.data(), sizeof v);
    return v;
}
inline std::uint64_t to_bits(const fp64_enc &e)
{
    std::uint64_t v = 0;
    std::memcpy(&v, e.data(), sizeof v);
    return v;
}
inline fp32_enc from_bits32(std::uint32_t v)
{
    fp32_enc e{};
    std::memcpy(e.data(), &v, sizeof v);
    return e;
}
inline fp64_enc from_bits64(std::uint64_t v)
{
    fp64_enc e{};
    std::memcpy(e.data(), &v, sizeof v);
    return e;
}

/* ---------------------------------------------------------------
 * Capabilities
 * --------------------------------------------------------------- */
struct capabilities {
    std::uint32_t format_mask    = 0;
    std::uint32_t tiles          = 0;
    std::uint32_t abi_version    = 0;
    std::uint32_t device_version = 0;
    bool          flags_readable = false;
    std::string   backend;

    bool has_format(cft_format f) const noexcept
    {
        return (format_mask & (1u << static_cast<unsigned>(f))) != 0;
    }
};

/* ---------------------------------------------------------------
 * buffer - RAII over cft_alloc / cft_buffer_free
 * --------------------------------------------------------------- */
class device;

class buffer {
public:
    buffer() noexcept = default;
    buffer(const buffer &) = delete;
    buffer &operator=(const buffer &) = delete;

    buffer(buffer &&o) noexcept : buf_(o.buf_), bytes_(o.bytes_)
    {
        o.buf_ = nullptr;
        o.bytes_ = 0;
    }
    buffer &operator=(buffer &&o) noexcept
    {
        if (this != &o) {
            reset();
            buf_ = o.buf_;
            bytes_ = o.bytes_;
            o.buf_ = nullptr;
            o.bytes_ = 0;
        }
        return *this;
    }
    ~buffer() { reset(); }

    void reset() noexcept
    {
        cft_buffer_free(buf_);   /* NULL is documented safe */
        buf_ = nullptr;
        bytes_ = 0;
    }

    explicit operator bool() const noexcept { return buf_ != nullptr; }
    cft_buffer *get() const noexcept { return buf_; }
    std::size_t size() const noexcept { return bytes_; }

    /* The host-visible pointer. On the software backend it is ordinary
     * memory and the sync calls below are no-ops, which is the property
     * that keeps code written this way portable to the device. */
    void *data() const noexcept { return buf_ ? cft_buffer_data(buf_) : nullptr; }

    cft_status to_device() noexcept
    {
        return buf_ ? cft_buffer_to_device(buf_) : CFT_ERR_INVALID_ARGUMENT;
    }
    cft_status from_device() noexcept
    {
        return buf_ ? cft_buffer_from_device(buf_) : CFT_ERR_INVALID_ARGUMENT;
    }

private:
    friend class device;
    buffer(cft_buffer *b, std::size_t bytes) noexcept : buf_(b), bytes_(bytes) {}

    cft_buffer *buf_ = nullptr;
    std::size_t bytes_ = 0;
};

/* ---------------------------------------------------------------
 * program - RAII over cft_program_load / cft_program_free
 *
 * A program image is a flat byte blob (docs/SEQUENCER.md), so this
 * type takes bytes and adds a destructor and an info() that does not
 * make the caller zero a struct_size by hand. It stays on the raw
 * layer - void pointers and a call_result - because a program's
 * format is a field of the image rather than a template argument.
 * --------------------------------------------------------------- */
class program {
public:
    program() noexcept = default;
    program(const program &) = delete;
    program &operator=(const program &) = delete;

    program(program &&o) noexcept : prog_(o.prog_) { o.prog_ = nullptr; }
    program &operator=(program &&o) noexcept
    {
        if (this != &o) {
            reset();
            prog_ = o.prog_;
            o.prog_ = nullptr;
        }
        return *this;
    }
    ~program() { reset(); }

    void reset() noexcept
    {
        cft_program_free(prog_);
        prog_ = nullptr;
    }

    explicit operator bool() const noexcept { return prog_ != nullptr; }
    cft_program *get() const noexcept { return prog_; }

    cft_status info(cft_program_info &out) const noexcept
    {
        if (!prog_)
            return CFT_ERR_INVALID_ARGUMENT;
        std::memset(&out, 0, sizeof out);
        out.struct_size = sizeof out;
        return cft_program_get_info(prog_, &out);
    }

    /* deposits holds n * max_deposits elements and counts holds n, or
     * counts may be null - cft.h's contract, unchanged. */
    call_result run(const void *a, const void *b, const void *c,
                    void *deposits, std::uint32_t *counts,
                    std::size_t n) noexcept
    {
        call_result r;
        if (!prog_) {
            r.status = CFT_ERR_INVALID_ARGUMENT;
            return r;
        }
        r.status = cft_program_run(prog_, a, b, c, deposits, counts, n,
                                   &r.flags, &r.bus);
        return r;
    }

private:
    friend class device;
    explicit program(cft_program *p) noexcept : prog_(p) {}

    cft_program *prog_ = nullptr;
};

/* ---------------------------------------------------------------
 * device - RAII over cft_open / cft_close, and the ABI one to one
 *
 * Non-copyable and movable, because a cft_device is a handle to one
 * thing and copying it would mean two closes. Not thread-safe, for
 * the reason cft.h gives: neither is the handle inside. Open one per
 * thread; opening several handles to the same physical device is
 * allowed and cheap.
 *
 * The methods below are the C calls with the same arguments in the
 * same order, minus the out-parameters, which come back in the
 * call_result. No format typing, no spans: this layer exists so that
 * code doing runtime format dispatch (a conformance runner, a
 * benchmark) does not have to pay for templates it cannot use, and so
 * the typed layer above has exactly one place to funnel through.
 * --------------------------------------------------------------- */
class device {
public:
    /* An unopened handle. Every call on it answers
     * CFT_ERR_INVALID_ARGUMENT rather than dereferencing null. */
    device() noexcept = default;

    /* Open, or throw. artifact == nullptr is the software backend:
     * no card, no driver, no Linux, same bits. */
    explicit device(const char *artifact, int index = 0)
    {
        const cft_status st = cft_open(artifact, index, &dev_);
        if (st != CFT_OK) {
            dev_ = nullptr;
            throw error(st, "cft_open");
        }
    }

    device(const device &) = delete;
    device &operator=(const device &) = delete;

    device(device &&o) noexcept : dev_(o.dev_) { o.dev_ = nullptr; }
    device &operator=(device &&o) noexcept
    {
        if (this != &o) {
            close();
            dev_ = o.dev_;
            o.dev_ = nullptr;
        }
        return *this;
    }
    ~device() { close(); }

    /* The non-throwing open, for a caller who treats "no device" as a
     * branch rather than an exception - which it usually is, since
     * CFT_ERR_NO_DEVICE is how a build without XRT answers an xclbin
     * path. Closes any handle already held. */
    cft_status try_open(const char *artifact = nullptr, int index = 0) noexcept
    {
        close();
        const cft_status st = cft_open(artifact, index, &dev_);
        if (st != CFT_OK)
            dev_ = nullptr;
        return st;
    }

    void close() noexcept
    {
        cft_close(dev_);            /* NULL is documented safe */
        dev_ = nullptr;
    }

    explicit operator bool() const noexcept { return dev_ != nullptr; }
    cft_device *get() const noexcept { return dev_; }

    /* -- queries -------------------------------------------------- */

    /* Throws: a device you cannot ask what it is is not a device you
     * can use. The struct_size handshake cft.h documents is done here
     * so that no caller has to remember it. */
    capabilities caps()
    {
        cft_caps c;
        std::memset(&c, 0, sizeof c);
        c.struct_size = sizeof c;
        const cft_status st = cft_get_caps(dev_, &c);
        if (st != CFT_OK)
            throw error(st, "cft_get_caps");
        capabilities out;
        out.format_mask    = c.format_mask;
        out.tiles          = c.tiles;
        out.abi_version    = c.abi_version;
        out.device_version = c.device_version;
        out.flags_readable = c.flags_readable != 0;
        /* backend[] is a fixed-width array; take it up to the NUL, or
         * up to the array's end if a future runtime fills it. */
        const void *nul = std::memchr(c.backend, '\0', sizeof c.backend);
        out.backend.assign(c.backend,
                           nul ? static_cast<std::size_t>(
                                     static_cast<const char *>(nul) - c.backend)
                               : sizeof c.backend);
        return out;
    }

    bool supports(cft_op op, cft_format fmt) noexcept
    {
        return cft_supports(dev_, op, fmt) != 0;
    }

    /* -- the core calls ------------------------------------------- */
    call_result run(cft_op op, cft_format fmt, cft_round rnd,
                    const void *a, const void *b, const void *c, void *d,
                    std::size_t n) noexcept
    {
        call_result r;
        r.status = cft_run(dev_, op, fmt, rnd, a, b, c, d, n, &r.flags, &r.bus);
        return r;
    }

    call_result reduce(cft_op op, cft_format fmt, cft_round rnd,
                       const void *a, const void *b, void *d,
                       std::size_t n) noexcept
    {
        call_result r;
        r.status = cft_reduce(dev_, op, fmt, rnd, a, b, d, n, &r.flags, &r.bus);
        return r;
    }

    call_result div(cft_format fmt, cft_round rnd, const void *a,
                    const void *b, void *d, std::size_t n) noexcept
    {
        call_result r;
        r.status = cft_div(dev_, fmt, rnd, a, b, d, n, &r.flags, &r.bus);
        return r;
    }

    call_result sqrt(cft_format fmt, cft_round rnd, const void *a, void *d,
                     std::size_t n) noexcept
    {
        call_result r;
        r.status = cft_sqrt(dev_, fmt, rnd, a, d, n, &r.flags, &r.bus);
        return r;
    }

    /* -- the clause-5 completion set ------------------------------ */
    call_result rint(cft_format fmt, cft_round rnd, bool exact,
                     const void *a, void *d, std::size_t n) noexcept
    {
        call_result r;
        r.status = cft_rint(dev_, fmt, rnd, exact ? 1 : 0, a, d, n,
                            &r.flags, &r.bus);
        return r;
    }

    call_result scaleb(cft_format fmt, cft_round rnd, const void *a,
                       std::int64_t nexp, void *d, std::size_t n) noexcept
    {
        call_result r;
        r.status = cft_scaleb(dev_, fmt, rnd, a, nexp, d, n, &r.flags, &r.bus);
        return r;
    }

    call_result cmp_sig(cft_op cmp, cft_format fmt, const void *a,
                        const void *b, void *d, std::size_t n) noexcept
    {
        call_result r;
        r.status = cft_cmp_sig(dev_, cmp, fmt, a, b, d, n, &r.flags, &r.bus);
        return r;
    }

    call_result convert(cft_format sfmt, cft_format dfmt, cft_round rnd,
                        const void *a, void *d, std::size_t n) noexcept
    {
        call_result r;
        r.status = cft_convert(dev_, sfmt, dfmt, rnd, a, d, n, &r.flags);
        return r;
    }

    call_result cvt_from(cft_format fmt, cft_round rnd, const std::int32_t *src,
                         void *d, std::size_t n) noexcept
    {
        call_result r;
        r.status = cft_cvt_from_i32(dev_, fmt, rnd, src, d, n, &r.flags);
        return r;
    }
    call_result cvt_from(cft_format fmt, cft_round rnd,
                         const std::uint32_t *src, void *d,
                         std::size_t n) noexcept
    {
        call_result r;
        r.status = cft_cvt_from_u32(dev_, fmt, rnd, src, d, n, &r.flags);
        return r;
    }
    call_result cvt_from(cft_format fmt, cft_round rnd, const std::int64_t *src,
                         void *d, std::size_t n) noexcept
    {
        call_result r;
        r.status = cft_cvt_from_i64(dev_, fmt, rnd, src, d, n, &r.flags);
        return r;
    }
    call_result cvt_from(cft_format fmt, cft_round rnd,
                         const std::uint64_t *src, void *d,
                         std::size_t n) noexcept
    {
        call_result r;
        r.status = cft_cvt_from_u64(dev_, fmt, rnd, src, d, n, &r.flags);
        return r;
    }

    call_result cvt_to(cft_format fmt, cft_round rnd, bool exact,
                       const void *a, std::int32_t *dst,
                       std::size_t n) noexcept
    {
        call_result r;
        r.status = cft_cvt_to_i32(dev_, fmt, rnd, exact ? 1 : 0, a, dst, n,
                                  &r.flags);
        return r;
    }
    call_result cvt_to(cft_format fmt, cft_round rnd, bool exact,
                       const void *a, std::uint32_t *dst,
                       std::size_t n) noexcept
    {
        call_result r;
        r.status = cft_cvt_to_u32(dev_, fmt, rnd, exact ? 1 : 0, a, dst, n,
                                  &r.flags);
        return r;
    }
    call_result cvt_to(cft_format fmt, cft_round rnd, bool exact,
                       const void *a, std::int64_t *dst,
                       std::size_t n) noexcept
    {
        call_result r;
        r.status = cft_cvt_to_i64(dev_, fmt, rnd, exact ? 1 : 0, a, dst, n,
                                  &r.flags);
        return r;
    }
    call_result cvt_to(cft_format fmt, cft_round rnd, bool exact,
                       const void *a, std::uint64_t *dst,
                       std::size_t n) noexcept
    {
        call_result r;
        r.status = cft_cvt_to_u64(dev_, fmt, rnd, exact ? 1 : 0, a, dst, n,
                                  &r.flags);
        return r;
    }

    call_result logb(cft_format fmt, const void *a, void *d,
                     std::size_t n) noexcept
    {
        call_result r;
        r.status = cft_logb(dev_, fmt, a, d, n, &r.flags);
        return r;
    }

    call_result next_up(cft_format fmt, const void *a, void *d,
                        std::size_t n) noexcept
    {
        call_result r;
        r.status = cft_next_up(dev_, fmt, a, d, n, &r.flags);
        return r;
    }
    call_result next_down(cft_format fmt, const void *a, void *d,
                          std::size_t n) noexcept
    {
        call_result r;
        r.status = cft_next_down(dev_, fmt, a, d, n, &r.flags);
        return r;
    }

    /* 5.7.2 class, one byte per element. Named classify because
     * `class` is a keyword; the values are cft_class_value. Signals
     * nothing, so there is no flag word to report. */
    cft_status classify(cft_format fmt, const void *a, std::uint8_t *cls,
                        std::size_t n) noexcept
    {
        return cft_class(dev_, fmt, a, cls, n);
    }

    cft_status total_order(cft_format fmt, const void *a, const void *b,
                           void *d, std::size_t n) noexcept
    {
        return cft_total_order(dev_, fmt, a, b, d, n);
    }
    cft_status total_order_mag(cft_format fmt, const void *a, const void *b,
                               void *d, std::size_t n) noexcept
    {
        return cft_total_order_mag(dev_, fmt, a, b, d, n);
    }

    call_result rem(cft_format fmt, const void *a, const void *b, void *d,
                    std::size_t n) noexcept
    {
        call_result r;
        r.status = cft_rem(dev_, fmt, a, b, d, n, &r.flags);
        return r;
    }

    /* ---------------------------------------------------------------
     * The phase-1 transcendentals (ABI 0.3)
     *
     * Correctly rounded in the caller's attribute, with the clause
     * 9.2.1 special values and exact flags - see cft.h. Host
     * operations, so there is no bus word and nothing to ask
     * cft_supports() about.
     * --------------------------------------------------------------- */
    call_result exp(cft_format fmt, cft_round rnd, const void *a, void *d,
                    std::size_t n) noexcept
    {
        call_result r;
        r.status = cft_exp(dev_, fmt, rnd, a, d, n, &r.flags);
        return r;
    }
    call_result expm1(cft_format fmt, cft_round rnd, const void *a, void *d,
                      std::size_t n) noexcept
    {
        call_result r;
        r.status = cft_expm1(dev_, fmt, rnd, a, d, n, &r.flags);
        return r;
    }
    call_result exp2(cft_format fmt, cft_round rnd, const void *a, void *d,
                     std::size_t n) noexcept
    {
        call_result r;
        r.status = cft_exp2(dev_, fmt, rnd, a, d, n, &r.flags);
        return r;
    }
    call_result log(cft_format fmt, cft_round rnd, const void *a, void *d,
                    std::size_t n) noexcept
    {
        call_result r;
        r.status = cft_log(dev_, fmt, rnd, a, d, n, &r.flags);
        return r;
    }
    call_result log1p(cft_format fmt, cft_round rnd, const void *a, void *d,
                      std::size_t n) noexcept
    {
        call_result r;
        r.status = cft_log1p(dev_, fmt, rnd, a, d, n, &r.flags);
        return r;
    }
    call_result log2(cft_format fmt, cft_round rnd, const void *a, void *d,
                     std::size_t n) noexcept
    {
        call_result r;
        r.status = cft_log2(dev_, fmt, rnd, a, d, n, &r.flags);
        return r;
    }
    call_result log10(cft_format fmt, cft_round rnd, const void *a, void *d,
                      std::size_t n) noexcept
    {
        call_result r;
        r.status = cft_log10(dev_, fmt, rnd, a, d, n, &r.flags);
        return r;
    }
    call_result pow(cft_format fmt, cft_round rnd, const void *a,
                    const void *b, void *d, std::size_t n) noexcept
    {
        call_result r;
        r.status = cft_pow(dev_, fmt, rnd, a, b, d, n, &r.flags);
        return r;
    }
    call_result hypot(cft_format fmt, cft_round rnd, const void *a,
                      const void *b, void *d, std::size_t n) noexcept
    {
        call_result r;
        r.status = cft_hypot(dev_, fmt, rnd, a, b, d, n, &r.flags);
        return r;
    }

    /* ---------------------------------------------------------------
     * The phase-2 trigonometrics (ABI 0.4)
     *
     * The eleven whose argument reduction is exact. Same shape, same
     * promise: correctly rounded in the caller's attribute with the
     * clause 9.2.1 special values - see cft.h. atan2 takes y first,
     * as C does.
     * --------------------------------------------------------------- */
#define CFT_HPP_TRIG1(name)                                             \
    call_result name(cft_format fmt, cft_round rnd, const void *a,      \
                     void *d, std::size_t n) noexcept                   \
    {                                                                   \
        call_result r;                                                  \
        r.status = cft_##name(dev_, fmt, rnd, a, d, n, &r.flags);       \
        return r;                                                       \
    }
    CFT_HPP_TRIG1(sinpi)
    CFT_HPP_TRIG1(cospi)
    CFT_HPP_TRIG1(tanpi)
    CFT_HPP_TRIG1(asin)
    CFT_HPP_TRIG1(acos)
    CFT_HPP_TRIG1(atan)
    CFT_HPP_TRIG1(asinpi)
    CFT_HPP_TRIG1(acospi)
    CFT_HPP_TRIG1(atanpi)
    /* The phase-3 radian trigonometry and the hyperbolics (ABI 0.5).
     * sin, cos and tan take RADIANS and are reduced against pi inside
     * the library at any magnitude the format holds; the six
     * hyperbolics need no reduction at all. Same shape, same promise,
     * and cft.h has every special row. */
    CFT_HPP_TRIG1(sin)
    CFT_HPP_TRIG1(cos)
    CFT_HPP_TRIG1(tan)
    CFT_HPP_TRIG1(sinh)
    CFT_HPP_TRIG1(cosh)
    CFT_HPP_TRIG1(tanh)
    CFT_HPP_TRIG1(asinh)
    CFT_HPP_TRIG1(acosh)
    CFT_HPP_TRIG1(atanh)
#undef CFT_HPP_TRIG1
    call_result atan2(cft_format fmt, cft_round rnd, const void *a,
                      const void *b, void *d, std::size_t n) noexcept
    {
        call_result r;
        r.status = cft_atan2(dev_, fmt, rnd, a, b, d, n, &r.flags);
        return r;
    }
    call_result atan2pi(cft_format fmt, cft_round rnd, const void *a,
                        const void *b, void *d, std::size_t n) noexcept
    {
        call_result r;
        r.status = cft_atan2pi(dev_, fmt, rnd, a, b, d, n, &r.flags);
        return r;
    }

    /* ---------------------------------------------------------------
     * The augmented arithmetic operations (754-2019 clause 9.5)
     *
     * The only entry points here that return TWO results - the
     * operation rounded, and the error rounding made - and the only
     * ones that take no cft_round, because 9.5 fixes the rounding to
     * roundTiesTowardZero and gives the operations no attribute
     * argument to carry it. There is nothing to pass and so no
     * parameter to pass it in; cft.h has the tie rule, the zero-sign
     * rules and the flag policy.
     *
     * `out_r` and `out_e` must be different buffers. Either may alias
     * `a` or `b`.
     * --------------------------------------------------------------- */
#define CFT_HPP_AUG(name)                                               \
    call_result augmented_##name(cft_format fmt, const void *a,         \
                                 const void *b, void *out_r,            \
                                 void *out_e, std::size_t n) noexcept   \
    {                                                                   \
        call_result r;                                                  \
        r.status = cft_augmented_##name(dev_, fmt, a, b, out_r, out_e,  \
                                        n, &r.flags);                   \
        return r;                                                       \
    }
    CFT_HPP_AUG(add)
    CFT_HPP_AUG(sub)
    CFT_HPP_AUG(mul)
#undef CFT_HPP_AUG


    /* -- device-resident buffers ---------------------------------- */
    buffer alloc(std::size_t bytes)
    {
        cft_buffer *b = nullptr;
        const cft_status st = cft_alloc(dev_, bytes, &b);
        if (st != CFT_OK)
            throw error(st, "cft_alloc");
        return buffer(b, bytes);
    }

    /* -- programs ------------------------------------------------- */
    program load_program(const void *image, std::size_t bytes)
    {
        cft_program *p = nullptr;
        const cft_status st = cft_program_load(dev_, image, bytes, &p);
        if (st != CFT_OK)
            throw error(st, "cft_program_load");
        return program(p);
    }

    /* -- conformance ---------------------------------------------- */

    /* Replay the published vector sets and report. The summary is not
     * optional in cft.h and it is not optional here: report is filled
     * on success too, naming the sets that ran and the ones skipped,
     * because a conformance pass that quietly checked nothing would be
     * worse than a failing one. */
    struct conformance_result {
        cft_status    status = CFT_OK;
        std::uint64_t cases  = 0;
        std::string   report;

        bool ok() const noexcept { return status == CFT_OK; }
        explicit operator bool() const noexcept { return ok(); }
    };

    conformance_result conformance(const char *dir = nullptr,
                                   std::size_t report_bytes = 8192)
    {
        conformance_result out;
        std::string buf(report_bytes ? report_bytes : 1, '\0');
        out.status = cft_conformance(dev_, dir, buf.data(), buf.size(),
                                     &out.cases);
        buf.resize(std::char_traits<char>::length(buf.c_str()));
        out.report = buf;
        return out;
    }

private:
    cft_device *dev_ = nullptr;
};

/* ---------------------------------------------------------------
 * value<F> - one encoding, bound to the context that can compute on it
 * --------------------------------------------------------------- */
template <cft_format F> class basic_context;

template <cft_format F>
class value {
public:
    using encoding_type = encoding<F>;
    static constexpr cft_format format = F;

    value() noexcept = default;   /* +0 with no context; not computable */

    basic_context<F> *context() const noexcept { return ctx_; }
    const encoding_type &bytes() const noexcept { return enc_; }
    std::string hex() const { return to_hex<F>(enc_); }

    /* Encoding identity - the comparison the tests and the parity
     * claims are actually about, and NOT what operator== does:
     * operator== is 754 equality, which calls -0 equal to +0 and NaN
     * equal to nothing. */
    bool same_bits(const value &o) const noexcept { return enc_ == o.enc_; }

    /* Arithmetic. Each of these is exactly one libcft call, under the
     * attribute the context was built with, with the flags landing in
     * that context. */
    value operator+(const value &o) const;
    value operator-(const value &o) const;
    value operator*(const value &o) const;
    value operator/(const value &o) const;
    value operator-() const;                       /* 5.5.1 negate */

    /* The quiet 754 predicates (5.11), through the device. Unordered
     * is false, +0 == -0, and a > b is cmplt with the operands
     * swapped exactly as cft.h says. */
    bool operator==(const value &o) const;
    bool operator!=(const value &o) const;
    bool operator<(const value &o) const;
    bool operator<=(const value &o) const;
    bool operator>(const value &o) const;
    bool operator>=(const value &o) const;

private:
    friend class basic_context<F>;
    value(basic_context<F> *ctx, const encoding_type &e) noexcept
        : ctx_(ctx), enc_(e) {}

    basic_context<F> *require_same(const value &o, const char *what) const;

    basic_context<F> *ctx_ = nullptr;
    encoding_type enc_{};
};

using fp32_value  = value<CFT_FP32>;
using fp64_value  = value<CFT_FP64>;
using fp128_value = value<CFT_FP128>;
using fp256_value = value<CFT_FP256>;

/* ---------------------------------------------------------------
 * basic_context<F> - a format, an attribute, and a device
 *
 * The batch surface. Every method takes spans of encodings and hands
 * the library one call for the whole array, because that is the call
 * cft_run is and the shape the tile wants: one dense buffer per
 * operand, one flag word out. The scalar overloads underneath are
 * each a batch of one and say so.
 *
 * An operand the opcode does not read may be passed as an empty span
 * and reaches the library as NULL (cft.h: "Unused operands (b for
 * ADD, c for MUL) may be NULL"). Any operand that IS passed must have
 * the same length as the output, and a length that disagrees is
 * std::invalid_argument rather than a shorter loop.
 *
 * Flags accumulate the way MPFR's do and the way bindings/python and
 * bindings/node already do: last_flags() is the most recent call's
 * word, flags() is the OR of every call this context has made, and
 * clear_flags() resets the sticky one. Both are this context's own -
 * copying a context gives the copy its own flag state.
 *
 * NOT thread-safe, because the device underneath is not.
 * --------------------------------------------------------------- */
template <cft_format F>
class basic_context {
public:
    using traits        = format_traits<F>;
    using encoding_type = encoding<F>;
    using value_type    = value<F>;
    static constexpr cft_format format = F;
    static constexpr std::size_t element_size = traits::size;

    basic_context(device &dev, cft_round rnd = CFT_RNE) noexcept
        : dev_(&dev), rnd_(rnd) {}

    device &get_device() const noexcept { return *dev_; }
    cft_round rounding() const noexcept { return rnd_; }
    const char *rounding_name() const noexcept { return round_name(rnd_); }
    const char *format_name() const noexcept { return cft_format_name(F); }

    /* The same context under a different attribute. Written out at the
     * call site, which is the whole point: an attribute that changes
     * has to be visible where it changes. */
    basic_context with_rounding(cft_round rnd) const noexcept
    {
        return basic_context(*dev_, rnd);
    }

    /* -- flags ---------------------------------------------------- */
    std::uint32_t flags() const noexcept { return sticky_; }
    std::uint32_t last_flags() const noexcept { return last_; }
    void clear_flags() noexcept { sticky_ = 0; }
    std::string flag_names() const { return cft::flag_names(sticky_); }

    /* -- making values -------------------------------------------- */
    /* Every member below that hands back a value_type is lvalue-ref-
     * qualified - the trailing `&` on its signature. A value carries a
     * pointer to the context that made it, and with_rounding() returns
     * a context BY VALUE, so
     *
     *     auto y = ctx.with_rounding(CFT_RUP).one();   // does not compile
     *
     * would otherwise hand back a value whose context is gone at the
     * semicolon and whose first operator use is undefined behaviour.
     * Name the context first and it is fine:
     *
     *     auto up = ctx.with_rounding(CFT_RUP);
     *     auto y  = up.one();
     *
     * The batch members return a flag word and bind nothing, so they
     * are not qualified: ctx.with_rounding(CFT_RUP).fma(a, b, c, d) is
     * a legitimate one-liner. */
    value_type make(const encoding_type &e) & noexcept { return value_type(this, e); }
    value_type zero(int sign = 0) & noexcept { return make(zero_enc<F>(sign)); }
    value_type inf(int sign = 0) & noexcept { return make(inf_enc<F>(sign)); }
    value_type quiet_nan() & noexcept { return make(quiet_nan_enc<F>()); }
    value_type signaling_nan() & noexcept { return make(signaling_nan_enc<F>()); }
    value_type one() & noexcept { return make(one_enc<F>()); }
    value_type from_hex(const std::string &s) & { return make(cft::from_hex<F>(s)); }

    /* -- supports ------------------------------------------------- */
    bool supports(cft_op op) const noexcept { return dev_->supports(op, F); }

    /* ===========================================================
     * Batch: elementwise
     * =========================================================== */

    /* The general form. op's operand slots are cft.h's, so this is the
     * escape hatch for an opcode the named helpers below do not cover
     * - including the unassigned ones, which are not an error and
     * return the canonical quiet NaN with invalid raised. */
    std::uint32_t map(cft_op op, cspan<encoding_type> a,
                      cspan<encoding_type> b, cspan<encoding_type> c,
                      span<encoding_type> d)
    {
        check_operand(a, d, "a");
        check_operand(b, d, "b");
        check_operand(c, d, "c");
        return record(dev_->run(op, F, rnd_, ptr(a), ptr(b), ptr(c), ptr(d),
                                d.size()),
                      "cft_run");
    }

    /* d = a*b + c, one rounding, exact product. */
    std::uint32_t fma(cspan<encoding_type> a, cspan<encoding_type> b,
                      cspan<encoding_type> c, span<encoding_type> d)
    {
        return map(CFT_FMA, a, b, c, d);
    }

    /* The named binaries put each operand in the slot cft.h reads it
     * from, which is the one piece of ceremony a wrapper genuinely
     * removes: ADD and SUB read a and c, MUL reads a and b, and a
     * caller who guesses wrong gets a plausible wrong answer. */
    std::uint32_t add(cspan<encoding_type> x, cspan<encoding_type> y,
                      span<encoding_type> d)
    {
        return map(CFT_ADD, x, cspan<encoding_type>(), y, d);
    }
    std::uint32_t sub(cspan<encoding_type> x, cspan<encoding_type> y,
                      span<encoding_type> d)
    {
        return map(CFT_SUB, x, cspan<encoding_type>(), y, d);
    }
    std::uint32_t mul(cspan<encoding_type> x, cspan<encoding_type> y,
                      span<encoding_type> d)
    {
        return map(CFT_MUL, x, y, cspan<encoding_type>(), d);
    }

    /* Sign operations (5.5.1): quiet, always - they signal nothing at
     * all, not even for a signaling NaN, and preserve payloads. */
    std::uint32_t abs(cspan<encoding_type> x, span<encoding_type> d)
    {
        return map(CFT_ABS, x, cspan<encoding_type>(), cspan<encoding_type>(), d);
    }
    std::uint32_t neg(cspan<encoding_type> x, span<encoding_type> d)
    {
        return map(CFT_NEG, x, cspan<encoding_type>(), cspan<encoding_type>(), d);
    }
    std::uint32_t copysign(cspan<encoding_type> x, cspan<encoding_type> y,
                           span<encoding_type> d)
    {
        return map(CFT_COPYSIGN, x, y, cspan<encoding_type>(), d);
    }

    std::uint32_t min(cspan<encoding_type> x, cspan<encoding_type> y,
                      span<encoding_type> d)
    { return map(CFT_MIN, x, y, cspan<encoding_type>(), d); }
    std::uint32_t max(cspan<encoding_type> x, cspan<encoding_type> y,
                      span<encoding_type> d)
    { return map(CFT_MAX, x, y, cspan<encoding_type>(), d); }
    std::uint32_t minnum(cspan<encoding_type> x, cspan<encoding_type> y,
                         span<encoding_type> d)
    { return map(CFT_MINNUM, x, y, cspan<encoding_type>(), d); }
    std::uint32_t maxnum(cspan<encoding_type> x, cspan<encoding_type> y,
                         span<encoding_type> d)
    { return map(CFT_MAXNUM, x, y, cspan<encoding_type>(), d); }

    /* d = (c != 0) ? a : b, moving NaNs intact - the branchless
     * conditional the predicates below are built to feed. */
    std::uint32_t select(cspan<encoding_type> a, cspan<encoding_type> b,
                         cspan<encoding_type> c, span<encoding_type> d)
    { return map(CFT_SELECT, a, b, c, d); }

    /* The quiet predicates, yielding 1.0 or +0.0 rather than a
     * boolean so CFT_SELECT consumes them directly. */
    std::uint32_t cmplt(cspan<encoding_type> x, cspan<encoding_type> y,
                        span<encoding_type> d)
    { return map(CFT_CMPLT, x, y, cspan<encoding_type>(), d); }
    std::uint32_t cmple(cspan<encoding_type> x, cspan<encoding_type> y,
                        span<encoding_type> d)
    { return map(CFT_CMPLE, x, y, cspan<encoding_type>(), d); }
    std::uint32_t cmpeq(cspan<encoding_type> x, cspan<encoding_type> y,
                        span<encoding_type> d)
    { return map(CFT_CMPEQ, x, y, cspan<encoding_type>(), d); }

    /* The integer group: the encoding as an unsigned integer of the
     * format's width. No rounding, no signalling, no NaN handling -
     * the bits are just bits, and the attribute is not consulted. */
    std::uint32_t iand(cspan<encoding_type> x, cspan<encoding_type> y,
                       span<encoding_type> d)
    { return map(CFT_IAND, x, y, cspan<encoding_type>(), d); }
    std::uint32_t ior(cspan<encoding_type> x, cspan<encoding_type> y,
                      span<encoding_type> d)
    { return map(CFT_IOR, x, y, cspan<encoding_type>(), d); }
    std::uint32_t ixor(cspan<encoding_type> x, cspan<encoding_type> y,
                       span<encoding_type> d)
    { return map(CFT_IXOR, x, y, cspan<encoding_type>(), d); }
    std::uint32_t iadd(cspan<encoding_type> x, cspan<encoding_type> y,
                       span<encoding_type> d)
    { return map(CFT_IADD, x, y, cspan<encoding_type>(), d); }
    std::uint32_t isub(cspan<encoding_type> x, cspan<encoding_type> y,
                       span<encoding_type> d)
    { return map(CFT_ISUB, x, y, cspan<encoding_type>(), d); }
    std::uint32_t ishl(cspan<encoding_type> x, cspan<encoding_type> y,
                       span<encoding_type> d)
    { return map(CFT_ISHL, x, y, cspan<encoding_type>(), d); }
    std::uint32_t ishr(cspan<encoding_type> x, cspan<encoding_type> y,
                       span<encoding_type> d)
    { return map(CFT_ISHR, x, y, cspan<encoding_type>(), d); }
    std::uint32_t icmplt(cspan<encoding_type> x, cspan<encoding_type> y,
                         span<encoding_type> d)
    { return map(CFT_ICMPLT, x, y, cspan<encoding_type>(), d); }

    /* The seeds: quiet table lookups, relative error < 2^-8.5, from
     * which div and sqrt Newton-refine. They raise no flags ever and
     * ignore the attribute. */
    std::uint32_t recip_seed(cspan<encoding_type> x, span<encoding_type> d)
    { return map(CFT_RECIP_SEED, x, cspan<encoding_type>(),
                 cspan<encoding_type>(), d); }
    std::uint32_t rsqrt_seed(cspan<encoding_type> x, span<encoding_type> d)
    { return map(CFT_RSQRT_SEED, x, cspan<encoding_type>(),
                 cspan<encoding_type>(), d); }

    /* Correctly rounded division and square root: the library's fixed
     * seed / Newton / exact-residual sequence, not a shortcut, and
     * about 25-30 opcode passes an element. */
    std::uint32_t div(cspan<encoding_type> x, cspan<encoding_type> y,
                      span<encoding_type> d)
    {
        check_operand(x, d, "a");
        check_operand(y, d, "b");
        return record(dev_->div(F, rnd_, ptr(x), ptr(y), ptr(d), d.size()),
                      "cft_div");
    }
    std::uint32_t sqrt(cspan<encoding_type> x, span<encoding_type> d)
    {
        check_operand(x, d, "a");
        return record(dev_->sqrt(F, rnd_, ptr(x), ptr(d), d.size()),
                      "cft_sqrt");
    }

    /* ===========================================================
     * Batch: reductions - n in, ONE out
     * =========================================================== */

    /* The tree shape is part of the contract, not an implementation
     * detail: a node's LEFT child is the largest power of two strictly
     * smaller than the range, evaluated with this context's attribute
     * at every node. n == 0 is +0 and raises nothing; n == 1 is a[0]
     * verbatim, not even quieting a signaling NaN. */
    value_type reduce(cft_op op, cspan<encoding_type> a,
                      cspan<encoding_type> b) &
    {
        if (op == CFT_DOT && b.size() != a.size())
            throw std::invalid_argument(
                "cft::reduce: dot needs b as long as a (" +
                std::to_string(b.size()) + " vs " + std::to_string(a.size()) +
                ")");
        encoding_type d{};
        record(dev_->reduce(op, F, rnd_, ptr(a), ptr(b), d.data(), a.size()),
               "cft_reduce");
        return make(d);
    }
    value_type sum(cspan<encoding_type> a) &
    {
        return reduce(CFT_SUM, a, cspan<encoding_type>());
    }
    value_type dot(cspan<encoding_type> a, cspan<encoding_type> b) &
    {
        return reduce(CFT_DOT, a, b);
    }

    /* ===========================================================
     * Batch: the clause-5 completion set
     * =========================================================== */

    /* roundToIntegral (5.3.1). exact == false is the five named
     * operations, direction from this context's attribute, inexact
     * NEVER signalled; exact == true is roundToIntegralExact, which
     * signals inexact when the value changed. */
    std::uint32_t rint(cspan<encoding_type> a, span<encoding_type> d,
                       bool exact = false)
    {
        check_operand(a, d, "a");
        return record(dev_->rint(F, rnd_, exact, ptr(a), ptr(d), d.size()),
                      "cft_rint");
    }

    /* scaleB (5.3.3): d = a * 2^nexp, one rounding, full flags. */
    std::uint32_t scaleb(cspan<encoding_type> a, std::int64_t nexp,
                         span<encoding_type> d)
    {
        check_operand(a, d, "a");
        return record(dev_->scaleb(F, rnd_, ptr(a), nexp, ptr(d), d.size()),
                      "cft_scaleb");
    }

    /* The signaling comparisons (5.6.1): the same 1.0/+0.0 predicate
     * values as the quiet opcodes, but invalid for ANY NaN operand.
     * cmp is CFT_CMPLT, CFT_CMPLE or CFT_CMPEQ. */
    std::uint32_t cmp_sig(cft_op cmp, cspan<encoding_type> a,
                          cspan<encoding_type> b, span<encoding_type> d)
    {
        check_operand(a, d, "a");
        check_operand(b, d, "b");
        return record(dev_->cmp_sig(cmp, F, ptr(a), ptr(b), ptr(d), d.size()),
                      "cft_cmp_sig");
    }

    /* formatOf-convertFormat (5.4.2) into another format's encodings.
     * Widening is exact and silent, narrowing rounds once with full
     * flags, and the destination must not overlap the source -
     * elements change size, so in-place is not well defined. This is
     * the ONLY way a value changes format here; there is no implicit
     * widening anywhere in this header. */
    template <cft_format Dst>
    std::uint32_t convert(cspan<encoding_type> a, span<encoding<Dst>> d)
    {
        if (a.size() != d.size())
            throw std::invalid_argument(
                "cft::convert: source and destination lengths differ (" +
                std::to_string(a.size()) + " vs " + std::to_string(d.size()) +
                ")");
        return record(dev_->convert(F, Dst, rnd_, ptr(a), d.data(), d.size()),
                      "cft_convert");
    }

    /* convertFromInt (5.4.1). Exact where the integer fits the
     * significand, inexact where it outruns it; nothing else signals. */
    template <class Int>
    std::uint32_t from_int(cspan<Int> src, span<encoding_type> d)
    {
        if (src.size() != d.size())
            throw std::invalid_argument(
                "cft::from_int: source and destination lengths differ");
        return record(dev_->cvt_from(F, rnd_, src.data(), ptr(d), d.size()),
                      "cft_cvt_from");
    }

    /* convertToInteger (5.4.1), direction from the attribute; exact
     * selects the ...Exact family, which alone reports inexact. The
     * invalid cases deliver RISC-V's FCVT values, because determinism
     * cannot leave them open. */
    template <class Int>
    std::uint32_t to_int(cspan<encoding_type> a, span<Int> dst,
                         bool exact = false)
    {
        if (a.size() != dst.size())
            throw std::invalid_argument(
                "cft::to_int: source and destination lengths differ");
        return record(dev_->cvt_to(F, rnd_, exact, ptr(a), dst.data(),
                                   dst.size()),
                      "cft_cvt_to");
    }

    /* logB (5.3.3) in the operand's own format. Value-based, always
     * exact; logB(0) is -inf and signals divideByZero. */
    std::uint32_t logb(cspan<encoding_type> a, span<encoding_type> d)
    {
        check_operand(a, d, "a");
        return record(dev_->logb(F, ptr(a), ptr(d), d.size()), "cft_logb");
    }

    /* nextUp / nextDown (5.3.1): one step on the encoding. The largest
     * finite steps to infinity WITHOUT overflow; invalid on a
     * signaling NaN is the only signal these can raise. */
    std::uint32_t next_up(cspan<encoding_type> a, span<encoding_type> d)
    {
        check_operand(a, d, "a");
        return record(dev_->next_up(F, ptr(a), ptr(d), d.size()),
                      "cft_next_up");
    }
    std::uint32_t next_down(cspan<encoding_type> a, span<encoding_type> d)
    {
        check_operand(a, d, "a");
        return record(dev_->next_down(F, ptr(a), ptr(d), d.size()),
                      "cft_next_down");
    }

    /* class (5.7.2), one cft_class_value byte per element.
     * Non-computational: signals nothing, so there is no flag word and
     * this returns void rather than a flags word that would always be
     * zero. */
    void classify(cspan<encoding_type> a, span<std::uint8_t> cls)
    {
        if (a.size() != cls.size())
            throw std::invalid_argument(
                "cft::classify: one class byte per element");
        const cft_status st = dev_->classify(F, ptr(a), cls.data(), cls.size());
        if (st != CFT_OK)
            throw error(st, "cft_class");
    }

    /* totalOrder / totalOrderMag (5.10) as 1.0/+0.0 predicates.
     * Defined on the whole encoding space and signalling on nothing,
     * which is what makes them the sort key compareQuiet cannot be. */
    void total_order(cspan<encoding_type> a, cspan<encoding_type> b,
                     span<encoding_type> d)
    {
        check_operand(a, d, "a");
        check_operand(b, d, "b");
        const cft_status st =
            dev_->total_order(F, ptr(a), ptr(b), ptr(d), d.size());
        if (st != CFT_OK)
            throw error(st, "cft_total_order");
    }
    void total_order_mag(cspan<encoding_type> a, cspan<encoding_type> b,
                         span<encoding_type> d)
    {
        check_operand(a, d, "a");
        check_operand(b, d, "b");
        const cft_status st =
            dev_->total_order_mag(F, ptr(a), ptr(b), ptr(d), d.size());
        if (st != CFT_OK)
            throw error(st, "cft_total_order_mag");
    }

    /* remainder (5.3.1), exact always - no attribute is consumed
     * because none is used. Can be very slow per element for an
     * adversarial fp256 pair; cft.h quantifies it. */
    std::uint32_t rem(cspan<encoding_type> a, cspan<encoding_type> b,
                      span<encoding_type> d)
    {
        check_operand(a, d, "a");
        check_operand(b, d, "b");
        return record(dev_->rem(F, ptr(a), ptr(b), ptr(d), d.size()),
                      "cft_rem");
    }

    /* ===========================================================
     * The phase-1 transcendentals (ABI 0.3)
     *
     * Correctly rounded in this context's attribute, at this
     * context's format, with the clause 9.2.1 special values and
     * exact flags. Host operations, so there is no bus word and
     * nothing to ask cft_supports() about; cft.h and
     * docs/TRANSCENDENTALS.md carry the semantics.
     * =========================================================== */
    std::uint32_t exp(cspan<encoding_type> a, span<encoding_type> d)
    {
        check_operand(a, d, "a");
        return record(dev_->exp(F, rnd_, ptr(a), ptr(d), d.size()),
                      "cft_exp");
    }
    std::uint32_t expm1(cspan<encoding_type> a, span<encoding_type> d)
    {
        check_operand(a, d, "a");
        return record(dev_->expm1(F, rnd_, ptr(a), ptr(d), d.size()),
                      "cft_expm1");
    }
    std::uint32_t exp2(cspan<encoding_type> a, span<encoding_type> d)
    {
        check_operand(a, d, "a");
        return record(dev_->exp2(F, rnd_, ptr(a), ptr(d), d.size()),
                      "cft_exp2");
    }
    std::uint32_t log(cspan<encoding_type> a, span<encoding_type> d)
    {
        check_operand(a, d, "a");
        return record(dev_->log(F, rnd_, ptr(a), ptr(d), d.size()),
                      "cft_log");
    }
    std::uint32_t log1p(cspan<encoding_type> a, span<encoding_type> d)
    {
        check_operand(a, d, "a");
        return record(dev_->log1p(F, rnd_, ptr(a), ptr(d), d.size()),
                      "cft_log1p");
    }
    std::uint32_t log2(cspan<encoding_type> a, span<encoding_type> d)
    {
        check_operand(a, d, "a");
        return record(dev_->log2(F, rnd_, ptr(a), ptr(d), d.size()),
                      "cft_log2");
    }
    std::uint32_t log10(cspan<encoding_type> a, span<encoding_type> d)
    {
        check_operand(a, d, "a");
        return record(dev_->log10(F, rnd_, ptr(a), ptr(d), d.size()),
                      "cft_log10");
    }
    std::uint32_t pow(cspan<encoding_type> a, cspan<encoding_type> b,
                      span<encoding_type> d)
    {
        check_operand(a, d, "a");
        check_operand(b, d, "b");
        return record(dev_->pow(F, rnd_, ptr(a), ptr(b), ptr(d), d.size()),
                      "cft_pow");
    }
    std::uint32_t hypot(cspan<encoding_type> a, cspan<encoding_type> b,
                        span<encoding_type> d)
    {
        check_operand(a, d, "a");
        check_operand(b, d, "b");
        return record(dev_->hypot(F, rnd_, ptr(a), ptr(b), ptr(d), d.size()),
                      "cft_hypot");
    }

    /* ===========================================================
     * The phase-2 trigonometrics (ABI 0.4)
     *
     * sinPi, cosPi and tanPi reduce by x mod 2, which is exact on a
     * dyadic operand at every magnitude, so none of these needs the
     * argument reduction against pi that the radian sin/cos/tan
     * would. cft.h and docs/TRANSCENDENTALS.md carry the semantics.
     * =========================================================== */
#define CFT_HPP_CTX_TRIG1(name)                                         \
    std::uint32_t name(cspan<encoding_type> a, span<encoding_type> d)   \
    {                                                                   \
        check_operand(a, d, "a");                                       \
        return record(dev_->name(F, rnd_, ptr(a), ptr(d), d.size()),    \
                      "cft_" #name);                                    \
    }
    CFT_HPP_CTX_TRIG1(sinpi)
    CFT_HPP_CTX_TRIG1(cospi)
    CFT_HPP_CTX_TRIG1(tanpi)
    CFT_HPP_CTX_TRIG1(asin)
    CFT_HPP_CTX_TRIG1(acos)
    CFT_HPP_CTX_TRIG1(atan)
    CFT_HPP_CTX_TRIG1(asinpi)
    CFT_HPP_CTX_TRIG1(acospi)
    CFT_HPP_CTX_TRIG1(atanpi)
    /* the phase-3 nine (ABI 0.5): radians for sin, cos and tan */
    CFT_HPP_CTX_TRIG1(sin)
    CFT_HPP_CTX_TRIG1(cos)
    CFT_HPP_CTX_TRIG1(tan)
    CFT_HPP_CTX_TRIG1(sinh)
    CFT_HPP_CTX_TRIG1(cosh)
    CFT_HPP_CTX_TRIG1(tanh)
    CFT_HPP_CTX_TRIG1(asinh)
    CFT_HPP_CTX_TRIG1(acosh)
    CFT_HPP_CTX_TRIG1(atanh)
#undef CFT_HPP_CTX_TRIG1
    /* y first, then x - C's order, and the one every caller expects. */
    std::uint32_t atan2(cspan<encoding_type> a, cspan<encoding_type> b,
                        span<encoding_type> d)
    {
        check_operand(a, d, "a");
        check_operand(b, d, "b");
        return record(dev_->atan2(F, rnd_, ptr(a), ptr(b), ptr(d), d.size()),
                      "cft_atan2");
    }
    std::uint32_t atan2pi(cspan<encoding_type> a, cspan<encoding_type> b,
                          span<encoding_type> d)
    {
        check_operand(a, d, "a");
        check_operand(b, d, "b");
        return record(dev_->atan2pi(F, rnd_, ptr(a), ptr(b), ptr(d),
                                    d.size()),
                      "cft_atan2pi");
    }

    /* ===========================================================
     * The augmented arithmetic operations (754-2019 clause 9.5)
     *
     * Two outputs, and no attribute: 9.5 fixes the rounding to
     * roundTiesTowardZero, so THIS CONTEXT'S ATTRIBUTE IS NOT
     * CONSULTED - which is worth saying here, where every other
     * member on this class does consult it. `out_r` and `out_e` must
     * be different spans; either may alias an operand. cft.h has the
     * tie rule, the zero-sign rules and the flag policy.
     * =========================================================== */
#define CFT_HPP_CTX_AUG(name)                                           \
    std::uint32_t augmented_##name(cspan<encoding_type> a,              \
                                   cspan<encoding_type> b,              \
                                   span<encoding_type> out_r,           \
                                   span<encoding_type> out_e)           \
    {                                                                   \
        check_operand(a, out_r, "a");                                   \
        check_operand(b, out_r, "b");                                   \
        check_operand(out_e, out_r, "e");                               \
        return record(dev_->augmented_##name(F, ptr(a), ptr(b),         \
                                             ptr(out_r), ptr(out_e),    \
                                             out_r.size()),             \
                      "cft_augmented_" #name);                          \
    }
    CFT_HPP_CTX_AUG(add)
    CFT_HPP_CTX_AUG(sub)
    CFT_HPP_CTX_AUG(mul)
#undef CFT_HPP_CTX_AUG


    /* ===========================================================
     * Scalar convenience - every one of these is the batch of one
     *
     * Offered for clarity, not for throughput: N of these is N round
     * trips where one batch call would do, which is exactly the shape
     * a streaming engine does not want.
     * =========================================================== */
    value_type fma(const value_type &x, const value_type &y,
                   const value_type &z) &
    {
        return one_of(CFT_FMA, x.bytes(), y.bytes(), z.bytes());
    }
    value_type add(const value_type &x, const value_type &y) &
    { return one_of(CFT_ADD, x.bytes(), null_enc(), y.bytes()); }
    value_type sub(const value_type &x, const value_type &y) &
    { return one_of(CFT_SUB, x.bytes(), null_enc(), y.bytes()); }
    value_type mul(const value_type &x, const value_type &y) &
    { return one_of(CFT_MUL, x.bytes(), y.bytes(), null_enc()); }
    value_type abs(const value_type &x) &
    { return one_of(CFT_ABS, x.bytes(), null_enc(), null_enc()); }
    value_type neg(const value_type &x) &
    { return one_of(CFT_NEG, x.bytes(), null_enc(), null_enc()); }
    value_type copysign(const value_type &x, const value_type &y) &
    { return one_of(CFT_COPYSIGN, x.bytes(), y.bytes(), null_enc()); }
    value_type min(const value_type &x, const value_type &y) &
    { return one_of(CFT_MIN, x.bytes(), y.bytes(), null_enc()); }
    value_type max(const value_type &x, const value_type &y) &
    { return one_of(CFT_MAX, x.bytes(), y.bytes(), null_enc()); }
    value_type minnum(const value_type &x, const value_type &y) &
    { return one_of(CFT_MINNUM, x.bytes(), y.bytes(), null_enc()); }
    value_type maxnum(const value_type &x, const value_type &y) &
    { return one_of(CFT_MAXNUM, x.bytes(), y.bytes(), null_enc()); }
    value_type select(const value_type &a, const value_type &b,
                      const value_type &c) &
    { return one_of(CFT_SELECT, a.bytes(), b.bytes(), c.bytes()); }
    value_type predicate(cft_op cmp, const value_type &x, const value_type &y) &
    { return one_of(cmp, x.bytes(), y.bytes(), null_enc()); }

    value_type div(const value_type &x, const value_type &y) &
    {
        encoding_type d{};
        record(dev_->div(F, rnd_, x.bytes().data(), y.bytes().data(),
                         d.data(), 1),
               "cft_div");
        return make(d);
    }
    value_type sqrt(const value_type &x) &
    {
        encoding_type d{};
        record(dev_->sqrt(F, rnd_, x.bytes().data(), d.data(), 1), "cft_sqrt");
        return make(d);
    }
    value_type rint(const value_type &x, bool exact = false) &
    {
        encoding_type d{};
        record(dev_->rint(F, rnd_, exact, x.bytes().data(), d.data(), 1),
               "cft_rint");
        return make(d);
    }
    value_type scaleb(const value_type &x, std::int64_t nexp) &
    {
        encoding_type d{};
        record(dev_->scaleb(F, rnd_, x.bytes().data(), nexp, d.data(), 1),
               "cft_scaleb");
        return make(d);
    }
    value_type logb(const value_type &x) &
    {
        encoding_type d{};
        record(dev_->logb(F, x.bytes().data(), d.data(), 1), "cft_logb");
        return make(d);
    }
    value_type next_up(const value_type &x) &
    {
        encoding_type d{};
        record(dev_->next_up(F, x.bytes().data(), d.data(), 1), "cft_next_up");
        return make(d);
    }
    value_type next_down(const value_type &x) &
    {
        encoding_type d{};
        record(dev_->next_down(F, x.bytes().data(), d.data(), 1),
               "cft_next_down");
        return make(d);
    }
    value_type rem(const value_type &x, const value_type &y) &
    {
        encoding_type d{};
        record(dev_->rem(F, x.bytes().data(), y.bytes().data(), d.data(), 1),
               "cft_rem");
        return make(d);
    }
    value_type exp(const value_type &x) &
    {
        encoding_type d{};
        record(dev_->exp(F, rnd_, x.bytes().data(), d.data(), 1), "cft_exp");
        return make(d);
    }
    value_type expm1(const value_type &x) &
    {
        encoding_type d{};
        record(dev_->expm1(F, rnd_, x.bytes().data(), d.data(), 1),
               "cft_expm1");
        return make(d);
    }
    value_type exp2(const value_type &x) &
    {
        encoding_type d{};
        record(dev_->exp2(F, rnd_, x.bytes().data(), d.data(), 1),
               "cft_exp2");
        return make(d);
    }
    value_type log(const value_type &x) &
    {
        encoding_type d{};
        record(dev_->log(F, rnd_, x.bytes().data(), d.data(), 1), "cft_log");
        return make(d);
    }
    value_type log1p(const value_type &x) &
    {
        encoding_type d{};
        record(dev_->log1p(F, rnd_, x.bytes().data(), d.data(), 1),
               "cft_log1p");
        return make(d);
    }
    value_type log2(const value_type &x) &
    {
        encoding_type d{};
        record(dev_->log2(F, rnd_, x.bytes().data(), d.data(), 1),
               "cft_log2");
        return make(d);
    }
    value_type log10(const value_type &x) &
    {
        encoding_type d{};
        record(dev_->log10(F, rnd_, x.bytes().data(), d.data(), 1),
               "cft_log10");
        return make(d);
    }
    value_type pow(const value_type &x, const value_type &y) &
    {
        encoding_type d{};
        record(dev_->pow(F, rnd_, x.bytes().data(), y.bytes().data(),
                         d.data(), 1),
               "cft_pow");
        return make(d);
    }
    value_type hypot(const value_type &x, const value_type &y) &
    {
        encoding_type d{};
        record(dev_->hypot(F, rnd_, x.bytes().data(), y.bytes().data(),
                           d.data(), 1),
               "cft_hypot");
        return make(d);
    }
#define CFT_HPP_SCALAR_TRIG1(name)                                      \
    value_type name(const value_type &x) &                              \
    {                                                                   \
        encoding_type d{};                                              \
        record(dev_->name(F, rnd_, x.bytes().data(), d.data(), 1),      \
               "cft_" #name);                                           \
        return make(d);                                                 \
    }
    CFT_HPP_SCALAR_TRIG1(sinpi)
    CFT_HPP_SCALAR_TRIG1(cospi)
    CFT_HPP_SCALAR_TRIG1(tanpi)
    CFT_HPP_SCALAR_TRIG1(asin)
    CFT_HPP_SCALAR_TRIG1(acos)
    CFT_HPP_SCALAR_TRIG1(atan)
    CFT_HPP_SCALAR_TRIG1(asinpi)
    CFT_HPP_SCALAR_TRIG1(acospi)
    CFT_HPP_SCALAR_TRIG1(atanpi)
    CFT_HPP_SCALAR_TRIG1(sin)
    CFT_HPP_SCALAR_TRIG1(cos)
    CFT_HPP_SCALAR_TRIG1(tan)
    CFT_HPP_SCALAR_TRIG1(sinh)
    CFT_HPP_SCALAR_TRIG1(cosh)
    CFT_HPP_SCALAR_TRIG1(tanh)
    CFT_HPP_SCALAR_TRIG1(asinh)
    CFT_HPP_SCALAR_TRIG1(acosh)
    CFT_HPP_SCALAR_TRIG1(atanh)
#undef CFT_HPP_SCALAR_TRIG1
    value_type atan2(const value_type &y, const value_type &x) &
    {
        encoding_type d{};
        record(dev_->atan2(F, rnd_, y.bytes().data(), x.bytes().data(),
                           d.data(), 1),
               "cft_atan2");
        return make(d);
    }
    value_type atan2pi(const value_type &y, const value_type &x) &
    {
        encoding_type d{};
        record(dev_->atan2pi(F, rnd_, y.bytes().data(), x.bytes().data(),
                             d.data(), 1),
               "cft_atan2pi");
        return make(d);
    }
    cft_class_value classify(const value_type &x)
    {
        std::uint8_t cls = 0;
        const cft_status st = dev_->classify(F, x.bytes().data(), &cls, 1);
        if (st != CFT_OK)
            throw error(st, "cft_class");
        return static_cast<cft_class_value>(cls);
    }
    bool total_order(const value_type &x, const value_type &y)
    {
        encoding_type d{};
        const cft_status st = dev_->total_order(F, x.bytes().data(),
                                                y.bytes().data(), d.data(), 1);
        if (st != CFT_OK)
            throw error(st, "cft_total_order");
        return !is_zero_enc(d);
    }
    bool total_order_mag(const value_type &x, const value_type &y)
    {
        encoding_type d{};
        const cft_status st = dev_->total_order_mag(
            F, x.bytes().data(), y.bytes().data(), d.data(), 1);
        if (st != CFT_OK)
            throw error(st, "cft_total_order_mag");
        return !is_zero_enc(d);
    }

    /* ===========================================================
     * The doorways in and out of host integer and double
     * =========================================================== */

    /* An integer, converted by the library (5.4.1). */
    template <class Int>
    value_type from_int(Int v) &
    {
        encoding_type d{};
        record(dev_->cvt_from(F, rnd_, &v, d.data(), 1), "cft_cvt_from");
        return make(d);
    }

    template <class Int>
    Int to_int(const value_type &x, bool exact = false)
    {
        Int out = 0;
        record(dev_->cvt_to(F, rnd_, exact, x.bytes().data(), &out, 1),
               "cft_cvt_to");
        return out;
    }

    /* A host double in. The double's own bytes ARE a binary64
     * encoding - that part is a copy, asserted at the top of this
     * header - and the library then converts binary64 to this format,
     * which is exact for fp64/fp128/fp256 and a real rounding for
     * fp32. Nothing wider than binary64 is ever routed through a
     * double: a value that does not fit one never becomes one here. */
    value_type from_double(double x) &
    {
        fp64_enc src{};
        std::memcpy(src.data(), &x, sizeof x);
        encoding_type d{};
        record(dev_->convert(CFT_FP64, F, rnd_, src.data(), d.data(), 1),
               "cft_convert");
        return make(d);
    }

    /* And out. A conversion, not a view: for fp128 and fp256 this
     * ROUNDS, in the library, under this context's attribute, with the
     * flags to prove it - and a binary64 cannot carry an fp256 or a
     * NaN payload. Move values as bytes or hex when that matters. */
    double to_double(const value_type &x)
    {
        fp64_enc dst{};
        record(dev_->convert(F, CFT_FP64, rnd_, x.bytes().data(), dst.data(), 1),
               "cft_convert");
        double out = 0.0;
        std::memcpy(&out, dst.data(), sizeof out);
        return out;
    }

    /* Format change for a single value, the library's own conversion. */
    template <cft_format Dst>
    encoding<Dst> convert(const value_type &x)
    {
        encoding<Dst> d{};
        record(dev_->convert(F, Dst, rnd_, x.bytes().data(), d.data(), 1),
               "cft_convert");
        return d;
    }

    /* Recorded and OR'd like every other call, then handed back so a
     * caller can branch on the word from THIS call alone. */
    std::uint32_t record(const call_result &r, const char *where)
    {
        const std::uint32_t f = r.check(where);
        last_ = f;
        sticky_ |= f;
        return f;
    }

private:
    static const void *ptr(cspan<encoding_type> s) noexcept
    {
        return s.empty() ? nullptr : static_cast<const void *>(s.data());
    }
    static void *ptr(span<encoding_type> s) noexcept
    {
        return s.empty() ? nullptr : static_cast<void *>(s.data());
    }
    static cspan<encoding_type> null_enc() noexcept
    {
        return cspan<encoding_type>();
    }
    static bool is_zero_enc(const encoding_type &e) noexcept
    {
        for (std::size_t i = 0; i < e.size(); i++)
            if (e[i])
                return false;
        return true;
    }

    /* An operand is either absent (empty span -> NULL) or exactly as
     * long as the output. A shorter one is a bug the library cannot
     * see: it would read past the end of the caller's array. */
    static void check_operand(cspan<encoding_type> s, span<encoding_type> d,
                              const char *name)
    {
        if (!s.empty() && s.size() != d.size())
            throw std::invalid_argument(
                std::string("cft: operand ") + name + " has " +
                std::to_string(s.size()) + " elements, output has " +
                std::to_string(d.size()));
    }

    value_type one_of(cft_op op, const encoding_type &a, const encoding_type &b,
                      const encoding_type &c) &
    {
        encoding_type d{};
        record(dev_->run(op, F, rnd_, a.data(), b.data(), c.data(), d.data(), 1),
               "cft_run");
        return make(d);
    }
    /* The overload that lets a scalar op pass "no operand" as NULL
     * rather than as a zero encoding the opcode would ignore anyway -
     * kept honest so the wrapper's scalar path issues exactly the C
     * call the batch path issues. */
    value_type one_of(cft_op op, const encoding_type &a,
                      cspan<encoding_type> b, const encoding_type &c) &
    {
        encoding_type d{};
        record(dev_->run(op, F, rnd_, a.data(), ptr(b), c.data(), d.data(), 1),
               "cft_run");
        return make(d);
    }
    value_type one_of(cft_op op, const encoding_type &a,
                      const encoding_type &b, cspan<encoding_type> c) &
    {
        encoding_type d{};
        record(dev_->run(op, F, rnd_, a.data(), b.data(), ptr(c), d.data(), 1),
               "cft_run");
        return make(d);
    }
    value_type one_of(cft_op op, const encoding_type &a,
                      cspan<encoding_type> b, cspan<encoding_type> c) &
    {
        encoding_type d{};
        record(dev_->run(op, F, rnd_, a.data(), ptr(b), ptr(c), d.data(), 1),
               "cft_run");
        return make(d);
    }

    device      *dev_ = nullptr;
    cft_round    rnd_ = CFT_RNE;
    std::uint32_t sticky_ = 0;
    std::uint32_t last_ = 0;
};

using context32  = basic_context<CFT_FP32>;
using context64  = basic_context<CFT_FP64>;
using context128 = basic_context<CFT_FP128>;
using context256 = basic_context<CFT_FP256>;

/* ---------------------------------------------------------------
 * value<F>'s operators, now that basic_context is complete
 * --------------------------------------------------------------- */
template <cft_format F>
basic_context<F> *value<F>::require_same(const value &o, const char *what) const
{
    if (!ctx_ || ctx_ != o.ctx_)
        throw std::invalid_argument(
            std::string("cft::value::") + what +
            ": both operands must belong to the same context - two contexts "
            "can differ in rounding attribute, and there is no defensible "
            "answer to which one an expression meant");
    return ctx_;
}

template <cft_format F>
value<F> value<F>::operator+(const value &o) const
{ return require_same(o, "operator+")->add(*this, o); }

template <cft_format F>
value<F> value<F>::operator-(const value &o) const
{ return require_same(o, "operator-")->sub(*this, o); }

template <cft_format F>
value<F> value<F>::operator*(const value &o) const
{ return require_same(o, "operator*")->mul(*this, o); }

template <cft_format F>
value<F> value<F>::operator/(const value &o) const
{ return require_same(o, "operator/")->div(*this, o); }

template <cft_format F>
value<F> value<F>::operator-() const
{
    if (!ctx_)
        throw std::invalid_argument(
            "cft::value::operator-: no context to negate in");
    return ctx_->neg(*this);
}

namespace detail {
template <cft_format F>
inline bool predicate_true(basic_context<F> *ctx, cft_op op,
                           const value<F> &a, const value<F> &b)
{
    const value<F> r = ctx->predicate(op, a, b);
    for (std::size_t i = 0; i < r.bytes().size(); i++)
        if (r.bytes()[i])
            return true;
    return false;
}
}  // namespace detail

template <cft_format F>
bool value<F>::operator==(const value &o) const
{ return detail::predicate_true(require_same(o, "operator=="), CFT_CMPEQ, *this, o); }

template <cft_format F>
bool value<F>::operator!=(const value &o) const
{ return !detail::predicate_true(require_same(o, "operator!="), CFT_CMPEQ, *this, o); }

template <cft_format F>
bool value<F>::operator<(const value &o) const
{ return detail::predicate_true(require_same(o, "operator<"), CFT_CMPLT, *this, o); }

template <cft_format F>
bool value<F>::operator<=(const value &o) const
{ return detail::predicate_true(require_same(o, "operator<="), CFT_CMPLE, *this, o); }

/* a > b IS cmplt with the operands swapped - cft.h is explicit that no
 * separate opcode exists or is needed. */
template <cft_format F>
bool value<F>::operator>(const value &o) const
{ return detail::predicate_true(require_same(o, "operator>"), CFT_CMPLT, o, *this); }

template <cft_format F>
bool value<F>::operator>=(const value &o) const
{ return detail::predicate_true(require_same(o, "operator>="), CFT_CMPLE, o, *this); }

}  // namespace cft

#endif /* CFT_HPP */
