# OPT-C: timing, and what the physical tools will and will not give us

A design study, 2026-09-06. Nothing here was built; nothing here is a
result. Every number is either quoted from this repository's own runs
(with the file it came from) or derived from them with the arithmetic
shown. Where I derived something I say so, and where the derivation
rests on an assumption about the fabric I name the assumption so it can
be checked rather than believed.

This is one of four parallel studies. Mine is the critical path,
pipelining, floorplanning, clock strategy and the place-and-route
tools. Where an idea belongs to one of the others I say so and stop.

**The one-line finding.** On the small-part tier the critical path is
**76% "work out how far to shift" and 10% "shift"** - of the 11.550 ns
routed fp256 data path, **8.77 ns** is the leading-zero count and the
shift-amount arithmetic, **1.58 ns** is the gather from the lane into
the shared ladder, and **1.20 ns** is the ladder itself. Everything
ranked below follows from that.

---

## 0. The measurement base

New evidence this study rests on, beyond what is already in
`docs/ARCHITECTURE.md` and `docs/BRINGUP.md`: the routed reports from
the 2026-09-06 out-of-context implementations, which are in the
scratchpad rather than the repo -
`scratchpad/build_mc_impl/{xc7k325tffg900-2,xc7k410tfbg676-2,xc7k410tffg900-2}_mp10_l1_impl/`,
each with `paths_routed.rpt`, `timing_routed.rpt`,
`util_routed{,_hier}.rpt`, and the QOR lines collected in
`build_mc_impl/summary.txt`. All at `MUL_PASSES=10`, `FUSE_NORM=1
FUSE_ALIGN=1`, Vivado 2026.1, speed file `-2 PRODUCTION 1.12
2017-02-17` on both parts.

### 0.1 The routed fp256 path, taken apart

| | K325T-2 @100 | K410T-2 @100 | K410T-2 @80 |
|---|---|---|---|
| routed WNS | **+0.096** | **-0.957** | +0.607 |
| data path delay | 9.538 ns | 10.591 ns | 11.550 ns |
| **logic** | **1.750 ns (18.3%)** | **1.749 ns (16.5%)** | 2.008 ns (17.4%) |
| **route** | **7.788 ns (81.7%)** | **8.842 ns (83.5%)** | 9.542 ns (82.6%) |
| logic levels | 20 | 19 | 23 |
| endpoint | `g_normseg/cs_r_reg[376]/R` | `.../cs_r_reg[376]/R` | `.../cs_r_reg[511]/R` |
| endpoint **pin** | reset | reset | reset |
| TNS / failing endpoints | 0.000 / 0 | -288.391 / 650 | 0.000 / 0 |
| slices used | 27,333 (53.65%) | 27,518 (43.30%) | (same netlist) |
| LUT / slice | 3.50 | 3.48 | |
| unique control sets | 441 | 441 | 441 |

Three things fall straight out of that table and none of them were
written down before:

1. **The design is a wire design.** 82-84% of the path is route on
   every run, on both parts, at both asks. Logic optimisation has
   about 1.8 ns to work with; wire has about 8.5.
2. **The path ends on a flip-flop's synchronous-reset pin, not its
   data pin.** All three of the worst paths in the 325T report end at
   `cs_r_reg[*]/R`. That is not cosmetic - see idea 3.
3. **The 325T and 410T netlists are identical** (95,695 vs 95,773
   LUT, 43,365 FF both, 441 control sets both, same DSP and BRAM) and
   their **logic delay is identical to the picosecond** (1.750 vs
   1.749 ns). The whole 1.053 ns difference is route: 8.842 - 7.788 =
   **1.054 ns**, which is 100.1% of it.

### 0.2 Where the 11.55 ns actually goes

From the fully detailed trace in
`xc7k410tfbg676-2_mp10_l1_impl/paths_routed.rpt` (the 80 MHz run, the
only routed report in hand with the whole cell-by-cell walk), summing
the segments between named nets:

| segment | what it is | cumulative | cost |
|---|---|---|---|
| clk→Q + first hop | `s10_mag_reg[591]` out | 1.546 | 1.01 ns |
| LUT3 + 5×CARRY4 | 64-bit chunk zero-detect | 2.074 | 0.53 ns |
| `chunk28_in` → 4 LUTs | chunk priority resolve | 4.433 | 2.36 ns |
| 7 LUTs + CARRY4 | `lzc64` + the `NW-1-msb` subtract | 9.306 | 4.87 ns |
| 3 LUTs → `ns_csh[0]` | the amount reaching `cft_lanes`' mode mux | 10.885 | 1.58 ns |
| 2 LUTs → `cs_r/R` | normseg slot mux + one ladder level | 12.087 | 1.20 ns |

Data-path cumulative (the Path column less the 0.537 ns clock-net
delay): **0 → 1.537 → 3.896 → 8.769 → 10.348 → 11.550**. So
**8.77 ns of 11.55 (76%) is the leading-zero count and the amount
arithmetic, 1.58 ns (14%) is the gather into `cft_lanes`' mode mux, and
1.20 ns (10%) is the ladder.** The path has 18 routed net hops
averaging **0.530 ns each**, and 23 logic levels contributing 2.008 ns
between them. To first order the period is *hop count × 0.53 ns*, and
almost every hop is spent deciding a shift distance.

That is the sentence this whole study turns on. It also explains why
the SPLIT sweep in `rtl/cft_normseg.sv`'s header found SPLIT=1 best and
then stopped helping: SPLIT moves ladder levels across the register,
and the ladder is 10% of the problem.

### 0.3 The second wall, which nothing has measured on a Kintex

`build_mc_z020/xc7z020clg484-1_mp1_l0_synth/paths_synth.rpt`, the one
configuration where the datapath was not worst:

    u_engine/beats_total_reg[1]/C -> u_engine/g_reader[0].rd_resv_reg[0][13]/D
    16.157 ns, 45 logic levels, 36 CARRY4, logic 8.853 ns (54.8%)

That is `rtl/cft_engine_stream.sv` lines 661-729: a 64-bit
`beats_total - issued_s`, into `burst_len(rem, addr, cnt_s, resv_s)`,
into `launch`, into a 16-bit `rd_resv` update - **144 bits of chained
carry in one cycle**, and unlike the datapath it is *logic*-dominated
(55%), so placement will not save it. On -1 Artix-class fabric it is
16.157 ns; scaling by the same-design K325T-2 / A200T-1 ratio measured
in `build_mc_7s/summary.txt` (9.698/17.422 = 0.557, and 9.956/17.785 =
0.560 for the other configuration - consistent to 0.5%) puts it near
**9.0 ns on a Kintex-7 325T at -2, i.e. about 111 MHz.**

It has never appeared in a K325T report because with the ladders on the
datapath always came first, and `hw/impl_krnl_ooc.tcl` asks for
`report_timing -max_paths 3` - which on the 325T returned the *same
path* three times (three different `R` pins on one fanout-90 net). **The
measurement rig cannot currently see the second wall.** See §7.

Every "we could reach X MHz" claim below is therefore capped at ~111
MHz until this path is either measured on a Kintex or fixed.

---

## 1. Ranked ideas

Ranked by *expected nanoseconds recovered, discounted by the
probability the mechanism holds and by the risk it carries*. That is
not the same as the order to run them in - §5 gives that, and the
cheapest idea here is third.

Throughout: latency is free (the contract prices bits, not cycles);
changing an arithmetic result is not permitted; and the RTL must stay
Yosys-clean, so anything I propose is either a register insertion, a
Vivado-only `(* attribute *)` (which Yosys ignores), a constraint file,
or a build flag.

---

### 1. Pipeline the leading-zero cone: split S11 at the LZC/ladder seam

