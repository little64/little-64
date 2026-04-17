#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR=$(dirname "$(readlink -f "$0")")
REPO_ROOT=$(readlink -f "$SCRIPT_DIR/../..")
EMULATOR_BIN="$REPO_ROOT/builddir/little-64"
EMULATOR_DEBUG_BIN="$REPO_ROOT/builddir/little-64-debug"
PROFILE_PATHS_PY="$SCRIPT_DIR/profile_paths.py"
DEFAULT_VIRT_DEFCONFIG_NAME="little64_defconfig"
DEFAULT_LITEX_DEFCONFIG_NAME="little64_litex_sim_defconfig"
DEFAULT_ROOTFS_IMAGE="$SCRIPT_DIR/rootfs/build/rootfs.ext4"
DEFAULT_LITEX_OUTPUT_DIR="${LITTLE64_LITEX_OUTPUT_DIR:-$REPO_ROOT/builddir/boot-direct-litex}"
LITEX_DTS_GENERATOR="$REPO_ROOT/hdl/tools/generate_litex_linux_dts.py"
LITEX_SD_ARTIFACT_BUILDER="$REPO_ROOT/target/linux_port/build_sd_boot_artifacts.py"
DEFAULT_MODE="smoke"
DEFAULT_MACHINE="litex"
DEFAULT_RSP_PORT="${LITTLE64_RSP_PORT:-9000}"
DEFAULT_BOOT_EVENTS_FILE="${LITTLE64_BOOT_EVENTS_FILE:-/tmp/little64_boot_events.l64t}"
DEFAULT_BOOT_LOG="${LITTLE64_BOOT_LOG:-/tmp/little64_boot.log}"
PYTHON_BIN="${LITTLE64_PYTHON:-$REPO_ROOT/.venv/bin/python}"

if [[ ! -x "$PYTHON_BIN" ]]; then
    PYTHON_BIN=$(command -v python3 || true)
fi

