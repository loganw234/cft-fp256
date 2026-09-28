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
#   - any git call here writes ANYTHING to stderr, even with a zero exit.
#     git status says "warning: could not open directory" and exits 0
#     about a directory whose untracked files it then leaves out of its
#     answer (measured with git 2.34.1 by verifier-C3, 2026-09-28), so a
#     warning means a count that cannot be vouched for; and a warning
#     parsed as porcelain would have read as a modification.
# The reason goes into the header as a comment and onto make's output,
# never into the id: the id is a value a certificate carries, and the
# reason is for the person reading a build log.
#
# git's stderr is kept apart from its stdout INSIDE this shell, with no
# temporary file (git_run, below). The first version wrote it to
# ${TMPDIR:-/tmp}/gen_build_id.<pid>.err, and on the Windows desktop that
# was blind: under MSYS2's make the recipe has no TMPDIR, the shell
# running this (make's /bin/sh, MSYS2's) wrote the file into its /tmp,
# C:/msys64/tmp, and the cat and rm found on PATH - Git for Windows' -
# looked in theirs. The warning was never read, the id came out whole
# where it had to be unknown, and one empty file leaked per build: 127 by
# 10:49 that day (verifier-C3 found it). Only shell built-ins and pipes
# touch git's output now, so no second runtime can mean another place.
# make passes <out.h> as a relative path, which every runtime and the
# native tools resolve alike.
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

# Runs git with the arguments given, and keeps what it wrote to stdout,
# what it wrote to stderr and its exit status apart - git_out, git_err,
# git_rc - all three in THIS shell and with no temporary file. Inside the
# command substitution, git's stderr goes to fd 3, which is the
# substitution's own output; git's stdout is captured on its own; and
# once git has exited, its status and its stdout follow, each after a
# byte no git message carries. So the capture reads
#   <stderr> \001 <status> \001 <stdout>
# and is taken apart with the shell's own parameter expansions. True when
# git exited 0 AND wrote nothing to stderr.
SEP=$(printf '\001')
git_run() {
    git_all=$( { git_o=$("$GIT" "$@" 2>&3); git_s=$?
                 printf '%s%s%s%s' "$SEP" "$git_s" "$SEP" "$git_o"; } 3>&1 )
    git_err=${git_all%%"$SEP"*}
    git_all=${git_all#*"$SEP"}
    git_rc=${git_all%%"$SEP"*}
    git_out=${git_all#*"$SEP"}
    [ "$git_rc" = 0 ] && [ -z "$git_err" ]
}
# What git said, for a reason: its stderr, or its status when it said
# nothing.
git_said() {
    tidy "${git_err:-exit status $git_rc}"
}

if ! command -v "$GIT" >/dev/null 2>&1; then
    why="no git on PATH ($GIT)"
elif ! git_run -C "$root" rev-parse --show-cdup; then
    why="git cannot place $root in a work tree: $(git_said)"
elif [ -n "$git_out" ]; then
    why="$root is not the top of its repository (git says the top is $(tidy "$git_out") above it): a copy inside another project's repository, whose commit is not this tree's"
elif ! git_run -C "$root" rev-parse --verify --quiet 'HEAD^{commit}'; then
    why="$root has no commit checked out${git_err:+: $(git_said)}"
else
    commit=$git_out
    case ${#commit} in
        40|64) ;;
        *) commit= ;;
    esac
    case $commit in
        ''|*[!0-9a-f]*)
            why="git named the commit in a form that is not 40 or 64 lowercase hex digits" ;;
        *)
            if ! git_run -C "$root" --no-optional-locks status --porcelain \
                    --untracked-files=all; then
                why="git status in $root did not answer cleanly: $(git_said)"
            else
                status=$git_out
                tracked=clean
                untracked=none
                # Two passes over the same text rather than one clever
                # one: `??` is untracked, anything else a tracked change.
                if printf '%s\n' "$status" | grep -q '^??'; then
                    untracked=present
                fi
                if printf '%s\n' "$status" | grep -v '^??' | grep -q .; then
                    tracked=modified
                fi
                id="commit=$commit tracked=$tracked untracked=$untracked"
            fi ;;
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
