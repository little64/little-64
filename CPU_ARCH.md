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

| Value | Mnemonic | Operation |
|---|---|---|
| 0 | ADD | `Rd = Rd + Rs1` |
| 1 | SUB | `Rd = Rd - Rs1` |
| 2 | AND | `Rd = Rd & Rs1` |
| 3 | OR | `Rd = Rd \| Rs1` |
| 4 | TEST | Compute `Rd - Rs1`, update flags, discard result |

All GP operations update the Zero, Carry, and Sign flags.

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
AND  Rs1, Rd             ; Rd = Rd & Rs1
OR   Rs1, Rd             ; Rd = Rd | Rs1
TEST Rs1, Rd             ; flags = Rd - Rs1 (result discarded)
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
.org 0x1000              ; set current assembly address
.word 0xABCD             ; emit a raw 16-bit word
; comment                ; semicolon starts a comment
```
