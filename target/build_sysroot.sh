#!/usr/bin/env bash
# target/build_sysroot.sh — Build the Little64 Linux sysroot.
#
# Installs kernel UAPI headers, builds mlibc, and populates target/sysroot/
# with everything needed to compile and link Little64 Linux userspace programs.
#
# Usage:
#   target/build_sysroot.sh          # full build + install
#   target/build_sysroot.sh clean    # remove build artifacts and sysroot
#   target/build_sysroot.sh rebuild  # clean + full build
#
# Prerequisites:
#   - LLVM toolchain built: (cd compilers && ./build.sh llvm)
#   - Linux kernel source at target/linux_port/linux/
#   - mlibc source at target/mlibc/
set -euo pipefail

SCRIPT_DIR=$(dirname "$(readlink -f "$0")")
REPO_ROOT=$(readlink -f "$SCRIPT_DIR/..")
TOOLS_DIR="$REPO_ROOT/compilers/bin"
SYSROOT="$REPO_ROOT/target/sysroot"

MLIBC_SRC="$REPO_ROOT/target/mlibc"
MLIBC_BUILD="$MLIBC_SRC/build-little64"
LINUX_SRC="$REPO_ROOT/target/linux_port/linux"

CLANG_VERSION=23
COMPILER_RT_LIB="$REPO_ROOT/compilers/lib/clang/$CLANG_VERSION/lib/libclang_rt.builtins-little64.a"

# ---------- helpers --------------------------------------------------------

die() { printf 'error: %s\n' "$1" >&2; exit 1; }

check_toolchain() {
    [[ -x "$TOOLS_DIR/clang" ]] || die "clang not found at $TOOLS_DIR/clang — build the toolchain first"
    [[ -x "$TOOLS_DIR/ld.lld" ]] || die "ld.lld not found at $TOOLS_DIR/ld.lld — build the toolchain first"
    [[ -x "$TOOLS_DIR/llvm-ar" ]] || die "llvm-ar not found"
    [[ -x "$TOOLS_DIR/llvm-strip" ]] || die "llvm-strip not found"
}

# ---------- wrapper scripts ------------------------------------------------
# These are deterministic and cheap to recreate, so always regenerate.

WRAP_DIR="$MLIBC_BUILD/.wrappers"

write_wrappers() {
    mkdir -p "$WRAP_DIR"

    cat > "$WRAP_DIR/clang-wrapper" <<'WRAPPER'
#!/bin/bash
TOOLCHAIN_BIN="@@TOOLS_DIR@@"

# Handle linker version probes.
for arg in "$@"; do
  case "$arg" in
    -Wl,--version) exec "$TOOLCHAIN_BIN/ld.lld" --version ;;
  esac
done

# Detect link-only steps (-shared without -c/-S/-E).
is_link=false is_compile=false is_shared=false
for arg in "$@"; do
  case "$arg" in
    -c|-S|-E) is_compile=true ;;
    -shared)  is_link=true; is_shared=true ;;
  esac
done

if $is_link && ! $is_compile; then
  lld_args=()
  for arg in "$@"; do
    case "$arg" in
      -Wl,*)
        IFS=',' read -ra parts <<< "${arg#-Wl,}"
        for p in "${parts[@]}"; do [[ -n "$p" ]] && lld_args+=("$p"); done
        ;;
      -nostdlib|-fPIC|-target|-target=*) ;;
      little64) ;;
      *) lld_args+=("$arg") ;;
    esac
  done
  $is_shared && lld_args+=("-z" "notext")
  exec "$TOOLCHAIN_BIN/ld.lld" "${lld_args[@]}"
fi

exec "$TOOLCHAIN_BIN/clang" -target little64 "$@"
WRAPPER
    sed -i "s|@@TOOLS_DIR@@|$TOOLS_DIR|g" "$WRAP_DIR/clang-wrapper"
    chmod +x "$WRAP_DIR/clang-wrapper"

    cat > "$WRAP_DIR/clangxx-wrapper" <<'WRAPPER'
