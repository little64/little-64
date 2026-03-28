#!/bin/bash

#
# vbcc Build Script
#
# Usage:
#   ./build.sh [TARGET] [ACTION]
#
# TARGET defaults to 'm68k' (reference backend for testing)
# ACTION defaults to 'build'
#
# Examples:
#   ./build.sh              # build vbcc for m68k
#   ./build.sh m68k         # build vbcc for m68k
#   ./build.sh little64     # build vbcc for little64 (once backend is ready)
#   ./build.sh m68k clean   # clean build artifacts for m68k
#

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VBCC_SOURCE_DIR="$SCRIPT_DIR/vbcc"
BIN_OUTPUT_DIR="$SCRIPT_DIR/../bin"

# Default target (use m68k reference backend for testing)
TARGET="${1:-m68k}"

# Action: build or clean
ACTION="${2:-build}"

# Validate that vbcc source is present
if [ ! -d "$VBCC_SOURCE_DIR" ]; then
    echo "Error: vbcc source not found at: $VBCC_SOURCE_DIR"
    echo "Please ensure the vbcc submodule is initialized and populated."
    exit 1
fi

# Ensure output directory exists
mkdir -p "$BIN_OUTPUT_DIR"

# Change to vbcc source directory
cd "$VBCC_SOURCE_DIR"

case "$ACTION" in
    build)
        echo "Building vbcc for target: $TARGET"
        echo "==================================="

        # Run make for the target
        if make "TARGET=$TARGET" all; then
            # Copy the resulting binary to the shared bin directory
            BINARY_NAME="vbcc$TARGET"
            SOURCE_BINARY="bin/$BINARY_NAME"
            OUTPUT_BINARY="$BIN_OUTPUT_DIR/vbcc-$TARGET"

            if [ -f "$SOURCE_BINARY" ]; then
                cp "$SOURCE_BINARY" "$OUTPUT_BINARY"
                echo ""
                echo "✓ Build successful!"
                echo "Binary available at: $OUTPUT_BINARY"
                exit 0
            else
                echo "Error: Expected binary not found at: $SOURCE_BINARY"
                exit 1
            fi
        else
            echo "Error: make failed"
            exit 1
        fi
        ;;

    clean)
        echo "Cleaning build artifacts for target: $TARGET"
        make "TARGET=$TARGET" clean

        # Remove the output binary
        OUTPUT_BINARY="$BIN_OUTPUT_DIR/vbcc-$TARGET"
        if [ -f "$OUTPUT_BINARY" ]; then
            rm "$OUTPUT_BINARY"
            echo "Removed: $OUTPUT_BINARY"
        fi
        echo "✓ Clean successful"
        ;;

    *)
        echo "Usage: $0 [TARGET] [ACTION]"
        echo ""
        echo "TARGET: vbcc machine backend (default: m68k)"
        echo "ACTION: 'build' (default) or 'clean'"
        echo ""
        echo "Examples:"
        echo "  $0              # build for m68k"
        echo "  $0 m68k         # build for m68k"
        echo "  $0 little64     # build for little64"
        echo "  $0 m68k clean   # clean m68k build"
        exit 1
        ;;
esac
