# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""Certificates, version 2 (docs/CERTIFICATES.md, "Version 2"): the golden
gate, beside test_cert.py, which is version 1's.

Every mechanism of python/cft_golden/cert2.py has a negative control here,
and each control asserts the NAME of the check it exists for, never merely
that something refused. Every control but the byte flip writes a valid hash
line over its defective body (cert.rehash), so that it reaches the check it
is for. The fixtures:

  mk    certificates/programs/markstep-fp64.cfta, defined by its source
        markstep-fp64.cftl: three lanes, three segments of four steps;
        segment 1 marks lanes 0 and 1, the first wrongly, and the golden
        writer replays both by the definition (`replay 1 marked 2 changed
        1`). Open, and keyed (mk_keyed).
  lz    Lorenz-63 compiled from programs/systems/lorenz63-rk4-fp64.cftl
        by cftc with rho = 29: a main run, a half-step run (the recompile's
        h-slots), a wider-source run (the source at fp128) and version 1's
        wider run (the fp64 compile one rung up), with an estimate on each.
  fl    flagstep (certificates/programs) with lane flags and a drift.
  full  every header line spelled out, its initial state made by the
        `shake-box` generator, signed under the published test key, and
        superseding fl.
  rb    Lorenz-63 compiled, its initial state generated: an audit that
        rebuilds it from the source and the generator alone.

The C auditor reads version 2 from the next parcel on: until then
host/tests/audit_check.py does not hand it these calls (it shadows
test_cert.py alone).
"""

import dataclasses
import hashlib
import os
import re
import subprocess
import sys
import types
from fractions import Fraction
from pathlib import Path

import pytest

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parents[1]))
ROOT = HERE.parents[2]
CERTS = ROOT / "certificates"
PROGRAMS = ROOT / "programs"

import cftc  # noqa: E402
from cft_golden import FORMATS, asm, cert, cert2, chars, ed25519  # noqa: E402
from cft_golden import seq, transcend  # noqa: E402
from cft_golden import softfloat as sf  # noqa: E402

F64, F128 = FORMATS["fp64"], FORMATS["fp128"]

# The page's example salt, and the published test key: each is printed on
# docs/CERTIFICATES.md, so neither is ever an owner's.
SALT = bytes(range(32))
TEST_SEED = bytes(range(32, 64))
TEST_KEY = ed25519.public_key(TEST_SEED).hex()
# the issuer the test key is bound to in a keyring: evidently a test, since
# anyone holding the published seed can sign as it (verifier-VCV2B's note)
TEST_ISSUER = "cft test issuer (published key)"
# RFC 8032 section 7.1 TEST 1's public key: a key that is not the test key
RFC_TEST_1_KEY = ("d75a980182b10ab7d54bfed3c964073a"
                  "0ee172f3daa62325af021a68f707511a")
# the identity, a key of small order (test_ed25519.py's SMALL_ORDER has all
# eight), and verifier-VCV2B's signature that verifies under it for every
# message: R = [1234567]B, S = 1234567
SMALL_KEY = "01" + "00" * 31
SMALL_SIG = (ed25519.encode_point(ed25519._mul(1234567, ed25519.B))
             + (1234567).to_bytes(32, "little")).hex()
IDN = cert.Identity(backend="software", device_xclbin="none",
                    device_version="none", device_caps="none", device_tiles=1)
CFTC = ("cftc", cftc.VERSION)
# a text of three UTF-8 lengths: L with a stroke, o acute, d, z acute
LODZ = chr(0x141) + chr(0xF3) + "d" + chr(0x17A)


def prov(**kw):
    base = dict(profile="2", language="1", device_platform="none",
                device_xrt="none", device_clock="none", device_serial="none",
                writer=("golden", "unknown"), writer_runtime="python-3.12.9",
                compiler_build="unknown", host_os="windows",
                host_arch="x86_64", started="2026-10-02T12:00:00Z",
                finished="2026-10-02T12:00:05Z",
                issued="2026-10-02T12:00:06Z")
    base.update(kw)
    return cert2.Provenance(**base)


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


def edit(data, prefix, new, nth=0):
    L = lines_of(data)
    L[find(L, prefix, nth)] = new
    return rebuilt(L)


def tok(line, i):
    return line.split(" ")[i]


def d64(text):
    return chars.from_decimal(F64, text, sf.RND_RNE)[0]


def reencode(data, **changes):
    """The certificate read, its provenance changed, written again."""
    c = cert.parse(data)
    return cert2.encode(dataclasses.replace(
        c, provenance=dataclasses.replace(c.provenance, **changes)))


# ---- markstep -----------------------------------------------------------------

MARK_SRC = CERTS / "programs" / "markstep-fp64.cftl"
MARK_ASM = CERTS / "programs" / "markstep-fp64.cfta"
MARK_INIT = ("0", "0.3333", "100", "0.5", "50", "0.2")


def markstep_bank(graph, b=None, zero=0):
    """markstep's bank: the source's a and b rounded once, 1, 7, 106, and
    the raw words 1, 0x81 (the mark with invalid) and `zero`."""
    pa = {p[0]: p[2] for p in graph.param}
    return cert.state_bytes("fp64", [pa["a"], pa["b"] if b is None else b,
                                     d64("1"), d64("7"), d64("106"), 1, 0x81,
                                     zero])


def make_markstep(salt=None, bank=None, segments=3, provenance=None,
                  lane_flags=None):
    src = MARK_SRC.read_bytes()
    g = cert2.source_graph(src)
    img = asm.assemble(MARK_ASM.read_text(encoding="utf-8"), "markstep-fp64")
    bank = markstep_bank(g) if bank is None else bank
    init = [d64(t) for t in MARK_INIT]
    ch = cert2.run_chain(img, bank, init, segments, steps=4,
                         definition=cert2.Definition(g),
                         lane_flags=lane_flags)
    run = cert2.certify_run("main", img, bank, salt, ch, steps=4,
                            source=cert2.source_lines(
                                src, "fp64", name="markstep-fp64.cftl"))
    p = provenance or prov(replay_methods=((0, "golden"),) if ch.raws
                           else ())
    c = cert2.Certificate("keyed" if salt else "open",
                          cert.salt_commitment(salt) if salt else None, IDN,
                          p, (run,), ())
    return types.SimpleNamespace(src=src, graph=g, img=img, bank=bank,
                                 init=init, chain=ch, run=run, cert=c,
                                 data=cert2.encode(c), salt=salt)


@pytest.fixture(scope="module")
def mk():
    return make_markstep()


@pytest.fixture(scope="module")
def mk_keyed():
    return make_markstep(salt=SALT)


def audit_mk(x, data=None, **kw):
    kw.setdefault("states", {0: {0: x.init}})
    kw.setdefault("sources", {0: x.src})
    return cert.audit(x.data if data is None else data, x.salt,
                      {0: (x.img, x.bank)}, **kw)


# ---- Lorenz-63, compiled from its source ----------------------------------

LZ_SRC = PROGRAMS / "systems" / "lorenz63-rk4-fp64.cftl"
LZ_PARAMS = {"rho": "29"}
LZ_S = 2


def lorenz_init(lanes=3):
    init = []
    for i in range(lanes):
        init += [d64(repr(1 + i / 64)), d64("1"), d64("1")]
    return init


def widened(fmt, data):
    up = cert.LADDER[cert.LADDER.index(fmt) + 1]
    return cert.state_bytes(up, [cert.widen(fmt, x)
                                 for x in cert.state_values(fmt, data)])


@pytest.fixture(scope="module")
def lz():
    src = LZ_SRC.read_bytes()
    c64 = cert2.compile_source(src, "fp64", 100, "sw", LZ_PARAMS)
    c128 = cert2.compile_source(src, "fp128", 100, "sw", LZ_PARAMS)
    init = lorenz_init()
    init_w = [cert.widen("fp64", x) for x in init]
    h_slots = tuple(c64.manifest["h_slots"])
    lines64 = cert2.source_lines(src, "fp64", name="lorenz63-rk4-fp64.cftl",
                                 params=LZ_PARAMS, compiler=CFTC + ("sw",))
    lines128 = cert2.source_lines(src, "fp128",
                                  name="lorenz63-rk4-fp64.cftl",
                                  params=LZ_PARAMS, compiler=CFTC + ("sw",))
    img_w = asm.assemble(re.sub(r"(?m)^\.format\s+fp64", ".format   fp128",
                                c64.cfta), "lorenz63-wider")
    bank_w = widened("fp64", c64.bank)
    ch = [cert2.run_chain(c64.image, c64.bank, init, LZ_S),
          cert2.run_chain(c64.image, c64.half_bank, init, 2 * LZ_S),
          cert2.run_chain(c128.image, c128.bank, init_w, LZ_S),
          cert2.run_chain(img_w, bank_w, init_w, LZ_S)]
    runs = (cert2.certify_run("main", c64.image, c64.bank, None, ch[0],
                              steps=100, source=lines64,
                              parameters=(("members", 3),)),
            cert2.certify_run("half-step", c64.image, c64.half_bank, None,
                              ch[1], steps=100, source=lines64,
                              h_slots=h_slots),
            cert2.certify_run("wider-source", c128.image, c128.bank, None,
                              ch[2], steps=100, source=lines128),
            cert2.certify_run("wider", img_w, bank_w, None, ch[3],
                              steps=100, main_image=c64.image))
    shapes = [(F64, 3), (F64, 3), (F128, 3), (F128, 3)]
    ends = {}
    for r, c in enumerate(ch):
        ends[(r, 0)] = c.states[0]
        ends[(r, len(c.states) - 1)] = c.states[-1]
    entries = []
    for method, uses, lane, form, fmt, rnd in (
            ("wider-source", 2, None, "enclosed", "fp64", None),
            ("wider", 3, 0, "rounded", "fp64", "rup"),
            ("step-halving", 1, None, "exact", None, None)):
        probe = cert.Entry(method, cert2.METHOD_KIND[method], uses, lane,
                           cert.Value("exact", exact=Fraction(0)))
        q = cert.derive(probe, runs, shapes, ends,
                        method_run=cert2.METHOD_RUN)
        entries.append(dataclasses.replace(
            probe, value=cert.make_value(q, form, fmt, rnd)))
    c = cert2.Certificate("open", None, IDN, prov(), runs, tuple(entries))
    progs = {0: (c64.image, c64.bank), 1: (c64.image, c64.half_bank),
             2: (c128.image, c128.bank), 3: (img_w, bank_w)}
    states = {0: {0: init}, 1: {0: init}, 2: {0: init_w}, 3: {0: init_w}}
    return types.SimpleNamespace(src=src, c64=c64, c128=c128, init=init,
                                 init_w=init_w, h_slots=h_slots,
                                 lines64=lines64, lines128=lines128,
                                 img_w=img_w, bank_w=bank_w, chains=ch,
                                 runs=runs, entries=tuple(entries), cert=c,
                                 data=cert2.encode(c), progs=progs,
                                 states=states, shapes=shapes)


def audit_lz(x, data=None, **kw):
    kw.setdefault("states", x.states)
    kw.setdefault("sources", {0: x.src, 1: x.src, 2: x.src})
    progs = kw.pop("progs", x.progs)
    return cert.audit(x.data if data is None else data, None, progs, **kw)


def with_runs(x, runs, accuracy=None):
    c = dataclasses.replace(x.cert, runs=tuple(runs),
                            accuracy=x.cert.accuracy if accuracy is None
                            else tuple(accuracy))
    return cert2.encode(c)


# ---- flagstep with lane flags ------------------------------------------------

def flagstep_image():
    return asm.assemble((CERTS / "programs" / "flagstep-fp64.cfta")
                        .read_text(encoding="utf-8"), "flagstep-fp64")


@pytest.fixture(scope="module")
def fl():
    img = flagstep_image()
    init = [d64(t) for t in ("3", "1", "3", "5")]
    ch = cert2.run_chain(img, b"", init, 5, lane_flags=True)
    run = cert2.certify_run("main", img, b"", None, ch, steps=1)
    probe = cert.Entry("drift", "measurement", 0, None,
                       cert.Value("exact", exact=Fraction(0)), "counter",
                       ((Fraction(1), (0,)),))
    q = cert.derive(probe, (run,), [(F64, 2)],
                    {(0, 0): ch.states[0], (0, 5): ch.states[-1]})
    e = dataclasses.replace(probe, value=cert.make_value(q))
    c = cert2.Certificate("open", None, IDN, prov(language="none"), (run,),
                          (e,))
    return types.SimpleNamespace(img=img, init=init, chain=ch, run=run,
                                 cert=c, data=cert2.encode(c))


def audit_fl(x, data=None, **kw):
    kw.setdefault("states", {0: {0: x.init}})
    return cert.audit(x.data if data is None else data, None,
                      {0: (x.img, None)}, **kw)


# ---- every header line spelled out, signed --------------------------------------

FULL_BOX = ("full case", "2", "4", "-1", "1")


@pytest.fixture(scope="module")
def full(fl):
    img = flagstep_image()
    init = cert2.generate_initial(("generator", "shake-box", FULL_BOX),
                                  "fp64", 2, 2)
    ch = cert2.run_chain(img, b"", init, 3, lane_flags=True)
    run = cert2.certify_run("main", img, b"", SALT, ch, steps=1)
    p = cert2.Provenance(
        profile="2", language="none",
        device_platform="xilinx_u50_gen3x16_xdma_5_202210_1",
        device_xrt="2.19.194", device_clock=135000000,
        device_serial="SN 0001 (a test)",
        writer=("golden", "commit=" + "a" * 40 +
                " tracked=clean untracked=none"),
        writer_runtime="python-3.12.9,mpmath-1.3.0",
        compiler_build="commit=" + "b" * 40 +
                       " tracked=modified untracked=present",
        certificate_id="cert 0001 / " + LODZ,
        issuer=TEST_ISSUER, issuer_key=TEST_KEY, host_os="linux-6.8.0",
        host_arch="x86_64", started="2026-10-02T12:00:00Z",
        finished="2026-10-02T12:00:05Z", issued="2026-10-02T12:00:06Z",
        supersedes=cert2.body_hash_of(fl.data),
        environment=(("CFT_TIMEOUT_MS", "60000"),
                     ("XCL_EMULATION_MODE", "hw_emu")),
        initial=("generator", "shake-box", FULL_BOX))
    c = cert2.Certificate("keyed", cert.salt_commitment(SALT), IDN, p,
                          (run,), ())
    data = cert2.encode(c)
    return types.SimpleNamespace(img=img, init=init, chain=ch, cert=c,
                                 data=data,
                                 sig=cert2.signature_file(TEST_SEED, data),
                                 ring=(f"key {TEST_KEY} "
                                       f"{cert2.text_token(TEST_ISSUER)}\n")
                                 .encode("ascii"))


def audit_full(x, data=None, **kw):
    kw.setdefault("states", {0: {0: x.init}})
    return cert.audit(x.data if data is None else data, SALT,
                      {0: (x.img, None)}, **kw)


# ---- the round trip, and every key ----------------------------------------------

def test_the_round_trip(mk, mk_keyed, lz, fl, full):
    for x in (mk, mk_keyed, lz, fl, full):
        back = cert.parse(x.data)
        assert isinstance(back, cert2.Certificate)
        assert back == cert2._normalized(x.cert)
        assert cert2.encode(back) == x.data


def test_the_fixtures_exercise_every_line_and_form(mk, mk_keyed, lz, fl,
                                                   full):
    keys = set()
    for x in (mk, mk_keyed, lz, fl, full):
        keys |= {ln.split(" ")[0] for ln in lines_of(x.data)}
    assert keys == set(cert2.RANK) - {"hash"}
    kinds = {r.kind for r in cert.parse(lz.data).runs}
    assert kinds == set(cert2.RUN_KINDS)
    assert {e.method for x in (lz, fl) for e in cert.parse(x.data).accuracy} \
        == set(cert2.METHOD_KIND)


def test_markstep_is_what_its_header_says(mk):
    """Segment 1 marks lanes 0 and 1: lane 0's last bit wrong, lane 1's
    right, each raising invalid with the mark (0x91); the replay changes
    one, and the certified segment carries the definition's flags."""
    raw_end, raw_block, marked, changed = mk.chain.raws[1]
    assert set(mk.chain.raws) == {1}
    assert raw_block == bytes([0x91, 0x91, 0x10])
    assert (marked, changed) == (2, 1)
    assert mk.chain.blocks == [bytes([0x10] * 3)] * 3
    assert mk.chain.results == [(16, 0)] * 3
    L = lines_of(mk.data)
    assert L[find(L, "replay ")].startswith("replay 1 marked 2 changed 1 ")


