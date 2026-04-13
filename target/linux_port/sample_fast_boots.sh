#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR=$(dirname "$(readlink -f "$0")")
PYTHON_BIN="${PYTHON:-python3}"
SCRIPT_PY="$SCRIPT_DIR/sample_fast_boots.py"

if [[ ! -f "$SCRIPT_PY" ]]; then
    echo "error: missing script: $SCRIPT_PY" >&2
    exit 1
fi

exec "$PYTHON_BIN" "$SCRIPT_PY" "$@"