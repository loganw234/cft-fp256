# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""The nightly page's data commit, PREPARED (parcel S4a). Logan, 2026-10-23: "Box prepares, lead pushes" - no GitHub credential on the box.

The scheduler keeps a clone of the repository of its own, publish/repo in the state root, fetched from the PUBLIC remote (config.json's code.remote; the box can reach it,
Logan's answer 9, and holds no credential). For each night it fetches the remote's main, checks that out DETACHED and cleans the clone, so the tools are main's, and then, in order:
the reducer on the night's run directory (`--out site/nightly.json`), its `--check` (the morning check, which must be rc 0), `source.metrics_sha256` held to the close-out's sums,
the nights the published file already holds held UNCHANGED, and the clone shown to differ in site/nightly.json alone. Then the file is committed alone, `nightly data: night N (DATE)`,
on the local branch `nightly-data` whose parent is the fetched main, and the commit, its parent and the one command that fetches it from the desktop are recorded. The lead fetches
it and pushes. NOTHING HERE PUSHES, adds a remote, writes to the remote or changes a git configuration (the commit's identity is given on its command line, `git -c`): every git
command goes through `git()` below, which refuses the verbs that would. Each thing that fails is a refusal by name (sched_names.py, "closeout"), with the tool's own message;
the clone is the scheduler's own and is brought back to main (`checkout -f`, `clean -fd`) at the start of every night, so a night that refused leaves nothing behind for the next.
"""
from __future__ import annotations

import json
import os
import socket
import subprocess

import sched_code as CODE
import sched_state as STATE
from sched_names import Refusal

BRANCH, DATA, REF = "nightly-data", "site/nightly.json", "refs/publish/main"
IDENT = ("-c", "user.name=cft-sched", "-c", "user.email=cft-sched@localhost.invalid", "-c", "commit.gpgsign=false")
NEVER = ("push", "send-pack", "receive-pack", "remote", "config", "credential")       # verbs this module may not run, whatever it is asked


def env_of(**more) -> dict:
    return {**{k: v for k, v in os.environ.items() if k not in CODE.GIT_DROP}, "GIT_TERMINAL_PROMPT": "0", "LC_ALL": "C", "PYTHONDONTWRITEBYTECODE": "1", **more}


def run(argv: list, cwd, secs: float):
    """(rc, stdout, stderr); rc None when the command did not start or ran past `secs` (stderr then names it)."""
    try:
        p = subprocess.run(argv, cwd=cwd, capture_output=True, timeout=secs, env=env_of(), stdin=subprocess.DEVNULL)
    except (OSError, subprocess.TimeoutExpired) as e:
        return None, "", f"{type(e).__name__}: {e}"
    return p.returncode, p.stdout.decode("utf-8", "replace"), p.stderr.decode("utf-8", "replace")


def git(repo, *args, timeout: float = 300):
    rest = list(args)
    while rest[:1] == ["-c"]:
        rest = rest[2:]
    if rest and rest[0] in NEVER:
        raise ValueError(f"the publish step may not run `git {rest[0]}`")
    return run(["git"] + (["-C", repo] if repo else []) + list(args), None, timeout)


def read_json(path: str):
    """The JSON in a file, or None where there is no file or it is not JSON."""
    try:
        with open(path, "rb") as fh:
            return json.loads(fh.read().decode("utf-8"))
    except (OSError, ValueError):
        return None


def lines(text: str, width: int = 400) -> str:
    return " | ".join(ln.strip() for ln in text.splitlines() if ln.strip())[:width] if text.strip() else "no message"


def sync(repo: str, remote: str) -> str:
    """The clone at the remote's main, detached and clean: the full SHA of that main. Refuses `remote-unreachable` or `publish-failed`."""
    if not os.path.isdir(os.path.join(repo, ".git")):
        tmp = repo + ".tmp"
        if os.path.isdir(tmp):
            CODE.remove_tree(tmp)                                      # a half-made clone of an earlier night: the scheduler's, by its exact name
        rc, _, err = git(None, "clone", "-q", "--no-checkout", remote, tmp, timeout=3600)
        if rc != 0:
            raise Refusal("remote-unreachable", f"git could not clone the remote: {lines(err)}")
        os.rename(tmp, repo)
    rc, _, err = git(repo, "fetch", "-q", "--no-tags", remote, f"+refs/heads/main:{REF}", timeout=1800)
    if rc != 0:
        raise Refusal("remote-unreachable", f"git could not fetch the remote's main: {lines(err)}")
    rc, out, err = git(repo, "rev-parse", "--verify", "-q", REF + "^{commit}")
    if rc != 0 or not out.strip():
        raise Refusal("remote-unreachable", f"the remote has no main ({lines(err)})")
    for what, args in (("checkout", ("checkout", "-q", "-f", "--detach", out.strip())), ("clean", ("clean", "-fdq"))):
        rc, _, err = git(repo, *args, timeout=600)
        if rc != 0:
            raise Refusal("publish-failed", f"git {what} in the scheduler's clone: {lines(err)}")
    return out.strip()


def first_diff(a, b, path: str = ""):
    """The path of the first difference between two JSON values, or None."""
    if isinstance(a, dict) and isinstance(b, dict):
        for k in sorted(set(a) | set(b)):
            if k not in a or k not in b:
                return f"{path}.{k} is {'missing from the published file' if k not in a else 'missing from the new one'}"
            d = first_diff(a[k], b[k], f"{path}.{k}")
            if d:
                return d
        return None
    if isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            return f"{path or '.'} has {len(a)} entries published and {len(b)} now"
        return next((d for d in (first_diff(x, y, f"{path}[{i}]") for i, (x, y) in enumerate(zip(a, b))) if d), None)
    return None if a == b and type(a) is type(b) else f"{path or '.'}: published {str(a)[:50]}, now {str(b)[:50]}"


def fetch_command(cfg: dict, repo: str) -> tuple:
    """(the one command that fetches the prepared commit from the desktop, a note). The host is config.json's publish.fetch_host, else this user at this machine's own name."""
    host = cfg["publish"]["fetch_host"]
    path = repo.replace(os.sep, "/")
    cmd = f"git fetch ssh://{host or STATE.user() + '@' + socket.gethostname()}{'' if path.startswith('/') else '/'}{path} {BRANCH}"
    return cmd, "" if host else "publish.fetch_host is not set: the host is this machine's own name, which the desktop may not resolve"


def prepare(root: str, cfg: dict, run_dir: str, metrics_sha256, python: str, rec: dict) -> None:
    """Make the data commit for the night in `run_dir`; `rec` is filled as it goes, so a refusal keeps what was learned. Refuses by name; never pushes."""
    remote = cfg["code"]["remote"]
    if not remote:
        raise Refusal("publish-no-remote", "config.json's code.remote names no URL: there is nowhere to fetch the repository's main from")
    repo = os.path.join(root, "publish", "repo")
    rec.update(main=sync(repo, remote), repo=repo)
    old = read_json(os.path.join(repo, DATA))
    reducer = os.path.join(repo, "hw", "card_stress_progress.py")
    rc, _, err = run([python, "-B", reducer, run_dir, "--out", DATA], repo, 900)
    if rc != 0:
        raise Refusal("reducer-refused", f"main's reducer exited with status {rc}: {lines(err)}")
    rc, _, err = run([python, "-B", reducer, "--check", DATA, run_dir], repo, 900)
    if rc != 0:
        raise Refusal("check-differs", f"main's --check exited with status {rc}: {lines(err)}")
    new = read_json(os.path.join(repo, DATA))
    if not isinstance(new, dict) or new.get("source", {}).get("metrics_sha256") != metrics_sha256:
        raise Refusal("metrics-sha-differs", f"the data file says metrics.jsonl is {str((new or {}).get('source', {}).get('metrics_sha256'))[:16]}, the sums' line says {str(metrics_sha256)[:16]}")
    rec.update(night=new["newest"]["night"], date=new["newest"]["date"], nights=len(new["nights"]))
    for i, n in enumerate((old or {}).get("nights") or []):
        d = first_diff(n, new["nights"][i]) if i < len(new["nights"]) else "the night is missing from the new file"
        if d:
            raise Refusal("earlier-night-changed", f"published night {n.get('n', i + 1)} is not what the new file has: {d}")
    if old is not None and first_diff({k: v for k, v in old.items() if k != "made"}, {k: v for k, v in new.items() if k != "made"}) is None:
        raise Refusal("nothing-to-publish", f"the new file is the published one ({len(new['nights'])} nights) but for `made`: no night to add")
    rc, out, err = git(repo, "status", "--porcelain", "--untracked-files=all")
    paths = sorted(ln[3:].strip('"') for ln in out.splitlines() if ln.strip())
    if rc != 0 or paths != [DATA]:
        raise Refusal("publish-touches-more", f"the clone shows {paths or lines(err)} and the commit may hold {DATA} alone")
    msg = f"nightly data: night {rec['night']} ({rec['date']})"
    for what, args in (("branch", ("checkout", "-q", "-B", BRANCH)), ("add", ("add", "--", DATA)), ("commit", (*IDENT, "commit", "-q", "-m", msg))):
        rc, _, err = git(repo, *args)
        if rc != 0:
            raise Refusal("publish-failed", f"git {what} in the scheduler's clone: {lines(err)}")
    sha, parent = (git(repo, "rev-parse", x)[1].strip() for x in ("HEAD", "HEAD^"))
    files = git(repo, "diff-tree", "--no-commit-id", "--name-only", "-r", "HEAD")[1].split()
    if parent != rec["main"] or files != [DATA]:
        raise Refusal("publish-touches-more", f"the commit {sha[:12]} has parent {parent[:12]} (main is {rec['main'][:12]}) and holds {files}")
    cmd, note = fetch_command(cfg, repo)
    rec.update(commit=sha, parent=parent, branch=BRANCH, message=msg, files=files, fetch=cmd, fetch_note=note or None)