usage() {
    cat <<EOF
Usage: $0 [--machine virt|litex] [--mode trace|smoke|rsp] [--rootfs PATH | --no-rootfs] [--max-cycles N] [--port N] [kernel-elf]

If kernel-elf is omitted, the selected machine profile's default kernel is used.
If --rootfs is omitted, $DEFAULT_ROOTFS_IMAGE is used for the virt profile.
The litex profile synthesizes a LiteX DTB, SDRAM-enabled bootrom stage-0 image, and SD card image before launch.
By default the litex profile also regenerates a minimal ext4 rootfs from target/linux_port/rootfs/init.S for SD partition 2.
Use --rootfs PATH to override that generated ext4 image, or --no-rootfs to leave the LiteX SD rootfs partition empty.
If --max-cycles is omitted, emulation runs indefinitely.

Machine profiles:
    virt   Emulator-oriented machine with ns16550 UART and PV block root disk.
    litex  Default machine profile: LiteX-compatible stage-0 plus LiteSDCard boot.

Modes:
    trace  Direct boot with MMIO/control-flow/boot-event capture.
    smoke  Default lower-overhead direct boot without boot-event capture.
    rsp    Launch the direct-boot debug server on a TCP RSP port.

Examples:
  $0
    $0 --mode trace
    $0 --mode smoke --max-cycles 10000000
    $0 --rsp --port 9000
      $0 --machine litex
      $0 --machine litex --mode smoke --max-cycles 10000000
    $0 path/to/kernel.elf
  $0 --rootfs "$DEFAULT_ROOTFS_IMAGE"
  $0 --no-rootfs
  $0 --max-cycles 10000000
    $0 path/to/kernel.elf --max-cycles=10000000
EOF
}

    default_defconfig_for_machine() {
        case "$1" in
            virt)
                printf '%s\n' "$DEFAULT_VIRT_DEFCONFIG_NAME"
                ;;
            litex)
                printf '%s\n' "$DEFAULT_LITEX_DEFCONFIG_NAME"
                ;;
            *)
                return 1
                ;;
        esac
    }

    default_kernel_path_for_machine() {
        local machine=$1
        local defconfig
        defconfig=$(default_defconfig_for_machine "$machine") || return 1
        "$PYTHON_BIN" "$PROFILE_PATHS_PY" kernel --defconfig "$defconfig"
    }

    recorded_defconfig_for_machine() {
        local machine=$1
        local defconfig
        defconfig=$(default_defconfig_for_machine "$machine") || return 1
        "$PYTHON_BIN" "$PROFILE_PATHS_PY" built-defconfig --defconfig "$defconfig" 2>/dev/null || true
    }

    kernel_config_path_for_image() {
        local kernel_path=$1
        local kernel_dir
        kernel_dir=$(dirname "$(readlink -f "$kernel_path")")
        if [[ -f "$kernel_dir/.config" ]]; then
            printf '%s\n' "$kernel_dir/.config"
            return 0
        fi
        return 1
    }

    require_kernel_config_option() {
        local config_path=$1
        local config_name=$2
        local expected_value=$3
        if ! grep -qx "${config_name}=${expected_value}" "$config_path"; then
            echo "error: kernel config $config_path is missing ${config_name}=${expected_value}" >&2
            return 1
        fi
    }

    ensure_litex_kernel_support() {
        local kernel_path=$1
        local config_path

        if [[ "${LITTLE64_SKIP_LITEX_KERNEL_CONFIG_CHECK:-0}" == "1" ]]; then
            return 0
        fi

        config_path=$(kernel_config_path_for_image "$kernel_path") || {
            echo "error: unable to verify LiteX kernel support for $kernel_path" >&2
            echo "hint: provide a kernel built in a Little64 Linux build directory so the adjacent .config is available" >&2
            echo "hint: or set LITTLE64_SKIP_LITEX_KERNEL_CONFIG_CHECK=1 to bypass this verification explicitly" >&2
            exit 1
        }

        require_kernel_config_option "$config_path" CONFIG_MMC y || exit 1
        require_kernel_config_option "$config_path" CONFIG_MMC_BLOCK y || exit 1
        require_kernel_config_option "$config_path" CONFIG_MMC_LITEX y || exit 1
        require_kernel_config_option "$config_path" CONFIG_FAT_FS y || exit 1
        require_kernel_config_option "$config_path" CONFIG_MSDOS_FS y || exit 1
        require_kernel_config_option "$config_path" CONFIG_VFAT_FS y || exit 1
        require_kernel_config_option "$config_path" CONFIG_MSDOS_PARTITION y || exit 1
        require_kernel_config_option "$config_path" CONFIG_EXT4_FS y || exit 1
        require_kernel_config_option "$config_path" CONFIG_LITTLE64_KERNEL_PHYS_BASE 0x40000000 || {
            echo "hint: rebuild the LiteX kernel so the early boot code matches the SDRAM-backed bootrom layout" >&2
            echo "hint: run target/linux_port/build.sh --machine litex clean && target/linux_port/build.sh --machine litex vmlinux -j1" >&2
            exit 1
        }
    }

    ensure_litex_python_env() {
        if [[ -z "$PYTHON_BIN" || ! -x "$PYTHON_BIN" ]]; then
            echo "error: Python interpreter not found for LiteX artifact generation" >&2
            echo "hint: set LITTLE64_PYTHON or create $REPO_ROOT/.venv" >&2
            exit 1
        fi
        if ! "$PYTHON_BIN" -c 'import litex' >/dev/null 2>&1; then
            echo "error: selected Python environment does not provide the LiteX package" >&2
            echo "hint: activate the repo virtualenv or set LITTLE64_PYTHON to an environment with LiteX installed" >&2
            exit 1
        fi
    }

    prepare_litex_artifacts() {
        local kernel_elf=$1
        local output_dir="$DEFAULT_LITEX_OUTPUT_DIR"
        local cpu_variant="${LITTLE64_LITEX_CPU_VARIANT:-standard}"
        local litex_target="${LITTLE64_LITEX_TARGET:-arty-a7-35}"
        local ram_size="${LITTLE64_LITEX_RAM_SIZE:-}"

        ensure_litex_python_env

        if [[ ! -f "$LITEX_DTS_GENERATOR" ]]; then
            echo "error: LiteX DTS generator not found at $LITEX_DTS_GENERATOR" >&2
            exit 1
        fi
        if [[ ! -f "$LITEX_SD_ARTIFACT_BUILDER" ]]; then
            echo "error: LiteX SD boot artifact builder not found at $LITEX_SD_ARTIFACT_BUILDER" >&2
            exit 1
        fi
        if ! command -v dtc >/dev/null 2>&1; then
            echo "error: dtc is required for the LiteX machine profile" >&2
            exit 1
        fi

        mkdir -p "$output_dir"

        LITEX_DTS_PATH="$output_dir/little64-litex-sim.dts"
        LITEX_DTB_PATH="$output_dir/little64-litex-sim.dtb"
        LITEX_BOOTROM_IMAGE_PATH="$output_dir/little64-sd-stage0-bootrom.bin"
        LITEX_SD_IMAGE_PATH="$output_dir/little64-linux-sdcard.img"

        local dts_args=(
            --output "$LITEX_DTS_PATH"
            --with-spi-flash
            --with-sdcard
            --with-sdram
            --litex-target "$litex_target"
            --boot-source bootrom
            --cpu-variant "$cpu_variant"
        )
        if [[ -n "$ram_size" ]]; then
            dts_args+=(--ram-size "$ram_size")
        fi

        "$PYTHON_BIN" "$LITEX_DTS_GENERATOR" "${dts_args[@]}" >/dev/null

        if [[ ! -f "$LITEX_DTB_PATH" || "$LITEX_DTB_PATH" -ot "$LITEX_DTS_PATH" ]]; then
            dtc -I dts -O dtb -o "$LITEX_DTB_PATH" "$LITEX_DTS_PATH"
        fi

        local builder_args=(
            --kernel-elf "$kernel_elf"
            --dtb "$LITEX_DTB_PATH"
            --bootrom-output "$LITEX_BOOTROM_IMAGE_PATH"
            --sd-output "$LITEX_SD_IMAGE_PATH"
            --litex-target "$litex_target"
            --boot-source bootrom
            --with-sdram
        )
        if [[ -n "$ram_size" ]]; then
            builder_args+=(--ram-size "$ram_size")
        fi
        if [[ "$ATTACH_ROOTFS" == "0" ]]; then
            builder_args+=(--no-rootfs)
        elif [[ -n "$ROOTFS_IMAGE" ]]; then
            builder_args+=(--rootfs-image "$ROOTFS_IMAGE")
        fi

        "$PYTHON_BIN" "$LITEX_SD_ARTIFACT_BUILDER" \
            "${builder_args[@]}"
    }

    KERNEL_ELF=""
