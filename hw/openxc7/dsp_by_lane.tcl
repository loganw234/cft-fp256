# Count the DSP48E1 cells of a routed cft_krnl checkpoint by bank, lane and
# module - the hierarchical utilisation report stops at depth 3 and charges
# merged cft_simpleops cells to their parent, so it cannot say this.
#   vivado -mode batch -source dsp_by_lane.tcl -tclargs <routed.dcp> <out.txt>
set dcp [lindex $argv 0]
set out [lindex $argv 1]
open_checkpoint $dcp
set counts [dict create]
foreach c [get_cells -hier -filter {REF_NAME == DSP48E1}] {
  set key "other"
  if {[regexp {g_bank(\d+)(?:\.g_lane\d+\[(\d+)\])?\.(u_\w+)} $c -> bank lane mod]} {
    set key "fp$bank [expr {$lane eq {} ? {-} : $lane}] $mod"
  }
  dict incr counts $key
}
set f [open $out w]
set total 0
foreach k [lsort [dict keys $counts]] {
  puts $f "[format %4d [dict get $counts $k]]  $k"
  incr total [dict get $counts $k]
}
puts $f "[format %4d $total]  total"
close $f
puts "DSP_BY_LANE DONE: $total cells -> $out"
