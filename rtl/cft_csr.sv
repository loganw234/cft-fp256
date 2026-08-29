// Copyright 2026 Logan W.
// SPDX-License-Identifier: Apache-2.0
//
// cft_csr: AXI4-Lite control/status block implementing the Vitis
// ap_ctrl_hs protocol plus the kernel's argument registers. The map
// below IS hw/kernel.xml and docs/ARCHITECTURE.md; the three must
// move together.
//
//   0x00  CTRL    [0] ap_start (host sets; cleared when a run ends)
//                 [1] ap_done  (sticky; cleared on read of CTRL)
//                 [2] ap_idle
//                 [3] ap_ready (mirrors ap_done: 1 run per start)
//   0x04  GIER    storage only - interrupt line not exported in v0
//   0x08  IER     storage only
//   0x0C  ISR     reads 0
//   0x10  MODE    [3:0] op: 0 fma, 1 add, 2 sub, 3 mul
//                 [7:4] precision: 0 fp32x8, 3 fp256 (1,2 reserved)
//   0x18  N       element count, 64-bit (lo at 0x18, hi at 0x1C)
//   0x20  A_PTR   64-bit HBM byte address, 64-byte aligned
//   0x28  B_PTR   64-bit
//   0x30  C_PTR   64-bit
//   0x38  D_PTR   64-bit
//   0x40  FLAGS   RO: sticky IEEE flags of the last run
//                 {inexact,underflow,overflow,divzero,invalid};
//                 cleared by hardware at ap_start
//   0x44  MAGIC   RO: 0x43465430 "CFT0"
//   0x48  VERSION RO: 0x00000100 (v0.1.0)

