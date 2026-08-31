// Copyright 2026 Logan W.
// SPDX-License-Identifier: Apache-2.0
//
// cft_krnl: Vitis RTL kernel top for the Coordinated Fusion Tile.
// ap_ctrl_hs control protocol on s_axi_control, and FOUR 256-bit
// AXI4 masters into the HBM subsystem - one per operand stream
// (m_axi_a/b/c read-only, m_axi_d write-only). 256 bits is the
// native HBM pseudo-channel width, so there is no width converter
// in fabric or emulation.
//
// One master per stream rather than one shared master because the
// shared one was the throughput ceiling: four transfers per beat
// through a port that retires one per cycle. See
// cft_engine_stream's header for the full argument.
//
// Port names follow the Vitis RTL kernel conventions so package_xo
// infers the interfaces; hw/kernel.xml describes the argument map
// (which is cft_csr's).

`timescale 1ns/1ps

module cft_krnl #(
    // Bank trims for constrained targets (open-core conformance
    // nodes); the full Alveo tile keeps all four rungs. fp32 is the
    // baseline and always present. Advertised in the CAPS CSR.
    parameter bit EN_FP64  = 1'b1,
    parameter bit EN_FP128 = 1'b1,
    parameter bit EN_FP256 = 1'b1,
    // The beat is the tile's compute AND memory width; see
    // cft_engine_stream for why they cannot disagree. 256 is
    // correct for Alveo (the HBM pseudo-channel width); narrow it
    // only together with the wide rungs, for a smaller tile.
    parameter int BEAT_BITS = 256,
    // Resource sharing across the banks, both default OFF and both
    // pass-through only - the engine's own headers carry the argument
    // and the measurements. They are exposed here because a parameter
    // no top-level can set cannot be built, measured, or refuted, and
    // FUSE_MUL spent a release in exactly that state.
    parameter bit FUSE_MUL  = 1'b0,
    parameter bit FUSE_NORM = 1'b0,
    parameter bit FUSE_ALIGN = 1'b0
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

    // AXI4 masters to HBM - one per stream. Generated from
    // cft_engine_stream's port list by
    // scratchpad/gen_krnl_ports.py; they are the same list by
    // construction, so they are not maintained twice.

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
    input  logic [BEAT_BITS-1:0] m_axi_a_rdata,
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
    input  logic [BEAT_BITS-1:0] m_axi_b_rdata,
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
    input  logic [BEAT_BITS-1:0] m_axi_c_rdata,
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
    output logic [BEAT_BITS-1:0] m_axi_d_wdata,
    output logic [BEAT_BITS/8-1:0] m_axi_d_wstrb,
    output logic m_axi_d_wlast,
    output logic m_axi_d_wvalid,
    input  logic m_axi_d_wready,
    input  logic [0:0] m_axi_d_bid,
    input  logic [1:0] m_axi_d_bresp,
    input  logic m_axi_d_bvalid,
    output logic m_axi_d_bready
);

  logic        start, busy, done;
  logic [4:0]  eng_flags;
  logic [2:0]  eng_err;
  logic [7:0]  cfg_op;
  logic [3:0]  cfg_prec;
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
      // arithmetic, sign, min/max, predicate, integer and reduction
      // are present; divide/sqrt and conversion are not yet built and
      // their bits stay clear.
      //
      // The reduction bit covers CFT_SUM. CFT_DOT is in the same group
      // and is NOT separate hardware: the contract makes
      // dot(a,b) == sum(mul(a,b)) exact, flags included, so the host
      // issues an elementwise MUL and then a SUM. Advertising the group
      // is therefore honest - both opcodes deliver the contract's
      // answer, one of them via two runs.
      // CAPS[15:8]: arithmetic, sign, min/max, predicate+select,
      // integer, reduction. Divide/sqrt and conversion are not built.
      // Write this as a bit per group and not as a number: it was
      // briefly 8'b0010_1111, which adds reduction and silently drops
      // integer, and eight working opcodes stopped being reachable.
      .op_caps({1'b0,       // [7]   conversion - not built
                1'b1,       // [6]   divide/sqrt (seed opcodes; the
                            //       full operations are FMA-composed
                            //       sequences in the host library)
                1'b1,       // [5]   reduction
                1'b1,       // [4]   integer
                1'b1,       // [3]   predicate + select
                1'b1,       // [2]   min/max
                1'b1,       // [1]   sign
                1'b1}),     // [0]   arithmetic
      .cfg_op(cfg_op), .cfg_prec(cfg_prec), .cfg_rnd(cfg_rnd), .cfg_n(cfg_n),
      .cfg_a(cfg_a), .cfg_b(cfg_b), .cfg_c(cfg_c), .cfg_d(cfg_d)
  );

  cft_engine_stream #(.LATENCY(15), .EN_FP64(EN_FP64), .EN_FP128(EN_FP128),
                      .EN_FP256(EN_FP256), .BEAT_BITS(BEAT_BITS),
                      .FUSE_MUL(FUSE_MUL), .FUSE_NORM(FUSE_NORM),
                      .FUSE_ALIGN(FUSE_ALIGN)) u_engine (
      .ap_clk(ap_clk), .ap_rst_n(ap_rst_n),
      .start(start), .busy(busy), .done(done), .flags_acc(eng_flags),
      .err_acc(eng_err),
      .cfg_op(cfg_op), .cfg_prec(cfg_prec), .cfg_rnd(cfg_rnd), .cfg_n(cfg_n),
      .cfg_a(cfg_a), .cfg_b(cfg_b), .cfg_c(cfg_c), .cfg_d(cfg_d),
      .m_axi_a_arid(m_axi_a_arid), .m_axi_a_araddr(m_axi_a_araddr), .m_axi_a_arlen(m_axi_a_arlen),
      .m_axi_a_arsize(m_axi_a_arsize), .m_axi_a_arburst(m_axi_a_arburst), .m_axi_a_arlock(m_axi_a_arlock),
      .m_axi_a_arcache(m_axi_a_arcache), .m_axi_a_arprot(m_axi_a_arprot), .m_axi_a_arqos(m_axi_a_arqos),
      .m_axi_a_arvalid(m_axi_a_arvalid), .m_axi_a_arready(m_axi_a_arready), .m_axi_a_rid(m_axi_a_rid),
      .m_axi_a_rdata(m_axi_a_rdata), .m_axi_a_rresp(m_axi_a_rresp), .m_axi_a_rlast(m_axi_a_rlast),
      .m_axi_a_rvalid(m_axi_a_rvalid), .m_axi_a_rready(m_axi_a_rready), .m_axi_b_arid(m_axi_b_arid),
      .m_axi_b_araddr(m_axi_b_araddr), .m_axi_b_arlen(m_axi_b_arlen), .m_axi_b_arsize(m_axi_b_arsize),
      .m_axi_b_arburst(m_axi_b_arburst), .m_axi_b_arlock(m_axi_b_arlock), .m_axi_b_arcache(m_axi_b_arcache),
      .m_axi_b_arprot(m_axi_b_arprot), .m_axi_b_arqos(m_axi_b_arqos), .m_axi_b_arvalid(m_axi_b_arvalid),
      .m_axi_b_arready(m_axi_b_arready), .m_axi_b_rid(m_axi_b_rid), .m_axi_b_rdata(m_axi_b_rdata),
      .m_axi_b_rresp(m_axi_b_rresp), .m_axi_b_rlast(m_axi_b_rlast), .m_axi_b_rvalid(m_axi_b_rvalid),
      .m_axi_b_rready(m_axi_b_rready), .m_axi_c_arid(m_axi_c_arid), .m_axi_c_araddr(m_axi_c_araddr),
      .m_axi_c_arlen(m_axi_c_arlen), .m_axi_c_arsize(m_axi_c_arsize), .m_axi_c_arburst(m_axi_c_arburst),
      .m_axi_c_arlock(m_axi_c_arlock), .m_axi_c_arcache(m_axi_c_arcache), .m_axi_c_arprot(m_axi_c_arprot),
      .m_axi_c_arqos(m_axi_c_arqos), .m_axi_c_arvalid(m_axi_c_arvalid), .m_axi_c_arready(m_axi_c_arready),
      .m_axi_c_rid(m_axi_c_rid), .m_axi_c_rdata(m_axi_c_rdata), .m_axi_c_rresp(m_axi_c_rresp),
      .m_axi_c_rlast(m_axi_c_rlast), .m_axi_c_rvalid(m_axi_c_rvalid), .m_axi_c_rready(m_axi_c_rready),
      .m_axi_d_awid(m_axi_d_awid), .m_axi_d_awaddr(m_axi_d_awaddr), .m_axi_d_awlen(m_axi_d_awlen),
      .m_axi_d_awsize(m_axi_d_awsize), .m_axi_d_awburst(m_axi_d_awburst), .m_axi_d_awlock(m_axi_d_awlock),
      .m_axi_d_awcache(m_axi_d_awcache), .m_axi_d_awprot(m_axi_d_awprot), .m_axi_d_awqos(m_axi_d_awqos),
      .m_axi_d_awvalid(m_axi_d_awvalid), .m_axi_d_awready(m_axi_d_awready), .m_axi_d_wdata(m_axi_d_wdata),
      .m_axi_d_wstrb(m_axi_d_wstrb), .m_axi_d_wlast(m_axi_d_wlast), .m_axi_d_wvalid(m_axi_d_wvalid),
      .m_axi_d_wready(m_axi_d_wready), .m_axi_d_bid(m_axi_d_bid), .m_axi_d_bresp(m_axi_d_bresp),
      .m_axi_d_bvalid(m_axi_d_bvalid), .m_axi_d_bready(m_axi_d_bready)
  );

endmodule
