# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
#
# libcft. Plain C99, no dependencies, no configure step - a library
# whose reason to exist is that other languages can call it should not
# demand a toolchain to build.
#
#   make                 static + shared library and the tools
#   make test            build, then run the contract tests and replay
#                        the published vectors through the library
#   make examples-lang   the C/Python identity check again, for the
#                        optional toolchains: C++, Julia, Rust, Go, C#
#                        and R are each run and diffed if present,
#                        SKIPped by name if not
#   make lang-rust       one leg of that on its own (lang-cpp,
#                        lang-julia, lang-rust, lang-go, lang-csharp,
#                        lang-r, lang-fortran) - how verify/run.sh
#                        reports the languages one by one
#   make cpptest         cft.hpp against cft.h, at C++17 and C++20.
#                        Its own target rather than part of `test`
#                        because a C library whose point is that it
#                        needs no toolchain should not make its own
#                        test lane demand a C++ one
#   make CC=clang        or any other C99 compiler
#
# On Windows, match the compiler's word size to the PYTHON you will run
# the ctypes checks with. An MSYS2 install puts an i686 gcc on PATH as
# `cc` while the system Python is 64-bit, and the mismatch does not
# surface until ctypes says
#
#   OSError: [WinError 193] %1 is not a valid Win32 application
#
# which reads like a corrupt DLL rather than a wrong architecture. The
# 64-bit compiler is the mingw64 one:
#
#   PATH="/c/msys64/mingw64/bin:$PATH" make CC=gcc test
#
# The shared library is what the ctypes and Julia callers load; the
# static one is for embedding, and is what the C, Fortran and Rust
# examples link.

CC      ?= cc
CXX     ?= g++
AR      ?= ar
PYTHON  ?= python3
CFLAGS  ?= -O2
CSTD    := -std=c99
CXXSTD  := -std=c++17
# cft.hpp is header-only and C++17 minimum, and uses std::span only
# behind a feature check - so the header is compiled BOTH ways by
# `cpptest`, because a feature check whose two branches were never
# both built is a feature check nobody has tested.
CXXSTD20 := -std=c++20
WARN    := -Wall -Wextra -Wpedantic -Wshadow
INC     := -Iinclude

SRC     := src/bigint.c src/softfloat.c src/device.c src/divsqrt.c \
           src/clause5.c src/program.c src/conformance.c
OBJ     := $(SRC:.c=.o)
PICOBJ  := $(SRC:.c=.lo)

# The device backend. Off by default, because the whole point of the
# software backend is that libcft builds and runs on a machine with no
# card, no driver and no Vitis - and a library that needed XRT to
# compile would not be that.
#
#   make XRT=1                 on a machine with XRT installed
#   make XRT=1 XRT_ROOT=...    if it lives somewhere else
#
# backend_xrt.cpp is the only C++ here, and only because XRT's API is
# C++. It exports nothing but the C functions in src/backend.h, so the
# library's surface is the same either way.
XRT      ?= 0
XRT_ROOT ?= /opt/xilinx/xrt
ifeq ($(XRT),1)
  XRTDEF  := -DCFT_ENABLE_XRT
  # -isystem, not -I: XRT's own headers trip -Wshadow and friends by
  # the hundred, and they are not ours to fix. Warnings you cannot act
  # on are warnings you learn to ignore, which is how a real one gets
  # missed.
  XRTINC  := -isystem $(XRT_ROOT)/include
  XRTLIBS := -L$(XRT_ROOT)/lib -lxrt_coreutil -lstdc++ -lpthread -luuid
  OBJ     += src/backend_xrt.o
  PICOBJ  += src/backend_xrt.lo
endif

