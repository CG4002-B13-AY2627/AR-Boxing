proc nn_param {dir width name} {
    set channel [open [file join $dir "params_w${width}.hpp"]]
    set text [read $channel]
    close $channel
    set defines [regexp -all -inline -line {^\s*#define\s+(\S+)\s+(-?\d+)} $text]
    foreach {match key value} $defines {
        if {$key eq $name} { return $value }
    }
    error "params_w${width}.hpp does not define $name"
}

set part "xczu3eg-sbva484-1-i"
set period 10
set e_unroll 8
set flags "-std=c++14 -DNN_WIDTH=$width"
set project "hls_w${width}_${build}"

if {$mode ni {full synth-export}} {
    if {![file exists "$project/sol/syn/report/nn_infer_csynth.rpt"]} {
        error "no synthesized RTL in $project; run full or synth-export first"
    }
    puts "HLS: reusing $project/sol RTL. Run full or synth-export after changing the design or directives."
    open_project $project
} else {
    open_project -reset $project
}
set_top nn_infer
add_files nn_infer.cpp -cflags $flags
add_files -tb nn_tb.cpp -cflags $flags

if {$mode ni {full synth-export}} {
    open_solution "sol"
} else {
    open_solution -reset "sol" -flow_target vivado
    set_part $part
    create_clock -period $period -name default

    switch $build {
        A { }
        B { set_directive_pipeline "nn_infer/CONV1_T"
            set_directive_pipeline "nn_infer/CONV2_T" }
        C { set_directive_pipeline "nn_infer/CONV1_T"
            set_directive_pipeline "nn_infer/CONV2_T"
            set_directive_unroll "nn_infer/CONV1_I"
            set_directive_unroll "nn_infer/CONV2_I" }
        D { set_directive_pipeline "nn_infer/CONV1_T"
            set_directive_pipeline "nn_infer/CONV2_T"
            set_directive_unroll "nn_infer/CONV1_I"
            set_directive_unroll "nn_infer/CONV2_I"
            set_directive_array_partition -type cyclic -factor 4 -dim 1 "nn_infer" a1
            set_directive_array_partition -type cyclic -factor 4 -dim 1 "nn_infer" p1 }
        E { set taps [nn_param $nn_hls_dir $width CONV2_K]
            set banks [expr {$e_unroll * $taps}]
            set_directive_unroll -factor $e_unroll "nn_infer/CONV2_I"
            set_directive_pipeline "nn_infer/CONV2_I"
            set_directive_array_partition -type complete -dim 0 "nn_infer" p1
            set_directive_array_partition -type cyclic -factor $banks -dim 1 "nn_infer" conv2_w }
    }
}
