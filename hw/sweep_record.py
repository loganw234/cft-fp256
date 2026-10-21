#!/usr/bin/env python3
# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""sweep_record.py - the stress driver's finished sweep slices as signed records.

    python hw/sweep_record.py export RUN --out FILE (--key KEY | --device-key HEX)
    python hw/sweep_record.py sign   FILE --key KEY --out FILE2
    python hw/sweep_record.py verify FILE... [--keyring RING] [--allow-unsigned]

export  reads RUN (a run directory, or a metrics.jsonl) and writes FILE, a file it creates new:
        JSON lines in canonical form, a campaign record the first time an item is met and a
        record for every sweep slice that finished with a verdict (status pass or fail). With
        --key it signs them; with --device-key (a public key, 64 hex) it leaves them for `sign`.
sign    adds each record's signature: Ed25519 over `cft-sweep-record 1`, a NUL and the 32-byte id,
        by a key file in python/cft_sign.py's format that lies outside every git working tree.
verify  holds a file to the rules as one run's records. Signatures are required unless
        --allow-unsigned; with --keyring (cft_sign's format) the key must be in it.

Exit status, all three commands: 0; 3 (verify) when the records verify and some record is a
FINDING (a slice that found a mismatch: a record, never coverage); 2 for a refusal, printed as
`cft-sweep: refused <name>: <why>`; 64 for usage, key-file and key-in-tree; 73 for output.

Design: docs/studies/SWP-A-coverage.md 5.3 and 6.6. The record, its keys and what a signature
proves: docs/SWEEP-RECORDS.md. Version 1 holds what a leg record and run_start hold and no more:
a field the data cannot fill is ABSENT, never a default.

Two versions are known. Version 1 is the card slice and stream (the subject is a card image: its
name, the SHA-256 of its xclbin, its tiles) and the campaign, as they have always been written.
Version 2 adds ONE form: the slice and stream of a host-pool job (the image `cpu`), whose subject
is the host build that computed it - src, the git tree hash of host/, whether host/ differed from
it, and the compiler's version line, each read from run_start.tree. The exporter writes version 2
for a host-pool leg and version 1 for every other; a record is the one or the other, never both,
and `verify` takes both and refuses any other version by name (`version`).

From the driver: Exporter(Signer(load_seed(KEY))) takes the run_start, build and leg records the
driver writes (.run_start(rec), .build(rec), .leg(rec)) and returns the lines to append: none for
a leg that is not a sweep leg, or that did not finish (a status other than pass or fail, counted
in .left). A run_start or a leg that cannot be a record - a finished sweep leg with no sweep block
or no counts, a time or rate that is not a finite number, a leg the catalog disagrees with, a
host-pool slice whose run recorded no host/ tree, a slice dressed as the other kind - is a
Refusal named `metrics`, and the exporter stays as it was. It imports hw/card_stress_lib.py (the
item table and the driver's rules), python/cft_sign.py (the key file format) and python/cft_golden
(cert, cert2, ed25519); every other import is the standard library.
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
import os
import re
import sys
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "python"))
import card_stress_lib as L  # noqa: E402  the item table and the driver's counting rules
import cft_sign  # noqa: E402  the key file format
from cft_golden import cert, cert2, ed25519  # noqa: E402

VERSION = 1                                 # the card slice and stream, and the campaign: as they have always been written
HOST_VERSION = 2                            # the host-pool slice and stream: version 1's with a host build for its subject
VERSIONS = (VERSION, HOST_VERSION)          # every version this verifier knows; any other is refused by name (`version`)
TAG_RECORD = b"cft-sweep-record 1\x00"      # a record's signature signs this, then the 32-byte id
TAG_DEVICE = b"cft-sweep-device 1\x00"      # a device pseudonym hashes this, then the 32-byte key
ORACLE = "host-fpu+glibc"                  # SWP-A 2.5: the soaks compare with the host FPU and libm
BINARY = {"divsqrt": "divsqrt-soak", "clause5": "clause5-soak"}
MAXINT = (1 << 53) - 1                      # every integer a JSON reader holds exactly

REFUSALS = {                                # every refusal, by name
    "usage": "a command line, file or keyring the command cannot take",
    "output": "the output file is there already (never overwritten) or cannot be created",
    "key-file": "a key file that cannot be read, is not cft_sign.py's format, or that others may read",
    "key-in-tree": "a key file inside a git working tree: a signing key lives outside every repository",
    "metrics": "a run that cannot be exported as the driver wrote it (the message says how: a host-pool slice whose "
               "run recorded no host/ tree, a slice dressed as the other kind, ...)",
    "empty": "no finished sweep slice to export, or no slice or stream in the file to verify",
    "canonical": "a line whose bytes are not the record's canonical form",
    "version": "a record of a version this verifier does not know (it knows 1 and 2)",
    "form": "not a record of its version and kind: a field missing, unknown or out of its form (a card subject in a "
            "version-2 record, a host subject in a version-1 one, a version-2 campaign)",
    "id": "a record whose bytes do not hash to its id",
    "signature": "no signature where one is required, or one that does not verify",
    "signature-domain": "a signature that verifies under the certificate domain, not the record's",
    "signer": "a key of small order or no point, or a keyring that breaks its form",
    "key": "a signing key the keyring handed does not name",
    "device": "a run.device that is not the pseudonym of the key (or of the signing key)",
    "signed": "sign was given a record that carries a signature already",
    "splice": "a record of another run, or another device, in a file that is one run's",
    "campaign": "a record naming a campaign that is not in the file, or not of its kind (a slice of a random campaign; "
                "a host-pool record of a campaign whose reach is the tile)",
    "counts": "counts that break the driver's rules for the campaign",
    "run": "a run block whose times and rate disagree with each other",
}
EXIT = {"usage": 64, "key-file": 64, "key-in-tree": 64, "output": 73}    # 2 for the others
EXIT_FINDING = 3


