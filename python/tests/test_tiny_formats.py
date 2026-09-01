# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""Exhaustive clause-5 sweeps on tiny formats, against ref754.

The model is format-generic, so 8-bit formats buy something the ladder
cannot: EXHAUSTIVENESS. Every encoding through every operation under
every attribute, and every pair through the binary operations, checked
against the independent Fraction oracle - whole failure families that
sampling on fp32 would have to get lucky to hit cost fractions of a
second here. This file is the 2026-09-01 adversarial review's tiny
sweep (which found the ladder clean) promoted to a standing gate.

Three shapes on purpose:

  e4m3  (bias 7)   the balanced case
  e5m2  (bias 15)  wide exponent, thin significand
  e3m4  (bias 3)   emax < p-1: OUTSIDE the ladder's envelope, kept to
                   exercise the model's documented ladder-scoped
                   asserts (round_int can be asked for an integer the
                   format cannot hold; the oracle agrees the value has
                   no encoding, and the test accepts exactly that
                   pairing). The sequences' staging preconditions
                   (emax >= p) also fail here, so seqs are ladder+
                   e4m3/e5m2 only.

These are NOT interchange formats and NOT contract surface - nothing
here changes what the tile promises. They are a microscope.
"""

import bisect
import sys
from fractions import Fraction as F

import pytest

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent))

from cft_golden.formats import FpFormat  # noqa: E402
from cft_golden import softfloat as sf  # noqa: E402
from cft_golden.sequences import rint_seq, scaleb_seq  # noqa: E402
import ref754 as orc  # noqa: E402
from ref754 import Fmt, dec, MODES  # noqa: E402

E4M3 = (FpFormat("e4m3", 4, 3), Fmt(4, 3), True)
E5M2 = (FpFormat("e5m2", 5, 2), Fmt(5, 2), True)
E3M4 = (FpFormat("e3m4", 3, 4), Fmt(3, 4), False)   # emax < p-1
TINY = (E4M3, E5M2, E3M4)
IDS = [t[0].name for t in TINY]


@pytest.mark.parametrize("mf,of,seqs", TINY, ids=IDS)
def test_round_int_exhaustive(mf, of, seqs):
    for x in range(1 << of.width):
        for rnd in MODES:
            for exact in (False, True):
                want = orc.ref_round_int(of, x, rnd, exact)
                try:
                    got = sf.round_int(mf, x, rnd, exact)
                except AssertionError:
                    # the ladder-scoped assert: acceptable exactly when
                    # the oracle also finds no encoding for the integer
                    assert want[0] is None, (mf.name, hex(x), rnd)
                    continue
                assert got == want, (mf.name, hex(x), rnd, exact, got, want)
                if seqs:
                    assert rint_seq(mf, x, rnd, exact) == got, \
                        (mf.name, hex(x), rnd, exact)


@pytest.mark.parametrize("mf,of,seqs", TINY, ids=IDS)
def test_scaleb_exhaustive(mf, of, seqs):
    lo_n = of.emin - of.man_w
    ns = list(range(lo_n - 4, 3 * of.emax + 6)) + [10 ** 4, -(10 ** 4)]
    for x in range(1 << of.width):
        for n in ns:
            for rnd in MODES:
                want = orc.ref_scaleb(of, x, n, rnd)
                got = sf.scaleb(mf, x, n, rnd)
                assert got == want, (mf.name, hex(x), n, rnd, got, want)
                if seqs:
                    assert scaleb_seq(mf, x, n, rnd) == got, \
                        (mf.name, hex(x), n, rnd)


@pytest.mark.parametrize("mf,of,seqs", TINY, ids=IDS)
def test_logb_classify_exhaustive(mf, of, seqs):
    for x in range(1 << of.width):
        want = orc.ref_logb(of, x)
        try:
            got = sf.logb(mf, x)
        except AssertionError:
            # the ladder-scoped exactness assert (|E| needs more
            # significand than a thin-p format has): acceptable exactly
            # when the oracle also finds no encoding for E
            assert want[0] is None, (mf.name, hex(x))
        else:
            assert got == want, (mf.name, hex(x), got, want)
        k = dec(of, x)
        if k[0] == "nan":
            cw = sf.CLASS_QNAN if k[2] else sf.CLASS_SNAN
        elif k[0] == "inf":
            cw = sf.CLASS_NEG_INF if k[1] else sf.CLASS_POS_INF
        elif k[2] == 0:
            cw = sf.CLASS_NEG_ZERO if k[1] else sf.CLASS_POS_ZERO
        elif ((x >> of.man_w) & of.exp_mask) == 0:
            cw = sf.CLASS_NEG_SUB if k[1] else sf.CLASS_POS_SUB
        else:
            cw = sf.CLASS_NEG_NORM if k[1] else sf.CLASS_POS_NORM
        assert sf.classify(mf, x) == cw, (mf.name, hex(x))


@pytest.mark.parametrize("mf,of,seqs", TINY, ids=IDS)
def test_next_exhaustive(mf, of, seqs):
    """Ground truth by VALUE ENUMERATION: sort every finite value the
    format holds and step through the sorted list - an implementation
    of 5.3.1 that never touches the encoding's ordering trick."""
    vals = sorted({dec(of, x)[2] for x in range(1 << of.width)
                   if dec(of, x)[0] == "num"})
    for x in range(1 << of.width):
        k = dec(of, x)
        got = sf.next_up(mf, x)
        if k[0] == "nan":
            want = (of.qnan(), 0 if k[2] else 1)
        elif k[0] == "inf":
            want = (x, 0) if k[1] == 0 else (of.maxfin_bits(1), 0)
        elif k[2] == 0:
            want = (1, 0)                       # +min_subnormal
        else:
            i = bisect.bisect_right(vals, k[2])
            if i == len(vals):
                want = (of.inf(0), 0)
            elif vals[i] == 0:
                want = (of.zero(1), 0)          # nextUp(-minsub) = -0
            else:
                want = (orc.enc_exact(of, vals[i]), 0)
        assert got == want, (mf.name, "up", hex(x), got, want)

        gd = sf.next_down(mf, x)
        if k[0] == "nan":
            wd = (of.qnan(), 0 if k[2] else 1)
        elif k[0] == "inf":
            wd = (x, 0) if k[1] else (of.maxfin_bits(0), 0)
        elif k[2] == 0:
            wd = (of.zero(1) | 1, 0)            # -min_subnormal
        else:
            i = bisect.bisect_left(vals, k[2])
            if i == 0:
                wd = (of.inf(1), 0)
            elif vals[i - 1] == 0:
                wd = (of.zero(0), 0)            # nextDown(+minsub) = +0
            else:
                wd = (orc.enc_exact(of, vals[i - 1]), 0)
        assert gd == wd, (mf.name, "down", hex(x), gd, wd)


