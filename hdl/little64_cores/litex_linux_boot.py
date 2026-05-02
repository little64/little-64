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
LITTLE64_SD_BOOT_FORMAT_STAGE0 = 'stage0'
LITTLE64_SD_BOOT_FORMAT_LITEX_BIOS = 'litex-bios'
LITTLE64_SD_BOOT_FORMATS = (
    LITTLE64_SD_BOOT_FORMAT_STAGE0,
    LITTLE64_SD_BOOT_FORMAT_LITEX_BIOS,
)


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
    boot_format: str
    kernel_file: Little64SDCardFileLayout
    dtb_file: Little64SDCardFileLayout
    checksums_file: Little64SDCardFileLayout | None
    boot_json_file: Little64SDCardFileLayout | None
    checksums: Little64SDCardBootChecksums | None
    kernel_entry_physical: int | None = None
    dtb_physical_address: int | None = None


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


def _fat32_short_name_text(short_name: bytes) -> str:
    if len(short_name) != 11:
        raise ValueError('FAT32 short names must be exactly 11 bytes')
    stem = short_name[:8].decode('ascii').rstrip()
    extension = short_name[8:11].decode('ascii').rstrip()
    return stem if not extension else f'{stem}.{extension}'


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


def _fat32_lfn_checksum(short_name: bytes) -> int:
    checksum = 0
    for value in short_name:
        checksum = (((checksum & 1) << 7) + (checksum >> 1) + value) & 0xFF
    return checksum


def _build_fat32_lfn_entries(long_name: str, short_name: bytes) -> list[bytes]:
    if not long_name:
        raise ValueError('long_name must not be empty')
    utf16_units = [ord(character) for character in long_name]
    if any(unit > 0xFFFF for unit in utf16_units):
        raise ValueError('FAT32 LFN builder only supports BMP characters')
    utf16_units.append(0x0000)
    while len(utf16_units) % 13 != 0:
        utf16_units.append(0xFFFF)

    chunks = [utf16_units[index:index + 13] for index in range(0, len(utf16_units), 13)]
    checksum = _fat32_lfn_checksum(short_name)
    entries: list[bytes] = []
    for reverse_index, chunk in enumerate(reversed(chunks)):
        sequence = len(chunks) - reverse_index
        if reverse_index == 0:
            sequence |= 0x40

        entry = bytearray(32)
        entry[0] = sequence
        entry[11] = 0x0F
        entry[12] = 0x00
        entry[13] = checksum

        positions = (
            (1, 5),
            (14, 6),
            (28, 2),
        )
        chunk_index = 0
        for offset, count in positions:
            for _ in range(count):
                unit = chunk[chunk_index]
                entry[offset:offset + 2] = struct.pack('<H', unit)
                offset += 2
                chunk_index += 1

        entries.append(bytes(entry))
    return entries


def _build_fat32_file_dir_entry(file_layout: Little64SDCardFileLayout) -> bytes:
    entry = bytearray(32)
    entry[0:11] = file_layout.short_name
    entry[11] = 0x20
    _write_u16_le(entry, 20, (file_layout.first_cluster >> 16) & 0xFFFF)
    _write_u16_le(entry, 26, file_layout.first_cluster & 0xFFFF)
    _write_u32_le(entry, 28, file_layout.size)
    return bytes(entry)


def _build_litex_bios_boot_json(
    *,
    kernel_name: str,
    dtb_name: str,
    kernel_physical_base: int,
    dtb_physical_address: int,
    kernel_entry_physical: int,
    kernel_boot_stack_top: int,
) -> bytes:
    return (
        '{\n'
        f'  "{kernel_name}": "0x{kernel_physical_base:x}",\n'
        f'  "{dtb_name}": "0x{dtb_physical_address:x}",\n'
        f'  "r1": "0x{dtb_physical_address:x}",\n'
        f'  "r2": "0x{kernel_boot_stack_top:x}",\n'
        f'  "addr": "0x{kernel_entry_physical:x}"\n'
        '}\n'
    ).encode('ascii')


