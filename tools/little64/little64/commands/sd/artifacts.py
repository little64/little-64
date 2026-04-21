#!/usr/bin/env python3

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import litex
from litedram.init import get_sdram_phy_c_header
from litex.soc.integration import export as litex_export

from little64.build_support import Stage0CompileUnit, build_stage0_binary
from little64.paths import repo_root
from little64.tooling_support import build_default_rootfs_image


def _litex_software_root() -> Path:
    return Path(litex.__file__).resolve().parent / 'soc' / 'software'


def _repo_root() -> Path:
    return repo_root()


REPO_ROOT = _repo_root()
sys.path.insert(0, str(REPO_ROOT / 'hdl'))

from little64_cores.litex import LITTLE64_LINUX_RAM_BASE, LITTLE64_LITEX_BOOT_SOURCES, LITTLE64_LITEX_TARGET_NAMES
from little64_cores.litex import normalize_litex_boot_source, resolve_litex_target
from little64_cores.litex_linux_boot import (
    DEFAULT_SD_BOOT_PARTITION_SIZE_MB,
    DEFAULT_SD_CARD_SIZE_BYTES,
    write_litex_sd_card_image,
)
from little64_cores.litex_soc import Little64LiteXSimSoC, Little64LiteXSoC


LITEX_BOOTROM_SD_UART_BASE = 0xF0004000


STAGE0_SYSTEM_HEADER = """#ifndef __SYSTEM_H
#define __SYSTEM_H

#ifdef CONFIG_CPU_NOP
#undef CONFIG_CPU_NOP
#endif
#define CONFIG_CPU_NOP \"move R0, R0\"

#endif
"""


