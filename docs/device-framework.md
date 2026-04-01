# Device Framework (Phase 2)

Date: 2026-04-01

This document describes the current device architecture after Phase 2 cleanup.

## Core Concepts

- `Device` (`emulator/device.hpp`)
  - Extends `MemoryRegion`.
  - Adds lifecycle hooks:
    - `reset()` for deterministic reinitialization,
    - `tick()` for per-cycle progression.
- `MachineConfig` (`emulator/machine_config.hpp/.cpp`)
  - Declarative memory-map and device registration.
  - Provides fluent helpers for common regions/devices.
  - Materializes the map into `MemoryBus` with one `applyTo()` call.

## CPU Integration

- `Little64CPU::loadProgram()` and `loadProgramElf()` create machine layout through `MachineConfig`.
- `Little64CPU::reset()` resets all registered devices.
- `Little64CPU::cycle()` ticks all registered devices each instruction cycle.

## Existing Device: Serial

- `SerialDevice` now derives from `Device`.
- `SerialDevice::reset()` clears FIFOs and register state.
- `SerialDevice::tick()` currently no-op (reserved for future timing behavior).

## Add a New Device

Use the scaffold helper:

```bash
python3 tools/new_device.py TimerDevice
```

Then:

1. Add generated source file to `core_emulator_src` in `meson.build`.
2. Register the device in machine setup via `MachineConfig`.
3. Add/update tests in `tests/test_devices.cpp` (or additional test files).

## Test Coverage

- Device conformance tests live in `tests/test_devices.cpp`.
- Included in Meson as suite `device`:

```bash
meson test -C builddir --suite device
```
