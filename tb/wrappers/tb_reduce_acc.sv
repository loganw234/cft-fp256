// Copyright 2026 Logan W.
// SPDX-License-Identifier: Apache-2.0
//
// cft_reduce_acc wired to a real adder: one cft_fpfma_pipe steered the
// way cft_opmux steers ADD, fma(x, 1.0, y), which is what the engine
// would hand it. The product x*1.0 is exact, so the pipe delivers
// round(x+y) - the model's add() - and its LATENCY is the accumulator's
// ADD_LATENCY by construction.

`timescale 1ns/1ps

module tb_reduce_acc #(
    parameter int LEVELS  = 40,
    parameter int LATENCY = 15
) (
    input  logic        clk,
    input  logic        rst_n,
    input  logic        clear,
    input  logic [2:0]  rnd,

    input  logic        in_valid,
    input  logic [31:0] in_data,
    output logic        in_ready,

    input  logic        flush,

    output logic        out_valid,
    output logic [31:0] out_data,
    output logic [4:0]  out_flags
);

  localparam logic [31:0] FP32_ONE = 32'h3F80_0000;

  logic        add_valid;
  logic [31:0] add_a, add_b, add_res;
  logic [4:0]  add_flags;

  cft_reduce_acc #(.W(32), .LEVELS(LEVELS), .ADD_LATENCY(LATENCY)) u_acc (
      .clk(clk), .rst_n(rst_n), .clear(clear),
      .in_valid(in_valid), .in_data(in_data), .in_ready(in_ready),
      .flush(flush),
      .add_valid(add_valid), .add_a(add_a), .add_b(add_b),
      .add_res(add_res), .add_flags(add_flags),
      .out_valid(out_valid), .out_data(out_data), .out_flags(out_flags));

  cft_fpfma_pipe #(.EXP_W(8), .MAN_W(23), .LATENCY(LATENCY),
                   .EXT_MUL(1'b0)) u_add (
      .clk(clk), .rst_n(rst_n),
      .in_valid(add_valid), .rnd(rnd),
      .byp(1'b0), .byp_d('0), .byp_f('0),
      .a(add_a), .b(FP32_ONE), .c(add_b),
      .out_valid(), .d(add_res), .flags(add_flags),
      .mul_a(), .mul_b(), .mul_p('0),
          .nrm_v(), .nrm_csh(), .nrm_fsh(), .nrm_d('0),
          .aln_v(), .aln_csh(), .aln_fsh(), .aln_dir(), .aln_d('0));

endmodule
