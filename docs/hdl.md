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

The HDL core now performs exception and maskable IRQ vector delivery through the architectural interrupt table and saves `interrupt_epc`, `interrupt_eflags`, and `interrupt_cpu_control` for `IRET`. Interrupt-table fetches now run through paging in supervisor mode when paging is enabled, and handler-fetch failure during entry causes architectural lockup. Trap and interrupt coverage includes synchronous exception entry, paged and unpaged handler fetch, return-to-context sequencing in simulation, and privileged MMU page walking. The remaining HDL gaps are now primarily at the platform and harness level rather than in the core execution path.

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
- `hdl/tests/` — Python simulation and unit tests for unit and ISA coverage
- `hdl/tools/run_verilator_linux_boot_smoke.py` — compiled Linux boot smoke entrypoint using a Verilator-built harness

The current Python/Amaranth simulation path is appropriate for unit and ISA coverage but is too slow for practical full-Linux boot validation. Linux-on-HDL boot validation now uses a compiled Verilator harness instead of the pure Python simulator.

## Linux Boot Smoke

The Linux boot smoke is the practical full-system validation path for the HDL core.
It uses:

- `target/linux_port/build/vmlinux` as the kernel image,
- `target/linux_port/linux/arch/little64/boot/dts/little64.dts` as the DT source,
- `hdl/tools/export_linux_boot_verilog.py` to emit the standalone top-level Verilog,
- `hdl/tools/verilator_linux_boot_smoke_main.cpp` as the compiled harness,
- `hdl/tools/run_verilator_linux_boot_smoke.py` as the normal entrypoint.

### Prerequisites

Before running the smoke:

```bash
target/linux_port/build.sh vmlinux -j1
./.venv/bin/pip install -r requirements-hdl.txt
```

The wrapper also requires `verilator` and `dtc` to be installed on the host.
If `vmlinux`, `verilator`, or `dtc` are missing, the wrapper exits with code `77`.

### Recommended Wrapper Flow

Run the smoke through the Python wrapper:

```bash
./.venv/bin/python hdl/tools/run_verilator_linux_boot_smoke.py
```

The wrapper:

1. rebuilds `builddir/hdl-verilator-linux-boot/little64.dtb` when the DTS changes,
2. regenerates `builddir/hdl-verilator-linux-boot/little64_linux_boot_top.v` when HDL sources change,
3. rebuilds the Verilator binary when the exported Verilog or harness changes,
4. runs the compiled binary against the normal `vmlinux` image.

The current default is single-threaded simulation because this harness currently runs faster that way than with wider Verilator threading on the common Linux debug workload.

### Useful Environment Overrides

The wrapper is configured through environment variables:

| Variable | Default | Meaning |
|---|---|---|
| `LITTLE64_VERILATOR_MAX_CYCLES` | `200000000` | Maximum simulated cycles before timing out |
| `LITTLE64_VERILATOR_THREADS` | `1` | Verilator simulation thread count |
| `LITTLE64_VERILATOR_BUILD_JOBS` | host CPU count | Parallelism for compiling the generated C++ model |
| `LITTLE64_VERILATOR_CFLAGS` | `-O3 -std=c++20 -march=native -flto -DNDEBUG` | Extra C++ compile flags for the harness build |
| `LITTLE64_VERILATOR_LDFLAGS` | `-O3 -march=native -flto` | Link flags for the harness build |
| `LITTLE64_VERILATOR_DEBUG_TRACE` | unset | Enables the harness' recent execute-trace capture in failure diagnostics |

Typical examples:

```bash
# Quick timing/sample run
LITTLE64_VERILATOR_MAX_CYCLES=1000000 \
	./.venv/bin/python hdl/tools/run_verilator_linux_boot_smoke.py

# Force a clean single-thread debug run with verbose failure trace capture
LITTLE64_VERILATOR_THREADS=1 \
LITTLE64_VERILATOR_DEBUG_TRACE=1 \
LITTLE64_VERILATOR_MAX_CYCLES=500000 \
	./.venv/bin/python hdl/tools/run_verilator_linux_boot_smoke.py
```

### Success And Failure Contract

The wrapper treats the smoke as successful only after the UART output contains all of these markers:

- `little64-timer: clocksource + clockevent @ 1 GHz`
- `Little64 PV block disk:`
- `Kernel panic - not syncing: VFS: Unable to mount root fs`

The root-mount failure is intentional here. This smoke is validating that the HDL core gets far enough into Linux boot to enumerate the timer and PV block device and then reaches the expected no-rootfs panic path.

During the run, UART bytes are streamed to stdout as they are produced by the guest. The harness also keeps an internal copy of the serial stream so it can keep searching for required markers and print a recent serial tail in failure diagnostics.

On success, the harness exits `0` once all required markers have been observed.

On failure, it exits `1` and prints a summary like:

```text
Verilator Linux boot smoke failed: cycles=1000000 timed_out=1 locked_up=0 halted=0 invalid_pc=0 zero_instruction=0
state=2 current_instruction=0x830c fetch_pc=0xffffffc0004dd306 fetch_phys_addr=0x5dd308 commit_valid=0 commit_pc=0xffffffc0004dd306
serial_tail:
0
B
P
```

Important failure bits:

- `timed_out=1`: hit the cycle cap before the required markers appeared,
- `locked_up=1`: architectural lockup,
- `halted=1`: core executed a halt/stop state,
- `invalid_pc=1`: fetch escaped the valid RAM/image window,
- `zero_instruction=1`: execution reached a zero-filled region, which is usually a useful early indicator of bad control flow.

### Timing And Progress Expectations

For the current single-threaded harness on the normal `vmlinux` image, `1000000` cycles is enough to see only early breadcrumb UART output such as `0`, `B`, and `P`. It is useful for rough performance estimates, not for reaching the later smoke markers.

If you need a quick throughput sample:

```bash
/usr/bin/time -f 'elapsed=%e user=%U sys=%S' \
	env LITTLE64_VERILATOR_MAX_CYCLES=1000000 \
	./.venv/bin/python hdl/tools/run_verilator_linux_boot_smoke.py
```

For deeper Linux bring-up work, raise `LITTLE64_VERILATOR_MAX_CYCLES` substantially.

### Direct Binary Mode

For timing experiments or when iterating on harness behavior, it is sometimes more useful to run the compiled binary directly after the wrapper has built it:

```bash
builddir/hdl-verilator-linux-boot/obj/little64_linux_boot_smoke_t1 \
	--kernel target/linux_port/build/vmlinux \
	--dtb builddir/hdl-verilator-linux-boot/little64.dtb \
	--max-cycles 1000000 \
	--require 'little64-timer: clocksource + clockevent @ 1 GHz' \
	--require 'Little64 PV block disk:' \
	--require 'Kernel panic - not syncing: VFS: Unable to mount root fs'
```

Direct mode avoids the Python wrapper overhead and makes it easier to benchmark different cycle caps or thread-count builds. The current binary accepts only:

- `--kernel <path>`
- `--dtb <path>`
- `--max-cycles <n>`
- repeated `--require <substring>`

### Meson Integration

The HDL smoke is also wired into the optional HDL Meson subtree as `hdl-linux-boot-smoke`:

```bash
meson test -C builddir-hdl hdl-linux-boot-smoke --print-errorlogs
```

That test simply invokes `hdl/tools/run_verilator_linux_boot_smoke.py`, so the same prerequisites and environment variables apply.

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