# ---- the census of version 1's controls, on version 2's grammar ---------------

@pytest.mark.parametrize("which", ["mk", "mk_keyed", "lz", "full"])
def test_a_byte_flipped_anywhere_is_refused(which, request):
    x = request.getfixturevalue(which)
    data = x.data
    for i in range(0, len(data), 3 if which == "lz" else 1):
        bad = bytearray(data)
        bad[i] ^= 0x01
        with pytest.raises(cert.Refusal) as ei:
            cert.parse(bytes(bad))
        assert ei.value.exit_code in (1, 2), (i, ei.value.name)


@pytest.mark.parametrize("which", ["mk", "mk_keyed", "lz", "fl", "full"])
def test_every_line_dropped_repeated_or_unknown_is_refused(which, request):
    x = request.getfixturevalue(which)
    L = lines_of(x.data)
    for i in range(len(L)):
        for bad, why in ((L[:i] + L[i + 1:], "dropped"),
                         (L[:i + 1] + L[i:], "repeated")):
            with pytest.raises(cert.Refusal) as ei:
                cert.parse(rebuilt(bad))
            assert ei.value.exit_code == 2, (why, i, L[i][:40],
                                             ei.value.name)
        if i:
            got = refused("unknown-line", cert.parse,
                          rebuilt(L[:i] + ["bogus 1"] + L[i:]))
            assert got.line == i + 1


@pytest.mark.parametrize("which", ["mk", "lz", "fl", "full"])
def test_every_adjacent_pair_exchanged_is_refused(which, request):
    x = request.getfixturevalue(which)
    L = lines_of(x.data)
    for i in range(len(L) - 1):
        if L[i].split(" ")[0] == L[i + 1].split(" ")[0] == "term":
            continue        # a term's order is the producer's statement
        bad = L[:i] + [L[i + 1], L[i]] + L[i + 2:]
        with pytest.raises(cert.Refusal) as ei:
            cert.parse(rebuilt(bad))
        assert ei.value.exit_code == 2, (i, L[i][:30], ei.value.name)


COUNTS = ("runs", "segments", "parameters", "source-params", "replays",
          "replay-methods", "environment", "accuracy")


@pytest.mark.parametrize("which", ["mk", "lz", "fl", "full"])
def test_every_count_one_more_and_one_less(which, request):
    x = request.getfixturevalue(which)
    L = lines_of(x.data)
    seen = 0
    for i, ln in enumerate(L):
        t = ln.split(" ")
        if t[0] not in COUNTS:
            continue
        n = int(t[1])
        for m in (n + 1, n - 1):
            if m < 0:
                continue
            bad = list(L)
            bad[i] = f"{t[0]} {m}"
            got = refused("malformed" if (t[0] in ("runs", "segments")
                                          and m == 0) else "count",
                          cert.parse, rebuilt(bad))
            assert got.line == i + 1
        seen += 1
    assert seen >= 4


# ---- the encodings ------------------------------------------------------------

def test_a_text_has_one_spelling():
    assert cert2.text_token("Logan W.") == "Logan%20W."
    assert cert2.text_token("100%") == "100%25"
    assert cert2.text_token(LODZ) == "%C5%81%C3%B3d%C5%BA"
    for v in ("Logan W.", "100%", LODZ, "a~!$&",
              "x" * 255):
        assert cert2.read_text(cert2.text_token(v)) == v
    for bad in cert2.WORDS + ("", "x" * 256, chr(0x100) * 128):
        refused("malformed", cert2.text_token, bad)
    refused("malformed", cert2.text_token, 5)
    refused("malformed", cert2.text_token, "\ud800")
    for tok in ("%41", "%2f", "%2", "%", "%FF", "x" * 256, "none",
                "%6Eone"):
        assert cert2.read_text(tok) is None, tok


def test_texts_and_words_on_their_lines(full):
    for prefix, value, name in (
            ("issuer ", "issuer %41", "malformed"),
            ("issuer ", "issuer Logan%2fW", "malformed"),
            ("issuer ", "issuer " + "x" * 256, "malformed"),
            ("issuer ", "issuer unknown", "malformed"),
            ("certificate-id ", "certificate-id withheld", "malformed"),
            ("device-platform ", "device-platform withheld", "malformed"),
            ("host-os ", "host-os none", "malformed"),
            ("device-serial ", "device-serial given", "malformed"),
            ("writer-runtime ", "writer-runtime withheld", "malformed")):
        refused(name, cert.parse, edit(full.data, prefix, value))
    for prefix, value in (("issuer ", "issuer none"),
                          ("issuer ", "issuer withheld"),
                          ("device-serial ", "device-serial withheld"),
                          ("host-os ", "host-os withheld")):
        cert.parse(edit(full.data, prefix, value))


@pytest.mark.parametrize("bad", [
    "2026-13-01T00:00:00Z", "2026-02-30T00:00:00Z", "2026-10-02T24:00:00Z",
    "2016-12-31T23:59:60Z", "2026-10-02T00:00:00z", "2026-10-02t00:00:00Z",
    "2026-10-02T00:00:00+00:00", "2026-10-02T00:00Z", "2100-02-29T00:00:00Z",
    "2026-10-02T00:00:00.5Z", "26-10-02T00:00:00Z", "withheld"])
def test_a_time_has_one_spelling(full, bad):
    refused("malformed", cert.parse, edit(full.data, "started ",
                                          f"started {bad}"))


def test_the_times_in_their_order(full):
    for good in ("2024-02-29T00:00:00Z", "2000-02-29T00:00:00Z"):
        cert.parse(reencode(full.data, started=good))
    late = edit(full.data, "started ", "started 2026-10-02T12:00:06Z")
    got = refused("provenance-order", cert.parse, late)
    assert lines_of(late)[got.line - 1].startswith("finished ")
    late = edit(full.data, "finished ", "finished 2026-10-02T12:00:07Z")
    got = refused("provenance-order", cert.parse, late)
    assert lines_of(late)[got.line - 1].startswith("issued ")
    late = edit(edit(full.data, "finished ", "finished unknown"),
                "started ", "started 2026-10-02T12:00:07Z")
    got = refused("provenance-order", cert.parse, late)
    assert lines_of(late)[got.line - 1].startswith("issued ")
    cert.parse(reencode(full.data, finished="unknown"))
    cert.parse(reencode(full.data, started="unknown", finished="unknown",
                        issued="unknown"))
    # in the line order (verifier-VCV2B): finished before started is
    # refused at finished's line, before issued's impossible date is read
    late = edit(edit(edit(full.data, "started ",
                          "started 2026-10-02T12:00:06Z"),
                     "finished ", "finished 2026-10-02T12:00:05Z"),
                "issued ", "issued 2026-02-30T00:00:00Z")
    got = refused("provenance-order", cert.parse, late)
    assert lines_of(late)[got.line - 1].startswith("finished ")


