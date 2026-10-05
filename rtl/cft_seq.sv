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
//     the constant region is NOT beat-padded).
//
//     Unless the header's flags.BANK_EXT is set (revision 2), in
//     which case the image is header then instructions with NO
//     constant section, the constants come from cfg_bank in a first
//     pass of the same byte parser, and the instructions from
//     cfg_prog + 32 in a second. The bank is laid out exactly as an
//     image's constant section is, which is what lets one parser read
//     either.
//
//     The image was validated by cft_program_load, and the hardware
//     re-checks only what protects the hardware:
//         magic   == "CFTP" (0x50544643)
//         version == 1
//         format  == cfg_prec (a program is compiled for one format)
//         n_insns <= STREAM_D (the capacity; IMEM_D until revision 8),
//         n_consts <= KMEM_D, max_deposits <= MAXD
//         flags[31:2] == 0; the second header word is zero unless
//           flags.SCRATCH_IO, and under it neither of its halves is
//           past SCRATCH_D
//     (the last line is revision 2's and revision 3's: the 0x600 tile
//     checked neither header word, which is why BANK_EXT needs a CAPS
//     bit and not only a flag - that tile would read constants out of
//     an image that has none - and the revision-2 tile's refusal of a
//     non-zero second word is in turn what guards SCRATCH_IO)
//     (max_deposits == 0 is LEGAL - the model allows it, every
//     deposit then overflows.) Every constant the header declares is
//     stored, up to KMEM_D: since 2026-09-07 an instruction with `kx`
//     set - bit 30, formerly reserved-must-be-zero - takes its three
//     constant indices from imm[7:0], imm[15:8] and imm[23:16] rather
//     than from the 4-bit operand fields, so all 256 are addressable.
//     Before that only the first 16 were stored, because no encoding
//     could name the rest.
//     A failure REFUSES the run: done pulses with `refuse` high,
//     nothing was computed, and no memory was written (the header/
//     image reads are the only traffic). Anything subtler - loop
//     structure, reserved bits, unassigned fields - is the loader's
//     to refuse, and the hardware's only obligation to a stream that
//     bypassed the loader is to terminate: an unknown control code
//     executes as HALT, an unmatched ENDREP as HALT.
//
//  2. EXECUTE, in blocks of NBEATS beats = NBEATS * lanes_per_beat
//     lanes. Per block: the register file's valid bits clear (an
//     unwritten entry reads +0; until 2026-09-14 the whole file was
//     wiped instead, RF_D cycles a block), the scratch is wiped to +0 as far as the
//     program can reach into it and, under flags.SCRATCH_IO, its
//     first n_scratch_in slots are preloaded per lane from cfg_sin
//     (lane-major and dense, so the preload is a transpose and runs
//     one element a cycle); r0/r1/r2 load from cfg_a/b/c at the
//     block's element offset (r3..r31 start +0), a lane is ACTIVE iff
//     its global index < cfg_n and, under MODE[23], its bit in the
//     lane mask at cfg_mask is set (revision 6, R17: the block's mask
//     bits are one single-beat read at block setup, and a masked lane
//     is not a lane the caller has); then the instruction stream runs to
//     HALT under seq.py's semantics - ALU results, deposits, SCRATCH
//     STORES, SCRATCH LOADS and FLAG contributions all masked
//     per-lane by active (P3); since revision 8, QUIET and ENDQUIET
//     bracket regions whose flags reach neither FLAGS nor a lane's R23
//     byte, RAISE ORs a register's [4:0] into both (unless in a region)
//     and marks the lane with its [7], AUGADD and AUGERR (where EN_AUGADD)
//     compute augmentedAddition's two halves, and a stepped STX or LDX
//     moves its index after the access (R21 to R24); REPEAT/ENDREP
//     from a 4-deep loop stack; SETACT narrows on (magnitude != 0, so
//     -0 deactivates); ACTALL reactivates every lane THE CALLER HAS
//     (global index < cfg_n) - the padding lanes the model never sees
//     stay dead, which is what keeps RTL-with-padding bit-identical
//     to the model without it. The early exit tests any(active) at
//     REPEAT/ENDREP; inside a loop the mask only ever narrows, so
//     even a stale view errs toward extra no-op iterations, which P3
//     makes invisible.
//
//  3. DRAIN, per block, one element a cycle through the deposit
//     banks' pipeline and one beat of eight counts a cycle (both
//     2026-09-14; both were an element a cycle at three states each,
//     the count drain a lane a cycle): every deposit slot in the block's window of
//     cfg_d is written - a lane's d-th deposit at element index
//     (i * max_deposits + d), slots the lane never reached as +0
//     (P2: addressed by index, never arrival) - then the per-lane
//     deposit counts as uint32 at cfg_cnt + 4*i, then, where the run
//     asked (MODE[24], revision 8's R23), the per-lane flag byte at
//     cfg_lflags + i, then, under flags.SCRATCH_IO, n_scratch_out
//     slots a lane at cfg_sout in the same lane-major layout the
//     preload reads. Lanes at or beyond cfg_n get none of them: the
//     tail of the caller's buffers is theirs, untouched. A MASKED lane
//     (R17) gets none of them either, and for the same reason - it is
//     not a lane the caller gave this run - but it sits INSIDE the
//     window rather than past it, so what "untouched" means on the bus
//     is a beat whose bytes for that lane's elements carry no write
//     strobe.
//
//  4. DONE. `flags` is the sticky OR of active-lane contributions
//     across the whole run; err[2:0] carry the engine's three bus
//     faults; err[3] is DEPOSIT OVERFLOW (a lane pushed past
//     max_deposits: the excess dropped, what fit is correct) - the
//     kernel maps it to STATUS[4], STATUS[3] being the refusal; err[4]
//     is SCRATCH RANGE (revision 4's R8: a strict indexed access past the
//     depth, suppressed) - STATUS[5]; and err[5] is the MARK (revision
//     8's R24: a RAISE whose operand's [7] is set, in a region or not) -
//     STATUS[6].
//
//  5. THE ABORT (revision 8, docs/ROADMAP.md "The abort"). A read burst
//     of the wrong length - RLAST before the beat ARLEN named (short), or
//     missing on it (long) - ENDS THE RUN, the engine's rule since
//     2026-08-30 (rtl/cft_engine_stream.sv, "abandoning a run the memory
//     system broke"). Until revision 8 a short burst left the burst
//     counter above zero, so the next burst was never issued and a
//     multi-beat read waited for ever; a long one zeroed the count a beat
//     early and handed its extra beats to a later read as data. Now, from
//     the fault on: no new burst is issued, read or write; a write burst
//     already committed (its AW issued) delivers its beats; every read in
//     flight lands, a long burst drained to its RLAST and a short one
//     ended by its own; and done comes with err[2] (STATUS[2]). A read
//     fault (RRESP not OKAY) on the HEADER BEAT or on a beat holding any
//     byte of an INSTRUCTION ends the run the same way, with err[0], so
//     no word the memory did not vouch for decides what runs. A read
//     fault on DATA - the constants, the bank, the scratch-in, a stream,
//     the mask, a table - completes the run as it always did, err[0]
//     saying its outputs are not to be trusted. An aborted run writes
//     nothing after the fault but the committed burst; S_ABORT is where
//     it waits for the reads, the write responses and the issue pipe.
//
// cfg_prog is 32-byte aligned (the library guarantees it); cfg_cnt is
// 4-byte aligned. n == 0 completes immediately, touching nothing.
//
// THE FETCH (revision 8, R8S; docs/studies/R8S-streaming.md). The image
// parse hands every instruction to rtl/cft_ifetch.sv, whose store keeps
// the first IMEM_D; a word past the store is read from the image again,
// during the block, by the unit's own read engine on this module's read
// port (the A master), and a REPEAT whose body starts outside the store
// moves the store to it. So the image is read throughout a run, not only
// at its start, and must not change between start and done. The fetch
// owns the read port from a block's first request until it is idle after
// the block ends (S_WAIT_B waits for it), and it opens only with the main
// read engine drained - no setup burst still to land, a long one drained
// to its RLAST by the abort, which then ends the run before any fetch. A
// program of at most IMEM_D instructions is held whole in the store, reads
// nothing during a block and runs in exactly the cycles it did before.
//
// The read port serves the program image and the three input streams
// (phases never overlap); the write port serves deposits and counts,
// and the lane-flag and scratch-out blocks after them.
// cft_krnl steers each read to the A, B or C master by the buffer it
// belongs to (m_rd_sel), since on HBM a master reaches only its own
// bank; one read port still keeps the whole machine a straight line.
// (Until 2026-09-23 this said B and C stayed quiet in sequencer runs,
// which stopped being true on 2026-09-02.) One burst is in flight at a time on each
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
//                   slice. 32 regs x NBEATS beats x 32 B = 16 KiB, the
//                   same silicon at every precision. It was 16 regs
//                   until revision 2; doubling it cost -258 LUT and
//                   0.000 ns on the U50 at 135 MHz, because the banks
//                   were already block RAM and 512 x 32 fits the same
//                   primitive 256 x 32 did (docs/VALIDATION.md,
//                   2026-09-08).
//   imem / kmem     the instruction stream, and the KMEM_D addressable
//                   constants, held already broadcast across the beat
//                   because a run's format never changes. The bank is
//                   read into three registers once per instruction,
//                   not once per issue beat: a constant cannot change
//                   during a run, and a 256-entry bank is a memory
//                   rather than a LUT mux, so the read belongs in the
//                   fetch shadow where the cycle is already spent.
//   deposit buffer  eight 32-bit banks, one per 32-bit word position
//                   within a beat - a wider lane occupies adjacent
//                   banks at one address - so divergent per-lane
//                   deposit counts still write in a single cycle.
//                   Slots are append-only, so "slot < count" IS the
//                   written mask and untouched slots need no
//                   bookkeeping to read back as +0.
//   scratch         SCRATCH_D x NBEATS entries of BEAT_BITS,
//                   addressed {slot, beat} exactly as the register
//                   file is addressed {reg, beat}: 128 KiB a tile at
//                   256 slots and 16 beats, the same silicon at every
//                   precision. One write port and one read port, but
//                   each of the eight word banks carries its OWN
//                   address, because STX and LDX take the slot from
//                   `rb` and the lanes of one beat hold divergent rb
//                   values - the deposit buffer's refinement, for the
//                   deposit buffer's exact reason. Wiped per block to
//                   as far as the program can reach into it, so a
//                   program that names no slot pays no cycles and a
//                   slot no lane wrote still reads +0.
//
// The issue/drain machine is the one the design sketched: an ALU
// instruction issues over the block's beats back to back, results
// retire LATENCY later through the same per-lane masking, and the next
// instruction's beats follow this one's without a gap - it is fetched
// under this one's issue and addressed from the cycle after this one's
// last address (2026-09-14; until that day a dependent chain cost
// beats + LATENCY + a few cycles of state machine a link, and an
// independent one the same, because every instruction waited for the
// last result of the one before). An instruction costs its beats. A
// dependent one waits, a beat at a time, for the beat it needs, and on
// a single-pass tile takes it as it lands - forwarded to the fire
// stage from the array's output, the write in flight or the write that
// landed as the file was read - so a link of a dependent chain costs
// LATENCY + 1 cycles at sixteen beats: the fire is a registered
// request and the landing is what it waits for.