**Mechanism.** `rtl/cft_fpfma_pipe.sv` lines 880-930 compute, in one
`always_comb` between the `s10_mag` register and the S11 registers:
a 717-bit zero-scan over 12 chunks, a 12-way priority encode, a 64:1
chunk mux, `lzc64` on the selected chunk, `NW-1-msb`, and the split
into `n11_csh`/`n11_fsh`. Those go out of the lane as
`nrm_csh`/`nrm_fsh`, through `cft_lanes`' mode mux into `ns_csh`/`ns_fsh`
(`rtl/cft_lanes.sv` 295-327), through `cft_normseg`'s slot mux, and into
the first ladder level - all in the same cycle.

Insert one register between the LZC and the amount consumers. Concretely:
register `n11_valw`, `n11_lsh` and `n11_empty` per lane, and let the
existing S11/S12 structure start from those. `LATENCY` 15 → 16; the
rounding-attribute delay line's taps at 1, 13, 14 shift with it (three
hardcoded sites, per `docs/ROADMAP.md`'s "LATENCY proved to be threaded
properly"); `cft_normseg`'s two registers and `cft_reduce_acc`'s
`ADD_LATENCY = LATENCY + 1` follow.

**What it buys, with arithmetic.** Working in the §0.2 trace's
data-path cumulative (its Path column less the 0.537 ns clock net), the
candidate cut points sit at 1.537, 3.896, 8.769, 10.348 and 11.550 ns.
**There is no good two-way split**: cutting after the subtract gives
8.77 / 2.78, and cutting at `ns_csh` gives 10.35 / 1.20. The cone has
to be cut *internally*, twice - after the chunk zero-detect and after
the `NW-1-msb` subtract - which gives **1.54 / 7.23 / 2.78** as the
trace stands. Still lopsided, because the middle segment is `lzc64`
plus the 64:1 chunk mux; combined with idea 7 (a balanced-tree LZC,
which removes ~5 of the 18 hops at 0.53 ns each, ~2.6 ns) the three
segments become roughly **1.5 / 4.6 / 2.8 ns**, plus ~0.36 ns of
clk→Q-and-setup overhead each: **1.9 / 5.0 / 3.1** on the 410T's scale,
or **1.6 / 4.1 / 2.6** scaled to the 325T (× 9.538/11.550 = 0.826).

**Read that as a direction, not a frequency.** It is a projection
through two independent estimates and a cross-part scaling. The
defensible form of the claim is: **this idea, with idea 7, removes the
datapath from the critical-path conversation on every part, and the
frequency you then get is decided by idea 4.** On the K325T that is
105 → ~111 MHz while the engine's ~9.0 ns path stands, and something
between 150 and 240 MHz after it is fixed. On the U50, where the same
path is 5.585-5.821 ns out of context (`build_mc/summary.txt`), the
same reasoning applies against the shell's ~141 MHz ceiling.

**Cost.** +1 or +2 cycles of latency (free). Flip-flops: the widest
lane registers `n11_valw` (NW bits) + `n11_lsh` (10) + `n11_empty` (1);
across all four banks that is 8×89 + 4×176 + 2×356 + 1×728 = **2,856
FFs**, against 43,365 used of 407,600 available - 0.7% of the device's
flip-flops for the whole tile. LUTs approximately unchanged. Complexity:
this is the file the contract rests on, and `docs/ROADMAP.md` records
that the last attempt to add a stage to it produced *garbage, not
drift*, because `cft_fpfma_pipe` is a synchronised multi-path pipeline -
S7 consumes `s6_mp` alongside sign/exponent/alignment control that
travelled its own path. **Every parallel path crossing the new boundary
must be rebalanced in the same commit.**

**Gate.** The pipe's own depth guard fires at elaboration if the
rebalance is wrong (it did last time, which is the evidence the guard
works). Then: `tb/test_fpfma_fp{32,64,128,256}.py`, `test_krnl*`,
`test_normshare`/`test_normseg` for the shared path, `test_mulpass` and
`test_mulcycle` at several `MUL_PASSES` (the pacing must still hold),
and the 111,278-vector RTL suite. A combinational equivalence miter of
the old and new LZC cone in `formal/` on the `equiv.sby` pattern is
cheap and worth having, since a leading-zero cone is a SAT-friendly
object in a way `cft_mulpass` was not.

**Doctrine.** Brushes the S11-split scar: `docs/BRINGUP.md` records that
an earlier S11 split promised 2% out of context and *regressed in the
shell*. Two differences make this one worth re-attempting rather than
being ruled out by that: that split moved ladder levels (10% of the
path) where this one cuts the LZC (79%), and the shell regression was
measured on the U50 with the ladders off, whereas the small-part tier
has the ladders on and a different endpoint. It must still be measured
in the shell before being believed - that is exactly the rule the
project learned.

---

### 2. Per-bank pipeline enables, and multicycle exceptions on the wide rungs

**This is the unusual one. It exploits `MUL_PASSES` for timing rather
than area, and the machinery is already built.**

**Mechanism.** `rtl/cft_lanes.sv` 165-183 generates one enable `en`
whose period is the *live rung's* pass count: with `MUL_PASSES=10`,
`cft_mulgeom.svh` gives NP256=10, NP128=5, NP64=3, NP32=1. Every stage
register in every pipe, and both shared ladders, advance only on `en`.
So when fp256 is the live rung, **every enabled-register-to-
enabled-register path in the array has ten clock periods to settle, and
Vivado times all of them as single-cycle.** At 100 MHz that is 100 ns of
real budget being reported against a 10 ns constraint.

It cannot be claimed today, because `en` is global: in fp32 mode `en` is
high every cycle and the fp256 bank's registers advance every cycle too,
so the fp256 LZC → ladder path really is single-cycle in that mode.

The change is to make each bank's enable its own:

```
    en256 = en && (prec == PREC_FP256)     // and likewise 128, 64
    en32  = en                             // fp32 is single-pass always
```

A bank that is not the live rung then freezes, its outputs hold, and its
contribution to `ns_din`/`ns_csh`/`ns_fsh` is a constant that the mode
mux discards anyway. With that in place the following are **true by
construction**, not asserted:

```
    set_multicycle_path -setup 10 -hold 9 \
        -from [get_cells u_lanes/g_bank256.u_fma/*_reg[*]] \
        -to   [get_cells u_lanes/g_normseg.u_normseg/*_reg[*]]
    #   and -setup 5 -hold 4 from g_bank128, -setup 3 -hold 2 from g_bank64
```

because the fp256 bank's `s10_mag` can only change on an edge where
`en256` is high, which requires `prec == FP256`, which forces the
global period to NP256 = 10, so the next change is at least ten cycles
away - and `prec` is already required to be stable with the pipe drained
(`cft_normseg.sv`: "in the engine `prec_r` cannot move mid-flight").

**What it buys.** At `MUL_PASSES=10` the fp64, fp128 and fp256 datapaths
leave the timing report entirely. What remains from the array is the
fp32 path: same shape but over `NW32 = 78` bits and 2 chunks instead of
717 and 12, so it loses the 12-way priority resolve (2.359 ns in §0.2)
and part of the chunk mux while keeping the 64-bit LZC, the subtract,
the gather and the ladder. Dropping that segment gives 11.550 - 2.359 =
9.191 ns on the 410T's scale, and scaling to the 325T (× 9.538/11.550 =
0.826) gives **about 7.6 ns → ~132 MHz** - at which point idea 4's
~9.0 ns engine path is the wall and the delivered number is **~111
MHz**. (Both steps are soft: the 410T trace being scaled *met* its ask,
so it is not a max-effort path, and the fp32 lanes' gather still crosses
the same physical distance to the shared ladder even though its logic is
shallower. The 132 figure is an upper bound on the array's contribution,
not a prediction.)

