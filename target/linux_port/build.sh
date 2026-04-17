#!/usr/bin/env bash
set -euo pipefail

SCRIPT_FOLDER=$(dirname "$(readlink -f "$0")")
PYTHON_BIN=${LITTLE64_PYTHON:-}

if [[ -z "$PYTHON_BIN" ]]; then
    PYTHON_BIN=$(command -v python3 || true)
fi

if [[ -z "$PYTHON_BIN" || ! -x "$PYTHON_BIN" ]]; then
    echo "error: python3 is required to run target/linux_port/build.sh" >&2
    exit 1
fi

exec "$PYTHON_BIN" "$SCRIPT_FOLDER/linux_build.py" "$@"

