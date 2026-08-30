// Copyright 2026 Logan W.
// SPDX-License-Identifier: Apache-2.0
//
// cft_opmux: operand steering. ADD, SUB and MUL are the one FMA core
// with steered operands - the same mapping as cft_golden.softfloat
// steer(), which the steering-composition self-test proves equivalent
// to the direct IEEE definitions, signed zeros and specials included:
//
//   FMA: d = a*b + c
//   ADD: d = a + c        b := 1.0
//   SUB: d = a - c        b := 1.0, c sign-flipped
//   MUL: d = a*b          c := zero with sign(a)^sign(b), preserving
//                         the sign of an exact zero product
//
// Change this table only together with softfloat.steer and the docs.

`timescale 1ns/1ps

module cft_opmux #(
    parameter int EXP_W = 8,
    parameter int MAN_W = 23
) (
    input  logic [7:0]           op,
    input  logic [EXP_W+MAN_W:0] a,
    input  logic [EXP_W+MAN_W:0] b,
    input  logic [EXP_W+MAN_W:0] c,
    output logic [EXP_W+MAN_W:0] fa,
    output logic [EXP_W+MAN_W:0] fb,
    output logic [EXP_W+MAN_W:0] fc
);

  localparam int W    = 1 + EXP_W + MAN_W;
  localparam int BIAS = (1 << (EXP_W - 1)) - 1;

  localparam logic [7:0] OP_FMA = 8'd0;
  localparam logic [7:0] OP_ADD = 8'd1;
  localparam logic [7:0] OP_SUB = 8'd2;
  localparam logic [7:0] OP_MUL = 8'd3;

  logic [EXP_W-1:0] bias_f;
  logic [W-1:0]     one;
  assign bias_f = BIAS;
  assign one = {1'b0, bias_f, {MAN_W{1'b0}}};

  always_comb begin
    fa = a;
    fb = b;
    fc = c;
    case (op)
      OP_ADD: begin
        fb = one;
      end
      OP_SUB: begin
        fb = one;
        fc = {~c[W-1], c[W-2:0]};
      end
      OP_MUL: begin
        fc = {a[W-1] ^ b[W-1], {(W-1){1'b0}}};
      end
      // Every other opcode is not arithmetic: cft_simpleops
      // computes it and the pipe delivers that result instead,
      // so what these operands steer to is irrelevant.
      default: ;  // OP_FMA and the non-arithmetic opcodes
    endcase
  end

endmodule