So: **on its own, worth ~5 MHz on the K325T; combined with idea 4,
worth ~105 → ~130 MHz; and it is the only idea here that costs
essentially no logic.** Its real value is on the Artix-7 200T and any
`-1` part, where the same 1.8× fabric penalty applies to a path that no
longer exists.

**Cost.** A few LUTs of enable gating. Zero latency change in
enabled-edge terms. A power saving as a side effect (three banks idle).

**What has to be proven, and it is the hard part.** A multicycle
exception that is wrong is a **silent wrong answer**, which is the one
failure class this project refuses. Three gates, in order:

1. An SVA or a formal property in `formal/`: *a bank's stage registers
   do not change on any cycle where that bank's enable is low.* This is
   a one-line liveness-free safety property and a natural fit for the
   existing `sby` harness.
2. The existing determinism bench - "the same program and the same
   stream give the same bits at every value of the parameter"
   (`tb/test_mulpass.py`, `test_mulcycle.py`) - re-run with per-bank
   enables, plus the precision-switch cases from `tb_mulshare` (64
   beats across eight precision switches with the pipe draining) which
   are exactly the transitions the exception depends on.
3. A routed build **plus** `hw/report_cdc.tcl`'s `check_timing`, because
   the failure mode of a wrong `-from` collection is that paths silently
   leave the analysis. An unconstrained path is not a met path.

**Doctrine.** Brushes "determinism must not depend on the issue
cadence" - and survives, because the cadence is unchanged: `en` is
generated exactly as it is now and every issuer sees it. What changes is
which registers *ignore* it, and a frozen bank contributes nothing to
any result. It also brushes `docs/ARCHITECTURE.md`'s "a reduced clock
changes nothing about results"; that stays true, since this is a
constraint-file claim about a netlist, not an arithmetic one.

---

### 3. Take the ladder's zero-fill off the flip-flop reset pin

**Cheapest idea in this document. Run it first.**

**Mechanism.** `rtl/cft_normseg.sv` writes each ladder bit as
`AML[mode] ? cs[gk][gb-SH] : 1'b0` - a mux whose false arm is a
constant zero. Vivado lifts that zero into the destination flip-flop's
**synchronous reset**: every worst path in every 7-series routed and
synthesised report ends at `cs_r_reg[*]/**R**`, never `/D`, and the last
net before it has fanout 90 (325T) or 62 (410T). `cs_r` has no reset in
the RTL at all; this reset was *inferred from the data expression*.

The R pin costs a great deal more setup than the D pin. Measured, on
one part at one corner so the comparison is clean -
`build_mc_z020/xc7z020clg484-1_mp10_l{0,1}_synth/paths_synth.rpt`, the
same design one parameter apart:

| endpoint | library arc | required-time adjustment | setup time |
|---|---|---|---|
| `s11_valw_reg[512]/D` (ladders off) | `Setup_fdre_C_D` | +0.077 | **-0.077 ns** |
| `cs_r_reg[450]/R` (ladders on) | `Setup_fdre_C_R` | -0.524 | **+0.524 ns** |

**0.601 ns of difference on the same flip-flop, on the -1 part.** On the
-2 Kintex the R-pin figure is a measured **0.304 ns** (routed) / 0.306
(synthesis); the D-pin figure at -2 is not in hand, but even taking it
as zero the recovery is **0.30 ns of a 10.000 ns period - 3.2× the
325T's entire +0.096 ns of routed margin.**

**How to make it happen without touching the arithmetic.** Two levers,
both function-preserving by construction:

- `(* extract_reset = "no" *)` on `cs_r` (and `dout`) in
  `cft_normseg.sv`. Vivado-only synthesis attribute; Yosys ignores
  unknown attributes, so the open-flow gate is untouched.
- `synth_design -control_set_opt_threshold <N>` as a build-flag
  alternative, if the attribute is unavailable in some flow. Global,
  so less surgical.

**Will it pay?** The term has to go somewhere, and it goes into the LUT
driving D. The last LUT on the path is a **LUT5** on the 325T
(`cs_r[449]_i_1__0`) and a **LUT2** on the 410T (`cs_r[511]_i_1__0`) -
one and four spare inputs respectively - so on the evidence in hand the
fold is free and the full ~0.30 ns is recoverable. If instead Vivado
adds a level it costs ~0.043 ns of logic and ~0.5 ns of route, and the
change is a 0.24 ns *regression*. **This is a coin flip that one
30-minute run settles, and the payoff side moves the 325T from 105 to
about 108 MHz for zero area and zero latency.**

**Gate.** No arithmetic changes, so the RTL suite is a formality; the
real gate is the routed path delay, read the correct way (§4). Also
worth reading `report_control_sets` before and after: the design has 441
unique control sets for 43,365 flops (~98 flops each), which is
*healthy* - so the fragmentation worry I started with is refuted by the
data, and only the setup-time argument survives.

---

### 4. Pipeline the engine's `beats_total → rd_resv` chain

**Mechanism.** §0.3. `rem = beats_total - issued_s` (64-bit),
`burst_len(rem, addr, cnt_s, resv_s)`, `launch`, `rd_resv +=` - 45
levels and 36 CARRY4 in one cycle, 55% logic.

The fix is ordinary sequential-logic hygiene and does not touch any
result: maintain `rem` as its own register (decremented by `len` at
launch rather than recomputed from two 64-bit values), and compute the
burst-length candidates one cycle ahead so `burst_len` selects among
registered terms. `launch` gains a cycle of decision latency, which
costs at most one bubble per burst against bursts of up to 256 beats.

**What it buys.** Removing a 144-bit carry chain from the cycle. On -1
Artix-class fabric the path is 16.157 ns with 8.853 ns of it in
carries; cutting the chain in two takes the logic to ~4.4 ns and the
whole path to roughly **9.5 ns on -1 / ~5.3 ns on a K325T-2 → the
engine stops being the wall.** That is what unlocks ideas 1 and 2 from
~111 MHz to whatever the datapath then supports.

**Cost.** Small LUT/FF cost. One cycle of AR-decision latency, which is
throughput, not bits. Complexity is moderate but the module has a strong
bench (`test_krnl`, `test_krnl_cycles`, the RLAST placement check, the
4KB-boundary logic).

**Gate.** `tb/test_krnl*.py` including `test_krnl_cycles` (which would
show any added bubble as a change in the 1.250 marginal cycles/beat -
that regression is a *measurement*, not a failure), `test_krnl_faults`,
and hw_emu. This is partly Study D's territory - the burst policy is a
system property - so I hand the *policy* question over and keep only the
claim that the arithmetic must not be 144 bits deep in one cycle.

---

### 5. Floorplan the small-part tile: pblock `u_lanes` around the two ladders, exile `u_seq`

**Mechanism.** From `xc7k325tffg900-2_mp10_l1_impl/util_routed_hier.rpt`:

| instance | LUT | share |
|---|---|---|
| `u_lanes` | 62,583 | 65.4% |
| ├ `g_normseg.u_normseg` | 8,004 | the convergence point |
| ├ `g_alignseg.u_alignseg` | 8,614 | the other convergence point |
| ├ `g_bank256.u_fma` | 11,364 | |
| ├ `g_bank128` ×2 | 8,854 | |
| ├ `g_bank64` ×4 | 10,704 | |
| ├ `g_lane32` ×8 | 13,217 | |
| `u_seq` | **26,051** | **27.2%**, and on no reported critical path |
| `u_engine` | 6,324 | |
| `u_csr` | 827 | |

