#!/usr/bin/env bash
# Run the FPGA HLS flow. Linux, with Vitis HLS installed.
#
#   ./hls.sh                         full build, selected width, build A
#   ./hls.sh 5 C                     full build, width 5, build C
#   ./hls.sh 6 A 2                   full build with two RTL test vectors
#   ./hls.sh 6 A 2 cosim-only        reuse existing synthesized RTL
#   ./hls.sh 6 A '' synth-export     synthesize and package IP without simulations
#
# Arguments are passed to fpga/hls/tcl/run_hls.tcl. With no arguments, its
# defaults apply. A full build runs C simulation, synthesis, RTL
# co-simulation, and IP export. cosim-only requires an existing synthesis.
# Set VITIS_HLS to the full executable path to override tool discovery.

set -euo pipefail

if [ "${1:-}" = "--help" ]; then
    echo "Usage: hls.sh [width [build [cosim_count [full|synth-export|cosim-only|cosim-export]]]]"
    echo "Defaults: selected width, build A, testbench default vector count, full flow."
    echo "Example: ./hls.sh 6 A 2 cosim-only"
    echo "Set VITIS_HLS to the full Vitis HLS executable path if needed."
    exit 0
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC_DIR="$(dirname "$SCRIPT_DIR")"
if [ -z "${NN_BUILD_GUARD:-}" ]; then
    exec bash "$SCRIPT_DIR/build_support.sh" guard "$SCRIPT_DIR/hls.sh" "$@"
fi
HLS_DIR="$SRC_DIR/fpga/hls"
bash "$SCRIPT_DIR/build_support.sh" preflight

find_hls() {
    local candidate
    if [ -n "${VITIS_HLS:-}" ]; then
        command -v "$VITIS_HLS"
        return
    fi

    # Also find the project's Vitis version outside a configured tool shell.
    for candidate in \
        vitis_hls \
        "${XILINX_HLS:-/nonexistent}/bin/vitis_hls" \
        /tools/Xilinx/Vitis_HLS/2022.1/bin/vitis_hls \
        /opt/Xilinx/Vitis_HLS/2022.1/bin/vitis_hls
    do
        if command -v "$candidate" >/dev/null 2>&1; then
            command -v "$candidate"
            return 0
        fi
    done
    return 1
}

if ! HLS_TOOL="$(find_hls)"; then
    echo "ERROR: Vitis HLS was not found." >&2
    echo "       Source its settings64.sh or set VITIS_HLS to its full executable path." >&2
    exit 1
fi

if [ ! -f "$HLS_DIR/tcl/run_hls.tcl" ]; then
    echo "ERROR: $HLS_DIR/tcl/run_hls.tcl does not exist." >&2
    exit 1
fi

# The Tcl script resolves sources and generated projects from this directory.
cd "$HLS_DIR"
echo "Running tcl/run_hls.tcl"
NN_HLS_STATUS_FILE=$(mktemp)
export NN_HLS_STATUS_FILE
trap 'rm -f -- "$NN_HLS_STATUS_FILE"' EXIT
HLS_EXIT_CODE=0
if [ "$#" -eq 0 ]; then
    "$HLS_TOOL" -f tcl/run_hls.tcl || HLS_EXIT_CODE=$?
else
    "$HLS_TOOL" -f tcl/run_hls.tcl -tclargs "$@" || HLS_EXIT_CODE=$?
fi
if ! grep -qx '0' "$NN_HLS_STATUS_FILE"; then
    echo 'ERROR: HLS did not complete the requested flow.' >&2
    [ "$HLS_EXIT_CODE" -ne 0 ] || HLS_EXIT_CODE=1
fi
exit "$HLS_EXIT_CODE"
