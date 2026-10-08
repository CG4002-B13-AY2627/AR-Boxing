#!/usr/bin/env bash
# transfer.sh — send one archived run's board artefacts to the Ultra96.
#
#   ./transfer.sh                  prompt for the run name
#   ./transfer.sh --name mark-2    skip the prompt
#   ./transfer.sh --name pipeline/mark-2   when two kinds share a name
#   ./transfer.sh --name mark-2 --dry-run    list what would be sent
#
# pipeline.sh archives every run into out/pipeline/<name>/, and all.sh into
# out/all/<name>/. Only the run's bitstream/
# is of any use to the board, and this sends exactly that, into a bitstream/
# subdirectory of the run on the board:
#
#   nn_w<N>_<B>.bit     the PL image
#   nn_w<N>_<B>.hwh     the hardware handoff Overlay() reads for the register
#                       map -- same basename as the .bit, side by side, which
#                       is how PYNQ finds the second from the first
#   norm_stats.json     per-channel standardisation the PS applies before
#                       every inference; without it the board feeds the
#                       accelerator raw IMU units it was never trained on
#   description_w<N>.json  class order, window, channels, accumulator width:
#                       the host's half of the interface contract
#   golden_w<N>.npz     held-out windows and the logits the model produced for
#                       them, for verify.py to replay against the accelerator.
#                       Sent when the run has one -- unlike the four above it
#                       is optional, because a run archived before golden.py
#                       emitted it has none, and loading the build does not
#                       need it
#
# Alongside them goes the PYNQ host code -- every file under ultra-96/src --
# into a src/ subdirectory of the run. The code and the build it drives travel
# together: a run directory holding a bitstream but not the host that loads it
# is not something you can pick up and run.
#
# Every file under ultra-96/scripts goes to the run root rather than into src/,
# because those are what you run on the board and src/ is what they run. So a
# run directory answers "how do I test this build?" by having verify.sh sitting
# in it, next to the bitstream it tests.
#
# ROOT_FROM_SRC names the one exception in the other direction: a file kept in
# ultra-96/src because that is where the host code is edited, but landing at
# the run root because it is a starting point for a caller to copy rather than
# part of the library a caller imports.
#
# The run lands in its own directory on the board, named for the run, so two
# runs never overwrite each other and the board can always say which build it
# is holding.
#
# Connection details are variables, not literals -- override from the
# environment when the lab reassigns a board:
#
#   U96_HOST=... U96_JUMP=... U96_ROOT=... ./transfer.sh --name mark-2
#
# Those names, and the board's password, can live in a .env beside this script
# instead. See .env.example. The environment still wins over the file, and a
# missing or wrong password only means ssh asks for it, exactly as it did
# before the file existed.

set -uo pipefail

# --- askpass mode -----------------------------------------------------------
#
# ssh re-invokes this script to ask for a password (see with_password below),
# handing it the prompt it was about to print. There is no second script for
# this: SSH_ASKPASS must name a program, and this is the program.
#
# The marker is what separates the two roles -- a transfer never sets it, and
# ssh always does. It answers the board and nothing else: the jump host's
# prompt is not ours to answer, a key passphrase is a different question, and a
# host-key confirmation is not a password at all.
if [ "${U96_ASKPASS_MODE:-}" = "1" ]; then
    case "${1-}" in
        *[Pp]assword*) ;;
        *) exit 1 ;;
    esac
    case "${1-}" in
        *"${U96_HOST:?}"*) ;;
        *) exit 1 ;;
    esac
    [ -n "${U96_HOST_PASSWORD:-}" ] || exit 1
    printf '%s\n' "$U96_HOST_PASSWORD"
    exit 0
fi

SELF="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/$(basename "${BASH_SOURCE[0]}")"
HERE="$(dirname "$SELF")"
ROOT="$(cd "$HERE/.." && pwd)"
OUT_ROOT="$ROOT/out"
SRC_DIR="$HERE/src"
SCRIPTS_DIR="$HERE/scripts"

# Kept in src/, shipped to the run root. See the note above.
ROOT_FROM_SRC="template.py"

ENV_FILE="${U96_ENV:-$HERE/.env}"

# --- .env -------------------------------------------------------------------

