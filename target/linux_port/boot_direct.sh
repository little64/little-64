#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR=$(dirname "$(readlink -f "$0")")
REPO_ROOT=$(readlink -f "$SCRIPT_DIR/../..")
EMULATOR_BIN="$REPO_ROOT/builddir/little-64"
EMULATOR_DEBUG_BIN="$REPO_ROOT/builddir/little-64-debug"
DEFAULT_DEFCONFIG_NAME="little64_defconfig"
DEFAULT_KERNEL_ELF="$SCRIPT_DIR/build/vmlinux"
DEFAULT_ROOTFS_IMAGE="$SCRIPT_DIR/rootfs/build/rootfs.ext2"
DEFAULT_MODE="trace"
DEFAULT_RSP_PORT="${LITTLE64_RSP_PORT:-9000}"
DEFAULT_BOOT_EVENTS_FILE="${LITTLE64_BOOT_EVENTS_FILE:-/tmp/little64_boot_events.l64t}"
DEFAULT_BOOT_LOG="${LITTLE64_BOOT_LOG:-/tmp/little64_boot.log}"

usage() {
    cat <<EOF
Usage: $0 [--mode trace|smoke|rsp] [--rootfs PATH | --no-rootfs] [--max-cycles N] [--port N] [kernel-elf]

If kernel-elf is omitted, $DEFAULT_KERNEL_ELF is used.
If --rootfs is omitted, $DEFAULT_ROOTFS_IMAGE is used.
Use --no-rootfs to boot without attaching a disk image.
If --max-cycles is omitted, emulation runs indefinitely.

Modes:
    trace  Default traced boot flow with MMIO/control-flow/boot-event capture.
    smoke  Lower-overhead direct boot without boot-event capture.
    rsp    Launch the direct-boot debug server on a TCP RSP port.

Examples:
  $0
    $0 --mode trace
    $0 --mode smoke --max-cycles 10000000
    $0 --rsp --port 9000
  $0 $DEFAULT_KERNEL_ELF
  $0 --rootfs "$DEFAULT_ROOTFS_IMAGE"
  $0 --no-rootfs
  $0 --max-cycles 10000000
  $0 $DEFAULT_KERNEL_ELF --max-cycles=10000000
EOF
}

KERNEL_ELF="$DEFAULT_KERNEL_ELF"
ROOTFS_IMAGE="${LITTLE64_ROOTFS_IMAGE:-$DEFAULT_ROOTFS_IMAGE}"
ATTACH_ROOTFS=1
MAX_CYCLES=""
MODE="$DEFAULT_MODE"
RSP_PORT="$DEFAULT_RSP_PORT"
BOOT_EVENTS_FILE="$DEFAULT_BOOT_EVENTS_FILE"
BOOT_LOG="$DEFAULT_BOOT_LOG"
POSITIONAL=()
while [[ $# -gt 0 ]]; do
    case "$1" in
        -h|--help)
            usage
            exit 0
            ;;
        --mode)
            shift
            if [[ $# -eq 0 ]]; then
                echo "error: --mode requires a value" >&2
                exit 1
            fi
            MODE="$1"
            shift
            continue
            ;;
        --mode=*)
            MODE="${1#*=}"
            shift
            continue
            ;;
        --smoke)
            MODE="smoke"
            shift
            continue
            ;;
        --rsp|--debug-server)
            MODE="rsp"
            shift
            continue
            ;;
        --rootfs)
            shift
            if [[ $# -eq 0 ]]; then
                echo "error: --rootfs requires a value" >&2
                exit 1
            fi
            ROOTFS_IMAGE="$1"
            ATTACH_ROOTFS=1
            shift
            continue
            ;;
        --rootfs=*)
            ROOTFS_IMAGE="${1#*=}"
            ATTACH_ROOTFS=1
            shift
            continue
            ;;
        --no-rootfs)
            ATTACH_ROOTFS=0
            ROOTFS_IMAGE=""
            shift
            continue
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
        --port)
            shift
            if [[ $# -eq 0 ]]; then
                echo "error: --port requires a value" >&2
                exit 1
            fi
            RSP_PORT="$1"
            shift
            continue
            ;;
        --port=*)
            RSP_PORT="${1#*=}"
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
        -* )
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

