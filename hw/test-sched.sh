#!/usr/bin/env bash
# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
#
# The card scheduler's tests (parcels S1, S2 and S3a): no XRT, no card, no amd-arc-box, no network. hw/sched/cft_sched.py against
# its fake runner (S1), its staged runner (S2: the driver's stand-in and parsers, a scratch repository for the remote and the
# bundle, a fake host tree for the build) and its window runner (S3a: the calendar, the nightly window's preflight, fallback and end
# check, against the driver's own dry run), in a state root made under the system's temporary directory. Each rule is then shown able to
# fail: a defect is put back into a copy of the code and the scenario written for it must go red at its own check
# (the plants; hw/test-sweep-judge.sh's standard), and each plant prints its failing set.
#
#   bash hw/test-sched.sh                      # everything, plants included
#   bash hw/test-sched.sh --no-plants          # the checks without the negative controls
#   bash hw/test-sched.sh --only spec,queue    # some groups
#   bash hw/test-sched.sh --only plants --plant "second service"    # the plants whose label has this text
#
# Groups for --only: spec queue records cli locks code build images guard steps window table plants (steps has parts: --only steps:parsers, and
# registry run_step jobs real refusals; window has parts: --only window:chain, and calendar spec claim driver end). --plant "S3a: " runs the
# plants of parcel S3a alone. `locks` needs flock(2): on a platform without it (Windows) its checks are skipped by name and
# the one check of the path without flock runs instead; so are the plants of the locks and of the root's mode. The S2 groups need make, sh,
# nice, timeout and /proc for some checks, skipped by name on Windows. Run it with no other driver suite or stand-in on the machine
# (the driver's guard sees every process). --plant "S2: " runs the plants of parcel S2 alone.
set -uo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
PY=${PYTHON:-}
if [ -z "$PY" ]; then
  for c in python3 python; do
    if command -v "$c" >/dev/null 2>&1; then PY=$c; break; fi
  done
fi
[ -n "$PY" ] || { echo "test-sched: no python3 on PATH (set PYTHON)" >&2; exit 2; }
exec "$PY" -B -I "$ROOT/hw/test_sched.py" "$@"
