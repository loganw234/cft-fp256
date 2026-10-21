# Signed sweep records

`hw/sweep_record.py` turns the finished slices of the card stress driver's sweep
into records that an owner's key signs and anyone can verify. It is the
record, the signature and the verifier of
[the sweep study](studies/SWP-A-coverage.md) (sections 5.3 and 6.6), built for
what Logan answered to the study's question 6 on 2026-10-20: "At the moment
only my device, though built to support a signing key would be good". One owner,
one device, a signing key; a second owner is a second line in a keyring and
changes nothing in the format. The store, the fold, the replay verifier,
honeypots and quorum are the study's ranks 6 and 10 and are not here.

Two versions of the record are known. **Version 1** is the slice or stream a card
image computed and the campaign they are slices of. **Version 2**, since
2026-10-21 (parcel SR2), is one more form: the slice or stream the **host pool**
computed, on the CPU, whose subject is the host build instead of a card image.
Logan asked for it ("10. Yes, change now for DR3's issue", the card scheduler
study's question 10, 2026-10-21); the section "Version 2" below says what it
adds and why it is a version of its own, and every other section is version 1's,
which version 2 leaves as it was.

```bash
python hw/sweep_record.py export RUN --out FILE (--key KEY | --device-key HEX)
python hw/sweep_record.py sign   FILE --key KEY --out FILE2
python hw/sweep_record.py verify FILE... [--keyring RING] [--allow-unsigned]
python hw/test_sweep_record.py [--metrics RUN_OR_FILE]       # the test, by hand
```

Marks, as everywhere in the record: MEASURED (a run, named), READ (a file,
named), COMPUTED (arithmetic on those), BELIEVED (unverified).

## What it reads

A run's `metrics.jsonl` (RUN is the directory, or the file). Three kinds of
record matter: `run_start` (the run's id, the commit and whether the tree was
clean, each image's SHA-256 and tile count and, since 2026-10-20, the `host/` tree and the compiler), `build` (the tools were held to the
tree: a leg with no passing `build` since its `run_start` is refused) and the
`leg` records of kind `sweep` that finished with a verdict, status `pass` or
`fail` (the driver's own definition of a covered slice, `sweep_coverage` in
`hw/card_stress_lib.py`). Every other record is ignored without error:
telemetry, cycles, events, battery legs, a record type no one has written yet.
A sweep leg that did not finish (timeout, no device, parse error) is counted
and named in what `export` prints, and is no record. A leg that says it finished
(`pass` or `fail`) but has no sweep block or no counts is refused (`metrics`), not
dropped. A run whose `run_start` says `dry_run` is refused: its legs came from
stand-ins. A finished sweep leg of the host pool (image `cpu`) is read too: it is a
version-2 record ("Version 2", below), and it is refused (`metrics`) where the run
recorded no `host/` tree.

## The record, version 1

This section, "The campaign record" and "Identity and signature" are version 1's
and stay its contract; "Version 2" adds what version 2 adds and changes none of
it. A version-1 record is a card slice or stream (the subject is a card image) or
a campaign.

One record is one JSON object on one line, in canonical form (below). There are
three kinds. A **slice** is an exhaustive item's finished `[lo, hi)`; a
**stream** is a random item's finished `(seed, count)`, which the study (5.8)
says never merges with an enumeration and counts only toward the floor of its
own distribution; a **campaign** says what a slice or stream is a slice of.

Every field below is READ from the leg or `run_start` named, never defaulted:
a field the data cannot fill is **absent**, not 0 and not null.

| field | in | what it is | read from |
|---|---|---|---|
| `v` | all | the version, 1 | |
| `kind` | all | `slice`, `stream` or `campaign` | |
| `id` | all | SHA-256 of the canonical bytes without `id` and `sig` | COMPUTED |
| `cid` | slice, stream | the id of the campaign record it is a slice of | COMPUTED |
| `lo`, `hi` | slice | the encodings `[lo, hi)` | `sweep.lo`, `sweep.hi` |
| `seed`, `count` | stream | the tool's arguments | `sweep.seed`, `sweep.count` |
| `cases`, `vm`, `fm` | slice, stream | cases compared, value mismatches, flag mismatches | `counts` |
| `skipped` | slice | pairs skipped, only where the tool's verdict line says what it covered | `counts.skipped` |
| `subject.image`, `.xclbin` | slice, stream | the image's name and SHA-256 (held equal to `run_start`'s) | `image`, `image_sha256` |
| `subject.tiles`, `.tile` | slice, stream | the image's tiles; the tile the job ran on, absent when none was recorded | `run_start.images`, `sweep.tile` |
| `tool.commit`, `.dirty` | slice, stream | the driver's checkout at the run's start: its commit and whether tracked files differed | `run_start.tree` |
| `run.id` | slice, stream | the run's name (the output directory's) | `run_start.run_id` |
| `run.device` | slice, stream | the device pseudonym of the key (below) | COMPUTED |
| `run.start_ms`, `.end_ms` | slice, stream | the job's own times, UTC milliseconds | `start_epoch`, `end_epoch` |
| `run.rate` | slice, stream | cases a second over the job's own time, rounded; absent when the leg has none | `rate.value` |
| `run.log` | slice, stream | the leg's log, a path relative to the run directory | `log` |
| `disagreements` | on a finding | the tool's first lines about the mismatch (at most 16) | `disagreements` |
| `sig` | optional | `{alg: ed25519, key, sig}` | COMPUTED |

