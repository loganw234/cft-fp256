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
# The shared library is what the ctypes, Julia and Fortran callers
# load; the static one is for embedding.

CC      ?= cc
CXX     ?= g++
AR      ?= ar
PYTHON  ?= python3
CFLAGS  ?= -O2
CSTD    := -std=c99
CXXSTD  := -std=c++17
WARN    := -Wall -Wextra -Wpedantic -Wshadow
INC     := -Iinclude

SRC     := src/bigint.c src/softfloat.c src/device.c src/divsqrt.c \
           src/program.c src/conformance.c
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
else
  SHLIB   := libcft.so
  SHFLAGS := -shared
  SHDEF   :=
  PIC     := -fPIC -fvisibility=hidden
  EXE     :=
endif

TOOLS := cft-selftest$(EXE) cft-bench$(EXE)
TESTS := api-test$(EXE) reduce-parts$(EXE)
EXAMPLES := vector-fma$(EXE)

.PHONY: all test difftest seqtest reducetest coverage fortran clean

all: libcft.a $(SHLIB) $(TOOLS) $(EXAMPLES)

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
#                   ABI is not doing its job
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

difftest: all
	$(PYTHON) tests/diff_check.py --trials 3000

# cft_div/cft_sqrt and the seed opcodes against the model: the same
# operand matrix test_sequences.py runs at model level, driven through
# the C port, flags compared per element. Its own target for the same
# reason difftest is - it needs Python and the model.
divsqrttest: all
	$(PYTHON) tests/divsqrt_check.py

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

divsqrt-soak: divsqrt-soak$(EXE)
.PHONY: divsqrt-soak

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
	      reduce-parts reduce-parts.exe \
	      device-test device-test.exe \
	      vector-fma vector-fma.exe vector-fma-f vector-fma-f.exe \
	      .out-c.txt .out-py.txt
