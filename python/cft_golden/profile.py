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
The tree is at profile 2: under the extended rule ee78152 (2026-10-01)
was a major step - seq.py's loader refused images whose header declares
more than 512 constants, which the model of 2026-09-16 loaded and ran -
and revision 8's forms (codes 10 to 14 and the STX/LDX step) and
revision 7's scratch depth as a run's parameter (a run at the default
computes what it did) minor ones. No certificate or record named a
profile between them, so they are one major step, taken on 2026-10-02
(CONFORMANCE.md says so).
"""

# (major, minor): spelt "2", or "2.1" once a minor step is taken
VERSION = (2, 0)
