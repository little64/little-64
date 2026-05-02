#!/usr/bin/env python3

from __future__ import annotations

import argparse
import os
import re
import shutil
import sys
from pathlib import Path
from typing import Any, cast

from little64 import config
from little64.build_support import run_checked
from little64.commands.kernel.build import default_defconfig_for_machine
from little64.hdl_bridge import ensure_hdl_path
from little64.paths import existing_boot_kernel_path, kernel_path, repo_root
from little64.tooling_support import compile_dts_to_dtb
from little64.vivado_support import run_vivado_batch, vivado_settings_script_from_env

REPO_ROOT = repo_root()
HDL_ROOT = ensure_hdl_path(REPO_ROOT)

from litex.build.xilinx import VivadoProgrammer  # type: ignore[import-untyped]
from litex.soc.integration.builder import Builder  # type: ignore[import-untyped]

import little64.commands.sd.artifacts as _BUILD_SD_BOOT_ARTIFACTS
from little64_cores.litex import LITTLE64_LINUX_RAM_BASE
from little64_cores.config import DEFAULT_CORE_VARIANT
from little64_cores.litex_arty import (
    ARTY_SDCARD_MODE_NATIVE,
    ARTY_SDCARD_MODE_SPI,
    ARTY_SDCARD_MODES,
    Little64ArtySDCardMapping,
    Little64ArtySPISDCardMapping,
    Little64LiteXArtySoC,
    create_arty_platform,
    resolve_arty_sdcard_mapping,
)
from little64_cores.litex_soc import generate_linux_dts


DEFAULT_OUTPUT_DIR = REPO_ROOT / 'builddir' / 'hdl-litex-arty'
DEFAULT_BUILD_NAME = 'little64_arty_a7_35'
DEFAULT_KERNEL_ELF = existing_boot_kernel_path(default_defconfig_for_machine('litex'), repo=REPO_ROOT)
if DEFAULT_KERNEL_ELF is None:
    DEFAULT_KERNEL_ELF = kernel_path(default_defconfig_for_machine('litex'), repo=REPO_ROOT)
DEFAULT_VIVADO_FLASH_PART = 's25fl128l-spi-x1_x2_x4'
DEFAULT_SD_BOOTROM_SOURCE = Path('target/c_boot/litex_sd_boot.c')
DEFAULT_SD_BOOTROM_LINKER = Path('target/c_boot/linker_litex_bootrom.ld')
DEFAULT_LITEX_BIOS_LIBC_DIR = REPO_ROOT / 'hdl' / 'little64_cores' / 'litex_software' / 'libc'
DEFAULT_LITEX_BIOS_LIBCOMPILER_RT_DIR = REPO_ROOT / 'hdl' / 'little64_cores' / 'litex_software' / 'libcompiler_rt'
DEFAULT_LITEX_BIOS_LIBBASE_DIR = REPO_ROOT / 'hdl' / 'little64_cores' / 'litex_software' / 'libbase'
DEFAULT_LITEX_BIOS_LIBLITEDRAM_DIR = REPO_ROOT / 'hdl' / 'little64_cores' / 'litex_software' / 'liblitedram'
DEFAULT_LITEX_BIOS_DIR = REPO_ROOT / 'hdl' / 'little64_cores' / 'litex_software' / 'bios'
BOOT_ARTIFACT_DIRNAME = 'boot'
PROGRAM_OPERATION_VOLATILE = 'volatile'
PROGRAM_OPERATION_FLASH = 'flash'
PROGRAM_OPERATIONS = (PROGRAM_OPERATION_VOLATILE, PROGRAM_OPERATION_FLASH)
PROGRAMMER_AUTO = 'auto'
PROGRAMMER_VIVADO = 'vivado'
PROGRAMMER_OPENOCD = 'openocd'
VIVADO_STOP_AFTER_SYNTHESIS = 'synthesis'
VIVADO_STOP_AFTER_IMPLEMENTATION = 'implementation'
VIVADO_STOP_AFTER_BITSTREAM = 'bitstream'
VIVADO_STOP_AFTER_CHOICES = (
    VIVADO_STOP_AFTER_SYNTHESIS,
    VIVADO_STOP_AFTER_IMPLEMENTATION,
    VIVADO_STOP_AFTER_BITSTREAM,
)
_VIVADO_STOP_AFTER_MARKERS = {
    VIVADO_STOP_AFTER_SYNTHESIS: 'write_checkpoint -force {build_name}_synth.dcp',
    VIVADO_STOP_AFTER_IMPLEMENTATION: 'report_power -file {build_name}_power.rpt',
}


def _parse_int(value: str) -> int:
    return int(value, 0)


def _sanitize_build_name(value: str) -> str:
    sanitized = re.sub(r'[^A-Za-z0-9_$]', '_', value)
    if not sanitized:
        raise SystemExit('Build name must contain at least one Verilog-safe character')
    if sanitized[0].isdigit():
        sanitized = f'_{sanitized}'
    return sanitized


