# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""The build stage (parcel S2): the driver's build step, run on a job's clone, with its checks named.

The targets, the tools and their `ldd` check are hw/card_stress.py `build_tools`'s own (hw/test_sched.py reads that source and
holds these lists equal to its), and so is the order: the roundeven probe, `make -C host -jN XRT=1 XRT_ROOT=... all device-test
api-test remote-test divsqrt-soak clause5-soak`, `ldd` of each tool for xrt_coreutil, then the build id. `XRT=1` is never
defaulted away (CLAUDE.md: without it backend_xrt.cpp is silently left out and every image answers "no such device").
  build-failed       make exited non-zero, or a tool it was to make is not there;
  xrt-not-linked     a required tool's `ldd` does not name xrt_coreutil (cft-resident and cft-selftest are optional, as the
                     driver has them: not linked means their steps are skipped by name, with the reason);
  build-id-mismatch  the tree's build id (`make -s -C host print-build-id`) is not the one cft-segrun carries
                     (`cft-segrun --build-id`), as hw/card-segrun.sh asserts; or the tree's does not name the job's commit on a
                     clean tree (`commit=SHA tracked=clean untracked=none`), which also refuses the id `unknown`.
  tool-not-runnable  (parcel S3c) a tool cannot run here, which says nothing about its id: `cft-segrun --build-id` exited non-zero or
                     printed the loader's error, or `ldd` lists a library of a tool as `not found`. The box's first card job (2026-10-23)
                     was refused `build-id-mismatch` for `libxrt_coreutil.so.2: cannot open shared object file`.
  xrt-setup-failed   (parcel S3c, raised before the clone, by xrt_env) XRT's setup.sh is not there or cannot be sourced.
XRT's ENVIRONMENT (parcel S3c). A tool linked against XRT finds libxrt_coreutil through LD_LIBRARY_PATH, which XRT's setup.sh sets, and
the box's shells do not source it: hw/card-stress.sh does (its lines 25 to 31), which is why the driver ran and the scheduler's own
`ldd` and `cft-segrun --build-id` did not. `xrt_env` sources `<runner.xrt_root>/setup.sh` in bash ONCE for a job and returns what it adds
and changes; the staged runner gives that to the make, to the ldd and build-id checks below, and to every step (sched_staged.py). A dry
job builds nothing and touches no card, so it has none of this and is not refused for the lack of it.
The real build is the lead's run on the box; this desktop has no XRT, and the suite drives this module with a scratch repository
and stand-in tools.

`check_clone_not_built` is the study's `clone-built`: the driver suite's `buildreal` group copies host/ and hw/ into a scratch
repository and commits them, and in a clone that was built it took the ignored products along (KL-13). It is ONE function and ONE
table row on purpose: parcel P5 removes the cause, and the lead can then retire this check.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import time

from sched_code import first_line, git, remove_tree
from sched_names import Refusal
from sched_proc import run_step

TARGETS = ["all", "device-test", "api-test", "remote-test", "divsqrt-soak", "clause5-soak"]
TOOLS = ["device-test", "api-test", "remote-test", "cft-segrun", "cft-audit", "divsqrt-soak", "clause5-soak", "cft-resident", "cft-selftest", "libcft.so"]
OPTIONAL = {"cft-resident": "resident", "cft-selftest": "selftest"}            # tool -> the step type it serves
LOADER_ERROR = "error while loading shared libraries"                          # what the dynamic loader prints for a library it cannot find (and exits 127)
# One bash: the shell's own environment (`env -0`, NUL-separated so a value may hold a newline), a marker, the exit status of sourcing the file, and the environment after it. The
# file's own words go to /dev/null (XRT's prints a banner), its errors to standard error. What it ADDS AND CHANGES is the difference between the two environments of the SAME shell,
# so what bash itself sets cancels out (but for SHELL_OWN). hw/card-stress.sh sources it the same way (`set +u; source ...`).
SOURCE_SH = r"""set +u; [ -f "$CFT_SCHED_XRT_SETUP" ] || exit 66; env -0; printf '%s\0' @@sourced@@; . "$CFT_SCHED_XRT_SETUP" >/dev/null; printf '%s\0' "$?"; env -0"""
NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")
SHELL_OWN = ("_", "SHLVL", "PWD", "OLDPWD")            # bash's own, which differ between the two listings by how it runs the last command (-c execs it, and SHLVL falls by one)


