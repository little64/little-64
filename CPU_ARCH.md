# Little 64

Goal: a minimal 64-bit processor, capable of running a UNIX-like OS.

## Quick Reference — Where Instructions Are Defined

To find or modify instruction definitions, look at these files:

| Task | File(s) | Notes |
|---|---|---|
| **View/modify opcodes and mnemonics** | `arch/opcodes_ls.def`, `arch/opcodes_gp.def` | X-macro files; includes both LS and GP instruction definitions |
| **View opcode values** | `arch/opcodes.hpp` | Generated enum (via `.def` files); includes `GP::Encoding` type |
| **Implement instruction behavior** | `emulator/cpu.cpp` | CPU execution logic: `_dispatchLSReg()`, `_dispatchLSPCRel()`, `_dispatchGP()` |
| **Assembler support** | `assembler/assembler.cpp`, `assembler/encoder.cpp` | Mnemonic-to-encoding mapping, operand parsing, validation |
| **Disassembler support** | `disassembler/disassembler.cpp` | Decoding and human-readable output |
| **Test instructions** | `tests/test_cpu_*.cpp` | CPU behavior tests (organized by category: gp, ldi, memory, jumps, special, integration) |
| **Device framework / memory map wiring** | `emulator/device.hpp`, `emulator/machine_config.hpp`, `emulator/machine_config.cpp` | Declarative registration of RAM/ROM/MMIO devices and lifecycle hooks |
| **Device conformance tests** | `tests/test_devices.cpp` | MMIO read/write/reset behavior checks |
| **Assembly examples** | `asm/test_program.asm` | Example assembly code |
| **Documentation** | `docs/assembly-syntax.md` | Assembly language syntax guide |

**Common workflows:**
- **Add a new LS instruction:** Update `arch/opcodes_ls.def`, then add case to `_dispatchLSReg()` or `_dispatchLSPCRel()` in `emulator/cpu.cpp`
- **Add a new GP instruction:** Update `arch/opcodes_gp.def` (set encoding to NONE/RD/RS1_RD/IMM4_RD), then add case to `_dispatchGP()` in `emulator/cpu.cpp`
- **Add a pseudo-instruction:** Modify `assembler/assembler.cpp` pseudo_table only (no other changes needed)

## Registers

| Register | Role |
|---|---|
| R0 | Always zero; writes are discarded |
| R1–R5 | General purpose, caller saved |
| R6-R10 | General purpose, callee saved |
| R11–R12 | Address registers, callee saved |
| R13 | Stack pointer (SP) |
| R14 | Link register (LR) |
| R15 | Program counter (PC) |

## Calling Convention

### Function arguments
Function arguments are passed in registers and on the stack:
- **Arguments 0–4:** Passed in registers R10, R9, R8, R7, R6 (in order)
- **Arguments 5+:** Passed on the stack (oldest arguments pushed first)

Registers R1–R5 are **caller-saved** and must be preserved by the caller if their values are needed after a function call.

### Return values
- **Single return value (≤64 bits):** Returned in **R1**
- **Pair return value (128 bits):** Low 64 bits in **R1**, high 64 bits in **R2**
- **Larger return values:** By reference (caller allocates, passes pointer as first argument)

### Stack
- **Stack grows downward** — SP decreases when allocating space
- **R13 = SP (stack pointer):** Points to the top of the stack (lowest allocated address)
- **Allocation:** `SP -= size` (e.g., `PUSH Rs, R13` decrements SP by 8)
- **Deallocation:** `SP += size` (e.g., `POP Rs, R13` increments SP by 8)

## Flags Register

| Bit | Name | Set when |
|---|---|---|
| 0 | Zero (Z) | Result == 0 |
| 1 | Carry (C) | Unsigned overflow or borrow |
| 2 | Sign (S) | Result MSB == 1 (negative) |

`JUMP.GT` fires when Z=0 and S=0. `JUMP.LT` fires when S=1.

## Instruction Format

