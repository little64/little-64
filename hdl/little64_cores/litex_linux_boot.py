from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import struct
import zlib

from .litex import (
    LITTLE64_LINUX_RAM_BASE,
    LITTLE64_LITEX_FLASH_BOOT_ABI_VERSION,
    LITTLE64_LITEX_FLASH_BOOT_HEADER_OFFSET,
    LITTLE64_LITEX_FLASH_BOOT_MAGIC,
)


EM_LITTLE64 = 0x4C36
PT_LOAD = 1
PAGE_SIZE = 4096
EARLY_PT_SCRATCH_PAGES = 30
FLASH_BOOT_HEADER = struct.Struct('<16Q')
SECTOR_SIZE = 512
DEFAULT_SD_CARD_SIZE_BYTES = 4 * 1024 * 1024 * 1024
DEFAULT_SD_BOOT_PARTITION_SIZE_MB = 256
BOOT_CHECKSUM_MAGIC = 0x4C36434B
BOOT_CHECKSUM_VERSION = 1
BOOT_CHECKSUM_STRUCT = struct.Struct('<8I')


@dataclass(frozen=True, slots=True)
class Little64LinuxElfImage:
    image: bytes
    image_span: int
    virtual_base: int
    entry_physical: int


@dataclass(frozen=True, slots=True)
class Little64FlashImageLayout:
    flash_image: bytes
    kernel_flash_offset: int
    dtb_flash_offset: int
    kernel_physical_base: int
    kernel_entry_physical: int
    dtb_physical_address: int
    kernel_boot_stack_top: int


@dataclass(frozen=True, slots=True)
class Little64SDCardFileLayout:
    short_name: bytes
    first_cluster: int
    size: int


@dataclass(frozen=True, slots=True)
class Little64SDCardBootChecksums:
    kernel_image_crc32: int
    kernel_image_size: int
    dtb_crc32: int
    dtb_size: int


@dataclass(frozen=True, slots=True)
class Little64SDCardImageLayout:
    disk_image: bytes | None
    disk_size_bytes: int
    boot_partition_lba: int
    boot_partition_sector_count: int
    root_partition_lba: int
    root_partition_sector_count: int
    kernel_file: Little64SDCardFileLayout
    dtb_file: Little64SDCardFileLayout
    checksums_file: Little64SDCardFileLayout
    checksums: Little64SDCardBootChecksums


def _align_up(value: int, alignment: int) -> int:
    return (value + alignment - 1) & -alignment


def _ceil_div(value: int, divisor: int) -> int:
    return (value + divisor - 1) // divisor


def _fat32_short_name(name: str) -> bytes:
    if '.' in name:
        stem, extension = name.split('.', 1)
    else:
        stem, extension = name, ''
    stem = stem.upper()
    extension = extension.upper()
    if len(stem) > 8 or len(extension) > 3:
        raise ValueError(f'FAT32 short name is too long: {name}')
    if not stem:
        raise ValueError('FAT32 short name stem cannot be empty')
    return stem.ljust(8).encode('ascii') + extension.ljust(3).encode('ascii')


def _write_u16_le(buffer: bytearray, offset: int, value: int) -> None:
    buffer[offset:offset + 2] = struct.pack('<H', value)


def _write_u32_le(buffer: bytearray, offset: int, value: int) -> None:
    buffer[offset:offset + 4] = struct.pack('<I', value)


def _partition_entry(start_lba: int, sector_count: int, partition_type: int) -> bytes:
    entry = bytearray(16)
    entry[0] = 0x00
    entry[1:4] = b'\xff\xff\xff'
    entry[4] = partition_type
    entry[5:8] = b'\xff\xff\xff'
    _write_u32_le(entry, 8, start_lba)
    _write_u32_le(entry, 12, sector_count)
    return bytes(entry)


def _crc32_zeros(initial_crc: int, size: int, *, chunk_size: int = 4096) -> int:
    crc = initial_crc
    zero_chunk = b'\x00' * chunk_size
    remaining = size
    while remaining > 0:
        current = chunk_size if remaining > chunk_size else remaining
        crc = zlib.crc32(zero_chunk[:current], crc)
        remaining -= current
    return crc & 0xFFFFFFFF


