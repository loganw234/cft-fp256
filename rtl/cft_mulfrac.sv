// Copyright 2026 Logan W.
// SPDX-License-Identifier: Apache-2.0
//
// cft_mulfrac: the fractured significand array.
//
// One physical partial-product array computing, per beat and by mode:
//
//     mode 0   8 x (24 x 24)      fp32
//     mode 1   4 x (53 x 53)      fp64
//     mode 2   2 x (113 x 113)    fp128
//     mode 3   1 x (237 x 237)    fp256
//
// This replaces four independent per-format multipliers with one, and
// it is the roadmap's "fused significand array". The four-bank design
// is its behavioural spec: this is only allowed to ship when it
// produces identical bits.
//
// WHY THE SLOTS LINE UP AT ALL
//
// The existing pipe already decomposes a P x P multiply into chunk
// columns: pp[k] = ma * mb[k*MCH +: MCH]. Chunk count is
// ceil(P/MCH) per lane, and lane count is 256/width, so the total slot
// demand per mode is fixed by MCH alone:
//
//     MCH = 24        MCH = 27
//     fp32   8         8
//     fp64  12         8
//     fp128 10        10
//     fp256 10         9
//
// 27 is the better number twice over: it needs ten slots rather than
// twelve, and it is the DSP48E2's native multiplicand width, so a slot
// maps onto the primitive instead of straddling it. Ten slots of
// 237x27 is about what the fp256 bank already spends - which is the
// whole point. The array costs what the widest rung costs and serves
// every rung.
//
// WHY THE REDUCTION TREE HAS NO SHIFTS IN IT
//
// The obvious fractured tree is mode-dependent: sum within a lane,
// never across. That is fiddly and it is unnecessary.
//
// A P x P product is at most 2P bits and lane L's result is placed at
// L*2P, so lanes occupy DISJOINT bit ranges of the accumulator and no
// lane's sum can carry into its neighbour's field - the value that
// would have to overflow is a product that already fits exactly. So
// every slot can be shifted into its final position up front and the
// tree becomes a plain 16-to-1 sum with no shifts and no mode
// awareness at all. The mode-dependence collapses into one 4:1 mux per
// slot at S2, on constants known at elaboration.
//
// That is the trick this module is built around, and it is worth
// stating plainly because it is what keeps the fracture cheap.
//
// LATENCY is 5 (S2 products, then four tree levels), matching the
// multiplier segment of cft_fpfma_pipe exactly, so this drops into
// that pipeline without moving any other stage.

