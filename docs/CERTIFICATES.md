# Certificates

A certificate is a text file that says what a deterministic run was and
how accurate it is: which program ran, on which inputs, cut into which
segments, which state each segment began and ended on, what flags it
raised, and what its accuracy is, of which kind. An audit checks that
statement by re-running segments on an implementation the producer does
not control, starting each from its certified start state. This page is
the whole of versions 1 and 2. Every section up to "Version 2" is version
1's, and stays its contract; "Version 2" adds what version 2 adds and
keeps version 1's rules where it does not say otherwise. A reader and an
auditor of either version can be written from it alone. An auditor reads
both versions, choosing by the magic line, and version 1's verdicts are
unchanged but for one rule that came with version 2: a wider run of a
routine image is refused `aux-image` ("Auxiliary runs"). The golden
auditor does so, and so does `cft-audit`, which reads both versions since
version 2's C half and audits in C every step of version 2 that needs no
source ("Version 2"; "The audit tool").

Where version 1 stands (2026-09-30; version 2's own is under "Version
2"):
- the golden implementation is `python/cft_golden/cert.py`: encode,
  strict parse, the hashes, the chain and the audit, which re-runs
  segments with `seq.run`;
- its gate is `python/tests/test_cert.py`, run by the golden stage,
  with a negative control, watched failing, for each mechanism "The
  controls" counts, and none yet for those it names as found without
  one;
- libcft names its build and its device image, `cft_build_id` and
  `cft_get_image_id` ([HOSTAPI.md](HOSTAPI.md), "Identity at ABI
  0.15");
- the segment runner, `cft-segrun`, writes version-1 certificates from
  the library (see "The segment runner"), their accuracy entries
  included since the plan's step 5 (2026-09-30; [ROADMAP.md](ROADMAP.md),
  "Steps 5 and 6"), and the `programs` stage holds them byte for byte to
  the golden writer. Since version 2's C half (2026-10-02) it writes
  version 2 by default, and version 1 with `--format-version 1`, byte for
  byte what it wrote before;
- the C auditor, `cft-audit`, audits them in C beside the golden one
  (see "The audit tool"), and the `audit` stage holds its verdicts equal
  to `cert.audit`'s (2026-09-29; the plan of record,
  [ROADMAP.md](ROADMAP.md), "Steps 4 and 7"). The two C tools compute
  an entry's value with one code, `host/tools/cert_exact.h`;
