# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""exp, exp2, expm1, log, log2 and log1p as routines, golden-first (step 6,
M1's build, parcels E1, MB1 and MB2): python/cft_golden/mathlib.py held to the
study's section 8, items 1 to 5 (docs/studies/M1-exp-log.md), quick enough for
the golden stage; the larger runs are python/tests/mathlib_runs.py.

  interface   fragment() returns C4's Fragment shape, specialised, cached,
              refused by name for anything but those six; evaluate() one
              lane
  proved      the widened invariants of every fragment (the flag word's
              values, the live cap, the attributes), each shown able to
              fail; the instruction, word and live counts; the error-free
              sums; that every fragment, fp32's included, fits seq.py's
              registers through routines.program, where the design's order
              does not
  reorder     the scheduled fragments are the design's, reordered: the
              order-free digest of the dataflow graph is the design's, and
              exp's, exp2's and expm1's are the ones they had before the log
              family (exp's at 1337a13, the other two at f22e8d2)
  item 1      every lane of the transcend pools, and of each routine's edge
              pool (thresholds with their signs and neighbours, cell ends),
              through each fragment at every format and attribute: unmarked
              lanes equal transcend's in bits AND flag word, a mark only
              where the structured family allows, the marked guesses
              counted; and on seq.py through C4's routines.program and
              routines.run at all four formats; and the compiled shape
              (QUIET, body, ENDQUIET, RAISE) on seq.py
  item 2      |V - mpmath| / Bv under 1 at 4p + 200 bits, over random
              arguments with every bit random, over each path's largest |r|
              (and expm1's first clamped k) and over the weighted sampler;
              and VM1b's first-order budget under 1 at fp64, fp128 and fp256
              (fp32 has none)
  item 3      the mark-rate law with the bound inflated to 2^-(p+6): the 15
              cells of fp64, fp128 and fp256 under every attribute, three
              sigma, every unmarked lane right, the marked guesses counted
  item 4      the structured families as committed lists (mathlib_family):
              equal to the theory's generation; the centres and their
              neighbours of exp, expm1, log and log1p at fp64, fp128 and
              fp256, expm1's second family (x near -n ln 2) included, log's
              centres isolated (1 +- c ulp); at fp32 the census finds no
              window; exp2 and log2 have no family and are held to that
  item 5      the constants' --check, in process and as a program, with
              RECIP_SEED's 512 cells

and, for every check, a planted fault shown red in the check it is meant
for, by name: the last section. A plant is a fault of the builder
(mathlib.PLANTS), of the budget tool (mathlib_budget.PLANTS), of an
independent derivation (TOOLS), or a mutation of a fresh build or of its
fragment (MUTATIONS); none touches a module-level cache, so every test passes
alone, in any order and under pytest-xdist. Each plant also says which checks
stay green, so that "caught by name" is not "everything is red".
"""

import pathlib
import subprocess
import sys
from fractions import Fraction

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

pytest.importorskip("mpmath")

from cft_golden import FP32, FP64, FP128, FP256, routines, seq  # noqa: E402
from cft_golden import mathlib as ml  # noqa: E402
from cft_golden import softfloat as sf  # noqa: E402
from cft_golden.formats import FpFormat  # noqa: E402

import mathlib_budget as B  # noqa: E402
import mathlib_family as F  # noqa: E402
import mathlib_harness as H  # noqa: E402

RND = sf.RND_MODES
RNE, RTZ, RDN, RUP, RMM = (sf.RND_RNE, sf.RND_RTZ, sf.RND_RDN, sf.RND_RUP,
                           sf.RND_RMM)
FORMATS = (FP32, FP64, FP128, FP256)
DOUBLE = (FP64, FP128, FP256)
FUNCS = ml.NAMES
EXP_FUNCS = ml.EXP_NAMES
LOG_FUNCS = ml.LOG_NAMES
PYTHON_DIR = pathlib.Path(__file__).resolve().parents[1]


def fid(v):
    return v.name


def rid(v):
    return sf.RND_NAMES[v]


# MEASURED (parcel MB1's entry): the instructions, bank words and values live
# of each fragment, by routine and format, in the order rne, rtz, rdn, rup,
# rmm. The instruction and word counts of exp are E1's (382, 71 ... at fp32;
# the study's section 5.1 gives the same at fp128 and fp256, and fp32's 382 at
# G = 40, though its fp64 counts are at G = 46: one more instruction than
# G = 44's); the live counts are the scheduled order's (E1 pinned 34 / 33 and
# 23 / 22, the design's order). A change here is a change of design.
SHAPE = {
    "exp": {
        "fp32": ((382, 71, 19), (380, 71, 19), (380, 71, 19), (379, 70, 19),
                 (382, 71, 19)),
        "fp64": ((180, 63, 11), (178, 63, 11), (178, 63, 11), (177, 62, 11),
                 (180, 63, 11)),
        "fp128": ((188, 72, 11), (186, 72, 11), (186, 72, 11), (185, 71, 11),
                  (188, 72, 11)),
        "fp256": ((201, 85, 11), (199, 85, 11), (199, 85, 11), (198, 84, 11),
                  (201, 85, 11)),
    },
    "exp2": {
        "fp32": ((371, 72, 20), (369, 72, 20), (369, 72, 20), (368, 71, 20),
                 (373, 72, 20)),
        "fp64": ((178, 64, 13), (176, 64, 13), (176, 64, 13), (175, 63, 13),
                 (180, 64, 13)),
        "fp128": ((186, 73, 13), (184, 73, 13), (184, 73, 13), (183, 72, 13),
                  (188, 73, 13)),
        "fp256": ((199, 86, 13), (197, 86, 13), (197, 86, 13), (196, 85, 13),
                  (201, 86, 13)),
    },
    "expm1": {
        "fp32": ((405, 71, 21), (408, 74, 21), (406, 72, 21), (407, 73, 21),
                 (405, 71, 21)),
        "fp64": ((176, 65, 13), (179, 68, 13), (177, 66, 13), (178, 67, 13),
                 (176, 65, 13)),
        "fp128": ((183, 72, 13), (186, 75, 13), (184, 73, 13), (185, 74, 13),
                  (183, 72, 13)),
        "fp256": ((196, 85, 13), (199, 88, 13), (197, 86, 13), (198, 87, 13),
                  (196, 85, 13)),
    },
    # the log family (parcel MB2, MEASURED): the attribute moves only log1p's
    # tiny path, whose underflow at x = +2^emin holds a compare and a select
    # under rtz and rdn; the live counts are the scheduled order's (the design's
    # order keeps 22, 21 and 24 at fp32 and 16, 14 and 18 at the double word)
    "log": {
        "fp32": ((379, 77, 19), (379, 77, 19), (379, 77, 19), (379, 77, 19),
                 (379, 77, 19)),
        "fp64": ((186, 74, 13), (186, 74, 13), (186, 74, 13), (186, 74, 13),
                 (186, 74, 13)),
        "fp128": ((208, 90, 13), (208, 90, 13), (208, 90, 13), (208, 90, 13),
                  (208, 90, 13)),
        "fp256": ((238, 120, 13), (238, 120, 13), (238, 120, 13),
                  (238, 120, 13), (238, 120, 13)),
    },
    "log2": {
        "fp32": ((391, 77, 17), (391, 77, 17), (391, 77, 17), (391, 77, 17),
                 (391, 77, 17)),
        "fp64": ((180, 74, 13), (180, 74, 13), (180, 74, 13), (180, 74, 13),
                 (180, 74, 13)),
        "fp128": ((202, 90, 13), (202, 90, 13), (202, 90, 13), (202, 90, 13),
                  (202, 90, 13)),
        "fp256": ((232, 120, 13), (232, 120, 13), (232, 120, 13),
                  (232, 120, 13), (232, 120, 13)),
    },
    "log1p": {
        "fp32": ((431, 80, 20), (433, 80, 20), (433, 80, 20), (431, 80, 20),
                 (431, 80, 20)),
        "fp64": ((220, 77, 12), (222, 77, 12), (222, 77, 12), (220, 77, 12),
                 (220, 77, 12)),
        "fp128": ((242, 93, 12), (244, 93, 12), (244, 93, 12), (242, 93, 12),
                  (242, 93, 12)),
        "fp256": ((272, 123, 12), (274, 123, 12), (274, 123, 12),
                  (272, 123, 12), (272, 123, 12)),
    },
}
# exp's dataflow graph at 1337a13, before the reorder: dag_digest of each
# fragment, rne, rtz, rdn, rup, rmm. MEASURED by the same function on the
# exported tree of that commit; the scheduled fragments have the same digests,
# so exp's instructions, operand for operand and attribute for attribute, are
# the ones E1 built, and only their order moved.
EXP_DIGESTS = {
    "fp32": (
        "5b74611e554894c07a790d13147055c179fba065a41deacfcf6e6bef362acfec",
        "a25bfe4a7ce327efa5c78bc2cdece0729d804b79931b41aac29ff34a6ab10e92",
        "a53fe40ab0a8041969011171c4bc46c58f2d8bd2af06c50662f4ee0bcd517b45",
        "3773f72cb470387673cd077f16be9ea2916280b3d6d841e3c3dda5069c7eb0d7",
        "ce4ed8d27f080b1e932f4ca17ef38a9092355976d82ed3370fd6c74d427db65a",
    ),
    "fp64": (
        "341bc67ff5cb7ed1d944e371878a3184ff972edd781a8a4a289e5ab2a86c9e56",
        "a09a9b802873279e5c4b3a8283a93a627f570263b3697789910e73d603cf2f54",
        "62260090528e8a3169abb7dc9808344c9626ff796a273104083f08407a83cd29",
        "d8222e266fd287c1e63ecb90dfdd52d2aa8664a6b850d986bef7da1d04c25212",
        "b0e354ea753b5918c32d8face08334137c46709ec4df18996000405b267bb3b8",
    ),
    "fp128": (
        "bade641ea8911338c605c9218346ff48439e53832c62dd0167c6711327bf2b41",
        "ad0f72431167c9923188c35def0f863354d3552058d065232355e8580fc62c30",
        "e981e8d4afbd769a02010bb140afad879f63ae475bb50de546f3bba121033555",
        "908fcfed6ccf29bfe7bcd3498f6b97da668190e03040a8fefd2c96aa88b8387a",
        "8e0fc84efc9960be0de0ac4ce10d1177edf8ff0d3a93dc5ecabff518844d85a9",
    ),
    "fp256": (
        "5bfd7036f04f83abfa008727416b2dcc9e56424568d73feb22a45ca832d710e0",
        "aa945b6d47b7f2079f970dbda56d7a1e5e7b1dd478bb8816046e742f4d7a721f",
        "e0370c2b53f7b19a210b055dc7028d1d2fb6080780ed336219e4e954522ff82d",
        "3a4a48f836d1c3d0f6757150bdc346902196d62bee9fbb8633498900c8ae48a6",
        "769722dda87ffd5a3790521f565011f04fb664746044adf234b8ddf83f75b91c",
    ),
}
# exp2's and expm1's dataflow graphs at f22e8d2, before the log family: the
# same function on the same fragments (MEASURED by dag_digest on the exported
# tree of that commit, scratch base_dump.py, with the instruction counts,
# word counts and live counts, and an order-SENSITIVE hash of each body, all
# equal at the commit that carries this table: 60 of 60 fragments), so that
# exp2 and expm1 are, operand for operand and attribute for attribute, what
# parcel MB1 merged. What the log family changed in code they share is three
# things that move no instruction: the classification's first six instructions
# split into a helper, in the same order; a phase name ("lowword") added to
# the scheduler's order, which none of their instructions carries; and a
# builder method for RECIP_SEED, which they do not call.
EXP2_DIGESTS = {
    "fp32": (
        "544aec2a58e0f954e557e364b514007571abe0ad661e1bdf6fa5f79092be6b5c",
        "bb07c87c222380fa20fcdd098e88618378b4c044ed68ea15400d1a2cacd124b6",
        "4f81803956d2d22e27675cb7bc47787245e76ad1b96720516d73f61ffd2a8190",
        "d6ca7a2cf7018beeb4fa366ec0db1a651cc5524440f40bfd2d5706546d93230b",
        "30780a03ef178f095df4ed876d97ef94801c82cf56a3c4887eaf4ac3dadfaa09",
    ),
    "fp64": (
        "d9a19cc6a63c5d06fe449868981674d781a1fb2d289db4e5fa79fb9eee0efa01",
        "23d9a6bc43cdb59672362470f712ed2350eec32cb4e0d7bf1f7e269e37bd80ac",
        "2e942637099c645257fb3979913aca6b6b89ecbed43ccea8faa96c172c4fb602",
        "224eebc78fcf10ce06835dbf9069626f42027974b77d521e8f6d11af83e54913",
        "effdb39df1aadf1a508b291867fa6d5ede367d20b2809cc6da9dea04267175bf",
    ),
    "fp128": (
        "ed37d31d2de77064d45ebd880f3c0260f7dbbfea83c4c20ddbd8e73e8ee1b336",
        "4d4eabc31ef5aca5ba895e93a510e5983f4dc2d96219a07a60abce3466c58e3a",
        "d99b705fe13bfed6eef4c8b9ead65db37a9e97613e8f1f02d79f1b67b3bda470",
        "524456ebf8dec5eddf7bc9b91cd3f69cfbec709dbf9c63cd75815970b38fa1cd",
        "f1b8d1edeefea416db865e36153a0625794988a323dd8f4cb7e8e6b50f31d7e3",
    ),
    "fp256": (
        "f6ad08ba47aa22425a4d1c97abaff58d70a66787ccc0170aa43c6be91eda0ced",
        "d29594313cb1375f0b6b9a8344a5f976b8d1efd8291f3dc8a89d102407b66c22",
        "89810282f20c0adb84b027c565e189b7d5ba96153c5b34a1eac64f2f0feb77bb",
        "9b399bd2b008eb212bf5b1e36132ce6fd395ef6b3dd0325767f5051375fd6e47",
        "f891887c0e3dc47fd70d8bfe459cd55a1ca1f558445eef07b47ad92a4765f4ce",
    ),
}
EXPM1_DIGESTS = {
    "fp32": (
        "86ec518a09fb00c5afd703a328e65d03b9ab99fb52d1ff862c7ea873a6bdb8f6",
        "73f0463520c120b2232a058e8d50ec0d2530740758d52c268763629236dc1c47",
        "5fefe6b0179f43b20170542928896382cddd342163c7c72974dc9b5ba5b3d85a",
        "c0895aa716c02f441934773cee8ec0158a6c5173dd4415c93c1f9abc88494014",
        "80e01517965eb3904ed1a2e3db9a1106f4a9152f1133eaec60cb5a38dcb70b3c",
    ),
    "fp64": (
        "ae48854f17e13e0e6a9fc85d300fd813d3ad1a805e730cc5ba81b8162dde31d1",
        "d4cb52d64b98131adfad3e819a142f7dc5ae1aaca03d14347b924b3c3a89ee8e",
        "f519c09af2e767ea8b242d9dcbfcddd5d1aceca9683931784d17cf09e446befb",
        "89c4b09ed37457c3f56de6713b064484950fde8cca6d50fe70a8a67b7089043e",
        "818d5d280878413c0ebc90e23aa7663114f8f2c089a4170212eac2a88041c907",
    ),
    "fp128": (
        "ee12accb485f7300021cf51c00900d80603258b2a92bfa113953efc311b413de",
        "789157e7ea2ed63b0bfbd95761317da66234c70fd741ae80b3811333726c5df7",
        "a9d23fd5f68a95455de7f8106a5392ae3fa7ab120b23290f319dcd0a9c116058",
        "a1ef807dc23edb9337a111b17f1d3e95b3307f22295e9e5955f969722b54d205",
        "41e88ca7544a6b29e32b02b3d1b018a703eb76743d80584abfe79b7624680717",
    ),
    "fp256": (
        "4da362e706e8a4f6f77cd6dba9d9afc54ade2f17fc6b5b67c054d15dd0776bc2",
        "79937081062f1b54a173a10bb0089f705fc1e18f1ea379fcfa9edc7f6dbf0754",
        "9fc60427cd6d2557ff48994e3bfdb0650a7b64e6ff54051bd16376f6f5568049",
        "12c6d916d839c4cacf5f46c739ba721ee7866b451c2dd129eef9f08a83f2baff",
        "e3214b0072fe975ca3643fe6b997e26867717520494aa388f12e8e88d2979fa3",
    ),
}
# the transcend pools' sizes at the stage's default counts (MEASURED): 25 more
# than at profile 3 (330, 367, 350 and 512), the 25 signed thresholds that the
# stage's pool and the vector sets' hold since profile 3.1
POOL_SIZES = {"fp32": 355, "fp64": 392, "fp128": 375, "fp256": 537}
# the study's census, through the fragments: (marked of 240 under rne and
# rmm, under the directed three); exp's fp64 at the decided G = 44 (the lead's
# verifier's 39; the study's 23 is at G = 46), expm1's 13 at fp64 (11 centres
# and two lanes between 0.7 and 1.3 of the nominal bound, as exp's five), the
# study's 16 and 127 at fp128 and fp256 (G = 46), MEASURED
CENSUS_MARKS = {
    "exp": {"fp32": (0, 0), "fp64": (16, 39), "fp128": (16, 184),
            "fp256": (16, 184)},
    "exp2": {"fp32": (0, 0), "fp64": (0, 0), "fp128": (0, 0),
             "fp256": (0, 0)},
    "expm1": {"fp32": (0, 0), "fp64": (6, 13), "fp128": (16, 127),
              "fp256": (16, 127)},
    # the log family (parcel MB2, MEASURED): log's census is its 32 arguments
    # 1 +- c ulp (the study's 3 and 9 at fp128 and fp256 for G = 46; the same
    # at fp64's G = 44), log1p's the 240 arguments c 2^-e (the study's 4 and
    # 11 at fp64's G = 44, 16 and 127 at fp128 and fp256); log2's marks none
    "log": {"fp32": (0, 0), "fp64": (3, 9), "fp128": (3, 9),
            "fp256": (3, 9)},
    "log2": {"fp32": (0, 0), "fp64": (0, 0), "fp128": (0, 0),
             "fp256": (0, 0)},
    "log1p": {"fp32": (0, 0), "fp64": (4, 11), "fp128": (16, 127),
              "fp256": (16, 127)},
}
# the committed centres, by routine and format: (rne and rmm, the directed
# three), both families together
CENTRES = {
    "exp": {"fp32": (0, 0), "fp64": (16, 34), "fp128": (16, 184),
            "fp256": (16, 184)},
    "exp2": {"fp32": (0, 0), "fp64": (0, 0), "fp128": (0, 0),
             "fp256": (0, 0)},
    "expm1": {"fp32": (0, 0), "fp64": (7, 16), "fp128": (17, 191),
              "fp256": (17, 314)},
    # log's equal its census's marks (3 and 9). log1p's are its census's
    # marks (4, 11, 16 and 127) and the anchors of its one-sided windows - a
    # power of two that is clear itself with a demanded-marked float beside
    # it: 6 under rne and rmm and 1 under the directed three at fp64, 15 and 1
    # at fp128 and fp256 (MEASURED, the module docstring of mathlib_family)
    "log": {"fp32": (0, 0), "fp64": (3, 9), "fp128": (3, 9),
            "fp256": (3, 9)},
    "log2": {"fp32": (0, 0), "fp64": (0, 0), "fp128": (0, 0),
             "fp256": (0, 0)},
    "log1p": {"fp32": (0, 0), "fp64": (10, 12), "fp128": (31, 128),
              "fp256": (31, 128)},
}


# =====================================================================
# the interface
# =====================================================================

@pytest.mark.parametrize("rnd", RND, ids=rid)
@pytest.mark.parametrize("fmt", FORMATS, ids=fid)
@pytest.mark.parametrize("fn", FUNCS)
def test_a_fragment_is_a_specialised_c4_fragment_and_is_built_once(fn, fmt, rnd):
    f = ml.fragment(fn, fmt, rnd)
    assert isinstance(f, routines.Fragment)
    assert (f.op, f.fmt, f.rnd, f.inputs, f.stage) == (
        fn, fmt, rnd, ("a",), "specialised")
    assert f.result[0] == f.flags[0] == "v"
    assert ml.fragment(fn, fmt, rnd) is f
    assert H.check_shape(f, SHAPE[fn][fmt.name][RND.index(rnd)]) == []


def test_a_name_that_is_not_built_is_refused_by_name():
    for name in ("sqrt", "", "EXP", "LOG", "exp10", "log10", "sin", "atan"):
        with pytest.raises(ValueError, match=repr(name)):
            ml.fragment(name, FP64, RNE)
        with pytest.raises(ValueError, match=repr(name)):
            ml.build(name, FP64, RNE)
    with pytest.raises(ValueError, match="attribute"):
        ml.build("exp", FP64, 7)
    with pytest.raises(ValueError, match="formats"):
        ml.build("exp2", FpFormat("fp16", 5, 10), RNE)
    with pytest.raises(ValueError, match="no_such_plant"):
        ml.build("expm1", FP64, RNE, plant="no_such_plant")
    with pytest.raises(ValueError, match="head_short.*triple-word"):
        ml.build("exp", FP32, RNE, plant="head_short")
    with pytest.raises(ValueError, match="square_term_dropped.*double-word"):
        ml.build("expm1", FP64, RNE, plant="square_term_dropped")
    with pytest.raises(ValueError, match="c1_ulp.*does not apply to exp2"):
        ml.build("exp2", FP64, RNE, plant="c1_ulp")
    with pytest.raises(ValueError, match="exact_no_j.*does not apply to exp"):
        ml.build("exp", FP64, RNE, plant="exact_no_j")
    with pytest.raises(ValueError, match="tiny_gate_off.*does not apply to"):
        ml.build("expm1", FP64, RNE, plant="tiny_gate_off")
    with pytest.raises(ValueError, match="exact_x_one.*does not apply to log"):
        ml.build("log", FP64, RNE, plant="exact_x_one")
    with pytest.raises(ValueError, match="newton_short.*triple-word"):
        ml.build("log1p", FP32, RNE, plant="newton_short")
    with pytest.raises(ValueError, match="rho2_dropped.*double-word"):
        ml.build("log1p", FP64, RNE, plant="rho2_dropped")
    with pytest.raises(ValueError, match="tiny_path_off.*does not apply to"):
        ml.build("log2", FP64, RNE, plant="tiny_path_off")


def test_the_build_functions_are_build_by_name():
    for fn, build in (("exp", ml.build_exp), ("exp2", ml.build_exp2),
                      ("expm1", ml.build_expm1), ("log", ml.build_log),
                      ("log2", ml.build_log2), ("log1p", ml.build_log1p)):
        b = build(FP64, RDN)
        assert b.meta["fn"] == fn and b.fragment().op == fn
        assert b.fragment().body == ml.build(fn, FP64, RDN).fragment().body


@pytest.mark.parametrize("fn", FUNCS)
def test_evaluate_is_one_lane_through_the_body_and_refuses_what_is_not_one(fn):
    f = ml.fragment(fn, FP64, RNE)
    one, zero = sf.one_bits(FP64), sf.zero_bits(FP64)
    # f(+0) is the definition's: 1, 1, +0 for exp, exp2, expm1; -inf with
    # divideByZero for log and log2, +0 for log1p. f(1): the definition's,
    # exact for exp2 (2), log (+0) and log2 (+0), inexact for the others
    assert ml.evaluate(f, zero) == H.golden(FP64, RNE, zero, fn)
    if fn in EXP_FUNCS:
        assert ml.evaluate(f, zero) == ((0 if fn == "expm1" else one), 0)
    elif fn == "log1p":
        assert ml.evaluate(f, zero) == (0, 0)
    else:
        assert ml.evaluate(f, zero) == (sf.inf_bits(FP64, 1),
                                        sf.FLAG_DIVZERO)
    bits, fw = ml.evaluate(f, one)
    assert (bits, fw) == H.golden(FP64, RNE, one, fn)
    assert fw == (0 if fn in ("exp2", "log", "log2") else sf.FLAG_INEXACT)
    for bad in (-1, 1 << 64):
        with pytest.raises(ValueError):
            ml.evaluate(f, bad)


# =====================================================================
# what is proved of every fragment
# =====================================================================

@pytest.mark.parametrize("rnd", RND, ids=rid)
@pytest.mark.parametrize("fmt", FORMATS, ids=fid)
@pytest.mark.parametrize("fn", FUNCS)
def test_every_fragment_holds_the_widened_invariants(fn, fmt, rnd):
    f = ml.fragment(fn, fmt, rnd)
    assert ml.invariants(f) == []
    # the live count: capped by format (the largest any routine keeps under
    # any attribute), and under what seq.py's 32 registers hold, so that
    # routines.program places every fragment, fp32's included
    assert f.live_max() <= ml.LIVE_CAP[fmt.name] < seq.NREG


@pytest.mark.parametrize("rnd", RND, ids=rid)
@pytest.mark.parametrize("fmt", FORMATS, ids=fid)
@pytest.mark.parametrize("fn", FUNCS)
def test_the_flag_word_takes_exactly_the_studys_values(fn, fmt, rnd):
    f = ml.fragment(fn, fmt, rnd)
    inx, unf, ovf = (sf.FLAG_INEXACT, sf.FLAG_INEXACT | sf.FLAG_UNDERFLOW,
                     sf.FLAG_OVERFLOW | sf.FLAG_INEXACT)
    if fn in LOG_FUNCS:
        # a log family result never overflows and is never marked tiny: the
        # flag words are the main path's inexact, with the mark, the zero
        # and the exact cases' 0, invalid and divideByZero, and, for log1p
        # alone, the tiny path's underflow with inexact (without the mark)
        want = {0, sf.FLAG_INVALID, sf.FLAG_DIVZERO, inx, inx | 0x80}
        if fn == "log1p":
            want |= {unf}
    else:
        want = {0, sf.FLAG_INVALID, inx, unf, ovf, inx | 0x80, ovf | 0x80}
        if fn != "expm1":            # only exp and exp2 mark an underflow
            want |= {unf | 0x80}
    assert ml.flag_words(f) == want <= ml.FLAG_WORDS


@pytest.mark.parametrize("fn", FUNCS)
def test_no_augmented_addition_and_the_error_free_sums_are_counted(fn):
    """No augadd (revision 8's question 9): an ALU fragment cannot hold one,
    and its opcodes are the design's eighteen (expm1's seventeen: it has no
    tininess compare; the log family's fifteen, log1p's eighteen, with
    RECIP_SEED); its error-free sums are Fast2Sum where the exponents are
    ordered and TwoSum elsewhere: nine and one in the double word's exp, nine
    and none in exp2's, ten and two in expm1's; 20 and 18, 21 and 15, 22 and
    23 in fp32's triple word; the log family's K + 3 Fast2Sums (K = 11 at
    fp64, 12 at fp128 and fp256) and one, none and two TwoSums, 25 and 19, 29
    and 18, 25 and 21 at fp32."""
    for fmt in FORMATS:
        for rnd in RND:
            assert H.check_sums(ml.build(fn, fmt, rnd)) == []
    assert len(H.ALU_OPS) == 18 and len(H.ALU_OPS_BY_FN["expm1"]) == 17
    assert len(H.ALU_OPS_BY_FN["log"]) == len(H.ALU_OPS_BY_FN["log2"]) == 15
    assert len(H.ALU_OPS_BY_FN["log1p"]) == 18
    assert "recip_seed" in H.ALU_OPS_BY_FN["log"] and         "recip_seed" not in H.ALU_OPS
    assert H.EFT_COUNTS[("exp", "fp32")] == (20, 18)
    assert H.EFT_COUNTS[("exp2", "dw")] == (9, 0)
    assert H.EFT_COUNTS[("expm1", "dw")] == (10, 2)
    assert H.EFT_COUNTS[("log", "fp64")] == (14, 1)
    assert H.EFT_COUNTS[("log2", "fp256")] == (15, 0)
    assert H.EFT_COUNTS[("log1p", "fp32")] == (25, 21)


@pytest.mark.parametrize("fmt", FORMATS, ids=fid)
@pytest.mark.parametrize("fn", FUNCS)
def test_the_fragment_is_specialised_and_the_unpruned_form_agrees(fn, fmt):
    """The fragment is in C4's specialised normal form, so cftc's internal
    check will instantiate the same body; and the instrumented form (the
    unpruned body the budget reads) computes the same result and flag
    word. A fresh build is the cached fragment."""
    for rnd in (RNE, RDN):
        b = ml.build(fn, fmt, rnd)
        assert H.check_specialised(b) == []
        assert b.fragment().body == ml.fragment(fn, fmt, rnd).body


def _mutated(f, **kw):
    fields = dict(op=f.op, fmt=f.fmt, rnd=f.rnd, inputs=f.inputs, body=f.body,
                  result=f.result, flags=f.flags, words=f.words,
                  stage=f.stage)
    fields.update(kw)
    return routines.Fragment(fields["op"], fields["fmt"], fields["rnd"],
                             fields["inputs"], fields["body"],
                             fields["result"], fields["flags"],
                             fields["words"], fields["stage"])


def _bodies(f, **kw):
    """f's body with the instruction `index` replaced."""
    body = list(f.body)
    for i, new in kw.items():
        body[int(i[1:])] = new
    return tuple(body)


def invariant_plants():
    """(name, mutated fragment of exp at fp64 under rne, text its findings
    must hold): one for each clause of mathlib.invariants()."""
    f = ml.fragment("exp", FP64, RNE)
    mark_word = [k for k, v in f.words.items() if v == 0x80][0]
    ior = [i for i, (op, _r, s) in enumerate(f.body)
           if op == sf.OP_IOR and all(x[0] == "v" for x in s)]
    assert len(ior) == 1
    rounded = [i for i, (op, r, _s) in enumerate(f.body)
               if op in routines.ROUNDED and r == RNE][0]
    sel = [i for i, (op, _r, s) in enumerate(f.body)
           if op == sf.OP_SELECT and s[0][0] == "v"][0]
    two = [i for i, (_op, _r, s) in enumerate(f.body) if len(s) == 2][0]
    op, r, s = f.body[two]
    return [
        ("the mark bit moved to bit 6", _mutated(
            f, words={**f.words, mark_word: 0x40}), "flag word's values"),
        ("the mark ORed by an add the walk cannot read", _mutated(
            f, body=_bodies(f, **{f"i{ior[0]}": (
                sf.OP_IADD, None, f.body[ior[0]][2])})),
         "flag word's values None"),
        ("an instruction rounding under a foreign attribute", _mutated(
            f, body=_bodies(f, **{f"i{rounded}": (
                f.body[rounded][0], RMM, f.body[rounded][2])})),
         "is not the routine's own"),
        ("an instruction reading only the routine's input", _mutated(
            f, body=_bodies(f, **{f"i{two}": (op, r, (("in", "a"),
                                                       ("in", "a")))})),
         "reads only the routine's inputs"),
        ("a SELECT whose two arms are one value", _mutated(
            f, body=_bodies(f, **{f"i{sel}": (
                sf.OP_SELECT, None,
                (f.body[sel][2][0], f.body[sel][2][0], f.body[sel][2][2]))})),
         "simplifies further"),
        ("an instruction reading a value not yet defined", _mutated(
            f, body=_bodies(f, i3=(f.body[3][0], f.body[3][1],
                                   (("v", 30),) + f.body[3][2][1:]))),
         "before it is defined"),
        ("an instruction reading a word the fragment lacks", _mutated(
            f, body=_bodies(f, i1=(f.body[1][0], f.body[1][1],
                                   (("w", "NO_SUCH_WORD"),)
                                   + f.body[1][2][1:]))),
         "which the fragment does not hold"),
        ("a result that is an input", _mutated(f, result=("in", "a")),
         "is not a value of the body"),
    ]


@pytest.mark.parametrize("index", range(8))
def test_each_clause_of_the_invariants_can_fail(index):
    name, bad, text = invariant_plants()[index]
    found = ml.invariants(bad)
    assert found and any(text in s for s in found), (name, found)


@pytest.mark.parametrize("fmt", FORMATS, ids=fid)
def test_the_live_caps_are_the_measured_maxima_and_can_fail(fmt):
    """LIVE_CAP is the largest live count of any routine under any attribute
    (SHAPE pins each), and a cap one under a fragment's count fails by name."""
    lives = {SHAPE[fn][fmt.name][i][2] for fn in FUNCS for i in range(5)}
    assert ml.LIVE_CAP[fmt.name] == max(lives)
    for fn in FUNCS:
        f = ml.fragment(fn, fmt, RNE)
        live = f.live_max()
        assert ml.invariants(f, live_cap=live) == []
        assert ml.invariants(f, live_cap=live - 1) == [
            f"{live} values live at once, past {live - 1}"]


@pytest.mark.parametrize("rnd", RND, ids=rid)
@pytest.mark.parametrize("fn", FUNCS)
def test_every_fp32_fragment_fits_seq_pys_registers_the_designs_order_not(
        fn, rnd):
    """The exp family's triple word keeps 33 to 36 values live in the
    design's order, past seq.py's 32 registers: routines.program refuses it
    by name (parcel E1 and the plan's verifier measured the same for exp). The
    log family's keeps 21 to 24 and routines.program places it in either
    order. Scheduled, every fp32 fragment keeps 17 to 21 and
    routines.program places it."""
    b = ml.build(fn, FP32, rnd)
    designed = b.fragment(schedule=False)
    if fn in EXP_FUNCS:
        assert designed.live_max() > seq.NREG
        with pytest.raises(AssertionError,
                           match="no register for the harness"):
            routines.program(designed)
    else:
        assert 21 <= designed.live_max() <= 24
        assert routines.program(designed)[0].insns
    f = ml.fragment(fn, FP32, rnd)
    assert f.live_max() < designed.live_max()
    assert f.live_max() < seq.NREG
    prog, _bank = routines.program(f)
    assert prog.insns


# =====================================================================
# the reorder
# =====================================================================

@pytest.mark.parametrize("rnd", RND, ids=rid)
@pytest.mark.parametrize("fmt", FORMATS, ids=fid)
@pytest.mark.parametrize("fn", FUNCS)
def test_the_scheduled_fragment_is_the_designs_reordered(fn, fmt, rnd):
    """The same dataflow graph (the order-free digest), the same words, a
    topological order, no more values live: and fewer, at every fragment."""
    b = ml.build(fn, fmt, rnd)
    f = ml.fragment(fn, fmt, rnd)
    assert H.check_reorder(b, f) == []
    g = b.fragment(schedule=False)
    assert ml.dag_digest(f) == ml.dag_digest(g)
    assert f.live_max() < g.live_max() and f.body != g.body


@pytest.mark.parametrize("rnd", RND, ids=rid)
@pytest.mark.parametrize("fmt", FORMATS, ids=fid)
def test_exps_dataflow_graph_is_the_one_it_had_at_1337a13(fmt, rnd):
    """Nothing but the order of exp's instructions moved: every operand, every
    attribute and every word of every instruction is E1's, whatever the
    format and the attribute. A value does not change when the graph does not,
    so every lane's bits and flag word are what they were."""
    f = ml.fragment("exp", fmt, rnd)
    assert ml.dag_digest(f) == EXP_DIGESTS[fmt.name][RND.index(rnd)]


@pytest.mark.parametrize("rnd", RND, ids=rid)
@pytest.mark.parametrize("fmt", FORMATS, ids=fid)
@pytest.mark.parametrize("fn,digests", [("exp2", EXP2_DIGESTS),
                                        ("expm1", EXPM1_DIGESTS)])
def test_exp2s_and_expm1s_dataflow_graphs_are_the_ones_they_had_at_f22e8d2(
        fn, digests, fmt, rnd):
    """The log family changed no instruction of exp2 or expm1: every operand,
    every attribute and every word of every instruction is what parcel MB1
    merged (the digests of the 40 fragments at f22e8d2), whatever the format
    and the attribute. A value does not change when the graph does not, so
    every lane's bits and flag word are what they were."""
    f = ml.fragment(fn, fmt, rnd)
    assert ml.dag_digest(f) == digests[fmt.name][RND.index(rnd)]


@pytest.mark.parametrize("fmt", FORMATS, ids=fid)
@pytest.mark.parametrize("fn", FUNCS)
def test_the_scheduler_takes_the_lower_peak_of_its_two_orders(fn, fmt):
    b = ml.build(fn, fmt, RNE)
    g = b.fragment(schedule=False)
    ph = [b.phase_of[i] for i in b.live_indices()]
    ranked = ml.permuted(g, ml._ranked_order(g, ph)).live_max()
    depth = ml.permuted(g, ml._dfs_order(g)).live_max()
    assert ml.fragment(fn, fmt, RNE).live_max() == min(ranked, depth)
    if fn in EXP_FUNCS:
        # they are complementary, which is why there are two: the phase order
        # is the better at fp32, the depth-first at the double word's formats
        assert (ranked < depth) == (fmt is FP32)
    else:
        # the log family's phase order is the better everywhere (MEASURED,
        # 13 against 14, 13 against 14, 12 against 15 at the double word; 19
        # against 20, 17 against 20, 20 against 22 at fp32): the depth-first
        # order is the lower peak nowhere, and is kept as the second candidate
        # because the exp family needs it
        assert ranked < depth


def test_the_phase_order_names_every_phase_a_builder_uses():
    used = {ph for fn in FUNCS for fmt in (FP32, FP64)
            for ph in ml.build(fn, fmt, RNE).phase_of}
    assert used <= set(ml.PHASE_ORDER) and "setup" not in used


# =====================================================================
# item 1: against transcend
# =====================================================================

def test_the_pools_are_the_stages_pools():
    for fmt in FORMATS:
        assert len(H.pools(fmt)) == POOL_SIZES[fmt.name]


def test_the_pools_and_edge_pool_hold_both_signs_of_each_negative_threshold():
    """transcend.py's exp reaches 2^emin at the argument emin ln2 and
    underflows below its screen (emin - p) ln2, both negative; the pools'
    other negative thresholds are n ln2 for n = emin - man_w, -(p + 2) and
    -(p + 3). Through profile 3 the pools held only the positive image of
    each (mpmath.libmp.to_man_exp returns an unsigned mantissa by default
    and the pool generators took the sign from it), so no pool met the
    tininess decision at k = emin; since profile 3.1 (parcel PS) each holds
    the signed image of all five, with its neighbours at +-1 and +-2 ulps,
    and the positive image as well, and edge_pool holds both signs of every
    n."""
    near = range(-2, 3)
    for fmt in FORMATS:
        pool, edges = set(H.pools(fmt)), set(H.edge_pool(fmt))
        for n in (fmt.emin, fmt.emin - fmt.man_w, fmt.emin - fmt.man_w - 1,
                  -(fmt.prec + 2), -(fmt.prec + 3)):
            b = ml._enc(fmt, n * ml._ln2())
            mirror = b & ~fmt.sign_mask
            assert b & fmt.sign_mask
            assert {b + d for d in near} <= pool, (fmt.name, n)
            assert {mirror + d for d in near} <= pool, (fmt.name, n)
            assert {b + d for d in near} <= edges, (fmt.name, n)
        unf = ml._screens(fmt)[1]
        assert unf & fmt.sign_mask and unf in pool and unf in edges


def test_the_edge_pools_hold_the_thresholds_of_exp2_and_expm1():
    """exp2's: the integers at its edges, the tie emin - p among them, with
    neighbours; expm1's: its clamp and the tiny path's edges and the second
    family's RN(-n ln 2), with neighbours."""
    for fmt in FORMATS:
        p, near = fmt.prec, range(-2, 3)
        e2, em = set(H.edge_pool(fmt, "exp2")), set(H.edge_pool(fmt, "expm1"))
        pool = set(H.pools(fmt))
        for n in (fmt.emax + 1, fmt.emax, fmt.emin, fmt.emin - fmt.man_w,
                  fmt.emin - p, fmt.emin - p - 1):
            for sg in (1, -1):
                b = ml._enc(fmt, sg * n)
                assert {b + d for d in near} <= e2, (fmt.name, n)
        tie = ml._enc_exact(fmt, fmt.emin - p)
        assert tie in e2 and tie in pool                # the tie is in both
        for n in (p, p + 1, p + 2, p + 3):
            b = ml._enc(fmt, -n * ml._ln2())
            assert {b + d for d in near} <= em, (fmt.name, n)
        for k in (p + 2, p + 3):
            for sg in (1, -1):
                b = ml._enc(fmt, sg * Fraction(1, 2 ** k))
                assert {b + d for d in near} <= em, (fmt.name, k)
        assert sf.min_normal_bits(fmt) in em and sf.max_subnormal_bits(fmt) in em


def test_the_seed_runs_are_the_runs_of_c_from_16_down_to_8():
    """RECIP_SEED's 512 cells share their C in runs: 16 (m up to 1.0316), 15,
    14, ..., 9, 8 (the wrap, m from 1.882): nine runs in order of m, from 1 to
    the largest float under 2, each run's ends being the lanes where |r| is
    largest (the study's rmax.py: 2^-4.081 at C = 9)."""
    for fmt in FORMATS:
        runs = H.seed_runs(fmt)
        assert [c for c, _lo, _hi in runs] == list(range(16, 7, -1))
        assert runs[0][1] == 1
        assert runs[-1][2] == 2 - Fraction(1, 2 ** (fmt.prec - 1))
        for (_c, _lo, hi), (_c2, lo2, _hi2) in zip(runs, runs[1:]):
            # adjacent cells: the next run's first float is the next float
            assert lo2 - hi == Fraction(1, 2 ** (fmt.prec - 1))
        assert runs[-1][1] > Fraction(188, 100)  # the wrap's first cell


def test_the_edge_pools_hold_the_log_familys_thresholds():
    """log and log2: 1 +- c ulp for c up to 16 (the census), the powers of
    two at the ends of the exponent range, of the subnormals and near 1, each
    with two neighbours either side (log2's exact cases and the neighbours of
    log(1)); log1p: -1 and its neighbours (the pole, and the NaN below it),
    the tiny path's gate 2^-(p+2) and 2^-(p+3) of both signs, 15/256 (the
    r = x path's end) and 1/16 of both signs, and 2^-k's clamp, p + G + 2."""
    for fmt in FORMATS:
        p, near = fmt.prec, range(-2, 3)
        one = sf.one_bits(fmt)
        e_log, e_log2, e_log1p = (set(H.edge_pool(fmt, fn))
                                  for fn in ("log", "log2", "log1p"))
        for e in (e_log, e_log2):
            assert {one + c for c in range(-16, 17)} <= e
            for k in (fmt.emax, fmt.emin, fmt.emin - fmt.man_w, 1, -1, p):
                b = ml._enc(fmt, Fraction(2) ** k)
                assert {b + d for d in near if b + d >= 0} <= e, (fmt.name, k)
            assert sf.max_normal_bits(fmt) in e
            assert sf.min_subnormal_bits(fmt) in e
        minus1 = ml._enc(fmt, Fraction(-1))
        assert {minus1 + d for d in near} <= e_log1p        # -1 and its sides
        for k in (p + 2, p + 3):
            for sg in (1, -1):
                b = ml._enc(fmt, sg * Fraction(1, 2 ** k))
                assert {b + d for d in near} <= e_log1p, (fmt.name, k)
        for edge in (Fraction(15, 256), Fraction(1, 16)):
            for sg in (1, -1):
                b = ml._enc(fmt, sg * edge)
                assert {b + d for d in range(-4, 5)} <= e_log1p, (fmt.name,
                                                                  edge)
        clamp = p + ml.GUARD[fmt.name] + 2
        for k in (clamp - 1, clamp, clamp + 1, clamp + 2):
            b = ml._enc(fmt, Fraction(2) ** k)
            assert {b + d for d in near} <= e_log1p, (fmt.name, k)


@pytest.mark.parametrize("rnd", RND, ids=rid)
@pytest.mark.parametrize("fmt", FORMATS, ids=fid)
@pytest.mark.parametrize("fn", FUNCS)
def test_the_pools_every_lane_equals_transcend_or_is_marked_on_the_list(
        fn, fmt, rnd):
    f = ml.fragment(fn, fmt, rnd)
    out, t = H.check_pools(f)
    assert out == []
    # the pools' only mark is exp(+2^-p) (rne, rmm) or exp(-2^-p), and
    # expm1(-2^-p) under rne and rmm, structured lanes; exp2 marks none. The
    # guess of exp(+2^-p) is wrong under rne (the true value is above the
    # midpoint 1 + 2^-p, the tie goes to even) and right under the others;
    # expm1(-2^-p)'s is right: counted. The log family's (parcel MB2): log
    # marks 1 + ulp under the directed three, log1p 2^-p under rne and rmm,
    # log2 none, with their guesses right
    assert set(t.marked) == H.expected_pool_marks(fmt, rnd, fn)
    assert len(t.guess_wrong) == (
        1 if fn == "exp" and fmt is not FP32 and rnd == RNE else 0)
    assert t.n == POOL_SIZES[fmt.name] and not t.wrong and not t.stray


@pytest.mark.parametrize("rnd", RND, ids=rid)
@pytest.mark.parametrize("fmt", FORMATS, ids=fid)
@pytest.mark.parametrize("fn", FUNCS)
def test_random_lanes_equal_transcend_and_none_is_marked(fn, fmt, rnd):
    """Random arguments with every bit random, and the weighted sampler's:
    a random lane is marked with probability about 2^-(p+G), so none is."""
    f = ml.fragment(fn, fmt, rnd)
    n = 120 if fn == "exp" else 60
    out, t = H.check_random_lanes(f, n, 3)
    assert out == [] and t.n >= 1.6 * n
    # log's weighted sampler draws mantissas within a few ulps of 1, the start
    # of the first seed run, where its isolated centres are (1 + c ulp): a mark
    # there is the theory's (check_lanes asked it); no other lane is marked
    assert not t.marked or fn == "log"


@pytest.mark.parametrize("rnd", RND, ids=rid)
@pytest.mark.parametrize("fmt", FORMATS, ids=fid)
@pytest.mark.parametrize("fn", FUNCS)
def test_the_signed_thresholds_and_cell_ends_equal_transcend(fn, fmt, rnd):
    f = ml.fragment(fn, fmt, rnd)
    out, t = H.check_edges(f)
    assert out == [] and t.n == len(H.edge_pool(fmt, fn)) and not t.wrong
    # the marks are the second family's windows, expm1's, and nothing else;
    # the log family's are exactly the lanes the theory demands marked (MEASURED:
    # the pool holds no lane between 0.7 and 1.3 of the bound from a boundary,
    # so the sets are equal): log's census centres, 1 +- c ulp for c up to 16,
    # all in the pool; log1p's one lane, -(2^-p)(1 - 2^-p) under rne and rmm;
    # log2's none - with their guesses right
    if fn in ("exp", "exp2"):
        assert not t.marked
    else:
        assert len(t.guess_wrong) == 0
    if fn in LOG_FUNCS:
        may, must = H.theory_marks(fmt, rnd, H.edge_pool(fmt, fn), fn)
        assert may == must and set(t.marked) == must


@pytest.mark.parametrize("rnd", RND, ids=rid)
@pytest.mark.parametrize("fmt", FORMATS, ids=fid)
@pytest.mark.parametrize("fn", FUNCS)
def test_on_seq_py_through_routines_program_and_run(fn, fmt, rnd):
    """The fragment as a stand-alone program on seq.py, through
    routines.program and routines.run, at all four formats: fp32's triple
    word fits the register file since the reorder. The lanes are the pools',
    and, for exp at the double word's formats, as E1 ran it, the edge pool's
    too (the other edge pools run through evaluate(), which seq.py equals on
    every pool lane)."""
    f = ml.fragment(fn, fmt, rnd)
    xs = sorted(set(H.pools(fmt)) | (set(H.edge_pool(fmt, fn))
                                     if fn == "exp" and fmt is not FP32
                                     else set()))
    if fn in LOG_FUNCS:
        # to keep the golden stage short, every third pool lane and the pools'
        # marked ones; mathlib_runs.py pools --seq --edges runs them all
        xs = sorted(set(xs[::3]) | H.expected_pool_marks(fmt, rnd, fn))
    out, t = H.check_seq(f, xs)
    assert out == []
    assert not t.wrong and set(t.marked) <= (
        H.structured_arguments(fmt, rnd, fn) | H.expected_pool_marks(
            fmt, rnd, fn))


@pytest.mark.parametrize("fn,fmt,rnds", [
    ("exp", FP64, RND), ("exp", FP128, (RNE, RUP)), ("exp", FP256, (RNE, RDN)),
    ("exp", FP32, (RMM,)),
    ("exp2", FP32, (RNE, RUP)), ("exp2", FP64, (RNE, RDN, RMM)),
    ("exp2", FP128, (RTZ,)), ("exp2", FP256, (RUP,)),
    ("expm1", FP32, (RDN,)), ("expm1", FP64, (RNE, RTZ, RMM)),
    ("expm1", FP128, (RUP,)), ("expm1", FP256, (RNE,)),
    ("log", FP64, (RNE, RDN)), ("log", FP32, (RUP,)),
    ("log2", FP128, (RTZ,)), ("log2", FP256, (RMM,)),
    ("log1p", FP64, (RNE, RTZ)), ("log1p", FP256, (RDN,))],
    ids=lambda v: v if isinstance(v, str) else getattr(v, "name", "rnds"))
def test_the_compiled_shape_raises_exactly_the_operations_flags_and_marks(
        fn, fmt, rnds):
    """QUIET, the body, ENDQUIET, RAISE of the flag word (cftc/inline.py's
    shape, R24): each lane's byte is transcend's flags exactly, or on a
    marked lane the routine's own flags with bit 7; FLAGS is their OR and
    STATUS[6] says a lane was marked."""
    for rnd in rnds:
        assert H.check_r24(ml.fragment(fn, fmt, rnd)) == []


@pytest.mark.parametrize("fmt", FORMATS, ids=fid)
def test_exp2_at_emin_minus_p_is_the_tie_and_rmm_rounds_it_away(fmt):
    """2^(emin - p) is half the smallest subnormal, the tie between +0 and it.
    transcend.exp2 gives +0 under rne (even), rtz and rdn, and the smallest
    subnormal under rup and rmm (roundTiesToAway), with underflow and inexact,
    since profile 3 (parcel XT); the study's model, written before, gave +0
    under rmm. The routine equals the definition at all five attributes, the
    lane unmarked, and the neighbours below and above are right too."""
    tie = ml._enc_exact(fmt, fmt.emin - fmt.prec)
    want = {RNE: 0, RTZ: 0, RDN: 0, RUP: 1, RMM: 1}
    for rnd in RND:
        f = ml.fragment("exp2", fmt, rnd)
        bits, fw = ml.evaluate(f, tie)
        assert (bits, fw) == (want[rnd], 0x18) == H.golden(fmt, rnd, tie,
                                                           "exp2")
        for d in (-2, -1, 1, 2):
            assert ml.evaluate(f, tie + d) == H.golden(fmt, rnd, tie + d,
                                                       "exp2")


# =====================================================================
# the fixed grid's rounding, on states no argument is known to reach
# =====================================================================

def test_a_probe_can_be_replaced_and_what_follows_runs_on_the_new_state():
    b = ml.build_exp(FP64, RNE)
    x = sf.one_bits(FP64)
    res, fw, pr = b.run(x, want=("Vh", "Vl", "Ek"))
    assert b.run(x, over={})[:2] == (res, fw)
    assert b.run(x, over=pr)[:2] == (res, fw)         # its own values back
    # V_h and V_l both replaced (V_l is computed from V_h, so one alone is
    # rebuilt around): V = 1, and 2^k is 2 for this argument (k = 1)
    other = b.run(x, over={"Vh": sf.one_bits(FP64), "Vl": 0})
    assert other[0] == ml._enc(FP64, 2) != res
    b.probes["a_word"] = ("w", "ZERO")
    with pytest.raises(ValueError, match="not a value of the body"):
        b.run(x, over={"a_word": 0})


@pytest.mark.parametrize("fmt", FORMATS, ids=fid)
@pytest.mark.parametrize("fn", ("exp", "exp2"))
def test_the_fixed_grids_rounding_is_right_where_round_to_odd_decides(fn, fmt):
    """V_h exactly on a half-grid point, |V_l| = 8 Bv: the correct rounding
    of V 2^k under every attribute, unmarked, at two grids."""
    for rnd in RND:
        assert H.check_fixed_grid(ml.build(fn, fmt, rnd)) == []


@pytest.mark.parametrize("fn", ("exp", "exp2"))
def test_round_to_nearest_is_wrong_on_those_states_under_rne_and_rmm_only(fn):
    """The plant odd_dropped builds the fixed grid's sum of V_l's share
    round-to-nearest: V_l is lost, the tie goes to even (rne) or away from
    zero (rmm), wrong for V_l > 0 under rne and for V_l < 0 under rmm, at
    both grids of each format (16 of 80 states), and right under the
    directed three. No other check sees it (the plants table)."""
    wrong = 0
    for fmt in FORMATS:
        for rnd in RND:
            found = H.check_fixed_grid(ml.build(fn, fmt, rnd,
                                                plant="odd_dropped"))
            if rnd == RNE:
                assert len(found) == 2 and all("V_l > 0" in s for s in found)
            elif rnd == RMM:
                assert len(found) == 2 and all("V_l < 0" in s for s in found)
            else:
                assert found == []
            assert all(s.startswith("fixed_grid:") and "marked" not in s
                       for s in found)
            wrong += len(found)
    assert wrong == 16


# =====================================================================
# item 2: the bound against mpmath, and the budget
# =====================================================================

# the largest |V - f| / Bv over the samples below, as log2 (MEASURED, parcel
# MB1's entry and E1's: exp fp32 2^-5.0, fp64 2^-2.6, fp128 2^-6.1, fp256
# 2^-5.8; exp2 2^-6.1, 2^-2.7, 2^-6.1, 2^-5.8; expm1 2^-3.0, 2^-2.9, 2^-2.9,
# 2^-2.9 - the first clamped k's own dropped term, 1/8 of Bv): each must stay
# at least this far under the bound
BOUND_ROOM = {
    "exp": {"fp32": -4.0, "fp64": -2.0, "fp128": -5.0, "fp256": -5.0},
    "exp2": {"fp32": -5.0, "fp64": -2.0, "fp128": -5.0, "fp256": -5.0},
    "expm1": {"fp32": -2.0, "fp64": -2.0, "fp128": -2.0, "fp256": -2.0},
    # the log family (parcel MB2, MEASURED over these samples: log -5.3, -4.5,
    # -5.3, -4.6 at fp32 to fp256; log2 -5.3, -3.95, -5.2, -4.9; log1p -3.7,
    # -4.4, -4.9, -4.6)
    "log": {"fp32": -3.0, "fp64": -3.0, "fp128": -4.0, "fp256": -4.0},
    "log2": {"fp32": -3.0, "fp64": -3.0, "fp128": -4.0, "fp256": -4.0},
    "log1p": {"fp32": -3.0, "fp64": -3.0, "fp128": -4.0, "fp256": -4.0},
}


@pytest.mark.parametrize("fmt", FORMATS, ids=fid)
@pytest.mark.parametrize("fn", FUNCS)
def test_the_bound_holds_against_mpmath_at_the_worst_points(fn, fmt):
    b = ml.build(fn, fmt, RNE)
    for label, xs in (("random", H.random_main(fmt, 150, 1, fn)),
                      ("placed", H.placed(fmt, fn)),
                      ("weighted", H.weighted(fmt, 150, 2, fn))):
        out, (worst, n) = H.check_bound(b, xs, label)
        assert out == [] and n >= 100, (label, out)
        assert worst < BOUND_ROOM[fn][fmt.name], (label, worst)


# the budget's bound at G = 44 (fp64) and 46, in Bv: the study's 3.3 gives
# 0.164 at fp64 for exp and exp2; expm1's is the clamp's own term (0.131 and
# 0.13 Bv) and, at fp64, the double word's floor amplified at n = +-1
# (capacities 0.04); the room kept
BUDGET_ROOM = {
    "exp": {"fp64": 0.25, "fp128": 0.1, "fp256": 0.1},
    "exp2": {"fp64": 0.25, "fp128": 0.1, "fp256": 0.1},
    "expm1": {"fp64": 0.25, "fp128": 0.2, "fp256": 0.2},
    # the log family's, MEASURED over these samples: log 0.083, 0.034, 0.042,
    # log2 0.136, 0.004, 0.030, log1p 0.165, 0.029, 0.031 Bv at fp64, fp128,
    # fp256 (the study's 3.3 at G = 44: log2 0.18, log1p 0.12 to 0.18)
    "log": {"fp64": 0.25, "fp128": 0.1, "fp256": 0.1},
    "log2": {"fp64": 0.25, "fp128": 0.1, "fp256": 0.1},
    "log1p": {"fp64": 0.25, "fp128": 0.1, "fp256": 0.1},
}


@pytest.mark.parametrize("fmt", DOUBLE, ids=fid)
@pytest.mark.parametrize("fn", FUNCS)
def test_the_budget_states_the_bound_by_the_instructions_at_the_decided_g(
        fn, fmt):
    b = ml.build(fn, fmt, RNE)
    xs = (H.uniform_unit(fmt, 30, 1, fn) + H.weighted(fmt, 30, 3, fn)
          + H.placed(fmt, fn)[::6])
    out, s = H.check_budget(b, xs)
    assert out == []
    assert s["bound"] < BUDGET_ROOM[fn][fmt.name], s
    assert s["rounding"] > 40 and s["lanes"] == len(xs)


@pytest.mark.parametrize("fn", FUNCS)
def test_fp32_has_no_budget_and_says_so(fn):
    with pytest.raises(ValueError, match="no budget"):
        B.Analyzer(ml.build(fn, FP32, RNE))


# =====================================================================
# item 3: the mark-rate law
# =====================================================================

# lanes a cell: exp's are E1's, exp2's and expm1's MB1's trim, and the log
# family's a further one (parcel MB2), 700 where the expected count is 15.8 and
# sigma 3.9: a mark silenced or a bound made too small is 4 sigma under it
RATE_N = {"exp": 2000, "exp2": 1000, "expm1": 1000, "log": 700,
          "log2": 700, "log1p": 700}

@pytest.mark.parametrize("rnd", RND, ids=rid)
@pytest.mark.parametrize("fmt", DOUBLE, ids=fid)
@pytest.mark.parametrize("fn", FUNCS)
def test_the_mark_rate_law_in_its_fifteen_cells(fn, fmt, rnd):
    """The bound inflated to 2^-(p+6), G' = 6: on uniform main-path
    arguments (as the study's m1rate.py draws them: 2,000 a cell for exp, as
    E1 ran it; 1,000 for exp2 and expm1 and 700 for the log family to keep
    the golden stage quick, the 2,000 being mathlib_runs.py rate's default)
    the marked fraction is
    within three sigma of 2^(0.53 - 6), every unmarked lane right, every
    marked guess counted - all right, as the study found."""
    out, st = H.check_rate(fmt, rnd, RATE_N[fn], 7, fn=fn)
    assert out == [], st
    assert st["wrong"] == 0 and st["guess_wrong"] == 0
    assert abs(st["marked"] - st["expected"]) <= 3 * st["sigma"]


# =====================================================================
# item 4: the structured families
# =====================================================================

def test_the_committed_family_is_what_the_theory_generates():
    assert H.check_family_list(F.FAMILY) == []
    for fn in FUNCS:
        for fmt in FORMATS:
            for rnd in RND:
                rn = rnd in (RNE, RMM)
                assert len(F.FAMILY[fn][fmt.name][sf.RND_NAMES[rnd]]) == \
                    CENTRES[fn][fmt.name][0 if rn else 1]


def census_of(fn, fmt):
    """The study's census of the routine's family: the 240 arguments c 2^-e
    (exp, expm1, log1p), or log's 32 arguments 1 +- c ulp (log, log2)."""
    return F.census_log(fmt) if fn in ("log", "log2") else F.census(fmt)


@pytest.mark.parametrize("rnd", RND, ids=rid)
@pytest.mark.parametrize("fmt", DOUBLE, ids=fid)
@pytest.mark.parametrize("fn", ("exp", "expm1", "log", "log1p"))
def test_the_windows_the_centres_and_their_neighbours_inside_and_outside(
        fn, fmt, rnd):
    """Every committed centre of the cell, each with its neighbours at 1,
    W/8, W/4, 0.65 W ulps (inside the window, d < 0.7 by the theory: marked)
    and 1.35 W, 2 W, 8 W, 1024 W (outside: not), the census arguments that
    are not centres and, at fp128 and fp256, the deep arguments below the
    census (the windows' lower edge, where the bound's calibration shows):
    every lane the theory puts inside is marked, none outside, every
    unmarked lane equals transcend's. Every centre of the committed list is
    run (expm1's directed cells hold 191 and 314 at fp128 and fp256: 6 and
    10 s). log's centres are isolated - its neighbours at 1 to 1024 ulps are
    other integers c, outside unless they are centres - and its deep
    arguments are 1 +- c ulp for c = 2^a, 3 2^a, 5 2^a and 7 2^a, from a = 2
    (mathlib_family.deep_arguments: the census's c, extended by the same
    rule)."""
    f = ml.fragment(fn, fmt, rnd)
    cen = F.FAMILY[fn][fmt.name][sf.RND_NAMES[rnd]]
    have = {F.argument(fmt, c) for c in cen}
    extra = [x for x in census_of(fn, fmt) if x not in have]
    out, st = H.check_family(f, cen, extra=extra, deep=True)
    assert out == [], st
    assert st["mark"] >= len(cen) and st["lanes"] > 10 * len(cen)
    assert st["marked_mark"] == st["mark"] and st["marked_clear"] == 0
    # expm1's tiny gate, 2^-(p+2), takes the census's c 2^-(p+3) for c = 1 and
    # perhaps 2 (exp's, 2^-(p+3), takes none): gated lanes are never marked
    assert st["wrong"] == 0 and st["marked_gated"] == 0
    if fn == "exp":
        assert st["gated"] == 0


@pytest.mark.parametrize("rnd", RND, ids=rid)
@pytest.mark.parametrize("fn", ("exp", "expm1", "log", "log1p"))
def test_at_fp32_the_census_finds_no_window_and_the_theory_agrees(fn, rnd):
    """Marks need an exponent from (p + G)/2 = 32 down to p = 24: none at
    G = 40 (for log, c^2 under about 3 2^(p-1-G), which is under 1). The
    study's census, 240 arguments (log: 32), through the fragment: none
    marked, every one right; the theory puts every one outside (d > 1.3) -
    and is not vacuous: at a guard of 16 it finds windows at fp32."""
    f = ml.fragment(fn, FP32, rnd)
    out, t = H.check_census_empty(f)
    assert out == [] and not t.marked and not t.wrong
    assert t.n == len(census_of(fn, FP32)) == (32 if fn == "log" else 240)
    assert F.centres(FP32, rnd, fn) == [] and F.FAMILY[fn]["fp32"][
        sf.RND_NAMES[rnd]] == []
    assert {F.classify(FP32, rnd, x, None, fn)
            for x in census_of(fn, FP32)} <= {"clear", "gated"}
    assert any(F.classify(FP32, rnd, x, 16, fn) == "mark"
               for x in census_of(fn, FP32))


@pytest.mark.parametrize("fmt", DOUBLE, ids=fid)
@pytest.mark.parametrize("fn", FUNCS)
def test_the_census_counts_at_the_decided_g(fn, fmt):
    """The study's 3.5 counts are at G = 46; at fp64's decided G = 44 the
    directed attributes mark 39 of exp's 240 (the plan's verifier: 39) and
    11 of expm1's. Every committed centre of the first family is among the
    marks; exp2's census marks none."""
    for rnd in RND:
        f = ml.fragment(fn, fmt, rnd)
        assert H.check_census_counts(f, CENSUS_MARKS[fn][fmt.name]) == []
        assert H.census_run(f).n == (32 if fn in ("log", "log2") else 240)


@pytest.mark.parametrize("rnd", RND, ids=rid)
@pytest.mark.parametrize("fmt", FORMATS, ids=fid)
@pytest.mark.parametrize("fn", H.NOFAMILY)
def test_exp2_and_log2_have_no_family_and_are_held_to_that(fn, fmt, rnd):
    """The study measured 0 of the census marked at fp64, fp128 and fp256 for
    both; the theory agrees at every format and attribute (the committed list
    is empty and generated), and the routine marks none of the census, the
    deep arguments, or the floats next to the exact cases - exp2's integers
    2^N, log2's powers of two 2^k, where a window would sit - and is right on
    all of them."""
    f = ml.fragment(fn, fmt, rnd)
    out, t = H.check_nofamily(f)
    assert out == [] and t.n > (300 if fn == "exp2" else 200) \
        and not t.marked and not t.wrong
    assert F.FAMILY[fn][fmt.name][sf.RND_NAMES[rnd]] == []
    assert CENSUS_MARKS[fn][fmt.name] == (0, 0)


@pytest.mark.parametrize("fmt", DOUBLE, ids=fid)
def test_logs_centres_are_isolated_and_the_deep_ones_grow_with_p_minus_g(fmt):
    """log(1 + c eps) = c eps - (c eps)^2/2 + (c eps)^3/3 - ...: the square
    term is a (half) multiple of the result's ulp when c is a power of two or
    c^2 is a multiple of 2^m, and the value then sits the cubic term, about
    c^2 eps/3 ulps, from a boundary, inside the bound while c^2 is under about
    3 2^(p-1-G). So under the directed three the deep centres c = 2^a mark for
    a up to (p - 1 - G)/2, rounded down (a = 4 at fp64, 33 at fp128, 95 at
    fp256) and not above it; THEORY, mpmath at 4p + 200 bits, whose distance
    d to the boundary in units of the bound is 0.67 at that a and four times
    more at each a above it. The next float of a centre, c + 1, is another
    integer: 2^a + 1 is clear."""
    G = ml.GUARD[fmt.name]
    top = (fmt.prec - 1 - G) // 2
    for a in sorted({0, 1, 2, top - 1, top, top + 1, top + 2, top + 4}):
        x = F.argument(fmt, ("u", 1 << a))
        want = "mark" if a <= top else "clear"
        assert F.classify(fmt, RTZ, x, None, "log") == want, (fmt.name, a)
    assert 0.6 < F.distance(fmt, RTZ, F.argument(fmt, ("u", 1 << top)), None,
                            "log") < 0.7
    for a in (top + 1, top + 3):
        assert F.classify(fmt, RTZ, F.argument(fmt, ("u", (1 << a) + 1)),
                          None, "log") == "clear", (fmt.name, a)


@pytest.mark.parametrize("fmt", DOUBLE, ids=fid)
def test_expm1_has_a_second_family_that_the_studys_census_did_not_hold(fmt):
    """x = RN(-n ln 2) puts e^x within 2^-p |x| of 2^-n, so expm1(x) =
    -1 + 2^-n (1 + eps) sits within 2^-n |eps| of a boundary: the grid point
    -1 + 2^-n under the directed three for n from about G to p, the midpoint
    -1 + 2^-(p+1) under rne and rmm for n = p + 1. The census (c 2^-e) holds
    none of those arguments; the pools' edges do (E1's edge pool holds both
    signs of (p + 1) ln 2), and the routine marks the centre with its right
    guess, and its neighbours inside the window."""
    p = fmt.prec
    census = F.census(fmt)
    for rnd in RND:
        rn = rnd in (RNE, RMM)
        cen = [c for c in F.FAMILY["expm1"][fmt.name][sf.RND_NAMES[rnd]]
               if isinstance(c[0], str)]
        ns = [n for _t, n in cen]
        assert ns == ([p + 1] if rn else ns) and (rn or max(ns) == p)
        assert not rn or len(ns) == 1
        assert not any(F.argument(fmt, c) in census for c in cen)
        f = ml.fragment("expm1", fmt, rnd)
        for c in cen[-1:]:
            x = F.argument(fmt, c)
            bits, fw = ml.evaluate(f, x)
            assert fw & ml.MARK and (bits, fw & 0x1F) == H.golden(
                fmt, rnd, x, "expm1")
            assert x in set(H.edge_pool(fmt, "expm1"))


# =====================================================================
# item 5: the constants
# =====================================================================

def test_the_constants_check_as_a_module_passes_and_can_exit_nonzero(
        monkeypatch, capsys):
    """`python -m cft_golden.mathlib --check` over the six routines and four
    formats: exit 0 and what it checked; then, with a routine built with a
    wrong word at fp64 - exp's table word, exp2's ln 2 high word, expm1's
    first Cody-Waite word, log's middle word of ln 2 (defect 2), log2's low
    word of 1/ln 2, log1p's r = x threshold (defect 8's) - exit 1 and the
    difference by name. `--only` limits the routines the check or the listing
    runs, and refuses a name that is not one."""
    done = subprocess.run([sys.executable, "-m", "cft_golden.mathlib",
                           "--check"], cwd=PYTHON_DIR, capture_output=True,
                          text=True)
    assert done.returncode == 0, done.stdout + done.stderr
    assert "6 routines, 4 formats, 0 differences" in done.stdout
    for fn in FUNCS:
        for fmt in FORMATS:
            assert f"{fn} {fmt.name}: G = {ml.GUARD[fmt.name]}" in done.stdout
    for fn in LOG_FUNCS:                  # RECIP_SEED's cells are in the lines
        assert done.stdout.count("RECIP_SEED's 512 cells") >= 12
    assert ml.main(["--check", "--only", "log2"]) == 0
    shown = capsys.readouterr().out
    assert "1 routines, 4 formats, 0 differences" in shown
    assert "log fp64" not in shown and "log2 fp64" in shown
    with pytest.raises(SystemExit):
        ml.main(["--check", "--only", "sqrt"])
    capsys.readouterr()
    real = ml.build
    monkeypatch.setattr(ml, "FORMATS", (FP64,))
    for plant, fn, role in (("table_entry", "exp", "TH3"),
                            ("ln2_ulp", "exp2", "LN2H"),
                            ("c1_ulp", "expm1", "NC1"),
                            ("ln2_two_words", "log", "LN2M"),
                            ("il2_short", "log2", "NIL2L"),
                            ("small_2m4", "log1p", "SMALL")):
        monkeypatch.setattr(ml, "build", lambda name, fmt, rnd, _p=plant,
                            _f=fn, **kw: real(name, fmt, rnd, plant=_p
                                              if name == _f else None, **kw))
        assert ml.main(["--check", "--only", fn]) == 1
        shown = capsys.readouterr().out
        assert "DIFFERENCE" in shown and f"{fn} fp64" in shown \
            and role in shown, (plant, shown[-400:])


@pytest.mark.parametrize("fn", FUNCS)
def test_the_derived_constants_are_what_the_independent_derivation_says(fn):
    """Spot values read from outside the generator: ln 2 to 3,200 bits by
    its atanh series, 2^(j/8) by an integer root, against the words held:
    ln 2 as derived, the table's eight high words, the Cody-Waite sum (exp2:
    ln 2's own words). The log family's: log(16/C) by the atanh series in
    integers, 1/ln 2 from ln 2's enclosure, and the words of ln 2 (log, log1p)
    or 1/ln 2 (log2) summing to them."""
    assert H.check_spot(fn=fn) == []


def test_recip_seeds_cells_are_what_the_log_reduction_assumes():
    """The 512 cells of RECIP_SEED at each format (the study's 8, item 5): the
    instruction gives the table's value, from its definition in integers,
    at both ends of every cell; C = round(16 seed) takes every value from 8 to
    16; max |r| = 0.0590820 = 2^-4.081 exactly (121/2048 less the last float,
    at C = 9), the same at fp64, fp128 and fp256 to the last float, under
    RHO_LOG = 0.0592 and over log1p's 15/256."""
    assert H.check_recip() == []
    for fmt in FORMATS:
        found, rmax, cs = ml._check_recip_cells(fmt)
        assert found == [] and cs == set(range(8, 17))
        assert ml.SMALL_LOG < rmax < ml.RHO_LOG
        assert float(rmax) == pytest.approx(0.05908203125, rel=1e-5)
        assert Fraction(121, 2048) - rmax <= Fraction(
            1, 2 ** (fmt.prec - 1)) * 2
    # the table's definition is the instruction's: a cell the check does not
    # believe is found by name
    wrong = H.check_recip(FP64, entry=lambda i: ml._seed_entry(i)
                          + (1 << 14 if i == 100 else 0))
    assert wrong and all(s.startswith("recip:") for s in wrong)


# =====================================================================
# the plants: a fault for every check, shown caught by name
# =====================================================================

# The mutations of a fresh build or of its fragment, for the checks whose
# faults the builder cannot make because the specialised fragment and the
# instrumented form both come from one body: name -> (what it is, a function
# (build, fragment) -> (build, fragment)). Each works on the fresh build that
# run_check makes, never on the cache.

def _select_unsimplified(b, f):
    res = f.result
    body = f.body + ((sf.OP_SELECT, None, (res, res, res)),)
    return b, _mutated(f, body=body, result=("v", len(f.body)))


def _operand_swapped(b, f):
    i = [k for k, (op, _r, _s) in enumerate(f.body) if op == sf.OP_SUB][0]
    op, r, (s0, s1) = f.body[i]
    return b, _mutated(f, body=_bodies(f, **{f"i{i}": (op, r, (s1, s0))}))


def _phase_short(b, f):
    b.phase_of.pop()
    return b, f


def _probe_dropped(b, f):
    del b.probes["Bv"]
    return b, f


MUTATIONS = {
    "select_unsimplified": (
        "a SELECT of one value three times appended as the result: the "
        "same value, but the fragment is not in the specialised form",
        _select_unsimplified),
    "operand_swapped": (
        "the first SUB of the fragment with its operands swapped: the "
        "instrumented form no longer computes what the fragment does",
        _operand_swapped),
    "phase_short": (
        "an instruction without its phase in the instrumented form",
        _phase_short),
    "probe_dropped": (
        "the probe Bv, which the budget reads, missing", _probe_dropped),
}


# Faults of an independent derivation, for the spot check: name -> (what it
# is, the keyword arguments of H.check_spot that plant it).

def _ln2_wrong():
    return {"ln2": ml._ln2() + Fraction(1, 2 ** 200)}


def _enclosure_loose():
    lo, hi = ml._check_ln2()
    return {"enclosure": (lo - Fraction(1, 2 ** 100), hi)}


def _seed_entry_wrong():
    """RECIP_SEED's table with cell 100's entry one C higher (16 seed is 1
    more): the table the check derives no longer matches the instruction's."""
    return {"entry": lambda i: ml._seed_entry(i) + ((1 << 14) if i == 100
                                                    else 0)}


TOOLS = {
    "ln2_wrong": ("the generator's ln 2 off by 2^-200", _ln2_wrong),
    "enclosure_loose": ("the independent enclosure of ln 2 no tighter than "
                        "2^-100", _enclosure_loose),
    "seed_entry_wrong": ("RECIP_SEED's table, as the check derives it, with "
                         "cell 100's entry one C higher than the "
                         "instruction's", _seed_entry_wrong),
}

# the checks of the table, and the harness function each is
CHECK_FUNCTIONS = {
    "pools": "check_pools", "edges": "check_edges",
    "lanes": "check_random_lanes", "bound": "check_bound",
    "budget": "check_budget", "rate": "check_rate",
    "family": "check_family", "constants": "check_constants",
    "census": "check_census_empty", "census_counts": "check_census_counts",
    "nofamily": "check_nofamily", "reorder": "check_reorder",
    "shape": "check_shape", "sums": "check_sums",
    "specialised": "check_specialised", "fixed_grid": "check_fixed_grid",
    "spot": "check_spot", "recip": "check_recip",
}
# the checks that apply to each routine, and so the columns of its rows: exp2
# has no family (nofamily instead of family, census and census_counts), expm1
# no fixed grid
CHECKS_OF = {
    "exp": ("pools", "edges", "lanes", "bound", "budget", "rate", "family",
            "constants", "census", "census_counts", "reorder", "shape",
            "sums", "specialised", "fixed_grid", "spot"),
    "exp2": ("pools", "edges", "lanes", "bound", "budget", "rate", "nofamily",
             "constants", "reorder", "shape", "sums", "specialised",
             "fixed_grid", "spot"),
    "expm1": ("pools", "edges", "lanes", "bound", "budget", "rate", "family",
              "constants", "census", "census_counts", "reorder", "shape",
              "sums", "specialised", "spot"),
    # the log family (parcel MB2): log and log1p have windows, log2 none; all
    # three read RECIP_SEED's cells; none has a fixed grid
    "log": ("pools", "edges", "lanes", "bound", "budget", "rate", "family",
            "constants", "census", "census_counts", "reorder", "shape",
            "sums", "specialised", "spot", "recip"),
    "log2": ("pools", "edges", "lanes", "bound", "budget", "rate", "nofamily",
             "constants", "reorder", "shape", "sums", "specialised", "spot",
             "recip"),
    "log1p": ("pools", "edges", "lanes", "bound", "budget", "rate", "family",
              "constants", "census", "census_counts", "reorder", "shape",
              "sums", "specialised", "spot", "recip"),
}


def applicable(check, fn, fmt):
    """Whether `check` runs on `fn` at `fmt`: fp32 has no budget (its V is
    three words) and no windows, its census is the check of that; the
    census's counts and the windows are the double word's."""
    if check not in CHECKS_OF[fn]:
        return False
    if check in ("budget", "family", "census_counts"):
        return fmt is not FP32
    if check == "census":
        return fmt is FP32
    return True


# the checks whose plants are tests of their own below
ELSEWHERE = {
    "check_seq": "test_the_seq_check_sees_a_faulted_evaluator",
    "check_r24": "test_the_r24_check_sees_a_flag_left_loud",
    "check_invariants": "test_each_clause_of_the_invariants_can_fail",
    "check_family_list": "test_the_census_and_family_list_checks_can_fail",
}
# the common comparison of pools, edges, lanes and seq, which has no name of
# its own in a finding: their plants are its
HELPERS = {"check_lanes"}


def run_check(check, plant, fn, fmt, rnd):
    """The findings of the check `check` on `fn` built under `plant`: a fault
    of the builder (mathlib.PLANTS), of the budget tool
    (mathlib_budget.PLANTS), of an independent derivation (TOOLS) or a
    mutation of the fresh build or its fragment (MUTATIONS); None builds
    clean."""
    builder_plant = plant if plant in ml.PLANTS else None
    b = ml.build(fn, fmt, rnd, plant=builder_plant)
    f = b.fragment()
    if plant in MUTATIONS:
        b, f = MUTATIONS[plant][1](b, f)
    if check == "pools":
        return H.check_pools(f)[0]
    if check == "edges":
        return H.check_edges(f)[0]
    if check == "lanes":
        return H.check_random_lanes(f, 60, 3)[0]
    if check == "bound":
        return H.check_bound(b, H.random_main(fmt, 100, 1, fn)
                             + H.placed(fmt, fn))[0]
    if check == "budget":
        return H.check_budget(
            b, H.weighted(fmt, 20, 3, fn) + H.placed(fmt, fn)[::8],
            plant=plant if plant in B.PLANTS else None)[0]
    if check == "family":
        cen = F.FAMILY[fn][fmt.name][sf.RND_NAMES[rnd]]
        return H.check_family(f, [cen[0], cen[len(cen) // 2], cen[-1]],
                              deep=True)[0]
    if check == "rate":
        return H.check_rate(fmt, rnd, 1000, 7, plant=builder_plant, fn=fn)[0]
    if check == "constants":
        return H.check_constants(
            builder=lambda name, ff, rr: ml.build(name, ff, rr,
                                                  plant=builder_plant),
            formats=(fmt,), attrs=(rnd,), names=(fn,))[0]
    if check == "census":
        return H.check_census_empty(f)[0]
    if check == "census_counts":
        return H.check_census_counts(f, CENSUS_MARKS[fn][fmt.name])
    if check == "nofamily":
        return H.check_nofamily(f)[0]
    if check == "reorder":
        return H.check_reorder(b, f)
    if check == "shape":
        return H.check_shape(f, SHAPE[fn][fmt.name][RND.index(rnd)])
    if check == "sums":
        return H.check_sums(b, f)
    if check == "specialised":
        return H.check_specialised(b, f)
    if check == "fixed_grid":
        return H.check_fixed_grid(b)
    if check == "spot":
        kw = TOOLS[plant][1]() if plant in TOOLS else {}
        return H.check_spot(
            builder=lambda ff, rr: ml.build(fn, ff, rr, plant=builder_plant),
            formats=(fmt,), rnd=rnd, fn=fn, **kw)
    if check == "recip":
        return H.check_recip(fmt, **(TOOLS[plant][1]() if plant in TOOLS
                                     else {}))
    raise ValueError(check)


# (plant, routine, format, attribute, the checks it must turn red, the checks
# that must stay green[, {check: text every one of its findings must hold}]).
# Each red check must return a finding that begins with its own name. The
# green ones are the study's "and only it": a fault in the reduction's low
# word or the polynomial is invisible to the pools and to the structured
# lanes and is the bound's alone. The rows are filled from the measurement of
# every (plant, check) pair (parcel MB1's plantmap, in the entry).
PLANTED = [
    # ---- exp: E1's rows, and the reorder's
    ("table_entry", "exp", FP64, RNE,
     ('pools', 'edges', 'lanes', 'bound', 'budget', 'rate', 'constants',
      'spot'),
     ('reorder', 'specialised', 'family')),
    ("c1_ulp", "exp", FP64, RNE,
     ('pools', 'edges', 'lanes', 'bound', 'budget', 'rate', 'constants',
      'spot'),
     ('reorder', 'specialised', 'family')),
    ("bound_loose", "exp", FP64, RNE,
     ('bound', 'budget', 'rate', 'family', 'constants', 'census_counts'),
     ('pools', 'edges', 'lanes')),
    ("bound_wide", "exp", FP64, RNE,
     ('rate', 'family', 'constants', 'fixed_grid'),
     ('bound', 'pools', 'edges')),
    ("bound_wide", "exp", FP32, RNE,
     ('pools', 'rate', 'constants', 'census', 'fixed_grid'),
     ('bound', 'edges', 'lanes')),
    ("bound_half", "exp", FP128, RNE,
     ('family', 'constants'),
     ('bound', 'pools', 'edges')),
    ("bound_double", "exp", FP128, RNE,
     ('rate', 'family', 'constants'),
     ('bound', 'pools', 'edges')),
    ("mark_silenced", "exp", FP64, RNE,
     ('pools', 'rate', 'family', 'census_counts', 'shape', 'sums'),
     ('bound', 'edges', 'lanes')),
    ("mark_silenced", "exp", FP64, RDN,
     ('pools', 'rate', 'family', 'census_counts', 'shape', 'sums'),
     ('bound', 'edges', 'lanes')),
    ("mark_forced", "exp", FP64, RNE,
     ('pools', 'edges', 'lanes', 'rate', 'family', 'census_counts', 'shape',
      'sums', 'fixed_grid'),
     ('bound', 'constants', 'reorder')),
    ("rl_through_y", "exp", FP64, RNE,
     ('bound', 'budget', 'shape'),
     ('pools', 'edges', 'lanes')),
    ("c3_dropped", "exp", FP64, RNE,
     ('bound', 'budget', 'constants', 'shape', 'spot'),
     ('pools', 'edges', 'lanes')),
    ("tiny_gate_off", "exp", FP64, RDN,
     ('pools', 'shape'),
     ('bound', 'edges', 'lanes')),
    ("screen_ulp", "exp", FP64, RNE,
     ('pools', 'edges', 'constants'),
     ('bound', 'lanes', 'rate')),
    ("head_short", "exp", FP64, RNE,
     ('bound', 'budget', 'constants', 'shape', 'sums'),
     ('pools', 'edges', 'lanes')),
    ("tininess_klt_only", "exp", FP64, RNE,
     ('pools', 'edges', 'shape', 'sums'),
     ('bound', 'lanes', 'rate')),
    ("c0_wrong", "exp", FP64, RNE,
     ('edges', 'constants'),
     ('bound', 'pools', 'lanes')),
    ("square_term_dropped", "exp", FP32, RNE,
     ('bound', 'constants', 'shape'),
     ('pools', 'edges', 'lanes')),
    ("two_sum_all", "exp", FP64, RNE,
     ('shape', 'sums'),
     ('bound', 'pools', 'edges')),
    ("two_sum_all", "exp", FP32, RNE,
     ('shape', 'sums'),
     ('bound', 'pools', 'edges')),
    ("abs_by_copysign", "exp", FP64, RNE,
     ('sums',),
     ('bound', 'pools', 'edges')),
    ("odd_dropped", "exp", FP64, RNE,
     ('shape', 'fixed_grid'),
     ('bound', 'pools', 'edges')),
    ("odd_dropped", "exp", FP32, RNE,
     ('shape', 'fixed_grid'),
     ('bound', 'pools', 'edges')),
    ("reorder_misnumbered", "exp", FP32, RNE,
     ('pools', 'edges', 'lanes', 'rate', 'census', 'reorder'),
     ('bound', 'constants', 'specialised')),
    ("reorder_forward", "exp", FP64, RNE,
     ('reorder',),
     ('bound', 'constants', 'spot')),
    ("capacities_dropped", "exp", FP128, RNE,
     ('budget',),
     ('bound', 'pools', 'edges'),
     {"budget": "is past the budget's bound"}),
    ("ln2_wrong", "exp", FP64, RNE,
     ('spot',),
     ('bound', 'pools', 'edges')),
    ("enclosure_loose", "exp", FP64, RNE,
     ('spot',),
     ('bound', 'pools', 'edges')),
    ("select_unsimplified", "exp", FP64, RNE,
     ('reorder', 'shape', 'specialised'),
     ('bound', 'pools', 'edges')),
    ("operand_swapped", "exp", FP64, RNE,
     ('pools', 'edges', 'lanes', 'reorder', 'specialised'),
     ('bound', 'rate', 'constants')),
    ("phase_short", "exp", FP64, RNE,
     ('specialised',),
     ('bound', 'pools', 'edges')),
    ("probe_dropped", "exp", FP64, RNE,
     ('specialised',),
     ('pools', 'edges', 'lanes')),
    # ---- exp2: its own faults, and the shared ones at its builders
    ("exact_no_j", "exp2", FP64, RNE,
     ('pools', 'edges', 'shape'),
     ('bound', 'rate', 'constants')),
    ("tie_screen", "exp2", FP64, RMM,
     ('pools', 'edges', 'shape'),
     ('bound', 'lanes', 'rate')),
    ("tie_screen", "exp2", FP32, RMM,
     ('pools', 'edges'),
     ('bound', 'lanes')),
    ("ln2_ulp", "exp2", FP64, RNE,
     ('pools', 'lanes', 'bound', 'budget', 'rate', 'constants', 'spot'),
     ('reorder', 'specialised', 'nofamily')),
    ("ln2_ulp", "exp2", FP32, RNE,
     ('bound', 'constants'),
     ('reorder', 'specialised')),
    ("ln2_short", "exp2", FP64, RNE,
     ('lanes', 'bound', 'constants'),
     ('pools', 'edges', 'reorder')),
    ("ln2_short", "exp2", FP32, RNE,
     ('bound', 'constants', 'shape'),
     ('pools', 'edges', 'lanes')),
    ("table_entry", "exp2", FP32, RNE,
     ('pools', 'bound', 'constants', 'spot'),
     ('reorder', 'specialised', 'nofamily')),
    ("rl_through_y", "exp2", FP64, RNE,
     ('bound', 'budget', 'shape'),
     ('pools', 'lanes', 'rate')),
    ("bound_loose", "exp2", FP64, RNE,
     ('bound', 'rate', 'constants'),
     ('pools', 'edges', 'lanes')),
    ("bound_wide", "exp2", FP64, RNE,
     ('rate', 'constants', 'fixed_grid'),
     ('bound', 'pools', 'edges')),
    ("mark_silenced", "exp2", FP64, RNE,
     ('rate', 'shape', 'sums'),
     ('bound', 'pools', 'edges')),
    ("mark_forced", "exp2", FP64, RNE,
     ('pools', 'nofamily', 'fixed_grid'),
     ('bound', 'constants', 'reorder')),
    ("screen_ulp", "exp2", FP64, RNE,
     ('pools', 'edges', 'constants'),
     ('bound', 'lanes', 'rate')),
    ("head_short", "exp2", FP64, RNE,
     ('bound', 'budget', 'constants', 'sums'),
     ('pools', 'edges', 'lanes')),
    ("tininess_klt_only", "exp2", FP64, RNE,
     ('edges', 'nofamily', 'sums'),
     ('bound', 'pools', 'lanes')),
    ("c0_wrong", "exp2", FP64, RNE,
     ('edges', 'constants'),
     ('bound', 'pools', 'lanes')),
    ("odd_dropped", "exp2", FP64, RNE,
     ('fixed_grid', 'shape'),
     ('bound', 'pools', 'edges')),
    ("square_term_dropped", "exp2", FP32, RNE,
     ('bound', 'constants', 'shape'),
     ('pools', 'edges', 'lanes')),
    ("two_sum_all", "exp2", FP64, RNE,
     ('shape', 'sums'),
     ('bound', 'pools', 'edges')),
    ("abs_by_copysign", "exp2", FP64, RNE,
     ('sums',),
     ('bound', 'pools', 'edges')),
    ("reorder_misnumbered", "exp2", FP32, RNE,
     ('pools', 'nofamily', 'reorder', 'specialised'),
     ('bound', 'constants', 'spot')),
    ("reorder_forward", "exp2", FP64, RNE,
     ('reorder',),
     ('bound', 'constants', 'spot')),
    ("tiny_gate_off", "exp2", FP64, RDN,
     ('pools', 'shape'),
     ('bound', 'edges', 'lanes')),
    # ---- expm1: its own faults, and the shared ones at its builders
    ("table_entry", "expm1", FP64, RNE,
     ('pools', 'lanes', 'bound', 'budget', 'constants', 'spot'),
     ('reorder', 'specialised', 'family')),
    ("table_entry", "expm1", FP32, RNE,
     ('pools', 'bound', 'constants'),
     ('reorder', 'specialised', 'census')),
    ("c1_ulp", "expm1", FP64, RNE,
     ('pools', 'bound', 'constants', 'spot'),
     ('reorder', 'specialised', 'family')),
    ("c1_ulp", "expm1", FP32, RNE,
     ('pools', 'bound', 'constants'),
     ('reorder', 'specialised')),
    ("c3_dropped", "expm1", FP64, RNE,
     ('bound', 'budget', 'constants', 'shape', 'spot'),
     ('pools', 'edges', 'lanes')),
    ("rl_through_y", "expm1", FP64, RNE,
     ('bound', 'budget', 'shape'),
     ('pools', 'edges', 'lanes')),
    ("bound_loose", "expm1", FP64, RNE,
     ('bound', 'rate', 'family', 'census_counts'),
     ('pools', 'lanes', 'reorder')),
    ("bound_wide", "expm1", FP64, RNE,
     ('rate', 'family', 'census_counts'),
     ('bound', 'pools', 'edges')),
    ("bound_wide", "expm1", FP32, RNE,
     ('pools', 'rate', 'census'),
     ('bound', 'edges', 'lanes')),
    ("bound_half", "expm1", FP128, RNE,
     ('family', 'constants'),
     ('bound', 'pools', 'edges')),
    ("bound_double", "expm1", FP128, RNE,
     ('rate', 'family'),
     ('bound', 'pools', 'edges')),
    ("mark_silenced", "expm1", FP64, RNE,
     ('pools', 'edges', 'shape', 'sums'),
     ('bound', 'lanes', 'constants')),
    ("mark_forced", "expm1", FP64, RNE,
     ('pools', 'lanes', 'family', 'shape'),
     ('bound', 'constants', 'reorder')),
    ("head_short", "expm1", FP64, RNE,
     ('bound', 'budget', 'constants', 'sums'),
     ('pools', 'edges', 'lanes')),
    ("screen_ulp", "expm1", FP64, RNE,
     ('edges', 'constants'),
     ('bound', 'lanes', 'rate')),
    ("square_term_dropped", "expm1", FP32, RNE,
     ('bound', 'constants', 'shape'),
     ('pools', 'edges', 'lanes')),
    ("two_sum_all", "expm1", FP32, RNE,
     ('shape', 'sums'),
     ('bound', 'pools', 'edges')),
    ("abs_by_copysign", "expm1", FP64, RNE,
     ('sums',),
     ('bound', 'pools', 'edges')),
    ("tiny_path_off", "expm1", FP64, RNE,
     ('pools', 'edges', 'shape'),
     ('bound', 'lanes', 'rate')),
    ("m1_screen_off", "expm1", FP64, RNE,
     ('pools', 'edges', 'constants'),
     ('bound', 'lanes', 'rate')),
    ("m1_answer_rne", "expm1", FP64, RTZ,
     ('pools', 'constants', 'shape'),
     ('bound', 'lanes', 'rate')),
    ("clamp_low", "expm1", FP64, RNE,
     ('bound', 'budget', 'constants'),
     ('pools', 'edges', 'lanes')),
    ("clamp_low", "expm1", FP32, RNE,
     ('bound', 'constants'),
     ('pools', 'edges', 'lanes')),
    ("ea_dropped", "expm1", FP64, RNE,
     ('pools', 'lanes', 'bound', 'budget', 'rate', 'shape'),
     ('constants', 'reorder', 'specialised')),
    ("ea_dropped", "expm1", FP32, RNE,
     ('pools', 'bound', 'shape'),
     ('constants', 'reorder', 'specialised')),
    ("nminn_dropped", "expm1", FP64, RTZ,
     ('pools', 'edges', 'constants'),
     ('bound', 'lanes', 'rate')),
    ("reorder_misnumbered", "expm1", FP64, RNE,
     ('pools', 'family', 'reorder', 'specialised'),
     ('bound', 'constants', 'spot')),
    ("reorder_forward", "expm1", FP32, RNE,
     ('reorder',),
     ('bound', 'constants', 'spot')),
    # ---- the log family (parcel MB2). The rows list the reds that show the
    # fault by name and enough greens to show it is not everything; the map of
    # every (plant, check) pair they come from is in docs/VALIDATION.md's entry.
    # Each routine has every check of CHECKS_OF red in a row of its own.
    # ---- log: its own faults, and the shared ones at its builders
    ("table_entry", "log", FP64, RNE,
     ('pools', 'edges', 'lanes', 'bound', 'budget', 'constants'),
     ('reorder', 'specialised', 'family')),
    ("table_entry", "log", FP32, RNE,
     ('pools', 'bound', 'constants'),
     ('reorder', 'specialised', 'census')),
    ("r_ulp", "log", FP64, RNE,
     ('pools', 'lanes', 'bound', 'family', 'census_counts', 'shape'),
     ('reorder', 'sums', 'specialised')),
    ("r_ulp", "log", FP32, RNE,
     ('bound', 'census', 'shape'),
     ('reorder', 'sums', 'specialised')),
    ("wrap_off", "log", FP64, RNE,
     ('pools', 'edges', 'lanes', 'bound', 'shape'),
     ('reorder', 'sums', 'specialised')),
    ("ln2_two_words", "log", FP64, RNE,
     ('bound', 'budget', 'constants', 'shape', 'spot'),
     ('pools', 'edges', 'lanes')),
    ("ln2_two_words", "log", FP32, RNE,
     ('bound', 'constants', 'shape'),
     ('pools', 'reorder', 'specialised')),
    ("ln2h_ulp", "log", FP64, RNE,
     ('pools', 'lanes', 'bound', 'budget', 'spot'),
     ('family', 'census_counts', 'reorder')),
    ("head_short", "log", FP64, RNE,
     ('bound', 'budget', 'constants', 'shape', 'sums'),
     ('pools', 'edges', 'lanes')),
    ("bound_loose", "log", FP64, RNE,
     ('bound', 'rate', 'family', 'census_counts'),
     ('pools', 'lanes', 'reorder')),
    ("mark_silenced", "log", FP64, RDN,
     ('pools', 'edges', 'lanes', 'family', 'census_counts', 'shape', 'sums'),
     ('bound', 'constants', 'reorder')),
    ("mark_forced", "log", FP64, RNE,
     ('pools', 'lanes', 'census_counts', 'shape', 'sums'),
     ('bound', 'constants', 'reorder')),
    ("two_sum_all", "log", FP64, RNE,
     ('shape', 'sums'),
     ('bound', 'pools', 'edges')),
    ("abs_by_copysign", "log", FP64, RNE,
     ('sums',),
     ('bound', 'pools', 'edges')),
    ("reorder_misnumbered", "log", FP64, RNE,
     ('pools', 'reorder', 'specialised'),
     ('bound', 'spot', 'shape')),
    ("reorder_forward", "log", FP64, RNE,
     ('reorder',),
     ('bound', 'constants', 'spot')),
    ("capacities_dropped", "log", FP64, RNE,
     ('budget',),
     ('bound', 'pools', 'edges'),
     {"budget": "is past the budget's bound"}),
    ("seed_entry_wrong", "log", FP64, RNE,
     ('recip',),
     ('reorder', 'specialised', 'shape')),
    # ---- log2: its own faults (1/ln 2, the exact test), and the shared ones
    ("table_entry", "log2", FP64, RNE,
     ('pools', 'edges', 'lanes', 'bound', 'budget', 'constants'),
     ('reorder', 'specialised', 'nofamily')),
    ("r_ulp", "log2", FP64, RNE,
     ('pools', 'bound', 'nofamily', 'shape'),
     ('reorder', 'sums', 'specialised')),
    ("il2_short", "log2", FP64, RNE,
     ('lanes', 'bound', 'constants', 'spot'),
     ('pools', 'reorder', 'specialised')),
    ("il2_short", "log2", FP32, RNE,
     ('bound', 'constants', 'shape'),
     ('pools', 'reorder', 'specialised')),
    ("il2h_ulp", "log2", FP64, RNE,
     ('pools', 'bound', 'spot'),
     ('reorder', 'shape', 'sums')),
    ("exact_x_one", "log2", FP64, RNE,
     ('pools', 'edges'),
     ('lanes', 'bound', 'shape')),
    ("head_short", "log2", FP64, RNE,
     ('bound', 'budget', 'constants', 'shape', 'sums'),
     ('pools', 'edges', 'lanes')),
    ("bound_loose", "log2", FP64, RNE,
     ('bound', 'budget', 'rate', 'constants'),
     ('pools', 'edges', 'lanes')),
    ("bound_wide", "log2", FP64, RNE,
     ('rate', 'constants'),
     ('bound', 'pools', 'edges')),
    ("mark_silenced", "log2", FP64, RNE,
     ('rate', 'shape', 'sums'),
     ('bound', 'pools', 'edges')),
    ("mark_forced", "log2", FP64, RNE,
     ('pools', 'nofamily', 'shape'),
     ('bound', 'constants', 'reorder')),
    ("two_sum_all", "log2", FP64, RNE,
     ('shape', 'sums'),
     ('bound', 'pools', 'edges')),
    ("reorder_misnumbered", "log2", FP32, RNE,
     ('reorder', 'specialised'),
     ('bound', 'spot', 'shape')),
    ("reorder_forward", "log2", FP64, RNE,
     ('reorder',),
     ('bound', 'constants', 'spot')),
    ("seed_entry_wrong", "log2", FP64, RNE,
     ('recip',),
     ('reorder', 'specialised', 'shape')),
    # ---- log1p: its own faults (the low word, the paths, the tiny path)
    ("table_entry", "log1p", FP64, RNE,
     ('pools', 'edges', 'lanes', 'bound', 'budget', 'constants'),
     ('reorder', 'specialised', 'family')),
    ("r_ulp", "log1p", FP64, RNE,
     ('pools', 'lanes', 'bound', 'shape'),
     ('reorder', 'family', 'specialised')),
    ("wrap_off", "log1p", FP64, RNE,
     ('pools', 'bound', 'shape'),
     ('family', 'census_counts', 'reorder')),
    ("ln2_two_words", "log1p", FP64, RNE,
     ('bound', 'budget', 'constants', 'shape', 'spot'),
     ('pools', 'edges', 'lanes')),
    ("ln2h_ulp", "log1p", FP64, RNE,
     ('pools', 'bound', 'spot'),
     ('family', 'census_counts', 'reorder')),
    ("small_2m4", "log1p", FP64, RNE,
     ('constants', 'shape'),
     ('pools', 'edges', 'lanes')),
    ("small_2m4", "log1p", FP256, RNE,
     ('bound', 'constants', 'shape'),
     ('pools', 'edges', 'lanes')),
    ("ul_dropped", "log1p", FP64, RNE,
     ('pools', 'lanes', 'bound', 'shape'),
     ('family', 'constants', 'census_counts')),
    ("ul_dropped", "log1p", FP32, RNE,
     ('bound', 'shape'),
     ('constants', 'reorder', 'specialised')),
    ("newton_short", "log1p", FP64, RNE,
     ('bound', 'budget', 'shape'),
     ('pools', 'edges', 'lanes')),
    ("rho2_dropped", "log1p", FP32, RNE,
     ('bound', 'shape'),
     ('pools', 'reorder', 'specialised')),
    ("p2mk_unclamped", "log1p", FP64, RNE,
     ('pools', 'constants', 'shape'),
     ('lanes', 'bound', 'budget')),
    ("p2mk_unclamped", "log1p", FP32, RNE,
     ('edges', 'shape'),
     ('lanes', 'bound', 'reorder')),
    ("tiny_path_off", "log1p", FP64, RNE,
     ('pools', 'edges', 'shape'),
     ('lanes', 'bound', 'reorder')),
    ("pminn_dropped", "log1p", FP64, RTZ,
     ('pools', 'edges', 'shape'),
     ('lanes', 'bound', 'reorder')),
    ("head_short", "log1p", FP64, RNE,
     ('bound', 'shape', 'sums'),
     ('pools', 'edges', 'lanes')),
    ("bound_loose", "log1p", FP64, RNE,
     ('bound', 'rate', 'family', 'census_counts'),
     ('edges', 'lanes', 'reorder')),
    ("bound_wide", "log1p", FP32, RNE,
     ('census',),
     ('lanes', 'bound', 'reorder')),
    ("bound_half", "log1p", FP128, RNE,
     ('family',),
     ('bound', 'lanes', 'reorder')),
    ("bound_double", "log1p", FP128, RNE,
     ('family',),
     ('bound', 'lanes', 'reorder')),
    ("mark_silenced", "log1p", FP64, RNE,
     ('pools', 'family', 'census_counts', 'shape', 'sums'),
     ('lanes', 'bound', 'constants')),
    ("mark_forced", "log1p", FP64, RNE,
     ('pools', 'lanes', 'census_counts', 'shape', 'sums'),
     ('bound', 'constants', 'reorder')),
    ("two_sum_all", "log1p", FP32, RNE,
     ('shape', 'sums'),
     ('reorder', 'specialised', 'bound')),
    ("reorder_misnumbered", "log1p", FP64, RNE,
     ('pools', 'reorder', 'specialised'),
     ('bound', 'spot', 'shape')),
    ("reorder_forward", "log1p", FP32, RNE,
     ('reorder',),
     ('bound', 'spot', 'sums')),
    ("seed_entry_wrong", "log1p", FP64, RNE,
     ('recip',),
     ('reorder', 'specialised', 'shape')),
]


def _row_id(r):
    return f"{r[0]}-{r[1]}-{r[2].name}-{sf.RND_NAMES[r[3]]}"


def test_every_plant_is_in_the_table_and_every_row_names_a_plant():
    named = {row[0] for row in PLANTED}
    kinds = (set(ml.PLANTS), set(B.PLANTS), set(TOOLS), set(MUTATIONS))
    assert named == set().union(*kinds)
    assert sum(len(k) for k in kinds) == len(named)     # one name, one kind
    for plant, (families, names, text) in ml.PLANTS.items():
        assert families and names and text
        assert set(families.split()) <= {"dw", "tw"}
        assert set(names.split()) <= set(FUNCS)
    for row in PLANTED:
        plant, fn, fmt = row[:3]
        assert set(row[4]) | set(row[5]) <= set(CHECK_FUNCTIONS), row[:4]
        assert not set(row[4]) & set(row[5]), row[:4]
        assert all(applicable(c, fn, fmt) for c in row[4] + row[5]), row[:4]
        if plant in ml.PLANTS:
            families, names, _text = ml.PLANTS[plant]
            assert fn in names.split(), row[:4]
            assert ("tw" if fmt is FP32 else "dw") in families.split(), row[:4]


def test_every_check_of_the_harness_has_a_plant_that_turns_it_red():
    """No check without a fault shown caught by name: every check function
    of the harness is a column of the table with a plant red in it, or has
    a test of its own among those below."""
    assert {n for n in dir(H) if n.startswith("check_")} == \
        set(CHECK_FUNCTIONS.values()) | set(ELSEWHERE) | HELPERS
    red = {c for row in PLANTED for c in row[4]}
    assert set(CHECK_FUNCTIONS) <= red
    for name in ELSEWHERE.values():
        assert callable(globals()[name]), name


def test_every_check_has_a_plant_for_every_routine_it_applies_to():
    """The checks run on each of exp, exp2 and expm1 (CHECKS_OF): every one,
    for each routine, has a row of that routine in which it is red - a fault
    that only one routine's builder can make is not the other's check."""
    for fn in FUNCS:
        red = {c for row in PLANTED if row[1] == fn for c in row[4]}
        assert set(CHECKS_OF[fn]) <= red, (fn, set(CHECKS_OF[fn]) - red)


@pytest.mark.parametrize("row", PLANTED, ids=_row_id)
def test_each_planted_fault_is_caught_by_name_and_the_others_stay_green(row):
    plant, fn, fmt, rnd, red, green, *rest = row
    says = rest[0] if rest else {}
    for check in red:
        found = run_check(check, plant, fn, fmt, rnd)
        assert found and all(s.startswith(check + ":") for s in found), \
            (plant, check, found)
        if check in says:
            assert all(says[check] in s for s in found), (plant, check, found)
    for check in green:
        assert run_check(check, plant, fn, fmt, rnd) == [], (plant, check)


@pytest.mark.parametrize("fn", FUNCS)
def test_a_clean_build_is_green_in_every_check_the_plants_use(fn):
    for check in CHECKS_OF[fn]:
        if check == "census":
            continue
        assert run_check(check, None, fn, FP64, RNE) == [], (fn, check)
    for check in ("shape", "sums", "specialised", "reorder", "spot",
                  "census", "pools") + (("fixed_grid",) if fn in ("exp", "exp2")
                                        else ()) \
            + (("recip",) if fn in LOG_FUNCS else ()):
        if fn in H.NOFAMILY and check == "census":
            continue
        assert run_check(check, None, fn, FP32, RNE) == [], (fn, check)


@pytest.mark.parametrize("fn", ("exp", "exp2"))
def test_a_mark_off_the_structured_list_fails_the_pools(fn):
    """A planted mark OFF the list is test 1's rule 7: the tiny gate removed
    marks the subnormal and tiny arguments under the directed attributes
    (not under rne, where V = 1 + Z cannot straddle a midpoint of 1): at
    fp64 under rdn it marks lanes that are not on the structured list."""
    f = ml.build(fn, FP64, RDN, plant="tiny_gate_off").fragment()
    out, t = H.check_pools(f)
    assert len(out) == 1 and "marked off the structured list" in out[0]
    assert len(t.marked) > (1 if fn == "exp" else 0) and not t.wrong
    g = ml.build(fn, FP64, RNE, plant="tiny_gate_off").fragment()
    assert H.check_pools(g)[0] == []


def test_the_seq_check_sees_a_faulted_evaluator():
    f = ml.fragment("exp", FP64, RDN)
    forced = routines.Fragment(
        f.op, f.fmt, f.rnd, f.inputs,
        tuple((op, RNE if r is not None else None, s)
              for op, r, s in f.body), f.result, f.flags, f.words, f.stage)

    def ignores_the_attributes(frag, x):
        return ml.evaluate(forced, x)
    out, _t = H.check_seq(f, evaluator=ignores_the_attributes)
    assert out and out[0].startswith("seq:") and "differ" in out[0]
    assert H.check_seq(f)[0] == []


def test_the_r24_check_sees_a_flag_left_loud():
    """The first instruction that can raise a flag left outside the quiet
    region: the lanes whose argument makes it overflow carry a flag the
    operation does not raise."""
    f = ml.fragment("exp", FP64, RNE)
    found = H.check_r24(f, loud=True)
    assert found and all(s.startswith("r24:") for s in found)
    assert H.check_r24(f) == []


def test_the_census_and_family_list_checks_can_fail():
    f = ml.build("exp", FP32, RUP, plant="bound_wide").fragment()
    found, t = H.check_census_empty(f)
    assert found and found[0].startswith("census:") and t.marked
    tampered = {fn: {k: {r: list(v) for r, v in per.items()}
                     for k, per in by_fmt.items()}
                for fn, by_fmt in F.FAMILY.items()}
    tampered["exp"]["fp64"]["rne"].pop()
    tampered["exp"]["fp128"]["rtz"].append((1, 1))
    tampered["expm1"]["fp64"]["rtz"].pop()                # a second-family n
    tampered["exp2"]["fp256"]["rne"].append((1, 237))     # a family it lacks
    found = H.check_family_list(tampered)
    assert len(found) == 4 and all(s.startswith("family:") for s in found)
    assert any("exp2 fp256 rne" in s for s in found)
    assert any("expm1 fp64 rtz" in s for s in found)
    assert H.check_family_list(F.FAMILY) == []


@pytest.mark.parametrize("fmt", FORMATS, ids=fid)
def test_the_sweeps_range_is_every_float_once_in_order_with_exact_bounds(fmt):
    """mathlib_runs.py sweep takes every float of [lo, hi], increasing,
    zero once, the bounds inclusive and exact (a bound between two floats
    excludes both), and a shard of n is every n-th: the shards partition."""
    one = sf.one_bits(fmt)
    ulp = ml._dec(fmt, sf.next_up(fmt, one)[0]) - 1
    xs = list(H.range_encodings(fmt, Fraction(1), 1 + 8 * ulp))
    assert xs == [one + d for d in range(9)]
    assert list(H.range_encodings(fmt, 1 + ulp / 2, 1 + 3 * ulp / 2)) == [
        one + 1]
    assert list(H.range_encodings(fmt, 1 + ulp / 2, 1 + ulp / 2)) == []
    tiny = ml._dec(fmt, sf.min_subnormal_bits(fmt))
    ys = list(H.range_encodings(fmt, -2 * tiny, 2 * tiny))
    assert [ml._dec(fmt, y) for y in ys] == [
        -2 * tiny, -tiny, 0, tiny, 2 * tiny]
    shards = [xs[i::4] for i in range(4)]
    assert sorted(sum(shards, [])) == xs and len({len(s) for s in shards}) <= 2


@pytest.mark.parametrize("fmt", FORMATS, ids=fid)
def test_the_sweeps_strided_shards_are_the_walk_of_every_encoding(fmt):
    """sweep_keys takes the lanes of a strided, sharded sweep as an arithmetic
    progression, in the time of the lanes; the form that walked every
    encoding of the range and kept those with idx % stride == 0 and
    (idx // stride) % n == i - the sweep's form until parcel MB2, which cost
    the whole range's walk however few lanes it took - is its oracle here:
    equal over ranges that cross zero, that begin and end between two floats
    and that hold none, for strides and shard counts that divide them
    unevenly, a shard left with no lane and the shards a partition."""
    one = sf.one_bits(fmt)
    ulp = ml._dec(fmt, sf.next_up(fmt, one)[0]) - 1
    tiny = ml._dec(fmt, sf.min_subnormal_bits(fmt))
    ranges = ((Fraction(1), 1 + 40 * ulp),
              (1 + ulp / 2, 1 + 33 * ulp + ulp / 2),
              (1 + ulp / 2, 1 + ulp / 2),
              (-3 * tiny, 4 * tiny))
    for lo, hi in ranges:
        every = list(H.range_encodings(fmt, lo, hi))
        for stride, n in ((1, 3), (7, 3), (50, 5)):
            taken = []
            for i in range(n):
                slow = [x for idx, x in enumerate(every)
                        if idx % stride == 0 and (idx // stride) % n == i]
                fast = [H.key_encoding(fmt, k)
                        for k in H.sweep_keys(fmt, lo, hi, stride, (i, n))]
                assert fast == slow, (lo, hi, stride, i, n)
                taken += fast
            assert sorted(taken) == sorted(every[::stride]), (lo, hi, stride,
                                                              n)
