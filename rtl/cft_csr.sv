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
//   0x10  MODE    [7:0] op: see docs/ARCHITECTURE.md for the table
//                 [11:8] precision: 0 fp32x8, 1 fp64x4, 2 fp128x2,
//                 3 fp256 - the PREC_CODE ladder; issue only
//                 precisions advertised in CAPS
//                 [14:12] rounding attribute (754 4.3), RISC-V frm
//                 encoding: 0 RNE, 1 RTZ, 2 RDN, 3 RUP, 4 RMM;
//                 5-7 reserved and behave as RNE
//                 The op field is a byte because four bits ran out at
//                 15 opcodes and the integer group needed eight more.
//   0x18  N       element count, 64-bit (lo at 0x18, hi at 0x1C)
//   0x20  A_PTR   64-bit HBM byte address, 32-byte aligned (one beat;
//                 XRT buffer objects are 4 KB aligned anyway)
//   0x28  B_PTR   64-bit
//   0x30  C_PTR   64-bit
//   0x38  D_PTR   64-bit
//   0x40  FLAGS   RO: sticky IEEE flags of the last run
//                 {inexact,underflow,overflow,divzero,invalid};
//                 cleared by hardware at ap_start
//   0x44  MAGIC   RO: 0x43465430 "CFT0"
//   0x48  VERSION RO: 0x00000410 (v0.4.1)
//   0x4C  CAPS    RO: what this bitstream actually implements.
//                 [3:0]  precision bitmask, bit p = MODE precision p
//                        (full tile 0xF; a trimmed open-core tile
//                        clears the banks it cannot fit)
//                 [15:8] opcode-group bitmask:
//                        [8]  arithmetic  fma/add/sub/mul
//                        [9]  sign        abs/neg/copysign
//                        [10] min/max     the four 9.6 forms
//                        [11] predicate   select/cmplt/cmple/cmpeq
//                        [12] integer     the eight bitwise/integer
//                        [13] reduction   reserved
//                        [14] divide/sqrt reserved
//                        [15] conversion  reserved
//                 Groups rather than 256 individual bits, because
//                 opcodes arrive in groups and a bit per opcode is a
//                 register nobody would keep current. A host asks
//                 before issuing; the alternative is guessing from
//                 VERSION, which stops working the moment one build
//                 ships without a group.
//   0x50  STATUS  RO: sticky bus faults from the last run, cleared by
//                 hardware at ap_start. A run that ends with STATUS
//                 non-zero computed on data the memory system did not
//                 vouch for, and its D buffer must not be trusted:
//                 [0] a read response was not OKAY
//                 [1] a write response was not OKAY
//                 [2] a read burst delivered the wrong beat count

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
    input  logic [2:0]  eng_err,     // sticky bus/protocol faults, see STATUS
    input  logic [3:0]  prec_caps,   // constant; from cft_krnl's EN_* params
    input  logic [7:0]  op_caps,     // constant; opcode groups present
    output logic [7:0]  cfg_op,
    output logic [3:0]  cfg_prec,
    output logic [2:0]  cfg_rnd,
    output logic [63:0] cfg_n,
    output logic [63:0] cfg_a,
    output logic [63:0] cfg_b,
    output logic [63:0] cfg_c,
    output logic [63:0] cfg_d
);

  localparam [31:0] MAGIC   = 32'h4346_5430;
  localparam [31:0] VERSION = 32'h0000_0410;

  logic ap_start_q, ap_done_q, ap_idle;
  logic [31:0] gier_q, ier_q;
  logic [31:0] mode_q;
  logic [63:0] n_q, a_q, b_q, c_q, d_q;

  assign ap_idle  = !busy;
  assign cfg_op   = mode_q[7:0];
  assign cfg_prec = mode_q[11:8];
  assign cfg_rnd  = mode_q[14:12];
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
  // Both the mask and the data come from the REGISTERED beat, never
  // from the live bus: do_write is at least one cycle after the W
  // handshake, and AXI4-Lite only requires WDATA to be valid while
  // WVALID is asserted. A master that pipelines its writes (or drives
  // zeros between them) would otherwise have each register commit its
  // successor's payload - invisible to a testbench that waits for
  // BVALID between writes, which is what both of ours do.
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
              // Drop any done left over from the previous run. A host
              // that starts again without reading CTRL first would
              // otherwise see the OLD done immediately and read a
              // half-written D buffer.
              ap_done_q  <= 1'b0;
            end
          end
          10'h001: gier_q <= (gier_q & ~wmask) | (wdata_q & wmask);
          10'h002: ier_q  <= (ier_q  & ~wmask) | (wdata_q & wmask);
          // 0x0C ISR: write-1-to-clear semantics unneeded (no interrupt)
          10'h004: mode_q <= (mode_q & ~wmask) | (wdata_q & wmask);
          10'h006: n_q[31:0]  <= (n_q[31:0]  & ~wmask) | (wdata_q & wmask);
          10'h007: n_q[63:32] <= (n_q[63:32] & ~wmask) | (wdata_q & wmask);
          10'h008: a_q[31:0]  <= (a_q[31:0]  & ~wmask) | (wdata_q & wmask);
          10'h009: a_q[63:32] <= (a_q[63:32] & ~wmask) | (wdata_q & wmask);
          10'h00A: b_q[31:0]  <= (b_q[31:0]  & ~wmask) | (wdata_q & wmask);
          10'h00B: b_q[63:32] <= (b_q[63:32] & ~wmask) | (wdata_q & wmask);
          10'h00C: c_q[31:0]  <= (c_q[31:0]  & ~wmask) | (wdata_q & wmask);
          10'h00D: c_q[63:32] <= (c_q[63:32] & ~wmask) | (wdata_q & wmask);
          10'h00E: d_q[31:0]  <= (d_q[31:0]  & ~wmask) | (wdata_q & wmask);
          10'h00F: d_q[63:32] <= (d_q[63:32] & ~wmask) | (wdata_q & wmask);
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
          10'h013: s_axi_control_rdata <= {16'b0, op_caps, 4'b0, prec_caps};
          10'h014: s_axi_control_rdata <= {29'b0, eng_err};
          default: s_axi_control_rdata <= 32'h0;
        endcase
      end
      if (s_axi_control_rvalid && s_axi_control_rready)
        s_axi_control_rvalid <= 1'b0;
    end
  end

endmodule
