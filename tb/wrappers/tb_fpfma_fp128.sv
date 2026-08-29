// Copyright 2026 Logan W.
// SPDX-License-Identifier: Apache-2.0
// cocotb top: fp128 instantiation of the FMA pipe. A fixed-parameter
// wrapper per format keeps parameter overrides out of the simulator
// command line, which is the part that differs between simulators.

`timescale 1ns/1ps

module tb_fpfma_fp128 (
    input  logic         clk,
    input  logic         rst_n,
    input  logic         in_valid,
    input  logic [2:0]   rnd,
    input  logic [127:0] a,
    input  logic [127:0] b,
    input  logic [127:0] c,
    output logic         out_valid,
    output logic [127:0] d,
    output logic [4:0]   flags
);
  cft_fpfma_pipe #(.EXP_W(15), .MAN_W(112), .LATENCY(15)) u_dut (
      .clk(clk), .rst_n(rst_n), .in_valid(in_valid), .rnd(rnd),
      .a(a), .b(b), .c(c),
      .out_valid(out_valid), .d(d), .flags(flags));
endmodule
