# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""The census of cft-audit's plants: each refusal the tool raises,
disabled alone, must turn the equality gate red, naming it (the audit
round's brief, P1; the census practice of the certificate round).

    python host/tests/audit_check.py --tool ... --segrun ... --cc CC
                                     --lib-src SRC --record CASES
    python host/tests/audit_plants.py --record CASES --cc CC
                                      --lib-src SRC [--copy DIR]

In a FRESH COPY of host/ - never in the tree - every call of refuse()
and malformed() in tools/audit.c becomes a numbered SITE that
CFT_AUDIT_PLANT_SITE=<n> skips, as if its check had passed, and that
names itself on stderr when it refuses. Two binaries are built from the
copy: the tool, and the narrow build (CFT_MAX_FORMAT=2) for the one site
only it compiles.

Then:
  1. every recorded case is replayed with no plant, and must give the
     verdict the gate recorded - so the copy is the tool - and the site
     that refused it is noted;
  2. each site is planted in turn and ITS cases replayed - a plant can
     change a case only where the case reaches its refuse() call, and
     only the cases that refused there did - until one differs from the
     golden verdict: RED, with the case and what the gate would print;
  3. a site whose cases all still agree is GREEN: another check refuses
     each of them by the same name at the same place; a site no case
     reaches is UNREACHED, green by construction, and named.

Exit 0 when every site is red; the report names every one that is not.
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
HOST = HERE.parent
sys.path.insert(0, str(HERE))

import audit_check as ac  # noqa: E402  (tool_verdict, same, compile_with)

SITE = re.compile(r"^cft-audit: site (\d+)$", re.M)
CALL = re.compile(r"\b(refuse|malformed)\s*\(")
TIMEOUT = 20


def instrument(src):
    """tools/audit.c's text -> (text with every refuse()/malformed() call
    a numbered site, [(site, name, line in the original)])."""
    # the two functions keep their bodies under new names; the calls
    # inside them are the functions' own, not sites
    src = src.replace("static void refuse(", "static void refuse_real(")
    src = src.replace("static void malformed(", "static void malformed_real(")
    # malformed_real's own call of refuse is not a site
    m = re.search(r"static void malformed_real\(long long line, const char "
                  r"\*fmt, \.\.\.\)\n\{.*?\n\}\n", src, re.S)
    body = m.group(0)
    src = src.replace(body, body.replace('refuse("malformed"',
                                         'refuse_real("malformed"'))
    # NORETURN off: a function that refused and now returns must be
    # well defined (refuse_real still exits, since it calls exit())
    src = src.replace("#  define NORETURN __attribute__((noreturn))",
                      "#  define NORETURN")
    # the sites, found in code only - not in comments or strings
    out, sites, i, line, n = [], [], 0, 1, len(src)
    state = "code"
    while i < n:
        c = src[i]
        if state == "code":
            if src.startswith("/*", i):
                state, out = "block", out + ["/*"]
                i += 2
                continue
            if src.startswith("//", i):
                state = "line"
            elif c == '"':
                state = "str"
            elif c == "'":
                state = "chr"
            else:
                mm = CALL.match(src, i)
                prev = src[i - 1] if i else " "
                if mm and not (prev.isalnum() or prev == "_"):
                    fn = mm.group(1)
                    sid = len(sites) + 1
                    rest = src[mm.end():mm.end() + 60]
                    nm = re.match(r'\s*"([a-z-]+)"', rest)
                    name = "malformed" if fn == "malformed" else \
                        (nm.group(1) if nm else "?")
                    sites.append((sid, name, line))
                    out.append(f"PLANT_{fn.upper()}({sid}, ")
                    i = mm.end()
                    continue
        elif state == "block":
            if src.startswith("*/", i):
                state, out = "code", out + ["*/"]
                i += 2
                continue
        elif state == "line":
            if c == "\n":
                state = "code"
        elif state == "str":
            if c == "\\":
                out.append(src[i:i + 2])
                line += src[i:i + 2].count("\n")
                i += 2
                continue
            if c == '"':
                state = "code"
        elif state == "chr":
            if c == "\\":
                out.append(src[i:i + 2])
                i += 2
                continue
            if c == "'":
                state = "code"
        out.append(c)
        if c == "\n":
            line += 1
        i += 1
    text = "".join(out)
    hook = r"""
static int plant_hit(int id)
{
    static int want = -2;
    if (want == -2) {
        const char *s = getenv("CFT_AUDIT_PLANT_SITE");
        want = s && *s ? atoi(s) : -1;
    }
    return id == want;
}
#define PLANT_REFUSE(id, ...) do { if (!plant_hit(id)) { \
    fprintf(stderr, "cft-audit: site %d\n", (id)); \
    refuse_real(__VA_ARGS__); } } while (0)
#define PLANT_MALFORMED(id, ...) do { if (!plant_hit(id)) { \
    fprintf(stderr, "cft-audit: site %d\n", (id)); \
    malformed_real(__VA_ARGS__); } } while (0)
"""
    # after refuse_real's definition, before the first site
    at = text.index("/* A library call that failed where no refusal names")
    text = text[:at] + hook + "\n" + text[at:]
    return text, sites


def replay(exe, cdir, case, plant=None):
    env = dict(os.environ)
    for k in ("CFT_AUDIT_PLANT", "CFT_AUDIT_PLANT_SITE"):
        env.pop(k, None)
    env.update(case["env"])
    if plant is not None:
        env["CFT_AUDIT_PLANT_SITE"] = str(plant)
    try:
        r = subprocess.run([str(exe)] + case["args"], cwd=str(cdir),
                           capture_output=True, text=True, env=env,
                           timeout=TIMEOUT)
        rc, out, err = r.returncode, r.stdout, r.stderr
    except subprocess.TimeoutExpired:
        rc, out, err = -1, "", f"ran past {TIMEOUT} s"
    m = SITE.search(err)
    return ac.tool_verdict(rc, out, err), (int(m.group(1)) if m else None)


def want_of(w):
    kind, det = w
    if kind == "refused":
        return "refused", (det[0], det[1], tuple(det[2]))
    return kind, det


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--record", required=True,
                    help="the cases audit_check.py --record wrote")
    ap.add_argument("--cc", required=True)
    ap.add_argument("--lib-src", required=True)
    ap.add_argument("--copy", help="where the fresh copy goes (default a "
                    "temporary directory, removed at the end)")
    ap.add_argument("--only", help="plant these sites only, comma-separated")
    args = ap.parse_args()
    t_all = time.perf_counter()
    rec = Path(args.record).resolve()
    cases = []
    for d in sorted(rec.iterdir()):
        j = d / "case.json"
        if j.is_file():
            c = json.loads(j.read_text(encoding="utf-8"))
            c["dir"] = d
            c["want"] = want_of(c["want"])
            cases.append(c)
    print(f"audit_plants: {len(cases)} recorded cases in {rec}", flush=True)

    # a fresh copy of host/'s sources, never the tree
    copy = Path(args.copy).resolve() if args.copy else \
        Path(tempfile.mkdtemp(prefix="audit-plants-"))
    for sub in ("src", "include", "tools", "gen"):
        if (HOST / sub).is_dir():
            shutil.copytree(HOST / sub, copy / sub, dirs_exist_ok=True)
    text, sites = instrument((HOST / "tools" / "audit.c").read_text(
        encoding="utf-8"))
    (copy / "tools" / "audit.c").write_bytes(text.encode("utf-8"))
    print(f"  {len(sites)} refusal sites in tools/audit.c, instrumented in "
          f"{copy}", flush=True)
    exes = {}
    for which, defs in (("tool", []), ("narrow", [
            "-DCFT_MAX_FORMAT=2", "-DCFT_NO_TRANSCEND",
            "-DCFT_NO_CONFORMANCE"])):
        exe = copy / (f"planted-{which}" + (".exe" if os.name == "nt"
                                            else ""))
        env = dict(os.environ)
        first = args.cc.split()[0]
        if os.path.dirname(first):
            env["PATH"] = os.path.dirname(first) + os.pathsep + env["PATH"]
        r = subprocess.run(args.cc.split() + ["-std=c99", "-O2", "-w"] + defs +
                           ["-Iinclude"] + args.lib_src.split() +
                           ["tools/audit.c", "-o", str(exe)], cwd=str(copy),
                           capture_output=True, text=True, env=env)
        if r.returncode != 0:
            sys.exit(f"audit_plants: the {which} copy does not build: "
                     f"{r.stderr[-800:]}")
        exes[which] = exe

    # 1. the baseline: the copy is the tool, and which site refused each
    t0 = time.perf_counter()
    by_site, bad = {}, []
    for c in cases:
        t, site = replay(exes[c["binary"]], c["dir"], c)
        agree, why = ac.same(c["want"], t, c.get("read_only", False))
        if not agree:
            bad.append(f"{c['label']}: {why}")
        if site is not None:
            by_site.setdefault(site, []).append(c)
    print(f"  the baseline: {len(cases) - len(bad)} of {len(cases)} cases "
          f"give their recorded verdict through the copy "
          f"({time.perf_counter() - t0:.0f} s)", flush=True)
    if bad:
        for b in bad[:10]:
            print(f"    FAIL  {b}")
        sys.exit("audit_plants: the instrumented copy is not the tool")

    # 2. each site planted alone
    only = {int(x) for x in args.only.split(",")} if args.only else None
    red, green, unreached = [], [], []
    for sid, name, line in sites:
        if only and sid not in only:
            continue
        mine = by_site.get(sid, [])
        if not mine:
            unreached.append((sid, name, line))
            continue
        hit = None
        for c in mine:
            t, _ = replay(exes[c["binary"]], c["dir"], c, plant=sid)
            agree, why = ac.same(c["want"], t, c.get("read_only", False))
            if not agree:
                hit = (c["label"], why)
                break
        if hit:
            red.append((sid, name, line, hit))
        else:
            green.append((sid, name, line, len(mine)))
    total = len(sites) if not only else len(only)
    print(f"== the census: {total} sites; {len(red)} red, {len(green)} "
          f"green, {len(unreached)} unreached "
          f"({time.perf_counter() - t_all:.0f} s)", flush=True)
    for sid, name, line, (label, why) in red:
        why = why.replace("\n", " | ")
        print(f"  red        site {sid:3d} {name:22s} audit.c:{line}: "
              f"{label[:70]} - {why[:160]}")
    for sid, name, line, n in green:
        print(f"  GREEN      site {sid:3d} {name:22s} audit.c:{line}: its "
              f"{n} case(s) refused the same way with it disabled")
    for sid, name, line in unreached:
        print(f"  UNREACHED  site {sid:3d} {name:22s} audit.c:{line}: no "
              f"recorded case reaches it")
    if not args.copy:
        shutil.rmtree(copy, ignore_errors=True)
    return 0 if not green and not unreached else 1


if __name__ == "__main__":
    sys.exit(main())