STAGE0_HW_COMMON_HEADER = """#ifndef __HW_COMMON_H
#define __HW_COMMON_H

#include <stdint.h>
#include <generated/soc.h>
#include <system.h>

#ifndef CSR_ACCESSORS_DEFINED
#define CSR_ACCESSORS_DEFINED

#define MMPTR(a) (*((volatile uint32_t *)(a)))

static inline void cdelay(int iterations) {
#ifndef CONFIG_BIOS_NO_DELAYS
    while (iterations > 0) {
        __asm__ volatile(CONFIG_CPU_NOP);
        --iterations;
    }
#endif
}

static inline void csr_write_simple(unsigned long value, unsigned long address) {
    MMPTR(address) = (uint32_t)value;
}

static inline unsigned long csr_read_simple(unsigned long address) {
    return MMPTR(address);
}

#endif

#define CSR_DW_BYTES     (CONFIG_CSR_DATA_WIDTH/8)
#define CSR_OFFSET_BYTES 4

static inline int num_subregs(int csr_bytes) {
    return (csr_bytes - 1) / CSR_DW_BYTES + 1;
}

static inline uint64_t _csr_rd(unsigned long address, int csr_bytes) {
    uint64_t value = csr_read_simple(address);
    for (int index = 1; index < num_subregs(csr_bytes); ++index) {
        value <<= CONFIG_CSR_DATA_WIDTH;
        address += CSR_OFFSET_BYTES;
        value |= csr_read_simple(address);
    }
    return value;
}

static inline void _csr_wr(unsigned long address, uint64_t value, int csr_bytes) {
    int subregs = num_subregs(csr_bytes);
    for (int index = 0; index < subregs; ++index) {
        csr_write_simple(value >> (CONFIG_CSR_DATA_WIDTH * (subregs - 1 - index)), address);
        address += CSR_OFFSET_BYTES;
    }
}

static inline uint8_t csr_rd_uint8(unsigned long address) {
    return (uint8_t)_csr_rd(address, sizeof(uint8_t));
}

static inline void csr_wr_uint8(uint8_t value, unsigned long address) {
    _csr_wr(address, value, sizeof(uint8_t));
}

static inline uint16_t csr_rd_uint16(unsigned long address) {
    return (uint16_t)_csr_rd(address, sizeof(uint16_t));
}

static inline void csr_wr_uint16(uint16_t value, unsigned long address) {
    _csr_wr(address, value, sizeof(uint16_t));
}

static inline uint32_t csr_rd_uint32(unsigned long address) {
    return (uint32_t)_csr_rd(address, sizeof(uint32_t));
}

static inline void csr_wr_uint32(uint32_t value, unsigned long address) {
    _csr_wr(address, value, sizeof(uint32_t));
}

static inline uint64_t csr_rd_uint64(unsigned long address) {
    return _csr_rd(address, sizeof(uint64_t));
}

static inline void csr_wr_uint64(uint64_t value, unsigned long address) {
    _csr_wr(address, value, sizeof(uint64_t));
}

#define _csr_rd_buf(address, buf, count) \
{ \
    int index, subindex, offset, subregs, subelems; \
    uint64_t value; \
    if (sizeof(buf[0]) >= CSR_DW_BYTES) { \
        for (index = 0; index < count; ++index) { \
            buf[index] = _csr_rd(address, sizeof(buf[0])); \
            address += CSR_OFFSET_BYTES * num_subregs(sizeof(buf[0])); \
        } \
    } else { \
        subregs = num_subregs(sizeof(buf[0]) * count); \
        subelems = CSR_DW_BYTES / sizeof(buf[0]); \
        offset = subregs * subelems - count; \
        for (index = 0; index < subregs; ++index) { \
            value = csr_read_simple(address); \
            for (subindex = subelems - 1; subindex >= 0; --subindex) { \
                if ((index * subelems + subindex - offset) >= 0) { \
                    buf[index * subelems + subindex - offset] = value; \
                    value >>= sizeof(buf[0]) * 8; \
                } \
            } \
            address += CSR_OFFSET_BYTES; \
        } \
    } \
}

#define _csr_wr_buf(address, buf, count) \
{ \
    int index, subindex, offset, subregs, subelems; \
    uint64_t value; \
    if (sizeof(buf[0]) >= CSR_DW_BYTES) { \
        for (index = 0; index < count; ++index) { \
            _csr_wr(address, buf[index], sizeof(buf[0])); \
            address += CSR_OFFSET_BYTES * num_subregs(sizeof(buf[0])); \
        } \
    } else { \
        subregs = num_subregs(sizeof(buf[0]) * count); \
        subelems = CSR_DW_BYTES / sizeof(buf[0]); \
        offset = subregs * subelems - count; \
        for (index = 0; index < subregs; ++index) { \
            value = 0; \
            for (subindex = 0; subindex < subelems; ++subindex) { \
                if ((index * subelems + subindex - offset) >= 0) { \
                    value <<= sizeof(buf[0]) * 8; \
                    value |= buf[index * subelems + subindex - offset]; \
                } \
            } \
            csr_write_simple(value, address); \
            address += CSR_OFFSET_BYTES; \
        } \
    } \
}

static inline void csr_rd_buf_uint8(unsigned long address, uint8_t *buf, int count) {
    _csr_rd_buf(address, buf, count);
}

static inline void csr_wr_buf_uint8(unsigned long address, const uint8_t *buf, int count) {
    _csr_wr_buf(address, buf, count);
}

static inline void csr_rd_buf_uint16(unsigned long address, uint16_t *buf, int count) {
    _csr_rd_buf(address, buf, count);
}

static inline void csr_wr_buf_uint16(unsigned long address, const uint16_t *buf, int count) {
    _csr_wr_buf(address, buf, count);
}

static inline void csr_rd_buf_uint32(unsigned long address, uint32_t *buf, int count) {
    _csr_rd_buf(address, buf, count);
}

static inline void csr_wr_buf_uint32(unsigned long address, const uint32_t *buf, int count) {
    _csr_wr_buf(address, buf, count);
}

static inline void csr_rd_buf_uint64(unsigned long address, uint64_t *buf, int count) {
    _csr_rd_buf(address, buf, count);
}

static inline void csr_wr_buf_uint64(unsigned long address, const uint64_t *buf, int count) {
    _csr_wr_buf(address, buf, count);
}

#endif
"""


