from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
BUILD_ROOT = REPO_ROOT / 'builddir' / 'hdl-verilator-linux-boot'
VMLINUX = REPO_ROOT / 'target' / 'linux_port' / 'build-little64_litex_sim_defconfig' / 'vmlinux'
GENERATE_DTS_SCRIPT = REPO_ROOT / 'hdl' / 'tools' / 'generate_litex_linux_dts.py'
EXPORT_SCRIPT = REPO_ROOT / 'hdl' / 'tools' / 'export_linux_boot_verilog.py'
FLASH_BUILD_SCRIPT = REPO_ROOT / 'hdl' / 'tools' / 'build_litex_flash_image.py'
HARNESS_CPP = REPO_ROOT / 'hdl' / 'tools' / 'verilator_linux_boot_smoke_main.cpp'

VERILOG = BUILD_ROOT / 'little64_linux_boot_top.v'
DTS = BUILD_ROOT / 'little64-litex-sim.dts'
DTB = BUILD_ROOT / 'little64-litex-sim.dtb'
FLASH_IMAGE = BUILD_ROOT / 'little64-linux-spiflash.bin'
OBJDIR = BUILD_ROOT / 'obj'


def _default_verilator_threads() -> int:
    # For this harness, wider Verilator threading adds more coordination
    # overhead than useful parallelism in the common early-boot debug window.
    return 1


THREADS = max(1, int(os.environ.get('LITTLE64_VERILATOR_THREADS', str(_default_verilator_threads()))))
BUILD_JOBS = max(1, int(os.environ.get('LITTLE64_VERILATOR_BUILD_JOBS', str(os.cpu_count() or 1))))
HARNESS_DEBUG = os.environ.get('LITTLE64_VERILATOR_COMPILE_DEBUG', '1') != '0'
CXXFLAGS = os.environ.get('LITTLE64_VERILATOR_CFLAGS', '-O3 -std=c++20 -march=native -flto -DNDEBUG')
LDFLAGS = os.environ.get('LITTLE64_VERILATOR_LDFLAGS', '-O3 -march=native -flto')
HARNESS_CXXFLAGS = f'{CXXFLAGS} -DLITTLE64_HARNESS_ENABLE_DEBUG={1 if HARNESS_DEBUG else 0}'
BINARY_NAME = f'little64_linux_boot_smoke_t{THREADS}' + ('' if HARNESS_DEBUG else '_ndbg')
BINARY = OBJDIR / BINARY_NAME
BOOTARGS = os.environ.get(
    'LITTLE64_VERILATOR_BOOTARGS',
    'console=liteuart earlycon=liteuart,0xf0001000 ignore_loglevel loglevel=8',
)

REQUIRED_MARKERS = [
    'little64-timer: clocksource + clockevent @ 1 GHz',
    'physmap platform flash device:',
    'VFS: Unable to mount root fs',
]


def _latest_mtime(paths: list[Path]) -> float:
    return max(path.stat().st_mtime for path in paths)


def _hdl_sources() -> list[Path]:
    return sorted((REPO_ROOT / 'hdl' / 'little64').glob('*.py'))


def _run_checked(command: list[str]) -> None:
    subprocess.run(command, check=True)


def _ensure_prerequisites() -> None:
    if not VMLINUX.exists() or not GENERATE_DTS_SCRIPT.exists():
        raise SystemExit(77)
    if shutil.which('verilator') is None or shutil.which('dtc') is None:
        raise SystemExit(77)


def _build_dts() -> None:
    BUILD_ROOT.mkdir(parents=True, exist_ok=True)
    sources = [GENERATE_DTS_SCRIPT, *_hdl_sources()]
    if DTS.exists() and DTS.stat().st_mtime >= _latest_mtime(sources):
        return
    _run_checked([
        sys.executable,
        str(GENERATE_DTS_SCRIPT),
        '--output',
        str(DTS),
        '--with-spi-flash',
        '--bootargs',
        BOOTARGS,
    ])


def _build_dtb() -> None:
    BUILD_ROOT.mkdir(parents=True, exist_ok=True)
    if DTB.exists() and DTB.stat().st_mtime >= DTS.stat().st_mtime:
        return
    _run_checked(['dtc', '-I', 'dts', '-O', 'dtb', '-o', str(DTB), str(DTS)])


def _build_verilog() -> None:
    sources = [EXPORT_SCRIPT, *_hdl_sources()]
    if VERILOG.exists() and VERILOG.stat().st_mtime >= _latest_mtime(sources):
        return
    _run_checked([sys.executable, str(EXPORT_SCRIPT), str(VERILOG)])


def _build_flash_image() -> None:
    deps = [
        FLASH_BUILD_SCRIPT,
        VMLINUX,
        DTB,
        REPO_ROOT / 'target' / 'c_boot' / 'litex_spi_boot.c',
        REPO_ROOT / 'target' / 'c_boot' / 'linker_litex_spi_boot.ld',
        REPO_ROOT / 'hdl' / 'little64' / 'litex.py',
        REPO_ROOT / 'hdl' / 'little64' / 'litex_linux_boot.py',
    ]
    if FLASH_IMAGE.exists() and FLASH_IMAGE.stat().st_mtime >= _latest_mtime(deps):
        return
    _run_checked([
        sys.executable,
        str(FLASH_BUILD_SCRIPT),
        '--kernel-elf',
        str(VMLINUX),
        '--dtb',
        str(DTB),
        '--output',
        str(FLASH_IMAGE),
    ])


def _build_binary() -> None:
    BUILD_ROOT.mkdir(parents=True, exist_ok=True)
    deps = [VERILOG, HARNESS_CPP]
    if BINARY.exists() and BINARY.stat().st_mtime >= _latest_mtime(deps):
        return

    if OBJDIR.exists():
        shutil.rmtree(OBJDIR)

    command = [
        'verilator',
        '--cc',
        str(VERILOG),
        '--top-module',
        'little64_linux_boot_top',
        '--exe',
        str(HARNESS_CPP),
        '--build',
        '--Mdir',
        str(OBJDIR),
        '--O3',
        '--x-assign', 'fast',
        '--x-initial', 'fast',
        '--noassert',
        '-Wno-fatal',
        '-Wno-CASEINCOMPLETE',
        '-Wno-WIDTHTRUNC',
        '-Wno-WIDTHEXPAND',
        '-CFLAGS',
        HARNESS_CXXFLAGS,
        '-LDFLAGS',
        LDFLAGS,
        '-o',
        BINARY_NAME,
        '-j',
        str(BUILD_JOBS),
    ]
    if THREADS > 1:
        command.extend(['--threads', str(THREADS)])
    _run_checked(command)


def main() -> int:
    _ensure_prerequisites()
    _build_dts()
    _build_dtb()
    _build_verilog()
    _build_flash_image()
    _build_binary()

    command = [
        str(BINARY),
        '--kernel',
        str(VMLINUX),
        '--flash',
        str(FLASH_IMAGE),
        '--max-cycles',
        os.environ.get('LITTLE64_VERILATOR_MAX_CYCLES', '200000000'),
    ]
    for marker in REQUIRED_MARKERS:
        command.extend(['--require', marker])

    return subprocess.run(command, check=False).returncode


if __name__ == '__main__':
    raise SystemExit(main())