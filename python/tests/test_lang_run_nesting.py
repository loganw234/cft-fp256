# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""lang.run refuses a mis-nested list by name, never with a TypeError (KL-334).

run() converts its inputs with list(): `states` is a list of lanes, each a
list of the state's encodings; `lane_params` the same; `tangents` a list of
lanes, each a list of vectors, each a list of the state's encodings. A
list where a lane belongs - `states=[0, 0, 0]`, `tangents=[[1, 0]]` for a
system with two tangent vectors - made list() raise TypeError out of
run(), where every other fault of an input is a Refusal by name
(docs/LANGUAGE.md, "Refusals of a run"). Each level of each argument is
`lane-shape` now, naming the thing that was not a list.

A run's inputs are not a source, so the refusal has no file and no line
(`line` and `source` are None, str() leads with `<text>`): the test says so.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cft_golden import lang  # noqa: E402

PLAIN = "system s\nformat fp64\nstate x, y\nnext x = x\nnext y = abs(x)\nstep map\n"
TANGENT = ("system s\nformat fp64\nstate x, y\ntangent v, w\n"
           "next x = x\nnext y = abs(x)\nstep map\n")
ONE = 0x3FF0000000000000            # 1.0 at fp64


@pytest.fixture(scope="module")
def plain():
    return lang.compile_text(PLAIN, "<t>").graph


@pytest.fixture(scope="module")
def tangent():
    return lang.compile_text(TANGENT, "<t>").graph


def refused(graph, **kw):
    with pytest.raises(lang.Refusal) as exc:
        lang.run(graph, steps=1, **kw)
    return exc.value


STATE_CASES = [
    ("states is a number", dict(states=0), "states is 0, which is not a list"),
    ("states is None", dict(states=None),
     "states is None, which is not a list"),
    ("a flat list of encodings", dict(states=[0, 0]),
     "lane 0 of states is 0, which is not a list"),
    ("the second lane is None", dict(states=[[0, 0], None]),
     "lane 1 of states is None, which is not a list"),
    ("a lane that is a float", dict(states=[[0, 0], [0, 0], 1.5]),
     "lane 2 of states is 1.5, which is not a list"),
]
LANE_PARAM_CASES = [
    ("lane_params is a number", dict(states=[[0, 0]], lane_params=3),
     "lane_params is 3, which is not a list"),
    ("a flat list of values", dict(states=[[0, 0]], lane_params=[0]),
     "lane 0 of lane_params is 0, which is not a list"),
    ("the second lane is True", dict(states=[[0, 0], [0, 0]],
                                     lane_params=[[], True]),
     "lane 1 of lane_params is True, which is not a list"),
]


@pytest.mark.parametrize("label, kw, sentence", STATE_CASES + LANE_PARAM_CASES,
                         ids=[c[0] for c in STATE_CASES + LANE_PARAM_CASES])
def test_a_mis_nested_state_or_lane_param_list_is_lane_shape(
        plain, label, kw, sentence):
    r = refused(plain, **kw)
    assert (r.name, r.line, r.source) == ("lane-shape", None, None)
    assert r.sentence == sentence
    assert str(r) == f"<text>: lane-shape: {sentence}"


TANGENT_CASES = [
    ("tangents is a number", dict(tangents=1),
     "tangents is 1, which is not a list"),
    ("tangents is None", dict(tangents=None), None),
    ("a flat list of vectors' values", dict(tangents=[1]),
     "lane 0 of tangents is 1, which is not a list"),
    ("a lane of numbers, the count right", dict(tangents=[[1, 0]]),
     "lane 0's tangent v is 1, which is not a list"),
    ("the second vector is None", dict(tangents=[[[0, 0], None]]),
     "lane 0's tangent w is None, which is not a list"),
    ("the second lane's first vector is 2.5",
     dict(states=[[0, 0], [0, 0]], tangents=[[[0, 0], [0, 0]], [2.5, [0, 0]]]),
     "lane 1's tangent v is 2.5, which is not a list"),
]


@pytest.mark.parametrize("label, kw, sentence", TANGENT_CASES,
                         ids=[c[0] for c in TANGENT_CASES])
def test_a_mis_nested_tangent_list_is_lane_shape(tangent, label, kw, sentence):
    kw = dict(dict(states=[[0, 0]]), **kw)
    r = refused(tangent, **kw)
    assert (r.name, r.line, r.source) == ("lane-shape", None, None)
    if sentence is None:        # tangents=None: the old refusal, unchanged
        assert "carries the tangent vectors v, w" in r.sentence
    else:
        assert r.sentence == sentence
        assert str(r) == f"<text>: lane-shape: {sentence}"


def test_the_same_calls_nested_right_run(plain, tangent):
    """The controls: a refusal above is about the nesting and nothing else.
    Lists and tuples alike (whatever list() takes still goes through)."""
    s = [ONE, ONE]
    z = [0, 0]
    a = lang.run(plain, [s], 3, lane_params=[[]])
    b = lang.run(plain, (tuple(s),), 3, lane_params=((),))
    assert a.states == b.states == lang.run(plain, [s], 3).states
    t = lang.run(tangent, [s, s], 2, tangents=[[z, z], [z, z]])
    u = lang.run(tangent, (tuple(s), tuple(s)), 2,
                 tangents=(((0, 0), (0, 0)), ((0, 0), (0, 0))))
    assert t.states == u.states and t.tangents == u.tangents


@pytest.mark.parametrize("junk", [None, 0, 1.5, True, object()],
                         ids=["None", "int", "float", "bool", "object"])
def test_no_type_error_escapes_for_any_junk_at_any_level(plain, tangent, junk):
    """Each argument of run() with a non-sequence put at each depth: the
    argument, a lane, a vector. A Refusal by name every time; the TypeError
    was the bug."""
    z = [0, 0]
    calls = [
        (plain, dict(states=junk)),
        (plain, dict(states=[junk])),
        (plain, dict(states=[z], lane_params=junk)),
        (plain, dict(states=[z], lane_params=[junk])),
        (tangent, dict(states=[z], tangents=junk)),
        (tangent, dict(states=[z], tangents=[junk])),
        (tangent, dict(states=[z], tangents=[[junk, z]])),
        (tangent, dict(states=[z], tangents=[[z, junk]])),
    ]
    for graph, kw in calls:
        try:
            lang.run(graph, steps=1, **kw)
        except lang.Refusal as r:
            assert r.name == "lane-shape", (kw, r)
        # a TypeError (or anything else) is not caught: it fails the test.
        # No refusal at all is right once: lane_params=None takes the defaults.
