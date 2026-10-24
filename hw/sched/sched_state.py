# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""The state root's operations: the locks, the job's record, the file queue, hold and release.

A JOB IS A DIRECTORY THAT MOVES BY RENAME, and on POSIX a rename is atomic on one filesystem:
  submit   built whole as queue/.tmp-ID, then renamed to queue/ID (the queue never shows half a job);
  claim    queue/ID -> running/ID, so of two claimants exactly one wins, and the loser's rename fails;
  cancel   of a queued job: queue/ID -> jobs/ID (it competes for the same rename, so it cannot also run);
           of a running one: running/ID/STOP is created and the runner looks for it at a safe point;
  finish   the end record, SHA256SUMS, then running/ID -> jobs/ID: a job is in jobs/ complete or not at all.
job.jsonl is born at submit, so a refusal has somewhere to leave its record. Ids come from markers
(ids/jNNNNNN, created O_EXCL and never deleted), so an id is never reused and no lock is needed for it.
Order is priority, then id AS A NUMBER (j999999 before j1000000; as text it is the other way round): the id sequence is
the scheduler's own clock of submissions and cannot step back.
THE EXCLUSIVITY IS POSIX rename(2)'S, NOT THIS CODE'S: on the Windows this was written on, eight threads renaming one
directory to one target all report success (measured, test_sched.py's rename_exclusive), so there a claim is exclusive
only if one claimant is the only one, which `serve --no-locks` says by name. The service runs on Linux.
"""
from __future__ import annotations

import errno
import getpass
import hashlib
import json
import os
import re
import socket
import time

import sched_calendar as CAL
from sched_names import OUTCOMES, REFUSALS, Refusal
from sched_spec import parse_text, sig_status, validate

try:
    import fcntl
except ImportError:                      # Windows: no flock, so the locks are refused or skipped by name
    fcntl = None
HAVE_FLOCK = fcntl is not None
ID_RE = re.compile(r"j(\d{6,})\Z")
O_BINARY = getattr(os, "O_BINARY", 0)


def user() -> str:
    try:
        return getpass.getuser()
    except Exception:
        return "unknown"


def parse_job_id(text: str) -> str:
    if not isinstance(text, str) or not ID_RE.match(text):
        raise Refusal("job-unknown", f"{text!r} is not a job id (j and six or more digits)")
    return text


def id_key(name: str) -> int:
    """An id as a number, to sort by: j999999 comes before j1000000 (as text it does not)."""
    return int(name[1:])


# ---------------------------------------------------------------------------------------- locks

class Lock:
    """An exclusive, non-blocking flock(2) on a file, held until release() or the process ends (the kernel
    drops it with the process, so a dead holder never leaves a stale lock). skip=True takes nothing and
    returns True: the caller has said so by name (--no-locks) and records it."""

    def __init__(self, path: str, skip: bool = False):
        self.path, self.skip, self.fd = path, skip, None

    def acquire(self, tries: int = 1, delay: float = 0.1) -> bool:
        if self.skip:
            return True
        if not HAVE_FLOCK:
            raise Refusal("locks-unavailable", "this platform has no flock(2); `serve --no-locks` runs without locks and says so in its records")
        fd = os.open(self.path, os.O_RDWR | os.O_CREAT, 0o644)
        for i in range(tries):
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                self.fd = fd
                return True
            except OSError as e:
                if e.errno not in (errno.EACCES, errno.EAGAIN):
                    os.close(fd)
                    raise
            if i + 1 < tries:
                time.sleep(delay)
        os.close(fd)
        return False

    def write_info(self, **info) -> None:
        if self.fd is not None:
            os.ftruncate(self.fd, 0)
            os.lseek(self.fd, 0, 0)
            os.write(self.fd, (json.dumps(info, sort_keys=True) + "\n").encode())

    def release(self) -> None:
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None


def lock_held(path: str):
    """True if someone holds the lock, False if it is free, None if this platform cannot tell. It takes a shared
    lock for an instant, which a holder's exclusive lock refuses; a service starting at that instant retries."""
    if not HAVE_FLOCK:
        return None
    try:
        fd = os.open(path, os.O_RDONLY)
    except FileNotFoundError:
        return False
    try:
        fcntl.flock(fd, fcntl.LOCK_SH | fcntl.LOCK_NB)
        fcntl.flock(fd, fcntl.LOCK_UN)
        return False
    except OSError as e:
        if e.errno in (errno.EACCES, errno.EAGAIN):
            return True
        raise
    finally:
        os.close(fd)


# ---------------------------------------------------------------------------------------- records

class Log:
    """An append-only JSON-lines file. Every record carries its type, its time, its job and its card. A record of a JOB
    names its card (as asked until the job is placed, then the card that ran it) or says why none could be read: a log
    opened for a job with no card (None or empty) and no `no_card` reason refuses to write (ValueError). `no_card` is for the
    one case where none can be read, a submit whose spec is not an object or whose `card` is missing, not a string, empty or
    longer than CARD_MAX characters; its records say `card: null` and `card_unreadable: why`, and the why says which. A log that is no job's (refusals.jsonl) names a card only for a card verb.
    Each append is one write and an fsync; a torn last line (no newline) is broken off before the next record."""

    def __init__(self, path: str, job: str | None = None, card: str | None = None, no_card: str | None = None):
        self.path, self.job, self.card, self.no_card = path, job, card, no_card

    def append(self, type_: str, **fields) -> dict:
        if self.job is not None and not self.card and not self.no_card:
            raise ValueError(f"job {self.job}: a record must name its card, or say why none could be read")
        rec = {"type": type_, "t": round(time.time(), 3), "job": self.job, "card": self.card or None}
        if not self.card and self.no_card:
            rec["card_unreadable"] = self.no_card
        rec.update(fields)
        line = (json.dumps(rec, sort_keys=True, separators=(",", ":")) + "\n").encode()
        try:
            with open(self.path, "rb") as r:
                r.seek(0, 2)
                if r.tell():
                    r.seek(-1, 2)
                    if r.read(1) != b"\n":
                        line = b"\n" + line
        except FileNotFoundError:
            pass
        fd = os.open(self.path, os.O_WRONLY | os.O_APPEND | os.O_CREAT | O_BINARY, 0o644)
        try:
            os.write(fd, line)
            os.fsync(fd)
        finally:
            os.close(fd)
        return rec

    def end(self, outcome: str, **fields) -> dict:
        if outcome not in OUTCOMES:
            raise ValueError(f"{outcome!r} is not an outcome ({', '.join(OUTCOMES)})")
        return self.append("ended", outcome=outcome, **fields)


def read_records(path: str) -> list:
    """The records of a log. A line that is not JSON (a torn tail) is not a record."""
    try:
        with open(path, "rb") as fh:
            data = fh.read()
    except FileNotFoundError:
        return []
    out = []
    for ln in data.split(b"\n"):
        if ln.strip():
            try:
                out.append(json.loads(ln))
            except ValueError:
                pass
    return out


CARD_MAX = 200


def card_text(c) -> tuple:
    """(c, None) when c is a card that can be recorded as asked, a non-empty string of at most CARD_MAX characters, else
    (None, why) with the reason for this case: is not a string, is empty, is longer than CARD_MAX characters."""
    if not isinstance(c, str):
        return None, "is not a string"
    if not c:
        return None, "is empty"
    if len(c) > CARD_MAX:
        return None, f"is longer than {CARD_MAX} characters"
    return c, None


def job_card(d: str) -> tuple:
    """(card, None) as the job's own `submitted` record has it, else (None, why): the card a job asked for when its
    spec.json cannot be trusted (a queued spec that is damaged, a cancel, a restart)."""
    for r in read_records(os.path.join(d, "job.jsonl")):
        if r.get("type") == "submitted":
            if r.get("card") is None:
                return None, "the job's submitted record names no card"
            card, why = card_text(r["card"])
            return (card, None) if card else (None, f"the job's submitted record: its card {why}")
    return None, "the job has no submitted record"


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for blk in iter(lambda: fh.read(1 << 20), b""):
            h.update(blk)
    return h.hexdigest()


def _files(d: str) -> list:
    return sorted(n for n in os.listdir(d) if n != "SHA256SUMS" and os.path.isfile(os.path.join(d, n)))


EXTRA = "sums-extra.json"        # parcel S4a: the files a window's sums list BESIDES its directory's top level: {"files": [{"name", "sha256"}]}


def _read_extra(d: str) -> list:
    with open(os.path.join(d, EXTRA), "rb") as fh:
        return [(e["name"], e["sha256"]) for e in json.loads(fh.read().decode())["files"]]


def _extra(d: str) -> list:
    """[(name, sha256)] of the job's EXTRA list, or [] (none, or a damaged one: the files it should have named are then not in the sums, and `extra_problem` says so)."""
    try:
        return _read_extra(d)
    except (OSError, ValueError, KeyError, TypeError):
        return []


def extra_problem(d: str):
    """None when the job has no EXTRA list or it reads; else why it does not. A damaged list drops the run's and the smoke's lines from the sums, which must not happen silently:
    `check_sums` reports it and `seal` puts it in the end record, and `status JOB` shows it (SUMS PROBLEM; plain `status` does not show this line for the newest window job)."""
    if not os.path.isfile(os.path.join(d, EXTRA)):
        return None
    try:
        _read_extra(d)
    except (OSError, ValueError, KeyError, TypeError) as e:
        return f"{EXTRA} cannot be read ({type(e).__name__}): the run's and the smoke's files are NOT in this job's SHA256SUMS"
    return None


def write_sums(d: str) -> None:
    """The job's SHA256SUMS: a line for every file of its top level and for each name of its EXTRA list. A name inside the directory (the smoke's files, one level down) is
    hashed now. An ABSOLUTE name (the run's own files, outside the job, which the next night resumes) keeps the hash taken when the night ended, and `check_sums` leaves
    it be: it holds for the lead's copy of that night, not for the file after the next night."""
    rows = [(sha256_file(os.path.join(d, n)), n) for n in _files(d)]
    for n, h in _extra(d):
        if os.path.isabs(n):
            rows.append((h, n))
        elif os.path.isfile(os.path.join(d, n)):
            rows.append((sha256_file(os.path.join(d, n)), n))
    with open(os.path.join(d, "SHA256SUMS"), "wb") as fh:
        fh.write("".join(f"{h}  {n}\n" for h, n in rows).encode())


def check_sums(d: str) -> list:
    """What is wrong with a job directory's SHA256SUMS, as a list of texts: what `sha256sum -c` would say of the names INSIDE the directory (a listed file missing, one that differs, one not
    listed) and a damaged EXTRA list. A name that is ABSOLUTE, the run's own files, is NOT looked at (see write_sums): `sha256sum -c` in the directory would also check those."""
    try:
        with open(os.path.join(d, "SHA256SUMS"), "rb") as fh:
            lines = fh.read().decode().splitlines()
    except FileNotFoundError:
        return ["SHA256SUMS is missing"]
    listed = dict((n, h) for h, _, n in (ln.partition("  ") for ln in lines))
    bad = [f"{n} is not listed" for n in _files(d) if n not in listed]
    for n, h in sorted(listed.items()):
        p = os.path.join(d, n)
        if os.path.isabs(n):
            continue                                            # a file of the run, outside the job (see write_sums)
        if not os.path.isfile(p):
            bad.append(f"{n} is listed and missing")
        elif sha256_file(p) != h:
            bad.append(f"{n} differs from its sum")
    return bad + ([extra_problem(d)] if extra_problem(d) else [])


def seal(d: str, log: Log, outcome: str, **fields) -> None:
    """The end record, whose last word is the outcome, and then the sums over every file, the end record included. A damaged EXTRA list is named in the end record (`sums_problem`)."""
    if extra_problem(d):
        fields["sums_problem"] = extra_problem(d)
    log.end(outcome, **fields)
    write_sums(d)


def finish(root: str, jid: str, log: Log, outcome: str, **fields) -> None:
    d = os.path.join(root, "running", jid)
    seal(d, log, outcome, **fields)
    os.rename(d, os.path.join(root, "jobs", jid))


# ---------------------------------------------------------------------------------------- the queue

def alloc_id(root: str) -> str:
    d = os.path.join(root, "ids")
    n = max([int(m.group(1)) for m in map(ID_RE.match, os.listdir(d)) if m] + [0]) + 1
    while True:
        jid = f"j{n:06d}"
        try:
            os.close(os.open(os.path.join(d, jid), os.O_CREAT | os.O_EXCL | os.O_WRONLY))
            return jid
        except FileExistsError:
            n += 1


def _plain(x):
    return x if isinstance(x, (str, int)) and not isinstance(x, bool) and len(str(x)) <= 200 else None


def submit(root: str, cfg: dict, raw: bytes, registry: dict) -> tuple:
    """(job id, the Refusal or None). A refused spec still becomes a job: jobs/ID holds what was sent, a `refused`
    record and an end record whose outcome is `refused`. The scheduler fills `owner`; nothing in the spec can."""
    jid = alloc_id(root)
    tmp = os.path.join(root, "queue", ".tmp-" + jid)
    os.mkdir(tmp)
    obj = spec = refusal = None
    try:
        obj = parse_text(raw)
        spec = validate(obj, cfg, registry)
    except Refusal as r:
        refusal = r
    shown = spec or (obj if isinstance(obj, dict) else {})
    if not isinstance(obj, dict):
        card, why = None, "the spec is not a JSON object"
    elif "card" not in shown:
        card, why = None, "the spec's card is missing"
    else:
        card, why = card_text(shown["card"])
        why = f"the spec's card {why}" if why else None
    log = Log(os.path.join(tmp, "job.jsonl"), jid, card, why)
    log.append("submitted", owner=user(), host=socket.gethostname(), raw_sha256=hashlib.sha256(raw).hexdigest(),
               signature=sig_status(obj), name=_plain(shown.get("name")), kind=_plain(shown.get("kind")),
               priority=_plain(shown.get("priority")), preempt=_plain(shown.get("preempt")))
    if refusal is None:
        with open(os.path.join(tmp, "spec.json"), "wb") as fh:
            fh.write((json.dumps(spec, indent=2, sort_keys=True) + "\n").encode())
        os.rename(tmp, os.path.join(root, "queue", jid))
        return jid, None
    with open(os.path.join(tmp, "spec.rejected"), "wb") as fh:
        fh.write(raw)
    log.append("refused", name=refusal.name, why=refusal.why)
    seal(tmp, log, "refused", refusal=refusal.name)
    os.rename(tmp, os.path.join(root, "jobs", jid))
    return jid, refusal


def queue_entries(root: str) -> list:
    """[(id, spec or None)] in claim order: an unreadable entry first (it is cleared at once), then priority, then id."""
    out = []
    qd = os.path.join(root, "queue")
    for name in os.listdir(qd):
        if not ID_RE.match(name):
            continue
        try:
            with open(os.path.join(qd, name, "spec.json"), "rb") as fh:
                spec = json.loads(fh.read().decode("utf-8"))
            if not isinstance(spec, dict) or type(spec.get("priority")) is not int:
                spec = None
        except (OSError, ValueError):
            spec = None
        out.append((name, spec))
    out.sort(key=lambda e: (e[1] is not None, -(e[1] or {}).get("priority", 0), id_key(e[0])))
    return out


def claim(root: str, jid: str) -> bool:
    """Win queue/ID by renaming it into running/. On POSIX exactly one of any number of claimants succeeds."""
    try:
        os.rename(os.path.join(root, "queue", jid), os.path.join(root, "running", jid))
        return True
    except FileNotFoundError:
        return False
    except PermissionError:
        # On Windows this would be a sharing violation (a handle open inside the directory). That was NOT measured here: what was
        # measured is that racing renames of one directory all succeed (test_sched.py's rename_exclusive). Not a win; the job stays queued.
        if os.name == "nt":
            return False
        raise


def claim_next(root: str, cfg: dict, card_id: str, now_t: float, registry: dict):
    """The front of the queue for this card, claimed: (id, spec, log), or None. A job that cannot run (its spec
    unreadable, no longer valid, past its deadline) is finished `refused`, with its record, and the scan goes on."""
    cards = {c["id"]: c["kind"] for c in cfg["cards"]}
    for jid, spec in queue_entries(root):
        if spec is not None:
            want = spec.get("card")
            if want in cards and want != card_id:
                continue                                        # another card's job
            nb = (spec.get("when") or {}).get("not_before")
            if isinstance(nb, (int, float)) and now_t < nb:
                continue                                        # not yet
            wn, dl0 = (spec.get("when") or {}).get("window"), (spec.get("when") or {}).get("deadline")
            if isinstance(wn, str) and not (isinstance(dl0, (int, float)) and now_t > dl0):
                ws = CAL.state(cfg, wn, now_t)
                if ws and ws["state"] == "waiting":
                    continue                                    # its window is not open yet (a deadline already past is refused below, not waited out)
        if not claim(root, jid):
            continue                                            # another claimant, or a cancel, won it
        d = os.path.join(root, "running", jid)
        card0, why0 = job_card(d)                               # as asked (the job's own submitted record), until it is placed
        log = Log(os.path.join(d, "job.jsonl"), jid, card0, why0)
        try:
            if spec is None:
                raise Refusal("queue-corrupt", "spec.json cannot be read")
            spec = validate(spec, cfg, registry)                # against the configuration of now
            dl = (spec.get("when") or {}).get("deadline")
            if dl is not None and now_t > dl:
                raise Refusal("deadline-passed", f"the deadline {dl} had passed at {now_t}")
            ws = CAL.state(cfg, spec["when"]["window"], now_t) if "window" in spec.get("when", {}) else None
            if ws and ws["state"] != "open":
                raise Refusal("window-closed", f"window {ws['name']!r} is not open ({ws['state']}; its occurrence nearest {CAL.fmt(ws['opens'])} to {CAL.fmt(ws['closes'])})")
            if ws and spec.get("estimate_s") and spec["estimate_s"] > ws["closes"] - now_t:
                raise Refusal("window-too-short", f"estimate_s {spec['estimate_s']} exceeds the {ws['closes'] - now_t:.0f} s the window {ws['name']!r} has left (it closes {CAL.fmt(ws['closes'])})")
        except Refusal as r:
            log.append("refused", name=r.name, why=r.why)
            finish(root, jid, log, "refused", refusal=r.name)
            continue
        log.card = card_id                                      # placed: `any` becomes this card's id
        log.append("claimed", card_kind=cards[card_id], card_requested=spec["card"], priority=spec["priority"])
        return jid, spec, log
    return None


def stop_asked(d: str) -> bool:
    """True when the job's own record shows its runner has already asked what it runs to stop (a window's driver: `scheduler_stop`, or `driver_overrun`): a cancel then adds
    nothing but its own record, and the answer says so."""
    return any(r.get("type") in ("scheduler_stop", "driver_overrun") for r in read_records(os.path.join(d, "job.jsonl")))


def cancel(root: str, jid: str, who: str) -> str:
    """'dequeued' (it never ran), 'stop-requested' or 'stop-already-requested' (it ends at its next safe point; the latter too when the job's record shows the
    runner had already asked its work to stop)."""
    parse_job_id(jid)
    q, r, j = (os.path.join(root, s, jid) for s in ("queue", "running", "jobs"))
    try:
        os.rename(q, j)                                         # the claim's own rename: the job cannot also run
    except FileNotFoundError:
        pass
    else:
        card0, why0 = job_card(j)
        log = Log(os.path.join(j, "job.jsonl"), jid, card0, why0)
        log.append("cancel_requested", by=who, how="dequeued")
        seal(j, log, "cancelled", why="cancelled while queued")
        return "dequeued"
    if os.path.isdir(r):
        try:
            fd = os.open(os.path.join(r, "STOP"), os.O_CREAT | os.O_EXCL | os.O_WRONLY | O_BINARY)
        except FileExistsError:
            return "stop-already-requested"
        except FileNotFoundError:
            pass                                                # it ended between the two looks
        else:
            os.write(fd, (json.dumps({"by": who, "t": round(time.time(), 3)}) + "\n").encode())
            os.close(fd)
            return "stop-already-requested" if stop_asked(r) else "stop-requested"
    if os.path.isdir(j):
        done = read_records(os.path.join(j, "job.jsonl"))
        raise Refusal("job-ended", f"{jid} already ended: {done[-1].get('outcome') if done else 'no record'}")
    raise Refusal("job-unknown", f"no job {jid}")


def stop_info(root: str, jid: str):
    """The STOP request on a running job: {by, t}, or None."""
    try:
        with open(os.path.join(root, "running", jid, "STOP"), "rb") as fh:
            return json.loads(fh.read().decode() or "{}")
    except FileNotFoundError:
        return None
    except ValueError:
        return {"by": "unreadable", "t": None}


# ---------------------------------------------------------------------------------------- hold and release

def card_log(root: str, card: str) -> Log:
    d = os.path.join(root, "cards", card)
    os.makedirs(d, exist_ok=True)
    return Log(os.path.join(d, "card.jsonl"), None, card)


def _known(cfg: dict, card: str) -> None:
    if card not in [c["id"] for c in cfg["cards"]]:
        raise Refusal("card-unknown", f"card {card!r} is not in config.json ({', '.join(c['id'] for c in cfg['cards'])})")


def hold_info(root: str, card: str):
    try:
        with open(os.path.join(root, "cards", card, "HOLD"), "rb") as fh:
            return json.loads(fh.read().decode() or "{}")
    except FileNotFoundError:
        return None
    except ValueError:
        return {"by": "unreadable", "t": None, "why": ""}


def hold(root: str, cfg: dict, card: str, who: str, why: str) -> None:
    """Stop new claims on the card; what runs is not touched."""
    _known(cfg, card)
    log = card_log(root, card)
    try:
        fd = os.open(os.path.join(root, "cards", card, "HOLD"), os.O_CREAT | os.O_EXCL | os.O_WRONLY | O_BINARY)
    except FileExistsError:
        h = hold_info(root, card) or {}
        raise Refusal("card-held", f"{card} is already held by {h.get('by')} since {h.get('t')}: {h.get('why')}")
    os.write(fd, (json.dumps({"by": who, "t": round(time.time(), 3), "why": why}) + "\n").encode())
    os.close(fd)
    log.append("hold", by=who, why=why)


def release(root: str, cfg: dict, card: str, who: str) -> None:
    _known(cfg, card)
    try:
        os.unlink(os.path.join(root, "cards", card, "HOLD"))
    except FileNotFoundError:
        raise Refusal("card-not-held", f"{card} has no hold")
    card_log(root, card).append("release", by=who)


# ---------------------------------------------------------------------------------------- a restart

def recover(root: str, out=print) -> list:
    """Called by a service that holds the root's lock, so a job still in running/ has no service: its end record is
    `interrupted` and it is never re-run (adoption and the rest of recovery are parcel S3's). A job whose end record
    was already written only had its move left."""
    done = []
    rd = os.path.join(root, "running")
    for jid in sorted((n for n in os.listdir(rd) if ID_RE.match(n)), key=id_key):
        d = os.path.join(rd, jid)
        recs = read_records(os.path.join(d, "job.jsonl"))
        if recs and recs[-1].get("type") == "ended":
            write_sums(d)
            outcome = recs[-1].get("outcome")
        else:
            card = next((r.get("card") for r in recs if r.get("type") == "claimed"), None)
            card, why = (card, None) if card else job_card(d)
            Log(os.path.join(d, "job.jsonl"), jid, card, why).end(
                "interrupted", why="found in running/ at a service start: the service that ran it is gone; recorded, not re-run")
            write_sums(d)
            outcome = "interrupted"
        os.rename(d, os.path.join(root, "jobs", jid))
        out(f"recovered {jid}: {outcome}")
        done.append((jid, outcome))
    return done


def note_refusal(root: str, r: Refusal, verb: str, card: str | None = None) -> None:
    """A refusal that has no job leaves a line in <root>/refusals.jsonl (only those the table files under `root`)."""
    if "root" in REFUSALS[r.name][1] and os.path.isdir(root):
        Log(os.path.join(root, "refusals.jsonl"), None, card).append("refused", name=r.name, why=r.why, verb=verb, by=user())
