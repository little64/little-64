# Little-64 Architecture Boundaries

This document defines module boundaries and allowed dependencies.

## Runtime Boundary

### Public runtime interface

- `host/emulator/frontend_api.hpp`
  - `IEmulatorRuntime`
  - `RegisterSnapshot`
  - `MemoryRegionView`

### Facade implementation

- `host/emulator/emulator_session.hpp/.cpp`

Frontend and tooling code should prefer `IEmulatorRuntime`/`EmulatorSession` over direct `Little64CPU` usage.

## Execution Paths

### Headless emulator

- Entry: `host/emulator/main.cpp`
- Shared helpers: `host/emulator/headless_runtime.hpp/.cpp`

### Debug server

- Entry: `host/emulator/debug_main.cpp`
- Server/transport: `host/emulator/debug_server.*`, `host/emulator/debug_transport.*`

### Frontends

- ImGui frontend: `host/gui/`
- Qt frontend: `host/qt/`
- Shared frontend helpers: `host/frontend/`

## Tooling Libraries and CLIs

- LLVM assembly wrapper: `host/project/llvm_assembler.*`
- Disassembler: `host/disassembler/`
- Linker: `host/linker/`
- Project runner: `host/project/`

## HDL Subsystem

- RTL implementation root: `hdl/little64_cores/`
- LiteX Linux boot/image helpers: `hdl/little64_cores/litex_linux_boot.py`
- HDL tests: `hdl/tests/`

The HDL subtree is a separate implementation of the Little-64 ISA and should
depend on `docs/hardware/` for the architectural contract, not on emulator-only
runtime details. Differential testing against the emulator is allowed and
encouraged, but emulator implementation details are not automatically part of
the HDL contract.

Within `hdl/little64_cores/`, executable microarchitectural blocks should stay
variant-owned under `basic/`, `v2/`, or `v3/`. Shared modules at the subtree
root should be limited to architectural metadata, configuration, interfaces,
and variant-selection glue rather than reusable pipeline/cache/LSU
implementations.

## Build Boundaries (Meson)

Top-level orchestration in `meson.build`, per-subsystem ownership in:

- `host/emulator/meson.build`
- `host/disassembler/meson.build`
- `host/linker/meson.build`
- `host/project/meson.build`
- `tests/meson.build`
- `host/gui/meson.build`
- `host/qt/meson.build`

## Dependency Rules

1. Frontends should not depend on raw CPU internals when runtime API methods exist.
2. Tool CLIs should use subsystem library APIs instead of duplicating logic.
3. Device registration/wiring must flow through `MachineConfig`.
4. Tests may reach internal APIs when needed but should prefer public surfaces first.
5. Translation internals (TLB/radix walker choices) must remain behind CPU translation boundaries defined in `hardware/memory-translation-and-boot.md`.

## Compatibility Rule

Build outputs expected by scripts remain available at root builddir paths:

- `builddir/little-64`
- `builddir/little-64-debug`

This is preserved for integration tests and task workflows.

## Update Checklist

When adding a new subsystem or crossing boundaries:

- update this document,
- update affected `meson.build` files,
- update `docs/README.md` index,
- run full tests to ensure no workflow regressions.
