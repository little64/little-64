#!/bin/bash

#
# Compiler Build Orchestrator
#
# Modular build system for managing multiple compilers.
# This script discovers and delegates to per-compiler build scripts.
#
# Usage:
#   ./build.sh                      # print usage
#   ./build.sh <compiler> [TARGET]  # build a specific compiler
#   ./build.sh all [TARGET]         # build all compilers
#   ./build.sh clean [compiler]     # clean build artifacts
#
# Examples:
#   ./build.sh lily-cc              # build lily-cc
#   ./build.sh all                  # build all compilers with defaults
#   ./build.sh clean lily-cc        # clean lily-cc
#   ./build.sh clean                # clean all compilers
#

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Discover available compilers by looking for <compiler>/build.sh
discover_compilers() {
    local compilers=()
    for build_script in "$SCRIPT_DIR"/*/build.sh; do
        if [ -f "$build_script" ]; then
            local compiler_dir=$(dirname "$build_script")
            local compiler_name=$(basename "$compiler_dir")
            compilers+=("$compiler_name")
        fi
    done
    echo "${compilers[@]}"
}

# Print usage information
print_usage() {
    echo "Compiler Build Orchestrator"
    echo ""
    echo "Usage: $(basename "$0") [COMMAND] [OPTIONS]"
    echo ""
    echo "Commands:"
    echo "  <compiler> [TARGET]  Build a specific compiler for a target"
    echo "  all [TARGET]         Build all available compilers"
    echo "  clean [compiler]     Clean build artifacts"
    echo "  help                 Print this help message"
    echo ""
    echo "Available compilers:"
    local compilers=($(discover_compilers))
    if [ ${#compilers[@]} -eq 0 ]; then
        echo "  (none found)"
    else
        for compiler in "${compilers[@]}"; do
            echo "  - $compiler"
        done
    fi
    echo ""
    echo "Examples:"
    echo "  $(basename "$0") lily-cc          # Build lily-cc"
    echo "  $(basename "$0") all              # Build all compilers"
    echo "  $(basename "$0") clean lily-cc    # Clean lily-cc artifacts"
}

# Main logic
if [ $# -eq 0 ]; then
    print_usage
    exit 0
fi

COMMAND="$1"
OPTION="${2:-}"

case "$COMMAND" in
    help)
        print_usage
        exit 0
        ;;

    clean)
        if [ -z "$OPTION" ]; then
            # Clean all compilers
            echo "Cleaning all compilers..."
            local compilers=($(discover_compilers))
            for compiler in "${compilers[@]}"; do
                "$SCRIPT_DIR/$compiler/build.sh" "" clean
            done
        else
            # Clean a specific compiler
            if [ -f "$SCRIPT_DIR/$OPTION/build.sh" ]; then
                "$SCRIPT_DIR/$OPTION/build.sh" "" clean
            else
                echo "Error: Compiler not found: $OPTION"
                exit 1
            fi
        fi
        ;;

    all)
        # Build all compilers with optional target
        local target="${OPTION:-little64}"
        echo "Building all compilers for target: $target"
        echo "========================================"
        local compilers=($(discover_compilers))
        for compiler in "${compilers[@]}"; do
            echo ""
            "$SCRIPT_DIR/$compiler/build.sh" "$target" build
        done
        echo ""
        echo "========================================"
        echo "✓ All builds complete"
        ;;

    *)
        # Build a specific compiler with optional target
        if [ -f "$SCRIPT_DIR/$COMMAND/build.sh" ]; then
            if [ -z "$OPTION" ]; then
                # No target specified, use default (little64)
                "$SCRIPT_DIR/$COMMAND/build.sh" little64 build
            else
                # Target specified
                "$SCRIPT_DIR/$COMMAND/build.sh" "$OPTION" build
            fi
        else
            echo "Error: Unknown compiler or command: $COMMAND"
            echo "Run '$(basename "$0") help' for usage information."
            exit 1
        fi
        ;;
esac
