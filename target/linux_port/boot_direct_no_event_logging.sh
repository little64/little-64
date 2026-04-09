#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR=$(dirname "$(readlink -f "$0")")
REPO_ROOT=$(readlink -f "$SCRIPT_DIR/../..")
EMULATOR_BIN="$REPO_ROOT/builddir/little-64"
DEFAULT_KERNEL_ELF="$SCRIPT_DIR/build/vmlinux"

usage() {
    cat <<EOM
Usage: $0 [--max-cycles N] [kernel-elf]

If kernel-elf is omitted, $DEFAULT_KERNEL_ELF is used.
If --max-cycles is omitted, emulation runs indefinitely.

Examples:
  $0
  $0 $DEFAULT_KERNEL_ELF
  $0 --max-cycles 10000000
  $0 $DEFAULT_KERNEL_ELF --max-cycles=10000000
EOM
}

KERNEL_ELF="$DEFAULT_KERNEL_ELF"
MAX_CYCLES=""
POSITIONAL=()
while [[ $# -gt 0 ]]; do
    case "$1" in
        -h|--help)
            usage
            exit 0
            ;;
        --max-cycles)
            shift
            if [[ $# -eq 0 ]]; then
                echo "error: --max-cycles requires a value" >&2
                exit 1
            fi
            MAX_CYCLES="$1"
            shift
            continue
            ;;
        --max-cycles=*)
            MAX_CYCLES="${1#*=}"
            shift
            continue
            ;;
        --)
            shift
            while [[ $# -gt 0 ]]; do
                POSITIONAL+=("$1")
                shift
            done
            break
            ;;
        -*)
            echo "error: unknown option: $1" >&2
            exit 1
            ;;
        *)
            POSITIONAL+=("$1")
            ;;
    esac
    shift
done

if [[ ${#POSITIONAL[@]} -gt 2 ]]; then
    echo "error: too many positional arguments" >&2
    usage
    exit 1
fi

if [[ ${#POSITIONAL[@]} -eq 2 ]]; then
    KERNEL_ELF="${POSITIONAL[0]}"
    MAX_CYCLES="${POSITIONAL[1]}"
elif [[ ${#POSITIONAL[@]} -eq 1 ]]; then
    if [[ -z "$MAX_CYCLES" && "${POSITIONAL[0]}" =~ ^[0-9]+$ ]]; then
        MAX_CYCLES="${POSITIONAL[0]}"
    else
        KERNEL_ELF="${POSITIONAL[0]}"
    fi
fi

if [[ -n "$MAX_CYCLES" && ! "$MAX_CYCLES" =~ ^[0-9]+$ ]]; then
    echo "error: max cycles must be a positive integer" >&2
    exit 1
fi

if [[ ! -x "$EMULATOR_BIN" ]]; then
    echo "error: emulator binary not found at $EMULATOR_BIN" >&2
    echo "hint: build it first with: meson compile -C $REPO_ROOT/builddir" >&2
    exit 1
fi

if [[ ! -f "$KERNEL_ELF" ]]; then
    echo "error: kernel ELF not found at $KERNEL_ELF" >&2
    echo "hint: build it first with: $SCRIPT_DIR/build.sh vmlinux -j1" >&2
    exit 1
fi

if [[ "${LITTLE64_TRACE_LR:-0}" == "1" ]]; then
    : "${LITTLE64_TRACE_LR_START:=0xffffffc0000ad000}"
    : "${LITTLE64_TRACE_LR_END:=0xffffffc0000b4700}"
    export LITTLE64_TRACE_LR_START LITTLE64_TRACE_LR_END
fi

if [[ "${LITTLE64_TRACE_WATCH:-0}" == "1" ]]; then
    : "${LITTLE64_TRACE_WATCH_START:=0xffffffc0006a3f40}"
    : "${LITTLE64_TRACE_WATCH_END:=0xffffffc0006a3f70}"
    export LITTLE64_TRACE_WATCH_START LITTLE64_TRACE_WATCH_END
fi

EMULATOR_ARGS=("$EMULATOR_BIN" --boot-mode=direct)
if [[ -n "$MAX_CYCLES" ]]; then
    EMULATOR_ARGS+=("--max-cycles=$MAX_CYCLES")
fi
EMULATOR_ARGS+=("$KERNEL_ELF")

exec "${EMULATOR_ARGS[@]}"
