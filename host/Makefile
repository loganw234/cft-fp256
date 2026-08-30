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
# The shared library is what the ctypes, Julia and Fortran callers
# load; the static one is for embedding.

CC      ?= cc
AR      ?= ar
PYTHON  ?= python3
CFLAGS  ?= -O2
CSTD    := -std=c99
WARN    := -Wall -Wextra -Wpedantic -Wshadow
INC     := -Iinclude

SRC     := src/bigint.c src/softfloat.c src/device.c src/conformance.c
OBJ     := $(SRC:.c=.o)
PICOBJ  := $(SRC:.c=.lo)

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

TOOLS := cft-selftest$(EXE)
TESTS := api-test$(EXE)
EXAMPLES := vector-fma$(EXE)

.PHONY: all test difftest coverage fortran clean

all: libcft.a $(SHLIB) $(TOOLS) $(EXAMPLES)

%.o: %.c
	$(CC) $(CSTD) $(CFLAGS) $(WARN) $(INC) -c $< -o $@

%.lo: %.c
	$(CC) $(CSTD) $(CFLAGS) $(WARN) $(INC) $(PIC) $(SHDEF) -c $< -o $@

libcft.a: $(OBJ)
	$(AR) rcs $@ $^

$(SHLIB): $(PICOBJ)
	$(CC) $(SHFLAGS) -o $@ $^

cft-selftest$(EXE): tools/cft_selftest.c libcft.a
	$(CC) $(CSTD) $(CFLAGS) $(WARN) $(INC) $^ -o $@

api-test$(EXE): tests/api_test.c libcft.a
	$(CC) $(CSTD) $(CFLAGS) $(WARN) $(INC) $^ -o $@

vector-fma$(EXE): examples/vector_fma.c libcft.a
	$(CC) $(CSTD) $(CFLAGS) $(WARN) $(INC) $^ -o $@

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
	./cft-selftest$(EXE) ../vectors/out
	./vector-fma$(EXE) > .out-c.txt
	$(PYTHON) examples/vector_fma_ctypes.py > .out-py.txt
	diff .out-c.txt .out-py.txt
	@echo "C and Python reached the same library and got the same bits"
	@rm -f .out-c.txt .out-py.txt

# The Fortran example is the one artifact here that has not been run -
# see its header. This target is what changes that, on any machine
# with a Fortran compiler.
FC ?= gfortran
fortran: libcft.a
	$(FC) examples/vector_fma.f90 libcft.a -o vector-fma-f$(EXE)
	./vector-fma-f$(EXE)

difftest: all
	$(PYTHON) tests/diff_check.py --trials 3000

coverage: all
	$(PYTHON) tests/diff_check.py --coverage --trials 3000

# Removes every platform's products, not just this one's. A tree on a
# shared volume gets built from more than one platform, and a clean
# that leaves the other platform's shared library behind leaves
# something for a loader to find.
clean:
	rm -f $(OBJ) $(PICOBJ) libcft.a libcft.dll.a \
	      cft.dll libcft.so libcft.dylib \
	      cft-selftest cft-selftest.exe api-test api-test.exe \
	      vector-fma vector-fma.exe vector-fma-f vector-fma-f.exe \
	      .out-c.txt .out-py.txt
