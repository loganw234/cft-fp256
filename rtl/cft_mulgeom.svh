// Copyright 2026 Logan W.
// SPDX-License-Identifier: Apache-2.0
//
// cft_mulgeom.svh: the chunk-column multiplier's geometry, derived.
//
// cft_fpfma_pipe decomposes a P x P significand product into columns
// of P x CFT_MUL_MCH, one per CFT_MUL_MCH-bit chunk of the multiplier
// (fp256: ten columns of 237 x 24). The multi-cycle variant builds only
// COLS of those columns per lane and iterates them over passes, and
// four modules have to agree about how many: the pipe (which builds
// them), cft_mulpass (which iterates them), cft_lanes (which paces the
// whole array at the live rung's pass count) and the unit benches
// (which pace one pipe the same way). Four copies of ceil() would be
// four places to mistype 24, so the geometry is ONE set of functions,
// included textually by every module that needs it - the way
// cft_seedop.sv includes its ROM. A module that disagrees with the
// pipe about the pass count is refused at elaboration: cft_fpfma_pipe
// cross-checks the period its paces hand it (MUL_PERIOD) against the
// count it derives for itself.
//
// Three quantities, all functions of P (= MAN_W + 1) and the pass
// BUDGET a build asks for:
//
//   chunks(P)          ceil(P / MCH)            the columns a full product needs
//   cols(P, budget)    ceil(chunks / budget)    the columns a lane builds
//   passes(P, budget)  ceil(chunks / cols)      the passes it takes - at most
//                                               the budget, sometimes fewer
//
// The last inequality is deliberate: with a budget of 4, fp256's ten
// chunks become three columns and FOUR passes, but fp128's five chunks
// become two columns and THREE passes, and fp64's three become one
// column and three passes. A rung takes the passes its own chunk count
// needs and no more; the budget bounds the widest one.
//
// Included inside module scope, so everything here is module-local.
// Locals and arguments are `integer` rather than `int`, and results
// are assigned rather than returned, because these are evaluated in
// constant context by every frontend this project builds with and
// that is the subset all of them agree on.
//
// CFT_MUL_MCH_FORMAL exists for formal/mulpass.sby and nothing else.
// The chunk is 24 bits because a 237 x 24 column is what the DSP
// fabric implements well, but nothing in cft_mulpass' mechanism - the
// pass walk, the fold, the shift-out, the level chain, the in-pass
// tree - depends on the value; every width and count is derived from
// it. A SAT solver, on the other hand, meets a multiplier as the
// hardest object it knows, and the smallest multi-pass geometry at 24
// is a 25 x 25 product it did not finish in ten minutes. Defining the
// macro narrows the chunk so the proof can bit-blast a 6 x 6 or an
// 18 x 18 and still cover every shape the module has. No build flow
// defines it: synthesis, lint and simulation all get 24, and a
// production netlist with a narrow chunk would announce itself in
// the DSP count of every rung.

`ifdef CFT_MUL_MCH_FORMAL
localparam integer CFT_MUL_MCH = `CFT_MUL_MCH_FORMAL;
`else
localparam integer CFT_MUL_MCH = 24;
`endif

function automatic integer cft_mul_chunks(input integer p);
  cft_mul_chunks = (p + CFT_MUL_MCH - 1) / CFT_MUL_MCH;
endfunction

function automatic integer cft_mul_cols(input integer p, input integer budget);
  integer nmc, bud;
  begin
    nmc = (p + CFT_MUL_MCH - 1) / CFT_MUL_MCH;
    bud = (budget < 1) ? 1 : budget;
    cft_mul_cols = (nmc + bud - 1) / bud;
  end
endfunction

function automatic integer cft_mul_passes(input integer p, input integer budget);
  integer nmc, bud, cols;
  begin
    nmc  = (p + CFT_MUL_MCH - 1) / CFT_MUL_MCH;
    bud  = (budget < 1) ? 1 : budget;
    cols = (nmc + bud - 1) / bud;
    cft_mul_passes = (nmc + cols - 1) / cols;
  end
endfunction
