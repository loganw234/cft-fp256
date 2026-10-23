# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""The job spec, version 1: written once, in SPEC_FIELDS, and the validator reads that table.

A spec is one JSON object. An unknown field is refused by name (`spec-form`), at the top and inside `code`,
`code.assert`, `when`, `driver` and `driver.options`; so is a missing one, a wrong type, a repeated key, and NaN or Infinity. A field
this build cannot honour is refused rather than carried: an unregistered step type is `step-unknown`, and the fields of the study that
parcel S3b adds (needs, build) are unknown here until it does. Parcel S2 added `code.assert` (rtl_tree, content, ancestors),
`code.allow_unpushed` and `dry_run`, and a registry may mark a step's field required (a type tag ending in `!`) and carry a
`check_step(step, spec)` for the rules between fields. Parcel S3a added the window job: `when.window` (a window of config.json: a
name it does not hold is `window-bad`, one with no occurrence left `window-closed`), `estimate_s`, `preflight` (the steps run before
the long run, from vectors, drytests and driver-quick, in that order) and `driver` (the run directory, whether to resume it, the
images, the sweep items and a closed set of options). A job of kind `window` has no `steps` and no `image`; a staged job has no
`preflight` and no `driver`; a registry may carry `check_window(spec)` for the rules that need the driver's catalog.
`owner` is not a field: the scheduler fills it from the operating-system user, in the `submitted` record.
`signature` is reserved: a spec that has one is recorded `present-unverified`, never `verified`.
"""
from __future__ import annotations

import json
import math
import os
import re
import time

import sched_calendar as CAL
from sched_names import Refusal

SPEC_VERSION = 1
KINDS = ("window", "staged")
PREEMPT = ("ok", "never")
PREFLIGHT_ORDER = ("vectors", "drytests", "driver-quick")      # the only steps a window runs before its long run, and the order they run in
DRIVER_OPTIONS = {"host_workers": ("nonneg", "--host-workers"), "sweep_chunk": ("pos", "--sweep-chunk"),
                  "telemetry_seconds": ("number", "--telemetry-seconds"), "deadline_grace": ("number", "--deadline-grace")}   # driver.options: the closed set
def option_args(options) -> list:
    """A window's `driver.options` as the driver's flags: the one place a name becomes a flag (the long run's command and the check that the driver's own parser accepts them)."""
    return [x for k, v in (options or {}).items() for x in (DRIVER_OPTIONS[k][1], str(v))]


DEFAULT_PRIORITY = {"window": 10, "staged": 50}   # a staged job outranks the sweep (Logan, question 5)
COMMIT_RE = re.compile(r"[0-9a-f]{40}\Z")
SOURCE_RE = re.compile(r"(?:bundle:(?!\.+\Z)[A-Za-z0-9._-]+|remote)\Z")
IDENT_RE = re.compile(r"[a-z0-9][a-z0-9._-]{0,31}\Z")


def _int(x):
    return None if isinstance(x, int) and not isinstance(x, bool) else "must be an integer"


def _pos(x):
    return _int(x) or (None if x >= 1 else "must be at least 1")


def _nonneg(x):
    return _int(x) or (None if x >= 0 else "must be 0 or more")


def _num(x):
    if isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x):
        return "must be a finite number"
    return None if x >= 0 else "must not be negative"


def _epoch(x):
    return _num(x) or (None if x > 0 else "must be seconds since the epoch, above 0")


def _str(x):
    return None if isinstance(x, str) and x and len(x) <= 200 else "must be a string of 1 to 200 characters"


def _name(x):
    return None if isinstance(x, str) and 1 <= len(x) <= 80 and x.isprintable() else "must be 1 to 80 printable characters"


def _ident(x):
    return None if isinstance(x, str) and IDENT_RE.match(x) else "must be 1 to 32 characters of a-z 0-9 . _ -, starting with a letter or digit"


def _priority(x):
    return _int(x) or (None if 0 <= x <= 100 else "must be 0 to 100")


def _bool(x):
    return None if isinstance(x, bool) else "must be true or false"


def _hex40(x):
    return None if isinstance(x, str) and COMMIT_RE.match(x) else "must be 40 lowercase hex digits"


def _strs(x):
    if not isinstance(x, list) or not 1 <= len(x) <= 200:
        return "must be a list of 1 to 200 strings"
    return None if all(isinstance(s, str) and 1 <= len(s) <= 200 for s in x) else "must hold only strings of 1 to 200 characters"


def _commits(x):
    """A list of commits; whether each is a FULL one is `commit-not-full`'s to say (validate), not a form error."""
    if not isinstance(x, list) or not 1 <= len(x) <= 50 or not all(isinstance(s, str) and s for s in x):
        return "must be a list of 1 to 50 commits"
    return None