def _vars(parts: list) -> dict:
    """NAME=value entries of an `env -0` listing; an exported function (BASH_FUNC_x%%) is not a variable and is left out."""
    out = {}
    for entry in parts:
        k, eq, v = entry.decode("utf-8", "surrogateescape").partition("=")
        if eq and NAME.match(k):
            out[k] = v
    return out


def xrt_env(rcfg: dict) -> dict:
    """XRT's environment for a card of kind `xrt`: `<runner.xrt_root>/setup.sh` sourced in bash, as hw/card-stress.sh does. Returns {"env": what it adds and changes (name -> value,
    for run_step's env_extra and run_quiet's env), "setup", "set": the names, "XILINX_XRT", "LD_LIBRARY_PATH": as they are afterwards}. An environment it leaves as it was (a setup file
    that is idempotent, run from a shell that had it sourced already) is an empty "env" and not a failure. `xrt-setup-failed` when the file is not there, bash cannot source it, it exits
    non-zero, or no environment comes out; the caller makes this ONCE per job, and never for a dry job (it builds nothing and touches no card)."""
    setup = os.path.join(rcfg["xrt_root"], "setup.sh")

    def fail(why: str) -> Refusal:
        return Refusal("xrt-setup-failed", f"{setup} {why}: the scheduler sources it, as hw/card-stress.sh does, so that the tools it runs find XRT's libraries (runner.xrt_root in config.json)")

    if not os.path.isfile(setup):
        raise fail("is not a file")
    try:
        # The file's name goes in the environment (the same in both listings, so not in the difference). bash is the one PATH names: on Windows a bare "bash" is System32's, the WSL launcher, which
        # passes neither arguments nor environment variables on.
        p = subprocess.run([shutil.which("bash") or "bash", "-c", SOURCE_SH], capture_output=True, timeout=60, stdin=subprocess.DEVNULL,
                           env={**os.environ, "CFT_SCHED_XRT_SETUP": setup.replace(os.sep, "/")})
    except (OSError, subprocess.TimeoutExpired) as e:
        raise fail(f"could not be sourced ({type(e).__name__}: {e})")
    parts, err = p.stdout.split(b"\0"), first_line(p.stderr.decode("utf-8", "replace"))
    if b"@@sourced@@" not in parts:
        raise fail(f"could not be sourced (bash exited {p.returncode}): {err}")
    i = parts.index(b"@@sourced@@")
    rc = parts[i + 1].decode("ascii", "replace") if i + 1 < len(parts) else ""
    if not rc:
        raise fail(f"ended the shell when sourced (bash exited {p.returncode}; an `exit` in the file?): {err}")
    if rc != "0":
        raise fail(f"exited {rc} when sourced: {err}")
    before, after = _vars(parts[:i]), _vars(parts[i + 2:])
    if not before or not after:
        raise fail("was sourced and bash printed no environment (`env -0`)")
    delta = {k: v for k, v in after.items() if before.get(k) != v and k not in SHELL_OWN}
    return {"env": delta, "setup": setup, "set": sorted(delta), "XILINX_XRT": after.get("XILINX_XRT"), "LD_LIBRARY_PATH": after.get("LD_LIBRARY_PATH")}


