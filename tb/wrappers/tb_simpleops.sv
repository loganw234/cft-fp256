// Copyright 2026 Logan W.
// SPDX-License-Identifier: Apache-2.0
//
// tb_simpleops: the non-arithmetic block built twice, at all four
// rungs, differing only in how the answer is selected.
//
//   *_r   cft_simpleops_ref - the flat case(op) form, frozen at 7ab02b3
//   *_n   cft_simpleops     - the eight-source form that ships
//
// Both halves see identical inputs, and the bench asserts their
// outputs are equal bit for bit - d, flags and valid. All four formats
// run at once from one 256-bit operand word because the rewrite's
// costs and risks are width-dependent: the barrel shifter is SHB deep,
// the mux tree is not, and fp32 would not catch a mistake in the
// reversal that only shows up past 32 bits.
//
// Purely combinational, so there is no clock and no reset. The bench
// drives inputs, settles, and compares.

`timescale 1ns/1ps

module tb_simpleops (
    input  logic [7:0]   op,
    input  logic [255:0] a,
    input  logic [255:0] b,
    input  logic [255:0] c,

    output logic         v32_r,   v32_n,
    output logic [31:0]  d32_r,   d32_n,
    output logic [4:0]   f32_r,   f32_n,

    output logic         v64_r,   v64_n,
    output logic [63:0]  d64_r,   d64_n,
    output logic [4:0]   f64_r,   f64_n,

    output logic         v128_r,  v128_n,
    output logic [127:0] d128_r,  d128_n,
    output logic [4:0]   f128_r,  f128_n,

    output logic         v256_r,  v256_n,
    output logic [255:0] d256_r,  d256_n,
    output logic [4:0]   f256_r,  f256_n
);

  cft_simpleops_ref #(.EXP_W(8), .MAN_W(23)) u_r32 (
      .op(op), .a(a[31:0]), .b(b[31:0]), .c(c[31:0]),
      .valid(v32_r), .d(d32_r), .flags(f32_r));
  cft_simpleops     #(.EXP_W(8), .MAN_W(23)) u_n32 (
      .op(op), .a(a[31:0]), .b(b[31:0]), .c(c[31:0]),
      .valid(v32_n), .d(d32_n), .flags(f32_n));

  cft_simpleops_ref #(.EXP_W(11), .MAN_W(52)) u_r64 (
      .op(op), .a(a[63:0]), .b(b[63:0]), .c(c[63:0]),
      .valid(v64_r), .d(d64_r), .flags(f64_r));
  cft_simpleops     #(.EXP_W(11), .MAN_W(52)) u_n64 (
      .op(op), .a(a[63:0]), .b(b[63:0]), .c(c[63:0]),
      .valid(v64_n), .d(d64_n), .flags(f64_n));

  cft_simpleops_ref #(.EXP_W(15), .MAN_W(112)) u_r128 (
      .op(op), .a(a[127:0]), .b(b[127:0]), .c(c[127:0]),
      .valid(v128_r), .d(d128_r), .flags(f128_r));
  cft_simpleops     #(.EXP_W(15), .MAN_W(112)) u_n128 (
      .op(op), .a(a[127:0]), .b(b[127:0]), .c(c[127:0]),
      .valid(v128_n), .d(d128_n), .flags(f128_n));

  cft_simpleops_ref #(.EXP_W(19), .MAN_W(236)) u_r256 (
      .op(op), .a(a), .b(b), .c(c),
      .valid(v256_r), .d(d256_r), .flags(f256_r));
  cft_simpleops     #(.EXP_W(19), .MAN_W(236)) u_n256 (
      .op(op), .a(a), .b(b), .c(c),
      .valid(v256_n), .d(d256_n), .flags(f256_n));

endmodule
