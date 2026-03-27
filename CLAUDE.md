# Little-64 — Claude Notes

##

This projet uses meson. The build folder is located in `builddir/`.

## Changing instructions

When adding, removing, or renaming an instruction, update all of the following:

| File | What to change |
|---|---|
| `arch/opcodes_ls.def` or `arch/opcodes_gp.def` | Add/remove/rename the `LITTLE64_*_OPCODE` entry (enum name, opcode value, mnemonic string) |
| `emulator/cpu.cpp` | Add/update the `case LS::Opcode::*` or `case GP::Opcode::*` in both `_dispatchLSReg` and `_dispatchLSPCRel` (LS instructions have different behaviour per format) |
| `assembler/assembler.cpp` | Add a parse path if the instruction needs non-standard syntax (e.g. bare registers instead of `[Rs1], Rd`); update any mnemonic-classification helpers |
| `disassembler/disassembler.cpp` | Add a special-case if the instruction's disassembly text differs from the default `[Rs1+N], Rd` pattern |
| `gui/panels/assembler_panel.cpp` | Add/remove the mnemonic string from the `opcodes[]` keyword list for syntax highlighting |
| `CPU_ARCH.md` | Update the OPCODE_LS or OPCODE_GP table and any associated notes |
| `docs/assembly-syntax.md` | Update examples if the syntax is affected |
| `test_program.asm` | Update any uses of the changed instruction |

## LS instruction specifics

LS opcodes are shared between Format 00 (register) and Format 01 (PC-relative). Their behaviour can differ between the two — check both `_dispatchLSReg` and `_dispatchLSPCRel` in `emulator/cpu.cpp`.

In Format 00, the instruction encoding is:
```
[OPCODE_LS 4b] [OFFSET 2b] [Rs1 4b] [Rd 4b]
```
In Format 01, only `Rd` is available (no `Rs1`); the other bits are the signed PC-relative offset.
