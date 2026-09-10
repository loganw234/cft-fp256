# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""host/tools/serial_replay.py's own pieces.

The harness is checked end to end by the loopback census and by its
negative-control battery (`--loopback --corrupt`), which are the runs
that matter and which need a compiled binary. These are the parts that
do not: the frame, the checksum, the refusals, and the order the sets
are walked in.

They are here rather than in host/tests because this is the repository's
pytest suite and `make golden` runs it. Nothing here imports
cft_golden, and nothing here needs a compiler - except the last test,
which uses the loopback binary if it has been built and skips itself by
name if it has not. A test that quietly checked nothing would be worse
than an absent one, so it says which.
"""

import importlib.util
import os
import subprocess
import sys

import pytest

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
TOOL = os.path.join(REPO, "host", "tools", "serial_replay.py")


def _load():
    spec = importlib.util.spec_from_file_location("serial_replay", TOOL)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


sr = _load()


# ---- the checksum ---------------------------------------------------
#
# CRC-16/CCITT-FALSE. The device computes the same value in
# bindings/arduino/cft-arduino/src/cft_replay.c, bitwise where this one
# is table-driven, so the two implementations are checked against the
# standard's own vector and then against each other by every case the
# loopback replays.

def test_crc16_reference_vector():
    # The check value every CRC-16/CCITT-FALSE catalogue lists.
    assert sr.crc16(b"123456789") == 0x29B1


def test_crc16_seed_and_emptiness():
    assert sr.crc16(b"") == 0xFFFF
    # A one-bit change anywhere changes it.
    assert sr.crc16(b"a") != sr.crc16(b"b")
    a = b">01 run fp64 rne fma 0000000000000000 0000000000000000 0"
    b = b">01 run fp64 rne fma 0000000000000000 0000000000000001 0"
    assert sr.crc16(a) != sr.crc16(b)


# ---- the frame ------------------------------------------------------

def _frame(seq, body):
    head = (">%02x %s" % (seq, body)).encode("ascii")
    return head + (" *%04x" % sr.crc16(head)).encode("ascii")


def _resp(seq, body):
    head = ("<%02x %s" % (seq, body)).encode("ascii")
    return head + (" *%04x" % sr.crc16(head)).encode("ascii")


def test_parse_accepts_a_well_formed_response():
    rseq, status, fields = sr.Link._parse(_resp(0x2A, "ok 3f800000 10"))
    assert rseq == 0x2A
    assert status == "ok"
    assert fields == ["3f800000", "10"]


def test_parse_rejects_a_wrong_checksum():
    good = _resp(1, "ok 3f800000 10")
    bad = good[:-1] + (b"0" if good[-1:] != b"0" else b"1")
    with pytest.raises(sr.ProtocolError):
        sr.Link._parse(bad)


def test_parse_rejects_a_damaged_body_under_an_old_checksum():
    good = _resp(1, "ok 3f800000 10")
    # Change the answer, leave the checksum: this is the `bits`
    # corruption mode with the CRC left stale, and it must not parse.
    bad = good.replace(b"3f800000", b"3f800001")
    with pytest.raises(sr.ProtocolError):
        sr.Link._parse(bad)


@pytest.mark.parametrize("line", [
    b"",
    b"<01 ok",
    b"<01 ok 3f800000 10",            # no checksum at all
    b"<zz ok 3f800000 10 *0000",      # sequence is not hex
    b"<01 ok 3f800000 10 *zzzz",      # checksum is not hex
])
def test_parse_rejects_malformed_frames(line):
    with pytest.raises(sr.ProtocolError):
        sr.Link._parse(line)


# ---- the field readers ----------------------------------------------

def test_elem_reads_the_set_files_spelling():
    assert sr._elem({"a": "0x007fffff"}, "a", 4) == "007fffff"
    assert sr._elem({"a": "0X00FFFFFF"}, "a", 4) == "00ffffff"


@pytest.mark.parametrize("bad,nbytes", [
    ({"a": "007fffff"}, 4),        # no 0x
    ({"a": "0x007fff"}, 4),        # too few digits
    ({"a": "0x007fffffff"}, 4),    # too many
    ({"a": 42}, 4),                # not a string
])
def test_elem_refuses_anything_else(bad, nbytes):
    with pytest.raises(ValueError):
        sr._elem(bad, "a", nbytes)


# ---- set discovery --------------------------------------------------
#
# The order is host/src/conformance.c's, and it is not cosmetic: a
# report that walks the sets in a different order than cft-selftest's
# cannot be read beside one.

def _touch(d, name):
    with open(os.path.join(d, name + ".jsonl"), "w") as fh:
        fh.write("")


def test_discovery_order_and_kinds(tmp_path):
    d = str(tmp_path)
    for n in ("fp64-rtz", "fp32", "fp32-transcend", "fp32-augmented",
              "fp32-reduce", "fp32-character", "fp32-minmaxmag",
              "fp32-to-fp64-formatof", "fp64"):
        _touch(d, n)
    got = [(os.path.basename(p)[:-6], k) for p, k, _ in sr.discover(d)]
    assert got == [
        ("fp32", "elementwise"),
        ("fp32-transcend", "transcend"),
        ("fp32-augmented", "augmented"),
        ("fp32-reduce", "reduce"),
        ("fp32-character", "character"),
        ("fp32-minmaxmag", "minmaxmag"),
        ("fp64", "elementwise"),
        ("fp64-rtz", "elementwise"),
        ("fp32-to-fp64-formatof", "formatof"),
    ]


def test_discovery_carries_both_formats_for_a_formatof_set(tmp_path):
    d = str(tmp_path)
    _touch(d, "fp128-to-fp32-formatof-rmm")
    (path, kind, meta), = sr.discover(d)
    assert kind == "formatof"
    assert meta["fmt"] == "fp128" and meta["dfmt"] == "fp32"


def test_discovery_of_an_empty_directory_is_empty(tmp_path):
    assert sr.discover(str(tmp_path)) == []


# ---- every kind of set has a verb -----------------------------------

def test_every_discovered_kind_names_a_verb(tmp_path):
    d = str(tmp_path)
    for n in ("fp32", "fp32-transcend", "fp32-augmented", "fp32-reduce",
              "fp32-character", "fp32-minmaxmag", "fp32-to-fp32-formatof"):
        _touch(d, n)
    for _, kind, _ in sr.discover(d):
        assert kind in sr.KIND_VERB, kind


# ---- end to end, if the loopback has been built ---------------------

def _loopback():
    base = os.path.join(REPO, "bindings", "arduino", "loopback",
                        "cft-replay-loopback-full")
    for cand in (base + ".exe", base):
        if os.path.exists(cand):
            return cand
    return None


@pytest.mark.skipif(_loopback() is None,
                    reason="no loopback binary; "
                           "make -C bindings/arduino/loopback")
def test_loopback_replays_a_subset_and_the_control_catches_a_lie():
    exe = _loopback()
    vec = os.path.join(REPO, "vectors", "out")
    if not os.path.isdir(vec):
        pytest.skip("no vectors/out; make vectors")

    def run(*extra):
        return subprocess.run(
            [sys.executable, TOOL, "--loopback", exe,
             "--sets", "fp32", "--limit", "50"] + list(extra),
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)

    ok = run()
    assert ok.returncode == 0, ok.stdout
    assert "50 cases" in ok.stdout and "all matching" in ok.stdout

    # The same fifty cases against a loopback that answers one of them
    # wrongly. A harness that passed this would be worthless.
    # --loopback-arg=X rather than --loopback-arg X: argparse reads a
    # value that begins with -- as the next OPTION otherwise, and every
    # argument being passed through here does.
    lied = subprocess.run(
        [sys.executable, TOOL, "--loopback", exe,
         "--loopback-arg=--corrupt", "--loopback-arg=bits",
         "--loopback-arg=--corrupt-verb", "--loopback-arg=run",
         "--sets", "fp32", "--limit", "50"],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    assert lied.returncode != 0, lied.stdout
    assert "CONFORMANCE FAILED" in lied.stdout


# ---- the board's readings -------------------------------------------
#
# `env` answers the responder's three counters and then whatever the
# board's hook added as key=value tokens. The harness reads it at the
# start and every 2,000 cases so a long run can be laid against the
# board's temperature and heap (the ESP32-S3's throughput decayed
# steadily from 62,000 cases on, 2026-09-09).

def test_parse_env_reads_counters_and_tokens():
    d = sr.parse_env(["12", "11", "1", "temp=41.5", "heap=298000",
                      "up=1234", "odd"])
    assert d == {"lines": "12", "ok": "11", "err": "1", "temp": "41.5",
                 "heap": "298000", "up": "1234", "odd": ""}


def test_parse_env_wants_the_three_counters():
    with pytest.raises(sr.ProtocolError):
        sr.parse_env(["12", "11"])


def test_env_brief_names_only_temperature_and_heap():
    assert sr.env_brief({"lines": "1", "ok": "1", "err": "0"}) == ""
    assert sr.env_brief({"temp": "41.5", "heap": "298000", "up": "9"}) \
        == ", 41.5 C, heap 298000"
    assert sr.env_brief({"heap": "1500"}) == ", heap 1500"


def test_report_remembers_first_last_and_extremes():
    rep = sr.Report()
    rep.env_seen({})
    assert rep.env_first is None and sr.env_summary(rep) == ""
    rep.env_seen({"lines": "0", "ok": "0", "err": "0", "temp": "38.0",
                  "heap": "300000"})
    rep.env_seen({"lines": "9", "ok": "9", "err": "0", "temp": "53.1",
                  "heap": "299000"})
    rep.env_seen({"lines": "20", "ok": "19", "err": "1", "temp": "52.4",
                  "heap": "299000"})
    assert (rep.temp_min, rep.temp_max) == (38.0, 53.1)
    line = sr.env_summary(rep)
    assert "38.0 C at the start and 52.4 C at the end" in line
    assert "max 53.1" in line
    assert "300000 bytes at the start and 299000 at the end" in line
    assert "1 request refused by the board" in line


@pytest.mark.skipif(_loopback() is None,
                    reason="no loopback binary; "
                           "make -C bindings/arduino/loopback")
def test_loopback_trace_has_a_header_and_a_first_row(tmp_path):
    exe = _loopback()
    vec = os.path.join(REPO, "vectors", "out")
    if not os.path.isdir(vec):
        pytest.skip("no vectors/out; make vectors")
    trace = tmp_path / "trace.csv"
    run = subprocess.run(
        [sys.executable, TOOL, "--loopback", exe, "--sets", "fp32",
         "--limit", "50", "--trace", str(trace)],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    assert run.returncode == 0, run.stdout
    rows = trace.read_text(encoding="utf-8").splitlines()
    assert rows[0] == ("cases,elapsed_s,rate_last_2000,rate_overall,"
                       "temp_c,heap_bytes,up_ms,lines,ok,err")
    assert len(rows) >= 2 and rows[1].startswith("0,0.0,0.0,0.0,")
    # A loopback built with `env` fills the counters; an older one
    # leaves the row's tail empty. Either is a row, not a failure.
    tail = rows[1].split(",")[7:]
    assert tail == ["", "", ""] or all(t.isdigit() for t in tail)

