# Emulator Virtual Platform

This chapter documents the default LiteX-compatible virtual machine used by the
current Linux helper flow and the legacy compatibility devices that still exist
for explicit manual emulator modes.

## Default Machine Map

The canonical `little64 boot run` and direct-loader Linux path
use the LiteX SD-capable layout below.

These CSR locations are intentionally fixed for the canonical Little64 LiteX
helper contract. The native LiteX SoC reserves the matching CSR slots in
`hdl/little64_cores/litex_soc.py`, and the generated DTS/stage-0 artifacts plus
the emulator's `--machine=litex` bootrom-first path are expected to stay in
sync with this table unless the project intentionally changes the contract.

| Region | Base | Size | Meaning |
|---|---|---|---|
| Boot ROM | `0x00000000` | `0x00008000` | integrated boot ROM window |
| SRAM | `0x10000000` | `0x00004000` | LiteX integrated SRAM used by early boot code |
| Flash window | `0x20000000` | `0x01000000` | erased SPI flash compatibility window |
| RAM | `0x40000000` | `0x10000000` | 256 MiB flat RAM matching the Arty A7-35T SDRAM contract |
| LiteSDCard reader | `0xF0000800` | `0x18` | block-to-memory DMA window |
| LiteSDCard core | `0xF0001000` | `0x2c` | command, response, and transfer status CSRs |
| LiteSDCard IRQ | `0xF0001800` | `0x0c` | interrupt pending and enable CSRs |
| LiteSDCard writer | `0xF0002000` | `0x1c` | memory-to-block DMA window |
| LiteSDCard PHY | `0xF0002800` | `0x1c` | card-detect and clocking CSRs |
| LiteDRAM DFII stub | `0xF0003000` | `0x00000100` | functional CSR stub for generated LiteDRAM init sequences |
| LiteUART | `0xF0004000` | `0x100` | LiteX LiteUART-compatible CSR subset |
| Timer | `0x08001000` | `0x20` | dual-mode timer |

## Explicit Manual LiteX Variants

The emulator still exposes smaller manual LiteX layouts for raw
`--boot-mode=litex-flash` and `--boot-mode=litex-bootrom` runs when no SD image
is attached.

### LiteX Flash Without SD

| Region | Base | Size | Meaning |
|---|---|---|---|
| RAM | `0x00000000` | `0x04000000` | 64 MiB RAM, with Linux still using the top 63 MiB via DT |
| Flash | `0x20000000` | `0x01000000` | raw SPI flash image window |
| LiteUART | `0xF0001000` | `0x100` | LiteX LiteUART-compatible CSR subset |
| Timer | `0x08001000` | `0x20` | dual-mode timer |

### LiteX Boot ROM Without SD

| Region | Base | Size | Meaning |
|---|---|---|---|
| Boot ROM | `0x00000000` | `0x00008000` | raw internal boot ROM image window |
| SRAM | `0x10000000` | `0x00004000` | LiteX integrated SRAM used by the early boot stack and scratch state |
| Flash window | `0x20000000` | `0x01000000` | erased SPI flash compatibility window |
| RAM | `0x40000000` | `0x10000000` | 256 MiB flat RAM matching the Arty A7-35T SDRAM contract |
| LiteDRAM DFII stub | `0xF0003000` | `0x00000100` | functional CSR stub for generated LiteDRAM init sequences |
| LiteUART | `0xF0001000` | `0x100` | LiteX LiteUART-compatible CSR subset |
| Timer | `0x08001000` | `0x20` | dual-mode timer |

Attaching an SD image to the explicit manual `litex-bootrom` mode enables the
LiteSDCard CSR windows and moves the LiteUART base to the canonical SD-capable
address used by the default machine map above.

Attaching an SD image to the explicit manual `litex-flash` mode is a separate
legacy compatibility path. It still exposes LiteUART at `0xF0003800` rather
than the canonical `0xF0004000`, so it should not be treated as the source of
truth for the current bootrom-first Little64 LiteX helper contract.

## Device Tree Description

The embedded DTB currently describes:

- compatible machine: `little64,litex-sim`, `little64,bootrom`
- model: `Little64 LiteX Emulator Machine`
- one CPU at 1 MHz
- RAM at `0x40000000` with size `0x10000000`
- LiteUART at `0xF0004000`, IRQ 65
- timer at `0x08001000`, IRQ 66
- LiteSDCard at IRQ 67 with its five LiteX CSR windows
- the LiteSDCard slot as `non-removable` for the default boot profile

The `chosen` node sets:

- `stdout-path = "serial0:115200n8"`
- a Linux-oriented bootargs string that expects `/dev/mmcblk0p2` as the root filesystem

## IRQ Assignments

Default LiteX paths use:

| Vector | Source |
|---|---|
| 65 | LiteUART |
| 66 | timer |
| 67 | LiteSDCard |

The legacy compatibility devices described later in this chapter reuse IRQ 65
for the ns16550A UART and IRQ 67 for the PV block device.

## LiteUART Model

### Register Map

| Offset | Access | Meaning |
|---|---|---|
| `+0x00` | `R/W` | `RXTX` |
| `+0x04` | `R` | `TXFULL` |
| `+0x08` | `R` | `RXEMPTY` |
| `+0x0c` | `R` | `EV_STATUS` |
| `+0x10` | `R/W` | `EV_PENDING` |
| `+0x14` | `R/W` | `EV_ENABLE` |

### Behavior

