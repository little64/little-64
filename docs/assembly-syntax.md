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

Three symbolic aliases are also recognised (case-insensitive):

| Alias | Register | Role |
|-------|----------|------|
| `SP`  | R13      | Stack pointer |
| `LR`  | R14      | Link register |
| `PC`  | R15      | Program counter |

Register `R15` (PC) is implicitly used as the destination by jump instructions and by `MOVE` when no destination is given.

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

`MOVE`, `JUMP`, `PUSH`, and `POP` do **not** use the bracket form (see their sections below).

### Register address `Rs1` / `Rs1+offset`

Used by `MOVE` and `JUMP` for register-relative address computation (format LS-REG), without implying a memory dereference:

```
R2          ; base register, offset = 0
R2+2        ; base register + 2-byte offset
```

```
MOVE Rs1, Rd
MOVE Rs1+offset, Rd
```

### PC-relative address `@label` / `@±N`

Used by load/store and jump instructions with PC-relative addressing (format LS-PCREL):

```
@loop           ; resolve label to a PC-relative offset
@+3             ; explicit positive offset (in instruction units)
@-5             ; explicit negative offset (in instruction units)
```

Offsets are counted in **instruction units** (each instruction is 2 bytes), relative to the instruction *following* the current one (i.e. PC + 2).

The encodable range depends on the opcode:
- Non-JUMP opcodes (LOAD, STORE, PUSH, POP, MOVE, BYTE\_LOAD, etc.): **−32 to +31** instruction units (6-bit signed field).
- JUMP.\* opcodes (conditional branches): **−511 to +511** instruction units (10-bit signed field).

The full instruction syntax is:

```
MNEMONIC @label, Rd
MNEMONIC @±N, Rd
```

For JUMP.\* in PC-relative form, the `Rd` operand is accepted but ignored — the destination is always R15 (the PC).

---

## Instruction format summary

The assembler recognises four instruction formats. The format is inferred automatically from the mnemonic and the first operand token.

### GP — General-purpose ALU instructions

```
MNEMONIC                    ; 0-register form  (e.g. IRET, STOP)
MNEMONIC Rd                 ; 1-register form  (reserved for future use)
MNEMONIC Rs1, Rd            ; 2-register form  (e.g. ADD, SLL)
MNEMONIC #N, Rd             ; immediate form   (e.g. SLLI, SRLI, SRAI)
```

The **immediate form** encodes a 4-bit literal `N` (0–15) in the Rs1 field of the instruction word. It is used by the immediate-shift instructions:

```
SLLI #N, Rd      ; Rd = Rd << N   (logical left,  N ∈ 0–15)
SRLI #N, Rd      ; Rd = Rd >> N   (logical right, N ∈ 0–15)
SRAI #N, Rd      ; Rd = Rd >> N   (arithmetic right, sign-extends, N ∈ 0–15)
```

For shift counts 16–63 use the register-operand variants `SLL`, `SRL`, `SRA`.

### LDI — Load immediate

```
LDI[.SN]  #imm8, Rd
LD[.SN]   #imm8, Rd   ; LD is an alias for LDI when the first operand is an immediate
```

`imm8` is an 8-bit unsigned value (0–255). `SN` is an optional shift index 0–3.

### LS-REG — Load/store, register-relative

```
MNEMONIC [Rs1],        Rd
MNEMONIC [Rs1+offset], Rd
```

`MOVE`, `JUMP`, `PUSH`, and `POP` use a bracket-free register form instead (see their sections below).

### LS-PCREL — Load/store/jump, PC-relative

```
MNEMONIC @label,  Rd
MNEMONIC @±N,     Rd
```

---

## Subroutine pseudo-instructions

Three pseudo-instructions provide a structured call/return mechanism. Each expands to one or more real instructions at assembly time; no new opcodes are needed.

### `JAL @target` — Jump and link (2 instructions)

```
MOVE R15+2, R14    ; LR = return address (instruction after the JUMP)
JUMP @target       ; jump to target
```

