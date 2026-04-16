from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
BUILD_ROOT = REPO_ROOT / 'builddir' / 'hdl-verilator-linux-boot'
VMLINUX = REPO_ROOT / 'target' / 'linux_port' / 'build' / 'vmlinux'
DTS = REPO_ROOT / 'target' / 'linux_port' / 'linux' / 'arch' / 'little64' / 'boot' / 'dts' / 'little64.dts'
EXPORT_SCRIPT = REPO_ROOT / 'hdl' / 'tools' / 'export_linux_boot_verilog.py'
HARNESS_CPP = REPO_ROOT / 'hdl' / 'tools' / 'verilator_linux_boot_smoke_main.cpp'

VERILOG = BUILD_ROOT / 'little64_linux_boot_top.v'
DTB = BUILD_ROOT / 'little64.dtb'
OBJDIR = BUILD_ROOT / 'obj'


def _default_verilator_threads() -> int:
    # For this harness, wider Verilator threading adds more coordination
    # overhead than useful parallelism in the common early-boot debug window.
    return 1


THREADS = max(1, int(os.environ.get('LITTLE64_VERILATOR_THREADS', str(_default_verilator_threads()))))
BUILD_JOBS = max(1, int(os.environ.get('LITTLE64_VERILATOR_BUILD_JOBS', str(os.cpu_count() or 1))))
CXXFLAGS = os.environ.get('LITTLE64_VERILATOR_CFLAGS', '-O3 -std=c++20 -march=native -flto -DNDEBUG')
LDFLAGS = os.environ.get('LITTLE64_VERILATOR_LDFLAGS', '-O3 -march=native -flto')
BINARY_NAME = f'little64_linux_boot_smoke_t{THREADS}'
BINARY = OBJDIR / BINARY_NAME

REQUIRED_MARKERS = [
    'little64-timer: clocksource + clockevent @ 1 GHz',
    'Little64 PV block disk:',
    'Kernel panic - not syncing: VFS: Unable to mount root fs',
]


def _latest_mtime(paths: list[Path]) -> float:
    return max(path.stat().st_mtime for path in paths)


def _hdl_sources() -> list[Path]:
    return sorted((REPO_ROOT / 'hdl' / 'little64').glob('*.py'))


def _run_checked(command: list[str]) -> None:
    subprocess.run(command, check=True)


def _ensure_prerequisites() -> None:
    if not VMLINUX.exists() or not DTS.exists():
        raise SystemExit(77)
    if shutil.which('verilator') is None or shutil.which('dtc') is None:
        raise SystemExit(77)


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
        CXXFLAGS,
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
    _build_dtb()
    _build_verilog()
    _build_binary()

    command = [
        str(BINARY),
        '--kernel',
        str(VMLINUX),
        '--dtb',
        str(DTB),
        '--max-cycles',
        os.environ.get('LITTLE64_VERILATOR_MAX_CYCLES', '200000000'),
    ]
    for marker in REQUIRED_MARKERS:
        command.extend(['--require', marker])

    return subprocess.run(command, check=False).returncode


if __name__ == '__main__':
    raise SystemExit(main())