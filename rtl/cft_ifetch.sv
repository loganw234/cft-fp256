// Copyright 2026 Logan W.
// SPDX-License-Identifier: Apache-2.0
//
// cft_ifetch: the sequencer's instruction fetch (revision 8, R8S).
// docs/studies/R8S-streaming.md is the design: sections 2 and 3 are
// what this module builds, and its section 13 records the unit as
// built, with every place this file departs from or settles what the
// study left open. formal/ifetch.sby proves it and tb/test_ifetch.py
// holds it to SeqRam at read latencies 0, 125 and 256.
//
// A program longer than the tile's store runs from card memory. The
// unit sits between cft_seq's consumer (the fetch states and the issue
// pipe's admission) and the A master, and has four parts:
//
//   1. THE STORE. STORE_D words of 64 bits (4,096 at the U50, the
//      build's SEQ_IMEM_D), holding one contiguous range of the
//      program, [base, send), at index address mod STORE_D. The image
//      parse fills [0, min(n_insns, STORE_D)) at run start, as it
//      fills imem today. No cascade: the store is the instruction
//      memory's 4K x 64 shape, 8 RAMB36 side by side (S8, section 5).
//   2. THE STREAM. A cft_fifo of 2^FIFO_LOG2 words (512), filled in
//      program order from the position `spos` by this module's own
//      read engine: bursts of BURST beats (8, 32 instructions), at
//      most LIVE_MAX of the current position's bursts in flight and
//      OUT_MAX counting bursts a redirect abandoned, one ID and in
//      order, never across 4 KB, never past n_insns, and a burst only
//      when the FIFO has room for it beside every live burst in flight.
//   3. THE REALIGNER. The instruction section starts at byte 32, or at
//      32 + n_consts x esz, so it is 4-byte aligned and not always
//      8-byte aligned. A beat is taken into a window of the beat and
//      the previous beat's last 4-byte granule (288 bits at the U50),
//      and one instruction a cycle is selected out of it at a granule
//      offset fixed for the run.
//   4. THE RULES, decided from what the consumer asks for:
//      - an address inside [base, send) is read from the store; any
//        other is the stream's head;
//      - the stream stands at `send` while the consumer is inside the
//        range and at the consumer's own address while it is outside;
//        a presented address that finds it anywhere else is a
//        REDIRECT: the FIFO is flushed, what is in flight is dropped,
//        and the engine refetches from the right place;
//      - a REPEAT entering a body outside the range retargets the
//        store to it (base = send = the body's first address); every
//        word then taken from the stream at `send` is written into the
//        store, until it holds STORE_D. The parse's own writes are the
//        same rule from base 0;
//      - at the block's end the unit stops issuing, drops what comes
//        back and reports idle;
//      - a fault ends delivery (below).
//
// A program of at most STORE_D instructions is held whole in the
// store: nothing streams and no read is issued during a block, so
// every cycle is today's.
//
// STREAM_D EQUAL TO STORE_D BUILDS NO STREAM (the plan: "A SEQ_STREAM_D
// equal to the store's depth builds no stream"): no FIFO, no engine, no
// realigner, the AXI outputs tied off, `idle` high and the fault bits
// low. The tile is then today's, with the store as its imem.
//
// ---------------------------------------------------------------
// The interface, for round 2 (cft_seq's hooks are round 2's; this
// module leaves cft_seq.sv untouched)
// ---------------------------------------------------------------
//
//   init        one cycle at the run's start (S_IDLE with start), before
//               the parse's first instruction. Clears the fault bits,
//               empties the store's range (base = send = 0) and stops
//               the stream. The unit is idle at every start (S_WAIT_B
//               and the abort wait for it); init is safe without that,
//               since what is outstanding is dropped, but a beat that
//               landed after init would raise its fault in the new run.
//   cfg_ibase   the byte address of instruction 0: cfg_prog + 32, plus
//               n_consts x esz unless BANK_EXT. 4-byte aligned (cfg_prog
//               is 32-byte aligned and esz is 4 to 32). Stable from the
//               parse to the run's end.
//   cfg_n       n_insns, PCW+1 bits (the header check has refused more
//               than STREAM_D). Stable as cfg_ibase is.
//   ld, ld_word the parse's instructions, in order, one strobe each:
//               the i-th strobe since init is instruction i. The store
//               keeps them while it has room (the first STORE_D); the
//               consumer still scans every one for its summaries.
//   want, addr  the address whose word the consumer wants NEXT cycle:
//               pc + 1 in S_ISSUE, pc in S_FETCH, S_FETCH2, S_SKIP_F
//               and S_SKIP_D - and LOW in a cycle that takes a word,
//               because each consuming cycle presents the consumed
//               word's own address, and asking for a stream word again
//               after its pop is a jump to it. So:
//                 want = (S_FETCH | S_FETCH2 | S_SKIP_F | S_SKIP_D |
//                         S_ISSUE) && !take
//               An address at or past n_insns asks for nothing.
//   word, ok    the word at the address wanted LAST cycle, when ok.
//               ok is low while the stream has not delivered it, never
//               high for an address at or past n_insns, and held low
//               once a fault is seen. It comes from registers through
//               two 2:1 selects - cft_fifo's own head bypass (its
//               bypass register or its RAM's read register), then the
//               store's read register or that head - so the admission's
//               path stays short.
//   take        the consumer takes `word` this cycle (only with ok):
//               S_FETCH2 and S_SKIP_D when ok, and S_ISSUE's last
//               unheld step when it continues with the word. S_FETCH2
//               and S_SKIP_D wait while ok is low; the continuation
//               falls to S_FETCH as a one-step instruction's does.
//               ok also stands for `32'(pc) + 32'd1 < h_ninsns`, which
//               may come off the admission path.
//   cap, cap_pc one cycle when a REPEAT enters its body (not when it
//               skips), with the body's first address, pc + 1. Never in
//               a cycle with want or take (S_DECODE has neither).
//   quiesce     the block has ended (S_DRAIN_SETUP; repeating it every
//               cycle of that state is harmless). The stream stops: no
//               burst is issued until the next block's first want.
//   idle        no burst is outstanding or pending: the port can carry
//               the next block's setup reads. S_WAIT_B waits for it
//               beside the write responses, and the abort waits for it
//               before done. RREADY is never high while idle, so the
//               unit takes no beat it did not ask for.
//   fault_rd    a fetch beat came back non-OKAY: STATUS[0].
//   fault_len   a fetch burst of the wrong length - RLAST early, or
//               missing on the beat ARLEN named: STATUS[2].
//               Both sticky until init. Either ends delivery: ok low
//               from the next cycle, no burst issued, everything in
//               flight drained to its RLAST and dropped, then idle. The
//               sequencer's abort (round 2) takes their OR to end the
//               run, as the plan's abort rule says; this module invents
//               no mechanism of its own.
//   m_rd_*      cft_seq's read port, exactly (ARLEN AXI-encoded, beats
//               minus one), without m_rd_sel: the fetch reads master A
//               only, so the select is 0 while the fetch owns the port.
//               The port is the fetch's from a block's first want until
//               `idle` after it ends; the main read engine issues
//               nothing in that span, so R beats belong to the fetch
//               exactly while it is not idle - PROVIDED the main read
//               engine is drained when the span opens. A setup load
//               stops at its last expected beat, so a burst the memory
//               made long would still have beats on the R channel, and
//               the fetch would take them as its own. Round 2 owes
//               that obligation: no fetch AR until every main-engine
//               burst has seen its RLAST (or a long one is refused and
//               drained to it, as the engines' length rule does).
//
// The redirect, for probe S: `redir` is combinational from `addr`
// through the range compare (AW bits, 25 at the U50), the stand
// compare against spos or spos + 1, and into the FIFO's synchronous
// clear and the stream's next state - where S8's section 5 expected
// the logic registered. If probe S finds it on the critical path,
// registering it is a design change, not a retiming: the answer below
// takes the FIFO's head with no address compare because the flush
// lands in the request's own edge, so a redirect a cycle late would
// need `ok` held low for the cycle between.
//
// What the unit guarantees the port: an AR only between a want and the
// next quiesce, init or fault, 32-byte aligned, of at most BURST beats,
// inside one 4 KB page, and inside the instruction section - from the
// beat holding instruction 0's first byte to the beat holding
// instruction n_insns-1's last.
//
// Parameters a build sets: STORE_D (SEQ_IMEM_D) and STREAM_D
// (SEQ_STREAM_D). The rest are the study's figures; GW is narrowed
// only by the formal proof, which runs this module with two-bit
// granules - the byte geometry (a 4-byte granule, an 8-byte
// instruction, a 32-byte beat) is fixed by the image format and does
// not change with GW, and the unit never reads an instruction's bits.

