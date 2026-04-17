from __future__ import annotations

import importlib.util
import os
import struct
from pathlib import Path

import pytest

from little64.config import Little64CoreConfig
from little64.litex import (
    LITTLE64_LITEX_BOOTROM_MAIN_RAM_BASE,
    LITTLE64_LITEX_BOOTROM_SIZE,
    LITTLE64_LITEX_BOOT_SOURCE_BOOTROM,
    LITTLE64_LITEX_BOOT_SOURCE_SPIFLASH,
    LITTLE64_LITEX_FLASH_BOOT_HEADER_OFFSET,
    LITTLE64_LITEX_TARGET_CONFIGS,
    Little64LiteXProfile,
    Little64LiteXShim,
    Little64LiteXTop,
    emit_litex_cpu_verilog,
    litex_mem_map_for_target,
    normalize_litex_boot_source,
    resolve_litex_target,
)
from little64.litex_sdcard import EMULATOR_VERILOG_FILENAMES, _resolve_emulator_verilog_dir
from little64.litex_cpu import Little64, Little64WishboneDataBridge, ensure_litex_llvm_toolchain_wrappers, register_little64_with_litex
from little64.litex_linux_boot import (
    FLASH_BOOT_HEADER,
    build_litex_flash_image,
    build_litex_sd_card_image,
    flatten_little64_linux_elf_image,
    write_litex_sd_card_image,
)
from little64.litex_soc import Little64LiteXSimSoC, _load_spi_flash_init, generate_linux_dts
from little64.variants import config_for_litex_variant, resolve_litex_cache_topology
from little64.v2 import Little64V2Core, Little64V2FetchFrontend
from little64.variants import resolve_litex_core_variant


_BUILD_SD_BOOT_ARTIFACTS_SPEC = importlib.util.spec_from_file_location(
    'little64_build_sd_boot_artifacts',
    Path(__file__).resolve().parents[2] / 'target' / 'linux_port' / 'build_sd_boot_artifacts.py',
)
assert _BUILD_SD_BOOT_ARTIFACTS_SPEC is not None and _BUILD_SD_BOOT_ARTIFACTS_SPEC.loader is not None
_BUILD_SD_BOOT_ARTIFACTS = importlib.util.module_from_spec(_BUILD_SD_BOOT_ARTIFACTS_SPEC)
_BUILD_SD_BOOT_ARTIFACTS_SPEC.loader.exec_module(_BUILD_SD_BOOT_ARTIFACTS)


def _make_test_elf64(payload: bytes, *, entry_offset: int = 0) -> bytes:
    phoff = 64
    phentsize = 56
    phnum = 1
    payload_offset = 0x100
    virtual_base = 0xFFFFFFC000000000
    entry = virtual_base + entry_offset

    elf_header = struct.pack(
        '<16sHHIQQQIHHHHHH',
        b'\x7fELF' + bytes([2, 1, 1, 0]) + bytes(8),
        2,
        0x4C36,
        1,
        entry,
        phoff,
        0,
        0,
        64,
        phentsize,
        phnum,
        0,
        0,
        0,
    )
    program_header = struct.pack(
        '<IIQQQQQQ',
        1,
        5,
        payload_offset,
        virtual_base,
        0,
        len(payload),
        len(payload),
        0x1000,
    )

    image = bytearray(payload_offset + len(payload))
    image[:len(elf_header)] = elf_header
    image[phoff:phoff + len(program_header)] = program_header
    image[payload_offset:payload_offset + len(payload)] = payload
    return bytes(image)


