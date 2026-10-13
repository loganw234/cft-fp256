# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""The transcendental pools' signed thresholds (parcel PS; profile 3.1).

The two unary transcendental pools - vectors.transcend_unary_pool, which the
published sets are made from, and host/tests/transcend_check.unary_pool, which
the libcft stage replays - hold the exponential's overflow and underflow
edges: n ln2 for eight n (emax, emax + 1, emin, emin - man_w, emin - man_w - 1,
-(p + 2), -(p + 3), p + 1), rounded to nearest even and walked two ulps either
way. Five of the eight n are negative. Through profile 3 both pools lost the
sign of each of the five: they took the mantissa from mpmath.libmp.to_man_exp,
which returns it UNSIGNED by default (mpmath 1.3; 1.4 deprecates that
default), and tested its sign, which is never negative. They held +|n| ln2
where -|n| ln2 was meant, so exp's underflow edges (emin ln2 and (emin - p)
ln2 among them) were in no exp-family pool (exp, expm1, exp2, log, log1p,
log2, log10) and in none of those functions' published sets.

Profile 3.1 adds the 25 signed images to each pool and keeps every image the
pools held, so no recorded case moves; and the four generators (the two unary
pools, the two hyperbolic) read the mpf's raw tuple, (sign, mantissa,
exponent, bit count), and call to_man_exp nowhere, so the published sets do
not change with the version of mpmath that makes them. This file holds that:

  signed        each pool, at every format, holds the signed image of each of
                the five negative n and its neighbours at +-1 and +-2 ulps
  fp64          the same for the example the brief names, with the encodings
                written out: -1022 ln2 is 0xc086232bdd7abcd2, and +1022 ln2
                is still there
  kept          each pool still holds the positive image of every one of the
                eight n; and, less the 25 signed images, each pool is bit for
                bit the pool of profile 3 (a digest of its structured part,
                extra = 0, MEASURED at bcf36ac)
  hyperbolic    the two hyperbolic pools hold both signs of the magnitude
                |n| ln2 and of its neighbours for their five n, and are bit
                for bit the pools of profile 3 (digests, as above): their sets
                were always right, and their code now says what it does
  mpmath        no file under python/ or host/tests/ names to_man_exp in code
                (an AST scan, comments and docstrings aside); and the four
                pools, made again with mpmath.libmp.to_man_exp replaced by a
                function that raises, and by one that returns the signed
                mantissa mpmath 1.4's signed=True gives (what a later
                mpmath's default would), equal the pools made with the real
                one: a simulation of another mpmath, not one
  oracle        the expected images are derived here, apart from the pools'
                code: ln2 from mpmath at 8p + 128 bits (the pools use
                4p + 64) as the dyadic it is, the product an exact integer
                product, the sign n's own, the rounding softfloat.round_pack's;
                and pinned against encodings computed by GNU MPFR, which this
                file does not import

