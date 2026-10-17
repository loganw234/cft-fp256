# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""The compiler's own claims, at the level of the golden model.

The compiler (python/cftc) is held to the language's interpreter by the
`lang` runner stage (programs/lang_check.py): every image it writes is
run on seq.py against lang.run, bit for bit. These are the smaller facts
that argument rests on, cheap enough for the golden stage:

* the one fold is an identity of the golden model: fma(c, -t, z) and
  fma(flip(c), t, z) - flip being the sign-bit inversion - give the same
  bits and flags, as do the multiplicands swapped and mul, for every
  special as c, t and z, under all five attributes, at all four formats;
  and RN(-c) in place of flip(c) is NOT one (the plant the gate keeps);
* sharing's commutations: + and * and fma's multiplicands;
* the targets, the refusal names (the language's one list), the
  manifest's shape, asm.py's round trip, the internal check refusing a
  damaged image, and the command line's exits - a source whose
  canonical form would not read back refused by name, exit 3, never 70;
* revision 8's three targets (parcel E; built in at cftc's output version
  5, parcel TG): each held to its image's words - rev8a's as the card read
  them, the quad's and the deep single's the plan's - seen by get(),
  names(), the command line and accepted_by, compiling C4's routines, and
  refusing one slot past its depth by name;
* the variational equations: an image with tangent vectors run as
  lang.run runs it, its lane block and manifest, the interleaved
  candidate offered only with tangents, scratch-capacity naming the
  tangent's slots;
* the math library's six as routines (M1's build, item 4; cftc's output
  version 6): every source the interim `math-library` refused compiles,
  for sw and revision 8's targets, refused `target-feature` without flag
  control and `routine-unavailable` without mpmath, and runs on seq.py as
  lang.run runs it, an unmarked lane bit for bit and a marked lane a
  guess; a structured centre marked through the image's RAISE; the
  primal-only values of the six's rules once a call; a call loop of the
  six; the internal check holding their routines and every fragment to
  its routine's statement; the bank counting their words; and a fold, in
  the source or in a run value, compiling as its constant.
"""

import hashlib
import json
import random
import subprocess
import sys
from fractions import Fraction
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "python"))

import cftc                                      # noqa: E402
from cftc import callloop                        # noqa: E402
from cftc import check as cftc_check             # noqa: E402
from cftc import targets as T                    # noqa: E402
from cft_golden import FORMATS, asm, lang, seq   # noqa: E402
from cft_golden import routines as R             # noqa: E402
from cft_golden import softfloat as sf           # noqa: E402
from cft_golden.lang import constants as K       # noqa: E402
from lang_mathform import NO_MPMATH, have_mpmath  # noqa: E402

SYSTEMS = ROOT / "programs" / "systems"
# revision 8's three targets, built in at cftc's output version 5
REV8 = ("u50-rev8", "u50-rev8-quad", "u50-rev8-deep")


def specials(fmt):
    """Eighteen encodings: each of nine kinds with both signs - zero, the
    smallest and the largest subnormal, the smallest normal, one, the
    largest finite, infinity, a quiet NaN and a signalling NaN, both
    NaNs with payloads."""
    one = fmt.bias << fmt.man_w
    top = ((fmt.exp_mask - 1) << fmt.man_w) | fmt.man_mask
    inf = fmt.exp_mask << fmt.man_w
    vals = [0, 1, fmt.man_mask, 1 << fmt.man_w, one, top, inf,
            inf | (1 << (fmt.man_w - 1)) | 5, inf | 3]
    return vals + [v | fmt.sign_mask for v in vals]


@pytest.mark.parametrize("name", list(FORMATS))
def test_the_fold_is_an_identity_at_every_special(name):
    """2.3's argument, exhaustively over the specials: same bits, same
    flags, five attributes, both multiplicand positions, fma and mul."""
    fmt = FORMATS[name]
    sp = specials(fmt)
    flip = fmt.sign_mask
    for rnd in range(5):
        for c in sp:
            fc = c ^ flip
            for t in sp:
                nt = t ^ flip
                assert sf.mul(fmt, c, nt, rnd) == sf.mul(fmt, fc, t, rnd)
                assert sf.mul(fmt, nt, c, rnd) == sf.mul(fmt, t, fc, rnd)
                for z in sp:
                    assert sf.fma(fmt, c, nt, z, rnd) == \
                        sf.fma(fmt, fc, t, z, rnd), (rnd, c, t, z)
                    assert sf.fma(fmt, nt, c, z, rnd) == \
                        sf.fma(fmt, t, fc, z, rnd), (rnd, c, t, z)


@pytest.mark.parametrize("name", list(FORMATS))
def test_the_fold_is_an_identity_on_random_encodings(name):
    fmt = FORMATS[name]
    rng = random.Random(1789 + fmt.width)
    flip = fmt.sign_mask
    top = 1 << fmt.width
    for _ in range(400):
        c, t, z = (rng.randrange(top) for _ in range(3))
        rnd = rng.randrange(5)
        assert sf.fma(fmt, c, t ^ flip, z, rnd) == \
            sf.fma(fmt, c ^ flip, t, z, rnd)
        assert sf.mul(fmt, c, t ^ flip, rnd) == \
            sf.mul(fmt, c ^ flip, t, rnd)


def test_rn_of_minus_c_is_not_the_fold():
    """Why the slot holds the flip: under rdn and rup the rounding of -c is
    not the negation of c's rounding when c is inexact (1/100 here), so a
    fold into RN(-c) would change bits - the plant the gate keeps red."""
    fmt = FORMATS["fp64"]
    c = Fraction(1, 100)
    for rnd in (sf.RND_RDN, sf.RND_RUP):
        rn_c, _ = K.round_once(fmt, rnd, c)
        rn_minus_c, _ = K.round_once(fmt, rnd, -c)
        assert rn_minus_c != rn_c ^ fmt.sign_mask
    for rnd in (sf.RND_RNE, sf.RND_RTZ, sf.RND_RMM):
        rn_c, _ = K.round_once(fmt, rnd, c)
        rn_minus_c, _ = K.round_once(fmt, rnd, -c)
        assert rn_minus_c == rn_c ^ fmt.sign_mask


@pytest.mark.parametrize("name", ["fp32", "fp256"])
def test_sharing_commutes_what_the_plan_allows(name):
    """Hash-consing puts the operands of add and mul, and fma's
    multiplicands, in one order: each swap gives the same bits and flags
    (verifier-P1 measured these at scale; this holds the specials)."""
    fmt = FORMATS[name]
    sp = specials(fmt)
    for rnd in range(5):
        for a in sp:
            for b in sp:
                assert sf.add(fmt, a, b, rnd) == sf.add(fmt, b, a, rnd)
                assert sf.mul(fmt, a, b, rnd) == sf.mul(fmt, b, a, rnd)
                for c in sp[::3]:
                    assert sf.fma(fmt, a, b, c, rnd) == \
                        sf.fma(fmt, b, a, c, rnd)


def test_targets_are_stated():
    assert T.names() == ["sw", "u50-rev8", "u50-rev8-quad", "u50-rev8-deep",
                         "u50-rev7", "u50-rev7-quad", "u50-round2",
                         "open-core"]
    assert T.get("u50-rev7").scratch_depth == 2048
    assert T.get("u50-rev7").max_insns == 32768
    assert T.get("u50-round2").scratch_depth == 256
    assert T.get("sw").seq_features == 0x7ff1f
    assert T.get("sw:2048").scratch_depth == 2048
    for bad in ("sw:0", "sw:3", "sw:65536", "sw:0256", "u51"):
        assert T.get(bad) is None
    need = {"BANK_PTR", "SCRATCH", "SCRATCH_IO", "SCRATCH_STRICT", "REGS32",
            "WIDE_CONST", "KX9"}
    for t in T.BUILTIN.values():
        assert need <= set(t.features()), t.name


def _every_feature_image():
    """An image needing every feature asm.py's features() can name: kx and
    KX9 (a constant at index 256), REGS32, BANK_PTR, IMUL, SCRATCH and
    SCRATCH_IO, and revision 8's AUGADD, SCRATCH_STEP and FLAG_CONTROL."""
    consts = "".join(f".const K{i}\n" for i in range(257))
    return asm.assemble_image(
        ".format fp64\n.deposits 1\n.bank external\n.scratch in 1\n"
        + consts + "add r1, K256, r2\nimul r17, r1, r2\nstl r1, 0\n"
        "augadd r3, r1, r2\nstx r1, r2, -1\nquiet\nraise r4\nendquiet\n"
        "halt\n", "every-feature")


def test_revision_8s_bits_are_published_by_sw_and_revision_8s_targets():
    """Revision 8's four bits (ABI 0.17, cft.h): the software targets
    publish them, as libcft's software handle does (0x7ff1f), and so do
    revision 8's single and deep single; the quad publishes all but
    AUGADD, being built without R21; no revision-7 or older target
    publishes any. So an image needing FLAG_CONTROL (R24), like one
    needing SCRATCH_STEP, is accepted by `sw` and revision 8's three, and
    one needing AUGADD by `sw`, the single and the deep single alone."""
    r8 = {"AUGADD": "CAPS2[11]", "SCRATCH_STEP": "CAPS2[12]",
          "LANE_FLAGS": "CAPS2[13]", "FLAG_CONTROL": "CAPS2[14]"}
    for name, place in r8.items():
        assert T.CAPS_PLACE[name] == place
        assert T.get("sw").seq_features & T.FEATURE_BITS[name]
        assert T.get("sw:2048").seq_features & T.FEATURE_BITS[name]
        for t in ("u50-rev8", "u50-rev8-deep"):
            assert name in T.get(t).features(), (t, name)
        assert (name in T.get("u50-rev8-quad").features()) == \
            (name != "AUGADD"), name
        for t in ("u50-rev7", "u50-rev7-quad", "u50-round2", "open-core"):
            assert name not in T.get(t).features(), (t, name)
    assert T.FEATURE_BITS["LANE_FLAGS"] == 1 << 17
    assert T.FEATURE_BITS["FLAG_CONTROL"] == 1 << 18
    from cftc import manifest as M
    for feats in (["FLAG_CONTROL"], ["SCRATCH_STEP"],
                  ["FLAG_CONTROL", "LANE_FLAGS"]):
        assert M.accepted_by("fp64", feats, 10, 0) == ["sw", *REV8], feats
    assert M.accepted_by("fp64", ["AUGADD"], 10, 0) == \
        ["sw", "u50-rev8", "u50-rev8-deep"]
    assert M.accepted_by("fp64", ["AUGADD", "FLAG_CONTROL"], 10, 0) == \
        ["sw", "u50-rev8", "u50-rev8-deep"]
    assert M.accepted_by("fp64", ["SCRATCH_STRICT"], 10, 0) == T.names()


def test_every_feature_asm_names_is_a_target_bit():
    """The compiler takes an image's needs from asm.py's features(), keeps
    those FEATURE_BITS names, and refuses what a target lacks (cftc's
    target-feature). A name asm.py reports and FEATURE_BITS lacks would be
    dropped there, and the image accepted where its loader refuses it - so
    every one maps, FLAG_CONTROL among them."""
    img = _every_feature_image()
    feats = img.features()
    assert feats == ["kx", "REGS32", "BANK_PTR", "KX9", "IMUL", "SCRATCH",
                     "SCRATCH_IO", "AUGADD", "SCRATCH_STEP", "FLAG_CONTROL"]
    for f in feats:
        name = T.ASM_FEATURE.get(f, f)
        assert name in T.FEATURE_BITS and name in T.CAPS_PLACE, f
    need = [T.ASM_FEATURE.get(f, f) for f in feats]
    assert not [f for f in need if f not in T.get("sw").features()]
    assert [f for f in need if f not in T.get("u50-rev7").features()] == \
        ["AUGADD", "SCRATCH_STEP", "FLAG_CONTROL"]


def test_the_compiler_raises_the_languages_names():
    """One class and one list (the lead's decision): every name the
    compiler raises is in L1's COMPILER_REFUSALS, raised through L1's
    Refusal, and no other name can be."""
    assert set(cftc.NAMES) == set(lang.COMPILER_REFUSALS)
    for name in cftc.NAMES + cftc.refusals.SHARED:
        e = cftc.refusals.refusal(name, "a sentence")
        assert isinstance(e, lang.Refusal) and e.name == name
    # the one catalogue name the compiler raises too: the bank's 512 (C4)
    assert cftc.refusals.SHARED == ("bank-capacity",)
    assert set(cftc.refusals.SHARED) <= set(lang.CATALOGUE)
    for name in ("unused", "runtime-routine"):
        with pytest.raises((cftc.InternalError, AssertionError)):
            cftc.refusals.refusal(name, "not the compiler's")


def _hh():
    return cftc.compile_file(SYSTEMS / "henonheiles-lf-fp64.cftl", 7,
                             source="programs/systems/henonheiles-lf-fp64."
                                    "cftl")


def test_henon_heiles_folds_its_kick_into_the_flip_of_h():
    c = _hh()
    assert len(c.lowered.folds) == 1
    assert [s.kind for s in c.lowered.slots] == ["const", "const", "flip",
                                                  "const", "const"]
    assert c.program.step_counts()["alu"] == 12
    assert len(c.image_obj.insns) == 23
    assert c.lowered.h_slots == [0, 1, 2]
    classic = (ROOT / "programs" / "henonheiles-lf-fp64.classic.bank")
    assert c.bank == classic.read_bytes()