The times are the epochs, never the strings: the driver's `ts`, `start` and
`end` are the host's local time and carry no zone (READ in
`hw/card_stress_lib.py`, `iso`; the 2026-10-19 run's `run_start` has local
19:36:47 and epoch 1792463807.507, which is 02:36:47 UTC, so the box ran at
UTC-7: MEASURED on that record).

**What section 5.3's record has and version 1 does not**, each because the run
does not record it:

- `digest`: the soak tools print no per-batch digest (the study's rank 6).
- `control`: the driver does not run the sabotage control per slice or session.
- `oracle` (libm, CPU, the probes' verdicts): `run_start.host` is a node name,
  which no record carries, and the probes' verdicts are text in the `build`
  record. The oracle's *kind* is in the campaign.
- `stratum`, `enumeration`: they do not exist yet; the items are the identity
  enumeration of the whole space.
- `subject.rtl` and `subject.abi`. **The RTL tree hash is not recorded** (READ:
  `run_start.tree` is the driver's checkout, whose commit is the host-side
  tools'; each image is `sha256`, `bytes`, `tiles`, `path` and `target`).
  Logan's answer to the study's question 4 is coverage per tree with the three
  images reported separately, so a reader has the images' hashes and names, and
  no tree. What it would take: the driver
  reading each image's manifest at `run_start`, which `hw/rebuild-2022.sh`
  writes beside the xclbin (`sha256:`, `commit:`, `bitstream_sources:`, READ),
  and recording `git rev-parse <commit>:rtl` of a full clone; or a table in the
  repository from image SHA-256 to commit. Neither is done, and nothing here
  computes the hash from a checkout.
- `tool.build_id`, `.cc`, `.flags`: the `build` record holds cft-segrun's build
  id, not the soak tools', and no compiler or flags. (A version-2 host record
  carries the compiler's line, `subject.cc`, which `run_start` has recorded
  since 2026-10-20.)

Today's data for one real slice, the first of the 2026-10-19 run, unsigned,
with the device of the test's throwaway key A (public key
`b93a34db38a13f7261a5ddcdec500ebc681f244a8cf11edf37b3e022d1b0c4b9`, its secret
derived from a label in `hw/test_sweep_record.py`, so nobody's), on one line as
it is written (`export RUN --out FILE --device-key` that key, MEASURED):

```
{"cases":1048576,"cid":"c2aaacbea9016dc8da1472d1a71f15e161d49bdecdb2db6cadc4177a4fb3edc1","fm":0,"hi":1048576,"id":"1cfcf540935fc48234c7cb15ef0a3d9f07a23c36011ca3e012374ec9db701fd7","kind":"slice","lo":0,"run":{"device":"fcd1dfc0b3edff2d","end_ms":1792465491677,"id":"card-stress-1019","log":"logs/c0001-00013-sweep-conv32to64-all.log.gz","rate":1204647,"start_ms":1792465490807},"skipped":0,"subject":{"image":"quad","tile":1,"tiles":4,"xclbin":"4f9921a25af65444abc5c267fff1117a8e14abbc16a75de643e43c9dbf6ef53b"},"tool":{"commit":"881bbcb676bbede9da20858325b7a966c56a25bf","dirty":false},"v":1,"vm":0}
```

## Version 2: the host-pool slice, and the version rule

Since parcel DR2 (2026-10-20) the stress driver runs the host items on a pool of CPU
workers, and each finished one is a `leg` record on the image `cpu`, which has no
xclbin. Version 1's subject is a card image and the SHA-256 of its xclbin (`subject.image`,
`.xclbin`, `.tiles`), so the exporter refused each host slice by name, and parcel DR3 (2026-10-21)
counted them and said so once. The card scheduler study put it to Logan with the signing
questions (question 10); his answer, 2026-10-21, verbatim: "10. Yes, change now for DR3's
issue". His earlier word on signing still holds: one owner and one key, the box's.

**The version rule.** A record's `v` is the version of the form it is written in, and a form
changes only by getting a new version.

- **Version 1** is the card slice, the card stream and the campaign, as they have always been
  written. Nothing of them changed: a version-1 file written before this change verifies, and a run
  exported now gives for every card slice the bytes it gave before (below, MEASURED).
- **Version 2** is ONE more form: the slice and the stream of a host-pool job. It differs from
  version 1's in `v` and in `subject`, and in nothing else. **A campaign has no version 2**: an item's campaign is
  version 1's record, the same record whoever computed a slice of it, so no campaign id depends
  on the version of the records that name it (and a host item's campaign says what it always said:
  `reach` host, the oracle kind `host-fpu+glibc`).
- **A record is the version its subject needs, never both.** The exporter writes version 2 for a leg on
  the image `cpu` and version 1 for every other, and has no path that writes a version-2 record of a card
  slice. The verifier refuses a card subject in a version-2 record and a host subject in a version-1 one
  (`form`, saying which a card slice is, which a host-pool slice), and a host-pool record whose campaign's `reach`
  is `tile` (`campaign`: a host build computes nothing the tile does, so its subject is no evidence about
  that campaign). The other way is not refused: until the host pool existed the card swept the host items
  too, and a card image's slice of a campaign whose reach is `host` is a valid version-1 record (MEASURED: 232 of the
  2026-10-19 run's 552 slices are of its 14 host campaigns, 22 campaigns in all).
- **`verify` takes every version it knows, versions 1 and 2, and refuses any other by name**,
  `version`: "version 3; this verifier knows versions 1 and 2". A campaign record that says version 2 is
  `form`. The signature's domain string, `cft-sweep-record 1`, is the domain's own number and not the
  record's: the id covers `v`, so a version-2 record's id is no version-1 record's, and the signature is unchanged.

**Why a version 2 for the host records only** (the brief left the choice open). *A version 2 for every
slice, with the subject either form* would make a card slice exported from now on a version-2 record with
another id, and the card slices DR3's driver writes, the real run's export and every fixture would be
re-made for a change of format Logan has not asked for. *A second subject shape inside version 1* changes
no byte, but a verifier of the old code reads the new line and says `form`, "'src' is not a field of version 1's subject":
a record that looks broken, where it is a record it cannot read. With a new version the old verifier says what
is true. MEASURED: the verifier of 77c5dbca (DR3's merge), given a file of both versions, says "refused version: ...
line 5: version 2; this verifier knows version 1". So: a version 2 for the host records only. Nothing existing moves, the
only new bytes are the host records', and a version-2 record of a card slice cannot appear by accident.

**The subject of a host-pool record** says what computed the slice: the host library's source and how it was built.
The key is DR2's, coverage by tree, which Logan kept on 2026-10-21 (the study's question 8, "keep the coarse key"): the
`host/` tree hash and the compiler, as the report keys a host item. Every field is READ from `run_start.tree`, never
defaulted; a field the run did not record is **absent**, not False and not null.

| field | in | what it is | read from |
|---|---|---|---|
| `v` | slice, stream | 2 | |
| `subject.src` | slice, stream | the git tree hash of `host/` at the checkout's HEAD, 40 hex (64 in a SHA-256 repository). **Required**: a host-pool slice whose run recorded none is refused | `run_start.tree.host_src` |
| `subject.dirty` | slice, stream | whether `host/` differed from that tree, untracked files included. Absent where git could not say | `run_start.tree.host_src_dirty` |
| `subject.cc` | slice, stream | the C compiler's first version line: text of 1 to 256 characters, no control character. Absent where the run could not read it | `run_start.tree.cc` |

Every other field (`cid`, `lo` and `hi` or `seed` and `count`, `cases`, `vm`, `fm`, `skipped`, `tool`, `run`, `disagreements`,
`sig`) is version 1's, read from the leg and `run_start` the same way: `tool.commit` and `.dirty` are the driver's checkout
at the run's start, and `run.device` the key's pseudonym. The leg is stamped with the `run_start` in force for it, the last
before it in the file (a resumed run writes one for each invocation). A leg on the image `cpu` has no image hash and no tile,
and the exporter holds it to that: **a card slice dressed as a host-pool one** (an `image_sha256` or a tile on the image
`cpu`) **and the reverse** (a card image's leg carrying the host pool's mark, `sweep.pool`) are refused, `metrics`, each
saying what it is, as is a host-pool slice of an item whose reach is `tile`. Every refusal leaves the exporter as it was.

What a host-pool record does **not** say, which the run does not record and which is therefore absent and not invented:

- **The machine.** The campaign's `oracle` says the kind, `host-fpu+glibc`: the host's FPU and libm, on the machine that ran the
  slice. `run_start.host` is a node name, which no record carries (the device pseudonym says which key, not which machine),
  and `run_start` holds **no CPU model, no libm or glibc version and no operating system**. A host record says which source
  was built with which compiler, not on which CPU or against which libm. The compiler's line often names the distribution's
  package (the 2026-10-19 run's second `run_start` has `cc (Ubuntu 13.3.0-6ubuntu2~24.04.1) 13.3.0`), which is a hint about the
  system and says nothing of its libm.
- **The flags.** The XRT flags and the roundeven probe's `C5DEFS` are text in the `build` record's steps; the tools' build id the
  driver held equal to the tree's (`sweep.pool.build_id`: it asks cft-segrun for it, not the soak tools) is not in the record
  either: the exporter requires a passing `build` record since the `run_start`, which is that assertion.
- **What `cc` is.** What `$CC --version` (or `cc`) printed when the run started, which is what `host/Makefile`'s `CC ?= cc`
  builds with unless the make was told otherwise; nothing asks the binary.

A host-pool record, from the test's synthetic run (a real run has none: the 2026-10-19 run is the card's, and its second
`run_start`, the only one that recorded a `host/` tree, ran no host slice), unsigned, for the test's throwaway key A, on one
line as it is written. The tree hash and the commit are made up:

```
{"cases":1048576,"cid":"c2aaacbea9016dc8da1472d1a71f15e161d49bdecdb2db6cadc4177a4fb3edc1","fm":0,"hi":1048576,"id":"c8e2ef97a89ee55459cf2fb5fe3f505f2a96fb6018220eb72d8eb1151b2b9fde","kind":"slice","lo":0,"run":{"device":"fcd1dfc0b3edff2d","end_ms":1792300033000,"id":"card-stress-host-1","log":"logs/c0001-00003-sweep-conv32to64-all.log.gz","rate":524288,"start_ms":1792300031000},"skipped":0,"subject":{"cc":"cc (Ubuntu 13.3.0-6ubuntu2~24.04.1) 13.3.0","dirty":false,"src":"a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1"},"tool":{"commit":"1111111111111111111111111111111111111111","dirty":false},"v":2,"vm":0}
```

Its `cid` is the campaign the card image's slice of `conv32to64-all` names, `c2aaacbe...`, the one below.

**MEASURED, version 1 is byte for byte what it was.** The 2026-10-19 run's `metrics.jsonl` (the copy of the lead's, sha256
`38f243c7...`), exported by the code of 77c5dbca and by this parcel's with the same throwaway key: `export --key` and `export --device-key`
each give the same 574 lines (552 records and 22 campaigns), sha256 `69a67871...` signed and `97896ddf...` unsigned, equal
under `cmp`. The campaign ids of all 125 items of the catalog (the 90 of the scripts and the 35 of the coverage wave) are one
digest, `2e8d9608...`, at both. The suite holds both: the synthetic card-only run's whole export hashes to what the code of 77c5dbca gave,
and the 125 campaign ids to the digest (`hw/test_sweep_record.py`, `hw/test_card_stress.py`, group `records`).

