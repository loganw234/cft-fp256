// Copyright 2026 Logan W.
// SPDX-License-Identifier: Apache-2.0
//
// cft_csr: AXI4-Lite control/status block implementing the Vitis
// ap_ctrl_hs protocol plus the kernel's argument registers. The map
// below IS hw/kernel.xml and docs/ARCHITECTURE.md; the three must
// move together.
//
//   0x00  CTRL    [0] ap_start (host sets; cleared when a run ends)
//                 [1] ap_done  (sticky; cleared on read of CTRL)
//                 [2] ap_idle
//                 [3] ap_ready (mirrors ap_done: 1 run per start)
//   0x04  GIER    storage only - interrupt line not exported in v0
//   0x08  IER     storage only
//   0x0C  ISR     reads 0
//   0x10  MODE    [7:0] op: see docs/ARCHITECTURE.md for the table
//                 [11:8] precision: 0 fp32x8, 1 fp64x4, 2 fp128x2,
//                 3 fp256 - the PREC_CODE ladder; issue only
//                 precisions advertised in CAPS
//                 [14:12] rounding attribute (754 4.3), RISC-V frm
//                 encoding: 0 RNE, 1 RTZ, 2 RDN, 3 RUP, 4 RMM;
//                 5-7 reserved and behave as RNE
//                 [15] SEQUENCER RUN. Set, this run belongs to cft_seq
//                 and the op field is ignored - the program says what
//                 to compute, one instruction at a time. Precision
//                 still applies, and is still refused the same way: a
//                 program is compiled for one format, so a rung the
//                 build lacks is exactly as unrunnable here as there.
//                 The op field is a byte because four bits ran out at
//                 15 opcodes and the integer group needed eight more.
//                 [18:16] SCALAR operands: a set bit makes
//                 that operand STRIDE-0 - the engine reads element 0
//                 for every element, so one value broadcasts over the
//                 run. [16] a, [17] b, [18] c. Advertised in CAPS2[7];
//                 a build without it REFUSES the bit rather than
//                 ignoring it, because ignoring it would read n
//                 elements from a one-element buffer.
//                 [23:19] ABI 0.14 (docs/ROUND2.md): [19] a, [20] b,
//                 [21] c and [22] scratch_in fetched through the index
//                 table at 0x88..0xA0, honoured only under CAPS2[9];
//                 [23] the lane mask at 0xA8, only under CAPS2[10]. A
//                 build whose feature parameter is clear REFUSES its
//                 bit exactly as the reserved range is refused:
//                 [31:24] RESERVED, MUST BE ZERO. A non-zero bit here
//                 is refused at start with STATUS[3], nothing begins
//                 and no memory is touched. This guard did not exist
//                 before the scalar bits, which is exactly why the three bits
//                 above each need a CAPS2 bit: a tile that predates
//                 the guard IGNORES an unknown MODE bit, and an
//                 ignored stride-0 flag is an out-of-bounds read
//                 rather than a wrong answer. The guard cannot teach
//                 a shipped bitstream to refuse; it makes every bit
//                 added after it fail safe.
//   0x18  N       element count, 64-bit (lo at 0x18, hi at 0x1C)
//   0x20  A_PTR   64-bit HBM byte address, 32-byte aligned (one beat;
//                 XRT buffer objects are 4 KB aligned anyway)
//   0x28  B_PTR   64-bit
//   0x30  C_PTR   64-bit
//   0x38  D_PTR   64-bit. On a sequencer run this is the DEPOSIT
//                 buffer: n * max_deposits elements, not n.
//   0x40  FLAGS   RO: sticky IEEE flags of the last run
//                 {inexact,underflow,overflow,divzero,invalid};
//                 cleared by hardware at an ACCEPTED ap_start. A
//                 refused start (STATUS[3]) leaves them untouched:
//                 a refusal is not a run, and scrubbing the previous
//                 run's flags would be quietly rewriting history
//   0x44  MAGIC   RO: 0x43465430 "CFT0"
//   0x48  VERSION RO: 0x00000A00 (v0.10.0). Guards the REGISTER MAP,
//                 not the feature set - features are announced in CAPS.
//                 A host accepts any version whose map it knows.
//   0x4C  CAPS    RO: what this bitstream actually implements.
//                 [3:0]  precision bitmask, bit p = MODE precision p
//                        (full tile 0xF; a trimmed open-core tile
//                        clears the banks it cannot fit)
//                 [15:8] opcode-group bitmask:
//                        [8]  arithmetic  fma/add/sub/mul
//                        [9]  sign        abs/neg/copysign
//                        [10] min/max     the four 9.6 forms
//                        [11] predicate   select/cmplt/cmple/cmpeq
//                        [12] integer     the eight bitwise/integer
//                        [13] reduction   sum (dot via the host)
//                        [14] divide/sqrt reserved
//                        [15] sequencer   MODE[15] runs a program
//                 Bit 15 was labelled "conversion - reserved" and is
//                 now the sequencer's, because conversion will never
//                 want it: the conversions landed as library entry
//                 points (cft_convert and the integer forms, see
//                 docs/COMPATIBILITY.md), composed from opcodes that
//                 already exist rather than issued as a MODE opcode.
//                 A group bit that nothing can ever set is a reserved
//                 bit, and the sequencer is a real thing a host must
//                 be able to ask about before writing PROG_PTR.
//                 Groups rather than 256 individual bits, because
//                 opcodes arrive in groups and a bit per opcode is a
//                 register nobody would keep current. A host asks
//                 before issuing; the alternative is guessing from
//                 VERSION, which stops working the moment one build
//                 ships without a group.
//                 [7:4]   sequencer feature nibble:
//                         [4] wide constant index (kx, 2026-09-07)
//                         [5] REGS32 - five-bit register fields, so a
//                             lane owns 32 registers (2026-09-08)
//                         [6] BANK_PTR - the per-run constant bank
//                             at 0x64/0x68 (2026-09-08)
//                         [7] reserved; assignments are made at the
//                             seq_feat port below and nowhere else
//                 [19:16] log2 of the deposit slots a lane (MAXD)
//                 [23:20] log2 of the instruction capacity (IMEM_D)
//                 [27:24] log2 of the constants an instruction can
//                         ADDRESS (the ka/kb/kc index field's width)
//                 [31:28] ALU extensions beyond the group bits:
//                         [28] IMUL, opcode 30 (2026-09-07); an
//                         opcode that joins a group after bitstreams
//                         shipped with the group's bit set cannot be
//                         announced by that bit. [31:29] reserved
//                 The three capacity fields carry an EXPONENT, not a
//                 count, which is what makes them fit four bits each
//                 and is honest because every one of them is a power
//                 of two by construction (a memory depth and a field
//                 width). They are what a host reads to size a
//                 program BEFORE it builds one: the tile refuses an
//                 image past any of them at its header check with
//                 STATUS[3], and a refusal on card day is a worse
//                 answer than a sizing calculation at startup.
//                 They are values inside a register that already
//                 exists, so they do NOT move VERSION - VERSION
//                 guards the map.
//   0x50  STATUS  RO: sticky faults from the last run, cleared by
//                 hardware at an accepted ap_start. A run that ends
//                 with STATUS non-zero either computed on data the
//                 memory system did not vouch for or never computed at
//                 all; its D buffer must not be trusted either way:
//                 [0] a read response was not OKAY
//                 [1] a write response was not OKAY
//                 [2] a read burst delivered the wrong beat count
//                 [3] the run was REFUSED, for either of two reasons:
//                     MODE selected a precision this build does not
//                     implement (or a code above 3) - the engine never
//                     started and no memory was touched at all; or a
//                     SEQUENCER run's program image failed the
//                     hardware's own header check (bad magic, a format
//                     that is not MODE's, more instructions, constants
//                     or deposit slots than the tile holds, a header
//                     `flags` bit this tile does not implement, or a
//                     non-zero reserved[1] - the last two are checked
//                     from revision 2 and were not before, which is
//                     what makes an image built for a LATER revision
//                     thrown back rather than half-understood). That
//                     second kind may have READ the image before
//                     refusing it, but it wrote nothing and computed
//                     nothing, which is what the bit means either way.
//                     One bit rather than two because a host's response
//                     is the same: the run did not happen, and the
//                     output buffer holds whatever it held before.
//                     CAPS[3:0] says in advance which precisions exist
//                     and CAPS[15] whether there is a sequencer at all;
//                     this bit is what a host that did not ask gets
//                     instead of plausible garbage.
//                 [4] DEPOSIT OVERFLOW on a sequencer run: some lane
//                     pushed past the program's max_deposits, so the
//                     excess was dropped. What fit is correct and the
//                     run is reproducible - which is why this is not
//                     an IEEE flag. The five in FLAGS mean what 754
//                     says they mean and "your buffer was too small"
//                     is not one of them.
//   0x54  PROG_PTR 64-bit HBM byte address of the program image
//                 (header, constants, instructions - see
//                 docs/SEQUENCER.md), 32-byte aligned. Read by the
//                 sequencer at start; ignored when MODE[15] is clear.
//   0x5C  CNT_PTR 64-bit HBM byte address of the per-lane deposit
//                 counts, n uint32s, 4-byte aligned. It is an output
//                 rather than a convenience: +0 is both a legal
//                 deposit and the defined value of a slot no lane
//                 wrote, so the count cannot be recovered from the
//                 deposit buffer.
//   0x64  BANK_PTR 64-bit HBM byte address of a run's CONSTANT BANK
//                 (revision 2). Read by the sequencer only when the
//                 program header's flags.BANK_EXT is set, and then it
//                 is the only source of constants: n_consts dense
//                 format-width values, laid out exactly as an image's
//                 constant section is. One image per positive, loaded
//                 once, with the levers riding as data. It binds to
//                 m_axi_a, the master the image already arrives on -
//                 the two never overlap in time, so no master is added
//                 and hw/link.cfg needs nothing. CAPS[6] says whether
//                 it exists; a 0x600 tile has no such register and its
//                 FETCH would read constants out of an image that has
//                 none, which is why the flag alone cannot guard it.
//   0x6C  CAPS2   RO: the second capability word (revision 3). CAPS
//                 (0x4C) is full - its feature nibble ends at [7] and
//                 its three log2 capacity fields fill [27:16] - so a
//                 fourth capacity needed a register rather than a
//                 field. It carries:
//                 [3:0]  log2 of the SCRATCH slots a lane (SCRATCH_D)
//                 [4]    a per-lane scratch exists: the four control
//                        codes STL/LDL/STX/LDX decode
//                 [5]    the scratch I/O block exists: the header's
//                        flags.SCRATCH_IO is understood and the two
//                        pointers below are read
//                 [31:6] reserved, zero - room for the capacities and
//                        features that come next, so the NEXT one
//                        does not move the map again
//                 A log2 field of zero would have to mean "one slot",
//                 not "no scratch", which is why [4] exists beside
//                 [3:0]; and a tile older than this register reads
//                 0x00000000 from an unmapped address, which says
//                 "none of it" correctly by accident and by the
//                 default arm below on purpose.
//   0x70  SCRATCH_IN_PTR  64-bit HBM byte address of a run's scratch
//                 preload: n * n_scratch_in format-width values,
//                 lane-major and dense (lane i's slot s at element
//                 i * n_scratch_in + s). Read by the sequencer only
//                 when the program header's flags.SCRATCH_IO is set,
//                 in its own phase after the image and the bank and
//                 before the first instruction. It binds to m_axi_a,
//                 the master the image and the bank already arrive
//                 on - the three never overlap in time.
//   0x78  SCRATCH_OUT_PTR 64-bit HBM byte address of the block the
//                 run hands back: n * n_scratch_out values in the same
//                 layout, written after the last deposit of each lane
//                 block. It binds to m_axi_d, beside the deposits and
//                 the counts, because it is written.
//
//                 These five sit ABOVE the read-only block rather than
//                 beside the other pointers, because moving A_PTR..
//                 D_PTR to make room would have changed every existing
//                 argument offset - and hw/kernel.xml's argument ids
//                 are a host ABI. Appending is the only change a
//                 shipped map can take.
//   0x80  SEG     A reduction's SEGMENT LENGTH (2026-09-14, CAPS2[8],
//                 VERSION 0x900). Zero, the decode default, is the whole
//                 array and one result - every reduction before this
//                 register. Non-zero, the accumulator restarts every SEG
//                 elements and the results land contiguously at D_PTR,
//                 d[s] being the same tree over a[s*SEG .. (s+1)*SEG)
//                 that a whole-array reduction of those elements would
//                 give (docs/HOSTAPI.md, cft_reduce_seg). Ignored by an
//                 elementwise run and by a program.
//   0x84  NRES    How many results that is, n / SEG, which the host
//                 computes and guarantees exact (n = NRES * SEG): the
//                 writer needs its beat count before the first result
//                 lands, and a divider in the tile would be a second
//                 opinion on the host's arithmetic. The two are one
//                 64-bit kernel argument (id 11), SEG in the low word.
//                 The same register pair also announces, through
//                 CAPS2[8], that opcode 31 (maxall) is a REDUCTION on
//                 this tile - the accumulator issuing maximum in place
//                 of add - where an older tile decodes 31 as an
//                 elementwise opcode and writes n elements.
//   0x88  IDX_A_PTR   ABI 0.14 (2026-09-15, docs/ROUND2.md; VERSION
//   0x90  IDX_B_PTR   0xA00; kernel arguments 12..15): the INDEX
//   0x98  IDX_C_PTR   TABLES of a program run's three streams and its
//   0xA0  IDX_SI_PTR  scratch block - n (or n * n_scratch_in) u32
//                 entries each, lane-major, beat-padded; element i of
//                 the block is source[idx[i]] and 0xFFFFFFFF reads as
//                 +0. Read by the sequencer through the A master,
//                 each only when its MODE bit ([19] a, [20] b, [21] c,
//                 [22] scratch_in) is set, and those bits are honoured
//                 only where CAPS2[9] is set; on a build without it
//                 the guard (feat_indexed, below) refuses them at
//                 start with STATUS[3] and no read issued. Appended
//                 here at the seam so that the parcel building the
//                 fetch (P1) and the parcel building the mask (P3)
//                 share one map and one version.
//   0xA8  MASK_PTR    the run's LANE MASK (argument 16): (n + 7) / 8
//                 bytes, bit i lane i, set for a lane that runs; read
//                 at block setup when MODE[23] is set, which CAPS2[10]
//                 announces and the same guard refuses without it.

