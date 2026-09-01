// Copyright 2026 Logan W.
// SPDX-License-Identifier: Apache-2.0
//
// cft_seq: the orbit sequencer. docs/SEQUENCER.md is the design;
// python/cft_golden/seq.py is the definition of correct; this module
// is verified against that model exactly as the FMA core was against
// softfloat.py. It is a peer of cft_engine_stream behind the same CSR
// block - MODE[15] selects which engine owns a run - computing with
// its own instance of the same verified lane recipe (cft_seq_lanes;
// see that header for the v1 instance-sharing deviation).
//
// ---------------------------------------------------------------
// Behavioural contract (what the bench holds this module to)
// ---------------------------------------------------------------
//
// On start, with cfg_* stable until done:
//
//  1. FETCH. Read the 32-byte program header at cfg_prog, then
//     n_consts format-width constants, then n_insns 64-bit
//     instructions (all little-endian, densely packed in that order;
//     the constant region is NOT beat-padded). The image was
//     validated by cft_program_load, and the hardware re-checks only
//     what protects the hardware:
//         magic  == "CFTP" (0x50544643)
//         format == cfg_prec (a program is compiled for one format)
//         n_insns  <= IMEM_D, n_consts <= KMEM_D,
//         max_deposits <= MAXD, max_deposits >= 1
//     A failure REFUSES the run: done pulses with `refuse` high,
//     nothing was computed, and no memory was written (the header/
//     image reads are the only traffic). Anything subtler - loop
//     structure, reserved bits, unassigned fields - is the loader's
//     to refuse, and the hardware's only obligation to a stream that
//     bypassed the loader is to terminate: an unknown control code
//     executes as HALT, an unmatched ENDREP as HALT.
//
//  2. EXECUTE, in blocks of NBEATS beats = NBEATS * lanes_per_beat
//     lanes. Per block: r0/r1/r2 load from cfg_a/b/c at the block's
//     element offset (r3..r15 start +0), a lane is ACTIVE iff its
//     global index < cfg_n; then the instruction stream runs to HALT
//     under seq.py's semantics - ALU results, deposits and FLAG
//     contributions all masked per-lane by active (P3); REPEAT/ENDREP
//     from a 4-deep loop stack; SETACT narrows on (ra != 0); the
//     early exit tests any(active) at ENDREP with whatever mask is
//     current, which P3 makes free. Issue/drain: one instruction
//     issues over the block's beats back to back, results retire
//     LATENCY later; a dependent chain costs ~2*LATENCY per
//     instruction with every lane busy.
//
//  3. DRAIN, per block: every deposit slot in the block's window of
//     cfg_d is written - a lane's d-th deposit at element index
//     (i * max_deposits + d), slots the lane never reached as +0
//     (P2: addressed by index, never arrival) - then the per-lane
//     deposit counts as uint32 at cfg_cnt + 4*i. Lanes at or beyond
//     cfg_n get neither deposits nor counts: the tail of the caller's
//     buffers is theirs, untouched.
//
//  4. DONE. `flags` is the sticky OR of active-lane contributions
//     across the whole run; err[2:0] carry the engine's three bus
//     faults; err[3] is DEPOSIT OVERFLOW (a lane pushed past
//     max_deposits: the excess dropped, what fit is correct) - the
//     kernel maps it to STATUS[4], STATUS[3] being the refusal.
//
// cfg_prog is 32-byte aligned (the library guarantees it); cfg_cnt is
// 4-byte aligned. n == 0 completes immediately, touching nothing.
//
// The read master serves the program image and the three input
// streams (phases never overlap); the write master serves deposits
// and counts. B and C stay quiet in sequencer runs - bandwidth is not
// what a sequencer run is for, and one read channel keeps the whole
// machine a straight line.

