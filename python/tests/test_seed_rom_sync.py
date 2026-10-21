# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""The committed seed ROM must be exactly what the model generates.

rtl/cft_seed_rom.svh is a build input, so it is committed - and a
committed generated file is a transcription waiting to happen. This
regenerates the content from the model and compares byte-for-byte, so
the ROM cannot drift from the specification without failing CI.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import gen_seed_rom  # noqa: E402

ROM = Path(__file__).resolve().parents[2] / "rtl" / "cft_seed_rom.svh"


def same_bytes(path, text):
    """Whether `path` holds exactly `text`, as UTF-8, byte for byte. Not a
    text-mode read: that folds CRLF to LF, so a copy saved with CRLF
    compared equal to the generated text and this test, which says
    byte-for-byte, could not see it (KL-609)."""
    return path.read_bytes() == text.encode("utf-8")


def test_rom_matches_model():
    assert ROM.exists(), "run python/gen_seed_rom.py"
    assert same_bytes(ROM, gen_seed_rom.render()), (
        "rtl/cft_seed_rom.svh drifted from the model - regenerate with "
        "python/gen_seed_rom.py (and ask why it changed)")


def test_a_crlf_copy_of_the_rom_is_not_the_rom(tmp_path):
    """The comparison above sees line ends: the model's own text, written
    with CRLF, is not the model's text. Control: written with LF it is."""
    text = gen_seed_rom.render()
    assert "\n" in text and "\r" not in text
    lf, crlf = tmp_path / "lf.svh", tmp_path / "crlf.svh"
    lf.write_bytes(text.encode("utf-8"))
    crlf.write_bytes(text.replace("\n", "\r\n").encode("utf-8"))
    assert same_bytes(lf, text)
    assert not same_bytes(crlf, text)
