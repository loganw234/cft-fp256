// Copyright 2026 Logan W.
// SPDX-License-Identifier: Apache-2.0
//
// cft_fifo: synchronous FIFO, block-RAM backed, same-cycle read data.
// The engine's stream buffers. Callers guarantee no overflow/underflow
// by checking `count` before asserting wr_en/rd_en - there are no
// internal guards, because every use site already needs the count for
// its burst-length arithmetic and a silent internal drop would be a
// determinism bug hidden from the testbench.
//
// THE INTERFACE IS THE OLD ONE, and that is the point of the design
// below. The first version read the memory asynchronously
// (`rd_data = mem[rp]`), which forecloses block RAM - UG574: LUTRAM
// reads combinationally, BRAM registers its output - so four FIFOs
// cost 2,368 LUTRAM plus the fabric around it. But the CALLERS depend
// on the async contract in two load-bearing ways:
//
//   * rd_data is valid in the same cycle count reads nonzero, and
//   * count moves at the write edge, because the readers' free-space
//     reservation (FDEPTH - count - outstanding) must never
//     overestimate space, and a count that lags a write does exactly
//     that.
//
// So the conversion happens INSIDE the port list. The RAM is
// synchronous-read with its address led by one (`rp + rd_en`), which
// keeps its output register holding mem[rp] across sustained
// one-per-cycle pops. The one place that breaks is a write landing at
// the READ HEAD - a write into an empty FIFO, or a write arriving
// exactly as the last-but-one word is popped - where the BRAM cannot
// deliver the just-written word in time (and a same-address
// read-during-write across ports is undefined on this fabric anyway,
// UG573). A two-cycle head bypass covers exactly those:
//
//   capture  = wr_en && (count == 0 || (count == 1 && rd_en));
//
// After a capture the written word IS the head and the count is 1, so
// nothing else can be popped until either this word goes (FIFO empty,
// rd_data don't-care) or two cycles pass and the RAM's output has
// caught up cleanly. The bypass therefore needs no address compare -
// the capture condition is the address compare, evaluated where the
// answer is already known.
//
// Cost, measured at the kernel: the four stream FIFOs move from
// distributed RAM into 16 block RAMs (of 1,344, previously 0 used) and
// the LUTs around them are returned to the pool.

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

  (* ram_style = "block" *)
  logic [WIDTH-1:0] mem [0:DEPTH-1];
  logic [DEPTH_LOG2-1:0] wp, rp;

  // Pointers and count: exactly the old process. count moves at the
  // write edge, which the readers' space reservation depends on.
  always_ff @(posedge clk) begin
    if (!rst_n || clear) begin
      wp <= '0;
      rp <= '0;
      count <= '0;
    end else begin
      if (wr_en) wp <= wp + 1'b1;
      if (rd_en) rp <= rp + 1'b1;
      // The enables zero-extended to count's width: +1, +0, or -1.
      count <= count + {{DEPTH_LOG2{1'b0}}, wr_en}
                     - {{DEPTH_LOG2{1'b0}}, rd_en};
    end
  end

  always_ff @(posedge clk) begin
    if (wr_en) mem[wp] <= wr_data;
  end

  // Synchronous read, address led by the pop: after any cycle - popping
  // or not - ram_q holds mem[rp as it now stands].
  logic [WIDTH-1:0] ram_q;
  logic [DEPTH_LOG2-1:0] rd_addr;
  assign rd_addr = rd_en ? (rp + 1'b1) : rp;
  always_ff @(posedge clk) begin
    ram_q <= mem[rd_addr];
  end

  // The head bypass. byp_v1 covers the cycle after the capture, where
  // the RAM read collided with the write; byp_v2 covers the cycle
  // after that, where the RAM output still holds the collided read.
  // From the third cycle the RAM has re-read the address cleanly. A
  // pop while the bypass is live consumes the captured word itself -
  // the capture condition forces count to 1 - so the bypass never
  // masks a DIFFERENT word than the RAM would present.
  logic             byp_v1, byp_v2;
  logic [WIDTH-1:0] byp_d;
  logic             capture;
  assign capture = wr_en && ((count == 0) ||
                             ((count == 1) && rd_en));

  always_ff @(posedge clk) begin
    if (!rst_n || clear) begin
      byp_v1 <= 1'b0;
      byp_v2 <= 1'b0;
    end else begin
      byp_v1 <= capture;
      byp_v2 <= byp_v1 && !rd_en;
      if (capture) byp_d <= wr_data;
    end
  end

  assign rd_data = (byp_v1 || byp_v2) ? byp_d : ram_q;

endmodule
