# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
#
# Probe S (docs/ROADMAP.md, "Revision 8", part 3; the plan's question 6):
# the kernel out of context at the U50's capacities, on a tree that holds
# revision 8's seam, the abort and the instruction fetch with its hooks
# and nothing else - so that what the fetch costs and where its paths
# land is read before R21 to R24 are in. Driven by hw/probe_s.sh.
#
#   vivado -mode batch -source hw/probe_s.tcl \
#       -tclargs <freq_mhz> <part> <out_dir> <rtl_dir> [synth|impl]
#
# Prints PROBE_S_* lines, each a fact the plan asks for (part 3, probe S):
#
#   WNS, UTIL       the kernel's worst slack and its LUTs, registers,
#                   block-RAM tiles, URAM, DSPs
#   HIER            from the hierarchical utilization: u_seq, the fetch
#                   unit, its store and its FIFO, and the kernel - the
#                   instruction memory's real share of a tile's block-RAM
#                   tiles (217 at revision 7, of which the 32K IMEM was 64
#                   RAMB36 by its geometry alone; R8S-streaming.md, section
#                   5's caution). Each row is INCLUSIVE of its children:
#                   u_fetch's counts hold u_fifo's, and u_seq's hold both
#                   (verifier-VC12's synthesis: u_fetch 8 RAMB36 and 1
#                   RAMB18, the store's 7 and 1 and the FIFO's 1). The
#                   store's own share is u_fetch's less u_fifo's.
#   SEQ_WORST       u_seq's twenty worst endpoints, each FETCH where it
#                   starts in the fetch unit - the plan wants the fetch path
#                   OFF this list (revision 7 out of context: the IMEM's
#                   seven-deep block-RAM cascade into bt_reg, +1.885 ns, was
#                   u_seq's worst). Taken from the DESIGN's worst 400
#                   paths, so where the kernel's worst 400 lie mostly
#                   outside u_seq it lists fewer than twenty, and says how
#                   many; u_seq's own worst 25 are then in
#                   paths_<tag>_u_seq.rpt, which this script always writes.
#   BRAM, CASCADE   every block RAM in the fetch unit with its cascade
#                   order: the store must be cascade-free, and carries
#                   `cascade_height = 1` since verifier-VC12's synthesis
#                   found Vivado chaining it
#   PATH_TAKE_RP    `take` - late, out of the admission - through the pop
#                   into the FIFO's read address (rp + rd_en into the block
#                   RAM), R8S-streaming.md section 13
#   PATH_REDIRECT   the redirect, combinational: pc -> addr (pc + 1) ->
#                   the 25-bit range compare -> the 25-bit target mux ->
#                   the 25-bit stand compare -> the FIFO's synchronous
#                   clear and resets, and the stream's position and state
#                   (verifier-VRD1's first path)
#   PATH_WORD       `word` through its two 2:1 selects - the FIFO's head
#                   bypass, then the store's read register or that head -
#                   into the admission and the issue (VRD1's second)
#
# Each section is caught on its own, so an ERROR in one prints PROBE_S_ERR
# and the rest still run. A `-quiet` query that matches nothing is not an
# error and prints no path at all - so each path section ends with a count
# line, and a count of 0 is a name Vivado changed, not a clean result.
# The UTIL lines are the summary table's: report_utilization repeats the
# same names in later tables, some with zeros, and only the first line of
# each name is printed (as hw/probe_l.sh reads them).

set freq 135
set part "xcu50-fsvh2104-2-e"
set out "build_probe_s"
set rtl_dir ""
set stage "impl"
if {$argc >= 1} { set freq [lindex $argv 0] }
if {$argc >= 2} { set part [lindex $argv 1] }
if {$argc >= 3} { set out [lindex $argv 2] }
if {$argc >= 4} { set rtl_dir [lindex $argv 3] }
if {$argc >= 5} { set stage [lindex $argv 4] }
if {$rtl_dir eq ""} {
  set rtl_dir [file normalize "[file dirname [file normalize [info script]]]/../rtl"]
}
file mkdir $out
set period [format %.3f [expr {1000.0 / $freq}]]
puts "PROBE_S: part=$part freq=$freq stage=$stage rtl=$rtl_dir out=$out"

