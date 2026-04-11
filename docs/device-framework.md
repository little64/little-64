# Little-64 Device Framework

This document describes how MMIO devices are modeled and integrated.

## Source of Truth

- Base class: `host/emulator/device.hpp`
- Machine composition: `host/emulator/machine_config.hpp/.cpp`
- Runtime usage: `host/emulator/cpu.cpp`
- Existing device implementation: `host/emulator/serial_device.hpp/.cpp`
- Device tests: `tests/host/test_devices.cpp`

## Core Model

### `Device`

`Device` extends `MemoryRegion` and adds lifecycle hooks:

- `reset()` — deterministic reset behavior
- `tick()` — per-cycle progression
- optional interrupt-line wiring via `connectInterruptSink(...)` and `setInterruptLine(...)`

### `MachineConfig`

`MachineConfig` is the declarative wiring layer for memory regions and devices.

Typical flow:

1. Add RAM/ROM/devices to config.
2. Call `applyTo(bus, devices, interrupt_sink)`.
3. Runtime uses resulting `MemoryBus` + device list.

## Runtime Integration Points

In `Little64CPU`:

- program/image load builds map through `MachineConfig`,
- `reset()` cascades to all devices,
- `cycle()` ticks all devices.
- configured devices can assert/clear CPU interrupt lines through `InterruptSink`.
- `--trace-mmio` / `setMmioTrace(true)` now enables shared MMIO tracing on all attached devices via `Device` trace hooks.

## MMIO Tracing

All `Device` instances inherit shared MMIO trace support.

- Base behavior is implemented in `host/emulator/device.hpp` and emitted from `host/emulator/memory_bus.cpp`.
- The default formatter logs device name, access width, region-relative offset, and value.
- Devices can override the trace formatting when they need richer output; `SerialDevice` does this to preserve printable TX byte logging.
- Headless CLI flag `--trace-mmio` toggles this path for every attached device, not only UART.

## Adding a New Device

### Step 1: scaffold

```bash
python3 host/tools/new_device.py TimerDevice
```

### Step 2: register source file

Add generated source to:

- `host/emulator/meson.build` (`core_emulator_src` list)

### Step 3: register in machine composition

Wire the device in `MachineConfig` setup path.

### Step 4: test

Add conformance tests to `tests/host/test_devices.cpp` (or a new dedicated device test file).

## Test Command

```bash
meson test -C builddir --suite device --print-errorlogs
```

## Design Guidance

1. Keep register map and side effects local to the device class.
2. Use `reset()` to return to power-on state.
3. Use `tick()` only when time progression matters.
4. Prefer the shared `Device` MMIO trace hooks over ad-hoc `fprintf` logging inside device read/write methods.
5. Avoid scattered ad-hoc memory-map edits outside `MachineConfig`.

## Update Checklist

When changing device framework behavior:

- update this file,
- update `CLAUDE.md` device section if workflow changed,
- run full tests (not only device suite) when map/lifecycle behavior changed.
