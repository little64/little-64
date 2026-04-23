"""Update an existing Little64 SD card without rewriting the full raw image."""

from __future__ import annotations

import argparse
import os
import stat
from dataclasses import dataclass
from pathlib import Path
import sys
from typing import List

import little64.commands.sd.artifacts as sd_artifacts
from little64.paths import repo_root
from little64.tooling_support import build_default_rootfs_image


SECTOR_SIZE = 512
_MBR_SIGNATURE = b"\x55\xaa"
_MBR_SIGNATURE_OFFSET = 510
_MBR_PARTITION_OFFSET = 446
_MBR_PARTITION_SIZE = 16
_FAT32_PARTITION_TYPES = {0x0B, 0x0C}


@dataclass(frozen=True, slots=True)
class PartitionEntry:
    index: int
    partition_type: int
    start_lba: int
    sector_count: int

    @property
    def start_offset(self) -> int:
        return self.start_lba * SECTOR_SIZE

    @property
    def size_bytes(self) -> int:
        return self.sector_count * SECTOR_SIZE


def _default_sd_image_candidates() -> tuple[Path, ...]:
    repo = repo_root()
    candidates = [
        repo / 'builddir' / 'hdl-litex-arty' / 'boot' / 'little64_arty_a7_35_sdcard.img',
        sd_artifacts._default_output_dir(sd_artifacts.DEFAULT_LITEX_MACHINE) / 'little64-linux-sdcard.img',
    ]
    resolved: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        key = str(candidate)
        if key in seen:
            continue
        resolved.append(candidate)
        seen.add(key)
    return tuple(resolved)


def _parse_partition_entry(mbr: bytes, index: int) -> PartitionEntry:
    offset = _MBR_PARTITION_OFFSET + (index - 1) * _MBR_PARTITION_SIZE
    partition_type = mbr[offset + 4]
    start_lba = int.from_bytes(mbr[offset + 8:offset + 12], 'little')
    sector_count = int.from_bytes(mbr[offset + 12:offset + 16], 'little')
    return PartitionEntry(
        index=index,
        partition_type=partition_type,
        start_lba=start_lba,
        sector_count=sector_count,
    )


def _read_partition_entries(path: Path) -> tuple[PartitionEntry, PartitionEntry]:
    with path.open('rb') as handle:
        mbr = handle.read(SECTOR_SIZE)
    if len(mbr) != SECTOR_SIZE:
        raise ValueError(f'{path} is too small to contain an MBR')
    if mbr[_MBR_SIGNATURE_OFFSET:_MBR_SIGNATURE_OFFSET + 2] != _MBR_SIGNATURE:
        raise ValueError(f'{path} does not contain a valid MBR signature')

    boot_partition = _parse_partition_entry(mbr, 1)
    root_partition = _parse_partition_entry(mbr, 2)
    if boot_partition.sector_count == 0:
        raise ValueError(f'{path} is missing partition 1')
    if root_partition.sector_count == 0:
        raise ValueError(f'{path} is missing partition 2')
    return boot_partition, root_partition


def _read_exact_range(path: Path, offset: int, size: int) -> bytes:
    with path.open('rb') as handle:
        handle.seek(offset)
        data = handle.read(size)
    if len(data) != size:
        raise ValueError(f'{path} ended unexpectedly while reading {size} bytes at offset {offset}')
    return data


def _partition_device_path(device: Path, index: int) -> Path:
    suffix = f'p{index}' if device.name[-1:].isdigit() else str(index)
    return device.with_name(f'{device.name}{suffix}')


def _mounted_sources() -> set[str]:
    mounts: set[str] = set()
    try:
        with Path('/proc/self/mounts').open('r', encoding='utf-8') as handle:
            for line in handle:
                if not line.strip():
                    continue
                mounts.add(line.split()[0].replace('\\040', ' '))
    except OSError:
        return set()
    return mounts


def _ensure_target_is_safe(device: Path) -> None:
    try:
        mode = device.stat().st_mode
    except FileNotFoundError as exc:
        raise ValueError(f'target device not found: {device}') from exc

    if stat.S_ISBLK(mode):
        mounted = _mounted_sources()
        blocked = [
            candidate
            for candidate in (device, _partition_device_path(device, 1), _partition_device_path(device, 2))
            if str(candidate) in mounted
        ]
        if blocked:
            blocked_text = ', '.join(str(path) for path in blocked)
            raise ValueError(f'refusing to update a mounted device: {blocked_text}')
        return

    if not stat.S_ISREG(mode):
        raise ValueError(f'target must be a block device or regular file: {device}')


def _resolve_sd_image(sd_image: Path | None) -> Path:
    if sd_image is not None:
        resolved = sd_image.expanduser()
        if resolved.is_file():
            return resolved
        raise ValueError(f'source SD image not found: {resolved}')

    for candidate in _default_sd_image_candidates():
        if candidate.is_file():
            return candidate

    candidate_text = '\n'.join(str(path) for path in _default_sd_image_candidates())
    raise ValueError(
        'no staged SD image was found; pass --sd-image or build one first with '\
        '"little64 hdl arty-build --generate-only" or "little64 sd build --machine litex". '\
        f'Checked:\n{candidate_text}'
    )


