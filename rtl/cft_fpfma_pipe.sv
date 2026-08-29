// Copyright 2026 Logan W.
// SPDX-License-Identifier: Apache-2.0
//
// cft_fpfma_pipe: fixed-latency registered wrapper around the
// combinational cft_fpfma core. One input register stage, the core,
// then LATENCY-1 output register stages: out_valid trails in_valid by
// exactly LATENCY cycles, always. No stalls, no backpressure - the
// engine paces issue, and a fixed pipe keeps result ordering a
// structural property rather than a protocol.
//
// v1 note: synthesis retiming cannot be expected to balance a cloud
// this deep at speed; the pipelined production core replaces cft_fpfma
// behind these exact ports, and every testbench carries over.

`timescale 1ns/1ps

module cft_fpfma_pipe #(
    parameter int EXP_W   = 8,
    parameter int MAN_W   = 23,
    parameter int LATENCY = 3
) (
    input  logic                 clk,
    input  logic                 rst_n,
    input  logic                 in_valid,
    input  logic [EXP_W+MAN_W:0] a,
    input  logic [EXP_W+MAN_W:0] b,
    input  logic [EXP_W+MAN_W:0] c,
    output logic                 out_valid,
    output logic [EXP_W+MAN_W:0] d,
    output logic [4:0]           flags
);

  localparam int W = 1 + EXP_W + MAN_W;

  logic [W-1:0] a_q, b_q, c_q;
  logic         v_q;
  logic [W-1:0] d_c;
  logic [4:0]   f_c;

  always_ff @(posedge clk) begin
    if (!rst_n) begin
      v_q <= 1'b0;
    end else begin
      v_q <= in_valid;
      a_q <= a;
      b_q <= b;
      c_q <= c;
    end
  end

  cft_fpfma #(.EXP_W(EXP_W), .MAN_W(MAN_W)) u_core (
      .a(a_q), .b(b_q), .c(c_q), .d(d_c), .flags(f_c)
  );

  generate
    if (LATENCY <= 1) begin : g_comb_out
      assign out_valid = v_q;
      assign d = d_c;
      assign flags = f_c;
    end else begin : g_reg_out
      logic [W-1:0] d_p [0:LATENCY-2];
      logic [4:0]   f_p [0:LATENCY-2];
      logic         v_p [0:LATENCY-2];
      always_ff @(posedge clk) begin
        if (!rst_n) begin
          for (int i = 0; i <= LATENCY-2; i = i + 1) v_p[i] <= 1'b0;
        end else begin
          d_p[0] <= d_c;
          f_p[0] <= f_c;
          v_p[0] <= v_q;
          for (int i = 1; i <= LATENCY-2; i = i + 1) begin
            d_p[i] <= d_p[i-1];
            f_p[i] <= f_p[i-1];
            v_p[i] <= v_p[i-1];
          end
        end
      end
      assign out_valid = v_p[LATENCY-2];
      assign d = d_p[LATENCY-2];
      assign flags = f_p[LATENCY-2];
    end
  endgenerate

endmodule
