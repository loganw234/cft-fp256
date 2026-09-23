// Copyright 2026 Logan W.
// SPDX-License-Identifier: Apache-2.0
//
// cft_imul: IMUL (opcode 30) with its multiply registered, beside a lane.
//
// IMUL is the low 32 bits of the product of the operands' low 32 bits,
// zero-extended to the format; cft_simpleops.sv carries the definition
// and the partial-product argument, and its combinational form stays
// the reference its own bench and proofs hold. Computed there inside a
// lane, it is three DSP48s chained in combinational mode on the path
// from the operand FIFO's block RAM to the pipe's stage-0 bypass
// register - the path that set a Kintex-7 325T's clock at about 82 MHz
// on 2026-09-23, where the tree before IMUL closed 100
// (docs/VALIDATION.md). Here the same three partial products are
// formed from REGISTERED operands and summed a level later, so no
// level holds more than one multiply or one pair of adds.
//
// The product has to reach the lane's result at the level the pipe's
// would, and the pipe takes its bypass result at stage 0, so this
// module keeps its own copy of the pipe's level count: a marker enters
// at level 0 with the operands - the same edge, the same `en` as the
// pipe's input registers - and both travel DEPTH levels. At level
// DEPTH-1, the pipe's output register (its valid line reads v[DEPTH-1]
// there), `out_v` says the lane's result is this product rather than
// the pipe's, which carried only cft_simpleops' placeholder through
// the bypass sideband (IMUL_EXT). The flags need no help: an integer
// opcode raises none, and the pipe delivers the sideband's zeros.
//
// Levels: 0 the operands, 1 the partial products, 2 the sum, then a
// delay line to DEPTH-1 with no reset (shift-register shaped). The
// marker line is reset like the pipe's valid line, so no stale marker
// outlives a reset.
module cft_imul #(
    parameter int DEPTH = 16
) (
    input  logic        clk,
    input  logic        rst_n,
    input  logic        en,
    input  logic        issue,     // the lane accepts an operation this cycle
    input  logic [7:0]  op,
    input  logic [31:0] a,         // the operands' low 32 bits
    input  logic [31:0] b,
    output logic        out_v,     // level DEPTH-1 holds an IMUL
    output logic [31:0] out_p      // and this is its product
);
  // python/cft_golden/softfloat.py: OP_IMUL = 30, as in cft_simpleops.
  localparam logic [7:0] OP_IMUL = 8'd30;

  generate
    if (DEPTH < 3) begin : g_bad_depth
      $error("cft_imul: DEPTH must leave levels 0-2 for the product");
    end
  endgenerate

  logic [DEPTH-1:0] v;
  always_ff @(posedge clk) begin
    if (!rst_n)  v <= '0;
    else if (en) v <= {v[DEPTH-2:0], issue && (op == OP_IMUL)};
  end
  assign out_v = v[DEPTH-1];

  // al*bl + ((al*bh + ah*bl) << 16), exactly cft_simpleops' algebra: the
  // fourth partial product lands at bit 32 and above and is not formed,
  // and only the low 16 bits of the middle terms survive the shift.
  logic [31:0] a0, b0;            // level 0
  logic [31:0] ll1;               // level 1: al*bl
  logic [15:0] lh1, hl1;          //          low halves of al*bh, ah*bl
  logic [31:0] p [2:DEPTH-1];     // level 2 onward: the product
  always_ff @(posedge clk) begin
    if (en) begin
      a0   <= a;
      b0   <= b;
      ll1  <= 32'(a0[15:0] * b0[15:0]);
      lh1  <= 16'(a0[15:0] * b0[31:16]);
      hl1  <= 16'(a0[31:16] * b0[15:0]);
      p[2] <= ll1 + {16'(lh1 + hl1), 16'b0};
      for (int k = 3; k < DEPTH; k++) p[k] <= p[k-1];
    end
  end
  assign out_p = p[DEPTH-1];
endmodule
