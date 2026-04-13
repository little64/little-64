#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR=$(dirname "$(readlink -f "$0")")
REPO_ROOT=$(readlink -f "$SCRIPT_DIR/../..")
EMULATOR_DEBUG_BIN="$REPO_ROOT/builddir/little-64-debug"
DEFAULT_KERNEL_ELF="$SCRIPT_DIR/build/vmlinux"
DEFAULT_ROOTFS_IMAGE="$SCRIPT_DIR/rootfs/build/rootfs.ext2"

usage() {
    cat <<EOF
Usage: $0 [--rootfs PATH | --no-rootfs] [kernel-elf]

If kernel-elf is omitted, $DEFAULT_KERNEL_ELF is used.
If --rootfs is omitted, $DEFAULT_ROOTFS_IMAGE is used.
Use --no-rootfs to boot without attaching a disk image.
EOF
}

KERNEL_ELF="$DEFAULT_KERNEL_ELF"
ROOTFS_IMAGE="${LITTLE64_ROOTFS_IMAGE:-$DEFAULT_ROOTFS_IMAGE}"
ATTACH_ROOTFS=1
POSITIONAL=()
while [[ $# -gt 0 ]]; do
    case "$1" in
        -h|--help)
            usage
            exit 0
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

if [[ ${#POSITIONAL[@]} -gt 1 ]]; then
    echo "error: too many positional arguments" >&2
    usage
    exit 1
fi

if [[ ${#POSITIONAL[@]} -eq 1 ]]; then
    KERNEL_ELF="${POSITIONAL[0]}"
fi

if [[ ! -x "$EMULATOR_DEBUG_BIN" ]]; then
    echo "error: emulator binary not found at $EMULATOR_DEBUG_BIN"
    echo "hint: build it first with: meson compile -C $REPO_ROOT/builddir"
    exit 1
fi

if [[ ! -f "$KERNEL_ELF" ]]; then
    echo "error: kernel ELF not found at $KERNEL_ELF"
    echo "hint: build it first with: $SCRIPT_DIR/build.sh vmlinux -j1"
    exit 1
fi

if [[ "$ATTACH_ROOTFS" == "1" && ! -f "$ROOTFS_IMAGE" ]]; then
    echo "error: rootfs image not found at $ROOTFS_IMAGE" >&2
    echo "hint: build it first with: $SCRIPT_DIR/rootfs/build.sh" >&2
    echo "hint: or boot without a root disk via: $0 --no-rootfs" >&2
    exit 1
fi

echo "[little64] starting debug server at port 9000: $KERNEL_ELF"
if [[ "$ATTACH_ROOTFS" == "1" ]]; then
    echo "[little64] rootfs image: $ROOTFS_IMAGE"
fi

# Keep output tooling readable when killed by timeout by forcing a trailing newline.
print_trailing_newline() {
    printf '\n' >&2
}

trap print_trailing_newline EXIT INT TERM
EMULATOR_ARGS=("$EMULATOR_DEBUG_BIN" --boot-mode=direct)
if [[ "$ATTACH_ROOTFS" == "1" ]]; then
    EMULATOR_ARGS+=("--disk=$ROOTFS_IMAGE" --disk-readonly)
fi
EMULATOR_ARGS+=(9000 "$KERNEL_ELF")
"${EMULATOR_ARGS[@]}"
status=$?
trap - EXIT INT TERM
printf '\n' >&2
exit "$status"
