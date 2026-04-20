from __future__ import annotations

import argparse
import importlib.util
from pathlib import Path

from little64.litex import LITTLE64_LITEX_BOOTROM_SIZE


def _load_smoke_wrapper_module():
    module_path = Path(__file__).resolve().parents[1] / 'tools' / 'run_litex_linux_boot_smoke.py'
    spec = importlib.util.spec_from_file_location('little64_run_litex_linux_boot_smoke', module_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_default_required_markers_use_linux_version_banner() -> None:
    smoke_wrapper = _load_smoke_wrapper_module()

    assert smoke_wrapper.DEFAULT_REQUIRED_MARKERS == [smoke_wrapper.LINUX_VERSION_MARKER]
    assert smoke_wrapper.DEFAULT_SD_REQUIRED_MARKERS == [smoke_wrapper.LINUX_VERSION_MARKER]


def test_resolved_output_dir_uses_sdcard_specific_build_dir() -> None:
    smoke_wrapper = _load_smoke_wrapper_module()
    args = argparse.Namespace(with_sdcard=True, output_dir=smoke_wrapper.DEFAULT_OUTPUT_DIR)

    assert smoke_wrapper._resolved_output_dir(args) == smoke_wrapper.DEFAULT_SD_OUTPUT_DIR


def test_resolve_required_markers_uses_linux_banner_by_default() -> None:
    smoke_wrapper = _load_smoke_wrapper_module()
    args = argparse.Namespace(with_sdcard=True, require=[], extra_require=[])

    assert smoke_wrapper._resolve_required_markers(args) == [smoke_wrapper.LINUX_VERSION_MARKER]


def test_resolve_required_markers_appends_extra_requirements_without_duplicates() -> None:
    smoke_wrapper = _load_smoke_wrapper_module()
    args = argparse.Namespace(
        with_sdcard=False,
        require=[],
        extra_require=[smoke_wrapper.LINUX_VERSION_MARKER, 'little64-timer: clocksource + clockevent @ 1 GHz'],
    )

    assert smoke_wrapper._resolve_required_markers(args) == [
        smoke_wrapper.LINUX_VERSION_MARKER,
        'little64-timer: clocksource + clockevent @ 1 GHz',
    ]


def test_resolve_required_markers_allows_exact_override() -> None:
    smoke_wrapper = _load_smoke_wrapper_module()
    args = argparse.Namespace(with_sdcard=False, require=['stage0: handing off to kernel'], extra_require=[])

    assert smoke_wrapper._resolve_required_markers(args) == ['stage0: handing off to kernel']


def test_create_soc_keeps_full_sim_bootrom_rom_size(tmp_path: Path) -> None:
    smoke_wrapper = _load_smoke_wrapper_module()
    flash_image = tmp_path / 'bootrom.bin'
    flash_image.write_bytes(b'\x00' * LITTLE64_LITEX_BOOTROM_SIZE)

    args = argparse.Namespace(
        cpu_variant='standard-v3',
        integrated_main_ram_size=0,
        with_sdram=False,
        with_sdcard=True,
        with_timer=True,
    )

    soc = smoke_wrapper._create_soc(args, tmp_path, flash_image, None)

    assert soc.bus.regions['rom'].size == LITTLE64_LITEX_BOOTROM_SIZE


def test_create_soc_without_sdcard_uses_spiflash_window_for_standard_v3(tmp_path: Path) -> None:
    smoke_wrapper = _load_smoke_wrapper_module()
    flash_image = tmp_path / 'flash.bin'
    flash_image.write_bytes(b'\x00' * LITTLE64_LITEX_BOOTROM_SIZE)

    args = argparse.Namespace(
        cpu_variant='standard-v3',
        integrated_main_ram_size=0x04000000,
        with_sdram=False,
        with_sdcard=False,
        with_timer=True,
    )

    soc = smoke_wrapper._create_soc(args, tmp_path, flash_image, None)

    assert 'rom' not in soc.bus.regions
    assert soc.bus.regions['spiflash'].origin == 0x20000000
    assert soc.bus.regions['sram'].origin == 0x10000000


def test_format_bus_region_summary_handles_missing_rom_region(tmp_path: Path) -> None:
    smoke_wrapper = _load_smoke_wrapper_module()
    flash_image = tmp_path / 'flash.bin'
    flash_image.write_bytes(b'\x00' * LITTLE64_LITEX_BOOTROM_SIZE)

    args = argparse.Namespace(
        cpu_variant='standard-v3',
        integrated_main_ram_size=0x04000000,
        with_sdram=False,
        with_sdcard=False,
        with_timer=True,
    )

    soc = smoke_wrapper._create_soc(args, tmp_path, flash_image, None)
    summary = smoke_wrapper._format_bus_region_summary(soc)

    assert 'rom=absent' in summary
    assert 'spiflash=0x1000000@0x20000000' in summary
    assert 'sram=0x4000@0x10000000' in summary


def test_load_rom_init_words_uses_64bit_little_endian_words(tmp_path: Path) -> None:
    smoke_wrapper = _load_smoke_wrapper_module()
    flash_image = tmp_path / 'bootrom.bin'
    flash_image.write_bytes(bytes(range(256)) * (LITTLE64_LITEX_BOOTROM_SIZE // 256))

    rom_words = smoke_wrapper._load_rom_init_words(flash_image)

    assert len(rom_words) == LITTLE64_LITEX_BOOTROM_SIZE // 8
    assert rom_words[0] == 0x0706050403020100


def test_stage_sd_image_for_run_uses_symlink_when_possible(tmp_path: Path) -> None:
    smoke_wrapper = _load_smoke_wrapper_module()
    gateware_dir = tmp_path / 'gateware'
    gateware_dir.mkdir()
    sd_image = tmp_path / 'little64-linux-sdcard.img'
    sd_image.write_bytes(b'test')

    smoke_wrapper._stage_sd_image_for_run(gateware_dir=gateware_dir, sd_image_path=sd_image)

    staged_image = gateware_dir / 'sdcard.img'
    assert staged_image.is_symlink()
    assert staged_image.resolve() == sd_image.resolve()