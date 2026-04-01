# Little-64

Little-64 is a 64-bit ISA project with:

- a C++ emulator/runtime,
- an assembler/disassembler/linker toolchain,
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
| `builddir/little-64-asm` | Assembler (`.asm` to `.bin`/`.o`) |
| `builddir/little-64-disasm` | Disassembler (`.bin` to text) |
| `builddir/little-64-linker` | Object linker |
| `builddir/little-64-run` | `.l64proj` compile/link/run harness |
| `builddir/little-64-gui` | ImGui frontend |
| `builddir/little-64-qt` | Qt frontend (if Qt detected/enabled) |

## Repository Layout

- `arch/` — opcode definitions (`opcodes_ls.def`, `opcodes_gp.def`) and generated enums
- `emulator/` — CPU, memory bus, devices, debug transport/server, headless runtime
- `assembler/`, `disassembler/`, `linker/` — tool libraries + CLI entrypoints
- `project/` — project-file model and runner
- `gui/`, `qt/` — frontends
- `tests/` — unit + integration + toolchain + debug tests
- `docs/` — architecture and workflow documentation
- `compilers/` — external compiler ports/toolchains

## Build System Structure

Meson files are modularized by subsystem:

- top-level orchestration: `meson.build`
- per-subsystem build files:
  - `emulator/meson.build`
  - `assembler/meson.build`
  - `disassembler/meson.build`
  - `linker/meson.build`
  - `project/meson.build`
  - `tests/meson.build`
  - `gui/meson.build`
  - `qt/meson.build`

## Documentation Map

Start at `docs/README.md` for the full index.

Key docs:

- `CPU_ARCH.md` — ISA and execution architecture reference
- `docs/assembly-syntax.md` — assembler language and directives
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
2. Update syntax docs for parser/assembler changes.
3. Update `CLAUDE.md` when contributor workflows or touched-file rules change.
4. Run `meson test -C builddir --print-errorlogs` before finalizing documentation that includes command examples.
