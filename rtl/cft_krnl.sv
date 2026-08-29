// Copyright 2026 Logan W.
// SPDX-License-Identifier: Apache-2.0
//
// cft_krnl: Vitis RTL kernel top for the Coordinated Fusion Tile.
// ap_ctrl_hs control protocol on s_axi_control, one 256-bit AXI4
// master (m00_axi) into the HBM subsystem (256 = native HBM
// pseudo-channel width; no width converter in fabric or emulation). Port names follow the
// Vitis RTL kernel conventions so package_xo infers the interfaces;
// hw/kernel.xml describes the argument map (which is cft_csr's).

`timescale 1ns/1ps

module cft_krnl #(
    // Bank trims for constrained targets (open-core conformance
    // nodes); the full Alveo tile keeps all four rungs. fp32 is the
    // baseline and always present. Advertised in the CAPS CSR.
    parameter bit EN_FP64  = 1'b1,
    parameter bit EN_FP128 = 1'b1,
    parameter bit EN_FP256 = 1'b1
) (
    input  logic         ap_clk,
    input  logic         ap_rst_n,

    // AXI4-Lite control
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

    // AXI4 master to HBM
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
    output logic [255:0] m00_axi_wdata,
    output logic [31:0]  m00_axi_wstrb,
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
    input  logic [255:0] m00_axi_rdata,
    input  logic [1:0]   m00_axi_rresp,
    input  logic         m00_axi_rlast,
    input  logic         m00_axi_rvalid,
    output logic         m00_axi_rready
);

  logic        start, busy, done;
  logic [4:0]  eng_flags;
  logic [2:0]  eng_err;
  logic [3:0]  cfg_op, cfg_prec;
  logic [2:0]  cfg_rnd;
  logic [63:0] cfg_n, cfg_a, cfg_b, cfg_c, cfg_d;

  cft_csr u_csr (
      .ap_clk(ap_clk), .ap_rst_n(ap_rst_n),
      .s_axi_control_awaddr(s_axi_control_awaddr),
      .s_axi_control_awvalid(s_axi_control_awvalid),
      .s_axi_control_awready(s_axi_control_awready),
      .s_axi_control_wdata(s_axi_control_wdata),
      .s_axi_control_wstrb(s_axi_control_wstrb),
      .s_axi_control_wvalid(s_axi_control_wvalid),
      .s_axi_control_wready(s_axi_control_wready),
      .s_axi_control_bresp(s_axi_control_bresp),
      .s_axi_control_bvalid(s_axi_control_bvalid),
      .s_axi_control_bready(s_axi_control_bready),
      .s_axi_control_araddr(s_axi_control_araddr),
      .s_axi_control_arvalid(s_axi_control_arvalid),
      .s_axi_control_arready(s_axi_control_arready),
      .s_axi_control_rdata(s_axi_control_rdata),
      .s_axi_control_rresp(s_axi_control_rresp),
      .s_axi_control_rvalid(s_axi_control_rvalid),
      .s_axi_control_rready(s_axi_control_rready),
      .start(start), .busy(busy), .done(done), .eng_flags(eng_flags),
      .eng_err(eng_err),
      .prec_caps({EN_FP256, EN_FP128, EN_FP64, 1'b1}),
      .cfg_op(cfg_op), .cfg_prec(cfg_prec), .cfg_rnd(cfg_rnd), .cfg_n(cfg_n),
      .cfg_a(cfg_a), .cfg_b(cfg_b), .cfg_c(cfg_c), .cfg_d(cfg_d)
  );

  cft_engine_stream #(.LATENCY(15), .EN_FP64(EN_FP64), .EN_FP128(EN_FP128),
                      .EN_FP256(EN_FP256)) u_engine (
      .ap_clk(ap_clk), .ap_rst_n(ap_rst_n),
      .start(start), .busy(busy), .done(done), .flags_acc(eng_flags),
      .err_acc(eng_err),
      .cfg_op(cfg_op), .cfg_prec(cfg_prec), .cfg_rnd(cfg_rnd), .cfg_n(cfg_n),
      .cfg_a(cfg_a), .cfg_b(cfg_b), .cfg_c(cfg_c), .cfg_d(cfg_d),
      .m00_axi_awid(m00_axi_awid), .m00_axi_awaddr(m00_axi_awaddr),
      .m00_axi_awlen(m00_axi_awlen), .m00_axi_awsize(m00_axi_awsize),
      .m00_axi_awburst(m00_axi_awburst), .m00_axi_awlock(m00_axi_awlock),
      .m00_axi_awcache(m00_axi_awcache), .m00_axi_awprot(m00_axi_awprot),
      .m00_axi_awqos(m00_axi_awqos), .m00_axi_awvalid(m00_axi_awvalid),
      .m00_axi_awready(m00_axi_awready), .m00_axi_wdata(m00_axi_wdata),
      .m00_axi_wstrb(m00_axi_wstrb), .m00_axi_wlast(m00_axi_wlast),
      .m00_axi_wvalid(m00_axi_wvalid), .m00_axi_wready(m00_axi_wready),
      .m00_axi_bid(m00_axi_bid), .m00_axi_bresp(m00_axi_bresp),
      .m00_axi_bvalid(m00_axi_bvalid), .m00_axi_bready(m00_axi_bready),
      .m00_axi_arid(m00_axi_arid), .m00_axi_araddr(m00_axi_araddr),
      .m00_axi_arlen(m00_axi_arlen), .m00_axi_arsize(m00_axi_arsize),
      .m00_axi_arburst(m00_axi_arburst), .m00_axi_arlock(m00_axi_arlock),
      .m00_axi_arcache(m00_axi_arcache), .m00_axi_arprot(m00_axi_arprot),
      .m00_axi_arqos(m00_axi_arqos), .m00_axi_arvalid(m00_axi_arvalid),
      .m00_axi_arready(m00_axi_arready), .m00_axi_rid(m00_axi_rid),
      .m00_axi_rdata(m00_axi_rdata), .m00_axi_rresp(m00_axi_rresp),
      .m00_axi_rlast(m00_axi_rlast), .m00_axi_rvalid(m00_axi_rvalid),
      .m00_axi_rready(m00_axi_rready)
  );

endmodule
