# Little-64 Assembly Syntax

This document defines the Little-64 assembly workflow.

## Source of Truth

- Primary assembler: `compilers/bin/llvm-mc -triple=little64`
- Runtime loader expectations: `host/linker/linker.cpp`, `host/emulator/cpu.cpp`
- Project assembly wrapper: `host/project/llvm_assembler.cpp`
- ISA semantics: `../CPU_ARCH.md`

If this document and `llvm-mc` behavior differ, `llvm-mc` is authoritative.

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

The LLVM Little-64 backend supports the core ISA forms used by runtime and linker tests:

- `LDI`, `LDI.S1`, `LDI.S2`, `LDI.S3`
- GP ops (`ADD`, `SUB`, `AND`, `OR`, `TEST`, `STOP`, etc.)
- LS memory ops (`LOAD`, `STORE`, `BYTE_*`, `SHORT_*`, `WORD_*`)
	- register-indirect LS offsets are encoded in 2-bit halfword units, so
		accepted byte offsets are `{0,2,4,6}`
- Branch/jump forms (`JUMP`, `JUMP.Z`, `JUMP.C`, `JUMP.S`, `JUMP.GT`, `JUMP.LT`)
- directives used by linker/object workflows (`.global`, `.extern`, `.byte`, `.short`, `.long`)

## Legacy Compatibility Notes

Legacy pseudo-forms such as `LDI64`, `CALL`, `JAL`, `RET`, textual `PUSH`/`POP`, and `MOVE Rn+imm` are not guaranteed as direct `llvm-mc` syntax.

CPU tests preserve legacy readability via compatibility preprocessing in `tests/support/cpu_test_helpers.hpp`, which rewrites these forms into LLVM-compatible code before assembly.

That compatibility path is test-only and not a CLI contract.

## Validation Checklist

When assembly behavior changes:

1. Update `host/project/llvm_assembler.*` if wrapper behavior changes.
2. Update `tests/test_assembler.cpp` for assembly wrapper expectations.
3. Update linker/CPU tests when syntax compatibility assumptions change.
4. Re-run `meson test -C builddir --print-errorlogs`.
