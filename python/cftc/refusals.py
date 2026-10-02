# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""The compiler's refusals, raised through the language's one class.

The language has one exception and one list of names
(cft_golden.lang.refusals: CATALOGUE for the checker and the
interpreter, COMPILER_REFUSALS for these). The compiler raises its eight
through that class - never a subclass, never a class of its own - so a
writer meets one form of refusal from the parser to the image:
`<source>:<line>: <name>: <sentence>`.

  target-format      the graph's format is not one the target carries
  target-feature     the image needs a feature bit the target does not
                     publish
  program-capacity   more instructions than the target's image holds
  scratch-capacity   state, lane params and spills past the target's
                     scratch depth a lane
  loader-bound       more than 2^40 worst-case instructions, the
                     loader's bound on every device
  segment-steps      a step count outside 1 to 2^32 - 1, the REPEAT
                     immediate a segment's steps are
  halving-underflow  an h-scaled constant whose exact halving
                     underflows, so no step-halving bank holds it
  runtime-routine    a run-time division or square root (the language's
                     div and sqrt, L4), which the compiler carries only
                     as an inlined routine, from parcel C4: raised first,
                     on every target, at the first source line holding
                     one, whatever its statement, so that no source the
                     language accepts reaches an internal error (exit 70)
                     in between
"""

NAMES = ("target-format", "target-feature", "program-capacity",
         "scratch-capacity", "loader-bound", "segment-steps",
         "halving-underflow", "runtime-routine")


class InternalError(AssertionError):
    """The compiler broke one of its own invariants: a defect in the
    compiler, never a property of the source. The internal check (check.py)
    raises it, and so does any step that finds its input inconsistent."""


def refusal(name, sentence, source=None, line=None):
    """The language's Refusal for one of the compiler's names."""
    if name not in NAMES:
        raise InternalError(f"{name!r} is not one of the compiler's "
                            f"refusals")
    from cft_golden.lang import Refusal          # L1's one class
    return Refusal(name, sentence, line=line, source=source)


def refuse(name, sentence, source=None, line=None):
    raise refusal(name, sentence, source, line)
