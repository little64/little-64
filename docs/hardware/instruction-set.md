# Instruction Set

This chapter defines the current executable ISA contract.

## Overview

All instructions are 16-bit words. The top-level encoding split is:

| Bits `[15:14]` | Meaning |
|---|---|
| `00` | LS register format |
| `01` | LS PC-relative format |
| `10` | `LDI` format |
| `11` | extended format |

Within the extended format:

| Bits `[15:13]` | Meaning |
|---|---|
| `110` | GP opcode space |
| `111` | unconditional PC-relative jump |

## Format Layouts

### LS register format (`00`)

| Bits | Meaning |
|---|---|
| `[15:14]` | `00` |
| `[13:10]` | LS opcode |
| `[9:8]` | `offset2` |
| `[7:4]` | `Rs1` |
| `[3:0]` | `Rd` |

Effective address:

`EA = regs[Rs1] + offset2 * 2`

### LS PC-relative format (`01`)

For non-jump LS opcodes:

| Bits | Meaning |
|---|---|
| `[15:14]` | `01` |
| `[13:10]` | LS opcode |
| `[9:4]` | signed 6-bit PC-relative offset |
| `[3:0]` | `Rd` |

Effective address:

`EA = post_increment_pc + pc_rel * 2`

For `JUMP.*` LS opcodes:

| Bits | Meaning |
|---|---|
| `[15:14]` | `01` |
| `[13:10]` | LS jump opcode |
| `[9:0]` | signed 10-bit PC-relative offset |

The destination register is implicit `R15`.

### `LDI` format (`10`)

| Bits | Meaning |
|---|---|
| `[15:14]` | `10` |
| `[13:12]` | `shift` |
| `[11:4]` | `imm8` |
| `[3:0]` | `Rd` |

### GP format (`110`)

| Bits | Meaning |
|---|---|
| `[15:13]` | `110` |
| `[12:8]` | GP opcode |
| `[7:4]` | `Rs1` or 4-bit immediate, depending on opcode encoding |
| `[3:0]` | `Rd` |

### Unconditional jump format (`111`)

| Bits | Meaning |
|---|---|
| `[15:13]` | `111` |
| `[12:0]` | signed 13-bit PC-relative offset |

Target rule:

`PC = post_increment_pc + pc_rel * 2`

## LS Opcode Map

| Opcode | Mnemonic | Summary |
|---|---|---|
| 0 | `LOAD` | 64-bit load |
| 1 | `STORE` | 64-bit store |
| 2 | `PUSH` | stack push |
| 3 | `POP` | stack pop |
| 4 | `MOVE` | effective-address move |
| 5 | `BYTE_LOAD` | 8-bit load |
| 6 | `BYTE_STORE` | 8-bit store |
| 7 | `SHORT_LOAD` | 16-bit load |
| 8 | `SHORT_STORE` | 16-bit store |
| 9 | `WORD_LOAD` | 32-bit load |
| 10 | `WORD_STORE` | 32-bit store |
| 11 | `JUMP.Z` | conditional jump on `Z` |
| 12 | `JUMP.C` | conditional jump on `C` |
| 13 | `JUMP.S` | conditional jump on `S` |
| 14 | `JUMP.GT` | conditional jump on `!Z && !S` |
| 15 | `JUMP.LT` | conditional jump on `S` |

## GP Opcode Map

| Opcode | Mnemonic | Encoding | Summary |
|---|---|---|---|
| 0 | `ADD` | `RS1_RD` | add |
| 1 | `SUB` | `RS1_RD` | subtract |
| 2 | `TEST` | `RS1_RD` | subtract-for-flags, no writeback |
| 3 | `LLR` | `RS1_RD` | load-linked |
| 4 | `SCR` | `RS1_RD` | store-conditional |
| 16 | `AND` | `RS1_RD` | bitwise and |
| 17 | `OR` | `RS1_RD` | bitwise or |
| 18 | `XOR` | `RS1_RD` | bitwise xor |
| 20 | `SLL` | `RS1_RD` | logical left shift by register |
| 21 | `SRL` | `RS1_RD` | logical right shift by register |
| 22 | `SRA` | `RS1_RD` | arithmetic right shift by register |
| 23 | `SLLI` | `IMM4_RD` | logical left shift by immediate |
| 24 | `SRLI` | `IMM4_RD` | logical right shift by immediate |
| 25 | `SRAI` | `IMM4_RD` | arithmetic right shift by immediate |
| 27 | `SYSCALL` | `NONE` | synchronous exception |
| 28 | `LSR` | `RS1_RD` | load special register |
| 29 | `SSR` | `RS1_RD` | store special register |
| 30 | `IRET` | `NONE` | return from interrupt/exception |
| 31 | `STOP` | `NONE` | halt execution |

Current reserved GP opcode values are the holes not listed above.

## Effective-Address Semantics

### Register-form LS instructions

`MOVE` in LS register format is not a register-to-register move. It writes the
computed effective address into `Rd`.

