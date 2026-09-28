#!/bin/sh
# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
#
# The build id compiled into libcft: which source tree a build came
# from (cft.h, cft_build_id).
#
#   sh tools/gen_build_id.sh <out.h> [repository-root]   write the header
#   sh tools/gen_build_id.sh --print [repository-root]   print the id
#
# host/Makefile runs the first form on every make that builds libcft or
# anything linking it - the header's prerequisite is a phony target - and
# this rewrites <out.h> only when the id it computes differs from the one
# already there. make re-reads the header's time after the recipe, so an
# unchanged tree rebuilds nothing,
# and a changed one recompiles src/build_id.o, re-archives libcft.a and
# relinks whatever links it. A binary built by this Makefile therefore
# never carries the id of an earlier tree. The second form is what
# `make print-build-id` and `make test` ask.
#
# The repository root defaults to `..`: the directory above host/, which
# is where this file's own repository keeps it. Run from host/.
#
# The id is one line in one of exactly two forms:
#
#   commit=<40 lowercase hex> tracked=<clean|modified> untracked=<none|present>
#   unknown
#
# (64 hex digits in a repository that uses SHA-256 object names.)
#
# `tracked=modified` is any line of `git status --porcelain` that is not
# an untracked file: an edit, a staged change, a deletion, a rename.
# `untracked=present` is any untracked file git does not ignore. It is
# `git status --untracked-files=all` and NOT `git diff`, for the reason
# hw/rebuild-2022.sh gives at length: git diff sees tracked files only,
# and a new source nobody added compiles in as easily as an edited one.
# Here the copy is bindings/arduino/sync.py, which vendors every file in
# host/src and host/include, tracked or not.
#
# `unknown`, whole, whenever any of the three cannot be measured:
#   - no git on PATH (or at $GIT);
#   - the root is in no repository: a source tarball, a copy;
#   - the root is not the TOP of its repository: a copy vendored inside
#     another project's repository, whose commit names that project's
#     tree and not this one;
#   - git answers with an error, or with a commit name that is not 40 or
#     64 lowercase hex digits;
#   - git status writes ANYTHING to stderr, even with a zero exit: a
#     directory it could not open is a directory whose untracked files
#     it did not count, and a warning parsed as porcelain would have
#     read as a modification.
# The reason goes into the header as a comment and onto make's output,
# never into the id: the id is a value a certificate carries, and the
# reason is for the person reading a build log.
#
# git runs with --no-optional-locks, so a make never takes the index lock
# from a git command someone else is running, and with the environment's
# GIT_DIR, GIT_WORK_TREE and GIT_INDEX_FILE unset, so the repository
# asked is the one the root is in and not whichever one a hook or a
# wrapper pointed git at.

set -u

GIT=${GIT:-git}
unset GIT_DIR GIT_WORK_TREE GIT_INDEX_FILE GIT_OBJECT_DIRECTORY \
      GIT_COMMON_DIR GIT_NAMESPACE 2>/dev/null

usage() {
    echo "usage: gen_build_id.sh <out.h> [repository-root]" >&2
    echo "       gen_build_id.sh --print [repository-root]" >&2
    exit 2
}

[ $# -ge 1 ] || usage
out=$1
root=${2:-..}

id=unknown
why=

# The first line, and nothing that could close the C comment it will sit
# in or break the make log it will be printed to: no `*`, no quote marks,
# no backslash. Applied to a git message and again to the whole reason,
# since the reason also carries the root's path.
tidy() {
    printf '%s' "$1" | head -n 1 | tr -cd "A-Za-z0-9 ._,:;/()=+@'-" |
        cut -c 1-${2:-200}
}

# git status's stderr goes to a file of its own: it must be SEEN (a
# warning makes the id unknown) and never read as porcelain.
errf="${TMPDIR:-/tmp}/gen_build_id.$$.err"
status=
serr=
srun() {
    status=$("$GIT" -C "$root" --no-optional-locks status --porcelain \
             --untracked-files=all 2>"$errf")
    s_rc=$?
    serr=$(cat "$errf" 2>/dev/null)
    rm -f "$errf"
    [ "$s_rc" -eq 0 ] && [ -z "$serr" ]
}

if ! command -v "$GIT" >/dev/null 2>&1; then
    why="no git on PATH ($GIT)"
elif ! cdup=$("$GIT" -C "$root" rev-parse --show-cdup 2>&1); then
    why="git cannot place $root in a work tree: $(tidy "$cdup")"
elif [ -n "$cdup" ]; then
    why="$root is not the top of its repository (git says the top is $(tidy "$cdup") above it): a copy inside another project's repository, whose commit is not this tree's"
elif ! commit=$("$GIT" -C "$root" rev-parse --verify --quiet 'HEAD^{commit}' 2>/dev/null); then
    why="$root has no commit checked out"
elif ! srun; then
    why="git status in $root did not answer cleanly: $(tidy "${serr:-exit status $s_rc}")"
else
    case ${#commit} in
        40|64) ;;
        *) commit= ;;
    esac
    case $commit in
        ''|*[!0-9a-f]*)
            why="git named the commit in a form that is not 40 or 64 lowercase hex digits" ;;
        *)
            tracked=clean
            untracked=none
            # Two passes over the same text rather than one clever one:
            # `??` is untracked, anything else is a tracked change.
            if printf '%s\n' "$status" | grep -q '^??'; then
                untracked=present
            fi
            if printf '%s\n' "$status" | grep -v '^??' | grep -q .; then
                tracked=modified
            fi
            id="commit=$commit tracked=$tracked untracked=$untracked"
            why= ;;
    esac
fi

if [ "$out" = --print ]; then
    printf '%s\n' "$id"
    exit 0
fi
case $out in -*) usage ;; esac
why=$(tidy "$why" 400)

mkdir -p "$(dirname "$out")" || exit 1
tmp="$out.tmp.$$"
{
    echo "/* Generated by host/tools/gen_build_id.sh on every make that builds"
    echo " * libcft, and rewritten only when the id changes. Not tracked"
    echo " * (.gitignore: host/gen/), never edited, and read by src/build_id.c"
    echo " * alone (cft.h, cft_build_id). */"
    if [ -n "$why" ]; then
        echo "/* unknown because: $why */"
    fi
    echo "#define CFT_BUILD_ID_STRING \"$id\""
} > "$tmp" || { rm -f "$tmp"; exit 1; }

if cmp -s "$tmp" "$out"; then
    rm -f "$tmp"
else
    mv -f "$tmp" "$out" || { rm -f "$tmp"; exit 1; }
    if [ -n "$why" ]; then
        echo "build id: $id - $why ($out)"
    else
        echo "build id: $id ($out)"
    fi
fi
exit 0