`timescale 1ns/1ps

module cft_seq #(
    parameter int BEAT_BITS  = 256,
    parameter int LATENCY    = 16,
    parameter int NBEATS     = 16,     // lane block; see the guard below
    parameter int MAXD       = 64,     // deposit slots per lane, hw cap
    // The instruction STORE (revision 8, R8S): the program's first IMEM_D
    // instructions, or a loop body a REPEAT moved it to, held on chip in
    // rtl/cft_ifetch.sv. Until revision 8 this was the capacity.
    parameter int IMEM_D     = 1024,
    // The instruction CAPACITY (revision 8, R8S): the most instructions a
    // program may have. Past the store they stream from card memory
    // through the A master (rtl/cft_ifetch.sv). Equal to IMEM_D, the
    // default, builds no stream, and the tile is the one it was.
    parameter int STREAM_D   = IMEM_D,
    // Constant capacity (image-side). 256 -> 512 at revision 3, where
    // imm[30:28] became the ninth bit of each kx index. This DEFAULT
    // matters beyond the unit bench: tb/test_krnl.py resolves
    // `localparam int KREG = KMEM_D` through it and holds
    // cft_krnl's SEQ_KIDX_W against the result, so a default that
    // lagged the instantiation would have CAPS advertising a bank the
    // decoder could not address.
    parameter int KMEM_D     = 512,
    // Scratch slots a lane (revision 3, R4). A POWER OF TWO: the
    // indexed forms reduce rb modulo this, and a mask is the only
    // reduction a cycle can afford. SCRATCH_D * NBEATS beats of
    // BEAT_BITS is 128 KiB at 256 and 16.
    parameter int SCRATCH_D  = 256,
    parameter int ADDR_W     = 64,
    parameter bit EN_FP32    = 1'b1,
    parameter bit EN_FP64    = 1'b1,
    parameter bit EN_FP128   = 1'b1,
    parameter bit EN_FP256   = 1'b1,
    // Own ALU array (1, the unit bench's configuration) or the
    // kernel's shared one through the lane_* ports (0).
    parameter bit OWN_LANES  = 1'b1,
    // The multi-cycle multiplier's pass budget, for the private array
    // only (cft_lanes has the story); the kernel's array is paced by
    // the kernel and reaches this module as lane_ready.
    parameter int MUL_PASSES = 1,
    // Revision 8's R21 (docs/ROADMAP.md, question 9): 1, the default,
    // decodes control codes 10 and 11 - augadd and augerr - and fires
    // them into the array with the aug_mode sideband; cft_krnl publishes
    // CAPS2[11] from the same parameter. At 0 the two codes are unknown
    // ones, as on revision 7: a stream that reaches one ends its block
    // there (HALT), and a loader refuses them first, by name, from
    // CAPS2[11]. The quad is built at 0 (probe L: +10,595 LUTs a tile).
    /* verilator lint_off WIDTHTRUNC */
    parameter bit EN_AUGADD  = 1'b1
    /* verilator lint_on WIDTHTRUNC */
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
    // The per-run constant bank (BANK_PTR, revision 2 R3). Read only
    // when the header's flags.BANK_EXT is set, and then it is the ONLY
    // source of constants: the image carries none. It rides the same
    // master the image does - the two never overlap in time - so no
    // master is added and hw/link.cfg needs nothing.
    input  logic [ADDR_W-1:0] cfg_bank,
    // The per-run scratch block (SCRATCH_IN_PTR / SCRATCH_OUT_PTR,
    // revision 3 R5). Read and written only when the header's
    // flags.SCRATCH_IO is set, and then only for the slots the header
    // declares. cfg_sin rides the A master with the image and the
    // bank - three phases of one read stream that never overlap in
    // time - and cfg_sout rides the D master with the deposits and
    // the counts, for the same reason.
    input  logic [ADDR_W-1:0] cfg_sin,
    input  logic [ADDR_W-1:0] cfg_sout,
    input  logic [ADDR_W-1:0] cfg_cnt,
    /* ABI 0.14, docs/SEQUENCER.md R16: the four index tables and the
     * MODE bits that say which input blocks are fetched through one -
     * [0] a, [1] b, [2] c, [3] scratch_in, decoded in the CSR out of
     * MODE[22:19]. The CSR has already REFUSED those bits on a build
     * whose FEAT_INDEXED is clear, so a bit that arrives here is one
     * this module implements and nothing below re-checks it - the same
     * division of labour cfg_prec has. */
    input  logic [3:0]        cfg_indexed,
    input  logic [ADDR_W-1:0] cfg_idx_a,
    input  logic [ADDR_W-1:0] cfg_idx_b,
    input  logic [ADDR_W-1:0] cfg_idx_c,
    input  logic [ADDR_W-1:0] cfg_idx_si,
    /* ABI 0.14, docs/SEQUENCER.md R17: the per-run LANE MASK, decoded
     * in the CSR out of MODE[23] and pointed at by MASK_PTR (0xA8).
     * The CSR has already REFUSED the bit on a build whose
     * FEAT_LANE_MASK is clear, so a bit that arrives here is one this
     * module implements - the same division of labour cfg_prec and
     * cfg_indexed have. Bit i of the buffer is lane i, GLOBAL, and a
     * clear bit is a lane the caller does not have: it runs no
     * instruction, contributes no flag, and none of the three drains
     * writes one of its elements. */
    input  logic              cfg_mask_en,
    input  logic [ADDR_W-1:0] cfg_mask,
    /* Revision 8's R23 (docs/SEQUENCER.md): MODE[24], decoded in the CSR,
     * asks for the per-lane flag block, a byte a lane, written at
     * cfg_lflags (LFLAGS_PTR, 0xB0) after the counts. The CSR refuses
     * MODE[24] on a build whose FEAT_LANE_FLAGS is clear, so a bit that
     * arrives here is one this module implements. cfg_lflags is 32-byte
     * aligned, as cfg_prog is (the library allocates the block). */
    input  logic              cfg_lflags_en,
    input  logic [ADDR_W-1:0] cfg_lflags,
    output logic              busy,
    output logic              done,       // one-cycle pulse
    output logic              refuse,     // valid with done
    output logic [4:0]        flags,      // valid from done to next start
    output logic [5:0]        err,        // [2:0] bus faults, [3] dep ovf,
                                          // [4] scratch index out of range,
                                          // [5] a RAISE marked a lane
                                          // (revision 8's R24)

    // ---- the ALU array (cft_lanes) ---------------------------------
    // The per-issue request the issue machine builds, and the array's
    // answer. With OWN_LANES the instance below closes the loop; in
    // cft_krnl these reach the array cft_engine_stream also drives.
    output logic                 lane_valid,
    output logic [7:0]           lane_op,
    output logic [2:0]           lane_rnd,
    // Revision 8's R21 sideband, the array's aug_mode: 0 an ordinary
    // operation, 1 augadd, 2 augerr. Zero at revision 8's seam, until
    // R21's decode is built: every code this module decodes today is an
    // ordinary operation. libcft refuses codes 10 and 11 by name on a
    // tile without CAPS2[11], and a stream that bypassed the loader
    // decodes them here as HALT (the `default` arm).
    output logic [1:0]           lane_aug_mode,
    output logic [1:0]           lane_prec,
    output logic [BEAT_BITS-1:0] lane_a,
    output logic [BEAT_BITS-1:0] lane_b,
    output logic [BEAT_BITS-1:0] lane_c,
    // The array accepts a request only in a cycle with lane_ready
    // high (cft_lanes' in_ready: every cycle in the shipping tile, one
    // in NP at a multi-cycle rung). The registered request below is
    // HELD until then, and the issue machine holds with it.
    input  logic                 lane_ready,
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
  // Addressable constants. Sixteen was a property of the ENCODING, not
  // of this module: an operand's index lived in a 4-bit field. `kx`
  // (bit 30) moved the indices into imm's low three bytes, so the
  // limit is now the header check's, which was already KMEM_D.
  localparam int KREG       = KMEM_D;
  // At least one bit, so a one-entry bank on some future trimmed
  // build does not elaborate a [-1:0] index.
  localparam int KAW        = (KREG > 1) ? $clog2(KREG) : 1;
  localparam int AR_MAXLEN  = 63;                     // 64-beat bursts
  localparam int LB         = $clog2(BLK_LANES);      // 7
  localparam int DB_D       = NBEATS * MAXD;
  localparam int DBA        = $clog2(DB_D);
  // log2 of the CAPACITY since revision 8 (of IMEM_D until then): pc and
  // skip_depth are a bit wider, [PCW:0], because pc must be able to equal
  // n_insns (the implicit halt) and the header admits n_insns equal to the
  // capacity; lp_body, a body's first instruction, is [PCW-1:0]
  // (R8S-streaming.md, section 2, "Widths").
  localparam int PCW        = $clog2(STREAM_D);

  localparam logic [1:0] PREC_FP32  = 2'd0;
  localparam logic [1:0] PREC_FP64  = 2'd1;
  localparam logic [1:0] PREC_FP128 = 2'd2;
  localparam logic [1:0] PREC_FP256 = 2'd3;

  // control codes (instruction bit 31 set), from seq.py
  localparam logic [7:0] C_HALT = 8'd0, C_REPEAT = 8'd1, C_ENDREP = 8'd2,
                         C_DEPOSIT = 8'd3, C_SETACT = 8'd4, C_ACTALL = 8'd5,
                         C_STL = 8'd6, C_LDL = 8'd7,
                         C_STX = 8'd8, C_LDX = 8'd9,
                         // Revision 8's R21: augmentedAddition's two
                         // halves (754-2019 9.5), decoded where EN_AUGADD.
                         C_AUGADD = 8'd10, C_AUGERR = 8'd11,
                         // Revision 8's R24, flag control
                         // (docs/SEQUENCER.md): a quiet region and a raise.
                         C_QUIET = 8'd12, C_ENDQUIET = 8'd13,
                         C_RAISE = 8'd14;
  // The opcode a scratch LOAD rides the array as (revision 7, R18), when
  // it is not FAST - a fast load's value goes into the file through the
  // retire's port and never enters the array (the send-back of
  // 2026-09-29; the rule is with the admission):
  // IOR, the integer group's bitwise OR, fired with both operands the
  // loaded value, gives the value back bit for bit at every format and
  // raises no flag - softfloat.ior returns (a | b, 0), cft_simpleops
  // selects `a | b` and leaves its flags at zero, and the four pipe
  // benches hold the two to each other at every format (IOR is one of
  // tb/fpfma_common.py's SIMPLE_OPS). That is a schedule over a
  // verified operation, not arithmetic of the sequencer's own (P1);
  // and the retire takes no flag from a load whatever the array says.
  localparam logic [7:0] OP_IOR = 8'd17;
  // ...and the opcode augadd and augerr ride the array as (revision 8,
  // R21): ADD, whose operands cft_opmux shapes as (a, 1.0, c), with the
  // sideband saying which half of the pair the pipe keeps.
  localparam logic [7:0] OP_ADD = 8'd1;
  // ...and revision 8's R22 step: IADD, the integer group's add on the
  // encoding, which is the contract's own arithmetic for rb := rb + step
  // modulo 2^W (docs/ROADMAP.md, R22) - the array computes it, so P1 holds.
  localparam logic [7:0] OP_IADD = 8'd19;

  // ---- the scratch's geometry (revision 3, R4) -----------------------
  // SCRSW is the slot field's width and the reduction the indexed
  // forms apply: rb's low SCRSW bits ARE the slot, which is a mask and
  // not a division only because SCRATCH_D is a power of two.
  // At least one bit, so a one-slot build does not elaborate a [-1:0]
  // index - the same guard KAW carries.
  localparam int SCRSW = (SCRATCH_D > 1) ? $clog2(SCRATCH_D) : 1;
  localparam int SCR_D = SCRATCH_D * NBEATS;
  // = SCRSW + NBSH, and written from SCR_D for the reason RFAW is:
  // NBSH is declared with the lane state, further down. The address is
  // {slot, beat}, exactly the register file's {reg, beat}.
  localparam int SCRAW = $clog2(SCR_D);

  // ---- run-latched configuration -------------------------------------
  logic [1:0]        prec_q;
  logic [63:0]       n_q;
  logic [ADDR_W-1:0] a_q, b_q, c_q, d_q, prog_q, bank_q, cnt_q;
  logic [ADDR_W-1:0] sin_q, sout_q;
  // R16's four tables and the bits that select them, latched with the
  // rest of the run's configuration for the reason every other pointer
  // is: a register the host rewrites mid-run cannot change what this
  // run reads.
  logic [ADDR_W-1:0] idx_a_q, idx_b_q, idx_c_q, idx_si_q;
  logic [3:0]        idx_en_q;
  // R17's mask pointer and its enable, latched for the same reason.
  logic [ADDR_W-1:0] mask_q;
  logic              mask_en_q;
  // R23's pointer and its enable, latched for the same reason.
  logic [ADDR_W-1:0] lf_q;
  logic              lf_en_q;

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
  // The header's second word under flags.SCRATCH_IO (revision 3, R5):
  // slots preloaded into every lane before the first instruction, and
  // slots read back out after the last deposit. Both are refused past
  // SCRATCH_D at the header, so SCRSW+1 bits hold either.
  logic [SCRSW:0] h_nsin, h_nsout;
  logic           scr_io_q;
  logic           scr_strict_q;   // flags[2], revision 4's R8
  // What the INSTRUCTION STREAM can reach, learned while it is parsed:
  // one past the highest static STL/LDL slot, and whether any STX or
  // LDX appears at all. The per-block wipe is sized from these, which
  // is what keeps a program that uses no scratch costing no cycles for
  // one - and every existing bench's cycle count unchanged.
  logic [SCRSW:0] scr_hi;
  logic           scr_all;
  // Which of r0..r2 the program READS - by the opcode's operand use
  // (op_reads, below, held to the model's own steering by
  // tb/test_seq_core.py), never by a field that merely names one, plus
  // the control codes that read one - gathered by the image parser: the
  // block load skips the streams it never reads. The first rule counted
  // any register field below three, which over-approximated by design
  // and cost a beat read dense; once a stream could be gathered through
  // a table (R16) it cost the whole table plus a round trip per entry
  // for a stream nothing read. Found by round 2's V1, 2026-09-15.
  logic [2:0]     rd_need;
  // (The instruction memory, `imem`, was here until revision 8; the store
  // is rtl/cft_ifetch.sv's, below with the fetch's hooks.)
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
  // Thirty-two registers a lane since revision 2 (docs/SEQUENCER.md,
  // R1): the file doubles from 7.5 to 15 KiB a tile and the addresses
  // grow by the one bit that says which half.
  localparam int RF_D  = 32 * NBEATS;
  // The address is {reg[4:0], beat[NBSH-1:0]}, so it is exactly wide
  // enough for the file and every entry is reachable. It was a fixed
  // eight bits with a fixed four-bit beat field, which is dense only
  // at NBEATS = 16 - the one value the kernel and the unit bench both
  // use, so nothing was ever wrong, but at any smaller block the
  // address ran off the end of an array the same expression had just
  // sized. Deriving both from NBEATS costs nothing at 16 and makes
  // `RF_D = 32 * NBEATS` a true statement about the addressing rather
  // than only about the declaration.
  // = 5 + NBSH; written from RF_D because NBSH is declared with the
  // lane state, further down.
  localparam int RFAW  = $clog2(RF_D);
  // Declared ahead of the register file that reads them; defined beside
  // what they are about - the array request, and the queue of retiring
  // destinations.
  logic issue_hold;
  logic raw_hold;                   // a dependent beat has not landed yet
  // Revision 7, R18: two more reasons the A stage holds, both about the
  // scratch (the section with the queue has the rules): a beat that is
  // not an LDX waits while an LDX beat is in B or F (gap_hold), and an
  // LDL waits while a store beat is in B or F (stld_hold).
  logic gap_hold, stld_hold;
  logic a_hold;                     // A holds and B and F drain
  logic rd_hold;                    // any of them: the A stage holds
  // Revision 7, R18: the beat each pipe stage is carrying (F acts on
  // pf_bt's row, an LDX fires at H on ph_bt's), and the rows the
  // requests in the array fired with - the shadow the retire reads,
  // LATENCY rows of WORDS bits, shifted beside `fs` on the array's own
  // enable. Declared here because the row selects below read them.
  logic [5:0]               pb_bt, pf_bt, pg_bt, ph_bt;
  logic [LATENCY*WORDS-1:0] fr;
  // Revision 7, R19: the beat each request fired from, shifted beside
  // the row. The retire counted beats (wb_bt) and wrote the n-th result
  // to beat n; with beats skipped a result must say which beat it is.
  logic [LATENCY*6-1:0]     ft;
  logic [5:0]               wb_tag;
  logic dr_stall;                   // the deposit drain holds (declared here
                                    // for the banks' read register, defined
                                    // with the drain's pipeline)
  logic [RFAW-1:0] rf_raddr_a, rf_raddr_b, rf_raddr_c;
  logic [BEAT_BITS-1:0] rf_rdata_a, rf_rdata_b, rf_rdata_c;
  logic        rf_we;
  logic [RFAW-1:0]  rf_waddr;
  logic [BEAT_BITS-1:0] rf_wdata;
  logic [WORDS-1:0]     rf_wwe;      // per-word (= per-lane-slice) enables

  // Each bank registers its own read data locally and drives its
  // slice of the shared read bus with a continuous assign - the one
  // multi-driver shape the tools all agree on. Eight always_ff blocks
  // each writing a slice of one shared VARIABLE is illegal
  // SystemVerilog that Icarus punishes with event-storm molasses
  // rather than an error message.
  // Zero on first read (2026-09-14). Every block used to WIPE the file
  // - RF_D = 512 cycles a block, which is 16 cycles a lane at fp128 and
  // was measured on the card as the largest share of a program run's
  // fixed cost - so that r3..r31 read +0. Now one valid bit per
  // {reg, beat} entry says whether the entry has been written THIS
  // block: a read of an unwritten entry answers +0, and the FIRST write
  // to an entry writes every lane slice - the result where the lane's
  // enable is on, +0 where it is off - after which writes mask per
  // lane as before. That is exactly seq.py's state: a lane's register
  // is +0 until the lane writes it while active, and a masked write
  // leaves it alone; the only lane whose slice a first write zeroes is
  // one that has never written the register this block, whose value
  // IS +0. The bits clear in one cycle at S_BLK_SETUP (rf_clear, wired
  // where the state is declared). 512 flops and three 512:1 selects
  // replace 512 cycles a block.
  logic [RF_D-1:0] rf_v;
  logic            rf_clear;
  logic            rf_first;
  assign rf_first = rf_we && !rf_v[rf_waddr];
  always_ff @(posedge ap_clk) begin
    if (!ap_rst_n || rf_clear)
      rf_v <= '0;
    else if (rf_we)
      rf_v[rf_waddr] <= 1'b1;
  end
  generate
    for (genvar gw = 0; gw < WORDS; gw = gw + 1) begin : g_rf
      logic [31:0] bank0 [0:RF_D-1];
      logic [31:0] bank1 [0:RF_D-1];
      logic [31:0] ra_q, rb_q, rc_q;
      logic        va_q, vb_q, vc_q;
      always_ff @(posedge ap_clk) begin
        // The read registers hold with the array's standing request
        // (issue_hold, below): the F stage fires beat c-2 from the data
        // that beat c's address request put on the bus two STEPS ago,
        // and a step is a cycle the array accepts, not a clock. They do
        // NOT hold with a dependent beat's wait (raw_hold), which holds
        // the A stage alone: an address already on the bus is sampled
        // and fired on schedule, whatever A is waiting for. Every other
        // reader of this bus runs when nothing is held. The valid bit
        // rides the same register, so data and its validity are always
        // from the same address on the same cycle.
        if (!issue_hold) begin
          ra_q <= bank0[rf_raddr_a];
          rb_q <= bank0[rf_raddr_b];
          rc_q <= bank1[rf_raddr_c];
          va_q <= rf_v[rf_raddr_a];
          vb_q <= rf_v[rf_raddr_b];
          vc_q <= rf_v[rf_raddr_c];
        end
        if (rf_we && (rf_wwe[gw] || rf_first)) begin
          bank0[rf_waddr] <= rf_wwe[gw] ? rf_wdata[gw*32 +: 32] : 32'b0;
          bank1[rf_waddr] <= rf_wwe[gw] ? rf_wdata[gw*32 +: 32] : 32'b0;
        end
      end
      assign rf_rdata_a[gw*32 +: 32] = va_q ? ra_q : 32'b0;
      assign rf_rdata_b[gw*32 +: 32] = vb_q ? rb_q : 32'b0;
      assign rf_rdata_c[gw*32 +: 32] = vc_q ? rc_q : 32'b0;
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
        // The read register holds with the drain's stall (2026-09-14,
        // the same day the drain became a pipeline). While the write
        // channel cannot take a completed beat the pipeline holds its
        // address and its tags - but the address it holds is the NEXT
        // element's, issued the cycle before, and a register that kept
        // sampling it moved on to that element's data while stage 2
        // still held the stalled element's tag: on release the stalled
        // element went out with its successor's data. A drain longer
        // than a burst, with a beat completing as the next burst was
        // not yet open, was what it took to see it.
        if (!dr_stall)
          rd_q <= bank[db_raddr];
      end
      assign db_rdata[gb*32 +: 32] = rd_q;
    end
  endgenerate

  // ---- the scratch (revision 3, R4) -----------------------------------
  //
  // Organised exactly like the register file: SCR_D = SCRATCH_D *
  // NBEATS entries of BEAT_BITS, addressed {slot, beat}, eight 32-bit
  // word banks each with its own always_ff and its own local arrays,
  // driving its slice of a shared read bus with a continuous assign.
  // Eight always_ff blocks writing slices of one shared VARIABLE is
  // the shape the register file's comment names as illegal
  // SystemVerilog that Icarus punishes with event-storm molasses, and
  // it is avoided here for the same reason. SCRATCH_D * NBEATS
  // entries of BEAT_BITS is 128 KiB a tile at 256 and 16 - eight
  // banks of 4,096 x 32 bits, 16 KiB each - and it is that at every
  // precision, because a beat is 32 bytes whatever the format.
  //
  // ONE read port and ONE write port, which is what the contract asks
  // for and all the four codes need - but each bank carries its OWN
  // address, which the register file does not do. That is the deposit
  // buffer's refinement and it is here for the deposit buffer's exact
  // reason: STX and LDX take the slot from `rb`, and the lanes of one
  // beat hold DIVERGENT rb values, so a shared address would force a
  // lane-serial access. Independent BRAMs make independent addresses
  // free, and a lane's element is a whole number of words, so a
  // lane's banks always move together.
  logic [WORDS-1:0]        scr_we;
  logic [WORDS*SCRAW-1:0]  scr_waddr;
  logic [WORDS*32-1:0]     scr_wdata;
  logic [WORDS*SCRAW-1:0]  scr_raddr;
  logic [WORDS*32-1:0]     scr_rdata;
  // The wipe's two bits (revision 7), declared here because g_scr reads
  // them: scr_wipe_q says this cycle's scr_we is the wipe's own write,
  // and scr_bcast that this block's wipe is BROADCAST - every sub-array
  // takes it at once (below, and S_BLK_SETUP).
  logic                    scr_wipe_q;
  logic                    scr_bcast;

  // Sub-banks (revision 7, 2026-09-29). A bank of SCR_D entries is built
  // from SCR_SUB-entry arrays - 4,096 x 32 bits, the shape revision 3
  // put each bank in, which the U50 build made one UltraRAM apiece and
  // which cost 0.000 ns at 135 MHz - and never as one deeper array. At
  // 256 slots a bank IS one such array and nothing here changes. At the
  // U50's 2,048 a bank is 32,768 deep: as one array it is an eight-deep
  // URAM cascade, whose read passes up to seven cascade hops before it
  // reaches the fabric, or a block-RAM fallback the quad cannot hold -
  // revision 3's instruction memory, a four-deep cascade, was moved to
  // block RAM "due to insufficient pipeline registers". As eight arrays
  // it is eight standalone URAMs and one 8:1 mux after them, selected by
  // the slot's high bits registered with the read: the same one-cycle
  // read, the same ports, the same bits in every simulator. The
  // attribute pins each array to UltraRAM, where the quad's scratch
  // fits and block RAM does not (docs/SEQUENCER.md, revision 7).
  localparam int SCR_SUB  = (SCR_D > 4096) ? 4096 : SCR_D;
  localparam int SCR_NSUB = SCR_D / SCR_SUB;
  localparam int SCR_SAW  = $clog2(SCR_SUB);          // 12 at 4,096
  localparam int SCR_SELW = (SCR_NSUB > 1) ? $clog2(SCR_NSUB) : 1;

  generate
    for (genvar gs = 0; gs < WORDS; gs = gs + 1) begin : g_scr
      if (SCR_NSUB == 1) begin : g_one
        logic [31:0] bank [0:SCR_D-1];
        logic [31:0] rd_q;
        always_ff @(posedge ap_clk) begin
          if (scr_we[gs])
            bank[scr_waddr[gs*SCRAW +: SCRAW]] <= scr_wdata[gs*32 +: 32];
          // Held with the array's standing request, as the register
          // file's read registers are (revision 7, R18). It was
          // unconditional while only the scratch states read it, one
          // access at a time; the loads now read it INSIDE the issue pipe
          // - an LDL between A and F, an LDX between F and H - and on a
          // multi-pass tile the pipe holds between accepts, so a register
          // that kept sampling would hand the fire the NEXT beat's slot.
          // issue_hold is zero outside a program's issue, so the preload,
          // the wipe and the scratch-out drain read it exactly as before.
          // A read enable is still the shape a block RAM's output
          // register infers from.
          if (!issue_hold)
            rd_q <= bank[scr_raddr[gs*SCRAW +: SCRAW]];
        end
        assign scr_rdata[gs*32 +: 32] = rd_q;
      end else begin : g_sub
        logic [SCRAW-1:0]         wa, ra;
        logic [SCR_NSUB*32-1:0]   rd_all;
        logic [SCR_SELW-1:0]      sel_q;
        assign wa = scr_waddr[gs*SCRAW +: SCRAW];
        assign ra = scr_raddr[gs*SCRAW +: SCRAW];
        for (genvar gk = 0; gk < SCR_NSUB; gk = gk + 1) begin : g_k
          (* ram_style = "ultra" *) logic [31:0] sub [0:SCR_SUB-1];
          logic [31:0] rd_q;
          always_ff @(posedge ap_clk) begin
            // Its own select - or a BROADCAST wipe, which writes +0 at
            // the same local address in every sub-array at once, so
            // SCR_SUB cycles clear the whole memory at any depth
            // (S_BLK_SETUP). Only the wipe's writes are ever broadcast.
            if (scr_we[gs] && (wa[SCRAW-1 -: SCR_SELW] == SCR_SELW'(gk) ||
                               (scr_wipe_q && scr_bcast)))
              sub[wa[SCR_SAW-1:0]] <= scr_wdata[gs*32 +: 32];
            // Held as g_one's is, for R18's reason: every sub-array reads
            // the low address whenever the pipe moves, and the select
            // picks one.
            if (!issue_hold)
              rd_q <= sub[ra[SCR_SAW-1:0]];
          end
          assign rd_all[gk*32 +: 32] = rd_q;
        end
        // Registered from the same address on the same edge as the
        // reads, and held with them, so the select and the data it
        // selects are always one read's - a held read keeps its own
        // sub-array.
        always_ff @(posedge ap_clk)
          if (!issue_hold)
            sel_q <= ra[SCRAW-1 -: SCR_SELW];
        assign scr_rdata[gs*32 +: 32] = rd_all[32'(sel_q) * 32 +: 32];
      end
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

  // The NBEATS guard docs/ROADMAP.md asked for before anyone changed
  // the ALU depth, written now that someone has (LATENCY 15 -> 16,
  // 2026-09-07). It is deliberately NOT `NBEATS >= LATENCY + 1`, which
  // is what the parameter's comment used to say. That relation is about
  // KEEPING THE PIPE FULL, not about correctness: results retire in
  // arrival order through wb_bt, and the retire block below the state
  // machine runs in every state, so a block shorter than the pipe
  // simply lands its results while the next instruction is fetched,
  // decoded or held on them (raw_hold, 2026-09-14). What IS
  // structural is the register file's address shape - rf_raddr_* and
  // rf_waddr carry {reg[4:0], beat[NBSH-1:0]} - and that the block
  // length fits the beat counters. Raise NBEATS past 16 and `bt` and
  // `wb_bt` no longer hold a block's worth of beats, and the six-bit
  // beat arguments those row functions take stop covering the block.
  // (The beat field was a fixed FOUR bits until revision 2, dense only
  // at NBEATS 16 - the one value anything builds - and is now NBSH, so
  // a smaller block addresses its own file exactly rather than
  // indexing past the end of an array the same expression sized.)
  generate
    if (NBEATS < 1 || NBEATS > 16) begin : g_nbeats
      $error("cft_seq: NBEATS must be 1..16 - the register file addresses a beat in four bits");
    end
    if ((1 << NBSH) != NBEATS) begin : g_nbeats_pow2
      $error("cft_seq: NBEATS must be a power of two - the beat index is NBSH bits wide");
    end
    // The indexed scratch forms reduce rb MODULO the depth, and the
    // model does the same, so the reduction is part of the contract.
    // A mask is the only reduction a cycle can afford, and a mask is
    // only a modulo for a power of two - a depth that was not one
    // would make the hardware and the model disagree about every
    // STX/LDX, silently.
    //
    // Since revision 4 the model does the same only while the header's
    // SCRATCH_STRICT is clear; with it, an index at or past the depth
    // is reported (STATUS[5]) instead. This file implements that too
    // (R8: scr_strict_q takes flags[2] at the header check, and
    // lane_oor_fn / scr_oor below suppress and report the access), so
    // the sentence above now holds for every image whose flags[2] is
    // clear - every image built before revision 4 - and a strict one
    // takes the range test rather than the modulo, as the model does.
    //
    // The assertion below is load-bearing twice now. A power-of-two
    // depth is what makes a mask a modulo, AND what makes
    // `bitlen(rb) > SCRSW` the same question as `rb >= SCRATCH_D` -
    // which is the range test R8 wants, and cheaper than a comparator:
    // an OR of the index bits above SCRSW.
    if ((1 << SCRSW) != SCRATCH_D) begin : g_scratch_pow2
      $error("cft_seq: SCRATCH_D must be a power of two - STX/LDX reduce rb with a mask");
    end
    // Revision 7 made MAXD, IMEM_D and SCRATCH_D a build's parameters
    // (rtl/cft_krnl.sv declares them, and a build may set them), and
    // the kernel publishes each as a FOUR-BIT log2 - CAPS[19:16],
    // CAPS[23:20], CAPS2[3:0]. So each must be a power of two no larger
    // than 2^15: $clog2 is the ceiling, so any other value would be
    // published as a larger capacity than this module has, and 2^16
    // would wrap its field to "one". The guards live here rather than
    // in cft_krnl.sv because this is where the three are elaborated,
    // and because cft_krnl.sv keeps this construct out of itself for
    // the open-toolchain gate. The scratch's power of two is the guard
    // above; these add its ceiling and the other two.
    if ((1 << $clog2(MAXD)) != MAXD || MAXD > 32768) begin : g_maxd_caps
      $error("cft_seq: MAXD must be a power of two no larger than 2^15 - CAPS[19:16] publishes its log2 in four bits");
    end
    // Revision 8 (R8S): IMEM_D is the store and STREAM_D the capacity. The
    // store is indexed by an address's low bits, so it is a power of two
    // of at least two words and no deeper than the capacity; the capacity
    // is a power of two to 2^30 (an int parameter stops there; CAPS2[20:16]
    // publishes its log2 in five bits). A tile that does not stream
    // (STREAM_D == IMEM_D) publishes its capacity in CAPS[23:20] alone, in
    // four bits, as every tile did: 2^15 at most.
    if ((1 << $clog2(IMEM_D)) != IMEM_D || IMEM_D < 2 || IMEM_D > STREAM_D) begin : g_imem_store
      $error("cft_seq: IMEM_D, the instruction store, must be a power of two from 2 to STREAM_D");
    end
    if ((1 << PCW) != STREAM_D || STREAM_D > (1 << 30)) begin : g_stream_caps
      $error("cft_seq: STREAM_D, the instruction capacity, must be a power of two no larger than 2^30 - CAPS2[20:16] publishes its log2");
    end
    if (STREAM_D == IMEM_D && IMEM_D > 32768) begin : g_imem_caps
      $error("cft_seq: a tile that does not stream publishes its capacity in CAPS[23:20], four bits of log2 - IMEM_D at most 2^15");
    end
    if (SCRATCH_D > 32768) begin : g_scratch_caps
      $error("cft_seq: SCRATCH_D must be no larger than 2^15 - CAPS2[3:0] publishes its log2 in four bits");
    end
  endgenerate

  initial begin
    if (NBEATS < 1 || NBEATS > 16 || (1 << NBSH) != NBEATS) begin
      $display("FATAL: cft_seq NBEATS=%0d must be a power of two in 1..16", NBEATS);
      $fatal(1);
    end
    if ((1 << SCRSW) != SCRATCH_D) begin
      $display("FATAL: cft_seq SCRATCH_D=%0d must be a power of two", SCRATCH_D);
      $fatal(1);
    end
    if ((1 << $clog2(MAXD)) != MAXD || MAXD > 32768 || SCRATCH_D > 32768) begin
      $display("FATAL: cft_seq MAXD=%0d SCRATCH_D=%0d: each must be a power of two no larger than 2^15, the most a four-bit log2 in CAPS publishes",
               MAXD, SCRATCH_D);
      $fatal(1);
    end
    if ((1 << $clog2(IMEM_D)) != IMEM_D || IMEM_D < 2 || IMEM_D > STREAM_D ||
        (1 << PCW) != STREAM_D || STREAM_D > (1 << 30) ||
        (STREAM_D == IMEM_D && IMEM_D > 32768)) begin
      $display("FATAL: cft_seq IMEM_D=%0d STREAM_D=%0d: the store a power of two from 2 to the capacity, the capacity a power of two to 2^30, and a tile that does not stream at most 2^15",
               IMEM_D, STREAM_D);
      $fatal(1);
    end
  end

  logic [BLK_LANES-1:0]    active;
  logic [BLK_LANES*CW-1:0] dcnt;
  logic any_active;
  assign any_active = |active;

  // ---- loop stack -----------------------------------------------------
  logic [PCW-1:0] lp_body [0:3];
  logic [31:0]    lp_left [0:3];
  logic [2:0]     lp_sp;
  // Revision 8's R24: the quiet depth, counted by QUIET and ENDQUIET as
  // they are decoded, in program order, as REPEAT and ENDREP keep the loop
  // stack; three bits (the loader nests regions four deep), saturating,
  // so a stream that bypassed the loader keeps a defined depth rather than
  // wrapping a region open or closed (it gates only flags, so it bears on
  // no termination). Reset at each block's start. An instruction is quiet
  // when admitted inside a region.
  logic [2:0]     qdepth;

  // ---- the ALU array --------------------------------------------------
  logic                 al_valid;
  logic [7:0]           al_op;
  logic [2:0]           al_rnd;
  // R21's sideband (revision 8): 0 an ordinary operation, 1 augadd, 2
  // augerr, registered with the request it travels beside (al_op, al_rnd)
  // and set at every fire, so it is 0 for every beat but an augadd's or
  // an augerr's. The same signal reaches the shared array (as
  // lane_aug_mode, which cft_krnl hands the array only in a sequencer
  // run) and the private one below.
  logic [1:0]           al_aug;
  logic [BEAT_BITS-1:0] al_a, al_b, al_c;
  logic                 al_rdy;
  logic                 al_ov;
  logic [BEAT_BITS-1:0] al_d;
  logic [WORDS*5-1:0]   al_lf;

  // A registered request the array has not yet taken. While it stands
  // the issue machine and the register file's read registers hold, so
  // the two-beats-ahead address pipeline of S_ISSUE stays two
  // beats ahead in ACCEPTED beats. In the shipping tile al_rdy is a
  // constant 1 and this is a constant 0.
  assign issue_hold = al_valid && !al_rdy;

  assign lane_valid = al_valid;
  assign lane_op    = al_op;
  assign lane_rnd   = al_rnd;
  assign lane_aug_mode = al_aug;
  assign lane_prec  = prec_q;
  assign lane_a     = al_a;
  assign lane_b     = al_b;
  assign lane_c     = al_c;

  generate
    if (OWN_LANES) begin : g_own_lanes
      cft_lanes #(
          .BEAT_BITS(BEAT_BITS), .LATENCY(LATENCY),
          .EN_FP32(EN_FP32), .EN_FP64(EN_FP64),
          .EN_FP128(EN_FP128), .EN_FP256(EN_FP256),
          .MUL_PASSES(MUL_PASSES), .EN_AUGADD(EN_AUGADD)
      ) u_lanes (
          .clk(ap_clk), .rst_n(ap_rst_n),
          .in_valid(al_valid), .op(al_op), .rnd(al_rnd),
          .aug_mode(al_aug), .prec(prec_q),
          .a(al_a), .b(al_b), .c(al_c), .in_ready(al_rdy),
          .out_valid(al_ov), .d(al_d), .lane_flags(al_lf));
    end else begin : g_shared_lanes
      assign al_rdy = lane_ready;
      assign al_ov  = lane_ov;
      assign al_d   = lane_d;
      assign al_lf  = lane_flags;
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
  // ...and the same construction for the two scratch blocks, which
  // are laid out exactly as the deposit buffer is: lane-major, dense,
  // format-width. blk_cap * esz is BLK_BYTES at every precision, so
  // the stride is a header field shifted by a compile-time constant
  // and not a product.
  logic [ADDR_W-1:0] sin_off,  sout_off;
  logic [ADDR_W-1:0] sin_stride, sout_stride;

  // blk_n * max_deposits, the block's deposit-element count. Both
  // factors are run-time values, so this is the one product in the
  // module that no shift replaces; it is formed one bit of the
  // multiplier per cycle in S_ZERO, which lasts CW + 1 cycles for it
  // (it used to last the register-file wipe's RF_D, with CW to spare;
  // the file's valid bits replaced the wipe on 2026-09-14).
  logic [31:0]   dep_elems;
  logic [31:0]   dep_addend;
  logic [CW-1:0] dep_mult;
  // The two scratch blocks want the same product against their own
  // counts, so they share the ADDEND - one shifter, three
  // accumulators, three multiplier registers. The longest of the
  // three is SCRSW+1 steps. That was an order of magnitude inside RF_D
  // while S_ZERO lasted the register-file wipe; since the wipe went
  // (2026-09-14) S_ZERO waits for the two scratch products explicitly
  // (revision 7), because SCRSW+1 grows with the depth.
  logic [31:0]    sin_elems, sout_elems;
  logic [SCRSW:0] sin_mult, sout_mult;

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
  // Which pass of the parser is running: the BANK_EXT constant pass
  // from BANK_PTR, or the instruction pass from the image. A program
  // without BANK_EXT never sets it and runs exactly one pass, as it
  // always did.
  logic        bank_phase;
  logic        bank_ext_q;
  logic [31:0] kons_i, insn_i;

  // How empty the parse window must become before the reader may take
  // another beat, while constants are being peeled. TWO constraints,
  // and both are required:
  //
  //   * the parser must not peel on the cycle `rready` is high, or the
  //     handshake completes and the beat falls on the floor - so the
  //     window must be too small for the NEXT field, which is another
  //     constant while `kons_left > 1`;
  //   * the beat below is absorbed at offset pw_have[2:0], so the
  //     window must hold fewer than eight bytes when it arrives.
  //
  // At fp64 and wider the second implies the first, because esz >= 8.
  // At fp32 it does not: a four-byte window is under eight and still
  // peelable, so rready went high, the parser peeled again, and the
  // beat the memory handed over on that handshake was lost - a program
  // whose CONSTANT REGION spans more than one beat then starved
  // forever. Found 2026-09-07 by tb/test_seq_core.py's first case to
  // load a bank longer than a beat (40 fp32 constants); every case
  // before it carried four constants or fewer, which is sixteen bytes
  // and never crossed a beat. Nothing to do with indexed constants -
  // it is simply the path they made worth reaching.
  logic [6:0] kons_room;
  assign kons_room = ((kons_left > 32'd1) && (esz < 6'd8)) ? {1'b0, esz}
                                                          : 7'd8;
  // The same two constraints for the scratch-in preload, which peels
  // format-width elements out of the same window for the same reason.
  logic [6:0] sin_room;
  assign sin_room = ((sin_left > 32'd1) && (esz < 6'd8)) ? {1'b0, esz}
                                                        : 7'd8;

  // ---- the gather (revision 6, R16) -----------------------------------
  //
  // An indexed block is read in two passes that INTERLEAVE on the one
  // read channel this module has: a beat of the TABLE (eight u32
  // entries at every format - the table holds indices, not elements),
  // then one single-beat read per entry at the element's own address,
  // then the next table beat. The two cannot overlap, because the
  // channel carries one burst at a time; that is also why the block's
  // whole table is not fetched in one burst, since the entries would
  // have nowhere to wait but a BLK_LANES-entry buffer and the saving
  // would be ceil(blk_n / 8) address phases against blk_n data round
  // trips.
  //
  // What comes back goes to the SAME two destinations the dense loads
  // have, by the same two paths: packed into beats for the register
  // file as S_LD_STREAM writes them, or one slot at a time into the
  // scratch as S_SIN_PARSE writes them. The gather is the drains'
  // beat assembler run backwards and the preload's transpose run
  // forwards; it invents no third way in.
  logic [BEAT_BITS-1:0] gt_tbl;    // the table beat being consumed
  logic [3:0]           gt_have;   // entries still in it, 0..WORDS
  logic [31:0]          gt_left;   // entries still owed for this block
  logic [ADDR_W-1:0]    gt_taddr;  // where the NEXT table beat is
  logic [ADDR_W-1:0]    gt_base;   // the source the entries index into
  logic [31:0]          gt_idx;    // the entry whose read is in flight
  logic                 gt_scr;    // this gather fills the scratch
  logic [BEAT_BITS-1:0] gt_beat;   // the beat being assembled
  logic [2:0]           gt_pos;    // where in it the next element goes
  logic [LB:0]          gt_lane;   // scratch only: lane and slot, the
  logic [SCRSW:0]       gt_slot;   // two counters S_SIN_PARSE keeps
  // The entry at the window's head, and whether it is the sentinel.
  // 32'hFFFF_FFFF is CFT_IDX_NONE (host/include/cft.h): the element
  // reads as +0 and NO read is issued for it, which is what makes a
  // row that has run out cost nothing in a gathered fold.
  logic [31:0] gt_ent;
  logic        gt_none;
  assign gt_ent  = gt_tbl[31:0];
  assign gt_none = (gt_ent == 32'hFFFF_FFFF);
  // Where the element sits inside the beat it arrives in. (idx * esz)
  // mod BEAT_BYTES is esz * (idx mod lpb), so no byte offset is ever
  // formed: the position IS the low bits of the index, and the select
  // is scr_elem_fn - the one the scratch-out drain already uses.
  logic [2:0] gt_sel;
  assign gt_sel = gt_idx[2:0] & 3'(lpb - 4'd1);
  // ONE placement path for both arms that produce an element - the
  // sentinel's +0, which needs no read, and a returned beat. Written
  // as a strobe and a value outside the case for the reason the retire
  // path is written that way: two copies of "pack an element into a
  // beat" is two chances to pack it differently.
  logic         gt_take;
  logic [255:0] gt_val;
  logic         gt_flush;   // this element closes a register-file beat

  // ---- AXI read side (single outstanding burst) -----------------------
  logic [ADDR_W-1:0] rd_addr;
  logic [1:0]        rd_sel;   // which buffer rd_addr points into
  logic [31:0]       rd_beats_left;   // beats not yet requested
  logic [8:0]        rd_burst_left;   // beats left in the open burst
  logic              rd_stream_on;    // a state wants read traffic
  // The abort (revision 8; the contract's item 5). rd_long_q: the open
  // burst ran past the beat ARLEN named, and its beats are being drained
  // to its RLAST - they belong to no reader. abort_q: the run is ending on
  // a fault; no new burst is issued from the cycle after the fault, and
  // the state machine goes to S_ABORT at its next safe point (abort_go).
  logic              rd_long_q;
  logic              abort_q;
  // The main read engine's AR and RREADY, registers since revision 8: the
  // read port is muxed between this engine and the instruction fetch's
  // (rtl/cft_ifetch.sv; the fetch's hooks, below), so the m_rd_* outputs
  // are driven there. rd_acc is a beat this engine took.
  logic [ADDR_W-1:0] rd_araddr_q;
  logic [7:0]        rd_arlen_q;
  logic              rd_arvalid_q;
  logic              rd_rready_q;
  logic [1:0]        rd_sel_q;
  logic              rd_acc;
  // The fetch's port side and its two status lines, declared here because
  // the read channel and the abort read them.
  logic              if_idle, if_fault_rd, if_fault_len;
  logic [ADDR_W-1:0] if_araddr;
  logic [7:0]        if_arlen;
  logic              if_arvalid, if_rready;
  // ...and its consumer side's answer, read by the admission, and the
  // abort's whole condition, read by the fetch's request.
  logic [63:0]       if_word;
  logic              if_ok;
  logic              abort_any;

  // ---- AXI write side (single outstanding burst) ----------------------
  logic [ADDR_W-1:0] wr_addr;
  logic [31:0]       wr_beats_left;   // beats not yet requested
  logic [8:0]        wr_burst_left;   // W beats left in the open burst
  logic [7:0]        wr_pend_len;
  logic              wr_aw_open;      // AW issued, not yet accepted
  logic [3:0]        wr_bresp_left;
  logic              wr_stream_on;

  /* WHICH OF THE THREE OPERANDS AN OPCODE ACTUALLY READS.
   *
   * R10 skips a stream no instruction reads, and until 2026-09-15 it
   * decided that from the OPERAND FIELD - a register number below
   * three in any of ra, rb, rc marked that stream needed. That is an
   * over-approximation, and the section that introduced it said so and
   * called it free, because it "only ever loads more": a defaulted
   * field is zero, so `alu(op, rd, ra=.., rc=..)` marked stream a and
   * cost one extra beat read a block.
   *
   * R16 made it anything but free. Through an index table that same
   * unread stream costs the whole table's beats AND one memory round
   * trip per entry - measured by this parcel's verifier at 9 table
   * bursts plus 70 element bursts for an fp64 program that names r0
   * only through a defaulted rb. The saving inverted into the most
   * expensive path the module has.
   *
   * So the rule is now the opcode's, and it is the model's: an operand
   * the ALU steers away from is not read. ADD and SUB take a and c
   * (b is steered to 1.0); MUL takes a and b (c is steered to a zero
   * of the product's sign); FMA and SELECT take all three; the unary
   * members of the simple group take a alone and the binary ones a and
   * b. Anything unassigned on this datapath keeps all three, because a
   * decode that guessed narrow would leave a register reading +0 and
   * answer confidently.
   *
   * Under-approximating here is a SILENT WRONG ANSWER - the stream is
   * not loaded and its register reads +0 - so the table is held to the
   * model twice over: tb/test_seq_core.py derives the same three bits
   * from `sf.steer` and the signatures of `sf.SIMPLE_IMPL` and asserts
   * every opcode, and every single-op, fuzz and corpus case in the
   * suite runs opcodes over r0..r2 and compares to the model, where a
   * stream wrongly skipped is a deposit that differs. */
  function automatic [2:0] op_reads(input [7:0] op);
    begin
      case (op)
        8'd0:  op_reads = 3'b111;   // FMA          a, b, c
        8'd1:  op_reads = 3'b101;   // ADD          a, c
        8'd2:  op_reads = 3'b101;   // SUB          a, c
        8'd3:  op_reads = 3'b011;   // MUL          a, b
        8'd4:  op_reads = 3'b001;   // ABS          a
        8'd5:  op_reads = 3'b001;   // NEG          a
        8'd6:  op_reads = 3'b011;   // COPYSIGN     a, b
        8'd7:  op_reads = 3'b011;   // MIN
        8'd8:  op_reads = 3'b011;   // MAX
        8'd9:  op_reads = 3'b011;   // MINNUM
        8'd10: op_reads = 3'b011;   // MAXNUM
        8'd11: op_reads = 3'b111;   // SELECT       a, b, c
        8'd12: op_reads = 3'b011;   // CMPLT
        8'd13: op_reads = 3'b011;   // CMPLE
        8'd14: op_reads = 3'b011;   // CMPEQ
        8'd16: op_reads = 3'b011;   // IAND
        8'd17: op_reads = 3'b011;   // IOR
        8'd18: op_reads = 3'b011;   // IXOR
        8'd19: op_reads = 3'b011;   // IADD
        8'd20: op_reads = 3'b011;   // ISUB
        8'd21: op_reads = 3'b011;   // ISHL
        8'd22: op_reads = 3'b011;   // ISHR
        8'd23: op_reads = 3'b011;   // ICMPLT
        8'd26: op_reads = 3'b001;   // RECIP_SEED   a
        8'd27: op_reads = 3'b001;   // RSQRT_SEED   a
        8'd30: op_reads = 3'b011;   // IMUL         a, b
        // 15, 24, 25, 28, 29 and 31 upward are unassigned on this
        // datapath (24/25/28/29/31 are the REDUCTIONS, which a program
        // cannot issue). All three, so a stream is never skipped for
        // an opcode whose operand use nobody has written down.
        default: op_reads = 3'b111;
      endcase
    end
  endfunction

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
  // The operand use of the instruction at the head of the peel window.
  // A continuous assign and not an inline call: a function's result
  // cannot be part-selected here, and calling it three times would
  // elaborate three copies of the decode. Assign rather than
  // always_comb, for the reason rd_bl below is an assign.
  logic [2:0] pw_reads;
  assign pw_reads = op_reads(pw[7:0]);

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
  // FIVE bits each since revision 2 (docs/SEQUENCER.md, R1). The low
  // four stay in the operand field the encoding has always kept them
  // in and the fifth comes from `imm`: imm[24] is rd[4], imm[25]
  // ra[4], imm[26] rb[4], imm[27] rc[4] - which is instruction bits
  // 56, 57, 58 and 59, all four of them reserved-must-be-zero on
  // every image an older loader would emit. imm[31:28] stays
  // reserved. Nothing else in the encoding moves.
  logic [4:0]  c_rd, c_ra, c_rb, c_rc;
  logic [2:0]  c_rnd;
  logic        c_ka, c_kb, c_kc, c_kx, c_ctrl;
  logic [31:0] c_imm;
  assign c_op   = cur[7:0];
  assign c_rd   = {cur[56], cur[11:8]};
  assign c_ra   = {cur[57], cur[15:12]};
  assign c_rb   = {cur[58], cur[19:16]};
  assign c_rc   = {cur[59], cur[23:20]};
  assign c_rnd  = cur[26:24];
  assign c_ka   = cur[27];
  assign c_kb   = cur[28];
  assign c_kc   = cur[29];
  assign c_kx   = cur[30];
  assign c_ctrl = cur[31];
  assign c_imm  = cur[63:32];

  // Revision 8's R22. The internal IADD a stepped LDX owes, admitted after
  // its last step as if it were the next instruction: IADD rb, rb, with
  // kb and kc set so that neither port B nor C is read, and the step in
  // imm[11:0] - which the F stage takes as operand b in place of a
  // constant (c_istep), sign-extended to the format's width. c_sld says
  // cur is a stepped LDX still owing it; both are registers, set where
  // cur is, so that neither adds logic to the admission's or the take's
  // paths beyond an AND.
  logic        c_istep, c_sld;
  logic [63:0] stp_word;
  assign stp_word = {4'b0, 1'b0, 1'b0, cur[58], cur[58], 12'b0, cur[43:32],
                     1'b0, 1'b0, 1'b1, 1'b1, 1'b0, 3'b0, 4'b0, 4'b0,
                     cur[19:16], cur[19:16], OP_IADD};

  // The constant index each operand names. Without `kx` it is the
  // operand's own 4-bit field, zero-extended; with `kx` it is a byte
  // of `imm`, which is what makes the whole bank reachable. The
  // loader has already refused every other reading of these fields
  // (a non-zero register field under `kx`, a non-zero imm byte
  // without one, imm[31:24], `kx` with no operand naming a constant),
  // so this mux is the only decision left.
  //
  // The FOUR-bit field, explicitly, in the plain form: an operand that
  // names a constant has no register, so the fifth bit is not its
  // index's - the loader refuses that bit set on such an operand, and
  // slicing here rather than trusting it keeps a stream that bypassed
  // the loader inside the bank instead of sixteen entries past it.
  //
  // The NINTH bit, revision 3's R7: under `kx` an operand's index is
  // its byte of `imm` plus one more bit from imm[30:28] - ka's, kb's
  // and kc's in that order - so the bank reaches 512. Same
  // construction as the fifth register bits one nibble down, and read
  // only under `kx` for an operand whose `k` flag is set; the loader
  // refuses it set anywhere else, as an unread field. imm[31] stays
  // reserved-must-be-zero, the next cheap version guard.
  logic [KAW-1:0] k_idx_a, k_idx_b, k_idx_c;
  assign k_idx_a = c_kx ? KAW'({c_imm[28], c_imm[7:0]})   : KAW'(c_ra[3:0]);
  assign k_idx_b = c_kx ? KAW'({c_imm[29], c_imm[15:8]})  : KAW'(c_rb[3:0]);
  assign k_idx_c = c_kx ? KAW'({c_imm[30], c_imm[23:16]}) : KAW'(c_rc[3:0]);

  // The three constants THIS instruction reads, latched out of the
  // bank one cycle behind `cur`. The bank was a 16-entry LUT mux read
  // COMBINATIONALLY on the issue path; at 256 entries it is a memory,
  // and a memory wants a registered read.
  //
  // There is no cycle cost, and the read rides the pipe (2026-09-14,
  // twice): the address stage captures the beat's three indices as it
  // captures its opcode (pb_kidx_*), the bank is read from those under
  // the hold the file's read registers hold under, and F fires from
  // the result - the register operands' own two-stage lead, so the
  // constants F sees are the constants of the instruction that
  // addressed the beat whatever the array's pace. The first version
  // read the bank from `cur` every clock and fired from that register
  // a stage later, which is the same thing only when the array accepts
  // every clock: a multi-pass tile holds the pipe between accepts,
  // `cur` moves on, and an instruction's last beat fired with the next
  // instruction's constants.
  //
  // In its own always_ff, not in the state machine's, and that is not
  // tidiness: one write port and three unconditional synchronous read
  // ports is the shape an inference engine recognises as a memory,
  // and a 256 x BEAT_BITS array that failed to infer would be 65,536
  // flip-flops behind three 256:1 muxes. No read enable, for the same
  // reason - the addresses are stable whenever the answer is wanted,
  // so gating the read would buy nothing and cost a condition.
  logic [BEAT_BITS-1:0] kq_a, kq_b, kq_c;   // the constants F fires with
  logic [KAW-1:0] pb_kidx_a, pb_kidx_b, pb_kidx_c;   // the B stage's beat's indices
  always_ff @(posedge ap_clk) begin
    if (!issue_hold) begin
      kq_a <= kmem[pb_kidx_a];
      kq_b <= kmem[pb_kidx_b];
      kq_c <= kmem[pb_kidx_c];
    end
  end

  // ---- state ----------------------------------------------------------
  typedef enum logic [5:0] {
    S_IDLE, S_HDR_GO, S_HDR_R, S_CHECK, S_BNK_GO, S_IMG_GO, S_IMG_PARSE,
    S_BLK_SETUP, S_MSK_GO, S_MSK_W,
    S_ZERO, S_SIN_GO, S_SIN_PARSE, S_LD_GO, S_LD_STREAM,
    S_GTH_GO, S_GTH_TBL, S_GTH_ELEM, S_GTH_WAIT,
    S_FETCH, S_FETCH2, S_DECODE,
    // Revision 7, R18: one issue state for every instruction that walks
    // the block's beats. DEPOSIT, SETACT and the four scratch codes had
    // states of their own (S_DEP_*, S_SET_*, S_SCR_*) at three to five
    // cycles a beat; they go through the pipe now, and the state that
    // was S_ALU_ISSUE issues them all.
    S_ISSUE,
    S_SKIP_F, S_SKIP_D,
    S_DRAIN_SETUP, S_DRAIN_RUN,
    S_CNT_SETUP, S_CNT_PACK, S_CNT_SEND,
    S_SO_SETUP, S_SO_RD, S_SO_W8, S_SO_PACK, S_SO_SEND,
    S_WAIT_B, S_NEXT_BLK, S_FIN,
    // Revision 8's R23: the per-lane flag block, after the counts.
    S_LF_SETUP, S_LF_PACK, S_LF_SEND,
    // Revision 8: the abort's wait - every read in flight landed, every
    // write response in, the issue pipe empty - then S_FIN.
    S_ABORT
  } state_e;
  state_e st;
  // R16's placement strobe. The sentinel arm of S_GTH_ELEM and the
  // return in S_GTH_WAIT are the only two producers, and gt_flush says
  // whether the element closes a beat: either it fills the last
  // position the format has, or it is the block's last entry and the
  // beat is short.
  assign gt_take = ((st == S_GTH_ELEM) && (gt_left != 0) &&
                    (gt_have != 0) && gt_none) ||
                   ((st == S_GTH_WAIT) && rd_acc);
  assign gt_val  = (st == S_GTH_WAIT)
                 ? scr_elem_fn(gt_sel, m_rd_rdata, wpe_sh) : 256'b0;
  assign gt_flush = (32'({29'b0, gt_pos}) == 32'(lpb) - 32'd1) ||
                    (gt_left == 32'd1);
  assign rf_clear = (st == S_BLK_SETUP);
  // The array is SHARED with the engine on the shipping tile, so its
  // result pulses reach this module while the engine runs; only a
  // program's own results retire (found on the card 2026-09-14: the
  // engine's fp128 reductions left a phantom instruction queued and the
  // next program's DEPOSIT waited for it forever).
  logic          seq_live;
  assign seq_live = (st != S_IDLE);
  // R19: the beat a result belongs to is the one it FIRED from (ft),
  // not the count of results so far, because a beat with no active lane
  // is never fired. An instruction that writes a register always fires
  // the block's last beat, so its last result is on that beat whatever
  // the mask, and that is where it leaves the queue.
  assign wb_tag  = ft[LATENCY*6-1 -: 6];
  // ...or a FAST load's last write (the send-back of 2026-09-29, below
  // with the load's rule): its value never enters the array, so it
  // leaves the queue at the write of the block's last beat.
  assign wb_pop  = (al_ov && seq_live &&
                    (wb_tag == 6'({1'b0, nb_blk} - 6'd1))) || fw_pop;
  assign q_after = q_n - {1'b0, wb_pop};
  assign q_e0    = wb_pop ? q_rd1 : q_rd0;
  assign q_e1    = wb_pop ? q_rd2 : q_rd1;
  assign q_room  = (q_after != 2'd3);
  // Revision 7, R18: which instructions go through the issue pipe, which
  // of those WRITE a register - and so take a queue slot and become a
  // producer later instructions wait on - and which register ports each
  // one reads. Until R18 the pipe carried arithmetic alone and every
  // control code that read the file, moved the mask or ended the block
  // waited for the queue to empty, then walked the block's beats in
  // states of its own at three cycles a beat (five for a load).
  //
  //   DEPOSIT ra, SETACT ra, STL ra   read port A; write no register
  //   RAISE ra (revision 8, R24)      read port A; write no register
  //   STX ra, rb                      read ports A and B; write none
  //   LDL rd                          read nothing from the file; write rd
  //   LDX rd, rb                      read port B; write rd
  //   AUGADD, AUGERR rd, ra, rb       read ra on port A and rb on port C;
  //     (revision 8, R21)             write rd - an ALU instruction's
  //                                   shape, with rb where ADD has rc
  //   STX ra, rb, step (R22, step     as STX, and WRITES rb: its F fires
  //     not zero)                     IADD(rb as the bank read it, the
  //                                   step) into the array, a slot a store
  //                                   leaves free, so it is a writer of rb
  //   LDX rd, rb, step (R22, step     as LDX (a writer of rd), then an
  //     not zero, rd not rb)          internal IADD rb, rb, step issued
  //                                   after it: up to one more
  //                                   instruction's beats (stp_word)
  //
  // R21's two exist only where EN_AUGADD is set; at 0 they are unknown
  // codes, as on revision 7, and end the block in S_DECODE.
  //
  // REPEAT, ENDREP, ACTALL and HALT walk no beats and stay in S_DECODE,
  // and so, since revision 8's R24, do QUIET and ENDQUIET.
  // A control code's read set is its row above, NOT ka/kb/kc: the loader
  // refuses those bits on a control code, and a stream that bypassed the
  // loader still reads the register the scratch states always read.
  function automatic logic aug_fn(input [63:0] w);
    begin
      aug_fn = EN_AUGADD && w[31] &&
               (w[7:0] == C_AUGADD || w[7:0] == C_AUGERR);
    end
  endfunction
  function automatic logic piped_fn(input [63:0] w);
    begin
      piped_fn = !w[31] ||
                 w[7:0] == C_DEPOSIT || w[7:0] == C_SETACT ||
                 w[7:0] == C_STL || w[7:0] == C_LDL ||
                 w[7:0] == C_STX || w[7:0] == C_LDX ||
                 w[7:0] == C_RAISE || aug_fn(w);
    end
  endfunction
  // Revision 8's R22: a stepped STX or LDX - imm[11:0], w[43:32], a signed
  // step not zero. Zero is the instruction exactly as it always was.
  function automatic logic stepped_fn(input [63:0] w);
    begin
      stepped_fn = w[31] && (w[7:0] == C_STX || w[7:0] == C_LDX) &&
                   (w[43:32] != 12'd0);
    end
  endfunction
  // ...and a stepped LDX whose destination is not its index, which owes
  // the internal IADD (`ldx rX, rX, step` keeps what it loaded, R22)
  function automatic logic sld_fn(input [63:0] w);
    begin
      sld_fn = stepped_fn(w) && (w[7:0] == C_LDX) &&
               ({w[56], w[11:8]} != {w[58], w[19:16]});
    end
  endfunction
  function automatic logic writer_fn(input [63:0] w);
    begin
      writer_fn = !w[31] || w[7:0] == C_LDL || w[7:0] == C_LDX ||
                  aug_fn(w) || (stepped_fn(w) && w[7:0] == C_STX);
    end
  endfunction
  // {c, b, a}
  function automatic [2:0] reads_fn(input [63:0] w);
    begin
      if (!w[31])
        reads_fn = {!w[29], !w[28], !w[27]};
      else if (w[7:0] == C_DEPOSIT || w[7:0] == C_SETACT ||
               w[7:0] == C_STL || w[7:0] == C_RAISE)
        reads_fn = 3'b001;
      else if (w[7:0] == C_STX)
        reads_fn = 3'b011;
      else if (w[7:0] == C_LDX)
        reads_fn = 3'b010;
      else if (aug_fn(w))
        reads_fn = 3'b101;
      else
        reads_fn = 3'b000;
    end
  endfunction
  // R21's two, which read rb on port C (the decode table above)
  logic       c_aug;
  assign c_aug     = aug_fn(cur);
  logic       c_piped, imq_piped, adm_wr;
  logic [2:0] adm_reads;
  assign c_piped   = piped_fn(cur);
  assign imq_piped = piped_fn(if_word);
  // Admission: from S_DECODE, the decoded instruction if it goes through
  // the pipe; from the last address cycle of an issue, the word read
  // under it if that is here, goes through the pipe and is not past the
  // end. Every admission needs queue ROOM, a writer or not: then a
  // producer an admitted instruction waits on is at position 0 or 1 of
  // the queue, and a control code waits no longer than it did when it
  // waited for the queue to be EMPTY.
  //
  // FAST LOADS (2026-09-29, verifier-R4's send-back). A load's value used
  // to reach the file only through the array, as IOR(v, v): at sixteen
  // beats the pipelining hides the array's depth, and at ONE beat nothing
  // does, so a program that used a loaded value at once ran slower than
  // f681dee's, whose LDL wrote the file itself. So a load is FAST when,
  // at its admission, every queued writer ahead of it (after this
  // cycle's pop) is a fast load too - an empty queue included. A fast
  // load keeps its queue slot, so everything that reads its destination
  // tracks it as it tracks any producer; but its value never enters the
  // array: the retire's own write port writes it into the file at F (an
  // LDL) or H (an LDX), under the row the beat fires with, the head's
  // reach wb_bt advances as a landing would advance it, and the slot pops
  // at the block's last beat. The port is free: every writer ahead of a
  // fast load is fast and writes in program order, one beat a step,
  // popping before the next one's first write; every writer behind it
  // fires after its last F (an LDX's last H - the gap keeps the next beat
  // two steps behind) and lands LATENCY + 1 later. So no array result
  // lands while a fast load writes, a fast load is the head whenever it
  // writes, and writes to its register stay in program order.
  //
  // A load that cannot be fast rides the array on a single-pass tile, as
  // before - a full block hides the depth. On a MULTI-PASS tile it waits
  // here until it can be (every array writer ahead of it has landed):
  // there the array takes a beat every pass period, and a load through it
  // costs sixteen of them to issue and sixteen more for its user to wait,
  // where f681dee's load waited for the same drain and then took five
  // cycles a beat. After the wait it takes one.
  assign e0_fast   = wb_pop ? q_f1 : q_f0;
  assign e1_fast   = wb_pop ? q_f2 : q_f1;
  assign all_fast  = (q_after == 2'd0) ||
                     (q_after == 2'd1 && e0_fast) ||
                     (q_after == 2'd2 && e0_fast && e1_fast);
  assign adm_ld    = adm_w[31] && (adm_w[7:0] == C_LDL || adm_w[7:0] == C_LDX);
  assign adm_fast  = adm_ld && all_fast;
  assign adm_ld_ok = FWD || !adm_ld || all_fast;
  // R22: a stepped LDX's last step admits its internal IADD (stp_word)
  // instead of the next word, which is neither taken nor waited for.
  assign adm_go  = (st == S_DECODE) ? (c_piped && adm_ld_ok) :
                   (st == S_ISSUE) && !rd_hold && last_step &&
                   (c_sld || (if_ok && imq_piped)) && adm_ld_ok;
  assign adm_take = adm_go && q_room;
  assign adm_w   = (st == S_ISSUE) ? (c_sld ? stp_word : if_word) : cur;
  assign adm_wr  = writer_fn(adm_w);
  assign q_push  = adm_take && adm_wr;
  assign adm_reads = reads_fn(adm_w);
  // ...and a stepped STX's destination is rb (R22), every other writer's rd
  assign adm_rd  = (stepped_fn(adm_w) && adm_w[7:0] == C_STX)
                 ? {adm_w[58], adm_w[19:16]} : {adm_w[56], adm_w[11:8]};
  assign adm_ra  = {adm_w[57], adm_w[15:12]};
  assign adm_rb  = {adm_w[58], adm_w[19:16]};
  // ...port C's field is rb's for augadd and augerr (R21), which read rb
  // there; every other instruction's is rc.
  assign adm_rc  = aug_fn(adm_w) ? {adm_w[58], adm_w[19:16]}
                                 : {adm_w[59], adm_w[23:20]};
  // the youngest queued writer of each register operand, if any
  assign dep_n_a = adm_reads[0] && ((q_after >= 2'd2 && q_e1 == adm_ra) ||
                                    (q_after >= 2'd1 && q_e0 == adm_ra));
  assign dep_p_a = (q_after >= 2'd2 && q_e1 == adm_ra) ? 2'd1 : 2'd0;
  assign dep_n_b = adm_reads[1] && ((q_after >= 2'd2 && q_e1 == adm_rb) ||
                                    (q_after >= 2'd1 && q_e0 == adm_rb));
  assign dep_p_b = (q_after >= 2'd2 && q_e1 == adm_rb) ? 2'd1 : 2'd0;
  assign dep_n_c = adm_reads[2] && ((q_after >= 2'd2 && q_e1 == adm_rc) ||
                                    (q_after >= 2'd1 && q_e0 == adm_rc));
  assign dep_p_c = (q_after >= 2'd2 && q_e1 == adm_rc) ? 2'd1 : 2'd0;
  // the per-beat wait: the producer is not the head yet, or its beat
  // for the one being addressed has not landed - or, forwarding, will
  // not have landed by the time F fires. "Will have landed" is the head's
  // reach two cycles from now: the highest beat + 1 among the results
  // landing within two cycles (win_q, below), or wb_bt if that is more.
  // Until the send-back of 2026-09-29 it was wb_bt + la, the number of
  // landings in that window added to the reach - the same thing while a
  // producer's beats land one after another, and short of it once R19
  // skips beats: a producer whose first issued beat is 3 or later, or
  // whose issued beats have a gap, lands a beat the count cannot reach,
  // and the dependent beat waited for the landing itself - two cycles a
  // link on a masked chain, which verifier-R4 measured slower than
  // f681dee. By TAG it reaches any beat. A beat in the window that is not
  // the head's is a younger instruction's, and then every beat of the
  // head's is in the window or before it, so the maximum only ever says
  // yes when yes is right.
  //
  // Which of the two rules a port takes (R18). Forwarding's (R15) where
  // the operand is DATA - every ALU operand, and the value DEPOSIT, STL
  // and STX move - because F takes it from the forwarding merge and
  // puts it straight into a register. R14's, "landed", where the
  // operand feeds deeper logic: SETACT's ra (the magnitude test that
  // writes `active`) and the indexed codes' rb (the slot that forms the
  // scratch address). F reads those straight from the bank, as the
  // scratch and SETACT states always did, so no forwarding mux is put
  // in front of either path; a dependent SETACT or indexed access pays
  // the three cycles forwarding saves an ALU instruction.
  logic       a_fwd, b_fwd;
  // RAISE's ra likewise (revision 8, R24): its flag word and mark are read
  // from the bank at F, as SETACT's operand is.
  assign a_fwd = !(c_ctrl && (c_op == C_SETACT || c_op == C_RAISE));
  assign b_fwd = !c_ctrl;
  logic [5:0] wb_soon;
  assign wb_soon = FWD ? ((win_q > wb_bt) ? win_q : wb_bt) : wb_bt;
  assign dep_hold_a = dep_v_a && (dep_pos_a != 2'd0 ||
                                  (a_fwd ? wb_soon : wb_bt) <= bt);
  assign dep_hold_b = dep_v_b && (dep_pos_b != 2'd0 ||
                                  (b_fwd ? wb_soon : wb_bt) <= bt);
  assign dep_hold_c = dep_v_c && (dep_pos_c != 2'd0 || wb_soon <= bt);
  // R19: only a beat with a live lane waits for its producers. The
  // one beat issued without one - a writer's last beat, forced - fires
  // under an empty row, so whatever it reads is never written anywhere,
  // and making it wait would charge a masked block a whole link of a
  // dependent chain for nothing.
  assign raw_hold = (st == S_ISSUE) && beat_live[bt[NBSH-1:0]] &&
                    (dep_hold_a || dep_hold_b || dep_hold_c);
  // The scratch's two holds (R18). An LDX's slot comes from rb, which
  // reaches the bus only at F, so an LDX reads the scratch at G and
  // fires into the array at H - two steps after a beat addressed with
  // it would. A beat that is NOT an LDX therefore waits while an LDX
  // beat is in B or F: two bubbles after an LDX, none before one or
  // between two. That keeps every fire in program order and gives the
  // scratch's read address one owner a cycle (an LDL's A and an LDX's F
  // never both write it). And a store's bank write lands at the end of
  // step A+3 while an LDL reads at A+1 of its own: an LDL waits while a
  // store beat is in B or F, whatever the slot and whatever the beat - so
  // it binds at every block length, two cycles where a store stands
  // straight before a load (verifier-R4 measured it at sixteen beats,
  // where this comment said it never bound). Only a store and a load of
  // the SAME beat can meet, so a rule comparing the beats would bind only
  // on a block of one or two beats or across skipped beats: a possible
  // gain, not taken. An LDX needs no such wait - it reads at A+3 of a
  // LATER A - and a store after a load needs none: the load has read.
  logic c_is_ldl, c_is_ldx, pb_ldx, pf_ldx, pb_st, pf_st;
  assign c_is_ldl  = c_ctrl && c_op == C_LDL;
  assign c_is_ldx  = c_ctrl && c_op == C_LDX;
  assign pb_ldx    = pb_v && pb_ctrl && pb_op == C_LDX;
  assign pf_ldx    = pf_v && pf_ctrl && pf_op == C_LDX;
  assign pb_st     = pb_v && pb_ctrl && (pb_op == C_STL || pb_op == C_STX);
  assign pf_st     = pf_v && pf_ctrl && (pf_op == C_STL || pf_op == C_STX);
  assign gap_hold  = (st == S_ISSUE) && issue_this && !c_is_ldx &&
                     (pb_ldx || pf_ldx);
  assign stld_hold = (st == S_ISSUE) && issue_this && c_is_ldl &&
                     (pb_st || pf_st);
  assign a_hold    = raw_hold || gap_hold || stld_hold;
  assign rd_hold   = issue_hold || a_hold;
  // Nothing is in the pipe: every beat addressed has acted or fired,
  // and so has captured its row. ACTALL waits for this, and so does the
  // end of the block (with the queue empty as well).
  logic pipe_idle;
  assign pipe_idle = !pb_v && !pf_v && !pg_v && !ph_v;

  // Revision 7, R19: which beats the A stage ISSUES. A beat with no
  // active lane writes nothing, deposits nothing and raises nothing, so
  // it is not addressed at all: A walks the live beats and jumps the
  // rest. The mask A reads is the one `active` holds as the beat comes
  // up, and it can only be WIDER than the one the beat would fire under
  // (a SETACT still in the pipe narrows it; ACTALL, the one code that
  // widens, waits for the pipe to empty) - so a beat skipped here is
  // dead at F as well, and a beat issued that has died by F is masked
  // there as it always was. One exception: an instruction that WRITES a
  // register always issues the block's last beat, live or not, because
  // its queue slot is released by the result on that beat - an
  // instruction every lane had left would otherwise hold its slot for
  // ever. That beat fires under an empty row and writes nothing.
  //
  // The live vector is REGISTERED, a cycle behind `active`: it feeds a
  // priority encoder, `bt` and the admission, and a view one cycle old
  // is safe for the same reason A's view of `active` is - it can only
  // be stale on the WIDE side. `active` narrows (SETACT, at F) or
  // widens; a widening is the block's start (S_ZERO, many cycles before
  // the first admission) or ACTALL (in S_DECODE with the pipe empty,
  // three cycles before the next admission at the earliest), and the
  // register has caught up by then. A beat live in the register and
  // dead in `active` is issued and masked at F, as it always was.
  logic [NBEATS-1:0] beat_live_c, beat_live, c_final, iss_mask, adm_mask;
  generate
    for (genvar gl = 0; gl < NBEATS; gl = gl + 1) begin : g_live
      assign beat_live_c[gl] = |active[gl*WORDS +: WORDS];
      assign c_final[gl]     = (32'(gl) == 32'(nb_blk) - 32'd1);
    end
  endgenerate
  always_ff @(posedge ap_clk)
    beat_live <= beat_live_c;
  // The lowest set bit of `m` at or above `lo`, or NBEATS for none.
  function automatic [5:0] first_from_fn(input [NBEATS-1:0] m,
                                         input [5:0] lo);
    logic [5:0] r;
    logic       found;
    begin
      r = 6'(NBEATS);
      found = 1'b0;
      for (int b = 0; b < NBEATS; b = b + 1)
        if (!found && m[b] && 32'(b) >= 32'(lo)) begin
          r = 6'(b);
          found = 1'b1;
        end
      first_from_fn = r;
    end
  endfunction
  logic       c_wr, issue_this, last_step;
  logic [5:0] next_bt, adm_first0, adm_first;
  assign c_wr       = writer_fn(cur);
  assign iss_mask   = beat_live | (c_wr ? c_final : '0);
  assign issue_this = iss_mask[bt[NBSH-1:0]];
  assign next_bt    = first_from_fn(iss_mask, bt + 6'd1);
  assign last_step  = (next_bt == 6'(NBEATS));
  // The first beat of the instruction being ADMITTED (the word adm_w
  // names): the lowest beat it will issue, or - for a code that writes
  // nothing, with every beat dead - the last beat, as one bubble step
  // that issues nothing and ends the instruction.
  assign adm_mask   = beat_live | (adm_wr ? c_final : '0);
  assign adm_first0 = first_from_fn(adm_mask, 6'd0);
  assign adm_first  = (adm_first0 == 6'(NBEATS))
                    ? 6'({1'b0, nb_blk} - 6'd1) : adm_first0;

  logic [PCW:0]  pc;
  logic [PCW:0]  skip_depth;
  logic [5:0]    bt, wb_bt;
  // Instruction overlap (2026-09-14, in two steps). The issue is a
  // three-stage pipe that runs every unheld cycle whatever state the
  // machine is in: A puts a beat's three register addresses on the
  // file's bus (the state machine, in S_ISSUE), B is the file's
  // read (the bank registers into the slice bus) and the constant
  // bank's, F fires the beat into the array with the data now on the
  // bus and the constants (kq_*). Each stage carries the context of the
  // instruction its beat belongs to, because A can be addressing one
  // instruction's first beat while F fires the previous one's last:
  // the next instruction is read under this one's issue (if_word) and
  // admitted the cycle after this one's last address, and the beats
  // never stop. Up to three instructions that WRITE a register are then
  // in flight - retiring, in the array, being addressed - and their
  // destinations sit in q_rd0..2 from admission until their last beat
  // lands; q_rd0 is the one retiring (wb_bt counts its landed beats),
  // and the retire block below the state machine writes its beats as
  // the array delivers them and pops it after nb_blk of them.
  //
  // Revision 7, R18: the beat-walking control codes go through the same
  // pipe, one beat a cycle, where they used to wait for the queue to
  // empty and then walk the block in states of their own (DEPOSIT and
  // SETACT three cycles a beat, a store three, a load five). DEPOSIT,
  // SETACT and the stores ACT at F - the deposit banks and the count
  // row, the active row, the scratch write - and take no queue slot.
  // The loads are producers: they take a queue slot, and their value
  // reaches the file by the one retire port, in order, under the row the
  // beat fires with - written there directly when the load is FAST (every
  // queued writer ahead of it a fast load; the rule is with the
  // admission), fired into the array as IOR(v, v) otherwise, which is v
  // bit for bit and raises no flag (softfloat.ior; cft_simpleops). An LDL
  // reads the scratch between A and F; an LDX, whose slot is rb, forms
  // the address at F, reads at G and writes or fires at H (pg_*, ph_*).
  //
  // Read-after-write is the one hazard: in-order, so writes land in
  // order, and an instruction's reads all leave the file before the
  // instruction behind it writes anything. At admission each operand
  // that names a register finds the YOUNGEST queued instruction that
  // writes it - dep_v / dep_pos, a position from the head that every
  // pop moves down - and at the cycle beat b's address would go on the
  // bus the issue holds (raw_hold) unless that producer is the head
  // and its beat b has landed (wb_bt > bt). Landed is enough: the
  // write is in the bank by the end of the cycle, and the address put
  // on the bus now is read at the end of the next unheld cycle at the
  // earliest. Results land in beat order one a step and the issue
  // reads in beat order one a step, so a beat that is late is the
  // first beat that is late. The hold is on the A stage ALONE: B and F
  // drain what A already addressed - they must, because with a block
  // shorter than the pipe the beat A is waiting on can still be in F,
  // and a hold that froze F waited for a landing it was itself
  // preventing - and the array's standing request is taken as usual.
  // Nothing fires twice and nothing in the pipe is lost.
  //
  // Until revision 7 every control code that read the file, moved the
  // mask or ended the block waited here for the queue to empty. Now
  // (R18) a control code waits, a beat at a time, only for a queued
  // producer of a register it READS, exactly as an ALU operand does;
  // ACTALL waits for the pipe (not the queue) to empty, because every
  // result still in the array carries the row it fired with; and what
  // ends the block waits for both, in S_DRAIN_SETUP. REPEAT and ENDREP
  // still wait for nothing: the mask they test can only be stale on
  // the WIDE side (a SETACT still narrowing it), which runs one more
  // all-inactive iteration - a no-op, by P3.
  logic [4:0]    q_rd0, q_rd1, q_rd2;
  logic [1:0]    q_n;
  logic          q_push, wb_pop;    // this cycle: a destination admitted / retired
  logic [1:0]    q_after;           // queued after this cycle's pop
  logic [4:0]    q_e0, q_e1;        // the head and the one behind, after that pop
  logic          q_room;            // a fourth would not fit
  logic          adm_go;            // this cycle admits, given room
  logic          adm_take;          // ...and it has room: the instruction enters A
  // Fast loads (the send-back): a flag per queue entry, beside q_rd; the
  // admitted word's; and the terms that decide it.
  logic          q_f0, q_f1, q_f2;
  logic          e0_fast, e1_fast, all_fast;
  logic          adm_ld, adm_fast, adm_ld_ok;
  logic          c_fast;            // the instruction in A is a fast load
  // R24's tag (revision 8): the instruction in A was admitted inside a
  // quiet region. Taken at admission and carried with every beat to F,
  // where it joins al_fen - the flag enable that rides beside every fired
  // beat (fq) and gates FLAGS at the retire - and gates a RAISE's flags.
  // A region's edge, decoded in S_DECODE, never moves a beat already
  // admitted.
  logic          c_quiet, pb_quiet, pf_quiet;
  logic          fw, fw_x, fw_pop;  // a fast load's write this step
  logic [5:0]    fw_bt;
  logic [WORDS-1:0] fw_wwe;
  logic [63:0]   adm_w;             // the word being admitted
  logic [4:0]    adm_rd, adm_ra, adm_rb, adm_rc;
  logic          dep_v_a, dep_v_b, dep_v_c;        // the operand waits on a producer
  logic [1:0]    dep_pos_a, dep_pos_b, dep_pos_c;  // ...this far from the head
  logic          dep_n_a, dep_n_b, dep_n_c;        // ...as computed at admission
  logic [1:0]    dep_p_a, dep_p_b, dep_p_c;
  logic          dep_hold_a, dep_hold_b, dep_hold_c;
  // the pipe's B and F stages: a beat is in the stage, and whose. Since
  // R18 a stage's beat may be a control code's: pX_ctrl says so, pX_op
  // is then its code, pX_bt the beat it is on, and pX_slot a static
  // store's slot (the slot `cur` held has moved on by F).
  logic          pb_v, pf_v;
  logic [7:0]    pb_op, pf_op;
  logic [2:0]    pb_rnd, pf_rnd;
  logic          pb_ka, pb_kb, pb_kc, pf_ka, pf_kb, pf_kc;
  logic          pb_ctrl, pf_ctrl;
  // R22: a beat's step (imm[11:0]), whether it is a stepped STX's, and
  // whether it is the internal IADD's (operand b the step)
  logic [11:0]   pb_step, pf_step;
  logic          pb_sstep, pf_sstep, pb_istep, pf_istep;
  logic [SCRSW-1:0] pb_slot, pf_slot;
  // ...and an LDX's two more (R18): G reads the scratch at the address
  // F formed, H fires what came back. pX_oor carries R8's suppressed
  // banks from F, where rb was on the bus, to H, where the value is.
  logic          pg_v, ph_v;
  logic [WORDS-1:0] pg_oor, ph_oor;
  logic          pb_fast, pf_fast, pg_fast, ph_fast;   // a fast load's beat
  // The row and the flag enable a request fires with (R18), held with
  // it until the array takes it - al_valid's own discipline - and then
  // shifted down fr and fq beside fs: the retire writes the lanes, and
  // ORs the flags of the lanes, that were active when the beat FIRED.
  // A load fires with its flag enable off: it raises no flag in the
  // model, and that is not left resting on IOR's.
  logic [WORDS-1:0] al_row;
  logic          al_fen;
  logic [LATENCY-1:0] fq;
  logic [5:0]    al_tag;            // R19: the beat the request fired from
  // Forwarding (2026-09-14, the second step). On a single-pass tile
  // the array accepts every cycle, so its validity line can be
  // shadowed exactly (fs: fs[LATENCY-1] is al_ov, fs[LATENCY-2] lands
  // next cycle, fs[LATENCY-3] the cycle after) and a dependent beat's
  // address can go on the bus as soon as the producer's beat will have
  // landed BY THE TIME F FIRES - two cycles on - rather than once it
  // is in the bank. F then takes the operand from wherever it is: the
  // array's output if it lands that cycle, the write in flight if it
  // landed the cycle before, or the write that landed as B sampled
  // (kept a cycle in wa1/wd1/wwe1), each merged word by word over
  // what B read - which is what the bank holds for the words the
  // write does not touch, and +0 where the entry was unwritten.
  // Younger source first: the same address can appear in two of them
  // only as one instruction's write of it behind another's. A
  // multi-pass tile keeps R14's rule and reads only the bank.
  localparam bit FWD = (MUL_PASSES == 1);
  logic [LATENCY-1:0]   fs;
  // The look-ahead's window, by tag (the send-back; with wb_soon): the
  // highest tag + 1 among the results landing within two cycles, 0 if
  // none. Formed a cycle AHEAD from the shadow's next three positions -
  // on a single-pass tile, the only one it is read on, the shadow shifts
  // every cycle - and registered, so the path into the issue's wait is
  // one 6-bit maximum with wb_bt where it was a 6-bit add.
  logic [5:0]           win_q, win_c, win_t2, win_t3, win_t4;
  logic                 we1;
  logic [RFAW-1:0]      wa1;
  logic [BEAT_BITS-1:0] wd1;
  logic [WORDS-1:0]     wwe1;
  logic [RFAW-1:0]      pf_aa, pf_ab, pf_ac;   // where F's beat was read from
  logic                 h1_a, h2_a, h3_a, h1_b, h2_b, h3_b, h1_c, h2_c, h3_c;
  logic [BEAT_BITS-1:0] op_a, op_b, op_c;      // F's register operands, forwarded
  assign win_t2 = fs[LATENCY-2] ? ft[(LATENCY-2)*6 +: 6] + 6'd1 : 6'd0;
  assign win_t3 = fs[LATENCY-3] ? ft[(LATENCY-3)*6 +: 6] + 6'd1 : 6'd0;
  assign win_t4 = fs[LATENCY-4] ? ft[(LATENCY-4)*6 +: 6] + 6'd1 : 6'd0;
  assign win_c  = (win_t2 > win_t3)
                ? ((win_t2 > win_t4) ? win_t2 : win_t4)
                : ((win_t3 > win_t4) ? win_t3 : win_t4);
  always_ff @(posedge ap_clk) begin
    if (!ap_rst_n) win_q <= '0;
    else           win_q <= win_c;
  end
  always_ff @(posedge ap_clk) begin
    if (!ap_rst_n) begin
      fs <= '0; we1 <= 1'b0;
      fr <= '0; fq <= '0; ft <= '0;
    end else begin
      // the array's own line shifts on its enable, which on a
      // single-pass tile is every cycle; the look-ahead reads the
      // validity shadow only there
      if (al_rdy) fs <= {fs[LATENCY-2:0], al_valid};
      // ...and the row and flag enable each request fired with (R18)
      // shift on exactly that enable, so they are exact on EVERY tile:
      // cft_lanes' own line is LATENCY stages on in_ready and its
      // out_valid is the top one, which is what the retire reads them
      // beside. The retire needs them on a multi-pass tile as much as
      // on a single-pass one.
      if (al_rdy) begin
        fr <= {fr[(LATENCY-1)*WORDS-1:0], al_row};
        fq <= {fq[LATENCY-2:0], al_fen};
        ft <= {ft[(LATENCY-1)*6-1:0], al_tag};
      end
      we1 <= rf_we; wa1 <= rf_waddr; wd1 <= rf_wdata; wwe1 <= rf_wwe;
    end
  end
  generate
    if (FWD && LATENCY < 4) begin : g_fwd_latency
      $error("cft_seq: forwarding looks two cycles ahead along the array's validity line, formed a cycle before - LATENCY must be at least 4");
    end
  endgenerate
  // ---- the instruction fetch (revision 8, R8S) -----------------------
  //
  // rtl/cft_ifetch.sv, wired per its header ("The interface, for round
  // 2") and docs/studies/R8S-streaming.md, section 13. Its store is the
  // instruction memory this module held until revision 8, IMEM_D words
  // deep; past the store the unit streams the image through the read
  // port. Until revision 8 the memory's one read register stood here,
  // addressed pc + 1 in S_ISSUE and pc otherwise, with nxt_ok saying it
  // held imem[pc + 1]. The unit is addressed the same way and answers
  // the same cycle, so a program the store holds runs in today's cycles:
  //
  //   want/addr  the address the consumer needs next: pc + 1 in S_ISSUE
  //              (the next word, read under the issue), pc in S_FETCH,
  //              S_FETCH2 and the skip. LOW in a cycle that takes a word,
  //              because each consuming state presents the consumed word's
  //              own address, and a stream word asked for again after its
  //              pop is a jump to it. Low as well while a fault is ending
  //              the run, and while the main read engine has anything in
  //              flight: the fetch's span on the port opens only with that
  //              engine drained (verifier-VRD1's note on RD1). A setup
  //              burst still landing at a block's first want is a long
  //              one, which the abort has already ended the run for, so no
  //              fetch follows it - the abort drains it to its RLAST first.
  //   word/ok    the word at the address wanted last cycle. `ok` stands
  //              for what nxt_ok and `pc + 1 < n_insns` stood for: it is
  //              never high for an address at or past n_insns, and is low
  //              the cycle after a take, since a take wants nothing.
  //   take       S_FETCH2 and S_SKIP_D when ok; S_ISSUE's last unheld step
  //              when it continues with the word.
  //   cap        a REPEAT entering its body (S_DECODE), with pc + 1.
  //   quiesce    the block's end (S_DRAIN_SETUP), and the abort.
  //   init       the run's start.
  logic                if_init, if_ld_q, if_want, if_take, if_cap;
  logic                if_quiesce, if_fst;
  logic [63:0]         if_ldw_q;
  logic [PCW:0]        if_addr, if_cap_pc;
  logic [ADDR_W-1:0]   if_ibase_q;
  assign if_init    = (st == S_IDLE) && start;
  assign if_fst     = (st == S_FETCH) || (st == S_FETCH2) ||
                      (st == S_SKIP_F) || (st == S_SKIP_D) || (st == S_ISSUE);
  assign if_take    = (((st == S_FETCH2) || (st == S_SKIP_D)) && if_ok) ||
                      ((st == S_ISSUE) && !rd_hold && last_step && if_ok &&
                       !c_sld);
  assign if_want    = if_fst && !if_take && !abort_any &&
                      (rd_burst_left == 9'd0) && !rd_long_q && !rd_arvalid_q;
  assign if_addr    = (st == S_ISSUE) ? pc + (PCW+1)'(1) : pc;
  assign if_cap     = (st == S_DECODE) && !c_piped && (c_op == C_REPEAT) &&
                      (c_imm != 32'd0) && any_active;
  assign if_cap_pc  = pc + (PCW+1)'(1);
  assign if_quiesce = (st == S_DRAIN_SETUP) || (st == S_ABORT);

  cft_ifetch #(.BEAT_BITS(BEAT_BITS), .GW(32), .ADDR_W(ADDR_W),
               .STORE_D(IMEM_D), .STREAM_D(STREAM_D)) u_fetch (
      .clk(ap_clk), .rst_n(ap_rst_n),
      .init(if_init), .cfg_ibase(if_ibase_q), .cfg_n(h_ninsns[PCW:0]),
      .ld(if_ld_q), .ld_word(if_ldw_q),
      .want(if_want), .addr(if_addr), .word(if_word), .ok(if_ok),
      .take(if_take), .cap(if_cap), .cap_pc(if_cap_pc),
      .quiesce(if_quiesce), .idle(if_idle),
      .fault_rd(if_fault_rd), .fault_len(if_fault_len),
      .m_rd_araddr(if_araddr), .m_rd_arlen(if_arlen),
      .m_rd_arvalid(if_arvalid), .m_rd_arready(m_rd_arready),
      .m_rd_rdata(m_rd_rdata), .m_rd_rlast(m_rd_rlast),
      .m_rd_rresp(m_rd_rresp), .m_rd_rvalid(m_rd_rvalid),
      .m_rd_rready(if_rready));

  // The read port: the fetch's while it is not idle, the main read
  // engine's otherwise. The two never want it at once - the main engine
  // issues only in the setup states, where the fetch is idle (S_WAIT_B
  // and the abort wait for it, and its issue tests if_idle besides), and
  // the fetch issues only between a want and the next quiesce, init or
  // fault, and wants only with the main engine drained - so the select is
  // the fetch's own idle line. m_rd_sel is 0, the A master the image sits
  // behind, for every fetch burst: the main engine's last setup read may
  // have been stream b's or c's. A tile that does not stream has a fetch
  // that is always idle, and this is the read port it always had.
  assign m_rd_araddr  = if_idle ? rd_araddr_q  : if_araddr;
  assign m_rd_arlen   = if_idle ? rd_arlen_q   : if_arlen;
  assign m_rd_arvalid = if_idle ? rd_arvalid_q : if_arvalid;
  assign m_rd_rready  = if_idle ? rd_rready_q  : if_rready;
  assign m_rd_sel     = if_idle ? rd_sel_q     : 2'd0;
  logic [1:0]    ld_reg;
  logic [LB:0]   lane_cursor;
  logic [31:0]   slot_cursor;
  logic          drain_last;         // the element just packed was final
  // The deposit drain's pipeline (2026-09-14): one element a cycle
  // through the banks' two-cycle read, where it was three states an
  // element - measured on the card as ~40 ns a deposit a lane. Stage 0
  // issues a read and its tag (lane, slot, where in the beat it lands,
  // whether it closes the beat, whether it is the block's last); the
  // tag reaches stage 2 with the data. A beat that completes goes to
  // the write channel that cycle; while the channel cannot take it the
  // whole pipeline holds - address, tags AND the banks' read register
  // (g_db, above), because the held address is already the next
  // element's - so nothing in flight is lost.
  logic        dr_v0, dr_v1;
  logic [LB:0] dr_lane0, dr_lane1;
  logic [31:0] dr_slot0, dr_slot1;
  logic [5:0]  dr_fill0, dr_fill1;
  logic        dr_end0, dr_end1, dr_last0, dr_last1;
  logic        dr_issued;            // the last element has been issued
  logic [LB:0] dr_ilane;             // the issue cursors
  logic [31:0] dr_islot;
  logic [5:0]  dr_ifill;
  logic        dr_ilast, dr_iend;    // this issue closes the block / the beat
  logic [RFAW-1:0] zaddr;
  // The scratch wipe's cursor, and how far it has to go. One more bit
  // than the address, so "done" is a comparison the counter can reach
  // rather than a wrap.
  logic [SCRAW:0]  szaddr, szlimit;
  logic            z_first;
  // Slots this block has to wipe: every one if the program indexes,
  // otherwise the highest static slot it names and the slots the
  // scratch-out drain will read. Nothing above that is reachable, so
  // nothing above that is a value any program can distinguish - and a
  // program that never touches the scratch wipes nothing, which is
  // what keeps every existing bench's cycle count exactly where it
  // was.
  logic [SCRSW:0]  scr_wipe_slots;
  assign scr_wipe_slots = scr_all ? (SCRSW+1)'(SCRATCH_D)
                        : (scr_hi > h_nsout) ? scr_hi : h_nsout;

  // ---- revision 7: the wipe follows what was written -----------------
  //
  // An indexing program can reach every slot, so the rule above wipes
  // all SCRATCH_D of them every block: 4,096 cycles at 256 slots and
  // 32,768 at the U50's 2,048, whatever the program actually wrote. But
  // a slot nothing has written since it was last wiped is +0 already.
  // So each word bank keeps a DIRTY HIGH-WATER MARK, with the invariant
  //
  //     in bank b, every slot at or above scr_hwm[b] holds +0,
  //
  // for every beat, and a block wipes only as far as the highest mark:
  // what the previous block (or the previous run) wrote, and never more
  // than the rule above asks. An indexing program that writes below slot
  // 256 then pays at 2,048 slots what it pays at 256, or less.
  //
  // The marks OBSERVE the memory's write port - scr_we and scr_waddr,
  // whoever drives them: a store, the scratch-in preload, the gather -
  // and ignore the wipe's own writes (scr_wipe_q, set with them). A
  // write at slot s raises its bank's mark to s + 1 if it was below;
  // one comparator a bank, beside the write and never in front of it.
  // At reset every mark is SCRATCH_D, all dirty, so the first block
  // wipes what it can observe, as it always did; after that the marks
  // persist ACROSS runs, so a run's first block wipes what the last run
  // left. When a block's wipe has covered a bank's mark, that bank is
  // clean (scr_clean_go); a static program's shorter wipe can leave a
  // bank dirty above it, and then its mark stands.
  //
  // scr_dirty_q, the highest mark, is read only at S_BLK_SETUP, and is
  // formed as a two-stage tree - pairs of banks, then the pairs - so no
  // cycle carries more than two compares; a for-loop maximum would be
  // synthesised as a chain of seven. It settles three edges after a
  // write, and a block's last store is at least five cycles before the
  // next block's setup: HALT drains every store, then the count drain,
  // S_WAIT_B and S_NEXT_BLK all come first. A run's first block is
  // further still from the last run's.
  localparam int HWW   = SCRSW + 1;
  localparam int HWPR  = (WORDS > 1) ? WORDS / 2 : 1;
  logic [WORDS*HWW-1:0] scr_hwm;
  logic [HWPR*HWW-1:0]  scr_hwm_pair;
  logic [HWW-1:0]  scr_dirty_q;
  logic            scr_clean_go;     // the wipe just covered scr_wipe_bnd
  logic [HWW-1:0]  scr_wipe_bnd;     // how far this block's wipe goes
  logic [HWW-1:0]  scr_wipe_need;
  assign scr_wipe_need = (scr_dirty_q < scr_wipe_slots) ? scr_dirty_q
                                                        : scr_wipe_slots;

  // A wipe of more than one sub-array's slots is BROADCAST (second
  // send-back, verifier-R5 08:16:48). The marks start all dirty at a
  // reset, so the first indexing block after one had to wipe the whole
  // depth - 32,768 cycles at 2,048 slots, where every indexing block at
  // 256 had paid 4,096 - and so did the block after a program that
  // wrote up to the top. But a bank at more than 256 slots is SCR_NSUB
  // standalone arrays sharing one local address, so writing +0 at local
  // address a in all of them at once, for a in [0, SCR_SUB), clears the
  // WHOLE memory in SCR_SUB cycles. No block's wipe is then longer than
  // SCR_SUB = 4,096 cycles at NBEATS 16, at any depth: the cost of the
  // widest wipe revision 3 ever made. And after it the whole memory is
  // +0, so every mark is cleaned, not only those under the need.
  localparam int SUB_SLOTS = SCR_SUB >> NBSH;  // 256 at 4,096 and NBEATS 16
  logic scr_wipe_bc;
  assign scr_wipe_bc = (SCR_NSUB > 1) && (scr_wipe_need > HWW'(SUB_SLOTS));

  // A block that can observe no scratch slot - no STX/LDX, no static
  // STL/LDL, no scratch-out: scr_wipe_slots is 0 - loads none of its
  // scratch-in block, dense or gathered (second send-back, verifier-R5
  // 08:03:27). Nothing it runs reads a slot and the drain reads none, so
  // no preloaded value could reach an output; revision 3's S_ZERO did
  // the same by accident at n_scratch_in = 256, where an empty wipe cut
  // the preload's product short. The skipped block writes nothing, so
  // the marks stand. A block that observes SOME of a longer block still
  // loads all of it, as it always has (docs/SEQUENCER.md, revision 7).
  logic scr_sin_skip;
  assign scr_sin_skip = (scr_wipe_slots == '0);

  function automatic [HWW-1:0] hw_max_fn(input [HWW-1:0] a, input [HWW-1:0] b);
    hw_max_fn = (a > b) ? a : b;
  endfunction

  always_ff @(posedge ap_clk) begin
    if (!ap_rst_n) begin
      scr_hwm <= {WORDS{HWW'(SCRATCH_D)}};
    end else begin
      for (int b = 0; b < WORDS; b = b + 1) begin
        if (scr_clean_go) begin
          if (scr_hwm[b*HWW +: HWW] <= scr_wipe_bnd)
            scr_hwm[b*HWW +: HWW] <= '0;
        end else if (scr_we[b] && !scr_wipe_q &&
                     HWW'(scr_waddr[b*SCRAW + NBSH +: SCRSW]) >=
                     scr_hwm[b*HWW +: HWW]) begin
          scr_hwm[b*HWW +: HWW] <=
              HWW'(scr_waddr[b*SCRAW + NBSH +: SCRSW]) + HWW'(1);
        end
      end
    end
  end

  // The tree, by the beat's width: eight banks at 256 bits, four at
  // 128, two at the quarter tile's 64.
  generate
    if (WORDS == 8 || WORDS == 4 || WORDS == 2) begin : g_hwm_pairs
      always_ff @(posedge ap_clk) begin
        if (!ap_rst_n)
          scr_hwm_pair <= {HWPR{HWW'(SCRATCH_D)}};
        else
          for (int p = 0; p < HWPR; p = p + 1)
            scr_hwm_pair[p*HWW +: HWW] <=
                hw_max_fn(scr_hwm[(2*p)*HWW +: HWW],
                          scr_hwm[(2*p+1)*HWW +: HWW]);
      end
    end else if (WORDS == 1) begin : g_hwm_one
      always_ff @(posedge ap_clk)
        scr_hwm_pair <= (!ap_rst_n) ? HWW'(SCRATCH_D) : scr_hwm;
    end else begin : g_hwm_words
      $error("cft_seq: the scratch's dirty marks are built for 1, 2, 4 or 8 word banks");
    end
    if (HWPR == 4) begin : g_hwm_four
      always_ff @(posedge ap_clk)
        scr_dirty_q <= (!ap_rst_n) ? HWW'(SCRATCH_D)
            : hw_max_fn(hw_max_fn(scr_hwm_pair[0*HWW +: HWW],
                                  scr_hwm_pair[1*HWW +: HWW]),
                        hw_max_fn(scr_hwm_pair[2*HWW +: HWW],
                                  scr_hwm_pair[3*HWW +: HWW]));
    end else if (HWPR == 2) begin : g_hwm_two
      always_ff @(posedge ap_clk)
        scr_dirty_q <= (!ap_rst_n) ? HWW'(SCRATCH_D)
            : hw_max_fn(scr_hwm_pair[0*HWW +: HWW],
                        scr_hwm_pair[1*HWW +: HWW]);
    end else begin : g_hwm_single
      always_ff @(posedge ap_clk)
        scr_dirty_q <= (!ap_rst_n) ? HWW'(SCRATCH_D) : scr_hwm_pair;
    end
  endgenerate
  // The scratch-in preload's cursors: which lane and which of its
  // slots the next element belongs to. Two counters rather than a
  // division, exactly as the deposit drain carries lane_cursor and
  // slot_cursor instead of dividing an element index.
  logic [LB:0]     sin_lane;
  logic [SCRSW:0]  sin_slot;
  logic [31:0]     sin_left;

  logic [4:0]  flags_q;
  logic        dep_ovf_q;
  // Revision 4's R8. Sticky for the whole run, like the deposit
  // overflow it is modelled on, and reported the same way: what the
  // run computed is correct and reproducible, and this says a lane
  // asked for a slot that is not there.
  logic        scr_rng_q;
  // Revision 8's R24: a RAISE marked a lane - err[5], STATUS[6] through
  // cft_krnl. Sticky for the run, and never silenced by a quiet region: a
  // mark lost would keep an undecided last bit as though decided.
  logic        mark_q;
  logic        refuse_q;
  logic        rd_fault_q, wr_fault_q, len_fault_q;

  // ---- the abort's three decisions (revision 8; the contract's item 5) --
  //
  // A beat of the open burst that shows its length wrong: RLAST before the
  // beat ARLEN named, or none on it - the engine's rule, beat by beat. A
  // beat of a burst already known long (rd_long_q) is being drained and is
  // no reader's, and shows nothing more.
  logic rd_len_bad, rd_word_bad, img_beat_insn;
  // A beat THIS engine took: the fetch's own R beats are its, while it is
  // not idle (the port's RREADY is then the fetch's, below).
  assign rd_acc     = m_rd_rvalid && rd_rready_q && if_idle;
  assign rd_len_bad = rd_acc && !rd_long_q && (rd_burst_left != 9'd0) &&
                      (m_rd_rlast ? (rd_burst_left != 9'd1)
                                  : (rd_burst_left == 9'd1));
  // A beat the image parse absorbs holds an instruction's byte unless every
  // one of its 32 bytes is a constant still to come: the window holds
  // pw_have bytes of what follows, so the constants not yet in it are
  // kons_left * esz - pw_have bytes, and the beat is all constants only
  // when that is a whole beat or more. A beat is absorbed only when the
  // window is too empty to peel (S_IMG_PARSE's rule), so its bytes start
  // where the window's end. The bank pass and an image with no
  // instruction left hold none.
  assign img_beat_insn = (insn_left != 32'd0) &&
                         ((kons_left << esz_sh) < 32'(pw_have) + 32'd32);
  // A read fault on the header beat or an instruction's beat ends the run;
  // on any other beat it is data, and the run completes with err[0].
  assign rd_word_bad = rd_acc && (m_rd_rresp != 2'b00) &&
                       ((st == S_HDR_R) ||
                        ((st == S_IMG_PARSE) && !bank_phase && img_beat_insn));
  // Where the state machine may leave for S_ABORT: anywhere a run's reads
  // happen (the setup states - no write is open there and the issue pipe
  // is empty), between instructions (S_FETCH, S_FETCH2 and the skip, never
  // in the middle of an instruction's beats: S_DECODE and S_ISSUE finish
  // the instruction in hand, every word of which the memory vouched for),
  // at the block's end, and in the drains once no write burst is open or
  // committed - a committed burst delivers its beats first, from the drain
  // that was producing them.
  logic wr_quiet, drain_st, abort_safe, abort_go;
  assign wr_quiet   = (wr_burst_left == 9'd0) && !m_wr_awvalid &&
                      !wr_aw_open && !m_wr_wvalid;
  assign drain_st   = (st == S_DRAIN_RUN) || (st == S_CNT_SETUP) ||
                      (st == S_CNT_PACK) || (st == S_CNT_SEND) ||
                      (st == S_SO_SETUP) || (st == S_SO_RD) ||
                      (st == S_SO_W8) || (st == S_SO_PACK) ||
                      (st == S_SO_SEND) || (st == S_WAIT_B) ||
                      (st == S_LF_SETUP) || (st == S_LF_PACK) ||
                      (st == S_LF_SEND);
  assign abort_safe = !((st == S_IDLE) || (st == S_FIN) || (st == S_ABORT) ||
                        (st == S_DECODE) || (st == S_ISSUE)) &&
                      (!drain_st || wr_quiet);
  // The fetch's faults end the run through this same abort, and no
  // mechanism of their own (docs/ROADMAP.md, R8S): a fetch fault holds
  // the unit's `ok` low for ever, so the consumer stops at its next word
  // and the abort takes the machine from there. Sticky to the next init.
  assign abort_any  = abort_q || if_fault_rd || if_fault_len;
  assign abort_go   = abort_any && abort_safe;

  assign flags  = flags_q;
  // err[5] is R24's mark (STATUS[6] through cft_krnl), since revision 8.
  // err[0] and err[2] are the fetch's as well (revision 8): a read fault
  // or a wrong length on a fetch burst is STATUS[0] or STATUS[2], as on
  // any other read, and needs no bit of its own.
  assign err    = {mark_q, scr_rng_q, dep_ovf_q, len_fault_q | if_fault_len,
                   wr_fault_q, rd_fault_q | if_fault_rd};
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

  // The row the F stage's beat is working on - DEPOSIT, SETACT, the
  // stores, an LDX's range report, and the row an ALU or LDL beat fires
  // with - and the row an LDX beat fires with at H (revision 7, R18:
  // every one of those is an action of the pipe now, so each takes the
  // beat the pipe carries rather than the A stage's `bt`).
  //
  // The row retiring into the register file is NOT read from `active`
  // any more. Until R18 it was `row_act_fn(active, wb_bt)` - the mask
  // as it stood when the result came back - which was right only
  // because every code that moves the mask waited for the queue to
  // empty. A SETACT now narrows the mask while earlier results are
  // still in the array, so a result must write the lanes that were
  // active when it FIRED: the row rides beside the request (al_row)
  // and down a shadow of the array's validity line (fr, beside fs),
  // and the retire takes it from there.
  logic [WORDS-1:0]    bt_act, h_act, wb_act;
  logic [WORDS*CW-1:0] bt_cnt;
  assign bt_act = row_act_fn(active, pf_bt);
  assign h_act  = row_act_fn(active, ph_bt);
  assign wb_act = fr[LATENCY*WORDS-1 -: WORDS];
  assign bt_cnt = row_cnt_fn(dcnt, pf_bt);

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

  // ---- R24's RAISE, at F (revision 8) --------------------------------
  //
  // The F stage's beat is a RAISE: each active lane position's ra, as the
  // BANK read it - its ra waits under R14's landed rule, as SETACT's does,
  // so no forwarding mux stands in front of it - gives the low byte of the
  // lane's element: [4:0] the five flags in FLAGS's order, ORed into FLAGS
  // unless the beat was admitted quiet, and [7] the mark, set whatever the
  // region. [6:5] and every bit from 8 up are read by nothing: deposit
  // overflow and a strict fault are the machine's reports about itself,
  // and no program may claim one. A lane's low byte is the first byte of
  // the first word of its run (little end first), lane_slot_fn's geometry.
  // An inactive lane - masked, padding, dropped - raises and marks nothing.
  function automatic [7:0] lane_low8_fn(input [WORDS*32-1:0] rdata,
                                        input [2:0] posn,
                                        input [1:0] wsh);
    logic [7:0] r;
    begin
      r = '0;
      for (int w = 0; w < WORDS; w = w + 1)
        if (32'(w) == (32'({29'b0, posn}) << wsh))
          r = rdata[w*32 +: 8];
      lane_low8_fn = r;
    end
  endfunction
  // {mark, flags} over the row's active lane positions
  function automatic [5:0] raise_or_fn(input [WORDS*8-1:0] b,
                                       input [WORDS-1:0] act,
                                       input [3:0] lanes);
    logic [5:0] acc;
    begin
      acc = '0;
      for (int p = 0; p < WORDS; p = p + 1)
        if (p < 32'(lanes) && act[p])
          acc = acc | {b[p*8 + 7], b[p*8 +: 5]};
      raise_or_fn = acc;
    end
  endfunction
  logic [WORDS*8-1:0] ra_low8;
  generate
    for (genvar gr = 0; gr < WORDS; gr = gr + 1) begin : g_raise
      assign ra_low8[gr*8 +: 8] = lane_low8_fn(rf_rdata_a, 3'(gr), wpe_sh);
    end
  endgenerate
  logic [5:0] raise_or;
  logic       raise_go, raise_mk;
  logic [4:0] raise_fl, ret_fl;
  assign raise_or = raise_or_fn(ra_low8, bt_act, lpb);
  // Gated like every F-stage action (!issue_hold): the beat acts once.
  assign raise_go = !issue_hold && pf_v && pf_ctrl && (pf_op == C_RAISE);
  assign raise_fl = (raise_go && !pf_quiet) ? raise_or[4:0] : 5'b0;
  assign raise_mk = raise_go && raise_or[5];
  // ...and a landing result's flags, under its row and its tag (fq).
  assign ret_fl   = (al_ov && seq_live && fq[LATENCY-1]) ? wb_flags_or : 5'b0;

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
  // Forwarding's hits and merge (declared with the pipe, above): the
  // landing beat, the write in flight, the write that landed as B
  // sampled - younger first - each merged over what B read.
  assign h1_a = FWD && al_ov && ({q_rd0, wb_tag[NBSH-1:0]} == pf_aa);
  assign h1_b = FWD && al_ov && ({q_rd0, wb_tag[NBSH-1:0]} == pf_ab);
  assign h1_c = FWD && al_ov && ({q_rd0, wb_tag[NBSH-1:0]} == pf_ac);
  assign h2_a = FWD && rf_we && (rf_waddr == pf_aa);
  assign h2_b = FWD && rf_we && (rf_waddr == pf_ab);
  assign h2_c = FWD && rf_we && (rf_waddr == pf_ac);
  assign h3_a = FWD && we1 && (wa1 == pf_aa);
  assign h3_b = FWD && we1 && (wa1 == pf_ab);
  assign h3_c = FWD && we1 && (wa1 == pf_ac);
  function automatic logic [BEAT_BITS-1:0] fwd_fn(
      input logic h1, input logic h2, input logic h3,
      input logic [WORDS-1:0] m1, input logic [WORDS-1:0] m2,
      input logic [WORDS-1:0] m3,
      input logic [BEAT_BITS-1:0] d1, input logic [BEAT_BITS-1:0] d2,
      input logic [BEAT_BITS-1:0] d3, input logic [BEAT_BITS-1:0] base);
    logic [BEAT_BITS-1:0] r;
    begin
      r = base;
      for (int w = 0; w < WORDS; w = w + 1) begin
        if (h1)      r[w*32 +: 32] = m1[w] ? d1[w*32 +: 32] : base[w*32 +: 32];
        else if (h2) r[w*32 +: 32] = m2[w] ? d2[w*32 +: 32] : base[w*32 +: 32];
        else if (h3) r[w*32 +: 32] = m3[w] ? d3[w*32 +: 32] : base[w*32 +: 32];
      end
      fwd_fn = r;   // the name, not `return`: Yosys reads this file too
    end
  endfunction
  assign op_a = fwd_fn(h1_a, h2_a, h3_a, wb_wwe, rf_wwe, wwe1, al_d, rf_wdata, wd1, rf_rdata_a);
  assign op_b = fwd_fn(h1_b, h2_b, h3_b, wb_wwe, rf_wwe, wwe1, al_d, rf_wdata, wd1, rf_rdata_b);
  assign op_c = fwd_fn(h1_c, h2_c, h3_c, wb_wwe, rf_wwe, wwe1, al_d, rf_wdata, wd1, rf_rdata_c);

  // The FIRE (revision 7, R18): one request a step, of one of three
  // kinds - an ALU beat at F, an LDL beat at F with the value the
  // scratch read, an LDX beat at H with the value G read (R8's
  // suppressed banks +0). Never two in one step: gap_hold keeps every
  // other beat two steps behind an LDX's. Written as one request with
  // its fields selected here, so the forwarded operand op_x enters at
  // the LAST 2:1 level before al_x, exactly as it did before R18: every
  // other source - a constant, the loaded value - is chosen in parallel
  // from registered selects, and the forwarding path, the longest into
  // the request, is not made longer.
  logic                 fire_alu, fire_ldl, fire_ldx, fire_go;
  // R21: an augadd or augerr beat at F fires as an ALU beat does - ADD's
  // request with both operands from the file (ra on A, rb on C) and its
  // flag enable on - and the sideband says which half the pipe keeps.
  logic                 pf_aug, fire_aug;
  // R22: a stepped STX beat at F also fires its step into the array:
  // IADD(rb as the bank read it - an indexed code's rb waits for its
  // producer under R14's landed rule, so the bank has it - and the step at
  // the format's width), under the beat's row, with its flag enable off.
  // The internal IADD of a stepped LDX fires as an ALU beat with the step
  // as operand b. Both new sources are registers, chosen in parallel with
  // the others, so the forwarded operand still enters at the last level.
  logic                 fire_sstep;
  logic [BEAT_BITS-1:0] stp_vec;
  logic [BEAT_BITS-1:0] ld_val, alt_a, alt_b, alt_c;
  logic                 use_op_a, use_op_b, use_op_c;
  assign fire_alu = pf_v && !pf_ctrl;
  assign fire_ldl = pf_v && pf_ctrl && pf_op == C_LDL && !pf_fast;
  assign fire_ldx = ph_v && !ph_fast;
  assign pf_aug   = EN_AUGADD && pf_ctrl &&
                    (pf_op == C_AUGADD || pf_op == C_AUGERR);
  assign fire_aug = pf_v && pf_aug;
  assign fire_sstep = pf_v && pf_sstep;
  assign fire_go  = fire_alu || fire_ldl || fire_ldx || fire_aug ||
                    fire_sstep;
  // The step sign-extended to each lane's width: a lane's lowest word holds
  // the twelve bits sign-extended to 32, and its higher words the sign.
  function automatic [BEAT_BITS-1:0] stepv_fn(input [11:0] s,
                                              input [1:0] wsh);
    logic [BEAT_BITS-1:0] r;
    begin
      for (int w = 0; w < WORDS; w = w + 1)
        r[w*32 +: 32] = ((32'(w) & ((32'd1 << wsh) - 32'd1)) == 32'd0)
                      ? {{20{s[11]}}, s} : {32{s[11]}};
      stepv_fn = r;
    end
  endfunction
  assign stp_vec  = stepv_fn(pf_step, wpe_sh);
  assign ld_val   = zero_oor_fn(scr_rdata, ph_v ? ph_oor : '0);
  // A FAST load's beat (the send-back; the rule is with the admission):
  // its value, the same ld_val the array path would fire, goes into the
  // file through the retire's write port instead, this step, under the
  // row the beat fires with - bt_act at F for an LDL, h_act at H for an
  // LDX, which is exactly the array path's al_row. At most one a step:
  // an LDL at F and an LDX at H never meet (the gap), as their fires
  // never do. Gated like every F-stage action; no request can be
  // standing while a fast load reads or writes, since every array writer
  // ahead of it has landed and every one behind fires after it.
  assign fw_x   = !issue_hold && ph_v && ph_fast;
  assign fw     = fw_x || (!issue_hold && pf_v && pf_ctrl &&
                           pf_op == C_LDL && pf_fast);
  assign fw_bt  = fw_x ? ph_bt : pf_bt;
  assign fw_wwe = fw_x ? wb_wwe_fn(h_act, wpe_sh) : bt_wwe;
  assign fw_pop = fw && (fw_bt == 6'({1'b0, nb_blk} - 6'd1));
  assign alt_a    = fire_alu ? kq_a : fire_sstep ? rf_rdata_b : ld_val;
  // pf_istep is F's context, which an LDX firing at H does not have (F is
  // a bubble then, and its context whatever the bubble carried): it is
  // read only under fire_alu, F's own fire.
  assign alt_b    = (fire_sstep || (fire_alu && pf_istep)) ? stp_vec :
                    fire_alu ? kq_b : ld_val;
  assign alt_c    = fire_alu ? kq_c : '0;
  // augadd and augerr read no constant (a control code's read set is its
  // row in the decode table), so A and C are the file's, forwarded as an
  // ALU operand is; B is ADD's 1.0, which cft_opmux supplies.
  assign use_op_a = (fire_alu && !pf_ka) || fire_aug;
  assign use_op_b = fire_alu && !pf_kb;
  assign use_op_c = (fire_alu && !pf_kc) || fire_aug;
  // The same mask for the beat the SCRATCH states are working on. A
  // store is a register write for P3's purposes and a load writes rd,
  // so both are masked by exactly this - an all-inactive loop body
  // that stores is a no-op by construction, not by argument.
  logic [WORDS-1:0] bt_wwe;
  assign bt_wwe = wb_wwe_fn(bt_act, wpe_sh);

  // ---- reaching the scratch (revision 3, R4) --------------------------
  //
  // Three pieces, all built the way everything else in this module
  // reaches a lane: loops over CONSTANT indices with an equality test
  // picking the position, never a computed part-select of a wide
  // packed vector.
  //
  // 1. The SLOT each lane position wants. For STL and LDL it is
  //    imm[23:0], the same for every lane - sliced to SCRSW bits here
  //    rather than trusted, so a stream that bypassed the loader
  //    stays inside the memory instead of indexing past it, exactly
  //    as k_idx_* slices a constant index. For STX and LDX it is the
  //    low SCRSW bits of the lane's own `rb`, which arrives on the
  //    register file's B read port - the index as it stands, before
  //    any post-step (revision 8's R22: imm[11:0] of the pair is a
  //    step, applied after the access by an IADD in the array).
  //
  //    A lane's low 32 bits sit in the FIRST word of its run of
  //    words (position p occupies banks p << wpe_sh upward, little
  //    end first - drain_elem_fn is the same geometry read the other
  //    way), so no shift is involved anywhere: the slot is a slice of
  //    one 32-bit word, selected by an equality against a constant
  //    bank number.
  function automatic [SCRSW-1:0] lane_slot_fn(input [WORDS*32-1:0] rdata,
                                              input [2:0] posn,
                                              input [1:0] wsh);
    logic [SCRSW-1:0] r;
    begin
      r = '0;
      for (int w = 0; w < WORDS; w = w + 1)
        if (32'(w) == (32'({29'b0, posn}) << wsh))
          r = rdata[w*32 +: SCRSW];
      lane_slot_fn = r;
    end
  endfunction

  // Revision 4's R8: is this position's `rb` at or past the depth?
  //
  // lane_slot_fn takes the LOW SCRSW bits, so "past the depth" is
  // "any bit above those is set" - over every word the lane owns,
  // which is eight of them at fp256. An OR, not a comparator, and
  // exact because SCRATCH_D is a power of two, which g_scratch_pow2
  // asserts at elaboration. Same geometry as lane_slot_fn: a lane's
  // low 32 bits sit in the first word of its run.
  function automatic logic lane_oor_fn(input [WORDS*32-1:0] rdata,
                                       input [2:0] posn,
                                       input [1:0] wsh);
    logic r;
    logic [31:0] base;
    begin
      r = 1'b0;
      base = 32'({29'b0, posn}) << wsh;
      for (int w = 0; w < WORDS; w = w + 1) begin
        if (32'(w) == base)
          r = r | (|rdata[w*32 + SCRSW +: 32 - SCRSW]);
        else if (32'(w) > base && 32'(w) < base + (32'd1 << wsh))
          r = r | (|rdata[w*32 +: 32]);
      end
      lane_oor_fn = r;
    end
  endfunction

  // Detection is per POSITION; the write enables are per BANK, and
  // bank w serves position w >> wsh - the mapping scr_addr_fn uses.
  function automatic [WORDS-1:0] oor_banks_fn(input [WORDS-1:0] pos_oor,
                                              input [1:0] wsh);
    logic [WORDS-1:0] r;
    begin
      r = '0;
      for (int w = 0; w < WORDS; w = w + 1)
        for (int p = 0; p < WORDS; p = p + 1)
          if (32'(p) == (32'(w) >> wsh))
            r[w] = pos_oor[p];
      oor_banks_fn = r;
    end
  endfunction

  // A load still WRITES on a suppressed access - the model reads +0
  // rather than leaving the register alone, because a stale register
  // would make the answer depend on what the lane happened to hold.
  function automatic [WORDS*32-1:0] zero_oor_fn(input [WORDS*32-1:0] v,
                                                input [WORDS-1:0] banks);
    logic [WORDS*32-1:0] r;
    begin
      r = v;
      for (int w = 0; w < WORDS; w = w + 1)
        if (banks[w])
          r[w*32 +: 32] = 32'b0;
      zero_oor_fn = r;
    end
  endfunction

  // The F stage's beat (revision 7, R18): the scratch codes act in the
  // pipe now, so the slot is the one THAT beat carries - pf_slot for
  // the static forms, rb as the bank read it for the indexed ones -
  // and not `cur`'s, which has moved on to the next instruction by the
  // time a beat reaches F. rb is read from the BANK and not forwarded:
  // an indexed code's rb waits for its producer under R14's rule (the
  // beat has landed), which keeps the path from rb to the scratch
  // address the one it has always been, with no forwarding mux in
  // front of it.
  logic c_scr_idx;                       // the F stage's beat is STX/LDX
  assign c_scr_idx = pf_ctrl && (pf_op == C_STX || pf_op == C_LDX);
  logic [WORDS*SCRSW-1:0] scr_slot;      // the slot each position wants
  logic [WORDS-1:0]       scr_oor;       // ...and whether it exists
  logic [WORDS-1:0]       scr_oor_bk;    // the same, by bank
  generate
    for (genvar gsl = 0; gsl < WORDS; gsl = gsl + 1) begin : g_slot
      assign scr_slot[gsl*SCRSW +: SCRSW] =
          c_scr_idx ? lane_slot_fn(rf_rdata_b, 3'(gsl), wpe_sh)
                    : pf_slot;
    end
  endgenerate

  // Only the INDEXED forms, and only under the flag. A static STL or
  // LDL slot is in the IMAGE and was refused at load if it was past the
  // depth; an indexed one is data and cannot be. Without the flag an
  // out-of-range index is not an error at all - it is the modulo, which
  // is what every image built before revision 4 means.
  generate
    for (genvar goo = 0; goo < WORDS; goo = goo + 1) begin : g_oor
      assign scr_oor[goo] = c_scr_idx && scr_strict_q &&
                            lane_oor_fn(rf_rdata_b, 3'(goo), wpe_sh);
    end
  endgenerate
  assign scr_oor_bk = oor_banks_fn(scr_oor, wpe_sh);

  // ---- revision 8's R23: per-lane sticky flags -----------------------
  //
  // A byte a lane slot, BLK_LANES of them, addressed as `active` is ({beat,
  // position}, 1,024 flops at sixteen beats of eight positions, at every
  // format): [4:0] the five IEEE flags the lane raised outside every quiet
  // region (R24), in FLAGS's order; [5] its deposit overflowed; [6] its
  // indexed access fell past the depth under SCRATCH_STRICT; [7] a RAISE
  // marked it - STATUS[6:4]'s three reports one place up, lane by lane
  // (docs/SEQUENCER.md, R23). Sticky, cleared at each block's start with
  // the register file's valid bits, and read only by the drain after the
  // counts (S_LF_*), when the run asked (MODE[24], lf_en_q).
  //
  // Every term is the one the run's own reports take today, captured from
  // a REGISTERED copy a cycle late, so no R23 logic sits on today's paths
  // - the retire, the F stage's deposit path among them (docs/ROADMAP.md,
  // revision 8, R23: the margins). Two sources a cycle, each one beat's
  // row of positions:
  //   the retire: a landing beat's lane flags, under the row it fired with
  //     and its flag enable (fq: arithmetic, and not admitted quiet) -
  //     wb_flags_or's terms before it ORs them;
  //   F: a RAISE's ra[4:0] unless the beat is quiet and its ra[7], a
  //     DEPOSIT's overflow by position (bt_dep_ovf), and STX's and LDX's
  //     strict suppression by position (scr_oor), each under the beat's
  //     active row.
  // A lane the caller does not have - masked, or past n - is never active,
  // so its byte stays 0, and the drain does not write it.
  logic [BLK_LANES*8-1:0] lflags;
  logic                   lf_rv, lf_fv;
  logic [NBSH-1:0]        lf_rbeat, lf_fbeat;
  logic [WORDS*8-1:0]     lf_rbits, lf_fbits, lf_rbits_c, lf_fbits_c;
  logic                   lf_f_c;
  generate
    for (genvar gf = 0; gf < WORDS; gf = gf + 1) begin : g_lf
      logic here;          // the position exists at this format
      assign here = (32'(gf) < 32'(lpb));
      assign lf_rbits_c[gf*8 +: 8] =
          {3'b0, (here && wb_act[gf]) ? al_lf[gf*5 +: 5] : 5'b0};
      assign lf_fbits_c[gf*8 +: 8] = {
          raise_go && here && bt_act[gf] && ra_low8[gf*8 + 7],     // [7]
          lf_f_c && c_scr_idx && here && bt_act[gf] && scr_oor[gf],  // [6]
          lf_f_c && (pf_op == C_DEPOSIT) && bt_dep_ovf[gf],          // [5]
          (raise_go && !pf_quiet && here && bt_act[gf])
              ? ra_low8[gf*8 +: 5] : 5'b0};                          // [4:0]
    end
  endgenerate
  // an F-stage control beat acting this cycle (every F action's gate)
  assign lf_f_c = !issue_hold && pf_v && pf_ctrl;
  always_ff @(posedge ap_clk) begin
    lf_rv    <= al_ov && seq_live && fq[LATENCY-1];
    lf_rbeat <= wb_tag[NBSH-1:0];
    lf_rbits <= lf_rbits_c;
    lf_fv    <= lf_f_c;
    lf_fbeat <= pf_bt[NBSH-1:0];
    lf_fbits <= lf_fbits_c;
    if (!ap_rst_n || rf_clear)
      lflags <= '0;
    else
      for (int b = 0; b < NBEATS; b = b + 1)
        for (int q = 0; q < WORDS; q = q + 1)
          lflags[(b*WORDS + q)*8 +: 8] <= lflags[(b*WORDS + q)*8 +: 8] |
              ((lf_rv && 32'(lf_rbeat) == b) ? lf_rbits[q*8 +: 8]
                                                       : 8'b0) |
              ((lf_fv && 32'(lf_fbeat) == b) ? lf_fbits[q*8 +: 8]
                                                       : 8'b0);
  end

  // The drain's beat: BEAT_BYTES lanes' bytes, lane L at byte L - the block's
  // first byte in the beat. A block's lanes sit in slots (L >> lpb_sh) x
  // WORDS + (L mod lpb) - the dense index to {beat, position} - so the
  // select is written over CONSTANT candidates (the format, which beat of
  // the block, the block's offset in the beat), never a computed index into
  // the 1,024 flops: at 256 bits a byte has about eight candidates, where a
  // computed index would be a 128:1 multiplexer a byte. A block narrower
  // than a beat (fp256's sixteen lanes) starts at a multiple of its own
  // width within the beat, which is the only offset `off` takes.
  localparam int LFB = BEAT_BYTES;                          // lanes a beat
  localparam int LFK = (BLK_LANES + LFB - 1) / LFB;         // beats a block
  localparam int LFKW = (LFK > 1) ? $clog2(LFK) : 1;
  function automatic [BEAT_BITS-1:0] lf_beat_fn(input [BLK_LANES*8-1:0] lf,
                                                input [1:0] lsh,
                                                input [LFKW-1:0] k,
                                                input [5:0] off);
    logic [BEAT_BITS-1:0] r;
    int L, slot;
    begin
      r = '0;
      for (int f = 0; f < 4; f = f + 1)
        if (32'(lsh) == f)
          for (int kk = 0; kk < LFK; kk = kk + 1)
            if (32'(k) == kk)
              for (int o = 0; o < LFB; o = o + (NBEATS << f))
                if (32'(off) == o)
                  for (int j = 0; j < LFB; j = j + 1) begin
                    L = kk*LFB + j - o;
                    if (L >= 0 && L < (NBEATS << f)) begin
                      slot = (L >> f) * WORDS + (L & ((1 << f) - 1));
                      if (slot < BLK_LANES)
                        r[j*8 +: 8] = lf[slot*8 +: 8];
                    end
                  end
      lf_beat_fn = r;
    end
  endfunction
  // ...and its strobes: a byte for a lane below blk_n that the caller has
  // (mask_lane, dense by lane) - the counts' rule.
  function automatic [LFB-1:0] lf_strb_fn(input [BLK_LANES-1:0] ml,
                                          input [1:0] lsh,
                                          input [LFKW-1:0] k,
                                          input [5:0] off,
                                          input [LB:0] bn);
    logic [LFB-1:0] r;
    int L;
    begin
      r = '0;
      for (int f = 0; f < 4; f = f + 1)
        if (32'(lsh) == f)
          for (int kk = 0; kk < LFK; kk = kk + 1)
            if (32'(k) == kk)
              for (int o = 0; o < LFB; o = o + (NBEATS << f))
                if (32'(off) == o)
                  for (int j = 0; j < LFB; j = j + 1) begin
                    L = kk*LFB + j - o;
                    if (L >= 0 && L < (NBEATS << f) && L < BLK_LANES)
                      r[j] = (32'(L) < 32'(bn)) && ml[L];
                  end
      lf_strb_fn = r;
    end
  endfunction
  // The drain's cursor - the beat of the block being packed - and the
  // block's first byte in its first beat: the block starts at byte
  // blk_base of the 32-byte-aligned block, so its offset in a beat is
  // blk_base's low bits, nonzero only where a block is narrower than a beat.
  logic [LFKW-1:0] lf_k;
  logic [5:0]      lf_off;
  assign lf_off = 6'(blk_base[$clog2(LFB)-1:0]);

  // 2. The per-bank ADDRESS those slots imply, for the beat named.
  //    Bank w serves lane position w >> wsh, so it takes that lane's
  //    slot; the beat is the low NBSH bits, as it is in the register
  //    file's rf_waddr.
  function automatic [WORDS*SCRAW-1:0] scr_addr_fn(
                                         input [WORDS*SCRSW-1:0] slots,
                                         input [5:0] beat,
                                         input [1:0] wsh);
    logic [WORDS*SCRAW-1:0] r;
    logic [SCRSW-1:0]       s;
    begin
      r = '0;
      for (int w = 0; w < WORDS; w = w + 1) begin
        s = '0;
        for (int p = 0; p < WORDS; p = p + 1)
          if (32'(p) == (32'(w) >> wsh))
            s = slots[p*SCRSW +: SCRSW];
        r[w*SCRAW +: SCRAW] = SCRAW'({s, beat[NBSH-1:0]});
      end
      scr_addr_fn = r;
    end
  endfunction

  // ...and the same address for every bank, which is what a phase
  // that visits ONE lane at a time wants: the scratch-out drain and
  // the scratch-in preload both do, because their buffers are
  // lane-major.
  function automatic [WORDS*SCRAW-1:0] scr_flat_fn(input [SCRSW-1:0] slot,
                                                   input [5:0] beat);
    logic [WORDS*SCRAW-1:0] r;
    begin
      r = '0;
      for (int w = 0; w < WORDS; w = w + 1)
        r[w*SCRAW +: SCRAW] = SCRAW'({slot, beat[NBSH-1:0]});
      scr_flat_fn = r;
    end
  endfunction

  // 3. Placing ONE element into the word banks its lane owns, and the
  //    write enables that go with it - drain_elem_fn run backwards.
  //    The preload uses both; the four codes use only the second,
  //    because there the data is already a whole beat in lane order.
  function automatic [WORDS*32-1:0] place_elem_fn(input [255:0] v,
                                                  input [2:0] posn,
                                                  input [1:0] wsh);
    logic [WORDS*32-1:0] r;
    begin
      r = '0;
      for (int w = 0; w < WORDS; w = w + 1)
        for (int k = 0; k < WORDS; k = k + 1)
          if (k < (32'd1 << wsh) &&
              32'(w) == 32'({29'b0, posn} << wsh) + k)
            r[w*32 +: 32] = v[k*32 +: 32];
      place_elem_fn = r;
    end
  endfunction

  function automatic [WORDS-1:0] lane_wwe_fn(input [2:0] posn,
                                             input [1:0] wsh);
    logic [WORDS-1:0] e;
    begin
      e = '0;
      for (int w = 0; w < WORDS; w = w + 1)
        if ((32'(w) >> wsh) == 32'({29'b0, posn}))
          e[w] = 1'b1;
      lane_wwe_fn = e;
    end
  endfunction

  // The element the scratch-out drain is packing: the same selection
  // drain_elem_fn makes out of the deposit banks, with no "did this
  // lane reach this slot" question - every slot of the scratch has a
  // defined value, because the wipe gave it one.
  function automatic [255:0] scr_elem_fn(input [2:0] posn,
                                         input [WORDS*32-1:0] rdata,
                                         input [1:0] wsh);
    logic [255:0] v;
    begin
      v = '0;
      for (int w = 0; w < WORDS; w = w + 1)
        for (int src = 0; src < WORDS; src = src + 1)
          if (w < (32'd1 << wsh) &&
              src == 32'({29'b0, posn} << wsh) + w)
            v[w*32 +: 32] = rdata[src*32 +: 32];
      scr_elem_fn = v;
    end
  endfunction

  // The block's opening active mask: slot (b, p) belongs to a lane
  // the caller has iff the position exists at this format and the
  // lane's index within the block is below blk_n. Both the block's
  // start and ACTALL want exactly this, and ACTALL's contract is that
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
  // R17. The block's mask bits, DENSE by lane index within the block -
  // mask_lane[l] is the caller's bit for global lane blk_base + l -
  // and all ones for a run without a mask, so every expression below
  // is the one it was before the mask existed. Held for the whole
  // block: the fetch writes it at block setup and nothing else does.
  logic [BLK_LANES-1:0] mask_lane;
  // ...and the same bits addressed by SLOT, which is what the active
  // mask is addressed by: slot (b, p) is lane (b << lpb_sh) + p, the
  // expression blk_act_fn already uses for the same mapping.
  function automatic [BLK_LANES-1:0] mask_slot_fn(input [BLK_LANES-1:0] ml,
                                                  input [3:0] lanes,
                                                  input [1:0] lsh);
    logic [BLK_LANES-1:0] m;
    begin
      m = '0;
      for (int b = 0; b < NBEATS; b = b + 1)
        for (int p = 0; p < WORDS; p = p + 1)
          if ((p < 32'(lanes)) && (((32'(b) << lsh) + p) < BLK_LANES))
            m[b*WORDS + p] = ml[(32'(b) << lsh) + p];
      mask_slot_fn = m;
    end
  endfunction
  logic [BLK_LANES-1:0] blk_act;
  // The lanes THE CALLER HAS: the block's own lanes, and of those the
  // ones the mask keeps. Both readers of blk_act want exactly this -
  // the block's opening active mask and ACTALL, whose contract is
  // that it reactivates every lane the caller has and whose sentence
  // R17 completes ("a masked lane is not one the caller has") - so
  // the mask is applied HERE, once, and the two cannot drift apart.
  assign blk_act = blk_act_fn(blk_n, lpb, lpb_sh) &
                   mask_slot_fn(mask_lane, lpb, lpb_sh);

  // R19: the beats a lane the CALLER HAS sits in (blk_act: the block's
  // lanes, of those the ones the mask keeps). A beat outside the first
  // and last of them holds no lane that can ever be active - ACTALL
  // reactivates blk_act and nothing else - so its r0..r2 entries are
  // never read by an issued beat that writes anything, and the stream
  // load reads from the first such beat to the last, and not at all
  // when there is none. One burst still, so a masked beat between two
  // live ones is read: a second round trip would cost more than it
  // saves.
  logic [NBEATS-1:0] blk_live;
  generate
    for (genvar gk = 0; gk < NBEATS; gk = gk + 1) begin : g_blk_live
      assign blk_live[gk] = |blk_act[gk*WORDS +: WORDS];
    end
  endgenerate
  function automatic [5:0] last_set_fn(input [NBEATS-1:0] m);
    logic [5:0] r;
    begin
      r = 6'd0;
      for (int b = 0; b < NBEATS; b = b + 1)
        if (m[b])
          r = 6'(b);
      last_set_fn = r;
    end
  endfunction
  // Registered, for the path into the load's 64-bit address: blk_act
  // is fixed from the mask fetch (S_MSK_W) on, and S_ZERO lasts several
  // cycles between that and the first S_LD_GO.
  logic [5:0] ld_lo, ld_hi;
  always_ff @(posedge ap_clk) begin
    ld_lo <= first_from_fn(blk_live, 6'd0);
    ld_hi <= last_set_fn(blk_live);
  end

  // R17's fetch, the block's bits out of the beat that holds them.
  //
  // A beat is 256 bits and a mask bit is a lane, so ONE beat holds 256
  // consecutive lanes' bits at every format: the beat a block's bits
  // live in is `blk_base >> 8` and the block's first bit sits at
  // `blk_base[7:0]` inside it. A block is `blk_cap = NBEATS << lpb_sh`
  // lanes, at most 128 at NBEATS 16, and blk_base is a multiple of it -
  // so a block's bits NEVER straddle two beats and the fetch is one
  // single-beat read a block whatever the format. What makes that true
  // is the NBEATS guard above (1..16, a power of two): NBEATS << 3 is
  // the widest a block can be and 128 is at most half a beat.
  //
  // The block's bits are a SELECT, and the shape of the select is the
  // whole cost of this feature.
  //
  // `blk_base` is a multiple of the block's lane count, which is
  // `NBEATS << lpb_sh` and therefore a multiple of NBEATS at every
  // format. So a beat divides into `BEAT_BITS / NBEATS` slots of
  // NBEATS bits, a block always begins at a slot boundary, and the
  // block is `BLK_LANES / NBEATS` consecutive slots. Reading it that
  // way makes each one an INDEXED PART-SELECT of CONSTANT WIDTH - one
  // mux a slot, eight of them.
  //
  // The first version asked, for each of the sixteen positions and each
  // of the 128 lanes, whether `mbit == j * NBEATS`, and assigned one
  // bit under it. That is the same function and it elaborates to 2,048
  // conditional updates in a priority chain: V3 measured this module at
  // 28,626 cells and 22,911 $mux against 9,823 and 4,792 before the
  // mask existed, and stubbing this function's body alone accounted for
  // ~96% of the difference. A lane mask is worth a few muxes; it is not
  // worth a third of the sequencer.
  //
  // The `& (BEAT_BITS/NBEATS - 1)` on the slot index is not arithmetic:
  // it keeps every elaborated part-select inside the beat for the slots
  // a NARROW format's block does not have (at fp256 a block is one slot
  // and the other seven wrap). Nothing reads a lane at or past blk_n -
  // `blk_act_fn` zeroes those slots before the AND, the count drain
  // tests `cl < blk_n`, and neither element drain walks past it - so
  // what those slots hold is not a value any run can distinguish, for
  // the reason the scratch wipe's own comment gives about slots above
  // the program's reach.
  function automatic [BLK_LANES-1:0] mask_blk_fn(input [BEAT_BITS-1:0] beat,
                                                 input [7:0] mbit);
    logic [BLK_LANES-1:0] v;
    int slot;
    begin
      v = '0;
      slot = 32'(mbit) >> NBSH;
      for (int c = 0; c < BLK_LANES / NBEATS; c = c + 1)
        v[c*NBEATS +: NBEATS] =
            beat[((slot + c) & (BEAT_BITS/NBEATS - 1)) * NBEATS +: NBEATS];
      mask_blk_fn = v;
    end
  endfunction

  // Where THIS block's index table starts, for whichever block is
  // being gathered - written once, read twice in S_GTH_GO, so the
  // address the first read uses and the address the second table beat
  // is derived from cannot be two different expressions.
  logic [ADDR_W-1:0] gt_tbl_base;
  assign gt_tbl_base =
      gt_scr ? idx_si_q + ((sin_off >> esz_sh) << 2)
             : (ld_reg == 2'd0 ? idx_a_q
              : ld_reg == 2'd1 ? idx_b_q : idx_c_q) + (blk_base << 2);

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
  // The count drain's beat (2026-09-14): eight consecutive lanes'
  // counts, each from its own row and position, and a strobe per lane
  // that exists. A count is four bytes whatever the format, so a
  // 32-byte beat is eight lanes of counts at every precision - which
  // is why this is eight picks and not lpb.
  logic [BEAT_BITS-1:0] cnt_beat;
  logic [WORDS-1:0]     cnt_beat_ok;
  generate
    for (genvar gc = 0; gc < WORDS; gc = gc + 1) begin : g_cnt_beat
      logic [LB:0] cl;
      assign cl = lane_cursor + (LB+1)'(gc);
      assign cnt_beat[gc*32 +: 32] =
          32'(pick_cnt_fn(row_cnt_fn(dcnt, 6'(32'(cl) >> lpb_sh)),
                          3'(cl[2:0] & 3'(lpb - 4'd1))));
      // ...strobed where the lane exists AND the caller has it (R17):
      // a masked lane's count is not written and the caller's array
      // keeps whatever was in it, which is the same claim the deposit
      // drain makes about its slots one strobe along.
      assign cnt_beat_ok[gc] = (32'(cl) < 32'(blk_n)) &&
                               mask_lane[cl[LB-1:0]];
    end
  endgenerate
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
  // The element arriving at stage 2: its lane's count from its own row
  // and position (dcnt is stable through the drain), the data from the
  // banks, zero if the lane never reached the slot - drain_elem_fn as
  // before, fed from the tag instead of the cursors.
  logic [5:0]          pk_beat;
  logic [2:0]          pk_posn;
  logic [CW-1:0]       pk_cnt;
  logic [255:0]        pk_elem;
  logic [BEAT_BITS-1:0] pk_data;
  logic [WORDS*4-1:0]  pk_strb;
  assign pk_beat = 6'(32'(dr_lane1) >> lpb_sh);
  assign pk_posn = dr_lane1[2:0] & 3'(lpb - 4'd1);
  assign pk_cnt  = pick_cnt_fn(row_cnt_fn(dcnt, pk_beat), pk_posn);
  assign pk_elem = drain_elem_fn(pk_posn, dr_slot1, pk_cnt, db_rdata,
                                 wpe_sh);
  // the beat with this element placed at its slot (whole words: every
  // format's element is a whole number of them)
  // R17: a masked lane's element keeps its POSITION in the stream and
  // loses its STROBE. The beat still carries it - the deposit window's
  // layout is n * max_deposits whatever the mask says, and a drain
  // that packed only the active lanes would move every later lane's
  // slot - so what "not written" means on the bus is a beat whose
  // bytes for that element are not strobed, and the caller's buffer
  // keeps what it held. Taken from mask_lane and not from the active
  // bit: an active bit is cleared by SETACT too, and a lane that
  // converged is a lane the caller HAS, whose slots are written.
  logic dr_keep1;
  assign dr_keep1 = mask_lane[dr_lane1[LB-1:0]];
  always_comb begin
    pk_data = as_data;
    pk_strb = as_strb;
    for (int w = 0; w < WORDS; w = w + 1)
      if ((32'(w) >> wpe_sh) == (32'(dr_fill1) >> esz_sh)) begin
        pk_data[w*32 +: 32] =
          pk_elem[(32'(w) & ((32'd1 << wpe_sh) - 32'd1)) * 32 +: 32];
        pk_strb[w*4 +: 4] = dr_keep1 ? 4'hf : 4'h0;
      end
  end
  // The open burst's beats left AFTER this cycle's acceptance, if any:
  // a beat presented in the cycle the previous one is taken must take
  // its WLAST - and its right to go at all - from the count the master
  // is about to have (AXI4 A3.4.1; the unit bench's RAM asserts it).
  // Every send site below uses this and nothing uses wr_burst_left
  // directly for a beat's WLAST any more.
  logic [8:0] wr_after;
  assign wr_after = wr_burst_left -
                    ((m_wr_wvalid && m_wr_wready) ? 9'd1 : 9'd0);
  // hold everything while a completed beat cannot leave
  assign dr_stall = dr_v1 && dr_end1 &&
                    !((!m_wr_wvalid || m_wr_wready) && wr_after != 0);
  // what the next issue closes
  assign dr_ilast = (32'(dr_ilane) == 32'(blk_n) - 1) &&
                    (dr_islot == h_maxdep - 1);
  assign dr_iend  = ({1'b0, dr_ifill} + {1'b0, esz} == 7'(BEAT_BYTES)) ||
                    dr_ilast;

  // ...and the same for the scratch-out drain, which visits (lane,
  // slot) in the same order and reads the scratch instead of the
  // deposit banks. No "did this lane reach this slot" question here:
  // every slot the drain reads was given a value by the wipe or by
  // the program.
  logic [255:0] scr_out_elem;
  assign scr_out_elem = scr_elem_fn(dc_posn, scr_rdata, wpe_sh);


  // R23's drain beat and its strobes (above), as continuous assigns for
  // the reason rd_bl's is one (an Icarus livelock under always_comb), and
  // here because they read mask_lane; S_LF_PACK registers them.
  logic [BEAT_BITS-1:0] lf_beat;
  logic [LFB-1:0]       lf_strb;
  assign lf_beat = lf_beat_fn(lflags, lpb_sh, lf_k, lf_off);
  assign lf_strb = lf_strb_fn(mask_lane, lpb_sh, lf_k, lf_off, blk_n);

  // ==== the machine ====================================================
  always_ff @(posedge ap_clk) begin
    if (!ap_rst_n) begin
      st <= S_IDLE;
      done <= 1'b0; refuse_q <= 1'b0;
      flags_q <= '0; dep_ovf_q <= 1'b0; scr_rng_q <= 1'b0;
      rd_fault_q <= 1'b0; wr_fault_q <= 1'b0; len_fault_q <= 1'b0;
      rd_arvalid_q <= 1'b0; rd_rready_q <= 1'b0; rd_sel_q <= 2'd0;
      rd_araddr_q <= '0; rd_arlen_q <= '0;
      m_wr_awvalid <= 1'b0; m_wr_wvalid <= 1'b0; m_wr_bready <= 1'b0;
      al_valid <= 1'b0; rf_we <= 1'b0;
      db_we <= '0;
      rd_stream_on <= 1'b0; wr_stream_on <= 1'b0;
      rd_beats_left <= '0; rd_burst_left <= '0;
      rd_long_q <= 1'b0; abort_q <= 1'b0;
      wr_beats_left <= '0; wr_burst_left <= '0;
      wr_aw_open <= 1'b0; wr_bresp_left <= '0;
      lane_cursor <= '0; slot_cursor <= '0;
      pc <= '0; bt <= '0; wb_bt <= '0; lp_sp <= '0; q_n <= '0;
      pb_v <= 1'b0; pf_v <= 1'b0;
      if_ld_q <= 1'b0; if_ldw_q <= '0; if_ibase_q <= '0;
      pg_v <= 1'b0; ph_v <= 1'b0;
      pb_fast <= 1'b0; pf_fast <= 1'b0; pg_fast <= 1'b0; ph_fast <= 1'b0;
      c_fast <= 1'b0; q_f0 <= 1'b0; q_f1 <= 1'b0; q_f2 <= 1'b0;
      c_quiet <= 1'b0; pb_quiet <= 1'b0; pf_quiet <= 1'b0;
      c_istep <= 1'b0; c_sld <= 1'b0;
      pb_step <= '0; pf_step <= '0;
      pb_sstep <= 1'b0; pf_sstep <= 1'b0; pb_istep <= 1'b0; pf_istep <= 1'b0;
      qdepth <= '0; mark_q <= 1'b0;
      al_row <= '0; al_fen <= 1'b0; al_tag <= '0; al_aug <= 2'd0;
      pf_aa <= '0; pf_ab <= '0; pf_ac <= '0;
      dep_v_a <= 1'b0; dep_v_b <= 1'b0; dep_v_c <= 1'b0;
      // The constant bank is read unconditionally on every cycle, so
      // the instruction word that supplies its three addresses must
      // start defined; an X index into a memory is a simulator
      // question nobody should have to answer.
      cur <= '0;
      blk_base <= '0; active <= '0; dcnt <= '0;
      in_off <= '0; dep_off <= '0;
      sin_off <= '0; sout_off <= '0;
      rd_addr <= '0; rd_sel <= 2'd0; wr_addr <= '0;
      idx_a_q <= '0; idx_b_q <= '0; idx_c_q <= '0; idx_si_q <= '0;
      idx_en_q <= '0;
      // All ones, not zero: mask_lane is ANDed into the lanes the
      // caller has, so its idle value has to be the one that says
      // "every lane", and a run without a mask never writes it.
      mask_q <= '0; mask_en_q <= 1'b0; mask_lane <= {BLK_LANES{1'b1}};
      lf_q <= '0; lf_en_q <= 1'b0; lf_k <= '0;
      gt_tbl <= '0; gt_have <= '0; gt_left <= '0; gt_taddr <= '0;
      gt_base <= '0; gt_idx <= '0; gt_scr <= 1'b0; gt_beat <= '0;
      gt_pos <= '0; gt_lane <= '0; gt_slot <= '0;
      bank_phase <= 1'b0; bank_ext_q <= 1'b0;
      bank_q <= '0; sin_q <= '0; sout_q <= '0;
      scr_we <= '0; scr_raddr <= '0;
      scr_wipe_q <= 1'b0; scr_clean_go <= 1'b0; scr_wipe_bnd <= '0;
      scr_bcast <= 1'b0;
      scr_io_q <= 1'b0; scr_hi <= '0; scr_all <= 1'b0; rd_need <= '0;
      scr_strict_q <= 1'b0;
      h_nsin <= '0; h_nsout <= '0;

    end else begin
      done <= 1'b0;
      if_ld_q <= 1'b0;
      // A request stands until the array takes it; the issue state
      // re-asserts it for the next beat in the same cycle it is taken.
      if (!issue_hold) al_valid <= 1'b0;
      rf_we <= 1'b0;
      db_we <= '0;
      scr_we <= '0;
      scr_wipe_q <= 1'b0;
      scr_clean_go <= 1'b0;

      // ---- read channel: one burst in flight --------------------------
      //
      // The open burst ends at its RLAST, whatever its length (revision 8,
      // the abort). A SHORT burst - RLAST before the beat ARLEN named - is
      // over at that RLAST, so its count is zeroed there; until revision 8
      // it stayed above zero, no next burst was ever issued and the read
      // waited for ever. A LONG one - no RLAST on that beat - is flagged on
      // it, and rd_long_q drains the rest to its RLAST; until revision 8
      // those beats were taken as a later read's data. Either ends the run
      // (abort_q, below), as a read fault on the header or an instruction
      // does: from the next cycle no burst is issued, and S_ABORT drains
      // what is in flight.
      if (rd_arvalid_q && m_rd_arready && if_idle)
        rd_arvalid_q <= 1'b0;
      if (rd_acc) begin
        if (m_rd_rresp != 2'b00) rd_fault_q <= 1'b1;
        if (rd_long_q) begin
          if (m_rd_rlast) rd_long_q <= 1'b0;
        end else if (rd_burst_left != 0) begin
          rd_burst_left <= m_rd_rlast ? 9'd0 : rd_burst_left - 9'd1;
          if (rd_len_bad) len_fault_q <= 1'b1;
          if (!m_rd_rlast && rd_burst_left == 1) rd_long_q <= 1'b1;
        end
      end
      if (rd_len_bad || rd_word_bad)
        abort_q <= 1'b1;
      if (rd_stream_on && !rd_arvalid_q && rd_burst_left == 0 && if_idle &&
          !rd_long_q && !abort_any && rd_beats_left != 0) begin
        rd_araddr_q   <= rd_addr;
        rd_sel_q      <= rd_sel;
        rd_arlen_q    <= rd_bl;
        rd_arvalid_q  <= 1'b1;
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
      // No new write burst once the run is ending on a fault (the abort): a
      // burst already committed still delivers its beats, from the drain
      // producing them, and the drain stops at the next burst's AW.
      if (wr_stream_on && !m_wr_awvalid && !wr_aw_open &&
          wr_burst_left == 0 && wr_beats_left != 0 && !abort_any) begin
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

      // ---- R16: one gathered element lands ---------------------------
      //
      // Outside the case because two states produce one, and after the
      // rf_we / scr_we defaults above because it asserts them. The
      // window advances here too, so an entry is consumed exactly
      // where its element is written and the two cannot get out of
      // step.
      if (gt_take) begin
        gt_tbl  <= {32'b0, gt_tbl[BEAT_BITS-1:32]};
        gt_have <= gt_have - 4'd1;
        gt_left <= gt_left - 32'd1;
        if (gt_scr) begin
          // The scratch takes one element at a time, lane-major, at
          // the position its lane owns - S_SIN_PARSE's write, reached
          // by a different road.
          scr_we    <= lane_wwe_fn(gt_lane[2:0] & 3'(lpb - 4'd1),
                                   wpe_sh);
          scr_waddr <= scr_flat_fn(gt_slot[SCRSW-1:0],
                                   6'(32'(gt_lane[LB-1:0]) >> lpb_sh));
          scr_wdata <= place_elem_fn(gt_val,
                                     gt_lane[2:0] & 3'(lpb - 4'd1),
                                     wpe_sh);
          if ((gt_slot + (SCRSW+1)'(1)) >= h_nsin) begin
            gt_slot <= '0;
            gt_lane <= gt_lane + 1;
          end else
            gt_slot <= gt_slot + (SCRSW+1)'(1);
        end else begin
          // A stream's register entry is a whole beat, so elements are
          // packed until the beat closes. The positions are disjoint,
          // so the assembly is an OR and needs no strobes.
          gt_beat <= gt_beat |
                     BEAT_BITS'(place_elem_fn(gt_val, gt_pos, wpe_sh));
          if (gt_flush) begin
            rf_we    <= 1'b1;
            rf_waddr <= {3'b0, ld_reg, bt[NBSH-1:0]};
            rf_wdata <= gt_beat |
                        BEAT_BITS'(place_elem_fn(gt_val, gt_pos, wpe_sh));
            // Every word, as S_LD_STREAM writes every word: a beat's
            // padding positions are +0 here rather than whatever the
            // caller's buffer held past n, which is the one place a
            // gathered block is not merely the dense block reordered.
            // No lane the caller has can read them.
            rf_wwe   <= {WORDS{1'b1}};
            gt_beat  <= '0;
            gt_pos   <= '0;
            bt       <= bt + 1;
          end else
            gt_pos <= gt_pos + 3'd1;
        end
      end

      // ---- the abort takes over at its next safe point -----------------
      //
      // Exclusive of every state's own arm: in the cycle the machine leaves
      // for S_ABORT nothing a state would have done is done - no refusal
      // decided from a header beat the memory faulted, no burst set up, no
      // drain begun. The fault's own beat was consumed by its state's arm
      // the cycle before, as any beat is; abort_q is registered at that
      // edge. No new read is issued from then on (the read channel's issue
      // tests abort_q), and S_ABORT raises RREADY for the burst in flight.
      if (abort_go) begin
        st <= S_ABORT;
        rd_stream_on <= 1'b0;
        rd_beats_left <= '0;
        rd_rready_q <= 1'b0;
      end else
      case (st)
        // --------------------------------------------------------------
        S_IDLE: begin
          if (start) begin
            abort_q <= 1'b0;
            prec_q <= cfg_prec[1:0];
            n_q <= cfg_n; a_q <= cfg_a; b_q <= cfg_b; c_q <= cfg_c;
            d_q <= cfg_d; prog_q <= cfg_prog; cnt_q <= cfg_cnt;
            bank_q <= cfg_bank;
            sin_q <= cfg_sin; sout_q <= cfg_sout;
            idx_a_q <= cfg_idx_a; idx_b_q <= cfg_idx_b;
            idx_c_q <= cfg_idx_c; idx_si_q <= cfg_idx_si;
            idx_en_q <= cfg_indexed;
            // R17. mask_lane goes back to all ones at every start, so
            // a masked run cannot leave a previous run's bits behind
            // for an unmasked one - the register file's valid bits and
            // the scratch wipe make the same promise about state that
            // outlives a run, and for the same reason.
            mask_q <= cfg_mask; mask_en_q <= cfg_mask_en;
            lf_q <= cfg_lflags; lf_en_q <= cfg_lflags_en;
            mask_lane <= {BLK_LANES{1'b1}};
            flags_q <= '0; dep_ovf_q <= 1'b0; scr_rng_q <= 1'b0;
            mark_q <= 1'b0;
            refuse_q <= 1'b0;
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
          rd_rready_q <= 1'b1;
          st <= S_HDR_R;
        end
        S_HDR_R: begin
          if (rd_acc) begin
            // 256'() rather than [255:0]: the beat is BEAT_BITS wide, and a
            // select past its top does not elaborate on a narrow tile.
            hdr_q <= 256'(m_rd_rdata);
            rd_rready_q <= 1'b0;
            rd_stream_on <= 1'b0;
            st <= S_CHECK;
          end
        end

        S_CHECK: begin
          h_ninsns  <= hdr_q[95:64];
          h_nconsts <= hdr_q[127:96];
          h_maxdep  <= hdr_q[159:128];
          // The header's reserved[0] is `flags` since revision 2, and
          // bit 0 is BANK_EXT: the image carries no constant section
          // and the constants come from BANK_PTR instead. Bit 1 is
          // SCRATCH_IO since revision 3, and it is what makes the
          // header's SECOND word mean something.
          bank_ext_q <= hdr_q[192];
          scr_io_q   <= hdr_q[193];
          // Bit 2 is SCRATCH_STRICT since revision 4: an indexed
          // access at or past the depth is REPORTED rather than
          // reduced modulo it. With the bit clear the modulo
          // stands, so every image built before revision 4 keeps
          // its meaning exactly.
          scr_strict_q <= hdr_q[194];
          // scratch_io: [15:0] slots in, [31:16] slots out. Latched
          // as zero when the flag is clear, so nothing downstream has
          // to ask twice - and the check below has already refused a
          // non-zero word in that case.
          h_nsin  <= hdr_q[193] ? (SCRSW+1)'(hdr_q[239:224]) : '0;
          h_nsout <= hdr_q[193] ? (SCRSW+1)'(hdr_q[255:240]) : '0;
          // one block's deposit window: BLK_BYTES of input lanes
          // times max_deposits slots each
          dep_stride <= ADDR_W'({32'b0, hdr_q[159:128]} << BLK_SH);
          sin_stride  <= hdr_q[193]
                       ? ADDR_W'({48'b0, hdr_q[239:224]} << BLK_SH) : '0;
          sout_stride <= hdr_q[193]
                       ? ADDR_W'({48'b0, hdr_q[255:240]} << BLK_SH) : '0;
          // The two words above the precision, checked. A 0x600 tile
          // checked NEITHER, which is exactly why BANK_EXT needs a
          // CAPS bit and not only a header flag: that tile would read
          // the constants out of an image that has none. This one
          // refuses any flag bit it does not implement, a scratch
          // count past the depth, and a non-zero scratch_io word with
          // the flag clear - the last of which is what makes a
          // revision-2 tile the guard for SCRATCH_IO, and what makes
          // an image built for a LATER revision get thrown back here
          // rather than half-understood.
          if (hdr_q[31:0] != 32'h5054_4643 || hdr_q[63:32] != 32'd1 ||
              hdr_q[191:160] != {30'b0, prec_q} ||
              hdr_q[95:64] > STREAM_D || hdr_q[127:96] > KMEM_D ||
              hdr_q[159:128] > MAXD ||
              hdr_q[223:195] != 29'b0 ||
              (!hdr_q[193] && hdr_q[255:224] != 32'b0) ||
              // 32'(): both counts are SIXTEEN-bit halves of one word,
              // so the comparison is widened from the slice's width
              // rather than left to the tool - the fixed pad width
              // revision 2's Verilator gate caught in this same file
              // was exactly this shape counted out by hand.
              (hdr_q[193] && (32'(hdr_q[239:224]) > SCRATCH_D ||
                              32'(hdr_q[255:240]) > SCRATCH_D)) ||
              // MODE[22] with no scratch block to gather INTO. R16's
              // other three bits always have somewhere to go - the
              // three streams exist on every run - but the block's
              // table indexes a block this image does not declare, so
              // the bit selects nothing. A MODE bit this run cannot
              // honour is REFUSED and never ignored, which is the rule
              // the whole guard exists for: taking S_ZERO's
              // h_nsin == 0 path and saying nothing would leave a host
              // believing its table had been read. The library refuses
              // it first, by name (program.c's seq_check_round2), and
              // this is the second line of the same defence for an
              // image that reached the tile another way.
              //
              // From the header's own bits and not from h_nsin, which
              // is being assigned in this same block: the two would be
              // one cycle apart and the refusal would read the
              // PREVIOUS run's count.
              (idx_en_q[3] &&
               (!hdr_q[193] || hdr_q[239:224] == 16'b0))) begin
            refuse_q <= 1'b1;
            st <= S_FIN;
          end else if (hdr_q[192])
            st <= S_BNK_GO;
          else
            st <= S_IMG_GO;
        end

        // ---- the per-run constant bank (BANK_EXT) --------------------
        //
        // One pass of the same parser, pointed at BANK_PTR with the
        // instruction count set to zero: the bank is laid out exactly
        // as an image's constant section is - dense, format-width,
        // little-endian - which is what lets FETCH read one the way it
        // reads the other rather than growing a second parser. The
        // instructions then arrive in a second pass from cfg_prog + 32,
        // where an image without a constant section keeps them.
        S_BNK_GO: begin
          rd_addr <= bank_q;
          rd_sel  <= 2'd0;
          rd_beats_left <= ((h_nconsts << esz_sh) + 32'd31) >> 5;
          rd_stream_on <= 1'b1;
          kons_left <= h_nconsts;
          insn_left <= '0;
          kons_i <= '0; insn_i <= '0;
          pw <= '0; pw_have <= '0;
          bank_phase <= 1'b1;
          rd_rready_q <= 1'b1;
          st <= S_IMG_PARSE;
        end

        // ---- constants + instructions: dense byte stream -------------
        S_IMG_GO: begin
          rd_addr <= prog_q + 32;
          // Where instruction 0 is, for the fetch's stream (revision 8):
          // the section starts at byte 32, or past the constants an
          // image without BANK_EXT carries. 4-byte aligned, not always
          // 8 (the unit's realigner takes the granule). Stable from
          // here to the run's end.
          if_ibase_q <= prog_q + 64'd32 +
                        (bank_ext_q ? 64'd0 : (64'(h_nconsts) << esz_sh));
          rd_sel  <= 2'd0;
          // Under BANK_EXT the constants have already been read from
          // the bank, so the image is instructions alone. The bytes are
          // summed in 64 bits: n_insns x 8 passes 32 bits from 2^29
          // instructions, and the capacity guard allows 2^30 (verifier-
          // VC12, 2026-10-05); the beats, at most 2^28 + 512, fit 32.
          rd_beats_left <= 32'(
            ((bank_ext_q ? 64'd0 : (64'(h_nconsts) << esz_sh))
             + (64'(h_ninsns) << 3) + 64'd31) >> 5);
          rd_stream_on <= 1'b1;
          kons_left <= bank_ext_q ? 32'd0 : h_nconsts;
          insn_left <= h_ninsns;
          // Both cursors reset, as they always were. Under BANK_EXT
          // kons_left is zero so the constant arm never runs again in
          // this fetch and kons_i is simply unused; the bank pass
          // already wrote every entry it was going to.
          kons_i <= '0; insn_i <= '0;
          pw <= '0; pw_have <= '0;
          bank_phase <= 1'b0;
          // What the stream about to arrive can reach in the scratch,
          // reset before it is scanned.
          scr_hi <= '0; scr_all <= 1'b0; rd_need <= '0;
          rd_rready_q <= 1'b1;
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
              kmem[kons_i[KAW-1:0]] <= kbroad(256'(pw) &
                                   ~(~256'b0 << ({26'b0, esz} << 3)));
            pw <= pw >> ({26'b0, esz} << 3);
            pw_have <= pw_have - {1'b0, esz};
            kons_i <= kons_i + 1;
            kons_left <= kons_left - 1;
            rd_rready_q <= ((pw_have - {1'b0, esz}) < kons_room) &&
                           !(kons_left == 1 && insn_left == 0);
          end else if (kons_left == 0 && insn_left != 0 &&
                       pw_have >= 7'd8) begin
            // Into the fetch's store (revision 8): the unit keeps the
            // first IMEM_D of them, in order, and this scan still reads
            // every one. Registered, so the store's write is a cycle
            // behind the parse; nothing reads the store before the
            // block's first request, many cycles on.
            if_ld_q  <= 1'b1;
            if_ldw_q <= pw[63:0];
            // ...and, on the way past, how far into the scratch this
            // instruction can reach. The per-block wipe is sized from
            // the answer, so a program that never touches the scratch
            // pays nothing for it and one that only uses slot 3 wipes
            // four. pw[31] is `ctrl`, pw[7:0] the code, and pw[55:32]
            // the static slot - sliced to SCRSW bits here rather than
            // trusted, exactly as k_idx_* slices a constant index: the
            // loader has already refused a slot past the depth, and a
            // stream that bypassed it must still stay inside the
            // memory.
            if (pw[31] && (pw[7:0] == C_STL || pw[7:0] == C_LDL) &&
                (SCRSW+1)'(pw[32 +: SCRSW]) >= scr_hi)
              scr_hi <= (SCRSW+1)'(pw[32 +: SCRSW]) + (SCRSW+1)'(1);
            if (pw[31] && (pw[7:0] == C_STX || pw[7:0] == C_LDX))
              scr_all <= 1'b1;
            // ...and which operand streams it reads. The register
            // fields are {imm[25..27], the 4-bit field} since revision
            // 2; a control code reads ra (DEPOSIT, SETACT, STL, STX,
            // RAISE, and R21's AUGADD and AUGERR) or rb (STX, LDX, and
            // R21's two) and never rc. A stream read only through one of
            // them would otherwise not be loaded, and read +0.
            //
            // `op_reads` gates each field by what the OPCODE consumes,
            // for the reason its own comment gives at length: through a
            // table, a stream marked by a defaulted field costs the
            // whole table and a round trip an entry.
            if (!pw[31]) begin
              if (pw_reads[0] &&
                  !pw[27] && {pw[57], pw[15:12]} < 5'd3)
                rd_need[pw[13:12]] <= 1'b1;
              if (pw_reads[1] &&
                  !pw[28] && {pw[58], pw[19:16]} < 5'd3)
                rd_need[pw[17:16]] <= 1'b1;
              if (pw_reads[2] &&
                  !pw[29] && {pw[59], pw[23:20]} < 5'd3)
                rd_need[pw[21:20]] <= 1'b1;
            end else begin
              if ((pw[7:0] == C_DEPOSIT || pw[7:0] == C_SETACT ||
                   pw[7:0] == C_STL || pw[7:0] == C_STX ||
                   pw[7:0] == C_RAISE || aug_fn(pw[63:0])) &&
                  {pw[57], pw[15:12]} < 5'd3)
                rd_need[pw[13:12]] <= 1'b1;
              if ((pw[7:0] == C_STX || pw[7:0] == C_LDX ||
                   aug_fn(pw[63:0])) &&
                  {pw[58], pw[19:16]} < 5'd3)
                rd_need[pw[17:16]] <= 1'b1;
            end
            pw <= pw >> 64;
            pw_have <= pw_have - 7'd8;
            insn_left <= insn_left - 1;
            insn_i <= insn_i + 1;
            rd_rready_q <= ((pw_have - 7'd8) < 7'd8) &&
                           (insn_left != 1);
          end else if (rd_acc) begin
            // Only the low three bits of pw_have: every assignment to
            // rready above sets it from a window that will hold FEWER
            // THAN 8 bytes, so a beat is never accepted at any other
            // offset. Shifting by all seven bits asked for 512
            // landing places instead of 8.
            pw <= pw | (PWW'(m_rd_rdata) << ({4'b0, pw_have[2:0]} << 3));
            pw_have <= pw_have + 7'(BEAT_BYTES);
            rd_rready_q <= 1'b0;         // window now needs draining
          end else if (kons_left == 0 && insn_left == 0) begin
            rd_rready_q <= 1'b0;
            rd_stream_on <= 1'b0;
            // The bank pass ends by starting the instruction pass;
            // only the second one has a whole program in hand.
            if (bank_phase)
              st <= S_IMG_GO;
            else begin
              blk_base <= '0;
              in_off   <= '0;
              dep_off  <= '0;
              sin_off  <= '0;
              sout_off <= '0;
              st <= S_BLK_SETUP;
            end
          end else
            rd_rready_q <= (pw_have < 7'd8);
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
            szaddr <= '0;
            z_first <= 1'b1;
            // How much of the scratch this block has to wipe. The
            // register file is wiped whole every block, which buys
            // "the previous block cannot leak" with no bookkeeping -
            // but the scratch is eight times larger, and wiping all of
            // it would cost SCR_D cycles a block whether or not the
            // program owns a single slot. So the wipe covers exactly
            // what the block can OBSERVE: every slot if the program
            // indexes, otherwise the highest static slot it names and
            // the slots the scratch-out drain will read. Anything
            // above that is unreachable this run, so its contents are
            // not a value any program can distinguish.
            // The preload writes slots 0..n_scratch_in-1 immediately
            // after, so those need no wipe of their own - but n_out
            // may exceed n_in, and those slots are read on the way
            // out even if nothing wrote them.
            // ...and no further than the dirty marks say anything was
            // written since it was last wiped (revision 7): the rest
            // is +0 already.
            szlimit <= scr_wipe_bc ? (SCRAW+1)'(SCR_SUB)
                                   : (SCRAW+1)'(scr_wipe_need) << NBSH;
            scr_wipe_bnd <= scr_wipe_bc ? HWW'(SCRATCH_D) : scr_wipe_need;
            scr_bcast <= scr_wipe_bc;
            // R17: the block's mask bits, one single-beat read, before
            // the wipe rather than under it. Under it would hide the
            // round trip on a fast memory and hide nothing on the card
            // (the wipe is a few dozen cycles against a hundred and
            // fifty), and it would put a second reader on the beat the
            // scratch preload is about to use. A run without a mask
            // goes straight on with mask_lane left at all ones.
            st <= mask_en_q ? S_MSK_GO : S_ZERO;
          end
        end

        // ---- the block's lane mask (revision 6, R17) -----------------
        //
        // One beat holds 256 consecutive lanes' bits at every format,
        // and a block is at most 128 lanes and starts at a multiple of
        // its own size, so this is ONE single-beat read a block and the
        // block's bits are a fixed slice of what comes back. The
        // address is the BEAT the block's first bit lives in - blk_base
        // counts lanes, so blk_base >> 8 counts beats - and nothing
        // here is scaled by the element size: a mask bit is a lane at
        // every precision, which is the one thing the four index
        // tables and this have in common.
        S_MSK_GO: begin
          rd_addr <= mask_q + ((blk_base >> 8) << 5);
          rd_sel  <= 2'd0;          // the mask rides the A master
          rd_beats_left <= 32'd1;
          rd_stream_on <= 1'b1;
          rd_rready_q <= 1'b1;
          st <= S_MSK_W;
        end

        S_MSK_W: begin
          if (rd_acc) begin
            mask_lane <= mask_blk_fn(m_rd_rdata, blk_base[7:0]);
            rd_rready_q <= 1'b0;
            rd_stream_on <= 1'b0;
            st <= S_ZERO;
          end
        end

        S_ZERO: begin
          // The register file is not wiped any more - its valid bits
          // are (see the file's declaration), in the one cycle of
          // S_BLK_SETUP. What stays here is the scratch wipe and the
          // serial multiplier below, and the state lasts as long as
          // the longer of the two: CW + 1 cycles for the product.
          if (zaddr < RFAW'(CW + 1))
            zaddr <= zaddr + 1;
          // ...and the scratch, in the same window and on its own
          // cursor, because the two are different depths. A slot a
          // lane never wrote must read +0, for the reason a deposit
          // slot no lane reached must: a run whose untouched storage
          // kept the previous block's values would not be bit-exact,
          // and two machines would disagree about memory neither of
          // them computed.
          if (szaddr < szlimit) begin
            scr_we    <= {WORDS{1'b1}};
            scr_wipe_q <= 1'b1;   // not a write the dirty marks count
            scr_waddr <= scr_flat_fn(szaddr[SCRAW-1:NBSH],
                                     6'(szaddr[NBSH-1:0]));
            scr_wdata <= '0;
            szaddr    <= szaddr + 1;
          end
          // ...and, in the same window, blk_n * max_deposits, one bit
          // of the multiplier per cycle. RF_D is 32 * NBEATS, so the
          // CW steps this takes finish long before the wipe does -
          // with twice the margin they had before revision 2, since
          // the wipe is the thing that doubled.
          //
          // The two scratch blocks want the same product against
          // their own counts, so they share the ADDEND: one shifter,
          // three accumulators. Keyed on `z_first` and not on
          // `zaddr == 0`, because the scratch wipe can outlast the
          // register file's and zaddr then WRAPS - which would
          // restart the multiplier mid-flight and hand the drain a
          // partial product.
          if (z_first) begin
            z_first    <= 1'b0;
            dep_elems  <= '0;
            sin_elems  <= '0;
            sout_elems <= '0;
            dep_addend <= 32'(blk_n);
            dep_mult   <= h_maxdep[CW-1:0];
            sin_mult   <= scr_sin_skip ? '0 : h_nsin;
            sout_mult  <= h_nsout;
          end else begin
            if (dep_mult[0])  dep_elems  <= dep_elems  + dep_addend;
            if (sin_mult[0])  sin_elems  <= sin_elems  + dep_addend;
            if (sout_mult[0]) sout_elems <= sout_elems + dep_addend;
            dep_addend <= dep_addend << 1;
            dep_mult   <= dep_mult >> 1;
            sin_mult   <= sin_mult >> 1;
            sout_mult  <= sout_mult >> 1;
          end
          // ...and the two scratch-count products are COMPLETE: the bit
          // this cycle adds is the last one either multiplier has
          // (revision 7). Their width is SCRSW + 1, which follows the
          // depth, while the window above was sized for the deposit
          // product alone: CW + 1 steps, eight at MAXD 64 and twelve at
          // 1,024. Until the dirty marks, a block whose preload or drain
          // anything could read also wiped at least one slot - sixteen
          // cycles at NBEATS 16 - so the window was never shorter than
          // fifteen steps there, and this wait mattered only for a count
          // of 2^15. With the marks, a block whose scratch is already clean
          // wipes NOTHING, so the window can be CW + 1 steps while
          // n_scratch_in or n_scratch_out needs more: at MAXD 64 a count
          // of 256 is nine bits, and without this wait it is cut to 0 -
          // nothing preloaded, nothing drained (verifier-R5's p6;
          // tb/test_seq_core.py's scratch_preload_read_with_the_marks_
          // clean holds it). At MAXD 1,024 the twelve steps cover every
          // count to 4,095, so on the U50's build it costs nothing. A
          // block that can observe no slot skips its preload
          // (scr_sin_skip) and starts sin_mult at 0: it does not wait.
          if (zaddr >= RFAW'(CW + 1) && (szaddr + 1) >= szlimit &&
              (sin_mult >> 1) == '0 && (sout_mult >> 1) == '0) begin
            // Every bank the wipe has now covered is clean.
            scr_clean_go <= 1'b1;
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
            qdepth <= '0;
            wb_bt <= '0;
            q_n <= '0;
            // The scratch-in block goes in BEFORE the operand streams
            // and therefore before the first instruction, which is
            // where the contract puts it: a program that declares
            // none skips the phase entirely and touches neither the
            // pointer nor the bus.
            // An indexed scratch block takes the gather in place of
            // the dense preload; both end at S_LD_GO.
            gt_scr <= idx_en_q[3];
            st <= (h_nsin == 0 || scr_sin_skip) ? S_LD_GO
                : idx_en_q[3]                   ? S_GTH_GO : S_SIN_GO;
          end
        end

        // ---- the scratch-in block (revision 3, R5) -------------------
        //
        // n_scratch_in slots for each of the block's lanes, lane-major
        // and dense: lane i's slot s is element i * n_scratch_in + s,
        // format-width, exactly the shape the deposit buffer has on
        // the way out. The SCRATCH is beat-organised, so this is a
        // transpose - which is why it runs one element per cycle
        // through the same peel window the image parser uses, rather
        // than a beat at a time: two elements of one bus beat can
        // belong to one lane at two slots (same banks, different
        // addresses) and no write port can serve both.
        //
        // Padding lanes receive nothing, and get it for free: the
        // element count is blk_n * n_scratch_in, so the stream simply
        // ends before their slots would begin.
        S_SIN_GO: begin
          rd_addr <= sin_q + sin_off;
          rd_sel  <= 2'd0;         // the A master, with the image
          rd_beats_left <= ((sin_elems << esz_sh) + 32'd31) >> 5;
          rd_stream_on <= 1'b1;
          sin_left <= sin_elems;
          sin_lane <= '0;
          sin_slot <= '0;
          pw <= '0; pw_have <= '0;
          rd_rready_q <= 1'b1;
          st <= S_SIN_PARSE;
        end

        S_SIN_PARSE: begin
          // One action per cycle - peel an element or absorb a beat -
          // with rready asserted ONLY when the window is too empty to
          // peel, for the reason S_IMG_PARSE's comment gives at
          // length: hold it high while peeling and the beat the
          // memory hands over falls on the floor.
          if (sin_left != 0 && pw_have >= {1'b0, esz}) begin
            scr_we    <= lane_wwe_fn(sin_lane[2:0] & 3'(lpb - 4'd1),
                                     wpe_sh);
            scr_waddr <= scr_flat_fn(sin_slot[SCRSW-1:0],
                                     6'(32'(sin_lane[LB-1:0]) >> lpb_sh));
            scr_wdata <= place_elem_fn(
                             256'(pw) & ~(~256'b0 << ({26'b0, esz} << 3)),
                             sin_lane[2:0] & 3'(lpb - 4'd1), wpe_sh);
            pw <= pw >> ({26'b0, esz} << 3);
            pw_have <= pw_have - {1'b0, esz};
            sin_left <= sin_left - 1;
            // slot within the lane, then on to the next lane - two
            // counters instead of dividing an element index
            if ((sin_slot + (SCRSW+1)'(1)) >= h_nsin) begin
              sin_slot <= '0;
              sin_lane <= sin_lane + 1;
            end else
              sin_slot <= sin_slot + (SCRSW+1)'(1);
            rd_rready_q <= ((pw_have - {1'b0, esz}) < sin_room) &&
                           (sin_left != 1);
          end else if (rd_acc) begin
            pw <= pw | (PWW'(m_rd_rdata) << ({4'b0, pw_have[2:0]} << 3));
            pw_have <= pw_have + 7'(BEAT_BYTES);
            rd_rready_q <= 1'b0;
          end else if (sin_left == 0) begin
            rd_rready_q <= 1'b0;
            rd_stream_on <= 1'b0;
            st <= S_LD_GO;
          end else
            rd_rready_q <= (pw_have < 7'd8);
        end

        S_LD_GO: begin
          // R19: a dense stream with no beat a lane the caller has sits
          // in is not loaded at all, like one no instruction reads.
          if (!rd_need[ld_reg] ||
              (!idx_en_q[ld_reg] && ld_lo == 6'(NBEATS))) begin
            // A stream the program never reads is not loaded: its
            // register entries stay unwritten and would read +0, and
            // nothing reads them.
            if (ld_reg == 2'd2)
              st <= S_FETCH;
            else
              ld_reg <= ld_reg + 1;
          end else if (idx_en_q[ld_reg]) begin
            // This stream is fetched through its table. The ELEMENTS
            // come from the stream's own base and NOT from `+ in_off`:
            // an entry is a global index into the caller's source,
            // which has no reason to hold n elements and in the shape
            // this was built for holds far fewer. The block's slice is
            // applied to the TABLE instead, in S_GTH_GO.
            gt_scr <= 1'b0;
            st <= S_GTH_GO;
          end else begin
            // R19: from the first beat a lane the caller has sits in
            // to the last, one burst; the beats outside stay unwritten
            // and read +0, and nothing that writes reads them.
            rd_addr <= (ld_reg == 0 ? a_q : ld_reg == 1 ? b_q : c_q)
                       + in_off + (ADDR_W'(ld_lo) << $clog2(BEAT_BYTES));
            rd_sel  <= ld_reg;   // ld_reg IS the stream index
            rd_beats_left <= 32'(ld_hi) - 32'(ld_lo) + 32'd1;
            rd_stream_on <= 1'b1;
            rd_rready_q <= 1'b1;
            bt <= ld_lo;
            st <= S_LD_STREAM;
          end
        end

        S_LD_STREAM: begin
          if (rd_acc) begin
            rf_we <= 1'b1;
            rf_waddr <= {3'b0, ld_reg, bt[NBSH-1:0]};
            rf_wdata <= m_rd_rdata;
            rf_wwe <= {WORDS{1'b1}};
            bt <= bt + 1;
            if (bt == ld_hi) begin
              rd_rready_q <= 1'b0;
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

        // ---- an input block through its index table (R16) -------------
        //
        // Entered from S_ZERO for the scratch block and from S_LD_GO
        // for a stream, and it leaves the way the state it replaced
        // does: the scratch gather to S_LD_GO, a stream's to the next
        // stream or to S_FETCH. `gt_scr` is the whole difference
        // between the two below this setup, and it chooses the
        // destination and nothing else.
        S_GTH_GO: begin
          // WHERE THE BLOCK'S TABLE STARTS - the trap this feature
          // has. An entry is indexed by the GLOBAL lane, so block b's
          // entries begin at ENTRY blk_base (or blk_base *
          // n_scratch_in), a count of entries and not of beats. An
          // entry is four bytes at every format, being an index and
          // not an element, so the byte offset is blk_base shifted by
          // two - and NOT in_off, which is scaled by esz and differs
          // by a factor of esz/4: at fp64 every lane would read a
          // plausible neighbour's element and no assertion about
          // lengths would notice.
          //
          // The scratch table is n_scratch_in entries a lane, so its
          // offset is that product - taken from sin_off, which holds
          // blk_base * esz * n_scratch_in already, rather than formed
          // a second time from a second multiplier that could
          // disagree with the first.
          gt_base  <= gt_scr ? sin_q
                    : (ld_reg == 0 ? a_q : ld_reg == 1 ? b_q : c_q);
          gt_taddr <= gt_tbl_base + ADDR_W'(BEAT_BYTES);
          gt_left  <= gt_scr ? sin_elems : 32'({24'b0, blk_n});
          rd_addr  <= gt_tbl_base;
          // Every read of this gather is a SINGLE BEAT, table and
          // element alike, so rd_beats_left is set to one at each
          // issue and rd_stream_on simply stays high: with no beats
          // owed the address channel issues nothing, and a beat only
          // arrives because this machine asked for it.
          rd_sel   <= 2'd0;          // the table rides the A master
          rd_beats_left <= 32'd1;
          rd_stream_on <= 1'b1;
          rd_rready_q <= 1'b1;
          gt_have <= '0;
          gt_beat <= '0;
          gt_pos  <= '0;
          gt_lane <= '0;
          gt_slot <= '0;
          bt      <= '0;
          st <= S_GTH_TBL;
        end

        // A beat of the table: eight entries at every format, because
        // an entry is a u32 and a beat is thirty-two bytes. The block
        // may own fewer than eight in its last beat, and gt_left, not
        // gt_have, is what says so.
        S_GTH_TBL: begin
          if (rd_acc) begin
            gt_tbl   <= m_rd_rdata;
            gt_have  <= 4'(WORDS);
            // gt_taddr is advanced where a table read is ISSUED (here
            // it would advance a second time for the same beat), so it
            // always names the beat after the one in flight.
            st <= S_GTH_ELEM;
          end
        end

        // One entry: +0 and no read for the sentinel (the placement
        // path above does it and this state simply stays), otherwise
        // one single-beat read of the beat the element lives in.
        S_GTH_ELEM: begin
          if (gt_left == 0) begin
            // The block is complete; a short last beat has already
            // been written by gt_flush.
            rd_rready_q <= 1'b0;
            rd_stream_on <= 1'b0;
            if (gt_scr)
              st <= S_LD_GO;
            else if (ld_reg == 2'd2)
              st <= S_FETCH;
            else begin
              ld_reg <= ld_reg + 1;
              st <= S_LD_GO;
            end
          end else if (gt_have == 0) begin
            rd_addr <= gt_taddr;
            rd_sel  <= 2'd0;
            rd_beats_left <= 32'd1;
            gt_taddr <= gt_taddr + ADDR_W'(BEAT_BYTES);
            st <= S_GTH_TBL;
          end else if (!gt_none) begin
            gt_idx  <= gt_ent;
            // (idx * esz) with the low five bits cleared: the beat the
            // element lives in. esz is 1 << esz_sh at every format, so
            // this is a shift and not a product.
            rd_addr <= gt_base +
                       ((ADDR_W'({32'b0, gt_ent}) << esz_sh) &
                        ~(ADDR_W'(BEAT_BYTES) - ADDR_W'(1)));
            // An element read belongs to the buffer it came from: the
            // stream's own master, the A master for the scratch pool,
            // exactly as the dense loads choose.
            rd_sel  <= gt_scr ? 2'd0 : ld_reg;
            rd_beats_left <= 32'd1;
            st <= S_GTH_WAIT;
          end
        end

        // The element's beat. One element is selected out of it at the
        // position the index's low bits give, by the same scr_elem_fn
        // the scratch-out drain uses; the placement path writes it.
        S_GTH_WAIT: begin
          if (rd_acc)
            st <= S_GTH_ELEM;
        end

        // ---- fetch/decode --------------------------------------------
        S_FETCH: begin
          // The implicit halt goes to the drain, and S_DRAIN_SETUP waits
          // there for every result to land and the pipe to empty - the
          // one wait every way a block can end shares (revision 7, R18).
          if (32'(pc) >= h_ninsns)             // implicit halt
            st <= S_DRAIN_SETUP;
          else
            st <= S_FETCH2;                    // pc is wanted this cycle
        end
        S_FETCH2: begin
          // The word, when the fetch has it: at once from the store, a
          // cycle on as the memory's read register gave it; from the
          // stream once it has arrived. Waiting presents pc again.
          if (if_ok) begin
            cur <= if_word;
            c_istep <= 1'b0;
            c_sld <= sld_fn(if_word);
            st <= S_DECODE;
          end
        end

        S_DECODE: begin
          if (c_piped) begin
            // Arithmetic, and since R18 every control code that walks
            // the block's beats: admitted with queue room (adm_take,
            // with the queue) and issued through the pipe. A code that
            // reads a register waits there, a beat at a time, for a
            // queued producer of it and for nothing else.
            // ...and, a load on a multi-pass tile, with every array
            // writer ahead of it landed (adm_ld_ok): it then goes fast.
            if (q_room && adm_ld_ok) begin
              bt <= adm_first;           // R19: its first live beat
              st <= S_ISSUE;
            end
            // otherwise wait here for a slot to free
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
              // Revision 8's R24: a quiet region opens and closes here,
              // in program order, and walks no beats - REPEAT's cost. The
              // depth saturates both ways: the loader nests regions four
              // deep and balances them, and a stream that bypassed it
              // keeps a defined depth instead of wrapping (verifier-VC34;
              // the depth gates only flags, so nothing here decides
              // whether a run ends).
              C_QUIET: begin
                if (qdepth != 3'd7) qdepth <= qdepth + 3'd1;
                pc <= pc + 1;
                st <= S_FETCH;
              end
              C_ENDQUIET: begin
                if (qdepth != 3'd0) qdepth <= qdepth - 3'd1;
                pc <= pc + 1;
                st <= S_FETCH;
              end
              C_ACTALL: begin
                // Widens the mask, so every beat before it must have
                // taken its row first: the pipe empty (R18). Not the
                // queue - a result still in the array retires under the
                // row it fired with, whatever the mask is by then.
                if (pipe_idle) begin
                  active <= blk_act;
                  pc <= pc + 1;
                  st <= S_FETCH;
                end
              end
              default: st <= S_DRAIN_SETUP;    // HALT and unknowns
            endcase
          end
        end

        // ---- skip to the matching endrep ------------------------------
        S_SKIP_F: begin
          if (32'(pc) >= h_ninsns)
            st <= S_DRAIN_SETUP;               // unbalanced: halt
          else
            st <= S_SKIP_D;                    // pc is wanted this cycle
        end
        S_SKIP_D: begin
          // ...and the scan waits for the word as S_FETCH2 does.
          if (if_ok) begin
            pc <= pc + 1;
            st <= S_SKIP_F;
            if (if_word[31] && if_word[7:0] == C_REPEAT)
              skip_depth <= skip_depth + 1;
            else if (if_word[31] && if_word[7:0] == C_ENDREP) begin
              if (skip_depth == 1)
                st <= S_FETCH;
              else
                skip_depth <= skip_depth - 1;
            end
          end
        end

        // ---- issue: the A stage ----------------------------------------
        S_ISSUE: begin
          // The banked register file costs TWO cycles from address to
          // data (the address registers into the bank read, the read
          // registers into the slice bus), so addresses run two beats
          // ahead of the array: this state puts beat bt's addresses on
          // the bus, and the F stage below the case fires beat bt-2
          // from the data now on the bus. Getting this off by one
          // shifted every operand a beat and failed every deposit slot
          // at once - the bench's first catch.
          //
          // "Cycle" here means a STEP: a cycle in which no request is
          // standing untaken and no dependent beat is waiting to land
          // (rd_hold, defined with the queue). On the multi-cycle tile
          // the array takes one beat per pass period, and between
          // acceptances the whole pipe - addresses, the bank read
          // registers, the stage contexts, bt, and the request itself -
          // holds, so the two-ahead relation is unchanged in accepted
          // beats. A dependent beat's hold (raw_hold), and the scratch's
          // two (gap_hold, stld_hold), hold THIS stage only: B and F
          // drain the beats already addressed, and the request the array
          // has stands until taken. Writeback, in the retire block below
          // the case, is outside every hold: a result is a pulse and is
          // taken whenever it arrives.
          //
          // Revision 7, R18: every beat-walking instruction is addressed
          // here, arithmetic or not. A control code puts the registers it
          // reads on the same ports (ra on A, rb on B - the fields it does
          // not read are zero by the loader's rule and read harmlessly),
          // and an LDL, whose slot is in the instruction, puts its scratch
          // address out now, so the scratch's read lands in F with the
          // file's. The pipe context (below the case) carries what F
          // needs to act on the beat after `cur` has moved on.
          if (!rd_hold) begin
            rf_raddr_a <= {c_ra, bt[NBSH-1:0]};
            rf_raddr_b <= {c_rb, bt[NBSH-1:0]};
            // port C reads rb for augadd and augerr (R21)
            rf_raddr_c <= {c_aug ? c_rb : c_rc, bt[NBSH-1:0]};
            if (c_is_ldl && issue_this)
              scr_raddr <= scr_flat_fn(c_imm[SCRSW-1:0], bt);
            // R19: on to the next beat this instruction issues, jumping
            // the ones with no active lane; its last STEP is the one
            // with none after it.
            bt <= next_bt;
            if (last_step) begin
              // The last address. The next instruction, read under this
              // one, is admitted and addressed from the next cycle if it
              // goes through the pipe and the queue has room (adm_go and
              // adm_take, with the queue); a code that does not - REPEAT,
              // ENDREP, ACTALL, HALT - goes to decode with its word
              // already in hand; past the end, or with the word not read
              // yet (a one-beat block, or a streamed word still on its
              // way), the fetch state takes over and the implicit halt
              // with it. The pipe acts on or fires this instruction's
              // last two beats meanwhile. if_ok is the word's being
              // here, and is never high past the program's end.
              // R22: a stepped LDX's step, as the internal IADD that
              // follows it, before the next word - which stays wanted
              // (pc does not move), and is taken at the IADD's own last
              // step. With room it is admitted now (adm_take), as the
              // next word would be; without, S_DECODE admits it.
              if (c_sld) begin
                cur <= stp_word;
                c_istep <= 1'b1;
                c_sld <= 1'b0;
                if (q_room)
                  bt <= adm_first;
                else
                  st <= S_DECODE;
              end else begin
                pc <= pc + 1;
                if (if_ok) begin
                  cur <= if_word;
                  c_istep <= 1'b0;
                  c_sld <= sld_fn(if_word);
                  if (imq_piped && q_room && adm_ld_ok)
                    bt <= adm_first;       // R19: its first live beat
                  else
                    st <= S_DECODE;
                end else
                  st <= S_FETCH;
              end
            end
          end
        end

        // ---- deposit drain --------------------------------------------
        S_DRAIN_SETUP: begin
          // Every way a block ends comes here - HALT, an unknown code,
          // an unmatched ENDREP, the implicit halt, a skip past the end -
          // and waits here, whatever the way, for every result to land
          // (the queue empty) and every beat in the pipe to have acted
          // (the deposits written, the stores in the scratch): the drains
          // read what the program left, so the program must have left it.
          // Revision 7, R18. Before it HALT, an unknown code and the
          // implicit halt waited for the queue, and an unmatched ENDREP
          // and a skip past the end went straight on - only an image that
          // bypassed the loader reaches either of those two - and no
          // control code could be in flight when the block ended.
          if (q_n == 2'd0 && pipe_idle) begin
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
            dr_v0 <= 1'b0; dr_v1 <= 1'b0;
            dr_issued <= 1'b0;
            dr_ilane <= '0; dr_islot <= '0; dr_ifill <= '0;
            if (h_maxdep == 0)
              st <= S_CNT_SETUP;
            else begin
              db_raddr <= DBA'(0);
              st <= S_DRAIN_RUN;
            end
          end
        end

        S_DRAIN_RUN: begin
          if (!dr_stall) begin
            // stage 2: the element whose data is on db_rdata lands in
            // the beat; a beat that this element completes leaves now
            if (dr_v1) begin
              if (dr_end1) begin
                m_wr_wvalid <= 1'b1;
                m_wr_wdata  <= pk_data;
                m_wr_wstrb  <= pk_strb;
                m_wr_wlast  <= (wr_after == 1);
                as_data <= '0; as_strb <= '0;
                if (dr_last1)
                  st <= S_CNT_SETUP;
              end else begin
                as_data <= pk_data;
                as_strb <= pk_strb;
              end
            end
            // stage 1: the tag follows the read
            dr_v1    <= dr_v0;
            dr_lane1 <= dr_lane0;
            dr_slot1 <= dr_slot0;
            dr_fill1 <= dr_fill0;
            dr_end1  <= dr_end0;
            dr_last1 <= dr_last0;
            // stage 0: issue the next element's read with its tag
            if (!dr_issued) begin
              db_raddr <= DBA'((32'(dr_ilane) >> lpb_sh) * MAXD + dr_islot);
              dr_v0    <= 1'b1;
              dr_lane0 <= dr_ilane;
              dr_slot0 <= dr_islot;
              dr_fill0 <= dr_ifill;
              dr_end0  <= dr_iend;
              dr_last0 <= dr_ilast;
              if (dr_ilast)
                dr_issued <= 1'b1;
              if (dr_islot == h_maxdep - 1) begin
                dr_islot <= '0;
                dr_ilane <= dr_ilane + 1;
              end else
                dr_islot <= dr_islot + 1;
              dr_ifill <= dr_iend ? 6'd0 : dr_ifill + esz;
            end else
              dr_v0 <= 1'b0;
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
          // A whole beat at once: eight lanes' counts (cnt_beat, built
          // beside cur_cnt), strobed where the lane exists. One cycle
          // a beat where it was one a lane.
          as_data <= cnt_beat;
          for (int w = 0; w < WORDS; w = w + 1)
            as_strb[w*4 +: 4] <= cnt_beat_ok[w] ? 4'hf : 4'h0;
          if (32'(lane_cursor) + 32'(WORDS) >= 32'(blk_n))
            drain_last <= 1'b1;
          lane_cursor <= lane_cursor + (LB+1)'(WORDS);
          st <= S_CNT_SEND;
        end

        S_CNT_SEND: begin
          if ((!m_wr_wvalid || m_wr_wready) && wr_after != 0) begin
            m_wr_wvalid <= 1'b1;
            m_wr_wdata <= as_data;
            m_wr_wstrb <= as_strb;
            m_wr_wlast <= (wr_after == 1);
            as_fill <= '0; as_strb <= '0; as_data <= '0;
            if (drain_last)
              // The scratch-out block goes out AFTER the last deposit
              // of the block, which is where the contract puts it; a
              // program that declares none touches neither the
              // pointer nor the bus.
              // ...and before it, R23's block where the run asked for it.
              st <= lf_en_q ? S_LF_SETUP
                  : (h_nsout != 0) ? S_SO_SETUP : S_WAIT_B;
            else
              st <= S_CNT_PACK;
          end
        end

        // ---- the per-lane flag block (revision 8, R23) ----------------
        //
        // A byte a lane at lf_q + the lane's global index, after the
        // counts and before the scratch-out block, in the counts' shape: a
        // beat packed in one cycle (lf_beat_fn, BEAT_BYTES lanes) and sent
        // in the next, strobed where the lane is below blk_n and the
        // caller's (mask_lane) - a masked lane's byte is the caller's, as
        // its count is. A block of 128, 64, 32 or 16 lanes is 4, 2, 1 or
        // half a beat; the half beat sits at its block's offset in the
        // 32-byte beat (lf_off), its other half unstrobed. A run that did
        // not ask (MODE[24] clear) never comes here and writes nothing.
        S_LF_SETUP: begin
          as_fill <= '0; as_strb <= '0; as_data <= '0;
          drain_last <= 1'b0;
          // the counts' stream quiet first, as S_SO_SETUP waits
          if (wr_burst_left == 0 && !m_wr_awvalid && !wr_aw_open &&
              !m_wr_wvalid && wr_beats_left == 0) begin
            wr_addr <= lf_q + (blk_base & ~(64'(LFB) - 64'd1));
            wr_beats_left <= (32'(lf_off) + 32'(blk_n) + 32'(LFB - 1))
                             >> $clog2(LFB);
            lf_k <= '0;
            st <= S_LF_PACK;
          end
        end

        S_LF_PACK: begin
          as_data <= lf_beat;
          as_strb <= lf_strb;
          if ((32'(lf_k) + 32'd1) * 32'(LFB) >= 32'(lf_off) + 32'(blk_n))
            drain_last <= 1'b1;
          lf_k <= lf_k + LFKW'(1);
          st <= S_LF_SEND;
        end

        S_LF_SEND: begin
          if ((!m_wr_wvalid || m_wr_wready) && wr_after != 0) begin
            m_wr_wvalid <= 1'b1;
            m_wr_wdata <= as_data;
            m_wr_wstrb <= as_strb;
            m_wr_wlast <= (wr_after == 1);
            as_fill <= '0; as_strb <= '0; as_data <= '0;
            if (drain_last)
              st <= (h_nsout != 0) ? S_SO_SETUP : S_WAIT_B;
            else
              st <= S_LF_PACK;
          end
        end

        // ---- the scratch-out block (revision 3, R5) -------------------
        //
        // The deposit drain's shape exactly, reading the scratch
        // instead of the deposit banks: (lane, slot) in the caller's
        // index order, packed into beats by the same assembler, out
        // through the same write master. It is NOT masked by the
        // active bit - it is a drain, like the deposit drain, and a
        // lane that converged early still has state worth carrying to
        // the next call. It IS masked by the CALLER'S bit (R17): a
        // lane the mask cleared was never this run's, so its slots
        // keep the caller's bytes - the two questions differ exactly
        // here, and S_SO_PACK's strobe below is where the difference
        // is written. Padding lanes write nothing, because the
        // element count is blk_n * n_scratch_out.
        S_SO_SETUP: begin
          lane_cursor <= '0;
          slot_cursor <= '0;
          as_fill <= '0; as_strb <= '0; as_data <= '0;
          drain_last <= 1'b0;
          // Wait for the counts stream to go quiet before switching
          // targets, exactly as S_CNT_SETUP waits for the deposits.
          if (wr_burst_left == 0 && !m_wr_awvalid && !wr_aw_open &&
              !m_wr_wvalid && wr_beats_left == 0) begin
            wr_addr <= sout_q + sout_off;
            wr_beats_left <= ((sout_elems << esz_sh)
                              + 32'(BEAT_BYTES) - 32'd1) >> 5;
            st <= S_SO_RD;
          end
        end

        S_SO_RD: begin
          // One lane at a time, so every bank takes the same address -
          // the per-bank addressing the four codes need is idle here.
          scr_raddr <= scr_flat_fn(slot_cursor[SCRSW-1:0], dc_beat);
          st <= S_SO_W8;
        end
        S_SO_W8: st <= S_SO_PACK;

        S_SO_PACK: begin
          for (int w = 0; w < WORDS; w = w + 1)
            if ((32'(w) >> wpe_sh) == (32'(as_fill) >> esz_sh)) begin
              as_data[w*32 +: 32] <=
                scr_out_elem[(32'(w) & ((32'd1 << wpe_sh) - 32'd1))
                             * 32 +: 32];
              // R17, and this is the drain the comment above is about:
              // NOT masked by the active bit, because a lane that
              // converged early still has state worth carrying - and
              // masked by the CALLER'S bit, because a lane the caller
              // did not give the run has no state of this run's at
              // all. The two are different questions and this is the
              // one place where the difference is visible in bytes.
              as_strb[w*4 +: 4] <=
                mask_lane[lane_cursor[LB-1:0]] ? 4'hf : 4'h0;
            end
          as_fill <= as_fill + esz;
          if (32'(lane_cursor) == 32'(blk_n) - 1 &&
              slot_cursor == 32'(h_nsout) - 32'd1)
            drain_last <= 1'b1;
          if (slot_cursor == 32'(h_nsout) - 32'd1) begin
            slot_cursor <= '0;
            lane_cursor <= lane_cursor + 1;
          end else
            slot_cursor <= slot_cursor + 1;
          if ({1'b0, as_fill} + {1'b0, esz} == 7'(BEAT_BYTES) ||
              (32'(lane_cursor) == 32'(blk_n) - 1 &&
               slot_cursor == 32'(h_nsout) - 32'd1))
            st <= S_SO_SEND;
          else
            st <= S_SO_RD;
        end

        S_SO_SEND: begin
          if ((!m_wr_wvalid || m_wr_wready) && wr_after != 0) begin
            m_wr_wvalid <= 1'b1;
            m_wr_wdata <= as_data;
            m_wr_wstrb <= as_strb;
            m_wr_wlast <= (wr_after == 1);
            as_fill <= '0; as_strb <= '0; as_data <= '0;
            if (drain_last)
              st <= S_WAIT_B;
            else
              st <= S_SO_RD;
          end
        end

        S_WAIT_B: begin
          // ...and the fetch idle (revision 8): its quiesce, raised in
          // S_DRAIN_SETUP, overlaps the drains, and the next block's
          // setup reads find the port free.
          if (wr_bresp_left == 0 && !m_wr_wvalid && !m_wr_awvalid &&
              !wr_aw_open && wr_burst_left == 0 && if_idle) begin
            m_wr_bready <= 1'b0;
            wr_stream_on <= 1'b0;
            st <= S_NEXT_BLK;
          end
        end

        S_NEXT_BLK: begin
          blk_base <= blk_base + {56'b0, blk_cap};
          in_off   <= in_off  + ADDR_W'(BLK_BYTES);
          dep_off  <= dep_off + dep_stride;
          sin_off  <= sin_off  + sin_stride;
          sout_off <= sout_off + sout_stride;
          st <= S_BLK_SETUP;
        end

        S_FIN: begin
          done <= 1'b1;
          st <= S_IDLE;
        end

        // ---- the abort (revision 8; the contract's item 5) ---------------
        //
        // Entered at a safe point (abort_go) once a fault has ended the
        // run. Nothing new is issued here; this waits for what is already
        // committed: the read burst in flight to land - RREADY high for it,
        // a long one drained to its RLAST, a short one already ended by
        // its own - so that no beat of this run reaches the next one's
        // first read; every write response (a committed write burst has
        // delivered its beats before abort_go let the machine leave the
        // drain that was producing them); and the issue pipe, so that no
        // result of this run lands in the next one's register file - the
        // array is shared, and a run's results retire whatever state the
        // machine is in. Then done, with err[2] or err[0] saying why.
        S_ABORT: begin
          rd_rready_q  <= (rd_burst_left != 0) || rd_long_q;
          m_wr_bready  <= 1'b1;
          if (rd_burst_left == 0 && !rd_long_q && !rd_arvalid_q &&
              wr_bresp_left == 0 && wr_quiet && if_idle &&
              q_n == 2'd0 && pipe_idle) begin
            rd_rready_q  <= 1'b0;
            m_wr_bready  <= 1'b0;
            wr_stream_on <= 1'b0;
            st <= S_FIN;
          end
        end

        default: st <= S_IDLE;
      endcase

      // ---- the issue pipe's B and F stages, every accepted cycle -------
      // B: the file reads what A addressed (the bank registers, in the
      // generate above, sample under the same hold), and the context
      // follows. F: the beat fires with the data on the bus and the
      // constants its indices fetched a stage ago; the request it makes stands
      // until taken, and is re-made for the next beat the cycle it is.
      // A held on a dependent beat (raw_hold) is simply a cycle A put
      // nothing on the bus: a bubble, drained like any other beat.
      //
      // Revision 7, R18: a beat at F is now one of three things. An ALU
      // beat or an LDL beat FIRES - the LDL's value as IOR(v, v) with its
      // flag enable off, or, a FAST load's, written into the file by the
      // retire's port (fw) - with the row of `active` it is firing under.
      // A DEPOSIT, SETACT or store beat ACTS here, on its own beat's row,
      // and never reaches the array. An LDX beat forms its scratch
      // address here and fires two steps on, at H. Everything F does is
      // in program order, one beat a step, which is what makes a
      // SETACT's narrowing visible to exactly the beats after it.
      if (!issue_hold) begin
        pb_v    <= (st == S_ISSUE) && !a_hold && issue_this;
        pb_op   <= c_op;
        pb_rnd  <= c_rnd;
        pb_ka   <= c_ka; pb_kb <= c_kb; pb_kc <= c_kc;
        pb_ctrl <= c_ctrl;
        pb_fast <= c_fast;
        pb_quiet <= c_quiet;
        pb_bt   <= bt;
        pb_slot <= c_imm[SCRSW-1:0];
        pb_step <= c_imm[11:0];
        pb_sstep <= c_ctrl && (c_op == C_STX) && (c_imm[11:0] != 12'd0);
        pb_istep <= c_istep;
        pb_kidx_a <= k_idx_a; pb_kidx_b <= k_idx_b; pb_kidx_c <= k_idx_c;
        pf_v    <= pb_v;
        pf_op   <= pb_op;
        pf_rnd  <= pb_rnd;
        pf_ka   <= pb_ka; pf_kb <= pb_kb; pf_kc <= pb_kc;
        pf_ctrl <= pb_ctrl;
        pf_fast <= pb_fast;
        pf_quiet <= pb_quiet;
        pf_bt   <= pb_bt;
        pf_slot <= pb_slot;
        pf_step <= pb_step;
        pf_sstep <= pb_sstep;
        pf_istep <= pb_istep;
        pf_aa   <= rf_raddr_a; pf_ab <= rf_raddr_b; pf_ac <= rf_raddr_c;
        // an LDX's G and H: the address F put on the scratch's read
        // port is read at G, and what came back fires at H
        pg_v    <= pf_ldx;
        pg_bt   <= pf_bt;
        pg_oor  <= scr_oor_bk;
        pg_fast <= pf_fast;
        ph_v    <= pg_v;
        ph_bt   <= pg_bt;
        ph_oor  <= pg_oor;
        ph_fast <= pg_fast;
        // The request (fire_* above): an ALU beat with its operands, a
        // load's value as IOR(v, v) - the scratch's read landed with the
        // file's for an LDL, at G for an LDX - under the row it fires
        // with, and with its flag enable off. A fast load's beat makes no
        // request: its write is the retire block's (fw).
        if (fire_go) begin
          al_valid <= 1'b1;
          al_op    <= fire_alu ? pf_op : fire_aug ? OP_ADD :
                      fire_sstep ? OP_IADD : OP_IOR;
          al_rnd   <= fire_alu ? pf_rnd : 3'd0;
          // R21: 1 augadd, 2 augerr, 0 every other request. 9.5 fixes the
          // pair's rounding, so the attribute is not read under it.
          al_aug   <= !fire_aug ? 2'd0 : (pf_op == C_AUGERR) ? 2'd2 : 2'd1;
          al_a     <= use_op_a ? op_a : alt_a;
          al_b     <= use_op_b ? op_b : alt_b;
          al_c     <= use_op_c ? op_c : alt_c;
          al_row   <= fire_ldx ? h_act : bt_act;
          // ...and quiet beats raise nothing (R24): the tag the beat
          // was admitted with, not the region the machine is in now.
          // R21's two raise their flags as an ALU instruction does.
          // ...and a step raises none (R22: IADD's arithmetic, no flag).
          al_fen   <= ((fire_alu && !pf_istep) || fire_aug) && !pf_quiet;
          al_tag   <= fire_ldx ? ph_bt : pf_bt;
        end
        if (pf_v && pf_ctrl) begin
          case (pf_op)
            // An indexed load's slot is its rb, which is on the bus
            // now: the address goes to the scratch's read port, and the
            // value fires at H. R8's report is taken here, where rb is,
            // under this beat's row - the row it will fire with, since
            // nothing after it can reach F before it reaches H.
            C_LDX: begin
              scr_raddr <= scr_addr_fn(scr_slot, pf_bt, wpe_sh);
              if (|(bt_wwe & scr_oor_bk))
                scr_rng_q <= 1'b1;
            end
            // A store is a register write for P3's purposes, so it takes
            // exactly the register file's per-lane mask - less any lane
            // R8 suppressed, whose store does not land anywhere rather
            // than landing on the slot the modulo would name. The value
            // is F's forwarded operand, as an ALU operand's is.
            C_STL, C_STX: begin
              scr_we    <= bt_wwe & ~scr_oor_bk;
              scr_waddr <= scr_addr_fn(scr_slot, pf_bt, wpe_sh);
              scr_wdata <= op_a;
              if (|(bt_wwe & scr_oor_bk))
                scr_rng_q <= 1'b1;
            end
            // Each active, in-capacity lane of the beat writes its own
            // bank set at its own slot; the banks' independent write
            // addresses are what makes one beat a cycle possible even
            // after SETACT has left the beat's lanes with divergent
            // counts. The counts advance once per LANE: only the eight
            // positions of this beat can move, and the value each moves
            // to was formed once (bt_cnt_inc), so this is a selection
            // over constant indices and not 128 counters with a decoder.
            C_DEPOSIT: begin
              for (int p = 0; p < WORDS; p = p + 1)
                if (bt_dep_go[32'(p) >> wpe_sh]) begin
                  db_we[p] <= 1'b1;
                  db_waddr[p*DBA +: DBA] <= DBA'(32'(pf_bt) * MAXD +
                      32'(pick_cnt_fn(bt_cnt, 3'(32'(p) >> wpe_sh))));
                  db_wdata[p*32 +: 32] <= op_a[p*32 +: 32];
                end
              for (int b = 0; b < NBEATS; b = b + 1)
                for (int q = 0; q < WORDS; q = q + 1)
                  if (b == 32'(pf_bt[NBSH-1:0]) && bt_dep_go[q])
                    dcnt[(b*WORDS + q)*CW +: CW] <= bt_cnt_inc[q*CW +: CW];
              if (|bt_dep_ovf)
                dep_ovf_q <= 1'b1;
            end
            // Eight magnitude tests, one per lane position in the beat,
            // on the operand as the BANK read it (SETACT's ra waits under
            // R14's rule, so the bank has it): narrowing only, so a lane
            // already out stays out.
            C_SETACT: begin
              for (int b = 0; b < NBEATS; b = b + 1)
                for (int q = 0; q < WORDS; q = q + 1)
                  if (b == 32'(pf_bt[NBSH-1:0]) && 32'(q) < 32'(lpb) &&
                      bt_act[q])
                    active[b*WORDS + q] <= sa_nz[q];
            end
            default: ;
          endcase
        end
      end

      // ---- retire: the array's results, whatever state the machine is
      // in - while a program runs; the engine's pulses are not ours -
      // to the destination at the head of the queue --------------------
      if (al_ov && seq_live) begin
        rf_we <= 1'b1;
        rf_waddr <= {q_rd0, wb_tag[NBSH-1:0]};
        rf_wdata <= al_d;
        rf_wwe <= wb_wwe;
        // the lanes that were active when this beat FIRED (fr), and its
        // flags only if it is arithmetic and was not admitted quiet (fq):
        // a load raises none. Written below, with a RAISE's, as one OR.
        // the head's next beat not yet landed or skipped: every beat
        // below the one that just landed has landed or was skipped
        wb_bt <= wb_pop ? 6'd0 : wb_tag + 6'd1;
      end else if (fw) begin
        // A FAST load's beat: written here, where an array result would
        // be, and the head's reach moved as a landing moves it - so a
        // reader of its register waits for exactly this write (R14's
        // "landed" rule), whatever port it reads by. No flag: a load
        // raises none, and this branch never touches flags_q.
        rf_we    <= 1'b1;
        rf_waddr <= {q_rd0, fw_bt[NBSH-1:0]};
        rf_wdata <= ld_val;
        rf_wwe   <= fw_wwe;
        wb_bt    <= fw_pop ? 6'd0 : fw_bt + 6'd1;
      end
      // FLAGS, the run's sticky OR, from its two sources in one write - a
      // result landing (its beat's flags, under the row and the tag it fired
      // with) and a RAISE acting at F (R24) - so neither overwrites the
      // other in a cycle they share. And the mark, which no region hides.
      if (ret_fl != 5'b0 || raise_fl != 5'b0)
        flags_q <= flags_q | ret_fl | raise_fl;
      if (raise_mk)
        mark_q <= 1'b1;
      // the queue: a pop moves everything down, and an admission lands
      // behind whatever is left
      if (wb_pop) begin
        q_rd0 <= q_rd1;
        q_rd1 <= q_rd2;
        q_f0  <= q_f1;
        q_f1  <= q_f2;
      end
      if (q_push) begin
        case (q_after)
          2'd0:    begin q_rd0 <= adm_rd; q_f0 <= adm_fast; end
          2'd1:    begin q_rd1 <= adm_rd; q_f1 <= adm_fast; end
          default: begin q_rd2 <= adm_rd; q_f2 <= adm_fast; end
        endcase
      end
      // Only when something moves: a `q_n <= q_n` every cycle would
      // override the block setup's reset, which is written above the
      // case and must win in its cycle.
      if (q_push || wb_pop)
        q_n <= q_after + {1'b0, q_push};
      // the admitted instruction's producers, positions from the head;
      // a pop moves them down, and the head popping releases the operand.
      // Every admission sets them (R18: a control code has producers too,
      // and most control codes take no queue slot of their own).
      if (adm_take) begin
        c_fast  <= adm_fast;
        c_quiet <= (qdepth != 3'd0);
      end
      if (adm_take) begin
        dep_v_a <= dep_n_a; dep_pos_a <= dep_p_a;
        dep_v_b <= dep_n_b; dep_pos_b <= dep_p_b;
        dep_v_c <= dep_n_c; dep_pos_c <= dep_p_c;
      end else if (wb_pop) begin
        if (dep_pos_a == 2'd0) dep_v_a <= 1'b0; else dep_pos_a <= dep_pos_a - 2'd1;
        if (dep_pos_b == 2'd0) dep_v_b <= 1'b0; else dep_pos_b <= dep_pos_b - 2'd1;
        if (dep_pos_c == 2'd0) dep_v_c <= 1'b0; else dep_pos_c <= dep_pos_c - 2'd1;
      end
    end
  end

endmodule
