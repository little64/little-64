from __future__ import annotations

import os
import struct
from pathlib import Path

import pytest

from little64.config import Little64CoreConfig
from little64.litex import (
    LITTLE64_LITEX_FLASH_BOOT_HEADER_OFFSET,
    Little64LiteXProfile,
    Little64LiteXShim,
    Little64LiteXTop,
    emit_litex_cpu_verilog,
)
from little64.litex_cpu import Little64, Little64WishboneDataBridge, ensure_litex_llvm_toolchain_wrappers, register_little64_with_litex
from little64.litex_linux_boot import FLASH_BOOT_HEADER, build_litex_flash_image, flatten_little64_linux_elf_image
from little64.litex_soc import Little64LiteXSimSoC, _load_spi_flash_init, generate_linux_dts


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
    assert profile.mem_map['rom'] == 0x0000_0000
    assert profile.mem_map['spiflash'] == 0x2000_0000
    assert profile.mem_map['main_ram'] == 0x0000_0000
    assert profile.io_regions == {0x0800_0000: 0x0100_0000, 0x8000_0000: 0x8000_0000}


def test_litex_shim_tracks_reset_vector_in_profile() -> None:
    config = Little64CoreConfig(reset_vector=0x4000_0000)

    shim = Little64LiteXShim(config)

    assert shim.profile.reset_address == 0x4000_0000
    assert shim.core.config.reset_vector == 0x4000_0000
    assert len(shim.irq_lines) == 63


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