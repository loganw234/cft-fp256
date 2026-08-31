# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""The committed seed ROM must be exactly what the model generates.

rtl/cft_seed_rom.svh is a build input, so it is committed - and a
committed generated file is a transcription waiting to happen. This
regenerates the content from the model and compares byte-for-byte, so
the ROM cannot drift from the specification without failing CI.
"""

import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import gen_seed_rom  # noqa: E402

ROM = Path(__file__).resolve().parents[2] / "rtl" / "cft_seed_rom.svh"


def test_rom_matches_model():
    assert ROM.exists(), "run python/gen_seed_rom.py"
    committed = io.open(ROM, encoding="utf-8").read()
    assert committed == gen_seed_rom.render(), (
        "rtl/cft_seed_rom.svh drifted from the model - regenerate with "
        "python/gen_seed_rom.py (and ask why it changed)")
