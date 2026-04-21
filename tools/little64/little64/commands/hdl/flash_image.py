#!/usr/bin/env python3

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from little64.paths import repo_root as _repo_root_cli

sys.path.insert(0, str(_repo_root_cli() / "hdl"))

from little64_cores.litex import LITTLE64_LINUX_RAM_BASE
from little64_cores.litex_linux_boot import build_litex_flash_image


def _repo_root() -> Path:
    return _repo_root_cli()


def _run(command: list[str]) -> None:
    subprocess.run(command, check=True)


def _build_stage0(stage0_source: Path, stage0_linker: Path, work_dir: Path) -> bytes:
    repo_root = _repo_root()
    compilers_bin = repo_root / 'compilers' / 'bin'
    obj_path = work_dir / 'litex_spi_boot.o'
    elf_path = work_dir / 'litex_spi_boot.elf'
    bin_path = work_dir / 'litex_spi_boot.bin'

    _run([
        str(compilers_bin / 'clang'),
        '-target', 'little64',
        '-O3',
        '-ffreestanding',
        '-fno-builtin',
        '-fomit-frame-pointer',
        '-fno-stack-protector',
        '-c',
        str(stage0_source),
        '-o',
        str(obj_path),
    ])
    _run([
        str(compilers_bin / 'ld.lld'),
        str(obj_path),
        '-o',
        str(elf_path),
        '-T',
        str(stage0_linker),
    ])
    _run([
        str(compilers_bin / 'llvm-objcopy'),
        '-O',
        'binary',
        str(elf_path),
        str(bin_path),
    ])
    return bin_path.read_bytes()


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description='Build a Little64 LiteX SPI flash image containing stage-0, Linux, and a DTB.')
    parser.add_argument('--kernel-elf', type=Path, required=True, help='Little64 Linux kernel ELF to flatten into SDRAM payload bytes.')
    parser.add_argument('--dtb', type=Path, required=True, help='Compiled DTB to copy into SDRAM before jumping to the kernel.')
    parser.add_argument('--output', type=Path, required=True, help='Flash image path to write.')
    parser.add_argument('--ram-base', type=lambda value: int(value, 0), default=LITTLE64_LINUX_RAM_BASE,
        help='Physical RAM base visible to the SoC.')
    parser.add_argument('--ram-size', type=lambda value: int(value, 0), default=0x04000000, help='Physical RAM size visible to the SoC.')
    parser.add_argument('--kernel-physical-base', type=lambda value: int(value, 0), default=LITTLE64_LINUX_RAM_BASE,
        help='Physical kernel load base expected by the current Little64 Linux port.')
    parser.add_argument('--stage0-source', type=Path, default=Path('target/c_boot/litex_spi_boot.c'),
        help='Stage-0 C source to compile into the beginning of the flash image.')
    parser.add_argument('--stage0-linker', type=Path, default=Path('target/c_boot/linker_litex_spi_boot.ld'),
        help='Linker script used for the stage-0 SPI-flash image.')
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    repo_root = _repo_root()
    output_path = args.output.resolve()
    work_dir = output_path.parent / f'{output_path.stem}.work'
    work_dir.mkdir(parents=True, exist_ok=True)

    stage0_bytes = _build_stage0((repo_root / args.stage0_source).resolve(), (repo_root / args.stage0_linker).resolve(), work_dir)
    layout = build_litex_flash_image(
        stage0_bytes=stage0_bytes,
        kernel_elf_bytes=args.kernel_elf.resolve().read_bytes(),
        dtb_bytes=args.dtb.resolve().read_bytes(),
        ram_base=args.ram_base,
        ram_size=args.ram_size,
        kernel_physical_base=args.kernel_physical_base,
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(layout.flash_image)
    return 0


def run(argv: list[str]) -> int:
    return main(argv) or 0


if __name__ == '__main__':
    raise SystemExit(main())