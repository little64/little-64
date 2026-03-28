#!/bin/bash

#
# lily-cc Build Script
#
# Usage:
#   ./build.sh [TARGET] [ACTION]
#
# TARGET is accepted for interface compatibility but ignored — lily-cc targets
# Little-64 exclusively and the backend is selected at compile time.
# ACTION defaults to 'build'
#
# Examples:
#   ./build.sh              # build lily-cc
#   ./build.sh little64     # build lily-cc (TARGET ignored)
#   ./build.sh "" clean     # clean build artifacts
#

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LILY_SOURCE_DIR="$SCRIPT_DIR/lily-cc"
BUILD_DIR="$LILY_SOURCE_DIR/build"
BIN_OUTPUT_DIR="$SCRIPT_DIR/../bin"

# Action: build or clean
ACTION="${2:-build}"

# Validate that lily-cc source is present
if [ ! -d "$LILY_SOURCE_DIR" ]; then
    echo "Error: lily-cc source not found at: $LILY_SOURCE_DIR"
    echo "Please ensure the lily-cc submodule is initialized and populated."
    exit 1
fi

# Ensure output directory exists
mkdir -p "$BIN_OUTPUT_DIR"

case "$ACTION" in
    build)
        echo "Building lily-cc"
        echo "================"

        cmake -B "$BUILD_DIR" "$LILY_SOURCE_DIR/src"
        cmake --build "$BUILD_DIR" --target lilycc

        BUILT_BINARY="$BUILD_DIR/main/lilycc"
        OUTPUT_BINARY="$BIN_OUTPUT_DIR/lily-cc"

        if [ -f "$BUILT_BINARY" ]; then
            cp "$BUILT_BINARY" "$OUTPUT_BINARY"
            echo ""
            echo "✓ Build successful!"
            echo "Binary available at: $OUTPUT_BINARY"
        else
            echo "Error: Expected binary not found at: $BUILT_BINARY"
            exit 1
        fi
        ;;

    clean)
        echo "Cleaning lily-cc build artifacts"
        if [ -d "$BUILD_DIR" ]; then
            rm -rf "$BUILD_DIR"
            echo "Removed: $BUILD_DIR"
        fi

        OUTPUT_BINARY="$BIN_OUTPUT_DIR/lily-cc"
        if [ -f "$OUTPUT_BINARY" ]; then
            rm "$OUTPUT_BINARY"
            echo "Removed: $OUTPUT_BINARY"
        fi
        echo "✓ Clean successful"
        ;;

    *)
        echo "Usage: $0 [TARGET] [ACTION]"
        echo ""
        echo "TARGET: accepted for interface compatibility, ignored (lily-cc targets Little-64)"
        echo "ACTION: 'build' (default) or 'clean'"
        echo ""
        echo "Examples:"
        echo "  $0              # build lily-cc"
        echo "  $0 little64     # build lily-cc"
        echo "  $0 \"\" clean     # clean build artifacts"
        exit 1
        ;;
esac