class Refusal(Exception):
    def __init__(self, name, why):
        assert name in REFUSALS, f"unnamed refusal {name!r}"
        super().__init__(f"{name}: {why}")
        self.name, self.why = name, why


# ---- canonical form, id, signature --------------------------------------------------

def _plain(o, where="record"):
    """Only what version 1 writes: str, int, bool, list, dict with str keys. Never a float or null."""
    if isinstance(o, (bool, str)):
        return
    if isinstance(o, int):
        if not -MAXINT <= o <= MAXINT:
            raise ValueError(f"{where}: {o} is beyond 2^53 - 1")
    elif isinstance(o, list):
        for i, x in enumerate(o):
            _plain(x, f"{where}[{i}]")
    elif isinstance(o, dict):
        for k, v in o.items():
            if not isinstance(k, str):
                raise ValueError(f"{where}: a key that is not a string")
            _plain(v, f"{where}.{k}")
    else:
        raise ValueError(f"{where}: a {type(o).__name__} is not canonical (str, int, bool, list, dict only)")


def canon(obj) -> bytes:
    """Sorted keys, no spaces, ASCII (anything else as \\uXXXX), integers only."""
    _plain(obj)
    return json.dumps(obj, sort_keys=True, separators=(",", ":")).encode("ascii")


def record_id(rec) -> str:
    """SHA-256 of the canonical bytes without the id and the signature."""
    return hashlib.sha256(canon({k: v for k, v in rec.items() if k not in ("id", "sig")})).hexdigest()


def device_of(public: bytes) -> str:
    """A key's device pseudonym: 16 hex of SHA-256(`cft-sweep-device 1`, NUL, the 32-byte key)."""
    return hashlib.sha256(TAG_DEVICE + bytes(public)).hexdigest()[:16]


class Signer:
    def __init__(self, seed: bytes):
        self.seed, self.public = seed, ed25519.public_key(seed)
        self.device = device_of(self.public)

    def sign(self, body: dict) -> dict:
        """body (no id, no sig) -> the record with its id and signature."""
        rec = dict(body)
        rec["id"] = record_id(rec)
        rec["sig"] = {"alg": "ed25519", "key": self.public.hex(),
                      "sig": ed25519.sign(self.seed, TAG_RECORD + bytes.fromhex(rec["id"])).hex()}
        return rec


def key_in_tree(path):
    """The git working tree a key file's path lies in, or None: this repository's, or any ancestor
    directory with a .git (a file, in a linked worktree)."""
    p, root = Path(path).resolve(), Path(ROOT).resolve()
    if p.is_relative_to(root):
        return root
    return next((d for d in p.parents if (d / ".git").exists()), None)


def load_seed(path) -> bytes:
    """A key file (cft_sign.py's format) -> its seed. Inside a git working tree it is refused by
    name before it is read."""
    where = key_in_tree(path)
    if where is not None:
        raise Refusal("key-in-tree", f"{path} lies inside {where}: a signing key lives outside every "
                                     f"repository (docs/SWEEP-RECORDS.md, 'Keys')")
    try:
        return cft_sign.read_key(path)
    except cft_sign.Stop as e:
        raise Refusal("key-file", e.why) from None


def read_keyring(path) -> dict:
    try:
        data = Path(path).read_bytes()
    except OSError as e:
        raise Refusal("usage", f"the keyring {path} cannot be read ({e.strerror})") from None
    try:
        return cert2.read_keyring(data)
    except cert.Refusal as e:
        raise Refusal("signer", e.message) from None


# ---- the records' forms -----------------------------------------------------------------

def _h(n): return re.compile(r"[0-9a-f]{%d}" % n)
def _uint(v): return type(v) is int and 0 <= v <= MAXINT
def _pos(v): return type(v) is int and 1 <= v <= MAXINT
def _bool(v): return type(v) is bool
def _rx(pat): return lambda v: type(v) is str and pat.fullmatch(v) is not None
def _one(*xs): return lambda v: type(v) is str and v in xs
def _eq(x): return lambda v: type(v) is type(x) and v == x
def _strs(n, m): return lambda v: type(v) is list and len(v) <= n and all(type(s) is str and len(s) <= m for s in v)
def _text(n): return lambda v: type(v) is str and 1 <= len(v) <= n and all(ord(ch) >= 32 and ord(ch) != 127 for ch in v)


NAME = re.compile(r"[a-z][a-z0-9-]{0,63}")
RUNID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")
RELPATH = re.compile(r"(?!/)(?!.*\.\.)[A-Za-z0-9._/-]{1,200}")      # relative, no `..`, no drive, no ~
COMMIT = re.compile(r"[0-9a-f]{40}|[0-9a-f]{64}")                   # a git object name: SHA-1, or SHA-256 in a repository that uses it
ARGS = re.compile(r"op (?:lo hi|count seed)(?: mode)?")
CC_MAX = 256                                                        # the compiler's version line: text of at most this many characters
H64, H128 = _rx(_h(64)), _rx(_h(128))
SUBJECT = ({"image": _rx(NAME), "xclbin": H64, "tiles": _pos}, {"tile": _pos})              # version 1: a card image
HOST_SUBJECT = ({"src": _rx(COMMIT)}, {"dirty": _bool, "cc": _text(CC_MAX)})                # version 2: a host build
TOOL = ({"commit": _rx(COMMIT), "dirty": _bool}, {})
RUN = ({"id": _rx(RUNID), "device": _rx(_h(16)), "start_ms": _uint, "end_ms": _uint},
       {"rate": _uint, "log": _rx(RELPATH)})
