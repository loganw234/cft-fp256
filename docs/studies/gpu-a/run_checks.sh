#!/bin/bash
# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
#
# run_checks.sh BIN LABEL CORPUS_DIR OUT_DIR [harness flags, e.g. --device 1]
#
# Every corpus gen_corpus.py writes, through one build on one device: the
# harness's check (compare, sha256 through libcft's sha256.c, time), then
# gen_corpus.py verify, which compares the output file again in Python and
# hashes it with hashlib. A corpus that is absent is said to be not run.
# Exit 0 only if every corpus present was GREEN by both.
set -uo pipefail
here=$(cd "$(dirname "$0")" && pwd)
BIN=${1:?BIN}; LABEL=${2:?LABEL}; C=${3:?CORPUS_DIR}; O=${4:?OUT_DIR}
shift 4
mkdir -p "$O"
rc=0
for f in ${CORPORA:-conf-fp32 conf-fp64 conf-fp128 conf-fp256 stream-fp32 stream-fp64 stream-fp128 stream-fp256}; do
    if [ ! -e "$C/$f.bin" ]; then
        echo "not run: $LABEL $f (no corpus $C/$f.bin)"
        continue
    fi
    timeout 110 "$BIN" check "$C/$f.bin" "$O/$LABEL-$f.out" "$@" || rc=1
    python3 -B "$here/gen_corpus.py" verify "$C/$f.bin" "$O/$LABEL-$f.out" || rc=1
done
echo "run_checks: $LABEL: $([ $rc = 0 ] && echo 'every corpus run GREEN' || echo 'RED somewhere')"
exit $rc
