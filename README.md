# Little-64

Little-64 is a 64-bit ISA/emulator/toolchain playground with a modular C++ core, assembler/disassembler/linker utilities, debug transport, and optional GUI frontends.

## Quick start

### Build emulator + tools

```bash
meson compile -C builddir
```

### Run all tests

```bash
meson test -C builddir --print-errorlogs
```

### Run emulator with an ELF

```bash
./builddir/little-64 path/to/program.elf
```

## Repository map

- `arch/` — opcode and ISA encoding definitions
- `emulator/` — CPU, memory bus, devices, runtime/debug server
- `assembler/` — lexer/parser/encoder + CLI
- `disassembler/` — disassembly library + CLI
- `linker/` — linker library + CLI
- `project/` — project runner/orchestration utilities
- `gui/` — ImGui frontend
- `qt/` — Qt frontend
- `tests/` — unit/integration/debug/toolchain tests
- `docs/` — architecture, workflow, and roadmap docs
- `compilers/` — external toolchain worktrees/build scripts

## Build system layout

Meson build logic is split by subsystem:

- Top-level orchestration: `meson.build`
- Subsystem build files:
  - `emulator/meson.build`
  - `assembler/meson.build`
  - `disassembler/meson.build`
  - `linker/meson.build`
  - `project/meson.build`
  - `tests/meson.build`
  - `gui/meson.build`
  - `qt/meson.build`

## Toolchain layout (`compilers/` kept separate)

`compilers/` intentionally keeps LLVM and Lily-CC separated for local development workflows:

- LLVM: `compilers/llvm/`
- Lily-CC: `compilers/lily-cc/`
- Exported binaries: `compilers/bin/`

This separation is preserved by design and should not be collapsed.

## Where to start reading

- Architecture boundaries: `docs/architecture-boundaries.md`
- Cleanup roadmap: `docs/cleanup-roadmap.md`
- VS Code integration: `docs/vscode-integration.md`
- Assembly syntax reference: `docs/assembly-syntax.md`
- ISA reference: `CPU_ARCH.md`
