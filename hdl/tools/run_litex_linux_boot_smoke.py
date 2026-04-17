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

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import litex
from litex.build.sim.config import SimConfig

from little64.litex_soc import Little64LiteXSimSoC


REPO_ROOT = Path(__file__).resolve().parents[2]
LITEX_SIM_CORE_DIR = Path(litex.__file__).resolve().parent / 'build' / 'sim' / 'core'
LITEX_SIM_MODULES_DIR = REPO_ROOT / 'hdl' / 'tools' / 'litex_sim_modules'
DEFAULT_OUTPUT_DIR = REPO_ROOT / 'builddir' / 'hdl-litex-linux-boot'
DEFAULT_SD_OUTPUT_DIR = REPO_ROOT / 'builddir' / 'hdl-litex-linux-boot-sdcard'
DEFAULT_KERNEL_ELF = REPO_ROOT / 'target' / 'linux_port' / 'build-litex' / 'vmlinux'
GENERATE_DTS_SCRIPT = REPO_ROOT / 'hdl' / 'tools' / 'generate_litex_linux_dts.py'
FLASH_IMAGE_SCRIPT = REPO_ROOT / 'hdl' / 'tools' / 'build_litex_flash_image.py'
SD_ARTIFACT_SCRIPT = REPO_ROOT / 'target' / 'linux_port' / 'build_sd_boot_artifacts.py'
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


def _parse_int(value: str) -> int:
    return int(value, 0)


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


def parse_args() -> argparse.Namespace:
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
        help='LiteX CPU variant to use for the simulation SoC build.',
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
    return parser.parse_args()


def _run_checked(command: list[str], *, cwd: Path | None = None) -> None:
    subprocess.run(command, cwd=cwd, check=True)


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
    if not GENERATE_DTS_SCRIPT.exists():
        raise SystemExit(f'Missing DTS generator: {GENERATE_DTS_SCRIPT}')
    if not FLASH_IMAGE_SCRIPT.exists():
        raise SystemExit(f'Missing flash image helper: {FLASH_IMAGE_SCRIPT}')
    if args.with_sdcard and not SD_ARTIFACT_SCRIPT.exists():
        raise SystemExit(f'Missing SD artifact helper: {SD_ARTIFACT_SCRIPT}')
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
    dts_path = output_dir / 'little64-litex-sim.dts'
    command: list[str] = [
        sys.executable,
        str(GENERATE_DTS_SCRIPT),
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
    _run_checked(command)
    return dts_path


def _build_dtb(dts_path: Path) -> Path:
    dtb_path = dts_path.with_suffix('.dtb')
    if dtb_path.exists() and dtb_path.stat().st_mtime >= dts_path.stat().st_mtime:
        return dtb_path
    _run_checked(['dtc', '-I', 'dts', '-O', 'dtb', '-o', str(dtb_path), str(dts_path)])
    return dtb_path


def _build_flash_image(output_dir: Path, args: argparse.Namespace, dtb_path: Path) -> Path:
    flash_image_path = output_dir / 'little64-linux-spiflash.bin'
    _run_checked([
        sys.executable,
        str(FLASH_IMAGE_SCRIPT),
        '--kernel-elf',
        str(args.kernel_elf),
        '--dtb',
        str(dtb_path),
        '--output',
        str(flash_image_path),
    ])
    return flash_image_path


def _build_sd_artifacts(output_dir: Path, args: argparse.Namespace, dtb_path: Path) -> tuple[Path, Path]:
    flash_image_path = output_dir / 'little64-sd-stage0-bootrom.bin'
    sd_image_path = output_dir / 'little64-linux-sdcard.img'
    command: list[str] = [
        sys.executable,
        str(SD_ARTIFACT_SCRIPT),
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
    _run_checked(command)
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
    ])
    _run_checked([
        compiler,
        '-shared',
        '-fPIC',
        '-Wl,-soname,' + shared_object_path.name,
        '-o',
        str(shared_object_path),
        str(object_path),
    ])


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
            'integrated_rom_init': str(flash_image_path),
        })
    else:
        soc_kwargs.update({
            'with_spi_flash': True,
            'spi_flash_image_path': flash_image_path,
        })
    soc = Little64LiteXSimSoC(**soc_kwargs)
    soc.platform.output_dir = str(output_dir)
    return soc


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
    enable_trace = args.trace or args.trace_fst
    sim_config = SimConfig()
    sim_config.add_clocker('sys_clk', freq_hz=int(1e9))
    sim_config.add_module('resetpulse', [], clocks='sys_rst', tickfirst=True)
    if enable_trace:
        sim_config.add_module('simtraceon', [], clocks='sim_trace', tickfirst=True)
    sim_config.add_module('serial2console', 'serial')
    if args.with_sdcard:
        sim_config.add_module('sdcardimage', 'sdcard_img', clocks='sys_clk', tickfirst=True)

    soc = _create_soc(args, output_dir, flash_image_path, sd_image_path)
    gateware_dir = output_dir / 'gateware'
    gateware_dir.mkdir(parents=True, exist_ok=True)
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

    build_script = gateware_dir / 'build_sim.sh'
    if not build_script.exists():
        raise SystemExit(f'LiteX simulator build script was not generated: {build_script}')
    _apply_litex_sim_compatibility_patches()
    if enable_trace:
        _patch_generated_sim_init(gateware_dir)
    _restrict_sim_modules(build_script, sim_config)
    _run_checked(['bash', build_script.name], cwd=gateware_dir)
    _build_local_sim_modules(gateware_dir, enable_trace=enable_trace, with_sdcard=args.with_sdcard)

    binary_path = gateware_dir / 'obj_dir' / 'Vsim'
    if not binary_path.exists():
        raise SystemExit(f'LiteX simulator binary was not generated: {binary_path}')
    _write_build_config(output_dir, _build_config(args))
    return gateware_dir, binary_path


