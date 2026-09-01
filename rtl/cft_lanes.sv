// Copyright 2026 Logan W.
// SPDX-License-Identifier: Apache-2.0
//
// cft_lanes: the tile's ONE beat-wide ALU array.
//
// Eight fp32 / four fp64 / two fp128 lanes or one fp256 unit, each
// lane the verified recipe: cft_opmux steering into cft_fpfma_pipe,
// with cft_simpleops and cft_seedop merged through the pipe's bypass
// sideband so every opcode has one fixed latency and per-lane flags.
// The optional fused ladders live here too - FUSE_NORM / FUSE_ALIGN,
// the size campaign's saving (kernel 131,860 -> 98,310 LUT), and
// FUSE_MUL, measured not to pay - because they are properties of the
// array, not of whoever drives it.
//
// Two drivers share it: cft_engine_stream (elementwise ops, and the
// reduction accumulator's adder through lane 0) and cft_seq
// (programs). They never run at once - MODE[15] names one owner per
// run - so the sharing is a static mux in cft_krnl with no
// arbitration, and P1 of docs/SEQUENCER.md ("the sequencer introduces
// no arithmetic, only a schedule") becomes a fact about the netlist
// rather than a claim about two copies of the same source.
//
// The second copy was real, and it is why this module exists.
// cft_seq_lanes, the v1 deviation the sequencer's bench was built
// against, instantiated the pipes a second time and WITHOUT the fused
// ladders: the sequencer-era kernel synthesised at 288,764 LUT against
// the engine's 98,310, and the quad tile asked for 1.32M LUTs of an
// 871k part (2026-09-01). Extracting the array was the work that
// deviation promised, and every driver now instantiates this module
// or is handed its ports.
//
// The interface is per-ISSUE: op and rnd travel with each beat (the
// pipe already carries the attribute alongside each operation, which
// is what lets adjacent sequencer instructions round differently),
// while prec is stable per run - it selects the live bank and the
// ladders' mode, and both drivers snapshot it at start and hold it
// until their last result has retired.
//
// Flags come out PER LANE, packed 5 bits per lane position at the
// current precision (positions at or beyond lanes_per_beat read
// zero). The sequencer masks each lane's contribution by its active
// bit before reducing (P3); the engine ORs them. Packed rather than
// an unpacked array because yosys's frontend refuses unpacked-array
// ports, and the portability lint gate is CI law here.