def _compute_kernel_image_checksums(kernel_elf_bytes: bytes) -> Little64SDCardBootChecksums:
    kernel_image = flatten_little64_linux_elf_image(kernel_elf_bytes)
    return Little64SDCardBootChecksums(
        kernel_image_crc32=zlib.crc32(kernel_image.image) & 0xFFFFFFFF,
        kernel_image_size=len(kernel_image.image),
        dtb_crc32=0,
        dtb_size=0,
    )


def _build_sd_boot_checksums(*, kernel_elf_bytes: bytes, dtb_bytes: bytes) -> Little64SDCardBootChecksums:
    kernel_checksums = _compute_kernel_image_checksums(kernel_elf_bytes)
    return Little64SDCardBootChecksums(
        kernel_image_crc32=kernel_checksums.kernel_image_crc32,
        kernel_image_size=kernel_checksums.kernel_image_size,
        dtb_crc32=zlib.crc32(dtb_bytes) & 0xFFFFFFFF,
        dtb_size=len(dtb_bytes),
    )


def _serialize_sd_boot_checksums(checksums: Little64SDCardBootChecksums) -> bytes:
    return BOOT_CHECKSUM_STRUCT.pack(
        BOOT_CHECKSUM_MAGIC,
        BOOT_CHECKSUM_VERSION,
        checksums.kernel_image_crc32,
        checksums.kernel_image_size,
        checksums.dtb_crc32,
        checksums.dtb_size,
        0,
        0,
    )


def _root_partition_sectors_for_disk(*, total_disk_size_bytes: int, boot_partition_lba: int, boot_partition_sector_count: int) -> int:
    if total_disk_size_bytes % SECTOR_SIZE != 0:
        raise ValueError('total_disk_size_bytes must be sector-aligned')
    total_disk_sectors = total_disk_size_bytes // SECTOR_SIZE
    root_partition_lba = boot_partition_lba + boot_partition_sector_count
    root_partition_sector_count = total_disk_sectors - root_partition_lba
    if root_partition_sector_count <= 0:
        raise ValueError('disk image is too small for the requested partition layout')
    return root_partition_sector_count


def _fat_size_sectors(total_sectors: int, *, reserved_sectors: int, num_fats: int, sectors_per_cluster: int) -> tuple[int, int]:
    fat_sectors = 1
    while True:
        data_sectors = total_sectors - reserved_sectors - num_fats * fat_sectors
        cluster_count = data_sectors // sectors_per_cluster
        required = _ceil_div((cluster_count + 2) * 4, SECTOR_SIZE)
        if required <= fat_sectors:
            return fat_sectors, cluster_count
        fat_sectors = required


