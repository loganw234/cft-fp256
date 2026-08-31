// Copyright 2026 Logan W.
// SPDX-License-Identifier: Apache-2.0
//
// cft_normseg: one segmented normalise shifter for every lane.
//
// The normalise shift (cft_fpfma_pipe S11 coarse + S12 fine) is a
// left barrel shift of a GW = 3P + 6 bit window, and there is one per
// lane - fifteen of them. Unlike the significand multiplier, whose
// cost is quadratic in P, a shifter's cost is LINEAR in P, and that is
// the whole reason this module can exist:
//
//     mode      lanes   GW = 3P + 6   aggregate
//     fp32        8          78          624
//     fp64        4         165          660
//     fp128       2         345          690
//     fp256       1         717          717
//
// Every bank consumes exactly one 256-bit beat, so every bank's
// AGGREGATE window width is within 15% of every other one. One 717-bit
// shifter hosts all four, and 2,706 bits of private ladder collapse
// into 717. The multiplier could not do this: its aggregate is 97,551
// bit-products against a widest bank of 56,169, so sharing buys 1.5x
// there and 3.8x here.
//
// Whether that translates into LUTs is a separate question from
// whether the geometry works, and cft_mulfrac is the cautionary tale -
// correct, proven bit-identical, and measured NOT to pay because the
// resource it collapsed was DSP, which is not scarce. This one
// collapses LUTs, which are. It still ships behind a parameter,
// default off, until a before/after says so.
//
// UNIFORM SLOTS, AND WHY 90
//
// The natural widths (78/165/345/717) do not nest, and non-nesting
// boundaries are what make a segmented shifter expensive: a bit's lane
// would differ per mode with no common structure, so the shift-amount
// selection becomes a mux per BIT rather than per region.
//
// Padding to eight uniform slots fixes that. A slot must hold one fp32
// window (78) and eight must hold one fp256 window (717), so
// SLOTW = ceil(717/8) = 90, and the boundaries then nest exactly:
//
//     mode 0   lane l -> slot l                 (78 of 90 used)
//     mode 1   lane l -> slots 2l, 2l+1        (165 of 180)
//     mode 2   lane l -> slots 4l .. 4l+3      (345 of 360)
//     mode 3   the whole 720                   (717 of 720)
//
// so the lane owning bit i is just `slot(i) >> mode`. The shift-amount
// select is therefore ONE 4:1 mux per slot per stage - eighty in the
// whole module - instead of one per bit.
//
// THE LADDER
//
// The pipe's shift amount is `lsh_coarse * 64 + fine` with fine in
// 0..63, so the concatenation {csh, fsh} IS the total amount: ten
// levels, shifting by 1 through 512. Latency is 2, matching S11 -> S12,
// so nothing else in the pipeline moves.
//
// WHERE THE REGISTER GOES
//
// SPLIT levels run before the register and NST-SPLIT after, and every
// value computes the same function - it is purely a timing knob. The
// pipe's own csh/fsh boundary is 4, but that is a 64-granule split in
// the ARITHMETIC and there is no reason a pipeline boundary should
// coincide with it.
//
// The two halves are not symmetric in delay, which is the thing to
// understand before touching this. The first stage's amount bits come
// live off the leading-zero count of s10_mag, so its path is
// LZC + slot mux + SPLIT levels. The second stage's bits are already
// registered, so its path is NST-SPLIT levels and nothing else.
// Balancing the LEVEL COUNTS is therefore the wrong instinct: the
// first stage starts with a large fixed cost the second does not have,
// so the balance point sits well below five.
//
// Measured at the kernel, the 4/6 split cost 0.668 ns of slack against
// FUSE_NORM=0 - and the shared version differs from the private one
// only by adding the slot mux to that first stage, which is itself
// evidence the first stage is the critical one.
//
// Each stage is `out[i] = en[i] ? in[i - 2^k] : in[i]`, where en is the
// owning lane's amount bit gated by an ALLOW constant that stops a
// lane pulling bits out of its neighbour. ALLOW is 1 for every bit
// more than 2^k above its group's start, which is most of them, so
// most stage bits stay a plain 2:1 mux and only the boundary
// neighbourhoods pay for the gate.

