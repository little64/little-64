#!/usr/bin/env bash
set -euo pipefail

REAL_CLANG="${LITTLE64_REAL_CLANG:-$(dirname "$0")/../../compilers/bin/clang}"
TIMEOUT_SEC="${LITTLE64_CLANG_TIMEOUT_SEC:-120}"
MAX_VMEM_KB="${LITTLE64_CLANG_MAX_VMEM_KB:-10485760}"
LOG_DIR="${LITTLE64_CLANG_GUARD_LOG_DIR:-/tmp/little64-clang-guard}"

mkdir -p "$LOG_DIR"

stamp="$(date +%Y%m%d-%H%M%S)-$$"
time_log="$LOG_DIR/$stamp.time"
cmd_log="$LOG_DIR/$stamp.cmd"

printf '%q ' "$REAL_CLANG" "$@" > "$cmd_log"
printf '\n' >> "$cmd_log"

set +e
(
    if [[ "$MAX_VMEM_KB" =~ ^[0-9]+$ ]] && [ "$MAX_VMEM_KB" -gt 0 ]; then
        ulimit -v "$MAX_VMEM_KB"
    fi
    exec /usr/bin/time -v -o "$time_log" \
        timeout --signal=TERM --kill-after=10s "${TIMEOUT_SEC}s" \
        "$REAL_CLANG" "$@"
)
status=$?
set -e

rss_kb="unknown"
if [ -f "$time_log" ]; then
    rss_kb="$(awk -F: '/Maximum resident set size/ {gsub(/^[ \t]+/, "", $2); print $2}' "$time_log" | tail -n 1)"
fi

if [ "$status" -eq 124 ]; then
    echo "clang_guard: timeout after ${TIMEOUT_SEC}s (likely backend loop), peak RSS=${rss_kb} KB" >&2
    echo "clang_guard: command log: $cmd_log" >&2
    echo "clang_guard: timing log: $time_log" >&2
elif [ "$status" -ne 0 ]; then
    echo "clang_guard: clang exited with status $status, peak RSS=${rss_kb} KB" >&2
    echo "clang_guard: command log: $cmd_log" >&2
    echo "clang_guard: timing log: $time_log" >&2
fi

exit "$status"
