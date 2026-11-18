if {![string match "2022.1*" [version -short]]} {
    error "This flow is validated with Vitis HLS 2022.1; found [version -short]."
}

proc nn_hls_finish {} {
    if {[info exists ::env(NN_HLS_STATUS_FILE)]} {
        set channel [open $::env(NN_HLS_STATUS_FILE) w]
        puts $channel 0
        close $channel
    }
    exit 0
}

set args $argv
if {[lindex $args 0] eq "-f"} { set args [lrange $args 2 end] }
if {[lindex $args 0] eq "-tclargs"} { set args [lrange $args 1 end] }

set width [lindex $args 0]
set build [lindex $args 1]
set cosim_count [lindex $args 2]
set mode [lindex $args 3]

set nn_tcl_dir [file dirname [file normalize [info script]]]
set nn_hls_dir [file normalize [file join $nn_tcl_dir ..]]

source [file join $nn_tcl_dir nn_width.tcl]
if {$width eq ""} { set width [nn_width::selected $nn_hls_dir] }
if {$build eq ""} { set build A }
set build [string toupper $build]
if {![string is integer -strict $width] || $width < 1 || $build ni {A B C D E}} {
    error "expected a positive width and build A, B, C, D or E"
}
if {$mode eq ""} { set mode full }
if {$mode ni {full synth-export cosim-only cosim-export}} {
    error "mode must be full, synth-export, cosim-only, or cosim-export"
}

set cosim_args "cosim"
if {$cosim_count ne ""} {
    if {![string is integer -strict $cosim_count] || $cosim_count < 1} {
        error "co-simulation vector count must be a positive integer"
    }
    append cosim_args " $cosim_count"
}

source [file join $nn_tcl_dir configure.tcl]

if {$mode in {full synth-export}} {
    if {$mode eq "full"} {
        source [file join $nn_tcl_dir csim.tcl]
    }
    source [file join $nn_tcl_dir csynth.tcl]

    if {$mode eq "full" && $::tcl_platform(platform) eq "windows" &&
        [string match "2022.1*" [version -short]]} {
        close_project
        puts "HLS: starting a fresh process for C/RTL co-simulation and IP export (Windows/Vitis 2022.1 workaround)."
        exec [info nameofexecutable] -f [file normalize [info script]] \
            -tclargs $width $build $cosim_count cosim-export >@stdout 2>@stderr
        nn_hls_finish
    }
}

if {$mode ne "synth-export"} {
    source [file join $nn_tcl_dir cosim.tcl]
}
if {$mode ne "cosim-only"} {
    source [file join $nn_tcl_dir export_ip.tcl]
}

nn_hls_finish