With the ladders on, **all fifteen lanes converge combinationally on two
physical blocks of 8,004 and 8,614 LUT.** The routed path on the 325T
walks `SLICE_X127Y143 → X121 → X126 → X123 → X122 → X118 → X112 → X110
→ X111 → X92 → X79 → X68 → X61` - **66 slice columns**, from a lane in
`g_bank64` to `g_normseg`, with the last four hops (0.914, 0.720, 0.676,
0.555 ns = 2.87 ns, 30% of the path) being pure long-distance travel.
Nothing stops the placer putting 26,051 LUT of sequencer in that
corridor.

The proposal: one `pblock` holding `u_lanes` in a compact region with
the two ladders at its centre and the banks around them, and a second
holding `u_seq` outside that region. Sized so the local slice occupancy
is 60-70% rather than the 53.65% the placer chose device-wide.

**What it buys.** Unquantified, and I will not pretend otherwise - but
§2 below shows that a 33% larger die cost this design 13.5% of its route
delay purely through spread, which is direct evidence that this
netlist's wire is set by how far the placer lets it wander. Recovering
even a third of the 2.87 ns spent on the last four hops is 0.96 ns, or
105 → 117 MHz on the 325T.

**Cost.** Constraint files that must be maintained per part. A pblock
that is too tight causes routing congestion and is worse; a pblock is a
lever with a wrong side.

**Gate.** Routed path delay at a fixed ask, compared against the same
ask unpblocked. Two runs.

---

### 6. Alveo: pin the single CU to one SLR, and sweep the directives that have never been swept

**Mechanism.** `hw/link_quad.cfg`'s own header says it: *"the single-CU
design spans both SLRs of the VU35P, and its critical path is in the
fp256 normalize/round stage - the kind of path an SLR crossing ruins."*
`docs/ROADMAP.md` names the lever - "`PLACE_DIRECTIVE=SSI_*` and
per-kernel pblocks are what the directive support exists for" - and
**nothing in this repository has used it.** `hw/link.cfg` has no `slr=`
line; `hw/rebuild-2022.sh` exposes `PLACE_DIRECTIVE`, `ROUTE_DIRECTIVE`,
`PHYS_OPT` and `VPP_PROPS`, and the only recorded use is
`RETIMING=1 PHYS_OPT=1` (`docs/VALIDATION.md`, the tip pair).

Three untried things, in increasing cost:

1. `[connectivity] slr=cft_krnl_1:SLR0` in `hw/link.cfg`. One tile is
   123,420 LUT against the 351K/353K of *dynamic-region* LUT per VU35P
   SLR that `docs/PLATFORMS.md` takes from UG1120 - it fits at 35% - so the
   crossing is optional, and an SLR crossing on this fabric is worth
   about a nanosecond.
2. `PLACE_DIRECTIVE` sweep. The script already documents the valid set
   (`Explore`, `ExtraTimingOpt`, `ExtraPostPlacementOpt`,
   `AltSpreadLogic_*`, `ExtraNetDelay_*`, `SSI_*`). `docs/ROADMAP.md`'s
   own framing is right: "a design sitting near its edge does not have
   ONE achievable WNS; it has a distribution". The quad missed 135 MHz
   by 0.113 ns twice - inside the spread a directive moves.
3. `ROUTE_DIRECTIVE=AggressiveExplore` and `HigherDelayCost` on a
   route-dominated design. `AlternateCLBRouting` is the interesting one
   for a design with 18 net hops of local-ish travel.

**What it buys.** Unmeasured on this design; the industry-typical
directive spread is 3-7% of period, and the SLR pin is worth ~1 ns if
the crossing is really on the path. On a 6.842 ns path that is 15%.

**Cost.** Build time only: 1h46m per point at 130 MHz, 3h56m for a 145
quad, ~12 GB peak, two concurrent on a 31 GB box (`docs/BRINGUP.md`).

**Gate.** `kernel_wns_ns` from the manifest, never `routed_wns_ns` -
and the reason is worth repeating with the number: `hw/rebuild-2022.sh`
line 356 comments `routed_wns_ns` as "whole design, shell included",
and the 130 MHz card-day quad is the proof - its global WNS is negative
because `hbm_aclk` misses by 0.001 ns on 1 endpoint of 39,282, a shell
clock the kernel does not touch.

---

### 7. Rewrite `lzc64` and the chunk scan as balanced trees

**Mechanism.** `rtl/cft_fpfma_pipe.sv` writes the leading-zero count as
two *priority loops*:

```
    for (int ci = NCH-1; ci >= 0; ci--) if (chunk == -1 && ...) chunk = ci;
    function lzc64: for (int i = 0; i < 64; i++) if (x[i]) r = 63 - i;
```

Vivado maps the chunk zero-detect well (5 CARRY4 for 0.484 ns and no
routing) but the rest badly: §0.2's trace shows 4.87 ns across 7 LUT
levels and 7 net hops for `lzc64` plus the subtract.

The replacement is the standard log-depth (valid, count) merge:
`v = vL | vR; cnt = vL ? {0,cntL} : {1,cntR}`, folded 4-wide so each
level is one LUT6 for the validity and one LUT6 per count bit. Over 717
bits that is `ceil(log4(717)) = 5` levels instead of the 13 the trace
shows between `s10_mag` and `ns_csh`.

**What it buys.** Removing ~5 of the 18 net hops at 0.53 ns each =
**~2.6 ns**, i.e. 9.538 → ~6.9 ns on the 325T, **105 → ~145 MHz** -
except that the engine wall at 9.0 ns binds first, so alone it delivers
~111 MHz. It is the natural partner to idea 1: idea 1 splits the cone,
idea 7 shortens it, and together they are what makes a three-way split
land near even.

**Cost.** LUTs, for the fp256 lane, counting a 4-wide merge: validity
is 180 + 45 + 12 + 3 + 1 = 241 LUTs; the count select is ~360 + 180 +
72 + 24 + 10 ≈ 646; total **~890 LUT for the widest lane** and, scaling
by total window bits (624 + 660 + 690 + 717 = 2,691), **~3,200 across
the tile** - about 3.3% of 95,695 *before* subtracting the cascade it
replaces, so the net figure is smaller and could be negative.
Complexity: moderate, self-contained, and the function is a textbook
one.

**Gate.** A combinational equivalence miter in `formal/` on the
`equiv.sby` pattern - old cone vs new cone, `bmc` depth 2, complete over
the whole 717-bit input space. This is exactly the shape the simpleops
miter already proves and exactly *not* the shape `mulpass_real.sby`
failed at (no multiplier). Then the vector suite.

**Doctrine.** None. It is a pure restructuring of a combinational
function with a complete proof available.

---

### 8. A leading-zero anticipator beside S9/S10

**Mechanism.** `docs/ROADMAP.md`'s own v2 list names it - "a
leading-zero anticipator beside S9/S10 so S11 starts from a registered
amount". The classic LZA computes the shift distance from the *pre-add*
operands in parallel with the add itself, giving the true count or the
true count minus one; the ±1 is corrected by a single conditional 1-bit
shift after the coarse shift, which leaves the normalised significand
bit-identical.

**What it buys.** In principle the whole 8.77 ns amount cone moves off
the post-add path, leaving S10 → ladder at ~2.4 ns. In practice the LZA
still needs a leading-one detect on its own string, so what actually
moves is the *dependence*, not the depth: the detect runs concurrently
with the S9/S10 split-carry adds instead of after them.

**Why it is ranked below 1 and 7 despite the bigger prize.** Ideas 1 and
7 get most of the same benefit through register insertion and a
restructuring with a complete proof; the LZA is a *different algorithm*
in the most safety-critical block, its correction case interacts with
the empty-window argument in `stage11`'s comment (the subnormal/epsilon
reasoning), and it costs a ~717-bit propagate/generate string per wide
lane. It is the right answer for a v2 rebalance, not the right answer
for the next month.

