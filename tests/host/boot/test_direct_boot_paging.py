#!/usr/bin/env python3
import pathlib
import subprocess

ROOT = pathlib.Path(__file__).resolve().parents[3]
BIN = ROOT / "compilers" / "bin"
LLVM_MC = BIN / "llvm-mc"
LD = BIN / "ld.lld"
EMU = ROOT / "builddir" / "little-64"


def main() -> int:
    builddir = ROOT / "builddir"
    builddir.mkdir(parents=True, exist_ok=True)

    # Note: renamed from test_direct_boot_highhalf to test_direct_boot_physical
    # The direct boot mode now uses the LiteX SDRAM contract, so the ELF must
    # link at the physical RAM base (0x40000000) not a virtual address.
    asm = builddir / "test_direct_boot_physical.s"
    linker = builddir / "test_direct_boot_physical.ld"
    obj = builddir / "test_direct_boot_physical.o"
    elf = builddir / "test_direct_boot_physical.elf"

    asm.write_text(
        ".text\n"
        ".global _start\n"
        "_start:\n"
        "  STOP\n",
        encoding="utf-8",
    )

    linker.write_text(
        "ENTRY(_start)\n"
        "SECTIONS\n"
        "{\n"
        "  . = 0x40000000;\n"
        "  .text : { *(.text*) }\n"
        "  .rodata : { *(.rodata*) }\n"
        "  .data : { *(.data*) }\n"
        "  .bss : { *(.bss*) *(COMMON) }\n"
        "}\n",
        encoding="utf-8",
    )

    subprocess.run(
        [
            str(LLVM_MC),
            "-triple=little64",
            "-filetype=obj",
            str(asm),
            "-o",
            str(obj),
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    subprocess.run(
        [
            str(LD),
            str(obj),
            "-o",
            str(elf),
            "-T",
            str(linker),
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    subprocess.run(
        [str(EMU), "--boot-mode=direct", str(elf)],
        check=True,
        capture_output=True,
        text=True,
        timeout=15,
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
