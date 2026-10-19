# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""The data python/project_figures.py draws that is not already a file in the tree.

Most of the figures read a committed file directly (the benchmark sweeps, the
layout generator, the golden model's format table, the design studies' captured
runs), and the sidecar beside each says which, by SHA-256. Four kinds of data
cannot be read that way, and each is reduced HERE to a small JSON file under
docs/figures/ that is committed and that a figure reads instead:

  history   what git knows: commits per day and area. CI's checkout is shallow,
            so --check must never ask git; the answer is committed, pinned to
            the commit it was read at, and remade by the command it records.
  tree      the tree at the end of each day: lines by area, the gate's size.
            Same reason, same pin.
  ledger    the card's timing record: read out of docs/VALIDATION.md (the
            ledger) by patterns that name the entry and quote the line, and
            pinned to a PREFIX of the ledger, so that appending a new entry
            does not invalidate it while editing an old one does. A scan of the
            prefix, repeated by --check, holds that every entry stating a kernel
            slack is drawn or listed as left out, with the reason.
  stress    the card's long stress run's metrics.jsonl, which is 8 MB, lives on
            amd-arc-box and is never committed. What is committed is its
            reduction, with the raw file's SHA-256 and the command that remakes
            the extract from it.

AN EXTRACT IS NOT TRUSTED BECAUSE IT IS COMMITTED. Each records:
  read_at    the commit it was read at (a data source that is the tree itself
             records the digest of exactly the bytes it read instead);
  sources    what it was made from, with digests where the source is a file;
  remake     the command that rewrites it;
  body_sha256   the digest of its own `data`, so a hand edit that does not also
             refresh the digest is caught by name, by --check, with no git.
`python python/project_figures.py --check` verifies the first three where it
can (a source that is a file in the tree is re-hashed; one that is not is named
as not rechecked here) and `python python/figure_extracts.py --verify` remakes
every extract it can from its source and compares the bytes - which needs the
full history, and the raw metrics file for the stress run, whose reduction it
then repeats with items the library's catalog could add and the run never
served injected, which must not move a byte.

No extract is a measurement of its own. A number in one is a count, a sum or a
pattern's capture group over its source, never an estimate, and a source that
does not hold what a pattern expects stops the remake rather than writing a
zero.
"""
import hashlib
import json
import pathlib
import re
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
EXTRACT_DIR = "docs/figures"
# The commit the history extracts were read at: main when this parcel was cut.
# Moving it is a decision (the figures then show the project as of that
# commit), so it is a constant here and an argument there, never a default
# that follows HEAD.
BASE_COMMIT = "0b77387ea1266f4d4a5e30c8798f57e8b6dc6ef8"
FORMAT = 1


class ExtractError(Exception):
    """An extract could not be made or read; the message says which and why."""


# ------------------------------------------------------------ digests and IO
def sha256_bytes(b):
    return hashlib.sha256(b).hexdigest()


def sha256_file(path):
    return sha256_bytes(pathlib.Path(path).read_bytes())


def canon(obj):
    """The canonical text a body digest is taken over."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def body_digest(data):
    return sha256_bytes(canon(data).encode("ascii"))


def dumps(obj):
    """An extract's or sidecar's file text: ASCII, LF, one final newline, a one-space indent, and a
    list of scalars kept on a line (wrapped at about a hundred columns) rather than one element a
    line. Deterministic: nothing here depends on the platform, and key order is the order built."""
    def scalar(v):
        return json.dumps(v, ensure_ascii=True)

    def emit(v, ind):
        pad = " " * ind
        if isinstance(v, dict):
            if not v:
                return "{}"
            rows = ["%s %s: %s" % (pad, scalar(str(k)), emit(x, ind + 1)) for k, x in v.items()]
            return "{\n" + ",\n".join(rows) + "\n" + pad + "}"
        if isinstance(v, (list, tuple)):
            if not v:
                return "[]"
            if all(not isinstance(x, (dict, list, tuple)) for x in v):
                parts = [scalar(x) for x in v]
                line = "[" + ", ".join(parts) + "]"
                if len(line) + ind <= 100:
                    return line
                rows, cur = [], ""
                for part in parts:
                    if cur and len(cur) + len(part) + 2 > 96:
                        rows.append(cur)
                        cur = part
                    else:
                        cur = cur + ", " + part if cur else part
                rows.append(cur)
                return "[\n" + ",\n".join(pad + "  " + r for r in rows) + "\n" + pad + "]"
            return "[\n" + ",\n".join(pad + " " + emit(x, ind + 1) for x in v) + "\n" + pad + "]"
        return scalar(v)
    return emit(obj, 0) + "\n"


def extract_path(root, name):
    return pathlib.Path(root) / EXTRACT_DIR / (name + ".json")


def finish(name, what, read_at, sources, remake, data, label=None):
    """The envelope every extract wears. `label` is how a figure's footer says when it was read."""
    return {"extract": name, "format": FORMAT, "what": what, "read_at": read_at,
            "read_at_label": label or read_at[:7],
            "sources": sources, "remake": remake, "body_sha256": body_digest(data),
            "data": data}


def load(root, name):
    """An extract, parsed and held to its own digest. Raises ExtractError."""
    p = extract_path(root, name)
    if not p.is_file():
        raise ExtractError("extract %s is missing: %s (remake: python python/figure_extracts.py %s)"
                           % (name, EXTRACT_DIR + "/" + name + ".json", name))
    try:
        ex = json.loads(p.read_text(encoding="utf-8"))
    except ValueError as e:
        raise ExtractError("extract %s does not parse: %s" % (name, e))
    for key in ("extract", "format", "read_at", "read_at_label", "sources", "remake", "body_sha256", "data"):
        if key not in ex:
            raise ExtractError("extract %s has no %r" % (name, key))
    if ex["extract"] != name or ex["format"] != FORMAT:
        raise ExtractError("extract %s says it is %r format %r" % (name, ex["extract"], ex["format"]))
    if body_digest(ex["data"]) != ex["body_sha256"]:
        raise ExtractError("extract %s: its data no longer matches its recorded body_sha256 "
                           "(edited by hand, or not remade: %s)" % (name, ex["remake"]))
    return ex


def source_problems(root, ex):
    """(problems, notes) for one extract's sources, with no git and no network.

    A source that is a file in the tree is re-hashed: the whole file, or the
    first N bytes of one that only ever grows (the ledger). A source that is not
    in the tree - git history, a raw metrics file - is NOT rechecked, and the
    note says so and how it would be: nothing here pretends otherwise."""
    root = pathlib.Path(root)
    problems, notes = [], []
    for s in ex["sources"]:
        kind = s.get("kind")
        if kind in ("file", "file-prefix"):
            p = root / s["path"]
            if not p.is_file():
                problems.append("extract %s: its source %s is not in the tree" % (ex["extract"], s["path"]))
                continue
            data = p.read_bytes()
            if kind == "file-prefix":
                if len(data) < s["bytes"]:
                    problems.append("extract %s: its source %s is now shorter (%d bytes) than the %d bytes "
                                    "it was read from" % (ex["extract"], s["path"], len(data), s["bytes"]))
                    continue
                data = data[:s["bytes"]]
                what = "the first %d bytes of %s" % (s["bytes"], s["path"])
            else:
                what = s["path"]
            if sha256_bytes(data) != s["sha256"]:
                problems.append("extract %s: its recorded source digest no longer matches: %s hashes to %s..., "
                                "the extract says %s..." % (ex["extract"], what, sha256_bytes(data)[:12],
                                                            s["sha256"][:12]))
            elif ex["extract"] == "ledger":
                problems += _ledger_problems(ex, data.decode("utf-8"))
        elif kind == "git":
            notes.append("extract %s: read from git at %s; not rechecked here (--check never reads git), "
                         "remake and compare with: python python/figure_extracts.py --verify"
                         % (ex["extract"], s["as_of"][:12]))
        elif kind == "raw":
            notes.append("extract %s: read from %s (sha256 %s...); the raw file is not in the tree, so its "
                         "digest is recorded, not rechecked here" % (ex["extract"], s["name"], s["sha256"][:12]))
        else:
            problems.append("extract %s: a source of unknown kind %r" % (ex["extract"], kind))
    return problems, notes


def _ledger_problems(ex, text):
    """What a fresh scan of the pinned prefix finds that the ledger extract does not account for statement by
    statement, the rules it records where they are not the script's, or a record of the scan that no longer matches a
    fresh one. The prefix is a file in the tree, so --check can do this with no git."""
    d = ex["data"]
    acc = d["accounting"]
    out = []
    if acc.get("kernel_rule") != KERNEL_SLACK.pattern or acc.get("negative_rule") != NEGATIVE_WNS.pattern:
        out.append("extract ledger: the scan rules it records are not the script's (the script's rules changed, or "
                   "the extract was edited; remake: %s)" % ex["remake"])
    problems, rows = ledger_accounting(ledger_scan(text), d["attempts"], d["left_out"])
    out += ["extract ledger: " + p for p in problems]
    if not problems and rows != acc["statements"]:
        out.append("extract ledger: its record of the statements the scan finds no longer matches a fresh scan of the "
                   "pinned prefix (remake: %s)" % ex["remake"])
    return out


# ------------------------------------------------------------------ git reads
def git(repo, *args):
    r = subprocess.run(["git", "-c", "core.quotepath=off", "-C", str(repo)] + list(args),
                       capture_output=True)
    if r.returncode != 0:
        raise ExtractError("git %s failed: %s" % (" ".join(args[:3]), r.stderr.decode("utf-8", "replace").strip()))
    return r.stdout.decode("utf-8", "replace")


def git_show(repo, rev, path):
    """A file at a commit, or None where it does not exist there."""
    r = subprocess.run(["git", "-c", "core.quotepath=off", "-C", str(repo), "show", "%s:%s" % (rev, path)],
                       capture_output=True)
    return r.stdout.decode("utf-8", "replace") if r.returncode == 0 else None


