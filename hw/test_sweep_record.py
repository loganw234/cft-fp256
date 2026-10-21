#!/usr/bin/env python3
# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""Tests for hw/sweep_record.py: no card, no XRT, no network, throwaway keys only, made here.

    python3 hw/test_sweep_record.py [--metrics RUN_DIR_OR_FILE] [--only GROUP,...]

  forms    the canonical form and the id, the shape of each kind, each syntax refusal by name
  rules    the driver's counting rules against the verifier's, item by item, on parse_soak itself;
           the rate rule on thousands of rounded runs
  export   a synthetic run in the driver's own format (exhaustive and random slices, a finding, legs
           left out, a resume, records of types the exporter does not know) exported, signed and
           verified; the exporter's refusals
  keys     key files, the keyring, the device pseudonym, a key inside a working tree
  domain   a certificate's signature and a record's, on the committed certificate and a throwaway key:
           the certificate's own signature in a record line is `signature`; a certificate-domain
           signature over the record's own id is `signature-domain`; a record-domain signature over
           the certificate's body hash is refused `signature` by the certificate reader; and, as a
           function call only, the committed signature over that hash given as an id is `signature-domain`
  plants   one defect each put into a signed file, and the refusal it must draw, by name; and the
           verifier without a check, which lets its plant through
  real     (needs --metrics) the same on a copy of a real run's metrics.jsonl, every field read back
           from the raw legs by code that does not share the exporter's

Every key here is derived from a fixed label or made by `cft_sign.py keygen` in a temporary directory
this script makes and removes by that exact path: a throwaway, never anyone's. Prints a line a group and
a last line "sweep-record test: N checks, F failed, S skipped".
"""
from __future__ import annotations

import collections
import contextlib
import hashlib
import json
import os
import random
import shutil
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
# ROOT holds docs/, certificates/ and python/. SWEEP_RECORD_TEST_ROOT names it for a copy of this test run from another directory (the driver's
# test runs it from a plant's copy of the code, which has none of them beside it); the module and the library imported are HERE's.
ROOT = os.environ.get("SWEEP_RECORD_TEST_ROOT") or os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "python"))
import card_stress_lib as L  # noqa: E402
import cft_sign  # noqa: E402
import sweep_record as S  # noqa: E402
from cft_golden import cert, cert2, ed25519  # noqa: E402

POSIX = os.name == "posix"
SCRIPT = os.path.join(HERE, "sweep_record.py")
CHECKS, FAILS, SKIPS, SEEN = 0, [], [], set()      # SEEN: the refusals a check has watched fire
K = {}                                             # the throwaway keys, rings and paths, set by main


def check(name, ok, detail=""):
    global CHECKS
    CHECKS += 1
    if not ok:
        FAILS.append(f"{name}: {detail}")
        print(f"  FAIL  {name}  {detail}"[:400])
    return bool(ok)


def skip(name, why):
    SKIPS.append(f"{name}: {why}")
    print(f"  SKIP  {name} - {why}")


def refusal(fn, *a, **k):
    """The name of the Refusal fn raises, or None; any other exception is a defect, shown as what it drew."""
    try:
        fn(*a, **k)
    except S.Refusal as e:
        SEEN.add(e.name)
        return e.name
    except Exception as e:
        return f"uncaught {type(e).__name__}"
    return None


def red(label, want, fn, *a, **k):
    got = refusal(fn, *a, **k)
    return check(f"{label} -> refused {want}", got == want, f"drew {got!r}")


def cli(*args):
    p = subprocess.run([sys.executable, "-B", SCRIPT, *map(str, args)], capture_output=True, text=True, timeout=600)
    SEEN.update(w for w in S.REFUSALS if f"refused {w}:" in p.stderr)
    return p.returncode, p.stdout, p.stderr


def seed_of(label):
    return hashlib.sha256(b"sweep_record test key " + label.encode()).digest()


def write_key(path, label):
    with open(path, "xb") as f:
        f.write(cft_sign.key_text(seed_of(label)).encode("ascii"))
    if POSIX:
        os.chmod(path, 0o600)


@contextlib.contextmanager
def without(name, repl):
    """The verifier with one function replaced: a check taken out, to see its plant get through."""
    old = getattr(S, name)
    setattr(S, name, repl)
    try:
        yield
    finally:
        setattr(S, name, old)


# ---- a run in the driver's own format -----------------------------------------------------------

ITEMS = {it.name: it for it in L.sweep_items()}
IMG = {n: (hashlib.sha256(b"test image " + n.encode()).hexdigest(), t)
       for n, t in (("quad", 4), ("single", 1), ("deep", 1))}
C1, C2 = "1" * 40, "2" * 40
# The sha256 of the whole export of fake_run() below at 77c5dbca (DR3's merge, before version 2): unsigned for key A, then signed by it.
BASE_FAKE_RUN = ("e2922293f9f36a4878c503067383c778344520ecbc5b21f9ce3a3952663a7b38",
                 "4b4eb1bf091364ed4326cdcd71747a4c6bf068956311a4da153680aef7e7dcf9")
# The digest over the name and campaign id of every item of the catalog at 77c5dbca (the 125; the first 90 are DR3's b8555f2f...).
BASE_CAMPAIGN_DIGEST = "2e8d96089a143918556275f5321c28f3fd9e78cae8b6044fe4dd88fbe52536b2"


def fake_start(rid, commit=C1, dirty=False, dry=False, resumed=False, t=1792000000.0, host_tree=None):
    """host_tree: the keys DR2's driver adds to run_start.tree (host_src, host_src_dirty, cc, rtl, rtl_dirty), or none: a run that
    recorded none of them, as the 2026-10-19 run's first run_start."""
    return {"type": "run_start", "run_id": rid, "out": "out/" + rid, "host": "testhost", "argv": [],
            "settings": {"quick": False, "dry_run": dry},
            "tree": dict({"commit": commit, "dirty": dirty, "dirty_files": 0}, **(host_tree or {})),
            "images": {n: {"sha256": h, "bytes": 1, "tiles": k, "path": f"images/{n}.xclbin", "target": "t-" + n}
                       for n, (h, k) in IMG.items()},
            "deadline": None, "resumed": resumed, "v": 1, "ts": "2026-10-20 00:00:00", "epoch": t}


def fake_build(ok=True):
    return {"type": "build", "ok": ok, "steps": [{"name": "tree", "ok": ok, "detail": "x"}], "v": 1,
            "ts": "2026-10-20 00:00:01", "epoch": 1792000001.0}


