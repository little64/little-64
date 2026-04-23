from __future__ import annotations

import argparse
import importlib.util
import os
import re
import struct
import subprocess
import sys
from pathlib import Path

from amaranth.sim import Simulator
import pytest

from little64_cores.config import Little64CoreConfig
from little64_cores.litex import (
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
from little64_cores.litex_sdcard import EMULATOR_VERILOG_FILENAMES, _resolve_emulator_verilog_dir
from little64_cores.litex_cpu import Little64, Little64WishboneDataBridge, ensure_litex_llvm_toolchain_wrappers, register_little64_with_litex
from little64_cores.litex_arty import Little64ArtySPISDCardMapping, arty_spi_sdcard_extension, resolve_arty_spi_sdcard_mapping
from little64_cores.litex_arty import Little64LiteXArtySoC
from little64_cores.litex_linux_boot import (
    BOOT_CHECKSUM_MAGIC,
    BOOT_CHECKSUM_STRUCT,
    BOOT_CHECKSUM_VERSION,
    FLASH_BOOT_HEADER,
    build_litex_flash_image,
    build_litex_sd_card_image,
    flatten_little64_linux_elf_image,
    write_litex_sd_card_image,
)
from little64_cores.litex_soc import Little64LinuxTimer, Little64LiteXSimSoC, _load_spi_flash_init, generate_linux_dts
from little64_cores.variants import config_for_litex_variant, resolve_litex_cache_topology
from little64_cores.v2 import Little64V2Core, Little64V2FetchFrontend
from little64_cores.variants import resolve_litex_core_variant


_BUILD_SD_BOOT_ARTIFACTS_SPEC = importlib.util.spec_from_file_location(
    'little64_build_sd_boot_artifacts',
    Path(__file__).resolve().parents[2] / 'tools' / 'little64' / 'little64' / 'commands' / 'sd' / 'artifacts.py',
)
assert _BUILD_SD_BOOT_ARTIFACTS_SPEC is not None and _BUILD_SD_BOOT_ARTIFACTS_SPEC.loader is not None
_BUILD_SD_BOOT_ARTIFACTS = importlib.util.module_from_spec(_BUILD_SD_BOOT_ARTIFACTS_SPEC)
_BUILD_SD_BOOT_ARTIFACTS_SPEC.loader.exec_module(_BUILD_SD_BOOT_ARTIFACTS)

_BUILD_ARTY_BITSTREAM_SPEC = importlib.util.spec_from_file_location(
    'little64_build_litex_arty_bitstream',
    Path(__file__).resolve().parents[2] / 'tools' / 'little64' / 'little64' / 'commands' / 'hdl' / 'arty_build.py',
)
assert _BUILD_ARTY_BITSTREAM_SPEC is not None and _BUILD_ARTY_BITSTREAM_SPEC.loader is not None
_BUILD_ARTY_BITSTREAM = importlib.util.module_from_spec(_BUILD_ARTY_BITSTREAM_SPEC)
_BUILD_ARTY_BITSTREAM_SPEC.loader.exec_module(_BUILD_ARTY_BITSTREAM)

_BUILD_FLASH_IMAGE_SPEC = importlib.util.spec_from_file_location(
    'little64_build_litex_flash_image',
    Path(__file__).resolve().parents[2] / 'tools' / 'little64' / 'little64' / 'commands' / 'hdl' / 'flash_image.py',
)
assert _BUILD_FLASH_IMAGE_SPEC is not None and _BUILD_FLASH_IMAGE_SPEC.loader is not None
_BUILD_FLASH_IMAGE = importlib.util.module_from_spec(_BUILD_FLASH_IMAGE_SPEC)
_BUILD_FLASH_IMAGE_SPEC.loader.exec_module(_BUILD_FLASH_IMAGE)


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
        'standard-v3',
        'standard-v3-none',
        'standard-v3-unified',
        'standard-v3-split',
    )
    assert profile.mem_map['rom'] == 0x0000_0000
    assert profile.mem_map['spiflash'] == 0x2000_0000
    assert profile.mem_map['main_ram'] == LITTLE64_LITEX_BOOTROM_MAIN_RAM_BASE
    assert profile.io_regions == {0x0800_0000: 0x0100_0000, 0x8000_0000: 0x8000_0000}


def test_arty_spi_sdcard_arduino_mapping_resolves_to_expected_fpga_pins() -> None:
    mapping = resolve_arty_spi_sdcard_mapping(connector='arduino')

    assert mapping.name == 'arduino-io30-33'
    assert mapping.clk == 'R15'
    assert mapping.mosi == 'R13'
    assert mapping.miso == 'P15'
    assert mapping.cs_n == 'R11'


def test_arty_bitstream_parse_args_accepts_vivado_stop_after(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        sys,
        'argv',
        ['build_litex_arty_bitstream.py', '--vivado-stop-after', 'implementation'],
    )

    args = _BUILD_ARTY_BITSTREAM.parse_args()

    assert args.vivado_stop_after == _BUILD_ARTY_BITSTREAM.VIVADO_STOP_AFTER_IMPLEMENTATION


def test_arty_bitstream_render_stage_tcl_truncates_after_synthesis(tmp_path: Path) -> None:
    build_name = 'little64_arty_a7_35'
    base_tcl = tmp_path / f'{build_name}.tcl'
    base_tcl.write_text(
        '\n'.join([
            '# Synthesis',
            f'write_checkpoint -force {build_name}_synth.dcp',
            '# Optimize design',
            'opt_design -directive default',
            '# Bitstream generation',
            f'write_bitstream -force {build_name}.bit ',
            'quit',
        ]) + '\n',
        encoding='utf-8',
    )

    stage_tcl = _BUILD_ARTY_BITSTREAM._render_vivado_stage_tcl(
        gateware_dir=tmp_path,
        build_name=build_name,
        stop_after=_BUILD_ARTY_BITSTREAM.VIVADO_STOP_AFTER_SYNTHESIS,
    )
    stage_text = stage_tcl.read_text(encoding='utf-8')

    assert f'write_checkpoint -force {build_name}_synth.dcp' in stage_text
    assert 'opt_design -directive default' not in stage_text
    assert 'write_bitstream -force' not in stage_text
    assert stage_text.rstrip().endswith('quit')


def test_arty_bitstream_render_stage_tcl_truncates_after_implementation(tmp_path: Path) -> None:
    build_name = 'little64_arty_a7_35'
    base_tcl = tmp_path / f'{build_name}.tcl'
    base_tcl.write_text(
        '\n'.join([
            '# Routing report',
            f'report_power -file {build_name}_power.rpt',
            '# Bitstream generation',
            f'write_bitstream -force {build_name}.bit ',
            'quit',
        ]) + '\n',
        encoding='utf-8',
    )

    stage_tcl = _BUILD_ARTY_BITSTREAM._render_vivado_stage_tcl(
        gateware_dir=tmp_path,
        build_name=build_name,
        stop_after=_BUILD_ARTY_BITSTREAM.VIVADO_STOP_AFTER_IMPLEMENTATION,
    )
    stage_text = stage_tcl.read_text(encoding='utf-8')

    assert f'report_power -file {build_name}_power.rpt' in stage_text
    assert 'write_bitstream -force' not in stage_text
    assert stage_text.rstrip().endswith('quit')


def test_arty_bitstream_rejects_program_without_bitstream_stage() -> None:
    args = argparse.Namespace(
        generate_only=False,
        program_only=False,
        toolchain='vivado',
        vivado_stop_after=_BUILD_ARTY_BITSTREAM.VIVADO_STOP_AFTER_SYNTHESIS,
    )

    with pytest.raises(SystemExit, match='--program requires --vivado-stop-after bitstream'):
        _BUILD_ARTY_BITSTREAM._validate_requested_actions(args, (_BUILD_ARTY_BITSTREAM.PROGRAM_OPERATION_VOLATILE,))


