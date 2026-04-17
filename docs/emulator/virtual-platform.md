# Emulator Virtual Platform

This chapter documents the default virtual machine and the LiteX-compatible
boot variants.

## Default Machine Map

| Region | Base | Size | Meaning |
|---|---|---|---|
| RAM | `0x00100000` | `0x03F00000` | 63 MiB Linux-visible RAM window |
| UART | `0x08000000` | `0x8` | ns16550a-compatible subset |
| Timer | `0x08001000` | `0x20` | dual-mode timer |
| PV block | `0x08002000` | `0x100` | paravirtual block device |

## LiteX Flash Machine Map

This map is kept for explicit manual `--boot-mode=litex-flash` runs.
The default `target/linux_port/boot_direct.sh --machine=litex` helper now
uses the LiteX boot-ROM machine map below so the emulator matches the
bootrom-first SDRAM-backed SoC contract used by real hardware targets.

| Region | Base | Size | Meaning |
|---|---|---|---|
| RAM | `0x00000000` | `0x04000000` | 64 MiB RAM, with Linux still using the top 63 MiB via DT |
| Flash | `0x20000000` | `0x01000000` | raw SPI flash image window |
| LiteUART | `0xF0001000` | `0x100` | LiteX LiteUART-compatible CSR subset |
| Timer | `0x08001000` | `0x20` | dual-mode timer |

## LiteX Boot ROM Machine Map

The `--boot-mode=litex-bootrom` path exposes the integrated-ROM Little64 LiteX
layout used by the current bootrom-first stage-0 flow and by the default
`--machine=litex` Linux boot helper path:

| Region | Base | Size | Meaning |
|---|---|---|---|
| Boot ROM | `0x00000000` | `0x00008000` | raw internal boot ROM image window |
| SRAM | `0x10000000` | `0x00004000` | LiteX integrated SRAM used by the early boot stack and scratch state |
| Flash window | `0x20000000` | `0x01000000` | erased SPI flash compatibility window |
| RAM | `0x40000000` | `0x10000000` | 256 MiB flat RAM matching the Arty A7-35T SDRAM contract |
| LiteDRAM DFII stub | `0xF0003000` | `0x00000100` | functional CSR stub for generated LiteDRAM init sequences |
| LiteUART | `0xF0001000` | `0x100` | LiteX LiteUART-compatible CSR subset |
| Timer | `0x08001000` | `0x20` | dual-mode timer |

When an SD image is attached on this bootrom path, the LiteSDCard CSR windows
start at `0xF0000800` and the LiteUART base shifts to `0xF0004000` because the
generated LiteX CSR layout also includes the LiteDRAM and SPI-flash controller
CSR pages ahead of the UART block.

## LiteX SD Machine Map

When `--boot-mode=litex-flash` is combined with an attached `--disk`, the
emulator switches to the SD-capable LiteX SoC layout:

| Region | Base | Size | Meaning |
|---|---|---|---|
| RAM | `0x00000000` | `0x04000000` | 64 MiB RAM, with Linux still using the top 63 MiB via DT |
| Flash | `0x20000000` | `0x01000000` | raw SPI flash image window containing stage-0 |
| LiteSDCard reader | `0xF0000800` | `0x18` | block-to-memory DMA window |
| LiteSDCard core | `0xF0001000` | `0x2c` | command, response, and transfer status CSRs |
| LiteSDCard IRQ | `0xF0001800` | `0x0c` | interrupt pending and enable CSRs |
| LiteSDCard writer | `0xF0002000` | `0x1c` | memory-to-block DMA window |
| LiteSDCard PHY | `0xF0002800` | `0x1c` | card-detect and clocking CSRs |
| LiteUART | `0xF0003800` | `0x100` | LiteX LiteUART-compatible CSR subset for the SD-capable SoC |
| Timer | `0x08001000` | `0x20` | dual-mode timer |

## Device Tree Description

The embedded DTB currently describes:

- compatible machine: `little64,virt`
- model: `Little-64 Virtual Machine`
- one CPU at 1 GHz
- RAM at `0x00100000` with size `0x03F00000`

