# Little-64 CPU Architecture Reference

This document describes the CPU-visible architecture and points to source-of-truth files used for implementation.

## Source of Truth

- Opcode definitions:
  - `host/arch/opcodes_ls.def`
  - `host/arch/opcodes_gp.def`
- Opcode enums/format helpers:
  - `host/arch/opcodes.hpp`
- Runtime execution behavior:
  - `host/emulator/cpu.cpp`
  - `host/emulator/cpu.hpp`
- Assembly/disassembly behavior:
  - `host/project/llvm_assembler.cpp`
  - `host/disassembler/disassembler.cpp`

If this document conflicts with code, code is authoritative and this document must be updated in the same change.

## Register File

| Register | Meaning |
|---|---|
| `R0` | Hard-wired zero (writes discarded) |
| `R1`–`R12` | General-purpose |
| `R13` | Stack pointer (`SP`) |
| `R14` | Link register (`LR`) |
| `R15` | Program counter (`PC`) |

## Flags Register

| Bit | Name | Meaning |
|---|---|---|
| 0 | `Z` | Result is zero |
| 1 | `C` | Carry/borrow depending on operation |
| 2 | `S` | Sign bit of result is set |

## Special Registers (for `LSR`/`SSR`)

`LSR Rs1, Rd` reads special register index `Rs1` into `Rd`.
`SSR Rs1, Rd` writes `Rd` to special register index `Rs1`.

Current index map (from `cpu.hpp`):

| Index | Register |
|---|---|
| 0 | `cpu_control` |
| 1 | `interrupt_table_base` |
| 2 | `interrupt_mask` |
| 3 | `interrupt_states` |
| 4 | `interrupt_epc` |
| 5 | `interrupt_eflags` |
| 6 | `trap_cause` |
| 7 | `trap_fault_addr` |
| 8 | `trap_access` |
| 9 | `trap_pc` |
| 10 | `trap_aux` |
| 11 | `page_table_root_physical` |
| 12 | `boot_info_frame_physical` |
| 13 | `boot_source_page_size` |
| 14 | `boot_source_page_count` |
| 15 | `hypercall_caps` |
| 16 | `interrupt_cpu_control` |

## Instruction Encoding Overview

All instructions are 16-bit words.

| Top bits `[15:14]` | Format |
|---|---|
| `00` | LS register form |
| `01` | LS PC-relative form |
| `10` | `LDI` |
| `11` | Extended (GP ALU or unconditional `JUMP`) |

## LS Opcode Space (formats `00` and `01`)

From `host/arch/opcodes_ls.def`:

| Opcode | Mnemonic |
|---|---|
| 0 | `LOAD` |
| 1 | `STORE` |
| 2 | `PUSH` |
| 3 | `POP` |
| 4 | `MOVE` |
| 5 | `BYTE_LOAD` |
| 6 | `BYTE_STORE` |
| 7 | `SHORT_LOAD` |
| 8 | `SHORT_STORE` |
| 9 | `WORD_LOAD` |
| 10 | `WORD_STORE` |
| 11 | `JUMP.Z` |
| 12 | `JUMP.C` |
| 13 | `JUMP.S` |
| 14 | `JUMP.GT` |
| 15 | `JUMP.LT` |

Notes:

- LS opcodes are shared between format `00` and format `01`.
- Behavior may differ by format and must be implemented/tested in both `_dispatchLSReg` and `_dispatchLSPCRel`.
- For PC-relative JUMPs, `R15` is always the target. The low 4 bits in that encoding extend offset range instead of selecting a register.

## GP Opcode Space (format `110`)

From `host/arch/opcodes_gp.def`:

| Opcode | Mnemonic | Encoding kind |
|---|---|---|
| 0 | `ADD` | `RS1_RD` |
| 1 | `SUB` | `RS1_RD` |
| 2 | `TEST` | `RS1_RD` |
| 16 | `AND` | `RS1_RD` |
| 17 | `OR` | `RS1_RD` |
| 18 | `XOR` | `RS1_RD` |
| 20 | `SLL` | `RS1_RD` |
| 21 | `SRL` | `RS1_RD` |
| 22 | `SRA` | `RS1_RD` |
| 23 | `SLLI` | `IMM4_RD` |
| 24 | `SRLI` | `IMM4_RD` |
| 25 | `SRAI` | `IMM4_RD` |
| 28 | `LSR` | `RS1_RD` |
| 29 | `SSR` | `RS1_RD` |
| 30 | `IRET` | `NONE` |
| 31 | `STOP` | `NONE` |

## Control-Flow Notes

- Conditional `JUMP.*` instructions exist in LS opcode space.
- Unconditional `JUMP` uses extended format `111` with a 13-bit signed PC-relative offset.
- `IRET` is a privileged instruction. It restores PC from `interrupt_epc`, flags from `interrupt_eflags`, and full CPU control state (including privilege level) from `interrupt_cpu_control`. It is blocked in user mode and raises trap 63 (`TRAP_PRIVILEGED_INSTRUCTION`) if executed in user mode.

## Privilege Levels and User Mode

User mode is controlled by bit 17 in `cpu_control`. Two privilege levels exist:

- **Supervisor mode** (bit 17 = 0): Can execute all instructions and access all memory.
- **User mode** (bit 17 = 1): Cannot execute privileged instructions (`IRET`, `STOP`, `LSR`, `SSR`); cannot access supervisor-only pages.

### Privileged Instructions

The following instructions raise trap 63 (`TRAP_PRIVILEGED_INSTRUCTION`) if executed in user mode:
- `IRET` — return from exception (allows changing privilege level)
- `STOP` — halt emulation
- `LSR` — load special register
- `SSR` — store special register

### Page Table User Bit

Bit 4 in a page table entry (PTE) is the user bit (`PTE_U`). In user mode, a page must have `PTE_U` set; otherwise, access raises trap 82 (`TRAP_PAGE_FAULT_PERMISSION`). In supervisor mode, `PTE_U` is ignored.

### Kernel→User Transition

The standard pattern to enter user mode:
1. In supervisor mode, set up `interrupt_epc` (user entry address) and `interrupt_eflags` (desired flags).
2. Write to `interrupt_cpu_control` (SR 16) with the desired `cpu_control` value **with bit 17 set** (user mode).
3. Execute `IRET` — this restores `cpu_control` (including mode), PC, and flags, entering user mode.

### Interrupt Entry

On any interrupt or exception:
1. The CPU saves `cpu_control` to `interrupt_cpu_control`.
2. The CPU forcibly clears the user-mode bit (bit 17), entering supervisor mode.
3. Other control bits are modified per interrupt handling rules (`InInterrupt`, `IntEnable`, `CurIntNum`).
4. PC jumps to the handler address from the interrupt table.

## Calling Convention (Project Convention)

Current convention used by project examples/tooling:

- `R13` = stack pointer
- `R14` = link register
- Return values typically in `R1` (and `R2` when needed)

Treat this as project ABI convention, not a formally versioned external ABI yet.

## Maintenance Checklist

When adding or changing an instruction:

1. Update `host/arch/opcodes_*.def` if opcode metadata changes.
2. Update emulator dispatch logic in `host/emulator/cpu.cpp`.
3. Update assembly wrapper/disassembler behavior if syntax/text changes.
4. Add or update tests under `tests/`.
5. Update `docs/assembly-syntax.md` and this file.

Before merging architecture changes:

- run `meson compile -C builddir`,
- run `meson test -C builddir --print-errorlogs`,
- verify opcode docs match `host/arch/opcodes_ls.def` and `host/arch/opcodes_gp.def`.
