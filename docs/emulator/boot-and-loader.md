# Emulator Boot And Loader Behavior

This chapter documents the current boot paths and loader contracts implemented
by the emulator.

## Minimal Boot Hypercall Services

The emulator currently exposes a minimal boot-service interface through the
special-register selector `15` path.

Service IDs read from `R1`:

| ID | Name |
|---|---|
| 1 | `MEMINFO` |
| 2 | `GET_BOOT_SOURCE_INFO` |
| 3 | `READ_BOOT_SOURCE_PAGES` |

Status values returned in `R1`:

| Value | Meaning |
|---|---|
| 0 | OK |
| 1 | invalid |
| 2 | unsupported |
| 3 | range error |

### `MEMINFO`

Returns:

| Register | Meaning |
|---|---|
| `R2` | physical memory base |
| `R3` | physical memory size |
| `R4` | MMIO hint, currently UART base |
| `R5` | capability bits |

### `GET_BOOT_SOURCE_INFO`

Input:

- `R2` = source selector, currently only `0`

Returns:

| Register | Meaning |
|---|---|
| `R2` | source type, currently `1` for paged source |
| `R3` | boot source page size |
| `R4` | boot source page count |
| `R5` | source flags |

### `READ_BOOT_SOURCE_PAGES`

Inputs:

| Register | Meaning |
|---|---|
| `R2` | start page |
| `R3` | page count |
| `R4` | destination physical address |
| `R5` | source selector |

Returns:

| Register | Meaning |
|---|---|
| `R1` | status |
| `R2` | copied page count |

The current implementation copies bytes directly into guest physical memory
through the emulator memory bus.

## Boot Payload Structure

`host/boot/boot_abi.h` defines `Little64BootInfoFrame`, used by BIOS and C-boot
experiments and tests.

Important fields include:

- physical memory base and size,
- kernel physical and virtual placement,
- page-table root physical address,
- boot stack top,
- a memory-region table.

## BIOS Boot Path

The emulator BIOS-oriented path currently assumes:

1. CPU starts in physical mode,
2. firmware uses the minimal boot hypercalls,
3. firmware parses and loads the kernel image,
4. firmware constructs page tables,
5. firmware enables paging,
6. control transfers to the kernel virtual entry point.

## Direct Linux Boot Path

The current `--boot-mode=direct` path is a Linux-oriented physical-entry loader
that now instantiates the same LiteX-compatible board contract used by the
current emulator DTB instead of the older low-memory `virt` machine.

The loader:

1. parses PT_LOAD segments,
2. loads them into LiteX SDRAM,
3. zero-fills `.bss`,
4. instantiates the default LiteX-compatible virtual platform,
5. places the embedded DTB after the image with a conservative scratch gap,
6. resolves the entry point to a physical address,
7. enters the kernel with paging disabled.

### Entry register contract

| Register / state | Value |
|---|---|
| `R1` | physical DTB address |
| `R13` | top of physical RAM minus 8 |
| `R15` | physical address of `_start` |
| `cpu_control.IntEnable` | `0` |
| `cpu_control.PagingEnable` | `0` |
| `cpu_control.UserMode` | `0` |
| `SR12` | mirrors the DTB physical address |

### Entry-point resolution

The current loader accepts either:

1. a virtual ELF entry inside the PT_LOAD window, translated into the loaded
   physical image, or
2. an already-physical entry inside the loaded image.

### DTB placement

The direct loader currently reserves 30 pages of scratch space after the loaded
image before placing the DTB. This is intended to keep the DTB clear of early
page-table scratch memory used by the current Linux entry path.

### Early-kernel expectations

The current Linux `head.S` path expects to:

1. align the stack,
2. clear `.bss`,
3. construct initial page tables,
4. enable paging,
5. jump into the virtual kernel path.

The default direct-loader physical RAM base is now `0x40000000`, matching the
LiteX SDRAM contract used by the Linux boot helpers and HDL smoke flows.

## LiteX SPI Flash Boot Path

The current `--boot-mode=litex-flash` path always expects a raw SPI flash image.
That flash image contains the reset-resident stage-0 loader.