case "$MODE" in
    trace|smoke|rsp)
        ;;
    *)
        echo "error: unknown mode: $MODE" >&2
        usage >&2
        exit 1
        ;;
esac

if [[ ! "$RSP_PORT" =~ ^[0-9]+$ ]] || [[ "$RSP_PORT" -lt 1 || "$RSP_PORT" -gt 65535 ]]; then
    echo "error: port must be an integer in range 1..65535" >&2
    exit 1
fi

RUNNER_BIN="$EMULATOR_BIN"
if [[ "$MODE" == "rsp" ]]; then
    RUNNER_BIN="$EMULATOR_DEBUG_BIN"
fi

if [[ ! -x "$RUNNER_BIN" ]]; then
    echo "error: emulator binary not found at $RUNNER_BIN" >&2
    echo "hint: build it first with: meson compile -C $REPO_ROOT/builddir" >&2
    exit 1
fi

if [[ ! -f "$KERNEL_ELF" ]]; then
    echo "error: kernel ELF not found at $KERNEL_ELF" >&2
    echo "hint: build it first with: $SCRIPT_DIR/build.sh vmlinux -j1" >&2
    exit 1
fi

if [[ "$(readlink -f "$KERNEL_ELF")" == "$(readlink -f "$DEFAULT_KERNEL_ELF")" ]]; then
    ACTIVE_DEFCONFIG_STAMP="$SCRIPT_DIR/build/.little64_defconfig.name"
    if [[ -f "$ACTIVE_DEFCONFIG_STAMP" ]]; then
        ACTIVE_DEFCONFIG=$(cat "$ACTIVE_DEFCONFIG_STAMP")
        if [[ "$ACTIVE_DEFCONFIG" != "$DEFAULT_DEFCONFIG_NAME" ]]; then
            echo "error: default emulator kernel path $DEFAULT_KERNEL_ELF currently points to a $ACTIVE_DEFCONFIG build" >&2
            echo "hint: rebuild the emulator kernel with: $SCRIPT_DIR/build.sh vmlinux -j1" >&2
            echo "hint: LiteX kernels now live under target/linux_port/build-<defconfig>/ by default" >&2
            echo "hint: or pass an explicit kernel path that matches the emulator machine profile" >&2
            exit 1
        fi
    fi
fi

if [[ "$ATTACH_ROOTFS" == "1" && ! -f "$ROOTFS_IMAGE" ]]; then
    echo "error: rootfs image not found at $ROOTFS_IMAGE" >&2
    echo "hint: build it first with: $SCRIPT_DIR/rootfs/build.sh" >&2
    echo "hint: or boot without a root disk via: $0 --no-rootfs" >&2
    exit 1
fi

# Optional targeted LR trace instrumentation for return-address debugging.
# Enable with:
#   LITTLE64_TRACE_LR=1 target/linux_port/boot_direct.sh
# Optionally override the PC window:
#   LITTLE64_TRACE_LR_START=0xffffffc0000ad000 LITTLE64_TRACE_LR_END=0xffffffc0000b4700
if [[ "${LITTLE64_TRACE_LR:-0}" == "1" ]]; then
    : "${LITTLE64_TRACE_LR_START:=0xffffffc0000ad000}"
    : "${LITTLE64_TRACE_LR_END:=0xffffffc0000b4700}"
    export LITTLE64_TRACE_LR_START LITTLE64_TRACE_LR_END
    echo "[little64] lr trace enabled: pc in [${LITTLE64_TRACE_LR_START}, ${LITTLE64_TRACE_LR_END}]" >&2
fi

