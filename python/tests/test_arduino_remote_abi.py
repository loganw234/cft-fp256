# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""The Arduino remote examples claim the ABI of the libcft in this tree.

Every frame of the remote protocol carries its sender's cft_abi_version()
and both ends refuse any difference at all (docs/REMOTE.md, "Both ends'
ABI, on every frame"; host/src/backend_remote.c, cftr_recv_frame), so a
sketch must claim its server's ABI exactly. The remote client does not link
libcft, and a Nano cannot run it, so the claim is a literal in each sketch:
`#define CFT_REMOTE_ABI 0x...UL      /* libcft M.N */`. A literal goes stale at
the next ABI step. The three examples claimed 0.11 (0x0B) from 2026-09-09
until 2026-10-21, when libcft was at 0.18, and a server built from this tree
refused all three at HELLO, as the comment beside the literal said it would.

This holds each literal, and the version its comment names, to cft.h's
CFT_ABI_VERSION, so that a step of the ABI is a failure here until the
three examples are set again from the probe:

    python host/tools/cft-serial-bridge.py --probe-abi HOST:PORT

The probe's answer is the server's cft_abi_version(), which is the cft.h
macro for a server built from this tree (host/tools/cft-serve.c). The
sketches' prose carries no version number, so the literal and the comment
beside it are the only places that can go stale.
"""

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
CFT_H = REPO / "host" / "include" / "cft.h"
EXAMPLES = REPO / "bindings" / "arduino" / "cft-arduino" / "examples"
SKETCHES = ("RemoteReplay", "RemoteSerialFma", "RemoteWiFiFma")

CLAIM = re.compile(r"^#define CFT_REMOTE_ABI (0x[0-9A-Fa-f]{8})UL[ \t]+"
                   r"/\* libcft (\d+)\.(\d+) \*/[ \t]*$", re.M)


def tree_abi(text):
    """(major, minor) from the text of cft.h."""
    got = []
    for part in ("MAJOR", "MINOR"):
        m = re.search(r"^#define CFT_ABI_VERSION_%s +(\d+)" % part, text,
                      re.M)
        assert m, "cft.h defines no CFT_ABI_VERSION_%s" % part
        got.append(int(m.group(1)))
    return tuple(got)


def drift(sketch, major, minor):
    """What is wrong with the text of a sketch's claim, as a list of
    sentences; empty when it claims libcft major.minor, by the word and by
    the comment beside it."""
    claims = CLAIM.findall(sketch)
    if len(claims) != 1:
        return ["%d lines match '#define CFT_REMOTE_ABI 0x........UL  /* "
                "libcft M.N */', not one" % len(claims)]
    word, cmajor, cminor = claims[0]
    bad = []
    if int(word, 16) != (major << 16) | minor:
        bad.append("the word is %s, libcft %d.%d is 0x%08X"
                   % (word, major, minor, (major << 16) | minor))
    if (int(cmajor), int(cminor)) != (major, minor):
        bad.append("the comment names libcft %s.%s, the tree is %d.%d"
                   % (cmajor, cminor, major, minor))
    return bad


def test_the_remote_examples_claim_the_trees_abi():
    major, minor = tree_abi(CFT_H.read_text(encoding="utf-8"))
    found = sorted(p.name for p in EXAMPLES.glob("Remote*"))
    assert found == list(SKETCHES), found
    bad = {}
    for name in SKETCHES:
        text = (EXAMPLES / name / (name + ".ino")).read_text(encoding="utf-8")
        if drift(text, major, minor):
            bad[name] = drift(text, major, minor)
    assert not bad, (
        "libcft is at %d.%d and these sketches claim another ABI: %r - set "
        "CFT_REMOTE_ABI in each from `python host/tools/cft-serial-bridge.py "
        "--probe-abi HOST:PORT` against a cft-serve built from this tree"
        % (major, minor, bad))


def test_the_abi_check_fails_where_it_should():
    """Red on each drift it is there for: the claim as it stood until
    2026-10-21, a word and a comment that disagree, a claim missing, a
    claim twice, and a step of the ABI in cft.h."""
    major, minor = tree_abi(CFT_H.read_text(encoding="utf-8"))
    text = (EXAMPLES / "RemoteReplay" / "RemoteReplay.ino").read_text(
        encoding="utf-8")
    assert drift(text, major, minor) == []
    line = "#define CFT_REMOTE_ABI 0x%08XUL      /* libcft %d.%d */" % (
        (major << 16) | minor, major, minor)
    assert line in text

    old = text.replace(line, "#define CFT_REMOTE_ABI 0x0000000BUL      "
                             "/* libcft 0.11 */")
    assert drift(old, major, minor) == [
        "the word is 0x0000000B, libcft %d.%d is 0x%08X"
        % (major, minor, (major << 16) | minor),
        "the comment names libcft 0.11, the tree is %d.%d" % (major, minor)]

    word_only = text.replace(line, line.replace("0x%08XUL" % (
        (major << 16) | minor), "0x%08XUL" % (((major << 16) | minor) - 1)))
    assert len(drift(word_only, major, minor)) == 1
    comment_only = text.replace(line, line.replace(
        "libcft %d.%d" % (major, minor), "libcft %d.%d" % (major, minor - 1)))
    assert len(drift(comment_only, major, minor)) == 1

    assert len(drift(text.replace(line, ""), major, minor)) == 1
    assert len(drift(text + "\n" + line + "\n", major, minor)) == 1
    stepped = CFT_H.read_text(encoding="utf-8").replace(
        "#define CFT_ABI_VERSION_MINOR %d" % minor,
        "#define CFT_ABI_VERSION_MINOR %d" % (minor + 1), 1)
    assert tree_abi(stepped) == (major, minor + 1)
    assert drift(text, *tree_abi(stepped)) != []
    with pytest.raises(AssertionError):
        tree_abi("no macros here")
