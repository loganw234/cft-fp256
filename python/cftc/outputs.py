# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""cftc's output version, and the record that holds it.

`cftc.VERSION` is an OUTPUT version: it names the bytes cftc writes, and
it is bumped with any change to the bytes cftc writes for some source -
an output whose bytes move, or a source that compiles where it was
refused. Certificate version 2 names a compile by it ("compiler cftc
<version> <target>", docs/studies/CERT-V2.md, 8.3), and an auditor whose
compiler has the named version may call a recompile that differs a false
claim (8.7) - which is only sound if two compilers with one version
write the same bytes.

`programs/systems/cftc-outputs.txt` is its record: under each `version
N`, the SHA-256 of every committed compiled file - programs/systems/
compiled/ and compiled-tangent/ - as cftc version N wrote it. Append
only:
  * a new output version adds a block, every committed file in it;
  * a new committed reference adds its lines to the current block;
  * no line ever changes.
The `lang` stage holds it (programs/lang_check.py, leg F): the last block
is cftc.VERSION's and names every committed compiled file with its true
digest and nothing else. So a change to the compiler that moves a
committed byte fails the stage until VERSION is bumped and a block is
appended; `python programs/lang_check.py --record` appends what these
rules allow, and refuses the rest.

What it cannot see: bytes cftc writes for a source that is not committed.
The committed references are its sample, as the vectors are a library's;
the rule, not the record, says when the version steps.
"""

import hashlib
import re

RECORD_NAME = "cftc-outputs.txt"
COMMITTED = ("compiled", "compiled-tangent")

HEADER = """\
# cftc's output versions (python/cftc/outputs.py): under each version,
# the SHA-256 of every committed compiled file (programs/systems/compiled/
# and compiled-tangent/) as that version of cftc wrote it. Append only:
# a new output version adds a block, a new committed reference adds its
# lines to the current block, and no line ever changes. Held by the lang
# stage (programs/lang_check.py, leg F); appended by its --record.
"""

_VERSION = re.compile(r"version ([1-9][0-9]*)")
_LINE = re.compile(r"([0-9a-f]{64})  ([A-Za-z0-9._/-]+)")


class RecordError(ValueError):
    """The record is not in its form, or a change it would need breaks
    the append-only rule."""


def committed(systems_dir):
    """{path under programs/systems: sha256 hex} of every committed
    compiled file, in path order."""
    out = {}
    for d in COMMITTED:
        base = systems_dir / d
        if not base.is_dir():
            continue
        for p in sorted(base.iterdir()):
            if p.is_file():
                out[f"{d}/{p.name}"] = hashlib.sha256(
                    p.read_bytes()).hexdigest()
    return out


def parse(text):
    """-> [(version, {path: digest})], in order. RecordError on any line
    out of form, a block out of turn (versions run 1, 2, 3, ...), a
    path twice in a block, or a digest before any version."""
    blocks = []
    for k, ln in enumerate(text.split("\n"), 1):
        if not ln or ln.startswith("#"):
            continue
        m = _VERSION.fullmatch(ln)
        if m:
            v = int(m.group(1))
            if v != len(blocks) + 1:
                raise RecordError(f"line {k}: version {v} where version "
                                  f"{len(blocks) + 1} is due")
            blocks.append((v, {}))
            continue
        m = _LINE.fullmatch(ln)
        if not m:
            raise RecordError(f"line {k} is neither a version nor "
                              f"'<sha256>  <path>': {ln[:60]!r}")
        if not blocks:
            raise RecordError(f"line {k}: a digest before any version")
        digest, path = m.groups()
        if path in blocks[-1][1]:
            raise RecordError(f"line {k}: {path} twice in version "
                              f"{blocks[-1][0]}")
        blocks[-1][1][path] = digest
    if not blocks:
        raise RecordError("no version recorded")
    return blocks


def problems(text, files, version):
    """What keeps the record from holding: [str], empty when it holds.
    `files` is committed()'s map, `version` cftc.VERSION."""
    try:
        blocks = parse(text)
    except RecordError as e:
        return [f"the record is not in its form: {e}"]
    last, have = blocks[-1]
    out = []
    if last != version:
        out.append(f"cftc's VERSION is {version} and the record's last "
                   f"block is version {last}: an output version is "
                   f"recorded when it is made (lang_check.py --record)")
        return out
    changed = sorted(p for p in files if p in have and have[p] != files[p])
    missing = sorted(p for p in files if p not in have)
    extra = sorted(p for p in have if p not in files)
    if changed:
        out.append(f"{len(changed)} committed compiled file(s) are not what "
                   f"version {version} wrote - bump cftc's VERSION and "
                   f"append a block: {', '.join(changed[:4])}")
    if missing:
        out.append(f"{len(missing)} committed compiled file(s) are not in "
                   f"version {version}'s block: {', '.join(missing[:4])}")
    if extra:
        out.append(f"version {version}'s block names {len(extra)} file(s) "
                   f"that are not committed: {', '.join(extra[:4])}")
    return out


def block_text(version, files):
    return f"version {version}\n" + "".join(
        f"{d}  {p}\n" for p, d in sorted(files.items()))


def append(text, files, version):
    """The record with what the append-only rule allows, or RecordError.
    -> (new text, what was done)."""
    if not text:
        return HEADER + "\n" + block_text(version, files), \
            f"version {version}: {len(files)} files, a new record"
    blocks = parse(text)
    last, have = blocks[-1]
    if version < last:
        raise RecordError(f"cftc's VERSION {version} is below the record's "
                          f"last, {last}")
    sep = "" if text.endswith("\n\n") else "\n" if text.endswith("\n") \
        else "\n\n"
    if version > last + 1:
        raise RecordError(f"cftc's VERSION {version} skips past the "
                          f"record's last, {last}: versions run one by one")
    if version == last + 1:
        return text + sep + block_text(version, files), \
            f"version {version}: a new block of {len(files)} files"
    changed = sorted(p for p in have if p in files and have[p] != files[p])
    gone = sorted(p for p in have if p not in files)
    if changed or gone:
        raise RecordError(f"version {version}'s block would change "
                          f"({len(changed)} digests, {len(gone)} files "
                          f"gone): bump cftc's VERSION instead")
    new = {p: d for p, d in files.items() if p not in have}
    if not new:
        return text, f"version {version}: nothing to add"
    if not text.endswith("\n"):
        text += "\n"
    # a new committed reference: its lines go at the end of the current
    # block, which is the end of the file
    return text + "".join(f"{d}  {p}\n" for p, d in sorted(new.items())), \
        f"version {version}: {len(new)} new files added"