@pytest.mark.parametrize("line,value", [
    ("profile ", "02"), ("profile ", "2.0"), ("profile ", "2.01"),
    ("profile ", "2."), ("profile ", "v2"), ("profile ", "0"),
    ("profile ", "none"), ("language ", "1.0"), ("language ", "withheld"),
    ("profile ", "9" * 20)])
def test_a_version_has_one_spelling(full, line, value):
    refused("malformed", cert.parse, edit(full.data, line,
                                          f"{line}{value}"))


def test_versions_that_read(full):
    for line, value in (("profile ", "2.1"), ("profile ", "unknown"),
                        ("language ", "none"), ("language ", "3.25"),
                        ("profile ", "9223372036854775807")):
        cert.parse(edit(full.data, line, f"{line}{value}"))
    assert cert2.covers((2, 0), "2") and cert2.covers((2, 3), "2.1")
    assert not cert2.covers((2, 0), "2.1") and not cert2.covers((2, 0), "1")
    assert not cert2.covers((2, 0), "3") and not cert2.covers((2, 0),
                                                              "unknown")
    assert cert2.covers((1, 0), "none")


def test_language_none_names_no_source(mk, fl):
    """`language none` says no run names a source (verifier-VCV2B: it was
    read beside one): refused `malformed` at the first run's source line,
    and by the writer. Where no run names a source the language is not
    compared, whatever is stated - no check reads it - and the profile
    always is."""
    data = edit(mk.data, "language ", "language none")
    got = refused("malformed", cert.parse, data)
    assert lines_of(data)[got.line - 1].startswith("source ")
    refused("malformed", reencode, mk.data, language="none")
    assert cert2._Cover(cert.parse(edit(fl.data, "language ",
                                        "language 9"))).covered
    assert not cert2._Cover(cert.parse(edit(mk.data, "language ",
                                            "language 9"))).covered
    assert not cert2._Cover(cert.parse(edit(fl.data, "profile ",
                                            "profile 9"))).covered
    assert cert2._Cover(cert.parse(mk.data)).covered


def test_keys_digests_builds_and_clock(full):
    for prefix, value in (
            ("issuer-key ", "issuer-key " + TEST_KEY[:63]),
            ("issuer-key ", "issuer-key " + TEST_KEY.upper()),
            ("issuer-key ", "issuer-key unknown"),
            ("supersedes ", "supersedes " + "a" * 65),
            ("supersedes ", "supersedes withheld"),
            ("device-clock ", "device-clock 0"),
            ("device-clock ", "device-clock 0135000000"),
            ("device-clock ", "device-clock withheld"),
            ("compiler-build ", "compiler-build commit=abc tracked=clean "
                                "untracked=none"),
            ("compiler-build ", "compiler-build withheld"),
            ("writer ", "writer golden"),
            ("writer ", "writer Golden unknown"),
            ("writer ", "writer none unknown"),
            ("writer ", "writer golden commit=" + "a" * 40),
            ("initial ", "initial given x"),
            ("initial ", "initial generator Shake-box x"),
            ("initial ", "initial generator shake-box " + " ".join(
                ["a"] * 17)),
            ("initial ", "initial generator shake-box a%2fb"),
            ("initial ", "initial generator given x"),
            ("initial ", "initial generator none"),
            ("initial ", "initial generator unknown x y"),
            ("initial ", "initial generator withheld x")):
        refused("malformed", cert.parse, edit(full.data, prefix, value))
    # verifier-VCV2B's case: signed-fp64's generator renamed a word
    line = lines_of(full.data)[find(lines_of(full.data), "initial ")]
    got = refused("malformed", cert.parse, edit(
        full.data, "initial ", line.replace(" shake-box ", " given ")))
    assert "one of the words" in got.message


def test_the_environment_lines(full):
    L = lines_of(full.data)
    i = find(L, "env ")
    a, b = L[i], L[i + 1]
    refused("line-order", cert.parse, rebuilt(L[:i] + [b, a] + L[i + 2:]))
    refused("line-unexpected", cert.parse,
            rebuilt(L[:i] + [a, a] + L[i + 2:]))
    for bad in ("env cft_timeout_ms 60000", "env CFT-X 1", "env 1X 2",
                "env CFT_TIMEOUT_MS 60%3000", "env CFT_TIMEOUT_MS none",
                # verifier-VCV2B: a name off the writer's list, a home path
                "env HOME /home/logan", "env CFT_HOME x"):
        refused("malformed", cert.parse, rebuilt(L[:i] + [bad]
                                                 + L[i + 1:]))


def test_the_environment_list_is_the_codes_getenv_calls():
    """cert2.ENVIRONMENT_NAMES is every variable libcft (host/src) and
    cft-segrun (host/tools/segrun.c) read, getenv and libcft's instrument
    seeds alike - so that a new variable cannot be missed."""
    found = set()
    files = [p for p in (ROOT / "host" / "src").iterdir()
             if p.suffix in (".c", ".cpp", ".h")]
    files.append(ROOT / "host" / "tools" / "segrun.c")
    for p in files:
        text = p.read_text(encoding="utf-8", errors="replace")
        found |= set(re.findall(r'(?:getenv|instrument_seed)\(\s*"([A-Z0-9_]+)"',
                                text))
    assert found == set(cert2.ENVIRONMENT_NAMES)
    assert list(cert2.ENVIRONMENT_NAMES) == sorted(cert2.ENVIRONMENT_NAMES)
    env = cert2.environment({"CFT_TIMEOUT_MS": "1", "CFT_XRT_TILES": "",
                             "PATH": "x"})
    assert env == (("CFT_TIMEOUT_MS", "1"),)


def test_the_run_and_source_lines(mk, lz):
    for prefix, value in (
            ("run 0 ", "run 0 wider-source"),
            ("compiler ", "compiler cftc 1"),
            ("compiler ", "compiler none x"),
            ("compiler ", "compiler unknown 1 sw"),
            ("compiler ", "compiler cftc 01 sw"),
            ("graph ", "graph " + "A" * 64),
            ("source ", "source " + "a" * 63),
            ("lane-flags ", "lane-flags maybe")):
        refused("malformed", cert.parse, edit(mk.data, prefix, value))
    L = lines_of(lz.data)
    i = find(L, "run 2 wider-source")
    refused("malformed", cert.parse, rebuilt(L[:i] + ["run 2 wider-source x"]
                                             + L[i + 1:]))
    i = find(L, "source-param ")
    refused("malformed", cert.parse,
            rebuilt(L[:i] + ["source-param 1rho 29"] + L[i + 1:]))
    j = find(L, "source-params ")
    two = L[:j] + ["source-params 2", "source-param rho 29",
                   "source-param beta 3"] + L[i + 1:]
    refused("line-order", cert.parse, rebuilt(two))
    two = L[:j] + ["source-params 2", "source-param rho 29",
                   "source-param rho 30"] + L[i + 1:]
    refused("line-unexpected", cert.parse, rebuilt(two))
    # a run of `source none` with a source line in it
    F = lines_of(mk.data)
    k = find(F, "source ")
    bad = F[:k] + ["source none"] + F[k + 1:]
    refused("line-unexpected", cert.parse, rebuilt(bad))


def test_the_versions_of_the_format(mk):
    """A version-2 body under `cft-certificate 1` is version 1's reader's,
    which refuses the first version-2 line it scans, `profile`; version 3
    is no version this reader speaks."""
    L = lines_of(mk.data)
    got = refused("unknown-line", cert.parse,
                  rebuilt(["cft-certificate 1"] + L[1:]))
    assert L[got.line - 1].startswith("profile ")
    refused("version", cert.parse, rebuilt(["cft-certificate 3"] + L[1:]))
    refused("malformed", cert.parse, rebuilt(["cft-certificate 2 x"]
                                             + L[1:]))


# ---- the lane flags and the replay lines, as the reader holds them ---------------

def test_a_lanes_pair_is_there_exactly_when_the_run_asks(mk, lz):
    L = lines_of(mk.data)
    i = find(L, "segment 0 ")
    refused("malformed", cert.parse,
            rebuilt(L[:i] + [" ".join(L[i].split(" ")[:10])] + L[i + 1:]))
    Z = lines_of(lz.data)
    j = find(Z, "segment 0 ")
    refused("malformed", cert.parse,
            rebuilt(Z[:j] + [Z[j] + " lanes " + "0" * 64] + Z[j + 1:]))


def test_a_mark_is_never_certified(mk, fl):
    for x in (mk, fl):
        L = lines_of(x.data)
        i = find(L, "segment 1 ")
        t = L[i].split(" ")
        t[9] = str(int(t[9]) | 64)
        got = refused("marked", cert.parse,
                      rebuilt(L[:i] + [" ".join(t)] + L[i + 1:]))
        assert got.line == i + 1


def test_the_replay_lines_form(mk):
    L = lines_of(mk.data)
    r = find(L, "replay ")
    rep = L[r]
    # in a `lane-flags no` run (the pairs dropped so that the lines read)
    no = [ln if not ln.startswith("segment ") else
          " ".join(ln.split(" ")[:10]) for ln in L]
    no[find(no, "lane-flags ")] = "lane-flags no"
    got = refused("replay-lane-flags", cert.parse, rebuilt(no))
    assert no[got.line - 1].startswith("replays ")
    # in a run that names no source
    k = find(L, "source ")
    nosrc = L[:k] + ["source none"] + L[find(L, "lanes "):]
    refused("replay-source", cert.parse, rebuilt(nosrc))
    # out of order, repeated, a count one off
    t = rep.split(" ")
    t0 = list(t)
    t0[1] = "0"
    m = find(L, "replays ")
    two = L[:m] + ["replays 2", rep, " ".join(t0)] + L[r + 1:]
    refused("line-order", cert.parse, rebuilt(two))
    two = L[:m] + ["replays 2", rep, rep] + L[r + 1:]
    refused("line-unexpected", cert.parse, rebuilt(two))
    refused("count", cert.parse, rebuilt(L[:m] + ["replays 2"] + L[m + 1:]))
    for i, v, name in ((3, "0", "malformed"), (3, "4", "malformed"),
                       (5, "3", "malformed"), (1, "3", "malformed"),
                       (2, "marks", "malformed")):
        tt = list(t)
        tt[i] = v
        refused(name, cert.parse, rebuilt(L[:r] + [" ".join(tt)]
                                          + L[r + 1:]))
    tt = list(t)
    tt[3], tt[5] = "1", "2"         # changed above marked
    refused("malformed", cert.parse, rebuilt(L[:r] + [" ".join(tt)]
                                             + L[r + 1:]))