def _build_fat32_boot_partition(
    *,
    kernel_elf_bytes: bytes,
    dtb_bytes: bytes,
    boot_partition_lba: int,
    boot_partition_sector_count: int,
    sectors_per_cluster: int,
    volume_label: bytes,
) -> tuple[
    bytearray,
    Little64SDCardFileLayout,
    Little64SDCardFileLayout,
    Little64SDCardFileLayout,
    Little64SDCardBootChecksums,
]:
    if sectors_per_cluster < 1:
        raise ValueError('sectors_per_cluster must be positive')
    if len(volume_label) != 11:
        raise ValueError('volume_label must be exactly 11 bytes')

    kernel_name = _fat32_short_name('VMLINUX')
    dtb_name = _fat32_short_name('BOOT.DTB')
    checksums_name = _fat32_short_name('BOOT.CRC')
    checksums = _build_sd_boot_checksums(kernel_elf_bytes=kernel_elf_bytes, dtb_bytes=dtb_bytes)
    checksums_bytes = _serialize_sd_boot_checksums(checksums)

    reserved_sectors = 32
    num_fats = 2
    fat_sectors, cluster_count = _fat_size_sectors(
        boot_partition_sector_count,
        reserved_sectors=reserved_sectors,
        num_fats=num_fats,
        sectors_per_cluster=sectors_per_cluster,
    )
    if cluster_count < 65525:
        raise ValueError('boot partition is too small for a FAT32 volume')

    cluster_size = sectors_per_cluster * SECTOR_SIZE
    root_dir_cluster = 2
    kernel_clusters = max(1, _ceil_div(len(kernel_elf_bytes), cluster_size))
    dtb_clusters = max(1, _ceil_div(len(dtb_bytes), cluster_size))
    checksums_clusters = max(1, _ceil_div(len(checksums_bytes), cluster_size))
    used_cluster_count = 1 + kernel_clusters + dtb_clusters + checksums_clusters
    if used_cluster_count + 2 > cluster_count:
        raise ValueError('kernel and DTB do not fit in the FAT32 boot partition')

    first_fat_sector = reserved_sectors
    first_data_sector = reserved_sectors + num_fats * fat_sectors

    kernel_first_cluster = root_dir_cluster + 1
    dtb_first_cluster = kernel_first_cluster + kernel_clusters
    checksums_first_cluster = dtb_first_cluster + dtb_clusters

    fat_entries = [0 for _ in range(cluster_count + 2)]
    fat_entries[0] = 0x0FFFFFF8
    fat_entries[1] = 0xFFFFFFFF
    fat_entries[root_dir_cluster] = 0x0FFFFFFF

    for index in range(kernel_clusters):
        cluster = kernel_first_cluster + index
        fat_entries[cluster] = 0x0FFFFFFF if index == kernel_clusters - 1 else cluster + 1
    for index in range(dtb_clusters):
        cluster = dtb_first_cluster + index
        fat_entries[cluster] = 0x0FFFFFFF if index == dtb_clusters - 1 else cluster + 1
    for index in range(checksums_clusters):
        cluster = checksums_first_cluster + index
        fat_entries[cluster] = 0x0FFFFFFF if index == checksums_clusters - 1 else cluster + 1

    fat_bytes = bytearray(fat_sectors * SECTOR_SIZE)
    for index, value in enumerate(fat_entries):
        _write_u32_le(fat_bytes, index * 4, value)

    partition = bytearray(boot_partition_sector_count * SECTOR_SIZE)
    partition_view = memoryview(partition)
    boot_sector = partition_view[0:SECTOR_SIZE]
    boot_sector[0:3] = b'\xebX\x90'
    boot_sector[3:11] = b'L64FAT32'
    _write_u16_le(boot_sector, 11, SECTOR_SIZE)
    boot_sector[13] = sectors_per_cluster
    _write_u16_le(boot_sector, 14, reserved_sectors)
    boot_sector[16] = num_fats
    _write_u16_le(boot_sector, 17, 0)
    _write_u16_le(boot_sector, 19, 0)
    boot_sector[21] = 0xF8
    _write_u16_le(boot_sector, 22, 0)
    _write_u16_le(boot_sector, 24, 63)
    _write_u16_le(boot_sector, 26, 255)
    _write_u32_le(boot_sector, 28, boot_partition_lba)
    _write_u32_le(boot_sector, 32, boot_partition_sector_count)
    _write_u32_le(boot_sector, 36, fat_sectors)
    _write_u16_le(boot_sector, 40, 0)
    _write_u16_le(boot_sector, 42, 0)
    _write_u32_le(boot_sector, 44, root_dir_cluster)
    _write_u16_le(boot_sector, 48, 1)
    _write_u16_le(boot_sector, 50, 6)
    boot_sector[64] = 0x80
    boot_sector[66] = 0x29
    _write_u32_le(boot_sector, 67, 0x4C363444)
    boot_sector[71:82] = volume_label
    boot_sector[82:90] = b'FAT32   '
    boot_sector[510:512] = b'\x55\xaa'

    fsinfo = partition_view[SECTOR_SIZE:2 * SECTOR_SIZE]
    fsinfo[0:4] = b'RRaA'
    fsinfo[484:488] = b'rrAa'
    _write_u32_le(fsinfo, 488, cluster_count - used_cluster_count)
    _write_u32_le(fsinfo, 492, dtb_first_cluster + dtb_clusters)
    fsinfo[510:512] = b'\x55\xaa'

    backup_boot_sector_offset = 6 * SECTOR_SIZE
    partition[backup_boot_sector_offset:backup_boot_sector_offset + SECTOR_SIZE] = boot_sector
    partition[(6 + 1) * SECTOR_SIZE:(6 + 2) * SECTOR_SIZE] = fsinfo

    for fat_index in range(num_fats):
        fat_offset = (first_fat_sector + fat_index * fat_sectors) * SECTOR_SIZE
        partition[fat_offset:fat_offset + len(fat_bytes)] = fat_bytes

    root_dir_offset = first_data_sector * SECTOR_SIZE
    root_dir = partition_view[root_dir_offset:root_dir_offset + cluster_size]

    def write_dir_entry(entry_index: int, short_name: bytes, first_cluster: int, size: int) -> None:
        entry = bytearray(32)
        entry[0:11] = short_name
        entry[11] = 0x20
        _write_u16_le(entry, 20, (first_cluster >> 16) & 0xFFFF)
        _write_u16_le(entry, 26, first_cluster & 0xFFFF)
        _write_u32_le(entry, 28, size)
        start = entry_index * 32
        root_dir[start:start + 32] = entry

    kernel_file = Little64SDCardFileLayout(
        short_name=kernel_name,
        first_cluster=kernel_first_cluster,
        size=len(kernel_elf_bytes),
    )
    dtb_file = Little64SDCardFileLayout(
        short_name=dtb_name,
        first_cluster=dtb_first_cluster,
        size=len(dtb_bytes),
    )
    checksums_file = Little64SDCardFileLayout(
        short_name=checksums_name,
        first_cluster=checksums_first_cluster,
        size=len(checksums_bytes),
    )

    write_dir_entry(0, kernel_file.short_name, kernel_file.first_cluster, kernel_file.size)
    write_dir_entry(1, dtb_file.short_name, dtb_file.first_cluster, dtb_file.size)
    write_dir_entry(2, checksums_file.short_name, checksums_file.first_cluster, checksums_file.size)
    root_dir[96] = 0x00

    def write_file(first_cluster: int, payload: bytes) -> None:
        payload_view = memoryview(payload)
        payload_offset = 0
        payload_size = len(payload_view)
        cluster = first_cluster
        while payload_offset < payload_size:
            sector = first_data_sector + (cluster - 2) * sectors_per_cluster
            offset = sector * SECTOR_SIZE
            chunk_size = min(cluster_size, payload_size - payload_offset)
            partition[offset:offset + chunk_size] = payload_view[payload_offset:payload_offset + chunk_size]
            payload_offset += chunk_size
            if payload_offset >= payload_size:
                break
            cluster = fat_entries[cluster]
            if cluster >= 0x0FFFFFF8:
                raise ValueError('unexpected end of FAT cluster chain while writing file')

    write_file(kernel_file.first_cluster, kernel_elf_bytes)
    write_file(dtb_file.first_cluster, dtb_bytes)
    write_file(checksums_file.first_cluster, checksums_bytes)

    return partition, kernel_file, dtb_file, checksums_file, checksums


