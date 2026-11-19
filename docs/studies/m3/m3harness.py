# M3 model: the pools, the regions and the comparison against transcend.py
# (scratch; the study's sections 3.3, 4 and 8).
#
# The pools are the vector sets' (python/cft_golden/vectors.py, as
# transcend_cases calls them: extra 24, pow at seed 10, powr at 18, the
# integer cases at 17) with the stage's (host/tests/transcend_check.py's
# pow_pairs, powr_pairs and int_pow_cases at its default trials, seed 5),
# deduplicated in order.

import importlib.util
import random

from m3core import (sf, tr, golden, FORMATS, ROOT, AN, ATTRS, val,  # noqa
                    INTARG)
from cft_golden import vectors
import m3pow as M

_spec = importlib.util.spec_from_file_location(
    "transcend_check", str(ROOT / "host" / "tests" / "transcend_check.py"))
tc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(tc)

MARK = M.ml.MARK


def trials(fmt):
    return 64 if fmt.width <= 64 else 16


def _dedup(seq_):
    seen, out = set(), []
    for v in seq_:
        if v not in seen:
            seen.add(v)
            out.append(v)
    return out


def pool(fmt, fn):
    """The lanes of fn at fmt: (x, y) pairs for pow and powr, (x, n) for
    the three of an integer operand."""
    t = trials(fmt)
    if fn == "pow":
        return _dedup(list(vectors.transcend_pow_pairs(fmt, 24, 10))
                      + list(tc.pow_pairs(fmt, t, 5)))
    if fn == "powr":
        return _dedup(list(vectors.transcend_powr_pairs(fmt, 24, 18))
                      + list(tc.powr_pairs(fmt, t, 5)))
    return _dedup(list(vectors.transcend_int_pow_cases(fmt, 24, 17))
                  + list(tc.int_pow_cases(fmt, t, 5)))


_BUILDS = {}


def builder(fn, fmt, rnd, n=None, plant=None):
    key = (fn, fmt.name, rnd, n, plant)
    if key not in _BUILDS:
        try:
            _BUILDS[key] = M.build_any(fn, fmt, rnd, n=n, plant=plant)
        except M.Refused as exc:
            _BUILDS[key] = exc
    return _BUILDS[key]


def compare(fmt, fn, lanes, rnd, plant=None, stop=20):
    """Run each lane on the model and against transcend.py. Returns a dict:
    lanes, marked, wrong (unmarked lanes whose bits or flags differ: the
    failures), guess_wrong (marked lanes whose guess differs: counted, not
    failures), refused (rootn's n = 0), and up to `stop` examples of each."""
    out = {"lanes": 0, "marked": 0, "wrong": 0, "guess_wrong": 0,
           "refused": 0, "wrong_ex": [], "marked_ex": []}
    for lane in lanes:
        x, b2 = lane
        n = b2 if fn in INTARG else None
        bld = builder(fn, fmt, rnd, n, plant)
        if isinstance(bld, Exception):
            out["refused"] += 1
            continue
        bits, fl, _ = M.run(bld, fn, lane)
        want = golden(fmt, fn, lane, rnd)
        out["lanes"] += 1
        mk = bool(fl & MARK)
        same = (bits, fl & ~MARK) == want
        if mk:
            out["marked"] += 1
            if len(out["marked_ex"]) < stop:
                out["marked_ex"].append((lane, bits, fl, want))
            if not same:
                out["guess_wrong"] += 1
        elif not same:
            out["wrong"] += 1
            if len(out["wrong_ex"]) < stop:
                out["wrong_ex"].append((lane, bits, fl, want))
    return out


def show(fmt, lane, fn):
    x, b2 = lane
    if fn in INTARG:
        return f"x={x:#x} n={b2}"
    return f"x={x:#x} y={b2:#x}"
