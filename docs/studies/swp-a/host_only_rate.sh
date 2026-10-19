#!/bin/bash
# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
#
# host_only_rate.sh - how much of a soak job's time is the HOST side?
#
# host/tools/divsqrt_soak.c generates the operands (banded32/banded64), computes the oracle
# natively (the CPU's SSE division or square root) and compares it with the library's answer.
# On the card the library's answer comes from the tile. Here a SCRATCH COPY of the tool has
# lib_call() replaced by the native computation itself, so every case matches and no device
# or softfloat is involved: what is left is operand generation, ONE native oracle pass, ONE
# native pass standing in for the library, flag capture and the comparison. That is an UPPER
# bound on the host side of a real job (the real job has one native pass, not two) and so a
# LOWER bound on the rate the host side alone would allow. sw_rates.out and the card's
# per-job medians are the other columns of the study's comparison.
#
#   usage: bash host_only_rate.sh HOSTDIR WORK
#          HOSTDIR  host/ of the tree (read only); WORK a new scratch directory (written)

set -u
H=${1:?usage: bash host_only_rate.sh HOSTDIR WORK}
W=${2:?usage: bash host_only_rate.sh HOSTDIR WORK}
mkdir -p "$W"
cp "$H/tools/divsqrt_soak.c" "$W/divsqrt_soak_native.c"

# Replace the body of lib_call: native computation, flags captured the way native_batch does.
python3 - "$W/divsqrt_soak_native.c" <<'PYEOF'
import re, sys
p = sys.argv[1]
s = open(p, encoding="utf-8").read()
start = s.index("static cft_status lib_call(")
end = s.index("static void report32(")
new = r'''static cft_status lib_call(soak_op op, cft_round cr, const uint8_t *a,
                           const uint8_t *b, uint8_t *d, size_t n,
                           uint32_t *fl)
{
    size_t i;
    int ex;
    (void)cr;
    fesetround(FE_TONEAREST);
    feclearexcept(FE_ALL_EXCEPT);
    switch (op) {
    case OP_DIV32:
        for (i = 0; i < n; i++)
            ((uint32_t *)(void *)d)[i] = f2u(u2f(((const uint32_t *)(const void *)a)[i]) /
                                              u2f(((const uint32_t *)(const void *)b)[i]));
        break;
    case OP_DIV64:
        for (i = 0; i < n; i++)
            ((uint64_t *)(void *)d)[i] = d2u(u2d(((const uint64_t *)(const void *)a)[i]) /
                                              u2d(((const uint64_t *)(const void *)b)[i]));
        break;
    case OP_SQRT32:
        for (i = 0; i < n; i++)
            ((uint32_t *)(void *)d)[i] = f2u(sqrtf(u2f(((const uint32_t *)(const void *)a)[i])));
        break;
    case OP_SQRT64:
        for (i = 0; i < n; i++)
            ((uint64_t *)(void *)d)[i] = d2u(sqrt(u2d(((const uint64_t *)(const void *)a)[i])));
        break;
    }
    ex = fetestexcept(FE_ALL_EXCEPT);
    *fl = fe_to_cft(ex);
    return CFT_OK;
}

'''
s = s[:start] + new + s[end:]
open(p, "w", encoding="utf-8").write(s)
print("lib_call replaced by the native computation")
PYEOF

( cd "$H" && cc -std=c99 -O2 -Wall -Iinclude -fno-math-errno -frounding-math "$W/divsqrt_soak_native.c" libcft.a -o "$W/ds-native" -lm ) \
  > "$W/build.log" 2>&1 || { echo "BUILD FAILED"; tail -5 "$W/build.log"; exit 2; }
echo "built a divsqrt-soak whose library call is the native computation (no device, no softfloat)"

run() {   # run NAME OP COUNT
  local name=$1 op=$2 count=$3 t0 t1 out
  t0=$(date +%s.%N)
  out=$(nice -n 10 "$W/ds-native" "$op" "$count" 7 rne 2>&1); local rc=$?
  t1=$(date +%s.%N)
  printf 'HOSTONLY %-8s count=%s seconds=%s rate=%s rc=%s  %s\n' "$name" "$count" \
    "$(awk -v a="$t0" -v b="$t1" 'BEGIN { printf "%.3f", b - a }')" \
    "$(awk -v a="$t0" -v b="$t1" -v c="$count" 'BEGIN { printf "%.0f", c / (b - a) }')" "$rc" \
    "$(printf '%s' "$out" | tail -1)"
}
run div32  div32  40000000
run div64  div64  40000000
run sqrt64 sqrt64 40000000