def check_clone_not_built(clone: str) -> None:
    """`clone-built`: refuse when the clone holds ignored files under host/ (the build's products). Retire after P5 (KL-13)."""
    rc, out, err = git(clone, "status", "--porcelain", "--ignored")
    if rc != 0:
        raise Refusal("clone-built", f"git status --ignored did not answer: {first_line(err)}")
    products = [ln[3:] for ln in out.splitlines() if ln.startswith("!! host/")]
    if products:
        raise Refusal("clone-built", f"{len(products)} ignored product(s) under host/ ({', '.join(products[:3])}): the dry tests copy host/ and hw/ and "
                      f"take them along (KL-13); run them in a clone nothing has built, before the build")


def run_quiet(argv: list, timeout: float, cwd=None, env=None) -> tuple:
    """(exit status, standard output and error together). `env` is added to this process's environment (xrt_env's); a command that cannot start is 127."""
    try:
        p = subprocess.run(argv, capture_output=True, timeout=timeout, cwd=cwd, stdin=subprocess.DEVNULL, env={**os.environ, **env} if env else None)
        return p.returncode, (p.stdout + p.stderr).decode("utf-8", "replace")
    except (OSError, subprocess.TimeoutExpired) as e:
        return 127, f"{e}"


def build_xrt(clone: str, sha: str, rcfg: dict, jobdir: str, log_path: str, steps: list, xenv: dict | None = None) -> dict:
    """Build the clone for a card of kind `xrt` and assert the build: the driver-shaped record {ok, steps, disabled, build_id}, or the first refusal.
    `steps` is the caller's list, filled as the build goes, so that a refusal leaves what was checked up to it. The make output is
    log_path, a file the job makes (one that exists is `job-exists`). `xenv` is XRT's environment (xrt_env's "env"): the make, the `ldd` checks and
    `cft-segrun --build-id` run in it, as every step of the job does and as the driver's own build does (hw/card-stress.sh sources it first)."""
    xenv = xenv or {}
    host = os.path.join(clone, "host")

    def step(name: str, ok: bool, detail: str) -> bool:
        steps.append({"name": name, "ok": ok, "detail": detail[:600]})
        return ok

    probe_dir = os.path.join(jobdir, ".build-probe")
    os.mkdir(probe_dir)
    try:
        src = os.path.join(probe_dir, "re-probe.c")
        with open(src, "w") as fh:
            fh.write("#define _GNU_SOURCE\n#include <math.h>\nint main(void){return (int)(roundeven(1.5)+roundevenf(2.5f));}\n")
        c5defs = "-DCFT_SOAK_HAVE_ROUNDEVEN=1" if run_quiet([os.environ.get("CC", "cc"), src, "-lm", "-o", src + ".out"], 120)[0] == 0 else ""
    finally:
        remove_tree(probe_dir)
    step("roundeven probe", True, "present" if c5defs else "absent: the rne oracle is rint under FE_TONEAREST")
    flags = ["XRT=1", f"XRT_ROOT={rcfg['xrt_root']}"]
    argv = ["make", "-C", host, f"-j{rcfg['build_jobs']}"] + flags + ([f"C5DEFS={c5defs}"] if c5defs else []) + TARGETS
    t0 = time.time()
    run = run_step(argv, clone, xenv, log_path, rcfg["build_timeout_s"], rcfg["kill_after_s"], rcfg["nice"])        # niced, under timeout, in a group of its own, as every step is
    rc = 124 if run.timed_out else 127 if run.rc is None else run.rc
    step("make", rc == 0, f"make -C host {' '.join(flags)} {' '.join(TARGETS)}: rc {rc} in {time.time() - t0:.0f} s; log {os.path.basename(log_path)}")
    if rc != 0:
        raise Refusal("build-failed", f"make exited {rc}; see {os.path.basename(log_path)}")
    disabled: dict = {}
    for exe in TOOLS:
        path = os.path.join(host, exe)
        if not os.path.exists(path):
            if exe in OPTIONAL:
                disabled[OPTIONAL[exe]] = f"{exe} was not built"
                step(f"xrt {exe}", True, f"not built: the {OPTIONAL[exe]} step is skipped, by name")
                continue
            raise Refusal("build-failed", f"make succeeded and {exe} was not built")
        lrc, lout = run_quiet(["ldd", path], 60, env=xenv)
        linked = lrc == 0 and "xrt_coreutil" in lout
        lost = next((ln.strip() for ln in lout.splitlines() if "not found" in ln), None)      # `libxrt_coreutil.so.2 => not found`: named by ldd, and the tool will not start
        if linked and lost:
            step(f"xrt {exe}", False, f"names libxrt_coreutil, and cannot load: {lost}")
            raise Refusal("tool-not-runnable", f"{exe} cannot run here: ldd, in the environment the scheduler runs it in, says '{lost}'")
        if exe in OPTIONAL and not linked:
            disabled[OPTIONAL[exe]] = f"{exe} does not link XRT (ldd)"
            step(f"xrt {exe}", True, f"NOT XRT-linked (an optional tool): the {OPTIONAL[exe]} step is skipped, by name")
        elif not linked:
            raise Refusal("xrt-not-linked", f"{exe} does NOT link XRT: built without XRT=1 it answers every xclbin with 'no such device' (CLAUDE.md)")
        else:
            step(f"xrt {exe}", True, "links libxrt_coreutil")
    trc, tree_id = run_quiet(["make", "-s", "-C", host, "print-build-id"], 120)
    brc, bin_id = run_quiet([os.path.join(host, "cft-segrun"), "--build-id"], 60, env=xenv)
    if brc != 0 or LOADER_ERROR in bin_id:                       # a tool that cannot run carries no id to compare: not a mismatch (the box, 2026-10-23: libxrt_coreutil.so.2 not found)
        step("build id", False, f"cft-segrun --build-id did not run: exit status {brc}: {first_line(bin_id)}")
        raise Refusal("tool-not-runnable", f"cft-segrun --build-id exited {brc}: {first_line(bin_id)}")
    tree_id, bin_id = tree_id.strip(), bin_id.strip()
    if trc != 0 or brc != 0 or not bin_id or bin_id != tree_id:                       # (brc is 0 here: a tool that cannot run was refused above)
        step("build id", False, f"the tree's {tree_id!r}, cft-segrun's {bin_id!r}")
        raise Refusal("build-id-mismatch", f"cft-segrun carries {bin_id!r} and the tree is {tree_id!r}: relink it (make -C host XRT=1 all)")
    want = f"commit={sha} tracked=clean untracked=none"
    if tree_id != want:
        step("build id", False, f"{tree_id!r} is not {want!r}")
        raise Refusal("build-id-mismatch", f"the build id {tree_id!r} does not name the job's commit on a clean tree ({want!r})")
    step("build id", True, f"the tree's and cft-segrun's: {tree_id}")
    return {"ok": True, "steps": steps, "disabled": disabled, "build_id": bin_id}


KIND_BUILDS = {"xrt": build_xrt}              # what building a clone means depends on the card's kind: XRT=1 and the ldd check are an xrt card's
KIND_ENVS = {"xrt": xrt_env}                  # and so does the environment its tools run in: XRT's setup.sh is an xrt card's


def dry_record() -> dict:
    """The build record of a dry job: the clone is not built (no make of the host tools, no ldd, no XRT), and it says so. It does not say
    that every command is a stand-in's: a step with a stand-in leg runs against it, and `vectors`, `drytests` and `driver-quick`, which
    have none, run their own commands (none of them touches a card)."""
    return {"ok": True, "steps": [{"name": "tools", "ok": True, "detail": "dry job: the clone is not built (no make of the host tools, no ldd, no XRT); "
            "a step with a stand-in leg runs against it, and vectors, drytests and driver-quick run their own commands"}],
            "disabled": {}, "build_id": None}
