# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
#
# Probe RT (the step-6 leftovers round, parcel RT): does RETIMING=1
# retime? Every link's kernel synthesis runs `synth_design ... -retiming
# -mode out_of_context` with no clock constraint, and Vivado 2022.2 says
# so in each run ("INFO: [Synth 8-11322] No global retiming is needed
# without any clock constraint"). This synthesizes one module out of
# context in ONE of four ways, so that hw/probe_rt.sh can set them side by
# side:
#
#   a   no -retiming, no clock          a build with RETIMING=0
#   b   -retiming, no clock             every link's kernel since 2026-09-02
#   c   -retiming, a clock in force     what RETIMING=1 was believed to do
#   d   the clock, no -retiming         what the clock alone does
#
#   vivado -mode batch -source hw/probe_rt.tcl -tclargs \
#       <a|b|c|d> <freq_mhz> <part> <out_dir> <rtl_dir> <top> <clock_port> <threads>
#
# The generics come through the environment, PROBE_RT_GENERICS="NAME=VALUE
# ...", never -tclargs (cmd.exe splits an argument at `=`; the header of
# hw/package_kernel.tcl says why), each passed as `-generic NAME=VALUE`.
#
# THE CLOCK. For c and d it is a create_clock on <clock_port> in an XDC
# read BEFORE synth_design, so synthesis is timing-driven against it and
# global retiming has a target. For a and b the same create_clock is
# applied AFTER synth_design - as the link's implementation applies its
# clock, and as every earlier probe here (ooc_retime.tcl, synth_krnl_ooc
# .tcl, probe S, L and K) applied theirs - so all four report a
# post-synthesis estimate against one clock. PROBE_RT_CLOCK_AT_SYNTH says
# which: the clocks in force when synth_design returned.
#
# Prints, for hw/probe_rt.sh to gather:
#   PROBE_RT             mode, top, generics, freq, period, port, threads, rtl
#   PROBE_RT_TOOL        the Vivado version
#   PROBE_RT_CLOCK_AT_SYNTH  0 for a and b, 1 for c and d
#   PROBE_RT_MSG         how many times Vivado issued Synth 8-11322 (declined:
#                        no clock) and Synth 8-5816 ("Retiming module", what
#                        it prints when global retiming runs), from
#                        get_msg_config; the run's log carries the
#                        "Retiming Report:" table itself when one is made
#   PROBE_RT_RETIMED     sequential cells whose names global retiming gives
#                        them (*_bret*, *_fret*: backward, forward)
#   PROBE_RT_UTIL        report_utilization's summary rows, the FIRST line of
#                        each name (later tables repeat names, some with
#                        zeros): CLB LUTs, CLB Registers, CARRY8, Block RAM
#                        Tile, URAM, DSPs
#   PROBE_RT_PRIM        the Primitives table: REF_NAME=count, one line
#   PROBE_RT_DSP         DSP48E2 cells, and how many have each of AREG, BREG,
#                        CREG, DREG, ADREG, MREG, PREG set - the "DSP output
#                        registers" the 2026-09-02 entry credits to retiming
#   PROBE_RT_DSP_0902    the same two counts the way hw/ooc_retime.tcl took
#                        them (every cell whose PRIMITIVE_TYPE matches *DSP*,
#                        MREG and PREG read where the property exists), to
#                        set beside that entry's 188
#   PROBE_RT_WNS         worst setup slack, TNS and failing endpoints against
#                        the clock, and the worst path's levels
#   PROBE_RT_CHECK       with SEQ_SCRATCH_D among the generics: URAM288 cells
#                        = SEQ_SCRATCH_D / 32 (cft_seq's scratch, 4,096 x 32
#                        sub-arrays; probe K's proof that a generic took)
#   PROBE_RT_NETLIST     the funcsim netlist written for the fingerprint;
#                        hw/probe_rt.sh hashes it with comment lines removed
#                        (they carry the date and the command)
#   PROBE_RT_DONE        the last line; a run without it did not finish
#
# Each section is caught on its own (PROBE_RT_ERR), so one failure does not
# hide the rest. A failed synth_design exits 3.

set mode a
set freq 135
set part "xcu50-fsvh2104-2-e"
set out "build_probe_rt"
set rtl_dir ""
set top cft_krnl
set clock_port ap_clk
set threads 8
if {$argc >= 1} { set mode [lindex $argv 0] }
if {$argc >= 2} { set freq [lindex $argv 1] }
if {$argc >= 3} { set part [lindex $argv 2] }
if {$argc >= 4} { set out [lindex $argv 3] }
if {$argc >= 5} { set rtl_dir [lindex $argv 4] }
if {$argc >= 6} { set top [lindex $argv 5] }
if {$argc >= 7} { set clock_port [lindex $argv 6] }
if {$argc >= 8} { set threads [lindex $argv 7] }
if {$mode ni {a b c d}} {
  puts "PROBE_RT_ERR: mode '$mode' is not a, b, c or d"
  exit 2
}
if {$rtl_dir eq ""} {
  set rtl_dir [file normalize "[file dirname [file normalize [info script]]]/../rtl"]
}
set rtl_dir [file normalize $rtl_dir]
set generics {}
if {[info exists ::env(PROBE_RT_GENERICS)]} { set generics $::env(PROBE_RT_GENERICS) }
file mkdir $out
set out [file normalize $out]
set period [format %.3f [expr {1000.0 / $freq}]]

puts "PROBE_RT: mode=$mode top=$top generics={$generics} freq=$freq period=${period}ns port=$clock_port threads=$threads part=$part rtl=$rtl_dir out=$out"
puts "PROBE_RT_TOOL: [version -short]"

