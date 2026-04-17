#!/usr/bin/env python3
import os
import pathlib
import subprocess

ROOT = pathlib.Path(__file__).resolve().parents[3]
BIN = ROOT / "compilers" / "bin"
LLVM_MC = BIN / "llvm-mc"
LD = BIN / "ld.lld"
BOOT_HELPER = ROOT / "target" / "linux_port" / "boot_direct.sh"
PYTHON_ENV = ROOT / ".venv" / "bin" / "python"

EXPECTED_STAGE0_MARKER = "stage0: entered from internal bootrom"
EXPECTED_SDRAM_INIT_MARKER = "stage0: initializing sdram"
EXPECTED_SDRAM_READY_MARKER = "stage0: sdram ready"
EXPECTED_SD_MARKER = "stage0: sdcard ready"
EXPECTED_RAM_DT_REG = "reg = <0x00000000 0x40000000 0x00000000 0x10000000>;"
EXPECTED_STAGE0_RAM_SIZE_DEFINE = "#define L64_RAM_SIZE 0x0000000010000000ULL"


def main() -> int:
    if not BOOT_HELPER.exists() or not PYTHON_ENV.exists():
        raise SystemExit(77)
    if not LLVM_MC.exists() or not LD.exists():
        raise SystemExit(77)

    builddir = ROOT / "builddir"
    builddir.mkdir(parents=True, exist_ok=True)

    asm = builddir / "test_litex_flash_boot.s"
    linker = builddir / "test_litex_flash_boot.ld"
    obj = builddir / "test_litex_flash_boot.o"
    elf = builddir / "test_litex_flash_boot.elf"

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
        "  . = 0x100000;\n"
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

    env = os.environ.copy()
    env["LITTLE64_PYTHON"] = str(PYTHON_ENV)
    env["LITTLE64_SKIP_LITEX_KERNEL_CONFIG_CHECK"] = "1"

    res = subprocess.run(
        [
            str(BOOT_HELPER),
            "--machine=litex",
            "--mode=smoke",
            "--max-cycles",
            "2000000",
            str(elf),
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=60,
        env=env,
    )

    if (
        EXPECTED_STAGE0_MARKER not in res.stdout
        or EXPECTED_SDRAM_INIT_MARKER not in res.stdout
        or EXPECTED_SDRAM_READY_MARKER not in res.stdout
        or EXPECTED_SD_MARKER not in res.stdout
    ):
        raise RuntimeError(
            "Missing LiteX SDRAM bootrom stage-0 output in boot stdout:\n"
            f"{res.stdout}"
        )

    dts_path = ROOT / "builddir" / "boot-direct-litex" / "little64-litex-sim.dts"
    regs_path = ROOT / "builddir" / "boot-direct-litex" / "little64-sd-stage0-bootrom.work" / "litex_sd_boot_regs.h"

    dts_text = dts_path.read_text(encoding="utf-8")
    regs_text = regs_path.read_text(encoding="utf-8")

    if EXPECTED_RAM_DT_REG not in dts_text:
        raise RuntimeError(
            "LiteX boot helper generated an unexpected RAM DT region:\n"
            f"{dts_text}"
        )

    if EXPECTED_STAGE0_RAM_SIZE_DEFINE not in regs_text:
        raise RuntimeError(
            "LiteX stage-0 header did not pick up the Arty-sized RAM window:\n"
            f"{regs_text}"
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())