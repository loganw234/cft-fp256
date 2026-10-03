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
* the variational equations: an image with tangent vectors run as
  lang.run runs it, its lane block and manifest, the interleaved
  candidate offered only with tangents, scratch-capacity naming the
  tangent's slots.
"""

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
from cftc import check as cftc_check             # noqa: E402
from cftc import targets as T                    # noqa: E402
from cft_golden import FORMATS, asm, lang        # noqa: E402
from cft_golden import softfloat as sf           # noqa: E402
from cft_golden.lang import constants as K       # noqa: E402

SYSTEMS = ROOT / "programs" / "systems"


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
    assert T.names() == ["sw", "u50-rev7", "u50-rev7-quad", "u50-round2",
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


def test_revision_8s_bits_are_published_by_sw_alone():
    """Revision 8's four bits (ABI 0.17, cft.h): the software targets
    publish them, as libcft's software handle does (0x7ff1f), and no
    revision-7 target does - so an image needing FLAG_CONTROL (R24), like
    one needing AUGADD or SCRATCH_STEP, is accepted by `sw` alone, and
    refused as target-feature, naming the CAPS2 bit, on the others."""
    r8 = {"AUGADD": "CAPS2[11]", "SCRATCH_STEP": "CAPS2[12]",
          "LANE_FLAGS": "CAPS2[13]", "FLAG_CONTROL": "CAPS2[14]"}
    for name, place in r8.items():
        assert T.CAPS_PLACE[name] == place
        assert T.get("sw").seq_features & T.FEATURE_BITS[name]
        assert T.get("sw:2048").seq_features & T.FEATURE_BITS[name]
        for t in ("u50-rev7", "u50-rev7-quad", "u50-round2", "open-core"):
            assert name not in T.get(t).features(), (t, name)
    assert T.FEATURE_BITS["LANE_FLAGS"] == 1 << 17
    assert T.FEATURE_BITS["FLAG_CONTROL"] == 1 << 18
    from cftc import manifest as M
    assert M.accepted_by("fp64", ["FLAG_CONTROL"], 10, 0) == ["sw"]
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
    for name in cftc.NAMES:
        e = cftc.refusals.refusal(name, "a sentence")
        assert isinstance(e, lang.Refusal) and e.name == name
    with pytest.raises(cftc.InternalError):
        cftc.refusals.refusal("unused", "not the compiler's")


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


# ---- L4: run-time division and square root, refused by name until C4 ----------
# The language has them (div, sqrt) and its interpreter runs them; a tile has
# no such instruction, and the compiler inlines their routines only from
# parcel C4. Until then cftc refuses them `runtime-routine`, first, on every
# target, at the first source line holding one - never an internal error.

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


@pytest.mark.parametrize("case", list(ROUTINE))
def test_the_interim_refusal_on_every_target(case):
    """compile_text on every built-in target and sw:N, compile_graph of the
    language's graph and of a graph read from its bytes (which carries no
    lines): `runtime-routine`, at the first line in source order holding
    one, whatever its statement, before the compiler's other checks (a
    step count of 0, a target without the format) and before its own
    reading of the graph."""
    text, line = ROUTINE[case]
    g = lang.compile_text(text, "src.cftl").graph
    assert {"div", "sqrt"} & set(g.op_counts("step"))
    assert g.routine_lines[0] == line
    assert lang.StepGraph.from_bytes(g.to_bytes()).routine_lines is None
    trim = T.Target("trim", ("fp64",), 32768, 512, 2048, 1024,
                    T.TILE_FEATURES)
    for target in T.names() + ["sw:4096", "sw:32768", trim]:
        for steps in (3, 0):
            with pytest.raises(lang.Refusal) as e:
                cftc.compile_text(text, steps, target=target,
                                  source="src.cftl")
            assert (e.value.name, e.value.line, e.value.source) == \
                ("runtime-routine", line, "src.cftl"), (target, str(e.value))
    with pytest.raises(lang.Refusal) as e:
        cftc.compile_graph(g, 3, source="src.cftl")
    assert (e.value.name, e.value.line) == ("runtime-routine", line)
    back = lang.StepGraph.from_bytes(g.to_bytes())
    with pytest.raises(lang.Refusal) as e:
        cftc.compile_graph(back, 3)
    assert (e.value.name, e.value.line) == ("runtime-routine", None)
    ops = [op for op in ("div", "sqrt") if op in g.op_counts("step")]
    s = e.value.sentence
    assert s.startswith("this step ") and f"({', '.join(ops)})" in s, s
    assert "parcel C4" in s and "lang.run" in s
    for op, routine in (("div", "divfull"), ("sqrt", "sqrtfull")):
        assert (routine in s) == (op in ops), s
    # and the interpreter runs it
    fmt = g.fmt
    lanes = [[K.round_once(fmt, sf.RND_RNE, Fraction(v, 7))[0]] * g.n_state
             for v in (3, 11)]
    kw = {"tangents": [[lane] * len(g.tangent) for lane in lanes]} \
        if g.tangent else {}
    assert len(lang.run(g, lanes, 2, **kw).states) == 2


def test_the_interim_refusal_through_the_command_line(tmp_path):
    """Exit 3 with the name and the line, nothing written, never 70."""
    py = [sys.executable, str(ROOT / "python" / "cftc")]
    for k, (case, (text, line)) in enumerate(ROUTINE.items()):
        src = tmp_path / f"routine{k}.cftl"
        src.write_bytes(text.encode("ascii"))
        out = tmp_path / f"out{k}"
        r = subprocess.run(py + [str(src), "--steps", "2", "--target",
                                 "u50-rev7-quad", "--out", str(out)],
                           capture_output=True, text=True)
        assert r.returncode == 3, (case, r.returncode, r.stderr)
        assert r.stderr.startswith("cftc: refused runtime-routine: "), r.stderr
        assert f"routine{k}.cftl:{line}: this step " in r.stderr, r.stderr
        assert "internal error" not in r.stderr
        assert not out.exists()


def test_divisions_and_roots_that_fold_compile():
    """A constant over a constant and the root of a rational's square fold
    (L4), so a system holding only those compiles, and its image equals
    the interpreter."""
    text = ("system f\nformat fp64\nstate x, y\nnext x = x * (8/3)\n"
            "next y = fma(y, sqrt(9/4), x / (1 + 1) * 0 + x * (1/3))\n"
            "step map\n")
    with pytest.raises(lang.Refusal) as e:      # x / (1 + 1) divides
        cftc.compile_text(text, 3)
    assert (e.value.name, e.value.line) == ("runtime-routine", 5)
    text = text.replace("x / (1 + 1) * 0 + ", "")
    c = cftc.compile_text(text, 3)
    assert "div" not in c.graph.op_counts() and \
        "sqrt" not in c.graph.op_counts()
    lanes = [[K.round_once(c.ir.fmt, sf.RND_RNE, Fraction(v, 9))[0]] * 2
             for v in (2, -5, 13)]
    r = c.run(lanes)
    ref = lang.run(c.graph, lanes, 3)
    assert [r.scratch_out[k * c.ir.m:k * c.ir.m + 2] for k in range(3)] == \
        ref.states and r.flags == ref.flags


# ---- the variational equations (L3) -----------------------------------------
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