- the golden certificates, twelve programs and their certificates in
  `certificates/`, hold both writers to committed bytes (see "Golden
  certificates"), and version 2's cases beside them hold the golden
  writer and auditor, and cft-audit beside the golden auditor since its
  C half (cft-segrun's remake of them is the next parcel's);
- `cft-orbits` certifies its own runs on the Newton route, each sample
  interval a segment of one image, with its angular momentum's drift as
  an exact entry where asked (2026-09-30; [ORBITS.md](ORBITS.md),
  "Certified runs"), and the `workloads` stage holds each to the golden
  writer and to both auditors.

## What a certificate says, and what an audit proves

**The statement.** "These bits came from this program, these inputs and
these parameters. Any conforming implementation reproduces them from the
same inputs. The producer says it ran them on this library build and
this device image. Their accuracy is this, of this kind."

**What an audit proves.**
- The RESULT of every segment it re-runs: from its certified start
  state, with the program and bank it was handed being the ones
  certified, the segment ends on its certified end state and raises its
  certified flags and STATUS.
  - A full audit re-runs every segment of every run.
  - A sampled audit re-runs k of a run's S segments. A producer who
    made f of the S segments wrong escapes it with probability
    C(S-f, k) / C(S, k), and the verdict says so, with the value for
    f = 1, which is (S - k) / S.
- That each auxiliary run is what it claims to be relative to the main
  run (see "Auxiliary runs").
- That each accuracy value is the stated function of certified runs.
  It does NOT prove that an estimate is a good one, that a quantity
  called energy is the model's energy, or that the bank slots a
  half-step run names are the ones that carry the step.

**What it does not prove.**
- The producer's identity claims. The library build and the device
  image are recorded so the run can be reproduced; every conforming
  build computes the same bits, so the bits cannot tell which build
  made them. An audit reports each identity field as stated, not
  checked.
- Authorship. The hash line catches corruption, not forgery. Nothing in
  version 1 is signed, and anyone can write a self-consistent
  certificate for bits it computed itself. A signature is detached (see
  "The detached signature"): version 2 defines it, Ed25519 over the body
  hash, and it signs a version-1 certificate as it signs its own, the
  certificate's bytes the same signed or not.
- Independence, for a certificate that libcft's software backend made:
  libcft made it, so only the golden auditor is an implementation
  independent of it there.

## Keyed or open

Every certificate is KEYED or OPEN. The owner chooses, per certificate
(Logan, 2026-09-28), and the certificate says which on its second line.

**Keyed.**
- Every state and stream hash is HMAC-SHA-256 under the owner's salt:
  exactly 32 bytes the owner draws at random and keeps.
- The certificate commits to the salt on its third line, as
  HMAC(salt, "cft-certificate 1 salt").
  - Believed, not tested here: the commitment BINDS the certificate to
    one salt (a second salt with the same commitment needs a SHA-256
    collision in HMAC's outer hash) and HIDES it (HMAC is taken to be a
    pseudorandom function of its 256-bit key). These are standard
    properties of HMAC, and verifier-C1's judgement.
  - It is never a bare SHA-256 of the salt. HMAC replaces a key longer
    than 64 bytes by that key's SHA-256 (RFC 2104), so a published
    SHA-256 of a long salt would BE the key. Verifier-C1 measured it,
    and it is why the salt is exactly 32 bytes.
  - A salt that is not random - a counter, a date, a password - can be
    recovered from its commitment by trying candidates, and then
    protects nothing.
- To audit, the owner hands an auditor the salt and the states. An
  audit handed no salt, or the wrong one, is refused by name.
- What it protects, while the salt stays secret and random: a reader of
  the published certificate cannot confirm a guessed state or stream
  from its hashes.
- What it does not protect:
  - the flag words and STATUS of every segment;
  - the accuracy values, which may be functions of the states (a
    drift for one lane is);
  - which states are equal (HMAC is deterministic, so equal states
    have equal hashes);
  - the program: its digests are unkeyed, and the classic banks are
    files in this repository;
  - the run lines: each run's format, lanes, steps, segment count and
    kind, and a half-step run's h-slots;
  - the parameters, in the clear by definition;
  - the identity fields.
  And it gives no integrity: the owner holds the key, and nothing is
  signed.

**Open.**
- Every state and stream hash is plain SHA-256 of the same tag and
  bytes. There is no salt and no commitment line.
- Anyone holding the states can audit. A salt handed to the audit of an
  open certificate is refused by name, so that nobody believes a salt
  meant something there.
- What it protects: nothing about the states beyond what SHA-256's
  preimage resistance gives a state of high entropy.
- What it does not protect: anyone can confirm a guessed state. A known
  initial condition, or any state with few plausible values, is
  confirmed by hashing it. Everything keyed does not protect, open does
  not either.

## The file

A certificate is bytes, and nothing else:
- printable ASCII (0x20 to 0x7E) and LF (0x0A). No CR, no tab, no byte
  above 0x7E;
- a sequence of lines, each ending in exactly one LF, none empty;
- each line a sequence of tokens separated by exactly one space, with
  no space at either end;
- the FIRST token of a line is its KEY. Each key has one place in the
  order below, and a line is read by its key.

It has three parts:

```
cft-certificate 1        <- the magic line
...                      <- the fields, in the order below
end                      <- the end line
hash <64 hex digits>     <- the hash line
```

The BODY is every byte from the start of the magic line to the LF that
ends `end`, inclusive. The hash line follows it and ends the file: no
byte comes after its LF.

## Encodings

Every value has ONE spelling. A reader refuses any other spelling,
including one that denotes the same value, so that one certificate is
one byte string.

- **Decimal integer:** `0`, or a nonzero digit followed by digits. No
  sign, no leading zero. At most 2^63 - 1. Counts, indices, lanes,
  steps, flag words and STATUS are decimal.
- **Digest:** 64 lowercase hex digits (a SHA-256 or HMAC-SHA-256
  value). A git commit is 40 lowercase hex digits.
- **Register word:** 8 lowercase hex digits, a 32-bit register as the
  register map prints it (VERSION, CAPS, CAPS2).
- **Element:** a value of the run's number format, as TWO tokens:
  - its bits, as exactly width/4 lowercase hex digits (16 for fp64,
    64 for fp256), leading zeros kept;
  - then its EXACT DECIMAL, which a reader holds to the hex. Every
    binary value is a finite decimal (2^-k = 5^k 10^-k), and its one
    spelling is:
    - a finite nonzero value, as `[-]D[.DDD]e[+-]X`: its significant
      digits with the first nonzero, the last nonzero (no trailing
      zero), a point after the first when there is more than one, `e`,
      the sign of the exponent always written, and the exponent X of
      the first digit's weight with no leading zero. One is `1e+0`, a
      half is `5e-1`, a hundred is `1e+2`;
    - +0 is `0` and -0 is `-0`;
    - +infinity is `inf` and -infinity is `-inf`.
    A NaN is never an element of a certificate. This is the exact mode
    of `chars.to_decimal` in the golden model. Its price is length: an
    fp256 subnormal's decimal runs to about 183,000 digits.
- **Rational:** a numerator and a denominator in hex, as one token
  `N/D`, in lowest terms:
  - the numerator carries the sign: `-` for a negative value, nothing
    for a positive one;
  - the denominator is positive;
  - neither has a leading zero;
  - zero is `0/1`;
  - a zero denominator is refused.
  So one third is `1/3`, minus one half `-1/2`, and 2/4, 0/3, -0/1,
  +1/3, 1/-3, 01/3 and 1/A are all refused as malformed. A token whose
  digits alone are past the width rule is refused `width` before its
  terms are reduced (see "The width rule").
- **Word:** one of the fixed words the line's definition lists, in
  lowercase.
- **Name:** a label or a parameter's name: a lowercase letter, then
  lowercase letters, digits and `-`, at most 64 characters.

**What a person reads.** The identity lines; the mode; the run lines'
formats, lanes, steps and segment counts; each segment's flag word and
STATUS; each accuracy entry's method, kind, scope and value - the
decimals beside a rounded or enclosed value are there for a person.
The digests and hashes are for machines. An exact rational is written
for machines too; the golden model's `Fraction` or any bignum reads it.

## The width rule

Every exact rational the format carries - each coefficient, each exact
value - has a numerator of at most 1,023 bits in magnitude and a
denominator of at most 1,023 bits, in lowest terms. So does every value
an audit computes on the way to an accuracy value - each element's exact
value, each product, each partial sum and each difference - in the
order this page fixes (see "Accuracy entries"). A value past it is
refused, `width`, by every writer and every reader, the golden model's
included, and nothing past it is ever approximated: a writer asked for a
rounded or enclosed value of an exact value past the rule refuses it,
as it would refuse the exact value.

**A rational's token is held to it by its digits first.** The reader
takes a rational's token in this order: its spelling (`malformed`);
then each part's digits against the rule, before anything is converted
or reduced (`width`); then zero's one spelling, 0/1, and last lowest
terms (`malformed`). A part spelt without leading zeros is past 1,023
bits when it has more than 256 hex digits, or 256 whose first is 8 or
more. So a long token that is not in lowest terms is `width`, and a
short one `malformed`: an auditor whose exact arithmetic is 2,048 bits
wide cannot hold a longer token, let alone reduce it, and the golden
reader's reduction of one would cost the square of its length (the
lead's decision, 2026-09-29). A token in lowest terms has its value's
own parts, so its digits decide the rule for its value too.

**Its reach over a value's elements.**
- An ENCLOSURE's two ends are compared with the exact value, an exact
  step like the others, so each finite end is held to the rule, and an
  end past it is refused `width` by the reader. An infinite end is
  compared by its sign alone.
- The reader takes an enclosure's line in this order: the format; the
  lower end's hex digits, then that it is not a NaN, then its decimal;
  the same for the upper end (`malformed`, `malformed`, `decimal`);
  then each finite end against the rule, the lower first (`width`);
  and last whether the lower end is above the upper (`malformed`). So
  an end past the rule is refused `width` only when both ends are
  spelt right, and before the ends are compared.
- A ROUNDED value's element is not held to it: the audit rounds the
  exact value into the named format and compares the BITS, which needs
  no exact comparison. Rounding an in-rule value, at most 1,023 bits,
  into fp256 takes an integer division of about 1,023 + 240 bits.

Why 1,023: one exact step on two such values, a/b + c/d = (ad + cb)/bd,
needs 2 x 1,023 + 1 = 2,047 bits of magnitude. libcft's unsigned bigint
holds 2,048 at its default width (`host/src/bigint.h`), so that fits
with one bit to spare; a rule of 1,024 bits would need 2,049, which does
not. A product needs 2,046, and a comparison of a/b with c/d compares
two such products. So a C auditor built at the default width can compute
every in-rule step without overflow, and, applying the same rule to the
same values in the same order, cannot differ from the golden auditor on
width. `cft-audit` is that auditor ("The audit tool"). Its gate holds
its verdicts to the golden auditor's on every width control
test_cert.py makes, and its arithmetic to Python's integers.

A narrower build is not a conforming auditor of exact values. By
default the bigint is 576 bits at an fp128 ceiling and 288 below, and
`CFT_BN_LIMBS` can keep it at 2,048 under either
(`host/include/cft_config.h`). A build whose bigint is narrower must
refuse to audit a certificate that carries an exact value, rather than
audit it differently. `cft-audit` built so refuses `build-width` (exit
78, a name of the tool's own) at an `accuracy` line counting 1 or more.

For the values these runs produce, 1,023 bits is room enough. Over one
segment of order-one states, the drift of Henon-Heiles' cubic energy
has denominator 2^171 x 3 (173 bits) at fp64, and 2^720 x 3 (722 bits,
with a 704-bit numerator) at fp256. Verifier-C1 measured both
denominators, and the golden stage reproduces them on every run. A
cubic of fp256 values near one is about 3 x 240 bits, so a quartic
still fits and a quintic does not.

## The lines, in order

The lines come in this order. A line marked (K) is present in a keyed
certificate only. Groups repeat as their count says.

**The header.**

| line | values |
|---|---|
| `cft-certificate 1` | the magic line: the format and its version |
| `mode <m>` | `keyed` or `open` |
| `salt-commitment <digest>` (K) | HMAC(salt, "cft-certificate 1 salt") |
| `build-id <id>` | the library's `cft_build_id()` string, verbatim: `commit=<40 or 64 lowercase hex> tracked=<clean\|modified> untracked=<none\|present>`, its three fields in that order, or `unknown` whole |
| `backend <w>` | `software`, `xrt`, `remote` or `unknown` |
| `device-xclbin <digest>` | SHA-256 of the xclbin loaded, `none` or `unknown` |
| `device-version <word>` | the register map's VERSION, `none` or `unknown` |
| `device-caps <word> [<word>]` | the raw words `cft_get_image_id` gives: CAPS alone for an image below VERSION 0x800, CAPS then CAPS2 from it; or `none` or `unknown` alone |
| `device-tiles <n>` | compute units, at least 1, or `unknown` |
| `runs <R>` | how many run blocks follow; at least 1 |

**A run block**, R of them. Run 0 is the main run; runs 1 and later are
auxiliary.

| line | values |
|---|---|
| `run <i> main` | run 0, and only run 0 |
| `run <i> half-step h-slots <n> <slot> ...` | an auxiliary run at half the step: 1 <= n <= 512 bank slot indices, each below 512 (a bank's reach), strictly increasing |
| `run <i> wider` | an auxiliary run one format wider |
| `program-format <fmt>` | `fp32`, `fp64`, `fp128` or `fp256` |
| `program-image <digest>` | SHA-256 of the program image's bytes |
| `program-digest <digest>` | SHA-256 of the image bytes then the bank bytes: `cft_program_digest` |
| `lanes <n>` | at least 1 |
| `steps <n>` | steps a segment, at least 1: stated, not checked |
| `stream-a <digest>` | the hash of input stream a (see "Hashes") |
| `stream-b <digest>` | stream b |
| `stream-c <digest>` | stream c |
| `parameters <p>` | how many parameter lines follow; 0 or more |
| `parameter <name> <n>` | a non-negative integer parameter the bank does not carry: stated, not checked, but for one name. Names strictly increasing in byte order. A real-valued parameter belongs in the bank, where the program digest covers it. The one name read is `scratch-depth`: the run's scratch depth where `device-caps` gives none (see "The chain"), a power of two in 1..32,768 |
| `segments <S>` | how many segment lines follow; at least 1 |
| `segment <k> start <digest> end <digest> flags <n> status <n>` | segment k: the hashes of its start and end states, its sticky IEEE flag word (0..31) and its STATUS (0..2^32-1) |
| `output <digest>` | the hash of the run's final state |

**The accuracy block.**

| line | values |
|---|---|
| `accuracy <A>` | how many entries follow; 0 or more |

**An entry**, A of them.

| line | values |
|---|---|
| `entry <j> <method>` | `drift`, `step-halving` or `wider` |
| `kind <k>` | `measurement` for drift, `estimate` for the other two. `bound` is a word of the grammar, and no version-1 method has one |
| `uses <r>` | the run it is a function of |
| `scope lane <i>` or `scope max-lanes` | one lane, or the maximum over lanes |
| `quantity <label> terms <t>` | drift only: the quantity's name and its term count, 1..64 |
| `term <rational> [s<slot> ...]` | drift only, t of them: a coefficient and up to 8 factors, each `s` and a decimal slot below 65,536 (the scratch counts are 16-bit), slots non-decreasing |
| `value exact <rational>` | the value, exactly |
| `value rounded <fmt> <rnd> <element>` | the value correctly rounded to fmt under rnd: `rne`, `rtz`, `rdn`, `rup` or `rmm` |
| `value enclosed <fmt> <element> <element>` | lo <= value <= hi, both in fmt, lo not above hi |

**The end.**

| line | values |
|---|---|
| `end` | the body's last line |
| `hash <digest>` | SHA-256 of the body |

The rounding attributes are IEEE 754-2019's: `rne` to nearest with ties
to even, `rtz` toward zero, `rdn` toward minus infinity, `rup` toward
plus infinity, `rmm` to nearest with ties away from zero.

### An example

This certificate is what `python/cft_golden/cert.py` writes for the
following recipe. `python/tests/test_cert.py` regenerates it and holds
this block to it byte for byte, and audits it.
- `programs/henonheiles-lf-fp64.cfta` with
  `programs/henonheiles-lf-fp64.classic.bank`: Stormer-Verlet, 100
  steps a segment.
- Two lanes of `programs/check.py`'s ensemble: lane i starts at x = 0,
  y = 0.1 + i/1024, px = 0.5, py = 0.
- Two segments, and beside them a half-step run: the same image with
  bank slots 0, 1 and 2 (H, H2 and MH) exactly halved, for four
  segments.
- Keyed, under the example salt: the bytes 00 01 02 ... 1f. It is
  printed here, so it must never be used.
- Two entries:
  - lane 1's energy drift, exact. Its denominator is 3 x 2^163: the
    y^3/3 in the energy leaves a 3 that neither hex nor a finite decimal
    can write, which is why rationals exist;
  - the step-halving estimate over both lanes, rounded upward to fp64.

<!-- the example certificate -->
```
cft-certificate 1
mode keyed
salt-commitment 14599c5e32d506724573517b8c32df264cbc4e6b6ad7198cce440fe26d84e1ff
build-id unknown
backend software
device-xclbin none
device-version none
device-caps none
device-tiles 1
runs 2
run 0 main
program-format fp64
program-image af8b49674a8053b28b631ad50714e61eb0ec51487b3f40d6490b87bfe357ec77
program-digest 56e22d0376b099b4221f5f0639d20dc947f62d4752d4d32837b613a6ce3f7e3e
lanes 2
steps 100
stream-a 87a9cc070651e023fab7e78a1b231a255792e0f080cc65ae37016a13aecd2d6f
stream-b a1ed0921019e6d04aca20ab6707b45e13d4216d0e4279258d1984ba77f437bd4
stream-c e283c4c0dd49286dfb605e205822aa2d90d991293a49ea51b13b7abdcb9336a0
parameters 0
segments 2
segment 0 start ee6508ace7a1dcbc0f4e9082db9bf2e614c88ca9987fa624caaaceaac44b87a4 end 3f2db08a33712f4c7135070db2e3d8fab1f1f0f472614d6713bafe792f5a2035 flags 16 status 0
segment 1 start 3f2db08a33712f4c7135070db2e3d8fab1f1f0f472614d6713bafe792f5a2035 end b4f26e93e3d8f6a00ecd20ecbaf039d18fb86a0442893d6a34c4c93c70e7bae5 flags 16 status 0
output b4f26e93e3d8f6a00ecd20ecbaf039d18fb86a0442893d6a34c4c93c70e7bae5
run 1 half-step h-slots 3 0 1 2
program-format fp64
program-image af8b49674a8053b28b631ad50714e61eb0ec51487b3f40d6490b87bfe357ec77
program-digest 85c03659d2b667f74bb9afd5b7db799b67e2dc2220c31de7c887417223e790f8
lanes 2
steps 100
stream-a 87a9cc070651e023fab7e78a1b231a255792e0f080cc65ae37016a13aecd2d6f
stream-b a1ed0921019e6d04aca20ab6707b45e13d4216d0e4279258d1984ba77f437bd4
stream-c e283c4c0dd49286dfb605e205822aa2d90d991293a49ea51b13b7abdcb9336a0
parameters 0
segments 4
segment 0 start ee6508ace7a1dcbc0f4e9082db9bf2e614c88ca9987fa624caaaceaac44b87a4 end d099071f1f030e93ea21e18310868c4379f20b85f8c742243ac1daf66f8af09f flags 16 status 0
segment 1 start d099071f1f030e93ea21e18310868c4379f20b85f8c742243ac1daf66f8af09f end cdaca71e48e60b49e369a871d912e4e65844a900945236e2bf62cc2e74d37884 flags 16 status 0
segment 2 start cdaca71e48e60b49e369a871d912e4e65844a900945236e2bf62cc2e74d37884 end 3f0b01916a84e5db64db9e5f9834f4b575f7aee322421a0cabbc9289eb4bd5dc flags 16 status 0
segment 3 start 3f0b01916a84e5db64db9e5f9834f4b575f7aee322421a0cabbc9289eb4bd5dc end 5623e8c94a1ef88b23112a7f7006e32e57449b1a92a98b9f12b2bf78ccdbb058 flags 16 status 0
output 5623e8c94a1ef88b23112a7f7006e32e57449b1a92a98b9f12b2bf78ccdbb058
accuracy 2
entry 0 drift
kind measurement
uses 0
scope lane 1
quantity energy terms 6
term 1/2 s2 s2
term 1/2 s3 s3
term 1/2 s0 s0
term 1/2 s1 s1
term 1/1 s0 s0 s1
term -1/3 s1 s1 s1
value exact -187d1b4c62da5865743a607042ae87c0e8227/180000000000000000000000000000000000000000
entry 1 step-halving
kind estimate
uses 1
scope max-lanes
value rounded fp64 rup 3ed9a053ec030000 6.109781395646773916041638585738837718963623046875e-6
end
hash 6e6f7de25934d892382ede1ef4213dc9b64813c43fa3cbd639f4efb3919dd434
```

Reading it: every segment raised inexact (flag word 16) and nothing
else, with STATUS 0. The half-step run starts on the main run's initial
state (the same start hash) and has twice its segments. Lane 1's energy
fell by about 9.7e-7 over the 200 steps. Halving the step moved the
final state by at most about 6.1e-6 in any slot of either lane - an
ESTIMATE, of which the audit proves only that it is this difference of
these certified runs.

## Hashes

**The body's hash.** The hash line is `hash`, one space, and the
SHA-256 of the body: every byte from the magic line to the LF that ends
`end`. It catches corruption: every byte of the body is covered by it,
including fields no other check reads, such as the build, the device,
the parameters and an unsampled segment's flags. It does not catch
forgery: anyone can write a body and hash it.

**A state** is the per-lane scratch block exactly as the library stores
it: lane-major - lane 0's slots, then lane 1's, and so on - and within a
lane, slots 0 upward; each element format-width and little-endian. It is
the block `seq.run` takes as `scratch_in` and gives back as
`scratch_out`, and the block libcft's scratch-in and scratch-out
pointers address. A run's boundary 0 is its initial state and boundary
k (1 <= k <= S) is segment k-1's end state.

**A stream** is one of the input streams a, b and c: n elements, one a
lane, format-width, little-endian, in lane order. They initialise r0, r1
and r2 in every lane at the start of every segment (docs/SEQUENCER.md).
A run's streams are the same for all its segments.

**The hashes** put a tag before the bytes. Each tag is ASCII, and
every tag but the salt's ends in a NUL (0x00), so that no message in one
domain is a message in another:

| what | tag |
|---|---|
| the salt commitment | `cft-certificate 1 salt` (no NUL, and no bytes after it) |
| a state | `cft-certificate 1 state` then 0x00, then the state's bytes |
| stream a, b or c | `cft-certificate 1 stream a` (b, c) then 0x00, then its bytes |
| the sampling PRNG | `cft-certificate 1 sample` then 0x00, then the input under "The audit" |

- In a keyed certificate, the hash of a state or stream is
  HMAC-SHA-256(salt, tag || bytes), as RFC 2104 defines it with SHA-256
  and its 64-byte block.
- In an open certificate, it is SHA-256(tag || bytes).
- The salt commitment is HMAC-SHA-256(salt, "cft-certificate 1 salt").

**Test vectors.** `python/tests/test_cert.py` holds each of these to the
implementation and to a second HMAC written from RFC 2104 with hashlib
alone:
- the example salt;
- a state of one fp64 lane of two slots, 1 and -0.5, with its keyed and
  open hashes;
- stream a of two fp64 lanes of +0, keyed;
- a sample (see "The audit").

<!-- the test vectors -->
```
salt             000102030405060708090a0b0c0d0e0f101112131415161718191a1b1c1d1e1f
salt-commitment  14599c5e32d506724573517b8c32df264cbc4e6b6ad7198cce440fe26d84e1ff
state-bytes      000000000000f03f000000000000e0bf
state-hash       1864ace3e9596d754451c3a3ce52f501e0409d17ef7dacb3e24e3351c8a47e95
open-state-hash  b7d023303a9909e06a08ae7312ea7234df5c0c28b9be154f769dd70bde4b358c
stream-a-bytes   00000000000000000000000000000000
stream-a-hash    87a9cc070651e023fab7e78a1b231a255792e0f080cc65ae37016a13aecd2d6f
sample-seed      0000000000000000000000000000000000000000000000000000000000000000
sample-run       0
sample-of        10
sample-k         3
sample           1 4 9
```

## The chain

A **segment** is one dense run of the program:
`seq.run(image, a, b, c, bank=bank, scratch_in=start,
scratch_depth=depth)`, where:
- every lane is active;
- no index table and no lane mask are used;
- the streams are the run's;
- the start state is the segment's start;
- `depth` is the scratch depth the run had (revision 7, 2026-09-29):
  `1 << CAPS2[3:0]` when `device-caps` carries CAPS2 with CAPS2[4] set,
  for every run, since a certificate names one device - 256 on the
  round-2 images, 2,048 on the U50's revision-7 ones; otherwise the
  run's `scratch-depth` parameter, where it states one, which is how a
  software handle opened deeper says its depth (the lead's decision,
  2026-09-29); and 256, the model's default, otherwise (`none` for the
  software backend opened plainly; a CAPS word alone; `unknown`). A
  non-strict `STX`/`LDX` reduces its index modulo the depth, and a
  state wider than 256 slots only loads on a deeper device, so a run is
  re-run at the depth it had or it is a different machine.
  `cert.scratch_depth_of` is the rule.

Its end state is the run's `scratch_out`, its flag word the run's sticky
IEEE flags (invalid 1, divide-by-zero 2, overflow 4, underflow 8,
inexact 16) and its STATUS the run's STATUS word.

**An auditor may compute a segment a block of lanes at a time**, and
the golden auditor does, 64 lanes to a block as libcft's software
backend does (`cert.run_segment`; the lead's decision, 2026-09-29). The
tile's block is LATENCY beats of a format's lanes - 128 lanes at fp32,
64 at fp64, 32 at fp128 and 16 at fp256 (docs/SEQUENCER.md) - and no
verdict depends on a block's size. Each block is the same run over its
own lanes' streams and start state. The end state is the blocks' end
states in lane order, and the flag word and STATUS are the OR of the
blocks'. This is the dense run exactly. Lanes share nothing but the
early exit, which is invisible (docs/SEQUENCER.md, P3): every write and
every flag is masked by the lane's active bit, which is also what lets
lanes be split across tiles. It is done so that a re-run holds one
block's scratch at the certified depth, not every lane's (see "What an
audit spends").

**A program is a segment** when its whole state travels through the
scratch block and nothing else comes out:
- its header sets `SCRATCH_IO`;
- its scratch-in and scratch-out counts are equal and at least 1;
- it deposits nothing (`max_deposits` 0).
A program that deposits is refused rather than half certified: version
1 certifies the state, and a deposit would go unchecked. The ODE
programs in `programs/gen_odes.py` are segments.

**Continuity.** In each run, segment k's start hash is segment k-1's end
hash, for every k >= 1, and the output hash is the last segment's end
hash. Equal states have equal hashes, so continuity is checked from the
certificate alone.

## Auxiliary runs

An estimate compares the main run with another run: a **half-step** run,
or a run one format **wider**. Such a run is certified as a run of its
own - its own program digests, lanes, streams and chain - and an audit
samples it like the main run instead of re-running all of it. It also
carries its RELATION to the main run, and the audit checks that
relation, in this order, before it re-runs anything:

| check | a half-step run | a wider run |
|---|---|---|
| `aux-format` | the main run's format | the next rung: fp32 to fp64, fp64 to fp128, fp128 to fp256. At fp256, the top of the ladder, refused: a program image is at most fp256, so a rounding estimate by a wider re-run cannot exist there |
| `aux-lanes` | the main run's lanes | the main run's lanes |
| `aux-image` | the same steps a segment, and the same image digest; then the main run's scratch depth | the same steps; a main image that holds no QUIET, ENDQUIET or RAISE (below); an image that is the main image one format wider: the same instruction words, `max_deposits`, flags, constant count and scratch word, the precision code one rung up, and any constants the image carries exactly widened; then the main run's scratch depth |
| `aux-segments` | twice the main run's segments | the main run's segments |
| `aux-h-slots` | the main image takes its constants from a bank, and each named slot is inside that bank and holds a finite nonzero value there | (none named) |
| `aux-bank` | each named slot exactly half the main bank's value; every other slot bit-identical | every slot the main bank's value exactly widened |
| `aux-streams` | the same stream hashes | each stream the main run's exactly widened |
| `aux-start` | the same initial-state hash | the main run's initial state exactly widened |

"Exactly widened" is the contract's convertFormat to the next rung: it
is exact for every finite and infinite value, and a NaN becomes the
wider format's canonical quiet NaN. The wider checks of streams and
start state need the main run's streams and initial state handed to the
audit.

An auxiliary run is the main run's instructions on the same machine, so
it runs at the main run's scratch depth ("The chain"; the lead's
decision, 2026-09-29). Where `device-caps` names a depth, every run has
it; where runs state their own by the `scratch-depth` parameter, a run
at another depth reduces a non-strict `STX`/`LDX` by another modulus,
and is refused `aux-image` - where its image loads at its own depth. An
image that does not load there is refused `program-image` at step 4
first.

Why a wider run is held to its instructions rather than to its image
digest: an image's header carries its format's precision code, so an
image one format wider cannot be the same bytes (`seq.Program.to_bytes`
and `asm.Image.to_bytes` both write it).

**A routine image has no wider run** (the lead's decision, 2026-10-02,
with the step-6 round's C4). A main image that holds revision 8's flag
control - any QUIET, ENDQUIET or RAISE (docs/SEQUENCER.md, R24) - holds a
routine, and a routine's words and bank words are format-specific (masks,
biases, Newton passes). Its words one rung up can pass every check above
and compute nothing the main run means. So every writer refuses to
certify a wider run of such an image, and every audit refuses one,
`aux-image` (exit 5):
- **The criterion.** The main image holds a control word (bit 31 set)
  whose code, its low byte, is 12, 13 or 14. Its words are read after the
  header and after any constants the image carries (none under an
  external bank).
- **The audit** checks it on each wider run, after `aux-format`,
  `aux-lanes` and the steps, and before the instruction words and the
  scratch depth. Its location is the wider run (`run=1` where it is run
  1), and its sentence is the writer's: "run 1 (wider): the main image
  holds a routine (QUIET, ENDQUIET or RAISE), whose words are its
  format's, so no image is it one format wider; certificate version 2's
  wider-source run compiles its source one format up instead".
- **A writer** checks the main image too, and makes nothing. cft-segrun
  checks it once every run's own checks have passed, and before the
  accuracy entries. The golden writer's `cert.certify_run`, handed the
  main image beside a wider run, checks it after the wider run's shape
  and states and before its steps and parameters, which the golden writer
  reads only at `encode`. So where one wider run has two faults - a
  routine main image and steps 0, a parameter out of order or a parameter
  named twice - the two writers can name different ones first, which
  version 1's contract allows: a writer's refusal names a fault it found,
  in no order the contract fixes. With the rule's fault alone they agree,
  W1 and W2 below among it.
- **Who holds it:** the golden writer's `cert.certify_run` and the golden
  audit (`cert.routine_words`), and `cft-segrun` and `cft-audit` from
  parcel C4's C half, with version 2's wider relation the same.
  `CFT_SEGRUN_PLANT=wider-routine` makes cft-segrun write the certificate
  it refuses, so that an audit has one to refuse ("The segment runner").
  The controls are test_cert.py's and test_cert2.py's on markstep, the
  first handed to cft-audit by the audit tool's gate, and lang_check's
  leg E on Kepler, each with the same construction on Lorenz-63, which
  has no routine, written and accepted. The construction is the main image's
  words with header bytes 20 to 23, the precision code, set to fp128's,
  and its bank and initial state widened exactly. test_cert2.py also
  holds verifier-VCV2B's W1, a routine main image beside a wider image
  that holds no flag control (refused, by the golden writer as by
  cft-segrun), and W2, the reverse (written by both, and refused by the
  audit as not the main image's words).

Version 2's `wider-source` run, the program's source compiled one format
wider, is how such a program gets a wider estimate.

**The main run attached as its own half-step run is refused.** Without
these checks it would pass everything, with an estimate of 0
(verifier-C1). As itself, it has the main run's segments, not twice as
many (`aux-segments`). Run for twice as long on the main bank, its bank
is not halved (`aux-bank`).

What the relation proves: the auxiliary run is the main image, run from
the main run's start, with the named bank slots halved and twice the
segments; or the same program one format wider on exactly widened
inputs. It does not prove that the named slots are the ones that carry
the step h. A binary image keeps no constant names, so the producer
names the slots, and the certificate records the naming.

## Accuracy entries

Each entry names a METHOD, which fixes its KIND and the function of
certified runs its value is:

| method | kind | uses | the value |
|---|---|---|---|
| `drift` | measurement | any run r | Q(final) - Q(initial) of run r, for the polynomial Q the entry states |
| `step-halving` | estimate | a half-step run r | the largest absolute difference, over the state's slots, between run 0's final state and run r's |
| `wider` | estimate | a wider run r | the same, between run 0's final state and run r's |

**Kinds.**
- A **measurement** is a quantity of the run itself.
- An **estimate** is a number that indicates an error without bounding
  it.
- A **bound** is proved: a rigorous remainder, or an enclosure. No
  version-1 method has a rigorous remainder, so no version-1 entry is a
  bound, and "method error <= X" is never written by version 1. An
  entry whose kind is not its method's is refused, `accuracy-kind`.

**Scope.**
- `scope lane i` is lane i's value, signed for a drift.
- `scope max-lanes` is the maximum over the lanes of the absolute
  value.

**The quantity** of a drift is a polynomial in one lane's state, stated
in the entry: each `term` is a coefficient times the state values at
the slots it lists. `term -1/3 s1 s1 s1` is -y^3/3 when slot 1 holds y.
The label names it for a person. A term's factors list their slots in
non-decreasing order, so one monomial has one spelling. The ORDER of
the terms is the producer's statement: two certificates that list the
same terms in two orders are two certificates, stating the same
function. The order fixes the partial sums, though, so the width rule
can refuse one of the two and accept the other (below).

**The functions, exactly.** Each value is computed in exact rational
arithmetic, in this order, and every value computed - each element's
exact value as it is reached, each product, each partial sum, each
difference - is held to the width rule (refused `width`):
- An element's exact value is m x 2^e for its integer significand m
  and exponent e (zero for a zero). A non-finite element has none:
  refused, `accuracy-finite`.
- **drift**, for each lane i in scope, in lane order:
  - Q(state) = ((T_1 + T_2) + T_3) + ..., over the terms in the order
    listed, starting from 0.
  - Each term is T = ((c x v_1) x v_2) x ..., its coefficient
    multiplied by its factors' exact values, left to right, each
    factor's exact value taken as it is reached.
  - D_i = Q(final) - Q(initial): Q of the final state first, then Q of
    the initial state, then the difference. The initial state is
    boundary 0 of run r and the final state boundary S of run r.
- **step-halving** and **wider**, for each lane i in scope:
  - E_i = max over slots s of |F0[i][s] - Fr[i][s]|, the slots in
    order, starting from 0, and in each slot F0's value before Fr's;
  - F0 is run 0's final state and Fr is run r's;
  - so the estimate is defined only where run r has run 0's lanes and
    slots a lane. Where it has not, the entry is refused `accuracy-run`,
    after its run's kind and before its lane. An audit never meets that
    refusal, since step 8 refuses such a run first (`aux-lanes`,
    `aux-image`); a writer, which checks no relation, does (the lead's
    decision, 2026-09-30: the golden writer raised an IndexError there,
    or read run 0's state by run r's shape).
- A run, a lane and a slot are indices from 0. A writer handed a
  negative one, which no certificate can spell, refuses it by the check
  it fails: `accuracy-run`, `accuracy-scope` or `accuracy-slot`, where
  the index past the end is refused. An audit never meets one, since the
  reader refuses a certificate that spells one (the lead's decision,
  2026-09-30: the golden writer read a negative lane or slot by Python's
  index from the end, another lane's value, an IndexError past the
  state, or another lane's `accuracy-finite`; verifier-W1b).
- The value is D_i or E_i for one lane, or the maximum over the lanes
  of |D_i| or E_i.
- The order fixes every intermediate value, and so it decides two
  things, which two auditors must decide alike:
  - whether the width rule refuses at all. The terms 1/a, 1/b, -1/b,
    with a = 2^600 + 1 and b = 2^601 - 1, are refused at the partial
    sum 1/a + 1/b, whose denominator has 1,202 bits; the same terms
    as 1/b, -1/b, 1/a are within the rule at every step, and their
    value is the same;
  - which refusal comes first when two apply, as when a value past the
    rule stands next to a non-finite one.
  It cannot change a value that is computed.

**The value's form.**
- `exact`: the rational itself, in its one spelling.
- `rounded`: the exact value correctly rounded to the named format
  under the named attribute. Overflow and underflow are as the
  attribute says. An exact zero rounds to +0 under every attribute.
- `enclosed`: two elements with lo <= value <= hi, both ends inclusive,
  each finite end within the width rule. The golden writer takes the
  tightest pair in the format, the value rounded down and rounded up,
  and refuses it `width` when a finite end of it is past the rule,
  which can happen to a value within the rule: 1/(3 x 2^900), enclosed
  in fp256, has a lower end whose denominator has 1,139 bits. Either
  end can be the one: 1/(2^900 - 1) has a lower end of 901 bits and an
  upper end of 1,137, and 1/(2^900 + 1) a lower end of 1,138 and an
  upper end of 901. It widens neither end. Any pair that holds the value is accepted.

**What re-deriving proves.** Each value IS the stated function of states
whose hashes the certificate carries, and those states are the ones the
chain certifies. That an estimate estimates the error well is not
proved, nor that a stated quantity is conserved, nor that it is the
model's energy.

## Identity

The header's build, backend and device lines are the producer's
statement of what it ran on.
- `build-id` is the string libcft's `cft_build_id()` returns, copied
  byte for byte, so that a certificate names the library build in the
  library's own words. The library computes it, and this page only
  spells it (step 2's identity parcel, P2, defines it):
  - `commit=` and the commit checked out when the library was built,
    40 lowercase hex digits, or 64 in a repository that names objects
    by SHA-256;
  - `tracked=modified` if any tracked file differed from that commit,
    else `tracked=clean`;
  - `untracked=present` if any file git does not ignore was untracked,
    else `untracked=none`;
  - or `unknown`, whole, never partly known, where the build was not
    measured.
  Only `tracked=clean untracked=none` says the library IS that commit.
- The device lines are what `cft_get_image_id` reports for an XRT
  image: the SHA-256 of the exact xclbin bytes loaded, VERSION, and
  the raw CAPS words, one below VERSION 0x800 and two from it. The
  reader holds each identity line to its own spelling and nothing
  more: not the number of CAPS words to `device-version`, and not the
  device lines - `device-tiles` among them - to one another or to
  `backend`.
- Each may be `unknown`: the producer did not record it. A reader
  reports it as such.
- The device lines may be `none`: the field does not exist for this
  backend. The software backend has no xclbin and no registers.
- A run through a remote handle records the client's library build,
  since the server sends none, and the SERVER's device fields where
  the protocol carries them. A field it does not carry is `unknown`.
- The audit checks none of them and reports every one: stated, not
  checked, or unknown (see "What an audit proves").
- One of them is READ: CAPS2's scratch depth, which the chain's
  re-runs take (above, "The chain"; revision 7). Reading is not
  checking - a certificate that misstated its device's depth would fail
  its own re-run, as one that misstated any number the arithmetic reads
  would. A remote handle's certificate records `unknown` and is re-run
  at 256 unless its runs state a depth by their `scratch-depth`
  parameter, whatever its server's depth: the protocol carries no
  CAPS2, a limit of this version (below, "What version 1 does not do").

## The detached signature

Version 1 reserved it, and defined nothing more:
- it signs the body's hash, the 32 bytes the hash line carries;
- it lives in a file of its own, beside the certificate, never inside
  it, so the certificate's bytes are the same signed or not;
- a version-1 reader never reads a signature;
- version 1 defines no scheme.

Version 2 defines the scheme, and it signs a certificate of either version
(Version 2, "The detached signature"): Ed25519 over `cft-signature 1`, a
NUL and the body hash, in a five-line `<certificate>.sig`. A version-1
certificate signed so is still read and audited by version 1's rules,
which read no signature; the key tool, `python/cft_sign.py`, verifies its
signature.

## The strict reader

A reader decides, in this order, and refuses at the first failure:

1. **The hash line.** The file ends in LF, and its last line is `hash`,
   one space and 64 lowercase hex digits. Otherwise `hash-line`. The
   body is everything before that line.
2. **The body's hash.** SHA-256 of the body equals the hash line's
   value. Otherwise `body-hash`.
3. **The bytes.** Each body line is printable ASCII, not empty, with
   single spaces and none at either end. Otherwise `malformed`.
4. **The magic line.** The first line's key is `cft-certificate`
   (otherwise `magic`), and the line is `cft-certificate 1` exactly. A
   body whose first line is exactly `cft-certificate 2` is not version
   1's: the reader sends it to version 2's reader (Version 2, "Version
   2's strict reader"), so a version-1 body under that line is refused
   there, `line-missing` at `profile`. Any other second and last token
   spelt as a decimal integer is `version`, whatever its size - past
   2^63 - 1 too, since a version is a name here and not a count; anything
   else is `malformed`.
5. **The keys.** Every line's key is a key of version 1. Otherwise
   `unknown-line`, wherever the line stands.
6. **The mode.** The second line is the mode line (when it is not, the
   rules of step 7 name the refusal), and its value is `keyed` or
   `open`: any other value is `mode-unknown`. An open certificate with
   a `salt-commitment` line anywhere is `commitment-unexpected`. A keyed
   one with none is `commitment-missing`.
7. **The lines, in order**, as "The lines, in order" gives them.

**Counts first.** When the reader meets a count line, it reads the
count's own value first, in its range: runs and segments at least 1, a
drift's terms 1 to 64, h-slots 1 to 512. A count out of its range is
`malformed`, even where it also disagrees with its lines. Then it
counts the group's lines, before it reads any of them. A disagreement
is `count`, whatever else is wrong with them. So a group member
dropped, added or moved out of its group is a count that disagrees.
- `parameters`, `segments` and a drift's `terms` count the member lines
  that directly follow the count line.
- `runs` counts the `run` lines before the `accuracy` line (or `end`);
  `accuracy` counts the `entry` lines before `end`.
- `h-slots` counts the tokens that follow it on its own line.

**Indices.** A run's, a segment's and an entry's index is its position,
from 0. When the index is wrong:
- an index already passed is `line-unexpected`;
- the right index appearing later in the group is `line-order`;
- otherwise `line-missing`.
Parameter names increase strictly in byte order - ASCII's, so `a-b`
(0x2d) comes before `a0` (0x30): a repeated name is `line-unexpected`,
a smaller one `line-order`.

**A line that is not the one expected.** When the reader expects a line
with key K and finds a line with key k, the refusal is decided like
this, with the body divided into BLOCKS: the header; each run; the
accuracy line; each entry; `end`.
- If k begins a block (`run`, `accuracy`, `entry`, `end`) that comes
  later, or begins the next of the repeating runs or entries, K is
  missing: `line-missing`. A block-starting line whose block is already
  behind is `line-unexpected`.
- If k belongs to a block already behind, or to this block but before
  K, or to this block when K begins the next one, the line has no place
  here: `line-unexpected`. A line repeated in place is one of these.
- If a K line appears later in this block, the lines are out of order:
  `line-order`.
- Otherwise K is missing: `line-missing`. A line dropped is one of
  these.
- A line after `end` is `line-unexpected`.

**Values.** A line whose key is right and whose values break their
spelling, their range or their token count is `malformed`. A rational
past the width rule is `width`, found by its digits before its terms
are reduced ("The width rule"). An element's decimal that is not the
exact decimal of its hex is `decimal`. An entry whose kind is not its
method's is `accuracy-kind`.

With a salt handed to it, a reader also checks the salt (the audit's
step 3).

## The audit

**What an auditor is given:**
- the certificate;
- each run's program image and bank;
- the salt, for a keyed certificate, and nothing for an open one;
- the states it needs, by run and boundary;
- the streams, when they are not all +0;
- its own choice of segments for each run: all of them, named ones, or
  a random sample of k.

It needs the start state of each segment it re-runs, the initial state
of run 0 for a wider run's relation, and the states each accuracy entry
reads. A segment's start state need not be handed when the segment
before it was re-run in the same audit and matched: its end state is
then the certified start. So a full audit handed only each run's
initial state is possible, and is the most independent audit there is.

**The shape of what it is handed.** Each argument is held to its shape
by the step that reads it, before the step uses it, and an argument in
another shape is refused by that step's name. In the golden model's
terms (`cert.audit`), where a run index is an integer (never a bool)
naming a run of this certificate:
- `programs`: a mapping from every run index to (image, bank), the
  image as bytes and the bank as bytes, or None for an image that
  carries its own constants; a run missing, a key that is no run, or a
  value of another shape is refused `program-image`;
- `streams`: absent, or a mapping from run indices to (a, b, c), three,
  each None for +0 or the run's lanes of elements, as integers (each
  an element's bits) or as the bytes the library stores; a key that is
  no run, or a value of another shape, is refused `stream`;
- `states`: absent, or a mapping from run indices to a mapping from
  boundary indices to states, each the run's elements as integers or
  as bytes; a key that is no run or no boundary, or a state of another
  shape, is refused `state-shape`;
- `choose`: absent, or a mapping from run indices to `all`, a list or
  tuple of distinct segment indices, at least one, or the pair
  ("sample", k) with k an integer in 1..S; any other key or value is
  refused `choice`;
- `seed`: absent, or exactly 32 bytes, whether or not a sample is
  asked; anything else is refused `choice`;
- `salt`: see step 3 (`salt-missing`, `salt-length`, `salt-unexpected`,
  `salt-commitment`).
The certificate itself is bytes, and anything else is a TypeError of the
golden model's Python interface rather than a refusal: a reader in any
other language reads a file.

**What an audit spends.** An auditor's memory and time are bounded by
what it is handed - the certificate's bytes, each run's image and bank,
the states and streams, and its own choice - and never by a number the
certificate states (the plan's step 4, 2026-09-29).
- Every count the certificate states is held to the lines or tokens it
  counts before they are read ("Counts first"), and every index and slot
  to its range before it is used. So each costs the certificate's own
  bytes. A rational's token is held to the width rule by its digits
  before it is reduced ("The width rule").
- A run's `lanes` is the one number no line pays for: `lanes
  1000000000000` is one line, and a +0 stream of that run is 10^12
  elements. So a run is BOUNDED when the audit was handed a stream of
  it, or a state for one of its boundaries (0 to S) that holds at least
  `lanes` elements - for a state handed as bytes, at least `lanes` x
  width/8 bytes. Nothing else bounds a run.
- The audit builds and hashes a run's +0 streams only when the run is
  bounded (step 5), and hashes the main run's streams exactly widened
  only when the main run is bounded (step 8). Every other step that
  spends on `lanes` reads a state handed, or one re-run from it, that
  step 7 has held to `lanes` x slots.
- A run that is not bounded costs nothing, and cannot be accepted. A
  state handed for it with fewer than `lanes` elements cannot be its
  state (`state-shape`, step 7), and with none handed its re-runs have
  no start (`state-missing`, at step 9, or at step 8 when a wider run
  needs the main run's initial state). So the audit refuses it where it
  would have anyway, without first spending anything on its `lanes`.
- The re-runs' scratch depth is stated too, by `device-caps` or a run's
  `scratch-depth` parameter ("The chain"), and is at most 32,768 slots a
  lane by this page. An auditor re-runs a segment one block of lanes at
  a time ("The chain"), so a re-run holds one block's
  scratch at the certified depth: a constant the page fixes, whatever
  the lanes. In libcft's software backend a block is 64 lanes of depth
  x 260 bytes, 545 MB at 32,768 (`host/include/cft.h`); in the golden
  auditor 64 lanes of depth references, 16 MiB at 32,768 (measured with
  tracemalloc, 2026-09-29). Its time is at most the lanes handed times
  the depth, since a block's scratch starts at +0.
- A size is compared with a stated number exactly. `lanes` x slots and
  `lanes` x width/8 can pass 2^64, so an implementation with fixed-width
  integers divides the size handed rather than multiplying the number
  stated. The golden auditor's integers are exact either way, and it
  multiplies at step 7.

**The order of the checks.** An auditor refuses at the first failure,
and exits with that refusal's code (the table below), or 0 when every
check passes.

1. **Integrity:** the hash line, then the body's hash (`hash-line`,
   `body-hash`).
2. **Form:** the strict reader (all of "The strict reader").
   - Then the auditor's own **choice** of segments is held to the
     certificate: sample sizes 1..S; a named list not empty, its
     segments distinct and in 0..S-1; runs that exist; and a seed, when
     one is handed, of exactly 32 bytes, whether or not a sample is
     asked (`choice`, exit 64, a usage error).
3. **Salt.**
   - Keyed: a salt is handed (`salt-missing`), it is 32 bytes
     (`salt-length`), and its commitment is the certificate's
     (`salt-commitment`).
   - Open: no salt is handed (`salt-unexpected`).
4. **Programs**, run by run:
   - the image's SHA-256 is the value on the run's `program-image`
     line (else `image-digest`);
   - SHA-256 of the image then the bank is the value on its
     `program-digest` line (else `program-digest`);
   - the image loads (else `program-image`), its format is the one its
     `program-format` line names (else `program-format`), and it is a
     segment (else `program-shape`);
   - the bank is exactly the constants the image addresses, or empty for
     an image that carries its own (else `program-image`).
5. **Streams**, run by run. Each stream handed is n elements of the
   run's format, held first by its length, before anything is built
   beside it (`stream`). Then, for a bounded run, each of a, b and c, as
   handed or +0, holds only elements of the format and has the
   certified hash (`stream`). A run that is not bounded has its +0
   streams neither built nor checked (see "What an audit spends").
6. **Continuity**, run by run (`continuity`).
7. **States handed**, run by run and boundary by boundary: each is
   lanes x slots elements of a boundary that exists (`state-shape`),
   and its hash is that boundary's (`state-hash`).
8. **Relations**, run by run: all of run 1's checks in the order of the
   table under "Auxiliary runs", then all of run 2's, and so on
   (`aux-format` through `aux-start`, and `state-missing` when a wider
   run's check needs run 0's initial state). So run 1's `aux-start`
   comes before run 2's `aux-segments`. A wider run's `aux-streams`
   hashes the main run's streams exactly widened only when the main run
   is bounded. When it is not, no state of the main run was handed, and
   the wider run's `aux-start` refuses `state-missing`.
9. **Re-runs**, run by run, the chosen segments in ascending order,
   each computed a block of lanes at a time ("The chain").
   - Each starts from its start state, handed or re-run into
     (`state-missing` when neither).
   - One the executor refuses to run is refused `program-image`, at its
     run and segment.
   - It must end on its certified end state (`segment-end`), with its
     certified flag word (`segment-flags`) and STATUS
     (`segment-status`).
10. **Accuracy**, entry by entry:
    - the run it uses exists and is of the right kind, and an estimate's
      run has the main run's lanes and slots a lane (`accuracy-run`);
    - its lane exists (`accuracy-scope`);
    - its terms' slots exist (`accuracy-slot`);
    - the states it reads are known (`state-missing`), a drift's
      initial state before its final;
    - the value, re-derived under the width rule (`width`,
      `accuracy-finite`), is the value written (`accuracy-value`).

The re-runs come before accuracy because an audit handed only the
initial states obtains the final states by re-running. The auditor's
choice is checked right after the form, so that a usage error costs
nothing.

**Sampling.** The seed is the AUDITOR's: 32 bytes, chosen after the
certificate is fixed, and never taken from it. Were it derived from the
certificate, a producer could re-salt and re-hash, without re-running
anything, until the sample missed a segment it had not computed
honestly. The verdict prints the seed, so that the sample can be
reproduced. The golden auditor draws one from the operating system when
none is given. For run r, with S segments and a sample of k:
- **The words.** Block j (j = 0, 1, 2, ...) is
  SHA-256(`cft-certificate 1 sample` || 0x00 || seed || r || j), with r
  as 4 bytes big-endian and j as 8 bytes big-endian. Each block is read
  as four 64-bit big-endian words, in order, and the words of block 0
  come first.
- **A uniform integer below m.** Take the next word w. If w is below
  2^64 - (2^64 mod m), the result is w mod m. Otherwise take another
  word. No modulo bias.
- **The sample.** Start from the list 0, 1, ..., S-1. For j = 0 to
  k-1, exchange position j with position j + (a uniform integer below
  S - j). The sample is the first k positions, sorted ascending.
- The test vectors above include one sample.
- The golden model's `cert.sample(seed, r, S, k)` holds its arguments
  to this: a seed of exactly 32 bytes, r an integer in 0..2^32-1 (its
  four bytes), and S and k integers with 1 <= k <= S, never a bool;
  anything else is refused `choice`.

**The verdict** of an accepted audit says:
- ACCEPTED;
- the mode;
- for each run, which segments were re-run and how they were chosen.
  For a sampled run it gives the seed, the escape probability
  C(S-f, k)/C(S, k) with its value for f = 1 - (S - k)/S, reduced,
  and computed so, in time linear in the digits of S - and the segments
  the sample drew, ascending, spelt as a named choice's are: `[1, 3]`;
- each accuracy value, re-derived, with what that proves and what it
  does not;
- each identity field: unknown, or stated and not checked.

## Refusals

Every refusal has a name, and every name has an exit code. The codes
name families of checks - integrity 1, form 2, width 3, the inputs
handed to the audit 4, the chain and the relations 5, re-runs 6,
accuracy 7, the auditor's own usage 64. The name is the report.

| name | exit | when |
|---|---|---|
| `hash-line` | 1 | the file's last line is not `hash` and 64 lowercase hex digits, or there is none |
| `body-hash` | 1 | the hash line is not the SHA-256 of the body |
| `magic` | 2 | the first line is not the magic line, or the body is empty |
| `version` | 2 | the magic line names a version other than 1 and 2 |
| `mode-unknown` | 2 | the mode line's value is not `keyed` or `open` |
| `commitment-missing` | 2 | a keyed certificate has no `salt-commitment` line |
| `commitment-unexpected` | 2 | an open certificate has a `salt-commitment` line |
| `unknown-line` | 2 | a line's key is not a key of version 1 |
| `line-missing` | 2 | a line is missing where the order puts it |
| `line-order` | 2 | lines are out of their order |
| `line-unexpected` | 2 | a line has no place where it stands: a repeat, or a line of a block already read |
| `count` | 2 | a count disagrees with the lines or tokens it counts |
| `malformed` | 2 | a value breaks its one spelling, its range or its token count, or a line breaks the byte rules; a count out of its own range; a `scratch-depth` parameter that is not a power of two in 1..32,768; a writer asked to certify a run of no segments, handed a certificate object it cannot spell, or handed a field that does not read back as itself (a value of the wrong type); asked to write a value it cannot spell (not a rational, or a form, format or direction the page does not name) |
| `decimal` | 2 | an element's decimal is not the exact decimal of its hex |
| `accuracy-kind` | 2 | an entry's kind is not its method's; every `bound` in version 1 |
| `width` | 3 | an exact value past 1,023 bits in numerator or denominator: written (a rational's token found so by its digits, before its terms are reduced), computed (an element's, a product, a partial sum, a difference), an enclosure's finite end, or one a writer was asked to round or enclose |
| `salt-missing` | 4 | the audit of a keyed certificate was handed no salt |
| `salt-unexpected` | 4 | the audit of an open certificate was handed a salt |
| `salt-length` | 4 | a salt that is not 32 bytes |
| `salt-commitment` | 4 | the salt handed is not the one the certificate commits to |
| `image-digest` | 4 | the image handed is not the one certified |
| `program-digest` | 4 | the image and bank handed are not the ones certified |
| `program-image` | 4 | no image was handed, the image does not load, the bank is not the size it addresses, or the executor refuses a re-run; `programs` not in its shape |
| `program-format` | 4 | the image's format is not the run's |
| `program-shape` | 4 | the program is not a segment |
| `stream` | 4 | a stream handed (or +0, in a bounded run) is not the one certified, is not the run's lanes long, holds a value that is not an element, or is bytes that are not whole elements; `streams` not in its shape |
| `state-shape` | 4 | a state handed is the wrong size, holds a value that is not an element, is bytes that are not whole elements, or is for a run or boundary that does not exist; `states` not in its shape; a writer handed states and segment results that disagree in number, or a start that is not whole lanes |
| `state-hash` | 4 | a state handed is not the one certified at its boundary |
| `state-missing` | 4 | a state the audit needs was neither handed nor re-run into |
| `continuity` | 5 | a segment does not start where the one before it ended, or the output is not the last end |
| `aux-format` | 5 | an auxiliary run's format is not its relation's, including any wider run of an fp256 run |
| `aux-lanes` | 5 | an auxiliary run's lanes differ from the main run's |
| `aux-image` | 5 | an auxiliary run's image or steps are not the main run's, or the main run's one format wider, or it runs at another scratch depth than the main run's; a wider run of a main image that holds QUIET, ENDQUIET or RAISE |
| `aux-segments` | 5 | a half-step run without twice the segments, or a wider run without the same |
| `aux-h-slots` | 5 | a named h-slot outside the bank, or holding zero or a non-finite value there, or a main image that takes no bank |
| `aux-bank` | 5 | a bank that is not the main bank halved in exactly the named slots, or exactly widened |
| `aux-streams` | 5 | streams that are not the main run's, or its exactly widened |
| `aux-start` | 5 | an initial state that is not the main run's, or its exactly widened |
| `segment-end` | 6 | a re-run segment does not end on its certified end state |
| `segment-flags` | 6 | a re-run segment's flag word is not the certified one |
| `segment-status` | 6 | a re-run segment's STATUS is not the certified one |
| `accuracy-run` | 7 | an entry uses a run that does not exist, or one of the wrong kind; or an estimate's run has other lanes, or other slots a lane, than the main run |
| `accuracy-scope` | 7 | an entry names a lane the run does not have |
| `accuracy-slot` | 7 | a term names a slot the state does not have |
| `accuracy-finite` | 7 | an exact value needs an element that is not finite |
| `accuracy-value` | 7 | the value written is not the stated function of the certified runs |
| `choice` | 64 | the auditor's own arguments: a sample, segment or run the certificate cannot give it, `choose` not in its shape, or a seed that is not 32 bytes |

A refusal locates itself in fields, each empty where it does not apply:
the line, for the reader's refusals; for the audit's, the run where it
concerns one run (a run index the certificate has), the segment or
boundary where it concerns one of that run's, and the accuracy entry
where it concerns one entry (in the golden model, `.line`, `.run`,
`.segment` and `.entry`).

## The controls

`python/tests/test_cert.py` holds the mechanisms above to negative
controls, and each control asserts the NAME of the check it exists for,
never merely that something refused. Every control but the byte flip
writes a valid hash line over its defective body. Otherwise the hash
check would refuse them all first, and a broken strict-form check would
pass unseen (verifier-C1). What was measured is a census, not every
mechanism. Each of the following was disabled alone in a fresh copy of
the implementation, and a test went red for every one but the two named
after the list (the round's ledger, P1.md, 2026-09-28):
- each of the 144 refusals the golden model raises, disabled;
- each of the 35 spelling checks the reader makes through a helper, let
  through for that one line;
- each of the 41 orders the page states, reversed;
- each of the 42 moves of a limit the page states, one lower and one
  higher;
- each of the 106 parts of a condition on the way to a refusal, made
  neutral alone, and each of the 16 branches of the three functions
  that return a reason instead of raising one;
- each of the 47 words the reader allows, removed from it;
- each end of the writer's enclosure widened alone, and each of four
  checks the page says the reader does not make among the identity
  lines, added.
The two cannot change any answer, and are named rather than counted:
an index's length bound moved from 19 digits to 20 (a 20-digit decimal
is past 2^63 - 1, refused by its value either way), and a wider image's
`max_deposits` left out of the header fields compared (step 4 refuses a
program that deposits before step 8 compares two images). Verifier-C2
found twenty-two checks that no test could fail for (fourteen, then
eight), verifier-C4 four, and these plants 41 more. Each of those has a control now, except two
that no answer could see - a branch no input reached and a test that
another decided - which were removed. A computation - a hash, the
PRNG, an accuracy value's derivation - is held by the test vectors and
by values derived again with none of the implementation's code; it was
planted where P1's and verifier-C2's ledger entries say, not
exhaustively.

The census is not every mechanism. Verifier-C5's plants on ed66890
found these with no control; each change leaves every test green (its
ledger, 2026-09-28):
- five one-rule relaxations of a digest's spelling: `stream-a` of any
  length, `stream-b` or `stream-c` in upper case, a segment's start hash
  of any length, and its end hash in upper case. The malformed table
  holds one departure for each field, so a check that lets through a
  different one is not seen;
- `aux-image`'s half-step digest part, and separately its wider part,
  moved after `aux-segments`;
- seven orders the page states: steps 4, 5 and 7 run by run; a drift's
  lanes in order, and Q(final) before Q(initial), which has a control
  since the audit round (below); an estimate's slots in order, and F0's
  value before Fr's;
- two locations: the stream-hash refusal's run, and a count refusal's
  line;
- a fresh sampling seed drawn for each run, where the page draws one
  for the audit.

The controls cover:
- a byte flipped, one at a time, in every byte of a certificate that
  holds every key of the grammar;
- every line dropped;
- an unknown line inserted at every position;
- every line repeated in place;
- every adjacent pair of lines in a block exchanged, and whole blocks
  moved;
- every count, one more and one less, and each count out of its own
  range;
- each encoding's non-canonical spellings, each limit the page states
  read at its last value and refused one past it, and every word the
  page allows read and written back as itself;
- the width rule, at the reader, at the writer (each end of an
  enclosure alone past it, never widened), and at the audit on an
  element's own value, a product and a partial sum, and at an
  enclosure's ends;
- a decimal that disagrees with its hex; an element read hex, then NaN,
  then decimal, and an enclosure's lower end before its upper; and a
  version of any size. Since version 2, a version-1 body under
  `cft-certificate 2` reaches version 2's reader and is `line-missing` at
  `profile` (verifier-VCV2 named the two controls that moved from
  `version`), and `cft-certificate 3` is `version`;
- since 2026-10-02, a wider run of a routine image, refused `aux-image` at
  the wider run by the golden writer and audit, which audit_check.py hands
  to cft-audit since parcel C4's C half (test_cert2.py holds its sentence,
  its place and version 2's relation; C4's control is lang_check's leg
  E);
- the identity lines held to their spelling alone, `device-tiles`
  among them;
- each kind that is not its method's;
- the mode: an unknown mode, a missing or unexpected commitment, and a
  salt missing, unexpected, wrong or not bytes;
- a wrong image or bank, stream, or state; bytes that are not whole
  elements; and each argument of the audit in a shape it does not take;
- the writer: a field it cannot spell, and a run it cannot certify;
- a broken chain;
- a segment whose certified end, flags or STATUS differ, and one the
  executor refuses to run;
- every auxiliary relation, including the main run attached as its own
  half-step run, a wider image's constants and each header field, an
  h-slot that halving cannot change, and the relations checked run by
  run;
- every accuracy check, the values derived again from the states with
  none of the implementation's code, an estimate's last slot, and an
  enclosure's ends held inclusive;
- two of step 10's orders (verifier-A1, the audit round): Q of a
  drift's final state before Q of its initial state (a final +inf
  beside an initial value of 1,024 bits is `accuracy-finite`, not
  `width`), and its initial state needed before its final
  (`state-missing` at boundary 0, not S);
- the audit's order, every adjacent pair of its steps from the choice
  to accuracy, and an auditor's seed never the certificate's;
- the verdict's sampled segments, byte for byte;
- a run's `scratch-depth` parameter: the depths it can state and those
  it cannot, read where `device-caps` gives no depth and not where it
  does, and an auxiliary run held to the main run's depth;
- what an audit spends (the audit round, 2026-09-29):
  - `lanes` 10^12 and 2^63 - 1, on the main run alone and on all three
    runs, in full and sampled audits, with states handed and without.
    Each is refused by name at its place (`state-shape` at step 7, or
    `state-missing` at step 9, or at step 8 for a wider run). Each takes
    under a second, with its memory flat: the peak of tracemalloc's
    traced memory over the audit call is within 64 KiB of the same
    audit's at 10 lanes, and under 4 MiB. Measured on the desktop
    (2026-09-29): at most 9.5 ms and 31.8 KiB traced for each of the
    24, flat within 0.3 KiB, and the process's peak commit moved by
    nothing;
  - the rule's place: the `streams` argument's shape before any run; a
    stream handed held by its length before anything is built beside
    it; step 4 before; step 6 after, reached having spent nothing;
  - "at least `lanes` elements" at its edge, by values and by bytes
    (9 elements bound 9 lanes and not 10; 71 bytes bound 8 and not 9);
    the output's boundary S bounding as boundary 0 does, and one past S
    bounding nothing;
  - a run bounded by what was handed for it alone, which verifier-A3
    found held only by its run key:
    - by its own states and streams, never another run's: run 1
      stating 10^12 lanes beside streams handed for run 0 alone is
      `aux-lanes` at run 1, within a second, its memory flat;
    - by a stream handed, and (None, None, None), three +0 streams in
      the page's own spelling, hands none: the main run stating 10^12
      lanes beside it is `state-missing` at run 0 boundary 0, or
      `state-shape` there with its states, within a second, its
      memory flat;
    - by a state for one of its own boundaries, not the main run's:
      the half-step run handed its boundary 7 alone, past the main
      run's S of 4, and named to re-run segment 7, is ACCEPTED;
    - against its own `lanes`, not the main run's: run 1 stating
      10^12 lanes beside every run's own states is `state-shape` at
      run 1 boundary 0, within a second, its memory flat;
  - step 8's guard reading the main run's bound, not the wider run's:
    a bounded wider run beside a main run handed nothing is
    `state-missing` at run 0's initial state, and an unbounded wider run
    beside a bounded main run still has its streams held to the main
    run's widened, `aux-streams` at run 2 (verifier-A3's cases);
  - a segment computed 64 lanes at a time: its end state, flag word and
    STATUS equal to the dense run's, at a depth past 256, over three
    blocks, each raising a flag or a STATUS bit no other raises, the
    last leaving its loop early; and one block's scratch held at a time
    (256 one-slot lanes at 32,768 peak under 24 MiB);
  - a rational's digits held to the width rule before its terms: a long
    token not in lowest terms is `width`, a short one `malformed`, and
    the digits' edge at 256 hex digits, 7 and 8;
  - the escape probability for f = 1, (S - k)/S, equal to the
    binomials' ratio at every k of every S to 40, and linear;
  - every huge-`lanes` control runs under a net, so that a regression
    fails by name rather than loading the machine: on Linux an
    address-space limit 4 GiB above the process's own, and everywhere
    a watchdog that ends a run that hashes forever.

The rule's plants (the audit round, 2026-09-29) were each made in a
fresh copy of the implementation at 00c2a2f, and each turned a named
control red for its reason (the round's ledger, P3.md):
- the rule removed;
- the rule moved one step later, the +0 streams built before the bound
  is read;
- step 8's guard alone removed;
- "at least" made "more than";
- a run bounded by any run's states, by a state for any boundary, and
  not by the output's;
- a handed stream's length checked after the build;
- a dense re-run;
- each of four one-block readings of the flag word's and STATUS's OR;
- the blocks' end states out of lane order, and their start states
  sliced by lane;
- a rational's digits read after its gcd, or not at all, or its first
  digit taken as four bits;
- the escape probability computed by its binomials.
Eleven more plants hold the verdict's segments and the `scratch-depth`
parameter. Three of the four one-block readings were green against
e5af2f1, whose special lanes all sat in its last block, so that block's
flags and STATUS were the run's. The control was strengthened at
00c2a2f, and they are red.

The real audit is `programs/lorenz63-rk4-fp64.cfta` with its classic
bank:
- three lanes over four segments, with a half-step run of eight and a
  wider fp128 run of four, every chain built by `seq.run`;
- green in full, from the initial states alone, and sampled;
- red, naming segment 1, when a producer's boundary 2 is one bit wrong
  and it carries on from there.

The C auditor is held to these controls as well. Its gate hands it every
parse call test_cert.py makes, and every audit call whose arguments
files and options can carry, 244 of 283; the other 39 are counted and
named. It requires the golden auditor's verdict by name, code and
location ("The audit tool").

## The segment runner

`cft-segrun` is the C writer of any segment program, the plan's step 3.
It runs a program as consecutive segments on one libcft device handle,
keeps the state at every boundary, and writes a certificate, its accuracy
entries included since the plan's step 5 (2026-09-30). Since version 2's
C half (2026-10-02) it writes version 2 by default ("Version 2", below
in this section) and version 1 with `--format-version 1`, byte for byte
what it wrote before; everything up to "Version 2" here is the version-1
manual, and holds for version 2 where that part does not say otherwise.
`make -C host all` builds it, from `host/tools/segrun.c`. `cft-orbits`
writes certificates of its own runs too ([ORBITS.md](ORBITS.md),
"Certified runs"), with the same encoding, `host/tools/cert_write.h`,
which both tools include (the steps-5-and-6 round, 2026-09-30). It holds
the hashes and the salt's commitment, and the identity lines from `mode`
to `device-tiles`. It also holds a run block's head from
`program-format` to `stream-c`, each segment line, each accuracy entry's
lines, `end` and the hash line, and a file's creation, new. Each tool
spells the rest itself: the magic line, `runs`, each `run` line,
`parameters` and each `parameter`, `segments`, `output` and `accuracy`.

    cft-segrun --out CERT --states DIR (--salt SALT | --open)
               [--format-version 1|2]
               [--device sw|<xclbin>|cft://host:port | --scratch-depth N]
               [--certificate-id ID] [--issuer ISSUER] [--issuer-key KEY]
               [--initial INITIAL] [--supersedes DIGEST]
               [--compiler-build BUILD]
               [--publish device-serial|host-os-version ...]
               --run main --image IMG [--bank BANK] --init INIT
                          --segments S --steps K [--param NAME=N ...]
                          [--lane-flags]
                          [--source SRC --manifest M [--compiler none]]
                          [--replay-image IMG [--replay-bank BANK]]
               [--run half-step --h-slots I,J,... --image IMG ...]
               [--run wider --image IMG ...]
               [--run wider-source --image IMG ...]
               [--entry drift|step-halving|wider|wider-source --uses R
                        --scope max-lanes|lane:I
                        [--quantity LABEL --term C[,sI...] ...]
                        --value exact|rounded:FMT:RND|enclosed:FMT] ...
    cft-segrun --hash state|stream-a|stream-b|stream-c FILE
               (--salt SALT | --open)
    cft-segrun --hash commitment --salt SALT
    cft-segrun --build-id

The options from `--certificate-id` to `--publish`, a run's from
`--lane-flags` to `--replay-bank`, and a `wider-source` run are version
2's: beside `--format-version 1` each is refused `usage`, naming it. A
`wider-source` entry there is `malformed`, version 1's methods being the
other three.

**What it runs.**
- Each `--run` opens a run block, and the options after it are that
  run's. Run 0 is `main`. A later run is `half-step`, the same image on
  a bank whose named h-slots are halved, for twice the segments, or
  `wider`, the image one format wider.
- A run is an image, its bank when the image takes one (`BANK_EXT`), an
  initial state and a segment count. Each segment is one
  `cft_program_run_ex` over every lane, with no index table and no lane
  mask, entered with the last segment's scratch-out.
- The streams a, b and c are +0. The tool takes none, and each stream
  line is the hash of the +0 stream it ran.
- `--init` is a state as "Hashes" defines one: the lane-major scratch
  block, the block `positive-run --scratch-in` takes. Its size fixes the
  run's lanes.
- `--salt` names a file of exactly 32 random bytes and makes the
  certificate keyed. `--open` makes it open.
- `steps` and each `--param` are stated, not checked. Parameters are
  written in the order given, and must already be in byte order.
- `--scratch-depth N` opens the software backend at N scratch slots a
  lane through `cft_open_ex`, as positive-run's option does, so that it
  computes what a tile of that depth must: a non-strict STX or LDX
  reduces its index modulo the depth.
  - Every run block then states `parameter scratch-depth N`, in its
    place in byte order among the run's parameters. That is the
    parameter the audit reads as the run's depth (see "The chain").
  - It is written only when the option is given, so every certificate
    made without it is byte for byte what it was before the option
    existed.
  - The identity lines do not change: the software backend's device
    lines stay `none`, and the depth is stated in the run blocks
    instead.
  - N is a power of two from 1 to 32,768, the range `cft_open_ex` takes
    and the reader holds the parameter to.
- `--hash` prints one of the hashes above for a file's bytes, and
  `--build-id` the library's `cft_build_id()`. The gate holds the first
  to the test vectors above.

**Its accuracy entries** (the plan's step 5, 2026-09-30). Each `--entry`
comes after the runs and opens one entry of the accuracy block, in the
order given. The options after it are that entry's:
- `--entry` names the method: `drift`, `step-halving` or `wider`. The
  kind is the method's (`measurement`, or `estimate`), so it takes no
  option.
- `--uses R` is the run the entry is a function of.
- `--scope max-lanes`, or `--scope lane:I`.
- A drift names its quantity, `--quantity LABEL`, and gives its terms,
  one `--term` each, in the order they are summed. A term is the
  certificate's `term` line with commas for its spaces: the coefficient
  in the page's one spelling (hex, lowest terms, `1/1` for one), then its
  factors, `s<slot>` each, non-decreasing. A constant term is its
  coefficient alone. An estimate takes neither option.
- `--value exact`, `--value rounded:FMT:RND` or `--value enclosed:FMT`,
  with FMT one of fp32 to fp256 and RND one of `rne`, `rtz`, `rdn`, `rup`
  and `rmm`.

The page's example certificate is made with these two:

    --entry drift --uses 0 --scope lane:1 --quantity energy
            --term 1/2,s2,s2 --term 1/2,s3,s3 --term 1/2,s0,s0
            --term 1/2,s1,s1 --term 1/1,s0,s0,s1 --term -1/3,s1,s1,s1
            --value exact
    --entry step-halving --uses 1 --scope max-lanes --value rounded:fp64:rup

How each value is made:
- It is computed as "The functions, exactly" says, in its order, with
  every value held to the width rule.
- The states come from the files the runs wrote to DIR. They are read
  back once every run has run, one entry's two states at a time: a
  drift's run at boundary 0 and then at S, an estimate's run 0 and then
  its run, each at its last boundary. Each state is read into a buffer of
  its own size and held to the hash the certificate carries at that
  boundary. A file that is not that state is refused `output`: another
  process changed DIR.
- Every value is computed first, and then every value is put in its
  form. That is the golden writer's order: `cert.derive` for each entry,
  then `make_value` and `encode`'s reader.
- A rounded or enclosed value is rounded and spelt through a software
  handle of its own, as cft-audit's are, whatever `--device` ran the
  segments.
- With no `--entry`, the block is `accuracy 0`, byte for byte what the
  tool wrote before step 5.
- The arithmetic is cft-audit's own. Step 5 moved it into one file that
  both tools build, `host/tools/cert_exact.h`. It is header-only, and
  nothing in it prints or exits. Each of its functions that can fail
  returns a status. A status that names a refusal, each tool refuses by
  that name. An exact step past the bigint, which the width rule makes
  impossible, is an internal error in both tools, and a library call
  that fails is this tool's `device` and cft-audit's internal error.

**The states.** Each boundary is written as it is reached, to

    DIR/run-<r>-boundary-<b>.bin

where r is the run and b the boundary, 0 the initial state and S the
output, both in decimal as the certificate numbers them. Each file is
the state's bytes, lane-major, the bytes its hash covers. The run
creates DIR, which must not exist before it, so two runs' states never
share a directory, and creates each file in it new. It creates the
certificate new as well, as a regular file, and before DIR: an `--out`
that is there already is refused, never overwritten, and an `--out`
inside DIR cannot be created at all, so the certificate is never one of
the boundary files. An auditor is handed the directory with the
certificate, the images and banks, and a keyed certificate's salt. The
golden audit takes the files as `states={r: {b: bytes}}`.

**Identity, from the library and nowhere else.**
- `build-id` is `cft_build_id()` of the library linked into the binary,
  verbatim. `cft-segrun --build-id` prints the same string.
- `backend` is `cft_caps.backend`: `software`, `xrt` or `remote`. Any
  other answer is written `unknown`.
- `device-xclbin`, `device-version` and `device-caps` are what
  `cft_get_image_id` reports: the SHA-256 of the xclbin loaded, VERSION,
  and CAPS alone or CAPS then CAPS2. Where it refuses:
  - on the software backend all three are `none`;
  - on an XRT image whose tiles disagree, all three are `unknown`;
  - through a remote handle the tool follows "Identity": the server's
    device fields where the protocol carries them. Its HELLO carries
    VERSION as `cft_caps.device_version`, which is written where it is
    not 0. A software server's is 0, which names no register map, so it
    is written `unknown`. The protocol carries no xclbin digest and no
    raw CAPS word, so those two lines are `unknown`.
- `device-tiles` is `cft_caps.tiles`, the server's through a remote
  handle, and `unknown` for 0.

**Refusals.** Before anything runs, the tool refuses a defective input by
the page's name and code for it, the name the golden writer
(`cert.run_chain`, `certify_run`, `encode`) gives the same defect:
- `salt-length`, for a salt that is not 32 bytes;
- `program-image`, for an image whose header does not describe its
  bytes, a bank that is not the size the image addresses (or any bank
  for an image that carries its constants), or an image the library's
  loader refuses;
- `program-shape`, for a program that is not a segment;
- `state-shape`, for an initial state that is not a whole number of
  lanes, at least one;
- `malformed`, for a count or index out of its spelling or range, a
  half-step run with no h-slots, run 0 not `main` or a later run that
  is, and no run at all;
- `line-unexpected` and `line-order`, for a parameter named twice, or
  out of byte order.

An accuracy entry is refused by the names the golden writer gives the
same defect (`cert.derive`, `make_value`, and `encode`'s reader). Before
anything is made, each entry in turn is checked for its spellings, then
against the runs in `cert.derive`'s order:
- `malformed`, for:
  - a method, a label, a run, a lane or a slot not in its spelling. A
    run, a lane or a slot given negative, a minus before a nonzero
    index in its one spelling, such as -1, is spelt: it names none, and
    it is `accuracy-run`, `accuracy-scope` or `accuracy-slot`, below,
    as `cert.derive` names it. `-0` and `-01` spell no index, and are
    `malformed`;
  - a drift with no `--quantity`, no `--term`, or more than 64;
  - an estimate given a `--quantity` or a `--term`;
  - a coefficient not in its one spelling: a zero denominator, 0/3, or
    not in lowest terms;
  - a factor not `s<slot>`, more than eight of them, or out of order,
    by the slots' values (-1 before 0);
  - a `--value` that is not `exact`, `rounded:FMT:RND` or
    `enclosed:FMT`, in the page's words;
- `width`, for a coefficient past the width rule by its digits;
- `accuracy-run`, for a run that does not exist (an index past the
  runs, or a negative one), and for an estimate on run 0, on a run of
  the other kind, or on a run whose lanes or slots a lane are not run
  0's;
- `accuracy-scope`, for a lane the run does not have (an index past its
  lanes, or a negative one);
- `accuracy-slot`, for a slot the run's state does not have (so every
  slot from 65,536, and every negative one).

After the runs, from the states read back:
- `accuracy-finite`, for an element a value needs that is not finite;
- `width`, for a value computed past the rule (an element's exact value,
  a product, a partial sum or a difference, in the page's order), and
  for an enclosure's finite end past it, the lower end first.

For one defect, the name is the golden writer's. Where one command line
has two, the tool names the first in its own order, which can differ
from the golden writer's: the golden writer checks the runs in `derive`
and the spellings at `encode`, and has no "before anything is made".
The same is true of a run's checks, which name a run's parameter
before a later run's image. For a spelling the golden writer cannot be
handed, such as a coefficient 2/4 (a `Fraction` is in lowest terms), it
has no name, and the tool uses the reader's, `malformed`.

For two of these the golden writer has no name. An image that does not
load, and an empty initial state, each make it raise
`seq.ProgramError`, and the tool uses the table's `program-image` and
`state-shape`. At a segment, a flag word the library reports past the
five sticky flags, which no reader could read, is `malformed`, as the
golden writer's `encode` refuses it.

A writer needs more names, which the golden writer, an API rather than
a command, never meets. They are the tool's, in sysexits' codes, of
which 64 is already the auditor's usage:
- `usage`, exit 64: a command line the tool does not take, or a file it
  names that cannot be read. Among them are an entry's options out of
  place (before any `--entry`, or a run's after one, or a `--run` after
  one), given twice in one entry, or an entry without `--uses`,
  `--scope` or `--value`. Also refused before anything is made is a
  `--scratch-depth`:
  - beside a `--device` other than `sw`: a device's depth is its image's,
    and `cft_open_ex` refuses the two together too;
  - not a power of two from 1 to 32,768, or not in its one decimal
    spelling;
  - given twice.
  A `--param scratch-depth=...` is refused `usage` too: that parameter is
  written by the option alone, from the depth the backend was opened at;
- `device`, exit 69: the device does not open; it cannot read the
  sticky flags a certificate records (`cft_caps.flags_readable` 0); a
  digest, or a segment's run, fails; the library leaves a segment's
  flag word unwritten; or the software handle an accuracy value is
  rounded and spelt through does not open, or one of its conversions
  fails;
- `memory`, exit 71: what the runs need in memory cannot be had, found
  before anything is made (**Memory**, below), or another of the tool's
  own allocations fails. The library's allocations are not the tool's:
  a library out of memory is refused as what failed, `program-image`
  (the load) or `device` (a segment's run), and a stdio buffer that
  cannot be had as `usage` (reading) or `output` (writing);
- `output`, exit 73: `--out` is there already, is not a regular file
  (Windows' `NUL`), or lies inside DIR, where it cannot be created
  because DIR does not exist yet; DIR is there already; the certificate
  or a state file cannot be created or written; or a boundary file read
  back for an entry is not the state this run wrote there (its size or
  its hash) or cannot be read, because another process changed DIR;
- `build-width`, exit 78, cft-audit's name: a build whose bigint is
  narrower than 2,047 bits, given an `--entry`. Such a build has no
  exact arithmetic, so it refuses rather than write a value differently.
  It comes after the runs' checks and before anything is made;
- `build-format`, exit 78, cft-audit's name too: a value rounded or
  enclosed in a format above the build's `CFT_MAX_FORMAT`. It is found
  at the format's word, since the value's decimals and its rounding are
  the library's. A run in such a format stays what it was, the loader's
  `program-image`.

An exact step past the bigint, which the width rule makes impossible, is
not a refusal. It prints `cft-segrun: internal error` and exits 70, as
cft-audit's does.

Every refusal prints `cft-segrun: refused <name>: <why>` and exits with
the name's code. None writes a certificate, and none removes or changes
a file the tool did not create. One made before the first segment
leaves nothing behind. A run that fails part way, and an entry refused
after the runs, leave the boundary files written, and say so. A `device` or `program-image` refusal
adds the library's sentence (`cft_last_error()`), unless it is the one
`cft_get_image_id` left before the runs: a sentence can outlive its
call, and at eb2d1ae a segment's out-of-memory carried that one
(verifier-C7). No backend in this tree reports
flags it cannot read, leaves a flag word unwritten or reports one past
31, so `CFT_SEGRUN_PLANT` is an instrument for the tests of those three
refusals: `flags-unreadable`, `flags-unwritten` or `flags-wide`. Each
makes a run refuse by that name, and says so. With `--build-id` or
`--hash`, which run nothing, it only prints that the run is to be
refused and exits 0 with the right output (verifier-C6). A fourth,
`trial-skipped`, refuses nothing: it skips the trial's allocations
(**Memory**, below), keeping its size checks, so that the gate can
measure what the trial costs the runs. A fifth, `wider-routine` (parcel
C4, 2026-10-02), turns a refusal into a certificate: a wider run of a
routine image, which every writer refuses `aux-image` ("Auxiliary runs"),
is written as stated, so that an audit has one to refuse. The read-back
refusal has a
plant BUILD instead of an instrument (the lead's condition, 2026-09-30).
Compiled with `-DCFT_SEGRUN_PLANT_STATE_CHANGED`, by the gate and never
by the Makefile, the first state read back has a bit flipped, and the
run is refused `output` by the state's hash. The tool `make` builds has
no such path, and the gate holds its binary to none of the plant
build's words. The refusals
only a failing library, device or filesystem, or another process, can
reach have no test in the gate:
- `cft_get_caps`, `cft_program_get_info`, `cft_program_digest`,
  `cft_sha256` or a segment's `cft_program_run_ex` returning an error;
- the library reading an image's header differently from the tool, or
  `cft_build_id()` answering outside its grammar;
- once the run has begun, a state file that cannot be opened, written or
  closed, a certificate that cannot be written or closed (it is opened
  before the run, and that refusal has a test), or a line that cannot be
  formatted;
- a boundary file already in DIR when the run comes to write it
  (`output`, as a file the run did not make);
- a boundary file changed, or gone, between its writing and an entry's
  reading it back (`output`). The plant build holds the hash check
  alone: a file of another size, or one that cannot be read, has no
  test here (verifier-W1 planted both, and each was refused `output`,
  2026-09-30), and a race is held by nothing;
- the software handle for an accuracy value not opening, or one of its
  conversions failing (`device`).
Two of these do happen on the desktop when another process makes them,
and verifier-C7 made both, there and in WSL (2026-09-28): a loopback
server killed part way through a run made a segment's run fail, refused
`device` with the boundary files written so far left and said so; and
a thread that wrote a boundary file into DIR ahead of the run had it
refused `output`, the thread's file kept byte for byte. Each is a race,
so the gate holds neither. Every other condition the lists above name
has a test, and so does every refusal name; not every branch of `usage`
or of `memory` has one.

**Memory.** The runs allocate as 99f1b43's tool did, and never hold
more at once. A run takes its boundary hashes, flag words and STATUS
when it starts, and keeps them for the certificate. It takes its two
states and its +0 streams, and lets them go when it ends, so no run
holds another's. A hash's buffer and a boundary file's path are held
only while each is used, and the certificate's text is grown after the
last run. They hold a little less than 99f1b43's did: each image is let
go once the library has loaded and digested it, and each initial state
once it is copied into its run's first state.

The accuracy entries come after the last run has let its states go.
Each reads its two states back into buffers of their exact size, and
lets both go before the next entry reads its own. The pair is one run's
(a drift), or run 0's final state beside a run of run 0's lanes and
slots (an estimate: other shapes are refused before anything is made).
So, by arithmetic, the entries hold no more at once than the largest
run did, which was its two states, its streams and a hash's copy. The
gate measures what they cost in two shapes (**Its gate**, below):
- Beside flagstep's three runs of 65,535 lanes, whose states are 1 MiB,
  with two entries that read four states back. In four runs of the gate
  the peak commit was 12 KiB less, 12 KiB less, 28 KiB more and 40 KiB
  more than the same three runs without entries (10,224 to 10,284 KiB).
  One more state held beside the runs' would be 1,024 KiB more. So the
  entries hold no state beside the runs'. This shape sees nothing else:
  the entries' own phase is more than two states under run 0's peak,
  which holds the later runs' initial states and the library's own lane
  block (its registers and its scratch, about 4.6 MiB at the default
  depth, whatever the lanes). An entry that held a third state, and
  entries that kept every pair, both passed it (verifier-W1's plants,
  2026-09-30).
- Beside `slotstep`'s one run of 65,535 lanes of 16 slots, whose states
  are 8 MiB, with two drifts of it that read four states back. There the
  entries' phase is the process's peak. The run holds its two states,
  its streams (a sixteenth of a state) and one state more at most (the
  initial state, or a hash's copy), and the entries hold a pair and a
  hash's copy. In six runs the peak commit was 476, 88 and 16 KiB less,
  and 16, 16 and 52 KiB more, than the run alone (26,300 to 26,780 KiB),
  and in verifier-W1b's, from other work paths, from 468 KiB less to 116
  KiB more. Against the gate as committed, W1's two plants were 7,696
  and 7,668 KiB more (the third state) and 15,912 and 15,848 KiB more
  (every pair kept), and the gate fails both. Its entries are drifts.
  An estimate needs a second run, and before the runs the trial holds
  every run's initial state beside the larger run's two states and
  streams: by arithmetic, that run's streams above an estimate's phase
  with ONE state more. So the trial hides an estimate holding one state
  more, in any shape; it does not hide a fault that builds up across
  estimates: two wider estimates that keep their pairs show +7,108 and
  +7,056 KiB as shipped (verifier-W1b). Measured: slotstep's main run beside its fp128
  wider run (16 MiB states) peaks at 59,244 KiB, and with a wider
  estimate 59,248; with the trial skipped (its instrument), 51,472 and
  51,496 (S1, 2026-09-30). A fault in an estimate's read-back alone
  passes both shapes (verifier-W1b's plant): the read-back is one code
  for every method, and the gate holds it on drifts.

Those are the desktop's peak commit (2026-09-30). In WSL (cft2204), the
least address space was 0 KiB more with the entries in both shapes, and
the two plants 7,616 and 15,808 KiB more (S1's send-back, 2026-09-30).
Each entry's definition is held from the command line to the end: a
rational of about 520 bytes a term at the default bigint, about 36 KiB
for a drift of 64 terms. Its value is held too, about 520 bytes. None of
it grows with lanes or segments.

Before the certificate or DIR is created, the tool counts what the runs
need against what the process can address. It then tries, in the runs'
own order, the pieces their sizes decide: each run's hashes, flag words
and STATUS, kept; its two states and streams, taken and let go; then
each entry's two states, taken and let go; and last the certificate's
text, at the least it can be, its entries' lines among it. So a run the
process cannot have is refused with nothing made. `--segments
9223372036854775807` on run 1 is refused by its size, naming the run.
`--segments 1000000000000` is refused at its boundary hashes' (10^12 +
1) x 65 bytes on the Windows desktop, and at the certificate's text in
WSL.

The trial takes nothing from the C library's heap. Every piece comes
from the operating system, rounded down to whole pages, and a piece
under a page is not tried; the trial's own list of what it holds comes
from the operating system too. All of it is given back before the
outputs are made. So the runs allocate from the heap they would have
had without the trial, and the trial costs them nothing. At eb2d1ae it
did not: its pieces under 64 KiB came from `calloc` and left the heap
bigger, so the runs needed up to 40 KiB more than 99f1b43's in 24 of
96 small shapes, and 99f1b43 wrote certificates under limits eb2d1ae
refused (verifier-C7, 2026-09-29).

The trial holds no hash's buffer (a state's size) and no library,
device or program: at each run, less than 99f1b43's tool held there.
But it holds every run's initial state throughout, as 99f1b43's runs
did, where the runs now let each go once it is copied. So the trial can
need more than the runs themselves, and refuse a certificate they alone
could have written. In verifier-C7's `up` shape (a main run of 64 Ki
lanes, then half-step runs of 256 Ki and 1 Mi) the trial needs 10,444
KiB more than its runs in WSL (10,440 at eb2d1ae): the tool's least
`ulimit -v` there is 92,452 kB, and 82,008 kB with the trial skipped.
99f1b43 needs 108,832 kB, so it could not write that certificate
either: a known limit, not a regression.

Measured on verifier-C7's case (flagstep, 1,048,576 lanes, a main and
two half-step runs), the least `ulimit -v` it writes the certificate
under in WSL is 164,128 kB at 99f1b43, 250,744 kB at 4eed552, 147,744
kB at eb2d1ae and 147,748 kB now. Its peak commit on the desktop is
157,936 to 157,984 KiB at 99f1b43 and 141,504 to 141,572 KiB now. In
verifier-C7's sweep of 96 small shapes in WSL (flagstep; 1, 16 and 256
lanes; two or three runs; a main run of 10 to 500 segments and
half-step runs of twice that; open and keyed), the tool writes its
certificate, the same bytes, under the least `ulimit -v` 99f1b43 writes
it under, in all 96; eb2d1ae fails there in 24. On the desktop, under a
job's commit limit of 5,680 KiB, one of them (1 lane, a main run of
100 segments and a half-step run of 200; verifier-C7's case) is written
by 99f1b43
and by the tool, 3 times of 3, and by eb2d1ae 0 of 3; across 72 of the
shapes the tool's peak commit is 99f1b43's within the several pages
that separate identical runs there (2026-09-29).

What the trial cannot promise:
- a hash's buffer or a boundary file's path, or a piece under a page;
- the library's own memory;
- memory the machine gives others between the trial and the run.
Where the operating system has no anonymous mapping, the trial is its
size checks alone. A piece of the tool's that cannot be had after the
trial had it is refused `memory` part way, with the boundary files left
and said so.
So are the tool's other allocations: a file read, the command line's
lists, a hash's buffer, a boundary file's path, and the certificate's
text as it grows. None of these has a test in the gate, though none
needs the machine loaded to reach it: an address-space limit reaches
each, and verifier-C7 had an initial state's read refused `memory`
under `ulimit -v` in WSL. The gate holds the size check, the trial's
refusals, what a run costs and what the trial costs (below).

Where memory is overcommitted, an allocation the machine cannot back
still succeeds. Linux does so in both of its usual modes. Mode 1 (WSL
cft2204) refuses nothing that fits the address space, and mode 0, the
default and amd-arc-box's, refuses only a single allocation larger than
the machine's memory and swap (the kernel's rule; not measured on
amd-arc-box). There, a count whose allocations each pass is not refused
before it runs. In WSL, 2 x 10^11 segments run: verifier-C7 ran them at
4eed552, and they ran again at P3b's send-back, 7,087 boundary files in
the first second before they were stopped. Such a run touches about 73
bytes of memory a segment and writes a file of at least one disk block
a boundary, and the certificate is written only at the end. So on
cft2204, with 66 million free inodes, the files would run out first,
after about 66 million segments with about 4.9 GB touched. The run
would then be refused `output` part way, by name, its boundary files
left and said so. That is arithmetic, not a run.

**Known limits.** On Windows, `--out name:stream` writes the
certificate into a new NTFS stream of an existing file or directory
`name`: the file's data, or the directory's entries, are kept, and its
time changes (verifier-C7). `--out name\` makes a plain file `name`.
Both are names the user gave, and neither changes a file's data. A run
killed by a signal leaves the certificate it created, empty, and its
boundary files, since a signal runs no cleanup; at 99f1b43 the same
kill truncated a file already at `--out`. The trial holds every run's
initial state, and can refuse a certificate the runs alone could write
(**Memory**, above). On Windows a narrow `main` is handed its command
line through the system's code page, which maps a character it lacks to
a near one ("best fit") before the tool reads it: a U+2212 MINUS SIGN,
U+FF0D FULLWIDTH HYPHEN-MINUS or U+2010 HYPHEN before 1 arrives as
`-1`, and is refused as -1 is, and U+FF11 FULLWIDTH DIGIT ONE arrives as
`1` and is taken as 1 (verifier-W1b on `--uses`, and S1 on a lane and a
slot, 2026-09-30). So a spelling outside ASCII can be read as an ASCII
one there. cft-segrun no longer meets it: since 2026-10-03 it reads the
wide command line (*The process's own text*, under **Version 2** below),
at both versions, so each such spelling is its own characters - U+FF11
is not a decimal, and `--segments` given it is `malformed` (section 14,
leg i). Every other tool in this tree still takes Windows' conversion,
before `main`, for every option: a known limit there, not fixed. How a
UCRT or MSVC build's C runtime splits a doubled quote inside quotes is not
determined here (no such toolchain): msvcrt, this tree's, splits the 28
classic quoting forms as `CommandLineToArgvW` does (verifier-VCV2CW,
2026-10-03), and a runtime that splits one otherwise is refused `usage`
where the line's ANSI form is exact, and read by `CommandLineToArgvW`'s
rules where it is not. Nor is how the runtime reads a double-byte code
page's trail byte 0x5C, a backslash's byte (this desktop's code page is
cp1252).

**What it certifies, and what it does not.** It certifies what ran:
which states each segment started and ended on, as hashes, with its
flag word and STATUS as the library reported them, on the library build
and device the library names. It certifies each accuracy entry's value
as the stated function of the states it certifies, and says nothing
more of an estimate than the page does: that an estimate estimates well
is not shown. It does not check an auxiliary run's relation to the main
run. A half-step bank that is not the main bank halved, or a half-step
run entered from a state other than the main run's, is written as
stated, an estimate against it computed as stated, and the audit
refuses it (`aux-bank`, `aux-start`). It signs nothing.

**Version 2** (parcel CV2CW, 2026-10-02; "Version 2", below, is its
contract, and the golden writer, `cert2.py`, its authority). Without
`--format-version 1` the tool writes version 2: version 1's lines, chain
and accuracy entries as above, and these.

*The header.* Each line comes from where the contract says, and the
tool's choice is named where it had one:
- `profile` and `language` are the library's definition, cft.h's
  `CFT_PROFILE_*` and `CFT_LANGUAGE_*`, spelt as a version is (`2`,
  `1.1`); `language none` where no run names a source.
- The four device lines are `cft_image_id`'s at ABI 0.18
  ([HOSTAPI.md](HOSTAPI.md)): `none` on the software backend; `unknown`
  through a remote handle, on an XRT image the library cannot name, and
  wherever the library knows no value; on a card, the platform's name,
  the XRT version the library was built against, the kernel clock the
  image's own BUILD_METADATA states and the card's serial, each spelt as
  a text. A value the card reports that no text can spell is written
  `unknown`, not refused (the tool's choice). `device-serial` is
  `withheld` where the library knows a serial, unless `--publish
  device-serial`.
- `writer cft-segrun <build-id>` (`cft_build_id()`, or `unknown`) and
  `writer-runtime none`. `compiler-build` is `--compiler-build`'s (a
  build in build-id's grammar, or `unknown`), else `unknown` where a run
  names a compiler and `none` where none does; the option is `usage` where
  no run names a compiler, and so is `none` where one does.
- `replay-methods`, and `replay-method <r> image <digest>` for each run
  with replay lines: the replay image's SHA-256. Its bank, where it takes
  one (`--replay-bank`), is not named on that line, which has no place for
  it: a known limit, the lead's decision (2026-10-02). The method is
  reported and never checked - the audit holds a replayed value to the
  definition, not to the replay image - and the bank is determined all the
  same: it is the compile of the run's named source by its named compiler
  and target.
- The header's statements, each the option of its line's name, each
  taking the line's own value as the certificate spells it: a word the
  line takes, or a text in its one spelling, percent-encoded. So
  signed-fp64's certificate-id - "cert 0001 / ", then U+0141, U+00F3, d
  and U+017A - is `--certificate-id
  cert%200001%20/%20%C5%81%C3%B3d%C5%BA`: the encoded spelling reaches the
  tool whole through whatever makes its command line, a shell, a script or
  a console whose code page cannot carry U+0141 among them (the lead's
  decision, 2026-10-02). A statement given as its characters is
  `malformed`: U+0141, o, d, U+017A is never read as Lodz, which is what
  Windows' ANSI code page makes of it by best fit. `--certificate-id`
  (`none` by default), `--issuer`
  (`withheld` by default; `none`, or a text), `--issuer-key` (`none`, or
  64 lowercase hex digits; a key that encodes no point is `malformed` and
  one of small order `signer`, as the golden writer's read-back names
  them), `--supersedes` (`none`, or the superseded certificate's body
  hash, its hash line's 64 digits) and `--initial` (`given`, or the line's
  tokens in one argument: `--initial "generator shake-box <tag> <lo>
  <hi> ..."`, at most sixteen arguments). The generator is reported: the
  tool does not regenerate the state it is handed.
- `host-os` and `host-arch`, measured as the golden writer's `host_os` and
  `host_arch` measure them: `windows`, `linux`, or another system's own
  name in lower case, with its version only on `--publish
  host-os-version` (`windows-<major>.<minor>.<build>`, the kernel's
  release on Linux, the system's version elsewhere); `x86_64` for amd64 and
  x86_64, `aarch64` for arm64 and aarch64, any other machine by its own
  name in lower case - uname's, and on Windows the native architecture
  `GetNativeSystemInfo` reports, named as Python's `platform.machine`
  names it there (`x86`, `mips`, `alpha`, `powerpc`, `arm`, `ia64`), one
  that Python's table has no name for `unknown`. A measurement that fails
  is `unknown`.
- `started` before the first segment, `finished` after the last, `issued`
  as the certificate is written, each in UTC and `unknown` where the
  clock does not answer. A clock that went back while the tool ran, which
  would break their order, is refused `provenance-order`.
- `environment` and an `env` line for each variable of the writer's list
  that is set non-empty, in the list's order: segrun.c's table, held equal
  to `cert2.ENVIRONMENT_NAMES` by the gate. Each value is the process's
  own text (below): on Windows `GetEnvironmentVariableW`'s, in UTF-8, not
  the ANSI code page's that `getenv` answers. A value no text can spell -
  one of the four words, more than 255 characters encoded, not UTF-8, or
  on Windows an unpaired surrogate - is refused `malformed` before
  anything is made, as the golden writer's text rule refuses it.

*The process's own text* (verifier-VCV2CW, 2026-10-03). The values the
tool reads are recorded as the process has them, as the golden writer's
are (Python's `os.environ` and `Path`). Windows hands a C program's `main`
its arguments, and `getenv` its values, in the ANSI code page, which spells
U+0141 as L by best fit and U+00E9 and U+20AC as bytes that are not
UTF-8; so on Windows the tool reads the wide command line, split by
`CommandLineToArgvW`, each argument in UTF-8, at both versions, and opens
every path through its wide form (`_wfopen`, `_wopen`, `_wmkdir`,
`_wrmdir`, `_wremove`). The Unicode split decides. The C runtime's argv is
its own split of the line's ANSI form, which best fit makes, and on cp1252
best fit spells U+3000, U+2002, U+2003 and U+2009 as a space, U+FF02,
U+2033 and U+02BA as a quote and U+FF3C as a backslash, so that split can
be of another string (verifier-VCV2CW, 2026-10-03). Only where the line's
ANSI form is exact - every character in the system code page as itself -
are the two held to each other, the count and each argument that is ASCII
as Unicode, and a C runtime that splits a quoting form otherwise is then
refused `usage` rather than guessed at. A source's file name, and every
path the tool is handed, may then hold any character that has a UTF-8
spelling, best fit's spaces and quotes among them, and `source-name`
spells the file's own; an argument with no UTF-8 spelling (an unpaired
surrogate, which only Windows can hand a program) is `usage`. Version 1's
bytes are unchanged for every command line both read alike. Elsewhere the
bytes the process holds are its text, handed on as they are.

*A run.* `--lane-flags` asks for the per-lane block (ABI 0.17), which the
run also asks for wherever its image holds QUIET, ENDQUIET or RAISE. Its
segment lines end in `lanes <h>`, and each segment's certified block is
written beside the boundaries as `run-<r>-segment-<k>.flags`.

`--source SRC --manifest M` names the run's source: the tool has no
interpreter of the language, so the graph's digest and the source params
come from M, the manifest cftc wrote beside the image, and are held to the
files the run runs, in this order: SRC's SHA-256 is the manifest's source
(`source-digest`, also for a manifest that names none); the manifest's
format is the run's, its graph being the step graph at the run's format
(`source-graph`); a main or half-step run's manifest names no format
override (`source-format`); its lane, scratch.in, is the image's slots a
lane (`source-shape`); and, the run being compiled from the source, the
image is the manifest's, and but for a half-step run's, whose bank is its
relation's, the bank too (`source-image`). `--compiler none` says the
image is not the source's compile, which defines it (`compiler none`):
then neither is held to the manifest. The source's name is SRC's file
name, without directories, as the system's path rules part it (on Windows
after the last `/` or `\` and past a drive's `X:`, elsewhere after the
last `/`, as `Path.name` parts it); the compiler line is the manifest's name,
output version and target. The source params are the manifest's
param_overrides, names in byte order, each value spelt as the language's
canonical literal by a port of `lang.constants.literal` on the library's
bigint; a value past it is the tool's own limit, `build-width`. A manifest
the tool cannot read - not JSON, not cftc's version 1, a field missing, a
value not frac_text's spelling - is `usage`.

*A marked lane.* A segment whose block marks a lane is certified as the
definition's segment. With no source the run is refused `replay-source`,
and with one but no `--replay-image`, `replay-missing`: the tool replays
only by the contract's producer's shortcut, an image of the same source
that decides the lane, with its constants in `--replay-bank`. The marked
lanes run once on it, each from the segment's start, with their own
block; a lane it marks too is `replay-undecided` (exit 78). Each marked
lane's values and five IEEE flags are the replay's, its [6:5] the raw
byte's; the flag word is the corrected bytes' OR and STATUS loses STATUS[6].
The raw end state and raw block are hashed for the replay line and
written beside the boundaries as `-raw.bin` and `-raw.flags`. A
`--replay-image` on a run that names no source is `replay-source` before
anything runs ("a writer asked to replay with no definition"). The replay
image is held to its own header: `program-image` (it does not load, or its
bank is not the size it addresses), `program-format` (another format
than the run's), `program-shape` and `source-shape` (another lane).

*Wider-source.* `--run wider-source` is the main run's source compiled one
rung up; the tool checks none of its relation, as it checks no auxiliary
run's, and `--entry wider-source` is its estimate. C4's routine rule holds
in both versions: a `wider` run beside a routine main image is
`aux-image`.

*Refused at a segment,* with the files written so far left and said so:
`replay-source`, `replay-missing`, `replay-undecided`, and
`replay-lane-flags`, which only a library that reports a mark in a run
that asked for no block can reach. *After the runs,* as the header's times
are written: `provenance-order`, the files the runs wrote left and said
so. *Before anything is made*: every other version-2 refusal above, the
command line's among them. `provenance-order` and `replay-lane-flags` have
no test: only a clock that goes back, or a library that misreports,
reaches either.

*Memory.* The trial counts version 2's pieces too: each block's hash,
kept; the block, a replay's raw end, its marked lanes' start and end and
the two blocks, taken and let go; the longer text. A run's replay lines
grow as its segments mark lanes, refused `memory` part way where they
cannot.

*Known limits.* The XRT version is the one the library was built
against, which a library links to; the issuer-key's decoding is a check
of the tool's own until cft-audit's Ed25519 (the auditor's half) brings
one for the tree, and then calls it; the device lines are those of one
handle, as version 1's are. libcft reads its own variables of the list
(`CFT_TIMEOUT_MS`, `CFT_DIVSQRT_SEQ`, `CFT_DIVSQRT_FULL`,
`CFT_TRANSCEND_MINPREC`) through `getenv`, so on Windows a non-ASCII value
of one is recorded as the process has it and acted on by the library as
its best fit - numeric in practice (verifier-VCV2CW, 2026-10-03).

**Its gate** is `host/tests/segrun_check.py`, `make -C host segruntest`,
which `verify/run.sh`'s `programs` stage runs. It certifies
`lorenz63-rk4`, `lorenz96-rk4` and `henonheiles-lf` at fp64 and fp256,
each image held to `programs/MANIFEST`, with its classic bank:
- beside each, a half-step run, the bank slots named H, H2, H6 or MH
  exactly halved, for twice the segments;
- beside each fp64 one, a wider run: the same source assembled at fp128,
  with the bank and the initial state exactly widened;
- `flagstep`, a small program written in the gate, whose segments
  raise flags 20, 0, 1, 0 and 20 and STATUS 48, 48, 0, 48 and 48. Every
  ODE segment raises flags 16 and STATUS 0, so the ODE programs alone
  cannot tell a writer that drops STATUS, or writes one segment's flags
  against another, from one that does not;
- `markstep`, also written in the gate (2026-10-02), whose segments
  raise flags 6, 3, 2, 31 and 30 and STATUS 64, 64, 64, 0 and 0: each
  decrements an integer and raises it (revision 8's R24), so STATUS[6],
  the mark, comes from the software backend. Every certificate's segment
  lines must carry it. A writer, a backend or a protocol that kept only
  STATUS[5:4] - as the XRT backend's report mask did until that day -
  writes 0 there;
- and `lorenz63-rk4` at fp64 once more, its half-step run entered from
  an initial state of its own, unlike the main run's. Every other
  half-step run shares run 0's, so a writer that entered one from run
  0's `--init` would pass them all (verifier-C6's plant).

Each program is certified keyed and open on the software backend, and
each but the one whose half-step run starts apart (the audit refuses it
before step 10) with accuracy entries (since the plan's step 5,
2026-09-30):
- Between them the entries have every method, both scopes, every form
  and every rounding direction:
  - a step-halving estimate on each ODE program;
  - a wider one on each fp64 program;
  - Henon-Heiles' energy drift, exact, whose denominator has a 3, at
    fp64 on lane 1 and at fp256 over the lanes, near the width rule;
  - flagstep's counter drift over the lanes. Every lane's drift is -5,
    so a writer that took the signed maximum writes -5.
- A difference of two values of one format is exact in it when they
  have one sign and each is within a factor of two of the other
  (Sterbenz's lemma). The gate's step-halving runs end that close: all
  210 pairs of final elements, run 0's beside its half-step run's, meet
  the condition and differ exactly (2026-09-30; verifier-W1 counted the
  exact differences first). So a step-halving estimate's value is exact
  in its runs' format, where no rounding shows its direction, and the
  rounded and enclosed ones that are to show it name a narrower format.
  The gate holds that each direction but `rup` rounds some entry's value
  to other bits than `rup` does, so that a writer that swapped its
  direction is seen.

Then:
- the golden reader must accept each certificate;
- the golden writer, handed its identity lines, the salt, the initial
  states and the same entries' definitions, runs every segment itself
  and must write the same bytes, every entry's value among them;
- every boundary file must be the golden chain's state;
- the golden audit must accept each, in full and sampled, from the
  states the tool wrote, every entry re-derived, except the one whose
  half-step run starts from its own state, which it must refuse
  `aux-start`, in full and sampled;
- cft-audit, handed the same files, must give the golden audit's
  verdict in full, line for line (each entry's re-derived value among
  them), or its refusal by name, so that both auditors accept each
  certificate;
- the build-id line must be what the binary prints and what the tree
  builds, and the software backend's device lines `none`.

It also holds the test vectors, and each tag keyed and open against an
HMAC written from RFC 2104 in the gate. It holds every refusal above
that an input or the instrument can cause, by its name and code, and
the golden writer's name for the same defect where it has one. Each
refusal whose command line has an `--out` of its own is made again with
a file already there, which must come through byte for byte. It
certifies `lorenz63-rk4` at fp64, `flagstep` and `markstep` through a
loopback cft-serve, stopped by its PID. Their device lines must be the
remote rule's, and their run blocks byte for byte the software
backend's, flagstep's and markstep's flag words and STATUS among them.

It holds `--scratch-depth` on the software backend (the golden-certificate
round, 2026-09-29):
- **deepstep**, written in the gate, reads index 256 through a
  non-strict LDX. That is its own slot 0 at 256 slots, and at 2,048 a
  slot nothing wrote. Certified at 256 (open) and at 2,048 (open and
  keyed), each certificate:
  - states `parameter scratch-depth N` between the run's own `alpha`
    and `zeta`, in byte order;
  - is byte for byte the golden writer's at that depth;
  - has every boundary file the golden chain's;
  - is accepted by the golden audit in full and sampled, re-run at the
    depth it states.
- The two depths end on other states, so the leg holds 256 against
  every deeper depth, not only the line. It does not tell 2,048 from
  any other depth of 512 or more: the program writes slots 0 and 1 only
  and reads slot 256, which nothing writes at any depth from 512 up, so
  each computes the same chain. A tool that runs at 4,096 while stating
  2,048 passes it (verifier-A2's plant T3), a known limit of this leg.
  The golden corpus's deepwrap-fp64-2048 fails that tool, since its
  chain is 2,048's alone ("Golden certificates"; since 2026-09-30).
- lorenz63-rk4's main, half-step and wider runs at 2,048 state the
  depth in every run block, and audit green.
- Its refusals are among the others:
  - beside an xclbin and beside a `cft://` device;
  - 0, 3, 65,536, `02048`, `2048x` and `-2048`;
  - the option twice, and beside `--hash` or `--build-id`;
  - a `--param scratch-depth=`.
- The range's two ends are taken, each refused only by the library's
  loader, at the depth it opened, for a program that cannot load there:
  flagstep's two slots at a depth of 1, and at 32,768 an image the loader
  refuses, so that nothing runs at 32,768. A scratch run's lane block is
  545 MB there (cft.h).

It holds the accuracy entries' refusals (2026-09-30). Each is held by
its name and code, and by the golden writer refusing the same defect by
the same name wherever it has one. The golden writer has no name for a
spelling it cannot be handed, such as a coefficient 2/4.
- The command line's own: an entry option before any `--entry`, a
  `--run` or a run's option after one, an option twice, and a missing
  `--uses`, `--scope` or `--value`.
- Every spelling (`malformed`), and a coefficient past the rule by its
  digits (`width`). Among them `-0` and `-01` as a run, a lane and a
  slot.
- The entry against the runs:
  - `accuracy-run`: a run that is not there, a run index past 2^63 - 1,
    a negative one (-1, a drift's -5, and -10^20), step-halving on run 0
    or on the wider run, wider on the half-step run, and an estimate
    whose half-step run has other lanes;
  - `accuracy-scope`: lane 3 of 3, a lane past 2^63 - 1, and a negative
    one: -1, -4 of 3 lanes, and -1 where the last lane holds +inf, which
    is `accuracy-scope` and not `accuracy-finite`;
  - `accuracy-slot`: slot 3 of 3, slot 70,000, and a negative one: -1,
    -10 of a state of 9 elements, -1 before 0 in one term, and -1 on
    lane 0 where the state's last element is +inf.
  Until verifier-W1 and W1b found them (2026-09-30), a negative run,
  lane or slot was refused `malformed`, and the golden writer read a
  negative lane or slot by Python's index from the end.
- Each of these leaves nothing behind.
- After the runs, `accuracy-finite` (a NaN reached from +inf) and
  `width` (an element of 2^1023, a product x^2 with x = 2^-600, a
  partial sum, an enclosure's end). Each leaves the boundary files,
  every run having run, and says so.
- The page's orders, each with its control:
  - 1/a, 1/b, -1/b is refused `width`, and 1/b, -1/b, 1/a is written,
    byte for byte the golden writer's;
  - a final +inf beside an initial fp64 largest finite, a 1,024-bit
    value, is `accuracy-finite`, not `width`;
  - 1/(3 x 2^900) enclosed in fp256 is refused at its lower end, and
    enclosed in fp64 it is written.

It builds what only it compiles, with `--cc` and `--lib-src` as the
audit tool's gate has them:
- cft-segrun narrow, at `CFT_MAX_FORMAT=2`:
  - at its own 576-bit bigint, an entry is refused `build-width` with
    nothing made, and the same runs without entries are written as the
    default build writes them, but for `build-id` (a build compiled from
    the sources names none);
  - at `CFT_BN_LIMBS=64`, an exact entry and one rounded into fp128 are
    written as the default build writes them, and fp256 rounded or
    enclosed is refused `build-format`;
- the plant build, `-DCFT_SEGRUN_PLANT_STATE_CHANGED`: its entry's first
  state read back is refused `output` (exit 73) by its hash, with no
  certificate and the boundary files left. Without entries it writes the
  default build's certificate;
- and the shipped binary carries none of the plant build's words.

Last, it holds memory. What a run costs: flagstep on 65,535 lanes, a
main run and two half-step runs, against the main run alone. The two
further runs may cost their inputs and one state more, no more. At
4eed552, which held every run's working set at once, they cost two
whole working sets. What the accuracy entries cost, in two shapes
(**Memory**, above):
- the same three runs with two entries that read four states back,
  against the three runs alone. They may cost 256 KiB more, a quarter
  of one of those states (and on Linux one bisection step), and no
  more; holding one more state beside the runs' would cost 1,024 KiB.
  This holds no state beside the runs', and nothing of the entries' own
  phase, which is under run 0's peak there;
- `slotstep`, a program written in the gate, one run of 65,535 lanes of
  16 slots, with two drifts of it that read four states back, against
  the run alone. There the entries' phase is the peak. They may cost a
  quarter of its 8 MiB state, 2,048 KiB, more (and on Linux one
  bisection step): one command line's peak commit is steady, but
  between command lines it steps by about 470 KiB on the desktop, by
  the path and the entries given. Verifier-W1b measured the cause: the
  initial state's first read buffers, 64 to 512 KiB, in the C heap.
  With a first buffer of 1 MiB there is no step, and every command line
  sits at the upper level, so the lower one is a command line whose
  later allocations reuse those buffers' freed memory. The step is at
  most the buffers, 960 KiB. By arithmetic, an entry that held a state
  more than its pair would cost 7,680 KiB more, and entries that held
  two pairs at once 15,872 KiB more: two states less the streams the run
  holds and the entries do not (512 KiB), which also lets the entries'
  own phase grow by up to 2,560 KiB before the check fails (verifier-
  W1b: a quarter of a state held, 1,548 and 1,524 KiB more, passes).
  Its entries are drifts (**Memory**, above).

The gate measures a process as its platform does:
its peak commit on Windows, and on Linux the least address space it
writes its certificate in (`ulimit -v`), doubled from 16 MiB and then
bisected. And what the trial costs the runs, to the page: in two small
shapes, and in a third with two entries, the least address space with
the trial must be no more than with `trial-skipped` (eb2d1ae's trial,
planted back, costs them 20 KiB and 4 KiB). That is held on Linux, where the least address space of a
run is the same every time in one environment. The trial-skipped run
carries 30 more bytes of environment, which in a window of 32 bytes in
every 4,096 add a page to it alone; a leaked page is not seen there,
and a right tool is never failed (verifier-C7). On Windows, identical
runs' peak commit
differs by up to 16 KiB, more than a page, so there it is NOT TESTED,
by name (a SKIP line, which `verify/run.sh` counts as an inner skip).
The bisection sets only the soft limit, never past the hard limit the
gate's process has. A host whose hard limit stops a measurement says
NOT TESTED too, and the gate goes on (at eb2d1ae, run as `nobody` under
a hard limit of about 8 GB, it stopped with a traceback; verifier-C7).
It also holds git to ignoring the tool's binary.

Its section 14 (`host/tests/segrun_check_v2.py`, since version 2's C half)
holds version 2; every section before it asks for `--format-version 1`,
so version 1 is held as it was. It certifies flagstep with its blocks;
`replaystep`, written in the gate with its source, an image marking lane
1 in segment 0 (its value right) and lane 0 in segment 1 (its last bit
wrong), replayed by cftc's compile of the source; and Lorenz-63 compiled
with source params (rho 29, beta 2.625) beside a half-step and a
wider-source run and a wider-source estimate - each keyed and open; then
flagstep with every statement given and both privacy defaults published,
keyed; a run at `--scratch-depth 2048`, open; and `replaystep` again with
its source, and every path the tool is handed, named past any one code
page (U+0141, U+00E9, U+20AC, U+1D11E, spaces), open, its `source-name`
the golden writer's spelling of the file's own name. Each is byte for
byte the golden writer's
(`cert2.run_chain`, replaying by the definition, `certify_run`, and
`encode` handed the tool's header lines), every boundary, block and raw
file the golden chain's, and the golden audit accepts each, handed the
sources and blocks, in full and sampled. It holds the measured lines to
the golden writer's own functions on the host, the profile and language
to `profile.py` and `lang/version.py`, the environment to the list's
variables set and segrun.c's table to `cert2.ENVIRONMENT_NAMES`, the tool
handed none of the list but what a leg sets - removed from its
environment, not set empty, which XRT reads as an emulation mode to load
(the card leg on q135b failed so, the lead, 2026-10-03); one run's
two versions to the same state and stream hashes; 22 source-param
literals at every edge of the canonical spelling; the issuer-key to
test_ed25519.py's vectors (the published key and RFC 8032's taken, the
eight keys of small order `signer`, the six of no point `malformed`);
every version-2 refusal by name and code beside a control, with the golden
writer's twin where it has one; the process's own text (since 2026-10-03,
verifier-VCV2CW's finding): `CFT_XRT_BIND` set to U+0141, U+00E9 and a,
U+20AC, b, each `env` line the golden writer's, a value with no UTF-8
spelling in the platform's form `malformed` beside the golden writer's
twin, a statement given as its characters and `--segments` as U+FF11
FULLWIDTH DIGIT ONE each `malformed` (best fit spells them Lodz and 1),
an issuer a, U+3000, b `malformed` and replaystep with every path named
with the characters best fit spells as a space, a quote and a backslash,
each the golden writer's, and on Windows an argument with no UTF-8
spelling `usage` - the tool of 7ec2178, reading main's and getenv's ANSI
text, fails fourteen of those checks, and that of 45a8024, whose
cross-check compared the runtime's best-fit split, the two of best fit's
spaces and quotes (planted by running them, 2026-10-03); the remote rule
through a
loopback cft-serve; and,
on a card (`hw/card-segrun.sh`), the device lines from the tile, the serial
published as a text but never printed, and the per-lane block refused by
name on revision 7.

With the writer's list removed from the tool's environment, not set
empty (the card leg on q135b, 2026-10-03): 1,057 checks on the Windows
desktop and one SKIP, 102 s, the desktop about 8 % busy before it -
sections 1 to 13 716, section 14 341. Not yet run on a card.
With the Unicode split deciding (verifier-VCV2CW's second check,
2026-10-03): 1,055 checks on the Windows desktop and one SKIP, the trial's
cost NOT TESTED there, 88 s, the desktop about 2 % busy before it -
sections 1 to 13 716, as before, and section 14 339, which alone
(`--v2-only`) takes 8 s; section 14 alone in WSL (cft2204, gcc 11.4,
Python 3.10), 337 checks, 0 failed, 6 s, without Windows' argument case
and its two checks. The whole gate not yet run in WSL, nor on a card.
With the process's own text (verifier-VCV2CW's finding, 2026-10-03):
1,044 checks on the Windows desktop and one SKIP, 91 s - section 14 328;
section 14 alone in WSL 326 checks, 0 failed, 6 s.
With version 2's section 14 (2026-10-03): 1,020 checks on the Windows
desktop and one SKIP, the trial's cost NOT TESTED there, 96 s, the
desktop about 6 % busy - sections 1 to 13 716, as before version 2, and
section 14 304, which alone (`--v2-only`) takes 10 s.
With a negative lane and slot (S1's second send-back, 2026-09-30): 679
checks on the Windows desktop and one SKIP, the trial's cost NOT TESTED
there, 88 s; in WSL (cft2204, gcc 11.4, at 350f7f2), 682 checks, 0
failed, nothing skipped, 81 s. With a negative run index and `slotstep`
(S1's send-back, 2026-09-30):
656 checks on the Windows desktop and one SKIP, the trial's cost NOT
TESTED there, 96 s. On Linux the three checks of the trial's cost run
in the SKIP's place: in WSL (cft2204, gcc 11.4, at f572ef3), 659 checks,
0 failed, nothing skipped, 85 s. With the accuracy
entries (2026-09-30): 634 checks on the Windows
desktop and one SKIP, the trial's cost NOT TESTED there, 80 s. On Linux
the three checks of the trial's cost run in the SKIP's place, so 637
there, by that arithmetic and not yet run. With `--scratch-depth`
(2026-09-29): 458 checks on the Windows desktop
and one SKIP, the trial's cost NOT TESTED there, 55 s. On Linux the two
checks of the trial's cost run in the SKIP's place, so 460 there, by
that arithmetic and not yet run. Before it, since P3b's second
send-back: 391 checks on Linux, 41 to 43 s in WSL; 389 on the Windows
desktop and one SKIP, 39 to 41 s. There were 293 at 99f1b43, 380 at
4eed552 and 389 at eb2d1ae. Verifier-C7 measured 4eed552's 380 at 45
to 52 s with the desktop at 0 to 4 % CPU, and 163 s at about 93 %.

**On the card**, `hw/card-segrun.sh <image.xclbin>` runs the same gate
with the certificates made on the tile. It holds the device lines to
`sha256sum` of the image and to what `device-test -i` prints, and each
card certificate's run blocks to the software backend's. Since step 5
each card certificate carries its program's accuracy entries, from the
states the card's runs wrote. Its accuracy block is held to the
software backend's too, and the script hands the gate cft-audit, so
both auditors must accept each card certificate. It has not run with
entries on a card yet: the card legs are the lead's. It ran at
99f1b43 on 2026-09-28, on the U50 (XRT 2.19) with both round-2 images:
8 checks of 8, the gate's 295 of 295 on the quad's four tiles and 295
of 295 on the single, 48 to 50 s each, and its negative control, a
wrong image digest, failing the device lines by name
([CARDDAY.md](CARDDAY.md)). It ran again at 4eed552, eb2d1ae and
d4abe2a, P3b's three answers (not at ff7ff7b alone),
8 of 8 each time, the gate on each image 373 of 373 at 4eed552, 382 of
382 at eb2d1ae, and 384 of 384 at d4abe2a in 66 to 68 s, nothing
skipped (2026-09-28 and 29; the round's ledger, card-p3b, card-p3b2
and card-p3b3).

## The audit tool

`cft-audit` is the C auditor, the plan's step 4: every step of "The
audit", the strict reader included, in this page's order, beside the
golden one. Since version 2's C half (parcel CV2CA, 2026-10-02) it reads
both versions and audits version 2 too, every step that needs no source
(**Version 2**, below). `make -C host all` builds it, from
`host/tools/audit.c`.

    cft-audit --cert CERT [--salt SALT] [--states DIR] [--seed HEX]
              [--signature SIG] [--keyring RING] [--superseded OLD]
              --run 0 --image IMG [--bank BANK] [--stream a|b|c FILE ...]
                      [--choose all|sample:K|K,K,...]
                      [--define all|K,K,...]
              [--run 1 --image IMG ...] ...
    cft-audit --read --cert CERT [--salt SALT]
    cft-audit --sample SEED R S K

**What it is handed.** Each option is one argument of `cert.audit`
("The shape of what it is handed"):
- `--cert`: the certificate's bytes;
- `--salt`: a file of any length, whose length is step 3's
  (`salt-length`). With none, no salt is handed;
- `--run R` opens run R's block, and the options after it, up to the
  next `--run`, are run R's:
  - `--image` and `--bank`: its program, image and bank;
  - `--stream X FILE`: its stream X, the others +0;
  - `--choose`: its choice, `all` (the default), `sample:K`, or the
    segments `K,K,...`;
- `--states DIR`: every file in DIR named `run-<r>-boundary-<b>.bin`, r
  and b in their one decimal spelling, is run r's state at boundary b.
  Those are the files cft-segrun writes ("The segment runner"). Other
  files are not read, and one named so but spelt otherwise
  (`run-01-boundary-0.bin`) is `usage`;
- `--seed HEX`: the sample's seed, 64 hex digits. Any other value is
  `choice`, at step 2. With none and a sample asked, the operating
  system draws 32 bytes, once for the audit, and the verdict prints
  them.

A run index that names no run of the certificate is refused by the
step that reads that argument, as `cert.audit` refuses a key that is no
run: `choice` for a choice, `program-image` for an image or a bank,
`stream` for a stream, and `state-shape` for a state file of a run or
boundary that does not exist.

**When it reads them.** The certificate, the salt, and every image,
bank and stream are read before step 1. The state files are listed
then too, and each is held to be a regular file and opened. So a file
the command line names that cannot be read, or a directory by a
boundary file's name, is `usage` before any step. A state's bytes are
read at step 7, where `cert.audit` takes them. Two things can fail
there: a file that changed or went after it was opened, `usage`; and a
file too large for the memory the tool may use, `memory` (verifier-A1:
100 MiB under a 64 MiB commit limit). A state read whole but of the
wrong size is `state-shape`, as the golden's.

`--read` is `cert.parse(data, salt)`: the hash line, the body's hash and
the strict form, and with `--salt` the salt against the mode and the
commitment. `--sample` prints the segments `cert.sample` draws, as the
page's test vector writes them. It samples through a map of at least
4K slots, and a K whose map this process cannot size or allocate is
`memory`, at once; on a 64-bit build every K from 2^59 up is. There
`cert.sample` has no verdict: it builds the list of all S segments.

**What it answers.**
- Accepted: stdout is the golden verdict's lines,
  `cert.Verdict.lines()`, byte for byte, and the exit code is 0.
- Refused: stderr carries `cft-audit: refused <name>: <why>`, as
  cft-segrun prints its refusals, and then `cft-audit: location
  line=<n> run=<r> segment=<k> entry=<j>`, each field `-` where it does
  not apply: the golden refusal's `.line`, `.run`, `.segment` and
  `.entry`. The exit code is the name's (the table under "Refusals").
- Four names are the tool's own:
  - `usage`, exit 64: a command line it does not take, or a file it
    names that cannot be read (above);
  - `memory`, exit 71: an allocation of its own that fails, or a
    `--sample` K past what a map can be sized for. A number the
    certificate states is never `memory` ("What an audit spends");
  - `build-width`, exit 78: a build whose bigint is narrower than 2,047
    bits, handed a certificate with an accuracy entry;
  - `build-format`, exit 78: a build asked for a format above its
    ceiling, by a run, by an image, or by an accuracy value where it
    reads one (both below).
- A library call that fails where no refusal names the failure, such as
  a software handle that does not open or a conversion that fails, is
  not a verdict. It prints `cft-audit: internal error` and exits 70.

**How it computes.**
- **Re-runs** go through libcft's software backend at each run's depth
  ("The chain"), on a handle `cft_open_ex` opens for that depth. A
  segment the executor refuses is `program-image` at its run and
  segment, with the library's sentence.
- **Hashes** are the library's streaming SHA-256 (`host/src/sha256.h`,
  which `cft_sha256` wraps). So a state is hashed where it lies, and a
  bounded run's +0 streams need no buffer.
- **Exact values** go through the library's own 2,048-bit bigint,
  `cft_bn` (`host/src/bigint.h`, an internal header; the lead's
  decision, 2026-09-29). The tool adds a division, a gcd and an exact
  left shift of its own: `cft_bn_shl` keeps a spare limb, and refuses to
  shift a value that fills the container, even by 0.
- **One arithmetic, two tools.** Since the plan's step 5 (2026-09-30)
  the tool's exact arithmetic lives in `host/tools/cert_exact.h`, which
  cft-segrun builds too, so the writer and the C auditor compute every
  value with the same code. It holds the bigint's missing pieces, an
  element's exact value, the rationals under the width rule, the
  rounding, a rational token's reading, and "The functions, exactly", in
  three parts: the checks, the states read, and the value. It also holds
  `value_holds`. Nothing in it prints or exits, and each function that
  can fail returns a status: this tool maps a status that names a
  refusal to that refusal (step 10's names at the entry), and the two
  that name none, an exact step past the bigint and a library call that
  failed, to its internal error, as before. The header is compiled
  into every build of the tool, the narrow builds and the probe among
  them, and each build compiles warning-free with the project's flags
  (-std=c99 -Wall -Wextra -Wpedantic -Wshadow; the lead's condition).
- **Elements.** An element's exact decimal is `cft_to_decimal_char` at
  0 digits, and a value exactly widened is `cft_convert`. A rational
  rounded into a format is one integer division, as `_round_rational`'s
  is, then `cft_from_hex_char` on the dyadic value that division leaves.
  That is round_pack's answer, as the golden's is.
- The gate held each of these to Python's integers or the golden model
  before they were trusted (section 6, below).
- **The narrow builds.** A library built with a `CFT_MAX_FORMAT` below
  3 carries the formats up to that ceiling. Its `cft_bn` is narrower by
  default, 576 bits at the fp128 ceiling, and `CFT_BN_LIMBS` can keep it
  at 2,048 bits (`host/include/cft_config.h`). A narrow build audits in
  full, with the golden's verdict, a certificate whose runs and values
  are all in formats within its ceiling, handed images in those
  formats, and, where its bigint is narrower than 2,047 bits, carrying
  no exact value. What it cannot do it refuses by a name of the tool's
  own, where the certificate or an input asks for it, rather than audit
  differently ("The width rule"). The rule is the lead's (2026-09-29,
  after verifier-A1 found a narrow build doing otherwise twice): nothing
  a narrow build cannot do reaches another name or an internal error.
  - `build-format` wherever a format above the ceiling would reach the
    library. The reader raises it at the format word, before the rest
    of that line: at a run's `program-format` line, whose image the
    library cannot load, and at an accuracy value's line, `rounded` or
    `enclosed`, whose decimals and rounding are the library's. A build
    whose bigint is narrower reads no value's line: its `build-width`
    comes first, at the `accuracy` line. Step 4 raises it at a run
    stated within the ceiling whose image's header names a format above
    it. The golden refuses that image `program-format`, or
    `program-image` for a defect found past its format, and a build that
    cannot load the image cannot learn which. An image the library finds
    malformed first (a wrong magic or version, an unknown flag bit, word
    7 without SCRATCH_IO, an unknown precision code, fewer bytes than a
    header) keeps the golden's `program-image` in every build.
  - `build-width`, where the `cft_bn` is narrower than 2,047 bits
    (2 x 1,023 + 1): at an `accuracy` line whose count is at least 1 and
    agrees with its entries. Such a build compiles the tool without its
    exact arithmetic. It is a `#if`, so no build computes an exact value
    in a narrower bigint.
  - The gate builds `CFT_MAX_FORMAT=2` both ways, at its own bigint and
    at `CFT_BN_LIMBS=64` (section 5, below).
- **The instrument.** `CFT_AUDIT_PLANT=executor-refuses` makes every
  re-run's executor refuse, as test_cert.py's monkeypatched `seq.run`
  does, so that the gate holds that refusal (`program-image` at the
  run and segment). The empty string is the variable unset, as
  `CFT_SEGRUN_PLANT`'s is: cmd and Windows PowerShell remove a variable
  set empty, so an empty one means the same everywhere. Any other value
  is `usage`. No library in this tree refuses a re-run that passed
  steps 4 to 7.

**What it proves, and what it does not.** It proves what "What an audit
proves" says, for the segments it re-runs. It is independent of the
golden model: it reads with its own reader and re-runs with libcft. It
is not independent of libcft. For a certificate cft-segrun made on the
software backend, libcft made it, so only the golden auditor is
independent of the producer there.

**Version 2** (parcel CV2CA, 2026-10-02). A file whose first 18 bytes are
`cft-certificate 2` and a newline is version 2's, as `cert.audit`
chooses: version 2's strict reader ("Version 2's strict reader") and
version 2's audit, in "Version 2's audit"'s order. Every other file is
version 1's, read and audited as before. Version 2's inputs, beside
version 1's options:
- `--signature SIG`, `--keyring RING` and `--superseded OLD`: the `.sig`
  file, a keyring and the superseded certificate (`signature`, `keyring`
  and `superseded`), read before step 1;
- `--define SPEC`, in a run's block: the definition re-run's segments,
  `all` or `K,K,...` (`define`), held at step 2 as a choice is
  (`choice`);
- `--states DIR` also hands every file named `run-<r>-segment-<k>.flags`,
  r and k in their one decimal spelling, as run r's block of segment k
  (`lane_flags`), listed and opened before step 1 as a state file is; one
  named so but spelt otherwise is `usage`. A raw end and a raw block
  (`-raw.bin`, `-raw.flags`) are not read, and version 1 reads no block
  file.
A version-1 certificate handed one of these is `usage`, as `cert.audit`
raises a TypeError for them.

What it does with them:
- **It takes no source,** and has no interpreter or compiler of the
  language. A step that needs one refuses `source-missing` exactly where
  the golden auditor handed no source does: a replay line of a re-run
  segment, after the line's own checks (`replay-missing`,
  `replay-unmarked`, `replay-raw`); a wider-source relation, after
  `aux-format`, `aux-lanes`, `aux-source` and the steps; and a definition
  re-run, at its first segment whose start is known (`state-missing`
  before that). So it accepts a certificate with replay lines only where
  the segments it re-runs carry none, and none with a wider-source run.
  A run that names a source is reported "named, not handed".
- **It regenerates no initial state.** A generator is reported: the golden
  model's `shake-box` as not regenerated, any other as not known - the
  lines the golden auditor prints when it is not asked to regenerate.
- **Its re-runs** ask libcft for each segment's block (ABI 0.17's
  `lane_flags`) where the run says `yes`, and hold it to the segment
  line's `lanes`. Where the run says `no`, a mark is STATUS[6], the OR of
  the lanes' marks (R23).
- **The signature** is verified in C: Ed25519 (RFC 8032, section 5.1) in
  `host/tools/ed25519.h`, with SHA-512 (FIPS 180-4) in
  `host/tools/sha512.h`, both written for this tree from their
  specifications, header-only, and verification alone
  (`python/cft_sign.py` signs). The cofactored equation, S below L, R and
  the key decoded by 5.1.3, and a key of small order refused `signer`
  wherever a key is read - the issuer-key line, a keyring's line, a
  signature file's key - through `ed25519_key_check`, the one decoding
  cft-segrun shares. It is not constant-time: it handles public data
  only.
- **The definition** is this library's: cft.h's `CFT_PROFILE_*` and
  `CFT_LANGUAGE_*`, which the gate holds to the golden model's. Where they
  do not cover the certificate's, a re-derivation that fails - step 4's
  loader verdicts, the wider-source relation, a re-run with its replay
  line's checks, and the segment line's - is refused
  `definition-differs` at its own location, as `cert2._Through` does.
- **Accepted,** stdout is two header lines, `auditor cft-audit <build
  id>` (the library's `cft_build_id()`) and `audited <time>` (UTC), the
  auditor's identity and the audit's time that `cert2.Verdict.header()`
  holds and the comparison between auditors leaves out, and then
  `cert2.Verdict.lines()`, byte for byte. `--read` prints
  `cft-certificate 2: READ`, as version 1's does with its number.

**Its gate** is `host/tests/audit_check.py`, `make -C host audittest`,
which `verify/run.sh`'s `audit` stage runs in the gate budget. It hands
both auditors the same inputs, and requires the same verdict: the
refusal's name, code and location, or both ACCEPTED with the same lines.
1. **The tool's own:**
   - every `usage` refusal a command line or a file causes. A directory
     by a boundary file's name, beside a certificate step 1 refuses, is
     among them, so a tool that found it only at step 7 goes red;
   - `--sample` against the page's vector and against `cert.sample`,
     with its `choice` refusals, and three samples whose map cannot be
     sized (K of 2^62, twice, and 2^63 - 1), each `memory` at once;
   - the instrument set empty, which is the instrument unset;
   - a seed the operating system draws: different in two audits, and
     the same verdict again when handed back;
   - five controls the plant census asked for (below);
   - git ignoring the binary;
   - since version 2's C half: version 2's `usage` refusals (each of its
     inputs beside a version-1 certificate, out of its place, twice, a
     file not there, a block file misspelt or a directory by its name), a
     misspelt block file beside a version-1 certificate not read, and
     cft.h's profile and language macros, the tool's writer's list of
     variables and its generators against the golden model's;
   - thirteen version-2 controls no test_cert2.py call hands the tool as
     it is handed them: `definition-differs` inside each re-derivation a
     source-free audit reaches past step 4 (a segment line's flags and
     block, a replay line's raw values and its absence, the wider-source
     relation), audits accepted under a definition that does not cover
     the certificate's (by the profile's minor, and by the language where
     a run names a source), a signature file whose key encodes no point
     and one naming another certificate over this one's signature (each
     `signature`), the wider-source relation's lanes and steps, and
     blocks past segment 9, which the golden auditor reads, and its
     verdict lists, in their decimal spelling's order (10 before 9).
2. **test_cert.py and test_cert2.py**, each run in the gate's process
   with `cert.parse` and `cert.audit` shadowed. Every top-level call their
   tests make is handed to the tool too, translated into files and
   options. So the tool is held to every control the golden auditor is
   held to whose arguments files and options can spell, and stays so as
   controls are added.
   - A call whose arguments no file or option spells faithfully is
     counted and named, not compared: a list where a mapping goes, a
     string or bool key, an integer past the format, a salt that is not
     bytes.
   - A seed the golden audit draws is caught and handed to the tool.
   - An executor the test makes refuse is the instrument.
   - A version-2 audit call handed a source, or asked to regenerate, is
     held to the golden auditor handed neither, as the tool is
     (`no_source_kwargs`); the golden call's own result still goes back
     to the test.
3. **segrun_check's certificates:** cft-segrun on its programs, keyed
   and open, with the accuracy entries segrun_check gives them (every
   method, scope, form and direction; since step 5), each audited in
   full, in full from the initial states alone, and sampled under a
   fixed seed.
4. **The golden corpus** (`certificates/MANIFEST`), where the tree has
   one: every case the same three ways, the two auditors against each
   other and against the manifest's verdict. Each version-2 case and
   control is handed as corpus.py hands the golden auditor its blocks,
   signature, keyring, superseded certificate and definition re-run,
   without the source and the regeneration: in full, from every committed
   state, and for a case a writer makes sampled under the fixed seed and
   from every state choosing the segments with no replay line and no
   definition re-run, where the tool can accept a certificate whose
   replays it cannot make. How many keep the manifest's verdict handed no
   source is printed, and each that does not by the verdict both auditors
   give it. Measured (2026-10-03, at parcel CV2CA's b886236): 20 of the
   37 keep it; of the other 17, 8 are refused `source-missing` and 3
   `state-missing` before the check the case is for, 3 `aux-source` and 1
   `aux-image` at run 1, the half-step run, and 2 are accepted,
   v2-source-format and v2-source-shape, whose defects only the source
   shows.
5. **The narrow builds**, both at `CFT_MAX_FORMAT=2`:
   - at its own 576-bit bigint: `build-width` at the example's
     `accuracy` line, in an audit and in `--read`, and the same runs with
     `accuracy 0` audited in full. lor (test_cert.py) with entry 1's
     value in fp256 is `build-width` at its `accuracy` line, before any
     value;
   - at `CFT_BN_LIMBS=64`, compiled at -O1 to keep it cheap: lor's four
     entries and the page's example audited in full, with the golden's
     verdict. lor with entry 1's value re-made in fp256, rounded or
     enclosed, is `build-format` at that value's line, in an audit and
     in `--read`. The golden auditor and the default build accept it
     (verifier-A1's second case);
   - in both: `build-format` at run 0's `program-format` line, in an
     audit and in `--read`, of an open fp256 certificate cft-segrun makes
     with `accuracy 0`, which the golden auditor and the default build
     accept (A1's first case). And `build-format` at run 0 when the same
     images are handed under runs restated as fp128, which the golden
     auditor and the default build refuse `program-format`.
6. **The numerics**, through a probe build of `tools/audit.c`
   (`-DCFT_AUDIT_PROBE`, compiled only by the gate):
   - the tool's division, gcd and exact arithmetic against Python's
     integers, up to 2,047 bits;
   - its rounding against `cert.round_rational`, in every format and
     direction;
   - an element's exact value and width against `cert.element_fraction`;
   - `cft_convert` and `cft_to_decimal_char` against `cert.widen` and
     `chars.to_decimal`.
7. **Ed25519 and SHA-512** (since version 2's C half), through the same
   probe build: every vector `python/tests/test_ed25519.py` carries -
   the RFC's five, every bit of their signatures, their messages and
   keys edited, another key's signature, the three S at or above L, the
   six encodings of no point as key and as R, the eight keys of small
   order with verifier-VCV2B's forgery under each, 64 signatures under a
   key with a small-order part (the cofactored equation, odd k among
   them), the mixed keys, the page's version-2 test vector and random
   keys the golden model signs - each answer the golden model's; and
   SHA-512's published examples ("abc", the 448-bit and 896-bit
   messages, a million 'a's, the empty message) and every length across
   its padding against hashlib.

Measured on the desktop, niced, on a day it was in use (2026-09-29, at
ca1327f): 6,799 checks, 0 failed, 219 s. That run read the corpus from
P2's tree at 679c64d, the commit the lead merged. Where a tree has no
corpus, section 4 is a SKIP line, which `verify/run.sh` counts as an
inner skip.
- Section 2: test_cert.py's 101 tests pass in 109 s, 67 s of it the
  tool's 6,505 runs. Every one of the 6,262 top-level parse calls, and
  243 of the 282 audit calls, got the same verdict from the tool. The
  other 39 pass arguments no file spells.
- Section 5: 26 checks, the two narrow builds compiled in 5 s each.
- Section 6: the probe's 4,566 operations all agree, in 15 s.

With the arithmetic moved to `cert_exact.h` and the entries in section
3 (2026-09-30, on the desktop, niced): 6,800 checks, 0 failed, 0
skipped, 221 s. The one check more counts section 3's entries, 15 of
them. Section 2's test_cert.py, then 102 tests with the golden writer's
new `accuracy-run`, passed through the tool, with parse 6,262 of 6,262
and audit 243 of 282 as before. The move alone, before the entries,
gave 6,799 of 6,799 in 218 s. So no verdict moved. With `cert.derive`
bounding a lane and a slot from below too (the second send-back,
2026-09-30): 6,800 checks, 0 failed, 246 s; test_cert.py's 103 tests
passed through the tool, parse 6,262 of 6,262 and audit 243 of 282 as
before, so no verdict moved there either.

**The plants.** `host/tests/audit_plants.py` is the census. In a fresh
copy of host/, never the tree, every call of `refuse` or `malformed` in
`tools/audit.c` becomes a numbered site that an environment variable
skips and that names itself when it refuses. The gate's recorded cases
(`audit_check.py --record`) are replayed through the copy. A plant
changes only the cases that reach its call, so each site is planted in
turn and only its own cases replayed. Since step 5 the arithmetic's
refusals come back to `tools/audit.c` as statuses from `cert_exact.h`,
refused there one call a name (step 10's `accuracy-run`, `-scope`,
`-slot`, `-finite` and `width` each at its own call), so the census
still plants each name apart. It does not plant inside the header,
whose checks are held by the gates' controls: test_cert.py's through
section 2, and segrun_check's section 12. The census below is
verifier-W1's, run after the move.

Since version 2's C half (parcel CV2CA, 2026-10-02) `tools/audit.c` has
259 sites, and `definition-differs` is a site of its own (the judgement
`refuse` hands to `judge_differs`), so planting it makes a re-derivation
refuse by its own name. The census also reports version 2's names: each
one's sites, and how it found them, and each name with no site - a
check that needs a source or a regeneration, which the tool does not
take - with why. Nor does it plant inside `tools/ed25519.h` or
`tools/sha512.h`, whose answers section 7 holds to their vectors. Its
instrumented copy was built and replayed (MEASURED, three sites planted,
the baseline 192 of 192 recorded cases); the census over every site and
every recorded case has not been run on version 2: it is the lead's.

On `tools/audit.c` as of 0ad2609 (unchanged since the move, 0612b37),
with the gate's 6,669 cases, the census found 163 sites (186 s on the
desktop; verifier-W1, 2026-09-30). At ca1327f, before the move, it
found 167: 148 red, 12 green and 7 unreached (157 s, 2026-09-29). The
move made seven sites three, calls that refuse one name each (W1's
reading of the diff): derive's two `accuracy-run` calls became one,
`exact_of`'s and `rat_checked`'s `width` one, and `read_rational`'s
three `malformed` calls one. The seven were six red and one green (zero
spelt 0/3), and the three are red.
- **145 red.** Each turns a case red, and the gate's line names the
  golden auditor's refusal beside the tool's other answer. Four answer
  verifier-A1's findings, each planted in turn:
  - `build-format` at a run's `program-format` line: its case reaches
    step 4, which refuses it `build-format` at the run, not the line;
  - `build-format` at a value's line: its case reaches the library's
    decimal, an internal error, exit 70;
  - `build-format` at an image above the ceiling: `program-image`;
  - the `--sample` map's size: a map of 16 slots, and the sample runs
    past the census's 20 s.
- **11 green.** Each stays green because another check refuses its
  cases by the same name at the same place:
  - in the golden auditor's order too:
    - a block-starting line whose block is behind: the next rule of
      "A line that is not the one expected" says `line-unexpected`;
    - a decimal's spelling, read again with its size;
    - a program without SCRATCH_IO, whose scratch goes in as 0 slots,
      the second reason;
  - in C alone:
    - a run line of two tokens, and a term with no coefficient: the
      next read takes the next line's key, never a kind or a rational,
      and refuses `malformed` at the same line;
    - a half-step run beside a main image with no bank: every h-slot is
      past the empty bank;
    - an h-slot past the bank: read from the file buffer's zero-filled
      slack, it holds zero;
    - a directory by a boundary file's name: on Windows, where the
      census ran, opening a directory fails as well, and that check says
      `usage` before step 1 too. On Linux it is red, measured by
      verifier-A1 in WSL (cft2204): fopen opens a directory, and the
      certificate beside it is refused `hash-line`;
    - no argument at all, `--sample` given twice, and no `--cert`: each
      is `usage` by the next check.
- **7 unreached.** No input reaches these:
  - an allocation of the tool's own that fails (`memory`);
  - a state file listed that then cannot be sized, or opened: gone
    since the listing, or behind permissions the gate does not set
    (`usage`, twice);
  - an operating system that gives no random bytes, on Windows and
    elsewhere (`usage`, twice);
  - a state file that changed or went between its opening and step 7
    (`usage`);
  - a library that fails a re-run the checks before it allowed
    (`program-image`). Its instrument twin is red.

The census's first pass left sites that no case reached, or that none
turned red, and the gate gained ten controls for them:
- five `usage` cases;
- an audit of each of two programs that are not segments. test_cert.py
  reaches those two reasons through the writer only;
- a stream for a run the certificate lacks;
- a stream of whole elements and one byte;
- a state one byte past its size.

## Golden certificates

`certificates/` holds a committed corpus of programs and their
certificates: the plan's step 7. Logan asked for it on 2026-09-29, as
"programs and their certificates utilized as regression tests
themselves as well as conformance tests in the future". It is a
regression test now, and a conformance test for another implementation
later.

**Why it exists.** The segment runner's gate holds cft-segrun and the
golden writer to each other, from states it makes fresh. So a change
that moves both at once passes it: a change to the model, to a hash or
to an encoding. A committed certificate does not move. Every such change
either keeps the corpus's bytes, or changes them in a commit that says
so, made by `python certificates/corpus.py make`.

**The cases.** Version 1 has twelve, each small: 2 to 4 lanes, and 2 to 8
segments a run. Each holds something no other does:
- `lorenz63-rk4-fp64`, `lorenz96-rk4-fp64` and `henonheiles-lf-fp64`: the
  three ODE programs at fp64, open. Each has a half-step run and a wider
  fp128 run beside its main run. lorenz63's carries two estimates:
  `wider`, enclosed in fp64, and `step-halving`, exact over the lanes.
- `lorenz63-rk4-fp256`, `lorenz96-rk4-fp256` and `henonheiles-lf-fp256`:
  the same at fp256, each with a half-step run. henonheiles' carries the
  energy's drift over its four lanes, exact. The value has a 697-bit
  numerator and a denominator of 3 x 2^717, 719 bits: near the width
  rule, where a C auditor's bigint is near its reach.
- `example`: this page's example certificate, byte for byte, keyed under
  the example salt, with the page's two entries. The gate holds the
  page's block to the committed file.
- `flagstep-fp64`: flags and STATUS that change from segment to segment
  (20, 0, 1, 0, 20 and 48, 48, 0, 48, 48), which no ODE segment's do.
- `augsum-fp64`: revision 8. augadd and augerr keep a compensated sum,
  and a stepped STX and LDX store and read back its partial sums. Only
  the software backend makes it: no tile built so far publishes either
  revision-8 bit, and a tile without one refuses the program at load,
  by name.
  - Its lanes 2 and 3 start at s = +-(2^53 + 2) with t = +-1, so their
    first augadd is a tie: +-(2^53 + 3), between +-(2^53 + 2), whose
    significand is odd, and +-(2^53 + 4). roundTiesTowardZero, 754's
    rule, gives +-(2^53 + 2) and e = +-1, and roundTiesToEven would give
    +-(2^53 + 4). So an augadd that rounds its ties to even fails the
    case, and so does one that rounds them toward minus infinity (lane
    3).
  - Lane 1's 1e16 + 1 is a tie at which those two agree, since 1e16 is
    both the smaller and the even neighbour. An augadd that rounds ties
    away from zero, or toward plus infinity, fails there.
- `deepwrap-fp64-256` and `deepwrap-fp64-2048`: one program, one bank
  and one initial state, certified at 256 slots and at 2,048 through
  `cft-segrun --scratch-depth`. Each has a main run of 3 segments and a
  half-step run of 6.
  - Eight probes index past the carried block, at p = 16,384 down to
    128. A non-strict LDX at p reads slot 0 at every depth up to p, and
    +0 past it. A non-strict STX at p + 2 stores the trip's count in slot
    2 at every depth up to p. So at a depth D, n probes reach the
    carried block: 7 at 256, 4 at 2,048, 0 at 32,768. A segment is an
    Euler step of x' = x, y' = n x, and z ends it as n: z starts at 0,
    and at 32,768 no store lands (the source's header).
  - So every power of two from 128 to 32,768 computes its own chain, in
    both runs, and every depth below 128 computes 128's. That was
    measured on 2026-09-30 at every power of two from 4 to 32,768, and
    at each, libcft's boundary states are the golden model's. At 1 and
    2 slots the image does not load. A run at 4,096, or at 1,024,
    stating 2,048 fails deepwrap-fp64-2048 (verifier-A2's plant T3).
  - Both runs of each state `parameter scratch-depth N`. So a writer that
    states the depth in the main run's block alone fails both cases.
  - It needs nothing past revision 7: a bank, the scratch block, a
    non-strict LDX and STX, IADD and ISHR, and a loop. So a revision-7
    tile loads it (by docs/SEQUENCER.md's features; no card has run
    it).
- `lorenz63-rk4-fp64-half-init`: a half-step run entered from an initial
  state of its own. Its runs are what ran, but its stated relation to
  the main run does not hold, so its expected verdict is the refusal
  `aux-start`: one committed negative for every auditor.

**Version 2's cases** (2026-10-02) are the golden writer's. Seven are
certificates a writer makes. The manifest marks each `writers both`: a C
writer must reproduce it, and since version 2's C half cft-segrun does
(the check's step 5, below).
- `markstep-fp64`: the replay case, and this page's version-2 example,
  byte for byte. markstep's image computes its source's map, and beside it
  a routine's own test, run quiet, which marks lanes 0 and 1 in segment 1
  and writes lane 0's last bit wrong. The golden writer replays both
  lanes by the definition (`replay 1 marked 2 changed 1`). Its audit is
  handed the source and also re-runs every segment by the source's
  interpreter (`define 0:all`).
- `lorenz63-rk4-fp64-sourced`: Lorenz-63 compiled by cftc for `sw` from
  `programs/systems/lorenz63-rk4-fp64.cftl`, 3 lanes. It has a main run, a
  half-step run on the compile's half bank and h-slots, and a
  wider-source run: the same source compiled at fp128. Its estimates are
  `wider-source`, enclosed in fp64, and `step-halving`, exact. Its lanes
  are `lorenz63-rk4-fp64`'s, and the two wider estimates differ, since
  the wider-source run's constants are the source's rounded at fp128 and
  the wider run's are the fp64 bank's widened: over the lanes 2.546e-14
  and 2.600e-14, on lane 0 2.7e-15 and 1.8e-15 (measured 2026-10-02).
  The step-halving value is version 1's case's, bit for bit. Its audit
  recompiles every run's image.
- `flagstep-fp64-lanes`: flagstep with each segment's per-lane flags, 3
  lanes whose counters start at 3, 2 and 1. So in each of the 5 segments
  the lanes raise different flags, and a block written against another
  lane, or another segment, fails it. It carries the counter's drift.
- `signed-fp64`: every header line of version 2 spelled out: texts with
  spaces and non-ASCII, the device lines, the writer's and compiler's
  builds, and the environment. It is keyed, its initial state is the
  `shake-box` generator's, and it supersedes `flagstep-fp64-lanes`. Its
  `.sig` is the test key's, and its issuer `cft test issuer (published
  key)`: anyone holding the published seed can sign as the key's holder,
  so the keyring binds it to an evidently test name, never a person's.
  Its audit is handed the signature, that keyring and the superseded
  certificate, and it regenerates the initial state.
- `lorenz63-rk4-fp64-rebuilt`: a compiled Lorenz-63 run whose initial
  state is `shake-box`'s. Its full audit is handed the source and no
  state, recompiles the image, regenerates the initial state and re-runs
  every segment: the verdict's `rebuilt`.
- `markstep-fp64-other-b` and `markstep-fp64-loud`: honest certificates of
  other maps, on a bank whose b is 1/4 and not the source's 1/7, and on
  one that raises invalid in every lane. Each holds together. The
  definition re-run of one segment refuses them, `definition-end` and
  `definition-flags`.

Thirty are controls, under `certificates/v2-controls/`, which the manifest
marks `writers golden`. Each is a case's certificate with one edit, or its
case with one of the audit's inputs replaced, and every auditor handed
the case's inputs, its source among them, must refuse it by its
verdict's name. (cft-audit, which takes no source, gives that name on
19 of them, refuses nine by another name - `source-missing` on four,
`aux-source` on three, `aux-image` and `state-missing` on one each -
and accepts two, v2-source-format and v2-source-shape, whose defects
only the source shows: "The audit tool".) There is one for each of
version 2's refusals that a committed case can carry: `marked`,
`replay-lane-flags`, `replay-source`, `replay-method`,
`provenance-order`, `signature-format`, `signature`, `signature-key`,
`signer`, `supersedes`, `source-digest`, `source-refused`,
`source-format`, `source-graph`, `source-param`, `source-shape`,
`source-image`, `compiler-differs`, `source-missing`,
`lane-flags-shape`, `lane-flags-hash`, `lane-flags-identity`,
`initial-state`, `aux-source`, `segment-lane-flags`, `replay-missing`,
`replay-unmarked`, `replay-raw`, `replay-changed` and
`definition-differs`. With the two definition cases above, that is 32 of
version 2's 34 new names. `definition-unavailable` and `replay-undecided`
are refusals of the auditor's or the writer's environment, so their
controls are test_cert2.py's plants.

The corpus's data is 333 KB: 313 files and 333,220 bytes besides
corpus.py (2026-10-02). Version 2 added 143 files of 115,186 bytes, the
controls' 59 of them 88,327, and the manifest grew from 23,839 bytes to
89,262. Before that it was 170 files and 152,611 bytes (152,617 until
step 5 made the manifest's three `golden` words `both`, and 145,061
before the fixes round's cases, both 2026-09-30).

**The files.**
- `certificates/MANIFEST`: every case, every file it names, and each
  file's SHA-256.
- `certificates/images/`: every image a run names. The gate assembles
  each again from its source and requires the same bytes:
  - a library image from `programs/`, whose digest `programs/MANIFEST`
    also carries;
  - a wider run's from its main run's source, with the `.format` line a
    rung up;
  - the corpus's own from `certificates/programs/`, markstep's definition
    `markstep-fp64.cftl` beside its image;
  - a compiled image (version 2's): cftc's compile of a source at a
    format, with its steps and target, compiled again.
- `certificates/<case>/<case>.cert`: the certificate.
- `certificates/<case>/states/run-<r>-boundary-<b>.bin`: every boundary
  of every run, lane-major, as cft-segrun writes them. Handed whole, the
  directory serves a sampled audit; its boundary-0 files alone serve a
  full audit from the initial states.
- `certificates/<case>/states/run-<r>-segment-<k>.flags`: in a version-2
  run with lane flags, each segment's per-lane block, one byte a lane,
  which the audit is handed. Beside them, `run-<r>-segment-<k>-raw.bin`
  and `-raw.flags`: each replayed segment's raw end state and raw block,
  as the machine wrote them before the replay. The certificate hashes
  both; no audit needs them.
- `certificates/<case>/run-<r>.bank`: a bank that is no library file, a
  half-step run's halved bank or a wider run's widened one, or a version-2
  run's: a compile's bank, or markstep's.
- `certificates/example.salt`: the example salt, 00 01 .. 1f. This page
  prints it, so it is a test salt only, and never an owner's.
- `certificates/signed-fp64/signed-fp64.cert.sig` and `keyring`: the
  detached signature by the test key, whose secret is 20 21 .. 3f, and
  the keyring its audit is handed. This page prints the key too (version
  2's "The detached signature"), so it signs test certificates only.
- `certificates/v2-controls/<name>.cert`, and `certificates/v2-controls/
  <name>/`: each control's certificate, and the files it hands that its
  case does not: a source, a block, a signature, a keyring, or states
  renumbered with its runs.
- `certificates/corpus.py`: `make` writes the corpus, and `check` is its
  gate.
- Git keeps the bytes: a certificate, a signature file and a keyring are
  `-text`, and the states, the blocks and the salt are `binary`
  (.gitattributes).

**The manifest** is text in a certificate's own style: printable ASCII
and LF, one record a line, its key first, single spaces. It takes two
liberties: `#` begins a comment line, and blank lines separate cases.
Paths are from the repository's root.
- Its first record, after the comment lines at its head, is
  `cft-golden-corpus 2` (`1` until version 2's cases, 2026-10-02). Then
  comes `source <path> <sha256>` for each of the corpus's own programs,
  and for each image one of `image <path> <sha256> library <name>`,
  `image <path> <sha256> source <path> [format <fmt>]`, or `image <path>
  <sha256> compiled <source> format <fmt> steps <K> target <t> params <n>
  [<name> <literal>] ...`, cftc's compile with its run's params.
- A block for each case follows:
  - `case`, then `what`, a sentence for a person;
  - `certificate <path> <sha256>`, and `version 1` or `version 2`, the
    certificate's format version;
  - `mode`, and for a keyed case `salt <path> <sha256>`;
  - `depth`, and `backends any` or `backends software`;
  - `writers both` or `writers golden`. `both`: the golden writer and a
    C writer each make it (version 2's C writer from its C half on).
    `golden`: a control, made by corpus.py from its case by one edit;
  - `accuracy 0 none`, or `accuracy <A> both` when the case has A
    entries. `both` says both writers make them: the golden writer, and
    cft-segrun handed each entry's definition, each held to the
    committed bytes. Until step 5 the word was `golden`, the golden
    writer's alone;
  - `verdict accepted` or `verdict refused <name>`;
  - `states <dir>` and `blocks <dir>`, where the boundaries and the
    blocks handed are;
  - what the audit is handed besides: `signature <path> <sha256>` or
    `signature none`, the same for `keyring`, `superseded <case>` or
    `superseded none`, `define none`, `define <run>:all` or `define
    <run>:<k>,<k>...` for a definition re-run, and `regenerate no` or
    `regenerate yes`;
  - `runs <R>`.
  A version-1 case is handed nothing of version 2's: `writers both`, its
  blocks its states, and the rest `none` or `no`.
- Each run follows its case's lines:
  - its `run` line as the certificate spells it;
  - `image <path>`;
  - `bank <path> <sha256>` or `bank none`;
  - `source <path> <sha256>`, the source its audit is handed, or `source
    none`;
  - `segments`, `steps`, `parameters` and each `parameter`;
  - a `boundary <b> <sha256>` line for each boundary, the SHA-256 of the
    state file's bytes, not the certificate's tagged hash;
  - in a run with blocks, a `block <k> <sha256>` line for each segment's,
    and a `raw <k> <sha256> <sha256>` line for each replayed segment's
    raw end state and raw block.
- corpus.py's `read_manifest` reads it strictly and names the line of
  any departure. Another gate may import it: `programs/estimates.py`
  does, and scores version 1's cases alone.

**As a regression test.** `make -C host corpustest` runs `corpus.py check
--tool ./cft-segrun`, and verify/run.sh's `programs` stage runs it beside
the segment runner's gate (the lead's decision, 2026-09-29). For each
case it holds:
1. every file against its SHA-256, and no file under `certificates/` that
   the manifest does not name, so an edited or added file fails by its
   name;
2. every image against its source, assembled again;
3. the golden writer making the committed bytes again, byte for byte:
   - `run_chain` and `certify_run` at the case's depth;
   - each accuracy value derived again, under the definition the
     committed entry states;
   - `encode`, handed the committed certificate's identity lines;
4. every boundary of the golden chain against its committed file;
5. cft-segrun, on the software backend at the case's depth, writing the
   committed certificate normalized in two places and in nothing else:
   - its `build-id` line is what the binary's own `--build-id` prints,
     and its hash line is computed again over that body;
   - the three accuracy cases (lorenz63-rk4-fp64, henonheiles-lf-fp256
     and example) are made WHOLE. The tool is handed each entry as the
     committed certificate defines it: its method, run, scope, quantity
     and terms, and its value's form, never its value. It makes every
     value again. Until step 5 their accuracy block was replaced by
     `accuracy 0`, the block the tool wrote then;
   - why nothing else may differ: every other line is a function of what
     the manifest fixes (the image, bank, initial state, segments,
     steps, parameters, mode and salt, and depth), of the entries'
     definitions, and of the backend, which the gate fixes to software.
     `build-id` names the library build, which changes with every commit
     by design, and the hash line covers it;
   - its boundary files are the committed ones;
6. the golden audit giving the case its expected verdict, in full from
   the initial states alone, and sampled from the committed states with
   its seed printed;
7. the case named `example` being this page's example certificate.

For a version-2 case it holds 1 and 2 as above, and then:
3. the golden writer making the committed bytes again: cert2's
   `run_chain` with each block, every marked lane replayed by the
   source's definition, and `certify_run`; each accuracy value derived
   again; and `encode`, handed the committed certificate's header lines
   and each run's statements of its source (its name, compiler and
   params);
4. every boundary, block and raw file of the golden chain against its
   committed file, and the signature made again by the test key;
5. cft-segrun remaking each case marked `writers both` (version 2's C
   half, 2026-10-02), on the software backend. It writes every line but
   its own measurements byte for byte: `build-id`, `writer`,
   `writer-runtime`, `compiler-build`, the `replay-method` lines, the
   three times, `host-os`, `host-arch` and the environment, and the four
   device lines only where the case carries a card's values
   (signed-fp64): `none`, which a software run writes there, is held.
   It is handed the header's statements, as the golden writer is:
   `certificate-id`, `issuer`, `issuer-key`, `supersedes` and `initial`,
   in their own spelling, and each run's lane-flags word. For each run
   that names a source the check compiles it with cftc at the run's
   format, steps, target and source params, and hands the tool that
   compile's manifest and, where the run replays a marked lane, its image
   and bank as the replay image. Its boundary, block and raw files must be
   the committed ones; signed-fp64, the tool writing its body, is signed
   by `python/cft_sign.py` with the published test key and verified with
   the committed keyring. A check counts the seven remade, and without
   `--tool` each remake is a SKIP by name;
6. the golden audit giving the case its verdict, handed what the manifest
   says: the sources, the blocks, the signature and keyring, the
   superseded certificate, the definition re-run and the regeneration.
   It audits in full from the initial states alone, or from no state
   where the case regenerates, and for a case a writer makes, sampled
   from the committed states too;
7. `markstep-fp64` being this page's version-2 example.

A control is held to its recipe instead of a writer: its certificate is
its case's with its edit made again, byte for byte, its own files and its
manifest entry are the recipe's, and its audit refuses it by its
verdict's name.

It is 156 checks, 21 to 32 s on the Windows desktop, niced. The
slowest was with the desktop at about 77 % from other work (2026-09-29).
With the fixes round's cases it was 21 to 23 s (2026-09-30), and with
the tool making the accuracy cases whole, 22 to 25 s (2026-09-30). With
version 2's cases it is 288 checks, 28 and 32 s on the desktop, niced,
with it 4 to 10 % busy; without the tool, version 1's twelve remakes skipped by
name, 239 checks in 27 and 29 s at 2 to 6 % (2026-10-02). With cft-segrun
remaking version 2's seven cases too: 311 checks, 0 failed, 28 to 32 s on
the desktop, niced, at 6 to 10 % (2026-10-03).

**Changing it.** A change that moves any byte of the corpus fails the
gate by name: a change to the model, a hash, an encoding, the assembler's
output, or the `programs/` sources and banks the corpus names. When the
change is meant, its commit runs `corpus.py make` with a clean build of
cft-segrun, and says so. `make` keeps a case's committed certificate,
byte for byte, where the one it makes equals it but for `build-id` and
the hash line, and every boundary file has the committed manifest's
digest. So a case's bytes, and the commit its `build-id` names, move
only when what it certifies does (the fixes round, 2026-09-30). `make
--rewrite-all` writes every certificate the tool makes. `make
--keep-version-1` keeps every version-1 case as committed, its files
untouched and no tool needed, and writes version 2's cases and controls
again: version 2's are the golden writer's, and corpus.py's recipes
make them.

**Its producer.** `make` refuses a tool whose build is not clean, so each
certificate names a commit anyone can check out. Every certificate but
`example`'s was written by cft-segrun built clean from one of two
commits, and its `build-id` says `tracked=clean untracked=none`:
- 0b8ea10, the commit that added `--scratch-depth`, wrote the six ODE
  cases', flagstep's and half-init's (2026-09-29);
- df06c14, the commit whose `make` keeps a certificate its remake
  equals, wrote augsum's and the two deepwrap cases' (2026-09-30). That
  `make` kept the other nine.

The two accuracy cases cft-segrun writes, lorenz63-rk4-fp64 and
henonheiles-lf-fp256, carry the golden writer's accuracy block, as
written at 0b8ea10. Since step 5 the tool makes the same block, and
`make` refuses a case whose entries are not the golden writer's, value
for value. So `make` kept both certificates byte for byte (2026-09-30).
`example`'s is the golden writer's, with the identity this page prints
(`build-id unknown`), and the check holds cft-segrun's to it but for
`build-id`.

Version 2's cases are the golden writer's, written by `make
--keep-version-1` at the commit that added them (2026-10-02). Every
measured header line is `unknown`, as the example's `build-id` is, but
in `signed-fp64`, which spells each out.

**As a conformance test.** Another implementation (another library, a
GPU library, a tile) takes each case's images, banks and initial states
from the manifest. It runs every run's segments at the case's depth and
writes a certificate. It conforms on the case when its certificate
reproduces:
- every run block, from `run` to `output`, byte for byte;
- every accuracy value, where it writes accuracy;
- and its boundary states are the committed files.

The streams are +0 in every case, and the manifest does not state them.
Its identity lines name it, and are not compared; neither is the hash
line, which covers them. The other lines - the magic line, `mode`,
`salt-commitment`, `runs`, the accuracy entries' definitions and `end` -
follow from the recipe and the grammar; this rule does not name them.
The other rules:
- **Depth.** A case's depth is its runs' `scratch-depth` parameter where
  they state one, and 256 otherwise. A tile states its depth in CAPS2
  and writes no such parameter. So a tile of a case's depth conforms
  when its run blocks equal the committed ones with that parameter taken
  out and the parameter count one less. Every case but the two deepwrap
  ones has the same chain at 256 and at 2,048 (by the golden model, not
  a card run), so a 2,048 tile conforms on every case but
  deepwrap-fp64-256, and refuses augsum-fp64 (below). Each deepwrap
  case's chain is its own depth's alone: at every other power of two
  from 4 to 32,768 the chain differs, and at 1 and 2 the image does not
  load. So a tile of any other depth that loads it fails each of them.
- **Revision 8.** A tile without revision 8 refuses `augsum-fp64` at
  load, by name, and that refusal is its conforming answer.
- **Auditors.** An auditor conforms when it gives each case its
  `verdict`, in full and sampled. The audit tool's gate holds
  `cft-audit` to that, beside the golden auditor ("The audit tool",
  its fourth section). A version-2 auditor is handed what the case's
  manifest lines say, and gives every control its verdict too.
- **Version 2.** A version-2 implementation conforms on a case marked
  `writers both` when, handed the header's statements, it reproduces
  every line but its own measurements (the regression test's step 5
  names them): every run block, its source lines, lane flags and replays
  included, and every accuracy value. Its boundary, block and raw files
  are the committed ones. It may replay a marked lane by an image of its
  own, which its `replay-method` line names.

The corpus is described here and committed in this repository, and
published nowhere else. Publishing it outside this repository needs
Logan's permission.

**What it does not hold yet.**
- A certificate made on a tile. The lead's, later: a deepwrap case from
  the revision-7 single, whose CAPS2 reads 2,048, would join with the
  card's device lines.
- One made through a remote handle.
- Streams other than +0, which cft-segrun does not take.
- A version-2 certificate as a C writer made it, committed: since
  version 2's C half (parcels CV2CW and CV2CA, 2026-10-02) the check has
  cft-segrun remake the seven `writers both` cases and holds them to the
  committed ones, and cft-audit audits every version-2 case and control,
  handed what the manifest hands but the source and the regeneration,
  giving the golden auditor's verdict for the same ("The audit tool").
- A replay decided through mpmath: no node of the language reaches it
  yet, so `definition-unavailable` and `replay-undecided` have no
  committed case.

## What version 1 does not do

- **Sign.** The detached signature is reserved, and version 1 defines no
  scheme. Version 2 defines one, which signs a version-1 certificate too.
- **Carry a bound.** No version-1 method has a rigorous remainder.
- **Carry a value that is not an exact rational.** Every version-1
  method's value is a polynomial in exact states, or a difference of
  them, and so exact. A quantity through a square root or a division by
  a state - cft-orbits' energy - needs a method a later version defines,
  rounded or enclosed and named so.
- **Certify deposits,** lane masks, index tables, or streams that
  change from segment to segment. A run is dense and its streams are
  fixed. A producer that needs any of these cannot be described: the
  golden writer has no way to take a mask, a table or a stream per
  segment, and it refuses a program that deposits (`program-shape`)
  rather than certify part of it.
- **Certify cft-orbits' exact route, or give its runs any accuracy entry
  but the angular momentum's drift.** Its Newton-route runs are
  certified, each sample interval a segment of one image, and they can
  carry the drift of each component of their angular momentum, exact
  (2026-09-30; [ORBITS.md](ORBITS.md), "Certified runs"). The default
  exact route has no image: its divide and square root are host calls
  between program runs, and certifying it needs an orbit integrator in
  the golden model. No auxiliary run can be related to an orbits run,
  since its constants ride in its image and are derived in each format.
  Its energy is not a polynomial in the state.
- **Record a remote run's scratch depth.** The remote protocol carries
  no CAPS2, so a certificate made through a remote handle reads
  `device-caps unknown` and is re-run at 256 (revision 7, "The chain").
  A run that indexed past 256 on a deeper server, or held a state wider
  than 256 slots, fails its own audit rather than passing, unless its
  runs state the server's depth by their `scratch-depth` parameter. A
  certificate made on the software backend is re-run at 256 too, unless
  its runs state a depth that way ("The chain"). cft-segrun states one
  in every run block when it is given `--scratch-depth N`, which it
  takes for the software backend only.

## Version 2

Version 2 says what a run MEANS, where version 1 says what the machine
did. Logan decided its design on 2026-10-02, as twelve recommendations:
"Regarding the 12 questions, the recommended solutions are appropriate as
stated". This part of the page is the whole of version 2. Every section
above is version 1's and stays its contract; where version 2 keeps a rule
of version 1's, this part says so and does not restate it.

A version-2 certificate adds five things to version 1's:
- **the per-lane flags** of every segment (docs/SEQUENCER.md, R23), as a
  hash a segment;
- **marked lanes replayed.** A routine that cannot decide a lane's last bit
  marks the lane (R24). Version 2 replays each marked lane by the program's
  definition and certifies the corrected segment, with the machine's raw
  segment on a replay line. So a version-2 chain is the definition's
  wherever it stands;
- **the source** a run was compiled from, or is defined by, checked by
  recompiling or by the language's interpreter, and `wider-source`, the
  same source compiled one format wider;
- **the definition** it is claimed under: the conformance profile
  (CONFORMANCE.md, now versioning the program model) and the language's
  version. A failure under an auditor whose definition does not cover the
  certificate's is that auditor's own limit, `definition-differs`;
- **provenance**: who issued it and with which key, when, on what host, by
  which writer and compiler build, on which device, in which environment,
  from which initial state, replacing which certificate. Each is reported,
  never checked, and the issuer and the device's serial are written only
  on request. A detached Ed25519 signature, defined here, signs a
  certificate of either version.

**Version 1 stays the format for the machine's own values.** A run with a
marked lane is certified under version 1 as its STATUS says: STATUS[6] set,
re-derived by the audit, and not replayed (the lead's decision,
2026-10-02). Version 1's certificates stay as they are: the corpus's,
cft-orbits', and every run whose producer wants the machine's values. A
version-1 certificate is never made version 2. Re-certifying a run writes a
new certificate, which may name the old one in `supersedes`.

Where things stand (2026-10-02):
- the golden implementation is `python/cft_golden/cert2.py`: the reader,
  the writer, the replays, the sources, the signature and the audit.
  `cert.parse` and `cert.audit` choose by the magic line, so version 1's
  reader is untouched. Version 1's golden writer and audit gained one
  rule with version 2, the wider run of a routine image (`aux-image`),
  which changes their verdicts for routine images alone;
- its gate is `python/tests/test_cert2.py`, with a negative control for
  each check below, caught by name ("Version 2's controls");
- Ed25519 is `python/cft_golden/ed25519.py`, held to RFC 8032's test
  vectors by `python/tests/test_ed25519.py`, and the key tool is
  `python/cft_sign.py`;
- the profile's version lives in `python/cft_golden/profile.py`, and the
  language's in `python/cft_golden/lang/version.py`;
- `cft-audit` reads both versions and audits version 2 in C since its C
  half (parcel CV2CA, 2026-10-02): every step that needs no source, with
  Ed25519 and SHA-512 in C, and `source-missing` where a step needs one
  ("The audit tool"). `host/tests/audit_check.py` holds it to the golden
  auditor on every parse call test_cert2.py makes and every audit call
  whose arguments files and options can carry, and on every version-2
  case and control of the corpus, the golden auditor handed no source as
  the tool is;
- `cft-segrun` writes version 2, its default since version 2's C half
  (parcel CV2CW, 2026-10-02), and version 1 with `--format-version 1`
  ("The segment runner"); libcft names the device's extra lines at ABI
  0.18; and the corpus check has cft-segrun remake every case a C writer
  makes ("Golden certificates").

### What a version-2 certificate says

**The statement.** "These bits are what this program means: its
definition's values from these inputs and parameters, every lane its
routine could not decide replayed by that definition, under this profile
and this language. The machine's own values, where they differ, are these
replay lines. The run was compiled from, or is defined by, this source.
Its accuracy is this, of this kind. The issuer says the rest."

**What an audit proves,** beyond version 1's "What an audit proves":
- for every segment it re-runs, the segment's per-lane flags, through
  their hash;
- for every re-run segment in which the machine marked a lane: which lanes
  it marked, and its raw end state and flags before any replay, through
  the replay line; and that each marked lane's certified values are
  exactly what the definition computes from the lane's certified start;
- for each run whose source it was handed: that the source is the one
  named, that the language accepts it at the run's format, its step graph,
  its params, and, where a compiler is named, that the image and bank are
  that compiler's compile of it;
- that a wider-source run is the main run's source compiled one format
  wider, run from exactly widened inputs;
- where the auditor chooses, that the source's interpreter itself ends a
  segment on its certified state with its certified flags (the definition
  re-run);
- with a signature file handed, that the holder of the key named in it,
  a key not of small order, vouched for these bytes; with a keyring,
  whose key it is;
- with the superseded certificate handed, that it is the one named.

**What it does not prove.** Any provenance line: a time, a place, the
issuer without a keyring, the writer, the environment, the device's
platform, XRT, clock or serial. Each is reported as stated and not
checked, unknown, none or withheld. Nor that a key belongs to a person:
the keyring is the auditor's own. Nor when a signature was made.

### Version 2's lines, in order

The file is version 1's ("The file"): printable ASCII and LF, tokens
separated by one space, a body ending in `end`, then the hash line. Lines
marked (K) appear in a keyed certificate only. Groups repeat as their count
says.

**The header.**

| line | values |
|---|---|
| `cft-certificate 2` | the magic line |
| `mode`, `salt-commitment` (K) | as in version 1 |
| `build-id`, `backend`, `device-xclbin`, `device-version`, `device-caps`, `device-tiles` | as in version 1 ("Identity") |
| `profile <version>` | the conformance profile the bits are claimed under; or `unknown` |
| `language <version>` | the language's version; `none` where no run names a source, and only there (refused `malformed` at a run's source line beside it); or `unknown` |
| `device-platform <text>` | the card's platform (shell) name as XRT reports it; `none` for the software backend; `unknown` |
| `device-xrt <text>` | XRT's version; `none`; `unknown` |
| `device-clock <n>` | the kernel clock in Hz, a decimal of at least 1; `none`; `unknown` |
| `device-serial <text>` | the card's serial; `none`; `unknown`; `withheld`, the writers' default |
| `writer <name> <build>` | the program that wrote it (`cft-segrun`, `cft-orbits`, `golden`) and its build in `build-id`'s grammar or `unknown`; or `writer unknown` whole |
| `writer-runtime <text>` | the golden writer's Python, and mpmath's version wherever it evaluated the definition (`python-3.12.9,mpmath-1.3.0`); `none` for a C writer; `unknown` |
| `compiler-build <build>` | in `build-id`'s grammar, the build of the compiler that made the runs' images; `none`; `unknown` |
| `replay-methods <n>` | how many `replay-method` lines follow |
| `replay-method <r> golden` or `replay-method <r> image <digest>` | how the producer replayed run r's marked lanes: by the golden model, or by a replay image (its SHA-256); one line for each run with replay lines, runs strictly increasing |
| `certificate-id <text>` | an identifier the issuer assigned before writing; `none` |
| `issuer <text>` | who issues it: a name, an ORCID for a person, or an organisation's identifier; `none`; `withheld`, the writers' default |
| `issuer-key <key>` | the Ed25519 public key it is to be signed with: a point of the curve (`malformed` where it encodes none) and not of small order (`signer` where [8]A is the identity); `none` |
| `host-os <text>` | the host's OS by name (`linux`, `windows`), with its version only on request (`linux-6.8`, the kernel's for Linux); `unknown`; `withheld` |
| `host-arch <text>` | the host's architecture (`x86_64`); `unknown`; `withheld` |
| `started <time>` | when the first run began; `unknown` |
| `finished <time>` | when the last run ended; `unknown` |
| `issued <time>` | when the certificate was written; `unknown` |
| `supersedes <digest>` | the body hash of a certificate this one replaces; `none` |
| `environment <n>` | how many `env` lines follow |
| `env <name> <text>` | a variable of the writer's list that was set, and its value; names strictly increasing, and a name off the list `malformed` |
| `initial given`, or `initial generator <name> <text> ...` | how run 0's initial state was made: handed as data, or by a named generator, whose name is never one of the four words, and at most 16 arguments |
| `runs <R>` | as in version 1 |

**A run block,** R of them. Run 0 is the main run.

| line | values |
|---|---|
| `run <i> main`, `run <i> half-step h-slots <n> <slot> ...`, `run <i> wider` | as in version 1 |
| `run <i> wider-source` | an auxiliary run: the main run's source compiled one format wider |
| `program-format`, `program-image`, `program-digest` | as in version 1 |
| `source <digest>` or `source none` | the SHA-256 of the source file's bytes; `none` is version 1's run, which names no source |
| `source-name <text>` | with a source only: its file name, without directories; or `none` |
| `graph <digest>` | with a source only: the SHA-256 of its step graph's canonical bytes at the run's format |
| `compiler none` or `compiler <name> <n> <text>` | with a source only: `none` where the image is not claimed to be the source's compile; else the compiler's name, its output version and the target (`compiler cftc 1 u50-rev7-quad`) |
| `source-params <p>`, then p lines `source-param <name> <literal>` | with a source only: the run values given for the source's params, names strictly increasing in byte order, each literal the language's canonical spelling of its value |
| `lanes`, `steps`, `stream-a`, `stream-b`, `stream-c`, `parameters`, `parameter` | as in version 1 |
| `lane-flags yes` or `lane-flags no` | whether the run asked for the per-lane block |
| `segments <S>` | as in version 1 |
| `segment <k> start <h> end <h> flags <n> status <n>` | as in version 1, the corrected segment ("A marked lane and its replay"); with `lane-flags yes` it ends in two more tokens, `lanes <h>`, the hash of the segment's block |
| `replays <m>`, then m lines `replay <k> marked <n> changed <c> raw-end <digest> raw-lanes <digest>` | one line for each segment in which the machine marked a lane, segments strictly increasing |
| `output <digest>` | as in version 1 |

**The accuracy block** is version 1's, with a fourth method, `entry <j>
wider-source`, of kind `estimate`, which uses a wider-source run. **The
end** is version 1's: `end`, then `hash`.

**The words.** A field with no value holds one of four words, and a text
is never one of them:
- `unknown`: the producer did not record it;
- `none`: the field does not exist for this producer;
- `withheld`: the producer has the value and chose not to publish it;
- `given`: run 0's initial state was handed as data (`initial` only).
Each line takes the words its table cell lists, and no other. A word on a
line that does not take it is `malformed`.

### Version 2's encodings

Version 1's encodings stand: a decimal, a digest, a register word, an
element, a rational, a word and a name. Version 2 adds six, each with one
spelling:
- **A text** is a value's UTF-8 bytes, percent-encoded as URIs encode
  them. A byte from 0x21 to 0x7E other than `%` stands as itself. Every
  other byte is `%` and two uppercase hex digits: a space, `%` itself, a
  control character, a byte of a non-ASCII character. A byte that may
  stand as itself is never encoded, the bytes decoded are UTF-8, and the
  token is 1 to 255 characters. So `Logan W.` is `Logan%20W.` and `100%`
  is `100%25`. A writer refuses a text equal to one of the four words
  (`malformed`).
- **A time** is `YYYY-MM-DDTHH:MM:SSZ`: UTC, a real Gregorian date, hours
  00 to 23, minutes and seconds 00 to 59, `T` and `Z` in upper case, no
  fraction and no other offset. It is one spelling of RFC 3339's
  `date-time`. A leap second (60) is refused, as SOURCE_DATE_EPOCH counts
  none.
- **A version** is a major in decimal, then `.` and a minor where the minor
  is not 0: `1`, `1.2`. Each part is at least 1, at most 2^63 - 1, with no
  leading zero. So `1.0`, `01` and `0` are refused.
- **A key** is 64 lowercase hex digits: an Ed25519 public key.
- **A variable's name** is an uppercase letter, then uppercase letters,
  digits and `_`, at most 64 characters. Its value is a text, and a
  variable set to the empty string counts as unset (libcft's rule).
- **A param's name** is the language's: a letter or `_`, then letters,
  digits and `_`. Its literal is a token the audit holds to the language's
  canonical spelling ("Sources").

A writer's and a generator's names are version 1's names, and never one of
the four words. A build is `build-id`'s grammar ("Identity").

### Hashes in version 2

Version 1's tags are kept. A state, a stream and the salt's commitment hash
exactly as in version 1, so one run's version-1 and version-2 certificates
carry the same state and stream hashes, and the corpus holds both to one
set of boundary files. A replay line's raw end is a state, under the state
tag. Two new objects take new tags:

| what | tag |
|---|---|
| a segment's per-lane flags | `cft-certificate 2 lane-flags` then 0x00, then the block's n bytes, lane i's at byte i |
| a signature's message | `cft-signature 1` then 0x00, then the 32 bytes of the body hash |

A block's hash is keyed as a state's is: HMAC-SHA-256 under the salt in a
keyed certificate, plain SHA-256 in an open one. The body hash covers
every line, so it covers each block, each replay line's two hashes and
every source line. The test vectors are under "Version 2's example and
test vectors".

### The per-lane flags

**What a run gives** (docs/SEQUENCER.md, R23). One byte a lane: [4:0] the
five IEEE flags the lane raised outside every quiet region, in FLAGS's
order; [5] its deposit overflowed; [6] its strict access fell past the
depth; [7] a raise marked it. So [7:5] are STATUS[6:4] one place up. Over
the lanes a run owns, the OR of [4:0] is FLAGS, the OR of [6:5] is
STATUS[5:4], and the OR of [7] is STATUS[6]. A run asks for the block with
MODE[24], at ABI 0.17 through `cft_run_args.lane_flags`, and over the
remote protocol through PROG_RUN_EX's `want` word. A segment yields one
block.

**The lines.** `lane-flags yes` says the run asked for the block, and then
every segment line ends in `lanes <h>`, its certified block's hash.
`lane-flags no` is version 1's run, and its segment lines end at `status`.
A pair where the run says `no`, or none where it says `yes`, is
`malformed`. No lane's byte is in the clear: a block is n bytes a
segment, which as hex would be twice the size of every state. A run's
flag word and STATUS stay in the clear, as in version 1.

**When a run asks.** A writer asks for the block whenever the image needs
flag control (CAPS2[14]: any QUIET, ENDQUIET or RAISE), since a mark alone
does not say which lane, and otherwise as its producer chooses. The chain
does not change: a block is an output of its segment, not an input to the
next.

**Beside the certificate.** A writer writes each segment's block into the
states directory as `run-<r>-segment-<k>.flags`, n bytes, beside the
boundaries. A person reads them to find which lane raised invalid. An
auditor need not be handed them, since a re-run recomputes each block.

**What the audit checks.**
- At step 7, each block handed: its size is the run's lanes, and it belongs
  to a segment that exists of a run that says `yes`
  (`lane-flags-shape`); its hash is the segment's (`lane-flags-hash`); and
  R23's identities against the segment line, which need no re-run
  (`lane-flags-identity`): the OR of its bytes' [4:0] is the flag word, the
  OR of their [6:5] is STATUS[5:4], and no byte carries [7], since a
  certified block's marks are resolved. So a sampled audit handed the
  blocks checks every segment's block, re-run or not.
- At step 9, each re-run segment's block is computed with the segment, a
  block of lanes at a time, as its end state is, and must hash to the
  certified value (`segment-lane-flags`).

### A marked lane and its replay

**What happens on the machine.** A correctly rounded routine runs inside a
quiet region and tests in-lane whether its last bit is decided. It raises
its operation's flags, with bit 7 set where its test failed, and the mark
sets the lane byte's [7] and STATUS[6]. A quiet region never silences a
mark. A marked lane's values are the routine's best guess, not necessarily
the correctly rounded ones.

**What a segment line means.** In version 2 a segment line is the
DEFINITION's segment: what the source's reference interpreter computes.
- Where no lane was marked, that is the machine's own run, and the line
  means what it meant in version 1.
- Where a lane was marked, the line is the corrected segment:
  - each marked lane's end values are the definition's, from the lane's
    certified start;
  - each marked lane's byte is the definition's five flags in [4:0], the
    raw [6:5], and [7] clear;
  - the flag word is the OR of the corrected bytes' [4:0], and STATUS is
    the raw STATUS with STATUS[6] cleared;
  - the machine's raw result goes on a replay line, one for the segment
    however many lanes it marked.
- So the chain holds the definition's states throughout. Continuity keeps
  version 1's rule, an accuracy entry reads correct states, and a lane
  marked once runs on the fast image from the next segment.

A version-2 segment line's STATUS never carries STATUS[6]: the reader
refuses it, `marked`. A producer who cannot replay, because it has no
source to name or no replay route, writes version 1.

**The replay line.** `replay <k> marked <n> changed <c> raw-end <digest>
raw-lanes <digest>`:
- k is the segment, strictly increasing over the run's lines, below S;
- `marked` is how many lanes the machine marked there, 1 to the run's
  lanes;
- `changed` is how many of those the replay changed, 0 to `marked`: a
  marked lane whose end values (its slice of the end state) the definition
  moves. It counts how often the routine's undecided guess was in fact
  wrong, and it is for a person and for measuring routines;
- `raw-end` is the hash of the segment's raw end state, before any replay,
  under the state tag;
- `raw-lanes` is the hash of the segment's raw block, under the block's
  tag. The marked lanes are its bytes with [7] set.

**The method,** in the header: `replay-methods <n>`, then one line for
each run that has replay lines, `replay-method <r> golden` or
`replay-method <r> image <digest>`. They are reported, and they sit in the
header because two writers of one run make them differently.

**Form rules,** which the reader checks with no inputs:
- a segment line's STATUS carries no STATUS[6] (`marked`);
- a run with replay lines says `lane-flags yes` (`replay-lane-flags`) and
  names a source (`replay-source`), each refused at its `replays` line,
  `replay-lane-flags` first, after the count has been held to its lines;
- `changed` is at most `marked`, `marked` at least 1 and at most the run's
  lanes, and a replay's segment below S (`malformed`);
- the runs with replay lines are exactly the runs the header's
  `replay-method` lines name (`replay-method`). A method line for a run
  without replay lines, or for no run, is refused at that line; a run with
  replay lines and no method line, at its `replays` line.

**Where the replay is made.**
- **The arbiter is the golden model.** A replay of lane i is
  `lang.run` of the source's step graph at the run's format, with the run's
  source params and h (h/2 for a half-step run), on lane i's certified
  start values for the segment's `steps`. Lanes do not interact, so a lane
  run alone is the lane as it is in the run. Each node is evaluated by its
  golden function: a division and a root by softfloat's, and a
  transcendental, when the language has one, by `transcend.py`'s.
- **A slower image is a producer's shortcut.** An image of the same source
  compiled with a more accurate routine, run over the marked lanes. A C
  producer has no interpreter of the language, so it replays that way. Its
  answer is accepted exactly when it is the definition's, lane by lane:
  the audit always replays by the definition, whatever the producer used,
  so a replay image is never handed to an auditor.
- **The lane's layout.** A lane of the image's scratch block is the
  graph's lane: its state, then each tangent vector's components, then its
  lane params, which is cftc's layout and the interpreter's. A run whose
  image's slots a lane are not that is refused `source-shape` by writer
  and audit alike.

**Beside the certificate.** For each segment with a replay line, a writer
writes the raw end state and the raw block, as
`run-<r>-segment-<k>-raw.bin` and `run-<r>-segment-<k>-raw.flags`, and it
may copy the source as `run-<r>.cftl`. A re-run recomputes the raw values,
so an audit needs none of them.

**The binding.** A replay record carries no golden value. The source and
its graph are named by digest, the definition by `profile` and `language`,
and each marked lane is replayed from its certified start, which the
segment's start hash binds. The values the definition computes are spliced
into the re-run's raw end, and the result must hash to the segment's `end`;
the corrected block must hash to its `lanes`. So a replayed lane's
certified value is its slice of the end state, bound by the end hash, and
the audit checks that it is exactly what the golden functions compute
through the interpreter. Correct rounding makes a value unique only under
one contract, which is why the definition is named ("The definition").

### Sources

**Two relations.** A run that names a source stands in one of two
relations to it:
- **compiled from** (`compiler <name> <n> <target>`): the image and bank
  are what that compiler, at that output version, makes of the source for
  that target, with the run's steps and source params. Compilation is byte
  for byte deterministic, and one image serves every target that accepts
  it, so the target decides only acceptance. This is checked by
  recompiling;
- **defined by** (`compiler none`): the run computes what the source's
  reference interpreter computes. This is checked by running the
  interpreter, the definition re-run, at the auditor's choice. It holds for
  a hand-written image, if that image is right. Without the definition
  re-run the audit checks the source itself (step 4a) and compares the
  image with it only where a marked lane is replayed, so an image of
  another map - a constant 3/5 where the source says 3/4 - passes there.
  The verdict's source line says so: "no compiler named, so the image's
  map is not re-derived from it - only a marked lane's replay and a
  definition re-run compare the two" (verifier-VCV2B). The re-run costs
  every lane the definition's interpreter, so the auditor spends it only
  by choice, as version 1's audit spends a full re-run.

**The format.** The source is taken at the run's `program-format`: a main
run's format must be the source's own (`source-format`), and a
wider-source run's is one rung up. The rung up is the format override: the
source with its format statement's value replaced, which the language and
cftc both take (`--format`).

**Naming is optional.** A run may write `source none`, and gives up its
replays and any wider-source run. A run with replays, and a wider-source
run and its main run, name a source. The source's digest is unkeyed in
both modes, as the program digests are, so a reader can confirm a guessed
source: the keyed mode protects neither the program nor its source.

**The source param's literal** is the language's canonical spelling of
its exact value (LANGUAGE.md, "The intention-out"): a decimal within 24
significant digits, a hexadecimal significand for a longer dyadic value,
otherwise `p` or `p/q`. So `29` and `1/2` stand, and `29.0` and `0.50`
are refused at the audit (`source-param`), whose reading of a literal is
the language's.

**`steps`** is checked where a compiler is named (it is the image's REPEAT
count) or a definition re-run or replay is made (it is the definition's
step count). It stays reported elsewhere, as in version 1.

**What the audit checks** (step 4a), for each run that names a source the
audit was handed, in this order:
1. its SHA-256 is the run's `source` (`source-digest`);
2. the language accepts it at the run's format (`source-refused`, the
   language's own refusal named in the sentence);
3. a main run's format is the source's own (`source-format`);
4. its step graph's SHA-256 at the run's format is the run's `graph`
   (`source-graph`);
5. each source param names a param of the graph, its literal is the
   canonical spelling of its value, and the language accepts the value for
   that param at that format (`source-param`);
6. the image's slots a lane are the graph's lane (`source-shape`);
7. where a compiler is named, the auditor's compiler compiles the source
   with the run's steps, source params, format and target. The image, and
   but for a half-step run the bank, must be the run's. A half-step run's
   bank is its relation's to check (step 8). Where they are not:
   `source-image` when the auditor's compiler is the named name and output
   version, since the claim is then false; `compiler-differs` otherwise,
   the auditor's own limit. A target the auditor's compiler does not have,
   and a source it refuses for that target, are judged the same way.

A source handed for a run that names none, or in another shape than
{run: bytes}, is `source-digest`. A source named and not handed is
reported "named, not handed - stated, not checked", and a later step that
needs it refuses `source-missing`: a replay, a wider-source relation, a
definition re-run. The recompile costs the compiler's time, bounded by the
source handed.

### The wider-source run

`run <i> wider-source` is the main run's source compiled at the next rung,
with the same steps, source params and target, from exactly widened
inputs. Its relation is checked at step 8, in this order:
- `aux-format`: the next rung; at fp256, the top of the ladder, refused;
- `aux-lanes`: the main run's lanes;
- `aux-source`: both runs name the source and a compiler, and they are the
  same source digest, source params, compiler name, output version and
  target;
- `aux-image`: the same steps a segment, then the recompile at the next
  rung, which step 4a made (`source-missing` where the source was not
  handed), then the main run's scratch depth;
- `aux-segments`: the main run's segment count;
- `aux-streams` and `aux-start`: the main run's streams and initial state
  exactly widened, as for version 1's wider run.

An entry `entry <j> wider-source`, of kind `estimate`, uses a wider-source
run. Its value is version 1's wider function: the largest absolute
difference over the slots between run 0's final state and the run's.

**Why both kinds stay.** Version 1's wider run carries the main bank's
constants exactly widened, so it estimates the rounding of the arithmetic
on those constants. The wider-source run rounds h, h/2 and h/6 once at the
wider format, so it estimates the rounding relative to the system as
written, the constants' rounding included. On Lorenz-63 at fp64 the two
differ by about 3.5e-15 at t = 3, the time shift of h's rounding. Neither
is a bound. A program with a routine has only the wider-source run.

**A routine image has no version-1 wider run.** A main image holding any
QUIET, ENDQUIET or RAISE (a routine's flag control) is refused a `wider`
run, `aux-image`, by every writer and every audit, of either version
("Auxiliary runs"). A routine's words are format-specific, so its words
one rung up can pass the wider relation and compute nothing the main run
means.

**The other relations' source lines** (`aux-source`, at the place it
holds in each: after `aux-lanes`). A half-step run's source lines are the
main run's, all of them, and a wider run names no source: its relation is
to the main image. Where the main run was compiled from a source the audit
was handed, a half-step run's h-slots must be exactly the slots the
recompile names as carrying the step (`aux-h-slots`): the step halved, all
of it and nothing else. That turns version 1's "not proved" into a check.

### The definition

A certificate names the definition its bits are claimed under, in two
header lines:
- **`profile`**: the conformance profile (CONFORMANCE.md, "Versioning").
  Since 2026-10-02 it versions the program model too: any change to what
  an accepted image computes, or to whether an image loads, steps it. The
  golden model states it, and the tree is at profile 2;
- **`language`**: the language's version (CONFORMANCE.md, "The
  language's version"), kept in the golden model and stepped by the same
  rule for sources: a major step whenever an accepted source is refused
  or computes another thing, a minor step for an addition that changes
  none. It starts at 1. A certificate whose runs name no source writes
  `none`.

**Coverage.** An auditor's definition covers a certificate's when, for
each of the two, the majors are equal and the auditor's minor is at least
the certificate's. The language is compared only where a run names a
source: where none does, no check reads it, so it is covered whatever the
certificate states (a writer writes `none` there, and `none` beside a
named source is refused `malformed`). `unknown` is never covered.

**Who is blamed when a re-derivation fails.** Where the auditor's
definition covers the certificate's, a failure is the certificate's, under
its own name. Where it does not, every re-derivation that fails is refused
`definition-differs` (exit 78), naming both definitions and the failure it
stands for: the auditor's own limit, not a verdict on the certificate.
Hand the audit the named definition, a checkout of the golden model at a
commit that implements it, and it decides. A false certificate is refused
either way, so claiming an old definition gains a producer nothing. The
re-derivations are:
- step 4's loader checks: `program-image` for an image that does not load,
  `program-format` and `program-shape`;
- step 4a's language checks and recompile: `source-refused`,
  `source-graph`, `source-param`, `source-shape`, `source-image` and
  `compiler-differs` (where both the definition and the compiler differ,
  `definition-differs` is named, since the compiler reads the language);
- step 8's wider-source relation;
- step 9's re-runs and replays, and step 9a.

Where every check passes, the verdict accepts and names both definitions,
saying where the auditor's does not cover the certificate's that every
re-derivation passed under the auditor's.

**An auditor that cannot evaluate the definition** refuses
`definition-unavailable` (exit 78) where it first needs to: no mpmath for
a node whose golden function is decided through mpmath's enclosures, or
an enclosure that reached its precision cap (`transcend.py`'s
`ZivEscalation`). No node of the language reaches `transcend.py` yet: the
language refuses `exp` (`transcendental`), and its division and root are
softfloat's. M1's routines will be the first. A writer that meets the same
refuses `replay-undecided` (exit 78).

### Provenance

**Three kinds of field.** A field is CHECKED when an auditor can re-derive
it from what it is handed (a re-run, a recompile, a regeneration, a
signature), READ when the audit's arithmetic takes it as given so that a
false value fails its own re-run, and REPORTED otherwise, stated and not
checked. Every provenance line but four is REPORTED:
- `issuer-key` is CHECKED by the signature, and `issuer` by a keyring;
- `supersedes` is CHECKED where the superseded certificate is handed;
- `initial` is CHECKED where the auditor knows the generator and chooses
  to regenerate;
- `profile` and `language` are REPORTED, and compared with the auditor's
  own to name a failure's cause.

**Identify the run, not the person** (Logan's decisions 9 and 10).
- Written only on request: the issuer and the device's serial, whose
  default is `withheld`; and `host-os`'s version.
- Never carried: the host name, the user name, the CPU model, paths, a
  licence, a contact, and free text, the params' meanings among it. Each
  is personal data, a fingerprint, or the publication's, and none can
  change the bits. The source carries the params' meanings, and the
  certificate names the source by digest.
- An issuer, where there is one, is a name, an ORCID for a person, or an
  organisation's identifier, as the issuer chooses.
- The keyed mode protects states only. The salt keys every state, stream,
  block and raw hash, and no provenance line: each one is published or
  withheld.

**The environment.** The writer's list is every variable libcft and
cft-segrun read: `CFT_DIVSQRT_FULL`, `CFT_DIVSQRT_SEQ`, `CFT_SEGRUN_PLANT`,
`CFT_TIMEOUT_MS`, `CFT_TRANSCEND_MINPREC`, `CFT_XRT_BIND`, `CFT_XRT_CAPS`,
`CFT_XRT_MASK_ADDR_OVERRIDE`, `CFT_XRT_PROGRAM_CUTS`, `CFT_XRT_REDUCE_BC`,
`CFT_XRT_TILES`, `CFT_XRT_TILE_ORDER`, `CFT_XRT_TRACE`, `CFT_XRT_WITNESS`
and `XCL_EMULATION_MODE`. A writer writes those that are set, by name, and
none carries a path. The reader holds `env` to the list: a name off it
is refused `malformed`, so a certificate carries no variable but those -
not a home directory, a user name or a path - and a variable joins the
list with the code that reads it. test_cert2.py holds the list to the
code's `getenv` calls and libcft's instrument seeds, so a new variable
cannot be missed.

**The times.** Where they are known, `started` is no later than
`finished`, and `finished` no later than `issued`, and so `started` no
later than `issued`: each pair of known times, refused at the later line
(`provenance-order`). The reader checks each time as it reads it, in the
line order, so an order broken at `finished` is refused there, before
`issued` is read (whose own form is checked only then). They are
reported: no time is checked against a clock.

**The device's extra lines** (`device-platform`, `device-xrt`,
`device-clock`, `device-serial`) come from the library's image identity,
which grows at ABI 0.18. Through a remote handle they are `unknown`, as
version 1's xclbin digest is.

**`certificate-id`** is the issuer's own name for the certificate, chosen
before it is written. The body hash stays the certificate's intrinsic
name, and the verdict prints it. A DOI belongs to a publication's record,
minted after the bytes exist, never to the body.

**The initial-state generators.** `initial generator <name> <args>` says
run 0's initial state is what the named generator makes. The golden model
defines one, `shake-box` (A1's rule for its reference lanes, without its
special lanes): `shake-box <tag> <lo> <hi> ...`, a (lo, hi) pair for each
slot of a lane, each bound a constant in the language's canonical
spelling. Lane k's slot j is a value in [lo_j, hi_j] at twice the format's
precision, drawn from SHAKE-256 of `<tag> lane <k> state <j>`, rounded
once to nearest. Regenerating costs the certificate's lanes, so the
auditor does it only by its own choice (`regenerate`), and then needs no
initial state handed; the regenerated state must hash to run 0's boundary
0 (`initial-state`, which also names arguments the generator cannot use).
A generator the auditor does not know is reported. In a keyed
certificate a generator publishes boundary 0, which the salt otherwise
protects, and the verdict says so.

### The detached signature

Version 1 reserved it ("The detached signature", above). Version 2
defines it, and it signs a certificate of either version.

**The scheme** is Ed25519 (RFC 8032). It is deterministic: one key and one
certificate give one signature, byte for byte, so a gate can hold a
signature to committed bytes. Its keys are 32 bytes and its signatures 64.
Verification is RFC 8032 section 5.1.7's: R and the key decode by 5.1.3
(y below p, a square root that exists, no x of zero with its sign bit
set), S is below L, and the cofactored equation [8][S]B = [8]R + [8][k]A
holds. And one refusal the RFC leaves to its user (verifier-VCV2B, the
lead's decision, 2026-10-02): **a key of small order** - [8]A the
identity, one of the eight points of the curve's torsion - is refused.
Under such a key [8][k]A vanishes, so any R = [S]B verifies for every
message: a signature nobody made. It is refused by name, `signer`,
wherever a key is read: the certificate's `issuer-key` (by the reader,
and so by every writer, which reads its text back), a keyring's line, and
a signature file's key; a key that encodes no point is `malformed` on the
`issuer-key` line and `signer` in a keyring. A point R of small order is
not refused, since the equation then needs the key's secret, and neither
is a key with a small-order component beside a prime-order part, since
signing under it needs that part's secret. An implementation in another
language decides the cofactored equation, refuses the same eight keys,
and is held to `python/tests/test_ed25519.py`'s vectors: the RFC's five,
the eight keys of small order, and the decoding and S edges.

**The message** is `cft-signature 1`, a NUL, then the 32 bytes of the body
hash: a signature over a certificate is a signature over nothing else.

**The file** is `<certificate>.sig`, by the certificate's byte rules, five
lines:

    cft-signature 1
    scheme ed25519
    key <64 hex>
    certificate <64 hex>
    signature <128 hex>

**The key's identity** is the public key itself. A certificate names the
key it is to be signed with by `issuer-key`, and which person holds a key
is in no certificate. An auditor may be handed a keyring, lines `key <64
hex> <text>`, each key once, and the verdict then names the key's holder.

**The audit** (step 2a), when a signature file is handed:
- the file follows its form (`signature-format`);
- its key is not of small order (`signer`);
- its `certificate` line is this certificate's body hash, and the
  signature verifies (`signature`);
- the key is the certificate's `issuer-key`, where it names one
  (`signature-key`);
- in a keyring handed, the key's holder is the certificate's `issuer`,
  where the issuer is a text (`signer`). A keyring that breaks its form is
  `signer` too, whether or not a signature is handed, and so is one whose
  line names a key of small order or no point.

Without a keyring the verdict says the key is one no keyring handed
names. What a signature proves: whoever holds the secret of the key's
prime-order part - the key's holder - vouched for these bytes, since a
key of small order, under which nobody's signature is needed, is refused
before the signature is read. Which person that is, a keyring handed
says, as far as the auditor trusts it. Not when, and not that the bits
are right: the audit proves the bits.

**The key tool,** `python/cft_sign.py`: `keygen` draws a secret from the
operating system's secure randomness into a new file and prints the public
key; `public` prints a key file's public key; `sign` writes a
certificate's `.sig`; `verify` checks one, and for version 2 its key and
signer, with step 2a's names. It never overwrites a file and never prints
a secret. `sign` signs only a certificate the strict reader reads, of
either version, and refuses anything else by the reader's name, bytes
with a good hash line that are no certificate among them. On a POSIX
system it refuses a key file its group or others may read or write, as
ssh does; on Windows, whose permissions are ACLs that a mode does not
show, it does not check them.

**The published test key** is the secret `20 21 22 ... 3f`, printed on
this page as the example salt is, so it is a test key only and never an
owner's.

What a reviewer of the implementation should look at: it is not
constant-time (Python's integers, and a double-and-add that branches on
the scalar), so a secret signing on a machine an adversary can time leaks;
nothing zeroes a secret in memory; and the key tool writes a key file
owner-only and refuses a group- or world-accessible one on POSIX
systems, and enforces neither on Windows.

### Version 2's strict reader

The reader chooses by the magic line. A body whose first line is exactly
`cft-certificate 2` is version 2's; every other body goes to version 1's
reader, which refuses a second token spelt as a decimal other than 1 or 2
as `version`. So a version-1 body under `cft-certificate 2` reaches
version 2's reader, which finds `runs` where `profile` belongs
(`line-missing`), and a version-2 body under `cft-certificate 1` reaches
version 1's, which refuses `profile`, its first line of no version-1 key
(`unknown-line`).

Version 2's reader decides in version 1's order ("The strict reader"): the
hash line, the body's hash, the bytes, the magic line, every key a key of
version 2 (`unknown-line`), the mode and its commitment, then the lines in
version 2's order, with version 1's rules for counts, indices, a line not
the one expected, and values. Version 2's groups follow those rules:
`replay-methods`, `environment`, `source-params` and `replays` each count
the lines that directly follow it. The keys strictly increase in
`replay-method` lines by run, in `env` lines by name, in `source-param`
lines by name in byte order, and in `replay` lines by segment: a repeat is
`line-unexpected` and a smaller one `line-order`. Then the form rules
above, in the line order: `marked` at its segment line,
`replay-lane-flags` and `replay-source` at a `replays` line,
`provenance-order` at the later time, and last, after every run is read,
`replay-method`.

### Version 2's audit

**What an auditor is handed,** beyond version 1's:
- `sources`: {run: the source's bytes};
- `lane_flags`: {run: {segment: the block's bytes}};
- `signature`: a `.sig` file's bytes, and `keyring`: a keyring's bytes;
- `superseded`: the certificate this one names in `supersedes`;
- its own choices: `define`, {run: `all` or a list of segments}, the
  segments to run by the source's interpreter too; and `regenerate`, to
  regenerate run 0's initial state by its named generator.

**What an audit spends.** Version 1's rule holds: never by a number the
certificate states. A recompile is bounded by the source handed; a replay
is one marked lane of a re-run segment, by the interpreter; a definition
re-run and a regeneration are the auditor's own choices, and each spends
the stated lanes because the auditor chose it.

**The order of the checks.** An auditor refuses at the first failure. The
steps are version 1's, with these inserted or extended:
1. **Integrity:** as in version 1.
2. **Form:** version 2's strict reader. Then the auditor's own choices:
   its segments (version 1's `choice`), the definition re-run's segments
   (`choice`: distinct, existing, at least one, of a run that exists), and
   `regenerate`, True or False (`choice`).
- **2a. The signature,** when one is handed, or a keyring alone.
3. **Salt:** as in version 1.
- **3a. Supersedes,** when the superseded certificate is handed: it is
  whole, and its body hash is the one named (`supersedes`); one handed
  where the certificate names none is `supersedes` too.
4. **Programs:** as in version 1, the loader's verdicts through the
   definition.
- **4a. Sources:** "Sources", above.
5. **Streams** and 6. **Continuity:** as in version 1; continuity runs on
   the certified, corrected chain. A run is bounded as in version 1, and
   by the regenerated initial state where the auditor chose to regenerate.
7. **States handed:** first the initial state regenerated, where the
   auditor chose it and knows the generator (`initial-state`); then version
   1's states handed; then the blocks handed (`lane-flags-shape`,
   `lane-flags-hash`, `lane-flags-identity`).
8. **Relations:** version 1's, with `aux-source` and the strengthened
   `aux-h-slots`, and the wider-source relation; run by run, each in its
   table's order.
9. **Re-runs,** each chosen segment in ascending order, a block of lanes
   at a time, in this order:
   1. re-run the image from the segment's start: the raw end, flag word,
      STATUS and block (`state-missing`, `program-image` as in version 1);
   2. a segment whose raw block marks a lane has a replay line
      (`replay-missing`), and one that marks none has none
      (`replay-unmarked`). A run that says `lane-flags no` and whose re-run
      marks a lane is `replay-missing`: the producer could not have found
      the lane;
   3. the line's `raw-end`, `raw-lanes` and `marked` are the re-run's
      (`replay-raw`);
   4. each marked lane replayed by the definition (`source-missing` where
      the source was not handed, `definition-unavailable`), and `changed`
      the number of marked lanes whose values the replay moved
      (`replay-changed`);
   5. the corrected end, block, flag word and STATUS are the segment
      line's: `segment-end`, `segment-lane-flags` (where the run says
      `yes`), `segment-flags` and `segment-status`, version 1's names, now
      against the corrected values.
   A segment with no replay line and no mark gets version 1's checks, and
   its block.
- **9a. The definition re-run,** the auditor's choice: each chosen
  segment, from its start (handed or re-run into, `state-missing`), run by
  the source's interpreter lane by lane (`source-missing`,
  `definition-unavailable`), must end on the certified state
  (`definition-end`) and raise the certified flag word and, where the run
  says `yes`, the certified block, the definition's lane bytes carrying
  [4:0] alone (`definition-flags`). This is the check for a hand-written
  image that a source defines.
10. **Accuracy:** as in version 1, with `wider-source` entries.

A replay or a definition re-run the language refuses on its inputs (a
half-step run whose source declares no h to halve) is `source-refused`.

**The verdict** of an accepted audit says, in this order: ACCEPTED; the
certificate's name, its body hash; the mode; the signature (none handed,
or verified, by which key, and its holder where a keyring names it); the
superseded certificate (none, checked, or named and not handed); the
definition, the certificate's and the auditor's, and whether the
auditor's covers it; for each run, version 1's line of what was re-run,
then its source (none; checked by the language, and recompiled by which
compiler; or named and not handed), its lane flags (how many blocks
re-run, which handed), its replays (how many lanes in how many segments,
each matched), and its definition re-run where one was chosen; each
accuracy value, re-derived; the initial state (given, regenerated by
which generator, or reported); what the audit was handed, at one of three
levels after ACM's and NISO's vocabulary: **rebuilt** (every image and
bank the auditor's own recompile, the initial state regenerated, no other
state handed), **re-run from the start** (states at boundary 0 alone), or
**re-run**; then version 1's identity lines, and each provenance line:
stated and not checked, unknown, none or withheld. The golden model's
`cert2.Verdict.lines()` is its byte-exact form, which a C auditor's gate
will hold it to. The auditor's own identity, with its mpmath version, and
the audit's time are a header above the verdict
(`cert2.Verdict.header()`), which the comparison between auditors leaves
out.

### Version 2's refusals

Version 1's names keep their meaning and their codes: `aux-format`,
`aux-lanes`, `aux-image`, `aux-segments` and `aux-streams` and `aux-start`
for the wider-source relation; `aux-h-slots`, strengthened;
`segment-end`, `segment-flags` and `segment-status`, against the corrected
values; `accuracy-run` for a wider-source entry on a run of another kind;
`malformed`, `line-missing`, `line-order`, `line-unexpected` and `count`
for the new lines. The new names:

| name | exit | when |
|---|---|---|
| `marked` | 2 | a segment line's STATUS carries STATUS[6] |
| `replay-lane-flags` | 2 | a run with replay lines says `lane-flags no`; a writer asked to certify a run that marks a lane without the block |
| `replay-source` | 2 | a run with replay lines names no source; a writer asked to replay with no definition |
| `replay-method` | 2 | a run with replay lines that no `replay-method` line names, or a `replay-method` line for a run with none, or for no run |
| `provenance-order` | 2 | `started` after `finished`, `finished` after `issued`, or `started` after `issued`, where both are known |
| `signature-format` | 4 | a signature file handed breaks its form |
| `signature` | 4 | the signature names another certificate, or does not verify |
| `signature-key` | 4 | the signing key is not the certificate's `issuer-key` |
| `signer` | 4 | a keyring handed names the signing key under another holder than the `issuer`, or breaks its form; a key read anywhere - the certificate's `issuer-key`, a keyring's line, a signature file's key - is of small order ([8]A the identity) |
| `supersedes` | 4 | the superseded certificate handed is not whole, or not the one named, or the certificate names none |
| `source-digest` | 4 | a source handed is not the one its run names, is handed for a run that names none, or `sources` is not in its shape |
| `source-refused` | 4 | the language refuses a source handed, at the run's format, or refuses to run it on a replay's or a definition re-run's inputs |
| `source-format` | 4 | a main run's format is not its source's own |
| `source-graph` | 4 | the source's step graph is not the one named |
| `source-param` | 4 | a source param names no param, its literal is not the canonical spelling of a constant, or the language refuses the value for that param |
| `source-shape` | 4 | the image's slots a lane are not the source's lane: its state, each tangent vector, its lane params |
| `source-image` | 4 | the source, compiled by the named compiler and output version, is not the run's image or bank |
| `source-missing` | 4 | a check needs a source that was not handed: a replay, a wider-source relation, a definition re-run |
| `lane-flags-shape` | 4 | a block handed is not the run's lanes long, belongs to a segment or run that has none, or `lane_flags` is not in its shape |
| `lane-flags-hash` | 4 | a block handed is not the certified one |
| `initial-state` | 4 | the named generator, regenerating, does not make run 0's initial state, or cannot from its arguments |
| `lane-flags-identity` | 5 | a block handed disagrees with its segment line's flag word or STATUS[5:4], or a byte carries [7] |
| `aux-source` | 5 | an auxiliary run's source lines are not its relation's |
| `segment-lane-flags` | 6 | a re-run segment's corrected block is not the certified one |
| `replay-missing` | 6 | a re-run segment marked a lane, and no replay line names it |
| `replay-unmarked` | 6 | a replay line names a segment whose re-run marked no lane |
| `replay-raw` | 6 | a replay line's `raw-end`, `raw-lanes` or `marked` is not the re-run's |
| `replay-changed` | 6 | `changed` is not the number of marked lanes the replay changed |
| `definition-end` | 6 | (the auditor's choice) the definition's run of a segment does not end on its certified state |
| `definition-flags` | 6 | (the auditor's choice) it does not raise the certified flags or block |
| `definition-differs` | 78 | a re-derivation failed, and the auditor's definition does not cover the certificate's `profile` and `language` |
| `definition-unavailable` | 78 | the auditor cannot evaluate the definition: no mpmath for a node that needs it, or an enclosure at its precision cap |
| `compiler-differs` | 78 | a recompile differs, and the auditor's compiler is another name or output version, or failed |
| `replay-undecided` | 78 | a writer cannot replay a marked lane: the definition cannot be evaluated there, or a replay image marks it too |

The codes are version 1's families. 78 is the one version 1 gives a tool's
own limits (cft-audit's `build-width` and `build-format`), and
`definition-differs`, `definition-unavailable`, `compiler-differs` and
`replay-undecided` join it: each is the auditor's or the writer's limit,
not a verdict on the certificate.

### Version 2's example and test vectors

This certificate is what `python/cft_golden/cert2.py` writes for the
golden corpus's replay case: `certificates/programs/markstep-fp64.cfta`,
defined by `certificates/programs/markstep-fp64.cftl` (`next k = k + 1`,
`next x = x * a + b`, a = 9/10 and b = 1/7 each rounded once), three lanes
from (k, x) = (0, 0.3333), (100, 0.5) and (50, 0.2), three segments of four
steps, open, with the counter's drift over the lanes. Every measured
header line is `unknown`, as version 1's example's `build-id` is.
`python/tests/test_cert2.py` regenerates it, holds this block to it byte
for byte, and audits it.

<!-- the version-2 example certificate -->
```
cft-certificate 2
mode open
build-id unknown
backend software
device-xclbin none
device-version none
device-caps none
device-tiles 1
profile 2
language 1
device-platform none
device-xrt none
device-clock none
device-serial none
writer golden unknown
writer-runtime unknown
compiler-build none
replay-methods 1
replay-method 0 golden
certificate-id none
issuer withheld
issuer-key none
host-os unknown
host-arch unknown
started unknown
finished unknown
issued unknown
supersedes none
environment 0
initial given
runs 1
run 0 main
program-format fp64
program-image 86bfd74a3cb1435a384d4e703ca82ff50488e9b9fab3f37c0a991c90340b55bf
program-digest 97088646bc0079578c2ed4bd3159d6c7307a94a373e5fb07b598f589aba14b78
source 78607fe6de418566894321bf255f48d7cd2f6caed4af4d5623bb9a6252548de0
source-name markstep-fp64.cftl
graph 6dafed3fffaadbcd84a6833fad87155eb4cdf64a2930ee9cd4350a5f428a768d
compiler none
source-params 0
lanes 3
steps 4
stream-a 24491f6a040123086eefac186e747eabad55bed41b9a74b2726990a1e8c6fe37
stream-b f53ceee9b603ad198e8fcb872fa3f441062e7c1375d400d6dee175d571317631
stream-c d3a329f70c79c48c2a594b4ff24b775c9b26aec851986f1f06f2c677a7d4668a
parameters 0
lane-flags yes
segments 3
segment 0 start 19592d8392f28690fa4526c23bb3389cb95e2c02ed9599e9bfdb758b0d56315b end 4cfcbbef215250707c8a80561463e75d424c5e2dd980ff724e8a6837133c4a20 flags 16 status 0 lanes cbf0bb15dddc2923be5b88871873a94d3673135fa2e5a0496ddee10825adaaaf
segment 1 start 4cfcbbef215250707c8a80561463e75d424c5e2dd980ff724e8a6837133c4a20 end 2e01e5bfde9714b9166ff860633ad3122c1b3182a6972881b8c269727fdb7e0c flags 16 status 0 lanes cbf0bb15dddc2923be5b88871873a94d3673135fa2e5a0496ddee10825adaaaf
segment 2 start 2e01e5bfde9714b9166ff860633ad3122c1b3182a6972881b8c269727fdb7e0c end 59e0ae73145a06c7f223ea7d64cf3042a96f9a562ace14968f50da7862aa57e2 flags 16 status 0 lanes cbf0bb15dddc2923be5b88871873a94d3673135fa2e5a0496ddee10825adaaaf
replays 1
replay 1 marked 2 changed 1 raw-end a4c7e417201e52528159f3f1ffdfe13c7cff12b47fc394dd2a57f92ec994a047 raw-lanes 0791994b8a4cb0817d19b23c4af478ee7060ca7da47e9eec92b465ec1e842669
output 59e0ae73145a06c7f223ea7d64cf3042a96f9a562ace14968f50da7862aa57e2
accuracy 1
entry 0 drift
kind measurement
uses 0
scope max-lanes
quantity counter terms 1
term 1/1 s0
value exact c/1
end
hash 797c51ef95e1e10eade458cd0897ca786a7d70ceee46424f0492eb19c7b2fb34
```

Reading it: the image marks lanes 0 and 1 in segment 1, where k is 7 and
106, and raises invalid with the mark there. Lane 0's last bit is wrong
and lane 1's is right, so the replay changes one of the two marked lanes.
Every certified segment raises inexact alone (flag word 16, every lane's
byte 0x10) with STATUS 0: the definition's, where the machine's segment 1
raised 17 and STATUS 64, which only the replay line's hashes now carry.
The counter rose by 12 in every lane over the twelve steps, and the drift
is exactly 12 (`c/1`).

The test vectors, which test_cert2.py holds to the implementation:
the example salt; a block of three lanes keyed and open; the published
test key; and a signature by it over the body hash of `cft-certificate 2`
and an LF alone:

<!-- the version-2 test vectors -->
```
salt                 000102030405060708090a0b0c0d0e0f101112131415161718191a1b1c1d1e1f
lane-flags-bytes     109100
lane-flags-hash      526bcd6e3d251c183731802a6782037506878d0b3adebfd1778634e5ca0a9dd6
open-lane-flags-hash ff136cc613ce720e89697f7479216e686dda325059e01f24f075ce276f5d8ec6
test-seed            202122232425262728292a2b2c2d2e2f303132333435363738393a3b3c3d3e3f
test-key             29acbae141bccaf0b22e1a94d34d0bc7361e526d0bfe12c89794bc9322966dd7
body-hash            1890cecc078460af04b03a9fca373e4ad37426ada26439f7d87d1a3e8f09947c
signed-message       6366742d7369676e61747572652031001890cecc078460af04b03a9fca373e4ad37426ada26439f7d87d1a3e8f09947c
signature            fbde0e5f01480f39a4fee9b6f275cea4a2dbe3253bba89b57492635c871fdfef93b8e5b4ca14ba4c4a68612d7a9bfe74afe0fb4e7f91d3fdf4d23c02dcf06907
text                 Logan W.
text-token           Logan%20W.
```

### Version 2's controls

The golden corpus commits thirty of them, one for each refusal a
committed case can carry, which every auditor handed the case's inputs,
its source among them, must give ("Golden certificates", version 2's
cases).
`python/tests/test_cert2.py` holds version 2's mechanisms to negative
controls, each by the name of the check it exists for, every one but the
byte flip over a valid hash line. Its fixtures are markstep (open and
keyed); Lorenz-63 compiled from `programs/systems` by cftc with rho = 29,
with a half-step run, a wider-source run and version 1's wider run, an
estimate on each; flagstep with lane flags and a drift; a certificate with
every header line spelled out, its initial state generated, signed under
the test key and superseding flagstep's; and a Lorenz-63 run that an audit
rebuilds from its source and its generator alone. The controls cover:
- version 1's census on version 2's grammar: a byte flipped anywhere,
  every line dropped and repeated, an unknown line at every position,
  every adjacent pair exchanged (a drift's terms aside, whose order is the
  producer's), every count one more and one less;
- every encoding's other spellings: texts (a space unencoded, `%41`,
  lowercase hex, 256 characters, a word as a text), times (month 13,
  February 30, 24:00:00, a leap second, a lowercase z or t, an offset, no
  seconds, a fraction, 2100-02-29), versions (`02`, `2.0`, `2.01`, `2.`,
  `0`, 20 digits), keys, digests, builds, the clock, the writer, the
  generator, every word on a line that does not take it, and the
  environment's names, order and repeats;
- every form rule by name, at its line: `marked`, `replay-lane-flags`,
  `replay-source`, `replay-method` (three ways), `provenance-order`
  (three pairs), a replay line's counts and order;
- the versions of the format, both ways, and `cft-certificate 3`;
- step 2a: the file's form eight ways, a flipped signature, another
  certificate's, another key's, a keyring's other holder and its form,
  and a version-1 certificate signed;
- step 3a, step 4's loader under profile 1 (513 constants, loaded before
  ee78152 and refused after) and profile 2, and every check of step 4a,
  `compiler-differs` and an equal recompile under another output version;
- `source-missing` at a replay, a wider-source relation and a definition
  re-run;
- the blocks handed (each shape, the hash, each of R23's identities), the
  initial state regenerated (another tag, too few arguments, a bound not
  in its canonical spelling, an unknown generator);
- every wider-source relation (another source, another target, other
  params, the same format, another segment count, streams and start not
  widened, version 1's wider image as one), each auxiliary run's source
  lines, and the h-slots held to the recompile's;
- a version-1 and a version-2 wider run of a routine image, refused
  `aux-image` by writer and audit;
- every re-run check: the block, a replay due and undue (in a `no` run
  too), each raw value, `changed` one more and one fewer, and the raw end,
  block, flag word and another STATUS certified as the corrected segment;
- the definition re-run (an image whose b is not the source's, and one
  that raises invalid in every lane), its choices, and `definition-differs`
  under six certificates' definitions, against `replay-changed` under the
  auditor's own;
- `definition-unavailable` and `replay-undecided`, with mpmath taken away
  from a node planted as transcendental, and with an enclosure forced to
  its cap: no node of the language reaches mpmath yet, so these plants
  stand for M1's;
- the golden writer's own refusals, and every field it cannot spell;
- the key tool: a key made, never overwritten, signing and verifying both
  ways, a bad key file, a key file others may read (POSIX's check, forced
  on), and bytes that are no certificate refused by `sign`;
- the dispatch, the keyed mode's reach, the verdict's three levels, the
  writer's environment list against the code, and the published example
  and test vectors;
- from verifier-VCV2B's findings: the eight keys of small order refused
  `signer` on the issuer-key line, in a keyring and as a signature
  file's key (its forged signature among them), and by the key tool; a
  key of no point; a generator named one of the words, by the reader and
  the writer; the times' order checked in the line order, before a later
  line's form; `language none` beside a source, and the language not
  compared where no run names one; an `env` name off the writer's list;
  the defined-by source's verdict line; and the routine rule's W1 and W2,
  the golden writer testing the main image.

`python/tests/test_ed25519.py` holds Ed25519 to RFC 8032 section 7.1's five
vectors, every refusal of 5.1.3 and 5.1.7, and the cofactored equation, on
a key with a small-order component where a cofactorless verifier parts
from it. Beside them it holds vectors for another implementation to be
held to: the eight keys of small order, each refused though verifier
VCV2B's signature satisfies the equation under it; six encodings that
decode to no point (y = p, y = p + 1, y = 2^255 - 1, a y with no square
root, and x = 0 with its sign bit set at y = 1 and y = p - 1); and three
signatures whose S is at or above L. The census by plants that version 1 had, each check disabled in a
copy, has not been run on version 2: it is the verifier's.

### Version 2's C half

Version 2's C half is two parcels, built against this page, and both are
built (2026-10-02):
- **cft-segrun** (parcel CV2CW; "The segment runner" is its manual, and
  segrun_check's section 14 its gate): `--lane-flags`, asking for the
  block (ABI 0.17) and writing `run-<r>-segment-<k>.flags`, and asking
  whenever the image
  needs flag control; `--replay-image IMG`, an option of each run, writing
  `replay-method <r> image <digest>`; refusing `replay-source` where a
  run that marks a lane names no source (the golden writer's name for
  it), `replay-missing` where it names one and was handed no replay
  image, and `replay-undecided` where the replay image marks the lane
  too; `--source SRC --manifest M`, the source lines from cftc's
  manifest, held to the files it runs; `profile` from the library's own
  constant; the header's statements as options (issuer, identifier,
  issuer-key, initial, supersedes) with the privacy defaults; measuring
  the times, the host's OS and architecture, and the environment list
  itself; the device's extra lines through `cft_image_id` at ABI 0.18; and
  `--format-version 1`, kept for the corpus and for runs that stay
  version 1.
- **cft-audit** (parcel CV2CA; "The audit tool" is its manual): both
  readers, by the magic line; block files in
  `--states DIR`; re-runs that ask for the block where a run says `yes`;
  its library's profile and language version compared with the
  certificate's (`definition-differs`); `--signature`, `--keyring` and
  `--superseded`; Ed25519 in C (`host/tools/ed25519.h`, with SHA-512 in
  `host/tools/sha512.h`), held to test_ed25519.py's vectors (the RFC's
  five, the eight keys of small order refused, the decoding and S edges)
  and the cofactored equation, and a key of small order refused `signer`
  wherever a key is read. It takes no source: a replay in a re-run
  segment, a wider-source relation and a definition re-run refuse
  `source-missing` there exactly where the golden auditor handed no
  source does, so the two keep one verdict.
- **cft.h** states the profile it implements and the language version
  beside it, `CFT_PROFILE_MAJOR` and `_MINOR` and `CFT_LANGUAGE_MAJOR` and
  `_MINOR` ([HOSTAPI.md](HOSTAPI.md)), since `definition-differs` compares
  both. cft-audit evaluates no language, so its language version is the
  one its tree's golden model states (`python/cft_golden/lang/version.py`),
  and audit_check.py holds the four to the two Python files.
- **libcft:** `cft_image_id` grows by the platform's name, the XRT
  version, the clock and the serial (ABI 0.18; [HOSTAPI.md](HOSTAPI.md),
  "Certificate version 2's device lines at ABI 0.18").
- **The gates:** audit_check.py hands cft-audit test_cert2.py's calls
  and the corpus's version-2 cases and controls, held to the golden
  auditor handed no source and not asked to regenerate, as the tool is;
  and corpus.py's check has cft-segrun remake each case the corpus marks
  `writers both`, leaving out of both certificates `build-id`, `writer`,
  `writer-runtime`, `compiler-build`, the `replay-method` lines, the
  three times, `host-os`, `host-arch` and the environment (corpus.py's
  `C_WRITER_MEASURED`), and the four device lines only where the case
  carries a card's values (signed-fp64; `C_WRITER_DEVICE`), and holding
  every other line byte for byte: a software run writes `none` on the
  device lines, and six of the seven cases carry it. A replay certificate cft-segrun writes
  (`replay-method 0 image`) is held to the golden writer's
  (`replay-method 0 golden`) that way. The NOTE that named those seven
  cases is a check: all seven remade ("Golden certificates").
- **The WASM module** is rebuilt at ABI 0.18.

### What version 2 does not do

- **Sign a time,** or check one. An RFC 3161 token over the body hash
  would bound `issued` from above; that is for a later version.
- **Check a place, the issuer without a keyring, the environment's values
  or the device's extra lines.** Each is reported; the environment's
  names are held to the writer's list.
- **Bind a key to a person,** distribute keys or revoke them. The keyring
  is the auditor's input.
- **Audit sources or replays in C.** cft-audit takes no source, since
  there is no C compiler or interpreter of the language, so a certificate
  with a replay in a re-run segment, or with a wider-source run, is the
  golden auditor's. Where marks come by design (M2 past its range), that
  can be every segment.
- **Decide across definitions.** An auditor whose definition does not
  cover a certificate's refuses `definition-differs` rather than decide.
- **Prove a slower image right.** The audit checks the replayed values
  against the definition instead.
- **Carry a bound, or a value that is not an exact rational,** certify
  deposits, lane masks, index tables, or streams that change between
  segments, certify cft-orbits' exact route or give it a wider run, or
  record a remote run's depth or device lines. As in version 1.
- **Countersign** an auditor's verdict, **publish** (the gallery's
  publication record carries the licence, the contact and a DOI), or
  **interoperate** as PROV-O, SLSA or RO-Crate.
- **Hide provenance with the salt.** A keyed certificate's provenance lines
  are in the clear, or withheld.
- **Make a version-1 certificate version 2.**