def _align_up(value: int, alignment: int) -> int:
    return (value + alignment - 1) & -alignment


def _litex_uart_tuning_word(clk_freq: int, baudrate: int) -> int:
    return (int(baudrate) << 32) // int(clk_freq)


def pack_litex_memory_words(data: bytes, *, data_width: int, endianness: str = 'big') -> list[int]:
    if data_width % 32 != 0:
        raise ValueError('LiteX memory word packing requires a data width divisible by 32 bits')
    if endianness not in ('big', 'little'):
        raise ValueError('LiteX memory word packing endianness must be either big or little')
    if not data:
        return []

    bytes_per_word = data_width // 8
    packed_words: list[int] = []
    for offset in range(0, len(data), bytes_per_word):
        chunk = data[offset: offset + bytes_per_word]
        if len(chunk) < bytes_per_word:
            chunk = chunk + (b'\x00' * (bytes_per_word - len(chunk)))

        word_value = 0
        for filled_data_width in range(0, data_width, 32):
            cur_byte = filled_data_width // 8
            subword = int.from_bytes(chunk[cur_byte: cur_byte + 4], endianness)
            word_value |= subword << filled_data_width
        packed_words.append(word_value)
    return packed_words


def _write_stage0_header(
    output_path: Path,
    *,
    soc: Little64LiteXSoC,
    ram_base: int,
    ram_size: int,
    kernel_physical_base: int,
) -> None:
    if not soc.finalized:
        soc.finalize()

    rom_region = soc.bus.regions.get('rom')
    uart_region = soc.csr.regions.get('uart')
    uart_phy_region = soc.csr.regions.get('uart_phy')
    spisdcard_region = soc.csr.regions.get('spisdcard')
    spisdcard = getattr(soc, 'spisdcard', None)
    sdcard_phy_region = soc.csr.regions.get('sdcard_phy')
    sdcard_core_region = soc.csr.regions.get('sdcard_core')
    sdcard_block2mem_region = soc.csr.regions.get('sdcard_block2mem')
    sdram_region = soc.csr.regions.get('sdram')
    has_native_sd = sdcard_phy_region is not None and sdcard_core_region is not None and sdcard_block2mem_region is not None
    has_spi_sd = spisdcard_region is not None
    if uart_region is None or (not has_native_sd and not has_spi_sd):
        raise ValueError('SD-capable LiteX SoC is missing the UART or SDCard CSR regions needed by stage-0')
    if has_native_sd and has_spi_sd:
        raise ValueError('stage-0 header generation expects either native SDCard CSRs or SPI SDCard CSRs, not both')

    uart_base = uart_region.origin
    if has_native_sd and soc.boot_source == 'bootrom':
        uart_base = LITEX_BOOTROM_SD_UART_BASE

    sdcard_lines: list[str]
    if has_native_sd:
        sdcard_lines = [
            '#define L64_SDCARD_INTERFACE_NATIVE 1',
            f'#define L64_SDCARD_BLOCK2MEM_BASE 0x{sdcard_block2mem_region.origin:016x}ULL',
            f'#define L64_SDCARD_CORE_BASE 0x{sdcard_core_region.origin:016x}ULL',
            f'#define L64_SDCARD_PHY_BASE 0x{sdcard_phy_region.origin:016x}ULL',
            '',
            '#define L64_SDCARD_BLOCK2MEM_DMA_BASE_ADDR (L64_SDCARD_BLOCK2MEM_BASE + 0x00ULL)',
            '#define L64_SDCARD_BLOCK2MEM_DMA_LENGTH_ADDR (L64_SDCARD_BLOCK2MEM_BASE + 0x08ULL)',
            '#define L64_SDCARD_BLOCK2MEM_DMA_ENABLE_ADDR (L64_SDCARD_BLOCK2MEM_BASE + 0x0cULL)',
            '#define L64_SDCARD_BLOCK2MEM_DMA_DONE_ADDR (L64_SDCARD_BLOCK2MEM_BASE + 0x10ULL)',
            '',
            '#define L64_SDCARD_CORE_CMD_ARGUMENT_ADDR (L64_SDCARD_CORE_BASE + 0x00ULL)',
            '#define L64_SDCARD_CORE_CMD_COMMAND_ADDR (L64_SDCARD_CORE_BASE + 0x04ULL)',
            '#define L64_SDCARD_CORE_CMD_SEND_ADDR (L64_SDCARD_CORE_BASE + 0x08ULL)',
            '#define L64_SDCARD_CORE_CMD_RESPONSE_ADDR (L64_SDCARD_CORE_BASE + 0x0cULL)',
            '#define L64_SDCARD_CORE_CMD_EVENT_ADDR (L64_SDCARD_CORE_BASE + 0x1cULL)',
            '#define L64_SDCARD_CORE_DATA_EVENT_ADDR (L64_SDCARD_CORE_BASE + 0x20ULL)',
            '#define L64_SDCARD_CORE_BLOCK_LENGTH_ADDR (L64_SDCARD_CORE_BASE + 0x24ULL)',
            '#define L64_SDCARD_CORE_BLOCK_COUNT_ADDR (L64_SDCARD_CORE_BASE + 0x28ULL)',
            '',
            '#define L64_SDCARD_PHY_CARD_DETECT_ADDR (L64_SDCARD_PHY_BASE + 0x00ULL)',
            '#define L64_SDCARD_PHY_CLOCK_DIVIDER_ADDR (L64_SDCARD_PHY_BASE + 0x04ULL)',
            '#define L64_SDCARD_PHY_INITIALIZE_ADDR (L64_SDCARD_PHY_BASE + 0x08ULL)',
            '#define L64_SDCARD_PHY_DATAW_STATUS_ADDR (L64_SDCARD_PHY_BASE + 0x10ULL)',
            '#define L64_SDCARD_PHY_SETTINGS_ADDR (L64_SDCARD_PHY_BASE + 0x18ULL)',
        ]
    else:
        spi_data_width = getattr(spisdcard, 'data_width', 8)
        sdcard_lines = [
            '#define L64_SDCARD_INTERFACE_SPI 1',
            f'#define L64_SDCARD_SPI_BASE 0x{spisdcard_region.origin:016x}ULL',
            f'#define L64_SDCARD_SPI_DATA_WIDTH {spi_data_width}U',
            '',
            '#define L64_SDCARD_SPI_CONTROL_ADDR (L64_SDCARD_SPI_BASE + 0x00ULL)',
            '#define L64_SDCARD_SPI_STATUS_ADDR (L64_SDCARD_SPI_BASE + 0x04ULL)',
            '#define L64_SDCARD_SPI_MOSI_ADDR (L64_SDCARD_SPI_BASE + 0x08ULL)',
            '#define L64_SDCARD_SPI_MISO_ADDR (L64_SDCARD_SPI_BASE + 0x0cULL)',
            '#define L64_SDCARD_SPI_CS_ADDR (L64_SDCARD_SPI_BASE + 0x10ULL)',
            '#define L64_SDCARD_SPI_LOOPBACK_ADDR (L64_SDCARD_SPI_BASE + 0x14ULL)',
            '#define L64_SDCARD_SPI_CLK_DIVIDER_ADDR (L64_SDCARD_SPI_BASE + 0x18ULL)',
        ]

    output_path.write_text(
        '\n'.join([
            '#ifndef LITTLE64_LITEX_SD_BOOT_REGS_H',
            '#define LITTLE64_LITEX_SD_BOOT_REGS_H',
            '',
            f'#define L64_SYS_CLK_FREQ {soc.sys_clk_freq}ULL',
            f'#define L64_RAM_BASE 0x{ram_base:016x}ULL',
            f'#define L64_RAM_SIZE 0x{ram_size:016x}ULL',
            f'#define L64_KERNEL_PHYSICAL_BASE 0x{kernel_physical_base:016x}ULL',
            f'#define L64_BOOTROM_BASE 0x{0 if rom_region is None else rom_region.origin:016x}ULL',
            f'#define L64_BOOTROM_SIZE 0x{0 if rom_region is None else rom_region.size:016x}ULL',
            f'#define L64_HAVE_SDRAM_INIT {1 if sdram_region is not None else 0}',
            '',
            '#define L64_UART_BAUDRATE 115200U',
            '#define L64_UART_EVENT_MASK 0x00000003U',
            f'#define L64_UART_PHY_TUNING_WORD_VALUE 0x{_litex_uart_tuning_word(soc.sys_clk_freq, 115200):08x}U',
            '',
            f'#define L64_UART_BASE 0x{uart_base:016x}ULL',
            *([] if uart_phy_region is None else [f'#define L64_UART_PHY_BASE 0x{uart_phy_region.origin:016x}ULL']),
            f'#define L64_SDRAM_CSR_BASE 0x{0 if sdram_region is None else sdram_region.origin:016x}ULL',
            '',
            '#define L64_UART_RXTX_ADDR (L64_UART_BASE + 0x00ULL)',
            '#define L64_UART_TXFULL_ADDR (L64_UART_BASE + 0x04ULL)',
            '#define L64_UART_RXEMPTY_ADDR (L64_UART_BASE + 0x08ULL)',
            '#define L64_UART_EV_STATUS_ADDR (L64_UART_BASE + 0x0cULL)',
            '#define L64_UART_EV_PENDING_ADDR (L64_UART_BASE + 0x10ULL)',
            '#define L64_UART_EV_ENABLE_ADDR (L64_UART_BASE + 0x14ULL)',
            *([] if uart_phy_region is None else ['#define L64_UART_PHY_TUNING_WORD_ADDR (L64_UART_PHY_BASE + 0x00ULL)']),
            '',
            *sdcard_lines,
            '',
            '#endif',
            '',
        ]),
        encoding='utf-8',
    )