**Gate.** The full suite plus a formal miter of "LZA + correction" vs
"add then LZC" - harder than idea 7's because the miter now spans the
adder.

---

### 9. Stop inferring SRLs in the lane pipes

**Mechanism.** The routed 325T uses **2,688 LUTs as shift registers**,
2,680 of them inside `u_lanes` (`util_routed_hier.rpt`: 600 in
`g_bank256.u_fma`, 309/308 in the fp128 lanes, ~171 each in fp64,
~98 each in fp32). Those are the pipes' delay lines. An SRL16E/SRL32E
lives only in a **SLICEM**, cannot be retimed, cannot be replicated by
`phys_opt`, and pins its lane's delay line to a SLICEM column.

`synth_design -shreg_min_size 100` (or `(* srl_style = "register" *)`)
turns them into ordinary flip-flops.

**What it buys, and the honest uncertainty.** Flip-flops are free here:
43,365 of 407,600 used (10.6%), and the design's 27,333 slices already
contain 218,664 FF sites against 43,365 in use, so ~43,000 more FFs
plausibly cost **zero extra slices**. The gain is placement freedom -
the lanes stop being anchored to the ~31% of slice columns that are
SLICEM (325T: 64,000 memory-capable LUTs of 203,800). Whether that
matters is *not* something I can settle from the reports: the design
needs at minimum 4,960/4 ≈ 1,240 SLICEM slices out of 16,000 available,
so there is no global shortage, and the 8,989 SLICEM slices actually
used are mostly opportunistic. **Expected value: small and positive,
cost: one flag, one run.** It is on the list because it is the cheapest
untested placement lever in the flow.

It is also the *open-flow* argument (idea 10): SRL packing is a
nextpnr-xilinx special case, and plain flip-flops are the most-travelled
path through that packer.

---

### 10. Make the netlist the open flow can actually place

**This is the answer to "does the open flow's placer need different RTL
than Vivado's". Yes, and specifically.**

`docs/PLATFORMS.md` records three things about openXC7/nextpnr-xilinx,
all sourced:

- STA is "very rudimentary, down to not even honoring timing
  constraints";
- the analytical placer locks up on designs with **high distributed-RAM
  usage**;
- **no published openXC7 design above 50% utilisation could be found on
  any part.** The K325T tile is 46.96% of LUTs and **53.65% of slices**.

Three consequences for the RTL, none of which apply to Vivado:

1. **A placer that does not honour timing constraints cannot rescue a
   design that is 82% wire.** Under Vivado, ideas 5 and 6 are
   alternatives to ideas 1 and 7; under nextpnr they are not available
   at all. **Pipelining is the only lever that survives the open flow**,
   which is an independent argument for ranking idea 1 first.
2. **Move `u_seq`'s distributed RAM to block RAM.** `u_seq` carries
   1,912 LUTRAM of the design's 2,272 - the exact construct the
   lock-up report names - while the K325T has 445 BRAM tiles and the
   design uses 36. This is a change with an open-flow-specific
   motivation and no Vivado-side cost worth mentioning. (The
   *contents* of those memories are Study D's and the array study's
   business; I am claiming only that their implementation should be
   BRAM on this target.)
3. **`MUL_PASSES=10` already shrinks the blast radius of
   nextpnr-xilinx#159 by 79%** (262 → 56 DSPs). Going further: with
   `(* use_dsp = "no" *)` the tile has none, and #159 becomes
   irrelevant rather than merely likelier to be caught. The area cost
   can be derived cleanly from two rows of `docs/ARCHITECTURE.md`'s own
   tables that differ *only* in whether Vivado ran out of DSP columns:
   `xc7z020, MUL_PASSES=1, ladders on` is 120,282 LUT with 220 DSPs
   (capped) and `xc7k325t, MUL_PASSES=1, ladders on` is 109,225 LUT
   with 262 - same fabric family, same mapping, so the 11,057 LUT
   difference bought back 42 DSPs, **263 LUT per displaced DSP**. At 56
   DSPs that is **14,743 LUT**, taking the ten-pass tile from 98,929 to
   about **113,700, or 55.8% of a K325T.** Soft, because the displaced
   Zynq DSPs were the narrower columns and fp256's is the wide one; and
   the timing cost is real, because `cft_mulpass` runs on the *wall*
   clock and a fabric 237×24 column would have to close in one wall
   cycle. **Worth one 12-minute synthesis run to price, before anyone
   assumes it is impossible.**

---

### 11. What I looked at and would not do

- **Split the normalise ladder so fp256 has its own.** The brief asks
  whether the fp256 path can stop setting the clock by splitting the
  normalise stage. Spatially: no. Giving the fp256 rung a private
  ladder costs about 8,000 LUT (the ladder is 720 bits either way, and
  `g_normseg` is 8,004) and buys only the **1.2 ns** of gather-plus-
  ladder in §0.2, because the 8.77 ns of LZC and amount arithmetic stays in the lane
  regardless. **Not worth 8,000 LUT for 1.2 ns.** The split that works
  is temporal, and it is idea 2.
- **A second clock inside a tile.** Refuse. `hw/report_cdc.tcl` exists
  to *verify* the prediction that "the kernel here is single-clock
  (ap_clk), so its own CDC surface should be empty". A second clock
  inside one tile puts a synchroniser between the issue point and the
  array, and a synchroniser is a place where determinism becomes a
  timing argument instead of a structural one. The contract's
  "clock-independent by construction" survives *any* single clock and
  survives *no* crossing. Between tiles it is already solved and
  already free: `docs/LAYOUTS.md` records that the platform has **two
  kernel clocks** and `v++ --clock.freqHz <f>:<cu>` assigns per CU, so
  a heterogeneous layout gets per-rung clocks with no RTL at all.
- **Retiming as a headline.** `-retiming` reads +1.681 ns out of
  context and **-0.141 in the shell on a quad** (`docs/ROADMAP.md`) -
  worse than without. It shortens logic, and this design's problem is
  wire. Keep it on where it is already on; do not expect it to move
  anything.
- **Carry-save / redundant forms on the wide adds.** `docs/NOVEL.md`
  entry 6's lesson, and the traces agree: the CARRY4 chains in the
  critical path cost 0.053-0.076 ns per level with **zero** net delay
  between them. The carry chains are the fastest thing on the path.

---

## 2. Why the 410T is slower than the 325T

Same speed file, lower occupancy, bigger die, and 11% slower. Here is
what I think is happening and how to break it.

### What it is not

- **Not the package.** `fbg676` and `ffg900` gave *bit-identical*
  results - both -0.957 ns, both 10.591 ns, both the same startpoint
  and endpoint. An out-of-context design has no bonded I/O.
- **Not the timing model.** Both reports read `Speed File: -2
  PRODUCTION 1.12 2017-02-17`.
- **Not SSI.** No Kintex-7 part is a stacked-silicon device; both are
  monolithic dies, so there are no SLL crossings to blame.
- **Not the netlist.** 95,695 vs 95,773 LUT, 43,365 FF both, 56 DSP
  both, 36 BRAM both, 441 control sets both, and the identical
  control-set histogram (42,712 CE+SyncReset, 644 CE+Set, 9
  CE+AsyncReset) on each.
- **Not logic.** 1.750 ns vs 1.749 ns. **Synthesis, which has no
  placement, priced the two parts at 9.698 and 9.708 ns - 0.1%
  apart.** Routing separated them by 11%.