SIG = ({"alg": _eq("ed25519"), "key": H64, "sig": H128}, {})
_CAMPAIGN_HEAD = {"id": H64, "v": _eq(VERSION)}


def _forms(version, subject):
    """The slice and the stream of one version: version 1's and version 2's differ in the subject and in `v`, and in nothing else."""
    head = {"id": H64, "v": _eq(version)}
    both = {"cases": _uint, "vm": _uint, "fm": _uint, "subject": subject, "run": RUN}
    opt = {"tool": TOOL, "disagreements": _strs(16, 1000), "sig": SIG}
    return {"slice": (dict(head, kind=_eq("slice"), cid=H64, lo=_uint, hi=_pos, **both), dict(opt, skipped=_uint)),
            "stream": (dict(head, kind=_eq("stream"), cid=H64, seed=_uint, count=_pos, **both), opt)}


SHAPES = {                                   # by version, then kind: a campaign is version 1's, whatever version the records naming it are
    VERSION: dict(_forms(VERSION, SUBJECT), campaign=(
        dict(_CAMPAIGN_HEAD, kind=_eq("campaign"), operation=_rx(NAME), sweep=_one("exhaustive", "random"),
             tool=_rx(NAME), args=_rx(ARGS), oracle=_rx(re.compile(r"[a-z][a-z0-9+-]{0,39}")),
             reach=_one("tile", "host")),
        {"attribute": _rx(NAME), "space": _pos, "exact": _bool, "extra_cases": _pos, "per_encoding": _pos})),
    HOST_VERSION: _forms(HOST_VERSION, HOST_SUBJECT),
}


def _shape(obj, spec, where, what, v=VERSION):
    req, opt = spec
    for k in req:
        if k not in obj:
            raise Refusal("form", f"{where}: the {what} has no field '{k}'")
    for k, val in obj.items():
        chk = req.get(k) or opt.get(k)
        if chk is None:
            raise Refusal("form", f"{where}: '{k}' is not a field of version {v}'s {what}")
        if isinstance(chk, tuple):
            if type(val) is not dict:
                raise Refusal("form", f"{where}: '{k}' is not an object")
            _shape(val, chk, f"{where}.{k}", k, v)
        elif not chk(val):
            raise Refusal("form", f"{where}: '{k}' is not in version {v}'s form for it")


def subject_kind(rec) -> str:
    """What computed a slice or stream: 'host' (version 2: a host-pool job, on the CPU) or 'card' (version 1: a card image)."""
    return "host" if rec["v"] == HOST_VERSION else "card"


def check_shape(obj, where):
    kind, v = obj.get("kind"), obj.get("v")
    if type(kind) is not str or kind not in ("campaign", "slice", "stream"):
        raise Refusal("form", f"{where}: kind {kind!r} is none of campaign, slice, stream")
    if type(v) is not int:
        raise Refusal("form", f"{where}: 'v', the version, is missing or not an integer")
    if v not in SHAPES:
        raise Refusal("version", f"{where}: version {v}; this verifier knows versions {' and '.join(map(str, VERSIONS))}")
    if kind not in SHAPES[v]:
        raise Refusal("form", f"{where}: version {v} has no {kind}: a campaign is version {VERSION}'s whatever the version of the "
                              f"records that name it, so no campaign id depends on it")
    sub = obj.get("subject")
    if isinstance(sub, dict) and kind != "campaign":     # a card slice dressed as a host one and the reverse, said as what each is
        if v == HOST_VERSION and ("image" in sub or "xclbin" in sub):
            raise Refusal("form", f"{where}: a version-{v} {kind} has a host build for its subject (src), and this one has a card "
                                  f"image's: a card slice is version {VERSION}")
        if v == VERSION and "src" in sub:
            raise Refusal("form", f"{where}: a version-{v} {kind} has a card image for its subject (image, xclbin, tiles), and this "
                                  f"one has a host build's (src): a host-pool slice is version {HOST_VERSION}")
    _shape(obj, SHAPES[v][kind], where, kind, v)
    if kind == "campaign":
        exh = obj["sweep"] == "exhaustive"
        have = {"space", "exact", "extra_cases", "per_encoding"} & set(obj)
        if (exh and not {"space", "exact"} <= have) or (not exh and have):
            raise Refusal("form", f"{where}: an exhaustive campaign has space and exact (and, where they "
                                  f"apply, extra_cases and per_encoding); a random one has none of them")
        want = ("op lo hi" if exh else "op count seed") + (" mode" if "attribute" in obj else "")
        if obj["args"] != want:
            raise Refusal("form", f"{where}: args is {obj['args']!r}; this campaign's form is {want!r}")
    else:
        sub = obj["subject"]
        if kind == "slice" and obj["lo"] >= obj["hi"]:
            raise Refusal("form", f"{where}: the interval [{obj['lo']}, {obj['hi']}) is empty")
        if "tiles" in sub and sub.get("tile", 1) > sub["tiles"]:         # a host build has no tiles
            raise Refusal("form", f"{where}: tile {sub['tile']} of an image with {sub['tiles']} tiles")


