# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""Kernel-level end-to-end test: the full cft_krnl RTL against the
golden model, through the same interfaces XRT uses on the card.

cocotbext-axi provides the host (AxiLiteMaster on s_axi_control) and
the HBM (AxiRam on m00_axi). Operand arrays are staged in the RAM, the
CSRs are programmed exactly as host/cft_host does, and every result
element plus the sticky FLAGS register is compared bit-for-bit against
cft_golden.compute - which makes this one test cover the CSR block,
the engine FSM, the AXI master, the operand steering muxes, and both
compute banks."""

import os
import random
import sys
from pathlib import Path

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, ReadOnly, RisingEdge

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "python"))

from cocotbext.axi import (  # noqa: E402
    AxiLiteBus, AxiLiteMaster, AxiRamRead, AxiRamWrite,
    AxiReadBus, AxiWriteBus,
)

from cft_golden import (  # noqa: E402
    FP32, FP64, FP128, FP256, PREC_CODE,
    OP_FMA, OP_ADD, OP_SUB, OP_MUL, OP_NAMES, SIMPLE_OPS,
    OP_COPYSIGN, OP_MAX, OP_MINNUM, OP_SELECT, OP_CMPLT,
    OP_RECIP_SEED, OP_RSQRT_SEED,
    RND_RNE, RND_RTZ, RND_RDN, RND_RUP, RND_RMM, RND_NAMES,
    compute, vectors,
)

# CSR map (cft_csr.sv / hw/kernel.xml)
CTRL, MODE, NREG = 0x00, 0x10, 0x18
APTR, BPTR, CPTR, DPTR = 0x20, 0x28, 0x30, 0x38
FLAGS, MAGIC, VERSION, CAPS, STATUS = 0x40, 0x44, 0x48, 0x4C, 0x50
# The second capability word (revision 3), above the sequencer's
# pointers because appending is the only change a shipped map takes.
CAPS2 = 0x6C

# Every kernel argument's register as rtl/cft_csr.sv decodes it, (offset,
# bytes) by hw/kernel.xml's argument name. kernel_xml_is_the_csr_map
# holds kernel.xml to this table AND writes each argument at the offset
# kernel.xml gives it, reading it back here, so the RTL's decode, the
# xml a bitstream is packaged with and this table cannot part company -
# the header of rtl/cft_csr.sv says "the three must move together", and
# until revision 8's seam nothing checked that they did. LFLAGS_PTR at
# 0xB0 is revision 8's (VERSION 0xB00), argument 17.
CSR_ARGS = {
    "mode": (0x10, 4), "n": (0x18, 8),
    "a": (0x20, 8), "b": (0x28, 8), "c": (0x30, 8), "d": (0x38, 8),
    "prog": (0x54, 8), "cnt": (0x5C, 8), "bank": (0x64, 8),
    "scratch_in": (0x70, 8), "scratch_out": (0x78, 8),
    "seg": (0x80, 8),                        # SEG low, NRES high
    "idx_a": (0x88, 8), "idx_b": (0x90, 8), "idx_c": (0x98, 8),
    "idx_si": (0xA0, 8), "mask": (0xA8, 8),
    "lflags": (0xB0, 8),
}

# ---- what a revision-8 tile reads at its seam --------------------------
# docs/ROADMAP.md, "Revision 8": the seam, and "What a revision-8 U50
# tile reads". VERSION 0xB00, and every revision-8 bit of CAPS and CAPS2
# zero until the item that builds it sets it - CAPS2[11] augadd and
# augerr, [12] the stepped index, [13] the lane-flags block, [14] flag
# control, [20:16] the streamed instruction capacity - so a seam tile's
# words are revision 7's. PINNED here as the plan computed them, for the
# U50's capacities and the open-core ones, beside check_caps2's
# derivation from the RTL: a derived expectation follows a bit set by
# mistake, and these are the words the host's decode
# (host/src/caps_decode.h, held to the same numbers in api-test) and
# cftc's targets were given. When an item sets its bit, its parcel
# changes these words, deliberately. CAPS[3:0] is the build's rungs.
#
# Revision 8's round 2 (parcel C) moves them item by item. Since the fetch's
# hooks (R8S) the U50's store is 4,096 and its capacity 2^24: CAPS[23:20]
# stays 15, min(15, 24), so CAPS is unchanged, and CAPS2[20:16] reads 24.
# Since R24, CAPS2[14] (flag control) on every build, and since R23
# CAPS2[13] (the lane-flag block). Since R21's decode CAPS2[11] where the
# build carries R21 (EN_AUGADD, the plan's question 9): 0x00186FFB at the
# U50's single, and 0x001867FB on the quad's tile, built without it
# (tb/Makefile's krnlseqnoaug) - where the plan's whole revision reads
# 0x00187FFB with [14:11] set, and 0x001877FB without R21
# (docs/ROADMAP.md, "What a revision-8 U50 tile reads"). The open-core
# configurations keep streaming off (SEQ_STREAM_D equal to the store) and
# build without R21 (EN_AUGADD=0, OPEN_CAPS_GENERICS), as the quad does.
VERSION_SEAM = 0x00000B00
SEAM_WORDS = {
    # (SEQ_MAXD, SEQ_IMEM_D, SEQ_SCRATCH_D, SEQ_STREAM_D, EN_AUGADD):
    #     (CAPS with [3:0] clear, CAPS2)
    (1024, 4096, 2048, 1 << 24, 1): (0x19FAFFF0, 0x00186FFB),  # the single
    (1024, 4096, 2048, 1 << 24, 0): (0x19FAFFF0, 0x001867FB),  # quad tile
    (64, 16384, 256, 16384, 0):     (0x19E6FFF0, 0x000067F8),  # open-core
}

# ---- which rungs THIS build carries ------------------------------------
# tb/Makefile's trimmed targets (`krnlf128`, `krnlf64f128`) build the
# kernel with -Pcft_krnl.EN_FP256=0 (and EN_FP32=0) and hand the same
# list here as CFT_GENERICS="EN_FP256=0" - the NAME=VALUE spelling
# hw/package_kernel.tcl, hw/impl_krnl_ooc.tcl and hw/synth_krnl_ooc.tcl
# take - derived from one Makefile variable, so the simulator's build
# and this bench's expectation cannot disagree. Empty is the full tile.
# The mask mirrors rtl/cft_krnl.sv's
# PREC_CAPS = {EN_FP256, EN_FP128, EN_FP64, EN_FP32}: since 2026-09-14
# every rung has a generic, and a build keeps at least one.
def prec_mask_from_env():
    en = {"EN_FP32": 1, "EN_FP64": 1, "EN_FP128": 1, "EN_FP256": 1}
    for g in os.environ.get("CFT_GENERICS", "").split():
        name, _, value = g.partition("=")
        if name in en:
            if value not in ("0", "1"):
                raise ValueError(f"CFT_GENERICS {g!r}: {name} is a bit")
            en[name] = int(value)
    mask = (en["EN_FP32"] | (en["EN_FP64"] << 1) | (en["EN_FP128"] << 2)
            | (en["EN_FP256"] << 3))
    if not mask:
        raise ValueError("CFT_GENERICS leaves no rung; the RTL refuses that too")
    return mask


PREC_MASK = prec_mask_from_env()


def carried(fmt):
    """True if this build advertises the rung; a case at an absent rung is
    not run - it is REFUSED, and that refusal is asserted below."""
    return bool(PREC_MASK & (1 << PREC_CODE[fmt.name]))


# The narrowest rung a build carries is the bench's workhorse. The
# shape-specific cases below - one beat, 37 beats, a ragged burst, a
# 4KB crossing - are written in beats of it (EPB elements make one
# 256-bit beat, so k beats is k * 32 bytes at any rung), and one file
# proves every trim. On the full tile BASE is fp32 and every number is
# what it always was.
BASE = next(f for f in (FP32, FP64, FP128, FP256) if carried(f))
EPB = 256 // BASE.width

import busfx  # noqa: E402

A_BASE, B_BASE, C_BASE, D_BASE = 0x00000, 0x40000, 0x80000, 0xC0000

# CAPS[15:8] is one bit per opcode group. Checked by NAME rather than
# against a literal, and the reason is a bug this assertion had:
# op_caps was written 8'b0010_1111, which sets the reduction bit and
# clears the integer bit, and both benches were updated to expect that
# number. Eight implemented opcodes stopped being advertised, the suite
# stayed green, and device-test skipped them silently because a skip is
# not a failure. The assertion's own message still said "integer ...
# groups present" while asserting they were absent.
#
# A literal cannot say WHICH bit is wrong. This can.
OP_GROUPS = {
    0: "arithmetic",
    1: "sign",
    2: "min/max",
    3: "predicate+select",
    4: "integer",
    5: "reduction",
    6: "divide/sqrt",   # seed opcodes 26/27; sequences composed on host
    7: "sequencer",     # MODE[15] runs a program; cft_seq is instantiated
}
# Bit 7 read "conversion - reserved" until the conversions landed as
# library entry points composed from opcodes that already exist, so the
# group will never take a MODE opcode and the bit was genuinely free.
OP_GROUPS_NOT_BUILT = {}


# CAPS[27:16] carries the SEQUENCER's on-chip capacities, one log2 per
# nibble, and CAPS[7:4] its feature nibble. The expected values are
# PARSED OUT OF THE RTL rather than written here, because a copy of a
# capacity in a test is exactly the thing that goes on agreeing with a
# stale CAPS field forever - which is the defect this register field
# exists to retire (docs/studies/OPT-D-contract.md 0.1). What the test
# asserts is that the register agrees with the parameters the same
# source file hands cft_seq.
RTL = Path(__file__).resolve().parents[1] / "rtl"


def _localparam(path, name):
    """The integer value of `localparam int <name> = <n>;` in a file."""
    import re
    src = path.read_text(encoding="utf-8")
    m = re.search(r"^\s*localparam\s+int\s+%s\s*=\s*(\d+|[A-Za-z_]\w*)\s*;" % name,
                  src, re.MULTILINE)
    assert m, f"{path.name} has no `localparam int {name}`"
    v = m.group(1)
    if v.isdigit():
        return int(v)
    # `localparam int KREG = KMEM_D;` - resolve one level through the
    # module's own parameter list, which is where cft_seq keeps it.
    m2 = re.search(r"\bparameter\s+int\s+%s\s*=\s*(\d+)" % v, src)
    assert m2, f"{path.name}: {name} = {v}, and {v} is not a literal parameter"
    return int(m2.group(1))


def krnl_param(name):
    """A cft_krnl `parameter int` as THIS build has it: the CFT_GENERICS
    override the Makefile target built with, or else the value the
    parameter list declares.

    Revision 7 (2026-09-29) made SEQ_MAXD, SEQ_IMEM_D and SEQ_SCRATCH_D
    parameters, so the U50's numbers are the declared defaults and an
    open-core target overrides them - tb/Makefile's OPEN_CAPS_GENERICS
    reaches the simulator as -P and this bench as CFT_GENERICS, from one
    list. Reading only the declaration would score the board's CAPS
    against the U50's, and reading only the environment would score a
    default build against nothing."""
    import re
    for g in os.environ.get("CFT_GENERICS", "").split():
        gname, _, value = g.partition("=")
        if gname == name:
            assert value.isdigit(), (
                f"CFT_GENERICS {g!r}: {name} is an int parameter")
            return int(value)
    src = (RTL / "cft_krnl.sv").read_text(encoding="utf-8")
    m = re.search(r"^\s*parameter\s+int\s+%s\s*=\s*(\d+)\s*[,)]" % name,
                  src, re.MULTILINE)
    assert m, f"cft_krnl.sv has no `parameter int {name}`"
    return int(m.group(1))


def krnl_param_bit(name):
    """A cft_krnl `parameter bit` as THIS build has it - krnl_param's rule
    for the one-bit build choices: the CFT_GENERICS override (0 or 1) the
    target built with, or else the declared default. Revision 8's
    EN_AUGADD is the first a bench keys on: the quad's tile is built
    without R21 (tb/Makefile's krnlseqnoaug)."""
    import re
    for g in os.environ.get("CFT_GENERICS", "").split():
        gname, _, value = g.partition("=")
        if gname == name:
            assert value in ("0", "1"), (
                f"CFT_GENERICS {g!r}: {name} is a bit parameter")
            return int(value)
    src = (RTL / "cft_krnl.sv").read_text(encoding="utf-8")
    m = re.search(r"^\s*parameter\s+bit\s+%s\s*=\s*1'b([01])" % name,
                  src, re.MULTILINE)
    assert m, f"cft_krnl.sv has no `parameter bit {name}`"
    return int(m.group(1))


def _feat_augadd():
    """CAPS2[11] as this build has it. FEAT_AUGADD has been EN_AUGADD, a
    build parameter, since R21's decode (revision 8's round 2): asserted
    here, so a localparam set back to a constant is a failure and not a
    bit read from the wrong place."""
    import re
    src = (RTL / "cft_krnl.sv").read_text(encoding="utf-8")
    assert re.search(r"^\s*localparam\s+bit\s+FEAT_AUGADD\s*=\s*"
                     r"EN_AUGADD\s*;", src, re.MULTILINE), (
        "cft_krnl.sv's FEAT_AUGADD is no longer EN_AUGADD")
    return krnl_param_bit("EN_AUGADD")


def _port_literal(path, port):
    """The value of a constant 4-bit port wired as `.<port>(4'bxxxx)`."""
    import re
    src = path.read_text(encoding="utf-8")
    m = re.search(r"\.%s\(4'b([01]{4})\)" % port, src)
    assert m, f"{path.name} does not wire .{port}(4'b....)"
    return int(m.group(1), 2)


def caps2_expected():
    """CAPS2 as rtl/cft_krnl.sv declares it: [3:0] log2 SCRATCH_D,
    [4] a scratch exists, [5] its per-run block exists, [6] an indexed
    access past the depth is reported rather than reduced (revision 4).

    Built from the localparam rather than from the port's own literal,
    for the reason the CAPS capacities are: two copies of a number is
    how a capability register ends up describing a memory that is no
    longer that size.

    The whole word is pinned on purpose, so a capability bit cannot
    appear without somebody noticing. Revision 4's did, and this is
    where it was noticed - so ADD the bit here deliberately rather than
    loosening the comparison."""
    d = krnl_param("SEQ_SCRATCH_D")
    assert d == 1 << (d.bit_length() - 1) and d <= 1 << 15, (
        f"SEQ_SCRATCH_D={d} is not a power of two in 1..2^15; CAPS2[3:0] "
        f"publishes its log2 in four bits, "
        f"and STX/LDX reduce modulo the depth with a mask - and, since "
        f"revision 4, decide `past the depth` by bit length, which is "
        f"the same question only for a power of two")
    # [7] is READ FROM THE RTL rather than written here, the way the
    # depth below is: a trimmed build that clears FEAT_SCALAR must make
    # this expectation follow it, not fail. The whole word is pinned so a
    # capability bit cannot appear unnoticed - which is what caught
    # CAPS2[6] and then CAPS2[7].
    scalar = _localparam_bit(RTL / "cft_krnl.sv", "FEAT_SCALAR")
    # [8] likewise: SEG/NRES and the streaming maximum (2026-09-14).
    seg = _localparam_bit(RTL / "cft_krnl.sv", "FEAT_REDUCE_SEG")
    # [9] and [10], ABI 0.14: an input block fetched through an index
    # table (R16) and a per-run lane mask (R17). Read from the RTL like
    # every bit above them, so a build that carries one and not the
    # other is described rather than failed - which is exactly the
    # state of the tile while the two parcels land one at a time.
    indexed = _localparam_bit(RTL / "cft_krnl.sv", "FEAT_INDEXED")
    lmask = _localparam_bit(RTL / "cft_krnl.sv", "FEAT_LANE_MASK")
    # [14:11], revision 8's seam (2026-10-02): R21's augadd and augerr,
    # R22's stepped index, R23's lane-flags block and R24's flag control.
    # Read from the RTL like every bit above them, so each item's parcel
    # sets its own bit and this follows - R21's from the build parameter
    # EN_AUGADD it has been since its decode.
    aug = _feat_augadd()
    step = _localparam_bit(RTL / "cft_krnl.sv", "FEAT_SCRATCH_STEP")
    lflags = _localparam_bit(RTL / "cft_krnl.sv", "FEAT_LANE_FLAGS")
    fctl = _localparam_bit(RTL / "cft_krnl.sv", "FEAT_FLAG_CONTROL")
    # [20:16], the streamed instruction capacity's log2 (R8S, revision 8's
    # round 2): log2 SEQ_STREAM_D on a tile that streams, past its store,
    # and zero on one that does not, where CAPS[23:20] is the capacity.
    # [15] and [31:21] are reserved.
    cap, store = krnl_param("SEQ_STREAM_D"), krnl_param("SEQ_IMEM_D")
    assert cap == 1 << (cap.bit_length() - 1) and store <= cap <= 1 << 30, (
        f"SEQ_STREAM_D={cap}: a power of two from the store ({store}) to "
        f"2^30")
    stream_log2 = cap.bit_length() - 1 if cap > store else 0
    return ((stream_log2 << 16) | (fctl << 14) | (lflags << 13) |
            (step << 12) | (aug << 11) |
            (lmask << 10) | (indexed << 9) | (seg << 8) | (scalar << 7) |
            (1 << 6) | (1 << 5) | (1 << 4) | (d.bit_length() - 1))


def _localparam_bit(path, name):
    """The value of `localparam bit <name> = 1'bX;` in a file.

    Its own parser because _localparam requires `int`, and a feature flag
    has to stay `bit`: it is concatenated into CAPS2, where an `int` would
    be thirty-two bits wide and silently shift every field above it.
    """
    import re
    src = path.read_text(encoding="utf-8")
    m = re.search(r"^\s*localparam\s+bit\s+%s\s*=\s*1'b([01])\s*;" % name,
                  src, re.MULTILINE)
    assert m, f"{path.name} has no `localparam bit {name}`"
    return int(m.group(1))


def check_caps2(caps2):
    want = caps2_expected()
    assert caps2 == want, (
        f"CAPS2 is {caps2:#010x}, want {want:#010x} - [3:0] log2 of the "
        f"scratch slots a lane, [4] a scratch exists, [5] the per-run "
        f"block exists, [6] SCRATCH_STRICT, [7] SCALAR operands, "
        f"[8] REDUCE_SEG, [9] INDEXED, [10] LANE_MASK, [11] AUGADD, "
        f"[12] SCRATCH_STEP, [13] LANE_FLAGS, [14] FLAG_CONTROL, "
        f"[20:16] log2 of a streamed instruction capacity, [15] and "
        f"[31:21] reserved zero")


def check_seam_words(caps, caps2, prec_mask):
    """CAPS and CAPS2 against the words the plan computed for a revision-8
    seam tile at this build's capacities (SEAM_WORDS). A configuration the
    table does not have is a failure, not a skip: add its words from the
    plan's arithmetic rather than letting the check pass by absence."""
    key = (krnl_param("SEQ_MAXD"), krnl_param("SEQ_IMEM_D"),
           krnl_param("SEQ_SCRATCH_D"), krnl_param("SEQ_STREAM_D"),
           krnl_param_bit("EN_AUGADD"))
    assert key in SEAM_WORDS, (
        f"no computed words for (SEQ_MAXD, SEQ_IMEM_D, SEQ_SCRATCH_D, "
        f"SEQ_STREAM_D, EN_AUGADD) = {key}: add them to SEAM_WORDS from "
        f"the plan's arithmetic")
    want_caps, want_caps2 = SEAM_WORDS[key]
    want_caps |= prec_mask
    assert caps == want_caps, (
        f"CAPS is {caps:#010x}; a revision-8 seam tile at {key} reads "
        f"{want_caps:#010x} (docs/ROADMAP.md, revision 8: CAPS unchanged, "
        f"CAPS[23:20] min(15, log2 of the capacity))")
    assert caps2 == want_caps2, (
        f"CAPS2 is {caps2:#010x}; a revision-8 seam tile at {key} reads "
        f"{want_caps2:#010x} - every revision-8 bit ([14:11], [20:16]) "
        f"zero until its item is built")


def seq_caps_expected():
    """(feat, log2 maxd, log2 imem, log2 kreg) as the RTL declares them."""
    # The two a build sets since revision 7, as this build set them; the
    # constant bank stays a localparam (a deeper one is an instruction-
    # format change, not a capacity).
    maxd = krnl_param("SEQ_MAXD")
    # CAPS[23:20] is the instruction CAPACITY's log2, at most 15, since
    # revision 8 (R8S): SEQ_STREAM_D's, which is SEQ_IMEM_D's - the store's
    # - on a tile that does not stream.
    imem = krnl_param("SEQ_STREAM_D")
    kmem = _localparam(RTL / "cft_krnl.sv", "SEQ_KMEM_D")
    kidx = _localparam(RTL / "cft_krnl.sv", "SEQ_KIDX_W")
    # cft_seq owns the constant bank's depth as its own localparam, and
    # cft_krnl publishes the log2 of it. Two files, one number: check
    # they still agree, because CAPS would otherwise advertise a bank
    # size the decoder does not have.
    kreg = _localparam(RTL / "cft_seq.sv", "KREG")
    assert (1 << kidx) == kreg, (
        f"cft_krnl's SEQ_KIDX_W={kidx} means {1 << kidx} addressable "
        f"constants and cft_seq's KREG is {kreg}")
    # A four-bit field can only carry an exponent, so a capacity that is
    # not a power of two would be published rounded UP ($clog2 is the
    # ceiling; this said DOWN until revision 7) - a cap a host would size
    # a program against and be refused by - and one past 2^15 would wrap
    # its field.
    for name, v in (("SEQ_MAXD", maxd), ("SEQ_KMEM_D", kmem)):
        assert v == 1 << (v.bit_length() - 1) and v <= 1 << 15, (
            f"{name}={v} is not a power of two in 1..2^15; CAPS publishes "
            f"its log2 in four bits")
    feat = _port_literal(RTL / "cft_krnl.sv", "seq_feat")
    return (feat, maxd.bit_length() - 1, min(15, imem.bit_length() - 1),
            kidx)


def check_seq_caps(caps):
    """CAPS[7:4] and CAPS[27:16] against rtl/cft_krnl.sv's parameters."""
    feat, l_maxd, l_imem, l_kreg = seq_caps_expected()
    got = ((caps >> 4) & 0xF, (caps >> 16) & 0xF,
           (caps >> 20) & 0xF, (caps >> 24) & 0xF)
    assert got == (feat, l_maxd, l_imem, l_kreg), (
        "CAPS does not publish the sequencer capacities cft_krnl "
        f"elaborates: feature nibble {got[0]:#x} (want {feat:#x}), "
        f"log2 MAXD {got[1]} (want {l_maxd}), the capacity's log2 {got[2]} "
        f"(want {l_imem}), log2 addressable consts {got[3]} "
        f"(want {l_kreg}) - CAPS is {caps:#010x}")
    ext = _port_literal(RTL / "cft_krnl.sv", "alu_ext")
    assert (caps >> 28) == ext, (
        f"CAPS[31:28] must publish the ALU extensions cft_krnl wires "
        f"({ext:#x}); CAPS is {caps:#010x}")


def check_op_groups(caps):
    """Every implemented opcode group advertised, and nothing else."""
    groups = (caps >> 8) & 0xFF
    missing = [n for b, n in sorted(OP_GROUPS.items()) if not groups & (1 << b)]
    assert not missing, (
        f"CAPS fails to advertise implemented opcode group(s): "
        f"{', '.join(missing)} - op groups are {groups:#010b}")
    claimed = [n for b, n in sorted(OP_GROUPS_NOT_BUILT.items())
               if groups & (1 << b)]
    assert not claimed, (
        f"CAPS advertises group(s) that are not built: {', '.join(claimed)} "
        f"- op groups are {groups:#010b}")


async def write64(axil, addr, val):
    await axil.write_dword(addr, val & 0xFFFFFFFF)
    await axil.write_dword(addr + 4, (val >> 32) & 0xFFFFFFFF)


def gen_stream(fmt, n, rng):
    """Operand stream: a blend of raw random patterns and the directed
    specials, so the engine meets NaN, inf, and subnormals in flight."""
    pool = vectors.interesting_operands(fmt)
    out = []
    for _ in range(n):
        if rng.random() < 0.25:
            out.append(rng.choice(pool))
        else:
            out.append(rng.getrandbits(fmt.width))
    return out


async def run_op(dut, axil, ram, fmt, op, n, seed, bases=None, rnd=RND_RNE,
                 want_rnd=None):
    """One elementwise run at MODE[14:12] = `rnd`, scored against the
    model at `want_rnd` (`rnd` unless given): the attribute codes 5 to 7
    are RNE by MODE's contract, so a case driving them names RNE here."""
    ba, bb, bc, bd = bases if bases else (A_BASE, B_BASE, C_BASE, D_BASE)
    ebytes = fmt.width // 8
    rng = random.Random(seed)
    va = gen_stream(fmt, n, rng)
    vb = gen_stream(fmt, n, rng)
    vc = gen_stream(fmt, n, rng)

    m_rnd = rnd if want_rnd is None else want_rnd
    exp = [compute(fmt, op, va[i], vb[i], vc[i], m_rnd) for i in range(n)]
    exp_d = [e[0] for e in exp]
    exp_f = 0
    for e in exp:
        exp_f |= e[1]

    ram.write(ba, b"".join(v.to_bytes(ebytes, "little") for v in va))
    ram.write(bb, b"".join(v.to_bytes(ebytes, "little") for v in vb))
    ram.write(bc, b"".join(v.to_bytes(ebytes, "little") for v in vc))
    ram.write(bd, b"\xAA" * (n * ebytes))  # prove full overwrite

    await axil.write_dword(MODE, op | (PREC_CODE[fmt.name] << 8) | (rnd << 12))
    await write64(axil, NREG, n)
    await write64(axil, APTR, ba)
    await write64(axil, BPTR, bb)
    await write64(axil, CPTR, bc)
    await write64(axil, DPTR, bd)
    await axil.write_dword(CTRL, 1)

    for _ in range(5000):
        await ClockCycles(dut.ap_clk, 10)
        status = await axil.read_dword(CTRL)
        if status & 0x2:  # ap_done (clear-on-read)
            break
    else:
        raise AssertionError(f"{fmt.name} {OP_NAMES[op]}: kernel never finished")

    got = ram.read(bd, n * ebytes)
    bad = 0
    for i in range(n):
        g = int.from_bytes(got[i * ebytes:(i + 1) * ebytes], "little")
        if g != exp_d[i]:
            bad += 1
            if bad <= 10:
                dut._log.error(
                    f"{fmt.name} {OP_NAMES[op]} [{i}]: a={va[i]:#x} "
                    f"b={vb[i]:#x} c={vc[i]:#x} got={g:#x} want={exp_d[i]:#x}")
    assert bad == 0, f"{fmt.name} {OP_NAMES[op]}: {bad}/{n} elements differ"

    got_f = await axil.read_dword(FLAGS)
    assert got_f == exp_f, \
        f"{fmt.name} {OP_NAMES[op]}: FLAGS {got_f:#07b} want {exp_f:#07b}"
    # the memory system vouched for every beat: a clean STATUS is what
    # makes the bit-exactness above mean anything
    got_err = await axil.read_dword(STATUS)
    assert got_err == 0, \
        f"{fmt.name} {OP_NAMES[op]}: STATUS {got_err:#05b}, bus faults during the run"
    dut._log.info(f"{fmt.name} {OP_NAMES[op]} "
                  f"{RND_NAMES.get(rnd, f'attribute code {rnd}')} n={n}: "
                  f"bit-exact, flags {got_f:#07b}")


async def run_refused_mode_bit(dut, axil, ram, mode_bit, name):
    """An elementwise run the CSR must throw back for one MODE bit this
    build does not honour: STATUS[3] alone, done still asserted, nothing
    written to D, and the previous run's FLAGS left alone - a refusal is
    not a run (rtl/cft_csr.sv's guard, cfg_mode_bad). The run is an
    ordinary fp FMA on the build's narrowest rung, so the bit is the only
    thing wrong with it."""
    flags_before = await axil.read_dword(FLAGS)
    ram.write(D_BASE, b"\xC3" * 64)
    await axil.write_dword(MODE, OP_FMA | (PREC_CODE[BASE.name] << 8)
                           | mode_bit)
    await write64(axil, NREG, EPB)
    await write64(axil, APTR, A_BASE)
    await write64(axil, BPTR, B_BASE)
    await write64(axil, CPTR, C_BASE)
    await write64(axil, DPTR, D_BASE)
    await axil.write_dword(CTRL, 1)
    for _ in range(200):
        await ClockCycles(dut.ap_clk, 5)
        if (await axil.read_dword(CTRL)) & 0x2:
            break
    else:
        raise AssertionError(f"{name}: a refused run must still complete")
    got = await axil.read_dword(STATUS)
    assert got == 0x8, (
        f"{name}: STATUS {got:#05b}, want the refusal bit alone - a MODE "
        f"bit this build does not honour is REFUSED, never ignored")
    assert ram.read(D_BASE, 64) == b"\xC3" * 64, f"{name}: a refused run wrote D"
    assert (await axil.read_dword(FLAGS)) == flags_before, (
        f"{name}: a refusal moved FLAGS, and a refusal is not a run")
    dut._log.info(f"{name}: refused with STATUS[3], D and FLAGS untouched")


# MODE[18:16] - a set bit makes that operand STRIDE-0: one value read once
# and applied to the whole run (CAPS2[7]).
async def run_scalar(dut, axil, ram, fmt, op, n, seed, which, rnd=RND_RNE):
    """One operand stride-0, scored against an array of copies.

    `which` is 0, 1 or 2 for a, b or c. The scalar's buffer holds ONE
    element and everything after it is POISON, which is what makes this
    case unable to pass for the wrong reason: a tile that ignored
    MODE[18:16] would stream n elements, read the poison, and differ.

    That is the empirical form of the argument CAPS2[7] exists for. The
    host-side control of the same shape does not merely differ - it
    SEGFAULTS, reading n elements out of a one-element allocation.
    """
    ebytes = fmt.width // 8
    rng = random.Random(seed)
    vs = [gen_stream(fmt, n, rng), gen_stream(fmt, n, rng),
          gen_stream(fmt, n, rng)]
    scal = vs[which][0]
    vs[which] = [scal] * n          # what the contract says it computes

    exp = [compute(fmt, op, vs[0][i], vs[1][i], vs[2][i], rnd)
           for i in range(n)]
    exp_d = [e[0] for e in exp]
    exp_f = 0
    for e in exp:
        exp_f |= e[1]

    bases = (A_BASE, B_BASE, C_BASE)
    for r in range(3):
        if r == which:
            ram.write(bases[r], scal.to_bytes(ebytes, "little"))
            ram.write(bases[r] + ebytes, b"\x5A" * ((n - 1) * ebytes))
        else:
            ram.write(bases[r],
                      b"".join(v.to_bytes(ebytes, "little") for v in vs[r]))
    ram.write(D_BASE, b"\xAA" * (n * ebytes))

    await axil.write_dword(MODE, op | (PREC_CODE[fmt.name] << 8) |
                                 (rnd << 12) | (1 << (16 + which)))
    await write64(axil, NREG, n)
    await write64(axil, APTR, A_BASE)
    await write64(axil, BPTR, B_BASE)
    await write64(axil, CPTR, C_BASE)
    await write64(axil, DPTR, D_BASE)
    await axil.write_dword(CTRL, 1)

    for _ in range(5000):
        await ClockCycles(dut.ap_clk, 10)
        if (await axil.read_dword(CTRL)) & 0x2:
            break
    else:
        raise AssertionError(f"{fmt.name} scalar[{which}]: never finished")

    got = ram.read(D_BASE, n * ebytes)
    bad = 0
    for i in range(n):
        g = int.from_bytes(got[i * ebytes:(i + 1) * ebytes], "little")
        if g != exp_d[i]:
            bad += 1
            if bad <= 6:
                dut._log.error(
                    f"{fmt.name} scalar[{which}] [{i}]: got={g:#x} "
                    f"want={exp_d[i]:#x} (scalar={scal:#x})")
    assert bad == 0, (
        f"{fmt.name} scalar[{which}]: {bad}/{n} differ - a tile that "
        f"streamed n elements would have read the 0x5A poison after the "
        f"single element, so a high count is that failure")

    got_f = await axil.read_dword(FLAGS)
    assert got_f == exp_f,         f"{fmt.name} scalar[{which}]: FLAGS {got_f:#07b} want {exp_f:#07b}"
    got_err = await axil.read_dword(STATUS)
    assert got_err == 0, f"{fmt.name} scalar[{which}]: STATUS {got_err:#05b}"
    dut._log.info(f"{fmt.name} scalar[{which}] n={n}: bit-exact against an "
                  f"array of copies, flags {got_f:#07b}")


@cocotb.test()
async def krnl_end_to_end(dut):
    cocotb.start_soon(Clock(dut.ap_clk, 4, units="ns").start())
    axil = AxiLiteMaster(AxiLiteBus.from_prefix(dut, "s_axi_control"),
                         dut.ap_clk, dut.ap_rst_n, reset_active_level=False)
    # Four masters, ONE memory.
    #
    # The engine has a dedicated port per stream now, but a, b, c and d
    # are regions of a single address space - the same HBM - so the four
    # attachments must share a backing store. Give them separate ones
    # and the test still passes for the wrong reason: each reader sees
    # the operands the test wrote into its own private copy, and a
    # genuine address-decode bug in the engine goes unnoticed because
    # every stream reads from a memory where only its own data exists.
    ram_a = AxiRamRead(AxiReadBus.from_prefix(dut, "m_axi_a"),
                       dut.ap_clk, dut.ap_rst_n, reset_active_level=False,
                       size=2 ** 20)
    ram_b = AxiRamRead(AxiReadBus.from_prefix(dut, "m_axi_b"),
                       dut.ap_clk, dut.ap_rst_n, reset_active_level=False,
                       size=2 ** 20, mem=ram_a.mem)
    ram_c = AxiRamRead(AxiReadBus.from_prefix(dut, "m_axi_c"),
                       dut.ap_clk, dut.ap_rst_n, reset_active_level=False,
                       size=2 ** 20, mem=ram_a.mem)
    ram_d = AxiRamWrite(AxiWriteBus.from_prefix(dut, "m_axi_d"),
                        dut.ap_clk, dut.ap_rst_n, reset_active_level=False,
                        size=2 ** 20, mem=ram_a.mem)
    # Staging and readback both go through the shared store; which
    # attachment is used to reach it does not matter, and naming one
    # `ram` keeps run_op unchanged.
    ram = ram_a
    assert ram_b.mem is ram_a.mem and ram_c.mem is ram_a.mem \
        and ram_d.mem is ram_a.mem, \
        "the four masters must address one memory or this bench proves " \
        "nothing about address decode"

    # Optional memory round trip (tb/Makefile's RD_LATENCY / WR_LATENCY;
    # zero installs nothing). This bench scores every result against the
    # golden model, so running it at the card's latency is the statement
    # that a deeper read-ahead changed the SCHEDULE and not the bits -
    # which is the only property that matters here.
    rd_lat, wr_lat = busfx.env_latency()
    if busfx.latency(ram_a, ram_b, ram_c, ram_d, clk=dut.ap_clk,
                     read=rd_lat, write=wr_lat) != (0, 0):
        dut._log.info(f"memory model: read latency {rd_lat} cycles, "
                      f"write-response latency {wr_lat} cycles")

    dut.ap_rst_n.value = 0
    await ClockCycles(dut.ap_clk, 8)
    dut.ap_rst_n.value = 1
    await ClockCycles(dut.ap_clk, 4)

    assert await axil.read_dword(MAGIC) == 0x43465430
    # 0x700 -> 0x800 at revision 3: the map GREW again, by CAPS2 at
    # 0x6C and the two scratch pointers at 0x70 and 0x78; 0x800 ->
    # 0x900 on 2026-09-14, by SEG/NRES at 0x80/0x84 (ask 7); 0xA00 on
    # 2026-09-15 by the five pointers at 0x88..0xA8 (docs/ROUND2.md);
    # 0xB00 on 2026-10-02 by LFLAGS_PTR at 0xB0, revision 8's seam.
    assert await axil.read_dword(VERSION) == VERSION_SEAM
    caps = await axil.read_dword(CAPS)
    # CAPS[3:0] against what this bench was BUILT with, not against 0xF: a
    # trimmed build (make krnlf128) must advertise exactly the rungs it
    # kept and nothing more, and a full build all four.
    built = os.environ.get("CFT_GENERICS", "") or "(nothing: the full tile)"
    assert (caps & 0xF) == PREC_MASK, (
        f"CAPS[3:0] is {caps & 0xF:#x}; this bench was built with "
        f"CFT_GENERICS={built!r}, which is {PREC_MASK:#x}")
    absent = [f for f in (FP32, FP64, FP128, FP256) if not carried(f)]
    dut._log.info("rungs carried: "
                  + " ".join(f.name for f in (FP32, FP64, FP128, FP256)
                             if carried(f))
                  + (("; absent, to be refused: "
                      + " ".join(f.name for f in absent)) if absent
                     else "; all four, so absent-rung refusals are NOT TESTED"))
    check_op_groups(caps)
    check_seq_caps(caps)
    caps2 = await axil.read_dword(CAPS2)
    check_caps2(caps2)
    # ...and both words against the plan's own numbers for a seam tile.
    check_seam_words(caps, caps2, PREC_MASK)
    status = await axil.read_dword(CTRL)
    assert status & 0x4, "kernel must come up idle"

    await run_op(dut, axil, ram, BASE, OP_FMA, 6 * EPB, seed=101)
    await run_op(dut, axil, ram, BASE, OP_ADD, 4 * EPB, seed=102)
    await run_op(dut, axil, ram, BASE, OP_SUB, 4 * EPB, seed=103)
    await run_op(dut, axil, ram, BASE, OP_MUL, 4 * EPB, seed=104)
    if carried(FP256):
        await run_op(dut, axil, ram, FP256, OP_FMA, 6, seed=105)
    if carried(FP256):
        await run_op(dut, axil, ram, FP256, OP_MUL, 4, seed=106)
    await run_op(dut, axil, ram, BASE, OP_FMA, 2 * EPB, seed=107)  # single-beat run
    await run_op(dut, axil, ram, FP64, OP_FMA, 24, seed=108)
    await run_op(dut, axil, ram, FP64, OP_SUB, 16, seed=109)
    await run_op(dut, axil, ram, FP128, OP_FMA, 8, seed=110)
    await run_op(dut, axil, ram, FP128, OP_ADD, 6, seed=111)
    await run_op(dut, axil, ram, FP64, OP_MUL, 4, seed=112)  # single-beat run

    # MODE[18:16], the stride-0 operands (CAPS2[7], 2026-09-12).
    #
    # n = 37 is odd and not a beat multiple at any rung, so the tail path
    # runs. Every format, because the broadcast is PER LANE and the lane
    # count differs at each rung - 8 at fp32, 1 at fp256, where the beat
    # IS the element and the replication is the identity. fp256 is the
    # rung a per-lane loop gets wrong.
    #
    # Skipped rather than failed on a build that does not carry it, the
    # way an absent precision is: FEAT_SCALAR is a localparam and a
    # trimmed tile may clear it.
    # n MUST BE A WHOLE NUMBER OF BEATS here, and that is the contract
    # rather than a convenience. host/src/slice.h:22 - "each slice covers
    # a whole number of 256-bit beats, because the engine's beat count is
    # n >> (LANE_SH - prec) and a partial beat would be TRUNCATED AWAY
    # rather than rounded up". cft_plan_slices rounds up and hands the
    # tile ; the library copies back . So a partial beat is
    # something no cft_run can produce, and driving one at the CSR - as
    # this bench does - is outside the contract.
    #
    # Written down because I got it wrong: n=37 at fp32 is 4 beats and 5
    # lanes, the engine correctly dropped the partial fifth, and it read
    # as an engine defect for half an hour. Every other case in this file
    # uses an exact multiple for the same reason, which looked like a
    # coverage gap and is the contract.
    if int(await axil.read_dword(CAPS2)) & (1 << 7):
        for which in (0, 1, 2):
            await run_scalar(dut, axil, ram, BASE, OP_FMA, 5 * EPB,
                             seed=0x5CA1 + which, which=which)
        await run_scalar(dut, axil, ram, FP64, OP_FMA, 36, seed=0x5CB0, which=1)
        await run_scalar(dut, axil, ram, FP128, OP_FMA, 38, seed=0x5CB1, which=1)
        if carried(FP256):
            await run_scalar(dut, axil, ram, FP256, OP_FMA, 37, seed=0x5CB2, which=1)
        # The control: the same shape with the flag CLEAR and full arrays
        # must still be right, so a scalar path that quietly streamed
        # could not pass both halves - the poison is what separates them.
        await run_op(dut, axil, ram, BASE, OP_FMA, 5 * EPB, seed=0x5CA0)
        dut._log.info("stride-0 operands: every format, and the "
                      "flag-clear control still streams full arrays")
    else:
        dut._log.info("CAPS2[7] clear: this build carries no stride-0 operand")

    # stream-engine stressors: multi-burst runs, a ragged tail, and
    # buffers placed so bursts must split at 4KB AXI boundaries
    await run_op(dut, axil, ram, BASE, OP_FMA, 37 * EPB, seed=113)  # 37 beats
    await run_op(dut, axil, ram, FP64, OP_ADD, 128, seed=114)  # 32 beats
    if carried(FP256):
        await run_op(dut, axil, ram, FP256, OP_FMA, 40, seed=115)  # 3 bursts
    await run_op(dut, axil, ram, BASE, OP_MUL, 8 * EPB, seed=116,
                 bases=(0x00FE0, 0x41FC0, 0x82FA0, 0xC3F20))

    # every rounding attribute, end to end through the CSR field
    for rnd in (RND_RTZ, RND_RDN, RND_RUP, RND_RMM):
        await run_op(dut, axil, ram, BASE, OP_FMA, 4 * EPB, seed=120 + rnd, rnd=rnd)
    await run_op(dut, axil, ram, FP64, OP_FMA, 16, seed=130, rnd=RND_RDN)
    await run_op(dut, axil, ram, FP128, OP_MUL, 6, seed=131, rnd=RND_RUP)
    if carried(FP256):
        await run_op(dut, axil, ram, FP256, OP_FMA, 4, seed=132, rnd=RND_RTZ)

    # back-to-back runs that differ only in attribute must differ in
    # results the way the contract says, and the CSR must not leak the
    # previous run's mode into the next one
    await run_op(dut, axil, ram, BASE, OP_ADD, 4 * EPB, seed=140, rnd=RND_RUP)
    await run_op(dut, axil, ram, BASE, OP_ADD, 4 * EPB, seed=140, rnd=RND_RDN)
    await run_op(dut, axil, ram, BASE, OP_ADD, 4 * EPB, seed=140, rnd=RND_RNE)

    # the non-arithmetic opcodes, end to end through the MODE field.
    # These bypass the datapath, so the run also proves the engine's
    # collection path delivers a bypassed result at the same latency as
    # a computed one - the two share a delay line.
    for i, op in enumerate(SIMPLE_OPS):
        await run_op(dut, axil, ram, BASE, op, 4 * EPB, seed=200 + i)
    await run_op(dut, axil, ram, FP64, OP_MINNUM, 16, seed=210)
    await run_op(dut, axil, ram, FP128, OP_COPYSIGN, 8, seed=211)
    if carried(FP256):
        await run_op(dut, axil, ram, FP256, OP_MAX, 4, seed=212)
    await run_op(dut, axil, ram, FP64, OP_CMPLT, 16, seed=213)
    if carried(FP256):
        await run_op(dut, axil, ram, FP256, OP_SELECT, 4, seed=214)
    # select is the only non-arithmetic opcode that reads c, so it is
    # the only end-to-end check that each bank's c slice is wired to
    # that bank's own operand. Run it on every rung, not just two.
    await run_op(dut, axil, ram, FP64, OP_SELECT, 16, seed=215)
    await run_op(dut, axil, ram, FP128, OP_SELECT, 8, seed=216)

    # The divide/sqrt seeds ride the same bypass sideband but from a
    # different module (cft_seedop), so the simpleops runs above vouch
    # for none of their wiring. One run per rung. Both opcodes are
    # quiet by specification, so FLAGS must come back zero even though
    # gen_stream salts the operands with specials.
    await run_op(dut, axil, ram, BASE, OP_RECIP_SEED, 4 * EPB, seed=217)
    await run_op(dut, axil, ram, FP64, OP_RSQRT_SEED, 16, seed=218)
    await run_op(dut, axil, ram, FP128, OP_RSQRT_SEED, 8, seed=219)
    if carried(FP256):
        await run_op(dut, axil, ram, FP256, OP_RECIP_SEED, 4, seed=220)

    # A MODE precision code outside 0-3 is refused on EVERY build, the
    # full tile included: STATUS[3], done still asserted, memory
    # untouched, and the next accepted run clears the sticky (run_op's
    # own STATUS==0 assert proves that part). Real precisions a trimmed
    # build lacks are refused the same way and are held to it below -
    # since 2026-09-14 for the full-beat trims (`make krnlf128`,
    # `make krnlf64f128`), and in test_krnl_quarter for the BEAT_BITS=64
    # one.
    ram.write(D_BASE, b"\xAA" * 64)
    await axil.write_dword(MODE, 0 | (9 << 8))
    await write64(axil, NREG, 4)
    await write64(axil, APTR, A_BASE)
    await write64(axil, BPTR, B_BASE)
    await write64(axil, CPTR, C_BASE)
    await write64(axil, DPTR, D_BASE)
    await axil.write_dword(CTRL, 1)
    refused_done = False
    for _ in range(200):
        await ClockCycles(dut.ap_clk, 5)
        if (await axil.read_dword(CTRL)) & 0x2:
            refused_done = True
            break
    assert refused_done, "a refused run must still complete"
    assert (await axil.read_dword(STATUS)) == 0x8, "want the refusal bit"
    assert ram.read(D_BASE, 64) == b"\xAA" * 64, "a refused run wrote"
    await run_op(dut, axil, ram, BASE, OP_ADD, EPB, seed=221)

    # ---- revision 8's MODE[24], refused where CAPS2[13] is clear ------
    #
    # MODE[24] asks for R23's per-lane flag block (docs/SEQUENCER.md),
    # honoured only on a build whose CAPS2[13] is set - and revision 8's
    # seam sets it on none, so the CSR must REFUSE the bit as it refused
    # it while it was reserved: STATUS[3] alone, done still asserted, D
    # untouched, FLAGS left alone. MODE[25] is the bottom of what is left
    # of the reserved range and is refused on every build. Each refusal
    # is followed by an accepted run, whose own STATUS == 0 assert proves
    # the sticky cleared.
    if caps2 & (1 << 13):
        dut._log.info("CAPS2[13] set: MODE[24] is honoured on this build, "
                      "and its block is test_krnl_seq's to hold")
    else:
        await run_refused_mode_bit(dut, axil, ram, 1 << 24,
                                   "MODE[24], R23's lane-flags block, on a "
                                   "build whose CAPS2[13] is clear")
        await run_op(dut, axil, ram, BASE, OP_ADD, EPB, seed=223)
    await run_refused_mode_bit(dut, axil, ram, 1 << 25,
                               "MODE[25], reserved on every build")
    await run_op(dut, axil, ram, BASE, OP_ADD, EPB, seed=224)

    # ---- a real rung this build LACKS --------------------------------
    #
    # The kernel cft-rebound shipped is a full-beat tile with binary256
    # left out - EN_FP256=0 at BEAT_BITS=256 - and until 2026-09-14 no
    # bench had ever built that shape: this file issued fp256 cases
    # unconditionally, and the one trimmed bench, test_krnl_quarter, is
    # trimmed the other way. `make krnlf128` builds it, and this is the
    # proof cft-rebound said "would have proved this image's RTL before a
    # link did" (its docs/BITSTREAM.md, ask 4): CAPS[3:0] exactly the
    # kept rungs (asserted above), the kept rungs bit-exact (every case
    # above), and the absent one refused with STATUS[3] - done still
    # asserted, nothing written, and FLAGS untouched, because a refusal
    # is not a run (rtl/cft_krnl.sv: "FLAGS are left alone"). The
    # out-of-range block above does not check FLAGS; this one does.
    # `make krnlf64f128` is the same proof for the tile without fp32 -
    # the one cft-rebound wants - where BASE is fp64 and this loop
    # refuses precisions 0 and 3. On a full build the loop is empty and
    # the banner above says so.
    for fmt in absent:
        flags_before = await axil.read_dword(FLAGS)
        ram.write(D_BASE, b"\xA5" * 64)
        await axil.write_dword(MODE, OP_FMA | (PREC_CODE[fmt.name] << 8))
        await write64(axil, NREG, 4)
        await write64(axil, APTR, A_BASE)
        await write64(axil, BPTR, B_BASE)
        await write64(axil, CPTR, C_BASE)
        await write64(axil, DPTR, D_BASE)
        await axil.write_dword(CTRL, 1)
        refused_done = False
        for _ in range(200):
            await ClockCycles(dut.ap_clk, 5)
            if (await axil.read_dword(CTRL)) & 0x2:
                refused_done = True
                break
        assert refused_done, f"{fmt.name}: a refused run must still complete"
        got = await axil.read_dword(STATUS)
        assert got == 0x8, \
            f"{fmt.name} on a build without it: STATUS {got:#05b}, want the " \
            f"refusal bit alone"
        assert ram.read(D_BASE, 64) == b"\xA5" * 64, \
            f"{fmt.name}: a refused run wrote to D"
        assert (await axil.read_dword(FLAGS)) == flags_before, \
            f"{fmt.name}: a refusal moved FLAGS, and a refusal is not a run"
        dut._log.info(f"{fmt.name}: refused with STATUS[3], D and FLAGS untouched")
        await run_op(dut, axil, ram, BASE, OP_ADD, EPB, seed=222)

    # ---- across a 4KB page -------------------------------------------
    #
    # AXI4 forbids a burst from crossing a 4KB boundary, so both reader
    # and writer shorten a burst that would. Nothing here had ever
    # reached a boundary: every base is page-aligned and the largest
    # run above is 48 elements, which at 32 bytes per beat is 192 bytes
    # into a 4096-byte page. The shortening logic on both paths was
    # therefore carried by inspection alone.
    #
    # 1104 fp32 is 138 beats and 600 fp64 is 150, so each crosses one
    # boundary on all four masters. Both are whole numbers of beats,
    # which elementwise requires - the host pads and the kernel relies
    # on it. The stock cocotbext-axi slave asserts if a burst it
    # receives crosses a page, so a DUT that forgot to shorten fails
    # here rather than quietly reading the wrong memory.
    await run_op(dut, axil, ram, BASE, OP_FMA, 138 * EPB, seed=250)
    await run_op(dut, axil, ram, FP64, OP_ADD, 600, seed=251)

    # ---- more bursts than the RLAST length queue holds ----------------
    #
    # With AR_DEPTH bursts in flight, each reader keeps a queue of the
    # lengths it is still expecting an RLAST for, and that queue wraps
    # at AR_DEPTH. Nothing above reached it: 150 beats is nine 16-beat
    # bursts against a queue of sixteen, so the write and read pointers
    # had never crossed a wrap in this file.
    #
    # 4,800 fp32 elements is 600 beats, 38 bursts a stream - two full
    # laps and change. It also crosses four 4KB pages rather than one,
    # and drives roughly four times the longest stream this bench had.
    # Scored against the model like every other run, so the failure
    # mode is wrong bits rather than a hang.
    #
    # It does NOT saturate the operand FIFOs, and it is worth saying
    # so: elementwise consumes a beat about as fast as a master
    # delivers one, so 600 beats leaves the FIFO a tenth full and the
    # RESERVATION never binds. The bench that puts the reservation
    # under load is the long reduction in test_krnl_reduce.py, for the
    # reason its comment gives.
    await run_op(dut, axil, ram, BASE, OP_FMA, 600 * EPB, seed=252)

    # ---- and now with a slave that is not cooperative ----------------
    #
    # Everything above ran against a memory that answers in zero cycles
    # and never withholds a handshake. That is the schedule this design
    # is LEAST likely to be wrong on, and it is the only one the suite
    # had ever seen.
    #
    # The assertion is not "it still works". run_op scores every result
    # against the golden model, and the model has no notion of a cycle
    # - so a run that survives a hostile schedule and still matches is
    # a statement that the schedule did not reach the answer. That is
    # the product claim, tested against the most plausible thing that
    # could quietly break it.
    #
    # Three duties rather than one: light stalling changes arrival
    # order without emptying anything, heavy stalling drains the FIFOs
    # and exercises the refill path, and they fail differently.
    for i, duty in enumerate((0.15, 0.45, 0.75)):
        busfx.stall(ram_a, ram_b, ram_c, ram_d, seed=9000 + i, duty=duty)
        dut._log.info(f"backpressure: duty {duty} on every channel")
        await run_op(dut, axil, ram, BASE, OP_FMA, 5 * EPB, seed=300 + i)
        await run_op(dut, axil, ram, FP64, OP_ADD, 20, seed=310 + i)
        if carried(FP256):
            await run_op(dut, axil, ram, FP256, OP_FMA, 5, seed=320 + i)
        # 136 fp32 is 17 beats: one full 16-beat burst plus a single
        # ragged one. That is the awkward size for an ELEMENTWISE run -
        # a whole number of beats that is not a whole number of bursts.
        #
        # Not 37. n must be a whole number of beats for elementwise;
        # the host pads and the kernel relies on it, so 37 leaves the
        # last 5 elements untouched and the bench reports 5 of 37
        # differing. Which it duly did on the first backpressure run -
        # a fault in the test, caught by the test.
        await run_op(dut, axil, ram, BASE, OP_MUL, 17 * EPB, seed=330 + i)
    busfx.unstall(ram_a, ram_b, ram_c, ram_d)


# ---- raw AXI4-Lite corner cases --------------------------------------
#
@cocotb.test()
async def krnl_attribute_codes_5_to_7(dut):
    """MODE[14:12] = 5, 6 and 7 through an elementwise run are RNE, as
    MODE's contract says (rtl/cft_csr.sv, docs/ARCHITECTURE.md) - at every
    rung this build carries, on ADD, the shape R21's augadd and augerr
    ride the array in, and on FMA. Since R21 the pipe's attribute line
    carries two internal codes, 5 and 6, written only from the sequencer's
    aug_mode sideband, and an outside 5 to 7 must still reach RNE and
    never R21's mode (docs/ROADMAP.md, part 4; verifier-VRB's note that no
    kernel case held it). No bench drove these codes through the kernel
    before; tb/fpfma_common.py holds them on the bare pipes."""
    cocotb.start_soon(Clock(dut.ap_clk, 4, units="ns").start())
    axil = AxiLiteMaster(AxiLiteBus.from_prefix(dut, "s_axi_control"),
                         dut.ap_clk, dut.ap_rst_n, reset_active_level=False)
    ram_a = AxiRamRead(AxiReadBus.from_prefix(dut, "m_axi_a"),
                       dut.ap_clk, dut.ap_rst_n, reset_active_level=False,
                       size=2 ** 20)
    AxiRamRead(AxiReadBus.from_prefix(dut, "m_axi_b"), dut.ap_clk,
               dut.ap_rst_n, reset_active_level=False, size=2 ** 20,
               mem=ram_a.mem)
    AxiRamRead(AxiReadBus.from_prefix(dut, "m_axi_c"), dut.ap_clk,
               dut.ap_rst_n, reset_active_level=False, size=2 ** 20,
               mem=ram_a.mem)
    AxiRamWrite(AxiWriteBus.from_prefix(dut, "m_axi_d"), dut.ap_clk,
                dut.ap_rst_n, reset_active_level=False, size=2 ** 20,
                mem=ram_a.mem)
    dut.ap_rst_n.value = 0
    await ClockCycles(dut.ap_clk, 8)
    dut.ap_rst_n.value = 1
    await ClockCycles(dut.ap_clk, 4)
    seed = 570
    for fmt in (FP32, FP64, FP128, FP256):
        if not carried(fmt):
            continue
        n = 4 * (256 // fmt.width)      # four beats at every rung
        for op in (OP_ADD, OP_FMA):
            for code in (5, 6, 7):
                seed += 1
                await run_op(dut, axil, ram_a, fmt, op, n, seed=seed,
                             rnd=code, want_rnd=RND_RNE)


# cocotbext-axi's AxiLiteMaster issues one write at a time and waits for
# BVALID before starting the next, which is also what XRT's MMIO path
# does. That politeness hides a whole class of CSR bugs: anything the
# slave gets wrong about WHEN it samples the bus is invisible to a
# master that never changes the bus. These tests drive the control
# signals by hand to close that gap.

async def _raw_idle(dut):
    dut.s_axi_control_awvalid.value = 0
    dut.s_axi_control_wvalid.value = 0
    dut.s_axi_control_arvalid.value = 0
    dut.s_axi_control_bready.value = 1
    dut.s_axi_control_rready.value = 1
    dut.s_axi_control_wstrb.value = 0xF


async def _raw_read(dut, addr):
    await RisingEdge(dut.ap_clk)
    dut.s_axi_control_araddr.value = addr
    dut.s_axi_control_arvalid.value = 1
    while True:
        await ReadOnly()
        accepted = int(dut.s_axi_control_arready.value)
        await RisingEdge(dut.ap_clk)
        if accepted:
            break
    dut.s_axi_control_arvalid.value = 0
    while True:
        await ReadOnly()
        if int(dut.s_axi_control_rvalid.value):
            val = int(dut.s_axi_control_rdata.value)
            await RisingEdge(dut.ap_clk)
            return val
        await RisingEdge(dut.ap_clk)


@cocotb.test()
async def csr_latches_the_handshake_beat(dut):
    """A register must keep the WDATA that was on the bus at the W
    handshake, not whatever the master drives afterwards.

    AXI4-Lite requires WDATA to be valid only while WVALID is asserted;
    once the handshake completes the master may drive anything. This
    slave commits the write a cycle later (it waits for both AW and W),
    so reading the live bus at commit time captures the wrong cycle.
    Here the master hands over a value and immediately drives garbage,
    which is exactly what a pipelined master or a FIFO-fed W channel
    does between beats."""
    cocotb.start_soon(Clock(dut.ap_clk, 4, units="ns").start())
    await _raw_idle(dut)
    dut.ap_rst_n.value = 0
    await ClockCycles(dut.ap_clk, 8)
    dut.ap_rst_n.value = 1
    await ClockCycles(dut.ap_clk, 4)

    POISON = 0xDEADBEEF
    for addr, want in ((NREG, 0x12345678), (MODE, 0x00000123),
                       (APTR, 0x0000BEE0)):
        await RisingEdge(dut.ap_clk)
        dut.s_axi_control_awaddr.value = addr
        dut.s_axi_control_awvalid.value = 1
        dut.s_axi_control_wdata.value = want
        dut.s_axi_control_wvalid.value = 1
        await ReadOnly()
        assert int(dut.s_axi_control_awready.value) == 1
        assert int(dut.s_axi_control_wready.value) == 1
        await RisingEdge(dut.ap_clk)      # the handshake edge
        # the master moves on the very next cycle
        dut.s_axi_control_awvalid.value = 0
        dut.s_axi_control_wvalid.value = 0
        dut.s_axi_control_wdata.value = POISON
        dut.s_axi_control_awaddr.value = 0
        await ClockCycles(dut.ap_clk, 6)

        got = await _raw_read(dut, addr)
        assert got == want, (
            f"CSR {addr:#x}: read back {got:#010x}, wrote {want:#010x} "
            f"(bus carried {POISON:#010x} the cycle after the handshake)")
    dut._log.info("CSR latches the handshake beat, not the following cycle")


# ---- hw/kernel.xml IS the CSR map ------------------------------------
#
# kernel.xml is what a bitstream is packaged with, and XRT writes each
# argument's value at the offset the xml gives it. An argument at an
# offset the CSR does not decode is a host write into a decode default -
# a pointer the tile never sees - and one at another register's offset
# is worse. No bench read the xml until revision 8's seam, whose plan
# names this as a plant: "argument 17 at an offset LFLAGS_PTR is not".

@cocotb.test()
async def kernel_xml_is_the_csr_map(dut):
    """hw/kernel.xml's arguments are exactly CSR_ARGS - ids 0, 1, 2...
    in order, each at the table's offset and size, revision 8's argument
    17 (lflags) a written pointer on m_axi_d - and, through the bus, a
    distinct value written at each argument's XML offset reads back from
    the table's register, so the RTL's decode is the third party to the
    agreement rather than an assumption."""
    import xml.etree.ElementTree as ET
    cocotb.start_soon(Clock(dut.ap_clk, 4, units="ns").start())
    axil = AxiLiteMaster(AxiLiteBus.from_prefix(dut, "s_axi_control"),
                         dut.ap_clk, dut.ap_rst_n, reset_active_level=False)
    dut.ap_rst_n.value = 0
    await ClockCycles(dut.ap_clk, 8)
    dut.ap_rst_n.value = 1
    await ClockCycles(dut.ap_clk, 4)

    xml_path = Path(__file__).resolve().parents[1] / "hw" / "kernel.xml"
    args = [{"name": a.get("name"), "id": int(a.get("id")),
             "offset": int(a.get("offset"), 16), "size": int(a.get("size"), 16),
             "port": a.get("port"), "aq": a.get("addressQualifier")}
            for a in ET.parse(xml_path).getroot().iter("arg")]
    ids = [a["id"] for a in args]
    assert ids == list(range(len(args))), (
        f"kernel.xml's argument ids are {ids}: a host binds arguments by "
        f"position, so they run 0, 1, 2... in order with none skipped")
    names = [a["name"] for a in args]
    assert len(set(names)) == len(names) and set(names) == set(CSR_ARGS), (
        f"kernel.xml declares {sorted(set(names) - set(CSR_ARGS))} that the "
        f"CSR map does not, and lacks {sorted(set(CSR_ARGS) - set(names))}")
    for a in args:
        off, size = CSR_ARGS[a["name"]]
        assert (a["offset"], a["size"]) == (off, size), (
            f"kernel.xml puts {a['name']} (argument {a['id']}) at "
            f"{a['offset']:#x}, {a['size']} bytes; rtl/cft_csr.sv decodes it "
            f"at {off:#x}, {size} bytes")
    lf = next(a for a in args if a["name"] == "lflags")
    assert (lf["id"], lf["port"], lf["aq"]) == (17, "m_axi_d", "1"), (
        f"revision 8's LFLAGS_PTR is argument 17, a pointer the tile WRITES "
        f"and so on m_axi_d (docs/ROADMAP.md, R23); kernel.xml has it as "
        f"argument {lf['id']} on {lf['port']}, addressQualifier {lf['aq']}")

    # Through the bus: each argument written at the offset kernel.xml
    # gives it, every one before any is read, then each read back from
    # the register the table names - so an argument the CSR does not
    # decode reads zero, and two that alias read the later one's value.
    want = {}
    for a in args:
        k = a["id"]
        if a["size"] == 4:
            v = 0x5A00_0000 | (k << 16) | (0x0100 + k)
            await axil.write_dword(a["offset"], v)
        else:
            v = (0xA5 << 56) | (k << 40) | (0x00C0_FFEE ^ (k * 0x0101_0101))
            await write64(axil, a["offset"], v)
        want[a["name"]] = v
    for a in args:
        off, size = CSR_ARGS[a["name"]]
        got = await axil.read_dword(off)
        if size == 8:
            got |= (await axil.read_dword(off + 4)) << 32
        assert got == want[a["name"]], (
            f"{a['name']} (argument {a['id']}) written at kernel.xml's "
            f"{a['offset']:#x} reads back {got:#x} from the CSR's {off:#x}, "
            f"not {want[a['name']]:#x}")
    dut._log.info(f"kernel.xml: {len(args)} arguments, ids 0..{len(args) - 1}, "
                  f"each written at its XML offset and read back from the "
                  f"register rtl/cft_csr.sv decodes there; argument 17 is "
                  f"lflags at {lf['offset']:#x} on m_axi_d")