def _content(x):
    """[[path, string, count], ...]: a path inside the clone, a non-empty string, and how many times it must be found."""
    if not isinstance(x, list) or not 1 <= len(x) <= 50:
        return "must be a list of 1 to 50 entries [path, string, count]"
    for i, e in enumerate(x):
        if not (isinstance(e, list) and len(e) == 3 and isinstance(e[0], str) and isinstance(e[1], str) and _int(e[2]) is None):
            return f"entry {i} must be [path, string, count] (a path, a string, a whole number)"
        if not (1 <= len(e[0]) <= 200 and 1 <= len(e[1]) <= 200 and e[2] >= 0):
            return f"entry {i}: the path and the string are 1 to 200 characters, the count 0 or more"
        parts = e[0].replace("\\", "/").split("/")
        if e[0].startswith(("/", "\\")) or ":" in e[0] or ".." in parts or "" in parts:
            return f"entry {i}: {e[0]!r} must be a path inside the clone (relative, no `..`, no drive)"
    return None


def _sig(x):
    return None if (isinstance(x, str) and x) or (isinstance(x, dict) and x) else "must be a non-empty string or object"


TYPES = {
    "int": _int, "pos": _pos, "nonneg": _nonneg, "number": _num, "epoch": _epoch, "str": _str, "name": _name, "ident": _ident,
    "priority": _priority, "sig": _sig,
    "object": lambda x: None if isinstance(x, dict) else "must be an object",
    "list": lambda x: None if isinstance(x, list) else "must be a list",
    "kind": lambda x: None if x in KINDS else f"must be one of {', '.join(KINDS)}",
    "preempt": lambda x: None if x in PREEMPT else f"must be one of {', '.join(PREEMPT)}",
    "bool": _bool, "hex40": _hex40, "strs": _strs, "commits": _commits, "content": _content,
}

