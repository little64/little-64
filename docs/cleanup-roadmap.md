# Little-64 Cleanup & Scale-Up Roadmap

Date: 2026-04-01

## Status Snapshot

- Phase 1: ✅ Completed
- Phase 2: ✅ Completed
- Phase 3: 🟡 In progress (headless debug skeleton in place)
- Phase 4: 🟡 In progress (LLVM tests integrated into Meson)

## Goals

1. Prepare the project for a paging-capable ISA and UNIX-like OS bring-up.
2. Make device addition simple, testable, and low-risk.
3. Unify testing so every subsystem has automated tests and output is consistent/clean.

## Current Baseline (updated)

- Build/test is Meson-based and already split into core libraries (`emulator`, `assembler`, `disassembler`, `linker`, `project`).
- CPU unit tests exist but still use local macros (`tests/test_harness.hpp`) and custom per-binary summaries.
- LLVM integration tests are now integrated into Meson (`llvm-integration` suite) via `tests/llvm/scripts/run_tests.py`.
- GUI debugger is useful for ISA-level bring-up but not yet suited for OS-level, multi-process, paging-heavy debugging workflows.
- Device model now uses `Device` + `MachineConfig` for declarative registration, lifecycle hooks, and centralized memory-map wiring.

---

## Strategic Decision: IDE in GUI vs External Tooling

### Recommendation

Do **not** turn `little-64-gui` into a full IDE.

Keep the GUI focused on:
- machine state visualization,
- execution control,
- memory/register/disassembly introspection,
- device trace views.

For editing/build/orchestration, use external tools (VS Code/CLI) and a debug protocol bridge.

### Why

- A full IDE inside the emulator duplicates mature tooling (editor, LSP, build systems, source navigation).
- OS bring-up needs scriptable automation and headless CI; GUI-first workflows do not scale for this.
- Long-term maintainability improves when emulator/debugger are protocol-driven and editor-agnostic.

### Target dev architecture

- **Editor/IDE**: VS Code/CLI (existing toolchain + tasks).
- **Build/test**: Meson + Ninja + LLVM flow wrappers.
- **Debug transport**: add a **GDB remote stub** or equivalent debug server in emulator.
- **UI options**:
  - CLI/headless emulator for CI and batch debugging.
  - GUI as optional frontend over same debug/runtime APIs.

---

## Phased Cleanup Plan

## Phase 1 — Project Structure & Boundaries (1–2 weeks)

Status: ✅ Completed (2026-04-01)

### Objectives

- Reduce clutter by making subsystem boundaries explicit.
- Prepare for paging and richer machine state without UI coupling.

### Changes

1. Introduce explicit internal modules/namespaces:
   - `core/isa` (decode/encode definitions),
   - `core/emulator` (CPU + MMU + interrupt controller eventually),
   - `core/devices` (device interfaces + implementations),
   - `tools/` (assembler/disassembler/linker frontends),
   - `ui/gui` (panels, renderer, app state).
2. Keep existing binaries, but route through library APIs only.
3. Define a stable emulator API surface used by both GUI and tests.

### Acceptance criteria

- GUI does not directly depend on internal CPU implementation details outside the public emulator API.
- Core libraries can be built/tested without GUI dependencies.

### Delivered

1. Stable runtime API boundary
   - Added `emulator/frontend_api.hpp` (`IEmulatorRuntime`, `RegisterSnapshot`, `MemoryRegionView`).
   - Added `emulator/emulator_session.hpp/.cpp` as facade implementation used by frontends.
2. GUI decoupling
   - GUI panels consume narrow context structs (`gui/panels/panel_contexts.hpp`) instead of direct `AppState` coupling.
   - Panel implementations use `EmulatorSession`/`IEmulatorRuntime` surface rather than raw CPU internals.