def test_the_replay_method_lines(mk, fl):
    L = lines_of(mk.data)
    i = find(L, "replay-methods ")
    none = L[:i] + ["replay-methods 0"] + L[i + 2:]
    got = refused("replay-method", cert.parse, rebuilt(none))
    assert none[got.line - 1].startswith("replays ")
    two = L[:i] + ["replay-methods 2", L[i + 1], "replay-method 1 golden"] \
        + L[i + 2:]
    got = refused("replay-method", cert.parse, rebuilt(two))
    assert got.line == i + 3
    F = lines_of(fl.data)
    j = find(F, "replay-methods ")
    one = F[:j] + ["replay-methods 1", "replay-method 0 golden"] + F[j + 1:]
    got = refused("replay-method", cert.parse, rebuilt(one))
    assert got.line == j + 2
    for bad in ("replay-method 0 image", "replay-method 0 golden x",
                "replay-method 0 silver", "replay-method 01 golden"):
        refused("malformed", cert.parse,
                rebuilt(L[:i + 1] + [bad] + L[i + 2:]))
    ok = L[:i + 1] + ["replay-method 0 image " + "c" * 64] + L[i + 2:]
    cert.parse(rebuilt(ok))


# ---- the audit: accepted, and what it was handed ----------------------------------

def test_markstep_audits_and_says_what_it_replayed(mk):
    v = audit_mk(mk, define={0: "all"})
    lines = v.lines()
    assert lines[0] == "cft-certificate 2: ACCEPTED - every check passed"
    assert lines[1] == (f"certificate {cert2.body_hash_of(mk.data)}: its "
                        f"name, the SHA-256 of its body")
    assert "run 0 replays: 2 lanes in 1 segment replayed by the definition, " \
           "each matched" in lines
    assert any(ln.startswith("run 0 definition re-run: segments [0, 1, 2]")
               for ln in lines)
    assert "handed: re-run from the start - from the initial states alone" \
        in lines
    every = {0: dict(enumerate(mk.chain.states))}
    v = audit_mk(mk, states=every, choose={0: [2]})
    assert "handed: re-run - from states handed" in v.lines()
    assert v.header()[0].startswith("auditor golden python-")
    # a source with no compiler named: the verdict says what is unchecked
    # (verifier-VCV2B: c = 3/5 against 3/4 passes unless the definition is
    # re-run, or a lane is replayed)
    assert any(ln.startswith(f"run 0 source {mk.run.source.digest}: checked")
               and "no compiler named, so the image's map is not re-derived "
                   "from it" in ln for ln in v.lines())


def test_the_keyed_mode_protects_states_and_nothing_else(mk, mk_keyed):
    """The salt keys every state, stream, block and raw hash; the source,
    its graph and every provenance line are the same bytes keyed or
    open."""
    a, b = cert.parse(mk.data), cert.parse(mk_keyed.data)
    assert a.provenance == b.provenance
    assert a.runs[0].source == b.runs[0].source
    assert a.runs[0].image == b.runs[0].image
    for x, y in zip(a.runs[0].chain, b.runs[0].chain):
        assert x.lanes != y.lanes and x.end != y.end
    assert a.runs[0].replays[0].raw_end != b.runs[0].replays[0].raw_end
    assert a.runs[0].replays[0].raw_lanes != b.runs[0].replays[0].raw_lanes
    audit_mk(mk_keyed)
    refused("salt-missing", cert.audit, mk_keyed.data, None,
            {0: (mk_keyed.img, mk_keyed.bank)}, states={0: {0: mk.init}},
            sources={0: mk.src})
    blk = mk_keyed.chain.blocks[0]
    assert cert.parse(mk_keyed.data).runs[0].chain[0].lanes == \
        cert2.lane_flags_hash(SALT, blk)


def test_lorenz_compiled_audits_with_its_sources(lz):
    v = audit_lz(lz, define={0: [0]})
    lines = v.lines()
    for r in (0, 1, 2):
        assert any(ln.startswith(f"run {r} source ") and "recompiled by "
                   f"cftc {cftc.VERSION} for sw" in ln for ln in lines), r
    assert "run 3 source: none" in lines
    ws = [e for e in cert.parse(lz.data).accuracy
          if e.method == "wider-source"]
    assert ws and ws[0].kind == "estimate" and ws[0].uses == 2


def test_an_audit_rebuilds_from_the_source_and_the_generator():
    """Every image and bank the auditor's own recompile, the initial state
    regenerated by its named generator, no state handed: `rebuilt`."""
    src = LZ_SRC.read_bytes()
    c64 = cert2.compile_source(src, "fp64", 50, "sw")
    box = ("rebuilt", "-1", "1", "-1", "1", "20", "30")
    init = cert2.generate_initial(("generator", "shake-box", box), "fp64",
                                  2, 3)
    ch = cert2.run_chain(c64.image, c64.bank, init, 2)
    run = cert2.certify_run("main", c64.image, c64.bank, None, ch, steps=50,
                            source=cert2.source_lines(
                                src, "fp64", compiler=CFTC + ("sw",)))
    c = cert2.Certificate("open", None, IDN, prov(
        initial=("generator", "shake-box", box)), (run,), ())
    data = cert2.encode(c)
    v = cert.audit(data, None, {0: (c64.image, c64.bank)},
                   sources={0: src}, regenerate=True)
    assert any(ln.startswith("handed: rebuilt") for ln in v.lines())
    assert "initial state: regenerated by shake-box, run 0's boundary 0" \
        in v.lines()
    # not asked to regenerate, and handed nothing: no start
    refused("state-missing", cert.audit, data, None,
            {0: (c64.image, c64.bank)}, sources={0: src})
    refused("choice", cert.audit, data, None, {0: (c64.image, c64.bank)},
            sources={0: src}, regenerate="yes")


def test_the_dispatch_by_the_magic_line(mk):
    """cert.parse and cert.audit read both versions by the magic line, and
    a version-1 audit takes none of version 2's inputs."""
    v = cert.audit(mk.data, None, {0: (mk.img, mk.bank)},
                   states={0: {0: mk.init}}, sources={0: mk.src})
    assert v.lines()[0] == "cft-certificate 2: ACCEPTED - every check passed"
    v1 = make_v1_markstep()
    with pytest.raises(TypeError):
        cert.audit(v1.data, None, {0: (v1.img, v1.bank)},
                   states={0: {0: v1.init}}, sources={0: v1.src})
    assert type(cert.parse(v1.data)) is cert.Certificate
    assert type(cert.parse(mk.data)) is cert2.Certificate
    with pytest.raises(TypeError):
        cert2.audit(v1.data, None, {0: (v1.img, v1.bank)})


def make_v1_markstep():
    """markstep certified in version 1: the machine's own values, the mark
    in segment 1's STATUS, no replay (the lead's decision, R8's question
    3)."""
    src = MARK_SRC.read_bytes()
    g = cert2.source_graph(src)
    img = asm.assemble(MARK_ASM.read_text(encoding="utf-8"), "markstep-fp64")
    bank = markstep_bank(g)
    init = [d64(t) for t in MARK_INIT]
    st, rs = cert.run_chain(img, bank, init, 3)
    run = cert.certify_run("main", img, bank, None, st, rs, steps=4)
    c = cert.Certificate("open", None, IDN, (run,), ())
    return types.SimpleNamespace(src=src, img=img, bank=bank, init=init,
                                 states=st, results=rs,
                                 data=cert.encode(c))


def test_version_1_records_the_machines_own_values(mk):
    v1 = make_v1_markstep()
    assert [s for _f, s in v1.results] == [0, 64, 0]
    assert [f for f, _s in v1.results] == [16, 17, 16]
    cert.audit(v1.data, None, {0: (v1.img, v1.bank)},
               states={0: {0: v1.init}})
    # the same run's boundary 0 and 1 in both versions; boundary 2 differs
    # by the replay
    a = cert.parse(v1.data).runs[0].chain
    b = cert.parse(mk.data).runs[0].chain
    assert a[0].start == b[0].start and a[0].end == b[0].end
    assert a[1].end != b[1].end


# ---- 2a: the signature -----------------------------------------------------------

def test_a_signed_certificate(full):
    v = audit_full(full, signature=full.sig, keyring=full.ring,
                   superseded=None)
    assert f"signature: by key {TEST_KEY}, verified, held by " \
           f"{cert2.text_token(TEST_ISSUER)} by the keyring handed" \
        in v.lines()
    v = audit_full(full, signature=full.sig)
    assert f"signature: by key {TEST_KEY}, verified, which no keyring " \
           f"handed names" in v.lines()
    v = audit_full(full)
    assert "signature: none handed" in v.lines()
    assert cert2.check_signature_file(full.data, full.sig) == TEST_KEY
    assert full.sig == cert2.signature_file(TEST_SEED, full.data)


def test_the_signature_files_form(full):
    S = full.sig.decode("ascii").split("\n")[:-1]
    for bad in ("\n".join(S[:4]) + "\n",
                "\n".join(S[:2] + [S[2][:-1]] + S[3:]) + "\n",
                "\n".join(S[:2] + [S[2].upper()] + S[3:]) + "\n",
                "\r\n".join(S) + "\r\n",
                "\n".join(S) + "\nextra\n",
                "\n".join(S),
                "\n".join(["cft-signature 2"] + S[1:]) + "\n",
                "\n".join(S[:1] + ["scheme ed448"] + S[2:]) + "\n"):
        refused("signature-format", audit_full, full,
                signature=bad.encode("ascii"))
    refused("signature-format", audit_full, full, signature="text")


def test_a_signature_that_does_not_verify_or_names_another(full, fl):
    S = full.sig.decode("ascii").split("\n")[:-1]
    last = S[4][-1]
    flipped = S[4][:-1] + ("0" if last != "0" else "1")
    bad = "\n".join(S[:4] + [flipped]) + "\n"
    refused("signature", audit_full, full, signature=bad.encode("ascii"))
    other = cert2.signature_file(TEST_SEED, fl.data)
    refused("signature", audit_full, full, signature=other)


def test_a_signature_by_another_key(full):
    rfc_test_1 = bytes.fromhex("9d61b19deffd5a60ba844af492ec2cc4"
                               "4449c5697b326919703bac031cae7f60")
    sig = cert2.signature_file(rfc_test_1, full.data)
    refused("signature-key", audit_full, full, signature=sig)
    # where the certificate names no key, any key's signature verifies
    data = reencode(full.data, issuer_key="none")
    cert.audit(data, SALT, {0: (full.img, None)}, states={0: {0: full.init}},
               signature=cert2.signature_file(rfc_test_1, data))


def test_a_keyring_names_the_signer(full):
    other = f"key {TEST_KEY} Someone%20Else\n".encode("ascii")
    refused("signer", audit_full, full, signature=full.sig, keyring=other)
    for bad in (b"key " + TEST_KEY.encode() + b" "
                + TEST_ISSUER.encode() + b"\n",
                b"key " + TEST_KEY[:63].encode() + b" x\n",
                b"key " + TEST_KEY.encode() + b" x",
                full.ring + full.ring, b"\x00\n", "text"):
        refused("signer", audit_full, full, signature=full.sig,
                keyring=bad)
    # a keyring is held to its form whether or not a signature is handed
    refused("signer", audit_full, full, keyring=b"junk\n")
    # a keyring that names other keys only
    v = audit_full(full, signature=full.sig,
                   keyring=f"key {RFC_TEST_1_KEY} x\n".encode())
    assert any("which the keyring handed does not name" in ln
               for ln in v.lines())


def small_order_keys():
    """The eight keys of small order, as test_ed25519.py derives them: the
    multiples of [L]P for the point P whose y is 3 and x even."""
    E = ed25519
    x = E._recover_x(3, 0)
    q = E._mul(E.L, (x, 3, 1, (x * 3) % E.P))
    return [E.encode_point(E._mul(k, q)).hex() for k in range(8)]


