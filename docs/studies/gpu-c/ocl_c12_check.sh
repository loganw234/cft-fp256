#!/bin/bash
# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
#
# ocl_c12_check.sh DEVSRC_DIR     DEVSRC_DIR = a build's devsrc (GPU-A's devcopy output)
# Syntax-only: is the device copy OpenCL C 1.2 (what Apple's deprecated OpenCL takes as text)?
# clang -x cl, target spir64, with a stdint/string shim written to a scratch dir. Two runs: the
# copy as it is, and with three mechanical edits made in a scratch copy: the format table in
# __constant, the identifier `half` (a type in OpenCL C) renamed, and the table's `name` string
# dropped to a __constant char *. Compile only: nothing here runs.
set -u
D=$(realpath "${1:?DEVSRC_DIR}"); CL=${CLANG:-/usr/lib/llvm-22/bin/clang}
T=$(mktemp -d); mkdir -p $T/shim; cd $T
cat > shim/stdint.h <<'EOT'
typedef char int8_t; typedef uchar uint8_t; typedef short int16_t; typedef ushort uint16_t;
typedef int int32_t; typedef uint uint32_t; typedef long int64_t; typedef ulong uint64_t;
#define UINT32_MAX 0xffffffffu
#define UINT64_MAX 0xffffffffffffffffUL
#define INT64_MAX 0x7fffffffffffffffL
#define INT32_MAX 0x7fffffff
EOT
: > shim/stddef.h; : > shim/limits.h
printf 'static inline void *memcpy(void *d, const void *s, size_t n){char *a=d; const char *b=s; while(n--) *a++=*b++; return d;}\nstatic inline void *memset(void *d, int c, size_t n){char *a=d; while(n--) *a++=(char)c; return d;}\n' > shim/string.h
cc12() { (cd "$1/src" && $CL -x cl -cl-std=CL1.2 -target spir64 -fsyntax-only -DCFT_HD= -I$T/shim -I. -I../include "$2" 2>&1 | grep -E "error" | sed 's/.*error: //' | sort | uniq -c | sort -rn); }
echo "== the device copy as it is"
for f in bigint.c softfloat.c; do echo "-- $f"; cc12 "$D" $f; done
cp -r "$D" $T/mod; cd $T/mod/src
sed -i 's/^extern const cft_fmt_desc cft_sf_formats/extern __constant const cft_fmt_desc cft_sf_formats/' softfloat.h
sed -i 's/^const cft_fmt_desc cft_sf_formats/__constant const cft_fmt_desc cft_sf_formats/; s/\bhalf\b/hlf/g' softfloat.c
echo "== after the table in __constant and half renamed"; cc12 $T/mod softfloat.c
sed -i 's/const char \*name;/__constant const char *name;/' softfloat.h
echo "== and the table's name field __constant"; cc12 $T/mod softfloat.c; echo "(no lines above = no errors)"
rm -rf $T
