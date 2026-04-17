#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, cast


SCRIPT_PATH = Path(__file__).resolve()
HDL_ROOT = SCRIPT_PATH.parents[1]
REPO_ROOT = SCRIPT_PATH.parents[2]
CACHE_VERSION = 1


def _cache_path_for_output(output_path: Path) -> Path:
    return output_path.with_name(output_path.name + '.cache.json')


def _dependency_paths() -> list[Path]:
    return [SCRIPT_PATH, *sorted((HDL_ROOT / 'little64').rglob('*.py'))]


FLAG_BOOTARGS: dict[str, str] = {
    'with_sdcard': 'root=/dev/mmcblk0p2 rootwait',
}


def _build_cache_state(args: argparse.Namespace) -> dict[str, object]:
    dependencies: list[dict[str, object]] = []
    for dependency in _dependency_paths():
        stat = dependency.stat()
        dependencies.append({
            'path': str(dependency.relative_to(REPO_ROOT)),
            'mtime_ns': stat.st_mtime_ns,
            'size': stat.st_size,
        })
    return {
        'version': CACHE_VERSION,
        'arguments': {
            'with_sdram': args.with_sdram,
            'with_spi_flash': args.with_spi_flash,
            'with_sdcard': args.with_sdcard,
            'without_timer': args.without_timer,
            'integrated_main_ram_size': args.integrated_main_ram_size,
            'ram_size': args.ram_size,
            'bootargs': args.bootargs,
            'cpu_variant': args.cpu_variant,
            'litex_target': args.litex_target,
            'boot_source': args.boot_source,
        },
        'dependencies': dependencies,
    }


def _split_bootargs(bootargs: str) -> list[str]:
    return bootargs.split()


def _bootarg_name(token: str) -> str:
    return token.split('=', 1)[0]


def _compose_bootargs(default_bootargs: str | None, bootargs: str) -> str | None:
    if not default_bootargs:
        return bootargs or None
    if not bootargs.strip():
        return default_bootargs

    user_tokens = _split_bootargs(bootargs)
    default_tokens = _split_bootargs(default_bootargs)
    user_names = {_bootarg_name(token) for token in user_tokens}
    merged_tokens = [token for token in default_tokens if _bootarg_name(token) not in user_names]
    merged_tokens.extend(user_tokens)
    return ' '.join(merged_tokens)


def _build_default_bootargs(args: argparse.Namespace, uart_region: Any) -> str | None:
    bootargs: list[str] = []
    if uart_region is not None:
        bootargs.append(
            f'console=liteuart earlycon=liteuart,0x{uart_region.origin:x} ignore_loglevel loglevel=8'
        )
    for flag, extra_arguments in FLAG_BOOTARGS.items():
        if getattr(args, flag, False):
            bootargs.append(extra_arguments)
    return ' '.join(bootargs) if bootargs else None


def _load_cache_state(cache_path: Path) -> dict[str, object] | None:
    if not cache_path.exists():
        return None
    try:
        loaded = json.loads(cache_path.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError):
        return None
    return cast(dict[str, object], loaded) if isinstance(loaded, dict) else None


def _write_cache_state(cache_path: Path, state: dict[str, object]) -> None:
    cache_path.write_text(json.dumps(state, indent=2, sort_keys=True) + '\n', encoding='utf-8')


def _write_text_if_changed(output_path: Path, text: str) -> None:
    if output_path.exists():
        try:
            existing = output_path.read_text(encoding='utf-8')
        except OSError:
            existing = None
        if existing == text:
            return
    output_path.write_text(text, encoding='utf-8')


def _generate_dts_text(args: argparse.Namespace, output_path: Path) -> str:
    if str(HDL_ROOT) not in sys.path:
        sys.path.insert(0, str(HDL_ROOT))

    from little64.litex_soc import Little64LiteXSimSoC, generate_linux_dts

    soc = Little64LiteXSimSoC(
        cpu_variant=args.cpu_variant,
        with_sdram=args.with_sdram,
        with_spi_flash=args.with_spi_flash,
        with_sdcard=args.with_sdcard,
        with_timer=not args.without_timer,
        spi_flash_image_path=args.spi_flash_image,
        integrated_main_ram_size=0 if args.with_sdram else args.integrated_main_ram_size,
        main_ram_size=args.ram_size,
        litex_target=args.litex_target,
        boot_source=args.boot_source,
    )
    soc.platform.output_dir = str(output_path.parent / 'litex-sim-build')
    csr = cast(Any, soc.csr)
    csr_regions = cast(dict[str, Any], csr.regions)
    uart_region = csr_regions.get('uart')
    default_bootargs = _build_default_bootargs(args, uart_region)
    bootargs = _compose_bootargs(default_bootargs, args.bootargs)
    return generate_linux_dts(soc, bootargs=bootargs)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    if str(HDL_ROOT) not in sys.path:
        sys.path.insert(0, str(HDL_ROOT))

    from little64.litex import LITTLE64_LITEX_BOOT_SOURCES, LITTLE64_LITEX_TARGET_NAMES

    parser = argparse.ArgumentParser(description='Generate a Linux DTS for the Little64 LiteX simulation SoC.')
    parser.add_argument('--output', type=Path, required=True, help='Path to the DTS file to write.')
    parser.add_argument('--with-sdram', action='store_true', help='Model main RAM with LiteDRAM instead of integrated RAM.')
    parser.add_argument('--with-spi-flash', action='store_true', help='Expose memory-mapped SPI flash in the generated SoC/DTS.')
    parser.add_argument('--with-sdcard', action='store_true', help='Expose a LiteSDCard controller in the generated SoC/DTS.')
    parser.add_argument('--without-timer', action='store_true', help='Disable the Little64 Linux timer block and DT node.')
    parser.add_argument('--spi-flash-image', type=Path, help='Optional flash image binary to preload into the SPI flash model.')
    parser.add_argument('--integrated-main-ram-size', type=lambda value: int(value, 0), default=0x04000000,
        help='Integrated main RAM size to use when SDRAM is disabled.')
    parser.add_argument('--ram-size', type=lambda value: int(value, 0), default=None,
        help='Main RAM size to advertise when SDRAM is enabled. Defaults to the selected LiteX target contract.')
    parser.add_argument(
        '--bootargs',
        default='',
        help=(
            'Optional bootargs string for the chosen node. When not empty, it is merged '
            'with automatically generated hardware defaults, and user-provided values '
            'override matching default kernel arguments.'
        ),
    )
    parser.add_argument(
        '--cpu-variant',
        default='standard',
        help='LiteX CPU variant to model when instantiating the simulation SoC.',
    )
    parser.add_argument(
        '--litex-target',
        choices=LITTLE64_LITEX_TARGET_NAMES,
        default='sim-flash',
        help='Named LiteX target descriptor used for SoC metadata and the default boot source.',
    )
    parser.add_argument(
        '--boot-source',
        choices=LITTLE64_LITEX_BOOT_SOURCES,
        default=None,
        help='Override the LiteX target default boot source.',
    )
    parser.add_argument('--force', action='store_true', help='Bypass the generator cache and rebuild the DTS unconditionally.')
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    output_path = args.output.resolve()

    output_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path = _cache_path_for_output(output_path)
    cache_state = _build_cache_state(args)
    if not args.force and output_path.exists() and _load_cache_state(cache_path) == cache_state:
        return 0

    dts_text = _generate_dts_text(args, output_path)
    _write_text_if_changed(output_path, dts_text)
    _write_cache_state(cache_path, cache_state)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())