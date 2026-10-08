# block_design.tcl — PS + nn_infer IP -> bitstream, script-driven.
#
#   & "C:\Xilinx\Vivado\2022.1\bin\vivado.bat" -mode batch -notrace -nolog -nojournal `
#       -source block_design.tcl -tclargs 6 A bd      # block design only, ~2 min
#   ... -tclargs 6 A                                   # full, through write_bitstream
#
# Consumes the IP run_hls.tcl packaged; produces bit/nn_w<N>_<B>.{bit,hwh}.
# Run install_board.tcl once per Vivado installation first.

source [file join [file dirname [info script]] session.tcl]
set args $argv
if {[lindex $args 0] eq "-tclargs"} { set args [lrange $args 1 end] }
set width [lindex $args 0]
set build [lindex $args 1]
set mode  [lindex $args 2]

# The width defaults to whatever the export selected, never to a literal.
# Same source of truth the HLS build reads, one directory over.
source [file join [file dirname [info script]] .. .. hls tcl nn_width.tcl]
if {$width eq ""} {
    set width [nn_width::selected [file join [file dirname [info script]] .. .. hls]]
}
if {$build eq ""} { set build A }
set build [string toupper $build]
if {![string is integer -strict $width] || $width < 1 || $build ni {A B C D E}} {
    error "expected a positive width and build A, B, C, D or E"
}
if {$mode  eq ""} { set mode full }
if {$mode ni {full bd impl}} { error "mode must be full, bd or impl" }

# This script lives in vivado/tcl/. Everything it writes -- the project, bit/
# and reports/ -- belongs one level up, so $here is the vivado directory and
# $nn_tcl_dir is where its companions are.
set nn_tcl_dir [file normalize [file dirname [info script]]]
set here   [file normalize [file join $nn_tcl_dir ..]]
set hls_ip "$here/../hls/hls_w${width}_${build}/sol/impl/ip"
if {![file exists "$hls_ip/component.xml"]} {
    error "no packaged IP at $hls_ip — run run_hls.tcl for w$width build $build first"
}

# Ultra96-V2, confirmed on hardware. The part comes from the board file rather
# than a second literal, so the two cannot drift apart.
set board    "avnet.com:ultra96v2:part0:1.2"
set freq_mhz 100
set proj     "vivado_w${width}_${build}"
set bd       "nn"
set out      "nn_w${width}_${build}"

if {$mode eq "impl"} {
    open_project "$here/$proj/$proj.xpr"
    source [file join $nn_tcl_dir implement.tcl]
    nn_vivado_finish
}

# XHub installs the board files under the store's own root and a fresh session
# does not scan it. Same two lines as install_board.tcl, for the same reason.
set_param board.repoPaths \
    [get_property LOCAL_ROOT_DIR [xhub::get_xstores xilinx_board_store]]
if {[llength [get_board_parts -quiet -filter "NAME == \"$board\""]] == 0} {
    error "$board not visible — run install_board.tcl first"
}
set part [get_property PART_NAME [get_board_parts $board]]
puts "BOARD: $board -> part $part"

if {[file exists "$here/$proj"]} {
    error "Project $here/$proj already exists. Use src/scripts/vivado.bat or src/scripts/vivado.sh for checked cleanup."
}
create_project $proj "$here/$proj" -part $part
set_property board_part $board [current_project]
set_property ip_repo_paths $hls_ip [current_project]
update_ip_catalog -rebuild

create_bd_design $bd

# --- PS, from the board preset ---------------------------------------------
set ps [create_bd_cell -type ip -vlnv xilinx.com:ip:zynq_ultra_ps_e zynq_ultra_ps_e_0]
apply_bd_automation -rule xilinx.com:bd_rule:zynq_ultra_ps_e \
    -config {apply_board_preset "1"} $ps

# GP0 = M_AXI_HPM0_FPD (AXI-Lite control). GP2 = S_AXI_HP0_FPD (the gmem path).
# The other masters stay off: an unused one still costs a SmartConnect port.
set_property -dict [list \
    CONFIG.PSU__USE__M_AXI_GP0 {1} \
    CONFIG.PSU__USE__M_AXI_GP1 {0} \
    CONFIG.PSU__USE__M_AXI_GP2 {0} \
    CONFIG.PSU__USE__S_AXI_GP2 {1} \
    CONFIG.PSU__SAXIGP2__DATA_WIDTH {128} \
    CONFIG.PSU__CRL_APB__PL0_REF_CTRL__FREQMHZ $freq_mhz \
] $ps

# --- the accelerator --------------------------------------------------------
create_bd_cell -type ip -vlnv xilinx.com:hls:nn_infer:1.0 nn_infer_0

# PS -> control registers
apply_bd_automation -rule xilinx.com:bd_rule:axi4 -config [list \
    Clk_master {Auto} Clk_slave {Auto} Clk_xbar {Auto} \
    Master {/zynq_ultra_ps_e_0/M_AXI_HPM0_FPD} \
    Slave {/nn_infer_0/s_axi_control} \
    ddr_seg {Auto} intc_ip {New AXI SmartConnect} master_apm {0}] \
    [get_bd_intf_pins nn_infer_0/s_axi_control]

# accelerator -> PS DRAM
apply_bd_automation -rule xilinx.com:bd_rule:axi4 -config [list \
    Clk_master {Auto} Clk_slave {Auto} Clk_xbar {Auto} \
    Master {/nn_infer_0/m_axi_gmem} \
    Slave {/zynq_ultra_ps_e_0/S_AXI_HP0_FPD} \
    ddr_seg {Auto} intc_ip {New AXI SmartConnect} master_apm {0}] \
    [get_bd_intf_pins zynq_ultra_ps_e_0/S_AXI_HP0_FPD]

assign_bd_address
validate_bd_design
save_bd_design

# Output generation and implementation run after this process closes the BD.
close_project
if {$mode eq "full"} {
    puts "VIVADO: reopening the saved block design in a fresh process."
    exec [info nameofexecutable] -mode batch -log implement.log -journal implement.jou \
        -source [file normalize [info script]] -tclargs $width $build impl >@stdout 2>@stderr
}
nn_vivado_finish
