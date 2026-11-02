"""Branch coverage of the golden model (transcend.py) by (a) the oracle's
directed cases and (b) the vector generator's cases, per function, at one
format. A line reached by (b) and not by (a) is a branch the oracle never
asks.  Uses sys.monitoring (Python 3.12): first hit per line, then disabled.

Needs Python 3.12 or later (sys.monitoring).  Usage, from the repository's
root:

    python -B host/tools/audit-pools/audit_branch.py DUMP FORMAT [OUT]

DUMP is a case dump, FORMAT one of fp32, fp64, fp128, fp256; OUT, if given,
receives the listing of the lines of python/cft_golden/transcend.py that the
vector generator reaches and the dump does not.
"""
import collections
import sys
import time

import os  # noqa: E402
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from audit_lib import *   # noqa

dump = sys.argv[1]
fmt_name = sys.argv[2]
out_path = sys.argv[3] if len(sys.argv) > 3 else None
fmt = FMTS[fmt_name]

mon = sys.monitoring
TOOL = mon.COVERAGE_ID
mon.use_tool_id(TOOL, "audit")
TARGET = T.__file__
cur = set()


def on_line(code, line):
    if code.co_filename == TARGET:
        cur.add((code.co_name, line))
    return mon.DISABLE


mon.register_callback(TOOL, mon.events.LINE, on_line)

# function name (as TRANSCEND_IMPL) -> code-object names whose lines belong to it
SRC = open(TARGET).read().splitlines()


def run(case_iter):
    cur.clear()
    mon.restart_events()
    mon.set_events(TOOL, mon.events.LINE)
    perfn = collections.defaultdict(set)
    n = 0
    for (fn, a, b, k) in case_iter:
        before = set(cur)
        T.compute(fmt, fn, a, b, 0, k)    # RNE
        n += 1
        newl = cur - before
        if newl:
            perfn[fn] |= newl
        # lines disabled after first hit are not re-reported, so keep a
        # per-fn union by also adding anything already in cur that this
        # function's code touched; handled by a second pass below.
    mon.set_events(TOOL, 0)
    return perfn, n


# Because a line is reported once, attribute lines to functions by the
# code-object name instead: run the cases function by function.
def run_by_fn(cases_by_fn):
    res = {}
    cnt = {}
    for fn, lst in cases_by_fn.items():
        cur.clear()
        mon.restart_events()
        mon.set_events(TOOL, mon.events.LINE)
        t0 = time.time()
        for (a, b, k) in lst:
            T.compute(fmt, fn, a, b, 0, k)
        mon.set_events(TOOL, 0)
        res[fn] = set(cur)
        cnt[fn] = (len(lst), time.time() - t0)
    return res, cnt


cases = parse_dump(dump)
oracle = {}
for fn in FNS:
    seen = set()
    lst = []
    for a, b, n, d, ps, i, j in cases[fmt_name][fn]:
        if not d:
            continue
        key = (a, b, n)
        if key in seen:
            continue
        seen.add(key)
        lst.append((a, b if b is not None else 0, n if n is not None else 0))
    oracle[fn] = lst

vec = collections.defaultdict(list)
seenv = set()
for (fn, a, b, k) in V.transcend_cases(fmt, 0):
    key = (fn, a, b, k)
    if key in seenv:
        continue
    seenv.add(key)
    vec[fn].append((a, b, k))

ores, ocnt = run_by_fn(oracle)
vres, vcnt = run_by_fn(vec)

out = open(out_path, "w") if out_path else sys.stdout
for fn in FNS:
    # all lines of the code objects of this function (executable lines
    # that are returns/ifs) are not enumerated; report the difference.
    only_v = sorted(vres[fn] - ores[fn], key=lambda x: x[1])
    only_o = sorted(ores[fn] - vres[fn], key=lambda x: x[1])
    print("%-8s oracle cases %5d (%.1fs) lines %3d | vectors cases %5d (%.1fs) lines %3d | only-vectors %2d only-oracle %2d" % (
        fn, ocnt[fn][0], ocnt[fn][1], len(ores[fn]), vcnt[fn][0], vcnt[fn][1],
        len(vres[fn]), len(only_v), len(only_o)), file=out)
    for (co, ln) in only_v:
        print("      V-only %s:%d  %s" % (co, ln, SRC[ln - 1].strip()[:100]),
              file=out)
    for (co, ln) in only_o:
        print("      O-only %s:%d  %s" % (co, ln, SRC[ln - 1].strip()[:100]),
              file=out)
