// Copyright 2026 Logan W.
// SPDX-License-Identifier: Apache-2.0
//
// cft_fifo: synchronous FIFO, distributed-RAM style (async read from
// the read pointer, registered pointers/count). The engine's stream
// buffers. Callers guarantee no overflow/underflow by checking
// `count` before asserting wr_en/rd_en - there are no internal
// guards, because every use site already needs the count for its
// burst-length arithmetic and a silent internal drop would be a
// determinism bug hidden from the testbench.

`timescale 1ns/1ps

module cft_fifo #(
    parameter int WIDTH      = 256,
    parameter int DEPTH_LOG2 = 5
) (
    input  logic                  clk,
    input  logic                  rst_n,
    input  logic                  clear,
    input  logic                  wr_en,
    input  logic [WIDTH-1:0]      wr_data,
    input  logic                  rd_en,
    output logic [WIDTH-1:0]      rd_data,
    output logic [DEPTH_LOG2:0]   count
);

  localparam int DEPTH = 1 << DEPTH_LOG2;

  logic [WIDTH-1:0] mem [0:DEPTH-1];
  logic [DEPTH_LOG2-1:0] wp, rp;

  assign rd_data = mem[rp];

  always_ff @(posedge clk) begin
    if (!rst_n || clear) begin
      wp <= '0;
      rp <= '0;
      count <= '0;
    end else begin
      if (wr_en) wp <= wp + 1'b1;
      if (rd_en) rp <= rp + 1'b1;
      count <= count + (wr_en ? 1'b1 : 1'b0) - (rd_en ? 1'b1 : 1'b0);
    end
  end

  always_ff @(posedge clk) begin
    if (wr_en) mem[wp] <= wr_data;
  end

endmodule