def _boot_artifact_paths(output_dir: Path, build_name: str) -> dict[str, Path]:
    artifact_dir = output_dir / BOOT_ARTIFACT_DIRNAME
    return {
        'dir': artifact_dir,
        'dts': artifact_dir / f'{build_name}.dts',
        'dtb': artifact_dir / f'{build_name}.dtb',
        'bootrom': artifact_dir / f'{build_name}_sd_bootrom.bin',
        'sd_image': artifact_dir / f'{build_name}_sdcard.img',
    }


def _compose_arty_bootargs(*, uart_origin: int | None, include_rootfs: bool) -> str | None:
    bootargs: list[str] = []
    if uart_origin is not None:
        bootargs.append(f'console=liteuart0 earlycon=liteuart,0x{uart_origin:x} ignore_loglevel loglevel=8')
    if include_rootfs:
        bootargs.append('root=/dev/mmcblk0p2 rootwait init=/init')
    return ' '.join(bootargs) if bootargs else None


def _clean_litex_output(output_dir: Path) -> None:
    for child in ('gateware', 'software', BOOT_ARTIFACT_DIRNAME):
        path = output_dir / child
        if path.exists():
            shutil.rmtree(path)


_VENDOR_PRIMITIVE_INPUT_DEFAULTS: dict[str, dict[str, str]] = {
    'IDELAYCTRL': {},
    'OSERDESE2': {
        'SHIFTIN1': "1'd0",
        'SHIFTIN2': "1'd0",
        'T1': "1'd0",
        'T2': "1'd0",
        'T3': "1'd0",
        'T4': "1'd0",
        'TBYTEIN': "1'd0",
        'TCE': "1'd0",
    },
    'ISERDESE2': {
        'CE2': "1'd0",
        'CLKDIVP': "1'd0",
        'D': "1'd0",
        'DYNCLKDIVSEL': "1'd0",
        'DYNCLKSEL': "1'd0",
        'OCLK': "1'd0",
        'OCLKB': "1'd0",
        'OFB': "1'd0",
        'SHIFTIN1': "1'd0",
        'SHIFTIN2': "1'd0",
    },
    'IOBUFDS': {},
    'PLLE2_ADV': {
        'CLKIN2': "1'd0",
        'CLKINSEL': "1'd1",
        'DADDR': "7'd0",
        'DCLK': "1'd0",
        'DEN': "1'd0",
        'DI': "16'd0",
        'DWE': "1'd0",
    },
}

_VENDOR_PRIMITIVE_OUTPUT_WIDTHS: dict[str, dict[str, int]] = {
    'IDELAYCTRL': {'RDY': 1},
    'OSERDESE2': {
        'OFB': 1,
        'SHIFTOUT1': 1,
        'SHIFTOUT2': 1,
        'TBYTEOUT': 1,
        'TFB': 1,
        'TQ': 1,
    },
    'ISERDESE2': {
        'O': 1,
        'SHIFTOUT1': 1,
        'SHIFTOUT2': 1,
    },
    'IOBUFDS': {'O': 1},
    'PLLE2_ADV': {
        'CLKOUT4': 1,
        'CLKOUT5': 1,
        'DO': 16,
        'DRDY': 1,
    },
}


def _find_instance_name(block_lines: list[str]) -> str | None:
    head_match = re.match(r'^\s*([A-Za-z0-9_]+)\s+([A-Za-z0-9_]+)\s*\($', block_lines[0])
    if head_match is not None:
        return head_match.group(2)

    single_line_param_match = re.match(r'^\s*[A-Za-z0-9_]+\s*#.*\)\s*([A-Za-z0-9_]+)\s*\($', block_lines[0])
    if single_line_param_match is not None:
        return single_line_param_match.group(1)

    for line in block_lines:
        match = re.match(r'^\s*\)\s*([A-Za-z0-9_]+)\s*\($', line)
        if match is not None:
            return match.group(1)
    return None


def _connection_indent(block_lines: list[str]) -> str:
    for line in block_lines:
        match = re.match(r'^(\s*)\.[A-Za-z0-9_]+\s*\(', line)
        if match is not None:
            return match.group(1)
    return '\t'


