# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
#
# cft-replay-loopback - the board's replay responder, as a host process.
#
#   make                 all four profiles
#   make full            everything, as the RP2040 and the ESP32 carry it
#   make tiny            CFT_TINY: fp32 and fp64, as the Uno/Nano carry it
#   make tiny128         CFT_TINY at fp128, as the Mega is measured at
#   make CC=clang        or any other C99 compiler
#
# It compiles the VENDORED sources - ../cft-arduino/src/cft - and not
# host/src, deliberately. Those are the bytes an Arduino build puts on
# the part, vendor.json records their hashes, and a loopback run that
# used host/src instead would be checking a copy of the library that no
# board ever runs. `sync.py --check` is what ties the two together;
# this is what exercises the end of the chain.
#
# On Windows, build with the mingw64 toolchain and the same PATH the
# rest of this repository's host targets use:
#
#   PATH="/c/msys64/mingw64/bin:$PATH" make -C bindings/arduino/loopback CC=gcc

CC      ?= cc
CFLAGS  ?= -O2
CSTD    := -std=c99
WARN    := -Wall -Wextra -Wpedantic -Wshadow

LIB     := ../cft-arduino
INC     := -I$(LIB)/src -I$(LIB)/src/cft/include

ifeq ($(OS),Windows_NT)
  EXE := .exe
else
  EXE :=
endif

# Every .c the Arduino build would compile, minus the ones under
# src/remote (the remote client's, not ours) - the same set, so a
# link failure here is a link failure there.
LIBSRC := $(wildcard $(LIB)/src/cft/src/*.c) $(LIB)/src/cft_replay.c
SRC    := $(LIBSRC) main.c

# The profiles, named the way docs/EMBEDDED.md names them.
DEF_full    :=
DEF_tiny    := -DCFT_TINY
DEF_tiny128 := -DCFT_TINY -DCFT_MAX_FORMAT=2
# The 32-bit boards do carry everything, but never the socket backend
# and never the file-reading conformance replay: there is no Berkeley
# socket layer on a Pico and no directory of vector sets on either.
DEF_board   := -DCFT_NO_REMOTE -DCFT_NO_CONFORMANCE

PROFILES := full tiny tiny128 board

all: $(addprefix cft-replay-loopback-,$(PROFILES))
	@echo "built: $(addsuffix $(EXE),$(addprefix cft-replay-loopback-,$(PROFILES)))"

# One rule per profile rather than a pattern rule with a lookup,
# because $(DEF_$*) inside a pattern rule is evaluated before $* is
# bound on some makes and silently builds every profile with no
# defines at all - which would have made the tiny loopback a second
# copy of the full one, passing for the wrong reason.
define PROFILE_rule
cft-replay-loopback-$(1)$(EXE): $$(SRC)
	$$(CC) $$(CSTD) $$(CFLAGS) $$(WARN) $$(INC) $$(DEF_$(1)) $$^ -o $$@
$(1): cft-replay-loopback-$(1)$(EXE)
.PHONY: $(1)
endef
$(foreach p,$(PROFILES),$(eval $(call PROFILE_rule,$(p))))

clean:
	rm -f cft-replay-loopback-* *.o

.PHONY: all clean
