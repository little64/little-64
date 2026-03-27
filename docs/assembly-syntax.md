# Little-64 Assembly Syntax

This document describes the syntax accepted by the Little-64 assembler. It covers source file structure, lexical rules, operand forms, instruction formats, and assembler directives. The specific instruction set is not listed here, as it is subject to change.

---

## Source file structure

A source file is a sequence of lines. Each line contains at most one of:

- a **label definition**
- an **instruction** (optionally preceded by a label on the same line)
- a **directive**
- a **comment** (or a blank line)

Lines are terminated by a newline character (`\n`). The assembler is **not** case-sensitive for register names, but mnemonics and labels are matched as written.

---

## Comments

Comments begin with a semicolon (`;`) and run to the end of the line. They may appear at the end of any line or on a line by themselves.

```
; This is a full-line comment
LOAD [R1], R0   ; This is an end-of-line comment
```

---

## Registers

Registers are written as `R` (or `r`) followed by a decimal number in the range **0–15**.

```
R0   R1   R2   ...   R14   R15
r0   r1   ...                    ; lowercase prefix is accepted
```

Register `R15` is the program counter (PC). It can be named explicitly in operands and is implicitly used as the destination by conditional jump instructions when no destination register is given.

---

## Numeric literals

Numeric literals can appear as immediates or as arguments to directives. Three bases are supported:

| Base        | Prefix        | Example       |
|-------------|---------------|---------------|
| Decimal     | none          | `42`          |
| Hexadecimal | `0x` or `0X`  | `0xFF`        |
| Binary      | `0b` or `0B`  | `0b1010`      |

When used as instruction immediates the `#` sigil must precede the value:

```
#42        ; decimal
#0xFF      ; hexadecimal
#0b1010    ; binary
```

The `#` is not required (and must not appear) in directive arguments.

---

## Labels

A label is defined by writing an identifier followed immediately by a colon (`:`). The label records the address of the next instruction or data word.

```
loop:
    ADD R1, R2
    JUMP.Z @loop
```

A label definition may share a line with an instruction:

```
start:  LDI #0, R0
```

Label names are sequences of letters, digits, underscores (`_`), and dots (`.`). They must not begin with a digit. Duplicate label definitions are an error.

---

## Instruction line structure

```
[label:] MNEMONIC[.SUFFIX] [operand [, operand ...]]
```

Commas separate operands. Leading/trailing whitespace and extra spaces between tokens are ignored.

---

## Mnemonic suffixes

### Shift suffix (LDI only)

`LDI` accepts an optional shift suffix that selects which byte-slot of the destination register the 8-bit immediate is loaded into. The suffix is written as `.SN` or simply `.N`, where `N` is **0–3**:

```
LDI     #0xFF, R0        ; shift = 0 (default)
LDI.S0  #0xFF, R0        ; explicit shift = 0
LDI.S1  #0xAB, R0        ; shift = 1
LDI.2   #0x12, R0        ; alternate form, shift = 2
LDI.S3  #0x00, R0        ; shift = 3
```

### Condition suffix (conditional jumps)

Conditional jump mnemonics embed the condition as a dot-separated suffix directly in the mnemonic name (e.g. `JUMP.Z`, `JUMP.C`). This suffix is part of the mnemonic, not a modifier applied at the syntax level.

---

## Operand forms

### Register operand

A plain register name: `R0` … `R15`.

### Immediate operand

A `#`-prefixed numeric literal: `#42`, `#0x1F`, `#0b11001111`.
Value must fit in 8 bits (0–255) for `LDI`.

### Register-indirect address `[Rs1]` / `[Rs1+offset]`

Used by load/store instructions with register-relative addressing (format LS-REG):

```
[R2]        ; base register, offset = 0
[R2+2]      ; base register + 2-byte offset
[R2+4]      ; base register + 4-byte offset
[R2+6]      ; base register + 6-byte offset
```

The offset, when present, must be a bare decimal integer. Only the values **0, 2, 4, and 6** are valid (word-aligned steps). The full instruction syntax is:

```
MNEMONIC [Rs1+offset], Rd
MNEMONIC [Rs1], Rd          ; offset defaults to 0
```

