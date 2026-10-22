# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""The code stage (parcel S2): clone the job's commit, and assert it before any step runs.

The model is the lead's box_nightly.sh (a clone, `checkout --detach`, HEAD, status, the rtl/ tree, a grep for a string only the
new commit has) and CLAUDE.md, "Before believing a remote build": the SHA and the content are asserted SEPARATELY, because a
clone that reports the right SHA with a working tree that never updated is what `rev-parse` cannot see. In order, each its own
refusal: the commit is in the source (`commit-missing`), HEAD is it (`head-mismatch`), the status is clean with untracked files
counted (`tree-dirty`), the rtl/ tree is the spec's (`rtl-mismatch`), each string is found the stated number of times
(`content-missing`), each named commit is an ancestor (`ancestor-missing`), and the commit is on the remote or the spec allowed
it (`commit-unpushed`, the one check that may need the network, so it comes last).

The clone cache is clones/SHA/ in the state root, one per full SHA. A clone is made in a temporary directory and renamed, so
a half-made one never looks finished. One that EXISTS has its working tree and HEAD neither touched nor repaired: it is asserted
like a fresh one, so a cache that was edited, or moved to another commit, is refused by name. Its refs/pushed/ is the exception,
because the pushed check writes there on every job, cache or not: the fetch is `--prune`d, so a branch deleted on the remote
after the clone was made is gone from the clone too, and a cache cannot answer `pushed` for a branch that no longer holds the
commit. This stage writes only under clones/ of the state root, and git is asked with the environment's GIT_DIR and friends
removed and no prompt for a credential; no git configuration is written, by this stage or by git on its behalf (what the clone
gains is the remote's branch heads as refs/pushed/ and the objects they need, and it loses the refs/pushed/ the remote no longer has).

A source is `bundle:FILE`, FILE in config.json's code.bundle_dir (a bundle made by `git bundle create FILE BRANCH` has no HEAD,
so the clone is made with --no-checkout and the SHA is checked out), or `remote`, config.json's code.remote.
"""
from __future__ import annotations

import os
import shutil
import stat
import subprocess

from sched_names import Refusal

GIT_DROP = ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_OBJECT_DIRECTORY", "GIT_COMMON_DIR", "GIT_NAMESPACE")


def git(clone, *args, timeout: float = 600) -> tuple:
    """(rc, stdout, stderr) of `git [-C clone] args`; a git that cannot run is rc 127, never an exception."""
    env = {k: v for k, v in os.environ.items() if k not in GIT_DROP}
    env.update(GIT_TERMINAL_PROMPT="0", LC_ALL="C")
    try:
        p = subprocess.run(["git"] + (["-C", clone] if clone else []) + list(args), capture_output=True, timeout=timeout, env=env,
                           stdin=subprocess.DEVNULL)
        return p.returncode, p.stdout.decode("utf-8", "replace"), p.stderr.decode("utf-8", "replace")
    except (OSError, subprocess.TimeoutExpired) as e:
        return 127, "", f"{type(e).__name__}: {e}"


def first_line(text: str, n: int = 200) -> str:
    return next((ln.strip() for ln in text.splitlines() if ln.strip()), "")[:n]


def _writable(fn, path, _exc):
    os.chmod(path, stat.S_IWRITE)         # git's object files are read-only, and Windows will not delete those
    fn(path)


def remove_tree(path: str) -> None:
    """Remove a directory THIS stage made, by its exact path."""
    shutil.rmtree(path, onerror=_writable)


def source_of(cfg: dict, code: dict) -> tuple:
    """(kind, where) for the spec's source, or `commit-missing` naming what is not there."""
    c = cfg["code"]
    if code["source"] == "remote":
        if not c["remote"]:
            raise Refusal("commit-missing", "source `remote`, and config.json's code.remote names no URL")
        return "remote", c["remote"]
    name = code["source"][len("bundle:"):]
    if not c["bundle_dir"]:
        raise Refusal("commit-missing", f"source `bundle:{name}`, and config.json's code.bundle_dir names no directory")
    path = os.path.join(c["bundle_dir"], name)
    if not os.path.isfile(path):
        raise Refusal("commit-missing", f"the bundle {name} is not in config.json's code.bundle_dir")
    return "bundle", path


def make_clone(root: str, sha: str, kind: str, where: str, jid: str) -> str:
    """clones/SHA, made from the source: cloned without a checkout into a temporary directory, the commit checked out detached,
    then renamed into place. Returns its path, or refuses `commit-missing`."""
    cdir = os.path.join(root, "clones")
    final, tmp = os.path.join(cdir, sha), os.path.join(cdir, f".tmp-{sha}-{jid}")
    try:
        rc, _, err = git(None, "clone", "-q", "--no-checkout", where, tmp, timeout=3600)
        if rc != 0:
            raise Refusal("commit-missing", f"git could not clone the {kind}: {first_line(err)}")
        if git(tmp, "cat-file", "-e", sha + "^{commit}")[0] != 0:
            raise Refusal("commit-missing", f"{sha} is not in the {kind}")
        rc, _, err = git(tmp, "checkout", "-q", "--detach", sha, timeout=1800)
        if rc != 0:
            raise Refusal("commit-missing", f"git could not check out {sha}: {first_line(err)}")
        try:
            os.rename(tmp, final)
        except OSError:
            if not os.path.isdir(final):
                raise
        return final
    finally:
        if os.path.isdir(tmp):
            remove_tree(tmp)


