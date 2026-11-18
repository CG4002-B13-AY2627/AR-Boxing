# Project-local Vitis HLS 2022.1 workarounds: Windows wrapper replacement
# retries during instrumentation, and the optional loop profiler below.
#
# Vitis HLS 2022.1 records every iteration of CONV2_I_CONV2_TAP in a
# SystemVerilog queue. At the end of 200 inferences its loop profiler trims
# dummy timestamps with repeated queue.delete(), stalling final reporting.
# Skip only that optional iteration profiler. The DUT, AXI adapters, output
# comparison, deadlock detection, and module/top-level timing remain intact.

namespace eval nn_cosim {}

# The Windows clang-tidy used for testbench instrumentation can lose a file
# replacement race: "unable to rename temporary ... permission denied".
# HLS normally hides this diagnostic behind COSIM 212-5. Retry only that
# failed transformation; other compiler errors and RTL failures are unchanged.
proc nn_cosim::exec_with_retry {args} {
    for {set attempt 1} {$attempt <= 3} {incr attempt} {
        catch {uplevel 1 [linsert $args 0 ::nn_cosim::native_exec]} result options
        if {[lsearch -glob $args *clang-tidy*] < 0 ||
            [lsearch -glob $args *xilinx-tb-process*] < 0 ||
            [string first {unable to rename temporary} $result] < 0 ||
            [string first {permission denied} $result] < 0} {
            break
        }
        if {$attempt == 3} {
            puts stderr "HLS: testbench wrapper replacement still failed after 3 attempts:\n$result"
            break
        }
        puts "HLS: Windows denied replacement of a testbench wrapper; retrying clang-tidy ($attempt/2)."
        after [expr {250 * $attempt}]
    }
    return -options $options $result
}

proc nn_cosim::prepare_simulator {command operation} {
    if {[file tail [lindex $command end]] ne ".run_sim.tcl" ||
        [file tail [pwd]] ne "verilog"} {
        return
    }
    set path [file join [pwd] dataflow_monitor.sv]
    if {![file exists $path]} { return }
    set channel [open $path r]
    set monitor [read $channel]
    close $channel

    # Resolve the generated number from the stable C loop name, rather than
    # assuming the profiler is always upc_loop_monitor_5.
    set pattern {assign upc_loop_intf_([0-9]+)\.cur_state = [^;]*Pipeline_CONV2_I_CONV2_TAP[^;]*;}
    if {![regexp $pattern $monitor match number]} { return }
    set registration "sample_manager_inst.add_one_monitor(upc_loop_monitor_$number);"
    if {[string first $registration $monitor] < 0} {
        error "unrecognized Vitis 2022.1 loop profiler registration in $path"
    }
    file copy -force $path "$path.original"
    set monitor [string map [list $registration \
        "// CONV2 iteration profiling omitted by cosim_workaround.tcl."] $monitor]
    set channel [open $path w]
    puts -nonewline $channel $monitor
    close $channel
    puts "HLS: skipped the Vitis 2022.1 CONV2 iteration profiler; RTL output verification remains enabled."
}

proc nn_cosim::run {args} {
    if {![string match "2022.1*" [version -short]]} {
        return [uplevel 1 [linsert $args 0 cosim_design]]
    }
    # HLS regenerates the monitor on every run. Apply the workaround just
    # before its generated simulator script is sourced, without editing the
    # installed Xilinx tools or replacing HLS's normal simulation/check flow.
    trace add execution ::source enter ::nn_cosim::prepare_simulator
    set windows [expr {$::tcl_platform(platform) eq "windows"}]
    if {$windows} {
        rename ::exec ::nn_cosim::native_exec
        rename ::nn_cosim::exec_with_retry ::exec
    }
    catch {uplevel 1 [linsert $args 0 cosim_design]} result options
    if {$windows} {
        rename ::exec ::nn_cosim::exec_with_retry
        rename ::nn_cosim::native_exec ::exec
    }
    trace remove execution ::source enter ::nn_cosim::prepare_simulator
    return -options $options $result
}