def _patch_vendor_primitive_block(module_name: str, block_lines: list[str]) -> tuple[list[str], list[str]]:
    existing_ports = set(re.findall(r'\.(\w+)\s*\(', ''.join(block_lines)))
    missing_inputs = [
        (port, value)
        for port, value in _VENDOR_PRIMITIVE_INPUT_DEFAULTS[module_name].items()
        if port not in existing_ports
    ]
    missing_outputs = [
        (port, width)
        for port, width in _VENDOR_PRIMITIVE_OUTPUT_WIDTHS[module_name].items()
        if port not in existing_ports
    ]
    if not missing_inputs and not missing_outputs:
        return block_lines, []

    instance_name = _find_instance_name(block_lines)
    if instance_name is None:
        return block_lines, []

    indent = _connection_indent(block_lines)
    declarations: list[str] = []
    inserted_lines: list[str] = []
    for port, value in missing_inputs:
        inserted_lines.append(f"{indent}.{port:<10} ({value})")
    for port, width in missing_outputs:
        net_name = f"little64_vendor_unused_{module_name.lower()}_{instance_name.lower()}_{port.lower()}"
        width_prefix = '' if width == 1 else f'[{width - 1}:0] '
        declarations.append(f'wire {width_prefix}{net_name};\n')
        inserted_lines.append(f"{indent}.{port:<10} ({net_name})")

    closing_index = next((index for index, line in enumerate(block_lines) if line.strip() == ');'), None)
    if closing_index is None:
        return block_lines, []

    last_connection_index = None
    for index in range(closing_index - 1, -1, -1):
        stripped = block_lines[index].strip()
        if stripped.startswith('.'):
            last_connection_index = index
            break
    if last_connection_index is not None and not block_lines[last_connection_index].rstrip().endswith(','):
        block_lines[last_connection_index] = block_lines[last_connection_index].rstrip('\n') + ',\n'

    for index in range(len(inserted_lines) - 1):
        inserted_lines[index] += ',\n'
    inserted_lines[-1] += '\n'

    patched = list(block_lines[:closing_index]) + inserted_lines + list(block_lines[closing_index:])
    return patched, declarations


def _inject_vendor_declarations(verilog_text: str, declarations: list[str]) -> str:
    if not declarations:
        return verilog_text

    module_start = verilog_text.find('module ')
    if module_start == -1:
        return verilog_text

    header_end = verilog_text.find('\n);\n', module_start)
    if header_end == -1:
        return verilog_text

    insert_at = header_end + len('\n);\n')
    unique_declarations: list[str] = []
    for declaration in declarations:
        if declaration not in unique_declarations and declaration not in verilog_text:
            unique_declarations.append(declaration)
    if not unique_declarations:
        return verilog_text

    return verilog_text[:insert_at] + ''.join(unique_declarations) + verilog_text[insert_at:]


def _patch_generated_arty_verilog(gateware_dir: Path, build_name: str) -> bool:
    verilog_path = gateware_dir / f'{build_name}.v'
    if not verilog_path.is_file():
        return False

    original_lines = verilog_path.read_text(encoding='utf-8').splitlines(keepends=True)
    patched_lines: list[str] = []
    declarations: list[str] = []
    changed = False
    index = 0
    target_modules = tuple(_VENDOR_PRIMITIVE_INPUT_DEFAULTS)

    while index < len(original_lines):
        line = original_lines[index]
        match = re.match(r'^\s*(' + '|'.join(target_modules) + r')\b', line)
        if match is None:
            patched_lines.append(line)
            index += 1
            continue

        module_name = match.group(1)
        block_lines = [line]
        index += 1
        while index < len(original_lines):
            block_lines.append(original_lines[index])
            if original_lines[index].strip() == ');':
                index += 1
                break
            index += 1

        patched_block, block_declarations = _patch_vendor_primitive_block(module_name, block_lines)
        if patched_block != block_lines:
            changed = True
        patched_lines.extend(patched_block)
        declarations.extend(block_declarations)

    if not changed:
        return False

    patched_text = ''.join(patched_lines)
    patched_text = _inject_vendor_declarations(patched_text, declarations)
    verilog_path.write_text(patched_text, encoding='utf-8')
    return True


def _render_vivado_stage_tcl(*, gateware_dir: Path, build_name: str, stop_after: str) -> Path:
    base_tcl = gateware_dir / f'{build_name}.tcl'
    if not base_tcl.is_file():
        raise SystemExit(f'Expected generated Vivado Tcl was not found: {base_tcl}')
    if stop_after == VIVADO_STOP_AFTER_BITSTREAM:
        return base_tcl

    stop_marker = _VIVADO_STOP_AFTER_MARKERS[stop_after].format(build_name=build_name)
    stage_lines: list[str] = []
    found_stop_marker = False
    for line in base_tcl.read_text(encoding='utf-8').splitlines():
        if line.strip() == 'quit':
            continue
        stage_lines.append(line)
        if line.strip() == stop_marker:
            found_stop_marker = True
            break

    if not found_stop_marker:
        raise SystemExit(f'Unable to find Vivado stage marker `{stop_marker}` in {base_tcl}')

    stage_lines.extend([
        '',
        '# End (truncated by build_litex_arty_bitstream.py)',
        'quit',
    ])
    stage_tcl = gateware_dir / f'{build_name}_{stop_after}.tcl'
    stage_tcl.write_text('\n'.join(stage_lines) + '\n', encoding='utf-8')
    return stage_tcl


def _run_vivado_stage(*, output_dir: Path, build_name: str, stop_after: str) -> Path:
    gateware_dir = output_dir / 'gateware'
    stage_tcl = _render_vivado_stage_tcl(
        gateware_dir=gateware_dir,
        build_name=build_name,
        stop_after=stop_after,
    )

    vivado_settings_script = vivado_settings_script_from_env()
    if shutil.which('vivado') is None and vivado_settings_script is None:
        raise SystemExit(
            'Unable to find or source Vivado toolchain. '
            'Source Vivado, set LITEX_ENV_VIVADO, or pass --vivado-settings PATH.'
        )

    run_vivado_batch(stage_tcl, cwd=gateware_dir, source_script=vivado_settings_script)

    return stage_tcl