- **Not packing.** 3.50 vs 3.48 LUTs per slice; 27,333 vs 27,518
  slices occupied - 0.7% apart.

Everything that differs is wire: **+1.054 ns of route, which is 100.1%
of the +1.053 ns of path.**

### What it is

**The placer spread the same netlist over a bigger die, and this design
pays for distance rather than logic.**

The 410T is not "a 325T with spare room". In fabric-tile terms it is a
third bigger. Counting a 7-series CLB column segment as 5 CLBs = 10
slices, a DSP48E1 tile as 5 CLB rows holding 2 DSPs, and a RAMB36 tile
as 5 CLB rows (UG474/UG479 geometry - **this is the assumption to check
if the arithmetic is challenged**):

| | CLB tile-slots | DSP tiles | BRAM tiles | total | hard-block share |
|---|---|---|---|---|---|
| K325T | 50,950/10 = 5,095 | 840/2 = 420 | 445 | **5,960** | 14.5% |
| K410T | 63,550/10 = 6,355 | 1540/2 = 770 | 795 | **7,920** | 19.8% |

Die area ratio **1.329**; linear ratio **√1.329 = 1.153**. A placer that
spreads in proportion to the fabric it is given would add **15.3%** of
wire delay. **Measured: 8.842/7.788 = 13.5%.** The design compacted very
slightly against the die, and otherwise did exactly what an
area-proportional spread predicts.

Two supporting observations:

- **The extra area is columns, and the extra travel is horizontal.**
  Start-to-end, the 325T path runs SLICE_X127 → X61 (**66 columns**)
  and the 410T X166 → X85 (**81 columns, +22.7%**); counting the full
  column span the path visits, it is 66 (X61-X127) against **90**
  (X85-X175), **+36.4%**. Both exceed the 15.3% isotropic prediction,
  which is what you expect when the added fabric is DSP and BRAM
  *columns* rather than rows. The 410T carries 47% more
  DSP sites and 43% more BRAM sites per slice than the 325T, and this
  design uses 3.6% of the DSPs and 4.5% of the BRAM, so those columns
  are pure detour: a horizontal long line buys fewer CLB columns of
  reach on the 410T than on the 325T.
- **The failure is broad, not pathological.** TNS -288.391 ns over 650
  failing endpoints - a mean of -0.444 ns - which is the signature of
  "everything got 13% more wire", not of one bad net.

### The nuance that makes the gap look smaller than it is

The 325T *met* at 100 MHz (+0.096) and therefore **stopped**; the 410T
*missed* and therefore kept working. So 9.538 ns is a
stop-when-met number and 10.591 ns is a max-effort one. **The
comparison as it stands is biased in the 410T's favour, and the true
gap is larger than 1.053 ns.** This is the project's own doctrine
applied to its own newest table.

### The experiments that would confirm or refute it

In order of cost. Every one is an out-of-context implementation, ~27-31
minutes and 25-30 GB, one at a time.

**E1 - remove the bias (2 runs, ~1 h). Do this first.** Run *both*
parts at an ask neither can meet - 130 MHz, period 7.692 ns - and
compare max-effort path delays. If the gap holds at ~1.0-1.2 ns, the
finding is real. If it collapses, the whole thing was the stop-when-met
artefact and there is no puzzle.

**E2 - pblock the 410T to 325T density (1-2 runs, ~30 min each).**
`create_pblock` over a contiguous region holding **50,950 slices** -
one K325T's worth of fabric, which is 80% of the 410T's 63,550 and
restores the 53.65% local occupancy the 325T was forced into -
`add_cells_to_pblock` the whole design, route, read the path delay.

- lands at 9.5-9.7 ns → **pure placer spread**; the fix on any
  oversized part is a pblock, and idea 5 generalises.
- lands at 10.0-10.3 ns → spread plus **column dilution**, which a
  pblock cannot remove because the extra DSP/BRAM columns are still
  inside it.
- stays at ~10.6 ns → both hypotheses are wrong; go to E4.

A second, tighter variant - a pblock of ~39,300 slices, 70% local
occupancy - is simultaneously the idea-5 experiment: it asks whether
compacting *past* the 325T's density keeps paying or starts costing
congestion.

**E3 - the dilution discriminator (1-2 runs).** Run the same
configuration on a part with *more* LUTs but a *lower* hard-block
ratio, or vice versa (`xc7k420t`: 260,600 LUT / 1,680 DSP;
`xc7k480t`: 298,600 / 1,920, both in the Basic tier per
`docs/PLATFORMS.md`). If path delay tracks √(fabric-tile area) across
325T/410T/420T/480T, it is spread. If it tracks DSP-per-slice, it is
dilution. If it tracks neither, E4.

**E4 - the fallback.** `report_design_analysis -congestion` and
`-complexity`, plus the placement bounding box per hierarchy, on the
routed checkpoints. **Which do not exist**, because
`hw/impl_krnl_ooc.tcl` never calls `write_checkpoint` - see §7. Adding
that one line turns E4 from a 30-minute build into a 30-second query,
and would have let E2 be answered from the runs already done.

### Why it matters beyond curiosity

`docs/PLATFORMS.md` prices the K410T as "48.6% for one tile, 97.0% for
two" and lists a £453.99 SOM. The routed evidence says **two tiles will
not fit and one tile is 5-10 MHz slower than on the £99-class part**,
and the reason is that this design buys nothing from spare fabric. It
also, separately, is "absent from the openXC7 database - Vivado only".
On the numbers in hand the K410T is not a step up from the K325T for
this design; it is a step sideways with a wire tax.

---

## 3. A frequency-sweep protocol for the small parts

The governing constraint is the one the project already learned:
**Vivado works the critical path exactly as hard as the constraint asks
and then stops.** A passing run's path delay is a *floor* on what the
tool could do, and a failing run's is close to the tool's best. So a
sweep is not a search for the largest passing frequency; it is a search
for the **fixed point** where the achieved path delay equals the
requested period.

### 3.1 The coefficient, measured here for the first time

The 410T pair is the cleanest instance in the repository: **same tree,
same part, same package, two asks.**

| ask | period T | achieved delay D | outcome |
|---|---|---|---|
| 80 MHz | 12.500 ns | 11.550 ns | met +0.607 |
| 100 MHz | 10.000 ns | 10.591 ns | missed -0.957 |

Tightening the ask by **2.500 ns** shortened the path by **0.959 ns**.
The marginal return on tightening is **ΔD/ΔT = 0.384**. The U50 sweep
in `docs/BRINGUP.md` gives an independent estimate over its two
tightest points (145 → 175 MHz: ΔT = 1.183, ΔD = 0.566): **0.478**. So

> **each nanosecond you take off the ask buys about 0.4 ns of path,
> near the crossing.**

That is enough to solve for the ceiling. With `D = sT + c` and the
ceiling at `D = T`:

    T* = (D_measured - s·T_measured) / (1 - s)

**410T:** from (10.000, 10.591) with s = 0.384 → **T\* = 10.96 ns =
91.3 MHz**; with s = 0.478 → 11.14 ns = 89.8 MHz. Call it **90-91 MHz**.
And the model back-predicts the other point: from (12.500, 11.550),
asking 10.000 predicts D = 11.550 - 0.4×2.5 = **10.550** against a
measured 10.591 - **41 ps out**.

Both slope estimates come from a *met* point paired with a *missed*
one, and the met point's D is itself only an upper bound on what the
tool could have achieved there - so the true slope is at or below these.
The floor: if the 410T at 80 MHz could really have reached 11.0 ns
rather than the 11.550 it stopped at, s = (11.0 - 10.591)/2.5 = **0.16**.
So the defensible band is **s ∈ [0.16, 0.48]** and every ceiling below
is quoted across it.

