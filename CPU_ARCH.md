# Little 64

Goal: a minimal 64-bit processor, capable of running a UNIX-like OS.

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

### Function arguments
Function arguments are given in order from R10 to R6; afterwards, on the stack.

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
     11      | GP ALU
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
- `SHIFT == 3`: Also sign-extend the value ORed in to cover the upper 32-bits

This allows the assembler to build up wider immediates across multiple LDI instructions:
```asm
LDI    #0x78, R1    ; R1 = 0x78
LDI.S1 #0x56, R1   ; R1 = 0x5678
LDI.S2 #0x34, R1   ; R1 = 0x345678
LDI.S3 #0x12, R1   ; R1 = 0x12345678
```

### Format 11 — GP ALU

```
15 14 13 12 11 10  9  8  7  6  5  4  3  2  1  0
 1  1 [        OPCODE_GP        ] [   Rs1  ] [Rd ]
```

| Field | Bits | Width | Description |
|---|---|---|---|
| OPCODE_GP | [13:8] | 6 | GP opcode (see table below) |
| Rs1 | [7:4] | 4 | Source register |
| Rd | [3:0] | 4 | Destination (and second source) register |

Operation: `Rd = Rd OP Rs1` (except TEST, which does not store the result).

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

**Note on JUMP instructions:** JUMP.* are conditional MOVEs. When `Rd = R15` (the PC), the instruction behaves as a conditional branch. The same encoding is valid for any `Rd` (conditional data move). The mnemonic `JUMP.*` should be used when the intent is to branch (i.e., when `Rd = R15`).

**Note on PUSH / POP:** `Rd` is always the stack pointer and is adjusted as part of the operation. In Format 00, the value pushed or popped is the **register value** of `Rs1`. In Format 01 (PC-relative), the value pushed or popped is the **memory contents** at the PC-relative address — PUSH reads `MEM64[effective]` onto the stack, POP writes the top of the stack to `MEM64[effective]`.

## OPCODE_GP Table

| Value | Mnemonic | Operands | Operation |
|---|---|---|---|
| 0 | ADD | Rs1, Rd | `Rd = Rd + Rs1` |
| 1 | SUB | Rs1, Rd | `Rd = Rd - Rs1` |
| 2 | TEST | Rs1, Rd | Compute `Rd - Rs1`, update flags, discard result |
| 16 | AND | Rs1, Rd | `Rd = Rd & Rs1` |
| 17 | OR | Rs1, Rd | `Rd = Rd \| Rs1` |
| 18 | XOR | Rs1, Rd | `Rd = Rd ^ Rs1` |
| 20 | SLL | Rs1, Rd | `Rd = Rd << Rs1` (logical left shift) |
| 21 | SRL | Rs1, Rd | `Rd = Rd >> Rs1` (logical right shift) |
| 22 | SRA | Rs1, Rd | `Rd = Rd >> Rs1` (arithmetic right shift, sign-extends) |
| 56 | LSR | Rs1, Rd | `Rd = SR[Rs1]` (load special register by index) |
| 57 | SSR | Rs1, Rd | `SR[Rs1] = Rd` (store special register by index) |
| 60 | IRET | — | Return from interrupt: restore PC, flags, re-enable interrupts |
| 63 | STOP | — | Halt the emulator |

All arithmetic and bitwise GP operations update the Zero, Carry, and Sign flags. LSR, SSR, IRET, and STOP do not affect flags.

**SLL/SRL/SRA carry flag:** set to the last bit shifted out. Shifts by 0 leave Rd unchanged and set flags on the unshifted value; shifts by ≥ 64 produce 0 (SRA: fills with sign bit).

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
LOAD  @label, Rd         ; load from label-relative address
STORE @-4, Rd            ; store to PC-relative offset -4 instructions
JUMP.Z @label            ; branch to label if zero flag set (Rd=R15 inferred)
JUMP.Z @label, R1        ; conditional move: R1 = effective addr if zero
```

### Format 10 — Load Immediate

```asm
LDI    #255, R1          ; R1 = 255 (shift=0, clears register)
LDI.S1 #0xAB, R1        ; R1 |= 0xAB << 8
LDI.S2 #0xCD, R1        ; R1 |= 0xCD << 16
LDI.S3 #0xEF, R1        ; R1 |= 0xEF << 24
```

### Format 11 — GP ALU

```asm
ADD  Rs1, Rd             ; Rd = Rd + Rs1
SUB  Rs1, Rd             ; Rd = Rd - Rs1
TEST Rs1, Rd             ; flags = Rd - Rs1 (result discarded)
AND  Rs1, Rd             ; Rd = Rd & Rs1
OR   Rs1, Rd             ; Rd = Rd | Rs1
XOR  Rs1, Rd             ; Rd = Rd ^ Rs1
SLL  Rs1, Rd             ; Rd = Rd << Rs1  (Rs1 = shift amount)
SRL  Rs1, Rd             ; Rd = Rd >> Rs1  (logical)
SRA  Rs1, Rd             ; Rd = Rd >> Rs1  (arithmetic)
LSR  Rs1, Rd             ; Rd = SR[Rs1]    (Rs1 holds the SR index)
SSR  Rs1, Rd             ; SR[Rs1] = Rd    (Rs1 holds the SR index)
IRET                     ; return from interrupt handler
STOP                     ; halt the emulator
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
