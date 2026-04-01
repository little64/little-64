# Little-64 Assembly Syntax

This document defines the assembly workflow used by Little-64.

## Source of Truth

- Primary assembler: `compilers/bin/llvm-mc -triple=little64`
- Runtime loader expectations: `linker/linker.cpp`, `emulator/cpu.cpp`
- Project assembly wrapper: `project/llvm_assembler.cpp`
- ISA semantics: `../CPU_ARCH.md`

If this document and `llvm-mc` behavior disagree, `llvm-mc` is authoritative.

## Standard Workflow

Assemble and link with LLVM tools:

```bash
compilers/bin/llvm-mc -triple=little64 -filetype=obj test.asm -o test.o
compilers/bin/ld.lld test.o -o test.elf
./builddir/little-64 test.elf
```

For multi-object linking into flat binary words:

```bash
./builddir/little-64-linker -o out.bin a.o b.o
./builddir/little-64 out.bin
```

## Supported Core Forms

The LLVM Little-64 backend supports the core ISA instruction forms used by runtime and linker tests:

- `LDI`, `LDI.S1`, `LDI.S2`, `LDI.S3`
- GP ops (`ADD`, `SUB`, `AND`, `OR`, `TEST`, `STOP`, etc.)
- LS memory ops (`LOAD`, `STORE`, `BYTE_*`, `SHORT_*`, `WORD_*`)
- Branch/jump forms (`JUMP`, `JUMP.Z`, `JUMP.C`, `JUMP.S`, `JUMP.GT`, `JUMP.LT`)
- directives used by linker/object workflows (`.global`, `.extern`, `.byte`, `.short`, `.long`)

## Legacy Compatibility Notes

Historical custom-assembler pseudo/informal forms like `LDI64`, `CALL`, `JAL`, `RET`, `PUSH`/`POP` textual forms, and `MOVE Rn+imm` are not guaranteed as direct `llvm-mc` syntax.

Current CPU tests keep legacy source readability through compatibility preprocessing in `tests/support/cpu_test_helpers.hpp`, which rewrites those forms into LLVM-compatible code before assembly.

That compatibility path is test-only and not a CLI contract.

## Validation Checklist

When assembly behavior changes:

1. Update `project/llvm_assembler.*` if wrapper behavior changes.
2. Update `tests/test_assembler.cpp` for assembly wrapper expectations.
3. Update linker/CPU tests when syntax compatibility assumptions change.
4. Re-run `meson test -C builddir --print-errorlogs`.