**410T:** T\* = **10.96 ns (91.3 MHz)** at s = 0.384, **11.14 ns (89.8
MHz)** at s = 0.478, **10.70 ns (93.4 MHz)** at s = 0.16. Call it
**90-93 MHz**.

**325T:** only one point exists, and it *met*, so the model can only
give a bound. From (10.000, 9.538): T\* = 9.23 ns (108.3 MHz) at s =
0.4, 9.12 ns (109.7) at 0.478, 9.45 ns (105.8) at 0.16 - **~106-110
MHz, and that is a lower bound**, because 9.538 is a stop-when-met
number and the true D at that ask is somewhere below it. The first
bracket run in §5 replaces this with a measurement.

**And it corrects a number this repository quotes.**
`docs/BRINGUP.md` reads the U50 ceiling as 1/6.276 = **159 MHz** from
the 175 MHz failure. **That is exactly the s = 0 limit of this model** -
the case where the tool's achieved delay does not depend on what you
ask for - and the 410T pair measures that case as false. Loosening the
ask from 5.714 to 6.276 ns would itself lengthen the path to
6.276 + 0.478×0.562 = **6.545 ns**, so the design would *miss* at 159
MHz. The fixed-point solution for that tree is **6.79 ns = 147 MHz** at
s = 0.478 and **6.39 ns = 157 MHz** at s = 0.16. **The honest reading of
the U50 sweep is "147-157 MHz", with 159 as the upper bound rather than
the estimate.** Nothing built depends on this - 130-135 MHz is
comfortably inside every version of it - but a sweep protocol that
produces a number should produce the right one.

### 3.2 The rule that keeps you from over-asking

`docs/VALIDATION.md`'s 2026-08-31 entry: a deliberate 260 MHz probe
(T = 3.846 ns) achieved **7.009 ns** on a tree whose 175 MHz probe
achieved 6.276. Asking 82% past the edge produced a *worse* number than
asking 10% past it, because at 29,937 failing endpoints the router
spends its effort on TNS rather than on the worst path.

> **Probe just past the edge, not far past it.** The useful failing ask
> is 10-20% tighter than the crossing. A hopeless ask measures the
> router's give-up behaviour, not the design.

### 3.3 The protocol

Cost model, from the runs in hand: a 7-series out-of-context
**implementation** of this kernel is **1,602-1,869 s (27-31 min)** and
**25-30 GB**, so **one at a time**, ~2 per hour, ~45/day on a free box
and realistically 20-24/day on a shared one. **Synthesis only** is
626-731 s (10-12 min) and much cheaper - and, as the 325T/410T pair
proves (9.698 vs 9.708 predicting +0.1% where routing delivered +11%),
**synthesis cannot rank two parts and must not be used for a ceiling.**
Use it only to check that a new RTL elaborates and to catch gross
regressions.

**Phase 0 - fix the rig (no build time).** Add to
`hw/impl_krnl_ooc.tcl`: `write_checkpoint` after place and after route;
`report_timing -max_paths 25 -nworst 1 -unique_pins -path_type summary`
(the current `-max_paths 3` returned one path three times);
`report_design_analysis -timing -congestion`; and a `QOR_*_PATH2/3` line
so the summary names the *second* path family. §7.

**Phase 1 - bracket, 3 runs per part.** For each part, at
`MUL_PASSES=10 FUSE_NORM=1 FUSE_ALIGN=1`:
- 325T: **125, 110, 100 MHz**. 100 is known to pass, so it is the
  anchor; 125 is the predicted failure.
- 410T: **100, 90 MHz** (80 and 100 are already in hand; 90 completes
  the bracket and tests the 91 MHz prediction directly).
Stop as soon as one pass and one fail bracket the crossing within 15%.

**Phase 2 - one max-effort probe per part, 1 run each.** At 10-15%
tighter than the bracketed crossing. Record the achieved path delay.

**Phase 3 - solve.** Fit `D = sT + c` through the tightest passing and
the tightest failing point, report `T* = c/(1-s)` **and** the slope,
and quote the ceiling as a range across s ∈ [0.16, 0.48] rather than a
single number. Publish the *path delay*, the *slope*, and the *path
name* - never the slack.

**Phase 4 - the part that actually matters.** Every K325T number in this
repository is `ffg900-2`. The board `docs/PLATFORMS.md` prices at
~$99.90, the QMTech K325T core board, is **`xc7k325tffg676-1`** - a
**-1** part. Packages are proven irrelevant out of context, but the
grade is not: nothing here measures a -1 Kintex. **One implementation of
`xc7k325tffg676-1` at 80 MHz decides whether step 4 of the third tier
has a board.** See §5.

**Sharing the machine.** One implementation at a time is the hard rule
(25-30 GB against a 46 GB box, and `docs/BRINGUP.md`'s note that a
Vitis link peaks at ~12 GB so two can share a 31 GB host - the
out-of-context 7-series flow is the expensive one, not the Alveo link).
Run the 7-series sweep serially in the foreground and, if an Alveo link
is also wanted, run it *instead*, not beside. Never kill by image name.

---

## 4. The unusual ideas

Five, of which two are ranked above and repeated here in one line so the
list is complete.

**U1. Exploit the `MUL_PASSES` enable for timing, not area (idea 2).**
The tile is already a multicycle design nine cycles out of ten at
`MUL_PASSES=10` and Vivado is timing it as single-cycle. Per-bank
enables make that provable, and a multicycle exception then deletes the
fp64/fp128/fp256 datapath from the timing report. Gated by a formal
"a frozen bank does not change" property, the existing pass-count
determinism bench, and `check_timing`.

**U2. The critical path ends on a reset pin, and that costs 0.30 ns
(idea 3).** Nobody in this repository has looked at pin-level setup.
Every 7-series worst path ends at `cs_r_reg[*]/R` because
`cft_normseg`'s zero-fill was lifted into an inferred synchronous reset.
Measured `Setup_fdre_C_R` = 0.304 ns at -2 against `Setup_fdre_C_D` =
-0.077 ns on the same fabric family at -1. One attribute
(`extract_reset = "no"`), one run.

**U3. The ask-slope, and the correction it implies.** §3.1. A path
delay is a function of the ask with a measurable slope of ~0.4, the
ceiling is the fixed point of that function, and reading `1/D` at a
failing ask overstates it. The repo's own 410T pair supplies the
coefficient and back-predicts the other point to 41 ps.

**U4. The rig cannot see past the first path.** `-max_paths 3` on a
design whose worst net has fanout 90 returns the same path three times.
The second wall - a 45-level, 36-CARRY4 engine path that has never been
measured on a Kintex - has been invisible for that reason alone. And no
routed checkpoint has ever been written by the out-of-context flow, so
every "why?" costs a rebuild. Two lines of Tcl. §7.

**U5. On a wire design, spare fabric is a cost.** §2. The 410T is 33%
more fabric-tile area and 13.5% more route delay for a netlist that
is identical to the picosecond in logic. The generalisation - and the
thing worth testing on the Alveo - is that **a pblock is a performance
feature, not a packaging one**, and that the U50 single-CU build, which
spans both SLRs by default and has never been given a `slr=` line, is
the same mistake at a larger scale (idea 6).

---

## 5. One week of machine time, in order

Assumes the box is otherwise free after the current implementation and
simulation finish, one 7-series implementation at a time at ~30 minutes
and 25-30 GB, and ~20-24 usable runs a day shared. Twenty-two runs
listed; the rest of the week is slack, which this flow always needs.

**Day 0, before any build (no machine time).** Phase 0 of §3.3:
`write_checkpoint`, `-max_paths 25 -unique_pins`,
`report_design_analysis`, `QOR_*_PATH2/3`. Everything below is worth
more with it and several runs below are wasted without it.