#!/bin/bash
TOOLCHAIN_BIN="@@TOOLS_DIR@@"

for arg in "$@"; do
  case "$arg" in
    -Wl,--version) exec "$TOOLCHAIN_BIN/ld.lld" --version ;;
  esac
done

is_link=false is_compile=false is_shared=false
for arg in "$@"; do
  case "$arg" in
    -c|-S|-E) is_compile=true ;;
    -shared)  is_link=true; is_shared=true ;;
  esac
done

if $is_link && ! $is_compile; then
  lld_args=()
  for arg in "$@"; do
    case "$arg" in
      -Wl,*)
        IFS=',' read -ra parts <<< "${arg#-Wl,}"
        for p in "${parts[@]}"; do [[ -n "$p" ]] && lld_args+=("$p"); done
        ;;
      -nostdlib|-fPIC|-target|-target=*) ;;
      little64) ;;
      *) lld_args+=("$arg") ;;
    esac
  done
  $is_shared && lld_args+=("-z" "notext")
  exec "$TOOLCHAIN_BIN/ld.lld" "${lld_args[@]}"
fi

exec "$TOOLCHAIN_BIN/clang++" -target little64 "$@"
WRAPPER
    sed -i "s|@@TOOLS_DIR@@|$TOOLS_DIR|g" "$WRAP_DIR/clangxx-wrapper"
    chmod +x "$WRAP_DIR/clangxx-wrapper"
}

# ---------- cross / native meson files ------------------------------------

write_meson_files() {
    mkdir -p "$WRAP_DIR"

    cat > "$WRAP_DIR/cross.ini" <<EOF
[properties]
skip_sanity_check = true

[binaries]
c = '$WRAP_DIR/clang-wrapper'
cpp = '$WRAP_DIR/clangxx-wrapper'
ar = '$TOOLS_DIR/llvm-ar'
strip = '$TOOLS_DIR/llvm-strip'
ld = '$TOOLS_DIR/ld.lld'

[built-in options]
c_args = ['-ffreestanding', '-D_GNU_SOURCE']
cpp_args = ['-ffreestanding', '-D_GNU_SOURCE']
c_link_args = ['-z', 'notext']
cpp_link_args = ['-z', 'notext']
cpp_std = 'c++23'

[host_machine]
system = 'linux'
cpu_family = 'little64'
cpu = 'little64'
endian = 'little'
EOF

    cat > "$WRAP_DIR/native.ini" <<EOF
[binaries]
c = '/usr/bin/gcc'
cpp = '/usr/bin/g++'
ar = '/usr/bin/ar'
strip = '/usr/bin/strip'
EOF
}

# ---------- kernel UAPI headers -------------------------------------------

install_kernel_headers() {
    [[ -d "$LINUX_SRC" ]] || die "Linux kernel source not found at $LINUX_SRC"

    echo "[sysroot] Installing kernel UAPI headers …"

    local build_dir
    build_dir=$(mktemp -d)
    trap "rm -rf '$build_dir'" RETURN

    make -C "$LINUX_SRC" \
        ARCH=little64 LLVM=1 \
        CC="$TOOLS_DIR/clang" \
        LD="$TOOLS_DIR/ld.lld" \
        AR="$TOOLS_DIR/llvm-ar" \
        OBJCOPY="$TOOLS_DIR/llvm-objcopy" \
        HOSTCC=gcc HOSTCXX=g++ \
        O="$build_dir" \
        INSTALL_HDR_PATH="$SYSROOT/usr" \
        headers_install \
        -j"$(nproc)" >/dev/null 2>&1

    echo "[sysroot] Kernel headers installed."
}

# ---------- mlibc ----------------------------------------------------------

