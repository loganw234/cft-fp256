// Copyright 2026 Logan W.
// SPDX-License-Identifier: Apache-2.0
//
// cft_seq: the orbit sequencer. docs/SEQUENCER.md is the design;
// python/cft_golden/seq.py is the definition of correct; this module
// is verified against that model exactly as the FMA core was against
// softfloat.py. It is a peer of cft_engine_stream behind the same CSR
// block - MODE[15] selects which engine owns a run - computing on the
// kernel's ONE cft_lanes array, handed in through the lane_* ports
// (OWN_LANES=0); the unit bench elaborates a private instance instead
// (OWN_LANES=1, the default). cft_lanes' header records the area
// finding that ended the v1 second-copy deviation.
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
//         magic   == "CFTP" (0x50544643)
//         version == 1
//         format  == cfg_prec (a program is compiled for one format)
//         n_insns <= IMEM_D, n_consts <= KMEM_D,
//         max_deposits <= MAXD
//     (max_deposits == 0 is LEGAL - the model allows it, every
//     deposit then overflows - and only the addressable first 16
//     constants are stored, because a 4-bit operand field cannot name
//     the rest; the loader already refused any program that tries.)
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
//     from a 4-deep loop stack; SETACT narrows on (magnitude != 0, so
//     -0 deactivates); ACTALL reactivates every lane THE CALLER HAS
//     (global index < cfg_n) - the padding lanes the model never sees
//     stay dead, which is what keeps RTL-with-padding bit-identical
//     to the model without it. The early exit tests any(active) at
//     REPEAT/ENDREP; inside a loop the mask only ever narrows, so
//     even a stale view errs toward extra no-op iterations, which P3
//     makes invisible.
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
// machine a straight line. One burst is in flight at a time on each
// channel: a sequencer run's memory traffic is bounded by its
// register file, not by the bus, so the simplicity is free.
//
// ---------------------------------------------------------------
// Structure (the three memories SEQUENCER.md sized)
// ---------------------------------------------------------------
//
//   register file   regs[{reg,beat}], 256 bits wide, mirrored twice
//                   so one cycle reads a, b and c; written with
//                   per-byte enables so a lane's active bit masks its
//                   slice. 16 regs x NBEATS beats x 32 B = 8 KiB, the
//                   same silicon at every precision.
//   imem / kmem     the instruction stream, and the 16 addressable
//                   constants broadcast at issue time.
//   deposit buffer  eight 32-bit banks, one per 32-bit word position
//                   within a beat - a wider lane occupies adjacent
//                   banks at one address - so divergent per-lane
//                   deposit counts still write in a single cycle.
//                   Slots are append-only, so "slot < count" IS the
//                   written mask and untouched slots need no
//                   bookkeeping to read back as +0.
//
// The issue/drain machine is the one the design sketched: an ALU
// instruction issues over the block's beats back to back, results
// retire LATENCY later through the same per-lane masking, and a
// dependent chain costs beats + LATENCY + a few cycles of state
// machine, with every lane busy during issue.