def test_a_key_of_small_order_is_refused_wherever_a_key_is_read(
        full, tmp_path):
    """verifier-VCV2B's case and the lead's decision. Under a key of
    small order ([8]A the identity) a signature nobody made verifies for
    every message, so such a key is refused `signer` wherever a key is
    read: the certificate's issuer-key line (by the reader, and so by the
    writer reading its text back), a keyring's line, a signature file's
    key, and the key tool's verify. A key that encodes no point is no key
    either: `malformed` on the issuer-key line, `signer` in a keyring."""
    keys = small_order_keys()
    assert SMALL_KEY in keys and len(set(keys)) == 8
    for k in keys:
        data = edit(full.data, "issuer-key ", f"issuer-key {k}")
        got = refused("signer", cert.parse, data)
        assert lines_of(data)[got.line - 1] == f"issuer-key {k}"
    refused("signer", reencode, full.data, issuer_key=SMALL_KEY)
    no_point = "02" + "00" * 31                 # y = 2: no square root
    data = edit(full.data, "issuer-key ", f"issuer-key {no_point}")
    got = refused("malformed", cert.parse, data)
    assert lines_of(data)[got.line - 1] == f"issuer-key {no_point}"
    # VCV2B's forged signature, under the identity, on a certificate that
    # names no key: the signature file's key is refused before anything
    plain = reencode(full.data, issuer_key="none")
    forged = (f"cft-signature 1\nscheme ed25519\nkey {SMALL_KEY}\n"
              f"certificate {cert2.body_hash_of(plain)}\n"
              f"signature {SMALL_SIG}\n").encode("ascii")
    got = refused("signer", cert.audit, plain, SALT, {0: (full.img, None)},
                  states={0: {0: full.init}}, signature=forged)
    assert SMALL_KEY in got.message
    refused("signer", cert2.check_signature_file, plain, forged)
    # a keyring's key, of small order or no point, with or without a
    # signature handed
    for k in (SMALL_KEY, keys[3], no_point):
        ring = f"key {k} x\n".encode("ascii")
        refused("signer", audit_full, full, keyring=ring)
        refused("signer", audit_full, full, signature=full.sig,
                keyring=ring)
    # the key tool's verify
    c = tmp_path / "plain.cert"
    c.write_bytes(plain)
    (tmp_path / "plain.cert.sig").write_bytes(forged)
    rc, out, err = _tool("verify", "--cert", c)
    assert rc == 4 and "refused signer" in err, (rc, err)


def test_either_version_is_signed(full):
    v1 = make_v1_markstep()
    sig = cert2.signature_file(TEST_SEED, v1.data)
    assert cert2.check_signature_file(v1.data, sig) == TEST_KEY
    refused("signature", cert2.check_signature_file, full.data, sig)
    refused("body-hash", cert2.signature_file, TEST_SEED,
            v1.data[:-3] + b"00\n")


# ---- 3a: supersedes ---------------------------------------------------------------

def test_supersedes(full, fl, mk):
    v = audit_full(full, superseded=fl.data)
    assert f"supersedes {cert2.body_hash_of(fl.data)}: the certificate " \
           f"handed is that one" in v.lines()
    v = audit_full(full)
    assert any(ln.endswith("named, not handed - stated, not checked") and
               ln.startswith("supersedes ") for ln in v.lines())
    refused("supersedes", audit_full, full, superseded=mk.data)
    refused("supersedes", audit_full, full, superseded=b"junk\n")
    refused("supersedes", audit_full, full, superseded="text")
    refused("supersedes", audit_mk, mk, superseded=fl.data)


# ---- 4: the loader's verdict through the definition -----------------------------

def _deep(mk):
    """markstep's image with its header declaring 513 constants: refused
    at load since ee78152, loaded and run before it."""
    img = bytearray(mk.img)
    img[12:16] = (513).to_bytes(4, "little")
    return bytes(img)


def test_the_definition_at_load(mk):
    img = _deep(mk)
    run = dataclasses.replace(mk.run, image=cert.sha256(img),
                              digest=cert.sha256(img + mk.bank))
    c = dataclasses.replace(mk.cert, runs=(run,))
    for profile, name in (("1", "definition-differs"),
                          ("2", "program-image")):
        data = cert2.encode(dataclasses.replace(
            c, provenance=dataclasses.replace(c.provenance,
                                              profile=profile)))
        got = refused(name, cert.audit, data, None, {0: (img, mk.bank)},
                      states={0: {0: mk.init}}, sources={0: mk.src})
        assert got.run == 0


# ---- 4a: the sources --------------------------------------------------------------

def test_a_source_handed_is_the_one_named(mk, fl):
    bad = mk.src.replace(b"9/10", b"9/11")
    refused("source-digest", audit_mk, mk, sources={0: bad})
    refused("source-digest", audit_fl, fl, sources={0: mk.src})
    refused("source-digest", audit_mk, mk, sources={0: "text"})
    refused("source-digest", audit_mk, mk, sources={1: mk.src})
    refused("source-digest", audit_mk, mk, sources=[mk.src])


def test_a_source_the_language_refuses(mk):
    bad = mk.src.replace(b"step   map", b"step   mapp")
    run = dataclasses.replace(mk.run, source=cert2.Source(
        cert.sha256(bad), "bad.cftl", "0" * 64, None, ()))
    data = cert2.encode(dataclasses.replace(mk.cert, runs=(run,)))
    got = refused("source-refused", audit_mk, mk, data, sources={0: bad})
    assert "unknown-integrator" in got.message


def test_a_main_runs_format_is_its_sources(lz):
    run = dataclasses.replace(lz.runs[2], kind="main")
    data = with_runs(lz, (run,), ())
    refused("source-format", cert.audit, data, None,
            {0: lz.progs[2]}, states={0: {0: lz.init_w}},
            sources={0: lz.src})


def test_the_graph_and_the_params(lz, mk):
    L = lines_of(lz.data)
    mk_graph = cert.parse(mk.data).runs[0].source.graph
    refused("source-graph", audit_lz, lz,
            edit(lz.data, "graph ", f"graph {mk_graph}"))
    i = find(L, "source-param ")
    j = find(L, "source-params ")
    zeta = L[:j] + ["source-params 2", L[i], "source-param zeta 1"] \
        + L[i + 1:]
    refused("source-param", audit_lz, lz, rebuilt(zeta))
    for lit in ("29.0", "29e0", "0x1d", "1e999999999"):
        refused("source-param", audit_lz, lz,
                rebuilt(L[:i] + [f"source-param rho {lit}"] + L[i + 1:]))


def test_a_lane_is_its_sources_lane(lz, mk):
    run = dataclasses.replace(lz.runs[0], source=cert2.source_lines(
        mk.src, "fp64", name="markstep-fp64.cftl"))
    data = with_runs(lz, (run,), ())
    refused("source-shape", cert.audit, data, None, {0: lz.progs[0]},
            states={0: {0: lz.init}}, sources={0: mk.src})


def test_the_recompile(lz):
    L = lines_of(lz.data)
    # the steps changed: the image differs
    i = find(L, "steps ")
    refused("source-image", audit_lz, lz,
            rebuilt(L[:i] + ["steps 99"] + L[i + 1:]))
    # a source param's value changed: the bank differs
    j = find(L, "source-param ")
    refused("source-image", audit_lz, lz,
            rebuilt(L[:j] + ["source-param rho 30"] + L[j + 1:]))
    # a target the auditor's compiler does not have
    k = find(L, "compiler ")
    refused("source-image", audit_lz, lz, rebuilt(
        L[:k] + [f"compiler cftc {cftc.VERSION} no-such-target"]
        + L[k + 1:]))
    # another compiler, whose recompile differs: the auditor's own limit
    other = cftc.VERSION + 97
    got = refused("compiler-differs", audit_lz, lz, rebuilt(
        L[:k] + [f"compiler cftc {other} sw"] + L[k + 1:i] + ["steps 99"]
        + L[i + 1:]))
    assert got.run == 0
    # another compiler whose recompile is equal: nothing to blame
    run0 = dataclasses.replace(lz.runs[0], source=dataclasses.replace(
        lz.lines64, compiler=("cftc", other, "sw")))
    cert.audit(with_runs(lz, (run0,), ()), None, {0: lz.progs[0]},
               states={0: {0: lz.init}}, sources={0: lz.src})


def test_a_source_needed_and_not_handed(mk, lz):
    got = refused("source-missing", audit_mk, mk, sources=None)
    assert (got.run, got.segment) == (0, 1)
    got = refused("source-missing", audit_lz, lz,
                  sources={0: lz.src, 1: lz.src})
    assert got.run == 2
    got = refused("source-missing", audit_lz, lz,
                  sources={1: lz.src, 2: lz.src}, define={0: [0]})
    assert (got.run, got.segment) == (0, 0)
    # named and not handed, where nothing needs it: reported
    v = audit_lz(lz, sources={0: lz.src, 2: lz.src})
    assert any(ln.startswith("run 1 source ") and "named, not handed" in ln
               for ln in v.lines())


# ---- 7: the blocks handed, and the initial state ------------------------------

def test_a_block_handed_is_its_segments(fl, lz):
    blk = fl.chain.blocks
    refused("lane-flags-shape", audit_fl, fl, lane_flags={0: {0: blk[0][:1]}})
    refused("lane-flags-shape", audit_fl, fl,
            lane_flags={0: {0: blk[0] + b"\x00"}})
    refused("lane-flags-shape", audit_fl, fl, lane_flags={0: {5: blk[0]}})
    refused("lane-flags-shape", audit_fl, fl, lane_flags={0: {0: "xx"}})
    refused("lane-flags-shape", audit_fl, fl, lane_flags={0: [blk[0]]})
    refused("lane-flags-shape", audit_fl, fl, lane_flags={1: {0: blk[0]}})
    refused("lane-flags-shape", audit_lz, lz,
            lane_flags={0: {0: bytes(3)}})
    bad = bytearray(blk[0])
    bad[1] ^= 0x10
    refused("lane-flags-hash", audit_fl, fl, lane_flags={0: {0: bytes(bad)}})
    v = audit_fl(fl, lane_flags={0: dict(enumerate(blk))})
    assert any("handed and consistent" in ln for ln in v.lines())


def _block_line(x, k, block):
    """x's certificate with segment k's lanes hash that of `block`."""
    L = lines_of(x.data)
    i = find(L, f"segment {k} ")
    t = L[i].split(" ")
    t[11] = cert2.lane_flags_hash(None, block)
    return rebuilt(L[:i] + [" ".join(t)] + L[i + 1:])


def test_a_block_handed_holds_r23s_identities(fl):
    blk = fl.chain.blocks
    assert cert.parse(fl.data).runs[0].chain[0].flags == 20
    noinexact = bytes(b & ~0x10 for b in blk[0])
    data = _block_line(fl, 0, noinexact)
    refused("lane-flags-identity", audit_fl, fl, data,
            lane_flags={0: {0: noinexact}})
    seg2 = cert.parse(fl.data).runs[0].chain[2]
    assert seg2.status & 0x20 == 0
    strict = bytes([blk[2][0] | 0x40]) + blk[2][1:]
    data = _block_line(fl, 2, strict)
    refused("lane-flags-identity", audit_fl, fl, data,
            lane_flags={0: {2: strict}})
    mark = bytes([blk[0][0] | 0x80]) + blk[0][1:]
    data = _block_line(fl, 0, mark)
    refused("lane-flags-identity", audit_fl, fl, data,
            lane_flags={0: {0: mark}})


