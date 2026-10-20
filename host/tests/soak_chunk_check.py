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
  clean      `make clean` removes the products of every size the Makefile allows - the tree's own build at three
             sizes and a synthetic one of all sixteen, binaries in both forms, archives, object directories - by their
             exact names AND ONLY WHEN EACH IS THE RIGHT KIND OF THING (a binary or archive: a regular file and no
             symlink; an object directory: a directory and no symlink), and the tree is as it was, with these still
             there: names that only BEGIN like a product (without digits, with a size's digits and a suffix - a .log,
             a .txt, -old, -notes/ - and with digits of no allowed size, four or five); a regular file named exactly
             like an object directory (soak-c61440; 67fd3f6 removed it) and a directory named exactly like a binary
             (divsqrt-soak-c61440/; `rm -f` refuses it and make stopped there); and, of the allowed sizes, a symlink
             to a file named like a binary, a dangling symlink and a FIFO named like an archive, a symlink to a
             directory named like a binary and one named like an object directory (5446351 removed the first three:
             its test excluded only directories; a FIFO is made with os.mkfifo and skipped by name where there is
             none). A regular file with a product's exact name is the build's to remove, and is removed
  ignore     git ignores every product (all sixteen sizes), so a build leaves the next build id untracked=none.
             No pattern of this build takes a name that only begins like a product, WITH ONE DOCUMENTED EXCEPTION:
             the shape is the tool's name and exactly four or five digits, so a name of that shape is ignored by
             this build's patterns whether or not the size is allowed (divsqrt-soak-c1234, divsqrt-soak-c12345,
             soak-c12345/), and `make clean` keeps it; the check holds both. A scratch repository holding this tree's
             .gitignore passes the same check (CONTROL), and one holding the earlier [0-9]* globs fails it. Two
             decoys are ignored by blanket rules that were there before (*.log, host/*.a), and the check says which
  unchanged  (with --baseline-tree DIR, a directory holding the baseline's host/ - `git archive REV host | tar -x
             -C DIR`) the default tools of that tree and of this one print the same bytes and exit with the same
             status over 40 invocations, sabotage and usage errors among them; the default goals' dry runs are the
             same text; and the two tools' objects, compiled with the Makefile's flags, are byte for byte the same
  plants     one defect in a scratch copy for each class of check, red at the check written for it, each preceded by a
             CONTROL that the unplanted copy passes: the library built without -DCFT_CHUNK (the tool still says
             16384 and only the probe sees 4096), the tool built without -DBATCH, the tool linked against libcft.a,
             the validation removed, `clean` leaving the object directory, `clean` with the earlier globs put back
             (it removes a divsqrt-soak-c16384.log: verifier VCK's finding at 318b597), `clean` that misses one
             size, `clean` with the unguarded `rm -rf` put back (it removes the file soak-c61440: VCK's finding at
             67fd3f6), `clean` with the unguarded `rm -f` put back (it stops on the directory divsqrt-soak-c61440/),
             `clean` with the directories-only test `[ ! -d ]` put back (it removes the symlinks and the FIFO: VCK's
             finding at 5446351), `clean` without the symlink test on the object directories (it removes the symlink
             soak-c40960), and the stderr line printed at the defaults

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
# Names `make clean` must leave. None is a product of any size the Makefile allows. The first five carry no digits;
# the next five carry a size's digits and something after them (the earlier globs, divsqrt-soak-c[0-9]*, took a .log
# of the user's: verifier VCK, 318b597); then names of four or five digits that are no allowed size (which
# .gitignore's shape DOES ignore, and clean keeps); then, at size 61440, which the tree does not build, two names that
# ARE a product's name and the wrong kind of thing: a regular file named like an object directory (67fd3f6 removed
# it: verifier VCK) and a directory named like a binary (`rm -f` refuses it, and make stopped there).
DECOYS = {"divsqrt-soak-cfg": "x", "clause5-soak-chunks.txt": "x", "libcft-core.a": "x", "soak-corpus/keep.txt": "x",
          "soak-c.notes": "x",
          "divsqrt-soak-c16384.log": "x", "clause5-soak-c16384.txt": "x", "libcft-c16384-old.a": "x",
          "soak-c16384-notes/keep.txt": "x", "clause5-soak-c16384-old": "x",
          "divsqrt-soak-c1234": "x", "divsqrt-soak-c12345": "x", "soak-c12345/keep.txt": "x",
          "soak-c61440": "x", "divsqrt-soak-c61440/keep.txt": "x"}
# Names of allowed sizes that are the wrong kind of thing, which `make clean` must also leave (verifier VCK, 5446351: its
# test on binaries and archives excluded only directories, and it removed the first three): a symlink to a file named
# like a binary, a dangling symlink and a FIFO named like an archive, a symlink to a directory named like a binary, and
# one named like an object directory. (name, what it is, the link's target: a decoy above for the symlinks that
# resolve, a name that is not there for the dangling one, None for the FIFO). Sizes the tree does not build.
SPECIAL_DECOYS = [("divsqrt-soak-c57344", "symlink to a file", "libcft-core.a"),
                  ("libcft-c53248.a", "dangling symlink", "no-such-target-ck"),
                  ("libcft-c49152.a", "FIFO", None),
                  ("clause5-soak-c45056", "symlink to a directory", "soak-corpus"),
                  ("soak-c40960", "symlink to a directory", "soak-corpus")]
EXTRA ="soaking with BATCH %d and CFT_CHUNK %d (the defaults are 4096)\n"
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


def make_synthetic_products(host: str, skip: set) -> None:
    """Every kind of product a build of every size the Makefile allows leaves, whether or not this tree built it: the
    two binaries in both forms, the archive, the object directory with an object in it. A name in `skip` is made by
    a decoy instead (a file named like an object directory, a directory named like a binary)."""
    for n in OK_VALUES:
        for name in (f"divsqrt-soak-c{n}", f"divsqrt-soak-c{n}.exe", f"clause5-soak-c{n}", f"clause5-soak-c{n}.exe",
                     f"libcft-c{n}.a"):
            if name not in skip:
                with open(os.path.join(host, name), "w") as f:
                    f.write("x")
        if f"soak-c{n}" not in skip:
            os.makedirs(os.path.join(host, f"soak-c{n}", "src"), exist_ok=True)
            with open(os.path.join(host, f"soak-c{n}", "src", "x.o"), "w") as f:
                f.write("x")


def make_special_decoys(host: str) -> list:
    """The SPECIAL_DECOYS the platform can make, in `host` (after the decoys they point at); returns their snapshot keys
    (a symlink to a directory is listed as a directory). One it cannot make is skipped by name."""
    keys = []
    for name, kind, target in SPECIAL_DECOYS:
        path = os.path.join(host, name)
        try:
            if kind == "FIFO":
                os.mkfifo(path)
            else:
                os.symlink(target, path)
        except (AttributeError, NotImplementedError, OSError) as ex:
            skip(f"clean: the {kind} decoy {name}", f"this platform cannot make one ({type(ex).__name__}: {ex})")
            continue
        keys.append(name + ("/" if kind == "symlink to a directory" else ""))
    return keys


def problems_clean(host: str, pristine: set, decoys: dict) -> list:
    """`make clean` in `host`, which has a build in it, holds synthetic products of all sixteen sizes, the decoys and
    (where the platform has symlinks and FIFOs) the special decoys: afterwards the tree must be the pristine tree plus
    the decoys - every product gone (left = in the tree and in neither), every decoy and every pristine file still
    there (gone = in neither the tree nor the decoys). A decoy is kept whatever kind of thing it is; a regular file
    with a product's exact name is a product (the synthetic ones), and is removed."""
    bad = []
    make_synthetic_products(host, {n.split("/")[0] for n in decoys} | {n for n, _, _ in SPECIAL_DECOYS})
    for name, content in decoys.items():
        path = os.path.join(host, name)
        os.makedirs(os.path.dirname(path) or host, exist_ok=True)
        with open(path, "w") as f:
            f.write(content)
    keep = pristine | {n for n in decoys} | {os.path.dirname(n) + "/" for n in decoys if os.path.dirname(n)}
    keep |= set(make_special_decoys(host))
    before = snapshot(host)
    rc, out, err = make(host, "clean", nice=False)
    if rc != 0:
        bad.append(f"make clean exited {rc}: {err[-200:]}")
    after = snapshot(host)
    left = sorted(after - keep)
    gone = sorted(keep - after)
    if left:
        bad.append(f"clean left {left[:12]}")
    if gone:
        bad.append(f"clean removed what it did not make: {gone[:12]}")
    if not (before - keep):
        bad.append("nothing was built before the clean, so it removed nothing")
    return bad


MINE = re.compile(r"soak-c\[")         # the .gitignore patterns this build added, whatever digits they spell


def ignore_answers(root: str, paths: list) -> dict:
    """{path: the pattern git matched, or None} for each path, from one `git check-ignore -v -n --stdin` in `root`."""
    # bytes both ways: a text-mode pipe on Windows would end each path with CR LF, and git would answer for "path\r"
    p = subprocess.run(["git", "-C", root, "check-ignore", "-v", "-n", "--stdin"],
                       input=("\n".join(paths) + "\n").encode("utf-8"), capture_output=True)
    got = {}
    for line in p.stdout.decode("utf-8", "replace").splitlines():
        src, _, path = line.partition("\t")
        parts = src.split(":", 2)               # source:line:pattern, and "::" for a path nothing matches
        got[path] = parts[2] if len(parts) == 3 and parts[2] else None
    return got


def problems_ignore(root: str) -> list:
    """What git, in the repository `root`, ignores of the soak-chunk build's names. (1) The products of all sixteen
    sizes must be ignored. (2) Names that only BEGIN like a product - a suffix after the digits, another digit count, a
    directory beside - must not be taken by any pattern this build added: the first group is ignored by nothing at all;
    the second is taken by a blanket rule that was there before (*.log, and host/*.a for any archive) or by nothing, and
    the check says which pattern, so a pattern of this build is told apart. (3) THE ONE DOCUMENTED EXCEPTION: the
    patterns are a SHAPE, the tool's name and exactly four or five digits, so a name of that shape is ignored by this
    build's patterns whether or not the size is allowed; `make clean` keeps such a name (the clean group holds that
    half). Verifier VCK, at 67fd3f6: the generic sentence "no pattern takes a name that only begins like one" left
    this exception out, and the check did not look at it."""
    products = []
    for n in OK_VALUES:
        for ext in ("", ".exe"):
            products += [f"host/divsqrt-soak-c{n}{ext}", f"host/clause5-soak-c{n}{ext}"]
        products += [f"host/libcft-c{n}.a", f"host/soak-c{n}/src/divsqrt.o", f"host/soak-c{n}/src/backend_xrt.o"]
    clear = ["host/clause5-soak-c16384.txt", "host/soak-c16384-notes/keep.txt", "host/clause5-soak-c16384-old",
             "host/divsqrt-soak-c163840", "host/divsqrt-soak-c409", "host/divsqrt-soak-cfg", "host/soak-corpus/keep.txt",
             "host/soak-c.notes"]
    blanket = ["host/divsqrt-soak-c16384.log", "host/libcft-c16384-old.a"]
    shape = ["host/divsqrt-soak-c1234", "host/divsqrt-soak-c12345", "host/clause5-soak-c1234", "host/clause5-soak-c12345",
             "host/soak-c1234/keep.txt", "host/soak-c12345/keep.txt"]
    got = ignore_answers(root, products + clear + blanket + shape)
    bad = []
    if not got:
        return ["git answered nothing"]
    for p in products:
        if p not in got:
            bad.append(f"git gave no answer for {p}")
        elif got[p] is None:
            bad.append(f"{p} is not ignored")
    for p in clear:
        if got.get(p):
            bad.append(f"{p} is ignored, by {got[p]}")
    for p in blanket:
        if got.get(p) and MINE.search(got[p]):
            bad.append(f"{p} is taken by this build's pattern {got[p]}")
    for p in shape:
        if p not in got:
            bad.append(f"git gave no answer for {p}")
        elif not (got[p] and MINE.search(got[p])):
            bad.append(f"{p} has the shape of a product (the tool's name and four or five digits, no allowed size) and is "
                       f"{'not ignored' if got[p] is None else 'ignored by ' + got[p]}, where the documented width is "
                       "ignored by a pattern of this build")
    return bad


def scratch_repo(base: str, name: str, gitignore: str):
    """A repository in base/name holding only the given .gitignore. `git init` writes the scratch repository's own
    .git/config and nothing outside the directory; it changes no global or system configuration, and with --template=
    it copies no template."""
    d = os.path.join(base, name)
    os.makedirs(d)
    rc, out, err = sh(["git", "init", "-q", "--template=", d])
    if rc != 0:
        return None
    with open(os.path.join(d, ".gitignore"), "w", newline="\n") as f:
        f.write(gitignore)
    return d


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
    bad = problems_clean(host, state["pristine"], DECOYS)
    check("clean: make clean removes the products of every allowed size (this tree's three and a synthetic set of all "
          "16, .exe forms included) and the default products by their exact names, leaves the tree as it was, and leaves "
          f"the {len(DECOYS)} names that only begin like a product (a divsqrt-soak-c16384.log, a soak-c16384-notes/, a "
          "regular file named like an object directory, a directory named like a binary) and the "
          f"{len(SPECIAL_DECOYS)} of an allowed size that are a symlink, a dangling symlink or a FIFO", not bad,
          "; ".join(bad))


def group_ignore(base: str) -> None:
    if not shutil.which("git"):
        skip("ignore", "no git")
        return
    rc, out, err = sh(["git", "-C", ROOT, "rev-parse", "--is-inside-work-tree"])
    if rc != 0 or out.strip() != "true":
        skip("ignore: git ignores the soak-chunk products", "this tree is in no git repository")
        return
    bad = problems_ignore(ROOT)
    check("ignore: git ignores every product of all 16 sizes (binaries in both forms, archive, object directory), so a "
          "build leaves the next build id untracked=none, and no pattern of this build takes a name that only begins "
          "like one (a .txt, a -notes/ directory, a -old name, six digits, three digits, no digits), except the "
          "documented width: the tool's name and four or five digits is ignored by this build's patterns whether or "
          "not the size is allowed", not bad,
          "; ".join(bad)[:700])
    try:
        text = open(os.path.join(ROOT, ".gitignore"), encoding="utf-8").read()
    except OSError:
        skip("ignore: the scratch repositories", "no .gitignore at the root of this tree")
        return
    # the same check in scratch repositories (git init writes nothing outside the directory): this tree's .gitignore
    # passes (CONTROL), and the earlier globs, put back after this build's lines are taken out, fail it by name
    ctl = scratch_repo(base, "ignore-control", text)
    bad = problems_ignore(ctl) if ctl else ["could not make a scratch repository"]
    check("ignore: CONTROL - a scratch repository holding this tree's .gitignore passes the check", not bad, "; ".join(bad)[:400])
    old = "".join(ln + "\n" for ln in text.splitlines() if "soak-c[" not in ln)
    old += "host/divsqrt-soak-c[0-9]*\nhost/clause5-soak-c[0-9]*\nhost/soak-c[0-9]*/\n"
    plant_repo = scratch_repo(base, "ignore-plant", old)
    bad = problems_ignore(plant_repo) if plant_repo else []
    check("ignore: PLANT - the earlier [0-9]* globs put back are caught, naming the .txt, the -old name and the -notes/ "
          "directory, and the .log that the glob (not the blanket *.log) now takes",
          any("clause5-soak-c16384.txt" in b for b in bad) and any("soak-c16384-notes" in b for b in bad)
          and any("divsqrt-soak-c16384.log" in b and "soak-c[" in b for b in bad), "; ".join(bad)[:600])


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
           "clean": problems_clean(ctl, pristine, DECOYS)}
    check("plants: CONTROL - the unplanted tree passes the tools' stderr check, the probe (passes of 16384), the recipe "
          "check, the refusals' check and the clean check (with the decoys that begin like a product, a "
          "divsqrt-soak-c16384.log among them)", not any(red.values()),
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
    # the two guarded lines of `clean` as the Makefile has them (the shell test is the point of the second fix)
    files_line = '\tfor f in $(SOAK_CHUNK_FILES); do if [ -f "$$f" ] && [ ! -L "$$f" ]; then rm -f "$$f"; fi; done\n'
    dirs_line = '\tfor d in $(SOAK_CHUNK_DIRS); do if [ -d "$$d" ] && [ ! -L "$$d" ]; then rm -rf "$$d"; fi; done\n'
    # 5. clean that leaves the object directory
    host = plant(base, "clean", [(mk, dirs_line, "\t@true\n")], None)
    if host:
        bad = problems_clean(host, pristine, DECOYS)
        check("plants: a clean that leaves the object directory is caught by the clean check",
              any("clean left" in b and "soak-c16384" in b for b in bad), "; ".join(bad)[:300])
    # 5b. the earlier globs put back (verifier VCK's finding at 318b597): the control above passed the same decoys
    # (directories first here: the directory decoy named like a binary would stop an `rm -f` before the `rm -rf`)
    host = plant(base, "glob", [(mk, files_line + dirs_line,
                                 "\trm -rf soak-c[0-9]*/\n\trm -f divsqrt-soak-c[0-9]* clause5-soak-c[0-9]* libcft-c[0-9]*.a\n")],
                 None)
    if host:
        bad = problems_clean(host, pristine, DECOYS)
        gone = " ".join(bad)
        check("plants: `clean` with the earlier globs is caught: it removes the divsqrt-soak-c16384.log, the "
              "clause5-soak-c16384.txt, the libcft-c16384-old.a and the soak-c16384-notes/ that are not products",
              all(x in gone for x in ("divsqrt-soak-c16384.log", "clause5-soak-c16384.txt", "libcft-c16384-old.a",
                                      "soak-c16384-notes/")), gone[:500])
    # 5c. a clean that misses one size (65536): only the synthetic products of all sixteen sizes see it, the build has three
    host = plant(base, "size", [(mk, "SOAK_CHUNK_FILES := $(foreach n,$(SOAK_CHUNK_OK),",
                                 "SOAK_CHUNK_FILES := $(foreach n,$(filter-out 65536,$(SOAK_CHUNK_OK)),")], None)
    if host:
        bad = problems_clean(host, pristine, DECOYS)
        check("plants: a clean that misses the size 65536 is caught (by the synthetic products of all 16 sizes: the "
              "tree's own build has three)", any("clean left" in b and "divsqrt-soak-c65536" in b for b in bad),
              "; ".join(bad)[:300])
    # 5d. the unguarded `rm -rf` of 67fd3f6 put back (verifier VCK's (a)): it removes the regular file soak-c61440
    host = plant(base, "rmrf", [(mk, dirs_line, "\trm -rf $(SOAK_CHUNK_DIRS)\n")], None)
    if host:
        bad = problems_clean(host, pristine, DECOYS)
        check("plants: the unguarded `rm -rf` of the object directories put back is caught: it removes the regular file "
              "soak-c61440 that is no directory (verifier VCK, 67fd3f6)",
              any("clean removed what it did not make" in b and "'soak-c61440'" in b for b in bad), "; ".join(bad)[:400])
    # 5e. the unguarded `rm -f` put back: it refuses the directory divsqrt-soak-c61440/ and make stops there
    host = plant(base, "rmf", [(mk, files_line, "\trm -f $(SOAK_CHUNK_FILES)\n")], None)
    if host:
        bad = problems_clean(host, pristine, DECOYS)
        check("plants: the unguarded `rm -f` of the binaries put back is caught: `make clean` stops on the directory "
              "divsqrt-soak-c61440/ that has a binary's name", any("make clean exited" in b for b in bad),
              "; ".join(bad)[:400])
    # 5f. 5446351's test on the binaries and archives put back (verifier VCK's (a) of the third pass): it excludes only
    # directories, and removes the symlink to a file, the dangling symlink and the FIFO
    host = plant(base, "notd", [(mk, files_line,
                                 '\tfor f in $(SOAK_CHUNK_FILES); do if [ ! -d "$$f" ]; then rm -f "$$f"; fi; done\n')], None)
    if host:
        bad = problems_clean(host, pristine, DECOYS)
        gone = " ".join(bad)
        check("plants: the directories-only test `[ ! -d ]` put back is caught: it removes the symlink to a file "
              "(divsqrt-soak-c57344), the dangling symlink (libcft-c53248.a) and the FIFO (libcft-c49152.a) (verifier VCK, "
              "5446351)", all(x in gone for x in ("divsqrt-soak-c57344", "libcft-c53248.a", "libcft-c49152.a")),
              gone[:500])
    # 5g. the symlink test taken off the object directories: it removes the symlink soak-c40960
    host = plant(base, "dirlink", [(mk, dirs_line,
                                    '\tfor d in $(SOAK_CHUNK_DIRS); do if [ -d "$$d" ]; then rm -rf "$$d"; fi; done\n')], None)
    if host:
        bad = problems_clean(host, pristine, DECOYS)
        check("plants: an object-directory loop without the symlink test is caught: it removes the symlink soak-c40960 "
              "that points at a directory", any("clean removed what it did not make" in b and "soak-c40960" in b for b in bad),
              "; ".join(bad)[:400])
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
