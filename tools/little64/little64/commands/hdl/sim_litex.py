#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import os
import selectors
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, cast

from little64.build_support import run_checked
from little64.paths import repo_root
from little64.tooling_support import compile_dts_to_dtb, little64_command

sys.path.insert(0, str(repo_root() / "hdl"))

import litex
from litex.build.sim.config import SimConfig
from litex.soc.integration.common import get_mem_data

from little64_cores.litex_soc import Little64LiteXSimSoC


REPO_ROOT = repo_root()
LITEX_SIM_CORE_DIR = Path(litex.__file__).resolve().parent / 'build' / 'sim' / 'core'
LITEX_SIM_MODULES_DIR = REPO_ROOT / 'hdl' / 'tools' / 'litex_sim_modules'
DEFAULT_OUTPUT_DIR = REPO_ROOT / 'builddir' / 'hdl-litex-linux-boot'
DEFAULT_SD_OUTPUT_DIR = REPO_ROOT / 'builddir' / 'hdl-litex-linux-boot-sdcard'
DEFAULT_KERNEL_ELF = REPO_ROOT / 'target' / 'linux_port' / 'build-litex' / 'vmlinux'
DEFAULT_BOOTARGS = ''
LINUX_VERSION_MARKER = 'Linux version '
DEFAULT_REQUIRED_MARKERS = [
    LINUX_VERSION_MARKER,
]
DEFAULT_SD_REQUIRED_MARKERS = [
    LINUX_VERSION_MARKER,
]
LITEX_BUILTIN_SIM_MODULES = {
    'clocker',
    'ethernet',
    'gmii_ethernet',
    'jtagremote',
    'serial2console',
    'serial2tcp',
    'spdeeprom',
    'video',
    'xgmii_ethernet',
}
RESETPULSE_SOURCE = LITEX_SIM_MODULES_DIR / 'resetpulse.c'
RESETPULSE_SO_NAME = 'resetpulse.so'
SIMTRACEON_SOURCE = LITEX_SIM_MODULES_DIR / 'simtraceon.c'
SDCARDIMAGE_SOURCE = LITEX_SIM_MODULES_DIR / 'sdcardimage.c'
LITEX_SIM_COMPAT_PATCHES = {
    Path('modules/clocker/clocker.c'): [
        ('static int clocker_start()', 'static int clocker_start(void *unused)'),
    ],
    Path('modules/spdeeprom/spdeeprom.c'): [
        ('static int spdeeprom_start();', 'static int spdeeprom_start(void *unused);'),
        ('static int spdeeprom_start()', 'static int spdeeprom_start(void *unused)'),
    ],
}
BUILD_CONFIG_STAMP = '.little64-litex-smoke-build.json'


class _RunDebugState:
    def __init__(self) -> None:
        self.phase: str = 'startup'
        self.output_dir: Path | None = None
        self.log_path: Path | None = None
        self.required_markers: list[str] = []
        self.run_started_at: float | None = None
        self.first_output_elapsed: float | None = None
        self.last_output_elapsed: float | None = None
        self.output_bytes: int = 0
        self.exit_code: int | None = None


_RUN_DEBUG_STATE = _RunDebugState()


def _log_progress(message: str) -> None:
    print(f"[progress {time.strftime('%H:%M:%S')}] {message}", flush=True)


def _set_phase(phase: str) -> None:
    _RUN_DEBUG_STATE.phase = phase


def _format_elapsed(seconds: float | None) -> str:
    if seconds is None:
        return 'n/a'
    return f'{seconds:.1f}s'


