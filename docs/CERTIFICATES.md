# Certificates, version 1

A certificate is a text file that says what a deterministic run was and
how accurate it is: which program ran, on which inputs, cut into which
segments, which state each segment began and ended on, what flags it
raised, and what its accuracy is, of which kind. An audit checks that
statement by re-running segments on an implementation the producer does
not control, starting each from its certified start state. This page is
the whole of version 1. A reader and an auditor can be written from it
alone.

Where things stand (2026-09-28):
- the golden implementation is `python/cft_golden/cert.py`: encode,
  strict parse, the hashes, the chain and the audit, which re-runs
  segments with `seq.run`;
- its gate is `python/tests/test_cert.py`, run by the golden stage,
  with negative controls, each watched failing, for every mechanism
  but those "The controls" names as still without one;
- libcft names its build and its device image, `cft_build_id` and
  `cft_get_image_id` ([HOSTAPI.md](HOSTAPI.md), "Identity at ABI
  0.15");
- the segment runner, `cft-segrun`, writes version-1 certificates from
  the library (see "The segment runner"), and the `programs` stage
  holds them byte for byte to the golden writer;
- the C auditor is later work, in the plan of record:
  [ROADMAP.md](ROADMAP.md), "Segments, certificates and the audit
  tool".

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
  +1/3, 1/-3, 01/3 and 1/A are all refused as malformed.
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
width. That is the design's argument; no C auditor exists yet to measure
it against.

A narrower build is not a conforming auditor of exact values. The
bigint is 576 bits at an fp128 ceiling and 288 below
(`host/include/cft_config.h`). Such a build must refuse to audit a
certificate that carries an exact value, rather than audit it
differently.

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
| `parameter <name> <n>` | a non-negative integer parameter the bank does not carry: stated, not checked. Names strictly increasing in byte order. A real-valued parameter belongs in the bank, where the program digest covers it |
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
`seq.run(image, a, b, c, bank=bank, scratch_in=start)`, where:
- every lane is active;
- no index table and no lane mask are used;
- the streams are the run's;
- the start state is the segment's start.

Its end state is the run's `scratch_out`, its flag word the run's sticky
IEEE flags (invalid 1, divide-by-zero 2, overflow 4, underflow 8,
inexact 16) and its STATUS the run's STATUS word.

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
| `aux-image` | the same steps a segment, and the same image digest | the same steps, and an image that is the main image one format wider: the same instruction words, `max_deposits`, flags, constant count and scratch word, the precision code one rung up, and any constants the image carries exactly widened |
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
  - F0 is run 0's final state and Fr is run r's.
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
  in fp256, has a lower end whose denominator has 1,139 bits. It does
  not widen the pair. Any pair that holds the value is accepted.

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
  device lines to one another or to `backend`.
- Each may be `unknown`: the producer did not record it. A reader
  reports it as such.
- The device lines may be `none`: the field does not exist for this
  backend. The software backend has no xclbin and no registers.
- A run through a remote handle records the client's library build,
  since the server sends none, and the SERVER's device fields where
  the protocol carries them. A field it does not carry is `unknown`.
- The audit checks none of them and reports every one: stated, not
  checked, or unknown (see "What an audit proves").

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
past the width rule is `width`. An element's decimal that is not the
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
5. **Streams**, run by run: each of a, b and c, as handed or +0, is n
   values whose hash is the certified one (`stream`).
6. **Continuity**, run by run (`continuity`).
7. **States handed**, run by run and boundary by boundary: each is
   lanes x slots elements of a boundary that exists (`state-shape`),
   and its hash is that boundary's (`state-hash`).
8. **Relations**, run by run: all of run 1's checks in the order of the
   table under "Auxiliary runs", then all of run 2's, and so on
   (`aux-format` through `aux-start`, and `state-missing` when a wider
   run's check needs run 0's initial state). So run 1's `aux-start`
   comes before run 2's `aux-segments`.
9. **Re-runs**, run by run, the chosen segments in ascending order.
   - Each starts from its start state, handed or re-run into
     (`state-missing` when neither).
   - It must end on its certified end state (`segment-end`), with its
     certified flag word (`segment-flags`) and STATUS
     (`segment-status`).
10. **Accuracy**, entry by entry:
    - the run it uses exists and is of the right kind (`accuracy-run`);
    - its lane exists (`accuracy-scope`);
    - its terms' slots exist (`accuracy-slot`);
    - the states it reads are known (`state-missing`);
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

**The verdict** of an accepted audit says:
- ACCEPTED;
- the mode;
- for each run, which segments were re-run and how they were chosen.
  For a sampled run it gives the seed and the escape probability
  C(S-f, k)/C(S, k), with its value for f = 1;
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
| `malformed` | 2 | a value breaks its one spelling, its range or its token count, or a line breaks the byte rules; a count out of its own range; a writer asked to certify a run of no segments |
| `decimal` | 2 | an element's decimal is not the exact decimal of its hex |
| `accuracy-kind` | 2 | an entry's kind is not its method's; every `bound` in version 1 |
| `width` | 3 | an exact value past 1,023 bits in numerator or denominator: written, computed (an element's, a product, a partial sum, a difference), an enclosure's finite end, or one a writer was asked to round or enclose |
| `salt-missing` | 4 | the audit of a keyed certificate was handed no salt |
| `salt-unexpected` | 4 | the audit of an open certificate was handed a salt |
| `salt-length` | 4 | a salt that is not 32 bytes |
| `salt-commitment` | 4 | the salt handed is not the one the certificate commits to |
| `image-digest` | 4 | the image handed is not the one certified |
| `program-digest` | 4 | the image and bank handed are not the ones certified |
| `program-image` | 4 | no image was handed, the image does not load, or the bank is not the size it addresses |
| `program-format` | 4 | the image's format is not the run's |
| `program-shape` | 4 | the program is not a segment |
| `stream` | 4 | a stream handed (or +0) is not the one certified, or is bytes that are not whole elements |
| `state-shape` | 4 | a state handed is the wrong size, bytes that are not whole elements, or for a run or boundary that does not exist; a writer handed states and segment results that disagree in number |
| `state-hash` | 4 | a state handed is not the one certified at its boundary |
| `state-missing` | 4 | a state the audit needs was neither handed nor re-run into |
| `continuity` | 5 | a segment does not start where the one before it ended, or the output is not the last end |
| `aux-format` | 5 | an auxiliary run's format is not its relation's, including any wider run of an fp256 run |
| `aux-lanes` | 5 | an auxiliary run's lanes differ from the main run's |
| `aux-image` | 5 | an auxiliary run's image or steps are not the main run's, or the main run's one format wider |
| `aux-segments` | 5 | a half-step run without twice the segments, or a wider run without the same |
| `aux-h-slots` | 5 | a named h-slot outside the bank, or holding zero or a non-finite value there, or a main image that takes no bank |
| `aux-bank` | 5 | a bank that is not the main bank halved in exactly the named slots, or exactly widened |
| `aux-streams` | 5 | streams that are not the main run's, or its exactly widened |
| `aux-start` | 5 | an initial state that is not the main run's, or its exactly widened |
| `segment-end` | 6 | a re-run segment does not end on its certified end state |
| `segment-flags` | 6 | a re-run segment's flag word is not the certified one |
| `segment-status` | 6 | a re-run segment's STATUS is not the certified one |
| `accuracy-run` | 7 | an entry uses a run that does not exist, or one of the wrong kind |
| `accuracy-scope` | 7 | an entry names a lane the run does not have |
| `accuracy-slot` | 7 | a term names a slot the state does not have |
| `accuracy-finite` | 7 | an exact value needs an element that is not finite |
| `accuracy-value` | 7 | the value written is not the stated function of the certified runs |
| `choice` | 64 | the auditor asked for a sample, segment or run the certificate cannot give it, or handed a seed that is not 32 bytes |

A refusal locates itself where that means something: the line, for the
reader's refusals; the run and the segment or boundary, for the audit's.

## The controls

`python/tests/test_cert.py` holds the mechanisms above to negative
controls, and each control asserts the NAME of the check it exists for,
never merely that something refused. Every control but the byte flip
writes a valid hash line over its defective body. Otherwise the hash
check would refuse them all first, and a broken strict-form check would
pass unseen (verifier-C1). That a control can fail is measured, not
intended: each mechanism was disabled in turn in a copy of the
implementation, and a test went red for it (the round's ledger, P1.md;
verifier-C2 found fourteen that could not fail at first, and each has
its test now). Some still have no control. Verifier-C2's re-check of
P1b disabled these and every test stayed green (its ledger,
2026-09-28 11:43:01):
- the hex spelling of `device-xclbin` and `device-version`. The audit
  never reads those lines, so a broken check would pass a malformed
  one through the reader and the audit alike;
- the spelling of `stream-a`, `stream-b` and `stream-c`, of `output`,
  of a segment's start and end hashes, and of `salt-commitment`;
- in step 8, a run's `aux-image` checked before its `aux-segments`;
- the reader's key scan, its step 5, ahead of the mode, its step 6.
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
- each encoding's non-canonical spellings, and each range limit at its
  edge: 64 terms, h-slot 511 and term slot 65,535 read, one more not;
- the width rule, at the reader, at the writer, and at the audit on an
  element's own value, a product and a partial sum, and at an
  enclosure's ends;
- a decimal that disagrees with its hex, and a version of any size;
- each kind that is not its method's;
- the mode: an unknown mode, a missing or unexpected commitment, and a
  salt missing, unexpected or wrong;
- a wrong image or bank, stream, or state, and bytes that are not whole
  elements;
- a broken chain;
- a segment whose certified end, flags or STATUS differ;
- every auxiliary relation, including the main run attached as its own
  half-step run, a wider image's constants and header, and the
  relations checked run by run;
- every accuracy check, the values derived again from the states with
  none of the implementation's code, an estimate's last slot, and an
  enclosure's ends held inclusive;
- the audit's order, every adjacent pair of its steps from the choice
  to accuracy, and an auditor's seed never the certificate's.

The real audit is `programs/lorenz63-rk4-fp64.cfta` with its classic
bank:
- three lanes over four segments, with a half-step run of eight and a
  wider fp128 run of four, every chain built by `seq.run`;
- green in full, from the initial states alone, and sampled;
- red, naming segment 1, when a producer's boundary 2 is one bit wrong
  and it carries on from there.

## The segment runner

`cft-segrun` is the C writer, the plan's step 3. It runs a program as
consecutive segments on one libcft device handle, keeps the state at
every boundary, and writes a version-1 certificate. `make -C host all`
builds it, from `host/tools/segrun.c`.

    cft-segrun --out CERT --states DIR (--salt SALT | --open)
               [--device sw|<xclbin>|cft://host:port]
               --run main --image IMG [--bank BANK] --init INIT
                          --segments S --steps K [--param NAME=N ...]
               [--run half-step --h-slots I,J,... --image IMG ...]
               [--run wider --image IMG ...]
    cft-segrun --hash state|stream-a|stream-b|stream-c FILE (--salt SALT | --open)
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
- It writes `accuracy 0`. Accuracy is the plan's step 5.
- `--hash` prints one of the hashes above for a file's bytes, and
  `--build-id` the library's `cft_build_id()`. The gate holds the first
  to the test vectors above.

**The states.** Each boundary is written as it is reached, to

    DIR/run-<r>-boundary-<b>.bin

where r is the run and b the boundary, 0 the initial state and S the
output, both in decimal as the certificate numbers them. Each file is
the state's bytes, lane-major, the bytes its hash covers. The run
creates DIR, which must not exist before it, so two runs' states never
share a directory. An auditor is handed the directory with the
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

**Refusals.** Before anything runs, the tool refuses what the golden
writer (`cert.run_chain`, `certify_run`, `encode`) refuses, by the same
names and codes:
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
  is, and no run at all; and, at a segment, a flag word the library
  reports past the five sticky flags, which no reader could read;
- `line-unexpected` and `line-order`, for a parameter named twice, or
  out of byte order.

For two of these the golden writer has no name. An image that does not
load, and an empty initial state, each make it raise
`seq.ProgramError`, and the tool uses the table's `program-image` and
`state-shape`.

A writer needs three more, which the golden writer, an API rather than
a command, never meets. They are the tool's, in sysexits' codes, of
which 64 is already the auditor's usage:
- `usage`, exit 64: a command line the tool does not take, or a file it
  names that cannot be read;
- `device`, exit 69: the device does not open; it cannot read the
  sticky flags a certificate records (`cft_caps.flags_readable` 0); a
  digest, or a segment's run, fails; or the library leaves a segment's
  flag word unwritten;
- `output`, exit 73: the certificate or a state file cannot be written,
  or DIR exists already.

Every refusal prints `cft-segrun: refused <name>: <why>` and exits with
the name's code. None writes a certificate. One made before the first
segment leaves nothing behind. A run that fails part way leaves the
boundary files it wrote, and says so. No backend in this tree reports
flags it cannot read, leaves a flag word unwritten or reports one past
31, so `CFT_SEGRUN_PLANT` is an instrument for the tests of those three
refusals: `flags-unreadable`, `flags-unwritten` or `flags-wide`. Each
only ever causes a refusal, and says so.

**What it certifies, and what it does not.** It certifies what ran:
which states each segment started and ended on, as hashes, with its
flag word and STATUS as the library reported them, on the library build
and device the library names. It does not check an auxiliary run's
relation to the main run. A half-step bank that is not the main bank
halved is written as stated, and the audit refuses it (`aux-bank`). It
computes no accuracy, and it signs nothing.

**Its gate** is `host/tests/segrun_check.py`, `make -C host segruntest`,
which `verify/run.sh`'s `programs` stage runs. It certifies
`lorenz63-rk4`, `lorenz96-rk4` and `henonheiles-lf` at fp64 and fp256,
each image held to `programs/MANIFEST`, with its classic bank:
- beside each, a half-step run, the bank slots named H, H2, H6 or MH
  exactly halved, for twice the segments;
- beside each fp64 one, a wider run: the same source assembled at fp128,
  with the bank and the initial state exactly widened;
- and `flagstep`, a small program written in the gate, whose segments
  raise flags 20, 0, 1, 0 and 20 and STATUS 48, 48, 0, 48 and 48. Every
  ODE segment raises flags 16 and STATUS 0, so the ODE programs alone
  cannot tell a writer that drops STATUS, or writes one segment's flags
  against another, from one that does not.

Each program is certified keyed and open on the software backend. Then:
- the golden reader must accept each certificate;
- the golden writer, handed its identity lines, the salt and the initial
  states, runs every segment itself and must write the same bytes;
- every boundary file must be the golden chain's state;
- the golden audit must accept each, in full and sampled, from the
  states the tool wrote;
- the build-id line must be what the binary prints and what the tree
  builds, and the software backend's device lines `none`.

It also holds the test vectors, and each tag keyed and open against an
HMAC written from RFC 2104 in the gate. It holds every refusal by its
name and code, and the golden writer's name for the same defect where
it has one. Last, it makes one certificate through a loopback cft-serve,
stopped by its PID. That certificate's device lines must be the remote
rule's, and its run blocks byte for byte the software backend's. 283
checks, 45 to 55 s on the Windows desktop at about half load
(2026-09-28).

**On the card**, `hw/card-segrun.sh <image.xclbin>` runs the same gate
with the certificates made on the tile. It holds the device lines to
`sha256sum` of the image and to what `device-test -i` prints, and each
card certificate's run blocks to the software backend's. It has not
run yet: the card leg is the round lead's.

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
- **Certify cft-orbits' runs.** The plan's step 6 certifies Newton-route
  intervals, each a program image and bank this format holds. Its
  records carry no flags today (docs/ROADMAP.md).
- **Audit in C.** The C auditor is the plan's step 4. The build id (step
  2) and the segment runner (step 3) exist.
