// Copyright 2026 Logan W.
// SPDX-License-Identifier: Apache-2.0
//
// cft_engine_stream: the v1 streaming vector engine. Same CSR
// contract, same compute banks, same delay-line collection and the
// same determinism argument as cft_engine (the naive reference
// engine, which stays in rtl/ as readable spec) - the difference is
// pure microarchitecture:
//
//   - each operand stream has its OWN read-only AXI master, issuing
//     INCR bursts (up to 2^BURST_LOG2 beats, 4KB-boundary safe) with
//     up to AR_DEPTH outstanding, into its own FIFO;
//   - compute issues one beat per cycle whenever all three operand
//     FIFOs are non-empty and the result FIFO has room for
//     everything already in flight;
//   - results collect through the latency-matched delay line into
//     the D FIFO and drain as write bursts on a write-only master.
//
// Read, compute and write all overlap across beats. Element order is
// still total: beats are popped in index order by the single issue
// point and written in index order by the single writer, so the
// determinism contract is untouched - flags remain an order-free OR.
// Four masters do not weaken that argument, because the argument was
// never about the memory system: it is about the single issue point,
// and there is still exactly one.
//
// The four-master arrangement replaced a single shared port, which was
// the throughput ceiling and nothing else. Steady state costs four
// transfers per beat - three operand reads and one result write - and
// one 256-bit port retires one transfer per cycle, so the engine sat
// at ~4.4 cycles/beat however fast the arithmetic ran. The pipe
// accepts a beat every cycle; four ports let it, and pipelined ARs
// stop the per-burst memory latency from putting the bubble straight
// back. Both were roadmap items ("multiple outstanding ARs, per-stream
// HBM pseudo-channels") and neither changes numerics.
//
// hw/link.cfg gives each master its own HBM pseudo-channel group.
// Four masters sharing one group would relocate the bottleneck rather
// than remove it.