# What a commit touched, by area. The first prefix that matches decides. These
# are the project's own directories (README's "Layout"), merged to seven so
# that a figure can colour them; a path under none goes to "docs" (the root
# files are documents, licences and plumbing).
AREAS = (
    ("rtl", "RTL, benches and proofs", ("rtl/", "tb/", "formal/")),
    ("golden", "golden model and compiler", ("python/", "vectors/")),
    ("host", "host library and bindings", ("host/", "bindings/")),
    ("programs", "programs and certificates", ("programs/", "certificates/")),
    ("hw", "FPGA builds and the card", ("hw/", "docker/")),
    ("gates", "gates and plumbing", ("verify/", ".github/", "Makefile", ".gitignore", ".gitattributes")),
    ("docs", "documents", ("docs/",)),
)
# For a count of lines two slices are cut out of the areas above, because each
# would otherwise be a large share of a chart for a reason that is not new work:
# the hard-workload pack, written by another model and kept as delivered
# (programs/workloads/README.md), and the Arduino library's vendored copy of
# host/ (bindings/arduino/sync.py), which counts host/'s code a second time.
LINE_SLICES = (
    ("pack", "the delivered hard-workload pack", ("programs/workloads/cft-hard-workloads/",)),
    ("vendored", "the Arduino copy of host/", ("bindings/arduino/cft-arduino/src/cft/",)),
)


def area_of(path):
    for aid, _name, prefixes in AREAS:
        if any(path == p or path.startswith(p) for p in prefixes):
            return aid
    return "docs"


def line_area_of(path):
    for aid, _name, prefixes in LINE_SLICES:
        if any(path.startswith(p) for p in prefixes):
            return aid
    return area_of(path)


def _days_between(first, last):
    """Every ISO day from first to last, inclusive, in order."""
    import datetime
    d0 = datetime.date.fromisoformat(first)
    d1 = datetime.date.fromisoformat(last)
    return [(d0 + datetime.timedelta(days=k)).isoformat() for k in range((d1 - d0).days + 1)]


def _commit_walk(repo, as_of):
    """[(sha, parents, day, [paths touched])] for every commit reachable from as_of."""
    out = git(repo, "log", as_of, "--no-renames", "--numstat",
              "--format=@%H|%P|%ad", "--date=format:%Y-%m-%d")
    commits, cur = [], None
    for line in out.splitlines():
        if line.startswith("@"):
            sha, parents, day = line[1:].split("|")
            cur = (sha, len(parents.split()), day, [])
            commits.append(cur)
        elif line.strip() and cur is not None:
            parts = line.split("\t")
            if len(parts) == 3:
                cur[3].append(parts[2])
    return commits


def make_history(repo, as_of=BASE_COMMIT):
    """Commits per day: how many touched each area, how many were not merges, how many were."""
    commits = _commit_walk(repo, as_of)
    if not commits:
        raise ExtractError("no commits reachable from %s" % as_of)
    days = sorted({c[2] for c in commits})
    days = _days_between(days[0], days[-1])
    idx = {d: i for i, d in enumerate(days)}
    touched = {aid: [0] * len(days) for aid, _n, _p in AREAS}
    plain, merges = [0] * len(days), [0] * len(days)
    for sha, nparents, day, paths in commits:
        i = idx[day]
        if nparents > 1:
            merges[i] += 1
            continue
        plain[i] += 1
        for aid in sorted({area_of(p) for p in paths}):
            touched[aid][i] += 1
    # ABI steps, as docs/COMPATIBILITY.md dates them: a bold line or a heading
    # that starts "ABI 0.N (date". Read at the same commit.
    compat = git_show(repo, as_of, "docs/COMPATIBILITY.md")
    if compat is None:
        raise ExtractError("docs/COMPATIBILITY.md does not exist at %s" % as_of)
    abi, seen = [], set()
    for m in re.finditer(r"(?m)^(?:\*\*|### )ABI 0\.(\d+) \((\d{4}-\d{2}-\d{2})", compat):
        if m.group(1) not in seen:
            seen.add(m.group(1))
            abi.append({"abi": "0." + m.group(1), "day": m.group(2)})
    abi.sort(key=lambda a: int(a["abi"].split(".")[1]))
    first_parent = len(git(repo, "rev-list", "--first-parent", as_of).split())
    offsets = {}
    for z in git(repo, "log", as_of, "--format=%ad", "--date=format:%z").split():
        offsets[z] = offsets.get(z, 0) + 1
    data = {
        "as_of": as_of,
        "days": days,
        "areas": [{"id": a, "name": nm, "prefixes": list(pf)} for a, nm, pf in AREAS],
        "touched": touched,
        "commits": plain,
        "merges": merges,
        "totals": {"commits": len(commits), "non_merge": sum(plain), "merges": sum(merges),
                   "first_parent": first_parent},
        "abi": abi,
        "author_offsets": dict(sorted(offsets.items())),
    }
    return finish(
        "history", "commits per day and the areas each touched, the merges apart, and the ABI steps' dates",
        as_of,
        [{"kind": "git", "as_of": as_of,
          "commands": ["git log AS_OF --no-renames --numstat --format=@%H|%P|%ad --date=format:%Y-%m-%d",
                       "git show AS_OF:docs/COMPATIBILITY.md",
                       "git rev-list --first-parent AS_OF",
                       "git log AS_OF --format=%ad --date=format:%z"]}],
        "python python/figure_extracts.py history --as-of " + as_of, data)


_COUNT_RE = {
    "stages": re.compile(r'^stage [a-z0-9-]+ "', re.M),
    "proofs": re.compile(r"^run_proof ", re.M),
}


def _budget_members(text, var):
    """The stage names a BUDGET_ variable lists, expanding $NAME references; None if absent."""
    m = re.search(r"^%s=(\S*)" % var, text, re.M)
    if not m:
        return None
    out = []
    for part in m.group(1).split(","):
        part = part.strip()
        if not part:
            continue
        if part.startswith("$"):
            inner = _budget_members(text, part[1:].strip("{}"))
            if inner:
                out.extend(inner)
        else:
            out.append(part)
    return out


def _bench_count(text):
    """The RTL benches `make sim` runs, from tb/Makefile as it was written at that commit:
    the prerequisites of `sim:` (until 2026-09-12), SIM_BENCHES as a flat list, or
    SIM_BENCHES as the union of SIM_GROUP_n (since 2026-10-19). None if it cannot say."""
    text = text.replace("\\\n", " ")
    assigns = dict(re.findall(r"^([A-Za-z0-9_]+)[ \t]*=[ \t]*(.*)$", text, re.M))
    if "SIM_BENCHES" in assigns:
        value = assigns["SIM_BENCHES"].strip()
        if "$" not in value:
            return len(value.split())
        groups = assigns.get("SIM_GROUPS", "").split()
        if re.fullmatch(r"\$\(foreach (\w+),\$\(SIM_GROUPS\),\$\(SIM_GROUP_\$\(\1\)\)\)", value) and groups \
                and all("SIM_GROUP_" + g in assigns for g in groups):
            return sum(len(assigns["SIM_GROUP_" + g].split()) for g in groups)
        return None
    m = re.search(r"^sim:[ \t]*(.*)$", text, re.M)
    if m:
        words = [w for w in m.group(1).split() if not w.startswith("$")]
        return len(words)
    return None


def _ledger_edits(repo, as_of):
    """Where in the ledger the lines later deleted from it sat when they were deleted.

    docs/VALIDATION.md says it is append-only and that "an entry never edits
    history". The one measurement that tests it is how far from the END of the
    ledger each deleted line was: a restatement of the entry just written is at
    distance 0, an edit to a closed entry is not. Distance is counted in `## `
    entries in the PARENT's file, 0 meaning the newest. Every non-merge commit
    that touched the file is diffed against its parent (-U0), and every deleted
    line is placed by its own old line number."""
    path = "docs/VALIDATION.md"
    hist, outside, total = {}, [], 0
    deleting, says = 0, 0
    words = re.compile(r"restat|correct|verifier|made true|finding|send-back|fix", re.I)
    log = git(repo, "log", as_of, "--no-merges", "--reverse", "--format=%H|%P|%ad|%s",
              "--date=format:%Y-%m-%d", "--", path).splitlines()
    for line in log:
        sha, parent, day, subject = line.split("|", 3)
        if not parent:
            continue
        diff = git(repo, "diff", "-U0", "--no-renames", parent, sha, "--", path)
        olds = []
        for m in re.finditer(r"(?m)^@@ -(\d+)(?:,(\d+))? \+\d+(?:,\d+)? @@", diff):
            start = int(m.group(1))
            count = int(m.group(2)) if m.group(2) is not None else 1
            olds.extend(range(start, start + count))
        if not olds:
            continue
        deleting += 1
        says += 1 if words.search(subject) else 0
        before = git_show(repo, parent, path) or ""
        heads = [i + 1 for i, ln in enumerate(before.splitlines()) if ln.startswith("## ")]
        per_commit = {}
        for ln_no in olds:
            k = sum(1 for h in heads if h <= ln_no)          # the entry the line was in (0: the preamble)
            dist = len(heads) - k
            hist[dist] = hist.get(dist, 0) + 1
            per_commit[dist] = per_commit.get(dist, 0) + 1
            total += 1
        for dist, cnt in sorted(per_commit.items()):
            if dist > 0:
                outside.append({"commit": sha[:7], "day": day, "entries_from_end": dist, "lines": cnt})
    return {"deleted": total,
            "by_distance": {str(k): hist[k] for k in sorted(hist)},
            "not_the_newest": outside,
            "commits_deleting": deleting,
            "subjects_restating": says,
            "subject_words": words.pattern}