# Optional memory write-watch for narrow stack-slot mining.
# Enable with:
#   LITTLE64_TRACE_WATCH=1 target/linux_port/boot_direct.sh
# Optionally override watched virtual address range:
#   LITTLE64_TRACE_WATCH_START=0xffffffc0006a3f40 LITTLE64_TRACE_WATCH_END=0xffffffc0006a3f70
if [[ "${LITTLE64_TRACE_WATCH:-0}" == "1" ]]; then
    : "${LITTLE64_TRACE_WATCH_START:=0xffffffc0006a3f40}"
    : "${LITTLE64_TRACE_WATCH_END:=0xffffffc0006a3f70}"
    export LITTLE64_TRACE_WATCH_START LITTLE64_TRACE_WATCH_END
    echo "[little64] watch trace enabled: addr in [${LITTLE64_TRACE_WATCH_START}, ${LITTLE64_TRACE_WATCH_END}]" >&2
fi

# Keep output tooling readable when killed by timeout by forcing a trailing newline.
print_trailing_newline() {
    printf '\n' >&2
}

append_common_runtime_args() {
    local -n args_ref=$1
    if [[ -n "$MAX_CYCLES" ]]; then
        args_ref+=("--max-cycles=$MAX_CYCLES")
    fi
    if [[ "$ATTACH_ROOTFS" == "1" ]]; then
        args_ref+=("--disk=$ROOTFS_IMAGE" --disk-readonly)
    fi
}

echo "[little64] mode       : $MODE"
echo "[little64] kernel ELF : $KERNEL_ELF"
echo "[little64] DT source  : $REPO_ROOT/host/emulator/little64.dts"
if [[ "$ATTACH_ROOTFS" == "1" ]]; then
    echo "[little64] rootfs     : $ROOTFS_IMAGE"
else
    echo "[little64] rootfs     : disabled (--no-rootfs)"
fi
if [[ -n "$MAX_CYCLES" ]]; then
    echo "[little64] max cycles : $MAX_CYCLES"
fi

case "$MODE" in
    trace)
        trap print_trailing_newline EXIT INT TERM

        EMULATOR_ARGS=("$EMULATOR_BIN" --trace-mmio --boot-events --trace-control-flow --boot-events-file="$BOOT_EVENTS_FILE" --boot-events-max-mb="${LITTLE64_BOOT_EVENTS_MAX_MB:-500}" --boot-mode=direct)

        if [[ -n "${LITTLE64_TRACE_START_CYCLE:-}" ]]; then
            EMULATOR_ARGS+=("--trace-start-cycle=$LITTLE64_TRACE_START_CYCLE")
        fi
        if [[ -n "${LITTLE64_TRACE_END_CYCLE:-}" ]]; then
            EMULATOR_ARGS+=("--trace-end-cycle=$LITTLE64_TRACE_END_CYCLE")
        fi

        append_common_runtime_args EMULATOR_ARGS
        EMULATOR_ARGS+=("$KERNEL_ELF")
        "${EMULATOR_ARGS[@]}" 2> "$BOOT_LOG"
        status=$?
        trap - EXIT INT TERM
        printf '\n(boot event log saved to %s)\n' "$BOOT_EVENTS_FILE" >&2
        printf '(stderr log saved to %s)\n' "$BOOT_LOG" >&2
        exit "$status"
        ;;
    smoke)
        EMULATOR_ARGS=("$EMULATOR_BIN" --boot-mode=direct)
        append_common_runtime_args EMULATOR_ARGS
        EMULATOR_ARGS+=("$KERNEL_ELF")
        exec "${EMULATOR_ARGS[@]}"
        ;;
    rsp)
        trap print_trailing_newline EXIT INT TERM

        EMULATOR_ARGS=("$EMULATOR_DEBUG_BIN" --boot-mode=direct)
        append_common_runtime_args EMULATOR_ARGS
        EMULATOR_ARGS+=("$RSP_PORT" "$KERNEL_ELF")

        echo "[little64] rsp        : 127.0.0.1:$RSP_PORT"

        "${EMULATOR_ARGS[@]}"
        status=$?
        trap - EXIT INT TERM
        printf '\n' >&2
        exit "$status"
        ;;
esac
