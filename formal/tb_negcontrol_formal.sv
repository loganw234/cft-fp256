// Copyright 2026 Logan W.
// SPDX-License-Identifier: Apache-2.0
//
// tb_negcontrol_formal: the deliberately broken property. MUST FAIL.
//
// A gate that cannot fail proves nothing, so this harness asserts a
// claim that is definitely false and run.sh requires sby to refute
// it (negcontrol.sby says `expect fail`, so a refutation is the
// passing outcome and an unexpected proof is the alarm).
//
// The false claim is chosen to be the one this design exists to
// dodge, not an arbitrary `assert (0)`: it says cft_fifo never
// needed its head bypass - that a plain synchronous read of the
// storage, address led by the pop, would have presented the right
// word whenever count reads nonzero. f_naive below is exactly that
// bypass-less read path, built against the same shadow memory the
// real proof trusts, with the same read-old collision semantics the
// RAM has. If the claim held, rd_data would equal f_naive in every
// nonempty cycle.
//
// It does not hold, and the counterexample sby produces is the
// module header's own story retold by a solver: a write landing at
// the read head - into an empty FIFO, or exactly as the last-but-one
// word pops - where the synchronous read returns the pre-write word
// and only the bypass has the fresh one. count says the word is
// there in the very next cycle; the naive path cannot deliver it.
//
// So this control earns its keep twice over: it proves the gate's
// machinery can see an assertion fail at all (the reason negative
// controls are house law - a bind that silently drops every
// assertion passes everything), and its trace documents that the
// main proof's world genuinely contains the collision case the
// bypass covers.

`timescale 1ns/1ps

module tb_negcontrol_formal #(
    parameter int WIDTH      = 8,
    parameter int DEPTH_LOG2 = 3
) (
    input logic             clk,
    input logic             rst_n,
    input logic             clear,
    input logic             wr_en,
    input logic [WIDTH-1:0] wr_data,
    input logic             rd_en
);

  localparam int DEPTH = 1 << DEPTH_LOG2;

  logic [WIDTH-1:0]    rd_data;
  logic [DEPTH_LOG2:0] count;

  cft_fifo #(
      .WIDTH(WIDTH),
      .DEPTH_LOG2(DEPTH_LOG2)
  ) dut (
      .clk    (clk),
      .rst_n  (rst_n),
      .clear  (clear),
      .wr_en  (wr_en),
      .wr_data(wr_data),
      .rd_en  (rd_en),
      .rd_data(rd_data),
      .count  (count)
  );

  // Same legal-traffic world as the real proof - the control must
  // fail INSIDE the assumptions, or it demonstrates nothing about
  // them.
  always_comb begin
    assume (!(wr_en && count == DEPTH));
    assume (!(rd_en && count == 0));
  end

  initial assume (!rst_n);

  logic f_past_valid = 1'b0;
  always_ff @(posedge clk) f_past_valid <= 1'b1;

  // The same port-built shadow FIFO the real proof checks against.
  logic [DEPTH_LOG2-1:0] f_swp, f_srp;
  logic [WIDTH-1:0]      f_shadow [0:DEPTH-1];

  always_ff @(posedge clk) begin
    if (!rst_n || clear) begin
      f_swp <= '0;
      f_srp <= '0;
    end else begin
      if (wr_en) begin
        f_shadow[f_swp] <= wr_data;
        f_swp <= f_swp + 1'b1;
      end
      if (rd_en) f_srp <= f_srp + 1'b1;
    end
  end

  // The bypass-less read path: synchronous, address led by the pop,
  // read-old on a same-cycle write to the same slot - a BRAM with no
  // help. This is what cft_fifo would present if its header's
  // "conversion inside the port list" had stopped before the bypass.
  logic [WIDTH-1:0] f_naive;
  always_ff @(posedge clk)
    f_naive <= f_shadow[rd_en ? (f_srp + 1'b1) : f_srp];

  // THE BROKEN PROPERTY - the whole point of the file. Reads as: the
  // bypass was never needed. sby must produce a counterexample.
  always_ff @(posedge clk) begin
    if (f_past_valid)
      a_no_bypass_needed: assert (count == 0 || rd_data == f_naive);
  end

endmodule