The pool functions set mpmath's global precision as they run, so nothing here
reads it: the oracle works at its own, with mpmath.workprec.
"""

import ast
import functools
import hashlib
import importlib.util
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

mpmath = pytest.importorskip("mpmath")

from cft_golden import FP32, FP64, FP128, FP256, vectors  # noqa: E402
from cft_golden import softfloat as sf  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[2]
FORMATS = (FP32, FP64, FP128, FP256)
NEAR = (-2, -1, 0, 1, 2)


def fid(v):
    return v.name


@functools.lru_cache(maxsize=None)
def _transcend_check():
    """host/tests/transcend_check.py as a module (a script of the libcft
    stage, whose pools that stage replays)."""
    spec = importlib.util.spec_from_file_location(
        "pool_signs_transcend_check",
        ROOT / "host" / "tests" / "transcend_check.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _trials(fmt):
    """transcend_check's defaults: --trials 64, and a quarter of that (but
    at least 8) at the two wide formats."""
    return 64 if fmt.width <= 64 else 16


# The pool functions, each as the place that uses it calls it: the published
# sets (gen_vectors.py --transcend 24 at its seed 3, which transcend_cases
# hands on as 3 + 6 = 9 to the unary pool and 9 + 6 = 15 to the hyperbolic
# one) and the libcft stage (--trials 64, --seed 5). `extra` is the number of
# random patterns, which the digest pins leave out (extra = 0).
def _unary(which, fmt, extra=None):
    if which == "vectors":
        return vectors.transcend_unary_pool(
            fmt, 24 if extra is None else extra, 9)
    return _transcend_check().unary_pool(
        fmt, _trials(fmt) if extra is None else extra, 5)


def _hyper(which, fmt, extra=None):
    if which == "vectors":
        return vectors.hyperbolic_unary_pool(
            fmt, 24 if extra is None else extra, 15)
    return _transcend_check().hyper_pool(
        fmt, _trials(fmt) if extra is None else extra, 5)


@functools.lru_cache(maxsize=None)
def unary_pool(which, fmt, extra=None):
    return frozenset(_unary(which, fmt, extra))


@functools.lru_cache(maxsize=None)
def hyper_pool(which, fmt, extra=None):
    return frozenset(_hyper(which, fmt, extra))


# ---- the expected images, derived apart from the pools -----------------------

@functools.lru_cache(maxsize=None)
def _ln2(p):
    """ln 2 at 8p + 128 bits as the (mantissa, exponent) of the dyadic it is."""
    with mpmath.workprec(8 * p + 128):
        sign, man, ex, _bc = mpmath.log(2)._mpf_
    assert sign == 0 and man > 0
    return int(man), int(ex)


def threshold(fmt, n):
    """n ln2 rounded to nearest even into fmt, as an encoding. The sign is
    n's own and the magnitude |n| man 2^ex an exact integer product, so the
    answer is round_pack's of an exact value, signed."""
    man, ex = _ln2(fmt.prec)
    return sf.round_pack(fmt, 1 if n < 0 else 0, abs(n) * man, ex,
                         sf.RND_RNE)[0]


def exp_edges(fmt):
    """The eight n of the unary pools' exponential edges."""
    p = fmt.prec
    return (fmt.emax, fmt.emax + 1, fmt.emin, fmt.emin - fmt.man_w,
            fmt.emin - fmt.man_w - 1, -(p + 2), -(p + 3), p + 1)


def hyper_edges(fmt):
    """The five n of the hyperbolic pools' overflow edges."""
    return (fmt.emax, fmt.emax + 1, fmt.emax + 2, fmt.emin,
            fmt.emin - fmt.man_w)


def signed_images(fmt):
    """The 25 images profile 3.1 adds: the five negative n, signed, each
    with its neighbours at +-1 and +-2 ulps."""
    return {threshold(fmt, n) + d for n in exp_edges(fmt) if n < 0
            for d in NEAR}


def positive_images(fmt):
    """The images every profile held: |n| ln2 for all eight n (for a negative
    n this is the mirror of the signed image), with its neighbours."""
    return {threshold(fmt, abs(n)) + d for n in exp_edges(fmt) for d in NEAR}


def digest(values):
    h = hashlib.sha256()
    h.update(",".join(f"{v:x}" for v in sorted(values)).encode())
    return h.hexdigest()


# MEASURED at bcf36ac (profile 3, before this parcel), by an independent
# script over an export of that commit: the encodings GNU MPFR gives for
# emin ln2 and (emin - p) ln2, the two underflow edges of exp, each from a
# working value at 8p + 128 and 16p + 256 bits and agreeing with mpmath at
# 6p + 100.
MPFR_EMIN_LN2 = {
    "fp32": 0xc2aeac50,
    "fp64": 0xc086232bdd7abcd2,
    "fp128": 0xc00c62d918ce2421d65ff90ac8f4ce66,
    "fp256": 0xc001062e37e7d8ba721881a1b9d4c544de96b8b374559a20af9c25deca4aa000,
}
MPFR_EMIN_MINUS_P_LN2 = {
    "fp32": 0xc2cff1b4,
    "fp64": 0xc0874910d52d3052,
    "fp128": 0xc00c654bb3b2c73ebb059fabb506ff34,
    "fp256": 0xc00106335a1cda3ddc011ec209132f62bbd62bb56d5f437570572b2010bb94fe,
}

