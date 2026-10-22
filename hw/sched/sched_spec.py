# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""The job spec, version 1: written once, in SPEC_FIELDS, and the validator reads that table.

A spec is one JSON object. An unknown field is refused by name (`spec-form`), at the top and inside `code`,
`code.assert` and `when`; so is a missing one, a wrong type, a repeated key, and NaN or Infinity. A field this build
cannot honour is refused rather than carried: `when.window` is `window-unsupported` until parcel S3 builds
the calendar, an unregistered step type is `step-unknown`, and the fields of the study that S3 adds
(needs, estimate_s, build, preflight, driver) are unknown here until it does. Parcel S2 added `code.assert`
(rtl_tree, content, ancestors), `code.allow_unpushed` and `dry_run`, and a registry may mark a step's field
required (a type tag ending in `!`) and carry a `check_step(step, spec)` for the rules between fields.
`owner` is not a field: the scheduler fills it from the operating-system user, in the `submitted` record.
`signature` is reserved: a spec that has one is recorded `present-unverified`, never `verified`.
"""
from __future__ import annotations

import json
import math
import re

from sched_names import Refusal

SPEC_VERSION = 1
KINDS = ("window", "staged")
PREEMPT = ("ok", "never")
DEFAULT_PRIORITY = {"window": 10, "staged": 50}   # a staged job outranks the sweep (Logan, question 5)
COMMIT_RE = re.compile(r"[0-9a-f]{40}\Z")
SOURCE_RE = re.compile(r"(?:bundle:(?!\.+\Z)[A-Za-z0-9._-]+|remote)\Z")
IDENT_RE = re.compile(r"[a-z0-9][a-z0-9._-]{0,31}\Z")


def _int(x):
    return None if isinstance(x, int) and not isinstance(x, bool) else "must be an integer"


def _pos(x):
    return _int(x) or (None if x >= 1 else "must be at least 1")


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
    "int": _int, "pos": _pos, "number": _num, "epoch": _epoch, "str": _str, "name": _name, "ident": _ident,
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
    "kind": ("kind", True, None, "`window` (the nightly sweep) or `staged` (a chain of named steps); the real runners are S3 and S2"),
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
    "when.window": ("ident", False, None, "a window of config.json: refused `window-unsupported` until S3"),
    "steps": ("list", True, None, "1 to 200 steps, each an object with a `type` the registry holds and that type's own fields"),
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
    for parent in ("code", "code.assert", "when"):
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
    if "window" in when:
        raise Refusal("window-unsupported", f"when.window {when['window']!r}: this build has no window calendar (parcel S3)")
    card = obj.get("card", "any")
    if cfg is not None and card != "any" and card not in [c["id"] for c in cfg["cards"]]:
        raise Refusal("card-unknown", f"card {card!r} is not in config.json ({', '.join(c['id'] for c in cfg['cards'])})")
    if cfg is not None and "image" in obj and obj["image"] not in [i["name"] for i in cfg["images"]]:
        raise Refusal("image-unknown", f"image {obj['image']!r} is not in config.json's registry")
    registry = registry or {}
    steps = obj["steps"]
    if not 1 <= len(steps) <= 200:
        raise Refusal("spec-form", "field steps must hold 1 to 200 steps")
    for i, st in enumerate(steps):
        p = f"steps[{i}]"
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
    out = dict(obj)
    out["card"] = card
    out["preempt"] = obj.get("preempt", "ok")
    out["priority"] = obj.get("priority", DEFAULT_PRIORITY[obj["kind"]])
    return out
