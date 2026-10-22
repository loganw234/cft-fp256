# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""The staged runner (parcel S2): a job of kind `staged`, run for real, step by step. It replaces the fake runner (sched_run.py)
for staged jobs; the window job is parcel S3's and is refused here by name (`window-unsupported`).

The order, which the lead's box_nightly.sh taught: the spec's image is held to its files; a job with a card step asks the guard
(refused at once, the driver's start); the code is cloned and asserted; then the steps, in order. A step that needs the build
(`build: needs`) makes the build, once, before it; a step that forbids one (`drytests`) is refused `clone-built` if the clone
holds one; a card step asks the guard again and waits for a foreign user (to the configured limit); then the step runs
(sched_proc.run_step), is judged (sched_steps.judge) and recorded as a `leg` in the driver's leg schema, with the card's id
(the log adds it), in the job's own job.jsonl. Each step's raw output is a file of the job's directory, NN-STEP.log, whole, so the
job's SHA256SUMS covers it; a driver run's own directory (driver-quick) is a subdirectory, which S1's sums do not cover.

The outcome is S1's: `failed` when a step failed (the steps after it are recorded `skipped`), `cancelled` at a stop (looked for
before every step, never in the middle of one), `done-with-findings` when a soak slice found a mismatch (the chain goes on,
Logan's answer 13), else `done`; a refusal before any step ran is `refused`, after one `failed`, and the end record names it.
A dry job (`dry_run`) wraps every step that has a stand-in leg as the driver's Driver.standin does, builds nothing, asks no guard,
touches no card, and every leg it writes says `dry` and `standin`; a stand-in's log in a job that is not dry is `dry-run-as-card`.
"""
from __future__ import annotations

import os
import shutil
import time
import traceback

import sched_build as BD
import sched_code as CODE
import sched_guard as GD
import sched_images as IM
import sched_steps as ST
from sched_driver import CS, L, is_dry_text, standin
from sched_names import Refusal
from sched_proc import run_step


class Ctx:
    """What a step's command template reads (sched_steps.py)."""

    def __init__(self, clone, image, images, python, rev8_images, dry):
        self.clone, self.image, self.images, self.python, self.rev8_images, self.dry = clone, image, images, python, rev8_images, dry
        self.step_dir = None


class _State:
    def __init__(self, total):
        self.total, self.next, self.ran, self.findings, self.rc_only = total, 0, 0, 0, 0
        self.failed = self.stopped = self.card_touched = False
        self.refusal = self.skip = self.ctx = None


class StagedRunner:
    name = "staged"

    def __init__(self, root: str, cfg: dict, entries=None):
        self.root, self.cfg = root, cfg
        self.registry = ST.StepRegistry(entries)
        self.entries = self.registry.entries

    # ------------------------------------------------------------------------------------ the job
    def run(self, spec: dict, log, stop) -> tuple:
        S = _State(len(spec["steps"]))
        dry = bool(spec.get("dry_run"))
        try:
            self._run(spec, log, stop, S, dry)
        except Refusal as r:
            log.append("refused", name=r.name, why=r.why)
            S.refusal = r.name
            if S.ran:                                                 # a refusal before any step is a job that never started: no legs
                self._skip_rest(spec, log, S, dry, f"{r.name}: the job was stopped by that refusal")
        except GD.Stopped:
            S.stopped = True
            self._skip_rest(spec, log, S, dry, "a stop was requested")
        except Exception as e:                                        # a defect here, or a tool's surprise, ends THIS job, recorded: never the service
            log.append("runner_error", error=f"{type(e).__name__}: {e}", traceback=traceback.format_exc()[-1500:])
            S.failed = True
            self._skip_rest(spec, log, S, dry, "the runner failed with an unexpected error (the runner_error record)")
        outcome = ("refused" if S.refusal and not S.ran else "failed" if S.failed or S.refusal else "cancelled" if S.stopped
                   else "done-with-findings" if S.findings else "done")
        fields = {"findings": S.findings, "steps_ran": S.ran, "steps_total": S.total, "card_touched": S.card_touched, "dry_run": dry,
                  "rc_only_steps": S.rc_only, "commit": spec["code"]["commit"]}
        if S.refusal:
            fields["refusal"] = S.refusal
        return outcome, fields

    def _run(self, spec, log, stop, S, dry):
        cfg = self.cfg
        rcfg = cfg["runner"]
        card = next(c for c in cfg["cards"] if c["id"] == log.card)
        if spec["kind"] != "staged":
            raise Refusal("window-unsupported", f"kind {spec['kind']!r}: the window job is parcel S3's; this runner runs staged jobs")
        steps = spec["steps"]
        for i, st in enumerate(steps):
            e = self.entries[st["type"]]
            if e.parse is None and not e.rc_only:
                raise Refusal("parser-unknown", f"steps[{i}] {st['type']!r} has neither a parser nor the rc_only label: its output could not be judged")
        jobdir = os.path.dirname(log.path)
        images = {i["name"]: dict(i, path=IM.expand(i["path"])) for i in cfg["images"]}
        image = None
        if spec.get("image"):
            image = IM.check_image(next(i for i in cfg["images"] if i["name"] == spec["image"]), card)
            log.append("image", **image)
        if not dry and any(self.entries[s["type"]].is_card(s) for s in steps):
            GD.hold_until_clear(log, card["kind"], 0, rcfg["guard_poll_s"])
        clone, facts = CODE.prepare(self.root, cfg, spec["code"], log.job)
        log.append("code", **facts)
        rev8 = IM.expand(rcfg["rev8_images"]) if rcfg["rev8_images"] else os.path.join(self.root, "rev8-images")
        ctx = S.ctx = Ctx(clone, image, images, rcfg["python"], rev8, dry)
        built = None
        for i, st in enumerate(steps):
            e = self.entries[st["type"]]
            if not S.skip and stop.requested():
                S.skip, S.stopped = "a stop was requested", True
            if S.skip:
                self._leg_skipped(log, S, ctx, i, st, e, S.skip)
                continue
            if e.build == "forbids":
                BD.check_clone_not_built(clone)
            if e.build == "needs" and built is None:
                built = self._build(log, spec, clone, jobdir, dry, rcfg, card["kind"])
            if built and st["type"] in built["disabled"]:
                self._leg_skipped(log, S, ctx, i, st, e, built["disabled"][st["type"]])
                continue
            if e.is_card(st) and not dry:
                GD.hold_until_clear(log, card["kind"], rcfg["guard_wait_max_s"], rcfg["guard_poll_s"], stop=stop.requested)
            self._step(log, S, ctx, jobdir, i, st, e, rcfg)

    def _build(self, log, spec, clone, jobdir, dry, rcfg, kind) -> dict:
        if dry:
            rec = BD.dry_record()
        else:
            done: list = []
            try:
                rec = BD.KIND_BUILDS[kind](clone, spec["code"]["commit"], rcfg, jobdir, os.path.join(jobdir, "build.log"), done)
            except Refusal:
                log.append("build", ok=False, steps=done, disabled={}, build_id=None)
                raise
        log.append("build", **rec)
        return rec

    # ------------------------------------------------------------------------------------ the legs
    def _base(self, S, ctx, i, st, e, now):
        host = st["type"] == "soak" and not e.is_card(st)
        return {"cycle": 1, "step": i, "image": L.CPU if host else (ctx.image["name"] if ctx.image else None),
                "image_sha256": None if host or not ctx.image else ctx.image["sha256"], "leg": st["type"],
                "kind": "sweep" if st["type"] == "soak" else "staged", "attempt": 1, "start": L.iso(now), "end": L.iso(now),
                "start_epoch": round(now, 3), "end_epoch": round(now, 3), "duration_s": 0.0, "rc": None, "timed_out": False, "killed": None,
                "counts": None, "rate": None, "sweep": None, "disagreements": None, "log": None, "log_kept": "none", "tile": st.get("tile"),
                "extra": None, "verdict_kind": "rc_only" if e.rc_only else "parsed", "dry": ctx.dry, "standin": False}

    def _leg_skipped(self, log, S, ctx, i, st, e, reason):
        log.append("leg", **dict(self._base(S, ctx, i, st, e, time.time()), status="skipped", reason=reason))
        S.next = i + 1

    def _skip_rest(self, spec, log, S, dry, reason):
        ctx = S.ctx or Ctx(None, None, {}, None, None, dry)                # the steps skipped by a refusal say which image they were for
        for i in range(S.next, S.total):
            st = spec["steps"][i]
            self._leg_skipped(log, S, ctx, i, st, self.entries[st["type"]], reason)

    def _step(self, log, S, ctx, jobdir, i, st, e, rcfg):
        dry = ctx.dry
        wrapped = bool(dry and e.standin_leg)
        label = st["type"] + ("-" + st["item"] if st["type"] == "soak" else "")
        logpath = os.path.join(jobdir, f"{i:02d}-{label}.log")
        ctx.step_dir = os.path.join(jobdir, f"{i:02d}-{st['type']}")
        real = e.argv(ctx, st)
        argv = standin(e.standin_leg, real) if wrapped else real
        env, drop = {}, ()
        if st["type"] == "soak":
            if e.is_card(st):
                env["CFT_SOAK_ARTIFACT"] = ctx.image["path"]
                if st.get("tile"):
                    env["CFT_XRT_TILES"] = str(st["tile"])
            else:
                drop = CS.HOST_JOB_DROPS                      # a host job must not be able to name the card
        tmp = None
        if e.tmpdir:
            tmp = env["TMPDIR"] = os.path.join(jobdir, f".tmp-{i:02d}")
            os.makedirs(tmp)
        try:
            run = run_step(argv, ctx.clone, env, logpath, ST.timeout_of(e, ctx, st), rcfg["kill_after_s"], rcfg["nice"], drop=drop)
        finally:
            if tmp:
                CODE.remove_tree(tmp)
        try:
            with open(logpath, encoding="utf-8", errors="replace") as fh:
                text = fh.read()
        except OSError:
            text = ""
        status, v, reason, no_verdict = ST.judge(e, ctx, st, run, text)
        offered = is_dry_text(text) and not dry                       # a stand-in's (or a driver's dry run's) output, in a job that says it ran the real tool
        if offered:
            status, v, reason = "error", None, "dry-run-as-card: this log is a stand-in's or a driver's dry run's and the job is not a dry run"
        dur = max(0.0, run.end - run.start)
        counts, extra = (dict(v.counts), dict(v.extra)) if v else (None, {})
        dis = extra.pop("disagreements", None)
        rate = None
        for key, unit in (("cases", "cases/s"), ("checks", "checks/s")):
            if counts and key in counts and dur > 0:
                rate = {"value": round(counts[key] / dur, 3), "unit": unit}
                break
        sweep = None
        if st["type"] == "soak":
            sweep = dict(ST.soak_job(ctx, st)["sweep"], tile=st.get("tile"), jobs=1)
            for k in ("batch", "chunk"):
                if k in extra:
                    sweep[k] = extra.pop(k)
        kd = extra.get("kept_dir")
        if kd and os.path.isdir(kd):                                # card-segrun keeps the logs of a failed gate in a directory of its own
            dest = logpath[:-4] + "-kept"
            shutil.move(kd, dest)
            extra["kept_dir"] = os.path.basename(dest)
        rec = dict(self._base(S, ctx, i, st, e, run.start), status=status, reason=reason or None, rc=run.rc, end=L.iso(run.end), end_epoch=round(run.end, 3),
                   duration_s=round(dur, 3), timed_out=bool(run.timed_out), killed=run.killed, counts=counts, rate=rate, sweep=sweep, disagreements=dis,
                   log=os.path.basename(logpath), log_kept="whole", extra=extra or None, standin=wrapped or offered,
                   card_touched=bool(e.is_card(st) and not dry and run.pid is not None), argv=run.argv[:12] if status != "pass" else None)
        if v and v.notes:
            rec["notes"] = v.notes
        log.append("leg", **rec)
        S.next, S.ran = i + 1, S.ran + 1
        S.card_touched = S.card_touched or rec["card_touched"]
        S.rc_only += bool(e.rc_only)
        if status == "fail" and e.finding:
            S.findings += 1                                           # a mismatch is a finding, and the chain goes on (answer 13)
        elif status != "pass":
            S.failed, S.skip = True, "an earlier step failed"
        if offered:
            raise Refusal("dry-run-as-card", f"step {i} ({st['type']}): its log is a stand-in's or a driver's dry run's and the job is not a dry run; it is not recorded as a card's")
        if no_verdict:
            raise Refusal("no-verdict", f"step {i} ({st['type']}) printed nothing, so no verdict can be read from it")