# MEASURED at bcf36ac: the sha256 of the sorted encodings (lower-case hex,
# comma-joined) of each pool at extra = 0. The unary two are the pools of
# profile 3, which held none of the signed images; the hyperbolic two have
# these digests at bcf36ac and after the edit of their code. A change to a
# pool that is not a step of the profile fails here, by pool and format; a
# step of the profile restates the digests, as it restates
# vectors/SHA256SUMS.
UNARY_DIGESTS = {
    ("vectors", "fp32"): "937f99c00d449e86a2bfc03a5db31ee32cbb5791e84e3542bd5c0fe32a28254e",
    ("check", "fp32"): "b7c15de7a5f0e435f0ab0d6a5e114cdecfb01adab3610fe4f2987f5fb3dce9f1",
    ("vectors", "fp64"): "53edcd6e06243c6f7a14f1dfe4c73c18263a34c60237e2af773200c2187f84c9",
    ("check", "fp64"): "3d15df94c88c09c614847d89d3f0ba1b7f6be0076f19c351fd25b6e590e3ba22",
    ("vectors", "fp128"): "7278033011d076e09df39ee195ad94eecd5433e5af78e01b1e4ebced81052ba6",
    ("check", "fp128"): "b8cd69c97c64afc968d6bfcee6f9f0415d4dec2ab3a74dc4ca7c077d8e43d2c0",
    ("vectors", "fp256"): "9b46b734228f946c6bb27b73ad2145ef56e83f9f4d650a2953359626cae5b807",
    ("check", "fp256"): "993dfd843d2460389b6eea354bc98e63d01164d5160fe541c51ec0d0390868a0",
}
HYPER_DIGESTS = {
    ("vectors", "fp32"): "21e1070d8b90bd9aea3900454a0106e8bc030d1d61e7dd71adbe55c813f51f4a",
    ("check", "fp32"): "3b1323fc689fb5f15c4117610b304ff9c8af5c788cde6564f1e4db78b26ba63b",
    ("vectors", "fp64"): "c2b53f84dbe6193f84e5a680abdc06839df559c1aee38d4f580cf4ac44285ea8",
    ("check", "fp64"): "5e71eb4060860c6aa3cabcf69c037d06cf6d99ccafdf398cc8a68e5976104706",
    ("vectors", "fp128"): "8cef47af20f19520703cca32a912d550846e46f42cbab6d67baf50f653ab5507",
    ("check", "fp128"): "5731e495bf091185839785e473743a21a428e86d824c1bbd9bedbe1b1232658e",
    ("vectors", "fp256"): "db5756116433187cbc869a9a3bdfabb977fd4d7a9e210e52ff8b9393dbe37f2a",
    ("check", "fp256"): "8a8b0448450c60fdd055d69b6e12722f472669767cf84cd2b1f0eb6698c9ab46",
}

WHICH = ("vectors", "check")


# ---- the oracle itself --------------------------------------------------------

@pytest.mark.parametrize("fmt", FORMATS, ids=fid)
def test_the_derived_underflow_edges_are_the_encodings_mpfr_gives(fmt):
    """emin ln2 and (emin - p) ln2, the two underflow edges of exp, from the
    derivation this file uses, equal the encodings MPFR gave, and are
    negative: so a derivation that lost the sign could not pass."""
    for n, want in ((fmt.emin, MPFR_EMIN_LN2[fmt.name]),
                    (fmt.emin - fmt.prec,
                     MPFR_EMIN_MINUS_P_LN2[fmt.name])):
        got = threshold(fmt, n)
        assert got == want, (fmt.name, n, hex(got), hex(want))
        assert got & fmt.sign_mask
        assert threshold(fmt, -n) == got & ~fmt.sign_mask