def _write_stage0_generated_support(output_dir: Path, *, soc: Little64LiteXSoC) -> None:
    if not soc.finalized:
        soc.finalize()

    generated_dir = output_dir / 'generated'
    hw_dir = output_dir / 'hw'
    generated_dir.mkdir(parents=True, exist_ok=True)
    hw_dir.mkdir(parents=True, exist_ok=True)

    soc_header_text = litex_export.get_soc_header(soc.constants, with_access_functions=False)
    soc_header_text = soc_header_text.replace(
        '#define CONFIG_CPU_NOP "nop"',
        '#define CONFIG_CPU_NOP "move R0, R0"',
    )
    (generated_dir / 'soc.h').write_text(soc_header_text, encoding='utf-8')
    (output_dir / 'system.h').write_text(STAGE0_SYSTEM_HEADER, encoding='utf-8')
    (hw_dir / 'common.h').write_text(STAGE0_HW_COMMON_HEADER, encoding='utf-8')

    if not hasattr(soc, 'sdram'):
        return

    liblitedram_regions = _ordered_liblitedram_csr_regions(soc)
    (generated_dir / 'csr.h').write_text(
        litex_export.get_csr_header(
            liblitedram_regions,
            soc.constants,
            with_access_functions=True,
            with_fields_access_functions=False,
        ),
        encoding='utf-8',
    )
    (generated_dir / 'mem.h').write_text(
        litex_export.get_mem_header({'main_ram': soc.bus.regions['main_ram']}),
        encoding='utf-8',
    )
    (generated_dir / 'sdram_phy.h').write_text(
        get_sdram_phy_c_header(
            soc.sdram.controller.settings.phy,
            soc.sdram.controller.settings.timing,
            soc.sdram.controller.settings.geom,
        ),
        encoding='utf-8',
    )
    _write_liblitedram_shims(output_dir)