`timescale 1ns/1ps

module cft_csr (
    input  logic        ap_clk,
    input  logic        ap_rst_n,

    // AXI4-Lite slave
    input  logic [11:0] s_axi_control_awaddr,
    input  logic        s_axi_control_awvalid,
    output logic        s_axi_control_awready,
    input  logic [31:0] s_axi_control_wdata,
    input  logic [3:0]  s_axi_control_wstrb,
    input  logic        s_axi_control_wvalid,
    output logic        s_axi_control_wready,
    output logic [1:0]  s_axi_control_bresp,
    output logic        s_axi_control_bvalid,
    input  logic        s_axi_control_bready,
    input  logic [11:0] s_axi_control_araddr,
    input  logic        s_axi_control_arvalid,
    output logic        s_axi_control_arready,
    output logic [31:0] s_axi_control_rdata,
    output logic [1:0]  s_axi_control_rresp,
    output logic        s_axi_control_rvalid,
    input  logic        s_axi_control_rready,

    // engine side
    output logic        start,       // one-cycle pulse
    input  logic        busy,
    input  logic        done,        // one-cycle pulse
    input  logic [4:0]  eng_flags,
    output logic [3:0]  cfg_op,
    output logic [3:0]  cfg_prec,
    output logic [63:0] cfg_n,
    output logic [63:0] cfg_a,
    output logic [63:0] cfg_b,
    output logic [63:0] cfg_c,
    output logic [63:0] cfg_d
);

  localparam [31:0] MAGIC   = 32'h4346_5430;
  localparam [31:0] VERSION = 32'h0000_0100;

  logic ap_start_q, ap_done_q, ap_idle;
  logic [31:0] gier_q, ier_q;
  logic [31:0] mode_q;
  logic [63:0] n_q, a_q, b_q, c_q, d_q;

  assign ap_idle  = !busy;
  assign cfg_op   = mode_q[3:0];
  assign cfg_prec = mode_q[7:4];
  assign cfg_n = n_q;
  assign cfg_a = a_q;
  assign cfg_b = b_q;
  assign cfg_c = c_q;
  assign cfg_d = d_q;

  // ---- write channel ------------------------------------------------
  logic        have_aw, have_w;
  logic [11:0] awaddr_q;
  logic [31:0] wdata_q;
  logic [3:0]  wstrb_q;
  logic        do_write;
  logic [31:0] wmask;

  assign s_axi_control_awready = !have_aw && !s_axi_control_bvalid;
  assign s_axi_control_wready  = !have_w && !s_axi_control_bvalid;
  assign do_write = have_aw && have_w;
  assign wmask = {{8{wstrb_q[3]}}, {8{wstrb_q[2]}}, {8{wstrb_q[1]}}, {8{wstrb_q[0]}}};
  assign s_axi_control_bresp = 2'b00;

  // start pulse: host writes CTRL[0]=1 while idle
  logic start_req;
  assign start_req = do_write && (awaddr_q[11:2] == 10'h000) &&
                     wstrb_q[0] && wdata_q[0];

  always_ff @(posedge ap_clk) begin
    if (!ap_rst_n) begin
      have_aw <= 1'b0;
      have_w  <= 1'b0;
      s_axi_control_bvalid <= 1'b0;
      ap_start_q <= 1'b0;
      ap_done_q  <= 1'b0;
      start      <= 1'b0;
      gier_q <= '0;
      ier_q  <= '0;
      mode_q <= '0;
      n_q <= '0; a_q <= '0; b_q <= '0; c_q <= '0; d_q <= '0;
    end else begin
      start <= 1'b0;

      if (s_axi_control_awvalid && s_axi_control_awready) begin
        have_aw  <= 1'b1;
        awaddr_q <= s_axi_control_awaddr;
      end
      if (s_axi_control_wvalid && s_axi_control_wready) begin
        have_w  <= 1'b1;
        wdata_q <= s_axi_control_wdata;
        wstrb_q <= s_axi_control_wstrb;
      end

      if (do_write) begin
        have_aw <= 1'b0;
        have_w  <= 1'b0;
        s_axi_control_bvalid <= 1'b1;
        // synthesis translate_off
        $display("[CFT-CSR] WR addr=0x%03h data=0x%08h strb=%b",
                 {awaddr_q[11:2], 2'b00}, wdata_q, wstrb_q);
        // synthesis translate_on
        case (awaddr_q[11:2])
          10'h000: begin
            if (start_req && !ap_start_q && !busy) begin
              ap_start_q <= 1'b1;
              start      <= 1'b1;
            end
          end
          10'h001: gier_q <= (gier_q & ~wmask) | (s_axi_control_wdata & wmask);
          10'h002: ier_q  <= (ier_q  & ~wmask) | (s_axi_control_wdata & wmask);
          // 0x0C ISR: write-1-to-clear semantics unneeded (no interrupt)
          10'h004: mode_q <= (mode_q & ~wmask) | (s_axi_control_wdata & wmask);
          10'h006: n_q[31:0]  <= (n_q[31:0]  & ~wmask) | (s_axi_control_wdata & wmask);
          10'h007: n_q[63:32] <= (n_q[63:32] & ~wmask) | (s_axi_control_wdata & wmask);
          10'h008: a_q[31:0]  <= (a_q[31:0]  & ~wmask) | (s_axi_control_wdata & wmask);
          10'h009: a_q[63:32] <= (a_q[63:32] & ~wmask) | (s_axi_control_wdata & wmask);
          10'h00A: b_q[31:0]  <= (b_q[31:0]  & ~wmask) | (s_axi_control_wdata & wmask);
          10'h00B: b_q[63:32] <= (b_q[63:32] & ~wmask) | (s_axi_control_wdata & wmask);
          10'h00C: c_q[31:0]  <= (c_q[31:0]  & ~wmask) | (s_axi_control_wdata & wmask);
          10'h00D: c_q[63:32] <= (c_q[63:32] & ~wmask) | (s_axi_control_wdata & wmask);
          10'h00E: d_q[31:0]  <= (d_q[31:0]  & ~wmask) | (s_axi_control_wdata & wmask);
          10'h00F: d_q[63:32] <= (d_q[63:32] & ~wmask) | (s_axi_control_wdata & wmask);
          default: ;
        endcase
      end
      if (s_axi_control_bvalid && s_axi_control_bready)
        s_axi_control_bvalid <= 1'b0;

      if (done) begin
        ap_done_q  <= 1'b1;
        ap_start_q <= 1'b0;
      end
      // ap_done clears on read of CTRL (handled in the read channel)
      if (s_axi_control_arvalid && s_axi_control_arready &&
          (s_axi_control_araddr[11:2] == 10'h000) && !done)
        ap_done_q <= 1'b0;
    end
  end

  // ---- read channel -------------------------------------------------
  assign s_axi_control_arready = !s_axi_control_rvalid;
  assign s_axi_control_rresp = 2'b00;

  always_ff @(posedge ap_clk) begin
    if (!ap_rst_n) begin
      s_axi_control_rvalid <= 1'b0;
      s_axi_control_rdata  <= '0;
    end else begin
      if (s_axi_control_arvalid && s_axi_control_arready) begin
        s_axi_control_rvalid <= 1'b1;
        case (s_axi_control_araddr[11:2])
          10'h000: s_axi_control_rdata <= {28'b0, ap_done_q, ap_idle, ap_done_q, ap_start_q};
          10'h001: s_axi_control_rdata <= gier_q;
          10'h002: s_axi_control_rdata <= ier_q;
          10'h003: s_axi_control_rdata <= 32'h0;
          10'h004: s_axi_control_rdata <= mode_q;
          10'h006: s_axi_control_rdata <= n_q[31:0];
          10'h007: s_axi_control_rdata <= n_q[63:32];
          10'h008: s_axi_control_rdata <= a_q[31:0];
          10'h009: s_axi_control_rdata <= a_q[63:32];
          10'h00A: s_axi_control_rdata <= b_q[31:0];
          10'h00B: s_axi_control_rdata <= b_q[63:32];
          10'h00C: s_axi_control_rdata <= c_q[31:0];
          10'h00D: s_axi_control_rdata <= c_q[63:32];
          10'h00E: s_axi_control_rdata <= d_q[31:0];
          10'h00F: s_axi_control_rdata <= d_q[63:32];
          10'h010: s_axi_control_rdata <= {27'b0, eng_flags};
          10'h011: s_axi_control_rdata <= MAGIC;
          10'h012: s_axi_control_rdata <= VERSION;
          default: s_axi_control_rdata <= 32'h0;
        endcase
      end
      if (s_axi_control_rvalid && s_axi_control_rready)
        s_axi_control_rvalid <= 1'b0;
    end
  end

endmodule