ROOTFS_IMAGE="${LITTLE64_ROOTFS_IMAGE:-$DEFAULT_ROOTFS_IMAGE}"
ATTACH_ROOTFS=1
    ROOTFS_OPTION_SET=0
MAX_CYCLES=""
MODE="$DEFAULT_MODE"
    MACHINE="$DEFAULT_MACHINE"
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
        --machine)
            shift
            if [[ $# -eq 0 ]]; then
                echo "error: --machine requires a value" >&2
                exit 1
            fi
            MACHINE="$1"
            shift
            continue
            ;;
        --machine=*)
            MACHINE="${1#*=}"
            shift
            continue
            ;;
        --litex)
            MACHINE="litex"
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
            ROOTFS_OPTION_SET=1
            shift
            continue
            ;;
        --rootfs=*)
            ROOTFS_IMAGE="${1#*=}"
            ATTACH_ROOTFS=1
            ROOTFS_OPTION_SET=1
            shift
            continue
            ;;
        --no-rootfs)
            ATTACH_ROOTFS=0
            ROOTFS_IMAGE=""
            ROOTFS_OPTION_SET=1
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

case "$MACHINE" in
    virt|litex)
        ;;
    *)
        echo "error: unknown machine: $MACHINE" >&2
        usage >&2
        exit 1
        ;;