def make_tree(repo, as_of=BASE_COMMIT):
    """The tree at the end of each day: lines by area, the ledger, and the gate's size.

    The tree of a day is the first-parent tip of that day - main's own line, the
    commit a person on main would have checked out - the last one whose author
    date falls on or before the day; a day with none keeps the day before's."""
    fp = []
    for line in git(repo, "log", "--first-parent", "--reverse", "--format=%H|%ad",
                    "--date=format:%Y-%m-%d", as_of).splitlines():
        sha, day = line.split("|")
        fp.append((sha, day))
    days = _days_between(min(d for _, d in fp), max(d for _, d in fp))
    last_of = {}
    for sha, day in fp:
        last_of[day] = sha                      # history order: the later one wins
    tips, cur = [], None
    for d in days:
        cur = last_of.get(d, cur)
        tips.append(cur)
    line_ids = [a for a, _n, _p in AREAS] + [a for a, _n, _p in LINE_SLICES]
    lines = {a: [] for a in line_ids}
    files, ledger_lines, ledger_entries = [], [], []
    gates = {k: [] for k in ("stages", "quick", "gate", "benches", "proofs", "tests")}
    cache = {}
    for sha in tips:
        if sha in cache:
            row = cache[sha]
        else:
            counts = {a: 0 for a in line_ids}
            nfiles = 0
            for ln in git(repo, "grep", "-I", "-c", "", sha, "--", ".").splitlines():
                _rev, rest = ln.split(":", 1)
                path, cnt = rest.rsplit(":", 1)
                counts[line_area_of(path)] += int(cnt)
                nfiles += 1
            ledger = git_show(repo, sha, "docs/VALIDATION.md")
            run_sh = git_show(repo, sha, "verify/run.sh")
            tb = git_show(repo, sha, "tb/Makefile")
            formal = git_show(repo, sha, "formal/run.sh")
            tests = 0
            for ln in subprocess.run(
                    ["git", "-c", "core.quotepath=off", "-C", str(repo), "grep", "-c", "-E", r"^\s*def test_",
                     sha, "--", "python/tests"], capture_output=True).stdout.decode("utf-8", "replace").splitlines():
                tests += int(ln.rsplit(":", 1)[1])
            row = {
                "lines": counts, "files": nfiles,
                "ledger_lines": len(ledger.splitlines()) if ledger else 0,
                "ledger_entries": len(re.findall(r"(?m)^## ", ledger)) if ledger else 0,
                "stages": len(_COUNT_RE["stages"].findall(run_sh)) if run_sh else None,
                "quick": (len(_budget_members(run_sh, "BUDGET_QUICK") or []) or None) if run_sh else None,
                "gate": (len(_budget_members(run_sh, "BUDGET_GATE") or []) or None) if run_sh else None,
                "benches": _bench_count(tb) if tb else None,
                "proofs": (len(_COUNT_RE["proofs"].findall(formal)) or None) if formal else None,
                "tests": tests or None,
            }
            cache[sha] = row
        for a in line_ids:
            lines[a].append(row["lines"][a])
        files.append(row["files"])
        ledger_lines.append(row["ledger_lines"])
        ledger_entries.append(row["ledger_entries"])
        for k in gates:
            gates[k].append(row[k])
    # The ledger's line traffic over the whole history: lines ever added to and deleted from it.
    idx = {d: i for i, d in enumerate(days)}
    added, deleted = [0] * len(days), [0] * len(days)
    cur = None
    for line in git(repo, "log", as_of, "--no-renames", "--numstat", "--format=@%H|%ad",
                    "--date=format:%Y-%m-%d", "--", "docs/VALIDATION.md").splitlines():
        if line.startswith("@"):
            cur = idx[line[1:].split("|")[1]]
        elif line.strip() and cur is not None:
            a, d, _p = line.split("\t")
            added[cur] += int(a)
            deleted[cur] += int(d)
    data = {
        "as_of": as_of,
        "days": days,
        "tips": [t[:7] for t in tips],
        "line_areas": ([{"id": a, "name": nm} for a, nm, _p in AREAS]
                       + [{"id": a, "name": nm, "prefixes": list(pf)} for a, nm, pf in LINE_SLICES]),
        "lines": lines,
        "files": files,
        "ledger": {"lines": ledger_lines, "entries": ledger_entries, "added": added, "deleted": deleted,
                   "edits": _ledger_edits(repo, as_of)},
        "gates": gates,
    }
    return finish(
        "tree", "the tree at the end of each day on main's own line: text lines by area, the ledger's size "
                "and line traffic, and the size of the gate",
        as_of,
        [{"kind": "git", "as_of": as_of,
          "commands": ["git log --first-parent --reverse --format=%H|%ad --date=format:%Y-%m-%d AS_OF",
                       "git grep -I -c '' TIP -- .", "git show TIP:docs/VALIDATION.md, verify/run.sh, "
                       "tb/Makefile, formal/run.sh", "git grep -c -E '^\\s*def test_' TIP -- python/tests",
                       "git log AS_OF --no-renames --numstat -- docs/VALIDATION.md"]}],
        "python python/figure_extracts.py tree --as-of " + as_of, data)


# ---------------------------------------------------------- the card's timing record
LEDGER = "docs/VALIDATION.md"

# The U50 builds the ledger states a kernel slack for, with the entry each is in (a prefix of the
# entry's heading, which must match exactly one) and the pattern that finds the number in that entry
# (its first group; it must match once). The identification - which image, how many tiles, at what
# clock - is mine; the number is the pattern's capture, never typed. "Closed" is the ledger's own
# definition (docs/VALIDATION.md, 2026-09-23: a kernel WNS that is not negative). That this list is
# EVERY such build is not asserted here: it is held by the scan below (KERNEL_SLACK, LEFT_OUT), which
# a first version of this list failed, by seven builds, when a verifier made it.
CLOCK_SPECS = (
    # id, entry, tiles, MHz, pattern, label
    ("bac9f550-single", "2026-08-30 - card-day image pair at bac9f550", 1, 130,
     r"cft_hw_single\.xclbin\s+kernel_wns ([+-]\d+\.\d+) ns", "bac9f550 single"),
    ("bac9f550-quad", "2026-08-30 - card-day image pair at bac9f550", 4, 130,
     r"cft_hw_quad\.xclbin\s+kernel_wns ([+-]\d+\.\d+) ns", "bac9f550 quad"),
    ("ms-single", "2026-09-01 - the general-purpose milestone pair", 1, 130,
     r"cft_hw_single\.xclbin\s+kernel_wns ([+-]\d+\.\d+) ns", "b1a014c single"),
    ("ms-quad", "2026-09-01 - the general-purpose milestone pair", 4, 130,
     r"cft_hw_quad\.xclbin\s+kernel_wns ([+-]\d+\.\d+) ns", "b1a014c quad"),
    ("long-shot-260", "2026-08-31 - the 260 MHz attempt", 1, 260,
     r"WNS\s+([+-]\d+\.\d+) ns\s+\(target period 3\.846 ns\)", "260 MHz long shot"),
    ("control-130-single", "2026-08-31 - the 260 MHz attempt", 1, 130,
     r"130 MHz from the same tree closed at kernel_wns ([+-]\d+\.\d+)", "130 MHz control single (the 260 MHz tree)"),
    ("bracket-single-145", "2026-09-01 - the ceiling bracket completes", 1, 145,
     r"single @145\s+CLOSED\s+kernel_wns ([+-]\d+\.\d+)", "single at 145"),
    ("bracket-single-150", "2026-09-01 - the ceiling bracket completes", 1, 150,
     r"single @150\s+failed\s+WNS ([+-]\d+\.\d+)", "single at 150"),
    ("bracket-quad-145", "2026-09-01 - the ceiling bracket completes", 4, 145,
     r"quad\s+@145\s+failed\s+WNS ([+-]\d+\.\d+)", "quad at 145"),
    ("135-single", "2026-09-01 - the 135 MHz card-day pair closes", 1, 135,
     r"single @135\s+CLOSED\s+kernel_wns ([+-]\d+\.\d+)", "39fc2c0 single"),
    ("135-quad", "2026-09-01 - the 135 MHz card-day pair closes", 4, 135,
     r"quad\s+@135\s+CLOSED\s+kernel_wns ([+-]\d+\.\d+)", "39fc2c0 quad"),
    ("caserom-single", "2026-09-02 - the case-ROM single closes at 135 MHz", 1, 135,
     r"kernel worst path\s+([+-]\d+\.\d+) ns\s+s12_enorm_reg", "0e7264e single (case-ROM seed)"),
    ("tip-quad", "2026-09-02 - the tip quad closes at 135 MHz", 4, 135,
     r"kernel worst path\s+([+-]\d+\.\d+) ns\s+g_bank128 lane 0", "9f73107 quad (the tip)"),
    ("tip-single", "2026-09-02 - the tip single closes at 135 MHz", 1, 135,
     r"kernel worst path\s+([+-]\d+\.\d+) ns\s+op_r", "9f73107 single (the tip)"),
    ("ed752dd-single", "2026-09-07 - the card-day pair from ed752dd", 1, 135,
     r"cd135single[\s\S]*?kernel WNS ([+-]\d+\.\d+)", "ed752dd single"),
    ("ed752dd-quad", "2026-09-07 - the card-day pair from ed752dd", 4, 135,
     r"cd135quad[\s\S]*?kernel WNS ([+-]\d+\.\d+)", "ed752dd quad"),
    ("rev2-single", "2026-09-08 - the revision-2 pair on silicon", 1, 135,
     r"r2-135single[\s\S]*?kernel WNS ([+-]\d+\.\d+)", "revision 2 single"),
    ("rev2-quad", "2026-09-08 - the revision-2 pair on silicon", 4, 135,
     r"r2-135quad[\s\S]*?kernel WNS ([+-]\d+\.\d+)", "revision 2 quad"),
    ("rev3-single", "2026-09-08 (evening into 2026-09-09) - revision 3 integrated", 1, 135,
     r"r3-135single[\s\S]*?kernel WNS ([+-]\d+\.\d+)", "revision 3 single"),
    ("rev3-quad", "2026-09-08 (evening into 2026-09-09) - revision 3 integrated", 4, 135,
     r"r3-135quad[\s\S]*?kernel WNS ([+-]\d+\.\d+)", "revision 3 quad"),
    ("ra-single", "2026-09-09 - the read-ahead pair on silicon", 1, 135,
     r"ra-135single[\s\S]*?kernel WNS ([+-]\d+\.\d+)", "read-ahead single"),
    ("ra-quad", "2026-09-09 - the read-ahead pair on silicon", 4, 135,
     r"ra-135quad[\s\S]*?kernel WNS ([+-]\d+\.\d+)", "read-ahead quad"),
    ("rev4-single", "2026-09-13 - the revision-4 pair", 1, 135,
     r"\| single \| \d+ min \| \*\*([+-]\d+\.\d+)\*\*", "revision 4 single"),
    ("rev4-quad", "2026-09-13 - the revision-4 pair", 4, 135,
     r"\| quad \| \d+ min \| \*\*([+-]\d+\.\d+)\*\*", "revision 4 quad"),
    ("f64f128-single", "2026-09-14 - the fp64/fp128 tile on silicon", 1, 135,
     r"Kernel WNS ([+-]\d+\.\d+) ns at 135 MHz", "fp64/fp128 single"),
    ("seq5-single", "2026-09-14 - the first revision-5 image hung a compute unit", 1, 135,
     r"kernel WNS ([+-]\d+\.\d+) ns at 135 MHz", "revision 5 single (seq5)"),
    ("r14-single", "2026-09-14 - the R14 image's program costs", 1, 135,
     r"kernel WNS ([+-]\d+\.\d+) ns at 135 MHz", "R14 single"),
    ("seq6-single", "2026-09-14 - the seq6 image: revision 5 complete", 1, 135,
     r"kernel WNS ([+-]\d+\.\d+) ns at 135 MHz", "seq6 single"),
    ("round2-quad-first", "2026-09-16 - round 2's quad: the first implementation missed 135 MHz", 4, 135,
     r"kernel-side WNS ([+-]\d+\.\d+) ns", "round 2 quad, first try"),
    ("round2-single", "2026-09-16 - round 2's pair complete", 1, 135,
     r"single\s+1\s+135 MHz\s+([+-]\d+\.\d+) ns", "round 2 single"),
    ("round2-quad", "2026-09-16 - round 2's pair complete", 4, 135,
     r"quad\s+4\s+135 MHz\s+([+-]\d+\.\d+) ns", "round 2 quad, directive rebuild"),
    ("rev7b-single", "2026-09-29 - revision 7", 1, 135,
     r"The final single \(rev7b[\s\S]*?kernel WNS ([+-]\d+\.\d+) ns", "revision 7 single"),
    ("q135b-quad", "2026-09-30 - the steps 5 and 6 round", 4, 135,
     r"kernel_wns_ns (\d+\.\d+)\.", "revision 7 quad (q135b)"),
    ("rev8a-single", "2026-10-06 - step 6's closing records, part two", 1, 135,
     r"\| rev8a, the single \| 1 \| yes \| [\d,]+ \| 0x\w+ \| 0x\w+ \| ([+-]\d+\.\d+) ns \|", "revision 8 single (rev8a)"),
    ("rev8q-quad", "2026-10-06 - step 6's closing records, part two", 4, 135,
     r"\| rev8q, the streaming quad \| 4 \| no \| [\d,]+ \| 0x\w+ \| 0x\w+ \| ([+-]\d+\.\d+) ns \|",
     "revision 8 quad (rev8q)"),
    ("rev8d-deep", "2026-10-06 - step 6's closing records, part two", 1, 135,
     r"\| rev8d, the deep single \| 1 \| yes \| [\d,]+ \| 0x\w+ \| 0x\w+ \| ([+-]\d+\.\d+) ns \|",
     "revision 8 deep single (rev8d)"),
)
# the single tile's clock sweep, a table in one entry: | MHz | recipe | kernel WNS | on the card |
SWEEP_ENTRY = "2026-09-24 - the U50 single closes 175 MHz with the second recipe"
SWEEP_ROW = re.compile(r"(?m)^\| (\d+) \| (standard|ExtraTimingOpt / AggressiveExplore) \| "
                       r"(?:\*\*)?([+-]\d+\.\d+)(?:\*\*)? \| ([^|]*?) \|$")
