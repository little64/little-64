#!/usr/bin/env python3

from __future__ import annotations

import argparse
from pathlib import Path

from little64.build_support import Stage0CompileUnit, build_stage0_binary
from little64.hdl_bridge import ensure_hdl_path
from little64.paths import repo_root as _repo_root_cli

ensure_hdl_path()

from little64_cores.litex import LITTLE64_LINUX_RAM_BASE
from little64_cores.litex_linux_boot import build_litex_flash_image


def _repo_root() -> Path:
    return _repo_root_cli()


def _build_stage0(stage0_source: Path, stage0_linker: Path, work_dir: Path) -> bytes:
    repo_root = _repo_root()
    return build_stage0_binary(
        compile_units=[
            Stage0CompileUnit((repo_root / stage0_source).resolve(), 'litex_spi_boot.o'),
        ],
        linker_script=(repo_root / stage0_linker).resolve(),
        work_dir=work_dir,
        output_stem='litex_spi_boot',
        optimization='-O3',
    )


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

    stage0_bytes = _build_stage0(args.stage0_source, args.stage0_linker, work_dir)
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