#!/usr/bin/env python3
# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""The soak tools' pass-size build, held to what it says (host/Makefile, "The soak tools at another pass size";
docs/CARDDAY.md, "The soak at a larger pass size").

    python3 host/tests/soak_chunk_check.py [--only GROUP,...] [--baseline-tree DIR] [--keep] [--verbose]

It lives with host's other build and tool checks because what it tests is host/Makefile's SOAK_CHUNK targets and the
two tools' compile-time BATCH; hw/'s tests (HC, CL) drive the tools and need the stress driver's library. POSIX with
make and a C compiler (the soak needs a 64-bit Linux), skipped by name elsewhere; the `ignore` group needs git only.
It builds in a scratch copy of host/ (Makefile, include, src, tools, examples) and runs niced, one process at a time:
  refuse     make's own refusals, by name, at parse time: SOAK_CHUNK unset, empty, or not a positive multiple of 4096
             up to 65536 (twelve values, among them 0x4000 and 016384, and the empty string), several words, and a goal that names another
             size; every value that is allowed passes a dry run; and a SOAK_CHUNK that is garbage changes nothing about
             the default goals (the same dry run as with none)
  recipe     the dry run of `soak-chunk` with XRT=1 XRT_ROOT=... C5DEFS=...: every library object compiled
             -DCFT_CHUNK=n into soak-c<n>/, the archive libcft-c<n>.a made of exactly the library's objects (the XRT one
             too), each tool compiled -DCFT_CHUNK=n -DBATCH=n and linked against that archive and not libcft.a, the XRT
             link line and C5DEFS carried through, and nothing of the default build named
  build      the real build at 16384 and at 8192: the products exist; everything the build made is under a name of its
             own (the default libcft.a, objects and tools are not made); the two sizes coexist
  passes     a probe linked against each archive with the linker's --wrap=cft_run sees the pass size the library really
             has - 16384, 8192, and 4096 for the default - for cft_div, cft_sqrt, cft_rint and cft_scaleb
  tools      the chunked tools' stderr names BATCH and CFT_CHUNK on a line of its own after the backend line, the
             default tools' stderr is the backend line alone, and a build at 4096 is the default's output byte for
             byte; stdout is the same at every size for 15 invocations; sabotage fails at every size
  clean      `make clean` removes the products of every size (binaries, archives, object directories) and the tree is
             as it was, with files whose names only resemble them still there
  ignore     git ignores every product, so a build leaves the next build id untracked=none
  unchanged  (with --baseline-tree DIR, a directory holding the baseline's host/ - `git archive REV host | tar -x
             -C DIR`) the default tools of that tree and of this one print the same bytes and exit with the same
             status over 40 invocations, sabotage and usage errors among them; the default goals' dry runs are the
             same text; and the two tools' objects, compiled with the Makefile's flags, are byte for byte the same
  plants     one defect in a scratch copy for each class of check, red at the check written for it, each preceded by a
             CONTROL that the unplanted copy passes: the library built without -DCFT_CHUNK (the tool still says
             16384 and only the probe sees 4096), the tool built without -DBATCH, the tool linked against libcft.a,
             the validation removed, `clean` leaving the object directory, and the stderr line printed at the defaults

Prints one line a group and a last line "soak-chunk test: N checks, F failed, S skipped".
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
HOST = os.path.dirname(HERE)
ROOT = os.path.dirname(HOST)

VERBOSE = "--verbose" in sys.argv
CHECKS = 0
FAILS: list = []
SKIPS: list = []
NICE = ["nice", "-n", "10"] if shutil.which("nice") else []
CHUNK = 16384
OK_VALUES = [4096 * k for k in range(1, 17)]
EXTRA = "soaking with BATCH %d and CFT_CHUNK %d (the defaults are 4096)\n"
BACKEND = "soaking the software backend\n"


def check(name: str, ok: bool, detail: str = "") -> bool:
    global CHECKS
    CHECKS += 1
    if not ok:
        FAILS.append(f"{name}: {detail}")
        print(f"  FAIL  {name}  {detail}"[:520])
    elif VERBOSE:
        print(f"  ok    {name}"[:400])
    return bool(ok)


def skip(name: str, why: str) -> None:
    SKIPS.append(f"{name}: {why}")
    print(f"  SKIP  {name} - {why}")


def sh(argv, cwd=None, env=None, timeout=900):
    e = dict(os.environ)
    e.pop("CFT_SOAK_SABOTAGE", None)
    e.pop("CFT_SOAK_ARTIFACT", None)
    e.update(env or {})
    p = subprocess.run(argv, cwd=cwd, capture_output=True, text=True, timeout=timeout, env=e)
    return p.returncode, p.stdout, p.stderr


def make(host, *args, nice=True, timeout=900):
    return sh((NICE if nice else []) + ["make", "--no-print-directory", "-C", host] + list(args), timeout=timeout)


def copy_host(dst_root: str, src_host: str = HOST) -> str:
    """The part of host/ the soak build needs, in dst_root/host. A copy, so the real tree is never built in."""
    dst = os.path.join(dst_root, "host")
    os.makedirs(dst)
    shutil.copy2(os.path.join(src_host, "Makefile"), dst)
    # sources only: a host/ that has been built in must not bring its objects into a tree that is to be "pristine"
    skip_built = shutil.ignore_patterns("*.o", "*.lo", "*.a", "*.so", "*.exe", "gen")
    for d in ("include", "src", "tools", "examples"):
        shutil.copytree(os.path.join(src_host, d), os.path.join(dst, d), copy_function=shutil.copy2, ignore=skip_built)
    return dst


def snapshot(host: str) -> set:
    out = set()
    for dp, dn, fn in os.walk(host):
        for f in fn:
            out.add(os.path.relpath(os.path.join(dp, f), host))
        for d in dn:
            out.add(os.path.relpath(os.path.join(dp, d), host) + "/")
    return out


def joined(text: str) -> str:
    return text.replace("\\\n", " ")


# ---------------------------------------------------------------------------------------------------
# the probe: the pass size of a libcft archive, seen from outside
# ---------------------------------------------------------------------------------------------------
PROBE_C = r'''
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include "cft.h"
cft_status __real_cft_run(cft_device *, cft_op, cft_format, cft_round, const void *, const void *, const void *,
                          void *, size_t, uint32_t *, uint32_t *);
static size_t passes, largest;
cft_status __wrap_cft_run(cft_device *dev, cft_op op, cft_format fmt, cft_round rnd, const void *a, const void *b,
                          const void *c, void *d, size_t n, uint32_t *fl, uint32_t *bus)
{
    passes++;
    if (n > largest) largest = n;
    return __real_cft_run(dev, op, fmt, rnd, a, b, c, d, n, fl, bus);
}
static int report(const char *what, cft_status st, size_t n)
{
    printf("%s n=%zu passes=%zu largest=%zu%s\n", what, n, passes, largest, st == CFT_OK ? "" : " FAILED");
    passes = largest = 0;
    return st == CFT_OK ? 0 : 1;
}
int main(int argc, char **argv)
{
    size_t n = argc > 1 ? (size_t)strtoull(argv[1], NULL, 0) : 0, i;
    cft_device *dev;
    float *a, *b, *d;
    uint32_t fl;
    int rc = 0;
    if (!n || cft_open(NULL, 0, &dev) != CFT_OK) return 2;
    a = malloc(n * 4); b = malloc(n * 4); d = malloc(n * 4);
    if (!a || !b || !d) return 2;
    for (i = 0; i < n; i++) { a[i] = 1.5f + (float)(i % 7); b[i] = 3.0f + (float)(i % 5); }
    rc |= report("div32", cft_div(dev, CFT_FP32, CFT_RNE, a, b, d, n, &fl, NULL), n);
    rc |= report("sqrt32", cft_sqrt(dev, CFT_FP32, CFT_RNE, a, d, n, &fl, NULL), n);
    rc |= report("rint32", cft_rint(dev, CFT_FP32, CFT_RNE, 0, a, d, n, &fl, NULL), n);
    rc |= report("scaleb32", cft_scaleb(dev, CFT_FP32, CFT_RNE, a, 3, d, n, &fl, NULL), n);
    cft_close(dev);
    return rc;
}
'''


def probe(host: str, lib: str, n: int, work: str):
    """(problems, {op: (passes, largest)}) of the archive `lib` (a name in host/) over n operands."""
    src = os.path.join(work, "probe.c")
    exe = os.path.join(work, "probe-" + lib.replace(".", "_"))
    with open(src, "w") as f:
        f.write(PROBE_C)
    rc, out, err = sh(["cc", "-std=c99", "-O2", "-Iinclude", src, lib, "-Wl,--wrap=cft_run", "-o", exe, "-lm"], cwd=host)
    if rc != 0:
        return [f"the probe did not link against {lib}: {err[-300:]}"], {}
    rc, out, err = sh(NICE + [exe, str(n)])
    got = {}
    for m in re.finditer(r"^(\w+) n=(\d+) passes=(\d+) largest=(\d+)$", out, re.M):
        got[m.group(1)] = (int(m.group(3)), int(m.group(4)))
    if rc != 0 or sorted(got) != ["div32", "rint32", "scaleb32", "sqrt32"]:
        return [f"the probe of {lib} exited {rc} and printed {out[-200:]!r}"], got
    return [], got


# ---------------------------------------------------------------------------------------------------
# the checks, each over a tree and returning its problems (so a plant can be held to one)
# ---------------------------------------------------------------------------------------------------
def problems_refuse(host: str) -> list:
    bad = []
    cases = [(None, "unset or empty"), ("", "unset or empty")]
    cases += [(v, f"SOAK_CHUNK={v} is refused") for v in
              ("4097", "0", "-4096", "abc", "8191", "65537", "69632", "131072", "0x4000", "016384", "16384 8192",
               "4096.0")]
    for v, want in cases:
        args = ["-n", "soak-chunk"] if v is None else ["-n", f"SOAK_CHUNK={v}", "soak-chunk"]
        rc, out, err = make(host, *args, nice=False)
        text = out + err
        if rc == 0:
            bad.append(f"SOAK_CHUNK={v!r} was accepted")
        elif want not in text:
            bad.append(f"SOAK_CHUNK={v!r} was refused without saying {want!r}: {text[-200:]!r}")
        elif "-DCFT_CHUNK" in text:
            bad.append(f"SOAK_CHUNK={v!r} was refused after a compile line was printed")
    rc, out, err = make(host, "-n", "SOAK_CHUNK=16384", "divsqrt-soak-c8192", nice=False)
    if rc == 0 or "divsqrt-soak-c8192" not in out + err or "SOAK_CHUNK=16384" not in out + err:
        bad.append(f"a goal naming another size was not refused naming both: rc {rc}: {(out + err)[-200:]!r}")
    for target in ("divsqrt-soak-c16384", "clause5-soak-c16384", "libcft-c16384.a"):
        rc, out, err = make(host, "-n", target, nice=False)
        if rc == 0 or "unset or empty" not in out + err:
            bad.append(f"`make {target}` with no SOAK_CHUNK was not refused as unset: rc {rc}")
    return bad


def problems_allowed(host: str) -> list:
    bad = []
    for v in OK_VALUES:
        rc, out, err = make(host, "-n", f"SOAK_CHUNK={v}", "soak-chunk", nice=False)
        text = joined(out)
        if rc != 0 or f"-DCFT_CHUNK={v} -DBATCH={v}" not in text or f"libcft-c{v}.a" not in text:
            bad.append(f"SOAK_CHUNK={v} did not give a dry run of the chunked tools: rc {rc}: {err[-200:]!r}")
    return bad


def problems_default_goals(host: str) -> list:
    bad = []
    for goal in ("all", "divsqrt-soak", "clause5-soak", "libcft.a"):
        ref = make(host, "-n", goal, nice=False)
        for v in ("bad", "16384", "4097", ""):
            got = make(host, "-n", f"SOAK_CHUNK={v}", goal, nice=False)
            if got != ref:
                bad.append(f"`make -n {goal}` differs with SOAK_CHUNK={v!r}")
    return bad


def problems_recipe(host: str) -> list:
    bad = []
    rc, out, err = make(host, "print-src", nice=False)
    srcs = out.split()
    rc, out, err = make(host, "-n", "SOAK_CHUNK=16384", "XRT=1", "XRT_ROOT=/opt/x/xrt",
                        "C5DEFS=-DCFT_SOAK_HAVE_ROUNDEVEN=1", "soak-chunk", nice=False)
    if rc != 0:
        return [f"the dry run with XRT=1 failed: {err[-300:]}"]
    text = joined(out)
    lines = [ln.strip() for ln in text.splitlines()]
    objs = ["soak-c16384/" + s.rsplit(".", 1)[0] + ".o" for s in srcs] + ["soak-c16384/src/backend_xrt.o"]
    for s in srcs + ["src/backend_xrt.cpp"]:
        o = "soak-c16384/" + s.rsplit(".", 1)[0] + ".o"
        cc = [ln for ln in lines if f"-c {s} -o {o}" in ln]
        if len(cc) != 1:
            bad.append(f"{s}: {len(cc)} compile lines into {o}")
        elif "-DCFT_CHUNK=16384" not in cc[0]:
            bad.append(f"{s} is compiled into {o} without -DCFT_CHUNK=16384")
        elif s.endswith(".cpp") and "-isystem /opt/x/xrt/include" not in cc[0]:
            bad.append("the XRT object is compiled without XRT_ROOT's include")
    ar = [ln for ln in lines if ln.startswith("ar rcs libcft-c16384.a ")]
    if len(ar) != 1 or sorted(ar[0].split()[3:]) != sorted(objs):
        bad.append(f"the archive is not made of exactly the library's objects (the XRT one too): {ar}")
    if "rm -f libcft-c16384.a" not in lines:
        bad.append("the archive is not removed before it is made (ar rcs only adds)")
    for tool, src, c5 in (("divsqrt-soak-c16384", "tools/divsqrt_soak.c", False),
                          ("clause5-soak-c16384", "tools/clause5_soak.c", True)):
        link = [ln for ln in lines if f"-o {tool}" in ln]
        if len(link) != 1:
            bad.append(f"{tool}: {len(link)} link lines")
            continue
        ln = link[0]
        for need in ("-DCFT_CHUNK=16384", "-DBATCH=16384", src, "-fno-math-errno", "-frounding-math",
                     "-L/opt/x/xrt/lib -lxrt_coreutil"):
            if need not in ln:
                bad.append(f"{tool}'s line lacks {need}")
        words = ln.split()
        if "libcft-c16384.a" not in words:
            bad.append(f"{tool} is not linked against libcft-c16384.a")
        if "libcft.a" in words:
            bad.append(f"{tool} is linked against the default libcft.a")
        if ("-DCFT_SOAK_HAVE_ROUNDEVEN=1" in ln) != c5:
            bad.append(f"{tool}: C5DEFS {'is lost' if c5 else 'reached the wrong tool'}")
    # whole words only: soak-c16384/src/bigint.o is the chunked build's, src/bigint.o is the default's
    named = [ln for ln in lines if any(w in ("libcft.a", "divsqrt-soak", "clause5-soak") or re.fullmatch(r"src/\w+\.o", w)
                                       for w in ln.split())]
    if named:
        bad.append(f"the dry run names the default build: {named[:2]}")
    # where EXE is .exe (Windows) the binaries carry it, and the name without it is an alias that reaches the same rule
    rc, out, err = make(host, "-n", "EXE=.exe", "SOAK_CHUNK=16384", "soak-chunk", nice=False)
    text = joined(out)
    if rc != 0 or "-o divsqrt-soak-c16384.exe" not in text or "-o clause5-soak-c16384.exe" not in text:
        bad.append(f"with EXE=.exe the tools are not named with it: rc {rc}")
    for goal in ("divsqrt-soak-c16384", "divsqrt-soak-c16384.exe", "clause5-soak-c16384"):
        rc, out, err = make(host, "-n", "EXE=.exe", "SOAK_CHUNK=16384", goal, nice=False)
        if rc != 0:
            bad.append(f"with EXE=.exe the goal {goal} is refused: {err[-120:]}")
    return bad


def problems_tools(host: str, n: int, with_stdout: bool = True) -> list:
    """The tools built at n: stderr, and (against the default tools in the same tree) stdout."""
    bad = []
    d_div, d_c5 = os.path.join(host, "divsqrt-soak"), os.path.join(host, "clause5-soak")
    c_div, c_c5 = os.path.join(host, f"divsqrt-soak-c{n}"), os.path.join(host, f"clause5-soak-c{n}")
    want_err = BACKEND if n == 4096 else BACKEND + EXTRA % (n, n)
    for tool, args in ((c_div, ["div32", "20000", "1", "rne"]), (c_c5, ["rint32", "0", "20000", "rne"])):
        rc, out, err = sh(NICE + [tool] + args)
        if rc != 0 or err != want_err:
            bad.append(f"{os.path.basename(tool)}'s stderr is {err!r}, not {want_err!r}")
    for tool in (d_div, d_c5):
        a = ["div32", "20000", "1", "rne"] if tool == d_div else ["rint32", "0", "20000", "rne"]
        rc, out, err = sh(NICE + [tool] + a)
        if rc != 0 or err != BACKEND:
            bad.append(f"the DEFAULT {os.path.basename(tool)}'s stderr is {err!r}, not the backend line alone")
    if not with_stdout:
        return bad
    runs = [("div", ["div32", "40000", "1", "rne"]), ("div", ["div64", "40000", "2", "rtz"]),
            ("div", ["sqrt64", "40000", "3", "rup"]), ("div", ["sqrt32", "0", "40000", "rmm"]),
            ("div", ["sqrt32", str(0x3F7FF000), str(0x3F7FF000 + 40000), "rdn"]),
            ("div", ["div32-hard", "0", "20481", "rne"]), ("div", ["sqrt64-hard", "0", "20481", "rmm"]),
            ("c5", ["rint32", "0", "40000", "rne"]), ("c5", ["rint64", "40000", "4", "rtz"]),
            ("c5", ["scaleb32", str(17 * 32768), "5", "rne"]), ("c5", ["scaleb64", str(27 * 32768), "6", "rdn"]),
            ("c5", ["cvtto32-all", "0", "40000", "rup"]), ("c5", ["rem32", "40000", "7"]),
            ("c5", ["rint64-class", "0", "5000", "rne"]), ("c5", ["scaleb64-class", "0", "5000", "rtz"])]
    for which, args in runs:
        dflt, chunk = (d_div, c_div) if which == "div" else (d_c5, c_c5)
        a = sh(NICE + [dflt] + args)
        b = sh(NICE + [chunk] + args)
        if a[0] != 0 or b[0] != a[0] or b[1] != a[1] or not a[1].strip():
            bad.append(f"{' '.join(args)}: rc {a[0]} / {b[0]}, stdout {a[1]!r} / {b[1]!r}")
    for which, args in (("div", ["div32", "30000", "1", "rne"]), ("c5", ["rint32", "0", "30000", "rne"]),
                        ("c5", ["scaleb64", str(27 * 32768), "6", "rdn"])):
        tool = c_div if which == "div" else c_c5
        rc, out, err = sh(NICE + [tool] + args, env={"CFT_SOAK_SABOTAGE": "1"})
        m = re.search(r"(\d+) value mismatches, (\d+) flag mismatches", out)
        if rc != 1 or not m or int(m.group(1)) + int(m.group(2)) == 0:
            bad.append(f"{' '.join(args)} under sabotage at {n}: rc {rc}, {out[-120:]!r} - the build cannot fail")
    return bad


def problems_clean(host: str, pristine: set, decoys: dict) -> list:
    bad = []
    for name, content in decoys.items():
        path = os.path.join(host, name)
        os.makedirs(os.path.dirname(path) or host, exist_ok=True)
        with open(path, "w") as f:
            f.write(content)
    keep = pristine | {n for n in decoys} | {os.path.dirname(n) + "/" for n in decoys if os.path.dirname(n)}
    before = snapshot(host)
    rc, out, err = make(host, "clean", nice=False)
    if rc != 0:
        bad.append(f"make clean exited {rc}: {err[-200:]}")
    after = snapshot(host)
    left = sorted(after - keep)
    gone = sorted(keep - after)
    if left:
        bad.append(f"clean left {left[:6]}")
    if gone:
        bad.append(f"clean removed what it did not make: {gone[:6]}")
    if not (before - keep):
        bad.append("nothing was built before the clean, so it removed nothing")
    return bad


# ---------------------------------------------------------------------------------------------------
# the groups
# ---------------------------------------------------------------------------------------------------
def group_refuse(base: str) -> None:
    host = copy_host(os.path.join(base, "refuse"))
    bad = problems_refuse(host)
    check("refuse: every refusal is by name and at parse time (unset, empty, 12 values, a goal at another size)",
          not bad, "; ".join(bad))
    bad = problems_allowed(host)
    check(f"refuse: all {len(OK_VALUES)} values that are positive multiples of 4096 up to 65536 give a dry run", not bad,
          "; ".join(bad))
    bad = problems_default_goals(host)
    check("refuse: a SOAK_CHUNK that is garbage, empty or valid changes no default goal's dry run", not bad, "; ".join(bad))


def group_recipe(base: str) -> None:
    host = copy_host(os.path.join(base, "recipe"))
    bad = problems_recipe(host)
    check("recipe: XRT=1, XRT_ROOT and C5DEFS pass through, every object and tool has its size and its own archive",
          not bad, "; ".join(bad))


def group_build(base: str, state: dict) -> None:
    host = copy_host(os.path.join(base, "build"))
    state["host"] = host
    state["pristine"] = snapshot(host)
    t0 = time.time()
    rc, out, err = make(host, "-j4", "SOAK_CHUNK=16384", "soak-chunk")
    check("build: make SOAK_CHUNK=16384 soak-chunk builds", rc == 0, (out + err)[-400:])
    if rc != 0:
        return
    after = snapshot(host)
    new = after - state["pristine"]
    mine = {"libcft-c16384.a", "divsqrt-soak-c16384", "clause5-soak-c16384"}
    stray = sorted(n for n in new if n not in mine and not n.startswith(("soak-c16384", "gen")))
    check("build: the chunked tools, their archive and their object directory exist",
          mine <= new and "soak-c16384/src/divsqrt.o" in new, f"missing {sorted(mine - new)}")
    check("build: everything the build made has a name of its own (no libcft.a, src/*.o or default tool is made)",
          not stray, f"made {stray[:6]}")
    warn = [ln for ln in (out + err).splitlines() if "warning" in ln.lower()]
    check("build: no warning but gcc's own note on the STDC FENV_ACCESS pragma, which the default build gives too",
          all("FENV_ACCESS" in w for w in warn), f"{[w for w in warn if 'FENV_ACCESS' not in w][:3]}")
    rc, out, err = make(host, "-j4", "SOAK_CHUNK=8192", "soak-chunk")
    check("build: a second size, 8192, builds beside the first", rc == 0 and os.path.exists(
        os.path.join(host, "divsqrt-soak-c8192")) and os.path.exists(os.path.join(host, "divsqrt-soak-c16384")),
          (out + err)[-300:])
    rc, out, err = make(host, "-j4", "SOAK_CHUNK=4096", "soak-chunk")
    check("build: 4096, the default's own sizes, builds as a control", rc == 0, (out + err)[-300:])
    rc, out, err = make(host, "-j4", "divsqrt-soak", "clause5-soak")
    check("build: the default tools build in the same tree", rc == 0, (out + err)[-300:])
    print(f"      (built in {time.time() - t0:.0f} s)")


def group_passes(base: str, state: dict) -> None:
    host = state.get("host")
    if not host or not os.path.exists(os.path.join(host, "libcft-c16384.a")):
        skip("passes", "no build")
        return
    rc, out, err = make(host, "libcft.a")
    n = 65545
    got = {}
    for lib, want in (("libcft.a", 4096), ("libcft-c16384.a", 16384), ("libcft-c8192.a", 8192)):
        bad, res = probe(host, lib, n, base)
        got[lib] = res
        wrong = {op: r for op, r in res.items() if r[1] != want}
        check(f"passes: {lib} issues passes of {want} and no larger, for div, sqrt, rint and scaleb over {n} operands",
              not bad and not wrong, "; ".join(bad) or f"{wrong}")
    if got.get("libcft.a") and got.get("libcft-c16384.a"):
        fewer = all(got["libcft-c16384.a"][op][0] < got["libcft.a"][op][0] for op in got["libcft.a"])
        check("passes: at 16384 each of the four operations makes fewer passes than at 4096", fewer, f"{got}")
        print("      passes at 4096 / 8192 / 16384 over %d operands: %s" % (n, "; ".join(
            "%s %d / %d / %d" % (op, got["libcft.a"][op][0], got["libcft-c8192.a"][op][0],
                                 got["libcft-c16384.a"][op][0]) for op in sorted(got["libcft.a"]))))


def group_tools(base: str, state: dict) -> None:
    host = state.get("host")
    if not host or not os.path.exists(os.path.join(host, "divsqrt-soak-c16384")):
        skip("tools", "no build")
        return
    for n in (16384, 8192):
        bad = problems_tools(host, n)
        check(f"tools: at {n} the stderr names BATCH and CFT_CHUNK, the default's does not, stdout is the default's "
              "for 15 invocations, sabotage fails", not bad, "; ".join(bad)[:900])
    bad = problems_tools(host, 4096, with_stdout=True)
    check("tools: the build at 4096 is the default's output, stderr included, byte for byte", not bad, "; ".join(bad)[:600])


def group_clean(base: str, state: dict) -> None:
    host = state.get("host")
    if not host or not os.path.exists(os.path.join(host, "divsqrt-soak-c16384")):
        skip("clean", "no build")
        return
    decoys = {"divsqrt-soak-cfg": "x", "clause5-soak-chunks.txt": "x", "libcft-core.a": "x", "soak-corpus/keep.txt": "x",
              "soak-c.notes": "x"}
    bad = problems_clean(host, state["pristine"], decoys)
    check("clean: make clean removes the chunked binaries, archives and object directories of every size and the "
          "default products, leaves the tree as it was, and leaves files that only look like them", not bad, "; ".join(bad))


def group_ignore(base: str) -> None:
    if not shutil.which("git"):
        skip("ignore", "no git")
        return
    rc, out, err = sh(["git", "-C", ROOT, "rev-parse", "--is-inside-work-tree"])
    if rc != 0 or out.strip() != "true":
        skip("ignore: git ignores the soak-chunk products", "this tree is in no git repository")
        return
    paths = []
    for n in (4096, 16384, 65536):
        for ext in ("", ".exe"):
            paths += [f"host/divsqrt-soak-c{n}{ext}", f"host/clause5-soak-c{n}{ext}"]
        paths += [f"host/libcft-c{n}.a", f"host/soak-c{n}/src/divsqrt.o", f"host/soak-c{n}/src/backend_xrt.o"]
    notign = []
    for p in paths:
        rc, out, err = sh(["git", "-C", ROOT, "check-ignore", "-q", p])
        if rc != 0:
            notign.append(p)
    check("ignore: git ignores every product of every size, so a build leaves the next build id untracked=none",
          not notign, f"not ignored: {notign[:5]}")
    decoy = [p for p in ("host/divsqrt-soak-cfg", "host/soak-corpus/keep.txt")
             if sh(["git", "-C", ROOT, "check-ignore", "-q", p])[0] == 0]
    check("ignore: ... and the patterns are not wider than the products (a name that only resembles one is not ignored)",
          not decoy, f"ignored: {decoy}")


FLAGS = ["-std=c99", "-O2", "-Wall", "-Wextra", "-Wpedantic", "-Wshadow", "-Iinclude", "-fno-math-errno",
         "-frounding-math"]


def group_unchanged(base: str, state: dict, baseline: str) -> None:
    rev = os.path.basename(os.path.normpath(baseline))
    bhost = copy_host(os.path.join(base, "baseline"), os.path.join(baseline, "host"))
    nhost = state.get("host")
    if not nhost or not os.path.exists(os.path.join(nhost, "divsqrt-soak")):
        skip("unchanged", "no build of this tree's default tools")
        return
    rc, out, err = make(bhost, "-j4", "divsqrt-soak", "clause5-soak")
    if not check(f"unchanged: the baseline {rev} builds", rc == 0, (out + err)[-300:]):
        return
    runs = []
    for seed in (1, 77):
        for m in ("rne", "rtz", "rdn", "rup"):
            runs += [("d", ["div32", "100000", str(seed), m]), ("d", ["div64", "100000", str(seed), m]),
                     ("d", ["sqrt64", "100000", str(seed), m])]
    runs += [("d", ["div32", str(c), "5", "rne"]) for c in (1, 4095, 4096, 4097, 12289, 16384, 16385)]
    for m in ("rne", "rtz", "rdn", "rup", "rmm"):
        runs += [("d", ["sqrt32", "0", "100000", m]), ("d", ["sqrt32", "0x3F800000", str(0x3F800000 + 50000), m])]
    runs += [("d", ["div32-hard", "0", "30000", "rne"]), ("d", ["div64-hard", "20000", "50000", "rdn"]),
             ("d", ["sqrt64-hard", "0", "30000", "rmm"]), ("d", ["hard-space", "div32-hard"]),
             ("d", ["hard-count", "div32-hard", "0", "5000"])]
    runs += [("c", ["rint32", "0", "60000", "rne"]), ("c", ["rint64", "60000", "3", "rmm"]),
             ("c", ["scaleb32", "300000", "5", "rne"]), ("c", ["scaleb64", "300000", "5", "rtz"]),
             ("c", ["cvtfrom64", "50000", "5", "rup"]), ("c", ["rem64", "30000", "5"]),
             ("c", ["rint64-class", "0", "5000", "rne"]), ("c", ["scaleb64-class", "0", "5000", "rtz"]),
             ("c", ["nextup32", "0", "60000"]), ("c", ["class32", "0", "60000"])]
    refusals = [("d", ["div32", "100", "1", "rmm"]), ("d", ["div32", "100", "1", "rtx"]), ("d", ["nosuchop", "100", "1",
                "rne"]), ("c", ["rint32", "5", "5", "rne"]), ("c", ["nosuchjob", "1", "2", "rne"])]
    sab = [("d", ["div32", "100000", "3", "rne"]), ("d", ["sqrt64", "100000", "3", "rdn"]), ("c", ["rint32", "0", "100000",
           "rne"]), ("c", ["scaleb32", "300000", "3", "rne"])]
    usage = [("d", []), ("d", ["div32"]), ("c", []), ("c", ["rint32"])]
    n = same = 0
    for kind, lst, env in (("normal", runs + refusals, {}), ("sabotaged", sab, {"CFT_SOAK_SABOTAGE": "1"}),
                           ("usage", usage, {})):
        for which, args in lst:
            name = "divsqrt-soak" if which == "d" else "clause5-soak"
            outs = []
            for h in (bhost, nhost):
                p = sh(NICE + [os.path.join(h, name)] + args, env=env, timeout=600)
                # a usage text names argv[0], which is the tool's path
                outs.append((p[0], p[1], p[2].replace(os.path.join(h, name), "X")))
            n += 1
            ok = outs[0] == outs[1]
            same += ok
            if not ok:
                check(f"unchanged ({kind}): {name} {' '.join(args)} prints the same bytes and exits the same", False,
                      f"{outs[0][0]} vs {outs[1][0]}: {outs[0][2][-80:]!r} / {outs[1][2][-80:]!r}")
    check(f"unchanged: {n} invocations of the default tools ({rev} and this tree): the same stdout, stderr and exit "
          f"status for all {same} that agree", same == n, f"{n - same} differ")
    # the Makefiles, each in a pristine copy: a dry run of a built tree says "up to date" instead
    pb = copy_host(os.path.join(base, "dry-baseline"), os.path.join(baseline, "host"))
    pn = copy_host(os.path.join(base, "dry-new"))
    for goal in ("all", "divsqrt-soak", "clause5-soak", "libcft.a", "libcft.so"):
        a = make(pb, "-n", goal, nice=False)
        b = make(pn, "-n", goal, nice=False)
        check(f"unchanged: `make -n {goal}` is the same text in {rev}'s Makefile and this one", a == b and a[0] == 0,
              f"rc {a[0]} vs {b[0]}")
    objs = os.path.join(base, "objs")
    os.makedirs(objs)
    for tool in ("divsqrt_soak", "clause5_soak"):
        for defs in ([], ["-DCFT_SOAK_HAVE_ROUNDEVEN=1"]) if tool == "clause5_soak" else ([],):
            tag = tool + ("-re" if defs else "")
            for lab, h in (("base", bhost), ("new", nhost)):
                sh(["cc"] + FLAGS + defs + ["-c", f"tools/{tool}.c", "-o", os.path.join(objs, f"{tag}-{lab}.o")], cwd=h)
            try:
                a = open(os.path.join(objs, f"{tag}-base.o"), "rb").read()
                b = open(os.path.join(objs, f"{tag}-new.o"), "rb").read()
            except OSError as e:
                check(f"unchanged: the {tag} objects compile", False, str(e))
                continue
            check(f"unchanged: the {tag} object, compiled with the Makefile's flags, is byte for byte the baseline's "
                  f"({len(a)} bytes)", a == b and len(a) > 1000, f"{len(a)} vs {len(b)} bytes")
    sh(["cc"] + FLAGS + ["-DBATCH=16384", "-DCFT_CHUNK=16384", "-c", "tools/divsqrt_soak.c", "-o",
                         os.path.join(objs, "ctl.o")], cwd=nhost)
    ctl = open(os.path.join(objs, "ctl.o"), "rb").read()
    check("unchanged: CONTROL - the object at -DBATCH=16384 -DCFT_CHUNK=16384 is not the baseline's (the comparison can "
          "tell)", ctl != open(os.path.join(objs, "divsqrt_soak-base.o"), "rb").read())


def plant(base: str, name: str, edits: list, build: list):
    """A copy of host/ with each (file, old, new) edit applied (the text must occur once), then built with the make
    arguments in `build`. Returns the planted tree, or None (a failed check, said) if it could not be made."""
    host = copy_host(os.path.join(base, "plant-" + name))
    for rel, old, new in edits:
        path = os.path.join(host, rel)
        text = open(path).read()
        if text.count(old) != 1:
            check(f"plants: {name}: the text to change is in {rel} exactly once", False, f"{text.count(old)} times")
            return None
        with open(path, "w") as f:
            f.write(text.replace(old, new))
    if build:
        rc, out, err = make(host, "-j4", *build)
        if rc != 0:
            check(f"plants: {name}: the planted tree builds", False, (out + err)[-300:])
            return None
    return host


def group_plants(base: str, state: dict) -> None:
    mk = "Makefile"
    full = ["SOAK_CHUNK=16384", "soak-chunk", "divsqrt-soak", "clause5-soak"]
    # the CONTROL: the same tree with nothing planted passes every check a plant is held to below
    ctl = plant(base, "control", [], full)
    if not ctl:
        return
    pristine = snapshot(copy_host(os.path.join(base, "plant-pristine")))
    pr_bad, res = probe(ctl, "libcft-c16384.a", 65545, base)
    fresh = plant(base, "control-dry", [], None)       # a dry run of a BUILT tree has little left to print
    red = {"stderr": problems_tools(ctl, 16384, with_stdout=False),
           "probe": pr_bad or [r for r in res.values() if r[1] != 16384],
           "recipe": problems_recipe(fresh), "refusals": problems_refuse(fresh),
           "clean": problems_clean(ctl, pristine, {})}
    check("plants: CONTROL - the unplanted tree passes the tools' stderr check, the probe (passes of 16384), the recipe "
          "check, the refusals' check and the clean check", not any(red.values()),
          "red on the unplanted copy: " + "; ".join(f"{k}: {v[:2]}" for k, v in red.items() if v))
    # 1. the library built without -DCFT_CHUNK: the tool is still told 16384 and says so, so only the probe sees it
    lib_edit = [(mk, "\t  -DCFT_CHUNK=$(SOAK_CHUNK) -c $< -o $@\n\n$(SOAK_DIR)/%.o: %.cpp",
                 "\t  -c $< -o $@\n\n$(SOAK_DIR)/%.o: %.cpp")]
    host = plant(base, "lib", lib_edit, full)
    if host:
        tool_bad = problems_tools(host, 16384, with_stdout=False)
        pr_bad, res = probe(host, "libcft-c16384.a", 65545, base)
        check("plants: the library built without -DCFT_CHUNK is NOT seen by the stderr check (the tool is compiled with "
              "-DCFT_CHUNK=16384 itself and still says 16384)", not tool_bad, "; ".join(tool_bad))
        check("plants: ... and IS seen by the probe, which finds passes of 4096 in the archive named c16384",
              not pr_bad and len(res) == 4 and all(r[1] == 4096 for r in res.values()), f"{pr_bad} {res}")
        check("plants: ... and by the recipe check, which finds the object compiled without -DCFT_CHUNK=16384",
              any("without -DCFT_CHUNK=16384" in b for b in problems_recipe(plant(base, "lib-dry", lib_edit, None) or host)),
              "")
    # 2. the tool built without -DBATCH
    bsnl = "\\" + "\n"                    # a backslash and a newline: a Makefile line continued
    batch_edit = [(mk, "-frounding-math -DCFT_CHUNK=$(SOAK_CHUNK) -DBATCH=$(SOAK_CHUNK) " + bsnl + "\t  tools/divsqrt_soak.c",
                   "-frounding-math -DCFT_CHUNK=$(SOAK_CHUNK) " + bsnl + "\t  tools/divsqrt_soak.c")]
    host = plant(base, "batch", batch_edit, full)
    if host:
        bad = problems_tools(host, 16384, with_stdout=False)
        check("plants: the tool built without -DBATCH says BATCH 4096 and the stderr check is red",
              any("BATCH 4096 and CFT_CHUNK 16384" in b for b in bad), "; ".join(bad))
        check("plants: ... and the recipe check finds its line without -DBATCH=16384",
              any("lacks -DBATCH=16384" in b for b in problems_recipe(plant(base, "batch-dry", batch_edit, None) or host)),
              "")
    # 3. the tool linked against the default archive
    host = plant(base, "link", [(mk, "tools/divsqrt_soak.c $(SOAK_LIB) -o $@", "tools/divsqrt_soak.c libcft.a -o $@")], None)
    if host:
        check("plants: a tool linked against libcft.a is caught by the recipe check",
              any("is linked against the default libcft.a" in b for b in problems_recipe(host)), "")
    # 4. a validation that lets a bad value through
    host = plant(base, "valid", [(mk, "SOAK_CHUNK_OK    := 4096 8192", "SOAK_CHUNK_OK    := 4097 4096 8192")], None)
    if host:
        bad = problems_refuse(host)
        check("plants: a Makefile that lets 4097 through is caught by the refusals' check",
              any("SOAK_CHUNK='4097' was accepted" in b for b in bad), "; ".join(bad)[:300])
    # 5. clean that leaves the object directory
    host = plant(base, "clean", [(mk, "\trm -rf soak-c[0-9]*/\n", "\t@true\n")], full)
    if host:
        bad = problems_clean(host, pristine, {})
        check("plants: a clean that leaves the object directory is caught by the clean check",
              any("clean left" in b and "soak-c16384" in b for b in bad), "; ".join(bad)[:300])
    # 6. the stderr line printed at the defaults too
    host = plant(base, "line", [("tools/divsqrt_soak.c", "#if BATCH != 4096 || CFT_CHUNK != 4096", "#if 1")],
                 ["divsqrt-soak", "clause5-soak", "SOAK_CHUNK=4096", "soak-chunk"])
    if host:
        bad = problems_tools(host, 4096, with_stdout=False)
        check("plants: a tool that prints the BATCH line at the defaults is caught (the default's stderr is the backend "
              "line alone)", any("DEFAULT divsqrt-soak's stderr" in b for b in bad), "; ".join(bad))


def main() -> int:
    args = sys.argv[1:]
    only = set(args[args.index("--only") + 1].split(",")) if "--only" in args else None
    baseline = args[args.index("--baseline-tree") + 1] if "--baseline-tree" in args else None
    keep = "--keep" in args

    def want(g: str) -> bool:
        return only is None or g in only

    t0 = time.time()
    posix = os.name == "posix" and shutil.which("make") and (shutil.which("cc") or shutil.which("gcc"))
    base = tempfile.mkdtemp(prefix="soak-chunk-test-")
    state: dict = {}
    try:
        if want("ignore"):
            n0, f0 = CHECKS, len(FAILS)
            group_ignore(base)
            print(f"ignore: {CHECKS - n0} checks, {len(FAILS) - f0} failed")
        if not posix:
            skip("soak-chunk", "needs POSIX with make and a C compiler (the soak requires a 64-bit Linux)")
        else:
            needs_build = any(want(g) for g in ("build", "passes", "tools", "clean", "unchanged"))
            steps = [("refuse", lambda: group_refuse(base)), ("recipe", lambda: group_recipe(base))]
            if needs_build:
                steps.append(("build", lambda: group_build(base, state)))
            steps += [("passes", lambda: group_passes(base, state)), ("tools", lambda: group_tools(base, state))]
            for name, fn in steps:
                if want(name) or (name == "build" and needs_build):
                    n0, f0 = CHECKS, len(FAILS)
                    fn()
                    print(f"{name}: {CHECKS - n0} checks, {len(FAILS) - f0} failed")
            if want("unchanged"):
                n0, f0 = CHECKS, len(FAILS)
                if baseline:
                    group_unchanged(base, state, baseline)
                else:
                    skip("unchanged", "needs --baseline-tree DIR")
                print(f"unchanged: {CHECKS - n0} checks, {len(FAILS) - f0} failed")
            for name, fn in (("clean", lambda: group_clean(base, state)), ("plants", lambda: group_plants(base, state))):
                if want(name):
                    n0, f0 = CHECKS, len(FAILS)
                    fn()
                    print(f"{name}: {CHECKS - n0} checks, {len(FAILS) - f0} failed")
    finally:
        if not keep:
            shutil.rmtree(base, ignore_errors=True)
        else:
            print(f"kept {base}")
    print(f"soak-chunk test: {CHECKS} checks, {len(FAILS)} failed, {len(SKIPS)} skipped, {time.time() - t0:.0f} s")
    for f in FAILS:
        print("  FAILED:", f[:300])
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
