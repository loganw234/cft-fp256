# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
#
# Package the RTL into a Vitis kernel object (.xo).
#
#   vivado -mode batch -source hw/package_kernel.tcl -tclargs <part> <build_dir>
#   CFT_GENERICS="EN_FP256=0" vivado -mode batch -source hw/package_kernel.tcl ...
#
# Defaults target the Alveo U50/U50C part. Driven by the top-level
# Makefile (`make xo`); the flow follows the Vitis_Accel_Examples RTL
# kernel packaging sequence.
#
# Validated 2026-08-28 against Vivado 2026.1 (Windows): ran clean on
# first contact, interfaces auto-inferred, .xo written with every
# source in rtl/ (globbed below, so new modules are picked up
# automatically) and the kernel.xml arg map embedded. (.xo files are
# portable; packaging on Windows and linking on Linux is a supported
# split.)
#
# GENERICS. cft_krnl carries trim generics - EN_FP32, EN_FP64, EN_FP128,
# EN_FP256, MUL_PASSES, the FUSE_* pair - and until 2026-09-14 none of
# them could reach a bitstream through this script: the loop below
# removes every user parameter from the packaged IP, so the .xo only
# ever carried the RTL defaults, the full tile. cft-rebound needed a
# binary128-only tile, found that, and packaged its own (its
# hw/package_variant.tcl, 2026-09-13; docs/BITSTREAM.md, ask 1). The
# fix is theirs and is now here: set the requested value on the HDL
# parameter BEFORE the removal, so what the IP integrator instantiates
# is the override.
#
# They arrive in CFT_GENERICS in the environment - the same variable
# hw/impl_krnl_ooc.tcl and hw/synth_krnl_ooc.tcl already take - and not
# in -tclargs, because on Windows vivado.bat is a cmd.exe wrapper and
# cmd.exe splits an argument at `=` (hw/impl_krnl_ooc.tcl learned that
# on 2026-09-06: a parameter with no value, bound to 0). Empty means
# the defaults, which is the full tile and exactly what this script
# always built. Every HDL parameter the .xo carries is printed as
# HDLPARAM: after the removal, so the log states what was packaged
# rather than what was asked for; hw/rebuild-2022.sh copies those
# lines into the manifest, and with generics set runs
# hw/verify_xo.tcl, which instantiates the packaged IP and reads the
# values back out of the synthesis wrapper - the cheap proof, twenty
# minutes after packaging rather than two hours after a link.
#
# The kernel NAME stays cft_krnl and hw/kernel.xml is unchanged. What a
# trimmed image lacks is published by the tile itself in CAPS[3:0] and
# refused by it with STATUS[3]; the host opens compute units by reading
# MAGIC out of each one, not by their names (host/src/backend_xrt.cpp),
# so a variant needs no name of its own to be opened. Packaging one .xo
# per variant for a mixed layout is still docs/LAYOUTS.md's open item.

set part      "xcu50-fsvh2104-2-e"
set build_dir "build"
if {$argc >= 1} { set part      [lindex $argv 0] }
if {$argc >= 2} { set build_dir [lindex $argv 1] }

set generics {}
if {[info exists ::env(CFT_GENERICS)] && $::env(CFT_GENERICS) ne ""} {
  set generics $::env(CFT_GENERICS)
}

set hw_dir  [file dirname [file normalize [info script]]]
set rtl_dir [file normalize "$hw_dir/../rtl"]
set pkg_dir [file normalize "$build_dir/packaged_kernel"]
set tmp_dir [file normalize "$build_dir/tmp_kernel_pack"]
set xo_path [file normalize "$build_dir/cft_krnl.xo"]

puts "PACKAGE: part=$part build=$build_dir generics={[expr {$generics eq {} ? "defaults" : $generics}]}"

file mkdir $build_dir

create_project -force kernel_pack $tmp_dir -part $part
add_files -norecurse [glob $rtl_dir/*.sv]
set_property top cft_krnl [current_fileset]
update_compile_order -fileset sources_1

ipx::package_project -root_dir $pkg_dir -vendor improperaperture.com \
    -library kernel -taxonomy /KernelIP -import_files -set_current false
ipx::unload_core $pkg_dir/component.xml
ipx::edit_ip_in_project -upgrade true -name tmp_edit_project \
    -directory $pkg_dir $pkg_dir/component.xml

set core [ipx::current_core]
set_property core_revision 2 $core

# ---- the overrides, BEFORE the user parameters are removed ------------
# Set on the HDL parameter (what the instantiation carries) and on the
# user parameter while it still exists, so the two cannot disagree in
# the moment between here and the removal below. A name the RTL does
# not declare is an error, not a warning: a typo would otherwise
# package the full tile and say nothing.
foreach g $generics {
  if {![regexp {^([A-Za-z_][A-Za-z0-9_]*)=(.+)$} $g -> name value]} {
    error "generic '$g' is not NAME=VALUE"
  }
  set hp [ipx::get_hdl_parameters $name -of_objects $core]
  if {$hp eq ""} { error "cft_krnl declares no parameter named $name" }
  set old [get_property value $hp]
  # A `parameter bit` is stored as a QUOTED bit string - the packager
  # writes EN_FP64's default as "1" (format bitString, length 1), and
  # the 2026.1 packager accepted a bare 0 too but then carried two
  # spellings for one type. Keep the packager's own spelling: quoted,
  # same length, digits substituted. Anything else (int, long) is taken
  # verbatim.
  if {[regexp {^"([01]+)"$} $old -> bits]} {
    if {![regexp {^[01]+$} $value] || [string length $value] != [string length $bits]} {
      error "$name is a [string length $bits]-bit parameter; '$value' is not a value for it"
    }
    set value "\"$value\""
  } elseif {[regexp {^(\d+)'b[01]+$} $old -> w]} {
    set value "${w}'b${value}"
  }
  set up [ipx::get_user_parameters $name -of_objects $core]
  if {$up ne ""} { set_property value $value $up }
  set_property value $value $hp
  puts "GENERIC: $name  $old -> [get_property value $hp]"
}

foreach up [ipx::get_user_parameters] {
  ipx::remove_user_parameter [get_property NAME $up] $core
}
# What the .xo carries, by name, after the removal. This is the line a
# manifest and a reader should trust - not the request above.
foreach hp [ipx::get_hdl_parameters -of_objects $core] {
  puts "HDLPARAM: [get_property NAME $hp] = [get_property value $hp]"
}
set_property sdx_kernel true $core
set_property sdx_kernel_type rtl $core
set_property supported_families { } $core
set_property auto_family_support_level level_2 $core
ipx::create_xgui_files $core
ipx::associate_bus_interfaces -busif s_axi_control -clock ap_clk $core
foreach busif {m_axi_a m_axi_b m_axi_c m_axi_d} {
  ipx::associate_bus_interfaces -busif $busif -clock ap_clk $core
}
ipx::update_checksums $core
ipx::save_core $core
close_project -delete

package_xo -xo_path $xo_path -kernel_name cft_krnl \
    -ip_directory $pkg_dir -kernel_xml $hw_dir/kernel.xml -force

puts "INFO: wrote $xo_path"
