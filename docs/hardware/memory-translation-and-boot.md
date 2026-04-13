# Memory And Translation

This chapter defines the core memory-access contract and paging model.

## Memory-Access Baseline

| Property | Architectural behavior |
|---|---|
| byte order | little-endian |
| load widths | 8, 16, 32, 64 bits |
| store widths | 8, 16, 32, 64 bits |
| instruction fetch width | 16 bits |
| instruction fetch alignment | MUST use an even virtual address |
| data alignment | MAY be unaligned |

If instruction fetch is attempted from an odd address, the CPU raises vector 1 (`TRAP_EXEC_ALIGN`).

Implementations MUST NOT raise an alignment fault for data loads or stores.

## Paging Overview

Paging is controlled by:

- `cpu_control[16]` = paging enable
- special-register selector `11` = `page_table_root_physical`

When paging is disabled, virtual addresses are treated as physical addresses.
When paging is enabled, instruction fetch and data access are translated through the page tables.

## Canonical Virtual Address Rule

Little-64 uses a 39-bit canonical virtual address space.

Canonical rule:

- bit `38` is sign-extended through bits `63:39`

If the address is not canonical, translation raises vector 8 (`TRAP_PAGE_FAULT_CANONICAL`).

## Page-Table Geometry

| Property | Value |
|---|---|
| page size | 4 KiB |
| PTE size | 8 bytes |
| entries per table | 512 |
| levels | 3 |

Index split:

| Bits | Meaning |
|---|---|
| `38:30` | L2 index |
| `29:21` | L1 index |
| `20:12` | L0 index |
| `11:0` | page offset |

## PTE Format

| Bit(s) | Name | Meaning |
|---|---|---|
| 0 | `V` | valid |
| 1 | `R` | readable |
| 2 | `W` | writable |
| 3 | `X` | executable |
| 4 | `U` | user-accessible |
| 5 | `G` | global / platform-defined |
| 6 | `A` | accessed |
| 7 | `D` | dirty |
| `9:8` | software | software-defined |
| `63:10` | `PPN` | physical page number |

Interpretation rules:

- non-leaf PTE: `V=1` and `R=W=X=0`
- leaf PTE: `V=1` and at least one of `R/W/X` is set

Supported leaf sizes:

| Level | Leaf size |
|---|---|
| L2 | 1 GiB |
| L1 | 2 MiB |
| L0 | 4 KiB |

Superpage bases are taken from the `PPN` field in 4 KiB granularity.

## Translation Rules

The translation contract REQUIRES:

1. a 3-level radix walk,
2. deterministic failure on missing or invalid entries,
3. permission checks for read, write, and execute intent,
4. no implicit identity mapping while paging is enabled.

User-mode accesses MUST have `PTE_U = 1`. Supervisor mode ignores `PTE_U`.

## A/D Bit Policy

Implementations MAY leave `A` and `D` unchanged as a side effect of translation.

## Trap Metadata For Translation Faults

| Register | Meaning |
|---|---|
| `trap_cause` | page-fault vector |
| `trap_fault_addr` | faulting VA |
| `trap_access` | `0=read`, `1=write`, `2=execute` |
| `trap_pc` | PC of faulting operation |
| `trap_aux` | subtype/level detail |

Page-fault vectors:

| Vector | Meaning |
|---|---|
| 5 | not present / invalid entry |
| 6 | permission fault |
| 7 | reserved-bit / invalid non-leaf fault |
| 8 | canonical-address fault |

`trap_aux` subtype encoding:

| Value | Meaning |
|---|---|
| 1 | no valid PTE |
| 2 | invalid non-leaf |
| 3 | permission |
| 4 | reserved-bit violation |
| 5 | canonical violation |

Level detail is platform- and implementation-defined.

## Translation Cache Scope

This hardware reference intentionally does not define any translation-cache organization.

Any translation-cache organization, page-walk cache, refill policy, or cache-invalidation detail is an implementation matter rather than a core ISA requirement.

## Boot Scope Boundary

This hardware reference intentionally does not define:

- firmware or BIOS services,
- loader handoff payloads,
- device-tree payloads,
- ELF loading policy,
- direct-boot or BIOS boot environment contracts.

## Drift Checklist

Update this chapter when any of the following change:

1. page-table geometry or PTE layout,
2. trap numbering or trap metadata encoding,
3. the architectural alignment or endianness rules,
4. the architectural scope boundary between paging semantics and platform-defined boot behavior.