def test_the_manifest_says_what_the_image_is():
    c = _hh()
    m = json.loads(c.manifest_bytes)
    assert list(m)[:4] == ["cftc_manifest", "compiler", "source", "graph"]
    assert m["steps"] == 7 and m["h_slots"] == [0, 1, 2]
    assert m["uses"]["instructions"] == 23
    assert m["per_step"]["alu"] == 12 and m["per_step"]["loads"] == 0
    assert [b["kind"] for b in m["bank"]] == ["const", "const", "flip",
                                              "const", "const"]
    assert m["bank"][2]["flips"] == 0
    assert m["time_shift"][0]["expression"] == "2 RN(h/2) / RN(h) - 1"
    assert m["time_shift"][0]["exact"] == "0"
    assert "u50-round2" in m["accepted_by"]
    assert m["files"]["image"]["sha256"] == \
        __import__("hashlib").sha256(c.image).hexdigest()
    assert c.manifest_bytes.endswith(b"\n") and c.manifest_bytes.isascii()


def test_rk4_time_shift_is_zero_at_fp256_and_not_at_fp64():
    for name, zero in (("lorenz63-rk4-fp64", False),
                       ("lorenz63-rk4-fp256", True)):
        c = cftc.compile_file(SYSTEMS / f"{name}.cftl", 3)
        shift = c.manifest["time_shift"][0]
        assert (shift["exact"] == "0") == zero, (name, shift)


def test_asm_reads_back_what_the_compiler_wrote():
    c = _hh()
    assert asm.assemble(c.cfta) == c.image
    assert asm.assemble(asm.disassemble(c.image)) == c.image


def test_the_internal_check_refuses_a_damaged_image():
    """A control for check.py: one operand register changed in one
    instruction of the step must be caught, and so must a bank slot."""
    c = _hh()
    img = asm.Image.from_bytes(c.image)
    words = list(img.insns)
    k = next(i for i, w in enumerate(words)
             if not asm.decode(w)["ctrl"] and asm.decode(w)["op"] == 0)
    d = asm.decode(words[k])
    words[k] = asm.alu(d["op"], d["rd"], d["ra"], d["rb"] ^ 1, d["rc"],
                       d["rnd"], d["ka"], d["kb"], d["kc"])
    bad = asm.Image(img.fmt, words, img.consts, img.max_deposits, img.flags,
                    scratch_depth=img.scratch_depth,
                    scratch_io=img.scratch_io).to_bytes()
    with pytest.raises(cftc.InternalError):
        cftc_check.verify(c.lowered, c.program, bad, c.steps,
                          c.lowered.half_bits)
    c.lowered.slots[2].bits ^= 1
    with pytest.raises(cftc.InternalError):
        cftc_check.verify(c.lowered, c.program, c.image, c.steps,
                          c.lowered.half_bits)


def test_a_param_run_value_is_read_as_the_language_reads_it():
    c = cftc.compile_file(SYSTEMS / "lorenz63-rk4-fp64.cftl", 3,
                          params={"beta": "8/3", "sigma": "0.1"})
    by_name = {b["name"]: b for b in c.manifest["bank"]}
    assert by_name["sigma"]["exact"] == "1/10"
    assert by_name["sigma"]["encoding"] == "0x3fb999999999999a"
    assert [o["name"] for o in c.manifest["param_overrides"]] == \
        ["sigma", "beta"]
    with pytest.raises(lang.Refusal) as e:
        cftc.compile_file(SYSTEMS / "lorenz63-rk4-fp64.cftl", 3,
                          params={"gamma": "1"})
    assert e.value.name == "unknown-param"
    with pytest.raises(lang.Refusal) as e:
        cftc.compile_file(SYSTEMS / "lorenz63-rk4-fp64.cftl", 3,
                          params={"sigma": "1e400"})
    assert e.value.name == "constant-overflow"
    # the param named, not the one-line system's own name for it ("v")
    assert e.value.sentence.startswith("--param sigma=1e400: sigma's "), \
        e.value.sentence
    # a value naming something names nothing the one-line system declared
    # (it was refused as naming that system's state, x)
    with pytest.raises(lang.Refusal) as e:
        cftc.compile_file(SYSTEMS / "lorenz63-rk4-fp64.cftl", 3,
                          params={"sigma": "x"})
    assert e.value.name == "undefined-name", e.value.sentence
    with pytest.raises(lang.Refusal) as e:
        cftc.compile_file(SYSTEMS / "lorenz63-rk4-fp64.cftl", 3,
                          params={"sigma": "1\nnext x = 0"})
    assert e.value.name == "param-value", e.value.sentence
    # a Python int is exact at any size: str() of it stops at 4,300 digits
    c = cftc.compile_file(SYSTEMS / "lorenz63-rk4-fp256.cftl", 3,
                          params={"sigma": 10 ** 5000})
    o = c.manifest["param_overrides"][0]
    assert K.parse_frac(o["value"]) == 10 ** 5000


@pytest.mark.parametrize("fmt, text, exact", [
    ("fp128", "0.1", Fraction(1, 10)),
    ("fp32", "0x1.000001000000001p+0",
     1 + Fraction(1, 1 << 24) + Fraction(1, 1 << 60))])
def test_a_param_run_value_binary64_would_get_wrong(fmt, text, exact):
    """Values a binary64 route rounds differently - 0.1 at fp128, and at
    fp32 a value whose binary64 rounding is an fp32 tie - so that this
    test, unlike the one above, could catch Python's float in the path."""
    src = (SYSTEMS / "lorenz63-rk4-fp64.cftl").read_bytes().decode("ascii")
    src = src.replace("format fp64", f"format {fmt}")
    c = cftc.compile_text(src, 3, params={"sigma": text})
    slot = next(s for s in c.lowered.slots if s.kind == "param"
                and c.ir.param[s.index][0] == "sigma")
    right = K.round_once(c.ir.fmt, sf.RND_RNE, exact)[0]
    via64 = K.round_once(c.ir.fmt, sf.RND_RNE, Fraction(float(exact)))[0]
    assert right != via64
    assert slot.bits == right


def test_a_renderer_fault_is_an_internal_error(monkeypatch):
    """The intention-out failing is the compiler's defect, never a refusal
    of the source: a renderer that writes text the language refuses, and
    one that writes another system's valid text, both stop the compile
    with InternalError."""
    other = cftc.compile_file(SYSTEMS / "lorenz63-rk4-fp64.cftl", 3).canonical
    monkeypatch.setattr(lang, "render_canonical",
                        lambda g: "system broken\nthis is not a statement\n")
    with pytest.raises(cftc.InternalError) as e:
        _hh()
    assert "intention-out" in str(e.value)
    monkeypatch.setattr(lang, "render_canonical", lambda g: other)
    with pytest.raises(cftc.InternalError) as e:
        _hh()
    assert "not the same step graph" in str(e.value)


def test_a_source_is_taken_as_bytes(tmp_path):
    """A file reaches the language's character rule whole: compile_file
    reads bytes (through lang.load), and compile_text takes a file's bytes
    as lang.compile_text does - so a lone CR is refused, `character`. The
    control is the text-mode read, which turns that CR into a line end
    and hands the language a different, valid system: why bytes."""
    text = b"system cr\nformat fp64\nstate x\rnext x = x + 1\nstep map\n"
    p = tmp_path / "cr.cftl"
    p.write_bytes(text)
    with pytest.raises(lang.Refusal) as e:
        cftc.compile_file(p, 3)
    assert e.value.name == "character"
    with pytest.raises(lang.Refusal) as e:
        cftc.compile_text(p.read_bytes(), 3)
    assert e.value.name == "character"
    with open(p, encoding="ascii") as fh:     # text mode: the CR is gone
        c = cftc.compile_text(fh.read(), 3)
    assert len(c.lowered.nodes) == 1
    good = cftc.compile_file(SYSTEMS / "henonheiles-lf-fp64.cftl", 3,
                             stem="h", source="h.cftl")
    same = cftc.compile_text((SYSTEMS / "henonheiles-lf-fp64.cftl")
                             .read_bytes(), 3, stem="h", source="h.cftl")
    assert same.files() == good.files()


def _long_decimal(seed, digits=5000):
    """(text, exact): 1.ddd...d with `digits` significant digits, the last
    odd and not 5, so its p/q has `digits` digits above and below - read
    here in chunks under Python's limit, not by the language's reader."""
    rng = random.Random(seed)
    body = "".join(rng.choice("0123456789") for _ in range(digits - 2)) + \
        rng.choice("1379")
    n = 0
    whole = "1" + body
    for k in range(0, len(whole), 1000):
        chunk = whole[k:k + 1000]
        n = n * 10 ** len(chunk) + int(chunk)
    return "1." + body, Fraction(n, 10 ** (digits - 1))


_P, _P_EXACT = _long_decimal("p")
_R, _R_EXACT = _long_decimal("r")
BIG = {
    "const": ("system bigconst\nformat fp256\nstate x, y\n"
              "const c = 1e-5000\nnext x = x * c\nnext y = y + c\nstep map\n",
              None),
    "h": ("system bigh\nformat fp256\nstate x\nd/dt x = -x\n"
          "step rk4, h = 1e-4400\n", None),
    "default": (f"system bigdefault\nformat fp256\nstate x\n"
                f"param p = {_P}\nnext x = x * p\nstep map\n", None),
    "run value": ("system bigrun\nformat fp256\nstate x\nparam p = 2\n"
                  "next x = x * p\nstep map\n", {"p": _R}),
}


@pytest.mark.parametrize("case", list(BIG))
def test_values_past_pythons_digit_limit(case):
    """The language reads a literal at any length and holds a constant to
    2^+-1048576, so each of these is a system L1's checker takes - and
    Python's own Fraction() and str() raise ValueError past 4,300 digits,
    which the compiler's reader and manifest once met (verifier-VL2: a
    bare ValueError, exit 1). Each compiles; its manifest writes the
    exact value, read back here by the language's parse_frac; and its
    image equals the interpreter on three lanes."""
    text, params = BIG[case]
    c = cftc.compile_text(text, 3, params=params)
    m = json.loads(c.manifest_bytes)
    bank = {b["name"]: b for b in m["bank"]}
    if case == "const":
        got, want = bank["1e-5000"]["exact"], Fraction(1, 10 ** 5000)
    elif case == "h":
        got, want = m["integrator"]["h"], Fraction(1, 10 ** 4400)
        scaled = [b for b in m["bank"] if b["h_factor"] is not None]
        assert scaled
        for b in scaled:
            assert K.parse_frac(b["exact"]) == \
                K.parse_frac(b["h_factor"]) * want
    elif case == "default":
        got, want = bank["p"]["exact"], _P_EXACT
    else:
        got, want = m["param_overrides"][0]["value"], _R_EXACT
        assert bank["p"]["exact"] == got
    assert len(got) > 4300 and K.parse_frac(got) == want
    fmt = c.ir.fmt
    lanes = [[K.round_once(fmt, sf.RND_RNE, Fraction(v, 7))[0]]
             * c.ir.n_state for v in (3, -11, 100)]
    pb = None if params is None else \
        {"p": next(s.bits for s in c.lowered.slots if s.kind == "param")}
    ref = lang.run(c.graph, lanes, 3, param_bits=pb)
    r = c.run(lanes)
    n = c.ir.n_state
    assert [r.scratch_out[k * c.ir.m:k * c.ir.m + n]
            for k in range(3)] == ref.states
    assert r.flags == ref.flags