def test_arty_spi_sdcard_pmod_mapping_supports_numato_adapter() -> None:
    mapping = resolve_arty_spi_sdcard_mapping(connector='pmodd', adapter='numato')

    assert mapping.name == 'numato-pmodd'
    assert mapping.clk == 'pmodd:5'
    assert mapping.mosi == 'pmodd:1'
    assert mapping.miso == 'pmodd:2'
    assert mapping.cs_n == 'pmodd:4'


def test_arty_spi_sdcard_mapping_overrides_selected_preset() -> None:
    mapping = resolve_arty_spi_sdcard_mapping(
        connector='arduino',
        clk='X1',
        mosi='X2',
        miso='X3',
        cs_n='X4',
    )

    assert mapping.clk == 'X1'
    assert mapping.mosi == 'X2'
    assert mapping.miso == 'X3'
    assert mapping.cs_n == 'X4'


def test_arty_spi_sdcard_extension_uses_mapping_pins() -> None:
    extension = arty_spi_sdcard_extension(
        Little64ArtySPISDCardMapping(
            name='custom',
            description='custom test mapping',
            clk='CLKPIN',
            mosi='MOSIPIN',
            miso='MISOPIN',
            cs_n='CSPIN',
        )
    )

    resource = extension[0]

    assert resource[0] == 'spisdcard'
    assert resource[1] == 0
    assert any('CLKPIN' in repr(item) for item in resource[2:])
    assert any('MOSIPIN' in repr(item) for item in resource[2:])
    assert any('MISOPIN' in repr(item) for item in resource[2:])
    assert any('CSPIN' in repr(item) for item in resource[2:])


def test_arty_spi_sdcard_extension_only_applies_slew_to_outputs() -> None:
    extension = arty_spi_sdcard_extension(resolve_arty_spi_sdcard_mapping(connector='arduino'))

    resource = extension[0]
    clk_repr = repr(resource[2])
    mosi_repr = repr(resource[3])
    cs_repr = repr(resource[4])
    miso_repr = repr(resource[5])

    assert 'SLEW=FAST' in clk_repr
    assert 'SLEW=FAST' in mosi_repr
    assert 'SLEW=FAST' in cs_repr
    assert 'SLEW=FAST' not in miso_repr


def test_create_arty_platform_reports_missing_litex_boards(monkeypatch) -> None:
    monkeypatch.setitem(sys.modules, 'litex_boards', None)
    monkeypatch.setitem(sys.modules, 'litex_boards.platforms', None)

    from little64_cores import litex_arty

    with pytest.raises(ModuleNotFoundError, match='litex-boards is required'):
        litex_arty.create_arty_platform()


def test_litex_target_catalog_exposes_boot_sources() -> None:
    assert normalize_litex_boot_source(LITTLE64_LITEX_BOOT_SOURCE_BOOTROM) == LITTLE64_LITEX_BOOT_SOURCE_BOOTROM
    assert normalize_litex_boot_source(LITTLE64_LITEX_BOOT_SOURCE_SPIFLASH) == LITTLE64_LITEX_BOOT_SOURCE_SPIFLASH

    assert resolve_litex_target('sim-flash') == LITTLE64_LITEX_TARGET_CONFIGS['sim-flash']
    assert resolve_litex_target('arty-a7-35') == LITTLE64_LITEX_TARGET_CONFIGS['arty-a7-35']
    assert resolve_litex_target(None) == LITTLE64_LITEX_TARGET_CONFIGS['sim-flash']


def test_litex_target_mem_maps_reflect_boot_source() -> None:
    assert litex_mem_map_for_target('sim-flash')['main_ram'] == LITTLE64_LITEX_BOOTROM_MAIN_RAM_BASE
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


def test_litex_top_v3_reaches_redirect_target_with_delayed_instruction_ack() -> None:
    top = Little64LiteXTop(Little64CoreConfig(core_variant='v3', cache_topology='none', reset_vector=0))
    sim = Simulator(top)
    sim.add_clock(1e-6)

    instruction_lines = {
        0x00: 0xE004_B10D_940D_800D,
        0x08: 0x0000_0000_0000_00BE,
        0x10: 0x1021_1002_101F_43B1,
        0xB8: 0xDF00 << 48,
    }
    data_lines = {
        0x08: 0x0000_0000_0000_00BE,
    }

    observed = {
        'halted': 0,
        'locked_up': 0,
        'seen_i_addresses': [],
        'seen_d_addresses': [],
    }
    pending_i_response: dict[str, int] = {}

    async def bus_process(ctx):
        request_active_last = False
        while True:
            ctx.set(top.i_bus_ack, 0)
            ctx.set(top.i_bus_err, 0)
            ctx.set(top.i_bus_dat_r, 0)
            ctx.set(top.d_bus_ack, 0)
            ctx.set(top.d_bus_err, 0)
            ctx.set(top.d_bus_dat_r, 0)

            if pending_i_response:
                pending_i_response['delay'] -= 1
                if pending_i_response['delay'] < 0:
                    address = pending_i_response['address']
                    ctx.set(top.i_bus_dat_r, instruction_lines.get(address, 0))
                    ctx.set(top.i_bus_ack, 1)
                    pending_i_response.clear()

            request_active = ctx.get(top.i_bus_cyc) and ctx.get(top.i_bus_stb)
            if request_active and not request_active_last and not pending_i_response:
                address = ctx.get(top.i_bus_adr)
                pending_i_response.update(address=address, delay=1)
                observed['seen_i_addresses'].append(address)

            if ctx.get(top.d_bus_cyc) and ctx.get(top.d_bus_stb):
                address = ctx.get(top.d_bus_adr)
                if not observed['seen_d_addresses'] or observed['seen_d_addresses'][-1] != address:
                    observed['seen_d_addresses'].append(address)
                ctx.set(top.d_bus_dat_r, data_lines.get(address, 0))
                ctx.set(top.d_bus_ack, 1)

            request_active_last = request_active
            await ctx.tick()

    async def checker_process(ctx):
        ctx.set(top.irq_lines, 0)
        for _ in range(64):
            if ctx.get(top.halted) or ctx.get(top.locked_up):
                break
            await ctx.tick()
        observed['halted'] = ctx.get(top.halted)
        observed['locked_up'] = ctx.get(top.locked_up)

    sim.add_testbench(bus_process, background=True)
    sim.add_testbench(checker_process)
    sim.run_until(80e-6)

    assert observed['halted'] == 1
    assert observed['locked_up'] == 0
    assert observed['seen_i_addresses'][:4] == [0x00, 0x08, 0x10, 0xB8]
    assert observed['seen_d_addresses'] == [0x08]