def test_litex_profile_matches_current_cpu_contract() -> None:
    profile = Little64LiteXProfile()

    assert profile.category == 'softcore'
    assert profile.name == 'little64'
    assert profile.family == 'little64'
    assert profile.gcc_triple == 'little64-unknown-elf'
    assert profile.clang_triple == 'little64-unknown-elf'
    assert profile.linker_output_format == 'elf64little64'
    assert profile.data_width == 64
    assert profile.instruction_width == 64
    assert profile.irq_count == 63
    assert profile.first_irq_vector == 65
    assert profile.variants == (
        'standard',
        'standard-basic',
        'standard-v2',
        'standard-v2-none',
        'standard-v2-unified',
        'standard-v2-split',
    )
    assert profile.mem_map['rom'] == 0x0000_0000
    assert profile.mem_map['spiflash'] == 0x2000_0000
    assert profile.mem_map['main_ram'] == 0x0000_0000
    assert profile.io_regions == {0x0800_0000: 0x0100_0000, 0x8000_0000: 0x8000_0000}


def test_litex_target_catalog_exposes_boot_sources() -> None:
    assert normalize_litex_boot_source(LITTLE64_LITEX_BOOT_SOURCE_BOOTROM) == LITTLE64_LITEX_BOOT_SOURCE_BOOTROM
    assert normalize_litex_boot_source(LITTLE64_LITEX_BOOT_SOURCE_SPIFLASH) == LITTLE64_LITEX_BOOT_SOURCE_SPIFLASH

    assert resolve_litex_target('sim-flash') == LITTLE64_LITEX_TARGET_CONFIGS['sim-flash']
    assert resolve_litex_target('arty-a7-35') == LITTLE64_LITEX_TARGET_CONFIGS['arty-a7-35']
    assert resolve_litex_target(None) == LITTLE64_LITEX_TARGET_CONFIGS['sim-flash']


def test_litex_target_mem_maps_reflect_boot_source() -> None:
    assert litex_mem_map_for_target('sim-flash')['main_ram'] == 0x0000_0000
    assert litex_mem_map_for_target('sim-bootrom')['main_ram'] == LITTLE64_LITEX_BOOTROM_MAIN_RAM_BASE
    assert litex_mem_map_for_target('arty-a7-35')['main_ram'] == LITTLE64_LITEX_TARGET_CONFIGS['arty-a7-35'].main_ram_base


def test_litex_shim_tracks_reset_vector_in_profile() -> None:
    config = Little64CoreConfig(reset_vector=0x4000_0000)

    shim = Little64LiteXShim(config)

    assert shim.profile.reset_address == 0x4000_0000
    assert shim.core.config.reset_vector == 0x4000_0000
    assert len(shim.irq_lines) == 63


def test_litex_shim_can_instantiate_v2_core() -> None:
    shim = Little64LiteXShim(Little64CoreConfig(core_variant='v2', reset_vector=0x2000))

    assert isinstance(shim.core, Little64V2Core)
    assert isinstance(shim.core.frontend, Little64V2FetchFrontend)
    assert shim.core.config.core_variant == 'v2'
    assert shim.profile.reset_address == 0x2000


def test_litex_shim_rejects_profile_reset_mismatch() -> None:
    config = Little64CoreConfig(reset_vector=0x0000_0000)
    profile = Little64LiteXProfile(reset_address=0x0000_0040)

    with pytest.raises(ValueError):
        Little64LiteXShim(config, profile=profile)


def test_litex_top_exposes_generic_bus_contract() -> None:
    top = Little64LiteXTop(Little64CoreConfig(reset_vector=0x0100_0000))

    assert top.reset_address == 0x0100_0000
    assert len(top.boot_r1) == 64
    assert len(top.boot_r13) == 64
    assert len(top.irq_lines) == 63
    assert len(top.i_bus_adr) == 64
    assert len(top.i_bus_dat_w) == 64
    assert len(top.i_bus_sel) == 8
    assert len(top.d_bus_adr) == 64
    assert len(top.d_bus_dat_w) == 64
    assert len(top.d_bus_sel) == 8
    assert len(top.ports()) == 27


def test_emit_litex_cpu_verilog_writes_named_module(tmp_path) -> None:
    output_path = tmp_path / 'little64_litex_cpu_top.v'

    emit_litex_cpu_verilog(output_path, module_name='little64_test_top')

    verilog_text = output_path.read_text(encoding='utf-8')
    assert 'module little64_test_top' in verilog_text
    assert 'i_bus_adr' in verilog_text
    assert 'd_bus_adr' in verilog_text
    assert 'irq_lines' in verilog_text