def test_the_initial_state_by_its_generator(full):
    v = audit_full(full, regenerate=True)
    assert "initial state: regenerated by shake-box, run 0's boundary 0 - " \
           "which a generator publishes, though the certificate is keyed" \
        in v.lines()
    v = audit_full(full)
    assert any(ln.startswith("initial state: generator shake-box - stated, "
                             "not checked") for ln in v.lines())
    other = ("generator", "shake-box", ("full case!",) + FULL_BOX[1:])
    data = reencode(full.data, initial=other)
    refused("initial-state", audit_full, full, data, regenerate=True)
    data = reencode(full.data, initial=("generator", "shake-box",
                                        FULL_BOX[:3]))
    refused("initial-state", audit_full, full, data, regenerate=True)
    data = reencode(full.data, initial=("generator", "shake-box",
                                        FULL_BOX[:1] + ("2.0", "4", "-1",
                                                        "1")))
    refused("initial-state", audit_full, full, data, regenerate=True)
    data = reencode(full.data, initial=("generator", "elsewhere", ("x",)))
    v = audit_full(full, data, regenerate=True)
    assert any("which this auditor does not know" in ln for ln in v.lines())


# ---- 8: the relations ---------------------------------------------------------------

def test_the_wider_source_relation(lz):
    src256 = (PROGRAMS / "systems" / "lorenz63-rk4-fp256.cftl").read_bytes()
    r0, r1, r2, r3 = lz.runs
    # another source, whose compile at fp128 is the same image
    other = dataclasses.replace(r2, source=cert2.source_lines(
        src256, "fp128", name="lorenz63-rk4-fp256.cftl", params=LZ_PARAMS,
        compiler=CFTC + ("sw",)))
    refused("aux-source", audit_lz, lz, with_runs(lz, (r0, r1, other, r3)),
            sources={0: lz.src, 1: lz.src, 2: src256})
    # another target: the same image, and another compiler line
    tgt = dataclasses.replace(r2, source=dataclasses.replace(
        lz.lines128, compiler=CFTC + ("sw:2048",)))
    refused("aux-source", audit_lz, lz, with_runs(lz, (r0, r1, tgt, r3)))
    # the same format
    same = dataclasses.replace(r0, kind="wider-source")
    refused("aux-format", audit_lz, lz, with_runs(lz, (r0, r1, same, r3)),
            progs={**lz.progs, 2: lz.progs[0]},
            states={**lz.states, 2: {0: lz.init}})
    # another segment count
    short = dataclasses.replace(r2, chain=r2.chain[:1],
                                output=r2.chain[0].end)
    refused("aux-segments", audit_lz, lz, with_runs(lz, (r0, r1, short, r3)))
    # streams not widened
    one = [cert.widen("fp64", d64("1"))] * 3
    own = cert.stream_hash(None, "a", cert.state_bytes("fp128", one))
    st = dataclasses.replace(r2, streams=(own,) + r2.streams[1:])
    refused("aux-streams", audit_lz, lz, with_runs(lz, (r0, r1, st, r3)),
            streams={2: (one, None, None)})
    # the start not widened (run 2's own boundary 0 not handed)
    seg0 = dataclasses.replace(r2.chain[0], start="d" * 64)
    start = dataclasses.replace(r2, chain=(seg0,) + r2.chain[1:])
    refused("aux-start", audit_lz, lz, with_runs(lz, (r0, r1, start, r3)),
            states={0: {0: lz.init}, 1: {0: lz.init}, 3: {0: lz.init_w}})
    # version 1's wider image (the widened bank) as the wider-source run
    v1w = dataclasses.replace(r3, kind="wider-source", source=lz.lines128)
    refused("source-image", audit_lz, lz, with_runs(lz, (r0, r1, v1w, r3)),
            progs={**lz.progs, 2: lz.progs[3]})


def test_other_params_for_the_wider_source_run(lz):
    params = {"rho": "30"}
    c = cert2.compile_source(lz.src, "fp128", 100, "sw", params)
    ch = cert2.run_chain(c.image, c.bank, lz.init_w, LZ_S)
    r2 = cert2.certify_run("wider-source", c.image, c.bank, None, ch,
                           steps=100, source=cert2.source_lines(
                               lz.src, "fp128",
                               name="lorenz63-rk4-fp64.cftl", params=params,
                               compiler=CFTC + ("sw",)))
    r0, r1, _r2, r3 = lz.runs
    refused("aux-source", audit_lz, lz, with_runs(lz, (r0, r1, r2, r3)),
            progs={**lz.progs, 2: (c.image, c.bank)})


def test_the_source_lines_of_the_other_auxiliary_runs(lz):
    r0, r1, r2, r3 = lz.runs
    loose = dataclasses.replace(r1, source=dataclasses.replace(
        lz.lines64, compiler=None))
    refused("aux-source", audit_lz, lz, with_runs(lz, (r0, loose, r2, r3)))
    named = dataclasses.replace(r3, source=dataclasses.replace(
        lz.lines128, compiler=None))
    refused("aux-source", audit_lz, lz, with_runs(lz, (r0, r1, r2, named)),
            sources={0: lz.src, 1: lz.src, 2: lz.src, 3: lz.src})


def test_h_slots_with_a_source_are_the_compiles(lz):
    bank = cert.state_bytes("fp64", cert.state_values("fp64", lz.c64.bank))
    half = cert.state_values("fp64", bank)
    for s in (0, 1):
        half[s], _f = sf.mul(F64, half[s], d64("0.5"))
    half = cert.state_bytes("fp64", half)
    ch = cert2.run_chain(lz.c64.image, half, lz.init, 2 * LZ_S)
    r1 = cert2.certify_run("half-step", lz.c64.image, half, None, ch,
                           steps=100, source=lz.lines64, h_slots=(0, 1))
    r0, _r1, r2, r3 = lz.runs
    assert lz.h_slots == (0, 1, 2)
    got = refused("aux-h-slots", audit_lz, lz,
                  with_runs(lz, (r0, r1, r2, r3), lz.entries[:2]),
                  progs={**lz.progs, 1: (lz.c64.image, half)})
    assert "[0, 1, 2]" in got.message
    # without the main run's source the slots are version 1's check alone
    audit_lz(lz, with_runs(lz, (r0, r1, r2, r3), lz.entries[:2]),
             progs={**lz.progs, 1: (lz.c64.image, half)},
             sources={2: lz.src})


# cft-segrun's and cft-audit's sentence for it (parcel C4's C half), which
# the golden audit gives at the wider run, `run 1 (wider): ` before it
ROUTINE_WIDER = ("the main image holds a routine (QUIET, ENDQUIET or "
                 "RAISE), whose words are its format's, so no image is it "
                 "one format wider; certificate version 2's wider-source run "
                 "compiles its source one format up instead")


def header_wider(image):
    """C4's construction of a wider image (lang_check's leg E): the main
    image's words with header bytes 20-23, the precision code, set to
    fp128's."""
    wide = bytearray(image)
    wide[20:24] = (2).to_bytes(4, "little")
    return bytes(wide)


def test_version_1_has_no_wider_run_of_a_routine_image(mk, lz):
    """Version 1's rule since 2026-10-02 (the lead's decision, with C4's
    design): a main image holding QUIET, ENDQUIET or RAISE has no wider
    run - a routine's words are format-specific - refused `aux-image`
    (exit 5) at the wider run by the golden writer and the golden audit,
    version 1's and version 2's, after the format, the lanes and the steps
    and before the instruction words. Its C half, cft-segrun and cft-audit,
    is parcel C4's, held by lang_check's leg E on Kepler; this control
    sits here so that audit_check's shadow of test_cert.py does not hand
    it to a cft-audit that refuses it only from then on. The same
    construction on Lorenz-63, which has no routine, is written and
    accepted."""
    v1 = make_v1_markstep()
    src = MARK_ASM.read_text(encoding="utf-8")
    img_w = asm.assemble(src.replace(".format   fp64", ".format   fp128"),
                         "markstep-wider")
    assert img_w == header_wider(v1.img), "C4's construction, byte for byte"
    bank_w = widened("fp64", v1.bank)
    init_w = [cert.widen("fp64", x) for x in v1.init]
    st, rs = cert.run_chain(img_w, bank_w, init_w, 3)
    got = refused("aux-image", cert.certify_run, "wider", img_w, bank_w,
                  None, st, rs, steps=4, main_image=v1.img)
    assert got.message == "the wider run: " + ROUTINE_WIDER
    # the run's shape and states come first, as in cft-segrun
    refused("state-shape", cert.certify_run, "wider", img_w, bank_w, None,
            st[:-1], rs, steps=4, main_image=v1.img)
    # a wider run is handed its main image: without it, no rule to apply
    with pytest.raises(TypeError):
        cert.certify_run("wider", img_w, bank_w, None, st, rs, steps=4)
    # the audit, of a certificate a writer that did not refuse would make
    main = cert.parse(v1.data).runs[0]
    hs = [cert.state_hash(None, cert.state_bytes("fp128", s)) for s in st]
    wider = cert.Run("wider", "fp128", cert.sha256(img_w),
                     cert.sha256(img_w + bank_w), main.lanes, 4,
                     tuple(cert.stream_hash(None, n, bytes(16 * 3))
                           for n in "abc"), (),
                     tuple(cert.Segment(hs[k], hs[k + 1], f, s)
                           for k, (f, s) in enumerate(rs)), hs[-1])
    data = cert.encode(cert.Certificate("open", None, IDN, (main, wider),
                                        ()))
    got = refused("aux-image", cert.audit, data, None,
                  {0: (v1.img, v1.bank), 1: (img_w, bank_w)},
                  states={0: {0: v1.init}, 1: {0: init_w}})
    assert (got.line, got.run, got.segment, got.entry) == (None, 1, None,
                                                           None)
    assert got.message == "run 1 (wider): " + ROUTINE_WIDER
    # after the steps: a wider run stating other steps is refused for them
    wrong = cert.encode(cert.Certificate(
        "open", None, IDN, (main, dataclasses.replace(wider, steps=5)), ()))
    got = refused("aux-image", cert.audit, wrong, None,
                  {0: (v1.img, v1.bank), 1: (img_w, bank_w)},
                  states={0: {0: v1.init}, 1: {0: init_w}})
    assert "steps" in got.message and got.run == 1
    # and version 2's wider relation, the same rule
    ch_main = cert2.run_chain(v1.img, v1.bank, v1.init, 3, steps=4,
                              definition=cert2.Definition(
                                  cert2.source_graph(v1.src)))
    r0 = cert2.certify_run("main", v1.img, v1.bank, None, ch_main, steps=4,
                           source=cert2.source_lines(v1.src, "fp64"))
    r1 = cert2.Run("wider", "fp128", wider.image, wider.digest, None,
                   wider.lanes, 4, wider.streams, (), False,
                   tuple(cert2.Segment(s.start, s.end, s.flags,
                                       s.status & ~64) for s in wider.chain),
                   (), wider.output)
    data = cert2.encode(cert2.Certificate(
        "open", None, IDN, prov(replay_methods=((0, "golden"),)), (r0, r1),
        ()))
    got = refused("aux-image", cert.audit, data, None,
                  {0: (v1.img, v1.bank), 1: (img_w, bank_w)},
                  states={0: {0: v1.init}, 1: {0: init_w}},
                  sources={0: v1.src})
    assert got.run == 1 and got.message == "run 1 (wider): " + ROUTINE_WIDER
    # the same construction on Lorenz-63, which holds no routine: written
    # by the golden writer and accepted by the golden audit
    lw = header_wider(lz.c64.image)
    assert lw == lz.img_w
    st0, rs0 = cert.run_chain(lz.c64.image, lz.c64.bank, lz.init, 1)
    st1, rs1 = cert.run_chain(lw, lz.bank_w, lz.init_w, 1)
    runs = (cert.certify_run("main", lz.c64.image, lz.c64.bank, None, st0,
                             rs0, steps=100),
            cert.certify_run("wider", lw, lz.bank_w, None, st1, rs1,
                             steps=100, main_image=lz.c64.image))
    data = cert.encode(cert.Certificate("open", None, IDN, runs, ()))
    cert.audit(data, None, {0: (lz.c64.image, lz.c64.bank),
                            1: (lw, lz.bank_w)},
               states={0: {0: lz.init}, 1: {0: lz.init_w}})