def _compose_sd_card_image(
    *,
    boot_partition: bytes,
    rootfs_payload: bytes,
    boot_partition_lba: int,
    boot_partition_sector_count: int,
    root_partition_sector_count: int,
    kernel_file: Little64SDCardFileLayout,
    dtb_file: Little64SDCardFileLayout,
    checksums_file: Little64SDCardFileLayout,
    checksums: Little64SDCardBootChecksums,
    include_disk_image: bool,
) -> tuple[Little64SDCardImageLayout, bytes, int]:
    root_partition_lba = boot_partition_lba + boot_partition_sector_count
    total_disk_sectors = root_partition_lba + root_partition_sector_count
    disk_size_bytes = total_disk_sectors * SECTOR_SIZE

    mbr = bytearray(SECTOR_SIZE)
    mbr[446:462] = _partition_entry(boot_partition_lba, boot_partition_sector_count, 0x0C)
    mbr[462:478] = _partition_entry(root_partition_lba, root_partition_sector_count, 0x83)
    mbr[510:512] = b'\x55\xaa'

    disk_image = None
    if include_disk_image:
        disk_image = bytearray(disk_size_bytes)
        disk_image[0:SECTOR_SIZE] = mbr
        boot_partition_offset = boot_partition_lba * SECTOR_SIZE
        disk_image[boot_partition_offset:boot_partition_offset + len(boot_partition)] = boot_partition
        if rootfs_payload:
            root_partition_offset = root_partition_lba * SECTOR_SIZE
            disk_image[root_partition_offset:root_partition_offset + len(rootfs_payload)] = rootfs_payload

    return (
        Little64SDCardImageLayout(
            disk_image=None if disk_image is None else bytes(disk_image),
            disk_size_bytes=disk_size_bytes,
            boot_partition_lba=boot_partition_lba,
            boot_partition_sector_count=boot_partition_sector_count,
            root_partition_lba=root_partition_lba,
            root_partition_sector_count=root_partition_sector_count,
            kernel_file=kernel_file,
            dtb_file=dtb_file,
            checksums_file=checksums_file,
            checksums=checksums,
        ),
        bytes(mbr),
        root_partition_lba * SECTOR_SIZE,
    )


