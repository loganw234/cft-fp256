# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
#
# Prove what a packaged kernel IP instantiates, without linking it.
#
#   vivado -mode batch -source hw/verify_xo.tcl -tclargs <part> <pkg_dir> <work_dir>
#
# Instantiate the packaged IP in a throwaway project exactly the way the
# Vitis link project will, generate its synthesis wrapper, and print the
# parameter overrides that wrapper hands to cft_krnl. A generic that did
# not survive packaging shows up here as its RTL default - twenty
# minutes after packaging rather than two hours after a link, which is
# the whole reason to have it. hw/rebuild-2022.sh runs this whenever
# CFT_GENERICS is set and refuses to link if a requested value is not
# the one the wrapper carries.
#
# Ported from cft-rebound's hw/verify_variant_xo.tcl (2026-09-13), which
# proved its binary128-only image this way before either of its links.

set part     "xcu50-fsvh2104-2-e"
set pkg_dir  ""
set work_dir ""
if {$argc >= 1} { set part     [lindex $argv 0] }
if {$argc >= 2} { set pkg_dir  [file normalize [lindex $argv 1]] }
if {$argc >= 3} { set work_dir [file normalize [lindex $argv 2]] }
if {$pkg_dir eq "" || $work_dir eq ""} {
  error "usage: -tclargs <part> <pkg_dir> <work_dir>"
}

create_project -force xo_verify $work_dir -part $part
set_property ip_repo_paths $pkg_dir [current_project]
update_ip_catalog
create_ip -vlnv improperaperture.com:kernel:cft_krnl:1.0 -module_name cft_krnl_v
generate_target {instantiation_template synthesis} [get_ips cft_krnl_v]

# The wrapper the IP integrator would synthesise.
set found 0
foreach f [get_files -all -of_objects [get_ips cft_krnl_v]] {
  if {[string match "*/synth/cft_krnl_v.v" $f] || [string match "*/synth/cft_krnl_v.sv" $f]} {
    set found 1
    puts "WRAPPER: $f"
    set fh [open $f r]
    set txt [read $fh]
    close $fh
    # Every override in cft_krnl's parameter block - from `cft_krnl #(` to
    # the `) inst (` that closes it - not a list of names: a list written
    # before revision 8 left out SEQ_*, EN_WIDE and EN_AUGADD, so the first
    # image that set SEQ_SCRATCH_D (rev8a, 2026-10-05) was refused here
    # while its wrapper carried .SEQ_SCRATCH_D(4096). A name cft_krnl does
    # not declare is refused at packaging (hw/package_kernel.tcl).
    set inpar 0
    set nparams 0
    foreach line [split $txt "\n"] {
      if {!$inpar} {
        if {[regexp {^\s*cft_krnl\s+#\(\s*$} $line]} { set inpar 1 }
        continue
      }
      if {[regexp {^\s*\)} $line]} { set inpar 0; continue }
      if {[regexp {^\s*\.([A-Za-z_][A-Za-z0-9_]*)\s*\(} $line]} {
        puts "WRAPPER_PARAM: [string trim $line]"
        incr nparams
      }
    }
    if {$nparams == 0} { error "no parameter overrides found in $f: its cft_krnl #( block was not read" }
    puts "WRAPPER_PARAMS: $nparams"
  }
}
if {!$found} { error "no synthesis wrapper generated for cft_krnl_v" }
close_project
