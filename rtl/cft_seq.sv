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
//                   constants, held already broadcast across the beat
//                   because a run's format never changes.
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
    //
    // m_rd_sel names the buffer each read belongs to: 0 = the program
    // image and the A operand, 1 = B, 2 = C. It exists because an
    // ADDRESS is not always enough to reach a buffer.
    //
    // On this platform every master is bound to one HBM pseudo-channel
    // (hw/link.cfg), so the A master cannot reach an address in HBM[1]
    // however correct that address is - which is precisely how this
    // module's first device run failed: DECERR on every program,
    // because r1 and r2 are loaded from buffers XRT places in HBM[1]
    // and HBM[2]. cft_krnl uses this select to steer the request at
    // the master that owns the bank.
    //
    // FOR A DIFFERENT MEMORY SYSTEM, which is where the open cores are
    // going: with ONE flat port - DDR3/4 behind a single controller, or
    // PCIe into host RAM - the select is redundant. Tie the masters
    // together and the address alone suffices, because there is only
    // one place an address can mean. The single-master shape this
    // module already had is the RIGHT one there and the cheaper one
    // (a single AR channel, no arbitration, no replicated read data
    // path); it is BANKED memory that forces the fan-out, not the
    // sequencer. So the select is an output rather than a parameter:
    // a single-port integration ignores it and pays nothing, and no
    // second version of this module has to exist.
    output logic [1:0]        m_rd_sel,
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
  // ...and the same number as a SHIFT AMOUNT on bytes: esz == 1 <<
  // esz_sh. An element is (1 << wpe_sh) words and a word is
  // BEAT_BYTES/WORDS bytes, so this is derived from the decode above
  // rather than written down a second time. Every address in this
  // module scales by esz; a fifth transcription of 4/8/16/32 is a
  // fifth chance to get one of them wrong.
  logic [2:0] esz_sh;
  assign esz_sh = {1'b0, wpe_sh} + 3'($clog2(BEAT_BYTES / WORDS));

  // ---- program state --------------------------------------------------
  logic [31:0] h_ninsns, h_nconsts, h_maxdep;
  logic [63:0] imem [0:IMEM_D-1];
  logic [BEAT_BITS-1:0] kmem [0:KREG-1];   // broadcast across the beat

  // broadcast a constant across the beat's lanes. Applied ONCE, as
  // the constant is parsed out of the image, so kmem holds the
  // broadcast form and issue reads it straight through: the same
  // three operands were each carrying their own copy of this
  // multiplexer on the issue path, for a value that cannot change
  // during a run.
  // Replication counts and slice widths follow the beat, so the
  // function elaborates on a narrower tile (the quarter tile's 64-bit
  // beat compiles this module even though its sequencer is refused at
  // start - cft_krnl needs the whole kernel to elaborate under every
  // simulator, Verilator included). At 256 every value below is what
  // was written here before: 8/4/2/1 copies of 32/64/128/256 bits.
  localparam int KW64  = (BEAT_BITS < 64)  ? BEAT_BITS : 64;
  localparam int KW128 = (BEAT_BITS < 128) ? BEAT_BITS : 128;
  localparam int KW256 = (BEAT_BITS < 256) ? BEAT_BITS : 256;
  function automatic [BEAT_BITS-1:0] kbroad(input [255:0] k);
    case (prec_q)
      PREC_FP32:  kbroad = {(BEAT_BITS / 32){k[31:0]}};
      PREC_FP64:  kbroad = {(BEAT_BITS / KW64){k[KW64-1:0]}};
      PREC_FP128: kbroad = {(BEAT_BITS / KW128){k[KW128-1:0]}};
      default:    kbroad = k[KW256-1:0];
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
  //
  // Indexed by SLOT - beat * WORDS + position-within-beat - and NOT
  // by the dense lane index. The two agree at fp32 and part below it:
  // an fp64 beat holds four lanes but still owns eight slots, four of
  // them permanently empty. The vector is the same NBEATS * WORDS
  // bits either way, because that is what BLK_LANES is.
  //
  // What the fixed stride buys is that "which lanes belong to beat
  // bt" stops being a question about all 128 of them. Under the dense
  // index it read `(l >> lpb_sh) == bt`, a run-time shift asked of
  // every lane, so DEPOSIT carried 128 counter increments and 128
  // enable terms and SETACT carried 128 magnitude tests - for eight
  // lanes of work. With the stride fixed it is a compare against the
  // slot's own constant beat number, one decoder shared by the eight
  // positions, and every one of those loops runs over WORDS instead
  // of BLK_LANES. It is also the register file's own shape: that has
  // always been addressed {reg, beat} with one enable per word.
  localparam int CW   = $clog2(MAXD + 1);
  localparam int NBSH = $clog2(NBEATS);      // beat index width
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

  // Where this block sits in the caller's buffers, carried forward a
  // block at a time instead of multiplied out. One block covers
  // blk_cap * esz bytes of input, and that is NBEATS * BEAT_BYTES at
  // EVERY precision - blk_cap is NBEATS << lpb_sh and esz is
  // BEAT_BYTES >> lpb_sh, so the shifts cancel. The input stride is
  // therefore a compile-time constant, and the deposit stride is that
  // constant scaled by max_deposits: one shift of a header field,
  // taken once per run.
  //
  // Written the obvious way - d_q + blk_base * esz * h_maxdep - that
  // address was a 64x6x32 product in a single cycle, four DSP48
  // slices in cascade feeding a 64-bit adder, and it was the kernel's
  // worst path by 0.17 ns at 135 MHz.
  localparam int BLK_BYTES = NBEATS * BEAT_BYTES;
  localparam int BLK_SH    = $clog2(BLK_BYTES);
  logic [ADDR_W-1:0] in_off;       // blk_base * esz
  logic [ADDR_W-1:0] dep_off;      // blk_base * esz * h_maxdep
  logic [ADDR_W-1:0] dep_stride;   // BLK_BYTES * h_maxdep

  // blk_n * max_deposits, the block's deposit-element count. Both
  // factors are run-time values, so this is the one product in the
  // module that no shift replaces; it is formed one bit of the
  // multiplier per cycle inside the register-file wipe, which is RF_D
  // cycles long and has CW of them to spare.
  logic [31:0]   dep_elems;
  logic [31:0]   dep_addend;
  logic [CW-1:0] dep_mult;

  // ---- byte-stream image parser (constants + instructions) -----------
  // The peel window never holds more than one absorbed beat plus the
  // residue that made room for it, and rready is asserted ONLY when
  // that residue is about to fall below 8 bytes (see S_IMG_PARSE), so
  // its high-water mark is BEAT_BYTES + 7. Sized at two beats and
  // filled with a shift by the full 7-bit byte count, the absorb was
  // a 512-bit barrel shifter with 512 positions - nine stages of
  // 512-bit multiplexer for a value that only ever lands on one of
  // eight byte offsets.
  localparam int PWW = BEAT_BITS + 64;
  logic [PWW-1:0] pw;
  logic [6:0]  pw_have;
  logic [255:0] hdr_q;              // the header beat, verbatim
  logic [31:0] kons_left, insn_left;
  logic [31:0] kons_i, insn_i;

  // ---- AXI read side (single outstanding burst) -----------------------
  logic [ADDR_W-1:0] rd_addr;
  logic [1:0]        rd_sel;   // which buffer rd_addr points into
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

  // ---- reaching one beat's row of lane state ------------------------
  // NOTHING below indexes `active` or `dcnt` with a computed
  // expression. Every select and every write here is a loop over
  // CONSTANT indices with an equality test picking the beat, and that
  // is the whole trick: a variable part-select of a wide packed
  // vector is a promise the tool cannot check, so it hedges. On the
  // read side it builds a multiplexer over every offset the
  // expression's range allows; on the WRITE side it is worse, because
  // it must decide per bit whether the window covers it, and dcnt is
  // 896 bits. `dcnt[<expr> +: CW] <= v` cost 6,933 LUTs - more than
  // half of everything left in the module - and the same behaviour
  // written as sixteen constant-index alternatives costs the sixteen
  // comparators, because the flip-flops then take their own enables.
  // The beat index is truncated to the NBSH bits the register file
  // already addresses with (rf_waddr carries wb_bt[NBSH-1:0]), so no
  // caller needs a range guard.
  function automatic [WORDS-1:0] row_act_fn(input [BLK_LANES-1:0] act,
                                            input [5:0] beat);
    logic [WORDS-1:0] r;
    begin
      r = '0;
      for (int b = 0; b < NBEATS; b = b + 1)
        if (b == 32'(beat[NBSH-1:0]))
          r = act[b*WORDS +: WORDS];
      row_act_fn = r;
    end
  endfunction

  function automatic [WORDS*CW-1:0] row_cnt_fn(
                                       input [BLK_LANES*CW-1:0] cnts,
                                       input [5:0] beat);
    logic [WORDS*CW-1:0] r;
    begin
      r = '0;
      for (int b = 0; b < NBEATS; b = b + 1)
        if (b == 32'(beat[NBSH-1:0]))
          r = cnts[b*WORDS*CW +: WORDS*CW];
      row_cnt_fn = r;
    end
  endfunction

  function automatic [CW-1:0] pick_cnt_fn(input [WORDS*CW-1:0] row,
                                          input [2:0] posn);
    logic [CW-1:0] r;
    begin
      r = '0;
      for (int q = 0; q < WORDS; q = q + 1)
        if (q == 32'({29'b0, posn}))
          r = row[q*CW +: CW];
      pick_cnt_fn = r;
    end
  endfunction

  // The row DEPOSIT and SETACT are working on, and the row retiring
  // into the register file.
  logic [WORDS-1:0]    bt_act, wb_act;
  logic [WORDS*CW-1:0] bt_cnt;
  assign bt_act = row_act_fn(active, bt);
  assign wb_act = row_act_fn(active, wb_bt);
  assign bt_cnt = row_cnt_fn(dcnt, bt);

  // DEPOSIT's whole decision for the row: which positions may append,
  // which have run out of slots, and what their counts become. Eight
  // incrementers and eight comparators serve all sixteen beats,
  // because the write below only selects between them.
  logic [WORDS*CW-1:0] bt_cnt_inc;
  logic [WORDS-1:0]    bt_dep_go, bt_dep_ovf;
  generate
    for (genvar gq = 0; gq < WORDS; gq = gq + 1) begin : g_dep
      assign bt_cnt_inc[gq*CW +: CW] = bt_cnt[gq*CW +: CW] + CW'(1);
      assign bt_dep_go[gq]  = (gq < 32'(lpb)) && bt_act[gq] &&
                              (32'(bt_cnt[gq*CW +: CW]) < h_maxdep);
      assign bt_dep_ovf[gq] = (gq < 32'(lpb)) && bt_act[gq] &&
                              !(32'(bt_cnt[gq*CW +: CW]) < h_maxdep);
    end
  endgenerate

  // magnitude-nonzero of lane position `posn` in a beat (SETACT),
  // asked of the beat's per-word OR terms rather than of the beat.
  // A lane's field is a run of whole 32-bit words and its sign bit is
  // the top bit of the run's top word, so the only word that needs
  // the sign masked off is that one, and nothing needs shifting. The
  // first version shifted the whole 256-bit beat down by posn * esz *
  // 8 - and its predecessor got the shift's self-determined width
  // wrong, so every SETACT beyond lane position 2 judged somebody
  // else's magnitude. There is no shift left to get wrong.
  logic [WORDS-1:0] sa_wor, sa_worm;
  generate
    for (genvar gs = 0; gs < WORDS; gs = gs + 1) begin : g_sa
      assign sa_wor[gs]  = |rf_rdata_a[gs*32 +: 32];
      assign sa_worm[gs] = |(rf_rdata_a[gs*32 +: 32] & 32'h7fff_ffff);
    end
  endgenerate

  // (the OR terms are named word_or/word_orm because `wor` is a
  // Verilog net type and an argument called that parses as one)
  // sa_nz below is SETACT's answer for all eight positions.
  function automatic logic lane_mag_nz(input [WORDS-1:0] word_or,
                                       input [WORDS-1:0] word_orm,
                                       input [2:0] posn,
                                       input [1:0] wsh);
    logic acc;
    begin
      acc = 1'b0;
      for (int w = 0; w < WORDS; w = w + 1)
        if ((32'(w) >> wsh) == 32'({29'b0, posn})) begin
          if ((32'(w) & ((32'd1 << wsh) - 32'd1)) ==
              ((32'd1 << wsh) - 32'd1))
            acc = acc | word_orm[w];      // the element's top word
          else
            acc = acc | word_or[w];
        end
      lane_mag_nz = acc;
    end
  endfunction
  logic [WORDS-1:0] sa_nz;
  generate
    for (genvar gn = 0; gn < WORDS; gn = gn + 1) begin : g_nz
      assign sa_nz[gn] = lane_mag_nz(sa_wor, sa_worm, 3'(gn), wpe_sh);
    end
  endgenerate

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
  function automatic [4:0] wb_flags_fn(input [WORDS-1:0] act,
                                       input [WORDS*5-1:0] lf,
                                       input [3:0] lanes);
    logic [4:0] acc;
    begin
      acc = 5'b0;
      for (int p = 0; p < WORDS; p = p + 1)
        if (p < 32'(lanes) && act[p])
          acc = acc | lf[p*5 +: 5];
      wb_flags_fn = acc;
    end
  endfunction
  logic [4:0] wb_flags_or;
  assign wb_flags_or = wb_flags_fn(wb_act, al_lf, lpb);

  // Per-word register-file write enables for the beat retiring now:
  // word w carries lane position w >> wpe_sh, and a word enable IS a
  // lane enable because every format's element is a whole number of
  // words. Built once here rather than twice in the state machine -
  // the issue state and the wait state retire beats through the same
  // masking and were carrying a copy each.
  function automatic [WORDS-1:0] wb_wwe_fn(input [WORDS-1:0] act,
                                           input [1:0] wsh);
    logic [WORDS-1:0] e;
    begin
      e = '0;
      for (int w = 0; w < WORDS; w = w + 1)
        e[w] = act[32'(w) >> wsh];
      wb_wwe_fn = e;
    end
  endfunction
  logic [WORDS-1:0] wb_wwe;
  assign wb_wwe = wb_wwe_fn(wb_act, wpe_sh);

  // The block's opening active mask: slot (b, p) belongs to a lane
  // the caller has iff the position exists at this format and the
  // lane's index within the block is below blk_n. Both the per-block
  // wipe and ACTALL want exactly this, and ACTALL's contract is that
  // it reactivates every lane THE CALLER HAS, so the two must not be
  // allowed to drift apart.
  function automatic [BLK_LANES-1:0] blk_act_fn(input [LB:0] bn,
                                                input [3:0] lanes,
                                                input [1:0] lsh);
    logic [BLK_LANES-1:0] m;
    begin
      m = '0;
      for (int b = 0; b < NBEATS; b = b + 1)
        for (int p = 0; p < WORDS; p = p + 1)
          m[b*WORDS + p] = (p < 32'(lanes)) &&
                           (((32'(b) << lsh) + p) < 32'(bn));
      blk_act_fn = m;
    end
  endfunction
  logic [BLK_LANES-1:0] blk_act;
  assign blk_act = blk_act_fn(blk_n, lpb, lpb_sh);

  // lane_cursor counts lanes densely - the drain visits them in the
  // caller's index order - while the lane state is addressed by slot,
  // so the two meet here.
  // The drain cursor's beat and position. lane_cursor counts lanes
  // densely - the drain visits them in the caller's index order -
  // while the lane state is addressed by (beat, position).
  logic [5:0] dc_beat;
  logic [2:0] dc_posn;
  assign dc_beat = 6'(32'(lane_cursor[LB-1:0]) >> lpb_sh);
  assign dc_posn = lane_cursor[2:0] & 3'(lpb - 4'd1);

  // The cursor lane's deposit count, selected once. Both the drain
  // ("has this lane reached this slot?") and the count pack want it,
  // and each selecting it for itself was a second 128-entry lookup
  // into a 896-bit vector. dcnt is read in the assign itself, not
  // through a function's scope, so it is in the sensitivity.
  logic [WORDS*CW-1:0] dc_row;
  logic [CW-1:0]       cur_cnt;
  assign dc_row  = row_cnt_fn(dcnt, dc_beat);
  assign cur_cnt = pick_cnt_fn(dc_row, dc_posn);

  function automatic [255:0] drain_elem_fn(input [2:0] posn,
                                           input [31:0] sc,
                                           input [CW-1:0] cnt,
                                           input [WORDS*32-1:0] rdata,
                                           input [1:0] wsh);
    logic [255:0] v;
    begin
      v = '0;
      // lane `posn` occupies banks posn << wsh upward; both sides of
      // this are constant selects with an equality picking the bank,
      // for the reason row_act_fn gives.
      for (int w = 0; w < WORDS; w = w + 1)
        for (int src = 0; src < WORDS; src = src + 1)
          if (w < (32'd1 << wsh) &&
              src == 32'({29'b0, posn} << wsh) + w)
            v[w*32 +: 32] = rdata[src*32 +: 32];
      if (sc >= 32'(cnt))
        v = '0;
      drain_elem_fn = v;
    end
  endfunction
  logic [255:0] drain_elem;
  assign drain_elem = drain_elem_fn(dc_posn, slot_cursor, cur_cnt,
                                    db_rdata, wpe_sh);


  // ==== the machine ====================================================
  always_ff @(posedge ap_clk) begin
    if (!ap_rst_n) begin
      st <= S_IDLE;
      done <= 1'b0; refuse_q <= 1'b0;
      flags_q <= '0; dep_ovf_q <= 1'b0;
      rd_fault_q <= 1'b0; wr_fault_q <= 1'b0; len_fault_q <= 1'b0;
      m_rd_arvalid <= 1'b0; m_rd_rready <= 1'b0; m_rd_sel <= 2'd0;
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
      in_off <= '0; dep_off <= '0;
      rd_addr <= '0; rd_sel <= 2'd0; wr_addr <= '0;

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
        m_rd_sel      <= rd_sel;
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
          rd_sel  <= 2'd0;    // the image sits with the A operand
          rd_beats_left <= 32'd1;
          rd_stream_on <= 1'b1;
          m_rd_rready <= 1'b1;
          st <= S_HDR_R;
        end
        S_HDR_R: begin
          if (m_rd_rvalid && m_rd_rready) begin
            // 256'() rather than [255:0]: the beat is BEAT_BITS wide, and a
            // select past its top does not elaborate on a narrow tile.
            hdr_q <= 256'(m_rd_rdata);
            m_rd_rready <= 1'b0;
            rd_stream_on <= 1'b0;
            st <= S_CHECK;
          end
        end

        S_CHECK: begin
          h_ninsns  <= hdr_q[95:64];
          h_nconsts <= hdr_q[127:96];
          h_maxdep  <= hdr_q[159:128];
          // one block's deposit window: BLK_BYTES of input lanes
          // times max_deposits slots each
          dep_stride <= ADDR_W'({32'b0, hdr_q[159:128]} << BLK_SH);
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
          rd_sel  <= 2'd0;
          rd_beats_left <=
            ((h_nconsts << esz_sh) + (h_ninsns << 3) + 32'd31) >> 5;
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
              kmem[kons_i[3:0]] <= kbroad(256'(pw) &
                                   ~(~256'b0 << ({26'b0, esz} << 3)));
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
            // Only the low three bits of pw_have: every assignment to
            // rready above sets it from a window that will hold FEWER
            // THAN 8 bytes, so a beat is never accepted at any other
            // offset. Shifting by all seven bits asked for 512
            // landing places instead of 8.
            pw <= pw | (PWW'(m_rd_rdata) << ({4'b0, pw_have[2:0]} << 3));
            pw_have <= pw_have + 7'(BEAT_BYTES);
            m_rd_rready <= 1'b0;         // window now needs draining
          end else if (kons_left == 0 && insn_left == 0) begin
            m_rd_rready <= 1'b0;
            rd_stream_on <= 1'b0;
            blk_base <= '0;
            in_off   <= '0;
            dep_off  <= '0;
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
          // ...and, in the same window, blk_n * max_deposits, one bit
          // of the multiplier per cycle. RF_D is 16 * NBEATS and
          // NBEATS is at least LATENCY+1, so the CW steps this takes
          // always finish long before the wipe does.
          if (zaddr == 0) begin
            dep_elems  <= '0;
            dep_addend <= 32'(blk_n);
            dep_mult   <= h_maxdep[CW-1:0];
          end else begin
            if (dep_mult[0]) dep_elems <= dep_elems + dep_addend;
            dep_addend <= dep_addend << 1;
            dep_mult   <= dep_mult >> 1;
          end
          if (zaddr == 9'(RF_D - 1)) begin
            // A lane is active iff its index is below the block's
            // lane count - and blk_n IS min(blk_cap, n_q - blk_base),
            // computed one state ago. The first version asked each of
            // the 128 lanes the two questions separately, which is
            // 128 64-bit adds against n_q and 128 64-bit compares.
            active <= blk_act;
            dcnt <= '0;
            // beats holding blk_n lanes = ceil(blk_n / lanes-per-beat):
            // esz * lpb is BEAT_BYTES at every precision, so dividing
            // esz * blk_n by BEAT_BYTES is dividing blk_n by lpb.
            // 9'(blk_n), not {1'b0, blk_n}: blk_n's width follows the lane
            // block, and the concatenation is only nine bits at 256.
            nb_blk <= 5'((9'(blk_n) + 9'(lpb) - 9'd1) >> lpb_sh);
            ld_reg <= 2'd0;
            pc <= '0;
            lp_sp <= '0;
            st <= S_LD_GO;
          end
        end

        S_LD_GO: begin
          rd_addr <= (ld_reg == 0 ? a_q : ld_reg == 1 ? b_q : c_q)
                     + in_off;
          rd_sel  <= ld_reg;   // ld_reg IS the stream index
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
                active <= blk_act;
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
            al_a <= c_ka ? kmem[c_ra] : rf_rdata_a;
            al_b <= c_kb ? kmem[c_rb] : rf_rdata_b;
            al_c <= c_kc ? kmem[c_rc] : rf_rdata_c;
          end
          bt <= bt + 1;
          if (bt == 6'({1'b0, nb_blk} + 6'd1))
            st <= S_ALU_WAIT;
          // With NBEATS > LATENCY the first result retires DURING the
          // last issue cycles - beat 0 lands exactly at issue cycle
          // LATENCY - so the writeback path runs here too. Missing
          // this dropped the first beat of every 16-beat block.
          if (al_ov) begin
            rf_we <= 1'b1;
            rf_waddr <= {c_rd, wb_bt[3:0]};
            rf_wdata <= al_d;
            rf_wwe <= wb_wwe;
            flags_q <= flags_q | wb_flags_or;
            wb_bt <= wb_bt + 1;
          end
        end

        S_ALU_WAIT: begin
          if (al_ov) begin
            rf_we <= 1'b1;
            rf_waddr <= {c_rd, wb_bt[3:0]};
            rf_wdata <= al_d;
            rf_wwe <= wb_wwe;
            flags_q <= flags_q | wb_flags_or;
            wb_bt <= wb_bt + 1;
            if (wb_bt == 6'({1'b0, nb_blk} - 6'd1)) begin
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
            if (bt_dep_go[32'(p) >> wpe_sh]) begin
              db_we[p] <= 1'b1;
              db_waddr[p*DBA +: DBA] <= DBA'(32'(bt) * MAXD +
                  32'(pick_cnt_fn(bt_cnt, 3'(32'(p) >> wpe_sh))));
              db_wdata[p*32 +: 32] <= rf_rdata_a[p*32 +: 32];
            end
          // The counts advance once per LANE. Only the eight
          // positions of beat bt can move, and the value each moves
          // to was formed once above, so this is a selection over
          // constant indices and not 128 counters with a decoder in
          // front of them.
          for (int b = 0; b < NBEATS; b = b + 1)
            for (int q = 0; q < WORDS; q = q + 1)
              if (b == 32'(bt[NBSH-1:0]) && bt_dep_go[q])
                dcnt[(b*WORDS + q)*CW +: CW] <= bt_cnt_inc[q*CW +: CW];
          if (|bt_dep_ovf)
            dep_ovf_q <= 1'b1;
          bt <= bt + 1;
          if (bt == 6'({1'b0, nb_blk} - 6'd1)) begin
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
          // Eight magnitude tests, one per lane position in the beat
          // on rf_rdata_a - not one per lane in the block. The lane
          // index only ever entered this through `l & (lpb - 1)`,
          // which is the position, so 120 of the 128 tests were the
          // same eight answers reached the expensive way.
          for (int b = 0; b < NBEATS; b = b + 1)
            for (int q = 0; q < WORDS; q = q + 1)
              if (b == 32'(bt[NBSH-1:0]) && 32'(q) < 32'(lpb) &&
                  bt_act[q])
                active[b*WORDS + q] <= sa_nz[q];
          bt <= bt + 1;
          if (bt == 6'({1'b0, nb_blk} - 6'd1)) begin
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
          wr_addr <= d_q + dep_off;
          wr_beats_left <= ((dep_elems << esz_sh)
                            + 32'(BEAT_BYTES) - 32'd1) >> 5;
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
          db_raddr <= DBA'((32'(lane_cursor) >> lpb_sh) * MAXD
                           + slot_cursor);
          st <= S_DRAIN_W8;
        end
        S_DRAIN_W8: st <= S_DRAIN_PACK;

        S_DRAIN_PACK: begin
          // An element lands on an ELEMENT boundary, never an
          // arbitrary byte one: as_fill starts at zero and advances by
          // esz, so a beat is a row of lpb slots and this fills slot
          // as_fill >> esz_sh - whole 32-bit words, because every
          // format's element is a whole number of words. Expressed as
          // a byte loop over a variable base it was a 256-bit
          // variable byte shifter: 32 output bytes each selected from
          // 32 sources, for a value that only ever lands on one of at
          // most eight slots.
          for (int w = 0; w < WORDS; w = w + 1)
            if ((32'(w) >> wpe_sh) == (32'(as_fill) >> esz_sh)) begin
              as_data[w*32 +: 32] <=
                drain_elem[(32'(w) & ((32'd1 << wpe_sh) - 32'd1))
                           * 32 +: 32];
              as_strb[w*4 +: 4] <= 4'hf;
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
            wr_addr <= cnt_q + (blk_base << 2);
            wr_beats_left <= ((32'(blk_n) << 2)
                              + 32'(BEAT_BYTES) - 32'd1) >> 5;
            st <= S_CNT_PACK;
          end
        end

        S_CNT_PACK: begin
          // A count is one word and as_fill advances by four, so the
          // same word-slot argument as S_DRAIN_PACK applies, with the
          // slot fixed at four bytes.
          for (int w = 0; w < WORDS; w = w + 1)
            if (32'(w) == (32'(as_fill) >> 2)) begin
              as_data[w*32 +: 32] <= 32'(cur_cnt);
              as_strb[w*4 +: 4] <= 4'hf;
            end
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
          in_off   <= in_off  + ADDR_W'(BLK_BYTES);
          dep_off  <= dep_off + dep_stride;
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
