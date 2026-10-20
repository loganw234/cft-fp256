#!/usr/bin/env bash
# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
#
# The long-run stress driver's dry run: no XRT, no card, no amd-arc-box. hw/card_stress.py
# against hw/card_stress_standin.py (which prints the tools' verdict lines and fails, hangs or
# loses the device on a schedule), the verdict parsers on real logs of the software backend
# (hw/card_stress_fixtures/), and the report. Each check class is then shown able to fail: a
# defect is put back into a copy of the code and the scenario written for it must go red
# (the plants; hw/test-sweep-judge.sh's standard). Nothing here starts anything heavy.
#
#   bash hw/test-card-stress.sh                 # everything: about 16 minutes under WSL (2026-10-19, niced,
#                                               # on a desktop other sessions share; process starts are the cost)
#   bash hw/test-card-stress.sh --no-plants     # the checks without the negative controls: about 5 minutes
#                                               # under WSL, 6 to 8 under Git Bash
#   bash hw/test-card-stress.sh --only parsers,commands     # seconds
#
# Groups for --only: parsers commands normal fail timeout deaf nodevice cardlost stopfile deadline
# rotation diskfloor guard sweep disagree telemetry build buildreal internal signal torn disable sweepall
# pool seeds trees report plants. `deaf` (a process that ignores SIGTERM), `signal` and `buildreal` need
# POSIX, and so does the pool group's niceness check: each is skipped by name elsewhere. `trees` skips its
# one check of the recorded tree, by name, where git cannot read this tree (a worktree whose .git file
# names a Windows path, read from WSL).
set -uo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
PY=${PYTHON:-}
if [ -z "$PY" ]; then
  for c in python3 python; do
    if command -v "$c" >/dev/null 2>&1; then PY=$c; break; fi
  done
fi
[ -n "$PY" ] || { echo "test-card-stress: no python3 on PATH (set PYTHON)" >&2; exit 2; }
exec "$PY" -B -I "$ROOT/hw/test_card_stress.py" "$@"
