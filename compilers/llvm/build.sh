#!/bin/bash

#
# LLVM Build Script for Little-64
#
# Builds a broad LLVM/LLDB toolchain for development, debugging, and testing.
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

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LLVM_SOURCE_DIR="$SCRIPT_DIR/llvm-project/llvm"
BUILD_DIR="$SCRIPT_DIR/build"
BIN_OUTPUT_DIR="$SCRIPT_DIR/../bin"

ACTION="${2:-build}"
LLVM_ENABLE_PROJECTS="clang;lld;lldb"

# Broad set of useful tool targets. Some may not exist on every platform/
# configuration; unavailable targets are filtered out automatically.
DESIRED_TOOL_TARGETS=(
    FileCheck
    clang
    clang++
    clang-cl
    clang-cpp
    # clang-format
    clang-tblgen
    count
    ld.lld
    ld64.lld
    llc
    lld
    lld-link
    lldb
    lldb-argdumper
    lldb-dap
    lldb-server
    lli
    llvm-ar
    llvm-as
    llvm-addr2line
    llvm-bcanalyzer
    llvm-cas
    llvm-cat
    llvm-config
    llvm-cov
    llvm-cxxfilt
    llvm-cxxmap
    llvm-debuginfo-analyzer
    llvm-debuginfod
    llvm-debuginfod-find
    llvm-diff
    llvm-dis
    llvm-dwarfdump
    llvm-link
    llvm-lit
    llvm-lto
    llvm-mc
    llvm-mca
    llvm-ml
    llvm-modextract
    llvm-nm
    llvm-objcopy
    llvm-objdump
    llvm-opt-report
    llvm-profdata
    llvm-profgen
    llvm-ranlib
    llvm-rc
    llvm-readelf
    llvm-readobj
    llvm-readtapi
    llvm-reduce
    llvm-size
    llvm-strings
    llvm-strip
    llvm-symbolizer
    llvm-undname
    llvm-windres
    llvm-xray
    not
    obj2yaml
    opt
    sancov
    sanstats
    split-file
    wasm-ld
    yaml2obj
)

# Tool binaries exported into compilers/bin
COPY_TOOLS=(
    FileCheck
    clang
    clang++
    clang-cl
    clang-cpp
    # clang-format
    count
    ld.lld
    ld64.lld
    llc
    lld
    lld-link
    lldb
    lldb-argdumper
    lldb-dap
    lldb-server
    lli
    llvm-ar
    llvm-as
    llvm-addr2line
    llvm-bcanalyzer
    llvm-cas
    llvm-cat
    llvm-config
    llvm-cov
    llvm-cxxfilt
    llvm-cxxmap
    llvm-debuginfo-analyzer
    llvm-debuginfod
    llvm-debuginfod-find
    llvm-diff
    llvm-dis
    llvm-dwarfdump
    llvm-link
    llvm-lit
    llvm-lto
    llvm-objdump
    llvm-mc
    llvm-mca
    llvm-ml
    llvm-modextract
    llvm-nm
    llvm-objcopy
    llvm-opt-report
    llvm-profdata
    llvm-profgen
    llvm-ranlib
    llvm-rc
    llvm-readelf
    llvm-readobj
    llvm-readtapi
    llvm-reduce
    llvm-size
    llvm-strings
    llvm-strip
    llvm-symbolizer
    llvm-undname
    llvm-windres
    llvm-xray
    not
    obj2yaml
    opt
    sancov
    sanstats
    split-file
    wasm-ld
    yaml2obj
)