esac

if [[ -z "$KERNEL_ELF" ]]; then
    KERNEL_ELF=$(default_kernel_path_for_machine "$MACHINE")
fi

if [[ "$MACHINE" == "litex" && "$ROOTFS_OPTION_SET" == "0" ]]; then
    if [[ -n "${LITTLE64_ROOTFS_IMAGE:-}" ]]; then
        ROOTFS_IMAGE="$LITTLE64_ROOTFS_IMAGE"
        ATTACH_ROOTFS=1
    else
        ROOTFS_IMAGE=""
        ATTACH_ROOTFS=1
    fi
fi

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
    if [[ "$MACHINE" == "litex" ]]; then
        echo "hint: build it first with: $SCRIPT_DIR/build.sh --machine litex vmlinux -j1" >&2
    else
        echo "hint: build it first with: $SCRIPT_DIR/build.sh --machine virt vmlinux -j1" >&2
    fi
    exit 1
fi


if [[ "$MACHINE" == "litex" ]]; then
    ensure_litex_kernel_support "$KERNEL_ELF"
fi
DEFAULT_KERNEL_ELF=$(default_kernel_path_for_machine "$MACHINE")
if [[ "$(readlink -f "$KERNEL_ELF")" == "$(readlink -f "$DEFAULT_KERNEL_ELF")" ]]; then
    ACTIVE_DEFCONFIG=$(recorded_defconfig_for_machine "$MACHINE")
    EXPECTED_DEFCONFIG=$(default_defconfig_for_machine "$MACHINE")
    if [[ -n "$ACTIVE_DEFCONFIG" && "$ACTIVE_DEFCONFIG" != "$EXPECTED_DEFCONFIG" ]]; then
        echo "error: default kernel path $DEFAULT_KERNEL_ELF currently points to a $ACTIVE_DEFCONFIG build" >&2
        if [[ "$MACHINE" == "litex" ]]; then
            echo "hint: rebuild the LiteX kernel with: $SCRIPT_DIR/build.sh --machine litex vmlinux -j1" >&2
        else
            echo "hint: rebuild the emulator kernel with: $SCRIPT_DIR/build.sh --machine virt vmlinux -j1" >&2
        fi
        echo "hint: LiteX kernels now live under target/linux_port/build-litex/ by default" >&2
        echo "hint: or pass an explicit kernel path that matches the selected machine profile" >&2
        exit 1
    fi
fi

if [[ "$ATTACH_ROOTFS" == "1" && -n "$ROOTFS_IMAGE" && ! -f "$ROOTFS_IMAGE" ]]; then
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
    if [[ "$MACHINE" == "litex" ]]; then
        args_ref+=("--disk=$LITEX_SD_IMAGE_PATH" --disk-readonly)
    elif [[ "$ATTACH_ROOTFS" == "1" ]]; then
        args_ref+=("--disk=$ROOTFS_IMAGE" --disk-readonly)
    fi
}

if [[ "$MACHINE" == "litex" ]]; then
    prepare_litex_artifacts "$KERNEL_ELF"
fi

echo "[little64] machine    : $MACHINE"
echo "[little64] mode       : $MODE"
echo "[little64] kernel ELF : $KERNEL_ELF"
if [[ "$MACHINE" == "litex" ]]; then
    echo "[little64] DT source  : $LITEX_DTS_PATH"
    echo "[little64] stage0     : $LITEX_BOOTROM_IMAGE_PATH"
    echo "[little64] sd image   : $LITEX_SD_IMAGE_PATH"
else
    echo "[little64] DT source  : $REPO_ROOT/host/emulator/little64.dts"
