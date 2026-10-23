# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""The step registry (parcel S2): what a staged job can run, how each step's command is made, and how its output is judged.

A step type is an ENTRY: its fields, its command template, whether it touches the card, whether it needs a built clone or must
not have one, its stand-in leg, and its parser. The twelve battery legs are hw/card_stress.py's (`Driver.leg_cmd`): the
templates here are the driver's, re-stated, and hw/test_sched.py holds each equal to `leg_cmd`'s argv for the same options
(quick or not, on each image, dry or not). A soak slice is one job of the sweep. `vectors`, `drytests` and `driver-quick` are the
lead's box_nightly.sh preamble as steps.

THE VERDICT. Every parser is the driver's (hw/card_stress_lib.py `parse_*`, imported), except the two small ones below:
`parse_drytests` (the suite's `card-stress test: N checks, F failed` line, and the failures a spec allows by name in two lists kept
apart: `known_flakes`, as box_nightly.sh allows two, and `noted_failures`, failures that are recorded and do not stop a night) and
`parse_driver_quick` (the driver's own end line). A tool whose output moved is a `parse_error`,
never a pass; a log with nothing in it is `no-verdict`; a timeout is a `timeout`. The one step with no parser is `vectors`
(`make vectors`, then `sha256sum -c`): its verdict IS the exit status, and it is labelled `verdict_kind: rc_only` in its leg, in
the job's end record (`rc_only_steps`) and in `status JOB`. The exit status is never ignored: a parser holds it to the log's
verdict (the driver's parsers, and these two, each with an `_rc_agrees`), and a step with no parser is judged by it alone.

A random soak slice's printed case count is NOT held to the count requested here: the real tools do not print the count itself
for every mode (4 x count for cvtfrom32/64, count + 8 for nextup64/nextdown64, scaleB rounded up by whole batches, cvtto32/64
draw-dependent), and parcel P5 (KL-23) puts the hold, per mode, in the driver, to be imported once it has merged. An exhaustive
slice is held to what the driver's own Item says (`expected_cases`, `cover_spec`).
"""
from __future__ import annotations

import functools
import os
import re

from sched_driver import CS, L, parser_problem, standin
from sched_spec import option_args

M = re.MULTILINE
DRY_TOTAL = re.compile(r"^card-stress test: (\d+) checks, (\d+) failed, (\d+) skipped, (\d+) s$", M)
DRY_FAIL = re.compile(r"^  FAIL  (.*)$", M)
DRIVER_END = re.compile(r"^card-stress ends: (\w+) \(exit (\d+)\); the card is left idle \(no process of this run is alive\)$", M)
DRIVER_BAD = re.compile(r"^quick: not every leg passed: (.*)$", M)
VERDICT_ERROR = L.VerdictError


def _one(rx, text: str, what: str):
    """The one line that matches, or a VerdictError: zero or two are both wrong (the driver's own rule, hw/card_stress_lib.py _one,
    re-stated so that a rename of a private helper there cannot break these two parsers)."""
    hits = list(rx.finditer(text))
    if len(hits) != 1:
        raise VERDICT_ERROR(f"{what}: expected exactly one line matching {rx.pattern!r}, found {len(hits)}")
    return hits[0]


def _rc_agrees(rc, ok: bool, what: str) -> None:
    """The exit status must say what the log says (the driver's _rc_agrees, re-stated for the same reason)."""
    if rc is None:
        raise VERDICT_ERROR(f"{what}: no exit status")
    if ok and rc != 0:
        raise VERDICT_ERROR(f"{what}: the log says it passed and the exit status is {rc}")
    if not ok and rc == 0:
        raise VERDICT_ERROR(f"{what}: the log says it failed and the exit status is 0")


def parse_drytests(text: str, rc, known_flakes=(), noted_failures=()) -> "L.Verdict":
    """hw/test_card_stress.py main prints `  FAIL  name  detail` for each failed check and ends `card-stress test: N checks, F failed,
    S skipped, T s`. Passes with F 0; with F above 0 passes only if EVERY failure's name begins with a string the spec allows, in one of
    two lists kept apart: `known_flakes` (the load flakes box_nightly.sh tolerates: `telemetry hang: `, `stopfile: `) and `noted_failures`
    (failures of tests that do not test what the card runs, which by Logan's answer 6 must not stop a night: the lead names their
    prefixes in the spec; parcel S3a). Each class has its own count (`known_flakes`, `noted_failures`) and its own note, naming the lines.
    A failure whose name begins with neither is a fail, as it was."""
    m = _one(DRY_TOTAL, text, "drytests totals")
    checks, failed, skipped = int(m.group(1)), int(m.group(2)), int(m.group(3))
    fails = [x.group(1) for x in DRY_FAIL.finditer(text)]
    if checks == 0:
        raise VERDICT_ERROR("drytests: 0 checks")
    if len(fails) != failed:
        raise VERDICT_ERROR(f"drytests: the totals line says {failed} failed and the log holds {len(fails)} `  FAIL  ` lines")
    counts = {"checks": checks, "failed": failed, "skipped": skipped}
    if failed == 0:
        _rc_agrees(rc, True, "drytests")
        return L.Verdict(True, counts)
    _rc_agrees(rc, False, "drytests")
    flakes = [f for f in fails if any(f.startswith(k) for k in known_flakes)]
    noted = [f for f in fails if f not in flakes and any(f.startswith(k) for k in noted_failures)]
    if len(flakes) + len(noted) == failed:
        notes = []
        if flakes:
            counts["known_flakes"] = len(flakes)
            notes.append(f"{len(flakes)} failed check(s), all known flakes the spec allows by name: " + "; ".join(f[:60] for f in flakes))
        if noted:
            counts["noted_failures"] = len(noted)
            notes.append(f"{len(noted)} failed check(s) NOTED, not stopping the night (the spec's noted_failures): " + "; ".join(f[:60] for f in noted))
        return L.Verdict(True, counts, notes)
    return L.Verdict(False, counts, [f"{failed - len(flakes) - len(noted)} failed check(s) not allowed by name: " + "; ".join(f[:60] for f in fails if f not in flakes and f not in noted)[:300]])


def parse_driver_quick(text: str, rc) -> "L.Verdict":
    """The driver's last line, `card-stress ends: REASON (exit N); the card is left idle ...` (hw/card_stress.py run). A --quick
    smoke passes only when it ran every image once (`quick_done`) with exit 0; any other reason is a smoke that did not complete."""
    m = _one(DRIVER_END, text, "driver end line")
    reason, code = m.group(1), int(m.group(2))
    if rc is None or code != rc:
        raise VERDICT_ERROR(f"driver: the end line says exit {code} and the exit status is {rc}")
    bad = DRIVER_BAD.search(text)
    notes = ([f"legs not passing: {bad.group(1)[:200]}"] if bad else []) + ([] if reason == "quick_done" else [f"the smoke stopped: {reason}"])
    return L.Verdict(reason == "quick_done" and code == 0, {"exit": code}, notes, {"reason": reason})


# ---------------------------------------------------------------------------------------- the entries

class Entry:
    def __init__(self, name, fields, argv, parse=None, standin_leg=None, card=True, image=False, build="needs", timeout=600,
                 tmpdir=False, finding=False, rc_only=False):
        self.name, self.fields, self.argv, self.parse, self.standin_leg = name, fields, argv, parse, standin_leg
        self.card, self.image, self.build, self.timeout, self.tmpdir, self.finding = card, image, build, timeout, tmpdir, finding
        self.rc_only = rc_only          # the label: the verdict is the exit status alone. A step with no parser and no label cannot be judged.

    def is_card(self, st) -> bool:
        return self.card(st) if callable(self.card) else self.card

    def needs_image(self, st) -> bool:
        return self.image(st) if callable(self.image) else self.image


def _join(ctx, *parts) -> str:
    return os.path.join(ctx.clone, *parts)


def _dt(flags, mode):
    return dict(argv=lambda c, st: ["bash", _join(c, "hw", "run-device-test.sh"), c.image["path"]] + flags,
                parse=lambda c, st, t, rc: L.parse_device_test(t, rc, mode))


def _dt_i(c, st, t, rc):
    v = L.parse_device_test(t, rc, "i")
    e, im = v.extra, c.image
    if e.get("image_sha256") != im["sha256"]:
        raise CS.WrongAnswer(f"device-test -i read the image as sha256 {e.get('image_sha256')}; the file hashes to {im['sha256']}")
    if e.get("tiles") != im["tiles"]:
        raise CS.WrongAnswer(f"device-test -i read {e.get('tiles')} tiles; {im['name']} has {im['tiles']}")
    if e.get("backend") != "xrt":
        raise CS.WrongAnswer(f"device-test -i opened backend {e.get('backend')!r}, not xrt")
    return v


def _rev8_missing(c, st) -> list:
    return [e for e in st["only"] if e not in CS.REV8_ROUTINE_ENTRIES
            and not all(os.path.isfile(os.path.join(c.rev8_images, e + ext)) for ext in (".cftp", ".bank"))]


def _rev8_argv(c, st):
    os.makedirs(c.rev8_images, exist_ok=True)
    argv = [c.python, _join(c, "programs", "acceptance.py"), "--set", "rev8", "--legs", "set", "--device", c.image["path"], "--target", st["target"],
            "--images", c.rev8_images, "--only", ",".join(st["only"])]
    if any(e in CS.REV8_ROUTINE_ENTRIES for e in st["only"]):
        argv += ["--lib", _join(c, "host", "libcft.so")]      # the XRT-linked library the build checked with ldd, not whatever the environment names
    return argv


@functools.lru_cache(maxsize=1)
def catalog() -> dict:
    return {it.name: it for it in L.sweep_items(L.MODES4, L.MODES4, L.MODES4)}


def _check_soak(st):
    it = catalog().get(st["item"])
    if it is None:
        return f"item {st['item']!r} is not in the sweep catalog (hw/card_stress_lib.py sweep_items)"
    if it.kind == "exhaustive":
        if "lo" not in st or "hi" not in st or "count" in st or "seed" in st:
            return f"item {it.name} is exhaustive: it takes lo and hi, and no count or seed"
        if not 0 <= st["lo"] < st["hi"] <= it.space:
            return f"needs 0 <= lo < hi <= {it.space} for item {it.name}"
    elif "count" not in st or "seed" not in st or "lo" in st or "hi" in st:
        return f"item {it.name} is random: it takes count and seed, and no lo or hi"
    if it.reach == L.HOST and "tile" in st:
        return f"item {it.name} is a host item, run on the CPU: it takes no tile"
    return None


def soak_job(c, st) -> dict:
    """The driver's own job for one slice (Item.argv, expected_cases, cover_spec), as plan_wave builds it. A RANDOM slice has no
    count hold here: see the module docstring."""
    it = catalog()[st["item"]]
    binary = _join(c, "host", "divsqrt-soak" if it.tool == "divsqrt" else "clause5-soak")
    if it.kind == "exhaustive":
        lo, hi = st["lo"], st["hi"]
        sweep = {"item": it.name, "tool": it.tool, "op": it.op, "mode": it.mode, "reach": it.reach, "lo": lo, "hi": hi}
        return dict(it=it, argv=it.argv(binary, lo=lo, hi=hi), expected=it.expected_cases(lo, hi), cover=it.cover_spec(lo, hi), sweep=sweep)
    sweep = {"item": it.name, "tool": it.tool, "op": it.op, "mode": it.mode, "reach": it.reach, "count": st["count"], "seed": st["seed"]}
    return dict(it=it, argv=it.argv(binary, count=st["count"], seed=st["seed"]), expected=None, cover=None, sweep=sweep)


def _soak_parse(c, st, t, rc):
    j = soak_job(c, st)
    host = j["it"].reach == L.HOST
    return L.parse_soak(t, rc, j["it"].op, j["it"].verdict_mode, None if host else c.image["path"], j["expected"], j["cover"], cpu=host)


def _is_card_soak(st) -> bool:
    return catalog()[st["item"]].reach != L.HOST


def _quick_argv(c, st):
    argv = ["bash", _join(c, "hw", "card-stress.sh"), "--quick", "--out", c.step_dir, "--rev8-images", c.rev8_images]
    for n, im in c.images.items():
        if n in CS.IMAGES:
            argv += ["--image", f"{n}={im['path']}", "--sha", f"{n}={im['sha256']}"]
    if st.get("sweep_items"):
        argv += ["--sweep-items", ",".join(st["sweep_items"])]
    return argv + (["--dry-run"] if c.dry else [])


T = CS.DEFAULT_TIMEOUTS
ENTRIES = {e.name: e for e in (
    Entry("api-test", {}, lambda c, st: [_join(c, "host", "api-test")], lambda c, st, t, rc: L.parse_api_test(t, rc), "api-test", card=False, timeout=T["api-test"]),
    Entry("dt-i", {}, **_dt(["-i"], "i") | {"parse": _dt_i}, standin_leg="dt-i", image=True, timeout=T["dt-i"]),
    Entry("dt-q8", {}, **_dt(["-q", "-n", "8"], "q8"), standin_leg="dt-q8", image=True, timeout=T["dt-q8"]),
    Entry("dt-full", {}, **_dt(["-n", "4096"], "full"), standin_leg="dt-full", image=True, timeout=T["dt-full"]),
    Entry("dt-r", {}, **_dt(["-r"], "r"), standin_leg="dt-r", image=True, timeout=T["dt-r"]),
    Entry("dt-b", {}, **_dt(["-b", "-n", "4096"], "b"), standin_leg="dt-b", image=True, timeout=T["dt-b"]),
    Entry("card-segrun", {}, lambda c, st: ["bash", _join(c, "hw", "card-segrun.sh"), c.image["path"]], lambda c, st, t, rc: L.parse_card_segrun(t, rc),
          "card-segrun", image=True, tmpdir=True, timeout=T["card-segrun"]),
    Entry("seq-check", {"trials": "pos"}, lambda c, st: [c.python, _join(c, "host", "tests", "seq_check.py"), "--trials", str(st.get("trials", 250)),
                                                            "--formats", "fp32", "fp64", "fp128", "fp256", "--device", c.image["path"]],
          lambda c, st, t, rc: L.parse_seq_check(t, rc, c.image["path"]), "seq-check", image=True, timeout=T["seq-check"]),
    Entry("acceptance", {"only": "strs"}, lambda c, st: [c.python, _join(c, "programs", "acceptance.py"), "--device", c.image["path"]]
          + (["--only", ",".join(st["only"])] if st.get("only") else []),
          lambda c, st, t, rc: L.parse_acceptance(t, rc, device=c.image["path"]), "acceptance", image=True, tmpdir=True, timeout=T["acceptance"]),
    Entry("acceptance-rev8", {"only": "strs!", "target": "str!"}, _rev8_argv,
          lambda c, st, t, rc: L.parse_acceptance(t, rc, device=c.image["path"], rev8=True, target=st["target"]), "acceptance-rev8", image=True,
          tmpdir=True, timeout=T["acceptance-rev8"]),
    Entry("resident", {}, lambda c, st: [_join(c, "host", "cft-resident"), c.image["path"]], lambda c, st, t, rc: L.parse_resident(t, rc), "resident",
          image=True, timeout=T["resident"]),
    Entry("selftest", {}, lambda c, st: [_join(c, "host", "cft-selftest"), _join(c, "vectors", "out"), c.image["path"]],
          lambda c, st, t, rc: L.parse_selftest(t, rc), "selftest", image=True, timeout=T["selftest"]),
    Entry("soak", {"item": "str!", "lo": "int", "hi": "int", "count": "pos", "seed": "int", "tile": "pos"}, lambda c, st: soak_job(c, st)["argv"],
          _soak_parse, "soak", card=_is_card_soak, image=_is_card_soak, timeout=1800, finding=True),
    Entry("vectors", {}, lambda c, st: ["bash", "-c", "make vectors && cd vectors && sha256sum -c --quiet SHA256SUMS"], None, None, card=False,
          build="none", timeout=1800, rc_only=True),
    Entry("drytests", {"known_flakes": "strs", "noted_failures": "strs"}, lambda c, st: ["bash", _join(c, "hw", "test-card-stress.sh"), "--no-plants"],
          lambda c, st, t, rc: parse_drytests(t, rc, st.get("known_flakes", ()), st.get("noted_failures", ())), None, card=False, build="forbids", timeout=3600),
    Entry("driver-quick", {"sweep_items": "strs"}, _quick_argv, lambda c, st, t, rc: parse_driver_quick(t, rc), None, timeout=5400),
)}
TARGETS_OF_REV8 = {v[2] for v in CS.IMAGES.values()}


class StepRegistry(dict):
    """step type -> {field: type tag}, which sched_spec.validate reads; check_step holds the rules between a step's fields and the spec."""

    def __init__(self, entries=None):
        self.entries = entries or ENTRIES
        super().__init__({n: dict(e.fields, timeout_s="pos") for n, e in self.entries.items()})

    def check_step(self, st, spec):
        e = self.entries[st["type"]]
        if st["type"] == "soak" and _check_soak(st):
            return _check_soak(st)
        if e.needs_image(st) and not spec.get("image"):
            return f"({st['type']}) needs the job's `image`, a name in config.json's registry"
        if st["type"] == "acceptance-rev8" and st["target"] not in TARGETS_OF_REV8:
            return f"target {st['target']!r} is not one of {', '.join(sorted(TARGETS_OF_REV8))}"
        return None

    def check_window(self, spec):
        """The rules of a window job's `driver` that are the driver's (parcel S3a): each sweep item is in its catalog, and its own parser accepts the options."""
        bad = [n for n in spec["driver"].get("sweep_items", []) if n not in catalog()]
        if bad:
            return f".sweep_items {bad[0]!r} is not in the sweep catalog (hw/card_stress_lib.py sweep_items)"
        why = parser_problem(option_args(spec["driver"].get("options"))) if spec["driver"].get("options") else None
        return f".options are refused by the driver's own parser: {why}" if why else None


def timeout_of(e: Entry, c, st) -> float:
    if st.get("timeout_s"):
        return float(st["timeout_s"])
    return float(e.timeout) + (CS.REV8_FIRST_COMPILE_ALLOWANCE if e.name == "acceptance-rev8" and _rev8_missing(c, st) else 0)


def judge(e: Entry, c, st, run, text: str) -> tuple:
    """(status, verdict, reason, no_verdict): the driver's `classify`, for a step. A timeout is a timeout; a step with no parser is
    judged by its exit status alone (rc_only); a log with nothing in it is no verdict; a parser that cannot read the log is a
    `parse_error` (or `no_device`, for a card step whose log says the card did not answer); a wrong answer is a `fail`."""
    if run.error:
        return "error", None, run.error, False
    if run.timed_out:
        return "timeout", None, f"no verdict within the limit; signalled {run.killed or 'TERM'}", False
    if e.rc_only:
        return ("pass" if run.rc == 0 else "fail"), L.Verdict(run.rc == 0, {}, [f"rc_only: the verdict is the exit status ({run.rc}) alone"]), "", False
    if not text.strip():
        return "parse_error", None, f"no-verdict: the step printed nothing (exit status {run.rc})", True
    try:
        v = e.parse(c, st, text, run.rc)
    except CS.WrongAnswer as ex:
        return "fail", None, str(ex), False
    except VERDICT_ERROR as ex:
        infra = L.classify_infra(text) if e.is_card(st) else None
        return ("no_device", None, f"{infra}: {ex}", False) if infra else ("parse_error", None, f"{ex} (exit status {run.rc})", False)
    return ("pass" if v.ok else "fail"), v, "", False
