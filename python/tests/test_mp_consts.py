# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""host/src/mp_consts.h is what the generator says it is.

A hand-typed constant has been wrong in this project three times, and a
wrong one HERE would not crash - it would return a plausible number
with a silently wrong low bit. So the header is generated, and this
regenerates it and compares, on every test run.

The second half is independent of the generator: it re-derives each
constant from mpmath directly, from the limbs the committed header
actually carries, and checks the truncation is toward zero and by less
than one unit in the last place. That catches a generator that is
itself wrong, which comparing the generator against its own output
cannot.
"""

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
HEADER = ROOT / "host" / "src" / "mp_consts.h"
SCRIPT = ROOT / "host" / "tools" / "gen_mp_consts.py"

mpmath = pytest.importorskip("mpmath")


def test_header_matches_the_generator():
    r = subprocess.run([sys.executable, str(SCRIPT), "--check"],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr


def _parse():
    """The committed header, as {name: (integer significand, exponent)}."""
    text = HEADER.read_text()
    bits = int(text.split("#define CFT_MP_CONST_BITS")[1].split()[0])
    limbs = int(text.split("#define CFT_MP_CONST_LIMBS")[1].split()[0])
    out = {}
    for name in ("ln2", "log2e", "ln10", "log10e"):
        exp = int(text.split(f"#define CFT_MP_{name.upper()}_EXP (")[1]
                  .split(")")[0])
        body = text.split(f"cft_mp_{name}_limbs[CFT_MP_CONST_LIMBS] = {{")[1]
        body = body.split("};")[0]
        vals = [int(tok.strip().rstrip("u"), 16)
                for tok in body.replace("\n", "").split(",") if tok.strip()]
        assert len(vals) == limbs, (name, len(vals))
        m = 0
        for i, v in enumerate(vals):
            m |= v << (32 * i)
        out[name] = (m, exp, bits)
    return out


def test_constants_are_the_true_values_truncated():
    """Each stored value is the true constant truncated toward zero at
    exactly CFT_MP_CONST_BITS bits - never rounded, never above."""
    table = {
        "ln2": lambda: mpmath.log(2),
        "log2e": lambda: 1 / mpmath.log(2),
        "ln10": lambda: mpmath.log(10),
        "log10e": lambda: 1 / mpmath.log(10),
    }
    for name, (m, exp, bits) in _parse().items():
        assert m.bit_length() == bits, name
        mpmath.mp.prec = bits + 128
        true = table[name]()
        stored = mpmath.ldexp(mpmath.mpf(m), exp)
        assert stored <= true, name                    # never above
        assert true - stored < mpmath.ldexp(mpmath.mpf(1), exp), name


def test_the_reciprocal_relations_hold():
    """The same two products the C self-check multiplies at runtime."""
    t = _parse()
    for a, b in (("ln2", "log2e"), ("ln10", "log10e")):
        ma, ea, bits = t[a]
        mb, eb, _ = t[b]
        mpmath.mp.prec = 4 * bits
        prod = (mpmath.ldexp(mpmath.mpf(ma), ea) *
                mpmath.ldexp(mpmath.mpf(mb), eb))
        assert abs(prod - 1) < mpmath.ldexp(mpmath.mpf(1), -(bits - 4))
