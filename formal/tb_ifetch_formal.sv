// Copyright 2026 Logan W.
// SPDX-License-Identifier: Apache-2.0
//
// tb_ifetch_formal: the instruction fetch unit, rtl/cft_ifetch.sv,
// against every consumer and every in-order memory - the two bounded
// claims against a memory that answers at once (revision 8, R8S;
// docs/studies/R8S-streaming.md, sections 8 and 13; parcel RD1).
//
// THE WORLD. The consumer is free: want, addr, take, cap, cap_pc,
// quiesce, init and ld are the solver's, every cycle, subject only to
// the interface's own rules (cft_ifetch.sv's header) - a take only
// with ok, and the parse's loads only between a run's start and its
// first request, the k-th load being instruction k. The memory is an
// AXI slave whose timing is free: ARREADY and RVALID are the solver's
// every cycle. Beats come back in order (one ID), at the addresses
// their burst asked for. Where HONEST is clear, RLAST and RRESP are
// free as well, so a burst may come back short, long, faulted, or not
// at all; where it is set, every beat is OKAY and every burst exactly
// as long as it was asked to be.
//
// THE DATA, by one watched instruction. widx and wdata are anyconst:
// one instruction of the image, anywhere, holding any value. A beat
// carries wdata's two granules wherever the watched instruction's bytes
// fall in it, and free data in every other granule - and in every
// granule of a beat that is non-OKAY or past the length its burst
// asked for, since such a beat vouches for nothing. The parse's load
// of instruction widx is wdata too. Since widx is any instruction and
// wdata any value, "whenever ok answers an address equal to widx, the
// word is wdata" is the claim for every address and every image; a
// unit that handed over a word from the wrong place, the wrong order,
// a dropped or a doubled position, or a stale store slot would be
// caught where widx is that word.
//
// THE TASKS, each asserting its groups (a group a task does not assert is
// not elaborated, so each task's model holds only what its claims read).
// Every proof task is unbounded: k-induction proving all of the task's
// assertions together - its claims (a_*) and the helper invariants (h_*,
// d_*) that make them inductive, each of which is proven, not assumed.
// The two cover tasks are bounded searches for reachability.
//
//   prove        (free RLAST and RRESP; depth 3)
//     a_past_n       ok only for an address wanted, and below n_insns;
//     a_fault_ends   ok never high once a fault bit is;
//     a_rd_fault / a_len_fault
//                    a non-OKAY beat, or a beat that shows a burst of
//                    the wrong length, raises its bit the next cycle;
//     a_no_false_*   and no bit rises without one;
//     a_ar_*         every AR beat-aligned, at most BURST beats, inside
//                    one 4 KB page, inside the instruction section
//                    (never past n_insns), and held until taken;
//     a_outstanding  no more than OUT_MAX bursts outstanding;
//     a_idle         idle exactly when nothing is outstanding or pending;
//     a_quiet        no new AR after a quiesce or an init until a
//                    request, nor after a fault;
//     a_fifo_*       the FIFO never written full nor read empty
//                    (cft_fifo's caller contract: the reservation holds),
//                    through probes the script attaches;
//     h_*            what the unit's bookkeeping means in the memory's
//                    terms (counts, the length queue, the read engine's
//                    position, the reservation);
//     s_*            at the default sizes only, the scope facts: the
//                    three shapes of HONEST SCOPE below never occur.
//   data_prove   (HONEST; depth 3; prove's claims and helpers beside it)
//     a_word         the word ok presents is the image's word at the
//                    address wanted the cycle before;
//     a_lat          the stream hands a word over at least two cycles
//                    after the beat carrying it landed (P_LAT);
//     d_*            where the watched word is - the store's slot, the
//                    FIFO's slot, the realigner's window and carry - and
//                    the positions, alignments and burst chain that put
//                    it there, and for a_lat how long it has been there.
//   deliver_prove (HONEST, and a cooperative memory: ARREADY always, a
//                  beat whenever one is owed; depth 19; with prove's and
//                  data_prove's assertions)
//     a_delivers     a consumer that waits on one address below n_insns,
//                    doing nothing else, is answered within WAIT_MAX
//                    cycles.
//   ends_prove   (the cooperative memory with RRESP free and no burst more
//                 than a beat past its ARLEN; depth 15; with prove's)
//     a_ends         after a quiesce, an init or a fault, the unit is
//                    idle within IDLE_MAX cycles.
//   cover        the shapes the proofs lean on are reachable (14), among
//                them a stream word handed over exactly two cycles after
//                its beat landed - a_lat's bound, met.
//   wide_prove, wide_data_prove
//                prove's and data_prove's assertions at the wide sizes
//                (HONEST SCOPE), the scope facts aside;
//   wide_cover   the three shapes reached at the wide sizes, and the
//                FIFO full there.
//
// WHY A FAULTED BEAT'S WORD NEEDS NO DATA TASK OF ITS OWN. A word
// reaches `ok` at least two cycles after the beat carrying it lands on
// the bus (a_lat, in data_prove; the realigner's register, then the
// FIFO's), a bad beat raises its bit the cycle after it lands
// (a_rd_fault, a_len_fault, in prove), and ok is never high with a bit
// raised (a_fault_ends, in prove). Up to its bad beat a faulting
// memory's run is an honest memory's; the word ok shows in that beat's
// own cycle came from beats two or more cycles older, and from the next
// cycle ok is low until an init, which drops everything. So no word of
// a bad beat is ever handed over, and data_prove can hold the words
// against an honest memory. The bench holds the same against SeqRam's
// faults.
//
// HONEST SCOPE. Two configurations, one byte geometry: the U50's - a
// 4-byte granule, an 8-byte instruction, a 32-byte beat - because it is
// the image format's and does not change with GW. The unit never reads
// an instruction's bits, so the two-bit granules both configurations
// use remove data, not control.
//   The default sizes (prove, data_prove, deliver_prove, ends_prove,
// cover): a 16-instruction capacity, a 4-word store, an 8-word FIFO,
// bursts of 2 beats, 2 live and 4 in all, 13-bit addresses (so the
// section can cross a 4 KB page). The FIFO holds exactly one burst, so
// three shapes of the reservation cannot occur: a whole burst launching
// while the unit is not empty, more than BURST beats owed to live
// bursts, and the launch's `live_n < LIVE_MAX` term deciding anything.
// verifier-VRD1 found them missing (2026-10-03); g_scope asserts each
// unreachable here, proven with the claims in every default-size task
// but cover.
//   The wide sizes (wide_prove, wide_data_prove, wide_cover): the FIFO
// at 32 words, four bursts, with LIVE_MAX = 2 below the four it could
// take, and a 64-instruction capacity so that a stream can fill it.
// wide_cover reaches all three shapes and the full FIFO, and the control
// and data claims are proven there. live_b's three bits wrap at 8 as the
// U50's six wrap at 64, so the launch's LIVE_MAX term carries weight
// here as it does on the card: VRD1's v13, which removes it, passes at
// the default sizes and is refuted here from reset (formal/README.md).
//   Neither runs the bounded claims at the wide sizes, nor the U50's
// own 4,096 / 2^24 / 512 / 8 / 4 / 8, which are argued from these, as
// fifo.sby argues 256 x 512 from 8 x 8 - and the three shapes are the
// ones found missing, not a proof that nothing else is. For any shape
// neither configuration reaches, the net is tb/test_ifetch.py, which
// runs the unit at the U50's stream sizes (512 / 8 / 4 / 8, with a
// 64-word store and a 4,096-word capacity).

