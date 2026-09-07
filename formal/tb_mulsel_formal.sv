// Copyright 2026 Logan W.
// SPDX-License-Identifier: Apache-2.0
//
// tb_mulsel_formal: LEMMAS B and C of cft_mulpass' exactness - the
// operands the chunk columns are handed on each pass are the captured
// `a` and the right chunk group of the captured `b`, the column
// register holds their product, and a column the geometry does not
// build holds zero.
//
// tb_mulfold_formal.sv carries lemma A and the whole argument;
// formal/README.md writes the composition out. In short: A proves the
// fold delivers the weighted sum of whatever the column registers hold,
// under two side-conditions on those values; B and C prove the column
// registers hold the right products and satisfy the side-conditions.
// Neither B nor C asks a solver to reason about a multiplier: B is an
// equality between operand slices, and C's reference product is written
// from the DUT's OWN operand wires, so yosys' opt_merge folds it onto
// the DUT's own $mul cell and the claim is one register against
// another.
//
// THE PROBES
//
// Yosys gives formal code no way to name a submodule's internals -
// `bind` binds nothing and hierarchical references elaborate as fresh
// dangling wires, both recorded in formal/README.md - so the probes
// here are driven from outside the language: formal/mulexact.sby
// flattens the design and then uses yosys' `connect -set` to drive each
// `probe_*` from the corresponding `dut.*` wire. `connect` aborts on a
// name it cannot resolve, and sby's model build turns any wire left
// undriven into an unconstrained `$anyseq` (design_prep.ys:
// `setundef -undriven -anyseq`), so a probe that failed to attach shows
// up as a refuted assertion, never as a vacuous pass.
//
// THE TIMING, FROM cft_mulpass' OWN TIMELINE
//
// With E_n the enabled edge that captures operation n and `off` the
// cycle's offset from the last enabled edge (0 in [E_n, E_n+1)):
//
//   off = p+1, p = 0..NP-2   a_r = a_n,     bsel_r = group p of b_n
//   off = 0                  a_r = a_{n-1}, bsel_r = group NP-1 of b_{n-1}
//
// The second line is not an exception, it is the last pass: the DUT's
// operand registers capture pass NP-1's selection at E_n, one edge into
// the next operation's interval, which is exactly why the fold runs
// past the interval boundary and why the level chain needs the KD
// argument in the module header. The harness keeps the previous
// interval's operands (ha2/hb2) to state it. The column registers are
// one further edge behind, which is why lemma C compares the probed
// column against a registered copy of the probed operands' product.

