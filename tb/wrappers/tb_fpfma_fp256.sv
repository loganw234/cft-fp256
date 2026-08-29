// Copyright 2026 Logan W.
// SPDX-License-Identifier: Apache-2.0
// cocotb top: fp256 instantiation of the FMA pipe.

`timescale 1ns/1ps

module tb_fpfma_fp256 (
    input  logic         clk,
    input  logic         rst_n,
    input  logic         in_valid,
    input  logic [2:0]   rnd,
    input  logic [255:0] a,
    input  logic [255:0] b,
    input  logic [255:0] c,
    output logic         out_valid,
    output logic [255:0] d,
    output logic [4:0]   flags
);
  cft_fpfma_pipe #(.EXP_W(19), .MAN_W(236), .LATENCY(15)) u_dut (
      .clk(clk), .rst_n(rst_n), .in_valid(in_valid), .rnd(rnd),
      .a(a), .b(b), .c(c),
      .out_valid(out_valid), .d(d), .flags(flags));
endmodule