# path: (type, required, default, meaning). Parents come before children; the table is the whole spec.
SPEC_FIELDS = {
    "v": ("int", True, None, "the spec's version; this build reads 1 and refuses any other as `spec-version`"),
    "kind": ("kind", True, None, "`window` (the nightly sweep: its window's preflight, then the driver's long run; sched_window.py, S3a) or `staged` (a chain of named steps; sched_staged.py, S2)"),
    "name": ("name", True, None, "what a person calls the job; the id is the scheduler's"),
    "card": ("ident", False, "any", "a card id from config.json, or `any`: the first free, unheld card; the claimed record names it"),
    "priority": ("priority", False, None, "0 to 100, higher first, then submission order; default 10 for a window, 50 for a staged job"),
    "preempt": ("preempt", False, "ok", "`ok`: a higher priority may stop this job at a safe point (S3 does it); `never`: it may not"),
    "image": ("ident", False, None, "a name in config.json's image registry; its digest, tiles and platform are checked when the job runs"),
    "dry_run": ("bool", False, False, "true: every step that has a stand-in runs against it (hw/card_stress_standin.py); the card is not touched, and no record says it was"),
    "code": ("object", True, None, "the code the job runs: a commit and where to get it"),
    "code.commit": ("str", True, None, "a full SHA, 40 lowercase hex digits, else `commit-not-full`"),
    "code.source": ("str", True, None, "`bundle:FILE` (a file name in config.json's code.bundle_dir) or `remote` (config.json's code.remote); cloned and asserted"),
    "code.allow_unpushed": ("bool", False, False, "true: a commit not shown to be on the remote may run, and the job's record says it was not"),
    "code.assert": ("object", False, None, "what the clone must show besides HEAD and a clean status (always asserted): the rtl/ tree, strings, ancestors"),
    "code.assert.rtl_tree": ("hex40", False, None, "the git tree hash of rtl/ at the commit (`git rev-parse COMMIT:rtl`), else `rtl-mismatch`"),
    "code.assert.content": ("content", False, None, "[[path, string, count], ...]: the string is found exactly `count` times in the file, else `content-missing`"),
    "code.assert.ancestors": ("commits", False, None, "full commits that must be ancestors of the job's commit, else `ancestor-missing`"),
    "when": ("object", False, None, "absent: as soon as the card is free"),
    "when.not_before": ("epoch", False, None, "seconds since the epoch: not claimed before then"),
    "when.deadline": ("epoch", False, None, "seconds since the epoch: past it at the front of the queue, the job is refused `deadline-passed`"),
    "when.window": ("ident", False, None, "a window of config.json (a start and an end in the box's zone): the job is not claimed before it is open and its end is the job's; required of kind window"),
    "estimate_s": ("pos", False, None, "seconds the job needs: held to what is left of its window when it is claimed, else `window-too-short`"),
    "steps": ("list", False, None, "staged: 1 to 200 steps (required), each an object with a `type` the registry holds and that type's own fields; a window job has none"),
    "preflight": ("list", False, None, "window: 1 to 3 steps from vectors, drytests, driver-quick, in that order, each as a staged step; absent: all three. vectors and drytests run only when the commit "
                  "differs from the last passed window's, driver-quick every night"),
    "driver": ("object", False, None, "window (required): the driver's long run, resumed, until the window's end"),
    "driver.out": ("str", False, None, "the driver's run directory (--out), an absolute path outside every git working tree, else `out-in-checkout` (required)"),
    "driver.resume": ("bool", False, True, "true: --resume, and the directory must hold a metrics.jsonl (else `resume-missing`); false: no --resume, a new run, refused `job-exists` if the directory already holds one"),
    "driver.images": ("strs", False, None, "registry names handed to the driver (--image, --sha) and held to their files; absent: the registry's quad, single and deep"),
    "driver.sweep_items": ("strs", False, None, "campaign items of the sweep catalog (--sweep-items), given to the smoke and the long run alike"),
    "driver.options": ("object", False, None, "a closed set of driver options: host_workers (--host-workers), sweep_chunk, telemetry_seconds, deadline_grace"),
    "driver.options.host_workers": ("nonneg", False, None, "--host-workers"),
    "driver.options.sweep_chunk": ("pos", False, None, "--sweep-chunk"),
    "driver.options.telemetry_seconds": ("number", False, None, "--telemetry-seconds"),
    "driver.options.deadline_grace": ("number", False, None, "--deadline-grace"),
    "signature": ("sig", False, None, "reserved, never verified here: recorded `present-unverified`"),
}


def sig_status(obj) -> str:
    """What the record says of a signature: only ever absent, present-unverified, or unreadable (no object to look in)."""
    if not isinstance(obj, dict):
        return "unreadable"
    return "present-unverified" if "signature" in obj else "absent"


def parse_text(raw: bytes):
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as e:
        raise Refusal("spec-form", f"not UTF-8: {e}")

    def pairs(items):
        d: dict = {}
        for k, v in items:
            if k in d:
                raise ValueError(f"the key {k!r} is repeated")
            d[k] = v
        return d

    def const(c):
        raise ValueError(f"{c} is not JSON")
    try:
        return json.loads(text, object_pairs_hook=pairs, parse_constant=const)
    except (ValueError, RecursionError) as e:
        raise Refusal("spec-form", f"not valid JSON: {e}")


