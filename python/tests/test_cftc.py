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
  damaged image, and the command line's exits;
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
    assert T.get("sw").seq_features == 0x1ff1f
    assert T.get("sw:2048").scratch_depth == 2048
    for bad in ("sw:0", "sw:3", "sw:65536", "sw:0256", "u51"):
        assert T.get(bad) is None
    need = {"BANK_PTR", "SCRATCH", "SCRATCH_IO", "SCRATCH_STRICT", "REGS32",
            "WIDE_CONST", "KX9"}
    for t in T.BUILTIN.values():
        assert need <= set(t.features()), t.name


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


def test_a_step_count_past_the_digit_limit_is_refused_by_name():
    """segment-steps formatted the count with repr(), so a count past
    Python's 4,300-digit limit raised a bare ValueError (verifier-VI)."""
    src = (SYSTEMS / "lorenz63-rk4-fp64.cftl").read_bytes().decode("ascii")
    with pytest.raises(lang.Refusal) as e:
        cftc.compile_text(src, 10 ** 5000)
    assert e.value.name == "segment-steps"
    assert len(str(e.value)) < 400


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
