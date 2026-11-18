puts "HLS: starting C/RTL co-simulation. The initial C testbench summary is not the final RTL result."
puts "HLS: RTL simulation follows; watch the completed transaction count in $project/sol/sim/verilog/xsim.log."
source [file join [file dirname [info script]] cosim_workaround.tcl]
nn_cosim::run -argv $cosim_args -rtl verilog -trace_level none -mflags "DEBUG="