def test_the_five_negative_thresholds_and_their_images_are_what_is_counted():
    """Five of the eight n are negative, so 25 signed images a pool; the
    positive images are 40, 15 of them the positive n's own; none is shared."""
    for fmt in FORMATS:
        ns = exp_edges(fmt)
        assert len(ns) == 8 and sum(n < 0 for n in ns) == 5
        signed, pos = signed_images(fmt), positive_images(fmt)
        assert len(signed) == 25 and len(pos) == 40
        assert not signed & pos
        assert all(x & fmt.sign_mask for x in signed)
        assert not any(x & fmt.sign_mask for x in pos)


# ---- the unary pools ----------------------------------------------------------

@pytest.mark.parametrize("fmt", FORMATS, ids=fid)
@pytest.mark.parametrize("which", WHICH)
def test_each_unary_pool_holds_the_signed_image_of_every_negative_threshold(
        which, fmt):
    pool = unary_pool(which, fmt)
    missing = []
    for n in exp_edges(fmt):
        if n < 0:
            b = threshold(fmt, n)
            missing += [(n, d) for d in NEAR if b + d not in pool]
    assert not missing, (
        f"{which} unary pool at {fmt.name} lacks the signed image of "
        f"n ln2 (n, ulps from the rounded value): {missing}")
    assert signed_images(fmt) <= pool


@pytest.mark.parametrize("fmt", FORMATS, ids=fid)
@pytest.mark.parametrize("which", WHICH)
def test_each_unary_pool_keeps_the_positive_image_of_every_threshold(
        which, fmt):
    """The images profile 3 held stay: for a negative n the mirror |n| ln2,
    which a repair that only read the sign would have removed."""
    pool = unary_pool(which, fmt)
    missing = [(n, d) for n in exp_edges(fmt) for d in NEAR
               if threshold(fmt, abs(n)) + d not in pool]
    assert not missing, (
        f"{which} unary pool at {fmt.name} lacks the positive image of "
        f"|n| ln2 (n, ulps): {missing}")
    assert positive_images(fmt) <= pool


@pytest.mark.parametrize("which", WHICH)
def test_the_fp64_pools_hold_minus_1022_ln2_with_neighbours_and_plus_1022_ln2(
        which):
    """The case the brief names, with the encodings written out. -1022 ln2 is
    -708.396..., the argument at which exp reaches 2^emin, and it was in no
    pool; +1022 ln2 was in both and is."""
    pool = unary_pool(which, FP64)
    minus, plus = 0xc086232bdd7abcd2, 0x4086232bdd7abcd2
    assert minus == MPFR_EMIN_LN2["fp64"] and plus == minus ^ FP64.sign_mask
    for d in NEAR:
        assert minus + d in pool, (which, d)
        assert plus + d in pool, (which, d)


@pytest.mark.parametrize("fmt", FORMATS, ids=fid)
@pytest.mark.parametrize("which", WHICH)
def test_each_unary_pool_less_its_signed_images_is_the_pool_of_profile_3(
        which, fmt):
    """Every case profile 3 held stays and nothing else is added but the 25
    signed images: the structured part of the pool (extra = 0), less those
    images, has the digest MEASURED at bcf36ac (where the pool held none of
    them, so this holds at bcf36ac too)."""
    pool = unary_pool(which, fmt, 0)
    assert digest(pool - signed_images(fmt)) == UNARY_DIGESTS[(which, fmt.name)]


# ---- the hyperbolic pools -----------------------------------------------------

@pytest.mark.parametrize("fmt", FORMATS, ids=fid)
@pytest.mark.parametrize("which", WHICH)
def test_each_hyperbolic_pool_holds_both_signs_of_each_magnitude_threshold(
        which, fmt):
    pool = hyper_pool(which, fmt)
    missing = []
    for n in hyper_edges(fmt):
        b = threshold(fmt, abs(n))
        for d in NEAR:
            for x in (b + d, (b + d) | fmt.sign_mask):
                if x not in pool:
                    missing.append((n, d, hex(x)))
    assert not missing, (
        f"{which} hyperbolic pool at {fmt.name} lacks (n, ulps, encoding): "
        f"{missing}")