The emulator and HDL smoke both keep the underlying RAM fabric mapped from
physical `0x0` through `0x03ffffff`. The first `0x00100000` is left out of the
Linux-visible DT memory window so stage-0 and other low-memory bootstrap state
can use that space without Linux allocating from it.
- UART at `0x08000000`, IRQ 65
- timer at `0x08001000`, IRQ 66
- PV block device at `0x08002000`, IRQ 67

The `chosen` node sets:

- `stdout-path = "/uart@8000000"`
- a Linux-oriented bootargs string that expects `/dev/l64blk0` as a read-only
  ext2 root filesystem and uses `/init`

## IRQ Assignments

| Vector | Source |
|---|---|
| 65 | UART |
| 66 | timer |
| 67 | paravirtual block device on the default machine, LiteSDCard on the LiteX SD machine |

## UART Model

### Register map

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

### Behavior

| Register/bit | Behavior |
|---|---|
| `IER[0]` | enables RX-ready interrupt |
| `IER[1]` | enables THRE interrupt |
| `IIR` | `0x04` for RX-ready, `0x02` for THRE, `0x01` for no interrupt |
| `LSR[0]` | data ready |
| `LSR[5]` | THRE |
| `LSR[6]` | TEMT |
| `MSR` | returns `0xB0` |
| `FCR` | accepted but ignored |

### Runtime notes

1. TX completes immediately.
2. TX data is appended to the host-side UART output stream.
3. RX data is injected into an internal FIFO from the host side.
4. If both RX-ready and THRE are pending, `IIR` reports RX-ready first.

## LiteUART Model

### Register map

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

### Register map

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

## Paravirtual Block Device Model

### Register map

| Offset | Access | Meaning |
|---|---|---|
| `+0x00` | `R` | magic = `0x4B4C42505634364C` |
| `+0x08` | `R` | version = `1` |
| `+0x10` | `R` | sector size = `512` |
| `+0x18` | `R` | sector count |
| `+0x20` | `R` | max sectors per request |
| `+0x28` | `R` | features |
| `+0x30` | `R` | status |
| `+0x38` | `R/W` | request descriptor physical address |
| `+0x40` | `W` | kick |
| `+0x48` | `W` | interrupt acknowledge |

### Feature bits

| Bit | Meaning |
|---|---|
| 0 | read-only disk |
| 1 | flush supported |

### Status bits

| Bit | Meaning |
|---|---|
| 0 | ready |
| 1 | busy |
| 2 | error |
| 3 | interrupt pending |

### Request header layout

| Word | Field |
|---|---|
| 0 | `op` |
| 1 | `status` |
| 2 | `sector` |
| 3 | `sector_count` |
| 4 | `buffer_phys` |
| 5 | `buffer_len` |
| 6 | `reserved0` |
| 7 | `reserved1` |

### Operation IDs

| Value | Meaning |
|---|---|
| 0 | read |
| 1 | write |
| 2 | flush |

### Completion status values

| Value | Meaning |
|---|---|
| 0 | OK |
| 1 | I/O error |
| 2 | range error |
| 3 | unsupported |
| 4 | read-only |
| 5 | invalid request |

### Completion behavior

On completion the current implementation:

1. writes the completion status back into the request header,
2. clears `busy`,
3. sets `interrupt pending`,
4. asserts IRQ 67,
5. waits for guest software to clear the pending state by writing `1` to the
   interrupt-acknowledge register.

## Reset-Visible Device State

| Device | Reset-visible state |
|---|---|
| UART | FIFOs empty, IRQ line clear, divisor and control registers zero |
| Timer | intervals zero, next-fire timestamps zero |
| PV block | request address zero, ready bit set, error cleared, interrupt line clear |

## Sources And Proving Tests

Primary implementation sources:

- `host/emulator/little64.dts`
- `host/emulator/lite_sdcard_device.*`
- `host/emulator/serial_device.*`
- `host/emulator/lite_uart_device.*`
- `host/emulator/timer_device.*`
- `host/emulator/pv_block_device.*`
- `host/emulator/machine_config.cpp`

Primary proving tests:

- `tests/host/test_devices.cpp`