def test_litex_top_v3_stage0_bootrom_handoff_survives_delayed_data_ack() -> None:
    top = Little64LiteXTop(Little64CoreConfig(core_variant='v3', cache_topology='none', reset_vector=0))
    sim = Simulator(top)
    sim.add_clock(1e-6)

    instruction_lines = {
        0x00: 0xE004_B10D_940D_800D,
        0x08: 0x0000_0000_0000_00BE,
        0x10: 0x1021_1002_101F_43B1,
        0x18: 0x10A4_83F1_6C1A_C209,
        0xB8: 0xDF00 << 48,
    }
    data_lines = {
        0x08: 0x0000_0000_0000_00BE,
    }

    observed = {
        'halted': 0,
        'locked_up': 0,
        'seen_fetch_pcs': [],
        'seen_i_addresses': [],
        'seen_d_addresses': [],
    }
    pending_i_response: dict[str, int] = {}
    pending_d_response: dict[str, int] = {}

    async def bus_process(ctx):
        request_active_last = False
        while True:
            ctx.set(top.i_bus_ack, 0)
            ctx.set(top.i_bus_err, 0)
            ctx.set(top.i_bus_dat_r, 0)
            ctx.set(top.d_bus_ack, 0)
            ctx.set(top.d_bus_err, 0)
            ctx.set(top.d_bus_dat_r, 0)

            observed['seen_fetch_pcs'].append(ctx.get(top.shim.core.fetch_pc))

            if pending_i_response:
                pending_i_response['delay'] -= 1
                if pending_i_response['delay'] < 0:
                    address = pending_i_response['address']
                    ctx.set(top.i_bus_dat_r, instruction_lines.get(address, 0))
                    ctx.set(top.i_bus_ack, 1)
                    pending_i_response.clear()

            if pending_d_response:
                pending_d_response['delay'] -= 1
                if pending_d_response['delay'] < 0:
                    address = pending_d_response['address']
                    ctx.set(top.d_bus_dat_r, data_lines.get(address, 0))
                    ctx.set(top.d_bus_ack, 1)
                    pending_d_response.clear()

            request_active = ctx.get(top.i_bus_cyc) and ctx.get(top.i_bus_stb)
            if request_active and not request_active_last and not pending_i_response:
                address = ctx.get(top.i_bus_adr)
                observed['seen_i_addresses'].append(address)
                pending_i_response.update(address=address, delay=1)

            if ctx.get(top.d_bus_cyc) and ctx.get(top.d_bus_stb) and not pending_d_response:
                address = ctx.get(top.d_bus_adr)
                observed['seen_d_addresses'].append(address)
                pending_d_response.update(address=address, delay=4)

            request_active_last = request_active
            await ctx.tick()

    async def checker_process(ctx):
        ctx.set(top.irq_lines, 0)
        for _ in range(96):
            if ctx.get(top.halted) or ctx.get(top.locked_up):
                break
            await ctx.tick()
        observed['halted'] = ctx.get(top.halted)
        observed['locked_up'] = ctx.get(top.locked_up)

    sim.add_testbench(bus_process, background=True)
    sim.add_testbench(checker_process)
    sim.run_until(120e-6)

    assert observed['halted'] == 1
    assert observed['locked_up'] == 0
    assert observed['seen_i_addresses'][:4] == [0x00, 0x08, 0x10, 0xB8]
    assert observed['seen_d_addresses'] == [0x08, 0x08]
    assert 0xBE in observed['seen_fetch_pcs']


def test_emit_litex_cpu_verilog_writes_named_module(tmp_path) -> None:
    output_path = tmp_path / 'little64_litex_cpu_top.v'

    emit_litex_cpu_verilog(output_path, module_name='little64_test_top')

    verilog_text = output_path.read_text(encoding='utf-8')
    assert 'module little64_test_top' in verilog_text
    assert 'i_bus_adr' in verilog_text
    assert 'd_bus_adr' in verilog_text
    assert 'irq_lines' in verilog_text
    assert not re.search(
        r"(?m)^[ \t]*\(\* full_case = 32'd1 \*\)[ \t]*\n(?:^[ \t]*\n)*(?=[ \t]*end\b)",
        verilog_text,
    )


def test_arty_build_script_sanitizes_build_name_for_verilog() -> None:
    assert _BUILD_ARTY_BITSTREAM._sanitize_build_name('little64-arty-a7-35') == 'little64_arty_a7_35'


def test_arty_build_script_resolves_boot_artifact_paths(tmp_path) -> None:
    paths = _BUILD_ARTY_BITSTREAM._boot_artifact_paths(tmp_path, 'little64_arty_a7_35')

    assert paths['dts'] == tmp_path / 'boot' / 'little64_arty_a7_35.dts'
    assert paths['dtb'] == tmp_path / 'boot' / 'little64_arty_a7_35.dtb'
    assert paths['bootrom'] == tmp_path / 'boot' / 'little64_arty_a7_35_sd_bootrom.bin'
    assert paths['sd_image'] == tmp_path / 'boot' / 'little64_arty_a7_35_sdcard.img'


def test_arty_build_script_composes_sd_bootargs() -> None:
    assert _BUILD_ARTY_BITSTREAM._compose_arty_bootargs(
        uart_origin=0xF0001000,
        include_rootfs=True,
    ) == 'console=liteuart earlycon=liteuart,0xf0001000 ignore_loglevel loglevel=8 root=/dev/mmcblk0p2 rootwait init=/init'


def test_arty_build_script_cleans_builder_outputs_only(tmp_path) -> None:
    for child in ('gateware', 'software', 'boot'):
        path = tmp_path / child
        path.mkdir(parents=True)
        (path / 'stamp.txt').write_text('x', encoding='utf-8')
    preserved = tmp_path / 'keep.txt'
    preserved.write_text('keep', encoding='utf-8')

    _BUILD_ARTY_BITSTREAM._clean_litex_output(tmp_path)

    assert not (tmp_path / 'gateware').exists()
    assert not (tmp_path / 'software').exists()
    assert not (tmp_path / 'boot').exists()
    assert preserved.exists()


def test_arty_build_script_patches_vendor_primitive_ports(tmp_path) -> None:
    gateware_dir = tmp_path / 'gateware'
    gateware_dir.mkdir()
    verilog_path = gateware_dir / 'little64_arty_a7_35.v'
    verilog_path.write_text(
        '\n'.join([
            'module little64_arty_a7_35(',
            '\tinput clk,',
            '\tinout io_p,',
            '\tinout io_n',
            ');',
            'IDELAYCTRL IDELAYCTRL(',
            '\t.REFCLK (clk),',
            '\t.RST    (1\'d0)',
            ');',
            'OSERDESE2 #( .DATA_WIDTH(4\'d8) ) OSERDESE2 (',
            '\t.CLK    (clk),',
            '\t.CLKDIV (clk),',
            '\t.D1     (1\'d0),',
            '\t.D2     (1\'d0),',
            '\t.D3     (1\'d0),',
            '\t.D4     (1\'d0),',
            '\t.D5     (1\'d0),',
            '\t.D6     (1\'d0),',
            '\t.D7     (1\'d0),',
            '\t.D8     (1\'d0),',
            '\t.OCE    (1\'d1),',
            '\t.RST    (1\'d0),',
            '\t.OQ     ()',
            ');',
            'ISERDESE2 #( .DATA_WIDTH(4\'d8) ) ISERDESE2 (',
            '\t.BITSLIP (1\'d0),',
            '\t.CE1     (1\'d1),',
            '\t.CLK     (clk),',
            '\t.CLKB    (~clk),',
            '\t.CLKDIV  (clk),',
            '\t.DDLY    (1\'d0),',
            '\t.RST     (1\'d0),',
            '\t.Q1      (),',
            '\t.Q2      (),',
            '\t.Q3      (),',
            '\t.Q4      (),',
            '\t.Q5      (),',
            '\t.Q6      (),',
            '\t.Q7      (),',
            '\t.Q8      ()',
            ');',
            'IDELAYE2 #( .IDELAY_TYPE("VARIABLE") ) IDELAYE2 (',
            '\t.C        (clk),',
            '\t.CE       (1\'d0),',
            '\t.IDATAIN  (1\'d0),',
            '\t.INC      (1\'d0),',
            '\t.LD       (1\'d0),',
            '\t.LDPIPEEN (1\'d0),',
            '\t.DATAOUT  ()',
            ');',
            'IOBUFDS IOBUFDS(',
            '\t.I   (1\'d0),',
            '\t.T   (1\'d0),',
            '\t.IO  (io_p),',
            '\t.IOB (io_n)',
            ');',
            'PLLE2_ADV #( .CLKFBOUT_MULT(5\'d16) ) PLLE2_ADV (',
            '\t.CLKFBIN  (clk),',
            '\t.CLKIN1   (clk),',
            '\t.PWRDWN   (1\'d0),',
            '\t.RST      (1\'d0),',
            '\t.CLKFBOUT (),',
            '\t.CLKOUT0  (),',
            '\t.CLKOUT1  (),',
            '\t.CLKOUT2  (),',
            '\t.CLKOUT3  (),',
            '\t.LOCKED   ()',
            ');',
            'endmodule',
            '',
        ]),
        encoding='utf-8',
    )

    assert _BUILD_ARTY_BITSTREAM._patch_generated_arty_verilog(gateware_dir, 'little64_arty_a7_35') is True

    patched = verilog_path.read_text(encoding='utf-8')
    assert 'wire little64_vendor_unused_idelayctrl_idelayctrl_rdy;' in patched
    assert '.RDY        (little64_vendor_unused_idelayctrl_idelayctrl_rdy)' in patched
    assert re.search(r"\.SHIFTIN1\s+\(1'd0\)", patched)
    assert re.search(r"\.TBYTEIN\s+\(1'd0\)", patched)
    assert 'wire little64_vendor_unused_oserdese2_oserdese2_shiftout1;' in patched
    assert re.search(r"\.CE2\s+\(1'd0\)", patched)
    assert 'wire [4:0] little64_vendor_unused_idelaye2_idelaye2_cntvalueout;' in patched
    assert 'wire little64_vendor_unused_iobufds_iobufds_o;' in patched
    assert re.search(r"\.CLKINSEL\s+\(1'd1\)", patched)
    assert 'wire [15:0] little64_vendor_unused_plle2_adv_plle2_adv_do;' in patched