def build_litex_sd_card_image(
    *,
    kernel_elf_bytes: bytes,
    dtb_bytes: bytes,
    rootfs_bytes: bytes | None = None,
    boot_partition_lba: int = 2048,
    boot_partition_size_mb: int = 64,
    root_partition_size_mb: int = 16,
    sectors_per_cluster: int = 1,
    volume_label: bytes = b'L64BOOT    ',
) -> Little64SDCardImageLayout:
    rootfs_payload = rootfs_bytes or b''

    boot_partition_sector_count = max(
        boot_partition_size_mb * 1024 * 1024 // SECTOR_SIZE,
        65536,
    )
    root_partition_sector_count = max(
        _ceil_div(len(rootfs_payload), SECTOR_SIZE),
        root_partition_size_mb * 1024 * 1024 // SECTOR_SIZE,
    )
    if _ceil_div(len(rootfs_payload), SECTOR_SIZE) > root_partition_sector_count:
        raise ValueError('rootfs payload does not fit in the configured root partition')

    boot_partition, kernel_file, dtb_file, checksums_file, checksums = _build_fat32_boot_partition(
        kernel_elf_bytes=kernel_elf_bytes,
        dtb_bytes=dtb_bytes,
        boot_partition_lba=boot_partition_lba,
        boot_partition_sector_count=boot_partition_sector_count,
        sectors_per_cluster=sectors_per_cluster,
        volume_label=volume_label,
    )
    layout, _, _ = _compose_sd_card_image(
        boot_partition=boot_partition,
        rootfs_payload=rootfs_payload,
        boot_partition_lba=boot_partition_lba,
        boot_partition_sector_count=boot_partition_sector_count,
        root_partition_sector_count=root_partition_sector_count,
        kernel_file=kernel_file,
        dtb_file=dtb_file,
        checksums_file=checksums_file,
        checksums=checksums,
        include_disk_image=True,
    )
    return layout


