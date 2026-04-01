# Little-64 Architecture Boundaries (Phase 1)

Date: 2026-04-01

This document records the current module boundaries after Phase 1 cleanup.

## Runtime API Boundary

- Public frontend contract: `emulator/frontend_api.hpp`
  - `IEmulatorRuntime`
  - `RegisterSnapshot`
  - `MemoryRegionView`
- Concrete implementation: `emulator/emulator_session.hpp/.cpp`

Frontends should depend on `IEmulatorRuntime`/`EmulatorSession`, not directly on `Little64CPU` internals.

## Frontend Composition

- GUI composition root: `gui/app.hpp/.cpp`
- Shared app state remains in `AppState`.
- Panels depend on narrow contexts (`gui/panels/panel_contexts.hpp`) rather than the full app state.

This keeps panel-level dependencies explicit and reduces cross-coupling.

## Headless Entrypoints

- Emulator CLI: `emulator/main.cpp`
  - uses shared loader/run helpers in `emulator/headless_runtime.hpp/.cpp`
- Debug CLI: `emulator/debug_main.cpp`
  - uses modular debug core (`emulator/debug_server.hpp/.cpp`)
  - transport abstraction via `emulator/debug_transport.hpp`

Both paths converge on the same runtime API boundary.

## Tooling Boundaries

- Project runner: `project/runner_main.cpp`
  - now drives execution through `EmulatorSession`
  - no direct `Little64CPU` dependency in this entrypoint

## Build-Level Boundaries (Meson)

- Core module source groups in `meson.build`:
  - `core_emulator_src`
  - `core_assembler_src`
  - `core_linker_src`
  - `core_disassembler_src`
  - `core_project_src`
- UI source group:
  - `ui_gui_src`

This keeps top-level responsibilities explicit without requiring immediate on-disk directory moves.

## Remaining Work Outside Phase 1

- Device registration/model simplification (`MachineConfig` / registry) — Phase 2.
- MMU/page-fault and trap plumbing — Phase 3.
- Unified unit test framework replacement (`tests/test_harness.hpp`) — Phase 4.