`timescale 1ns/1ps

module cft_ifetch #(
    parameter int BEAT_BITS = 256,      // the read port's data width
    parameter int GW        = 32,       // a 4-byte granule's bits
    parameter int ADDR_W    = 64,
    parameter int STORE_D   = 4096,     // the store (SEQ_IMEM_D)
    parameter int STREAM_D  = 16777216, // the capacity (SEQ_STREAM_D)
    parameter int FIFO_LOG2 = 9,        // the stream's FIFO, 512 words
    parameter int BURST     = 8,        // beats a burst
    parameter int LIVE_MAX  = 4,        // the position's bursts in flight
    parameter int OUT_MAX   = 8         // ...and with abandoned ones
)(
    input  logic                      clk,
    input  logic                      rst_n,

    // the run, and the parse
    input  logic                      init,
    input  logic [ADDR_W-1:0]         cfg_ibase,
    input  logic [$clog2(STREAM_D):0] cfg_n,
    input  logic                      ld,
    input  logic [2*GW-1:0]           ld_word,

    // the consumer
    input  logic                      want,
    input  logic [$clog2(STREAM_D):0] addr,
    output logic [2*GW-1:0]           word,
    output logic                      ok,
    input  logic                      take,
    input  logic                      cap,
    input  logic [$clog2(STREAM_D):0] cap_pc,
    input  logic                      quiesce,
    output logic                      idle,
    output logic                      fault_rd,
    output logic                      fault_len,

    // AXI4 read master, the A master (cft_seq's m_rd_* minus the select)
    output logic [ADDR_W-1:0]         m_rd_araddr,
    output logic [7:0]                m_rd_arlen,
    output logic                      m_rd_arvalid,
    input  logic                      m_rd_arready,
    input  logic [BEAT_BITS-1:0]      m_rd_rdata,
    input  logic                      m_rd_rlast,
    input  logic [1:0]                m_rd_rresp,
    input  logic                      m_rd_rvalid,
    output logic                      m_rd_rready
);

  // pc's width: PCW is log2 of the capacity, and a pc-like value takes
  // one bit more, because pc must be able to equal n_insns (the
  // implicit halt) and n_insns may equal the capacity (S8, "Widths").
  localparam int PCW    = $clog2(STREAM_D);
  localparam int AW     = PCW + 1;
  localparam int IW     = 2 * GW;             // an instruction, two granules
  localparam int GPB    = BEAT_BITS / GW;     // granules a beat: 8
  localparam int WPB    = GPB / 2;            // instructions a beat: 4
  localparam int GSH    = $clog2(GPB);        // 3
  localparam int BSH    = GSH + 2;            // log2 of a beat's bytes: 5
  localparam int SW     = $clog2(STORE_D);    // the store's index: 12
  localparam int FDEPTH = 1 << FIFO_LOG2;
  localparam int OW     = $clog2(OUT_MAX + 1);          // 0..OUT_MAX
  localparam int LW     = $clog2(BURST + 1);            // a burst's beats
  localparam int JW     = $clog2(WPB + 1);              // 0..WPB
  localparam int VW     = $clog2(LIVE_MAX * BURST + 1); // live beats owed
  localparam bit STREAM = (STREAM_D > STORE_D);

  // ---- what the parameters must be ----------------------------------
  // Each is a property something below relies on, and a build that
  // broke one would elaborate into a unit that computes the wrong
  // addresses rather than refusing. The same pair of guards cft_seq
  // keeps: a generate-time $error, and an initial $fatal for the
  // simulators that only report that form.
  generate
    if (GPB < 2 || (1 << GSH) != GPB || GPB * GW != BEAT_BITS) begin : g_beat
      $error("cft_ifetch: BEAT_BITS must be a power-of-two number of granules, at least two (an instruction is two)");
    end
    if (STORE_D < 2 || (1 << SW) != STORE_D) begin : g_store
      $error("cft_ifetch: STORE_D must be a power of two, at least 2 - the store is indexed by the address's low bits");
    end
    if ((1 << PCW) != STREAM_D || STREAM_D < STORE_D || STREAM_D > (1 << 30)) begin : g_cap
      $error("cft_ifetch: STREAM_D must be a power of two from STORE_D to 2^30 (an int parameter stops there; CAPS2[20:16] publishes its log2)");
    end
    if (BURST < 1 || BURST > 256 || BURST * (1 << BSH) > 4096) begin : g_burst
      $error("cft_ifetch: BURST must be 1..256 beats and fit a 4 KB page");
    end
    if (LIVE_MAX < 1 || OUT_MAX < LIVE_MAX) begin : g_depth
      $error("cft_ifetch: need 1 <= LIVE_MAX <= OUT_MAX");
    end
    if (FDEPTH < WPB * BURST) begin : g_fifo
      $error("cft_ifetch: the FIFO must hold a whole burst's instructions, or no burst could ever be reserved");
    end
  endgenerate

  initial begin
    if (GPB < 2 || (1 << GSH) != GPB || GPB * GW != BEAT_BITS ||
        STORE_D < 2 || (1 << SW) != STORE_D ||
        (1 << PCW) != STREAM_D || STREAM_D < STORE_D || STREAM_D > (1 << 30) ||
        BURST < 1 || BURST > 256 || BURST * (1 << BSH) > 4096 ||
        LIVE_MAX < 1 || OUT_MAX < LIVE_MAX || FDEPTH < WPB * BURST) begin
      $display("FATAL: cft_ifetch BEAT_BITS=%0d GW=%0d STORE_D=%0d STREAM_D=%0d BURST=%0d LIVE_MAX=%0d OUT_MAX=%0d FIFO_LOG2=%0d: see the generate guards",
               BEAT_BITS, GW, STORE_D, STREAM_D, BURST, LIVE_MAX, OUT_MAX, FIFO_LOG2);
      $fatal(1);
    end
  end

  // ---- the stream's state, declared here because the store reads it --
  // The no-stream build ties all of these to zero (g_store_only).
  logic               s_on;      // the stream has a position
  logic [AW-1:0]      spos;      // ...the address of its head word
  logic [IW-1:0]      fq_data;   // the FIFO's head, valid while fq_any
  logic [FIFO_LOG2:0] fq_cnt;
  logic               fq_any;

  // ---- the store ------------------------------------------------------
  //
  // One write port (the parse's writes, and the capture's) and one
  // read port, registered, whose address is the consumer's own: the
  // store reads `addr` every cycle it is wanted, and whether the word
  // it reads is the answer is decided beside it (rq_hit), from the
  // range compare registered in the same cycle. The read and the
  // capture never meet at one index in a wanted cycle: the capture
  // writes at send, and every address inside the range [base, send)
  // has another index, since send - base < STORE_D while it writes.
  (* ram_style = "block" *)
  logic [IW-1:0] smem [0:STORE_D-1];
  logic [IW-1:0] st_q;
  logic          st_wr;
  logic [IW-1:0] st_wd;

  logic [AW-1:0] base, send;     // the store holds [base, send)
  logic [SW:0]   cnt;            // send - base, 0..STORE_D
  logic          st_room;
  assign st_room = (cnt < (SW + 1)'(STORE_D));

  always_ff @(posedge clk) begin
    if (st_wr) smem[send[SW-1:0]] <= st_wd;
    if (want)  st_q <= smem[addr[SW-1:0]];
  end

  // ---- the request: the address wanted this cycle --------------------
  logic          a_ok, a_in, hit_n, sreq_n;
  logic [AW-1:0] tgt;            // where the stream must stand for it
  assign a_ok   = want && (addr < cfg_n);
  assign a_in   = (addr >= base) && (addr < send);
  assign hit_n  = a_ok && a_in;
  assign sreq_n = a_ok && !a_in;
  assign tgt    = a_in ? send : addr;

  // ---- the answer, a cycle later -------------------------------------
  //
  // From registers only: the hit bit the compare above registered, the
  // store's read register, and the FIFO's head and count. A stream
  // request's word is the FIFO's head whenever the FIFO is not empty,
  // with no address compare: the request either found the stream
  // standing at its address (and the head IS that word) or redirected
  // it, which flushed the FIFO in the same edge.
  logic rq_hit, rq_s, fault, pop;
  always_ff @(posedge clk) begin
    if (!rst_n) begin
      rq_hit <= 1'b0;
      rq_s   <= 1'b0;
    end else begin
      rq_hit <= hit_n && !init;
      rq_s   <= sreq_n && !init && STREAM;
    end
  end
  assign fault = fault_rd || fault_len;
  assign word  = rq_hit ? st_q : fq_data;
  assign ok    = !fault && (rq_hit || (rq_s && fq_any));
  // A stream word taken leaves the FIFO.
  assign pop   = take && ok && !rq_hit;

  // ---- the range: the parse, the capture and the retarget ------------
  //
  // One rule writes the store: the word for address `send` goes in at
  // send while there is room, and send moves on. The parse hands
  // instructions 0, 1, 2 ... from base 0 (init), so it fills [0,
  // min(n, STORE_D)); a capture is a stream word taken at send, so it
  // extends whatever range the store holds - a retargeted loop body, or
  // the program's head when the stream continues sequentially from it.
  //
  // A retarget needs the body's first address below n_insns as well as
  // outside the range. Without that, a REPEAT as an image's last word
  // (only an image that bypassed the loader has one) would empty a
  // no-stream build's store, and the next block's pc 0 would wait for a
  // stream that is not built. With it, a no-stream build never
  // retargets: every body below n_insns starts inside [0, n_insns).
  logic ld_wr, cap_wr, retgt;
  assign ld_wr  = ld && st_room;
  assign cap_wr = pop && (spos == send) && st_room;
  assign retgt  = cap && (cap_pc < cfg_n) &&
                  !((cap_pc >= base) && (cap_pc < send));
  assign st_wr  = (ld_wr || cap_wr) && !retgt && !init;
  assign st_wd  = ld_wr ? ld_word : fq_data;

  always_ff @(posedge clk) begin
    if (!rst_n || init) begin
      base <= '0;
      send <= '0;
      cnt  <= '0;
    end else if (retgt) begin
      base <= cap_pc;
      send <= cap_pc;
      cnt  <= '0;
    end else if (st_wr) begin
      send <= send + AW'(1);
      cnt  <= cnt + (SW + 1)'(1);
    end
  end

  generate
    if (STREAM) begin : g_stream

      // ---- the redirect ------------------------------------------------
      //
      // A wanted address the stream is not standing for. "Standing" is
      // judged after this cycle's pop, so a consumer that wanted the
      // next word in the cycle it took this one would not redirect;
      // the two compares run in parallel and the pop picks one, to keep
      // `take` - late, from the consumer's admission - off the compare.
      logic          stop;           // init or quiesce: the stream ends
      logic          redir;
      logic [AW-1:0] spos_p1;
      assign stop    = init || quiesce;
      assign spos_p1 = spos + AW'(1);
      assign redir   = a_ok && !fault && !stop &&
                       (!s_on || (pop ? (tgt != spos_p1) : (tgt != spos)));

      // ---- the FIFO -----------------------------------------------------
      // cft_fifo's caller contract holds by construction: a write only
      // into room the reservation below kept, a read only of a word
      // `ok` showed. A flush is its synchronous clear.
      logic          fq_clr, fq_wr, fq_rd;
      logic [IW-1:0] fq_wd;
      assign fq_clr = redir || stop;
      cft_fifo #(.WIDTH(IW), .DEPTH_LOG2(FIFO_LOG2)) u_fifo (
          .clk(clk), .rst_n(rst_n), .clear(fq_clr),
          .wr_en(fq_wr), .wr_data(fq_wd),
          .rd_en(fq_rd), .rd_data(fq_data), .count(fq_cnt));
      assign fq_any = (fq_cnt != '0);
      assign fq_rd  = pop && !fq_clr;

      // ---- outstanding bursts ------------------------------------------
      //
      // out_n counts every burst from its launch (the AR committed, as
      // the engine commits at launch, not at the handshake) to its
      // RLAST: the pending AR, the accepted ones, live or abandoned.
      // A redirect, a quiesce or an init abandons all of them at once -
      // drop_n of the oldest are dropped as they land - and new live
      // bursts queue behind them, which with one ID in order is where
      // their beats arrive. lq holds each burst's beats, the head at
      // entry 0, for the length check; bcnt counts the head's beats.
      logic [OW-1:0]         out_n, drop_n, live_n;
      logic [VW-1:0]         live_b;   // beats of live bursts not yet landed
      logic [OUT_MAX*LW-1:0] lq, lq_sh, lq_nx;
      logic [8:0]            bcnt;
      logic [LW-1:0]         exp_len;
      logic                  acc, cmpl, hd_drop, len_bad, beat_bad;
      assign exp_len = lq[LW-1:0];
      assign acc     = m_rd_rvalid && m_rd_rready;
      assign cmpl    = acc && m_rd_rlast;
      assign hd_drop = (drop_n != '0);
      // The engine's length rule, burst by burst (cft_engine_stream's
      // RLAST placement check): RLAST on any beat but the one ARLEN
      // named is short, and no RLAST on that beat is long. Either is
      // flagged on the beat that shows it. bcnt saturates rather than
      // wraps, and the compare is a bit wider than it: a burst that
      // never ends must stay long, not wrap round to look short or
      // right after an init has cleared its first flag (formal/
      // ifetch.sby found the wrapping form at step 518).
      assign len_bad  = acc && (m_rd_rlast ? (({1'b0, bcnt} + 10'd1) != 10'(exp_len))
                                           : (({1'b0, bcnt} + 10'd1) >= 10'(exp_len)));
      assign beat_bad = (m_rd_rresp != 2'b00) || len_bad;

      // ---- the realigner -----------------------------------------------
      //
      // The window is {the beat, the previous beat's last granule}:
      // granule 0 is the carry and granules 1..GPB are the beat. With
      // the section's granule offset even, instruction j of a beat is
      // window granules 2j+1 and 2j+2 and the carry is never read; with
      // it odd, instruction j is granules 2j and 2j+1, instruction 0
      // straddles from the previous beat, and the beat's last granule
      // is the next beat's carry. A stream's first beat starts at the
      // word holding its position, ra_j0 - for an odd offset at the
      // beat's last granule, at WPB: no word from that beat, only its
      // carry.
      logic [BEAT_BITS-1:0]    ra_b;
      logic [GW-1:0]           ra_c;
      logic                    ra_v, ra_first, ra_acc, ra_fin, ra_e;
      logic [JW-1:0]           ra_j, ra_j0;
      logic [AW-1:0]           ra_pos;   // the instruction ra_j holds
      logic [BEAT_BITS+GW-1:0] ra_win;
      logic [WPB*IW-1:0]       ra_cand;
      logic [IW-1:0]           ra_word;
      assign ra_win = {ra_b, ra_c};
      assign ra_e   = !cfg_ibase[2];
      for (genvar j = 0; j < WPB; j = j + 1) begin : g_cand
        assign ra_cand[j*IW +: IW] = ra_e ? ra_win[(2*j+1)*GW +: IW]
                                          : ra_win[(2*j)*GW +: IW];
      end
      // A select by constant indices rather than `cand[ra_j * IW +: IW]`:
      // ra_j can hold WPB (a first beat with no word), where a part-select
      // would read past the vector and hand back X - harmless, since no
      // word is taken then, but an X the formal backend refuses and a
      // simulator propagates. (An OR chain through slices of one vector
      // was tried first; Verilator calls that circular, UNOPTFLAT.)
      always_comb begin
        ra_word = '0;
        for (int j = 0; j < WPB; j = j + 1)
          if (32'(ra_j) == j)
            ra_word = ra_cand[j*IW +: IW];
      end
      // The beat's last word: the window's last, or the program's.
      assign ra_fin  = ra_v && ((32'(ra_j) == WPB - 1) ||
                                ((ra_pos + AW'(1)) == cfg_n));
      // A live beat with nothing wrong, for the current stream.
      assign ra_acc  = acc && !hd_drop && !fault && !beat_bad && !redir && !stop;
      assign fq_wr   = ra_v && !fq_clr;
      assign fq_wd   = ra_word;

      // RREADY: always for a beat to drop (an abandoned burst's, or any
      // once a fault is seen); for a live beat only when the realigner
      // is free or frees this cycle. Never while nothing is outstanding.
      assign m_rd_rready = (out_n != '0) &&
                           (hd_drop || fault || !ra_v || ra_fin);

      // ---- where a stream starts -----------------------------------------
      //
      // Computed the cycle after a redirect (rs_go), from the registered
      // position, so the redirect's own cycle carries only the compare.
      // In granules from sec0 (the beat holding instruction 0), the
      // position's first granule is gofs + 2 x spos and the program's
      // last is gofs + 2 x n_insns - 1; a granule's beat is its index
      // shifted by GSH. A position at or past n_insns reads nothing.
      logic [ADDR_W-1:0] sec0, rd_ba;   // rd_ba: the next beat to read
      logic [GSH-1:0]    gofs;
      logic [AW+1:0]     q0, qlast, bidx0, blast;
      logic [JW-1:0]     j0;
      logic [AW:0]       rd_left;       // beats from rd_ba to the last
      logic              rs_go;
      assign sec0  = {cfg_ibase[ADDR_W-1:BSH], {BSH{1'b0}}};
      assign gofs  = cfg_ibase[GSH+1:2];
      assign q0    = (AW + 2)'(gofs) + (AW + 2)'({spos, 1'b0});
      assign qlast = (AW + 2)'(gofs) + (AW + 2)'({cfg_n, 1'b0}) - (AW + 2)'(1);
      assign bidx0 = q0 >> GSH;
      assign blast = qlast >> GSH;
      assign j0    = JW'(({1'b0, q0[GSH-1:0]} + (GSH + 1)'(1)) >> 1);

      // ---- the launch ----------------------------------------------------
      //
      // A burst is min(BURST, the beats left to the program's last, the
      // beats left in the 4 KB page), issued whole or not at all - the
      // engine's full-burst rule, for the engine's reason. Its room is
      // reserved in instructions: WPB a beat, an upper bound (a
      // stream's first beat and the program's last can hold fewer),
      // beside the FIFO's count, every live beat still owed, and a
      // realigner that is still emptying a beat. Abandoned beats are
      // never written, so they reserve nothing.
      logic [12:0] to4k;
      logic [31:0] len_a, len_c, need;
      logic        launch;
      assign to4k   = (13'd4096 - {1'b0, rd_ba[11:0]}) >> BSH;
      assign len_a  = (32'(rd_left) < 32'(BURST)) ? 32'(rd_left) : 32'(BURST);
      assign len_c  = (32'(to4k) < len_a) ? 32'(to4k) : len_a;
      assign need   = 32'(fq_cnt) + (ra_v ? 32'(WPB) : 32'd0) +
                      32'(WPB) * (32'(live_b) + len_c);
      assign launch = s_on && !rs_go && !fault && !redir && !stop &&
                      !m_rd_arvalid && (rd_left != '0) &&
                      (32'(live_n) < 32'(LIVE_MAX)) &&
                      (32'(out_n) < 32'(OUT_MAX)) &&
                      (need <= 32'(FDEPTH));

      // The length queue: shift down at an RLAST, push at a launch
      // behind whatever is left.
      logic [OW-1:0] widx;
      assign widx = out_n - (cmpl ? OW'(1) : OW'(0));
      for (genvar k = 0; k < OUT_MAX; k = k + 1) begin : g_lq
        if (k + 1 < OUT_MAX) begin : g_mid
          assign lq_sh[k*LW +: LW] = cmpl ? lq[(k+1)*LW +: LW] : lq[k*LW +: LW];
        end else begin : g_top
          assign lq_sh[k*LW +: LW] = cmpl ? LW'(0) : lq[k*LW +: LW];
        end
        assign lq_nx[k*LW +: LW] = (launch && (32'(widx) == k)) ? LW'(len_c)
                                                                 : lq_sh[k*LW +: LW];
      end

      always_ff @(posedge clk) begin
        if (!rst_n) begin
          s_on <= 1'b0;  spos <= '0;  rs_go <= 1'b0;
          out_n <= '0;  drop_n <= '0;  live_n <= '0;  live_b <= '0;
          lq <= '0;  bcnt <= '0;
          rd_ba <= '0;  rd_left <= '0;
          ra_b <= '0;  ra_c <= '0;  ra_v <= 1'b0;  ra_first <= 1'b0;
          ra_j <= '0;  ra_j0 <= '0;  ra_pos <= '0;
          fault_rd <= 1'b0;  fault_len <= 1'b0;
          m_rd_arvalid <= 1'b0;  m_rd_araddr <= '0;  m_rd_arlen <= '0;
        end else begin
          // ---- the position
          if (stop)
            s_on <= 1'b0;
          else if (redir)
            s_on <= 1'b1;
          if (redir)
            spos <= tgt;
          else if (pop)
            spos <= spos_p1;

          // ---- a stream's start, and the AR
          rs_go <= redir;
          if (rs_go) begin
            rd_ba   <= sec0 + (ADDR_W'(bidx0) << BSH);
            rd_left <= (spos < cfg_n) ? (AW + 1)'(blast - bidx0 + (AW + 2)'(1))
                                      : '0;
            ra_j0   <= j0;
          end
          // An AR stands until it is taken (AXI4 A3.2.1), whatever a
          // redirect, a quiesce or a fault does meanwhile: it is
          // already counted, and its beats are dropped when they land.
          if (launch) begin
            m_rd_arvalid <= 1'b1;
            m_rd_araddr  <= rd_ba;
            m_rd_arlen   <= 8'(len_c - 32'd1);
            rd_ba        <= rd_ba + (ADDR_W'(len_c) << BSH);
            rd_left      <= rd_left - (AW + 1)'(len_c);
          end else if (m_rd_arvalid && m_rd_arready)
            m_rd_arvalid <= 1'b0;

          // ---- the counts
          out_n <= out_n + (launch ? OW'(1) : OW'(0)) - (cmpl ? OW'(1) : OW'(0));
          if (redir || stop)
            drop_n <= out_n - (cmpl ? OW'(1) : OW'(0));
          else if (cmpl && hd_drop)
            drop_n <= drop_n - OW'(1);
          if (redir || stop) begin
            live_n <= '0;
            live_b <= '0;
          end else begin
            live_n <= live_n + (launch ? OW'(1) : OW'(0))
                             - ((cmpl && !hd_drop && live_n != '0) ? OW'(1) : OW'(0));
            live_b <= live_b + (launch ? VW'(len_c) : VW'(0))
                             - ((acc && !hd_drop && live_b != '0) ? VW'(1) : VW'(0));
          end
          lq <= lq_nx;
          if (acc)
            bcnt <= m_rd_rlast ? 9'd0 : ((bcnt == 9'h1FF) ? bcnt : bcnt + 9'd1);

          // ---- the faults, sticky to the next run
          if (init) begin
            fault_rd  <= 1'b0;
            fault_len <= 1'b0;
          end else begin
            if (acc && m_rd_rresp != 2'b00)
              fault_rd <= 1'b1;
            if (len_bad)
              fault_len <= 1'b1;
          end

          // ---- the realigner
          if (redir || stop) begin
            ra_v     <= 1'b0;
            ra_first <= 1'b1;
            ra_pos   <= tgt;
          end else begin
            if (ra_v) begin
              ra_pos <= ra_pos + AW'(1);
              ra_j   <= ra_j + JW'(1);
              if (ra_fin)
                ra_v <= 1'b0;
            end
            if (ra_acc) begin
              ra_b     <= m_rd_rdata;
              ra_c     <= ra_b[BEAT_BITS-1 -: GW];
              ra_j     <= ra_first ? ra_j0 : JW'(0);
              ra_v     <= ra_first ? (32'(ra_j0) < 32'(WPB)) : 1'b1;
              ra_first <= 1'b0;
            end
          end
        end
      end

      assign idle = (out_n == '0);

      // cfg_ibase's low two bits are zero by the image's layout (the
      // section is 4-byte aligned); no address here reads them.
      /* verilator lint_off UNUSED */
      logic unused_ib;
      assign unused_ib = &{1'b0, cfg_ibase[1:0]};
      /* verilator lint_on UNUSED */

    end else begin : g_store_only

      // No stream: the store is the whole program, and the port is
      // never used. The inputs the stream would read are sunk here so
      // that a lint which counts unused bits counts none.
      assign s_on         = 1'b0;
      assign spos         = '0;
      assign fq_data      = '0;
      assign fq_cnt       = '0;
      assign fq_any       = 1'b0;
      assign idle         = 1'b1;
      assign fault_rd     = 1'b0;
      assign fault_len    = 1'b0;
      assign m_rd_araddr  = '0;
      assign m_rd_arlen   = '0;
      assign m_rd_arvalid = 1'b0;
      assign m_rd_rready  = 1'b0;
      /* verilator lint_off UNUSED */
      logic unused_port;
      assign unused_port = &{1'b0, quiesce, cfg_ibase, m_rd_arready,
                             m_rd_rdata, m_rd_rlast, m_rd_rresp, m_rd_rvalid,
                             tgt, sreq_n, fq_cnt, s_on};
      /* verilator lint_on UNUSED */

    end
  endgenerate

endmodule