`timescale 1ns/1ps

module cft_normseg #(
    parameter int PMAX  = 237,             // fp256 significand, 1 + MAN_W
    parameter int SLOTS = 8,               // = 256/32, the fp32 lane count
    // Derived. Do not override: SLOTW is the smallest slot that holds
    // an fp32 window and tiles to an fp256 one, and WT is the ladder.
    parameter int SLOTW = ((3 * PMAX + 6) + SLOTS - 1) / SLOTS,
    parameter int WT    = SLOTS * SLOTW,
    // How many of the ten levels run BEFORE the register. See "WHERE THE
    // REGISTER GOES" in the header - this is a timing knob, not a
    // correctness one, and every value from 1 to 9 computes the same
    // function (the equivalence bench passes at 1, 2, 3, 4, 5, 7, 9).
    //
    // 1 is measured, not guessed. Swept at the kernel against the
    // unshared baseline's +2.456 ns:
    //
    //   SPLIT   LUT       WNS      levels   critical path
    //     -   115,903   +2.456       21     S13 rounding
    //     1   110,780   +2.474       21     S13 rounding
    //     2   110,612   +2.051       23     this ladder
    //     3   110,532   +2.141       22     this ladder
    //     4   110,940   +2.038       22     this ladder
    //
    // Only at 1 does the ladder stop being critical and hand the clock
    // back to the rounding stage, which is what makes sharing free
    // rather than merely cheap. 2 and 3 are ~250 LUT smaller and cost
    // 0.4 ns; that is the wrong side of the trade.
    parameter int SPLIT = 1,
    // Per-lane shift DIRECTION. The normaliser only ever shifts left,
    // and with BIDIR=0 the dir port is ignored and the generated logic
    // is exactly the left-only ladder. The ALIGNER shifts either way -
    // left when the addend anchors, right when the product does, and
    // adjacent lanes disagree freely - so BIDIR=1 gives each slot a
    // direction and the boundary masks exist in both orientations:
    // left must not pull from below the group, right must not pull
    // from above it, and both fill zero at their own edge.
    parameter bit BIDIR = 1'b0
) (
    input  logic             clk,
    input  logic [1:0]       mode,          // 0 fp32, 1 fp64, 2 fp128, 3 fp256
    input  logic [WT-1:0]    din,           // lanes packed at slot pitch
    input  logic [3:0]       csh [0:SLOTS-1],   // coarse, in 64-bit granules
    input  logic [5:0]       fsh [0:SLOTS-1],   // fine, 0..63
    input  logic             dir [0:SLOTS-1],   // per lane: 0 left, 1 right (BIDIR only)
    output logic [WT-1:0]    dout
);

  localparam int NST  = 10;                 // 2^9 = 512 covers 717
  localparam int LO   = NST - SPLIT;        // levels after the register
  localparam int LOGS = $clog2(SLOTS);      // modes 0..LOGS

  // The interchange ladder. These are the formats, not knobs - GW is
  // cft_fpfma_pipe's own 3P + 6 and the lane count is 256/width.
  localparam int NW0 = 3 * 24  + 6, LN0 = 8;
  localparam int NW1 = 3 * 53  + 6, LN1 = 4;
  localparam int NW2 = 3 * 113 + 6, LN2 = 2;
  localparam int NW3 = 3 * 237 + 6, LN3 = 1;

  // Elaboration guards. Every one of these is a silent-wrong-answer
  // failure rather than a build failure, which is why they are here:
  // a window wider than its slot group would be truncated, and a
  // truncated significand window is a wrong result with clean flags.
  generate
    if (NW0 > SLOTW)             begin : g_fit32
      $error("cft_normseg: fp32 window %0d exceeds slot %0d", NW0, SLOTW);
    end
    if (NW1 > 2 * SLOTW)         begin : g_fit64
      $error("cft_normseg: fp64 window %0d exceeds 2 slots", NW1);
    end
    if (NW2 > 4 * SLOTW)         begin : g_fit128
      $error("cft_normseg: fp128 window %0d exceeds 4 slots", NW2);
    end
    if (NW3 > WT)                begin : g_fit256
      $error("cft_normseg: fp256 window %0d exceeds the ladder %0d", NW3, WT);
    end
    if (SLOTS != (1 << LOGS))    begin : g_pow2
      $error("cft_normseg: SLOTS must be a power of two");
    end
    if ((1 << (NST - 1)) < WT / 2) begin : g_stages
      $error("cft_normseg: NST too small for the ladder width");
    end
    if (SPLIT < 1 || SPLIT > NST - 1) begin : g_split
      $error("cft_normseg: SPLIT must leave at least one level on each side");
    end
  endgenerate

  initial begin
    if (NW0 > SLOTW || NW1 > 2*SLOTW || NW2 > 4*SLOTW || NW3 > WT) begin
      $display("FATAL: cft_normseg slot geometry cannot hold a window (SLOTW=%0d WT=%0d)",
               SLOTW, WT);
      $finish;
    end
  end

  // The amount and the mode TRAVEL WITH THE DATA. The first stage
  // consumes its bits in the cycle the operand arrives; the second runs
  // a cycle later and must use THAT operand's bits, not whatever is on
  // the port by then. cft_fpfma_pipe does the same thing by registering
  // s11_fine and reading it in S12, and a shared ladder has to, or it
  // silently mixes two operations' shifts whenever the amounts change
  // cycle to cycle.
  //
  // The whole distance as one number. csh counts 64-bit granules and
  // fsh is the 0..63 remainder, so {csh, fsh} IS the amount and level k
  // simply reads bit k of it. The pipe's csh/fsh boundary is arithmetic,
  // not structural, and nothing requires the register to sit there.
  logic [NST-1:0] amt [0:SLOTS-1];
  always_comb begin
    for (int l = 0; l < SLOTS; l++) amt[l] = {csh[l], fsh[l]};
  end

  // Only the levels that run in the SECOND stage need their amount bits
  // registered; the first stage consumes its bits live, in the cycle
  // the operand arrives. The mode is registered for the same reason -
  // in the engine prec_r cannot move mid-flight, so this costs two
  // flip-flops and buys independence from that argument.
  logic [LO-1:0] amt_lo_r [0:SLOTS-1];
  logic [1:0]    mode_r;
  logic          dir_r [0:SLOTS-1];
  always_ff @(posedge clk) begin
    for (int l = 0; l < SLOTS; l++) begin
      amt_lo_r[l] <= amt[l][LO-1:0];
      dir_r[l]    <= dir[l];
    end
    mode_r <= mode;
  end

  // Per slot, the amount of the lane that owns it. Slot s belongs to
  // lane s >> mode, which is the whole benefit of the uniform pitch:
  // this is eighty 4:1 muxes, and it is the entire runtime cost of
  // being segmented.
  // BALANCED 5/5, not 4/6. The distance is one ten-bit number and the
  // register may sit anywhere in it; the pipe's own csh/fsh split is a
  // 64-granule boundary, not a pipeline boundary. Splitting there put
  // four mux levels in the first stage and six in the second, so the
  // second stage set the clock. Moving the 32-bit level up makes it
  // five and five.
  //
  // slot_hi is amount bits 9..5 = {csh, fsh[5]}, taken live because the
  // first stage consumes them in the cycle the operand arrives.
  // slot_lo is bits 4..0, registered, because the second stage runs a
  // cycle later and must use ITS operand's amount.
  logic [SPLIT-1:0] slot_hi [0:SLOTS-1];
  logic [LO-1:0]    slot_lo [0:SLOTS-1];
  logic             slot_dhi [0:SLOTS-1];   // direction, first stage
  logic             slot_dlo [0:SLOTS-1];   // direction, second stage
  always_comb begin
    for (int s = 0; s < SLOTS; s++) begin
      slot_hi[s]  = amt[s >> mode][NST-1:LO];
      slot_lo[s]  = amt_lo_r[s >> mode_r];
      slot_dhi[s] = BIDIR ? dir[s >> mode]     : 1'b0;
      slot_dlo[s] = BIDIR ? dir_r[s >> mode_r] : 1'b0;
    end
  end

  // ALLOW[k] for a given mode: 1 where bit i sits at least 2^k above
  // the start of its lane's group, so the shift cannot reach across a
  // boundary. Constant at elaboration; one 4:1 select of constants at
  // runtime, which folds into the stage mux for all but the boundary
  // neighbourhoods.
  function automatic logic [WT-1:0] allow_mask(input int slots_per_lane,
                                               input int k);
    logic [WT-1:0] v;
    int gw;
    begin
      gw = slots_per_lane * SLOTW;
      v  = '0;
      for (int i = 0; i < WT; i++) v[i] = ((i % gw) >= (1 << k));
      allow_mask = v;
    end
  endfunction

  // The mirror image, for right shifts: bit i may take from i + 2^k
  // only when the source is still inside i's own group.
  function automatic logic [WT-1:0] allow_mask_r(input int slots_per_lane,
                                                 input int k);
    logic [WT-1:0] v;
    int gw;
    begin
      gw = slots_per_lane * SLOTW;
      v  = '0;
      for (int i = 0; i < WT; i++) v[i] = ((i % gw) < (gw - (1 << k)));
      allow_mask_r = v;
    end
  endfunction

  // The ladder. cs[] is the coarse half (stages 6..9), fs[] the fine
  // half (stages 0..5), with a register between them and after.
  // The dependency analysis is per-variable and not per-element, so a
  // ladder written as an array reads as `cs` depending on `cs` and
  // trips UNOPTFLAT. It is strictly acyclic: cs[0] is din and cs[k+1]
  // reads only cs[k], for k in 0..3, and likewise fs. The pragma is a
  // comment to Icarus, Yosys and Vivado, so it costs those nothing.
  //
  // A comment whose first word is the tool's own name is read as a
  // pragma, so this one deliberately does not start that way.
  /* verilator lint_off UNOPTFLAT */
  logic [WT-1:0] cs [0:SPLIT];
  logic [WT-1:0] fs [0:LO];
  /* verilator lint_on UNOPTFLAT */
  logic [WT-1:0] cs_r;

  assign cs[0] = din;
  assign fs[0] = cs_r;

  genvar gk, gb;
  generate
    // ---- coarse: stages 6..9, the 64-granule half ------------------
    for (gk = 0; gk < SPLIT; gk = gk + 1) begin : g_hi
      localparam int K  = LO + gk;
      localparam int SH = 1 << K;
      localparam logic [WT-1:0] A0 = allow_mask(1, K);
      localparam logic [WT-1:0] A1 = allow_mask(2, K);
      localparam logic [WT-1:0] A2 = allow_mask(4, K);
      localparam logic [WT-1:0] A3 = allow_mask(8, K);

      localparam logic [WT-1:0] R0 = allow_mask_r(1, K);
      localparam logic [WT-1:0] R1 = allow_mask_r(2, K);
      localparam logic [WT-1:0] R2 = allow_mask_r(4, K);
      localparam logic [WT-1:0] R3 = allow_mask_r(8, K);

      for (gb = 0; gb < WT; gb = gb + 1) begin : g_bit
        localparam int S = gb / SLOTW;
        // The masks are elaboration constants: whether this bit can
        // reach its left or right source in each mode is known now, and
        // Vivado folds the AM[mode] selects (measured: writing the
        // folded cases out by hand changed nothing - 5,269 LUT either
        // way). Three outcomes per direction: not shifting passes
        // through, shifting takes from the source, shifting ACROSS A
        // BOUNDARY fills zero - and collapsing the last two into one
        // enable is the mistake that leaks a neighbour's unshifted
        // bits.
        localparam bit [3:0] AML = {A3[gb], A2[gb], A1[gb], A0[gb]};
        localparam bit [3:0] AMR = {R3[gb], R2[gb], R1[gb], R0[gb]};
        logic sl, sr;
        if (gb >= SH) begin : g_sl
          assign sl = AML[mode] ? cs[gk][gb-SH] : 1'b0;
        end else begin : g_sl0
          assign sl = 1'b0;    // below the ladder base: zero-fill
        end
        if (BIDIR && (gb + SH < WT)) begin : g_sr
          assign sr = AMR[mode] ? cs[gk][gb+SH] : 1'b0;
        end else begin : g_sr0
          assign sr = 1'b0;    // above the top, or a left-only ladder
        end
        assign cs[gk+1][gb] = slot_hi[S][K-LO]
                                ? (slot_dhi[S] ? sr : sl)
                                : cs[gk][gb];
      end
    end

    // ---- fine: stages 0..5 -----------------------------------------
    for (gk = 0; gk < LO; gk = gk + 1) begin : g_lo
      localparam int K  = gk;
      localparam int SH = 1 << K;
      localparam logic [WT-1:0] A0 = allow_mask(1, K);
      localparam logic [WT-1:0] A1 = allow_mask(2, K);
      localparam logic [WT-1:0] A2 = allow_mask(4, K);
      localparam logic [WT-1:0] A3 = allow_mask(8, K);

      localparam logic [WT-1:0] R0 = allow_mask_r(1, K);
      localparam logic [WT-1:0] R1 = allow_mask_r(2, K);
      localparam logic [WT-1:0] R2 = allow_mask_r(4, K);
      localparam logic [WT-1:0] R3 = allow_mask_r(8, K);

      for (gb = 0; gb < WT; gb = gb + 1) begin : g_bit
        localparam int S = gb / SLOTW;
        localparam bit [3:0] AML = {A3[gb], A2[gb], A1[gb], A0[gb]};
        localparam bit [3:0] AMR = {R3[gb], R2[gb], R1[gb], R0[gb]};
        logic sl, sr;
        if (gb >= SH) begin : g_sl
          assign sl = AML[mode_r] ? fs[gk][gb-SH] : 1'b0;
        end else begin : g_sl0
          assign sl = 1'b0;
        end
        if (BIDIR && (gb + SH < WT)) begin : g_sr
          assign sr = AMR[mode_r] ? fs[gk][gb+SH] : 1'b0;
        end else begin : g_sr0
          assign sr = 1'b0;
        end
        assign fs[gk+1][gb] = slot_lo[S][K]
                                ? (slot_dlo[S] ? sr : sl)
                                : fs[gk][gb];
      end
    end
  endgenerate

  // Two registers, at exactly the pipe's S11 -> S12 -> S13 boundaries.
  always_ff @(posedge clk) begin
    cs_r <= cs[SPLIT];
    dout <= fs[LO];
  end

endmodule
