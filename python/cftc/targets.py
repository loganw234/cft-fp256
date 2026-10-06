# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""The targets a compiled image may be loaded on, stated.

A target is what a device publishes and its loader holds an image to:
the formats it carries, how many instructions it holds, how far a
constant index reaches, how many scratch slots a lane owns, how many
deposit slots a lane owns, and its feature bits (cft_caps.seq_features,
host/include/cft.h). The compiler's lowering never reads a target - one
image, the same bytes, serves every target that accepts it - so a
target decides only which refusal, if any, stops a compilation, and the
manifest lists every built-in target that would accept the image.

The built-in table, and where each number is stated:

  sw            libcft's software backend: host/src/program.c's
                cft_sw_seq_caps, and cft.h at ABI 0.17 (seq_features
                0x7ff1f: revision 8's four bits, R21 to R24, defined
                golden-first). `sw:N` is the same backend opened at N
                scratch slots a lane through cft_open_ex (cft-segrun's
                --scratch-depth), N a power of two up to 32,768.
  u50-rev8      rev8a, the U50's revision-8 single, with R21: 2^24
                instructions, 4,096 scratch slots and 1,024 deposit slots
                a lane (below).
  u50-rev8-quad rev8q, revision 8's streaming quad, without R21: the
                same capacities a tile; a program's lanes are cut across
                the four tiles, so one image serves all four.
  u50-rev8-deep rev8d, revision 8's deep single, with R21: the single's,
                at 8,192 scratch slots a lane.
  u50-rev7      the U50's revision-7 single: docs/SEQUENCER.md, "Revision
                7, the program limits per build" - 32,768 instructions,
                2,048 scratch slots and 1,024 deposit slots a lane.
  u50-rev7-quad the same capacities a tile; a program's lanes are cut
                across the four tiles, so one image serves all four.
  u50-round2    the round-2 images: SEQUENCER.md's capacity table,
                16,384 / 256 / 64. Their feature word is revision 6's
                bits, believed rather than read from an image.
  open-core     the open-core builds: tb/Makefile's OPEN_CAPS_GENERICS
                and hw/openxc7, 16,384 / 256 / 64; formats per build, all
                four unless a build trims them (a trimmed build is a
                Target of its own, written in code).