def test_register_little64_with_litex_exposes_cpu_plugin() -> None:
    cpu_cls = register_little64_with_litex(force=True)

    assert cpu_cls is Little64


def test_litex_cpu_variant_names_resolve_to_core_variants() -> None:
    assert resolve_litex_core_variant('standard') == 'basic'
    assert resolve_litex_core_variant('standard-basic') == 'basic'
    assert resolve_litex_core_variant('standard-v2') == 'v2'
    assert resolve_litex_core_variant('standard-v2-none') == 'v2'
    assert resolve_litex_core_variant('standard-v2-unified') == 'v2'
    assert resolve_litex_core_variant('standard-v2-split') == 'v2'


def test_litex_cpu_variant_names_resolve_to_cache_topologies() -> None:
    assert resolve_litex_cache_topology('standard') == 'none'
    assert resolve_litex_cache_topology('standard-basic') == 'none'
    assert resolve_litex_cache_topology('standard-v2') == 'none'
    assert resolve_litex_cache_topology('standard-v2-none') == 'none'
    assert resolve_litex_cache_topology('standard-v2-unified') == 'unified'
    assert resolve_litex_cache_topology('standard-v2-split') == 'split'


def test_litex_variant_config_builder_preserves_reset_vector() -> None:
    config = config_for_litex_variant('standard-v2-split', reset_vector=0x1234)

    assert config.reset_vector == 0x1234
    assert config.core_variant == 'v2'
    assert config.cache_topology == 'split'


def test_litex_cpu_can_select_v2_cache_topology_variants() -> None:
    cpu = Little64(type('Platform', (), {'output_dir': 'builddir'})(), variant='standard-v2-unified')

    assert cpu.core_config.core_variant == 'v2'
    assert cpu.core_config.cache_topology == 'unified'


def test_litex_sim_soc_can_select_v2_variant() -> None:
    soc = Little64LiteXSimSoC(cpu_variant='standard-v2-split')

    assert soc.cpu.variant == 'standard-v2-split'
    assert soc.cpu.core_config.core_variant == 'v2'
    assert soc.cpu.core_config.cache_topology == 'split'


def test_litex_sim_soc_can_switch_to_bootrom_target() -> None:
    soc = Little64LiteXSimSoC(litex_target='sim-bootrom', integrated_main_ram_size=0x0200_0000)

    assert soc.boot_source == LITTLE64_LITEX_BOOT_SOURCE_BOOTROM
    assert soc.litex_target == LITTLE64_LITEX_TARGET_CONFIGS['sim-bootrom']
    assert soc.cpu.reset_address == 0
    assert soc.cpu.mem_map['main_ram'] == LITTLE64_LITEX_BOOTROM_MAIN_RAM_BASE
    assert 'rom' in soc.bus.regions
    assert soc.bus.regions['rom'].size >= LITTLE64_LITEX_BOOTROM_SIZE
    assert soc.bus.regions['main_ram'].origin == LITTLE64_LITEX_BOOTROM_MAIN_RAM_BASE


def test_data_bridge_splits_unaligned_qword_reads() -> None:
    bridge = Little64WishboneDataBridge()
    seen_transactions: list[tuple[int, int, int]] = []
    read_results: list[int] = []

    def cpu_driver():
        yield bridge.cpu_adr.eq(0x81)
        yield bridge.cpu_sel.eq(0xFF)
        yield bridge.cpu_cyc.eq(1)
        yield bridge.cpu_stb.eq(1)
        yield bridge.cpu_we.eq(0)
        for _ in range(10):
            if (yield bridge.cpu_ack):
                read_results.append((yield bridge.cpu_dat_r))
                break
            yield
        yield bridge.cpu_cyc.eq(0)
        yield bridge.cpu_stb.eq(0)
        yield

    def wb_target():
        for _ in range(12):
            if (yield bridge.bus.cyc) and (yield bridge.bus.stb):
                adr = (yield bridge.bus.adr)
                sel = (yield bridge.bus.sel)
                we = (yield bridge.bus.we)
                seen_transactions.append((adr, sel, we))
                if adr == 0x10:
                    yield bridge.bus.dat_r.eq(0x0706050403020100)
                else:
                    yield bridge.bus.dat_r.eq(0x0F0E0D0C0B0A0908)
                yield bridge.bus.ack.eq(1)
                yield
                yield bridge.bus.ack.eq(0)
            yield

    from migen.sim import run_simulation

    run_simulation(bridge, [cpu_driver(), wb_target()])

    assert seen_transactions == [(0x10, 0xFE, 0), (0x11, 0x01, 0)]
    assert read_results == [0x0807060504030201]


