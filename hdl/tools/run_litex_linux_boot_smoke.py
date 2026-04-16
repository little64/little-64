#!/usr/bin/env python3

from __future__ import annotations

import argparse
import os
import selectors
import shutil
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import litex
from litex.build.sim.config import SimConfig

from little64.litex_soc import Little64LiteXSimSoC


REPO_ROOT = Path(__file__).resolve().parents[2]
LITEX_SIM_CORE_DIR = Path(litex.__file__).resolve().parent / 'build' / 'sim' / 'core'
LITEX_SIM_MODULES_DIR = REPO_ROOT / 'hdl' / 'tools' / 'litex_sim_modules'
DEFAULT_OUTPUT_DIR = REPO_ROOT / 'builddir' / 'hdl-litex-linux-boot'
DEFAULT_KERNEL_ELF = REPO_ROOT / 'target' / 'linux_port' / 'build-little64_litex_sim_defconfig' / 'vmlinux'
GENERATE_DTS_SCRIPT = REPO_ROOT / 'hdl' / 'tools' / 'generate_litex_linux_dts.py'
FLASH_IMAGE_SCRIPT = REPO_ROOT / 'hdl' / 'tools' / 'build_litex_flash_image.py'
DEFAULT_BOOTARGS = 'console=liteuart earlycon=liteuart,0xf0001000 ignore_loglevel loglevel=8'
DEFAULT_REQUIRED_MARKERS = [
    'little64-timer: clocksource + clockevent @ 1 GHz',
    'physmap platform flash device:',
    'VFS: Unable to mount root fs',
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
BCONSOLE_SOURCE = LITEX_SIM_MODULES_DIR / 'breadcrumbconsole.c'
SIMTRACEON_SOURCE = LITEX_SIM_MODULES_DIR / 'simtraceon.c'
LITEX_SIM_COMPAT_PATCHES = {
    Path('modules/clocker/clocker.c'): [
        ('static int clocker_start()', 'static int clocker_start(void *unused)'),
    ],
    Path('modules/spdeeprom/spdeeprom.c'): [
        ('static int spdeeprom_start();', 'static int spdeeprom_start(void *unused);'),
        ('static int spdeeprom_start()', 'static int spdeeprom_start(void *unused)'),
    ],
}


def _parse_int(value: str) -> int:
    return int(value, 0)


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
        '--bootargs',
        default=DEFAULT_BOOTARGS,
        help='Bootargs injected into the generated LiteX simulation DTS.',
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
        help='Required serial substring. Can be repeated. Defaults to the standard LiteX smoke markers.',
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
    command = [
        sys.executable,
        str(GENERATE_DTS_SCRIPT),
        '--output',
        str(dts_path),
        '--with-spi-flash',
        '--bootargs',
        args.bootargs,
    ]
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


def _build_local_sim_modules(gateware_dir: Path, *, enable_trace: bool) -> None:
    _build_local_sim_module(gateware_dir, RESETPULSE_SOURCE)
    _build_local_sim_module(gateware_dir, BCONSOLE_SOURCE)
    if enable_trace:
        _build_local_sim_module(gateware_dir, SIMTRACEON_SOURCE)


def _create_soc(args: argparse.Namespace, output_dir: Path, flash_image_path: Path) -> Little64LiteXSimSoC:
    soc = Little64LiteXSimSoC(
        integrated_main_ram_size=0 if args.with_sdram else args.integrated_main_ram_size,
        with_sdram=args.with_sdram,
        with_spi_flash=True,
        with_timer=True,
        spi_flash_image_path=flash_image_path,
    )
    soc.platform.output_dir = str(output_dir)
    return soc


def _restrict_sim_modules(build_script: Path, sim_config: SimConfig) -> None:
    required_modules = sorted({
        module['module']
        for module in sim_config.modules
        if module['module'] in LITEX_BUILTIN_SIM_MODULES
    })
    module_list = ' '.join(required_modules)
    original = build_script.read_text(encoding='utf-8')
    marker = ' OPT_LEVEL='
    if marker not in original:
        raise SystemExit(f'Unable to restrict LiteX simulation modules in {build_script}')
    patched = original.replace(marker, f' MODULES="{module_list}"{marker}', 1)
    build_script.write_text(patched, encoding='utf-8')


def _build_simulator(args: argparse.Namespace, output_dir: Path, flash_image_path: Path) -> tuple[Path, Path]:
    enable_trace = args.trace or args.trace_fst
    sim_config = SimConfig()
    sim_config.add_clocker('sys_clk', freq_hz=int(1e6))
    sim_config.add_module('resetpulse', [], clocks='sys_rst', tickfirst=True)
    if enable_trace:
        sim_config.add_module('simtraceon', [], clocks='sim_trace', tickfirst=True)
    sim_config.add_module('breadcrumbconsole', 'breadcrumb')
    sim_config.add_module('serial2console', 'serial')

    soc = _create_soc(args, output_dir, flash_image_path)
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
    _build_local_sim_modules(gateware_dir, enable_trace=enable_trace)

    binary_path = gateware_dir / 'obj_dir' / 'Vsim'
    if not binary_path.exists():
        raise SystemExit(f'LiteX simulator binary was not generated: {binary_path}')
    return gateware_dir, binary_path


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

    with log_path.open('w', encoding='utf-8') as log_file:
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
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
                break

        if not success and process.poll() is None:
            process.kill()
            process.wait()

    selector.close()

    if success:
        return 0

    tail = captured[-2048:]
    sys.stderr.write(
        '\nLiteX Linux boot smoke failed to reach the required markers.\n'
        f'log: {log_path}\n'
        'serial_tail:\n'
        f'{tail}\n'
    )
    return 1


def main() -> int:
    args = parse_args()
    if args.build_only and args.run_only:
        raise SystemExit('--build-only and --run-only are mutually exclusive')

    args.kernel_elf = args.kernel_elf.resolve()
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    _ensure_prerequisites(args)

    required_markers = args.require or list(DEFAULT_REQUIRED_MARKERS)
    log_path = output_dir / 'litex-sim-serial.log'

    if args.run_only:
        gateware_dir = output_dir / 'gateware'
        binary_path = gateware_dir / 'obj_dir' / 'Vsim'
        if not binary_path.exists():
            raise SystemExit(f'Missing LiteX simulator binary for --run-only: {binary_path}')
        _build_local_sim_modules(gateware_dir, enable_trace=args.trace or args.trace_fst)
        return _run_simulator(
            gateware_dir=gateware_dir,
            binary_path=binary_path,
            required_markers=required_markers,
            timeout_seconds=args.timeout_seconds,
            log_path=log_path,
        )

    dts_path = _build_dts(output_dir, args)
    dtb_path = _build_dtb(dts_path)
    flash_image_path = _build_flash_image(output_dir, args, dtb_path)
    gateware_dir, binary_path = _build_simulator(args, output_dir, flash_image_path)

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