# WHAT THE TIMING FIGURE DRAWS, AND WHAT THE CHECK CAN AND CANNOT SAY ABOUT THE REST OF THE LEDGER. The figure
# draws the builds in CLOCK_SPECS and the sweep's table: each is read by a pattern that names its entry and
# captures the slack the ledger states there. It does NOT claim these are all the builds the ledger gives a slack
# for: the ledger is twenty-one thousand lines of prose, and a build can be given a slack in a sentence, a table
# cell, a neighbour's entry or another repository's design. What this module does is account for STATEMENTS. A
# scan of the pinned prefix finds each line that pairs the word "kernel" with a worst-slack figure (KERNEL_SLACK)
# and each that gives a negative WNS (NEGATIVE_WNS); the number of every such statement must be the slack of a
# build drawn from that entry, or of an item of LEFT_OUT, which says what the statement is and why it is not drawn.
# make_ledger refuses an extract with a statement that is neither, and source_problems repeats the scan on the
# pinned prefix on every --check: a new statement of those two forms fails by name until it is drawn or listed. An
# entry is no longer the unit: the first version of this scan accounted for ENTRIES, which let a second build
# inside a drawn entry through (verifier-VFG found two). LEFT_OUT also lists, by hand (manual), builds the ledger
# gives a slack for in words the two patterns do not read: that is what a reader found, and it is not claimed to be
# complete.
KERNEL_SLACK = re.compile(
    r"(?i)kernel(?:'s)?[ _-]*(?:side[ _-]*)?(?:wns|slack|worst[ _-]+path)[^\n]{0,60}?[+-]\d+\.\d+"
    r"|kernel[^\n]{0,24}?[+-]\d+\.\d+\s*ns"
    r"|[+-]\d+\.\d+(?: ns)? in the kernel"
    r"|kernel\s+[+-]\d+\.\d+")
NEGATIVE_WNS = re.compile(
    r"(?i)(?:\bwns\b|kernel_wns|worst[- ]negative[- ]slack|\bslack\b)[^\n]{0,40}?(?<![\w.])-\d+\.\d+")
_SIGNED = re.compile(r"[+-]\d+\.\d+")

# The kinds of a left-out item, with the words a caption uses (in this order):
#   repeat         a drawn build's kernel slack, stated again in another entry (its number must equal the attempt's)
#   mention        a drawn build's kernel slack, named in passing in another build's entry or in a list
#   other-number   another number of a drawn build: its whole-design slack, an earlier stage of its run, another clock
#   whole-design   a miss recorded only with the whole design's slack, in an entry that gives no kernel slack
#   probe          an out-of-context run of the kernel or of a toy, not a build of an image
#   other-design   not this project's U50 image: another part, or another repository's design
#   text           a U50 build named only in running text: its slack is given without a table, a build block or a
#                  heading, and a pattern here reads it; `manual` says the scan's two patterns do not find it
KIND_WORDS = (("repeat", "repeats of a drawn build's slack"), ("mention", "mentions of one"),
              ("other-number", "other numbers of drawn builds (an earlier stage of a run, the whole design's, another "
                               "clock)"),
              ("whole-design", "misses recorded only with the whole design's slack"),
              ("probe", "out-of-context probes"), ("other-design", "figures of other designs and parts"),
              ("text", "builds named only in running text"))


def _lo(lid, kind, entry, pattern, why, same_as=None, tiles=None, mhz=None, group=1, many=False, manual=False,
        label=None):
    """One item of LEFT_OUT: `pattern` finds the number in the entry (group `group`; once, or more than once where
    `many`), and `same_as` names the attempt whose number a repeat or a mention must equal."""
    return {"id": lid, "kind": kind, "entry": entry, "pattern": pattern, "why": why, "same_as": same_as,
            "tiles": tiles, "mhz": mhz, "group": group, "many": many, "manual": manual, "label": label or lid}


