# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
#
# Package the RTL into a Vitis kernel object (.xo).
#
#   vivado -mode batch -source hw/package_kernel.tcl -tclargs <part> <build_dir>
#
# Defaults target the Alveo U50/U50C part. Driven by the top-level
# Makefile (`make xo`); the flow follows the Vitis_Accel_Examples RTL
# kernel packaging sequence.
#
# HONESTY NOTE (v0): this script is written to the documented flow but
# has not yet been run against a live Vitis install - it is the first
# thing docs/BRINGUP.md says to validate on the synthesis box.

set part      "xcu50-fsvh2104-2-e"
set build_dir "build"
if {$argc >= 1} { set part      [lindex $argv 0] }
if {$argc >= 2} { set build_dir [lindex $argv 1] }

set hw_dir  [file dirname [file normalize [info script]]]
set rtl_dir [file normalize "$hw_dir/../rtl"]
set pkg_dir [file normalize "$build_dir/packaged_kernel"]
set tmp_dir [file normalize "$build_dir/tmp_kernel_pack"]
set xo_path [file normalize "$build_dir/cft_krnl.xo"]

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
foreach up [ipx::get_user_parameters] {
  ipx::remove_user_parameter [get_property NAME $up] $core
}
set_property sdx_kernel true $core
set_property sdx_kernel_type rtl $core
set_property supported_families { } $core
set_property auto_family_support_level level_2 $core
ipx::create_xgui_files $core
ipx::associate_bus_interfaces -busif s_axi_control -clock ap_clk $core
ipx::associate_bus_interfaces -busif m00_axi -clock ap_clk $core
ipx::update_checksums $core
ipx::save_core $core
close_project -delete

package_xo -xo_path $xo_path -kernel_name cft_krnl \
    -ip_directory $pkg_dir -kernel_xml $hw_dir/kernel.xml -force

puts "INFO: wrote $xo_path"