def _holder(obj, parent: str):
    """The object at a dotted path of the spec ('' is the spec itself), or None where there is none."""
    for part in parent.split(".") if parent else []:
        obj = obj.get(part) if isinstance(obj, dict) else None
    return obj


def _children(prefix: str) -> set:
    return {p[len(prefix):] for p in SPEC_FIELDS if p.startswith(prefix) and "." not in p[len(prefix):]}


def validate(obj, cfg: dict | None = None, registry: dict | None = None) -> dict:
    """The spec, normalized (defaults filled), or a Refusal by name. `cfg` is the configuration (cards, images)
    to hold names to; `registry` maps a step type to {field: type} (S1's is the fake runner's)."""
    if not isinstance(obj, dict):
        raise Refusal("spec-form", "the spec must be a JSON object")
    if "v" not in obj:
        raise Refusal("spec-form", "field v is missing")
    if _int(obj["v"]):
        raise Refusal("spec-form", f"field v {_int(obj['v'])}")
    if obj["v"] != SPEC_VERSION:
        raise Refusal("spec-version", f"v is {obj['v']}; this build reads version {SPEC_VERSION}")
    for key in sorted(obj):
        if key not in _children(""):
            raise Refusal("spec-form", f"field {key} is unknown")
    for parent in ("code", "code.assert", "when", "driver", "driver.options"):
        if isinstance(_holder(obj, parent), dict):
            for key in sorted(_holder(obj, parent)):
                if key not in _children(parent + "."):
                    raise Refusal("spec-form", f"field {parent}.{key} is unknown")
    for path, (tag, required, _dflt, _what) in SPEC_FIELDS.items():
        parent, _, leaf = path.rpartition(".")
        holder = _holder(obj, parent)
        if not isinstance(holder, dict):
            continue                     # the parent's own row reports it
        if leaf not in holder:
            if required:
                raise Refusal("spec-form", f"field {path} is missing")
            continue
        err = TYPES[tag](holder[leaf])
        if err:
            raise Refusal("spec-form", f"field {path} {err}")
    code, when = obj["code"], obj.get("when", {})
    if not COMMIT_RE.match(code["commit"]):
        raise Refusal("commit-not-full", f"code.commit {code['commit']!r} is not 40 lowercase hex digits")
    for anc in (code.get("assert") or {}).get("ancestors", []):
        if not COMMIT_RE.match(anc):
            raise Refusal("commit-not-full", f"code.assert.ancestors {anc!r} is not 40 lowercase hex digits")
    if not SOURCE_RE.match(code["source"]):
        raise Refusal("spec-form", "field code.source must be `bundle:FILE` (a file name, no directory) or `remote`")
    if "not_before" in when and "deadline" in when and when["deadline"] <= when["not_before"]:
        raise Refusal("spec-form", "field when.deadline must be after when.not_before")
    if obj["kind"] == "window":
        if not hasattr(registry, "check_window"):
            raise Refusal("window-unsupported", "the runner this spec is checked against runs no job of kind window (S1's fake runner has no steps to give it); "
                                                "`serve` and `submit` use the window runner unless --runner fake")
        for k in ("steps", "image"):
            if k in obj:
                raise Refusal("spec-form", f"field {k} is not for a window job (its work is `preflight` and `driver`; its images are driver.images)")
        for k, found in (("when.window", "window" in when), ("driver", "driver" in obj), ("driver.out", "out" in (obj.get("driver") or {}))):
            if not found:
                raise Refusal("spec-form", f"field {k} is missing: a job of kind window needs it")
        if not os.path.isabs(obj["driver"]["out"]):
            raise Refusal("spec-form", "field driver.out must be an absolute path")
        import sched_config                                           # at call time: sched_config imports this module
        above = sched_config.checkout_of(obj["driver"]["out"])
        if above:
            raise Refusal("out-in-checkout", f"driver.out {obj['driver']['out']!r} is inside the git working tree at {above}: the driver's files there would make the tree untracked")
    else:
        for k in ("preflight", "driver"):
            if k in obj:
                raise Refusal("spec-form", f"field {k} is for a job of kind window")
        if "steps" not in obj:
            raise Refusal("spec-form", "field steps is missing")
    if "window" in when and cfg is not None:
        ws = CAL.state(cfg, when["window"], time.time())
        if ws is None:
            raise Refusal("window-bad", f"when.window {when['window']!r} is not in config.json ({', '.join(w['name'] for w in cfg['windows']['list']) or 'no windows'})")
        if ws["state"] == "closed":
            raise Refusal("window-closed", f"window {when['window']!r} has no occurrence left (the last opened {CAL.fmt(ws['opens'])})")
    card = obj.get("card", "any")
    if cfg is not None and card != "any" and card not in [c["id"] for c in cfg["cards"]]:
        raise Refusal("card-unknown", f"card {card!r} is not in config.json ({', '.join(c['id'] for c in cfg['cards'])})")
    if cfg is not None and "image" in obj and obj["image"] not in [i["name"] for i in cfg["images"]]:
        raise Refusal("image-unknown", f"image {obj['image']!r} is not in config.json's registry")
    for n in (obj.get("driver") or {}).get("images", []):
        if cfg is not None and n not in [i["name"] for i in cfg["images"]]:
            raise Refusal("image-unknown", f"driver.images {n!r} is not in config.json's registry")
    registry = registry or {}
    if "steps" in obj:
        _steps(obj["steps"], "steps", 1, 200, obj, registry)
    if "preflight" in obj:
        _steps(obj["preflight"], "preflight", 1, 3, obj, registry)
        kinds = [s["type"] for s in obj["preflight"]]
        if kinds != [t for t in PREFLIGHT_ORDER if t in kinds]:
            raise Refusal("spec-form", f"field preflight holds {', '.join(kinds)}: only {', '.join(PREFLIGHT_ORDER)}, each at most once, in that order")
    if obj["kind"] == "window":
        err = getattr(registry, "check_window", lambda spec: None)(obj)
        if err:
            raise Refusal("spec-form", f"field driver {err}")
    out = dict(obj)
    out["card"] = card
    out["preempt"] = obj.get("preempt", "ok")
    out["priority"] = obj.get("priority", DEFAULT_PRIORITY[obj["kind"]])
    if obj["kind"] == "window":
        out["driver"] = dict(obj["driver"], resume=obj["driver"].get("resume", True))
    return out


