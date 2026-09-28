# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""Certificates, version 1 (docs/CERTIFICATES.md): the golden gate.

Every mechanism of python/cft_golden/cert.py has a negative control
here, and each control asserts the NAME of the check it exists for -
never merely that something refused. Every control but the byte flip
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
    assert L[find(L, "build-commit")] == "build-commit unknown"


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
        ("build-commit ", "build-commit " + "a" * 39),
        ("build-tree ", "build-tree unclean"),
        ("backend ", "backend fpga"),
        ("device-caps ", "device-caps 0000000f"),
        ("device-caps ", "device-caps 0000000F 00000000"),
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
        ("value exact", f"value exact {2 * num:x}/{2 * den:x}"),
        ("value rounded", " ".join(rnd[:4] + [rnd[4].upper()] + rnd[5:])),
        ("value rounded", " ".join(rnd[:4] + [rnd[4][1:]] + rnd[5:])),
        ("value rounded", " ".join(rnd[:3] + ["rnd"] + rnd[4:])),
        ("value rounded", " ".join(rnd[:4] + ["7ff8000000000000", "nan"])),
        ("value enclosed", " ".join(enc[:3] + enc[5:7] + enc[3:5])),
        ("scope lane", "scope lane 00"), ("scope lane", "scope lanes 0"),
        ("quantity ", "quantity Square terms 3"),
        ("entry 0 ", "entry 0 extrapolation"),
        ("kind ", "kind guess"),
        ("parameter ", "parameter Spread 64"),
        ("run 0 ", "run 0 wider"),
        ("run 1 ", "run 1 main"),
        ("run 1 ", "run 1 half-step h-slots 3 0 2 1"),
        ("run 1 ", "run 1 half-step h-slots 0"),
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
        e = refused("malformed", cert.parse, rebuilt(M))
        assert e.line == i + 1, (new[:60], e.message)
    # and bytes a line may not hold
    i = find(L, "lanes ")
    for bad in ("lanes  3", "lanes 3 ", " lanes 3", "lanes\t3", "lanes 3\r"):
        e = refused("malformed", cert.parse,
                    rebuilt(L[:i] + [bad] + L[i + 1:]))
        assert e.line == i + 1
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
    refused("width", cert.make_value, Fraction(1, 1 << 1023))
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
    for bad in (SALT[:31], SALT + b"\x00", bytes(64), "salt"):
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
    # a run whose certificate says fp128 while the image it names is fp64
    r0 = dataclasses.replace(lor.runs[0], fmt="fp128")
    data = with_runs(lor, [r0])
    refused("program-format", cert.audit, data, SALT, lor.progs)


def test_a_stream_that_is_not_the_one_certified(lor):
    one = [dec64("1")] * LANES
    refused("stream", cert.audit, lor.data, SALT, lor.progs,
            streams={0: (one, None, None)})
    refused("stream", cert.audit, lor.data, SALT, lor.progs,
            streams={0: ([0] * 2, None, None)})


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
        dataclasses.replace(r0, chain=tuple(chain))]), SALT, lor.progs)
    assert (e.run, e.segment) == (0, 2)
    e = refused("continuity", cert.audit, with_runs(lor, [
        dataclasses.replace(r0, output=chain[0].start)]), SALT, lor.progs)
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
    e = refused("segment-end", cert.audit, data, SALT, lor.progs,
                states=states)
    assert (e.run, e.segment) == (0, S - 1)
    assert f"run 0 segment {S - 1}" in e.message


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
        refused(name, cert.audit, _with_entries(lor, [bad]), SALT,
                lor.progs, states=lor.states, choose=QUICK)
    # the final state an entry needs, neither handed nor re-run into
    e = refused("state-missing", cert.audit, lor.data, SALT, lor.progs,
                states={r: {0: lor.st[r][0]} for r in range(3)},
                choose=QUICK)
    assert (e.run, e.segment) == (0, S)


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
                (bytes(32), 0, 4, 5)):
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
                {0: [1, 1]}, {0: []}, {3: "all"}, {0: "most"}):
        refused("choice", cert.audit, lor.data, SALT, lor.progs,
                states=lor.states, choose=bad, seed=seed)


# ---- identity ---------------------------------------------------------------

def test_identity_is_reported_never_checked(lor):
    """An unknown field is reported as unknown; a stated one as stated,
    not checked - and an audit passes whatever the producer says it ran
    on, because the bits are the same on every conforming build."""
    rows = cert.identity_report(lor.cert)
    assert "build-commit: unknown - the producer did not record it" in rows
    assert "backend: software - stated, not checked" in rows
    said = cert.Identity("0123456789abcdef0123456789abcdef01234567", "dirty",
                         "present", "xrt", "ab" * 32, "00000a00",
                         ("0000f0ff", "000007ff"), 2)
    data = cert.encode(dataclasses.replace(lor.cert, identity=said))
    v = cert.audit(data, SALT, lor.progs, states=lor.states, choose=QUICK)
    text = "\n".join(v.lines())
    assert "device-caps: 0000f0ff 000007ff - stated, not checked" in text
    assert "unknown" not in text


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
    cert.audit(data, SALT, progs, states=states)


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