def _get_process_debug_details(pid: int) -> list[str]:
    details: list[str] = []
    status_path = Path('/proc') / str(pid) / 'status'
    stat_path = Path('/proc') / str(pid) / 'stat'

    try:
        status_lines = status_path.read_text(encoding='utf-8').splitlines()
    except OSError:
        return ['process_status: unavailable']

    interesting_fields = {
        'Name',
        'State',
        'Threads',
        'VmRSS',
        'VmSize',
        'voluntary_ctxt_switches',
        'nonvoluntary_ctxt_switches',
    }
    for line in status_lines:
        if ':' not in line:
            continue
        key, value = line.split(':', 1)
        if key in interesting_fields:
            details.append(f'{key}: {value.strip()}')

    try:
        stat_fields = stat_path.read_text(encoding='utf-8').split()
        if len(stat_fields) > 15:
            clock_ticks = os.sysconf(os.sysconf_names['SC_CLK_TCK'])
            user_seconds = int(stat_fields[13]) / clock_ticks
            system_seconds = int(stat_fields[14]) / clock_ticks
            details.append(f'cpu_user_seconds: {user_seconds:.2f}')
            details.append(f'cpu_system_seconds: {system_seconds:.2f}')
    except (OSError, KeyError, ValueError):
        pass

    return details


def _emit_debug_summary(
    reason: str,
    *,
    captured: str,
    process_details: list[str] | None = None,
    timed_out: bool = False,
) -> None:
    missing_markers = [marker for marker in _RUN_DEBUG_STATE.required_markers if marker not in captured]
    tail = captured[-2048:]

    lines = [
        '',
        'LiteX Linux boot smoke debug summary.',
        f'reason: {reason}',
        f'phase: {_RUN_DEBUG_STATE.phase}',
        f'output_dir: {_RUN_DEBUG_STATE.output_dir}',
        f'log: {_RUN_DEBUG_STATE.log_path}',
        f'timed_out: {int(timed_out)}',
        f'exit_code: {_RUN_DEBUG_STATE.exit_code}',
        f'first_output_after: {_format_elapsed(_RUN_DEBUG_STATE.first_output_elapsed)}',
        f'last_output_at: {_format_elapsed(_RUN_DEBUG_STATE.last_output_elapsed)}',
        f'output_bytes: {_RUN_DEBUG_STATE.output_bytes}',
        f'missing_markers: {missing_markers}',
    ]
    if process_details:
        lines.extend(process_details)
    lines.extend([
        'serial_tail:',
        tail,
    ])
    sys.stderr.write('\n'.join(lines) + '\n')


def _parse_int(value: str) -> int:
    return int(value, 0)


def _load_rom_init_words(image_path: Path) -> list[int]:
    return cast(list[int], get_mem_data(str(image_path), data_width=64, endianness='little'))


def _resolved_output_dir(args: argparse.Namespace) -> Path:
    if args.with_sdcard and args.output_dir == DEFAULT_OUTPUT_DIR:
        return DEFAULT_SD_OUTPUT_DIR
    return args.output_dir


def _default_required_markers(*, with_sdcard: bool) -> list[str]:
    return list(DEFAULT_SD_REQUIRED_MARKERS if with_sdcard else DEFAULT_REQUIRED_MARKERS)


def _resolve_required_markers(args: argparse.Namespace) -> list[str]:
    required_markers = list(args.require) if args.require else _default_required_markers(with_sdcard=args.with_sdcard)
    for marker in args.extra_require:
        if marker not in required_markers:
            required_markers.append(marker)
    return required_markers


def _build_config(args: argparse.Namespace) -> dict[str, object]:
    return {
        'with_sdcard': args.with_sdcard,
        'with_sdram': args.with_sdram,
        'integrated_main_ram_size': args.integrated_main_ram_size,
        'cpu_variant': args.cpu_variant,
    }


def _load_build_config(output_dir: Path) -> dict[str, object] | None:
    stamp_path = output_dir / BUILD_CONFIG_STAMP
    if not stamp_path.exists():
        return None
    try:
        return json.loads(stamp_path.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError):
        return None


def _write_build_config(output_dir: Path, config: dict[str, object]) -> None:
    (output_dir / BUILD_CONFIG_STAMP).write_text(
        json.dumps(config, indent=2, sort_keys=True) + '\n',
        encoding='utf-8',
    )