def _ordered_liblitedram_csr_regions(soc: Little64LiteXSoC) -> dict:
    wanted = ('sdram', 'ddrphy')
    present = [name for name in wanted if name in soc.csr_regions]
    present.sort(key=lambda name: soc.csr_regions[name].origin)
    return {name: soc.csr_regions[name] for name in present}


def _write_liblitedram_shims(work_dir: Path) -> None:
    (work_dir / 'stdio.h').write_text(
        '#ifndef STAGE0_STDIO_H\n#define STAGE0_STDIO_H\n#endif\n',
        encoding='utf-8',
    )
    (work_dir / 'stdlib.h').write_text(
        '#ifndef STAGE0_STDLIB_H\n#define STAGE0_STDLIB_H\n'
        '#ifndef NULL\n#define NULL ((void*)0)\n#endif\n'
        '#endif\n',
        encoding='utf-8',
    )
    (work_dir / 'litedram_compat.h').write_text(
        '#ifndef STAGE0_LITEDRAM_COMPAT_H\n'
        '#define STAGE0_LITEDRAM_COMPAT_H\n'
        '/* Force-included when building liblitedram and stage-0. Neutralises printf\n'
        '   so the calibration log strings do not consume boot ROM space. */\n'
        '#define printf(...) ((void)0)\n'
        '#endif\n',
        encoding='utf-8',
    )


