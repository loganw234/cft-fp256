// Copyright 2026 Logan W.
// SPDX-License-Identifier: Apache-2.0
//
// tb_seedop: the seed opcodes at all four rungs from one operand word,
// compared against the golden model by the cocotb side. Combinational,
// like the module: no clock, drive and settle.

`timescale 1ns/1ps

module tb_seedop (
    input  logic [7:0]   op,
    input  logic [255:0] a,
    output logic         v32,
    output logic [31:0]  d32,
    output logic         v64,
    output logic [63:0]  d64,
    output logic         v128,
    output logic [127:0] d128,
    output logic         v256,
    output logic [255:0] d256
);

  cft_seedop #(.EXP_W(8),  .MAN_W(23))  u32  (.op(op), .a(a[31:0]),
                                              .valid(v32),  .d(d32));
  cft_seedop #(.EXP_W(11), .MAN_W(52))  u64  (.op(op), .a(a[63:0]),
                                              .valid(v64),  .d(d64));
  cft_seedop #(.EXP_W(15), .MAN_W(112)) u128 (.op(op), .a(a[127:0]),
                                              .valid(v128), .d(d128));
  cft_seedop #(.EXP_W(19), .MAN_W(236)) u256 (.op(op), .a(a),
                                              .valid(v256), .d(d256));

endmodule
