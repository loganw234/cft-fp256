#!/usr/bin/env python3
# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""The card scheduler's tests (parcels S1, S2 and S3a): no card, no XRT, no amd-arc-box, no network.

    python3 hw/test_sched.py [--only NAME,...] [--no-plants] [--plant TEXT]        (bash hw/test-sched.sh)

Groups of S1: spec (the job spec's table and refusals), queue (ids, atomic submit, order, claim, cancel, hold, deadlines),
records (job.jsonl, the outcomes, the sums, restart), cli (the state root, the configuration, every verb), locks (the
service's lock and the card's, with real processes), table (the checks that every refusal the table gives to S1, and to S2, was raised
by a scenario and left its record where its row says; each needs the groups of its parcel in the same run), then plants.
`locks` needs flock(2): where there is none (Windows) its checks are skipped by name, and the one check of the path without flock runs instead.

Groups of S2, the staged runner (hw/sched/sched_staged.py), run against the DRIVER's own stand-in and parsers, a scratch repository
for the remote and for the bundle, and a fake host tree (a Makefile that makes shell-script tools) for the build: code (the clone and its
assertions), build (make, ldd, the build id, `clone-built`; POSIX), images (the registry against the files), guard (the driver's
own find_card_users behind the card's lock, on synthetic tables and, on /proc, on real processes), steps (the registry of step types,
the parsers, run_step, dry jobs through the whole runner, the real-tool steps, the refusals; `--only steps:PART` runs one of its parts:
registry parsers run_step jobs real refusals). Windows skips by name what needs make, sh, nice, timeout or /proc. A run that starts the
driver's stand-in or the guard's real-process scenario collides with another suite doing the same on the machine (the driver's guard
sees every process): run one at a time. SCHED_TEST_MANIFESTS may name a directory of the three real cft_hw_*.manifest.txt files, which one
check of `images` reads (skipped by name otherwise).

Group of S3a, the nightly window (hw/sched/sched_calendar.py, sched_window.py), in parts (`--only window:PART`): calendar (the zone, the
changed-clock nights, stated dates), spec (the new fields and their refusals), claim (the queue holds a job for its window; the refusals at
the claim; `status` of a queued job), and, where bash, make, git and sha256sum are (skipped by name elsewhere), chain (nights of a window
job through a scratch repository holding the REAL driver and wrapper, with a fake python for the long run: the preflight rule, the fallback,
the noted failures, a refused build), driver (two nights against the driver's own `--dry-run`, the second resumed) and end (the end check, a
cancel, the STOP file, the launcher's refusals). The card is never involved; the plants of S3a are labelled "S3a: ".

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
import sched_build as BD      # noqa: E402
import sched_calendar as CAL  # noqa: E402
import sched_code as CODE     # noqa: E402
import sched_config as C     # noqa: E402
import sched_driver as DR     # noqa: E402
import sched_guard as GD      # noqa: E402
import sched_images as IM     # noqa: E402
import sched_names as N      # noqa: E402
import sched_proc as PR       # noqa: E402
import sched_run as R        # noqa: E402
import sched_spec as P       # noqa: E402
import sched_staged as SG     # noqa: E402
import sched_state as S      # noqa: E402
import sched_steps as ST      # noqa: E402
import sched_window as WD     # noqa: E402

CHECKS, FAILS, SKIPS = 0, [], []
TMP = ""
ONLY = None                    # the groups --only names, for a group that has parts
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


def wvalid(**kw) -> dict:
    """A window spec that validates against the default configuration (it names the window `nightly`)."""
    s = {"v": 1, "kind": "window", "name": "n", "card": "u50-0", "code": {"commit": "a" * 40, "source": "bundle:t.bundle"}, "when": {"window": "nightly"},
         "driver": {"out": os.path.abspath(os.sep + "x")}}
    for k, v in kw.items():
        s.pop(k, None) if v is DEL else s.__setitem__(k, v)
    return s


def clock_window(name, start_in, lasts) -> dict:
    """A window of config.json (zone local) that opens `start_in` seconds from now (negative: it has) and lasts `lasts` seconds, as HH:MM:SS read off the clock:
    it holds across midnight, because the calendar looks at the occurrence that began yesterday."""
    t = time.time()
    f = lambda x: time.strftime("%H:%M:%S", time.localtime(x))
    return {"name": name, "start": f(t + start_in), "end": f(t + start_in + lasts)}


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
    if not (isinstance(jid, str) and S.ID_RE.match(jid)):         # what `safely` returns for a crash is no id, and on Windows a path made of it is an OSError
        return []
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


def cli(root, *args, stdin=None, env=None, runner="fake"):
    """The command as a process. S1's groups ask for --runner fake (the step types they submit are the fake runner's); runner=None leaves the default."""
    e = {k: v for k, v in os.environ.items() if k != C.ENV_ROOT}
    e.update(env or {})
    p = subprocess.run([sys.executable, "-B", "-I", os.path.join(SCHED, "cft_sched.py")] + (["--root", root] if root else []) + (["--runner", runner] if runner else []) + list(args),
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
          P.validate(wvalid(), cfg, ST.StepRegistry())["priority"] == 10 and P.DEFAULT_PRIORITY["staged"] > P.DEFAULT_PRIORITY["window"])
    full = spec(priority=7, preempt="never", image="quad", card="any", signature="x", dry_run=True, estimate_s=60,
                code={"commit": "a" * 40, "source": "remote", "allow_unpushed": True,
                      "assert": {"rtl_tree": "b" * 40, "content": [["hw/x.py", "s", 1]], "ancestors": ["c" * 40]}},
                when={"not_before": 100, "deadline": 200, "window": "nightly"}, steps=[{"type": "sleep", "seconds": 1.5}, {"type": "fail", "reason": "r"},
                                                                                        {"type": "find", "count": 2}, {"type": "ignore-stop", "seconds": 0}])
    fullw = wvalid(priority=7, preempt="never", card="any", signature="x", dry_run=True, estimate_s=60, code=full["code"], when=full["when"],
                   preflight=[{"type": "vectors"}, {"type": "drytests", "known_flakes": ["a"], "noted_failures": ["b"]}, {"type": "driver-quick", "sweep_items": ["rint32-rne"]}],
                   driver={"out": os.path.abspath(os.sep + "x"), "resume": False, "images": ["quad"], "sweep_items": ["rint32-rne"],
                           "options": {"host_workers": 0, "sweep_chunk": 4096, "telemetry_seconds": 0, "deadline_grace": 1.5}})
    kids = lambda parent: {p.split(".")[1] for p in P.SPEC_FIELDS if p.startswith(parent + ".")}
    check("spec: every field of the table, set at once (a staged spec and a window spec between them), is accepted: the table and the validator agree",
          verdict(lambda: P.validate(full, cfg, R.FAKE_REGISTRY)) is None and verdict(lambda: P.validate(fullw, cfg, ST.StepRegistry())) is None
          and set(full) | set(fullw) == {p for p in P.SPEC_FIELDS if "." not in p} and set(full["code"]) == kids("code") and set(full["when"]) == kids("when")
          and set(fullw["driver"]) == kids("driver") and set(fullw["driver"]["options"]) == {p.split(".")[2] for p in P.SPEC_FIELDS if p.startswith("driver.options.")}
          and set(full["code"]["assert"]) == {p.split(".")[2] for p in P.SPEC_FIELDS if p.startswith("code.assert.")})
    cases = [
        ("an unknown field", spec(needs=[]), "spec-form", "needs"),
        ("owner (the scheduler fills it, a spec cannot)", spec(owner="x"), "spec-form", "owner"),
        ("an unknown field inside code", spec(code={"commit": "a" * 40, "source": "remote", "mirror": "x"}), "spec-form", "code.mirror"),
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
        ("a window the configuration does not hold (the default config has `nightly`)", spec(when={"window": "nope"}), "window-bad", "nope"),
        ("estimate_s of 0", spec(estimate_s=0), "spec-form", "estimate_s"),
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
    sid = lambda s: safely(lambda: sub(r2, c2, s)[0])              # a plant may make a submit raise: a check must fail, not the group
    jn, jm, jx, jr, je, jl = sid(b"[]"), sid(spec(card=5)), sid({"v": 1}), sid(spec(needs=[])), sid(spec(card="")), sid(spec(card="x" * 201))
    cs = lambda j: [(x.get("card"), bool(x.get("card_unreadable"))) for x in recs(r2, "jobs", j)]
    why = lambda j: {x.get("card_unreadable") for x in recs(r2, "jobs", j)}
    one = lambda j, phrase: len(why(j)) == 1 and phrase in next(iter(why(j)))
    check("records: a submit whose card cannot be read (a spec that is not an object, a card that is missing, a card that is not a string) says `card: null` and why in every record, "
          "with the reason for its case, and invents no card",
          all(cs(j) == [(None, True)] * 3 for j in (jn, jm, jx)) and one(jn, "not a JSON object") and one(jx, "is missing") and one(jm, "is not a string"),
          f"{cs(jn)} {cs(jm)} {cs(jx)} {why(jn)} {why(jx)} {why(jm)}")
    check("records: an empty card is not a card: a spec whose card is the empty string is recorded `card: null` in every record, and card_unreadable says it is empty",
          cs(je) == [(None, True)] * 3 and one(je, "is empty"), f"{cs(je)} {why(je)}")
    check("records: a card longer than 200 characters is not recorded as a card either: `card: null`, and card_unreadable says it is longer than 200 characters (it is a string, so not missing or not a string)",
          cs(jl) == [(None, True)] * 3 and one(jl, "is longer than 200 characters"), f"{cs(jl)} {why(jl)}")
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
    return subprocess.Popen([sys.executable, "-B", "-I", os.path.join(SCHED, "cft_sched.py"), "--root", root, "--runner", "fake", "serve", "--poll", "0.05"] + list(args),
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


# ---------------------------------------------------------------------------------------- the runner's fixtures (parcel S2)
# A scratch repository stands in for the remote and for the bundle, as hw/test_card_stress.py's scn_pool_tree does for the driver:
# no test of this file touches the network, a card, XRT or amd-arc-box. git is given its identity on the command line, so that
# nobody's configuration is read for it or changed.

PLAT = "xilinx_u50_gen3x16_xdma_5_202210_1"
FIX: dict = {}
GIT_ID = ["-c", "user.name=sched-test", "-c", "user.email=sched-test@example.invalid", "-c", "commit.gpgsign=false"]
GITIGNORE = ("host/*.o\nhost/*.so\nhost/gen/\nhost/device-test\nhost/api-test\nhost/remote-test\nhost/divsqrt-soak\nhost/clause5-soak\n"
             "host/cft-segrun\nhost/cft-audit\nhost/cft-resident\nhost/cft-selftest\nvectors/out/\n")
MANIFEST = ("artifact:      cft_hw.xclbin\nsha256:        {sha}\nbytes:         {n}\nhost:          amd-arc-box\ntarget:        hw\nplatform:      {plat}\n"
            "kernel_freq:   135000000\ngenerics:      EN_AUGADD=0 SEQ_SCRATCH_D=4096\n  hdlparam:    EN_FP32 = \"1\"\n  hdlparam:    BEAT_BITS = 256\n"
            "clock_cus:     {cus}\nroute_directive: AggressiveExplore\nrouted_wns_ns: 0.018   # whole design, shell included\n")


def git_t(repo, *args):
    return subprocess.run(["git"] + GIT_ID + (["-C", repo] if repo else []) + list(args), capture_output=True, text=True, timeout=120)


def commit_all(repo, files, msg):
    for rel, text in files.items():
        p = os.path.join(repo, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", newline="") as fh:
            fh.write(text)
    git_t(repo, "add", "-A")
    git_t(repo, "commit", "-q", "-m", msg)
    return git_t(repo, "rev-parse", "HEAD").stdout.strip()


def write_image(d, cus=4, name="cft_hw_quad", sums=True, manifest=True, plat=PLAT):
    """An image directory as the box has one: the xclbin, its SHA256SUMS and its manifest (hw/rebuild-2022.sh's format). Returns the registry entry."""
    os.makedirs(d, exist_ok=True)
    data = b"XCLBIN-TEST " + name.encode() + b"\n" * 3
    sha = hashlib.sha256(data).hexdigest()
    open(os.path.join(d, name + ".xclbin"), "wb").write(data)
    if sums:
        open(os.path.join(d, "SHA256SUMS"), "w", newline="").write(f"{sha}  {name}.xclbin\n")
    if manifest:
        open(os.path.join(d, name + ".manifest.txt"), "w", newline="").write(
            MANIFEST.format(sha=sha, n=len(data), plat=plat, cus=".".join(f"cft_krnl_{i + 1}" for i in range(cus))))
    return {"name": "quad", "path": os.path.join(d, name + ".xclbin"), "sha256": sha, "tiles": cus, "platform": plat}


def fixture():
    """Built once: the remote (c1, c2 on main), a clone of it holding one commit more (c3, never pushed) and a bundle of that
    clone's main made as `git bundle create FILE BRANCH` (no HEAD, the trap the lead's ledger names), the rtl/ tree of c1 and c2,
    and an image directory."""
    if FIX:
        return FIX
    base = os.path.join(TMP, "fx")
    rem, work = os.path.join(base, "remote"), os.path.join(base, "work")
    os.makedirs(os.path.join(base, "bundles"))
    git_t(None, "init", "-q", "-b", "main", rem)
    c1 = commit_all(rem, {"rtl/a.sv": "module a;\n", "hw/x.py": "MARK one\nMARK two\n", "host/y.c": "int y;\n", ".gitignore": GITIGNORE, **FAKE_TREE}, "c1")
    t1 = git_t(rem, "rev-parse", "HEAD:rtl").stdout.strip()
    c2 = commit_all(rem, {"rtl/a.sv": "module a2;\n", "hw/x.py": "MARK one\nMARK two\nNEW_TAG\n"}, "c2")
    t2 = git_t(rem, "rev-parse", "HEAD:rtl").stdout.strip()
    git_t(None, "clone", "-q", rem, work)
    c3 = commit_all(work, {"hw/x.py": "MARK one\nMARK two\nNEW_TAG\nUNPUSHED\n"}, "c3")
    git_t(work, "bundle", "create", os.path.join(base, "bundles", "u.bundle"), "main")
    open(os.path.join(base, "bundles", "bad.bundle"), "w").write("this is not a bundle\n")
    FIX.update(base=base, remote=rem, work=work, bundles=os.path.join(base, "bundles"), c1=c1, c2=c2, c3=c3, t1=t1, t2=t2,
               image=write_image(os.path.join(base, "images")))
    return FIX


def mkroot2(name, **over):
    """A root for the staged runner: the fixture's bundles and remote, the quad image registered, a card with its platform, short waits.
    `over` replaces a section of config.json."""
    fx = fixture()
    raw = {"cards": [{"id": "u50-0", "kind": "xrt", "platform": PLAT}], "images": [fx["image"]], "code": {"bundle_dir": fx["bundles"], "remote": fx["remote"]},
           "runner": {"kill_after_s": 2, "guard_poll_s": 0.05, "guard_wait_max_s": 1, "build_timeout_s": 120}}
    raw.update(over)
    root = os.path.join(TMP, name)
    os.makedirs(root)
    with open(os.path.join(root, "config.json"), "w") as fh:
        json.dump(raw, fh)
    cfg = C.load_config(root)
    C.ensure_layout(root, cfg)
    ROOTS.append(root)
    return root, cfg


def staged(**kw):
    """A staged spec: a dry job (the stand-in), the fixture's c2 from its bundle, one step. Keyword arguments replace its top-level fields."""
    s = {"v": 1, "kind": "staged", "name": "t", "card": "u50-0", "dry_run": True, "code": {"commit": fixture()["c2"], "source": "bundle:u.bundle"},
         "steps": [{"type": "api-test"}]}
    for k, v in kw.items():
        s.pop(k, None) if v is DEL else s.__setitem__(k, v)
    return s


def code_of(commit=None, source="bundle:u.bundle", **extra):
    return staged(code={"commit": commit or fixture()["c2"], "source": source, **extra})


def job(root, cfg, s, runner=None):
    """Submit s against the staged registry and serve it: (id, the end record, every record of the job)."""
    jid, ref = S.submit(root, cfg, s if isinstance(s, bytes) else json.dumps(s).encode(), (runner.registry if runner else ST.StepRegistry()))
    if not ref:
        R.serve(root, cfg, runner or SG.StagedRunner(root, cfg), drain=True, poll=0.02, skip_locks=not S.HAVE_FLOCK, out=lambda x: None)
    rs = recs(root, "jobs", jid)
    return jid, (rs[-1] if rs else {}), rs


def refusal_of(rs):
    r = next((x for x in rs if x["type"] == "refused"), None)
    return f"{r['name']}: {r['why']}" if r else ""


def legs_of(rs):
    return [r for r in rs if r["type"] == "leg"]


def prepop(root, sha, at=None):
    """A clone already in the cache at clones/SHA, checked out at `at` (default SHA): the way a cache gets edited, or left behind."""
    d = os.path.join(root, "clones", sha)
    git_t(None, "clone", "-q", "--no-checkout", FIX["work"], d)
    git_t(d, "checkout", "-q", "--detach", at or sha)
    return d


# ---------------------------------------------------------------------------------------- code

def group_code():
    fx = fixture()
    root, cfg = mkroot2("c-main")
    j, end, rs = job(root, cfg, code_of())
    cr = next((r for r in rs if r["type"] == "code"), {})
    check("code: a commit in a bundle (made as `git bundle create FILE BRANCH`, so it has no HEAD) is cloned, checked out detached and asserted: "
          "HEAD, a clean status, the rtl/ tree, pushed; the job ends done",
          end.get("outcome") == "done" and cr.get("head") == fx["c2"] and cr.get("status_lines") == 0 and cr.get("rtl_tree") == fx["t2"] and cr.get("pushed") == "pushed"
          and cr.get("origin") == "bundle" and cr.get("reused") is False and os.path.isdir(os.path.join(root, "clones", fx["c2"], ".git")), str(cr)[:300])
    j2, end2, rs2 = job(root, cfg, code_of(source="bundle:not-there.bundle"))
    cr2 = next((r for r in rs2 if r["type"] == "code"), {})
    check("code: a second job at the same commit finds the clone in the cache and asserts it (reused; its source is not asked for: a bundle that is gone does not matter)",
          end2.get("outcome") == "done" and cr2.get("reused") is True and cr2.get("head") == fx["c2"], refusal_of(rs2))
    j3, end3, rs3 = job(root, cfg, code_of(commit=fx["c1"], source="remote"))
    cr3 = next((r for r in rs3 if r["type"] == "code"), {})
    check("code: the same from the remote (config.json's code.remote): cloned, asserted, pushed",
          end3.get("outcome") == "done" and cr3.get("origin") == "remote" and cr3.get("head") == fx["c1"] and cr3.get("pushed") == "pushed", refusal_of(rs3))
    root, cfg = mkroot2("c-missing")
    j, end, rs = job(root, cfg, code_of(commit="f" * 40))
    why = refusal_of(rs)
    left = [n for n in os.listdir(os.path.join(root, "clones"))]
    gone = refusal_of(job(root, cfg, code_of(source="bundle:nope.bundle"))[2])
    unreadable = refusal_of(job(root, cfg, code_of(source="bundle:bad.bundle"))[2])
    r2, c2 = mkroot2("c-nosrc", code={"bundle_dir": None, "remote": None})
    nb, nr = refusal_of(job(r2, c2, code_of())[2]), refusal_of(job(r2, c2, code_of(source="remote"))[2])
    check("code: a full commit the bundle does not hold is refused `commit-missing`, naming it, and leaves no clone and no half-made one behind",
          why.startswith("commit-missing:") and "f" * 40 in why and end.get("outcome") == "refused" and left == [], f"{why!r} {left}")
    check("code: a bundle that is not in code.bundle_dir, one that git cannot read, and a source nobody configured (no bundle_dir, no remote), are `commit-missing` too, each saying what is not there",
          gone.startswith("commit-missing:") and "nope.bundle" in gone and nb.startswith("commit-missing:") and "bundle_dir" in nb
          and nr.startswith("commit-missing:") and "code.remote" in nr and unreadable.startswith("commit-missing:") and "could not clone" in unreadable
          and not [n for n in os.listdir(os.path.join(root, "clones")) if n.startswith(".")], f"{gone!r} {nb!r} {nr!r} {unreadable!r}")
    root, cfg = mkroot2("c-unpushed")
    j, end, rs = job(root, cfg, code_of(commit=fx["c3"]))
    ju, endu, rsu = job(root, cfg, code_of(commit=fx["c3"], allow_unpushed=True))
    cu = next((r for r in rsu if r["type"] == "code"), {})
    check("code: a commit no branch of the remote holds is refused `commit-unpushed` unless the spec says `allow_unpushed`, and then the job runs and its code record SAYS it was not pushed",
          refusal_of(rs).startswith("commit-unpushed:") and "allow_unpushed" in refusal_of(rs) and endu.get("outcome") == "done" and cu.get("pushed") == "unpushed" and cu.get("allow_unpushed") is True,
          f"{refusal_of(rs)!r} {endu.get('outcome')} {cu.get('pushed')}")
    ru, cu_ = mkroot2("c-noremote", code={"bundle_dir": fx["bundles"], "remote": os.path.join(fx["base"], "no-such-remote")})
    ja = job(ru, cu_, code_of())
    jb = job(ru, cu_, code_of(allow_unpushed=True))
    cb = next((r for r in jb[2] if r["type"] == "code"), {})
    rn, cn = mkroot2("c-noremote2", code={"bundle_dir": fx["bundles"], "remote": None})
    jc = job(rn, cn, code_of())
    check("code: a remote that cannot be read (or none configured) does not SHOW the commit pushed: `commit-unpushed` saying so, and `allow_unpushed` records it `unknown`",
          refusal_of(ja[2]).startswith("commit-unpushed:") and "could not be read" in refusal_of(ja[2]) and jb[1].get("outcome") == "done" and cb.get("pushed") == "unknown"
          and refusal_of(jc[2]).startswith("commit-unpushed:") and "names no remote" in refusal_of(jc[2]), f"{refusal_of(ja[2])!r} {cb.get('pushed')} {refusal_of(jc[2])!r}")
    rem = os.path.join(TMP, "c-prune-remote")                           # a remote of its own: the fixture's is shared, and a branch of this one is deleted
    git_t(None, "init", "-q", "-b", "main", rem)
    b0 = commit_all(rem, {"hw/x.py": "MARK one\n"}, "b0")
    git_t(rem, "checkout", "-q", "-b", "feature")
    f1 = commit_all(rem, {"hw/x.py": "MARK one\nFEATURE\n"}, "f1")
    git_t(rem, "checkout", "-q", "main")
    root, cfg = mkroot2("c-prune", code={"bundle_dir": fx["bundles"], "remote": rem})
    first = job(root, cfg, code_of(commit=f1, source="remote"))        # f1 is held by `feature` alone: cloned, pushed
    other = job(root, cfg, code_of(commit=b0, source="remote"))        # b0 by `main`
    git_t(rem, "branch", "-q", "-D", "feature")                       # the branch is deleted on the remote; both clones are in the cache
    again = job(root, cfg, code_of(commit=f1, source="bundle:not-there.bundle"))
    still = job(root, cfg, code_of(commit=b0, source="bundle:not-there.bundle"))
    cf, cs = (next((r for r in x[2] if r["type"] == "code"), {}) for x in (first, still))
    held = git_t(os.path.join(root, "clones", f1), "for-each-ref", "--format=%(refname)", "refs/pushed/").stdout.split()
    check("code: a cached clone does not go on answering `pushed` for a branch the remote has since deleted (the pushed check fetches with --prune): the commit only that branch held is "
          "refused `commit-unpushed` at the next job, the cache reused (its source not asked for), while a commit `main` still holds stays pushed and the clone's refs/pushed/ is main's alone",
          first[1].get("outcome") == "done" and cf.get("pushed") == "pushed" and other[1].get("outcome") == "done" and again[1].get("outcome") == "refused"
          and refusal_of(again[2]).startswith("commit-unpushed:") and still[1].get("outcome") == "done" and cs.get("pushed") == "pushed" and cs.get("reused") is True
          and held == ["refs/pushed/main"], f"{first[1].get('outcome')} {cf.get('pushed')} {again[1].get('outcome')} {refusal_of(again[2])!r} {still[1].get('outcome')} {cs.get('pushed')} {held}")
    root, cfg = mkroot2("c-head")
    prepop(root, fx["c2"], at=fx["c1"])
    j, end, rs = job(root, cfg, code_of())
    check("code: a clone in the cache whose HEAD is not the spec's commit is refused `head-mismatch`, naming both, and is not repaired",
          refusal_of(rs).startswith("head-mismatch:") and fx["c1"] in refusal_of(rs) and git_t(os.path.join(root, "clones", fx["c2"]), "rev-parse", "HEAD").stdout.strip() == fx["c1"], refusal_of(rs))
    root, cfg = mkroot2("c-dirty")
    d = prepop(root, fx["c2"])
    open(os.path.join(d, "hw", "x.py"), "a").write("an edit\n")
    a = refusal_of(job(root, cfg, code_of())[2])
    git_t(d, "checkout", "--", "hw/x.py")
    open(os.path.join(d, "stray.txt"), "w").write("untracked\n")
    b = refusal_of(job(root, cfg, code_of())[2])
    os.remove(os.path.join(d, "stray.txt"))
    git_t(d, "checkout", "-q", fx["c1"], "--", "hw/x.py")                # HEAD still c2, the working tree and index are c1's: a stale tree whose HEAD is right
    c = refusal_of(job(root, cfg, code_of())[2])
    check("code: a clone whose HEAD is right and whose status is not clean is refused `tree-dirty`: a changed tracked file, an untracked file, and a tree left at an older commit's content",
          a.startswith("tree-dirty:") and "hw/x.py" in a and b.startswith("tree-dirty:") and "stray.txt" in b and c.startswith("tree-dirty:") and "hw/x.py" in c, f"{a!r} {b!r} {c!r}")
    root, cfg = mkroot2("c-rtl")
    ok = job(root, cfg, code_of(**{"assert": {"rtl_tree": fx["t2"]}}))
    bad = refusal_of(job(root, cfg, code_of(**{"assert": {"rtl_tree": fx["t1"]}}))[2])
    check("code: the rtl/ tree the spec names is compared: c2's passes, c1's tree is refused `rtl-mismatch` naming both",
          ok[1].get("outcome") == "done" and bad.startswith("rtl-mismatch:") and fx["t1"] in bad and fx["t2"] in bad, f"{ok[1].get('outcome')} {bad!r}")
    root, cfg = mkroot2("c-content")
    fine = job(root, cfg, code_of(**{"assert": {"content": [["hw/x.py", "MARK", 2], ["hw/x.py", "NEW_TAG", 1], ["hw/x.py", "ABSENT", 0]]}}))
    many = refusal_of(job(root, cfg, code_of(**{"assert": {"content": [["hw/x.py", "MARK", 1]]}}))[2])
    none = refusal_of(job(root, cfg, code_of(**{"assert": {"content": [["hw/x.py", "ABSENT", 1]]}}))[2])
    nofile = refusal_of(job(root, cfg, code_of(**{"assert": {"content": [["hw/nope.py", "MARK", 0]]}}))[2])
    old = refusal_of(job(root, cfg, code_of(commit=fx["c1"], **{"assert": {"content": [["hw/x.py", "NEW_TAG", 1]]}}))[2])
    check("code: each string is found exactly the stated number of times (2, 1 and 0 pass); one found twice for one, one that is not there, a file that is not there (even for 0) and "
          "a string only the NEWER commit has, asked of the older one, are `content-missing`, each saying what was found",
          fine[1].get("outcome") == "done" and many.startswith("content-missing:") and "2 time" in many and none.startswith("content-missing:") and "0 time" in none
          and nofile.startswith("content-missing:") and "not a file" in nofile and old.startswith("content-missing:") and "NEW_TAG" in old, f"{many!r} {none!r} {nofile!r} {old!r}")
    root, cfg = mkroot2("c-anc")
    fine = job(root, cfg, code_of(**{"assert": {"ancestors": [fx["c1"]]}}))
    notanc = refusal_of(job(root, cfg, code_of(**{"assert": {"ancestors": [fx["c3"]]}}))[2])
    absent = refusal_of(job(root, cfg, code_of(**{"assert": {"ancestors": ["e" * 40]}}))[2])
    check("code: a named ancestor is checked: c1 is one of c2; c3 (a descendant that IS in the clone) is `ancestor-missing` as not an ancestor, and a commit the clone does not hold is too",
          fine[1].get("outcome") == "done" and notanc.startswith("ancestor-missing:") and "not an ancestor" in notanc and absent.startswith("ancestor-missing:") and "not in the clone" in absent,
          f"{notanc!r} {absent!r}")
    spec_bad = [verdict(lambda o=o: P.validate(code_of(**{"assert": o}), None, ST.StepRegistry())) or "" for o in
                ({"rtl_tree": "abc"}, {"content": [["../x", "a", 1]]}, {"content": [["/etc/passwd", "a", 1]]}, {"content": [["a", "", 1]]}, {"ancestors": ["abc"]}, {"colour": 1})]
    check("code: the spec's assertions are validated whole: a short rtl tree, a path that leaves the clone (`..`, absolute), an empty string, a short ancestor and an unknown field are refused by name",
          [x.split(":")[0] for x in spec_bad] == ["spec-form", "spec-form", "spec-form", "spec-form", "commit-not-full", "spec-form"], str(spec_bad))
    before = {d: sorted(os.listdir(os.path.join(root, d))) for d in ("queue", "running", "cards", "ids", "extracts")}
    job(root, cfg, code_of(commit=fx["c1"]))
    after = {d: sorted(os.listdir(os.path.join(root, d))) for d in ("queue", "running", "cards", "extracts")}
    check("code: a clone is made in a temporary directory and renamed, none is left behind by any scenario above, and the stage leaves the root's queue/, running/, cards/ and extracts/ as they were",
          not [n for r in ROOTS if os.path.isdir(os.path.join(r, "clones")) for n in os.listdir(os.path.join(r, "clones")) if n.startswith(".tmp-")]
          and all(after[d] == before[d] for d in after), str(after))
    bc = {"bundle_dir": "x", "remote": None}
    check("code: config.json's `code` section is validated: a path or URL, or null; an unknown key and a number are `config-form`",
          verdict(lambda: C.validate_config({**GOOD, "code": bc})) is None and (verdict(lambda: C.validate_config({**GOOD, "code": {"mirror": "x"}})) or "").startswith("config-form:")
          and (verdict(lambda: C.validate_config({**GOOD, "code": {"remote": 5}})) or "").startswith("config-form:"))


# ---------------------------------------------------------------------------------------- build

# The fake host tree every clone of the fixture carries: a Makefile that makes shell-script "tools" (ignored products, as the real
# ones are), a `vectors` target, and the two scripts a dry-test and a smoke step run. The environment steers them:
# FAKE_FAIL (make fails), FAKE_SKIP (a tool is not made), TREE_ID and BIN_ID (the two build ids), FAKE_VEC_BAD / FAKE_VEC_FAIL,
# FAKE_DRY (the suite's output), FAKE_QUICK (the driver's).
FAKE_MAKEFILE = (
    "SHA := $(shell git rev-parse HEAD)\nTREE_ID ?= commit=$(SHA) tracked=clean untracked=none\nBIN_ID ?= $(TREE_ID)\n"
    "TOOLS := device-test api-test remote-test divsqrt-soak clause5-soak cft-segrun cft-audit cft-resident cft-selftest\n.PHONY: all print-build-id\n"
    "all: $(TOOLS) libcft.so\n\t@test -z \"$$FAKE_FAIL\" || { echo fake make failure; exit 2; }\n"
    "$(TOOLS):\n\t@test -n \"$$FAKE_FAIL\" && exit 0; case \" $$FAKE_SKIP \" in *\" $@ \"*) exit 0;; esac; sed 's/@BIN_ID@/$(BIN_ID)/' fake/$@.sh > $@ && chmod +x $@\n"
    "libcft.so:\n\t@test -n \"$$FAKE_FAIL\" && exit 0; echo lib > $@\nprint-build-id:\n\t@echo \"$(TREE_ID)\"\n")
FAKE_TREE = {
    "host/Makefile": FAKE_MAKEFILE,
    "host/fake/api-test.sh": "#!/bin/sh\necho 'api-test: all contract checks passed'\n",
    "host/fake/cft-segrun.sh": "#!/bin/sh\n[ \"$1\" = --build-id ] && echo '@BIN_ID@'\nexit 0\n",
    **{f"host/fake/{n}.sh": "#!/bin/sh\nexit 0\n" for n in ("device-test", "remote-test", "divsqrt-soak", "clause5-soak", "cft-audit", "cft-resident", "cft-selftest")},
    "Makefile": ".PHONY: vectors\nvectors:\n\t@mkdir -p vectors/out && if [ -n \"$$FAKE_VEC_FAIL\" ]; then exit 2; elif [ -n \"$$FAKE_VEC_BAD\" ]; then echo bad > vectors/out/a.txt; else echo ok > vectors/out/a.txt; fi\n",
    "vectors/SHA256SUMS": hashlib.sha256(b"ok\n").hexdigest() + "  out/a.txt\n",
    "hw/card-segrun.sh": "#!/bin/sh\nd=$(mktemp -d \"${TMPDIR:-/tmp}/card-segrun.XXXXXX\")\necho kept > \"$d/gate1.log\"\n"
        "echo '  FAIL  the gate on this card exited 1'; echo '== card-segrun: 6 checks, 1 failed'; echo \"   logs kept in $d\"; exit 1\n",
    "hw/test-card-stress.sh": "#!/bin/sh\ncase \"$FAKE_DRY\" in\n"
        "  flakes) echo '  FAIL  telemetry hang: x  detail'; echo '  FAIL  stopfile: y  detail'; echo 'card-stress test: 600 checks, 2 failed, 0 skipped, 5 s'; exit 1;;\n"
        "  noted) echo '  FAIL  report test: a  d'; echo '  FAIL  progress test: b  d'; echo '  FAIL  telemetry hang: x  d'; echo 'card-stress test: 600 checks, 3 failed, 0 skipped, 5 s'; exit 1;;\n"
        "  real) echo '  FAIL  something real  detail'; echo 'card-stress test: 600 checks, 1 failed, 0 skipped, 5 s'; exit 1;;\n"
        "  lie) echo 'card-stress test: 600 checks, 0 failed, 0 skipped, 5 s'; exit 1;;\n"
        "  *) echo 'card-stress test: 600 checks, 0 failed, 0 skipped, 5 s'; exit 0;;\nesac\n",
    "hw/card-stress.sh": "#!/bin/sh\necho \"args: $*\"\ncase \"$FAKE_QUICK\" in\n"
        "  fail) echo \"quick: not every leg passed: {'fail': 1}\"; echo 'card-stress ends: quick_done (exit 1); the card is left idle (no process of this run is alive)'; exit 1;;\n"
        "  dryrun) echo '[2026-10-22 07:00:00] card-stress: out /x; QUICK DRY RUN until no deadline'; echo 'card-stress ends: quick_done (exit 0); the card is left idle (no process of this run is alive)'; exit 0;;\n"
        "  stopped) echo 'card-stress ends: guard_refused (exit 2); the card is left idle (no process of this run is alive)'; exit 2;;\n"
        "  noend) echo 'something else'; exit 0;;\n"
        "  *) echo 'card-stress ends: quick_done (exit 0); the card is left idle (no process of this run is alive)'; exit 0;;\nesac\n",
}


class env:
    """Set environment variables for a block, and put them back."""

    def __init__(self, **kw):
        self.kw, self.old = kw, {}

    def __enter__(self):
        for k, v in self.kw.items():
            self.old[k] = os.environ.get(k)
            os.environ[k] = v
        return self

    def __exit__(self, *a):
        for k, v in self.old.items():
            os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)


def fake_ldd(kind):
    """A directory with an `ldd` that says what XRT-linked tools say (ok), that nothing is (no), or that only cft-selftest is not (opt)."""
    d = os.path.join(TMP, "fakebin-" + kind)
    if not os.path.isdir(d):
        os.makedirs(d)
        body = {"ok": "echo '\tlibxrt_coreutil.so.2 => /fake/libxrt_coreutil.so.2 (0x0)'", "no": "echo '\tnot a dynamic executable'; exit 1",
                "opt": 'case "$1" in *cft-selftest) echo "\tnot a dynamic executable"; exit 1;; *) echo "\tlibxrt_coreutil.so.2 => /fake/libxrt_coreutil.so.2 (0x0)";; esac'}[kind]
        open(os.path.join(d, "ldd"), "w", newline="").write("#!/bin/sh\n" + body + "\n")
        os.chmod(os.path.join(d, "ldd"), 0o755)
    return d


class no_users:
    """The guard finds nobody: for the scenarios that test something else with a job that is not dry."""

    def __enter__(self):
        self.old = GD.KIND_SCANS["xrt"]
        GD.KIND_SCANS["xrt"] = lambda exclude: ([], [])

    def __exit__(self, *a):
        GD.KIND_SCANS["xrt"] = self.old


def real(**kw):
    """A staged spec that is NOT dry: the real tools of the fixture's fake tree."""
    return staged(dry_run=False, **kw)


def group_build():
    fx = fixture()
    src = open(os.path.join(HERE, "card_stress.py"), encoding="utf-8").read()
    import ast
    drv = {k: ast.literal_eval(re.search(k + r" = (\[.*?\]|\{.*?\})", src, re.S).group(1)) for k in ("targets", "exes", "optional")}
    check("build: the targets, the tools and the optional tools are the driver's own: hw/card_stress.py build_tools's lists, read from its source",
          drv["targets"] == BD.TARGETS and drv["exes"] == BD.TOOLS and drv["optional"] == BD.OPTIONAL, f"{drv} {BD.TARGETS} {BD.TOOLS}")
    if os.name != "posix" or not all(shutil.which(x) for x in ("make", "sh", "git", "sed")):
        for n in ("a clean build is made, XRT=1 and every tool checked", "make failing, and a tool not made", "a tool that does not link XRT", "a build id that is not the tree's",
                  "the dry tests in a built clone", "the vectors, the dry tests and the smoke as steps"):
            skip(f"build: {n}", "needs POSIX with make, sh, sed and git")
        return
    ok_path = fake_ldd("ok") + os.pathsep + os.environ["PATH"]
    with no_users(), env(PATH=ok_path):
        root, cfg = mkroot2("b-ok")
        j, end, rs = job(root, cfg, real())
        bd = next((r for r in rs if r["type"] == "build"), {})
        lg = legs_of(rs)
        check("build: a clean build is made on the clone with XRT=1 and the driver's targets, ldd names xrt_coreutil for each of the ten tools, the build id is the tree's and names the commit, "
              "and the step then runs the real (fake-tree) tool",
              end.get("outcome") == "done" and bd.get("ok") is True and any("XRT=1" in s["detail"] and "clause5-soak" in s["detail"] for s in bd.get("steps", []))
              and sum(1 for s in bd.get("steps", []) if s["name"].startswith("xrt ")) == 10 and bd.get("build_id") == f"commit={fx['c2']} tracked=clean untracked=none"
              and len(lg) == 1 and lg[0]["status"] == "pass" and lg[0]["standin"] is False and lg[0]["dry"] is False, f"{end.get('outcome')} {refusal_of(rs)!r} {bd}"[:400])
        with env(CC="false"):
            r2, c2 = mkroot2("b-probe")
            bp = next((r for r in job(r2, c2, real())[2] if r["type"] == "build"), {})
        check("build: the roundeven probe is the driver's: a compiler that cannot build it is recorded `absent`, and the build goes on",
              bp.get("ok") is True and any(s["name"] == "roundeven probe" and s["detail"].startswith("absent") for s in bp.get("steps", [])), str(bp)[:300])
        with env(FAKE_FAIL="1"):
            rf, cf = mkroot2("b-fail")
            jf = job(rf, cf, real())
        with env(FAKE_SKIP="cft-audit"):
            r2, c2 = mkroot2("b-skip")
            js = job(r2, c2, real())
        check("build: a make that fails is refused `build-failed` saying its exit status, with the build record not ok and the make output kept; the job ends refused, nothing run",
              refusal_of(jf[2]).startswith("build-failed:") and "make exited 2" in refusal_of(jf[2]) and jf[1].get("outcome") == "refused" and not legs_of(jf[2])
              and any(r["type"] == "build" and r["ok"] is False for r in jf[2]) and os.path.isfile(os.path.join(rf, "jobs", jf[0], "build.log")), refusal_of(jf[2]))
        check("build: a make that succeeds without making a tool is `build-failed` naming the tool",
              refusal_of(js[2]).startswith("build-failed:") and "cft-audit was not built" in refusal_of(js[2]), refusal_of(js[2]))
    with no_users(), env(PATH=fake_ldd("no") + os.pathsep + os.environ["PATH"]):
        r2, c2 = mkroot2("b-nolink")
        jn = job(r2, c2, real())
    check("build: a tool whose ldd does not name xrt_coreutil is refused `xrt-not-linked`, naming it and why (built without XRT=1 it answers every xclbin 'no such device')",
          refusal_of(jn[2]).startswith("xrt-not-linked:") and "device-test" in refusal_of(jn[2]) and "no such device" in refusal_of(jn[2]) and jn[1].get("outcome") == "refused", refusal_of(jn[2]))
    with no_users(), env(PATH=fake_ldd("opt") + os.pathsep + os.environ["PATH"]):
        r2, c2 = mkroot2("b-opt")
        jo = job(r2, c2, real(image="quad", steps=[{"type": "selftest"}, {"type": "api-test"}]))
    bo = next((r for r in jo[2] if r["type"] == "build"), {})
    lo = legs_of(jo[2])
    check("build: cft-selftest not linked is not the job's failure: as the driver has it, the `selftest` step is SKIPPED by name with the reason, the build record says it, and the others run",
          jo[1].get("outcome") == "done" and bo.get("disabled", {}).get("selftest", "").startswith("cft-selftest does not link XRT") and [x["status"] for x in lo] == ["skipped", "pass"]
          and "does not link XRT" in (lo[0]["reason"] or ""), f"{jo[1].get('outcome')} {refusal_of(jo[2])!r} {bo.get('disabled')} {[x['status'] for x in lo]}")
    with no_users(), env(PATH=ok_path, FAKE_SKIP="cft-resident"):
        r2, c2 = mkroot2("b-notbuilt")
        jr = job(r2, c2, real(image="quad", steps=[{"type": "resident"}, {"type": "api-test"}]))
    lr = legs_of(jr[2])
    check("build: an optional tool that make did not make (cft-resident) skips ITS step by name with the reason, as the driver has it, and the job's other steps run",
          jr[1].get("outcome") == "done" and [x["status"] for x in lr] == ["skipped", "pass"] and "cft-resident was not built" in ((lr or [{}])[0].get("reason") or ""),
          f"{jr[1].get('outcome')} {refusal_of(jr[2])!r} {[x['status'] for x in lr]}")
    with no_users(), env(PATH=ok_path):
        r2, c2 = mkroot2("b-id1")
        with env(BIN_ID="commit=" + "d" * 40 + " tracked=clean untracked=none"):
            ja = job(r2, c2, real())
        r3, c3 = mkroot2("b-id2")
        with env(TREE_ID="unknown", BIN_ID="unknown"):
            jb = job(r3, c3, real())
    check("build: the tools' build id is held to the tree's: cft-segrun carrying another id is refused `build-id-mismatch`, naming both",
          refusal_of(ja[2]).startswith("build-id-mismatch:") and "d" * 40 in refusal_of(ja[2]) and fx["c2"] in refusal_of(ja[2]), refusal_of(ja[2]))
    check("build: and the tree's id must name the job's commit on a clean tree: two ids that agree on `unknown` are refused `build-id-mismatch` too",
          refusal_of(jb[2]).startswith("build-id-mismatch:") and "does not name the job's commit" in refusal_of(jb[2]), refusal_of(jb[2]))
    with no_users(), env(PATH=ok_path):
        r2, c2 = mkroot2("b-built")
        job(r2, c2, real())                                              # builds the clone
        jd = job(r2, c2, real(steps=[{"type": "drytests"}]))
        r3, c3 = mkroot2("b-fresh")
        jv = job(r3, c3, real(steps=[{"type": "vectors"}, {"type": "drytests", "known_flakes": ["telemetry hang: "]}, {"type": "api-test"}]))
    check("build: the dry tests are refused `clone-built` in a clone that has been built (ignored products under host/), before anything runs",
          refusal_of(jd[2]).startswith("clone-built:") and "host/" in refusal_of(jd[2]) and jd[1].get("outcome") == "refused" and not legs_of(jd[2]), refusal_of(jd[2]))
    lv = legs_of(jv[2])
    check("build: and in a clone nothing has built they run after `make vectors` (its ignored vectors/out is not a build product), and the build comes after them, once, before api-test",
          jv[1].get("outcome") == "done" and [x["leg"] for x in lv] == ["vectors", "drytests", "api-test"] and [x["status"] for x in lv] == ["pass"] * 3
          and [r["type"] for r in jv[2] if r["type"] in ("leg", "build")] == ["leg", "leg", "build", "leg"], f"{jv[1].get('outcome')} {refusal_of(jv[2])!r} {[(x['leg'], x['status']) for x in lv]}")


# ---------------------------------------------------------------------------------------- images

def group_images():
    d = os.path.join(TMP, "im-ok")
    entry = write_image(d)
    card = {"id": "u50-0", "kind": "xrt", "platform": PLAT}
    got = safely(IM.check_image, entry, card)
    check("images: an image whose file, registry, SHA256SUMS and manifest agree passes, with its tile count (the manifest's clock_cus) and its platform",
          isinstance(got, dict) and got["tiles"] == 4 and got["platform"] == PLAT and got["sha256"] == entry["sha256"] and got["witnesses"] == ["file", "registry", "SHA256SUMS", "manifest"], str(got))
    with env(SCHED_TEST_IMGDIR=d):
        viaenv = safely(IM.check_image, dict(entry, path="$SCHED_TEST_IMGDIR/cft_hw_quad.xclbin"), card)
    check("images: a registry path may carry an environment variable ($HOME, as the driver's defaults do), which is expanded when the job runs",
          isinstance(viaenv, dict) and os.path.normpath(viaenv["path"]) == os.path.normpath(entry["path"]) and viaenv["sha256"] == entry["sha256"], str(viaenv))
    one = lambda name, e=None, c=None: verdict(lambda: IM.check_image(e or entry, c or card)) or ""
    other = "1" * 64
    check("images: a registry whose SHA-256 is not the file's is refused `image-digest`, naming both",
          one("reg", dict(entry, sha256=other)).startswith("image-digest:") and "registry says 1111111111111111" in one("reg", dict(entry, sha256=other)), one("reg", dict(entry, sha256=other)))
    d2 = os.path.join(TMP, "im-sums")
    e2 = write_image(d2)
    open(os.path.join(d2, "SHA256SUMS"), "w").write(other + "  cft_hw_quad.xclbin\n")
    a = one("sums", e2)
    open(os.path.join(d2, "SHA256SUMS"), "w").write(other + "  some_other.xclbin\n")
    b = one("sums", e2)
    os.remove(os.path.join(d2, "SHA256SUMS"))
    c = one("sums", e2)
    check("images: the directory's SHA256SUMS is compared: a line that differs, no line for the file, and no SHA256SUMS at all are each `image-digest`",
          a.startswith("image-digest:") and "SHA256SUMS says 1111111111111111" in a and b.startswith("image-digest:") and "no line for cft_hw_quad.xclbin" in b
          and c.startswith("image-digest:") and "no SHA256SUMS" in c, f"{a!r} {b!r} {c!r}")
    d3 = os.path.join(TMP, "im-man")
    e3 = write_image(d3)
    mp = os.path.join(d3, "cft_hw_quad.manifest.txt")
    text = open(mp).read().replace(e3["sha256"], other)
    open(mp, "w", newline="").write(text)
    m = one("man", e3)
    check("images: the manifest beside the image is a witness too: one that describes another file (its `sha256:`) is `image-digest`",
          m.startswith("image-digest:") and "manifest says sha256 1111111111111111" in m, m)
    e4 = write_image(os.path.join(TMP, "im-gone"))
    os.remove(e4["path"])
    gone = one("gone", e4)
    check("images: a file that cannot be read is `image-digest` as well (its digest cannot be held to anything)", gone.startswith("image-digest:") and "cannot be read" in gone, gone)
    t1, t2 = one("tiles", dict(entry, tiles=1)), one("tiles", {k: v for k, v in entry.items() if k != "tiles"})
    d5 = os.path.join(TMP, "im-nomanifest")
    t3 = one("tiles", write_image(d5, manifest=False))
    check("images: the tile count is the manifest's number of compute units: a registry that says 1 for four is refused `image-tiles`, so is a registry that gives none and an image with no manifest",
          t1.startswith("image-tiles:") and "lists 4 compute unit(s)" in t1 and t2.startswith("image-tiles:") and "gives no tile count" in t2 and t3.startswith("image-tiles:") and "no cft_hw_quad.manifest.txt" in t3, f"{t1!r} {t2!r} {t3!r}")
    p1, p2, p3 = one("plat", dict(entry, platform="xilinx_u50_other"), None), one("plat", None, dict(card, platform="xilinx_u50_other")), one("plat", None, {"id": "u50-0", "kind": "xrt"})
    check("images: the platform must be the manifest's, the registry's and the card's alike: a registry or a card that differs, and a card that gives none, are `image-platform`",
          all(x.startswith("image-platform:") for x in (p1, p2, p3)) and "xilinx_u50_other" in p1 and "xilinx_u50_other" in p2 and "None" in p3, f"{p1!r} {p2!r} {p3!r}")
    root, cfg = mkroot2("i-run", images=[dict(entry, tiles=1)])
    jr = job(root, cfg, staged(image="quad", steps=[{"type": "dt-i"}]))
    root, cfg = mkroot2("i-run2", images=[dict(entry, sha256=other)])
    jr2 = job(root, cfg, staged(image="quad", steps=[{"type": "dt-i"}]))
    root, cfg = mkroot2("i-run3", cards=[{"id": "u50-0", "kind": "xrt", "platform": "xilinx_u50_other"}])
    jr3 = job(root, cfg, staged(image="quad", steps=[{"type": "dt-i"}]))
    check("images: through a job the same refusals end it refused, before the code is cloned and with no leg (digest, tiles, platform)",
          [refusal_of(x[2]).split(":")[0] for x in (jr, jr2, jr3)] == ["image-tiles", "image-digest", "image-platform"] and all(x[1].get("outcome") == "refused" and not legs_of(x[2]) for x in (jr, jr2, jr3))
          and not os.path.isdir(os.path.join(root, "clones", FIX["c2"])), [refusal_of(x[2])[:60] for x in (jr, jr2, jr3)])
    mdir = os.environ.get("SCHED_TEST_MANIFESTS")
    if mdir and all(os.path.isfile(os.path.join(mdir, f"cft_hw_{n}.manifest.txt")) for n in ("quad", "single", "deep")):
        facts = {n: IM.read_manifest(os.path.join(mdir, f"cft_hw_{n}.manifest.txt")) for n in ("quad", "single", "deep")}
        check("images: the lead's three real manifests (SCHED_TEST_MANIFESTS) read as the driver's own table has them: tiles, SHA-256 and the platform",
              all(IM.tiles_of(facts[n]) == DR.CS.IMAGES[n][1] and facts[n]["sha256"] == DR.CS.IMAGES[n][3] and facts[n]["platform"] == PLAT for n in facts), str({n: (IM.tiles_of(f), f.get("platform")) for n, f in facts.items()}))
    else:
        skip("images: the lead's three real manifests read as the driver's table has them", "SCHED_TEST_MANIFESTS names no directory of cft_hw_{quad,single,deep}.manifest.txt")
    cm = {"images": [{"name": "q", "path": "p", "sha256": "0" * 64, "tiles": 4, "platform": PLAT}], "cards": [{"id": "a", "kind": "xrt", "platform": PLAT}]}
    bad = [("an image with tiles 0", {"images": [dict(cm["images"][0], tiles=0)]}, "images[0].tiles"), ("an image with a platform that has a space", {"images": [dict(cm["images"][0], platform="a b")]}, "images[0].platform"),
           ("a card with a platform that has a space", {"cards": [{"id": "a", "kind": "xrt", "platform": "a b"}]}, "cards[0].platform"),
           ("a runner section with an unknown key", {"runner": {"speed": 1}}, "runner.speed"), ("a runner nice of 20", {"runner": {"nice": 20}}, "runner.nice"),
           ("a runner guard_poll_s of 0", {"runner": {"guard_poll_s": 0}}, "runner.guard_poll_s")]
    got = [verdict(lambda o=o: C.validate_config({**GOOD, **o})) or "" for _, o, _ in bad]
    check("images: the registry's tiles and platform, a card's platform and the runner section are validated, each refusal naming its key",
          all(g.startswith("config-form:") and f in g for g, (_, _, f) in zip(got, bad)) and verdict(lambda: C.validate_config({**GOOD, **cm, "runner": {"guard_wait_max_s": 0, "nice": 0}})) is None, str(got))
    check("images: every kind of card the configuration admits has its image check, its guard and its build",
          set(C.CARD_KINDS) == set(IM.IMAGE_CHECKS) == set(GD.KIND_SCANS) == set(BD.KIND_BUILDS), f"{set(C.CARD_KINDS)} {set(IM.IMAGE_CHECKS)} {set(GD.KIND_SCANS)} {set(BD.KIND_BUILDS)}")


# ---------------------------------------------------------------------------------------- guard

IMG = "/images/cft_hw_quad.xclbin"


class table_of:
    """The driver's process listing replaced by a table, as docs/studies/sched-a/guard_probe.py does: no real process is read."""

    def __init__(self, table):
        self.table = table

    def __enter__(self):
        self.old = DR.CS.list_processes
        DR.CS.list_processes = lambda: [dict(p) for p in self.table]

    def __exit__(self, *a):
        DR.CS.list_processes = self.old


class MemLog:
    """Where a guard writes its records, in memory."""

    def __init__(self):
        self.recs = []

    def append(self, type_, **kw):
        self.recs.append(dict(kw, type=type_))

    def of(self, type_):
        return [r for r in self.recs if r["type"] == type_]


def group_guard():
    me = os.getpid()
    table = [
        {"pid": 1, "ppid": 0, "args": ["init"]},
        {"pid": 200, "ppid": 1, "args": ["bash", "-c", "pgrep -fc 'card_stress.py|divsqrt-soak'; device-test " + IMG]},    # the shell that launched the service
        {"pid": me, "ppid": 200, "args": ["python3", "cft_sched.py", "serve", "device-test", IMG]},                       # the service: its own command line looks like a card user
        {"pid": 300, "ppid": me, "args": ["bash", "hw/run-device-test.sh", IMG, "-i"]},                                    # a step it started
        {"pid": 400, "ppid": 1, "args": ["bash", "verify/run.sh", "--budget", "gate"]},                                    # a gate: it uses no card
    ]
    plain = [dict(p, args=["python3", "cft_sched.py", "serve"]) if p["pid"] in (200, me) else p for p in table]               # the same, its two command lines innocent
    lg = MemLog()
    with table_of(table):
        users, beside = GD.scan("xrt")
        got = safely(GD.hold_until_clear, lg, "xrt", 0, 0.01)
    check("guard: the process that asks, what it started and the shell that launched it are not foreign users, though their command lines name a card tool and an image; a gate "
          "(verify/run.sh) is allowed and recorded `beside`, once",
          users == [] and [b["pid"] for b in beside] == [400] and got is None and len(lg.of("beside")) == 1 and not lg.of("guard_refused"), f"{users} {got} {lg.recs}")
    lg = MemLog()
    with table_of(plain + [{"pid": 600, "ppid": 1, "args": ["cft-serve", "--artifact", IMG, "--port", "7754"]}]):
        err = verdict(lambda: GD.hold_until_clear(lg, "xrt", 0, 0.01))
    with table_of(plain + [{"pid": 601, "ppid": 1, "args": ["cft-serve", "--port", "7754"]}, {"pid": 602, "ppid": 1, "args": ["xbutil", "examine", "-d", "0000:02:00.1"]}]):
        soft = safely(GD.hold_until_clear, MemLog(), "xrt", 0, 0.01)
    check("guard: an idle `cft-serve --artifact IMAGE` is a card user (it holds the card whether or not a client is connected) and a job at its start is refused `card-busy-foreign` "
          "naming it, with a `guard_refused` record; the same server on the software backend, and `xbutil examine`, are not users",
          (err or "").startswith("card-busy-foreign:") and "pid 600" in err and "an xclbin argument" in err and lg.of("guard_refused")[0]["users"][0]["pid"] == 600 and soft is None, f"{err!r} {soft}")
    seq = iter([[{"pid": 9, "why": "an xclbin argument (x.xclbin)", "args": "device-test x.xclbin"}]] * 2 + [[]])
    old, sleeps, lg = GD.KIND_SCANS["xrt"], [], MemLog()
    GD.KIND_SCANS["xrt"] = lambda exclude: (next(seq), [])
    try:
        got = safely(GD.hold_until_clear, lg, "xrt", 100, 5, None, sleeps.append)
    finally:
        GD.KIND_SCANS["xrt"] = old
    check("guard: between steps a foreign user is waited for, polling, and the wait is recorded: `guard_wait` once, then `guard_clear` when the card is free; the job goes on",
          got is None and sleeps == [5, 5] and len(lg.of("guard_wait")) == 1 and len(lg.of("guard_clear")) == 1 and not lg.of("guard_refused"), f"{got} {sleeps} {lg.recs}")
    ticks, lg = iter(range(0, 100)), MemLog()
    GD.KIND_SCANS["xrt"] = lambda exclude: ([{"pid": 9, "why": "x", "args": "x"}], [])
    try:
        err = verdict(lambda: GD.hold_until_clear(lg, "xrt", 3, 1, None, lambda s: None, lambda: next(ticks)))
        stopped = safely(GD.hold_until_clear, MemLog(), "xrt", 100, 1, lambda: True, lambda s: None)
    finally:
        GD.KIND_SCANS["xrt"] = old
    check("guard: a user that does not go is refused `card-busy-foreign` after the limit, saying how long it waited; a stop asked while waiting ends the wait as a stop, not a refusal",
          (err or "").startswith("card-busy-foreign:") and "still in use after 3 s" in err and len(lg.of("guard_wait")) == 1 and len(lg.of("guard_refused")) == 1 and "Stopped" in str(stopped),
          f"{err!r} {stopped}")
    if os.name != "posix" or not os.path.isdir("/proc/self"):
        skip("guard: real processes: an idle cft-serve is found, the asker and a bystander are not", "needs /proc (POSIX)")
        return
    tok = f"{me}-{int(time.time())}"
    sleeper = "import time; time.sleep(120)"
    serve = subprocess.Popen([sys.executable, "-c", sleeper, "cft-serve", "--artifact", f"/x/SERVE-{tok}.xclbin", "--port", "7754"])
    by = subprocess.Popen([sys.executable, "-c", sleeper, f"bystander-{tok}"])
    try:
        time.sleep(0.5)
        code = f"import sys, json, os; sys.path.insert(0, {SCHED!r}); import sched_guard as G; u, b = G.scan('xrt'); print(json.dumps({{'me': os.getpid(), 'users': [x['pid'] for x in u]}}))"
        p = subprocess.run([sys.executable, "-B", "-I", "-c", code, "device-test", f"/x/ASK-{tok}.xclbin"], capture_output=True, text=True, timeout=120)
        res = json.loads(p.stdout.strip().splitlines()[-1]) if p.returncode == 0 else {"me": 0, "users": []}
    finally:
        for x in (serve, by):
            x.kill()
            x.wait()
    check("guard: with real processes (/proc), an idle `cft-serve --artifact` started by someone else is found, and the asker (whose own command line names device-test and an image) "
          "and a bystander are not", serve.pid in res["users"] and res["me"] not in res["users"] and by.pid not in res["users"], f"{res} serve {serve.pid} bystander {by.pid} {p.stderr[-200:]}")


# ---------------------------------------------------------------------------------------- steps

def pick_items():
    """(a tile item that is exhaustive, a host item that is exhaustive, a tile item that is random), the first of each in the driver's catalog."""
    cat = ST.catalog()
    return tuple(next(n for n, i in cat.items() if i.reach == r and i.kind == k) for r, k in ((DR.L.TILE, "exhaustive"), (DR.L.HOST, "exhaustive"), (DR.L.TILE, "random")))


def driver_for(*args):
    """The driver's own Driver object for these options (never run: its leg_cmd, wrap and standin are asked)."""
    return DR.CS.Driver(DR.CS.parse_args(list(args) + ["--until", "2099-01-01 00:00"]))


def group_steps():
    """All six parts, or the ones `--only steps:PART` names (registry, parsers, run_step, jobs, real, refusals): a plant runs the part written for it."""
    parts = {"registry": steps_registry, "parsers": steps_parsers, "run_step": steps_run_step, "jobs": steps_jobs, "real": steps_real_tools, "refusals": steps_refusals}
    want = {o.split(":", 1)[1] for o in (ONLY or ()) if o.startswith("steps:")} if ONLY and "steps" not in ONLY else set(parts)
    for name, fn in parts.items():
        if name in want:
            fn()


def steps_registry():
    py = sys.executable
    check("steps: the registry holds every leg of the driver's battery, each with its parser or the rc_only label, and its fields' type tags are known",
          set(DR.CS.BATTERY) <= set(ST.ENTRIES) and all(e.parse is not None or e.rc_only for e in ST.ENTRIES.values())
          and all(t.rstrip("!") in P.TYPES for e in ST.ENTRIES.values() for t in e.fields.values()) and ST.ENTRIES["vectors"].rc_only and not any(e.rc_only for n, e in ST.ENTRIES.items() if n != "vectors"),
          str(sorted(set(DR.CS.BATTERY) - set(ST.ENTRIES))))
    for dry in (False, True):
        for quick in (False, True):
            d = os.path.join(TMP, f"drv-{int(dry)}{int(quick)}")
            os.makedirs(d, exist_ok=True)
            drv = driver_for("--root", d, "--out", os.path.join(d, "out"), "--python", py, "--rev8-images", os.path.join(d, "rev8"), "--seq-trials", "7",
                             *(["--dry-run"] if dry else []), *(["--quick"] if quick else []))
            bad = []
            for name, (path, tiles, target, sha) in DR.CS.IMAGES.items():
                img = DR.CS.Image(name, os.path.join(d, name + ".xclbin"), tiles, target, sha)
                image = {"name": name, "path": img.path, "sha256": sha, "tiles": tiles}
                ctx = SG.Ctx(d, image, {name: image}, py, os.path.join(d, "rev8"), dry)
                for leg in DR.CS.BATTERY:
                    want = drv.leg_cmd(leg, img, 1)
                    if not isinstance(want, DR.CS.Cmd):
                        continue                                            # the driver skips it here (no revision-8 entry for the single)
                    st = {"type": leg}
                    if leg == "seq-check":
                        st["trials"] = 7
                    if leg == "acceptance" and quick:
                        st["only"] = DR.CS.QUICK_ACCEPT_ONLY.split(",")
                    if leg == "acceptance-rev8":
                        st.update(only=want.argv[want.argv.index("--only") + 1].split(","), target=target)
                    e = ST.ENTRIES[leg]
                    real_argv = e.argv(ctx, st)
                    got = DR.standin(e.standin_leg, real_argv) if dry else real_argv
                    if got != want.argv or ST.timeout_of(e, ctx, st) != want.timeout:
                        bad.append(f"{leg}/{name}")
            check(f"steps: the registry's command for each of the driver's legs, on each image, is Driver.leg_cmd's own argv and timeout (dry {dry}, quick {quick})", not bad, str(bad[:6]))
    drv = driver_for("--root", TMP, "--out", os.path.join(TMP, "w"), "--dry-run")
    check("steps: the stand-in's wrapping and run_step's (timeout --kill-after, then nice) are Driver.standin's and Driver.wrap's own for the same options",
          DR.standin("dt-i", ["a", "b"]) == drv.standin("dt-i", ["a", "b"]) and PR.wrap(["a", "b"], 100.4, 60, 10) == drv.wrap(["a", "b"], 100.4) and PR.wrap(["a"], 0.2, 5, 0) == driver_for(
              "--root", TMP, "--out", os.path.join(TMP, "w"), "--nice", "0", "--kill-after", "5").wrap(["a"], 0.2))
    item_tile, item_host, item_rnd = pick_items()
    cases = [("a soak step for an item the catalog does not hold", {"type": "soak", "item": "nope", "lo": 0, "hi": 1}, "item 'nope'"),
             ("an exhaustive soak with a count", {"type": "soak", "item": item_tile, "lo": 0, "hi": 1 << 20, "count": 5}, "exhaustive"),
             ("an exhaustive soak slice past its space", {"type": "soak", "item": item_tile, "lo": 0, "hi": 1 << 40}, "0 <= lo < hi"),
             ("a random soak with a slice", {"type": "soak", "item": item_rnd, "lo": 0, "hi": 5}, "random"),
             ("a step with no image where its type needs one", {"type": "dt-i"}, "needs the job's `image`"),
             ("acceptance-rev8 without `only`", {"type": "acceptance-rev8", "target": "u50-rev8-quad"}, "only is missing"),
             ("acceptance-rev8 for a target nobody has", {"type": "acceptance-rev8", "only": ["x"], "target": "u50-nope"}, "u50-nope"),
             ("a timeout of 0", {"type": "api-test", "timeout_s": 0}, "timeout_s"), ("a field a step type does not have", {"type": "vectors", "item": "x"}, "item")]
    cases.append(("a tile on a host item", {"type": "soak", "item": item_host, "lo": 0, "hi": 1 << 20, "tile": 2}, "host item"))
    got = [verdict(lambda st=st: P.validate(staged(steps=[st]) if st["type"] == "dt-i" else staged(image="quad", steps=[st]), None, ST.StepRegistry())) or "" for _, st, _ in cases]
    check("steps: the registry's rules between a step's fields and the spec are `spec-form` refusals naming the step: " + "; ".join(c[0] for c in cases[:4]) + "...",
          all(g.startswith("spec-form:") and f in g and "steps[0]" in g for g, (_, _, f) in zip(got, cases)), str(got))
    check("steps: a window job is not this runner's, and is refused by name when claimed (S3 builds it); an unknown step type is `step-unknown` at submit",
          verdict(lambda: P.validate(staged(steps=[{"type": "acceptance-rev9"}]), None, ST.StepRegistry())).startswith("step-unknown:"))


def parse_cases():
    ok = "card-stress test: 600 checks, 0 failed, 0 skipped, 5 s\n"
    two = "  FAIL  telemetry hang: x  detail\n  FAIL  stopfile: y  detail\ncard-stress test: 600 checks, 2 failed, 0 skipped, 5 s\n"
    return ok, two


def steps_parsers():
    ok, two = parse_cases()
    flake = ("telemetry hang: ", "stopfile: ")
    v0 = safely(ST.parse_drytests, ok, 0, flake)
    vf = safely(ST.parse_drytests, two, 1, flake)
    vn = safely(ST.parse_drytests, two, 1, ())
    vm = safely(ST.parse_drytests, "  FAIL  telemetry hang: x  d\n  FAIL  real one  d\ncard-stress test: 600 checks, 2 failed, 0 skipped, 5 s\n", 1, flake)
    check("steps: parse_drytests reads the suite's last line: 0 failed is a pass; failures all allowed BY NAME in the spec are a pass that says so (known_flakes, in counts and notes); "
          "the same failures not allowed, or one not allowed among them, are a fail",
          v0.ok and v0.counts == {"checks": 600, "failed": 0, "skipped": 0} and vf.ok and vf.counts["known_flakes"] == 2 and "known flakes" in vf.notes[0] and not vn.ok and not vm.ok
          and "something" not in str(vm.notes) and "real one" in vm.notes[0], f"{v0} {vf} {vn} {vm}")
    note3 = "  FAIL  report test: a  d\n  FAIL  progress test: b  d\n  FAIL  telemetry hang: x  d\ncard-stress test: 600 checks, 3 failed, 0 skipped, 5 s\n"
    nf = ("report test: ", "progress test: ", "testfiles control: ")
    n1, n2 = safely(ST.parse_drytests, note3, 1, flake, nf), safely(ST.parse_drytests, note3, 1, flake)
    n3 = safely(ST.parse_drytests, note3.replace("progress test: b", "something real"), 1, flake, nf)
    check("steps: parse_drytests keeps the spec's `noted_failures` APART from its `known_flakes`: a failure that begins with a noted prefix passes (the night goes on) with its own count and its own note "
          "naming the lines, beside the flakes' count and note; the same lines with no noted_failures list fail the step, and one line in neither list fails it too, naming only that line",
          n1.ok and n1.counts == {"checks": 600, "failed": 3, "skipped": 0, "known_flakes": 1, "noted_failures": 2} and "known flakes" in n1.notes[0] and "NOTED" in n1.notes[1]
          and "report test: a" in n1.notes[1] and "progress test: b" in n1.notes[1] and not n2.ok and "2 failed check(s) not allowed" in n2.notes[0] and "report test: a" in n2.notes[0]
          and not n3.ok and "something real" in n3.notes[0] and "report test" not in n3.notes[0], f"{n1} {n2} {n3}")
    bad = {"a pass with the exit status 1": safely(ST.parse_drytests, ok, 1, flake), "a failure with the exit status 0": safely(ST.parse_drytests, two, 0, flake),
           "a totals line that disagrees with the FAIL lines": safely(ST.parse_drytests, "  FAIL  a  d\ncard-stress test: 5 checks, 2 failed, 0 skipped, 1 s\n", 1, flake),
           "no totals line": safely(ST.parse_drytests, "nothing\n", 0, flake), "two totals lines": safely(ST.parse_drytests, ok + ok, 0, flake),
           "0 checks": safely(ST.parse_drytests, "card-stress test: 0 checks, 0 failed, 0 skipped, 1 s\n", 0, flake)}
    check("steps: parse_drytests refuses (VerdictError, so the leg is parse_error) a pass the exit status contradicts, a failure it contradicts, a count that disagrees with the log, "
          "a log with no totals line, two, and 0 checks: " + ", ".join(bad), all(isinstance(v, str) and v.startswith("crashed: VerdictError") for v in bad.values()), str(bad))
    end = "card-stress ends: {} (exit {}); the card is left idle (no process of this run is alive)\n"
    q0 = safely(ST.parse_driver_quick, "noise\n" + end.format("quick_done", 0), 0)
    q1 = safely(ST.parse_driver_quick, "quick: not every leg passed: {'fail': 1}\n" + end.format("quick_done", 1), 1)
    q2 = safely(ST.parse_driver_quick, end.format("guard_refused", 2), 2)
    q3 = safely(ST.parse_driver_quick, end.format("deadline", 0), 0)
    check("steps: parse_driver_quick reads the driver's end line: quick_done with exit 0 is the only pass; a failing leg, a refused guard and a deadline are fails that say why",
          q0.ok and not q1.ok and "legs not passing" in q1.notes[0] and not q2.ok and "guard_refused" in q2.notes[0] and not q3.ok and "deadline" in q3.notes[0], f"{q0} {q1} {q2} {q3}")
    bad = {"an end line and another exit status": safely(ST.parse_driver_quick, end.format("quick_done", 0), 1), "no end line": safely(ST.parse_driver_quick, "something else\n", 0),
           "two end lines": safely(ST.parse_driver_quick, end.format("quick_done", 0) * 2, 0), "no exit status": safely(ST.parse_driver_quick, end.format("quick_done", 0), None)}
    check("steps: parse_driver_quick refuses a log with no end line, two, and an exit status that is not the line's: " + ", ".join(bad),
          all(isinstance(v, str) and v.startswith("crashed: VerdictError") for v in bad.values()), str(bad))

    class Run:
        def __init__(self, rc=0, timed_out=False, error=None, killed=None):
            self.rc, self.timed_out, self.error, self.killed = rc, timed_out, error, killed

    ctx = SG.Ctx("/c", None, {}, "py", "/r", False)
    api, vec = ST.ENTRIES["api-test"], ST.ENTRIES["vectors"]
    passing = "api-test: all contract checks passed\n"
    j = lambda e, text, **kw: ST.judge(e, ctx, {"type": e.name}, Run(**kw), text)
    blank, rcpass, rcfail, contradict, garbage = j(api, "  \n", rc=0), j(vec, "", rc=0), j(vec, "make: stuff\n", rc=3), j(api, passing, rc=1), j(api, "(stand-in) a log with no verdict line\n", rc=0)
    check("steps: a log with nothing in it is `parse_error` flagged no-verdict (never a pass); a log the parser cannot read is parse_error; a pass the exit status contradicts is parse_error",
          blank[0] == "parse_error" and blank[3] is True and "no-verdict" in blank[2] and garbage[0] == "parse_error" and garbage[3] is False and contradict[0] == "parse_error" and "exit status is 1" in contradict[2], f"{blank} {garbage} {contradict}")
    check("steps: a step with no parser is judged by its exit status ALONE, and says so (rc_only in the notes): 0 passes, 3 fails",
          rcpass[0] == "pass" and rcfail[0] == "fail" and "rc_only" in rcfail[1].notes[0], f"{rcpass} {rcfail}")
    nd = j(ST.ENTRIES["dt-i"], "device /x.xclbin: no such device\n", rc=2)
    nd2 = j(api, "device /x.xclbin: no such device\n", rc=2)
    check("steps: a timeout is `timeout` and an unstartable command `error`, whatever the log says; a card step whose log says the card did not answer is `no_device`, and a step that uses no card never is",
          j(api, passing, rc=124, timed_out=True, killed="TERM")[0] == "timeout" and j(api, passing, rc=None, error="could not start")[0] == "error" and nd[0] == "no_device" and nd2[0] == "parse_error", f"{nd} {nd2}")


def watched(fn, secs):
    """fn() in a thread: (result, finished). A defect that makes a step hang must fail a check, not the whole run."""
    out = []
    th = threading.Thread(target=lambda: out.append(fn()), daemon=True)
    th.start()
    th.join(secs)
    return (out[0] if out else None), bool(out)


def steps_run_step():
    if os.name != "posix" or not all(shutil.which(x) for x in ("nice", "timeout")):
        for n in ("a step runs niced, in a process group of its own, with standard input closed", "the timeout wrapper ends a hung step, and KILLs one that ignores TERM",
                  "the loop ends a hung step by the PID of its group when the wrapper is absent, and a bystander of the same name lives"):
            skip(f"steps: {n}", "needs POSIX with nice and timeout")
        return
    d = os.path.join(TMP, "proc")
    os.makedirs(d)
    probe, hang = os.path.join(d, "probe.py"), os.path.join(d, "hang.py")
    open(probe, "w").write("import os, sys\nprint('nice', os.nice(0), 'pgid', os.getpgid(0), 'pid', os.getpid(), 'stdin', repr(sys.stdin.read()))\n")
    open(hang, "w").write("import os, signal, sys, time\nif 'deaf' in sys.argv:\n    signal.signal(signal.SIGTERM, signal.SIG_IGN)\nprint('hanging', flush=True)\ntime.sleep(10 ** 6)\n")
    n = [0]

    def go(script, *args, timeout_s=2, kill_after_s=2, nice=10, pids=None):
        n[0] += 1
        return PR.run_step([sys.executable, script, *args], d, {}, os.path.join(d, f"s{n[0]}.log"), timeout_s, kill_after_s, nice, on_start=(pids.append if pids is not None else None))

    run = go(probe, timeout_s=10)
    text = open(os.path.join(d, "s1.log")).read()
    m = re.search(r"nice (\d+) pgid (\d+) pid (\d+) stdin (.*)", text)
    want_nice = str(min(19, os.nice(0) + 10))                               # nice -n 10 adds to this process's own niceness
    check("steps: a step runs niced: nice -n 10, on top of this process's own niceness", run.rc == 0 and m and m.group(1) == want_nice and run.argv[:3] == ["nice", "-n", "10"], f"{run.rc} {text!r} {run.argv[:4]}")
    old_which = PR.shutil.which
    PR.shutil.which = lambda name, *a, **k: None if name == "timeout" else old_which(name, *a, **k)       # GNU timeout makes a process group of its own; the step's own is what is asked
    try:
        run_g = go(probe, timeout_s=10)
    finally:
        PR.shutil.which = old_which
    mg = re.search(r"pgid (\d+) pid (\d+)", open(os.path.join(d, "s2.log")).read())
    check("steps: a step runs in a process group of its own (start_new_session): its pid is the group's leader, not this process's group, with no timeout wrapper to make one",
          bool(mg) and int(mg.group(1)) == run_g.pid != os.getpgid(0), f"{mg and mg.groups()} {run_g.pid} {os.getpgid(0)}")
    r_fd, w_fd = os.pipe()                                                  # an open pipe nobody writes to, as this process's standard input
    try:
        saved = os.dup(0)
    except OSError:                                                         # a harness that closed standard input
        saved = None
    os.dup2(r_fd, 0)
    try:
        run2 = go(probe, timeout_s=5)
    finally:
        if saved is None:
            os.close(0)
        else:
            os.dup2(saved, 0)
            os.close(saved)
        os.close(r_fd)
        os.close(w_fd)
    check("steps: a step's standard input is closed: with an open pipe as this process's own, a step that reads it still gets end-of-file at once (an ssh that leaves a pipe open would hang it)",
          run2.rc == 0 and not run2.timed_out and "stdin ''" in open(os.path.join(d, "s3.log")).read(), f"{run2.rc} {run2.timed_out}")
    t0, pids = time.time(), []
    r, fin = watched(lambda: go(hang, pids=pids), 40)
    if not fin:
        PR.kill_group(type("P", (), {"pid": pids[0]})(), "KILL")
    t1 = time.time()
    r2, fin2 = watched(lambda: go(hang, "deaf", pids=pids), 40)
    if not fin2:
        PR.kill_group(type("P", (), {"pid": pids[-1]})(), "KILL")
    check("steps: the timeout is ENFORCED: a step that hangs is ended at its limit by the timeout wrapper (TERM, rc 124, timed_out) and one that ignores TERM is KILLed after kill_after (rc 137), "
          "each within seconds, not at the end of its sleep",
          fin and fin2 and r.timed_out and r.killed == "TERM" and r.rc == 124 and t1 - t0 < 15 and r2.timed_out and r2.killed == "KILL" and r2.rc in (137, -9) and time.time() - t1 < 20,
          f"{fin} {fin2} {r and (r.rc, r.killed)} {r2 and (r2.rc, r2.killed)} {t1 - t0:.1f} s")
    tok = f"bystander-{os.getpid()}"
    by = subprocess.Popen([sys.executable, hang, tok], stdout=subprocess.DEVNULL)      # a process that carries the same script name and the same words
    old = PR.shutil.which
    PR.shutil.which = lambda name, *a, **k: None if name == "timeout" else old(name, *a, **k)
    try:
        t0, pids = time.time(), []
        r, fin = watched(lambda: go(hang, tok, pids=pids), 40)
        if not fin:
            PR.kill_group(type("P", (), {"pid": pids[0]})(), "KILL")
        r2, fin2 = watched(lambda: go(hang, tok, "deaf", pids=pids), 40)
        if not fin2:
            PR.kill_group(type("P", (), {"pid": pids[-1]})(), "KILL")
    finally:
        PR.shutil.which = old
    alive = by.poll() is None
    by.kill()
    by.wait()
    check("steps: with no timeout wrapper the loop ends a hung step at its limit by the PID of the process group it started (TERM; KILL for one that ignores TERM), and a bystander process "
          "whose command line carries the same script name and words is NOT touched (a stop by pattern would have ended it)",
          fin and fin2 and r.timed_out and r.killed == "TERM" and r2.timed_out and r2.killed == "KILL" and alive and r.argv[0] != "timeout", f"{fin} {fin2} {r and (r.rc, r.killed, r.argv[:2])} {r2 and (r2.rc, r2.killed)} bystander alive {alive}")


def run_dry(name, steps, scenario=None, image="quad", cfg_over=None, **kw):
    """A dry job in a root of its own, its steps against the stand-in; scenario is the stand-in's rule list. (root, id, end, records)."""
    root, cfg = mkroot2(name, **(cfg_over or {}))
    state = os.path.join(root, "standin-state")
    sc = os.path.join(root, "scenario.json")
    json.dump(scenario or [], open(sc, "w"))
    with env(CFT_STANDIN_SCENARIO=sc, CFT_STANDIN_STATE=state):
        j, end, rs = job(root, cfg, staged(image=image, steps=steps, **kw))
    return root, j, end, rs


def steps_jobs():
    fx = fixture()
    cat = ST.catalog()
    tile_ex, host_ex, tile_rnd = pick_items()
    legs = [{"type": t} for t in ("api-test", "dt-i", "dt-q8", "dt-full", "dt-r", "dt-b", "card-segrun", "seq-check", "acceptance", "resident", "selftest")]
    steps = legs + [{"type": "acceptance-rev8", "only": ["gray_scott_hard_fp64"], "target": "u50-rev8-quad"},
                    {"type": "soak", "item": tile_ex, "lo": 0, "hi": 1 << 20, "tile": 2}, {"type": "soak", "item": host_ex, "lo": 0, "hi": 1 << 20},
                    {"type": "soak", "item": tile_rnd, "count": 1000, "seed": 5}]
    calls = []
    old = GD.KIND_SCANS["xrt"]
    GD.KIND_SCANS["xrt"] = lambda exclude: (calls.append(1), ([], []))[1]
    try:
        with env(CFT_SOAK_ARTIFACT="/leaked/other.xclbin"):
            root, j, end, rs = run_dry("s-dry", steps)
    finally:
        GD.KIND_SCANS["xrt"] = old
    lg = legs_of(rs)
    at = lambda i: lg[i] if -len(lg) <= i < len(lg) else {}               # a plant may leave the job short of legs: a check must fail, not the group
    d = os.path.join(root, "jobs", j)
    logs = {x["step"]: open(os.path.join(d, x["log"]), errors="replace").read() for x in lg if x.get("log")}
    check("steps: a dry job runs every step of the registry that has a stand-in leg (the driver's twelve and the soak slices) through the DRIVER's parsers, all pass; every leg says `dry` and "
          "`standin`, none touched a card, the end record says dry_run and card_touched false, and the job ended done",
          end.get("outcome") == "done" and len(lg) == len(steps) and [x["status"] for x in lg] == ["pass"] * len(steps) and all(x["dry"] and x["standin"] and not x["card_touched"] for x in lg)
          and end.get("dry_run") is True and end.get("card_touched") is False and end.get("steps_ran") == len(steps), f"{end.get('outcome')} {refusal_of(rs)!r} {[(x['leg'], x['status'], x['reason']) for x in lg if x['status'] != 'pass']}")
    check("steps: a dry job asks no guard: nothing touches the card, so nobody else's use of it matters to it", not calls, f"{len(calls)} guard calls")
    check("steps: a dry job builds nothing (its build record says so) and the clone it asserted is still unbuilt",
          [s["detail"][:9] for r in rs if r["type"] == "build" for s in r["steps"]] == ["dry job: "] and os.path.isdir(os.path.join(root, "clones", fx["c2"])), str([r for r in rs if r["type"] == "build"])[:200])
    check("steps: each leg is in the driver's leg schema and names its card (u50-0): image, image_sha256, leg, kind, start, end, duration, rc, status, counts, rate, sweep, log; "
          "the soak legs say which slice (item, lo, hi, tile) and which kind of job they were (a host item runs on image `cpu`)",
          all(x["card"] == "u50-0" and {"image", "image_sha256", "leg", "kind", "start_epoch", "end_epoch", "duration_s", "rc", "status", "timed_out", "killed", "counts", "rate", "sweep", "log", "log_kept", "reason", "tile", "extra"} <= set(x)
              for x in lg) and len(lg) == len(steps) and at(0).get("image_sha256") == fx["image"]["sha256"] and at(0).get("image") == "quad" and (at(-3).get("sweep") or {}).get("item") == tile_ex
          and (at(-3).get("sweep") or {}).get("hi") == 1 << 20 and at(-3).get("tile") == 2 and at(-2).get("image") == "cpu" and at(-2).get("image_sha256") is None
          and (at(-3).get("rate") or {}).get("unit") in ("cases/s", "checks/s"), str(at(-3))[:300])
    check("steps: a host item's step never sees the card: the stand-in prints the variables it was handed and a CFT_SOAK_ARTIFACT in this process's environment did not reach it, while the card "
          "item's step gets its image and its tile",
          "CFT_SOAK_ARTIFACT=<unset> CFT_XRT_TILES=<unset>" in logs.get(len(steps) - 2, "") and f"CFT_SOAK_ARTIFACT={fx['image']['path']} CFT_XRT_TILES=2" in logs.get(len(steps) - 3, ""),
          logs.get(len(steps) - 2, "")[:200])
    check("steps: every step's raw output is a file of the job's directory, named NN-STEP.log, whole, and the job's SHA256SUMS lists them (an independent sha256sum -c agrees); "
          "no scratch directory is left behind",
          verify_sums(d) == [] and all(f"{i:02d}-" in "".join(os.listdir(d)) for i in (0, 5, 11)) and "SHA256SUMS" in os.listdir(d) and not [n for n in os.listdir(d) if n.startswith(".")]
          and logs and all(l.splitlines()[:1] and l.splitlines()[0].startswith("standin: would run:") for l in logs.values()), str(sorted(os.listdir(d))[:8]))
    rc, out, err = cli(root, "status", j)
    check("steps: `status JOB` lists the legs, each marked dry: stand-in", rc == 0 and out.count("[dry: stand-in]") == len(steps) and "step 0 api-test: pass" in out, out[:300])
    r7, c7 = mkroot2("s-cli")
    spec_file = os.path.join(TMP, "s-cli-spec.json")
    json.dump(staged(steps=[{"type": "api-test"}]), open(spec_file, "w"))
    nolock = [] if S.HAVE_FLOCK else ["--no-locks"]
    rc1, out1, err1 = cli(r7, "submit", spec_file, runner=None)
    rc2, out2, err2 = cli(r7, "serve", "--drain", *nolock, runner=None)
    rc3, out3, err3 = cli(r7, "status", (out1.split() or ["j000000"])[-1], runner=None)
    rc4, out4, err4 = cli(r7, "submit", spec_file, runner="fake")
    check("steps: the command's default runner is the staged one: a dry staged spec is submitted, served (`serve --drain`) and ends done with no --runner, and `status JOB` lists its leg; "
          "with --runner fake the same spec is refused `step-unknown` (the fake runner holds four step types of its own)",
          rc1 == 0 and rc2 == 0 and "ended: done" in out2 and rc3 == 0 and "step 0 api-test: pass [dry: stand-in]" in out3 and rc4 == 2 and "step-unknown" in err4, f"{rc1} {err1[-100:]!r} {rc2} {out2!r} {err2[-100:]!r} {out3!r} {rc4} {err4[-100:]!r}")
    fail = [{"leg": "dt-full", "nth": [1], "do": "fail"}]
    r1 = run_dry("s-fail", [{"type": "api-test"}, {"type": "dt-full"}, {"type": "dt-r"}, {"type": "dt-b"}], fail)
    l1 = legs_of(r1[3])
    check("steps: a failing step (the stand-in's own failure verdict) fails the job and the steps after it are recorded `skipped` with the reason, not run",
          r1[2].get("outcome") == "failed" and [x["status"] for x in l1] == ["pass", "fail", "skipped", "skipped"] and l1[2]["reason"] == "an earlier step failed" and r1[2].get("steps_ran") == 2, str([x["status"] for x in l1]))
    rw = run_dry("s-wrongsha", [{"type": "dt-i"}], [{"leg": "dt-i", "nth": [1], "do": "wrongsha"}])
    rt = run_dry("s-wrongtiles", [{"type": "dt-i"}], [{"leg": "dt-i", "nth": [1], "do": "wrongtiles"}])
    lw, ltl = legs_of(rw[3]), legs_of(rt[3])
    check("steps: dt-i holds the identity device-test prints to the image the job names, as the driver's own leg does: another SHA-256 or another tile count (the stand-in's wrongsha and wrongtiles) is a `fail` saying which",
          [x["status"] for x in lw] == ["fail"] and "read the image as sha256" in (lw[0]["reason"] or "") and [x["status"] for x in ltl] == ["fail"] and "tiles" in (ltl[0]["reason"] or "")
          and rw[2].get("outcome") == "failed", f"{[(x['status'], x['reason']) for x in lw]} {[(x['status'], x['reason']) for x in ltl]}")
    r2 = run_dry("s-garbage", [{"type": "api-test"}], [{"leg": "api-test", "nth": [1], "do": "garbage"}])
    l2 = legs_of(r2[3])
    check("steps: a tool whose output moved (the stand-in's garbage: exit 0 and no verdict line) is `parse_error`, never a pass, and the job fails",
          r2[2].get("outcome") == "failed" and [x["status"] for x in l2] == ["parse_error"] and "expected one verdict line" in (l2[0]["reason"] or ""), str(l2 and l2[0]["reason"]))
    r3 = run_dry("s-find", [{"type": "soak", "item": tile_ex, "lo": 0, "hi": 1 << 20}, {"type": "soak", "item": tile_ex, "lo": 1 << 20, "hi": 2 << 20}, {"type": "api-test"}],
                 [{"leg": "soak", "op": cat[tile_ex].op, "nth": [1], "do": "mismatch"}])
    l3 = legs_of(r3[3])
    check("steps: a soak slice that finds a mismatch is a recorded `fail` with its operands, a FINDING and not a failure: the chain goes on and the job ends done-with-findings (answer 13)",
          r3[2].get("outcome") == "done-with-findings" and [x["status"] for x in l3] == ["fail", "pass", "pass"] and l3[0]["disagreements"] and r3[2].get("findings") == 1, f"{r3[2].get('outcome')} {[x['status'] for x in l3]}")
    root, cfg = mkroot2("s-stop")
    sc = os.path.join(root, "scenario.json")
    json.dump([{"leg": "dt-q8", "nth": [1], "do": "slow:2"}], open(sc, "w"))
    with env(CFT_STANDIN_SCENARIO=sc, CFT_STANDIN_STATE=os.path.join(root, "st")):
        jid = S.submit(root, cfg, json.dumps(staged(image="quad", steps=[{"type": "dt-i"}, {"type": "dt-q8"}, {"type": "dt-full"}])).encode(), ST.StepRegistry())[0]
        th = threading.Thread(target=lambda: R.serve(root, cfg, SG.StagedRunner(root, cfg), drain=True, poll=0.02, skip_locks=not S.HAVE_FLOCK, out=lambda x: None))
        th.start()
        wait_for(lambda: os.path.exists(os.path.join(root, "st", "n-dt-q8-any-any")), 30)      # the stand-in counts its invocation, then sleeps its two seconds
        safely(S.cancel, root, jid, "tester")            # a plant may have ended the job already
        th.join(120)
    l5 = legs_of(recs(root, "jobs", jid))
    check("steps: a stop asked while a step runs ends the job at that step's end (never in the middle of one): cancelled, the step passed whole, the later one skipped by name",
          rec(root, "jobs", jid).get("outcome") == "cancelled" and [x["status"] for x in l5] == ["pass", "pass", "skipped"] and l5[2]["reason"] == "a stop was requested", str([(x["leg"], x["status"]) for x in l5]))
    if os.name == "posix" and shutil.which("timeout"):
        r6 = run_dry("s-hang", [{"type": "dt-q8", "timeout_s": 2}, {"type": "api-test"}], [{"leg": "dt-q8", "nth": [1], "do": "hang"}])
        l6 = legs_of(r6[3])
        check("steps: a step that hangs is a recorded `timeout` (killed TERM by the wrapper, within seconds) and the job fails, the rest skipped",
              r6[2].get("outcome") == "failed" and [x["status"] for x in l6] == ["timeout", "skipped"] and l6[0]["timed_out"] is True and l6[0]["killed"] == "TERM" and l6[0]["duration_s"] < 15, str([(x["status"], x["duration_s"]) for x in l6]))
    else:
        skip("steps: a step that hangs is a recorded `timeout`", "needs the timeout wrapper (POSIX)")


def steps_real_tools():
    need = ("make", "sh", "git", "sha256sum", "bash", "sed")
    if os.name != "posix" or not all(shutil.which(x) for x in need):
        for n in ("vectors, labelled rc_only", "the exit status is never ignored", "the dry tests with their known flakes allowed by name", "the driver's smoke",
                  "in a dry job the steps with no stand-in leg run their own commands"):
            skip(f"steps: {n}", "needs POSIX with " + ", ".join(need))
        return
    path = fake_ldd("ok") + os.pathsep + os.environ["PATH"]
    fresh = [0]

    def one(steps, dry=False, **kw):
        fresh[0] += 1
        root, cfg = mkroot2(f"t-real{fresh[0]}")
        j, end, rs = job(root, cfg, staged(dry_run=dry, steps=steps, **kw))
        return root, j, end, rs, legs_of(rs)
    with no_users(), env(PATH=path):
        root, j, end, rs, lg = one([{"type": "vectors"}])
        rc, out, _ = cli(root, "status", j)
        check("steps: `vectors` (make vectors, then sha256sum -c) has no parser, so its verdict is its exit status ALONE, and it is LABELLED rc_only in its leg, in the end record and in `status JOB`",
              end.get("outcome") == "done" and lg[0]["status"] == "pass" and lg[0]["verdict_kind"] == "rc_only" and end.get("rc_only_steps") == 1 and "step 0 vectors: pass [rc_only]" in out
              and "rc_only" in lg[0]["notes"][0], f"{end.get('outcome')} {lg} {out}"[:300])
        with env(FAKE_VEC_BAD="1"):
            bad = one([{"type": "vectors"}, {"type": "api-test"}])
        with env(FAKE_VEC_FAIL="1"):
            failing = one([{"type": "vectors"}])
        check("steps: the exit status is never ignored: a vectors step whose sha256sum -c fails (exit 1) or whose make fails (exit 2) is a `fail`, the job fails, and the step after it is skipped",
              bad[2].get("outcome") == "failed" and [x["status"] for x in bad[4]] == ["fail", "skipped"] and bad[4][0]["rc"] == 1 and failing[2].get("outcome") == "failed"
              and failing[4][0]["status"] == "fail" and failing[4][0]["rc"] == 2, f"{[(x['status'], x['rc']) for x in bad[4]]} {[(x['status'], x['rc']) for x in failing[4]]}")
        flakes = ["telemetry hang: ", "stopfile: "]
        with env(FAKE_DRY="flakes"):
            allowed = one([{"type": "drytests", "known_flakes": flakes}])
            plain = one([{"type": "drytests"}])
        with env(FAKE_DRY="real"):
            realf = one([{"type": "drytests", "known_flakes": flakes}])
        with env(FAKE_DRY="lie"):
            lie = one([{"type": "drytests", "known_flakes": flakes}])
        check("steps: the dry tests' known flakes are allowed BY NAME in the spec, as box_nightly.sh allows two: two failures with those names pass and say so (counts, notes); the same without the "
              "spec's allowance fail; a failure that is no flake fails; a log that says 0 failed while the suite exited 1 is parse_error",
              allowed[2].get("outcome") == "done" and allowed[4][0]["counts"]["known_flakes"] == 2 and "known flakes" in allowed[4][0]["notes"][0] and plain[4][0]["status"] == "fail"
              and realf[4][0]["status"] == "fail" and lie[4][0]["status"] == "parse_error" and "exit status is 1" in lie[4][0]["reason"],
              f"{allowed[4][0]['status']} {plain[4][0]['status']} {realf[4][0]['status']} {lie[4][0]['status']}")
        smoke = one([{"type": "driver-quick", "sweep_items": ["sqrt32-rne", "rem32"]}])
        sdry = one([{"type": "driver-quick"}], dry=True)
        d0 = os.path.join(smoke[0], "jobs", smoke[1])
        log0 = open(os.path.join(d0, smoke[4][0]["log"])).read()
        logd = open(os.path.join(sdry[0], "jobs", sdry[1], sdry[4][0]["log"])).read()
        with env(FAKE_QUICK="fail"):
            qf = one([{"type": "driver-quick"}])
        with env(FAKE_QUICK="stopped"):
            qs = one([{"type": "driver-quick"}])
        with env(FAKE_QUICK="noend"):
            qn = one([{"type": "driver-quick"}])
        with env(FAKE_QUICK="dryrun"):
            offered = one([{"type": "driver-quick"}])
            dry_ok = one([{"type": "driver-quick"}], dry=True)
        check("steps: the driver's own dry-run console, offered by a job that is not dry, is refused `dry-run-as-card` too (the leg is `error`); the same console in a dry job is a pass",
              refusal_of(offered[3]).startswith("dry-run-as-card:") and offered[4][0]["status"] == "error" and offered[2].get("outcome") == "failed" and dry_ok[2].get("outcome") == "done" and dry_ok[4][0]["status"] == "pass",
              f"{refusal_of(offered[3])!r} {[x['status'] for x in offered[4]]} {dry_ok[2].get('outcome')}")
        seg = one([{"type": "card-segrun"}], image="quad")
        sd, sl = os.path.join(seg[0], "jobs", seg[1]), (seg[4] or [{}])[0]
        kept = (sl.get("extra") or {}).get("kept_dir")
        check("steps: a failing gate's kept logs (card-segrun's `logs kept in DIR`, made under the step's TMPDIR) are moved into the job's directory beside the step's log, and the scratch directory is gone",
              sl.get("status") == "fail" and bool(kept) and os.path.isfile(os.path.join(sd, kept or "x", "gate1.log")) and not [n for n in os.listdir(sd) if n.startswith(".tmp-")],
              f"{sl.get('status')} {kept} {sorted(os.listdir(sd))}")
        check("steps: a card step that ran in a job that is not dry says so: `card_touched` in its leg and in the end record (a dry job's say false)",
              sl.get("card_touched") is True and seg[2].get("card_touched") is True and sdry[2].get("card_touched") is False, f"{sl.get('card_touched')} {seg[2].get('card_touched')} {sdry[2].get('card_touched')}")
        im = FIX["image"]
        check("steps: `driver-quick` runs hw/card-stress.sh --quick with an out directory in the job's own, the revision-8 cache and the registry's images the driver knows (--image quad=PATH --sha quad=SHA), "
              "and the driver's own --dry-run in a dry job; its verdict is the driver's end line (quick_done, exit 0): a failing smoke or a stopped one is a fail, a log with no end line parse_error",
              smoke[2].get("outcome") == "done" and "--quick --out " in log0 and "00-driver-quick --rev8-images " in log0 and f"--image quad={im['path']} --sha quad={im['sha256']}" in log0
              and "--sweep-items sqrt32-rne,rem32" in log0 and "--dry-run" not in log0 and "--dry-run" in logd and sdry[2].get("outcome") == "done" and sdry[4][0]["standin"] is False
              and qf[4][0]["status"] == "fail" and qs[4][0]["status"] == "fail" and qn[4][0]["status"] == "parse_error", f"{log0[:200]!r} {logd[:120]!r} {[q[4][0]['status'] for q in (qf, qs, qn)]}")
        nv = one([{"type": "vectors"}, {"type": "drytests"}, {"type": "driver-quick"}], dry=True)
        nlogs = {x["leg"]: open(os.path.join(nv[0], "jobs", nv[1], x["log"]), errors="replace").read() for x in nv[4] if x.get("log")}
        check("steps: in a dry job the three steps with no stand-in leg (`vectors`, `drytests`, `driver-quick`) run their OWN commands, and their legs say `dry` and NOT `standin`: `vectors` made vectors/out in "
              "the clone, the suite's log and the smoke's are theirs and not the stand-in's, no card was touched, and the end record says dry_run and card_touched false",
              nv[2].get("outcome") == "done" and [x["leg"] for x in nv[4]] == ["vectors", "drytests", "driver-quick"] and all(x["dry"] is True and x["standin"] is False and x["card_touched"] is False for x in nv[4])
              and os.path.isfile(os.path.join(nv[0], "clones", fixture()["c2"], "vectors", "out", "a.txt")) and len(nlogs) == 3 and not any(t.startswith("standin: would run:") for t in nlogs.values())
              and "card-stress test: 600 checks" in nlogs.get("drytests", "") and "--dry-run" in nlogs.get("driver-quick", "") and nv[2].get("dry_run") is True and nv[2].get("card_touched") is False,
              f"{nv[2].get('outcome')} {[(x['leg'], x['dry'], x['standin']) for x in nv[4]]} {sorted(nlogs)}")


def steps_refusals():
    fx = fixture()
    root, cfg = mkroot2("r-inject")
    blank = ST.Entry("blank", {}, lambda c, st: [sys.executable, "-c", "pass"], lambda c, st, t, rc: DR.L.parse_api_test(t, rc), None, card=False, build="none")
    broken = ST.Entry("broken", {}, lambda c, st: ["x"], None, None, card=False, build="none")
    disguised = ST.Entry("disguised", {}, lambda c, st: DR.standin("api-test", ["api-test"]), lambda c, st, t, rc: DR.L.parse_api_test(t, rc), None, card=False, build="none")
    collide = ST.Entry("collide", {}, lambda c, st: (open(os.path.join(os.path.dirname(c.step_dir), "00-collide.log"), "w").close(), [sys.executable, "-c", "pass"])[1],
                       lambda c, st, t, rc: DR.L.parse_api_test(t, rc), None, card=False, build="none")
    def boom_argv(c, st):
        raise RuntimeError("a template that raises")
    boom = ST.Entry("boom", {}, boom_argv, lambda c, st, t, rc: DR.L.parse_api_test(t, rc), None, card=False, build="none")
    runner = SG.StagedRunner(root, cfg, entries={**ST.ENTRIES, "blank": blank, "broken": broken, "disguised": disguised, "collide": collide, "boom": boom})
    jb = job(root, cfg, staged(steps=[{"type": "api-test"}, {"type": "broken"}]), runner)
    check("steps: a step type with neither a parser nor the rc_only label is refused `parser-unknown` before anything runs (no clone, no leg): its output could not be judged",
          refusal_of(jb[2]).startswith("parser-unknown:") and "broken" in refusal_of(jb[2]) and jb[1].get("outcome") == "refused" and not legs_of(jb[2]) and not any(r["type"] == "code" for r in jb[2]), refusal_of(jb[2]))
    jn = job(root, cfg, staged(steps=[{"type": "blank"}, {"type": "api-test"}]), runner)
    ln = legs_of(jn[2])
    check("steps: a step that prints nothing is recorded `parse_error` (reason no-verdict), the job is refused `no-verdict`, ends failed naming it, and the step after is skipped",
          [x["status"] for x in ln] == ["parse_error", "skipped"] and "no-verdict" in ln[0]["reason"] and refusal_of(jn[2]).startswith("no-verdict:") and jn[1].get("outcome") == "failed"
          and jn[1].get("refusal") == "no-verdict", f"{[x['status'] for x in ln]} {refusal_of(jn[2])!r} {jn[1].get('outcome')}")
    jd = job(root, cfg, staged(dry_run=False, steps=[{"type": "disguised"}, {"type": "api-test"}]), runner)
    ld = legs_of(jd[2])
    check("steps: a stand-in's output in a job that is not dry is never recorded as a card's: the leg is `error` and says standin, the job is refused `dry-run-as-card` and fails",
          [x["status"] for x in ld] == ["error", "skipped"] and ld[0]["standin"] is True and "dry-run-as-card" in ld[0]["reason"] and refusal_of(jd[2]).startswith("dry-run-as-card:")
          and jd[1].get("outcome") == "failed" and jd[1].get("card_touched") is False, f"{[(x['status'], x['standin']) for x in ld]} {refusal_of(jd[2])!r}")
    jc = job(root, cfg, staged(steps=[{"type": "collide"}]), runner)
    check("steps: a file the job would write that exists is `job-exists`: refused, not written over, before the step runs",
          refusal_of(jc[2]).startswith("job-exists:") and "00-collide.log" in refusal_of(jc[2]) and jc[1].get("outcome") == "refused", refusal_of(jc[2]))
    old = GD.KIND_SCANS["xrt"]
    GD.KIND_SCANS["xrt"] = lambda exclude: ([{"pid": 777, "why": "an xclbin argument (cft_hw_quad.xclbin)", "args": "cft-serve --artifact cft_hw_quad.xclbin"}], [])
    try:
        r2, c2 = mkroot2("r-busy")
        jg = job(r2, c2, staged(dry_run=False, image="quad", steps=[{"type": "dt-i"}]))
        jg_dry = job(r2, c2, staged(image="quad", steps=[{"type": "dt-i"}]))
    finally:
        GD.KIND_SCANS["xrt"] = old
    check("steps: a job with a card step that is not dry asks the guard BEFORE it clones anything: a foreign user is `card-busy-foreign` (naming the pid), a `guard_refused` record, no clone, no leg, "
          "the card untouched; the same job as a dry run does not ask",
          refusal_of(jg[2]).startswith("card-busy-foreign:") and "pid 777" in refusal_of(jg[2]) and jg[1].get("outcome") == "refused" and any(r["type"] == "guard_refused" for r in jg[2])
          and not any(r["type"] == "code" for r in jg[2]) and not legs_of(jg[2]) and jg[1].get("card_touched") is False and jg_dry[1].get("outcome") == "done", f"{refusal_of(jg[2])!r} {jg_dry[1].get('outcome')}")
    r3, c3 = mkroot2("r-boom")
    boom1 = S.submit(r3, c3, json.dumps(staged(steps=[{"type": "api-test"}, {"type": "boom"}, {"type": "api-test"}])).encode(), runner.registry)[0]
    boom2 = S.submit(r3, c3, json.dumps(staged()).encode(), runner.registry)[0]
    served = safely(lambda: R.serve(r3, c3, SG.StagedRunner(r3, c3, entries=runner.entries), drain=True, poll=0.02, skip_locks=not S.HAVE_FLOCK, out=lambda x: None))
    boom_rs = recs(r3, "jobs", boom1)
    check("steps: an unexpected error while a job runs (here a command template that raises) ends THAT job, recorded (`runner_error` with the error, the later steps skipped, outcome failed) and "
          "never the service: the next job in the queue still runs",
          served == 2 and rec(r3, "jobs", boom1).get("outcome") == "failed" and any(r["type"] == "runner_error" and "RuntimeError" in r["error"] for r in boom_rs)
          and [x["status"] for x in legs_of(boom_rs)] == ["pass", "skipped", "skipped"] and rec(r3, "jobs", boom2).get("outcome") == "done", f"{served} {rec(r3, 'jobs', boom1).get('outcome')} {[r['type'] for r in boom_rs]}")
    rw, cw = mkroot2("r-window", windows={"zone": "local", "list": [clock_window("w", -60, 3600)]})
    jw = job(rw, cw, wvalid(when={"window": "w"}, code={"commit": fx["c2"], "source": "bundle:u.bundle"}, dry_run=True))
    check("steps: a job of kind window handed to the STAGED runner (not the window runner, which `serve` uses) is refused `window-unsupported`, before anything runs: no clone, no leg, never run as a staged job",
          refusal_of(jw[2]).startswith("window-unsupported:") and jw[1].get("outcome") == "refused" and not legs_of(jw[2]) and not any(r["type"] == "code" for r in jw[2]), refusal_of(jw[2]))
    def claimed_then_lost(name, **lose):
        """A staged job claimed against the whole configuration and run by a runner whose configuration has since lost something: the job's records."""
        rt, ct = mkroot2(name)
        S.submit(rt, ct, json.dumps(staged(image="quad", steps=[{"type": "api-test"}])).encode(), ST.StepRegistry())
        gid, gspec, glog = S.claim_next(rt, ct, "u50-0", time.time(), ST.StepRegistry())
        R.run_claimed(rt, gid, gspec, glog, SG.StagedRunner(rt, {**ct, **lose}))
        return recs(rt, "jobs", gid)
    lost_image, lost_card = claimed_then_lost("r-lost-image", images=[]), claimed_then_lost("r-lost-card", cards=[])
    check("steps: a registry that lost the job's image, or a configuration that lost its card, between the claim and the run is refused by name (`image-unknown`, `card-unknown`): the job ends refused "
          "with the refusal recorded, no `runner_error`, nothing cloned, no leg",
          all(x and x[-1].get("outcome") == "refused" and not legs_of(x) and not any(r["type"] in ("runner_error", "code") for r in x) for x in (lost_image, lost_card))
          and refusal_of(lost_image).startswith("image-unknown:") and "quad" in refusal_of(lost_image) and refusal_of(lost_card).startswith("card-unknown:") and "u50-0" in refusal_of(lost_card),
          f"{refusal_of(lost_image)!r} {refusal_of(lost_card)!r} {[r['type'] for r in lost_image]} {[r['type'] for r in lost_card]}")
    check("steps: the end record of a job that ran says whether it touched the card and whether it was dry, and a job the runner refused is `refused` with the refusal named",
          jb[1].get("refusal") == "parser-unknown" and jb[1].get("dry_run") is True and jb[1].get("card_touched") is False and jb[1].get("commit") == fx["c2"], str(jb[1]))


def table_checks(only=None):
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
    s1_ran = only is None or {"spec", "queue", "records", "cli", "locks"} <= only         # a location check needs the scenarios it reads the records of
    s2_ran = only is None or {"code", "build", "images", "guard", "steps"} <= only
    s3_ran = only is None or "window" in only
    in_jobs, in_root = set(), set()
    for r in ROOTS:
        in_root |= {x.get("name") for x in S.read_records(os.path.join(r, "refusals.jsonl"))}
        jd = os.path.join(r, "jobs")
        for j in os.listdir(jd) if os.path.isdir(jd) else []:
            in_jobs |= {x.get("name") for x in recs(r, "jobs", j) if x["type"] == "refused"}
    off = {"locks-unavailable"} if S.HAVE_FLOCK else {"lock-held", "locks-required"}        # what this platform cannot raise
    wrong = []
    for n, (by, where, _m) in N.REFUSALS.items():
        if s1_ran and by == "S1" and n not in off:
            want = ("job" in where.split(", "), "root" in where.split(", "))
            if (n in in_jobs, n in in_root) != want or (where == "none" and n not in SEEN):
                wrong.append(f"{n} (row says {where}; jobs {n in in_jobs}, refusals.jsonl {n in in_root}, stderr {n in SEEN})")
    if s1_ran:
        check("the table: every refusal it gives to S1 was raised by a scenario and left a record exactly where its row says", not wrong, f"wrong: {wrong}")
    if s3_ran:
        s3b = ("card-unavailable", "card-quarantined", "record-write-failed")                 # the cards' and the records' names are parcel S3b's to raise
        s3a = [n for n, (by, where, _m) in N.REFUSALS.items() if by == "S3" and n not in s3b]
        posix_only = () if os.name == "posix" else ("stop-file-present", "resume-missing", "preflight-failed", "no-fallback")      # raised by the parts that need POSIX
        bad3 = [n for n in s3a if n not in posix_only and (n not in in_jobs or n in in_root)]
        check("the table: every refusal the table gives to S3 but S3b's (" + ", ".join(s3a) + ") was raised by a scenario of the window group and left its `refused` record in the job and nowhere else",
              len(s3a) >= 7 and not bad3, f"not raised, or filed wrong: {bad3}")
    if not s2_ran:
        return
    off2 = set() if os.name == "posix" else {"clone-built", "build-failed", "xrt-not-linked", "build-id-mismatch"}         # the build's scenarios need POSIX
    wrong2 = [n for n, (by, where, _m) in N.REFUSALS.items() if by == "S2" and where != "label" and n not in off2 and (n not in in_jobs or n in in_root)]
    labels = [n for n, (by, where, _m) in N.REFUSALS.items() if where == "label"]
    check("the table: every refusal it gives to S2 was raised by a scenario THROUGH THE RUNNER and left its `refused` record in the job and nowhere else; "
          "the one label (`rc-only`) is raised by nothing, and its scenario is the vectors step's leg",
          not wrong2 and labels == ["rc-only"] and not (set(labels) & (in_jobs | in_root)), f"not raised, or filed wrong: {wrong2}; labels {labels}")


# ---------------------------------------------------------------------------------------- window (parcel S3a)
# The window runner against the driver's own dry run and a fake python. A scratch repository holds the REAL driver and wrapper (hw/card_stress*.py, hw/card-stress.sh,
# copied unchanged) beside the fake host tree; the wrapper execs the python PYTHON names, and the fixture names a script that answers the smoke as FAKE_QUICK says and a long run
# as FAKE_LONG says (end: at once, one cycle; idle: ends at once with no cycle; deaf: ignores --until AND its STOP file, runs FAKE_MAX s; stubborn: ignores --until, ends at its STOP file or by itself after FAKE_MAX s; fail; crash; real: the clone's real driver, --dry-run).
# Parts (`--only window:PART`): calendar spec claim long (everywhere), chain driver end (POSIX: bash, make, a clone). The card is never involved.

WFIX: dict = {}
FAKE_INTERP = r'''#!@PY@
import json, os, signal, sys, time
args = sys.argv[2:]
arg = lambda k: args[args.index(k) + 1] if k in args else None
END = "card-stress ends: {} (exit {}); the card is left idle (no process of this run is alive)"
if "--quick" in args:
    bad = os.environ.get("FAKE_QUICK") == "fail"
    print("fake smoke: " + " ".join(args))
    print(("quick: not every leg passed: {'fail': 1}\n" if bad else "") + END.format("quick_done", int(bad)))
    sys.exit(int(bad))
mode = os.environ.get("FAKE_LONG", "end")
if mode == "real":
    os.environ["PYTHON"] = sys.executable
    os.execv(sys.executable, [sys.executable, sys.argv[1]] + args)
out = arg("--out")
os.makedirs(out, exist_ok=True)
def note_signal(n, frame):
    with open(os.path.join(out, "signals.txt"), "a") as fh:
        fh.write("signal %d\n" % n)
for s in (signal.SIGTERM, signal.SIGINT):
    signal.signal(s, note_signal)
def rec(r):
    with open(os.path.join(out, "metrics.jsonl"), "a") as fh:
        fh.write(json.dumps(r) + "\n")
def end(reason, code):
    rec({"type": "run_end", "reason": reason, "exit": code, "cycles": 1})
    print(END.format(reason, code))
    sys.exit(code)
print("fake driver: cwd " + os.getcwd() + " args " + " ".join(args), flush=True)
if mode == "crash":
    sys.exit(3)
rec({"type": "run_start", "run_id": "fake", "argv": args})
if mode != "idle":
    rec({"type": "cycle_start", "cycle": 1})
if mode == "fail":
    end("card_lost", 3)
if mode == "stubborn":
    t0 = time.time()
    while time.time() - t0 < float(os.environ.get("FAKE_MAX", "25")):
        if os.path.exists(os.path.join(out, "STOP")):
            end("stop_file", 0)
        time.sleep(0.05)
if mode == "deaf":
    time.sleep(float(os.environ.get("FAKE_MAX", "25")))
end("deadline", 0)
'''


def wfixture():
    """Built once: the scratch repository (w1, w2 on main; w3 on bad-vec, whose `make vectors` fails; w4 on bad-build, whose `make` fails), a bundle of them, three images, and the fake python."""
    if WFIX:
        return WFIX
    base = os.path.join(TMP, "wfx")
    repo = os.path.join(base, "repo")
    os.makedirs(os.path.join(repo, "hw"))
    os.makedirs(os.path.join(base, "bundles"))
    git_t(None, "init", "-q", "-b", "main", repo)
    for f in ("card-stress.sh", "card_stress.py", "card_stress_lib.py", "card_stress_standin.py", "card_stress_report.py"):
        shutil.copy(os.path.join(HERE, f), os.path.join(repo, "hw", f))
    tree = {**FAKE_TREE, ".gitignore": GITIGNORE + "__pycache__/\n*.pyc\n", "host/tests/seq_check.py": "THE ROUTINE CORPUS DID NOT REACH EVERY FORM\n", "programs/acceptance.py": "REV8_ORDER = ()\n"}
    tree.pop("hw/card-stress.sh")                                             # the real wrapper stands in its place
    w1 = commit_all(repo, {**tree, "docs/w.txt": "one\n"}, "w1")
    w2 = commit_all(repo, {"docs/w.txt": "two\n"}, "w2")
    git_t(repo, "checkout", "-q", "-b", "bad-vec")
    w3 = commit_all(repo, {"Makefile": ".PHONY: vectors\nvectors:\n\t@exit 2\n"}, "w3")
    git_t(repo, "checkout", "-q", "main")
    git_t(repo, "checkout", "-q", "-b", "bad-build")
    w4 = commit_all(repo, {"host/Makefile": FAKE_MAKEFILE.replace('@test -z "$$FAKE_FAIL" ||', "@false ||")}, "w4")
    git_t(repo, "checkout", "-q", "main")
    git_t(repo, "bundle", "create", os.path.join(base, "bundles", "w.bundle"), "main", "bad-vec", "bad-build")
    interp = os.path.join(base, "fake-python")
    open(interp, "w", newline="").write(FAKE_INTERP.replace("@PY@", sys.executable))
    os.chmod(interp, 0o755)
    imgs = [dict(write_image(os.path.join(base, "img-" + n), cus=c, name="cft_hw_" + n), name=n) for n, c in (("quad", 4), ("single", 1), ("deep", 1))]
    WFIX.update(base=base, repo=repo, bundles=os.path.join(base, "bundles"), w1=w1, w2=w2, w3=w3, w4=w4, interp=interp, images=imgs)
    return WFIX


def mkrootw(name, **runner):
    w = wfixture()
    raw = {"cards": [{"id": "u50-0", "kind": "xrt", "platform": PLAT}], "images": w["images"], "code": {"bundle_dir": w["bundles"], "remote": w["repo"]},
           "runner": {"kill_after_s": 2, "guard_poll_s": 0.05, "guard_wait_max_s": 1, "build_timeout_s": 120, "window_grace_s": 1, "window_poll_s": 0.2, **runner},
           "windows": {"zone": "local", "list": [clock_window("w", -2, 60)]}}
    root = os.path.join(TMP, name)
    os.makedirs(root)
    json.dump(raw, open(os.path.join(root, "config.json"), "w"))
    cfg = C.load_config(root)
    C.ensure_layout(root, cfg)
    ROOTS.append(root)
    return root, cfg


def wspec(commit, out, resume=True, **kw):
    s = {"v": 1, "kind": "window", "name": "nightly", "card": "u50-0", "dry_run": True, "code": {"commit": commit, "source": "bundle:w.bundle"}, "when": {"window": "w"},
         "driver": {"out": out, "resume": resume, "options": {"host_workers": 0, "telemetry_seconds": 0}},
         "preflight": [{"type": "vectors"}, {"type": "drytests", "known_flakes": ["telemetry hang: ", "stopfile: "], "noted_failures": ["report test: ", "progress test: ", "testfiles control: "]},
                       {"type": "driver-quick"}]}
    for k, v in kw.items():
        s.pop(k, None) if v is DEL else s.__setitem__(k, v)
    return s


def night(root, spec_, secs=60, **envv):
    """One night: the root's window `w` made to close `secs` from now, the spec submitted and served by the window runner, the fake python as the driver's python (envv steers it).
    Returns (id, the end record, every record)."""
    p = os.path.join(root, "config.json")
    raw = json.load(open(p))
    raw["windows"]["list"] = [clock_window("w", -2, secs + 2)]
    json.dump(raw, open(p, "w"))
    cfg = C.load_config(root)
    runner = WD.WindowRunner(root, cfg)
    jid, ref = S.submit(root, cfg, json.dumps(spec_).encode(), runner.registry)
    if not ref:
        with env(PYTHON=wfixture()["interp"], **envv), no_users():
            R.serve(root, cfg, runner, drain=True, poll=0.02, skip_locks=not S.HAVE_FLOCK, out=lambda x: None)
    rs = recs(root, "jobs", jid)
    return jid, (rs[-1] if rs else {}), rs


def longlog(root, jid):
    d = os.path.join(root, "jobs", jid)
    return "".join(open(os.path.join(d, n), errors="replace").read() for n in sorted(os.listdir(d)) if n.endswith("-driver-long.log"))


def first(rs, typ):
    return next((r for r in rs if r["type"] == typ), {})


def legsum(rs):
    return [(x["leg"], x["status"], (x["reason"] or "")[:70]) for x in legs_of(rs)]


def window_posix(label):
    if os.name == "posix" and all(shutil.which(x) for x in ("bash", "make", "sh", "git", "sha256sum")):
        return True
    skip(f"window: {label}", "needs POSIX with bash, make, git and sha256sum")
    return False


def group_window():
    parts = {"calendar": window_calendar, "spec": window_spec, "claim": window_claim, "long": window_long, "chain": window_chain, "driver": window_driver, "end": window_end}
    want = {o.split(":", 1)[1] for o in (ONLY or ()) if o.startswith("window:")} if ONLY and "window" not in ONLY else set(parts)
    for name, fn in parts.items():
        if name in want:
            fn()


def window_calendar():
    try:
        zc = C.validate_config({**GOOD, "windows": {"zone": "America/Chicago", "list": [
            {"name": "nightly", "start": "18:00", "end": "08:00"}, {"name": "weekend", "start": "18:00", "end": "07:45", "dates": ["2026-10-23", "2026-10-30"]}]}})
    except N.Refusal as r:
        skip("window: the calendar in a named zone", f"this machine's time zone database lacks America/Chicago: {r.why[:90]}")
        zc = None
    if zc:
        import datetime as dt
        import zoneinfo
        at = lambda *a: dt.datetime(*a, tzinfo=zoneinfo.ZoneInfo("America/Chicago")).timestamp()
        st = lambda name, *a: CAL.state(zc, name, at(*a))
        o, o2, back, fwd = st("nightly", 2026, 10, 22, 20, 0), st("nightly", 2026, 10, 23, 7, 0), st("nightly", 2026, 10, 31, 20, 0), st("nightly", 2027, 3, 13, 20, 0)
        check("window: an ordinary night is the window's 14 hours, 18:00 to 08:00, and at 07:00 it is still the night that began the evening before (across midnight)",
              o["state"] == "open" and (o["opens"], o["closes"]) == (at(2026, 10, 22, 18, 0), at(2026, 10, 23, 8, 0)) and o["length_s"] == 14 * 3600
              and o2["state"] == "open" and o2["opens"] == o["opens"], f"{o} {o2}")
        check("window: the night the clocks change is 15 hours when they go back (2026-11-01) and 13 when they go forward (2027-03-14), not 14: the length is the difference of the epochs "
              "of the two ends in the zone, and the nights either side of them are 14",
              back["length_s"] == 15 * 3600 and fwd["length_s"] == 13 * 3600 and st("nightly", 2026, 10, 30, 20, 0)["length_s"] == 14 * 3600 and st("nightly", 2027, 3, 14, 20, 0)["length_s"] == 14 * 3600,
              f"{back['length_s'] / 3600} h and {fwd['length_s'] / 3600} h")
        w1, w2, w3 = st("weekend", 2026, 10, 23, 20, 0), st("weekend", 2026, 10, 25, 10, 0), st("weekend", 2026, 11, 2, 10, 0)
        check("window: a window with stated dates opens only on them (13.75 hours for 18:00 to 07:45), waits for the next between them, and when the last has passed is `closed`; "
              "an unknown window is None",
              w1["state"] == "open" and w1["length_s"] == 13.75 * 3600 and w2["state"] == "waiting" and w2["opens"] == at(2026, 10, 30, 18, 0) and w3["state"] == "closed"
              and w3["opens"] == at(2026, 10, 30, 18, 0) and CAL.state(zc, "nope", at(2026, 10, 23, 9, 0)) is None and st("nightly", 2026, 10, 23, 9, 0)["state"] == "waiting"
              and st("nightly", 2026, 10, 23, 9, 0)["opens"] == at(2026, 10, 23, 18, 0), f"{w1} {w2} {w3}")
        x = at(2026, 10, 23, 8, 0)
        check("window: the driver reads the scheduler's --until as the same instant: parse_when(fmt(epoch)) is the epoch, to the second", DR.L.parse_when(CAL.fmt(x)) == x, f"{CAL.fmt(x)} {DR.L.parse_when(CAL.fmt(x))} {x}")
    t = time.time()
    cl = C.validate_config({**GOOD, "windows": {"zone": "local", "list": [clock_window("c", -30, 90)]}})
    s = CAL.state(cl, "c", t)
    check("window: in the zone `local` a window read off the clock (HH:MM:SS) is open now, 90 seconds long (give or take the second the clock truncates), and closes about 60 seconds from now",
          s["state"] == "open" and 89 <= s["length_s"] <= 91 and 58 <= s["closes"] - t <= 62, str(s))
    bad = [("a zone no database holds", {"zone": "Mars/Olympus"}, "windows.zone"), ("a date that is not a date", {"list": [{"name": "n", "start": "18:00", "end": "08:00", "dates": ["2026-02-30"]}]}, "windows.list[0].dates"),
           ("dates that are not a list", {"list": [{"name": "n", "start": "18:00", "end": "08:00", "dates": "2026-10-23"}]}, "windows.list[0].dates"),
           ("a time with seconds out of range", {"list": [{"name": "n", "start": "18:00:61", "end": "08:00"}]}, "windows.list[0].start")]
    got = [verdict(lambda w=w: C.validate_config({**GOOD, "windows": w})) or "" for _, w, _ in bad] + [verdict(lambda: C.validate_config({**GOOD, "runner": {"window_grace_s": 0}})) or ""]
    check("window: config.json refuses by name " + ", ".join(b[0] for b in bad) + " and a window_grace_s of 0; it accepts seconds in a time and the runner's window_grace_s and window_poll_s",
          all(g.startswith("config-form:") and want in g for g, (_, _, want) in zip(got, bad)) and got[-1].startswith("config-form:") and "window_grace_s" in got[-1]
          and verdict(lambda: C.validate_config({**GOOD, "windows": {"list": [{"name": "n", "start": "18:00:30", "end": "07:45:15"}]}, "runner": {"window_grace_s": 60, "window_poll_s": 1}})) is None, str(got))


def window_spec():
    os.makedirs(os.path.join(TMP, "co", ".git"))                    # a directory that holds a .git: git's sign of a working tree
    root, cfg = mkroot2("ws-main", windows={"zone": "local", "list": [clock_window("w", -60, 7200), {"name": "past", "start": "18:00", "end": "08:00", "dates": ["2020-01-01"]}]})
    reg = ST.StepRegistry()
    od = wvalid()["driver"]["out"]
    cases = [("a window job with no when.window", wvalid(when=DEL), "spec-form", "when.window"), ("a window job with steps", wvalid(steps=[{"type": "vectors"}], when={"window": "w"}), "spec-form", "steps"),
             ("a window job with an image", wvalid(image="quad", when={"window": "w"}), "spec-form", "image"), ("a window job with no driver", wvalid(driver=DEL, when={"window": "w"}), "spec-form", "driver"),
             ("a driver with no out", wvalid(driver={"resume": True}, when={"window": "w"}), "spec-form", "driver.out"), ("a driver out that is not absolute", wvalid(driver={"out": "x/y"}, when={"window": "w"}), "spec-form", "driver.out"),
             ("an unknown driver field", wvalid(driver={"out": od, "colour": 1}, when={"window": "w"}), "spec-form", "driver.colour"),
             ("an unknown driver option", wvalid(driver={"out": od, "options": {"colour": 1}}, when={"window": "w"}), "spec-form", "driver.options.colour"),
             ("a driver out inside a git working tree", wvalid(driver={"out": os.path.join(TMP, "co", "run")}, when={"window": "w"}), "out-in-checkout", "working tree"),
             ("a sweep_chunk the driver's own parser refuses", wvalid(driver={"out": od, "options": {"sweep_chunk": 4097}}, when={"window": "w"}), "spec-form", "--sweep-chunk 4097"),
             ("a negative host_workers", wvalid(driver={"out": od, "options": {"host_workers": -1}}, when={"window": "w"}), "spec-form", "host_workers"),
             ("a sweep item the catalog does not hold", wvalid(driver={"out": od, "sweep_items": ["nope-rne"]}, when={"window": "w"}), "spec-form", "nope-rne"),
             ("a driver image the registry does not hold", wvalid(driver={"out": od, "images": ["nope"]}, when={"window": "w"}), "image-unknown", "nope"),
             ("a preflight out of order", wvalid(preflight=[{"type": "driver-quick"}, {"type": "vectors"}], when={"window": "w"}), "spec-form", "preflight"),
             ("a preflight with a step that is not a preflight's", wvalid(preflight=[{"type": "api-test"}], when={"window": "w"}), "spec-form", "preflight"),
             ("a preflight step type the registry does not hold", wvalid(preflight=[{"type": "nope"}], when={"window": "w"}), "step-unknown", "nope"),
             ("a staged job with a driver", spec(driver={"out": od}), "spec-form", "driver"), ("a staged job with a preflight", spec(preflight=[{"type": "vectors"}]), "spec-form", "preflight"),
             ("a window the configuration does not hold", wvalid(when={"window": "nope"}), "window-bad", "nope"), ("a window with no occurrence left (its only date was in 2020)", wvalid(when={"window": "past"}), "window-closed", "past")]
    for label, obj, name, frag in cases:
        jid, r = S.submit(root, cfg, json.dumps(obj).encode(), reg)
        got = f"{r.name}: {r.why}" if r else None
        check(f"window spec: {label} is refused {name}, naming {frag!r}, and the job's record says so", got is not None and got.startswith(name + ":") and frag in got and rec(root, "jobs", jid, -2).get("name") == name, str(got))
    import contextlib
    import io
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            DR.CS.parse_args(["--help"])
    except SystemExit:
        pass
    flags = [f for _, f in P.DRIVER_OPTIONS.values()]
    check("window spec: every flag DRIVER_OPTIONS maps a name to is a WHOLE option of the driver's own parser (its --help lists it: argparse alone would take an abbreviation), and the options of the fullest spec pass the parser",
          all(re.search(r"(?<![-\w])" + re.escape(f) + r"(?![-\w])", buf.getvalue()) for f in flags) and DR.parser_problem(P.option_args({"host_workers": 2, "sweep_chunk": 8192, "telemetry_seconds": 0, "deadline_grace": 1.5})) is None
          and DR.parser_problem(["--sweep-chunk", "4097"]) is not None, str(flags))
    jf, rf = S.submit(root, cfg, json.dumps(wvalid(when={"window": "w"})).encode(), R.FAKE_REGISTRY)
    check("window spec: a window job submitted against the FAKE runner's registry (S1's, which has no steps to give it) is refused `window-unsupported` at the submit, so it never reaches a runner that would crash on it",
          rf is not None and rf.name == "window-unsupported" and rec(root, "jobs", jf, -2).get("name") == "window-unsupported", str(rf))
    ok = [S.submit(root, cfg, json.dumps(s_).encode(), reg)[1] for s_ in (wvalid(when={"window": "w"}), spec(when={"window": "w"}, steps=[{"type": "api-test"}]),
                                                                          wvalid(when={"window": "w"}, preflight=[{"type": "driver-quick"}], driver={"out": od, "resume": False, "options": {}}))]
    j = S.submit(root, cfg, json.dumps(wvalid(when={"window": "w"})).encode(), reg)[0]
    sp = json.load(open(os.path.join(root, "queue", j, "spec.json")))
    check("window spec: a window job and a staged job naming a window the configuration holds are accepted, a preflight may be cut to the smoke, and the stored spec has the defaults filled "
          "(priority 10, driver.resume true)", ok == [None, None, None] and sp["priority"] == 10 and sp["driver"]["resume"] is True, f"{ok} {sp.get('priority')} {sp.get('driver')}")


def window_claim():
    t0 = time.time()
    wins = [clock_window("wopen", -60, 7200), clock_window("wlater", 3600, 3600), {"name": "wdates", "start": "18:00", "end": "08:00", "dates": [time.strftime("%Y-%m-%d", time.localtime(t0 + 2 * 86400))]}]
    root, cfg = mkroot2("wc-main", windows={"zone": "local", "list": wins})
    reg = ST.StepRegistry()
    sw = lambda **kw: S.submit(root, cfg, json.dumps(wvalid(**kw)).encode(), reg)[0]
    cl = lambda now=t0, c=None: S.claim_next(root, c or cfg, "u50-0", now, reg)
    later = sw(when={"window": "wlater"})
    rc_s, out_s, _ = cli(root, "status", later, runner=None)
    rc_g, out_g, _ = cli(root, "status", runner=None)
    wl = CAL.state(cfg, "wlater", t0)
    check("window status: a window job still in the queue shows its window (the calendar's answer: when it opens and closes, and that it is waiting) in `status JOB` and in `status`",
          rc_s == 0 and f"window: wlater, waiting: {CAL.fmt(wl['opens'])} to {CAL.fmt(wl['closes'])} (1.00 h)" in out_s and rc_g == 0 and f"window  : {later} (queue)" in out_g and "waiting:" in out_g,
          f"{rc_s} {out_s[:250]!r} {out_g[:300]!r}")
    before = cl()
    waiting = os.path.isdir(os.path.join(root, "queue", later)) and S.read_records(os.path.join(root, "queue", later, "job.jsonl"))[-1]["type"] == "submitted"
    after = cl(t0 + 3601)
    check("window claim: a job whose window has not opened WAITS in the queue (it is not claimed, and nothing is recorded against it); once the window is open it is claimed",
          before is None and waiting and after is not None and after[0] == later, f"{before and before[0]} {waiting} {after and after[0]}")
    short = sw(when={"window": "wopen"}, estimate_s=9000)
    ok = sw(when={"window": "wopen"}, estimate_s=3600)
    got = cl()
    check("window claim: a job whose estimate_s fits what its window has left is claimed, and one whose estimate_s (9000 s, of the 7140 left) exceeds it is refused `window-too-short`, naming the seconds left",
          got is not None and got[0] == ok and rec(root, "jobs", short, -2).get("name") == "window-too-short" and "9000" in rec(root, "jobs", short, -2).get("why", ""), f"{got and got[0]} {rec(root, 'jobs', short, -2)}")
    late = sw(when={"window": "wlater", "deadline": t0 - 5})
    cl()
    check("window claim: a job whose deadline has passed is refused `deadline-passed` even when its window has not opened: it is not made to wait for a window it can no longer use",
          rec(root, "jobs", late, -2).get("name") == "deadline-passed", str(rec(root, "jobs", late, -2)))
    gone = sw(when={"window": "wdates"})
    cl(t0 + 5 * 86400)
    check("window claim: a job whose window has no occurrence left at the claim (its only date has passed) is refused `window-closed`, not left waiting for ever",
          rec(root, "jobs", gone, -2).get("name") == "window-closed", str(rec(root, "jobs", gone, -2)))
    lost = sw(when={"window": "wopen"})                 # submitted after the call above, which would have claimed it: the window is open at that time of day, five days on
    cl(t0, dict(cfg, windows={"zone": "local", "list": []}))
    check("window claim: a job whose window the configuration has lost since the submit is refused `window-bad` at the claim", rec(root, "jobs", lost, -2).get("name") == "window-bad", str(rec(root, "jobs", lost, -2)))


def window_long():
    """Pieces of the long run that need no process, so they run everywhere: the window's end looked at again after the guard's wait and the driver's limit counted from its
    start (the guard and run_step stubbed), the refusals of the run's own start, those about the driver's directory, a person's STOP file, and what the history counts."""
    root, cfg = mkroot2("wl-main", windows={"zone": "local", "list": [clock_window("w", -60, 3600), clock_window("wlater", 3600, 3600)]})
    runner, card, out = WD.WindowRunner(root, cfg), cfg["cards"][0], os.path.join(TMP, "wl-out")
    os.makedirs(out)
    spec_ = P.validate(wvalid(when={"window": "w"}, driver={"out": out, "resume": False}), cfg, runner.registry)
    ctx = SG.Ctx(os.path.join(TMP, "wl-no-clone"), None, {}, "python3", os.path.join(TMP, "wl-rev8"), False)
    n, old_guard, old_run = [0], GD.hold_until_clear, WD.run_step

    def long_(closes, wait):
        """runner._long with the guard stubbed to wait `wait` seconds and run_step stubbed to read its limit and run nothing: (the Refusal's text or None, the log's record types, the limits)."""
        n[0] += 1
        lg, got = S.Log(os.path.join(TMP, f"wl-{n[0]}.jsonl"), f"j{n[0]:06d}", "u50-0"), []

        def fake_run(argv, cwd, env_, logpath, timeout_s, *a, **k):
            got.append(timeout_s)
            r = PR.StepRun()
            r.error, r.start, r.end = "stub: the check reads the limit and runs nothing", time.time(), time.time()
            return r
        GD.hold_until_clear, WD.run_step = (lambda *a, **k: time.sleep(wait)), fake_run
        try:
            v = verdict(lambda: runner._long(spec_, lg, R.StopWatch(root, lg.job, lg), SG._State(0), {}, ctx, 0, {"name": "w", "closes": closes}, card))
        finally:
            GD.hold_until_clear, WD.run_step = old_guard, old_run
        return v, [r["type"] for r in S.read_records(lg.path)], got
    v1, types1, _ = long_(time.time() + 1.0, 1.6)
    check("window long: a window that closes while the job waits for the card (the guard stubbed to wait 1.6 s, the window to close in 1) is refused `window-closed`, naming the wait, and the driver "
          "is never started: no driver_started and no leg in the record", (v1 or "").startswith("window-closed:") and "while the job waited" in v1 and "driver_started" not in types1 and "leg" not in types1, f"{v1!r} {types1}")
    v2, _, lim = long_(time.time() + 100, 0.2)
    check("window long: the long run is given NO limit the scheduler can reach (Logan on N-5, 2026-10-23: warn only): run_step's limit is NEVER_S, about 31 years, whatever the window has left, "
          "so run_step's timeout can never send the driver a TERM or a KILL", v2 is None and lim and lim[0] >= 10 ** 8, f"{v2!r} {lim}")

    def direct(window, **kw):
        n[0] += 1
        lg = S.Log(os.path.join(TMP, f"wl-{n[0]}.jsonl"), f"j{n[0]:06d}", "u50-0")
        sp = P.validate(wvalid(when={"window": window}, driver={"out": out, "resume": False}, **kw), cfg, runner.registry)
        outcome, fields = runner.run(sp, lg, R.StopWatch(root, lg.job, lg))
        return outcome, fields.get("refusal"), [r["type"] for r in S.read_records(lg.path)]
    short, closed = direct("w", estimate_s=7000), direct("wlater")
    check("window long: the run's own start refuses what the claim let by (the clock moves between them): an estimate_s of 7000 against the 3,500 s left is `window-too-short` and a window that is not open is "
          "`window-closed`, each outcome refused before a window record, an image or a clone", short[:2] == ("refused", "window-too-short") and closed[:2] == ("refused", "window-closed")
          and not ({"window", "image", "code", "leg"} & set(short[2] + closed[2])), f"{short} {closed}")
    d0 = os.path.join(TMP, "wl-dir")
    os.makedirs(d0)
    chk = lambda **kw: (verdict(lambda: runner._out_ok({"out": d0, "resume": True, **kw})) or "ok").split(":")[0]
    got_ = [chk()]
    open(os.path.join(d0, "metrics.jsonl"), "w").close()
    got_ += [chk(resume=False), chk()]
    open(os.path.join(d0, "STOP"), "w").close()
    got_ += [chk()]
    os.remove(os.path.join(d0, "STOP"))
    os.remove(os.path.join(d0, "metrics.jsonl"))
    got_ += [chk(resume=False)]
    check("window long: the driver directory's refusals are the launcher's, all three: a resume with no metrics.jsonl is `resume-missing`, a NEW run over one is `job-exists` (the launcher's \"outputs exist\"), "
          "a STOP file is `stop-file-present`, and the two good cases pass", got_ == ["resume-missing", "job-exists", "ok", "stop-file-present", "ok"], str(got_))
    dp = os.path.join(TMP, "wl-person")
    os.makedirs(dp)
    open(os.path.join(dp, "STOP"), "w").write("a person's\n")
    mem = MemLog()
    mem.job = "j000009"
    wt = WD.Watch(dp, type("Asked", (), {"requested": lambda self: True})(), mem, time.time() + 3600, 900, 0.05)
    wt.start(os.getpid())
    wait_for(lambda: wt.sent is not None, 10)
    wt.finish()
    check("window long: a STOP file the scheduler did not make (a person's, there before the cancel) is left alone: the driver is asked by it, the record says `made` false, and it is still there when the watch ends",
          wt.sent == "cancel" and wt.made is None and os.path.exists(os.path.join(dp, "STOP")) and [r.get("made") for r in mem.of("scheduler_stop")] == [False] and not mem.of("scheduler_stop_removed"), str(mem.recs))
    rh, _ch = mkroot2("wl-hist")
    for k, cyc in ((1, 0), (2, 3)):
        jid = f"j{k:06d}"
        os.makedirs(os.path.join(rh, "jobs", jid))
        lg = S.Log(os.path.join(rh, "jobs", jid, "job.jsonl"), jid, "u50-0")
        lg.append("submitted", kind="window", name="n")
        lg.end("done", commit=str(k) * 40, dry_run=True, driver_cycles=cyc)
    check("window long: a window that ended `done` in which the driver started no cycle is not history, whatever its outcome says: of two done jobs only the one with cycles is a passed window",
          WD.history(rh, "u50-0", True) == [("j000002", "2" * 40)], str(WD.history(rh, "u50-0", True)))


def window_chain():
    if not window_posix("the preflight chain, the fallback and the record of a night"):
        return
    w = wfixture()
    out, (root, cfg) = os.path.join(TMP, "wout-chain"), mkrootw("wc-chain")
    sw = lambda rs: [(x["leg"], x["status"]) for x in legs_of(rs)]
    j1, e1, r1 = night(root, wspec(w["w1"], out, resume=False))
    win = first(r1, "window")
    t1 = longlog(root, j1)
    check("window chain: a new commit's night runs the launcher's chain in its order, the window, the images, the preflight, the clone, then vectors, drytests and the smoke and the driver's long run, "
          "each passing; the job ends done, dry, the card untouched, and the end record names the commit, the window and the driver's run_end",
          e1.get("outcome") == "done" and sw(r1) == [("vectors", "pass"), ("drytests", "pass"), ("driver-quick", "pass"), ("driver-long", "pass")]
          and [r["type"] for r in r1 if r["type"] in ("window", "image", "preflight", "code")] == ["window", "image", "image", "image", "preflight", "code"]
          and first(r1, "preflight").get("changed") is True and e1.get("commit") == w["w1"] and e1.get("dry_run") is True and e1.get("card_touched") is False and not e1.get("fallback")
          and e1.get("window") == "w" and e1.get("driver_reason") == "deadline" and e1.get("driver_exit") == 0, f"{e1.get('outcome')} {sw(r1)} {refusal_of(r1)!r}")
    check("window chain: the long run is the launcher's line on the clone: --until the window's end (as the driver reads it), --out the spec's directory, --rev8-images, every registry image with its "
          "SHA-256, the spec's options and --dry-run, and no --resume for a new run; the pid is recorded when the driver starts",
          f"--until {CAL.fmt(win.get('closes', 0))} --out {out} --rev8-images" in t1 and "--resume" not in t1 and "--image quad=" in t1 and "--sha deep=" in t1 and "--host-workers 0" in t1
          and "--telemetry-seconds 0" in t1 and "--dry-run" in t1 and os.path.join("clones", w["w1"]) in t1 and isinstance(first(r1, "driver_started").get("pid"), int), t1[:300])
    j2, e2, r2 = night(root, wspec(w["w1"], out))
    pf2 = first(r2, "preflight")
    check("window chain: the same commit the next night does NOT run vectors and the dry tests again (answer 7): both legs are recorded `skipped`, the reason names the last passed window's job, "
          "and the preflight record says the commit did not change",
          [x["status"] for x in legs_of(r2)[:2]] == ["skipped", "skipped"] and pf2.get("changed") is False and "vectors" in pf2.get("skips", []) and "drytests" in pf2.get("skips", [])
          and j1 in (legs_of(r2)[0].get("reason") or "") and e2.get("outcome") == "done", f"{legsum(r2)} {pf2}")
    check("window chain: the smoke runs EVERY night, the commit unchanged or not (answer 7): driver-quick passes on the second night, and the driver's long run follows it, resumed (--resume)",
          [x for x in sw(r2) if x[0] in ("driver-quick", "driver-long")] == [("driver-quick", "pass"), ("driver-long", "pass")] and "driver-quick" in pf2.get("runs", []) and "--resume" in longlog(root, j2), f"{legsum(r2)} {pf2}")
    j3, e3, r3 = night(root, wspec(w["w2"], out), FAKE_DRY="noted")
    dt3 = next((x for x in legs_of(r3) if x["leg"] == "drytests"), {})
    ok3, st3 = cli(root, "status", j3, runner=None)[:2]
    check("window chain: a new commit whose dry tests fail only on lines the spec names (one known flake, two noted failures of the testfiles) passes the preflight and the night goes on; the leg counts them apart "
          "(known_flakes 1, noted_failures 2) and its notes name the lines; the end record counts the noted failures; `status JOB` shows them",
          e3.get("outcome") == "done" and sw(r3)[:2] == [("vectors", "pass"), ("drytests", "pass")] and (dt3.get("counts") or {}).get("noted_failures") == 2 and (dt3.get("counts") or {}).get("known_flakes") == 1
          and "report test: a" in str(dt3.get("notes")) and e3.get("noted_failures") == 2 and "2 NOTED failure(s)" in st3 and "report test: a" in st3, f"{sw(r3)} {dt3.get('counts')} {st3[:300]}")
    j4, e4, r4 = night(root, wspec(w["w1"], out), FAKE_VEC_FAIL="1")
    check("window chain: a preflight failure on a commit that HAS passed before (w1, though not the last) is the night's failure: `preflight-failed`, outcome failed, the later steps skipped, no fallback, "
          "and the long run never starts",
          e4.get("outcome") == "failed" and e4.get("refusal") == "preflight-failed" and refusal_of(r4).startswith("preflight-failed:") and sw(r4) == [("vectors", "fail"), ("drytests", "skipped"), ("driver-quick", "skipped")]
          and not first(r4, "fallback") and not first(r4, "driver_started"), f"{e4.get('outcome')} {sw(r4)} {refusal_of(r4)!r}")
    j5, e5, r5 = night(root, wspec(w["w3"], out))
    fb = first(r5, "fallback")
    ok5, st5 = cli(root, "status", j5, runner=None)[:2]
    check("window chain: a preflight failure on a commit whose window has never passed (w3: its `make vectors` fails) falls back, by name, to the last commit whose window did (w2, job " + j3 + "): "
          "the night runs on w2, the record says why in a `fallback` record, in the end record and in `status`, and the fake driver ran in w2's clone",
          e5.get("outcome") == "done" and fb.get("from_commit") == w["w3"] and fb.get("to_commit") == w["w2"] and fb.get("last_passed_job") == j3 and "vectors" in fb.get("reason", "")
          and e5.get("commit") == w["w2"] and e5.get("requested_commit") == w["w3"] and (e5.get("fallback") or {}).get("to") == w["w2"] and [r["commit"] for r in r5 if r["type"] == "code"] == [w["w3"], w["w2"]]
          and sw(r5) == [("vectors", "fail"), ("drytests", "skipped"), ("driver-quick", "skipped"), ("vectors", "skipped"), ("drytests", "skipped"), ("driver-quick", "pass"), ("driver-long", "pass")]
          and os.path.join("clones", w["w2"]) in longlog(root, j5) and "FELL BACK from " + w["w3"] in st5, f"{e5.get('outcome')} {sw(r5)} {fb} {refusal_of(r5)!r}")
    check("window chain: only a passed window is history, and a dry job's history is the dry jobs': the passed commits are w1, w1, w2 and (the fallback night, which ran w2) w2 in order, the failed night is not there, "
          "and the real jobs' history is empty",
          [c for _, c in WD.history(root, "u50-0", True)] == [w["w1"], w["w1"], w["w2"], w["w2"]] and WD.history(root, "u50-0", False) == [], str(WD.history(root, "u50-0", True)))
    r6, c6 = mkrootw("wc-nohist")
    j6, e6, rr6 = night(r6, wspec(w["w3"], os.path.join(TMP, "wout-nohist"), resume=False))
    check("window chain: a preflight failure on a new commit with no passed window to fall back to is `no-fallback` (outcome failed, the later steps skipped, no long run): nothing can run, and the record says why",
          e6.get("outcome") == "failed" and e6.get("refusal") == "no-fallback" and refusal_of(rr6).startswith("no-fallback:") and [x[1] for x in sw(rr6)] == ["fail", "skipped", "skipped"]
          and not first(rr6, "fallback") and not first(rr6, "driver_started"), f"{e6.get('outcome')} {sw(rr6)} {refusal_of(rr6)!r}")
    out_b, (rb, cb) = os.path.join(TMP, "wout-build"), mkrootw("wc-build")
    with env(PATH=fake_ldd("ok") + os.pathsep + os.environ["PATH"]):                # the fake host tree builds, ldd says XRT is linked: the jobs are not dry (fake tools, no card)
        jb1, eb1, rb1 = night(rb, wspec(w["w2"], out_b, resume=False, dry_run=False), FAKE_LONG="end")
        jb2, eb2, rb2 = night(rb, wspec(w["w4"], out_b, dry_run=False), FAKE_LONG="end")
    pr, fbb = first(rb2, "preflight_refused"), first(rb2, "fallback")
    check("window chain: a build the preflight cannot make (w4's `make` fails, in a job that is not dry) is a preflight failure like a failed step: `preflight_refused` names `build-failed`, the steps it cut off "
          "are recorded skipped, and the night falls back to the last passed commit (w2, its clone already built) and runs there; each build has a log of its own in the job's directory",
          eb1.get("outcome") == "done" and eb2.get("outcome") == "done" and eb2.get("dry_run") is False and pr.get("name") == "build-failed" and fbb.get("to_commit") == w["w2"]
          and fbb.get("reason", "").startswith("build-failed:") and [x[1] for x in sw(rb2)][:3] == ["pass", "pass", "skipped"] and eb2.get("commit") == w["w2"] and eb2.get("requested_commit") == w["w4"]
          and {"build.log", "build-03.log"} <= set(os.listdir(os.path.join(rb, "jobs", jb2))), f"{eb1.get('outcome')} {eb2.get('outcome')} {refusal_of(rb2)!r} {sw(rb2)} {pr} {fbb} {sorted(os.listdir(os.path.join(rb, 'jobs', jb2)))}")

    ri, ci = mkrootw("wc-idle")
    out_i = os.path.join(TMP, "wout-idle")
    ji1, ei1, ri1 = night(ri, wspec(w["w1"], out_i, resume=False), FAKE_LONG="idle")
    h1 = WD.history(ri, "u50-0", True)
    ji2, ei2, ri2 = night(ri, wspec(w["w1"], out_i), FAKE_LONG="end")
    ll = next((x for x in legs_of(ri1) if x["leg"] == "driver-long"), {})
    check("window chain: a night in which the driver ended at its deadline having started NO cycle did no work and is not a passed window: the long leg is `fail` and says so, the job ends failed, "
          "it is no history, and the next night runs vectors and the dry tests again (the commit never passed) and ends done",
          ei1.get("outcome") == "failed" and ll.get("status") == "fail" and "no cycle" in (ll.get("reason") or "") and ei1.get("driver_cycles") == 0 and h1 == []
          and [x["status"] for x in legs_of(ri2)][:2] == ["pass", "pass"] and first(ri2, "preflight").get("changed") is True and ei2.get("outcome") == "done" and ei2.get("driver_cycles") == 1,
          f"{ei1.get('outcome')} {ll.get('status')} {ll.get('reason')} {h1} {legsum(ri2)}")


def window_driver():
    if not window_posix("the window against the driver's own dry run"):
        return
    w = wfixture()
    tile, _host, rnd = pick_items()
    out, (root, cfg) = os.path.join(TMP, "wout-drv"), mkrootw("wc-drv")
    items = [tile, rnd]
    d = {"out": out, "resume": False, "sweep_items": items, "options": {"host_workers": 0, "telemetry_seconds": 0}}
    j1, e1, r1 = night(root, wspec(w["w1"], out, driver=d), secs=14, FAKE_LONG="real")
    win, lg = first(r1, "window"), next((x for x in legs_of(r1) if x["leg"] == "driver-long"), {})
    recs1 = DR.L.read_records(os.path.join(out, "metrics.jsonl"))[0]
    start1 = next((r for r in recs1 if r.get("type") == "run_start"), {})
    check("window driver: the long run is the driver's OWN --dry-run, unchanged, in the clone: it ran to the window's end and said `deadline` (run_end, exit 0), the job ends done, its --until is the window's end "
          "and its argv carries the images, the items and the options; the driver made legs against its stand-in, and left no STOP or STOPPED.txt",
          e1.get("outcome") == "done" and (lg.get("extra") or {}).get("run_end", {}).get("reason") == "deadline" and (lg.get("extra") or {}).get("run_end", {}).get("exit") == 0
          and CAL.fmt(win.get("closes", 0)) in start1.get("argv", []) and "--dry-run" in start1.get("argv", []) and ",".join(items) in start1.get("argv", [])
          and sum(r.get("type") == "leg" for r in recs1) >= 1 and not os.path.exists(os.path.join(out, "STOP")) and not os.path.exists(os.path.join(out, "STOPPED.txt")),
          f"{e1.get('outcome')} {refusal_of(r1)!r} {legsum(r1)} {start1.get('argv')}")
    j2, e2, r2 = night(root, wspec(w["w1"], out, driver=dict(d, resume=True)), secs=10, FAKE_LONG="real")
    recs2 = DR.L.read_records(os.path.join(out, "metrics.jsonl"))[0]
    check("window driver: the next night resumes the SAME run directory with --resume (the driver's own resume, from its records): a second run_start and a second run_end in the one metrics.jsonl, "
          "the job done, vectors and the dry tests skipped (the commit is unchanged)",
          e2.get("outcome") == "done" and sum(r.get("type") == "run_start" for r in recs2) == 2 and sum(r.get("type") == "run_end" for r in recs2) == 2 and "--resume" in [r for r in recs2 if r.get("type") == "run_start"][-1].get("argv", [])
          and [x["status"] for x in legs_of(r2)][:2] == ["skipped", "skipped"], f"{e2.get('outcome')} {refusal_of(r2)!r}")


def window_end():
    if not window_posix("the end check, the cancel and the launcher's refusals"):
        return
    w = wfixture()
    out, (root, cfg) = os.path.join(TMP, "wout-end"), mkrootw("we-main")
    pre = [{"type": "driver-quick"}]
    j1, e1, r1 = night(root, wspec(w["w1"], out, resume=False, preflight=pre), secs=8, FAKE_LONG="stubborn", FAKE_MAX="25")
    win, lg = first(r1, "window"), next((x for x in legs_of(r1) if x["leg"] == "driver-long"), {})
    ask, gone = first(r1, "scheduler_stop"), first(r1, "scheduler_stop_removed")
    check("window end: a driver that ignores the window's end (--until) and runs on is asked to stop THROUGH ITS STOP FILE once it has run on past the end by the grace (1 s): not before, not by a signal, "
          "and it stops within seconds of the ask, at the leg it is in (run_end `stop_file`); the job is done, the driver was not killed, and the scheduler's own end check is in the record",
          e1.get("outcome") == "done" and ask.get("why") == "window" and ask.get("made") is True and ask["t"] >= win["closes"] + 1 - 0.05 and (lg.get("extra") or {}).get("run_end", {}).get("reason") == "stop_file"
          and (lg.get("extra") or {}).get("scheduler_stop") == "window" and not lg.get("timed_out") and lg.get("killed") is None and lg["end_epoch"] < win["closes"] + 1 + 4, f"{e1.get('outcome')} {ask} {lg.get('extra')} {legsum(r1)}")
    check("window end: the STOP file the scheduler made is removed when the driver has ended (and the record says so), so the next night is not refused for it",
          bool(gone) and not os.path.exists(os.path.join(out, "STOP")), f"{gone} {os.listdir(out)}")
    j2, e2, r2 = night(root, wspec(w["w1"], out, preflight=pre), secs=30, FAKE_LONG="end")
    check("window end: the next night after an end check resumes the same directory and runs (the scheduler's STOP file was not left behind)", e2.get("outcome") == "done", f"{e2.get('outcome')} {refusal_of(r2)!r}")
    open(os.path.join(out, "STOP"), "w").write("a person's\n")
    j3, e3, r3 = night(root, wspec(w["w1"], out, preflight=pre), secs=30, FAKE_LONG="end")
    os.remove(os.path.join(out, "STOP"))
    j4, e4, r4 = night(root, wspec(w["w1"], os.path.join(TMP, "wout-none"), preflight=pre), secs=30, FAKE_LONG="end")
    check("window end: the launcher's refusals about the driver's directory: a STOP file in it is `stop-file-present`, and a directory with no metrics.jsonl to resume is `resume-missing`; "
          "each refuses the job before any step (no clone, no leg)",
          e3.get("refusal") == "stop-file-present" and e4.get("refusal") == "resume-missing" and e3.get("outcome") == e4.get("outcome") == "refused" and not legs_of(r3) and not legs_of(r4)
          and not first(r3, "code") and not first(r4, "code"), f"{e3.get('outcome')} {refusal_of(r3)!r} | {e4.get('outcome')} {refusal_of(r4)!r}")
    p = os.path.join(root, "config.json")
    raw = json.load(open(p))
    raw["windows"]["list"] = [clock_window("w", -2, 120)]
    json.dump(raw, open(p, "w"))
    cfg = C.load_config(root)
    runner = WD.WindowRunner(root, cfg)
    jid = S.submit(root, cfg, json.dumps(wspec(w["w1"], out, preflight=pre)).encode(), runner.registry)[0]
    with env(PYTHON=w["interp"], FAKE_LONG="stubborn", FAKE_MAX="30"), no_users():
        th = threading.Thread(target=lambda: R.serve(root, cfg, runner, drain=True, poll=0.02, skip_locks=not S.HAVE_FLOCK, out=lambda x: None))
        th.start()
        wait_for(lambda: not th.is_alive() or any(r["type"] == "driver_started" for r in recs(root, "running", jid)), 40)
        started = th.is_alive()                          # the driver is running: the job is still in running/ (a job refused at its start has gone before the cancel)
        t0 = time.time()
        how = safely(S.cancel, root, jid, "tester")
        th.join(60)
    took, rs = time.time() - t0, recs(root, "jobs", jid)
    lg = next((x for x in legs_of(rs) if x["leg"] == "driver-long"), {})
    check("window end: a CANCEL of a running window job stops the driver, through its STOP file, within seconds (not at the window's end, which is two minutes off and the fake's 30): the job ends cancelled, "
          "the record says the scheduler asked because of the cancel, the driver ended at its stop file, and the file is gone",
          started and how == "stop-requested" and took < 8 and rec(root, "jobs", jid).get("outcome") == "cancelled" and first(rs, "scheduler_stop").get("why") == "cancel"
          and (lg.get("extra") or {}).get("run_end", {}).get("reason") == "stop_file" and not os.path.exists(os.path.join(out, "STOP")), f"{started} {how} {took:.1f} s {rec(root, 'jobs', jid).get('outcome')} {lg.get('extra')}")
    ro, co = mkrootw("we-over")
    out_o = os.path.join(TMP, "wout-over")
    raw = json.load(open(os.path.join(ro, "config.json")))
    raw["windows"]["list"] = [clock_window("w", -2, 5)]                     # closes in about 3 s, the grace is 1 s
    json.dump(raw, open(os.path.join(ro, "config.json"), "w"))
    co = C.load_config(ro)
    runner = WD.WindowRunner(ro, co)
    ja = S.submit(ro, co, json.dumps(wspec(w["w1"], out_o, resume=False, preflight=pre)).encode(), runner.registry)[0]
    jb = S.submit(ro, co, json.dumps(wspec(w["w1"], out_o, preflight=pre)).encode(), runner.registry)[0]      # the next window's job, queued behind the first
    old_extra = WD.HARD_EXTRA_S
    WD.HARD_EXTRA_S = 2                                                    # the old limit, shortened: the end + the grace + 2 s
    try:
        with env(PYTHON=w["interp"], FAKE_LONG="deaf", FAKE_MAX="10"), no_users():
            th = threading.Thread(target=lambda: R.serve(ro, co, runner, drain=True, poll=0.02, skip_locks=not S.HAVE_FLOCK, out=lambda x: None))
            th.start()
            wait_for(lambda: not th.is_alive() or any(r["type"] == "driver_overrun" for r in recs(ro, "running", ja)), 40)
            mid = [r for r in recs(ro, "running", ja) if r["type"] == "driver_overrun"]
            b_mid = [r["type"] for r in recs(ro, "queue", jb)] if os.path.isdir(os.path.join(ro, "queue", jb)) else None
            st_mid = cli(ro, "status", runner=None)[1]
            th.join(60)
    finally:
        WD.HARD_EXTRA_S = old_extra
    rs = recs(ro, "jobs", ja)
    ov = [r for r in rs if r["type"] == "driver_overrun"]
    lg = next((x for x in legs_of(rs) if x["leg"] == "driver-long"), {})
    endr = rec(ro, "jobs", ja)
    check("window end: a driver that runs on past the old limit (the end + the grace + the extra, shortened to 2 s here) is NAMED once, `driver_overrun`, with the time past the end and its pid, and is NEVER signalled "
          "(the driver's own note of the signals it got does not exist; the leg is not timed out or killed); the job ends only when the driver does, and its end record carries the overrun",
          len(ov) == 1 and ov[0]["pid"] == first(rs, "driver_started").get("pid") and ov[0]["past_end_s"] >= 3 and not os.path.exists(os.path.join(out_o, "signals.txt")) and lg.get("status") == "pass"
          and not lg.get("timed_out") and lg.get("killed") is None and lg.get("end_epoch", 0) - ov[0]["t"] >= 2.5 and endr.get("outcome") == "done" and (endr.get("overrun") or {}).get("pid") == ov[0]["pid"],
          f"{len(ov)} {ov[:1]} {lg.get('status')} {lg.get('killed')} {endr.get('outcome')} {sorted(os.listdir(out_o))}")
    check("window end: while the driver overruns `status` names it (still running, how far past the end, its pid), and the NEXT window's job waits behind it: neither claimed nor refused (its record is its submit alone, "
          "then and after the first job ends, its window being closed by then: it waits for the next occurrence)",
          len(mid) == 1 and "DRIVER OVERRUN: still running" in st_mid and str(mid[0]["pid"]) in st_mid and b_mid == ["submitted"] and [r["type"] for r in recs(ro, "queue", jb)] == ["submitted"]
          and not os.path.isdir(os.path.join(ro, "jobs", jb)), f"{len(mid)} {b_mid} {st_mid[-300:]!r} {[r['type'] for r in recs(ro, 'queue', jb)]}")


# ---------------------------------------------------------------------------------------- plants

GROUPS = {"spec": group_spec, "queue": group_queue, "records": group_records, "cli": group_cli, "locks": group_locks,
          "code": group_code, "build": group_build, "images": group_images, "guard": group_guard, "steps": group_steps, "window": group_window}


def make_copy(name: str, edits: list) -> str:
    d = os.path.join(TMP, "plant-" + re.sub(r"[^A-Za-z0-9_.,-]+", "-", name))             # a part of a group (steps:jobs) names a directory: no colon on Windows
    os.makedirs(os.path.join(d, "sched"))
    shutil.copy(os.path.join(HERE, "test_sched.py"), d)
    for f in os.listdir(SCHED):
        if f.endswith(".py") or f == "cft-sched":
            shutil.copy(os.path.join(SCHED, f), os.path.join(d, "sched"))
    for f in ("card_stress.py", "card_stress_lib.py", "card_stress_standin.py", "card_stress_report.py", "card-stress.sh"):      # the driver, beside the copy, unchanged: the scheduler imports it
        shutil.copy(os.path.join(HERE, f), d)                                                                                  # (sched_driver.py) and the window fixture commits it to its scratch repository
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
    imp = ("import sys; sys.path.insert(0, sys.argv[1]); import sched_names, sched_spec, sched_config, sched_state, sched_run, cft_sched, sched_driver, sched_proc, "
           "sched_guard, sched_code, sched_images, sched_build, sched_steps, sched_staged, sched_calendar, sched_window")
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
    ("an empty card is taken for a card", [E("sched_state.py", "    if not c:", "    if False:")], "records", "records: an empty card is not a card", None),
    ("an over-long card is called missing or not a string", [E("sched_state.py", 'return None, f"is longer than {CARD_MAX} characters"', 'return None, "is not a string"')],
     "records", "a card longer than 200 characters is not recorded as a card either", None),
    ("a queued spec that cannot be read is refused in records that name no card", [E("sched_state.py", "card0, why0 = job_card(d)  ", 'card0, why0 = None, "plant"  ')],
     "records", "a queued spec that cannot be read is refused `queue-corrupt` in records that name the card", None),
    ("a job's log writes a record that names no card and says nothing", [E("sched_state.py", "        if self.job is not None and not self.card and not self.no_card:", "        if False:")],
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
    ("a record names no card", [E("sched_state.py", '"job": self.job, "card": self.card or None}', '"job": self.job}')], "records", "every record names its card", False),
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
    # ---- parcel S2: the code stage, the images, the guard, the build, the steps. `posix` is "posix" where the scenario needs POSIX (make, sh, nice, timeout, /proc).
    ("S2: HEAD is not asserted", [E("sched_code.py", "    if rc != 0 or head != sha:", "    if False:")], "code", "a clone in the cache whose HEAD is not the spec's commit is refused", False),
    ("S2: a clone in the cache is repaired, not asserted", [E("sched_code.py", '    facts = assert_clone(clone, sha, code.get("assert") or {})',
                                                          '    git(clone, "checkout", "-q", "--detach", sha)\n    facts = assert_clone(clone, sha, code.get("assert") or {})')],
     "code", "a clone in the cache whose HEAD is not the spec's commit is refused", False),
    ("S2: a dirty status is not asserted", [E("sched_code.py", "    if rc != 0 or changed:", "    if False:")], "code", "a clone whose HEAD is right and whose status is not clean is refused", False),
    ("S2: a string's count is ignored", [E("sched_code.py", "        if found != count:", "        if False:")], "code", "each string is found exactly the stated number of times", False),
    ("S2: the rtl/ tree is not compared", [E("sched_code.py", '    if want is not None and facts["rtl_tree"] != want:', "    if False:")], "code", "the rtl/ tree the spec names is compared", False),
    ("S2: a commit that is no ancestor is accepted", [E("sched_code.py", '        if git(clone, "merge-base", "--is-ancestor", anc, "HEAD")[0] != 0:', "        if False:")], "code", "a named ancestor is checked", False),
    ("S2: an unpushed commit runs without the spec's word", [E("sched_code.py", '    if state != "pushed" and not allowed:', "    if False:")], "code", "a commit no branch of the remote holds is refused `commit-unpushed`", False),
    ("S2: the registry's SHA-256 is not compared to the file's", [E("sched_images.py", '    if digest != entry["sha256"]:', "    if False:")], "images", "a registry whose SHA-256 is not the file's is refused", False),
    ("S2: SHA256SUMS is not compared", [E("sched_images.py", "    if listed != digest:", "    if False:")], "images", "the directory's SHA256SUMS is compared", False),
    ("S2: the manifest's SHA-256 is not compared", [E("sched_images.py", '    if man.get("sha256") != digest:', "    if False:")], "images", "the manifest beside the image is a witness too", False),
    ("S2: the tile count is not compared", [E("sched_images.py", "    if found != want:", "    if False:")], "images", "the tile count is the manifest's number of compute units", False),
    ("S2: the platform is not compared", [E("sched_images.py", "    if not plat == rplat == cplat:", "    if False:")], "images", "the platform must be the manifest's", False),
    ("S2: a job's image is not held to its files", [E("sched_staged.py", "            image = IM.check_image(entry, card)", '            image = dict(entry, path=IM.expand(entry["path"]))')],
     "images", "through a job the same refusals end it refused", False),
    ("S2: the guard is blind to an idle cft-serve", [E("sched_guard.py", "    return CS.find_card_users(exclude_pids=set(exclude_pids))",
                                                   '    users, beside = CS.find_card_users(exclude_pids=set(exclude_pids))\n    return [u for u in users if "cft-serve" not in u["args"]], beside')],
     "guard", "an idle `cft-serve --artifact IMAGE` is a card user", False),
    ("S2: the guard counts its own process and the shell above it", [E("sched_guard.py", "    return CS.find_card_users(exclude_pids=set(exclude_pids))",
                                                                  '    users, beside = CS.find_card_users(exclude_pids=set(exclude_pids))\n    procs, mine, cur = {p["pid"]: p for p in CS.list_processes()}, [], __import__("os").getpid()\n'
                                                                  '    while cur in procs and cur not in [m["pid"] for m in mine]:\n'
                                                                  '        mine.append({"pid": cur, "why": CS.card_user(procs[cur]), "args": " ".join(procs[cur]["args"])})\n        cur = procs[cur]["ppid"]\n'
                                                                  '    return users + [m for m in mine if m["why"]], beside')],
     "guard", "the process that asks, what it started and the shell that launched it are not foreign users", False),
    ("S2: the ldd check is dropped", [E("sched_build.py", "        elif not linked:", "        elif False:")], "build", "a tool whose ldd does not name xrt_coreutil is refused", "posix"),
    ("S2: the build id is not compared", [E("sched_build.py", "    if trc != 0 or brc != 0 or not bin_id or bin_id != tree_id:", "    if False:")], "build", "the tools' build id is held to the tree's", "posix"),
    ("S2: the tree's build id is not held to the commit", [E("sched_build.py", "    if tree_id != want:", "    if False:")], "build", "and the tree's id must name the job's commit", "posix"),
    ("S2: a failing make is not refused", [E("sched_build.py", '    if rc != 0:\n        raise Refusal("build-failed", f"make exited', '    if False:\n        raise Refusal("build-failed", f"make exited')],
     "build", "a make that fails is refused `build-failed`", "posix"),
    ("S2: the dry tests are allowed in a built clone", [E("sched_build.py", "    if products:", "    if False:")], "build", "the dry tests are refused `clone-built` in a clone that has been built", "posix"),
    ("S2: a step that forbids the build is not asked", [E("sched_staged.py", '            if e.build == "forbids":', "            if False:")], "build", "the dry tests are refused `clone-built` in a clone that has been built", "posix"),
    ("S2: a parser passes a log with no verdict", [E("sched_steps.py", '    m = _one(DRIVER_END, text, "driver end line")\n',
                                                '    m = DRIVER_END.search(text)\n    if m is None:\n        return L.Verdict(True, {"exit": 0})\n')],
     "steps:parsers", "parse_driver_quick refuses a log with no end line", False),
    ("S2: a parsed step's exit status is ignored", [E("sched_steps.py", '        _rc_agrees(rc, True, "drytests")', "        pass")], "steps:parsers", "parse_drytests refuses (VerdictError", False),
    ("S2: a step with no parser ignores its exit status", [E("sched_steps.py", '        return ("pass" if run.rc == 0 else "fail"), L.Verdict(run.rc == 0, {}, [f"rc_only:',
                                                         '        return "pass", L.Verdict(True, {}, [f"rc_only:')], "steps:parsers", "a step with no parser is judged by its exit status ALONE", False),
    ("S2: known flakes are allowed without the spec's word", [E("sched_steps.py", "    flakes = [f for f in fails if any(f.startswith(k) for k in known_flakes)]", "    flakes = list(fails)")],
     "steps:parsers", "parse_drytests reads the suite's last line", False),
    ("S2: an rc_only verdict is not labelled", [E("sched_staged.py", '"verdict_kind": "rc_only" if e.rc_only else "parsed"', '"verdict_kind": "parsed"')], "steps:real",
     "`vectors` (make vectors, then sha256sum -c) has no parser", "posix"),
    ("S2: a stand-in's output is recorded as a card's", [E("sched_staged.py", "        offered = is_dry_text(text) and not dry", "        offered = False")], "steps:refusals",
     "a stand-in's output in a job that is not dry is never recorded as a card's", False),
    ("S2: a dry job's legs do not say standin", [E("sched_staged.py", "standin=wrapped or offered,", "standin=False,")], "steps:jobs", "a dry job runs every step of the registry that has a stand-in leg", False),
    ("S2: a dry job asks the guard", [E("sched_staged.py", "        if not dry and any(self.entries[s[\"type\"]].is_card(s) for s in steps):", "        if any(self.entries[s[\"type\"]].is_card(s) for s in steps):")],
     "steps:jobs", "a dry job asks no guard", False),
    ("S2: a dry job builds", [E("sched_staged.py", "        if dry:\n            rec = BD.dry_record()", "        if False:\n            rec = BD.dry_record()")], "steps:jobs", "a dry job builds nothing", False),
    ("S2: a job with a card step does not ask the guard at its start", [E("sched_staged.py", '            GD.hold_until_clear(log, card["kind"], 0, rcfg["guard_poll_s"])', "            pass")],
     "steps:refusals", "a job with a card step that is not dry asks the guard BEFORE it clones anything", False),
    ("S2: a failed step does not skip the rest", [E("sched_staged.py", '            S.failed, S.skip = True, "an earlier step failed"', "            S.failed = True")], "steps:jobs",
     "a failing step (the stand-in's own failure verdict) fails the job", False),
    ("S2: a soak mismatch fails the chain", [E("sched_staged.py", '        if status == "fail" and e.finding:', "        if False:")], "steps:jobs", "a soak slice that finds a mismatch is a recorded `fail`", False),
    ("S2: a step type with no parser runs", [E("sched_staged.py", "            if e.parse is None and not e.rc_only:", "            if False:")], "steps:refusals", "a step type with neither a parser nor the rc_only label is refused", False),
    ("S2: a blank log is not no-verdict", [E("sched_staged.py", "        if no_verdict:", "        if False:")], "steps:refusals", "a step that prints nothing is recorded `parse_error`", False),
    ("S2: a file the job would write is written over", [E("sched_proc.py", '        return open(path, "xb")', '        return open(path, "wb")')], "steps:refusals", "a file the job would write that exists is `job-exists`", False),
    ("S2: an unexpected error ends the service", [E("sched_staged.py", "        except Exception as e:                                        # a defect here", "        except KeyboardInterrupt as e:                                # a defect here")],
     "steps:refusals", "an unexpected error while a job runs", False),
    ("S2: the command's default runner is the fake one", [E("cft_sched.py", 'choices=("staged", "fake"), default="staged"', 'choices=("staged", "fake"), default="fake"')],
     "steps:jobs", "the command's default runner is the staged one", False),
    ("S2: a driver's own dry run is recorded as a card's", [E("sched_driver.py", " or any(DRY_RUN_LINE.search(ln) for ln in head)", " or False")], "steps:real",
     "the driver's own dry-run console, offered by a job that is not dry", "posix"),
    ("S2: a failed clone is left behind", [E("sched_code.py", "        if os.path.isdir(tmp):\n            remove_tree(tmp)", "        if False:\n            remove_tree(tmp)")], "code",
     "a full commit the bundle does not hold is refused `commit-missing`", False),
    ("S2: a card kind has no image check", [E("sched_config.py", 'CARD_KINDS = {"xrt": "an Alveo card driven through XRT over PCIe (the U50)"}', 'CARD_KINDS = {"xrt": "an Alveo card driven through XRT over PCIe (the U50)", "serial": "x"}')],
     "images", "every kind of card the configuration admits has its image check, its guard and its build", False),
    ("S2: the build's targets are not the driver's", [E("sched_build.py", '"api-test", "remote-test", "divsqrt-soak", "clause5-soak"]\nTOOLS', '"api-test", "divsqrt-soak", "clause5-soak"]\nTOOLS')], "build",
     "the targets, the tools and the optional tools are the driver's own", False),
    ("S2: the build is made without XRT=1", [E("sched_build.py", "    flags = [\"XRT=1\", f\"XRT_ROOT={rcfg['xrt_root']}\"]", "    flags = [f\"XRT_ROOT={rcfg['xrt_root']}\"]")], "build",
     "a clean build is made on the clone with XRT=1", "posix"),
    ("S2: a leg's command is not the driver's", [E("sched_steps.py", '**_dt(["-n", "4096"], "full")', '**_dt(["-n", "4097"], "full")')], "steps:registry",
     "the registry's command for each of the driver's legs, on each image", False),
    ("S2: a host job inherits the card's environment", [E("sched_staged.py", "drop = CS.HOST_JOB_DROPS", "drop = ()")], "steps:jobs", "a host item's step never sees the card", False),
    ("S2: a stop is not looked for between steps", [E("sched_staged.py", "            if not S.skip and stop.requested():", "            if False:")], "steps:jobs",
     "a stop asked while a step runs ends the job at that step's end", False),
    ("S2: a failing gate's kept logs are lost", [E("sched_staged.py", "            shutil.move(kd, dest)", "            pass")], "steps:real", "a failing gate's kept logs", "posix"),
    ("S2: a card step that ran is not marked card_touched", [E("sched_staged.py", "card_touched=bool(e.is_card(st) and not dry and run.pid is not None)", "card_touched=False")], "steps:real",
     "a card step that ran in a job that is not dry says so", "posix"),
    ("S2: a registry path's environment variable is not expanded", [E("sched_images.py", "    return os.path.expandvars(os.path.expanduser(path))", "    return path")], "images",
     "a registry path may carry an environment variable", False),
    ("S2: dt-i's image identity is not held", [E("sched_steps.py", '    if e.get("image_sha256") != im["sha256"]:', "    if False:")], "steps:jobs", "dt-i holds the identity", False),
    ("S2: a window job is run as a staged one", [E("sched_staged.py", '        if spec["kind"] != "staged":', "        if False:")], "steps:refusals", "a job of kind window handed to the STAGED runner", False),
    ("S2: a timeout is not enforced", [E("sched_proc.py", '        if shutil.which("timeout"):', "        if False:"),
                                   E("sched_proc.py", '        deadline = time.monotonic() + timeout_s + (kill_after_s + 30 if POSIX and shutil.which("timeout") else 0)', "        deadline = time.monotonic() + 10 ** 9")],
     "steps:run_step", "the timeout is ENFORCED", "posix"),
    ("S2: a process is stopped by pattern and not by PID", [E("sched_proc.py", '            os.killpg(proc.pid, signal.SIGTERM if sig == "TERM" else signal.SIGKILL)',
                                                           '            subprocess.run(["pkill", "-" + ("TERM" if sig == "TERM" else "KILL"), "-f", next(a for a in map(str, proc.args) if a.startswith("bystander-"))])')],
     "steps:run_step", "with no timeout wrapper the loop ends a hung step", "posix"),
    ("S2: a step is not niced", [E("sched_proc.py", '        if nice and shutil.which("nice"):', "        if False:")], "steps:run_step", "a step runs niced", "posix"),
    ("S2: a step stays in the scheduler's process group", [E("sched_proc.py", 'kw = {"start_new_session": True} if POSIX else', "kw = {} if POSIX else")], "steps:run_step", "a step runs in a process group of its own", "posix"),
    ("S2: a step's standard input is left open", [E("sched_proc.py", "stdin=subprocess.DEVNULL, env=env, cwd=cwd", "stdin=None, env=env, cwd=cwd")], "steps:run_step", "a step's standard input is closed", "posix"),
    ("S2: a refusal the table gives to S2 that nothing raises", [E("sched_names.py", '    "card-busy-foreign": ("S2", "job",', '    "never-raised-s2": ("S2", "job", "x"), "card-busy-foreign": ("S2", "job",')],
     "code,build,images,guard,steps,table", "the table: every refusal it gives to S2", None),
    ("S2: a cached clone's pushed ref outlives the remote's branch", [E("sched_code.py", '"--no-tags", "--prune", remote', '"--no-tags", remote')], "code",
     "a cached clone does not go on answering `pushed` for a branch the remote has since deleted", False),
    ("S2: every leg of a dry job says standin", [E("sched_staged.py", "standin=wrapped or offered,", "standin=dry or offered,")], "steps:real",
     "in a dry job the three steps with no stand-in leg", "posix"),
    ("S2: a registry that lost the job's image is a runner_error", [E("sched_staged.py", 'entry = next((i for i in cfg["images"] if i["name"] == spec["image"]), None)',
                                                                       'entry = next(i for i in cfg["images"] if i["name"] == spec["image"])')],
     "steps:refusals", "a registry that lost the job's image, or a configuration that lost its card", False),
    ("S2: a configuration that lost the job's card is a runner_error", [E("sched_staged.py", 'card = next((c for c in cfg["cards"] if c["id"] == log.card), None)',
                                                                           'card = next(c for c in cfg["cards"] if c["id"] == log.card)')],
     "steps:refusals", "a registry that lost the job's image, or a configuration that lost its card", False),
    # ---- parcel S3a: the window. The groups are parts of `window` (and one of `steps`); chain, driver and end need POSIX.
    ("S3a: the window's end is not enforced", [E("sched_window.py", 'else "window" if time.time() >= self.closes + self.grace else None', "else None")], "window:end",
     "window end: a driver that ignores the window's end", "posix"),
    ("S3a: the changed-clock night is taken as 14 hours", [E("sched_calendar.py", "    return wall(zone, day, a), wall(zone, day if b > a else day + dt.timedelta(days=1), b)",
                                                           "    o = wall(zone, day, a)\n    return o, o + ((b[0] - a[0]) * 3600 + (b[1] - a[1]) * 60 + b[2] - a[2]) % 86400")],
     "window:calendar", "window: the night the clocks change is 15 hours", False),
    ("S3a: vectors and the dry tests run when the commit did not change", [E("sched_window.py", '        gated = [s for s in steps if s["type"] in GATED and not changed]', "        gated = []")],
     "window:chain", "window chain: the same commit the next night does NOT run vectors", "posix"),
    ("S3a: the smoke is skipped when the commit did not change", [E("sched_window.py", 'GATED = ("vectors", "drytests")', 'GATED = ("vectors", "drytests", "driver-quick")')],
     "window:chain", "window chain: the smoke runs EVERY night", "posix"),
    ("S3a: a failed preflight on a new commit leaves the card idle when a passed commit exists", [E("sched_window.py", "            if last is None:\n                raise Refusal(\"no-fallback\"",
                                                                                                      "            if True:\n                raise Refusal(\"no-fallback\"")],
     "window:chain", "falls back, by name", "posix"),
    ("S3a: a fallback from a commit that has passed before", [E("sched_window.py", "            if want in [c for _, c in hist]:", "            if False:")], "window:chain",
     "window chain: a preflight failure on a commit that HAS passed before", "posix"),
    ("S3a: a failed preflight does not stop the night", [E("sched_window.py", "        if problem:\n            if want in", "        if False:\n            if want in")], "window:chain",
     "window chain: a preflight failure on a commit that HAS passed before", "posix"),
    ("S3a: a cancel does not stop the driver", [E("sched_window.py", 'why = "cancel" if self.stop.requested() else "window" if', 'why = "window" if')], "window:end",
     "window end: a CANCEL of a running window job stops the driver", "posix"),
    ("S3a: the scheduler's own STOP file is left behind", [E("sched_window.py", "        if self.made:\n            try:\n                os.unlink(self.path)", "        if False:\n            try:\n                os.unlink(self.path)")],
     "window:end", "window end: the STOP file the scheduler made is removed", "posix"),
    ("S3a: a STOP file in the driver's directory is not refused", [E("sched_window.py", '        if os.path.exists(os.path.join(d["out"], "STOP")):', "        if False:")], "window:end",
     "window end: the launcher's refusals about the driver's directory", "posix"),
    ("S3a: a job is claimed before its window opens", [E("sched_state.py", '                if ws and ws["state"] == "waiting":', "                if False:")], "window:claim",
     "window claim: a job whose window has not opened WAITS", False),
    ("S3a: the estimate is not held to the window", [E("sched_state.py", '            if ws and spec.get("estimate_s") and spec["estimate_s"] > ws["closes"] - now_t:', "            if False:")], "window:claim",
     "window claim: a job whose estimate_s fits", False),
    ("S3a: a deadline already past is waited out with the window", [E("sched_state.py", "            if isinstance(wn, str) and not (isinstance(dl0, (int, float)) and now_t > dl0):", "            if isinstance(wn, str):")],
     "window:claim", "window claim: a job whose deadline has passed is refused", False),
    ("S3a: a window the configuration does not hold is accepted", [E("sched_spec.py", "        if ws is None:\n            raise Refusal(\"window-bad\"", "        if ws is None:\n            ws = {\"state\": \"open\"}\n        if False:\n            raise Refusal(\"window-bad\"")],
     "window:spec", "window spec: a window the configuration does not hold is refused window-bad", False),
    ("S3a: a window job is accepted against the fake runner's registry", [E("sched_spec.py", '        if not hasattr(registry, "check_window"):', "        if False:")], "window:spec",
     "window spec: a window job submitted against the FAKE runner's registry", False),
    ("S3a: a refused build is not a preflight failure", [E("sched_window.py", 'BUILD_REFUSALS = ("build-failed", "xrt-not-linked", "build-id-mismatch", "clone-built")', "BUILD_REFUSALS = ()")], "window:chain",
     "window chain: a build the preflight cannot make", "posix"),
    ("S3a: the fallback's build writes over the first build's log", [E("sched_window.py", 'blog = "build.log" if first == 0 else f"build-{first:02d}.log"', 'blog = "build.log"')], "window:chain",
     "window chain: a build the preflight cannot make", "posix"),
    ("S3a: noted failures are allowed without the spec's word", [E("sched_steps.py", "    noted = [f for f in fails if f not in flakes and any(f.startswith(k) for k in noted_failures)]",
                                                               "    noted = [f for f in fails if f not in flakes]")],
     "steps:parsers", "steps: parse_drytests keeps the spec's `noted_failures` APART", False),
    ("S3a: the window's end is not looked at again after the guard's wait", [E("sched_window.py", "            if time.time() >= ws[\"closes\"]:\n                raise Refusal(\"window-closed\", f\"the window closed at {CAL.fmt(ws['closes'])}, while the job waited",
                                                                                "            if False:\n                raise Refusal(\"window-closed\", f\"the window closed at {CAL.fmt(ws['closes'])}, while the job waited")],
     "window:long", "window long: a window that closes while the job waits for the card", False),
    ("S3a: the kill is put back (the long run is given a limit it can reach), seen without a process", [E("sched_window.py", 'logpath, NEVER_S, rcfg["kill_after_s"]',
                                                                                                         'logpath, ws["closes"] - time.time() + rcfg["window_grace_s"] + HARD_EXTRA_S, rcfg["kill_after_s"]')],
     "window:long", "window long: the long run is given NO limit the scheduler can reach", False),
    ("S3a: the kill is put back, seen against a driver that runs on", [E("sched_window.py", 'logpath, NEVER_S, rcfg["kill_after_s"]', 'logpath, ws["closes"] - time.time() + rcfg["window_grace_s"] + HARD_EXTRA_S, rcfg["kill_after_s"]')],
     "window:end", "window end: a driver that runs on past the old limit", "posix"),
    ("S3a: an overrun is not named", [E("sched_window.py", "                self._note_overrun()", "                pass")], "window:end", "window end: a driver that runs on past the old limit", "posix"),
    ("S3a: a night in which the driver started no cycle is a passed window", [E("sched_window.py", '        if status == "pass" and not S.stopped and not cycles:', "        if False:")], "window:chain",
     "window chain: a night in which the driver ended at its deadline having started NO cycle", "posix"),
    ("S3a: the history counts a done night in which the driver started no cycle", [E("sched_window.py", 'and end.get("commit") and end.get("driver_cycles"):', 'and end.get("commit"):')], "window:long",
     "window long: a window that ended `done` in which the driver started no cycle is not history", False),
    ("S3a: a driver out inside a git working tree is accepted", [E("sched_spec.py", "        if above:\n            raise Refusal(\"out-in-checkout\"", "        if False:\n            raise Refusal(\"out-in-checkout\"")], "window:spec",
     "window spec: a driver out inside a git working tree is refused out-in-checkout", False),
    ("S3a: the driver's options are not held to the driver's own parser", [E("sched_steps.py", '        why = parser_problem(option_args(spec["driver"].get("options"))) if spec["driver"].get("options") else None', "        why = None")],
     "window:spec", "window spec: a sweep_chunk the driver's own parser refuses is refused spec-form", False),
    ("S3a: an option's flag is not the driver's", [E("sched_spec.py", '"host_workers": ("nonneg", "--host-workers")', '"host_workers": ("nonneg", "--host-worker")')], "window:spec",
     "window spec: every flag DRIVER_OPTIONS maps a name to is a WHOLE option", False),
    ("S3a: a new run over an earlier run's metrics.jsonl is allowed", [E("sched_window.py", '        if not d["resume"] and have:', "        if False:")], "window:long",
     "window long: the driver directory's refusals are the launcher's, all three", False),
    ("S3a: a STOP file the scheduler did not make is removed", [E("sched_window.py", "        if self.made:\n            try:\n                os.unlink(self.path)", "        if self.sent:\n            try:\n                os.unlink(self.path)")],
     "window:long", "window long: a STOP file the scheduler did not make", False),
    ("S3a: the run's own start does not hold the estimate to the window", [E("sched_window.py", '        if spec.get("estimate_s", 0) > ws["closes"] - now:', "        if False:")], "window:long",
     "window long: the run's own start refuses what the claim let by", False),
    ("S3a: the run's own start does not look at the window's state", [E("sched_window.py", "        if ws[\"state\"] != \"open\":\n            raise Refusal(\"window-closed\", f\"window {ws['name']!r} is not open when the job starts",
                                                                      "        if False:\n            raise Refusal(\"window-closed\", f\"window {ws['name']!r} is not open when the job starts")],
     "window:long", "window long: the run's own start refuses what the claim let by", False),
    ("S3a: a refusal the table gives to S3 that nothing raises", [E("sched_names.py", '    "no-fallback": ("S3", "job",', '    "never-raised-s3": ("S3", "job", "x"), "no-fallback": ("S3", "job",')],
     "window,table", "the table: every refusal the table gives to S3 but S3b's", None),
]


def plant_skipped(posix) -> bool:
    """True where a plant's scenario cannot run on this platform (it needs flock(2), a platform without it, or POSIX)."""
    return (posix == "flock" and not S.HAVE_FLOCK) or (posix == "noflock" and S.HAVE_FLOCK) or (posix == "posix" and os.name != "posix")


def plants(only_text: str | None):
    ctl = {}
    if not only_text:
        for g in sorted({p[2] for p in PLANTS if not plant_skipped(p[4])}):               # a group whose every plant is skipped here makes 0 checks: no control
            d = make_copy("control-" + g, [])
            rc, n, fails, err = run_copy(d, g)
            ctl[g] = n
            check(f"plants: the CONTROL (an unmodified copy of the code and of this test) passes the {g} group, {n} checks", rc == 0 and not fails and n > 0, "; ".join(fails)[:300] or err[-200:])
    for n, (label, edits, g, want, posix) in enumerate(PLANTS):
        if only_text and only_text not in label:
            continue
        if plant_skipped(posix):
            skip(f"plant [{label}]", "needs a platform without flock(2)" if posix == "noflock" else "needs POSIX (flock(2), make, nice, timeout, /proc), which this platform lacks")
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
    global ONLY
    only = ONLY = set(sys.argv[sys.argv.index("--only") + 1].split(",")) if "--only" in sys.argv else None
    plant_text = sys.argv[sys.argv.index("--plant") + 1] if "--plant" in sys.argv else None
    TMP = tempfile.mkdtemp(prefix="sched-test-")
    t0 = time.time()
    try:
        for name, fn in GROUPS.items():
            if (only is None or name in only or any(o.startswith(name + ":") for o in only)) and not plant_text:
                before, bad = CHECKS, len(FAILS)
                try:
                    fn()
                except Exception:
                    traceback.print_exc()
                    check(f"{name}: the group ran to its end", False, "it crashed (traceback above)")
                print(f"{name}: {CHECKS - before} checks, {len(FAILS) - bad} failed")
        if (only is None or "table" in only) and not plant_text:
            table_checks(only)
        if (only is None or "plants" in only) and "--no-plants" not in sys.argv:
            plants(plant_text)
    finally:
        try:
            CODE.remove_tree(TMP)            # git's object files are read-only, and Windows will not delete those without a chmod first
        except OSError:
            shutil.rmtree(TMP, ignore_errors=True)
    print(f"sched test: {CHECKS} checks, {len(FAILS)} failed, {len(SKIPS)} skipped, {time.time() - t0:.0f} s")
    for f in FAILS:
        print("  FAILED:", f[:300])
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
