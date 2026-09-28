#!/bin/sh
# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
#
# The build id regenerated, and watched doing it (cft.h, cft_build_id).
#
#   make -C host buildidtest         (make test runs it; CC, MAKE, GIT,
#                                     EXE and OS come from the Makefile)
#
# A build id is only worth carrying if it is the id of the tree the
# build ran in. The ways it could stop being that are all in the build,
# not in the C, so this drives the real build: THIS tree's Makefile,
# tools/gen_build_id.sh, src/build_id.c, cft.h and .gitignore, copied
# into scratch repositories of its own - never this tree, which it must
# not edit - and `make src/build_id.o src/build_id.lo` in each. Each
# object is linked into a four-line program that prints cft_build_id(),
# so what is checked is the id the library returns, from both the
# static archive's object and the shared library's.
#
# What each step would catch, were it broken:
#   clean       the id's grammar, and the commit being HEAD's
#   again       the header rewritten, or the object recompiled, with
#               nothing changed (every make relinking everything)
#   own output  the build's own files counted as untracked - the
#               generated header or an object not ignored - which would
#               mark every second build dirty
#   edited      the generator not re-run (a header with no phony
#               prerequisite), the object not depending on the header,
#               or tracked edits not counted
#   untracked   `git diff` in place of `git status --untracked-files`
#   reverted, a new commit
#               an id that sticks after the tree moves on
#   no repository, inside another repository, no git
#               "unknown", and never a guess: a copy vendored inside
#               another project must not take that project's commit
#
# Output: one line per check, "ok" or "FAIL", then a count; the exit
# status is the count of failures, capped at 1. With no git at all the
# check cannot build a repository, and says so on a SKIP line - which
# verify/run.sh counts as a skipped check, not a pass.

set -u
CC=${CC:-cc}
MAKE=${MAKE:-make}
GIT=${GIT:-git}
EXE=${EXE:-}
# The sub-makes are this script's, not the caller's: its -j jobserver,
# -k, -s and command-line variables do not apply to them. CC, GIT and OS
# are handed over explicitly instead.
unset MAKEFLAGS MFLAGS MAKELEVEL GNUMAKEFLAGS

HOST=$(cd "$(dirname "$0")/.." && pwd)
REPO=$(cd "$HOST/.." && pwd)

checks=0
failed=0
ok()  { checks=$((checks + 1)); echo "  ok    $*"; }
bad() { checks=$((checks + 1)); failed=$((failed + 1)); echo "  FAIL  $*"; }

if ! command -v "$GIT" >/dev/null 2>&1; then
    echo "SKIP build-id regeneration check: no git ($GIT) to build its scratch repositories with"
    exit 0
fi

T=$(mktemp -d "${TMPDIR:-/tmp}/cft-build-id.XXXXXX") || exit 1
# On Windows the shell running this (make's /bin/sh, MSYS2's) and the
# mktemp found on PATH (Git's) can be two MSYS runtimes that mean two
# different directories by /tmp - measured on the desktop, 2026-09-28:
# the directory mktemp made was not there for the next line. Its
# drive-letter form means the same place to both and to the native
# compiler, so it is taken from the cygpath beside that mktemp.
if command -v cygpath >/dev/null 2>&1; then
    T=$(cygpath -m "$T")
fi
[ -d "$T" ] || { echo "  FAIL  the scratch directory $T is not visible to this shell"; exit 1; }
trap 'rm -rf "$T"' EXIT
trap 'rm -rf "$T"; exit 1' INT TERM

# Hermetic git for the scratch repositories: the caller's global and
# system configuration - signing, hooks, templates, status settings -
# neither applies to them nor steers what the generator sees.
: > "$T/gitconfig"
GIT_CONFIG_GLOBAL="$T/gitconfig"
GIT_CONFIG_NOSYSTEM=1
export GIT_CONFIG_GLOBAL GIT_CONFIG_NOSYSTEM
g() { "$GIT" -c user.name=cft-build-id-check -c user.email=check@invalid "$@"; }

cat > "$T/print.c" <<'EOF'
#include <stdio.h>
#include "cft.h"
int main(void) { puts(cft_build_id()); return 0; }
EOF

# The files the id's build needs, from THIS tree, into $1.
mk_tree() {
    mkdir -p "$1/host/src" "$1/host/include" "$1/host/tools" || return 1
    cp "$REPO/.gitignore" "$1/" &&
    cp "$HOST/Makefile" "$1/host/" &&
    cp "$HOST/tools/gen_build_id.sh" "$1/host/tools/" &&
    cp "$HOST/src/build_id.c" "$1/host/src/" &&
    cp "$HOST/include/cft.h" "$HOST/include/cft_config.h" "$1/host/include/" &&
    printf 'a tracked file this check edits\n' > "$1/README.md"
}

# Build both objects in the tree at $1 and print the id each carries,
# one line each; any failure prints the log and returns 1.
ids() {
    if ! (cd "$1/host" && "$MAKE" --no-print-directory CC="$CC" \
              GIT="$GIT" ${OS:+OS="$OS"} src/build_id.o src/build_id.lo) \
            > "$T/make.log" 2>&1; then
        sed 's/^/        /' "$T/make.log" >&2
        return 1
    fi
    for o in o lo; do
        rm -f "$T/print$EXE"
        "$CC" -I"$1/host/include" "$T/print.c" "$1/host/src/build_id.$o" \
              -o "$T/print$EXE" > "$T/cc.log" 2>&1 &&
            "$T/print$EXE" | tr -d '\r' || {
                sed 's/^/        /' "$T/cc.log" >&2
                return 1
            }
    done
}

