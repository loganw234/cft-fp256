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
// 0..63, so the concatenation {csh, fsh} IS the total amount and the
// ten stages split at exactly the pipe's own register boundary:
// stages 6..9 (64, 128, 256, 512) are the coarse stage, stages 0..5
// (1, 2, 4, 8, 16, 32) are the fine one. Latency is 2, matching
// S11 -> S12, so nothing else in the pipeline moves.
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
    parameter int WT    = SLOTS * SLOTW
) (
    input  logic             clk,
    input  logic [1:0]       mode,          // 0 fp32, 1 fp64, 2 fp128, 3 fp256
    input  logic [WT-1:0]    din,           // lanes packed at slot pitch
    input  logic [3:0]       csh [0:SLOTS-1],   // coarse, in 64-bit granules
    input  logic [5:0]       fsh [0:SLOTS-1],   // fine, 0..63
    output logic [WT-1:0]    dout
);

  localparam int NST  = 10;                 // 2^9 = 512 covers 717
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
  endgenerate

  initial begin
    if (NW0 > SLOTW || NW1 > 2*SLOTW || NW2 > 4*SLOTW || NW3 > WT) begin
      $display("FATAL: cft_normseg slot geometry cannot hold a window (SLOTW=%0d WT=%0d)",
               SLOTW, WT);
      $finish;
    end
  end

  // The fine amount and the mode TRAVEL WITH THE DATA. The coarse
  // stage consumes csh in the cycle the operand arrives; the fine
  // stage runs a cycle later and must use that operand's fsh, not
  // whatever is on the port by then. cft_fpfma_pipe does this by
  // registering s11_fine and reading it in S12, and a shared shifter
  // has to do the same or it silently mixes two operations' shifts
  // whenever the amounts change cycle to cycle.
  //
  // The mode is registered for the same reason. In the engine it is
  // constant for a whole run - prec_r cannot move while anything is in
  // flight - so this costs two flip-flops and buys independence from
  // that argument.
  logic [5:0] fsh_r [0:SLOTS-1];
  logic [1:0] mode_r;
  always_ff @(posedge clk) begin
    for (int l = 0; l < SLOTS; l++) fsh_r[l] <= fsh[l];
    mode_r <= mode;
  end

  // Per slot, the amount of the lane that owns it. Slot s belongs to
  // lane s >> mode, which is the whole benefit of the uniform pitch:
  // this is eighty 4:1 muxes, and it is the entire runtime cost of
  // being segmented.
  logic [3:0] slot_csh [0:SLOTS-1];
  logic [5:0] slot_fsh [0:SLOTS-1];
  always_comb begin
    for (int s = 0; s < SLOTS; s++) begin
      slot_csh[s] = csh[s >> mode];
      slot_fsh[s] = fsh_r[s >> mode_r];
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
  logic [WT-1:0] cs [0:4];
  logic [WT-1:0] fs [0:6];
  /* verilator lint_on UNOPTFLAT */
  logic [WT-1:0] cs_r;

  assign cs[0] = din;
  assign fs[0] = cs_r;

  genvar gk, gb;
  generate
    // ---- coarse: stages 6..9, the 64-granule half ------------------
    for (gk = 0; gk < 4; gk = gk + 1) begin : g_coarse
      localparam int K  = 6 + gk;
      localparam int SH = 1 << K;
      localparam logic [WT-1:0] A0 = allow_mask(1, K);
      localparam logic [WT-1:0] A1 = allow_mask(2, K);
      localparam logic [WT-1:0] A2 = allow_mask(4, K);
      localparam logic [WT-1:0] A3 = allow_mask(8, K);

      for (gb = 0; gb < WT; gb = gb + 1) begin : g_bit
        localparam int S = gb / SLOTW;
        // The four masks are elaboration constants, so whether this bit
        // needs a boundary gate at all is known now, and the three cases
        // are split out explicitly.
        //
        // This is for the reader, NOT for area. It was written to
        // recover the gap between this ladder at 0.73 LUT per stage-bit
        // and a plain shifter at 0.46, on the theory that selecting the
        // whole 720-bit mask with a case(mode) hid the constants from
        // the optimiser. It did not: measured before and after, the
        // module is 5,269 LUT either way. Vivado folds the masks
        // regardless, and the 1.6x is what segmentation actually costs.
        localparam bit [3:0] AM = {A3[gb], A2[gb], A1[gb], A0[gb]};
        if (gb < SH) begin : g_below
          // The source is below the ladder's own base, so a stage that
          // shifts fills zero here and a stage that does not passes
          // through.
          assign cs[gk+1][gb] = slot_csh[S][K-6] ? 1'b0 : cs[gk][gb];
        end else if (AM == 4'b1111) begin : g_free
          // Interior in every mode: a plain 2:1 mux, no gate.
          assign cs[gk+1][gb] = slot_csh[S][K-6] ? cs[gk][gb-SH]
                                                 : cs[gk][gb];
        end else if (AM == 4'b0000) begin : g_edge
          // Crosses a boundary in every mode: the source is never
          // reachable, so shifting always fills zero.
          assign cs[gk+1][gb] = slot_csh[S][K-6] ? 1'b0 : cs[gk][gb];
        end else begin : g_mux
          // Mode-dependent. Three cases, not two: not shifting passes
          // through; shifting takes from below; shifting ACROSS A
          // BOUNDARY fills zero. Collapsing the last two into one
          // enable is the obvious mistake and it leaks the neighbour's
          // unshifted bits.
          assign cs[gk+1][gb] = slot_csh[S][K-6]
                                  ? (AM[mode] ? cs[gk][gb-SH] : 1'b0)
                                  : cs[gk][gb];
        end
      end
    end

    // ---- fine: stages 0..5 -----------------------------------------
    for (gk = 0; gk < 6; gk = gk + 1) begin : g_fine
      localparam int K  = gk;
      localparam int SH = 1 << K;
      localparam logic [WT-1:0] A0 = allow_mask(1, K);
      localparam logic [WT-1:0] A1 = allow_mask(2, K);
      localparam logic [WT-1:0] A2 = allow_mask(4, K);
      localparam logic [WT-1:0] A3 = allow_mask(8, K);

      for (gb = 0; gb < WT; gb = gb + 1) begin : g_bit
        localparam int S = gb / SLOTW;
        localparam bit [3:0] AM = {A3[gb], A2[gb], A1[gb], A0[gb]};
        if (gb < SH) begin : g_below
          assign fs[gk+1][gb] = slot_fsh[S][K] ? 1'b0 : fs[gk][gb];
        end else if (AM == 4'b1111) begin : g_free
          assign fs[gk+1][gb] = slot_fsh[S][K] ? fs[gk][gb-SH]
                                               : fs[gk][gb];
        end else if (AM == 4'b0000) begin : g_edge
          assign fs[gk+1][gb] = slot_fsh[S][K] ? 1'b0 : fs[gk][gb];
        end else begin : g_mux
          assign fs[gk+1][gb] = slot_fsh[S][K]
                                  ? (AM[mode_r] ? fs[gk][gb-SH] : 1'b0)
                                  : fs[gk][gb];
        end
      end
    end
  endgenerate

  // Two registers, at exactly the pipe's S11 -> S12 -> S13 boundaries.
  always_ff @(posedge clk) begin
    cs_r <= cs[4];
    dout <= fs[6];
  end

endmodule