def test_litex_sim_soc_generates_linux_dts(tmp_path) -> None:
    soc = Little64LiteXSimSoC(
        integrated_main_ram_size=0x0200_0000,
        with_spi_flash=True,
        with_timer=True,
    )
    soc.platform.output_dir = str(tmp_path / 'litex-sim')

    dts_text = generate_linux_dts(soc, bootargs='console=liteuart earlycon=liteuart,0xf0001000')

    assert 'compatible = "little64,litex-sim";' in dts_text
    assert 'compatible = "litex,liteuart";' in dts_text
    assert 'compatible = "jedec-flash";' in dts_text
    assert 'compatible = "little64,timer";' in dts_text
    assert 'device_type = "memory";' in dts_text
    assert 'memory@100000' in dts_text


def test_litex_sim_soc_generates_target_specific_metadata(tmp_path) -> None:
    soc = Little64LiteXSimSoC(
        litex_target='arty-a7-35',
        integrated_main_ram_size=0x0200_0000,
    )
    soc.platform.output_dir = str(tmp_path / 'litex-arty')

    dts_text = generate_linux_dts(soc)

    assert 'compatible = "little64,arty-a7-35", "digilent,arty-a7-35";' in dts_text
    assert 'model = "Little64 LiteX Arty A7-35T SoC";' in dts_text
    assert 'bootrom0: rom@0 {' in dts_text


def test_litex_arty_target_enables_sdram_model(tmp_path) -> None:
    soc = Little64LiteXSimSoC(litex_target='arty-a7-35')
    soc.platform.output_dir = str(tmp_path / 'litex-arty-sdram')
    soc.finalize()

    assert soc.boot_source == LITTLE64_LITEX_BOOT_SOURCE_BOOTROM
    assert soc.cpu.mem_map['main_ram'] == LITTLE64_LITEX_TARGET_CONFIGS['arty-a7-35'].main_ram_base
    assert hasattr(soc, 'sdrphy')
    assert soc.bus.regions['main_ram'].size == LITTLE64_LITEX_TARGET_CONFIGS['arty-a7-35'].default_ram_size


def test_stage0_artifact_builder_emits_sdram_init_headers_for_arty(tmp_path) -> None:
    soc = Little64LiteXSimSoC(litex_target='arty-a7-35', with_sdcard=True)
    soc.platform.output_dir = str(tmp_path / 'litex-arty-stage0')

    regs_header = tmp_path / 'litex_sd_boot_regs.h'
    _BUILD_SD_BOOT_ARTIFACTS._write_stage0_header(
        regs_header,
        soc=soc,
        ram_base=LITTLE64_LITEX_TARGET_CONFIGS['arty-a7-35'].main_ram_base,
        ram_size=LITTLE64_LITEX_TARGET_CONFIGS['arty-a7-35'].default_ram_size,
        kernel_physical_base=LITTLE64_LITEX_TARGET_CONFIGS['arty-a7-35'].main_ram_base,
    )
    _BUILD_SD_BOOT_ARTIFACTS._write_stage0_generated_support(tmp_path, soc=soc)

    regs_text = regs_header.read_text(encoding='utf-8')
    csr_text = (tmp_path / 'generated' / 'csr.h').read_text(encoding='utf-8')
    sdram_text = (tmp_path / 'generated' / 'sdram_phy.h').read_text(encoding='utf-8')

    assert '#define L64_HAVE_SDRAM_INIT 1' in regs_text
    assert '#define L64_SDRAM_CSR_BASE ' in regs_text
    assert 'CSR_SDRAM_DFII_CONTROL_ADDR' in csr_text
    assert 'sdram_dfii_pi0_command_write' in csr_text
    assert 'static inline void init_sequence(void)' in sdram_text