def test_arty_build_script_rejects_generate_only_programming_combo() -> None:
    args = type('Args', (), {'generate_only': True, 'program_only': False})()

    with pytest.raises(SystemExit, match='--generate-only cannot be combined with --program'):
        _BUILD_ARTY_BITSTREAM._validate_requested_actions(
            args,
            (_BUILD_ARTY_BITSTREAM.PROGRAM_OPERATION_VOLATILE,),
        )


def test_arty_build_script_auto_programmer_prefers_vivado_for_flash() -> None:
    backend = _BUILD_ARTY_BITSTREAM._resolve_programmer_backend(
        requested_backend=_BUILD_ARTY_BITSTREAM.PROGRAMMER_AUTO,
        operations=(_BUILD_ARTY_BITSTREAM.PROGRAM_OPERATION_FLASH,),
        vivado_available=True,
        openocd_available=True,
    )

    assert backend == _BUILD_ARTY_BITSTREAM.PROGRAMMER_VIVADO


def test_arty_build_script_resolves_programming_artifacts(tmp_path) -> None:
    assert _BUILD_ARTY_BITSTREAM._resolve_programming_artifact(
        tmp_path,
        'little64_arty_a7_35',
        _BUILD_ARTY_BITSTREAM.PROGRAM_OPERATION_VOLATILE,
    ) == tmp_path / 'gateware' / 'little64_arty_a7_35.bit'
    assert _BUILD_ARTY_BITSTREAM._resolve_programming_artifact(
        tmp_path,
        'little64_arty_a7_35',
        _BUILD_ARTY_BITSTREAM.PROGRAM_OPERATION_FLASH,
    ) == tmp_path / 'gateware' / 'little64_arty_a7_35.bin'


def test_build_sd_boot_artifacts_pads_bootrom_image(tmp_path, monkeypatch) -> None:
    kernel_elf = tmp_path / 'vmlinux'
    dtb = tmp_path / 'system.dtb'
    rootfs = tmp_path / 'rootfs.ext4'
    bootrom_output = tmp_path / 'bootrom.bin'
    sd_output = tmp_path / 'sdcard.img'
    kernel_elf.write_bytes(b'kernel')
    dtb.write_bytes(b'dtb')
    rootfs.write_bytes(b'rootfs')

    monkeypatch.setattr(_BUILD_SD_BOOT_ARTIFACTS, '_write_stage0_header', lambda *args, **kwargs: None)
    monkeypatch.setattr(_BUILD_SD_BOOT_ARTIFACTS, '_write_stage0_generated_support', lambda *args, **kwargs: None)
    monkeypatch.setattr(_BUILD_SD_BOOT_ARTIFACTS, '_build_stage0', lambda *args, **kwargs: b'\x01\x02\x03\x04')
    captured: dict[str, object] = {}

    def fake_write_sd_card_image(path, **kwargs):
        captured['path'] = path
        captured['kwargs'] = kwargs

    monkeypatch.setattr(_BUILD_SD_BOOT_ARTIFACTS, 'write_litex_sd_card_image', fake_write_sd_card_image)

    fake_soc = type(
        'FakeSoC',
        (),
        {
            'boot_source': 'bootrom',
            'litex_target': type('FakeTarget', (), {'integrated_rom_size': 0x80})(),
        },
    )()

    _BUILD_SD_BOOT_ARTIFACTS.build_litex_sd_boot_artifacts(
        soc=fake_soc,
        kernel_elf=kernel_elf,
        dtb=dtb,
        bootrom_output=bootrom_output,
        sd_output=sd_output,
        ram_base=0x40000000,
        ram_size=0x1000,
        kernel_physical_base=0x40000000,
        rootfs_image=rootfs,
    )

    assert bootrom_output.read_bytes()[:4] == b'\x01\x02\x03\x04'
    assert len(bootrom_output.read_bytes()) == 0x1000
    assert captured['path'] == sd_output