def test_the_golden_writer_tests_the_main_image():
    """verifier-VCV2B's W1 and W2: the routine rule tests the MAIN image,
    as the contract, cft-segrun and both audits do, never the wider run's
    own. markstep's source compiled by cftc holds no flag control; the
    hand-written markstep image does.
    - W1: the main image is markstep, the wider image cftc's compile at
      fp128: the golden writer refuses `aux-image`, as cft-segrun does
      (exit 5), and the audit refuses it for the routine.
    - W2, the reverse: the main image is cftc's compile, the wider image
      markstep at fp128: the routine rule does not apply and the golden
      writer writes it, as cft-segrun does; the audit refuses the
      certificate `aux-image`, the wider image not being the main one's
      words."""
    v1 = make_v1_markstep()
    src = MARK_SRC.read_bytes()
    plain64 = cftc.compile_graph(cert2.source_graph(src, "fp64"), 4, "sw",
                                 stem="markstep")
    plain128 = cftc.compile_graph(cert2.source_graph(src, "fp128"), 4, "sw",
                                  stem="markstep")
    for c in (plain64, plain128):
        prog = seq.Program.from_bytes(c.image)
        assert not seq.features_rev8(prog.insns) & seq.FEAT_FLAG_CONTROL
    init_w = [cert.widen("fp64", x) for x in v1.init]
    # W1
    st, rs = cert.run_chain(plain128.image, plain128.bank, init_w, 3)
    got = refused("aux-image", cert.certify_run, "wider", plain128.image,
                  plain128.bank, None, st, rs, steps=4, main_image=v1.img)
    assert got.message == "the wider run: " + ROUTINE_WIDER
    main = cert.parse(v1.data).runs[0]
    hs = [cert.state_hash(None, cert.state_bytes("fp128", s)) for s in st]
    wider = cert.Run("wider", "fp128", cert.sha256(plain128.image),
                     cert.sha256(plain128.image + plain128.bank), main.lanes,
                     4, tuple(cert.stream_hash(None, n, bytes(16 * 3))
                              for n in "abc"), (),
                     tuple(cert.Segment(hs[k], hs[k + 1], f, s)
                           for k, (f, s) in enumerate(rs)), hs[-1])
    data = cert.encode(cert.Certificate("open", None, IDN, (main, wider),
                                        ()))
    got = refused("aux-image", cert.audit, data, None,
                  {0: (v1.img, v1.bank), 1: (plain128.image, plain128.bank)},
                  states={0: {0: v1.init}, 1: {0: init_w}})
    assert got.run == 1 and got.message == "run 1 (wider): " + ROUTINE_WIDER
    # W2
    img_w = header_wider(v1.img)
    bank_w = widened("fp64", v1.bank)
    st0, rs0 = cert.run_chain(plain64.image, plain64.bank, v1.init, 3)
    st1, rs1 = cert.run_chain(img_w, bank_w, init_w, 3)
    runs = (cert.certify_run("main", plain64.image, plain64.bank, None, st0,
                             rs0, steps=4),
            cert.certify_run("wider", img_w, bank_w, None, st1, rs1, steps=4,
                             main_image=plain64.image))
    data = cert.encode(cert.Certificate("open", None, IDN, runs, ()))
    got = refused("aux-image", cert.audit, data, None,
                  {0: (plain64.image, plain64.bank), 1: (img_w, bank_w)},
                  states={0: {0: v1.init}, 1: {0: init_w}})
    assert got.run == 1 and "not the main image one format wider" in \
        got.message


# ---- 9: the re-runs, the blocks and the replays ---------------------------------

def test_a_re_run_block_is_the_certified_one(fl):
    blk = fl.chain.blocks[0]
    other = bytes([blk[0] & ~0x10]) + blk[1:]
    got = refused("segment-lane-flags", audit_fl, fl,
                  _block_line(fl, 0, other))
    assert (got.run, got.segment) == (0, 0)


def _mk_lines(mk):
    L = lines_of(mk.data)
    return L, find(L, "replay "), find(L, "replays ")


def test_a_replay_is_due_exactly_where_the_re_run_marks(mk):
    L, r, m = _mk_lines(mk)
    i = find(L, "replay-methods ")
    gone = L[:i] + ["replay-methods 0"] + L[i + 2:m] + ["replays 0"] \
        + L[r + 1:]
    got = refused("replay-missing", audit_mk, mk, rebuilt(gone))
    assert (got.run, got.segment) == (0, 1)
    rep = L[r].split(" ")
    extra = list(rep)
    extra[1] = "0"
    extra[3], extra[5] = "1", "0"
    two = L[:m] + ["replays 2", " ".join(extra), L[r]] + L[r + 1:]
    got = refused("replay-unmarked", audit_mk, mk, rebuilt(two))
    assert (got.run, got.segment) == (0, 0)
    # a run that does not ask for the block, whose re-run marks a lane
    no = [ln if not ln.startswith("segment ") else
          " ".join(ln.split(" ")[:10]) for ln in gone]
    no[find(no, "lane-flags ")] = "lane-flags no"
    got = refused("replay-missing", audit_mk, mk, rebuilt(no))
    assert (got.run, got.segment) == (0, 1)


def test_a_replay_lines_raw_values_are_the_re_runs(mk):
    L, r, _m = _mk_lines(mk)
    t = L[r].split(" ")
    raw_end, raw_block, _n, _c = mk.chain.raws[1]
    seg1 = cert.parse(mk.data).runs[0].chain[1]
    corrected_block = cert2.lane_flags_hash(
        None, bytes(b & ~0x80 for b in raw_block))
    for i, v in ((7, seg1.end), (9, corrected_block), (3, "3")):
        tt = list(t)
        tt[i] = v
        got = refused("replay-raw", audit_mk, mk,
                      rebuilt(L[:r] + [" ".join(tt)] + L[r + 1:]))
        assert (got.run, got.segment) == (0, 1)
    tt = list(t)
    tt[3], tt[5] = "1", "1"
    refused("replay-raw", audit_mk, mk,
            rebuilt(L[:r] + [" ".join(tt)] + L[r + 1:]))


def test_changed_is_what_the_replay_changes(mk):
    L, r, _m = _mk_lines(mk)
    for c in ("2", "0"):
        tt = L[r].split(" ")
        tt[5] = c
        got = refused("replay-changed", audit_mk, mk,
                      rebuilt(L[:r] + [" ".join(tt)] + L[r + 1:]))
        assert (got.run, got.segment) == (0, 1)


def test_the_certified_segment_is_the_corrected_one(mk):
    """The raw end, the raw block, the raw flag word and a STATUS other
    than the raw one with its mark cleared: each certified as segment 1's
    is refused by version 1's name, against the corrected values."""
    L = lines_of(mk.data)
    i = find(L, "segment 1 ")
    t = L[i].split(" ")
    raw_end, raw_block, _n, _c = mk.chain.raws[1]
    raw_end_h = cert.state_hash(None, cert.state_bytes("fp64", raw_end))
    t2 = L[i + 1].split(" ")
    for field, value, name in ((5, raw_end_h, "segment-end"),
                               (11, cert2.lane_flags_hash(None, raw_block),
                                "segment-lane-flags"),
                               (7, "17", "segment-flags"),
                               (9, "16", "segment-status")):
        tt = list(t)
        tt[field] = value
        nxt = list(t2)
        if field == 5:
            nxt[3] = value          # the chain kept whole
        got = refused(name, audit_mk, mk,
                      rebuilt(L[:i] + [" ".join(tt), " ".join(nxt)]
                              + L[i + 2:]))
        assert (got.run, got.segment) == (0, 1)


# ---- 9a: the definition re-run ------------------------------------------------------

def test_the_definition_re_run(mk):
    """An image whose bank's b is not the source's computes another map:
    its certificate holds together, and only running the source's
    interpreter finds it (`definition-end`). One that raises invalid in
    every lane computes the map with other flags (`definition-flags`)."""
    other_b = make_markstep(bank=markstep_bank(mk.graph, b=d64("0.25")))
    audit_mk(other_b)
    got = refused("definition-end", audit_mk, other_b, define={0: [0]})
    assert (got.run, got.segment) == (0, 0)
    loud = make_markstep(bank=markstep_bank(mk.graph, zero=1))
    assert loud.chain.results[0][0] == 17
    audit_mk(loud)
    got = refused("definition-flags", audit_mk, loud, define={0: [2]})
    assert (got.run, got.segment) == (0, 2)
    for bad in ({0: []}, {0: [3]}, {0: [0, 0]}, {0: "every"}, {1: "all"},
                [0]):
        refused("choice", audit_mk, mk, define=bad)


# ---- 78: whose definition --------------------------------------------------------

def test_a_failure_under_another_definition(mk, fl):
    L, r, _m = _mk_lines(mk)
    tt = L[r].split(" ")
    tt[5] = "2"
    wrong = rebuilt(L[:r] + [" ".join(tt)] + L[r + 1:])
    refused("replay-changed", audit_mk, mk, wrong)
    for field, value in (("language", "2"), ("language", "1.1"),
                         ("profile", "3"), ("profile", "2.1"),
                         ("profile", "unknown"), ("language", "unknown")):
        line = f"{field} {value}"
        got = refused("definition-differs", audit_mk, mk,
                      edit(wrong, f"{field} ", line))
        assert (got.run, got.segment) == (0, 1)
        assert "replay-changed" in got.message
    # a re-derivation that passes under a definition that does not cover
    # the certificate's: accepted, and the verdict says so
    v = audit_mk(mk, edit(mk.data, "language ", "language 2"))
    assert any("do not cover them, and every re-derivation passed" in ln
               for ln in v.lines())
    # `language none`: no source read, so every language covers it
    F = lines_of(fl.data)
    i = find(F, "segment 1 ")
    t = F[i].split(" ")
    t[7] = "21"
    got = refused("segment-flags", audit_fl, fl,
                  rebuilt(F[:i] + [" ".join(t)] + F[i + 1:]))
    assert got.segment == 1


def test_an_auditor_that_cannot_evaluate_the_definition(mk, lz,
                                                        monkeypatch):
    """A replay reaches transcend.py exactly where a node's golden function
    is one of its, which no node of the language is yet: these plants
    stand for M1's. Without mpmath, or where an enclosure reaches its cap,
    the audit refuses `definition-unavailable` and the writer
    `replay-undecided` - each the producer's or the auditor's own limit."""
    with monkeypatch.context() as m:
        m.setattr(cert2, "TRANSCEND_OPS", frozenset({"add"}))
        m.setattr(cert2, "_mpmath_version", lambda: None)
        got = refused("definition-unavailable", audit_mk, mk)
        assert (got.run, got.segment) == (0, 1)
        refused("replay-undecided", make_markstep)
        assert cert2.runtime_text(True).endswith(",mpmath-none")

    def capped(self, values, steps):
        raise transcend.ZivEscalation("forced to its cap")
    with monkeypatch.context() as m:
        m.setattr(cert2.Definition, "lane", capped)
        got = refused("definition-unavailable", audit_mk, mk)
        assert "precision cap" in got.message
        got = refused("definition-unavailable", audit_lz, lz,
                      define={0: [1]})
        assert (got.run, got.segment) == (0, 1)
        refused("replay-undecided", make_markstep)
    assert not cert2.Definition(mk.graph).needs_mpmath()