Sets the link register (R14 / LR) to the address immediately following the `JAL` and then jumps. Use `JAL` when calling a leaf function or when the current link register does not need to be preserved.

```
JAL @my_function
; R14 = return address here
```

### `CALL @target` — Subroutine call (4 instructions)

```
PUSH R14           ; save caller's LR on the stack
MOVE R15+2, R14    ; LR = address of POP below (the return address)
JUMP @target       ; jump to target
POP R14            ; ← return address — restores caller's LR on return
```

The `POP R14` instruction is **embedded at the return address**. When the callee executes `RET` (`MOVE R14, R15`), control jumps to this `POP R14`, which restores the caller's original link register before continuing. The stack is balanced on return and `R14` is transparent to the caller.

This self-embedding pattern makes `CALL`/`RET` fully composable: nested calls work correctly without any manual push/pop around the call site.

```
CALL @some_function
; R14 is automatically restored here, stack is balanced
```

### `RET` — Return from subroutine (1 instruction)

```
MOVE R14, R15      ; PC = LR — jump to the link register
```

Returns to the address in `R14`. When paired with `CALL`, control lands on the `POP R14` embedded by the caller, restoring the caller's link register. When paired with `JAL`, returns directly to the instruction after the `JAL`.

### Calling convention summary

| Instruction | Preserves LR? | Stack effect | Paired with |
|-------------|---------------|--------------|-------------|
| `JAL`       | No            | None         | `RET`       |
| `CALL`      | Yes (auto)    | Balanced     | `RET`       |
| `RET`       | —             | None         | `JAL`/`CALL` |

### Example: nested calls

```
main:
    JAL  @foo          ; R14 = ret_A, no stack push
    ; ... continues here after foo returns ...

foo:
    CALL @bar          ; saves R14, jumps bar; POP R14 at return addr
    ; R14 restored automatically when bar returns via RET
    RET                ; return to main (MOVE R14, R15)

bar:
    ; ... leaf function ...
    RET                ; MOVE R14, R15 → lands on POP R14 in foo's CALL
```

---

## Linker/ELF directives and relocatable output

The assembler supports generating relocatable ELF object files via `assembleElf()` and the command-line option `--elf`.

### `.global` / `.extern`

- `.global <symbol>` marks a symbol as exported.
- `.extern <symbol>` declares an undefined symbol to be resolved by the linker.

```
.global start
start: STOP

.extern ext_fn
JUMP @ext_fn
```

### `.long <value|symbol>`

- `.long <immediate>` emits an 8-byte constant value.
- `.long <symbol>` emits a relocation entry (ABS64) in ELF object mode.

```
.long 0x123456789ABCDEF0
.long start
.long ext_fn
```

### PC-relative relocations for ELF

PC-relative label operands generate relocations in ELF object output:

- `JUMP @label` and all non-JUMP PC-relative instructions generate `PCREL6` relocations. The linker fills in the final 6-bit offset when sections are laid out.
- `JUMP.Z @label`, `JUMP.C @label`, etc. (conditional branches) generate `PCREL10` relocations. The linker fills in the final 10-bit offset.

---

## LD / ST pseudo-instructions

`LD` and `ST` are pseudo-instructions that dispatch to the appropriate underlying instruction based on width suffix and operand type. They are intended as a more familiar alternative to the explicit mnemonic names.

### LD — unified load

| Form | Resolves to | Width |
|------|-------------|-------|
| `LD #imm8, Rd` | `LDI #imm8, Rd` | immediate (8-bit slot) |
| `LD[.SN] #imm8, Rd` | `LDI[.SN] #imm8, Rd` | immediate with byte-slot shift |
| `LD …` | `LOAD …` | 64-bit memory load |
| `LD.B …` | `BYTE_LOAD …` | 8-bit memory load |
| `LD.S …` / `LD.W …` | `SHORT_LOAD …` | 16-bit memory load |
| `LD.I …` | `WORD_LOAD …` | 32-bit memory load |