_SWEEP_WHY = "the clock sweep's own entry for that point; the 24 Sep table's row is drawn"
LEFT_OUT = (
    # a drawn build's number, stated again
    _lo("round2-single-again", "repeat", "2026-09-15 - round 2's card day, second half", r"kernel WNS ([+-]\d+\.\d+)",
        "the same image as the 16 Sep table's row, stated a day earlier", same_as="round2-single"),
    _lo("sweep-145-entry", "repeat", "2026-09-23 - the U50 single closes 145 MHz", r"kernel WNS\s+([+-]\d+\.\d+) ns",
        _SWEEP_WHY, same_as="sweep-145-std"),
    _lo("sweep-150-entry", "repeat", "2026-09-23 - the U50 single closes 150 MHz", r"kernel WNS\s+([+-]\d+\.\d+) ns",
        _SWEEP_WHY, same_as="sweep-150-std"),
    _lo("sweep-155-entry", "repeat", "2026-09-23 - the U50 single closes 155 MHz", r"kernel WNS\s+([+-]\d+\.\d+) ns",
        _SWEEP_WHY, same_as="sweep-155-std"),
    _lo("sweep-160-entry", "repeat", "2026-09-23 - the U50 single closes 160 MHz", r"kernel WNS\s+([+-]\d+\.\d+) ns",
        _SWEEP_WHY, same_as="sweep-160-std"),
    _lo("sweep-165-entry", "repeat", "2026-09-23 - the U50 single closes 165 MHz", r"kernel WNS\s+([+-]\d+\.\d+) ns",
        _SWEEP_WHY, same_as="sweep-165-std"),
    _lo("sweep-170-entry", "repeat", "2026-09-24 - the U50 single closes 170 MHz", r"kernel WNS\s+([+-]\d+\.\d+) ns",
        _SWEEP_WHY, same_as="sweep-170-std"),
    _lo("rev8a-first", "repeat", "2026-10-06 - step 6's closing records, part one", r"Kernel WNS \*\*([+-]\d+\.\d+) ns\*\*",
        "the same image as part two's table row, stated in part one", same_as="rev8a-single"),
    # a drawn build's number, named in passing
    _lo("tip-quad-cited", "mention", "2026-09-30 - the fixes round",
        r'tip quad \(2026-09-02, "closes at 135 MHz: kernel ([+-]\d+\.\d+)"',
        "names the 2 Sep tip quad in a list of quads", same_as="tip-quad"),
    _lo("caserom-in-tip-single", "mention", "2026-09-02 - the tip single closes at 135 MHz",
        r"case-ROM single from 0e7264e \(kernel ([+-]\d+\.\d+)\)",
        "the entry's comparison with the case-ROM single, whose own entry is drawn", same_as="caserom-single"),
    _lo("round2-single-in-quad-entry", "mention", "2026-09-16 - round 2's quad", r"\(kernel ([+-]\d+\.\d+) ns, routed",
        "the round's single, named in the failing quad's entry as unaffected; its own row is drawn", same_as="round2-single"),
    # another number of a drawn build
    _lo("round2-quad-system-clock", "other-number", "2026-09-16 - round 2's quad", r"system-clock slack ([+-]\d+\.\d+) ns",
        "the failing quad's slack on the system clock, beside its kernel slack (-0.363, drawn)"),
    _lo("sweep-175-before-physopt", "other-number", "2026-09-24 - the U50 single closes 175 MHz with the second recipe",
        r"kernel WNS - ([+-]\d+\.\d+) ns, 92 failing endpoints",
        "the 175 MHz build's kernel WNS in the summary written before post-route phys_opt, which then closed it (+0.001, "
        "drawn)"),
    _lo("q135b-before-physopt", "other-number", "2026-09-30 - the steps 5 and 6 round",
        r"Routed WNS ([+-]\d+\.\d+), which Vitis's optional post-route phys_opt took to",
        "revision 7's quad's routed WNS before post-route phys_opt took it to +0.003 (drawn)"),
    _lo("rev8q-whole-design", "other-number", "2026-10-06 - step 6's closing records, part two",
        r"the whole design's routed WNS ([+-]\d+\.\d+) ns, shell included",
        "revision 8's quad's whole-design routed WNS, beside its kernel slack (drawn)"),
    _lo("rev8-routes", "other-number", "2026-10-06 - step 6's closing records, part two",
        r"after global iterations 0 to 3, ([+-]\d+\.\d+) \(TNS",
        "the first negative step of revision 8's quad's and deep single's routes, before their post-routing summaries "
        "(drawn)", many=True),
    # a miss recorded only with the whole design's slack
    _lo("single-ladders-135", "whole-design", "2026-09-01 - one ALU array", r"missed at \*\*WNS ([+-]\d+\.\d+) ns",
        "a single tile linked at 135 MHz with the ladders on; the entry gives the whole design's WNS (the worst path is "
        "in the kernel) and no kernel slack of its own", tiles=1, mhz=135, label="single, ladders on, 135 MHz"),
    _lo("quad-retimed-135", "whole-design", "2026-09-02 - the retimed quad at 135 MHz misses",
        r"routed WNS ([+-]\d+\.\d+)\s+TNS",
        "four tiles, retimed, no xclbin; the entry gives the whole design's routed WNS, the worst paths in the kernel, "
        "and no kernel slack of its own", tiles=4, mhz=135, label="quad, retimed, 135 MHz"),
    _lo("quad-plain-135", "whole-design", "2026-09-02 - the retimed quad at 135 MHz misses",
        r"without retiming: ([+-]\d+\.\d+) /",
        "the same four tiles without retiming; the entry gives the whole design's routed WNS and no kernel slack of its "
        "own (a later entry's judge calls build-diet-quad MISSED at the same number: see that item)", tiles=4, mhz=135,
        label="quad, not retimed, 135 MHz"),
    # out-of-context runs
    _lo("probes-s-k", "probe", "2026-10-05 - step 6's round 2: revision 8's sequencer in the tile",
        r"the kernel's WNS ([+-]\d+\.\d+)",
        "out-of-context runs of the kernel (probes S and K), not builds of an image", many=True),
    _lo("retiming-toys", "probe", "2026-10-12 - does RETIMING=1 retime?", r"WNS ([+-]\d+\.\d+)",
        "out-of-context toy pipelines for the retiming question, not builds", many=True),
    # not this project's U50 image
    _lo("seven-series-survey", "other-design", "2026-09-06 - the multi-cycle fp256 rung",
        r"WNS of ([+-]\d+\.\d+) - which is a far better clock",
        "a 7-series part survey (Kintex-7 325T at a 100 MHz ask), not the U50"),
    _lo("kintex-flows", "other-design", "2026-09-23 - the Kintex-7 in both flows",
        r"(?m)^\s+(?:synthesis|routed)\s+WNS ([+-]\d+\.\d+) ns", "the Kintex-7 325T in Vivado 2026.1, not the U50",
        many=True),
    _lo("f128x6-routed", "other-design", "2026-09-23 - hw/sweep_freq.sh rebuilt on build-pair",
        r"routed ([+-]\d+\.\d+) \(written", "a sibling repository's design (cft-rebound's build-hw-f128x6) built on the same "
        "box: its routed WNS, which the manifest recorded", manual=True, label="cft-rebound f128x6, routed"),
    _lo("f128x6-postroute", "other-design", "2026-09-23 - hw/sweep_freq.sh rebuilt on build-pair",
        r"post-route ([+-]\d+\.\d+) \(19:09\)", "the same sibling build's post-route WNS, 74 minutes later, after "
        "phys_opt", manual=True, label="cft-rebound f128x6, post-route"),
    # U50 builds named only in running text
    _lo("rev7a-probe-single", "text", "2026-09-29 - revision 7: control codes",
        r"The probe single \(rev7a, 3582de0, pre-fix\):\*\* kernel WNS ([+-]\d+\.\d+) ns",
        "a single tile's probe build before the fix; the entry states no clock for it (the final single beside it is at "
        "135 MHz)", tiles=1, label="rev7a probe single"),
    _lo("old-sweep-115", "text", "2026-09-23 - hw/sweep_freq.sh rebuilt on build-pair",
        r"same reports, had ([+-]\d+\.\d+), ([+-]\d+\.\d+) and ([+-]\d+\.\d+) ns",
        "a build of the first clock sweep (27f94cf), left on the box: the entry gives its whole-design WNS in a table and "
        "its kernel clock's slack in one sentence, by clock only; 115 MHz is below the chart's range", mhz=115, group=1,
        manual=True, label="first sweep, 115 MHz"),
    _lo("old-sweep-145", "text", "2026-09-23 - hw/sweep_freq.sh rebuilt on build-pair",
        r"same reports, had ([+-]\d+\.\d+), ([+-]\d+\.\d+) and ([+-]\d+\.\d+) ns",
        "the first clock sweep's 145 MHz build, in the same sentence", mhz=145, group=2, manual=True,
        label="first sweep, 145 MHz"),
    _lo("old-sweep-175", "text", "2026-09-23 - hw/sweep_freq.sh rebuilt on build-pair",
        r"same reports, had ([+-]\d+\.\d+), ([+-]\d+\.\d+) and ([+-]\d+\.\d+) ns",
        "the first clock sweep's 175 MHz build, which failed, in the same sentence", mhz=175, group=3, manual=True,
        label="first sweep, 175 MHz"),
    _lo("build-seq135s", "text", "2026-09-12 - two gates that could not fail",
        r"`build-seq135s` at \*\*([+-]\d+\.\d+)\*\*",
        "a sequencer build that did not close, named build-seq135s and limited by a sequencer path; its clock and tile "
        "count are not stated beyond the name", manual=True, label="build-seq135s"),
    _lo("single-045-earlier", "text", "2026-09-02 - the case-ROM single closes at 135 MHz",
        r"closed the same clock at ([+-]\d+\.\d+);",
        "the case-ROM single's predecessor, one commit earlier, stated in one clause without the word kernel", tiles=1,
        mhz=135, manual=True, label="single one commit earlier, 135 MHz"),
    _lo("single-045-table", "text", "2026-10-12 - does RETIMING=1 retime?",
        r"closes at ([+-]\d+\.\d+) with retiming and at ([+-]\d+\.\d+) without it",
        "a table cell that reads the single's +0.045 as two link builds, retiming on and off (the first number; the second "
        "is the same)", tiles=1, mhz=135, manual=True, label="single, retiming on, 135 MHz"),
    _lo("build-diet-quad", "text", "2026-09-23 - hw/sweep_freq.sh rebuilt on build-pair",
        r"called `build-diet-quad` MISSED at ([+-]\d+\.\d+)",
        "the sweep judge, which reads the kernel clock by name, calls this quad build MISSED; the number equals the 2 Sep "
        "unretimed quad's (listed above) and the ledger does not say they are the same build (BELIEVED that they are)",
        tiles=4, manual=True, label="build-diet-quad"),
)
# entries a figure marks as milestones: the entry's own heading is the evidence, its date the date
MILESTONES = (
    ("first-images", "2026-08-30 - card-day image pair at bac9f550", "the first card-day images (130 MHz)"),
    ("sequencer", "2026-09-02 - the sequencer passes on a device", "the sequencer runs on a device"),
    ("first-light", "2026-09-08 - card day: first light", "first light on the card"),
    ("clock-175", "2026-09-24 - the U50 single closes 175 MHz", "one tile closes 175 MHz"),
    ("rev8", "2026-10-06 - step 6's closing records, part two", "revision 8's three images on the card"),
    ("stress-driver", "2026-10-16 - the long-run stress driver", "the long-run stress driver"),
)


def _entries(text):
    """[(heading line without '## ', first line number, the entry's text)] for every '## ' heading."""
    lines = text.split("\n")
    marks = [i for i, ln in enumerate(lines) if ln.startswith("## ")]
    out = []
    for k, i in enumerate(marks):
        j = marks[k + 1] if k + 1 < len(marks) else len(lines)
        out.append((lines[i][3:], i + 1, "\n".join(lines[i:j])))
    return out


def _entry(entries, prefix):
    hits = [e for e in entries if e[0].startswith(prefix)]
    if len(hits) != 1:
        raise ExtractError("the ledger has %d entries headed %r (want exactly one)" % (len(hits), prefix))
    return hits[0]


def ledger_scan(text):
    """The statements of a ledger text that the two rules find, one per match, in ledger order:
    [(rule, entry_line, line, number, heading)] with the number as the ledger writes it. A statement is a line that
    pairs the word kernel with a worst-slack figure (KERNEL_SLACK) or gives a negative WNS (NEGATIVE_WNS); the number
    is the last signed decimal of the match. What the rules do not read, a scan cannot find."""
    out, seen = [], set()
    for head, line, body in _entries(text):
        for rule, rx in (("kernel", KERNEL_SLACK), ("negative", NEGATIVE_WNS)):
            for m in rx.finditer(body):
                nums = _SIGNED.findall(m.group(0))
                if not nums:
                    continue
                key = (rule, line, line + body[:m.start()].count("\n"), nums[-1])
                if key not in seen:
                    seen.add(key)
                    out.append(key + (head,))
    return sorted(out, key=lambda s: (s[2], s[0]))