def _clean_generated_build_dirs(output_dir: Path) -> None:
    for subdir_name in ('bin', 'gateware', 'litex-sim-build', 'software'):
        subdir = output_dir / subdir_name
        if subdir.exists():
            _log_progress(f'Cleaning previous build directory {subdir}')
            shutil.rmtree(subdir)


def _prepare_output_dir(output_dir: Path, args: argparse.Namespace, *, run_only: bool) -> None:
    existing_config = _load_build_config(output_dir)
    desired_config = _build_config(args)

    if run_only:
        if existing_config is not None and existing_config != desired_config:
            raise SystemExit(
                'The existing LiteX simulator build does not match the requested mode. '
                'Rebuild without --run-only or choose a different --output-dir.'
            )
        return

    if output_dir.exists():
        _clean_generated_build_dirs(output_dir)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description='Run the Little64 LiteX simulation SoC through LiteX\'s native simulator flow.',
    )
    parser.add_argument(
        '--output-dir',
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help='Base output directory for the LiteX simulation build and generated boot artifacts.',
    )
    parser.add_argument(
        '--kernel-elf',
        type=Path,
        default=DEFAULT_KERNEL_ELF,
        help='Kernel ELF image to pack into the LiteX SPI flash model.',
    )
    parser.add_argument(
        '--rootfs-image',
        type=Path,
        default=None,
        help='Optional ext4 rootfs image override for the second SD partition. When omitted, the SD artifact builder regenerates the default init.S-based rootfs.',
    )
    parser.add_argument(
        '--integrated-main-ram-size',
        type=_parse_int,
        default=0x04000000,
        help='Integrated main RAM size to model when SDRAM is disabled.',
    )
    parser.add_argument(
        '--with-sdram',
        action='store_true',
        help='Use the LiteDRAM SDRAM model instead of integrated main RAM.',
    )
    parser.add_argument(
        '--with-sdcard',
        action='store_true',
        help='Expose LiteSDCard in the LiteX simulation SoC.',
    )
    parser.add_argument(
        '--bootargs',
        default=DEFAULT_BOOTARGS,
        help='Bootargs injected into the generated LiteX simulation DTS. Defaults to the LiteUART earlycon string for the chosen SoC layout.',
    )
    parser.add_argument(
        '--timeout-seconds',
        type=float,
        default=120.0,
        help='Maximum wall-clock time to wait for the required boot markers.',
    )
    parser.add_argument(
        '--require',
        action='append',
        default=[],
        help='Exact required serial substring. Can be repeated. Replaces the default success markers when provided.',
    )
    parser.add_argument(
        '--extra-require',
        action='append',
        default=[],
        help='Additional serial substring to require on top of the default success markers.',
    )
    parser.add_argument(
        '--jobs',
        default=None,
        help='Limit the number of compiler jobs used by LiteX\'s Verilator build.',
    )
    parser.add_argument(
        '--threads',
        type=int,
        default=1,
        help='Set the number of LiteX Verilator simulation threads.',
    )
    parser.add_argument(
        '--trace',
        action='store_true',
        help='Enable LiteX waveform tracing.',
    )
    parser.add_argument(
        '--trace-fst',
        action='store_true',
        help='Use FST tracing instead of VCD.',
    )
    parser.add_argument(
        '--trace-start',
        type=float,
        default=0.0,
        help='Simulation time in ps at which tracing should start.',
    )
    parser.add_argument(
        '--trace-end',
        type=float,
        default=-1.0,
        help='Simulation time in ps at which tracing should stop.',
    )
    parser.add_argument(
        '--opt-level',
        default='O3',
        help='Compilation optimization level for the LiteX Verilator build.',
    )
    parser.add_argument(
        '--cpu-variant',
        default='standard',
        help='LiteX CPU variant to use for the simulation SoC build. `standard` selects the V2 core; use `standard-basic` for the legacy core.',
    )
    parser.add_argument(
        '--build-only',
        action='store_true',
        help='Prepare boot artifacts and compile the LiteX simulator, but do not run it.',
    )
    parser.add_argument(
        '--run-only',
        action='store_true',
        help='Reuse an existing LiteX simulator build from --output-dir and only run it.',
    )
    return parser.parse_args(argv)


