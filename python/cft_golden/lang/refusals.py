# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""Every refusal the language makes, by name.

A source the language will not take, a run the interpreter will not
start, and bytes that are not a step graph all end the same way: one
exception, `Refusal`, carrying a short kebab-case NAME, the SOURCE and
LINE it is about (None when it is about the file, the run or the bytes
as a whole) and a SENTENCE saying what was wrong. Nothing else escapes
the parser or the checker - a bare IndexError from a malformed source
would be a refusal nobody could look up, which is the failure this
file exists to make impossible (python/tests/test_lang.py fuzzes the
references to hold it).

CATALOGUE is the list of the checker's and the interpreter's names,
each with what it refuses, and COMPILER_REFUSALS the names reserved for
the compiler (L2), which raises them through this same class. Together
they are the one list: docs/LANGUAGE.md's tables are held to it, the
gate makes every CATALOGUE name by a test (the compiler's own gate makes
its names), and a refusal raised under a name in neither is an internal
error rather than a new name.
"""

CATALOGUE = {
    # -- text and declarations ---------------------------------------
    "character": "a byte or a character the text does not hold: bytes "
                 "that are not UTF-8; a line end other than LF or CR LF "
                 "(a lone CR, VT, FF, 0x1c-0x1e, NEL, U+2028, U+2029) or "
                 "a NUL or Ctrl-Z, anywhere; outside a comment, anything "
                 "but printable ASCII, space and tab",
    "syntax": "the text is not a statement of the language",
    "too-deep": "parentheses nested more than 100 deep - in the source, "
                "or in the canonical form it would have - or a system the "
                "checker cannot evaluate from a caller whose own stack is "
                "already deep (Python's recursion limit); never a chain, "
                "which may be any length",
    "constant-range": "a constant whose exact value lies beyond "
                      "2^+-1048576, outside every format by far",
    "missing-system": "no `system` line",
    "missing-format": "no `format` line",
    "missing-state": "no `state` line",
    "missing-step": "no `step` line",
    "duplicate-declaration": "system, format, round, step or an "
                             "expansion block declared twice",
    "unknown-format": "a format other than fp32, fp64, fp128 and fp256",
    "unknown-rounding": "an attribute other than rne, rtz, rdn, rup "
                        "and rmm",
    "unknown-integrator": "an integrator other than rk4, euler, "
                          "stormer-verlet and map",
    "duplicate-name": "a name declared twice",
    "reserved-name": "a keyword, a built-in, h or a refused name used "
                     "to name a value",
    "undefined-name": "a name used and never declared",
    "array-length": "an array whose length is not written as a whole "
                    "number from 1 to 32,768",
    "lane-capacity": "a lane of more than 32,768 values (state and lane "
                     "params), the deepest scratch any tile publishes",
    "unused": "a const, param, lane param, let or h that nothing uses; h "
              "is used only where a constant of the step scales with it",
    "cycle": "a definition that depends on itself",
    "not-constant": "a value needed when the program is compiled that "
                    "reads the state, a param, a lane param or a let",
    "bank-capacity": "more than 512 params and constants: the bank "
                     "holds 512 on every device",
    # -- equations, indices, the step ---------------------------------
    "missing-equation": "a state component with no equation",
    "duplicate-equation": "a state component with two equations",
    "mixed-equations": "a system with both d/dt and next equations",
    "not-state": "an equation whose target is not a state component",
    "integrator-mismatch": "a flow's integrator on a map, map on a "
                           "flow, or an expansion block on a map",
    "index-range": "an index outside a non-cyclic array, an undefined "
                   "component of a let array, or an empty range",
    "index-not-integer": "an index that is not integer arithmetic on "
                         "literals and the statement's index variable",
    "array-index": "a scalar indexed, or an array named without its "
                   "index",
    "unbound-index": "an index variable bound by nothing",
    "missing-step-size": "rk4, euler or stormer-verlet without h",
    "step-size-zero": "a step h whose exact value is zero",
    "h-nonlinear": "a constant in which h appears other than as a "
                   "rational multiple of it",
    "h-scope": "h read by a flow's equations or a default",
    "step-option": "an option the integrator does not take",
    "verlet-partition": "q and p that do not split the state, each "
                        "component in exactly one",
    "verlet-not-separable": "a position's right-hand side reading a "
                            "position, or a momentum's a momentum",
    "expansion-mismatch": "a written-out step that is not the "
                          "integrator's expansion",
    # -- the variational equations --------------------------------------
    "tangent-mismatch": "a written tangent equation, tangent let or "
                        "expansion line that is not the derivation's",
    "tangent-scope": "a tangent component read where it cannot be: by the "
                     "state's equations, lets or constants, or by another "
                     "tangent vector's equations; or a tangent vector read "
                     "whole",
    # -- operations v1 does not have -----------------------------------
    "runtime-division": "a division with an operand that is not a "
                        "constant",
    "runtime-sqrt": "a square root at run time",
    "transcendental": "a transcendental function at run time",
    "irrational-constant": "a square root or transcendental of a "
                           "constant, which no rational carries",
    "power": "^ or **",
    "not-equal": "!=",
    "chained-comparison": "a comparison of a comparison, unparenthesised",
    "time-dependence": "t used in an equation and declared nowhere",
    "unknown-function": "a call of a name that is not a built-in",
    "arity": "a built-in given the wrong number of arguments",
    # -- the values a rational cannot carry ----------------------------
    "constant-negative-zero": "-0 written as a constant",
    "constant-infinity": "inf or infinity written as a constant",
    "constant-nan": "nan or snan written as a constant",
    "constant-division-by-zero": "a constant divided by a constant "
                                 "zero",
    "constant-overflow": "a constant whose one rounding overflows",
    "constant-rounds-to-zero": "a nonzero constant whose one rounding "
                               "is zero",
    # -- the interpreter's inputs and the graph's bytes ----------------
    "lane-shape": "a lane with the wrong number of values",
    "lane-value": "a lane value that does not fit the format",
    "unknown-param": "a run value for a name that is not a param, or "
                     "an h for a system that has none",
    "param-value": "a run value that is not an exact rational (a Python "
                   "float is binary64 already) or an encoding that does "
                   "not fit the format",
    "step-count": "a step count that is not a whole number of at "
                  "least 0",
    "step-size-sign": "a run's h of the other sign from the graph's: a "
                      "constant may hold h's sign, fixed when the graph "
                      "was compiled",
    "graph-format": "bytes that are not a step graph of version 1 (or 2, "
                    "with tangent vectors)",
}

# The compiler's refusals, reserved for it (L2): the target's stated
# capacities (the plan's item 10), which depend on the lowering and on
# the device, and two of the compiled image's own. The checker never
# raises these; the compiler raises them through the same Refusal, so
# the language has one class and one list of names, and
# docs/LANGUAGE.md gives each its sentence.
COMPILER_REFUSALS = {
    "scratch-capacity": "registers plus scratch past the target's: "
                        "2,048 slots on the U50's revision 7, 256 "
                        "elsewhere",
    "program-capacity": "more instructions than the target's image "
                        "holds",
    "loader-bound": "more than 2^40 worst-case instructions, the "
                    "loader's bound on every device",
    "target-format": "a format the target does not carry",
    "target-feature": "a feature whose CAPS bit the target does not "
                      "publish",
    "segment-steps": "a step count outside 1 to 2^32-1, the range of "
                     "the REPEAT immediate a segment's steps are",
    "halving-underflow": "an h-scaled constant whose exact halving "
                         "underflows, so the step-halving bank cannot "
                         "hold it exactly",
}

# Every name a Refusal may carry: the checker's and the interpreter's,
# then the compiler's.
NAMES = {**CATALOGUE, **COMPILER_REFUSALS}


class Refusal(ValueError):
    """The language's one exception: a refusal by name - the checker's,
    the interpreter's and the compiler's.

    `name` is a key of NAMES (CATALOGUE or COMPILER_REFUSALS),
    `sentence` says what was wrong in the source's own terms, `line` is
    the 1-based source line or None, and `source` names the text (a
    path, or `<text>`). str() is `<source>:<line>: <name>: <sentence>`."""

    def __init__(self, name, sentence, line=None, source=None):
        if name not in NAMES:
            raise AssertionError(f"refusal {name!r} is in neither the "
                                 f"catalogue nor the compiler's names")
        self.name = name
        self.sentence = sentence
        self.line = line
        self.source = source
        super().__init__(self._text())

    def _text(self):
        where = self.source or "<text>"
        if self.line is not None:
            where = f"{where}:{self.line}"
        return f"{where}: {self.name}: {self.sentence}"

    def __str__(self):
        return self._text()

    def with_source(self, source):
        """The same refusal, naming its source - set once, by the entry
        point that knows the file, so the parser need not carry it."""
        if self.source is None:
            self.source = source
            self.args = (self._text(),)
        return self


def refuse(name, sentence, line=None):
    raise Refusal(name, sentence, line)


def too_deep(what):
    """The refusal for a recursion the package will not deepen: Python's
    limit is kept, since below 3.11 a deeper Python recursion is a
    deeper C stack. Chains and runs of minus are walked in loops, and a
    definition read by name at any depth is evaluated from the top
    (check.py, BUDGET); what is left to recurse is nesting, which the
    parser bounds at 100, so a system the language accepts meets the
    limit only from a caller already deep in its own stack. It said "or
    shorten a chain of lets" until D2, when a chain of lets could not be
    any length (2026-10-01)."""
    return Refusal("too-deep", f"{what} nests deeper than this package "
                   f"evaluates from here (Python's recursion limit, which it "
                   f"keeps): name parts of it with lets, or call it from a "
                   f"shallower stack")