def ledger_accounting(statements, attempts, left_out):
    """(problems, rows): every statement the scan found must carry the number of a build drawn from its entry or of an
    item listed from it, and a repeat or a mention must carry the number of the attempt it names. `rows` is what the
    extract stores - [rule, entry_line, line, number, id of the attempt or item that carries it] - so that --check can
    compare it with a fresh scan of the pinned prefix. The unit is the STATEMENT, and it is matched by its number within
    its entry: a second number that a drawn entry states is not covered by the first."""
    carried = {}
    for a in attempts:
        carried.setdefault((a["entry_line"], a["wns"]), a["id"])
    for item in left_out:
        if item["wns"] is not None:
            carried.setdefault((item["entry_line"], item["wns"]), item["id"])
    by_id = {a["id"]: a for a in attempts}
    problems, rows = [], []
    for rule, entry_line, line, number, head in statements:
        by = carried.get((entry_line, float(number)))
        if by is None:
            problems.append("the ledger states %s %s at line %d (the entry headed %r, line %d), which the extract neither "
                            "draws nor lists as left out (draw it in CLOCK_SPECS, or list it in LEFT_OUT with the reason)"
                            % ("a kernel slack" if rule == "kernel" else "a negative WNS", number, line, head[:60],
                               entry_line))
        else:
            rows.append([rule, entry_line, line, number, by])
    for item in left_out:
        if item["same_as"] is not None:
            a = by_id.get(item["same_as"])
            if a is None or item["wns"] != a["wns"]:
                problems.append("left-out item %s says %s where the attempt it repeats (%s) says %s" % (
                    item["id"], item["wns"], item["same_as"], None if a is None else a["wns"]))
    return problems, rows


def make_ledger(root=ROOT, existing=None):
    """The card's timing attempts and the ledger's milestones, read out of docs/VALIDATION.md.

    The ledger is append-only (its own rule, and a measurement of it is in the `tree` extract), so what
    is pinned is its first N bytes: appending an entry leaves the digest valid, editing an old one does
    not. N is the whole file the first time, and what the committed extract recorded when remaking it."""
    root = pathlib.Path(root)
    data = (root / LEDGER).read_bytes()
    if existing is not None and pathlib.Path(existing).is_file():
        n = json.loads(pathlib.Path(existing).read_text(encoding="utf-8"))["sources"][0]["bytes"]
    else:
        n = len(data)
    if len(data) < n:
        raise ExtractError("the ledger is shorter than the prefix its extract was read from")
    prefix = data[:n]
    text = prefix.decode("utf-8")
    entries = _entries(text)
    attempts = []
    for aid, entry, tiles, mhz, pat, label in CLOCK_SPECS:
        head, line, body = _entry(entries, entry)
        ms = list(re.finditer(pat, body))
        if len(ms) != 1:
            raise ExtractError("attempt %s: the pattern finds %d matches in the entry %r (want one)"
                               % (aid, len(ms), entry))
        wns = float(ms[0].group(1))
        attempts.append({"id": aid, "label": label, "date": head[:10], "tiles": tiles, "mhz": mhz, "wns": wns,
                         "closed": wns >= 0, "entry_line": line, "line": line + body[:ms[0].start()].count("\n"),
                         "recipe": "standard", "card": None})
    head, line, body = _entry(entries, SWEEP_ENTRY)
    rows = SWEEP_ROW.findall(body)
    if len(rows) != 8:
        raise ExtractError("the clock sweep's table has %d rows in %r (want 8)" % (len(rows), SWEEP_ENTRY))
    for mhz, recipe, wns, card in rows:
        w = float(wns)
        # each point's date is that of the entry headed "the U50 single closes N MHz": read, not assumed
        hits = [e for e in entries if re.match(r"\d{4}-\d{2}-\d{2} - the U50 single closes %s MHz" % mhz, e[0])]
        if len(hits) != 1:
            raise ExtractError("%d entries record the sweep's %s MHz point (want one)" % (len(hits), mhz))
        attempts.append({"id": "sweep-%s-%s" % (mhz, "std" if recipe == "standard" else "extra"),
                         "label": "single at %s, %s" % (mhz, "standard recipe" if recipe == "standard"
                                                         else "ExtraTimingOpt + AggressiveExplore"),
                         "date": hits[0][0][:10], "tiles": 1, "mhz": int(mhz),
                         "wns": w, "closed": w >= 0, "entry_line": line, "line": None,
                         "recipe": "standard" if recipe == "standard" else "second", "card": card.strip()})
    left_out = []
    for spec in LEFT_OUT:
        head, line, body = _entry(entries, spec["entry"])
        ms = list(re.finditer(spec["pattern"], body))
        if not ms or (len(ms) != 1 and not spec["many"]):
            raise ExtractError("left-out item %s: the pattern finds %d matches in the entry %r (want %s)" % (
                spec["id"], len(ms), spec["entry"], "one or more" if spec["many"] else "one"))
        for k, m in enumerate(ms):
            left_out.append({"id": spec["id"] if len(ms) == 1 else "%s-%d" % (spec["id"], k + 1), "kind": spec["kind"],
                             "manual": spec["manual"], "label": spec["label"], "date": head[:10],
                             "entry": head[:110], "entry_line": line, "line": line + body[:m.start()].count("\n"),
                             "tiles": spec["tiles"], "mhz": spec["mhz"], "wns": float(m.group(spec["group"])),
                             "same_as": spec["same_as"], "why": spec["why"]})
    problems, statements = ledger_accounting(ledger_scan(text), attempts, left_out)
    if problems:
        raise ExtractError("the timing record accounts for every statement its scan finds, and does not: "
                           + "; ".join(problems))
    accounting = {"kernel_rule": KERNEL_SLACK.pattern, "negative_rule": NEGATIVE_WNS.pattern,
                  "statements": statements}
    mil = []
    for mid, entry, label in MILESTONES:
        head, line, _ = _entry(entries, entry)
        mil.append({"id": mid, "label": label, "date": head[:10], "entry_line": line, "entry": head[:110]})
    # one sentence of the ledger's own that a figure quotes: its lesson about what slack at a met target means
    qhead, qline, qbody = _entry(entries, "2026-09-01 - the ceiling moves")
    qm = re.search(r"(an achieved-period reading from a hopelessly\s+over-constrained run understates what the "
                   r"router does for an\s+achievable target)", qbody)
    if not qm:
        raise ExtractError("the 2026-09-01 entry no longer holds the sentence about achieved-period readings")
    quotes = [{"entry": qhead[:60], "line": qline + qbody[:qm.start()].count("\n"),
               "text": " ".join(qm.group(1).split())}]
    data_ = {"attempts": attempts, "left_out": left_out, "accounting": accounting, "milestones": mil, "quotes": quotes,
             "entries": len(entries), "prefix_lines": text.count("\n")}
    return finish(
        "ledger", "the U50 builds whose kernel slack the figures read from the ledger (kernel WNS by image, tiles and "
                  "clock), the other slacks it gives and why each is not drawn, the scan that accounts for every "
                  "statement its two patterns find, and the ledger's milestones, read out of docs/VALIDATION.md by "
                  "patterns that name the entry",
        "the first %d bytes of docs/VALIDATION.md (sha256 below)" % n,
        [{"kind": "file-prefix", "path": LEDGER, "bytes": n, "sha256": sha256_bytes(prefix)}],
        "python python/figure_extracts.py ledger", data_, label="ledger, first %s bytes" % "{:,}".format(n))


# ----------------------------------------------------- the card's stress run
# Which sweep operations exercise the card's tile, and which run in libcft's host code on the
# box's CPU beside the card with the card idle. Read, not believed: host/src/clause5.c's header
# lists COMPOSED = cft_rint, cft_scaleb, cft_cmp_sig (their floating-point work is cft_run()
# passes, and the file has exactly two cft_run call sites) and HOST = cft_convert, the integer
# conversions, cft_logb, cft_next_*, cft_class, cft_total_order*, cft_rem; and
# host/tools/divsqrt_soak.c's lib_call calls cft_div and cft_sqrt. project_figures.py re-reads
# those two files on every --check and fails by name if they stop saying so.
#
# THIS TABLE COVERS THE OPS OF THE ITEMS THE RUN SERVED, AND ONLY THOSE (card-stress-1016 served 68
# items of hw/card_stress_lib.py's catalog, 14 exhaustive and 54 random). The catalog is the library's
# and grows: soak-exhaustive adds twenty-two exhaustive items (conv32to64-all, cvtto32-all,
# cvtfrom32-all, cvtfrom64-all, scaleb32-all, scaleb32-wide) and its own table of the same fact,
# OP_REACH, which knows their ops and this one does not. make_stress therefore reduces the run's items
# (served_items) and, where the library has OP_REACH, holds the served ops to it.
STRESS_TILE_OPS = ("sqrt32", "div32", "div64", "sqrt64", "rint32", "rint64", "scaleb32", "scaleb64")
STRESS_TEL = {
    "power_w": "electrical.devices[0].electrical.power_consumption_watts",
    "fpga_c": "thermal.devices[0].thermals.FPGA.temp_C",
    "intvcc_c": "thermal.devices[0].thermals.Int Vcc.temp_C",
    "pcb_front_c": "thermal.devices[0].thermals.PCB Top Front.temp_C",
    "pcb_rear_c": "thermal.devices[0].thermals.PCB Top Rear.temp_C",
    "hbm_c": "thermal.devices[0].thermals.FPGA HBM.temp_C",
}


def _median(vals):
    import statistics
    return statistics.median(vals) if vals else None


def served_items(catalog, legs):
    """{name: item} of the catalog's items that the run served - at least one sweep slice that passed or failed - in
    the catalog's order. The catalog is the library's list of everything the driver can run, and it grows; the
    reduction is of the RUN, so an item the run never served is not in it: not a row, not a coverage list (an
    exhaustive item with no slice has no last coverage point, which broke this reduction once, when a later catalog
    added items this run never served)."""
    served = {r["sweep"]["item"] for r in legs if r.get("kind") == "sweep" and r.get("status") in ("pass", "fail")}
    return {it.name: it for it in catalog if it.name in served}


def _decoys(catalog):
    """Items the run never served, of the three kinds a later catalog brings, made as copies of real ones under new
    names: an exhaustive item of a served op, a random one, and an exhaustive one of an op nothing here knows. Only
    attributes are set after the copy, so a library whose Item looks its op up in a table is not asked to."""
    import copy
    ex = next(it for it in catalog if it.kind == "exhaustive")
    rn = next(it for it in catalog if it.kind == "random")
    out = []
    for base, name, op in ((ex, ex.name + "-decoy", None), (rn, rn.name + "-decoy", None),
                           (ex, "decoy-unknown-op", "zz-unknown-op32")):
        d = copy.copy(base)
        d.name = name
        if op:
            d.op = op
        out.append(d)
    return out


