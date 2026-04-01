#!/bin/bash

#
# LLVM Build Script for Little-64
#
# Builds only the tools needed for C/C++ development and debugging:
#   clang, llc, llvm-objdump, llvm-mc, lld (+ optional lldb/lldb-dap)
#
# Usage:
#   ./build.sh [TARGET] [ACTION]
#
# TARGET is accepted for interface compatibility but ignored — this script
# always builds the Little64 LLVM backend.
# ACTION defaults to 'build'
#
# Examples:
#   ./build.sh              # build LLVM tools
#   ./build.sh little64     # build LLVM tools (TARGET ignored)
#   ./build.sh "" clean     # clean build artifacts
#
# Optional environment flags:
#   ENABLE_LLDB=1           # build and copy lldb + lldb-dap
#

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LLVM_SOURCE_DIR="$SCRIPT_DIR/llvm-project/llvm"
BUILD_DIR="$SCRIPT_DIR/build"
BIN_OUTPUT_DIR="$SCRIPT_DIR/../bin"

ACTION="${2:-build}"
ENABLE_LLDB="${ENABLE_LLDB:-0}"
LLVM_ENABLE_PROJECTS="clang;lld"

# Tools needed for C/C++ work and debugging
LLVM_TOOLS=(clang llc llvm-objdump llvm-mc lld llvm-readelf llvm-readobj)

# Tools to copy
COPY_TOOLS=(
    clang
    llc
    llvm-objdump
    llvm-mc
    lld
    ld.lld
    llvm-readelf
    llvm-readobj
)

if [ "$ENABLE_LLDB" = "1" ]; then
    LLVM_ENABLE_PROJECTS="clang;lld;lldb"
    LLVM_TOOLS+=(lldb lldb-dap)
    COPY_TOOLS+=(lldb lldb-dap)
fi

copy_binary() {
    local src="$1"
    local dst="$2"

    if [ ! -f "$src" ]; then
        echo "  Warning: expected binary not found: $src"
        return
    fi

    if command -v strip >/dev/null 2>&1 && strip -o "$dst" "$src" 2>/dev/null; then
        :
    else
        cp "$src" "$dst"
    fi

    local size
    size=$(du -sh "$dst" | cut -f1)
    echo "  ✓ $(basename "$dst") ($size)"
}

if [ ! -d "$LLVM_SOURCE_DIR" ]; then
    echo "Error: LLVM source not found at: $LLVM_SOURCE_DIR"
    echo "Please ensure the llvm-project submodule is initialized and populated."
    exit 1
fi

mkdir -p "$BIN_OUTPUT_DIR"

case "$ACTION" in
    build)
        echo "Building LLVM for Little-64"
        echo "==========================="

        if [ ! -f "$BUILD_DIR/CMakeCache.txt" ]; then
            echo "Configuring LLVM..."
            cmake -S "$LLVM_SOURCE_DIR" -B "$BUILD_DIR" \
                -DCMAKE_BUILD_TYPE=RelWithDebInfo \
                -DLLVM_TARGETS_TO_BUILD="Little64" \
                -DLLVM_ENABLE_PROJECTS="$LLVM_ENABLE_PROJECTS" \
                -DLLVM_BUILD_TOOLS=ON \
                -DLLVM_INCLUDE_TESTS=OFF \
                -DLLVM_INCLUDE_EXAMPLES=OFF \
                -DLLVM_INCLUDE_BENCHMARKS=OFF \
                -DCLANG_INCLUDE_TESTS=OFF \
                -DCLANG_INCLUDE_DOCS=OFF
        else
            echo "Using existing CMake configuration."
            if [ "$ENABLE_LLDB" = "1" ] && ! grep -q 'LLVM_ENABLE_PROJECTS:STRING=.*lldb' "$BUILD_DIR/CMakeCache.txt"; then
                echo "Reconfiguring to enable LLDB project..."
                cmake -S "$LLVM_SOURCE_DIR" -B "$BUILD_DIR" \
                    -DCMAKE_BUILD_TYPE=RelWithDebInfo \
                    -DLLVM_TARGETS_TO_BUILD="Little64" \
                    -DLLVM_ENABLE_PROJECTS="$LLVM_ENABLE_PROJECTS" \
                    -DLLVM_BUILD_TOOLS=ON \
                    -DLLVM_INCLUDE_TESTS=OFF \
                    -DLLVM_INCLUDE_EXAMPLES=OFF \
                    -DLLVM_INCLUDE_BENCHMARKS=OFF \
                    -DCLANG_INCLUDE_TESTS=OFF \
                    -DCLANG_INCLUDE_DOCS=OFF
            fi
        fi

        echo "Building tools: ${LLVM_TOOLS[*]}"
        cmake --build "$BUILD_DIR" --target "${LLVM_TOOLS[@]}" -- -j"$(nproc)"

        echo ""
        echo "Copying and stripping binaries to: $BIN_OUTPUT_DIR"
        for tool in "${COPY_TOOLS[@]}"; do
            src="$BUILD_DIR/bin/$tool"
            dst="$BIN_OUTPUT_DIR/$tool"
            copy_binary "$src" "$dst"
        done

        echo ""
        echo "✓ Build successful!"
        ;;

    clean)
        echo "Cleaning LLVM build artifacts"
        if [ -d "$BUILD_DIR" ]; then
            rm -rf "$BUILD_DIR"
            echo "Removed: $BUILD_DIR"
        fi

        for tool in "${LLVM_TOOLS[@]}"; do
            bin="$BIN_OUTPUT_DIR/$tool"
            if [ -f "$bin" ]; then
                rm "$bin"
                echo "Removed: $bin"
            fi
        done
        echo "✓ Clean successful"
        ;;

    *)
        echo "Usage: $0 [TARGET] [ACTION]"
        echo ""
        echo "TARGET: accepted for interface compatibility, ignored (always builds Little64)"
        echo "ACTION: 'build' (default) or 'clean'"
        echo "ENV:    ENABLE_LLDB=1 to build lldb/lldb-dap"
        echo ""
        echo "Examples:"
        echo "  $0              # build LLVM tools"
        echo "  $0 little64     # build LLVM tools"
        echo "  ENABLE_LLDB=1 $0 # build LLVM tools + lldb/lldb-dap"
        echo "  $0 \"\" clean     # clean build artifacts"
        exit 1
        ;;
esac