def test_sd_build_machine_mode_resolves_default_kernel_and_generates_dtb(tmp_path, monkeypatch) -> None:
    kernel_elf = tmp_path / 'vmlinux'
    kernel_elf.write_bytes(b'kernel')
    output_dir = tmp_path / 'artifacts'
    captured: dict[str, object] = {}

    def fake_write_generated_dts(**kwargs):
        captured['dts_kwargs'] = kwargs
        output_path = kwargs['output_path']
        output_path.write_text('/dts-v1/;\n', encoding='utf-8')
        return output_path

    def fake_compile_dts_to_dtb(dts_path, *, dtb_path=None, only_if_stale=False):
        assert only_if_stale is True
        assert dts_path == output_dir / 'little64-litex-sim.dts'
        resolved = dtb_path or dts_path.with_suffix('.dtb')
        resolved.write_bytes(b'dtb')
        return resolved

    def fake_build_artifacts(**kwargs):
        captured['build_kwargs'] = kwargs

    class FakeSoC:
        def __init__(self, **kwargs) -> None:
            captured['soc_kwargs'] = kwargs

    monkeypatch.setattr(_BUILD_SD_BOOT_ARTIFACTS, 'default_kernel_for_machine', lambda machine: kernel_elf)
    monkeypatch.setattr(_BUILD_SD_BOOT_ARTIFACTS, 'ensure_litex_kernel_support', lambda path: None)
    monkeypatch.setattr(_BUILD_SD_BOOT_ARTIFACTS, 'recorded_defconfig_for_machine', lambda machine: 'little64_litex_sim_defconfig')
    monkeypatch.setattr(_BUILD_SD_BOOT_ARTIFACTS, '_write_generated_dts', fake_write_generated_dts)
    monkeypatch.setattr(_BUILD_SD_BOOT_ARTIFACTS, 'compile_dts_to_dtb', fake_compile_dts_to_dtb)
    monkeypatch.setattr(_BUILD_SD_BOOT_ARTIFACTS, 'build_litex_sd_boot_artifacts', fake_build_artifacts)
    monkeypatch.setattr(_BUILD_SD_BOOT_ARTIFACTS, 'Little64LiteXSimSoC', FakeSoC)

    assert _BUILD_SD_BOOT_ARTIFACTS.main(['--machine', 'litex', '--output-dir', str(output_dir)]) == 0

    assert captured['dts_kwargs'] == {
        'output_path': output_dir / 'little64-litex-sim.dts',
        'cpu_variant': 'standard',
        'litex_target': 'arty-a7-35',
        'boot_source': 'bootrom',
        'ram_size': 0x1000_0000,
        'with_sdram': True,
        'with_spi_flash': False,
    }
    assert captured['soc_kwargs']['litex_target'] == 'arty-a7-35'
    assert captured['soc_kwargs']['boot_source'] == 'bootrom'
    assert captured['build_kwargs']['kernel_elf'] == kernel_elf
    assert captured['build_kwargs']['dtb'] == output_dir / 'little64-litex-sim.dtb'
    assert captured['build_kwargs']['bootrom_output'] == output_dir / 'little64-sd-stage0-bootrom.bin'
    assert captured['build_kwargs']['sd_output'] == output_dir / 'little64-linux-sdcard.img'


def test_sd_build_machine_mode_uses_spiflash_stage0_defaults(tmp_path, monkeypatch) -> None:
    kernel_elf = tmp_path / 'vmlinux'
    kernel_elf.write_bytes(b'kernel')
    output_dir = tmp_path / 'artifacts'
    captured: dict[str, object] = {}

    monkeypatch.setattr(_BUILD_SD_BOOT_ARTIFACTS, 'default_kernel_for_machine', lambda machine: kernel_elf)
    monkeypatch.setattr(_BUILD_SD_BOOT_ARTIFACTS, 'ensure_litex_kernel_support', lambda path: None)
    monkeypatch.setattr(_BUILD_SD_BOOT_ARTIFACTS, 'recorded_defconfig_for_machine', lambda machine: 'little64_litex_sim_defconfig')
    monkeypatch.setattr(
        _BUILD_SD_BOOT_ARTIFACTS,
        '_write_generated_dts',
        lambda **kwargs: (kwargs['output_path'].parent.mkdir(parents=True, exist_ok=True), kwargs['output_path'].write_text('/dts-v1/;\n', encoding='utf-8'), kwargs['output_path'])[-1],
    )
    monkeypatch.setattr(
        _BUILD_SD_BOOT_ARTIFACTS,
        'compile_dts_to_dtb',
        lambda dts_path, *, dtb_path=None, only_if_stale=False: (dtb_path.write_bytes(b'dtb'), dtb_path)[1],
    )
    monkeypatch.setattr(_BUILD_SD_BOOT_ARTIFACTS, 'Little64LiteXSimSoC', lambda **kwargs: object())
    monkeypatch.setattr(_BUILD_SD_BOOT_ARTIFACTS, 'build_litex_sd_boot_artifacts', lambda **kwargs: captured.setdefault('build_kwargs', kwargs))

    assert _BUILD_SD_BOOT_ARTIFACTS.main([
        '--machine', 'litex',
        '--output-dir', str(output_dir),
        '--boot-source', 'spiflash',
    ]) == 0

    assert captured['build_kwargs']['bootrom_output'] == output_dir / 'little64-sd-stage0-spiflash.bin'
    assert captured['build_kwargs']['stage0_linker'] == Path('target/c_boot/linker_litex_spi_boot.ld')


def test_sd_build_explicit_mode_keeps_legacy_inputs(tmp_path, monkeypatch) -> None:
    kernel_elf = tmp_path / 'vmlinux'
    dtb = tmp_path / 'system.dtb'
    bootrom_output = tmp_path / 'bootrom.bin'
    sd_output = tmp_path / 'sdcard.img'
    kernel_elf.write_bytes(b'kernel')
    dtb.write_bytes(b'dtb')
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        _BUILD_SD_BOOT_ARTIFACTS,
        '_write_generated_dts',
        lambda **kwargs: (_ for _ in ()).throw(AssertionError('machine-mode DTS generation should not run in explicit mode')),
    )
    monkeypatch.setattr(
        _BUILD_SD_BOOT_ARTIFACTS,
        'default_kernel_for_machine',
        lambda machine: (_ for _ in ()).throw(AssertionError('default kernel lookup should not run in explicit mode')),
    )

    class FakeSoC:
        def __init__(self, **kwargs) -> None:
            captured['soc_kwargs'] = kwargs

    monkeypatch.setattr(_BUILD_SD_BOOT_ARTIFACTS, 'Little64LiteXSimSoC', FakeSoC)
    monkeypatch.setattr(_BUILD_SD_BOOT_ARTIFACTS, 'build_litex_sd_boot_artifacts', lambda **kwargs: captured.setdefault('build_kwargs', kwargs))

    assert _BUILD_SD_BOOT_ARTIFACTS.main([
        '--kernel-elf', str(kernel_elf),
        '--dtb', str(dtb),
        '--bootrom-output', str(bootrom_output),
        '--sd-output', str(sd_output),
    ]) == 0

    assert captured['soc_kwargs']['litex_target'] == 'sim-bootrom'
    assert captured['soc_kwargs']['boot_source'] == 'bootrom'
    assert captured['build_kwargs']['kernel_elf'] == kernel_elf
    assert captured['build_kwargs']['dtb'] == dtb
    assert captured['build_kwargs']['bootrom_output'] == bootrom_output
    assert captured['build_kwargs']['sd_output'] == sd_output


def test_pack_litex_memory_words_matches_litex_big_endian_word_order() -> None:
    words = _BUILD_SD_BOOT_ARTIFACTS.pack_litex_memory_words(
        b'\x11\x22\x33\x44\x55\x66\x77\x88\x99',
        data_width=64,
        endianness='big',
    )

    assert words == [0x5566778811223344, 0x0000000099000000]


def test_register_little64_with_litex_exposes_cpu_plugin() -> None:
    cpu_cls = register_little64_with_litex(force=True)

    assert cpu_cls is Little64


def test_litex_cpu_variant_names_resolve_to_core_variants() -> None:
    assert resolve_litex_core_variant('standard') == 'v2'
    assert resolve_litex_core_variant('standard-basic') == 'basic'
    assert resolve_litex_core_variant('standard-v2') == 'v2'
    assert resolve_litex_core_variant('standard-v2-none') == 'v2'
    assert resolve_litex_core_variant('standard-v2-unified') == 'v2'
    assert resolve_litex_core_variant('standard-v2-split') == 'v2'
    assert resolve_litex_core_variant('standard-v3') == 'v3'
    assert resolve_litex_core_variant('standard-v3-none') == 'v3'
    assert resolve_litex_core_variant('standard-v3-unified') == 'v3'
    assert resolve_litex_core_variant('standard-v3-split') == 'v3'


