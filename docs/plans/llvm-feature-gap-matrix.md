# Little-64 LLVM Feature Coverage and Gap Matrix

Saved for later implementation planning.

## Current Status Summary

The backend already supports several pseudo and lowering paths for direct Clang/LLVM code generation, while some handwritten-assembly ergonomic aliases remain missing in parser-level forms.

## Coverage Matrix

| Feature | Direct Clang / CodeGen Path | AsmParser / Handwritten ASM Path | Notes |
|---|---|---|---|
| `CALL` pseudo | Implemented | Partially implemented / syntax-sensitive | Defined in `Little64InstrInfo.td`, expanded in `Little64ExpandPseudos.cpp` |
| `RET` pseudo | Implemented | Partially implemented / syntax-sensitive | Defined in `Little64InstrInfo.td`, expanded in `Little64ExpandPseudos.cpp` |
| `LDI64` pseudo | Implemented | Implemented (special handling) | Lowered by `Little64ExpandPseudos.cpp`, special parser path in `Little64AsmParser.cpp` |
| `PUSH` / `POP` ISA opcodes | Implemented | Implemented with current operand forms | Present in `Little64InstrInfo.td` as real instructions |
| `JAL` alias | Not required by codegen | Missing alias | Candidate parser/InstAlias addition |
| `LDI.N` alias (example `LDI.2`) | Not required by codegen | Missing alias | Current canonical forms are `LDI.S1/2/3` |
| `.word` alias | Not required by codegen | Missing alias | `.long`, `.quad`, `.short` currently handled |
| `.asciiz` alias | Not required by codegen | Missing alias | `.ascii` works; null-terminated alias not wired |
| `MOVE Rn+imm, Rd` textual alias | Not required by codegen | Missing alias | Canonical parser forms differ |

## Confirmed Implementation Locations

- `compilers/llvm/llvm-project/llvm/lib/Target/Little64/Little64InstrInfo.td`
- `compilers/llvm/llvm-project/llvm/lib/Target/Little64/Little64ExpandPseudos.cpp`
- `compilers/llvm/llvm-project/llvm/lib/Target/Little64/AsmParser/Little64AsmParser.cpp`

## Practical Priority (Given C/C++-first Workflow)

1. Keep as-is for now (codegen path already productive).
2. Later parser ergonomics pass: `JAL`, `LDI.N`, `.word`, `.asciiz`.
3. Optional legacy compatibility aliases: textual `MOVE Rn+imm` and additional call/stack shorthand spellings.

## Validation Checklist When Resuming

- Build LLVM backend: `cd compilers && ./build.sh llvm`
- Run backend tests: `python3 tests/host/llvm/scripts/run_tests.py`
- Re-run project tests: `meson test -C builddir --print-errorlogs`
