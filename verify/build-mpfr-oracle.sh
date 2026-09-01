#!/usr/bin/env bash
# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
#
# Build the MPFR oracle's libraries from source, into a prefix this
# repo owns - so the third oracle runs on hosts with no libmpfr-dev
# and no root, exactly the situation amd-arc-box turned out to be in
# when the clause-5 MPFR campaign needed it (2026-09-01; the recipe
# below is that campaign's, promoted to a script).
#
#   bash verify/build-mpfr-oracle.sh              # into verify/_mpfr-prefix
#   PREFIX=/somewhere bash verify/build-mpfr-oracle.sh
#   CHECK=0 ...                                   # skip upstream test suites
#
# verify/run.sh's mpfr stage auto-detects the default prefix; by hand:
#
#   make -C host mpfr-check CFLAGS="-O2 -I$PREFIX/include" \
#                           LDLIBS="-L$PREFIX/lib"
#
# Everything is pinned and verified: versions AND SHA-256, measured
# from the artifacts whose upstream `make check` suites ran green on
# the campaign box. Static libraries only, so the resulting mpfr-check
# binary carries its oracle with it. Nothing is installed outside
# $PREFIX; sudo is never used.

set -eu

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PREFIX="${PREFIX:-$ROOT/verify/_mpfr-prefix}"
WORK="${WORK:-$PREFIX-build}"
CHECK="${CHECK:-1}"
JOBS="${JOBS:-4}"

M4_V=1.4.19
GMP_V=6.3.0
MPFR_V=4.2.2
M4_SHA=63aede5c6d33b6d9b13511cd0be2cac046f2e70fd0a07aa9573a04a82783af96
GMP_SHA=a3c2b80201b89e68616f4ad30bc66aee4927c3ce50e33929ca819d5c43538898
MPFR_SHA=b67ba0383ef7e8a8563734e2e889ef5ec3c3b898a01d00fa0a6869ad81c6ce01

if [ -f "$PREFIX/include/mpfr.h" ] && [ -f "$PREFIX/lib/libmpfr.a" ]; then
  echo "== $PREFIX already holds mpfr.h and libmpfr.a - nothing to do."
  echo "   (remove the prefix to force a rebuild)"
  exit 0
fi

mkdir -p "$PREFIX" "$WORK"
cd "$WORK"

fetch() {  # <url> <file> <sha256>
  if [ ! -f "$2" ]; then
    echo "== fetching $2"
    if command -v curl >/dev/null 2>&1; then
      curl -fsSL -o "$2.part" "$1"
    elif command -v wget >/dev/null 2>&1; then
      wget -q -O "$2.part" "$1"
    else
      # The sim container has python3 but neither curl nor wget; the
      # SHA-256 gate below is the integrity check either way.
      python3 -c 'import sys, urllib.request as u; u.urlretrieve(sys.argv[1], sys.argv[2])' \
        "$1" "$2.part"
    fi
    mv "$2.part" "$2"
  fi
  echo "$3  $2" | sha256sum -c - || {
    echo "SHA-256 MISMATCH for $2 - refusing to build from it." >&2
    exit 1
  }
}

# m4 only if the host lacks one (GMP's configure needs it).
if ! command -v m4 >/dev/null 2>&1; then
  fetch "https://ftp.gnu.org/gnu/m4/m4-$M4_V.tar.xz" \
        "m4-$M4_V.tar.xz" "$M4_SHA"
  tar xf "m4-$M4_V.tar.xz"
  (cd "m4-$M4_V" && ./configure --prefix="$PREFIX" >/dev/null &&
     make -j"$JOBS" >/dev/null && make install >/dev/null)
  export PATH="$PREFIX/bin:$PATH"
  echo "== m4 $M4_V built (host had none)"
fi

fetch "https://ftp.gnu.org/gnu/gmp/gmp-$GMP_V.tar.xz" \
      "gmp-$GMP_V.tar.xz" "$GMP_SHA"
tar xf "gmp-$GMP_V.tar.xz"
(cd "gmp-$GMP_V" &&
   ./configure --prefix="$PREFIX" --disable-shared --enable-static \
     >/dev/null &&
   make -j"$JOBS" >/dev/null)
if [ "$CHECK" = 1 ]; then
  echo "== gmp $GMP_V: running the upstream test suite (CHECK=0 skips)"
  (cd "gmp-$GMP_V" && make check >/dev/null)
fi
(cd "gmp-$GMP_V" && make install >/dev/null)
echo "== gmp $GMP_V installed"

fetch "https://ftp.gnu.org/gnu/mpfr/mpfr-$MPFR_V.tar.xz" \
      "mpfr-$MPFR_V.tar.xz" "$MPFR_SHA"
tar xf "mpfr-$MPFR_V.tar.xz"
(cd "mpfr-$MPFR_V" &&
   ./configure --prefix="$PREFIX" --with-gmp="$PREFIX" \
     --disable-shared --enable-static >/dev/null &&
   make -j"$JOBS" >/dev/null)
if [ "$CHECK" = 1 ]; then
  echo "== mpfr $MPFR_V: running the upstream test suite"
  (cd "mpfr-$MPFR_V" && make check >/dev/null)
fi
(cd "mpfr-$MPFR_V" && make install >/dev/null)
echo "== mpfr $MPFR_V installed"

echo
echo "== done. The oracle libraries live under:"
echo "     $PREFIX"
echo "   verify/run.sh's mpfr stage will find this prefix by itself;"
echo "   by hand:"
echo "     make -C host mpfr-check CFLAGS=\"-O2 -I$PREFIX/include\" \\"
echo "                             LDLIBS=\"-L$PREFIX/lib\""
echo "   The build tree ($WORK) can be deleted."