def test_litex_cpu_variant_names_resolve_to_cache_topologies() -> None:
    assert resolve_litex_cache_topology('standard') == 'none'
    assert resolve_litex_cache_topology('standard-basic') == 'none'
    assert resolve_litex_cache_topology('standard-v2') == 'none'
    assert resolve_litex_cache_topology('standard-v2-none') == 'none'
    assert resolve_litex_cache_topology('standard-v2-unified') == 'unified'
    assert resolve_litex_cache_topology('standard-v2-split') == 'split'
    assert resolve_litex_cache_topology('standard-v3') == 'none'
    assert resolve_litex_cache_topology('standard-v3-none') == 'none'
    assert resolve_litex_cache_topology('standard-v3-unified') == 'unified'
    assert resolve_litex_cache_topology('standard-v3-split') == 'split'


def test_litex_variant_config_builder_preserves_reset_vector() -> None:
    config = config_for_litex_variant('standard-v2-split', reset_vector=0x1234)

    assert config.reset_vector == 0x1234
    assert config.core_variant == 'v2'
    assert config.cache_topology == 'split'


def test_litex_cpu_can_select_v2_cache_topology_variants() -> None:
    cpu = Little64(type('Platform', (), {'output_dir': 'builddir'})(), variant='standard-v2-unified')

    assert cpu.core_config.core_variant == 'v2'
    assert cpu.core_config.cache_topology == 'unified'


def test_litex_cpu_can_select_v3_variant() -> None:
    cpu = Little64(type('Platform', (), {'output_dir': 'builddir'})(), variant='standard-v3')

    assert cpu.core_config.core_variant == 'v3'
    assert cpu.core_config.cache_topology == 'none'


def test_litex_cpu_can_select_v3_cache_topology_variants() -> None:
    cpu = Little64(type('Platform', (), {'output_dir': 'builddir'})(), variant='standard-v3-split')

    assert cpu.core_config.core_variant == 'v3'
    assert cpu.core_config.cache_topology == 'split'


def test_litex_cpu_standard_variant_defaults_to_v2() -> None:
    cpu = Little64(type('Platform', (), {'output_dir': 'builddir'})(), variant='standard')

    assert cpu.core_config.core_variant == 'v2'
    assert cpu.core_config.cache_topology == 'none'


def test_litex_cpu_can_select_basic_variant_explicitly() -> None:
    cpu = Little64(type('Platform', (), {'output_dir': 'builddir'})(), variant='standard-basic')

    assert cpu.core_config.core_variant == 'basic'
    assert cpu.core_config.cache_topology == 'none'


def test_litex_sim_soc_can_select_v2_variant() -> None:
    soc = Little64LiteXSimSoC(cpu_variant='standard-v2-split')

    assert soc.cpu.variant == 'standard-v2-split'
    assert soc.cpu.core_config.core_variant == 'v2'
    assert soc.cpu.core_config.cache_topology == 'split'


def test_litex_sim_soc_can_select_v3_variant() -> None:
    soc = Little64LiteXSimSoC(cpu_variant='standard-v3')

    assert soc.cpu.variant == 'standard-v3'
    assert soc.cpu.core_config.core_variant == 'v3'
    assert soc.cpu.core_config.cache_topology == 'none'


def test_litex_sim_soc_can_select_v3_cache_variant() -> None:
    soc = Little64LiteXSimSoC(cpu_variant='standard-v3-unified')

    assert soc.cpu.variant == 'standard-v3-unified'
    assert soc.cpu.core_config.core_variant == 'v3'
    assert soc.cpu.core_config.cache_topology == 'unified'


def test_litex_sim_soc_defaults_to_v2_variant() -> None:
    soc = Little64LiteXSimSoC()

    assert soc.cpu.variant == 'standard'
    assert soc.cpu.core_config.core_variant == 'v2'
    assert soc.cpu.core_config.cache_topology == 'none'


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
    bus_ack_cycles: list[int] = []
    cpu_ack_cycles: list[int] = []

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

    def monitor():
        for cycle in range(12):
            if (yield bridge.bus.ack):
                bus_ack_cycles.append(cycle)
            if (yield bridge.cpu_ack):
                cpu_ack_cycles.append(cycle)
            yield

    from migen.sim import run_simulation

    run_simulation(bridge, [cpu_driver(), wb_target(), monitor()])

    assert seen_transactions == [(0x10, 0xFE, 0), (0x11, 0x01, 0)]
    assert read_results == [0x0807060504030201]
    assert bus_ack_cycles
    assert cpu_ack_cycles
    assert cpu_ack_cycles[0] > bus_ack_cycles[-1]


def test_litex_timer_ignores_partial_interval_writes() -> None:
    timer = Little64LinuxTimer(sys_clk_freq=1_000_000)
    observed: dict[str, int] = {}
    word_base = 0x08001000 >> 3

    def process():
        yield timer.bus.adr.eq(word_base + 2)
        yield timer.bus.dat_w.eq(0xAA)
        yield timer.bus.sel.eq(0x01)
        yield timer.bus.we.eq(1)
        yield timer.bus.cyc.eq(1)
        yield timer.bus.stb.eq(1)
        for _ in range(4):
            if (yield timer.bus.ack):
                break
            yield
        yield timer.bus.cyc.eq(0)
        yield timer.bus.stb.eq(0)
        yield timer.bus.we.eq(0)
        yield

        yield timer.bus.adr.eq(word_base + 2)
        yield timer.bus.sel.eq(0xFF)
        yield timer.bus.cyc.eq(1)
        yield timer.bus.stb.eq(1)
        for _ in range(4):
            if (yield timer.bus.ack):
                observed['cycle_interval'] = (yield timer.bus.dat_r)
                break
            yield
        yield timer.bus.cyc.eq(0)
        yield timer.bus.stb.eq(0)
        for _ in range(32):
            yield
        observed['irq'] = (yield timer.irq)

    from migen.sim import run_simulation

    run_simulation(timer, process())

    assert observed['cycle_interval'] == 0
    assert observed['irq'] == 0


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
    assert 'memory@40000000' in dts_text


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


def test_arty_hardware_soc_exposes_uart_phy_tuning_word_by_default(tmp_path) -> None:
    mapping = resolve_arty_spi_sdcard_mapping(connector='arduino', adapter='digilent')
    soc = Little64LiteXArtySoC(spisdcard_mapping=mapping)
    soc.platform.output_dir = str(tmp_path / 'litex-arty-hw-stage0')

    soc.finalize()
    uart_region = soc.csr.regions.get('uart')
    uart_phy_region = soc.csr.regions.get('uart_phy')
    expected_tuning_word = _BUILD_SD_BOOT_ARTIFACTS._litex_uart_tuning_word(soc.sys_clk_freq, 115200)

    assert uart_region is not None
    assert uart_phy_region is not None
    assert uart_phy_region.origin > uart_region.origin
    assert [csr.size for csr in uart_phy_region.obj] == [32]
    assert expected_tuning_word == (115200 << 32) // soc.sys_clk_freq
    assert soc.cpu.variant == 'standard'
    assert soc.cpu.core_config.core_variant == 'v2'


def test_arty_hardware_soc_can_select_basic_variant_explicitly(tmp_path) -> None:
    mapping = resolve_arty_spi_sdcard_mapping(connector='arduino', adapter='digilent')
    soc = Little64LiteXArtySoC(cpu_variant='standard-basic', spisdcard_mapping=mapping)
    soc.platform.output_dir = str(tmp_path / 'litex-arty-hw-basic')

    soc.finalize()

    assert soc.cpu.variant == 'standard-basic'
    assert soc.cpu.core_config.core_variant == 'basic'
    assert soc.cpu.core_config.cache_topology == 'none'


