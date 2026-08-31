# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
#
# Where the LUTs are, by module, with the hierarchy left intact.
#
#   vivado -mode batch -source hw/synth_attrib.tcl -tclargs [part] [build_dir]
#
# This is NOT a QoR run and its timing numbers should be ignored.
# `-flatten_hierarchy none` costs optimisation across module boundaries,
# so the total will be larger than a real build and the critical path
# will be worse. Use hw/synth_krnl_ooc.tcl for QoR.
#
# It exists because the default flow makes attribution impossible.
# Vivado flattens by default, and then `report_utilization -hierarchical`
# charges logic to whichever surviving instance it merged into. On the
# 2026-08-30 run that put ~25,000 LUT inside the four cft_fifo
# instances - which is not where it lives. The tell was that four
# identical FIFOs reported 14,092 / 9,741 / 1,431 / 202 logic LUTs; a
# module cannot cost four different amounts. What actually happened is
# that cft_opmux is instantiated fifteen times and appears in the
# report zero times, so its steering logic was charged to the FIFOs
# whose outputs it consumes.
#
# With the boundaries preserved, every instance is charged what it
# actually contains, and the question "which module should be
# optimised" has an answer instead of an estimate.
set part "xcu50-fsvh2104-2-e"
set build_dir "build_attrib"
if {$argc >= 1} { set part [lindex $argv 0] }
if {$argc >= 2} { set build_dir [lindex $argv 1] }

set hw_dir  [file dirname [file normalize [info script]]]
set rtl_dir [file normalize "$hw_dir/../rtl"]
file mkdir $build_dir

create_project -in_memory -part $part
read_verilog -sv [glob $rtl_dir/*.sv]
synth_design -top cft_krnl -mode out_of_context -flatten_hierarchy none

report_utilization -hierarchical -hierarchical_depth 4 \
                   -file $build_dir/attrib.rpt

# One line per module type, summed over instances - the form that
# answers "is it worth optimising this module" directly.
puts "ATTRIB: module utilization with hierarchy preserved"
foreach cell [get_cells -hier -filter {IS_PRIMITIVE == 0}] {
  set ref [get_property REF_NAME $cell]
  if {$ref eq ""} { continue }
  set luts [llength [get_cells -quiet -hier -filter \
              "PARENT == $cell && PRIMITIVE_GROUP == LUT"]]
  if {$luts > 0} { puts "ATTRIB_CELL: $cell $ref $luts" }
}
puts "ATTRIB: done"
