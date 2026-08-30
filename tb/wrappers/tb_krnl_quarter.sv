// Copyright 2026 Logan W.
// SPDX-License-Identifier: Apache-2.0
//
// A quarter-tile: 64-bit beat, fp32 and fp64 only. Two fp32 lanes or
// one fp64 per beat instead of eight and four.
//
// This is not a hypothetical. It is the shape that fits an Alchitry Au
// (docs/ROADMAP.md's conformance node - the cheapest object that can
// attest the contract), and the shape a 130nm chiplet wants when it
// trades compute width for on-chip deposition buffer, where SRAM costs
// millimetres and the off-die link is the real constraint.
//
// It exists as a testbench top so the parameterization is PROVEN
// rather than declared. A parameter nothing instantiates is a
// parameter that does not work yet; this one runs the same kernel
// bench, against the same golden model, at a different geometry.

`timescale 1ns/1ps

module tb_krnl_quarter (
    input  logic         ap_clk,
    input  logic         ap_rst_n,

    input  logic [11:0]  s_axi_control_awaddr,
    input  logic         s_axi_control_awvalid,
    output logic         s_axi_control_awready,
    input  logic [31:0]  s_axi_control_wdata,
    input  logic [3:0]   s_axi_control_wstrb,
    input  logic         s_axi_control_wvalid,
    output logic         s_axi_control_wready,
    output logic [1:0]   s_axi_control_bresp,
    output logic         s_axi_control_bvalid,
    input  logic         s_axi_control_bready,
    input  logic [11:0]  s_axi_control_araddr,
    input  logic         s_axi_control_arvalid,
    output logic         s_axi_control_arready,
    output logic [31:0]  s_axi_control_rdata,
    output logic [1:0]   s_axi_control_rresp,
    output logic         s_axi_control_rvalid,
    input  logic         s_axi_control_rready,

    output logic [0:0]   m00_axi_awid,
    output logic [63:0]  m00_axi_awaddr,
    output logic [7:0]   m00_axi_awlen,
    output logic [2:0]   m00_axi_awsize,
    output logic [1:0]   m00_axi_awburst,
    output logic         m00_axi_awlock,
    output logic [3:0]   m00_axi_awcache,
    output logic [2:0]   m00_axi_awprot,
    output logic [3:0]   m00_axi_awqos,
    output logic         m00_axi_awvalid,
    input  logic         m00_axi_awready,
    output logic [63:0]  m00_axi_wdata,
    output logic [7:0]   m00_axi_wstrb,
    output logic         m00_axi_wlast,
    output logic         m00_axi_wvalid,
    input  logic         m00_axi_wready,
    input  logic [0:0]   m00_axi_bid,
    input  logic [1:0]   m00_axi_bresp,
    input  logic         m00_axi_bvalid,
    output logic         m00_axi_bready,
    output logic [0:0]   m00_axi_arid,
    output logic [63:0]  m00_axi_araddr,
    output logic [7:0]   m00_axi_arlen,
    output logic [2:0]   m00_axi_arsize,
    output logic [1:0]   m00_axi_arburst,
    output logic         m00_axi_arlock,
    output logic [3:0]   m00_axi_arcache,
    output logic [2:0]   m00_axi_arprot,
    output logic [3:0]   m00_axi_arqos,
    output logic         m00_axi_arvalid,
    input  logic         m00_axi_arready,
    input  logic [0:0]   m00_axi_rid,
    input  logic [63:0]  m00_axi_rdata,
    input  logic [1:0]   m00_axi_rresp,
    input  logic         m00_axi_rlast,
    input  logic         m00_axi_rvalid,
    output logic         m00_axi_rready
);

  cft_krnl #(.EN_FP64(1'b1), .EN_FP128(1'b0), .EN_FP256(1'b0),
             .BEAT_BITS(64)) u_krnl (.*);

endmodule
