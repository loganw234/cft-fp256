# Tile- and site-type census of 7-series parts, to answer: does a part
# bring any tile type (or site type) that prjxray-db's family does not
# already model? Nothing here needs a design: the part is opened the way
# openXC7/prjxray#16 opens it for 005-tilegrid (link_design, no netlist),
# because SITE_TYPE on a placed design reports what a site is configured
# as, not what it is.
#
#   vivado -mode batch -source census.tcl -tclargs <out.txt> <part> [part ...]

set out   [lindex $argv 0]
set parts [lrange $argv 1 end]
set fh [open $out w]

foreach part $parts {
  if {[llength [get_parts -quiet $part]] == 0} {
    puts $fh "PART $part UNAVAILABLE (not in the active licence tier or not installed)"
    flush $fh
    continue
  }
  set how "link_design"
  if {[catch {link_design -part $part} err]} {
    # Fallback: one flip-flop, synthesised, which loads the same device.
    set how "synth_design (link_design said: [string range $err 0 80])"
    set v [file join [file dirname $out] census_top.v]
    set vf [open $v w]
    puts $vf "module top(input c, input d, output reg q); always @(posedge c) q <= d; endmodule"
    close $vf
    create_project -in_memory -part $part
    read_verilog $v
    synth_design -top top -part $part
  }

  set tiles [get_tiles]
  set tcount [dict create]
  foreach t [get_property TYPE $tiles] { dict incr tcount $t }
  set xs [get_property GRID_POINT_X $tiles]
  set ys [get_property GRID_POINT_Y $tiles]
  set gx [expr {[tcl::mathfunc::max {*}$xs] + 1}]
  set gy [expr {[tcl::mathfunc::max {*}$ys] + 1}]

  set sites [get_sites]
  set scount [dict create]
  foreach s [get_property SITE_TYPE $sites] { dict incr scount $s }

  # Grid columns carrying an interconnect tile: the first thing
  # utils/tilegrid_derive.py checks against a part's part.yaml.
  set intx [dict create]
  foreach t [get_tiles -filter {TYPE == INT_L || TYPE == INT_R}] {
    dict set intx [get_property GRID_POINT_X $t] 1
  }

  puts $fh "PART $part opened_by {$how} tiles [llength $tiles] tile_types [dict size $tcount] grid ${gx}x${gy} sites [llength $sites] site_types [dict size $scount] clock_regions [llength [get_clock_regions]] int_columns [dict size $intx]"
  foreach k [lsort [dict keys $tcount]] { puts $fh "TILE $part $k [dict get $tcount $k]" }
  foreach k [lsort [dict keys $scount]] { puts $fh "SITE $part $k [dict get $scount $k]" }
  flush $fh
  close_design
  catch {close_project}
}
close $fh
puts "CENSUS DONE: [llength $parts] part(s) -> $out"
