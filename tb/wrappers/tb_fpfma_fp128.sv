// Copyright 2026 Logan W.
// SPDX-License-Identifier: Apache-2.0
// cocotb top: fp128 instantiation of the FMA pipe. MUL_PASSES paces the
// pipe the way cft_lanes would at that budget - see tb_fpfma_fp32.sv.

`timescale 1ns/1ps

module tb_fpfma_fp128 #(
    parameter int MUL_PASSES = 1
) (
    input  logic         clk,
    input  logic         rst_n,
    input  logic         in_valid,
    input  logic [2:0]   rnd,
    input  logic [7:0]   op,
    input  logic [127:0] a,
    input  logic [127:0] b,
    input  logic [127:0] c,
    output logic         in_ready,
    output logic         out_valid,
    output logic [127:0] d,
    output logic [4:0]   flags
);
  `include "cft_mulgeom.svh"
  localparam int NP  = cft_mul_passes(112 + 1, MUL_PASSES);
  localparam int PHW = (NP > 1) ? $clog2(NP) : 1;
  logic [PHW-1:0] ph;
  logic           en;
  always_ff @(posedge clk) begin
    if (!rst_n)                       ph <= '0;
    else if (ph >= PHW'(NP - 1))      ph <= '0;
    else                              ph <= ph + 1'b1;
  end
  assign en       = (ph >= PHW'(NP - 1));
  assign in_ready = en;

  logic bv; logic [127:0] bd; logic [4:0] bf;
  cft_simpleops #(.EXP_W(15), .MAN_W(112)) u_simple (
      .op(op), .a(a), .b(b), .c(c), .valid(bv), .d(bd), .flags(bf));
  cft_fpfma_pipe #(.EXP_W(15), .MAN_W(112), .LATENCY(15),
                   .MUL_PASSES(MUL_PASSES), .MUL_PERIOD(NP)) u_dut (
      .clk(clk), .rst_n(rst_n), .en(en), .in_valid(in_valid), .rnd(rnd),
      .byp(bv), .byp_d(bd), .byp_f(bf),
      .a(a), .b(b), .c(c),
      .out_valid(out_valid), .d(d), .flags(flags),
      .mul_a(), .mul_b(), .mul_p('0),
          .nrm_v(), .nrm_csh(), .nrm_fsh(), .nrm_d('0),
          .aln_v(), .aln_csh(), .aln_fsh(), .aln_dir(), .aln_d('0));
endmodule
