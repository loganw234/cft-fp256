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
#   bash hw/test-card-stress.sh                 # everything: about 39 minutes under WSL (2026-10-26, niced, at e72cbf08: 626 s without the
#                                               # plants and 1,699 s for its 193 plants, run apart; 1,761 s with 130 plants on 2026-10-21),
#                                               # on a desktop other sessions share; process starts are the cost
#   bash hw/test-card-stress.sh --no-plants --skip-groups stopfile,guard,pool --skip-why "TEXT"
#                                               # SKIP those groups, by name, with TEXT printed beside each (what verify/run.sh's cardstress stage
#                                               # does on Windows, where the guard's process listing can stall for minutes on a loaded desktop)
#   bash hw/test-card-stress.sh --no-plants     # the checks without the negative controls: about 10 minutes
#                                               # under WSL, 11 under Git Bash (2026-10-21)
#   bash hw/test-card-stress.sh --only parsers,commands     # seconds
#   CARD_STRESS_PLANT=<text> bash hw/test-card-stress.sh --only plants   # only the plants whose name has <text>, no control;
#                                               # CARD_STRESS_PLANT_ALL=1 also prints every failing check of each plant
#
# Groups for --only: parsers commands standin normal cadence fail timeout deaf nodevice cardlost stopfile deadline
# rotation diskfloor guard sweep disagree telemetry build buildreal internal signal torn disable sweepall
# pool seeds trees items chunk records notes resume wide testfiles report plants. `deaf` (a process that ignores SIGTERM),
# `signal` and `buildreal` need POSIX, and so does the pool group's niceness check and the records and wide groups'
# real (not dry) runs over test doubles: each is skipped by name elsewhere. `wide` (parcel HXc, 2026-10-26): the 102
# wide-format items, --mpfr-prefix and the build line with MPFR=1. `trees` skips its
# one check of the recorded tree, by name, where git cannot read this tree (a worktree whose .git file
# names a Windows path, read from WSL). The four groups of parcel DR3 (2026-10-21): `items` the 35 hard-case
# and class-level items (real logs, plans, served and refused), `chunk` --sweep-chunk and its streams, `records`
# --records and the campaign's space, `notes` four verifiers' notes (`standin` is one of them, run alone by its
# plants). `notes` skips its figure_extracts check, by name, unless CARD_STRESS_METRICS names a finished run's
# metrics.jsonl (the stress copy the committed figures come from). `resume` (parcel DR4, 2026-10-21): --resume counts coverage per
# tree class; its last check, the planner over a real file of the lead's stress run (his two nights', his three nights', or a later night's: it derives
# what it expects from the file, and holds the figures measured on his two files only for those, by sha256), is skipped by name unless CARD_STRESS_RESUME_RUN names
# that run's directory (the one holding metrics.jsonl) and the checkout holds its first commit, 881bbcb.
# `testfiles` (parcel TG, 2026-10-23): hw/test_card_stress_report.py and hw/test_card_stress_progress.py, the report's own test and the nightly page's, each run
# as a process (about 5 s and 16 s) and made this suite's checks: a crash, a hang, a missing summary line, an exit status or a failed count above 0 is a failed
# check naming the file, each FAIL line of a file is one, and its SKIP lines are passed on as this suite's own SKIPs, by name and with the file's reason, so
# the runner counts them as inner skips. Eleven controls on stand-in files come first and show those checks able to fail. The files' real-copy checks read
# CARD_STRESS_RESUME_RUN (the report's, which is also the `resume` group's) and CARD_STRESS_PROGRESS_RUNS (the page's: the lead's run directories, separated as
# PATH is) and are skipped by name without them. The group cannot be named in --skip-groups. The card scheduler's `drytests` step runs this suite, and
# tolerates a failure only by its spec's known_flakes: a failure here is not one unless the spec lists the prefix "report test: " or "progress test: ".
# Since 2026-10-22 (parcel P5, the driver before the nights run it): `build` also holds the images' manifests (what the driver reads beside
# each xclbin: refused or flagged, by name) and vectors/out (refused at the start when the selftest leg would read it), `telemetry` the
# status file's telemetry line and the report's HBM zeros, `chunk` every random slice held to its count in a default run, and `buildreal`
# copies only the files git tracks (a built host/ no longer fails it). `bash verify/run.sh --only cardstress` runs this with --no-plants as a
# stage of the gate; it is skipped by name there while another process on the system uses the card (the guard's refusal, guard_refused).
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