def _rebuild_sd_boot_artifacts(
    *,
    args: argparse.Namespace,
    output_dir: Path,
) -> list[int] | None:
    if not args.with_sdcard:
        return None
    if shutil.which('dtc') is None:
        raise SystemExit('Missing required host tool: dtc')

    kernel_elf = args.kernel_elf.resolve()
    if not kernel_elf.is_file():
        raise SystemExit(
            f'SD boot artifact rebuild requires a kernel ELF, but none was found at: {kernel_elf}. '
            'Build target/linux_port/build-litex/vmlinux first or pass --kernel-elf PATH.'
        )

    artifact_paths = _boot_artifact_paths(output_dir, args.build_name)
    artifact_paths['dir'].mkdir(parents=True, exist_ok=True)

    soc = Little64LiteXArtySoC(
        sys_clk_freq=int(args.sys_clk_freq),
        cpu_variant=args.cpu_variant,
        integrated_main_ram_size=0 if args.with_sdram else args.integrated_main_ram_size,
        with_sdram=args.with_sdram,
        with_spi_flash=args.with_spi_flash,
        with_sdcard=True,
        with_bios=args.use_litex_bios,
        with_timer=True,
        sdcard_mode=args.sdcard_mode,
        sdcard_mapping=_resolve_sdcard_mapping(args),
        toolchain=args.toolchain,
    )
    soc.platform.output_dir = str(artifact_paths['dir'])
    soc.finalize()
    csr_regions = cast(dict[str, Any], getattr(soc.csr, 'regions'))
    uart_region = csr_regions.get('uart')
    bootargs = _compose_arty_bootargs(
        uart_origin=None if uart_region is None else uart_region.origin,
        include_rootfs=not args.no_rootfs,
    )
    artifact_paths['dts'].write_text(generate_linux_dts(soc, bootargs=bootargs), encoding='utf-8')
    compile_dts_to_dtb(artifact_paths['dts'], dtb_path=artifact_paths['dtb'])

    bus_regions = cast(dict[str, Any], getattr(soc.bus, 'regions'))
    main_ram_region = bus_regions['main_ram']
    if args.use_litex_bios:
        bootrom_image = _BUILD_SD_BOOT_ARTIFACTS.build_litex_bios_boot_artifacts(
            soc=soc,
            kernel_elf=kernel_elf,
            dtb=artifact_paths['dtb'],
            bootrom_output=artifact_paths['bootrom'],
            sd_output=artifact_paths['sd_image'],
            ram_base=main_ram_region.origin,
            ram_size=main_ram_region.size,
            kernel_physical_base=max(main_ram_region.origin, LITTLE64_LINUX_RAM_BASE),
            bios_build_dir=output_dir / 'software',
            rootfs_image=args.rootfs_image,
            no_rootfs=args.no_rootfs,
        )
    else:
        bootrom_image = _BUILD_SD_BOOT_ARTIFACTS.build_litex_sd_boot_artifacts(
            soc=soc,
            kernel_elf=kernel_elf,
            dtb=artifact_paths['dtb'],
            bootrom_output=artifact_paths['bootrom'],
            sd_output=artifact_paths['sd_image'],
            ram_base=main_ram_region.origin,
            ram_size=main_ram_region.size,
            kernel_physical_base=max(main_ram_region.origin, LITTLE64_LINUX_RAM_BASE),
            rootfs_image=args.rootfs_image,
            no_rootfs=args.no_rootfs,
            stage0_source=args.sd_bootrom_source,
            stage0_linker=args.sd_bootrom_linker,
        )
    print(f'Rebuilt SD boot artifacts: {artifact_paths["bootrom"]} and {artifact_paths["sd_image"]}')
    sd_backend = 'native LiteSDCard' if args.sdcard_mode == ARTY_SDCARD_MODE_NATIVE else 'SPI-mode SD'
    if args.use_litex_bios:
        print(
            'Built the staged LiteX BIOS bootrom '
            f'against the Arty {sd_backend} CSR layout and regenerated a BIOS-compatible SD image.'
        )
    else:
        print(
            'Compiled the staged bootrom from target/c_boot/litex_sd_boot.c '
            f'against the Arty {sd_backend} CSR layout and will preload it into the integrated boot ROM.'
        )
    return _BUILD_SD_BOOT_ARTIFACTS.pack_litex_memory_words(
        bootrom_image,
        data_width=int(soc.bus.data_width),
        endianness='little',
    )


def _normalize_program_operations(operations: list[str] | None) -> tuple[str, ...]:
    if not operations:
        return ()
    return tuple(dict.fromkeys(operations))


def _has_vivado_tool() -> bool:
    return shutil.which('vivado') is not None or bool(os.environ.get('LITEX_ENV_VIVADO'))


