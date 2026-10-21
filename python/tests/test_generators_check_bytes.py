# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""A generator's --check compares BYTES, so a CRLF copy fails it (KL-609).

Four generators check a committed file against a fresh generation:
python/gen_divfull.py, python/gen_seq_flags.py, hw/gen_layouts.py (the
.cfg files and the table in docs/LAYOUTS.md) and
bindings/node/make_seq_corpus.py. Each used to read the file with
`read_text`, which folds CRLF to LF, so a copy an editor had saved with
CRLF compared equal to the generated text and the check passed it. The
writers write LF (`newline="\\n"`), and `.gitattributes` makes a checkout
LF, so a CRLF file is something a tool or an editor wrote - and the one
case the check exists to see.

Each test is the same three steps on a scratch copy, never on the tree:
the generated text written with LF (the check passes: the control, which
says the failure below is the line ends and nothing else), the same text
written with CRLF (the check fails, by name, and says CRLF), and, where
the file has more than one part, each part alone.

host/tools/gen_2opi.py and host/tools/gen_mp_consts.py read their file the
same way and are not covered here: host/ is not this test's to change.
"""

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "python"))

import gen_divfull  # noqa: E402
import gen_seq_flags  # noqa: E402


def _crlf(data: bytes) -> bytes:
    assert b"\r" not in data
    return data.replace(b"\n", b"\r\n")


def _load(relpath: str, name: str):
    """A script of the tree that is not on the import path, as a module."""
    spec = importlib.util.spec_from_file_location(name, ROOT / relpath)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_gen_divfull_check_sees_a_crlf_header(tmp_path, monkeypatch, capsys):
    header = tmp_path / "host" / "src" / "divfull_images.h"
    header.parent.mkdir(parents=True)
    monkeypatch.setattr(gen_divfull, "ROOT", tmp_path)
    monkeypatch.setattr(gen_divfull, "HEADER", header)
    want = gen_divfull.render().encode("utf-8")

    header.write_bytes(want)                    # the control: LF passes
    assert gen_divfull.main(["--check"]) == 0
    capsys.readouterr()

    header.write_bytes(_crlf(want))             # the same text, CRLF
    assert gen_divfull.main(["--check"]) == 1
    out = capsys.readouterr().out
    assert "STALE" in out and "CRLF" in out, out   # verify/run.sh reads STALE


def test_gen_seq_flags_check_sees_a_crlf_header(tmp_path, monkeypatch, capsys):
    header = tmp_path / "cft_seq_flags.h"
    monkeypatch.setattr(gen_seq_flags, "HEADER", header)
    want = gen_seq_flags.render().encode("utf-8")

    header.write_bytes(want)
    assert gen_seq_flags.main(["--check"]) == 0
    capsys.readouterr()

    header.write_bytes(_crlf(want))
    assert gen_seq_flags.main(["--check"]) == 1
    err = capsys.readouterr().err
    assert "drifted" in err and "CRLF" in err, err


def test_gen_layouts_check_sees_a_crlf_cfg_and_a_crlf_doc(
        tmp_path, monkeypatch, capsys):
    gl = _load("hw/gen_layouts.py", "p6_gen_layouts")
    hw = tmp_path / "hw"
    hw.mkdir()
    doc = tmp_path / "docs" / "LAYOUTS.md"
    doc.parent.mkdir(parents=True)
    doc.write_bytes(b"# Layouts\n\nprose\n<!-- layouts:begin -->\n"
                    b"<!-- layouts:end -->\nmore prose\n")
    monkeypatch.setattr(gl, "HW", hw)
    monkeypatch.setattr(gl, "OUT", hw / "layouts")

    assert gl.main([]) == 0                     # write: the cfgs and the table
    cfgs = sorted((hw / "layouts").glob("u50-*.cfg"))
    assert cfgs and b"layouts:begin" in doc.read_bytes()
    assert b"\r" not in doc.read_bytes() + cfgs[0].read_bytes()
    assert gl.main(["--check"]) == 0            # the control
    capsys.readouterr()

    lf_cfg = cfgs[0].read_bytes()               # one .cfg, CRLF
    cfgs[0].write_bytes(_crlf(lf_cfg))
    assert gl.main(["--check"]) == 1
    out = capsys.readouterr().out
    assert "STALE: " + cfgs[0].name in out, out
    cfgs[0].write_bytes(lf_cfg)
    assert gl.main(["--check"]) == 0
    capsys.readouterr()

    lf_doc = doc.read_bytes()                   # the doc, CRLF throughout
    doc.write_bytes(_crlf(lf_doc))
    assert gl.main(["--check"]) == 1
    out = capsys.readouterr().out
    assert "STALE: LAYOUTS.md" in out, out
    # and the writer puts it right: LF again, the table as it was
    assert gl.main([]) == 0
    assert doc.read_bytes() == lf_doc
    assert gl.main(["--check"]) == 0


def test_make_seq_corpus_check_sees_a_crlf_corpus(tmp_path, monkeypatch, capsys):
    # The generator drives libcft through ctypes; its verdict on the file is
    # check_committed(), which needs the text and the file and no library.
    msc = _load("bindings/node/make_seq_corpus.py", "p6_make_seq_corpus")
    corpus = tmp_path / "seq_corpus.jsonl"
    monkeypatch.setattr(msc, "OUT", corpus)
    text = '{"kind": "cft sequencer corpus"}\n{"case": 1}\n{"case": 2}\n'
    want = text.encode("utf-8")

    corpus.write_bytes(want)
    assert msc.check_committed(text, 2) == 0
    capsys.readouterr()

    corpus.write_bytes(_crlf(want))
    assert msc.check_committed(text, 2) == 1
    out = capsys.readouterr().out
    assert "differs from a fresh generation" in out and "CRLF" in out, out

    corpus.unlink()                             # absent is still refused
    assert msc.check_committed(text, 2) == 1


def test_make_seq_corpus_main_hands_its_check_to_check_committed():
    """main() cannot run without libcft, so the verdict above would be a
    function nothing calls if main() stopped calling it: hold the call."""
    import ast
    tree = ast.parse((ROOT / "bindings" / "node" / "make_seq_corpus.py")
                     .read_text(encoding="utf-8"))
    main = next(n for n in tree.body
                if isinstance(n, ast.FunctionDef) and n.name == "main")
    calls = [c.func.id for c in ast.walk(main)
             if isinstance(c, ast.Call) and isinstance(c.func, ast.Name)]
    assert "check_committed" in calls
    # and main() no longer reads the corpus itself, in text mode or any other
    attrs = [c.func.attr for c in ast.walk(main)
             if isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute)]
    assert "read_text" not in attrs and "read_bytes" not in attrs