**Run 1 - `xc7k325tffg676-1` @ 80 MHz, impl.** *Decides whether the
$99 board exists.* Every K325T number in the repo is a -2 part; the
affordable board is -1. If this lands near 11 ns the third tier's step 4
board is a ~90 MHz board and that is fine; if it lands near 17 ns the
board is an Artix in Kintex clothing and the plan needs a different one.
**This is the highest-value single run in the study and it is not about
optimisation at all.**

**Runs 2-3 - E1: 325T and 410T both @ 130 MHz, impl.** *Decides whether
the 410T puzzle is real.* Removes the stop-when-met bias (§2). Also
gives the 325T its first failing point, which Phase 3 needs.

**Run 4 - E2: 410T @ 100 MHz with a density pblock, impl.** *Decides
whether the 410T gap is placer spread or column dilution*, and therefore
whether idea 5 generalises.

**Run 5 - U2: 325T @ 130 MHz with `extract_reset = "no"` on
`cft_normseg`'s registers, impl.** *Decides whether 0.30 ns is free.*
Cheapest idea in the document. **At 130, not 100**, so that it fails and
the path delay is max-effort - directly comparable with run 2's number
at the same ask. Comparing two *passing* runs would compare two places
the tool chose to stop.

**Runs 6-8 - Phase 1 bracket on the 325T: 125, 115, 110 MHz, impl.**
*Establishes the 325T ceiling* with the fixed-point method, and tests
the ~106-110 MHz prediction.

**Run 9 - 410T @ 90 MHz, impl.** *Completes the 410T bracket* and tests
the 90-93 MHz prediction.

**Run 10 - 325T @ 100 MHz with the ladders OFF, impl.** Never measured
on a 7-series part with routing. *Decides whether `FUSE_NORM`/
`FUSE_ALIGN` are still the right default on the small-part tier* now
that we know they move the endpoint from `s11_valw/D` (private, local)
to `cs_r/R` (shared, device-wide gather, reset pin). The **17,211 LUT**
they save on 7-series fabric (`docs/ARCHITECTURE.md`'s Zynq-7020 table,
116,498 → 99,287 at ten passes) may be buying a slower part than it
looks.

**Run 11 - 325T @ 100 MHz, `-shreg_min_size 100`, impl.** Idea 9, one
flag.

**Runs 12-13 - Alveo: single CU with `slr=cft_krnl_1:SLR0` at 145 and
160 MHz.** Idea 6, first item, ~1h50m each and only ~12 GB, so these
can run while a 7-series run is *not* in flight. *Decides whether the
Alveo's ceiling has a nanosecond of SLR crossing in it.* The 145 point
is against a known result (+0.116 kernel WNS on the old tree); the 160
point is the max-effort probe.

**Runs 14-16 - Alveo directive spread at 145 MHz:**
`PLACE_DIRECTIVE=Explore`, `ExtraTimingOpt`, `AltSpreadLogic_high`, all
with `PHYS_OPT=1`. *Measures the distribution* `docs/ROADMAP.md` says
exists but nobody has sampled.

**Runs 17-19 - if run 5 paid: 325T with `extract_reset=no` at the three
bracket frequencies.** Re-establishes the ceiling on the improved
netlist.

**Runs 20-22 - reserve.** For whichever of E3 (the 420T/480T dilution
discriminator), the DSP-free synthesis probe (idea 10.3, synthesis only,
12 minutes), or a re-bracket after an RTL change the week has produced.

**What is deliberately not in the week:** any RTL change to
`cft_fpfma_pipe`. Ideas 1, 7 and 8 are days of work on the file the
contract rests on and their gate is the vector suite, not a build. They
are the *next* month, and runs 1-9 are what tells you which of them to
start with.

---

## 6. What I could not evaluate

- **Anything in the shell.** Every new number in this study is
  out-of-context on 7-series parts. `docs/BRINGUP.md`'s scar is
  explicit - +0.307 OOC became -0.577 in the shell once, a 0.88 ns
  swing - and none of my Alveo proposals (ideas 5, 6) has a measurement
  behind it. They are ranked on mechanism and on the repository's own
  statements about SLR crossings, not on evidence.
- **The K325T's actual ceiling.** One passing point at one ask. §3.3
  Phase 1 exists because I could not do this from the reports.
- **The -1 Kintex-7, i.e. the board the plan will actually buy.** No
  measurement exists anywhere in the repo. Run 1.
- **The engine path on a Kintex.** §0.3's ~9.0 ns is a scaling estimate
  from a Zynq-7020 *synthesis* number through a ratio measured on a
  different (route-dominated) path. It could be 8 ns or 11. It has never
  appeared in a 7-series routed report because `-max_paths 3` could not
  show it.
- **Whether `extract_reset = "no"` actually behaves as documented in
  Vivado 2026.1 on this netlist**, and whether Vivado folds the term
  into the existing LUT (free) or adds a level (a 0.24 ns regression).
  Both are one run.
- **Everything about the open flow.** Nothing in this repository has
  ever run nextpnr-xilinx on this design at any size. My idea 10 is
  reasoning from openXC7's own published assessments quoted in
  `docs/PLATFORMS.md`, not from a placement. The specific claim I am
  least sure of is (2): that moving `u_seq`'s 1,912 LUTRAM to BRAM is
  what unblocks the analytical placer. It is the construct the lock-up
  report names, but "named in a report" is not "measured here".
- **The exact 7-series column geometry** underpinning §2's 1.329 area
  ratio. I assumed the standard UG474/UG479 pitches (5 CLB rows per
  DSP/BRAM tile, 2 DSP48E1 per DSP tile, 2 slices per CLB). If those are
  wrong the ratio moves; the *direction* of the argument does not,
  because the DSP-per-slice and BRAM-per-slice ratios (+47%, +43%) are
  read straight off the utilisation reports.
- **The area cost of a DSP-free tile** (idea 10.3, ~14,700 LUT).
  Derived by differencing two synthesis rows that happen to differ only
  in a DSP cap, at `MUL_PASSES=1`, with a different mix of displaced
  columns than a ten-pass tile would have. Treat as an order of
  magnitude, and its *timing* cost as entirely unknown.
- **Power, and whether any of this changes it.** Not looked at.
- **The arithmetic itself.** I did not verify that any proposed
  restructuring preserves bits - I specified the gate that would. That
  is the arithmetic study's ground and the golden model's authority,
  not mine.

---

## 7. Fix the measurement rig first

Three changes to `hw/impl_krnl_ooc.tcl`, none of which cost build time,
all of which this study wanted and could not have:

1. **`write_checkpoint -force $build_dir/post_place.dcp` and
   `routed.dcp`.** Every "why is the 410T slower" question in §2 needs a
   placed design and costs a 30-minute rebuild without one.
   `hw/report_cdc.tcl` already takes a routed DCP as its argument, so
   the flow expects them to exist. ~200-400 MB each.
2. **`report_timing -max_paths 25 -nworst 1 -unique_pins -path_type
   summary`.** The current `-max_paths 3` returned the same path three
   times on the 325T. A build should say what the *shape* of the wall
   is, not just its top - and the second family (§0.3) has been
   invisible for exactly this reason.
3. **`QOR_*_PATH2` / `QOR_*_PATH3` lines** naming the second and third
   *distinct* path families in `summary.txt`, so a sweep's summary
   answers "what would be critical if I fixed this" without opening a
   report.

And one to the doctrine, following §3.1: when a sweep reports a ceiling,
report the **slope** with it. `1/D` at a failing ask is an upper bound,
not an estimate, and the repository's own 410T pair is what proves it.