def _report_facts(text):
    """The numbers hw/card_stress_report.py printed in report.txt that the reduction can be held to."""
    facts = {}
    m = re.search(r"^legs\s+: (\d+) recorded; pass (\d+), fail (\d+), timeout (\d+), no_device (\d+), "
                  r"parse_error (\d+), skipped (\d+), error (\d+)", text, re.M)
    if not m:
        raise ExtractError("report.txt has no 'legs :' totals line")
    facts["legs"] = int(m.group(1))
    facts["pass"] = int(m.group(2))
    facts["skipped"] = int(m.group(7))
    facts["not_pass_or_skipped"] = sum(int(m.group(i)) for i in (3, 4, 5, 6, 8))
    m = re.search(r"^cycles\s+: (\d+) started, (\d+) ended", text, re.M)
    if not m:
        raise ExtractError("report.txt has no 'cycles :' line")
    facts["cycles"] = int(m.group(1))
    facts["sweep_cases"] = {}
    for m in re.finditer(r"^\s+(quad|single|deep)\s+sweep \(all items\)\s+\d+\s+\d+(?:\s+0){6}\s+(\d+)\s*$", text, re.M):
        facts["sweep_cases"][m.group(1)] = int(m.group(2))
    m = re.search(r"covered (\d+) of (\d+) encodings", text)
    if not m:
        raise ExtractError("report.txt has no exhaustive coverage line")
    facts["covered"], facts["encodings"] = int(m.group(1)), int(m.group(2))
    return facts


