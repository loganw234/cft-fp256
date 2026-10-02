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
TILE_FEATURES = 0x7f1f              # every tile from revision 6 on


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


BUILTIN = {
    "sw": _sw(),
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
