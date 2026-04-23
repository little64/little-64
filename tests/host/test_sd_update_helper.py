#!/usr/bin/env python3

from __future__ import annotations

import os
import pathlib
import subprocess
import sys


REPO = pathlib.Path(__file__).resolve().parents[2]
PKG = REPO / 'tools' / 'little64'
VENV_PYTHON = REPO / '.venv' / 'bin' / 'python'


def _python_env() -> dict[str, str]:
    env = os.environ.copy()
    env['PYTHONPATH'] = os.pathsep.join([str(PKG), env.get('PYTHONPATH', '')]).strip(os.pathsep)
    return env


def _run_python(code: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(VENV_PYTHON), '-c', code],
        env=_python_env(),
        capture_output=True,
        text=True,
    )


def main() -> int:
    if not VENV_PYTHON.is_file():
        sys.stderr.write(f'missing test interpreter: {VENV_PYTHON}\n')
        return 1

    result = _run_python(
        'import tempfile\n'
        'from pathlib import Path\n'
        'import little64.commands.sd.update as update\n'
        'SECTOR = 512\n'
        'def entry(start_lba, sector_count, partition_type):\n'
        '    item = bytearray(16)\n'
        '    item[4] = partition_type\n'
        '    item[8:12] = start_lba.to_bytes(4, "little")\n'
        '    item[12:16] = sector_count.to_bytes(4, "little")\n'
        '    return bytes(item)\n'
        'def write_mbr(path, boot_lba, boot_count, root_lba, root_count):\n'
        '    mbr = bytearray(SECTOR)\n'
        '    mbr[446:462] = entry(boot_lba, boot_count, 0x0C)\n'
        '    mbr[462:478] = entry(root_lba, root_count, 0x83)\n'
        '    mbr[510:512] = b"\\x55\\xaa"\n'
        '    with path.open("r+b") as handle:\n'
        '        handle.seek(0)\n'
        '        handle.write(mbr)\n'
        'with tempfile.TemporaryDirectory() as tmp:\n'
        '    tmp_path = Path(tmp)\n'
        '    boot_lba = 2048\n'
        '    boot_count = 8\n'
        '    root_lba = boot_lba + boot_count\n'
        '    root_count = 32\n'
        '    disk_bytes = (root_lba + root_count) * SECTOR\n'
        '    source = tmp_path / "source.img"\n'
        '    target = tmp_path / "target.img"\n'
        '    source.write_bytes(b"\\x00" * disk_bytes)\n'
        '    target.write_bytes(b"\\x00" * disk_bytes)\n'
        '    write_mbr(source, boot_lba, boot_count, root_lba, root_count)\n'
        '    write_mbr(target, boot_lba, boot_count, root_lba, root_count)\n'
        '    boot_payload = b"B" * (boot_count * SECTOR)\n'
        '    target_boot_before = b"T" * (boot_count * SECTOR)\n'
        '    target_root_before = b"R" * (root_count * SECTOR)\n'
        '    rootfs_payload = b"rootfs-update" * 73\n'
        '    with source.open("r+b") as handle:\n'
        '        handle.seek(boot_lba * SECTOR)\n'
        '        handle.write(boot_payload)\n'
        '    with target.open("r+b") as handle:\n'
        '        handle.seek(boot_lba * SECTOR)\n'
        '        handle.write(target_boot_before)\n'
        '        handle.seek(root_lba * SECTOR)\n'
        '        handle.write(target_root_before)\n'
        '    summary = update.update_partitioned_sd_device(source, target, rootfs_bytes=rootfs_payload)\n'
        '    assert summary["boot_partition_bytes"] == len(boot_payload)\n'
        '    assert summary["rootfs_bytes"] == len(rootfs_payload)\n'
        '    target_bytes = target.read_bytes()\n'
        '    boot_offset = boot_lba * SECTOR\n'
        '    root_offset = root_lba * SECTOR\n'
        '    assert target_bytes[boot_offset:boot_offset + len(boot_payload)] == boot_payload\n'
        '    assert target_bytes[root_offset:root_offset + len(rootfs_payload)] == rootfs_payload\n'
        '    root_suffix_end = root_offset + len(target_root_before)\n'
        '    assert target_bytes[root_offset + len(rootfs_payload):root_suffix_end] == target_root_before[len(rootfs_payload):]\n'
        'print("ok")\n'
    )
    if result.returncode != 0:
        sys.stderr.write(result.stdout + result.stderr)
        return result.returncode

    result = _run_python(
        'import tempfile\n'
        'from pathlib import Path\n'
        'import little64.commands.sd.update as update\n'
        'SECTOR = 512\n'
        'def entry(start_lba, sector_count, partition_type):\n'
        '    item = bytearray(16)\n'
        '    item[4] = partition_type\n'
        '    item[8:12] = start_lba.to_bytes(4, "little")\n'
        '    item[12:16] = sector_count.to_bytes(4, "little")\n'
        '    return bytes(item)\n'
        'def write_mbr(path, boot_lba, boot_count, root_lba, root_count):\n'
        '    mbr = bytearray(SECTOR)\n'
        '    mbr[446:462] = entry(boot_lba, boot_count, 0x0C)\n'
        '    mbr[462:478] = entry(root_lba, root_count, 0x83)\n'
        '    mbr[510:512] = b"\\x55\\xaa"\n'
        '    with path.open("r+b") as handle:\n'
        '        handle.seek(0)\n'
        '        handle.write(mbr)\n'
        'with tempfile.TemporaryDirectory() as tmp:\n'
        '    tmp_path = Path(tmp)\n'
        '    source = tmp_path / "source.img"\n'
        '    target = tmp_path / "target.img"\n'
        '    source.write_bytes(b"\\x00" * (4096 * SECTOR))\n'
        '    target.write_bytes(b"\\x00" * (4096 * SECTOR))\n'
        '    write_mbr(source, 2048, 8, 2056, 16)\n'
        '    write_mbr(target, 2048, 4, 2052, 16)\n'
        '    try:\n'
        '        update.update_partitioned_sd_device(source, target)\n'
        '        raise AssertionError("expected layout validation failure")\n'
        '    except ValueError as exc:\n'
        '        assert "boot partition" in str(exc) or "root partition" in str(exc)\n'
        'print("ok")\n'
    )
    if result.returncode != 0:
        sys.stderr.write(result.stdout + result.stderr)
        return result.returncode

    result = subprocess.run(
        [str(VENV_PYTHON), '-m', 'little64.cli', 'sd', 'update', '--help'],
        env=_python_env(),
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        sys.stderr.write(result.stdout + result.stderr)
        return result.returncode
    if '--device' not in result.stdout or '--update-rootfs' not in result.stdout:
        sys.stderr.write(result.stdout)
        return 1

    return 0


if __name__ == '__main__':
    raise SystemExit(main())