def _parse_little64_elf_load_segments(
    elf_bytes: bytes,
) -> tuple[memoryview, int, list[tuple[int, int, int, int]], int, int]:
    if len(elf_bytes) < 64:
        raise ValueError('ELF image is too small')

    elf_view = memoryview(elf_bytes)

    if bytes(elf_view[:4]) != b'\x7fELF':
        raise ValueError('ELF image is missing the ELF magic')
    if elf_view[4] != 2 or elf_view[5] != 1:
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
    ) = struct.unpack_from('<16sHHIQQQIHHHHHH', elf_view, 0)
    if machine != EM_LITTLE64:
        raise ValueError(f'ELF machine does not match Little64: 0x{machine:x}')
    if phoff + phnum * phentsize > len(elf_view):
        raise ValueError('ELF program headers extend beyond the file')

    load_segments: list[tuple[int, int, int, int]] = []
    min_vaddr = None
    max_vaddr = 0
    for index in range(phnum):
        p_type, _, p_offset, p_vaddr, _, p_filesz, p_memsz, _ = struct.unpack_from(
            '<IIQQQQQQ',
            elf_view,
            phoff + index * phentsize,
        )
        if p_type != PT_LOAD:
            continue
        if p_offset + p_filesz > len(elf_view):
            raise ValueError('ELF PT_LOAD segment extends beyond the file')
        min_vaddr = p_vaddr if min_vaddr is None else min(min_vaddr, p_vaddr)
        max_vaddr = max(max_vaddr, p_vaddr + p_memsz)
        load_segments.append((p_offset, p_vaddr, p_filesz, p_memsz))

    if not load_segments or min_vaddr is None:
        raise ValueError('ELF image does not contain any PT_LOAD segments')

    return elf_view, entry, load_segments, min_vaddr, max_vaddr