ifeq ($(OS),Windows_NT)
  SHLIB   := cft.dll
  SHFLAGS := -shared -Wl,--out-implib,libcft.dll.a
  SHDEF   := -DCFT_BUILD_SHARED
  PIC     :=
  EXE     := .exe
  # make under MSYS2 hands recipes a stripped environment - HOME, PATH
  # and a few system variables, no USERPROFILE, no APPDATA, no TEMP -
  # and without those NuGet cannot locate its packages folder ("Value
  # cannot be null. (Parameter 'path1')"), so the C# example failed in
  # a way that read as a checksum mismatch (2026-09-02). Measured under
  # `env -i`: USERPROFILE alone is not enough; the set below is. All
  # taken from the registry - HKCU\Volatile Environment\USERPROFILE is
  # the profile Windows itself uses, and reg.exe reads it regardless of
  # what the process environment lost - because HOME is no use here:
  # under MSYS2 make it is /home/<user>, which cygpath maps to
  # C:\Program Files\Git\home\<user>, a profile that does not exist
  # (measured: "Access to the path ... is denied"). cygpath of HOME
  # stays as the fallback for a shell that has a real HOME and no
  # reg.exe. Plus dotnet's own switches that keep a first run from
  # writing sentinels and notices into the log.
  # `//v`, not `/v`: from an MSYS shell a lone `/v` is rewritten into a
  # path before reg.exe sees it and the query fails with "Invalid
  # syntax"; the doubled slash is the documented escape.
  WINHOME    := $(strip $(shell reg query "HKCU\Volatile Environment" //v USERPROFILE 2>/dev/null \
                  | sed -n 's/.*REG_SZ[[:space:]]*//p' | tr -d '\r'))
  ifeq ($(WINHOME),)
    WINHOME  := $(strip $(shell powershell -NoProfile -NonInteractive -Command \
                  "[Environment]::GetFolderPath('UserProfile')" 2>/dev/null | tr -d '\r'))
  endif
  ifeq ($(WINHOME),)
    WINHOME  := $(shell cygpath -w "$(HOME)" 2>/dev/null || echo "$(HOME)")
  endif
  # PROGRAMFILES is the one NuGet's "path1" actually came from - with
  # the profile set alone it still failed; with this it passes. Passed
  # through `env` because the x86 name carries parentheses, which the
  # shell's VAR=value prefix form does not accept.
  SYSTEMDRIVE ?= C:
  DOTNET_ENV := env USERPROFILE="$(WINHOME)" \
                APPDATA="$(WINHOME)\AppData\Roaming" \
                LOCALAPPDATA="$(WINHOME)\AppData\Local" \
                TEMP="$(WINHOME)\AppData\Local\Temp" \
                TMP="$(WINHOME)\AppData\Local\Temp" \
                PROGRAMFILES="$(SYSTEMDRIVE)\Program Files" \
                "PROGRAMFILES(X86)=$(SYSTEMDRIVE)\Program Files (x86)" \
                DOTNET_SKIP_FIRST_TIME_EXPERIENCE=1 DOTNET_NOLOGO=1 \
                DOTNET_CLI_TELEMETRY_OPTOUT=1
else
  DOTNET_ENV :=
  SHLIB   := libcft.so
  SHFLAGS := -shared
  SHDEF   :=
  PIC     := -fPIC -fvisibility=hidden
  EXE     :=
endif

TOOLS := cft-selftest$(EXE) cft-bench$(EXE)
TESTS := api-test$(EXE) reduce-parts$(EXE)
EXAMPLES := vector-fma$(EXE)

.PHONY: all test cpptest difftest seqtest reducetest coverage fortran \
        examples-lang lang-cpp lang-julia lang-rust lang-go lang-csharp \
        lang-r lang-fortran clean

all: libcft.a $(SHLIB) $(TOOLS) $(EXAMPLES)