`timescale 1ns/1ps

module cft_engine_stream #(
    parameter int LATENCY    = 15,
    parameter bit EN_FP64    = 1'b1,
    parameter bit EN_FP128   = 1'b1,
    parameter bit EN_FP256   = 1'b1,
    parameter int BEAT_BITS  = 256,
    parameter int BURST_LOG2 = 4,   // max beats per AXI burst
    // Per-stream buffer depth (beats). Deeper than the shared-port
    // design needed, because in-flight bursts now reserve space: with
    // AR_DEPTH bursts of BURST_MAX outstanding, that reservation alone
    // is AR_DEPTH*BURST_MAX beats, and anything left over is what
    // actually smooths the stream.
    parameter int FIFO_LOG2  = 7,
    // Bursts in flight per stream. Sized against memory latency, not
    // against the FIFO: a burst is BURST_MAX beats, so hiding an
    // L-cycle latency wants roughly L/BURST_MAX bursts queued behind
    // the one streaming. HBM read latency on this shell is order 60
    // cycles, 16-beat bursts, hence 4.
    parameter int AR_DEPTH   = 4,
    // Share one cft_mulfrac across every lane instead of giving each its
    // own multiplier. Measured NOT to pay on this fabric - see the
    // USE_FUSED_MUL comment below for the numbers and the reason - so it
    // is off, and stays available for the granule-grid work that would.
    parameter bit FUSE_MUL   = 1'b0
) (
    input  logic         ap_clk,
    input  logic         ap_rst_n,

    // control (cft_csr)
    input  logic         start,
    output logic         busy,
    output logic         done,
    output logic [4:0]   flags_acc,
    output logic [2:0]   err_acc,
    input  logic [7:0]   cfg_op,
    input  logic [3:0]   cfg_prec,
    input  logic [2:0]   cfg_rnd,
    input  logic [63:0]  cfg_n,
    input  logic [63:0]  cfg_a,
    input  logic [63:0]  cfg_b,
    input  logic [63:0]  cfg_c,
    input  logic [63:0]  cfg_d,

    // ---- AXI4 masters: one per stream ----------------------------------
    //
    // a, b and c are READ-ONLY masters and d is WRITE-ONLY, which is
    // both what the engine needs and cheaper than four full-duplex
    // ports: Vivado infers the direction from the channels present, so
    // the interconnect never builds a write path for an operand stream.
    //
    // The single shared port this replaces was the design's throughput
    // ceiling and nothing else. Steady state costs four transfers per
    // beat - three operand reads and one result write - and one 256-bit
    // port can retire one transfer per cycle, so the engine sat at
    // ~4.4 cycles/beat no matter how fast the arithmetic was. The
    // arithmetic pipe accepts a beat every cycle. Four ports let it.
    //
    // This is the "per-stream HBM pseudo-channels" roadmap item, and it
    // is why hw/link.cfg now assigns each master its own HBM group:
    // four masters sharing one group would move the bottleneck rather
    // than remove it.

    // a (read-only)
    output logic [0:0]   m_axi_a_arid,
    output logic [63:0]  m_axi_a_araddr,
    output logic [7:0]   m_axi_a_arlen,
    output logic [2:0]   m_axi_a_arsize,
    output logic [1:0]   m_axi_a_arburst,
    output logic         m_axi_a_arlock,
    output logic [3:0]   m_axi_a_arcache,
    output logic [2:0]   m_axi_a_arprot,
    output logic [3:0]   m_axi_a_arqos,
    output logic         m_axi_a_arvalid,
    input  logic         m_axi_a_arready,
    input  logic [0:0]   m_axi_a_rid,
    input  logic [BEAT_BITS-1:0] m_axi_a_rdata,
    input  logic [1:0]   m_axi_a_rresp,
    input  logic         m_axi_a_rlast,
    input  logic         m_axi_a_rvalid,
    output logic         m_axi_a_rready,

    // b (read-only)
    output logic [0:0]   m_axi_b_arid,
    output logic [63:0]  m_axi_b_araddr,
    output logic [7:0]   m_axi_b_arlen,
    output logic [2:0]   m_axi_b_arsize,
    output logic [1:0]   m_axi_b_arburst,
    output logic         m_axi_b_arlock,
    output logic [3:0]   m_axi_b_arcache,
    output logic [2:0]   m_axi_b_arprot,
    output logic [3:0]   m_axi_b_arqos,
    output logic         m_axi_b_arvalid,
    input  logic         m_axi_b_arready,
    input  logic [0:0]   m_axi_b_rid,
    input  logic [BEAT_BITS-1:0] m_axi_b_rdata,
    input  logic [1:0]   m_axi_b_rresp,
    input  logic         m_axi_b_rlast,
    input  logic         m_axi_b_rvalid,
    output logic         m_axi_b_rready,

    // c (read-only)
    output logic [0:0]   m_axi_c_arid,
    output logic [63:0]  m_axi_c_araddr,
    output logic [7:0]   m_axi_c_arlen,
    output logic [2:0]   m_axi_c_arsize,
    output logic [1:0]   m_axi_c_arburst,
    output logic         m_axi_c_arlock,
    output logic [3:0]   m_axi_c_arcache,
    output logic [2:0]   m_axi_c_arprot,
    output logic [3:0]   m_axi_c_arqos,
    output logic         m_axi_c_arvalid,
    input  logic         m_axi_c_arready,
    input  logic [0:0]   m_axi_c_rid,
    input  logic [BEAT_BITS-1:0] m_axi_c_rdata,
    input  logic [1:0]   m_axi_c_rresp,
    input  logic         m_axi_c_rlast,
    input  logic         m_axi_c_rvalid,
    output logic         m_axi_c_rready,

    // d (write-only)
    output logic [0:0]   m_axi_d_awid,
    output logic [63:0]  m_axi_d_awaddr,
    output logic [7:0]   m_axi_d_awlen,
    output logic [2:0]   m_axi_d_awsize,
    output logic [1:0]   m_axi_d_awburst,
    output logic         m_axi_d_awlock,
    output logic [3:0]   m_axi_d_awcache,
    output logic [2:0]   m_axi_d_awprot,
    output logic [3:0]   m_axi_d_awqos,
    output logic         m_axi_d_awvalid,
    input  logic         m_axi_d_awready,
    output logic [BEAT_BITS-1:0] m_axi_d_wdata,
    output logic [BEAT_BITS/8-1:0] m_axi_d_wstrb,
    output logic         m_axi_d_wlast,
    output logic         m_axi_d_wvalid,
    input  logic         m_axi_d_wready,
    input  logic [0:0]   m_axi_d_bid,
    input  logic [1:0]   m_axi_d_bresp,
    input  logic         m_axi_d_bvalid,
    output logic         m_axi_d_bready
);

  localparam logic [1:0] PREC_FP32  = 2'd0;
  localparam logic [1:0] PREC_FP64  = 2'd1;
  localparam logic [1:0] PREC_FP128 = 2'd2;
  localparam logic [1:0] PREC_FP256 = 2'd3;

  // ---- beat geometry -------------------------------------------------
  //
  // BEAT_BITS is the ONE parameter here. Lane counts are not
  // independent knobs: a beat holds BEAT_BITS/width elements of each
  // format, so 256 bits gives 8/4/2/1 and narrowing the beat narrows
  // every bank together. That is the honest shape of the thing - the
  // beat is the tile's compute width AND its memory width, and the two
  // cannot disagree without a width converter, which is exactly what
  // this design refuses to have.
  //
  // A format wider than the beat would need multi-beat elements and an
  // assembly buffer; rather than pretend, the guards below refuse the
  // configuration. So narrowing the beat means dropping the wide rungs
  // with it: BEAT_BITS=64 with fp32+fp64 only is a quarter-tile that
  // fits an Alchitry Au (docs/ROADMAP.md's conformance node), and a
  // 130nm chiplet that wants area back for deposition buffering makes
  // the same trade.
  //
  // 256 is correct for the Alveo path and should stay there: it is the
  // native width of an HBM pseudo-channel, which is why no width
  // converter sits between kernel and memory.
  localparam int BEAT_BYTES = BEAT_BITS / 8;
  localparam int ADDR_SH    = $clog2(BEAT_BYTES);   // byte address step
  localparam int LANE_SH    = $clog2(BEAT_BITS / 32);
  localparam int LANES32    = BEAT_BITS / 32;
  localparam int LANES64    = (BEAT_BITS >= 64)  ? BEAT_BITS / 64  : 0;
  localparam int LANES128   = (BEAT_BITS >= 128) ? BEAT_BITS / 128 : 0;
  localparam int LANES256   = (BEAT_BITS >= 256) ? BEAT_BITS / 256 : 0;

  generate
    if (BEAT_BITS != (1 << ADDR_SH) * 8)
      $error("BEAT_BITS must be a power of two");
    if (BEAT_BITS < 32)
      $error("BEAT_BITS must hold at least one fp32 element");
    if (EN_FP64 && BEAT_BITS < 64)
      $error("EN_FP64 needs BEAT_BITS >= 64");
    if (EN_FP128 && BEAT_BITS < 128)
      $error("EN_FP128 needs BEAT_BITS >= 128");
    if (EN_FP256 && BEAT_BITS < 256)
      $error("EN_FP256 needs BEAT_BITS >= 256");
    // Upper bound, deliberately. This parameterization exists to make
    // the tile SMALLER - a quarter-tile for an open-core conformance
    // node, or a chiplet trading lanes for deposition buffer. Going
    // wider than 256 would put two fp256 elements in a beat, and the
    // fp256 bank is a single instance rather than a generate loop, so
    // it would silently compute only the low one. Refuse instead.
    // (256 is also the native HBM pseudo-channel width, and a 512-bit
    // master demonstrably lost write payloads through this platform's
    // emulation models - see docs/BRINGUP.md.)
    if (BEAT_BITS > 256)
      $error("BEAT_BITS > 256 needs the fp256 bank to become a loop");
  endgenerate


  localparam int BURST_MAX = 1 << BURST_LOG2;
  localparam int FDEPTH    = 1 << FIFO_LOG2;
  localparam logic [7:0] AR_MAX = AR_DEPTH;

  // The writer starts a burst only once the result FIFO holds the
  // whole burst, so a burst longer than the FIFO can never start and
  // the engine would deadlock with beats still outstanding. Equality
  // is legal but degenerate (writes could only begin with the FIFO
  // completely full, stalling read and compute for the whole burst),
  // so demand real headroom.
  // Generate scope AND initial, for the reason cft_fpfma_pipe's guards
  // spell out: Yosys and Vivado honour the elaboration-time $error and
  // ignore `initial`, Icarus is the reverse, so one form alone leaves
  // some toolchain able to build a deadlocking design.
  //
  // The second guard is new with pipelined ARs and is the sharper of
  // the two. AR_DEPTH bursts in flight reserve AR_DEPTH*BURST_MAX
  // beats; if that exceeds the FIFO, the reservation arithmetic
  // saturates at zero free space and the stream deadlocks with ARs
  // issued and nowhere to put their data. Caught at elaboration
  // because the symptom - a run that starts and never completes - is
  // indistinguishable from a dozen other faults at runtime.
  generate
    if (BURST_MAX >= FDEPTH) begin : g_burst_exceeds_fifo
      $error("cft_engine_stream: BURST_LOG2 must be less than FIFO_LOG2");
    end
    if (AR_DEPTH < 1) begin : g_ar_depth_zero
      $error("cft_engine_stream: AR_DEPTH must be at least 1");
    end
    if (AR_DEPTH * BURST_MAX > FDEPTH) begin : g_ar_depth_exceeds_fifo
      $error("cft_engine_stream: AR_DEPTH*BURST_MAX must fit the stream FIFO");
    end
  endgenerate

  initial begin
    if (AR_DEPTH < 1 || AR_DEPTH * BURST_MAX > FDEPTH) begin
      $display("FATAL: cft_engine_stream AR_DEPTH (%0d) * BURST_MAX (%0d) must fit FDEPTH (%0d)",
               AR_DEPTH, BURST_MAX, FDEPTH);
      $finish;
    end
    if (BURST_MAX >= FDEPTH) begin
      $display("FATAL: cft_engine_stream needs BURST_LOG2 (%0d) < FIFO_LOG2 (%0d)",
               BURST_LOG2, FIFO_LOG2);
      $fatal(1);
    end
  end

  // sticky bus faults, reported through the STATUS CSR
  localparam int ERR_RRESP = 0;
  localparam int ERR_BRESP = 1;
  localparam int ERR_RLEN  = 2;

  // constant AXI attributes. One ID per master, and only one: read
  // responses on a single ID return in issue order, which is what lets
  // ARs be pipelined without any reorder buffer.
  assign m_axi_a_arid    = 1'b0;
  assign m_axi_a_arsize  = ADDR_SH[2:0];   // log2(BEAT_BYTES)
  assign m_axi_a_arburst = 2'd1;           // INCR
  assign m_axi_a_arlock  = 1'b0;
  assign m_axi_a_arcache = 4'b0011;
  assign m_axi_a_arprot  = 3'b000;
  assign m_axi_a_arqos   = 4'd0;

  assign m_axi_b_arid    = 1'b0;
  assign m_axi_b_arsize  = ADDR_SH[2:0];
  assign m_axi_b_arburst = 2'd1;
  assign m_axi_b_arlock  = 1'b0;
  assign m_axi_b_arcache = 4'b0011;
  assign m_axi_b_arprot  = 3'b000;
  assign m_axi_b_arqos   = 4'd0;

  assign m_axi_c_arid    = 1'b0;
  assign m_axi_c_arsize  = ADDR_SH[2:0];
  assign m_axi_c_arburst = 2'd1;
  assign m_axi_c_arlock  = 1'b0;
  assign m_axi_c_arcache = 4'b0011;
  assign m_axi_c_arprot  = 3'b000;
  assign m_axi_c_arqos   = 4'd0;

  assign m_axi_d_awid    = 1'b0;
  assign m_axi_d_awsize  = ADDR_SH[2:0];
  assign m_axi_d_awburst = 2'd1;
  assign m_axi_d_awlock  = 1'b0;
  assign m_axi_d_awcache = 4'b0011;
  assign m_axi_d_awprot  = 3'b000;
  assign m_axi_d_awqos   = 4'd0;
  assign m_axi_d_wstrb   = {BEAT_BYTES{1'b1}};

  // ---- run control ---------------------------------------------------
  logic         running;
  logic [1:0]   prec_r;
  logic [7:0]   op_r;
  logic [2:0]   rnd_r;
  logic [63:0]  beats_total;
  logic [63:0]  n_elems;      // elements, for the reduction serializer
  logic [63:0]  base_a, base_b, base_c, base_d;

  // Beats this run will stream.
  //
  // Elementwise TRUNCATES, and that is the long-standing contract: N is
  // a whole number of beats, the host pads the tail with zeros, and
  // zero operands raise nothing so the flags cannot depend on the
  // padding (api_test checks exactly that for all 256 opcodes).
  //
  // A reduction cannot use that contract. Padding a sum with +0.0 is
  // not the identity - it destroys a negative-zero result and perturbs
  // the directed attributes - so the host hands over the TRUE element
  // count and the engine reads ceil(n / elements-per-beat) beats,
  // consuming only the real elements from the last one. Truncating here
  // silently drops the tail: n=1 fp32 became zero beats and finished
  // having summed nothing, and n=7 fp128 summed six of seven.
  logic [5:0]  beat_sh;
  logic [63:0] beats_new;
  logic        cfg_is_reduce;
  assign beat_sh       = 6'(LANE_SH) - {4'b0, cfg_prec[1:0]};
  assign cfg_is_reduce = (cfg_op == 8'd24);
  assign beats_new = cfg_is_reduce
                     ? ((cfg_n + ((64'd1 << beat_sh) - 64'd1)) >> beat_sh)
                     : (cfg_n >> beat_sh);

  logic start_accept, fifo_clear, wfinish;
  assign start_accept = start && !running;
  assign fifo_clear   = start_accept;
  assign busy = running;

  always_ff @(posedge ap_clk) begin
    if (!ap_rst_n) begin
      running <= 1'b0;
      done <= 1'b0;
      prec_r <= 2'd0;
      op_r <= 8'd0;
      rnd_r <= 3'd0;
      beats_total <= '0;
      n_elems <= '0;
      base_a <= '0; base_b <= '0; base_c <= '0; base_d <= '0;
    end else begin
      done <= 1'b0;
      if (start_accept) begin
        // synthesis translate_off
        $display("[CFT-ENGS] START op=%0d prec=%0d n=%0d beats=%0d a=0x%h b=0x%h c=0x%h d=0x%h",
                 cfg_op, cfg_prec, cfg_n, beats_new, cfg_a, cfg_b, cfg_c, cfg_d);
        // synthesis translate_on
        // Everything the run depends on is snapshot here. op and rnd
        // used to be read combinationally, which meant a MODE write
        // landing mid-run changed the arithmetic partway through the
        // array - and the split point depended on memory timing, so
        // the same host program could produce different bits on
        // different runs. That is the exact failure this design
        // exists to rule out.
        prec_r <= cfg_prec[1:0];
        op_r   <= cfg_op;
        rnd_r  <= cfg_rnd;
        beats_total <= beats_new;
        // Element count, not beat count. A reduction must stop at the
        // real elements: the beat padding is zeros, and adding +0.0 is
        // not the identity on this type.
        n_elems <= cfg_n;
        base_a <= cfg_a; base_b <= cfg_b; base_c <= cfg_c; base_d <= cfg_d;
        // beats_new == 0 finishes immediately WITHOUT writing anything.
        //
        // That is right for an elementwise run - zero elements, zero
        // results - but for a REDUCTION the contract says n=0 returns
        // +0.0, and this path writes no D beat at all, so the
        // destination keeps whatever it held. FLAGS is correctly zero,
        // which makes it look like a clean answer.
        //
        // The contract is kept by the HOST: cft_reduce returns +0.0
        // before it ever reaches a backend, so n=0 never arrives here.
        // cft_reduce_acc's own "nothing was accumulated" branch is
        // therefore unreachable through the engine and untested. If
        // that short-circuit is ever removed, or a non-libcft host
        // drives the CSRs directly, THIS is the line that has to
        // change - emit one beat of +0.0 for a reduction instead of
        // finishing silently.
        if (beats_new == 0) done <= 1'b1;
        else running <= 1'b1;
      end
      if (wfinish) begin
        running <= 1'b0;
        done <= 1'b1;
        // synthesis translate_off
        // The engine logs its start, its bursts and each result beat,
        // but never logged finishing - so a run that executed and a
        // run that stalled waiting for a write response looked
        // identical from the log, and telling them apart is exactly
        // what you need when a host says a kernel never completed.
        $display("[CFT-ENGS] DONE beats=%0d flags=%b err=%b",
                 beats_total, flags_acc, err_acc);
        // synthesis translate_on
      end
    end
  end
  // flags_acc lives in its own block at the end of the module, after
  // beat_f exists

  // ---- stream FIFOs --------------------------------------------------
  logic         a_wr, b_wr, c_wr, abc_rd, d_wr, d_rd;
  logic [BEAT_BITS-1:0] a_q, b_q, c_q, d_qout;
  logic [FIFO_LOG2:0] a_cnt, b_cnt, c_cnt, d_cnt;

  cft_fifo #(.WIDTH(256), .DEPTH_LOG2(FIFO_LOG2)) u_fifo_a (
      .clk(ap_clk), .rst_n(ap_rst_n), .clear(fifo_clear),
      .wr_en(a_wr), .wr_data(m_axi_a_rdata),
      .rd_en(abc_rd), .rd_data(a_q), .count(a_cnt));
  cft_fifo #(.WIDTH(256), .DEPTH_LOG2(FIFO_LOG2)) u_fifo_b (
      .clk(ap_clk), .rst_n(ap_rst_n), .clear(fifo_clear),
      .wr_en(b_wr), .wr_data(m_axi_b_rdata),
      .rd_en(abc_rd), .rd_data(b_q), .count(b_cnt));
  cft_fifo #(.WIDTH(256), .DEPTH_LOG2(FIFO_LOG2)) u_fifo_c (
      .clk(ap_clk), .rst_n(ap_rst_n), .clear(fifo_clear),
      .wr_en(c_wr), .wr_data(m_axi_c_rdata),
      .rd_en(abc_rd), .rd_data(c_q), .count(c_cnt));

  // ---- readers: one per stream, ARs pipelined ------------------------
  //
  // Three identical readers, each owning a master. There is no
  // arbitration left to get wrong - the a > b > c priority existed only
  // because one port had to be shared, and sharing was the bottleneck.
  //
  // Each reader keeps up to AR_DEPTH bursts in flight. That is not a
  // refinement, it is what makes the dedicated port worth having: with
  // a single outstanding AR the reader must wait out the full memory
  // latency after every RLAST before the next burst's first beat
  // arrives, and on HBM that bubble is comparable to the burst itself.
  // A 16-beat burst followed by a ~60-cycle bubble is ~4.8 cycles/beat,
  // which is where the shared port already was. Pipelining the ARs is
  // what turns four ports into four times the throughput.
  //
  // Ordering is safe with a single AXI ID: responses on one ID return
  // in issue order, so beats arrive in address order and the FIFO stays
  // an index-ordered stream. The determinism argument is untouched -
  // it was never about the memory system, only about issue order at the
  // single compute point, which is unchanged.
  //
  // FIFO space is reserved at AR time, not at R time. Two bursts in
  // flight can together exceed the free space that each looked at
  // separately, and the resulting overflow would corrupt operands
  // rather than stall - so `reserved` counts beats promised by
  // in-flight ARs and every free-space test subtracts it.

  logic [63:0] rd_issued [0:2];   // beats whose AR has gone out
  logic [7:0]  rd_outst  [0:2];   // bursts in flight
  // Beats promised by in-flight ARs and not yet arrived. Sixteen bits,
  // not FIFO_LOG2-derived: the value is bounded by AR_DEPTH*BURST_MAX
  // (at most 256, since ARLEN is a byte) and a width tied to FIFO_LOG2
  // makes every add and part-select depend on a parameter, which is how
  // `len[FIFO_LOG2+1:0]` came to select bit 8 of an 8-bit signal.
  logic [15:0] rd_resv   [0:2];

  // per-stream port fan-out, so the readers can be one generate block
  logic [63:0]        rd_araddr  [0:2];
  logic [7:0]         rd_arlen   [0:2];
  logic               rd_arvalid [0:2];
  logic               rd_arready [0:2];
  logic               rd_rvalid  [0:2];
  logic               rd_rlast   [0:2];
  logic               rd_wr      [0:2];
  logic [63:0]        rd_base    [0:2];
  logic [FIFO_LOG2:0] rd_cnt     [0:2];
  logic [2:0]         rlen_err;

  assign rd_base[0] = base_a;
  assign rd_base[1] = base_b;
  assign rd_base[2] = base_c;
  assign rd_cnt[0]  = a_cnt;
  assign rd_cnt[1]  = b_cnt;
  assign rd_cnt[2]  = c_cnt;

  assign m_axi_a_arvalid = rd_arvalid[0];
  assign m_axi_a_araddr  = rd_araddr[0];
  assign m_axi_a_arlen   = rd_arlen[0] - 8'd1;
  assign m_axi_a_rready  = 1'b1;
  assign rd_arready[0]   = m_axi_a_arready;
  assign rd_rvalid[0]    = m_axi_a_rvalid;
  assign rd_rlast[0]     = m_axi_a_rlast;

  assign m_axi_b_arvalid = rd_arvalid[1];
  assign m_axi_b_araddr  = rd_araddr[1];
  assign m_axi_b_arlen   = rd_arlen[1] - 8'd1;
  assign m_axi_b_rready  = 1'b1;
  assign rd_arready[1]   = m_axi_b_arready;
  assign rd_rvalid[1]    = m_axi_b_rvalid;
  assign rd_rlast[1]     = m_axi_b_rlast;

  assign m_axi_c_arvalid = rd_arvalid[2];
  assign m_axi_c_araddr  = rd_araddr[2];
  assign m_axi_c_arlen   = rd_arlen[2] - 8'd1;
  assign m_axi_c_rready  = 1'b1;
  assign rd_arready[2]   = m_axi_c_arready;
  assign rd_rvalid[2]    = m_axi_c_rvalid;
  assign rd_rlast[2]     = m_axi_c_rlast;

  // RREADY is tied high on all three, and that is safe BECAUSE space
  // was reserved at AR time: the engine never asks for a beat it has
  // nowhere to put. Holding RREADY low to throttle would be the
  // alternative and it costs a cycle of latency on every beat.
  assign a_wr = rd_wr[0];
  assign b_wr = rd_wr[1];
  assign c_wr = rd_wr[2];

  // beats this burst may cover: min(BURST_MAX, remaining, beats to the
  // 4KB AXI boundary, UNRESERVED FIFO space). Addresses are 32B-aligned
  // by the host contract, so the boundary term is never zero.
  function automatic logic [7:0] burst_len(
      input logic [63:0] rem,
      input logic [63:0] addr,
      input logic [FIFO_LOG2:0] cnt,
      input logic [15:0]        resv);
    logic [63:0] bound, free, used, l;
    begin
      // Beats to the next 4KB boundary. The shift is ADDR_SH, not a
      // literal 5: 5 is log2(32) and only correct while BEAT_BITS is
      // 256. The quarter tile (BEAT_BITS=64) has 8-byte beats, where a
      // hardcoded 5 understates the distance by 4x. Harmless today
      // because BURST_MAX bounds it first either way, but it is a
      // parameterization bug sitting in the one function whose job is
      // to respect a hard AXI rule.
      bound = (64'd4096 - {52'd0, addr[11:0]}) >> ADDR_SH;
      used  = {{(63-FIFO_LOG2){1'b0}}, cnt} + {48'd0, resv};
      free  = (used >= FDEPTH) ? 64'd0 : (FDEPTH - used);
      l = BURST_MAX;
      if (rem   < l) l = rem;
      if (bound < l) l = bound;
      if (free  < l) l = free;
      burst_len = l[7:0];
    end
  endfunction

  genvar rs;
  generate
    for (rs = 0; rs < 3; rs = rs + 1) begin : g_reader
      logic [63:0] rem, addr;
      logic [7:0]  len;
      logic        launch;

      // The function's arguments are read into local SCALARS first, and
      // that is not stylistic. Passing unpacked-array elements
      // (rd_cnt[rs], rd_resv[rs]) straight into a function called from
      // always_comb leaves Icarus unable to build a correct implicit
      // sensitivity list for them, and the block then re-triggers on
      // itself: the simulation spins at time 0 at full CPU and never
      // reaches the first clock edge. The original code passed scalars
      // and worked; the array indexing arrived with the per-stream
      // generate loop and took the sensitivity inference with it.
      logic [FIFO_LOG2:0] cnt_s;
      logic [15:0]        resv_s;
      logic [63:0]        issued_s;
      logic [63:0]        base_s;

      assign cnt_s    = rd_cnt[rs];
      assign resv_s   = rd_resv[rs];
      assign issued_s = rd_issued[rs];
      assign base_s   = rd_base[rs];

      assign rem  = beats_total - issued_s;
      assign addr = base_s + (issued_s << ADDR_SH);
      assign len  = burst_len(rem, addr, cnt_s, resv_s);

      // The AR request is REGISTERED, and it has to be. addr and len
      // above are combinational on rd_cnt, the FIFO occupancy, which
      // falls every time compute pops a beat - so driving them straight
      // at the port would change ARADDR and ARLEN while ARVALID was
      // asserted and waiting for ARREADY. AXI4 forbids that (A3.2.1:
      // the source must hold payload stable until the handshake), and
      // the failure it produces is not a clean protocol error: the
      // slave latches one length and the reader accounts for another,
      // so the FIFO reservation stops matching the beats that arrive.
      logic [63:0] ar_addr_q;
      logic [7:0]  ar_len_q;
      logic        ar_pend;

      // Commit at LAUNCH, not at handshake: rd_issued, the reservation
      // and the outstanding count all advance when the burst is decided,
      // so the next candidate address is computed from a state that
      // already includes it. Deciding at handshake instead would let the
      // combinational len re-derive the same burst twice.
      assign launch = running && !ar_pend && (len != 8'd0) &&
                      (rd_outst[rs] < AR_MAX);

      assign rd_araddr[rs]  = ar_addr_q;
      assign rd_arlen[rs]   = ar_len_q;
      assign rd_arvalid[rs] = ar_pend;
      assign rd_wr[rs]      = rd_rvalid[rs];

      always_ff @(posedge ap_clk) begin
        if (!ap_rst_n || !running) begin
          rd_issued[rs] <= '0;
          rd_outst[rs]  <= '0;
          rd_resv[rs]   <= '0;
          ar_pend       <= 1'b0;
          ar_addr_q     <= '0;
          ar_len_q      <= '0;
        end else begin
          logic r_go;
          r_go = rd_rvalid[rs];

          if (launch) begin
            ar_addr_q <= addr;
            ar_len_q  <= len;
            ar_pend   <= 1'b1;
            rd_issued[rs] <= rd_issued[rs] + {56'd0, len};
            // synthesis translate_off
            $display("[CFT-ENGS] AR s=%0d addr=0x%h len=%0d", rs, addr, len);
            // synthesis translate_on
          end else if (ar_pend && rd_arready[rs]) begin
            ar_pend <= 1'b0;
          end

          // outstanding: +1 per launch, -1 per RLAST. Both can happen in
          // the same cycle once bursts are pipelined, so the update is
          // written as a single expression rather than two ifs - the
          // sequential form loses one of them.
          rd_outst[rs] <= rd_outst[rs]
                          + (launch ? 8'd1 : 8'd0)
                          - ((r_go && rd_rlast[rs]) ? 8'd1 : 8'd0);

          // reserved: +len per launch, -1 per beat received. Same reason.
          rd_resv[rs] <= rd_resv[rs]
                         + (launch ? {8'd0, len} : 16'd0)
                         - (r_go   ? 16'd1 : 16'd0);
        end
      end

      // ---- RLAST placement check ------------------------------------
      //
      // RLAST must land on exactly the beat ARLEN asked for. A short
      // burst starves compute forever; a long one overruns the FIFO
      // past its reservation and corrupts operands. Both are silent
      // without this.
      //
      // Pipelined ARs made it need a queue: with several bursts in
      // flight the length to check against is the OLDEST outstanding
      // one, not the most recently issued. Depth AR_DEPTH, which is
      // exactly how many can be waiting.
      logic [7:0] len_q [0:AR_DEPTH-1];
      logic [7:0] beat_ctr;
      logic [$clog2(AR_DEPTH):0] len_wp, len_rp;

      always_ff @(posedge ap_clk) begin
        if (!ap_rst_n || !running) begin
          beat_ctr <= 8'd0;
          len_wp   <= '0;
          len_rp   <= '0;
          rlen_err[rs] <= 1'b0;
        end else begin
          // Pushed at launch, matching where the burst is committed.
          if (launch) begin
            len_q[len_wp[$clog2(AR_DEPTH)-1:0]] <= len;
            len_wp <= len_wp + 1'b1;
          end
          if (rd_rvalid[rs]) begin
            if (rd_rlast[rs]) begin
              // last beat of this burst: the count must match
              if ((beat_ctr + 8'd1) != len_q[len_rp[$clog2(AR_DEPTH)-1:0]])
                rlen_err[rs] <= 1'b1;
              beat_ctr <= 8'd0;
              len_rp <= len_rp + 1'b1;
            end else begin
              // not last: overrunning the expected length is the
              // other half of the same fault
              if ((beat_ctr + 8'd1) >= len_q[len_rp[$clog2(AR_DEPTH)-1:0]])
                rlen_err[rs] <= 1'b1;
              beat_ctr <= beat_ctr + 8'd1;
            end
          end
        end
      end
    end
  endgenerate

  // ---- reductions ----------------------------------------------------
  //
  // CFT_SUM (opcode 24) folds the whole array into ONE element using
  // the tree python/cft_golden/reduce.py defines. The hardware for it
  // is cft_reduce_acc, a streaming binary-counter accumulator; this
  // block feeds it and borrows an adder for it.
  //
  // CFT_DOT (25) is NOT built, and does not need to be. The contract
  // says dot(a,b) == sum(mul(a,b)) exactly, flags included, so the host
  // issues an elementwise MUL and then a SUM and gets bit-identical
  // results from hardware that already exists. Building a second
  // datapath - a multiply pass sharing the same pipe as the
  // accumulator's adds, with tagged results and arbitration between
  // them - would buy one saved round trip at the cost of the most
  // schedule-sensitive logic in the engine. The composition property
  // was put in the contract partly so this choice would be available.
  localparam logic [7:0] OP_SUM = 8'd24;
  localparam logic [7:0] OP_DOT = 8'd25;

  // Declared here rather than beside the bank mux that drives them: the
  // accumulator borrows the active bank's adder, so it needs the bank
  // result before the mux appears further down.
  logic [BEAT_BITS-1:0] beat_d;
  logic [4:0]           beat_f;

  logic is_reduce;
  assign is_reduce = (op_r == OP_SUM);

  // Elements per beat at the active precision, and how many of them are
  // real in the LAST beat. Padding a reduction with +0.0 is not the
  // identity - see the model - so the serializer stops at the true
  // element count rather than running to the end of the beat.
  //
  // DERIVED from LANE_SH, not a case on prec_r. It has to be the same
  // function the beat COUNT uses (beat_sh above) or the two disagree
  // about how many elements a beat holds: 8/4/2/1 is only right at
  // BEAT_BITS=256, and at the quarter tile's 64 a beat holds 2 fp32,
  // not 8. The serializer would then walk four elements off the end of
  // every beat, and `n_elems - beat*epb` would underflow on the second
  // beat and fold twelve "elements" for an n of four.
  logic [5:0] epb;
  assign epb = 6'd1 << (6'(LANE_SH) - {4'b0, prec_r[1:0]});

  logic [63:0] ser_beat_idx;
  logic [5:0]  ser_idx, ser_cnt;
  logic        ser_busy;
  logic [BEAT_BITS-1:0] ser_data;

  logic red_in_valid, red_in_ready;
  logic [BEAT_BITS-1:0] red_in_elem;

  // The active element, right-aligned. Everything above the element's
  // width is zero and the accumulator never looks at it; the adder it
  // hands work to is the one for this precision.
  always_comb begin
    red_in_elem = '0;
    case (prec_r)
      PREC_FP64:  red_in_elem[63:0]  = ser_data[ser_idx*64  +: 64];
      PREC_FP128: red_in_elem[127:0] = ser_data[ser_idx*128 +: 128];
      PREC_FP256: red_in_elem        = ser_data;
      default:    red_in_elem[31:0]  = ser_data[ser_idx*32  +: 32];
    endcase
  end

  assign red_in_valid = ser_busy && (ser_idx < ser_cnt);

  logic red_take_beat;            // pop a beat into the serializer
  // All three operand FIFOs share one read enable, so a reduction that
  // only looks at `a` still pops b and c - and cft_fifo has no underflow
  // guard by design ("callers check count"). So all three must be
  // non-empty, exactly as the elementwise path requires.
  assign red_take_beat = is_reduce && running && !ser_busy &&
                         (a_cnt != 0) && (b_cnt != 0) && (c_cnt != 0) &&
                         (ser_beat_idx < beats_total);

  always_ff @(posedge ap_clk) begin
    if (!ap_rst_n || !running) begin
      ser_busy     <= 1'b0;
      ser_idx      <= '0;
      ser_cnt      <= '0;
      ser_beat_idx <= '0;
      ser_data     <= '0;
    end else if (is_reduce) begin
      if (red_take_beat) begin
        ser_data <= a_q;
        ser_idx  <= '0;
        // real elements left, capped at one beat
        ser_cnt  <= ((n_elems - ser_beat_idx * {58'd0, epb}) < {58'd0, epb})
                    ? (n_elems - ser_beat_idx * {58'd0, epb})
                    : {58'd0, epb};
        ser_beat_idx <= ser_beat_idx + 64'd1;
        ser_busy <= 1'b1;
      end else if (ser_busy && red_in_valid && red_in_ready) begin
        if ((ser_idx + 6'd1) >= ser_cnt) ser_busy <= 1'b0;
        ser_idx <= ser_idx + 6'd1;
      end
    end
  end

  logic                 red_add_valid;
  logic [BEAT_BITS-1:0] red_add_a, red_add_b;
  logic                 red_flush, red_out_valid;
  logic [BEAT_BITS-1:0] red_out_data;
  logic [4:0]           red_out_flags;

  // Flush once every element has been handed over.
  assign red_flush = is_reduce && running && !ser_busy &&
                     (ser_beat_idx >= beats_total);

  // The bank result, masked to the active element. Lanes 1..7 are
  // computing nothing meaningful while a reduction runs, so their bits
  // of the beat are noise; keeping them out of the accumulator means
  // the value it eventually writes is the element and nothing else.
  logic [BEAT_BITS-1:0] red_add_res;
  always_comb begin
    red_add_res = '0;
    case (prec_r)
      PREC_FP64:  red_add_res[63:0]  = beat_d[63:0];
      PREC_FP128: red_add_res[127:0] = beat_d[127:0];
      PREC_FP256: red_add_res        = beat_d;
      default:    red_add_res[31:0]  = beat_d[31:0];
    endcase
  end

  cft_reduce_acc #(.W(BEAT_BITS), .LEVELS(40), .ADD_LATENCY(LATENCY))
  u_reduce (
      .clk(ap_clk), .rst_n(ap_rst_n), .clear(start_accept),
      .in_valid(red_in_valid && is_reduce), .in_data(red_in_elem),
      .in_ready(red_in_ready),
      .flush(red_flush),
      .add_valid(red_add_valid), .add_a(red_add_a), .add_b(red_add_b),
      .add_res(red_add_res), .add_flags(beat_f),
      .out_valid(red_out_valid), .out_data(red_out_data),
      .out_flags(red_out_flags));

  // The result is pushed once. out_valid latches high and stays there
  // until the next clear, so an edge is what the FIFO wants.
  logic red_pushed, red_push;
  assign red_push = is_reduce && red_out_valid && !red_pushed;

  always_ff @(posedge ap_clk) begin
    if (!ap_rst_n || start_accept) red_pushed <= 1'b0;
    else if (red_push)             red_pushed <= 1'b1;
  end

  // ---- compute issue and collection ----------------------------------
  logic [63:0] issued_beats;
  logic [7:0]  inflight;
  logic        ex_valid, collect;

  // In reduction mode the elementwise path is idle: the only work the
  // banks do is the accumulator's adds, issued through lane 0.
  assign ex_valid = running && !is_reduce &&
                    (issued_beats < beats_total) &&
                    (a_cnt != 0) && (b_cnt != 0) && (c_cnt != 0) &&
                    ((d_cnt + inflight) < FDEPTH);

  // The serializer owns the operand FIFOs while reducing. It pops only
  // the `a` stream's beat, but all three advance together because they
  // share one read enable and the host supplies all three pointers.
  assign abc_rd = is_reduce ? red_take_beat : ex_valid;

  logic [LATENCY-1:0] vdl;
  assign collect = vdl[LATENCY-1];

  always_ff @(posedge ap_clk) begin
    if (!ap_rst_n) begin
      issued_beats <= '0;
      inflight <= 8'd0;
      vdl <= '0;
    end else if (!running) begin
      issued_beats <= '0;
      inflight <= 8'd0;
      vdl <= {vdl[LATENCY-2:0], 1'b0};
    end else begin
      vdl <= {vdl[LATENCY-2:0], ex_valid};
      if (ex_valid) issued_beats <= issued_beats + 64'd1;
      inflight <= inflight + (ex_valid ? 8'd1 : 8'd0) - (collect ? 8'd1 : 8'd0);
    end
  end

  // Elementwise pushes a beat per result; a reduction pushes one beat,
  // once, when the accumulator has folded everything.
  assign d_wr = is_reduce ? red_push : collect;

  // The writer's beat count. One for a reduction, whatever the run
  // asked for otherwise - and it has to be a separate signal from
  // beats_total, which is still what the READERS stream.
  logic [63:0] wr_total;
  assign wr_total = is_reduce ? 64'd1 : beats_total;

  // ---- the fractured significand array -------------------------------
  //
  // One cft_mulfrac replaces the per-lane multipliers in all four
  // banks. Fifteen private multipliers become one array that costs
  // about what the fp256 one alone did; see cft_mulfrac's header for
  // why the slots line up and why its reduction tree needs no shifts.
  //
  // OFF BY DEFAULT, AND THE REASON IS A MEASUREMENT.
  //
  // Out-of-context synthesis of cft_krnl at 145 MHz, same commit, only
  // this switch changed:
  //
  //             LUT       DSP    WNS
  //   private   124,589   262    +0.959
  //   fused     125,282   259    -0.181
  //
  // No LUT saving, no DSP saving, and timing stops closing - with the
  // new critical path running prec_r into this array's own mode muxes.
  //
  // The estimate that justified the work assumed the multiplier was
  // about 45% of a lane's LUTs. It is not: the multipliers are
  // DSP-mapped, so removing them saves DSPs rather than LUTs. And the
  // DSP saving did not appear either, because each private multiplier
  // is sized for ITS OWN format - fp32's is 24x24, two DSPs - while
  // every slot of this array is sized for fp256 at 237x27 and every
  // mode uses full-width slots. Ten fp256-width slots cost about what
  // four banks of right-sized multipliers cost. Fusing this way throws
  // away exactly the efficiency separate banks already had.
  //
  // The array is correct - tb_mulshare proves bit-identity across every
  // format, attribute and precision switch - so it stays, and stays
  // tested. What it is not is cheaper. The version that would be cheaper
  // is the granule grid docs/ARCHITECTURE.md originally sketched:
  // fracture the WIDTH, tiling 237x237 into 24x24 granules with gated
  // cross-terms, so fp32 mode lights eight granules rather than eight
  // full-width slots. This module is the correctness scaffolding for
  // that, not a replacement for it.
  //
  // Also requires the full-tile geometry when enabled. The array's shape
  // IS the 256-bit beat's - eight fp32 lanes of 24 bits, four fp64 of
  // 53, two fp128 of 113, one fp256 of 237 - and the quarter tile
  // (BEAT_BITS=64, fp32+fp64) does not even build the fp256 rung it is
  // sized for.
  localparam bit USE_FUSED_MUL = FUSE_MUL && (BEAT_BITS == 256) &&
                                 EN_FP64 && EN_FP128 && EN_FP256;

  localparam int MF_PMAX = 237;
  localparam int MF_MCH  = 27;
  localparam int MF_ACCW = 2 * MF_PMAX + 2 * MF_MCH;

  logic [MF_PMAX-1:0] mf_a, mf_b;
  logic [MF_ACCW-1:0] mf_p;

  // Significands out of each lane, waiting to be packed.
  logic [23:0]  mfa32  [0:7],  mfb32  [0:7];
  logic [52:0]  mfa64  [0:3],  mfb64  [0:3];
  logic [112:0] mfa128 [0:1],  mfb128 [0:1];
  logic [236:0] mfa256,        mfb256;

  generate
    if (USE_FUSED_MUL) begin : g_mulfrac
      cft_mulfrac #(.PMAX(MF_PMAX), .MCH(MF_MCH), .SLOTS(16)) u_mulfrac (
          .clk(ap_clk), .mode(prec_r), .in_valid(ex_valid),
          .a(mf_a), .b(mf_b), .out_valid(), .p(mf_p));

      // Pack whichever bank is live. prec_r is snapshot at start and
      // never moves while anything is in flight - running does not drop
      // until wfinish, by which point every result has been collected
      // and written - so the array's mode always matches the operands
      // it is being handed. That is the same argument that makes op_r
      // and rnd_r safe to latch per run.
      always_comb begin
        mf_a = '0;
        mf_b = '0;
        case (prec_r)
          PREC_FP32:  for (int i = 0; i < 8; i = i + 1) begin
                        mf_a[i*24 +: 24] = mfa32[i];
                        mf_b[i*24 +: 24] = mfb32[i];
                      end
          PREC_FP64:  for (int i = 0; i < 4; i = i + 1) begin
                        mf_a[i*53 +: 53] = mfa64[i];
                        mf_b[i*53 +: 53] = mfb64[i];
                      end
          PREC_FP128: for (int i = 0; i < 2; i = i + 1) begin
                        mf_a[i*113 +: 113] = mfa128[i];
                        mf_b[i*113 +: 113] = mfb128[i];
                      end
          default:    begin
                        mf_a = mfa256;
                        mf_b = mfb256;
                      end
        endcase
      end
    end else begin : g_no_mulfrac
      assign mf_a = '0;
      assign mf_b = '0;
      assign mf_p = '0;
    end
  endgenerate

  // ---- compute banks (identical structure to cft_engine) -------------
  // 8 x fp32 lanes
  logic [BEAT_BITS-1:0] d32;
  logic [4:0]   f32_l [0:LANES32-1];
  logic [4:0]   f32_or;
  genvar gi;
  generate
    for (gi = 0; gi < LANES32; gi = gi + 1) begin : g_lane32
      logic [31:0] sa, sb, sc, fa, fb, fc, dd;
      assign sa = a_q[gi*32 +: 32];
      assign sb = b_q[gi*32 +: 32];
      assign sc = c_q[gi*32 +: 32];
      cft_opmux #(.EXP_W(8), .MAN_W(23)) u_mux (
          .op(op_r), .a(sa), .b(sb), .c(sc),
          .fa(fa), .fb(fb), .fc(fc));
      logic bv; logic [31:0] bd; logic [4:0] bf;
      cft_simpleops #(.EXP_W(8), .MAN_W(23)) u_simple (
          .op(op_r), .a(sa), .b(sb), .c(sc),
          .valid(bv), .d(bd), .flags(bf));
      // Lane 0 doubles as the accumulator's adder while a reduction
      // runs. Steered the way cft_opmux steers ADD - fma(x, 1.0, y) -
      // because the product is exact and the pipe is already there.
      // The other lanes idle; their outputs are masked out of the
      // accumulator's view.
      logic        rv;
      logic [31:0] ra, rc;
      assign rv = is_reduce && (gi == 0) && (prec_r == PREC_FP32) &&
                  red_add_valid;
      assign ra = is_reduce ? red_add_a[31:0] : fa;
      assign rc = is_reduce ? red_add_b[31:0] : fc;

      cft_fpfma_pipe #(.EXP_W(8), .MAN_W(23), .LATENCY(LATENCY),
                       .EXT_MUL(USE_FUSED_MUL)) u_fma (
          .clk(ap_clk), .rst_n(ap_rst_n),
          .in_valid(is_reduce ? rv : (ex_valid && (prec_r == PREC_FP32))),
          .rnd(rnd_r),
          .byp(is_reduce ? 1'b0 : bv), .byp_d(bd), .byp_f(bf),
          .a(ra), .b(is_reduce ? 32'h3F80_0000 : fb), .c(rc),
          .out_valid(), .d(dd), .flags(f32_l[gi]),
          .mul_a(mfa32[gi]), .mul_b(mfb32[gi]),
          .mul_p(mf_p[gi*48 +: 48]));
      assign d32[gi*32 +: 32] = dd;
    end
  endgenerate
  always_comb begin
    f32_or = 5'b0;
    for (int i = 0; i < LANES32; i = i + 1) f32_or = f32_or | f32_l[i];
  end

  // 4 x fp64 lanes
  logic [BEAT_BITS-1:0] d64;
  logic [4:0]   f64_or;
  generate
    if (EN_FP64 && LANES64 > 0) begin : g_bank64
      logic [4:0] f64_l [0:LANES64-1];
      for (gi = 0; gi < LANES64; gi = gi + 1) begin : g_lane64
        logic [63:0] sa, sb, sc, fa, fb, fc, dd;
        assign sa = a_q[gi*64 +: 64];
        assign sb = b_q[gi*64 +: 64];
        assign sc = c_q[gi*64 +: 64];
        cft_opmux #(.EXP_W(11), .MAN_W(52)) u_mux (
            .op(op_r), .a(sa), .b(sb), .c(sc),
            .fa(fa), .fb(fb), .fc(fc));
        logic bv; logic [63:0] bd; logic [4:0] bf;
        cft_simpleops #(.EXP_W(11), .MAN_W(52)) u_simple (
            .op(op_r), .a(sa), .b(sb), .c(sc),
            .valid(bv), .d(bd), .flags(bf));
        logic        rv;
        logic [63:0] ra, rc;
        assign rv = is_reduce && (gi == 0) && (prec_r == PREC_FP64) &&
                    red_add_valid;
        assign ra = is_reduce ? red_add_a[63:0] : fa;
        assign rc = is_reduce ? red_add_b[63:0] : fc;

        cft_fpfma_pipe #(.EXP_W(11), .MAN_W(52), .LATENCY(LATENCY),
                         .EXT_MUL(USE_FUSED_MUL)) u_fma (
            .clk(ap_clk), .rst_n(ap_rst_n),
            .in_valid(is_reduce ? rv : (ex_valid && (prec_r == PREC_FP64))),
          .rnd(rnd_r),
          .byp(is_reduce ? 1'b0 : bv), .byp_d(bd), .byp_f(bf),
            .a(ra), .b(is_reduce ? 64'h3FF0_0000_0000_0000 : fb), .c(rc),
            .out_valid(), .d(dd), .flags(f64_l[gi]),
            .mul_a(mfa64[gi]), .mul_b(mfb64[gi]),
            .mul_p(mf_p[gi*106 +: 106]));
        assign d64[gi*64 +: 64] = dd;
      end
      always_comb begin
        f64_or = 5'b0;
        for (int i = 0; i < LANES64; i = i + 1) f64_or = f64_or | f64_l[i];
      end
    end else begin : g_bank64_off
      assign d64 = '0;
      assign f64_or = 5'b0;
    end
  endgenerate

  // 2 x fp128 lanes
  logic [BEAT_BITS-1:0] d128;
  logic [4:0]   f128_or;
  generate
    if (EN_FP128 && LANES128 > 0) begin : g_bank128
      logic [4:0] f128_l [0:LANES128-1];
      for (gi = 0; gi < LANES128; gi = gi + 1) begin : g_lane128
        logic [127:0] sa, sb, sc, fa, fb, fc, dd;
        assign sa = a_q[gi*128 +: 128];
        assign sb = b_q[gi*128 +: 128];
        assign sc = c_q[gi*128 +: 128];
        cft_opmux #(.EXP_W(15), .MAN_W(112)) u_mux (
            .op(op_r), .a(sa), .b(sb), .c(sc),
            .fa(fa), .fb(fb), .fc(fc));
        logic bv; logic [127:0] bd; logic [4:0] bf;
        cft_simpleops #(.EXP_W(15), .MAN_W(112)) u_simple (
            .op(op_r), .a(sa), .b(sb), .c(sc),
            .valid(bv), .d(bd), .flags(bf));
        logic         rv;
        logic [127:0] ra, rc;
        assign rv = is_reduce && (gi == 0) && (prec_r == PREC_FP128) &&
                    red_add_valid;
        assign ra = is_reduce ? red_add_a[127:0] : fa;
        assign rc = is_reduce ? red_add_b[127:0] : fc;

        cft_fpfma_pipe #(.EXP_W(15), .MAN_W(112), .LATENCY(LATENCY),
                         .EXT_MUL(USE_FUSED_MUL)) u_fma (
            .clk(ap_clk), .rst_n(ap_rst_n),
            .in_valid(is_reduce ? rv : (ex_valid && (prec_r == PREC_FP128))),
          .rnd(rnd_r),
          .byp(is_reduce ? 1'b0 : bv), .byp_d(bd), .byp_f(bf),
            .a(ra),
            .b(is_reduce ? {1'b0, 15'h3FFF, 112'd0} : fb),
            .c(rc),
            .out_valid(), .d(dd), .flags(f128_l[gi]),
            .mul_a(mfa128[gi]), .mul_b(mfb128[gi]),
            .mul_p(mf_p[gi*226 +: 226]));
        assign d128[gi*128 +: 128] = dd;
      end
      always_comb begin
        f128_or = 5'b0;
        for (int i = 0; i < LANES128; i = i + 1) f128_or = f128_or | f128_l[i];
      end
    end else begin : g_bank128_off
      assign d128 = '0;
      assign f128_or = 5'b0;
    end
  endgenerate

  // 1 x fp256 unit
  logic [BEAT_BITS-1:0] d256;
  logic [4:0]   f256;
  generate
    if (EN_FP256 && LANES256 > 0) begin : g_bank256
      logic [BEAT_BITS-1:0] w_fa, w_fb, w_fc;
      cft_opmux #(.EXP_W(19), .MAN_W(236)) u_wmux (
          .op(op_r), .a(a_q), .b(b_q), .c(c_q),
          .fa(w_fa), .fb(w_fb), .fc(w_fc));
      logic bv; logic [255:0] bd; logic [4:0] bf;
      cft_simpleops #(.EXP_W(19), .MAN_W(236)) u_simple (
          .op(op_r), .a(a_q), .b(b_q), .c(c_q),
          .valid(bv), .d(bd), .flags(bf));
      logic rv256;
      assign rv256 = is_reduce && (prec_r == PREC_FP256) && red_add_valid;

      cft_fpfma_pipe #(.EXP_W(19), .MAN_W(236), .LATENCY(LATENCY),
                       .EXT_MUL(USE_FUSED_MUL)) u_wfma (
          .clk(ap_clk), .rst_n(ap_rst_n),
          .in_valid(is_reduce ? rv256
                              : (ex_valid && (prec_r == PREC_FP256))),
          .rnd(rnd_r),
          .byp(is_reduce ? 1'b0 : bv), .byp_d(bd), .byp_f(bf),
          .a(is_reduce ? red_add_a : w_fa),
          .b(is_reduce ? {1'b0, 19'h3FFFF, 236'd0} : w_fb),
          .c(is_reduce ? red_add_b : w_fc),
          .out_valid(), .d(d256), .flags(f256),
          .mul_a(mfa256), .mul_b(mfb256), .mul_p(mf_p[0 +: 474]));
    end else begin : g_bank256_off
      assign d256 = '0;
      assign f256 = 5'b0;
    end
  endgenerate

  always_comb begin
    beat_d = d32;
    beat_f = f32_or;
    case (prec_r)
      PREC_FP64:  begin beat_d = d64;  beat_f = f64_or;  end
      PREC_FP128: begin beat_d = d128; beat_f = f128_or; end
      PREC_FP256: begin beat_d = d256; beat_f = f256;    end
      default: ;  // PREC_FP32 falls through to the defaults
    endcase
  end

  // A reduction writes exactly one beat, holding the single result in
  // its low bits. Everything above the element is zero because the
  // accumulator was fed masked values; the host copies back one element
  // and ignores the rest.
  cft_fifo #(.WIDTH(256), .DEPTH_LOG2(FIFO_LOG2)) u_fifo_d (
      .clk(ap_clk), .rst_n(ap_rst_n), .clear(fifo_clear),
      .wr_en(d_wr), .wr_data(is_reduce ? red_out_data : beat_d),
      .rd_en(d_rd), .rd_data(d_qout), .count(d_cnt));

  // ---- writer: index-order bursts from the D FIFO --------------------
  localparam logic [1:0] W_IDLE = 2'd0, W_AW = 2'd1, W_DATA = 2'd2, W_B = 2'd3;

  logic [1:0]  wr_state;
  logic [63:0] wr_done;
  logic [7:0]  w_len, w_cnt;

  logic [63:0] rem_w, addr_w;
  assign rem_w  = wr_total - wr_done;
  assign addr_w = base_d + (wr_done << ADDR_SH);

  // target burst: full-size when possible; the tail is always fully
  // buffered by the time rem_w is what is left, so d_cnt >= target
  // holds without a special drain case.
  logic [7:0] w_target;
  always_comb begin
    logic [63:0] bound, l;
    // ADDR_SH, not a literal 5 - the same trap the read path documents
    // at burst_len(). A hardcoded 5 is only right at BEAT_BITS=256. At
    // the quarter tile's 64 it understates by 4x and reaches ZERO for
    // the last beats of a 4KB page (addr_w[11:0]=4072 gives 24>>5=0),
    // which clears w_go permanently: wr_done stops, ap_done never
    // asserts, and the run hangs until the host's timeout.
    bound = (64'd4096 - {52'd0, addr_w[11:0]}) >> ADDR_SH;
    l = BURST_MAX;
    if (rem_w < l) l = rem_w;
    if (bound < l) l = bound;
    w_target = l[7:0];
  end

  logic w_go;
  assign w_go = running && (w_target != 8'd0) && (d_cnt >= w_target);

  always_ff @(posedge ap_clk) begin
    if (!ap_rst_n) begin
      wr_state <= W_IDLE;
      wr_done <= '0;
      w_len <= 8'd0;
      w_cnt <= 8'd0;
    end else if (!running) begin
      wr_state <= W_IDLE;
      wr_done <= '0;
    end else begin
      case (wr_state)
        W_IDLE: if (w_go) begin
          w_len <= w_target;
          w_cnt <= 8'd0;
          wr_state <= W_AW;
        end
        W_AW: if (m_axi_d_awready) begin
          wr_state <= W_DATA;
          // synthesis translate_off
          $display("[CFT-ENGS] AW addr=0x%h len=%0d", m_axi_d_awaddr, w_len);
          // synthesis translate_on
        end
        W_DATA: if (m_axi_d_wvalid && m_axi_d_wready) begin
          w_cnt <= w_cnt + 8'd1;
          if (w_cnt + 8'd1 == w_len) wr_state <= W_B;
        end
        W_B: if (m_axi_d_bvalid) begin
          wr_done <= wr_done + {56'd0, w_len};
          wr_state <= W_IDLE;
        end
        default: wr_state <= W_IDLE;
      endcase
    end
  end

  assign m_axi_d_awvalid = (wr_state == W_AW);
  assign m_axi_d_awaddr  = addr_w;
  assign m_axi_d_awlen   = w_len - 8'd1;
  assign m_axi_d_wvalid  = (wr_state == W_DATA) && (d_cnt != 0);
  assign m_axi_d_wdata   = d_qout;
  assign m_axi_d_wlast   = (w_cnt == w_len - 8'd1);
  assign d_rd            = m_axi_d_wvalid && m_axi_d_wready;
  assign m_axi_d_bready  = (wr_state == W_B);

  assign wfinish = (wr_state == W_B) && m_axi_d_bvalid &&
                   ((wr_done + {56'd0, w_len}) == wr_total);

  // ---- sticky bus faults ---------------------------------------------
  //
  // The memory system's own verdict on the data this run consumed and
  // produced. Without it a DECERR on an out-of-range pointer is
  // indistinguishable from success: the engine would compute on
  // whatever the interconnect drove, write it out, and report done
  // with clean IEEE flags. A determinism claim that cannot tell
  // "these are the bits" from "the memory never answered" is not
  // worth much, so a run ending with STATUS non-zero is a run whose
  // output must be discarded.
  always_ff @(posedge ap_clk) begin
    if (!ap_rst_n) begin
      err_acc <= 3'b0;
    end else if (start_accept) begin
      err_acc <= 3'b0;
    end else begin
      // Every read master's verdict, not just the one that used to be
      // shared. A DECERR on stream c is exactly as fatal as one on a.
      if ((m_axi_a_rvalid && (m_axi_a_rresp != 2'b00)) ||
          (m_axi_b_rvalid && (m_axi_b_rresp != 2'b00)) ||
          (m_axi_c_rvalid && (m_axi_c_rresp != 2'b00)))
        err_acc[ERR_RRESP] <= 1'b1;
      if ((wr_state == W_B) && m_axi_d_bvalid && (m_axi_d_bresp != 2'b00))
        err_acc[ERR_BRESP] <= 1'b1;
      // Raised per stream by the length queues in the reader generate.
      if (|rlen_err)
        err_acc[ERR_RLEN] <= 1'b1;
    end
  end

  // ---- sticky flags --------------------------------------------------
  //
  // Elementwise accumulates a beat at a time as results are collected.
  // A reduction collects nothing - its adds go through lane 0 and its
  // one result arrives from the accumulator - so it contributes its OR
  // once, when that result appears. cft_reduce_acc has been ORing every
  // add's flags along the way, which is the same set the elementwise
  // path would have gathered and in an order that cannot matter.
  always_ff @(posedge ap_clk) begin
    if (!ap_rst_n)          flags_acc <= 5'b0;
    else if (start_accept)  flags_acc <= 5'b0;
    else if (red_push) begin
      flags_acc <= flags_acc | red_out_flags;
      // synthesis translate_off
      $display("[CFT-ENGS] RED prec=%0d d[127:0]=0x%h flags=%b",
               prec_r, red_out_data[127:0], red_out_flags);
      // synthesis translate_on
    end
    else if (collect) begin
      flags_acc <= flags_acc | beat_f;
      // synthesis translate_off
      $display("[CFT-ENGS] EXQ prec=%0d d[127:0]=0x%h flags=%b", prec_r, beat_d[127:0], beat_f);
      // synthesis translate_on
    end
  end

endmodule
