# Little-64 — Contributor Notes

This file documents practical update paths and maintenance rules for common project changes.

## Build System

- Build system: Meson
- Build directory: `builddir/`
- Build graph is modularized:
  - `meson.build` (top-level orchestration)
  - subsystem build files in `host/emulator/`, `host/disassembler/`, `host/linker/`, `host/project/`, `tests/`, `host/gui/`, `host/qt/`

## Temporary Linux Build Script

- A temporary Linux kernel build helper exists at `target/linux_port/build.sh`.
- It invokes the Linux kernel `make` target with the Little64 LLVM toolchain from `compilers/bin`.
- The script is currently not part of the Meson graph and is meant for local Linux port experimentation only.
- Usage: `target/linux_port/build.sh [target]` where the default target is `vmlinux`.
- The script normally passes `-j$(nproc)` to `make` unless a `-j` argument is already provided.
- Optional guarded-clang mode can be enabled to catch backend non-termination/memory blowups:
  - `LITTLE64_CLANG_GUARD=1` enables `target/linux_port/clang_guard.sh` wrapper.
  - `LITTLE64_CLANG_TIMEOUT_SEC` sets per-clang timeout (default `120`).
  - `LITTLE64_CLANG_MAX_VMEM_KB` sets per-clang virtual memory cap in KB (default `10485760`, ~10 GB).
  - `LITTLE64_CLANG_GUARD_LOG_DIR` sets log directory (default `/tmp/little64-clang-guard`).
- Direct ELF boot helper for first Linux bring-up exists at `target/linux_port/boot_direct.sh`:
  - Default image path: `target/linux_port/build/vmlinux`.
  - Usage: `target/linux_port/boot_direct.sh [optional-path-to-vmlinux]`.
  - It launches the headless emulator in direct mode (`--boot-mode=direct`).
- PC-to-source lookup helper for Linux kernel debugging exists at `target/linux_port/pc_to_line.sh`:
  - Default image path: `target/linux_port/build/vmlinux`.
  - Usage: `target/linux_port/pc_to_line.sh [--elf <path>] [--context-bytes N] [--no-disasm] <pc>`.
  - It resolves a PC to function/file/line using LLVM tools from `compilers/bin` and can show nearby disassembly.
- To override core count or pass custom `make` arguments, add them after the target, for example:
  - `target/linux_port/build.sh vmlinux -j4`
  - `target/linux_port/build.sh vmlinux LOCALVERSION=-custom CONFIG_DEBUG_INFO=y`
  - `LITTLE64_CLANG_GUARD=1 LITTLE64_CLANG_TIMEOUT_SEC=90 target/linux_port/build.sh vmlinux -j4`
  - `LITTLE64_CLANG_GUARD=1 LITTLE64_CLANG_MAX_VMEM_KB=10485760 target/linux_port/build.sh vmlinux -j1`

## Instruction Change Guide

## LS instructions (formats 00 and 01)

| File | Required change |
|---|---|
| `host/arch/opcodes_ls.def` | Add/update `LITTLE64_LS_OPCODE(...)` entry |
| `host/emulator/cpu.cpp` | Update handling in both `_dispatchLSReg(...)` and `_dispatchLSPCRel(...)` |
| `host/project/llvm_assembler.cpp` | Update only if assembly wrapper/tool invocation behavior changes |
| `host/disassembler/disassembler.cpp` | Update only if text output differs from defaults |
| `CPU_ARCH.md` | Update opcode and semantics reference |
| `docs/assembly-syntax.md` | Update syntax and examples if affected |
| tests | Add/update targeted instruction tests |

LS opcodes are shared between format 00 and 01. Behavior can differ by format and must be validated in both dispatch paths.

## GP instructions (format 11 ALU space)

| File | Required change |
|---|---|
| `host/arch/opcodes_gp.def` | Add/update `LITTLE64_GP_OPCODE(...)` entry |
| `host/emulator/cpu.cpp` | Update `_dispatchGP(...)` |
| `host/project/llvm_assembler.cpp` | Usually unnecessary unless wrapper behavior/toolchain pathing changes |
| `host/disassembler/disassembler.cpp` | Update if text output differs from defaults |
| `CPU_ARCH.md` | Update opcode and semantics reference |
| `docs/assembly-syntax.md` | Update syntax and examples if affected |
| tests | Add/update targeted instruction tests |

## Legacy syntax compatibility

Legacy pseudo-forms used in older tests (`LDI64`, `CALL`, `JAL`, `RET`, textual `PUSH`/`POP`, `MOVE Rn+imm`) are currently rewritten for LLVM assembly in `tests/support/cpu_test_helpers.hpp`.

For compatibility updates:

1. adjust rewrite rules in `tests/support/cpu_test_helpers.hpp`,
2. ensure generated instructions preserve original test semantics,
3. update `docs/assembly-syntax.md` compatibility notes,
4. run full test suite.

## Device Framework Changes

| File | Required change |
|---|---|
| `host/emulator/device.hpp` | Base lifecycle contract (`reset`, `tick`) |
| `host/emulator/machine_config.hpp/.cpp` | Machine map registration path (including interrupt sink wiring) |
| `host/emulator/cpu.cpp` | Runtime wiring if device behavior impacts load/reset/cycle |
| `host/tools/new_device.py` | Scaffold hints/messages when integration path changes |
| `docs/device-framework.md` | Update extension workflow |
| tests (`tests/host/test_devices.cpp`) | Add conformance coverage |

Note: `host/tools/new_device.py` currently instructs contributors to add new device sources in `host/emulator/meson.build`.

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

## Required Reading

Before answering any questions, planning any tasks or implementing any changes, you are required to read the documentation under `docs/`. If you find code contradicts the documentation, the code is authorative, as previously stated, and you must in your next response message report the contradiction, and how it should be solved.
