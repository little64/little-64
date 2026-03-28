# Little-64 — Claude Notes

##

This projet uses meson. The build folder is located in `builddir/`.

## Changing instructions

### LS instructions (Formats 00/01 — load/store/move/jump)

| File | What to change |
|---|---|
| `arch/opcodes_ls.def` | `LITTLE64_LS_OPCODE(enum_name, opcode_value, "mnemonic")` |
| `emulator/cpu.cpp` | Add/update the `case LS::Opcode::*` in **both** `_dispatchLSReg` (Format 00) and `_dispatchLSPCRel` (Format 01) — the two formats share an opcode but can behave differently |
| `assembler/assembler.cpp` | Only if the instruction needs non-standard syntax (e.g. bare registers instead of `[Rs1], Rd`) or a new mnemonic-classification helper |
| `disassembler/disassembler.cpp` | Only if the disassembly text differs from the default `[Rs1+N], Rd` pattern |
| `CPU_ARCH.md` | Update the OPCODE_LS table |
| `docs/assembly-syntax.md` | Update if the syntax is affected |
| `asm/test_program.asm` | Update any uses of the changed instruction |

### GP instructions (Format 11 — ALU)

| File | What to change |
|---|---|
| `arch/opcodes_gp.def` | `LITTLE64_GP_OPCODE(enum_name, opcode_value, "mnemonic", num_regs)` where `num_regs` is 2 (Rs1+Rd), 1 (Rd only), or 0 (no registers) |
| `emulator/cpu.cpp` | Add/update the `case GP::Opcode::*` in `_dispatchGP` only |
| `assembler/assembler.cpp` | Rarely needed — the `num_regs` field in the `.def` drives operand parsing automatically |
| `disassembler/disassembler.cpp` | Only if the disassembly text differs from the default pattern |
| `CPU_ARCH.md` | Update the OPCODE_GP table |
| `docs/assembly-syntax.md` | Update if the syntax is affected |
| `asm/test_program.asm` | Update any uses of the changed instruction |

`gui/panels/assembler_panel.cpp` never needs updating — the keyword list is built automatically from `Assembler::getAllMnemonics()`.

## Adding pseudo-instructions

Pseudo-instructions expand to one or more real instructions at assembly time. They live in the `pseudo_table` in `assembler/assembler.cpp` — adding a new one requires no changes anywhere else (syntax highlighting and documentation aside).

| File | What to change |
|---|---|
| `assembler/assembler.cpp` | Add an entry to `pseudo_table` (mnemonic → arity + expander lambda) |
| `docs/assembly-syntax.md` | Document the expansion and intended usage |

The expander lambda receives the source operand tokens, the base address of the first emitted instruction, and the source line number. It returns a `std::vector<ParsedInstruction>` in emission order; each instruction's `.address` field must be set to `base_addr + 2*index`. Use `makeRegToken()` and `makeImmToken()` to build synthetic operand tokens.

Pseudo-instructions are detected in `pass1()` before `parseInstruction()` is called, so they are fully transparent to the encoder and disassembler.

## LS instruction specifics

LS opcodes are shared between Format 00 (register) and Format 01 (PC-relative). Their behaviour can differ between the two — check both `_dispatchLSReg` and `_dispatchLSPCRel` in `emulator/cpu.cpp`.

In Format 00, the instruction encoding is:
```
[OPCODE_LS 4b] [OFFSET 2b] [Rs1 4b] [Rd 4b]
```
In Format 01, only `Rd` is available (no `Rs1`); the other bits are the signed PC-relative offset.
