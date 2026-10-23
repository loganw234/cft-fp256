# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""The stress driver, imported and never copied (parcel S2).

hw/card_stress.py (card_user, find_card_users, list_processes, the leg templates and timeouts) and hw/card_stress_lib.py (the
parse_* functions, Item, Verdict) are the authority on what a card user is and on what a tool's output means. This is the one
module the scheduler reaches them through, so that a copy of the scheduler made for a plant (hw/test_sched.py) carries the
driver beside it, unchanged, and a parcel that renames something in the driver finds every use here. The scheduler imports the
parsers of ITS checkout while a job's tools come from the job's commit: a tool whose output moved is a `parse_error`, loudly,
and never a pass (docs/studies/SCHED-A-card-scheduler.md, section 8, item 8).
"""
from __future__ import annotations

import os
import re
import sys

HW = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))          # hw/ (a plant's copy: the directory holding sched/ and the driver)
if HW not in sys.path:
    sys.path.insert(0, HW)
import card_stress as CS            # noqa: E402,F401  card_user, find_card_users, list_processes, IMAGES, DEFAULT_TIMEOUTS, WrongAnswer ...
import card_stress_lib as L         # noqa: E402,F401  parse_*, Item, sweep_items, Verdict, VerdictError

STANDIN = os.path.join(HW, "card_stress_standin.py")
STANDIN_MARK = "standin: would run:"          # the first line the stand-in prints (card_stress_standin.py, main)
DRY_RUN_LINE = re.compile(r"card-stress: out .*; (?:QUICK )?DRY RUN ")       # the driver's own start line of a --dry-run (card_stress.py, run)


def parser_problem(args: list):
    """None when the driver's OWN parser (card_stress.parse_args) accepts `args`, else its error message: argparse prints the message and exits 2, and
    the exit is caught here. A stand-in --until and --out are added, so nothing is looked up. The scheduler holds a spec's driver options to the driver's
    rules with this and keeps no copy of them."""
    import contextlib
    import io
    err = io.StringIO()
    try:
        with contextlib.redirect_stderr(err):
            CS.parse_args(["--until", "2099-01-01 00:00", "--out", os.devnull] + list(args))
    except SystemExit:
        return (err.getvalue().strip().splitlines() or ["the driver's parser refused the options"])[-1]
    return None


def standin(leg: str, real: list) -> list:
    """A command as the driver's own Driver.standin wraps it: the stand-in, the leg's name, `--`, the real argv. A test holds
    this equal to the driver's."""
    return [sys.executable, STANDIN, leg, "--"] + list(real)


def is_dry_text(text: str) -> bool:
    """True when a log is a stand-in's (it carries the stand-in's own header line, which a real tool never prints) or a driver's own
    --dry-run's console (its start line says DRY RUN): output that must never be recorded as a card's."""
    head = text.splitlines()[:30]
    return any(ln.startswith(STANDIN_MARK) for ln in head[:5]) or any(DRY_RUN_LINE.search(ln) for ln in head)
