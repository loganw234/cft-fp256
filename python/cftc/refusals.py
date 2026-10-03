# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""The compiler's refusals, raised through the language's one class.

The language has one exception and one list of names
(cft_golden.lang.refusals: CATALOGUE for the checker and the
interpreter, COMPILER_REFUSALS for these). The compiler raises its seven
through that class - never a subclass, never a class of its own - so a
writer meets one form of refusal from the parser to the image:
`<source>:<line>: <name>: <sentence>`.

  target-format      the graph's format is not one the target carries
  target-feature     the image needs a feature bit the target does not
                     publish - revision 8's flag control, for an image
                     holding a routine, on revision 7's targets (C4)
  program-capacity   more instructions than the target's image holds
  scratch-capacity   state, lane params and spills past the target's
                     scratch depth a lane
  loader-bound       more than 2^40 worst-case instructions, the
                     loader's bound on every device
  segment-steps      a step count outside 1 to 2^32 - 1, the REPEAT
                     immediate a segment's steps are
  halving-underflow  an h-scaled constant whose exact halving
                     underflows, so no step-halving bank holds it

and one of the language's own: `bank-capacity`, the bank's 512 on every
device, which the checker raises for params and constants and the
compiler for the words of the routines it inlines (C4) - one limit, one
name, the cause in the sentence.

Until parcel C4 an eighth, `runtime-routine`, refused a run-time division
or square root (L4); C4 compiles them, and the name went with it.
"""

NAMES = ("target-format", "target-feature", "program-capacity",
         "scratch-capacity", "loader-bound", "segment-steps",
         "halving-underflow")
# the language's names the compiler raises too, for a cause the checker
# cannot see (the module docstring)
SHARED = ("bank-capacity",)


class InternalError(AssertionError):
    """The compiler broke one of its own invariants: a defect in the
    compiler, never a property of the source. The internal check (check.py)
    raises it, and so does any step that finds its input inconsistent."""


def refusal(name, sentence, source=None, line=None):
    """The language's Refusal for one of the compiler's names."""
    if name not in NAMES and name not in SHARED:
        raise InternalError(f"{name!r} is not one of the compiler's "
                            f"refusals")
    from cft_golden.lang import Refusal          # L1's one class
    return Refusal(name, sentence, line=line, source=source)


def refuse(name, sentence, source=None, line=None):
    raise refusal(name, sentence, source, line)
