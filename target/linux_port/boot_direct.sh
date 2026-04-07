#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR=$(dirname "$(readlink -f "$0")")
REPO_ROOT=$(readlink -f "$SCRIPT_DIR/../..")
EMULATOR_BIN="$REPO_ROOT/builddir/little-64"
DEFAULT_KERNEL_ELF="$SCRIPT_DIR/build/vmlinux"

KERNEL_ELF="${1:-$DEFAULT_KERNEL_ELF}"

if [[ ! -x "$EMULATOR_BIN" ]]; then
    echo "error: emulator binary not found at $EMULATOR_BIN"
    echo "hint: build it first with: meson compile -C $REPO_ROOT/builddir"
    exit 1
fi

if [[ ! -f "$KERNEL_ELF" ]]; then
    echo "error: kernel ELF not found at $KERNEL_ELF"
    echo "hint: build it first with: $SCRIPT_DIR/build.sh vmlinux -j1"
    exit 1
fi

echo "[little64] direct boot: $KERNEL_ELF"

# Keep output tooling readable when killed by timeout by forcing a trailing newline.
print_trailing_newline() {
    printf '\n' >&2
}

trap print_trailing_newline EXIT INT TERM
"$EMULATOR_BIN" --trace-mmio --boot-events --boot-mode=direct "$KERNEL_ELF"
status=$?
trap - EXIT INT TERM
printf '\n' >&2
exit "$status"
