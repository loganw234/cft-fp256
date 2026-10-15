# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""The language's version (CONFORMANCE.md, "The language's version").

It versions what the language means: which sources it accepts and what
each one computes - the checker's refusals, the step graph, and the
reference interpreter, lang.run, which is the definition of correct for
every compiled image (docs/LANGUAGE.md).

  * a MAJOR step whenever an accepted source is refused, or computes
    another thing: a new keyword that an old source used as a name, a
    refusal added, a node's golden function changed;
  * a MINOR step for an addition that changes no accepted source: a
    function, an integrator or a statement the language refused before
    only because it did not have it.

It starts at 1 with certificate format version 2 (2026-10-02), the first
thing that names it: the majors the language would have taken from L1 to
then (verifier-VCV2 counted about four: the step-size-sign refusal, D2's
`unused` and `too-deep`, and `tangent` reserved) are before its count.

A version-2 certificate whose runs name a source states it on its
`language` line, and an auditor compares it with VERSION to decide who
is blamed when a re-derivation through the language fails
(`definition-differs`, docs/CERTIFICATES.md).

The steps:
  1    2026-10-02, with certificate format version 2.
  1.1  2026-10-15, M1's build, item 3: exp, expm1, exp2, log, log1p and
       log2, each an operation with transcend.py's golden function, their
       folds where the value of a constant is rational, and their tangent
       rules. Functions the language refused before only because it did
       not have them: every source accepted at 1 is accepted at 1.1 and
       computes the same, and a source refused at 1 is refused still,
       or, using one of the six, accepted (M1's question 9, Logan's
       answer, 2026-10-12). A source that was refused one way and is
       refused another now - log(0), `irrational-constant` at 1 and
       `constant-division-by-zero` at 1.1 - changes no accepted source.
"""

# (major, minor): spelt "1", or "1.1" once a minor step is taken
VERSION = (1, 1)