def _run_checked(command: list[str], *, cwd: Path | None = None, label: str | None = None) -> None:
    if label is not None:
        _log_progress(f'{label}: starting')
    run_checked(command, cwd=cwd)
    if label is not None:
        _log_progress(f'{label}: finished')


def _pkg_config_has(package_name: str) -> bool:
    if shutil.which('pkg-config') is None:
        return False
    return subprocess.run(
        ['pkg-config', '--exists', package_name],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    ).returncode == 0


def _ensure_prerequisites(args: argparse.Namespace) -> None:
    if not args.kernel_elf.exists():
        raise SystemExit(f'Missing kernel ELF: {args.kernel_elf}')
    if shutil.which('dtc') is None:
        raise SystemExit('Missing required host tool: dtc')
    if shutil.which('verilator') is None:
        raise SystemExit('Missing required host tool: verilator')
    if not _pkg_config_has('json-c'):
        raise SystemExit(
            'Missing host development headers for json-c. '
            'Install the package that provides pkg-config module "json-c" '
            '(for example json-c-devel or libjson-c-dev).'
        )
    if not _pkg_config_has('libevent'):
        raise SystemExit(
            'Missing host development headers for libevent. '
            'Install the package that provides pkg-config module "libevent" '
            '(for example libevent-devel or libevent-dev).'
        )


def _apply_litex_sim_compatibility_patches() -> None:
    modules_header = LITEX_SIM_CORE_DIR / 'modules.h'
    header_text = modules_header.read_text(encoding='utf-8')
    if 'int (*start)(void *);' not in header_text:
        return

    for relative_path, replacements in LITEX_SIM_COMPAT_PATCHES.items():
        source_path = LITEX_SIM_CORE_DIR / relative_path
        text = source_path.read_text(encoding='utf-8')
        original = text
        for old, new in replacements:
            text = text.replace(old, new)
        if text != original:
            source_path.write_text(text, encoding='utf-8')


def _patch_generated_sim_init(gateware_dir: Path) -> None:
    sim_init_path = gateware_dir / 'sim_init.cpp'
    text = sim_init_path.read_text(encoding='utf-8')
    original = text
    text = text.replace(
        'extern "C" void litex_sim_dump()\n{\n}\n',
        'extern "C" void litex_sim_dump()\n{\n    litex_sim_tracer_dump();\n}\n',
    )
    if text != original:
        sim_init_path.write_text(text, encoding='utf-8')


def _build_dts(output_dir: Path, args: argparse.Namespace) -> Path:
    _set_phase('generating dts')
    dts_path = output_dir / 'little64-litex-sim.dts'
    command: list[str] = [
        *little64_command('hdl', 'dts-linux', python_bin=sys.executable),
        '--output',
        str(dts_path),
        '--with-spi-flash',
        '--cpu-variant',
        args.cpu_variant,
        '--bootargs',
        args.bootargs,
    ]
    if args.with_sdcard:
        command.append('--with-sdcard')
    if args.with_sdram:
        command.append('--with-sdram')
    else:
        command.extend([
            '--integrated-main-ram-size',
            hex(args.integrated_main_ram_size),
        ])
    _run_checked(command, label=f'Generating DTS at {dts_path}')
    return dts_path


def _build_dtb(dts_path: Path) -> Path:
    _set_phase('generating dtb')
    dtb_path = dts_path.with_suffix('.dtb')
    if dtb_path.exists() and dtb_path.stat().st_mtime >= dts_path.stat().st_mtime:
        _log_progress(f'Reusing up-to-date DTB {dtb_path}')
        return dtb_path
    _log_progress(f'Compiling DTB at {dtb_path}: starting')
    compile_dts_to_dtb(dts_path, dtb_path=dtb_path)
    _log_progress(f'Compiling DTB at {dtb_path}: finished')
    return dtb_path