@pytest.mark.parametrize("mf,of,seqs", TINY, ids=IDS)
def test_int_conversions_exhaustive(mf, of, seqs):
    for x in range(1 << of.width):
        for width, signed in ((5, True), (5, False), (9, True), (9, False)):
            for rnd in MODES:
                for exact in (False, True):
                    got = sf.to_int(mf, x, width, signed, rnd, exact)
                    want = orc.ref_to_int(of, x, width, signed, rnd, exact)
                    assert got == want, \
                        (mf.name, hex(x), width, signed, rnd, exact)
    for v in list(range(-70, 71)) + [255, -255, 256, 1023, 4096,
                                     2 ** 20, -(2 ** 20),
                                     2 ** 40 + 3, -(2 ** 40) - 3]:
        for rnd in MODES:
            assert sf.from_int(mf, v, rnd) == orc.ref_from_int(of, v, rnd), \
                (mf.name, v, rnd)


@pytest.mark.parametrize("mf,of,seqs", TINY, ids=IDS)
def test_pairs_exhaustive(mf, of, seqs):
    """Every pair of encodings through remainder, totalOrder(+Mag) and
    the signaling comparisons."""
    onep, zerop = sf.one_bits(mf), sf.zero_bits(mf)
    smask = of.sign_mask
    n = 1 << of.width
    for x in range(n):
        x_nan = sf.is_nan(mf, x)
        for y in range(n):
            assert sf.remainder(mf, x, y) == orc.ref_remainder(of, x, y), \
                (mf.name, "rem", hex(x), hex(y))
            want = onep if orc.ref_total_order(of, x, y) else zerop
            assert sf.total_order(mf, x, y) == (want, 0), \
                (mf.name, "torder", hex(x), hex(y))
            wm = onep if orc.ref_total_order(of, x & ~smask, y & ~smask) \
                else zerop
            assert sf.total_order_mag(mf, x, y) == (wm, 0), \
                (mf.name, "tordermag", hex(x), hex(y))
            anynan = 1 if (x_nan or sf.is_nan(mf, y)) else 0
            for q, s in ((sf.cmplt, sf.cmplt_sig), (sf.cmple, sf.cmple_sig),
                         (sf.cmpeq, sf.cmpeq_sig)):
                qb, _ = q(mf, x, y)
                sb, sfl = s(mf, x, y)
                assert sb == qb and sfl == anynan, \
                    (mf.name, q.__name__, hex(x), hex(y))


CONVERT_PAIRS = [
    ((4, 3), (5, 2)),      # balanced -> wide exponent (narrower p)
    ((5, 2), (4, 3)),
    ((4, 3), (3, 4)),      # into the sub-ladder shape and back
    ((3, 4), (4, 3)),
]


@pytest.mark.parametrize("src,dst", CONVERT_PAIRS,
                         ids=[f"e{a[0]}m{a[1]}-e{b[0]}m{b[1]}"
                              for a, b in CONVERT_PAIRS])
def test_convert_exhaustive(src, dst):
    mfs = FpFormat("s", src[0], src[1])
    mfd = FpFormat("d", dst[0], dst[1])
    ofs, ofd = Fmt(*src), Fmt(*dst)
    for x in range(1 << ofs.width):
        for rnd in MODES:
            got = sf.convert(mfs, mfd, x, rnd)
            want = orc.ref_convert(ofs, ofd, x, rnd)
            assert got == want, (hex(x), rnd, got, want)
