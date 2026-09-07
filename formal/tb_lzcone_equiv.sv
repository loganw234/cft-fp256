// Copyright 2026 Logan W.
// SPDX-License-Identifier: Apache-2.0
//
// tb_lzcone_equiv: the pipe's leading-zero cone, proven equal to the
// priority-loop form it replaced - not tested equal, proven.
//
// rtl/cft_fpfma_pipe.sv computed the normalise distance inline in S11
// until 2026-09-07: a per-64-bit chunk zero-scan, a top-down priority
// resolve, a chunk mux, a 64-way priority leading-zero count, and
// NW-1-msb. That cone is 8.77 ns of the 11.55 ns routed fp256 path
// (docs/studies/OPT-C-timing.md 0.2), so it was cut with a register and
// then rewritten as a balanced tree. Both changes have to leave the
// three outputs bit-identical on every input, and a leading-zero cone
// is a SAT-friendly object in a way cft_mulpass was not - so this is
// the proof, not a sweep.
//
// formal/cft_lzcone_ref.sv is the frozen copy of the old always_comb.
// Both instances see the same symbolic window, and both are purely
// combinational, so each BMC step is the WHOLE 2^NW input space at this
// rung - a complete equivalence proof, bounded in time, not in
// coverage. NW is a parameter because the pipe builds four of these
// (78, 165, 345, 717 bits at fp32/64/128/256) and the chunk count, the
// zero-fill and the priority depth all move with it; lzcone.sby runs a
// task per rung.
//
// All three outputs are compared, including the two on an empty window.
// That case is not a don't-care: the amount leaves the lane on the
// nrm_csh/nrm_fsh ports and reaches a ladder other lanes are using
// (rtl/cft_normseg.sv), so "zero when empty" is part of the contract
// and not an implementation detail.

`timescale 1ns/1ps

module tb_lzcone_equiv #(
    parameter int NW = 717
) (
    input logic [NW-1:0] v
);

  logic       e_new, e_ref;
  logic [9:0] m_new, m_ref;
  logic [9:0] l_new, l_ref;

  cft_lzcone #(.NW(NW)) u_new (
      .v(v), .empty(e_new), .msb(m_new), .lsh(l_new)
  );

  cft_lzcone_ref #(.NW(NW)) u_ref (
      .v(v), .empty(e_ref), .msb(m_ref), .lsh(l_ref)
  );

  always_comb begin
    a_same_empty: assert (e_new == e_ref);
    a_same_msb:   assert (m_new == m_ref);
    a_same_lsh:   assert (l_new == l_ref);
  end

endmodule
