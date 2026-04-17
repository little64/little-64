from __future__ import annotations

import argparse
import importlib.util
from pathlib import Path

SCRIPT_PATH = Path(__file__).resolve().parents[1] / 'tools' / 'generate_litex_linux_dts.py'
spec = importlib.util.spec_from_file_location('generate_litex_linux_dts', str(SCRIPT_PATH))
generate_litex_linux_dts = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(generate_litex_linux_dts)


def test_compose_bootargs_merges_unrelated_user_args() -> None:
    default = 'console=liteuart ignore_loglevel loglevel=8'
    user = 'root=/dev/mmcblk0p1'

    composed = generate_litex_linux_dts._compose_bootargs(default, user)

    assert 'console=liteuart' in composed
    assert 'ignore_loglevel' in composed
    assert 'loglevel=8' in composed
    assert 'root=/dev/mmcblk0p1' in composed


def test_compose_bootargs_prefers_user_override() -> None:
    default = 'console=liteuart earlycon=liteuart,0x100 ignore_loglevel loglevel=8'
    user = 'console=ttyS0'

    composed = generate_litex_linux_dts._compose_bootargs(default, user)

    assert 'console=ttyS0' in composed
    assert 'console=liteuart' not in composed
    assert 'earlycon=liteuart,0x100' in composed


def test_build_default_bootargs_includes_sdcard_flag() -> None:
    args = argparse.Namespace(
        with_sdram=False,
        with_spi_flash=False,
        with_sdcard=True,
        without_timer=False,
        integrated_main_ram_size=0x04000000,
        bootargs='',
        cpu_variant='standard',
    )

    bootargs = generate_litex_linux_dts._build_default_bootargs(args, uart_region=None)

    assert bootargs == 'root=/dev/mmcblk0p2 rootwait'
