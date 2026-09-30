# Certificates, version 1

A certificate is a text file that says what a deterministic run was and
how accurate it is: which program ran, on which inputs, cut into which
segments, which state each segment began and ended on, what flags it
raised, and what its accuracy is, of which kind. An audit checks that
statement by re-running segments on an implementation the producer does
not control, starting each from its certified start state. This page is
the whole of version 1. A reader and an auditor can be written from it
alone.

Where things stand (2026-09-29):
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
  the golden writer;
- the C auditor, `cft-audit`, audits them in C beside the golden one
  (see "The audit tool"), and the `audit` stage holds its verdicts equal
  to `cert.audit`'s (2026-09-29; the plan of record,
  [ROADMAP.md](ROADMAP.md), "Steps 4 and 7"). The two C tools compute
  an entry's value with one code, `host/tools/cert_exact.h`;
- the golden certificates, twelve programs and their certificates in
  `certificates/`, hold both writers to committed bytes (see "Golden
  certificates");
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
  certificate for bits it computed itself. A signature, when one is
  defined, is detached (see "The detached signature").
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
| `aux-image` | the same steps a segment, and the same image digest; then the main run's scratch depth | the same steps, and an image that is the main image one format wider: the same instruction words, `max_deposits`, flags, constant count and scratch word, the precision code one rung up, and any constants the image carries exactly widened; then the main run's scratch depth |
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

Reserved, and nothing more.
- A later version may define a signature. It signs the body's hash,
  the 32 bytes the hash line carries.
- It lives in a file of its own, beside the certificate, never inside
  it. The certificate's bytes are the same signed or not.
- A version-1 reader never reads a signature.
- Version 1 defines no scheme.

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
   second and last token spelt as a decimal integer other than 1 is
   `version`, whatever its size - past 2^63 - 1 too, since a version is
   a name here and not a count; anything else is `malformed`.
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
| `version` | 2 | the magic line names a version other than 1 |
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
| `aux-image` | 5 | an auxiliary run's image or steps are not the main run's, or the main run's one format wider, or it runs at another scratch depth than the main run's |
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
  version of any size;
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
files and options can carry, 243 of 282; the other 39 are counted and
named. It requires the golden auditor's verdict by name, code and
location ("The audit tool").

## The segment runner

`cft-segrun` is the C writer of any segment program, the plan's step 3.
It runs a program as consecutive segments on one libcft device handle,
keeps the state at every boundary, and writes a version-1 certificate,
its accuracy entries included since the plan's step 5 (2026-09-30).
`make -C host all` builds it, from `host/tools/segrun.c`. `cft-orbits`
writes certificates of its own runs too ([ORBITS.md](ORBITS.md),
"Certified runs"), with the same encoding: `host/tools/cert_write.h`,
the hashes, the identity lines and every line of the text, which both
tools include (the steps-5-and-6 round, 2026-09-30).

    cft-segrun --out CERT --states DIR (--salt SALT | --open)
               [--device sw|<xclbin>|cft://host:port | --scratch-depth N]
               --run main --image IMG [--bank BANK] --init INIT
                          --segments S --steps K [--param NAME=N ...]
               [--run half-step --h-slots I,J,... --image IMG ...]
               [--run wider --image IMG ...]
               [--entry drift|step-halving|wider --uses R
                        --scope max-lanes|lane:I
                        [--quantity LABEL --term C[,sI...] ...]
                        --value exact|rounded:FMT:RND|enclosed:FMT] ...
    cft-segrun --hash state|stream-a|stream-b|stream-c FILE
               (--salt SALT | --open)
    cft-segrun --hash commitment --salt SALT
    cft-segrun --build-id

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
  each of its functions returns a status, which each tool refuses by
  name.

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
  - a method, a label, a run, a lane or a slot not in its spelling;
  - a drift with no `--quantity`, no `--term`, or more than 64;
  - an estimate given a `--quantity` or a `--term`;
  - a coefficient not in its one spelling: a zero denominator, 0/3, or
    not in lowest terms;
  - a factor not `s<slot>`, more than eight of them, or out of order;
  - a `--value` that is not `exact`, `rounded:FMT:RND` or
    `enclosed:FMT`, in the page's words;
- `width`, for a coefficient past the width rule by its digits;
- `accuracy-run`, for a run that does not exist, and for an estimate on
  run 0, on a run of the other kind, or on a run whose lanes or slots a
  lane are not run 0's;
- `accuracy-scope`, for a lane the run does not have;
- `accuracy-slot`, for a slot the run's state does not have (so every
  slot from 65,536).

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
measure what the trial costs the runs. The read-back refusal has a
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
  reading it back (`output`; the plant build holds the check, and a
  race does not);
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
gate measures it (**Its gate**, below). On the desktop, with flagstep's
three runs of 65,535 lanes and two entries that read four states back,
the peak commit was:
- in four runs of the gate, 12 KiB less, 12 KiB less, 28 KiB more and
  40 KiB more than the same three runs without entries (10,224 to 10,284
  KiB);
- beside that, one more state held beside the runs' would be 1,024 KiB.
So the entries add nothing that identical runs' noise does not
(2026-09-30). Each entry's definition is held from the command line to
the end: a rational of about 520 bytes a term at the default bigint,
about 36 KiB for a drift of 64 terms. Its value is held too, about 520
bytes. None of it grows with lanes or segments. The least address space
in Linux (`ulimit -v`), and the trial's cost with entries, are measured
by the gate on Linux; they have not been run for this page yet.

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
(**Memory**, above).

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
- and `lorenz63-rk4` at fp64 once more, its half-step run entered from
  an initial state of its own, unlike the main run's. Every other
  half-step run shares run 0's, so a writer that entered one from run
  0's `--init` would pass them all (verifier-C6's plant).