`timescale 1ns/1ps

module cft_seq #(
    parameter int BEAT_BITS  = 256,
    parameter int LATENCY    = 15,
    parameter int NBEATS     = 16,     // lane block; >= LATENCY + 1
    parameter int MAXD       = 64,     // deposit slots per lane, hw cap
    parameter int IMEM_D     = 1024,   // instruction capacity
    parameter int KMEM_D     = 256,    // constant capacity (image-side)
    parameter int ADDR_W     = 64,
    parameter bit EN_FP64    = 1'b1,
    parameter bit EN_FP128   = 1'b1,
    parameter bit EN_FP256   = 1'b1,
    // Own ALU array (1, the unit bench's configuration) or the
    // kernel's shared one through the lane_* ports (0).
    parameter bit OWN_LANES  = 1'b1
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

    // ---- the ALU array (cft_lanes) ---------------------------------
    // The per-issue request the issue machine builds, and the array's
    // answer. With OWN_LANES the instance below closes the loop; in
    // cft_krnl these reach the array cft_engine_stream also drives.
    output logic                 lane_valid,
    output logic [7:0]           lane_op,
    output logic [2:0]           lane_rnd,
    output logic [1:0]           lane_prec,
    output logic [BEAT_BITS-1:0] lane_a,
    output logic [BEAT_BITS-1:0] lane_b,
    output logic [BEAT_BITS-1:0] lane_c,
    input  logic                 lane_ov,
    input  logic [BEAT_BITS-1:0] lane_d,
    input  logic [BEAT_BITS/32*5-1:0] lane_flags,

    // AXI4 read master (single outstanding burst)
    output logic [ADDR_W-1:0] m_rd_araddr,
    output logic [7:0]        m_rd_arlen,
    output logic              m_rd_arvalid,
    input  logic              m_rd_arready,
    input  logic [BEAT_BITS-1:0] m_rd_rdata,
    input  logic              m_rd_rlast,
    input  logic [1:0]        m_rd_rresp,
    input  logic              m_rd_rvalid,
    output logic              m_rd_rready,

    // AXI4 write master (single outstanding burst)
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

  localparam int BEAT_BYTES = BEAT_BITS / 8;          // 32
  localparam int WORDS      = BEAT_BITS / 32;         // 8 banks
  localparam int BLK_LANES  = NBEATS * WORDS;         // 128 at fp32
  localparam int KREG       = 16;                     // addressable consts
  localparam int AR_MAXLEN  = 63;                     // 64-beat bursts
  localparam int LB         = $clog2(BLK_LANES);      // 7
  localparam int DB_D       = NBEATS * MAXD;
  localparam int DBA        = $clog2(DB_D);
  localparam int PCW        = $clog2(IMEM_D);

  localparam logic [1:0] PREC_FP32  = 2'd0;
  localparam logic [1:0] PREC_FP64  = 2'd1;
  localparam logic [1:0] PREC_FP128 = 2'd2;
  localparam logic [1:0] PREC_FP256 = 2'd3;

  // control codes (instruction bit 31 set), from seq.py
  localparam logic [7:0] C_HALT = 8'd0, C_REPEAT = 8'd1, C_ENDREP = 8'd2,
                         C_DEPOSIT = 8'd3, C_SETACT = 8'd4, C_ACTALL = 8'd5;

  // ---- run-latched configuration -------------------------------------
  logic [1:0]        prec_q;
  logic [63:0]       n_q;
  logic [ADDR_W-1:0] a_q, b_q, c_q, d_q, prog_q, cnt_q;

  // element bytes / lanes per beat / log2(lanes per beat)
  logic [5:0] esz;
  logic [3:0] lpb;
  logic [1:0] lpb_sh;      // lanes = WORDS >> prec-ish; lane = beat<<lpb_sh
  always_comb begin
    case (prec_q)
      PREC_FP32:  begin esz = 6'd4;  lpb = 4'd8; lpb_sh = 2'd3; end
      PREC_FP64:  begin esz = 6'd8;  lpb = 4'd4; lpb_sh = 2'd2; end
      PREC_FP128: begin esz = 6'd16; lpb = 4'd2; lpb_sh = 2'd1; end
      default:    begin esz = 6'd32; lpb = 4'd1; lpb_sh = 2'd0; end
    endcase
  end
  // words (32-bit banks) per element, as a shift: esz/4 = 1,2,4,8
  logic [1:0] wpe_sh;
  always_comb begin
    case (prec_q)
      PREC_FP32:  wpe_sh = 2'd0;
      PREC_FP64:  wpe_sh = 2'd1;
      PREC_FP128: wpe_sh = 2'd2;
      default:    wpe_sh = 2'd3;
    endcase
  end

  // ---- program state --------------------------------------------------
  logic [31:0] h_ninsns, h_nconsts, h_maxdep;
  logic [63:0] imem [0:IMEM_D-1];
  logic [255:0] kmem [0:KREG-1];      // low esz*8 bits hold the value

  // broadcast a constant across the beat's lanes
  function automatic [BEAT_BITS-1:0] kbroad(input [255:0] k);
    case (prec_q)
      PREC_FP32:  kbroad = {8{k[31:0]}};
      PREC_FP64:  kbroad = {4{k[63:0]}};
      PREC_FP128: kbroad = {2{k[127:0]}};
      default:    kbroad = k[255:0];
    endcase
  endfunction

  // ---- register file --------------------------------------------------
  // Eight 32-bit word banks, mirrored twice for the three read ports.
  // Word-granular write enables are exactly lane-granular: every
  // format's lane is a whole number of words, so masking a lane masks
  // its words and nothing narrower is ever needed. One conditional
  // whole-word write per bank is the shape every memory compiler
  // recognises - a byte loop over a 256-bit word is the shape that
  // made yosys flatten the file into 130k registers.
  localparam int RF_D = 16 * NBEATS;
  logic [7:0] rf_raddr_a, rf_raddr_b, rf_raddr_c;
  logic [BEAT_BITS-1:0] rf_rdata_a, rf_rdata_b, rf_rdata_c;
  logic        rf_we;
  logic [7:0]  rf_waddr;
  logic [BEAT_BITS-1:0] rf_wdata;
  logic [WORDS-1:0]     rf_wwe;      // per-word (= per-lane-slice) enables

  // Each bank registers its own read data locally and drives its
  // slice of the shared read bus with a continuous assign - the one
  // multi-driver shape the tools all agree on. Eight always_ff blocks
  // each writing a slice of one shared VARIABLE is illegal
  // SystemVerilog that Icarus punishes with event-storm molasses
  // rather than an error message.
  generate
    for (genvar gw = 0; gw < WORDS; gw = gw + 1) begin : g_rf
      logic [31:0] bank0 [0:RF_D-1];
      logic [31:0] bank1 [0:RF_D-1];
      logic [31:0] ra_q, rb_q, rc_q;
      always_ff @(posedge ap_clk) begin
        ra_q <= bank0[rf_raddr_a];
        rb_q <= bank0[rf_raddr_b];
        rc_q <= bank1[rf_raddr_c];
        if (rf_we && rf_wwe[gw]) begin
          bank0[rf_waddr] <= rf_wdata[gw*32 +: 32];
          bank1[rf_waddr] <= rf_wdata[gw*32 +: 32];
        end
      end
      assign rf_rdata_a[gw*32 +: 32] = ra_q;
      assign rf_rdata_b[gw*32 +: 32] = rb_q;
      assign rf_rdata_c[gw*32 +: 32] = rc_q;
    end
  endgenerate

  // ---- deposit buffer -------------------------------------------------
  // Every bank carries its own write address: lanes of one beat hold
  // DIVERGENT deposit counts once SETACT has split them, and a shared
  // address would force a lane-serial deposit. Independent BRAMs make
  // independent addresses free, so a deposit is always one beat per
  // cycle.
  logic [WORDS-1:0]        db_we;
  logic [WORDS*DBA-1:0]    db_waddr;
  logic [WORDS*32-1:0]     db_wdata;
  logic [DBA-1:0]          db_raddr;
  logic [WORDS*32-1:0]     db_rdata;

  generate
    for (genvar gb = 0; gb < WORDS; gb = gb + 1) begin : g_db
      logic [31:0] bank [0:DB_D-1];
      logic [31:0] rd_q;
      always_ff @(posedge ap_clk) begin
        if (db_we[gb])
          bank[db_waddr[gb*DBA +: DBA]] <= db_wdata[gb*32 +: 32];
        rd_q <= bank[db_raddr];
      end
      assign db_rdata[gb*32 +: 32] = rd_q;
    end
  endgenerate

  // ---- lane state -----------------------------------------------------
  // Packed, not unpacked arrays: Verilator refuses non-blocking
  // element writes to unpacked arrays inside loops, and Icarus's
  // implicit sensitivity treats a partially-written unpacked array as
  // read-modify-write of the whole thing - the combination that froze
  // simulation time the first time the drain phase ran. Packed bits
  // have neither problem, and any(active) collapses to a reduction.
  localparam int CW = $clog2(MAXD + 1);
  logic [BLK_LANES-1:0]    active;
  logic [BLK_LANES*CW-1:0] dcnt;
  logic any_active;
  assign any_active = |active;

  // ---- loop stack -----------------------------------------------------
  logic [PCW-1:0] lp_body [0:3];
  logic [31:0]    lp_left [0:3];
  logic [2:0]     lp_sp;

  // ---- the ALU array --------------------------------------------------
  logic                 al_valid;
  logic [7:0]           al_op;
  logic [2:0]           al_rnd;
  logic [BEAT_BITS-1:0] al_a, al_b, al_c;
  logic                 al_ov;
  logic [BEAT_BITS-1:0] al_d;
  logic [WORDS*5-1:0]   al_lf;

  assign lane_valid = al_valid;
  assign lane_op    = al_op;
  assign lane_rnd   = al_rnd;
  assign lane_prec  = prec_q;
  assign lane_a     = al_a;
  assign lane_b     = al_b;
  assign lane_c     = al_c;

  generate
    if (OWN_LANES) begin : g_own_lanes
      cft_lanes #(
          .BEAT_BITS(BEAT_BITS), .LATENCY(LATENCY),
          .EN_FP64(EN_FP64), .EN_FP128(EN_FP128), .EN_FP256(EN_FP256)
      ) u_lanes (
          .clk(ap_clk), .rst_n(ap_rst_n),
          .in_valid(al_valid), .op(al_op), .rnd(al_rnd), .prec(prec_q),
          .a(al_a), .b(al_b), .c(al_c),
          .out_valid(al_ov), .d(al_d), .lane_flags(al_lf));
    end else begin : g_shared_lanes
      assign al_ov = lane_ov;
      assign al_d  = lane_d;
      assign al_lf = lane_flags;
    end
  endgenerate

  // ---- block bookkeeping ----------------------------------------------
  // The lane-block CAPACITY is per-precision: NBEATS beats hold
  // NBEATS * lanes_per_beat lanes - 128 at fp32 but only 16 at fp256.
  // Clamping at the fp32 constant let an fp64 block claim 65 lanes =
  // 17 beats, and beat 16 wrapped onto beat 0 of the same register
  // through the 4-bit beat field while lane 64 was never run at all.
  logic [7:0] blk_cap;
  assign blk_cap = 8'(NBEATS) << lpb_sh;

  logic [63:0] blk_base;
  logic [LB:0] blk_n;              // 1..BLK_LANES
  logic [4:0]  nb_blk;             // beats holding them

  // ---- byte-stream image parser (constants + instructions) -----------
  logic [2*BEAT_BITS-1:0] pw;
  logic [6:0]  pw_have;
  logic [255:0] hdr_q;              // the header beat, verbatim
  logic [31:0] kons_left, insn_left;
  logic [31:0] kons_i, insn_i;

  // ---- AXI read side (single outstanding burst) -----------------------
  logic [ADDR_W-1:0] rd_addr;
  logic [31:0]       rd_beats_left;   // beats not yet requested
  logic [8:0]        rd_burst_left;   // beats left in the open burst
  logic              rd_stream_on;    // a state wants read traffic

  // ---- AXI write side (single outstanding burst) ----------------------
  logic [ADDR_W-1:0] wr_addr;
  logic [31:0]       wr_beats_left;   // beats not yet requested
  logic [8:0]        wr_burst_left;   // W beats left in the open burst
  logic [7:0]        wr_pend_len;
  logic              wr_aw_open;      // AW issued, not yet accepted
  logic [3:0]        wr_bresp_left;
  logic              wr_stream_on;

  function automatic [7:0] burst_len(input [ADDR_W-1:0] addr,
                                     input [31:0] beats);
    logic [31:0] to4k, cap;
    begin
      to4k = (32'd4096 - {20'b0, addr[11:0]}) >> 5;
      cap  = beats;
      if (cap > AR_MAXLEN + 1) cap = AR_MAXLEN + 1;
      if (cap > to4k)          cap = to4k;
      burst_len = 8'(cap - 1);
    end
  endfunction

  // burst lengths for the next read/write request, precomputed so the
  // state machine stays free of block-local declarations (the yosys
  // frontend, which the portability lint gate runs, refuses them)
  // Continuous assigns, NOT always_comb: Icarus livelocks evaluating
  // a function automatic under always_comb's implicit sensitivity the
  // moment its inputs first change - simulation time stops with vvp
  // at full CPU. The bisect that found this took nine builds; the
  // assign form is semantically identical and immune.
  logic [7:0] rd_bl, wr_bl;
  assign rd_bl = burst_len(rd_addr, rd_beats_left);
  assign wr_bl = burst_len(wr_addr, wr_beats_left);

  // ---- beat assembler (drain element stream -> beats) -----------------
  logic [BEAT_BITS-1:0]  as_data;
  logic [BEAT_BYTES-1:0] as_strb;
  logic [5:0]            as_fill;

  // ---- current instruction --------------------------------------------
  logic [63:0] cur;
  logic [7:0]  c_op;
  logic [3:0]  c_rd, c_ra, c_rb, c_rc;
  logic [2:0]  c_rnd;
  logic        c_ka, c_kb, c_kc, c_ctrl;
  logic [31:0] c_imm;
  assign c_op   = cur[7:0];
  assign c_rd   = cur[11:8];
  assign c_ra   = cur[15:12];
  assign c_rb   = cur[19:16];
  assign c_rc   = cur[23:20];
  assign c_rnd  = cur[26:24];
  assign c_ka   = cur[27];
  assign c_kb   = cur[28];
  assign c_kc   = cur[29];
  assign c_ctrl = cur[31];
  assign c_imm  = cur[63:32];

  // ---- state ----------------------------------------------------------
  typedef enum logic [5:0] {
    S_IDLE, S_HDR_GO, S_HDR_R, S_CHECK, S_IMG_GO, S_IMG_PARSE,
    S_BLK_SETUP, S_ZERO, S_LD_GO, S_LD_STREAM,
    S_FETCH, S_FETCH2, S_DECODE,
    S_ALU_ISSUE, S_ALU_WAIT,
    S_DEP_RD, S_DEP_W8, S_DEP_WR,
    S_SET_RD, S_SET_W8, S_SET_AP,
    S_SKIP_F, S_SKIP_D,
    S_DRAIN_SETUP, S_DRAIN_RD, S_DRAIN_W8, S_DRAIN_PACK, S_DRAIN_SEND,
    S_CNT_SETUP, S_CNT_PACK, S_CNT_SEND,
    S_WAIT_B, S_NEXT_BLK, S_FIN
  } state_e;
  state_e st;

  logic [PCW:0]  pc;
  logic [PCW:0]  skip_depth;
  logic [5:0]    bt, wb_bt;
  logic [1:0]    ld_reg;
  logic [LB:0]   lane_cursor;
  logic [31:0]   slot_cursor;
  logic          drain_last;         // the element just packed was final
  logic [8:0]    zaddr;

  logic [4:0]  flags_q;
  logic        dep_ovf_q;
  logic        refuse_q;
  logic        rd_fault_q, wr_fault_q, len_fault_q;

  assign flags  = flags_q;
  assign err    = {dep_ovf_q, len_fault_q, wr_fault_q, rd_fault_q};
  assign refuse = refuse_q;
  assign busy   = (st != S_IDLE);

  // first block-lane of beat `beat` is beat << lpb_sh; lane l sits in
  // beat (l >> lpb_sh) at position (l & (lpb-1))
  function automatic logic lane_in_beat(input int l, input [5:0] beat);
    lane_in_beat = ((l >> lpb_sh) == {26'b0, beat});
  endfunction

  // magnitude-nonzero of lane position `posn` in a beat (SETACT)
  function automatic logic lane_mag_nz(input [BEAT_BITS-1:0] v,
                                       input [2:0] posn);
    logic [BEAT_BITS-1:0] s;
    begin
      // full 32-bit shift arithmetic: the first version's 6-bit
      // self-determined shift wrapped at lane position 2, so every
      // SETACT beyond the first two lanes judged somebody else's
      // magnitude
      s = v >> (32'(posn) << (32'(wpe_sh) + 5));        // posn*esz*8
      case (prec_q)
        PREC_FP32:  lane_mag_nz = |(s[31:0]  & 32'h7fff_ffff);
        PREC_FP64:  lane_mag_nz = |(s[63:0]  & {1'b0, {63{1'b1}}});
        PREC_FP128: lane_mag_nz = |(s[127:0] & {1'b0, {127{1'b1}}});
        default:    lane_mag_nz = |(s[255:0] & {1'b0, {255{1'b1}}});
      endcase
    end
  endfunction

  // the drain element for (lane_cursor, slot_cursor), +0 when the
  // lane never reached the slot; db_rdata was addressed last cycle
  // Function-shaped combinationals: a function body accumulates in
  // ordinary blocking code with no event scheduling inside, so the
  // self-triggering that an accumulator-style always_comb invites
  // under Icarus simply cannot happen.
  // EVERY module-scope value these functions consume is passed as an
  // argument, never read through the function's static scope. Icarus
  // re-evaluates a continuous assign's function call only when its
  // ARGUMENTS change: the first version read db_rdata and dcnt from
  // module scope, so drain_elem updated when the cursors moved but
  // not when the data arrived, and the whole drain stream shipped one
  // element behind itself with a zero at the front. (burst_len never
  // misbehaved for exactly this reason - its reads were always
  // arguments.)
  function automatic [4:0] wb_flags_fn(input [5:0] beat,
                                       input [BLK_LANES-1:0] act,
                                       input [WORDS*5-1:0] lf,
                                       input [3:0] lanes,
                                       input [1:0] lsh);
    logic [4:0] acc;
    begin
      acc = 5'b0;
      for (int p = 0; p < WORDS; p = p + 1)
        if (p < 32'(lanes) && (32'(beat) << lsh) + p < BLK_LANES &&
            act[(32'(beat) << lsh) + p])
          acc = acc | lf[p*5 +: 5];
      wb_flags_fn = acc;
    end
  endfunction
  logic [4:0] wb_flags_or;
  assign wb_flags_or = wb_flags_fn(wb_bt, active, al_lf, lpb, lpb_sh);

  function automatic [255:0] drain_elem_fn(input [LB:0] lc,
                                           input [31:0] sc,
                                           input [WORDS*32-1:0] rdata,
                                           input [BLK_LANES*CW-1:0] cnts,
                                           input [3:0] lanes,
                                           input [1:0] wsh);
    logic [2:0] posn;
    logic [255:0] v;
    begin
      posn = 3'(lc[LB-1:0] & {3'(lanes - 1)});
      v = '0;
      for (int w = 0; w < WORDS; w = w + 1)
        if (w < (32'd1 << wsh))
          v[w*32 +: 32] =
            rdata[(32'({29'b0, posn} << wsh) + w) * 32 +: 32];
      if (sc >= 32'(cnts[32'(lc[LB-1:0]) * CW +: CW]))
        v = '0;
      drain_elem_fn = v;
    end
  endfunction
  logic [255:0] drain_elem;
  assign drain_elem = drain_elem_fn(lane_cursor, slot_cursor,
                                    db_rdata, dcnt, lpb, wpe_sh);


  // ==== the machine ====================================================
  always_ff @(posedge ap_clk) begin
    if (!ap_rst_n) begin
      st <= S_IDLE;
      done <= 1'b0; refuse_q <= 1'b0;
      flags_q <= '0; dep_ovf_q <= 1'b0;
      rd_fault_q <= 1'b0; wr_fault_q <= 1'b0; len_fault_q <= 1'b0;
      m_rd_arvalid <= 1'b0; m_rd_rready <= 1'b0;
      m_wr_awvalid <= 1'b0; m_wr_wvalid <= 1'b0; m_wr_bready <= 1'b0;
      al_valid <= 1'b0; rf_we <= 1'b0;
      db_we <= '0;
      rd_stream_on <= 1'b0; wr_stream_on <= 1'b0;
      rd_beats_left <= '0; rd_burst_left <= '0;
      wr_beats_left <= '0; wr_burst_left <= '0;
      wr_aw_open <= 1'b0; wr_bresp_left <= '0;
      lane_cursor <= '0; slot_cursor <= '0;
      pc <= '0; bt <= '0; wb_bt <= '0; lp_sp <= '0;
      blk_base <= '0; active <= '0; dcnt <= '0;
      rd_addr <= '0; wr_addr <= '0;

    end else begin
      done <= 1'b0;
      al_valid <= 1'b0;
      rf_we <= 1'b0;
      db_we <= '0;

      // ---- read channel: one burst in flight --------------------------
      if (m_rd_arvalid && m_rd_arready)
        m_rd_arvalid <= 1'b0;
      if (m_rd_rvalid && m_rd_rready) begin
        if (m_rd_rresp != 2'b00) rd_fault_q <= 1'b1;
        if (rd_burst_left != 0) begin
          rd_burst_left <= rd_burst_left - 1;
          if (m_rd_rlast && rd_burst_left != 1) len_fault_q <= 1'b1;
          if (!m_rd_rlast && rd_burst_left == 1) len_fault_q <= 1'b1;
        end
      end
      if (rd_stream_on && !m_rd_arvalid && rd_burst_left == 0 &&
          rd_beats_left != 0) begin
        m_rd_araddr   <= rd_addr;
        m_rd_arlen    <= rd_bl;
        m_rd_arvalid  <= 1'b1;
        rd_burst_left <= {1'b0, rd_bl} + 9'd1;
        rd_addr       <= rd_addr + (({56'b0, rd_bl} + 64'd1) << 5);
        rd_beats_left <= rd_beats_left - ({24'b0, rd_bl} + 32'd1);
      end

      // ---- write channel: one burst in flight -------------------------
      if (m_wr_awvalid && m_wr_awready) begin
        m_wr_awvalid <= 1'b0;
        wr_aw_open   <= 1'b0;
        wr_burst_left<= {1'b0, wr_pend_len} + 9'd1;
      end
      if (m_wr_bvalid && m_wr_bready && m_wr_bresp != 2'b00)
        wr_fault_q <= 1'b1;
      // one accounting site for outstanding B responses: an accept
      // and an arrival in the same cycle would otherwise be two
      // non-blocking writes, the second silently discarding the first
      if ((m_wr_awvalid && m_wr_awready) &&
          !(m_wr_bvalid && m_wr_bready))
        wr_bresp_left <= wr_bresp_left + 1;
      else if (!(m_wr_awvalid && m_wr_awready) &&
               (m_wr_bvalid && m_wr_bready))
        wr_bresp_left <= wr_bresp_left - 1;
      if (wr_stream_on && !m_wr_awvalid && !wr_aw_open &&
          wr_burst_left == 0 && wr_beats_left != 0) begin
        m_wr_awaddr   <= wr_addr;
        m_wr_awlen    <= wr_bl;
        m_wr_awvalid  <= 1'b1;
        wr_aw_open    <= 1'b1;
        wr_pend_len   <= wr_bl;
        wr_addr       <= wr_addr + (({56'b0, wr_bl} + 64'd1) << 5);
        wr_beats_left <= wr_beats_left - ({24'b0, wr_bl} + 32'd1);
      end
      if (m_wr_wvalid && m_wr_wready) begin
        m_wr_wvalid <= 1'b0;
        wr_burst_left <= wr_burst_left - 1;
      end

      case (st)
        // --------------------------------------------------------------
        S_IDLE: begin
          if (start) begin
            prec_q <= cfg_prec[1:0];
            n_q <= cfg_n; a_q <= cfg_a; b_q <= cfg_b; c_q <= cfg_c;
            d_q <= cfg_d; prog_q <= cfg_prog; cnt_q <= cfg_cnt;
            flags_q <= '0; dep_ovf_q <= 1'b0; refuse_q <= 1'b0;
            rd_fault_q <= 1'b0; wr_fault_q <= 1'b0; len_fault_q <= 1'b0;
            if (cfg_n == 0)
              done <= 1'b1;
            else
              st <= S_HDR_GO;
          end
        end

        // ---- header: one aligned beat --------------------------------
        S_HDR_GO: begin
          rd_addr <= prog_q;
          rd_beats_left <= 32'd1;
          rd_stream_on <= 1'b1;
          m_rd_rready <= 1'b1;
          st <= S_HDR_R;
        end
        S_HDR_R: begin
          if (m_rd_rvalid && m_rd_rready) begin
            hdr_q <= m_rd_rdata[255:0];
            m_rd_rready <= 1'b0;
            rd_stream_on <= 1'b0;
            st <= S_CHECK;
          end
        end

        S_CHECK: begin
          h_ninsns  <= hdr_q[95:64];
          h_nconsts <= hdr_q[127:96];
          h_maxdep  <= hdr_q[159:128];
          if (hdr_q[31:0] != 32'h5054_4643 || hdr_q[63:32] != 32'd1 ||
              hdr_q[191:160] != {30'b0, prec_q} ||
              hdr_q[95:64] > IMEM_D || hdr_q[127:96] > KMEM_D ||
              hdr_q[159:128] > MAXD) begin
            refuse_q <= 1'b1;
            st <= S_FIN;
          end else
            st <= S_IMG_GO;
        end

        // ---- constants + instructions: dense byte stream -------------
        S_IMG_GO: begin
          rd_addr <= prog_q + 32;
          rd_beats_left <=
            (h_nconsts * {26'b0, esz} + h_ninsns * 32'd8 + 32'd31) >> 5;
          rd_stream_on <= 1'b1;
          kons_left <= h_nconsts;
          insn_left <= h_ninsns;
          kons_i <= '0; insn_i <= '0;
          pw <= '0; pw_have <= '0;
          m_rd_rready <= 1'b1;
          st <= S_IMG_PARSE;
        end

        S_IMG_PARSE: begin
          // One action per cycle - peel a field or absorb a beat -
          // with rready asserted ONLY when the window is too empty to
          // peel. That makes every accepted beat an absorbed beat by
          // construction; the first version held rready high while
          // peeling, so the memory handed over a beat the parser was
          // too busy to take, the handshake counted it, and the bytes
          // fell on the floor - any image larger than one beat then
          // starved forever.
          if (kons_left != 0 && pw_have >= {1'b0, esz}) begin
            if (kons_i < KREG)
              kmem[kons_i[3:0]] <= 256'(pw[255:0]) &
                                   ~(~256'b0 << ({26'b0, esz} << 3));
            pw <= pw >> ({26'b0, esz} << 3);
            pw_have <= pw_have - {1'b0, esz};
            kons_i <= kons_i + 1;
            kons_left <= kons_left - 1;
            m_rd_rready <= ((pw_have - {1'b0, esz}) < 7'd8) &&
                           !(kons_left == 1 && insn_left == 0);
          end else if (kons_left == 0 && insn_left != 0 &&
                       pw_have >= 7'd8) begin
            imem[insn_i[PCW-1:0]] <= pw[63:0];
            pw <= pw >> 64;
            pw_have <= pw_have - 7'd8;
            insn_left <= insn_left - 1;
            insn_i <= insn_i + 1;
            m_rd_rready <= ((pw_have - 7'd8) < 7'd8) &&
                           (insn_left != 1);
          end else if (m_rd_rvalid && m_rd_rready) begin
            pw <= pw | ({{BEAT_BITS{1'b0}}, m_rd_rdata}
                        << ({2'b0, pw_have} << 3));
            pw_have <= pw_have + 7'(BEAT_BYTES);
            m_rd_rready <= 1'b0;         // window now needs draining
          end else if (kons_left == 0 && insn_left == 0) begin
            m_rd_rready <= 1'b0;
            rd_stream_on <= 1'b0;
            blk_base <= '0;
            st <= S_BLK_SETUP;
          end else
            m_rd_rready <= (pw_have < 7'd8);
        end

        // ---- per-block setup -----------------------------------------
        S_BLK_SETUP: begin
          if (blk_base >= n_q)
            st <= S_FIN;
          else begin
            blk_n <= (n_q - blk_base > {56'b0, blk_cap})
                     ? (LB+1)'(blk_cap)
                     : (LB+1)'(n_q - blk_base);
            zaddr <= '0;
            st <= S_ZERO;
          end
        end

        S_ZERO: begin
          // wipe the register file: RF_D cycles per block buys
          // "the previous block cannot leak" with no bookkeeping
          rf_we <= 1'b1;
          rf_waddr <= zaddr[7:0];
          rf_wdata <= '0;
          rf_wwe <= {WORDS{1'b1}};
          zaddr <= zaddr + 1;
          if (zaddr == 9'(RF_D - 1)) begin
            for (int l = 0; l < BLK_LANES; l = l + 1)
              active[l] <= (l < 32'(blk_cap)) && (blk_base + l < n_q);
            dcnt <= '0;
            nb_blk <= 5'(({58'b0, esz} * blk_n + BEAT_BYTES - 1) >> 5);
            ld_reg <= 2'd0;
            pc <= '0;
            lp_sp <= '0;
            st <= S_LD_GO;
          end
        end

        S_LD_GO: begin
          rd_addr <= (ld_reg == 0 ? a_q : ld_reg == 1 ? b_q : c_q)
                     + blk_base * {58'b0, esz};
          rd_beats_left <= {27'b0, nb_blk};
          rd_stream_on <= 1'b1;
          m_rd_rready <= 1'b1;
          bt <= '0;
          st <= S_LD_STREAM;
        end

        S_LD_STREAM: begin
          if (m_rd_rvalid && m_rd_rready) begin
            rf_we <= 1'b1;
            rf_waddr <= {2'b0, ld_reg, bt[3:0]};
            rf_wdata <= m_rd_rdata;
            rf_wwe <= {WORDS{1'b1}};
            bt <= bt + 1;
            if (bt == 6'({27'b0, nb_blk} - 1)) begin
              m_rd_rready <= 1'b0;
              rd_stream_on <= 1'b0;
              if (ld_reg == 2'd2)
                st <= S_FETCH;
              else begin
                ld_reg <= ld_reg + 1;
                st <= S_LD_GO;
              end
            end
          end
        end

        // ---- fetch/decode --------------------------------------------
        S_FETCH: begin
          if ({21'b0, pc} >= h_ninsns)
            st <= S_DRAIN_SETUP;               // implicit halt
          else begin
            cur <= imem[pc[PCW-1:0]];
            st <= S_FETCH2;
          end
        end
        S_FETCH2: st <= S_DECODE;

        S_DECODE: begin
          if (!c_ctrl) begin
            bt <= '0; wb_bt <= '0;
            st <= S_ALU_ISSUE;
          end else begin
            case (c_op)
              C_REPEAT: begin
                if (c_imm == 0 || !any_active) begin
                  skip_depth <= (PCW+1)'(1);
                  pc <= pc + 1;
                  st <= S_SKIP_F;
                end else begin
                  lp_body[lp_sp[1:0]] <= pc[PCW-1:0] + PCW'(1);
                  lp_left[lp_sp[1:0]] <= c_imm;
                  lp_sp <= lp_sp + 1;
                  pc <= pc + 1;
                  st <= S_FETCH;
                end
              end
              C_ENDREP: begin
                if (lp_sp == 0)
                  st <= S_DRAIN_SETUP;         // unmatched: halt
                else if (lp_left[lp_sp[1:0] - 2'd1] > 1 && any_active)
                begin
                  lp_left[lp_sp[1:0] - 2'd1] <=
                    lp_left[lp_sp[1:0] - 2'd1] - 1;
                  pc <= {1'b0, lp_body[lp_sp[1:0] - 2'd1]};
                  st <= S_FETCH;
                end else begin
                  lp_sp <= lp_sp - 1;
                  pc <= pc + 1;
                  st <= S_FETCH;
                end
              end
              C_DEPOSIT: begin
                bt <= '0;
                st <= S_DEP_RD;
              end
              C_SETACT: begin
                bt <= '0;
                st <= S_SET_RD;
              end
              C_ACTALL: begin
                for (int l = 0; l < BLK_LANES; l = l + 1)
                  active[l] <= (l < 32'(blk_cap)) &&
                               (blk_base + l < n_q);
                pc <= pc + 1;
                st <= S_FETCH;
              end
              default: st <= S_DRAIN_SETUP;    // HALT and unknowns
            endcase
          end
        end

        // ---- skip to the matching endrep ------------------------------
        S_SKIP_F: begin
          if ({21'b0, pc} >= h_ninsns)
            st <= S_DRAIN_SETUP;               // unbalanced: halt
          else begin
            cur <= imem[pc[PCW-1:0]];
            st <= S_SKIP_D;
          end
        end
        S_SKIP_D: begin
          pc <= pc + 1;
          st <= S_SKIP_F;
          if (c_ctrl && c_op == C_REPEAT)
            skip_depth <= skip_depth + 1;
          else if (c_ctrl && c_op == C_ENDREP) begin
            if (skip_depth == 1)
              st <= S_FETCH;
            else
              skip_depth <= skip_depth - 1;
          end
        end

        // ---- ALU issue / writeback ------------------------------------
        S_ALU_ISSUE: begin
          // The banked register file costs TWO cycles from address to
          // data (the address registers into the bank read, the read
          // registers into the slice bus), so addresses run two beats
          // ahead of the array: cycle c presents beat c's address and
          // fires beat c-2 from the data now on the bus. Getting this
          // off by one shifted every operand a beat and failed every
          // deposit slot at once - the bench's first catch.
          if (bt < 6'({1'b0, nb_blk})) begin
            rf_raddr_a <= {c_ra, bt[3:0]};
            rf_raddr_b <= {c_rb, bt[3:0]};
            rf_raddr_c <= {c_rc, bt[3:0]};
          end
          if (bt >= 6'd2) begin
            al_valid <= 1'b1;
            al_op <= c_op;
            al_rnd <= c_rnd;
            al_a <= c_ka ? kbroad(kmem[c_ra]) : rf_rdata_a;
            al_b <= c_kb ? kbroad(kmem[c_rb]) : rf_rdata_b;
            al_c <= c_kc ? kbroad(kmem[c_rc]) : rf_rdata_c;
          end
          bt <= bt + 1;
          if (bt == 6'({1'b0, nb_blk} + 1))
            st <= S_ALU_WAIT;
          // With NBEATS > LATENCY the first result retires DURING the
          // last issue cycles - beat 0 lands exactly at issue cycle
          // LATENCY - so the writeback path runs here too. Missing
          // this dropped the first beat of every 16-beat block.
          if (al_ov) begin
            rf_we <= 1'b1;
            rf_waddr <= {c_rd, wb_bt[3:0]};
            rf_wdata <= al_d;
            for (int w = 0; w < WORDS; w = w + 1)
              rf_wwe[w] <=
                active[(32'(wb_bt) << lpb_sh) + (w >> wpe_sh)];
            flags_q <= flags_q | wb_flags_or;
            wb_bt <= wb_bt + 1;
          end
        end

        S_ALU_WAIT: begin
          if (al_ov) begin
            rf_we <= 1'b1;
            rf_waddr <= {c_rd, wb_bt[3:0]};
            rf_wdata <= al_d;
            for (int w = 0; w < WORDS; w = w + 1)
              rf_wwe[w] <=
                active[(32'(wb_bt) << lpb_sh) + (w >> wpe_sh)];
            flags_q <= flags_q | wb_flags_or;
            wb_bt <= wb_bt + 1;
            if (wb_bt == 6'({1'b0, nb_blk} - 1)) begin
              pc <= pc + 1;
              st <= S_FETCH;
            end
          end
        end

        // ---- DEPOSIT ---------------------------------------------------
        S_DEP_RD: begin
          rf_raddr_a <= {c_ra, bt[3:0]};
          st <= S_DEP_W8;
        end
        S_DEP_W8: st <= S_DEP_WR;    // bank read + bus register
        S_DEP_WR: begin
          // regs[ra][bt] is on rf_rdata_a. Each active, in-capacity
          // lane of this beat writes its own bank set at its own
          // slot; the banks' independent write addresses are what
          // makes one beat per cycle possible even after SETACT has
          // left the beat's lanes with divergent counts.
          for (int p = 0; p < WORDS; p = p + 1)
            if ((p >> wpe_sh) < 32'(lpb) &&
                (32'(bt) << lpb_sh) + (p >> wpe_sh) < BLK_LANES &&
                active[(32'(bt) << lpb_sh) + (p >> wpe_sh)] &&
                32'(dcnt[((32'(bt) << lpb_sh) + (p >> wpe_sh)) * CW
                         +: CW]) < h_maxdep) begin
              db_we[p] <= 1'b1;
              db_waddr[p*DBA +: DBA] <= DBA'(32'(bt) * MAXD +
                  32'(dcnt[((32'(bt) << lpb_sh) + (p >> wpe_sh)) * CW
                           +: CW]));
              db_wdata[p*32 +: 32] <= rf_rdata_a[p*32 +: 32];
            end
          for (int l = 0; l < BLK_LANES; l = l + 1)
            if ((l >> lpb_sh) == 32'(bt) && active[l]) begin
              if (32'(dcnt[l*CW +: CW]) < h_maxdep)
                dcnt[l*CW +: CW] <= dcnt[l*CW +: CW] + CW'(1);
              else
                dep_ovf_q <= 1'b1;
            end
          bt <= bt + 1;
          if (bt == 6'({1'b0, nb_blk} - 1)) begin
            pc <= pc + 1;
            st <= S_FETCH;
          end else
            st <= S_DEP_RD;
        end

        // ---- SETACT ----------------------------------------------------
        S_SET_RD: begin
          rf_raddr_a <= {c_ra, bt[3:0]};
          st <= S_SET_W8;
        end
        S_SET_W8: st <= S_SET_AP;
        S_SET_AP: begin
          for (int l = 0; l < BLK_LANES; l = l + 1)
            if ((l >> lpb_sh) == 32'(bt) && active[l])
              active[l] <= lane_mag_nz(rf_rdata_a, 3'(l & (lpb - 1)));
          bt <= bt + 1;
          if (bt == 6'({1'b0, nb_blk} - 1)) begin
            pc <= pc + 1;
            st <= S_FETCH;
          end else
            st <= S_SET_RD;
        end

        // ---- deposit drain --------------------------------------------
        S_DRAIN_SETUP: begin
          lane_cursor <= '0;
          slot_cursor <= '0;
          as_fill <= '0; as_strb <= '0; as_data <= '0;
          drain_last <= 1'b0;
          wr_addr <= d_q + blk_base * {58'b0, esz} * {32'b0, h_maxdep};
          wr_beats_left <= 32'(({32'b0, blk_n} * {58'b0, esz}
                                * {32'b0, h_maxdep}
                                + BEAT_BYTES - 1) >> 5);
          wr_stream_on <= 1'b1;
          wr_bresp_left <= '0;
          m_wr_bready <= 1'b1;
          if (h_maxdep == 0)
            st <= S_CNT_SETUP;
          else begin
            db_raddr <= DBA'(0);
            st <= S_DRAIN_RD;
          end
        end

        S_DRAIN_RD: begin
          db_raddr <= DBA'(32'(lane_cursor >> lpb_sh) * MAXD
                           + slot_cursor);
          st <= S_DRAIN_W8;
        end
        S_DRAIN_W8: st <= S_DRAIN_PACK;

        S_DRAIN_PACK: begin
          for (int by = 0; by < 32; by = by + 1)
            if (by < 32'(esz)) begin
              as_data[(32'(as_fill) + by) * 8 +: 8] <=
                drain_elem[by*8 +: 8];
              as_strb[32'(as_fill) + by] <= 1'b1;
            end
          as_fill <= as_fill + esz;
          if (32'(lane_cursor) == 32'(blk_n) - 1 &&
              slot_cursor == h_maxdep - 1)
            drain_last <= 1'b1;
          if (slot_cursor == h_maxdep - 1) begin
            slot_cursor <= '0;
            lane_cursor <= lane_cursor + 1;
          end else
            slot_cursor <= slot_cursor + 1;
          if ({1'b0, as_fill} + {1'b0, esz} == 7'(BEAT_BYTES) ||
              (32'(lane_cursor) == 32'(blk_n) - 1 &&
               slot_cursor == h_maxdep - 1))
            st <= S_DRAIN_SEND;
          else
            st <= S_DRAIN_RD;
        end

        S_DRAIN_SEND: begin
          // wait for an open burst window and a free W slot
          if ((!m_wr_wvalid || m_wr_wready) && wr_burst_left != 0) begin
            m_wr_wvalid <= 1'b1;
            m_wr_wdata <= as_data;
            m_wr_wstrb <= as_strb;
            m_wr_wlast <= (wr_burst_left == 1);
            as_fill <= '0; as_strb <= '0; as_data <= '0;
            if (drain_last)
              st <= S_CNT_SETUP;
            else
              st <= S_DRAIN_RD;
          end
        end

        // ---- counts drain ---------------------------------------------
        S_CNT_SETUP: begin
          // deposits may still owe W beats when maxdep==0 skipped
          // straight here; the write plumbing continues regardless
          lane_cursor <= '0;
          as_fill <= '0; as_strb <= '0; as_data <= '0;
          drain_last <= 1'b0;
          // NOTE: the deposit stream's bursts complete before this
          // reprogram because wr_beats_left reached zero exactly when
          // the last deposit beat was addressed; wait for the channel
          // to go quiet before switching targets
          if (wr_burst_left == 0 && !m_wr_awvalid && !wr_aw_open &&
              !m_wr_wvalid && wr_beats_left == 0) begin
            wr_addr <= cnt_q + blk_base * 4;
            wr_beats_left <= (32'({32'b0, blk_n} * 4)
                              + BEAT_BYTES - 1) >> 5;
            st <= S_CNT_PACK;
          end
        end

        S_CNT_PACK: begin
          as_data[32'(as_fill) * 8 +: 32] <=
            32'(dcnt[32'(lane_cursor[LB-1:0]) * CW +: CW]);
          for (int by = 0; by < 4; by = by + 1)
            as_strb[32'(as_fill) + by] <= 1'b1;
          as_fill <= as_fill + 6'd4;
          if (32'(lane_cursor) == 32'(blk_n) - 1)
            drain_last <= 1'b1;
          lane_cursor <= lane_cursor + 1;
          if ({1'b0, as_fill} + 7'd4 == 7'(BEAT_BYTES) ||
              32'(lane_cursor) == 32'(blk_n) - 1)
            st <= S_CNT_SEND;
        end

        S_CNT_SEND: begin
          if ((!m_wr_wvalid || m_wr_wready) && wr_burst_left != 0) begin
            m_wr_wvalid <= 1'b1;
            m_wr_wdata <= as_data;
            m_wr_wstrb <= as_strb;
            m_wr_wlast <= (wr_burst_left == 1);
            as_fill <= '0; as_strb <= '0; as_data <= '0;
            if (drain_last)
              st <= S_WAIT_B;
            else
              st <= S_CNT_PACK;
          end
        end

        S_WAIT_B: begin
          if (wr_bresp_left == 0 && !m_wr_wvalid && !m_wr_awvalid &&
              !wr_aw_open && wr_burst_left == 0) begin
            m_wr_bready <= 1'b0;
            wr_stream_on <= 1'b0;
            st <= S_NEXT_BLK;
          end
        end

        S_NEXT_BLK: begin
          blk_base <= blk_base + {56'b0, blk_cap};
          st <= S_BLK_SETUP;
        end

        S_FIN: begin
          done <= 1'b1;
          st <= S_IDLE;
        end

        default: st <= S_IDLE;
      endcase
    end
  end

endmodule