def read_record_line(raw: bytes, n: int) -> dict:
    """One line, without its LF -> the record, its syntax, version and canonical bytes held."""
    where = f"line {n}"
    if raw.endswith(b"\r"):
        raise Refusal("canonical", f"{where} ends in CR: a record file is LF, not CRLF")
    if not raw or any(b > 0x7E or b < 0x20 for b in raw):
        raise Refusal("canonical", f"{where} is empty or holds a byte outside printable ASCII (other "
                                   f"text is written \\uXXXX)")

    def no_float(s): raise ValueError(f"the number {s} is not an integer")
    def no_const(s): raise ValueError(f"{s} is not a JSON value")

    def pairs(ps):
        d = {}
        for k, v in ps:
            if k in d:
                raise ValueError(f"the key {k!r} twice")
            d[k] = v
        return d
    try:
        obj = json.loads(raw.decode("ascii"), parse_float=no_float, parse_constant=no_const,
                         object_pairs_hook=pairs)
    except (ValueError, RecursionError) as e:
        raise Refusal("form", f"{where} is not JSON a reader can take: {e}") from None
    if not isinstance(obj, dict):
        raise Refusal("form", f"{where} is not a JSON object")
    if type(obj.get("v")) is not int:
        raise Refusal("form", f"{where}: 'v', the version, is missing or not an integer")
    if obj["v"] not in VERSIONS:
        raise Refusal("version", f"{where}: version {obj['v']}; this verifier knows versions {' and '.join(map(str, VERSIONS))}")
    try:
        same = canon(obj) == raw
    except ValueError as e:
        raise Refusal("form", f"{where}: {e}") from None
    if not same:
        raise Refusal("canonical", f"{where} is not the canonical form of its record (sorted keys, no "
                                   f"spaces, integers only)")
    return obj


def read_file(path):
    try:
        return parse_file(Path(path).read_bytes())
    except OSError as e:
        raise Refusal("usage", f"{path} cannot be read ({e.strerror})") from None


def parse_file(data: bytes):
    """A file's bytes -> [(line number, record)], each held to its form and its id."""
    if not data:
        raise Refusal("empty", "the file is empty")
    lines = data.split(b"\n")
    if lines.pop() != b"":
        raise Refusal("canonical", "the last line has no LF")
    out = []
    for n, raw in enumerate(lines, 1):
        rec = read_record_line(raw, n)
        check_shape(rec, f"line {n}")
        if rec["id"] != record_id(rec):
            raise Refusal("id", f"line {n}: the bytes hash to {record_id(rec)[:16]}..., the id says "
                                f"{rec['id'][:16]}...")
        out.append((n, rec))
    return out


# ---- the rules the verifier applies ---------------------------------------------------------

def campaign_body(it) -> dict:
    """The campaign record (no id) of one of hw/card_stress_lib.py's items: what is swept and how a
    slice's counts are held. Its SHA-256 is the cid. The study's stratum and enumeration do not exist
    yet and are absent."""
    exh = it.kind == "exhaustive"
    c = {"v": VERSION, "kind": "campaign", "operation": it.op, "sweep": it.kind, "tool": BINARY[it.tool],
         "oracle": ORACLE, "reach": it.reach,
         "args": ("op lo hi" if exh else "op count seed") + ("" if it.mode is None else " mode")}
    if it.mode is not None:
        c["attribute"] = it.mode
    if exh:
        # the item's own space: 2^32 encodings for the fp32-operand items (Item.space's default, so every one of those campaign
        # records and its hash is what it was), the mode's indices for the hard-case and class-level items (2026-10-21, DR3, at the
        # lead's word: before it every campaign said 2^32, and counts_problem could not see an interval past a smaller space)
        c["space"], c["exact"] = getattr(it, "space", L.EXH), bool(it.exact)
        if it.extra_cases:
            c["extra_cases"] = it.extra_cases
        if it.per_encoding is not None:
            c["per_encoding"] = it.per_encoding
    return c


def counts_problem(camp, rec):
    """Why a record's counts break the driver's rules for its campaign, or None: the rules of
    card_stress_lib.parse_soak - expected_cases where the count is exact, the cover rule (cases +
    skipped = the checks an encoding takes x its encodings) where the tool says what it covered, and
    otherwise more than 0 cases."""
    if rec["kind"] == "stream":
        return None if rec["cases"] > 0 else "0 cases: the tool ran nothing"
    n, per = rec["hi"] - rec["lo"], camp.get("per_encoding")
    if rec["hi"] > camp["space"]:
        return f"the interval ends at {rec['hi']}, past the campaign's space of {camp['space']}"
    if (per is None) != ("skipped" not in rec):
        return (f"skipped is carried exactly where the tool prints what it covered (per_encoding {per}); "
                f"this record " + ("has it" if "skipped" in rec else "lacks it"))
    if camp["exact"] and rec["cases"] != n * (per or 1) + camp.get("extra_cases", 0):
        return f"{rec['cases']} cases where the slice has {n * (per or 1) + camp.get('extra_cases', 0)}"
    if per is not None and rec["cases"] + rec["skipped"] != per * n:
        return (f"{rec['cases']} cases and {rec['skipped']} skipped make {rec['cases'] + rec['skipped']} checks "
                f"where {per} for each of {n} encodings make {per * n}")
    if per is None and not camp["exact"] and rec["cases"] == 0:
        return "0 cases: the tool ran nothing"
    return None


def run_problem(rec):
    """Why a run block disagrees with itself, or None: the end before the start, or a rate that is not
    the record's cases over its own duration, to the millisecond the times are kept to."""
    r = rec["run"]
    d = r["end_ms"] - r["start_ms"]
    if d < 0:
        return f"the end ({r['end_ms']}) is before the start ({r['start_ms']})"
    if "rate" in r:
        if d < 2:
            return "a rate over a duration of under 2 ms, which the times cannot hold it to"
        lo, hi = rec["cases"] * 1000 // (d + 1) - 1, -(-rec["cases"] * 1000 // (d - 1)) + 1
        if not lo <= r["rate"] <= hi:
            return f"a rate of {r['rate']} cases/s where {rec['cases']} cases in {d} ms is {lo} to {hi}"
    return None


