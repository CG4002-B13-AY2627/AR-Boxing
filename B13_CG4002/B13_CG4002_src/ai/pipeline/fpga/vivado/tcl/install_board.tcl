# Install the Avnet Ultra96-V2 1.2 board definition when needed.
# Run with:
#   & "C:\Xilinx\Vivado\2022.1\bin\vivado.bat" -mode batch -notrace -nolog -nojournal -source install_board.tcl

source [file join [file dirname [info script]] session.tcl]
set store [xhub::get_xstores xilinx_board_store]
set_param board.repoPaths [get_property LOCAL_ROOT_DIR $store]

set bp [get_board_parts -quiet -filter {NAME == "avnet.com:ultra96v2:part0:1.2"}]
if {[llength $bp] == 0} {
    xhub::refresh_catalog $store

    set item [xhub::get_xitems -filter {NAME == "avnet.com:xilinx_board_store:Ultra96v2:1.2"}]
    if {[llength $item] == 0} {
        error "Ultra96-V2 1.2 was not found in the XHub catalog"
    }

    xhub::install $item

    set bp [get_board_parts -quiet -filter {NAME == "avnet.com:ultra96v2:part0:1.2"}]
    if {[llength $bp] == 0} {
        error "Ultra96-V2 1.2 is not visible after installation"
    }
}

puts "Board part available: $bp"
nn_vivado_finish