configure_mlibc() {
    echo "[sysroot] Configuring mlibc …"

    meson setup "$MLIBC_BUILD" "$MLIBC_SRC" \
        --cross-file "$WRAP_DIR/cross.ini" \
        --native-file "$WRAP_DIR/native.ini" \
        -Ddefault_library=both \
        -Dlinux_kernel_headers="$SYSROOT/usr/include" \
        -Dbuild_tests=false \
        -Dprefix=/usr \
        --reconfigure 2>/dev/null || \
    meson setup "$MLIBC_BUILD" "$MLIBC_SRC" \
        --cross-file "$WRAP_DIR/cross.ini" \
        --native-file "$WRAP_DIR/native.ini" \
        -Ddefault_library=both \
        -Dlinux_kernel_headers="$SYSROOT/usr/include" \
        -Dbuild_tests=false \
        -Dprefix=/usr

    echo "[sysroot] mlibc configured."
}

build_mlibc() {
    echo "[sysroot] Building mlibc …"
    ninja -C "$MLIBC_BUILD" -j"$(nproc)"
    echo "[sysroot] mlibc built."
}

install_mlibc() {
    echo "[sysroot] Installing mlibc to $SYSROOT …"
    DESTDIR="$SYSROOT" ninja -C "$MLIBC_BUILD" install
    echo "[sysroot] mlibc installed."
}

# ---------- compiler-rt builtins ------------------------------------------

install_compiler_rt() {
    if [[ ! -f "$COMPILER_RT_LIB" ]]; then
        echo "[sysroot] warning: compiler-rt builtins not found at $COMPILER_RT_LIB — skipping"
        return
    fi
    echo "[sysroot] Installing compiler-rt builtins …"
    cp "$COMPILER_RT_LIB" "$SYSROOT/usr/lib/"
    echo "[sysroot] compiler-rt builtins installed."
}

# ---------- main -----------------------------------------------------------

usage() {
    cat <<'EOF'
Usage: target/build_sysroot.sh [clean | rebuild]

Build the Little64 Linux sysroot (target/sysroot/).

Targets:
  (default)   Build kernel headers + mlibc + compiler-rt, install to sysroot
  clean       Remove the sysroot and mlibc build directory
  rebuild     Clean then build

Prerequisites:
  - LLVM toolchain: (cd compilers && ./build.sh llvm)
  - Linux kernel source at target/linux_port/linux/
  - mlibc source at target/mlibc/
EOF
}

do_clean() {
    echo "[sysroot] Cleaning …"
    rm -rf "$SYSROOT" "$MLIBC_BUILD"
    echo "[sysroot] Clean."
}

do_build() {
    check_toolchain
    mkdir -p "$SYSROOT/usr/lib" "$SYSROOT/usr/include"

    write_wrappers
    write_meson_files

    install_kernel_headers
    configure_mlibc
    build_mlibc
    install_mlibc
    install_compiler_rt

    echo ""
    echo "[sysroot] Complete.  Sysroot at: $SYSROOT"
    echo ""
    echo "  Compile:  $TOOLS_DIR/clang -target little64 \\"
    echo "              --sysroot=$SYSROOT \\"
    echo "              -isystem $SYSROOT/usr/include \\"
    echo "              -c -o out.o src.c"
    echo ""
    echo "  Link (dynamic):  $TOOLS_DIR/ld.lld \\"
    echo "              $SYSROOT/usr/lib/Scrt1.o $SYSROOT/usr/lib/crti.o out.o \\"
    echo "              -L $SYSROOT/usr/lib -lc \\"
    echo "              -dynamic-linker /usr/lib/ld.so \\"
    echo "              $SYSROOT/usr/lib/crtn.o -o binary"
    echo ""
    echo "  Link (static):  $TOOLS_DIR/ld.lld -static \\"
    echo "              $SYSROOT/usr/lib/crt1.o $SYSROOT/usr/lib/crti.o out.o \\"
    echo "              -L $SYSROOT/usr/lib -lc \\"
    echo "              $SYSROOT/usr/lib/libclang_rt.builtins-little64.a \\"
    echo "              $SYSROOT/usr/lib/crtn.o -o binary"
}

case "${1:-}" in
    "")       do_build ;;
    clean)    do_clean ;;
    rebuild)  do_clean; do_build ;;
    -h|--help) usage ;;
    *)        echo "error: unknown argument: $1" >&2; usage >&2; exit 1 ;;
esac