## The campaign record

Its SHA-256 is the `cid`: the whole record without its `id`, in canonical form.
It is written once into the file, before the first slice that names it, and a
slice's verifier needs it, since the rule a slice's counts are held to is in it
and a hash cannot be replayed. A campaign is not coverage and carries no
signature: its hash is its identity.

| field | what it is | READ from (`hw/card_stress_lib.py`, `Item`) |
|---|---|---|
| `operation`, `attribute` | the soak's job word; the rounding-mode word, absent for a job that takes none | `op`, `mode` |
| `sweep` | `exhaustive` or `random` | `kind` |
| `tool`, `args` | `clause5-soak` or `divsqrt-soak`; the argument form, `op lo hi [mode]` or `op count seed [mode]` | `tool`, `argv` |
| `oracle` | `host-fpu+glibc`: the soaks compare with the host FPU and libm (the study, 2.5) | |
| `reach` | `tile` or `host`: whether the job's work runs on the card's tile at all | `reach` |
| `space` | exhaustive only: the indices are `[0, space)`: 2^32 encodings for the fp32-operand items, the mode's own index count for a hard-case or class-level item (21,235,788 for `div32-hard`, 35,840 for `rint64-class`, ...) | `space` (`EXH`, 2^32, where an item has none) |
| `exact`, `extra_cases`, `per_encoding` | exhaustive only: the count rule (below) | `exact`, `extra_cases`, `per_encoding` |