`timescale 1ns/1ps

module tb_mulsel_formal #(
    parameter int P      = 53,
    parameter int COLS   = 1,
    // the pass count mulexact.sby expects of this geometry; 0 is not a
    // pass count, so a task that forgot to set it cannot elaborate
    parameter int EXP_NP = 0
) (
    input logic         clk,
    input logic         rst_n,
    input logic [P-1:0] a,
    input logic [P-1:0] b
);

  `include "cft_mulgeom.svh"

  localparam int MCH   = CFT_MUL_MCH;
  localparam int NMC   = cft_mul_chunks(P);
  localparam int C     = COLS;
  localparam int NP    = (NMC + C - 1) / C;
  localparam int K     = C * MCH;
  localparam int PSW   = P + K;
  localparam int PHW   = (NP > 1) ? $clog2(NP) : 1;
  localparam int OFW   = $clog2(NP + 1);
  localparam int LEVEL = 5;
  // the module's own in-pass tree depth, and the columns it reaches -
  // the same NC tb_mulfold_formal's cut covers
  localparam int L     = (C <= 1) ? 0 : (C <= 2) ? 1 : (C <= 4) ? 2 : (C <= 8) ? 3 : 4;
  localparam int NC    = 1 << L;

  generate
    if (EXP_NP != NP) begin : g_bad_geom
      $error("EXP_NP disagrees with the pass count derived from P and COLS");
    end
  endgenerate

  // ---- the reset shape: low at the first step, high after ------------
  logic past_valid = 1'b0;
  always_ff @(posedge clk) past_valid <= 1'b1;
  always_comb begin
    if (!past_valid) assume (!rst_n);
    else             assume (rst_n);
  end

  // ---- the pacer, exactly cft_lanes' ---------------------------------
  logic [PHW-1:0] ph;
  logic           en;
  always_ff @(posedge clk) begin
    if (!rst_n)                  ph <= '0;
    else if (ph >= PHW'(NP - 1)) ph <= '0;
    else                         ph <= ph + 1'b1;
  end
  assign en = rst_n && (ph >= PHW'(NP - 1));

  // ---- the S1 model, and the interval before it -----------------------
  logic [P-1:0] ha1, hb1, ha2, hb2;
  always_ff @(posedge clk) begin
    if (en) begin
      ha1 <= a;   hb1 <= b;
      ha2 <= ha1; hb2 <= hb1;
    end
  end

  logic [2*P-1:0] p;
  cft_mulpass #(.P(P), .COLS(COLS), .LEVEL(LEVEL)) dut (
      .clk(clk), .en(en), .a(ha1), .b(hb1), .p(p));

  // ---- the probes, attached by mulexact.sby's `connect -set` ----------
  (* keep *) logic [P-1:0]   probe_ar;
  (* keep *) logic [K-1:0]   probe_bsel;
  (* keep *) logic [PSW-1:0] probe_pcol0;
  (* keep *) logic [PSW-1:0] probe_pcol1;
  (* keep *) logic [PSW-1:0] probe_pcol2;
  (* keep *) logic [PSW-1:0] probe_pcol3;
  (* keep *) logic [PSW-1:0] probe_pcol4;
  (* keep *) logic [PSW-1:0] probe_pcol5;
  (* keep *) logic [PSW-1:0] probe_pcol6;
  (* keep *) logic [PSW-1:0] probe_pcol7;

  // Packed, not an unpacked array: an array assigned in one always_comb
  // is inferred as a memory and mapped to registers, so the "alias"
  // arrives a cycle late - which is a counterexample about the harness,
  // and it took one to find out.
  logic [8*PSW-1:0] pv;
  assign pv = {probe_pcol7, probe_pcol6, probe_pcol5, probe_pcol4,
               probe_pcol3, probe_pcol2, probe_pcol1, probe_pcol0};

  // ---- offset from the last enabled edge, and the edge count ----------
  logic [OFW-1:0] off;
  always_ff @(posedge clk) begin
    if (en)                  off <= '0;
    else if (off < OFW'(NP)) off <= off + 1'b1;
  end

  logic [3:0] edges;
  always_ff @(posedge clk) begin
    if (!rst_n)                  edges <= '0;
    else if (en && edges < 4'd8) edges <= edges + 1'b1;
  end

  // ---- what the operands should be ------------------------------------
  // b padded to NP+1 whole groups exactly as the module pads it, so the
  // expectation is derived from the same geometry and not restated.
  logic [(NP+1)*K-1:0] bpad1, bpad2;
  assign bpad1 = {{((NP+1)*K - P){1'b0}}, hb1};
  assign bpad2 = {{((NP+1)*K - P){1'b0}}, hb2};

  logic [P-1:0] exp_ar;
  logic [K-1:0] exp_bsel;
  always_comb begin
    if (off == '0) begin
      exp_ar   = ha2;
      exp_bsel = bpad2[(NP-1)*K +: K];
    end else begin
      exp_ar   = ha1;
      exp_bsel = bpad1[0 +: K];
      for (int j = 1; j < NP; j = j + 1)
        if (off == OFW'(j)) exp_bsel = bpad1[(j-1)*K +: K];
    end
  end

  // ---- LEMMA C's reference product ------------------------------------
  // Written from the probes - that is, from the DUT's own operand wires
  // - so this is structurally the same multiply the module performs and
  // opt_merge folds the two into one cell. Registered here the way the
  // module registers it, so the claim is register against register.
  // The assertions inside the generate carry no label: yosys names a
  // procedural assertion by its label alone, so one label would collide
  // across the unrolled scopes.
  generate
    for (genvar gc = 0; gc < NC; gc = gc + 1) begin : g_col
      if (gc < C) begin : g_built
        logic [PSW-1:0] pnow, pref;
        always_comb pnow = probe_ar * probe_bsel[gc*MCH +: MCH];
        always_ff @(posedge clk) pref <= pnow;
        always_comb begin
          if (past_valid && edges >= 4'd2)
            assert (pv[gc*PSW +: PSW] == pref);
        end
      end else begin : g_unbuilt
        // a column the tree reads but the geometry does not build: the
        // module drives it to zero, which is what lemma A assumes of it
        always_comb begin
          if (past_valid && edges >= 4'd2)
            assert (pv[gc*PSW +: PSW] == '0);
        end
      end
    end
  endgenerate

  // ---- the claims ------------------------------------------------------
  // Two enabled edges are enough for ha2/hb2 to hold a real captured
  // operand; the property then holds in every cycle, at every offset,
  // including the boundary cycle where the operand registers still carry
  // the previous interval's operation.
  always_comb begin
    if (past_valid && edges >= 4'd2) begin
      a_sel_a: assert (probe_ar   == exp_ar);
      a_sel_b: assert (probe_bsel == exp_bsel);
    end
  end

  // The range side-condition lemma A assumes of a built column: below
  // 2^(P+24), because `a` is below 2^P and a chunk below 2^24. It is
  // only expressible where the column register is wider than that, i.e.
  // where the geometry builds more than one column.
  generate
    if (PSW > P + MCH) begin : g_range
      always_comb begin
        if (past_valid && edges >= 4'd2)
          for (int c = 0; c < C; c = c + 1)
            assert (pv[c*PSW + P + MCH +: PSW - P - MCH] == '0);
      end
    end
  endgenerate

  // Non-vacuity: every pass's selection is reached, the boundary cycle
  // is reached, and the columns carry something other than zero.
  always_comb begin
    c_off0:    cover (past_valid && edges >= 4'd2 && off == '0);
    c_offlast: cover (past_valid && edges >= 4'd2 && off == OFW'(NP-1));
    c_bsel:    cover (past_valid && edges >= 4'd2 && probe_bsel != '0);
    c_pcol:    cover (past_valid && edges >= 4'd2 && pv[0 +: PSW] != '0);
  end

endmodule