All instructions are 16 bits. Bits `[15:14]` select the format:

```
Bits [15:14] | Format
     00      | LS Register
     01      | LS PC-Relative
     10      | Load Immediate (LDI)
  11      | Extended (GP or unconditional JUMP)
```

### Format 00 — LS Register

```
15 14 13 12 11 10  9  8  7  6  5  4  3  2  1  0
 0  0 [  OPCODE_LS  ] [OFF] [    Rs1    ] [   Rd  ]
```

| Field | Bits | Width | Description |
|---|---|---|---|
| OPCODE_LS | [13:10] | 4 | LS opcode (see table below) |
| OFFSET | [9:8] | 2 | Byte offset = field × 2 (→ 0, 2, 4, 6) |
| Rs1 | [7:4] | 4 | Base address register |
| Rd | [3:0] | 4 | Destination (loads) or source (stores) |

Effective address = `Rs1 + OFFSET × 2`

### Format 01 — LS PC-Relative

Format 01 has two sub-encodings depending on the opcode.

#### Sub-layout A — Non-JUMP opcodes (LOAD, STORE, PUSH, POP, MOVE, BYTE\_LOAD, BYTE\_STORE, SHORT\_LOAD, SHORT\_STORE, WORD\_LOAD, WORD\_STORE)

```
15 14 13 12 11 10  9  8  7  6  5  4  3  2  1  0
 0  1 [  OPCODE_LS  ] [    PC-REL OFFSET   ] [Rd ]
```

| Field | Bits | Width | Description |
|---|---|---|---|
| OPCODE_LS | [13:10] | 4 | LS opcode |
| PC-REL | [9:4] | 6 | Signed offset; byte offset = PC-REL × 2 |
| Rd | [3:0] | 4 | Destination (loads) or source (stores) |

Effective address = `PC_next + PC-REL × 2` (PC_next = address of following instruction)

#### Sub-layout B — JUMP.\* opcodes (opcodes 11–15: JUMP.Z, JUMP.C, JUMP.S, JUMP.GT, JUMP.LT)

```
15 14 13 12 11 10  9  8  7  6  5  4  3  2  1  0
 0  1 [  OPCODE_LS  ] [         PC-REL OFFSET        ]
```

| Field | Bits | Width | Description |
|---|---|---|---|
| OPCODE_LS | [13:10] | 4 | JUMP.\* opcode (11–15) |
| PC-REL | [9:0] | 10 | Signed offset; byte offset = PC-REL × 2 |

Rd is always R15 (the PC) — there is no Rd field. Bits [3:0] are the low 4 bits of the 10-bit offset.

Effective address = `PC_next + PC-REL × 2`

Branch range: **±511 instructions** (±1022 bytes) relative to the following instruction.

### Format 10 — Load Immediate (LDI)

```
15 14 13 12 11 10  9  8  7  6  5  4  3  2  1  0
 1  0 [SH]  [        IMM8        ] [    Rd     ]
```

| Field | Bits | Width | Description |
|---|---|---|---|
| SHIFT | [13:12] | 2 | Byte shift amount (0–3) |
| IMM8 | [11:4] | 8 | 8-bit immediate value |
| Rd | [3:0] | 4 | Destination register |

Behavior:
- `SHIFT == 0`: `Rd = IMM8` (clears Rd, then loads the immediate)
- `SHIFT > 0`: `Rd |= (IMM8 << (SHIFT × 8))` (OR into existing Rd value)
- `SHIFT == 3` with MSB set: Sign-extend from bit 31 upward if IMM8 bit 7 = 1
  - If bit 7 of IMM8 is set: `Rd |= 0xFFFFFFFF_00000000` (fill bits [63:32] with 1s)
  - This converts a signed 32-bit value to a 64-bit sign-extended value

This allows building 32-bit constants:
```asm
LDI    #0x78, R1    ; R1 = 0x78
LDI.S1 #0x56, R1   ; R1 = 0x5678
LDI.S2 #0x34, R1   ; R1 = 0x345678
LDI.S3 #0x12, R1   ; R1 = 0x12345678  (bit 7 of 0x12 is 0, no sign extension)
```