def _build_flash_image(output_dir: Path, args: argparse.Namespace, dtb_path: Path) -> Path:
    _set_phase('building spi flash image')
    flash_image_path = output_dir / 'little64-linux-spiflash.bin'
    _run_checked([
        *little64_command('hdl', 'flash-image', python_bin=sys.executable),
        '--kernel-elf',
        str(args.kernel_elf),
        '--dtb',
        str(dtb_path),
        '--output',
        str(flash_image_path),
    ], label=f'Building SPI flash image at {flash_image_path}')
    return flash_image_path


def _build_sd_artifacts(output_dir: Path, args: argparse.Namespace, dtb_path: Path) -> tuple[Path, Path]:
    _set_phase('building sd boot artifacts')
    flash_image_path = output_dir / 'little64-sd-stage0-bootrom.bin'
    sd_image_path = output_dir / 'little64-linux-sdcard.img'
    command: list[str] = [
        *little64_command('sd', 'build', python_bin=sys.executable),
        '--kernel-elf',
        str(args.kernel_elf),
        '--dtb',
        str(dtb_path),
        '--bootrom-output',
        str(flash_image_path),
        '--sd-output',
        str(sd_image_path),
        '--cpu-variant',
        args.cpu_variant,
        '--ram-size',
        hex(args.integrated_main_ram_size),
        '--litex-target',
        'sim-bootrom',
        '--boot-source',
        'bootrom',
    ]
    if args.rootfs_image is not None and args.rootfs_image.exists():
        command.extend(['--rootfs-image', str(args.rootfs_image)])
    _run_checked(command, label=f'Building SD boot artifacts under {output_dir}')
    return flash_image_path, sd_image_path


def _build_local_sim_module(gateware_dir: Path, source_path: Path) -> None:
    compiler = shutil.which(os.environ.get('CC', 'cc'))
    if compiler is None:
        raise SystemExit('Missing required host tool: cc')

    modules_dir = gateware_dir / 'modules'
    modules_dir.mkdir(parents=True, exist_ok=True)

    module_name = source_path.stem
    object_path = modules_dir / f'{module_name}.o'
    shared_object_path = modules_dir / f'{module_name}.so'

    _run_checked([
        compiler,
        '-c',
        '-Wall',
        '-O3',
        '-ggdb',
        '-fPIC',
        '-Werror',
        '-I',
        str(LITEX_SIM_CORE_DIR),
        '-o',
        str(object_path),
        str(source_path),
    ], label=f'Compiling simulator helper {source_path.name}')
    _run_checked([
        compiler,
        '-shared',
        '-fPIC',
        '-Wl,-soname,' + shared_object_path.name,
        '-o',
        str(shared_object_path),
        str(object_path),
    ], label=f'Linking simulator helper {shared_object_path.name}')


def _build_local_sim_modules(gateware_dir: Path, *, enable_trace: bool, with_sdcard: bool) -> None:
    _build_local_sim_module(gateware_dir, RESETPULSE_SOURCE)
    if enable_trace:
        _build_local_sim_module(gateware_dir, SIMTRACEON_SOURCE)
    if with_sdcard:
        _build_local_sim_module(gateware_dir, SDCARDIMAGE_SOURCE)


def _create_soc(
    args: argparse.Namespace,
    output_dir: Path,
    flash_image_path: Path,
    sd_image_path: Path | None,
) -> Little64LiteXSimSoC:
    soc_kwargs: dict[str, object] = {
        'cpu_variant': args.cpu_variant,
        'integrated_main_ram_size': 0 if args.with_sdram else args.integrated_main_ram_size,
        'with_sdram': args.with_sdram,
        'with_sdcard': args.with_sdcard,
        'with_timer': True,
        'sdcard_image_path': sd_image_path,
    }
    if args.with_sdcard:
        soc_kwargs.update({
            'litex_target': 'sim-bootrom',
            'boot_source': 'bootrom',
            'integrated_rom_init': _load_rom_init_words(flash_image_path),
        })
    else:
        soc_kwargs.update({
            'with_spi_flash': True,
            'spi_flash_image_path': flash_image_path,
        })
    soc = Little64LiteXSimSoC(**soc_kwargs)
    soc.platform.output_dir = str(output_dir)
    return soc