def test_stage0_artifact_builder_skips_sdram_init_for_sim_bootrom(tmp_path) -> None:
    soc = Little64LiteXSimSoC(litex_target='sim-bootrom', with_sdcard=True)
    soc.platform.output_dir = str(tmp_path / 'litex-sim-bootrom-stage0')

    regs_header = tmp_path / 'litex_sd_boot_regs.h'
    _BUILD_SD_BOOT_ARTIFACTS._write_stage0_header(
        regs_header,
        soc=soc,
        ram_base=LITTLE64_LITEX_BOOTROM_MAIN_RAM_BASE,
        ram_size=0x0400_0000,
        kernel_physical_base=LITTLE64_LITEX_BOOTROM_MAIN_RAM_BASE,
    )
    _BUILD_SD_BOOT_ARTIFACTS._write_stage0_generated_support(tmp_path, soc=soc)

    regs_text = regs_header.read_text(encoding='utf-8')

    assert '#define L64_HAVE_SDRAM_INIT 0' in regs_text
    assert not (tmp_path / 'generated' / 'sdram_phy.h').exists()


def test_stage0_artifact_builder_emits_sdram_init_headers_for_sim_bootrom_override(tmp_path) -> None:
    soc = Little64LiteXSimSoC(litex_target='sim-bootrom', with_sdcard=True, with_sdram=True)
    soc.platform.output_dir = str(tmp_path / 'litex-sim-bootrom-stage0-sdram')

    regs_header = tmp_path / 'litex_sd_boot_regs.h'
    _BUILD_SD_BOOT_ARTIFACTS._write_stage0_header(
        regs_header,
        soc=soc,
        ram_base=LITTLE64_LITEX_BOOTROM_MAIN_RAM_BASE,
        ram_size=0x0400_0000,
        kernel_physical_base=LITTLE64_LITEX_BOOTROM_MAIN_RAM_BASE,
    )
    _BUILD_SD_BOOT_ARTIFACTS._write_stage0_generated_support(tmp_path, soc=soc)

    regs_text = regs_header.read_text(encoding='utf-8')
    csr_text = (tmp_path / 'generated' / 'csr.h').read_text(encoding='utf-8')
    sdram_text = (tmp_path / 'generated' / 'sdram_phy.h').read_text(encoding='utf-8')

    assert '#define L64_HAVE_SDRAM_INIT 1' in regs_text
    assert 'CSR_SDRAM_DFII_CONTROL_ADDR' in csr_text
    assert 'static inline void init_sequence(void)' in sdram_text
    assert soc.bus.regions['main_ram'].size == LITTLE64_LITEX_TARGET_CONFIGS['sim-bootrom'].default_ram_size


def test_litex_sdcard_emulator_verilog_sources_are_available() -> None:
    verilog_dir = _resolve_emulator_verilog_dir()

    for filename in EMULATOR_VERILOG_FILENAMES:
        assert (verilog_dir / filename).is_file()