The distinction between immediate and memory forms is made automatically: if the first operand begins with `#`, the instruction resolves to `LDI`; otherwise it resolves to the appropriate memory-load mnemonic.

```
LD   #42, R1            ; LDI #42, R1
LD.S1 #0xAB, R1         ; LDI.S1 #0xAB, R1  (shift = 1)
LD   [R3], R4           ; LOAD [R3], R4
LD.B [R3], R4           ; BYTE_LOAD [R3], R4
LD.S [R3+2], R4         ; SHORT_LOAD [R3+2], R4
LD.W [R3+2], R4         ; SHORT_LOAD [R3+2], R4  (alias for .S)
LD.I [R3], R4           ; WORD_LOAD [R3], R4
LD   @label, R4         ; LOAD @label, R4
```

### ST — unified store

| Form | Resolves to | Width |
|------|-------------|-------|
| `ST …` | `STORE …` | 64-bit memory store |
| `ST.B …` | `BYTE_STORE …` | 8-bit memory store |
| `ST.S …` / `ST.W …` | `SHORT_STORE …` | 16-bit memory store |
| `ST.I …` | `WORD_STORE …` | 32-bit memory store |

```
ST   [R3], R4           ; STORE [R3], R4
ST.B [R3], R4           ; BYTE_STORE [R3], R4
ST.S [R3+2], R4         ; SHORT_STORE [R3+2], R4
ST.I [R3], R4           ; WORD_STORE [R3], R4
```

---

## MOVE

`MOVE` computes an effective address (adds an optional byte offset to a register) and places the result in `Rd`. It never reads or writes memory. In the register form, the source is written without brackets to distinguish it from memory-accessing instructions.

```
MOVE Rs1, Rd            ; Rd = Rs1
MOVE Rs1+N, Rd          ; Rd = Rs1 + N  (N must be 0, 2, 4, or 6)
MOVE @label, Rd         ; Rd = PC-relative address of label
MOVE @±N, Rd            ; Rd = PC-relative numeric offset
```

When `Rd` is `R15` (or `PC`), `MOVE` acts as an unconditional jump. Use `JUMP` as a more readable alias for that case.

---

## Jump forms

### Unconditional jump — `JUMP` pseudo-instruction

`JUMP` is a pseudo-instruction that encodes as `MOVE` with `R15` as the implicit destination.

```
JUMP @loop              ; PC-relative, Rd = R15 (implicit)
JUMP @+3                ; PC-relative numeric offset, Rd = R15
JUMP R3                 ; Rd = R3, Rd = R15 (implicit)
JUMP R3+2, R15          ; Rd = R3 + 2, explicit Rd
```

### Conditional jumps — `JUMP.*`

Conditional jump mnemonics (those of the form `JUMP.*`) are LS-class instructions. In PC-relative form (Format 01), they use a **10-bit signed offset** (range ±511 instructions) and the destination is always R15 (the PC) — no explicit `Rd` field exists in the encoding. In register form (Format 00), any `Rd` is valid.

```
JUMP.Z @loop            ; PC-relative, Rd = R15 (implicit), ±511 instruction range
JUMP.Z @loop, R15       ; PC-relative, Rd argument is accepted but ignored
JUMP.Z @+2              ; PC-relative numeric offset, Rd = R15
JUMP.Z R3               ; register form (Format 00), offset = 0, Rd = R15
JUMP.Z R3, R0           ; register form (Format 00), Rd = R0 (conditional move)
```

---

## PUSH / POP

`PUSH` and `POP` use a plain register form (no brackets). The stack-pointer register is optional and defaults to `R13` (`SP`) when omitted.

```
PUSH Rs1            ; SP -= 8; MEM64[SP] = Rs1   (stack pointer = R13)
PUSH Rs1, Rd        ; Rd -= 8; MEM64[Rd] = Rs1   (explicit stack pointer)

POP  Rs1            ; Rs1 = MEM64[SP]; SP += 8   (stack pointer = R13)
POP  Rs1, Rd        ; Rs1 = MEM64[Rd]; Rd += 8   (explicit stack pointer)
```

