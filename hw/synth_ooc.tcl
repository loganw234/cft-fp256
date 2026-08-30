# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
#
# Out-of-context synthesis of one FMA pipe instance: the QoR probe that
# tells us what the behavioural core actually costs (LUTs, DSPs) and
# what clock it tolerates - the numbers docs/BRINGUP.md lists as the
# open question deciding v1 pipelining priorities.
#
#   vivado -mode batch -source hw/synth_ooc.tcl -tclargs <exp_w> <man_w> <freq_mhz> [latency] [retime] [part] [build_dir]
#
#   fp32 lane:            -tclargs 8 23 300
#   fp256 unit:           -tclargs 19 236 250   (expect a long run)
#
# LATENCY is no longer a knob: the pipe is structurally staged and its
# elaboration guard refuses any value but its own depth, so the
# default here must track that depth. It is 16. The retime argument
# survives for experiments but has nothing left to retime.
#
# Read the PATH DELAY, not the slack: implementation is
# constraint-driven and stops once the ask is met, so slack tells you
# the design met its target and nothing about headroom. Path delay is
# period minus WNS, and it is what predicts a ceiling
# (docs/BRINGUP.md gate 3).

set exp_w 8
set man_w 23
set freq  100
set latency 16
set retime 0
set part  "xcu50-fsvh2104-2-e"
set build_dir "build"
if {$argc >= 1} { set exp_w [lindex $argv 0] }
if {$argc >= 2} { set man_w [lindex $argv 1] }
if {$argc >= 3} { set freq  [lindex $argv 2] }
if {$argc >= 4} { set latency [lindex $argv 3] }
if {$argc >= 5} { set retime [lindex $argv 4] }
if {$argc >= 6} { set part  [lindex $argv 5] }
if {$argc >= 7} { set build_dir [lindex $argv 6] }

set hw_dir  [file dirname [file normalize [info script]]]
set rtl_dir [file normalize "$hw_dir/../rtl"]
file mkdir $build_dir
set tag "ooc_e${exp_w}m${man_w}_${freq}mhz_l${latency}[expr {$retime ? "_rt" : ""}]"

create_project -in_memory -part $part
read_verilog -sv [list $rtl_dir/cft_fpfma.sv $rtl_dir/cft_fpfma_pipe.sv]
set synth_args [list -top cft_fpfma_pipe -mode out_of_context \
    -generic EXP_W=$exp_w -generic MAN_W=$man_w -generic LATENCY=$latency]
if {$retime} { lappend synth_args -retiming }
synth_design {*}$synth_args
create_clock -period [format %.3f [expr {1000.0 / $freq}]] -name clk [get_ports clk]
report_utilization   -file $build_dir/${tag}_util.rpt
report_timing_summary -file $build_dir/${tag}_timing.rpt -no_detailed_paths

set wns [get_property SLACK [lindex [get_timing_paths -max_paths 1 -nworst 1 -setup] 0]]
puts "QOR_TAG: $tag"
puts "QOR_WNS_NS: $wns (at [format %.1f $freq] MHz; negative = does not close)"
set util [report_utilization -return_string]
foreach line [split $util "\n"] {
  if {[regexp {^\| (CLB LUTs|LUT as Logic|CLB Registers|DSPs|Block RAM)} $line]} {
    puts "QOR_UTIL: [string trim $line]"
  }
}
