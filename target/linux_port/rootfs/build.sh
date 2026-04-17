#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR=$(dirname "$(readlink -f "$0")")
REPO_ROOT=$(readlink -f "$SCRIPT_DIR/../../..")
TOOLS_DIR="$REPO_ROOT/compilers/bin"
BUILD_DIR="$SCRIPT_DIR/build"
STAGING_DIR="$BUILD_DIR/staging"
INIT_OBJ="$BUILD_DIR/init.o"
INIT_ELF="$BUILD_DIR/init"
ROOTFS_IMAGE="$BUILD_DIR/rootfs.ext4"
ROOTFS_SIZE_MB="${LITTLE64_ROOTFS_SIZE_MB:-8}"

usage() {
    cat <<EOF
Usage: $0 [clean]

Builds a minimal ext4 rootfs image for the Little64 PV block device.

Environment:
    LITTLE64_ROOTFS_SIZE_MB   Size of the generated ext4 image in MiB (default: 8)
EOF
}

find_host_tool() {
    local tool_name="$1"

    if command -v "$tool_name" >/dev/null 2>&1; then
        command -v "$tool_name"
        return 0
    fi
    if [[ -x "/usr/sbin/$tool_name" ]]; then
        printf '%s\n' "/usr/sbin/$tool_name"
        return 0
    fi
    if [[ -x "/sbin/$tool_name" ]]; then
        printf '%s\n' "/sbin/$tool_name"
        return 0
    fi

    return 1
}

if [[ $# -gt 1 ]]; then
    usage >&2
    exit 1
fi

if [[ $# -eq 1 ]]; then
    case "$1" in
        clean)
            rm -rf "$BUILD_DIR"
            exit 0
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            echo "error: unknown argument: $1" >&2
            usage >&2
            exit 1
            ;;
    esac
fi

if [[ ! -x "$TOOLS_DIR/llvm-mc" ]]; then
    echo "error: llvm-mc not found at $TOOLS_DIR/llvm-mc" >&2
    echo "hint: build the LLVM toolchain first with: (cd $REPO_ROOT/compilers && ./build.sh llvm)" >&2
    exit 1
fi

if [[ ! -x "$TOOLS_DIR/ld.lld" ]]; then
    echo "error: ld.lld not found at $TOOLS_DIR/ld.lld" >&2
    echo "hint: build the LLVM toolchain first with: (cd $REPO_ROOT/compilers && ./build.sh llvm)" >&2
    exit 1
fi

if ! [[ "$ROOTFS_SIZE_MB" =~ ^[0-9]+$ ]] || [[ "$ROOTFS_SIZE_MB" == "0" ]]; then
    echo "error: LITTLE64_ROOTFS_SIZE_MB must be a positive integer" >&2
    exit 1
fi

MKFS_EXT4=""
if MKFS_EXT4=$(find_host_tool mke2fs); then
    :
elif MKFS_EXT4=$(find_host_tool mkfs.ext4); then
    :
else
    echo "error: neither mke2fs nor mkfs.ext4 is available" >&2
    exit 1
fi

rm -rf "$BUILD_DIR"
mkdir -p "$BUILD_DIR" "$STAGING_DIR/dev" "$STAGING_DIR/etc" "$STAGING_DIR/proc" "$STAGING_DIR/sys" "$STAGING_DIR/tmp"

"$TOOLS_DIR/llvm-mc" -triple=little64 -filetype=obj "$SCRIPT_DIR/init.S" -o "$INIT_OBJ"
"$TOOLS_DIR/ld.lld" -z noexecstack -e _start -T "$SCRIPT_DIR/init.ld" "$INIT_OBJ" -o "$INIT_ELF"
chmod 0755 "$INIT_ELF"
cp "$INIT_ELF" "$STAGING_DIR/init"

cat > "$STAGING_DIR/etc/issue" <<'EOF'
Little-64 Linux test rootfs
EOF

cat > "$STAGING_DIR/README.little64" <<'EOF'
This image is a minimal Little-64 test rootfs for the paravirtual block device.
It exists to get VFS onto a real disk-backed root filesystem during kernel bring-up.
EOF

"$MKFS_EXT4" -q -F -t ext4 -L little64-rootfs -m 0 -d "$STAGING_DIR" "$ROOTFS_IMAGE" "${ROOTFS_SIZE_MB}M"

echo "[little64-rootfs] built $ROOTFS_IMAGE"
echo "[little64-rootfs] init payload: $INIT_ELF"