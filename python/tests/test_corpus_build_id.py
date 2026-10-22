# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""A committed certificate's build-id, held by certificates/corpus.py (KL-355,
parcel P4; its docstring is the definition). `make` kept a committed
certificate whose remake equalled it but for build-id and the hash line, and
`check` compared the remake normalized in those places, so a wrong build-id
(a `--force-dirty` trial's, or a commit not in the history) was kept and
passed. Held here with no tool, card or network: the form (one planted case
a way to be wrong, the committed corpus), the history leg (real git in a
repository, a real depth-1 clone, a folder inside it, a folder in none and no
git on PATH; where git cannot say the leg is a SKIP by name that the runner's
own inner-skip scan counts), the keep rule (keep_decision; make_version_1
calls it) and the gate (hold_build_ids fails a planted certificate by name in
every state). The runs of corpus.py against planted trees are in
docs/VALIDATION.md's entry for the parcel.
"""

import inspect
import os
import pathlib
import re
import shutil
import subprocess
import sys
import types

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "python"))
sys.path.insert(0, str(ROOT / "certificates"))

import corpus as C  # noqa: E402

COMMIT = "0b8ea100ad108d886fc6ea2126905d1deb385fa4"
CLEAN = f"commit={COMMIT} tracked=clean untracked=none"
GIT = shutil.which("git")


def a_tool_written_certificate():
    """Lorenz-63 at fp64 as committed: the bytes, and its manifest case."""
    case = next(c for c in C.read_manifest().cases
                if c.name == "lorenz63-rk4-fp64")
    return (ROOT / case.certificate[0]).read_bytes(), case


def runner_skip_regex():
    """The pattern verify/run.sh counts an inner skip by, read from it."""
    text = (ROOT / "verify" / "run.sh").read_text()
    m = re.search(r"^INNER_SKIP_RE='([^']*)'", text, re.M)
    pattern = m.group(1).replace("[[:space:]:]", r"[\s:]")
    return re.compile(pattern.replace("[[:space:]]", r"\s"))


# ---- form ---------------------------------------------------------------

@pytest.mark.parametrize("value", [
    f"commit={COMMIT} tracked=modified untracked=none",
    f"commit={COMMIT} tracked=clean untracked=present",
    "unknown",
    f"commit={COMMIT[:20]} tracked=clean untracked=none",
])
def test_plant_a_tool_written_build_id_that_is_not_a_clean_build(value):
    probs = C.build_id_problems(value, None, True)
    assert len(probs) == 1 and "not a clean build" in probs[0], (value, probs)


def test_the_right_build_ids_and_the_certificates_no_tool_wrote():
    assert C.build_id_problems(CLEAN) == []
    assert C.build_id_problems(f"commit={'a' * 64} tracked=clean "
                               f"untracked=none") == []       # SHA-256 repo
    assert C.build_id_problems("unknown", None, False) == []
    dirty = f"commit={COMMIT} tracked=modified untracked=none"
    assert "not a clean build" in C.build_id_problems(dirty, None, False)[0]
    data, case = a_tool_written_certificate()
    assert C.tool_written(case) and C.build_id_of(data) == CLEAN
    assert C.build_id_of(C.normalized(data, "unknown")) == "unknown"
    assert C.build_id_of(b"cft-certificate 1\nend\n") is None


def test_the_committed_corpus_names_clean_builds():
    """In every clone: the form of every committed certificate's build-id,
    and that the 11 cft-segrun wrote name the two commits that did."""
    corpus = C.read_manifest()
    named = set()
    for case in corpus.cases:
        value = C.build_id_of((ROOT / case.certificate[0]).read_bytes())
        assert C.build_id_problems(value, None, C.tool_written(case)) == [], \
            case.name
        if C.CLEAN_BUILD.fullmatch(value or ""):
            named.add(C.CLEAN_BUILD.fullmatch(value).group(1))
    assert len([c for c in corpus.cases if C.tool_written(c)]) == 11
    assert named == {COMMIT, "df06c1450e233e609b4392bc8dab44add86a53b9"}


def test_the_committed_corpus_names_commits_this_clone_has():
    """The history leg on the corpus as committed, where this clone has its
    history: a SKIP by name where it has not (CI's host job checks out with
    fetch-depth 0, so that it runs there; the golden job's shallow clone
    shows this one skipped, in pytest's -rs)."""
    known, state, why = C.history_lookup()
    if state != "full":
        pytest.skip(f"the history leg cannot run here: {why}")
    for case in C.read_manifest().cases:
        value = C.build_id_of((ROOT / case.certificate[0]).read_bytes())
        assert C.build_id_problems(value, known, C.tool_written(case)) == [], \
            case.name


# ---- history ------------------------------------------------------------

def test_a_commit_the_history_lacks_is_a_problem_only_if_it_can_say():
    probs = C.build_id_problems(CLEAN, lambda c: False)
    assert len(probs) == 1 and COMMIT[:12] in probs[0]
    assert "does not have" in probs[0]
    assert C.build_id_problems(CLEAN, lambda c: True) == []
    assert C.build_id_problems(CLEAN, lambda c: None) == []
    assert C.build_id_problems(CLEAN, None) == []


@pytest.mark.skipif(GIT is None, reason="git is not on PATH")
def test_real_git_in_each_state(tmp_path, monkeypatch):
    """One control a state, against real git: a repository of its own, a
    real depth-1 clone of it, a folder inside it, a folder in none, and no
    git on PATH."""
    def git(cwd, *args):
        p = subprocess.run(
            [GIT, "-c", "user.name=t", "-c", "user.email=t@example.invalid",
             "-c", "commit.gpgsign=false", "-C", str(cwd)] + list(args),
            capture_output=True, text=True, timeout=60,
            env=dict(os.environ, GIT_TERMINAL_PROMPT="0"))
        assert p.returncode == 0, (args, p.stderr)
        return p.stdout.strip()
    src = tmp_path / "src"
    src.mkdir()
    git(src, "init", "-q")
    for i in range(3):
        git(src, "commit", "-q", "--allow-empty", "-m", f"c{i}")
    oldest = git(src, "rev-list", "--max-parents=0", "HEAD")
    newest = git(src, "rev-parse", "HEAD")

    monkeypatch.setattr(C, "ROOT", src.resolve())            # full
    assert C.history() == ("full", "")
    known, state, _why = C.history_lookup()
    assert state == "full" and known(oldest) is True
    assert known(newest) is True and known("0" * 40) is False

    shallow = tmp_path / "shallow"                           # depth 1
    git(tmp_path, "clone", "-q", "--depth", "1", src.as_uri(), str(shallow))
    monkeypatch.setattr(C, "ROOT", shallow.resolve())
    state, why = C.history()
    assert state == "shallow" and "shallow" in why
    known, state, _why = C.history_lookup()
    assert known(oldest) is None and known(newest) is None

    (src / "inner").mkdir()                                  # inside another
    monkeypatch.setattr(C, "ROOT", (src / "inner").resolve())
    state, why = C.history()
    assert state == "none" and "not a repository of its own" in why

    (tmp_path / "bare").mkdir()                              # in none
    monkeypatch.setattr(C, "ROOT", (tmp_path / "bare").resolve())
    assert C.history()[0] == "none"

    (tmp_path / "empty").mkdir()                             # no git at all
    monkeypatch.setattr(C, "ROOT", src.resolve())
    monkeypatch.setenv("PATH", str(tmp_path / "empty"))
    state, why = C.history()
    assert state == "none" and "git cannot be run" in why


# ---- the keep rule ------------------------------------------------------

def test_the_keep_rule_keeps_a_right_build_id_and_writes_over_a_wrong_one():
    data, case = a_tool_written_certificate()
    boundaries = [r.boundaries for r in case.runs]
    bid = "commit=" + "9" * 40 + " tracked=clean untracked=none"
    made = C.normalized(data, bid)             # what the tool makes now
    old = (data, boundaries)
    assert C.keep_decision(old, made, bid, boundaries,
                           lambda c: True) == (True, "")
    # the rule before KL-355 kept this: its remake equals it but for the
    # build-id and the hash line
    dirty = (C.normalized(data, f"commit={COMMIT} tracked=modified "
                                f"untracked=none"), boundaries)
    assert C.normalized(dirty[0], bid) == made
    keep, why = C.keep_decision(dirty, made, bid, boundaries, lambda c: True)
    assert not keep and "not a clean build" in why
    keep, why = C.keep_decision(old, made, bid, boundaries, lambda c: False)
    assert not keep and COMMIT[:12] in why and "does not have" in why
    for known in (lambda c: None, None):       # the history cannot say
        assert C.keep_decision(old, made, bid, boundaries, known) \
            == (True, "")
    # `example` is the golden writer's: `unknown` is its build-id
    unknown = (C.normalized(data, "unknown"), boundaries)
    assert C.keep_decision(unknown, made, bid, boundaries, None,
                           tool_written=False)[0]
    assert not C.keep_decision(unknown, made, bid, boundaries, None)[0]


def test_the_keep_rule_still_needs_the_rest_of_what_it_needed():
    data, case = a_tool_written_certificate()
    boundaries = [r.boundaries for r in case.runs]
    bid = "commit=" + "9" * 40 + " tracked=clean untracked=none"
    made = C.normalized(data, bid)
    assert C.keep_decision(None, made, bid, boundaries) == (False, "")
    assert C.keep_decision((data, boundaries[:-1]), made, bid,
                           boundaries) == (False, "")
    other = made[:100] + bytes([made[100] ^ 1]) + made[101:]
    assert C.keep_decision((data, boundaries), other, bid,
                           boundaries) == (False, "")


def test_make_version_1_asks_keep_decision_and_not_the_old_inline_rule():
    """The pure function is held above; a make that stopped calling it is
    held here, by its text, since make needs a tool to run."""
    src = inspect.getsource(C.make_version_1)
    assert "keep_decision(" in src and "history_lookup()" in src
    assert "normalized(old[0], bid) == data" not in src
    assert 'tool_written=c.name != "example"' in src


# ---- the gate -----------------------------------------------------------

def a_tmp_corpus(tmp_path, monkeypatch, **values):
    """Fake cases, each a tool-written one whose certificate is the
    committed Lorenz-63 with its build-id replaced by the value given; the
    check's counters reset and restored."""
    data, _case = a_tool_written_certificate()
    cases = []
    for name, value in values.items():
        path = f"certificates/{name}.cert"
        (tmp_path / "certificates").mkdir(exist_ok=True)
        (tmp_path / path).write_bytes(C.normalized(data, value))
        cases.append(types.SimpleNamespace(
            name=name, version=1, certificate=(path, "0" * 64), runs=[]))
    monkeypatch.setattr(C, "ROOT", tmp_path)
    for counter, fresh in (("CHECKS", 0), ("FAILED", []), ("SKIPS", [])):
        monkeypatch.setattr(C, counter, fresh)
    return types.SimpleNamespace(cases=cases)


def stub_history(monkeypatch, state, why, answer):
    """history_lookup answering `answer`: a value, or a function of the
    commit."""
    known = answer if callable(answer) else (lambda c: answer)
    monkeypatch.setattr(C, "history_lookup",
                        lambda run=None: (known, state, why))


def test_the_gate_passes_the_right_corpus_in_a_full_clone(tmp_path,
                                                          monkeypatch, capsys):
    corpus = a_tmp_corpus(tmp_path, monkeypatch, a=CLEAN, b=CLEAN)
    stub_history(monkeypatch, "full", "", True)
    C.hold_build_ids(corpus)
    out = capsys.readouterr().out
    assert C.FAILED == [] and C.SKIPS == []
    assert "each one this repository has" in out and "SKIP" not in out


@pytest.mark.parametrize("state, why", [
    ("shallow", "this clone is shallow"),
    ("none", "this tree is not a git repository")])
def test_where_git_cannot_say_the_history_leg_is_a_skip_by_name(
        tmp_path, monkeypatch, capsys, state, why):
    """Not a note and not a pass: a line the runner counts as an inner skip
    (INNER_SKIP_RE, read from verify/run.sh), so that the VERDICT names it
    and --require-all fails it; no failure."""
    corpus = a_tmp_corpus(tmp_path, monkeypatch, a=CLEAN)
    stub_history(monkeypatch, state, why, None)
    C.hold_build_ids(corpus)
    out = capsys.readouterr().out
    assert C.FAILED == [] and len(C.SKIPS) == 1
    counted = [ln for ln in out.splitlines() if runner_skip_regex().match(ln)]
    assert len(counted) == 1 and why in counted[0], out
    assert "each one this repository has" not in out


def test_plant_wrong_build_ids_and_the_gate_names_them_in_every_state(
        tmp_path, monkeypatch, capsys):
    dirty = f"commit={COMMIT} tracked=modified untracked=none"
    gone = "commit=" + "1" * 40 + " tracked=clean untracked=none"
    corpus = a_tmp_corpus(tmp_path, monkeypatch, good=CLEAN, dirty=dirty,
                          unknown="unknown", gone=gone)
    for state, answer, failed in (
            ("full", lambda c: c != "1" * 40, 3), ("shallow", None, 2),
            ("none", None, 2)):
        for counter, fresh in (("CHECKS", 0), ("FAILED", []), ("SKIPS", [])):
            monkeypatch.setattr(C, counter, fresh)
        stub_history(monkeypatch, state, state, answer)
        C.hold_build_ids(corpus)
        capsys.readouterr()
        assert len(C.FAILED) == failed, (state, C.FAILED)
        assert any(f.startswith("dirty: ") and "tracked=modified" in f
                   for f in C.FAILED)
        assert any(f.startswith("unknown: ") and "'unknown'" in f
                   for f in C.FAILED)
        assert not any(f.startswith("good: ") for f in C.FAILED)
        assert any(f.startswith("gone: ") and "1" * 12 in f
                   for f in C.FAILED) == (state == "full")


def test_a_corpus_with_no_tool_written_certificate_does_not_pass_vacuously(
        tmp_path, monkeypatch, capsys):
    corpus = a_tmp_corpus(tmp_path, monkeypatch)
    stub_history(monkeypatch, "full", "", True)
    C.hold_build_ids(corpus)
    capsys.readouterr()
    assert any("certificates a tool wrote" in f for f in C.FAILED)