target_available() {
    local target="$1"
    for available in "${AVAILABLE_TARGETS[@]}"; do
        if [ "$available" = "$target" ]; then
            return 0
        fi
    done
    return 1
}

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

        # Flags applied on every configure (fresh or incremental).
        CMAKE_FLAGS=(
            -DCMAKE_BUILD_TYPE=RelWithDebInfo
            -DLLVM_TARGETS_TO_BUILD="Little64"
            -DLLVM_ENABLE_PROJECTS="$LLVM_ENABLE_PROJECTS"
            -DLLVM_BUILD_TOOLS=ON
            -DLLVM_INCLUDE_TESTS=OFF
            -DLLVM_INCLUDE_EXAMPLES=OFF
            -DLLVM_INCLUDE_BENCHMARKS=OFF
            -DCLANG_INCLUDE_TESTS=OFF
            -DCLANG_INCLUDE_DOCS=OFF
            # Keep assert() active even in RelWithDebInfo (strips -DNDEBUG).
            -DLLVM_ENABLE_ASSERTIONS=ON
            # Use mold for host linking; ld.lld is still used for target output.
            # LLVM_ENABLE_LLD must be OFF when LLVM_USE_LINKER is set explicitly.
            -DLLVM_ENABLE_LLD=OFF
            -DLLVM_USE_LINKER=mold
        )

        if [ ! -f "$BUILD_DIR/CMakeCache.txt" ]; then
            echo "Configuring LLVM..."
            cmake -S "$LLVM_SOURCE_DIR" -B "$BUILD_DIR" "${CMAKE_FLAGS[@]}"
        else
            echo "Using existing CMake configuration."
            if ! grep -q 'LLVM_ENABLE_PROJECTS:STRING=.*lldb' "$BUILD_DIR/CMakeCache.txt" ||
               ! grep -q 'LLVM_ENABLE_ASSERTIONS:BOOL=ON' "$BUILD_DIR/CMakeCache.txt" ||
               ! grep -q 'LLVM_USE_LINKER.*=mold' "$BUILD_DIR/CMakeCache.txt"; then
                echo "Reconfiguring (assertions, linker, or projects changed)..."
                cmake -S "$LLVM_SOURCE_DIR" -B "$BUILD_DIR" "${CMAKE_FLAGS[@]}"
            fi
        fi

        mapfile -t AVAILABLE_TARGETS < <(ninja -C "$BUILD_DIR" -t targets all | awk -F: '{print $1}')

        BUILD_TARGETS=()
        for tool in "${DESIRED_TOOL_TARGETS[@]}"; do
            if target_available "$tool"; then
                BUILD_TARGETS+=("$tool")
            fi
        done

        if [ "${#BUILD_TARGETS[@]}" -eq 0 ]; then
            echo "Error: none of the requested tool targets are available."
            exit 1
        fi

        echo "Building tools: ${BUILD_TARGETS[*]}"
        nice -n 19 cmake --build "$BUILD_DIR" --target "${BUILD_TARGETS[@]}" -- -j"$(nproc)"

        echo ""
        echo "Copying and stripping binaries to: $BIN_OUTPUT_DIR"

        PARALLEL_COPY_JOBS="$(nproc)"
        tmpdir=$(mktemp -d)
        cleanup() {
            rm -rf "$tmpdir"
        }
        trap cleanup EXIT

        copy_pids=()
        copy_failed=0
        active_jobs=0
        for tool in "${COPY_TOOLS[@]}"; do
            src="$BUILD_DIR/bin/$tool"
            dst="$BIN_OUTPUT_DIR/$tool"
            outfile="$tmpdir/$tool.out"

            (
                copy_binary "$src" "$dst"
            ) >"$outfile" 2>&1 &
            copy_pids+=("$!")
            active_jobs=$((active_jobs + 1))

            if [ "$active_jobs" -ge "$PARALLEL_COPY_JOBS" ]; then
                if ! wait -n; then
                    copy_failed=1
                fi
                active_jobs=$((active_jobs - 1))
            fi
        done

        while [ "$active_jobs" -gt 0 ]; do
            if ! wait -n; then
                copy_failed=1
            fi
            active_jobs=$((active_jobs - 1))
        done

        for tool in "${COPY_TOOLS[@]}"; do
            outfile="$tmpdir/$tool.out"
            if [ -s "$outfile" ]; then
                cat "$outfile"
            fi
        done

        if [ "$copy_failed" -ne 0 ]; then
            echo ""
            echo "Error: one or more binaries failed to copy or strip."
            exit 1
        fi

        echo ""
        echo "✓ Build successful!"

        # ---------------------------------------------------------------
        # Cross-build compiler-rt builtins for Little64
        # ---------------------------------------------------------------
        echo ""
        echo "Building compiler-rt builtins for Little64"
        echo "=========================================="

        BUILTINS_SOURCE_DIR="$SCRIPT_DIR/llvm-project/compiler-rt/lib/builtins"
        BUILTINS_BUILD_DIR="$SCRIPT_DIR/build-builtins-little64"
        CLANG_BIN="$BUILD_DIR/bin/clang"
        LLVM_AR_BIN="$BUILD_DIR/bin/llvm-ar"
        LLVM_RANLIB_BIN="$BUILD_DIR/bin/llvm-ranlib"

        BUILTINS_CMAKE_FLAGS=(
            -DCMAKE_C_COMPILER="$CLANG_BIN"
            -DCMAKE_C_COMPILER_TARGET="little64-unknown-elf"
            -DCMAKE_ASM_COMPILER="$CLANG_BIN"
            -DCMAKE_ASM_COMPILER_TARGET="little64-unknown-elf"
            -DCMAKE_AR="$LLVM_AR_BIN"
            -DCMAKE_NM="$BUILD_DIR/bin/llvm-nm"
            -DCMAKE_RANLIB="$LLVM_RANLIB_BIN"
            -DCMAKE_C_FLAGS="-ffreestanding -nostdlib -fPIC --target=little64-unknown-elf"
            -DCMAKE_ASM_FLAGS="--target=little64-unknown-elf"
            -DCMAKE_SYSTEM_NAME=Generic
            -DCMAKE_CROSSCOMPILING=ON
            -DCMAKE_TRY_COMPILE_TARGET_TYPE=STATIC_LIBRARY
            # The toolchain only has the Little64 target, so skip the CXX
            # compiler test (builtins are pure C) and force the C compiler
            # so cmake does not try to compile a host test program.
            -DCMAKE_CXX_COMPILER_FORCED=ON
            -DCMAKE_C_COMPILER_FORCED=ON
            -DCOMPILER_RT_BAREMETAL_BUILD=ON
            -DCOMPILER_RT_DEFAULT_TARGET_ONLY=ON
            -DCOMPILER_RT_OS_DIR=""
        )

        if [ ! -f "$BUILTINS_BUILD_DIR/CMakeCache.txt" ]; then
            echo "Configuring compiler-rt builtins..."
            cmake -S "$BUILTINS_SOURCE_DIR" -B "$BUILTINS_BUILD_DIR" \
                "${BUILTINS_CMAKE_FLAGS[@]}"
        else
            echo "Using existing compiler-rt builtins configuration."
        fi

        nice -n 19 cmake --build "$BUILTINS_BUILD_DIR" -- -j"$(nproc)"

        # Install into the clang resource directory so the driver finds it.
        CLANG_VERSION=$("$CLANG_BIN" --version | grep -oP 'clang version \K[0-9]+\.[0-9]+\.[0-9]+')
        CLANG_MAJOR="${CLANG_VERSION%%.*}"
        RESOURCE_LIB_DIR="$BUILD_DIR/lib/clang/$CLANG_MAJOR/lib"

        # The BareMetal driver looks under <resource>/lib/baremetal/ and also
        # under <resource>/lib/ directly.  Install to both so that the library
        # is found regardless of the driver's lookup order.
        for dest_dir in "$RESOURCE_LIB_DIR/baremetal" "$RESOURCE_LIB_DIR"; do
            mkdir -p "$dest_dir"
            # Find the built builtins library (name varies by cmake version).
            for candidate in \
                "$BUILTINS_BUILD_DIR/libclang_rt.builtins-little64.a" \
                "$BUILTINS_BUILD_DIR/libclang_rt.builtins.a" \
                "$BUILTINS_BUILD_DIR/lib/libclang_rt.builtins-little64.a" \
                "$BUILTINS_BUILD_DIR/lib/libclang_rt.builtins.a" \
                "$BUILTINS_BUILD_DIR/lib/little64/libclang_rt.builtins.a"; do
                if [ -f "$candidate" ]; then
                    cp "$candidate" "$dest_dir/libclang_rt.builtins-little64.a"
                    echo "  ✓ Installed to $dest_dir/libclang_rt.builtins-little64.a"
                    break
                fi
            done
        done

        # Also install into the exported bin/../lib tree so the shipped
        # toolchain can find it.
        EXPORT_RESOURCE_LIB="$BIN_OUTPUT_DIR/../lib/clang/$CLANG_MAJOR/lib"
        for dest_dir in "$EXPORT_RESOURCE_LIB/baremetal" "$EXPORT_RESOURCE_LIB"; do
            mkdir -p "$dest_dir"
            for candidate in \
                "$BUILTINS_BUILD_DIR/libclang_rt.builtins-little64.a" \
                "$BUILTINS_BUILD_DIR/libclang_rt.builtins.a" \
                "$BUILTINS_BUILD_DIR/lib/libclang_rt.builtins-little64.a" \
                "$BUILTINS_BUILD_DIR/lib/libclang_rt.builtins.a" \
                "$BUILTINS_BUILD_DIR/lib/little64/libclang_rt.builtins.a"; do
                if [ -f "$candidate" ]; then
                    cp "$candidate" "$dest_dir/libclang_rt.builtins-little64.a"
                    echo "  ✓ Exported to $dest_dir/libclang_rt.builtins-little64.a"
                    break
                fi
            done
        done

        # Export the clang resource-directory headers so the shipped
        # toolchain can find stdint.h, stddef.h, etc.
        EXPORT_RESOURCE_INCLUDE="$BIN_OUTPUT_DIR/../lib/clang/$CLANG_MAJOR/include"
        BUILD_RESOURCE_INCLUDE="$BUILD_DIR/lib/clang/$CLANG_MAJOR/include"
        if [ -d "$BUILD_RESOURCE_INCLUDE" ]; then
            mkdir -p "$EXPORT_RESOURCE_INCLUDE"
            cp -a "$BUILD_RESOURCE_INCLUDE/." "$EXPORT_RESOURCE_INCLUDE/"
            echo "  ✓ Exported resource headers to $EXPORT_RESOURCE_INCLUDE"
        else
            echo "  ⚠ Resource headers not found at $BUILD_RESOURCE_INCLUDE"
        fi

        echo ""
        echo "✓ compiler-rt builtins build successful!"
        ;;

    clean)
        echo "Cleaning LLVM build artifacts"
        if [ -d "$BUILD_DIR" ]; then
            rm -rf "$BUILD_DIR"
            echo "Removed: $BUILD_DIR"
        fi

        BUILTINS_BUILD_DIR="$SCRIPT_DIR/build-builtins-little64"
        if [ -d "$BUILTINS_BUILD_DIR" ]; then
            rm -rf "$BUILTINS_BUILD_DIR"
            echo "Removed: $BUILTINS_BUILD_DIR"
        fi

        for tool in "${COPY_TOOLS[@]}"; do
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
        echo ""
        echo "Examples:"
        echo "  $0              # build LLVM tools"
        echo "  $0 little64     # build LLVM tools"
        echo "  $0 \"\" clean     # clean build artifacts"
        exit 1
        ;;
esac