For sign-extended 64-bit values from negative 32-bit constants:
```asm
LDI    #0x00, R1    ; R1 = 0x00
LDI.S1 #0x00, R1   ; R1 = 0x0000
LDI.S2 #0x00, R1   ; R1 = 0x000000
LDI.S3 #0x80, R1   ; R1 = 0xFFFFFFFF80000000  (bit 7 of 0x80 is 1, sign extend)
```

Use `LDI64` pseudo-instruction for convenient 64-bit constant loading.

### Format 11 — Extended

Format 11 has two sub-encodings selected by bit 13.

#### Sub-layout A — GP ALU (`110`)

```
15 14 13 12 11 10  9  8  7  6  5  4  3  2  1  0
 1  1  0 [    OPCODE_GP    ] [   Rs1  ] [Rd ]
```

| Field | Bits | Width | Description |
|---|---|---|---|
| OPCODE_GP | [12:8] | 5 | GP opcode (see OPCODE_GP table below) |
| Rs1 | [7:4] | 4 | Register (register-form) or Immediate (immediate-form); see table |
| Rd | [3:0] | 4 | Destination (and second source) register |

**Operand encoding:** The meaning of the Rs1 field depends on the opcode:
- **Register-form** (ADD, SUB, TEST, AND, OR, XOR, SLL, SRL, SRA, LSR, SSR, IRET, STOP): Rs1 = register index (0–15)
  - Operation: `Rd = Rd OP Rs1` (or appropriate register-indexed behavior)
- **Immediate-form** (SLLI, SRLI, SRAI): Rs1 = 4-bit immediate (0–15)
  - Operation: `Rd = Rd OP #Rs1` (shift by the literal count in Rs1)
  - The assembler validates that the immediate is in range [0–15]

#### Sub-layout B — Unconditional PC-Relative JUMP (`111`)

```
15 14 13 12 11 10  9  8  7  6  5  4  3  2  1  0
 1  1  1 [               PC-REL OFFSET               ]
```

| Field | Bits | Width | Description |
|---|---|---|---|
| PC-REL | [12:0] | 13 | Signed offset; byte offset = PC-REL × 2 |

Destination is always R15 (the PC).

Effective address = `PC_next + PC-REL × 2`

Branch range: **±4095 instructions** (±8190 bytes) relative to the following instruction.

## OPCODE_LS Table

| Value | Mnemonic | Description |
|---|---|---|
| 0 | LOAD | `Rd = MEM64[addr]` |
| 1 | STORE | `MEM64[addr] = Rd` |
| 2 | PUSH | Format 00: `Rd -= 8; MEM64[Rd] = Rs1` — Format 01: `Rd -= 8; MEM64[Rd] = MEM64[effective]` |
| 3 | POP | Format 00: `Rs1 = MEM64[Rd]; Rd += 8` — Format 01: `MEM64[effective] = MEM64[Rd]; Rd += 8` |
| 4 | MOVE | `Rd = addr` (address value itself, no memory access) |
| 5 | BYTE_LOAD | `Rd = (uint8_t) MEM8[addr]` (zero-extended) |
| 6 | BYTE_STORE | `MEM8[addr] = Rd[7:0]` |
| 7 | SHORT_LOAD | `Rd = (uint16_t) MEM16[addr]` (zero-extended) |
| 8 | SHORT_STORE | `MEM16[addr] = Rd[15:0]` |
| 9 | WORD_LOAD | `Rd = (uint32_t) MEM32[addr]` (zero-extended) |
| 10 | WORD_STORE | `MEM32[addr] = Rd[31:0]` |
| 11 | JUMP.Z | If Zero flag set: `Rd = addr` |
| 12 | JUMP.C | If Carry flag set: `Rd = addr` |
| 13 | JUMP.S | If Sign flag set: `Rd = addr` |
| 14 | JUMP.GT | If Z=0 and S=0: `Rd = addr` |
| 15 | JUMP.LT | If S=1: `Rd = addr` |