def fake_leg(item, *, image="quad", lo=0, hi=1 << 20, count=1 << 20, seed=0x50AC0001, seed_n=0, tile=None, jobs=1,
             status="pass", vm=0, fm=0, dis=None, skipped=None, cases=None, t=1792000100.0, dur=2.0, log=True, n=1):
    it = ITEMS[item]
    sw = {"item": item, "tool": it.tool, "op": it.op, "mode": it.mode, "reach": it.reach}
    if it.kind == "exhaustive":
        nn, per = hi - lo, it.per_encoding
        c, s = (nn * (per or 1) + it.extra_cases, 0) if it.exact else (nn * per - nn * per // 3, nn * per // 3)
        c, s = (c if cases is None else cases), (s if skipped is None else skipped)
        counts = {"cases": c, "value_mismatches": vm, "flag_mismatches": fm}
        sw.update(lo=lo, hi=hi, tile=tile, jobs=jobs)
        if it.exact:
            sw["expected_cases"] = it.expected_cases(lo, hi)
        if per is not None:
            counts.update(encodings=nn, skipped=s)
            sw["expected_encodings"] = nn
    else:
        c = count if cases is None else cases
        counts = {"cases": c, "value_mismatches": vm, "flag_mismatches": fm}
        sw.update(count=count, seed=seed, seed_n=seed_n, tile=tile, jobs=jobs)
    host = image == "cpu"                                  # a host-pool leg (hw/card_stress.py run_host_slice): no image, no tile, the pool's mark
    if host:
        sw["pool"] = {"worker": 1, "host": "testhost", "build_id": "commit=" + "3" * 40 + " tracked=clean untracked=none"}
    done = status in ("pass", "fail")
    return {"type": "leg", "cycle": 1, "image": image, "image_sha256": None if host else IMG[image][0], "leg": "sweep-" + item,
            "kind": "sweep", "attempt": 1, "start": "2026-10-20 00:01:40", "end": "2026-10-20 00:01:42",
            "start_epoch": round(t, 3), "end_epoch": round(t + dur, 3), "duration_s": round(dur, 3),
            "rc": 0 if status == "pass" else 1, "status": status, "timed_out": status == "timeout", "killed": None,
            "counts": counts if done else None,
            "rate": {"value": round(c / dur, 3), "unit": "cases/s"} if done else None, "sweep": sw,
            "disagreements": (dis or []) if done else None,
            "log": f"logs/c0001-{n:05d}-sweep-{item}.log.gz" if log else None, "log_kept": "gz" if log else "none",
            "reason": None if done else status, "tile": tile, "extra": None, "argv": None, "v": 1,
            "ts": "2026-10-20 00:01:42", "epoch": t + dur}


def fake_run(rid="card-stress-test-1", t0=1792000000.0):
    """20 records: indices 2 to 11 and 18, 19 are finished sweep legs; 12 to 14 are not; 15 is a battery leg."""
    st = {"t": t0 + 10, "n": 0}

    def leg(item, **kw):
        st["t"] += 7
        st["n"] += 1
        return fake_leg(item, t=st["t"], n=st["n"], **kw)
    bad = ["MISMATCH sqrt32 a=0x3f800001 dev=0x3f800000 ref=0x3f800001", "FLAGS sqrt32 a=0x00000001"]
    return [fake_start(rid, t=t0), fake_build(),
            leg("sqrt32-rne", tile=1, jobs=4), leg("nextup32", tile=2, jobs=4, lo=1 << 20, hi=2 << 20),
            leg("scaleb32-all-rne", tile=3, jobs=4), leg("cvtto32-all-rne", tile=4, jobs=4, lo=1 << 20, hi=2 << 20),
            leg("cvtto32-all-rtz", image="single", skipped=4 << 20, cases=0),
            leg("conv32to64-all", image="deep"),
            leg("div32-rne", image="single"), leg("rem64", tile=1, jobs=4, seed=0xC5000000 + 40, seed_n=2),
            leg("scaleb64-rup", tile=2, jobs=2, count=5, seed=7919, seed_n=1),
            leg("sqrt32-rtz", lo=1 << 20, hi=2 << 20, status="fail", vm=1, fm=1, dis=bad),
            leg("sqrt32-rdn", status="timeout"), leg("sqrt32-rup", status="no_device"), leg("logb32", status="parse_error"),
            {"type": "leg", "kind": "battery", "leg": "api-test", "status": "pass", "counts": {"failed": 0}},
            fake_start(rid, commit=C2, resumed=True, t=st["t"] + 60), fake_build(),
            leg("rint32-rne", lo=2 << 20, hi=3 << 20), leg("class32", image="deep", lo=0, hi=1 << 20)]


def write_metrics(path, recs):
    with open(path, "wb") as f:
        for r in recs:
            f.write(json.dumps(r, separators=(",", ":")).encode() + b"\n")


def metrics_file(tmp, name="run1.jsonl", recs=None):
    path = os.path.join(tmp, name)
    if not os.path.exists(path):
        write_metrics(path, recs or fake_run())
    return path


def export(path, **kw):
    ex = S.Exporter(**kw)
    lines, partial = S.export_run(path, ex)
    return ex, lines, partial


def verify_lines(lines, ring=None, require=True):
    return S.verify_records(S.parse_file(b"".join(lines)), ring, require)


def verdict(lines, ring=None, require=True):
    """The refusal verifying these lines draws, or 'ok'."""
    return refusal(verify_lines, lines, ring, require) or "ok"


def edit(line, fn, fix_id=False):
    o = json.loads(line)
    fn(o)
    if fix_id:
        o["id"] = S.record_id(o)
    return S.canon(o) + b"\n"


def resign(line, fn, signer):
    """The line with fn applied and then signed afresh: a valid signature over changed content."""
    o = json.loads(line)
    fn(o)
    return S.canon(signer.sign({k: v for k, v in o.items() if k not in ("id", "sig")})) + b"\n"


def strip_sig(lines):
    return [S.canon({k: v for k, v in json.loads(ln).items() if k != "sig"}) + b"\n" for ln in lines]


def op_index(lines, op):
    """The index of the first record of the campaign whose operation is `op`; KeyError where there is none."""
    for ln in lines:
        c = json.loads(ln)
        if c["kind"] == "campaign" and c["operation"] == op:
            return next(n for n, m in enumerate(lines) if json.loads(m).get("cid") == c["id"])
    raise KeyError(op)


def campaign_line(lines, idx):
    cid = json.loads(lines[idx])["cid"]
    return next(ln for ln in lines if json.loads(ln)["id"] == cid)


def moved_legs(raw):
    """The finished sweep legs of `raw` whose run_start in force names another commit (or dirty flag) than the file's first run_start
    does: the legs a first-run_start expectation gets wrong, and no other."""
    key = lambda s: ((s.get("tree") or {}).get("commit"), (s.get("tree") or {}).get("dirty"))
    first = cur = None
    out = []
    for r in raw:
        if r["type"] == "run_start":
            cur = r
            first = first or r
        elif r["type"] == "leg" and r["kind"] == "sweep" and r["status"] in ("pass", "fail") and key(cur) != key(first):
            out.append(r["leg"])
    return out


def readback(raw, flat, device, first_only=False):
    """Every finished sweep leg of `raw` (a run's records, in file order) against its record in `flat` (the exported slices and streams,
    in the same order), field by field, by code that shares nothing with the exporter. A leg is held to the run_start IN FORCE for it:
    the last one before it in the file, because a resumed run writes one run_start for each invocation and the exporter stamps each
    slice with the one in force (the images, the run id and the tool's commit and dirty flag can differ between them; the 2026-10-19
    run's file has two, of different commits). first_only is the PLANT: the first run_start's for every leg, which is what this check
    did until 2026-10-21 and what it must go red on, for the legs after a resume. Returns [(the leg's name, the fields that differ)]."""
    cur, fin = None, []
    for r in raw:
        if r["type"] == "run_start":
            cur = cur if (first_only and cur is not None) else r
        elif r["type"] == "leg" and r["kind"] == "sweep" and r["status"] in ("pass", "fail"):
            fin.append((r, cur))
    if len(fin) != len(flat):
        return [("the number of finished legs and of records", [f"{len(fin)} legs, {len(flat)} records"])]
    bad = []
    for (leg, st), r in zip(fin, flat):
        sw, c, tr = leg["sweep"], leg["counts"], st.get("tree") or {}
        diff = []
        if "lo" in sw:
            diff += [k for k, v in (("lo", sw["lo"]), ("hi", sw["hi"])) if r.get(k) != v]
            diff += ["skipped"] if r.get("skipped") != c.get("skipped") else []
        else:
            diff += [k for k, v in (("seed", sw["seed"]), ("count", sw["count"])) if r.get(k) != v] + (["skipped"] if "skipped" in r else [])
        diff += [k for k, v in (("cases", c["cases"]), ("vm", c["value_mismatches"]), ("fm", c["flag_mismatches"])) if r.get(k) != v]
        if leg["image"] == "cpu":                        # a host-pool leg: version 2, the host build run_start.tree names
            want = {"src": tr.get("host_src")}
            if isinstance(tr.get("host_src_dirty"), bool):
                want["dirty"] = tr["host_src_dirty"]
            if isinstance(tr.get("cc"), str):
                want["cc"] = tr["cc"]
            diff += [k for k, ok in (("v", r["v"] == 2), ("subject", r["subject"] == want), ("image_sha256", leg["image_sha256"] is None)) if not ok]
        else:                                            # a card leg: version 1, the image run_start names and the tile the leg ran on
            im = st["images"][leg["image"]]
            want = dict({"image": leg["image"], "xclbin": leg["image_sha256"], "tiles": im["tiles"]},
                        **({} if sw["tile"] is None else {"tile": sw["tile"]}))
            diff += [k for k, ok in (("v", r["v"] == 1), ("subject", r["subject"] == want), ("image_sha256", leg["image_sha256"] == im["sha256"])) if not ok]
        run = {"id": st["run_id"], "device": device, "start_ms": round(leg["start_epoch"] * 1000), "end_ms": round(leg["end_epoch"] * 1000),
               "rate": round(leg["rate"]["value"])}
        if leg["log"]:
            run["log"] = leg["log"]
        diff += ["run"] if r["run"] != run else []
        tool = {"commit": tr["commit"], "dirty": tr["dirty"]} if isinstance(tr.get("commit"), str) and isinstance(tr.get("dirty"), bool) else None
        diff += ["tool"] if r.get("tool") != tool else []
        diff += ["finding"] if (not S.is_finding(r)) != (leg["status"] == "pass") else []
        if diff:
            bad.append((leg["leg"], diff))
    return bad


# ---- forms ----------------------------------------------------------------------------------------

def group_forms(tmp):
    check("canon: sorted keys, no spaces, integers", S.canon({"b": [1, True, "x"], "a": 0}) == b'{"a":0,"b":[1,true,"x"]}')
    for label, val in (("a float", 1.5), ("a null", None), ("an integer beyond 2^53-1", 1 << 53), ("a tuple", (1,))):
        try:
            S.canon({"x": val})
            check(f"canon refuses {label}", False)
        except ValueError:
            check(f"canon refuses {label}", True)
    check("canon: other than ASCII is written \\uXXXX", S.canon({"x": "\u00e9"}) == b'{"x":"\\u00e9"}')
    rec = {"v": 1, "kind": "x", "a": 1}
    check("record_id leaves out the id and the signature (hashlib)", S.record_id(dict(rec, id="0" * 64, sig={"k": 1})) ==
          S.record_id(rec) == hashlib.sha256(b'{"a":1,"kind":"x","v":1}').hexdigest())
    check("record_id changes with any field", S.record_id(dict(rec, a=2)) != S.record_id(rec))

    lines = export(metrics_file(tmp), public=K["pub_a"])[1]
    base = lines[0].rstrip(b"\n")                                   # a campaign record
    obj = json.loads(base)
    check("a campaign's id is the SHA-256 of its canonical bytes without the id (hashlib, not the module)",
          obj["id"] == hashlib.sha256(json.dumps({k: v for k, v in obj.items() if k != "id"}, sort_keys=True,
                                                 separators=(",", ":")).encode()).hexdigest())
    check("a canonical line reads back", S.read_record_line(base, 1) == obj)

    def raw(**ch):
        return json.dumps(dict(obj, **ch), sort_keys=True, separators=(",", ":")).encode()
    nov = json.dumps({k: v for k, v in obj.items() if k != "v"}, sort_keys=True, separators=(",", ":")).encode()
    for label, line, want in (
            ("spaces after the separators", json.dumps(obj, sort_keys=True).encode(), "canonical"),
            ("keys out of order", json.dumps(dict(reversed(list(obj.items()))), separators=(",", ":")).encode(), "canonical"),
            ("a line ending in CR (a CRLF file)", base + b"\r", "canonical"),
            ("a trailing space", base + b" ", "canonical"),
            ("a byte beyond ASCII", base.replace(b"tile", "t\u00efle".encode()), "canonical"),
            ("an empty line", b"", "canonical"),
            ("a float where the form has an integer", raw(space=4294967296.0), "form"),
            ("NaN", base[:-1] + b',"x":NaN}', "form"),
            ("a key twice", base[:-1] + b',"v":1}', "form"),
            ("a null", raw(attribute=None), "form"),
            ("not an object", b"[1]", "form"),
            ("no version", nov, "form"),
            ("a version that is a string", raw(v="1"), "form"),
            ("a version that is a bool", raw(v=True), "form"),
            ("version 3 (version 2 is known since 2026-10-21: the host-pool slice)", raw(v=3), "version"),
            ("version 0", raw(v=0), "version"),
            ("a negative version", raw(v=-1), "version")):
        red(f"line: {label}", want, S.read_record_line, line, 1)
    check("a line of version 2 reads, as a line: version 2 is known", S.read_record_line(raw(v=2), 1)["v"] == 2)
    red("a file whose last line has no LF", "canonical", S.parse_file, b"".join(lines)[:-1])
    red("an empty file", "empty", S.parse_file, b"")
    red("a record whose bytes do not hash to its id", "id", S.parse_file, edit(lines[0], lambda o: o.update(space=1)))
    signed = export(metrics_file(tmp), signer=K["signer_a"])[1]
    stale = [(n + 1, json.loads(ln)) for n, ln in enumerate(signed)]
    stale[1][1]["cases"] += 1                # handed to verify_records directly, parse_file never having seen it
    red("verify_records re-checks every id itself, for a caller that did not go through parse_file", "id", S.verify_records, stale, K["ring_a"])

    sl = json.loads(lines[1])
    for label, fn in (
            ("a field of the study that version 1 does not have (digest)", lambda o: o.update(digest={"alg": "x"})),
            ("a missing field", lambda o: o.pop("vm")),
            ("a bool where an integer goes", lambda o: o.update(cases=True)),
            ("a string where an integer goes", lambda o: o.update(cases="5")),
            ("a negative count", lambda o: o.update(vm=-1)),
            ("an integer beyond 2^53-1", lambda o: o.update(cases=1 << 53)),
            ("an uppercase hex id", lambda o: o.update(cid=o["cid"].upper())),
            ("a log path that is absolute", lambda o: o["run"].update(log="/var/x/a.log")),
            ("a log path with a drive", lambda o: o["run"].update(log="C:/x/a.log")),
            ("a log path that leaves the run directory", lambda o: o["run"].update(log="../a.log")),
            ("a tile past the image's tiles", lambda o: o["subject"].update(tile=5)),
            ("an empty interval", lambda o: o.update(lo=o["hi"])),
            ("a signature that is no ed25519", lambda o: o.update(sig={"alg": "rsa", "key": "0" * 64, "sig": "0" * 128})),
            ("a nested field that is not in the form (a host name)", lambda o: o["run"].update(host="some-host"))):
        o = json.loads(json.dumps(sl))
        fn(o)
        red(f"shape: {label}", "form", S.check_shape, o, "x")
    rows = {}                                  # the document's table of refusals, read as text
    in_table = False
    for ln in open(os.path.join(ROOT, "docs", "SWEEP-RECORDS.md"), encoding="utf-8").read().splitlines():
        in_table = ln.startswith("## The refusals, by name") or (in_table and not ln.startswith("## "))
        cells = [c.strip() for c in ln.split("|")]
        if in_table and len(cells) > 3 and cells[1].startswith("`") and cells[2].isdigit():
            rows[cells[1].strip("`")] = int(cells[2])
    check("the refusals table of docs/SWEEP-RECORDS.md names exactly the module's refusals, with their exit codes",
          rows == {n: S.EXIT.get(n, 2) for n in S.REFUSALS}, f"document {sorted(rows)} module {sorted(S.REFUSALS)}")
    doc = open(os.path.join(ROOT, "docs", "SWEEP-RECORDS.md"), encoding="utf-8").read()
    ex_line = next(ln for ln in doc.splitlines() if ln.startswith('{"args":"op lo hi","exact":true,"kind":"campaign"'))
    cb = S.campaign_body(ITEMS["conv32to64-all"])
    check("the document's example campaign is conv32to64-all's campaign record, and its sha256 is the cid the document gives",
          json.loads(ex_line) == cb and S.canon(cb).decode() == ex_line and
          hashlib.sha256(ex_line.encode()).hexdigest() in doc and S.record_id(cb) == hashlib.sha256(ex_line.encode()).hexdigest())
    camp = json.loads(lines[0])
    for label, fn in (("an exhaustive campaign without its space", lambda o: o.pop("space")),
                      ("a random campaign that has a space", lambda o: o.update(sweep="random")),
                      ("args that are not the campaign's form", lambda o: o.update(args="op count seed")),
                      ("a campaign with a signature", lambda o: o.update(sig={"alg": "ed25519", "key": "0" * 64, "sig": "0" * 128}))):
        o = json.loads(json.dumps(camp))
        fn(o)
        red(f"shape: {label}", "form", S.check_shape, o, "x")


# ---- rules ----------------------------------------------------------------------------------------

def driver_accepts(it, lo, hi, cases, skipped):
    """What card_stress_lib.parse_soak says of this slice's verdict line, for the item's own rule."""
    n = hi - lo
    text = f"{it.op} {it.verdict_mode}: {cases} cases, 0 value mismatches, 0 flag mismatches" + (
        f", {n} encodings, {skipped} skipped" if it.per_encoding is not None else "")
    try:
        L.parse_soak(text, 0, it.op, it.verdict_mode, None, it.expected_cases(lo, hi), it.cover_spec(lo, hi))
        return True
    except L.VerdictError:
        return False


def group_rules(tmp):
    rng = random.Random(20261020)
    disagree, grid = [], 0
    for it in ITEMS.values():
        camp = S.campaign_body(it)
        if it.kind == "exhaustive":
            for n in (1, 3, 1 << 20):
                if 5 + n > it.space:
                    continue    # past the item's own space (a campaign says it since 2026-10-21): the verifier refuses it, parse_soak has no space
                per = it.per_encoding
                good = n * (per or 1) + it.extra_cases
                tries = [(good, 0), (good - 1, 0), (good + 1, 0), (good, 1), (good - 1, 1), (0, 0)]
                if per is not None:
                    full = per * n
                    tries += [(full - s, s) for s in (0, 1, n, full)] + [(full - 3, 2), (full, 0), (full + 1, 0)]
                for cases, skipped in tries:
                    if cases < 0 or (per is None and skipped):
                        continue                      # no clause is printed: nothing to carry
                    rec = {"kind": "slice", "lo": 5, "hi": 5 + n, "cases": cases}
                    if per is not None:
                        rec["skipped"] = skipped
                    grid += 1
                    if (S.counts_problem(camp, rec) is None) != driver_accepts(it, 5, 5 + n, cases, skipped):
                        disagree.append((it.name, n, cases, skipped))
        else:
            for cases in (0, 1, 7, 1 << 20):
                grid += 1
                line = f"{it.op} {it.verdict_mode}: {cases} cases, 0 value mismatches, 0 flag mismatches"
                try:
                    L.parse_soak(line, 0, it.op, it.verdict_mode, None, None, None)
                    drv = True
                except L.VerdictError:
                    drv = False
                if (S.counts_problem(camp, {"kind": "stream", "cases": cases}) is None) != drv:
                    disagree.append((it.name, cases))
    check(f"the verifier's counting rule agrees with parse_soak on {grid} (item, interval, cases, skipped) points of "
          f"{len(ITEMS)} items", not disagree, str(disagree[:3]))
    print(f"  rules: {grid} points over {len(ITEMS)} items, {len(disagree)} disagreements")
    check("nextup32's campaign carries its 8 extra cases; cvtto32-all's is not exact and takes 4 checks an encoding",
          S.campaign_body(ITEMS["nextup32"])["extra_cases"] == 8 and S.campaign_body(ITEMS["cvtto32-all-rne"])["exact"] is False
          and S.campaign_body(ITEMS["cvtto32-all-rne"])["per_encoding"] == 4)

    def driver_run(cases, dur):                   # what finish_leg writes, and the record keeps
        t0 = rng.uniform(1.79e9, 1.80e9)
        s, e = round(t0, 3), round(t0 + dur, 3)
        return {"kind": "slice", "cases": cases, "run": {"start_ms": int(round(s * 1000)), "end_ms": int(round(e * 1000)),
                                                          "rate": int(round(round(cases / dur, 3)))}}
    refused = sum(S.run_problem(driver_run(rng.randrange(1, 10 ** 12), rng.uniform(0.01, 4000))) is not None for _ in range(20000))
    check("the rate rule accepts 20,000 driver-rounded runs (cases to 10^12, durations 10 ms to 4,000 s)", refused == 0, f"{refused} refused")
    accepted = 0
    for _ in range(2000):
        rec = driver_run(rng.randrange(10 ** 6, 10 ** 12), rng.uniform(0.2, 4000))
        rec["run"]["rate"] = int(rec["run"]["rate"] * 1.02) + 2
        accepted += S.run_problem(rec) is None
    check("the rate rule refuses a rate 2% too high on 2,000 runs", accepted == 0, f"{accepted} accepted")
    check("the rate rule refuses an end before the start",
          S.run_problem({"cases": 100, "run": {"start_ms": 5000, "end_ms": 4999}}) is not None)
    check("the rate rule refuses a rate over 1 ms, which the times cannot hold",
          S.run_problem({"cases": 100, "run": {"start_ms": 5000, "end_ms": 5001, "rate": 100000}}) is not None)


# ---- export -----------------------------------------------------------------------------------------

FORBIDDEN = ("digest", "control", "oracle", "stratum", "rtl", "abi", "cc", "flags", "build_id", "libm", "cpu", "probes")


def group_export(tmp):
    path = metrics_file(tmp)
    pub, signer = K["pub_a"], K["signer_a"]
    ex, lines, partial = export(path, public=pub)
    recs = [json.loads(ln) for ln in lines]
    kinds = collections.Counter(r["kind"] for r in recs)
    check("export: 9 slices, 3 streams and 12 campaigns from 12 finished sweep legs",
          kinds == {"slice": 9, "stream": 3, "campaign": 12} and ex.legs == 12, str(kinds))
    check("export: the sweep legs not finished are counted by status; the battery leg is not a sweep leg",
          ex.left == {"timeout": 1, "no_device": 1, "parse_error": 1}, str(ex.left))
    check("export: one finding", ex.findings == 1)
    dev = hashlib.sha256(b"cft-sweep-device 1\x00" + pub).hexdigest()[:16]
    flat = [r for r in recs if r["kind"] != "campaign"]
    check("every record names the device of the key (hashlib)", all(r["run"]["device"] == dev for r in flat))
    check("no field the data cannot fill, no null: a slice has none of the study's digest, control, oracle, stratum, rtl, abi ...; "
          "a campaign has no stratum or enumeration", not any(k in r for r in flat for k in FORBIDDEN) and
          not any(k in r for r in recs if r["kind"] == "campaign" for k in ("stratum", "enumeration")) and
          all(v is not None for r in recs for v in r.values()))
    by = {r["id"]: r for r in recs if r["kind"] == "campaign"}
    check("every record names a campaign in the file, and a campaign's id is the hash of its bytes", all(r["cid"] in by for r in flat)
          and all(c["id"] == hashlib.sha256(json.dumps({k: v for k, v in c.items() if k != "id"}, sort_keys=True,
                                                       separators=(",", ":")).encode()).hexdigest() for c in by.values()))
    o = {by[r["cid"]]["operation"] + ("-" + by[r["cid"]]["attribute"] if "attribute" in by[r["cid"]] else ""): r for r in flat}
    check("skipped only where the verdict line has it: scaleb32-all 0, cvtto32-all its pairs, none for sqrt32 or a stream",
          o["scaleb32-all-rne"]["skipped"] == 0 and o["cvtto32-all-rne"]["skipped"] > 0 and o["cvtto32-all-rtz"]["cases"] == 0
          and "skipped" not in o["sqrt32-rne"] and "skipped" not in o["div32-rne"])
    check("nextup32's 8 edge cases are in its cases", o["nextup32"]["cases"] == (1 << 20) + 8)
    check("tile absent where the leg recorded none, present where it did", "tile" not in o["conv32to64-all"]["subject"] and
          o["sqrt32-rne"]["subject"]["tile"] == 1 and o["sqrt32-rne"]["subject"]["tiles"] == 4)
    check("a stream carries seed and count, no interval", {"seed", "count"} <= set(o["rem64"]) and "lo" not in o["rem64"]
          and o["rem64"]["seed"] == 0xC5000000 + 40)
    check("the three images are told apart", {o["sqrt32-rne"]["subject"]["image"], o["conv32to64-all"]["subject"]["image"],
                                              o["div32-rne"]["subject"]["image"]} == {"quad", "deep", "single"})
    check("the tool's commit follows the resume's run_start", o["sqrt32-rne"]["tool"]["commit"] == C1 and
          o["rint32-rne"]["tool"]["commit"] == C2 and o["sqrt32-rne"]["tool"]["dirty"] is False)
    # the read-back every `--metrics` run does on a real file, here on the synthetic one, in every run of the suite (found 2026-10-21: the
    # real run's file has two run_starts, and a check that took the FIRST for every leg failed the legs of the second; SG's test, not a regression)
    raw0, dev0 = fake_run(), S.device_of(pub)
    check("readback: every record equals its raw leg, field by field, each against the run_start in force for it: this file has two run_starts, "
          "of commits C1 and C2 (a resume's), and the legs after the second carry C2", readback(raw0, flat, dev0) == [] and moved_legs(raw0) == ["sweep-rint32-rne", "sweep-class32"])
    planted = readback(raw0, flat, dev0, first_only=True)
    check("readback, the plant: the first run_start's expectation for every leg is red on this file, at the two legs after the resume and on the tool's "
          "commit alone (so the check can fail, and for the reason it is there)",
          [b[0] for b in planted] == moved_legs(raw0) and all(b[1] == ["tool"] for b in planted), str(planted))
    wrong = json.loads(json.dumps(flat))
    wrong[0]["subject"]["tiles"] = 7
    wrong[-1]["tool"]["commit"] = C1
    names = [r["leg"] for r in raw0 if r["type"] == "leg" and r["kind"] == "sweep" and r["status"] in ("pass", "fail")]
    check("readback: a wrong tile count on the first record and the first run_start's commit on the last are each found, and nothing else",
          readback(raw0, wrong, dev0) == [(names[0], ["subject"]), (names[-1], ["tool"])], str(readback(raw0, wrong, dev0)))
    f = o["sqrt32-rtz"]
    check("the finding is a record that says what it found, and the only finding",
          S.is_finding(f) and len(f["disagreements"]) == 2 and sum(S.is_finding(r) for r in flat) == 1)
    r0 = o["sqrt32-rne"]["run"]
    check("times are the epochs in ms, the rate the leg's, the log the leg's", (r0["start_ms"], r0["end_ms"], r0["rate"]) ==
          (1792000017000, 1792000019000, (1 << 20) // 2) and r0["log"] == "logs/c0001-00001-sweep-sqrt32-rne.log.gz")
    rep = verify_lines(lines, None, False)
    check("the unsigned file verifies, with --allow-unsigned, as one run", (rep["slices"], rep["streams"], rep["clean"],
          len(rep["findings"]), rep["unsigned"], rep["run"]) == (9, 3, 11, 1, 12, "card-stress-test-1"), str(rep["slices"]))
    check("a finding is not clean, and its cases are not among the cases in clean records",
          rep["cases"] == sum(r["cases"] for r in flat if not S.is_finding(r)))
    red("unsigned records where signatures are required", "signature", verify_lines, lines)

    ex2, lines2, _ = export(path, signer=signer)
    check("a signed file verifies with the keyring naming the key", verdict(lines2, K["ring_a"]) == "ok")
    check("version 1 is byte for byte what it was at 77c5dbca, before version 2: this synthetic run's whole export (12 slices and streams, "
          "12 campaigns), unsigned for key A and signed by it, hashes to what the base's code gave (MEASURED at 77c5dbca, "
          "scratch/digest_fake_run.py), and none of its records is version 2",
          (len(lines), hashlib.sha256(b"".join(lines)).hexdigest(), len(lines2), hashlib.sha256(b"".join(lines2)).hexdigest()) ==
          (24,) + BASE_FAKE_RUN[:1] + (24,) + BASE_FAKE_RUN[1:] and all(json.loads(ln)["v"] == 1 for ln in lines))
    check("export is deterministic: the same run and key give the same bytes",
          export(path, signer=signer)[1] == lines2 and export(path, public=pub)[1] == lines)
    unk = [{"type": "event", "event": "sweep_empty", "detail": "nothing left", "v": 1, "ts": "x", "epoch": 1.0},
           {"type": "frobnicate", "x": [1, {"y": None}], "v": 9}, {"type": "telemetry", "v": 1}, {"type": "cycle_start", "cycle": 1},
           {"type": "leg", "kind": "future", "status": "pass", "sweep": {"item": "nope"}}, {"type": "run_end", "reason": "deadline"}]
    good = fake_run()
    write_metrics(os.path.join(tmp, "unknown.jsonl"), good[:6] + unk[:3] + good[6:] + unk[3:])
    exu, lu, _ = export(os.path.join(tmp, "unknown.jsonl"), public=pub)
    check("records and events of types the exporter does not know are ignored without error: the same lines", lu == lines and
          exu.left == ex.left)
    legacy = json.loads(json.dumps(good))
    for r in legacy:
        for k in ("reach", "expected_cases", "expected_encodings", "jobs"):
            (r.get("sweep") or {}).pop(k, None)
    write_metrics(os.path.join(tmp, "legacy.jsonl"), legacy)
    check("legs without the keys later parcels added (reach, expected_cases, expected_encodings, jobs) export to the same records",
          export(os.path.join(tmp, "legacy.jsonl"), public=pub)[1] == lines)
    os.makedirs(os.path.join(tmp, "rundir"))
    shutil.copy(path, os.path.join(tmp, "rundir", "metrics.jsonl"))
    check("a run directory is read as its metrics.jsonl", export(os.path.join(tmp, "rundir"), public=pub)[1] == lines)

    out, outs, outs2 = (os.path.join(tmp, n) for n in ("cli-unsigned.jsonl", "cli-signed.jsonl", "cli-signed2.jsonl"))
    rc, so, se = cli("export", path, "--out", out, "--device-key", pub.hex())
    check("CLI export --device-key exits 0 and writes the unsigned lines", rc == 0 and open(out, "rb").read() == b"".join(lines), se[-200:])
    rc, so, se = cli("export", path, "--out", outs, "--key", K["key_a"])
    check("CLI export --key exits 0 and writes the signed lines", rc == 0 and open(outs, "rb").read() == b"".join(lines2), se[-200:])
    rc, so, se = cli("sign", out, "--key", K["key_a"], "--out", outs2)
    check("sign after export equals export --key, byte for byte", rc == 0 and open(outs2, "rb").read() == b"".join(lines2), se[-200:])
    rc, so, se = cli("verify", outs, "--keyring", K["ring_a_path"])
    check("verify: a file with a finding verifies, says FINDING and 'never coverage', and exits 3",
          rc == 3 and "FINDING" in so and "never coverage" in so and "held by test%20key%20A" in so, f"rc {rc} {so[-300:]}")
    rc, so, se = cli("verify", out)
    check("verify without --allow-unsigned refuses an unsigned file by name, exit 2", rc == 2 and "refused signature" in se)
    rc, so, se = cli("verify", out, "--allow-unsigned")
    check("verify --allow-unsigned says UNSIGNED, and exits 3 for the finding", rc == 3 and "UNSIGNED" in so)
    rc, so, se = cli("export", path, "--out", out, "--key", K["key_a"])
    check("export never overwrites an output file: refused output, exit 73", rc == 73 and "refused output" in se)
    rc, so, se = cli("verify", os.path.join(tmp, "no-such-file"))
    check("verify of a missing file: refused usage, exit 64", rc == 64 and "refused usage" in se)
    rc, so, se = cli("export", path, "--out", os.path.join(tmp, "x.jsonl"), "--device-key", "01" + "00" * 31)
    check("a --device-key of small order: refused usage, exit 64", rc == 64 and "refused usage" in se)
    check("no files to verify: usage, exit 64", cli("verify")[0] == 64)

    # the exporter's refusals, each a `metrics` or `empty`, each on the run altered in one way
    def mut(i, fn):
        r = json.loads(json.dumps(good))
        fn(r[i])
        return r
    cases = (
        ("a dry run", mut(0, lambda r: r["settings"].update(dry_run=True))),
        ("a leg with no build record before it", good[:1] + good[2:]),
        ("a failed build record", mut(1, lambda r: r.update(ok=False))),
        ("an item the catalog does not have", mut(2, lambda r: r["sweep"].update(item="sqrt32-nope"))),
        ("a leg whose op is not its item's", mut(2, lambda r: r["sweep"].update(op="sqrt64"))),
        ("a leg whose expected cases are not the catalog's", mut(2, lambda r: r["sweep"].update(expected_cases=5))),
        ("a leg whose reach is not the item's", mut(2, lambda r: r["sweep"].update(reach="host"))),
        ("a leg of an image run_start does not have", mut(2, lambda r: r.update(image="octo"))),
        ("a leg whose image hash is not run_start's", mut(2, lambda r: r.update(image_sha256="e" * 64))),
        ("counts that break the rule (not a leg this driver passed)", mut(2, lambda r: r["counts"].update(cases=5))),
        ("a pass that counted a mismatch", mut(2, lambda r: r["counts"].update(value_mismatches=1))),
        ("a fail that counted none", mut(11, lambda r: r["counts"].update(value_mismatches=0, flag_mismatches=0))),
        ("a start time that is no number", mut(2, lambda r: r.update(start_epoch="x"))),
        ("a run id with no version-1 spelling", mut(0, lambda r: r.update(run_id="a b"))),
        ("a log path that is absolute", mut(2, lambda r: r.update(log="/var/x/y.log"))),
        ("a second run in the file", good[:3] + [fake_start("card-stress-test-2"), fake_build(), good[3]]),
        # VSG's (b)-3: each of these was dropped with rc 0 or an uncaught OverflowError before bc962f4's follow-up
        ("a pass leg whose counts are null", mut(2, lambda r: r.update(counts=None))),
        ("a fail leg whose counts are null", mut(11, lambda r: r.update(counts=None))),
        ("a pass sweep leg with no sweep block", mut(2, lambda r: r.pop("sweep"))),
        ("a fail sweep leg whose sweep block is null", mut(11, lambda r: r.update(sweep=None))),
        ("a rate that is Infinity", mut(2, lambda r: r["rate"].update(value=float("inf")))),
        ("a start time that is Infinity", mut(2, lambda r: r.update(start_epoch=float("inf")))),
        ("an end time that is -Infinity", mut(2, lambda r: r.update(end_epoch=float("-inf")))),
        ("a rate that is NaN (refused before)", mut(2, lambda r: r["rate"].update(value=float("nan")))),
        ("a start time that is NaN (refused before)", mut(2, lambda r: r.update(start_epoch=float("nan")))))
    for n, (label, recs) in enumerate(cases):
        p = os.path.join(tmp, f"bad{n}.jsonl")
        write_metrics(p, recs)
        red(f"export: {label}", "metrics", export, p, public=pub)
    for n, label in ((len(cases) - 9, "null counts"), (len(cases) - 7, "no sweep block"), (len(cases) - 5, "a rate of Infinity")):
        rc, so, se = cli("export", os.path.join(tmp, f"bad{n}.jsonl"), "--out", os.path.join(tmp, f"bad{n}.out"), "--device-key", pub.hex())
        check(f"CLI export of a pass leg with {label}: refused metrics, exit 2, no traceback, nothing written",
              rc == 2 and "refused metrics" in se and "Traceback" not in se and not os.path.exists(os.path.join(tmp, f"bad{n}.out")),
              f"rc {rc} {se[-160:]}")
    unfinished = mut(12, lambda r: r.pop("sweep"))
    write_metrics(os.path.join(tmp, "unfinished.jsonl"), unfinished)
    exf = export(os.path.join(tmp, "unfinished.jsonl"), public=pub)
    check("control: a sweep leg that did not finish is counted as left out, whatever blocks it lacks, and is no refusal",
          exf[0].left == ex.left and exf[1] == lines)
    red("a finite-number check on a time that is Infinity", "metrics", S._ms, float("inf"), "start_epoch")
    red("a finite-number check on a time that is NaN", "metrics", S._ms, float("nan"), "start_epoch")
    check("a finite-number check keeps a finite time as the epoch in ms", S._ms(1792000017.0, "t") == 1792000017000)
    for label, what in (("a record that is no dict", [1, 2]), ("a run id that is no string", {"run_id": ["x"], "images": {}}),
                        ("images that are no dict", {"run_id": "x", "images": []})):
        red(f"run_start given {label}", "metrics", S.Exporter(public=pub).run_start, what)
    p = os.path.join(tmp, "alltimeout.jsonl")
    write_metrics(p, [good[0], good[1], good[12]])
    red("export: a run whose sweep legs all timed out", "empty", export, p, public=pub)
    with open(os.path.join(tmp, "torn.jsonl"), "wb") as f:
        f.write(b"".join(json.dumps(r, separators=(",", ":")).encode() + b"\n" for r in good[:4]) + b'{"type":"leg","sta')
    ext, lt, partial = export(os.path.join(tmp, "torn.jsonl"), public=pub)
    check("a torn last line is no record, and is said", partial and ext.legs == 2)
    with open(os.path.join(tmp, "garbled.jsonl"), "wb") as f:
        f.write(b"{not json}\n" + json.dumps(good[0]).encode() + b"\n")
    red("export: a metrics line that does not parse", "metrics", export, os.path.join(tmp, "garbled.jsonl"), public=pub)
    with open(os.path.join(tmp, "array.jsonl"), "wb") as f:
        f.write(b"[1,2]\n")
    red("export: a metrics line that is no JSON object", "metrics", export, os.path.join(tmp, "array.jsonl"), public=pub)
    exh = S.Exporter(public=pub)
    exh.run_start(good[0])
    exh.build(good[1])
    bad = json.loads(json.dumps(good[3]))
    bad["counts"]["cases"] = 5
    red("a leg that cannot be a record", "metrics", exh.leg, bad)
    again = exh.leg(good[3])
    check("a refusal leaves the exporter as it was: the next good leg still brings its campaign", len(again) == 2 and exh.legs == 1)


# ---- keys -----------------------------------------------------------------------------------------

def group_keys(tmp):
    pa, pb = K["pub_a"], K["pub_b"]
    check("the temporary directory is outside every working tree", S.key_in_tree(tmp) is None, str(S.key_in_tree(tmp)))
    d = hashlib.sha256(b"cft-sweep-device 1\x00" + pa).hexdigest()[:16]
    check("the device pseudonym is 16 hex of SHA-256('cft-sweep-device 1', NUL, the key), and keys differ in it (hashlib)",
          S.device_of(pa) == d and S.device_of(pa) != S.device_of(pb) and len(d) == 16)
    check("a key file made from a seed loads, and its public key is the signer's", ed25519.public_key(S.load_seed(K["key_a"])) == pa)
    gen = os.path.join(tmp, "gen.key")
    with contextlib.redirect_stdout(open(os.devnull, "w")):          # keygen prints the public key
        made = cft_sign.main(["keygen", "--out", gen])
    check("keygen of cft_sign.py, the documented way, makes a key this tool signs with (and a new device)",
          made == 0 and S.Signer(S.load_seed(gen)).device != S.device_of(pa))
    tree = os.path.join(tmp, "faketree")
    os.makedirs(os.path.join(tree, ".git"))
    os.makedirs(os.path.join(tree, "keys"))
    os.makedirs(os.path.join(tmp, "outside"))
    inside, outside = os.path.join(tree, "keys", "k.key"), os.path.join(tmp, "outside", "k.key")
    write_key(inside, "A")
    write_key(outside, "A")
    red("a valid key file inside a working tree (a .git directory above it)", "key-in-tree", S.load_seed, inside)
    check("the same key outside every tree is read", S.load_seed(outside) == seed_of("A"))
    wt = os.path.join(tmp, "worktree")
    os.makedirs(os.path.join(wt, "k"))
    with open(os.path.join(wt, ".git"), "w") as f:
        f.write("gitdir: elsewhere\n")
    write_key(os.path.join(wt, "k", "k.key"), "A")
    red("a key inside a linked worktree (.git is a file)", "key-in-tree", S.load_seed, os.path.join(wt, "k", "k.key"))
    red("a path inside this repository is refused before it is read (CLAUDE.md is no key file)", "key-in-tree", S.load_seed,
        os.path.join(ROOT, "CLAUDE.md"))
    o = os.path.join(tmp, "never.jsonl")
    rc, so, se = cli("export", metrics_file(tmp), "--out", o, "--key", inside)
    check("CLI: export --key with a key in a working tree: refused key-in-tree, exit 64, nothing written",
          rc == 64 and "refused key-in-tree" in se and not os.path.exists(o), se[-200:])
    rc, so, se = cli("sign", metrics_file(tmp), "--key", os.path.join(ROOT, "CLAUDE.md"), "--out", o)
    check("CLI: sign --key with a path in this repository: refused key-in-tree, nothing written",
          rc == 64 and "refused key-in-tree" in se and not os.path.exists(o))
    junk = os.path.join(tmp, "junk.key")
    with open(junk, "w") as f:
        f.write("not a key\n")
    red("a file that is no key file", "key-file", S.load_seed, junk)
    red("a key file that is missing", "key-file", S.load_seed, os.path.join(tmp, "missing.key"))
    wrong = os.path.join(tmp, "wrong.key")
    with open(wrong, "w", newline="\n") as f:
        f.write(cft_sign.key_text(seed_of("A")).replace(pa.hex(), pb.hex()))
    red("a key file whose key line is not its seed's public key", "key-file", S.load_seed, wrong)
    if POSIX:
        loose = os.path.join(tmp, "loose.key")
        write_key(loose, "A")
        os.chmod(loose, 0o644)
        red("a key file that others may read (POSIX)", "key-file", S.load_seed, loose)
    else:
        skip("a key file that others may read", "Windows permissions are ACLs that a mode does not show; cft_sign.py does not check them either")
    check("a keyring in cft_sign's format reads", S.read_keyring(K["ring_a_path"]) == {pa.hex(): "test key A"})
    for n, (label, body) in enumerate((("a line that is no keyring line", b"hello\n"),
                                       ("a key twice", f"key {pa.hex()} a\n".encode() * 2),
                                       ("a key of small order", b"key " + b"01" + b"00" * 31 + b" nobody\n"))):
        p = os.path.join(tmp, f"bad{n}.ring")
        with open(p, "wb") as f:
            f.write(body)
        red(f"keyring: {label}", "signer", S.read_keyring, p)
    red("a keyring that is missing", "usage", S.read_keyring, os.path.join(tmp, "missing.ring"))


# ---- domain -----------------------------------------------------------------------------------------

def group_domain(tmp):
    cpath = os.path.join(ROOT, "certificates", "signed-fp64", "signed-fp64.cert")
    data, sigfile = open(cpath, "rb").read(), open(cpath + ".sig", "rb").read()
    h = cert2.body_hash_of(data)
    committed_key = cert2.check_signature_file(data, sigfile)
    check("control: the committed certificate's own signature verifies as a certificate's", len(committed_key) == 64)
    check("the two domain strings differ, in content and in length", S.TAG_RECORD != cert2.TAG_SIGNATURE and
          len(S.TAG_RECORD) != len(cert2.TAG_SIGNATURE))
    seed, pub = seed_of("A"), K["pub_a"]
    # a record's signature, taken for a certificate's: the key's record-domain signature over the certificate's body hash
    forged = (f"cft-signature 1\nscheme ed25519\nkey {pub.hex()}\ncertificate {h}\nsignature "
              f"{ed25519.sign(seed, S.TAG_RECORD + bytes.fromhex(h)).hex()}\n").encode()
    try:
        cert2.check_signature_file(data, forged)
        check("a record-domain signature presented as the certificate's is refused by the certificate reader", False)
    except cert.Refusal as e:
        check("a record-domain signature presented as the certificate's is refused by the certificate reader (signature)",
              e.name == "signature", e.name)
    check("control: the same key's certificate-domain signature over that hash is accepted",
          cert2.check_signature_file(data, cert2.signature_file(seed, data)) == pub.hex())
    # a certificate's signature in a record FILE. The committed signature signs the certificate's body hash, so on a record
    # line, whose id is the hash of its own bytes, it verifies under neither domain: `signature`, not `signature-domain`
    key_hex, _cert_hex, sig_hex = cert2.read_signature_file(sigfile)
    lines = export(metrics_file(tmp), public=pub)[1]
    certsig = lambda o: o.update(sig={"alg": "ed25519", "key": key_hex, "sig": sig_hex})
    red("a record line whose sig is the committed certificate's key and signature, with the record's own id (a file)",
        "signature", verify_lines, [lines[0], edit(lines[1], certsig)] + lines[2:])
    # a certificate-domain signature over the record's own id: this is what `signature-domain` is, in a file
    signed = export(metrics_file(tmp), signer=K["signer_a"])[1]
    certdomain = lambda o: o["sig"].update(sig=ed25519.sign(seed, cert2.signature_message(o["id"])).hex())
    check("control: the same file with the key's record-domain signatures verifies", verdict(signed, K["ring_a"]) == "ok")
    red("a record line whose sig is the key's certificate-domain signature over the record's own id (a file)",
        "signature-domain", verify_lines, [signed[0], edit(signed[1], certdomain)] + signed[2:], K["ring_a"])
    # a function call only: no file has a record whose id is the certificate's body hash (that would be a SHA-256 preimage)
    rec = {"id": h, "sig": {"alg": "ed25519", "key": key_hex, "sig": sig_hex}, "run": {"device": S.device_of(bytes.fromhex(key_hex))}}
    red("check_signature, given the certificate's body hash as the id (a value no file can have): the committed signature",
        "signature-domain", S.check_signature, rec, None)
    mine = {"id": h, "sig": {"alg": "ed25519", "key": pub.hex(), "sig": ed25519.sign(seed, S.TAG_RECORD + bytes.fromhex(h)).hex()},
            "run": {"device": S.device_of(pub)}}
    check("control: a record-domain signature over the same 32 bytes verifies as a record's", refusal(S.check_signature, mine, None) is None)
    mine["sig"]["sig"] = ed25519.sign(seed, cert2.signature_message(h)).hex()
    red("check_signature, the key's certificate-domain signature over the same 32 bytes", "signature-domain",
        S.check_signature, mine, None)


# ---- plants -----------------------------------------------------------------------------------------

def group_plants(tmp, lines=None, tag="synthetic"):
    A, B, RA, RAB = K["signer_a"], K["signer_b"], K["ring_a"], K["ring_ab"]
    if lines is None:
        lines = export(metrics_file(tmp), signer=A)[1]
    other = export(metrics_file(tmp, "run2.jsonl", fake_run("card-stress-test-2", t0=1792100000.0)), signer=A)[1]
    other_b = export(metrics_file(tmp, "run3.jsonl", fake_run("card-stress-test-1", t0=1792200000.0)), signer=B)[1]
    t = lambda s: f"{tag}: {s}"
    check(t("control: the unaltered signed file verifies with the keyring"), verdict(lines, RA) == "ok")

    def put(k, new, drop=()):
        return [new if n == k else ln for n, ln in enumerate(lines) if n not in drop]

    def case(label, want, make, ring=None, require=True):
        try:
            edited = make()
        except KeyError as e:
            skip(t(label), f"this run has no {e} record")
            return
        red(t(label), want, verify_lines, edited, ring, require)
    i = op_index(lines, "scaleb32-all")                  # a slice with a clause: the one most plants alter
    shifted = lambda o: o.update(lo=o["lo"] + 1, hi=o["hi"] + 1)           # another interval; every count still holds
    swap = lambda o: o.update(sig=B.sign({k: v for k, v in o.items() if k not in ("id", "sig")})["sig"])
    # 1. a count changed after signing
    case("a count changed after signing (the id left as it was)", "id", lambda: put(i, edit(lines[i], lambda o: o.update(cases=o["cases"] + 1))))
    case("the interval moved with the id recomputed to match (the signature is stale)", "signature",
         lambda: put(i, edit(lines[i], shifted, fix_id=True)))
    # 2. the signature of another key
    case("another key's valid signature, a keyring naming only the first", "key", lambda: put(i, edit(lines[i], swap)), RA)
    case("another key's valid signature, no keyring: the device is the first key's", "device", lambda: put(i, edit(lines[i], swap)))
    case("another key's valid signature, a keyring naming both: still not the device's", "device", lambda: put(i, edit(lines[i], swap)), RAB)
    case("another key's name on the first key's signature", "signature", lambda: put(i, edit(lines[i], lambda o: o["sig"].update(key=K["pub_b"].hex()))))
    # 3. a record of another run spliced in
    k = op_index(other, "scaleb32-all")
    case("a validly signed slice of another run, with its campaign", "splice", lambda: lines + [campaign_line(other, k), other[k]])
    case("a validly signed slice of another run, without its campaign", "splice", lambda: lines + [other[k]])
    case("a slice of a run of the same name made on another device", "splice", lambda: lines + [other_b[op_index(other_b, "scaleb32-all")]], RAB)
    # 4. the domain string swapped to a certificate's
    sw = json.loads(lines[i])
    sw["sig"]["sig"] = ed25519.sign(seed_of("A"), cert2.signature_message(sw["id"])).hex()
    case("a record signed under the certificate's domain string", "signature-domain", lambda: put(i, S.canon(sw) + b"\n"))
    # 5. a key file inside the tree: group keys. 6. the rest of the list
    case("a signature missing where signatures are required", "signature", lambda: put(i, edit(lines[i], lambda o: o.pop("sig"))))
    case("a key the keyring does not name", "key", lambda: lines, {K["pub_b"].hex(): "B"})
    case("version 3 (unknown)", "version", lambda: put(i, edit(lines[i], lambda o: o.update(v=3))))
    case("a card slice given version 2 (a card subject in a version-2 record: a card slice is version 1)", "form",
         lambda: put(i, edit(lines[i], lambda o: o.update(v=2))))
    case("spaces after the separators", "canonical", lambda: put(i, json.dumps(json.loads(lines[i]), sort_keys=True).encode() + b"\n"))
    case("the file written with CRLF line endings", "canonical", lambda: [ln[:-1] + b"\r\n" for ln in lines])
    case("a key of small order on a signature", "signer", lambda: put(i, edit(lines[i], lambda o: o["sig"].update(key="01" + "00" * 31))))
    # counts, each validly signed afresh: a signature does not launder a count
    for label, op, fn in (
            ("expected_cases, one case over (scaleb32-all)", "scaleb32-all", lambda o: o.update(cases=o["cases"] + 1)),
            ("the cover rule, one pair skipped too many (cvtto32-all)", "cvtto32-all", lambda o: o.update(skipped=o["skipped"] + 1)),
            ("no skipped where the tool prints a clause (scaleb32-all)", "scaleb32-all", lambda o: o.pop("skipped")),
            ("an interval past the space (scaleb32-all)", "scaleb32-all",
             lambda o: o.update(hi=(1 << 32) + 1, cases=((1 << 32) + 1 - o["lo"]) * 17)),
            ("nextup32 without its 8 edge cases", "nextup32", lambda o: o.update(cases=o["cases"] - 8)),
            ("skipped where the tool prints no clause (sqrt32)", "sqrt32", lambda o: o.update(skipped=0)),
            ("a stream with 0 cases (rem64)", "rem64", lambda o: o.update(cases=0))):
        case(f"counts: {label}, validly signed", "counts", lambda op=op, fn=fn: put(op_index(lines, op), resign(lines[op_index(lines, op)], fn, A)), RA)
    p = os.path.join(tmp, f"sign-in-{tag}.jsonl")
    with open(p, "wb") as f:
        f.write(b"".join(strip_sig(put(i, edit(lines[i], lambda o: o.update(cases=o["cases"] + 1), fix_id=True)))))
    rc, so, se = cli("sign", p, "--key", K["key_a"], "--out", os.path.join(tmp, f"sign-out-{tag}.jsonl"))
    check(t("`sign` refuses a file holding a count that breaks the rule: counts, nothing written"),
          rc == 2 and "refused counts" in se and not os.path.exists(os.path.join(tmp, f"sign-out-{tag}.jsonl")), se[-200:])
    # campaigns
    ci = next(n for n, ln in enumerate(lines) if json.loads(ln)["kind"] == "campaign" and json.loads(ln)["operation"] == "scaleb32-all")
    case("a campaign record dropped: the slice names one that is not in the file", "campaign", lambda: put(ci, b"", drop=(ci,)))
    case("a campaign record altered, its id left as it was", "id", lambda: put(ci, edit(lines[ci], lambda o: o.update(per_encoding=9))))
    case("a campaign record altered and its id fixed: it no longer hashes to the cid the slice names", "campaign",
         lambda: put(ci, edit(lines[ci], lambda o: o.update(per_encoding=9), fix_id=True)))
    rs = next((json.loads(ln) for ln in lines if json.loads(ln)["kind"] == "campaign" and json.loads(ln)["sweep"] == "random"), None)
    case("a slice that names a random campaign, validly signed", "campaign",
         lambda: put(i, resign(lines[i], lambda o: o.update(cid=rs["id"]), A)), RA) if rs else \
        skip(t("a slice that names a random campaign"), "this run has no random campaign")
    # the run block
    case("a rate ten times the record's own cases over its own time, validly signed", "run",
         lambda: put(i, resign(lines[i], lambda o: o["run"].update(rate=o["run"]["rate"] * 10), A)), RA)
    case("an end before the start, validly signed", "run", lambda: put(i, resign(lines[i], lambda o: o["run"].update(end_ms=o["run"]["start_ms"] - 1), A)), RA)
    case("a file of campaign records only", "empty", lambda: [ln for ln in lines if json.loads(ln)["kind"] == "campaign"])
    # sign's refusals
    p = os.path.join(tmp, f"signed-{tag}.jsonl")
    with open(p, "wb") as f:
        f.write(b"".join(lines))
    rc, so, se = cli("sign", p, "--key", K["key_b"], "--out", os.path.join(tmp, f"sign-out1-{tag}.jsonl"))
    check(t("`sign` of records that are signed already -> refused signed"), rc == 2 and "refused signed" in se, se[-200:])
    p = os.path.join(tmp, f"unsigned-{tag}.jsonl")
    with open(p, "wb") as f:
        f.write(b"".join(strip_sig(lines)))
    out = os.path.join(tmp, f"sign-out2-{tag}.jsonl")
    rc, so, se = cli("sign", p, "--key", K["key_b"], "--out", out)
    check(t("`sign` with a key whose device is not the one the records name -> refused device, nothing written"),
          rc == 2 and "refused device" in se and not os.path.exists(out), se[-200:])
    # a known limit, run: nothing in version 1 signs the set, so a record dropped from the file is not seen
    findings = [n for n, ln in enumerate(lines) if json.loads(ln)["kind"] != "campaign" and S.is_finding(json.loads(ln))]
    if findings:
        check(t("known limit: a finding's record dropped from a signed file leaves a file that verifies"),
              verdict(put(findings[0], b"", drop=(findings[0],)), RA) == "ok")
    # the verifier without a check lets its plant through: each plant above is red because of its check
    forged = put(i, edit(lines[i], shifted, fix_id=True))
    with without("check_signature", lambda rec, ring: None):
        check(t("the verifier without check_signature accepts the moved interval"), verdict(forged, RA) == "ok")
    badc = put(i, resign(lines[i], lambda o: o.update(cases=o["cases"] + 1), A))
    with without("counts_problem", lambda camp, rec: None):
        check(t("the verifier without counts_problem accepts the validly signed wrong count"), verdict(badc, RA) == "ok")
    badr = put(i, resign(lines[i], lambda o: o["run"].update(rate=o["run"]["rate"] * 10), A))
    with without("run_problem", lambda rec: None):
        check(t("the verifier without run_problem accepts the validly signed wrong rate"), verdict(badr, RA) == "ok")


# ---- host: version 2, the host-pool slice and stream ----------------------------------------------------

HA, HB = "a1" * 20, "b2" * 20                           # two host/ tree hashes (git tree hashes: 40 hex)
CCV = "cc (Ubuntu 13.3.0-6ubuntu2~24.04.1) 13.3.0"      # a compiler's first version line, as the 2026-10-19 run's second run_start has one


def host_tree(src=HA, dirty=False, cc=CCV):
    """The keys DR2's driver adds to run_start.tree (hw/card_stress.py tree_facts)."""
    return {"host_src": src, "host_src_dirty": dirty, "cc": cc, "rtl": "c3" * 20, "rtl_dirty": False}


def fake_host_run(rid="card-stress-host-1", t0=1792300000.0):
    """A run of the driver's format that holds card slices (a tile item's, and one of a host item, which is what the card swept before the
    host pool) and host-pool slices (image cpu: no image hash, no tile, the pool's mark): records 4 to 9 are host legs, 9 timed out; the
    resume's run_start (another host/ tree, a host_src_dirty that git could not say and no compiler) is followed by one more host slice."""
    st = {"t": t0 + 10, "n": 0}

    def leg(item, **kw):
        st["t"] += 7
        st["n"] += 1
        return fake_leg(item, t=st["t"], n=st["n"], **kw)

    def host(item, **kw):
        return leg(item, image="cpu", **kw)
    bad = ["MISMATCH class32 a=0x7f800001 dev=0x00000001 ref=0x00000002", "FLAGS class32 a=0x00000001"]
    return [fake_start(rid, t=t0, host_tree=host_tree()), fake_build(),
            leg("sqrt32-rne", tile=1, jobs=4), leg("conv32to64-all", image="deep"),
            host("conv32to64-all"), host("nextup32", lo=1 << 20, hi=2 << 20), host("cvtto32-all-rne", lo=1 << 20, hi=2 << 20),
            host("rem64", seed=0xC5000000 + 41, seed_n=3), host("class32", lo=0, hi=1 << 20, status="fail", vm=1, fm=1, dis=bad),
            host("logb32", status="timeout"),
            fake_start(rid, commit=C2, resumed=True, t=st["t"] + 60, host_tree=host_tree(HB, None, None)), fake_build(),
            host("logb32", lo=0, hi=1 << 20)]


def snap(ex):
    """What an exporter's state is, for 'a refusal leaves it as it was'."""
    return (ex.legs, ex.findings, sorted(ex.seen), dict(ex.left), ex.built, ex.start and ex.start["run_id"])


def group_host(tmp):
    pub, A, RA = K["pub_a"], K["signer_a"], K["ring_a"]
    raw = fake_host_run()
    path = metrics_file(tmp, "host1.jsonl", raw)
    try:
        ex, lines, _ = export(path, signer=A)
    except S.Refusal as e:                       # a defect in the exporter is a red check, not a crash of the group
        check("host: the run exports 8 finished legs (2 card, 6 host-pool) as 7 slices and a stream, over 7 campaigns", False, f"refused {e.name}: {e.why}")
        return
    recs = [json.loads(ln) for ln in lines]
    flat = [r for r in recs if r["kind"] != "campaign"]
    camps = {r["id"]: r for r in recs if r["kind"] == "campaign"}
    dev = S.device_of(pub)
    check("host: the run exports 8 finished legs (2 card, 6 host-pool) as 7 slices and a stream, over 7 campaigns; the host job that timed out "
          "is counted as left", collections.Counter((r["kind"], r["v"]) for r in recs) ==
          {("campaign", 1): 7, ("slice", 1): 2, ("slice", 2): 5, ("stream", 2): 1} and ex.legs == 8 and ex.left == {"timeout": 1}, str(ex.left))
    check("host: the card legs are version 1, the host-pool legs version 2, and every campaign version 1 (a campaign is version 1's whatever "
          "version the records naming it are)", [r["v"] for r in flat] == [1, 1, 2, 2, 2, 2, 2, 2] and all(c["v"] == 1 for c in camps.values()))
    check("host: the first host slice's subject is run_start.tree's host_src, host_src_dirty and cc, read as they stand (and nothing of the "
          "machine: no node name, no CPU)", flat[2]["subject"] == {"src": HA, "dirty": False, "cc": CCV} and flat[2]["tool"] == {"commit": C1, "dirty": False},
          str(flat[2]["subject"]))
    check("host: after the resume, whose run_start recorded another host/ tree, git could not say whether host/ differed and no compiler, the "
          "slice has the new tree and no `dirty` and no `cc`: a field the data cannot fill is absent, not False and not null",
          flat[7]["subject"] == {"src": HB} and flat[7]["tool"]["commit"] == C2 and "testhost" not in json.dumps(recs))
    check("host: no host subject has a card field and no card subject a host field; no host record has a tile, tiles, image or xclbin",
          all(not {"image", "xclbin", "tiles", "tile"} & set(r["subject"]) for r in flat if r["v"] == 2)
          and all("src" not in r["subject"] and "dirty" not in r["subject"] and "cc" not in r["subject"] for r in flat if r["v"] == 1))
    check("host: readback - every record equals its raw leg, field by field, against the run_start in force for it (this file has two)",
          readback(raw, flat, dev) == [], str(readback(raw, flat, dev)))
    planted = readback(raw, flat, dev, first_only=True)
    check("host: readback, the plant - the first run_start's expectation is red here, at the one host slice after the resume, on its subject and "
          "the tool's commit", planted == [("sweep-logb32", ["subject", "tool"])], str(planted))
    # the campaign: the same record whoever computed the slice, and unchanged since 77c5dbca
    i_card, i_host = (next(n for n, r in enumerate(flat) if r["v"] == v and camps[r["cid"]]["operation"] == "conv32to64-all") for v in (1, 2))
    conv_id = "c2aaacbea9016dc8da1472d1a71f15e161d49bdecdb2db6cadc4177a4fb3edc1"
    check("host: a host-pool slice and a card image's slice of the same item name one campaign, whose id is the one the document prints; the "
          "campaign says reach host and the oracle kind host-fpu+glibc", flat[i_card]["cid"] == flat[i_host]["cid"] == conv_id and
          camps[conv_id]["reach"] == "host" and camps[conv_id]["oracle"] == "host-fpu+glibc"
          and all(c["reach"] == "host" for c in camps.values() if c["operation"] != "sqrt32"), str(sorted(camps.values(), key=lambda c: c["operation"])[0]))
    alone = os.path.join(tmp, "host-alone.jsonl")
    write_metrics(alone, raw[:2] + [raw[4]])
    exa, la, _ = export(alone, signer=A)
    camp_line = next(ln for ln in lines if json.loads(ln)["id"] == conv_id)
    cards_only = export(metrics_file(tmp), signer=A)[1]
    check("host: a host slice's cid and campaign line are the same exported alone as with the card slices of the run, and the same as the card-only "
          "synthetic run's line for that item (no card campaign id moves)", len(la) == 2 and la[0] == camp_line and json.loads(la[1])["cid"] == conv_id and
          camp_line == next(ln for ln in cards_only if json.loads(ln)["id"] == conv_id))
    dig = hashlib.sha256()
    for it in L.sweep_items():
        dig.update(f"{it.name} {S.record_id(S.campaign_body(it))}\n".encode())
    check("host: the campaign ids of all 125 catalog items are what they were at 77c5dbca (one digest over each name and id; the first 90 are DR3's)",
          dig.hexdigest() == BASE_CAMPAIGN_DIGEST and len(L.sweep_items()) == 125, dig.hexdigest())
    # verify: both versions in one file, the totals by subject kind equal to the raw legs'
    rep = verify_lines(lines, RA)
    done = [x for x in raw if x["type"] == "leg" and x["kind"] == "sweep" and x["status"] == "pass"]
    want = {k: (sum(1 for x in done if (x["image"] == "cpu") == (k == "host")),
                sum(x["counts"]["cases"] for x in done if (x["image"] == "cpu") == (k == "host"))) for k in ("card", "host")}
    check("host: the mixed file verifies signed against the keyring; its totals by subject kind (records, clean, cases) are the raw legs' own, summed apart",
          (rep["slices"], rep["streams"], len(rep["findings"]), rep["clean"], rep["cases"]) == (7, 1, 1, 7, sum(w[1] for w in want.values())) and
          {k: (v["clean"], v["cases"]) for k, v in rep["kinds"].items()} == want and rep["kinds"]["host"]["records"] == 6 and rep["kinds"]["card"]["records"] == 2,
          f"{rep['kinds']} {want}")
    rc, so, se = cli("verify", write_lines(tmp, "host-signed.jsonl", lines), "--keyring", K["ring_a_path"])
    check("host: `verify` prints the first line as it always did and a line of the totals by subject kind; the host finding exits 3",
          rc == 3 and f"7 clean ({rep['cases']} cases), 1 FINDINGS" in so and
          f"by subject: card {want['card'][0]} clean ({want['card'][1]} cases); host {want['host'][0]} clean ({want['host'][1]} cases), 1 findings" in so, so[-400:])
    hl = [ln for ln in lines if json.loads(ln).get("v") == 2]
    only_host = [ln for ln in lines if json.loads(ln)["kind"] == "campaign" and json.loads(ln)["id"] in {json.loads(h)["cid"] for h in hl}] + hl
    rep_h = verify_lines(only_host, RA)
    check("host: a file of host-pool records alone (version-1 campaigns, version-2 slices) verifies, and its card total is 0",
          rep_h["kinds"]["card"] == {"records": 0, "clean": 0, "cases": 0} and rep_h["kinds"]["host"]["records"] == 6)
    unsigned = export(path, public=pub)[1]
    p_un, p_sg = os.path.join(tmp, "host-un.jsonl"), os.path.join(tmp, "host-sg.jsonl")
    write_lines(tmp, "host-un.jsonl", unsigned)
    rc, so, se = cli("sign", p_un, "--key", K["key_a"], "--out", p_sg)
    check("host: `sign` of the unsigned file equals `export --key`, byte for byte, version-2 records included", rc == 0 and open(p_sg, "rb").read() == b"".join(lines), se[-200:])
    check("host: export is deterministic, the unsigned file verifies only as unsigned, and every host record has an id and no signature",
          export(path, signer=A)[1] == lines and verdict(unsigned, None, False) == "ok" and verdict(unsigned) == "signature"
          and all("sig" not in json.loads(ln) for ln in unsigned))
    # the example in the document: a host slice, from this synthetic run (a real run holds none: night 1's run_start recorded no host/ tree)
    doc = open(os.path.join(ROOT, "docs", "SWEEP-RECORDS.md"), encoding="utf-8").read().splitlines()
    check("host: the document's example host slice is this synthetic run's first host slice, exported unsigned for the test's key A",
          unsigned[lines.index(next(ln for ln in lines if json.loads(ln).get("v") == 2))].decode().rstrip("\n") in doc)

    # version rule
    i_h = next(n for n, ln in enumerate(lines) if json.loads(ln).get("v") == 2)
    red("a version-3 record in the mixed file", "version", S.parse_file, b"".join(lines[:i_h] + [edit(lines[i_h], lambda o: o.update(v=3))] + lines[i_h + 1:]))
    why = None
    try:
        S.parse_file(edit(lines[i_h], lambda o: o.update(v=3)))
    except S.Refusal as e:
        why = e.why
    check("host: an unknown version is refused by that name and the message says which versions are known", why is not None and "version 3" in why and "versions 1 and 2" in why, str(why))
    red("a campaign record given version 2 (a campaign is version 1's)", "form", S.parse_file,
        b"".join([edit(lines[0], lambda o: o.update(v=2), fix_id=True)] + lines[1:]))

    # the exporter's refusals, each leaving it as it was
    tile_on_cpu = fake_leg("sqrt32-rne", image="cpu")      # a TILE item's job given to the host pool

    def refuse(label, want_in, mutate_leg=None, mutate_start=None, the_leg=None):
        e = S.Exporter(public=pub)
        st = json.loads(json.dumps(raw[0]))
        (mutate_start or (lambda s: None))(st)
        e.run_start(st)
        e.build(raw[1])
        e.leg(raw[2])                                       # a card slice first: the exporter has a run, a build, a campaign and a leg to keep
        before = snap(e)
        leg = json.loads(json.dumps(the_leg or raw[4]))
        (mutate_leg or (lambda s: None))(leg)
        try:
            e.leg(leg)
            got = None
        except S.Refusal as x:
            SEEN.add(x.name)
            got = (x.name, x.why)
        after = snap(e)
        check(f"host export: {label} -> refused metrics, saying {want_in!r}", got is not None and got[0] == "metrics" and want_in in got[1], str(got))
        nxt = e.leg(raw[3])                                 # a card slice of another item: its campaign line, then itself
        check(f"host export: {label} - the exporter is as it was after the refusal, and the next good leg still brings its campaign first",
              after == before and len(nxt) == 2 and json.loads(nxt[0])["kind"] == "campaign" and e.legs == before[0] + 1, f"{before} -> {after}")
    refuse("a host slice whose run recorded no host/ tree (run_start.tree has no host_src: night 1 of the 2026-10-19 run)", "no host/ tree",
           mutate_start=lambda s: s["tree"].pop("host_src"))
    refuse("a host slice whose run_start.tree says host_src is null", "no host/ tree", mutate_start=lambda s: s["tree"].update(host_src=None))
    refuse("a host slice whose host_src is not a tree hash (an abbreviation)", "no host/ tree", mutate_start=lambda s: s["tree"].update(host_src="4d9905f"))
    refuse("a host slice whose run_start has no tree at all", "no host/ tree", mutate_start=lambda s: s.update(tree=None))
    refuse("a card slice dressed as a host one: the image cpu with an image hash", "dressed as a host-pool one",
           mutate_leg=lambda s: s.update(image_sha256=IMG["quad"][0]))
    refuse("a card slice dressed as a host one: the image cpu with a tile", "dressed as a host-pool one", mutate_leg=lambda s: s["sweep"].update(tile=2))
    refuse("a host slice dressed as a card one: a card image's name and hash, with the host pool's mark (sweep.pool)", "dressed as a card one",
           mutate_leg=lambda s: s.update(image="quad", image_sha256=IMG["quad"][0]))
    refuse("a host-pool slice of a tile item (sqrt32-rne on the image cpu): a host build is no evidence about the tile", "an item whose reach is tile",
           the_leg=tile_on_cpu)
    refuse("a compiler line with a control character", "compiler version line", mutate_start=lambda s: s["tree"].update(cc="gcc 13\x07"))
    refuse("a compiler line of 257 characters", "compiler version line", mutate_start=lambda s: s["tree"].update(cc="x" * 257))
    ok_cc = S.Exporter(public=pub)
    ok_cc.run_start(dict(raw[0], tree=dict(raw[0]["tree"], cc="x" * 256)))
    ok_cc.build(raw[1])
    check("host export: a compiler line of exactly 256 characters is held as it is", json.loads(ok_cc.leg(raw[4])[-1])["subject"]["cc"] == "x" * 256)

    # the verifier's refusals, on validly signed records, so that only the check aimed at can fire
    ih = next(n for n, ln in enumerate(lines) if json.loads(ln).get("v") == 2)
    ic = next(n for n, ln in enumerate(lines) if json.loads(ln).get("v") == 1 and json.loads(ln)["kind"] == "slice")
    sqrt_cid = next(c["id"] for c in camps.values() if c["operation"] == "sqrt32")
    # the host slice moved to a tile campaign must otherwise be fit for it, so that only the reach check can refuse it: logb32's slice is exact,
    # takes one case an encoding and prints no clause, as sqrt32's campaign says of its own
    il = next(n for n, ln in enumerate(lines) if json.loads(ln).get("v") == 2 and camps[json.loads(ln)["cid"]]["operation"] == "logb32")
    put = lambda k, new: [new if n == k else ln for n, ln in enumerate(lines)]
    card_subject = lambda o: o.update(subject={"image": "quad", "xclbin": IMG["quad"][0], "tiles": 4})
    for label, want, make in (
            ("a host-pool slice edited to carry a card image's subject (a card slice dressed as a host one): the record says version 2", "form",
             lambda: put(ih, resign(lines[ih], card_subject, A))),
            ("a card slice edited to carry a host build's subject (a host slice dressed as a card one): the record says version 1", "form",
             lambda: put(ic, resign(lines[ic], lambda o: o.update(subject={"src": HA}), A))),
            ("a host-pool slice given version 1 (its host subject is not version 1's)", "form",
             lambda: put(ih, resign(lines[ih], lambda o: o.update(v=1), A))),
            ("a host-pool slice naming a campaign whose reach is the tile (a host build is no evidence about the tile)", "campaign",
             lambda: put(il, resign(lines[il], lambda o: o.update(cid=sqrt_cid), A)))):
        red(f"verify: {label}", want, verify_lines, make(), RA)
    why = {}
    for label, make in (("a card subject in version 2", lambda: put(ih, resign(lines[ih], card_subject, A))),
                        ("a host subject in version 1", lambda: put(ic, resign(lines[ic], lambda o: o.update(subject={"src": HA}), A))),
                        ("a host slice of a tile campaign", lambda: put(il, resign(lines[il], lambda o: o.update(cid=sqrt_cid), A)))):
        try:
            verify_lines(make(), RA)
        except S.Refusal as e:
            why[label] = e.why
    check("host: each of those refusals says what it refuses: a card slice is version 1, a host-pool slice is version 2, and a host build's reach",
          "a card slice is version 1" in why.get("a card subject in version 2", "") and "a host-pool slice is version 2" in why.get("a host subject in version 1", "")
          and "reach is tile" in why.get("a host slice of a tile campaign", ""), str(why))
    h = json.loads(lines[ih])
    for label, fn in (("no src", lambda o: o["subject"].pop("src")), ("src in capitals", lambda o: o["subject"].update(src=HA.upper())),
                      ("src of 39 characters", lambda o: o["subject"].update(src=HA[:39])), ("src that is not a string", lambda o: o["subject"].update(src=5)),
                      ("dirty that is 0", lambda o: o["subject"].update(dirty=0)), ("an empty cc", lambda o: o["subject"].update(cc="")),
                      ("a cc of 257 characters", lambda o: o["subject"].update(cc="x" * 257)), ("a cc with a control character", lambda o: o["subject"].update(cc="a\x00b")),
                      ("a null cc", lambda o: o["subject"].update(cc=None)), ("a node name in the subject", lambda o: o["subject"].update(host="testhost")),
                      ("a tile in a host subject", lambda o: o["subject"].update(tile=1)), ("tiles in a host subject", lambda o: o["subject"].update(tiles=1)),
                      ("a host/ build id the form does not have", lambda o: o["subject"].update(build_id="x"))):
        o = json.loads(json.dumps(h))
        fn(o)
        red(f"shape (version 2): {label}", "form", S.check_shape, o, "x")
    check("host: the host subject's optional fields may be absent and the record is still of its form: src alone, src and dirty, src and cc",
          all(refusal(S.check_shape, dict(h, subject=sub), "x") is None for sub in ({"src": HA}, {"src": HA, "dirty": True}, {"src": HA, "cc": "x"})))
    # the verifier without the check lets its plant through
    ontile = put(il, resign(lines[il], lambda o: o.update(cid=sqrt_cid), A))
    with without("subject_problem", lambda camp, rec: None):
        check("host: the verifier without subject_problem accepts the validly signed host-pool slice of a tile campaign", verdict(ontile, RA) == "ok")
    dressed = put(ih, resign(lines[ih], card_subject, A))
    with without("check_shape", lambda obj, where: None):
        check("host: the verifier without check_shape accepts the validly signed card subject in a version-2 record", verdict(dressed, RA) == "ok")
    # a finding is a record: the host finding
    hf = next(r for r in flat if r["v"] == 2 and S.is_finding(r))
    check("host: the host slice that found a mismatch is a record with its first lines, version 2, and a finding, never coverage",
          hf["vm"] == 1 and len(hf["disagreements"]) == 2 and hf["v"] == 2 and rep["kinds"]["host"]["records"] - rep["kinds"]["host"]["clean"] == 1)


def write_lines(tmp, name, lines):
    p = os.path.join(tmp, name)
    with open(p, "wb") as f:
        f.write(b"".join(lines))
    return p


# ---- real -------------------------------------------------------------------------------------------

def group_real(tmp, metrics):
    p = os.path.join(metrics, "metrics.jsonl") if os.path.isdir(metrics) else metrics
    raw = [json.loads(ln) for ln in open(p, "rb").read().split(b"\n") if ln.strip()]
    fin = [r for r in raw if r["type"] == "leg" and r["kind"] == "sweep" and r["status"] in ("pass", "fail")]
    others = collections.Counter(r["type"] for r in raw if r["type"] not in ("run_start", "build", "leg"))
    def shape_of(r):
        return set(r), set(r["sweep"]), set(r["counts"])
    unfit = [r["leg"] for r in fin if shape_of(fake_leg(r["sweep"]["item"], lo=r["sweep"].get("lo", 0), hi=r["sweep"].get("hi", 1 << 20),
                                                        tile=r["sweep"]["tile"])) != shape_of(r)]
    check(f"real: the synthetic legs have the real legs' keys, their sweep dicts' and their counts' ({len(fin)} legs)", not unfit, str(unfit[:3]))
    t0 = time.time()
    ex, lines, _ = export(p, public=K["pub_a"])
    t1 = time.time()
    recs = [json.loads(ln) for ln in lines]
    flat = [r for r in recs if r["kind"] != "campaign"]
    check(f"real: {len(fin)} finished sweep legs make {len(fin)} records and {len({l['sweep']['item'] for l in fin})} campaigns; "
          f"{sum(others.values())} records of other types ({dict(others)}) are ignored",
          len(flat) == len(fin) and len(recs) - len(flat) == len({l["sweep"]["item"] for l in fin}))
    # every field read back from the raw leg, literally, against the run_start IN FORCE for the leg (a resumed run's file has one for each
    # invocation: the 2026-10-19 run's two, of commits 881bbcb6 and 0b7c9599, give 378 records the first and 174 the second)
    bad = readback(raw, flat, S.device_of(K["pub_a"]))
    check("real: every record equals its raw leg, field by field (interval, counts, image, tile, run, rate, log, tree), each against the "
          "run_start in force for it", not bad, str(bad[:3]))
    starts = [r for r in raw if r["type"] == "run_start"]
    moved = moved_legs(raw)
    if moved:
        planted = readback(raw, flat, S.device_of(K["pub_a"]), first_only=True)
        check(f"real: the plant, the first run_start's expectation for every leg, is red on this file ({len(starts)} run_starts, commits "
              f"{', '.join(str((s.get('tree') or {}).get('commit'))[:8] for s in starts)}): it fails the {len(moved)} legs the later ones are "
              f"in force for, on the tool's commit, and no other", [b[0] for b in planted] == moved and all("tool" in b[1] for b in planted), str(planted[:2]))
    else:
        skip("real: the first-run_start plant", "this file has one run_start, or several of one commit: the plant would not differ")
    total = sum(l["counts"]["cases"] for l in fin)
    rep = verify_lines(lines, None, False)
    check(f"real: the cases in clean records, {rep['cases']:,}, are the sum of the raw legs' ({total:,}), and none is a finding",
          rep["cases"] == total and rep["findings"] == [])
    doc = open(os.path.join(ROOT, "docs", "SWEEP-RECORDS.md"), encoding="utf-8").read()
    check("real: the document's example slice is the run's first slice, exported for the test's key A",
          lines[1].decode().rstrip("\n") in doc.splitlines())
    imgs = collections.Counter(r["subject"]["image"] for r in flat)
    check(f"real: the three images are told apart: {dict(imgs)}", imgs == collections.Counter(l["image"] for l in fin))
    check("real: no field the data cannot fill, no null", not any(k in r for r in flat for k in FORBIDDEN) and
          all(v is not None for r in recs for v in r.values()))
    t2 = time.time()
    ex2, lines2, _ = export(p, signer=K["signer_a"])
    t3 = time.time()
    check("real: the signed file verifies with the keyring", verdict(lines2, K["ring_a"]) == "ok")
    t4 = time.time()
    check("real: export is deterministic, and a signed export is the unsigned one signed",
          export(p, signer=K["signer_a"])[1] == lines2 and
          [ln if json.loads(ln)["kind"] == "campaign" else S.canon(K["signer_a"].sign(
              {k: v for k, v in json.loads(ln).items() if k != "id"})) + b"\n" for ln in lines] == lines2)
    out, ring = os.path.join(tmp, "real-signed.jsonl"), K["ring_a_path"]
    c0 = time.time()
    rc1, so1, se1 = cli("export", p, "--out", out, "--key", K["key_a"])
    c1 = time.time()
    rc2, so2, se2 = cli("verify", out, "--keyring", ring)
    c2 = time.time()
    check("real: CLI export --key then verify --keyring: both exit 0, the same bytes, nothing a finding",
          rc1 == 0 and rc2 == 0 and open(out, "rb").read() == b"".join(lines2) and "0 FINDINGS" in so2, se1[-150:] + se2[-150:])
    print(f"  real: {len(flat)} records, {sum(map(len, lines2)):,} bytes signed: export unsigned {t1 - t0:.2f} s, signed {t3 - t2:.2f} s "
          f"({(t3 - t2) / len(flat) * 1000:.1f} ms a record), verify {t4 - t3:.2f} s; as commands (each with its 0.4 s start): "
          f"export --key {c1 - c0:.2f} s, verify {c2 - c1:.2f} s")
    # the plants on real records: the first slice of each campaign, so that each verification is short
    seen, sub = set(), []
    for ln in lines2:
        o = json.loads(ln)
        if o["kind"] == "campaign" or o["cid"] not in seen:
            seen.add(o.get("cid"))
            sub.append(ln)
    group_plants(tmp, sub, "real")


# ---- main -------------------------------------------------------------------------------------------

def main():
    only = set(sys.argv[sys.argv.index("--only") + 1].split(",")) if "--only" in sys.argv else None
    metrics = sys.argv[sys.argv.index("--metrics") + 1] if "--metrics" in sys.argv else None
    want = lambda g: only is None or g in only
    tmp = tempfile.mkdtemp(prefix="sweep-record-test-")
    t0 = time.time()
    try:
        for n in "ab":
            K["key_" + n] = os.path.join(tmp, n + ".key")
            write_key(K["key_" + n], n.upper())
            K["signer_" + n] = S.Signer(seed_of(n.upper()))
            K["pub_" + n] = K["signer_" + n].public
        K["ring_a_path"] = os.path.join(tmp, "a.ring")
        with open(K["ring_a_path"], "w", newline="\n") as f:
            f.write(f"key {K['pub_a'].hex()} test%20key%20A\n")
        K["ring_a"] = {K["pub_a"].hex(): "test key A"}
        K["ring_ab"] = dict(K["ring_a"], **{K["pub_b"].hex(): "test key B"})
        for name, fn in (("forms", group_forms), ("rules", group_rules), ("export", group_export), ("keys", group_keys),
                         ("domain", group_domain), ("plants", group_plants), ("host", group_host)):
            if want(name):
                n0, f0 = CHECKS, len(FAILS)
                fn(tmp)
                print(f"{name}: {CHECKS - n0} checks, {len(FAILS) - f0} failed")
        if want("real"):
            if metrics:
                n0, f0 = CHECKS, len(FAILS)
                group_real(tmp, metrics)
                print(f"real: {CHECKS - n0} checks, {len(FAILS) - f0} failed")
            else:
                skip("real", "no --metrics given: a copy of a real run's metrics.jsonl is not in the repository")
        if only is None:
            miss = sorted(set(S.REFUSALS) - SEEN)
            check("every refusal the module names was watched firing in this run", not miss, f"never fired: {miss}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print(f"sweep-record test: {CHECKS} checks, {len(FAILS)} failed, {len(SKIPS)} skipped, {time.time() - t0:.0f} s")
    for f in FAILS:
        print("  FAILED:", f[:300])
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
