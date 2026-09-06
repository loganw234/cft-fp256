# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
#
# Out-of-context IMPLEMENTATION of the full kernel: synthesis, then
# opt/place/route with no shell around it, for the parts the multi-cycle
# tile is meant for (docs/ARCHITECTURE.md, "The multi-cycle fp256
# rung"). hw/synth_krnl_ooc.tcl stops at synthesis; a synthesis-only
# path delay is an estimate with no wire in it, and on a 7-series part
# at speed grade -1 the wire is most of the number.
#
#   vivado -mode batch -source hw/impl_krnl_ooc.tcl \
#       -tclargs <freq_mhz> <part> <build_dir> ["GENERIC=v ..."] [synth|impl]
#
# The generics may also arrive in the environment as CFT_GENERICS,
# which takes precedence: on Windows, vivado.bat is a cmd.exe wrapper
# and cmd.exe splits an argument at `=`, so "MUL_PASSES=10" handed
# through -tclargs reaches synth_design as a parameter with no value
# (bound to 0, measured 2026-09-06). hw/mc_sweep.sh uses the variable.
#
# The last argument stops after synthesis (synth) or runs the whole
# flow (impl, the default). Every run leaves, in <build_dir>:
#
#   util_synth.rpt / util_synth_hier.rpt     post-synthesis utilization, flat and by module
#   timing_synth.rpt, paths_synth.rpt         post-synthesis estimate and its worst paths
#   util_routed.rpt / util_routed_hier.rpt    post-route utilization (impl only)
#   timing_routed.rpt, paths_routed.rpt       routed timing and its worst paths (impl only)
#
# and prints QOR_* lines the sweep script collects. Read the PATH DELAY
# (period minus WNS), never the slack: the tool works exactly as hard
# as the constraint asks, and a routed WNS says nothing about headroom.
#
# One implementation at a time on a shared host: a placement of this
# kernel can take 25-30 GB.

set freq 100
set part "xc7k325tffg900-2"
set build_dir "build_impl_ooc"
set generics {}
set stage "impl"
if {$argc >= 1} { set freq [lindex $argv 0] }
if {$argc >= 2} { set part [lindex $argv 1] }
if {$argc >= 3} { set build_dir [lindex $argv 2] }
if {$argc >= 4} { set generics [lindex $argv 3] }
if {$argc >= 5} { set stage [lindex $argv 4] }
if {[info exists ::env(CFT_GENERICS)] && $::env(CFT_GENERICS) ne ""} {
  set generics $::env(CFT_GENERICS)
}
puts "IMPL_OOC: part=$part freq=$freq generics={$generics} stage=$stage"

set hw_dir  [file dirname [file normalize [info script]]]
set rtl_dir [file normalize "$hw_dir/../rtl"]
file mkdir $build_dir

set period [format %.3f [expr {1000.0 / $freq}]]

proc qor_lines {tag} {
  set wns [get_property SLACK [lindex [get_timing_paths -max_paths 1 -nworst 1 -setup] 0]]
  puts "QOR_${tag}_WNS_NS: $wns"
  set util [report_utilization -return_string]
  foreach line [split $util "\n"] {
    if {[regexp {^\| (Slice LUTs|CLB LUTs|Slice Registers|CLB Registers|DSPs|Block RAM Tile|DSP48E1 only|DSP48E2 only|LUT as Logic|LUT as Memory)} $line]} {
      puts "QOR_${tag}_UTIL: [string trim $line]"
    }
  }
  # The worst path, by name, so the table can say what is critical.
  set p [lindex [get_timing_paths -max_paths 1 -nworst 1 -setup] 0]
  if {$p ne ""} {
    puts "QOR_${tag}_PATH: [get_property STARTPOINT_PIN $p] -> [get_property ENDPOINT_PIN $p] levels=[get_property LOGIC_LEVELS $p] delay=[get_property DATAPATH_DELAY $p]"
  }
}

create_project -in_memory -part $part
read_verilog -sv [glob $rtl_dir/*.sv]
set gargs {}
foreach g $generics { lappend gargs -generic $g }
synth_design -top cft_krnl -mode out_of_context {*}$gargs
create_clock -period $period -name ap_clk [get_ports ap_clk]

report_utilization -file $build_dir/util_synth.rpt
report_utilization -hierarchical -hierarchical_depth 3 -file $build_dir/util_synth_hier.rpt
report_timing_summary -file $build_dir/timing_synth.rpt -no_detailed_paths
report_timing -max_paths 3 -file $build_dir/paths_synth.rpt
puts "QOR_TAG: krnl_${freq}mhz $part [expr {$generics eq {} ? "defaults" : $generics}]"
qor_lines SYNTH

if {$stage eq "synth"} {
  puts "QOR_STAGE: synth only"
  exit
}

opt_design
place_design
report_utilization -file $build_dir/util_placed.rpt
route_design
report_utilization -file $build_dir/util_routed.rpt
report_utilization -hierarchical -hierarchical_depth 3 -file $build_dir/util_routed_hier.rpt
report_timing_summary -file $build_dir/timing_routed.rpt -no_detailed_paths
report_timing -max_paths 3 -file $build_dir/paths_routed.rpt
qor_lines ROUTED
puts "QOR_STAGE: routed"