def make_stress(metrics, root=ROOT, report=None, decoys=False):
    """The long stress run, reduced. `metrics` is the run's metrics.jsonl (never committed);
    `report` is its report.txt, which the reduction is held to when given. `decoys` gives the library's catalog items
    the run never served (see _decoys): the reduction must not change by a byte, which --verify holds."""
    import collections
    root = pathlib.Path(root)
    metrics = pathlib.Path(metrics)
    raw = metrics.read_bytes()
    sys.path.insert(0, str(root / "hw"))
    try:
        import card_stress_lib as L
        import card_stress_report as R
    finally:
        sys.path.pop(0)
    recs, partial, bad = L.read_records(str(metrics))
    if partial or bad:
        raise ExtractError("metrics.jsonl has a torn or unparseable line (partial tail %s, bad lines %s): "
                           "reduce a run that has ended" % (partial, bad[:5]))
    by = collections.defaultdict(list)
    for r in recs:
        by[r.get("type")].append(r)
    if len(by["run_start"]) != 1 or len(by["run_end"]) != 1:
        raise ExtractError("the run has %d run_start and %d run_end records; a reduction needs a finished "
                           "run, started once" % (len(by["run_start"]), len(by["run_end"])))
    rs, re_ = by["run_start"][0], by["run_end"][0]
    t0 = float(rs["epoch"])

    def off(e):
        return int(round(float(e) - t0))
    catalog = list(L.sweep_items())
    if decoys:
        catalog += _decoys(catalog)
    items = served_items(catalog, by["leg"])
    host_ops = sorted({it.op for it in items.values()} - set(STRESS_TILE_OPS))
    reach = getattr(L, "OP_REACH", None)          # the library's own table of the same fact, where it has one
    if reach is not None:
        wrong = sorted(op for op in {it.op for it in items.values()}
                       if reach.get(op) != ("tile" if op in STRESS_TILE_OPS else "host"))
        if wrong:
            raise ExtractError("the library's OP_REACH and STRESS_TILE_OPS disagree about the served op%s %s: %s there, "
                               "%s here" % ("" if len(wrong) == 1 else "s", ", ".join(wrong),
                                            ", ".join(str(reach.get(op)) for op in wrong),
                                            ", ".join("tile" if op in STRESS_TILE_OPS else "host" for op in wrong)))
    legs = [r for r in by["leg"]]
    ran = [r for r in legs if r["status"] != "skipped"]
    status = collections.Counter(r["status"] for r in legs)
    # cycles, with where the battery ended and the sweep began
    ends = {r["cycle"]: r for r in by["cycle_end"]}
    cycles = []
    for c in by["cycle_start"]:
        e = ends.get(c["cycle"])
        if e is None:
            raise ExtractError("cycle %d started and never ended" % c["cycle"])
        batt = [r for r in ran if r["cycle"] == c["cycle"] and r["kind"] == "battery"]
        cycles.append({"n": c["cycle"], "image": c["image"], "start_s": off(c["epoch"]),
                       "battery_end_s": off(max(r["end_epoch"] for r in batt)) if batt else off(c["epoch"]),
                       "end_s": off(e["epoch"]), "legs": e["legs"], "failed": e["failed"]})
    spans = [(c["start_s"], c["end_s"], c["image"]) for c in cycles]

    def image_at(s):
        for a, b, img in spans:
            if a <= s <= b:
                return img
        return None
    # the battery legs, by image
    matrix = []
    for img in ("quad", "single", "deep"):
        names = []
        for r in legs:
            if r["image"] == img and r["kind"] == "battery" and r["leg"] not in names:
                names.append(r["leg"])
        for nm in names:
            rows = [r for r in legs if r["image"] == img and r["kind"] == "battery" and r["leg"] == nm]
            good = [r for r in rows if r["status"] == "pass"]
            rates = [r["rate"]["value"] for r in good if r.get("rate")]
            units = sorted({r["rate"]["unit"] for r in good if r.get("rate")})
            reasons = sorted({r["reason"] for r in rows if r["status"] == "skipped" and r.get("reason")})
            matrix.append({
                "image": img, "leg": nm, "runs": len(rows), "pass": len(good),
                "skipped": sum(1 for r in rows if r["status"] == "skipped"),
                "other": sum(1 for r in rows if r["status"] not in ("pass", "skipped")),
                "seconds_median": round(_median([r["duration_s"] for r in good]) or 0, 3) if good else None,
                "rate_median": round(_median(rates), 3) if rates else None,
                "rate_unit": units[0] if len(units) == 1 else None,
                "checks": sum((r.get("counts") or {}).get("checks", 0) for r in good) or None,
                "skip_reason": reasons[0] if reasons else None})
    # the telemetry
    tel = [r for r in by["telemetry"] if r.get("values")]
    for key, label in STRESS_TEL.items():
        if label not in tel[0]["values"]:
            raise ExtractError("telemetry has no %r" % label)
    series = {"t_s": [off(r["epoch"]) for r in tel], "when": [r["when"] for r in tel],
              "image": [image_at(off(r["epoch"])) for r in tel]}
    for key, label in STRESS_TEL.items():
        series[key] = [round(r["values"][label], 3) if label in r["values"] else None for r in tel]
    power = series["power_w"]
    peak_i = max(range(len(power)), key=lambda i: power[i])
    pk = tel[peak_i]["epoch"]
    active = [r["leg"] for r in ran if r["kind"] == "battery" and r["start_epoch"] <= pk <= r["end_epoch"]]
    by_image = {}
    for img in ("quad", "single", "deep"):
        v = [power[i] for i in range(len(power)) if series["image"][i] == img]
        by_image[img] = {"n": len(v), "median": round(_median(v), 3), "min": min(v), "max": max(v)}
    # what was running when each sample was taken: the one thing the card's power could follow besides the image
    sweeps_run = [r for r in ran if r["kind"] == "sweep"]
    batt_run = [r for r in ran if r["kind"] == "battery"]

    def activity_at(epoch):
        if any(r["leg"] == "resident" and r["start_epoch"] <= epoch <= r["end_epoch"] for r in batt_run):
            return "cft-resident leg"
        if any(r["start_epoch"] <= epoch <= r["end_epoch"] for r in batt_run):
            return "other battery leg"
        act = [r for r in sweeps_run if r["start_epoch"] <= epoch <= r["end_epoch"]]
        if any(r["sweep"]["op"] in STRESS_TILE_OPS for r in act):
            return "sweep, with tile items"
        if act:
            return "sweep, host items only"
        return "between legs"
    ACTS = ("between legs", "other battery leg", "cft-resident leg", "sweep, host items only", "sweep, with tile items")
    cell = collections.defaultdict(list)
    for i, r in enumerate(tel):
        cell[(series["image"][i], activity_at(r["epoch"]))].append(power[i])
    by_activity = {img: {a: {"n": len(cell[(img, a)]), "median": round(_median(cell[(img, a)]), 3)}
                         for a in ACTS if cell.get((img, a))} for img in ("quad", "single", "deep")}
    telemetry = dict(series, power_by_image=by_image, power_by_activity=by_activity,
                     peak={"watts": power[peak_i], "t_s": series["t_s"][peak_i], "image": series["image"][peak_i],
                           "battery_leg_running": active[0] if active else None},
                     hbm_zero_samples=sum(1 for v in series["hbm_c"] if v == 0.0))
    # the sweep
    swl = [r for r in ran if r["kind"] == "sweep" and r["status"] in ("pass", "fail")]
    per_item = collections.OrderedDict((n, {"slices": 0, "cases": 0, "images": collections.Counter()})
                                       for n in items)
    mism = 0
    hourly_end = max(off(r["end_epoch"]) for r in swl)
    for r in swl:
        nm = r["sweep"]["item"]
        if nm not in items:
            raise ExtractError("a sweep leg for %s, which hw/card_stress_lib.py does not list" % nm)
        d = per_item[nm]
        d["slices"] += 1
        d["cases"] += r["counts"]["cases"]
        d["images"][r["image"]] += 1
        mism += r["counts"].get("value_mismatches", 0) + r["counts"].get("flag_mismatches", 0)
        if r["status"] != "pass":
            mism += 1

    def unit_of(op):
        return "tile" if op in STRESS_TILE_OPS else "host"
    item_rows = []
    for nm, it in items.items():
        d = per_item[nm]
        item_rows.append({"item": nm, "op": it.op, "mode": it.mode, "kind": it.kind, "unit": unit_of(it.op),
                          "slices": d["slices"], "cases": d["cases"], "on": dict(sorted(d["images"].items()))})
    totals = collections.defaultdict(int)
    for row in item_rows:
        totals[(row["unit"], row["kind"])] += row["cases"]
    # coverage of the exhaustive items, slice by slice
    coverage = {}
    for nm, it in items.items():
        if it.kind != "exhaustive":
            continue
        rows = sorted((r for r in swl if r["sweep"]["item"] == nm), key=lambda r: r["end_epoch"])
        iv, pts = [], []
        for r in rows:
            iv.append((int(r["sweep"]["lo"]), int(r["sweep"]["hi"])))
            pts.append([off(r["end_epoch"]), L.covered(iv)])
        coverage[nm] = pts
    # cumulative cases by the hour, tile and host apart
    hours = list(range(0, hourly_end // 3600 + 2))
    cum = {"tile": [], "host": []}
    ordered = sorted(swl, key=lambda r: r["end_epoch"])
    for u in cum:
        k, acc, series_u = 0, 0, []
        sel = [r for r in ordered if unit_of(r["sweep"]["op"]) == u]
        for h in hours:
            while k < len(sel) and off(sel[k]["end_epoch"]) <= h * 3600:
                acc += sel[k]["counts"]["cases"]
                k += 1
            series_u.append(acc)
        cum[u] = series_u
    # rates by op and image
    rates = collections.defaultdict(list)
    for r in swl:
        if r.get("rate"):
            rates[(r["sweep"]["op"], r["image"])].append(r["rate"]["value"])
    rate_rows = [{"op": op, "image": img, "unit": unit_of(op), "slices": len(v), "median": round(_median(v), 1)}
                 for (op, img), v in sorted(rates.items())]
    # held to the run's own reduction (hw/card_stress_report.py), computed here from the same records
    S = R.summarize(recs, now=float(re_["epoch"]))
    covered_total = sum(pts[-1][1] for pts in coverage.values())
    cross = [
        {"what": "legs recorded", "mine": len(legs), "report_module": S["totals"]["legs"]["total"]},
        {"what": "legs passed", "mine": status["pass"], "report_module": S["totals"]["legs"]["by_status"]["pass"]},
        {"what": "legs skipped", "mine": status["skipped"], "report_module": S["totals"]["legs"]["by_status"]["skipped"]},
        {"what": "cycles", "mine": len(cycles), "report_module": S["totals"]["cycles"]["ended"]},
        {"what": "exhaustive encodings covered", "mine": covered_total,
         "report_module": S["sweep"]["total_exhaustive"]["covered"]},
        {"what": "sweep slices completed", "mine": len(swl), "report_module": S["sweep"]["completed"]},
    ]
    sources = [{"kind": "raw", "name": "metrics.jsonl", "sha256": sha256_bytes(raw), "bytes": len(raw),
                "records": len(recs)}]
    if report is not None:
        rtxt = pathlib.Path(report).read_text(encoding="utf-8")
        facts = _report_facts(rtxt)
        cross += [
            {"what": "legs recorded (report.txt)", "mine": len(legs), "report_txt": facts["legs"]},
            {"what": "legs passed (report.txt)", "mine": status["pass"], "report_txt": facts["pass"]},
            {"what": "legs skipped (report.txt)", "mine": status["skipped"], "report_txt": facts["skipped"]},
            {"what": "cycles (report.txt)", "mine": len(cycles), "report_txt": facts["cycles"]},
            {"what": "exhaustive encodings covered (report.txt)", "mine": covered_total,
             "report_txt": facts["covered"]},
        ]
        for img in ("quad", "single", "deep"):
            cross.append({"what": "sweep cases on %s (report.txt)" % img,
                          "mine": sum(r["counts"]["cases"] for r in swl if r["image"] == img),
                          "report_txt": facts["sweep_cases"].get(img)})
        sources.append({"kind": "raw", "name": "report.txt", "sha256": sha256_bytes(rtxt.encode("utf-8")),
                        "bytes": len(rtxt.encode("utf-8"))})
    for c in cross:
        other = [v for k, v in c.items() if k not in ("what", "mine")][0]
        if other != c["mine"]:
            raise ExtractError("the reduction disagrees with the run's own report on %s: %s here, %s there"
                               % (c["what"], c["mine"], other))
    data = {
        "run": {"id": rs["run_id"], "commit": rs["tree"]["commit"], "tree_dirty": rs["tree"]["dirty"],
                "started": rs["ts"], "ended": re_["ts"], "end_reason": re_["reason"], "exit": re_["exit"],
                "seconds": off(re_["epoch"]), "clock": "the box's local time, as the records give it",
                "deadline": rs["settings"]["until"], "weights": rs["settings"]["weights"],
                "sweep_minutes": rs["settings"]["sweep_minutes"], "telemetry_seconds": 300,
                "visits": dict(collections.Counter(c["image"] for c in cycles))},
        "images": {k: {"sha256": v["sha256"], "tiles": v["tiles"], "target": v["target"]}
                   for k, v in rs["images"].items()},
        "legs": {"total": len(legs), "battery": sum(1 for r in legs if r["kind"] == "battery"),
                 "sweep": sum(1 for r in legs if r["kind"] == "sweep"),
                 "by_status": {k: status.get(k, 0) for k in ("pass", "fail", "timeout", "no_device",
                                                              "parse_error", "skipped", "error")}},
        "cycles": cycles,
        "matrix": matrix,
        "telemetry": telemetry,
        "sweep": {
            "tile_ops": list(STRESS_TILE_OPS), "host_ops": host_ops,
            "items": item_rows,
            "mismatches": mism,
            "cases": {"tile_exhaustive": totals[("tile", "exhaustive")], "tile_random": totals[("tile", "random")],
                      "host_exhaustive": totals[("host", "exhaustive")], "host_random": totals[("host", "random")]},
            "encodings_per_item": L.EXH,
            "coverage": coverage,
            "cumulative_hours": hours, "cumulative_cases": cum,
            "rates": rate_rows,
        },
        "crosschecks": cross,
    }
    return finish(
        "stress", "the card's long stress run (card-stress-1016), reduced from its metrics.jsonl: the legs, "
                  "the cycles, the telemetry, and the sweep with its tile items and host items apart",
        "the raw file's own digest (below); the run ended " + re_["ts"] + " on the box's clock",
        sources, "python python/figure_extracts.py stress PATH/metrics.jsonl --report PATH/report.txt", data,
        label="run ended " + re_["ts"])


# ------------------------------------------------------------------- the CLI
MAKERS = {"history": make_history, "tree": make_tree}    # the ones that read git; more are added below


def _write(out, name, ex):
    text = dumps(ex)
    p = extract_path(out, name)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8", newline="") as fh:
        fh.write(text)
    return p, text


def main(argv):
    import argparse
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("which", nargs="?", choices=["history", "tree", "ledger", "stress", "all"],
                    help="the extract to remake; `all` is history, tree and ledger (stress needs its raw file)")
    ap.add_argument("metrics", nargs="?", help="stress: the run's metrics.jsonl (never committed)")
    ap.add_argument("--report", help="stress: the run's report.txt, which the reduction is held to")
    ap.add_argument("--as-of", default=BASE_COMMIT, help="the commit to read git at (default: the pinned base)")
    ap.add_argument("--repo", default=str(ROOT), help="the repository to read git from")
    ap.add_argument("--out", default=str(ROOT), help="the root whose docs/figures to write, and whose tree "
                                                     "the ledger and stress readers read")
    ap.add_argument("--extend", action="store_true",
                    help="ledger: pin the prefix to the whole current file, to read entries appended since (the "
                         "default keeps the prefix the committed extract recorded, so a remake changes only what "
                         "the patterns read)")
    ap.add_argument("--verify", action="store_true",
                    help="remake each extract from its source and compare the bytes with the committed one "
                         "(history and tree need the full git history; stress needs --stress-metrics)")
    ap.add_argument("--stress-metrics", help="--verify: the raw metrics.jsonl, to remake the stress extract")
    ap.add_argument("--stress-report", help="--verify: the run's report.txt")
    a = ap.parse_args(argv)
    if a.which is None and not a.verify:
        ap.error("name an extract, or use --verify")
    names = ["history", "tree", "ledger"] if a.which in (None, "all") else [a.which]
    if a.verify and a.which in (None, "all") and a.stress_metrics:
        names.append("stress")
    bad = 0
    for name in names:
        try:
            if name in ("history", "tree"):
                ex = MAKERS[name](a.repo, a.as_of)
                how = "git at %s" % a.as_of[:12]
            elif name == "ledger":
                ex = make_ledger(a.out, existing=(extract_path(a.out, "ledger") if (a.verify or not a.extend) else None))
                how = "the ledger's %s prefix" % ("whole current" if a.extend and not a.verify else "recorded")
            else:
                metrics = a.stress_metrics if a.verify else a.metrics
                if not metrics:
                    print("figure_extracts: stress needs the raw metrics.jsonl (the run's, never committed)",
                          file=sys.stderr)
                    return 1
                ex = make_stress(metrics, a.out, a.stress_report if a.verify else a.report)
                how = "the raw metrics.jsonl"
        except ExtractError as e:
            print("figure_extracts: %s: %s" % (name, e), file=sys.stderr)
            return 1
        if a.verify:
            p = extract_path(a.out, name)
            have = p.read_text(encoding="utf-8") if p.is_file() else None
            if have == dumps(ex):
                print("ok      %s remakes byte for byte from %s" % (name, how))
            else:
                print("DIFFERS %s: the committed extract is not what its source gives" % name)
                bad += 1
            if name == "stress":
                # the control: the library's catalog grows, and an item the run never served must not move a byte
                # (or break the reduction, which is what an unserved exhaustive item did to it once)
                try:
                    ex2 = make_stress(metrics, a.out, a.stress_report, decoys=True)
                except Exception as e:          # whatever a catalog adds must not be able to break the reduction
                    print("DIFFERS stress (control): the reduction broke on catalog items the run never served: %s: %s"
                          % (type(e).__name__, e))
                    bad += 1
                else:
                    if dumps(ex2) == dumps(ex):
                        print("ok      stress is unchanged by catalog items the run never served (3 decoys: an "
                              "exhaustive item of a served op, a random one, an exhaustive one of an unknown op)")
                    else:
                        print("DIFFERS stress (control): catalog items the run never served changed the reduction")
                        bad += 1
        else:
            p, text = _write(a.out, name, ex)
            print("wrote  %s (%d bytes; %s)" % (p.relative_to(pathlib.Path(a.out)).as_posix(),
                                                         len(text.encode("ascii")), ex["read_at_label"]))
    if a.verify and a.which in (None, "all") and not a.stress_metrics:
        print("note: stress not verified here: its source is the raw metrics.jsonl (pass --stress-metrics)")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