def test_the_command_line_takes_a_value_past_the_digit_limit(tmp_path):
    """The const case through the command line: exit 0 and the manifest
    written (it was exit 1, a traceback); and a target `sw:N` whose N is
    past the limit, or not in ASCII digits, is a usage error, 64."""
    src = tmp_path / "bigconst.cftl"
    src.write_bytes(BIG["const"][0].encode("ascii"))
    py = [sys.executable, str(ROOT / "python" / "cftc")]
    r = subprocess.run(py + [str(src), "--steps", "3", "--target", "sw",
                             "--out", str(tmp_path)],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    m = json.loads((tmp_path / "bigconst.manifest.json").read_bytes())
    assert K.parse_frac(m["bank"][0]["exact"]) == Fraction(1, 10 ** 5000)
    for name in ("sw:" + "1" * 5000, "sw:\u00b2", "sw:\u0661\u0666"):
        assert T.get(name) is None
    r = subprocess.run(py + [str(src), "--steps", "3", "--target",
                             "sw:" + "1" * 5000, "--out",
                             str(tmp_path / "x")],
                       capture_output=True, text=True)
    assert r.returncode == 64 and "is not a target" in r.stderr, r.stderr


@pytest.mark.parametrize("name", ["lorenz63-rk4-fp64", "lorenz96-rk4-fp256",
                                  "henonheiles-lf-fp64"])
def test_the_compiler_reads_a_graph_from_its_bytes(name):
    """L1's from_bytes accepts only a graph equal to its canonical form;
    the compiler reads the bytes of every graph it is given, so a graph
    read back from them compiles to the same files."""
    g = lang.load(SYSTEMS / f"{name}.cftl").graph
    back = lang.StepGraph.from_bytes(g.to_bytes())
    a = cftc.compile_graph(g, 4, stem=name).files()
    b = cftc.compile_graph(back, 4, stem=name).files()
    assert a == b


def test_the_command_line(tmp_path):
    py = [sys.executable, str(ROOT / "python" / "cftc")]
    r = subprocess.run(py + ["--targets"], capture_output=True, text=True)
    assert r.returncode == 0 and "u50-rev7" in r.stdout
    src = SYSTEMS / "henonheiles-lf-fp64.cftl"
    r = subprocess.run(py + [str(src), "--steps", "5", "--out",
                             str(tmp_path)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    names = sorted(p.name for p in tmp_path.iterdir())
    assert names == sorted(f"henonheiles-lf-fp64.{x}" for x in (
        "cfta", "cftp", "bank", "half.bank", "manifest.json", "graph.json",
        "canonical.cftl", "math.txt"))
    r = subprocess.run(py + [str(src), "--steps", "0", "--out",
                             str(tmp_path / "x")], capture_output=True,
                       text=True)
    assert r.returncode == 3 and "refused segment-steps" in r.stderr
    assert r.stderr.count("segment-steps") == 1, r.stderr
    assert not (tmp_path / "x").exists()
    r = subprocess.run(py + [str(src)], capture_output=True, text=True)
    assert r.returncode == 64


def _negmul(k):
    e = "x"
    for _ in range(k):
        e = f"-({e}) * y"
    return e


READBACK = {   # name: (source, the refusal, its line)
    # every use of h folds away (the challenge suite's finding 1)
    "h folded away": ("system folded\nformat fp64\nstate x\n"
                      "next x = x + (h - h)\nstep map, h = 1/8\n",
                      "unused", 5),
    # a canonical form 101 deep: a negation used as a multiplicand ...
    "nesting, primal": (f"system deep\nformat fp64\nstate x, y\n"
                        f"next x = {_negmul(51)}\nnext y = y\nstep map\n",
                        "too-deep", 4),
    # ... and the tangent of an unnamed product of 102 terms (verifier-VL3)
    "nesting, tangent": (
        "system deeptan\nformat fp64\nstate "
        + ", ".join(f"x{i}" for i in range(102)) + "\ntangent v\n"
        + "next x0 = " + " * ".join(f"x{i}" for i in range(102)) + "\n"
        + "".join(f"next x{i} = x{i}\n" for i in range(1, 102))
        + "step map\n", "too-deep", 5),
}


def test_the_command_line_refuses_what_would_not_read_back(tmp_path):
    """Each of these was accepted by the language until D2, and stopped
    cftc with exit 70, an internal error, writing nothing: the canonical
    form it rendered did not read back. Each is the language's own refusal
    now - exit 3 with its name and line, nothing written, never 70 - and
    compile_text raises the Refusal, not InternalError."""
    py = [sys.executable, str(ROOT / "python" / "cftc")]
    for k, (name, (text, want, line)) in enumerate(READBACK.items()):
        with pytest.raises(lang.Refusal) as e:
            cftc.compile_text(text, 2)
        assert (e.value.name, e.value.line) == (want, line), name
        src = tmp_path / f"case{k}.cftl"
        src.write_bytes(text.encode("ascii"))
        out = tmp_path / f"out{k}"
        r = subprocess.run(py + [str(src), "--steps", "2", "--out", str(out)],
                           capture_output=True, text=True)
        assert r.returncode == 3, (name, r.returncode, r.stderr)
        assert r.stderr.startswith(f"cftc: refused {want}: "), r.stderr
        assert f"case{k}.cftl:{line}: " in r.stderr, r.stderr
        assert "internal error" not in r.stderr
        assert not out.exists()


def _letchain(n, step="step rk4, h = 1/8"):
    return ("system letchain\nformat fp64\nstate x, y\nlet a1 = x + y\n"
            + "".join(f"let a{j} = a{j - 1} + y\n" for j in range(2, n + 1))
            + f"d/dt x = a{n}\nd/dt y = y\n{step}\n")


def test_the_command_line_compiles_a_chain_of_lets_of_any_length(tmp_path):
    """verifier-VD2's cases/rk4_letchain_81.cftl, rebuilt: rk4 with 81 lets
    was accepted by the language and stopped cftc at exit 70 - its canonical
    form, whose expansion block chains the stages through labels, could not
    be read back within Python's recursion limit. It compiles now, exit 0,
    every file written; so does a chain of 1,000; and a cycle of 300 lets,
    refused too-deep before for the same limit, is refused `cycle`, exit 3.
    Never 70."""
    py = [sys.executable, str(ROOT / "python" / "cftc")]
    cycle = ("system cyc\nformat fp64\nstate x, y\nlet a1 = a300 + y\n"
             + "".join(f"let a{j} = a{j - 1} + y\n" for j in range(2, 301))
             + "next x = a150\nnext y = y\nstep map\n")
    for k, (text, want) in enumerate(((_letchain(81), 0),
                                      (_letchain(1000), 0), (cycle, 3))):
        src = tmp_path / f"chain{k}.cftl"
        src.write_bytes(text.encode("ascii"))
        out = tmp_path / f"out{k}"
        r = subprocess.run(py + [str(src), "--steps", "2", "--target",
                                 "sw:32768", "--out", str(out)],
                           capture_output=True, text=True)
        assert r.returncode == want, (k, r.returncode, r.stderr)
        assert "internal error" not in r.stderr
        if want == 0:
            assert len(list(out.iterdir())) == 8
        else:
            assert r.stderr.startswith("cftc: refused cycle: "), r.stderr
            assert not out.exists()


def test_a_step_count_past_the_digit_limit_is_refused_by_name():
    """segment-steps formatted the count with repr(), so a count past
    Python's 4,300-digit limit raised a bare ValueError (verifier-VI)."""
    src = (SYSTEMS / "lorenz63-rk4-fp64.cftl").read_bytes().decode("ascii")
    with pytest.raises(lang.Refusal) as e:
        cftc.compile_text(src, 10 ** 5000)
    assert e.value.name == "segment-steps"
    assert len(str(e.value)) < 400


# ---- C4: run-time division and square root, inlined as routines --------------
# The language has them (div, sqrt, L4); a tile has no such instruction, and
# cftc inlines each as its routine (cft_golden/routines.py), quiet, then a
# raise of exactly its flags. Such an image needs revision 8's flag control:
# the software targets and revision 8's three compile it, seq.py runs it
# here, and revision 7's targets refuse it `target-feature`, by name - never
# an internal error. These sources were L4's interim refusal's; each now
# compiles.

ROUTINE = {   # name: (source, the first line holding a division or a root)
    "a quotient": ("system d\nformat fp64\nstate x, y\nnext x = x\n"
                   "next y = x / y\nstep map\n", 5),
    "a root": ("system r\nformat fp64\nstate x\nnext x = sqrt(x)\n"
               "step map\n", 4),
    "both, a let, rk4, two vectors": (
        "system b\nformat fp256\nstate x, y\ntangent v, w\n"
        "let s = sqrt(abs(y) + 1)\nd/dt x = y\nd/dt y = -(x / s)\n"
        "step rk4, h = 1/16\n", 5),
    "a quotient by a constant": ("system c\nformat fp32\nstate x\n"
                                 "next x = x / 3\nstep map\n", 4),
    "a quotient by h": ("system m\nformat fp128\nstate x\nnext x = x / h\n"
                        "step map, h = 1/8\n", 4),
    "a division by zero": ("system z\nformat fp64\nstate x\n"
                           "next x = x / (1 - 1)\nstep map\n", 4),
    # verifier-VL4's (b)1: statements come in any order, and a written
    # tangent or an expansion block above the equations holds the first
    # division - refused at the primal's line (7, 8, 9) until the checker
    # handed the compiler its own lines
    "a written tangent first": (
        "system m\nformat fp64\nstate x, y\ntangent v\n"
        "next v.x = fma(-(x / y), v.y, v.x) / y\n"
        "next v.y = v.y / (2 * sqrt(y))\nnext x = x / y\nnext y = sqrt(y)\n"
        "step map\n", 5),
    "a tangent let above its let": (
        "system t\nformat fp64\nstate x, y\ntangent v\n"
        "let v.u = fma(-u, v.y, v.x) / y\nnext v.x = v.u\nnext v.y = v.y\n"
        "let u = x / y\nnext x = u\nnext y = y\nstep map\n", 5),
    "an expansion block first": (
        "system b\nformat fp64\nstate x, y\nstep euler, h = 0.125\n"
        "expansion\n  next x = fma(h, x / ((y * y) + 1), x)\n"
        "  next y = fma(h, -y, y)\nend\nd/dt x = x / ((y * y) + 1)\n"
        "d/dt y = -y\n", 6),
}


def _routine_lanes(g, seed):
    """Lanes for a routine image: rationals, a zero state (0/0, a root of
    0), a signalling NaN, the smallest subnormal - and, with tangent
    vectors, a tangent for each."""
    fmt = g.fmt
    rng = random.Random(seed)

    def val():
        return K.round_once(fmt, sf.RND_RNE,
                            Fraction(rng.randint(-900, 900), 97))[0]
    states = [[val() for _ in range(g.n_state)] for _ in range(5)]
    states += [[0] * g.n_state, [sf.snan_bits(fmt)] * g.n_state,
               [1] * g.n_state]
    tans = None
    if g.tangent:
        tans = [[[val() for _ in range(g.n_state)] for _ in g.tangent]
                for _ in states]
    return states, tans


def _held(c, states, tans, steps):
    """The image (compiled at `steps`) on seq.py against lang.run."""
    r = c.run(states, tangents=tans)
    ref = lang.run(c.graph, states, steps, tangents=tans)
    m, n = c.ir.m, c.ir.n_primal
    got = [r.scratch_out[k * m:k * m + n] for k in range(len(states))]
    assert got == ref.states
    if tans is not None:
        gt = [r.scratch_out[k * m + n:k * m + c.ir.n_state]
              for k in range(len(states))]
        assert gt == [[v for vec in t for v in vec] for t in ref.tangents]
    assert r.flags == ref.flags
    return r


@pytest.mark.parametrize("case", list(ROUTINE))
def test_each_routine_compiles_on_the_software_targets(case):
    """Each source - a quotient, a root, both under rk4 with two vectors, a
    quotient by a constant, by h and by zero, a written tangent, a tangent
    let or an expansion block first - compiles for sw and sw:4096, its image
    holding QUIET, ENDQUIET and RAISE, accepted by `sw` and revision 8's
    three, which publish flag control, and by no other built-in target;
    and runs on seq.py as lang.run does, states, tangents and FLAGS, on
    lanes that divide 0 by 0, hold a signalling NaN and hold
    subnormals."""
    text, _line = ROUTINE[case]
    g = lang.compile_text(text, "src.cftl").graph
    ops = [op for op in ("div", "sqrt") if op in g.op_counts("step")]
    assert ops
    states, tans = _routine_lanes(g, case)
    for steps in (1, 3):
        for target in ("sw", "sw:4096"):
            c = cftc.compile_text(text, steps, target=target,
                                  source="src.cftl")
            assert "FLAG_CONTROL" in c.features
            assert c.accepted_by == ["sw", *REV8]
            names = {asm.CTRL_NAMES.get(asm.decode(w)["op"])
                     for w in c.image_obj.insns if asm.decode(w)["ctrl"]}
            assert {"quiet", "endquiet", "raise"} <= names
            m = c.manifest
            assert set(m["routines"]["calls"]) == set(ops)
            assert m["per_step"]["instructions"] == len(c.program.body) + 1
            assert all(b["kind"] != "word" or b["exact"] is None
                       for b in m["bank"])
        _held(c, states, tans, steps)
    # a graph read from its bytes compiles to the same image
    back = lang.StepGraph.from_bytes(g.to_bytes())
    assert cftc.compile_graph(back, 3, source="src.cftl").image == c.image


@pytest.mark.parametrize("case", list(ROUTINE))
def test_revision_7s_targets_refuse_a_routine_by_name(case):
    """Revision 7's tiles have no flag control: on each of revision 7's
    targets, and a trimmed one, a routine image is refused
    `target-feature`, the sentence naming FLAG_CONTROL, CAPS2[14], the
    routines and the built-in targets that publish the bit, `sw` and
    revision 8's three - by name, never an internal error; a step count
    of 0 is still `segment-steps`, first."""
    text, _line = ROUTINE[case]
    g = lang.compile_text(text, "src.cftl").graph
    ops = [op for op in ("div", "sqrt") if op in g.op_counts("step")]
    trim = T.Target("trim", ("fp32", "fp64", "fp128", "fp256"), 32768, 512,
                    2048, 1024, T.TILE_FEATURES)
    for target in ["u50-rev7", "u50-rev7-quad", "u50-round2", "open-core",
                   trim]:
        with pytest.raises(lang.Refusal) as e:
            cftc.compile_text(text, 3, target=target, source="src.cftl")
        assert e.value.name == "target-feature", (target, str(e.value))
        s = e.value.sentence
        assert "FLAG_CONTROL (CAPS2[14])" in s and "revision 8" in s, s
        assert all(op in s for op in ops), s
        assert s.endswith("which the built-in targets sw, u50-rev8, "
                          "u50-rev8-quad and u50-rev8-deep publish"), s
        with pytest.raises(lang.Refusal) as e:
            cftc.compile_text(text, 0, target=target)
        assert e.value.name == "segment-steps"


def test_a_routine_through_the_command_line(tmp_path):
    """sw: exit 0, the files, the text's regions; revision 8's quad, by
    name: exit 0, the image and bank sw's bytes, the manifest naming the
    quad; a revision-7 target: exit 3, `target-feature`, nothing written;
    never 70."""
    py = [sys.executable, str(ROOT / "python" / "cftc")]
    text, _line = ROUTINE["both, a let, rk4, two vectors"]
    src = tmp_path / "b.cftl"
    src.write_bytes(text.encode("ascii"))
    r = subprocess.run(py + [str(src), "--steps", "2", "--out",
                             str(tmp_path / "a")], capture_output=True,
                       text=True)
    assert r.returncode == 0, r.stderr
    cfta = (tmp_path / "a" / "b.cfta").read_text(encoding="ascii")
    assert "\n  quiet " in cfta and "\n  endquiet\n" in cfta
    assert "\n  raise    r" in cfta and "\n    fma.rtz  r" in cfta
    assert "; routines " in cfta
    r = subprocess.run(py + [str(src), "--steps", "2", "--target",
                             "u50-rev8-quad", "--out", str(tmp_path / "q")],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    for ext in ("cftp", "bank"):
        assert (tmp_path / "q" / f"b.{ext}").read_bytes() == \
            (tmp_path / "a" / f"b.{ext}").read_bytes(), ext
    m = json.loads((tmp_path / "q" / "b.manifest.json").read_bytes())
    assert m["target"]["name"] == "u50-rev8-quad"
    assert m["accepted_by"] == ["sw", *REV8]
    r = subprocess.run(py + [str(src), "--steps", "2", "--target",
                             "u50-rev7-quad", "--out", str(tmp_path / "b")],
                       capture_output=True, text=True)
    assert r.returncode == 3, r.stderr
    assert r.stderr.startswith("cftc: refused target-feature: ")
    assert "internal error" not in r.stderr
    assert not (tmp_path / "b").exists()


def test_divisions_and_roots_that_fold_compile_without_a_routine():
    """A constant over a constant and the root of a rational's square fold
    (L4): a system holding only those has no routine and no flag control,
    and every target accepts it; x / (1 + 1) is a division at run time, a
    routine, which `sw` and revision 8's three accept, and no other
    built-in target."""
    text = ("system f\nformat fp64\nstate x, y\nnext x = x * (8/3)\n"
            "next y = fma(y, sqrt(9/4), x / (1 + 1) * 0 + x * (1/3))\n"
            "step map\n")
    c = cftc.compile_text(text, 3)
    assert c.manifest["routines"]["calls"] == {"div": 1}
    assert c.accepted_by == ["sw", *REV8]
    states, _t = _routine_lanes(c.graph, "fold")
    _held(c, states, None, 3)
    text = text.replace("x / (1 + 1) * 0 + ", "")
    c = cftc.compile_text(text, 3)
    assert "div" not in c.graph.op_counts() and \
        "sqrt" not in c.graph.op_counts()
    assert "FLAG_CONTROL" not in c.features and "routines" not in c.manifest
    assert c.accepted_by == T.names()
    lanes = [[K.round_once(c.ir.fmt, sf.RND_RNE, Fraction(v, 9))[0]] * 2
             for v in (2, -5, 13)]
    r = c.run(lanes)
    ref = lang.run(c.graph, lanes, 3)
    assert [r.scratch_out[k * c.ir.m:k * c.ir.m + 2] for k in range(3)] == \
        ref.states and r.flags == ref.flags


def test_the_bank_capacity_counts_the_routines_words():
    """The language holds params and constants to 512; the compiler counts
    the routines' words too, and refuses the language's own name,
    `bank-capacity`, where they take the bank past it - a sentence naming
    all three. Below the limit the same source compiles."""
    def source(k):
        ps = ", ".join(f"p{i} = {i + 1}" for i in range(k))
        total = " + ".join(f"p{i}" for i in range(k))
        return (f"system wide\nformat fp64\nstate x, y\nparam {ps}\n"
                f"next x = x / y + ({total})\nnext y = y\nstep map\n")
    words = len(set(R.fragment("div", FORMATS["fp64"],
                               sf.RND_RNE).words.values()))
    over = 512 - words + 1
    lang.compile_text(source(over), "wide")             # the language's 512
    with pytest.raises(lang.Refusal) as e:
        cftc.compile_text(source(over), 2)
    assert e.value.name == "bank-capacity"
    assert f"{over} params, 0 constants and {words} words" in \
        e.value.sentence and "512 on every device" in e.value.sentence
    c = cftc.compile_text(source(over - 1), 2)
    assert len(c.lowered.slots) == 512


def _routine_compile():
    text = ("system p\nformat fp64\nstate x, y\nnext x = (x + 1) / y\n"
            "next y = y * 3\nstep map\n")
    return cftc.compile_text(text, 2)


def _image_with(c, words):
    img = asm.Image.from_bytes(c.image)
    return asm.Image(img.fmt, words, img.consts, img.max_deposits, img.flags,
                     scratch_depth=img.scratch_depth,
                     scratch_io=img.scratch_io).to_bytes()


def test_the_internal_check_holds_a_routine():
    """Controls for check.py's routine rules, each a damaged image of a
    step with a division and the language's own nodes: an instruction of
    the routine moved outside its region; the raise moved inside it; the
    raise dropped; the truncating fma made rne; a language node moved into
    the region; a word's bits changed in the bank. Each an InternalError."""
    c = _routine_compile()
    insns = list(asm.Image.from_bytes(c.image).insns)
    dec = [asm.decode(w) for w in insns]

    def ctrl(k, name):
        return dec[k]["ctrl"] and asm.CTRL_NAMES.get(dec[k]["op"]) == name
    q = next(k for k in range(len(dec)) if ctrl(k, "quiet"))
    e = next(k for k in range(len(dec)) if ctrl(k, "endquiet"))
    r = next(k for k in range(len(dec)) if ctrl(k, "raise"))
    assert q < e < r

    def refused(words):
        with pytest.raises(cftc.InternalError):
            cftc_check.verify(c.lowered, c.program, _image_with(c, words),
                              c.steps, c.lowered.half_bits)
    w = list(insns)                     # the region's last instruction out
    w[e - 1], w[e] = w[e], w[e - 1]
    refused(w)
    w = list(insns)                     # the raise in
    w[e], w[r] = w[r], w[e]
    refused(w)
    refused(insns[:r] + insns[r + 1:])  # the raise dropped
    k = next(k for k in range(q, e) if not dec[k]["ctrl"]
             and dec[k]["op"] == sf.OP_FMA and dec[k]["rnd"] == sf.RND_RTZ)
    w = list(insns)                     # the routine's own rtz made rne
    w[k] = (insns[k] & ~(0x7 << 24)) | (sf.RND_RNE << 24)
    refused(w)
    # a language node into the region: the instruction before QUIET, if it
    # is the language's, moved after it
    lang_k = max(k for k in range(q) if not dec[k]["ctrl"])
    w = list(insns)
    w[lang_k], w[q] = w[q], w[lang_k]
    refused(w)
    # the bank: a word's bits
    k = next(k for k, s in enumerate(c.lowered.slots) if s.kind == "word")
    c.lowered.slots[k].bits ^= 1
    with pytest.raises(cftc.InternalError):
        cftc_check.verify(c.lowered, c.program, c.image, c.steps,
                          c.lowered.half_bits)
    c.lowered.slots[k].bits ^= 1
    cftc_check.verify(c.lowered, c.program, c.image, c.steps,
                      c.lowered.half_bits)


# ---- C4: the call loop -------------------------------------------------------
# A step whose routines, inlined, would pass callloop.CALL_LOOP_ABOVE
# instructions runs batches of them in loops (Logan's rule, 2026-10-02).
# The constant is lowered here so that small systems loop; the lang stage
# holds the natural case - eight bodies under rk4 - at the constant itself.

KEPLER_RK4 = ("system kepler\nformat fp64\nstate x, y, px, py\n"
              "let r2 = fma(x, x, y * y)\nlet r3 = r2 * sqrt(r2)\n"
              "d/dt x = px\nd/dt y = py\nd/dt px = -(x / r3)\n"
              "d/dt py = -(y / r3)\nstep rk4, h = 1/100\n")
FIXED = ("system f\nformat fp64\nstate x, y, u, v\n"
         "next x = 1 / (x * x + 1)\nnext y = 1 / (y * y + 2)\n"
         "next u = sqrt(u * u + 1) / 3\nnext v = sqrt(v * v + 2) / 3\n"
         "step map\n")


def _looped(monkeypatch, text, above, steps=2, **kw):
    monkeypatch.setattr(callloop, "CALL_LOOP_ABOVE", above)
    return cftc.compile_text(text, steps, source="loop.cftl", **kw)


def _batches(c):
    return [(b.op, b.depth, len(b.calls)) for b in c.looped]


def test_a_step_past_the_constant_loops_the_largest_batch_first(monkeypatch):
    """Kepler under rk4 has four batches: the first two stages' roots
    (depth 1) and divisions (2), the last two's (3, 4). A constant one
    under its inlined step loops the largest batch - a division's, four
    calls - and no more; a constant of 0 loops all four. Each image runs as
    lang.run does, states and FLAGS, on lanes that divide 0 by 0, hold a
    signalling NaN and hold subnormals; the manifest and the text say
    what was looped, and nothing of it appears where nothing was."""
    inl = cftc.compile_text(KEPLER_RK4, 2)
    assert inl.looped == []
    assert "call_loops" not in inl.manifest["routines"]
    assert "call_loops" not in inl.manifest["cost_model"]
    assert "; call loops" not in inl.cfta
    size = len(inl.program.body) + 1
    assert inl.program.executed() == size
    states, _t = _routine_lanes(inl.graph, "loop")
    c = _looped(monkeypatch, KEPLER_RK4, size - 1)
    assert _batches(c) == [("div", 2, 4)]
    assert len(c.program.body) + 1 <= size - 1
    assert c.program.executed() > size
    _held(c, states, None, 2)
    m = c.manifest["routines"]
    assert m["calls"] == {"sqrt": 4, "div": 8}
    loops = m["call_loops"]
    assert loops["above"] == size - 1
    assert [(e["op"], e["depth"], e["calls"]) for e in loops["loops"]] == \
        [("div", 2, 4)]
    assert loops["executed_per_step"] == c.program.executed()
    assert "call_loops" in c.manifest["cost_model"]
    assert "; call loops 1, " in c.cfta
    assert "\n  repeat 4 " in c.cfta and "\n    ldx      r" in c.cfta
    assert "\n    stx      r" in c.cfta and "\n      fma.rtz  r" in c.cfta
    c0 = _looped(monkeypatch, KEPLER_RK4, 0)
    assert sorted(_batches(c0)) == [("div", 2, 4), ("div", 4, 4),
                                    ("sqrt", 1, 2), ("sqrt", 3, 2)]
    _held(c0, states, None, 2)


def test_a_batch_of_one_call_is_never_looped(monkeypatch):
    """Three divisions each reading the last are three batches of one
    call; a loop of one would only add its own instructions, so past the
    constant the step stays inlined, and runs as lang.run does."""
    text = ("system chain\nformat fp64\nstate x\n"
            "next x = ((x / 3) / 5) / 7\nstep map\n")
    c = _looped(monkeypatch, text, 0)
    assert c.looped == [] and c.program.loops() == []
    assert c.manifest["routines"]["calls"] == {"div": 3}
    states, _t = _routine_lanes(c.graph, "chain")
    _held(c, states, None, 2)


def test_one_looped_image_serves_every_target_that_takes_it(monkeypatch):
    """The constant is the compiler's, never a target's: the same source
    loops the same way for sw, sw:4096 and revision 8's three - one image,
    the same bytes, which each of them accepts - and revision 7's targets
    still refuse it `target-feature`, by name."""
    a = _looped(monkeypatch, KEPLER_RK4, 1000)
    b = _looped(monkeypatch, KEPLER_RK4, 1000, target="sw:4096")
    assert a.looped and a.image == b.image and a.bank == b.bank
    assert a.accepted_by == ["sw", *REV8]
    for t in REV8:
        r = _looped(monkeypatch, KEPLER_RK4, 1000, target=t)
        assert r.image == a.image and r.bank == a.bank, t
    with pytest.raises(lang.Refusal) as e:
        _looped(monkeypatch, KEPLER_RK4, 1000, target="u50-rev7")
    assert e.value.name == "target-feature"


def test_a_loop_with_tangent_vectors_and_at_every_format(monkeypatch):
    """Looped calls with two tangent vectors under rk4, at fp256 (the
    quotient's and the root's derivatives are divisions too), and Kepler
    looped at fp32, fp128 and fp256 and under rtz, rdn, rup and rmm: each
    as lang.run, states, tangents and FLAGS."""
    text, _line = ROUTINE["both, a let, rk4, two vectors"]
    c = _looped(monkeypatch, text, 0)
    assert c.looped and c.graph.tangent == ["v", "w"]
    states, tans = _routine_lanes(c.graph, "loop tangent")
    _held(c, states, tans, 2)
    for fmt, rnd in (("fp32", "rne"), ("fp128", "rne"), ("fp256", "rne"),
                     ("fp64", "rtz"), ("fp64", "rdn"), ("fp64", "rup"),
                     ("fp64", "rmm")):
        text = KEPLER_RK4.replace("format fp64", f"format {fmt}\nround {rnd}")
        c = _looped(monkeypatch, text, 0)
        assert len(c.looped) == 4
        states, _t = _routine_lanes(c.graph, f"loop {fmt} {rnd}")
        _held(c, states, None, 2)


def test_an_input_every_call_takes_from_one_slot_is_no_part_of_a_record(
        monkeypatch):
    """Two divisions of 1 (N bodies' 1 / (s sqrt(s)) is 56 of them at
    N = 8) and two divisions by 3: the 1 and the 3 are read from the bank
    by the loop's body, each record one slot - the a for the divisions by
    3, the b for those of 1 - and the result over it."""
    c = _looped(monkeypatch, FIXED, 0)
    assert sorted(_batches(c)) == [("div", 1, 2), ("div", 2, 2),
                                   ("sqrt", 1, 2)]
    by = {(e["op"], e["depth"]): e
          for e in c.manifest["routines"]["call_loops"]["loops"]}
    one = by[("div", 1)]
    assert list(one["fixed"]) == ["a"]
    assert c.lowered.slots[one["fixed"]["a"]].exact == 1
    assert one["records"][1] - one["records"][0] == 1
    three = by[("div", 2)]
    assert list(three["fixed"]) == ["b"]
    assert c.lowered.slots[three["fixed"]["b"]].exact == 3
    assert by[("sqrt", 1)]["fixed"] == {}
    states, _t = _routine_lanes(c.graph, "fixed")
    _held(c, states, None, 2)


def test_the_internal_check_holds_a_call_loop(monkeypatch):
    """Controls for check.py's loop rules, each a damaged looped image of
    Kepler under rk4: the index's last step dropped (the next call reads
    the last one's result), the call's raise dropped, a loop's count one
    short, an operand stored into the wrong record, and the index stepped
    by another word (4, which the routines hold) than the 1. Each an
    InternalError; the image as written passes."""
    c = _looped(monkeypatch, KEPLER_RK4, 0)
    insns = list(asm.Image.from_bytes(c.image).insns)
    dec = [asm.decode(w) for w in insns]

    def ctrl(k, name):
        return dec[k]["ctrl"] and asm.CTRL_NAMES.get(dec[k]["op"]) == name

    def refused(words):
        with pytest.raises(cftc.InternalError):
            cftc_check.verify(c.lowered, c.program, _image_with(c, words),
                              c.steps, c.lowered.half_bits)
    reps = [k for k in range(len(dec)) if ctrl(k, "repeat")]
    ends = [k for k in range(len(dec)) if ctrl(k, "endrep")]
    r, e = reps[1], ends[0]                 # the first call loop
    assert r < e < reps[2]
    step = e - 1                            # its last instruction: the step
    assert not dec[step]["ctrl"] and \
        sf.OP_NAMES[dec[step]["op"]] == "iadd"
    refused(insns[:step] + insns[step + 1:])
    rz = next(k for k in range(r, e) if ctrl(k, "raise"))
    refused(insns[:rz] + insns[rz + 1:])
    w = list(insns)
    w[r] = asm.repeat(dec[r]["imm"] - 1)
    refused(w)
    node, calls = c.program.loops()[0]
    loop = c.program.x.nodes[node]
    first = range(loop.base, loop.base + loop.stride * calls)
    st = max(k for k in range(r) if ctrl(k, "stl")
             and (dec[k]["imm"] & asm.SLOT_MASK) in first)
    w = list(insns)
    w[st] = asm.stl(dec[st]["ra"], (dec[st]["imm"] & asm.SLOT_MASK) + 1)
    refused(w)
    # the index stepped by another word, not the 1: evaluated concretely,
    # the next call reads a slot no record is in
    four = c.lowered.slot_of[("w", 4)]
    w = list(insns)
    w[step] = asm.alu(dec[step]["op"], dec[step]["rd"], dec[step]["ra"],
                      four, kb=True)
    refused(w)
    cftc_check.verify(c.lowered, c.program, c.image, c.steps,
                      c.lowered.half_bits)


def test_a_call_loop_is_counted_as_the_loader_counts_it(monkeypatch):
    """The worst case the loader bounds counts a loop's body once a call:
    the compilation's, and seq.py's own reading of the image, agree; and
    the cycle model runs the loop as unrolled."""
    c = _looped(monkeypatch, KEPLER_RK4, 0, steps=7)
    p = c.program
    assert c.worst_case == len(p.prologue) + 1 + 7 * p.executed() + \
        len(p.epilogue) + 1
    insns = [asm.decode(w) for w in asm.Image.from_bytes(c.image).insns]
    mult, worst = [1], 0
    for d in insns:
        worst += mult[-1]
        if d["ctrl"] and d["op"] == asm.REPEAT:
            mult.append(mult[-1] * d["imm"])
        elif d["ctrl"] and d["op"] == asm.ENDREP:
            mult.pop()
    assert worst == c.worst_case
    from cftc import schedule
    assert len(schedule.unrolled(p.body)) + 1 == p.executed()
# The `tangent` stage (programs/tangent_check.py) holds every compiled
# variational image to lang.run on seq.py; these are its smaller facts.

def _tangent_lanes(fmt, n, count, T, seed):
    rng = random.Random(seed)

    def val():
        return K.round_once(fmt, sf.RND_RNE,
                            Fraction(rng.randint(-900, 900), 97))[0]
    states = [[val() for _ in range(n)] for _ in range(count)]
    tans = [[[val() for _ in range(n)] for _ in range(T)]
            for _ in range(count)]
    return states, tans


def test_a_variational_image_runs_as_lang_runs():
    for name, T in (("lorenz63-rk4-tangent-fp64", 1),):
        c = cftc.compile_file(SYSTEMS / f"{name}.cftl", 5)
        g = c.ir
        assert (g.version, g.T, g.n_primal, g.n_state) == (2, 1, 3, 6)
        states, tans = _tangent_lanes(g.fmt, 3, 4, T, name)
        r = c.run(states, tangents=tans)
        ref = lang.run(c.graph, states, 5, tangents=tans)
        m = g.m
        for k in range(4):
            out = r.scratch_out[k * m:(k + 1) * m]
            assert out[:3] == ref.states[k]
            assert [out[3:6]] == ref.tangents[k]
        assert r.flags == ref.flags


def test_the_lane_block_and_the_manifest_of_a_variational_system():
    """[state | v | w | lane params], in the image's scratch block and in
    the manifest's layout; the manifest says version 2 and the vectors."""
    text = ("system s\nformat fp64\nstate x, y\ntangent v, w\n"
            "lane param m = 3\nnext x = x * y\nnext y = fma(m, x, y)\n"
            "step map\n")
    c = cftc.compile_text(text, 2)
    g = c.ir
    assert g.components == ["x", "y", "v.x", "v.y", "w.x", "w.y"]
    block = c.scratch_block([[1, 2]], tangents=[[[3, 4], [5, 6]]])
    lane_m = K.round_once(g.fmt, sf.RND_RNE, Fraction(3))[0]
    assert block == [1, 2, 3, 4, 5, 6, lane_m]
    with pytest.raises(ValueError):
        c.scratch_block([[1, 2]])
    man = c.manifest
    assert man["graph"]["cftl_graph"] == 2
    assert man["tangent"] == {"vectors": ["v", "w"], "components": 2,
                              "slots": [2, 4]}
    kinds = [(e["name"], e["kind"], e.get("vector"), e.get("of"))
             for e in man["scratch"]["layout"]]
    assert kinds == [("x", "state", None, None), ("y", "state", None, None),
                     ("v.x", "tangent", "v", "x"), ("v.y", "tangent", "v", "y"),
                     ("w.x", "tangent", "w", "x"), ("w.y", "tangent", "w", "y"),
                     ("m", "lane param", None, None)]
    assert man["lowering"]["graph_tangent_step_nodes"] == \
        len(c.graph.tangent_step.nodes)
    assert "; tangent v (slots 2..3), w (slots 4..5)" in c.cfta
    # a system without tangents writes a manifest without the keys
    plain = cftc.compile_file(SYSTEMS / "lorenz63-rk4-fp64.cftl", 3).manifest
    assert "tangent" not in plain and plain["graph"]["cftl_graph"] == 1
    assert "graph_tangent_step_nodes" not in plain["lowering"]


def test_the_interleaved_order_is_offered_only_with_tangents():
    from cftc import schedule
    plain = cftc.compile_file(SYSTEMS / "lorenz96-rk4-fp64.cftl", 2)
    assert schedule.candidates(plain.lowered) == schedule.CANDIDATES
    var = cftc.compile_file(SYSTEMS / "lorenz96-rk4-tangent-fp64.cftl", 2)
    assert schedule.candidates(var.lowered)[-1] == ("interleaved", 0)
    assert var.program.candidate == ("interleaved", 0)
    assert var.program.slots_used == 139


def test_scratch_capacity_names_the_tangent_slots():
    text = ("system s\nformat fp64\nstate x[200]\ntangent v\n"
            "next x[i] = x[i] * x[i]\nstep map\n")
    with pytest.raises(lang.Refusal) as e:
        cftc.compile_text(text, 2, target="sw")
    assert e.value.name == "scratch-capacity"
    assert "200 state, 200 for 1 tangent vector" in e.value.sentence
    c = cftc.compile_text(text, 2, target="u50-rev7")
    assert c.program.slots_used >= 400


# ---- C4's first commit: the format override, the compiler id, VERSION ----

def test_a_format_override_compiles_the_source_at_another_format():
    """compile_file's fmt is the language's override: every output the
    compile of the text with its format line replaced writes, but the
    manifest's "source" saying so and the .cfta's one line more; and an
    override equal to the declared format changes no byte at all."""
    path = SYSTEMS / "lorenz63-rk4-fp64.cftl"
    data = path.read_bytes()
    src = "programs/systems/lorenz63-rk4-fp64.cftl"
    plain = cftc.compile_file(path, 9, source=src)
    same = cftc.compile_file(path, 9, source=src, fmt="fp64")
    assert same.files() == plain.files()
    assert same.format_override is None
    over = cftc.compile_file(path, 9, source=src, fmt="fp128")
    swapped = cftc.compile_text(data.replace(b"format fp64", b"format fp128"),
                                9, source=src, stem="lorenz63-rk4-fp64")
    assert over.format_override == ("fp64", "fp128")
    assert over.source_sha256 == plain.source_sha256       # the source's bytes
    for what in ("image", "bank", "graph", "canonical", "math"):
        assert over._bytes(what) == swapped._bytes(what), what
    m = json.loads(over.manifest_bytes)
    assert m["source"]["format_override"] == {"source": "fp64",
                                              "compiled": "fp128"}
    assert m["format"] == "fp128"
    assert "format_override" not in json.loads(plain.manifest_bytes)["source"]
    assert "; format  fp128 by a format override; the source declares " \
           "fp64\n" in over.cfta
    # the .cfta: the swapped text's, but for the source's digest (the
    # override's is the source's own bytes') and the one line more
    assert over.cfta.replace("; format  fp128 by a format override; the "
                             "source declares fp64\n", "").replace(
        over.source_sha256, "S") == swapped.cfta.replace(
        swapped.source_sha256, "S")


def test_the_format_override_through_the_command_line(tmp_path):
    py = [sys.executable, str(ROOT / "python" / "cftc")]
    src = str(SYSTEMS / "henonheiles-lf-fp64.cftl")
    r = subprocess.run(py + [src, "--steps", "3", "--format", "fp256",
                             "--out", str(tmp_path / "a")],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    m = json.loads((tmp_path / "a" / "henonheiles-lf-fp64.manifest.json")
                   .read_bytes())
    assert (m["format"], m["source"]["format_override"]["source"]) == \
        ("fp256", "fp64")
    r = subprocess.run(py + [src, "--steps", "3", "--format", "fp99",
                             "--out", str(tmp_path / "b")],
                       capture_output=True, text=True)
    assert r.returncode == 3, r.stderr
    assert r.stderr.startswith("cftc: refused unknown-format: ")
    assert not (tmp_path / "b").exists()


def test_the_compiler_id_is_the_build_ids_grammar(monkeypatch):
    """--compiler-id runs host/tools/gen_build_id.sh on the repository
    cftc runs from: its answer, in cft_build_id()'s grammar, or unknown -
    and unknown, with a reason, where there is no shell or no script."""
    py = [sys.executable, str(ROOT / "python" / "cftc")]
    r = subprocess.run(py + ["--compiler-id"], capture_output=True,
                       text=True)
    assert r.returncode == 0, r.stderr
    line = r.stdout.strip()
    assert r.stdout.count("\n") == 1
    assert line == "unknown" or cftc._ID.fullmatch(line), line
    ident, why = cftc.compiler_id_detail()
    assert ident == line and (why is None) == (line != "unknown")
    sh = __import__("shutil").which("sh")
    if sh is not None:                      # the one generator, run directly
        d = subprocess.run([sh, "host/tools/gen_build_id.sh", "--print",
                            ROOT.as_posix()], capture_output=True,
                           text=True, cwd=str(ROOT))
        assert d.stdout.strip() == line
    monkeypatch.setattr(cftc.shutil, "which", lambda name: None)
    assert cftc.compiler_id_detail()[0] == "unknown"
    assert "no POSIX shell" in cftc.compiler_id_detail()[1]
    monkeypatch.undo()
    monkeypatch.setattr(cftc, "ROOT", ROOT / "python" / "nowhere")
    ident, why = cftc.compiler_id_detail()
    assert ident == "unknown" and "gen_build_id.sh" in why


def test_version_is_the_records_last_and_the_record_holds():
    """cftc's VERSION is an output version: the record's last block is
    VERSION's and names every committed compiled file with its digest
    (the lang stage's leg F holds the same, with its plants)."""
    from cftc import outputs as O
    text = (SYSTEMS / O.RECORD_NAME).read_text(encoding="ascii")
    files = O.committed(SYSTEMS)
    assert O.problems(text, files, cftc.VERSION) == []
    blocks = O.parse(text)
    assert [v for v, _b in blocks] == list(range(1, cftc.VERSION + 1))
    m = json.loads((SYSTEMS / "compiled" / "lorenz63-rk4-fp64.manifest.json")
                   .read_bytes())
    assert m["compiler"] == {"name": "cftc", "version": cftc.VERSION}
    assert "2.2% to 5.8% slower" in m["cost_model"]["assumes"]
    # the rule is mechanical: each break is named
    some = sorted(files)[0]
    assert O.problems(text, dict(files, **{some: "0" * 64}), cftc.VERSION)
    assert O.problems(text, files, cftc.VERSION + 1)
    assert O.problems(text, {p: d for p, d in files.items() if p != some},
                      cftc.VERSION)
    with pytest.raises(O.RecordError):
        O.append(text, dict(files, **{some: "0" * 64}), cftc.VERSION)
    with pytest.raises(O.RecordError):
        O.append(text, files, cftc.VERSION + 2)
    new, what = O.append(text, dict(files, **{"compiled/z.cfta": "1" * 64}),
                         cftc.VERSION)
    assert new.endswith("1" * 64 + "  compiled/z.cfta\n") and "1 new" in what
    assert O.problems(new, dict(files, **{"compiled/z.cfta": "1" * 64}),
                      cftc.VERSION) == []
    bumped, _w = O.append(text, files, cftc.VERSION + 1)
    assert [v for v, _b in O.parse(bumped)][-1] == cftc.VERSION + 1
    with pytest.raises(O.RecordError):
        O.parse(text.replace("version 1\n", "version 3\n", 1))


# ---- revision 8's targets (parcel E, 2026-10-05; built in, parcel TG) --------
# cftc/targets.py's three revision-8 targets (REV8, above), in the built-in
# table since cftc's output version 5 (2026-10-06): each held to its image's
# words - rev8a's as the card read them, rev8q's and rev8d's the plan's,
# computed - and seen by get(), names(), get_target, the command line and
# accepted_by. Until then they were provisional, kept out of all five.

# "What a revision-8 U50 tile reads" (docs/ROADMAP.md, "Revision 8"): CAPS
# unchanged from revision 7; CAPS2 0x00187ffb at 2,048 slots, 0x00187ffc at
# 4,096 and 0x001877fb without R21; seq_features 0x7ff1f, 0x77f1f without.
PLAN_CAPS = 0x19faffff
# rev8a, the image u50-rev8 stands for, on the card (2026-10-06; the step-6
# records in docs/VALIDATION.md): device-test -i read VERSION 0x00000b00,
# CAPS 0x19faffff and CAPS2 0x00187ffc, and libcft decoded them as
# seq_features 0x7ff1f, capacities 1024/16777216/512 (deposits,
# instructions, constants) and max_scratch 4096 - here in _decode_b00's
# order.
REV8A_CARD = (0x19faffff, 0x00187ffc)
REV8A_DECODED = (0x7ff1f, 1 << 24, 512, 4096, 1024)


def _decode_b00(caps, caps2):
    """A 0xB00 tile's words as host/src/caps_decode.h decodes them, which
    api-test holds in C to the same words: (seq_features, max_insns,
    max_consts, scratch depth, max_deposits)."""
    feats = ((caps >> 4) & 0xF) | (((caps >> 28) & 0xF) << 4)
    feats |= ((caps2 >> 4) & 0xF) << 8
    for bit, feat in ((0x100, 0x1000), (0x200, 0x2000), (0x400, 0x4000)):
        if caps2 & bit:
            feats |= feat
    feats |= ((caps2 >> 11) & 0xF) << 15
    insns = 1 << ((caps >> 20) & 0xF)
    if (caps2 >> 16) & 0x1F:
        insns = 1 << ((caps2 >> 16) & 0x1F)
    depth = 1 << (caps2 & 0xF) if caps2 & 0x10 else 0
    return (feats, insns, 1 << ((caps >> 24) & 0xF), depth,
            1 << ((caps >> 16) & 0xF))


def _caps2(depth, r21):
    """The CAPS2 a revision-8 U50 image at `depth` slots publishes: the
    plan's 0x00187ffb with CAPS2[3:0] at the depth's log2, and CAPS2[11]
    clear without R21."""
    word = 0x00187ff0 | (depth.bit_length() - 1)
    return word if r21 else word & ~0x800


def test_the_words_decode_as_the_plan_and_the_card_say():
    """The transcription above, anchored to the plan's three stated words,
    to revision 7's, through which a seam tile reads as revision 7, and to
    rev8a's words as libcft decoded them on the card."""
    assert _decode_b00(PLAN_CAPS, 0x00187ffb) == \
        (0x7ff1f, 1 << 24, 512, 2048, 1024)
    assert _decode_b00(PLAN_CAPS, 0x00187ffc) == \
        (0x7ff1f, 1 << 24, 512, 4096, 1024)
    assert _decode_b00(PLAN_CAPS, 0x001877fb) == \
        (0x77f1f, 1 << 24, 512, 2048, 1024)
    assert _decode_b00(PLAN_CAPS, 0x000007fb) == \
        (0x7f1f, 32768, 512, 2048, 1024)
    assert _decode_b00(*REV8A_CARD) == REV8A_DECODED
    assert _caps2(2048, True) == 0x00187ffb
    assert _caps2(4096, True) == 0x00187ffc == REV8A_CARD[1]
    assert _caps2(2048, False) == 0x001877fb


def test_revision_8s_targets_are_their_images_words():
    """Each target is its image's words decoded: the single and the deep
    single with R21, 0x7ff1f, the software handle's word; the quad without
    it, 0x77f1f, AUGADD alone apart; 2^24 instructions, 512 constants and
    1,024 deposit slots each. Their depths are the images', which probe K
    decided (2026-10-05): 4,096 for the quad and the single built at the
    quad's slots, and 8,192 for the deep single, since 16,384 would cross
    both SLRs. u50-rev8 is rev8a's words as the card read them; the quad's
    and the deep single's are the plan's."""
    single, quad, deep = (T.get(n) for n in REV8)
    for t, r21 in ((single, True), (quad, False), (deep, True)):
        assert t.formats == T.ALL_FORMATS
        assert (t.seq_features, t.max_insns, t.max_consts, t.scratch_depth,
                t.max_deposits) == \
            _decode_b00(PLAN_CAPS, _caps2(t.scratch_depth, r21)), t.name
    assert (single.seq_features, single.max_insns, single.max_consts,
            single.scratch_depth, single.max_deposits) == REV8A_DECODED
    assert (PLAN_CAPS, _caps2(single.scratch_depth, True)) == REV8A_CARD
    assert single.seq_features == deep.seq_features == 0x7ff1f == \
        T.SW_FEATURES
    assert quad.seq_features == 0x77f1f
    assert single.seq_features ^ quad.seq_features == \
        T.FEATURE_BITS["AUGADD"]
    assert single.scratch_depth == quad.scratch_depth == 4096
    assert deep.scratch_depth == 8192
    assert _caps2(quad.scratch_depth, False) == 0x001877fc
    assert _caps2(deep.scratch_depth, True) == 0x00187ffd
    for t in (single, quad, deep):
        assert {"FLAG_CONTROL", "LANE_FLAGS", "SCRATCH_STEP"} <= \
            set(t.features())
    assert "AUGADD" in single.features() and "AUGADD" in deep.features()
    assert "AUGADD" not in quad.features()


def test_revision_8s_targets_are_built_in(tmp_path):
    """In BUILTIN, get() and names(), after `sw` and before revision 7's;
    get_target gives each; accepted_by lists each that an image fits, at
    their capacities' edges; and named on the command line each compiles
    - exit 0, the image and bank sw's bytes, the manifest naming the
    target and listing the three - while `--targets` prints each with its
    capacities and feature word."""
    assert T.names()[:4] == ["sw", *REV8]
    for name in REV8:
        assert name in T.BUILTIN and T.get(name) is T.BUILTIN[name]
        assert cftc.get_target(name) is T.BUILTIN[name]
    from cftc import manifest as M
    fc = ["FLAG_CONTROL"]
    assert M.accepted_by("fp64", [], 10, 0) == T.names()
    assert M.accepted_by("fp64", fc, 1 << 24, 256) == ["sw", *REV8]
    assert M.accepted_by("fp64", fc, (1 << 24) + 1, 256) == ["sw"]
    assert M.accepted_by("fp64", fc, 10, 4096) == list(REV8)
    assert M.accepted_by("fp64", fc, 10, 4097) == ["u50-rev8-deep"]
    assert M.accepted_by("fp64", fc, 10, 8192) == ["u50-rev8-deep"]
    assert M.accepted_by("fp64", fc, 10, 8193) == []
    py = [sys.executable, str(ROOT / "python" / "cftc")]
    src = SYSTEMS / "lorenz63-rk4-fp64.cftl"
    r = subprocess.run(py + [str(src), "--steps", "2", "--out",
                             str(tmp_path / "sw")], capture_output=True,
                       text=True)
    assert r.returncode == 0, r.stderr
    for name in REV8:
        out = tmp_path / name
        r = subprocess.run(py + [str(src), "--steps", "2", "--target", name,
                                 "--out", str(out)],
                           capture_output=True, text=True)
        assert r.returncode == 0, (name, r.stderr)
        for ext in ("cftp", "bank"):
            assert (out / f"lorenz63-rk4-fp64.{ext}").read_bytes() == \
                (tmp_path / "sw" / f"lorenz63-rk4-fp64.{ext}").read_bytes()
        m = json.loads((out / "lorenz63-rk4-fp64.manifest.json").read_bytes())
        assert m["target"]["name"] == name
        assert m["target"]["scratch_depth"] == T.get(name).scratch_depth
        assert m["accepted_by"] == T.names()
    r = subprocess.run(py + ["--targets"], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    lines = {ln.split()[0]: ln for ln in r.stdout.splitlines() if ln}
    for name in REV8:
        t = T.get(name)
        assert f"insns {1 << 24:>10,}" in lines[name], lines[name]
        assert f"scratch {t.scratch_depth:>5,}" in lines[name], lines[name]
        assert f"features 0x{t.seq_features:x}" in lines[name], lines[name]


def _routine_for(text, name):
    """A routine source compiled for a revision-8 target, by name:
    FLAG_CONTROL among its needs, the manifest naming the target, and
    accepted_by `sw` and the three."""
    c = cftc.compile_text(text, 2, target=name, source="src.cftl")
    assert "FLAG_CONTROL" in c.features
    assert c.accepted_by == ["sw", *REV8]
    assert c.manifest["target"]["name"] == name
    assert c.manifest["target"]["max_insns"] == 1 << 24
    return c


@pytest.mark.parametrize("case", list(ROUTINE))
def test_routines_compile_for_the_revision_8_quad(case):
    """The quad publishes FLAG_CONTROL, without R21, so every routine
    source compiles for it - the image and bank the same bytes as for sw,
    one image serving every target that takes it - where revision 7's
    targets refuse it `target-feature`."""
    text, _line = ROUTINE[case]
    base = cftc.compile_text(text, 2, source="src.cftl")
    c = _routine_for(text, "u50-rev8-quad")
    assert c.image == base.image and c.bank == base.bank


def test_routines_compile_for_every_revision_8_target():
    """...and for the single and the deep single, which publish it too: the
    target is read only for its refusals, so one source shows it."""
    text, _line = ROUTINE["a quotient"]
    images = {_routine_for(text, name).image for name in REV8}
    assert images == {cftc.compile_text(text, 2, source="src.cftl").image}


def test_program_capacity_on_revision_8s_targets():
    """On every revision-8 target a routine image passes the feature check,
    and the capacity after it is refused by name: program-capacity, never
    target-feature. Each target holds 2^24 instructions (the words test),
    and an image past that is not one a test compiles, so the refusal is
    held at each target's own fields with its instruction capacity one
    under the image's size; at the size itself it compiles."""
    import dataclasses
    text, _line = ROUTINE["a quotient"]
    n = len(cftc.compile_text(text, 2).image_obj.insns)
    for name in REV8:
        t = T.get(name)
        with pytest.raises(lang.Refusal) as e:
            cftc.compile_text(text, 2,
                              target=dataclasses.replace(t, max_insns=n - 1))
        assert e.value.name == "program-capacity", str(e.value)
        assert f"{n:,} instructions and {name} holds {n - 1:,}" in \
            e.value.sentence
        cftc.compile_text(text, 2, target=dataclasses.replace(t, max_insns=n))


def _lane_chain(k):
    """A state and k lane params, each read once: k + 1 scratch slots, in a
    chain that compiles in time linear in k (a wide step's is about
    quadratic: 36 s at 4,097 slots on the desktop, against 2.4 s here)."""
    lines = ["system lanes", "format fp64", "state x"]
    lines += [f"lane param p{j} = 1" for j in range(k)]
    lines += ["next x = x + " + " + ".join(f"p{j}" for j in range(k)),
              "step map"]
    return "\n".join(lines) + "\n"


@pytest.mark.parametrize("name", REV8)
def test_scratch_capacity_one_past_each_revision_8_depth(name):
    """One slot past each target's depth is refused `scratch-capacity`, by
    name, the target named as the command line names it, the sentence
    giving the slots needed, the target and its depth; the deep single
    takes the quad's depth plus one."""
    d = T.get(name).scratch_depth
    with pytest.raises(lang.Refusal) as e:
        cftc.compile_text(_lane_chain(d), 1, target=name)
    assert e.value.name == "scratch-capacity", str(e.value)
    assert f"needs {d + 1:,} scratch slots" in e.value.sentence
    assert f"{name} has {d:,}" in e.value.sentence
    if name == "u50-rev8-deep":
        quad = T.get("u50-rev8-quad").scratch_depth
        c = cftc.compile_text(_lane_chain(quad), 1, target=name)
        assert c.program.slots_used == quad + 1


# ---- M1's build, item 4: the math library's six as routines -------------------
# cftc carries exp, expm1, exp2, log, log1p and log2 since M1's build, item 4,
# at its output version 6: a run-time call is inlined as its routine -
# mathlib.py's fragment, handed out by routines.fragment - quiet, then a RAISE
# of its flag word, whose bit 7 MARKS the lane where the routine's in-lane test
# cannot decide the last bit; a function of a constant folds in the language
# and compiles as the constant it is. From item 3 until item 4 the interim
# `math-library` refused every source naming one (MATHLIB, below: the sources
# it refused here at 97076f3): each now compiles, its run-time six refused
# `target-feature` on the targets without flag control, and on a host without
# mpmath `routine-unavailable` (a child process, below). Never exit 70.

MATHLIB = {   # name: (source, its run-time ops) - math-library's at 97076f3
    "exp at run time": ("system e\nformat fp64\nstate x\nnext x = exp(x)\n"
                        "step map\n", ["exp"]),
    "the six, rk4, two vectors": (
        "system six\nformat fp256\nround rdn\nstate x, y\ntangent v, w\n"
        "let u = log1p(x * x) + log2(abs(y) + 1)\n"
        "d/dt x = expm1(-x) + exp2(y) * u\nd/dt y = log(abs(x) + 2) - exp(y)\n"
        "step rk4, h = 1/16\n",
        ["exp", "expm1", "exp2", "log", "log1p", "log2"]),
    "a fold alone": ("system f\nformat fp32\nstate x\n"
                     "next x = x * exp(0) + log2(1/8)\nstep map\n", []),
    "a fold in a const": ("system c\nformat fp64\nstate x\n"
                          "const k = exp2(-3) + log(1)\nnext x = x * k\n"
                          "step map\n", []),
    "a fold in a default": ("system d\nformat fp128\nstate x\n"
                            "param p = log1p(0) + expm1(0) + 1\n"
                            "next x = x * p\nstep map\n", []),
    "a fold in h": ("system h\nformat fp64\nstate x\nd/dt x = -x\n"
                    "step euler, h = exp2(-4)\n", []),
    # statements come in any order: a written tangent or an expansion block
    # above the equations holds the first call (verifier-VL4's lesson)
    "a written tangent first": (
        "system t\nformat fp64\nstate x, y\ntangent v\n"
        "next v.x = v.x\nnext v.y = exp(x) * v.x\nnext x = x\n"
        "next y = exp(x)\nstep map\n", ["exp"]),
    "an expansion block first": (
        "system b\nformat fp64\nstate x\nstep euler, h = 0.125\n"
        "expansion\n  next x = fma(h, log(x), x)\nend\nd/dt x = log(x)\n",
        ["log"]),
}
# the targets without flag control (CAPS2[14]): revision 7's and the
# round-2 and open-core builds
NO_FLAG_CONTROL = ("u50-rev7", "u50-rev7-quad", "u50-round2", "open-core")
needs_mpmath = pytest.mark.skipif(not have_mpmath(), reason=NO_MPMATH)


def _math_lanes(g, seed):
    """Lanes for an image of the six: rationals of either sign near 1 and
    near 0 (logarithms below their domain among them), a zero state, a
    signalling NaN, the smallest subnormal; with tangent vectors, a tangent
    for each. None of these is a structured family's argument at its
    attribute, so a lane is marked only at the rate the routines' bound
    gives (2^-43.5 a call at fp64)."""
    fmt = g.fmt
    rng = random.Random(seed)

    def val():
        return K.round_once(fmt, sf.RND_RNE,
                            Fraction(rng.randint(-900, 900), 397))[0]
    n = g.n_primal
    states = [[val() for _ in range(n)] for _ in range(4)]
    states += [[0] * n, [sf.snan_bits(fmt)] * n, [1] * n]
    tans = None
    if g.tangent:
        tans = [[[val() for _ in range(n)] for _ in g.tangent]
                for _ in states]
    return states, tans


def _held_lanes(c, states, tans, steps):
    """The image on seq.py against lang.run, lane by lane, each lane alone
    through the interpreter: an unmarked lane's states, tangents and lane
    byte's five flags equal the interpreter's, bit for bit; a marked lane's
    values are a guess, compared only as one (docs/LANGUAGE.md, "A marked
    lane") and counted. -> (the seq.py Result, the marked lanes)."""
    r = c.run(states, tangents=tans)
    m, n, N = c.ir.m, c.ir.n_primal, c.ir.n_state
    marked = []
    for k, st in enumerate(states):
        byte = r.lane_flags[k]
        if byte & seq.LANE_MARKED:
            marked.append(k)
            continue
        kw = {"tangents": [tans[k]]} if tans is not None else {}
        ref = lang.run(c.graph, [st], steps, **kw)
        out = r.scratch_out[k * m:(k + 1) * m]
        assert out[:n] == ref.states[0], (k, "states")
        if tans is not None:
            assert out[n:N] == [v for vec in ref.tangents[0] for v in vec]
        assert byte & seq.LANE_FLAGS_IEEE == ref.flags, (k, "flags")
        assert not byte & (seq.LANE_DEPOSIT_OVERFLOW | seq.LANE_SCRATCH_RANGE)
    assert bool(r.status & seq.STATUS_MARKED) == bool(marked)
    if not marked:
        ref = lang.run(c.graph, states, steps,
                       **({"tangents": tans} if tans is not None else {}))
        assert r.flags == ref.flags
    return r, marked


@pytest.mark.parametrize("case", list(MATHLIB))
def test_what_math_library_refused_now_compiles(case):
    """Each source the interim `math-library` refused at 97076f3 compiles
    (cftc's output version 6): its run-time six inlined as routines - the
    image holding QUIET, ENDQUIET and RAISE, needing FLAG_CONTROL, the same
    bytes for sw and revision 8's targets, accepted by those and refused
    `target-feature` by name, naming the bit and its routines, on the
    targets without it - and a source of folds alone a plain image every
    target takes. A graph read from its bytes compiles to the same image.
    With mpmath it runs on seq.py as lang.run runs it, lane by lane."""
    text, ops = MATHLIB[case]
    g = lang.compile_text(text, "src.cftl").graph
    assert cftc.math_nodes(g) == ops
    # the source holding all six (4 s a compile at fp256) is compiled for
    # sw and refused on one target; the others show every target
    heavy = len(ops) > 1
    c = cftc.compile_text(text, 3, source="src.cftl")
    assert c.version == 6
    for t in () if heavy else REV8 + ("sw:4096",):
        ct = cftc.compile_text(text, 3, target=t, source="src.cftl")
        assert (ct.image, ct.bank) == (c.image, c.bank), t
    no_fc = NO_FLAG_CONTROL[:1] if heavy else NO_FLAG_CONTROL
    if ops:
        assert "FLAG_CONTROL" in c.features
        assert c.accepted_by == ["sw", *REV8]
        assert set(c.manifest["routines"]["calls"]) - {"div", "sqrt"} == \
            set(ops)
        names = {asm.CTRL_NAMES.get(asm.decode(w)["op"])
                 for w in c.image_obj.insns if asm.decode(w)["ctrl"]}
        assert {"quiet", "endquiet", "raise"} <= names
        for t in no_fc:
            with pytest.raises(lang.Refusal) as e:
                cftc.compile_text(text, 3, target=t, source="src.cftl")
            assert e.value.name == "target-feature", (t, str(e.value))
            assert "FLAG_CONTROL (CAPS2[14])" in e.value.sentence
            assert all(op in e.value.sentence for op in ops)
    else:
        assert "routines" not in c.manifest and \
            "FLAG_CONTROL" not in c.features
        assert c.accepted_by == T.names()
        for t in no_fc:
            assert cftc.compile_text(text, 3, target=t,
                                     source="src.cftl").image == c.image
    if not heavy:
        back = lang.StepGraph.from_bytes(g.to_bytes())
        assert cftc.compile_graph(back, 3, source="src.cftl").image == c.image
    if ops and not have_mpmath():
        pytest.skip(f"the interpreter's run of {', '.join(ops)}: {NO_MPMATH}")
    states, tans = _math_lanes(c.ir, case)
    _held_lanes(c, states, tans, 3)


def test_the_six_through_the_command_line(tmp_path):
    """sw: exit 0, the files, the six's regions in the text; revision 8's
    quad: exit 0, the same image and bank; a revision-7 target: exit 3,
    `target-feature`, nothing written; never 70."""
    py = [sys.executable, str(ROOT / "python" / "cftc")]
    src = tmp_path / "e.cftl"
    src.write_bytes(MATHLIB["exp at run time"][0].encode("ascii"))
    r = subprocess.run(py + [str(src), "--steps", "2", "--out",
                             str(tmp_path / "a")], capture_output=True,
                       text=True)
    assert r.returncode == 0, r.stderr
    cfta = (tmp_path / "a" / "e.cfta").read_text(encoding="ascii")
    assert "; exp(x): mathlib's exp routine, run quiet\n" in cfta
    assert "\n  raise    r" in cfta and "\n    add.rup  r" in cfta
    r = subprocess.run(py + [str(src), "--steps", "2", "--target",
                             "u50-rev8-quad", "--out", str(tmp_path / "q")],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    for ext in ("cftp", "bank"):
        assert (tmp_path / "q" / f"e.{ext}").read_bytes() == \
            (tmp_path / "a" / f"e.{ext}").read_bytes(), ext
    r = subprocess.run(py + [str(src), "--steps", "2", "--target",
                             "u50-rev7", "--out", str(tmp_path / "b")],
                       capture_output=True, text=True)
    assert r.returncode == 3, r.stderr
    assert r.stderr.startswith("cftc: refused target-feature: ")
    assert "internal error" not in r.stderr and not (tmp_path / "b").exists()


_NO_MPMATH_CFTC = r"""
import hashlib, json, subprocess, sys
sys.modules["mpmath"] = None            # import mpmath raises ImportError
sys.path.insert(0, sys.argv[1])
import cftc
from cftc import callloop
from cft_golden import lang
cases = json.loads(sys.argv[2])
out = {}
for name, (text, ops) in cases.items():
    # a step that loops its routines (the constant lowered) builds the
    # fragments of the routines it holds, and only those
    callloop.CALL_LOOP_ABOVE = 0 if name.endswith("looped") else 32768
    for target in ("sw", "u50-rev8", "u50-rev7"):
        for steps in (3, 0):
            try:
                c = cftc.compile_text(text, steps, target=target,
                                      source="src.cftl")
                out[f"{name} {target} {steps}"] = {
                    k: hashlib.sha256(v).hexdigest()
                    for k, v in c.files().items()}
            except lang.Refusal as e:
                out[f"{name} {target} {steps}"] = [e.name, e.line,
                                                   e.sentence]
print(json.dumps(out, sort_keys=True))
"""


def test_routine_unavailable_without_mpmath(tmp_path):
    """With mpmath taken away in a child process (sys.modules: simulated,
    not a host without it): a source with a run-time call of the six is
    refused `routine-unavailable` on every target - on a revision-7 target
    too, where with mpmath it is `target-feature`, which reads the built
    image - with no line, its sentence naming the functions, mathlib.py and
    mpmath; at 0 steps `segment-steps` first, the arguments' refusal. A
    source of folds alone, and one that divides, compile there to the very
    bytes they compile to here - a step whose divisions and roots run in a
    call loop among them. The command line: exit 3, the name, nothing
    written, never 70."""
    cases = {k: MATHLIB[k] for k in ("exp at run time", "a fold alone",
                                     "a fold in h")}
    cases["a quotient"] = (ROUTINE["a quotient"][0], [])
    cases["kepler, looped"] = (KEPLER_RK4, [])
    script = tmp_path / "nompmath.py"
    script.write_text(_NO_MPMATH_CFTC, encoding="utf-8")
    r = subprocess.run([sys.executable, str(script), str(ROOT / "python"),
                        json.dumps(cases)], capture_output=True, text=True,
                       cwd=str(tmp_path))
    assert r.returncode == 0, r.stderr
    got = json.loads(r.stdout)
    for name, (text, ops) in cases.items():
        for target in ("sw", "u50-rev8", "u50-rev7"):
            zero = got[f"{name} {target} 0"]
            assert zero[0] == "segment-steps", (name, target, zero)
            res = got[f"{name} {target} 3"]
            if ops:
                assert res[:2] == ["routine-unavailable", None], res
                assert res[2].startswith("this system computes exp at run "
                                         "time"), res
                assert "mathlib.py" in res[2] and "mpmath" in res[2]
                assert "target-feature" in res[2]
                continue
            if name in ("a quotient", "kepler, looped") and \
                    target == "u50-rev7":
                assert res[0] == "target-feature", res
                continue
            from cftc import callloop
            with pytest.MonkeyPatch.context() as m:
                if name.endswith("looped"):
                    m.setattr(callloop, "CALL_LOOP_ABOVE", 0)
                here = cftc.compile_text(text, 3, target=target,
                                         source="src.cftl")
                if name.endswith("looped"):
                    assert here.looped
            assert res == {k: hashlib.sha256(v).hexdigest()
                           for k, v in here.files().items()}, (name, target)
    # the command line, mpmath taken away the same way
    src = tmp_path / "e.cftl"
    src.write_bytes(MATHLIB["exp at run time"][0].encode("ascii"))
    run = ("import runpy, sys; sys.modules['mpmath'] = None; "
           "sys.argv = ['cftc'] + sys.argv[1:]; "
           f"runpy.run_path({str(ROOT / 'python' / 'cftc')!r}, "
           f"run_name='__main__')")
    r = subprocess.run([sys.executable, "-c", run, str(src), "--steps", "2",
                        "--target", "u50-rev7", "--out", str(tmp_path / "o")],
                       capture_output=True, text=True)
    assert r.returncode == 3, (r.returncode, r.stderr)
    assert r.stderr.startswith("cftc: refused routine-unavailable: "), \
        r.stderr
    assert f"{src.as_posix()}: this system computes exp" in \
        r.stderr.replace("\\", "/") and "internal error" not in r.stderr
    assert not (tmp_path / "o").exists()


@needs_mpmath
def test_a_marked_lane_through_a_compiled_image():
    """exp at fp64 under rne, on lanes holding a structured centre whose
    last bit the routine cannot decide (mathlib_family.FAMILY's first,
    2^-53) and an ordinary argument: through the image's RAISE the centre's
    lane is MARKED - R23's byte [7] - and STATUS[6] set; its guess is
    compared only as a guess; the ordinary lane is unmarked and the
    interpreter's, bit for bit with its flags."""
    import mathlib_family as fam
    fmt = FORMATS["fp64"]
    c = cftc.compile_text(MATHLIB["exp at run time"][0], 1, source="e.cftl")
    centre = fam.FAMILY["exp"]["fp64"]["rne"][0]
    assert centre == (1, 53)
    x = fam.argument(fmt, centre)
    plain = K.round_once(fmt, sf.RND_RNE, Fraction(1, 3))[0]
    r, marked = _held_lanes(c, [[plain], [x]], None, 1)
    assert marked == [1]
    assert r.lane_flags[1] & seq.LANE_MARKED and r.status & seq.STATUS_MARKED
    assert not r.lane_flags[0] & seq.LANE_MARKED
    # the guess, compared as a guess: the definition's value or a neighbour
    ref = lang.run(c.graph, [[x]], 1).states[0][0]
    assert abs(r.scratch_out[c.ir.m] - ref) <= 1


def _rule_nodes(c, op, args):
    """The step's language nodes computing `op` of `args` - each wanted
    operand ("c", a const's exact value) or ("n", the op of the node it
    is: a routine's for a routine's result) - in the lowered step, and the
    image's ALU instructions computing them (the expanded step's nodes,
    where a routine's result is the value of one of its instructions)."""
    low, x = c.lowered, c.program.x

    def low_op(j):
        return low.nodes[j].op

    def x_op(j):
        nd = x.nodes[j]
        if getattr(nd, "kind", "lang") == "quiet":
            return low.nodes[nd.routine].op
        return nd.op

    def matches(ref, want, op_of):
        if want[0] == "c":
            return ref[0] == "c" and low.graph.const[ref[1]][0] == want[1]
        return ref[0] == "n" and op_of(ref[1]) == want[1]
    nodes = [j for j, nd in enumerate(low.nodes) if nd.op == op and
             len(nd.args) == len(args) and all(
                 matches(a, w, low_op) for a, w in zip(nd.args, args))]
    alu = []
    for ins in c.program.body:
        nd = x.nodes[ins.node] if ins.node is not None else None
        if ins.kind != "alu" or getattr(nd, "kind", "lang") != "lang" or \
                nd.op != op or len(nd.args) != len(args):
            continue
        if all(matches(a, w, x_op) for a, w in zip(nd.args, args)):
            alu.append(ins)
    return nodes, alu


@needs_mpmath
def test_the_primal_only_values_are_computed_once_a_call():
    """The six's tangent rules read values of the primal alone - 1 + r for
    expm1, L r for exp2, r == r for the three logarithms, L a for log2 and
    1 + a for log1p - which no tangent reads (ML's report: the compiler's
    job). With two tangent vectors each is one node of the lowered step and
    one instruction of the image a call, not one a vector; and the routine
    itself runs once a call, its result shared by the primal and both
    vectors."""
    one = Fraction(1)
    for fn in cftc.MATH:
        text = (f"system p\nformat fp64\nstate x, y\ntangent v, w\n"
                f"next x = {fn}(x * y)\nnext y = y\nstep map\n")
        c = cftc.compile_text(text, 2, source="p.cftl")
        assert c.manifest["routines"]["calls"][fn] == 1, fn
        L = c.graph.const
        lv = [v for v, _f, _b, _fl in L if v != one and v not in (0, -1, 2)]
        want = []
        if fn == "expm1":
            want.append(("add", (("c", one), ("n", fn))))
        if fn == "exp2":
            want.append(("mul", (("c", lv[0]), ("n", fn))))
        if fn.startswith("log"):
            want.append(("cmpeq", (("n", fn), ("n", fn))))
        if fn == "log1p":
            want.append(("add", (("c", one), ("n", "mul"))))
        if fn == "log2":
            want.append(("mul", (("c", lv[0]), ("n", "mul"))))
        for op, args in want:
            nodes, alu = _rule_nodes(c, op, args)
            if not nodes:
                # an operand in the other order
                nodes, alu = _rule_nodes(c, op, args[::-1])
            assert len(nodes) == 1 and len(alu) == 1, (fn, op, nodes)
        states, tans = _math_lanes(c.ir, f"once {fn}")
        _held_lanes(c, states, tans, 2)


@needs_mpmath
def test_a_call_loop_of_the_six(monkeypatch):
    """With the constant lowered, a step holding expm1 and log1p three times
    each loops both batches - an exp-family and a log-family routine, one
    copy each in a REPEAT over records of one slot - held by the internal
    check, and runs on seq.py as lang.run runs it; the batches go in the
    stated order, largest first, ties by depth and then by the eight's
    order (callloop.ORDER)."""
    from cftc import callloop
    text = ("system loop\nformat fp64\nstate x[3], y[3]\n"
            "next x[i] = expm1(x[i]) * 0.5\n"
            "next y[i] = log1p(abs(y[i])) + y[i]\nstep map\n")
    inl = cftc.compile_text(text, 2)
    assert inl.looped == []
    c = _looped(monkeypatch, text, 0)
    assert sorted(_batches(c)) == [("expm1", 1, 3), ("log1p", 1, 3)]
    sizes = {op: len(R.fragment(op, FORMATS["fp64"], sf.RND_RNE))
             for op in ("expm1", "log1p")}
    big = max(sizes, key=sizes.get)
    assert _batches(c)[0][0] == big
    loops = c.manifest["routines"]["call_loops"]["loops"]
    assert {e["op"] for e in loops} == {"expm1", "log1p"}
    assert all(e["records"][1] - e["records"][0] == 2 for e in loops)
    assert callloop.ORDER == {op: k for k, op in enumerate(R.ROUTINES)}
    states, _t = _math_lanes(c.ir, "loop six")
    _held_lanes(c, states, None, 2)


@needs_mpmath
def test_a_tie_between_batches_goes_by_the_eights_order(monkeypatch):
    """At fp128 under rdn, expm1's and exp2's fragments are one length (184
    instructions; 197 at fp256), so a step calling each three times
    has two batches of one size at one depth. The batch looped first is
    expm1's, the earlier in the eight's order (callloop.ORDER, from
    routines.ROUTINES), whichever the source writes first - where an
    order by name would loop exp2's. The constant is set one under the
    inlined step, so that one loop suffices."""
    fmt, rnd = "fp128", sf.RND_RDN
    sizes = {op: len(R.fragment(op, FORMATS[fmt], rnd))
             for op in ("expm1", "exp2")}
    assert sizes["expm1"] == sizes["exp2"], sizes   # the test's premise
    assert list(R.ROUTINES).index("expm1") < list(R.ROUTINES).index("exp2")
    real = callloop.CALL_LOOP_ABOVE
    for a, b in (("expm1", "exp2"), ("exp2", "expm1")):
        text = (f"system tie\nformat {fmt}\nround rdn\nstate x[3]\n"
                f"next x[i] = {a}(x[i]) + {b}(x[i])\nstep map\n")
        monkeypatch.setattr(callloop, "CALL_LOOP_ABOVE", real)
        inl = cftc.compile_text(text, 2, source="tie.cftl")
        assert inl.looped == []
        c = _looped(monkeypatch, text, len(inl.program.body))
        assert _batches(c) == [("expm1", 1, 3)], (a, b, _batches(c))


@needs_mpmath
def test_the_routines_words_go_in_the_eights_order():
    """The bank holds the routines' words routine by routine in the
    eight's order (lower.routine_words, through lower.routines_of), one
    slot a bit pattern, a word shared by two routines in the earlier one's
    place. So on a step holding all eight, each word slot's first owner
    never comes before the previous slot's in that order: div's words first,
    then sqrt's, then the six's - where an order by name would put sqrt's
    after the six's and exp2's before expm1's."""
    text = ("system all8\nformat fp64\nstate x\n"
            "next x = x / (abs(x) + 1) + sqrt(abs(x)) + exp(x) + expm1(x)"
            " + exp2(x) + log(abs(x) + 1) + log1p(abs(x))"
            " + log2(abs(x) + 1)\nstep map\n")
    c = cftc.compile_text(text, 2, source="all8.cftl")
    eight = list(R.ROUTINES)
    owners = [s.names[0][0] for s in c.lowered.slots if s.kind == "word"]
    assert set(owners) <= set(eight), owners
    at = [eight.index(op) for op in owners]
    assert at == sorted(at), owners
    assert owners[0] == "div" and {"sqrt", "expm1", "exp2"} <= set(owners)


@needs_mpmath
def test_the_internal_check_holds_a_routine_of_the_six():
    """Controls for check.py on an image holding exp: an instruction of its
    routine made to round under another attribute (its rdn made rne); the
    raise dropped; the raise moved inside its region; a word's bits changed
    in the bank. Each an InternalError; the image as written passes."""
    c = cftc.compile_text("system p\nformat fp64\nstate x, y\n"
                          "next x = exp(x) * y\nnext y = y + 1\nstep map\n", 2)
    insns = list(asm.Image.from_bytes(c.image).insns)
    dec = [asm.decode(w) for w in insns]

    def ctrl(k, name):
        return dec[k]["ctrl"] and asm.CTRL_NAMES.get(dec[k]["op"]) == name
    q = next(k for k in range(len(dec)) if ctrl(k, "quiet"))
    e = next(k for k in range(len(dec)) if ctrl(k, "endquiet"))
    r = next(k for k in range(len(dec)) if ctrl(k, "raise"))

    def refused(words):
        with pytest.raises(cftc.InternalError):
            cftc_check.verify(c.lowered, c.program, _image_with(c, words),
                              c.steps, c.lowered.half_bits)
    k = next(k for k in range(q, e) if not dec[k]["ctrl"]
             and dec[k]["rnd"] == sf.RND_RDN)
    w = list(insns)
    w[k] = (insns[k] & ~(0x7 << 24)) | (sf.RND_RNE << 24)
    refused(w)
    refused(insns[:r] + insns[r + 1:])
    w = list(insns)
    w[e], w[r] = w[r], w[e]
    refused(w)
    k = next(k for k, s in enumerate(c.lowered.slots) if s.kind == "word")
    c.lowered.slots[k].bits ^= 1
    with pytest.raises(cftc.InternalError):
        cftc_check.verify(c.lowered, c.program, c.image, c.steps,
                          c.lowered.half_bits)
    c.lowered.slots[k].bits ^= 1
    cftc_check.verify(c.lowered, c.program, c.image, c.steps,
                      c.lowered.half_bits)


@needs_mpmath
def test_the_internal_check_holds_each_fragment_to_its_routines_statement(
        monkeypatch):
    """check.held_fragment, the one door to every fragment the compiler
    reads, refuses a fragment made for another attribute than the one
    asked for; one breaking its routine's statement (exp's flag word made
    to carry the mark without inexact); and the golden model's own
    assertion at a fragment's making - each an InternalError naming the
    routine, never a bare AssertionError."""
    from cft_golden import routines as RR
    fmt = FORMATS["fp64"]
    good = RR.fragment
    cftc_check._HELD.clear()
    monkeypatch.setattr(RR, "fragment", lambda op, f, r: good(op, f, sf.RND_RTZ
                                                              if r == sf.RND_RNE
                                                              else r))
    with pytest.raises(cftc.InternalError) as e:
        cftc_check.held_fragment("exp", fmt, sf.RND_RNE)
    assert "is exp's at fp64 under 1" in str(e.value)
    monkeypatch.setattr(RR, "fragment", good)
    f = good("exp", fmt, sf.RND_RNE)
    bad = R.Fragment(f.op, f.fmt, f.rnd, f.inputs, list(f.body) + [
        (sf.OP_IOR, None, (f.flags, ("w", "MARKED")))], f.result,
        ("v", len(f.body)), dict(f.words, MARKED=0x80), f.stage)
    cftc_check._HELD.clear()
    monkeypatch.setattr(RR, "fragment", lambda op, f2, r: bad)
    with pytest.raises(cftc.InternalError) as e:
        cftc_check.held_fragment("exp", fmt, sf.RND_RNE)
    assert "breaks its routine's invariants" in str(e.value) and \
        "flag word's values" in str(e.value)

    def asserting(op, f2, r):
        raise AssertionError(f"{op} at {f2.name}, rnd {r}: planted")
    cftc_check._HELD.clear()
    monkeypatch.setattr(RR, "fragment", asserting)
    with pytest.raises(cftc.InternalError) as e:
        cftc_check.held_fragment("log", fmt, sf.RND_RNE)
    assert "planted" in str(e.value)
    monkeypatch.setattr(RR, "fragment", good)
    cftc_check._HELD.clear()


def test_the_bank_capacity_counts_the_sixs_words():
    """The six's words are bank slots of the routine kind, after
    division's in the eight's order: past 512 with the params, `bank-
    capacity`, its sentence naming the routines in that order; one param
    fewer compiles at exactly 512."""
    if not have_mpmath():
        pytest.skip(f"the six's fragments are built through mpmath: "
                    f"{NO_MPMATH}")

    def source(k):
        ps = ", ".join(f"p{i} = {i + 1}" for i in range(k))
        total = " + ".join(f"p{i}" for i in range(k))
        return (f"system wide\nformat fp64\nstate x, y\nparam {ps}\n"
                f"next x = log(x) / y + exp(y) + ({total})\nnext y = y\n"
                f"step map\n")
    fmt = FORMATS["fp64"]
    words = len({b for op in ("div", "exp", "log") for b in
                 R.fragment(op, fmt, sf.RND_RNE).words.values()})
    over = 512 - words + 1
    with pytest.raises(lang.Refusal) as e:
        cftc.compile_text(source(over), 2)
    assert e.value.name == "bank-capacity"
    assert (f"{over} params, 0 constants and {words} words of the routines "
            f"the compiler inlines for div, exp and log come to 513") in \
        e.value.sentence
    c = cftc.compile_text(source(over - 1), 2)
    assert len(c.lowered.slots) == 512
    kinds = [s.kind for s in c.lowered.slots]
    assert kinds.index("word") == over - 1      # after the params
    first = c.lowered.slots[kinds.index("word")]
    assert first.names[0][0] == "div"           # division's words first


def test_a_run_value_or_a_source_of_folds_compiles_as_its_constants():
    """Two of the interim refusal's known limits, closed (ML's): `--param
    p=exp(0)` compiled while a fold in the source was refused - now both
    compile, the run value byte for byte as `p = 1`; and a fold-only
    source was refused while its graph, read from its bytes, compiled -
    now both compile, to the same image as the source that writes the
    folded values."""
    text = ("system r\nformat fp64\nstate x\nparam p = 2\n"
            "next x = x * p\nstep map\n")
    one = cftc.compile_text(text, 3, params={"p": "1"})
    for v in ("exp(0)", "exp2(0)", "log2(2)", "expm1(0) + 1", "log1p(0) + 1"):
        c = cftc.compile_text(text, 3, params={"p": v})
        assert (c.image, c.bank) == (one.image, one.bank), v
    with pytest.raises(lang.Refusal) as e:
        cftc.compile_text(text, 3, params={"p": "exp(1)"})
    assert e.value.name == "irrational-constant"
    folds = cftc.compile_text(MATHLIB["a fold alone"][0], 3, stem="f")
    written = cftc.compile_text("system f\nformat fp32\nstate x\n"
                                "next x = x * 1 + -3\nstep map\n", 3,
                                stem="f")
    assert folds.graph_bytes == written.graph_bytes
    assert (folds.image, folds.bank) == (written.image, written.bank)
    back = lang.StepGraph.from_bytes(folds.graph_bytes)
    assert cftc.compile_graph(back, 3).image == folds.image