`timescale 1ns/1ps

module tb_ifetch_formal #(
    parameter int GW        = 2,
    parameter int BEAT_BITS = 16,
    parameter int ADDR_W    = 13,
    parameter int STORE_D   = 4,
    parameter int STREAM_D  = 16,
    parameter int FIFO_LOG2 = 3,
    parameter int BURST     = 2,
    parameter int LIVE_MAX  = 2,
    parameter int OUT_MAX   = 4,
    // The world, and which claims a task asserts. A claim group is a
    // generate block: a task that does not assert it has none of its
    // logic, so the unit's data path leaves every model but data_prove's.
    // The defaults are task `prove`'s, which is also what run.sh's
    // vacuity preflight elaborates.
    parameter bit HONEST    = 1'b0,
    parameter bit LIVE      = 1'b0,
    parameter bit P_DATA    = 1'b0,
    parameter bit P_CTRL    = 1'b1,
    parameter bit P_DELIV   = 1'b0,
    parameter bit P_ENDS    = 1'b0,
    // data_prove's latency claim (a_lat) and its helpers, inside P_DATA
    parameter bit P_LAT     = 1'b0,
    // The helper invariants (h_*, d_*) and the scope facts (s_*). On in
    // every gate task; off only to run the claims alone as a bounded check
    // from reset, which names the claim a planted defect breaks rather
    // than the helper it breaks first (the plants were run that way, the
    // round's ledger RD1.md).
    parameter bit HELPERS   = 1'b1,
    parameter int WAIT_MAX  = 18,
    parameter int IDLE_MAX  = 14
) (
    input logic                      clk,
    input logic                      rst_n,
    // the consumer
    input logic                      init,
    input logic                      ld,
    input logic                      want,
    input logic                      take,
    input logic                      cap,
    input logic                      quiesce,
    input logic [$clog2(STREAM_D):0] addr,
    input logic [$clog2(STREAM_D):0] cap_pc,
    input logic [2*GW-1:0]           ld_free,
    // the memory's free choices
    input logic                      arready_f,
    input logic                      rvalid_f,
    input logic                      rlast_f,
    input logic [1:0]                rresp_f,
    input logic [BEAT_BITS-1:0]      rdata_free
);

  localparam int PCW = $clog2(STREAM_D);
  localparam int AW  = PCW + 1;
  localparam int IW  = 2 * GW;
  localparam int GPB = BEAT_BITS / GW;          // granules a beat
  localparam int BSH = $clog2(GPB) + 2;         // log2 of a beat's bytes
  localparam int BAW = ADDR_W - BSH;            // a beat's address
  localparam int QW  = $clog2(OUT_MAX + 1);
  localparam int LW  = $clog2(BURST + 2);       // asked lengths, and one past
  localparam int HW  = 9;                       // beats sent, saturating as the unit's
  localparam int FDEPTH = 1 << FIFO_LOG2;
  // The FIFO holds exactly one burst's instructions (the default sizes):
  // then three shapes of the reservation cannot occur, and g_scope
  // asserts as much; with room for more, the cover task reaches them.
  localparam bit ONE_BURST = (FDEPTH == (GPB / 2) * BURST);

  // ---- the image: where it is, how long, and the watched word ---------
  (* anyconst *) logic [ADDR_W-1:0] ibase;
  (* anyconst *) logic [AW-1:0]     n;
  (* anyconst *) logic [AW-1:0]     widx;
  (* anyconst *) logic [IW-1:0]     wdata;

  logic [ADDR_W+1:0] sec_end, wa0, wa1;
  logic [ADDR_W-1:0] sec0, last_beat;
  assign sec_end   = (ADDR_W + 2)'(ibase) + ((ADDR_W + 2)'(n) << 3);
  assign sec0      = {ibase[ADDR_W-1:BSH], {BSH{1'b0}}};
  assign last_beat = ADDR_W'((sec_end - (ADDR_W + 2)'(1)) >> BSH) << BSH;
  assign wa0       = (ADDR_W + 2)'(ibase) + ((ADDR_W + 2)'(widx) << 3);
  assign wa1       = wa0 + (ADDR_W + 2)'(4);

  always_comb begin
    assume (ibase[1:0] == 2'b00);                // 4-byte aligned
    assume (n <= AW'(STREAM_D));
    // No wrap, with a beat to spare: the engine's next-beat pointer moves
    // a beat past the section's last, and in the formal address space
    // that must not wrap to 0 (the hardware's is 64 bits and cannot).
    assume (sec_end + (ADDR_W + 2)'(1 << BSH) <= (ADDR_W + 2)'(1 << ADDR_W));
    assume (n == '0 || widx < n);
  end

  // The trace starts in reset, and the reset is the only one: a run's
  // own restart is `init`, which the world drives freely.
  logic f_past_valid = 1'b0;
  always_ff @(posedge clk) f_past_valid <= 1'b1;
  initial assume (!rst_n);
  always_comb if (f_past_valid) assume (rst_n);
  // The same two facts as one, for a window that does not start at the
  // trace's first cycle (k-induction's): a cycle before f_past_valid is
  // a cycle in reset. Without it the window may open on a state the
  // checks never saw, run out of reset, and refute nothing real.
  always_comb assume (f_past_valid || !rst_n);

  // ---- the DUT --------------------------------------------------------
  logic [IW-1:0]        word, ld_word;
  logic                 ok, idle, fault_rd, fault_len;
  logic [ADDR_W-1:0]    araddr;
  logic [7:0]           arlen;
  logic                 arvalid, arready, rvalid, rlast, rready;
  logic [1:0]           rresp;
  logic [BEAT_BITS-1:0] rdata;

  cft_ifetch #(
      .BEAT_BITS(BEAT_BITS), .GW(GW), .ADDR_W(ADDR_W),
      .STORE_D(STORE_D), .STREAM_D(STREAM_D), .FIFO_LOG2(FIFO_LOG2),
      .BURST(BURST), .LIVE_MAX(LIVE_MAX), .OUT_MAX(OUT_MAX)
  ) dut (
      .clk(clk), .rst_n(rst_n),
      .init(init), .cfg_ibase(ibase), .cfg_n(n), .ld(ld), .ld_word(ld_word),
      .want(want), .addr(addr), .word(word), .ok(ok), .take(take),
      .cap(cap), .cap_pc(cap_pc), .quiesce(quiesce), .idle(idle),
      .fault_rd(fault_rd), .fault_len(fault_len),
      .m_rd_araddr(araddr), .m_rd_arlen(arlen), .m_rd_arvalid(arvalid),
      .m_rd_arready(arready), .m_rd_rdata(rdata), .m_rd_rlast(rlast),
      .m_rd_rresp(rresp), .m_rd_rvalid(rvalid), .m_rd_rready(rready));

  logic fault;
  assign fault = fault_rd || fault_len;

  // ---- the consumer's rules ---------------------------------------------
  // The parse: from a reset or an init to the first request of any kind,
  // and the k-th load is instruction k - wdata at widx.
  logic          parse;
  logic [AW:0]   ld_cnt;
  always_ff @(posedge clk) begin
    if (!rst_n || init) begin
      parse  <= 1'b1;
      ld_cnt <= '0;
    end else begin
      if (want || take || cap || quiesce) parse <= 1'b0;
      if (ld) ld_cnt <= ld_cnt + (AW + 1)'(1);
    end
  end
  assign ld_word = (ld_cnt == (AW + 1)'(widx)) ? wdata : ld_free;
  always_comb begin
    assume (!take || ok);
    assume (!ld || (parse && !init && ld_cnt < (AW + 1)'(n)));
  end

  // ---- the memory ---------------------------------------------------------
  // A queue of the bursts it has accepted, by start beat and asked
  // length, the head at entry 0, and the head's beats sent so far.
  logic [OUT_MAX*BAW-1:0] qa;
  logic [OUT_MAX*LW-1:0]  ql;
  logic [QW-1:0]          qn;
  logic [HW-1:0]          hb;
  logic                   ar_hs, r_hs, r_end;
  logic [BAW-1:0]         hd_a;
  logic [LW-1:0]          hd_l;
  assign hd_a    = qa[BAW-1:0];
  assign hd_l    = ql[LW-1:0];
  assign arready = LIVE ? 1'b1 : arready_f;
  assign rvalid  = (qn != '0) && (LIVE ? 1'b1 : rvalid_f);
  // Exact where HONEST; free where not, but in the cooperative world
  // never more than one beat past the asked length.
  assign rlast   = HONEST ? (32'(hb) + 1 == 32'(hd_l))
                          : (rlast_f || (LIVE && (32'(hb) >= 32'(hd_l))));
  assign rresp   = HONEST ? 2'b00 : rresp_f;
  assign ar_hs   = arvalid && arready;
  assign r_hs    = rvalid && rready;
  assign r_end   = r_hs && rlast;

  // The beat's data: wdata's granules where the watched instruction's
  // bytes are, free elsewhere, all free when the beat vouches for
  // nothing.
  logic [ADDR_W+1:0] cur_byte;
  logic              honest;
  assign cur_byte = (ADDR_W + 2)'((BAW + 1)'(hd_a) + (BAW + 1)'(hb)) << BSH;
  assign honest   = (rresp == 2'b00) && (32'(hb) < 32'(hd_l));
  for (genvar g = 0; g < GPB; g = g + 1) begin : g_gran
    logic [ADDR_W+1:0] ga;
    assign ga = cur_byte + (ADDR_W + 2)'(4 * g);
    assign rdata[g*GW +: GW] = (honest && ga == wa0) ? wdata[GW-1:0]
                             : (honest && ga == wa1) ? wdata[IW-1:GW]
                             : rdata_free[g*GW +: GW];
  end

  logic [OUT_MAX*BAW-1:0] qa_sh;
  logic [OUT_MAX*LW-1:0]  ql_sh;
  logic [QW-1:0]          q_wi;
  assign q_wi = qn - (r_end ? QW'(1) : QW'(0));
  for (genvar k = 0; k < OUT_MAX; k = k + 1) begin : g_q
    if (k + 1 < OUT_MAX) begin : g_mid
      assign qa_sh[k*BAW +: BAW] = r_end ? qa[(k+1)*BAW +: BAW] : qa[k*BAW +: BAW];
      assign ql_sh[k*LW +: LW]   = r_end ? ql[(k+1)*LW +: LW]   : ql[k*LW +: LW];
    end else begin : g_top
      assign qa_sh[k*BAW +: BAW] = r_end ? BAW'(0) : qa[k*BAW +: BAW];
      assign ql_sh[k*LW +: LW]   = r_end ? LW'(0)  : ql[k*LW +: LW];
    end
  end
  always_ff @(posedge clk) begin
    if (!rst_n) begin
      qn <= '0;
      hb <= '0;
      qa <= '0;
      ql <= '0;
    end else begin
      qa <= qa_sh;
      ql <= ql_sh;
      if (ar_hs && 32'(q_wi) < OUT_MAX) begin
        qa[32'(q_wi)*BAW +: BAW] <= araddr[ADDR_W-1:BSH];
        ql[32'(q_wi)*LW +: LW]   <= LW'(32'(arlen) + 1);
      end
      qn <= qn + (ar_hs ? QW'(1) : QW'(0)) - (r_end ? QW'(1) : QW'(0));
      if (r_hs)
        hb <= rlast ? HW'(0) : ((hb == {HW{1'b1}}) ? hb : hb + HW'(1));
    end
  end

  // The beat carrying the watched word's last granule, wb2 (a word that
  // straddles two beats is formed when the second is in the window), and
  // w_age: the cycles since a beat at wb2 last landed on the bus, live or
  // abandoned - 1, 2, or 3 meaning three or more, or none yet. data_prove's
  // a_lat reads them, and the cover task's c_lat_two.
  logic [ADDR_W:0] wb2;
  logic            w_land;
  logic [1:0]      w_age;
  assign wb2    = (ADDR_W + 1)'(wa1 >> BSH);
  assign w_land = r_hs && ((ADDR_W + 1)'(cur_byte >> BSH) == wb2);
  always_ff @(posedge clk) begin
    if (!rst_n)
      w_age <= 2'd3;
    else
      w_age <= w_land ? 2'd1 : ((w_age == 2'd3) ? 2'd3 : w_age + 2'd1);
  end

  // ---- what the harness knows of each beat and each request ---------------
  logic bad_rd, bad_len;
  assign bad_rd  = r_hs && (rresp != 2'b00);
  assign bad_len = r_hs && (rlast ? (32'(hb) + 1 != 32'(hd_l))
                                  : (32'(hb) + 1 >= 32'(hd_l)));
  logic          seen_rd, seen_len, quiet, p_want, p_fault, p_init;
  logic          p_bad_rd, p_bad_len, p_arwait;
  logic [AW-1:0] p_addr;
  logic [ADDR_W-1:0] p_araddr;
  logic [7:0]    p_arlen;
  always_ff @(posedge clk) begin
    if (!rst_n) begin
      seen_rd <= 1'b0;  seen_len <= 1'b0;  quiet <= 1'b1;
      p_want <= 1'b0;  p_fault <= 1'b0;  p_init <= 1'b0;
      p_bad_rd <= 1'b0;  p_bad_len <= 1'b0;  p_arwait <= 1'b0;
      p_addr <= '0;  p_araddr <= '0;  p_arlen <= '0;
    end else begin
      if (init) begin
        seen_rd  <= 1'b0;
        seen_len <= 1'b0;
      end else begin
        if (bad_rd)  seen_rd  <= 1'b1;
        if (bad_len) seen_len <= 1'b1;
      end
      if (init || quiesce)
        quiet <= 1'b1;
      else if (want && addr < n)
        quiet <= 1'b0;
      p_want    <= want;
      p_addr    <= addr;
      p_fault   <= fault;
      p_init    <= init;
      p_bad_rd  <= bad_rd;
      p_bad_len <= bad_len;
      p_arwait  <= arvalid && !arready;
      p_araddr  <= araddr;
      p_arlen   <= arlen;
    end
  end

  // ---- the FIFO's contract, through probes ----------------------------
  // Attached by ifetch.sby's `connect -nounset -set` on the flattened
  // design (formal/README.md: the frontend has no other way to a
  // submodule's internals). A connect whose internal name does not
  // resolve stops the build: yosys errors, and sby ends the task in
  // ERROR (rc 16), which run.sh reports as a failure. A probe with no
  // connect at all is left undriven, which sby's model build turns into
  // a free value, so its assertions are refuted rather than passed.
  (* keep *) logic                 probe_fq_wr;
  (* keep *) logic                 probe_fq_rd;
  (* keep *) logic [FIFO_LOG2:0]   probe_fq_cnt;

  // ...and the bookkeeping the control claims rest on, for the helper
  // invariants below. Widths are the unit's own (cft_ifetch.sv's
  // localparams), so `connect` meets equal widths.
  localparam int U_OW = $clog2(OUT_MAX + 1);
  localparam int U_VW = $clog2(LIVE_MAX * BURST + 1);
  localparam int U_LW = $clog2(BURST + 1);
  localparam int U_JW = $clog2(GPB / 2 + 1);
  localparam int WPB  = GPB / 2;
  (* keep *) logic [U_OW-1:0]         probe_out_n;
  (* keep *) logic [U_OW-1:0]         probe_drop_n;
  (* keep *) logic [U_OW-1:0]         probe_live_n;
  (* keep *) logic [U_VW-1:0]         probe_live_b;
  (* keep *) logic [OUT_MAX*U_LW-1:0] probe_lq;
  (* keep *) logic [8:0]              probe_bcnt;
  (* keep *) logic [ADDR_W-1:0]       probe_rd_ba;
  (* keep *) logic [AW:0]             probe_rd_left;
  (* keep *) logic                    probe_ra_v;
  (* keep *) logic [U_JW-1:0]         probe_ra_j;
  (* keep *) logic                    probe_s_on;
  // ...and the launch's own terms, for the scope facts and their covers
  (* keep *) logic                    probe_launch;
  (* keep *) logic                    probe_redir;
  (* keep *) logic [31:0]             probe_need;
  (* keep *) logic [31:0]             probe_len_c;

  // ...and, for data_prove, where the words are: the store's and the
  // FIFO's memories (made registers by the script's memory_map; the
  // FIFO's FDEPTH words as one vector, slot k at [k*IW +: IW]), the
  // FIFO's pointers, read register and bypass, the realigner's window
  // and carry, and the unit's positions. These are written for a 4-word
  // store and eight granules a beat, at any FIFO depth; g_p_data refuses
  // any other store or beat.
  (* keep *) logic [AW-1:0]             probe_spos;
  (* keep *) logic [AW-1:0]             probe_base;
  (* keep *) logic [AW-1:0]             probe_send;
  (* keep *) logic [$clog2(STORE_D):0]  probe_cnt;
  (* keep *) logic [AW-1:0]             probe_ra_pos;
  (* keep *) logic                      probe_ra_first;
  (* keep *) logic [U_JW-1:0]           probe_ra_j0;
  (* keep *) logic                      probe_rs_go;
  (* keep *) logic                      probe_rq_s;
  (* keep *) logic [BEAT_BITS-1:0]      probe_ra_b;
  (* keep *) logic [GW-1:0]             probe_ra_c;
  (* keep *) logic [IW-1:0]             probe_smem0, probe_smem1, probe_smem2, probe_smem3;
  (* keep *) logic [FDEPTH*IW-1:0]      probe_fmem;
  (* keep *) logic [FIFO_LOG2-1:0]      probe_rp, probe_wp;
  (* keep *) logic [IW-1:0]             probe_ram_q, probe_byp_d;
  (* keep *) logic                      probe_byp_v1, probe_byp_v2;
  // ...and the FIFO's late pop (the S1 follow-up, 2026-10-05): a stream
  // word taken leaves the FIFO a cycle later, so while pop_q stands the
  // FIFO's count is one above the stream's and its head is the word
  // taken - the logical stream starts one slot on.
  (* keep *) logic                      probe_pop_q;
  logic [FIFO_LOG2:0]                   lcnt;     // the stream's words in it
  assign lcnt = probe_fq_cnt - (FIFO_LOG2 + 1)'(probe_pop_q);

  // ---- the properties ----------------------------------------------------
  logic new_ar;
  logic [ADDR_W:0] ar_last;
  assign new_ar  = arvalid && !p_arwait;
  assign ar_last = (ADDR_W + 1)'(araddr) + ((ADDR_W + 1)'(arlen) << BSH);

  // The three shapes of the reservation a one-burst FIFO cannot reach,
  // and the U50's 512-word FIFO does (verifier-VRD1, 2026-10-03): a whole
  // burst launching while the unit is not empty (a word in the FIFO, a
  // beat in the window or a live beat owed); more than BURST beats owed
  // to live bursts; and the launch's `live_n < LIVE_MAX` term deciding -
  // every other term of the launch true, and live_n at LIVE_MAX. At the
  // default sizes g_scope asserts each unreachable; at sizes with room
  // for more than one burst the cover task reaches each.
  logic sh_full_busy, sh_owed, sh_live_gate;
  assign sh_full_busy = probe_launch && probe_len_c == 32'(BURST) &&
                        (probe_fq_cnt != '0 || probe_ra_v || probe_live_b != '0);
  assign sh_owed      = 32'(probe_live_b) > BURST;
  assign sh_live_gate = probe_s_on && !probe_rs_go && !fault && !probe_redir &&
                        !init && !quiesce && !arvalid && probe_rd_left != '0 &&
                        32'(probe_out_n) < OUT_MAX && probe_need <= 32'(FDEPTH) &&
                        32'(probe_live_n) >= LIVE_MAX;

  if (P_DATA) begin : g_p_data
    if (STORE_D != 4 || GPB != 8) begin : g_sizes
      $error("tb_ifetch_formal: data_prove's probes are written for a 4-word store and 8 granules a beat");
    end
    // ---- the data helpers ------------------------------------------------
    // Where the watched word can be, and that it is wdata wherever it is:
    // in the store's slot for its address while the range holds it, in
    // the FIFO's slot for its address while the FIFO does, in the
    // realigner's window and in its carry. And the bookkeeping that
    // puts it there: the FIFO head's provenance, ra_pos = spos + the
    // FIFO's count, and the chain of live bursts back to the beat the
    // realigner expects next. Granules are counted from sec0, the beat
    // holding instruction 0 (instruction k is granules gofs + 2k and
    // gofs + 2k + 1).
    localparam int GX = AW + 4;
    localparam int XW = ADDR_W + 1;
    logic          odd;
    logic [2:0]    gofs;
    logic [GX-1:0] gw0, gw1, gb, e_rel;
    logic [XW-1:0] e_abs;
    assign odd  = ibase[2];
    assign gofs = ibase[4:2];
    assign gw0  = GX'(gofs) + (GX'(widx) << 1);
    assign gw1  = gw0 + GX'(1);
    // the realigner's beat: the granule its granule 0 is
    assign gb   = GX'(gofs) + (GX'(probe_ra_pos) << 1) + GX'(odd) - (GX'(probe_ra_j) << 1);
    // the beat the realigner takes next, from sec0's beat and absolute
    assign e_rel = probe_ra_v     ? ((gb >> 3) + GX'(1))
                 : probe_ra_first ? ((GX'(gofs) + (GX'(probe_ra_pos) << 1)) >> 3)
                 : ((GX'(gofs) + (GX'(probe_ra_pos) << 1) + GX'(odd)) >> 3);
    assign e_abs = XW'(sec0 >> BSH) + XW'(e_rel);

    // the store's slot and the FIFO's slot for widx, and the FIFO's head
    logic [IW-1:0]        smem_w, fmem_w, fmem_rp, fhead;
    logic [AW-1:0]        wrel;
    logic [FIFO_LOG2-1:0] fslot;
    assign smem_w  = (widx[1:0] == 2'd0) ? probe_smem0 : (widx[1:0] == 2'd1) ? probe_smem1
                   : (widx[1:0] == 2'd2) ? probe_smem2 : probe_smem3;
    assign wrel    = widx - probe_spos;
    // the logical head is a slot on from rp while a pop is pending
    assign fslot   = probe_rp + FIFO_LOG2'(probe_pop_q) + wrel[FIFO_LOG2-1:0];
    // slot selects by constant indices, as the unit's own ra_word is
    always_comb begin
      fmem_w  = '0;
      fmem_rp = '0;
      for (int k = 0; k < FDEPTH; k = k + 1) begin
        if (32'(fslot) == k)    fmem_w  = probe_fmem[k*IW +: IW];
        if (32'(probe_rp) == k) fmem_rp = probe_fmem[k*IW +: IW];
      end
    end
    assign fhead   = (probe_byp_v1 || probe_byp_v2) ? probe_byp_d : probe_ram_q;
    // Wrapping sums as wires of their own width, never as a narrowing
    // cast inside a comparison: yosys sizes `c == a + 3'(b)` without
    // wrapping where the simulators wrap (measured 2026-10-03, with c, a
    // three bits and b four: c = 0, a = 5, b = 3 gives 0 in yosys 0.68 and
    // 1 in Icarus 12 and Verilator 5.020).
    logic [FIFO_LOG2-1:0] wp_exp;
    logic [2:0]           q0m, nxm;
    assign wp_exp = probe_rp + probe_fq_cnt[FIFO_LOG2-1:0];
    assign q0m    = gofs + {probe_ra_pos[1:0], 1'b0};
    assign nxm    = gofs + {probe_ra_pos[1:0], 1'b0} + {2'b0, odd};

    // the realigner's window, granule by granule
    logic [GPB-1:0] rb_ok;
    for (genvar p = 0; p < GPB; p = p + 1) begin : g_rb
      assign rb_ok[p] = (gb + GX'(p) != gw0 || probe_ra_b[p*GW +: GW] == wdata[GW-1:0]) &&
                        (gb + GX'(p) != gw1 || probe_ra_b[p*GW +: GW] == wdata[IW-1:GW]);
    end

    // each outstanding burst's start beat, in the unit's numbering: the
    // memory's queue, then the pending AR behind it
    logic [OUT_MAX*XW-1:0] st;
    logic [OUT_MAX-1:0]    link_ok;
    logic [XW-1:0]         st_d, st_last, len_last;
    // the selects at drop_n and at out_n - 1, as OR chains (no part-select
    // can read off the end and hand the backend an undefined bit)
    logic [(OUT_MAX+1)*XW-1:0] sd_or, sl_or, ll_or;
    assign sd_or[XW-1:0] = '0;
    assign sl_or[XW-1:0] = '0;
    assign ll_or[XW-1:0] = '0;
    for (genvar k = 0; k < OUT_MAX; k = k + 1) begin : g_st
      assign st[k*XW +: XW] = (32'(k) < 32'(qn)) ? XW'(qa[k*BAW +: BAW])
                                                 : XW'(araddr[ADDR_W-1:BSH]);
      if (k + 1 < OUT_MAX) begin : g_l
        assign link_ok[k] = !(32'(k) >= 32'(probe_drop_n) && 32'(k) + 1 < 32'(probe_out_n)) ||
                            (st[(k+1)*XW +: XW] == st[k*XW +: XW] +
                                                   XW'(probe_lq[k*U_LW +: U_LW]));
      end else begin : g_l
        assign link_ok[k] = 1'b1;
      end
      assign sd_or[(k+1)*XW +: XW] = sd_or[k*XW +: XW] |
                                     ((32'(probe_drop_n) == k) ? st[k*XW +: XW] : XW'(0));
      assign sl_or[(k+1)*XW +: XW] = sl_or[k*XW +: XW] |
                                     ((32'(probe_out_n) == k + 1) ? st[k*XW +: XW] : XW'(0));
      assign ll_or[(k+1)*XW +: XW] = ll_or[k*XW +: XW] |
                                     ((32'(probe_out_n) == k + 1)
                                      ? XW'(probe_lq[k*U_LW +: U_LW]) : XW'(0));
    end
    assign st_d     = sd_or[OUT_MAX*XW +: XW];
    assign st_last  = sl_or[OUT_MAX*XW +: XW];
    assign len_last = ll_or[OUT_MAX*XW +: XW];

    always_comb begin
      if (f_past_valid) begin
        // the claim
        a_word:  assert (!(ok && p_addr == widx) || word == wdata);
      end
      if (f_past_valid && HELPERS) begin
        // where the watched word is
        d_store: assert (!(widx >= probe_base && widx < probe_send) || smem_w == wdata);
        d_fifo:  assert (!(probe_s_on && widx >= probe_spos &&
                           32'(wrel) < 32'(lcnt)) || fmem_w == wdata);
        d_head:  assert (probe_fq_cnt == '0 || fhead == fmem_rp);
        d_win:   assert (!probe_ra_v || &rb_ok);
        // the window starts on a beat, and between beats the next
        // instruction starts the next beat (or straddles into it from
        // granule 7) unless the program has ended
        d_align: assert ((!probe_ra_v || gb[2:0] == 3'd0) &&
                         (!(probe_s_on && !probe_ra_v && !probe_ra_first) ||
                          probe_ra_pos == n || nxm == 3'd0));
        d_carry: assert (!(probe_ra_v && odd && probe_ra_j == '0 && probe_ra_pos == widx) ||
                         probe_ra_c == wdata[GW-1:0]);
        d_carry2: assert (!(probe_s_on && !probe_ra_v && !probe_ra_first && odd &&
                            probe_ra_pos == widx) ||
                          probe_ra_b[(GPB-1)*GW +: GW] == wdata[GW-1:0]);
        // the honest memory sends no bad beat: its beat count stays below
        // its burst's length, so no fault can stop a redirect here
        d_honest: assert (!HONEST || (!seen_rd && !seen_len &&
                          (qn == '0 || (hd_l != '0 && 32'(hb) < 32'(hd_l)))));
        // what puts it there
        d_off:   assert (probe_s_on || (probe_fq_cnt == '0 && !probe_ra_v && probe_live_n == '0));
        d_first: assert (!probe_ra_first || (!probe_ra_v && probe_fq_cnt == '0));
        // a stream's first beat starts at the word holding its position
        d_j0:    assert (!(probe_s_on && probe_ra_first && !probe_rs_go) ||
                         32'(probe_ra_j0) == ((32'(q0m) + 1) >> 1));
        d_pos:   assert (!probe_s_on || probe_ra_pos == probe_spos + AW'(lcnt));
        // the realigner never passes the program's end, and is short of it
        // while it holds a word or a live burst still owes it beats
        d_bound: assert (!probe_s_on ||
                         (probe_ra_pos <= n &&
                          ((!probe_ra_v && probe_live_n == '0 &&
                            (probe_rs_go || probe_rd_left == '0)) ||
                           probe_ra_pos < n)));
        d_req:   assert (!(probe_rq_s && probe_fq_cnt != '0) || (probe_s_on && p_addr == probe_spos));
        d_range: assert (probe_send == probe_base + AW'(probe_cnt) &&
                         32'(probe_cnt) <= STORE_D && probe_send <= n);
        d_parse: assert (!parse || (probe_base == '0 &&
                         32'(probe_send) == ((32'(ld_cnt) < STORE_D) ? 32'(ld_cnt) : STORE_D)));
        d_fptr:  assert (probe_wp == wp_exp && 32'(probe_fq_cnt) <= FDEPTH);
        // the chain: the first live burst starts at the beat the
        // realigner takes next (less what its head has landed), each
        // starts where the one before ends, and the engine asks next for
        // the beat after the last
        d_chain0: assert (probe_live_n == '0 ||
                          (probe_drop_n == '0 ? (st_d + XW'(hb) == e_abs) : (st_d == e_abs)));
        d_chain:  assert (&link_ok);
        d_chain1: assert (!(probe_s_on && !probe_rs_go) ||
                          (probe_live_n != '0 ? (XW'(probe_rd_ba >> BSH) == st_last + len_last)
                                              : (probe_rd_left == '0 ||
                                                 XW'(probe_rd_ba >> BSH) == e_abs)));
        // ...and while live bursts are outstanding the engine's next beat
        // and the beats it has left still end at the section's last beat,
        // none left included
        d_rdend:  assert (!(probe_s_on && !probe_rs_go && probe_live_n != '0) ||
                          (32'(probe_rd_ba >> BSH) + 32'(probe_rd_left) ==
                           32'(last_beat >> BSH) + 1));
        // ...and with none outstanding, the beats left are exactly those
        // from the beat the realigner takes next to the last: none at the
        // program's end or past its last beat
        d_rdend2: assert (!(probe_s_on && !probe_rs_go && probe_live_n == '0) ||
                          ((probe_ra_pos == n || 32'(e_abs) > 32'(last_beat >> BSH))
                           ? (probe_rd_left == '0)
                           : (32'(e_abs) + 32'(probe_rd_left) ==
                              32'(last_beat >> BSH) + 1)));
      end
    end

    // ---- the latency (P_LAT; task data_prove) ----------------------------
    // A word reaches `ok` at least two cycles after its beat lands: the
    // third of the three facts behind "no word of a bad beat is handed
    // over" (the header), and the one that is a property of the unit's
    // registers rather than of its fault logic. w_age, wb2 and w_land are
    // the harness's (below the memory), so the cover task can show the
    // bound is met exactly.
    if (P_LAT) begin : g_lat
      logic w_in_fifo, w_in_win;
      // the watched word in the FIFO, or in the window and not yet emitted
      // (every word a window emits ends in the window's own beat)
      assign w_in_fifo = probe_s_on && widx >= probe_spos && 32'(wrel) < 32'(lcnt);
      assign w_in_win  = probe_ra_v && widx >= probe_ra_pos && ((gw1 >> 3) == (gb >> 3));
      always_comb begin
        if (f_past_valid) begin
          // the claim: the stream hands over the watched word only when no
          // beat carrying it landed this cycle or the last
          a_lat:    assert (!(ok && probe_rq_s && p_addr == widx) ||
                            (w_age >= 2'd2 && !w_land));
        end
        if (f_past_valid && HELPERS) begin
          // a word in the FIFO, or a beat in the window, came after every
          // abandoned burst (one ID, in order), so none is still to land
          d_nodrop: assert (!(probe_ra_v || probe_fq_cnt != '0) || probe_drop_n == '0);
          // the watched word, once in the FIFO, landed two or more cycles ago
          d_age:    assert (!w_in_fifo || w_age >= 2'd2);
          // ...and while it is in the FIFO or the window, no beat of it is
          // still to land: no burst is live (at the program's end the next
          // beat may be its own, but nothing is outstanding or can launch),
          // or the beat the realigner takes next is past its beat
          d_noland: assert (!(w_in_fifo || w_in_win) || probe_live_n == '0 ||
                            32'(e_abs) > 32'(wb2));
        end
      end
    end
  end
  if (P_CTRL) begin : g_p_ctrl
    // ---- the helper invariants ----------------------------------------
    // Asserted, so proven with the claims: each states what the unit's
    // bookkeeping means in the memory's terms, which is what makes the
    // claims inductive. With them the task's assertions are proven
    // together (k-induction assumes every assertion at the steps
    // before), and without them three of the claims are not inductive
    // at any small depth.
    //
    // The beats still owed to live bursts: every live burst's length,
    // less the head's beats already landed when the head is live.
    logic [OUT_MAX*8+7:0] osum;
    logic [OUT_MAX:0]     lq_and;
    logic [8:0]           owed;
    assign osum[7:0] = 8'd0;
    assign lq_and[0] = 1'b1;
    for (genvar k = 0; k < OUT_MAX; k = k + 1) begin : g_owe
      logic [7:0] term;
      logic       lq_k;
      assign term = (32'(k) >= 32'(probe_drop_n) && 32'(k) < 32'(probe_out_n))
                  ? 8'(probe_lq[k*U_LW +: U_LW]) : 8'd0;
      assign osum[(k+1)*8 +: 8] = osum[k*8 +: 8] + term;
      // the unit's length queue is the memory's, entry for entry, and
      // the pending AR's length is the entry behind them
      assign lq_k = ((32'(k) < 32'(qn))
                     ? (32'(probe_lq[k*U_LW +: U_LW]) == 32'(ql[k*LW +: LW]))
                     : ((32'(k) == 32'(qn) && arvalid)
                        ? (32'(probe_lq[k*U_LW +: U_LW]) == 32'(arlen) + 1) : 1'b1)) &&
                    // ...and every outstanding burst is 1 to BURST beats
                    (32'(k) >= 32'(probe_out_n) ||
                     (probe_lq[k*U_LW +: U_LW] != '0 &&
                      32'(probe_lq[k*U_LW +: U_LW]) <= BURST));
      assign lq_and[k+1] = lq_and[k] && lq_k;
    end
    assign owed = 9'(osum[OUT_MAX*8 +: 8]) -
                  ((probe_drop_n == '0 && probe_out_n != '0) ? probe_bcnt : 9'd0);

    always_comb begin
      if (f_past_valid && HELPERS) begin
        h_out:  assert (32'(probe_out_n) == 32'(qn) + (arvalid ? 1 : 0));
        h_lr:   assert (32'(probe_live_n) + 32'(probe_drop_n) == 32'(probe_out_n));
        h_live: assert (32'(probe_live_n) <= LIVE_MAX);
        h_bc:   assert (probe_bcnt == hb && (qn != '0 || hb == '0));
        h_lq:   assert (lq_and[OUT_MAX]);
        h_rd:   assert (probe_rd_left == '0 ||
                        (n != '0 && probe_rd_ba[BSH-1:0] == '0 && probe_rd_ba >= sec0 &&
                         32'(probe_rd_ba >> BSH) + 32'(probe_rd_left) ==
                         32'(last_beat >> BSH) + 1));
        h_raj:  assert (!probe_ra_v || 32'(probe_ra_j) < WPB);
        // a pending pop's word is still in the FIFO, of a stream that is on
        // (a flush or a stop in the pop's cycle cancels it)
        h_popq: assert (!probe_pop_q || (probe_fq_cnt != '0 && probe_s_on));
        h_room: assert (32'(probe_fq_cnt) +
                        (probe_ra_v ? WPB - 32'(probe_ra_j) : 0) +
                        (fault ? 0 : WPB * 32'(probe_live_b)) <= (1 << FIFO_LOG2));
        h_owed: assert (fault || 9'(probe_live_b) == owed);
        h_son:  assert (!probe_s_on || !quiet);
        // a live head with no fault has landed fewer beats than its length
        // (a beat past it is a length fault), so every live burst still
        // owes a beat. Needed by s_live_gate, true at any size.
        h_bcl:  assert (fault || probe_drop_n != '0 || probe_out_n == '0 ||
                        probe_bcnt < 9'(probe_lq[U_LW-1:0]));
      end
    end

    // The scope facts: at the default sizes, the three shapes above
    // never occur. Off with the helpers, so that a claims-alone run
    // names a claim.
    if (ONE_BURST) begin : g_scope
      always_comb begin
        if (f_past_valid && HELPERS) begin
          s_full_busy: assert (!sh_full_busy);
          s_owed:      assert (!sh_owed);
          s_live_gate: assert (!sh_live_gate);
        end
      end
    end

    always_comb begin
      if (f_past_valid) begin
        a_past_n:       assert (!ok || (p_want && p_addr < n));
        a_fault_ends:   assert (!(ok && fault));
        a_rd_fault:     assert (!(p_bad_rd && !p_init) || fault_rd);
        a_len_fault:    assert (!(p_bad_len && !p_init) || fault_len);
        a_no_false_rd:  assert (!fault_rd || seen_rd);
        a_no_false_len: assert (!fault_len || seen_len);
        if (arvalid) begin
          a_ar_aligned: assert (araddr[BSH-1:0] == '0);
          a_ar_len:     assert (32'(arlen) + 1 <= BURST);
          a_ar_4k:      assert (!ar_last[ADDR_W] && araddr[ADDR_W-1:12] == ar_last[ADDR_W-1:12]);
          a_ar_section: assert (n != '0 && araddr >= sec0 && ar_last <= (ADDR_W + 1)'(last_beat));
        end
        if (p_arwait) begin
          a_ar_held:    assert (arvalid && araddr == p_araddr && arlen == p_arlen);
        end
        a_outstanding:  assert (32'(qn) + (arvalid ? 1 : 0) <= OUT_MAX);
        a_idle:         assert (idle == (qn == '0 && !arvalid));
        a_quiet:        assert (!(new_ar && (quiet || p_fault)));
        a_fifo_full:    assert (!(probe_fq_wr && probe_fq_cnt == (FIFO_LOG2 + 1)'(1 << FIFO_LOG2)));
        a_fifo_empty:   assert (!(probe_fq_rd && probe_fq_cnt == '0));
      end
    end
  end

  // ---- the bounded forms, tasks `deliver_prove` and `ends_prove` ---------
  // A wait: the consumer asks again for the address it asked for last
  // cycle, below n_insns, has done nothing else since, and is not yet
  // answered. A fault ends the wait (ok never comes after one).
  logic [5:0] w_cnt, i_cnt;
  logic       calm;
  assign calm = !init && !quiesce && !cap && !take && !ld;
  always_ff @(posedge clk) begin
    if (!rst_n) begin
      w_cnt <= '0;
      i_cnt <= '0;
    end else begin
      if (want && p_want && addr == p_addr && addr < n && calm && !ok && !fault)
        w_cnt <= (w_cnt == '1) ? w_cnt : w_cnt + 6'd1;
      else
        w_cnt <= '0;
      // stopped (a quiesce, an init, a fault) and not idle yet
      if (idle || !(quiet || fault))
        i_cnt <= '0;
      else
        i_cnt <= (i_cnt == '1) ? i_cnt : i_cnt + 6'd1;
    end
  end
  if (P_DELIV) begin : g_p_deliv
    always_comb begin
      if (f_past_valid) begin
        a_delivers: assert (32'(w_cnt) < WAIT_MAX);
      end
    end
  end
  if (P_ENDS) begin : g_p_ends
    always_comb begin
      if (f_past_valid) begin
        a_ends:     assert (32'(i_cnt) < IDLE_MAX);
      end
    end
  end

  // ---- reachability (task `cover`) --------------------------------------
  logic [AW-1:0] last_ok_addr;
  logic          ever_ok;
  always_ff @(posedge clk) begin
    if (!rst_n) begin
      ever_ok <= 1'b0;
      last_ok_addr <= '0;
    end else if (ok) begin
      ever_ok <= 1'b1;
      last_ok_addr <= p_addr;
    end
  end

  if (!ONE_BURST) begin : g_cov_wide
    // At sizes with room for more than one burst (task wide_cover): the
    // three shapes the default sizes cannot reach, and the reservation
    // reaching the larger FIFO's every slot.
    always_comb begin
      if (f_past_valid) begin
        c_full_busy: cover (sh_full_busy);
        c_owed:      cover (sh_owed);
        c_live_gate: cover (sh_live_gate);
        c_fifo_full: cover (probe_fq_cnt == (FIFO_LOG2 + 1)'(FDEPTH));
      end
    end
  end else begin : g_cov
    always_comb begin
      if (f_past_valid) begin
        // the watched word, handed over
        c_word:          cover (ok && p_addr == widx && n >= AW'(STORE_D + 2));
        // ...when it straddles two beats (an odd granule offset, at the
        // beat's last granule)
        c_straddle:      cover (ok && p_addr == widx && wa0[BSH-1:2] == '1 &&
                                widx >= AW'(STORE_D));
        // ...from the stream, exactly two cycles after its beat landed: so
        // a_lat's "at least two" is reached, and is the bound
        c_lat_two:       cover (ok && probe_rq_s && p_addr == widx && w_age == 2'd2);
        // a backward jump answered while bursts are still outstanding
        c_jump_inflight: cover (ok && ever_ok && p_addr + AW'(1) < last_ok_addr &&
                                qn != '0 && p_addr >= AW'(STORE_D));
        // an underrun: the consumer waited, then was answered
        c_underrun:      cover (ok && w_cnt >= 6'd2);
        // a program of the whole capacity, its last word handed over and
        // the presented address at n_insns itself
        c_capacity:      cover (n == AW'(STREAM_D) && p_want && p_addr == n - AW'(1) && ok);
        c_addr_at_n:     cover (n == AW'(STREAM_D) && want && addr == n && ever_ok);
        // a burst cut by the 4 KB page, the section going on past it
        c_4k:            cover (arvalid && araddr[11:BSH] == '1 &&
                                sec_end > (ADDR_W + 2)'(araddr) + (ADDR_W + 2)'(1 << BSH));
        // two bursts outstanding, and the most the unit allows
        c_two_out:       cover (qn >= QW'(2));
        c_full_out:      cover (32'(qn) + (arvalid ? 1 : 0) == OUT_MAX);
        // each fault, raised
        c_fault_rd:      cover (fault_rd && ever_ok);
        c_fault_len:     cover (fault_len && ever_ok);
        // a quiesce with bursts outstanding
        c_quiesce_drain: cover (quiet && qn != '0 && ever_ok);
        // the FIFO full (the reservation reached)
        c_fifo_full:     cover (probe_fq_cnt == (FIFO_LOG2 + 1)'(1 << FIFO_LOG2));
      end
    end
  end

endmodule