def is_finding(rec) -> bool:
    """A slice or stream that found a mismatch: a record, and a finding; never coverage."""
    return rec["vm"] + rec["fm"] > 0


def subject_problem(camp, rec):
    """Why a record's subject cannot be the evidence its campaign is about, or None. A host-pool record (version 2) is evidence about
    the host library run on the CPU, and a campaign whose reach is the tile asks about the card's tile, which a host job does not
    touch; the other way is not refused: until the host pool existed the card swept the host items too (a card image's slice of a
    campaign whose reach is the host), and those version-1 records stay valid."""
    if subject_kind(rec) == "host" and camp["reach"] != "host":
        return (f"a host-pool {rec['kind']} (version {rec['v']}) of a campaign whose reach is {camp['reach']}: a host build computes "
                f"nothing the tile does, so its subject is no evidence about this campaign")
    return None


def check_signature(rec, ring):
    """The signature, then its key against the keyring, then its device; a refusal by name."""
    sg, key = rec["sig"], bytes.fromhex(rec["sig"]["key"])
    why = cert2.key_problem(sg["key"])
    if why is not None:
        raise Refusal("signer", f"the key {sg['key']}: {why[1]}")
    sig = bytes.fromhex(sg["sig"])
    if not ed25519.verify(key, TAG_RECORD + bytes.fromhex(rec["id"]), sig):
        if ed25519.verify(key, cert2.signature_message(rec["id"]), sig):
            raise Refusal("signature-domain", "the signature verifies under the certificate domain "
                                              "'cft-signature 1', not 'cft-sweep-record 1': a certificate's "
                                              "signature signs no record")
        raise Refusal("signature", f"the signature does not verify under key {sg['key']}")
    if ring is not None and sg["key"] not in ring:
        raise Refusal("key", f"the key {sg['key']} is not in the keyring handed")
    if rec["run"]["device"] != device_of(key):
        raise Refusal("device", f"run.device is {rec['run']['device']}; this key's pseudonym is "
                                f"{device_of(key)}")


def verify_records(recs, ring=None, require_signed=True):
    """Every record of a file held to the rules, for each in this order: splice, signature, campaign
    (its kind and its reach), counts, run. Returns the report, whose `kinds` totals the records by what
    computed them (card, host); raises the first refusal."""
    for n, rec in recs:                     # a caller may hand records parse_file has not seen: no trust in a stored id
        if rec["id"] != record_id(rec):
            raise Refusal("id", f"line {n}: the bytes hash to {record_id(rec)[:16]}..., the id says {rec['id'][:16]}...")
    camps = {r["id"]: r for _, r in recs if r["kind"] == "campaign"}
    rep = {"run": None, "device": None, "campaigns": len(camps), "slices": 0, "streams": 0, "clean": 0,
           "findings": [], "unsigned": 0, "keys": collections.Counter(), "cases": 0,
           "kinds": {k: {"records": 0, "clean": 0, "cases": 0} for k in ("card", "host")}}
    for n, rec in recs:
        if rec["kind"] == "campaign":
            continue
        who = f"line {n} (record {rec['id'][:16]})"
        ident = (rec["run"]["id"], rec["run"]["device"])
        if rep["run"] is None:
            rep["run"], rep["device"] = ident
        elif ident != (rep["run"], rep["device"]):
            raise Refusal("splice", f"{who} is run {ident[0]} on device {ident[1]}; this file is run "
                                    f"{rep['run']} on device {rep['device']}")
        if "sig" in rec:
            try:
                check_signature(rec, ring)
            except Refusal as e:
                raise Refusal(e.name, f"{who}: {e.why}") from None
            rep["keys"][rec["sig"]["key"]] += 1
        elif require_signed:
            raise Refusal("signature", f"{who} has no signature (--allow-unsigned accepts it and "
                                       f"attributes it to no one)")
        else:
            rep["unsigned"] += 1
        camp = camps.get(rec["cid"])
        if camp is None:
            raise Refusal("campaign", f"{who} names the campaign {rec['cid'][:16]}..., not in the file")
        if (rec["kind"] == "slice") != (camp["sweep"] == "exhaustive"):
            raise Refusal("campaign", f"{who} is a {rec['kind']} of a {camp['sweep']} campaign")
        for name, why in (("campaign", subject_problem(camp, rec)), ("counts", counts_problem(camp, rec)), ("run", run_problem(rec))):
            if why:
                raise Refusal(name, f"{who}: {why}")
        rep[rec["kind"] + "s"] += 1
        row = rep["kinds"][subject_kind(rec)]
        row["records"] += 1
        if is_finding(rec):
            rep["findings"].append((n, rec, camp))
        else:
            rep["clean"] += 1
            rep["cases"] += rec["cases"]
            row["clean"] += 1
            row["cases"] += rec["cases"]
    if rep["run"] is None:
        raise Refusal("empty", "no slice or stream record in the file")
    return rep


# ---- export: a leg record becomes a record --------------------------------------------------

def _ms(x, what, scale=1000):
    """x times `scale` (seconds to milliseconds), rounded to an integer; a Refusal for what is no finite number."""
    if isinstance(x, bool) or not isinstance(x, (int, float)):
        raise Refusal("metrics", f"{what} is missing or not a number")
    try:
        return int(round(x * scale))
    except (OverflowError, ValueError):                 # Infinity, NaN
        raise Refusal("metrics", f"{what} is not a finite number") from None