def test_litex_sim_soc_generates_linux_dts_with_sdcard(tmp_path) -> None:
    soc = Little64LiteXSimSoC(
        integrated_main_ram_size=0x0200_0000,
        with_spi_flash=True,
        with_sdcard=True,
        with_timer=True,
    )
    soc.platform.output_dir = str(tmp_path / 'litex-sim-sdcard')

    dts_text = generate_linux_dts(
        soc,
        bootargs='console=liteuart earlycon=liteuart,0xf0003800 ignore_loglevel loglevel=8',
    )

    assert 'sdcard0 = &mmc0;' in dts_text
    assert 'sys_clk: clock {' in dts_text
    assert 'vreg_mmc: vreg_mmc {' in dts_text
    assert 'uart0: serial@f0003800 {' in dts_text
    assert 'mmc0: mmc@f0002800 {' in dts_text
    assert 'compatible = "litex,mmc";' in dts_text
    assert 'reg-names = "phy", "core", "reader", "writer", "irq";' in dts_text
    assert 'clocks = <&sys_clk>;' in dts_text
    assert 'vmmc-supply = <&vreg_mmc>;' in dts_text
    assert 'bus-width = <4>;' in dts_text
    assert 'interrupts = <67>;' in dts_text


def test_litex_sim_soc_can_use_image_backed_sdcard(tmp_path) -> None:
    soc = Little64LiteXSimSoC(
        integrated_main_ram_size=0x0200_0000,
        with_spi_flash=True,
        with_sdcard=True,
        with_timer=True,
        sdcard_image_path=tmp_path / 'sdcard.img',
    )
    soc.platform.output_dir = str(tmp_path / 'litex-sim-sd-image')

    assert hasattr(soc, 'sdcard_sdemulator')
    assert hasattr(soc, 'sdcard_image_bridge')


def test_litex_sim_soc_can_use_sdram_model(tmp_path) -> None:
    soc = Little64LiteXSimSoC(with_sdram=True)
    soc.platform.output_dir = str(tmp_path / 'litex-sdram')
    soc.finalize()

    assert hasattr(soc, 'sdrphy')
    assert 'main_ram' in soc.bus.regions


def test_spi_flash_init_matches_litespi_model_word_width(tmp_path) -> None:
    image_path = tmp_path / 'flash.bin'
    image_path.write_bytes(bytes.fromhex('0d800d9ffda004e01400002000000000'))

    init_words = _load_spi_flash_init(image_path)

    assert init_words[:4] == [0x0D800D9F, 0xFDA004E0, 0x14000020, 0x00000000]


def test_generated_litex_sim_dts_matches_built_in_profile(tmp_path) -> None:
    built_in_dts = Path('target/linux_port/linux/arch/little64/boot/dts/little64-litex-sim.dts').read_text(encoding='utf-8')

    soc = Little64LiteXSimSoC(
        integrated_main_ram_size=0x0400_0000,
        with_spi_flash=True,
        with_timer=True,
    )
    soc.platform.output_dir = str(tmp_path / 'litex-sim')

    generated_dts = generate_linux_dts(
        soc,
        model='Little-64 LiteX Simulation SoC',
        bootargs='console=liteuart earlycon=liteuart,0xf0001000 ignore_loglevel loglevel=8',
    )

    shared_lines = [
        'compatible = "little64,litex-sim";',
        'bootargs = "console=liteuart earlycon=liteuart,0xf0001000 ignore_loglevel loglevel=8";',
        'memory@100000',
        'compatible = "litex,liteuart";',
        'serial@f0001000',
        'interrupts = <65>;',
        'compatible = "jedec-flash";',
        'flash@20000000',
        'compatible = "little64,timer";',
        'timer@8001000',
        'interrupts = <66>;',
    ]

    for line in shared_lines:
        assert line in built_in_dts
        assert line in generated_dts

    assert 'reg = <0x0 0x00100000 0x0 0x03f00000>;' in built_in_dts
    assert 'reg = <0x00000000 0x00100000 0x00000000 0x03f00000>;' in generated_dts
    assert 'reg = <0x0 0xf0001000 0x0 0x100>;' in built_in_dts
    assert 'reg = <0x00000000 0xf0001000 0x00000000 0x00000100>;' in generated_dts
    assert 'reg = <0x0 0x20000000 0x0 0x01000000>;' in built_in_dts
    assert 'reg = <0x00000000 0x20000000 0x00000000 0x01000000>;' in generated_dts
    assert 'reg = <0x0 0x08001000 0x0 0x20>;' in built_in_dts
    assert 'reg = <0x00000000 0x08001000 0x00000000 0x00000020>;' in generated_dts


