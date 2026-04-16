#!/usr/bin/env python3

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from little64.litex_soc import Little64LiteXSimSoC, generate_linux_dts


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description='Generate a Linux DTS for the Little64 LiteX simulation SoC.')
    parser.add_argument('--output', type=Path, required=True, help='Path to the DTS file to write.')
    parser.add_argument('--with-sdram', action='store_true', help='Model main RAM with LiteDRAM instead of integrated RAM.')
    parser.add_argument('--with-spi-flash', action='store_true', help='Expose memory-mapped SPI flash in the generated SoC/DTS.')
    parser.add_argument('--without-timer', action='store_true', help='Disable the Little64 Linux timer block and DT node.')
    parser.add_argument('--spi-flash-image', type=Path, help='Optional flash image binary to preload into the SPI flash model.')
    parser.add_argument('--integrated-main-ram-size', type=lambda value: int(value, 0), default=0x04000000,
        help='Integrated main RAM size to use when SDRAM is disabled.')
    parser.add_argument('--bootargs', default='', help='Optional bootargs string for the chosen node.')
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    output_path = args.output.resolve()

    soc = Little64LiteXSimSoC(
        with_sdram=args.with_sdram,
        with_spi_flash=args.with_spi_flash,
        with_timer=not args.without_timer,
        spi_flash_image_path=args.spi_flash_image,
        integrated_main_ram_size=0 if args.with_sdram else args.integrated_main_ram_size,
    )
    soc.platform.output_dir = str(output_path.parent / 'litex-sim-build')
    dts_text = generate_linux_dts(soc, bootargs=args.bootargs or None)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(dts_text, encoding='utf-8')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())