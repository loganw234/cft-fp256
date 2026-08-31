// Copyright 2026 Logan W.
// SPDX-License-Identifier: Apache-2.0
//
// tb_normseg: fifteen private normalise shifters beside one shared
// segmented shifter, driven from the same operand word.
//
//   *_ref   cft_normref x15 - literally cft_fpfma_pipe's own two
//           expressions, `valw << (csh*64)` then `<< fsh`, at the four
//           interchange widths
//   u_seg   cft_normseg x1 - the segmented ladder that is meant to
//           replace all fifteen
//
// This is the tb_mulshare argument again, and deliberately so: the
// shared multiplier was correct and did not pay, so the equivalence
// bench and the area measurement are separate questions and both get
// asked. This file answers the first. hw/ answers the second.
//
// PACKING. Lane l under mode m occupies bits [l*(SLOTW<<m) +: NW_m],
// with SLOTW = 90 - the smallest slot holding an fp32 window whose
// eight-fold tiling holds an fp256 one. The reference lanes are fed
// the same slices, so a mismatch is the shifter's and not the
// wiring's. Padding inside a slot is not compared: the shared ladder
// carries bits there that a private NW-wide shifter truncates away,
// and no consumer reads them. The bench masks to the live fields.

`timescale 1ns/1ps

module tb_normseg #(
    parameter int PMAX  = 237,
    parameter int SLOTS = 8,
    parameter int SLOTW = ((3 * PMAX + 6) + SLOTS - 1) / SLOTS,
    parameter int WT    = SLOTS * SLOTW
) (
    input  logic          clk,
    input  logic [1:0]    mode,
    input  logic [WT-1:0] din,
    // Packed rather than unpacked arrays, so the bench can drive them
    // as plain integers on every simulator rather than depending on
    // how each one exposes an unpacked array port.
    input  logic [SLOTS*4-1:0] csh_v,
    input  logic [SLOTS*6-1:0] fsh_v,

    output logic [WT-1:0] dout,     // the shared ladder
    output logic [WT-1:0] r0,       // fp32  reference, 8 lanes
    output logic [WT-1:0] r1,       // fp64  reference, 4 lanes
    output logic [WT-1:0] r2,       // fp128 reference, 2 lanes
    output logic [WT-1:0] r3        // fp256 reference, 1 lane
);

  localparam int NW0 = 3 * 24  + 6;
  localparam int NW1 = 3 * 53  + 6;
  localparam int NW2 = 3 * 113 + 6;
  localparam int NW3 = 3 * 237 + 6;

  logic [3:0] csh [0:SLOTS-1];
  logic [5:0] fsh [0:SLOTS-1];
  always_comb begin
    for (int l = 0; l < SLOTS; l++) begin
      csh[l] = csh_v[l*4 +: 4];
      fsh[l] = fsh_v[l*6 +: 6];
    end
  end

  cft_normseg #(.PMAX(PMAX), .SLOTS(SLOTS)) u_seg (
      .clk(clk), .mode(mode), .din(din), .csh(csh), .fsh(fsh), .dout(dout));

  genvar gl;
  generate
    for (gl = 0; gl < 8; gl = gl + 1) begin : g_ref32
      cft_normref #(.NW(NW0)) u (
          .clk(clk), .din(din[gl*SLOTW +: NW0]),
          .csh(csh[gl]), .fsh(fsh[gl]),
          .dout(r0[gl*SLOTW +: NW0]));
      if (SLOTW > NW0) assign r0[gl*SLOTW + NW0 +: (SLOTW - NW0)] = '0;
    end

    for (gl = 0; gl < 4; gl = gl + 1) begin : g_ref64
      cft_normref #(.NW(NW1)) u (
          .clk(clk), .din(din[gl*2*SLOTW +: NW1]),
          .csh(csh[gl]), .fsh(fsh[gl]),
          .dout(r1[gl*2*SLOTW +: NW1]));
      if (2*SLOTW > NW1) assign r1[gl*2*SLOTW + NW1 +: (2*SLOTW - NW1)] = '0;
    end

    for (gl = 0; gl < 2; gl = gl + 1) begin : g_ref128
      cft_normref #(.NW(NW2)) u (
          .clk(clk), .din(din[gl*4*SLOTW +: NW2]),
          .csh(csh[gl]), .fsh(fsh[gl]),
          .dout(r2[gl*4*SLOTW +: NW2]));
      if (4*SLOTW > NW2) assign r2[gl*4*SLOTW + NW2 +: (4*SLOTW - NW2)] = '0;
    end
  endgenerate

  cft_normref #(.NW(NW3)) u_ref256 (
      .clk(clk), .din(din[0 +: NW3]),
      .csh(csh[0]), .fsh(fsh[0]),
      .dout(r3[0 +: NW3]));
  generate
    if (WT > NW3) assign r3[NW3 +: (WT - NW3)] = '0;
  endgenerate

endmodule


// The private shifter, exactly as cft_fpfma_pipe writes it today:
// S11 shifts by whole 64-bit granules, S12 by the remainder, with a
// register between them. Copied rather than referenced so that
// changing the pipe cannot silently change what this is compared to.
//
// f_r is not decoration. The pipe registers the fine amount in S11
// (`s11_fine <= (NW - 1 - msb) & 63`) and reads it in S12, so the
// amount travels with its operand. A reference that read the live port
// instead would model a shifter nobody built, and the first version of
// this file did exactly that - which made the shared ladder look wrong
// on every vector where the amount changed, i.e. all of them.
module cft_normref #(
    parameter int NW = 78
) (
    input  logic          clk,
    input  logic [NW-1:0] din,
    input  logic [3:0]    csh,
    input  logic [5:0]    fsh,
    output logic [NW-1:0] dout
);
  logic [NW-1:0] c_r;
  logic [5:0]    f_r;
  always_ff @(posedge clk) begin
    c_r  <= din << (csh * 64);
    f_r  <= fsh;
    dout <= c_r << f_r;
  end
endmodule