3. Headless architecture convergence
   - `emulator/main.cpp` now uses shared headless runtime helpers (`emulator/headless_runtime.hpp/.cpp`).
   - Added modular `little-64-debug` entrypoint (`debug_server`, `debug_transport`, `debug_main`).
4. Tool boundary cleanup
   - `project/runner_main.cpp` migrated to `EmulatorSession` (no direct `Little64CPU` usage).
5. Build/test boundary clarity
   - Meson source organization split by module groups (`core_*`, `ui_gui_src`).

---

## Phase 2 — Device Framework Simplification (1–2 weeks)

Status: ✅ Completed (2026-04-01)

### Objectives

- Make adding a new MMIO/peripheral device a small, repeatable task.

### Changes

1. Add a `Device` abstraction layered on top of `MemoryRegion`:
   - identity (`name`, `base`, `size`),
   - lifecycle hooks (`reset`, optional `tick`),
   - read/write handlers.
2. Introduce a `DeviceRegistry` / `MachineConfig` object:
   - declarative registration of ROM/RAM/UART/timer/etc,
   - one place to define machine memory map.
3. Add a templated/skeleton helper for new devices (e.g. `tools/new_device.py` or minimal C++ template file).
4. Add device conformance tests:
   - register-level read/write behavior,
   - reset semantics,
   - side effects (FIFO status flags, interrupts when added).

### Acceptance criteria

- New device can be added by implementing one class + one registry entry + tests.
- No manual memory map edits scattered across unrelated files.

### Delivered

1. `Device` abstraction
   - Added `emulator/device.hpp` (`Device : MemoryRegion`) with lifecycle hooks: `reset()` and `tick()`.
2. Declarative machine/device config
   - Added `emulator/machine_config.hpp/.cpp` with fluent registration helpers:
     - `addRam(...)`,
     - `addPreloadedRam(...)`,
     - `addRom(...)`,
     - `addSerial(...)`,
     - `applyTo(bus, devices)`.
3. CPU wiring migrated to config path
   - `Little64CPU::loadProgram()` and `loadProgramElf()` now build memory maps through `MachineConfig`.
   - `Little64CPU::reset()` now resets all registered devices.
   - `Little64CPU::cycle()` now ticks all registered devices.
4. Serial device lifecycle conformance
   - `SerialDevice` now derives from `Device` and implements `reset()` (state + FIFO clear) and `tick()`.
5. New-device scaffold helper
   - Added `tools/new_device.py` to generate `Device` skeleton header/source files.
6. Device-focused tests
   - Added `tests/test_devices.cpp`.
   - Added Meson suite entry `test('devices', ...)`.

---

## Phase 3 — Paging/UNIX Bring-up Infrastructure (2–4 weeks)

Status: 🟡 Started

### Objectives

- Support OS-level iteration speed and observability before full OS porting.

### Changes

1. Add MMU abstraction now (even with identity mapping initially):
   - translation API (`virt -> phys`),
   - page fault reporting path,
   - TLB invalidation hooks.
2. Add debug events/tracing channel:
   - instruction trace (optional),
   - memory access trace (filterable),
   - trap/fault stream.
3. Add debug server mode:
   - first target: GDB remote protocol subset sufficient for single-step, register read/write, memory read/write, breakpoints.
4. Add deterministic execution mode:
   - fixed seed, deterministic timers/device ordering to make OS bugs reproducible.

### Acceptance criteria

- Headless emulator can be run under scripted debug sessions.
- Page fault and trap states are inspectable without GUI.

### Progress so far

- A modular headless debug skeleton exists (`little-64-debug`) with transport abstraction and command server over `IEmulatorRuntime`.
- This is not a GDB remote implementation yet, but it establishes the seam where a GDB transport can plug in.

---

## Phase 4 — Unified Testing & Clean Output (1–2 weeks)

Status: 🟡 Started

### Objectives

- One command to run all tests with uniform reporting and CI friendliness.

### Changes

