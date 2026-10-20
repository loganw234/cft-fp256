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
clean, each image's SHA-256 and tile count), `build` (the tools were held to the
tree: a leg with no passing `build` since its `run_start` is refused) and the
`leg` records of kind `sweep` that finished with a verdict, status `pass` or
`fail` (the driver's own definition of a covered slice, `sweep_coverage` in
`hw/card_stress_lib.py`). Every other record is ignored without error:
telemetry, cycles, events, battery legs, a record type no one has written yet.
A sweep leg that did not finish (timeout, no device, parse error) is counted
and named in what `export` prints, and is no record. A run whose `run_start`
says `dry_run` is refused: its legs came from stand-ins.

## The record, version 1

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
  id, not the soak tools', and no compiler or flags.

Today's data for one real slice, the first of the 2026-10-19 run, unsigned,
with the device of the test's throwaway key A (public key
`b93a34db38a13f7261a5ddcdec500ebc681f244a8cf11edf37b3e022d1b0c4b9`, its secret
derived from a label in `hw/test_sweep_record.py`, so nobody's), on one line as
it is written (`export RUN --out FILE --device-key` that key, MEASURED):

```
{"cases":1048576,"cid":"c2aaacbea9016dc8da1472d1a71f15e161d49bdecdb2db6cadc4177a4fb3edc1","fm":0,"hi":1048576,"id":"1cfcf540935fc48234c7cb15ef0a3d9f07a23c36011ca3e012374ec9db701fd7","kind":"slice","lo":0,"run":{"device":"fcd1dfc0b3edff2d","end_ms":1792465491677,"id":"card-stress-1019","log":"logs/c0001-00013-sweep-conv32to64-all.log.gz","rate":1204647,"start_ms":1792465490807},"skipped":0,"subject":{"image":"quad","tile":1,"tiles":4,"xclbin":"4f9921a25af65444abc5c267fff1117a8e14abbc16a75de643e43c9dbf6ef53b"},"tool":{"commit":"881bbcb676bbede9da20858325b7a966c56a25bf","dirty":false},"v":1,"vm":0}
```

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
| `space` | exhaustive only: the indices are `[0, space)`, 2^32 | `EXH` |
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
enumeration are not in it. A later version adds them; that changes the hash, so
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
other, even for the same 32 bytes. The test shows both refusals on the
committed certificate `certificates/signed-fp64/signed-fp64.cert`: the
certificate's own signature, taken for a record's signature over its body hash
as an id, is refused `signature-domain`; and a record-domain signature over that
hash, written into a signature file for the certificate, is refused
`signature` by the certificate reader.

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
| `version` | 2 | a record of a version this verifier does not know (checked as soon as the line parses, before its canonical bytes and its fields) |
| `form` | 2 | not a version-1 record of its kind: a field missing or not in version 1, a float, a null, a path that is not relative |
| `id` | 2 | a record whose bytes do not hash to its id |
| `signature` | 2 | no signature where one is required, or one that does not verify |
| `signature-domain` | 2 | a signature that verifies under the certificate's domain `cft-signature 1` and not the record's |
| `signer` | 2 | a key of small order or no point; a keyring that breaks its form (the certificate reader's own name for these) |
| `key` | 2 | a key the keyring handed does not name |
| `device` | 2 | `run.device` is not the pseudonym of the key; at `sign`, a record that names another key's device |
| `splice` | 2 | a record of another run, or another device, in a file that is one run's |
| `campaign` | 2 | a record naming a campaign that is not in the file (which is what a campaign record altered, its id fixed, becomes), or one of the other sweep kind |
| `counts` | 2 | counts that break the driver's rule for the campaign (`parse_soak`'s cover rule, `expected_cases`, 0 cases, an interval past the space) |
| `run` | 2 | an end before the start, or a rate that is not the record's cases over its own time |
| `signed` | 2 | `sign` was given a record that carries a signature |
| `metrics` | 2 | at `export`: a run it cannot read as the driver wrote it (a dry run, a leg that disagrees with the catalog, counts the driver would not have passed) |
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
- whether it found a mismatch.

**Does not prove**, which is section 6.6's "What a record can never prove"
applied here:

- **that the slice was run**, or on the card, or by a specific device: a pass
  proves nothing by itself, and nothing on the U50 attests. Version 1 carries no
  digest to confirm against a second device and has no replay: a false pass is a
  false hole in the coverage, which only a replay or a second owner closes
  (rank 10). The honest statement of a coverage is "covered by K owners each
  replayed", and version 1 has one owner, unreplayed.
- **that the image named was on the card**: the driver hashed the file it passed
  to XRT and held it to its `SHA256SUMS`; nothing in the record shows what the
  card ran, and the tree the image's RTL came from is not in the record.
- **what the oracle was**: the CPU and libm are not recorded.
- **that the tool is the commit's build**: `tool.commit` is the driver's
  checkout, which the driver's build check held to the commit cft-segrun was
  stamped with; the soak binaries' own build ids and flags are not recorded.
- **when it was signed**: there is no time in a signature. `run.start_ms` and
  `end_ms` are the driver's clock. Records exported from `metrics.jsonl` after
  the run vouch for that file as it was when exported; one signed as the driver
  records narrows the window, and holds the key for the whole run.
- **that nothing is missing**: nothing in version 1 signs the set, so a record
  dropped from a file is not seen (the test runs this as a known limit).
- **who holds the key**: the keyring is the verifier's own statement.

## From the driver

Parcel DR2 wires this into the stress driver. What it calls:

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

`run_start` and `leg` raise `SR.Refusal` (name `metrics`) for a run or a leg that
cannot be records, and `leg` leaves the exporter as it was: the driver should log
an `event` and go on, since a record error must never stop a long run. After a
resume the exporter has seen no campaign, so it writes each campaign line again
(harmless: a repeated campaign line is the same record); fill `ex.seen` from the
file to avoid it. Cost per slice on the desktop (MEASURED, the 2026-10-19 run's
378 legs, a call each): `leg` 3.0 ms median signed (3.2 mean, 5.3 worst;
`Signer(...)` once, 1.5 ms) and 0.06 ms unsigned; a signed slice line is 853
bytes on average (837 to 860), 619 unsigned, a campaign line 299; about 2.8 MB
for a 60-hour run's 3,300 slices; `verify` 3.3 ms a slice.

## Version 1's known limits

- The stream form has not been run on a real run's legs (the 2026-10-19 run is
  all exhaustive); it is held to synthetic legs in the driver's format.
- The `build` record is required, and the item table is the exporting tree's:
  a run is exported from the tree it ran at, and `export` refuses a leg whose
  recorded expectations are not that catalog's.
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
- The tests need no card, no XRT and no compiler; `--metrics` takes the copy of a
  real run (the 2026-10-19 run's `metrics.jsonl` is not in the repository) and
  without it that group is skipped by name.

## The test

`python hw/test_sweep_record.py [--metrics RUN_OR_FILE]` makes its own
temporary directory and removes it by that path, and its keys are derived from
fixed labels or made by `cft_sign.py keygen` there: throwaways. Groups: forms
(canonical form and shapes), rules (the driver's rules, item by item), export
(a synthetic run in the driver's format, including records of types the
exporter does not know), keys, domain, plants (each defect put into a signed
file, and the refusal it must draw; and the verifier without a check, which
lets its plant through) and real. No runner stage runs it; one could
(the groups other than `real` need only Python and the repository, and take
seconds), and the stage counts are the lead's.
