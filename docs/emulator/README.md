# Little-64 Emulator Documentation

This directory documents the behavior of the current Little-64 emulator and its
default LiteX-compatible virtual platform.

Unlike the hardware ISA reference under `docs/hardware/`, this documentation is
implementation-specific. It covers details that software can observe on the
current emulator but that are not part of the core ISA contract.

## Scope

This emulator documentation defines the current behavior for:

1. runtime execution order and reset/load behavior,
2. the software translation cache and other implementation details,
3. boot modes and loader handoff contracts,
4. the default LiteX-compatible virtual machine memory map,
5. the DTB-backed device model and device register behavior.

## Chapter Map

| File | Scope |
|---|---|
| `runtime-model.md` | cycle order, program-load state, software TLB, and other implementation-specific CPU runtime behavior |
| `boot-and-loader.md` | minimal boot hypercalls, boot payloads, BIOS/direct boot flows, ELF loader behavior, and DTB placement |
| `virtual-platform.md` | default LiteX virtual machine memory map, DTB contract, LiteUART, timer, LiteSDCard, and legacy compatibility device behavior |

## Recommended Read Order

1. `../hardware/README.md`
2. `README.md`
3. `runtime-model.md`
4. `boot-and-loader.md`
5. `virtual-platform.md`

## Source Of Truth

Primary implementation sources:

- `host/emulator/cpu.hpp`
- `host/emulator/cpu.cpp`
- `host/emulator/address_translator.hpp`
- `host/emulator/address_translator.cpp`
- `host/emulator/little64.dts`
- `host/emulator/lite_sdcard_device.*`
- `host/emulator/lite_uart_device.*`
- `host/emulator/serial_device.*`
- `host/emulator/timer_device.*`
- `host/emulator/pv_block_device.*`

Primary proving tests:

- `tests/target/test_cpu_special.cpp`
- `tests/host/test_paging.cpp`
- `tests/host/test_tlb.cpp`
- `tests/host/test_devices.cpp`
- `tests/host/boot/test_direct_boot_paging.py`

If emulator documentation disagrees with implementation, implementation is
authoritative and the docs should be updated in the same change.