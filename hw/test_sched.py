#!/usr/bin/env python3
# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""The card scheduler's tests (parcel S1): no card, no XRT, no amd-arc-box, no driver, no network.

    python3 hw/test_sched.py [--only NAME,...] [--no-plants] [--plant TEXT]        (bash hw/test-sched.sh)

Groups: spec (the job spec's table and refusals), queue (ids, atomic submit, order, claim, cancel, hold, deadlines),
records (job.jsonl, the outcomes, the sums, restart), cli (the state root, the configuration, every verb), locks (the
service's lock and the card's, with real processes), table (one check, that every refusal the table gives to S1 was raised by a
scenario of the groups before it, so it needs them in the same run), then plants. `locks` needs flock(2): where there is none
(Windows) its checks are skipped by name, and the one check of the path without flock runs instead.

A plant puts one defect back into a COPY of the code (and of this file), runs the groups written for it from the copy as a
process, and requires three things: the copy is whole (it imports, and its run makes exactly as many checks as the unmodified
copy's, so a copy that died part-way is not "caught"), the failing set is not empty, and it holds the check written for that
defect. Each plant prints its failing set. An edit that does not match exactly once is an error: a plant that did not apply
would prove nothing. Prints one line a group and a last line "sched test: N checks, F failed, S skipped, T s".
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.environ.get("SCHED_TEST_ROOT") or os.path.dirname(HERE)       # a plant's copy reads the real tree's docs, not its own parent
SCHED = os.path.join(HERE, "sched")
sys.path.insert(0, SCHED)
import sched_config as C     # noqa: E402
import sched_names as N      # noqa: E402
import sched_run as R        # noqa: E402
import sched_spec as P       # noqa: E402
import sched_state as S      # noqa: E402

CHECKS, FAILS, SKIPS = 0, [], []
TMP = ""
ROOTS: list = []               # every root a scenario made, read at the end for the refusals each one left
SEEN: set = set()              # refusal names the command printed
DEL = object()
GOOD = {"cards": [{"id": "u50-0", "kind": "xrt"}], "images": [{"name": "quad", "path": "q.xclbin", "sha256": "0" * 64}]}


def check(name: str, ok, detail: str = "") -> bool:
    global CHECKS
    CHECKS += 1
    if not ok:
        FAILS.append(f"{name}: {detail}")
        print(f"  FAIL  {name}  {detail}"[:400])
    return bool(ok)


def skip(name: str, why: str) -> None:
    SKIPS.append(name)
    print(f"  SKIP  {name} - {why}")


def spec(**kw) -> dict:
    s = {"v": 1, "kind": "staged", "name": "t", "card": "u50-0", "code": {"commit": "a" * 40, "source": "bundle:t.bundle"},
         "steps": [{"type": "sleep", "seconds": 0}]}
    for k, v in kw.items():
        s.pop(k, None) if v is DEL else s.__setitem__(k, v)
    return s


def mkroot(name: str, cards=("u50-0",)):
    root = os.path.join(TMP, name)
    os.makedirs(root)
    with open(os.path.join(root, "config.json"), "w") as fh:
        json.dump({"cards": [{"id": c, "kind": "xrt"} for c in cards], "images": GOOD["images"]}, fh)
    cfg = C.load_config(root)
    C.ensure_layout(root, cfg)
    ROOTS.append(root)
    return root, cfg


def sub(root, cfg, s):
    return S.submit(root, cfg, s if isinstance(s, bytes) else json.dumps(s).encode(), R.FAKE_REGISTRY)


def serve_here(root, cfg, **kw):
    return R.serve(root, cfg, R.FakeRunner(), drain=True, poll=0.02, skip_locks=not S.HAVE_FLOCK, out=lambda s: None, **kw)


def recs(root, where, jid):
    return S.read_records(os.path.join(root, where, jid, "job.jsonl"))


def types(root, where, jid):
    return [r["type"] for r in recs(root, where, jid)]


def rec(root, where, jid, i=-1):
    """One record of a job, or {} when there is none: a plant that removes records must fail a check, not crash the group."""
    r = recs(root, where, jid)
    return r[i] if -len(r) <= i < len(r) else {}


def safely(fn, *a):
    """fn(*a), or the name of the Refusal or the exception it raised: the group goes on and a check says what happened."""
    try:
        return fn(*a)
    except N.Refusal as r:
        return r.name
    except Exception as e:
        return "crashed: " + repr(e)[:70]


def claim1(root, cfg, now=None):
    return S.claim_next(root, cfg, "u50-0", time.time() if now is None else now, R.FAKE_REGISTRY)


def verdict(fn):
    """The name and text of the Refusal fn raises, or None."""
    try:
        fn()
        return None
    except N.Refusal as r:
        return f"{r.name}: {r.why}"


def cli(root, *args, stdin=None, env=None):
    e = {k: v for k, v in os.environ.items() if k != C.ENV_ROOT}
    e.update(env or {})
    p = subprocess.run([sys.executable, "-B", "-I", os.path.join(SCHED, "cft_sched.py")] + (["--root", root] if root else []) + list(args),
                       input=stdin, capture_output=True, text=True, timeout=120, env=e)
    SEEN.update(re.findall(r"^refused(?: j\d+)?: ([a-z0-9-]+):", p.stderr, re.M))
    return p.returncode, p.stdout, p.stderr


def wait_for(cond, secs=30.0):
    end = time.time() + secs
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.05)
    return False


def verify_sums(d):
    """An independent `sha256sum -c`: what a job directory's SHA256SUMS lists and whether each file matches."""
    try:
        listed = dict((n, h) for h, _, n in (ln.partition("  ") for ln in open(os.path.join(d, "SHA256SUMS")).read().splitlines()))
    except OSError:
        return ["no SHA256SUMS"]
    files = {n for n in os.listdir(d) if n != "SHA256SUMS"}
    bad = [f"{n} not listed" for n in files - set(listed)] + [f"{n} listed, missing" for n in set(listed) - files]
    for n in files & set(listed):
        if hashlib.sha256(open(os.path.join(d, n), "rb").read()).hexdigest() != listed[n]:
            bad.append(f"{n} differs")
    return bad


# ---------------------------------------------------------------------------------------- spec

def group_spec():
    root, cfg = mkroot("s-refuse")
    ok = P.validate(spec(), cfg, R.FAKE_REGISTRY)
    check("spec: a good staged spec validates, its defaults filled (preempt ok, priority 50, card kept)",
          ok["preempt"] == "ok" and ok["priority"] == 50 and ok["card"] == "u50-0")
    check("spec: a window job's default priority is 10, below a staged job's 50 (a staged job outranks the sweep)",
          P.validate(spec(kind="window"), cfg, R.FAKE_REGISTRY)["priority"] == 10 and P.DEFAULT_PRIORITY["staged"] > P.DEFAULT_PRIORITY["window"])
    full = spec(kind="window", priority=7, preempt="never", image="quad", card="any", signature="x",
                when={"not_before": 100, "deadline": 200}, steps=[{"type": "sleep", "seconds": 1.5}, {"type": "fail", "reason": "r"},
                                                                   {"type": "find", "count": 2}, {"type": "ignore-stop", "seconds": 0}])
    kids = lambda parent: {p.split(".")[1] for p in P.SPEC_FIELDS if p.startswith(parent + ".")}
    check("spec: every field of the table, set at once (when.window apart, which S3 honours), is accepted: the table and the validator agree",
          verdict(lambda: P.validate(full, cfg, R.FAKE_REGISTRY)) is None and set(full) == {p for p in P.SPEC_FIELDS if "." not in p}
          and set(full["code"]) == kids("code") and set(full["when"]) == kids("when") - {"window"})
    cases = [
        ("an unknown field", spec(needs=[]), "spec-form", "needs"),
        ("owner (the scheduler fills it, a spec cannot)", spec(owner="x"), "spec-form", "owner"),
        ("an unknown field inside code", spec(code={"commit": "a" * 40, "source": "remote", "assert": {}}), "spec-form", "code.assert"),
        ("an unknown field inside when", spec(when={"zone": "x"}), "spec-form", "when.zone"),
        ("an unknown field of a step", spec(steps=[{"type": "sleep", "colour": "red"}]), "spec-form", "steps[0].colour"),
        ("a missing required field", spec(kind=DEL), "spec-form", "kind"),
        ("a missing code.commit", spec(code={"source": "remote"}), "spec-form", "code.commit"),
        ("a priority that is a string", spec(priority="high"), "spec-form", "priority"),
        ("a boolean where an integer is wanted", spec(priority=True), "spec-form", "priority"),
        ("a priority out of range", spec(priority=101), "spec-form", "priority"),
        ("a kind that is neither window nor staged", spec(kind="batch"), "spec-form", "kind"),
        ("a preempt that is neither ok nor never", spec(preempt="maybe"), "spec-form", "preempt"),
        ("a negative sleep", spec(steps=[{"type": "sleep", "seconds": -1}]), "spec-form", "steps[0].seconds"),
        ("no steps", spec(steps=[]), "spec-form", "steps"),
        ("a step with no type", spec(steps=[{}]), "spec-form", "steps[0].type"),
        ("a step that is not an object", spec(steps=["sleep"]), "spec-form", "steps[0]"),
        ("a name with a newline", spec(name="a\nb"), "spec-form", "name"),
        ("a source with a directory in it", spec(code={"commit": "a" * 40, "source": "bundle:../x.bundle"}), "spec-form", "code.source"),
        ("a deadline before not_before", spec(when={"not_before": 200, "deadline": 100}), "spec-form", "when.deadline"),
        ("a version that is a string", spec(v="1"), "spec-form", "v"),
        ("a missing version", spec(v=DEL), "spec-form", "v"),
        ("a spec that is not an object", [1, 2], "spec-form", "object"),
        ("version 2, with fields version 1 does not know", {**spec(v=2), "new_thing": 1}, "spec-version", "2"),
        ("an abbreviated commit", spec(code={"commit": "0b7c959", "source": "remote"}), "commit-not-full", "0b7c959"),
        ("an uppercase commit", spec(code={"commit": "A" * 40, "source": "remote"}), "commit-not-full", "AAAA"),
        ("a 41-digit commit", spec(code={"commit": "a" * 41, "source": "remote"}), "commit-not-full", "aaaa"),
        ("a commit that is not hex", spec(code={"commit": "g" * 40, "source": "remote"}), "commit-not-full", "gggg"),
        ("a step type the registry does not hold", spec(steps=[{"type": "acceptance-rev8"}]), "step-unknown", "acceptance-rev8"),
        ("a card the configuration does not hold", spec(card="u51-9"), "card-unknown", "u51-9"),
        ("an image the registry does not hold", spec(image="nope"), "image-unknown", "nope"),
        ("when.window (S3's calendar)", spec(when={"window": "nightly"}), "window-unsupported", "nightly"),
        ("a signature that is a number", spec(signature=5), "spec-form", "signature"),
    ]
    for label, obj, name, frag in cases:            # through a real submit: the refusal must also be the job's record
        jid, r = sub(root, cfg, obj)
        got = f"{r.name}: {r.why}" if r else None
        check(f"spec: {label} is refused {name}, naming {frag!r}, and the job's record says so",
              got is not None and got.startswith(name + ":") and frag in got and rec(root, "jobs", jid, -2).get("name") == name, str(got))
    for label, raw, frag in (("not JSON", b"{no", "valid JSON"), ("a repeated key", b'{"v":1,"v":1}', "repeated"), ("NaN", b'{"v":NaN}', "NaN"),
                             ("a byte-order mark", b'\xef\xbb\xbf{}', "BOM"), ("bytes that are not UTF-8", b"\xff\xfe", "UTF-8")):
        jid, r = sub(root, cfg, raw)
        got = f"{r.name}: {r.why}" if r else None
        check(f"spec: {label} is refused spec-form", got is not None and got.startswith("spec-form:") and frag in got and rec(root, "jobs", jid, -2).get("name") == "spec-form", str(got))
    check("spec: bundle:FILE, remote, card any and a card of the configuration are accepted",
          all(verdict(lambda c=c: P.validate(c, cfg, R.FAKE_REGISTRY)) is None
              for c in (spec(code={"commit": "a" * 40, "source": "remote"}), spec(card="any"), spec(code={"commit": "b" * 40, "source": "bundle:x.bundle"}))))
    check("spec: a signature is `present-unverified` when there, `absent` when not, `unreadable` with no object, and never `verified`",
          P.sig_status(spec(signature="abc")) == "present-unverified" and P.sig_status(spec()) == "absent" and P.sig_status(None) == "unreadable")


# ---------------------------------------------------------------------------------------- queue

def rename_exclusive():
    """MEASURED here, never assumed from the platform's name: do 8 threads racing to rename one directory to one target
    ever see more than one succeed? On POSIX rename(2) gives the losers ENOENT; on the Windows this was written on, all 8
    succeed (20 rounds of 20), so the claim's exclusivity is a property of the platform and not of this code."""
    d = os.path.join(TMP, "rename-probe")
    os.makedirs(os.path.join(d, "q"))
    os.makedirs(os.path.join(d, "r"))
    several = 0
    for rnd in range(10):
        src, dst = os.path.join(d, "q", f"p{rnd}"), os.path.join(d, "r", f"p{rnd}")
        os.mkdir(src)
        won, bar = [], threading.Barrier(8)

        def go():
            bar.wait()
            try:
                os.rename(src, dst)
                won.append(1)
            except OSError:
                pass
        ts = [threading.Thread(target=go) for _ in range(8)]
        [x.start() for x in ts]
        [x.join() for x in ts]
        several += len(won) > 1
    return several == 0, f"racing renames of one directory all succeeded in {several} of 10 rounds on this platform (measured), so a claim by rename is not exclusive here"


def group_queue():
    root, cfg = mkroot("q-submit")
    j, r = sub(root, cfg, spec())
    q = os.path.join(root, "queue")
    check("queue: a submit lands whole: queue/ID holds spec.json and job.jsonl, and no .tmp- entry is left",
          r is None and sorted(os.listdir(os.path.join(q, j))) == ["job.jsonl", "spec.json"] and not [n for n in os.listdir(q) if n.startswith(".")])
    os.mkdir(os.path.join(q, ".tmp-j000099"))
    open(os.path.join(q, ".tmp-j000099", "spec.json"), "w").write("{}")
    listed = [e[0] for e in S.queue_entries(root)]
    c = claim1(root, cfg)
    check("queue: a half-made submit (a .tmp- directory) is not in the queue and is never claimed",
          listed == [j] and c and c[0] == j and claim1(root, cfg) is None, str(listed))
    root, cfg = mkroot("q-order")
    ids = {t: sub(root, cfg, spec(name=t, priority=p))[0] for t, p in (("low", 10), ("high1", 50), ("mid", 30), ("high2", 50))}
    got = []
    for _ in range(4):
        c = claim1(root, cfg)
        got.append(c[1]["name"] if c else None)
        if c:
            S.finish(root, c[0], c[2], "done")
    check("queue: order is priority, then submission: high1, high2 (same priority, submitted in that order), mid, low",
          got == ["high1", "high2", "mid", "low"], str(got))
    root, cfg = mkroot("q-bigids")
    open(os.path.join(root, "ids", "j999998"), "w").close()         # the next ids are j999999 and j1000000: as text, seven digits sort first
    a, b = sub(root, cfg, spec(name="a", priority=50))[0], sub(root, cfg, spec(name="b", priority=50))[0]
    order = [e[0] for e in S.queue_entries(root)]
    check("queue: two jobs of one priority claim in submission order across the id 999999 to 1000000 boundary (ids are numbers, not text)",
          (a, b) == ("j999999", "j1000000") and order == [a, b], f"{a} {b} {order}")
    serve_here(root, cfg)
    check("queue: `list` shows what ended in id order across the same boundary", [j["id"] for j in R.list_jobs(root)["finished"]] == [a, b])
    root, cfg = mkroot("q-ids")
    a = safely(lambda: sub(root, cfg, spec())[0])
    b = safely(lambda: sub(root, cfg, spec())[0])
    how = safely(S.cancel, root, b, "t")
    serve_here(root, cfg)
    c = safely(lambda: sub(root, cfg, spec())[0])
    d = safely(lambda: sub(root, cfg, b"{")[0])
    e = safely(lambda: sub(root, cfg, spec())[0])
    check("queue: cancel of a queued job (b, in this scenario) answers `dequeued`", how == "dequeued", str(how))
    check("queue: ids never repeat, though every earlier job has left queue/ and running/ (one cancelled, one run, one refused)",
          len({a, b, c, d, e}) == 5 and [a, b, c, d, e] == sorted([a, b, c, d, e]), str([a, b, c, d, e]))
    out, lock = [], threading.Lock()

    def alloc():
        for _ in range(25):
            i = S.alloc_id(root)
            with lock:
                out.append(i)
    ts = [threading.Thread(target=alloc) for _ in range(8)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    check("queue: 8 threads allocating 25 ids each get 200 different ids", len(out) == 200 and len(set(out)) == 200, f"{len(set(out))} distinct")
    root, cfg = mkroot("q-claim")
    j = sub(root, cfg, spec())[0]
    check("queue: a second claim of a claimed job loses", S.claim(root, j) is True and S.claim(root, j) is False)
    exclusive, why = rename_exclusive()
    if not exclusive:
        skip("queue: of 8 claimants racing for one job, exactly one wins", why)
        skip("queue: a claim and a cancel racing for one queued job: one wins, never both", why)
    else:
        wins, seen = [], []
        for rnd in range(30):
            j = sub(root, cfg, spec())[0]
            res, bar = [], threading.Barrier(8)

            def go():
                bar.wait()
                try:
                    res.append(S.claim(root, j))
                except Exception as ex:                      # any error is recorded, and fails the check
                    res.append(repr(ex))
            ts = [threading.Thread(target=go) for _ in range(8)]
            [t.start() for t in ts]
            [t.join() for t in ts]
            wins.append(res.count(True))
            seen += [x for x in res if x not in (True, False)]
        check("queue: of 8 claimants racing for one job, exactly one wins, in each of 30 rounds", wins == [1] * 30 and not seen, f"{wins} {seen[:2]}")
        pairs = set()
        for rnd in range(30):
            j = sub(root, cfg, spec())[0]
            res, bar = {}, threading.Barrier(2)

            def go1():
                bar.wait()
                res["claim"] = S.claim(root, j)

            def go2():
                bar.wait()
                res["cancel"] = safely(S.cancel, root, j, "t")
            ts = [threading.Thread(target=go1), threading.Thread(target=go2)]
            [t.start() for t in ts]
            [t.join() for t in ts]
            pairs.add((res.get("claim"), res.get("cancel")))
        check("queue: a claim and a cancel racing for one queued job: one wins, never both and never neither, in 30 rounds",
              pairs <= {(True, "stop-requested"), (False, "dequeued")}, str(pairs))
    root, cfg = mkroot("q-cancel")
    j = sub(root, cfg, spec())[0]
    how = safely(S.cancel, root, j, "t")
    again = verdict(lambda: S.cancel(root, j, "t"))
    check("queue: a queued job is cancelled out of the queue: it is in jobs/ with outcome cancelled and its sums, and is never claimed",
          how == "dequeued" and not os.path.exists(os.path.join(root, "queue", j)) and rec(root, "jobs", j).get("outcome") == "cancelled"
          and verify_sums(os.path.join(root, "jobs", j)) == [] and claim1(root, cfg) is None, str(how))
    check("queue: cancelling it again is `job-ended`, and an id nobody has is `job-unknown`",
          (again or "").startswith("job-ended:") and (verdict(lambda: S.cancel(root, "j999999", "t")) or "").startswith("job-unknown:"))
    check("queue: what is not a job id (a path, a name, too few digits) is `job-unknown` before anything touches the disk, and j and six digits is accepted",
          all((verdict(lambda x=x: S.parse_job_id(x)) or "").startswith("job-unknown:") for x in ("../queue", "j12", "x000001", "j000001/..", "")) and S.parse_job_id("j000012") == "j000012")
    root, cfg = mkroot("q-hold")
    j = sub(root, cfg, spec())[0]
    S.hold(root, cfg, "u50-0", "t", "a person is using the card")
    serve_here(root, cfg)
    held_left = os.path.isdir(os.path.join(root, "queue", j))
    twice = verdict(lambda: S.hold(root, cfg, "u50-0", "u", "again"))
    S.release(root, cfg, "u50-0", "t")
    serve_here(root, cfg)
    check("queue: a held card claims nothing (the job stays queued), and release lets it run",
          held_left and os.path.isdir(os.path.join(root, "jobs", j)) and rec(root, "jobs", j).get("outcome") == "done")
    check("queue: a second hold is `card-held`, naming who holds the card", (twice or "").startswith("card-held:") and " t " in (twice or ""), str(twice))
    check("queue: release of a card that is not held is `card-not-held`", (verdict(lambda: S.release(root, cfg, "u50-0", "t")) or "").startswith("card-not-held:"))
    check("queue: hold or release of a card nobody has is `card-unknown`",
          (verdict(lambda: S.hold(root, cfg, "zz", "t", "")) or "").startswith("card-unknown:")
          and (verdict(lambda: S.release(root, cfg, "zz", "t")) or "").startswith("card-unknown:"))
    root, cfg = mkroot("q-hold-runs")
    j = sub(root, cfg, spec(steps=[{"type": "sleep", "seconds": 1.5}]))[0]
    th = threading.Thread(target=serve_here, args=(root, cfg))
    th.start()
    wait_for(lambda: os.path.isdir(os.path.join(root, "running", j)))
    S.hold(root, cfg, "u50-0", "t", "while it runs")
    during = os.path.isdir(os.path.join(root, "running", j))
    th.join(30)
    check("queue: a hold made while a job runs does not touch it: the job was still running when the hold was made, and ends done",
          during and rec(root, "jobs", j).get("outcome") == "done", f"running at the hold: {during}")
    root, cfg = mkroot("q-deadline")
    now = time.time()
    over = sub(root, cfg, spec(name="over", when={"deadline": now - 100}, priority=90))[0]
    ok = sub(root, cfg, spec(name="ok", priority=5))[0]
    c = claim1(root, cfg, now)
    ref = recs(root, "jobs", over)
    check("queue: a job past its deadline is refused `deadline-passed`, with a record, and the scan goes on to the next job",
          c and c[0] == ok and [r["type"] for r in ref] == ["submitted", "refused", "ended"] and rec(root, "jobs", over, 1).get("name") == "deadline-passed"
          and rec(root, "jobs", over).get("outcome") == "refused")
    root, cfg = mkroot("q-notbefore")
    late = sub(root, cfg, spec(name="late", when={"not_before": now + 3600}, priority=50))[0]
    ok = sub(root, cfg, spec(name="ok", priority=5))[0]
    c = claim1(root, cfg, now)
    check("queue: a job whose not_before is in the future waits (the job behind it runs first), and is claimed once the time has come",
          c and c[0] == ok and os.path.isdir(os.path.join(root, "queue", late)) and claim1(root, cfg, now) is None
          and (claim1(root, cfg, now + 7200) or [None])[0] == late)
    root, cfg = mkroot("q-corrupt")
    bad = sub(root, cfg, spec(name="bad", priority=99))[0]
    open(os.path.join(root, "queue", bad, "spec.json"), "w").write("not json")
    ok = sub(root, cfg, spec(name="ok"))[0]
    c = claim1(root, cfg)
    ref = recs(root, "jobs", bad)
    check("queue: a queued spec that cannot be read is refused `queue-corrupt` with a record, and the job behind it is claimed",
          c and c[0] == ok and rec(root, "jobs", bad, -2).get("name") == "queue-corrupt" and rec(root, "jobs", bad).get("outcome") == "refused")
    root, cfg = mkroot("q-cards", cards=("u50-0", "u50-1"))
    j1, j2, ja = (sub(root, cfg, spec(card=x))[0] for x in ("u50-1", "u50-0", "any"))
    serve_here(root, cfg)
    cards = {j: rec(root, "jobs", j, 2).get("card") for j in (j1, j2, ja)}
    check("queue: a job runs on the card it names (u50-1 on u50-1), and `any` on the first free one", cards[j1] == "u50-1" and cards[j2] == "u50-0" and cards[ja] in ("u50-0", "u50-1"), str(cards))
    root, cfg = mkroot("q-gone")
    j = sub(root, cfg, spec())[0]
    other = C.validate_config({"cards": [{"id": "u50-7", "kind": "xrt"}]})
    S.claim_next(root, other, "u50-7", time.time(), R.FAKE_REGISTRY)
    ref = recs(root, "jobs", j)
    check("queue: a queued job whose card has left the configuration is refused `card-unknown` when claimed",
          rec(root, "jobs", j, -2).get("name") == "card-unknown" and rec(root, "jobs", j).get("outcome") == "refused")


# ---------------------------------------------------------------------------------------- records

def run_one(root, cfg, s, stop_first=False):
    """Submit s, claim it, optionally ask for a stop before it runs, run it: (id, outcome)."""
    j = sub(root, cfg, s)[0]
    jid, sp, log = S.claim_next(root, cfg, "u50-0", time.time(), R.FAKE_REGISTRY)
    if stop_first:
        S.cancel(root, jid, "tester")
    return jid, R.run_claimed(root, jid, sp, log, R.FakeRunner())


def run_stop_during(root, cfg, s, delay):
    """Claim s and run it in a thread; ask for a stop `delay` seconds in, during the first step: (id, outcome)."""
    sub(root, cfg, s)
    jid, sp, log = S.claim_next(root, cfg, "u50-0", time.time(), R.FAKE_REGISTRY)
    res = []
    th = threading.Thread(target=lambda: res.append(R.run_claimed(root, jid, sp, log, R.FakeRunner())))
    th.start()
    time.sleep(delay)
    S.cancel(root, jid, "tester")
    th.join(60)
    return jid, (res or [None])[0]


def group_records():
    root, cfg = mkroot("r-done")
    jd = sub(root, cfg, spec(card="any", signature="sig-text", steps=[{"type": "sleep", "seconds": 0}, {"type": "sleep", "seconds": 0}]))[0]
    serve_here(root, cfg)
    rs, d = recs(root, "jobs", jd), os.path.join(root, "jobs", jd)
    check("records: a job's directory holds spec.json, job.jsonl and SHA256SUMS, and nothing is left in queue/ or running/",
          sorted(os.listdir(d)) == ["SHA256SUMS", "job.jsonl", "spec.json"] and not os.listdir(os.path.join(root, "queue")) and not os.listdir(os.path.join(root, "running")))
    check("records: job.jsonl runs submitted, claimed, started, one step record each, ended",
          [r["type"] for r in rs] == ["submitted", "claimed", "started", "step", "step", "ended"], str([r["type"] for r in rs]))
    check("records: the last word is an outcome from the named set", rs[-1:] and rs[-1].get("outcome") == "done" and rs[-1]["outcome"] in N.OUTCOMES)
    check("records: SHA256SUMS lists every file and each sum matches (an independent sha256sum -c), and the scheduler's own check agrees",
          verify_sums(d) == [] and S.check_sums(d) == [])
    if shutil.which("sha256sum"):
        d2 = os.path.join(TMP, "sums-copy")
        shutil.copytree(d, d2)
        open(os.path.join(d2, "job.jsonl"), "ab").write(b"x")
        sumc = lambda dd: subprocess.run(["sha256sum", "-c", "SHA256SUMS"], cwd=dd, capture_output=True, text=True).returncode
        check("records: SHA256SUMS is a real one: `sha256sum -c` passes in a job's directory and fails on a copy with one byte added", sumc(d) == 0 and sumc(d2) != 0)
    else:
        skip("records: SHA256SUMS is a real one (`sha256sum -c`)", "no sha256sum on PATH")
    check("records: every record names its card, and `any` is resolved to the card's id from the claimed record on",
          all(r.get("card") for r in rs) and rs[1]["card"] == "u50-0" and rs[1]["card_requested"] == "any" and all(r["card"] == "u50-0" for r in rs[1:]),
          str([r.get("card") for r in rs]))
    check("records: the fake runner says it touched no card, in started and in ended", rs[2].get("runner") == "fake" and rs[2].get("card_touched") is False
          and rs[-1].get("card_touched") is False)
    check("records: the submitter's signature is recorded `present-unverified`, never `verified`; the owner is the system user",
          rs[0]["signature"] == "present-unverified" and rs[0]["owner"] == S.user() and "verified" not in {r.get("signature") for r in rs})
    for label, steps, want, extra in (
            ("every step passes", [{"type": "sleep", "seconds": 0}], "done", {}),
            ("a step finds something", [{"type": "find", "count": 2}, {"type": "sleep", "seconds": 0}], "done-with-findings", {"findings": 2, "steps_ran": 2}),
            ("a step fails, so the rest are skipped by name", [{"type": "sleep", "seconds": 0}, {"type": "fail", "reason": "boom"}, {"type": "find"}, {"type": "sleep", "seconds": 0}],
             "failed", {"steps_ran": 2})):
        r2, c2 = mkroot("r-" + label[:9].replace(" ", "-"))
        jid, out = run_one(r2, c2, spec(steps=steps))
        end, st = recs(r2, "jobs", jid)[-1], [x for x in recs(r2, "jobs", jid) if x["type"] == "step"]
        check(f"records: {label}: outcome {want}", out == want and end["outcome"] == want and all(end.get(k) == v for k, v in extra.items()), str(end))
        if want == "failed":
            check("records: the steps after a failure are `skipped`, each with its reason, and a failure outranks a finding earlier or later",
                  [x["status"] for x in st] == ["pass", "failed", "skipped", "skipped"] and st[2]["reason"] == "an earlier step failed" and end["findings"] == 0)
    r2, c2 = mkroot("r-fail-find")
    jid, out = run_one(r2, c2, spec(steps=[{"type": "find"}, {"type": "fail"}]))
    check("records: a failure after a finding is `failed`, not `done-with-findings`", out == "failed")
    r2, c2 = mkroot("r-stop")
    jid, out = run_stop_during(r2, c2, spec(steps=[{"type": "sleep", "seconds": 0.5}] * 3), 0.1)
    st, rs = [x for x in recs(r2, "jobs", jid) if x["type"] == "step"], recs(r2, "jobs", jid)
    check("records: a stop asked during a step ends the job at that step's end: outcome cancelled, the later steps skipped by name, the stop recorded with who asked",
          out == "cancelled" and [x["status"] for x in st] == ["pass", "skipped", "skipped"] and st[1]["reason"] == "a stop was requested"
          and any(r["type"] == "stop_requested" and r.get("by") == "tester" for r in rs) and rec(r2, "jobs", jid).get("outcome") == "cancelled")
    check("records: a stop does not cut the step it arrives in short: that step ran its whole 0.5 s and passed", st[0]["status"] == "pass" and st[0]["elapsed_s"] >= 0.48, str(st[0]))
    r2, c2 = mkroot("r-start")
    jid, out = run_one(r2, c2, spec(steps=[{"type": "sleep", "seconds": 0.05}] * 2), stop_first=True)
    st = [x for x in recs(r2, "jobs", jid) if x["type"] == "step"]
    check("records: a stop asked before the job starts is honoured at the start: no step runs, both are skipped, outcome cancelled",
          out == "cancelled" and [x["status"] for x in st] == ["skipped", "skipped"] and rec(r2, "jobs", jid).get("steps_ran") == 0, str([x["status"] for x in st]))
    r2, c2 = mkroot("r-deaf")
    jid, out = run_stop_during(r2, c2, spec(steps=[{"type": "ignore-stop", "seconds": 0.5}, {"type": "sleep", "seconds": 0.05}, {"type": "sleep", "seconds": 0.05}]), 0.1)
    st = [x for x in recs(r2, "jobs", jid) if x["type"] == "step"]
    check("records: ignore-stop is no safe point: a stop asked during it is honoured only after the next step (pass, pass, skipped), still cancelled",
          out == "cancelled" and [x["status"] for x in st] == ["pass", "pass", "skipped"] and st[0]["safe_point"] is False and st[1]["safe_point"] is True, str([x["status"] for x in st]))
    r2, c2 = mkroot("r-late")
    jid, out = run_stop_during(r2, c2, spec(steps=[{"type": "sleep", "seconds": 0.5}]), 0.15)
    check("records: a stop that comes when no step is left to skip ends `done`, and the stop is recorded all the same",
          out == "done" and "stop_requested" in types(r2, "jobs", jid))
    r2, c2 = mkroot("r-refuse")
    jid, ref = sub(r2, c2, spec(needs=[]))
    rs, d = recs(r2, "jobs", jid), os.path.join(r2, "jobs", jid)
    check("records: a refused submit leaves jobs/ID: what was sent (spec.rejected, in place of spec.json), a `refused` record naming the field, an end record with outcome refused, and sums",
          ref and ref.name == "spec-form" and [r["type"] for r in rs] == ["submitted", "refused", "ended"] and rs[1]["name"] == "spec-form" and "needs" in rs[1]["why"]
          and rs[2]["outcome"] == "refused" and rs[2]["refusal"] == "spec-form" and open(os.path.join(d, "spec.rejected"), "rb").read() == json.dumps(spec(needs=[])).encode()
          and verify_sums(d) == [] and sorted(os.listdir(d)) == ["SHA256SUMS", "job.jsonl", "spec.rejected"])
    jid, ref = sub(r2, c2, b"{not json")
    check("records: a spec that is not JSON is a job too (outcome refused, signature `unreadable`), and its id is a new one",
          ref.name == "spec-form" and rec(r2, "jobs", jid, 0).get("signature") == "unreadable" and rec(r2, "jobs", jid).get("outcome") == "refused")
    r2, c2 = mkroot("r-nocard")
    jn, jm, jr = sub(r2, c2, b"[]")[0], sub(r2, c2, spec(card=5))[0], sub(r2, c2, spec(needs=[]))[0]
    cs = lambda j: [(x.get("card"), bool(x.get("card_unreadable"))) for x in recs(r2, "jobs", j)]
    check("records: a submit whose card cannot be read (a spec that is not an object, a card that is not a string) says `card: null` and why in every record, and invents no card",
          cs(jn) == [(None, True)] * 3 and cs(jm) == [(None, True)] * 3, f"{cs(jn)} {cs(jm)}")
    check("records: a refused submit whose card is readable names it in every record, with no card_unreadable", cs(jr) == [("u50-0", False)] * 3, str(cs(jr)))
    r2, c2 = mkroot("r-corrupt")
    ja, jb = sub(r2, c2, spec(card="u50-0", priority=90))[0], sub(r2, c2, spec(card="any", priority=80))[0]
    for j in (ja, jb):
        open(os.path.join(r2, "queue", j, "spec.json"), "w").write("not json")
    claim1(r2, c2)
    cc = [[x.get("card") for x in recs(r2, "jobs", j)] for j in (ja, jb)]
    check("records: a queued spec that cannot be read is refused `queue-corrupt` in records that name the card from the job's own submitted record (u50-0; any, as asked), not null",
          cc == [["u50-0"] * 3, ["any"] * 3] and rec(r2, "jobs", ja, -2).get("name") == "queue-corrupt", str(cc))
    pn = os.path.join(TMP, "nocard.jsonl")
    refused_write = verdict_exc(lambda: S.Log(pn, "j000001", None).append("x"), ValueError) and not os.path.exists(pn)
    said = S.Log(pn, "j000001", None, "no card in the spec").append("x")
    no_job = S.Log(os.path.join(TMP, "no-job.jsonl"), None, None).append("x")
    check("records: a job's log refuses to write a record that names no card and gives no reason; given a reason the record says so; a log that is no job's may name no card",
          refused_write and said.get("card") is None and said.get("card_unreadable") == "no card in the spec" and no_job.get("card") is None)
    d = os.path.join(root, "jobs", jd)
    open(os.path.join(d, "job.jsonl"), "ab").write(b"x")
    open(os.path.join(d, "extra"), "wb").write(b"y")
    bad = S.check_sums(d)
    os.unlink(os.path.join(d, "spec.json"))
    check("records: tampering is named: a changed file, an unlisted file, a listed file gone",
          any("job.jsonl differs" in b for b in bad) and any("extra is not listed" in b for b in bad) and any("spec.json is listed and missing" in b for b in S.check_sums(d)), str(bad))
    check("records: an outcome that is not in the set cannot be written, and a refusal that is not in the table cannot be raised",
          verdict_exc(lambda: S.Log(os.path.join(TMP, "x.jsonl"), "j", "c").end("bogus"), ValueError) and verdict_exc(lambda: N.Refusal("made-up", "x"), KeyError))
    p = os.path.join(TMP, "torn.jsonl")
    open(p, "wb").write(b'{"type":"a"}\n{"type":"b"')
    S.Log(p, "j", "c").append("c")
    check("records: a torn last line is broken off before the next record, so every record after it parses",
          [r["type"] for r in S.read_records(p)] == ["a", "c"] and open(p, "rb").read().count(b"\n") == 3)
    root, cfg = mkroot("r-restart")
    j1, j2 = sub(root, cfg, spec(name="killed"))[0], sub(root, cfg, spec(name="ended-not-moved"))[0]
    for j, last in ((j1, None), (j2, "done")):
        shutil.move(os.path.join(root, "queue", j), os.path.join(root, "running", j))
        lg = S.Log(os.path.join(root, "running", j, "job.jsonl"), j, "u50-0")
        lg.append("claimed", card_kind="xrt")
        lg.append("started", runner="fake")
        if last:
            lg.end(last)
    j3 = sub(root, cfg, spec(name="next"))[0]
    serve_here(root, cfg)
    r1, r2_ = recs(root, "jobs", j1), recs(root, "jobs", j2)
    check("records: a job found in running/ at a service start is recorded `interrupted` and not re-run; one already ended is only moved",
          rec(root, "jobs", j1).get("outcome") == "interrupted" and "step" not in [r["type"] for r in r1] and [r["type"] for r in r2_].count("ended") == 1 and rec(root, "jobs", j2).get("outcome") == "done"
          and verify_sums(os.path.join(root, "jobs", j1)) == [] and rec(root, "jobs", j3).get("outcome") == "done" and not os.listdir(os.path.join(root, "running")))


def verdict_exc(fn, exc):
    try:
        fn()
    except exc:
        return True
    return False


# ---------------------------------------------------------------------------------------- locks (real processes)

def spawn(root, *args):
    return subprocess.Popen([sys.executable, "-B", "-I", os.path.join(SCHED, "cft_sched.py"), "--root", root, "serve", "--poll", "0.05"] + list(args),
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def group_locks():
    root, cfg = mkroot("l-nolocks")
    j = sub(root, cfg, spec())[0]
    rc, out, err = cli(root, "serve", "--drain", "--no-locks")
    cl = S.read_records(os.path.join(root, "cards", "u50-0", "card.jsonl"))
    if S.HAVE_FLOCK:
        check("locks: `serve --no-locks` where flock exists is refused `locks-required`, with a record, and runs nothing",
              rc == 2 and "locks-required" in err and "locks-required" in open(os.path.join(root, "refusals.jsonl")).read() and not cl and os.path.isdir(os.path.join(root, "queue", j)))
        skip("locks: `serve --no-locks` runs without locks and says so by name", "this platform has flock(2): the option is refused instead")
        skip("locks: serve without flock is refused `locks-unavailable`", "this platform has flock(2)")
    else:
        check("locks: `serve --no-locks` runs without locks and says so by name, in its output and in the card's record",
              rc == 0 and "SKIPPED" in out and cl and cl[0]["type"] == "service_start" and cl[0]["locks"] == "skipped" and not os.path.exists(os.path.join(root, "lock")))
        rc, out, err = cli(root, "serve", "--drain")
        check("locks: where there is no flock(2), `serve` is refused `locks-unavailable` by name, with a record",
              rc == 2 and "locks-unavailable" in err and "locks-unavailable" in open(os.path.join(root, "refusals.jsonl")).read())
        for n in ("a second service on the same root is refused", "the card lock is held while the job runs", "a service killed mid-job leaves an orphan the next start records"):
            skip(f"locks: {n}", "no flock(2) on this platform")
        return
    root, cfg = mkroot("l-svc")
    p1 = spawn(root)
    try:
        up = wait_for(lambda: (json.loads(cli(root, "status", "--json")[1])["service"]["info"] or {}).get("pid") == p1.pid, 60)
        rc, out, err = cli(root, "serve", "--drain")
        st = json.loads(cli(root, "status", "--json")[1])
        check("locks: a second service on the same root is refused `lock-held`, with a record, and the first one still holds the lock",
              up and rc == 2 and "lock-held" in err and "lock-held" in open(os.path.join(root, "refusals.jsonl")).read() and st["service"]["running"] is True
              and st["service"]["info"]["pid"] == p1.pid, f"{up} {rc} {err[:80]} {st['service']}")
    finally:
        p1.kill()
        p1.wait()
    free = wait_for(lambda: S.lock_held(os.path.join(root, "lock")) is False, 20)
    check("locks: the lock dies with its holder: after the service is killed another starts at once", free and cli(root, "serve", "--drain")[0] == 0)
    root, cfg = mkroot("l-card", cards=("u50-0", "u50-1"))
    j = sub(root, cfg, spec(card="u50-0", steps=[{"type": "sleep", "seconds": 4.0}]))[0]
    p = spawn(root, "--drain")
    try:
        running = wait_for(lambda: os.path.isdir(os.path.join(root, "running", j)), 30)
        held, other = S.lock_held(os.path.join(root, "cards", "u50-0", "CARDLOCK")), S.lock_held(os.path.join(root, "cards", "u50-1", "CARDLOCK"))
        st = json.loads(cli(root, "status", "--json")[1])
        states = {c["id"]: c["state"] for c in st["cards"]}
        check("locks: the card's lock is held while its job runs, and the other card's is free", running and held is True and other is False, f"{running} {held} {other}")
        check("locks: status says busy for the card running a job (its lock held) and ready for the other", states == {"u50-0": "busy", "u50-1": "ready"}, str(states))
        p.wait(60)
    finally:
        if p.poll() is None:
            p.kill()
            p.wait()
    check("locks: the card's lock is free again once the job has ended, and the job is done",
          S.lock_held(os.path.join(root, "cards", "u50-0", "CARDLOCK")) is False and rec(root, "jobs", j).get("outcome") == "done")
    root, cfg = mkroot("l-foreign")
    j = sub(root, cfg, spec())[0]
    fd = os.open(os.path.join(root, "cards", "u50-0", "CARDLOCK"), os.O_RDWR | os.O_CREAT)
    S.fcntl.flock(fd, S.fcntl.LOCK_EX | S.fcntl.LOCK_NB)             # a holder the scheduler does not own
    rc, out, _ = cli(root, "serve", "--drain")
    state = json.loads(cli(root, "status", "--json")[1])["cards"][0]["state"]
    left = os.path.isdir(os.path.join(root, "queue", j))
    os.close(fd)
    rc2, out2, _ = cli(root, "serve", "--drain")
    check("locks: a card whose lock someone else holds is not claimed on (the job stays queued, status says locked), and runs once the holder lets go",
          rc == 0 and left and "claimed" not in out and state == "locked" and rc2 == 0 and rec(root, "jobs", j).get("outcome") == "done", f"{state} {out!r}")
    root, cfg = mkroot("l-orphan")
    j1 = sub(root, cfg, spec(name="long", steps=[{"type": "sleep", "seconds": 30}]))[0]
    j2 = sub(root, cfg, spec(name="short"))[0]
    p = spawn(root)
    try:
        wait_for(lambda: os.path.isdir(os.path.join(root, "running", j1)), 30)
    finally:
        p.kill()
        p.wait()
    wait_for(lambda: S.lock_held(os.path.join(root, "cards", "u50-0", "CARDLOCK")) is False, 20)
    st = json.loads(cli(root, "status", "--json")[1])
    rc, out, _ = cli(root, "serve", "--drain")
    check("locks: a job whose service was killed shows as an orphan (running, its card lock free), and the next start records it `interrupted` and runs the rest",
          st["cards"][0]["state"] == "orphaned" and rc == 0 and f"recovered {j1}: interrupted" in out and rec(root, "jobs", j1).get("outcome") == "interrupted"
          and rec(root, "jobs", j2).get("outcome") == "done", f"{st['cards'][0]['state']} {out[:200]}")


# ---------------------------------------------------------------------------------------- cli

def group_cli():
    rc, out, err = cli(None, "list")
    check("cli: with no --root and no $CFT_SCHED_ROOT the command is refused `root-unset`, printed as `refused: NAME: why` on stderr, exit 2", rc == 2 and err.startswith("refused: root-unset: "), err[:80])
    repo = os.path.join(TMP, "repo")
    os.makedirs(os.path.join(repo, ".git"))
    rc, out, err = cli(os.path.join(repo, "state"), "init")
    check("cli: a root inside a git working tree is refused `root-in-checkout`, and nothing is created there",
          rc == 2 and "root-in-checkout" in err and not os.path.exists(os.path.join(repo, "state")))
    wt = os.path.join(TMP, "wt")
    os.makedirs(wt)
    open(os.path.join(wt, ".git"), "w").write("gitdir: elsewhere\n")
    rc, out, err = cli(wt, "init")
    check("cli: so is a root that is a worktree itself (its .git is a file), and no config.json is written in it",
          rc == 2 and "root-in-checkout" in err and not os.path.exists(os.path.join(wt, "config.json")))
    ghost = os.path.join(TMP, "no-such-root")
    rc, out, err = cli(ghost, "status")
    check("cli: a root that does not exist is refused `root-missing` and is not created (only `init` makes a root)", rc == 2 and "root-missing" in err and not os.path.exists(ghost))
    root = os.path.join(TMP, "c-root")
    rc, out, err = cli(root, "init")
    cfg_text = open(os.path.join(root, "config.json"), "rb").read()
    cfg = C.load_config(root)
    check("cli: `init` makes the root with the layout and a config.json that loads", rc == 0 and all(os.path.isdir(os.path.join(root, d)) for d in C.LAYOUT + ("cards/u50-0",)))
    if os.name == "posix":
        check("cli: `init` makes the root private, mode 0700, so that only the box user can submit", os.stat(root).st_mode & 0o077 == 0, oct(os.stat(root).st_mode))
    else:
        skip("cli: `init` makes the root private, mode 0700", "file modes mean nothing on this platform")
    ROOTS.append(root)
    check("cli: $CFT_SCHED_ROOT names the root when there is no --root, and --root wins over it",
          cli(None, "status", env={C.ENV_ROOT: root})[0] == 0 and cli(root, "status", env={C.ENV_ROOT: ghost})[0] == 0 and cli(None, "status", env={C.ENV_ROOT: ghost})[0] == 2)
    rc, out, err = cli(root, "init")
    check("cli: `init` again is refused `config-exists`, leaves config.json as it was, and leaves a record in refusals.jsonl",
          rc == 2 and "config-exists" in err and open(os.path.join(root, "config.json"), "rb").read() == cfg_text and "config-exists" in open(os.path.join(root, "refusals.jsonl")).read())
    check("cli: the retention defaults are Logan's doubled figures: an idle sample every 7.5 minutes, clones 14 days, passing logs 360 days, every record kept; the disk floor stays 5 GB",
          cfg["retention"] == {"idle_sample_minutes": 7.5, "clone_days": 14, "passing_log_days": 360, "record_days": None} and cfg["floors"] == {"disk_free_gb": 5}, str(cfg["retention"]))
    check("cli: the default window is the nightly 18:00 to 08:00 in the machine's own zone, and a card carries an id and a kind",
          cfg["windows"] == {"zone": "local", "list": [{"name": "nightly", "start": "18:00", "end": "08:00"}]} and cfg["cards"] == [{"id": "u50-0", "kind": "xrt"}])
    check("cli: a file states only what it changes: the retention is merged over the defaults", C.validate_config({**GOOD, "retention": {"clone_days": 3}})["retention"]["clone_days"] == 3
          and C.validate_config({**GOOD, "retention": {"clone_days": 3}})["retention"]["passing_log_days"] == 360)
    bad = [("an unknown top-level key", {**GOOD, "colour": 1}, "colour"), ("no cards", {"images": []}, "cards"), ("an empty list of cards", {"cards": []}, "cards"),
           ("an unknown key of a card", {"cards": [{"id": "a", "kind": "xrt", "address": "x"}]}, "cards[0].address"),
           ("a card with no kind", {"cards": [{"id": "a"}]}, "cards[0].kind"), ("a card kind nobody serves", {"cards": [{"id": "a", "kind": "serial"}]}, "cards[0].kind"),
           ("a repeated card id", {"cards": [{"id": "a", "kind": "xrt"}, {"id": "a", "kind": "xrt"}]}, "cards[1].id"), ("a card named any", {"cards": [{"id": "any", "kind": "xrt"}]}, "cards[0].id"),
           ("an image sum that is not hex", {**GOOD, "images": [{"name": "q", "path": "p", "sha256": "xyz"}]}, "images[0].sha256"),
           ("an image with no path", {**GOOD, "images": [{"name": "q", "sha256": "0" * 64}]}, "images[0].path"),
           ("a window time of 25:00", {**GOOD, "windows": {"list": [{"name": "n", "start": "25:00", "end": "08:00"}]}}, "windows.list[0].start"),
           ("a window that starts and ends together", {**GOOD, "windows": {"list": [{"name": "n", "start": "08:00", "end": "08:00"}]}}, "windows.list[0]"),
           ("a zone with a space", {**GOOD, "windows": {"zone": "Mountain Time"}}, "windows.zone"), ("a floor that is a string", {**GOOD, "floors": {"disk_free_gb": "5"}}, "floors.disk_free_gb"),
           ("a negative retention", {**GOOD, "retention": {"clone_days": -1}}, "retention.clone_days"), ("an unknown retention key", {**GOOD, "retention": {"weeks": 1}}, "retention.weeks")]
    for label, obj, frag in bad:
        got = verdict(lambda obj=obj: C.validate_config(obj))
        check(f"cli: config.json with {label} is refused `config-form`, naming {frag!r}", got and got.startswith("config-form:") and frag in got, str(got))
    check("cli: record_days may be null (every record kept), and a floor of 0 is allowed", verdict(lambda: C.validate_config({**GOOD, "retention": {"record_days": None}, "floors": {"disk_free_gb": 0}})) is None)
    r2 = os.path.join(TMP, "c-bad")
    os.makedirs(r2)
    ROOTS.append(r2)
    rc0, _, err0 = cli(r2, "serve", "--drain")
    open(os.path.join(r2, "config.json"), "w").write('{"cards": [{"id": "a", "kind": "xrt"}], "colour": 1}')
    rc1, _, err1 = cli(r2, "serve", "--drain")
    check("cli: serve with no config.json is refused `config-missing`, and with a bad one `config-form` naming the key; each leaves a record",
          rc0 == 2 and "config-missing" in err0 and rc1 == 2 and "config-form" in err1 and "colour" in err1
          and [r["name"] for r in S.read_records(os.path.join(r2, "refusals.jsonl"))] == ["config-missing", "config-form"])
    good = os.path.join(TMP, "spec-a.json")
    open(good, "w").write(json.dumps(spec(name="alpha", priority=50)))
    rc, out, err = cli(root, "submit", good)
    rc2, out2, err2 = cli(root, "submit", "-", stdin=json.dumps(spec(name="beta", priority=10)))
    rc3, out3, err3 = cli(root, "submit", "-", stdin=json.dumps(spec(name="gamma", priority=10, needs=[])))
    check("cli: submit prints the id of the job it queued (from a file and from stdin), and a refused spec exits 2 naming the job, the refusal and the field",
          rc == 0 and out.strip() == "submitted j000001" and rc2 == 0 and out2.strip() == "submitted j000002"
          and rc3 == 2 and re.match(r"refused j000003: spec-form: field needs is unknown", err3), f"{out!r} {out2!r} {err3!r}")
    bare = os.path.join(TMP, "c-bare")
    os.makedirs(bare)
    open(os.path.join(bare, "config.json"), "w").write(json.dumps(GOOD))
    ROOTS.append(bare)
    rc, out, err = cli(bare, "submit", good)
    check("cli: a root made by hand with only a config.json works: the verbs make the layout good", rc == 0 and out.strip() == "submitted j000001" and os.path.isdir(os.path.join(bare, "queue", "j000001")), err[-120:])
    rc, out, err = cli(root, "submit", os.path.join(TMP, "nope.json"))
    check("cli: submit of a file that is not there says so and queues nothing", rc != 0 and "cannot read" in err and sorted(os.listdir(os.path.join(root, "queue"))) == ["j000001", "j000002"])
    rc, out, _ = cli(root, "list")
    lj = json.loads(cli(root, "list", "--json")[1])
    check("cli: list shows the queue in claim order, then what ended; --json says the same", rc == 0 and out.index("j000001") < out.index("j000002") < out.index("j000003")
          and [j["id"] for j in lj["queued"]] == ["j000001", "j000002"] and lj["finished"][0]["refusal"] == "spec-form")
    rc, out, _ = cli(root, "status")
    st = json.loads(cli(root, "status", "--json")[1])
    check("cli: status names the card's state, the queue and the last outcome (here: ready, two queued, the refusal)",
          rc == 0 and "card u50-0 (xrt): ready" in out and "queue   : 2 queued" in out and "last    : j000003 refused (spec-form)" in out
          and st["cards"][0]["state"] == "ready" and st["last"]["outcome"] == "refused")
    rc, out, err = cli(root, "hold", "u50-0", "--why", "testing by hand")
    rc2, out2, err2 = cli(root, "hold", "u50-0")
    rc3, out3, _ = cli(root, "serve", "--drain", *([] if S.HAVE_FLOCK else ["--no-locks"]))
    rc4, out4, _ = cli(root, "status")
    check("cli: hold puts a card on hold (status says held, with who and why), a second hold is `card-held`, and a held card runs nothing",
          rc == 0 and rc2 == 2 and "card-held" in err2 and "card u50-0 (xrt): held" in out4 and "testing by hand" in out4 and rc3 == 0 and "claimed" not in out3
          and sorted(os.listdir(os.path.join(root, "queue"))) == ["j000001", "j000002"], f"{out4!r}")
    check("cli: hold of an unknown card is `card-unknown` and leaves a record naming the card",
          cli(root, "hold", "zz")[0] == 2 and S.read_records(os.path.join(root, "refusals.jsonl"))[-1]["card"] == "zz")
    rc, out, err = cli(root, "release", "u50-0")
    rc2, out2, err2 = cli(root, "release", "u50-0")
    check("cli: release lifts it; releasing again is `card-not-held`", rc == 0 and rc2 == 2 and "card-not-held" in err2)
    rc, out, err = cli(root, "cancel", "j000002")
    rc2, out2, err2 = cli(root, "cancel", "j000002")
    rc3, out3, err3 = cli(root, "cancel", "j999999")
    rc4, out4, err4 = cli(root, "cancel", "../x")
    check("cli: cancel takes a queued job out of the queue; again is `job-ended`; an unknown id and a path are `job-unknown`",
          rc == 0 and "outcome cancelled" in out and rc2 == 2 and "job-ended" in err2 and rc3 == 2 and "job-unknown" in err3 and rc4 == 2 and "job-unknown" in err4)
    rc, out, err = cli(root, "serve", "--drain", *([] if S.HAVE_FLOCK else ["--no-locks"]))
    rc2, out2, _ = cli(root, "status", "j000001")
    st = json.loads(cli(root, "status", "--json")[1])
    check("cli: serve --drain runs what is queued and exits 0; status for a job gives its outcome; status gives the last outcome and an empty queue",
          rc == 0 and "j000001 ended: done" in out and "j000001: jobs" in out2 and "outcome done" in out2 and st["queue"] == [] and st["last"]["id"] == "j000001" and st["last"]["outcome"] == "done", out2)
    check("cli: status of an id nobody has is `job-unknown`", cli(root, "status", "j424242")[0] == 2)
    live = os.path.join(TMP, "c-live")
    cli(live, "init")
    ROOTS.append(live)
    p = spawn(live, *([] if S.HAVE_FLOCK else ["--no-locks"]))
    try:
        rc, out, _ = cli(live, "submit", "-", stdin=json.dumps(spec(steps=[{"type": "sleep", "seconds": 1.5}] * 3)))     # while the service runs
        jid = out.split()[-1]
        started = wait_for(lambda: os.path.isdir(os.path.join(live, "running", jid)), 30)
        rc2, out2, _ = cli(live, "cancel", jid)
        ended = wait_for(lambda: os.path.isdir(os.path.join(live, "jobs", jid)), 30)
    finally:
        p.kill()
        p.wait()
    st = [x["status"] for x in recs(live, "jobs", jid) if x["type"] == "step"]
    check("cli: a job submitted while the service loops is picked up, and `cancel` of it while it runs stops it at a safe point (cancelled; a step passed, the last skipped)",
          rc == 0 and started and ended and "stop requested" in out2 and rec(live, "jobs", jid).get("outcome") == "cancelled" and st[:1] == ["pass"] and st[-1:] == ["skipped"], f"{out2!r} {st}")
    if os.name == "posix" and shutil.which("bash"):
        p = subprocess.run(["bash", os.path.join(SCHED, "cft-sched"), "--root", root, "status"], capture_output=True, text=True, env={**os.environ, "PYTHON": sys.executable})
        h = subprocess.run(["bash", os.path.join(SCHED, "cft-sched"), "--help"], capture_output=True, text=True, env={**os.environ, "PYTHON": sys.executable})
        check("cli: `bash hw/sched/cft-sched` runs the command, and --help lists every verb",
              p.returncode == 0 and "cft-sched status" in p.stdout and h.returncode == 0 and all(v in h.stdout for v in ("init", "submit", "list", "status", "cancel", "hold", "release", "serve")), p.stderr[:200] + h.stderr[:200])
    else:
        skip("cli: `bash hw/sched/cft-sched` runs the command, and --help lists every verb", "needs POSIX bash")


def table_checks():
    """Two checks on the refusals' table. (1) It holds every name of the study's section 5.4, read from the study. (2) Each name it
    gives to S1 was raised by a scenario and left a record exactly where its row says: `job` a job's `refused` record and nowhere
    else, `root` a line of refusals.jsonl and nowhere else, `job, root` both, `none` (no usable root to write in) stderr only."""
    sp = os.path.join(ROOT, "docs", "studies", "SCHED-A-card-scheduler.md")
    if not os.path.isfile(sp):
        skip("the table: it holds every refusal name of the study's section 5.4", "the study is not in this tree")
    else:
        with open(sp, encoding="utf-8") as fh:
            text = fh.read()
        study = set(re.findall(r"`([a-z]+(?:-[a-z]+)+)`", text[text.index("### 5.4 Refusals, by name"):text.index("### 5.5")]))
        missing = sorted(study - set(N.REFUSALS))
        check("the table: it holds every refusal name of the study's section 5.4 (read from the study, not copied)", len(study) >= 30 and not missing, f"{len(study)} names read, missing {missing}")
    in_jobs, in_root = set(), set()
    for r in ROOTS:
        in_root |= {x.get("name") for x in S.read_records(os.path.join(r, "refusals.jsonl"))}
        jd = os.path.join(r, "jobs")
        for j in os.listdir(jd) if os.path.isdir(jd) else []:
            in_jobs |= {x.get("name") for x in recs(r, "jobs", j) if x["type"] == "refused"}
    off = {"locks-unavailable"} if S.HAVE_FLOCK else {"lock-held", "locks-required"}        # what this platform cannot raise
    wrong = []
    for n, (by, where, _m) in N.REFUSALS.items():
        if by == "S1" and n not in off:
            want = ("job" in where.split(", "), "root" in where.split(", "))
            if (n in in_jobs, n in in_root) != want or (where == "none" and n not in SEEN):
                wrong.append(f"{n} (row says {where}; jobs {n in in_jobs}, refusals.jsonl {n in in_root}, stderr {n in SEEN})")
    check("the table: every refusal it gives to S1 was raised by a scenario and left a record exactly where its row says", not wrong, f"wrong: {wrong}")


# ---------------------------------------------------------------------------------------- plants

GROUPS = {"spec": group_spec, "queue": group_queue, "records": group_records, "cli": group_cli, "locks": group_locks}


def make_copy(name: str, edits: list) -> str:
    d = os.path.join(TMP, "plant-" + name)
    os.makedirs(os.path.join(d, "sched"))
    shutil.copy(os.path.join(HERE, "test_sched.py"), d)
    for f in os.listdir(SCHED):
        if f.endswith(".py") or f == "cft-sched":
            shutil.copy(os.path.join(SCHED, f), os.path.join(d, "sched"))
    for fname, old, new in edits:
        p = os.path.join(d, "sched", fname)
        text = open(p, "r", encoding="utf-8", newline="").read()
        if text.count(old) != 1:
            raise SystemExit(f"plant {name}: {old[:60]!r} found {text.count(old)} times in {fname}; the plant did not apply, so it would prove nothing")
        open(p, "w", encoding="utf-8", newline="").write(text.replace(old, new))
    return d


def run_copy(d: str, groups: str):
    p = subprocess.run([sys.executable, "-B", "-I", os.path.join(d, "test_sched.py"), "--only", groups, "--no-plants"], capture_output=True, text=True, timeout=900,
                       env={**os.environ, "SCHED_TEST_ROOT": ROOT})
    m = re.search(r"sched test: (\d+) checks, (\d+) failed", p.stdout)
    return p.returncode, int(m.group(1)) if m else -1, [ln[6:].strip() for ln in p.stdout.splitlines() if ln.startswith("  FAIL  ")], p.stderr


def whole(d: str) -> bool:
    imp = "import sys; sys.path.insert(0, sys.argv[1]); import sched_names, sched_spec, sched_config, sched_state, sched_run, cft_sched"
    return subprocess.run([sys.executable, "-B", "-I", "-c", imp, os.path.join(d, "sched")], capture_output=True).returncode == 0


def E(f, old, new):
    return (f, old, new)


PLANTS = [  # (what is wrong, edits, the groups written for it, a fragment of the check that must fail, None | "flock" | "noflock": where it can run)
    ("a second service is allowed", [E("sched_run.py", "    if not svc.acquire(tries=3, delay=0.1):", "    svc.acquire(tries=3, delay=0.1)\n    if False:")], "locks", "a second service on the same root is refused", "flock"),
    ("a claim that two workers can win", [E("sched_state.py", "        return True\n    except FileNotFoundError:\n        return False", "        return True\n    except FileNotFoundError:\n        return True")],
     "queue", "a second claim of a claimed job loses", False),
    ("an unknown field is accepted", [E("sched_spec.py", '        if key not in _children(""):', "        if False:")], "spec", "an unknown field is refused spec-form", False),
    ("a refused job that leaves no record", [E("sched_state.py", '    os.rename(tmp, os.path.join(root, "jobs", jid))\n    return jid, refusal', '    __import__("shutil").rmtree(tmp)\n    return jid, refusal')],
     "records", "a refused submit leaves jobs/ID", False),
    ("a job id is reused", [E("sched_state.py", "for m in map(ID_RE.match, os.listdir(d))", 'for m in map(ID_RE.match, os.listdir(os.path.join(root, "queue")) + os.listdir(os.path.join(root, "running")))'),
                            E("sched_state.py", "os.open(os.path.join(d, jid), os.O_CREAT | os.O_EXCL | os.O_WRONLY)", "os.open(os.path.join(d, jid), os.O_CREAT | os.O_WRONLY)")],
     "queue", "ids never repeat", False),
    ("the card lock is not held for the job", [E("sched_run.py", "                try:\n                    if hold_info(root, cid) is not None:\n                        continue",
                                                  "                lk.release()\n                try:\n                    if hold_info(root, cid) is not None:\n                        continue")],
     "locks", "the card's lock is held while its job runs", "flock"),
    ("a root inside a checkout is accepted", [E("sched_config.py", '        if os.path.lexists(os.path.join(d, ".git")):', "        if False:")], "cli", "a root inside a git working tree is refused", False),
    ("a hold does not stop claims", [E("sched_run.py", "                if hold_info(root, cid) is not None:\n                    continue\n                lk", "                lk"),
                                     E("sched_run.py", "                    if hold_info(root, cid) is not None:\n                        continue", "                    if False:\n                        continue")],
     "queue", "a held card claims nothing", False),
    ("the queue ignores priority", [E("sched_state.py", '-(e[1] or {}).get("priority", 0), id_key(e[0])))', "id_key(e[0])))")], "queue", "order is priority, then submission", False),
    ("ids are sorted as text in the queue", [E("sched_state.py", '-(e[1] or {}).get("priority", 0), id_key(e[0])))', '-(e[1] or {}).get("priority", 0), e[0]))')], "queue",
     "two jobs of one priority claim in submission order across the id 999999", None),
    ("ids are sorted as text in the lists", [E("sched_run.py", ", key=id_key)", ")")], "queue", "`list` shows what ended in id order across the same boundary", None),
    ("a cancel finds nothing to take out of the queue", [E("sched_state.py", "        os.rename(q, j)  ", "        raise FileNotFoundError(q)  ")], "queue", "a queued job is cancelled out of the queue", False),
    ("a submit with no readable card invents one", [E("sched_state.py", 'log = Log(os.path.join(tmp, "job.jsonl"), jid, card, why)', 'log = Log(os.path.join(tmp, "job.jsonl"), jid, card or "any")')],
     "records", "a submit whose card cannot be read (", None),
    ("a queued spec that cannot be read is refused in records that name no card", [E("sched_state.py", "card0, why0 = job_card(d)  ", 'card0, why0 = None, "plant"  ')],
     "records", "a queued spec that cannot be read is refused `queue-corrupt` in records that name the card", None),
    ("a job's log writes a record that names no card and says nothing", [E("sched_state.py", "        if self.job is not None and self.card is None and not self.no_card:", "        if False:")],
     "records", "a job's log refuses to write a record that names no card", None),
    ("a stop does not stop a running job", [E("sched_run.py", "            if not skip and at_safe_point and stop.requested():", "            if False:")], "records", "a stop asked during a step ends the job", False),
    ("the start of a job is not a safe point", [E("sched_run.py", "skip, at_safe_point = None, True ", "skip, at_safe_point = None, False")], "records", "a stop asked before the job starts is honoured at the start", False),
    ("a stop cuts the step it arrives in short", [E("sched_run.py", '                sleep(st.get("seconds", 0))', '                [sleep(0.01) for _ in range(int(st.get("seconds", 0) * 100)) if not stop.requested()]')],
     "records", "a stop does not cut the step it arrives in short", False),
    ("ignore-stop is taken for a safe point", [E("sched_run.py", '            at_safe_point = kind != "ignore-stop"', "            at_safe_point = True")], "records", "ignore-stop is no safe point", False),
    ("the sums are written before the end record", [E("sched_state.py", "    log.end(outcome, **fields)\n    write_sums(d)\n", "    write_sums(d)\n    log.end(outcome, **fields)\n")], "records", "SHA256SUMS lists every file", False),
    ("the sums leave job.jsonl out", [E("sched_state.py", 'if n != "SHA256SUMS" and os.path.isfile(os.path.join(d, n)))', 'if n not in ("SHA256SUMS", "job.jsonl") and os.path.isfile(os.path.join(d, n)))')],
     "records", "SHA256SUMS lists every file", False),
    ("a present signature is recorded verified", [E("sched_spec.py", 'return "present-unverified" if "signature" in obj else "absent"', 'return "verified" if "signature" in obj else "absent"')], "spec", "a signature is `present-unverified`", False),
    ("the retention defaults are the study's undoubled 7 days", [E("sched_config.py", '"clone_days": 14', '"clone_days": 7')], "cli", "the retention defaults are Logan's doubled figures", False),
    ("a job left in running/ is not recovered at a restart", [E("sched_run.py", "        recover(root, out)", "        pass")], "records", "a job found in running/ at a service start", False),
    ("a record names no card", [E("sched_state.py", '"job": self.job, "card": self.card}', '"job": self.job}')], "records", "every record names its card", False),
    ("`any` is not resolved to the card that claimed the job", [E("sched_state.py", "        log.card = card_id", "        pass  # log.card = card_id")], "records", "every record names its card", False),
    ("an outcome outside the set is accepted", [E("sched_state.py", "        if outcome not in OUTCOMES:", "        if False:")], "records", "an outcome that is not in the set cannot be written", False),
    ("a job past its deadline is run", [E("sched_state.py", "            if dl is not None and now_t > dl:", "            if False:")], "queue", "a job past its deadline is refused `deadline-passed`", False),
    ("not_before is ignored", [E("sched_state.py", "            if isinstance(nb, (int, float)) and now_t < nb:", "            if False:")], "queue", "a job whose not_before is in the future waits", False),
    ("a job id from the command line is not checked", [E("sched_state.py", "    if not isinstance(text, str) or not ID_RE.match(text):", "    if not isinstance(text, str):")], "queue", "what is not a job id", False),
    ("the service takes a card whose lock another holds", [E("sched_run.py", "                if not lk.acquire():\n                    continue ", "                lk.acquire()\n                if False:\n                    continue ")], "locks",
     "a card whose lock someone else holds is not claimed on", "flock"),
    ("a cancel of a running job leaves its STOP where the runner does not look", [E("sched_state.py", 'fd = os.open(os.path.join(r, "STOP"),', 'fd = os.open(os.path.join(r, "STOP.x"),')], "cli",
     "a job submitted while the service loops is picked up", False),
    ("--no-locks is not said in the record", [E("sched_run.py", '        locks = "skipped" if skip_locks else "flock"', '        locks = "flock"')], "locks", "`serve --no-locks` runs without locks and says so", "noflock"),
    ("--no-locks is accepted where flock exists", [E("sched_run.py", "    if skip_locks and HAVE_FLOCK:", "    if False:")], "locks", "`serve --no-locks` where flock exists is refused", "flock"),
    ("an abbreviated commit is accepted", [E("sched_spec.py", r'COMMIT_RE = re.compile(r"[0-9a-f]{40}\Z")', r'COMMIT_RE = re.compile(r"[0-9a-f]{7,40}\Z")')], "spec", "an abbreviated commit is refused", False),
    ("version 2 is read as version 1", [E("sched_spec.py", '    if obj["v"] != SPEC_VERSION:', "    if False:")], "spec", "version 2, with fields version 1 does not know", False),
    ("a step type the registry does not hold is accepted", [E("sched_spec.py", "        if params is None:", "        if False:")], "spec", "a step type the registry does not hold is refused", False),
    ("when.window is accepted and the job runs at once", [E("sched_spec.py", '    if "window" in when:', "    if False:")], "spec", "when.window (S3's calendar) is refused", False),
    ("a card the configuration does not hold is accepted at submit", [E("sched_spec.py", 'if cfg is not None and card != "any" and card not in [c["id"] for c in cfg["cards"]]:', "if False:")],
     "spec", "a card the configuration does not hold is refused", False),
    ("init overwrites an existing config.json", [E("cft_sched.py", 'with open(path, "xb") as fh:', 'with open(path, "wb") as fh:')], "cli", "`init` again is refused `config-exists`", False),
    ("a second hold replaces the first", [E("sched_state.py", '"HOLD"), os.O_CREAT | os.O_EXCL | os.O_WRONLY | O_BINARY)', '"HOLD"), os.O_CREAT | os.O_TRUNC | os.O_WRONLY | O_BINARY)')],
     "queue", "a second hold is `card-held`", False),
    ("release of a card with no hold passes in silence", [E("sched_state.py", '        raise Refusal("card-not-held", f"{card} has no hold")', "        pass")], "queue", "release of a card that is not held is `card-not-held`", False),
    ("init makes the root readable by others", [E("sched_config.py", "os.makedirs(real, mode=0o700)", "os.makedirs(real); os.chmod(real, 0o755)")], "cli", "`init` makes the root private", "flock"),
    ("a refusal the table gives to S1 that nothing raises", [E("sched_names.py", '    "card-held": ("S1", "root",', '    "never-raised": ("S1", "root", "x"), "card-held": ("S1", "root",')],
     "spec,queue,records,cli,locks,table", "the table: every refusal it gives to S1", None),
    ("a name of the study's 5.4 is left out of the table", [E("sched_names.py", '    "job-exists": ("S2", "job",', '    "job-exists-x": ("S2", "job",')],
     "spec,queue,records,cli,locks,table", "the table: it holds every refusal name of the study's section 5.4", None),
    ("a name filed under job and root is recorded under one", [E("sched_state.py", '    if "root" in REFUSALS[r.name][1] and os.path.isdir(root):', '    if REFUSALS[r.name][1] == "root" and os.path.isdir(root):')],
     "spec,queue,records,cli,locks,table", "left a record exactly where its row says", None),
    ("an unknown key in config.json is accepted", [E("sched_config.py", "        if k not in required + optional:", "        if False:")], "cli", "config.json with an unknown top-level key is refused", False),
    ("a card's worker takes another card's job", [E("sched_state.py", "            if want in cards and want != card_id:\n                continue", "            if False:\n                continue")], "queue", "a job runs on the card it names", False),
]


def plants(only_text: str | None):
    ctl = {}
    if not only_text:
        for g in sorted({p[2] for p in PLANTS}):
            d = make_copy("control-" + g, [])
            rc, n, fails, err = run_copy(d, g)
            ctl[g] = n
            check(f"plants: the CONTROL (an unmodified copy of the code and of this test) passes the {g} group, {n} checks", rc == 0 and not fails and n > 0, "; ".join(fails)[:300] or err[-200:])
    for n, (label, edits, g, want, posix) in enumerate(PLANTS):
        if only_text and only_text not in label:
            continue
        if (posix == "flock" and not S.HAVE_FLOCK) or (posix == "noflock" and S.HAVE_FLOCK):
            skip(f"plant [{label}]", "needs POSIX (flock(2), file modes), which this platform lacks" if posix == "flock" else "needs a platform without flock(2)")
            continue
        try:
            d = make_copy(f"{n:02d}-" + re.sub(r"\W+", "-", label)[:24], edits)         # numbered: two labels may start alike
        except SystemExit as e:
            check(f"plant [{label}]: applies", False, str(e))
            continue
        if g not in ctl:
            ctl[g] = run_copy(make_copy("control-" + g, []), g)[1]
        rc, n, fails, err = run_copy(d, g)
        check(f"plant [{label}]: the copy is whole: it imports, and its {g} run made the control's {ctl[g]} checks, none cut short by a crash",
              whole(d) and n == ctl[g] and "Traceback" not in err, f"imports {whole(d)}, {n} checks against {ctl[g]}, stderr {err[-160:]!r}")
        hit = [f for f in fails if want in f]
        check(f"plant [{label}]: it turns the {g} group red at the check written for it", bool(hit), f"failing set: {[f[:80] for f in fails[:4]]}")
        print(f"  plant [{label}] -> {g}: failing set ({len(fails)}): " + " | ".join(f[:72] for f in fails[:6]) + (f" | ... {len(fails) - 6} more" if len(fails) > 6 else ""))


def main() -> int:
    global TMP
    only = set(sys.argv[sys.argv.index("--only") + 1].split(",")) if "--only" in sys.argv else None
    plant_text = sys.argv[sys.argv.index("--plant") + 1] if "--plant" in sys.argv else None
    TMP = tempfile.mkdtemp(prefix="sched-test-")
    t0 = time.time()
    try:
        for name, fn in GROUPS.items():
            if (only is None or name in only) and not plant_text:
                before, bad = CHECKS, len(FAILS)
                try:
                    fn()
                except Exception:
                    traceback.print_exc()
                    check(f"{name}: the group ran to its end", False, "it crashed (traceback above)")
                print(f"{name}: {CHECKS - before} checks, {len(FAILS) - bad} failed")
        if (only is None or "table" in only) and not plant_text:
            table_checks()
        if (only is None or "plants" in only) and "--no-plants" not in sys.argv:
            plants(plant_text)
    finally:
        shutil.rmtree(TMP, ignore_errors=True)
    print(f"sched test: {CHECKS} checks, {len(FAILS)} failed, {len(SKIPS)} skipped, {time.time() - t0:.0f} s")
    for f in FAILS:
        print("  FAILED:", f[:300])
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
