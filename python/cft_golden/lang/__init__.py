# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""The language, golden-first: its definition in the golden model.

A system is a small text (docs/LANGUAGE.md): a format and a rounding
attribute, state, constants and parameters, equations, and an
integrator. This package is the language's definition of correct:

  compile_text / load   parse and check a system, refusing by name
                        (Refusal) anything the language does not take,
                        and return it with its step graph
  StepGraph             the checked form of one step - the input the
                        interpreter, the renderers and the compiler (L2)
                        read; canonical bytes, version 1, or 2 with the
                        variational equations (L3): the step's tangent,
                        derived node by node (tangent.py)
  run                   the reference interpreter: the step graph through
                        the golden softfloat, one operation a node, any
                        number of lanes, S steps; states and FLAGS, and a
                        system's tangent vectors beside its state
  render_canonical      the intention-out: the program in the language's
  render_math           canonical form, and the equations in conventional
                        notation, both regenerated from the step graph

    from cft_golden import lang
    system = lang.load("programs/systems/lorenz63-rk4-fp64.cftl")
    result = lang.run(system.graph, states, 100)
"""

from pathlib import Path

from .check import check as _check
from .graph import OPS, StepGraph
from .interp import Run, run
from .refusals import CATALOGUE, COMPILER_REFUSALS, NAMES, Refusal
from .render import GREEK, render_canonical, render_math
from .templates import INTEGRATORS, TEXT as TEMPLATE_TEXT


class System:
    """A checked system: its source's name and text, and its graph."""
    __slots__ = ("source", "text", "graph")

    def __init__(self, source, text, graph):
        self.source = source
        self.text = text
        self.graph = graph


def compile_text(text, source="<text>"):
    """Parse and check a system's text - a str, or a file's bytes, which
    is how a caller holding a file should pass it (a text-mode read
    turns a lone CR into a line end before the character rule could
    refuse it). A Refusal names the source."""
    graph = _check(text, source)
    if not isinstance(text, str):
        text = bytes(text).decode("utf-8")      # the check read it whole
    return System(source, text, graph)


def load(path):
    """compile_text of a file's bytes: UTF-8, held whole to the
    character rule (docs/LANGUAGE.md, "The text") - a byte-order mark
    included, which outside a comment is refused like any other
    character outside ASCII."""
    return compile_text(Path(path).read_bytes(), str(path))


__all__ = ["CATALOGUE", "COMPILER_REFUSALS", "GREEK", "INTEGRATORS", "NAMES",
           "OPS", "Refusal", "Run", "StepGraph", "System", "TEMPLATE_TEXT",
           "compile_text", "load", "render_canonical", "render_math", "run"]
