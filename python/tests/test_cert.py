# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""Certificates, version 1 (docs/CERTIFICATES.md): the golden gate.

The mechanisms of python/cft_golden/cert.py have negative controls
here, all but those docs/CERTIFICATES.md's "The controls" names as
still without one, and each control asserts the NAME of the check it
exists for - never merely that something refused. Every control but the byte flip
writes a valid hash line over its defective body (cert.rehash, or
cert.encode for a structurally sound certificate with a semantic
defect), so it reaches the check it is for instead of stopping at the
hash (verifier-C1, N5).

The real audit is programs/lorenz63-rk4-fp64.cfta with its classic
bank: three lanes over four segments, its chain built by seq.run, with
a half-step run and a run one format wider beside it - green, and red
naming the segment when one boundary state is altered.

The specification's example certificate, its test vectors and its
refusal table are held to this implementation byte for byte and name
for name, so those three cannot drift from the code. The rest of the
page is prose, held by review.
"""

import dataclasses
import hashlib
import re
import struct
import sys
import types
from fractions import Fraction
from pathlib import Path

import pytest

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parents[1]))
ROOT = HERE.parents[2]
PROGRAMS = ROOT / "programs"
DOC = ROOT / "docs" / "CERTIFICATES.md"

from cft_golden import FORMATS, asm, chars, cert  # noqa: E402
from cft_golden import softfloat as sf  # noqa: E402

F64, F128 = FORMATS["fp64"], FORMATS["fp128"]

# The specification's example salt: public, printed on the page, and so
# never a salt anyone may use.
SALT = bytes(range(32))
OTHER_SALT = bytes(range(1, 33))

S = 4           # the main run's segments
LANES = 3


def refused(name, fn, *a, **k):
    """fn(*a, **k) must be refused, BY THIS NAME."""
    with pytest.raises(cert.Refusal) as ei:
        fn(*a, **k)
    got = ei.value
    assert got.name == name, (f"refused as {got.name!r} ({got.message}); "
                              f"the control exists for {name!r}")
    assert got.exit_code == cert.REFUSALS[name]
    return got


def lines_of(data):
    return cert.body_of(data).decode("ascii").split("\n")[:-1]


def rebuilt(lines):
    return cert.rehash("\n".join(lines) + "\n")


def find(lines, prefix, nth=0):
    hits = [i for i, ln in enumerate(lines) if ln.startswith(prefix)]
    return hits[nth]


def dec64(text):
    return chars.from_decimal(F64, text, sf.RND_RNE)[0]


def halved(fmt, bank, slots):
    """The bank with each named slot exactly halved - the half-step
    bank of docs/ROADMAP.md's plan (verifier-C1 measured it equal to the
    bank re-derived from h/2)."""
    vals = cert.state_values(fmt, bank)
    half = chars.from_decimal(FORMATS[fmt], "0.5", sf.RND_RNE)[0]
    for s in slots:
        vals[s], fl = sf.mul(FORMATS[fmt], vals[s], half)
        assert fl == 0, "halving is exact for these banks"
    return cert.state_bytes(fmt, vals)


def entry_with(method, kind, uses, lane, runs, shapes, states, form,
               fmt=None, rnd=None, label=None, terms=()):
    """An accuracy entry whose value the golden writer derives."""
    probe = cert.Entry(method, kind, uses, lane,
                       cert.Value("exact", exact=Fraction(0)), label, terms)
    q = cert.derive(probe, runs, shapes, states)
    return dataclasses.replace(probe, value=cert.make_value(q, form, fmt,
                                                            rnd)), q


SQUARES = ((Fraction(1), (0, 0)), (Fraction(1), (1, 1)),
           (Fraction(1), (2, 2)))
IDENTITY = cert.Identity(backend="software", device_xclbin="none",
                         device_version="none", device_caps="none",
                         device_tiles=1)


def keyed(runs, entries, identity=IDENTITY):
    """A keyed certificate under the example salt."""
    return cert.Certificate("keyed", cert.salt_commitment(SALT), identity,
                            tuple(runs), tuple(entries))


def opened(runs, entries, identity=IDENTITY):
    """An open certificate: no salt, no commitment."""
    return cert.Certificate("open", None, identity, tuple(runs),
                            tuple(entries))


@pytest.fixture(scope="module")
def lor():
    """Lorenz-63 at fp64 with its classic bank: the main run, a
    half-step run (the same image, H, H2 and H6 halved, twice the
    segments) and a run one format wider (the same instructions at
    fp128, bank and start exactly widened) - every chain built by
    seq.run. Four accuracy entries cover every method, form and
    scope."""
    src = (PROGRAMS / "lorenz63-rk4-fp64.cfta").read_text(encoding="utf-8")
    img = asm.assemble(src, "lorenz63-rk4-fp64")
    img128 = asm.assemble(src.replace(".format   fp64", ".format   fp128"),
                          "lorenz63-rk4-fp128")
    bank = (PROGRAMS / "lorenz63-rk4-fp64.classic.bank").read_bytes()
    bank_half = halved("fp64", bank, (0, 1, 2))
    bank_w = cert.state_bytes("fp128", [cert.widen("fp64", x) for x in
                                        cert.state_values("fp64", bank)])
    init = []
    for i in range(LANES):                  # programs/check.py's ensemble
        init += [dec64(repr(1 + i / 64)), dec64("1"), dec64("1")]
    init_w = [cert.widen("fp64", x) for x in init]
    st0, rs0 = cert.run_chain(img, bank, init, S)
    st1, rs1 = cert.run_chain(img, bank_half, init, 2 * S)
    st2, rs2 = cert.run_chain(img128, bank_w, init_w, S)
    params = (("ensemble-spread", 64), ("members", LANES))
    r0 = cert.certify_run("main", img, bank, SALT, st0, rs0, steps=100,
                          parameters=params)
    r1 = cert.certify_run("half-step", img, bank_half, SALT, st1, rs1,
                          steps=100, h_slots=(0, 1, 2))
    r2 = cert.certify_run("wider", img128, bank_w, SALT, st2, rs2,
                          steps=100)
    runs = (r0, r1, r2)
    shapes = [(F64, 3), (F64, 3), (F128, 3)]
    ends = {(0, 0): st0[0], (0, S): st0[-1], (1, 0): st1[0],
            (1, 2 * S): st1[-1], (2, 0): st2[0], (2, S): st2[-1]}
    e0, q0 = entry_with("step-halving", "estimate", 1, None, runs, shapes,
                        ends, "exact")
    e1, q1 = entry_with("wider", "estimate", 2, 0, runs, shapes, ends,
                        "rounded", "fp64", "rup")
    e2, q2 = entry_with("drift", "measurement", 0, None, runs, shapes, ends,
                        "enclosed", "fp32", label="square-norm",
                        terms=SQUARES)
    e3, q3 = entry_with("drift", "measurement", 0, 2, runs, shapes, ends,
                        "exact", label="square-norm", terms=SQUARES)
    c = keyed(runs, (e0, e1, e2, e3))
    data = cert.encode(c)
    # the same runs, certified OPEN: the same states and results, hashed
    # without a salt (no re-run: certify_run only hashes)
    open_runs = (
        cert.certify_run("main", img, bank, None, st0, rs0, steps=100,
                         parameters=params),
        cert.certify_run("half-step", img, bank_half, None, st1, rs1,
                         steps=100, h_slots=(0, 1, 2)),
        cert.certify_run("wider", img128, bank_w, None, st2, rs2,
                         steps=100))
    open_data = cert.encode(opened(open_runs, (e0, e1, e2, e3)))
    return types.SimpleNamespace(
        open_runs=open_runs, open_data=open_data,
        img=img, img128=img128, bank=bank, bank_half=bank_half,
        bank_w=bank_w, init=init, init_w=init_w, st=(st0, st1, st2),
        rs=(rs0, rs1, rs2), runs=runs, entries=(e0, e1, e2, e3),
        values=(q0, q1, q2, q3), cert=c, data=data, shapes=shapes,
        progs={0: (img, bank), 1: (img, bank_half), 2: (img128, bank_w)},
        states={r: dict(enumerate(st)) for r, st in enumerate((st0, st1,
                                                                st2))},
        ends=ends)


def with_runs(lor, runs, accuracy=()):
    return cert.encode(dataclasses.replace(lor.cert, runs=tuple(runs),
                                           accuracy=tuple(accuracy)))


# ---- the round trip -------------------------------------------------------

def test_round_trip(lor):
    back = cert.parse(lor.data)
    assert back == cert._normalized(lor.cert)
    assert cert.encode(back) == lor.data
    assert cert.parse(lor.data, salt=SALT) == back


def test_the_fixture_exercises_every_line_and_form(lor):
    """The byte-flip and structure controls below run over this
    certificate, so it must hold every key of the grammar and every
    variant a line can take - otherwise 'every field' would be a claim
    about the fields it happens to have."""
    keys = {ln.split(" ")[0] for ln in lines_of(lor.data)}
    assert keys == set(cert.RANK) - {"hash"}
    assert {r.kind for r in lor.runs} == {"main", "half-step", "wider"}
    assert {e.method for e in lor.entries} == set(cert.METHOD_KIND)
    assert {e.value.form for e in lor.entries} == {"exact", "rounded",
                                                   "enclosed"}
    assert {e.lane is None for e in lor.entries} == {True, False}
    L = lines_of(lor.data)
    assert L[find(L, "build-id")] == "build-id unknown"


# ---- integrity: a byte flipped anywhere -------------------------------------

def test_a_byte_flipped_anywhere_is_refused(lor):
    """Every byte of the file, flipped (x ^ 0x01), is refused - in the
    body by the body's hash, which covers fields no other check reads
    (the build, the device, the parameters, an unsampled segment's
    flags); in the hash line by the hash line's form or its value. No
    re-hash: this is the one control the hash line is for."""
    data = lor.data
    body_len = len(cert.body_of(data))
    names = []
    for i in range(len(data)):
        flipped = data[:i] + bytes([data[i] ^ 0x01]) + data[i + 1:]
        if i < body_len - 1:
            names.append(refused("body-hash", cert.parse, flipped).name)
        elif i == body_len - 1:
            # the LF that ends 'end': the hash line runs into the body,
            # so the last line is no longer a hash line
            names.append(refused("hash-line", cert.parse, flipped).name)
        else:
            last = flipped[body_len:]
            still = re.fullmatch(rb"hash [0-9a-f]{64}\n", last)
            names.append(refused("body-hash" if still else "hash-line",
                                 cert.parse, flipped).name)
    assert len(names) == len(data) == body_len + 70
    assert names.count("body-hash") >= body_len - 1


def test_the_hash_line(lor):
    body = cert.body_of(lor.data)
    refused("hash-line", cert.parse, body)                      # none
    refused("hash-line", cert.parse, lor.data[:-1])             # no LF
    refused("hash-line", cert.parse, lor.data + b"\n")          # a blank
    refused("hash-line", cert.parse, body + b"hash "
            + cert.sha256(body).upper().encode() + b"\n")
    refused("hash-line", cert.parse, body + b"hash  "
            + cert.sha256(body).encode() + b"\n")
    refused("body-hash", cert.parse, body + b"hash "
            + cert.sha256(body + b"x").encode() + b"\n")
    # a second hash line: the first is then a body line after 'end'
    refused("line-unexpected", cert.parse, cert.rehash(lor.data))


# ---- the strict form --------------------------------------------------------

MEMBERS = ("parameter", "segment", "term", "run", "entry")
CONSECUTIVE = ("parameter", "segment", "term")
COUNT_LINES = ("parameters", "segments", "quantity")


def test_a_line_dropped(lor):
    """Each body line dropped, re-hashed. The magic line's absence is
    'magic'; a keyed certificate's salt commitment, 'commitment-missing';
    a member of a counted group is a count that disagrees (counts are
    taken before members are read); any other line is 'line-missing'."""
    L = lines_of(lor.data)
    for i, ln in enumerate(L):
        k = ln.split(" ")[0]
        want = ("magic" if i == 0 else
                "commitment-missing" if k == "salt-commitment" else
                "count" if k in MEMBERS else "line-missing")
        e = refused(want, cert.parse, rebuilt(L[:i] + L[i + 1:]))
        if want == "line-missing":
            assert f"'{k}' is missing" in e.message


def test_a_line_added(lor):
    """An unknown line anywhere is 'unknown-line' (before the magic
    line, the first line is not the magic). A line repeated in place
    has no place there, 'line-unexpected' - except a counted member, or
    the count line of a group whose members must follow it directly and
    now do not, which is a count that disagrees."""
    L = lines_of(lor.data)
    for i in range(len(L) + 1):
        refused("magic" if i == 0 else "unknown-line", cert.parse,
                rebuilt(L[:i] + ["note this line is not in version 1"]
                        + L[i:]))
    for i, ln in enumerate(L):
        k = ln.split(" ")[0]
        want = ("count" if k in MEMBERS or (k in COUNT_LINES
                                            and not ln.endswith(" 0"))
                else "line-unexpected")
        refused(want, cert.parse, rebuilt(L[:i + 1] + [ln] + L[i + 1:]))


def _block_of(L):
    out, b = [], 0
    for ln in L:
        if ln.split(" ")[0] in ("run", "accuracy", "entry", "end"):
            b += 1
        out.append(b)
    return out


def test_a_line_moved(lor):
    """Every adjacent pair inside one block, exchanged: 'line-order' -
    or, when the first is the last member of a group that must be
    consecutive and the second is not, a count that disagrees. Two
    `term` lines are not exchanged: a quantity's terms are the
    producer's statement in the order it chose, and exchanging two is a
    different, valid certificate. Whole blocks moved are 'line-order'
    by their indices."""
    L = lines_of(lor.data)
    blocks = _block_of(L)
    starters = ("cft-certificate", "run", "accuracy", "entry", "end")
    tried = 0
    for i in range(len(L) - 1):
        a, b = L[i].split(" ")[0], L[i + 1].split(" ")[0]
        if a in starters or b in starters or blocks[i] != blocks[i + 1]:
            continue
        if a == b == "term":
            continue
        want = "count" if (a in CONSECUTIVE and b != a) else "line-order"
        M = list(L)
        M[i], M[i + 1] = M[i + 1], M[i]
        refused(want, cert.parse, rebuilt(M))
        tried += 1
    assert tried > 60
    # whole run blocks 1 and 2, and entry blocks 0 and 1, exchanged
    r1, r2, acc = find(L, "run 1 "), find(L, "run 2 "), find(L, "accuracy ")
    refused("line-order", cert.parse,
            rebuilt(L[:r1] + L[r2:acc] + L[r1:r2] + L[acc:]))
    e0, e1, e2 = (find(L, f"entry {j} ") for j in range(3))
    refused("line-order", cert.parse,
            rebuilt(L[:e0] + L[e1:e2] + L[e0:e1] + L[e2:]))
    # a line moved far within its block
    sc = find(L, "salt-commitment")
    t = find(L, "device-tiles")
    refused("line-order", cert.parse,
            rebuilt(L[:sc] + L[sc + 1:t + 1] + [L[sc]] + L[t + 1:]))


def test_a_line_not_the_one_expected_by_the_pages_rules(lor):
    """"A line that is not the one expected", rule by rule, each with a
    line the other rules would name differently (the census found the
    first two and the third's name with no control): a line of a block
    already behind, in a later block; a run line, whose block is behind,
    where an entry's line belongs; and a line of a later block where a
    block-starting line is expected. (A line dropped, repeated or
    exchanged, above, reaches the other rules.)"""
    L = lines_of(lor.data)
    kind = find(L, "kind ")                 # entry 0's second line
    acc = find(L, "accuracy ")
    for at, line, name, why in (
            # a header line, its block behind, where `kind` belongs
            (kind, "backend software", "line-unexpected",
             "its place is earlier"),
            # a block-starting line whose block is behind
            (kind, "run 3 wider", "line-unexpected",
             "its block is already read"),
            # an entry's line where the block-starting `accuracy` belongs:
            # it belongs to a LATER block, so `accuracy` is missing
            (acc, "kind estimate", "line-missing", "is here instead")):
        e = refused(name, cert.parse, rebuilt(L[:at] + [line] + L[at + 1:]))
        assert e.line == at + 1 and why in e.message, (line, e.message)


def test_a_groups_indices_by_the_pages_three_rules(lor):
    """Indices with the count right: an index already passed is
    `line-unexpected`, the right index further on is `line-order`, and
    otherwise the index is `line-missing` - for segments, runs and
    entries, each at the line where it goes wrong (the census found the
    first and third with no control)."""
    L = lines_of(lor.data)

    def reindex(prefix, old_to_new, nth_block=0):
        """L with the group's member lines renumbered: {position: index}."""
        M = list(L)
        at = [i for i, ln in enumerate(L) if ln.startswith(prefix)]
        for pos, new in old_to_new.items():
            toks = M[at[pos]].split(" ")
            toks[1] = str(new)
            M[at[pos]] = " ".join(toks)
        return M, at
    for prefix in ("segment ", "run ", "entry "):
        for mapping, name, where in (({2: 1}, "line-unexpected", 2),
                                     ({1: 2, 2: 1}, "line-order", 1),
                                     ({2: 3}, "line-missing", 2)):
            M, at = reindex(prefix, mapping)
            e = refused(name, cert.parse, rebuilt(M))
            assert e.line == at[where] + 1, (prefix, mapping, e.message)


def test_a_count_changed(lor):
    """Every count, one more and one less, re-hashed: 'count'."""
    L = lines_of(lor.data)
    tried = 0
    for i, ln in enumerate(L):
        toks = ln.split(" ")
        if toks[0] in ("runs", "parameters", "segments", "accuracy"):
            pos = 1
        elif toks[0] == "quantity":
            pos = 3
        elif toks[0] == "run" and toks[2] == "half-step":
            pos = 4
        else:
            continue
        n = int(toks[pos])
        for m in (n + 1, n - 1):
            if m < (1 if toks[0] in ("runs", "segments", "quantity", "run")
                    else 0):
                continue
            t2 = list(toks)
            t2[pos] = str(m)
            refused("count", cert.parse,
                    rebuilt(L[:i] + [" ".join(t2)] + L[i + 1:]))
            tried += 1
    assert tried >= 20


def test_magic_and_version(lor):
    L = lines_of(lor.data)
    refused("version", cert.parse, rebuilt(["cft-certificate 2"] + L[1:]))
    refused("magic", cert.parse, rebuilt(["cft-certificat 1"] + L[1:]))
    refused("malformed", cert.parse, rebuilt(["cft-certificate 1 x"]
                                             + L[1:]))
    refused("magic", cert.parse, cert.rehash(b""))


# The malformed numbers: (line prefix, a replacement line). Each is one
# encoding rule broken - a spelling other than the one the page gives.
def _malformed_cases(L):
    seg = L[find(L, "segment 0 ")].split(" ")
    rnd = L[find(L, "value rounded")].split(" ")
    enc = L[find(L, "value enclosed")].split(" ")
    num, den = (int(x, 16) for x in
                L[find(L, "value exact")].split(" ")[2].split("/"))
    run1 = find(L, "run 1 ")
    cases = [
        ("lanes ", "lanes 03"), ("lanes ", "lanes +3"), ("lanes ", "lanes -3"),
        ("lanes ", "lanes 3.0"), ("lanes ", "lanes 0"),
        ("lanes ", "lanes 9223372036854775808"),
        # past Python's 4,300-digit int() limit: refused, not a crash
        ("lanes ", "lanes " + "9" * 5000),
        ("segment 0 ", " ".join(["segment", "1" * 5000] + seg[2:])),
        ("steps ", "steps 0"), ("segments ", "segments 0"),
        ("runs ", "runs 0"),
        ("segment 0 ", " ".join(seg[:7] + ["32"] + seg[8:])),
        ("segment 0 ", " ".join(seg[:9] + ["4294967296"])),
        ("segment 0 ", " ".join(seg[:2] + ["begin"] + seg[3:])),
        ("program-image ", "program-image " + "A" * 64),
        ("program-image ", "program-image " + "a" * 63),
        ("program-format ", "program-format fp80"),
        # cft_build_id()'s string and nothing near it
        ("build-id ", "build-id commit=" + "a" * 39
         + " tracked=clean untracked=none"),
        ("build-id ", "build-id commit=" + "a" * 41
         + " tracked=clean untracked=none"),
        ("build-id ", "build-id commit=" + "A" * 40
         + " tracked=clean untracked=none"),
        ("build-id ", "build-id commit=" + "a" * 40
         + " tracked=dirty untracked=none"),
        ("build-id ", "build-id commit=" + "a" * 40
         + " untracked=none tracked=clean"),
        ("build-id ", "build-id commit=" + "a" * 40 + " tracked=clean"),
        ("build-id ", "build-id commit=" + "a" * 40
         + " tracked=clean untracked=some"),
        ("build-id ", "build-id " + "a" * 40
         + " tracked=clean untracked=none"),
        ("build-id ", "build-id unknown tracked=clean"),
        ("build-id ", "build-id Unknown"),
        ("backend ", "backend fpga"),
        # The hex spelling of lines the audit never reads (P1c, after
        # verifier-C2): only the reader stands between these and an
        # accepted certificate.
        ("device-xclbin ", "device-xclbin " + "a" * 63),
        ("device-xclbin ", "device-xclbin " + "a" * 65),
        ("device-xclbin ", "device-xclbin " + "A" * 64),
        ("device-xclbin ", "device-xclbin 0x" + "a" * 62),
        ("device-version ", "device-version 0000a00"),
        ("device-version ", "device-version 000000a00"),
        ("device-version ", "device-version 00000A00"),
        ("device-version ", "device-version 0x000a00"),
        # a decimal of another length is not hex digits (the tiles line's
        # decimal is not the others')
        ("device-version ", "device-version 1234567"),
        ("device-xclbin ", "device-xclbin 1234"),
        # and of the hashes the audit compares, which the reader holds to
        # their spelling first, so a misspelt one is `malformed` rather
        # than a mismatch found later under another name
        ("stream-a ", "stream-a " + seg[3].upper()),
        ("stream-b ", "stream-b " + seg[3][1:]),
        ("stream-c ", "stream-c " + seg[3] + "0"),
        ("output ", "output " + seg[3].upper()),
        ("output ", "output " + seg[3][1:]),
        ("segment 0 ", " ".join(seg[:3] + [seg[3].upper()] + seg[4:])),
        ("segment 0 ", " ".join(seg[:5] + [seg[5][1:]] + seg[6:])),
        ("salt-commitment ", "salt-commitment " + "F" * 64),
        ("salt-commitment ", "salt-commitment " + "f" * 63),
        ("device-caps ", "device-caps 0000000f 00000000 00000000"),
        ("device-caps ", "device-caps 0000000F 00000000"),
        ("device-caps ", "device-caps 0000000f none"),
        ("device-tiles ", "device-tiles 0"),
        ("term 1/1 s0 s0", "term 2/2 s0 s0"),
        ("term 1/1 s0 s0", "term 0/3 s0 s0"),
        ("term 1/1 s0 s0", "term -0/1 s0 s0"),
        ("term 1/1 s0 s0", "term 1/0 s0 s0"),
        ("term 1/1 s0 s0", "term 01/1 s0 s0"),
        ("term 1/1 s0 s0", "term 1/-1 s0 s0"),
        ("term 1/1 s0 s0", "term +1/1 s0 s0"),
        ("term 1/1 s0 s0", "term 1/A s0 s0"),
        ("term 1/1 s0 s0", "term 1 s0 s0"),
        ("term 1/1 s0 s0", "term 1/1 s0 x0"),
        ("term 1/1 s0 s0", "term 1/1 s0 s00"),
        ("term 1/1 s1 s1", "term 1/1 s1 s0"),
        ("term 1/1 s0 s0", "term 1/1 " + " ".join(["s0"] * 9)),
        ("term 1/1 s0 s0", "term"),
        ("value exact", f"value exact {2 * num:x}/{2 * den:x}"),
        ("value rounded", " ".join(rnd[:4] + [rnd[4].upper()] + rnd[5:])),
        ("value rounded", " ".join(rnd[:4] + [rnd[4][1:]] + rnd[5:])),
        ("value rounded", " ".join(rnd[:3] + ["rnd"] + rnd[4:])),
        ("value rounded", " ".join(rnd[:4] + ["7ff8000000000000", "nan"])),
        ("value enclosed", " ".join(enc[:3] + enc[5:7] + enc[3:5])),
        ("value exact", "value exact"),
        ("value rounded", " ".join(rnd[:5])),
        ("value enclosed", " ".join(enc[:6])),
        ("value exact", "value approximate 1/3"),
        # each form with one token more, and a form's payload under
        # another form's word
        ("value exact", L[find(L, "value exact")] + " 0"),
        ("value rounded", " ".join(rnd + ["0"])),
        ("value enclosed", " ".join(enc + ["0"])),
        ("value enclosed", " ".join(["value", "exact"] + enc[2:])),
        ("value rounded", " ".join(["value", "exact"] + rnd[2:])),
        ("value exact", " ".join(["value", "rounded"]
                                 + L[find(L, "value exact")].split(" ")[2:])),
        ("scope lane", "scope lane 00"), ("scope lane", "scope lanes 0"),
        ("scope lane", "scope lane 0 0"), ("scope lane", "scope lane"),
        ("quantity ", "quantity Square terms 3"),
        ("quantity ", "quantity square-norm terms"),
        ("quantity ", "quantity square-norm factors 3"),
        ("entry 0 ", "entry 0 extrapolation"),
        ("kind ", "kind guess"),
        ("parameter ", "parameter Spread 64"),
        ("run 0 ", "run 0 wider"),
        ("run 0 ", "run 0"),
        ("run 0 ", "run 0 main main"),
        ("run 0 ", "run 0 half-step h-slots 3 0 1 2"),
        ("run 1 ", "run 1 quarter-step"),
        ("run 1 ", "run 1 main"),
        ("run 1 ", "run 1 half-step h-slots 3 0 2 1"),
        ("run 1 ", "run 1 half-step h-slots 0"),
        ("run 1 ", "run 1 half-step h-slots"),
        ("run 1 ", "run 1 half-step"),
        ("run 1 ", "run 1 half-step slots 3 0 1 2"),
        ("run 2 ", "run 2 wider h-slots 1 0"),
        ("end", "end now"),
    ]
    out = []
    for prefix, new in cases:
        i = run1 if prefix == "run 1 " else find(L, prefix)
        out.append((i, new, L[:i] + [new] + L[i + 1:]))
    return out


def test_a_malformed_number_or_word(lor):
    """Every encoding's one spelling: each departure refused
    'malformed', re-hashed, at the line it is on - the rationals'
    canonical form (reduced, a positive denominator, no leading zeros,
    zero as 0/1, the sign on the numerator), decimal integers, hex
    digests and words among them."""
    L = lines_of(lor.data)
    for i, new, M in _malformed_cases(L):
        try:
            e = refused("malformed", cert.parse, rebuilt(M))
        except (Exception, pytest.fail.Exception) as x:
            # name the case, so a red run says which spelling got through
            raise AssertionError(f"{new[:70]!r}: {str(x)[:200]}") from None
        assert e.line == i + 1, (new[:60], e.message)
    # and each for its own reason where two checks could both refuse it:
    # a decimal's spelling, then its size, then its range
    lanes = find(L, "lanes ")
    for tok, why in (("03", "one spelling"), ("+3", "one spelling"),
                     ("3.0", "one spelling"),
                     ("9223372036854775808", "past 2^63 - 1"),
                     ("0", "it must be in 1..")):
        e = refused("malformed", cert.parse, rebuilt(
            L[:lanes] + [f"lanes {tok}"] + L[lanes + 1:]))
        assert why in e.message, (tok, e.message)
    # a rational's: its spelling, then zero's one spelling, then lowest
    # terms (0/3 is both a zero misspelt and not in lowest terms)
    t = find(L, "term 1/1 s0 s0")
    for tok, why in (("01/1", "one spelling"), ("1/0", "zero denominator"),
                     ("0/3", "zero is spelled 0/1"),
                     ("2/2", "not in lowest terms")):
        e = refused("malformed", cert.parse, rebuilt(
            L[:t] + [f"term {tok} s0 s0"] + L[t + 1:]))
        assert why in e.message, (tok, e.message)
    # an identity word's refusal names what the line may hold, the word
    # among them (a decimal line's own spelling check would not)
    i = find(L, "device-tiles ")
    e = refused("malformed", cert.parse, rebuilt(
        L[:i] + ["device-tiles x"] + L[i + 1:]))
    assert "or 'unknown'" in e.message, e.message
    # and bytes a line may not hold
    i = find(L, "lanes ")
    # each for its own reason: a line's spaces are checked as spaces, not
    # left to a token count that a trailing space would also upset
    for bad, why in (("lanes  3", "exactly one space"),
                     ("lanes 3 ", "exactly one space"),
                     (" lanes 3", "exactly one space"),
                     ("lanes\t3", "printable ASCII"),
                     ("lanes 3\r", "printable ASCII")):
        e = refused("malformed", cert.parse,
                    rebuilt(L[:i] + [bad] + L[i + 1:]))
        assert e.line == i + 1 and why in e.message, (bad, e.message)
    e = refused("malformed", cert.parse, rebuilt(L[:i] + [""] + L[i:]))
    assert e.line == i + 1


def test_rational_spelling_round_trips():
    for q in (Fraction(0), Fraction(1), Fraction(-1, 3), Fraction(255, 256),
              Fraction(-(1 << 1022) - 1, 3), Fraction(7, (1 << 1022) + 1)):
        t = cert.rational_text(q)
        assert re.fullmatch(r"(0|-?[1-9a-f][0-9a-f]*)/[1-9a-f][0-9a-f]*", t)
        r = cert._Reader([["x"]])
        assert r.rational(t, "q") == q


def test_the_width_rule_one_name_everywhere(lor):
    """1,023 bits a numerator or a denominator: past it, refused
    'width' by the reader, by the writer and by the audit's
    re-derivation, with one exit code."""
    L = lines_of(lor.data)
    i = find(L, "term 1/1 s0 s0")
    ok = (1 << 1023) - 1
    for num, den, name in ((ok, 1, None), (1, ok, None),
                           (1 << 1023, 1, "width"), (1, 1 << 1023, "width"),
                           (-(1 << 1023), 3, "width")):
        line = f"term {cert.rational_text(Fraction(num, den))} s0 s0"
        data = rebuilt(L[:i] + [line] + L[i + 1:])
        if name is None:
            cert.parse(data)
        else:
            refused(name, cert.parse, data)
    # the writer
    e = lor.entries[0]
    big = dataclasses.replace(e, value=cert.Value(
        "exact", exact=Fraction(1 << 1023)))
    refused("width", cert.encode, dataclasses.replace(
        lor.cert, accuracy=(big,)))
    # the writer refuses a value past the rule whatever form it would
    # write: rounding it would approximate what no audit can re-derive
    for form, fmt, rnd in (("exact", None, None), ("rounded", "fp64", "rup"),
                           ("enclosed", "fp64", None)):
        refused("width", cert.make_value, Fraction(1, 1 << 1023), form, fmt,
                rnd)
    # the audit: every value written is in the rule, and an intermediate
    # of the stated function is not - a 1,001-bit coefficient times a
    # 53-bit state value
    coef = Fraction((1 << 1000) + 1)
    drift = cert.Entry("drift", "measurement", 0, 0,
                       cert.Value("exact", exact=Fraction(0)), "wide",
                       ((coef, (0,)),))
    refused("width", cert.derive, drift, lor.runs, lor.shapes, lor.ends)
    data = cert.encode(dataclasses.replace(lor.cert, accuracy=(drift,)))
    e = refused("width", cert.audit, data, SALT, lor.progs,
                states=lor.states, choose={0: [0], 1: [0], 2: [0]})
    assert e.message.startswith("entry 0: ")
    assert cert.REFUSALS["width"] == 3


def test_an_exact_decimal_must_be_its_hex(lor):
    """The reader holds each element's decimal to its hex (O6): a digit
    changed, or an equal value in another spelling, is 'decimal'."""
    L = lines_of(lor.data)
    i = find(L, "value rounded")
    toks = L[i].split(" ")
    wrong = toks[5][:-1] + ("4" if toks[5][-1] != "4" else "3")
    refused("decimal", cert.parse,
            rebuilt(L[:i] + [" ".join(toks[:5] + [wrong])] + L[i + 1:]))
    j = find(L, "value enclosed")
    toks = L[j].split(" ")
    m, e = toks[4].split("e")
    refused("decimal", cert.parse,
            rebuilt(L[:j] + [" ".join(toks[:4] + [m + "0e" + e] + toks[5:])]
                    + L[j + 1:]))
    # 1 is '1e+0', and nothing else
    one = "value rounded fp64 rne 3ff0000000000000 "
    for spelling, ok in (("1e+0", True), ("1.0e+0", False), ("1", False),
                         ("10e-1", False), ("1e0", False)):
        data = rebuilt(L[:i] + [one + spelling] + L[i + 1:])
        if ok:
            cert.parse(data)
        else:
            refused("decimal", cert.parse, data)


def test_an_accuracy_kind_must_be_its_methods(lor):
    L = lines_of(lor.data)
    for j, bad in ((0, "bound"), (0, "measurement"), (2, "estimate"),
                   (2, "bound")):
        i = find(L, "kind ", j)
        e = refused("accuracy-kind", cert.parse,
                    rebuilt(L[:i] + [f"kind {bad}"] + L[i + 1:]))
        if bad == "bound":
            assert "rigorous remainder" in e.message


# ---- the salt ---------------------------------------------------------------

def test_the_salt_commitment(lor):
    refused("salt-commitment", cert.parse, lor.data, salt=OTHER_SALT)
    refused("salt-commitment", cert.audit, lor.data, OTHER_SALT, lor.progs,
            states=lor.states)
    # the certificate's own commitment edited to another valid value
    L = lines_of(lor.data)
    i = find(L, "salt-commitment")
    data = rebuilt(L[:i] + ["salt-commitment "
                            + cert.salt_commitment(OTHER_SALT)] + L[i + 1:])
    cert.parse(data)                        # well formed ...
    refused("salt-commitment", cert.parse, data, salt=SALT)  # ... not ours
    refused("salt-commitment", cert.audit, data, SALT, lor.progs,
            states=lor.states)
    # 32 of something that is not bytes is not a salt, even the salt's
    # own 32 values in a list
    for bad in (SALT[:31], SALT + b"\x00", bytes(64), "salt", "s" * 32,
                list(SALT)):
        refused("salt-length", cert.audit, lor.data, bad, lor.progs)
        refused("salt-length", cert.state_hash, bad, b"")


def test_keyed_or_open(lor):
    """Each certificate is keyed or open, its owner's choice (Logan,
    2026-09-28), and says which on its second line. Every control
    re-hashed, each asserting its check's name."""
    # open: no salt, no commitment, plain SHA-256 - and anyone holding
    # the states audits it
    L = lines_of(lor.open_data)
    assert L[1] == "mode open" and not any(
        ln.startswith("salt-commitment") for ln in L)
    assert cert.encode(cert.parse(lor.open_data)) == lor.open_data
    v = cert.audit(lor.open_data, None, lor.progs, states=lor.states)
    assert v.accuracy == list(lor.values)
    assert "anyone holding the states can audit" in "\n".join(v.lines())
    s0 = cert.state_bytes("fp64", lor.init)
    assert lor.open_runs[0].chain[0].start == hashlib.sha256(
        b"cft-certificate 1 state\x00" + s0).hexdigest()
    # a commitment is to a salt: an open certificate's writer has none to
    # commit to, and asking for one is refused rather than hashed open
    refused("salt-missing", cert.salt_commitment, None)
    # the salt's presence, against the mode
    refused("salt-unexpected", cert.audit, lor.open_data, SALT, lor.progs,
            states=lor.states)
    refused("salt-unexpected", cert.parse, lor.open_data, salt=SALT)
    refused("salt-missing", cert.audit, lor.data, None, lor.progs,
            states=lor.states)
    # a mode this reader does not know
    K = lines_of(lor.data)
    for bad in ("mode signed", "mode KEYED", "mode opened"):
        refused("mode-unknown", cert.parse, rebuilt([K[0], bad] + K[2:]))
    # the commitment line against the mode, wherever it stands
    sc = find(K, "salt-commitment")
    refused("commitment-missing", cert.parse, rebuilt(K[:sc] + K[sc + 1:]))
    moved = K[:sc] + K[sc + 1:]
    t = find(moved, "device-tiles")
    refused("commitment-missing", cert.parse, rebuilt(
        [moved[0], "mode keyed"] + moved[2:t + 1] + moved[t + 1:]))
    refused("commitment-unexpected", cert.parse,
            rebuilt(L[:2] + [K[sc]] + L[2:]))
    t = find(L, "device-tiles")
    refused("commitment-unexpected", cert.parse,
            rebuilt(L[:t + 1] + [K[sc]] + L[t + 1:]))
    # a keyed certificate relabelled open reads as well formed, and its
    # keyed hashes are then not the open hashes of the same states
    relabelled = rebuilt([K[0], "mode open"] + K[sc + 1:])
    cert.parse(relabelled)
    refused("stream", cert.audit, relabelled, None, lor.progs,
            states=lor.states)


def rfc2104(key, msg):
    """HMAC-SHA-256 written out from RFC 2104, with hashlib alone - an
    implementation that shares nothing with cert.py's hmac module."""
    if len(key) > 64:
        key = hashlib.sha256(key).digest()
    key = key.ljust(64, b"\x00")
    inner = hashlib.sha256(bytes(x ^ 0x36 for x in key) + msg).digest()
    return hashlib.sha256(bytes(x ^ 0x5C for x in key) + inner).hexdigest()


def test_the_keyed_hashes_are_rfc2104_hmac():
    state = cert.state_bytes("fp64", [dec64("1"), dec64("-0.5")])
    assert cert.salt_commitment(SALT) == rfc2104(
        SALT, b"cft-certificate 1 salt")
    assert cert.state_hash(SALT, state) == rfc2104(
        SALT, b"cft-certificate 1 state\x00" + state)
    for n in "abc":
        assert cert.stream_hash(SALT, n, state) == rfc2104(
            SALT, b"cft-certificate 1 stream " + n.encode() + b"\x00"
            + state)
    # open: plain SHA-256 of the same tag and bytes
    assert cert.state_hash(None, state) == hashlib.sha256(
        b"cft-certificate 1 state\x00" + state).hexdigest()
    assert cert.stream_hash(None, "c", state) == hashlib.sha256(
        b"cft-certificate 1 stream c\x00" + state).hexdigest()
    # the domains are kept apart: the same bytes, three different hashes
    assert len({cert.state_hash(SALT, state), cert.stream_hash(
        SALT, "a", state), cert.stream_hash(SALT, "b", state)}) == 3
    assert len({cert.state_hash(None, state), cert.stream_hash(
        None, "a", state), cert.state_hash(SALT, state)}) == 3
    # and a 65-byte key is what C1 measured: its SHA-256 IS the key
    long = bytes(65)
    assert rfc2104(long, b"m") == rfc2104(hashlib.sha256(long).digest(),
                                          b"m")


# ---- the inputs handed to the audit -----------------------------------------

def test_the_real_audit_is_green(lor):
    """The whole certificate, every segment of every run re-run from its
    certified start state by seq.run, every accuracy value re-derived."""
    v = cert.audit(lor.data, SALT, lor.progs, states=lor.states)
    assert v.exit_code == 0
    assert [len(r["rerun"]) for r in v.runs] == [S, 2 * S, S]
    assert v.accuracy == list(lor.values)
    text = "\n".join(v.lines())
    assert "every segment" in text and "ACCEPTED" in text
    assert "that an estimate estimates well is not shown" in text


def test_a_full_audit_handed_only_the_initial_states(lor):
    """Each segment starts from the one before it, re-run in this audit
    and matched: the most independent audit there is, handed nothing
    but the certificate, the programs, the salt and three initial
    states - and it still re-derives the accuracy values."""
    v = cert.audit(lor.data, SALT, lor.progs,
                   states={r: {0: lor.st[r][0]} for r in range(3)})
    assert v.accuracy == list(lor.values)


def test_a_wrong_image_or_bank(lor):
    hh = (PROGRAMS / "henonheiles-lf-fp64.cfta").read_text(encoding="utf-8")
    other = asm.assemble(hh, "henonheiles-lf-fp64")
    progs = dict(lor.progs)
    progs[0] = (other, lor.bank)
    refused("image-digest", cert.audit, lor.data, SALT, progs)
    flipped = bytearray(lor.bank)
    flipped[0] ^= 1
    progs[0] = (lor.img, bytes(flipped))
    refused("program-digest", cert.audit, lor.data, SALT, progs)
    progs[0] = (lor.img, lor.bank_half)
    refused("program-digest", cert.audit, lor.data, SALT, progs)
    progs = dict(lor.progs)
    del progs[2]
    refused("program-image", cert.audit, lor.data, SALT, progs)


def test_a_program_that_is_not_a_segment(lor):
    """A program whose state does not travel whole through the scratch
    block, or that deposits, is refused by name before it is run."""
    horner = asm.assemble((PROGRAMS / "horner-bank-fp64.cfta").read_text(
        encoding="utf-8"), "horner")
    bank = (PROGRAMS / "horner-bank-fp64.exp.bank").read_bytes()
    refused("program-shape", cert.run_chain, horner, bank, [0], 1)
    # and certify_run, handed a producer's own chain for it
    refused("program-shape", cert.certify_run, "main", horner, bank, SALT,
            [[0], [0]], [(16, 0)], steps=1)
    # a run whose certificate says fp128 while the image it names is fp64
    r0 = dataclasses.replace(lor.runs[0], fmt="fp128")
    data = with_runs(lor, [r0])
    refused("program-format", cert.audit, data, SALT, {0: lor.progs[0]})


SHAPE = """.format   fp64
.deposits {d}
{scratch}
.const    K = 0x3fd5555555555555
ldl  r3, 0
add  r3, r3, K
stl  r3, 0
halt
"""


def test_each_reason_a_program_is_not_a_segment():
    """The page's three reasons, each alone and each named in the
    refusal: no scratch block; a block that goes in and out at different
    widths, or at none; and a program that deposits (the census found
    only the last reached by a test)."""
    for d, (n_in, n_out), why in (
            (0, (None, None), "declares no scratch block"),
            (0, (2, 1), "goes in as 2 and out as 1"),
            (0, (0, 0), "goes in as 0 and out as 0"),
            (1, (1, 1), "it deposits")):
        scratch = "" if n_in is None else (f".scratch  in {n_in}\n"
                                           f".scratch  out {n_out}")
        img = asm.assemble(SHAPE.format(d=d, scratch=scratch), "shape")
        e = refused("program-shape", cert.run_chain, img, b"", [0], 1)
        assert why in e.message, (scratch, e.message)


def test_a_stream_that_is_not_the_one_certified(lor):
    one = [dec64("1")] * LANES
    refused("stream", cert.audit, lor.data, SALT, lor.progs,
            streams={0: (one, None, None)})
    e = refused("stream", cert.audit, lor.data, SALT, lor.progs,
                streams={0: ([0] * 2, None, None)})
    # its length is found as its length, before the hash that would
    # differ anyway (the census found the length check masked by it)
    assert "holds 2 values" in e.message and e.run == 0, e.message


def test_a_state_handed_that_is_not_the_one_certified(lor):
    states = {r: dict(s) for r, s in lor.states.items()}
    x = list(states[0][2])
    x[3] ^= 1                                       # lane 1 x, one ulp
    states[0][2] = x
    e = refused("state-hash", cert.audit, lor.data, SALT, lor.progs,
                states=states)
    assert (e.run, e.segment) == (0, 2) and "run 0 boundary 2" in e.message
    refused("state-shape", cert.audit, lor.data, SALT, lor.progs,
            states={0: {0: lor.init[:-1]}})
    refused("state-shape", cert.audit, lor.data, SALT, lor.progs,
            states={0: {S + 1: lor.init}})
    refused("state-shape", cert.audit, lor.data, SALT, lor.progs,
            states={5: {0: lor.init}})
    # a segment whose start was neither handed nor re-run into
    e = refused("state-missing", cert.audit, lor.data, SALT, lor.progs,
                states={0: {0: lor.init}}, choose={0: [2]})
    assert (e.run, e.segment) == (0, 2)


# ---- the chain --------------------------------------------------------------

def test_continuity(lor):
    r0 = lor.runs[0]
    chain = list(r0.chain)
    chain[2] = dataclasses.replace(chain[2], start=chain[1].start)
    e = refused("continuity", cert.audit, with_runs(lor, [
        dataclasses.replace(r0, chain=tuple(chain))]), SALT,
        {0: lor.progs[0]})
    assert (e.run, e.segment) == (0, 2)
    e = refused("continuity", cert.audit, with_runs(lor, [
        dataclasses.replace(r0, output=chain[0].start)]), SALT,
        {0: lor.progs[0]})
    assert (e.run, e.segment) == (0, S - 1)


def test_a_segment_whose_certified_end_differs(lor):
    """The certificate's last segment ends, it says, on a state one ulp
    from the one seq.run reaches - and its output says so too, so the
    chain is continuous, and the state handed for that boundary matches
    it. Re-running the segment from its certified start finds it."""
    r0 = lor.runs[0]
    bad = list(lor.st[0][S])
    bad[0] ^= 1
    h = cert.state_hash(SALT, cert.state_bytes("fp64", bad))
    chain = list(r0.chain)
    chain[S - 1] = dataclasses.replace(chain[S - 1], end=h)
    data = with_runs(lor, [dataclasses.replace(r0, chain=tuple(chain),
                                               output=h)])
    states = {0: dict(lor.states[0])}
    states[0][S] = bad
    e = refused("segment-end", cert.audit, data, SALT, {0: lor.progs[0]},
                states=states)
    assert (e.run, e.segment) == (0, S - 1)
    assert f"run 0 segment {S - 1}" in e.message


def test_a_segment_the_executor_refuses_is_refused_by_name(lor,
                                                          monkeypatch):
    """The checks before the re-run leave the executor nothing it refuses
    today: each image loaded, and its bank, its streams and every state
    handed were held to their shapes. The audit still names a refusal
    the executor makes at a re-run - `program-image`, at its run and
    segment - so that one a later executor adds is a refusal and not a
    crash. Shown with an executor made to refuse (the census found this
    refusal unreached, and it can only be reached so)."""
    def refuse(*a, **k):
        raise cert.seq.ProgramError("an executor made to refuse")
    monkeypatch.setattr(cert.seq, "run", refuse)
    e = refused("program-image", cert.audit, lor.data, SALT, lor.progs,
                states=lor.states, choose=QUICK)
    assert (e.run, e.segment) == (0, 0), e.message
    assert "made to refuse" in e.message


def test_a_segments_flags_or_status(lor):
    r0 = lor.runs[0]
    for field, val, name in (("flags", 0, "segment-flags"),
                             ("flags", 17, "segment-flags"),
                             ("status", 16, "segment-status")):
        chain = list(r0.chain)
        chain[1] = dataclasses.replace(chain[1], **{field: val})
        e = refused(name, cert.audit, with_runs(lor, [dataclasses.replace(
            r0, chain=tuple(chain))]), SALT, {0: lor.progs[0]},
            states={0: lor.states[0]})
        assert (e.run, e.segment) == (0, 1)


def test_one_boundary_state_altered_is_found_and_named(lor):
    """The real audit's red: a producer whose segment 1 went wrong - one
    bit of lane 1's x at boundary 2 - and who carried on from there.
    Its certificate is self-consistent (the chain is continuous, every
    hash matches the states it publishes), and the audit re-running
    segment 1 from its certified start names it."""
    b = 2
    st, rs = cert.run_chain(lor.img, lor.bank, lor.init, b)
    faulty = list(st[b])
    faulty[3] ^= 1
    st2, rs2 = cert.run_chain(lor.img, lor.bank, faulty, S - b)
    states = st[:b] + st2
    run = cert.certify_run("main", lor.img, lor.bank, SALT, states,
                           rs + rs2, steps=100)
    data = cert.encode(keyed((run,), ()))
    handed = {0: dict(enumerate(states))}
    e = refused("segment-end", cert.audit, data, SALT, {0: lor.progs[0]},
                states=handed)
    assert (e.run, e.segment) == (0, b - 1)
    assert f"run 0 segment {b - 1}" in e.message
    # every other segment is right, and an audit that re-runs only them
    # passes - which is what a sampled audit's stated escape probability
    # is about
    others = [k for k in range(S) if k != b - 1]
    v = cert.audit(data, SALT, {0: lor.progs[0]}, states=handed,
                   choose={0: others})
    assert v.runs[0]["rerun"] == others
    # the honest chain passes the same audit
    good = cert.certify_run("main", lor.img, lor.bank, SALT, lor.st[0],
                            lor.rs[0], steps=100)
    cert.audit(cert.encode(keyed((good,), ())),
               SALT, {0: lor.progs[0]}, states={0: {0: lor.init}})


# ---- the auxiliary runs' relation to the main run ---------------------------

def _fake_chain(start, n, flags=16):
    """A continuous chain of n segments from `start` whose other hashes
    are made up - for relation controls, which the audit decides before
    it re-runs anything."""
    hs = [start] + [hashlib.sha256(bytes([k]) * 7).hexdigest()
                    for k in range(1, n + 1)]
    return tuple(cert.Segment(hs[k], hs[k + 1], flags, 0) for k in range(n))


def _audit_runs(lor, runs, progs, **kw):
    kw.setdefault("states", {0: {0: lor.init}})
    return cert.audit(with_runs(lor, runs), SALT, progs, **kw)


def test_the_main_run_attached_as_its_own_half_step_run(lor):
    """verifier-C1's N1: every check would pass with an estimate of 0.
    As itself it has the main run's segments, not twice as many; run
    for twice as long on the main bank instead, its bank is not halved.
    Both refused by name."""
    r0 = lor.runs[0]
    itself = dataclasses.replace(r0, kind="half-step", h_slots=(0, 1, 2),
                                 parameters=())
    refused("aux-segments", _audit_runs, lor, [r0, itself],
            {0: lor.progs[0], 1: lor.progs[0]})
    ch = _fake_chain(r0.chain[0].start, 2 * S)
    longer = dataclasses.replace(itself, chain=ch, output=ch[-1].end)
    refused("aux-bank", _audit_runs, lor, [r0, longer],
            {0: lor.progs[0], 1: lor.progs[0]})


def test_every_auxiliary_relation_refused_by_name(lor):
    r0, r1, r2 = lor.runs
    P = lor.progs
    zeros2 = [0, 0]
    two_lanes = tuple(cert.stream_hash(SALT, n, cert.state_bytes(
        "fp64", zeros2)) for n in "abc")
    cases = []
    # format
    cases.append(("aux-format", [r0, dataclasses.replace(
        r2, kind="half-step", h_slots=(0, 1, 2))], {0: P[0], 1: P[2]}))
    cases.append(("aux-format", [r0, dataclasses.replace(r1, kind="wider",
                                                         h_slots=())],
                  {0: P[0], 1: P[1]}))
    # lanes
    cases.append(("aux-lanes", [r0, dataclasses.replace(
        r1, lanes=2, streams=two_lanes)], {0: P[0], 1: P[1]}))
    # image: the steps it states, a different image, other instructions
    cases.append(("aux-image", [r0, dataclasses.replace(r1, steps=50)],
                  {0: P[0], 1: P[1]}))
    src = (PROGRAMS / "lorenz63-rk4-fp64.cfta").read_text(encoding="utf-8")
    img50 = asm.assemble(src.replace("repeat 100", "repeat 50"), "l63-50")
    cases.append(("aux-image", [r0, dataclasses.replace(
        r1, image=cert.sha256(img50),
        digest=cert.sha256(img50 + lor.bank_half))],
        {0: P[0], 1: (img50, lor.bank_half)}))
    img50w = asm.assemble(src.replace("repeat 100", "repeat 50").replace(
        ".format   fp64", ".format   fp128"), "l63-50w")
    cases.append(("aux-image", [r0, dataclasses.replace(
        r2, image=cert.sha256(img50w),
        digest=cert.sha256(img50w + lor.bank_w))],
        {0: P[0], 1: (img50w, lor.bank_w)}))
    # segments: a wider run of three
    ch = _fake_chain(r2.chain[0].start, S - 1)
    cases.append(("aux-segments", [r0, dataclasses.replace(
        r2, chain=ch, output=ch[-1].end)], {0: P[0], 1: P[2]}))
    # h-slots: one past the bank
    cases.append(("aux-h-slots", [r0, dataclasses.replace(
        r1, h_slots=(0, 1, 9))], {0: P[0], 1: P[1]}))
    # bank: only H halved while H2 and H6 are named; H2 and H6 halved and
    # not named; the wider bank re-derived at fp128 instead of widened -
    # the different discrete scheme docs/ROADMAP.md warns of
    only_h = halved("fp64", lor.bank, (0,))
    cases.append(("aux-bank", [r0, dataclasses.replace(
        r1, digest=cert.sha256(lor.img + only_h))],
        {0: P[0], 1: (lor.img, only_h)}))
    cases.append(("aux-bank", [r0, dataclasses.replace(r1, h_slots=(0,))],
                  {0: P[0], 1: P[1]}))
    f128 = F128

    def d128(t):
        return chars.from_decimal(f128, t, sf.RND_RNE)[0]
    h = d128("0.01")
    rederived = [h, sf.mul(f128, h, d128("0.5"))[0],
                 sf.div(f128, h, d128("6"))[0], d128("2"), d128("10"),
                 d128("28"), sf.div(f128, d128("8"), d128("3"))[0]]
    bank_r = cert.state_bytes("fp128", rederived)
    assert bank_r != lor.bank_w
    cases.append(("aux-bank", [r0, dataclasses.replace(
        r2, digest=cert.sha256(lor.img128 + bank_r))],
        {0: P[0], 1: (lor.img128, bank_r)}))
    # streams: a half-step run given another stream a; a wider one too
    one = [dec64("1")] * LANES
    cases.append(("aux-streams", [r0, dataclasses.replace(r1, streams=(
        cert.stream_hash(SALT, "a", cert.state_bytes("fp64", one)),)
        + r1.streams[1:])], {0: P[0], 1: P[1]},
        {"streams": {1: (one, None, None)}}))
    one_w = [cert.widen("fp64", x) for x in one]
    cases.append(("aux-streams", [r0, dataclasses.replace(r2, streams=(
        cert.stream_hash(SALT, "a", cert.state_bytes("fp128", one_w)),)
        + r2.streams[1:])], {0: P[0], 1: P[2]},
        {"streams": {1: (one_w, None, None)}}))
    # start
    other = hashlib.sha256(b"another start").hexdigest()
    ch1 = (dataclasses.replace(r1.chain[0], start=other),) + r1.chain[1:]
    cases.append(("aux-start", [r0, dataclasses.replace(r1, chain=ch1)],
                  {0: P[0], 1: P[1]}))
    ch2 = (dataclasses.replace(r2.chain[0], start=other),) + r2.chain[1:]
    cases.append(("aux-start", [r0, dataclasses.replace(r2, chain=ch2)],
                  {0: P[0], 1: P[2]}))
    cases.append(("state-missing", [r0, r2], {0: P[0], 1: P[2]},
                  {"states": {}}))
    for case in cases:
        name, runs, progs = case[:3]
        kw = case[3] if len(case) > 3 else {}
        e = refused(name, _audit_runs, lor, runs, progs, **kw)
        assert e.run == (0 if name == "state-missing" else 1), name
    # and both honest auxiliary runs pass their relation on their own
    _audit_runs(lor, [r0, r1], {0: P[0], 1: P[1]},
                states={0: lor.states[0], 1: lor.states[1]})
    _audit_runs(lor, [r0, r2], {0: P[0], 1: P[2]},
                states={0: lor.states[0], 1: lor.states[2]})


def test_no_wider_run_above_fp256():
    """A rounding estimate by a re-run one format wider is refused by
    name at fp256: a program image is at most fp256."""
    src = (PROGRAMS / "lorenz63-rk4-fp256.cfta").read_text(encoding="utf-8")
    img = asm.assemble(src, "lorenz63-rk4-fp256")
    bank = (PROGRAMS / "lorenz63-rk4-fp256.classic.bank").read_bytes()
    zeros = tuple(cert.stream_hash(SALT, n, bytes(32)) for n in "abc")
    start = hashlib.sha256(b"x").hexdigest()
    ch = _fake_chain(start, 1)
    main = cert.Run("main", "fp256", cert.sha256(img),
                    cert.sha256(img + bank), 1, 100, zeros, (), ch,
                    ch[-1].end)
    wider = dataclasses.replace(main, kind="wider")
    data = cert.encode(keyed((main, wider), ()))
    e = refused("aux-format", cert.audit, data, SALT,
                {0: (img, bank), 1: (img, bank)})
    assert "top of the ladder" in e.message


# ---- accuracy ---------------------------------------------------------------

def _with_entries(lor, entries):
    return cert.encode(dataclasses.replace(lor.cert,
                                           accuracy=tuple(entries)))


QUICK = {0: [0], 1: [0], 2: [0]}


def test_each_accuracy_value_is_re_derived(lor):
    e0, e1, e2, e3 = lor.entries
    q0, q1, q2, q3 = lor.values
    wrong = [
        (0, dataclasses.replace(e0, value=cert.Value(
            "exact", exact=q0 + Fraction(1, 1 << 60)))),
        (1, dataclasses.replace(e1, value=dataclasses.replace(
            e1.value, bits=e1.value.bits + 1))),
        # the upward rounding's bits, labelled downward: q1 is not an
        # fp64 value, so the two differ
        (1, dataclasses.replace(e1, value=dataclasses.replace(
            e1.value, rnd="rdn"))),
        (2, dataclasses.replace(e2, value=dataclasses.replace(
            e2.value, lo=e2.value.hi))),
        (3, dataclasses.replace(e3, value=cert.Value("exact", exact=-q3))),
    ]
    for j, bad in wrong:
        entries = list(lor.entries)
        entries[j] = bad
        e = refused("accuracy-value", cert.audit, _with_entries(lor, entries),
                    SALT, lor.progs, states=lor.states, choose=QUICK)
        assert e.message.startswith(f"entry {j}: ")
        assert e.entry == j


def test_an_accuracy_entry_refers_to_what_exists(lor):
    e0, e1, e2, e3 = lor.entries
    cases = [
        ("accuracy-run", dataclasses.replace(e0, uses=2)),
        ("accuracy-run", dataclasses.replace(e0, uses=0)),
        ("accuracy-run", dataclasses.replace(e1, uses=1)),
        ("accuracy-run", dataclasses.replace(e2, uses=7)),
        ("accuracy-scope", dataclasses.replace(e1, lane=LANES)),
        ("accuracy-slot", dataclasses.replace(
            e3, terms=((Fraction(1), (0, 3)),))),
    ]
    for name, bad in cases:
        e = refused(name, cert.audit, _with_entries(lor, [bad]), SALT,
                    lor.progs, states=lor.states, choose=QUICK)
        assert e.entry == 0
    # an estimate compares run 0 with ANOTHER run: derive() refuses run 0
    # whatever the run objects it is handed call it
    odd = ((dataclasses.replace(lor.runs[0], kind="half-step"),)
           + tuple(lor.runs[1:]))
    refused("accuracy-run", cert.derive, dataclasses.replace(e0, uses=0),
            odd, lor.shapes, lor.ends)
    # the final state an entry needs, neither handed nor re-run into
    e = refused("state-missing", cert.audit, lor.data, SALT, lor.progs,
                states={r: {0: lor.st[r][0]} for r in range(3)},
                choose=QUICK)
    assert (e.run, e.segment, e.entry) == (0, S, 0)


def test_an_exact_value_needs_a_finite_state(lor):
    """A lane that holds a NaN has no exact quantity: refused by name,
    never approximated. (Lorenz-63 carries a NaN along faithfully.)"""
    nan = sf.qnan_bits(F64)
    init = [nan, dec64("1"), dec64("1")]
    st, rs = cert.run_chain(lor.img, lor.bank, init, 1)
    run = cert.certify_run("main", lor.img, lor.bank, SALT, st, rs,
                           steps=100)
    probe = cert.Entry("drift", "measurement", 0, 0,
                       cert.Value("exact", exact=Fraction(0)),
                       "square-norm", SQUARES)
    refused("accuracy-finite", cert.derive, probe, (run,), [(F64, 3)],
            {(0, 0): st[0], (0, 1): st[1]})
    data = cert.encode(keyed((run,), (probe,)))
    refused("accuracy-finite", cert.audit, data, SALT, {0: lor.progs[0]},
            states={0: {0: init}})


@pytest.fixture(scope="module")
def henon():
    """Henon-Heiles at fp64: its energy has y^3/3, so its drift is an
    exact rational with 3 in the denominator - what neither hex nor a
    finite decimal can write (verifier-C1 measured 2^171 * 3 on one
    segment)."""
    src = (PROGRAMS / "henonheiles-lf-fp64.cfta").read_text(encoding="utf-8")
    img = asm.assemble(src, "henonheiles-lf-fp64")
    bank = (PROGRAMS / "henonheiles-lf-fp64.classic.bank").read_bytes()
    init = []
    for i in range(2):                      # programs/check.py's ensemble
        init += [dec64("0"), dec64(repr(0.1 + i / 1024)), dec64("0.5"),
                 dec64("0")]
    st, rs = cert.run_chain(img, bank, init, 3)
    run = cert.certify_run("main", img, bank, SALT, st, rs, steps=100)
    ends = {(0, 0): st[0], (0, 3): st[-1]}
    ent = []
    for lane in (0, 1, None):
        e, q = entry_with("drift", "measurement", 0, lane, (run,),
                          [(F64, 4)], ends, "exact", label="energy",
                          terms=ENERGY)
        ent.append((e, q))
    data = cert.encode(keyed((run,), tuple(e for e, _ in ent)))
    return types.SimpleNamespace(img=img, bank=bank, init=init, st=st,
                                 data=data, entries=ent)


# H = (px^2 + py^2)/2 + (x^2 + y^2)/2 + x^2 y - y^3/3 over the slots x=0,
# y=1, px=2, py=3 (programs/gen_odes.py's layout).
ENERGY = ((Fraction(1, 2), (2, 2)), (Fraction(1, 2), (3, 3)),
          (Fraction(1, 2), (0, 0)), (Fraction(1, 2), (1, 1)),
          (Fraction(1), (0, 0, 1)), (Fraction(-1, 3), (1, 1, 1)))


def test_henon_heiles_drift_is_an_exact_rational(henon):
    v = cert.audit(henon.data, SALT, {0: (henon.img, henon.bank)},
                   states={0: {0: henon.init}})
    (_, q0), (_, q1), (_, qm) = henon.entries
    assert v.accuracy == [q0, q1, qm]
    assert qm == max(abs(q0), abs(q1))
    assert q1 != 0 and q1.denominator % 3 == 0
    # the same value rounded to fp64 is not what was certified: the 3
    # in the denominator is what no binary value can hold
    rounded = cert.element_fraction("fp64", cert.round_rational("fp64", q1,
                                                               "rne"))[1]
    assert rounded != q1
    L = lines_of(henon.data)
    i = find(L, "value exact", 1)
    bad = rebuilt(L[:i] + ["value exact " + cert.rational_text(rounded)]
                  + L[i + 1:])
    e = refused("accuracy-value", cert.audit, bad, SALT,
                {0: (henon.img, henon.bank)}, states={0: {0: henon.init}})
    assert e.message.startswith("entry 1: ")


@pytest.mark.parametrize("fmt,k", [("fp64", 171), ("fp256", 720)])
def test_one_segment_of_henon_heiles_drifts_by_three_times_a_power_of_two(
        fmt, k):
    """verifier-C1's measurement, reproduced: over one segment of
    programs/check.py's first two members, the energy's drift has the
    denominator 2^171 x 3 at fp64 and 2^720 x 3 at fp256 - inside the
    width rule, and past what hex or a finite decimal can write."""
    f = FORMATS[fmt]
    src = (PROGRAMS / f"henonheiles-lf-{fmt}.cfta").read_text(
        encoding="utf-8")
    img = asm.assemble(src, f"henonheiles-lf-{fmt}")
    bank = (PROGRAMS / f"henonheiles-lf-{fmt}.classic.bank").read_bytes()

    def d(t):
        return chars.from_decimal(f, t, sf.RND_RNE)[0]
    init = []
    for i in range(2):
        init += [d("0"), d(repr(0.1 + i / 1024)), d("0.5"), d("0")]
    st, rs = cert.run_chain(img, bank, init, 1)
    run = cert.certify_run("main", img, bank, None, st, rs, steps=100)
    for lane in (0, 1):
        probe = cert.Entry("drift", "measurement", 0, lane,
                           cert.Value("exact", exact=Fraction(0)), "energy",
                           ENERGY)
        q = cert.derive(probe, (run,), [(f, 4)], {(0, 0): st[0],
                                                  (0, 1): st[1]})
        assert q.denominator == 3 << k
        assert q.denominator.bit_length() <= cert.WIDTH
        assert abs(q.numerator).bit_length() <= cert.WIDTH


# ---- sampling ---------------------------------------------------------------

def spec_sample(seed, run, S_, k):
    """docs/CERTIFICATES.md's sampling procedure, written again from the
    page: SHA-256 counter blocks, 64-bit big-endian words, rejection
    below the largest multiple of m, a partial Fisher-Yates."""
    def words():
        c = 0
        while True:
            blk = hashlib.sha256(b"cft-certificate 1 sample\x00" + seed
                                 + struct.pack(">I", run)
                                 + struct.pack(">Q", c)).digest()
            for i in range(0, 32, 8):
                yield struct.unpack(">Q", blk[i:i + 8])[0]
            c += 1
    w = words()
    a = list(range(S_))
    for j in range(k):
        m = S_ - j
        while True:
            x = next(w)
            if x < (1 << 64) - (1 << 64) % m:
                break
        r = j + x % m
        a[j], a[r] = a[r], a[j]
    return sorted(a[:k])


def test_the_sampling_prng():
    for seed in (bytes(32), SALT, hashlib.sha256(b"auditor").digest()):
        for run, S_, k in ((0, 10, 3), (1, 8, 8), (2, 1000, 17), (7, 5, 1)):
            assert cert.sample(seed, run, S_, k) == spec_sample(seed, run,
                                                                S_, k)
    # rejection, with words chosen to hit it: m = 3 rejects 2^64 - 1
    words = iter([(1 << 64) - 1, 5])
    assert cert._uniform(words, 3) == 2
    for bad in ((bytes(31), 0, 4, 2), (bytes(32), 0, 4, 0),
                (bytes(32), 0, 4, 5),
                # each argument held to its type, bool not an integer
                (list(bytes(32)), 0, 4, 2), (bytes(32), True, 4, 2),
                (bytes(32), -1, 4, 2), (bytes(32), 0, True, 1),
                (bytes(32), 0, 4, True), (bytes(32), 0, 4.0, 2),
                (bytes(32), 0, 4, 2.0)):
        refused("choice", cert.sample, *bad)


def test_the_escape_probability():
    ep = cert.escape_probability
    assert ep(4, 2, 1) == Fraction(1, 2)
    assert ep(8, 3, 1) == Fraction(5, 8)
    assert ep(10, 10, 1) == 0
    assert ep(10, 3, 0) == 1
    assert ep(10, 3, 2) == Fraction(7, 15)


def test_a_sampled_audit_states_what_it_missed(lor):
    seed = bytes(32)
    v = cert.audit(lor.data, SALT, lor.progs, states=lor.states,
                   choose={0: ("sample", 2), 1: ("sample", 3), 2: [1, 3]},
                   seed=seed)
    assert v.runs[0]["rerun"] == cert.sample(seed, 0, S, 2)
    assert v.runs[1]["rerun"] == cert.sample(seed, 1, 2 * S, 3)
    assert v.runs[2]["rerun"] == [1, 3]
    text = "\n".join(v.lines())
    assert "C(4-f,2)/C(4,2); for f = 1 that is 1/2" in text
    assert "C(8-f,3)/C(8,3); for f = 1 that is 5/8" in text
    assert seed.hex() in text
    # no seed given: the auditor draws its own, never the certificate's,
    # and reports it so the sample can be reproduced
    v1 = cert.audit(lor.data, SALT, lor.progs, states=lor.states,
                    choose={0: ("sample", 1)})
    drawn = bytes.fromhex(v1.runs[0]["seed"])
    assert len(drawn) == 32
    assert v1.runs[0]["rerun"] == cert.sample(drawn, 0, S, 1)
    for bad in ({0: ("sample", 0)}, {0: ("sample", S + 1)}, {0: [S]},
                {0: [1, 1]}, {0: []}, {3: "all"}, {0: "most"},
                # a sample is the pair ("sample", k) and nothing like it
                {0: ["sample", 2]}, {0: ("sample", 2, 3)}):
        e = refused("choice", cert.audit, lor.data, SALT, lor.progs,
                    states=lor.states, choose=bad, seed=seed)
        # a size the run cannot give is found as the choice's, at its
        # run, before the sampler is asked for it
        if bad in ({0: ("sample", 0)}, {0: ("sample", S + 1)}):
            assert e.run == 0 and "a sample's size" in e.message, e.message
    # and two indices in a tuple are those two segments, not a sample
    v2 = cert.audit(lor.data, SALT, lor.progs, states=lor.states,
                    choose={2: (1, 3)}, seed=seed)
    assert (v2.runs[2]["how"], v2.runs[2]["rerun"]) == ("named", [1, 3])


# ---- identity ---------------------------------------------------------------

def test_identity_is_reported_never_checked(lor):
    """An unknown field is reported as unknown; a stated one as stated,
    not checked - and an audit passes whatever the producer says it ran
    on, because the bits are the same on every conforming build."""
    rows = cert.identity_report(lor.cert)
    assert "build-id: unknown - the producer did not record it" in rows
    assert "backend: software - stated, not checked" in rows
    said = cert.Identity(
        "commit=0123456789abcdef0123456789abcdef01234567 tracked=modified "
        "untracked=present", "xrt", "ab" * 32, "00000a00",
        ("0000f0ff", "000007ff"), 2)
    data = cert.encode(dataclasses.replace(lor.cert, identity=said))
    L = lines_of(data)
    assert L[find(L, "build-id")] == (
        "build-id commit=0123456789abcdef0123456789abcdef01234567 "
        "tracked=modified untracked=present")
    v = cert.audit(data, SALT, lor.progs, states=lor.states, choose=QUICK)
    text = "\n".join(v.lines())
    assert "device-caps: 0000f0ff 000007ff - stated, not checked" in text
    assert "unknown" not in text


def test_the_build_id_is_cft_build_ids_string_verbatim(lor):
    """P2's cft_build_id() grammar (host/include/cft.h), recorded byte for
    byte: `unknown` whole, or commit, tracked and untracked in that
    order, the commit 40 lowercase hex digits or 64 in a SHA-256
    repository. Every form it can return reads back as itself."""
    L = lines_of(lor.data)
    i = find(L, "build-id")
    for c in ("a" * 40, "0123456789abcdef" * 4):
        for t in ("clean", "modified"):
            for u in ("none", "present"):
                s = f"commit={c} tracked={t} untracked={u}"
                back = cert.parse(rebuilt(L[:i] + ["build-id " + s]
                                          + L[i + 1:]))
                assert back.identity.build_id == s
    assert cert.parse(lor.data).identity.build_id == "unknown"
    # an image that predates CAPS2 publishes one CAPS word
    # (cft_image_id.n_caps is 1 below VERSION 0x800), and the field
    # records one
    j = find(L, "device-caps")
    one = cert.parse(rebuilt(L[:j] + ["device-caps 18a6ff1f"] + L[j + 1:]))
    assert one.identity.device_caps == ("18a6ff1f",)


# ---- the gates verifier-C2 found missing, and the orders it found open ------
#
# verifier-C2 (2026-09-28, 10:08:17) planted fourteen defects that no test
# above could fail for, and found five orders the page left open. Each
# test below exists for one of them, and each was watched failing with
# C2's plant or P1's own (Data/runs/2026-09-28-cert-round/ledger/P1.md).

# A segment program small enough to choose its states: x and y pass
# through untouched and z gains h*h a segment, so a half-step run (h/2,
# twice the segments) ends with only the LAST slot different, by an exact
# amount. A real program, run by seq.run like any other.
ZSQ = """.format   fp64
.deposits 0
.bank     external
.scratch  in 3
.scratch  out 3
.const    H
ldl  r3, 0
ldl  r4, 1
ldl  r5, 2
fma  r5, H, H, r5
stl  r3, 0
stl  r4, 1
stl  r5, 2
halt
"""

# IEEE 754's binary interchange fields, written out here rather than read
# from cft_golden, so that the values below are derived with nothing the
# implementation under test also uses.
WIDTHS = {"fp32": (8, 23), "fp64": (11, 52), "fp128": (15, 112),
          "fp256": (19, 236)}


def ieee(fmt, bits):
    """A finite element's exact value, from its sign, exponent and
    significand fields."""
    ew, mw = WIDTHS[fmt]
    sign, e, m = bits >> (ew + mw), (bits >> mw) & ((1 << ew) - 1), \
        bits & ((1 << mw) - 1)
    bias = (1 << (ew - 1)) - 1
    assert e != (1 << ew) - 1, "not finite"
    if e == 0:
        v = Fraction(m, 1 << (bias - 1 + mw))
    else:
        v = Fraction((1 << mw) | m) * Fraction(2) ** (e - bias - mw)
    return -v if sign else v


def pow2_64(k):
    """The fp64 encoding of 2^k, for a normal k."""
    assert -1022 <= k <= 1023
    return (k + 1023) << 52


@pytest.fixture(scope="module")
def zsq():
    img = asm.assemble(ZSQ, "zsq")
    bank = cert.state_bytes("fp64", [dec64("0.25")])
    return types.SimpleNamespace(img=img, bank=bank,
                                 half=halved("fp64", bank, (0,)))


def zsq_cert(z, init, entries, segments=2):
    """A keyed certificate of zsq from `init` over `segments` segments,
    with its half-step run (h-slot 0 halved, twice the segments), every
    chain by seq.run. -> (bytes, programs, states, (main, half) states)"""
    st0, rs0 = cert.run_chain(z.img, z.bank, init, segments)
    st1, rs1 = cert.run_chain(z.img, z.half, init, 2 * segments)
    r0 = cert.certify_run("main", z.img, z.bank, SALT, st0, rs0, steps=1)
    r1 = cert.certify_run("half-step", z.img, z.half, SALT, st1, rs1,
                          steps=1, h_slots=(0,))
    return (cert.encode(keyed((r0, r1), entries)),
            {0: (z.img, z.bank), 1: (z.img, z.half)},
            {0: {0: init}, 1: {0: init}}, (st0, st1))


def test_an_h_slot_that_halving_cannot_change_is_refused(zsq):
    """An h-slot names a bank constant the half-step run halves. One
    holding zero, or an infinity, halves to itself, and a NaN has no
    half: the half-step run would be the main run again, so each is
    refused `aux-h-slots` - before the bank is compared, where the
    zero and the infinity would pass (the census found this check with
    no control)."""
    for text, what in (("0", "zero"), ("inf", "inf"), ("-inf", "-inf"),
                       ("nan", "nan")):
        z = types.SimpleNamespace(
            img=zsq.img, bank=cert.state_bytes("fp64", [dec64(text)]))
        z.half = z.bank                    # halved, it is itself
        data, progs, states, _ = zsq_cert(z, [dec64("1")] * 3, ())
        e = refused("aux-h-slots", cert.audit, data, SALT, progs,
                    states=states)
        assert f"holds {what}" in e.message and e.run == 1, e.message


def estimate(value, lane=None):
    return cert.Entry("step-halving", "estimate", 1, lane, value)


def drift(terms, value, lane=0, label="q"):
    return cert.Entry("drift", "measurement", 0, lane, value, label,
                      tuple(terms))


def test_the_lorenz_values_are_what_the_states_say(lor):
    """The fixture's four accuracy values, derived again from its states
    with this file's own decoding and arithmetic, not cert.derive."""
    st0, st1, st2 = lor.st
    f0 = [ieee("fp64", x) for x in st0[-1]]
    f1 = [ieee("fp64", x) for x in st1[-1]]
    f2 = [ieee("fp128", x) for x in st2[-1]]
    i0 = [ieee("fp64", x) for x in st0[0]]

    def diff(fa, fb, lane):
        return max(abs(fa[3 * lane + s] - fb[3 * lane + s]) for s in range(3))

    def square(st, lane):
        return sum(v * v for v in st[3 * lane:3 * lane + 3])
    d = [square(f0, i) - square(i0, i) for i in range(LANES)]
    assert lor.values == (max(diff(f0, f1, i) for i in range(LANES)),
                          diff(f0, f2, 0), max(abs(x) for x in d), d[2])


def test_an_estimate_reads_every_slot_to_the_last(zsq):
    """Only zsq's last slot differs between the two runs, by exactly 1/16
    (two steps of 1/16 against four of 1/64): an estimate that stopped
    one slot short would read 0."""
    one = dec64("1")
    data, progs, states, (st0, st1) = zsq_cert(
        zsq, [one] * 3, [estimate(cert.Value("exact", exact=Fraction(1, 16))),
                         estimate(cert.Value("exact", exact=Fraction(1, 16)),
                                  lane=0)])
    diffs = [abs(ieee("fp64", a) - ieee("fp64", b))
             for a, b in zip(st0[-1], st1[-1])]
    assert diffs == [0, 0, Fraction(1, 16)]
    assert cert.audit(data, SALT, progs, states=states).accuracy == \
        [Fraction(1, 16)] * 2


def test_the_width_rule_holds_an_elements_own_value(zsq):
    """fp64 2^1023 (7fe0000000000000) has a 1,024-bit numerator. In both
    runs' final states it is unchanged, so its difference is 0 - and the
    estimate is still refused `width`, at the element, never computed
    past it."""
    one = dec64("1")
    data, progs, states, _ = zsq_cert(
        zsq, [0x7FE0000000000000, one, one],
        [estimate(cert.Value("exact", exact=Fraction(1, 16)))])
    e = refused("width", cert.audit, data, SALT, progs, states=states)
    assert "slot 0" in e.message


def test_the_width_rule_holds_a_drifts_every_product(zsq):
    """A term 2^-100 x s0 x s1 over s0 = 2^-1000 and s1 = 2^1000: its
    value is 2^-100 and its first product 2^-1100, with a 1,101-bit
    denominator. Refused at that product, not after it."""
    data, progs, states, _ = zsq_cert(
        zsq, [pow2_64(-1000), pow2_64(1000), dec64("1")],
        [drift([(Fraction(1, 1 << 100), (0, 1))],
               cert.Value("exact", exact=Fraction(0)))])
    e = refused("width", cert.audit, data, SALT, progs, states=states)
    assert "product" in e.message


# verifier-C2's terms: 1/a + 1/b has a 1,202-bit denominator, and adding
# -1/b brings the sum back to 1/a - so only a check on the partial sum
# can refuse it, and the same three terms in another order are within
# the rule at every step.
C2_A, C2_B = (1 << 600) + 1, (1 << 601) - 1


def test_the_width_rule_holds_a_drifts_every_partial_sum(zsq):
    # the page's count (CERTIFICATES.md, "Accuracy entries"), which
    # verifier-C2 found one short
    s = Fraction(1, C2_A) + Fraction(1, C2_B)
    assert s.denominator.bit_length() == 1202
    assert "whose denominator has 1,202 bits" in " ".join(_doc().split())
    one = dec64("1")
    terms = [(Fraction(1, C2_A), ()), (Fraction(1, C2_B), ()),
             (Fraction(-1, C2_B), ())]
    data, progs, states, _ = zsq_cert(
        zsq, [one] * 3, [drift(terms, cert.Value("exact",
                                                 exact=Fraction(0)))])
    e = refused("width", cert.audit, data, SALT, progs, states=states)
    assert "sum at term 1" in e.message
    # the order of the terms decides it: the same terms, the sum at
    # every step within the rule, and the same exact value
    data, progs, states, _ = zsq_cert(
        zsq, [one] * 3,
        [drift(terms[1:] + terms[:1], cert.Value("exact", exact=Fraction(0)))])
    assert cert.audit(data, SALT, progs, states=states).accuracy == [0]


def test_an_enclosure_holds_a_value_at_its_ends(zsq):
    """lo <= value <= hi, both ends inclusive: zsq's estimate is exactly
    1/16, an fp32 value, so [1/16, 1/16] holds it, and one ulp either
    way past it does not."""
    one = dec64("1")
    sixteenth = 0x3D800000                              # fp32 1/16
    for lo, hi, ok in ((sixteenth, sixteenth, True),
                       (sixteenth - 1, sixteenth, True),
                       (sixteenth, sixteenth + 1, True),
                       (sixteenth + 1, sixteenth + 2, False),
                       (sixteenth - 2, sixteenth - 1, False)):
        data, progs, states, _ = zsq_cert(
            zsq, [one] * 3,
            [estimate(cert.Value("enclosed", fmt="fp32", lo=lo, hi=hi))])
        if ok:
            cert.audit(data, SALT, progs, states=states)
        else:
            refused("accuracy-value", cert.audit, data, SALT, progs,
                    states=states)


SELF_K = """.format   {fmt}
.deposits 0
.scratch  in {n}
.scratch  out {n}
{strict}
.const    K = 0x{k:0{w}x}
{extra}
ldl  r3, 0
add  r3, r3, K
stl  r3, 0
halt
"""


def test_a_wider_image_is_held_to_its_constants_and_header():
    """Images that carry their own constant K = RN(1/3), each run from 1
    for two segments. One format wider, K exactly widened is the same
    program; K re-derived at fp128 - the different discrete scheme the
    plan warns of - is not, and neither is the same program with a
    header field of its own: a flag (SCRATCH_STRICT), a second constant
    (n_consts) or a wider scratch block (scratch_io). (The fourth,
    max_deposits, cannot differ between two images that both passed step
    4: neither deposits.)"""
    k64 = sf.div(F64, dec64("1"), dec64("3"))[0]
    k128 = sf.div(F128, chars.from_decimal(F128, "1", sf.RND_RNE)[0],
                  chars.from_decimal(F128, "3", sf.RND_RNE)[0])[0]
    assert k128 != cert.widen("fp64", k64)

    def image(fmt, k, strict="", n=1, extra=""):
        w = FORMATS[fmt].width // 4
        return asm.assemble(SELF_K.format(fmt=fmt, k=k, w=w, strict=strict,
                                          n=n, extra=extra), f"k-{fmt}")
    main_img = image("fp64", k64)
    st0, rs0 = cert.run_chain(main_img, b"", [dec64("1")], 2)
    r0 = cert.certify_run("main", main_img, b"", SALT, st0, rs0, steps=1)
    init_w = [cert.widen("fp64", dec64("1"))]
    kw128 = cert.widen("fp64", k64)
    for img, name, why in (
            (image("fp128", kw128), None, None),
            (image("fp128", k128), "aux-image", "constants"),
            (image("fp128", kw128, ".scratch  strict"),
             "aux-image", "header's flags"),
            (image("fp128", kw128, extra=f".const    K2 = 0x{kw128:032x}"),
             "aux-image", "header's n_consts"),
            (image("fp128", kw128, n=2), "aux-image",
             "header's scratch_io_word")):
        init = init_w * (2 if "scratch_io" in (why or "") else 1)
        st1, rs1 = cert.run_chain(img, b"", init, 2)
        r1 = cert.certify_run("wider", img, b"", SALT, st1, rs1, steps=1)
        data = cert.encode(keyed((r0, r1), ()))
        # None for the bank of an image that carries its constants
        args = (data, SALT, {0: (main_img, None), 1: (img, None)})
        kw = {"states": {0: {0: [dec64("1")]}, 1: {0: init}}}
        if name is None:
            cert.audit(*args, **kw)
        else:
            assert why in refused(name, cert.audit, *args, **kw).message


def test_a_half_step_run_needs_a_bank_to_halve():
    """A half-step run is the main image with named bank slots halved. A
    main image that carries its own constants has no bank, so no slot of
    it can be named: refused `aux-h-slots`, not a crash (the census found
    this check with no control)."""
    k64 = sf.div(F64, dec64("1"), dec64("3"))[0]
    img = asm.assemble(SELF_K.format(fmt="fp64", k=k64, w=16, strict="",
                                     n=1, extra=""), "k-fp64")
    start = [dec64("1")]
    st0, rs0 = cert.run_chain(img, b"", start, 2)
    st1, rs1 = cert.run_chain(img, b"", start, 4)
    r0 = cert.certify_run("main", img, b"", SALT, st0, rs0, steps=1)
    r1 = cert.certify_run("half-step", img, b"", SALT, st1, rs1, steps=1,
                          h_slots=(0,))
    e = refused("aux-h-slots", cert.audit, cert.encode(keyed((r0, r1), ())),
                SALT, {0: (img, b""), 1: (img, b"")},
                states={0: {0: start}, 1: {0: start}})
    assert "carries its constants" in e.message and e.run == 1


def test_the_auditors_seed_is_never_the_certificates(lor):
    """With no seed given, the auditor draws its own: two audits of the
    same certificate draw two seeds. A seed derived from the certificate
    would be the same seed both times - one a producer could predict,
    and re-salt against until the sample missed a wrong segment."""
    ask = {0: ("sample", 1), 1: ("sample", 1), 2: ("sample", 1)}
    seeds = {cert.audit(lor.data, SALT, lor.progs, states=lor.states,
                        choose=ask).runs[0]["seed"] for _ in range(2)}
    assert len(seeds) == 2


def test_the_audits_order_step_by_step(lor):
    """Every adjacent pair of the audit's steps from the auditor's choice
    to accuracy, each with a defect of its own: the earlier step's name
    wins, and each defect alone is refused by its own."""
    P = lor.progs
    bad_choice = {0: ("sample", 99)}
    hh = asm.assemble((PROGRAMS / "henonheiles-lf-fp64.cfta").read_text(
        encoding="utf-8"), "henonheiles-lf-fp64")
    bad_progs = dict(P)
    bad_progs[0] = (hh, lor.bank)
    bad_streams = {0: ([dec64("1")] * LANES, None, None)}
    bad_states = {r: dict(s) for r, s in lor.states.items()}
    x = list(bad_states[0][1])
    x[0] ^= 1
    bad_states[0][1] = x
    r0, r1, r2 = lor.runs
    ch = list(r0.chain)
    ch[2] = dataclasses.replace(ch[2], start=ch[1].start)
    cont = dataclasses.replace(r0, chain=tuple(ch))
    rel = dataclasses.replace(r1, steps=50)
    end_state = list(lor.st[0][S])
    end_state[0] ^= 1
    h = cert.state_hash(SALT, cert.state_bytes("fp64", end_state))
    ch = list(r0.chain)
    ch[S - 1] = dataclasses.replace(ch[S - 1], end=h)
    end = dataclasses.replace(r0, chain=tuple(ch), output=h)
    end_states = {r: dict(s) for r, s in lor.states.items()}
    end_states[0][S] = end_state
    e0 = lor.entries[0]
    wrong = dataclasses.replace(e0, value=cert.Value(
        "exact", exact=lor.values[0] + 1))

    def cert_of(runs, entries=lor.entries):
        return cert.encode(keyed(runs, entries))
    data = lor.data
    d_cont = cert_of((cont, r1, r2))
    d_rel = cert_of((r0, rel, r2))
    d_end = cert_of((end, r1, r2))
    d_rel_end = cert_of((end, rel, r2))
    d_acc = cert_of((r0, r1, r2), (wrong,) + lor.entries[1:])
    d_end_acc = cert_of((end, r1, r2), (wrong,) + lor.entries[1:])
    st = lor.states
    # (both defects, the earlier's name), (the later alone, its name)
    pairs = [
        ((data, OTHER_SALT, P, {"choose": bad_choice}), "choice",
         (data, OTHER_SALT, P, {}), "salt-commitment"),
        ((data, OTHER_SALT, bad_progs, {}), "salt-commitment",
         (data, SALT, bad_progs, {}), "image-digest"),
        ((data, SALT, bad_progs, {"streams": bad_streams}), "image-digest",
         (data, SALT, P, {"streams": bad_streams}), "stream"),
        ((d_cont, SALT, P, {"streams": bad_streams}), "stream",
         (d_cont, SALT, P, {}), "continuity"),
        ((d_cont, SALT, P, {"states": bad_states}), "continuity",
         (data, SALT, P, {"states": bad_states}), "state-hash"),
        ((d_rel, SALT, P, {"states": bad_states}), "state-hash",
         (d_rel, SALT, P, {"states": st}), "aux-image"),
        ((d_rel_end, SALT, P, {"states": end_states}), "aux-image",
         (d_end, SALT, P, {"states": end_states}), "segment-end"),
        ((d_end_acc, SALT, P, {"states": end_states}), "segment-end",
         (d_acc, SALT, P, {"states": st, "choose": QUICK}),
         "accuracy-value"),
    ]
    for (d, salt, progs, kw), first, (d2, salt2, progs2, kw2), later in pairs:
        refused(first, cert.audit, d, salt, progs, **kw)
        refused(later, cert.audit, d2, salt2, progs2, **kw2)


def _entry_block(L, j):
    """The lines of entry j: from its `entry` line to the next entry's or
    `end`."""
    a = find(L, f"entry {j} ")
    b = next(i for i in range(a + 1, len(L))
             if L[i].startswith("entry ") or L[i] == "end")
    return a, b


def test_the_range_limits(lor):
    """64 terms, h-slot 511 and term slot 65,535 read; 65 terms, h-slot
    512 and term slot 65,536 are refused `malformed`."""
    L = lines_of(lor.data)
    a, b = _entry_block(L, 2)                       # a drift entry
    head = L[a:a + 4]
    value = L[b - 1]
    for n, ok in ((64, True), (65, False)):
        M = (L[:a] + head + [f"quantity square-norm terms {n}"]
             + ["term 1/1 s0"] * n + [value] + L[b:])
        if ok:
            cert.parse(rebuilt(M))
        else:
            refused("malformed", cert.parse, rebuilt(M))
    r1 = find(L, "run 1 ")
    for slot, ok in ((511, True), (512, False)):
        M = L[:r1] + [f"run 1 half-step h-slots 1 {slot}"] + L[r1 + 1:]
        if ok:
            cert.parse(rebuilt(M))
        else:
            refused("malformed", cert.parse, rebuilt(M))
    t = find(L, "term 1/1 s0 s0")
    for slot, ok in ((65535, True), (65536, False)):
        M = L[:t] + [f"term 1/1 s0 s{slot}"] + L[t + 1:]
        if ok:
            cert.parse(rebuilt(M))
        else:
            refused("malformed", cert.parse, rebuilt(M))


def test_every_stated_limit_at_both_edges(lor):
    """Each limit the page states, read at its last value (accepted) and
    one past it (refused `malformed`), so a limit moved by one either way
    turns this red: flags 31, STATUS 2^32 - 1, a decimal integer 2^63 -
    1, a term's 8 factors, a name's 64 characters, 512 h-slots. (The
    width rule, the term count, the h-slot and term-slot indices, the
    lanes and the other counts at 1 have tests of their own.)"""
    L = lines_of(lor.data)
    seg = L[find(L, "segment 0 ")].split(" ")
    q = find(L, "quantity ")
    t = find(L, "term 1/1 s0 s0")
    p = find(L, "parameter ensemble-spread")
    r1 = find(L, "run 1 ")
    name64, name65 = "a" + "b" * 63, "a" + "b" * 64
    cases = [
        # (line index, accepted at the edge, refused one past it)
        (find(L, "segment 0 "), " ".join(seg[:7] + ["31"] + seg[8:]),
         " ".join(seg[:7] + ["32"] + seg[8:])),
        (find(L, "segment 0 "), " ".join(seg[:9] + ["4294967295"]),
         " ".join(seg[:9] + ["4294967296"])),
        (find(L, "lanes "), "lanes 9223372036854775807",
         "lanes 9223372036854775808"),
        (t, "term 1/1 " + " ".join(["s0"] * 8),
         "term 1/1 " + " ".join(["s0"] * 9)),
        (q, f"quantity {name64} terms 3", f"quantity {name65} terms 3"),
        (p, f"parameter {name64} 64", f"parameter {name65} 64"),
        (r1, "run 1 half-step h-slots 512 "
         + " ".join(str(i) for i in range(512)),
         "run 1 half-step h-slots 513 "
         + " ".join(str(i) for i in range(513))),
    ]
    for i, ok, bad in cases:
        cert.parse(rebuilt(L[:i] + [ok] + L[i + 1:]))
        e = refused("malformed", cert.parse, rebuilt(L[:i] + [bad]
                                                     + L[i + 1:]))
        assert e.line == i + 1
    # the sampling PRNG's run index is four bytes
    cert.sample(bytes(32), (1 << 32) - 1, 4, 2)
    refused("choice", cert.sample, bytes(32), 1 << 32, 4, 2)


def test_a_counts_own_value_is_read_before_its_lines(lor):
    """A count out of its own range is `malformed`, even where it also
    disagrees with its lines: the value is read before the lines are
    counted (the page's "Counts first")."""
    L = lines_of(lor.data)
    q = find(L, "quantity ")
    r1 = find(L, "run 1 ")
    for i, new in ((find(L, "runs "), "runs 0"),
                   (find(L, "segments "), "segments 0"),
                   (q, "quantity square-norm terms 0"),
                   (q, "quantity square-norm terms 65"),
                   (r1, "run 1 half-step h-slots 0 0 1 2"),
                   (r1, "run 1 half-step h-slots 600 0 1 2")):
        e = refused("malformed", cert.parse, rebuilt(L[:i] + [new]
                                                     + L[i + 1:]))
        assert e.line == i + 1


def test_a_version_of_any_size_is_a_version(lor):
    """The magic line's second token in decimal spelling, whatever its
    size - past 2^63 - 1 too - names a version: `version`, not
    `malformed`."""
    L = lines_of(lor.data)
    for v in ("2", "9223372036854775808", "9" * 5000):
        refused("version", cert.parse, rebuilt([f"cft-certificate {v}"]
                                               + L[1:]))
    for v in ("01", "-1", "1.0", "one"):
        refused("malformed", cert.parse, rebuilt([f"cft-certificate {v}"]
                                                 + L[1:]))


def test_parameter_names_increase_in_byte_order(lor):
    """Names compare as bytes: `a-b` (0x2d) comes before `a0` (0x30)."""
    L = lines_of(lor.data)
    p = find(L, "parameters ")
    rest = L[p + 3:]
    ordered = L[:p] + ["parameters 2", "parameter a-b 1", "parameter a0 2"]
    cert.parse(rebuilt(ordered + rest))
    refused("line-order", cert.parse, rebuilt(
        L[:p] + ["parameters 2", "parameter a0 2", "parameter a-b 1"]
        + rest))
    # and a name twice is a line that should not be there at all, not one
    # out of order (the census found this with no control)
    e = refused("line-unexpected", cert.parse, rebuilt(
        L[:p] + ["parameters 2", "parameter a0 2", "parameter a0 2"]
        + rest))
    assert e.line == p + 3 and "again" in e.message


def test_relations_are_checked_run_by_run(lor):
    """All of run 1's relation checks before any of run 2's: run 1's
    aux-start is reported, though run 2's aux-segments comes earlier in
    the table's order."""
    r0, r1, r2 = lor.runs
    other = hashlib.sha256(b"another start").hexdigest()
    bad1 = dataclasses.replace(r1, chain=(dataclasses.replace(
        r1.chain[0], start=other),) + r1.chain[1:])
    ch = _fake_chain(r2.chain[0].start, S - 1)
    bad2 = dataclasses.replace(r2, chain=ch, output=ch[-1].end)
    e = refused("aux-start", cert.audit, cert.encode(keyed(
        (r0, bad1, bad2), ())), SALT, lor.progs,
        states={0: {0: lor.init}})
    assert e.run == 1


def test_a_runs_relations_are_checked_in_the_tables_order(lor):
    """Within one auxiliary run, step 8's checks in the order of the
    page's table - format, lanes, image, segments, h-slots, bank,
    streams, start. Each adjacent pair, both defects in one run: the
    earlier check's name. And each defect alone is refused by its own,
    so both are live (verifier-C2 found aux-segments-before-aux-image
    green at e484425)."""
    r0, r1, r2 = lor.runs
    P = lor.progs

    def zero_hashes(fmt, n):
        return tuple(cert.stream_hash(SALT, nm, cert.state_bytes(
            fmt, [0] * n)) for nm in "abc")
    one = [dec64("1")] * LANES
    one_hash = cert.stream_hash(SALT, "a", cert.state_bytes("fp64", one))
    only_h = halved("fp64", lor.bank, (0,))
    ch3 = _fake_chain(r1.chain[0].start, 3)
    other = hashlib.sha256(b"another start").hexdigest()
    # each defect of run 1, as a change to the run and what it needs
    # handed: (run fields, programs for run 1, streams)
    D = {
        "aux-format": ({"fmt": "fp128"}, None, None),
        "aux-lanes": ({"lanes": 2, "streams": zero_hashes("fp64", 2)},
                      None, None),
        "aux-image": ({"steps": 50}, None, None),
        "aux-segments": ({"chain": ch3, "output": ch3[-1].end}, None, None),
        "aux-h-slots": ({"h_slots": (0, 1, 9)}, None, None),
        "aux-bank": ({"digest": cert.sha256(lor.img + only_h)},
                     (lor.img, only_h), None),
        "aux-streams": ({"streams": (one_hash,) + r1.streams[1:]}, None,
                        {1: (one, None, None)}),
        "aux-start": ({"chain": (dataclasses.replace(
            r1.chain[0], start=other),) + r1.chain[1:]}, None, None),
    }
    order = list(D)

    def audit_with(names):
        fields, prog1, streams = {}, P[1], None
        for n in names:
            f, p, s = D[n]
            fields.update(f)
            prog1 = p or prog1
            streams = s or streams
        if "aux-format" in names:
            # run 1 at fp128 is run 2's image and bank; the certificate
            # still says half-step
            fields.update(image=r2.image, digest=r2.digest,
                          streams=fields.get("streams", r2.streams))
            prog1 = P[2]
            if "aux-lanes" in names:
                fields["streams"] = zero_hashes("fp128", 2)
        run1 = dataclasses.replace(r1, **fields)
        data = cert.encode(keyed((r0, run1, r2), ()))
        return cert.audit(data, SALT, {0: P[0], 1: prog1, 2: P[2]},
                          states={0: {0: lor.init}}, streams=streams)
    for a, b in zip(order, order[1:]):
        e = refused(a, audit_with, [a, b])
        assert e.run == 1, (a, b)
        refused(b, audit_with, [b])
    refused(order[0], audit_with, [order[0]])


def test_the_readers_key_scan_comes_before_its_mode(lor):
    """Step 5 before step 6: a certificate with a line no key names AND a
    mode no reader knows is `unknown-line`, and so is one with such a
    line that is keyed with no commitment. Each defect alone is its own
    refusal (verifier-C2 found the order green at e484425)."""
    L = lines_of(lor.data)
    extra = L[:12] + ["note this line is not in version 1"] + L[12:]
    refused("unknown-line", cert.parse,
            rebuilt([extra[0], "mode signed"] + extra[2:]))
    refused("mode-unknown", cert.parse, rebuilt([L[0], "mode signed"]
                                                + L[2:]))
    sc = find(extra, "salt-commitment")
    refused("unknown-line", cert.parse, rebuilt(extra[:sc]
                                                + extra[sc + 1:]))
    refused("commitment-missing", cert.parse,
            rebuilt(L[:find(L, "salt-commitment")]
                    + L[find(L, "salt-commitment") + 1:]))


def test_the_readers_steps_in_order(lor):
    """The page's reader order where no other test holds it: the bytes
    (step 3) before the magic line (step 4), and the mode (step 6)
    before the lines that follow it (step 7). Each pair with both
    defects, and each defect alone."""
    L = lines_of(lor.data)
    i = find(L, "lanes ")
    bad_bytes = L[:i] + ["lanes  3"] + L[i + 1:]
    refused("malformed", cert.parse, rebuilt(["cft-certificat 1"]
                                             + bad_bytes[1:]))
    refused("malformed", cert.parse, rebuilt(bad_bytes))
    refused("magic", cert.parse, rebuilt(["cft-certificat 1"] + L[1:]))
    j = find(L, "backend ")
    dropped = L[:j] + L[j + 1:]
    refused("mode-unknown", cert.parse,
            rebuilt([dropped[0], "mode signed"] + dropped[2:]))
    refused("line-missing", cert.parse, rebuilt(dropped))


def test_a_programs_checks_in_order(lor):
    """Step 4 for one run, in the page's order: the image's digest, then
    the program digest, then that the image loads, its format, that it
    is a segment, and last the bank's size. Each adjacent pair that can
    both be wrong at once, with both defects, and each defect alone."""
    r0 = lor.runs[0]
    horner = asm.assemble((PROGRAMS / "horner-bank-fp64.cfta").read_text(
        encoding="utf-8"), "horner")
    hbank = (PROGRAMS / "horner-bank-fp64.exp.bank").read_bytes()
    junk = b"not a program image"

    def run_for(image, bank, fmt="fp64"):
        return dataclasses.replace(r0, image=cert.sha256(image),
                                   digest=cert.sha256(image + bank), fmt=fmt)

    def audit1(run, image, bank):
        return cert.audit(cert.encode(keyed((run,), ())), SALT,
                          {0: (image, bank)})
    # the program digest before the image loads: a junk image certified
    # with one bank and handed with another
    refused("program-digest", audit1, run_for(junk, b"x"), junk, b"y")
    refused("program-image", audit1, run_for(junk, b"x"), junk, b"x")
    refused("program-digest", audit1, run_for(lor.img, lor.bank), lor.img,
            lor.bank_half)
    # the format before the segment's shape: horner (it deposits)
    # certified as fp128
    refused("program-format", audit1, run_for(horner, hbank, "fp128"),
            horner, hbank)
    refused("program-format", audit1, run_for(lor.img, lor.bank, "fp128"),
            lor.img, lor.bank)
    # the shape before the bank's size: horner with a bank one short
    short = hbank[:-8]
    refused("program-shape", audit1, run_for(horner, short), horner, short)
    refused("program-shape", audit1, run_for(horner, hbank), horner, hbank)
    short = lor.bank[:-8]
    refused("program-image", audit1, run_for(lor.img, short), lor.img,
            short)


def test_a_reruns_checks_in_order(lor):
    """Step 9 for one segment: its end state, then its flags, then its
    STATUS."""
    r0 = lor.runs[0]
    bad = list(lor.st[0][1])
    bad[0] ^= 1
    h = cert.state_hash(SALT, cert.state_bytes("fp64", bad))

    def with_seg0(**kw):
        chain = (dataclasses.replace(r0.chain[0], **kw),) + r0.chain[1:]
        if "end" in kw:
            chain = chain[:1] + (dataclasses.replace(
                chain[1], start=kw["end"]),) + chain[2:]
        data = cert.encode(keyed((dataclasses.replace(r0, chain=chain),),
                                 ()))
        return cert.audit(data, SALT, {0: lor.progs[0]},
                          states={0: {0: lor.init}}, choose={0: [0]})
    for kw, name in (({"end": h, "flags": 0}, "segment-end"),
                     ({"end": h}, "segment-end"),
                     ({"flags": 0, "status": 16}, "segment-flags"),
                     ({"flags": 0}, "segment-flags"),
                     ({"status": 16}, "segment-status")):
        e = refused(name, with_seg0, **kw)
        assert (e.run, e.segment) == (0, 0)


def test_an_entrys_checks_in_order(lor):
    """Step 10 for one entry: the run it uses, its lane, its terms'
    slots, then the states it reads."""
    e0, e1, e2, e3 = lor.entries
    far = ((Fraction(1), (0, 3)),)
    for bad, name in (
            (dataclasses.replace(e2, uses=7, lane=LANES), "accuracy-run"),
            # a run that exists, of the wrong kind, before the lane
            (dataclasses.replace(e0, uses=2, lane=LANES), "accuracy-run"),
            (dataclasses.replace(e2, lane=LANES), "accuracy-scope"),
            (dataclasses.replace(e3, lane=LANES, terms=far),
             "accuracy-scope"),
            (dataclasses.replace(e3, terms=far), "accuracy-slot")):
        e = refused(name, cert.audit, _with_entries(lor, [bad]), SALT,
                    lor.progs, states=lor.states, choose=QUICK)
        assert e.entry == 0
    # a term's slot before the states it reads: neither final state was
    # handed or re-run into
    only0 = {r: {0: lor.st[r][0]} for r in range(3)}
    e = refused("accuracy-slot", cert.audit, _with_entries(
        lor, [dataclasses.replace(e3, terms=far)]), SALT, lor.progs,
        states=only0, choose=QUICK)
    e = refused("state-missing", cert.audit, _with_entries(lor, [e3]),
                SALT, lor.progs, states=only0, choose=QUICK)
    assert (e.run, e.segment, e.entry) == (0, S, 0)


def test_states_and_the_chain_are_checked_in_order_of_place(lor):
    """Steps 6 and 7 name the first place in order: run by run, and in a
    run segment by segment (then the output) or boundary by boundary."""
    r0, r1, r2 = lor.runs
    # states: boundary 1 wrong by its hash, boundary 3 by its shape
    states = {r: dict(s) for r, s in lor.states.items()}
    x = list(states[0][1])
    x[0] ^= 1
    states[0][1] = x
    states[0][3] = lor.init[:-1]
    e = refused("state-hash", cert.audit, lor.data, SALT, lor.progs,
                states=states)
    assert (e.run, e.segment) == (0, 1)
    # continuity: segments 1 and 3 both broken; runs 1 and 2 both broken
    ch = list(r0.chain)
    ch[1] = dataclasses.replace(ch[1], start=ch[2].start)
    ch[3] = dataclasses.replace(ch[3], start=ch[0].start)
    e = refused("continuity", cert.audit, with_runs(lor, [
        dataclasses.replace(r0, chain=tuple(ch))]), SALT, {0: lor.progs[0]})
    assert (e.run, e.segment) == (0, 1)
    bad1 = dataclasses.replace(r1, output=r1.chain[0].start)
    bad2 = dataclasses.replace(r2, output=r2.chain[0].start)
    e = refused("continuity", cert.audit, with_runs(lor, [r0, bad1, bad2]),
                SALT, lor.progs)
    assert (e.run, e.segment) == (1, 2 * S - 1)


def test_the_width_rule_reaches_an_enclosures_ends_not_a_rounded_value(lor):
    """An enclosure's finite ends are compared exactly with the value, so
    each is held to the rule: fp256 2^-1100 or 2^1100 as an end is
    `width` at the reader, and 2^-1000 and 2^1000 are not. An infinite
    end is compared by its sign. A rounded value's element is compared by
    its bits, so 2^-1100 is readable there."""
    L = lines_of(lor.data)
    i = find(L, "value enclosed")
    f = FORMATS["fp256"]

    def el(k):
        bits = chars.from_hex(f, f"0x1p{k}", sf.RND_RNE)[0]
        return f"{bits:064x} {cert.exact_decimal(f, bits)}"
    inf = f"{sf.inf_bits(f):064x} inf"
    ninf = f"{sf.inf_bits(f, 1):064x} -inf"
    for lo, hi, name in ((el(-1100), el(1), "width"),
                         (el(-1), el(1100), "width"),
                         (el(-1000), el(1000), None),
                         (ninf, inf, None)):
        data = rebuilt(L[:i] + [f"value enclosed fp256 {lo} {hi}"]
                       + L[i + 1:])
        if name is None:
            cert.parse(data)
        else:
            refused(name, cert.parse, data)
    j = find(L, "value rounded")
    cert.parse(rebuilt(L[:j] + [f"value rounded fp256 rup {el(-1100)}"]
                       + L[j + 1:]))


def test_an_enclosures_line_is_read_in_the_pages_order(lor):
    """The page's order for an enclosure's line (verifier-C2 found it
    open at e484425): each end's hex, NaN and decimal, the lower end
    first; then each finite end against the width rule, the lower first;
    last, whether the lower end is above the upper. A lower end past the
    rule does not decide a line whose upper end is misspelt or has the
    wrong decimal, and it is refused before the ends are compared."""
    L = lines_of(lor.data)
    i = find(L, "value enclosed")
    f = FORMATS["fp256"]

    def el(k):
        bits = chars.from_hex(f, f"0x1p{k}", sf.RND_RNE)[0]
        return f"{bits:064x} {cert.exact_decimal(f, bits)}"
    one_hex, one_dec = el(0).split(" ")
    for lo, hi, name, said in (
            # the upper end's decimal, before the lower end's width
            (el(-1100), f"{one_hex} 2", "decimal", "upper end"),
            # the upper end's hex, before the lower end's width
            (el(-1100), f"{one_hex[1:]} {one_dec}", "malformed",
             "upper end"),
            # both ends past the rule: the lower end first
            (el(-1100), el(1100), "width", "lower end"),
            # the width rule before the comparison of the ends
            (el(1100), el(0), "width", "lower end"),
            (el(1), el(-1100), "width", "upper end")):
        data = rebuilt(L[:i] + [f"value enclosed fp256 {lo} {hi}"]
                       + L[i + 1:])
        e = refused(name, cert.parse, data)
        assert said in e.message, e.message
    # and with both ends in the rule, the comparison refuses
    data = rebuilt(L[:i] + [f"value enclosed fp256 {el(1)} {el(0)}"]
                   + L[i + 1:])
    e = refused("malformed", cert.parse, data)
    assert "above" in e.message


def test_the_tightest_pair_past_the_rule_is_refused_not_widened(lor):
    """An in-rule value whose tightest enclosure has an end past the rule
    (verifier-C2): 1/(3 x 2^900), 902 bits, rounded down into fp256 has
    a 1,139-bit denominator, and 1/(3 x 2^1010) in fp64 likewise. The
    writer refuses `width`, by name, and does not widen the pair."""
    for fmt, q, lo_bits in (("fp256", Fraction(1, 3 << 900), 1139),
                            ("fp64", Fraction(1, 3 << 1010), 1065)):
        assert q.denominator.bit_length() <= 1023
        v = cert.make_value(q, "enclosed", fmt)
        kind, lo = cert.element_fraction(FORMATS[fmt], v.lo)
        assert kind == "finite" and lo.denominator.bit_length() == lo_bits
        e2 = dataclasses.replace(lor.entries[2], value=v)
        refused("width", cert.encode,
                keyed(lor.runs, lor.entries[:2] + (e2,) + lor.entries[3:]))
    assert ("in fp256, has a lower end whose denominator has 1,139 bits"
            in " ".join(_doc().split()))


def test_the_identity_lines_are_held_to_their_spelling_alone(lor):
    """The page: the reader does not hold the number of CAPS words to
    device-version, or the device lines to one another or to backend
    (verifier-C2 measured the four mismatches accepted). Held here so a
    reader that starts to check them changes the page with it."""
    L = lines_of(lor.data)
    for backend, xclbin, version, caps in (
            ("xrt", "a" * 64, "00000a00", "0000000f"),
            ("xrt", "a" * 64, "00000600", "0000000f 00000000"),
            ("xrt", "a" * 64, "none", "0000000f"),
            ("xrt", "a" * 64, "00000a00", "none"),
            ("software", "a" * 64, "unknown", "none")):
        M = list(L)
        for key, val in (("backend", backend), ("device-xclbin", xclbin),
                         ("device-version", version),
                         ("device-caps", caps)):
            M[find(M, key + " ")] = f"{key} {val}"
        c = cert.parse(rebuilt(M))
        assert (c.identity.backend, c.identity.device_version) == (
            backend, version)


def test_every_word_the_page_allows_is_read(lor):
    """The other side of the strict reader: each word the page allows on
    a line reads, and writes back as the same bytes. Each identity word,
    each program format, each rounding direction at each format, and each
    format of an enclosure; the build id's forms, the mode, the methods,
    kinds, run kinds, value forms and scopes are read by the fixture and
    the tests above. A reader that lost one would refuse a certificate
    the page calls valid - found by removing each word from the reader,
    one at a time, in a copy (the round's ledger, P1.md)."""
    L = lines_of(lor.data)

    def reads(prefix, line):
        i = find(L, prefix)
        data = rebuilt(L[:i] + [line] + L[i + 1:])
        assert cert.encode(cert.parse(data)) == data, line
    for key, words in (
            ("backend", ("software", "xrt", "remote", "unknown")),
            ("device-xclbin", ("none", "unknown", "0123abcd" * 8)),
            ("device-version", ("none", "unknown", "00000a00")),
            ("device-caps", ("none", "unknown", "0000000f",
                             "0000000f 00000001")),
            ("device-tiles", ("unknown", "1", "4"))):
        for w in words:
            reads(key + " ", f"{key} {w}")
    for fmt in cert.LADDER:
        reads("program-format ", f"program-format {fmt}")
        one = chars.from_decimal(FORMATS[fmt], "1", sf.RND_RNE)[0]
        for rnd in ("rne", "rtz", "rdn", "rup", "rmm"):
            reads("value rounded", cert._value_text(cert.Value(
                "rounded", fmt=fmt, rnd=rnd, bits=one)))
        reads("value enclosed", cert._value_text(cert.Value(
            "enclosed", fmt=fmt, lo=one, hi=one)))
    assert cert.LADDER == ("fp32", "fp64", "fp128", "fp256")


def test_bytes_that_are_not_whole_elements_are_refused_by_name(lor):
    whole = cert.state_bytes("fp64", lor.init)
    assert len(whole) == 72
    e = refused("state-shape", cert.audit, lor.data, SALT, lor.progs,
                states={0: {0: whole[:-1]}})
    assert "71 bytes" in e.message
    # located in its fields, not only in its message (verifier-C2)
    assert (e.run, e.segment, e.entry) == (0, 0, None)
    e = refused("stream", cert.audit, lor.data, SALT, lor.progs,
                streams={0: (bytes(23), None, None)})
    assert "23 bytes" in e.message
    assert (e.run, e.segment, e.entry) == (0, None, None)
    # whole elements, handed as bytes, are read as the values they are
    states = {r: dict(s) for r, s in lor.states.items()}
    states[0][0] = whole
    cert.audit(lor.data, SALT, lor.progs, states=states, choose=QUICK)


def test_the_writer_refuses_an_empty_or_ragged_run(lor):
    refused("malformed", cert.certify_run, "main", lor.img, lor.bank, SALT,
            [lor.init], [], steps=100)
    refused("state-shape", cert.certify_run, "main", lor.img, lor.bank, SALT,
            [lor.init] * 2, [(16, 0)] * 2, steps=100)


def test_the_writer_refuses_what_the_executor_would(lor):
    """run_chain and certify_run refuse by name what seq.run would not
    run as a segment: a bank handed to an image that carries its own
    constants, a start that is not whole lanes, a stream of the wrong
    length. And the audit's step 4 refuses the first, for a run
    certified with a bank its image cannot take (certify_run hashes what
    it is handed; it does not load the bank)."""
    k64 = sf.div(F64, dec64("1"), dec64("3"))[0]
    img = asm.assemble(SELF_K.format(fmt="fp64", k=k64, w=16, strict="",
                                     n=1, extra=""), "k-fp64")
    junk = bytes(8)
    e = refused("program-image", cert.run_chain, img, junk, [dec64("1")], 1)
    assert "must be empty" in e.message
    st, rs = cert.run_chain(img, b"", [dec64("1")], 2)
    r0 = cert.certify_run("main", img, junk, SALT, st, rs, steps=1)
    e = refused("program-image", cert.audit, cert.encode(keyed((r0,), ())),
                SALT, {0: (img, junk)})
    assert "must be empty" in e.message and e.run == 0
    e = refused("state-shape", cert.run_chain, lor.img, lor.bank,
                lor.init[:-1], 1)
    assert "whole number of lanes" in e.message
    short = ([0] * 2, None, None)
    for fn, a in ((cert.run_chain, (lor.img, lor.bank, lor.init, 1)),
                  (cert.certify_run, ("main", lor.img, lor.bank, SALT,
                                      lor.st[0], lor.rs[0]))):
        kw = {"streams": short}
        if fn is cert.certify_run:
            kw["steps"] = 100
        e = refused("stream", fn, *a, **kw)
        assert "holds 2 values" in e.message


def test_the_writer_refuses_a_field_it_cannot_spell_by_name(lor):
    """A certificate object whose field is of the wrong type - device_caps
    a bare string, device_tiles or a count a string - or of a shape the
    writer cannot spell is refused `malformed`, naming the field, where
    P1b's writer raised AssertionError (verifier-C2; c6d92ac refused the
    bare string `malformed`)."""
    c = lor.cert
    idn = c.identity
    r0 = lor.runs[0]
    for bad, field in (
            (dataclasses.replace(c, identity=dataclasses.replace(
                idn, device_caps="0000000f")), "identity.device_caps"),
            (dataclasses.replace(c, identity=dataclasses.replace(
                idn, device_caps="0000000f 00000000")),
             "identity.device_caps"),
            (dataclasses.replace(c, identity=dataclasses.replace(
                idn, device_tiles="1")), "identity.device_tiles"),
            (dataclasses.replace(c, runs=(dataclasses.replace(
                r0, lanes="3"),) + c.runs[1:]), "runs[0].lanes"),
            (dataclasses.replace(c, runs=(dataclasses.replace(
                r0, chain=(dataclasses.replace(r0.chain[0], flags="16"),)
                + r0.chain[1:]),) + c.runs[1:]),
             "runs[0].chain[0].flags")):
        e = refused("malformed", cert.encode, bad)
        assert field in e.message, e.message
    # shapes the writer cannot spell at all
    for bad in (dataclasses.replace(c, runs=(dataclasses.replace(
                    r0, streams=r0.streams[:2]),) + c.runs[1:]),
                dataclasses.replace(c, identity=None),
                dataclasses.replace(c, accuracy=(None,))):
        e = refused("malformed", cert.encode, bad)
        assert "cannot spell" in e.message, e.message
    # the right types are what they always were
    ok = dataclasses.replace(c, identity=dataclasses.replace(
        idn, device_caps=["0000000f"]))
    assert cert.parse(cert.encode(ok)).identity.device_caps == ("0000000f",)


def test_the_audits_arguments_are_held_to_their_shape_by_name(lor):
    """Each argument of audit() in a shape it does not take is refused by
    the name of the step that reads it - programs `program-image`,
    streams `stream`, states `state-shape`, the choice and the seed
    `choice` - with its location in the refusal's fields, where P1b's
    audit crashed (IndexError, TypeError, AttributeError) or ignored
    the argument (a stream or a program for a run that does not
    exist)."""
    d, P, st = lor.data, lor.progs, lor.states
    img, bank = P[0]
    cases = [
        # (name, (run, segment), keyword arguments to audit)
        ("program-image", (None, None), {"programs": [P[0]]}),
        ("program-image", (None, None), {"programs": {**P, 3: P[0]}}),
        ("program-image", (None, None), {"programs": {**P, "0": P[0]}}),
        ("program-image", (0, None), {"programs": {**P, 0: img}}),
        ("program-image", (0, None), {"programs": {**P, 0: (img, bank,
                                                           bank)}}),
        ("program-image", (0, None), {"programs": {**P, 0: (list(img),
                                                           bank)}}),
        ("program-image", (0, None), {"programs": {**P, 0: (img,
                                                           list(bank))}}),
        # two items, but not a pair
        ("program-image", (0, None), {"programs": {**P, 0: {0: img,
                                                           1: bank}}}),
        ("stream", (None, None), {"streams": [None]}),
        ("stream", (None, None), {"streams": {3: None}}),
        ("stream", (None, None), {"streams": {"0": None}}),
        ("stream", (0, None), {"streams": {0: ([0] * LANES, [0] * LANES)}}),
        ("stream", (0, None), {"streams": {0: 5}}),
        ("stream", (0, None), {"streams": {0: (5, None, None)}}),
        ("stream", (0, None), {"streams": {0: (["0"] * LANES, None,
                                               None)}}),
        ("state-shape", (None, None), {"states": [st[0]]}),
        ("state-shape", (None, None), {"states": {**st, "1": st[1]}}),
        # True is not run 1, though a dict would merge the two keys
        ("state-shape", (None, None), {"states": {True: st[1]}}),
        ("state-shape", (0, None), {"states": {**st, 0: [lor.init]}}),
        ("state-shape", (0, None), {"states": {**st, 0: {**st[0],
                                                         "1": lor.init}}}),
        ("state-shape", (0, 0), {"states": {**st, 0: {**st[0],
                                                      0: 1.5}}}),
        ("choice", (None, None), {"choose": [0]}),
        ("choice", (None, None), {"choose": {"0": "all"}}),
        ("choice", (0, None), {"choose": {0: ("sample", "1")},
                               "seed": bytes(32)}),
        ("choice", (0, None), {"choose": {0: ("sample", 1.0)},
                               "seed": bytes(32)}),
        ("choice", (0, None), {"choose": {0: ("sample", True)},
                               "seed": bytes(32)}),
        ("choice", (0, None), {"choose": {0: ["1"]}}),
        ("choice", (None, None), {"seed": "0" * 64}),
        # 32 of something that is not bytes is not a seed
        ("choice", (None, None), {"seed": "0" * 32}),
        ("choice", (None, None), {"seed": list(bytes(32))}),
    ]
    for name, where, kw in cases:
        kw = dict(kw)
        progs = kw.pop("programs", P)
        kw.setdefault("states", st)
        e = refused(name, cert.audit, d, SALT, progs, **kw)
        assert (e.run, e.segment) == where, (kw, e.message)
    # integers, the right number of them, that are not an element's bits:
    # found as that, where a value past the format would otherwise reach
    # the hash as bytes it cannot be
    e = refused("stream", cert.audit, d, SALT, P, states=st,
                streams={0: ([1 << 64] * LANES, None, None)})
    assert e.run == 0 and "not the bits of a fp64 element" in e.message
    e = refused("state-shape", cert.audit, d, SALT, P,
                states={**st, 0: {**st[0], 0: [1 << 64] * len(lor.init)}})
    assert (e.run, e.segment) == (0, 0) and "not the bits" in e.message
    # a run's states in a list are found as that, before the list's items
    # would be read as boundaries and refused by the same name (the
    # census found the first check masked by the second)
    e = refused("state-shape", cert.audit, d, SALT, P,
                states={**st, 0: [lor.init]})
    assert "a mapping from boundary to state" in e.message, e.message
    # and the page says which name each argument gets
    doc = " ".join(_doc().split())
    for arg, name in (("programs", "program-image"), ("streams", "stream"),
                      ("states", "state-shape"), ("choose", "choice"),
                      ("seed", "choice")):
        assert re.search(rf"- `{arg}`: [^;]*;[^;]* refused `{name}`;",
                         doc), (arg, name)


def test_a_seed_handed_is_a_seed_whatever_is_asked(lor):
    """The page lists a 32-byte seed among the auditor's choice: held
    whether or not the audit samples."""
    for bad in (bytes(31), bytes(33), "seed"):
        refused("choice", cert.audit, lor.data, SALT, lor.progs,
                states=lor.states, seed=bad)


# ---- the specification, held to the code ------------------------------------

def _doc():
    return DOC.read_text(encoding="utf-8")


def _fenced_after(marker):
    text = _doc()
    at = text.index(marker)
    m = re.search(r"```[a-z]*\n(.*?)```", text[at:], re.S)
    return m.group(1)


def example_certificate():
    """The specification's example, from its recipe: Henon-Heiles at
    fp64 with its classic bank, two lanes of programs/check.py's
    ensemble over two segments, a half-step run beside it (H, H2 and MH
    halved, four segments), the energy's drift for lane 1 and the
    step-halving estimate over both lanes, rounded upward to fp64."""
    src = (PROGRAMS / "henonheiles-lf-fp64.cfta").read_text(encoding="utf-8")
    img = asm.assemble(src, "henonheiles-lf-fp64")
    bank = (PROGRAMS / "henonheiles-lf-fp64.classic.bank").read_bytes()
    half = halved("fp64", bank, (0, 1, 2))
    init = []
    for i in range(2):
        init += [dec64("0"), dec64(repr(0.1 + i / 1024)), dec64("0.5"),
                 dec64("0")]
    st0, rs0 = cert.run_chain(img, bank, init, 2)
    st1, rs1 = cert.run_chain(img, half, init, 4)
    r0 = cert.certify_run("main", img, bank, SALT, st0, rs0, steps=100)
    r1 = cert.certify_run("half-step", img, half, SALT, st1, rs1, steps=100,
                          h_slots=(0, 1, 2))
    runs = (r0, r1)
    shapes = [(F64, 4), (F64, 4)]
    ends = {(0, 0): st0[0], (0, 2): st0[-1], (1, 0): st1[0],
            (1, 4): st1[-1]}
    e0, q0 = entry_with("drift", "measurement", 0, 1, runs, shapes, ends,
                        "exact", label="energy", terms=ENERGY)
    # lane 1's drift keeps the 3 of y^3/3 in its denominator (lane 0's
    # happens to cancel it over these two segments)
    assert q0.denominator % 3 == 0
    e1, _ = entry_with("step-halving", "estimate", 1, None, runs, shapes,
                       ends, "rounded", "fp64", "rup")
    data = cert.encode(keyed(runs, (e0, e1)))
    return data, {0: (img, bank), 1: (img, half)}, {0: {0: init},
                                                     1: {0: init}}


def test_the_specifications_example_is_what_the_writer_writes():
    data, progs, states = example_certificate()
    shown = _fenced_after("<!-- the example certificate -->")
    assert shown.encode("ascii") == data, (
        "docs/CERTIFICATES.md's example is not what cert.py writes for its "
        "recipe; regenerate it from test_cert.example_certificate()")
    v = cert.audit(data, SALT, progs, states=states)
    # the prose's reading of the example's drift, held to its value
    # (verifier-C2 found it said 2^159 where the value is 3 x 2^163)
    m = re.search(r"Its denominator is 3 x 2\^(\d+)", _doc())
    assert m, "the page no longer states the example drift's denominator"
    drift_q = v.accuracy[0]
    assert drift_q.denominator == 3 << int(m.group(1)), (
        f"the page says 3 x 2^{m.group(1)}; the example's drift has "
        f"denominator {drift_q.denominator:#x}")


def test_the_specifications_test_vectors():
    rows = dict(ln.split(None, 1) for ln in _fenced_after(
        "<!-- the test vectors -->").strip().split("\n"))
    assert len(rows) == 12
    salt = bytes.fromhex(rows["salt"])
    assert salt == SALT
    assert rows["salt-commitment"] == cert.salt_commitment(salt) == rfc2104(
        salt, b"cft-certificate 1 salt")
    state = bytes.fromhex(rows["state-bytes"])
    assert state == cert.state_bytes("fp64", [dec64("1"), dec64("-0.5")])
    assert rows["state-hash"] == cert.state_hash(salt, state) == rfc2104(
        salt, b"cft-certificate 1 state\x00" + state)
    assert rows["open-state-hash"] == cert.state_hash(None, state) \
        == hashlib.sha256(b"cft-certificate 1 state\x00" + state).hexdigest()
    stream = bytes.fromhex(rows["stream-a-bytes"])
    assert rows["stream-a-hash"] == cert.stream_hash(salt, "a", stream)
    seed = bytes.fromhex(rows["sample-seed"])
    run, of, k = (int(rows[x]) for x in ("sample-run", "sample-of",
                                         "sample-k"))
    got = [int(x) for x in rows["sample"].split(" ")]
    assert got == cert.sample(seed, run, of, k) == spec_sample(seed, run,
                                                               of, k)


def test_the_specifications_refusal_table():
    rows = re.findall(r"(?m)^\| `([a-z-]+)` \| (\d+) \|", _doc())
    assert dict((n, int(c)) for n, c in rows) == cert.REFUSALS
    assert len(rows) == len(cert.REFUSALS)
