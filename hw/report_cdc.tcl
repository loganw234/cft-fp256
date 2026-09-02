# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
#
# Clock-domain-crossing and constraint-coverage review of a ROUTED
# design checkpoint.
#
#   vivado -mode batch -source hw/report_cdc.tcl -tclargs <routed.dcp> [outdir]
#
# Static timing analysis only proves things about paths it was told to
# analyse, between clocks it was told are related. Two things escape it,
# and both are what this script looks for:
#
#   * an UNCONSTRAINED path is not a met path, it is an unexamined one.
#     `check_timing` enumerates endpoints with no clock, no input delay,
#     no output delay - the ones a timing summary silently omits from
#     its WNS.
#   * a CLOCK-DOMAIN CROSSING between asynchronous clocks cannot be
#     fixed by slack at all. It needs a synchroniser, and whether one is
#     present is a structural question `report_cdc` answers and a WNS
#     number never does.
#
# The kernel here is single-clock (ap_clk), so its own CDC surface
# should be empty and the crossings should all belong to the platform
# shell - which is Xilinx's, pre-verified, and not ours to fix. That is
# a PREDICTION this script exists to check rather than assume: the
# reports are written per-scope so "the kernel has no crossings of its
# own" is something a reader can confirm instead of taking on trust.

if {$argc < 1} {
  puts "usage: report_cdc.tcl <routed.dcp> \[outdir\]"
  exit 2
}
set dcp [lindex $argv 0]
set outdir "cdc-report"
if {$argc >= 2} { set outdir [lindex $argv 1] }
file mkdir $outdir

puts "== opening $dcp"
open_checkpoint $dcp

# ---- 1. constraint coverage -----------------------------------------
# check_timing is the one that finds paths the summary never looked at.
puts "== check_timing (unconstrained paths, missing delays)"
check_timing -verbose -file $outdir/check_timing.rpt

# ---- 2. clock-domain crossings --------------------------------------
puts "== report_cdc (whole design)"
report_cdc -details -file $outdir/cdc_full.rpt

puts "== report_clock_interaction (whole design)"
report_clock_interaction -delay_type min_max -file $outdir/clock_interaction.rpt

# ---- 3. the kernel's own surface ------------------------------------
# Scoped so the shell's crossings do not drown the question we can
# actually act on. The cell name differs between single and quad links,
# so find it rather than hardcode it.
set krnl [get_cells -hier -filter {NAME =~ "*cft_krnl*" && IS_PRIMITIVE == 0} -quiet]
if {[llength $krnl] > 0} {
  set top [lindex $krnl 0]
  puts "== kernel scope: $top"
  report_cdc -details -cells $top -file $outdir/cdc_kernel.rpt -quiet
  # every clock that reaches the kernel: more than one is the thing to know
  set kclk [get_clocks -of_objects [get_cells -hier -filter "NAME =~ ${top}/*" -quiet] -quiet]
  set fh [open $outdir/kernel_clocks.rpt w]
  puts $fh "clocks reaching $top:"
  foreach c $kclk { puts $fh "  [get_property NAME $c]  period=[get_property PERIOD $c]" }
  close $fh
} else {
  puts "== WARNING: no cft_krnl cell found; kernel-scoped reports skipped"
}

# ---- 4. methodology (includes the CDC rule set) ---------------------
puts "== report_methodology"
report_methodology -file $outdir/methodology.rpt -quiet

puts "== report_drc (routed)"
report_drc -file $outdir/drc.rpt -quiet

# ---- 5. a short machine-readable summary ----------------------------
set fh [open $outdir/SUMMARY.txt w]
puts $fh "dcp: $dcp"
puts $fh "date: [clock format [clock seconds]]"
# CDC severities, counted from the report Vivado just wrote
foreach sev {Critical Warning Info} {
  set n 0
  if {[catch {set n [llength [get_cdc_violations -quiet -filter "SEVERITY == $sev"]]}]} { set n "n/a" }
  puts $fh "cdc_${sev}: $n"
}
puts $fh "methodology_violations: [llength [get_methodology_violations -quiet]]"
puts $fh "drc_violations: [llength [get_drc_violations -quiet]]"
close $fh
puts "== SUMMARY =="
puts [read [open $outdir/SUMMARY.txt r]]
puts "== reports in $outdir"
