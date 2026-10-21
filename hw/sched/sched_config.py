# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""The state root and its configuration (docs/studies/SCHED-A-card-scheduler.md, section 5.1).

The root lives outside every checkout, given by --root or CFT_SCHED_ROOT; one inside a git working tree is
refused `root-in-checkout`. Its layout: config.json, lock, queue/, running/, jobs/, cards/, clones/,
extracts/ (clones/ and extracts/ are S2's and S4's), and ids/ (the markers that make a job id never reused).
config.json is read at start and an invalid one is refused `config-form`, by name. Each section is merged
over DEFAULTS, so a file may state only what it changes; `cards` has no default, because inventing a card
would be a claim about the machine. The retention is Logan's, 2026-10-21, doubled from the study's numbers.
This parcel carries the retention, the floors and the windows and acts on none of them (S3 and S4 do).
"""
from __future__ import annotations

import copy
import json
import math
import os
import re

from sched_names import Refusal
from sched_spec import IDENT_RE, parse_text      # one JSON reader: a repeated key and NaN are refused the same way

ENV_ROOT = "CFT_SCHED_ROOT"
LAYOUT = ("queue", "running", "jobs", "cards", "clones", "extracts", "ids")
CARD_KINDS = {"xrt": "an Alveo card driven through XRT over PCIe (the U50)"}   # nothing else reads a card's kind
HEX64 = re.compile(r"[0-9a-f]{64}\Z")
CLOCK = re.compile(r"(?:[01]\d|2[0-3]):[0-5]\d\Z")
ZONE = re.compile(r"[A-Za-z0-9_+./-]{1,64}\Z")

DEFAULTS = {
    "cards": None,                       # required
    "images": [],                        # [{name, path, sha256}]: validated for shape only
    "windows": {"zone": "local", "list": [{"name": "nightly", "start": "18:00", "end": "08:00"}]},
    "floors": {"disk_free_gb": 5},       # the driver's own floor, unchanged
    "retention": {"idle_sample_minutes": 7.5, "clone_days": 14, "passing_log_days": 360, "record_days": None},
}                                        # record_days null: every record is kept


def resolve_root(flag: str | None, environ=os.environ) -> str:
    root = flag or environ.get(ENV_ROOT)
    if not root:
        raise Refusal("root-unset", f"give --root DIR or set {ENV_ROOT} (on the box: /data/cft-sched)")
    return os.path.abspath(os.path.expanduser(root))


def check_root(root: str, create: bool = False) -> str:
    """The root, or a refusal. The checkout test comes before anything is created."""
    real = os.path.realpath(root)
    d = real
    while True:
        if os.path.lexists(os.path.join(d, ".git")):
            raise Refusal("root-in-checkout", f"{root} is inside the git working tree at {d}")
        up = os.path.dirname(d)
        if up == d:
            break
        d = up
    if os.path.exists(real) and not os.path.isdir(real):
        raise Refusal("root-missing", f"{root} is not a directory")
    if not os.path.isdir(real):
        if not create:
            raise Refusal("root-missing", f"{root} does not exist (`init` creates a root)")
        os.makedirs(real, mode=0o700)            # private: this is how only the box user can submit (the study's 4.7)
    return real


def ensure_layout(root: str, cfg: dict) -> None:
    for sub in LAYOUT:
        os.makedirs(os.path.join(root, sub), exist_ok=True)
    for card in cfg["cards"]:
        os.makedirs(os.path.join(root, "cards", card["id"]), exist_ok=True)


def _form(path: str, why: str):
    return Refusal("config-form", f"{path} {why}")


def _keys(obj, path: str, required: tuple, optional: tuple = ()) -> None:
    if not isinstance(obj, dict):
        raise _form(path, "must be an object")
    for k in sorted(obj):
        if k not in required + optional:
            raise _form(f"{path}.{k}" if path else k, "is unknown")
    for k in required:
        if k not in obj:
            raise _form(f"{path}.{k}" if path else k, "is missing")


def _number(x, path: str, zero_ok: bool = False) -> None:
    ok = not isinstance(x, bool) and isinstance(x, (int, float)) and math.isfinite(x) and (x >= 0 if zero_ok else x > 0)
    if not ok:
        raise _form(path, "must be a finite number above 0" if not zero_ok else "must be a finite number, 0 or more")


def validate_config(raw) -> dict:
    """The effective configuration (DEFAULTS under the file's own values), or `config-form` naming what is wrong."""
    _keys(raw, "", (), tuple(DEFAULTS))
    cfg = copy.deepcopy(DEFAULTS)
    if "cards" not in raw:
        raise _form("cards", "is missing: name the cards this scheduler owns")
    cards = raw["cards"]
    if not isinstance(cards, list) or not cards:
        raise _form("cards", "must be a non-empty list")
    seen = set()
    for i, c in enumerate(cards):
        _keys(c, f"cards[{i}]", ("id", "kind"))
        if not isinstance(c["id"], str) or not IDENT_RE.match(c["id"]) or c["id"] == "any":
            raise _form(f"cards[{i}].id", "must be 1 to 32 characters of a-z 0-9 . _ -, and not `any`")
        if c["id"] in seen:
            raise _form(f"cards[{i}].id", f"{c['id']!r} repeats")
        seen.add(c["id"])
        if c["kind"] not in CARD_KINDS:
            raise _form(f"cards[{i}].kind", f"{c['kind']!r} is not one of {', '.join(CARD_KINDS)}")
    cfg["cards"] = cards
    if "images" in raw:
        if not isinstance(raw["images"], list):
            raise _form("images", "must be a list")
        names = set()
        for i, im in enumerate(raw["images"]):
            _keys(im, f"images[{i}]", ("name", "path", "sha256"))
            if not isinstance(im["name"], str) or not IDENT_RE.match(im["name"]) or im["name"] in names:
                raise _form(f"images[{i}].name", "must be a unique identifier of a-z 0-9 . _ -")
            names.add(im["name"])
            if not isinstance(im["path"], str) or not im["path"]:
                raise _form(f"images[{i}].path", "must be a non-empty string")
            if not isinstance(im["sha256"], str) or not HEX64.match(im["sha256"]):
                raise _form(f"images[{i}].sha256", "must be 64 lowercase hex digits")
        cfg["images"] = raw["images"]
    if "windows" in raw:
        w = raw["windows"]
        _keys(w, "windows", (), ("zone", "list"))
        if "zone" in w:
            if not isinstance(w["zone"], str) or not ZONE.match(w["zone"]):
                raise _form("windows.zone", "must be `local` or a zone name such as Area/City")
            cfg["windows"]["zone"] = w["zone"]
        if "list" in w:
            if not isinstance(w["list"], list):
                raise _form("windows.list", "must be a list")
            names = set()
            for i, x in enumerate(w["list"]):
                _keys(x, f"windows.list[{i}]", ("name", "start", "end"))
                if not isinstance(x["name"], str) or not IDENT_RE.match(x["name"]) or x["name"] in names:
                    raise _form(f"windows.list[{i}].name", "must be a unique identifier of a-z 0-9 . _ -")
                names.add(x["name"])
                for k in ("start", "end"):
                    if not isinstance(x[k], str) or not CLOCK.match(x[k]):
                        raise _form(f"windows.list[{i}].{k}", "must be a time of day, HH:MM")
                if x["start"] == x["end"]:
                    raise _form(f"windows.list[{i}]", "start and end are the same time")
            cfg["windows"]["list"] = w["list"]
    if "floors" in raw:
        _keys(raw["floors"], "floors", (), tuple(DEFAULTS["floors"]))
        for k, v in raw["floors"].items():
            _number(v, f"floors.{k}", zero_ok=True)
            cfg["floors"][k] = v
    if "retention" in raw:
        _keys(raw["retention"], "retention", (), tuple(DEFAULTS["retention"]))
        for k, v in raw["retention"].items():
            if not (k == "record_days" and v is None):
                _number(v, f"retention.{k}")
            cfg["retention"][k] = v
    return cfg


def load_config(root: str) -> dict:
    path = os.path.join(root, "config.json")
    try:
        with open(path, "rb") as fh:
            raw = fh.read()
    except FileNotFoundError:
        raise Refusal("config-missing", f"{path} does not exist (run `init`)")
    try:
        obj = parse_text(raw)
    except Refusal as r:
        raise Refusal("config-form", f"config.json: {r.why}")
    return validate_config(obj)


def default_config_text() -> str:
    """What `init` writes: the defaults, and the one card the study names (edit it for another machine)."""
    d = {k: v for k, v in DEFAULTS.items()}
    d["cards"] = [{"id": "u50-0", "kind": "xrt"}]
    return json.dumps(d, indent=2, sort_keys=True) + "\n"
