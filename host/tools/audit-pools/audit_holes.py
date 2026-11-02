"""Lines of the golden model's public family code that NEITHER the oracle's
directed cases NOR the vector generator's cases reach, at one format.

Needs Python 3.12 or later (sys.monitoring).  Usage, from the repository's
root:

    python -B host/tools/audit-pools/audit_holes.py DUMP FORMAT

DUMP is a case dump, FORMAT one of fp32, fp64, fp128, fp256.
"""
import collections
import sys
import types

import os  # noqa: E402
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from audit_lib import *   # noqa

dump = sys.argv[1]
fmt_name = sys.argv[2]
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
SRC = open(TARGET).read().splitlines()

cases = parse_dump(dump)
allcases = []
for fn in FNS:
    for a, b, n, d, ps, i, j in cases[fmt_name][fn]:
        if d:
            allcases.append((fn, a, b if b is not None else 0,
                             n if n is not None else 0))
allcases = list(dict.fromkeys(allcases))
vcases = list(dict.fromkeys(V.transcend_cases(fmt, 0)))

mon.restart_events()
mon.set_events(TOOL, mon.events.LINE)
for (fn, a, b, k) in allcases + vcases:
    T.compute(fmt, fn, a, b, 0, k)
mon.set_events(TOOL, 0)
hit = set(cur)


# every code object in transcend.py
def walk(co, out):
    out.append(co)
    for c in co.co_consts:
        if isinstance(c, types.CodeType):
            walk(c, out)


mod_code = compile(open(TARGET).read(), TARGET, "exec")
cos = []
walk(mod_code, cos)
rows = collections.defaultdict(list)
for co in cos:
    if co.co_name in ("<module>",):
        continue
    lines = sorted({ln for (_s, _e, ln) in co.co_lines() if ln})
    for ln in lines:
        if (co.co_name, ln) in hit:
            continue
        txt = SRC[ln - 1].strip()
        if txt.startswith(("def ", '"""', "#", "@")) or txt in ('"""', ""):
            continue
        rows[co.co_name].append((ln, txt))
for name in sorted(rows, key=lambda n: rows[n][0][0]):
    for ln, txt in rows[name]:
        print("%s:%d  %s" % (name, ln, txt[:110]))