def test_litex_sim_defconfig_tracks_built_in_dts_contract() -> None:
    dts_text = Path('target/linux_port/linux/arch/little64/boot/dts/little64-litex-sim.dts').read_text(encoding='utf-8')
    defconfig_text = Path('target/linux_port/linux/arch/little64/configs/little64_litex_sim_defconfig').read_text(encoding='utf-8')

    assert 'compatible = "litex,liteuart";' in dts_text
    assert 'compatible = "jedec-flash";' in dts_text
    assert 'compatible = "little64,timer";' in dts_text
    assert 'compatible = "ns16550a";' not in dts_text
    assert 'little64,pvblk' not in dts_text

    assert 'CONFIG_LITEX_SOC_CONTROLLER=y' in defconfig_text
    assert 'CONFIG_SERIAL_LITEUART=y' in defconfig_text
    assert 'CONFIG_SERIAL_LITEUART_CONSOLE=y' in defconfig_text
    assert 'CONFIG_MMC=y' in defconfig_text
    assert 'CONFIG_MMC_BLOCK=y' in defconfig_text
    assert 'CONFIG_MMC_LITEX=y' in defconfig_text
    assert 'CONFIG_FAT_FS=y' in defconfig_text
    assert 'CONFIG_MSDOS_FS=y' in defconfig_text
    assert 'CONFIG_VFAT_FS=y' in defconfig_text
    assert 'CONFIG_MSDOS_PARTITION=y' in defconfig_text
    assert 'CONFIG_MTD_PHYSMAP=y' in defconfig_text
    assert 'CONFIG_MTD_PHYSMAP_OF=y' in defconfig_text
    assert 'CONFIG_MTD_JEDECPROBE=y' in defconfig_text
    assert '# CONFIG_LITTLE64_PVBLK is not set' in defconfig_text


def test_flash_image_builder_matches_linux_loader_contract() -> None:
    stage0 = b'STAGE0'
    kernel_payload = b'\x11\x22\x33\x44'
    dtb = b'DTB'

    layout = build_litex_flash_image(
        stage0_bytes=stage0,
        kernel_elf_bytes=_make_test_elf64(kernel_payload),
        dtb_bytes=dtb,
    )

    header = FLASH_BOOT_HEADER.unpack_from(layout.flash_image, LITTLE64_LITEX_FLASH_BOOT_HEADER_OFFSET)
    assert layout.flash_image[:len(stage0)] == stage0
    assert header[2] == layout.kernel_flash_offset
    assert header[5] == 0x0010_0000
    assert header[6] == layout.dtb_flash_offset
    assert header[8] == layout.dtb_physical_address
    assert layout.flash_image[layout.kernel_flash_offset:layout.kernel_flash_offset + 4] == kernel_payload
    assert layout.flash_image[layout.dtb_flash_offset:layout.dtb_flash_offset + 3] == dtb


def test_sd_card_image_builder_matches_stage0_contract() -> None:
    kernel_payload = _make_test_elf64(b'KERNEL')
    dtb = b'DTB!'
    rootfs = b'ROOTFS'

    layout = build_litex_sd_card_image(
        kernel_elf_bytes=kernel_payload,
        dtb_bytes=dtb,
        rootfs_bytes=rootfs,
        boot_partition_size_mb=64,
        root_partition_size_mb=1,
    )

    disk = layout.disk_image
    boot_partition_offset = layout.boot_partition_lba * 512
    root_partition_offset = layout.root_partition_lba * 512
    boot_sector = disk[boot_partition_offset:boot_partition_offset + 512]
    reserved_sectors = struct.unpack_from('<H', boot_sector, 14)[0]
    fat_count = boot_sector[16]
    fat_sectors = struct.unpack_from('<I', boot_sector, 36)[0]
    sectors_per_cluster = boot_sector[13]
    first_data_sector = reserved_sectors + fat_count * fat_sectors
    root_dir_offset = boot_partition_offset + first_data_sector * 512
    root_dir = disk[root_dir_offset:root_dir_offset + 96]

    assert disk[510:512] == b'\x55\xaa'
    assert disk[446 + 4] == 0x0C
    assert disk[462 + 4] == 0x83
    assert boot_sector[3:11] == b'L64FAT32'
    assert boot_sector[11:13] == b'\x00\x02'
    assert sectors_per_cluster == 1
    assert boot_sector[510:512] == b'\x55\xaa'
    assert root_dir[0:11] == b'VMLINUX    '
    assert root_dir[32:43] == b'BOOT    DTB'
    assert disk[root_partition_offset:root_partition_offset + len(rootfs)] == rootfs
    assert layout.kernel_file.short_name == b'VMLINUX    '
    assert layout.dtb_file.short_name == b'BOOT    DTB'
    assert layout.kernel_file.size == len(kernel_payload)
    assert layout.dtb_file.size == len(dtb)
    assert layout.disk_size_bytes == len(disk)