fi
if [[ "$ATTACH_ROOTFS" == "1" ]]; then
    if [[ -n "$ROOTFS_IMAGE" ]]; then
        echo "[little64] rootfs     : $ROOTFS_IMAGE"
    elif [[ "$MACHINE" == "litex" ]]; then
        echo "[little64] rootfs     : auto-generated ext4 from target/linux_port/rootfs/init.S"
    else
        echo "[little64] rootfs     : enabled"
    fi
else
    echo "[little64] rootfs     : disabled (--no-rootfs)"
fi
if [[ -n "$MAX_CYCLES" ]]; then
    echo "[little64] max cycles : $MAX_CYCLES"
fi

case "$MODE" in
    trace)
        trap print_trailing_newline EXIT INT TERM

        EMULATOR_ARGS=("$EMULATOR_BIN" --trace-mmio --boot-events --trace-control-flow --boot-events-file="$BOOT_EVENTS_FILE" --boot-events-max-mb="${LITTLE64_BOOT_EVENTS_MAX_MB:-500}")
        if [[ "$MACHINE" == "litex" ]]; then
            EMULATOR_ARGS+=(--boot-mode=litex-bootrom)
        else
            EMULATOR_ARGS+=(--boot-mode=direct)
        fi

        if [[ -n "${LITTLE64_TRACE_START_CYCLE:-}" ]]; then
            EMULATOR_ARGS+=("--trace-start-cycle=$LITTLE64_TRACE_START_CYCLE")
        fi
        if [[ -n "${LITTLE64_TRACE_END_CYCLE:-}" ]]; then
            EMULATOR_ARGS+=("--trace-end-cycle=$LITTLE64_TRACE_END_CYCLE")
        fi

        append_common_runtime_args EMULATOR_ARGS
        if [[ "$MACHINE" == "litex" ]]; then
            EMULATOR_ARGS+=("$LITEX_BOOTROM_IMAGE_PATH")
        else
            EMULATOR_ARGS+=("$KERNEL_ELF")
        fi
        "${EMULATOR_ARGS[@]}" 2> "$BOOT_LOG"
        status=$?
        trap - EXIT INT TERM
        printf '\n(boot event log saved to %s)\n' "$BOOT_EVENTS_FILE" >&2
        printf '(stderr log saved to %s)\n' "$BOOT_LOG" >&2
        exit "$status"
        ;;
    smoke)
        EMULATOR_ARGS=("$EMULATOR_BIN")
        if [[ "$MACHINE" == "litex" ]]; then
            EMULATOR_ARGS+=(--boot-mode=litex-bootrom)
        else
            EMULATOR_ARGS+=(--boot-mode=direct)
        fi
        append_common_runtime_args EMULATOR_ARGS
        if [[ "$MACHINE" == "litex" ]]; then
            EMULATOR_ARGS+=("$LITEX_BOOTROM_IMAGE_PATH")
        else
            EMULATOR_ARGS+=("$KERNEL_ELF")
        fi
        exec "${EMULATOR_ARGS[@]}"
        ;;
    rsp)
        trap print_trailing_newline EXIT INT TERM

        EMULATOR_ARGS=("$EMULATOR_DEBUG_BIN")
        if [[ "$MACHINE" == "litex" ]]; then
            EMULATOR_ARGS+=(--boot-mode=litex-bootrom)
        else
            EMULATOR_ARGS+=(--boot-mode=direct)
        fi
        append_common_runtime_args EMULATOR_ARGS
        if [[ "$MACHINE" == "litex" ]]; then
            EMULATOR_ARGS+=("$RSP_PORT" "$LITEX_BOOTROM_IMAGE_PATH")
        else
            EMULATOR_ARGS+=("$RSP_PORT" "$KERNEL_ELF")
        fi

        echo "[little64] rsp        : 127.0.0.1:$RSP_PORT"

        "${EMULATOR_ARGS[@]}"
        status=$?
        trap - EXIT INT TERM
        printf '\n' >&2
        exit "$status"
        ;;
esac