The count rule is the driver's, not a second one: `parse_soak`'s. Where `exact`,
a slice has `(hi - lo) * (per_encoding or 1) + extra_cases` cases
(`nextup32` and `nextdown32` add 8). Where the tool says what it covered
(`per_encoding`), `cases + skipped` is `per_encoding * (hi - lo)`, and `skipped`
is carried exactly then (`cvtto32-all` compares in-range pairs only, so it is
not `exact`, and a slice that skips every pair, with 0 cases, passes). Otherwise
a slice or stream must have more than 0 cases. The test holds
this to `parse_soak` itself on 1,233 (item, interval, cases, skipped) points of
the catalog's 90 items, with 0 disagreements (MEASURED).

A campaign is built from the item and nothing else, so anyone can rebuild it.
`conv32to64-all`, the study's first exhaustive conversion, is

```
{"args":"op lo hi","exact":true,"kind":"campaign","operation":"conv32to64-all","oracle":"host-fpu+glibc","per_encoding":1,"reach":"host","space":4294967296,"sweep":"exhaustive","tool":"clause5-soak","v":1}
```

and `printf '%s' LINE | sha256sum` of exactly that line, with no newline, is
`c2aaacbea9016dc8da1472d1a71f15e161d49bdecdb2db6cadc4177a4fb3edc1`, the `cid` of
every slice of that item in the run (MEASURED). Section 5.2's stratum and
enumeration are not in it.

