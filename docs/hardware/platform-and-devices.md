# Platform Boundary

This chapter defines what the core Little-64 ISA does and does not specify at platform level.

## Scope Boundary

The core ISA reference does not define:

- a machine memory map,
- a peripheral set,
- MMIO register maps,
- device-discovery formats,
- firmware services,
- loader handoff payloads.

Those are platform-defined concerns rather than core ISA behavior.

## Architecturally Reserved Platform Hooks

The ISA does reserve some integration space for platform-defined behavior:

| Resource | Meaning |
|---|---|
| vectors `65..127` | hardware IRQ space available for platform assignment |
| special-register selector `12` | platform-defined boot/environment pointer |
| special-register selector `13` | platform-defined boot-source granularity |
| special-register selector `14` | platform-defined boot-source count |
| special-register selector `15` | platform-defined capability/control register |

These hooks allow a platform specification to define boot, firmware, and device contracts without changing the core instruction set.
Software MUST NOT assume these are always writeable with any value. The special registers numbered above MUST return either all-zeros or all-ones, and ignore any writes, to signal not being present. If they are present, software MAY use them as temporary per-core scratch space, and they MUST be readable and writeable. The hardware MUST NOT use these registers for hardware configuration.

## Conformance Implication

A conforming Little-64 implementation MAY provide:

- no MMIO devices,
- a different peripheral set,
- a different interrupt assignment,
- a different firmware environment,
- no device tree at all.

Software that depends on a specific machine profile MUST bind to that profile's platform documentation, not just the core ISA. However, despite these freedoms in implementation, it is strongly RECOMMENDED that any given implementation uses a device tree, provides a timer controllable over MMIO, and a generic UART peripheral.

## Drift Checklist

Update this chapter when any of the following change:

1. the architecturally reserved IRQ range,
2. the architecturally reserved platform-integration register set,
3. the scope boundary between core ISA behavior and platform-defined behavior.