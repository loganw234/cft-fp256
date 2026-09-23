# TOOL-A: the open router at density

A study, 2026-09-23. It reads the router the openXC7 flow uses, says why
it does not converge on this project's tile, and sets out what to change
and in what order. What gets built from it, and what that measures, is
recorded in the `dense` branch's own ledger
([loganw234/nextpnr-xilinx, dense/LEDGER.md](https://github.com/loganw234/nextpnr-xilinx/blob/dense/dense/LEDGER.md)),
not here.

Every line number below is **nextpnr-xilinx 0.9.6** (openXC7's 3fd78784,
the binary in `docker/Dockerfile.openxc7`'s image) unless it says
otherwise. `router2.cc` means that version's `common/router2.cc`;
`arch.cc` and `arch.h` its `xilinx/` files. "Mainline" is YosysHQ/nextpnr
`main` at 3edea68 (2026-09-21), whose `common/route/router2.cc` (blob
3d7ca2f8) was read for comparison.

## Why

The single tile is routable on an XC7K325T: Vivado 2026.1 routes the board
configuration at 100 MHz with +0.411 ns and the full-rate tile at +0.155
and +0.182 (docs/VALIDATION.md, 2026-09-23). The 0.9.6 router did not
converge on it. Four runs on amd-arc-box, each placing and routing in one
go at `--freq 100 --timing-allow-fail`, left after one to five iterations:

| run | configuration | LUT bels | total overuse by iteration |
|---|---|---|---|
| pnr | board, ef9c3ec | 160,138 of 407,600 (39%) | 334,494; 85,421; 56,656; 47,133; 43,343 |
| pnr-f1 | full rate, ladders on, ef9c3ec | 182,106 (44%) | 542,678, then no second iteration in six hours |
| pnr-f2 | full rate, ladders off, ef9c3ec | 214,154 (52%) | 420,129; 128,231; 89,419; 77,116; 69,979 |
| pnr-board-6a2b26c | board, 6a2b26c | 160,261 (39%) | 340,836; 98,546 (still running when this was written) |

The board run's fifth iteration took more than two hours and removed 8% of
what was left. Each process used 1.3 to 1.5 cores of the machine's 36. The
first three runs were stopped at 13:05 to free the machine for the
experiments below; the data is in docs/VALIDATION.md.

The question is whether that is the chip or the program. Vivado answers
for the chip.

## The router in one paragraph

router2 is David Shah's 2019 implementation of CRoute (Vercruyce,
Vansteenkiste and Stroobandt, FCCM 2019): negotiated congestion over
connections rather than nets. Every arc from a net's driver to one sink is
routed on its own; wires may be shared between nets while the router
negotiates, at a price; after each pass, each overused wire's history cost
rises and every net that touches one is routed again, arc by arc, until no
wire carries two nets. Each arc first tries a short backwards search from
the sink for the net's existing routing, then a forward A* from the net's
source, confined to the net's bounding box. Nets are routed four threads
at a time by quadrant.

The openXC7 fork has worked on it for its own large designs, and its
comments say so: constant nets routed afterwards by router1 because they
starved bypass wires (`router2.cc:1525-1533`), stall detection so an
unroutable placement stops instead of spinning (1512-1523), a debug mode
that accepts a partial route (1612-1619), and the router1 re-check made
optional because it destroyed router2's result on large designs (1642-1654).

## Why overuse falls so slowly

**The congestion price grows by addition.** `curr_cong_weight +=
cfg.curr_cong_mult` (1595), from `initCurrCongWeight` 0.5 by
`currCongWeightMult` 2.0 (1674, 1676): 0.5, 2.5, 4.5, 6.5. The name says
multiply; the code adds. Negotiated-congestion routers normally grow the
present-cost factor geometrically, and that growth is what finally makes
sharing a wire dearer than any detour. Mainline adds too (its line 1805).
Mainline's `router2/alt-weights` profile takes the other route: a price of
5.0 from the first iteration, not growing, history weight 0.5, estimate
weight 1.0.

**The first pass barely negotiates.** At 0.5, sharing a wire costs 1.5
times using a free one, so the first iteration routes nearly as if the
chip were empty: 264,619 wires overused on the 6a2b26c board. Everything
after is spent unwinding that.

**The search keeps the first path to reach a wire, not the cheapest.**
`route_arc` marks a wire visited when it is queued (`set_visited`, 1008)
and skips any wire already visited (979-980). The test that would replace a
queued path with a cheaper one, `v.score.total() > next_score.total()`
(1000), can never be true, because no visited wire reaches it. Negotiation
depends on finding the cheapest detour at the current prices; this finds
the first. Mainline replaced the test with `was_visited_fwd(wire, cost)`,
which admits a wire again when it arrives cheaper (mainline 774-776, 929).

**The search is pulled hard towards the sink.** The distance estimate is
weighted 1.75 (1677, applied at 998). Weighted A* trades path cost for
speed; at 1.75 it rarely explores around a congested region. Mainline's
default is 1.25; alt-weights uses 1.0.

**Detours outside the net's box open late.** A net may search three tiles
beyond its bounding box (206-209, 1670-1671), and a net that keeps failing
gains one more tile each tenth failure (1148-1154). The per-arc box is
compiled out (`#if 0`, 966-970), so the net's box is the limit for every
arc of a high-fanout net.

**Timing-driven routing at a target the placement cannot meet.** nextpnr's
own estimate after placement was 19.8 MHz for the ef9c3ec board and
22.4 MHz for 6a2b26c, against the 100 MHz asked. Nearly every arc is then
critical: the timing term raises the price of wires held by critical nets
(450-458) and the criticalities are recomputed with a full timing analysis
while more than a fiftieth of the nets are queued (1546-1565). For a
routability question that is cost without information.

## Why an iteration takes hours

**Four threads at most.** `do_route` splits the chip at the median net
centre into four quadrants, then two halves each way (1382-1455). Any net
whose box crosses a split, and any arc that failed inside its thread's box,
is routed on one thread afterwards (1456-1463). On this design that is most
of the work: 1.3 to 1.5 cores each, on a 36-thread machine. Mainline has
the same partitioning.

**The innermost loop pays for lookups.** Every wire in the device - not
only the used ones - gets a record (`setup_wires`, 283-307) holding a
`std::map` of the nets on it (89). Each wire the search explores is found
through a hash table (`wire_to_idx.at`, 978) and priced by
`score_wire_for_arc`, which looks the net up in that map and walks it
(440-458). Mainline reworked this ("router2: Reduce redundancy in
PerWireData", 914e842, 2026-08-26).

**The distance estimate is coarse and not cheap.** `estimateDelay`
(`arch.cc:650-762`) is a piecewise-linear distance - 30 per column, 60 per
row, a constant 300, times 1.5 on 7-series (746-750) - that ignores what
kind of wire the search is standing on; the terms that credited long and
quad lines are commented out (740-745). For a wire spanning several tiles
it first walks up to 200 of the tile positions to find the one nearest the
sink (702-713), on every call, and the search calls it for every neighbour
it scores.

**Every arc starts again at the source.** The forward search is seeded
with the net's source wire alone (920), so a net with many sinks walks its
own routing tree again for each. The backwards search that tries to join
existing routing first is capped at 20 steps, 400 for nets of more than 40
sinks (831-833), and refuses any shared wire (880-881).

## What is not the problem

**LUT input permutation is there.** The routing graph has
`PIP_LUT_PERMUTATION` pips inside each slice, open for every LUT that is
not LUTRAM or an SRL (`arch.h:1224-1239`), so the router chooses physical
LUT pins itself; a pass afterwards rewrites the truth tables to match
(`arch_place.cc:1706`). This is one of Vivado's main routability tools and
it is not missing.

**Route-throughs are limited,** two cases marked FIXME (`arch.h:1240-1256`),
but in a design this full few LUTs are empty to route through.

## What cannot be seen yet

**Where the congestion is.** Pin access at the slices' input multiplexers,
a shortage of general interconnect, and a few hot regions call for
different fixes, and the router does not say which. Its heatmap is compiled
out (1577-1582) and it counts overuse without telling wire types apart.
Mainline writes congestion by wire type, by coordinate and by net, every
iteration.

**Whether the placement is the problem.** The HeAP spreader treats a
region as over-full above `beta` of its capacity, and this fork sets beta
to 0.4 (`arch.cc:865`). At 39 to 52% of the LUT bels occupied, nearly every
region is over that, so the spreader cannot meet its target anywhere and
does little more than even the density out.

## Two things found on the way that decide how experiments are run

**The 0.9.6 Python bindings do not reach `ctx->settings`.** Nothing in
`common/pybindings.cc`, `xilinx/arch_pybindings.cc` or
`arch_pybindings_shared.h` exposes it. The first reading of this router, in
conversation on 2026-09-23, said a `--pre-route` script could set every
router option without rebuilding; that was wrong. The pinned binary can
take options only through the design file.

**A placed design's settings win over the command line.** `executeMain`
applies the command line first (`setupContext`), then loads the JSON, and
`frontend_base.h:281-283` writes every setting the file carries over the
table. A placed design routed again with another `--freq`, `--no-tmdriv` or
`--seed` keeps the file's values, silently, and the recorded command line
misstates the run.

Both are handled in the `dense` branch's first commits: `--set KEY=VALUE`
applied after the load and logged with what it replaced, a log line for
every setting a design file overrides, router2 printing the values it
applies, and unknown `router2/` keys refused by name.

## A fork, and where it starts

Options 2 to 4 below change the router's core, its data structures and the
placer: too much to carry as patches, and each result has to name the
build that made it. So a fork: loganw234/nextpnr-xilinx, public, forked
from openXC7 on 2026-09-23, with a `dense` branch.

It starts at **3fd78784**, the pinned 0.9.6, because every measurement so
far came from that binary, so the fork's unmodified build is the control
(`dense/build.sh` checks it on blinky-kc705, bitstream against bitstream).
openXC7's `main` was seven commits ahead, none in the router or placer:
BRAM cascade placement, pad drive, FASM, and a prjxray-db bump that changes
the chip database - a confound for every comparison, so rebasing waits
until something here is worth sending back. Mainline's own Xilinx support
(`himbaechel/uarch/xilinx`) is a separate implementation with its own chip
database; moving to it would change everything at once. Its router2 is the
source of backports, not the base.

Every change that alters what the router does goes in behind a setting,
off by default, until the ledger records it helping: one binary runs both
sides of each comparison, and the default build keeps routing as 0.9.6
does.

## What to try, in order

1. **Settings alone,** through `--set`: mainline's estimate weight 1.25;
   mainline's alt-weights profile; a bounding-box margin of 8; timing-driven
   routing off. Cheap, and they bear directly on the convergence findings
   above.
2. **Diagnostics, then small backports:** congestion by wire type and by
   coordinate, each iteration (the first code change, because the fix
   depends on what is congested); the cheaper-path revisit; a price that
   multiplies instead of adding; faster box growth for nets that keep
   failing.
3. **Speed:** partitioning into as many regions as the machine has
   threads; flat per-wire records indexed directly; a precomputed distance
   estimate; seeding each arc's search from the net's existing routing.
4. **Designed for density:** a distance estimate that knows where
   congestion is and steers around it; an exact cheapest-path mode for the
   last conflicts, when there are few and each matters; placement that
   spreads cells where routing will be tight; packing that pairs each
   flip-flop with the LUT that drives it, which saves the bypass pins the
   fork's own comments call scarce.

## How a change is judged

One placement of the 6a2b26c board netlist, made once by the pinned binary
with `--no-route`, is routed by every experiment through `dense/bench.sh`,
so two runs differ only in the binary and the settings. A run is recorded
with its binary's `git describe --dirty`, the settings router2 printed as
applied, the placement's hash, the machine's load each minute, its overuse
curve, and an outcome read from the log. A change is judged by its curve
against the base settings' curve on the same placement - overuse by
iteration, iterations to converge - and by minutes per iteration beside the
load. The curves should not depend on load or on how many runs share the
machine; that is to be shown, by running one configuration twice, not
assumed.

## What would change this reading

If the heatmaps put the overuse at the slices' input pins rather than in
the interconnect, the router's search matters less than placement and
packing, and option 4's last two items move to the front. If the settings
in option 1 converge the board configuration outright, the code work
shrinks to making it fast. And if nothing here converges the board, the
comparison that says why is Vivado's own placement of the same netlist
routed by this router - a route of a placement Vivado has shown to be
routable separates the placer from the router.