**A host item's campaign** says `reach` host and the oracle kind `host-fpu+glibc`, as every host item's has since
version 1, and it is the same record for a slice a card image computed (before the host pool) and a slice the pool
computed (version 2): the item is the same job, so the campaign, which is built from the item and nothing else, is the
same bytes and the same `cid` whether a host slice is exported alone or with the card's. The test holds it
(`conv32to64-all`'s `cid` is `c2aaacbe...` in a card-only run, in a file of both, and exported alone) and holds all
125 items' campaign ids to one digest taken at 77c5dbca. A later version adds them; that changes the hash, so
it is a new campaign, which is the rule ("coverage never merges across a change
of definition"), and a run's `metrics.jsonl` is exported again under it.

## Identity and signature

**Canonical form.** Keys sorted, no spaces, ASCII (anything else as `\uXXXX`),
integers only and none above 2^53 - 1, so that any reader holds them exactly;
no float, no null; one record a line, each line ended by LF. A record whose
bytes are not that form, however it parses, is refused (`canonical`): that is
how a file written with CRLF line endings and a pretty-printed record are
caught; a float or a null is not in version 1's form at all (`form`).

**The id** is the SHA-256 of the record's canonical bytes without its `id` and
`sig`. The record carries its id, so a changed byte is seen without a key.

**The signature** is Ed25519 (`python/cft_golden/ed25519.py`, RFC 8032) over
`cft-sweep-record 1`, a NUL, and the 32 bytes of the id. A certificate's
signature is over `cft-signature 1`, a NUL and the body hash
(`docs/CERTIFICATES.md`, "The detached signature"): two messages that differ in
their first bytes and their length, so that neither signature verifies as the
other, even over the same 32 bytes. The test shows it on the committed
certificate `certificates/signed-fp64/signed-fp64.cert` and a throwaway key:
- the certificate's own signature, written as the `sig` of a record line with
  that record's own id, gives `signature` from `verify`: it signs the
  certificate's body hash, which is not that id;
- a signature made under the certificate's domain over the record's own id gives
  `signature-domain`, and the same key's record-domain signature over that id
  verifies;
- the other way, the key's record-domain signature over the certificate's body
  hash, written into a signature file for the certificate, is refused
  `signature` by the certificate reader;
- as a function call only, `check_signature` given the certificate's body hash
  as the id, which no file can have (a record's id is the SHA-256 of its own
  bytes), gives the committed signature `signature-domain`. That shows the two
  domains separating the same 32 bytes under one key, and no more.

**The device pseudonym** is the first 16 hex digits of SHA-256 over
`cft-sweep-device 1`, a NUL and the 32-byte public key. It is made from the key
and not drawn and stored, so there is no state to lose, `export` can make it
from a public key alone (`--device-key`), the verifier recomputes it and refuses
a `run.device` that is not the signing key's (`device`), and a record cannot
claim another device's label without that device's key. It keeps the host's name
out of the record and hides nothing else: anyone holding a signed record can
compute it from the key. It says which key, not which machine: an owner with two
devices has two keys, which a keyring can name as one holder.

## Keys

**Never in the repository.** `export --key` and `sign` refuse a key file whose
path lies inside a git working tree, any ancestor with a `.git`, or inside this
repository, by name (`key-in-tree`), before the file is read.
`python/cft_sign.py keygen` has no such rule, writes where it is told to, and is
not changed by this parcel: the refusal is at the use.

**Making a key**, once, by its owner, on the machine that will sign (for the
driver's own records, the box that runs it), into a directory outside every
repository:

```bash
mkdir -p ~/.cft/keys && chmod 700 ~/.cft/keys
python python/cft_sign.py keygen --out ~/.cft/keys/sweep.key    # prints the public key, never the secret
printf 'key %s %s\n' "$(python python/cft_sign.py public --key ~/.cft/keys/sweep.key)" Logan%20W. > sweep.keyring
```

The key file is `cft_sign.py`'s own: `cft-signing-key 1`, `scheme ed25519`,
`seed <64 hex>`, `key <64 hex>`; written new, never over a file, mode 600 on
POSIX, where a file group or others may read is refused (`key-file`). On Windows
the mode is not checked (ACLs, as `cft_sign.py` says), so the directory's
protection is the user's. The keyring is public: lines `key <64 hex> <holder>`,
the holder spelled as in `docs/CERTIFICATES.md` (a space is `%20`). It is the
verifier's input, not the record's: `verify --keyring` refuses a record whose key
it does not name (`key`), and prints the holder where it does. Without a keyring
the signature is checked against the key it carries, and the output says that
nothing names whose it is.

What this does not do: **rotate or revoke** (drop the key from the keyring and
its records fail `key`, with no way to tell which were signed before a theft,
since a signature carries no time); and it is **not constant-time** (the
Ed25519 module says so: signing on a machine an adversary can time leaks the
key; this is the project's own machine). A driver that signs as it records holds
the secret in memory and the key file readable by its user for the length of the
run.

## Export, sign, verify

```bash
python hw/sweep_record.py export /data/card-stress-1019 --out sweep-1019.jsonl --key ~/.cft/keys/sweep.key
python hw/sweep_record.py verify sweep-1019.jsonl --keyring sweep.keyring

python hw/sweep_record.py export RUN --out unsigned.jsonl --device-key <public key>   # signed elsewhere, later
python hw/sweep_record.py sign unsigned.jsonl --key KEY --out signed.jsonl
python hw/sweep_record.py verify unsigned.jsonl --allow-unsigned
```

`export` writes a file it creates new (an existing one is refused: `output`).
With `--key` it signs; with `--device-key` it names the device that key will
make and leaves the signing to `sign`, which gives the same bytes as
`export --key` (Ed25519 is deterministic: MEASURED, byte for byte). `sign`
verifies first, so a key never signs what would not verify, and refuses a record
that names another key's device (`device`) or is signed already (`signed`).
A signature made after the run attests the export, not the run's time.

`verify` holds a file to the rules, as one run's records: first every line, for
the whole file, its syntax, version, canonical bytes, form and id; then, for each
slice or stream in turn, that it is of the run the file is (`splice`), its
signature and key and device, its campaign, its counts and its run block. It prints a line a file and exits:

| exit | meaning |
|---|---|
| 0 | every record verifies, none is a finding |
| 3 | every record verifies, and some are findings: each is listed, as `FINDING` |
| 2 | a refusal, `cft-sweep: refused <name>: <why>`, with the line and the record's id |
| 64 | usage: a command line, a file or a keyring it cannot take; a key file it will not use |
| 73 | `output`: the file to write is there already |

Signatures are required unless `--allow-unsigned`, which says `UNSIGNED` and
that the records are attributed to no one. On the 2026-10-19 run's real
`metrics.jsonl` and a throwaway key (MEASURED, the desktop, as commands with
their 0.4 s of start-up): `export --key` 1.5 s for 378 slices and 22 campaigns,
`verify --keyring` 1.6 s, exit 0, "378 clean (978480791566 cases), 0 FINDINGS",
the case total the sum of the raw legs' (computed by a separate script).

## The refusals, by name

| name | exit | what it refuses |
|---|---|---|
| `canonical` | 2 | a line whose bytes are not the record's canonical form: spaces, order, CRLF, non-ASCII, a missing final LF |
| `version` | 2 | a record of a version this verifier does not know: it knows 1 and 2 (checked as soon as the line parses, before its canonical bytes and its fields) |
| `form` | 2 | not a record of its version and kind: a field missing or not in that version, a float, a null, a path that is not relative; a card subject in a version-2 record and a host subject in a version-1 one (a card slice dressed as a host-pool one, and the reverse), a version-2 campaign |
| `id` | 2 | a record whose bytes do not hash to its id |
| `signature` | 2 | no signature where one is required, or one that does not verify |
| `signature-domain` | 2 | a signature that verifies under the certificate's domain `cft-signature 1` and not the record's |
| `signer` | 2 | a key of small order or no point; a keyring that breaks its form (the certificate reader's own name for these) |
| `key` | 2 | a key the keyring handed does not name |
| `device` | 2 | `run.device` is not the pseudonym of the key; at `sign`, a record that names another key's device |
| `splice` | 2 | a record of another run, or another device, in a file that is one run's |
| `campaign` | 2 | a record naming a campaign that is not in the file (which is what a campaign record altered, its id fixed, becomes), or one of the other sweep kind; a host-pool record whose campaign's reach is `tile` (the subject kind does not match the item's reach) |
| `counts` | 2 | counts that break the driver's rule for the campaign (`parse_soak`'s cover rule, `expected_cases`, 0 cases, an interval past the space) |
| `run` | 2 | an end before the start, or a rate that is not the record's cases over its own time |
| `signed` | 2 | `sign` was given a record that carries a signature |
| `metrics` | 2 | at `export`: a run it cannot read as the driver wrote it (a dry run, a leg that disagrees with the catalog, counts the driver would not have passed; a host-pool slice whose run recorded no `host/` tree, a card slice dressed as a host-pool one or the reverse, a host-pool slice of a tile item, a compiler line a record cannot hold) |
| `empty` | 2 | no finished sweep slice to export; no slice or stream in the file to verify |
| `key-in-tree` | 64 | a key file inside a git working tree |
| `key-file` | 64 | a key file that cannot be read, is not `cft_sign.py`'s format, or that others may read (POSIX) |
| `usage` | 64 | a command line, file or keyring the command cannot take |
| `output` | 73 | the output file is there already |

Every one is watched firing by `hw/test_sweep_record.py`, which ends by
checking that no name in the table went unseen.

## A finding is a record, never coverage

A slice or stream that found a mismatch is a **finding**: `vm + fm` is above 0,
and the record carries the tool's first lines about it (`disagreements`). It is
a valid, signed record, and a failing slice is one: the driver's `fail` leg is
exported like a pass. A reader tells them apart by `vm` and `fm`; `verify` counts
them apart (clean, and FINDINGS), prints each finding with `never coverage`, and
exits 3. Section 5.4's fold takes a record as coverage only when it is
consistent (its counts hold) and clean, and `is_finding` in the module is that
second half for one record; a finding is a finding to re-check on the golden
model, not a hole to fill by running the slice again.

## What a signed record proves, and what it does not

**Proves**, to a verifier that trusts the keyring's line for the key (the
certificate's words, [CERTIFICATES.md](CERTIFICATES.md), apply: whoever holds
the secret vouched for these bytes):

- the record is exactly what was signed: a changed field, count or interval
  changes the id and breaks the signature, and the file's lines are the
  canonical bytes;
- it is of one run and one device, with a campaign that hashes to its cid, and
  with counts that follow the driver's rule for that campaign, an interval inside
  the space, times in order and a rate that is its own cases over its own time;
- whether it found a mismatch;
- for a **host-pool record** (version 2): that it says which `host/` source (`subject.src`, and `dirty`) and, where the run
  recorded it, which compiler (`subject.cc`) the slice is about, that the campaign is one whose reach is the host, and that the
  subject is no card image: a host build is not offered as evidence about a tile.

**Does not prove**, which is section 6.6's "What a record can never prove"
applied here:

- **that the slice was run**, or on the card, or by a specific device: a pass
  proves nothing by itself, and nothing on the U50 attests. Version 1 carries no
  digest to confirm against a second device and has no replay: a false pass is a
  false hole in the coverage, which only a replay or a second owner closes
  (rank 10). The honest statement of a coverage is "covered by K owners each
  replayed", and version 1 has one owner, unreplayed.
- **that no one ran the golden model in software and reported the card's
  identity** (section 6.6's second clause): a contributor can run it, slowly, and
  sign a record that names the card's image. The study's defence is a rate above
  the measured maximum for the operation and the tile count (6.6 says 1.5 times),
  which refuses the fast fabrications, and that a slow, honest-looking one costs
  the fabricator more than running the card (BELIEVED). Version 1 checks neither:
  its `run` rule compares a record's rate only with its own cases and times.
- **that the image named was on the card**: the driver hashed the file it passed
  to XRT and held it to its `SHA256SUMS`; nothing in the record shows what the
  card ran, and the tree the image's RTL came from is not in the record.
- **what the oracle was**: the CPU and libm are not recorded. For a host-pool record this is the machine, the whole of it: the
  campaign says the kind (`host-fpu+glibc`, the host's FPU and libm), the run records no CPU model, no libm or glibc version and no
  operating system, and the record does not invent one. A host record can be a pass on one CPU and libm that another's would not
  repeat, and says nothing to tell them apart but the key (`run.device`).
- **that the tool is the commit's build**: `tool.commit` is the driver's
  checkout, which the driver's build check held to the commit cft-segrun was
  stamped with; the soak binaries' own build ids and flags are not recorded. For a host-pool record, `subject.src` is the tree the
  driver RUNS FROM (`git rev-parse HEAD:host`), and it is the source the soak tools were built from because the build step
  held the tree to the tools' build id at the start, which is the only link the record has (a run whose HEAD moves is stopped,
  `tree_moved`, READ in `should_stop`; an uncommitted edit to `host/` after the start is not seen, since `dirty` is read once, at
  the start); `subject.cc` is what the compiler said when the run started, not what built the binary.
- **when it was signed**: there is no time in a signature. `run.start_ms` and
  `end_ms` are the driver's clock. Records exported from `metrics.jsonl` after
  the run vouch for that file as it was when exported; one signed as the driver
  records narrows the window, and holds the key for the whole run.
- **that nothing is missing**: nothing in version 1 signs the set, so a record
  dropped from a file is not seen (the test runs this as a known limit).
- **who holds the key**: the keyring is the verifier's own statement.

## From the driver

Parcel DR3 wired this into the stress driver on 2026-10-21 (this section said DR2 would; the plan moved it, and
DR2's work was the host pool, the seeds and the trees). `hw/card_stress.py --records`, with `--sign-key KEYFILE` or
`--device-key HEX` (unsigned records, for `sign` to sign later), does the following; what it calls:

```python
import sweep_record as SR
seed = SR.load_seed(KEY_PATH)                 # Refusal key-in-tree / key-file, by name, never a crash
ex = SR.Exporter(signer=SR.Signer(seed))      # or Exporter(public=<32 bytes>) for unsigned records
ex.run_start(run_start_record)                # the dict the driver writes as run_start, once a start
ex.build(build_record)                        # and as build
lines = ex.leg(leg_record)                    # for every leg record, as finish_leg writes it
# lines: [] unless a sweep leg finished with a verdict; else [campaign line (first time), record line]:
# whole lines in canonical form ending in LF, to append to a file beside metrics.jsonl
```

**How the driver calls it** (`RecordSink` in `hw/card_stress.py`). Every record the driver appends to `metrics.jsonl` goes to
the sink AFTER the append (`Driver.rec`, the one place every record passes): `run_start` to `ex.run_start`, `build` to
`ex.build`, and each sweep `leg` to `ex.leg`, whose lines are appended to `OUT/sweep-records.jsonl` in one write, so a slice is
never in the file without its campaign. The sink has a lock of its own (the card's thread and the host pool's workers finish
legs at once). **A leg the exporter refuses** (`Refusal`, named `metrics`) is an `event` `record_refused` in `metrics.jsonl` and
`driver.log`, with the refusal's name and reason, and the run goes on (the first 50 are named, the rest counted); a `run_start`
it refuses disables the sink with one event, `records_disabled`. **A host-pool slice** (image `cpu`) is offered to `leg()` like
every other finished slice, and since version 2 (2026-10-21, parcel SR2) it is a record: a version-2 slice or stream whose subject is the
host build `run_start.tree` recorded (`host_src`, `host_src_dirty`, `cc`: "Version 2", above), signed like a card slice. Where the
run recorded no `host/` tree (night 1 of the 2026-10-19 run: its `run_start` has `commit`, `dirty` and `dirty_files` and nothing
else) the exporter refuses it by name, `metrics`, and the sink says so as any refusal, an event `record_refused` (the first 50 are
named, the rest counted, and the summary has the counts). **The event `records_host_slices` is retired**: DR3's sink said it once to
say host slices were counted and not written, which is no longer true, so no driver after this one writes it (a `metrics.jsonl`
written by DR3's may hold one, and every reader ignores an event it does not know). The sink counts what it wrote by what computed it,
card and host: records, clean ones and their cases. **A dry run is refused twice**: at the
command line (`--records` with `--dry-run` is an argument error), and, if it ever got through, by `run_start`. The key is checked
at the command line too: `load_seed`'s `key-in-tree` and `key-file` refusals, by name, before anything starts; the secret is read
there and let go, and again when the sink is made, and is in no setting, record or log. On `--resume` the sink reads the file, takes its campaigns into
`ex.seen` (none is written twice), refuses a file of another device or run (`device`), and cuts back a torn last line. At the
end an event `records_summary` gives the counts, with the records, the clean ones and their cases by subject kind (`by subject: card N
record(s), N clean (CASES cases); host ...`), and `driver.log` the `verify` command. **The case total `verify` prints is the sum of
the clean slices' cases, the card's and the host pool's, which is the driver's own coverage of all the clean slices it recorded; it
prints the total by subject kind on a line of its own** (`by subject: card N clean (CASES cases); host N clean (CASES cases)`, with the
findings of a kind after it, and a kind a file does not hold as 0), and `records_summary` says the same figures. The tests hold the
three - the raw legs' sums, the sink's counts and what the `verify` command prints - to one another on a run that is
not a dry run (the tools of that run are test doubles in a scratch tree, which is the one way the exporter's refusal of a dry run
can be met without weakening it). The pass size is not in a record of either version: a `--sweep-chunk` run's streams are told from a
default run's by `metrics.jsonl` (`sweep.batch`, `sweep.chunk`) and not by the file.

`run_start` and `leg` raise `SR.Refusal` (name `metrics`) for a run or a leg that
cannot be records: a finished sweep leg (pass or fail) with no sweep block or no
counts, a time or a rate that is not a finite number (Infinity or NaN), a leg the
catalog disagrees with, counts the driver's rule would not have passed, a dry
run, a host-pool slice of a run that recorded no `host/` tree. A sweep leg that did not finish returns no lines and is counted in `ex.left`,
by status, whatever it lacks; a leg that is no sweep leg returns none. `leg`
leaves the exporter as it was after a refusal: the driver should log an `event`
and go on, since a record error must never stop a long run. After a
resume the exporter has seen no campaign, so it writes each campaign line again
(harmless: a repeated campaign line is the same record); fill `ex.seen` from the
file to avoid it. Cost per slice on the desktop (MEASURED, the 2026-10-19 run's
378 legs, a call each): `leg` 3.0 ms median signed (3.2 mean, 5.3 worst;
`Signer(...)` once, 1.5 ms) and 0.06 ms unsigned; a signed slice line is 853
bytes on average (837 to 860), 619 unsigned, a campaign line 299; about 2.8 MB
for a 60-hour run's 3,300 slices; `verify` 3.3 ms a slice.

## Known limits, version 1's and what version 2 changed

Version 1's, as they were, restated where version 2 changes them:

- The stream form has not been run on a real run's legs (the 2026-10-19 run is
  all exhaustive); it is held to synthetic legs in the driver's format. **Version 2 has not been run on a real
  run's legs either**: a real run holds no host-pool slice that could be signed (the 2026-10-19 file has no leg on the image
  `cpu` at all; its first `run_start` recorded no `host/` tree and its second ran no host slice), so the version-2 form is held to
  synthetic legs and to the driver's own run over test doubles, and the first real host record will be the first real one.
- The `build` record is required, and the item table is the exporting tree's:
  a run is exported from the tree it ran at, and `export` refuses a leg whose
  recorded expectations are not that catalog's.
- The case total `verify` prints is the sum of the clean records' cases, now of both subject kinds and told apart on its line by
  subject. Two slices of one campaign that overlap count twice, and nothing refuses an
  overlap or a gap: the fold (the study's rank 6) takes the union. A card image's slice and a host-pool slice of one host
  campaign are one campaign's slices, and their cases are counted together in that total: **the fold, not this version, keeps the
  two subjects apart** (a host item's key is `host/` tree and compiler, a tile item's the RTL tree).
- A resumed run's file is one run, as the driver names it: the same run id and
  device. Two runs given one id by the same key are not told apart.
- `splice` and `device` are the only protection of a file's membership; there is
  no manifest that names the set.
- **Copying is not seen.** Another key can re-sign the same content under its own
  device, which is a new record with a new id, and a fold that counts owners would
  count it as a second. Independence is what the replay verifier and the quorum of
  the study's rank 10 are for.
- A run made before the driver wrote `reach`, `expected_cases` or `expected_encodings`
  exports (a key an older driver did not write is no conflict, a key that is there
  must agree with the catalog). Only the 2026-10-19 run was to hand, so this is held
  to legs with those keys taken out, and that the 2026-10-16 run's legs lack them is
  BELIEVED.
- **A host-pool slice whose `run_start` recorded no `host/` tree cannot be signed** (refused, by name; the drivers before
  2026-10-20 recorded none). A slice is held to the `run_start` in force for it, so a resumed file whose `run_start`s differ in
  whether they recorded the tree has records for some of its host slices and refusals for the others.
- **The machine is not in a host-pool record**: no CPU model, no libm or glibc version, no operating system, no flags, no node
  name (by design: the device pseudonym stands for the key); `subject.cc` is the compiler's line as the run read it at its start; `dirty`
  is read once, at the start. The oracle's kind is in the campaign and its machine is not in the record ("Version 2").
- A card image's slice of a host-reach campaign (the old runs') and a host-pool slice of it have different subjects and one
  campaign; version 2 does not decide which counts for which tree, and does not merge them.
- The tests need no card, no XRT and no compiler; `--metrics` takes the copy of a
  real run (the 2026-10-19 run's `metrics.jsonl` is not in the repository) and
  without it that group is skipped by name.

## The test

`python hw/test_sweep_record.py [--metrics RUN_OR_FILE] [--only GROUP,...]` makes its own
temporary directory and removes it by that path, and its keys are derived from
fixed labels or made by `cft_sign.py keygen` there: throwaways. Groups: forms
(canonical form and shapes, the version rule), rules (the driver's rules, item by item), export
(a synthetic run in the driver's format, including records of types the
exporter does not know, and the read-back below), keys, domain, plants (each defect put into a signed
file, and the refusal it must draw; and the verifier without a check, which
lets its plant through), **host** (version 2: a synthetic run of card and host-pool slices, the
subject's fields read back, the campaigns and their ids, the totals by subject kind, each export
refusal with the exporter left as it was, each verifier refusal on a validly signed record so that only the check aimed at
can fire, and the verifier without `subject_problem` and without `check_shape`) and real. No runner stage runs it; one could
(the groups other than `real` need only Python and the repository, and take
seconds), and the stage counts are the lead's.

**The read-back reads the `run_start` in force.** A resumed run's file has one `run_start` for each invocation, and the
exporter stamps each slice with the one in force for it (the images, the run id, the tool's commit and dirty flag, and a host
record's tree can differ between them). `readback` re-derives every record from its raw leg and that `run_start`, by code
that shares nothing with the exporter. Before 2026-10-21 `real` took the file's first `run_start` for every leg, which failed
the 174 legs of the 2026-10-19 file's second invocation (0b7c9599 after 881bbcb6: SG's test, not a regression); it now holds
on the real file (`--metrics`), and in every run of the suite on a synthetic file of two `run_start`s of different commits, with its
plant, the first-`run_start` expectation, which must be red there at exactly the legs after the resume and on the tool's commit
alone (on the real file: the 174, MEASURED).

The driver's test (`hw/test_card_stress.py`, group `records`) runs the records through `RecordSink`, on a real dry run's stream
with the one flag that says dry changed, and on a real, not dry, run over test doubles; its plants for the format's version 2
run this test's groups from a plant's copy of the code (`SWEEP_RECORD_TEST_ROOT` names the tree that has `docs/`, `certificates/` and
`python/`).
