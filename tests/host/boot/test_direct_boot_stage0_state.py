#!/usr/bin/env python3
import pathlib
import re
import subprocess

ROOT = pathlib.Path(__file__).resolve().parents[3]
BIN = ROOT / "compilers" / "bin"
LLVM_MC = BIN / "llvm-mc"
LD = BIN / "ld.lld"
EMU = ROOT / "builddir" / "little-64"


def _parse_register(stderr_text: str, name: str) -> int:
    pattern = rf"^\s+{name}\s+=\s+0x([0-9a-fA-F]+)$"
    for line in stderr_text.splitlines():
        match = re.match(pattern, line)
        if match:
            return int(match.group(1), 16)
    raise RuntimeError(f"missing register dump line for {name}:\n{stderr_text}")


def main() -> int:
    builddir = ROOT / "builddir"
    builddir.mkdir(parents=True, exist_ok=True)

    asm = builddir / "test_direct_stage0_state.s"
    linker = builddir / "test_direct_stage0_state.ld"
    obj = builddir / "test_direct_stage0_state.o"
    elf = builddir / "test_direct_stage0_state.elf"
    dtb = builddir / "test_direct_stage0_state.dtb"

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

    dtb.write_bytes(bytes(range(64)))

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

    result = subprocess.run(
        [
            str(EMU),
            "--boot-mode=direct",
            f"--direct-dtb={dtb}",
            "--direct-stack-reserve-bytes=512",
            "--final-registers",
            str(elf),
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=15,
    )

    r1 = _parse_register(result.stderr, "R1")
    r13 = _parse_register(result.stderr, "R13")
    r15 = _parse_register(result.stderr, "R15")

    expected_dtb = 0x40000000 + 31 * 4096
    expected_sp = 0x40000000 + 0x10000000 - 512 - 8
    expected_pc = 0x40000002

    if r1 != expected_dtb:
        raise RuntimeError(f"unexpected R1 DTB pointer: got 0x{r1:x}, expected 0x{expected_dtb:x}\n{result.stderr}")
    if r13 != expected_sp:
        raise RuntimeError(f"unexpected R13 stack pointer: got 0x{r13:x}, expected 0x{expected_sp:x}\n{result.stderr}")
    if r15 != expected_pc:
        raise RuntimeError(f"unexpected R15 entry: got 0x{r15:x}, expected 0x{expected_pc:x}\n{result.stderr}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
