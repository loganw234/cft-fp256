// Copyright 2026 Logan W.
// SPDX-License-Identifier: Apache-2.0
//
// tb_fifo_formal: unbounded proof of cft_fifo's contract.
//
// The simulation benches drive traffic and compare against the golden
// model; this harness makes the complementary claim: for EVERY legal
// input sequence, from reset, forever - not for the sequences some
// generator happened to draw. "Legal" is the module's own published
// contract, assumed here exactly as its header states it: callers
// check `count` before asserting wr_en/rd_en, so a write never lands
// on a full FIFO and a read never lands on an empty one. There are no
// internal guards on purpose, so driving illegal traffic proves
// nothing about the design - it would only prove the absence of
// guards the header already tells you are absent.
//
// What is proven (fifo.sby task `prove`, mode prove, so it holds for
// unbounded time, not just a BMC horizon):
//
//   * count consistency: `count` equals the spec's own occupancy
//     (writes minus reads since reset, cleared by reset and clear),
//     and it never exceeds DEPTH. Together with the assumptions this
//     is the full/empty contract as the module defines it: full is
//     count == DEPTH, empty is count == 0, and count moves at the
//     write edge because it IS the write-edge accounting.
//   * data integrity and ordering: in every cycle with count != 0,
//     rd_data is bit-for-bit the oldest unconsumed write - the
//     same-cycle-valid head the callers depend on. The spec is a
//     shadow FIFO built here from port activity alone; it shares no
//     state with the DUT, so a DUT that reordered, duplicated,
//     dropped or corrupted a word would part ways with it. Checking
//     every pop against the shadow head subsumes the two-token
//     argument: every word is the watched word.
//
// HONEST SCOPE: the proof runs at WIDTH=8, DEPTH_LOG2=3 (DEPTH 8),
// not at the deployed 256x32. The module is parameterized and nothing
// in it branches on the parameter values, but a proof at one size is
// a proof at one size: the properties are proven for this instance
// and argued, not proven, for the rest. Small is still complete in
// the dimension that matters - every control shape (empty, full,
// wrap-around, the bypass capture in both its forms, the bypass's
// two-cycle age-out, clear and reset mid-stream) exists at DEPTH 8,
// and the cover task demonstrates each is reachable under the
// assumptions, so the proof does not pass by excluding them.
//
// WHY THE ENGINE IS abc pdr AND NOT smtbmc k-INDUCTION - recorded
// because the failure mode is silent and cost this gate a vacuous
// first "pass". The contract assertions alone are not k-inductive:
// closing an induction by hand needs strengthening invariants that
// name the DUT's internals (RAM slot vs shadow slot, bypass registers
// vs head), and yosys's open Verilog frontend offers formal code no
// path to them. `bind` parses and then binds nothing - the checker
// module is dropped as unused, and every assertion silently vanishes
// with it. Hierarchical references (dut.wp) parse too, as fresh
// DANGLING wires, so every property written against them is checked
// against unconstrained values. Both were tried; the $check-cell
// count in run.sh's vacuity step exists because of what that
// uncovered. pdr needs neither: it derives an inductive invariant
// internally from the external spec below - a proof by induction
// where the induction hypothesis is found by the engine instead of
// written by hand. The price is honest: the discovered invariant is
// not a human-readable artifact, so the design insight a hand-written
// invariant set would document lives in cft_fifo.sv's own header
// instead of here.
//
// A note on read-during-write: formal uses Verilog semantics, where a
// same-cycle read of a written address returns the OLD word, while on
// the real fabric (UG573) it is undefined - that hazard is why the
// head bypass exists. The proof shows rd_data is right in those
// cycles, i.e. the bypass presents the correct word whenever it is
// selected; it cannot show what a BRAM would have driven instead,
// because "undefined" has no model here. The negative control
// (negcontrol.sby) asserts a bypass-less FIFO would have been good
// enough, and fails on exactly the capture case, which demonstrates
// these proofs do exercise the bypass.

