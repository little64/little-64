# Little-64 Architecture Boundaries

This document defines module boundaries and allowed dependencies.

## Runtime Boundary

## Public runtime interface

- `emulator/frontend_api.hpp`
  - `IEmulatorRuntime`
  - `RegisterSnapshot`
  - `MemoryRegionView`

## Facade implementation

- `emulator/emulator_session.hpp/.cpp`

Frontend and tooling code should prefer `IEmulatorRuntime`/`EmulatorSession` over direct `Little64CPU` usage.

## Execution Paths

## Headless emulator

- Entry: `emulator/main.cpp`
- Shared helpers: `emulator/headless_runtime.hpp/.cpp`

## Debug server

- Entry: `emulator/debug_main.cpp`
- Server/transport: `emulator/debug_server.*`, `emulator/debug_transport.*`

## Frontends

- ImGui frontend: `gui/`
- Qt frontend: `qt/`
- Shared frontend helpers: `frontend/`

## Tooling Libraries and CLIs

- Assembler: `assembler/`
- Disassembler: `disassembler/`
- Linker: `linker/`
- Project runner: `project/`

## Build Boundaries (Meson)

Top-level orchestration in `meson.build`, per-subsystem ownership in:

- `emulator/meson.build`
- `assembler/meson.build`
- `disassembler/meson.build`
- `linker/meson.build`
- `project/meson.build`
- `tests/meson.build`
- `gui/meson.build`
- `qt/meson.build`

## Dependency Rules

1. Frontends should not depend on raw CPU internals when runtime API methods exist.
2. Tool CLIs should use subsystem library APIs instead of duplicating logic.
3. Device registration/wiring must flow through `MachineConfig`.
4. Tests may reach internal APIs when needed but should prefer public surfaces first.

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