### PC-relative address `@label` / `@±N`

Used by load/store and jump instructions with PC-relative addressing (format LS-PCREL):

```
@loop           ; resolve label to a PC-relative offset
@+3             ; explicit positive offset (in instruction units)
@-5             ; explicit negative offset (in instruction units)
```

Offsets are counted in **instruction units** (each instruction is 2 bytes), relative to the instruction *following* the current one (i.e. PC + 2). The encodable range is **−32 to +31** instruction units.

The full instruction syntax is:

```
MNEMONIC @label, Rd
MNEMONIC @±N, Rd
```

---

## Instruction format summary

The assembler recognises four instruction formats. The format is inferred automatically from the mnemonic and the first operand token.

### GP — General-purpose ALU instructions

```
MNEMONIC                    ; 0-register form
MNEMONIC Rd                 ; 1-register form
MNEMONIC Rs1, Rd            ; 2-register form
```

### LDI — Load immediate

```
LDI[.SN]  #imm8, Rd
```

`imm8` is an 8-bit unsigned value (0–255). `SN` is an optional shift index 0–3.

### LS-REG — Load/store, register-relative

```
MNEMONIC [Rs1],       Rd
MNEMONIC [Rs1+offset], Rd
```

Also used for the bare-register jump form (see below).

### LS-PCREL — Load/store/jump, PC-relative

```
MNEMONIC @label,  Rd
MNEMONIC @±N,     Rd
```

---

## Jump forms

### Unconditional jump — `JUMP` pseudo-instruction

`JUMP` is a pseudo-instruction that encodes as `MOVE` with `R15` as the implicit destination. It provides a readable unconditional branch syntax without requiring an explicit `MOVE … R15`.

```
JUMP @loop              ; PC-relative, Rd = R15 (implicit)
JUMP @+3                ; PC-relative numeric offset, Rd = R15
JUMP R3                 ; register-indirect [R3+0], Rd = R15
JUMP [R3+2], R15        ; bracket form, explicit Rd
```

### Conditional jumps — `JUMP.*`

Conditional jump mnemonics (those of the form `JUMP.*`) are LS-class instructions and accept the same syntactic forms as `JUMP`. When no destination register is given, `R15` (the PC) is used implicitly.

```
JUMP.Z @loop            ; PC-relative, Rd = R15 (implicit)
JUMP.Z @loop, R15       ; PC-relative, Rd explicit
JUMP.Z @+2              ; PC-relative numeric offset, Rd = R15
JUMP.Z R3               ; register-indirect, offset = 0, Rd = R15
JUMP.Z [R3], R15        ; bracket form, same encoding
JUMP.Z R3, R0           ; register-indirect, Rd = R0 (unusual)
```

---

## Assembler directives

Directives begin with a dot and are not emitted as instructions.

### `.org <address>`

Sets the **current assembly address**. Subsequent instructions and data words are placed starting at `<address>`. The address is a bare numeric literal (no `#`).

```
.org 0x0200
```

### `.word <value>`

Emits a single **16-bit word** of data at the current address. The value is a bare numeric literal (no `#`). `.word` directives are always appended *after* all instructions in the output, in the order they appear in the source.

```
data_table:
    .word 0xBEEF
    .word 42
```

---

## Two-pass assembly

The assembler works in two passes:

1. **Pass 1** — scans labels and instructions to build the symbol table and record instruction addresses. No output is produced.
2. **Pass 2** — encodes each instruction, resolving label references. `.word` data words are appended after all instructions.

Because labels are resolved in pass 1, **forward references** in PC-relative operands (`@label`) are fully supported.

---

## Example

```
.org 0x0100

start:
    LDI     #0,    R0      ; R0 = 0
    LDI.S1  #0xFF, R1      ; load 0xFF into byte-slot 1 of R1
    ADD     R0, R2          ; R2 = R0 + R2

loop:
    INC_LOAD [R1], R3       ; load and post-increment
    TEST     R3, R3
    JUMP.Z   @done          ; branch if zero flag set
    JUMP.Z   @loop          ; else loop

done:
    STOP

table:
    .word 0x0001
    .word 0x0002
```
