# Tracing

The Little-64 emulator includes a high-performance binary tracing subsystem
for recording CPU events during execution.  All trace data is written in the
L64T binary format (41 bytes per event) and decoded offline with
`target/linux_port/l64trace.py`.

## Quick Start

```bash
# Boot Linux with default tracing (control flow + boot events + MMIO)
target/linux_port/boot_direct.sh

# Decode the trace
target/linux_port/l64trace.py stats /tmp/little64_boot_events.l64t
target/linux_port/l64trace.py tail  /tmp/little64_boot_events.l64t -n 50
target/linux_port/l64trace.py watch /tmp/little64_boot_events.l64t
```

## CLI Flags

These flags are passed directly to the emulator binary.

| Flag | Purpose |
|------|---------|
| `--trace-control-flow` | Record non-fallthrough PC changes (jumps, branches, odd PCs, out-of-bounds) |
| `--trace-mmio` | Log device MMIO reads/writes to stderr |
| `--boot-events` | Dump the 128-entry boot event ring buffer to stderr on exit |
| `--boot-events-file=PATH` | Stream full event history to a binary L64T file |
| `--boot-events-max-mb=N` | Cap trace file size at N megabytes (default: unlimited) |
| `--trace-start-cycle=N` | Only record events at or after cycle N |
| `--trace-end-cycle=N` | Only record events at or before cycle N |
| `--max-cycles=N` | Stop after N cycles; auto-enables boot events and final registers |
| `--final-registers` | Dump final CPU register state to stderr on exit |

## Environment Variables

Environment variables configure fine-grained trace features.  They are read
by the CPU constructor at startup and cannot be changed at runtime.

### Cycle-Window Filtering

Limits which cycles are recorded when `--boot-events-file` is active.

| Variable | Default | Description |
|----------|---------|-------------|
| `LITTLE64_TRACE_START_CYCLE` | `0` | First cycle to include |
| `LITTLE64_TRACE_END_CYCLE` | `UINT64_MAX` | Last cycle to include |

### Control Flow Tracing

Alternative to the `--trace-control-flow` CLI flag.

| Variable | Default | Description |
|----------|---------|-------------|
| `LITTLE64_TRACE_CONTROL_FLOW` | `0` | Set to `1` to enable |

Tags emitted:

- **`pc-flow`** — non-fallthrough PC change (a=from, b=to, c=instruction word)
- **`pc-odd`** — odd PC detected (misaligned fetch)
- **`pc-below-ram`** — PC fell below RAM base

### Memory Write Watchpoints

Monitor writes to a virtual address range.  Only **write** operations
(8/16/32/64-bit) trigger events; reads are not traced.

| Variable | Default | Description |
|----------|---------|-------------|
| `LITTLE64_TRACE_WATCH` | `0` | Set to `1` to enable |
| `LITTLE64_TRACE_WATCH_START` | — | Start of watched address range (hex or decimal) |
| `LITTLE64_TRACE_WATCH_END` | — | End of watched address range (inclusive) |

Both `START` and `END` must be set when `LITTLE64_TRACE_WATCH=1`.

Tags emitted:

- **`watch-write8`** — 8-bit write (a=address, b=value, c=pc)
- **`watch-write16`** — 16-bit write
- **`watch-write32`** — 32-bit write
- **`watch-write64`** — 64-bit write
- **`watch-regs`** — register snapshot at time of write (a=R11, b=R12, c=R13)

Example:

```bash
LITTLE64_TRACE_WATCH=1 \
  LITTLE64_TRACE_WATCH_START=0xffffffc0006a3f40 \
  LITTLE64_TRACE_WATCH_END=0xffffffc0006a3f70 \
  target/linux_port/boot_direct.sh
```

### Link Register (LR) Tracing

Traces R14/R15 changes during PUSH, POP and MOVE operations within a PC
window.  Designed for debugging call/return sequences and stack corruption.

| Variable | Default | Description |
|----------|---------|-------------|
| `LITTLE64_TRACE_LR` | `0` | Set to `1` to enable |
| `LITTLE64_TRACE_LR_START` | `0` | PC window start (inclusive) |
| `LITTLE64_TRACE_LR_END` | `UINT64_MAX` | PC window end (inclusive) |

If `START > END`, the values are automatically swapped.

Tags emitted:

- **`lr-ls-pre`** / **`lr-ls-post`** — before/after LS operation
- **`lr-regs-pre`** / **`lr-regs-post`** — R13, R14 snapshots
- **`lr-r15`** — R15 (PC) and flags
- **`lr-r1r12`** — R1 and R12 snapshot
- **`r1-change`** / **`r1-change-op`** — R1 changed during instruction
- **`r11-change`** / **`r11-change-op`** — R11 changed during instruction
- **`lr-mem-write`** — memory written during PUSH
- **`lr-mem-read`** — memory read during POP

Example:

```bash
LITTLE64_TRACE_LR=1 \
  LITTLE64_TRACE_LR_START=0xffffffc0000ad000 \
  LITTLE64_TRACE_LR_END=0xffffffc0000b4700 \
  target/linux_port/boot_direct.sh
```

### PC Probe (Instruction-Level Inspection)

Captures the full CPU register state each time the PC matches one of two
configurable addresses.  Useful for inspecting function entry, loop heads,
or a specific suspicious instruction.

