#!/usr/bin/env bash
# Run the FPGA Vivado flow. Linux, with Vivado installed.
#
#   ./vivado.sh                      implement width 6, build A
#   ./vivado.sh 5 C                  implement width 5, build C
#   ./vivado.sh 6 A bd               block design only, validated and saved
#
# Runs fpga/vivado/tcl/install_board.tcl, then fpga/vivado/tcl/block_design.tcl. The
# first is idempotent: it installs the Avnet board part only when it is
# missing, so a fresh machine works unattended and a configured one pays a
# catalog query.
#
# Arguments are passed to block_design.tcl. With no arguments, its defaults
# apply: width 6, build A, full flow through write_bitstream. bd as the third
# argument stops after validate_bd_design.
#
# Each phase uses a fresh process and scratch directory. Logs and journals
# go to NN_VIVADO_LOG_DIR, or fpga/vivado/logs for standalone runs.
#
# Set VIVADO to the full executable path to override tool discovery.

set -euo pipefail

if [ "${1:-}" = "--help" ]; then
    echo "Usage: vivado.sh [width [build [bd]]]"
    echo "Defaults: width 6, build A, full flow through write_bitstream."
    echo "  bd   stop after validate_bd_design"
    echo "Set VIVADO to the full Vivado executable path if needed."
    exit 0
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC_DIR="$(dirname "$SCRIPT_DIR")"
VIVADO_DIR="$SRC_DIR/fpga/vivado"

find_vivado() {
    local candidate
    if [ -n "${VIVADO:-}" ]; then
        command -v "$VIVADO"
        return
    fi

    # Also find the project's Vivado version outside a configured tool shell.
    for candidate in \
        vivado \
        "${XILINX_VIVADO:-/nonexistent}/bin/vivado" \
        /tools/Xilinx/Vivado/2022.1/bin/vivado \
        /opt/Xilinx/Vivado/2022.1/bin/vivado
    do
        if command -v "$candidate" >/dev/null 2>&1; then
            command -v "$candidate"
            return 0
        fi
    done
    return 1
}

if ! VIVADO_TOOL="$(find_vivado)"; then
    echo "ERROR: Vivado was not found." >&2
    echo "       Source its settings64.sh or set VIVADO to its full executable path." >&2
    exit 1
fi

for script in install_board.tcl block_design.tcl; do
    if [ ! -f "$VIVADO_DIR/tcl/$script" ]; then
        echo "ERROR: $VIVADO_DIR/tcl/$script does not exist." >&2
        exit 1
    fi
done

exec bash "$SCRIPT_DIR/build_support.sh" vivado --tool "$VIVADO_TOOL" "$@"
