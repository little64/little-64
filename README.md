# Little-64

Little-64 is a 64-bit ISA project with:

- a C++ emulator/runtime,
- an LLVM-based assembler + custom disassembler/linker toolchain,
- project-runner workflows,
- debug-server support (GDB RSP subset),
- optional ImGui and Qt frontends.

## Quick Start

### 1) Configure and build

```bash
meson setup builddir
meson compile -C builddir
```

### 2) Run all tests

```bash
meson test -C builddir --print-errorlogs
```

### 3) Run emulator with an image

```bash
./builddir/little-64 <program.bin|program.o|program.elf>
```

## Primary Binaries

| Binary | Purpose |
|---|---|
| `builddir/little-64` | Headless emulator runner |
| `builddir/little-64-debug` | TCP debug server (RSP) |
| `builddir/little-64-disasm` | Disassembler (`.bin` to text) |
| `builddir/little-64-linker` | Object linker |
| `builddir/little-64-run` | `.l64proj` compile/link/run harness |
| `builddir/little-64-gui` | ImGui frontend |
| `builddir/little-64-qt` | Qt frontend (if Qt detected/enabled) |

Assembly to object code is performed through `compilers/bin/llvm-mc` (see `host/project/llvm_assembler.*`).

## Repository Layout

- `host/` — host-side runtime/tools/frontends (`host/emulator/`, `host/disassembler/`, `host/linker/`, `host/project/`, `host/gui/`, `host/qt/`, ...)
- `target/` — target-side code/images (`target/asm/`, `target/c_boot/`)
- `tests/host/` — host tool/runtime/integration tests
- `tests/target/` — CPU/ISA-focused tests
- `tests/support/` — shared test helpers
- `docs/` — architecture and workflow documentation
- `compilers/` — external compiler ports/toolchains

## Build System Structure

Meson files are modularized by subsystem:

- top-level orchestration: `meson.build`
- per-subsystem build files:
  - `host/emulator/meson.build`
  - `host/disassembler/meson.build`
  - `host/linker/meson.build`
  - `host/project/meson.build`
  - `tests/meson.build`
  - `host/gui/meson.build`
  - `host/qt/meson.build`

## Documentation Map

Start at `docs/README.md` for the full index.

Key docs:

- `CPU_ARCH.md` — ISA and execution architecture reference
- `docs/assembly-syntax.md` — LLVM-targeted assembly language notes and compatibility guidance
- `docs/architecture-boundaries.md` — module/API boundaries
- `docs/device-framework.md` — MMIO/device model and extension path
- `docs/vscode-integration.md` — editor/debug workflow integration
- `GUI_DEBUGGER.md` — frontend behavior and usage

## Toolchain Separation Policy

`compilers/llvm/` and `compilers/lily-cc/` remain intentionally separate to preserve independent local development workflows.

Do not merge or restructure these trees as part of normal project cleanup.

## Documentation Maintenance Rule

When behavior changes, update docs in the same change:

1. Update architecture/runtime docs for behavior changes.
2. Update syntax docs for LLVM assembly behavior changes.
3. Update `CLAUDE.md` when contributor workflows or touched-file rules change.
4. Run `meson test -C builddir --print-errorlogs` before finalizing documentation that includes command examples.
