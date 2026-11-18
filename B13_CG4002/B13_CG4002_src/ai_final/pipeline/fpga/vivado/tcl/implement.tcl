# Sourced by block_design.tcl only in the fresh implementation process.
set bd_file [get_files "$here/$proj/$proj.srcs/sources_1/bd/$bd/$bd.bd"]
open_bd_design $bd_file
# Generate explicitly once, before make_wrapper and launch_runs. A failed
# simulation target is a real error; do not suppress it or force regeneration.
generate_target all $bd_file
set wrapper [make_wrapper -files $bd_file -top]
add_files -norecurse $wrapper
set_property top ${bd}_wrapper [current_fileset]
update_compile_order -fileset sources_1
save_bd_design

launch_runs impl_1 -to_step write_bitstream -jobs 4
wait_on_run impl_1
set run [get_runs impl_1]
set status [get_property STATUS $run]
if {[get_property PROGRESS $run] ne "100%" || ![string match "*write_bitstream Complete*" $status]} {
    error "Implementation failed: $status. See $here/$proj/$proj.runs/impl_1"
}

open_run impl_1
file mkdir "$here/reports"
report_timing_summary -file "$here/reports/${out}_timing.rpt"
report_utilization -file "$here/reports/${out}_utilization.rpt"
report_power -file "$here/reports/${out}_power.rpt"

set wns [get_property SLACK [get_timing_paths -delay_type max]]
set whs [get_property SLACK [get_timing_paths -delay_type min]]
puts "TIMING: WNS = $wns ns, WHS = $whs ns"
if {$wns eq "" || $whs eq "" || $wns < 0 || $whs < 0} {
    error "Timing is missing or not met; do not deploy this build. See the timing report."
}

set bit "$here/$proj/$proj.runs/impl_1/${bd}_wrapper.bit"
set hwh "$here/$proj/$proj.gen/sources_1/bd/$bd/hw_handoff/${bd}.hwh"
foreach path [list $bit $hwh] {
    if {![file exists $path] || [file size $path] == 0} { error "Missing output: $path" }
}
file mkdir "$here/bit"
file copy -force $bit "$here/bit/${out}.bit"
file copy -force $hwh "$here/bit/${out}.hwh"
puts "wrote bit/${out}.bit and bit/${out}.hwh"
close_project