def write_litex_sd_card_image(
    output_path: Path,
    *,
    kernel_elf_bytes: bytes,
    dtb_bytes: bytes,
    rootfs_bytes: bytes | None = None,
    total_disk_size_bytes: int = DEFAULT_SD_CARD_SIZE_BYTES,
    boot_partition_lba: int = 2048,
    boot_partition_size_mb: int = DEFAULT_SD_BOOT_PARTITION_SIZE_MB,
    sectors_per_cluster: int = 1,
    volume_label: bytes = b'L64BOOT    ',
) -> Little64SDCardImageLayout:
    rootfs_payload = rootfs_bytes or b''
    boot_partition_sector_count = max(
        boot_partition_size_mb * 1024 * 1024 // SECTOR_SIZE,
        65536,
    )
    root_partition_sector_count = _root_partition_sectors_for_disk(
        total_disk_size_bytes=total_disk_size_bytes,
        boot_partition_lba=boot_partition_lba,
        boot_partition_sector_count=boot_partition_sector_count,
    )
    if _ceil_div(len(rootfs_payload), SECTOR_SIZE) > root_partition_sector_count:
        raise ValueError('rootfs payload does not fit in the configured root partition')

    boot_partition, kernel_file, dtb_file, checksums_file, checksums = _build_fat32_boot_partition(
        kernel_elf_bytes=kernel_elf_bytes,
        dtb_bytes=dtb_bytes,
        boot_partition_lba=boot_partition_lba,
        boot_partition_sector_count=boot_partition_sector_count,
        sectors_per_cluster=sectors_per_cluster,
        volume_label=volume_label,
    )
    layout, mbr, root_partition_offset = _compose_sd_card_image(
        boot_partition=boot_partition,
        rootfs_payload=rootfs_payload,
        boot_partition_lba=boot_partition_lba,
        boot_partition_sector_count=boot_partition_sector_count,
        root_partition_sector_count=root_partition_sector_count,
        kernel_file=kernel_file,
        dtb_file=dtb_file,
        checksums_file=checksums_file,
        checksums=checksums,
        include_disk_image=False,
    )

    boot_partition_offset = boot_partition_lba * SECTOR_SIZE
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open('wb') as handle:
        handle.truncate(total_disk_size_bytes)
        handle.seek(0)
        handle.write(mbr)
        handle.seek(boot_partition_offset)
        handle.write(boot_partition)
        if rootfs_payload:
            handle.seek(root_partition_offset)
            handle.write(rootfs_payload)

    return layout