`timescale 1ns/1ps

module tb_fifo_formal #(
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

  // ------------------------------------------------------------------
  // The caller contract, assumed. Exactly the header's two rules and
  // nothing else: rst_n, clear, wr_data and the enable timing stay
  // free otherwise, so mid-stream clears, back-to-back pops,
  // simultaneous push+pop and repeated resets are all inside the
  // proof.
  // ------------------------------------------------------------------
  always_comb begin
    assume (!(wr_en && count == DEPTH));   // never write a full FIFO
    assume (!(rd_en && count == 0));       // never read an empty FIFO
  end

  // The trace starts where the engine starts: in reset. Only t=0 is
  // constrained; rst_n is free afterwards.
  initial assume (!rst_n);

  // Registers are unconstrained at t=0, so nothing is asserted about
  // the pre-reset state.
  logic f_past_valid = 1'b0;
  always_ff @(posedge clk) f_past_valid <= 1'b1;

  // ------------------------------------------------------------------
  // The specification: a shadow FIFO built from the ports alone. Its
  // pointers count port events, its memory holds what was pushed. It
  // deliberately reads nothing from inside the DUT - agreement is the
  // thing being proven, not an assumption.
  // ------------------------------------------------------------------
  logic [DEPTH_LOG2-1:0] f_swp, f_srp;
  logic [DEPTH_LOG2:0]   f_cnt;
  logic [WIDTH-1:0]      f_shadow [0:DEPTH-1];

  always_ff @(posedge clk) begin
    if (!rst_n || clear) begin
      f_swp <= '0;
      f_srp <= '0;
      f_cnt <= '0;
    end else begin
      if (wr_en) begin
        f_shadow[f_swp] <= wr_data;
        f_swp <= f_swp + 1'b1;
      end
      if (rd_en) f_srp <= f_srp + 1'b1;
      f_cnt <= f_cnt + (wr_en ? 1'b1 : 1'b0) - (rd_en ? 1'b1 : 1'b0);
    end
  end

  // ------------------------------------------------------------------
  // The contract, asserted.
  // ------------------------------------------------------------------
  always_ff @(posedge clk) begin
    if (f_past_valid) begin
      // Count consistency: the output is the spec's occupancy, and
      // the occupancy is bounded. Underflow cannot hide either - a
      // wrap of the (DEPTH_LOG2+1)-bit counter would blow the range
      // check the next cycle.
      a_count_matches_spec: assert (count == f_cnt);
      a_count_in_range:     assert (count <= DEPTH);

      // Data integrity and ordering, the load-bearing claim: whenever
      // count reads nonzero, rd_data IS the oldest unconsumed write,
      // in the same cycle. FIFO order follows: every pop is checked
      // against the head slot, and the head index only ever advances
      // by the pops themselves.
      a_head_data: assert (count == 0 || rd_data == f_shadow[f_srp]);
    end
  end

  // ------------------------------------------------------------------
  // Reachability, for the cover task. A property proven over an
  // over-constrained world passes for the wrong reason; each cover
  // below fails that task if the assumptions ever exclude the shape
  // it names. The bypass cannot be named directly (no internal
  // access, as above), so its three-act story is covered by its
  // port-level fingerprint: capture, hold, pop two cycles later -
  // exactly the two-cycle window cft_fifo's header walks through.
  // ------------------------------------------------------------------
  // Gated on f_past_valid: the t=0 register soup can read count ==
  // DEPTH before reset has ever run, and a cover satisfied by
  // pre-reset garbage demonstrates nothing (it was reached in step 2
  // before this guard existed - a real fill takes eight writes).
  logic f_seen_full = 1'b0;
  always_ff @(posedge clk)
    if (f_past_valid && count == DEPTH) f_seen_full <= 1'b1;

  logic f_cap1 = 1'b0;                  // last cycle captured into empty
  logic f_cap2 = 1'b0;                  // ...and the word is two cycles old
  always_ff @(posedge clk) begin
    f_cap1 <= rst_n && !clear && wr_en && (count == 0);
    f_cap2 <= rst_n && !clear && f_cap1 && !rd_en;
  end

  always_ff @(posedge clk) begin
    if (f_past_valid) begin
      c_full:                  cover (count == DEPTH);
      c_empty_after_full:      cover (f_seen_full && count == 0);
      c_capture_into_empty:    cover (wr_en && count == 0);
      c_capture_pop_through:   cover (wr_en && rd_en && count == 1);
      c_pop_fresh_capture:     cover (f_cap1 && rd_en);
      c_pop_aged_capture:      cover (f_cap2 && rd_en);
      c_wrapped_occupancy:     cover (count != 0 && f_swp < f_srp);
      c_clear_midstream:       cover (clear && count != 0);
    end
  end

endmodule