# $1 tree, $2 the id both objects must carry, $3 what the step is.
expect() {
    got=$(ids "$1") || { bad "$3: the build failed"; return; }
    want=$(printf '%s\n%s' "$2" "$2")
    if [ "$got" = "$want" ]; then
        ok "$3: $2"
    else
        bad "$3: wanted $2 from build_id.o and build_id.lo, got: $(echo $got)"
    fi
}

# Ages every input and output of the id's build to 2000, then says which
# of the three outputs a build since has written: a file newer than the
# year-2001 marker was rewritten. The inputs are aged too, or the objects
# would be older than cft.h and recompiled for that reason alone - and
# equal times are up to date to make.
age() {
    touch -t 200001010000 "$1/host/src/build_id.c" \
          "$1/host/include/cft.h" "$1/host/include/cft_config.h" \
          "$1/host/gen/cft_build_id.h" \
          "$1/host/src/build_id.o" "$1/host/src/build_id.lo"
}
touch -t 200101010000 "$T/y2001"
written() {
    w=
    for f in gen/cft_build_id.h src/build_id.o src/build_id.lo; do
        [ -n "$(find "$1/host/$f" -newer "$T/y2001" 2>/dev/null)" ] && w="$w $f"
    done
    echo "${w# }"
}

echo "build id: regenerated on every build, in scratch repositories under $T"

# 1. A clean commit.
A="$T/a"
mk_tree "$A" && g init -q "$A" && g -C "$A" add -A &&
    g -C "$A" commit -q -m "a clean commit" || { echo "  FAIL  could not make the scratch repository"; exit 1; }
head=$(g -C "$A" rev-parse HEAD)
expect "$A" "commit=$head tracked=clean untracked=none" "a clean commit"

# The header is outside src/ and include/, which sync.py vendors whole.
stray=$(cd "$A/host" && ls src include | grep -v -x -e 'src:' -e 'include:' \
          -e '' -e build_id.c -e build_id.o -e build_id.lo -e cft.h \
          -e cft_config.h)
if [ -f "$A/host/gen/cft_build_id.h" ] && [ -z "$stray" ]; then
    ok "the header is host/gen/cft_build_id.h, and src/ and include/ gained no source or header"
else
    bad "the header is not where it belongs, or src/ or include/ gained: $stray"
fi

# 2. Built again with nothing changed: nothing rewritten, nothing rebuilt.
age "$A"
expect "$A" "commit=$head tracked=clean untracked=none" "the same tree again"
w=$(written "$A")
if [ -z "$w" ]; then
    ok "the same tree again: the header was not rewritten and neither object was recompiled"
else
    bad "the same tree again rewrote or recompiled: $w"
fi

# 3. The build's own output is not dirt.
st=$(g -C "$A" status --porcelain --untracked-files=all)
if [ -z "$st" ]; then
    ok "the build's own output (host/gen/, the objects) is ignored: git status is empty"
else
    bad "the build left files git counts, which make the next id dirty: $(echo $st)"
fi

# 4. A tracked file edited: re-run, rewritten, recompiled.
age "$A"
printf 'an edit\n' >> "$A/README.md"
expect "$A" "commit=$head tracked=modified untracked=none" "a tracked file edited"
w=$(written "$A")
if [ "$w" = "gen/cft_build_id.h src/build_id.o src/build_id.lo" ]; then
    ok "a tracked file edited: the header was rewritten and both objects recompiled"
else
    bad "a tracked file edited: wanted the header and both objects rewritten, got: ${w:-nothing}"
fi

# 5. Reverted: clean again.
g -C "$A" checkout -q -- README.md
expect "$A" "commit=$head tracked=clean untracked=none" "the edit reverted"

# 6. An untracked file, which git diff would not see.
printf 'nobody added this\n' > "$A/host/src/stray.c"
expect "$A" "commit=$head tracked=clean untracked=present" "an untracked source"

# 7. Both at once.
printf 'an edit\n' >> "$A/README.md"
expect "$A" "commit=$head tracked=modified untracked=present" "an edit and an untracked file"
g -C "$A" checkout -q -- README.md
rm -f "$A/host/src/stray.c"

# 8. A new commit: the id follows HEAD.
printf 'a second commit\n' >> "$A/README.md"
g -C "$A" commit -q -a -m "a second commit"
head2=$(g -C "$A" rev-parse HEAD)
expect "$A" "commit=$head2 tracked=clean untracked=none" "a new commit"

# 9. No repository: the same files, no .git.
B="$T/b"
mk_tree "$B"
expect "$B" "unknown" "no repository at all"
grep -q '^/\* unknown because: ' "$B/host/gen/cft_build_id.h" &&
    ok "no repository: the header says why" ||
    bad "no repository: the header does not say why"

# 10. Inside another project's repository, which must not lend its commit.
C="$T/outer"
mkdir -p "$C/vendor/cft" && mk_tree "$C/vendor/cft" && g init -q "$C" &&
    g -C "$C" add -A && g -C "$C" commit -q -m "another project"
expect "$C/vendor/cft" "unknown" "a copy inside another repository"
grep -q 'not the top of its repository' "$C/vendor/cft/host/gen/cft_build_id.h" &&
    ok "inside another repository: the header says so" ||
    bad "inside another repository: the header does not say so"

# 11. No git.
GIT_KEEP=$GIT
GIT=cft-no-such-git
expect "$A" "unknown" "no git"
GIT=$GIT_KEEP
expect "$A" "commit=$head2 tracked=clean untracked=none" "git back"

echo "buildidtest: $checks checks, $failed failed"
[ "$failed" -eq 0 ]