def flatten_little64_linux_elf_image(
    elf_bytes: bytes,
    *,
    kernel_physical_base: int = LITTLE64_LINUX_RAM_BASE,
) -> Little64LinuxElfImage:
    if len(elf_bytes) < 64:
        raise ValueError('ELF image is too small')

    ident = elf_bytes[:16]
    if ident[:4] != b'\x7fELF':
        raise ValueError('ELF image is missing the ELF magic')
    if ident[4] != 2 or ident[5] != 1:
        raise ValueError('ELF image must be ELF64 little-endian')

    (
        _,
        _,
        machine,
        _,
        entry,
        phoff,
        _,
        _,
        _,
        phentsize,
        phnum,
        _,
        _,
        _,
    ) = struct.unpack_from('<16sHHIQQQIHHHHHH', elf_bytes, 0)
    if machine != EM_LITTLE64:
        raise ValueError(f'ELF machine does not match Little64: 0x{machine:x}')
    if phoff + phnum * phentsize > len(elf_bytes):
        raise ValueError('ELF program headers extend beyond the file')

    load_segments: list[tuple[int, int, int, int]] = []
    min_vaddr = None
    max_vaddr = 0
    for index in range(phnum):
        p_type, _, p_offset, p_vaddr, _, p_filesz, p_memsz, _ = struct.unpack_from(
            '<IIQQQQQQ',
            elf_bytes,
            phoff + index * phentsize,
        )
        if p_type != PT_LOAD:
            continue
        if p_offset + p_filesz > len(elf_bytes):
            raise ValueError('ELF PT_LOAD segment extends beyond the file')
        min_vaddr = p_vaddr if min_vaddr is None else min(min_vaddr, p_vaddr)
        max_vaddr = max(max_vaddr, p_vaddr + p_memsz)
        load_segments.append((p_offset, p_vaddr, p_filesz, p_memsz))

    if not load_segments or min_vaddr is None:
        raise ValueError('ELF image does not contain any PT_LOAD segments')

    virtual_base = (min_vaddr // PAGE_SIZE) * PAGE_SIZE
    image_span = _align_up(max_vaddr - virtual_base, PAGE_SIZE)
    image = bytearray(image_span)

    for segment_offset, segment_vaddr, segment_filesz, _ in load_segments:
        image_offset = segment_vaddr - virtual_base
        image[image_offset:image_offset + segment_filesz] = elf_bytes[segment_offset:segment_offset + segment_filesz]

    virtual_end = virtual_base + image_span
    if virtual_base <= entry < virtual_end:
        entry_physical = kernel_physical_base + (entry - virtual_base)
    elif kernel_physical_base <= entry < kernel_physical_base + image_span:
        entry_physical = entry
    else:
        raise ValueError('ELF entry point is outside the loadable image window')

    return Little64LinuxElfImage(
        image=bytes(image),
        image_span=image_span,
        virtual_base=virtual_base,
        entry_physical=entry_physical,
    )


def build_litex_flash_image(
    *,
    stage0_bytes: bytes,
    kernel_elf_bytes: bytes,
    dtb_bytes: bytes,
    ram_base: int = LITTLE64_LINUX_RAM_BASE,
    ram_size: int = 0x0400_0000,
    kernel_physical_base: int = LITTLE64_LINUX_RAM_BASE,
    header_offset: int = LITTLE64_LITEX_FLASH_BOOT_HEADER_OFFSET,
    early_pt_scratch_pages: int = EARLY_PT_SCRATCH_PAGES,
) -> Little64FlashImageLayout:
    if len(stage0_bytes) > header_offset:
        raise ValueError('Stage-0 image is larger than the reserved flash boot gap')

    kernel_image = flatten_little64_linux_elf_image(
        kernel_elf_bytes,
        kernel_physical_base=kernel_physical_base,
    )

    boot_stack_top = ram_base + ram_size - 8
    dtb_physical = kernel_physical_base + _align_up(
        kernel_image.image_span + early_pt_scratch_pages * PAGE_SIZE,
        PAGE_SIZE,
    )
    kernel_end = kernel_physical_base + kernel_image.image_span
    dtb_end = dtb_physical + len(dtb_bytes)
    ram_end = ram_base + ram_size
    if kernel_physical_base < ram_base or kernel_end > ram_end or dtb_end > ram_end:
        raise ValueError('Kernel image or DTB does not fit inside the configured RAM window')

    kernel_flash_offset = _align_up(header_offset + FLASH_BOOT_HEADER.size, PAGE_SIZE)
    dtb_flash_offset = _align_up(kernel_flash_offset + len(kernel_image.image), PAGE_SIZE)
    flash_image_size = dtb_flash_offset + len(dtb_bytes)

    flash_image = bytearray(flash_image_size)
    flash_image[:len(stage0_bytes)] = stage0_bytes
    flash_image[header_offset:header_offset + FLASH_BOOT_HEADER.size] = FLASH_BOOT_HEADER.pack(
        LITTLE64_LITEX_FLASH_BOOT_MAGIC,
        LITTLE64_LITEX_FLASH_BOOT_ABI_VERSION,
        kernel_flash_offset,
        len(kernel_image.image),
        kernel_physical_base,
        kernel_image.entry_physical,
        dtb_flash_offset,
        len(dtb_bytes),
        dtb_physical,
        boot_stack_top,
        flash_image_size,
        0,
        0,
        0,
        0,
        0,
    )
    flash_image[kernel_flash_offset:kernel_flash_offset + len(kernel_image.image)] = kernel_image.image
    flash_image[dtb_flash_offset:dtb_flash_offset + len(dtb_bytes)] = dtb_bytes

    return Little64FlashImageLayout(
        flash_image=bytes(flash_image),
        kernel_flash_offset=kernel_flash_offset,
        dtb_flash_offset=dtb_flash_offset,
        kernel_physical_base=kernel_physical_base,
        kernel_entry_physical=kernel_image.entry_physical,
        dtb_physical_address=dtb_physical,
        kernel_boot_stack_top=boot_stack_top,
    )