@pytest.mark.parametrize("fmt", FORMATS, ids=fid)
@pytest.mark.parametrize("which", WHICH)
def test_each_hyperbolic_pool_is_the_pool_of_profile_3(which, fmt):
    pool = hyper_pool(which, fmt, 0)
    assert digest(pool) == HYPER_DIGESTS[(which, fmt.name)]


# ---- the pools do not depend on mpmath's version ---------------------------------

def _python_files():
    for sub in ("python", "host/tests"):
        for path in sorted((ROOT / sub).rglob("*.py")):
            if "__pycache__" not in path.parts:
                yield path


def test_no_code_under_python_or_host_tests_names_to_man_exp():
    """mpmath.libmp.to_man_exp returns the mantissa unsigned by default in
    1.3 and deprecates that default in 1.4 (CI's 64 DeprecationWarnings at
    ad7c409, one for each of the old pool generators' calls), so a pool that
    called it would change with the version of mpmath that made it, and the
    published sets with the pool. The four generators read the mpf's raw
    tuple, whose mantissa is unsigned in every mpmath, and nothing under
    python/ or host/tests/ names the function in code - no call, no
    reference, no import. (Comments and docstrings, which an AST does not
    hold as names, may speak of it.)"""
    found = []
    for path in _python_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), str(path))
        for node in ast.walk(tree):
            named = ((isinstance(node, ast.Name) and node.id == "to_man_exp")
                     or (isinstance(node, ast.Attribute)
                         and node.attr == "to_man_exp")
                     or (isinstance(node, ast.alias)
                         and node.name == "to_man_exp"))
            if named:
                where = f"{path.relative_to(ROOT).as_posix()}:"
                found.append(where + str(getattr(node, "lineno", "?")))
    assert not found, (
        "mpmath's to_man_exp is named in code, where its default (unsigned "
        "in 1.3, deprecated in 1.4) would move the published vector sets "
        "with the mpmath that generates them; read the raw tuple, "
        f"`sign, man, ex, _bc = x._mpf_`, instead: {found}")


def _raising_to_man_exp(raw):
    raise AssertionError("a pool generator called mpmath.libmp.to_man_exp")


def _signed_to_man_exp(raw):
    """What mpmath 1.4's to_man_exp(raw, signed=True) returns, and what its
    default would give once the unsigned default is gone: the mantissa with
    the mpf's sign on it. Written from the raw tuple, not from mpmath's own
    function."""
    sign, man, ex, _bc = raw
    return (-man if sign else man), ex


def _all_four_pools():
    """Every pool this file holds, made again (not from the caches): the two
    unary and the two hyperbolic, from the vector sets' generators and the
    libcft stage's, at every format, at the counts of the places that use
    them."""
    return {(kind, which, fmt.name): sorted(make(which, fmt))
            for kind, make in (("unary", _unary), ("hyper", _hyper))
            for which in WHICH for fmt in FORMATS}


@pytest.mark.parametrize("stub", (_raising_to_man_exp, _signed_to_man_exp),
                         ids=("raises", "signed"))
def test_the_pools_are_the_same_whatever_mpmath_to_man_exp_does(
        stub, monkeypatch):
    """A simulation of another mpmath, not one: with mpmath.libmp.to_man_exp
    (and its definition's module) replaced, first by a function that raises
    and then by one that returns the signed mantissa, all sixteen pools are
    made again and equal the pools made with the real function. The pool
    generators therefore never reach it. (Run against bcf36ac's generators
    this fails both ways: they call it, and under the signed convention the
    positive images of the negative thresholds become the signed ones.)"""
    from mpmath import libmp
    want = _all_four_pools()
    monkeypatch.setattr(libmp, "to_man_exp", stub)
    monkeypatch.setattr(libmp.libmpf, "to_man_exp", stub, raising=False)
    got = _all_four_pools()
    assert got.keys() == want.keys() and len(got) == 16
    for key in want:
        assert got[key] == want[key], key
