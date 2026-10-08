# Common settings for each independent Vivado phase.
if {[version -short] ne "2022.1"} {
    error "This flow is validated with Vivado 2022.1; found [version -short]. Select the matching installation."
}
puts "VIVADO_VERSION: [version]"
set_param general.maxThreads 2

proc nn_vivado_finish {} {
    if {[info exists ::env(NN_VIVADO_STATUS_FILE)]} {
        set channel [open $::env(NN_VIVADO_STATUS_FILE) w]
        puts $channel 0
        close $channel
    }
    exit 0
}
