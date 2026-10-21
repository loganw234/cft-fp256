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
#   bash hw/test-card-stress.sh                 # everything: about 27 minutes under WSL (2026-10-21, niced, 1,636 s,
#                                               # on a desktop other sessions share; process starts are the cost)
#   bash hw/test-card-stress.sh --no-plants     # the checks without the negative controls: about 10 minutes
#                                               # under WSL, 11 under Git Bash (2026-10-21)
#   bash hw/test-card-stress.sh --only parsers,commands     # seconds
#   CARD_STRESS_PLANT=<text> bash hw/test-card-stress.sh --only plants   # only the plants whose name has <text>, no control;
#                                               # CARD_STRESS_PLANT_ALL=1 also prints every failing check of each plant
#
# Groups for --only: parsers commands standin normal fail timeout deaf nodevice cardlost stopfile deadline
# rotation diskfloor guard sweep disagree telemetry build buildreal internal signal torn disable sweepall
# pool seeds trees items chunk records notes report plants. `deaf` (a process that ignores SIGTERM),
# `signal` and `buildreal` need POSIX, and so does the pool group's niceness check and the records group's
# real (not dry) run over test doubles: each is skipped by name elsewhere. `trees` skips its
# one check of the recorded tree, by name, where git cannot read this tree (a worktree whose .git file
# names a Windows path, read from WSL). The four groups of parcel DR3 (2026-10-21): `items` the 35 hard-case
# and class-level items (real logs, plans, served and refused), `chunk` --sweep-chunk and its streams, `records`
# --records and the campaign's space, `notes` four verifiers' notes (`standin` is one of them, run alone by its
# plants). `notes` skips its figure_extracts check, by name, unless CARD_STRESS_METRICS names a finished run's
# metrics.jsonl (the stress copy the committed figures come from).
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