**Note on JUMP instructions:** In Format 00 (register), JUMP.* are conditional MOVEs. The same encoding is valid for any `Rd` (conditional data move), and `Rd = R15` causes a conditional branch. In Format 01 (PC-relative), JUMP.* always target R15 (the PC) with a 10-bit signed offset — no explicit `Rd` field exists. The `JUMP.*` mnemonic should be used when the intent is to branch.

**Note on PUSH / POP:** `Rd` is always the stack pointer and is adjusted as part of the operation. In Format 00, the value pushed or popped is the **register value** of `Rs1`. In Format 01 (PC-relative), the value pushed or popped is the **memory contents** at the PC-relative address — PUSH reads `MEM64[effective]` onto the stack, POP writes the top of the stack to `MEM64[effective]`.

## OPCODE_GP Table

| Value | Mnemonic | Encoding | Operands | Operation |
|---|---|---|---|---|
| 0 | ADD | register-form | Rs1, Rd | `Rd = Rd + Rs1` |
| 1 | SUB | register-form | Rs1, Rd | `Rd = Rd - Rs1` |
| 2 | TEST | register-form | Rs1, Rd | Compute `Rd - Rs1`, update flags, discard result |
| 16 | AND | register-form | Rs1, Rd | `Rd = Rd & Rs1` |
| 17 | OR | register-form | Rs1, Rd | `Rd = Rd \| Rs1` |
| 18 | XOR | register-form | Rs1, Rd | `Rd = Rd ^ Rs1` |
| 20 | SLL | register-form | Rs1, Rd | `Rd = Rd << Rs1` (logical left shift, shift count in Rs1) |
| 21 | SRL | register-form | Rs1, Rd | `Rd = Rd >> Rs1` (logical right shift, shift count in Rs1) |
| 22 | SRA | register-form | Rs1, Rd | `Rd = Rd >> Rs1` (arithmetic right shift, shift count in Rs1) |
| 23 | SLLI | immediate-form | #N, Rd | `Rd = Rd << N` (left shift by 4-bit immediate, N ∈ 0–15) |
| 24 | SRLI | immediate-form | #N, Rd | `Rd = Rd >> N` (logical right shift by 4-bit immediate, N ∈ 0–15) |
| 25 | SRAI | immediate-form | #N, Rd | `Rd = Rd >> N` (arithmetic right shift by 4-bit immediate, N ∈ 0–15) |
| 28 | LSR | register-form | Rs1, Rd | `Rd = SR[Rs1]` (load special register by index in Rs1) |
| 29 | SSR | register-form | Rs1, Rd | `SR[Rs1] = Rd` (store special register by index in Rs1) |
| 30 | IRET | — | — | Return from interrupt: restore PC, flags, re-enable interrupts |
| 31 | STOP | — | — | Halt the emulator |

**Encoding column:** Register-form instructions use the Rs1 field as a register index (0–15). Immediate-form instructions (SLLI/SRLI/SRAI) use the Rs1 field as a 4-bit literal value (0–15). The assembler automatically selects the encoding based on the mnemonic.

**Flags:** All arithmetic and bitwise operations update the Zero, Carry, and Sign flags. LSR, SSR, IRET, and STOP do not affect flags.

**Shift instructions (SLL/SRL/SRA):** The carry flag is set to the last bit shifted out. Shifts by 0 leave Rd unchanged and set flags on the unshifted value; shifts by ≥ 64 produce 0 (SRA fills with the sign bit).

**Immediate shift instructions (SLLI/SRLI/SRAI):** Provide fast shifts by constant amounts (0–15). For larger shift counts, use the register variants (SLL, SRL, SRA).

## Assembler Syntax

### Format 00 — LS Register

