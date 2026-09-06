// Copyright 2026 Logan W.
// SPDX-License-Identifier: Apache-2.0
//
// tb_mulpass: the iterated chunk-column multiplier against exact
// integer arithmetic, at every geometry a tile can ask for.
//
// Ten cft_mulpass instances - the three wide rungs at every column
// count between one and one short of their chunk count that a pass
// budget can produce - each paced by its own phase counter at its own
// period, each behind a model of the pipe's S1 register (an
// `en`-clocked capture of the shared operand inputs). The bench
// changes the operands EVERY cycle; only what the S1 model captured on
// an enabled edge is what an instance is asked to multiply, which is
// exactly the pipe's contract, and the product must be exact at level
// 5 and hold for the whole interval.
//
// The instance table is written out rather than generated over a
// parameter because each period is a different port the bench has to
// watch; the geometry each instance carries is cft_mulgeom.svh's, and
// the Python side re-derives the periods independently and asserts the
// counters agree.

`timescale 1ns/1ps

module tb_mulpass (
    input  logic         clk,
    input  logic         rst_n,
    input  logic [236:0] a,
    input  logic [236:0] b,
    // one enable and one product per instance: en_k marks the last
    // cycle of instance k's interval, p_k is its product
    output logic         en_0, en_1, en_2, en_3, en_4,
                         en_5, en_6, en_7, en_8, en_9,
    output logic [105:0] p_0, p_1,
    output logic [225:0] p_2, p_3, p_4,
    output logic [473:0] p_5, p_6, p_7, p_8, p_9
);

  `define MP_INST(K, PW, CW)                                              \
    localparam int NP_``K  = (cft_mul_chunks(PW) + CW - 1) / CW;          \
    localparam int PHW_``K = (NP_``K > 1) ? $clog2(NP_``K) : 1;           \
    logic [PHW_``K-1:0] ph_``K;                                           \
    logic [PW-1:0] ar_``K, br_``K;                                        \
    always_ff @(posedge clk) begin                                        \
      if (!rst_n)                              ph_``K <= '0;              \
      else if (ph_``K >= PHW_``K'(NP_``K - 1)) ph_``K <= '0;              \
      else                                     ph_``K <= ph_``K + 1'b1;   \
    end                                                                   \
    assign en_``K = (ph_``K >= PHW_``K'(NP_``K - 1));                      \
    always_ff @(posedge clk) begin                                        \
      if (en_``K) begin ar_``K <= a[PW-1:0]; br_``K <= b[PW-1:0]; end     \
    end                                                                   \
    cft_mulpass #(.P(PW), .COLS(CW), .LEVEL(5)) u_``K (                   \
        .clk(clk), .en(en_``K), .a(ar_``K), .b(br_``K), .p(p_``K));

  `include "cft_mulgeom.svh"

  // The pass count an instance runs at is ceil(chunks / COLS), the
  // same expression cft_mulpass evaluates for itself from the same
  // include; the Python side derives it a third way and compares.
  `MP_INST(0,  53, 1)   // fp64:  3 chunks, 1 column, 3 passes
  `MP_INST(1,  53, 2)   //        2 columns, 2 passes
  `MP_INST(2, 113, 1)   // fp128: 5 chunks, 1 column, 5 passes
  `MP_INST(3, 113, 2)   //        2 columns, 3 passes
  `MP_INST(4, 113, 3)   //        3 columns, 2 passes
  `MP_INST(5, 237, 1)   // fp256: 10 chunks, 1 column, 10 passes
  `MP_INST(6, 237, 2)   //        2 columns, 5 passes
  `MP_INST(7, 237, 5)   //        5 columns, 2 passes
  `MP_INST(8, 237, 3)   //        3 columns, 4 passes
  `MP_INST(9, 237, 4)   //        4 columns, 3 passes

  `undef MP_INST

endmodule
