# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""run_step: one command, niced, under `timeout --kill-after`, in a process group of its own, stopped by PID (parcel S2).

The shape is the driver's (hw/card_stress.py Driver.wrap, spawn, kill_group, await_proc), re-stated here because those are
methods of a Driver that reads its options; hw/test_sched.py holds `wrap` equal to the driver's for the same options. A step
ends at its own end or at its timeout and never at a person's request: a card process is not stopped in the middle of a leg
(an abandoned run poisons its tile until an image is reloaded), so a job looks for a stop between its steps.

A process is stopped by the PID of the process group this module started (its leader is the child, `start_new_session`),
never by a pattern in a command line: `pkill -f` would stop whatever else carries the words, a bystander's shell included.
The GNU `timeout` wrapper does the stopping on POSIX (TERM at the limit, KILL after `kill_after_s`); the loop here is the
backstop for a wrapper that has died, a little later. Windows has neither `nice` nor `timeout`, so there the loop alone ends the
process (`terminate()`, then `taskkill /F /T` of its PID); hw/test_sched.py skips those checks by name on Windows: not run there.
"""
from __future__ import annotations

import os
import shutil
import signal
import subprocess
import time

from sched_names import Refusal

POSIX = os.name == "posix"


class StepRun:
    """What happened to one command: the argv that ran (wrapped), its pid, exit status, and whether and how it was ended."""

    def __init__(self):
        self.argv: list = []
        self.pid = None
        self.rc = None
        self.start = self.end = 0.0
        self.timed_out = False
        self.killed = None              # None, "TERM" or "KILL": the signal that ended it
        self.error = None


def wrap(argv: list, timeout_s: float, kill_after_s: float, nice: int) -> list:
    cmd = list(argv)
    if POSIX:
        if shutil.which("timeout"):
            cmd = ["timeout", "--signal=TERM", "-k", str(int(kill_after_s)), str(int(max(1, round(timeout_s)))) + "s"] + cmd
        if nice and shutil.which("nice"):
            cmd = ["nice", "-n", str(nice)] + cmd
    return cmd


def kill_group(proc: subprocess.Popen, sig: str) -> None:
    """Signal the process group WE started, by PID (its leader is our child)."""
    try:
        if POSIX:
            os.killpg(proc.pid, signal.SIGTERM if sig == "TERM" else signal.SIGKILL)
        elif sig == "TERM":
            proc.terminate()
        else:
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True, timeout=30)
            proc.kill()
    except (ProcessLookupError, PermissionError, OSError):
        pass


def create_new(path: str):
    """A file the job makes, opened for writing; one that exists is `job-exists`, never written over."""
    try:
        return open(path, "xb")
    except FileExistsError:
        raise Refusal("job-exists", f"{os.path.basename(path)} already exists in the job's directory: refused, not written over")


def run_step(argv: list, cwd: str, env_extra: dict, log_path: str, timeout_s: float, kill_after_s: float = 60, nice: int = 10,
             drop: tuple = (), poll_s: float = 0.5, on_start=None) -> StepRun:
    """Run argv to its end, its output (standard output and error together) in log_path, standard input closed (an ssh that
    leaves a pipe open would hang a step that reads it). on_start(pid) is called once the process exists."""
    run = StepRun()
    env = {k: v for k, v in os.environ.items() if k not in drop}
    env.update(env_extra)
    env.setdefault("PYTHONUNBUFFERED", "1")
    run.argv = wrap(argv, timeout_s, kill_after_s, nice)
    logf = create_new(log_path)
    kw = {"start_new_session": True} if POSIX else ({"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if hasattr(subprocess, "CREATE_NEW_PROCESS_GROUP") else {})
    try:
        run.start = time.time()
        try:
            proc = subprocess.Popen(run.argv, stdout=logf, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, env=env, cwd=cwd, **kw)
        except OSError as e:
            run.error = f"could not start {run.argv[0]}: {e}"
            return run
        run.pid = proc.pid
        if on_start:
            on_start(proc.pid)
        deadline = time.monotonic() + timeout_s + (kill_after_s + 30 if POSIX and shutil.which("timeout") else 0)
        termed_at = None
        while True:
            try:
                run.rc = proc.wait(timeout=poll_s)
                break
            except subprocess.TimeoutExpired:
                pass
            now = time.monotonic()
            if now >= deadline and termed_at is None:
                run.timed_out, run.killed, termed_at = True, "TERM", now
                kill_group(proc, "TERM")
            elif termed_at is not None and now - termed_at >= kill_after_s:
                run.killed, termed_at = "KILL", now + 3600          # once
                kill_group(proc, "KILL")
    finally:
        logf.close()
        run.end = time.time()
    if POSIX and run.rc == 124:                                      # the wrapper's own: it ended the command at the limit
        run.timed_out, run.killed = True, run.killed or "TERM"
    elif POSIX and run.rc in (137, -9) and not run.timed_out:        # KILLed (by the wrapper after a TERM the command ignored, or from outside)
        run.timed_out, run.killed = True, "KILL"
    return run
