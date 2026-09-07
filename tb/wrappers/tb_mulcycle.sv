// Copyright 2026 Logan W.
// SPDX-License-Identifier: Apache-2.0
//
// tb_mulcycle: the lane array at two pass budgets, fed the same beats.
//
//   u_ref   cft_lanes at MUL_PASSES=1 - the shipping array, every rung
//           a beat per cycle, the arrangement the whole suite scores
//           against the golden model
//   u_mc    cft_lanes at MUL_PASSES=MC - the multi-cycle array, its wide
//           rungs iterating a subset of their chunk columns and the
//           whole pipe paced at the live rung's pass count
//
// Both see identical requests. The multi-cycle array accepts a beat
// only in a cycle with in_ready high, so the bench presents each beat
// in such a cycle and both arrays take it on the same edge; results
// then emerge from u_ref fifteen edges later and from u_mc fifteen
// ENABLED edges later, and the bench matches them in order. Every
// result word and every lane's flags must be equal bit for bit, in
// every format, under every rounding attribute, with the issue cadence
// varied at random - the cadence is the one thing the multi-cycle
// array adds, and the contract says it cannot reach the bits.
//
// Compared against each other rather than each against the model, for
// the reason tb_mulshare gives: the model comparison exists (the kernel
// and pipe benches run at MUL_PASSES=MC too), and what is new here is a
// claim of EQUIVALENCE, best tested by subtraction. A bug that moves
// both arrays the same way is the model benches' to catch; one that
// moves the multi-cycle array alone is caught here, with no opinion
// about what the right answer is.

`timescale 1ns/1ps

module tb_mulcycle #(
    parameter int MC      = 10,
    parameter int LATENCY = 16
) (
    input  logic         clk,
    input  logic         rst_n,
    input  logic         in_valid,
    input  logic [7:0]   op,
    input  logic [2:0]   rnd,
    input  logic [1:0]   prec,
    input  logic [255:0] a,
    input  logic [255:0] b,
    input  logic [255:0] c,
    output logic         ready_mc,     // u_mc takes a request this cycle
    output logic         ov_ref, ov_mc,
    output logic [255:0] d_ref, d_mc,
    output logic [39:0]  lf_ref, lf_mc
);

  logic ready_ref;

  cft_lanes #(.BEAT_BITS(256), .LATENCY(LATENCY), .MUL_PASSES(1)) u_ref (
      .clk(clk), .rst_n(rst_n),
      .in_valid(in_valid), .op(op), .rnd(rnd), .prec(prec),
      .a(a), .b(b), .c(c), .in_ready(ready_ref),
      .out_valid(ov_ref), .d(d_ref), .lane_flags(lf_ref));

  cft_lanes #(.BEAT_BITS(256), .LATENCY(LATENCY), .MUL_PASSES(MC)) u_mc (
      .clk(clk), .rst_n(rst_n),
      .in_valid(in_valid), .op(op), .rnd(rnd), .prec(prec),
      .a(a), .b(b), .c(c), .in_ready(ready_mc),
      .out_valid(ov_mc), .d(d_mc), .lane_flags(lf_mc));

  // The reference array is always ready; a bench presenting a beat in
  // a cycle the multi-cycle array declines would otherwise hand the
  // two arrays different streams and compare nothing.
  // synthesis translate_off
  always_ff @(posedge clk)
    if (rst_n && !ready_ref)
      $fatal(1, "tb_mulcycle: the MUL_PASSES=1 array declined a cycle");
  // synthesis translate_on

endmodule
