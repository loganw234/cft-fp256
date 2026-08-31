// Copyright 2026 Logan W.
// SPDX-License-Identifier: Apache-2.0
// cocotb top: fp256 instantiation of the FMA pipe.

`timescale 1ns/1ps

module tb_fpfma_fp256 (
    input  logic         clk,
    input  logic         rst_n,
    input  logic         in_valid,
    input  logic [2:0]   rnd,
    input  logic [7:0]   op,
    input  logic [255:0] a,
    input  logic [255:0] b,
    input  logic [255:0] c,
    output logic         out_valid,
    output logic [255:0] d,
    output logic [4:0]   flags
);
  logic bv; logic [255:0] bd; logic [4:0] bf;
  cft_simpleops #(.EXP_W(19), .MAN_W(236)) u_simple (
      .op(op), .a(a), .b(b), .c(c), .valid(bv), .d(bd), .flags(bf));
  cft_fpfma_pipe #(.EXP_W(19), .MAN_W(236), .LATENCY(15)) u_dut (
      .clk(clk), .rst_n(rst_n), .in_valid(in_valid), .rnd(rnd), .byp(bv), .byp_d(bd), .byp_f(bf),
      .a(a), .b(b), .c(c),
      .out_valid(out_valid), .d(d), .flags(flags),
      // EXT_MUL defaults off, so these are inert - but a pin
      // that is not named is fatal to Verilator, and that is
      // what kept `make SIM=verilator` from ever running.
      .mul_a(), .mul_b(), .mul_p('0),
          .nrm_v(), .nrm_csh(), .nrm_fsh(), .nrm_d('0),
          .aln_v(), .aln_csh(), .aln_fsh(), .aln_dir(), .aln_d('0));
endmodule