def _generate_stage0_sdram_csr_header(soc: Little64LiteXSoC) -> str:
    if not soc.finalized:
        soc.finalize()
    return litex_export.get_csr_header(
        _ordered_liblitedram_csr_regions(soc),
        soc.constants,
        with_access_functions=True,
        with_fields_access_functions=False,
    )


def build_litex_sd_stage0(stage0_source: Path, stage0_linker: Path, generated_header_dir: Path, work_dir: Path) -> bytes:
    sdram_phy_header = generated_header_dir / 'generated' / 'sdram_phy.h'
    use_liblitedram = sdram_phy_header.is_file()
    compat_header = generated_header_dir / 'litedram_compat.h'

    compile_units = [
        Stage0CompileUnit(stage0_source, 'litex_sd_boot.o'),
    ]
    extra_include_dirs: list[Path] = []
    force_include_headers: list[Path] = []
    extra_cflags: list[str] = []
    if use_liblitedram:
        software_root = _litex_software_root()
        extra_include_dirs += [
            software_root,
            software_root / 'include',
        ]
        force_include_headers.append(compat_header)
        extra_cflags.append('-DSDRAM_TEST_DISABLE')
        liblitedram_dir = _litex_software_root() / 'liblitedram'
        compile_units += [
            Stage0CompileUnit(liblitedram_dir / 'sdram.c', 'liblitedram_sdram.o'),
            Stage0CompileUnit(liblitedram_dir / 'accessors.c', 'liblitedram_accessors.o'),
        ]

    return build_stage0_binary(
        compile_units=compile_units,
        linker_script=stage0_linker,
        work_dir=work_dir,
        output_stem='litex_sd_boot',
        optimization='-Os',
        generated_header_dir=generated_header_dir,
        extra_include_dirs=extra_include_dirs,
        force_include_headers=force_include_headers,
        extra_cflags=extra_cflags,
    )


