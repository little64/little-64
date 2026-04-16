# Emulator Virtual Platform

This chapter documents the default virtual machine and its devices.

## Default Machine Map

| Region | Base | Size | Meaning |
|---|---|---|---|
| RAM | `0x00100000` | `0x03F00000` | 63 MiB Linux-visible RAM window |
| UART | `0x08000000` | `0x8` | ns16550a-compatible subset |
| Timer | `0x08001000` | `0x20` | dual-mode timer |
| PV block | `0x08002000` | `0x100` | paravirtual block device |

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
| 67 | paravirtual block device |

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
- `host/emulator/serial_device.*`
- `host/emulator/timer_device.*`
- `host/emulator/pv_block_device.*`
- `host/emulator/machine_config.cpp`

Primary proving tests:

- `tests/host/test_devices.cpp`