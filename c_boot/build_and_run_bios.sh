#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

OBJ="builddir/c_boot_bios.o"
ELF="builddir/c_boot_bios.elf"

mkdir -p builddir

compilers/bin/clang -target little64 -O0 -g -ffreestanding -Iboot -c c_boot/start.c -o "$OBJ"
compilers/bin/ld.lld "$OBJ" -o "$ELF" -T c_boot/linker_bios.ld

echo "[little-64] running BIOS image: $ELF"
./builddir/little-64 "$ELF"