# Every object depends on every header. Crude next to real dependency
# generation, but this bit twice in one day - a stale device.o
# reported the old ABI version against a fresh api-test, then a stale
# program.o reported a STATUS bit the model had moved - and the build
# is small enough that over-rebuilding costs seconds where a stale
# object costs a debugging session.
HDRS := include/cft.h $(wildcard src/*.h)
$(OBJ) $(PICOBJ): $(HDRS)

%.o: %.c
	$(CC) $(CSTD) $(CFLAGS) $(WARN) $(INC) $(XRTDEF) -c $< -o $@

%.lo: %.c
	$(CC) $(CSTD) $(CFLAGS) $(WARN) $(INC) $(XRTDEF) $(PIC) $(SHDEF) \
		-c $< -o $@

%.o: %.cpp
	$(CXX) $(CXXSTD) $(CFLAGS) $(WARN) $(INC) $(XRTINC) -c $< -o $@

%.lo: %.cpp
	$(CXX) $(CXXSTD) $(CFLAGS) $(WARN) $(INC) $(XRTINC) $(PIC) $(SHDEF) \
		-c $< -o $@

libcft.a: $(OBJ)
	$(AR) rcs $@ $^

$(SHLIB): $(PICOBJ)
	$(CC) $(SHFLAGS) -o $@ $^ $(XRTLIBS)

cft-selftest$(EXE): tools/cft_selftest.c libcft.a
	$(CC) $(CSTD) $(CFLAGS) $(WARN) $(INC) $^ -o $@ $(XRTLIBS)

# Reports ns/element per format and per op, for the software backend or
# for an artifact. Same binary either way, so the two tiers are compared
# with one measurement rather than two.
cft-bench$(EXE): tools/cft_bench.c libcft.a
	$(CC) $(CSTD) $(CFLAGS) $(WARN) $(INC) $^ -o $@ $(XRTLIBS)

api-test$(EXE): tests/api_test.c libcft.a
	$(CC) $(CSTD) $(CFLAGS) $(WARN) $(INC) $^ -o $@ $(XRTLIBS)

# Built against src/ as well as include/: the canonical partitioner is
# internal, and a host never sees it - it calls cft_reduce.
reduce-parts$(EXE): tests/reduce_parts_test.c libcft.a
	$(CC) $(CSTD) $(CFLAGS) $(WARN) $(INC) -Isrc $^ -o $@ $(XRTLIBS)

vector-fma$(EXE): examples/vector_fma.c libcft.a
	$(CC) $(CSTD) $(CFLAGS) $(WARN) $(INC) $^ -o $@ $(XRTLIBS)

# cft.hpp against cft.h: every wrapper entry point issued twice on the
# same bytes, compared for identical encodings and identical flags.
# Built at both standards, from one source, because the header picks
# std::span or its own view on a feature check and the answer must not
# depend on which. Not $^ in the recipe: cft.hpp is a prerequisite so
# that editing it rebuilds these, but handing a header to the compiler
# would precompile it instead.
cpp-api-test$(EXE): tests/cpp_api_test.cpp libcft.a include/cft.hpp
	$(CXX) $(CXXSTD) $(CFLAGS) $(WARN) $(INC) tests/cpp_api_test.cpp \
		libcft.a -o $@ $(XRTLIBS)

cpp-api-test20$(EXE): tests/cpp_api_test.cpp libcft.a include/cft.hpp
	$(CXX) $(CXXSTD20) $(CFLAGS) $(WARN) $(INC) tests/cpp_api_test.cpp \
		libcft.a -o $@ $(XRTLIBS)

# The C++ layer's whole test story. Takes the vector directory the
# same way cft-selftest does; the replay inside is cft_conformance
# itself, reached through the wrapper.
cpptest: all cpp-api-test$(EXE) cpp-api-test20$(EXE)
	./cpp-api-test$(EXE) ../vectors/out
	./cpp-api-test20$(EXE) ../vectors/out

# Only meaningful in an XRT build, and only useful with an artifact:
#   ./device-test cardday/quad_emu/cft_hw_emu.xclbin 256
device-test$(EXE): tests/device_test.c libcft.a
	$(CC) $(CSTD) $(CFLAGS) $(WARN) $(INC) $^ -o $@ $(XRTLIBS)

# The library is checked four ways, and they catch different things.
#
#   api-test        the promises the vectors cannot express: aliasing,
#                   optional operands, arguments that must be refused
#   cft-selftest    replay of the published vector sets
#   the C/Python    the cross-language claim. Two languages, one
#   comparison      library, and the output has to be identical or the
#                   ABI is not doing its job (examples-lang re-runs
#                   this one for julia and rustc, whichever this
#                   machine carries)
#   diff_check.py   this library against the golden model right now,
#                   over the far/near alignment boundary that neither
#                   of the first two reaches. Needs Python and takes a
#                   few minutes, so it is its own target.
test: all $(TESTS)
	./api-test$(EXE)
	./reduce-parts$(EXE)
	./cft-selftest$(EXE) ../vectors/out
	./vector-fma$(EXE) > .out-c.txt
	$(PYTHON) examples/vector_fma_ctypes.py > .out-py.txt
	diff .out-c.txt .out-py.txt
	@echo "C and Python reached the same library and got the same bits"
	@rm -f .out-c.txt .out-py.txt

# `FC ?= gfortran` looks right and does nothing: make defines FC as a
# built-in (f77), so ?= never fires and the target silently used
# whatever f77 happens to be. Overriding only the DEFAULT leaves
# `make FC=...` working.
ifeq ($(origin FC),default)
  FC := gfortran
endif
fortran: libcft.a
	$(FC) examples/vector_fma.f90 libcft.a -o vector-fma-f$(EXE)
	./vector-fma-f$(EXE)

# The C/Python identity check from `test`, re-run for the language
# toolchains this Makefile does not get to assume. Every leg is
# optional here: a machine that lacks a toolchain says SKIP with the
# language's name and checks what it has, because a log that quietly
# checked nothing must not read as a pass - the rule cft_conformance
# applies to its own summary, applied to make. A toolchain that IS
# present and prints different bits fails the build outright; that is
# a broken ABI story, not a warning.
#
# Each leg is its own target - lang-cpp, lang-julia, lang-rust,
# lang-go, lang-csharp, lang-r, and lang-fortran for the `fortran`
# target under the same naming - so that verify/run.sh can run and
# report them one at a time, by language. `examples-lang` is all of
# them and then the cleanup. The legs share .out-c.txt, the C
# example's output, made once by its own rule.
#
# The C++ leg is the same example again through host/include/cft.hpp,
# so it checks the wrapper's marshalling with the checksum the other
# six languages are already held to. It follows the C# leg's shape for
# the same reason that one has it: a compile that fails must be
# reported as a build failure and not left looking like a bit
# mismatch.
#
# --strip-trailing-cr: on Windows the C example's stdout passes
# through msvcrt text mode and picks up \r\n, while Rust and Julia
# write \n on every platform. The CR is the C runtime's contribution,
# not the library's, and the characters of the checksum lines are
# what is under test - so the diff strips it rather than teaching two
# more languages to imitate msvcrt. (On Linux both sides are already
# \n and the flag changes nothing.)
.out-c.txt: vector-fma$(EXE)
	./vector-fma$(EXE) > .out-c.txt

lang-cpp: all .out-c.txt
	@if command -v $(CXX) >/dev/null 2>&1; then \
		if ! $(CXX) $(CXXSTD) $(CFLAGS) $(WARN) $(INC) \
			examples/vector_fma.cpp libcft.a -o vector-fma-cpp$(EXE) \
			$(XRTLIBS) 2> .out-cpp.err; then \
			echo "c++: $(CXX) FAILED - a build problem, NOT a bit mismatch:"; \
			tail -5 .out-cpp.err; exit 1; \
		fi; \
		./vector-fma-cpp$(EXE) > .out-cpp.txt && \
		diff --strip-trailing-cr .out-c.txt .out-cpp.txt && \
		echo "c++: same library, same bits"; \
	else \
		echo "SKIP c++: no $(CXX) on PATH"; \
	fi

lang-julia: all .out-c.txt
	@if command -v julia >/dev/null 2>&1; then \
		julia examples/vector_fma.jl > .out-jl.txt && \
		diff --strip-trailing-cr .out-c.txt .out-jl.txt && \
		echo "julia: same library, same bits"; \
	else \
		echo "SKIP julia: no julia on PATH"; \
	fi

lang-rust: all .out-c.txt
	@if command -v rustc >/dev/null 2>&1; then \
		rustc --edition 2021 -L native=. examples/vector_fma.rs \
			-o vector-fma-rs$(EXE) && \
		./vector-fma-rs$(EXE) > .out-rs.txt && \
		diff --strip-trailing-cr .out-c.txt .out-rs.txt && \
		echo "rust: same library, same bits"; \
	else \
		echo "SKIP rust: no rustc on PATH"; \
	fi

lang-go: all .out-c.txt
	@if command -v go >/dev/null 2>&1; then \
		go run examples/vector_fma.go > .out-go.txt && \
		diff --strip-trailing-cr .out-c.txt .out-go.txt && \
		echo "go: same library, same bits"; \
	else \
		echo "SKIP go: no go on PATH"; \
	fi

lang-csharp: all .out-c.txt
	@if command -v dotnet >/dev/null 2>&1; then \
		if ! $(DOTNET_ENV) dotnet run --project examples/vector_fma_cs.csproj \
			> .out-cs.txt 2> .out-cs.err; then \
			echo "csharp: dotnet run FAILED - a build or runtime problem, NOT a bit mismatch:"; \
			tail -5 .out-cs.err; exit 1; \
		fi; \
		diff --strip-trailing-cr .out-c.txt .out-cs.txt && \
		echo "csharp: same library, same bits"; \
	else \
		echo "SKIP csharp: no dotnet on PATH"; \
	fi

lang-r: all .out-c.txt
	@if command -v Rscript >/dev/null 2>&1; then \
		Rscript examples/vector_fma.R > .out-r.txt && \
		diff --strip-trailing-cr .out-c.txt .out-r.txt && \
		echo "r: same library, same bits"; \
	else \
		echo "SKIP r: no Rscript on PATH"; \
	fi

lang-fortran: fortran

examples-lang: all lang-cpp lang-julia lang-rust lang-go lang-csharp lang-r
	@rm -f .out-c.txt .out-cpp.txt .out-cpp.err .out-jl.txt .out-rs.txt \
		.out-go.txt .out-cs.txt .out-cs.err .out-r.txt

difftest: all
	$(PYTHON) tests/diff_check.py --trials 3000

# cft_div/cft_sqrt and the seed opcodes against the model: the same
# operand matrix test_sequences.py runs at model level, driven through
# the C port, flags compared per element. Its own target for the same
# reason difftest is - it needs Python and the model. Runs twice: the
# chunk route, then the sequencer-program route forced through the
# software executor (CFT_DIVSQRT_SEQ=1) - the same matrix over the
# route a program-capable device takes.
divsqrttest: all
	$(PYTHON) tests/divsqrt_check.py
	CFT_DIVSQRT_SEQ=1 $(PYTHON) tests/divsqrt_check.py

# The clause-5 completion set against the model: every new entry point
# (rint, scaleb, the conversions, the signaling compares, logB, next,
# class, totalOrder, remainder), per element for exact flags plus the
# chunk-crossing batches. Same shape and reasoning as divsqrttest.
clause5test: all
	$(PYTHON) tests/clause5_check.py

# The native-oracle soak: cft_div/cft_sqrt against the host CPU's own
# IEEE division and square root, which nobody in this repository
# defined. -fno-math-errno keeps sqrt a bare instruction and
# -frounding-math keeps the compiler from folding across fesetround;
# both matter for the oracle to BE the hardware. Driven at scale by
# hw/run-soak.sh; see the tool's header for what it can and cannot
# validate.
divsqrt-soak$(EXE): tools/divsqrt_soak.c libcft.a
	$(CC) $(CSTD) $(CFLAGS) $(WARN) $(INC) -fno-math-errno \
	  -frounding-math tools/divsqrt_soak.c libcft.a -o $@ $(LDLIBS) -lm

# The same oracle, aimed at the clause-5 completion set: rint, scaleb,
# the conversions, logb, next, class and remainder against libm and
# the CPU's own casts. Same flags for the same reasons; C5DEFS is how
# hw/run-c5-soak.sh feeds in its roundeven probe result. Driven at
# scale by that script; the tool's header says which oracle each
# operation gets and why the flags are compared the way they are.
clause5-soak$(EXE): tools/clause5_soak.c libcft.a
	$(CC) $(CSTD) $(CFLAGS) $(WARN) $(INC) -fno-math-errno \
	  -frounding-math $(C5DEFS) tools/clause5_soak.c libcft.a -o $@ \
	  $(LDLIBS) -lm

# Convenience alias for Windows, where the real target carries .exe.
# Guarded: with EXE empty the alias would be a circular self-edge.
ifneq ($(EXE),)
divsqrt-soak: divsqrt-soak$(EXE)
clause5-soak: clause5-soak$(EXE)
mpfr-check: mpfr-check$(EXE)
cft-bench-peers: cft-bench-peers$(EXE)
.PHONY: divsqrt-soak clause5-soak mpfr-check cft-bench-peers
endif

# MPFR parity: the third oracle, and the only independent one that
# reaches fp128/fp256. Needs libmpfr/libgmp (mingw64 carries them as
# gcc dependencies; Linux wants libmpfr-dev). See the tool's header
# for the RMM construction and the flag-derivation policy.
mpfr-check$(EXE): tools/mpfr_check.c libcft.a
	$(CC) $(CSTD) $(CFLAGS) $(WARN) $(INC) tools/mpfr_check.c libcft.a \
	  -o $@ $(LDLIBS) -lmpfr -lgmp -lm

# The software backend priced against the libraries people already
# use: MPFR at matched precision (raw, and emulating the binary format
# by its manual's recipe), __float128 for fp128, the CPU itself for
# fp32/fp64. Same prefix as mpfr-check; -fno-math-errno so the cpu-hw
# rows are the CPU's price, not errno bookkeeping's. The tool's header
# says what each row means and why call shape is part of the price;
# docs/BENCHMARKS.md holds measured numbers.
cft-bench-peers$(EXE): tools/cft_bench_peers.c libcft.a
	$(CC) $(CSTD) $(CFLAGS) $(WARN) $(INC) -fno-math-errno \
	  tools/cft_bench_peers.c libcft.a -o $@ $(LDLIBS) -lmpfr -lgmp \
	  -lquadmath -lm

# The same idea as difftest, for programs rather than arithmetic: two
# independent ports of the sequencer, one in Python and one in C, over
# the same fuzz corpus. It also checks that they REFUSE the same
# programs, because two validators that disagree about what is legal
# are a device executing something the host believed it had rejected.
seqtest: all
	$(PYTHON) tests/seq_check.py --trials 250 \
		--formats fp32 fp64 fp128 fp256

# Reductions are the one place where the two ports have to agree about
# a SHAPE rather than about arithmetic, and a shape that matches on
# powers of two can still diverge on 5. Hence its own target and a
# sweep that covers every small n exhaustively.
reducetest: all
	$(PYTHON) tests/reduce_check.py --trials 1500

coverage: all
	$(PYTHON) tests/diff_check.py --coverage --trials 3000

# Removes every platform's products, not just this one's. A tree on a
# shared volume gets built from more than one platform, and a clean
# that leaves the other platform's shared library behind leaves
# something for a loader to find.
clean:
	rm -f $(OBJ) $(PICOBJ) src/backend_xrt.o src/backend_xrt.lo \
	      libcft.a libcft.dll.a \
	      cft.dll libcft.so libcft.dylib \
	      cft-selftest cft-selftest.exe api-test api-test.exe \
	      cft-bench cft-bench.exe \
	      cft-bench-peers cft-bench-peers.exe \
	      divsqrt-soak divsqrt-soak.exe clause5-soak clause5-soak.exe \
	      mpfr-check mpfr-check.exe \
	      reduce-parts reduce-parts.exe \
	      device-test device-test.exe \
	      cpp-api-test cpp-api-test.exe \
	      cpp-api-test20 cpp-api-test20.exe \
	      vector-fma vector-fma.exe vector-fma-f vector-fma-f.exe \
	      vector-fma-rs vector-fma-rs.exe vector-fma-rs.pdb \
	      vector-fma-go vector-fma-go.exe \
	      vector-fma-cpp vector-fma-cpp.exe \
	      .out-c.txt .out-py.txt .out-cpp.txt .out-cpp.err .out-jl.txt \
	      .out-rs.txt .out-go.txt .out-cs.txt .out-cs.err .out-r.txt
	rm -rf examples/bin examples/obj
