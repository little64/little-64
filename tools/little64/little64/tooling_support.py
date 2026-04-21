from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

from little64.build_support import run_checked
from little64.paths import repo_root


DEFAULT_ROOTFS_IMAGE = repo_root() / 'target' / 'linux_port' / 'rootfs' / 'build' / 'rootfs.ext4'


def resolve_python_bin(root: Path | None = None) -> str:
    repo = repo_root() if root is None else root
    override = os.environ.get('LITTLE64_PYTHON')
    if override:
        return override
    venv = repo / '.venv' / 'bin' / 'python'
    if venv.is_file() and os.access(venv, os.X_OK):
        return str(venv)
    return shutil.which('python3') or sys.executable


def python_has_module(python_bin: str, module_name: str) -> bool:
    return subprocess.run(
        [python_bin, '-c', f'import {module_name}'],
        capture_output=True,
        check=False,
    ).returncode == 0


def little64_command(*args: str, python_bin: str | None = None) -> list[str]:
    return [python_bin or sys.executable, '-m', 'little64', *args]


def compile_dts_to_dtb(
    dts_path: Path,
    *,
    dtb_path: Path | None = None,
    only_if_stale: bool = False,
) -> Path:
    resolved_dtb = dts_path.with_suffix('.dtb') if dtb_path is None else dtb_path
    if only_if_stale and resolved_dtb.exists() and resolved_dtb.stat().st_mtime >= dts_path.stat().st_mtime:
        return resolved_dtb

    run_checked([
        'dtc', '-I', 'dts', '-O', 'dtb',
        '-o', resolved_dtb,
        dts_path,
    ])
    return resolved_dtb


def build_default_rootfs_image(*, python_bin: str | None = None) -> Path:
    run_checked(little64_command('rootfs', 'build', python_bin=python_bin))
    if not DEFAULT_ROOTFS_IMAGE.is_file():
        raise FileNotFoundError(f'default rootfs builder did not produce {DEFAULT_ROOTFS_IMAGE}')
    return DEFAULT_ROOTFS_IMAGE