def infer_little64_linux_kernel_physical_base(
    elf_bytes: bytes,
    *,
    ram_base: int = LITTLE64_LINUX_RAM_BASE,
    ram_size: int = 0x0400_0000,
    default_kernel_physical_base: int = LITTLE64_LINUX_RAM_BASE,
) -> tuple[int, bool]:
    _elf_view, _entry, _load_segments, min_vaddr, max_vaddr = _parse_little64_elf_load_segments(elf_bytes)
    virtual_base = (min_vaddr // PAGE_SIZE) * PAGE_SIZE
    image_span = _align_up(max_vaddr - virtual_base, PAGE_SIZE)
    ram_end = ram_base + ram_size
    preserves_input_load_address = ram_base <= virtual_base and virtual_base + image_span <= ram_end
    if preserves_input_load_address:
        return virtual_base, True
    return default_kernel_physical_base, False


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
    boot_format: str = LITTLE64_SD_BOOT_FORMAT_STAGE0,
    ram_base: int = LITTLE64_LINUX_RAM_BASE,
    ram_size: int = 0x0400_0000,
    kernel_physical_base: int = LITTLE64_LINUX_RAM_BASE,
) -> tuple[
    bytearray,
    Little64SDCardFileLayout,
    Little64SDCardFileLayout,
    Little64SDCardFileLayout | None,
    Little64SDCardFileLayout | None,
    Little64SDCardBootChecksums | None,
    int | None,
    int | None,
]:
    if sectors_per_cluster < 1:
        raise ValueError('sectors_per_cluster must be positive')
    if len(volume_label) != 11:
        raise ValueError('volume_label must be exactly 11 bytes')

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

    file_payloads: list[tuple[bytes, bytes, str | None]]
    checksums_file: Little64SDCardFileLayout | None = None
    boot_json_file: Little64SDCardFileLayout | None = None
    checksums: Little64SDCardBootChecksums | None = None
    kernel_entry_physical: int | None = None
    dtb_physical_address: int | None = None

    if boot_format == LITTLE64_SD_BOOT_FORMAT_STAGE0:
        kernel_name = _fat32_short_name('VMLINUX')
        dtb_name = _fat32_short_name('BOOT.DTB')
        checksums_name = _fat32_short_name('BOOT.CRC')
        checksums = _build_sd_boot_checksums(kernel_elf_bytes=kernel_elf_bytes, dtb_bytes=dtb_bytes)
        checksums_bytes = _serialize_sd_boot_checksums(checksums)
        file_payloads = [
            (kernel_name, kernel_elf_bytes, None),
            (dtb_name, dtb_bytes, None),
            (checksums_name, checksums_bytes, None),
        ]
    elif boot_format == LITTLE64_SD_BOOT_FORMAT_LITEX_BIOS:
        effective_kernel_physical_base, preserves_input_load_address = infer_little64_linux_kernel_physical_base(
            kernel_elf_bytes,
            ram_base=ram_base,
            ram_size=ram_size,
            default_kernel_physical_base=kernel_physical_base,
        )
        kernel_image = flatten_little64_linux_elf_image(
            kernel_elf_bytes,
            kernel_physical_base=effective_kernel_physical_base,
        )
        ram_end = ram_base + ram_size
        boot_stack_top = ram_end - 8
        dtb_physical_address = effective_kernel_physical_base + _align_up(
            kernel_image.image_span + EARLY_PT_SCRATCH_PAGES * PAGE_SIZE,
            PAGE_SIZE,
        )
        kernel_end = effective_kernel_physical_base + kernel_image.image_span
        dtb_end = dtb_physical_address + len(dtb_bytes)
        if effective_kernel_physical_base < ram_base or kernel_end > ram_end or dtb_end > ram_end:
            raise ValueError('kernel image or DTB does not fit inside the configured RAM window')
        if boot_stack_top <= dtb_end:
            raise ValueError('kernel boot stack overlaps the BIOS DTB placement window')

        kernel_name = _fat32_short_name('BOOT.BIN')
        dtb_name = _fat32_short_name('BOOT.DTB')
        boot_json_name = _fat32_short_name('BOOTJSN.JSN')
        kernel_entry_physical = kernel_image.entry_physical
        boot_json_bytes = _build_litex_bios_boot_json(
            kernel_name='boot.bin',
            dtb_name='boot.dtb',
            kernel_physical_base=effective_kernel_physical_base,
            dtb_physical_address=dtb_physical_address,
            kernel_entry_physical=kernel_entry_physical,
            kernel_boot_stack_top=boot_stack_top,
        )
        file_payloads = [
            (kernel_name, kernel_image.image, 'boot.bin'),
            (dtb_name, dtb_bytes, 'boot.dtb'),
            (boot_json_name, boot_json_bytes, 'boot.json'),
        ]
    else:
        raise ValueError(f'Unsupported SD boot format: {boot_format}')

    file_specs: list[tuple[Little64SDCardFileLayout, bytes, str | None, int]] = []
    next_cluster = root_dir_cluster + 1
    for short_name, payload, long_name in file_payloads:
        clusters = max(1, _ceil_div(len(payload), cluster_size))
        layout = Little64SDCardFileLayout(
            short_name=short_name,
            first_cluster=next_cluster,
            size=len(payload),
        )
        file_specs.append((layout, payload, long_name, clusters))
        next_cluster += clusters

    kernel_file = file_specs[0][0]
    dtb_file = file_specs[1][0]
    if boot_format == LITTLE64_SD_BOOT_FORMAT_STAGE0:
        checksums_file = file_specs[2][0]
    else:
        boot_json_file = file_specs[2][0]

    used_cluster_count = 1 + sum(clusters for _, _, _, clusters in file_specs)
    if used_cluster_count + 2 > cluster_count:
        raise ValueError('boot files do not fit in the FAT32 boot partition')

    first_fat_sector = reserved_sectors
    first_data_sector = reserved_sectors + num_fats * fat_sectors

    fat_entries = [0 for _ in range(cluster_count + 2)]
    fat_entries[0] = 0x0FFFFFF8
    fat_entries[1] = 0xFFFFFFFF
    fat_entries[root_dir_cluster] = 0x0FFFFFFF
    for file_layout, _payload, _long_name, cluster_count_for_file in file_specs:
        for index in range(cluster_count_for_file):
            cluster = file_layout.first_cluster + index
            fat_entries[cluster] = 0x0FFFFFFF if index == cluster_count_for_file - 1 else cluster + 1

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
    _write_u32_le(fsinfo, 492, next_cluster)
    fsinfo[510:512] = b'\x55\xaa'

    backup_boot_sector_offset = 6 * SECTOR_SIZE
    partition[backup_boot_sector_offset:backup_boot_sector_offset + SECTOR_SIZE] = boot_sector
    partition[(6 + 1) * SECTOR_SIZE:(6 + 2) * SECTOR_SIZE] = fsinfo

    for fat_index in range(num_fats):
        fat_offset = (first_fat_sector + fat_index * fat_sectors) * SECTOR_SIZE
        partition[fat_offset:fat_offset + len(fat_bytes)] = fat_bytes

    root_dir_offset = first_data_sector * SECTOR_SIZE
    root_dir = partition_view[root_dir_offset:root_dir_offset + cluster_size]

    dir_offset = 0
    for file_layout, _payload, long_name, _clusters in file_specs:
        if long_name is not None:
            for lfn_entry in _build_fat32_lfn_entries(long_name, file_layout.short_name):
                root_dir[dir_offset:dir_offset + 32] = lfn_entry
                dir_offset += 32
        root_dir[dir_offset:dir_offset + 32] = _build_fat32_file_dir_entry(file_layout)
        dir_offset += 32
    root_dir[dir_offset] = 0x00

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

    for file_layout, payload, _long_name, _clusters in file_specs:
        write_file(file_layout.first_cluster, payload)

    return (
        partition,
        kernel_file,
        dtb_file,
        checksums_file,
        boot_json_file,
        checksums,
        kernel_entry_physical,
        dtb_physical_address,
    )