def pushed_state(clone: str, sha: str, remote) -> tuple:
    """('pushed' | 'unpushed' | 'unknown', why): whether a branch of the remote holds the commit. The remote's branches are
    fetched into refs/pushed/ of the clone (no configuration is written) with --prune, so a ref left by an earlier job for a branch
    the remote has since deleted does not count: a cached clone answers as a fresh one does. 'unknown' is a remote that is not
    configured or cannot be read: the commit is then not SHOWN to be on it."""
    if not remote:
        return "unknown", "config.json's code.remote names no remote"
    rc, _, err = git(clone, "fetch", "-q", "--no-tags", "--prune", remote, "+refs/heads/*:refs/pushed/*", timeout=1800)
    if rc != 0:
        return "unknown", f"the remote could not be read: {first_line(err)}"
    rc, out, _ = git(clone, "for-each-ref", "--count=1", "--contains", sha, "refs/pushed/")
    return ("pushed", "a branch of the remote holds it") if rc == 0 and out.strip() else ("unpushed", "no branch of the remote holds it")


def assert_clone(clone: str, sha: str, assertions: dict) -> dict:
    """The facts of a clone that passes every assertion, or the first refusal. HEAD and a clean status are asserted always."""
    rc, out, err = git(clone, "rev-parse", "HEAD")
    head = out.strip()
    if rc != 0 or head != sha:
        raise Refusal("head-mismatch", f"HEAD is {head or 'unreadable (' + first_line(err) + ')'}; the spec's commit is {sha}")
    rc, out, err = git(clone, "status", "--porcelain", "--untracked-files=all")
    changed = [ln for ln in out.splitlines() if ln.strip()]
    if rc != 0 or changed:
        raise Refusal("tree-dirty", f"git status {'did not answer: ' + first_line(err) if rc != 0 else f'shows {len(changed)} path(s)'}"
                      + (f": {'; '.join(changed[:3])}" if changed else ""))
    facts = {"head": head, "status_lines": 0}
    for key, rel in (("rtl_tree", "rtl"), ("host_tree", "host")):
        rc, out, _ = git(clone, "rev-parse", f"HEAD:{rel}")
        facts[key] = out.strip() if rc == 0 and out.strip() else None
    want = assertions.get("rtl_tree")
    if want is not None and facts["rtl_tree"] != want:
        raise Refusal("rtl-mismatch", f"the rtl/ tree is {facts['rtl_tree']}; the spec names {want}")
    facts["content"] = []
    for rel, text, count in assertions.get("content", []):
        full = os.path.join(clone, rel)
        if not os.path.isfile(full) or os.path.commonpath([os.path.realpath(full), os.path.realpath(clone)]) != os.path.realpath(clone):
            raise Refusal("content-missing", f"{rel} is not a file of the clone")
        with open(full, "rb") as fh:
            found = fh.read().decode("utf-8", "replace").count(text)
        facts["content"].append({"path": rel, "string": text[:80], "expected": count, "found": found})
        if found != count:
            raise Refusal("content-missing", f"{text[:60]!r} is found {found} time(s) in {rel}; the spec says {count}")
    facts["ancestors"] = []
    for anc in assertions.get("ancestors", []):
        if git(clone, "cat-file", "-e", anc + "^{commit}")[0] != 0:
            raise Refusal("ancestor-missing", f"{anc} is not in the clone")
        if git(clone, "merge-base", "--is-ancestor", anc, "HEAD")[0] != 0:
            raise Refusal("ancestor-missing", f"{anc} is not an ancestor of {sha}")
        facts["ancestors"].append(anc)
    return facts


def prepare(root: str, cfg: dict, code: dict, jid: str) -> tuple:
    """(clone path, the facts the job's `code` record carries): the clone made or found, and every assertion held."""
    sha = code["commit"]
    final = os.path.join(root, "clones", sha)
    reused = os.path.isdir(final)
    kind = "cache"                                  # a clone that is there is asserted, not made again, and its source is not asked for
    clone = final
    if not reused:
        kind, where = source_of(cfg, code)
        clone = make_clone(root, sha, kind, where, jid)
    facts = assert_clone(clone, sha, code.get("assert") or {})
    state, why = pushed_state(clone, sha, cfg["code"]["remote"])
    allowed = bool(code.get("allow_unpushed"))
    if state != "pushed" and not allowed:
        raise Refusal("commit-unpushed", f"{sha} is {state}: {why}; `code.allow_unpushed` runs it anyway, and the record says so")
    facts.update(commit=sha, source=code["source"], origin=kind, clone=f"clones/{sha}", reused=reused, pushed=state, pushed_why=why,
                 allow_unpushed=allowed)
    return clone, facts
