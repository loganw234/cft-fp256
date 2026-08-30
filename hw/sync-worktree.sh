#!/bin/bash
# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
#
# Put an exact commit onto a build host, as a real git checkout.
#
#   bash hw/sync-worktree.sh <bundle> [destination]
#
# The build hosts (amd-arc-box, the cft2204 WSL distro) used to hold
# file copies of the tree with no .git. That is fine until it is not:
# hw/rebuild-2022.sh writes a manifest naming the commit an artifact
# came from, and on a copy that field reads "unknown" - which makes the
# manifest worthless on exactly the machines that produce the
# artifacts. A git bundle is the simplest way to move history across a
# network with no server: one file, verifiable, and the checkout it
# produces normalises line endings per .gitattributes instead of
# carrying a Windows worktree's CRLFs onto a machine whose shell
# scripts then will not run.
#
# Existing build caches are preserved because they are expensive and
# not reproducible from source: .ipcache is Vivado's IP cache, and
# sweep/ and cardday/ hold hours of implementation results.
#
# Idempotent: run it again with a newer bundle and it fetches rather
# than re-cloning.
set -euo pipefail

BUNDLE=${1:?usage: sync-worktree.sh <bundle> [destination]}
DEST=${2:-$HOME/cft-fp256}
KEEP="${KEEP:-.ipcache sweep cardday build}"

[ -f "$BUNDLE" ] || { echo "no such bundle: $BUNDLE" >&2; exit 1; }

if [ -d "$DEST/.git" ]; then
  echo "== updating $DEST"
  git -C "$DEST" remote set-url origin "$BUNDLE"
  git -C "$DEST" fetch -q origin
  git -C "$DEST" reset -q --hard origin/main
  echo "   now at $(git -C "$DEST" log --oneline -1)"
  exit 0
fi

TMP="$DEST.incoming.$$"
rm -rf "$TMP"
echo "== cloning $BUNDLE -> $DEST"
git clone -q --branch main "$BUNDLE" "$TMP"

# Carry the expensive, non-reproducible directories across. Quoted and
# tested individually: an unset variable here would match the whole
# tree and move the old checkout inside the new one, which is exactly
# what happened the first time this was done by hand.
if [ -d "$DEST" ]; then
  for d in $KEEP; do
    [ -n "$d" ] || continue
    if [ -e "$DEST/$d" ]; then
      mv "$DEST/$d" "$TMP/$d"
      echo "   kept $d"
    fi
  done
  mv "$DEST" "$DEST.pre-git.$(date +%Y%m%d%H%M%S)"
  echo "   previous tree set aside"
fi
mv "$TMP" "$DEST"
echo "   now at $(git -C "$DEST" log --oneline -1)"
