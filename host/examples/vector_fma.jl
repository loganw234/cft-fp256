# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
#
# The same program as vector_fma.c, in Julia, through ccall.
#
#     julia host/examples/vector_fma.jl [artifact.xclbin]
#
# It must print exactly what the C program prints - every line, every
# digit. Nothing beyond the standard library is used: Libdl finds the
# shared library, Printf formats the lines, and ccall is part of the
# language. No package, no Project.toml, no binding generator - the
# claim cft.h makes about its ABI, paid out in another language.
#
# As in the ctypes port, the arithmetic is not reimplemented here.
# Only the operand stream and the checksum are, because they are the
# test harness rather than the product; everything the library
# guarantees still happens inside the library.
#
# *** UNVERIFIED ***
# The machine this file was written on has no Julia toolchain - none
# on PATH, none in the usual install directories, none in the repo's
# containers - so unlike every other file in examples/ this one has
# not been run against the library it binds. The claim it makes is
# still machine-checkable: `make -C host examples-lang` diffs its
# output against the C example's on any machine that does have julia.
# Run that before trusting this file, and delete this block when it
# passes - an example should not keep its asterisk one commit longer
# than the asterisk is true.

using Libdl
using Printf

# cft_op and cft_round - the values are normative (cft.h), so a
# caller writes the names and never the register layout behind them.
const FMA = Cint(0)
const RNE = Cint(0)

const N = 4096

# width, exp_w, man_w, bias - the geometry table vector_fma.c
# carries. This is operand-stream machinery, not format knowledge the
# caller should own: element sizes and format names below still come
# from the library, because a size the caller guesses is a size that
# goes stale.
const GEOM = [
    (32, 8, 23, 127),
    (64, 11, 52, 1023),
    (128, 15, 112, 16383),
    (256, 19, 236, 262143),
]

# Exactly one candidate, chosen by platform - the same policy as
# vector_fma_ctypes.py, for the same reason: listing every name and
# taking the first that exists looks tolerant and is not. A tree
# built from two platforms holds both libraries, and the fallback
# then loads the foreign one and fails with a loader error instead of
# "build it first".
function library_path()
    override = get(ENV, "CFT_LIB", "")
    isempty(override) || return override
    name = Sys.iswindows() ? "cft.dll" :
           Sys.isapple() ? "libcft.dylib" : "libcft.so"
    root = normpath(joinpath(@__DIR__, "..", ".."))
    return joinpath(root, "host", name)
end

function load()
    path = library_path()
    if !isfile(path)
        println(stderr, "$path not found - run `make -C host` first")
        exit(1)
    end
    return dlopen(path)
end

# xorshift32, stepped once per byte - the stream vector_fma.c
# generates, which is what lets the two checksums be compared at all.
# Julia's fixed-width unsigned integers shift and wrap exactly as C's
# unsigned ints do, so the port is line for line.
mutable struct Rng
    s::UInt32
    Rng(seed::Integer) = new(seed == 0 ? UInt32(1) : UInt32(seed))
end

function rng_byte!(r::Rng)
    s = r.s
    s = xor(s, s << 13)
    s = xor(s, s >> 17)
    s = xor(s, s << 5)
    r.s = s
    return UInt8(s & 0xff)
end

# One element at byte offset `off` of e: a normal with a fraction
# from the stream and an exponent within 32 of 1.0, so that products
# stay in range and the run exercises rounding rather than overflow.
# vector_fma.c line for line, shifted to 1-based indexing - the
# offsets are the one place a Julia port can silently diverge, which
# is precisely what the checksum diff exists to catch.
function make_element!(e::Vector{UInt8}, off::Int, r::Rng,
                       width::Int, exp_w::Int, man_w::Int, bias::Int)
    nb = div(width, 8)
    kb = div(man_w, 8)
    rb = man_w % 8

    for j in 1:nb
        e[off + j] = rng_byte!(r)
    end
    ef = bias - 32 + Int(rng_byte!(r) & 0x3f)

    e[off + kb + 1] &= UInt8((1 << rb) - 1)
    for j in (kb + 2):nb
        e[off + j] = 0x00
    end
    for j in 0:(exp_w - 1)
        if ((ef >> j) & 1) != 0
            bit = man_w + j
            e[off + div(bit, 8) + 1] |= UInt8(1) << (bit % 8)
        end
    end
    if (rng_byte!(r) & 0x01) != 0x00
        e[off + nb] |= 0x80
    end
