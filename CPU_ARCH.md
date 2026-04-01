# Little-64 CPU Architecture Reference

This document describes the CPU-visible architecture and points to source-of-truth files used for implementation.

## Source of Truth

- Opcode definitions:
  - `arch/opcodes_ls.def`
  - `arch/opcodes_gp.def`
- Opcode enums/format helpers:
  - `arch/opcodes.hpp`
- Runtime execution behavior:
  - `emulator/cpu.cpp`
  - `emulator/cpu.hpp`
- Assembly/disassembly behavior:
  - `project/llvm_assembler.cpp`
  - `disassembler/disassembler.cpp`

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
| 6 | `interrupt_except` |
| 7..10 | `interrupt_data[0..3]` |

## Instruction Encoding Overview

All instructions are 16-bit words.

| Top bits `[15:14]` | Format |
|---|---|
| `00` | LS register form |
| `01` | LS PC-relative form |
| `10` | `LDI` |
| `11` | Extended (GP ALU or unconditional `JUMP`) |

## LS Opcode Space (formats `00` and `01`)

From `arch/opcodes_ls.def`:

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

## GP Opcode Space (format `110`)

From `arch/opcodes_gp.def`:

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
- `IRET` restores interrupt return state (`interrupt_epc`/`interrupt_eflags`) and re-enables interrupts.

## Calling Convention (Project Convention)

Current convention used by project examples/tooling:

- `R13` = stack pointer
- `R14` = link register
- Return values typically in `R1` (and `R2` when needed)

Treat this as project ABI convention, not a formally versioned external ABI yet.

## Change Checklist

When adding/changing an instruction:

1. Update `arch/opcodes_*.def` if opcode metadata changes.
2. Update emulator dispatch logic in `emulator/cpu.cpp`.
3. Update assembly wrapper/disassembler behavior if syntax/text changes.
4. Add or update tests under `tests/`.
5. Update `docs/assembly-syntax.md` and this file.

## Update Checklist

Before merging architecture changes:

- run `meson compile -C builddir`,
- run `meson test -C builddir --print-errorlogs`,
- verify opcode docs still match `arch/opcodes_ls.def` and `arch/opcodes_gp.def`.
