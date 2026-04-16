from __future__ import annotations

from dataclasses import dataclass
import struct

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


def _align_up(value: int, alignment: int) -> int:
    return (value + alignment - 1) & -alignment


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
    ram_base: int = 0,
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