`timescale 1ns/1ps

module cft_lanes #(
    parameter int BEAT_BITS  = 256,
    parameter int LATENCY    = 15,
    parameter bit EN_FP64    = 1'b1,
    parameter bit EN_FP128   = 1'b1,
    parameter bit EN_FP256   = 1'b1,
    // The three fused ladders, in the words cft_engine_stream's header
    // used for them: FUSE_MUL shares one cft_mulfrac across the lanes
    // (collapses DSP, which is not the constraint, and measured +693
    // LUT - off); FUSE_NORM shares one segmented normalise ladder;
    // FUSE_ALIGN one bidirectional ladder for the alignment shifters.
    // The latter two are what the shipping builds carry.
    parameter bit FUSE_MUL   = 1'b0,
    parameter bit FUSE_NORM  = 1'b0,
    parameter bit FUSE_ALIGN = 1'b0
)(
    input  logic                 clk,
    input  logic                 rst_n,

    input  logic                 in_valid,
    input  logic [7:0]           op,     // opcode, sampled per issue
    input  logic [2:0]           rnd,    // 754 attribute, per issue
    input  logic [1:0]           prec,   // PREC_CODE; stable per run
    input  logic [BEAT_BITS-1:0] a,
    input  logic [BEAT_BITS-1:0] b,
    input  logic [BEAT_BITS-1:0] c,

    output logic                 out_valid,   // in_valid, LATENCY later
    output logic [BEAT_BITS-1:0] d,
    output logic [BEAT_BITS/32*5-1:0] lane_flags
);

  localparam logic [1:0] PREC_FP32  = 2'd0;
  localparam logic [1:0] PREC_FP64  = 2'd1;
  localparam logic [1:0] PREC_FP128 = 2'd2;
  localparam logic [1:0] PREC_FP256 = 2'd3;

  localparam int LANES32  = BEAT_BITS / 32;
  localparam int LANES64  = (BEAT_BITS >= 64)  ? BEAT_BITS / 64  : 0;
  localparam int LANES128 = (BEAT_BITS >= 128) ? BEAT_BITS / 128 : 0;
  localparam int LANES256 = (BEAT_BITS >= 256) ? BEAT_BITS / 256 : 0;

  // ---- validity delay line -------------------------------------------
  logic [LATENCY-1:0] v_sh;
  always_ff @(posedge clk) begin
    if (!rst_n)
      v_sh <= '0;
    else
      v_sh <= {v_sh[LATENCY-2:0], in_valid};
  end
  assign out_valid = v_sh[LATENCY-1];

  // ---- the shared multiplier (off by default) -------------------------
  //
  // All three ladders require the full-tile geometry: their slot pitch
  // IS the 256-bit beat's shape, and a quarter tile does not build the
  // rungs it is sized for. See cft_engine_stream's history for the
  // measurements behind each default.
  localparam bit USE_FUSED_MUL = FUSE_MUL && (BEAT_BITS == 256) &&
                                 EN_FP64 && EN_FP128 && EN_FP256;

  localparam int MF_PMAX = 237;
  localparam int MF_MCH  = 27;
  localparam int MF_ACCW = 2 * MF_PMAX + 2 * MF_MCH;

  logic [MF_PMAX-1:0] mf_a, mf_b;
  logic [MF_ACCW-1:0] mf_p;

  // Significands out of each lane, waiting to be packed. Fixed sizes
  // rather than LANES-derived: only the first LANES* of each are
  // driven, and the fused path is gated on the geometry where that is
  // all of them.
  logic [23:0]  mfa32  [0:7],  mfb32  [0:7];
  logic [52:0]  mfa64  [0:3],  mfb64  [0:3];
  logic [112:0] mfa128 [0:1],  mfb128 [0:1];
  logic [236:0] mfa256,        mfb256;

  generate
    if (USE_FUSED_MUL) begin : g_mulfrac
      cft_mulfrac #(.PMAX(MF_PMAX), .MCH(MF_MCH), .SLOTS(16)) u_mulfrac (
          .clk(clk), .mode(prec), .in_valid(in_valid),
          .a(mf_a), .b(mf_b), .out_valid(), .p(mf_p));

      // Pack whichever bank is live. prec is stable per run and cannot
      // move while anything is in flight - both drivers hold it until
      // their last result has retired - so the array's mode always
      // matches the operands it is being handed.
      always_comb begin
        mf_a = '0;
        mf_b = '0;
        case (prec)
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

  // ---- the shared normalise ladder -----------------------------------
  localparam bit USE_FUSED_NORM = FUSE_NORM && (BEAT_BITS == 256) &&
                                  EN_FP64 && EN_FP128 && EN_FP256;

  // Eight uniform slots of 90 bits: the smallest slot holding an fp32
  // window (78) whose eight-fold tiling holds an fp256 one (717). Lane
  // l of mode m sits at l*(NSEG_SLOTW<<m). See cft_normseg's header for
  // why the pitch is uniform rather than the natural width.
  localparam int NSEG_SLOTW = 90;
  localparam int NSEG_W     = 8 * NSEG_SLOTW;
  localparam int NW32  = 78;
  localparam int NW64  = 165;
  localparam int NW128 = 345;
  localparam int NW256 = 717;

  logic [NSEG_W-1:0] ns_din, ns_dout;
  logic [8*4-1:0]    ns_csh;               // lane l at l*4, the ladder's pitch
  logic [8*6-1:0]    ns_fsh;               // lane l at l*6

  logic [NW32-1:0]  nv32  [0:7];
  logic [NW64-1:0]  nv64  [0:3];
  logic [NW128-1:0] nv128 [0:1];
  logic [NW256-1:0] nv256;
  logic [3:0] nc32 [0:7], nc64 [0:3], nc128 [0:1], nc256;
  logic [5:0] nf32 [0:7], nf64 [0:3], nf128 [0:1], nf256;

  generate
    if (USE_FUSED_NORM) begin : g_normseg
      cft_normseg #(.PMAX(237), .SLOTS(8)) u_normseg (
          .clk(clk), .mode(prec), .din(ns_din),
          .csh(ns_csh), .fsh(ns_fsh), .dir('0), .dout(ns_dout));

      always_comb begin
        ns_din = '0;
        ns_csh = '0;
        ns_fsh = '0;
        case (prec)
          PREC_FP32:  for (int i = 0; i < 8; i = i + 1) begin
                        ns_din[i*NSEG_SLOTW +: NW32] = nv32[i];
                        ns_csh[i*4 +: 4] = nc32[i];
                        ns_fsh[i*6 +: 6] = nf32[i];
                      end
          PREC_FP64:  for (int i = 0; i < 4; i = i + 1) begin
                        ns_din[i*2*NSEG_SLOTW +: NW64] = nv64[i];
                        ns_csh[i*4 +: 4] = nc64[i];
                        ns_fsh[i*6 +: 6] = nf64[i];
                      end
          PREC_FP128: for (int i = 0; i < 2; i = i + 1) begin
                        ns_din[i*4*NSEG_SLOTW +: NW128] = nv128[i];
                        ns_csh[i*4 +: 4] = nc128[i];
                        ns_fsh[i*6 +: 6] = nf128[i];
                      end
          default:    begin
                        ns_din[0 +: NW256] = nv256;
                        ns_csh[0 +: 4] = nc256;
                        ns_fsh[0 +: 6] = nf256;
                      end
        endcase
      end
    end else begin : g_no_normseg
      assign ns_din  = '0;
      assign ns_dout = '0;
      assign ns_csh  = '0;
      assign ns_fsh  = '0;
    end
  endgenerate

  // ---- the shared ALIGN ladder ---------------------------------------
  localparam bit USE_FUSED_ALIGN = FUSE_ALIGN && (BEAT_BITS == 256) &&
                                   EN_FP64 && EN_FP128 && EN_FP256;

  // AW = 3*MAN_W + 8 per rung - one bit under the normalise window.
  localparam int AW32  = 77;
  localparam int AW64  = 164;
  localparam int AW128 = 344;
  localparam int AW256 = 716;

  logic [NSEG_W-1:0] as_din, as_dout;
  logic [8*4-1:0]    as_csh;               // lane l at l*4, as above
  logic [8*6-1:0]    as_fsh;               // lane l at l*6
  logic [7:0]        as_dir;               // lane l at bit l

  logic [AW32-1:0]  av32  [0:7];
  logic [AW64-1:0]  av64  [0:3];
  logic [AW128-1:0] av128 [0:1];
  logic [AW256-1:0] av256;
  logic [3:0] ac32 [0:7], ac64 [0:3], ac128 [0:1], ac256;
  logic [5:0] af32 [0:7], af64 [0:3], af128 [0:1], af256;
  logic       ad32 [0:7], ad64 [0:3], ad128 [0:1], ad256;

  generate
    if (USE_FUSED_ALIGN) begin : g_alignseg
      cft_normseg #(.PMAX(237), .SLOTS(8), .BIDIR(1'b1)) u_alignseg (
          .clk(clk), .mode(prec), .din(as_din),
          .csh(as_csh), .fsh(as_fsh), .dir(as_dir), .dout(as_dout));

      always_comb begin
        as_din = '0;
        as_csh = '0;
        as_fsh = '0;
        as_dir = '0;
        case (prec)
          PREC_FP32:  for (int i = 0; i < 8; i = i + 1) begin
                        as_din[i*NSEG_SLOTW +: AW32] = av32[i];
                        as_csh[i*4 +: 4] = ac32[i];
                        as_fsh[i*6 +: 6] = af32[i];
                        as_dir[i] = ad32[i];
                      end
          PREC_FP64:  for (int i = 0; i < 4; i = i + 1) begin
                        as_din[i*2*NSEG_SLOTW +: AW64] = av64[i];
                        as_csh[i*4 +: 4] = ac64[i];
                        as_fsh[i*6 +: 6] = af64[i];
                        as_dir[i] = ad64[i];
                      end
          PREC_FP128: for (int i = 0; i < 2; i = i + 1) begin
                        as_din[i*4*NSEG_SLOTW +: AW128] = av128[i];
                        as_csh[i*4 +: 4] = ac128[i];
                        as_fsh[i*6 +: 6] = af128[i];
                        as_dir[i] = ad128[i];
                      end
          default:    begin
                        as_din[0 +: AW256] = av256;
                        as_csh[0 +: 4] = ac256;
                        as_fsh[0 +: 6] = af256;
                        as_dir[0] = ad256;
                      end
        endcase
      end
    end else begin : g_no_alignseg
      assign as_din  = '0;
      assign as_dout = '0;
      assign as_csh  = '0;
      assign as_fsh  = '0;
      assign as_dir  = '0;
    end
  endgenerate

  // ---- fp32 bank -----------------------------------------------------
  logic [BEAT_BITS-1:0] d32;
  logic [4:0] f32_l [0:LANES32-1];
  genvar gi;
  generate
    for (gi = 0; gi < LANES32; gi = gi + 1) begin : g_lane32
      logic [31:0] sa, sb, sc, fa, fb, fc, dd;
      assign sa = a[gi*32 +: 32];
      assign sb = b[gi*32 +: 32];
      assign sc = c[gi*32 +: 32];
      cft_opmux #(.EXP_W(8), .MAN_W(23)) u_mux (
          .op(op), .a(sa), .b(sb), .c(sc),
          .fa(fa), .fb(fb), .fc(fc));
      logic bv; logic [31:0] bd; logic [4:0] bf;
      cft_simpleops #(.EXP_W(8), .MAN_W(23)) u_simple (
          .op(op), .a(sa), .b(sb), .c(sc),
          .valid(bv), .d(bd), .flags(bf));
      // Divide/sqrt seeds: quiet unary precomputed results, delivered
      // through the SAME bypass sideband as simpleops - which is why no
      // new collection plumbing exists for them. Opcode sets disjoint,
      // so the merge is an OR.
      logic sev; logic [31:0] sed;
      cft_seedop #(.EXP_W(8), .MAN_W(23)) u_seed (
          .op(op), .a(sa), .valid(sev), .d(sed));
      logic bv_m; logic [31:0] bd_m; logic [4:0] bf_m;
      assign bv_m = bv | sev;
      assign bd_m = sev ? sed : bd;
      assign bf_m = sev ? 5'b0 : bf;
      cft_fpfma_pipe #(.EXP_W(8), .MAN_W(23), .LATENCY(LATENCY),
                       .EXT_MUL(USE_FUSED_MUL), .EXT_NORM(USE_FUSED_NORM),
                       .EXT_ALIGN(USE_FUSED_ALIGN)) u_fma (
          .clk(clk), .rst_n(rst_n),
          .in_valid(in_valid && (prec == PREC_FP32)),
          .rnd(rnd),
          .byp(bv_m), .byp_d(bd_m), .byp_f(bf_m),
          .a(fa), .b(fb), .c(fc),
          .out_valid(), .d(dd), .flags(f32_l[gi]),
          .mul_a(mfa32[gi]), .mul_b(mfb32[gi]),
          .mul_p(mf_p[gi*48 +: 48]),
          .nrm_v(nv32[gi]), .nrm_csh(nc32[gi]), .nrm_fsh(nf32[gi]),
          .nrm_d(ns_dout[gi*NSEG_SLOTW +: NW32]),
          .aln_v(av32[gi]), .aln_csh(ac32[gi]), .aln_fsh(af32[gi]),
          .aln_dir(ad32[gi]), .aln_d(as_dout[gi*NSEG_SLOTW +: AW32]));
      assign d32[gi*32 +: 32] = dd;
    end
  endgenerate

  // ---- fp64 bank -----------------------------------------------------
  logic [BEAT_BITS-1:0] d64;
  logic [4:0] f64_l [0:(LANES64 > 0 ? LANES64 : 1)-1];
  generate
    if (EN_FP64 && LANES64 > 0) begin : g_bank64
      for (gi = 0; gi < LANES64; gi = gi + 1) begin : g_lane64
        logic [63:0] sa, sb, sc, fa, fb, fc, dd;
        assign sa = a[gi*64 +: 64];
        assign sb = b[gi*64 +: 64];
        assign sc = c[gi*64 +: 64];
        cft_opmux #(.EXP_W(11), .MAN_W(52)) u_mux (
            .op(op), .a(sa), .b(sb), .c(sc),
            .fa(fa), .fb(fb), .fc(fc));
        logic bv; logic [63:0] bd; logic [4:0] bf;
        cft_simpleops #(.EXP_W(11), .MAN_W(52)) u_simple (
            .op(op), .a(sa), .b(sb), .c(sc),
            .valid(bv), .d(bd), .flags(bf));
        logic sev; logic [63:0] sed;
        cft_seedop #(.EXP_W(11), .MAN_W(52)) u_seed (
            .op(op), .a(sa), .valid(sev), .d(sed));
        logic bv_m; logic [63:0] bd_m; logic [4:0] bf_m;
        assign bv_m = bv | sev;
        assign bd_m = sev ? sed : bd;
        assign bf_m = sev ? 5'b0 : bf;
        cft_fpfma_pipe #(.EXP_W(11), .MAN_W(52), .LATENCY(LATENCY),
                         .EXT_MUL(USE_FUSED_MUL), .EXT_NORM(USE_FUSED_NORM),
                         .EXT_ALIGN(USE_FUSED_ALIGN)) u_fma (
            .clk(clk), .rst_n(rst_n),
            .in_valid(in_valid && (prec == PREC_FP64)),
            .rnd(rnd),
            .byp(bv_m), .byp_d(bd_m), .byp_f(bf_m),
            .a(fa), .b(fb), .c(fc),
            .out_valid(), .d(dd), .flags(f64_l[gi]),
            .mul_a(mfa64[gi]), .mul_b(mfb64[gi]),
            .mul_p(mf_p[gi*106 +: 106]),
            .nrm_v(nv64[gi]), .nrm_csh(nc64[gi]), .nrm_fsh(nf64[gi]),
            .nrm_d(ns_dout[gi*2*NSEG_SLOTW +: NW64]),
            .aln_v(av64[gi]), .aln_csh(ac64[gi]), .aln_fsh(af64[gi]),
            .aln_dir(ad64[gi]), .aln_d(as_dout[gi*2*NSEG_SLOTW +: AW64]));
        assign d64[gi*64 +: 64] = dd;
      end
    end else begin : g_no_bank64
      assign d64 = '0;
      always_comb
        for (int i = 0; i < (LANES64 > 0 ? LANES64 : 1); i = i + 1)
          f64_l[i] = '0;
    end
  endgenerate

  // ---- fp128 bank ----------------------------------------------------
  logic [BEAT_BITS-1:0] d128;
  logic [4:0] f128_l [0:(LANES128 > 0 ? LANES128 : 1)-1];
  generate
    if (EN_FP128 && LANES128 > 0) begin : g_bank128
      for (gi = 0; gi < LANES128; gi = gi + 1) begin : g_lane128
        logic [127:0] sa, sb, sc, fa, fb, fc, dd;
        assign sa = a[gi*128 +: 128];
        assign sb = b[gi*128 +: 128];
        assign sc = c[gi*128 +: 128];
        cft_opmux #(.EXP_W(15), .MAN_W(112)) u_mux (
            .op(op), .a(sa), .b(sb), .c(sc),
            .fa(fa), .fb(fb), .fc(fc));
        logic bv; logic [127:0] bd; logic [4:0] bf;
        cft_simpleops #(.EXP_W(15), .MAN_W(112)) u_simple (
            .op(op), .a(sa), .b(sb), .c(sc),
            .valid(bv), .d(bd), .flags(bf));
        logic sev; logic [127:0] sed;
        cft_seedop #(.EXP_W(15), .MAN_W(112)) u_seed (
            .op(op), .a(sa), .valid(sev), .d(sed));
        logic bv_m; logic [127:0] bd_m; logic [4:0] bf_m;
        assign bv_m = bv | sev;
        assign bd_m = sev ? sed : bd;
        assign bf_m = sev ? 5'b0 : bf;
        cft_fpfma_pipe #(.EXP_W(15), .MAN_W(112), .LATENCY(LATENCY),
                         .EXT_MUL(USE_FUSED_MUL), .EXT_NORM(USE_FUSED_NORM),
                         .EXT_ALIGN(USE_FUSED_ALIGN)) u_fma (
            .clk(clk), .rst_n(rst_n),
            .in_valid(in_valid && (prec == PREC_FP128)),
            .rnd(rnd),
            .byp(bv_m), .byp_d(bd_m), .byp_f(bf_m),
            .a(fa), .b(fb), .c(fc),
            .out_valid(), .d(dd), .flags(f128_l[gi]),
            .mul_a(mfa128[gi]), .mul_b(mfb128[gi]),
            .mul_p(mf_p[gi*226 +: 226]),
            .nrm_v(nv128[gi]), .nrm_csh(nc128[gi]), .nrm_fsh(nf128[gi]),
            .nrm_d(ns_dout[gi*4*NSEG_SLOTW +: NW128]),
            .aln_v(av128[gi]), .aln_csh(ac128[gi]), .aln_fsh(af128[gi]),
            .aln_dir(ad128[gi]), .aln_d(as_dout[gi*4*NSEG_SLOTW +: AW128]));
        assign d128[gi*128 +: 128] = dd;
      end
    end else begin : g_no_bank128
      assign d128 = '0;
      always_comb
        for (int i = 0; i < (LANES128 > 0 ? LANES128 : 1); i = i + 1)
          f128_l[i] = '0;
    end
  endgenerate

  // ---- fp256 bank ----------------------------------------------------
  logic [BEAT_BITS-1:0] d256;
  logic [4:0] f256_l;
  generate
    if (EN_FP256 && LANES256 > 0) begin : g_bank256
      logic [255:0] fa, fb, fc, dd;
      cft_opmux #(.EXP_W(19), .MAN_W(236)) u_mux (
          .op(op), .a(a[255:0]), .b(b[255:0]), .c(c[255:0]),
          .fa(fa), .fb(fb), .fc(fc));
      logic bv; logic [255:0] bd; logic [4:0] bf;
      cft_simpleops #(.EXP_W(19), .MAN_W(236)) u_simple (
          .op(op), .a(a[255:0]), .b(b[255:0]), .c(c[255:0]),
          .valid(bv), .d(bd), .flags(bf));
      logic sev; logic [255:0] sed;
      cft_seedop #(.EXP_W(19), .MAN_W(236)) u_seed (
          .op(op), .a(a[255:0]), .valid(sev), .d(sed));
      logic bv_m; logic [255:0] bd_m; logic [4:0] bf_m;
      assign bv_m = bv | sev;
      assign bd_m = sev ? sed : bd;
      assign bf_m = sev ? 5'b0 : bf;
      cft_fpfma_pipe #(.EXP_W(19), .MAN_W(236), .LATENCY(LATENCY),
                       .EXT_MUL(USE_FUSED_MUL), .EXT_NORM(USE_FUSED_NORM),
                       .EXT_ALIGN(USE_FUSED_ALIGN)) u_fma (
          .clk(clk), .rst_n(rst_n),
          .in_valid(in_valid && (prec == PREC_FP256)),
          .rnd(rnd),
          .byp(bv_m), .byp_d(bd_m), .byp_f(bf_m),
          .a(fa), .b(fb), .c(fc),
          .out_valid(), .d(dd), .flags(f256_l),
          .mul_a(mfa256), .mul_b(mfb256), .mul_p(mf_p[0 +: 474]),
          .nrm_v(nv256), .nrm_csh(nc256), .nrm_fsh(nf256),
          .nrm_d(ns_dout[0 +: NW256]),
          .aln_v(av256), .aln_csh(ac256), .aln_fsh(af256),
          .aln_dir(ad256), .aln_d(as_dout[0 +: AW256]));
      assign d256 = dd;
    end else begin : g_no_bank256
      assign d256 = '0;
      assign f256_l = '0;
    end
  endgenerate

  // ---- result and per-lane flag selection ----------------------------
  always_comb begin
    case (prec)
      PREC_FP32:  d = d32;
      PREC_FP64:  d = d64;
      PREC_FP128: d = d128;
      default:    d = d256;
    endcase
  end

  always_comb begin
    lane_flags = '0;
    case (prec)
      PREC_FP32:
        for (int i = 0; i < LANES32; i = i + 1)
          lane_flags[i*5 +: 5] = f32_l[i];
      PREC_FP64:
        for (int i = 0; i < LANES64; i = i + 1)
          lane_flags[i*5 +: 5] = f64_l[i];
      PREC_FP128:
        for (int i = 0; i < LANES128; i = i + 1)
          lane_flags[i*5 +: 5] = f128_l[i];
      default:
        if (LANES256 > 0)
          lane_flags[4:0] = f256_l;
    endcase
  end

endmodule
