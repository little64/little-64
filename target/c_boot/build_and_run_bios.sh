#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT_DIR"

OBJ="builddir/c_boot_bios.o"
ELF="builddir/c_boot_bios.elf"

mkdir -p builddir

compilers/bin/clang -target little64 -O0 -gdwarf-4 -fno-omit-frame-pointer -funwind-tables -fasynchronous-unwind-tables -fforce-dwarf-frame -ffreestanding -Ihost/boot -c target/c_boot/start.c -o "$OBJ"
compilers/bin/ld.lld "$OBJ" -o "$ELF" -T target/c_boot/linker_bios.ld

echo "[little-64] running BIOS image: $ELF"
./builddir/little-64 "$ELF"