def test_arty_hardware_soc_wires_debug_leds(tmp_path) -> None:
    mapping = resolve_arty_spi_sdcard_mapping(connector='arduino', adapter='digilent')
    soc = Little64LiteXArtySoC(spisdcard_mapping=mapping)
    soc.platform.output_dir = str(tmp_path / 'litex-arty-hw-leds')

    soc.finalize()

    assert len(soc.arty_user_led_pads) == 4
    assert len(soc.arty_rgb_led_pads) == 4
    assert hasattr(soc.arty_rgb_led_pads[0], 'r')
    assert hasattr(soc.arty_rgb_led_pads[0], 'g')
    assert hasattr(soc.arty_rgb_led_pads[0], 'b')
    assert soc.arty_led_halted is not None
    assert soc.arty_led_locked_up is not None
    assert soc.arty_led_i_bus_activity is not None
    assert soc.arty_led_d_bus_activity is not None
    assert soc.arty_led_store_activity is not None
    assert soc.arty_led_running_heartbeat is not None
    assert soc.arty_led_irq_pending is not None


def test_stage0_artifact_builder_emits_spi_sd_header_for_arty_hardware(tmp_path) -> None:
    mapping = resolve_arty_spi_sdcard_mapping(connector='arduino', adapter='digilent')
    soc = Little64LiteXArtySoC(spisdcard_mapping=mapping)
    soc.platform.output_dir = str(tmp_path / 'litex-arty-hw-stage0-spi')

    regs_header = tmp_path / 'litex_sd_boot_regs.h'
    _BUILD_SD_BOOT_ARTIFACTS._write_stage0_header(
        regs_header,
        soc=soc,
        ram_base=0x40000000,
        ram_size=0x10000000,
        kernel_physical_base=0x40000000,
    )

    regs_text = regs_header.read_text(encoding='utf-8')

    assert '#define L64_SDCARD_INTERFACE_SPI 1' in regs_text
    assert '#define L64_SDCARD_SPI_BASE ' in regs_text
    assert '#define L64_SDCARD_SPI_DATA_WIDTH 32U' in regs_text
    assert '#define L64_SDCARD_SPI_CONTROL_ADDR ' in regs_text
    assert '#define L64_SDCARD_CORE_BASE ' not in regs_text
    assert soc.spisdcard.data_width == 32


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


def test_stage0_artifact_builder_matches_emulator_bootrom_uart_layout_without_spiflash(tmp_path) -> None:
    target = LITTLE64_LITEX_TARGET_CONFIGS['sim-bootrom']
    soc = Little64LiteXSimSoC(
        litex_target='sim-bootrom',
        boot_source='bootrom',
        integrated_main_ram_size=target.default_ram_size,
        main_ram_size=target.default_ram_size,
        with_sdcard=True,
        with_spi_flash=target.with_spi_flash,
        with_timer=True,
        integrated_rom_init=[],
    )
    soc.platform.output_dir = str(tmp_path / 'litex-sim-bootrom-stage0-uart-layout')
    soc.finalize()

    regs_header = tmp_path / 'litex_sd_boot_regs.h'
    _BUILD_SD_BOOT_ARTIFACTS._write_stage0_header(
        regs_header,
        soc=soc,
        ram_base=target.main_ram_base,
        ram_size=target.default_ram_size,
        kernel_physical_base=target.main_ram_base,
        emulator_bootrom_uart_layout=True,
    )

    regs_text = regs_header.read_text(encoding='utf-8')

    assert 'spiflash_core' not in soc.csr.regions
    assert soc.csr.regions['uart'].origin == 0xF0004000
    assert '#define L64_UART_BASE 0x00000000f0004000ULL' in regs_text


def test_stage0_artifact_builder_keeps_spiflash_layout_when_boot_source_is_spiflash(tmp_path) -> None:
    target = LITTLE64_LITEX_TARGET_CONFIGS['sim-bootrom']
    soc = Little64LiteXSimSoC(
        litex_target='sim-bootrom',
        boot_source='spiflash',
        integrated_main_ram_size=0x0400_0000,
        main_ram_size=0x0400_0000,
        with_sdcard=True,
        with_spi_flash=True,
        with_timer=True,
    )
    soc.platform.output_dir = str(tmp_path / 'litex-sim-spiflash-stage0-uart-layout')
    soc.finalize()

    regs_header = tmp_path / 'litex_sd_boot_regs.h'
    _BUILD_SD_BOOT_ARTIFACTS._write_stage0_header(
        regs_header,
        soc=soc,
        ram_base=0,
        ram_size=0x0400_0000,
        kernel_physical_base=0x4000_0000,
    )

    regs_text = regs_header.read_text(encoding='utf-8')

    assert 'spiflash_core' in soc.csr.regions
    assert soc.csr.regions['spiflash_core'].origin == 0xF0003800
    assert soc.csr.regions['uart'].origin == 0xF0004000
    assert '#define L64_UART_BASE 0x00000000f0004000ULL' in regs_text


def test_stage0_artifact_builder_uses_raw_sim_uart_layout_by_default(tmp_path) -> None:
    target = LITTLE64_LITEX_TARGET_CONFIGS['sim-bootrom']
    soc = Little64LiteXSimSoC(
        litex_target='sim-bootrom',
        boot_source='bootrom',
        integrated_main_ram_size=target.default_ram_size,
        main_ram_size=target.default_ram_size,
        with_sdcard=True,
        with_spi_flash=target.with_spi_flash,
        with_timer=True,
        integrated_rom_init=[],
    )
    soc.platform.output_dir = str(tmp_path / 'litex-sim-bootrom-stage0-uart-raw')
    soc.finalize()

    regs_header = tmp_path / 'litex_sd_boot_regs.h'
    _BUILD_SD_BOOT_ARTIFACTS._write_stage0_header(
        regs_header,
        soc=soc,
        ram_base=target.main_ram_base,
        ram_size=target.default_ram_size,
        kernel_physical_base=target.main_ram_base,
    )

    regs_text = regs_header.read_text(encoding='utf-8')

    assert soc.csr.regions['uart'].origin == 0xF0004000
    assert '#define L64_UART_BASE 0x00000000f0004000ULL' in regs_text


