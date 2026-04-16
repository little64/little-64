#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR=$(dirname "$(readlink -f "$0")")
REPO_ROOT=$(readlink -f "$SCRIPT_DIR/../..")
LLVM_BIN="$REPO_ROOT/compilers/bin"
SYMBOLIZER="$LLVM_BIN/llvm-symbolizer"
ADDR2LINE="$LLVM_BIN/llvm-addr2line"
OBJDUMP="$LLVM_BIN/llvm-objdump"
PROFILE_PATHS_PY="$SCRIPT_DIR/profile_paths.py"

usage() {
    cat <<EOF
Usage: $(basename "$0") [--defconfig <name>] [--elf <path>] [--context-bytes N] [--no-disasm] <pc>

Resolve a program counter (PC) to function/file/line in a Linux vmlinux image.

Arguments:
  <pc>                 Address to resolve (hex like 0xffffffc000013302 or decimal)

Options:
    --defconfig <name>   Linux defconfig for profile-aware default ELF lookup
    --elf <path>         ELF image to inspect (default: selected profile vmlinux)
  --context-bytes N    Disassembly bytes before/after PC (default: 32)
  --no-disasm          Skip disassembly context output
  -h, --help           Show this help message

Examples:
  $(basename "$0") 0xffffffc000013302
    $(basename "$0") --defconfig little64_litex_sim_defconfig 0xffffffc000013302
  $(basename "$0") --elf target/linux_port/build/vmlinux 0xffffffc000013302
  $(basename "$0") --context-bytes 64 0xffffffc000013302
EOF
}

DEFCONFIG_NAME=""
ELF_PATH=""
CONTEXT_BYTES=32
SHOW_DISASM=1
PC_ARG=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --defconfig)
            [[ $# -ge 2 ]] || { echo "error: --defconfig requires a value" >&2; exit 1; }
            DEFCONFIG_NAME="$2"
            shift 2
            ;;
        --elf)
            [[ $# -ge 2 ]] || { echo "error: --elf requires a path" >&2; exit 1; }
            ELF_PATH="$2"
            shift 2
            ;;
        --context-bytes)
            [[ $# -ge 2 ]] || { echo "error: --context-bytes requires a value" >&2; exit 1; }
            CONTEXT_BYTES="$2"
            shift 2
            ;;
        --no-disasm)
            SHOW_DISASM=0
            shift
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            if [[ -n "$PC_ARG" ]]; then
                echo "error: multiple PC arguments provided" >&2
                usage >&2
                exit 1
            fi
            PC_ARG="$1"
            shift
            ;;
    esac
done

PROFILE_ARGS=()
if [[ -n "$DEFCONFIG_NAME" ]]; then
    PROFILE_ARGS+=(--defconfig "$DEFCONFIG_NAME")
fi

if [[ -z "$ELF_PATH" ]]; then
    ELF_PATH=$(python3 "$PROFILE_PATHS_PY" existing-kernel "${PROFILE_ARGS[@]}" 2>/dev/null || true)
    if [[ -z "$ELF_PATH" ]]; then
        ELF_PATH=$(python3 "$PROFILE_PATHS_PY" kernel "${PROFILE_ARGS[@]}" 2>/dev/null || true)
    fi
fi

if [[ -z "$PC_ARG" ]]; then
    echo "error: missing PC argument" >&2
    usage >&2
    exit 1
fi

if [[ ! -f "$ELF_PATH" ]]; then
    echo "error: ELF not found: $ELF_PATH" >&2
    echo "hint: build the selected kernel first with: target/linux_port/build.sh vmlinux" >&2
    exit 1
fi

if [[ ! -x "$SYMBOLIZER" ]]; then
    echo "error: missing tool: $SYMBOLIZER" >&2
    echo "hint: build LLVM tools first with: compilers/build.sh llvm" >&2
    exit 1
fi

if ! [[ "$CONTEXT_BYTES" =~ ^[0-9]+$ ]]; then
    echo "error: --context-bytes must be a non-negative integer" >&2
    exit 1
fi

PC_DEC=$((PC_ARG))
PC_HEX=$(printf "0x%x" "$PC_DEC")

echo "[little64] pc-to-line"
echo "  elf: $ELF_PATH"
echo "  pc : $PC_HEX"
echo

echo "== symbolizer =="
"$SYMBOLIZER" --obj="$ELF_PATH" --inlining "$PC_HEX"
echo

if [[ -x "$ADDR2LINE" ]]; then
    echo "== addr2line =="
    "$ADDR2LINE" -e "$ELF_PATH" -f -C "$PC_HEX"
    echo
fi

if [[ "$SHOW_DISASM" -eq 1 ]]; then
    if [[ -x "$OBJDUMP" ]]; then
        START_DEC=$((PC_DEC > CONTEXT_BYTES ? PC_DEC - CONTEXT_BYTES : 0))
        STOP_DEC=$((PC_DEC + CONTEXT_BYTES))
        START_HEX=$(printf "0x%x" "$START_DEC")
        STOP_HEX=$(printf "0x%x" "$STOP_DEC")

        echo "== disassembly context =="
        "$OBJDUMP" \
            --disassemble \
            --demangle \
            --line-numbers \
            --print-imm-hex \
            --start-address="$START_HEX" \
            --stop-address="$STOP_HEX" \
            "$ELF_PATH"
    else
        echo "warning: $OBJDUMP not found, skipping disassembly context" >&2
    fi
fi