`PUSH` / `POP` in LS register format use `Rd` as the stack-pointer register:

- `PUSH`: decrement `Rd` by 8, then store `regs[Rs1]` to `[Rd]`
- `POP`: load from `[Rd]` into `Rs1`, then increment `Rd` by 8

### PC-relative LS instructions

The PC-relative LS format uses the already incremented PC. That means all
PC-relative data and branch offsets are relative to the instruction after the
current one.

`PUSH` / `POP` in LS PC-relative format are asymmetric by design:

- `PUSH`: read 64 bits from the PC-relative effective address, then push that
   value using stack register `Rd`
- `POP`: pop 64 bits via stack register `Rd`, then store that value to the
   PC-relative effective address

`MOVE` in LS PC-relative format also writes the computed effective address into
`Rd`.

## Flag Semantics

### Instructions that update flags

| Instruction class | `Z` | `C` | `S` |
|---|---|---|---|
| `ADD` | result == 0 | unsigned carry-out | result bit 63 |
| `SUB` | result == 0 | borrow (`Rs1 > Rd_old`) | result bit 63 |
| `TEST` | same as `SUB` | same as `SUB` | same as `SUB` |
| `AND` / `OR` / `XOR` | result == 0 | 0 | result bit 63 |
| `SLL` / `SLLI` | result == 0 | shifted-out high bits non-zero | result bit 63 |
| `SRL` / `SRLI` | result == 0 | last shifted-out bit | result bit 63 |
| `SRA` / `SRAI` | result == 0 | last shifted-out bit | result bit 63 |

### Instructions that do not update flags

- all LS loads/stores and address-generation forms,
- unconditional `JUMP`,
- `LDI`,
- `LLR`,
- `LSR`, `SSR`, `IRET`, and `STOP`.

### Conditional-jump interpretation

Current branch conditions are taken directly from the flag register:

| Mnemonic | Condition |
|---|---|
| `JUMP.Z` | `Z == 1` |
| `JUMP.C` | `C == 1` |
| `JUMP.S` | `S == 1` |
| `JUMP.GT` | `Z == 0 && S == 0` |
| `JUMP.LT` | `S == 1` |

`JUMP.GT` and `JUMP.LT` are therefore tied to the current subtraction-based flag model and do not use a separate overflow flag.

## `LDI` Semantics

`LDI` uses an 8-bit immediate and a 2-bit shift field.

| `shift` | Behavior |
|---|---|
| `0` | `Rd = imm8` |
| `1` | `Rd |= imm8 << 8` |
| `2` | `Rd |= imm8 << 16` |
| `3` | `Rd |= imm8 << 24`; if `imm8[7] == 1`, sign-extend from bit 31 through bit 63 |

`LDI` is therefore a piecewise constant-construction instruction, not a pure load-immediate overwrite except in `shift = 0` form.

## Arithmetic And Bitwise Semantics

### `ADD`, `SUB`, `TEST`

```text
ADD : Rd = Rd + Rs1
SUB : Rd = Rd - Rs1
TEST: temp = Rd - Rs1; flags = flags(temp); Rd unchanged
```

### Shifts

Register shifts treat counts `>= 64` specially:

- `SLL`: result `0`
- `SRL`: result `0`
- `SRA`: result all ones for negative input, else `0`

Immediate shifts use the 4-bit immediate field and therefore range from `0..15`.

## Synchronization Instructions: `LLR` And `SCR`

### `LLR`

```text
value = MEM64[Rs1]
Rd = value
reservation_addr = Rs1
reservation_valid = true
```

### `SCR`

```text
if reservation_valid && reservation_addr == Rs1:
      MEM64[Rs1] = Rd
      reservation_valid = false
      Z = 1
else:
      reservation_valid = false
      Z = 0
```

`SCR` reports success only through `Z`. Software MUST NOT rely on `C` or `S` being meaningfully updated by `SCR`. The CPU MUST preserve the other flags.

The reservation is invalidated by:

1. a successful `SCR` to the reserved address,
2. any successful memory write of any width whose byte range overlaps the reserved 8-byte location,
3. a new `LLR` that changes the reserved address.

## Privilege-Gated Instructions

From the instruction-set point of view, the privileged instructions are:

- `LSR`
- `SSR`
- `IRET`
- `STOP`

`LSR` and `SSR` are selector-gated in user mode rather than being completely unavailable. The precise rules are defined in `privileged-architecture.md`.

## Pseudocode Summary For Control-Flow Instructions

### Unconditional jump

```text
PC = post_increment_pc + pc_rel * 2
```

### Conditional LS jumps

```text
if condition(flags):
      target = post_increment_pc + pc_rel * 2
      if format == LS register:
            Rd = target
      else:
            PC = target
```

The register-form and PC-relative-form jumps therefore differ in where the target is written.

## Drift Checklist

Update this chapter when any of the following change:

1. instruction field layout,
2. opcode assignment,
3. flag behavior,
4. branch condition definitions,
5. atomic reservation semantics,
6. privilege gating of instruction execution.