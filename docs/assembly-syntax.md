# Little-64 Assembly Syntax

This document defines the syntax accepted by `little-64-asm`.

## Source of Truth

- Parser and pseudo-expansion logic: `assembler/assembler.cpp`
- Encoding rules: `assembler/encoder.cpp`
- ISA semantics: `../CPU_ARCH.md`

If this document and assembler behavior disagree, `assembler/assembler.cpp` is authoritative and this document must be updated.

## Lexical Rules

## Comments

- `;` begins a comment and runs to end of line.

## Registers

- Register names: `R0`..`R15` (case-insensitive)
- Aliases:
  - `SP` → `R13`
  - `LR` → `R14`
  - `PC` → `R15`

## Number Literals

Supported numeric forms:

- decimal: `42`
- hexadecimal: `0x2A`
- binary: `0b101010`

Immediates in instructions must use `#` (for example `#42`, `#0x10`).

## Labels

- Definition: `name:`
- Valid chars: letters, digits, `_`, `.`
- First char cannot be a digit

## Instruction Line Form

```asm
[label:] MNEMONIC[.SUFFIX] [operand [, operand ...]]
```

## Operand Forms

## Register

```asm
R1
SP
```

## Immediate

```asm
#12
#0xFF
```

## Register-indirect memory

```asm
[R2]
[R2+2]
[R2+4]
[R2+6]
```

Offset for this form is limited to `0, 2, 4, 6` bytes.

## Register-address expression (no dereference)

Used by `MOVE` and register-form conditional jumps:

```asm
R2
R2+2
```

## PC-relative address

```asm
@label
@+3
@-2
```

Offsets are in instruction units (2 bytes each), relative to the next instruction.

## Core Instruction Families

## `LDI` and `LDI.SN`

```asm
LDI    #0x12, R1
LDI.S1 #0x34, R1
LDI.S2 #0x56, R1
LDI.S3 #0x78, R1
```

`LDI` loads an 8-bit literal into a selected byte lane (`S0`..`S3`).

## GP ALU instructions

Typical forms:

```asm
ADD R1, R2
SLLI #4, R2
IRET
STOP
```

## LS register/PC-relative instructions

```asm
LOAD  [R3], R1
STORE [R3+2], R1
LOAD  @data, R1
JUMP.Z @target
JUMP @loop
```

## Pseudo-instructions

Pseudo-instructions expand in `assembler/assembler.cpp` (`pseudo_table`).

Common pseudo-instructions include:

- `LDI64`
- `CALL`
- `JAL`
- `RET`

Always treat expansion behavior in assembler source as canonical.

## Directives

Common directives include:

- `.org`
- `.word`
- `.byte`
- `.global`
- `.extern`

Use assembler tests and examples in `asm/` for practical forms.

## Minimal Example

```asm
.org 0x0000

start:
    LDI #1, R1
    LDI #2, R2
    ADD R1, R2
    STOP
```

## Validation Workflow

```bash
./builddir/little-64-asm --elf -o test.o test.asm
compilers/bin/ld.lld test.o -o test.elf
./builddir/little-64 test.elf
```

## Update Checklist

When syntax changes:

1. update parser/encoder implementation,
2. update or add tests in `tests/test_assembler.cpp` (and related CPU tests when needed),
3. update this file with exact accepted forms,
4. verify examples still assemble and run.