class Exporter:
    """run_start, build and leg records in, lines out. Its state - the run, whether its build was held,
    the campaigns met - changes only when a leg has become a record."""

    def __init__(self, signer=None, public=None, items=None):
        self.signer = signer
        self.public = signer.public if signer else bytes(public)
        self.device = device_of(self.public)
        self.items = items or {it.name: it for it in L.sweep_items()}
        self.start, self.built, self.seen = None, False, set()
        self.left = collections.Counter()       # sweep legs not exported, by status
        self.legs = self.findings = 0

    def run_start(self, rec):
        try:
            rid = rec.get("run_id")
            if not isinstance(rid, str) or not RUNID.fullmatch(rid):
                raise Refusal("metrics", f"run_start: the run id {rid!r} has no version-{VERSION} spelling")
            if isinstance(rec.get("settings"), dict) and rec["settings"].get("dry_run"):
                raise Refusal("metrics", f"run {rid} is a dry run (settings.dry_run): its legs came from "
                                         f"stand-ins, not the card, and are never exported")
            if self.start is not None and self.start["run_id"] != rid:
                raise Refusal("metrics", f"the file holds two runs, {self.start['run_id']} and {rid}")
            if not isinstance(rec.get("images"), dict):
                raise Refusal("metrics", f"run {rid}: run_start has no images")
        except (AttributeError, KeyError, TypeError, ValueError, OverflowError) as e:
            raise Refusal("metrics", f"run_start: {type(e).__name__}: {e}") from None
        self.start, self.built = rec, False

    def build(self, rec):
        self.built = rec.get("ok") is True

    def _card_subject(self, rec, sw, where):
        """Version 1's subject: the card image the job ran on (name, the SHA-256 of its xclbin held equal to run_start's, its tiles) and
        the tile it ran on, where the leg recorded one. A leg that carries the host pool's mark (sweep.pool) is a host-pool slice
        dressed as a card one: refused."""
        if sw.get("pool") is not None:
            raise Refusal("metrics", f"{where}: a host-pool slice dressed as a card one: it names the image {rec.get('image')!r} and "
                                     f"carries the host pool's mark (sweep.pool), and the pool's jobs are on the image {L.CPU!r}")
        img = self.start["images"].get(rec.get("image"))
        if not isinstance(img, dict) or img.get("sha256") != rec.get("image_sha256"):
            raise Refusal("metrics", f"{where}: image {rec.get('image')!r} with a hash that is not run_start's")
        sub = {"image": rec["image"], "xclbin": rec["image_sha256"], "tiles": img.get("tiles")}
        if sw.get("tile") is not None:
            sub["tile"] = sw["tile"]
        return sub

    def _host_subject(self, rec, sw, it, where):
        """Version 2's subject, for a leg of the host pool (the image cpu): the host build that computed it, each field READ from
        run_start.tree - src (host_src, the git tree hash of host/, which the run must have recorded: required), dirty (host_src_dirty,
        whether host/ differed from it, untracked files included) and cc (the compiler's version line) - and ABSENT where the run
        recorded none, never a default. Nothing of the machine is in it (run_start.host is a node name, which no record carries; no CPU
        model or libm version is recorded). A card slice dressed as a host one, and a host slice of a tile item, are refused."""
        if rec.get("image_sha256") is not None or sw.get("tile") is not None:
            raise Refusal("metrics", f"{where}: a card slice dressed as a host-pool one: image {L.CPU!r} (a CPU job has no xclbin and "
                                     f"no tile) with " + ("an image hash" if rec.get("image_sha256") is not None else f"tile {sw['tile']}"))
        if it.reach != L.HOST:
            raise Refusal("metrics", f"{where}: a host-pool slice of {it.name}, an item whose reach is {it.reach}: a host build computes "
                                     f"nothing the tile does, so its subject is no evidence about it")
        tree = self.start.get("tree")
        tree = tree if isinstance(tree, dict) else {}
        src = tree.get("host_src")
        if not isinstance(src, str) or not COMMIT.fullmatch(src):
            raise Refusal("metrics", f"{where}: a host-pool slice whose run recorded no host/ tree (run_start.tree.host_src is "
                                     f"{src!r}): a record of what a host job tested says which source it was, and this run does not")
        sub = {"src": src}
        if isinstance(tree.get("host_src_dirty"), bool):
            sub["dirty"] = tree["host_src_dirty"]
        cc = tree.get("cc")
        if cc is not None:
            if not HOST_SUBJECT[1]["cc"](cc):
                raise Refusal("metrics", f"{where}: run_start.tree.cc is not a compiler version line a record can hold (text of 1 to "
                                         f"{CC_MAX} characters, no control character): {str(cc)[:60]!r}")
            sub["cc"] = cc
        return sub

    def _body(self, rec, sw, counts, status, where):
        """-> (the campaign record with its id, the record's body without id and signature), or Refusal metrics."""
        it = self.items.get(sw.get("item")) if isinstance(sw.get("item"), str) else None
        if it is None:
            raise Refusal("metrics", f"{where}: not an item of this tree's catalog")
        exh = it.kind == "exhaustive"
        for k, want in (("op", it.op), ("mode", it.mode), ("tool", it.tool), ("reach", it.reach)):
            if k in sw and sw[k] != want:       # a key an older driver did not write is no conflict
                raise Refusal("metrics", f"{where}: sweep.{k} is {sw[k]!r}; the catalog says {want!r}")
        if exh != ("lo" in sw):
            raise Refusal("metrics", f"{where}: its range form is not its item's ({it.kind})")
        if exh:
            lo, hi = sw["lo"], sw["hi"]
            for k, want in (("expected_cases", it.expected_cases(lo, hi)),
                            ("expected_encodings", (hi - lo) if it.per_encoding is not None else None)):
                if k in sw and sw[k] != want:
                    raise Refusal("metrics", f"{where}: sweep.{k} is {sw[k]!r}; the catalog's rule for the item gives {want!r}")
            if counts.get("encodings", hi - lo) != hi - lo:
                raise Refusal("metrics", f"{where}: the tool ran {counts['encodings']} encodings of {hi - lo}")
        camp = campaign_body(it)
        camp["id"] = record_id(camp)
        if rec.get("image") == L.CPU:
            version, subject = HOST_VERSION, self._host_subject(rec, sw, it, where)
        else:
            version, subject = VERSION, self._card_subject(rec, sw, where)
        body = {"v": version, "cid": camp["id"], "cases": counts.get("cases"), "vm": counts.get("value_mismatches"),
                "fm": counts.get("flag_mismatches"), "subject": subject,
                "run": {"id": self.start["run_id"], "device": self.device,
                        "start_ms": _ms(rec.get("start_epoch"), "start_epoch"),
                        "end_ms": _ms(rec.get("end_epoch"), "end_epoch")}}
        body.update(kind="slice", lo=lo, hi=hi) if exh else body.update(
            kind="stream", seed=sw.get("seed"), count=sw.get("count"))
        if exh and "skipped" in counts:
            body["skipped"] = counts["skipped"]
        rate = rec.get("rate")
        if isinstance(rate, dict) and rate.get("unit") == "cases/s" and isinstance(rate.get("value"), (int, float)):
            body["run"]["rate"] = _ms(rate["value"], "rate.value", 1)
        if rec.get("log"):
            body["run"]["log"] = rec["log"]
        tree = self.start.get("tree")
        if isinstance(tree, dict) and isinstance(tree.get("commit"), str) and isinstance(tree.get("dirty"), bool):
            body["tool"] = {"commit": tree["commit"], "dirty": tree["dirty"]}
        found = (body["vm"] or 0) + (body["fm"] or 0) > 0
        if found != (status == "fail"):
            raise Refusal("metrics", f"{where}: status {status} and mismatches {body['vm']}/{body['fm']} disagree")
        if rec.get("disagreements"):
            if not found:
                raise Refusal("metrics", f"{where}: disagreement lines on a slice with none counted")
            body["disagreements"] = list(rec["disagreements"])
        return camp, body

    def leg(self, rec):
        """The lines to append for one record of the run: [] unless it is a sweep leg that finished with
        a verdict; the campaign's line first the first time its item is met. A leg that did not finish
        is counted in .left. A finished one that cannot be a record is a Refusal named `metrics`."""
        if rec.get("type") != "leg" or rec.get("kind") != "sweep":
            return []
        sw, counts, status = rec.get("sweep"), rec.get("counts"), rec.get("status")
        if status not in ("pass", "fail"):
            self.left[str(status)] += 1
            return []
        where = f"the {status} leg of {sw.get('item') if isinstance(sw, dict) else None!r} started {rec.get('start')}"
        if not isinstance(sw, dict) or not isinstance(counts, dict):
            raise Refusal("metrics", f"{where}: a finished sweep leg has a sweep block and counts, and this one has "
                                     + ("no sweep block" if not isinstance(sw, dict) else "no counts"))
        if self.start is None or not self.built:
            raise Refusal("metrics", f"{where}: no run_start, or no passing build record since it: the tools "
                                     f"were not held to the tree")
        ver = VERSION
        try:
            camp, body = self._body(rec, sw, counts, status, where)
            ver = body["v"]
            out = self.signer.sign(body) if self.signer else dict(body, id=record_id(body))
            check_shape(out, where)                     # the output is held to the verifier's own rules
            for name, why in (("campaign", subject_problem(camp, out)), ("counts", counts_problem(camp, out)),
                              ("run", run_problem(out))):
                if why:
                    raise Refusal(name, why)
        except Refusal as e:
            if e.name == "metrics":
                raise
            raise Refusal("metrics", f"{where} is not a version-{ver} record: {e.name}: {e.why}") from None
        except (KeyError, TypeError, ValueError, OverflowError) as e:
            raise Refusal("metrics", f"{where}: {type(e).__name__}: {e}") from None
        lines = [] if camp["id"] in self.seen else [canon(camp) + b"\n"]
        self.seen.add(camp["id"])
        self.legs += 1
        self.findings += is_finding(out)
        return lines + [canon(out) + b"\n"]


