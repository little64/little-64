# Little-64 — Contributor Notes

This file documents practical update paths and maintenance rules for common project changes.

## Build System

- Build system: Meson
- Build directory: `builddir/`
- Build graph is modularized:
  - `meson.build` (top-level orchestration)
  - subsystem build files in `emulator/`, `assembler/`, `disassembler/`, `linker/`, `project/`, `tests/`, `gui/`, `qt/`

## Instruction Change Guide

## LS instructions (formats 00 and 01)

| File | Required change |
|---|---|
| `arch/opcodes_ls.def` | Add/update `LITTLE64_LS_OPCODE(...)` entry |
| `emulator/cpu.cpp` | Update handling in both `_dispatchLSReg(...)` and `_dispatchLSPCRel(...)` |
| `assembler/assembler.cpp` | Update only if syntax/parsing is non-standard |
| `disassembler/disassembler.cpp` | Update only if text output differs from defaults |
| `CPU_ARCH.md` | Update opcode and semantics reference |
| `docs/assembly-syntax.md` | Update syntax and examples if affected |
| tests | Add/update targeted instruction tests |

LS opcodes are shared between format 00 and 01. Behavior can differ by format and must be validated in both dispatch paths.

## GP instructions (format 11 ALU space)

| File | Required change |
|---|---|
| `arch/opcodes_gp.def` | Add/update `LITTLE64_GP_OPCODE(...)` entry |
| `emulator/cpu.cpp` | Update `_dispatchGP(...)` |
| `assembler/assembler.cpp` | Usually unnecessary (encoding metadata drives parsing) |
| `disassembler/disassembler.cpp` | Update if text output differs from defaults |
| `CPU_ARCH.md` | Update opcode and semantics reference |
| `docs/assembly-syntax.md` | Update syntax and examples if affected |
| tests | Add/update targeted instruction tests |

## Pseudo-instructions

Pseudo-instructions are defined in `assembler/assembler.cpp` (`pseudo_table`).

For a new pseudo-instruction:

1. add pseudo expansion in `pseudo_table`,
2. set correct synthetic instruction addresses (`base + 2 * index`),
3. update `docs/assembly-syntax.md` with expansion and usage,
4. add tests covering assembly + execution semantics.

## Device Framework Changes

| File | Required change |
|---|---|
| `emulator/device.hpp` | Base lifecycle contract (`reset`, `tick`) |
| `emulator/machine_config.hpp/.cpp` | Machine map registration path |
| `emulator/cpu.cpp` | Runtime wiring if device behavior impacts load/reset/cycle |
| `tools/new_device.py` | Scaffold hints/messages when integration path changes |
| `docs/device-framework.md` | Update extension workflow |
| tests (`tests/test_devices.cpp`) | Add conformance coverage |

Note: `tools/new_device.py` currently instructs contributors to add new device sources in `emulator/meson.build`.

## Test Structure

- Generic test macros: `tests/support/test_harness.hpp`
- CPU-specific helpers: `tests/support/cpu_test_helpers.hpp`
- Backward-compat include shim: `tests/test_harness.hpp`

When adding CPU tests, prefer including `tests/support/cpu_test_helpers.hpp` directly.

## Documentation Update Contract

When behavior changes, update docs in the same change:

1. `CPU_ARCH.md` for ISA/semantic changes.
2. `docs/assembly-syntax.md` for assembler syntax/directive changes.
3. `docs/architecture-boundaries.md` for layering/API changes.
4. `docs/device-framework.md` for machine/device model changes.
5. `README.md` and `docs/README.md` when command paths or reading order changes.
6. this `CLAUDE.md` when contributor workflow instructions change.

## Verification Commands

```bash
# Reconfigure + build
meson setup --reconfigure builddir
meson compile -C builddir

# Full test suite
meson test -C builddir --print-errorlogs
```

For ISA bring-up via LLVM tools:

```bash
compilers/bin/llvm-mc -triple=little64 -filetype=obj test.asm -o test.o
compilers/bin/ld.lld test.o -o test.elf
compilers/bin/llvm-objdump -d --triple=little64 test.elf
./builddir/little-64 test.elf
```

## RSP Debug Server Quick Check

```bash
meson compile -C builddir little-64-debug
./builddir/little-64-debug 9000 [optional-image.elf]
meson test -C builddir debug-rsp-integration --print-errorlogs
meson test -C builddir debug-lldb-remote-smoke --print-errorlogs
```