`timescale 1ns/1ps

module cft_seq #(
    parameter int BEAT_BITS  = 256,
    parameter int LATENCY    = 15,
    parameter int NBEATS     = 16,     // lane block; >= LATENCY + 1
    parameter int MAXD       = 64,     // deposit slots per lane, hw cap
    parameter int IMEM_D     = 1024,   // instruction capacity
    parameter int KMEM_D     = 256,    // constant capacity
    parameter int ADDR_W     = 64,
    parameter bit EN_FP64    = 1'b1,
    parameter bit EN_FP128   = 1'b1,
    parameter bit EN_FP256   = 1'b1
)(
    input  logic              ap_clk,
    input  logic              ap_rst_n,

    // run control; cfg_* stable from start to done
    input  logic              start,      // one-cycle pulse
    input  logic [1:0]        cfg_prec,
    input  logic [63:0]       cfg_n,
    input  logic [ADDR_W-1:0] cfg_a,
    input  logic [ADDR_W-1:0] cfg_b,
    input  logic [ADDR_W-1:0] cfg_c,
    input  logic [ADDR_W-1:0] cfg_d,
    input  logic [ADDR_W-1:0] cfg_prog,
    input  logic [ADDR_W-1:0] cfg_cnt,
    output logic              busy,
    output logic              done,       // one-cycle pulse
    output logic              refuse,     // valid with done
    output logic [4:0]        flags,      // valid from done to next start
    output logic [3:0]        err,        // [2:0] bus faults, [3] dep ovf

    // AXI4 read master
    output logic [ADDR_W-1:0] m_rd_araddr,
    output logic [7:0]        m_rd_arlen,
    output logic              m_rd_arvalid,
    input  logic              m_rd_arready,
    input  logic [BEAT_BITS-1:0] m_rd_rdata,
    input  logic              m_rd_rlast,
    input  logic [1:0]        m_rd_rresp,
    input  logic              m_rd_rvalid,
    output logic              m_rd_rready,

    // AXI4 write master
    output logic [ADDR_W-1:0] m_wr_awaddr,
    output logic [7:0]        m_wr_awlen,
    output logic              m_wr_awvalid,
    input  logic              m_wr_awready,
    output logic [BEAT_BITS-1:0] m_wr_wdata,
    output logic [BEAT_BITS/8-1:0] m_wr_wstrb,
    output logic              m_wr_wlast,
    output logic              m_wr_wvalid,
    input  logic              m_wr_wready,
    input  logic [1:0]        m_wr_bresp,
    input  logic              m_wr_bvalid,
    output logic              m_wr_bready
);

  // ------------------------------------------------------------------
  // IMPLEMENTATION IN PROGRESS - this stub elaborates (so the lint
  // gate covers the interface from day one) and refuses every run, so
  // nothing can mistake it for a sequencer. The bench being written
  // against the contract above will fail against this stub by design;
  // green arrives only with the real body.
  // ------------------------------------------------------------------

  logic pending_q;
  always_ff @(posedge ap_clk) begin
    if (!ap_rst_n) begin
      pending_q <= 1'b0;
      done      <= 1'b0;
      refuse    <= 1'b0;
    end else begin
      done   <= pending_q;
      refuse <= pending_q;
      pending_q <= start;
    end
  end
  assign busy  = pending_q;
  assign flags = 5'b0;
  assign err   = 4'b0;

  assign m_rd_araddr  = '0;
  assign m_rd_arlen   = '0;
  assign m_rd_arvalid = 1'b0;
  assign m_rd_rready  = 1'b0;
  assign m_wr_awaddr  = '0;
  assign m_wr_awlen   = '0;
  assign m_wr_awvalid = 1'b0;
  assign m_wr_wdata   = '0;
  assign m_wr_wstrb   = '0;
  assign m_wr_wlast   = 1'b0;
  assign m_wr_wvalid  = 1'b0;
  assign m_wr_bready  = 1'b0;

  // silence unused-signal lint until the body lands
  logic unused;
  assign unused = &{1'b0, cfg_prec, cfg_n, cfg_a, cfg_b, cfg_c, cfg_d,
                    cfg_prog, cfg_cnt, m_rd_rdata, m_rd_rlast, m_rd_rresp,
                    m_rd_rvalid, m_rd_arready, m_wr_awready, m_wr_wready,
                    m_wr_bresp, m_wr_bvalid, 1'b0};

endmodule
