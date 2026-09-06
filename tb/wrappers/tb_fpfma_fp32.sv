// Copyright 2026 Logan W.
// SPDX-License-Identifier: Apache-2.0
// cocotb top: fp32 instantiation of the FMA pipe. A fixed-parameter
// wrapper per format keeps parameter overrides out of the simulator
// command line, which is the part that differs between simulators.
//
// MUL_PASSES is the one override the wrapper does take, so the same
// bench can score the pipe at a multi-cycle budget: the wrapper then
// paces the pipe exactly as cft_lanes would - a phase counter with the
// period the geometry include derives for this rung, `en` on its last
// cycle - and exposes that as in_ready, which the driver honours. fp32
// is single-pass at every budget, so here the period is always 1 and
// the counter is a constant; the wrapper carries the mechanism anyway
// so all four rungs' benches are one shape.

`timescale 1ns/1ps

module tb_fpfma_fp32 #(
    parameter int MUL_PASSES = 1
) (
    input  logic        clk,
    input  logic        rst_n,
    input  logic        in_valid,
    input  logic [2:0]  rnd,
    input  logic [7:0]  op,
    input  logic [31:0] a,
    input  logic [31:0] b,
    input  logic [31:0] c,
    output logic        in_ready,
    output logic        out_valid,
    output logic [31:0] d,
    output logic [4:0]  flags
);
  `include "cft_mulgeom.svh"
  localparam int NP  = cft_mul_passes(23 + 1, MUL_PASSES);
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

  logic bv; logic [31:0] bd; logic [4:0] bf;
  cft_simpleops #(.EXP_W(8), .MAN_W(23)) u_simple (
      .op(op), .a(a), .b(b), .c(c), .valid(bv), .d(bd), .flags(bf));
  cft_fpfma_pipe #(.EXP_W(8), .MAN_W(23), .LATENCY(15),
                   .MUL_PASSES(MUL_PASSES), .MUL_PERIOD(NP)) u_dut (
      .clk(clk), .rst_n(rst_n), .en(en), .in_valid(in_valid), .rnd(rnd),
      .byp(bv), .byp_d(bd), .byp_f(bf),
      .a(a), .b(b), .c(c),
      .out_valid(out_valid), .d(d), .flags(flags),
      // EXT_MUL defaults off, so these are inert - but a pin
      // that is not named is fatal to Verilator, and that is
      // what kept `make SIM=verilator` from ever running.
      .mul_a(), .mul_b(), .mul_p('0),
          .nrm_v(), .nrm_csh(), .nrm_fsh(), .nrm_d('0),
          .aln_v(), .aln_csh(), .aln_fsh(), .aln_dir(), .aln_d('0));
endmodule