```asm
LOAD  [Rs1], Rd          ; offset = 0
LOAD  [Rs1+N], Rd        ; offset = N bytes (N must be 0, 2, 4, or 6)
STORE [Rs1+2], Rd        ; Rd is the source for stores
PUSH  Rs1, Rd            ; Rd -= 8; MEM64[Rd] = Rs1  (Rd is the stack pointer)
POP   Rs1, Rd            ; Rs1 = MEM64[Rd]; Rd += 8  (Rd is the stack pointer)
```

### Format 01 — LS PC-Relative

```asm
LOAD  @label, Rd         ; load from label-relative address (6-bit offset, ±31 instructions)
STORE @-4, Rd            ; store to PC-relative offset -4 instructions
JUMP.Z @label            ; branch to label if zero flag set (10-bit offset, ±511 instructions)
JUMP.Z @label, R1        ; Rd is ignored; always branches to R15 (PC)
```

### Format 10 — Load Immediate

```asm
LDI    #255, R1          ; R1 = 255 (shift=0, clears register)
LDI.S1 #0xAB, R1        ; R1 |= 0xAB << 8
LDI.S2 #0xCD, R1        ; R1 |= 0xCD << 16
LDI.S3 #0xEF, R1        ; R1 |= 0xEF << 24
```

### Format 11 — GP ALU

#### Register-form instructions

```asm
ADD  Rs1, Rd             ; Rd = Rd + Rs1
SUB  Rs1, Rd             ; Rd = Rd - Rs1
TEST Rs1, Rd             ; flags = Rd - Rs1 (result discarded)
AND  Rs1, Rd             ; Rd = Rd & Rs1
OR   Rs1, Rd             ; Rd = Rd | Rs1
XOR  Rs1, Rd             ; Rd = Rd ^ Rs1
SLL  Rs1, Rd             ; Rd = Rd << Rs1       (Rs1 = register with shift amount)
SRL  Rs1, Rd             ; Rd = Rd >> Rs1       (logical right shift)
SRA  Rs1, Rd             ; Rd = Rd >> Rs1       (arithmetic right shift)
LSR  Rs1, Rd             ; Rd = SR[Rs1]         (Rs1 = SR index)
SSR  Rs1, Rd             ; SR[Rs1] = Rd         (Rs1 = SR index)
IRET                     ; return from interrupt handler
STOP                     ; halt the emulator
```

#### Immediate-form instructions

```asm
SLLI #5, Rd              ; Rd = Rd << 5         (left shift by 4-bit literal, 0–15)
SRLI #7, Rd              ; Rd = Rd >> 7         (logical right shift by 4-bit literal)
SRAI #3, Rd              ; Rd = Rd >> 3         (arithmetic right shift by 4-bit literal)
```

**Note:** SLLI, SRLI, and SRAI use the Rs1 field in the instruction encoding as a 4-bit immediate (the shift count), not as a register index. The assembler validates the immediate is in range [0–15].

### Format 11 — Unconditional JUMP

```asm
JUMP @label              ; branch to label (13-bit PC-relative offset, ±4095 instructions)
JUMP @-4                 ; branch to PC-relative offset -4 instructions
```

### JUMP.* bare register form (Format 00)

```asm
JUMP.Z R1                ; if Z: PC = R1          (shorthand, offset=0, Rd=R15)
JUMP.Z R1, R2            ; if Z: R2 = R1          (shorthand, offset=0, explicit Rd)
JUMP.Z [R1+4], R15       ; if Z: PC = R1 + 4      (full form with offset)
```

### Other syntax

```asm
label:                   ; define a label at current address
.org 0x1000              ; set current assembly address (gaps are zero-filled)
.byte  0xAB              ; emit 1 byte
.short 0xABCD            ; emit 2 bytes (little-endian)
.int   0xABCDEF01        ; emit 4 bytes (little-endian)
.long  0xABCDEF0123456789 ; emit 8 bytes (little-endian)
.ascii  "hello"          ; emit raw bytes (no null terminator)
.asciiz "hello"          ; emit bytes followed by a null terminator
; comment                ; semicolon starts a comment
```

