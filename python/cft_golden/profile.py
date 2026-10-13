# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""The conformance profile this golden model defines (CONFORMANCE.md,
"Versioning").

The profile versions the bits: the elementwise operations its vector
sets record, and - since 2026-10-02, Logan's decision 6 on certificate
version 2 (docs/studies/CERT-V2.md, section 16) - the program model as
seq.py defines it. Any change to what an accepted image computes, or to
whether an image loads, steps it: a change to an accepted image's result
or acceptance is a major step, and an addition that changes none (an
encoding every loader refused, now taken) a minor one. The record that
backs the rule - vectors/SHA256SUMS, the golden corpus's states - is a
backstop: the rule, not the record, defines when the number moves.

A version-2 certificate names the profile its bits are claimed under on
its `profile` line, and an auditor compares it with VERSION below to
decide who is blamed when a re-derivation fails (`definition-differs`,
docs/CERTIFICATES.md).

Profile 1 was the vector sets of 2026-09-16 and the model of that day.
Profile 2 (2026-10-02): under the extended rule ee78152 (2026-10-01)
was a major step - seq.py's loader refused images whose header declares
more than 512 constants, which the model of 2026-09-16 loaded and ran -
and revision 8's forms (codes 10 to 14 and the STX/LDX step) and
revision 7's scratch depth as a run's parameter (a run at the default
computes what it did) minor ones. No certificate or record named a
profile between them, so they are one major step, taken on 2026-10-02
(CONFORMANCE.md says so).

Profile 3 (2026-10-05), a major step: recorded bits moved. exp2 at
x = emin - p, whose exact value 2^(emin - p) is half the smallest
subnormal - the tie between +0 and it - was rounded as a quarter of it:
+0 under roundTiesToAway, where IEEE 754 gives the subnormal.
transcend.py rounds the exact power now, and so does libcft; the four
rmm transcendental sets each moved by that one case (step 6's M1,
question 5; Logan's decision of 2026-10-05).

The tree is at profile 3.1 (2026-10-13), a minor step: an addition that
changes no recorded case and no accepted image. The transcendental test
pools lost the sign of every negative threshold n ln2 (vectors.py and
host/tests/transcend_check.py took the mantissa from mpmath's to_man_exp,
which is unsigned by default, and tested its sign), so exp's underflow
edges were in no pool and no published set. Each of the 20 transcendental
sets gains the 25 signed images of the five negative n for each of the
seven functions that read the pool (exp, expm1, exp2, log, log1p, log2,
log10): 175 cases a set, 3,500 in all, and 1,068,915 cases become
1,072,415. Every recorded case, every other set and the model keep their
bits (parcel PS; Logan's decision of 2026-10-13). A profile-3 certificate
stays covered. The pool generators read the mpf's raw tuple now and call
to_man_exp nowhere: mpmath 1.4 deprecates its unsigned default, and the
sets must not change with the version of mpmath that makes them.
"""

# (major, minor): spelt "3", or "3.1" once a minor step is taken
VERSION = (3, 1)
