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

The current `--boot-mode=direct` path is a Linux-oriented physical-entry loader.

The loader:

1. parses PT_LOAD segments,
2. loads them into RAM,
3. zero-fills `.bss`,
4. instantiates the default virtual platform,
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
- `host/boot/boot_abi.h`
- `target/linux_port/linux/arch/little64/kernel/head.S`

Primary proving tests:

- `tests/host/test_paging.cpp`
- `tests/host/boot/test_direct_boot_paging.py`