The first register is always the data register (value being pushed or the destination for a pop). The optional second register is the stack pointer.

```
PUSH R5             ; save R5 onto the stack
POP  R5             ; restore R5 from the stack
PUSH LR             ; save link register (R14) onto the stack
POP  LR             ; restore link register
```

---

## Assembler directives

Directives begin with a dot and are not emitted as instructions.

### `.org <address>`

Sets the **current assembly address**. Subsequent instructions and data words are placed starting at `<address>`. The address is a bare numeric literal (no `#`).

```
.org 0x0200
```

### `.byte <value>`

Emits a single **8-bit byte**. The address advances by 1. Because the CPU requires instructions to be 16-bit aligned, a `.byte` that leaves the address at an odd boundary must be followed by another `.byte` (or a `.org`) before the next instruction — the assembler does not auto-pad after `.byte`.

```
.byte 0xFF
.byte 0x00
```

### `.short <value>` / `.word <value>`

Emits a single **16-bit value** in little-endian byte order. `.word` is an accepted alias. If the current address is odd (due to a preceding `.byte`), one padding byte is automatically inserted to restore 2-byte alignment before emitting.

```
.short 0xBEEF
.word  42       ; alias for .short
```

### `.int <value>`

Emits a **32-bit value** in little-endian byte order (two 16-bit words). Auto-pads to 2-byte alignment if needed.

```
.int 0xDEADBEEF
```

### `.long <value>`

Emits a **64-bit value** in little-endian byte order (four 16-bit words). Auto-pads to 2-byte alignment if needed.

```
.long 0x0123456789ABCDEF
.long some_label    ; relocatable in ELF mode; value of some_label
```

### `.global <symbol>` and `.extern <symbol>`

Controls symbol visibility for ELF object output.

- `.global name` marks `name` as a global symbol (exported in the symbol table).
- `.extern name` declares `name` as an undefined external symbol reference.

```
.extern printf
.global start
```

### `.ascii <string>`

Emits the raw bytes of a string literal, **without** a null terminator. No alignment padding is inserted before or after.

```
.ascii "hello"       ; emits 5 bytes: h e l l o
.ascii "A\nB"        ; emits 3 bytes: 0x41 0x0A 0x42
```

### `.asciiz <string>`

Like `.ascii` but appends a **null byte** (`0x00`) after the string content.

```
.asciiz "hi"         ; emits 3 bytes: h i 0x00
.asciiz ""           ; emits 1 byte:  0x00
```

String literals are enclosed in double quotes. Supported escape sequences: `\"`, `\\`, `\n`, `\t`, `\0`.

Data directives are emitted **in source order**, interleaved with instructions. This is essential for PC-relative addressing: non-JUMP instructions have a range of ±31 instruction units (±62 bytes), while JUMP.\* branches reach ±511 instruction units (±1022 bytes).

---

## Two-pass assembly

The assembler works in two passes:

1. **Pass 1** — scans labels, instructions, and data directives in source order. Builds the symbol table and records the address of every item. No output is produced.
2. **Pass 2** — emits each item in source order: instructions are encoded and data directives are serialised into the byte stream. Label references are resolved using the symbol table.

Because labels are resolved in pass 1, **forward references** in PC-relative operands (`@label`) are fully supported.

---

## Example

```
.org 0x0100

start:
    LDI     #0,    R0       ; R0 = 0
    LDI.S1  #0xFF, R1       ; load 0xFF into byte-slot 1 of R1
    ADD     R0, R2           ; R2 = R0 + R2

loop:
    POP R3                   ; R3 = MEM64[SP]; SP += 8
    TEST     R3, R3
    JUMP.Z   @done           ; branch if zero flag set
    JUMP.Z   @loop           ; else loop

done:
    STOP

    ; Data is emitted here, in source order, right after the code.
    ; This keeps it within the ±64-byte PC-relative range.
table:
    .short 0x0001
    .short 0x0002

msg:
    .asciiz "hello"
```
