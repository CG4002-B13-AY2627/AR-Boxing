#!/usr/bin/env bash
# Check the export against Brevitas, both halves of it. macOS and Linux.
#
#   ./check.sh              set up if needed, then check
#   ./check.sh --reinstall  reinstall the dependencies first, then check
#
# On the first run this creates the virtual environment in src/.venv and
# installs the requirements into it. On later runs it does neither, unless the
# requirements file has changed since the last install. Any other argument is
# passed straight through to check.py, so
#
#   ./check.sh --rounding trunc
#   ./check.sh --vectors 20
#
# reach the checker unchanged. The rounding modes are in export/check_config.py.
#
# check.py runs two checks over one Brevitas pass: the exported description
# executed as integers, and ultra-96/src/preprocess.py against the quantizer at
# the PS/PL boundary. It exits non-zero if either fails.
#
# The environment is src/.venv, shared with train.sh and export.sh rather than a
# third copy of torch: check.py imports train/config.py and train/qacnn.py to
# rebuild the module the checkpoint was saved from, and needs torch itself to
# produce the Brevitas side of the comparison. The setup below is byte-for-byte
# the one in export.sh, down to the stamp file, so whichever of the three
# scripts runs first does the install and the others find the work already done.
#
# The virtual environment is never "activated": we call its interpreter by path
# instead, which has the same effect and cannot leak into the calling shell.

set -euo pipefail

SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
EXPORT_DIR="$SRC_DIR/export"
TRAIN_DIR="$SRC_DIR/train"
VENV_DIR="$SRC_DIR/.venv"
PYTHON="$VENV_DIR/bin/python"
STAMP="$VENV_DIR/.requirements.sha256"

# Pinned, not "whatever python3 happens to be". torch stopped shipping
# Intel-Mac wheels after 2.2.2, and 2.2.2's last supported interpreter is
# cp312, so requirements-macos.txt only resolves under Python 3.12.
REQUIRED_PYTHON="3.12"

case "$(uname -s)" in
    Darwin) REQUIREMENTS="$TRAIN_DIR/requirements-macos.txt" ;;
    *)      REQUIREMENTS="$TRAIN_DIR/requirements.txt" ;;
esac

REINSTALL=0
if [ "${1:-}" = "--reinstall" ]; then
    REINSTALL=1
    shift
fi

# Homebrew installs to /usr/local on Intel and /opt/homebrew on Apple Silicon,
# and neither is guaranteed to be on PATH when this runs from an IDE.
find_interpreter() {
    local candidate
    for candidate in \
        "python${REQUIRED_PYTHON}" \
        "/opt/homebrew/bin/python${REQUIRED_PYTHON}" \
        "/usr/local/bin/python${REQUIRED_PYTHON}"
    do
        if command -v "$candidate" >/dev/null 2>&1; then
            command -v "$candidate"
            return 0
        fi
    done

    return 1
}

hash_requirements() {
    if command -v shasum >/dev/null 2>&1; then
        shasum -a 256 "$REQUIREMENTS" | awk '{print $1}'
    else
        sha256sum "$REQUIREMENTS" | awk '{print $1}'
    fi
}

if [ ! -f "$REQUIREMENTS" ]; then
    echo "ERROR: $REQUIREMENTS does not exist." >&2
    exit 1
fi

if [ ! -x "$PYTHON" ]; then
    if ! interpreter="$(find_interpreter)"; then
        echo "ERROR: python${REQUIRED_PYTHON} was not found." >&2
        echo "       Install it with:  brew install python@${REQUIRED_PYTHON}" >&2
        exit 1
    fi

    echo "Creating the virtual environment in $VENV_DIR"
    echo "  using $interpreter"
    "$interpreter" -m venv "$VENV_DIR"
    "$PYTHON" -m pip install --upgrade pip --quiet

    # Nothing is installed in a venv that was just created.
    REINSTALL=1
fi

# Reinstall when the requirements file has changed, so that editing a pin takes
# effect on the next run rather than silently doing nothing.
current_hash="$(hash_requirements)"
stored_hash=""
if [ -f "$STAMP" ]; then
    stored_hash="$(cat "$STAMP")"
fi

if [ "$REINSTALL" -eq 1 ] || [ "$current_hash" != "$stored_hash" ]; then
    echo "Installing $(basename "$REQUIREMENTS")"
    "$PYTHON" -m pip install -r "$REQUIREMENTS"
    printf '%s\n' "$current_hash" > "$STAMP"
fi

# export_config.py resolves its paths from __file__, so this is not strictly
# needed; it is here so that anything the run writes relative to the working
# directory lands next to the code rather than wherever the script was called
# from.
cd "$EXPORT_DIR"

echo "Running check.py"
exec "$PYTHON" check.py "$@"
