#!/bin/bash
# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
#
# eval_order.sh - does the soak tools' operand stream depend on the compiler?
#
# host/tools/divsqrt_soak.c and clause5_soak.c draw a banded exponent with
#     e = bands[rng() % 7] + (rng() % 3);
# two calls of rng() in one expression. C leaves the order of evaluation of the two
# operands of `+` unspecified, so a compiler may draw either first and the SAME seed
# then gives different operands. This builds divsqrt-soak from this tree's source with
# several compilers and optimization levels (the Makefile's own flags otherwise: -std=c99
# -Wall -Wextra -Wpedantic -Wshadow -Iinclude -fno-math-errno -frounding-math, linked
# against the tree's libcft.a) and prints the first lanes of div32, div64 and sqrt64 for
# several seeds under the tool's sabotage control, as tool_probe.sh does.
# seed_audit.py reads the output and says which order each build used.
#
#   usage: bash eval_order.sh HOSTDIR WORK
#          HOSTDIR  host/ of a tree whose libcft.a is built (make -C host divsqrt-soak)
#          WORK     a new or empty scratch directory (written; the caller removes it)
#
# Output: for each build "BUILD <name>" then OPERANDS lines (as tool_probe.out's).

set -u
H=${1:?usage: bash eval_order.sh HOSTDIR WORK}
W=${2:?usage: bash eval_order.sh HOSTDIR WORK}
mkdir -p "$W"
[ -f "$H/libcft.a" ] || { echo "no libcft.a in $H (build divsqrt-soak first)" >&2; exit 2; }

operands() {   # operands BIN OP SEED
  local bin=$1 op=$2 seed=$3
  CFT_SOAK_SABOTAGE=1 nice -n 10 "$bin" "$op" 4096 "$seed" rne 2>/dev/null |
    awk -v op="$op" -v seed="$seed" '
      /^  MISMATCH/ { n++;
        f = "";
        for (i = 2; i <= NF; i++) if ($i ~ /^[ab]=/) f = f " " $i;
        printf "OPERANDS %s %s rne %d%s\n", op, seed, n - 1, f }'
}

build_and_probe() {   # build_and_probe NAME CC OPT
  local name=$1 cc=$2 opt=$3
  if ! command -v "$cc" > /dev/null 2>&1; then
    echo "BUILD $name: compiler $cc not found; skipped"
    return
  fi
  ( cd "$H" && "$cc" -std=c99 "$opt" -Wall -Wextra -Wpedantic -Wshadow -Iinclude \
      -fno-math-errno -frounding-math tools/divsqrt_soak.c libcft.a -o "$W/ds-$name" -lm ) \
    > "$W/build-$name.log" 2>&1 || { echo "BUILD $name: FAILED (see build log)"; return; }
  echo "BUILD $name: $("$cc" --version | head -1)  $opt"
  for op in div32 div64 sqrt64; do
    for seed in 0x50AC0001 0x50AC1F20 0x50AC0007; do
      operands "$W/ds-$name" "$op" "$seed" | sed "s/^OPERANDS /OPERANDS [$name] /"
    done
  done
}

build_and_probe gcc11-O0 gcc-11 -O0
build_and_probe gcc11-O1 gcc-11 -O1
build_and_probe gcc11-O2 gcc-11 -O2
build_and_probe gcc11-O3 gcc-11 -O3
build_and_probe gcc12-O0 gcc-12 -O0
build_and_probe gcc12-O2 gcc-12 -O2
build_and_probe gcc12-O3 gcc-12 -O3