# Parsed, not sourced. Sourcing would execute it, which turns a password
# containing a backtick or a $ into a command, and a typo into a surprise.
# Only these four names are recognised; anything else is called out rather than
# silently ignored, because a misspelt key looks exactly like a key that did
# not work.
if [ -f "$ENV_FILE" ]; then
    while IFS= read -r line || [ -n "$line" ]; do
        line="${line%$'\r'}"                    # written on Windows, read here
        case "$line" in ''|'#'*) continue ;; esac
        case "$line" in *=*) ;; *) continue ;; esac

        key="${line%%=*}"
        val="${line#*=}"
        key="${key#"${key%%[![:space:]]*}"}"    # trim both ends of the key
        key="${key%"${key##*[![:space:]]}"}"
        val="${val%"${val##*[![:space:]]}"}"    # trailing space only: a
                                                # password may start with one
        case "$val" in                          # one surrounding pair of quotes
            \"*\"|\'*\') val="${val:1:${#val}-2}" ;;
        esac

        case "$key" in
            U96_HOST|U96_JUMP|U96_ROOT|U96_HOST_PASSWORD)
                # The environment wins: an override given at the prompt must
                # not be undone by a file.
                if [ -z "${!key:-}" ]; then
                    printf -v "$key" '%s' "$val"
                fi ;;
            *)
                echo "note: $(basename "$ENV_FILE") sets $key, which nothing reads." >&2 ;;
        esac
    done < "$ENV_FILE"
fi

HOST="${U96_HOST:-xilinx@makerslab-fpga-12.ddns.comp.nus.edu.sg}"
JUMP="${U96_JUMP:-wayne@stujump.comp.nus.edu.sg}"
REMOTE_ROOT="${U96_ROOT:-ai}"

# --- password handling ------------------------------------------------------

# OpenSSH will take a password from a helper program instead of the terminal,
# but only if told to: SSH_ASKPASS names the helper and SSH_ASKPASS_REQUIRE
# forces its use even when a terminal is available. 8.4 and later; no version
# check, because the fallback below covers an older ssh as well as it covers a
# wrong password.
AUTH="prompt"
if [ -n "${U96_HOST_PASSWORD:-}" ]; then
    AUTH="env"
    export U96_HOST U96_HOST_PASSWORD
fi

# SSH_ASKPASS_REQUIRE applies to every prompt, and we can only answer one of
# the two. So the jump is made by its own ssh, as a ProxyCommand rather than
# -o ProxyJump, with the helper stripped from its environment: that connection
# asks for the NUS password on the terminal as it always has, and only the
# board's prompt reaches the helper.
#
# Were the jump left under -o ProxyJump, its prompt would go to the helper too,
# be refused, and take the whole connection down with it.
PROXY="env -u SSH_ASKPASS -u SSH_ASKPASS_REQUIRE -u U96_ASKPASS_MODE"
PROXY="$PROXY ssh -W %h:%p $JUMP"

# Runs ssh or scp with the helper wired up, and runs it again the old way if
# that did not work. The second attempt is what makes this safe to leave
# switched on: every failure mode -- no .env, empty or stale password, an ssh
# too old for SSH_ASKPASS_REQUIRE -- lands on the prompt this script would have
# shown anyway. AUTH stays "prompt" afterwards, so the rest of the transfer
# does not re-run the same doomed attempt. Both commands are safe to repeat:
# the copy overwrites, the mkdir is -p.
with_password() {
    prog="$1"; shift

    if [ "$AUTH" = "env" ]; then
        if SSH_ASKPASS="$SELF" SSH_ASKPASS_REQUIRE=force U96_ASKPASS_MODE=1 \
           DISPLAY="${DISPLAY:-:0}" \
           "$prog" -o ProxyCommand="$PROXY" "$@"; then
            return 0
        fi
        echo >&2
        echo "note: the password in $(basename "$ENV_FILE") did not get through." >&2
        echo "      Falling back to asking for it." >&2
        AUTH="prompt"
    fi

    "$prog" -o ProxyJump="$JUMP" "$@"
}

NAME=""
DRY_RUN=0

usage() {
    echo "Usage: transfer.sh [--name <run>] [--dry-run]"
    echo
    echo "  --name     the run under out/, as <name> or <kind>/<name>;"
    echo "             prompted for if omitted"
    echo "  --dry-run  list the files and the destination, transfer nothing"
    echo
    echo "Override the connection with U96_HOST, U96_JUMP and U96_ROOT,"
    echo "in the environment or in a .env beside this script (.env.example)."
}

while [ $# -gt 0 ]; do
    case "$1" in
        --name)    NAME="${2:-}"; shift 2 ;;
        --name=*)  NAME="${1#*=}"; shift ;;
        --dry-run) DRY_RUN=1; shift ;;
        -h|--help) usage; exit 0 ;;
        *) echo "ERROR: unknown argument: $1" >&2; usage >&2; exit 1 ;;
    esac
done

# --- which run --------------------------------------------------------------

