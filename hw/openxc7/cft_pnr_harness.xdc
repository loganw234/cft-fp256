# Pins for the place-and-route harness only. The clock pair and AB8 are
# openXC7/demo-projects blinky-kc705's own (xc7k325tffg900-2, bank 33);
# AA8 and AC9 are the KC705's neighbouring bank-33 LED pins. A bitstream
# built against this file must never be loaded onto a board.
set_property LOC AD12 [get_ports clk_p]
set_property IOSTANDARD LVDS [get_ports {clk_p}]
set_property LOC AD11 [get_ports clk_n]
set_property IOSTANDARD LVDS [get_ports {clk_n}]

set_property LOC AB8 [get_ports sout]
set_property IOSTANDARD LVCMOS15 [get_ports {sout}]
set_property LOC AA8 [get_ports sin]
set_property IOSTANDARD LVCMOS15 [get_ports {sin}]
set_property LOC AC9 [get_ports rst_n_pin]
set_property IOSTANDARD LVCMOS15 [get_ports {rst_n_pin}]