def build_litex_sd_boot_artifacts(
    *,
    soc: Little64LiteXSoC,
    kernel_elf: Path,
    dtb: Path,
    bootrom_output: Path,
    sd_output: Path,
    ram_base: int,
    ram_size: int,
    kernel_physical_base: int,
    rootfs_image: Path | None = None,
    no_rootfs: bool = False,
    stage0_source: Path = Path('target/c_boot/litex_sd_boot.c'),
    stage0_linker: Path = Path('target/c_boot/linker_litex_bootrom.ld'),
    sd_card_size_bytes: int = DEFAULT_SD_CARD_SIZE_BYTES,
    boot_partition_size_mb: int = DEFAULT_SD_BOOT_PARTITION_SIZE_MB,
) -> bytes:
    image_output = bootrom_output.resolve()
    sd_output = sd_output.resolve()
    work_dir = image_output.parent / f'{image_output.stem}.work'
    work_dir.mkdir(parents=True, exist_ok=True)

    generated_header = work_dir / 'litex_sd_boot_regs.h'
    _write_stage0_header(
        generated_header,
        soc=soc,
        ram_base=ram_base,
        ram_size=ram_size,
        kernel_physical_base=kernel_physical_base,
    )
    _write_stage0_generated_support(work_dir, soc=soc)

    stage0_bytes = build_litex_sd_stage0(
        (REPO_ROOT / stage0_source).resolve(),
        (REPO_ROOT / stage0_linker).resolve(),
        work_dir,
        work_dir,
    )

    if soc.boot_source == 'bootrom':
        image_size = max(soc.litex_target.integrated_rom_size, _align_up(len(stage0_bytes), 4096))
        if len(stage0_bytes) > image_size:
            raise ValueError('stage-0 image exceeds the selected boot ROM capacity')
        stage0_image = bytearray(image_size)
        stage0_image[:len(stage0_bytes)] = stage0_bytes
    else:
        image_size = max(0x10000, _align_up(len(stage0_bytes), 4096))
        stage0_image = bytearray(image_size)
        stage0_image[:len(stage0_bytes)] = stage0_bytes

    rootfs_bytes = None
    if not no_rootfs:
        resolved_rootfs = build_default_rootfs_image(python_bin=sys.executable) if rootfs_image is None else rootfs_image.resolve()
        rootfs_bytes = resolved_rootfs.read_bytes()
    write_litex_sd_card_image(
        sd_output,
        kernel_elf_bytes=kernel_elf.resolve().read_bytes(),
        dtb_bytes=dtb.resolve().read_bytes(),
        rootfs_bytes=rootfs_bytes,
        total_disk_size_bytes=sd_card_size_bytes,
        boot_partition_size_mb=boot_partition_size_mb,
    )

    image_output.parent.mkdir(parents=True, exist_ok=True)
    image_bytes = bytes(stage0_image)
    image_output.write_bytes(image_bytes)
    return image_bytes


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description='Build Little64 SD boot artifacts for LiteX-compatible boot flows.')
    parser.add_argument('--kernel-elf', type=Path, required=True, help='Little64 Linux kernel ELF to store as VMLINUX in the FAT32 boot partition.')
    parser.add_argument('--dtb', type=Path, required=True, help='Compiled DTB to store as BOOT.DTB in the FAT32 boot partition.')
    parser.add_argument('--bootrom-output', type=Path, help='Boot ROM image path to write.')
    parser.add_argument('--flash-output', type=Path, default=None, help=argparse.SUPPRESS)
    parser.add_argument('--sd-output', type=Path, required=True, help='Raw SD card image path to write.')
    rootfs_group = parser.add_mutually_exclusive_group()
    rootfs_group.add_argument('--rootfs-image', type=Path,
        help='Explicit ext4 rootfs image to place in the second partition. When omitted, the builder regenerates the default init.S-based rootfs.')
    rootfs_group.add_argument('--no-rootfs', action='store_true',
        help='Leave the second partition empty instead of generating the default ext4 rootfs.')
    parser.add_argument('--ram-base', type=lambda value: int(value, 0), default=None, help='Physical RAM base visible to the SoC. Defaults to the selected LiteX target contract.')
    parser.add_argument('--ram-size', type=lambda value: int(value, 0), default=None, help='Physical RAM size visible to the SoC. Defaults to the selected LiteX target contract.')
    parser.add_argument('--kernel-physical-base', type=lambda value: int(value, 0), default=None,
        help='Physical kernel load base. Defaults to the selected RAM base when it is above the historical Linux low-memory base.')
    parser.add_argument(
        '--cpu-variant',
        default='standard',
        help='LiteX CPU variant used to derive the SoC CSR layout for stage-0. `standard` selects the V2 core; use `standard-basic` for the legacy core.',
    )
    parser.add_argument('--litex-target', choices=LITTLE64_LITEX_TARGET_NAMES, default='sim-bootrom',
        help='Named LiteX target descriptor used for SoC metadata and the default boot source.')
    parser.add_argument('--boot-source', choices=LITTLE64_LITEX_BOOT_SOURCES, default=None,
        help='Override the LiteX target default boot source while deriving the SoC CSR layout.')
    parser.add_argument('--sdcard-mode', choices=('native', 'spi'), default='native',
        help='Select the SD controller backend when deriving the LiteX CSR layout.')
    parser.add_argument('--with-sdram', action='store_true',
        help='Enable the LiteDRAM-backed SDRAM model even for simulation targets that default to integrated RAM.')
    parser.add_argument('--stage0-source', type=Path, default=Path('target/c_boot/litex_sd_boot.c'), help='SD-capable stage-0 C source to compile into the internal boot ROM image.')
    parser.add_argument('--stage0-linker', type=Path, default=Path('target/c_boot/linker_litex_bootrom.ld'), help='Linker script used for the internal boot ROM stage-0 image.')
    parser.add_argument('--sd-card-size-bytes', type=lambda value: int(value, 0), default=DEFAULT_SD_CARD_SIZE_BYTES,
        help='Total raw SD card image size in bytes. Defaults to 4 GiB.')
    parser.add_argument('--boot-partition-size-mb', type=int, default=DEFAULT_SD_BOOT_PARTITION_SIZE_MB,
        help='FAT32 boot partition size in MiB. Defaults to 256.')
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    legacy_flash_output = args.flash_output is not None and args.bootrom_output is None
    output_arg = args.bootrom_output or args.flash_output
    if output_arg is None:
        raise ValueError('missing required output path: pass --bootrom-output')

    target = resolve_litex_target(args.litex_target)
    default_boot_source = 'spiflash' if legacy_flash_output else target.boot_source
    boot_source = normalize_litex_boot_source(args.boot_source or default_boot_source)
    resolved_with_sdram = args.with_sdram or target.with_sdram

    default_ram_base = 0 if boot_source == 'spiflash' else target.main_ram_base
    default_ram_size = 0x0400_0000 if boot_source == 'spiflash' else target.default_ram_size
    ram_base = default_ram_base if args.ram_base is None else args.ram_base
    ram_size = default_ram_size if args.ram_size is None else args.ram_size
    kernel_physical_base = max(ram_base, LITTLE64_LINUX_RAM_BASE) if args.kernel_physical_base is None else args.kernel_physical_base

    stage0_linker = args.stage0_linker
    if legacy_flash_output and stage0_linker == Path('target/c_boot/linker_litex_bootrom.ld'):
        stage0_linker = Path('target/c_boot/linker_litex_spi_boot.ld')

    soc = Little64LiteXSimSoC(
        cpu_variant=args.cpu_variant,
        integrated_main_ram_size=0 if resolved_with_sdram else ram_size,
        main_ram_size=ram_size,
        with_sdram=resolved_with_sdram,
        with_spi_flash=(target.with_spi_flash or boot_source == 'spiflash'),
        with_sdcard=True,
        sdcard_mode=args.sdcard_mode,
        with_timer=True,
        litex_target=args.litex_target,
        boot_source=boot_source,
        sdram_module=target.sdram_module,
    )
    build_litex_sd_boot_artifacts(
        soc=soc,
        kernel_elf=args.kernel_elf,
        dtb=args.dtb,
        bootrom_output=output_arg,
        sd_output=args.sd_output,
        ram_base=ram_base,
        ram_size=ram_size,
        kernel_physical_base=kernel_physical_base,
        rootfs_image=args.rootfs_image,
        no_rootfs=args.no_rootfs,
        stage0_source=args.stage0_source,
        stage0_linker=stage0_linker,
        sd_card_size_bytes=args.sd_card_size_bytes,
        boot_partition_size_mb=args.boot_partition_size_mb,
    )
    return 0


def run(argv: list[str]) -> int:
    return main(argv) or 0


if __name__ == '__main__':
    raise SystemExit(main())