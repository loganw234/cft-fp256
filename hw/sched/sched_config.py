# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""The state root and its configuration (docs/studies/SCHED-A-card-scheduler.md, section 5.1).

The root lives outside every checkout, given by --root or CFT_SCHED_ROOT; one inside a git working tree is
refused `root-in-checkout`. Its layout: config.json, lock, queue/, running/, jobs/, cards/, clones/,
extracts/ (clones/ and extracts/ are S2's and S4's), and ids/ (the markers that make a job id never reused).
config.json is read at start and an invalid one is refused `config-form`, by name. Each section is merged
over DEFAULTS, so a file may state only what it changes; `cards` has no default, because inventing a card
would be a claim about the machine. The retention is Logan's, 2026-10-21, doubled from the study's numbers.
The windows are acted on since parcel S3a (sched_calendar.py, sched_window.py); the retention since parcel S4a (sched_retention.py), at the end of every window job;
the floors are not acted on yet.
Parcel S2 added a card's optional `platform`, an image's optional `tiles` and `platform`, and the sections `code` (where a
job's bundles and remote are) and `runner` (the driver's own defaults for how a step runs). Parcel S3a added a window's optional
`dates` and seconds in its times, a zone that must be one this machine knows, and the runner's `window_grace_s` and `window_poll_s`. Parcel S4a added the
root's `publish/` (the scheduler's own clone of the repository, where a night's data commit is made) and `archive/` (what the retention keeps of a clone it removes),
and the section `publish`: `fetch_host`, how the desktop reaches this machine (the command that fetches a prepared commit is built with it).
"""
from __future__ import annotations

import copy
import datetime
import json
import math
import os
import re

import sched_calendar as CAL
from sched_names import Refusal
from sched_spec import IDENT_RE, parse_text      # one JSON reader: a repeated key and NaN are refused the same way

ENV_ROOT = "CFT_SCHED_ROOT"
LAYOUT = ("queue", "running", "jobs", "cards", "clones", "extracts", "ids", "publish", "archive")
CARD_KINDS = {"xrt": "an Alveo card driven through XRT over PCIe (the U50)"}   # nothing else reads a card's kind
HEX64 = re.compile(r"[0-9a-f]{64}\Z")
PLATFORM = re.compile(r"[A-Za-z0-9_.-]{1,100}\Z")
CLOCK = re.compile(r"(?:[01]\d|2[0-3]):[0-5]\d(?::[0-5]\d)?\Z")
DATE = re.compile(r"\d{4}-\d{2}-\d{2}\Z")
ZONE = re.compile(r"[A-Za-z0-9_+./-]{1,64}\Z")
HOST = re.compile(r"(?:[A-Za-z0-9._-]{1,64}@)?[A-Za-z0-9._:-]{1,255}\Z")

DEFAULTS = {
    "cards": None,                       # required
    "images": [],                        # [{name, path, sha256[, tiles, platform]}]: held to the files when a job runs (sched_images.py)
    "windows": {"zone": "local", "list": [{"name": "nightly", "start": "18:00", "end": "08:00"}]},
    "floors": {"disk_free_gb": 5},       # the driver's own floor, unchanged; nothing acts on it yet, and the retention never touches it
    "retention": {"idle_sample_minutes": 7.5, "clone_days": 14, "passing_log_days": 360, "record_days": None},
    # where a job's code comes from (parcel S2): `bundle:FILE` is FILE in bundle_dir, `remote` clones this URL, and a commit is
    # "pushed" when a branch of this remote holds it. Null: not configured, and a job that needs it is refused by name.
    "code": {"bundle_dir": None, "remote": None},
    # the data commit a window prepares (parcel S4a): fetch_host is `[user@]host` as the DESKTOP reaches this machine; null: this user at this machine's own name, which the desktop may not resolve
    "publish": {"fetch_host": None},
    # how a staged job runs (parcel S2): the driver's own defaults for its options of the same names
    # window_grace_s: how long past its window's end the driver may run before the scheduler asks it to stop (its STOP file); the driver's
    # own overshoot was 31, 74 and 181 s in the three runs measured and its longest leg is about 11 minutes. window_poll_s: how often
    # the scheduler looks while the driver runs (for the grace, and for a cancel).
    "runner": {"nice": 10, "kill_after_s": 60, "xrt_root": "/opt/xilinx/xrt", "build_jobs": 4, "build_timeout_s": 2400,
               "guard_wait_max_s": 14400, "guard_poll_s": 30, "rev8_images": None, "python": "python3",
               "window_grace_s": 900, "window_poll_s": 5},
}                                        # record_days null: every record is kept


def resolve_root(flag: str | None, environ=os.environ) -> str:
    root = flag or environ.get(ENV_ROOT)
    if not root:
        raise Refusal("root-unset", f"give --root DIR or set {ENV_ROOT} (on the box: /data/cft-sched)")
    return os.path.abspath(os.path.expanduser(root))


def checkout_of(path: str):
    """The directory, `path` itself or the nearest above it, that holds a .git (git's sign of a working tree), else None. The state root and a
    window's driver.out (sched_spec.validate) are both held to it."""
    d = os.path.realpath(path)
    while True:
        if os.path.lexists(os.path.join(d, ".git")):
            return d
        up = os.path.dirname(d)
        if up == d:
            return None
        d = up


def check_root(root: str, create: bool = False) -> str:
    """The root, or a refusal. The checkout test comes before anything is created."""
    real = os.path.realpath(root)
    d = checkout_of(real)
    if d:
        raise Refusal("root-in-checkout", f"{root} is inside the git working tree at {d}")
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
        _keys(c, f"cards[{i}]", ("id", "kind"), ("platform",))
        if not isinstance(c["id"], str) or not IDENT_RE.match(c["id"]) or c["id"] == "any":
            raise _form(f"cards[{i}].id", "must be 1 to 32 characters of a-z 0-9 . _ -, and not `any`")
        if c["id"] in seen:
            raise _form(f"cards[{i}].id", f"{c['id']!r} repeats")
        seen.add(c["id"])
        if c["kind"] not in CARD_KINDS:
            raise _form(f"cards[{i}].kind", f"{c['kind']!r} is not one of {', '.join(CARD_KINDS)}")
        if "platform" in c and not (isinstance(c["platform"], str) and PLATFORM.match(c["platform"])):
            raise _form(f"cards[{i}].platform", "must be the platform name an image manifest's `platform:` line carries, e.g. xilinx_u50_gen3x16_xdma_5_202210_1")
    cfg["cards"] = cards
    if "images" in raw:
        if not isinstance(raw["images"], list):
            raise _form("images", "must be a list")
        names = set()
        for i, im in enumerate(raw["images"]):
            _keys(im, f"images[{i}]", ("name", "path", "sha256"), ("tiles", "platform"))
            if not isinstance(im["name"], str) or not IDENT_RE.match(im["name"]) or im["name"] in names:
                raise _form(f"images[{i}].name", "must be a unique identifier of a-z 0-9 . _ -")
            names.add(im["name"])
            if not isinstance(im["path"], str) or not im["path"]:
                raise _form(f"images[{i}].path", "must be a non-empty string")
            if not isinstance(im["sha256"], str) or not HEX64.match(im["sha256"]):
                raise _form(f"images[{i}].sha256", "must be 64 lowercase hex digits")
            if "tiles" in im and (not isinstance(im["tiles"], int) or isinstance(im["tiles"], bool) or im["tiles"] < 1):
                raise _form(f"images[{i}].tiles", "must be a whole number, 1 or more")
            if "platform" in im and not (isinstance(im["platform"], str) and PLATFORM.match(im["platform"])):
                raise _form(f"images[{i}].platform", "must be the platform name an image manifest's `platform:` line carries")
        cfg["images"] = raw["images"]
    if "windows" in raw:
        w = raw["windows"]
        _keys(w, "windows", (), ("zone", "list"))
        if "zone" in w:
            if not isinstance(w["zone"], str) or not ZONE.match(w["zone"]):
                raise _form("windows.zone", "must be `local` or a zone name such as Area/City")
            if CAL.zone_problem(w["zone"]):
                raise _form("windows.zone", CAL.zone_problem(w["zone"]))
            cfg["windows"]["zone"] = w["zone"]
        if "list" in w:
            if not isinstance(w["list"], list):
                raise _form("windows.list", "must be a list")
            names = set()
            for i, x in enumerate(w["list"]):
                _keys(x, f"windows.list[{i}]", ("name", "start", "end"), ("dates",))
                if not isinstance(x["name"], str) or not IDENT_RE.match(x["name"]) or x["name"] in names:
                    raise _form(f"windows.list[{i}].name", "must be a unique identifier of a-z 0-9 . _ -")
                names.add(x["name"])
                for k in ("start", "end"):
                    if not isinstance(x[k], str) or not CLOCK.match(x[k]):
                        raise _form(f"windows.list[{i}].{k}", "must be a time of day, HH:MM or HH:MM:SS")
                if x["start"] == x["end"]:
                    raise _form(f"windows.list[{i}]", "start and end are the same time")
                if "dates" in x:
                    ds = x["dates"]
                    if not (isinstance(ds, list) and 1 <= len(ds) <= 400 and all(isinstance(d, str) and DATE.match(d) for d in ds)):
                        raise _form(f"windows.list[{i}].dates", "must be a list of 1 to 400 dates, YYYY-MM-DD (the dates the window starts on)")
                    for d in ds:
                        try:
                            datetime.date.fromisoformat(d)
                        except ValueError:
                            raise _form(f"windows.list[{i}].dates", f"{d!r} is not a date")
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
    if "code" in raw:
        _keys(raw["code"], "code", (), tuple(DEFAULTS["code"]))
        for k, v in raw["code"].items():
            if v is not None and not (isinstance(v, str) and v and len(v) <= 1000):
                raise _form(f"code.{k}", "must be a path or URL of 1 to 1000 characters, or null (not configured)")
            cfg["code"][k] = v
    if "publish" in raw:
        _keys(raw["publish"], "publish", (), tuple(DEFAULTS["publish"]))
        fh = raw["publish"].get("fetch_host")
        if fh is not None and not (isinstance(fh, str) and HOST.match(fh)):
            raise _form("publish.fetch_host", "must be [user@]host (letters, digits and . _ - : only), or null")
        cfg["publish"].update(raw["publish"])
    if "runner" in raw:
        _keys(raw["runner"], "runner", (), tuple(DEFAULTS["runner"]))
        for k, v in raw["runner"].items():
            if k in ("xrt_root", "python"):
                if not (isinstance(v, str) and v):
                    raise _form(f"runner.{k}", "must be a non-empty string")
            elif k == "rev8_images":
                if v is not None and not (isinstance(v, str) and v):
                    raise _form(f"runner.{k}", "must be a directory, or null (the state root's rev8-images)")
            elif k in ("nice", "build_jobs"):
                lo, hi = (0, 19) if k == "nice" else (1, 4096)
                if not isinstance(v, int) or isinstance(v, bool) or not lo <= v <= hi:
                    raise _form(f"runner.{k}", f"must be a whole number, {lo} to {hi}")
            else:
                _number(v, f"runner.{k}", zero_ok=k == "guard_wait_max_s")
            cfg["runner"][k] = v
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