`timescale 1ns/1ps

module cft_csr (
    input  logic        ap_clk,
    input  logic        ap_rst_n,

    // AXI4-Lite slave
    input  logic [11:0] s_axi_control_awaddr,
    input  logic        s_axi_control_awvalid,
    output logic        s_axi_control_awready,
    input  logic [31:0] s_axi_control_wdata,
    input  logic [3:0]  s_axi_control_wstrb,
    input  logic        s_axi_control_wvalid,
    output logic        s_axi_control_wready,
    output logic [1:0]  s_axi_control_bresp,
    output logic        s_axi_control_bvalid,
    input  logic        s_axi_control_bready,
    input  logic [11:0] s_axi_control_araddr,
    input  logic        s_axi_control_arvalid,
    output logic        s_axi_control_arready,
    output logic [31:0] s_axi_control_rdata,
    output logic [1:0]  s_axi_control_rresp,
    output logic        s_axi_control_rvalid,
    input  logic        s_axi_control_rready,

    // engine side
    output logic        start,       // one-cycle pulse
    input  logic        busy,
    input  logic        done,        // one-cycle pulse
    input  logic [4:0]  eng_flags,
    input  logic [5:0]  eng_err,     // sticky faults + refusal + deposit
                                     // overflow + scratch range, see
                                     // STATUS
    input  logic [3:0]  prec_caps,   // constant; from cft_krnl's EN_* params
    input  logic [7:0]  op_caps,     // constant; opcode groups present
    // CAPS[7:4]: what the SEQUENCER can do beyond the base program
    // model, as opposed to whether one exists at all (that is
    // op_caps[7]). [4] is set from 2026-09-07; the assignments are
    // reserved here so that two builds cannot spend the same bit on
    // two features:
    //   [4] wide constant index - an instruction addresses more than
    //       the 16 constants a 4-bit operand field reaches
    //   [5] REGS32 - five-bit register fields (2026-09-08)
    //   [6] BANK_PTR - the per-run constant bank (2026-09-08)
    //   [7] KX9 - a ninth constant-index bit under kx, so the bank
    //       reaches 512 (revision 3, 2026-09-08)
    // A host reads them the way it reads op_caps: ask, then issue.
    // The nibble is now FULL; the next sequencer feature takes a bit
    // of CAPS2 below, which is what that register exists for.
    input  logic [3:0]  seq_feat,    // constant; CAPS[7:4]
    // CAPS2 (0x6C), the second capability word: [3:0] log2 of the
    // scratch slots a lane, [4] a scratch exists, [5] its per-run
    // block exists, [31:6] reserved. Assembled by cft_krnl from the
    // same localparams cft_seq elaborates its scratch from, so the
    // register cannot drift from the memory it describes without the
    // elaboration changing too.
    input  logic [15:0] caps2,
    // The sequencer's on-chip capacities, as LOG2, from the very
    // parameters cft_krnl hands cft_seq - so CAPS cannot drift from
    // the memories it describes without the elaboration changing too.
    input  logic [3:0]  cap_maxd,    // CAPS[19:16] log2(MAXD)
    input  logic [3:0]  cap_imem,    // CAPS[23:20] log2(IMEM_D)
    input  logic [3:0]  cap_kreg,    // CAPS[27:24] log2(addressable consts)
    // CAPS[31:28]: ALU extensions beyond the opcode groups - an opcode
    // that joins a group after bitstreams shipped with the group's bit
    // set cannot be announced by that bit, so it takes one here.
    //   [28] IMUL, opcode 30 (2026-09-07)
    input  logic [3:0]  alu_ext,     // constant; CAPS[31:28]
    output logic [7:0]  cfg_op,
    output logic [3:0]  cfg_prec,
    output logic [2:0]  cfg_rnd,
    output logic        cfg_seq,     // MODE[15]: this run is a program
    output logic [63:0] cfg_n,
    output logic [63:0] cfg_a,
    output logic [63:0] cfg_b,
    output logic [63:0] cfg_c,
    output logic [63:0] cfg_d,
    output logic [63:0] cfg_prog,
    output logic [63:0] cfg_bank,
    output logic [63:0] cfg_sin,
    output logic [63:0] cfg_sout,
    /* The MODE bits are decoded here so every consumer reads one
     * name rather than a bit index, which is how MODE[15] is handled. */
    output logic [2:0]  cfg_scalar,    // MODE[18:16], a/b/c stride-0
    /* MODE[22:19] (ABI 0.14, R16): which of a program run's four input
     * blocks are fetched through an index table - [0] a, [1] b, [2] c,
     * [3] scratch_in, the order the four pointer registers are in at
     * 0x88..0xA0. Decoded here beside cfg_scalar and for the same
     * reason: the sequencer reads one name rather than a bit index. */
    output logic [3:0]  cfg_indexed,
    /* MODE[23] (ABI 0.14, R17): the run carries a lane mask at
     * MASK_PTR. Decoded here beside cfg_indexed and for the same
     * reason - the sequencer reads one name rather than a bit index. */
    output logic        cfg_mask_en,
    output logic        cfg_mode_bad,  // a MODE bit this build refuses
    /* Constants from cft_krnl's localparams, exactly as prec_caps and
     * op_caps are: the tile decides what it carries, the CSR decides
     * what to refuse, and neither hard-codes the other's answer. */
    input  logic        feat_scalar,
    /* ...and the same for the index tables (CAPS2[9]). A build whose
     * sequencer cannot gather refuses MODE[22:19] rather than ignoring
     * it, which is the same argument feat_scalar makes: an ignored
     * table would read the dense stream and answer confidently from
     * the wrong elements. */
    input  logic        feat_indexed,
    /* ...and the same for the lane mask (CAPS2[10]). A build whose
     * sequencer does not read MASK_PTR refuses MODE[23] rather than
     * ignoring it: an ignored mask would run every lane and write
     * over the caller's bytes in the lanes it was told to leave
     * alone, confidently and with clean flags. */
    input  logic        feat_lane_mask,
    output logic [63:0] cfg_cnt,
    // SEG / NRES (0x80 / 0x84): a reduction's segment length and its
    // result count; zero is the whole array.
    output logic [31:0] cfg_seg,
    output logic [31:0] cfg_nres,
    // ABI 0.14 (docs/ROUND2.md): the four index-table pointers and the
    // lane-mask pointer, 0x88..0xA8. Registers only at this version -
    // the MODE bits that would select them are refused (cfg_mode_bad)
    // until the parcels that read them set CAPS2[9] and [10].
    output logic [63:0] cfg_idx_a, cfg_idx_b, cfg_idx_c, cfg_idx_si,
    output logic [63:0] cfg_mask
);

  localparam [31:0] MAGIC   = 32'h4346_5430;
  // v0.8.0: CAPS2 at 0x6C and the two scratch pointers at 0x70/0x78.
  //
  // VERSION guards the REGISTER MAP, not the feature set. Adding an
  // opcode group does not move a register, so a host built for 0x410
  // reads every register correctly from a 0x500 tile and vice versa -
  // and it will not issue opcode 24 to a tile whose CAPS bit 13 is
  // clear, because asking CAPS is the protocol. That is why the host
  // accepts a SET of contract versions rather than one: bumping this
  // must not orphan a bitstream whose registers it understands
  // perfectly, and the card-day images are 0x410.
  //
  // 0x500 -> 0x600 is a bump the previous two were not: the map GREW.
  // Four registers exist at 0x54..0x60 that did not, so a host that
  // writes PROG_PTR to a 0x500 tile writes into a decode default and
  // starts a sequencer run against address zero. That is precisely
  // what this register is for, and it is why 0x600 is a new entry in
  // the host's accepted set rather than a replacement for the old
  // ones - the old maps are still correct, just smaller.
  //
  // 0x600 -> 0x700 (revision 2, 2026-09-08) is a bump for exactly the
  // same reason and no other: two registers exist at 0x64 and 0x68
  // that did not, so a host that writes BANK_PTR to a 0x600 tile
  // writes into a decode default and runs a BANK_EXT program against
  // constants at address zero. Revision 2's other two changes do NOT
  // move VERSION and could not: five-bit register fields and IMEM_D
  // 4096 add no register, and features are announced in CAPS - REGS32
  // at [5], BANK_PTR at [6], the instruction capacity in [23:20]
  // where it was already published. The host accepts {0x410, 0x500,
  // 0x600, 0x700}: the card-day images are 0x410 and 0x600 and their
  // maps are still correct, just smaller.
  //
  // 0x700 -> 0x800 (revision 3, 2026-09-08) is the same bump a third
  // time, and it is the whole of why VERSION moves: THREE registers
  // exist at 0x6C, 0x70/0x74 and 0x78/0x7C that did not, so a host
  // that writes SCRATCH_IN_PTR to a 0x700 tile writes into a decode
  // default and would run a SCRATCH_IO program against a preload at
  // address zero. Revision 3's other two changes add no register and
  // could not move it: IMEM_D 16384 and the ninth constant-index bit
  // are published in CAPS[23:20] and CAPS[7], in fields that already
  // existed. The host accepts {0x410, 0x500, 0x600, 0x700, 0x800} -
  // every one of those maps is still correct, just smaller, and the
  // card-day images are 0x410 and 0x600.
  //
  // 0x800 -> 0x900 (2026-09-14) is the same bump a fourth time: SEG and
  // NRES exist at 0x80 and 0x84 as kernel argument 11, so a host that
  // writes a segment length to an 0x800 tile writes into a decode
  // default and gets one result where it sized NRES. The host accepts
  // {0x410, 0x500, 0x600, 0x700, 0x800, 0x900}. The feature the
  // register serves is announced in CAPS2[8] as every feature is.
  //
  // 0x900 -> 0xA00 (2026-09-15, docs/ROUND2.md) is the same bump a
  // fifth time, and the first made at a SEAM rather than with a
  // feature: five registers exist at 0x88..0xAF as kernel arguments
  // 12..16 - four index-table pointers and a lane-mask pointer - so
  // that the two parcels that will read them share one map. Nothing
  // reads them at this version: the MODE bits that would are still
  // refused by the guard below, and CAPS2[9] and [10] are zero until
  // each parcel sets its own. A host that wrote a table pointer to a
  // 0x900 tile would write into a decode default, which is the whole
  // of why VERSION moves. The host accepts {0x410, 0x500, 0x600,
  // 0x700, 0x800, 0x900, 0xA00}.
  localparam [31:0] VERSION = 32'h0000_0A00;

  logic ap_start_q, ap_done_q, ap_idle;
  logic [31:0] gier_q, ier_q;
  logic [31:0] mode_q;
  logic [63:0] n_q, a_q, b_q, c_q, d_q, prog_q, bank_q, cnt_q;
  logic [63:0] sin_q, sout_q;
  logic [31:0] seg_q, nres_q;              // 0x80 / 0x84
  logic [63:0] idx_a_q, idx_b_q, idx_c_q, idx_si_q, mask_q;   // 0x88 .. 0xAF

  assign ap_idle  = !busy;
  assign cfg_op   = mode_q[7:0];
  assign cfg_prec = mode_q[11:8];
  assign cfg_rnd  = mode_q[14:12];
  assign cfg_seq  = mode_q[15];
  assign cfg_n = n_q;
  assign cfg_a = a_q;
  assign cfg_b = b_q;
  assign cfg_c = c_q;
  assign cfg_d = d_q;
  assign cfg_prog = prog_q;
  assign cfg_bank = bank_q;
  assign cfg_sin  = sin_q;
  assign cfg_seg  = seg_q;
  assign cfg_nres = nres_q;
  assign cfg_idx_a  = idx_a_q;
  assign cfg_idx_b  = idx_b_q;
  assign cfg_idx_c  = idx_c_q;
  assign cfg_idx_si = idx_si_q;
  assign cfg_mask   = mask_q;
  assign cfg_sout = sout_q;

  assign cfg_scalar   = mode_q[18:16];
  assign cfg_indexed  = mode_q[22:19];
  assign cfg_mask_en  = mode_q[23];

  /* A MODE bit this build will not honour, which must be REFUSED and
   * never ignored: an ignored stride-0 flag reads n elements from a
   * one-element buffer, and an ignored index table reads the dense
   * stream and answers from the wrong elements with clean flags.
   * [31:23] is reserved on every build; [22:16] is refused unless the
   * feature parameter says this tile carries it.
   *
   * Written as an OR of named terms rather than a mask compare, for the
   * reason op_caps is written as a bit per group in cft_krnl.sv: a mask
   * is one typo away from silently permitting a bit.
   *
   * MODE[23], the lane mask, has its own feature bit as of P3 and is
   * refused exactly where the tile cannot honour it; [31:24] is what
   * is left of the reserved range. */
  assign cfg_mode_bad =
      (mode_q[31:24] != 8'b0)                     ||
      (mode_q[23] && !feat_lane_mask)             ||
      (|mode_q[22:19] && !feat_indexed)           ||
      (|mode_q[18:16] && !feat_scalar);
  assign cfg_cnt  = cnt_q;

  // ---- write channel ------------------------------------------------
  logic        have_aw, have_w;
  logic [11:0] awaddr_q;
  logic [31:0] wdata_q;
  logic [3:0]  wstrb_q;
  logic        do_write;
  logic [31:0] wmask;

  assign s_axi_control_awready = !have_aw && !s_axi_control_bvalid;
  assign s_axi_control_wready  = !have_w && !s_axi_control_bvalid;
  assign do_write = have_aw && have_w;
  // Both the mask and the data come from the REGISTERED beat, never
  // from the live bus: do_write is at least one cycle after the W
  // handshake, and AXI4-Lite only requires WDATA to be valid while
  // WVALID is asserted. A master that pipelines its writes (or drives
  // zeros between them) would otherwise have each register commit its
  // successor's payload - invisible to a testbench that waits for
  // BVALID between writes, which is what both of ours do.
  assign wmask = {{8{wstrb_q[3]}}, {8{wstrb_q[2]}}, {8{wstrb_q[1]}}, {8{wstrb_q[0]}}};
  assign s_axi_control_bresp = 2'b00;

  // start pulse: host writes CTRL[0]=1 while idle
  logic start_req;
  assign start_req = do_write && (awaddr_q[11:2] == 10'h000) &&
                     wstrb_q[0] && wdata_q[0];

  always_ff @(posedge ap_clk) begin
    if (!ap_rst_n) begin
      have_aw <= 1'b0;
      have_w  <= 1'b0;
      s_axi_control_bvalid <= 1'b0;
      ap_start_q <= 1'b0;
      ap_done_q  <= 1'b0;
      start      <= 1'b0;
      gier_q <= '0;
      ier_q  <= '0;
      mode_q <= '0;
      n_q <= '0; a_q <= '0; b_q <= '0; c_q <= '0; d_q <= '0;
      prog_q <= '0; cnt_q <= '0; bank_q <= '0;
      sin_q <= '0; sout_q <= '0;
      seg_q <= '0; nres_q <= '0;
      idx_a_q <= '0; idx_b_q <= '0; idx_c_q <= '0; idx_si_q <= '0;
      mask_q <= '0;
    end else begin
      start <= 1'b0;

      if (s_axi_control_awvalid && s_axi_control_awready) begin
        have_aw  <= 1'b1;
        awaddr_q <= s_axi_control_awaddr;
      end
      if (s_axi_control_wvalid && s_axi_control_wready) begin
        have_w  <= 1'b1;
        wdata_q <= s_axi_control_wdata;
        wstrb_q <= s_axi_control_wstrb;
      end

      if (do_write) begin
        have_aw <= 1'b0;
        have_w  <= 1'b0;
        s_axi_control_bvalid <= 1'b1;
        // synthesis translate_off
        $display("[CFT-CSR] WR addr=0x%03h data=0x%08h strb=%b",
                 {awaddr_q[11:2], 2'b00}, wdata_q, wstrb_q);
        // synthesis translate_on
        case (awaddr_q[11:2])
          10'h000: begin
            if (start_req && !ap_start_q && !busy) begin
              ap_start_q <= 1'b1;
              start      <= 1'b1;
              // Drop any done left over from the previous run. A host
              // that starts again without reading CTRL first would
              // otherwise see the OLD done immediately and read a
              // half-written D buffer.
              ap_done_q  <= 1'b0;
            end
          end
          10'h001: gier_q <= (gier_q & ~wmask) | (wdata_q & wmask);
          10'h002: ier_q  <= (ier_q  & ~wmask) | (wdata_q & wmask);
          // 0x0C ISR: write-1-to-clear semantics unneeded (no interrupt)
          10'h004: mode_q <= (mode_q & ~wmask) | (wdata_q & wmask);
          10'h006: n_q[31:0]  <= (n_q[31:0]  & ~wmask) | (wdata_q & wmask);
          10'h007: n_q[63:32] <= (n_q[63:32] & ~wmask) | (wdata_q & wmask);
          10'h008: a_q[31:0]  <= (a_q[31:0]  & ~wmask) | (wdata_q & wmask);
          10'h009: a_q[63:32] <= (a_q[63:32] & ~wmask) | (wdata_q & wmask);
          10'h00A: b_q[31:0]  <= (b_q[31:0]  & ~wmask) | (wdata_q & wmask);
          10'h00B: b_q[63:32] <= (b_q[63:32] & ~wmask) | (wdata_q & wmask);
          10'h00C: c_q[31:0]  <= (c_q[31:0]  & ~wmask) | (wdata_q & wmask);
          10'h00D: c_q[63:32] <= (c_q[63:32] & ~wmask) | (wdata_q & wmask);
          10'h00E: d_q[31:0]  <= (d_q[31:0]  & ~wmask) | (wdata_q & wmask);
          10'h00F: d_q[63:32] <= (d_q[63:32] & ~wmask) | (wdata_q & wmask);
          // 0x54 / 0x5C: the sequencer's two pointers. Above the
          // read-only block, because appending is the only change a
          // map with a shipped argument list can take.
          10'h015: prog_q[31:0]  <= (prog_q[31:0]  & ~wmask) | (wdata_q & wmask);
          10'h016: prog_q[63:32] <= (prog_q[63:32] & ~wmask) | (wdata_q & wmask);
          10'h017: cnt_q[31:0]   <= (cnt_q[31:0]   & ~wmask) | (wdata_q & wmask);
          10'h018: cnt_q[63:32]  <= (cnt_q[63:32]  & ~wmask) | (wdata_q & wmask);
          // 0x64 / 0x68: BANK_PTR, appended for the same reason and in
          // the same place as the two above.
          10'h019: bank_q[31:0]  <= (bank_q[31:0]  & ~wmask) | (wdata_q & wmask);
          10'h01A: bank_q[63:32] <= (bank_q[63:32] & ~wmask) | (wdata_q & wmask);
          // 0x6C is CAPS2 and is READ-ONLY, so 10'h01B has no write
          // arm - it falls to the default and is dropped, exactly as
          // a write to FLAGS, MAGIC, VERSION, CAPS or STATUS is.
          // 0x70 / 0x78: the two scratch pointers, appended after it
          // for the reason the three before them were appended.
          10'h01C: sin_q[31:0]   <= (sin_q[31:0]   & ~wmask) | (wdata_q & wmask);
          10'h01D: sin_q[63:32]  <= (sin_q[63:32]  & ~wmask) | (wdata_q & wmask);
          10'h01E: sout_q[31:0]  <= (sout_q[31:0]  & ~wmask) | (wdata_q & wmask);
          10'h01F: sout_q[63:32] <= (sout_q[63:32] & ~wmask) | (wdata_q & wmask);
          // 0x80 / 0x84: SEG and NRES, appended for the reason the seven
          // words before them were appended.
          10'h020: seg_q  <= (seg_q  & ~wmask) | (wdata_q & wmask);
          10'h021: nres_q <= (nres_q & ~wmask) | (wdata_q & wmask);
          // 0x88 .. 0xA8: the four index tables and the lane mask (ABI
          // 0.14), appended for the reason the nine words before them
          // were, at the seam of the round that reads them.
          10'h022: idx_a_q[31:0]   <= (idx_a_q[31:0]   & ~wmask) | (wdata_q & wmask);
          10'h023: idx_a_q[63:32]  <= (idx_a_q[63:32]  & ~wmask) | (wdata_q & wmask);
          10'h024: idx_b_q[31:0]   <= (idx_b_q[31:0]   & ~wmask) | (wdata_q & wmask);
          10'h025: idx_b_q[63:32]  <= (idx_b_q[63:32]  & ~wmask) | (wdata_q & wmask);
          10'h026: idx_c_q[31:0]   <= (idx_c_q[31:0]   & ~wmask) | (wdata_q & wmask);
          10'h027: idx_c_q[63:32]  <= (idx_c_q[63:32]  & ~wmask) | (wdata_q & wmask);
          10'h028: idx_si_q[31:0]  <= (idx_si_q[31:0]  & ~wmask) | (wdata_q & wmask);
          10'h029: idx_si_q[63:32] <= (idx_si_q[63:32] & ~wmask) | (wdata_q & wmask);
          10'h02A: mask_q[31:0]    <= (mask_q[31:0]    & ~wmask) | (wdata_q & wmask);
          10'h02B: mask_q[63:32]   <= (mask_q[63:32]   & ~wmask) | (wdata_q & wmask);
          default: ;
        endcase
      end
      if (s_axi_control_bvalid && s_axi_control_bready)
        s_axi_control_bvalid <= 1'b0;

      if (done) begin
        ap_done_q  <= 1'b1;
        ap_start_q <= 1'b0;
      end
      // ap_done clears on read of CTRL (handled in the read channel)
      if (s_axi_control_arvalid && s_axi_control_arready &&
          (s_axi_control_araddr[11:2] == 10'h000) && !done)
        ap_done_q <= 1'b0;
    end
  end

  // ---- read channel -------------------------------------------------
  assign s_axi_control_arready = !s_axi_control_rvalid;
  assign s_axi_control_rresp = 2'b00;

  always_ff @(posedge ap_clk) begin
    if (!ap_rst_n) begin
      s_axi_control_rvalid <= 1'b0;
      s_axi_control_rdata  <= '0;
    end else begin
      if (s_axi_control_arvalid && s_axi_control_arready) begin
        s_axi_control_rvalid <= 1'b1;
        case (s_axi_control_araddr[11:2])
          10'h000: s_axi_control_rdata <= {28'b0, ap_done_q, ap_idle, ap_done_q, ap_start_q};
          10'h001: s_axi_control_rdata <= gier_q;
          10'h002: s_axi_control_rdata <= ier_q;
          10'h003: s_axi_control_rdata <= 32'h0;
          10'h004: s_axi_control_rdata <= mode_q;
          10'h006: s_axi_control_rdata <= n_q[31:0];
          10'h007: s_axi_control_rdata <= n_q[63:32];
          10'h008: s_axi_control_rdata <= a_q[31:0];
          10'h009: s_axi_control_rdata <= a_q[63:32];
          10'h00A: s_axi_control_rdata <= b_q[31:0];
          10'h00B: s_axi_control_rdata <= b_q[63:32];
          10'h00C: s_axi_control_rdata <= c_q[31:0];
          10'h00D: s_axi_control_rdata <= c_q[63:32];
          10'h00E: s_axi_control_rdata <= d_q[31:0];
          10'h00F: s_axi_control_rdata <= d_q[63:32];
          10'h010: s_axi_control_rdata <= {27'b0, eng_flags};
          10'h011: s_axi_control_rdata <= MAGIC;
          10'h012: s_axi_control_rdata <= VERSION;
          10'h013: s_axi_control_rdata <= {alu_ext, cap_kreg, cap_imem, cap_maxd,
                                           op_caps, seq_feat, prec_caps};
          10'h014: s_axi_control_rdata <= {26'b0, eng_err};
          10'h015: s_axi_control_rdata <= prog_q[31:0];
          10'h016: s_axi_control_rdata <= prog_q[63:32];
          10'h017: s_axi_control_rdata <= cnt_q[31:0];
          10'h018: s_axi_control_rdata <= cnt_q[63:32];
          10'h019: s_axi_control_rdata <= bank_q[31:0];
          10'h01A: s_axi_control_rdata <= bank_q[63:32];
          10'h01B: s_axi_control_rdata <= {16'b0, caps2};
          10'h01C: s_axi_control_rdata <= sin_q[31:0];
          10'h01D: s_axi_control_rdata <= sin_q[63:32];
          10'h01E: s_axi_control_rdata <= sout_q[31:0];
          10'h01F: s_axi_control_rdata <= sout_q[63:32];
          10'h020: s_axi_control_rdata <= seg_q;
          10'h021: s_axi_control_rdata <= nres_q;
          10'h022: s_axi_control_rdata <= idx_a_q[31:0];
          10'h023: s_axi_control_rdata <= idx_a_q[63:32];
          10'h024: s_axi_control_rdata <= idx_b_q[31:0];
          10'h025: s_axi_control_rdata <= idx_b_q[63:32];
          10'h026: s_axi_control_rdata <= idx_c_q[31:0];
          10'h027: s_axi_control_rdata <= idx_c_q[63:32];
          10'h028: s_axi_control_rdata <= idx_si_q[31:0];
          10'h029: s_axi_control_rdata <= idx_si_q[63:32];
          10'h02A: s_axi_control_rdata <= mask_q[31:0];
          10'h02B: s_axi_control_rdata <= mask_q[63:32];
          default: s_axi_control_rdata <= 32'h0;
        endcase
      end
      if (s_axi_control_rvalid && s_axi_control_rready)
        s_axi_control_rvalid <= 1'b0;
    end
  end

endmodule
