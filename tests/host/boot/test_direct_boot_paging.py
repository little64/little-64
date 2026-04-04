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

    asm = builddir / "test_direct_boot_highhalf.s"
    linker = builddir / "test_direct_boot_highhalf.ld"
    obj = builddir / "test_direct_boot_highhalf.o"
    elf = builddir / "test_direct_boot_highhalf.elf"

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
        "  . = 0xFFFFFFC000000000;\n"
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