def _resolve_rootfs_payload(args: argparse.Namespace) -> tuple[bytes | None, Path | None]:
    if args.rootfs_image is not None:
        rootfs_path = args.rootfs_image.expanduser()
        if not rootfs_path.is_file():
            raise ValueError(f'rootfs image not found: {rootfs_path}')
        return rootfs_path.read_bytes(), rootfs_path

    if args.update_rootfs:
        rootfs_path = build_default_rootfs_image(python_bin=sys.executable)
        return rootfs_path.read_bytes(), rootfs_path

    return None, None


def _validate_target_layout(
    source_boot: PartitionEntry,
    source_root: PartitionEntry,
    target_boot: PartitionEntry,
    target_root: PartitionEntry,
    *,
    rootfs_bytes: bytes | None,
) -> None:
    if source_boot.partition_type not in _FAT32_PARTITION_TYPES:
        raise ValueError('source image partition 1 is not FAT32')
    if target_boot.partition_type not in _FAT32_PARTITION_TYPES:
        raise ValueError('target partition 1 is not FAT32')
    if source_root.partition_type != 0x83:
        raise ValueError('source image partition 2 is not Linux type 0x83')
    if target_root.partition_type != 0x83:
        raise ValueError('target partition 2 is not Linux type 0x83')
    if target_boot.start_lba != source_boot.start_lba:
        raise ValueError(
            f'target boot partition starts at LBA {target_boot.start_lba}, expected {source_boot.start_lba}'
        )
    if target_boot.sector_count < source_boot.sector_count:
        raise ValueError(
            f'target boot partition is too small ({target_boot.sector_count} sectors, expected at least {source_boot.sector_count})'
        )
    if target_root.start_lba != source_root.start_lba:
        raise ValueError(
            f'target root partition starts at LBA {target_root.start_lba}, expected {source_root.start_lba}'
        )
    if rootfs_bytes is not None and len(rootfs_bytes) > target_root.size_bytes:
        raise ValueError(
            f'rootfs payload ({len(rootfs_bytes)} bytes) does not fit in target partition 2 ({target_root.size_bytes} bytes)'
        )


def update_partitioned_sd_device(
    source_image: Path,
    target_device: Path,
    *,
    rootfs_bytes: bytes | None = None,
    dry_run: bool = False,
) -> dict[str, int]:
    source_boot, source_root = _read_partition_entries(source_image)
    target_boot, target_root = _read_partition_entries(target_device)
    _validate_target_layout(
        source_boot,
        source_root,
        target_boot,
        target_root,
        rootfs_bytes=rootfs_bytes,
    )

    summary = {
        'boot_partition_offset': target_boot.start_offset,
        'boot_partition_bytes': source_boot.size_bytes,
        'root_partition_offset': target_root.start_offset,
        'rootfs_bytes': 0 if rootfs_bytes is None else len(rootfs_bytes),
    }
    if dry_run:
        return summary

    boot_partition_bytes = _read_exact_range(source_image, source_boot.start_offset, source_boot.size_bytes)
    with target_device.open('r+b', buffering=0) as handle:
        handle.seek(target_boot.start_offset)
        handle.write(boot_partition_bytes)
        if rootfs_bytes is not None:
            handle.seek(target_root.start_offset)
            handle.write(rootfs_bytes)
        handle.flush()
        os.fsync(handle.fileno())
    return summary


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description='Update a correctly partitioned SD card or raw disk image without rewriting the full raw image.'
    )
    parser.add_argument('--device', type=Path, required=True,
        help='Target block device or raw disk image file to update in place.')
    parser.add_argument('--sd-image', type=Path, default=None,
        help='Source SD image produced by little64 sd build or little64 hdl arty-build. Defaults to the staged Arty image when present.')
    parser.add_argument('--update-rootfs', action='store_true',
        help='Also rewrite partition 2 with the default generated rootfs image.')
    parser.add_argument('--rootfs-image', type=Path, default=None,
        help='Explicit ext4 image to write into partition 2. Implies --update-rootfs behavior for the second partition.')
    parser.add_argument('--dry-run', action='store_true',
        help='Validate the target layout and print the planned writes without modifying the device.')
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    try:
        source_image = _resolve_sd_image(args.sd_image)
        target_device = args.device.expanduser()
        _ensure_target_is_safe(target_device)
        rootfs_bytes, rootfs_path = _resolve_rootfs_payload(args)
        summary = update_partitioned_sd_device(
            source_image,
            target_device,
            rootfs_bytes=rootfs_bytes,
            dry_run=args.dry_run,
        )
    except (OSError, ValueError) as exc:
        print(f'error: {exc}', file=sys.stderr)
        return 1

    action = 'Would update' if args.dry_run else 'Updated'
    print(
        f'{action} boot partition: {summary["boot_partition_bytes"]} bytes from {source_image} '
        f'to {target_device} at offset {summary["boot_partition_offset"]}'
    )
    if rootfs_bytes is None:
        print('Left partition 2 unchanged.')
    else:
        origin = 'default generated rootfs image' if rootfs_path is None else str(rootfs_path)
        rootfs_action = 'Would update' if args.dry_run else 'Updated'
        print(
            f'{rootfs_action} partition 2: {summary["rootfs_bytes"]} bytes from {origin} '
            f'to {target_device} at offset {summary["root_partition_offset"]}'
        )
    return 0


def run(argv: List[str]) -> int:
    return main(argv) or 0


if __name__ == '__main__':
    raise SystemExit(main())