def _has_openocd_tool() -> bool:
    return shutil.which('openocd') is not None


def _resolve_programmer_backend(
    *,
    requested_backend: str,
    operations: tuple[str, ...],
    vivado_available: bool,
    openocd_available: bool,
) -> str:
    if not operations:
        return requested_backend
    if requested_backend != PROGRAMMER_AUTO:
        return requested_backend
    if PROGRAM_OPERATION_FLASH in operations and vivado_available:
        return PROGRAMMER_VIVADO
    if PROGRAM_OPERATION_VOLATILE in operations and vivado_available:
        return PROGRAMMER_VIVADO
    if openocd_available:
        return PROGRAMMER_OPENOCD
    if vivado_available:
        return PROGRAMMER_VIVADO
    raise SystemExit(
        'Programming was requested, but neither Vivado nor OpenOCD is available. '
        'Source Vivado, pass --vivado-settings PATH, or install openocd.'
    )


def _resolve_programming_artifact(output_dir: Path, build_name: str, operation: str) -> Path:
    suffix = '.bit' if operation == PROGRAM_OPERATION_VOLATILE else '.bin'
    return output_dir / 'gateware' / f'{build_name}{suffix}'


def _validate_requested_actions(args: argparse.Namespace, program_operations: tuple[str, ...]) -> None:
    if args.generate_only and program_operations:
        raise SystemExit('--generate-only cannot be combined with --program; no programmable artifact would be produced')
    if args.generate_only and args.program_only:
        raise SystemExit('--generate-only cannot be combined with --program-only')
    if args.program_only and not program_operations:
        raise SystemExit('--program-only requires at least one --program operation')
    if args.program_only and args.vivado_stop_after != VIVADO_STOP_AFTER_BITSTREAM:
        raise SystemExit('--vivado-stop-after cannot be combined with --program-only')
    if args.toolchain != 'vivado' and args.vivado_stop_after != VIVADO_STOP_AFTER_BITSTREAM:
        raise SystemExit('--vivado-stop-after is only supported with --toolchain vivado')
    if program_operations and not args.program_only and args.vivado_stop_after != VIVADO_STOP_AFTER_BITSTREAM:
        raise SystemExit('--program requires --vivado-stop-after bitstream because earlier stops do not emit programmable artifacts')


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description='Build a Little64 LiteX hardware bitstream for the Digilent Arty A7-35T.',
    )
    parser.add_argument(
        '--machine',
        choices=config.available_machines(),
        default=config.DEFAULT_MACHINE,
        help='Machine profile that provides the default kernel ELF and defconfig for bundled boot artifacts.',
    )
    parser.add_argument('--output-dir', type=Path, default=DEFAULT_OUTPUT_DIR, help='Output directory for generated LiteX gateware and project files.')
    parser.add_argument('--build-name', default=DEFAULT_BUILD_NAME, help='LiteX/Vivado build name.')
    parser.add_argument('--sys-clk-freq', type=float, default=100e6, help='Requested system clock frequency in Hz.')
    parser.add_argument(
        '--cpu-variant',
        default='standard',
        help=f'Little64 LiteX CPU variant to synthesize (default: `standard` → {DEFAULT_CORE_VARIANT}; use `standard-v2`, `standard-v3`, `standard-basic`, etc.).',
    )
    parser.add_argument('--toolchain', default='vivado', help='LiteX toolchain backend. Vivado is the supported path for Arty.')
    parser.add_argument('--vivado-settings', type=Path, default=None,
        help='Optional path to Vivado settings64.sh. When provided, exports LITEX_ENV_VIVADO for the current build.')
    parser.add_argument('--with-sdram', action=argparse.BooleanOptionalAction, default=True, help='Enable the onboard DDR3 controller and expose main RAM in SDRAM.')
    parser.add_argument('--integrated-main-ram-size', type=_parse_int, default=0x008000, help='Integrated main RAM size to use when SDRAM is disabled.')
    parser.add_argument('--with-spi-flash', action='store_true', help='Expose the onboard SPI flash as a memory-mapped LiteSPI controller.')
    parser.add_argument('--with-sdcard', action=argparse.BooleanOptionalAction, default=True, help='Expose an SD card controller using the selected backend and connector mapping.')
    parser.add_argument('--sdcard-mode', choices=ARTY_SDCARD_MODES, default=ARTY_SDCARD_MODE_NATIVE, help='SD card backend to expose on Arty hardware. `native` is the default and uses the non-conflicting Arduino IO34..40 SDIO preset; `spi` preserves the current SPI module path.')
    parser.add_argument('--sdcard-connector', choices=('arduino', 'pmoda', 'pmodb', 'pmodc', 'pmodd'), default='arduino', help='Board connector used for the external SD wiring.')
    parser.add_argument('--sdcard-adapter', choices=('digilent', 'numato'), default='digilent', help='Wiring convention used when the SD card is attached through a PMOD adapter.')
    parser.add_argument('--sdcard-clk-pin', help='Override the resolved SD clock pin or connector pin expression.')
    parser.add_argument('--sdcard-mosi-pin', help='Override the resolved SPI MOSI pin or connector pin expression. Only valid with --sdcard-mode spi.')
    parser.add_argument('--sdcard-miso-pin', help='Override the resolved SPI MISO pin or connector pin expression. Only valid with --sdcard-mode spi.')
    parser.add_argument('--sdcard-cs-pin', help='Override the resolved SPI chip-select pin or connector pin expression. Only valid with --sdcard-mode spi.')
    parser.add_argument('--sdcard-cmd-pin', help='Override the resolved native SD CMD pin or connector pin expression. Only valid with --sdcard-mode native.')
    parser.add_argument('--sdcard-d0-pin', help='Override the resolved native SD DAT0 pin or connector pin expression. Only valid with --sdcard-mode native.')
    parser.add_argument('--sdcard-d1-pin', help='Override the resolved native SD DAT1 pin or connector pin expression. Only valid with --sdcard-mode native.')
    parser.add_argument('--sdcard-d2-pin', help='Override the resolved native SD DAT2 pin or connector pin expression. Only valid with --sdcard-mode native.')
    parser.add_argument('--sdcard-d3-pin', help='Override the resolved native SD DAT3 pin or connector pin expression. Only valid with --sdcard-mode native.')
    parser.add_argument('--sdcard-det-pin', help='Override the reserved SD card-detect pin or connector pin expression. Only valid with --sdcard-mode native.')
    parser.add_argument('--sdcard-det-active-low', action=argparse.BooleanOptionalAction, default=None,
        help='Override native SD card-detect polarity. The default Arty native presets treat card-detect as active-low.')
    parser.add_argument('--kernel-elf', type=Path, default=DEFAULT_KERNEL_ELF,
        help='Kernel ELF packed into regenerated SD boot artifacts when the SD boot path is enabled.')
    rootfs_group = parser.add_mutually_exclusive_group()
    rootfs_group.add_argument('--rootfs-image', type=Path,
        help='Optional ext4 rootfs image to place in the regenerated SD card artifact. When omitted, the default rootfs is rebuilt.')
    rootfs_group.add_argument('--no-rootfs', action='store_true',
        help='Leave the second SD partition empty when regenerating SD boot artifacts.')
    parser.add_argument('--sd-bootrom-source', type=Path, default=DEFAULT_SD_BOOTROM_SOURCE,
        help='SD bootrom stage-0 source file to compile into the integrated boot ROM image.')
    parser.add_argument('--sd-bootrom-linker', type=Path, default=DEFAULT_SD_BOOTROM_LINKER,
        help='Linker script used when compiling the SD bootrom stage-0 image.')
    parser.add_argument('--use-litex-bios', action=argparse.BooleanOptionalAction, default=True,
        help='Build the integrated ROM from the upstream LiteX BIOS instead of the repo-local SD stage-0 bootrom.')
    parser.add_argument('--with-ethernet', action='store_true', help='Reserved for future Arty peripheral expansion. Not implemented yet.')
    parser.add_argument('--generate-only', action='store_true', help='Generate the LiteX/Vivado project without invoking Vivado.')
    parser.add_argument('--vivado-stop-after', choices=VIVADO_STOP_AFTER_CHOICES, default=VIVADO_STOP_AFTER_BITSTREAM,
        help='Stop the Vivado flow after `synthesis`, after `implementation` (route/checkpoint/reports), or run through `bitstream` generation.')
    parser.add_argument('--vivado-max-threads', type=int, default=None, help='Optional maximum thread count for Vivado runs.')
    parser.add_argument('--program', action='append', choices=PROGRAM_OPERATIONS,
        help='Program the built artifact onto hardware. Use `volatile` for a temporary JTAG bitstream load or `flash` for persistent SPI-flash programming. Repeat to request both.')
    parser.add_argument('--program-only', action='store_true', help='Skip the build step and program existing artifacts from output-dir/gateware.')
    parser.add_argument('--programmer', choices=(PROGRAMMER_AUTO, PROGRAMMER_VIVADO, PROGRAMMER_OPENOCD), default=PROGRAMMER_AUTO,
        help='Programmer backend to use. `auto` prefers Vivado when available, otherwise OpenOCD.')
    parser.add_argument('--programmer-device-index', type=int, default=0,
        help='Hardware device index used by the programmer backend when supported.')
    parser.add_argument('--vivado-hw-target', default='',
        help='Optional Vivado hw_target argument used for volatile JTAG programming.')
    parser.add_argument('--vivado-flash-part', default=DEFAULT_VIVADO_FLASH_PART,
        help='Vivado cfgmem flash part used for persistent flash programming.')
    parser.add_argument('--flash-address', type=_parse_int, default=0,
        help='Flash offset used when programming the persistent configuration image.')
    return parser.parse_args(argv)


