#!/bin/bash
# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
#
# The long-run stress driver for the U50: cycles of the card's own checks on revision 8's
# three images, weighted toward the quad, with the native-oracle soaks worked through slice
# by slice between them. This file only finds the tools and hands over; the driver is
# hw/card_stress.py, its design is that file's docstring, and the operator's page is
# docs/CARDDAY.md, "The long run".
#
#   bash hw/card-stress.sh --quick                         # the smoke, under 30 minutes (an estimate)
#   bash hw/card-stress.sh --until "2026-10-19 08:00"      # the long run
#   touch "$OUT/STOP"                                      # stop after the leg running
#   python3 hw/card_stress_report.py "$OUT"                # read a run at any time
#   bash hw/card-stress.sh --help                          # every setting and its default
#
# Run it from a checkout nobody else touches, on the box that has the card, under tmux or
# `setsid nohup`: it builds the host tools from that tree once (make -C host XRT=1 ...),
# and hw/card-segrun.sh asserts at every run that the tools' build id names the tree's HEAD.
# Agents never run it: it opens the card.
set -uo pipefail

ROOT=$(cd "$(dirname "$0")/.." && pwd)

# XRT's environment (xbutil on PATH, the runtime's libraries), as hw/run-device-test.sh sources it
for r in /opt/xilinx/xrt /usr/local/xrt; do
  if [ -f "$r/setup.sh" ]; then
    set +u; source "$r/setup.sh" >/dev/null 2>&1; set -u
    break
  fi
done

# the python that runs the driver, seq_check.py and acceptance.py: $PYTHON, else python3
PY=${PYTHON:-}
if [ -z "$PY" ]; then
  for c in python3 python; do
    if command -v "$c" >/dev/null 2>&1; then PY=$c; break; fi
  done
fi
[ -n "$PY" ] || { echo "card-stress: no python3 on PATH (set PYTHON)" >&2; exit 2; }
export PYTHON=$PY

exec "$PY" "$ROOT/hw/card_stress.py" "$@"