1. Standardize test execution through Meson as the single entrypoint:
   - unit tests: `meson test -C builddir --suite ...`,
   - integration/LLVM tests wrapped as Meson test targets.
2. Replace custom assertion macros over time with a single framework:
   - options: Catch2 or doctest,
   - keep adapter utilities for CPU setup/assembly helpers.
3. Convert `tests/llvm/scripts/run_tests.py` into either:
   - a Meson-invoked executable/script that outputs TAP/JUnit/JSON,
   - or split into smaller integration test binaries where practical.
4. Add test taxonomy and tags:
   - `unit`, `integration`, `isa`, `device`, `toolchain`, `slow`.
5. Enforce clean output:
   - default concise mode (pass/fail summary),
   - verbose mode only on failure or with explicit flag.

### Acceptance criteria

- `meson test -C builddir` runs all test categories.
- CI artifact includes machine-readable report (JUnit or JSON).
- Every major subsystem has at least one focused unit test file:
  - assembler, encoder, disassembler,
  - cpu core (decode/execute),
  - memory bus/MMU,
  - each device,
  - linker/project runner paths.

### Progress so far

- LLVM integration tests are wired into Meson as `llvm-integration`.
- Test runner output is cleaner and timeout diagnostics are improved.

---

## Immediate High-Value Tasks (start now)

1. Add Meson target `test('llvm-integration', ...)` that calls current Python script.
2. Introduce a common test utility layer (`tests/support/`) and stop adding new ad-hoc macros.
3. Define `MachineConfig` (even minimal) and migrate ROM/RAM/UART setup through it.
4. Add a headless run mode contract doc (CLI args, deterministic mode, trace flags).
5. Add CI workflow that runs:
   - build,
   - fast unit suites,
   - LLVM integration suite.

### Implemented in this branch

- Introduced `emulator/frontend_api.hpp` with `IEmulatorRuntime` as the stable frontend contract.
- Added reusable headless runtime helpers in `emulator/headless_runtime.hpp/.cpp` (image loading + run loop).
- Updated `emulator/main.cpp` (CLI emulator entrypoint) to use that shared headless runtime path.
- Added `little-64-debug` as a modular headless debug entrypoint:
   - transport abstraction: `emulator/debug_transport.hpp` (`IDebugTransport`),
   - debug core: `emulator/debug_server.hpp/.cpp`,
   - stdio adapter: `StdioDebugTransport`,
   - entrypoint wiring: `emulator/debug_main.cpp`.
   - Integrated LLVM tests into Meson (`llvm-integration`) and centralized required test environment in `meson.build`.
   - Added declarative `MachineConfig` + `Device` lifecycle framework and migrated CPU program-loading paths to use it.

This makes the future debug-server entrypoint straightforward: a new transport layer can drive the same `IEmulatorRuntime` + headless loader/loop without duplicating emulator startup logic.

---

## Proposed Repository Conventions

- `tests/unit/...` for small isolated behavior tests.
- `tests/integration/...` for multi-component execution tests.
- `tests/fixtures/...` for asm/c inputs.
- `tests/support/...` for reusable harness/helpers.
- `docs/adr/...` for architecture decisions (e.g., debugger protocol, MMU design).

---

## Risks & Mitigations

- **Risk:** large refactor stalls ISA feature work.
  - **Mitigation:** do phased migration with compatibility wrappers.
- **Risk:** GUI and headless paths diverge.
  - **Mitigation:** shared emulator API and shared debug event bus.
- **Risk:** flaky tests with timing/device behavior.
  - **Mitigation:** deterministic mode and strict test fixtures.

---

## Definition of “Clean Enough” Before Major ISA Expansion

Proceed with major paging and OS features only after:

1. Single-command test run exists and is stable.
2. Device registration is declarative (no scattered wiring).
3. Headless debug flow exists (not GUI-only).
4. MMU abstraction exists, even if feature-minimal.

This keeps architecture work focused and prevents compounding technical debt while moving toward UNIX-like OS support.