def _format_bus_region_summary(soc: Little64LiteXSimSoC) -> str:
    parts: list[str] = []
    for region_name in ('rom', 'spiflash', 'sram', 'main_ram'):
        region = soc.bus.regions.get(region_name)
        if region is None:
            parts.append(f'{region_name}=absent')
            continue
        parts.append(f'{region_name}=0x{region.size:x}@0x{region.origin:x}')
    return ', '.join(parts)


def _restrict_sim_modules(build_script: Path, sim_config: SimConfig) -> None:
    sim_modules = cast(list[dict[str, Any]], getattr(sim_config, 'modules', []))
    required_modules: list[str] = sorted({
        module['module']
        for module in sim_modules
        if module['module'] in LITEX_BUILTIN_SIM_MODULES
    })
    module_list = ' '.join(required_modules)
    original = build_script.read_text(encoding='utf-8')
    marker = ' OPT_LEVEL='
    if marker not in original:
        raise SystemExit(f'Unable to restrict LiteX simulation modules in {build_script}')
    patched = original.replace(marker, f' MODULES="{module_list}"{marker}', 1)
    build_script.write_text(patched, encoding='utf-8')


def _build_simulator(
    args: argparse.Namespace,
    output_dir: Path,
    flash_image_path: Path,
    sd_image_path: Path | None,
) -> tuple[Path, Path]:
    _set_phase('building simulator')
    enable_trace = args.trace or args.trace_fst
    sim_config = SimConfig()
    sim_config.add_clocker('sys_clk', freq_hz=int(1e9))
    sim_config.add_module('resetpulse', [], clocks='sys_rst', tickfirst=True)
    if enable_trace:
        sim_config.add_module('simtraceon', [], clocks='sim_trace', tickfirst=True)
    sim_config.add_module('serial2console', 'serial')
    if args.with_sdcard:
        sim_config.add_module('sdcardimage', 'sdcard_img', clocks='sys_clk', tickfirst=True)

    _log_progress('Creating LiteX simulation SoC')
    soc = _create_soc(args, output_dir, flash_image_path, sd_image_path)
    _log_progress(
        'LiteX simulation SoC ready: '
        f'{_format_bus_region_summary(soc)}, '
        f'with_sdcard={int(args.with_sdcard)}, '
        f'with_sdram={int(args.with_sdram)}'
    )
    gateware_dir = output_dir / 'gateware'
    gateware_dir.mkdir(parents=True, exist_ok=True)
    _log_progress(f'Generating LiteX simulator sources in {gateware_dir}')
    vns = soc.build(
        build_dir=str(gateware_dir),
        build_name='sim',
        run=False,
        sim_config=sim_config,
        interactive=False,
        jobs=args.jobs,
        threads=args.threads,
        trace=args.trace,
        trace_fst=args.trace_fst,
        trace_start=int(args.trace_start),
        trace_end=int(args.trace_end),
        opt_level=args.opt_level,
    )
    soc.do_exit(vns=vns)
    _log_progress('LiteX simulator sources generated')

    build_script = gateware_dir / 'build_sim.sh'
    if not build_script.exists():
        raise SystemExit(f'LiteX simulator build script was not generated: {build_script}')
    _apply_litex_sim_compatibility_patches()
    if enable_trace:
        _patch_generated_sim_init(gateware_dir)
    _restrict_sim_modules(build_script, sim_config)
    _run_checked(['bash', build_script.name], cwd=gateware_dir, label='Building LiteX simulator binary with Verilator')
    _log_progress('Building local simulator helper modules')
    _build_local_sim_modules(gateware_dir, enable_trace=enable_trace, with_sdcard=args.with_sdcard)

    binary_path = gateware_dir / 'obj_dir' / 'Vsim'
    if not binary_path.exists():
        raise SystemExit(f'LiteX simulator binary was not generated: {binary_path}')
    _log_progress(f'LiteX simulator binary ready at {binary_path}')
    _write_build_config(output_dir, _build_config(args))
    return gateware_dir, binary_path