proc sec {name body} {
  if {[catch {uplevel 1 $body} err]} { puts "PROBE_S_ERR: $name: $err" }
}

proc path_line {tag p} {
  set cells [get_cells -quiet -of_objects $p]
  set fetch 0
  foreach c $cells { if {[string match "u_seq/u_fetch/*" $c]} { set fetch 1 } }
  puts [format "%s: slack=%s delay=%s levels=%s %s -> %s%s" $tag \
        [get_property SLACK $p] [get_property DATAPATH_DELAY $p] \
        [get_property LOGIC_LEVELS $p] [get_property STARTPOINT_PIN $p] \
        [get_property ENDPOINT_PIN $p] [expr {$fetch ? " FETCH" : ""}]]
}

proc report_all {tag out} {
  set wns [get_property SLACK [lindex [get_timing_paths -max_paths 1 -nworst 1 -setup] 0]]
  puts "PROBE_S_WNS_${tag}: $wns"
  set seen {}
  foreach line [split [report_utilization -return_string] "\n"] {
    if {[regexp {^\| (CLB LUTs|CLB Registers|Block RAM Tile|URAM|DSPs)} $line -> name]} {
      if {[lsearch -exact $seen $name] >= 0} { continue }
      lappend seen $name
      puts "PROBE_S_UTIL_${tag}: [string trim $line]"
    }
  }
  report_utilization -hierarchical -hierarchical_depth 4 -file $out/util_${tag}_hier.rpt
  sec "hier" {
    set f [open $out/util_${tag}_hier.rpt r]
    set hier [read $f]
    close $f
    foreach line [split $hier "\n"] {
      if {[regexp {^\|\s+(cft_krnl|u_seq|u_fetch|u_fifo|g_stream\.u_fifo|u_lanes|u_engine)\s} $line]} {
        puts "PROBE_S_HIER_${tag}: [string trim $line]"
      }
    }
    puts "PROBE_S_HIER_${tag}: (columns as util_${tag}_hier.rpt's header; each row includes its children - the store's share is u_fetch's less u_fifo's)"
  }
  sec "seq_worst" {
    set n 0
    foreach p [get_timing_paths -max_paths 400 -nworst 1 -unique_pins -setup] {
      if {![string match "u_seq/*" [get_property ENDPOINT_PIN $p]]} { continue }
      path_line "PROBE_S_SEQ_WORST_${tag}" $p
      incr n
      if {$n >= 20} { break }
    }
    puts "PROBE_S_SEQ_WORST_${tag}: $n endpoints in u_seq listed, from the design's worst 400 (u_seq's own worst 25: paths_${tag}_u_seq.rpt)"
  }
  sec "bram" {
    set brams [get_cells -quiet -hierarchical -filter {PRIMITIVE_GROUP == BLOCKRAM && NAME =~ "u_seq/u_fetch/*"}]
    set chained 0
    foreach b $brams {
      set ca [get_property -quiet CASCADE_ORDER_A $b]
      set cb [get_property -quiet CASCADE_ORDER_B $b]
      if {($ca ne "" && $ca ne "NONE") || ($cb ne "" && $cb ne "NONE")} { incr chained }
      puts "PROBE_S_BRAM_${tag}: $b [get_property REF_NAME $b] cascade_a=$ca cascade_b=$cb"
    }
    puts "PROBE_S_CASCADE_${tag}: [llength $brams] block RAMs in the fetch unit, $chained of them in a cascade"
  }
  sec "take_rp" {
    set to [get_pins -quiet -of_objects [get_cells -quiet -hierarchical -filter {PRIMITIVE_GROUP == BLOCKRAM && NAME =~ "u_seq/u_fetch/*u_fifo*"}] -filter {REF_PIN_NAME =~ ADDR*}]
    set to [concat $to [get_pins -quiet -hierarchical -filter {NAME =~ "u_seq/u_fetch/*u_fifo*/rp_reg*/D"}]]
    set k 0
    foreach p [get_timing_paths -quiet -max_paths 3 -nworst 1 -setup -to $to] {
      path_line "PROBE_S_PATH_TAKE_RP_${tag}" $p
      incr k
    }
    puts "PROBE_S_PATH_TAKE_RP_${tag}: $k paths ([llength $to] endpoint pins matched)"
  }
  sec "redirect" {
    set from [get_cells -quiet -hierarchical -filter {NAME =~ "u_seq/pc_reg*"}]
    set to [get_pins -quiet -hierarchical -filter {(NAME =~ "u_seq/u_fetch/*u_fifo*/wp_reg*/*" || NAME =~ "u_seq/u_fetch/*u_fifo*/rp_reg*/*" || NAME =~ "u_seq/u_fetch/*u_fifo*/count_reg*/*" || NAME =~ "u_seq/u_fetch/*u_fifo*/byp_v*_reg*/*") && (REF_PIN_NAME == D || REF_PIN_NAME == R || REF_PIN_NAME == S || REF_PIN_NAME == CE)}]
    set k 0
    foreach p [get_timing_paths -quiet -max_paths 3 -nworst 1 -setup -from $from -to $to] {
      path_line "PROBE_S_PATH_REDIRECT_FIFO_${tag}" $p
      incr k
    }
    puts "PROBE_S_PATH_REDIRECT_FIFO_${tag}: $k paths ([llength $from] pc cells, [llength $to] endpoint pins matched)"
    set to2 [get_pins -quiet -hierarchical -filter {(NAME =~ "u_seq/u_fetch/*spos_reg*/*" || NAME =~ "u_seq/u_fetch/*s_on_reg*/*" || NAME =~ "u_seq/u_fetch/*rs_go_reg*/*" || NAME =~ "u_seq/u_fetch/*ra_v_reg*/*") && (REF_PIN_NAME == D || REF_PIN_NAME == R || REF_PIN_NAME == S || REF_PIN_NAME == CE)}]
    set k 0
    foreach p [get_timing_paths -quiet -max_paths 3 -nworst 1 -setup -from $from -to $to2] {
      path_line "PROBE_S_PATH_REDIRECT_STREAM_${tag}" $p
      incr k
    }
    puts "PROBE_S_PATH_REDIRECT_STREAM_${tag}: $k paths ([llength $to2] endpoint pins matched)"
  }
  sec "word" {
    set from [get_cells -quiet -hierarchical -filter {NAME =~ "u_seq/u_fetch/*st_q_reg*" || NAME =~ "u_seq/u_fetch/*u_fifo*/byp_d_reg*" || NAME =~ "u_seq/u_fetch/*u_fifo*/ram_q_reg*" || NAME =~ "u_seq/u_fetch/*rq_hit_reg*" || (PRIMITIVE_GROUP == BLOCKRAM && NAME =~ "u_seq/u_fetch/*")}]
    set k 0
    foreach p [get_timing_paths -quiet -max_paths 5 -nworst 1 -setup -from $from] {
      path_line "PROBE_S_PATH_WORD_${tag}" $p
      incr k
    }
    puts "PROBE_S_PATH_WORD_${tag}: $k paths ([llength $from] start cells matched)"
  }
  report_timing_summary -file $out/timing_${tag}.rpt -no_detailed_paths
  report_timing -max_paths 25 -unique_pins -file $out/paths_${tag}.rpt
  report_timing -max_paths 25 -unique_pins -to [get_cells -quiet -hierarchical -filter {NAME =~ "u_seq/*"}] -file $out/paths_${tag}_u_seq.rpt
}

create_project -in_memory -part $part
read_verilog -sv [glob $rtl_dir/*.sv]
synth_design -top cft_krnl -mode out_of_context
create_clock -period $period -name ap_clk [get_ports ap_clk]
report_utilization -file $out/util_synth.rpt
report_all synth $out
if {$stage eq "synth"} {
  puts "PROBE_S_STAGE: synth only"
  exit
}
opt_design
place_design
route_design
write_checkpoint -force $out/routed.dcp
report_utilization -file $out/util_routed.rpt
report_all routed $out
puts "PROBE_S_STAGE: routed"
