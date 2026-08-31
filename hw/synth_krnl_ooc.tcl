# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
#
# Out-of-context synthesis of the FULL kernel (cft_krnl): the QoR
# probe for paths the per-core probe (synth_ooc.tcl) cannot see -
# engine FSMs, the FIFO async-read -> operand steering -> S0 input
# registers path, the CSR block, and the bank result muxes.
#
#   vivado -mode batch -source hw/synth_krnl_ooc.tcl -tclargs <freq_mhz> [part] [build_dir]
#
# WNS at the shipping kernel clock is the number that matters; the
# three worst paths land in <build_dir>/krnl_paths.rpt by name.

set freq 100
set part "xcu50-fsvh2104-2-e"
set build_dir "build_ooc_krnl"
if {$argc >= 1} { set freq [lindex $argv 0] }
if {$argc >= 2} { set part [lindex $argv 1] }
if {$argc >= 3} { set build_dir [lindex $argv 2] }

set hw_dir  [file dirname [file normalize [info script]]]
set rtl_dir [file normalize "$hw_dir/../rtl"]
file mkdir $build_dir

create_project -in_memory -part $part
read_verilog -sv [glob $rtl_dir/*.sv]
synth_design -top cft_krnl -mode out_of_context
create_clock -period [format %.3f [expr {1000.0 / $freq}]] -name ap_clk [get_ports ap_clk]
report_utilization    -file $build_dir/krnl_util.rpt

# Per-module utilization, which the flat report above cannot give.
#
# Every area figure this project has quoted was a SUBTRACTION between
# whole builds - tile total minus the arithmetic banks, or one commit
# minus another. That works, and it is how the 119,543-LUT tile and the
# +9,198 four-master delta were measured, but it cannot say which
# module inside the engine holds the LUTs. Three separate analyses of
# where to save area all had to estimate, and all three estimated
# differently.
#
# Ten seconds of reporting replaces that. Depth 3 reaches
# cft_krnl -> cft_engine_stream -> the banks, the FIFOs and
# cft_reduce_acc, which is the level the open questions live at.
#
# AREA attribution is OOC-stable in a way TIMING is not: this file's
# own header warns that OOC WNS does not predict shell WNS, and
# ROADMAP records an OOC run predicting +2% for what became a shell
# regression. That caution is about timing. Utilization out of context
# is the same netlist the shell build starts from.
report_utilization -hierarchical -hierarchical_depth 3 \
                   -file $build_dir/krnl_util_hier.rpt

report_timing_summary -file $build_dir/krnl_timing.rpt -no_detailed_paths
report_timing -max_paths 3 -file $build_dir/krnl_paths.rpt

set wns [get_property SLACK [lindex [get_timing_paths -max_paths 1 -nworst 1 -setup] 0]]
puts "QOR_TAG: krnl_${freq}mhz"
puts "QOR_WNS_NS: $wns (at [format %.1f $freq] MHz; negative = does not close)"
set util [report_utilization -return_string]
foreach line [split $util "\n"] {
  if {[regexp {^\| (CLB LUTs|CLB Registers|DSPs|Block RAM)} $line]} {
    puts "QOR_UTIL: [string trim $line]"
  }
}
