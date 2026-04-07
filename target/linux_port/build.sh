SCRIPT_FOLDER=$(dirname "$(readlink -f "$0")")
cd "$SCRIPT_FOLDER" || exit 1
COMPILER_BIN=$SCRIPT_FOLDER/../../compilers/bin
CC_CMD="$COMPILER_BIN/clang"

# Get the target we want if arguments are provided, else default to vmlinux
if [ $# -eq 0 ]; then
    TARGET="vmlinux"
else
    TARGET="$1"
    shift
fi

# Compose make args and default to all cores when -j is not provided
MAKE_ARGS=("$@")
if [[ " $* " != *" -j"* ]]; then
    MAKE_ARGS=("-j$(nproc)" "${MAKE_ARGS[@]}")
fi

# Enable line debug info by default, unless caller explicitly manages debug config.
DEBUG_KCONFIG_ARGS=()
if [[ "$*" != *"CONFIG_DEBUG_INFO="* && \
      "$*" != *"CONFIG_DEBUG_INFO_NONE="* && \
      "$*" != *"CONFIG_DEBUG_INFO_DWARF"* ]]; then
    DEBUG_KCONFIG_ARGS=(
        "CONFIG_DEBUG_INFO=y"
        "CONFIG_DEBUG_INFO_NONE=n"
        "CONFIG_DEBUG_INFO_DWARF_TOOLCHAIN_DEFAULT=y"
    )
fi

echo "Building Linux kernel for Little64"
if [ "${LITTLE64_CLANG_GUARD:-0}" = "1" ]; then
    CC_CMD="$SCRIPT_FOLDER/clang_guard.sh"
    export LITTLE64_REAL_CLANG="$COMPILER_BIN/clang"
    echo "Using compiler: $CC_CMD (guarded)"
    echo "Guard timeout: ${LITTLE64_CLANG_TIMEOUT_SEC:-120}s"
    echo "Guard max virtual memory: ${LITTLE64_CLANG_MAX_VMEM_KB:-10485760} KB"
else
    echo "Using compiler: $CC_CMD"
fi
echo "Target: $TARGET"
echo "-----------------------------------"

nice -n 19 make -C linux ARCH=little64 \
    LLVM=1 \
    CC="$CC_CMD" \
    LD="$COMPILER_BIN/ld.lld" \
    AR="$COMPILER_BIN/llvm-ar" \
    OBJCOPY="$COMPILER_BIN/llvm-objcopy" \
    O=$SCRIPT_FOLDER/build \
    HOSTCC=gcc \
    HOSTCXX=g++ \
    "${MAKE_ARGS[@]}" \
    "${DEBUG_KCONFIG_ARGS[@]}" \
    $TARGET

