# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""python/figure_extracts.py's table of the card stress run's tile ops (KL-135).

STRESS_TILE_OPS says which swept operations exercise the card's tile. It is
a table of its own beside hw/card_stress_lib.py's OP_REACH on purpose: the
two are two statements of one fact, made apart, and make_stress holds the
ops a run served to the driver's table, a check that can fail only while the
two stay two. The price is drift: until 2026-10-21 the catalog had gained
seven tile ops (div32-hard, div64-hard, sqrt64-hard, rint64-class,
scaleb64-class, scaleb32-all, scaleb32-wide) that the table lacked, and the
check refused by name every run that served one.

Held here: the whole of OP_REACH against the whole table on every test run,
not only the ops of one run when it is reduced; the reach check passing a
run that served every item of the catalog, and refusing it by name under the
old table; the C tools saying what each of the seven was read from (with a
control that the reading can fail); and the extract's `tile_ops` being the
ops the RUN served - so that a table that grows with the catalog does not
change a run's extract by a byte, and the committed docs/figures/stress.json
is what a remake from card-stress-1016 writes.
"""

import ast
import importlib.util
import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "python"))

import figure_extracts as FE  # noqa: E402

NEW_TILE_OPS = ("div32-hard", "div64-hard", "sqrt64-hard", "rint64-class",
                "scaleb64-class", "scaleb32-all", "scaleb32-wide")
OLD_TILE_OPS = ("sqrt32", "div32", "div64", "sqrt64", "rint32", "rint64",
                "scaleb32", "scaleb64")      # card-stress-1016's, the table's first


@pytest.fixture(scope="module")
def csl():
    """hw/card_stress_lib.py, by path (it imports the standard library only)."""
    spec = importlib.util.spec_from_file_location(
        "p6_card_stress_lib", ROOT / "hw" / "card_stress_lib.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_the_table_is_the_old_eight_then_the_new_seven():
    assert FE.STRESS_TILE_OPS == OLD_TILE_OPS + NEW_TILE_OPS
    assert len(set(FE.STRESS_TILE_OPS)) == len(FE.STRESS_TILE_OPS)


def test_the_table_and_the_drivers_op_reach_say_the_same_of_every_op(csl):
    driver = {op for op, reach in csl.OP_REACH.items() if reach == "tile"}
    table = set(FE.STRESS_TILE_OPS)
    assert driver == table, (
        f"OP_REACH says tile and the table does not: {sorted(driver - table)}; "
        f"the table says tile and OP_REACH does not: {sorted(table - driver)}")


def test_a_run_that_served_every_item_of_the_catalog_passes_the_reach_check(
        csl, monkeypatch):
    served = {it.op for it in csl.sweep_items()}
    assert set(NEW_TILE_OPS) <= served
    FE._check_reach(served, csl.OP_REACH)                 # must not raise
    # and the check can fail, by name: under the table of card-stress-1016
    monkeypatch.setattr(FE, "STRESS_TILE_OPS", OLD_TILE_OPS)
    with pytest.raises(FE.ExtractError) as exc:
        FE._check_reach(served, csl.OP_REACH)
    msg = str(exc.value)
    assert "OP_REACH and STRESS_TILE_OPS disagree" in msg
    assert all(op in msg for op in NEW_TILE_OPS), msg


def _flat(text):
    """A C header comment as one line: the leading asterisks and the line
    breaks taken out (project_figures.py reads clause5.c the same way)."""
    return re.sub(r"\s+", " ", re.sub(r"(?m)^\s*\*", " ", text))


def _body(text, signature):
    m = re.search(r"^%s.*?^}" % re.escape(signature), text, re.M | re.S)
    return m.group(0) if m else ""


def c_tool_problems(clause5, divsqrt):
    """What the C soak tools must say for the seven ops to be tile ops, as
    the list of what their text does not say (empty: all of it)."""
    flat = _flat(clause5)
    out = []
    if ("Which of them reach a device: scaleb32-all and scaleb32-wide are "
            "composed from tile passes") not in flat:
        out.append("clause5_soak.c does not say scaleb32-all and scaleb32-wide "
                   "are composed from tile passes")
    if ("Which of them reach a device: rint64-class and scaleb64-class"
            not in flat):
        out.append("clause5_soak.c does not say rint64-class and scaleb64-class "
                   "reach a device")
    if flat.count("SAME batch kernels as the random mode of the operation") < 2:
        out.append("clause5_soak.c does not say its exhaustive and class modes "
                   "call the random mode's batch kernels")
    for op in ("div32-hard", "div64-hard", "sqrt64-hard"):
        if '{ "%s", ' % op not in divsqrt:
            out.append(f"divsqrt_soak.c has no hard-case mode {op}")
    if "run_batch(" not in _body(divsqrt, "static int soak_hard("):
        out.append("divsqrt_soak.c: soak_hard does not call run_batch")
    if "lib_call(" not in _body(divsqrt, "static int run_batch("):
        out.append("divsqrt_soak.c: run_batch does not call lib_call")
    lib = _body(divsqrt, "static cft_status lib_call(")
    if "cft_div(dev" not in lib or "cft_sqrt(dev" not in lib:
        out.append("divsqrt_soak.c: lib_call does not call cft_div and cft_sqrt")
    return out


def test_the_c_tools_say_what_each_of_the_seven_was_read_from():
    clause5 = (ROOT / "host" / "tools" / "clause5_soak.c").read_text(
        encoding="utf-8")
    divsqrt = (ROOT / "host" / "tools" / "divsqrt_soak.c").read_text(
        encoding="utf-8")
    assert c_tool_problems(clause5, divsqrt) == []


@pytest.mark.parametrize("old, new, problem", [
    ("composed from tile passes", "composed from host code",
     "scaleb32-all and scaleb32-wide are composed"),
    ("rint64-class and scaleb64-class (the latter",
     "conv64to32-class (the latter", "rint64-class and scaleb64-class reach"),
    ("SAME batch kernels", "own batch kernels", "random mode's batch kernels"),
], ids=["scaleb32", "class", "kernels"])
def test_the_reading_of_clause5_soak_can_fail(old, new, problem):
    """The control: the same text with the sentence changed is reported."""
    clause5 = (ROOT / "host" / "tools" / "clause5_soak.c").read_text(
        encoding="utf-8")
    divsqrt = (ROOT / "host" / "tools" / "divsqrt_soak.c").read_text(
        encoding="utf-8")
    assert old in clause5
    out = c_tool_problems(clause5.replace(old, new), divsqrt)
    assert any(problem in p for p in out), out


@pytest.mark.parametrize("old, new, problem", [
    ("rc = run_batch(sp->op", "rc = other_batch(sp->op", "soak_hard does not call"),
    ("cft_sqrt(dev, fmt, cr, a, d, n, fl, NULL)", "other(dev)", "lib_call"),
], ids=["soak_hard", "lib_call"])
def test_the_reading_of_divsqrt_soak_can_fail(old, new, problem):
    clause5 = (ROOT / "host" / "tools" / "clause5_soak.c").read_text(
        encoding="utf-8")
    divsqrt = (ROOT / "host" / "tools" / "divsqrt_soak.c").read_text(
        encoding="utf-8")
    assert old in divsqrt
    out = c_tool_problems(clause5, divsqrt.replace(old, new))
    assert any(problem in p for p in out), out


def _committed_sweep():
    path = ROOT / "docs" / "figures" / "stress.json"
    return json.loads(path.read_text(encoding="utf-8"))["data"]["sweep"]


def test_the_extract_records_the_tile_ops_the_run_served_not_the_table():
    sweep = _committed_sweep()
    served = {it["op"] for it in sweep["items"]}
    # what a remake from card-stress-1016 writes is what is committed
    assert FE.tile_ops_served(served) == sweep["tile_ops"]
    assert sorted(served - set(FE.STRESS_TILE_OPS)) == sweep["host_ops"]
    assert tuple(sweep["tile_ops"]) == OLD_TILE_OPS
    # the table is wider than that run, and the extract does not follow it
    assert len(FE.STRESS_TILE_OPS) > len(sweep["tile_ops"])
    # a run that served a new op records it, after the ops it shares
    assert FE.tile_ops_served(served | {"div32-hard", "scaleb32-wide"}) == \
        list(OLD_TILE_OPS) + ["div32-hard", "scaleb32-wide"]
    # and a host op, or one nothing here knows, is no tile op
    assert FE.tile_ops_served({"logb32", "zz-unknown-op32"}) == []


def test_make_stress_writes_the_served_tile_ops_and_checks_reach():
    """make_stress needs a finished run's metrics.jsonl, which is never
    committed, so the two calls that carry this are held in its source."""
    tree = ast.parse((ROOT / "python" / "figure_extracts.py").read_text(
        encoding="utf-8"))
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "make_stress")
    called = {c.func.id for c in ast.walk(fn)
              if isinstance(c, ast.Call) and isinstance(c.func, ast.Name)}
    assert {"tile_ops_served", "_check_reach"} <= called
    # no whole-table copy goes into the extract
    assert "list(STRESS_TILE_OPS)" not in ast.get_source_segment(
        (ROOT / "python" / "figure_extracts.py").read_text(encoding="utf-8"),
        fn)