def read_metrics(path):
    """RUN (a directory holding metrics.jsonl, or the file itself) -> (records, torn tail?)."""
    p = Path(path)
    p = p / "metrics.jsonl" if p.is_dir() else p
    try:
        recs, partial, bad = L.read_records(str(p))
    except OSError as e:
        raise Refusal("metrics", f"{p} cannot be read ({e.strerror})") from None
    if bad:
        raise Refusal("metrics", f"{p}: lines {bad[:10]} do not parse")
    return recs, partial


def export_run(path, ex):
    """-> (the lines, a torn tail?), the records in file order, each run_start and build ahead of its legs."""
    recs, partial = read_metrics(path)
    lines = []
    for rec in recs:
        if not isinstance(rec, dict):
            raise Refusal("metrics", f"{path}: a line that is no JSON object")
        t = rec.get("type")          # every type but these three is another reader's: ignored
        if t == "run_start":
            ex.run_start(rec)
        elif t == "build":
            ex.build(rec)
        elif t == "leg":
            lines += ex.leg(rec)
    if not ex.legs:
        left = ", ".join(f"{k} {v}" for k, v in sorted(ex.left.items())) or "no sweep leg"
        raise Refusal("empty", f"no sweep slice finished with a verdict in {path} ({left})")
    return lines, partial