Each program is certified keyed and open on the software backend, with
accuracy entries (since the plan's step 5, 2026-09-30):
- Between them the entries have every method, both scopes, every form
  and every rounding direction:
  - a step-halving estimate on each ODE program;
  - a wider one on each fp64 program;
  - Henon-Heiles' energy drift, exact, whose denominator has a 3, at
    fp64 on lane 1 and at fp256 over the lanes, near the width rule;
  - flagstep's counter drift over the lanes. Every lane's drift is -5,
    so a writer that took the signed maximum writes -5.
- A difference of two values of one format is exact in it, so a rounded
  estimate names a narrower format. The gate holds that each direction
  but `rup` rounds some entry's value to other bits than `rup` does, so
  that a writer that swapped its direction is seen.

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
certifies `lorenz63-rk4` at fp64 and `flagstep` through a loopback
cft-serve, stopped by its PID. Their device lines must be the remote
rule's, and their run blocks byte for byte the software backend's,
flagstep's flag words and STATUS among them.

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
  digits (`width`).
- The entry against the runs:
  - `accuracy-run`: a run that is not there, a run index past 2^63 - 1,
    step-halving on run 0 or on the wider run, wider on the half-step
    run, and an estimate whose half-step run has other lanes;
  - `accuracy-scope`: lane 3 of 3, and a lane past 2^63 - 1;
  - `accuracy-slot`: slot 3 of 3, and slot 70,000.
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
whole working sets. What the accuracy entries cost: the same three runs
with two entries that read four states back, against the three runs
alone. They may cost 256 KiB more, a quarter of one of those states
(and on Linux one bisection step), and no more; holding one more state
beside the runs' would cost 1,024 KiB. The gate measures a process as
its platform does:
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

With the accuracy entries (2026-09-30): 634 checks on the Windows
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
golden one. `make -C host all` builds it, from `host/tools/audit.c`.

    cft-audit --cert CERT [--salt SALT] [--states DIR] [--seed HEX]
              --run 0 --image IMG [--bank BANK] [--stream a|b|c FILE ...]
                      [--choose all|sample:K|K,K,...]
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
  `value_holds`. Every function returns a status and prints nothing:
  this tool maps each status to its refusal (step 10's names at the
  entry) or to its internal error, as before. The header is compiled
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
   - git ignoring the binary.
2. **test_cert.py**, run in the gate's process with `cert.parse` and
   `cert.audit` shadowed. Every top-level call its tests make is handed
   to the tool too, translated into files and options. So the tool is
   held to every control the golden auditor is held to whose arguments
   files and options can spell, and stays so as controls are added.
   - A call whose arguments no file or option spells faithfully is
     counted and named, not compared: a list where a mapping goes, a
     string or bool key, an integer past the format, a salt that is not
     bytes.
   - A seed the golden audit draws is caught and handed to the tool.
   - An executor the test makes refuse is the instrument.
3. **segrun_check's certificates:** cft-segrun on its programs, keyed
   and open, with the accuracy entries segrun_check gives them (every
   method, scope, form and direction; since step 5), each audited in
   full, in full from the initial states alone, and sampled under a
   fixed seed.
4. **The golden corpus** (`certificates/MANIFEST`), where the tree has
   one: every case the same three ways, the two auditors against each
   other and against the manifest's verdict.
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
gave 6,799 of 6,799 in 218 s. So no verdict moved.

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
ca1327f's, and has not been run again since the move.

On `tools/audit.c` as of ca1327f, with the gate's 6,669 cases, the
census found 167 sites (157 s on the desktop, 2026-09-29):
- **148 red.** Each turns a case red, and the gate's line names the
  golden auditor's refusal beside the tool's other answer. Four answer
  verifier-A1's findings, each planted in turn:
  - `build-format` at a run's `program-format` line: its case reaches
    step 4, which refuses it `build-format` at the run, not the line;
  - `build-format` at a value's line: its case reaches the library's
    decimal, an internal error, exit 70;
  - `build-format` at an image above the ceiling: `program-image`;
  - the `--sample` map's size: a map of 16 slots, and the sample runs
    past the census's 20 s.
- **12 green.** Each stays green because another check refuses its
  cases by the same name at the same place:
  - in the golden auditor's order too:
    - a block-starting line whose block is behind: the next rule of
      "A line that is not the one expected" says `line-unexpected`;
    - a decimal's spelling, read again with its size;
    - zero spelt 0/3, which is not in lowest terms either;
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

**The cases.** There are twelve, each small: 2 to 4 lanes, and 2 to 8
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

The corpus's data is about 153 KB: 170 files and 152,611 bytes besides
corpus.py (152,617 until step 5 made the manifest's three `golden`
words `both`, and 145,061 before the fixes round's cases, both
2026-09-30).

**The files.**
- `certificates/MANIFEST`: every case, every file it names, and each
  file's SHA-256.
- `certificates/images/`: every image a run names. The gate assembles
  each again from its source and requires the same bytes:
  - a library image from `programs/`, whose digest `programs/MANIFEST`
    also carries;
  - a wider run's from its main run's source, with the `.format` line a
    rung up;
  - the corpus's own from `certificates/programs/`.
- `certificates/<case>/<case>.cert`: the certificate.
- `certificates/<case>/states/run-<r>-boundary-<b>.bin`: every boundary
  of every run, lane-major, as cft-segrun writes them. Handed whole, the
  directory serves a sampled audit; its boundary-0 files alone serve a
  full audit from the initial states.
- `certificates/<case>/run-<r>.bank`: a bank that is no library file, a
  half-step run's halved bank or a wider run's widened one.
- `certificates/example.salt`: the example salt, 00 01 .. 1f. This page
  prints it, so it is a test salt only, and never an owner's.
- `certificates/corpus.py`: `make` writes the corpus, and `check` is its
  gate.
- Git keeps the bytes: a certificate is `-text`, and the states and the
  salt are `binary` (.gitattributes).

**The manifest** is text in a certificate's own style: printable ASCII
and LF, one record a line, its key first, single spaces. It takes two
liberties: `#` begins a comment line, and blank lines separate cases.
Paths are from the repository's root.
- Its first record, after the comment lines at its head, is
  `cft-golden-corpus 1`. Then comes `source <path> <sha256>`
  for each of the corpus's own programs, and `image <path> <sha256>
  library <name>` or `image <path> <sha256> source <path> [format <fmt>]`
  for each image.
- A block for each case follows:
  - `case`, then `what`, a sentence for a person;
  - `certificate <path> <sha256>`;
  - `mode`, and for a keyed case `salt <path> <sha256>`;
  - `depth`, and `backends any` or `backends software`;
  - `accuracy 0 none`, or `accuracy <A> both` when the case has A
    entries. `both` says both writers make them: the golden writer, and
    cft-segrun handed each entry's definition, each held to the
    committed bytes. Until step 5 the word was `golden`, the golden
    writer's alone;
  - `verdict accepted` or `verdict refused <name>`;
  - `states <dir>` and `runs <R>`.
- Each run follows its case's lines:
  - its `run` line as the certificate spells it;
  - `image <path>`;
  - `bank <path> <sha256>` or `bank none`;
  - `segments`, `steps`, `parameters` and each `parameter`;
  - a `boundary <b> <sha256>` line for each boundary, the SHA-256 of the
    state file's bytes, not the certificate's tagged hash.
- corpus.py's `read_manifest` reads it strictly and names the line of
  any departure. Another gate may import it.

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

It is 156 checks, 21 to 32 s on the Windows desktop, niced. The
slowest was with the desktop at about 77 % from other work (2026-09-29).
With the fixes round's cases it was 21 to 23 s (2026-09-30), and with
the tool making the accuracy cases whole, 22 to 25 s (2026-09-30).

**Changing it.** A change that moves any byte of the corpus fails the
gate by name: a change to the model, a hash, an encoding, the assembler's
output, or the `programs/` sources and banks the corpus names. When the
change is meant, its commit runs `corpus.py make` with a clean build of
cft-segrun, and says so. `make` keeps a case's committed certificate,
byte for byte, where the one it makes equals it but for `build-id` and
the hash line, and every boundary file has the committed manifest's
digest. So a case's bytes, and the commit its `build-id` names, move
only when what it certifies does (the fixes round, 2026-09-30). `make
--rewrite-all` writes every certificate the tool makes.

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
  its fourth section).

The corpus is described here and committed in this repository, and
published nowhere else. Publishing it outside this repository needs
Logan's permission.

**What it does not hold yet.**
- A certificate made on a tile. The lead's, later: a deepwrap case from
  the revision-7 single, whose CAPS2 reads 2,048, would join with the
  card's device lines.
- One made through a remote handle.
- Streams other than +0, which cft-segrun does not take.

## What version 1 does not do

- **Sign.** The detached signature is reserved, and no scheme is
  defined.
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