def test_litex_sim_soc_keeps_reserved_csr_layout_across_optional_features(tmp_path) -> None:
    base_soc = Little64LiteXSimSoC(litex_target='sim-bootrom', with_sdcard=True)
    base_soc.platform.output_dir = str(tmp_path / 'litex-sim-bootrom-base')
    base_soc.finalize()

    sdram_soc = Little64LiteXSimSoC(litex_target='sim-bootrom', with_sdcard=True, with_sdram=True)
    sdram_soc.platform.output_dir = str(tmp_path / 'litex-sim-bootrom-sdram')
    sdram_soc.finalize()

    flash_soc = Little64LiteXSimSoC(litex_target='sim-bootrom', with_sdcard=True, with_spi_flash=True)
    flash_soc.platform.output_dir = str(tmp_path / 'litex-sim-bootrom-flash')
    flash_soc.finalize()

    expected_sdcard_map = {
        'sdcard_block2mem': 0xF0000800,
        'sdcard_core': 0xF0001000,
        'sdcard_irq': 0xF0001800,
        'sdcard_mem2block': 0xF0002000,
        'sdcard_phy': 0xF0002800,
        'uart': 0xF0004000,
    }

    for name, origin in expected_sdcard_map.items():
        assert base_soc.csr.regions[name].origin == origin
        assert sdram_soc.csr.regions[name].origin == origin
        assert flash_soc.csr.regions[name].origin == origin

    assert sdram_soc.csr.regions['sdram'].origin == 0xF0003000
    assert flash_soc.csr.regions['spiflash_core'].origin == 0xF0003800


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
    assert f'#define L64_UART_BASE 0x{soc.csr.regions["uart"].origin:016x}ULL' in regs_text
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
        bootargs='console=liteuart earlycon=liteuart,0xf0004000 ignore_loglevel loglevel=8',
    )

    assert 'sdcard0 = &mmc0;' in dts_text
    assert 'sys_clk: clock {' in dts_text
    assert 'vreg_mmc: vreg_mmc {' in dts_text
    assert 'uart0: serial@f0004000 {' in dts_text
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
    soc = Little64LiteXSimSoC(litex_target='sim-bootrom', with_sdram=True)
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
        litex_target='sim-bootrom',
        with_sdram=True,
        with_spi_flash=True,
        with_sdcard=True,
        with_timer=True,
        main_ram_size=0x0800_0000,
    )
    soc.platform.output_dir = str(tmp_path / 'litex-sim')

    generated_dts = generate_linux_dts(
        soc,
        model='Little64 LiteX Simulation SoC (Boot ROM)',
        bootargs='root=/dev/mmcblk0p2 rootwait',
    )

    shared_lines = [
        'compatible = "little64,litex-sim", "little64,bootrom";',
        'model = "Little64 LiteX Simulation SoC (Boot ROM)";',
        'bootargs = "root=/dev/mmcblk0p2 rootwait";',
        'memory@40000000',
        'compatible = "litex,liteuart";',
        'serial@f0004000',
        'interrupts = <65>;',
        'compatible = "jedec-flash";',
        'flash@20000000',
        'compatible = "little64,bootrom";',
        'rom@0',
        'compatible = "litex,mmc";',
        'mmc@f0002800',
        'compatible = "little64,timer";',
        'timer@8001000',
        'interrupts = <66>;',
    ]

    for line in shared_lines:
        assert line in built_in_dts
        assert line in generated_dts

    assert 'reg = <0x00000000 0x40000000 0x00000000 0x08000000>;' in built_in_dts
    assert 'reg = <0x00000000 0x40000000 0x00000000 0x08000000>;' in generated_dts
    assert 'reg = <0x00000000 0xf0004000 0x00000000 0x00000100>;' in built_in_dts
    assert 'reg = <0x00000000 0xf0004000 0x00000000 0x00000100>;' in generated_dts
    assert 'reg = <0x00000000 0x20000000 0x00000000 0x01000000>;' in built_in_dts
    assert 'reg = <0x00000000 0x20000000 0x00000000 0x01000000>;' in generated_dts
    assert 'reg = <0x00000000 0x00000000 0x00000000 0x00008000>;' in built_in_dts
    assert 'reg = <0x00000000 0x00000000 0x00000000 0x00008000>;' in generated_dts
    assert 'reg = <0x00000000 0xf0002800 0x00000000 0x00000100>,' in built_in_dts
    assert 'reg = <0x00000000 0xf0002800 0x00000000 0x00000100>,' in generated_dts
    assert '<0x00000000 0xf0001800 0x00000000 0x00000100>;' in built_in_dts
    assert '<0x00000000 0xf0001800 0x00000000 0x00000100>;' in generated_dts
    assert 'reg = <0x00000000 0x08001000 0x00000000 0x00000020>;' in built_in_dts
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
    assert header[5] == LITTLE64_LITEX_BOOTROM_MAIN_RAM_BASE
    assert header[6] == layout.dtb_flash_offset
    assert header[8] == layout.dtb_physical_address
    assert layout.flash_image[layout.kernel_flash_offset:layout.kernel_flash_offset + 4] == kernel_payload
    assert layout.flash_image[layout.dtb_flash_offset:layout.dtb_flash_offset + 3] == dtb


def test_spi_flash_stage0_startup_uses_integrated_sram_stack(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    stage0_source = repo_root / 'target' / 'c_boot' / 'litex_spi_boot.c'
    stage0_linker = repo_root / 'target' / 'c_boot' / 'linker_litex_spi_boot.ld'

    _BUILD_FLASH_IMAGE._build_stage0(stage0_source, stage0_linker, tmp_path)

    disassembly = subprocess.run(
        [
            str(repo_root / 'compilers' / 'bin' / 'llvm-objdump'),
            '--triple=little64',
            '-d',
            str(tmp_path / 'litex_spi_boot.elf'),
        ],
        check=True,
        capture_output=True,
        text=True,
    ).stdout

    start_block = re.search(r'<_start>:(.*?)(?:\n\n|<)', disassembly, re.S)

    assert start_block is not None
    assert re.search(r'LDI\s+#0, R13', start_block.group(1))
    assert re.search(r'LDI\.S1\s+#64, R13', start_block.group(1))
    assert re.search(r'LDI\.S3\s+#16, R13', start_block.group(1))
    assert not re.search(r'LDI\.S2\s+#15, R13', start_block.group(1))


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
    root_dir = disk[root_dir_offset:root_dir_offset + 128]

    assert disk[510:512] == b'\x55\xaa'
    assert disk[446 + 4] == 0x0C
    assert disk[462 + 4] == 0x83
    assert boot_sector[3:11] == b'L64FAT32'
    assert boot_sector[11:13] == b'\x00\x02'
    assert sectors_per_cluster == 1
    assert boot_sector[510:512] == b'\x55\xaa'
    assert root_dir[0:11] == b'VMLINUX    '
    assert root_dir[32:43] == b'BOOT    DTB'
    assert root_dir[64:75] == b'BOOT    CRC'
    assert disk[root_partition_offset:root_partition_offset + len(rootfs)] == rootfs
    assert layout.kernel_file.short_name == b'VMLINUX    '
    assert layout.dtb_file.short_name == b'BOOT    DTB'
    assert layout.checksums_file.short_name == b'BOOT    CRC'
    assert layout.kernel_file.size == len(kernel_payload)
    assert layout.dtb_file.size == len(dtb)
    assert layout.checksums_file.size == BOOT_CHECKSUM_STRUCT.size
    assert layout.checksums.dtb_size == len(dtb)
    assert layout.disk_size_bytes == len(disk)

    checksums_offset = boot_partition_offset + first_data_sector * 512 + (layout.checksums_file.first_cluster - 2) * 512
    manifest = disk[checksums_offset:checksums_offset + BOOT_CHECKSUM_STRUCT.size]
    magic, version, kernel_image_crc32, kernel_image_size, dtb_crc32, dtb_size, _, _ = BOOT_CHECKSUM_STRUCT.unpack(manifest)
    expected_kernel_image = flatten_little64_linux_elf_image(kernel_payload)

    assert magic == BOOT_CHECKSUM_MAGIC
    assert version == BOOT_CHECKSUM_VERSION
    assert kernel_image_crc32 == layout.checksums.kernel_image_crc32
    assert kernel_image_size == len(expected_kernel_image.image)
    assert dtb_crc32 == layout.checksums.dtb_crc32
    assert dtb_size == len(dtb)


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

    assert image.entry_physical == 0x4000_0001
    assert image.image[:2] == b'\xaa\xbb'
    assert image.image_span == 0x1000


def test_llvm_wrapper_generation_creates_triple_prefixed_tools(tmp_path) -> None:
    wrapper_dir = ensure_litex_llvm_toolchain_wrappers(tmp_path)
    gcc_wrapper = wrapper_dir / 'little64-unknown-elf-gcc'
    readelf_wrapper = wrapper_dir / 'little64-unknown-elf-readelf'

    assert gcc_wrapper.exists()
    assert readelf_wrapper.exists()
    assert os.access(gcc_wrapper, os.X_OK)