def test_sd_card_image_builder_does_not_slice_payload_remainders() -> None:
    class NoSliceBytes(bytes):
        def __getitem__(self, key):
            if isinstance(key, slice):
                raise AssertionError('payload remainder slicing should not be used here')
            return super().__getitem__(key)

    kernel_payload = NoSliceBytes(_make_test_elf64(b'KERNEL' * 1024))
    dtb = NoSliceBytes(b'DTB!')

    layout = build_litex_sd_card_image(
        kernel_elf_bytes=kernel_payload,
        dtb_bytes=dtb,
        boot_partition_size_mb=64,
        root_partition_size_mb=1,
    )

    assert layout.kernel_file.size == len(kernel_payload)
    assert layout.dtb_file.size == len(dtb)


def test_sd_card_image_writer_creates_requested_disk_size_and_partitions(tmp_path) -> None:
    output_path = tmp_path / 'little64-linux-sdcard.img'
    kernel_payload = _make_test_elf64(b'KERNEL')
    dtb = b'DTB!'
    rootfs = b'ROOTFS'

    layout = write_litex_sd_card_image(
        output_path,
        kernel_elf_bytes=kernel_payload,
        dtb_bytes=dtb,
        rootfs_bytes=rootfs,
        total_disk_size_bytes=96 * 1024 * 1024,
        boot_partition_size_mb=64,
    )

    disk = output_path.read_bytes()
    boot_partition_offset = layout.boot_partition_lba * 512
    root_partition_offset = layout.root_partition_lba * 512

    assert output_path.stat().st_size == 96 * 1024 * 1024
    assert layout.disk_image is None
    assert layout.disk_size_bytes == 96 * 1024 * 1024
    assert layout.boot_partition_sector_count == 64 * 1024 * 1024 // 512
    assert disk[510:512] == b'\x55\xaa'
    assert disk[446 + 4] == 0x0C
    assert disk[462 + 4] == 0x83
    assert disk[boot_partition_offset + 3:boot_partition_offset + 11] == b'L64FAT32'
    assert disk[root_partition_offset:root_partition_offset + len(rootfs)] == rootfs


def test_flatten_linux_elf_resolves_virtual_entry_to_physical() -> None:
    image = flatten_little64_linux_elf_image(_make_test_elf64(b'\xaa\xbb', entry_offset=1))

    assert image.entry_physical == 0x0010_0001
    assert image.image[:2] == b'\xaa\xbb'
    assert image.image_span == 0x1000


def test_llvm_wrapper_generation_creates_triple_prefixed_tools(tmp_path) -> None:
    wrapper_dir = ensure_litex_llvm_toolchain_wrappers(tmp_path)
    gcc_wrapper = wrapper_dir / 'little64-unknown-elf-gcc'
    readelf_wrapper = wrapper_dir / 'little64-unknown-elf-readelf'

    assert gcc_wrapper.exists()
    assert readelf_wrapper.exists()
    assert os.access(gcc_wrapper, os.X_OK)