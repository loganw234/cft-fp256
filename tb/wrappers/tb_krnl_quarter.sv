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
    // a
    output logic [0:0] m_axi_a_arid,
    output logic [63:0] m_axi_a_araddr,
    output logic [7:0] m_axi_a_arlen,
    output logic [2:0] m_axi_a_arsize,
    output logic [1:0] m_axi_a_arburst,
    output logic m_axi_a_arlock,
    output logic [3:0] m_axi_a_arcache,
    output logic [2:0] m_axi_a_arprot,
    output logic [3:0] m_axi_a_arqos,
    output logic m_axi_a_arvalid,
    input  logic m_axi_a_arready,
    input  logic [0:0] m_axi_a_rid,
    input  logic [63:0] m_axi_a_rdata,
    input  logic [1:0] m_axi_a_rresp,
    input  logic m_axi_a_rlast,
    input  logic m_axi_a_rvalid,
    output logic m_axi_a_rready,

    // b
    output logic [0:0] m_axi_b_arid,
    output logic [63:0] m_axi_b_araddr,
    output logic [7:0] m_axi_b_arlen,
    output logic [2:0] m_axi_b_arsize,
    output logic [1:0] m_axi_b_arburst,
    output logic m_axi_b_arlock,
    output logic [3:0] m_axi_b_arcache,
    output logic [2:0] m_axi_b_arprot,
    output logic [3:0] m_axi_b_arqos,
    output logic m_axi_b_arvalid,
    input  logic m_axi_b_arready,
    input  logic [0:0] m_axi_b_rid,
    input  logic [63:0] m_axi_b_rdata,
    input  logic [1:0] m_axi_b_rresp,
    input  logic m_axi_b_rlast,
    input  logic m_axi_b_rvalid,
    output logic m_axi_b_rready,

    // c
    output logic [0:0] m_axi_c_arid,
    output logic [63:0] m_axi_c_araddr,
    output logic [7:0] m_axi_c_arlen,
    output logic [2:0] m_axi_c_arsize,
    output logic [1:0] m_axi_c_arburst,
    output logic m_axi_c_arlock,
    output logic [3:0] m_axi_c_arcache,
    output logic [2:0] m_axi_c_arprot,
    output logic [3:0] m_axi_c_arqos,
    output logic m_axi_c_arvalid,
    input  logic m_axi_c_arready,
    input  logic [0:0] m_axi_c_rid,
    input  logic [63:0] m_axi_c_rdata,
    input  logic [1:0] m_axi_c_rresp,
    input  logic m_axi_c_rlast,
    input  logic m_axi_c_rvalid,
    output logic m_axi_c_rready,

    // d
    output logic [0:0] m_axi_d_awid,
    output logic [63:0] m_axi_d_awaddr,
    output logic [7:0] m_axi_d_awlen,
    output logic [2:0] m_axi_d_awsize,
    output logic [1:0] m_axi_d_awburst,
    output logic m_axi_d_awlock,
    output logic [3:0] m_axi_d_awcache,
    output logic [2:0] m_axi_d_awprot,
    output logic [3:0] m_axi_d_awqos,
    output logic m_axi_d_awvalid,
    input  logic m_axi_d_awready,
    output logic [63:0] m_axi_d_wdata,
    output logic [7:0] m_axi_d_wstrb,
    output logic m_axi_d_wlast,
    output logic m_axi_d_wvalid,
    input  logic m_axi_d_wready,
    input  logic [0:0] m_axi_d_bid,
    input  logic [1:0] m_axi_d_bresp,
    input  logic m_axi_d_bvalid,
    output logic m_axi_d_bready
);

  cft_krnl #(.EN_FP64(1'b1), .EN_FP128(1'b0), .EN_FP256(1'b0),
             .BEAT_BITS(64)) u_krnl (.*);

endmodule
