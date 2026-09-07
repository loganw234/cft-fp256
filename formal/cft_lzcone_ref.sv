// Copyright 2026 Logan W.
// SPDX-License-Identifier: Apache-2.0
//
// cft_lzcone_ref: the leading-zero cone as rtl/cft_fpfma_pipe.sv wrote
// it before 2026-09-07 - a frozen byte copy of the always_comb that
// lived inline in S11, lifted into a module and otherwise untouched.
//
// It is here for the same reason tb/wrappers/cft_simpleops_ref.sv is
// there: so the form that replaced it can be proven equal to it rather
// than tested equal to it. formal/lzcone.sby drives one symbolic window
// into this and into rtl/'s cft_lzcone and asserts all three outputs
// agree; both are combinational, so a BMC step is the whole 2^NW input
// space at that rung.
//
// DO NOT "improve" this file. Its only job is to be what the pipe used
// to compute. If the cone's contract changes - what it reports on an
// empty window, say - the change belongs in rtl/ and the proof is then
// allowed to fail, which is the point of having it.

`timescale 1ns/1ps

module cft_lzcone_ref #(
    parameter int NW = 717
) (
    input  logic [NW-1:0] v,
    output logic          empty,
    output logic [9:0]    msb,
    output logic [9:0]    lsh
);

  localparam int NCH = (NW + 63) / 64;

  function automatic int lzc64(input logic [63:0] x);
    int r;
    begin
      r = 64;
      for (int i = 0; i < 64; i = i + 1) if (x[i]) r = 63 - i;
      lzc64 = r;
    end
  endfunction

  // The one edit against the frozen source: `n11_msb` was an `int` in
  // the pipe (its only consumer was the signed exponent add, which now
  // happens a stage later), and the module port is ten bits. The scan,
  // the priority resolve, the chunk mux and both subtractions are
  // character for character what was there.
  int n11_msb;

  always_comb begin
    logic [NCH*64-1:0] padded;
    logic [31:0] lsh_full, msb_full;
    int chunk, cl;
    cl = 0;
    lsh_full = '0;
    msb_full = '0;
    padded = {{(NCH*64-NW){1'b0}}, v};
    chunk = -1;
    for (int ci = NCH - 1; ci >= 0; ci = ci - 1) begin
      if (chunk == -1 && (padded[ci*64 +: 64] != 0)) chunk = ci;
    end
    if (chunk == -1) begin
      empty   = 1'b1;
      n11_msb = 0;
      msb     = '0;
      lsh     = '0;
    end else begin
      cl       = lzc64(padded[chunk*64 +: 64]);
      n11_msb  = chunk * 64 + (63 - cl);
      empty    = 1'b0;
      lsh_full = NW - 1 - n11_msb;
      msb_full = n11_msb;
      lsh      = lsh_full[9:0];
      msb      = msb_full[9:0];
    end
  end

endmodule