proc sec {name body} {
  if {[catch {uplevel 1 $body} err]} { puts "PROBE_RT_ERR: $name: $err" }
}

set_param general.maxThreads $threads
create_project -in_memory -part $part
read_verilog -sv [glob $rtl_dir/*.sv]

if {$mode in {c d}} {
  set f [open $out/synth_clock.xdc w]
  puts $f "create_clock -period $period -name $clock_port \[get_ports $clock_port\]"
  close $f
  read_xdc $out/synth_clock.xdc
}

set sargs [list -top $top -part $part -mode out_of_context -include_dirs $rtl_dir]
foreach g $generics { lappend sargs -generic $g }
if {$mode in {b c}} { lappend sargs -retiming }
puts "PROBE_RT_SYNTH: synth_design $sargs"
if {[catch {synth_design {*}$sargs} err]} {
  puts "PROBE_RT_ERR: synth_design: $err"
  exit 3
}

set at_synth [llength [get_clocks -quiet]]
puts "PROBE_RT_CLOCK_AT_SYNTH: $at_synth"
if {$at_synth == 0} {
  create_clock -period $period -name $clock_port [get_ports $clock_port]
}

sec msg {
  set m ""
  foreach id {{Synth 8-11322} {Synth 8-5816}} {
    append m " [string map {{ } _} $id]=[get_msg_config -id $id -count]"
  }
  puts "PROBE_RT_MSG:$m"
}

sec retimed {
  set bret [llength [get_cells -quiet -hierarchical -filter {IS_SEQUENTIAL && NAME =~ "*_bret*"}]]
  set fret [llength [get_cells -quiet -hierarchical -filter {IS_SEQUENTIAL && NAME =~ "*_fret*"}]]
  puts "PROBE_RT_RETIMED: bret=$bret fret=$fret"
}

sec util {
  report_utilization -file $out/util.rpt
  set seen {}
  set prim {}
  set in_prim 0
  foreach line [split [report_utilization -return_string] "\n"] {
    if {[regexp {^\| (CLB LUTs|CLB Registers|CARRY8|Block RAM Tile|URAM|DSPs)} $line -> name]} {
      if {[lsearch -exact $seen $name] < 0} {
        lappend seen $name
        puts "PROBE_RT_UTIL: [string trim $line]"
      }
    }
    if {[regexp {^\d+\. Primitives} $line]} { set in_prim 1; continue }
    if {$in_prim && [regexp {^\d+\. } $line]} { set in_prim 0 }
    if {$in_prim && [regexp {^\|\s*([A-Za-z0-9_]+)\s*\|\s*(\d+)\s*\|} $line -> ref n]} {
      if {$ref ne "Ref Name"} { lappend prim "$ref=$n" }
    }
  }
  puts "PROBE_RT_PRIM: [join [lsort $prim] { }]"
}

sec dsp {
  set dsps [get_cells -quiet -hierarchical -filter {REF_NAME == DSP48E2}]
  set line "total=[llength $dsps]"
  foreach p {AREG BREG CREG DREG ADREG MREG PREG} {
    set n 0
    foreach c $dsps {
      set v [get_property -quiet $p $c]
      if {$v ne "" && $v > 0} { incr n }
    }
    append line " $p=$n"
  }
  puts "PROBE_RT_DSP: $line"
}

sec dsp0902 {
  # hw/ooc_retime.tcl's own loop, unchanged in substance.
  set n_mreg 0; set n_preg 0
  set cells [get_cells -hier -filter {PRIMITIVE_TYPE =~ *DSP*} -quiet]
  foreach c $cells {
    if {[catch {set m [get_property MREG $c]}]} { continue }
    if {$m == 1} { incr n_mreg }
    if {![catch {set p [get_property PREG $c]}] && $p == 1} { incr n_preg }
  }
  puts "PROBE_RT_DSP_0902: cells=[llength $cells] MREG=$n_mreg PREG=$n_preg"
}

sec wns {
  set p [lindex [get_timing_paths -max_paths 1 -nworst 1 -setup] 0]
  set wns [get_property SLACK $p]
  set lv [get_property LOGIC_LEVELS $p]
  set tns "?"; set nfail "?"; set ntot "?"
  set rts [report_timing_summary -no_detailed_paths -return_string]
  report_timing_summary -no_detailed_paths -file $out/timing.rpt
  set f 0
  foreach line [split $rts "\n"] {
    if {[string match "*Design Timing Summary*" $line]} { set f 1; continue }
    if {$f && [regexp {^\s*(-?[0-9]+\.[0-9]+)\s+(-?[0-9]+\.[0-9]+)\s+(\d+)\s+(\d+)} $line -> w t nf nt]} {
      set tns $t; set nfail $nf; set ntot $nt; break
    }
  }
  puts "PROBE_RT_WNS: wns=$wns tns=$tns failing=$nfail endpoints=$ntot levels=$lv"
  report_timing -max_paths 10 -nworst 1 -unique_pins -file $out/paths.rpt
}

sec check {
  foreach g $generics {
    if {[regexp {^SEQ_SCRATCH_D=(\d+)$} $g -> slots]} {
      set want [expr {$slots / 32}]
      set got [llength [get_cells -quiet -hierarchical -filter {REF_NAME == URAM288}]]
      puts "PROBE_RT_CHECK: [expr {$got == $want ? "PASS" : "FAIL"}] URAM288 cells $got, SEQ_SCRATCH_D=$slots wants $want"
    }
  }
}

sec netlist {
  write_verilog -force -mode funcsim $out/netlist.v
  puts "PROBE_RT_NETLIST: $out/netlist.v"
}

puts "PROBE_RT_DONE: mode=$mode"