# ---- the golden writer's own refusals --------------------------------------------

def test_the_writer_refuses_what_it_cannot_certify(mk, lz):
    g = mk.graph
    refused("replay-lane-flags", cert2.run_chain, mk.img, mk.bank, mk.init,
            3, steps=4, definition=cert2.Definition(g), lane_flags=False)
    refused("replay-source", cert2.run_chain, mk.img, mk.bank, mk.init, 3,
            steps=4)
    lzg = cert2.source_graph(lz.src)
    refused("source-shape", cert2.run_chain, mk.img, mk.bank, mk.init, 3,
            steps=4, definition=cert2.Definition(lzg))
    with pytest.raises(TypeError):
        cert2.run_chain(mk.img, mk.bank, mk.init, 3,
                        definition=cert2.Definition(g))
    # an image that needs flag control asks for the block by default; one
    # that does not, does not
    assert cert2.run_chain(mk.img, mk.bank, mk.init, 1, steps=4,
                           definition=cert2.Definition(g)).lane_flags
    assert not lz.chains[0].lane_flags


def test_the_writer_spells_each_field_or_refuses_it(mk):
    for change in (dict(issuer="unknown"), dict(issuer=""),
                   dict(issuer=5), dict(certificate_id="withheld"),
                   dict(writer=("none", "unknown")),
                   dict(writer=("Golden", "unknown")),
                   dict(device_clock=0), dict(profile=(2, 0)),
                   dict(environment=(("lower", "1"),)),
                   dict(environment=(("CFT_TIMEOUT_MS", ""),)),
                   dict(environment=(("HOME", "/home/x"),)),
                   dict(initial=("generator", "x", ("given",))),
                   dict(initial=("generator", "given", ("x",))),
                   dict(started="2026-10-02 12:00:00")):
        refused("malformed", reencode, mk.data, **change)


# ---- the key tool ------------------------------------------------------------------

def _tool(*args):
    r = subprocess.run([sys.executable, str(ROOT / "python" / "cft_sign.py")]
                       + [str(a) for a in args], capture_output=True,
                       text=True, timeout=120)
    return r.returncode, r.stdout, r.stderr


def test_the_key_tool(tmp_path, full):
    key = tmp_path / "test.key"
    rc, out, err = _tool("keygen", "--out", key)
    assert rc == 0, err
    pub = out.strip()
    assert re.fullmatch(r"[0-9a-f]{64}", pub)
    rows = key.read_text().splitlines()
    assert rows[3] == f"key {pub}"
    assert rows[2].split(" ")[1] not in out
    rc, out, err = _tool("keygen", "--out", key)
    assert rc == 73 and "refused output" in err
    rc, out, _ = _tool("public", "--key", key)
    assert out.strip() == pub
    c = tmp_path / "c.cert"
    c.write_bytes(full.data)
    rc, out, err = _tool("sign", "--key", key, "--cert", c)
    assert rc == 0, err
    sig = (tmp_path / "c.cert.sig").read_bytes()
    assert cert2.read_signature_file(sig)[0] == pub
    # the certificate names the test key, so another key is signature-key
    rc, out, err = _tool("verify", "--cert", c)
    assert rc == 4 and "refused signature-key" in err
    rc, out, err = _tool("sign", "--key", key, "--cert", c)
    assert rc == 73
    # the published test key, in a key file
    tk = tmp_path / "published.key"
    tk.write_text(f"cft-signing-key 1\nscheme ed25519\nseed "
                  f"{TEST_SEED.hex()}\nkey {TEST_KEY}\n", newline="\n")
    os.chmod(tk, 0o600)         # owner-only, which POSIX checks
    rc, out, err = _tool("sign", "--key", tk, "--cert", c, "--out",
                         tmp_path / "t.sig")
    assert rc == 0, err
    assert (tmp_path / "t.sig").read_bytes() == full.sig
    ring = tmp_path / "ring"
    ring.write_bytes(full.ring)
    rc, out, err = _tool("verify", "--cert", c, "--sig", tmp_path / "t.sig",
                         "--keyring", ring)
    assert rc == 0 and f"held by {cert2.text_token(TEST_ISSUER)}" in out, err
    bad = bytearray(full.sig)
    bad[-3] ^= 1
    (tmp_path / "bad.sig").write_bytes(bytes(bad))
    rc, out, err = _tool("verify", "--cert", c, "--sig", tmp_path / "bad.sig")
    assert rc == 4 and "refused signature" in err
    (tmp_path / "junk.key").write_text("seed 00\n")
    rc, out, err = _tool("public", "--key", tmp_path / "junk.key")
    assert rc == 64 and "refused usage" in err
    rc, out, err = _tool("frobnicate")
    assert rc == 64
    # sign signs a certificate the strict reader reads, nothing else: bytes
    # with a good hash line are refused by the reader's name
    junk = tmp_path / "junk.cert"
    body = b"not a certificate\n"
    junk.write_bytes(body + b"hash " + hashlib.sha256(body).hexdigest()
                     .encode("ascii") + b"\n")
    rc, out, err = _tool("sign", "--key", key, "--cert", junk)
    name = err.split("refused ", 1)[1].split(":", 1)[0]
    assert rc == cert.REFUSALS[name] and rc != 0, err
    assert not (tmp_path / "junk.cert.sig").exists()


def test_the_key_tool_refuses_a_key_file_others_may_read(tmp_path,
                                                         monkeypatch):
    """On a POSIX system a key file its group or others may read or write
    is refused (`usage`). Here the check is forced on, so that Windows,
    which does not check (its permissions are ACLs), runs it too."""
    import cft_sign
    k = tmp_path / "loose.key"
    k.write_text(cft_sign.key_text(TEST_SEED), newline="\n")
    os.chmod(k, 0o644)
    monkeypatch.setattr(cft_sign, "_POSIX", True)
    with pytest.raises(cft_sign.Stop) as ei:
        cft_sign.read_key(k)
    assert ei.value.name == "usage" and "chmod 600" in ei.value.why


# ---- the page's example and test vectors -----------------------------------------

def _doc():
    return (ROOT / "docs" / "CERTIFICATES.md").read_text(encoding="utf-8")


def _fenced_after(marker):
    text = _doc()
    at = text.index(marker)
    m = re.search(r"```[a-z]*\n(.*?)```", text[at:], re.S)
    return m.group(1)


EXAMPLE_PROVENANCE = cert2.Provenance(
    profile="2", language="1", device_platform="none", device_xrt="none",
    device_clock="none", device_serial="none", writer=("golden", "unknown"),
    writer_runtime="unknown", compiler_build="none",
    replay_methods=((0, "golden"),), issuer="withheld", issuer_key="none")


def example_certificate_v2():
    """The page's version-2 example, from its recipe: markstep, open, every
    measured header line `unknown`, and the counter's drift over the
    lanes - the golden corpus's markstep-fp64 case."""
    x = make_markstep(provenance=EXAMPLE_PROVENANCE)
    probe = cert.Entry("drift", "measurement", 0, None,
                       cert.Value("exact", exact=Fraction(0)), "counter",
                       ((Fraction(1), (0,)),))
    q = cert.derive(probe, (x.run,), [(F64, 2)],
                    {(0, 0): x.chain.states[0], (0, 3): x.chain.states[-1]})
    e = dataclasses.replace(probe, value=cert.make_value(q))
    data = cert2.encode(dataclasses.replace(x.cert, accuracy=(e,)))
    return x, data


def test_the_pages_version_2_example_is_what_the_writer_writes():
    x, data = example_certificate_v2()
    shown = _fenced_after("<!-- the version-2 example certificate -->")
    assert shown.encode("ascii") == data, (
        "docs/CERTIFICATES.md's version-2 example is not what cert2.py "
        "writes for its recipe; regenerate it from "
        "test_cert2.example_certificate_v2()")
    v = cert.audit(data, None, {0: (x.img, x.bank)},
                   states={0: {0: x.init}}, sources={0: x.src})
    assert "run 0 replays: 2 lanes in 1 segment replayed by the definition, " \
           "each matched" in v.lines()
    assert "accuracy entry 0: re-derived as c/1 - the value is the stated " \
           "function of the certified runs; that an estimate estimates " \
           "well is not shown" in v.lines()
    # the prose's reading of it
    doc = " ".join(_doc().split())
    assert "replay 1 marked 2 changed 1" in shown
    assert "the drift is exactly 12 (`c/1`)" in doc
    assert "segment 1 raised 17 and STATUS 64" in doc


def rfc2104(key, msg):
    """HMAC-SHA-256 from RFC 2104 with hashlib alone."""
    block = 64
    key = key + bytes(block - len(key))
    inner = hashlib.sha256(bytes(k ^ 0x36 for k in key) + msg).digest()
    return hashlib.sha256(bytes(k ^ 0x5C for k in key) + inner).hexdigest()


def test_the_pages_version_2_test_vectors():
    rows = dict(ln.split(None, 1) for ln in _fenced_after(
        "<!-- the version-2 test vectors -->").strip().split("\n"))
    assert len(rows) == 11
    salt = bytes.fromhex(rows["salt"])
    assert salt == SALT
    block = bytes.fromhex(rows["lane-flags-bytes"])
    tag = b"cft-certificate 2 lane-flags\x00"
    assert rows["lane-flags-hash"] == cert2.lane_flags_hash(salt, block) \
        == rfc2104(salt, tag + block)
    assert rows["open-lane-flags-hash"] == cert2.lane_flags_hash(None, block) \
        == hashlib.sha256(tag + block).hexdigest()
    seed = bytes.fromhex(rows["test-seed"])
    assert seed == TEST_SEED and rows["test-key"] == TEST_KEY
    assert rows["body-hash"] == hashlib.sha256(b"cft-certificate 2\n") \
        .hexdigest()
    msg = bytes.fromhex(rows["signed-message"])
    assert msg == b"cft-signature 1\x00" + bytes.fromhex(rows["body-hash"]) \
        == cert2.signature_message(rows["body-hash"])
    sig = bytes.fromhex(rows["signature"])
    assert sig == ed25519.sign(seed, msg)
    assert ed25519.verify(bytes.fromhex(rows["test-key"]), msg, sig)
    assert rows["text-token"] == cert2.text_token(rows["text"]) \
        == "Logan%20W."


# ---- the page's table ---------------------------------------------------------------

def test_version_2s_names_are_in_the_one_table():
    v2 = {"marked", "replay-lane-flags", "replay-source", "replay-method",
          "provenance-order", "signature-format", "signature",
          "signature-key", "signer", "supersedes", "source-digest",
          "source-refused", "source-format", "source-graph", "source-param",
          "source-shape", "source-image", "source-missing",
          "lane-flags-shape", "lane-flags-hash", "initial-state",
          "lane-flags-identity", "aux-source", "segment-lane-flags",
          "replay-missing", "replay-unmarked", "replay-raw",
          "replay-changed", "definition-end", "definition-flags",
          "definition-differs", "definition-unavailable",
          "compiler-differs", "replay-undecided"}
    assert v2 <= set(cert.REFUSALS)
    assert {cert.REFUSALS[n] for n in v2} <= {2, 4, 5, 6, 78}
    assert all(cert.REFUSALS[n] == 78 for n in (
        "definition-differs", "definition-unavailable", "compiler-differs",
        "replay-undecided"))