def create_new(path, data):
    try:
        fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0), 0o644)
    except FileExistsError:
        raise Refusal("output", f"{path} is there already; it is never overwritten") from None
    except OSError as e:
        raise Refusal("output", f"{path} cannot be created ({e.strerror})") from None
    with os.fdopen(fd, "wb") as f:
        f.write(data)


# ---- the commands -------------------------------------------------------------------------

def cmd_export(a):
    if a.key is not None:
        ex = Exporter(signer=Signer(load_seed(a.key)))
    else:
        if not re.fullmatch(r"[0-9a-f]{64}", a.device_key) or cert2.key_problem(a.device_key):
            raise Refusal("usage", "--device-key is a public key: 64 lowercase hex, a point of the curve "
                                   "not of small order")
        ex = Exporter(public=bytes.fromhex(a.device_key))
    lines, partial = export_run(a.run, ex)
    create_new(a.out, b"".join(lines))
    print(f"sweep_record: {ex.legs} records and {len(lines) - ex.legs} campaigns of run {ex.start['run_id']} "
          f"to {a.out}; {ex.findings} findings; device {ex.device}, "
          + (f"signed by key {ex.public.hex()}" if ex.signer else f"UNSIGNED, for key {ex.public.hex()}"))
    if ex.left:
        print("sweep_record: not exported, not finished slices: "
              + ", ".join(f"{v} {k}" for k, v in sorted(ex.left.items())))
    if partial:
        print("sweep_record: the metrics file ends in a torn line, which is no record")


def cmd_sign(a):
    signer = Signer(load_seed(a.key))
    recs = read_file(a.file)
    verify_records(recs, None, require_signed=False)       # a key does not vouch for what would not verify
    out, n_signed = [], 0
    for n, rec in recs:
        if rec["kind"] != "campaign":
            if "sig" in rec:
                raise Refusal("signed", f"line {n}: the record has a signature; a version-{rec['v']} record has one")
            if rec["run"]["device"] != signer.device:
                raise Refusal("device", f"line {n}: it names device {rec['run']['device']}, not this key's "
                                        f"({signer.device}): export it for this key")
            rec = signer.sign({k: v for k, v in rec.items() if k not in ("id", "sig")})
            n_signed += 1
        out.append(canon(rec) + b"\n")
    create_new(a.out, b"".join(out))
    print(f"sweep_record: signed {n_signed} records to {a.out} with key {signer.public.hex()} "
          f"(device {signer.device})")


def cmd_verify(a):
    ring = read_keyring(a.keyring) if a.keyring else None
    found = 0
    for path in a.files:
        try:
            rep = verify_records(read_file(path), ring, require_signed=not a.allow_unsigned)
        except Refusal as e:
            raise Refusal(e.name, f"{path}: {e.why}") from None
        print(f"{path}: run {rep['run']}, device {rep['device']}: {rep['campaigns']} campaigns, {rep['slices']} "
              f"slices and {rep['streams']} streams; {rep['clean']} clean ({rep['cases']} cases), "
              f"{len(rep['findings'])} FINDINGS")
        print("  by subject: " + "; ".join(f"{k} {v['clean']} clean ({v['cases']} cases)" + (
            f", {v['records'] - v['clean']} findings" if v["records"] != v["clean"] else "") for k, v in rep["kinds"].items()))
        for key, k in sorted(rep["keys"].items()):
            holder = ring.get(key) if ring is not None else None
            print(f"  {k} signed by key {key}, " + (f"held by {cert2.text_token(holder)} by the keyring handed"
                  if holder else "which no keyring handed names: nothing here says whose it is"))
        if rep["unsigned"]:
            print(f"  UNSIGNED: {rep['unsigned']} records; their form, ids and counts are held, and they are "
                  f"attributed to no one")
        for n, rec, camp in rep["findings"]:
            what = f"slice [{rec['lo']}, {rec['hi']})" if rec["kind"] == "slice" else f"stream seed {rec['seed']}"
            print(f"  FINDING line {n}: {camp['operation']} {camp.get('attribute', '-')} {what}: {rec['vm']} value "
                  f"and {rec['fm']} flag mismatches (record {rec['id'][:16]}); never coverage"
                  + (f"; first line: {rec['disagreements'][0]}" if rec.get("disagreements") else ""))
        found += len(rep["findings"])
    print("sweep_record: verified" + (f"; {found} FINDINGS" if found else ""))
    return EXIT_FINDING if found else 0


def main(argv=None):
    ap = argparse.ArgumentParser(prog="sweep_record", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="what")
    e = sub.add_parser("export")
    e.add_argument("run")
    e.add_argument("--out", required=True)
    g = e.add_mutually_exclusive_group(required=True)
    g.add_argument("--key")
    g.add_argument("--device-key")
    s = sub.add_parser("sign")
    s.add_argument("file")
    s.add_argument("--key", required=True)
    s.add_argument("--out", required=True)
    v = sub.add_parser("verify")
    v.add_argument("files", nargs="+")
    v.add_argument("--keyring")
    v.add_argument("--allow-unsigned", action="store_true")
    try:
        a = ap.parse_args(argv)
    except SystemExit as ex:
        return EXIT["usage"] if ex.code else 0
    if a.what is None:
        ap.print_usage(sys.stderr)
        return EXIT["usage"]
    try:
        return {"export": cmd_export, "sign": cmd_sign, "verify": cmd_verify}[a.what](a) or 0
    except Refusal as ex:
        print(f"cft-sweep: refused {ex.name}: {ex.why}", file=sys.stderr)
        return EXIT.get(ex.name, 2)


if __name__ == "__main__":
    sys.exit(main())