`timescale 1ns/1ps

module cft_mulfrac #(
    parameter int PMAX  = 237,   // widest significand (fp256, 1 + MAN_W)
    parameter int MCH   = 27,    // chunk width; DSP48E2 multiplicand
    parameter int SLOTS = 16     // physical partial-product slots
) (
    input  logic                    clk,
    input  logic [1:0]              mode,   // 0 fp32, 1 fp64, 2 fp128, 3 fp256
    input  logic                    in_valid,
    // Lane significands packed at their natural width, low lane first.
    // Every mode's packing fits in PMAX bits: 8*24=192, 4*53=212,
    // 2*113=226, 1*237=237.
    input  logic [PMAX-1:0]         a,
    input  logic [PMAX-1:0]         b,
    output logic                    out_valid,
    // Lane products packed at 2*width, low lane first.
    output logic [2*PMAX+2*MCH-1:0] p
);

  localparam int ACCW = 2 * PMAX + 2 * MCH;

  // ---- per-mode geometry --------------------------------------------
  // Significand width, lane count and chunks per lane. These are the
  // interchange formats, not knobs: 256/width lanes per beat.
  localparam int PW0 = 24,  LN0 = 8, NC0 = (PW0 + MCH - 1) / MCH;  // fp32
  localparam int PW1 = 53,  LN1 = 4, NC1 = (PW1 + MCH - 1) / MCH;  // fp64
  localparam int PW2 = 113, LN2 = 2, NC2 = (PW2 + MCH - 1) / MCH;  // fp128
  localparam int PW3 = 237, LN3 = 1, NC3 = (PW3 + MCH - 1) / MCH;  // fp256

  // ---- elaboration guards -------------------------------------------
  //
  // Generate scope AND initial, for the reason cft_fpfma_pipe's guards
  // spell out: Vivado and Yosys honour the elaboration-time $error and
  // ignore `initial`; Icarus is the reverse. One form alone leaves some
  // toolchain able to build a design that silently drops products.
  generate
    if (LN0 * NC0 > SLOTS || LN1 * NC1 > SLOTS ||
        LN2 * NC2 > SLOTS || LN3 * NC3 > SLOTS) begin : g_slots_short
      $error("cft_mulfrac: SLOTS too small for some mode's lane x chunk demand");
    end
    if (LN0 * PW0 > PMAX || LN1 * PW1 > PMAX ||
        LN2 * PW2 > PMAX || LN3 * PW3 > PMAX) begin : g_pack_overflow
      $error("cft_mulfrac: a mode's packed lanes do not fit in PMAX bits");
    end
    if (PW3 != PMAX) begin : g_pmax_mismatch
      $error("cft_mulfrac: PMAX must equal the fp256 significand width");
    end
  endgenerate

  initial begin
    if (LN0 * NC0 > SLOTS || LN1 * NC1 > SLOTS ||
        LN2 * NC2 > SLOTS || LN3 * NC3 > SLOTS) begin
      $display("FATAL: cft_mulfrac needs %0d slots (fp32 %0d, fp64 %0d, fp128 %0d, fp256 %0d), has %0d",
               LN1 * NC1, LN0 * NC0, LN1 * NC1, LN2 * NC2, LN3 * NC3, SLOTS);
      $finish;
    end
    if (LN0 * PW0 > PMAX || LN1 * PW1 > PMAX ||
        LN2 * PW2 > PMAX || LN3 * PW3 > PMAX) begin
      $display("FATAL: cft_mulfrac packed lanes exceed PMAX=%0d", PMAX);
      $finish;
    end
  end

  // ---- S2: products, pre-shifted into their final lane position -----
  logic [ACCW-1:0] s2_pp [0:SLOTS-1];

  genvar gk;
  generate
    for (gk = 0; gk < SLOTS; gk = gk + 1) begin : g_slot

      // Geometry of THIS slot under each mode, all elaboration
      // constants. lane = which lane owns the slot, ci = which chunk of
      // that lane's multiplier it is.
      localparam int L0 = gk / NC0, C0 = gk % NC0;
      localparam int L1 = gk / NC1, C1 = gk % NC1;
      localparam int L2 = gk / NC2, C2 = gk % NC2;
      localparam int L3 = gk / NC3, C3 = gk % NC3;

      localparam bit V0 = (L0 < LN0);
      localparam bit V1 = (L1 < LN1);
      localparam bit V2 = (L2 < LN2);
      localparam bit V3 = (L3 < LN3);

      // Where this slot's contribution lands: chunk offset inside the
      // lane's product, plus the lane's own offset in the packed
      // output. Lane products are 2*PW wide and adjacent.
      localparam int S0 = C0 * MCH + L0 * 2 * PW0;
      localparam int S1 = C1 * MCH + L1 * 2 * PW1;
      localparam int S2S= C2 * MCH + L2 * 2 * PW2;
      localparam int S3 = C3 * MCH + L3 * 2 * PW3;

      // Operand slices. The multiplicand is the whole lane; the chunk
      // is MCH bits of the multiplier, zero-filled where the lane runs
      // out - a chunk must never reach into the next lane's bits.
      localparam int AO0 = L0 * PW0, AO1 = L1 * PW1;
      localparam int AO2 = L2 * PW2, AO3 = L3 * PW3;

      localparam int BO0 = L0 * PW0 + C0 * MCH;
      localparam int BO1 = L1 * PW1 + C1 * MCH;
      localparam int BO2 = L2 * PW2 + C2 * MCH;
      localparam int BO3 = L3 * PW3 + C3 * MCH;

      // Valid bits remaining in the lane at this chunk.
      localparam int BN0 = (PW0 - C0 * MCH > MCH) ? MCH : PW0 - C0 * MCH;
      localparam int BN1 = (PW1 - C1 * MCH > MCH) ? MCH : PW1 - C1 * MCH;
      localparam int BN2 = (PW2 - C2 * MCH > MCH) ? MCH : PW2 - C2 * MCH;
      localparam int BN3 = (PW3 - C3 * MCH > MCH) ? MCH : PW3 - C3 * MCH;

      // A slot a mode does not use has a lane index past that mode's
      // lane count, and its offsets point past the end of the operand.
      // The `if (V*)` in each arm below keeps such a slot from ever
      // being READ in that mode, but the slice constants are
      // elaborated regardless, and Verilator's SELRANGE gate - fatal
      // in this project's flow - refuses a select it can prove is out
      // of range even in an arm that cannot execute (84 warnings, all
      // here, on 2026-09-02). So the dead arm's offsets are clamped to
      // zero at elaboration: nothing changes for a live slot, and a
      // dead slot's unread slice is now a legal one.
      localparam int AO0c = V0 ? AO0 : 0, BO0c = V0 ? BO0 : 0;
      localparam int AO1c = V1 ? AO1 : 0, BO1c = V1 ? BO1 : 0;
      localparam int AO2c = V2 ? AO2 : 0, BO2c = V2 ? BO2 : 0;
      localparam int AO3c = V3 ? AO3 : 0, BO3c = V3 ? BO3 : 0;

      logic [PMAX-1:0] aop;
      logic [MCH-1:0]  bch;
      logic [PMAX+MCH-1:0] prod;

      // One 4:1 mux per operand, on elaboration constants. This is the
      // entire runtime cost of being fractured.
      always_comb begin
        aop = '0;
        bch = '0;
        case (mode)
          2'd0: if (V0) begin
                  aop = {{(PMAX - PW0){1'b0}}, a[AO0c +: PW0]};
                  bch = {{(MCH - BN0){1'b0}}, b[BO0c +: BN0]};
                end
          2'd1: if (V1) begin
                  aop = {{(PMAX - PW1){1'b0}}, a[AO1c +: PW1]};
                  bch = {{(MCH - BN1){1'b0}}, b[BO1c +: BN1]};
                end
          2'd2: if (V2) begin
                  aop = {{(PMAX - PW2){1'b0}}, a[AO2c +: PW2]};
                  bch = {{(MCH - BN2){1'b0}}, b[BO2c +: BN2]};
                end
          default: if (V3) begin
                  aop = a[AO3c +: PW3];
                  bch = {{(MCH - BN3){1'b0}}, b[BO3c +: BN3]};
                end
        endcase
      end

      assign prod = aop * bch;

      // Zero-extended by concatenation rather than a size cast: Icarus
      // is uneven about ACCW'(x), and this file has to elaborate in
      // Icarus, Yosys and Vivado alike.
      logic [ACCW-1:0] prod_w;
      assign prod_w = {{(ACCW - PMAX - MCH){1'b0}}, prod};

      always_ff @(posedge clk) begin
        case (mode)
          2'd0:    s2_pp[gk] <= V0 ? (prod_w << S0)  : {ACCW{1'b0}};
          2'd1:    s2_pp[gk] <= V1 ? (prod_w << S1)  : {ACCW{1'b0}};
          2'd2:    s2_pp[gk] <= V2 ? (prod_w << S2S) : {ACCW{1'b0}};
          default: s2_pp[gk] <= V3 ? (prod_w << S3)  : {ACCW{1'b0}};
        endcase
      end
    end
  endgenerate

  // ---- S3..S6: plain reduction tree, no shifts ----------------------
  //
  // Shifts were applied at S2, so this is a straight sum. Lanes cannot
  // interfere: their fields are disjoint and each holds a product that
  // fits exactly.
  logic [ACCW-1:0] s3_q [0:7];
  logic [ACCW-1:0] s4_t [0:3];
  logic [ACCW-1:0] s5_u [0:1];
  logic [ACCW-1:0] s6_p;

  always_ff @(posedge clk) begin : tree
    for (int j = 0; j < 8; j = j + 1)
      s3_q[j] <= s2_pp[2*j] + s2_pp[2*j + 1];
    for (int i = 0; i < 4; i = i + 1)
      s4_t[i] <= s3_q[2*i] + s3_q[2*i + 1];
    for (int i = 0; i < 2; i = i + 1)
      s5_u[i] <= s4_t[2*i] + s4_t[2*i + 1];
    s6_p <= s5_u[0] + s5_u[1];
  end

  assign p = s6_p;

  // ---- valid, matched to the 5-stage depth --------------------------
  localparam int DEPTH = 5;
  logic [DEPTH-1:0] v;
  always_ff @(posedge clk) v <= {v[DEPTH-2:0], in_valid};
  assign out_valid = v[DEPTH-1];

endmodule