def _compose_sd_card_image(
    *,
    boot_partition: bytes,
    rootfs_payload: bytes,
    boot_partition_lba: int,
    boot_partition_sector_count: int,
    root_partition_sector_count: int,
    boot_format: str,
    kernel_file: Little64SDCardFileLayout,
    dtb_file: Little64SDCardFileLayout,
    checksums_file: Little64SDCardFileLayout | None,
    boot_json_file: Little64SDCardFileLayout | None,
    checksums: Little64SDCardBootChecksums | None,
    kernel_entry_physical: int | None,
    dtb_physical_address: int | None,
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
            boot_format=boot_format,
            kernel_file=kernel_file,
            dtb_file=dtb_file,
            checksums_file=checksums_file,
            boot_json_file=boot_json_file,
            checksums=checksums,
            kernel_entry_physical=kernel_entry_physical,
            dtb_physical_address=dtb_physical_address,
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
    boot_format: str = LITTLE64_SD_BOOT_FORMAT_STAGE0,
    ram_base: int = LITTLE64_LINUX_RAM_BASE,
    ram_size: int = 0x0400_0000,
    kernel_physical_base: int = LITTLE64_LINUX_RAM_BASE,
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

    boot_partition, kernel_file, dtb_file, checksums_file, boot_json_file, checksums, kernel_entry_physical, dtb_physical_address = _build_fat32_boot_partition(
        kernel_elf_bytes=kernel_elf_bytes,
        dtb_bytes=dtb_bytes,
        boot_partition_lba=boot_partition_lba,
        boot_partition_sector_count=boot_partition_sector_count,
        sectors_per_cluster=sectors_per_cluster,
        volume_label=volume_label,
        boot_format=boot_format,
        ram_base=ram_base,
        ram_size=ram_size,
        kernel_physical_base=kernel_physical_base,
    )
    layout, _, _ = _compose_sd_card_image(
        boot_partition=boot_partition,
        rootfs_payload=rootfs_payload,
        boot_partition_lba=boot_partition_lba,
        boot_partition_sector_count=boot_partition_sector_count,
        root_partition_sector_count=root_partition_sector_count,
        boot_format=boot_format,
        kernel_file=kernel_file,
        dtb_file=dtb_file,
        checksums_file=checksums_file,
        boot_json_file=boot_json_file,
        checksums=checksums,
        kernel_entry_physical=kernel_entry_physical,
        dtb_physical_address=dtb_physical_address,
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
    boot_format: str = LITTLE64_SD_BOOT_FORMAT_STAGE0,
    ram_base: int = LITTLE64_LINUX_RAM_BASE,
    ram_size: int = 0x0400_0000,
    kernel_physical_base: int = LITTLE64_LINUX_RAM_BASE,
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

    boot_partition, kernel_file, dtb_file, checksums_file, boot_json_file, checksums, kernel_entry_physical, dtb_physical_address = _build_fat32_boot_partition(
        kernel_elf_bytes=kernel_elf_bytes,
        dtb_bytes=dtb_bytes,
        boot_partition_lba=boot_partition_lba,
        boot_partition_sector_count=boot_partition_sector_count,
        sectors_per_cluster=sectors_per_cluster,
        volume_label=volume_label,
        boot_format=boot_format,
        ram_base=ram_base,
        ram_size=ram_size,
        kernel_physical_base=kernel_physical_base,
    )
    layout, mbr, root_partition_offset = _compose_sd_card_image(
        boot_partition=boot_partition,
        rootfs_payload=rootfs_payload,
        boot_partition_lba=boot_partition_lba,
        boot_partition_sector_count=boot_partition_sector_count,
        root_partition_sector_count=root_partition_sector_count,
        boot_format=boot_format,
        kernel_file=kernel_file,
        dtb_file=dtb_file,
        checksums_file=checksums_file,
        boot_json_file=boot_json_file,
        checksums=checksums,
        kernel_entry_physical=kernel_entry_physical,
        dtb_physical_address=dtb_physical_address,
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
    # Go through a memoryview so the caller's buffer is never copied for slicing.
    # This also lets read-only callers (e.g. SD-image checksum computation) keep
    # zero-copy semantics on large kernel payloads.
    elf_view, entry, load_segments, min_vaddr, max_vaddr = _parse_little64_elf_load_segments(elf_bytes)

    virtual_base = (min_vaddr // PAGE_SIZE) * PAGE_SIZE
    image_span = _align_up(max_vaddr - virtual_base, PAGE_SIZE)
    image = bytearray(image_span)

    for segment_offset, segment_vaddr, segment_filesz, _ in load_segments:
        image_offset = segment_vaddr - virtual_base
        image[image_offset:image_offset + segment_filesz] = elf_view[segment_offset:segment_offset + segment_filesz]

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