def _stage_sd_image_for_run(*, gateware_dir: Path, sd_image_path: Path | None) -> None:
    if sd_image_path is None:
        return
    staged_image = gateware_dir / 'sdcard.img'
    shutil.copyfile(sd_image_path, staged_image)


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
    success = False
    timed_out = False
    exit_code: int | None = None

    with log_path.open('w', encoding='utf-8') as log_file:
        while True:
            remaining = deadline - time.monotonic()
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
            sys.stdout.write(text)
            sys.stdout.flush()
            log_file.write(text)
            log_file.flush()
            captured += text
            if len(captured) > 65536:
                captured = captured[-65536:]

            if all(marker in captured for marker in required_markers):
                success = True
                process.terminate()
                _wait_for_exit(process, 2.0)
                exit_code = process.returncode
                break

        if not success and process.poll() is None:
            process.kill()
            process.wait()
        exit_code = process.returncode

    selector.close()

    if success:
        return 0

    missing_markers = [marker for marker in required_markers if marker not in captured]
    tail = captured[-2048:]
    sys.stderr.write(
        '\nLiteX Linux boot smoke failed to reach the required markers.\n'
        f'log: {log_path}\n'
        f'timed_out: {int(timed_out)}\n'
        f'exit_code: {exit_code}\n'
        f'missing_markers: {missing_markers}\n'
        'serial_tail:\n'
        f'{tail}\n'
    )
    return 1


def main() -> int:
    args = parse_args()
    if args.build_only and args.run_only:
        raise SystemExit('--build-only and --run-only are mutually exclusive')

    args.kernel_elf = args.kernel_elf.resolve()
    output_dir = _resolved_output_dir(args).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    _prepare_output_dir(output_dir, args, run_only=args.run_only)
    _ensure_prerequisites(args)

    required_markers = _resolve_required_markers(args)
    log_path = output_dir / 'litex-sim-serial.log'

    if args.run_only:
        gateware_dir = output_dir / 'gateware'
        binary_path = gateware_dir / 'obj_dir' / 'Vsim'
        if not binary_path.exists():
            raise SystemExit(f'Missing LiteX simulator binary for --run-only: {binary_path}')
        sd_image_path = output_dir / 'little64-linux-sdcard.img' if args.with_sdcard else None
        if sd_image_path is not None and not sd_image_path.exists():
            raise SystemExit(f'Missing SD image for --run-only: {sd_image_path}')
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


if __name__ == '__main__':
    raise SystemExit(main())