## Special Registers

Special registers are accessed by index using `LSR` (load) and `SSR` (store). The index is passed in Rs1; the value is in Rd.

| Index | Name | Description |
|---|---|---|
| 0 | `cpu_control` | CPU control flags (see below) |
| 1 | `interrupt_table_base` | Base address of the interrupt handler table (64 × 8-byte entries) |
| 2 | `interrupt_mask` | Bit mask of unmasked interrupts; bit N = 1 enables interrupt N |
| 3 | `interrupt_states` | Pending interrupt bits; writing bit N = 1 asserts interrupt N from software |
| 4 | `interrupt_epc` | Saved PC on interrupt entry (return address) |
| 5 | `interrupt_eflags` | Saved flags on interrupt entry |
| 6 | `interrupt_except` | Exception number written on hardware exception entry |
| 7–10 | `interrupt_data[0–3]` | Scratch registers for interrupt handlers (not used by hardware) |

### `cpu_control` bit fields

| Bit(s) | Name | Description |
|---|---|---|
| 0 | IE | Interrupt Enable — set to allow interrupts to be taken |
| 1 | IN | In Interrupt — set by hardware on interrupt entry, cleared by IRET |
| 2–7 | N | Currently-handled interrupt number (valid when IN=1) |

## Interrupt System

### Interrupt table

The interrupt table is an array of 64 × 8-byte handler addresses located at `interrupt_table_base`. Entry N contains the absolute address of the handler for interrupt N. A zero entry means no handler is registered and the interrupt is silently dropped.

### Taking an interrupt

On each cycle, after the current instruction executes, the CPU checks:

```
pending = interrupt_states & interrupt_mask
```

If any bit is set and IE=1, the lowest-numbered pending interrupt is taken:

1. IE is cleared and IN is set in `cpu_control`; the interrupt number is stored in N.
2. The current PC (address of the next instruction to execute) is saved to `interrupt_epc`.
3. The current flags are saved to `interrupt_eflags`.
4. PC is set to the handler address from the interrupt table.

Interrupts are **level-triggered**: `interrupt_states` is not automatically cleared when an interrupt is taken. The handler is responsible for clearing the relevant bit in `interrupt_states` (via `SSR 3, Rd`) before returning, otherwise the interrupt will re-fire immediately after `IRET`.

Hardware exceptions set `interrupt_except` to the exception number in addition to the steps above.

### Priority

Lower interrupt numbers have higher priority. A regular interrupt (from `interrupt_states`) cannot preempt a running handler. A hardware exception can preempt a handler only if its interrupt number is strictly lower (higher priority) than the one currently being handled.

### Returning from a handler (IRET)

`IRET` atomically:
1. Restores PC from `interrupt_epc`.
2. Restores flags from `interrupt_eflags`.
3. Clears IN and re-enables IE in `cpu_control`.

### Minimal interrupt setup

```asm
; 1. Point interrupt_table_base at a table of 64-bit handler addresses
LDI.S0 <lo(table)>, R1
LDI.S1 <hi(table)>, R1
LDI.S0 1, R2            ; SR index 1 = interrupt_table_base
SSR R2, R1

; 2. Unmask the desired interrupt(s) in interrupt_mask
LDI.S0 <mask_lo>, R3    ; build a bitmask of interrupts to enable
LDI.S0 2, R2            ; SR index 2 = interrupt_mask
SSR R2, R3

; 3. Enable interrupts globally
LDI.S0 0, R2            ; SR index 0 = cpu_control
LSR R2, R1              ; read current cpu_control
LDI.S0 1, R4
OR  R4, R1              ; set IE bit
SSR R2, R1

; Handler skeleton:
handler:
    ; ... do work ...
    ; Clear the interrupt's pending bit before returning
    LDI.S0 3, R1         ; SR index 3 = interrupt_states
    LSR R1, R2
    ; (clear the relevant bit in R2, then:)
    SSR R1, R2
    IRET
```
