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
//
// ---------------------------------------------------------------
// Two engines, one set of masters
// ---------------------------------------------------------------
//
// cft_engine_stream and cft_seq are peers behind one CSR block, and
// MODE[15] says which of them owns a run. They never run at once - the
// CSR issues one start and refuses another until done - so the
// interconnect only ever sees one owner, and the masters are shared
// rather than duplicated.
//
// The sequencer wants one read stream and one write stream, so it
// borrows A and D and leaves B and C quiet; a program's inputs arrive
// through A's beats along with its image, and bandwidth is not what a
// sequencer run is for. Four masters for a machine that reads one
// array slowly would buy nothing and cost three HBM pseudo-channel
// groups.
//
// The mux select is REGISTERED at the accepted start, never read live
// from MODE. A host that rewrote MODE mid-run would otherwise hand the
// masters to the other engine partway through a burst - the same
// failure cft_engine_stream snapshots op and rnd to avoid, one level
// up and with an AXI protocol violation attached.

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

  logic        start;
  logic        eng_busy, eng_done;
  logic [4:0]  eng_flags;
  logic [2:0]  eng_err;
  logic        seq_busy, seq_done, seq_refuse;
  logic [4:0]  seq_flags;
  logic [3:0]  seq_err;
  logic [7:0]  cfg_op;
  logic [3:0]  cfg_prec;
  logic [2:0]  cfg_rnd;
  logic        cfg_seq;
  logic [63:0] cfg_n, cfg_a, cfg_b, cfg_c, cfg_d, cfg_prog, cfg_cnt;

  // A run whose MODE selects a precision this build does not carry is
  // REFUSED: the engine never starts, nothing is read or written, the
  // run completes immediately with STATUS[3] set. Before this gate, a
  // trimmed build handed such a run to banks that do not exist - the
  // lanes idled, the writer wrote whatever the absent datapath drove,
  // and the failure shape was plausible-looking garbage with clean
  // flags, indistinguishable from a wrong answer. CAPS[3:0] already
  // told an honest host not to ask; this makes the answer to a
  // dishonest one an error instead of an output. Codes 4-15 of the
  // 4-bit field are refused on every build for the same reason.
  localparam [3:0] PREC_CAPS = {EN_FP256, EN_FP128, EN_FP64, 1'b1};

  logic prec_ok, refused_q, refuse_done_q;
  assign prec_ok = (cfg_prec[3:2] == 2'b00) && PREC_CAPS[cfg_prec[1:0]];

  // Which engine owns the run in flight, and whether the sequencer
  // threw its program image back. The image refusal is not known at
  // start the way a precision refusal is - the header has to be read
  // first - so it arrives with `done` and is made sticky here, with
  // the same lifetime as refused_q.
  logic mode_seq_q, seq_refused_q, refuse_any;
  logic       run_busy, run_done;
  logic [4:0] run_flags, flags_pub, flags_hold_q;
  logic [2:0] run_bus;
  logic       run_ovf;

  assign run_busy  = mode_seq_q ? seq_busy      : eng_busy;
  assign run_done  = mode_seq_q ? seq_done      : eng_done;
  assign run_flags = mode_seq_q ? seq_flags     : eng_flags;
  assign run_bus   = mode_seq_q ? seq_err[2:0]  : eng_err;
  assign run_ovf   = mode_seq_q ? seq_err[3]    : 1'b0;
  assign refuse_any = refused_q | seq_refused_q;

  // FLAGS is the last RUN's truth, and a refusal is not a run.
  //
  // Live-muxing the two engines' sticky words cannot express that. A
  // refused sequencer run reads back five zeros - it computed nothing,
  // so it contributed nothing - and publishing those would scrub the
  // previous run's flags, which is the history-rewriting the CSR's own
  // header refuses to do. Holding the last published word covers both
  // refusal kinds with one register, and leaves the elementwise path
  // reading exactly what it always read.
  assign flags_pub = refuse_any ? flags_hold_q : run_flags;

  always_ff @(posedge ap_clk) begin
    if (!ap_rst_n) begin
      refused_q     <= 1'b0;
      refuse_done_q <= 1'b0;
      mode_seq_q    <= 1'b0;
      seq_refused_q <= 1'b0;
      flags_hold_q  <= 5'b0;
    end else begin
      // The refusal's done arrives one cycle after start, matching the
      // one-cycle-pulse contract the CSR expects from the engine; the
      // sticky clears on the next ACCEPTED start, same lifetime as the
      // engine's own error sticky.
      refuse_done_q <= start && !prec_ok;
      if (start) begin
        refused_q     <= !prec_ok;
        seq_refused_q <= 1'b0;
        // Sampled once, here, and read by every mux below for the
        // whole run - so for the START CYCLE ITSELF the muxes still
        // carry the previous run's select. That is harmless and not
        // by luck: both engines report busy and done from registers
        // that are still clear this cycle, and neither can drive AR or
        // AW until it has registered its own start (cft_engine_stream
        // needs `running`, and cft_seq's FSM the same). An engine that
        // issued a burst combinationally from `start` would be the one
        // thing this arrangement could not carry.
        mode_seq_q    <= cfg_seq;
        // Captured before either engine clears its own sticky word at
        // this same edge, and from the published value rather than the
        // live one, so a refusal followed by a refusal still holds the
        // last real run's flags rather than the first refusal's zeros.
        flags_hold_q  <= flags_pub;
      end else if (seq_done && seq_refuse) begin
        seq_refused_q <= 1'b1;
      end
    end
  end

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
      .start(start), .busy(run_busy), .done(run_done | refuse_done_q),
      .eng_flags(flags_pub),
      // While the LAST start was a refusal, the engine's sticky bits
      // are by definition from an earlier run - the engine never
      // started, so nothing could have cleared them - and STATUS is
      // documented as the last run's truth. Masking them here is what
      // keeps a refusal reading as exactly 0x8: the adversarial
      // review simulated fault-run -> refusal and read 0xA, two runs'
      // truths ORed together, which the host then misfiled as a bus
      // fault on a run that never touched the bus.
      //
      // The sequencer's image refusal joins bit 3 and gets the same
      // masking, for the same reason and one step further: a sequencer
      // run that refuses its image DID read memory, so its own fault
      // bits could be live rather than stale - but a refused run has
      // no output to distrust, and 0x8 exactly is what tells a host
      // "this did not happen" without also telling it the memory
      // system is broken. Bit 4, the deposit overflow, is masked with
      // them: a run that never deposited cannot have overflowed.
      .eng_err({run_ovf & ~refuse_any, refuse_any,
                run_bus & {3{~refuse_any}}}),
      .prec_caps(PREC_CAPS),
      //
      // The reduction bit covers CFT_SUM. CFT_DOT is in the same group
      // and is NOT separate hardware: the contract makes
      // dot(a,b) == sum(mul(a,b)) exact, flags included, so the host
      // issues an elementwise MUL and then a SUM. Advertising the group
      // is therefore honest - both opcodes deliver the contract's
      // answer, one of them via two runs.
      // CAPS[15:8]: arithmetic, sign, min/max, predicate+select,
      // integer, reduction, divide/sqrt seeds, and the sequencer.
      // Write this as a bit per group and not as a number: it was
      // briefly 8'b0010_1111, which adds reduction and silently drops
      // integer, and eight working opcodes stopped being reachable.
      .op_caps({1'b1,       // [7]   SEQUENCER: cft_seq is instantiated
                            //       and MODE[15] reaches it. This bit
                            //       read "conversion - reserved" until
                            //       the conversions landed as library
                            //       entry points composed from opcodes
                            //       that already exist - so the group
                            //       will never want a MODE opcode, and
                            //       a group bit nothing can ever set is
                            //       a reserved bit. The sequencer is a
                            //       thing a host must ask about before
                            //       it writes PROG_PTR, so it takes it.
                1'b1,       // [6]   divide/sqrt (seed opcodes; the
                            //       full operations are FMA-composed
                            //       sequences in the host library)
                1'b1,       // [5]   reduction
                1'b1,       // [4]   integer
                1'b1,       // [3]   predicate + select
                1'b1,       // [2]   min/max
                1'b1,       // [1]   sign
                1'b1}),     // [0]   arithmetic
      .cfg_op(cfg_op), .cfg_prec(cfg_prec), .cfg_rnd(cfg_rnd),
      .cfg_seq(cfg_seq), .cfg_n(cfg_n),
      .cfg_a(cfg_a), .cfg_b(cfg_b), .cfg_c(cfg_c), .cfg_d(cfg_d),
      .cfg_prog(cfg_prog), .cfg_cnt(cfg_cnt)
  );

  // ---- the shared masters --------------------------------------------
  //
  // Only the signals cft_seq has a port for are muxed. The rest - ID,
  // size, burst, lock, cache, prot, QoS - are tied constants inside
  // cft_engine_stream (one 256-bit INCR master against HBM) and are
  // exactly the constants a sequencer burst wants, so they reach the
  // pins straight from there rather than through a mux with the same
  // value on both inputs.
  logic [63:0]            eng_a_araddr;
  logic [7:0]             eng_a_arlen;
  logic                   eng_a_arvalid, eng_a_rready;
  logic                   eng_b_arvalid, eng_c_arvalid;
  logic [63:0]            eng_d_awaddr;
  logic [7:0]             eng_d_awlen;
  logic                   eng_d_awvalid;
  logic [BEAT_BITS-1:0]   eng_d_wdata;
  logic [BEAT_BITS/8-1:0] eng_d_wstrb;
  logic                   eng_d_wlast, eng_d_wvalid, eng_d_bready;

  logic [63:0]            seq_araddr, seq_awaddr;
  logic [7:0]             seq_arlen, seq_awlen;
  logic                   seq_arvalid, seq_rready, seq_awvalid;
  logic [BEAT_BITS-1:0]   seq_wdata;
  logic [BEAT_BITS/8-1:0] seq_wstrb;
  logic                   seq_wlast, seq_wvalid, seq_bready;

  assign m_axi_a_araddr  = mode_seq_q ? seq_araddr  : eng_a_araddr;
  assign m_axi_a_arlen   = mode_seq_q ? seq_arlen   : eng_a_arlen;
  assign m_axi_a_arvalid = mode_seq_q ? seq_arvalid : eng_a_arvalid;
  assign m_axi_a_rready  = mode_seq_q ? seq_rready  : eng_a_rready;

  // B and C are held quiet in a sequencer run rather than merely left
  // idle. The engine cannot drive them while it is not running, so
  // this is belt and braces - but it is the statement that ONE owner
  // exists per run, and a statement the interconnect can rely on
  // should not depend on reading another module's FSM.
  assign m_axi_b_arvalid = mode_seq_q ? 1'b0 : eng_b_arvalid;
  assign m_axi_c_arvalid = mode_seq_q ? 1'b0 : eng_c_arvalid;

  assign m_axi_d_awaddr  = mode_seq_q ? seq_awaddr  : eng_d_awaddr;
  assign m_axi_d_awlen   = mode_seq_q ? seq_awlen   : eng_d_awlen;
  assign m_axi_d_awvalid = mode_seq_q ? seq_awvalid : eng_d_awvalid;
  assign m_axi_d_wdata   = mode_seq_q ? seq_wdata   : eng_d_wdata;
  assign m_axi_d_wstrb   = mode_seq_q ? seq_wstrb   : eng_d_wstrb;
  assign m_axi_d_wlast   = mode_seq_q ? seq_wlast   : eng_d_wlast;
  assign m_axi_d_wvalid  = mode_seq_q ? seq_wvalid  : eng_d_wvalid;
  assign m_axi_d_bready  = mode_seq_q ? seq_bready  : eng_d_bready;

  // The idle engine must not SEE the other's traffic either. Its
  // stream FIFOs write on RVALID with no further qualification, and
  // its fault latch watches every R and B response whenever a run is
  // not starting - so a sequencer's beats would fill a FIFO nobody
  // drains and file the sequencer's bus faults a second time, in a
  // register the STATUS mux is not reading. One AND gate per channel
  // makes the sharing invisible from inside the engine.
  logic eng_sees_bus;
  assign eng_sees_bus = ~mode_seq_q;

  // ---- the ONE ALU array ---------------------------------------------
  //
  // cft_engine_stream and cft_seq each present a per-issue request -
  // valid, opcode, attribute, precision, three operands - and the
  // owner of the run (MODE[15], registered at start as mode_seq_q) is
  // the one whose request reaches the array. No arbitration: the two
  // never run at once, the idle one holds valid low, and the select
  // is a register, so this costs one mux level between registered
  // operands and the array's steering. The results fan out to both;
  // each consumes only during its own run. cft_lanes' header says why
  // this is not optional: two copies of the array put the quad tile
  // at 1.32M LUTs on an 871k part.
  logic                      eng_lv, seq_lv;
  logic [7:0]                eng_lop, seq_lop;
  logic [2:0]                eng_lrnd, seq_lrnd;
  logic [1:0]                eng_lprec, seq_lprec;
  logic [BEAT_BITS-1:0]      eng_la, eng_lb, eng_lc;
  logic [BEAT_BITS-1:0]      seq_la, seq_lb, seq_lc;
  logic                      arr_ov;
  logic [BEAT_BITS-1:0]      arr_d;
  logic [BEAT_BITS/32*5-1:0] arr_lf;

  cft_lanes #(.BEAT_BITS(BEAT_BITS), .LATENCY(15),
              .EN_FP64(EN_FP64), .EN_FP128(EN_FP128), .EN_FP256(EN_FP256),
              .FUSE_MUL(FUSE_MUL), .FUSE_NORM(FUSE_NORM),
              .FUSE_ALIGN(FUSE_ALIGN)) u_lanes (
      .clk(ap_clk), .rst_n(ap_rst_n),
      .in_valid (mode_seq_q ? seq_lv    : eng_lv),
      .op       (mode_seq_q ? seq_lop   : eng_lop),
      .rnd      (mode_seq_q ? seq_lrnd  : eng_lrnd),
      .prec     (mode_seq_q ? seq_lprec : eng_lprec),
      .a        (mode_seq_q ? seq_la    : eng_la),
      .b        (mode_seq_q ? seq_lb    : eng_lb),
      .c        (mode_seq_q ? seq_lc    : eng_lc),
      .out_valid(arr_ov), .d(arr_d), .lane_flags(arr_lf));

  cft_engine_stream #(.LATENCY(15), .EN_FP64(EN_FP64), .EN_FP128(EN_FP128),
                      .EN_FP256(EN_FP256), .BEAT_BITS(BEAT_BITS),
                      .FUSE_MUL(FUSE_MUL), .FUSE_NORM(FUSE_NORM),
                      .FUSE_ALIGN(FUSE_ALIGN), .OWN_LANES(1'b0)) u_engine (
      .ap_clk(ap_clk), .ap_rst_n(ap_rst_n),
      .start(start && prec_ok && !cfg_seq), .busy(eng_busy), .done(eng_done),
      .flags_acc(eng_flags),
      .err_acc(eng_err),
      .cfg_op(cfg_op), .cfg_prec(cfg_prec), .cfg_rnd(cfg_rnd), .cfg_n(cfg_n),
      .cfg_a(cfg_a), .cfg_b(cfg_b), .cfg_c(cfg_c), .cfg_d(cfg_d),
      .lane_valid(eng_lv), .lane_op(eng_lop), .lane_rnd(eng_lrnd),
      .lane_prec(eng_lprec), .lane_a(eng_la), .lane_b(eng_lb), .lane_c(eng_lc),
      .lane_d(arr_d), .lane_flags(arr_lf),
      .m_axi_a_arid(m_axi_a_arid), .m_axi_a_araddr(eng_a_araddr), .m_axi_a_arlen(eng_a_arlen),
      .m_axi_a_arsize(m_axi_a_arsize), .m_axi_a_arburst(m_axi_a_arburst), .m_axi_a_arlock(m_axi_a_arlock),
      .m_axi_a_arcache(m_axi_a_arcache), .m_axi_a_arprot(m_axi_a_arprot), .m_axi_a_arqos(m_axi_a_arqos),
      .m_axi_a_arvalid(eng_a_arvalid), .m_axi_a_arready(m_axi_a_arready), .m_axi_a_rid(m_axi_a_rid),
      .m_axi_a_rdata(m_axi_a_rdata), .m_axi_a_rresp(m_axi_a_rresp), .m_axi_a_rlast(m_axi_a_rlast),
      .m_axi_a_rvalid(m_axi_a_rvalid & eng_sees_bus), .m_axi_a_rready(eng_a_rready), .m_axi_b_arid(m_axi_b_arid),
      .m_axi_b_araddr(m_axi_b_araddr), .m_axi_b_arlen(m_axi_b_arlen), .m_axi_b_arsize(m_axi_b_arsize),
      .m_axi_b_arburst(m_axi_b_arburst), .m_axi_b_arlock(m_axi_b_arlock), .m_axi_b_arcache(m_axi_b_arcache),
      .m_axi_b_arprot(m_axi_b_arprot), .m_axi_b_arqos(m_axi_b_arqos), .m_axi_b_arvalid(eng_b_arvalid),
      .m_axi_b_arready(m_axi_b_arready), .m_axi_b_rid(m_axi_b_rid), .m_axi_b_rdata(m_axi_b_rdata),
      .m_axi_b_rresp(m_axi_b_rresp), .m_axi_b_rlast(m_axi_b_rlast), .m_axi_b_rvalid(m_axi_b_rvalid & eng_sees_bus),
      .m_axi_b_rready(m_axi_b_rready), .m_axi_c_arid(m_axi_c_arid), .m_axi_c_araddr(m_axi_c_araddr),
      .m_axi_c_arlen(m_axi_c_arlen), .m_axi_c_arsize(m_axi_c_arsize), .m_axi_c_arburst(m_axi_c_arburst),
      .m_axi_c_arlock(m_axi_c_arlock), .m_axi_c_arcache(m_axi_c_arcache), .m_axi_c_arprot(m_axi_c_arprot),
      .m_axi_c_arqos(m_axi_c_arqos), .m_axi_c_arvalid(eng_c_arvalid), .m_axi_c_arready(m_axi_c_arready),
      .m_axi_c_rid(m_axi_c_rid), .m_axi_c_rdata(m_axi_c_rdata), .m_axi_c_rresp(m_axi_c_rresp),
      .m_axi_c_rlast(m_axi_c_rlast), .m_axi_c_rvalid(m_axi_c_rvalid & eng_sees_bus), .m_axi_c_rready(m_axi_c_rready),
      .m_axi_d_awid(m_axi_d_awid), .m_axi_d_awaddr(eng_d_awaddr), .m_axi_d_awlen(eng_d_awlen),
      .m_axi_d_awsize(m_axi_d_awsize), .m_axi_d_awburst(m_axi_d_awburst), .m_axi_d_awlock(m_axi_d_awlock),
      .m_axi_d_awcache(m_axi_d_awcache), .m_axi_d_awprot(m_axi_d_awprot), .m_axi_d_awqos(m_axi_d_awqos),
      .m_axi_d_awvalid(eng_d_awvalid), .m_axi_d_awready(m_axi_d_awready), .m_axi_d_wdata(eng_d_wdata),
      .m_axi_d_wstrb(eng_d_wstrb), .m_axi_d_wlast(eng_d_wlast), .m_axi_d_wvalid(eng_d_wvalid),
      .m_axi_d_wready(m_axi_d_wready), .m_axi_d_bid(m_axi_d_bid), .m_axi_d_bresp(m_axi_d_bresp),
      .m_axi_d_bvalid(m_axi_d_bvalid & eng_sees_bus), .m_axi_d_bready(eng_d_bready)
  );

  // The sequencer. LATENCY matches the engine's because they share the
  // ALU recipe and a block shorter than the pipeline cannot fill it;
  // NBEATS is the lane block, >= LATENCY + 1 for the same reason.
  // MAXD, IMEM_D and KMEM_D are the on-chip caps the hardware checks a
  // program image against, and refuses past - a program the tile
  // cannot hold is not a program the tile may half-run.
  cft_seq #(.BEAT_BITS(BEAT_BITS), .LATENCY(15), .NBEATS(16), .MAXD(64),
            .IMEM_D(1024), .KMEM_D(256), .ADDR_W(64),
            .EN_FP64(EN_FP64), .EN_FP128(EN_FP128),
            .EN_FP256(EN_FP256), .OWN_LANES(1'b0)) u_seq (
      .ap_clk(ap_clk), .ap_rst_n(ap_rst_n),
      .start(start && prec_ok && cfg_seq),
      // prec_ok has already proved cfg_prec[3:2] is zero, so the top
      // two bits carry nothing the sequencer needs.
      .cfg_prec(cfg_prec[1:0]), .cfg_n(cfg_n),
      .cfg_a(cfg_a), .cfg_b(cfg_b), .cfg_c(cfg_c), .cfg_d(cfg_d),
      .cfg_prog(cfg_prog), .cfg_cnt(cfg_cnt),
      .busy(seq_busy), .done(seq_done), .refuse(seq_refuse),
      .lane_valid(seq_lv), .lane_op(seq_lop), .lane_rnd(seq_lrnd),
      .lane_prec(seq_lprec), .lane_a(seq_la), .lane_b(seq_lb), .lane_c(seq_lc),
      .lane_ov(arr_ov), .lane_d(arr_d), .lane_flags(arr_lf),
      .flags(seq_flags), .err(seq_err),
      // ARLEN and AWLEN are AXI-encoded here, beats minus one, the way
      // they leave cft_engine_stream and the way they arrive at the
      // slave. The sequencer's ports carry AXI signal names, so they
      // carry AXI meanings; there is no adjustment on this path.
      .m_rd_araddr(seq_araddr), .m_rd_arlen(seq_arlen),
      .m_rd_arvalid(seq_arvalid), .m_rd_arready(m_axi_a_arready),
      .m_rd_rdata(m_axi_a_rdata), .m_rd_rlast(m_axi_a_rlast),
      .m_rd_rresp(m_axi_a_rresp), .m_rd_rvalid(m_axi_a_rvalid & mode_seq_q),
      .m_rd_rready(seq_rready),
      .m_wr_awaddr(seq_awaddr), .m_wr_awlen(seq_awlen),
      .m_wr_awvalid(seq_awvalid), .m_wr_awready(m_axi_d_awready),
      .m_wr_wdata(seq_wdata), .m_wr_wstrb(seq_wstrb),
      .m_wr_wlast(seq_wlast), .m_wr_wvalid(seq_wvalid),
      .m_wr_wready(m_axi_d_wready),
      .m_wr_bresp(m_axi_d_bresp), .m_wr_bvalid(m_axi_d_bvalid & mode_seq_q),
      .m_wr_bready(seq_bready)
  );

endmodule