def _stage_sd_image_for_run(*, gateware_dir: Path, sd_image_path: Path | None) -> None:
    if sd_image_path is None:
        return
    staged_image = gateware_dir / 'sdcard.img'
    _set_phase('staging sd image')
    _log_progress(f'Staging SD image {sd_image_path} -> {staged_image}')
    if staged_image.exists() or staged_image.is_symlink():
        staged_image.unlink()
    try:
        staged_image.symlink_to(os.path.relpath(sd_image_path, staged_image.parent))
        _log_progress('SD image staging finished via symlink')
    except OSError as exc:
        _log_progress(f'SD symlink staging unavailable ({exc}); falling back to copy')
        shutil.copyfile(sd_image_path, staged_image)
        _log_progress('SD image staging finished via copy')


def _wait_for_exit(process: subprocess.Popen[bytes], timeout_seconds: float) -> None:
    try:
        process.wait(timeout=timeout_seconds)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()


def _run_simulator(
    *,
    gateware_dir: Path,
    binary_path: Path,
    required_markers: list[str],
    timeout_seconds: float,
    log_path: Path,
) -> int:
    _set_phase('running simulator')
    _log_progress(f'Launching LiteX simulator binary {binary_path}')
    process = subprocess.Popen(
        [str(binary_path)],
        cwd=gateware_dir,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    assert process.stdout is not None

    selector = selectors.DefaultSelector()
    selector.register(process.stdout, selectors.EVENT_READ)

    captured = ''
    deadline = time.monotonic() + timeout_seconds
    start_time = time.monotonic()
    _RUN_DEBUG_STATE.run_started_at = start_time
    _RUN_DEBUG_STATE.first_output_elapsed = None
    _RUN_DEBUG_STATE.last_output_elapsed = None
    _RUN_DEBUG_STATE.output_bytes = 0
    _RUN_DEBUG_STATE.exit_code = None
    success = False
    timed_out = False
    exit_code: int | None = None
    interrupted = False
    process_details: list[str] | None = None

    _log_progress(
        'Waiting for serial markers: '
        + ', '.join(required_markers)
        + f' (timeout={timeout_seconds:.1f}s)'
    )

    with log_path.open('w', encoding='utf-8') as log_file:
        try:
            while True:
                now = time.monotonic()
                remaining = deadline - now
                if remaining <= 0:
                    timed_out = True
                    break

                events = selector.select(timeout=min(0.1, remaining))
                if not events:
                    if process.poll() is not None:
                        break
                    continue

                chunk = os.read(process.stdout.fileno(), 4096)
                if not chunk:
                    if process.poll() is not None:
                        break
                    continue

                text = chunk.decode('utf-8', errors='replace')
                elapsed = time.monotonic() - start_time
                if _RUN_DEBUG_STATE.first_output_elapsed is None:
                    _RUN_DEBUG_STATE.first_output_elapsed = elapsed
                    _log_progress(f'Received first simulator output after {elapsed:.1f}s')
                _RUN_DEBUG_STATE.last_output_elapsed = elapsed
                _RUN_DEBUG_STATE.output_bytes += len(chunk)

                sys.stdout.write(text)
                sys.stdout.flush()
                log_file.write(text)
                log_file.flush()
                captured += text
                if len(captured) > 65536:
                    captured = captured[-65536:]

                if all(marker in captured for marker in required_markers):
                    success = True
                    _log_progress('Required serial markers observed; terminating simulator')
                    process.terminate()
                    _wait_for_exit(process, 2.0)
                    exit_code = process.returncode
                    break
        except KeyboardInterrupt:
            interrupted = True
            process_details = _get_process_debug_details(process.pid)
            _log_progress('Keyboard interrupt received; terminating simulator cleanly')
        finally:
            if not success and process.poll() is None:
                process.terminate()
                _wait_for_exit(process, 2.0)
            if process.poll() is None:
                process.kill()
                process.wait()
            exit_code = process.returncode

    selector.close()
    _RUN_DEBUG_STATE.exit_code = exit_code

    if interrupted:
        _emit_debug_summary('keyboard interrupt', captured=captured, process_details=process_details)
        return 130

    if success:
        _log_progress('LiteX simulator run completed successfully')
        return 0

    _emit_debug_summary('missing required markers', captured=captured, timed_out=timed_out)
    _log_progress('LiteX simulator run finished without the required markers')
    return 1


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.build_only and args.run_only:
        raise SystemExit('--build-only and --run-only are mutually exclusive')

    args.kernel_elf = args.kernel_elf.resolve()
    output_dir = _resolved_output_dir(args).resolve()
    _RUN_DEBUG_STATE.output_dir = output_dir
    _log_progress(f'LiteX smoke wrapper starting with output_dir={output_dir}')
    output_dir.mkdir(parents=True, exist_ok=True)
    _set_phase('preparing output directory')
    _prepare_output_dir(output_dir, args, run_only=args.run_only)
    _set_phase('checking prerequisites')
    _log_progress('Checking host prerequisites')
    _ensure_prerequisites(args)
    _log_progress('Host prerequisites satisfied')

    required_markers = _resolve_required_markers(args)
    log_path = output_dir / 'litex-sim-serial.log'
    _RUN_DEBUG_STATE.log_path = log_path
    _RUN_DEBUG_STATE.required_markers = list(required_markers)

    try:
        if args.run_only:
            gateware_dir = output_dir / 'gateware'
            binary_path = gateware_dir / 'obj_dir' / 'Vsim'
            if not binary_path.exists():
                raise SystemExit(f'Missing LiteX simulator binary for --run-only: {binary_path}')
            sd_image_path = output_dir / 'little64-linux-sdcard.img' if args.with_sdcard else None
            if sd_image_path is not None and not sd_image_path.exists():
                raise SystemExit(f'Missing SD image for --run-only: {sd_image_path}')
            _set_phase('reusing simulator build')
            _log_progress('Reusing existing LiteX simulator build (--run-only)')
            _build_local_sim_modules(gateware_dir, enable_trace=args.trace or args.trace_fst, with_sdcard=args.with_sdcard)
            _stage_sd_image_for_run(gateware_dir=gateware_dir, sd_image_path=sd_image_path)
            return _run_simulator(
                gateware_dir=gateware_dir,
                binary_path=binary_path,
                required_markers=required_markers,
                timeout_seconds=args.timeout_seconds,
                log_path=log_path,
            )

        dts_path = _build_dts(output_dir, args)
        dtb_path = _build_dtb(dts_path)
        if args.with_sdcard:
            flash_image_path, sd_image_path = _build_sd_artifacts(output_dir, args, dtb_path)
        else:
            flash_image_path = _build_flash_image(output_dir, args, dtb_path)
            sd_image_path = None
        gateware_dir, binary_path = _build_simulator(args, output_dir, flash_image_path, sd_image_path)
        _stage_sd_image_for_run(gateware_dir=gateware_dir, sd_image_path=sd_image_path)

        if args.build_only:
            print(binary_path)
            return 0

        return _run_simulator(
            gateware_dir=gateware_dir,
            binary_path=binary_path,
            required_markers=required_markers,
            timeout_seconds=args.timeout_seconds,
            log_path=log_path,
        )
    except KeyboardInterrupt:
        _log_progress('Keyboard interrupt received; exiting cleanly')
        _RUN_DEBUG_STATE.exit_code = 130
        _emit_debug_summary('keyboard interrupt', captured='')
        return 130


def run(argv: list[str]) -> int:
    return main(argv) or 0


if __name__ == '__main__':
    raise SystemExit(main())