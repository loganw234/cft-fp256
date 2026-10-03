# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
#
# Probe L (docs/ROADMAP.md, "Revision 8", part 3): ONE FMA pipe out of
# context at one of the U50's rungs, with R21's lanes built
# (EN_AUGADD=1) or not (0), for what R21 costs and what it does to the
# timing of the two stages it changes most - S6, where the re-anchor
# selects the anchor, and S10, where design (b)'s decision sits between
# the add's carry chain and its select. A sibling of hw/synth_ooc.tcl:
# the same out-of-context synthesis of cft_fpfma_pipe, with the
# parameter, per-stage path reports, and optionally the pipe placed and
# routed alone.
#
#   vivado -mode batch -source hw/probe_l.tcl -tclargs \
#       <exp_w> <man_w> <en_augadd|none> [freq_mhz] [synth|impl] [build_dir] [part] [rtl_dir]
#
#   the U50's rungs: 8 23 | 11 52 | 15 112 | 19 236, at 135 MHz
#   (KERNEL_FREQ=135000000, the period 7.407 ns). en_augadd "none"
#   passes no EN_AUGADD generic, for a tree from before R21 (5e033f6),
#   whose pipe has no such parameter. hw/probe_l.sh runs the matrix.
#
# Prints, for hw/probe_l.sh to collect:
#   PROBE_L_TAG    e<exp>m<man> en=<...> <stage> <freq>
#   PROBE_L_UTIL_<st>   the CLB LUTs, CLB Registers, CARRY8 and DSPs lines
#   PROBE_L_WORST_<st>  the pipe's worst setup path anywhere
#   PROBE_L_S6_<st>     the worst path ending at S6's alignment-prep
#                       registers (s6_*, the product's s6_mp_r excepted)
#   PROBE_L_S10_<st>    the worst path ending at S10's registers (s10_*)
#   PROBE_L_S13_<st>    the worst path ending at the round stage (s13_*),
#                       the pipe's critical stage on record, to compare
# each as slack, data path delay, logic levels, start -> end; <st> is
# synth, and routed too at the impl stage.
#
# Read the PATH DELAY, not the slack (synth_ooc.tcl): implementation is
# constraint-driven, and a synthesis-only delay has no wire in it - the
# impl stage places and routes the pipe alone for the wire. Neither sees
# the kernel around the pipe; the kernel's own worst path out of context
# is +1.576 ns at 135 MHz today (docs/VALIDATION.md, revision 7), an
# engine path, and the question for each pipe is whether its worst slack
# stays above that.

set exp_w 8
set man_w 23
set en_aug 1
set freq 135
set stage synth
set build_dir "build_probe_l"
set part "xcu50-fsvh2104-2-e"
set hw_dir  [file dirname [file normalize [info script]]]
set rtl_dir [file normalize "$hw_dir/../rtl"]
if {$argc >= 1} { set exp_w [lindex $argv 0] }
if {$argc >= 2} { set man_w [lindex $argv 1] }
if {$argc >= 3} { set en_aug [lindex $argv 2] }
if {$argc >= 4} { set freq [lindex $argv 3] }
if {$argc >= 5} { set stage [lindex $argv 4] }
if {$argc >= 6} { set build_dir [lindex $argv 5] }
if {$argc >= 7} { set part [lindex $argv 6] }
if {$argc >= 8} { set rtl_dir [file normalize [lindex $argv 7]] }

file mkdir $build_dir
set period [format %.3f [expr {1000.0 / $freq}]]
set tag "e${exp_w}m${man_w} en=${en_aug} ${stage} ${freq}MHz"
puts "PROBE_L_TAG: $tag rtl=$rtl_dir part=$part period=${period}ns"

create_project -in_memory -part $part
read_verilog -sv [list $rtl_dir/cft_fpfma.sv $rtl_dir/cft_fpfma_pipe.sv]
set gargs [list -generic EXP_W=$exp_w -generic MAN_W=$man_w -generic LATENCY=16]
if {$en_aug ne "none"} { lappend gargs -generic EN_AUGADD=$en_aug }
synth_design -top cft_fpfma_pipe -mode out_of_context -include_dirs $rtl_dir {*}$gargs
create_clock -period $period -name clk [get_ports clk]

proc probe_reports {suffix} {
  global build_dir
  report_utilization -file $build_dir/util_$suffix.rpt
  report_timing_summary -file $build_dir/timing_$suffix.rpt -no_detailed_paths
  set util [report_utilization -return_string]
  foreach line [split $util "\n"] {
    if {[regexp {^\| (CLB LUTs|CLB Registers|CARRY8|DSPs)} $line]} {
      puts "PROBE_L_UTIL_$suffix: [string trim $line]"
    }
  }
  set regs [all_registers]
  set groups [list \
    WORST {} \
    S6  [filter $regs {NAME =~ "*s6_*" && NAME !~ "*s6_mp*"}] \
    S10 [filter $regs {NAME =~ "*s10_*"}] \
    S13 [filter $regs {NAME =~ "*s13_*"}]]
  foreach {g cells} $groups {
    if {$g eq "WORST"} {
      set p [lindex [get_timing_paths -max_paths 1 -nworst 1 -setup] 0]
      report_timing -max_paths 5 -file $build_dir/paths_${suffix}_worst.rpt
    } elseif {[llength $cells] == 0} {
      puts "PROBE_L_${g}_$suffix: no register matched"
      continue
    } else {
      set p [lindex [get_timing_paths -to $cells -max_paths 1 -nworst 1 -setup] 0]
      report_timing -to $cells -max_paths 5 -file $build_dir/paths_${suffix}_[string tolower $g].rpt
    }
    if {$p eq ""} { puts "PROBE_L_${g}_$suffix: no path"; continue }
    puts [format "PROBE_L_%s_%s: slack=%s delay=%s levels=%s %s -> %s" $g $suffix \
      [get_property SLACK $p] [get_property DATAPATH_DELAY $p] \
      [get_property LOGIC_LEVELS $p] \
      [get_property STARTPOINT_PIN $p] [get_property ENDPOINT_PIN $p]]
  }
}

probe_reports synth
if {$stage eq "synth"} {
  puts "PROBE_L_STAGE: synth"
  exit
}

# The pipe alone, placed and routed. An out-of-context pipe has no I/O
# constraints, so read the register-to-register paths above, not its
# ports.
opt_design
place_design
route_design
probe_reports routed
puts "PROBE_L_STAGE: routed"