| Variable | Default | Description |
|----------|---------|-------------|
| `LITTLE64_TRACE_PC_PROBE` | `0` | Set to `1` to enable |
| `LITTLE64_TRACE_PC_PROBE0` | — | First PC address to probe |
| `LITTLE64_TRACE_PC_PROBE1` | same as `PC_PROBE0` | Second PC address to probe |
| `LITTLE64_TRACE_PC_PROBE_DEREF` | `0` | Set to `1` to dereference R10/R11 pointers |
| `LITTLE64_TRACE_PC_PROBE_LIMIT` | unlimited | Maximum number of probes to record |

Tags emitted:

- **`pc-probe`** — instruction word and flags (a=instruction, b=flags)
- **`pc-probe-r8r9`** — R8, R9
- **`pc-probe-r10r1`** — R10, R1
- **`pc-probe-r3r4`** — R3, R4
- **`pc-probe-r5r12`** — R5, R12
- **`pc-probe-r6r7`** — R6, R7
- **`pc-probe-r2r11`** — R2, R11
- **`pc-probe-r14r15`** — R14, R15

When `LITTLE64_TRACE_PC_PROBE_DEREF=1`:

- **`pc-probe-r10mem0`** through **`pc-probe-r10mem4`** — memory at R10+0, R10+8, R10+16, R10+24, R10+32 (each event packs two 8-byte reads)
- **`pc-probe-r11mem`** — memory at R11+0, R11+8

Example:

```bash
LITTLE64_TRACE_PC_PROBE=1 \
  LITTLE64_TRACE_PC_PROBE0=0xffffffc000013816 \
  LITTLE64_TRACE_PC_PROBE_DEREF=1 \
  LITTLE64_TRACE_PC_PROBE_LIMIT=100 \
  target/linux_port/boot_direct.sh
```

## Always-On Tags

These tags are emitted unconditionally (no env var or flag required):

| Tag | Description |
|-----|-------------|
| `reset` | CPU reset event |
| `fetch-failed` | Instruction fetch failed (trap raised) |
| `irq-raise` | Hardware IRQ vector raised (device IRQ vectors currently start at 65) |
| `exception-raise` | Exception vector raised (current exception vectors occupy 1..8) |
| `exception-lockup` | Exception could not safely enter a handler |
| `interrupt-no-handler` | No handler for the recorded vector number |
| `self-loop-lockup` | Infinite loop with interrupts disabled |
| `uart-tx` | Character written to UART |

## Binary Format (L64T v1)

```
Header (64 bytes):
  [0..3]    magic "L64T"
  [4..7]    version (uint32 LE)
  [8..11]   flags (uint32 LE)
  [12..15]  tag_count (uint32 LE)
  [16..23]  event_count (uint64 LE)
  [24..31]  total_events_written (uint64 LE)
  [32..39]  tag_table_offset (uint64 LE)
  [40..47]  events_offset (uint64 LE)
  [48..63]  reserved

Event records (41 bytes each, at events_offset):
  [0]       tag_id (uint8)
  [1..8]    cycle (uint64 LE)
  [9..16]   pc (uint64 LE)
  [17..24]  a (uint64 LE)
  [25..32]  b (uint64 LE)
  [33..40]  c (uint64 LE)

Tag table (at tag_table_offset):
  Repeated: 1-byte length + name bytes (no NUL terminator)
```

The writer updates the header and tag table on every buffer flush so that
live watchers can decode tags from an in-progress file.

**Important**: Trace files (`.l64t`) are binary and cannot be read with
`cat` or text editors.  Always use `l64trace.py` subcommands.

## Decoder Tool (l64trace.py)

```bash
l64trace.py decode <file>                      # Full text conversion
l64trace.py stats <file>                       # File and tag statistics
l64trace.py tail <file> -n N                   # Last N events (default 100)
l64trace.py search <file> --tags TAG --pc 0xADDR  # Filter events
l64trace.py watch <file>                       # Live-tail (like tail -f)
```

The `watch` subcommand survives file recreation between emulator runs and
shows the last 20 events on startup (configurable with `-n`).

## Lockup Analyzer

```bash
target/linux_port/analyze_lockup_flow.py --log /tmp/little64_boot_events.l64t --tail 24
```

Detects control-flow loops, identifies suspect transfers (odd PC, below
RAM base), and optionally symbolizes addresses with `llvm-addr2line`.

## Combining Features

Multiple tracing features can be enabled simultaneously:

```bash
LITTLE64_TRACE_WATCH=1 \
  LITTLE64_TRACE_WATCH_START=0xffffffc0006a3f40 \
  LITTLE64_TRACE_WATCH_END=0xffffffc0006a3f70 \
LITTLE64_TRACE_PC_PROBE=1 \
  LITTLE64_TRACE_PC_PROBE0=0xffffffc000013816 \
LITTLE64_TRACE_LR=1 \
  LITTLE64_TRACE_LR_START=0xffffffc0000ad000 \
  LITTLE64_TRACE_LR_END=0xffffffc0000b4700 \
LITTLE64_TRACE_START_CYCLE=50000000 \
  LITTLE64_TRACE_END_CYCLE=60000000 \
  target/linux_port/boot_direct.sh
```

All features write to the same L64T stream and can be filtered offline
with `l64trace.py search --tags`.

## Boot Event Ring Buffer

Independent of `--boot-events-file`, the emulator maintains a 128-entry
circular ring buffer of the most recent boot events.  This buffer is dumped
to stderr on exit when `--boot-events` is set or the emulator exits
abnormally.  It provides a fallback when no trace file was configured.