# Runs sit one level below out/, under the script that wrote them: pipeline/,
# all/ and sweep/. A run is therefore <kind>/<name>, and a bare <name> is
# resolved by looking in every kind -- which is what you want almost always.
# The qualified form is what settles it when two kinds hold the same name.
list_runs() {
    (cd "$OUT_ROOT" 2>/dev/null && ls -1td -- */*/ 2>/dev/null | sed 's:/*$::')
}

if [ ! -d "$OUT_ROOT" ]; then
    echo "ERROR: no out/ directory. Run src/pipeline.sh first." >&2
    exit 1
fi

if [ -z "$NAME" ]; then
    echo "runs available in out/:"
    # Listed newest first: the run you just built is the one you want to send.
    list_runs | sed 's/^/    /'
    echo
    printf 'which run: '
    read -r NAME
fi

# A pasted name can carry a trailing CR on Windows, which would otherwise
# become part of the path and stay invisible in every error message about it.
NAME=$(printf '%s' "$NAME" | tr -d '\r')

if [ -z "$NAME" ]; then
    echo "ERROR: no run named." >&2
    exit 1
fi

KIND=""
case "$NAME" in
    */*) KIND="${NAME%%/*}"; NAME="${NAME#*/}" ;;
esac

# Both halves become path components here, and the name becomes one on the
# board, so neither may contain anything that could leave its directory.
for part in ${KIND:+"$KIND"} "$NAME"; do
    case "$part" in
        .|..|*[!A-Za-z0-9._-]*)
            echo "ERROR: use letters, digits, dot, dash and underscore only." >&2
            exit 1 ;;
    esac
done