1. TX completes immediately and appends bytes to the host-side UART output stream.
2. `TXFULL` always reads `0`.
3. `RXEMPTY` reads `1` when no queued input is available, otherwise `0`.
4. `EV_STATUS[0]` reports TX-ready and `EV_STATUS[1]` reports RX-ready.
5. `EV_PENDING` is the enabled subset of `EV_STATUS`.
6. Enabling the TX event immediately asserts IRQ 65 because the transmitter is always ready.
7. RX bytes are consumed by reading `RXTX`.

## LiteSDCard Model

The SD-capable LiteX machine exposes the five LiteX MMC register windows used by
the current stage-0 loader and Linux host driver.

The current model:

1. backs CMD17/CMD18 and CMD24/CMD25 transfers with the attached raw disk image,
2. implements CMD6, ACMD51, and ACMD13 completion semantics expected by the stage-0 loader even when no LiteX DMA engine is armed,
3. drives the LiteX IRQ pending and enable registers so the Linux LiteX MMC driver can complete command-done waits through IRQ 67,
4. reports a present card whenever an SD image is attached,
5. accepts the Linux helper's split 64-bit DMA base writes in high32-then-low32 order.

## LiteDRAM DFII Stub

The LiteX bootrom path exposes a minimal LiteDRAM DFII CSR model at
`0xF0003000`, and the default LiteX helper now generates stage-0 artifacts that
exercise it before SD boot.

The current stub is intentionally functional rather than cycle-accurate:

1. it provides the control, command, address, and bank-address registers used by LiteDRAM's generated `init_sequence()` helper,
2. it preserves guest writes so bootrom code can switch between hardware and software DFII control and issue the expected initialization commands,
3. it leaves read-data windows zero-filled and does not emulate real PHY training progress,
4. the Arty-sized main RAM window is already usable, so the stub exists only to keep the generated bootrom SDRAM-init code from faulting under emulation.

## Timer Model

### Register Map

| Offset | Access | Meaning |
|---|---|---|
| `+0` | `R` | cycle counter |
| `+8` | `R` | virtual nanoseconds |
| `+16` | `R/W` | cycle interval |
| `+24` | `R/W` | nanosecond interval |

### Behavior

1. a non-zero cycle interval schedules IRQ 66 at `current_cycles + interval`,
2. a non-zero nanosecond interval schedules IRQ 66 at `current_virtual_ns + interval`,
3. either threshold can fire the interrupt,
4. writing `0` disables the corresponding interval and clears the interrupt line,
5. byte writes are ignored.

There is no separate guest-visible interrupt acknowledge register for the timer.

## Legacy Compatibility Devices

The emulator still carries the older ns16550A UART and PV block device for
explicit manual compatibility paths. They are not part of the default LiteX DTB,
they are not used by `little64 boot run`, and they should not be
treated as the current Linux-helper contract.

### ns16550A UART Model

| Offset | Access | Meaning |
|---|---|---|
| `+0` | `R/W` | `RBR` / `THR` when `DLAB=0`, `DLL` when `DLAB=1` |
| `+1` | `R/W` | `IER` when `DLAB=0`, `DLM` when `DLAB=1` |
| `+2` | `R/W` | `IIR` on read, `FCR` on write |
| `+3` | `R/W` | `LCR` |
| `+4` | `R/W` | `MCR` |
| `+5` | `R` | `LSR` |
| `+6` | `R` | `MSR` |
| `+7` | `R/W` | `SCR` |

Behavior notes:

1. `IER[0]` enables RX-ready interrupts and `IER[1]` enables THRE interrupts.
2. `IIR` returns `0x04` for RX-ready, `0x02` for THRE, and `0x01` when no interrupt is pending.
3. `LSR[0]` reports data ready, `LSR[5]` reports THRE, and `LSR[6]` reports TEMT.
4. `MSR` returns `0xB0`.
5. `FCR` writes are accepted and ignored.
6. TX completes immediately and RX data is injected through an internal FIFO.

### PV Block Device Model

| Offset | Access | Meaning |
|---|---|---|
| `+0x00` | `R` | magic |
| `+0x08` | `R` | version |
| `+0x10` | `R` | sector size |
| `+0x18` | `R` | sector count |
| `+0x20` | `R` | max sectors per request |
| `+0x28` | `R` | feature bits |
| `+0x30` | `R` | device status |
| `+0x38` | `R/W` | guest request-header address |
| `+0x40` | `W` | submit request when written with `1` |
| `+0x48` | `W` | clear interrupt pending when written with `1` |

Completion status values written back into the request header:

| Value | Meaning |
|---|---|
| 0 | OK |
| 1 | I/O error |
| 2 | range error |
| 3 | unsupported |
| 4 | read-only |
| 5 | invalid request |

Completion behavior:

1. the device writes the completion status back into the request header,
2. clears `busy`,
3. sets `interrupt pending`,
4. asserts IRQ 67,
5. waits for guest software to clear the pending state by writing `1` to the interrupt-acknowledge register.

## Reset-Visible Device State

| Device | Reset-visible state |
|---|---|
| LiteUART | TX/RX FIFOs empty, event-enable mask zero, IRQ line clear |
| Timer | intervals zero, next-fire timestamps zero |
| LiteSDCard | transfer state cleared, IRQ pending and enable cleared, card-selection state reset |
| ns16550A UART | FIFOs empty, IRQ line clear, divisor and control registers zero |
| PV block | request address zero, ready bit set, error cleared, interrupt line clear |

## Sources And Proving Tests

Primary implementation sources:

- `host/emulator/little64.dts`
- `host/emulator/lite_sdcard_device.*`
- `host/emulator/lite_uart_device.*`
- `host/emulator/serial_device.*`
- `host/emulator/timer_device.*`
- `host/emulator/pv_block_device.*`
- `host/emulator/machine_config.cpp`

Primary proving tests:

- `tests/host/test_devices.cpp`