def _configure_vivado_environment(args: argparse.Namespace) -> None:
    if args.vivado_settings is not None:
        settings_path = args.vivado_settings.resolve()
        if not settings_path.is_file():
            raise SystemExit(f'Vivado settings script not found: {settings_path}')
        os.environ['LITEX_ENV_VIVADO'] = str(settings_path.parent)


def _ensure_requested_toolchain_is_available(args: argparse.Namespace) -> None:
    if args.generate_only or args.program_only:
        return
    if args.toolchain == 'vivado':
        if _has_vivado_tool():
            return
        raise SystemExit(
            'Vivado is required for a full Arty bitstream build. '
            'Source the Vivado settings script, set LITEX_ENV_VIVADO, or pass --vivado-settings PATH.'
        )


def _resolve_sdcard_mapping(args: argparse.Namespace) -> Little64ArtySDCardMapping | None:
    if not args.with_sdcard:
        return None
    if args.sdcard_mode == ARTY_SDCARD_MODE_SPI:
        if any((args.sdcard_cmd_pin, args.sdcard_d0_pin, args.sdcard_d1_pin, args.sdcard_d2_pin, args.sdcard_d3_pin, args.sdcard_det_pin, args.sdcard_det_active_low is not None)):
            raise SystemExit('Native SD overrides (--sdcard-cmd-pin/--sdcard-d{0,1,2,3}-pin/--sdcard-det-pin/--[no-]sdcard-det-active-low) require --sdcard-mode native')
    elif args.sdcard_mode == ARTY_SDCARD_MODE_NATIVE:
        if any((args.sdcard_mosi_pin, args.sdcard_miso_pin, args.sdcard_cs_pin)):
            raise SystemExit('SPI SD pin overrides (--sdcard-mosi-pin/--sdcard-miso-pin/--sdcard-cs-pin) require --sdcard-mode spi')
    return resolve_arty_sdcard_mapping(
        mode=args.sdcard_mode,
        connector=args.sdcard_connector,
        adapter=args.sdcard_adapter,
        clk=args.sdcard_clk_pin,
        mosi=args.sdcard_mosi_pin,
        miso=args.sdcard_miso_pin,
        cs_n=args.sdcard_cs_pin,
        cmd=args.sdcard_cmd_pin,
        data0=args.sdcard_d0_pin,
        data1=args.sdcard_d1_pin,
        data2=args.sdcard_d2_pin,
        data3=args.sdcard_d3_pin,
        det=args.sdcard_det_pin,
        det_active_low=args.sdcard_det_active_low,
    )