if [ -z "$KIND" ]; then
    MATCHES=""
    for candidate in "$OUT_ROOT"/*/"$NAME"; do
        [ -d "$candidate" ] || continue
        MATCHES="$MATCHES $(basename "$(dirname "$candidate")")"
    done

    # shellcheck disable=SC2086
    set -- $MATCHES

    if [ "$#" -eq 0 ]; then
        echo "ERROR: no run named $NAME under out/." >&2
        echo >&2
        echo "runs that do exist:" >&2
        list_runs | sed 's/^/    /' >&2
        exit 1
    fi

    if [ "$#" -gt 1 ]; then
        echo "ERROR: $# runs are named $NAME: $*." >&2
        echo "       Say which one, for instance --name $1/$NAME." >&2
        exit 1
    fi

    KIND="$1"
fi

RUN="$OUT_ROOT/$KIND/$NAME"
RUN_REL="out/$KIND/$NAME"

if [ ! -d "$RUN" ]; then
    echo "ERROR: no such run: $RUN_REL" >&2
    echo >&2
    echo "runs that do exist:" >&2
    list_runs | sed 's/^/    /' >&2
    exit 1
fi

BITSTREAM="$RUN/bitstream"

if [ ! -d "$BITSTREAM" ]; then
    echo "ERROR: $RUN_REL has no bitstream/ directory." >&2
    echo "       A run that failed before Vivado has none, and a sweep, which" >&2
    echo "       measures widths rather than producing one, never has one." >&2
    exit 1
fi

# --- find the files ---------------------------------------------------------

# Globbed, not named: the width comes from the training sweep and the build
# letter from the run, so neither is knowable here. Exactly one of each must
# match -- two .bit files means the archive is not one coherent build.
one_of() {
    what="$1"
    pattern="$2"

    # shellcheck disable=SC2086
    set -- $pattern
    if [ ! -e "$1" ]; then
        echo "ERROR: $RUN_REL/bitstream/ holds no $what." >&2
        echo "       That run failed before Vivado wrote one." >&2
        return 1
    fi
    if [ "$#" -gt 1 ]; then
        echo "ERROR: $RUN_REL/bitstream/ holds $# ${what}s, expected one." >&2
        return 1
    fi

    printf '%s' "$1"
}

BIT=$(one_of ".bit" "$BITSTREAM/*.bit") || exit 1
HWH=$(one_of ".hwh" "$BITSTREAM/*.hwh") || exit 1
DESC=$(one_of "description json" "$BITSTREAM/description_w*.json") || exit 1

# Overlay('x.bit') looks for x.hwh beside it, so a mismatch here is a failure
# that would otherwise appear on the board as a missing-metadata error.
if [ "$(basename "$BIT" .bit)" != "$(basename "$HWH" .hwh)" ]; then
    echo "ERROR: $(basename "$BIT") and $(basename "$HWH") are different builds." >&2
    echo "       PYNQ finds the .hwh by the .bit's name; they must match." >&2
    exit 1
fi

NORM="$BITSTREAM/norm_stats.json"

if [ ! -f "$NORM" ]; then
    echo "ERROR: $RUN_REL/bitstream/norm_stats.json is absent." >&2
    echo "       The PS cannot standardise input without it." >&2
    exit 1
fi

# --- host source ------------------------------------------------------------

if [ ! -d "$SRC_DIR" ]; then
    echo "ERROR: ultra-96/src is absent." >&2
    echo "       It holds the PYNQ host code the board runs." >&2
    exit 1
fi

# Whatever is in there, not a named list: the host is still being written, and
# a script naming its files would need editing every time one was added.
SRC_ITEMS=""
ROOT_ITEMS=""
for f in "$SRC_DIR"/*; do
    [ -e "$f" ] || continue          # an unmatched glob leaves the pattern behind
    # Bytecode is written by whatever Python last imported these locally, and
    # is both useless on the board and possibly built by another version of
    # Python. It reappears every time the modules are imported here, so it is
    # skipped rather than deleted.
    case "$(basename "$f")" in __pycache__|*.pyc) continue ;; esac
    case "$(basename "$f")" in
        "$ROOT_FROM_SRC") ROOT_ITEMS="$ROOT_ITEMS $f"; continue ;;
    esac
    SRC_ITEMS="$SRC_ITEMS $f"
done

# The runnable half, landing in the run root beside the build. Globbed for the
# same reason src/ is. Optional rather than required: an older checkout has no
# scripts/ and the build still loads without it.
SCRIPT_ITEMS=""
if [ -d "$SCRIPTS_DIR" ]; then
    for f in "$SCRIPTS_DIR"/*; do
        [ -e "$f" ] || continue
        SCRIPT_ITEMS="$SCRIPT_ITEMS $f"
    done
fi

if [ -z "$SCRIPT_ITEMS" ]; then
    echo "note: ultra-96/scripts is absent or empty, so the run will have no" >&2
    echo "      verify.sh. Run src/verify.py directly on the board instead." >&2
fi

FILES="$BIT $HWH $NORM $DESC"

# Optional, where the four above are required: an older archive has no .npz,
# and a power or pre-processing session on the board does not replay anything.
# One run holds one width, so the last match is the only match.
GOLDEN=""
for f in "$BITSTREAM"/golden_w*.npz; do
    [ -e "$f" ] || continue
    GOLDEN="$f"
done

if [ -n "$GOLDEN" ]; then
    FILES="$FILES $GOLDEN"
else
    echo "note: $RUN_REL/bitstream/ has no golden npz, so verify.py will have" >&2
    echo "      nothing to replay. The build itself is unaffected." >&2
fi

DEST="$REMOTE_ROOT/$NAME"

echo
echo "run       $RUN_REL"
echo "build     $(basename "$BIT" .bit)"
echo "host      $HOST"
echo "jump      $JUMP"
if [ "$AUTH" = "env" ]; then
    echo "auth      board password from $(basename "$ENV_FILE"); jump typed"
else
    echo "auth      both passwords typed"
fi
echo "dest      ~/$DEST"
echo
echo "sending:"
for f in $FILES; do
    printf '    bitstream/%-14s %s\n' "$(basename "$f")" "$(du -h "$f" | cut -f1)"
done

for f in $SCRIPT_ITEMS $ROOT_ITEMS; do
    printf '    %-24s %s\n' "$(basename "$f")" "$(du -h "$f" | cut -f1)"
done

if [ -z "$SRC_ITEMS" ]; then
    echo "    src/                     empty, nothing to copy into it"
else
    for f in $SRC_ITEMS; do
        printf '    src/%-20s %s\n' "$(basename "$f")" "$(du -sh "$f" | cut -f1)"
    done
fi

if [ "$DRY_RUN" = "1" ]; then
    echo
    echo "--dry-run: nothing sent."
    exit 0
fi

# --- send -------------------------------------------------------------------

# scp cannot create a missing remote directory and takes one target, so this is
# one ssh and one copy -- a password prompt each, unless keys are set up.
echo
echo "creating ~/$DEST"

if ! with_password ssh "$HOST" "mkdir -p '$DEST'"; then
    echo "ERROR: could not create ~/$DEST on the board." >&2
    exit 1
fi

STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT
mkdir "$STAGE/bitstream" "$STAGE/src"
# shellcheck disable=SC2086
cp $FILES "$STAGE/bitstream/"
if [ -n "$SRC_ITEMS" ]; then
    # shellcheck disable=SC2086
    cp -r $SRC_ITEMS "$STAGE/src/"
fi

echo "copying"

# shellcheck disable=SC2086
if ! with_password scp -r "$STAGE/bitstream" "$STAGE/src" $SCRIPT_ITEMS $ROOT_ITEMS "$HOST:$DEST/"; then
    echo "ERROR: transfer failed. Nothing on the board should be trusted." >&2
    exit 1
fi

echo
echo "Done. On the board:"
if [ -n "$SCRIPT_ITEMS" ]; then
    # bash rather than ./ because transfer.bat cannot send an executable bit --
    # NTFS has none -- and the instruction should not depend on which machine
    # the run was sent from.
    echo "    cd ~/$DEST && bash verify.sh"
else
    echo "    cd ~/$DEST && ls -l"
fi
