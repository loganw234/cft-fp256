# Experiment A: can Vivado recover the DSP pipeline registers by
# RETIMING, with no RTL change at all?
#
# The RTL asks for `s2_pp[k] <= s1_ma * mb_pad[...]` - a 237x24 product
# registered once. Vivado builds that as a combinational cascade of DSP
# columns and puts the register in fabric, so MREG and PREG go unused
# (DPOP-3/DPOP-4, 460 of them). Retiming is allowed to move registers
# across combinational logic, so if the cascade can be balanced by
# moving that fabric register INTO the DSPs, this flag finds it and the
# function is unchanged by construction.
#
# If it does not help, the conclusion is that the register does not
# exist to be moved - the pipeline is too shallow through the multiply -
# and only adding a stage will do, which is experiment B.

set freq 135
set part "xcu50-fsvh2104-2-e"
set build_dir "build_ooc_retime"
set retime 1
if {$argc >= 1} { set freq [lindex $argv 0] }
if {$argc >= 2} { set build_dir [lindex $argv 1] }
if {$argc >= 3} { set retime [lindex $argv 2] }

set hw_dir  [file dirname [file normalize [info script]]]
set rtl_dir [file normalize "$hw_dir/rtl"]
if {![file isdirectory $rtl_dir]} { set rtl_dir [file normalize "$hw_dir/../rtl"] }
file mkdir $build_dir

create_project -in_memory -part $part
read_verilog -sv [glob $rtl_dir/*.sv]
if {$retime} {
  puts "== synth WITH -retiming"
  synth_design -top cft_krnl -mode out_of_context -retiming
} else {
  puts "== synth WITHOUT retiming (baseline)"
  synth_design -top cft_krnl -mode out_of_context
}
create_clock -period [format %.3f [expr {1000.0 / $freq}]] -name ap_clk [get_ports ap_clk]

report_utilization -file $build_dir/util.rpt
report_timing_summary -file $build_dir/timing.rpt -no_detailed_paths
report_timing -max_paths 3 -file $build_dir/paths.rpt

# the question this experiment exists to answer
set dpop [llength [get_drc_violations -quiet -name dsp_check]]
if {[catch {report_drc -checks {DPOP-3 DPOP-4 DPIP-2} -file $build_dir/dsp_drc.rpt}]} {
  puts "== (DSP drc checks unavailable pre-implementation)"
}

set wns [get_property SLACK [lindex [get_timing_paths -max_paths 1 -nworst 1 -setup] 0]]
puts "RETIME_TAG: retiming=$retime freq=$freq"
puts "RETIME_WNS_NS: $wns"
set util [report_utilization -return_string]
foreach line [split $util "\n"] {
  if {[regexp {^\| (CLB LUTs|CLB Registers|DSPs)} $line]} { puts "RETIME_UTIL: [string trim $line]" }
}
# how many DSPs ended up with their internal registers in use
set n_mreg 0; set n_preg 0
foreach c [get_cells -hier -filter {PRIMITIVE_TYPE =~ *DSP*} -quiet] {
  if {[catch {set m [get_property MREG $c]}]} { continue }
  if {$m == 1} { incr n_mreg }
  if {![catch {set p [get_property PREG $c]}] && $p == 1} { incr n_preg }
}
puts "RETIME_DSP_MREG: $n_mreg"
puts "RETIME_DSP_PREG: $n_preg"
puts "RETIME_DSP_TOTAL: [llength [get_cells -hier -filter {PRIMITIVE_TYPE =~ *DSP*} -quiet]]"