def _create_programmer(backend: str, args: argparse.Namespace) -> Any:
    if backend == PROGRAMMER_VIVADO:
        return VivadoProgrammer(flash_part=args.vivado_flash_part)
    platform = create_arty_platform(variant='a7-35', toolchain=args.toolchain)
    return platform.create_programmer()


def _program_artifacts(
    *,
    backend: str,
    args: argparse.Namespace,
    output_dir: Path,
    program_operations: tuple[str, ...],
) -> None:
    programmer = _create_programmer(backend, args)
    for operation in program_operations:
        artifact_path = _resolve_programming_artifact(output_dir, args.build_name, operation)
        if not artifact_path.is_file():
            raise SystemExit(
                f'Programming requested for {operation}, but the required artifact is missing: {artifact_path}'
            )

        print(f'Programming {operation} image via {backend}: {artifact_path}')
        if operation == PROGRAM_OPERATION_VOLATILE:
            if backend == PROGRAMMER_VIVADO:
                programmer.load_bitstream(
                    str(artifact_path),
                    target=args.vivado_hw_target,
                    device=args.programmer_device_index,
                )
            else:
                programmer.load_bitstream(str(artifact_path))
        else:
            if backend == PROGRAMMER_VIVADO:
                programmer.flash(
                    args.flash_address,
                    str(artifact_path),
                    device=args.programmer_device_index,
                )
            else:
                programmer.flash(args.flash_address, str(artifact_path))


def _print_sdcard_mapping(mapping: Little64ArtySDCardMapping, *, mode: str) -> None:
    print('Little64 Arty SD mapping:')
    print(f'  mode:   {mode}')
    print(f'  source: {mapping.name}')
    print(f'  clk:    {mapping.clk}')
    if isinstance(mapping, Little64ArtySPISDCardMapping):
        print(f'  mosi:   {mapping.mosi}')
        print(f'  miso:   {mapping.miso}')
        print(f'  cs_n:   {mapping.cs_n}')
        return
    print(f'  cmd:    {mapping.cmd}')
    print(f'  d0:     {mapping.data0}')
    print(f'  d1:     {mapping.data1}')
    print(f'  d2:     {mapping.data2}')
    print(f'  d3:     {mapping.data3}')
    print(f'  det:    {mapping.det or "(reserved only)"}')
    if mapping.det is not None:
        print(f'  det_polarity: {'active-low' if mapping.det_active_low else 'active-high'}')


