# Little-64

Little-64 is a 64-bit ISA project with:

- a C++ emulator/runtime,
- an Amaranth HDL implementation subtree,
- an LLVM-based assembler + custom disassembler/linker toolchain,
- project-runner workflows,
- debug-server support (GDB RSP subset),
- optional ImGui and Qt frontends.

## Cloning

Clone the `llvm-project` submodule as well. There is a wired-up `lily-cc` submodule as well, but I haven't written any working backend for it yet, and to be honest, will be using LLVM mostly anyway.

LLVM is required for the tests as well. Compile it with `bash compilers/build.sh llvm` first. This will take a while and use a lot of RAM.

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

Assembly to object code uses `compilers/bin/llvm-mc` (see `host/project/llvm_assembler.*`).

## Repository Layout

- `host/` — host-side runtime/tools/frontends (`host/emulator/`, `host/disassembler/`, `host/linker/`, `host/project/`, `host/gui/`, `host/qt/`, ...)
- `hdl/` — Amaranth soft-core CPU implementation and HDL tests
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

## Documentation

Start with `docs/README.md` for the full index.

Key docs:

- `docs/hardware/README.md` — hardware architecture reference and replacement entry point for the old monolithic architecture docs
- `docs/hdl.md` — HDL subsystem scope, layout, and test entry points
- `docs/emulator/README.md` — emulator runtime, boot, and virtual-platform documentation
- `docs/assembly-syntax.md` — LLVM-targeted assembly language notes and compatibility guidance
- `docs/architecture-boundaries.md` — module/API boundaries
- `docs/device-framework.md` — MMIO/device model and extension path
- `docs/vscode-integration.md` — editor/debug workflow integration
- `GUI_DEBUGGER.md` — frontend behavior and usage

## Linux Direct Boot

The Linux bring-up flow lives under `target/linux_port/` and is intentionally outside the Meson graph.

Typical direct-boot flow with the paravirtual block rootfs:

```bash
target/linux_port/build.sh vmlinux -j1
target/linux_port/rootfs/build.sh
target/linux_port/boot_direct.sh
```

The default direct-boot rootfs image is `target/linux_port/rootfs/build/rootfs.ext2`.
Use `target/linux_port/boot_direct.sh --no-rootfs` to boot the kernel without attaching the PV block disk.

## Toolchain Separation Policy

`compilers/llvm/` and `compilers/lily-cc/` remain intentionally separate to preserve independent local development workflows.

Do not merge or restructure these trees as part of normal project cleanup.

## Documentation Maintenance

When behavior changes, update docs in the same change:

1. Update hardware docs for core ISA changes and emulator docs for implementation-specific behavior changes.
2. Update syntax docs for LLVM assembly behavior changes.
3. Update `CLAUDE.md` when contributor workflows or touched-file rules change.
4. Run `meson test -C builddir --print-errorlogs` before finalizing documentation that includes command examples.

## Clanker warning

LLMs were used when developing this, but mostly for the LLVM port.
LLMs were used in other places as well, but the code was a lot more reviewed there than in the LLVM target.