This path is now mainly a compatibility path for explicit manual runs. The
default LiteX Linux helper launches the bootrom path below so the emulator uses
the same integrated-ROM plus SDRAM contract as the current hardware-oriented
LiteX targets.

Without an attached `--disk`, the loader:

1. maps 64 MiB of RAM from physical `0x0`,
2. maps a 16 MiB flash ROM window at `0x20000000`, padding unused space with `0xff`,
3. exposes a LiteUART-compatible CSR block at `0xF0001000`,
4. exposes the existing timer at `0x08001000`,
5. starts execution at flash base with paging disabled.

With an attached `--disk`, the same boot mode switches to the SD-capable LiteX
layout used by the current LiteX simulation SoC:

1. the flash ROM window remains at `0x20000000`,
2. LiteSDCard CSRs are exposed starting at `0xF0000800`,
3. LiteUART moves to `0xF0004000`,
4. the timer stays at `0x08001000`,
5. stage-0 still starts from SPI flash and then loads `VMLINUX` and `BOOT.DTB` from the SD image.

### Entry register contract

| Register / state | Value |
|---|---|
| `R15` | `0x20000000` |
| `cpu_control.IntEnable` | `0` |
| `cpu_control.PagingEnable` | `0` |
| `cpu_control.UserMode` | `0` |

The flash-resident stage-0 loader is responsible for either:

1. validating the flash boot header and loading the kernel directly from flash, or
2. initializing LiteSDCard and loading `VMLINUX` plus `BOOT.DTB` from the SD image,

before transferring control to the kernel entry point.

For hardware-oriented LiteX targets that expose a programmable `uart_phy` CSR
bank, the current stage-0 code also programs the LiteUART PHY tuning word for
`115200` baud before printing its first serial status line. The emulator's
simulation UART model does not expose that PHY CSR, so the same code path
naturally skips the write there.

When the SD-backed LiteX stage-0 path is selected, the same serial output now
also includes coarse-grained progress updates while `VMLINUX` PT_LOAD contents
and `BOOT.DTB` bytes are copied from the SD image into RAM. The SPI-mode SD
build of the same stage-0 also emits short command breadcrumbs for `CMD0`,
`CMD8`, `ACMD41`, `CMD58`, and `CMD16` so hardware UART logs show the exact
init phase that failed.

The Linux helper can still be pointed at this path explicitly for compatibility,
but `--machine=litex` now defaults to the bootrom path below.

## LiteX Boot ROM Boot Path

The `--boot-mode=litex-bootrom` path expects a raw internal boot ROM image and
starts execution at physical `0x0` with the LiteX bootrom memory map.

In addition to the integrated ROM, SRAM, RAM, LiteUART, and timer windows, the
emulator now exposes a minimal LiteDRAM DFII CSR stub at `0xF0003000`. This is
present so bootrom images built for SDRAM-backed LiteX targets can run the
generated LiteDRAM initialization sequence under functional emulation before
continuing to a small stage-0 SDRAM read/write sanity test and then on to SD
or kernel handoff logic.

The Linux helper `little64 boot run` now generates this bootrom image shape by default for `--machine=litex`, along with a DTS/DTB and SD image derived from the Arty A7-35T LiteX target contract. That default helper path now assumes SDRAM at `0x40000000` with a `0x10000000` RAM window so the emulator, stage-0 metadata, and runtime DT agree on the board-sized memory map.

## ELF Loader Expectations

The current emulator loaders expect:

- ELF64,
- little-endian encoding,
- `EM_LITTLE64`,
- valid PT_LOAD ranges,
- `.bss` zero-fill semantics.

## Software VA Convention Used By The Current Linux Port

Current Linux software and paging tests use the higher-half kernel base:

`0xFFFFFFC000000000`

This is a software and loader convention for the current environment, not a
core ISA requirement.

## Sources And Proving Tests

Primary implementation sources:

- `host/emulator/cpu.cpp`
- `host/emulator/lite_uart_device.cpp`
- `host/emulator/little64.dts`
- `host/boot/boot_abi.h`
- `target/linux_port/linux/arch/little64/kernel/head.S`

Primary proving tests:

- `tests/host/test_paging.cpp`
- `tests/host/boot/test_direct_boot_paging.py`