Revision 8's three images (docs/ROADMAP.md, "Revision 8: step 6's RTL
revision", part 3; their targets parcel E's, 2026-10-05) each hold 2^24
instructions a program, streamed (CAPS2[20:16] = 24, the plan's
question 2), and the U50's 1,024 deposit slots and 512 constants a lane
(CAPS 0x19faffff, unchanged from revision 7). Each publishes revision
8's flag control, FLAG_CONTROL (CAPS2[14]), so the run-time division and
square root (C4's routines) compile for each where revision 7's targets
refuse them `target-feature`. Each target is its image's words as
host/src/caps_decode.h decodes them at VERSION 0x00000b00, and
python/tests/test_cftc.py holds each to them:

  u50-rev8       rev8a, with R21, built "at the slots the quad will
                 have": CAPS2 0x00187ffc, seq_features 0x7ff1f, as
                 device-test -i read them on the card (2026-10-06).
  u50-rev8-quad  rev8q, WITHOUT R21 (EN_AUGADD=0): CAPS2 0x001877fc,
                 seq_features 0x77f1f - CAPS2[11] clear, AUGADD alone
                 apart. Question 9's branch: probe L measured R21's
                 lanes at +10,595 LUTs a tile, far past the 2,000 that
                 would have kept the quad with them.
  u50-rev8-deep  rev8d, with R21: CAPS2 0x00187ffd, seq_features
                 0x7ff1f, the single's words with CAPS2[3:0] at its
                 depth.

rev8q's and rev8d's words are the plan's, computed from rtl/cft_krnl.sv's
assembly ("What a revision-8 U50 tile reads"), and each image's card
legs read its words (device-test -i, 2026-10-06), the plan's exactly.
The depths follow probe K (2026-10-05): the quad fits at 4,096 slots, so
it is built at 4,096 and the single at the quad's; 16,384 slots would
cross both SLRs, so the deep single is built at 8,192. The images and
their card legs are recorded in docs/VALIDATION.md, step 6's closing
entries.

They joined the table together at the images' build, as ONE output
version step (python/cftc/outputs.py; cftc's VERSION 4 to 5), with the
committed manifests regenerated, the output record's block appended and
the certificate corpus remade (`certificates/corpus.py make
--keep-version-1`, as e45a2f7 remade it at cftc 4). Until then they
were PROVISIONAL (the lead's decision on parcel E's question,
2026-10-05): kept out of BUILTIN, get(), names(), the command line and
accepted_by while their depths waited on probe K and on the images, so
that no manifest or certificate named a target whose parameters would
still move ("cftc 4 u50-rev8" would otherwise have meant two images over
time), and reached by Python alone through provisional(name). That table
and its function went when they joined (parcel TG, 2026-10-06): nothing
else is provisional, and a table with no entry would have been a second
way to look a target up that nothing used.
"""

from dataclasses import dataclass

# cft_caps.seq_features, bit by bit (host/include/cft.h). The low nibble
# is CAPS[7:4], the next CAPS[31:28], then CAPS2[7:4] and CAPS2[14:8].
# A name missing here would be dropped from what an image needs, and the
# image accepted where its loader refuses it - so every name asm.py's
# features() can report is one (python/tests/test_cftc.py holds that).
FEATURE_BITS = {
    "WIDE_CONST": 0x01,         # CAPS[4]   kx: indices in the immediate
    "REGS32": 0x02,             # CAPS[5]   r16..r31
    "BANK_PTR": 0x04,           # CAPS[6]   the bank supplied per run
    "KX9": 0x08,                # CAPS[7]   a constant index past 255
    "IMUL": 0x10,               # CAPS[28]
    "SCRATCH": 0x100,           # CAPS2[4]  the per-lane scratch
    "SCRATCH_IO": 0x200,        # CAPS2[5]  its per-run block
    "SCRATCH_STRICT": 0x400,    # CAPS2[6]  revision 4's R8
    "SCALAR": 0x800,            # CAPS2[7]
    "REDUCE_SEG": 0x1000,       # CAPS2[8]
    "INDEXED": 0x2000,          # CAPS2[9]
    "LANE_MASK": 0x4000,        # CAPS2[10]
    "AUGADD": 0x8000,           # CAPS2[11] revision 8, R21
    "SCRATCH_STEP": 0x10000,    # CAPS2[12] revision 8, R22
    "LANE_FLAGS": 0x20000,      # CAPS2[13] revision 8, R23 (a run's option)
    "FLAG_CONTROL": 0x40000,    # CAPS2[14] revision 8, R24
}
CAPS_PLACE = {
    "WIDE_CONST": "CAPS[4]", "REGS32": "CAPS[5]", "BANK_PTR": "CAPS[6]",
    "KX9": "CAPS[7]", "IMUL": "CAPS[28]", "SCRATCH": "CAPS2[4]",
    "SCRATCH_IO": "CAPS2[5]", "SCRATCH_STRICT": "CAPS2[6]",
    "SCALAR": "CAPS2[7]", "REDUCE_SEG": "CAPS2[8]", "INDEXED": "CAPS2[9]",
    "LANE_MASK": "CAPS2[10]", "AUGADD": "CAPS2[11]",
    "SCRATCH_STEP": "CAPS2[12]", "LANE_FLAGS": "CAPS2[13]",
    "FLAG_CONTROL": "CAPS2[14]",
}
# asm.Image.features() names `kx` what cft.h calls WIDE_CONST.
ASM_FEATURE = {"kx": "WIDE_CONST"}

ALL_FORMATS = ("fp32", "fp64", "fp128", "fp256")
SCRATCH_DEPTH_MAX = 1 << 15         # CAPS2[3:0] is a four-bit log2

SW_FEATURES = 0x7ff1f               # ABI 0.17's software handle
TILE_FEATURES = 0x7f1f              # every tile of revisions 6 and 7
# revision 8: the single's and the deep single's word, every bit cft.h
# defines - the software handle's - and the quad's, without R21's AUGADD
# (CAPS2[11])
REV8_FEATURES = 0x7ff1f
REV8_QUAD_FEATURES = 0x77f1f
REV8_INSNS = 1 << 24                # CAPS2[20:16] = 24, streamed
REV8_DEPTH = 4096                   # rev8a and rev8q: probe K's 4,096
REV8_DEEP_DEPTH = 8192              # rev8d: 16,384 would cross both SLRs


@dataclass(frozen=True)
class Target:
    name: str
    formats: tuple
    max_insns: int
    max_consts: int
    scratch_depth: int
    max_deposits: int
    seq_features: int
    where: str = ""

    def features(self):
        """The feature names this target publishes, in bit order."""
        return [n for n, b in FEATURE_BITS.items() if self.seq_features & b]

    def describe(self):
        return {"name": self.name, "formats": list(self.formats),
                "max_insns": self.max_insns, "max_consts": self.max_consts,
                "scratch_depth": self.scratch_depth,
                "max_deposits": self.max_deposits,
                "seq_features": "0x%x" % self.seq_features}


def _sw(depth=256):
    name = "sw" if depth == 256 else f"sw:{depth}"
    return Target(name, ALL_FORMATS, 0xFFFFFFFF, 512, depth, 1 << 20,
                  SW_FEATURES, "host/src/program.c cft_sw_seq_caps; "
                               "cft.h ABI 0.17")


# The software backend first, then the U50's images, the newest revision
# first, then the open core: the order of names(), of --targets and of
# every manifest's accepted_by.
BUILTIN = {
    "sw": _sw(),
    "u50-rev8": Target("u50-rev8", ALL_FORMATS, REV8_INSNS, 512, REV8_DEPTH,
                       1024, REV8_FEATURES,
                       "rev8a, revision 8's single, with R21; "
                       "docs/VALIDATION.md, step 6's closing entries"),
    "u50-rev8-quad": Target("u50-rev8-quad", ALL_FORMATS, REV8_INSNS, 512,
                            REV8_DEPTH, 1024, REV8_QUAD_FEATURES,
                            "rev8q, revision 8's streaming quad, without "
                            "R21, a tile of four; docs/VALIDATION.md, step "
                            "6's closing entries"),
    "u50-rev8-deep": Target("u50-rev8-deep", ALL_FORMATS, REV8_INSNS, 512,
                            REV8_DEEP_DEPTH, 1024, REV8_FEATURES,
                            "rev8d, revision 8's deep single, with R21; "
                            "docs/VALIDATION.md, step 6's closing entries"),
    "u50-rev7": Target("u50-rev7", ALL_FORMATS, 32768, 512, 2048, 1024,
                       TILE_FEATURES,
                       "docs/SEQUENCER.md, revision 7's program limits"),
    "u50-rev7-quad": Target("u50-rev7-quad", ALL_FORMATS, 32768, 512, 2048,
                            1024, TILE_FEATURES,
                            "docs/SEQUENCER.md, revision 7's program "
                            "limits, a tile of four"),
    "u50-round2": Target("u50-round2", ALL_FORMATS, 16384, 512, 256, 64,
                         TILE_FEATURES,
                         "docs/SEQUENCER.md's capacity table; the feature "
                         "word revision 6's, believed"),
    "open-core": Target("open-core", ALL_FORMATS, 16384, 512, 256, 64,
                        TILE_FEATURES,
                        "tb/Makefile OPEN_CAPS_GENERICS; hw/openxc7; the "
                        "feature word believed"),
}


def get(name):
    """A built-in target by name, `sw:N` included, or None."""
    if isinstance(name, Target):
        return name
    if name in BUILTIN:
        return BUILTIN[name]
    if isinstance(name, str) and name.startswith("sw:"):
        text = name[3:]
        # ASCII digits, and no more of them than the largest depth has:
        # str.isdigit() takes a superscript two, which int() refuses, and
        # int() refuses past 4,300 digits - each a bare ValueError once
        if text.isascii() and text.isdigit() and text[0] != "0" and \
                len(text) <= len(str(SCRATCH_DEPTH_MAX)):
            n = int(text)
            if 1 <= n <= SCRATCH_DEPTH_MAX and n & (n - 1) == 0:
                return _sw(n)
    return None


def names():
    return list(BUILTIN)
