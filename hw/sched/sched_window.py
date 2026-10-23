# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""The window runner (parcel S3a): the lead's nightly launcher, box_nightly2.sh, as a job of kind `window`.

At its window's start (sched_state.claim_next holds the job in the queue until the calendar says the window is open, and the service
holds the card's lock for the job's whole run) a window job does what the launcher did, in the launcher's order, and records each part:
the window and its refusals (`window-closed`, `window-too-short`; the launcher's `stop-file-present` and `resume-missing`), the
images held to their files, the commit cloned and asserted, THE PREFLIGHT, then the driver's long run, resumed, `--until` the
window's end, and the job's outcome read from the driver's `run_end`.

THE PREFLIGHT (Logan, answer 7): `vectors` and `drytests` run only when the commit differs from the last passed window's, `driver-quick`
(the smoke, the card's health check) every night. A window has PASSED when its job ended `done` or `done-with-findings`; a dry job's
history is the dry jobs' and a real job's the real ones', so a stand-in never stands for a card run (sched_staged's rule, applied to history).
NEVER IDLE OVERNIGHT (answer 6): when the preflight fails (a step, or the build) on a commit whose window has never passed, and a commit's
window has, the night is run on that one, the last, and says so (`fallback` record, `status`, the end record). A failure on a commit
that HAS passed, or on the fallback commit, is the night's failure, `preflight-failed`; with nothing to fall back to it is `no-fallback`.
Only the preflight triggers it: a refusal before it (the clone's assertions, an image, the guard) refuses the night as it does a staged
job. The fallback asserts HEAD, a clean status and the spec's rtl/ tree when it names one, not its strings or ancestors (those are the new
commit's), and clones from the spec's own source.

THE END. The driver is given the window's end as `--until` and ends itself there, after the leg running. If it has run on more than
`runner.window_grace_s` past the end, the scheduler creates the driver's own STOP file (never a signal, never a pattern), and removes
it, if it made it, once the driver has ended; a cancel of the job does the same at once. THE LONG RUN IS NEVER SIGNALLED (Logan, 2026-10-23, on the
study's R4, "a card process is never ended by the scheduler in the middle of a leg": "Warn only for now"): run_step is given a limit it cannot reach
(NEVER_S), so no TERM and no KILL comes from it or from anything else here. A driver still running HARD_EXTRA_S (the longest leg's timeout with a cold
revision-8 cache's allowance, plus ten minutes: about 5.2 hours) past the window's end and its grace is NAMED, once, by `Watch`: a `driver_overrun`
record, `status` while it lasts, and the end record; the job ends only when the driver does, and the card stays held under the job's lock until then or
until the lead acts. Revisit the kill when S3b adds the image reload after an unclean end (a kill could leave the tile unusable, and the next night
would idle anyway). The next night's job waits meanwhile, as it does for any job: the service runs one job at a time on a card.
The driver itself runs at nice 0, as the launcher's did (its legs are niced by it). The outcome: `done` when `run_end` is `deadline`
with exit 0 (or `stop_file` after the scheduler's own end check), `cancelled` when the night was cut short by a cancel or a STOP or
signal that is not the scheduler's, else `failed` (a `run_end` that says otherwise, none, or an exit status it contradicts). The
driver's findings are in its own records; this outcome does not count them (S4a's close-out does).
"""
from __future__ import annotations

import json
import os
import threading
import time
import traceback

import sched_calendar as CAL
import sched_guard as GD
import sched_images as IM
import sched_staged as SG
import sched_state as STATE
import sched_steps as ST
from sched_driver import CS, L, is_dry_text
from sched_names import Refusal
from sched_proc import run_step
from sched_spec import option_args

GATED = ("vectors", "drytests")                        # run only when the commit differs from the last passed window's; driver-quick runs every night
PASSED = ("done", "done-with-findings")
BUILD_REFUSALS = ("build-failed", "xrt-not-linked", "build-id-mismatch", "clone-built")        # a preflight failure of the commit, not of the spec
# run_step takes a limit in seconds and has no "none", so the long run is given NEVER_S (about 31 years), a limit it cannot reach: no timeout wrapper's TERM, no loop's KILL.
NEVER_S = 10 ** 9
HARD_EXTRA_S = max(CS.DEFAULT_TIMEOUTS.values()) + CS.REV8_FIRST_COMPILE_ALLOWANCE + 600       # past the window's end and its grace: the longest leg the driver may be in (a cold revision-8 cache adds its allowance), and its stop


def _never(c, st, text, rc):
    raise NotImplementedError("a driver-long step is judged by sched_window.WindowRunner._long, from the driver's run_end")


def _long_argv(c, st):
    """The launcher's line: card-stress.sh --resume --until UNTIL --out OUT --rev8-images DIR --sweep-items ITEMS, and the registry's images as the smoke gets them."""
    argv = ["bash", os.path.join(c.clone, "hw", "card-stress.sh")] + (["--resume"] if st["resume"] else []) + ["--until", st["until"], "--out", st["out"],
                                                                                                             "--rev8-images", c.rev8_images]
    for n, im in c.images.items():
        if n in CS.IMAGES:
            argv += ["--image", f"{n}={im['path']}", "--sha", f"{n}={im['sha256']}"]
    if st.get("sweep_items"):
        argv += ["--sweep-items", ",".join(st["sweep_items"])]
    return argv + option_args(st.get("options")) + (["--dry-run"] if c.dry else [])


LONG = ST.Entry("driver-long", {}, _long_argv, _never, None, card=True, image=False, build="needs", timeout=0)


def history(root: str, card: str, dry: bool) -> list:
    """[(job id, commit)] of the window jobs that ended passed on this card, oldest first: a dry job's history is the dry jobs', a real one's the real ones'.
    A night in which the driver started no cycle (`driver_cycles` 0 or absent in the end record) did no work and is not a passed window, whatever its outcome says."""
    jd, out = os.path.join(root, "jobs"), []
    for jid in sorted((n for n in os.listdir(jd) if STATE.ID_RE.match(n)), key=STATE.id_key):
        rs = STATE.read_records(os.path.join(jd, jid, "job.jsonl"))
        sub = next((r for r in rs if r.get("type") == "submitted"), {})
        end = rs[-1] if rs and rs[-1].get("type") == "ended" else {}
        if sub.get("kind") == "window" and end.get("outcome") in PASSED and end.get("card") == card and bool(end.get("dry_run")) == dry and end.get("commit") and end.get("driver_cycles"):
            out.append((jid, end["commit"]))
    return out


def metrics(out: str) -> tuple:
    """(records of the driver's metrics.jsonl, how many are run_start, how many run_end): a torn last line is no record."""
    rs = STATE.read_records(os.path.join(out, "metrics.jsonl"))
    return rs, sum(r.get("type") == "run_start" for r in rs), sum(r.get("type") == "run_end" for r in rs)


class Watch:
    """While the driver runs: asks it to stop through ITS stop file (never a signal, never a pattern) when the job is cancelled, or when it has run
    on past the window's end by more than the grace. The file is the scheduler's own, removed after the driver has ended; one that was
    there already is a person's, and is left alone."""

    def __init__(self, out, stop, log, closes, grace, poll, overrun_at=None):
        self.path, self.stop, self.log, self.closes, self.grace, self.poll = os.path.join(out, "STOP"), stop, log, closes, grace, poll
        self.sent = self.made = self.pid = self.th = self.overrun = self.cancel_late = None
        self.overrun_at = overrun_at                   # an epoch: the driver still running then is an overrun, named once and never signalled
        self.done = threading.Event()

    def start(self, pid):
        self.pid = pid
        self.th = threading.Thread(target=self._loop, daemon=True)
        self.th.start()

    def _alive(self) -> bool:
        """Is the driver's process (the leader of its group) still there? POSIX only: on Windows os.kill(pid, 0) would END the process."""
        if os.name != "posix":
            return True
        try:
            os.kill(self.pid, 0)
        except ProcessLookupError:
            return False
        except OSError:
            pass
        return True

    def _loop(self):
        while not self.done.wait(self.poll):
            if self.sent is None and self._alive():
                why = "cancel" if self.stop.requested() else "window" if time.time() >= self.closes + self.grace else None
                if why:
                    self._ask(why)
            elif self.sent == "window" and self.cancel_late is None and self.stop.requested():
                self._note_late_cancel()                   # a cancel after the scheduler's own stop: the state an overrun creates
            if self.overrun is None and self.overrun_at is not None and time.time() >= self.overrun_at and self._alive():
                self._note_overrun()

    def _ask(self, why):
        self.sent = why
        text = {"cancel": "the job was cancelled", "window": f"the driver ran on {time.time() - self.closes:.0f} s past the window's end (grace {self.grace:.0f} s)"}[why]
        try:
            fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | STATE.O_BINARY)
        except FileExistsError:
            self.log.append("scheduler_stop", why=why, detail=text, file=self.path, made=False, note="a STOP file was already there (a person's): the driver is stopping, and it is left")
            return
        os.write(fd, (json.dumps({"by": "cft-sched", "job": self.log.job, "why": why, "t": round(time.time(), 3)}) + "\n").encode())
        os.close(fd)
        self.made = True
        self.log.append("scheduler_stop", why=why, detail=text, file=self.path, made=True)

    def _note_late_cancel(self):
        self.cancel_late = {"pid": self.pid, "t": round(time.time(), 3), "after": self.sent,
                            "note": "a cancel arrived after the scheduler had asked the driver to stop; nothing more is sent (no signal: Logan, 2026-10-23): the job ends cancelled when the driver does"}
        self.log.append("cancel_after_stop", **self.cancel_late)

    def _note_overrun(self):
        self.overrun = {"past_end_s": round(time.time() - self.closes), "pid": self.pid, "stop_asked": self.sent, "t": round(time.time(), 3),
                        "after_end_and_grace_s": round(self.overrun_at - self.closes - self.grace),
                        "note": "the scheduler sends the driver no signal (Logan, 2026-10-23: warn only for now); the card stays held under this job's lock until the driver ends or the lead acts"}
        self.log.append("driver_overrun", **self.overrun)

    def finish(self):
        self.done.set()
        if self.th:
            self.th.join()
        if self.made:
            try:
                os.unlink(self.path)
                self.log.append("scheduler_stop_removed", file=self.path)
            except FileNotFoundError:
                pass


class WindowRunner(SG.StagedRunner):
    """The staged runner, and the window job besides: a spec of kind `window` is run here, any other is the staged runner's own."""
    name = "staged"

    def __init__(self, root: str, cfg: dict, entries=None):
        super().__init__(root, cfg, {**(entries or ST.ENTRIES), "driver-long": LONG})
        self.registry = ST.StepRegistry(entries)             # what a spec is validated against: a staged job cannot name driver-long

    def run(self, spec: dict, log, stop) -> tuple:
        if spec["kind"] != "window":
            return super().run(spec, log, stop)
        S, F, dry = SG._State(0), {}, bool(spec.get("dry_run"))
        try:
            self._window(spec, log, stop, S, F, dry)
        except Refusal as r:
            log.append("refused", name=r.name, why=r.why)
            S.refusal = r.name
        except GD.Stopped:
            S.stopped = True
        except Exception as e:                                # a defect here, or a tool's surprise, ends THIS job, recorded: never the service
            log.append("runner_error", error=f"{type(e).__name__}: {e}", traceback=traceback.format_exc()[-1500:])
            S.failed = True
        outcome = "refused" if S.refusal and not S.ran else "failed" if S.failed or S.refusal else "cancelled" if S.stopped else "done"
        fields = {"findings": 0, "steps_ran": S.ran, "steps_total": S.next, "card_touched": S.card_touched, "dry_run": dry, "rc_only_steps": S.rc_only,
                  "commit": spec["code"]["commit"], "requested_commit": spec["code"]["commit"], **F}
        if S.refusal:
            fields["refusal"] = S.refusal
        noted = sum((r.get("counts") or {}).get("noted_failures", 0) for r in STATE.read_records(log.path) if r.get("type") == "leg")
        if noted:
            fields["noted_failures"] = noted                      # failures the spec names as noted, which did not stop the night (the legs' notes name them)
        return outcome, fields

    # ------------------------------------------------------------------------------------ the night
    def _window(self, spec, log, stop, S, F, dry):
        cfg, d = self.cfg, spec["driver"]
        card, want = self._card(log), spec["code"]["commit"]
        now = time.time()
        ws = CAL.state(cfg, spec["when"]["window"], now)
        if ws is None:
            raise Refusal("window-bad", f"window {spec['when']['window']!r} is not in the configuration this runner holds (the job was claimed against one that had it)")
        if ws["state"] != "open":
            raise Refusal("window-closed", f"window {ws['name']!r} is not open when the job starts ({ws['state']})")
        if spec.get("estimate_s", 0) > ws["closes"] - now:
            raise Refusal("window-too-short", f"estimate_s {spec['estimate_s']} exceeds the {ws['closes'] - now:.0f} s the window has left")
        log.append("window", name=ws["name"], zone=ws["zone"], opens=ws["opens"], closes=ws["closes"], length_s=ws["length_s"], opens_at=CAL.fmt(ws["opens"]),
                   closes_at=CAL.fmt(ws["closes"]))
        F.update(window=ws["name"], window_closes=ws["closes"])
        self._out_ok(d)
        names = d.get("images") or [i["name"] for i in cfg["images"] if i["name"] in CS.IMAGES]
        for n in names:
            entry = next((i for i in cfg["images"] if i["name"] == n), None)
            if entry is None:
                raise Refusal("image-unknown", f"driver.images {n!r} is not in the registry this runner holds")
            log.append("image", **IM.check_image(entry, card))
        hist = history(self.root, log.card, dry)
        last = hist[-1] if hist else None
        ctx, nxt, built, problem = self._attempt(spec, log, stop, S, card, spec["code"], want != (last or (None, None))[1], last, 0, names)
        F["commit"] = want
        if problem:
            if want in [c for _, c in hist]:
                raise Refusal("preflight-failed", f"commit {want[:12]} has had a passed window before, so this is the night's failure and the night does not fall back: {problem}")
            if last is None:
                raise Refusal("no-fallback", f"commit {want[:12]} failed its preflight ({problem}) and no window has passed on this card yet: nothing can run tonight")
            code = {"commit": last[1], "source": spec["code"]["source"], "allow_unpushed": spec["code"].get("allow_unpushed", False)}
            if (spec["code"].get("assert") or {}).get("rtl_tree"):
                code["assert"] = {"rtl_tree": spec["code"]["assert"]["rtl_tree"]}
            log.append("fallback", from_commit=want, to_commit=last[1], last_passed_job=last[0], reason=problem)
            F["fallback"] = {"from": want, "to": last[1], "reason": problem[:300]}
            S.failed, S.skip = False, None
            try:
                ctx, nxt, built, problem = self._attempt(spec, log, stop, S, card, code, False, last, nxt, names)
            except Refusal as r:
                raise Refusal("no-fallback", f"the last passed commit {last[1][:12]} cannot be run ({r.name}: {r.why}); the new commit {want[:12]} failed its preflight ({F['fallback']['reason']})")
            if problem:
                raise Refusal("preflight-failed", f"the fallback commit {last[1][:12]} failed its preflight too: {problem}")
            F["commit"] = last[1]
        self._long(spec, log, stop, S, F, ctx, nxt, ws, card)

    def _out_ok(self, d):
        """The launcher's refusals about the driver's directory: a STOP file in it, no metrics.jsonl to resume, and (the launcher's "outputs exist") a metrics.jsonl
        where a new run is to start, which would be written over (`job-exists`)."""
        if os.path.exists(os.path.join(d["out"], "STOP")):
            raise Refusal("stop-file-present", f"{os.path.join(d['out'], 'STOP')} exists: remove it to start (the driver would end after its first leg, or refuse)")
        have = os.path.isfile(os.path.join(d["out"], "metrics.jsonl"))
        if d["resume"] and not have:
            raise Refusal("resume-missing", f"{d['out']} has no metrics.jsonl to resume (`driver.resume: false` starts a new run)")
        if not d["resume"] and have:
            raise Refusal("job-exists", f"{os.path.join(d['out'], 'metrics.jsonl')} exists and driver.resume is false: a new run would be written over the record of an earlier one (resume it, or name a new driver.out)")

    def _attempt(self, spec, log, stop, S, card, code, changed, last, first, wanted):
        """Clone and assert `code`, run its preflight and its build. Returns (ctx, the next step's number, the build record, the first thing that failed as text or None).
        A refusal of the clone's assertions, the images or the guard is raised (the night is refused); a failed step or a refused build is a problem."""
        d, sp = spec["driver"], dict(spec, code=code)
        steps = [dict(s) for s in spec.get("preflight") or [{"type": t} for t in ("vectors", "drytests", "driver-quick")]]
        for s in steps:
            if s["type"] == "driver-quick" and "sweep_items" not in s and d.get("sweep_items"):
                s["sweep_items"] = d["sweep_items"]                      # the smoke over the night's items
        gated = [s for s in steps if s["type"] in GATED and not changed]
        todo = [s for s in steps if s not in gated]
        log.append("preflight", commit=code["commit"], last_passed=last and last[1], last_passed_job=last and last[0], changed=changed, runs=[s["type"] for s in todo],
                   skips=[s["type"] for s in gated])
        ctx = self._open(sp, log, S, bool(spec.get("dry_run")), card, todo + [{"type": "driver-long"}])
        ctx.images = {n: v for n, v in ctx.images.items() if n in wanted}
        why = f"the commit is the last passed window's ({code['commit'][:12]}, job {last and last[0]}): vectors and the dry tests run only when it differs (answer 7)"
        for k, s in enumerate(gated):
            self._leg_skipped(log, S, ctx, first + k, s, self.entries[s["type"]], why)
        i, problem, built = first + len(gated), None, None
        blog = "build.log" if first == 0 else f"build-{first:02d}.log"            # a file the job makes: the fallback's build must not write over the first
        try:
            built = self._chain(sp, log, stop, S, ctx, todo, card, i, None, blog)
            if built is None and not S.failed and not S.skip:
                built = self._build(log, sp, ctx.clone, os.path.dirname(log.path), ctx.dry, self.cfg["runner"], card["kind"], blog)
        except Refusal as r:
            if r.name not in BUILD_REFUSALS:
                raise
            problem = f"{r.name}: {r.why}"
            log.append("preflight_refused", name=r.name, why=r.why)
            for k in range(S.next - i, len(todo)):                       # what the refusal cut off is recorded, as a failed step's rest is
                self._leg_skipped(log, S, ctx, i + k, todo[k], self.entries[todo[k]["type"]], f"{r.name}: the preflight was ended by that refusal")
        if problem is None and S.failed:
            bad = [r for r in STATE.read_records(log.path) if r.get("type") == "leg" and r["step"] >= first and r["status"] not in ("pass", "skipped")]
            problem = f"{bad[0]['leg']} {bad[0]['status']}: {bad[0]['reason'] or 'exit status ' + str(bad[0]['rc']) + ', log ' + str(bad[0]['log'])}"[:300] if bad else "a preflight step failed"
        return ctx, first + len(gated) + len(todo), built, problem

    def _long(self, spec, log, stop, S, F, ctx, i, ws, card):
        """The driver's long run, resumed, until the window's end: started, watched (cancel, the grace), and its end read from run_end."""
        d, rcfg, e = spec["driver"], self.cfg["runner"], self.entries["driver-long"]
        if S.stopped or stop.requested():
            S.stopped = True
            return self._leg_skipped(log, S, ctx, i, {"type": "driver-long"}, e, "a stop was requested")
        if time.time() >= ws["closes"]:
            raise Refusal("window-closed", f"the window closed at {CAL.fmt(ws['closes'])}, during the preflight")
        self._out_ok(d)
        t0 = time.time()
        if not ctx.dry:
            GD.hold_until_clear(log, card["kind"], rcfg["guard_wait_max_s"], rcfg["guard_poll_s"], stop=stop.requested)
            if time.time() >= ws["closes"]:
                raise Refusal("window-closed", f"the window closed at {CAL.fmt(ws['closes'])}, while the job waited {time.time() - t0:.0f} s for the card")
        st = {"type": "driver-long", "out": d["out"], "resume": d["resume"], "until": CAL.fmt(ws["closes"]), "sweep_items": d.get("sweep_items"), "options": d.get("options")}
        _, n_start, n_end = metrics(d["out"])
        argv, logpath = e.argv(ctx, st), os.path.join(os.path.dirname(log.path), f"{i:02d}-driver-long.log")
        watch = Watch(d["out"], stop, log, ws["closes"], rcfg["window_grace_s"], rcfg["window_poll_s"], ws["closes"] + rcfg["window_grace_s"] + HARD_EXTRA_S)

        def started(pid):
            log.append("driver_started", pid=pid, out=d["out"], until=st["until"], resume=d["resume"])
            watch.start(pid)
        try:
            run = run_step(argv, ctx.clone, {}, logpath, NEVER_S, rcfg["kill_after_s"], 0, on_start=started)
        finally:
            watch.finish()
        try:
            with open(logpath, encoding="utf-8", errors="replace") as fh:
                text = fh.read()
        except OSError:
            text = ""
        recs, s1, e1 = metrics(d["out"])
        end = [r for r in recs if r.get("type") == "run_end"][-1] if s1 > n_start and e1 > n_end else None
        reason, code = (end.get("reason"), end.get("exit")) if end else (None, None)
        if run.error:
            status, why = "error", run.error
        elif run.timed_out:                                        # run_step's flag for a process ended by a TERM or KILL (exit status 124 or 137): not the scheduler's, which sends the long run none
            status, why = "fail", f"the driver was ended from outside by a signal (exit status {run.rc}); the scheduler sends the long run none"
        elif end is None:
            status, why = "fail", f"the driver wrote {'a run_start but' if s1 > n_start else 'no run_start and'} no run_end (exit status {run.rc}): no_run_end, never a pass"
        elif code != run.rc:
            status, why = "parse_error", f"run_end says exit {code} and the exit status is {run.rc}"
        elif is_dry_text(text) and not ctx.dry:
            status, why = "error", "dry-run-as-card: this log is a driver's dry run's and the job is not a dry run"
        elif code == 0 and reason == "deadline":
            status, why = "pass", ""
        elif code == 0 and reason in ("stop_file", "signal"):
            status, why = "pass", f"the driver stopped at {reason}: " + ("the scheduler's end check, past the grace" if watch.sent == "window" else "a cancel" if watch.sent == "cancel" else "not the scheduler's")
            S.stopped = S.stopped or watch.sent != "window"                  # a cancel, or a person's STOP or signal: the night was cut short
        else:
            status, why = "fail", f"the driver stopped: {reason} (exit {code})"
        if watch.cancel_late:
            S.stopped = True                                       # a cancel that came after the scheduler's own stop: the job ends cancelled, when the driver does
        starts = [k for k, r in enumerate(recs) if r.get("type") == "run_start"]
        cycles = sum(r.get("type") == "cycle_start" for r in recs[starts[-1]:]) if s1 > n_start else 0         # this night's work: its cycle_start records (run_end's `cycles` counts the file's)
        if status == "pass" and not S.stopped and not cycles:
            status, why = "fail", f"the driver ended {reason} (exit {code}) having started no cycle this night: no driver work was done, so this is not a passed window"
        rec = dict(self._base(S, ctx, i, st, e, run.start), kind="window", status=status, reason=why or None, rc=run.rc, end=L.iso(run.end), end_epoch=round(run.end, 3),
                   duration_s=round(max(0.0, run.end - run.start), 3), timed_out=bool(run.timed_out), killed=run.killed, counts={"cycles": end.get("cycles"), "cycles_this_night": cycles} if end else None,
                   log=os.path.basename(logpath), log_kept="whole", card_touched=bool(not ctx.dry and run.pid is not None), argv=run.argv[:12] if status != "pass" else None,
                   extra={"out": d["out"], "until": st["until"], "run_end": end, "scheduler_stop": watch.sent, "overrun": watch.overrun, "cancel_after_stop": watch.cancel_late})
        log.append("leg", **rec)
        S.next, S.ran, S.card_touched = i + 1, S.ran + 1, S.card_touched or rec["card_touched"]
        F.update(driver_reason=reason, driver_exit=code, driver_cycles=cycles)
        if watch.overrun:
            F["overrun"] = watch.overrun                              # the end record carries it
        if watch.cancel_late:
            F["cancel_after_stop"] = watch.cancel_late
        if status != "pass":
            S.failed = True
        if status == "error" and why.startswith("dry-run-as-card"):
            raise Refusal("dry-run-as-card", why)


# ---------------------------------------------------------------------------------------- what `status` shows

def window_info(root: str, where: str, jid: str, cfg: dict | None = None) -> dict:
    """What `status` shows of a window job: its window (the record of the night, or the calendar's answer for a job still in the queue), what it ran and why,
    the preflight's legs and the driver's end."""
    rs = STATE.read_records(os.path.join(root, where, jid, "job.jsonl"))
    w = next((r for r in rs if r.get("type") == "window"), None)
    if w is None and cfg is not None and where == "queue":
        try:
            with open(os.path.join(root, where, jid, "spec.json"), "rb") as fh:
                name = (json.loads(fh.read().decode()).get("when") or {}).get("window")
            ws = CAL.state(cfg, name, time.time()) if name else None
        except (OSError, ValueError):
            ws = None
        w = ws and {"name": ws["name"], "state": ws["state"], "opens_at": CAL.fmt(ws["opens"]), "closes_at": CAL.fmt(ws["closes"]), "length_s": ws["length_s"]}
    end = rs[-1] if rs and rs[-1].get("type") == "ended" else {}
    code = [r for r in rs if r.get("type") == "preflight"]
    return {"window": w, "commit": end.get("commit") or (code[-1].get("commit") if code else None), "requested_commit": end.get("requested_commit"),
            "fallback": next((r for r in rs if r.get("type") == "fallback"), None),
            "preflight": [{k: r.get(k) for k in ("step", "leg", "status", "reason", "counts", "notes")} for r in rs if r.get("type") == "leg" and r.get("kind") != "window"],
            "driver": next(({"reason": r["extra"].get("run_end", {}) and r["extra"]["run_end"].get("reason"), "status": r["status"], "scheduler_stop": r["extra"].get("scheduler_stop")}
                            for r in rs if r.get("type") == "leg" and r.get("kind") == "window"), None),
            "overrun": next((r for r in rs if r.get("type") == "driver_overrun"), None), "cancel_late": next((r for r in rs if r.get("type") == "cancel_after_stop"), None), "ended": bool(end)}


def format_window(info: dict) -> list:
    w, lines = info["window"], []
    if w:
        lines.append(f"  window: {w['name']}, {w.get('state', 'opened')}: {w['opens_at']} to {w['closes_at']} ({w['length_s'] / 3600:.2f} h)")
    if info["commit"]:
        lines.append(f"  runs: commit {info['commit']}" + (f", FELL BACK from {info['fallback']['from_commit']}: {info['fallback']['reason']}" if info["fallback"] else ""))
    if info["preflight"]:
        lines.append("  preflight: " + "; ".join(f"{x['leg']} {x['status']}" + (f" ({x['counts']['noted_failures']} NOTED failure(s))" if (x.get("counts") or {}).get("noted_failures") else "")
                                                for x in info["preflight"]))
        lines += [f"  noted, did not stop the night: {n}" for x in info["preflight"] for n in (x.get("notes") or []) if "NOTED" in n]
    if info["driver"]:
        lines.append(f"  driver: {info['driver']['status']}, run_end {info['driver']['reason']}" + (f" (the scheduler asked it to stop: {info['driver']['scheduler_stop']})" if info["driver"]["scheduler_stop"] else ""))
    o = info.get("overrun")
    if o:
        lines.append(f"  DRIVER OVERRUN: {'ran on' if info.get('ended') else 'still running'} {o['past_end_s']} s past the window's end (pid {o['pid']}; named {o['after_end_and_grace_s']} s after the end and the grace): "
                     "the scheduler sends it no signal, and the card stays held under this job's lock until the driver ends or the lead acts")
    c = info.get("cancel_late")
    if c:
        lines.append(f"  cancel received after the driver (pid {c['pid']}) had been asked to stop: the scheduler sends it no signal, and the job ends cancelled when the driver does")
    return lines
