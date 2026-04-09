#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR=$(dirname "$(readlink -f "$0")")
REPO_ROOT=$(readlink -f "$SCRIPT_DIR/../..")
LLVM_BIN="$REPO_ROOT/compilers/bin"
LLDB_BIN="$LLVM_BIN/lldb"

DEFAULT_HOST="127.0.0.1"
DEFAULT_PORT="9000"
DEFAULT_ELF_UNSTRIPPED="$SCRIPT_DIR/build/vmlinux.unstripped"
DEFAULT_ELF="$SCRIPT_DIR/build/vmlinux"

usage() {
    cat <<EOF
Usage: $(basename "$0") [--host <ip-or-hostname>] [--port <port>] [--elf <path>] [--] [lldb args...]

Connect LLDB to a Little64 RSP server and enter LLDB TUI (gui) mode.

Options:
  --host <value>    RSP host (default: $DEFAULT_HOST)
  --port <value>    RSP port (default: $DEFAULT_PORT)
  --elf <path>      ELF for symbols (default: vmlinux.unstripped if present, else vmlinux)
  -h, --help        Show this help message

Examples:
  $(basename "$0")
  $(basename "$0") --port 1234
  $(basename "$0") --host 10.0.0.5 --port 9000 --elf target/linux_port/build/vmlinux.unstripped
EOF
}

HOST="$DEFAULT_HOST"
PORT="$DEFAULT_PORT"
ELF_PATH=""
EXTRA_LLDB_ARGS=()

while [[ $# -gt 0 ]]; do
    case "$1" in
        --host)
            [[ $# -ge 2 ]] || { echo "error: --host requires a value" >&2; exit 1; }
            HOST="$2"
            shift 2
            ;;
        --port)
            [[ $# -ge 2 ]] || { echo "error: --port requires a value" >&2; exit 1; }
            PORT="$2"
            shift 2
            ;;
        --elf)
            [[ $# -ge 2 ]] || { echo "error: --elf requires a path" >&2; exit 1; }
            ELF_PATH="$2"
            shift 2
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        --)
            shift
            EXTRA_LLDB_ARGS=("$@")
            break
            ;;
        *)
            echo "error: unknown argument: $1" >&2
            usage >&2
            exit 1
            ;;
    esac
done

if [[ -z "$ELF_PATH" ]]; then
    if [[ -f "$DEFAULT_ELF_UNSTRIPPED" ]]; then
        ELF_PATH="$DEFAULT_ELF_UNSTRIPPED"
    elif [[ -f "$DEFAULT_ELF" ]]; then
        ELF_PATH="$DEFAULT_ELF"
    fi
fi

if [[ ! -x "$LLDB_BIN" ]]; then
    echo "error: missing LLDB binary: $LLDB_BIN" >&2
    echo "hint: build LLVM tools first with: compilers/build.sh llvm" >&2
    exit 1
fi

if ! [[ "$PORT" =~ ^[0-9]+$ ]] || [[ "$PORT" -lt 1 || "$PORT" -gt 65535 ]]; then
    echo "error: --port must be an integer in range 1..65535" >&2
    exit 1
fi

LLDB_ARGS=()
if [[ -n "$ELF_PATH" ]]; then
    if [[ ! -f "$ELF_PATH" ]]; then
        echo "error: ELF not found: $ELF_PATH" >&2
        exit 1
    fi
    LLDB_ARGS+=("$ELF_PATH")
fi

LLDB_ARGS+=(
    --one-line "gdb-remote $HOST:$PORT"
    --one-line "gui"
)

if [[ ${#EXTRA_LLDB_ARGS[@]} -gt 0 ]]; then
    LLDB_ARGS+=("${EXTRA_LLDB_ARGS[@]}")
fi

echo "[little64] launching LLDB TUI"
echo "  lldb: $LLDB_BIN"
echo "  rsp : $HOST:$PORT"
if [[ -n "$ELF_PATH" ]]; then
    echo "  elf : $ELF_PATH"
else
    echo "  elf : (none, symbols may be unavailable)"
fi
echo

exec "$LLDB_BIN" "${LLDB_ARGS[@]}"