def _steps(steps: list, label: str, lo: int, hi: int, obj: dict, registry) -> None:
    """The steps of `steps` or `preflight`: each an object with a `type` the registry holds and that type's own fields, typed."""
    if not lo <= len(steps) <= hi:
        raise Refusal("spec-form", f"field {label} must hold {lo} to {hi} steps")
    for i, st in enumerate(steps):
        p = f"{label}[{i}]"
        if not isinstance(st, dict):
            raise Refusal("spec-form", f"field {p} must be an object")
        if "type" not in st:
            raise Refusal("spec-form", f"field {p}.type is missing")
        if not isinstance(st["type"], str):
            raise Refusal("spec-form", f"field {p}.type must be a string")
        params = registry.get(st["type"])
        if params is None:
            raise Refusal("step-unknown", f"{p}.type {st['type']!r}: the registry holds {', '.join(sorted(registry)) or 'nothing'}")
        for k, v in st.items():
            if k == "type":
                continue
            if k not in params:
                raise Refusal("spec-form", f"field {p}.{k} is unknown for step type {st['type']!r}")
            bad = TYPES[params[k].rstrip("!")](v)
            if bad:
                raise Refusal("spec-form", f"field {p}.{k} {bad}")
        for k, tag in (params or {}).items():
            if tag.endswith("!") and k not in st:
                raise Refusal("spec-form", f"field {p}.{k} is missing for step type {st['type']!r}")
        err = getattr(registry, "check_step", lambda step, spec: None)(st, obj)
        if err:
            raise Refusal("spec-form", f"field {p} {err}")