end

# FNV-1a, 64-bit. The constants are written in hex because that is
# how they are specified; transcribing them as decimal is how you get
# a checksum that is stable, plausible, and not FNV.
function fnv1a(p::Vector{UInt8})
    h = 0xcbf29ce484222325
    for b in p
        h = xor(h, b)
        h *= 0x100000001b3
    end
    return h
end

function main()
    artifact = isempty(ARGS) ? nothing : ARGS[1]
    backend = artifact === nothing ? "software" : artifact
    lib = load()

    # One dlsym per entry point. ccall through a looked-up pointer is
    # the stdlib route to a library whose location is decided at run
    # time; the tuple of argument types is the entire binding, which
    # is the point being demonstrated.
    cft_open        = dlsym(lib, :cft_open)
    cft_close       = dlsym(lib, :cft_close)
    cft_run         = dlsym(lib, :cft_run)
    cft_supports    = dlsym(lib, :cft_supports)
    cft_format_size = dlsym(lib, :cft_format_size)
    cft_format_name = dlsym(lib, :cft_format_name)
    cft_strerror    = dlsym(lib, :cft_strerror)

    strerror(st) =
        unsafe_string(ccall(cft_strerror, Ptr{UInt8}, (Cint,), st))

    dev = Ref{Ptr{Cvoid}}(C_NULL)
    st = ccall(cft_open, Cint, (Ptr{UInt8}, Cint, Ptr{Ptr{Cvoid}}),
               artifact === nothing ? C_NULL : artifact, Cint(0), dev)
    if st != 0
        println(stderr, "cft_open($backend): $(strerror(st))")
        exit(1)
    end
    println("cft-fp256 vector fma, $backend backend")

    for f in 0:3
        (width, exp_w, man_w, bias) = GEOM[f + 1]
        fmt = Cint(f)

        # The name comes from the library, not a local table - cft.h
        # provides cft_format_name precisely so a binding, a log line
        # and a conformance report all say the same thing.
        name = unsafe_string(ccall(cft_format_name, Ptr{UInt8}, (Cint,),
                                   fmt))

        if ccall(cft_supports, Cint, (Ptr{Cvoid}, Cint, Cint),
                 dev[], FMA, fmt) == 0
            @printf("%-6s not available on this device\n", name)
            continue
        end

        esz = Int(ccall(cft_format_size, Csize_t, (Cint,), fmt))

        a = Vector{UInt8}(undef, N * esz)
        b = Vector{UInt8}(undef, N * esz)
        c = Vector{UInt8}(undef, N * esz)
        d = Vector{UInt8}(undef, N * esz)

        # Seeded per format, so each line is independent of the ones
        # before it and can be reproduced on its own.
        r = Rng(0x1234567 + f)
        for i in 0:(N - 1)
            make_element!(a, i * esz, r, width, exp_w, man_w, bias)
            make_element!(b, i * esz, r, width, exp_w, man_w, bias)
            make_element!(c, i * esz, r, width, exp_w, man_w, bias)
        end

        flags = Ref{UInt32}(0)
        st = ccall(cft_run, Cint,
                   (Ptr{Cvoid}, Cint, Cint, Cint,
                    Ptr{UInt8}, Ptr{UInt8}, Ptr{UInt8}, Ptr{UInt8},
                    Csize_t, Ptr{UInt32}, Ptr{UInt32}),
                   dev[], FMA, fmt, RNE, a, b, c, d, N, flags, C_NULL)
        if st != 0
            println(stderr, "cft_run $name: $(strerror(st))")
            ccall(cft_close, Cvoid, (Ptr{Cvoid},), dev[])
            exit(1)
        end

        @printf("%-6s n=%d rne  checksum 0x%016x  flags 0x%02x\n",
                name, N, fnv1a(d), flags[])
    end

    ccall(cft_close, Cvoid, (Ptr{Cvoid},), dev[])
end

if abspath(PROGRAM_FILE) == @__FILE__
    main()
end
