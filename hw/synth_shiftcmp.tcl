# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
#
# Does one shared segmented shifter cost less than the fifteen private
# ones it replaces? Both are in tb_normseg, driven from the same
# operand word, so one synthesis run with the hierarchy preserved
# answers it directly.
#
#   vivado -mode batch -source hw/synth_shiftcmp.tcl -tclargs [part] [build_dir]
#
# NOT a QoR run - `-flatten_hierarchy none` is what makes the two sides
# separable, and it costs cross-boundary optimisation. The timing
# numbers here mean nothing. See hw/synth_krnl_ooc.tcl for QoR and
# hw/synth_attrib.tcl for the same argument at kernel scale.
#
# This exists because cft_mulfrac is the standing counterexample to
# reasoning about area from geometry: the fused multiplier collapses
# 97,551 bit-products into 63,990 and still cost +693 LUT, because what
# it collapsed was DSP. The shifters collapse LUTs, so the trade should
# invert - but "should" is why this file runs.

set part "xcu50-fsvh2104-2-e"
set build_dir "build_shiftcmp"
if {$argc >= 1} { set part [lindex $argv 0] }
if {$argc >= 2} { set build_dir [lindex $argv 1] }

set hw_dir  [file dirname [file normalize [info script]]]
set rtl_dir [file normalize "$hw_dir/../rtl"]
set tb_dir  [file normalize "$hw_dir/../tb/wrappers"]
file mkdir $build_dir

create_project -in_memory -part $part
read_verilog -sv $rtl_dir/cft_normseg.sv
read_verilog -sv $tb_dir/tb_normseg.sv
synth_design -top tb_normseg -mode out_of_context -flatten_hierarchy none

report_utilization -hierarchical -hierarchical_depth 3 \
                   -file $build_dir/shiftcmp.rpt

# Sum the two sides. The reference lanes are fifteen instances across
# four generate blocks plus the fp256 one, so they are added up rather
# than read off a single line.
set shared 0
set refsum 0
set fh [open $build_dir/shiftcmp.rpt r]
while {[gets $fh line] >= 0} {
  if {[regexp {^\|\s+(\S+)\s+\|\s+(\S+)\s+\|\s+(\d+)\s+\|} $line -> inst mod luts]} {
    if {[string match "u_seg*" $inst]} {
      set shared [expr {$shared + $luts}]
    } elseif {[string match "*ref*" $inst] || [string match "*u_ref256*" $inst]} {
      set refsum [expr {$refsum + $luts}]
    }
  }
}
close $fh

puts "SHIFTCMP_SHARED_LUT: $shared"
puts "SHIFTCMP_PRIVATE_LUT: $refsum"
if {$shared > 0} {
  puts "SHIFTCMP_RATIO: [format %.2f [expr {double($refsum) / $shared}]]x"
  puts "SHIFTCMP_SAVING_LUT: [expr {$refsum - $shared}]"
}