def _override_litex_bios_packages(builder: Builder) -> None:
    builder.software_packages = [
        (
            name,
            str(DEFAULT_LITEX_BIOS_LIBC_DIR) if name == 'libc'
            else str(DEFAULT_LITEX_BIOS_LIBCOMPILER_RT_DIR) if name == 'libcompiler_rt'
            else str(DEFAULT_LITEX_BIOS_LIBBASE_DIR) if name == 'libbase'
            else str(DEFAULT_LITEX_BIOS_LIBLITEDRAM_DIR) if name == 'liblitedram'
            else src_dir,
        )
        for name, src_dir in builder.software_packages
    ]

    original_add_software_package = builder.add_software_package

    def add_software_package(name: str, src_dir: str | None = None) -> None:
        if name == 'bios' and src_dir is None:
            src_dir = str(DEFAULT_LITEX_BIOS_DIR)
        original_add_software_package(name, src_dir)

    builder.add_software_package = add_software_package


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    requested_build_name = args.build_name
    args.build_name = _sanitize_build_name(args.build_name)
    program_operations = _normalize_program_operations(args.program)
    _validate_requested_actions(args, program_operations)
    _configure_vivado_environment(args)
    _ensure_requested_toolchain_is_available(args)

    if args.with_ethernet:
        raise SystemExit('Ethernet support is reserved for a later Arty hardware iteration and is not implemented yet')

    sdcard_mapping = _resolve_sdcard_mapping(args)
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    programmer_backend = _resolve_programmer_backend(
        requested_backend=args.programmer,
        operations=program_operations,
        vivado_available=_has_vivado_tool(),
        openocd_available=_has_openocd_tool(),
    )

    if args.build_name != requested_build_name:
        print(f'Adjusted build name for Verilog compatibility: {requested_build_name} -> {args.build_name}')

    if sdcard_mapping is not None:
        _print_sdcard_mapping(sdcard_mapping, mode=args.sdcard_mode)

    if not args.program_only:
        _clean_litex_output(output_dir)
        bootrom_init = None
        if args.with_sdcard:
            bootrom_init = _rebuild_sd_boot_artifacts(
                args=args,
                output_dir=output_dir,
            )
        soc = Little64LiteXArtySoC(
            sys_clk_freq=int(args.sys_clk_freq),
            integrated_rom_init=[] if bootrom_init is None else bootrom_init,
            integrated_main_ram_size=0 if args.with_sdram else args.integrated_main_ram_size,
            with_sdram=args.with_sdram,
            with_spi_flash=args.with_spi_flash,
            with_sdcard=args.with_sdcard,
            with_bios=args.use_litex_bios,
            with_timer=True,
            cpu_variant=args.cpu_variant,
            sdcard_mode=args.sdcard_mode,
            sdcard_mapping=sdcard_mapping,
            toolchain=args.toolchain,
        )

        builder = Builder(
            soc,
            output_dir=str(output_dir),
            compile_software=args.use_litex_bios and bootrom_init is None,
            compile_gateware=not args.generate_only,
        )
        if args.use_litex_bios and bootrom_init is None:
            _override_litex_bios_packages(builder)
        build_kwargs: dict[str, Any] = {
            'build_name': args.build_name,
            'vivado_max_threads': args.vivado_max_threads,
        }
        if args.toolchain == 'vivado':
            build_kwargs['run'] = False
        else:
            build_kwargs['run'] = not args.generate_only
        cast(Any, builder).build(**build_kwargs)
        if _patch_generated_arty_verilog(output_dir / 'gateware', args.build_name):
            print('Patched generated gateware to tie off optional Xilinx primitive ports and reduce noisy synthesis warnings.')
        if args.toolchain == 'vivado' and not args.generate_only:
            stage_tcl = _run_vivado_stage(
                output_dir=output_dir,
                build_name=args.build_name,
                stop_after=args.vivado_stop_after,
            )
            print(f'Executed Vivado stage script: {stage_tcl}')

    print(f'LiteX output directory: {output_dir}')
    print(f'Gateware directory: {output_dir / "gateware"}')
    if args.generate_only:
        print('Vivado execution was skipped; generated project files are ready for inspection.')
    elif args.vivado_stop_after == VIVADO_STOP_AFTER_SYNTHESIS:
        print(f'Synthesis checkpoint: {output_dir / "gateware" / f"{args.build_name}_synth.dcp"}')
        print(f'Synthesis timing report: {output_dir / "gateware" / f"{args.build_name}_timing_synth.rpt"}')
    elif args.vivado_stop_after == VIVADO_STOP_AFTER_IMPLEMENTATION:
        print(f'Implementation checkpoint: {output_dir / "gateware" / f"{args.build_name}_route.dcp"}')
        print(f'Implementation timing report: {output_dir / "gateware" / f"{args.build_name}_timing.rpt"}')
    else:
        print(f'Expected bitstream path: {output_dir / "gateware" / f"{args.build_name}.bit"}')
    if program_operations:
        _program_artifacts(
            backend=programmer_backend,
            args=args,
            output_dir=output_dir,
            program_operations=program_operations,
        )
    return 0


def run(argv: list[str]) -> int:
    return main(argv) or 0


if __name__ == '__main__':
    raise SystemExit(main())