# Little-64 HDL Subsystem

This document describes the initial HDL implementation subtree under `hdl/`.

## Scope

The HDL subsystem is a hardware implementation effort for the Little-64 ISA.

Initial goals:

- implement the core ISA in Amaranth,
- keep the CPU LiteX-compatible at the bus and wrapper boundary,
- use 64-bit instruction and data buses,
- keep a parameterized TLB in the design,
- make architectural special registers `12..15` optional and toggleable.

Current implemented execution support includes:

- `LDI` / `LDI.S1` / `LDI.S2` / `LDI.S3`,
- the GP ALU space used by the existing shared arithmetic tests,
- special-register `LSR` / `SSR` execution, including selector normalization and user-mode access checks,
- privileged GP control instructions `SYSCALL`, `IRET`, and `STOP`,
- unconditional jumps plus conditional LS jump forms,
- basic LS register-form addressing for `LOAD` / `STORE`, byte/short/word loads and stores, and `MOVE`.

The HDL core now performs exception and maskable IRQ vector delivery through the architectural interrupt table and saves `interrupt_epc`, `interrupt_eflags`, and `interrupt_cpu_control` for `IRET`. Interrupt-table fetches now run through paging in supervisor mode when paging is enabled, and handler-fetch failure during entry causes architectural lockup. Trap and interrupt coverage includes synchronous exception entry, paged and unpaged handler fetch, and return-to-context sequencing in simulation. Page walking and privileged MMU execution are still in progress.

## Source Of Truth

- ISA contract: `docs/hardware/`
- Golden behavioral reference: `host/emulator/cpu.*`, `host/emulator/address_translator.*`
- HDL implementation: `hdl/little64/`
- HDL tests: `hdl/tests/`

If the HDL conflicts with the ISA docs or proving tests, the HDL should be corrected unless the docs are stale.

## Current Layout

- `hdl/little64/config.py` — core configuration and architectural build-time choices
- `hdl/little64/wishbone.py` — 64-bit LiteX-compatible bus signal bundle
- `hdl/little64/tlb.py` — direct-mapped TLB module
- `hdl/little64/special_registers.py` — architected special-register storage
- `hdl/little64/core.py` — single-issue core FSM with fetch, GP ALU, jumps, and basic LSU execution
- `hdl/little64/litex.py` — LiteX-facing wrapper shim
- `hdl/tests/` — Python simulation and unit tests, including shared backend-neutral ISA/program coverage

## Detailed Missing Features

The major execution and privileged-state gaps called out in the earlier HDL
audit are now implemented and covered in simulation. The HDL core now includes:

- LS register-format `PUSH` / `POP`
- LS PC-relative non-jump forms for loads, stores, `MOVE`, `PUSH`, and `POP`
- GP atomics `LLR` / `SCR`, including overlapping-store reservation invalidation
- special-register selector normalization for the architected user-visible bank
- `cpu_control` reserved-bit masking
- no-MMU `page_table_root_physical` ignore-on-write / zero-on-read behavior
- invalid-non-leaf paging faults for malformed L0 table entries

The remaining known HDL issue in this area is architectural reconciliation, not
missing execution support.

### Spec-Reconciliation Items

- The current HDL and emulator both treat PTE bits `63:54` as reserved during
	translation, while the hardware reference currently describes bits `63:10` as
	the `PPN` field. This is a live architecture/documentation mismatch that still
	needs reconciliation.

## Running HDL Tests

Install HDL dependencies:

```bash
./.venv/bin/pip install -r requirements-hdl.txt
```

The HDL pytest configuration enables `pytest-xdist` with `-n auto` by default so
direct HDL test runs use the available machine parallelism automatically. To
force a serial run while debugging, pass `-n 0` explicitly.

Run tests directly:

```bash
./.venv/bin/python -m pytest -q hdl/tests
```

Or enable the optional Meson subtree and run the HDL suite through Meson.

Useful targeted Meson suites after configuring `-Dhdl=enabled`:

```bash
meson test -C builddir-hdl --suite gp --suite ldi --print-errorlogs
meson test -C builddir-hdl --suite jumps --suite memory --print-errorlogs
```

The shared `gp`, `ldi`, `jumps`, and `memory` suites are intended to run both the emulator and HDL backends against the same backend-neutral case files wherever the instruction subset overlaps.
